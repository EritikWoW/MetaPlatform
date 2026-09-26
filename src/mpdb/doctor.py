from __future__ import annotations

import io
import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .mpdb import (
    MAGIC,
    VERSION,
    FORMAT_REV,
    HEADER_SIZE,
    CT_LZMA,
    CT_ZLIB,
    CT_ZSTD,
    META_NEXT_PAGE_ID,
    META_WAL,
    _crc32,
    AdaptiveCompressor,
    unpack_page_slot,
)
from .migrations import ensure_supported_format_rev
from .wal import iter_records as wal_iter_records


@dataclass
class DoctorIssue:
    code: str
    message: str
    page_id: Optional[int] = None


@dataclass
class DoctorReport:
    path: str
    ok: bool
    file_size: int
    page_size: int
    format_major: int
    format_rev: int
    comp_type: int
    pages_total: int
    pages_checked: int
    pages_bad: int
    wal_records_ok: int
    issues: List[DoctorIssue]


def _read_header_only(f: io.BufferedReader) -> Tuple[int, int, int, int]:
    """Return (format_major, format_rev, page_size, comp_type)."""
    f.seek(0)
    buf = f.read(HEADER_SIZE)
    if len(buf) != HEADER_SIZE:
        raise ValueError("Bad header size")
    if buf[0:6] != MAGIC:
        raise ValueError("Bad magic")
    ver = struct.unpack_from("<H", buf, 6)[0]
    if ver != VERSION:
        raise ValueError(f"Unsupported version: {ver}")
    page_size = struct.unpack_from("<I", buf, 8)[0]
    comp = int(buf[12])
    fmt_rev = struct.unpack_from("<H", buf, 14)[0]
    crc = struct.unpack_from("<I", buf, 124)[0]
    if _crc32(buf[0:124]) != crc:
        raise ValueError("Header CRC mismatch")
    ensure_supported_format_rev(int(fmt_rev), current_rev=int(FORMAT_REV))
    if comp not in (CT_ZSTD, CT_ZLIB, CT_LZMA):
        raise ValueError("Unsupported page compression in file header")
    return int(ver), int(fmt_rev), int(page_size), int(comp)


def check(path: str | Path, *, max_pages: Optional[int] = None) -> DoctorReport:
    """Offline integrity check.

    The checker is intentionally conservative:
    - It never writes to the file.
    - It stops WAL scanning at first sign of corruption (same rule as recovery).
    """
    p = Path(path)
    issues: List[DoctorIssue] = []

    if not p.exists():
        return DoctorReport(
            path=str(p),
            ok=False,
            file_size=0,
            page_size=0,
            format_major=0,
            format_rev=0,
            comp_type=0,
            pages_total=0,
            pages_checked=0,
            pages_bad=0,
            wal_records_ok=0,
            issues=[DoctorIssue("FILE_MISSING", "Database file does not exist")],
        )

    file_size = int(p.stat().st_size)
    with open(p, "rb", buffering=0) as raw:
        f = io.BufferedReader(raw)
        try:
            fmt_major, fmt_rev, page_size, comp_type = _read_header_only(f)
        except Exception as e:
            return DoctorReport(
                path=str(p),
                ok=False,
                file_size=file_size,
                page_size=0,
                format_major=0,
                format_rev=0,
                comp_type=0,
                pages_total=0,
                pages_checked=0,
                pages_bad=0,
                wal_records_ok=0,
                issues=[DoctorIssue("HEADER", str(e))],
            )

        if comp_type == CT_ZSTD:
            compressor = AdaptiveCompressor(algo="zstd", level=19)
        elif comp_type == CT_LZMA:
            compressor = AdaptiveCompressor(algo="lzma", level=9)
        else:
            compressor = AdaptiveCompressor(algo="zlib", level=19)

        # Read and validate META page (page_id=1)
        try:
            off = HEADER_SIZE + (1 - 1) * page_size
            f.seek(off)
            slot = f.read(page_size)
            if len(slot) != page_size:
                raise ValueError("Meta page read failed")
            pid, ptype, _ctype, payload, _lsn = unpack_page_slot(page_size, slot, compressor)
            if pid != 1:
                raise ValueError(f"Meta page id mismatch: {pid}")
            meta: Dict[str, Any] = json.loads(payload.decode("utf-8"))
        except Exception as e:
            issues.append(DoctorIssue("META", f"Meta page corrupted: {e}", page_id=1))
            meta = {}

        next_pid = int(meta.get(META_NEXT_PAGE_ID, 1) or 1)
        wal = meta.get(META_WAL, {}) if isinstance(meta.get(META_WAL, {}), dict) else {}
        wal_start = int(wal.get("start", 0) or 0)
        wal_end = int(wal.get("end", 0) or 0)
        if wal_start and wal_end and wal_end < wal_start:
            issues.append(DoctorIssue("WAL_PTR", "WAL end < WAL start"))

        pages_total = max(0, next_pid - 1)
        if max_pages is not None:
            pages_total = min(pages_total, int(max_pages))

        pages_bad = 0
        pages_checked = 0

        for page_id in range(1, pages_total + 1):
            pages_checked += 1
            try:
                off = HEADER_SIZE + (page_id - 1) * page_size
                f.seek(off)
                slot = f.read(page_size)
                if len(slot) != page_size:
                    raise ValueError("Short read")
                pid, _ptype, _ctype, _payload, _lsn = unpack_page_slot(page_size, slot, compressor)
                if pid != page_id:
                    raise ValueError(f"Page id mismatch: {pid}")
            except Exception as e:
                pages_bad += 1
                issues.append(DoctorIssue("PAGE", f"Bad page: {e}", page_id=page_id))

        wal_records_ok = 0
        if wal_start and wal_end and wal_end <= file_size:
            try:
                for _rtype, _txid, _payload in wal_iter_records(f, wal_start, wal_end):
                    wal_records_ok += 1
            except Exception as e:
                issues.append(DoctorIssue("WAL", f"WAL scan failed: {e}"))

        ok = (len(issues) == 0)
        return DoctorReport(
            path=str(p),
            ok=ok,
            file_size=file_size,
            page_size=page_size,
            format_major=fmt_major,
            format_rev=fmt_rev,
            comp_type=comp_type,
            pages_total=pages_total,
            pages_checked=pages_checked,
            pages_bad=pages_bad,
            wal_records_ok=wal_records_ok,
            issues=issues,
        )
