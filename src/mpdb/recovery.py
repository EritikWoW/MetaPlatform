from __future__ import annotations

import struct
from typing import Any, Dict, List, Optional, Protocol

from .wal import iter_records, unpack_relocate_intent


class MpdbForRecovery(Protocol):
    """A minimal protocol for Mpdb used by recovery to avoid circular imports."""

    _lock: Any
    path: Any
    _meta: Dict[str, Any]
    _wal_start: int
    _wal_end: int
    page_size: int

    def _require_file(self): ...
    def _load_meta(self) -> Dict[str, Any]: ...
    def _decode_meta(self, data: bytes) -> Dict[str, Any]: ...
    def _encode_meta(self, meta: Dict[str, Any]) -> bytes: ...
    def _write_page(self, page_id: int, page_type: int, payload: bytes, *, lsn: Optional[int] = None) -> None: ...
    def _write_header(self) -> None: ...


HEADER_SIZE = 128


def _recover_relocated_wal_range(
    db: MpdbForRecovery,
    *,
    meta_wal_start: int,
    end_of_pages: int,
    file_end: int,
    WAL_RELOCATE_INTENT: int,
) -> Optional[tuple[int, int]]:
    """Find a relocated WAL stream after pages when META still points to the old range."""
    if meta_wal_start >= end_of_pages or end_of_pages >= file_end:
        return None

    saw_records = False
    saw_matching_intent = False
    for rec_type, _txid, payload in iter_records(db._require_file(), end_of_pages, file_end):
        saw_records = True
        if rec_type != WAL_RELOCATE_INTENT:
            continue
        try:
            old_start, _old_end, new_start, _new_end = unpack_relocate_intent(payload)
        except Exception:
            continue
        if int(old_start) == int(meta_wal_start) and int(new_start) == int(end_of_pages):
            saw_matching_intent = True

    if saw_records and saw_matching_intent:
        # Safe to return the whole tail here: ``file_end`` is only a scan bound,
        # not a promise that every trailing byte belongs to WAL. ``iter_records``
        # validates MPWL magic and per-record CRC and stops at the first invalid
        # record, so zero-filled padding, stale bytes, or any non-WAL tail after
        # the relocated stream are ignored during replay.
        return int(end_of_pages), int(file_end)
    return None


def recover_db(db: MpdbForRecovery, *, PT_META: int, META_WAL: str, WAL_BEGIN: int, WAL_PUT_PAGE: int,
              WAL_SET_META: int, WAL_COMMIT: int, WAL_ABORT: int, WAL_RELOCATE_INTENT: int) -> None:
    """Replay WAL and apply only committed transactions.

    This function is intentionally conservative:
    - stops at the first sign of WAL corruption (handled by iter_records)
    - applies only BEGIN..COMMIT sequences

    Parameters PT_META/META_WAL/WAL_* are passed in to keep this module decoupled
    from mpdb.mpdb constant definitions.
    """

    with db._lock:
        f = db._require_file()

        db._meta = db._load_meta()
        meta_wal_start = int(db._meta[META_WAL]["start"])
        meta_end = int(db._meta[META_WAL]["end"])
        end_of_pages = HEADER_SIZE + (int(db._meta["next_page_id"]) - 1) * int(db.page_size)

        file_end = int(db.path.stat().st_size)
        recovered_wal = _recover_relocated_wal_range(
            db,
            meta_wal_start=meta_wal_start,
            end_of_pages=int(end_of_pages),
            file_end=int(file_end),
            WAL_RELOCATE_INTENT=WAL_RELOCATE_INTENT,
        )
        if recovered_wal is not None:
            db._wal_start, db._wal_end = recovered_wal
            db._meta.setdefault(META_WAL, {})
            db._meta[META_WAL]["start"] = int(db._wal_start)
            db._meta[META_WAL]["end"] = int(db._wal_end)
        else:
            db._wal_start = int(meta_wal_start)
            db._wal_end = max(meta_end, file_end)

        tx_buf: Dict[int, Dict[str, Any]] = {}
        committed: List[int] = []

        for rec_type, txid, payload in iter_records(f, db._wal_start, db._wal_end):
            if rec_type == WAL_BEGIN:
                tx_buf[txid] = {"pages": [], "meta": None}

            elif rec_type == WAL_PUT_PAGE:
                buf = tx_buf.get(txid)
                if not buf:
                    continue
                pid, ptype = struct.unpack_from("<QI", payload, 0)
                data = payload[12:]
                buf["pages"].append((int(pid), int(ptype), data))

            elif rec_type == WAL_SET_META:
                buf = tx_buf.get(txid)
                if not buf:
                    continue
                buf["meta"] = payload

            elif rec_type == WAL_COMMIT:
                if txid in tx_buf:
                    committed.append(txid)

            elif rec_type == WAL_ABORT:
                tx_buf.pop(txid, None)

        for txid in committed:
            buf = tx_buf.get(txid)
            if not buf:
                continue

            for pid, ptype, data in buf["pages"]:
                db._write_page(pid, ptype, data)

            if buf["meta"] is not None:
                meta = db._decode_meta(buf["meta"])
                db._meta = meta
                db._write_page(1, PT_META, db._encode_meta(db._meta))
                db._write_header()

        db._meta = db._load_meta()
        if recovered_wal is not None:
            wal = db._meta.setdefault(META_WAL, {})
            if int(wal.get("start") or 0) != int(recovered_wal[0]) or int(wal.get("end") or 0) != int(recovered_wal[1]):
                wal["start"] = int(recovered_wal[0])
                wal["end"] = int(recovered_wal[1])
                db._write_page(1, PT_META, db._encode_meta(db._meta))
                db._write_header()
                db._meta = db._load_meta()
