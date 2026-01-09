from __future__ import annotations

import os
import io
import json
import time
import struct
import zlib
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Iterator, Tuple, List

import zstandard as zstd


# ============================================================
# Constants / Layout
# ============================================================

MAGIC = b"PY1CDB"  # 6 bytes
VERSION = 1

HEADER_SIZE = 128

# Page types
PT_META = 1
PT_DATA = 2
PT_INDEX = 3

# Compression types
CT_NONE = 0
CT_ZSTD = 1

# WAL record types
WAL_BEGIN = 1
WAL_PUT_PAGE = 2
WAL_SET_META = 3
WAL_COMMIT = 4
WAL_ABORT = 5
WAL_CHECKPOINT = 6

# Meta keys inside META JSON
META_ROOT = "root"
META_TABLES = "tables"
META_NEXT_PAGE_ID = "next_page_id"
META_FREE_PAGES = "free_pages"
META_INDEXES = "indexes"
META_STRINGS = "strings"
META_NEXT_STR_ID = "next_str_id"
META_WAL = "wal"  # wal pointers


def _crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class Stats:
    file_size: int
    page_size: int
    pages_total: int
    pages_used: int
    wal_size: int
    cache_capacity_pages: int
    cache_items: int
    cache_hits: int
    cache_misses: int
    compression: str


# ============================================================
# Page Encoding
# ============================================================

# Page slot layout inside file:
# [PAGE_SLOT] size = page_size
#   PageHeader (22 bytes) + payload area
#
# PageHeader:
#   page_id: u64
#   page_type: u8
#   comp_type: u8
#   comp_size: u32
#   orig_size: u32
#   checksum: u32 (CRC32 of ORIGINAL bytes)
#
PAGE_HDR_STRUCT = struct.Struct("<QBBIII")  # 8 +1+1+4+4+4 = 22
PAGE_HDR_SIZE = PAGE_HDR_STRUCT.size


def pack_page_slot(
    page_size: int,
    page_id: int,
    page_type: int,
    comp_type: int,
    original: bytes,
    compressor: "AdaptiveCompressor",
) -> bytes:
    if comp_type == CT_ZSTD:
        compressed = compressor.compress(original)
    else:
        compressed = original

    comp_size = len(compressed)
    orig_size = len(original)

    if PAGE_HDR_SIZE + comp_size > page_size:
        raise ValueError(f"Payload too large for page (need {PAGE_HDR_SIZE + comp_size}, have {page_size})")

    checksum = _crc32(original)
    hdr = PAGE_HDR_STRUCT.pack(page_id, page_type, comp_type, comp_size, orig_size, checksum)

    slot = hdr + compressed
    # pad to full page size
    if len(slot) < page_size:
        slot += b"\x00" * (page_size - len(slot))
    return slot


def unpack_page_slot(page_size: int, slot: bytes, compressor: "AdaptiveCompressor") -> Tuple[int, int, int, bytes]:
    if len(slot) != page_size:
        raise ValueError("Invalid page slot length")

    page_id, page_type, comp_type, comp_size, orig_size, checksum = PAGE_HDR_STRUCT.unpack_from(slot, 0)
    if page_id == 0:
        # empty slot
        return 0, 0, 0, b""

    payload = slot[PAGE_HDR_SIZE: PAGE_HDR_SIZE + comp_size]
    if comp_type == CT_ZSTD:
        original = compressor.decompress(payload, orig_size)
    else:
        original = payload

    if _crc32(original) != checksum:
        raise IOError(f"Page CRC mismatch page_id={page_id}")

    return page_id, page_type, comp_type, original


# ============================================================
# Adaptive Compression (MVP)
# ============================================================

class AdaptiveCompressor:
    """
    MVP: ZSTD always, with small heuristics.
    Later: detect structured/text/numerical, dictionary training, delta codecs, etc.
    """

    def __init__(self, level: int = 19):
        self.level = int(level)
        self._cctx = zstd.ZstdCompressor(level=self.level)
        self._dctx = zstd.ZstdDecompressor()

    def compress(self, data: bytes) -> bytes:
        # Heuristic: very small payloads don't compress well, but requirement says "compress all pages".
        # We'll still compress; ZSTD handles small inputs acceptably.
        return self._cctx.compress(data)

    def decompress(self, data: bytes, orig_size: int) -> bytes:
        return self._dctx.decompress(data, max_output_size=orig_size)


# ============================================================
# LRU Cache (pages)
# ============================================================

class LRUCache:
    def __init__(self, capacity: int):
        self.capacity = max(16, int(capacity))
        self._lock = threading.RLock()
        self._dict: Dict[int, bytes] = {}
        self._order: List[int] = []  # MRU at end
        self.hits = 0
        self.misses = 0

    def get(self, key: int) -> Optional[bytes]:
        with self._lock:
            if key in self._dict:
                self.hits += 1
                # bump
                try:
                    self._order.remove(key)
                except ValueError:
                    pass
                self._order.append(key)
                return self._dict[key]
            self.misses += 1
            return None

    def put(self, key: int, value: bytes) -> None:
        with self._lock:
            if key in self._dict:
                self._dict[key] = value
                try:
                    self._order.remove(key)
                except ValueError:
                    pass
                self._order.append(key)
                return

            self._dict[key] = value
            self._order.append(key)

            while len(self._dict) > self.capacity:
                old = self._order.pop(0)
                self._dict.pop(old, None)

    def clear(self) -> None:
        with self._lock:
            self._dict.clear()
            self._order.clear()

    @property
    def size(self) -> int:
        return len(self._dict)


# ============================================================
# WAL (inside same file)
# ============================================================

# WAL record header:
#   rec_type: u8
#   txid: u64
#   length: u32
#   crc32: u32 (crc of payload)
WAL_HDR = struct.Struct("<BQII")  # 1 +8 +4 +4 = 17


def _wal_pack(rec_type: int, txid: int, payload: bytes) -> bytes:
    crc = _crc32(payload)
    hdr = WAL_HDR.pack(rec_type, txid, len(payload), crc)
    return hdr + payload


def _wal_iter(f: io.BufferedRandom, start: int, end: int) -> Iterator[Tuple[int, int, bytes]]:
    pos = start
    while pos + WAL_HDR.size <= end:
        f.seek(pos)
        raw = f.read(WAL_HDR.size)
        if len(raw) != WAL_HDR.size:
            return
        rec_type, txid, length, crc = WAL_HDR.unpack(raw)
        if rec_type == 0 and txid == 0 and length == 0 and crc == 0:
            return
        payload = f.read(length)
        if len(payload) != length:
            return
        if _crc32(payload) != crc:
            # stop at first corruption
            return
        yield rec_type, txid, payload
        pos += WAL_HDR.size + length


# ============================================================
# mpdb core
# ============================================================

class MpdbError(Exception):
    pass


class Mpdb:
    """
    One-file mpdb (MVP):
    - fixed-size page slots
    - ZSTD compression of page payload
    - metadata stored in META page(s)
    - WAL region inside same file (append-only)
    - crash recovery replays committed WAL transactions
    """

    def __init__(
        self,
        path: str | Path,
        *,
        page_size: int = 16384,
        compression: str = "zstd:19",
        cache_mb: int = 64,
    ):
        self.path = Path(path)
        self._lock = threading.RLock()

        # compression
        algo, level = self._parse_compression(compression)
        if algo != "zstd":
            raise MpdbError("MVP supports zstd only")
        self._compressor = AdaptiveCompressor(level=level)
        self._comp_type = CT_ZSTD

        # page size sanity
        if page_size < 4096 or page_size > 65536 or (page_size % 4096 != 0):
            raise MpdbError("page_size must be 4096..65536 and multiple of 4096")
        self.page_size = int(page_size)

        # cache
        cap_pages = max(32, int((cache_mb * 1024 * 1024) // self.page_size))
        self._cache = LRUCache(capacity=cap_pages)

        self._file: Optional[io.BufferedRandom] = None
        self._meta: Dict[str, Any] = {}
        self._opened = False

        # WAL pointers
        self._wal_start = 0
        self._wal_end = 0

        self._open_or_create()
        self.recover()

    # ------------------------- public API -------------------------

    def close(self) -> None:
        with self._lock:
            if self._file:
                self._file.flush()
                self._file.close()
            self._file = None
            self._opened = False
            self._cache.clear()

    def create_table(self, name: str, schema: Dict[str, Any]) -> None:
        with self.transaction() as tx:
            tables = self._meta[META_TABLES]
            if name in tables:
                raise MpdbError(f"Table exists: {name}")
            tables[name] = {
                "schema": schema,
                "data_pages": [],   # list of page_ids (append-only)
                "versioned": False,
            }
            # simple indexes definition
            indexes = self._meta[META_INDEXES]
            indexes.setdefault(name, {})  # field -> dict
            tx.set_meta(self._meta)

    def table(self, name: str) -> "Table":
        with self._lock:
            if name not in self._meta[META_TABLES]:
                raise MpdbError(f"No such table: {name}")
        return Table(self, name)

    def query(self, table: str, where: Optional[Dict[str, Any]] = None, *, order_by: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.table(table).select(where=where, order_by=order_by)

    def compact(self) -> None:
        """
        MVP compaction: rewrite WAL checkpoint marker and truncate WAL region.
        Full defrag/page reuse can be added later.
        """
        with self.transaction() as tx:
            tx.checkpoint()

    def verify_integrity(self) -> None:
        # Verify header + meta page CRC via normal reads; verify all referenced pages
        with self._lock:
            self._read_header()
            meta = self._load_meta()
            tables = meta.get(META_TABLES, {})
            for tname, tinfo in tables.items():
                for pid in tinfo.get("data_pages", []):
                    _ = self._read_page(pid)  # will CRC-check

    def get_statistics(self) -> Stats:
        with self._lock:
            f = self._require_file()
            f.flush()
            size = self.path.stat().st_size
            pages_total = max(0, (self._wal_start - HEADER_SIZE) // self.page_size)
            used = pages_total - len(self._meta.get(META_FREE_PAGES, []))
            wal_size = max(0, self._wal_end - self._wal_start)
            return Stats(
                file_size=size,
                page_size=self.page_size,
                pages_total=pages_total,
                pages_used=used,
                wal_size=wal_size,
                cache_capacity_pages=self._cache.capacity,
                cache_items=self._cache.size,
                cache_hits=self._cache.hits,
                cache_misses=self._cache.misses,
                compression=f"zstd:{self._compressor.level}",
            )

    # ------------------------- transactions -------------------------

    def transaction(self) -> "Transaction":
        return Transaction(self)

    # ============================================================
    # internals
    # ============================================================

    def _parse_compression(self, s: str) -> Tuple[str, int]:
        s = (s or "").strip().lower()
        if s.startswith("zstd"):
            if ":" in s:
                _, lvl = s.split(":", 1)
                return "zstd", int(lvl)
            return "zstd", 19
        raise MpdbError("Unsupported compression string")

    def _open_or_create(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        exists = self.path.exists()
        f = open(self.path, "r+b" if exists else "w+b", buffering=0)
        self._file = io.BufferedRandom(f)
        if not exists or self.path.stat().st_size < HEADER_SIZE:
            self._init_new_file()
        else:
            self._read_header()
            self._meta = self._load_meta()
            self._wal_start = int(self._meta[META_WAL]["start"])
            self._wal_end = int(self._meta[META_WAL]["end"])
        self._opened = True

    def _init_new_file(self) -> None:
        # Create empty header + first META page + WAL pointers
        self._meta = {
            META_ROOT: 1,  # meta page id
            META_TABLES: {},
            META_INDEXES: {},
            META_NEXT_PAGE_ID: 2,  # 1 reserved for meta
            META_FREE_PAGES: [],
            META_STRINGS: {},      # str -> id
            META_NEXT_STR_ID: 1,
            META_WAL: {
                "start": HEADER_SIZE + self.page_size * 1,  # after page area (currently 1 page)
                "end": HEADER_SIZE + self.page_size * 1,
            }
        }

        # write header placeholder
        self._write_header()

        # write meta page
        self._write_page(1, PT_META, self._encode_meta(self._meta))

        # set WAL start/end after current pages
        self._wal_start = HEADER_SIZE + self.page_size * 1
        self._wal_end = self._wal_start
        self._meta[META_WAL]["start"] = self._wal_start
        self._meta[META_WAL]["end"] = self._wal_end

        # rewrite meta + header with correct pointers
        self._write_page(1, PT_META, self._encode_meta(self._meta))
        self._write_header()

    # --------------------- header ---------------------

    # HEADER layout (128 bytes):
    # magic(6) + ver(u16) + page_size(u32) + comp(u8) + enc(u8) + reserved(??) + crc32(u32 at end)
    # We'll keep simple:
    #   0..5  magic
    #   6..7  ver u16
    #   8..11 page_size u32
    #   12    comp u8
    #   13    enc u8 (0)
    #   14..123 reserved
    #   124..127 crc32 of bytes 0..123
    def _write_header(self) -> None:
        f = self._require_file()
        buf = bytearray(HEADER_SIZE)
        buf[0:6] = MAGIC
        struct.pack_into("<H", buf, 6, VERSION)
        struct.pack_into("<I", buf, 8, self.page_size)
        struct.pack_into("<B", buf, 12, self._comp_type)
        struct.pack_into("<B", buf, 13, 0)
        # reserved: could include meta root page id, etc. but we store root in meta page.
        crc = _crc32(bytes(buf[0:124]))
        struct.pack_into("<I", buf, 124, crc)
        f.seek(0)
        f.write(buf)
        f.flush()

    def _read_header(self) -> None:
        f = self._require_file()
        f.seek(0)
        buf = f.read(HEADER_SIZE)
        if len(buf) != HEADER_SIZE:
            raise MpdbError("Bad header size")
        if buf[0:6] != MAGIC:
            raise MpdbError("Bad magic")
        ver = struct.unpack_from("<H", buf, 6)[0]
        if ver != VERSION:
            raise MpdbError(f"Unsupported version: {ver}")
        page_size = struct.unpack_from("<I", buf, 8)[0]
        comp = buf[12]
        crc = struct.unpack_from("<I", buf, 124)[0]
        if _crc32(buf[0:124]) != crc:
            raise MpdbError("Header CRC mismatch")
        if page_size != self.page_size:
            # allow opening existing db with its own page_size
            self.page_size = int(page_size)
        if comp != CT_ZSTD:
            raise MpdbError("MVP expects ZSTD pages")

    # --------------------- meta ---------------------

    def _encode_meta(self, meta: Dict[str, Any]) -> bytes:
        # JSON for MVP (zstd will compress). Later: MessagePack.
        return json.dumps(meta, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def _decode_meta(self, data: bytes) -> Dict[str, Any]:
        return json.loads(data.decode("utf-8"))

    def _load_meta(self) -> Dict[str, Any]:
        pid, ptype, _, payload = self._read_page_slot(1)
        if pid != 1 or ptype != PT_META:
            raise MpdbError("Meta page corrupted")
        meta = self._decode_meta(payload)
        # ensure fields
        meta.setdefault(META_TABLES, {})
        meta.setdefault(META_INDEXES, {})
        meta.setdefault(META_NEXT_PAGE_ID, 2)
        meta.setdefault(META_FREE_PAGES, [])
        meta.setdefault(META_STRINGS, {})
        meta.setdefault(META_NEXT_STR_ID, 1)
        meta.setdefault(META_WAL, {"start": HEADER_SIZE + self.page_size, "end": HEADER_SIZE + self.page_size})
        return meta

    # --------------------- pages ---------------------

    def _page_offset(self, page_id: int) -> int:
        # page_id starts at 1
        return HEADER_SIZE + (page_id - 1) * self.page_size

    def _read_page_slot(self, page_id: int) -> Tuple[int, int, int, bytes]:
        cached = self._cache.get(page_id)
        if cached is not None:
            pid, ptype, ctype, payload = unpack_page_slot(self.page_size, cached, self._compressor)
            return pid, ptype, ctype, payload

        f = self._require_file()
        off = self._page_offset(page_id)
        f.seek(off)
        slot = f.read(self.page_size)
        if len(slot) != self.page_size:
            raise MpdbError(f"Page read failed page_id={page_id}")
        self._cache.put(page_id, slot)
        pid, ptype, ctype, payload = unpack_page_slot(self.page_size, slot, self._compressor)
        return pid, ptype, ctype, payload

    def _read_page(self, page_id: int) -> bytes:
        pid, _, _, payload = self._read_page_slot(page_id)
        if pid != page_id:
            raise MpdbError(f"Page id mismatch {pid} != {page_id}")
        return payload

    def _write_page(self, page_id: int, page_type: int, payload: bytes) -> None:
        f = self._require_file()
        slot = pack_page_slot(self.page_size, page_id, page_type, self._comp_type, payload, self._compressor)
        off = self._page_offset(page_id)
        f.seek(off)
        f.write(slot)
        f.flush()
        self._cache.put(page_id, slot)

        # update WAL start if file grew beyond
        end_of_pages = HEADER_SIZE + (self._meta[META_NEXT_PAGE_ID] - 1) * self.page_size
        if self._wal_start < end_of_pages:
            self._wal_start = end_of_pages
            self._wal_end = max(self._wal_end, self._wal_start)
            self._meta[META_WAL]["start"] = self._wal_start
            self._meta[META_WAL]["end"] = self._wal_end

    def _alloc_page_id(self) -> int:
        free = self._meta.get(META_FREE_PAGES, [])
        if free:
            return int(free.pop())
        pid = int(self._meta[META_NEXT_PAGE_ID])
        self._meta[META_NEXT_PAGE_ID] = pid + 1
        # ensure file expanded (lazy: just seek)
        f = self._require_file()
        needed = self._page_offset(pid) + self.page_size
        f.seek(0, os.SEEK_END)
        if f.tell() < needed:
            f.seek(needed - 1)
            f.write(b"\x00")
            f.flush()
        return pid

    # --------------------- strings (dedup) MVP ---------------------

    def _intern_strings(self, obj: Any) -> Any:
        """
        Replace strings with {"$s":id} for dedup, recursively.
        """
        if isinstance(obj, str):
            sdict: Dict[str, Any] = self._meta[META_STRINGS]
            if obj in sdict:
                sid = int(sdict[obj])
            else:
                sid = int(self._meta[META_NEXT_STR_ID])
                self._meta[META_NEXT_STR_ID] = sid + 1
                sdict[obj] = sid
            return {"$s": sid}

        if isinstance(obj, list):
            return [self._intern_strings(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self._intern_strings(v) for k, v in obj.items()}
        return obj

    def _restore_strings(self, obj: Any) -> Any:
        if isinstance(obj, dict) and set(obj.keys()) == {"$s"}:
            sid = int(obj["$s"])
            # reverse lookup (MVP: O(n), later: store id->str map)
            for s, v in self._meta[META_STRINGS].items():
                if int(v) == sid:
                    return s
            return ""
        if isinstance(obj, list):
            return [self._restore_strings(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self._restore_strings(v) for k, v in obj.items()}
        return obj

    # --------------------- WAL ---------------------

    def _wal_append(self, rec_type: int, txid: int, payload: bytes) -> int:
        f = self._require_file()
        data = _wal_pack(rec_type, txid, payload)
        f.seek(self._wal_end)
        f.write(data)
        f.flush()
        pos = self._wal_end
        self._wal_end += len(data)
        self._meta[META_WAL]["end"] = self._wal_end
        return pos

    def recover(self) -> None:
        """
        Replay WAL: apply only committed txns (BEGIN..COMMIT).
        We store PUT_PAGE and SET_META in WAL; on commit we apply them.
        """
        with self._lock:
            f = self._require_file()

            # reload meta to get wal pointers
            self._meta = self._load_meta()
            self._wal_start = int(self._meta[META_WAL]["start"])
            self._wal_end = int(self._meta[META_WAL]["end"])

            # scan WAL
            tx_buf: Dict[int, Dict[str, Any]] = {}  # txid -> {"pages":[(pid,ptype,payload)], "meta":meta_json}
            committed: List[int] = []

            for rec_type, txid, payload in _wal_iter(f, self._wal_start, self._wal_end):
                if rec_type == WAL_BEGIN:
                    tx_buf[txid] = {"pages": [], "meta": None}
                elif rec_type == WAL_PUT_PAGE:
                    if txid not in tx_buf:
                        continue
                    pid, ptype = struct.unpack_from("<QI", payload, 0)  # pid u64, ptype u32
                    data = payload[12:]
                    tx_buf[txid]["pages"].append((int(pid), int(ptype), data))
                elif rec_type == WAL_SET_META:
                    if txid not in tx_buf:
                        continue
                    tx_buf[txid]["meta"] = payload
                elif rec_type == WAL_COMMIT:
                    if txid in tx_buf:
                        committed.append(txid)
                elif rec_type == WAL_ABORT:
                    tx_buf.pop(txid, None)

            # apply committed in order
            for txid in committed:
                buf = tx_buf.get(txid)
                if not buf:
                    continue
                for pid, ptype, data in buf["pages"]:
                    self._write_page(pid, ptype, data)
                if buf["meta"] is not None:
                    meta = self._decode_meta(buf["meta"])
                    self._meta = meta
                    self._write_page(1, PT_META, self._encode_meta(self._meta))
                    self._write_header()

            # After recovery, write a checkpoint marker (optional)
            # We keep WAL for now; compaction can truncate.
            self._meta = self._load_meta()

    def _require_file(self) -> io.BufferedRandom:
        if not self._file:
            raise MpdbError("Database closed")
        return self._file


# ============================================================
# Transaction
# ============================================================

class Transaction:
    def __init__(self, db: Mpdb):
        self.db = db
        self.txid = (_now_ms() << 16) ^ (id(self) & 0xFFFF)
        self._active = False
        self._pages: List[Tuple[int, int, bytes]] = []
        self._meta_bytes: Optional[bytes] = None

    def __enter__(self) -> "Transaction":
        with self.db._lock:
            self._active = True
            self.db._wal_append(WAL_BEGIN, self.txid, b"")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.abort()

    def put_page(self, page_id: int, page_type: int, payload: bytes) -> None:
        if not self._active:
            raise MpdbError("Transaction not active")
        self._pages.append((page_id, page_type, payload))

    def set_meta(self, meta: Dict[str, Any]) -> None:
        if not self._active:
            raise MpdbError("Transaction not active")
        self._meta_bytes = self.db._encode_meta(meta)

    def commit(self) -> None:
        with self.db._lock:
            if not self._active:
                return

            # write WAL records
            for pid, ptype, payload in self._pages:
                hdr = struct.pack("<QI", int(pid), int(ptype))
                self.db._wal_append(WAL_PUT_PAGE, self.txid, hdr + payload)

            if self._meta_bytes is not None:
                self.db._wal_append(WAL_SET_META, self.txid, self._meta_bytes)

            self.db._wal_append(WAL_COMMIT, self.txid, b"")

            # apply changes to main file (post-commit)
            for pid, ptype, payload in self._pages:
                self.db._write_page(pid, ptype, payload)

            if self._meta_bytes is not None:
                self.db._meta = self.db._decode_meta(self._meta_bytes)
                self.db._write_page(1, PT_META, self.db._encode_meta(self.db._meta))
                self.db._write_header()

            self._active = False

    def abort(self) -> None:
        with self.db._lock:
            if not self._active:
                return
            self.db._wal_append(WAL_ABORT, self.txid, b"")
            self._active = False

    def checkpoint(self) -> None:
        """
        Minimal checkpoint: mark and truncate WAL (safe only if we already applied).
        """
        with self.db._lock:
            if not self._active:
                raise MpdbError("Checkpoint must be inside transaction")

            # mark
            self.db._wal_append(WAL_CHECKPOINT, self.txid, b"")

            # truncate WAL by moving start=end
            self.db._wal_start = self.db._wal_end
            self.db._meta[META_WAL]["start"] = self.db._wal_start
            self.db._meta[META_WAL]["end"] = self.db._wal_end
            self.set_meta(self.db._meta)


# ============================================================
# Table layer (row store MVP)
# ============================================================

class Table:
    def __init__(self, db: Mpdb, name: str):
        self.db = db
        self.name = name

    def insert(self, row: Dict[str, Any]) -> int:
        """
        Insert into append-only data page chain.
        Returns rowid (monotonic).
        """
        with self.db.transaction() as tx:
            tables = self.db._meta[META_TABLES]
            tinfo = tables[self.name]

            rowid = int(tinfo.get("next_rowid", 1))
            tinfo["next_rowid"] = rowid + 1

            # intern strings (dedup)
            packed_obj = {
                "rowid": rowid,
                "data": self.db._intern_strings(row),
            }
            blob = json.dumps(packed_obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

            # append record to last page or allocate new
            pages: List[int] = tinfo["data_pages"]
            if pages:
                last_pid = pages[-1]
                payload = self.db._read_page(last_pid)
            else:
                last_pid = 0
                payload = b""

            rec = struct.pack("<I", len(blob)) + blob  # length + record bytes
            new_payload = payload + rec

            if len(new_payload) > (self.db.page_size - PAGE_HDR_SIZE - 64):
                # allocate new page
                pid = self.db._alloc_page_id()
                pages.append(pid)
                tx.put_page(pid, PT_DATA, rec)  # page starts with first record
            else:
                if last_pid == 0:
                    pid = self.db._alloc_page_id()
                    pages.append(pid)
                    tx.put_page(pid, PT_DATA, rec)
                else:
                    tx.put_page(last_pid, PT_DATA, new_payload)

            # auto index (MVP): if schema says indexed=True or unique=True
            self._maybe_update_indexes(tx, tinfo, row, rowid)

            tx.set_meta(self.db._meta)

            return rowid

    def select(self, where: Optional[Dict[str, Any]] = None, *, order_by: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.db._lock:
            tables = self.db._meta[META_TABLES]
            tinfo = tables[self.name]
            pages = list(tinfo.get("data_pages", []))

        # try index if possible
        candidate_rowids: Optional[set[int]] = None
        if where:
            candidate_rowids = self._try_index(where)

        out: List[Dict[str, Any]] = []
        for pid in pages:
            payload = self.db._read_page(pid)
            for rowid, data in _iter_records(payload):
                if candidate_rowids is not None and rowid not in candidate_rowids:
                    continue
                # restore strings
                restored = self.db._restore_strings(data)
                if where and not _match(restored, where):
                    continue
                out.append(restored)

        if order_by:
            out.sort(key=lambda x: x.get(order_by))
        return out

    def _maybe_update_indexes(self, tx: Transaction, tinfo: Dict[str, Any], row: Dict[str, Any], rowid: int) -> None:
        schema = tinfo.get("schema", {})
        idx_def = self.db._meta[META_INDEXES].setdefault(self.name, {})
        for field, opts in schema.items():
            if isinstance(opts, dict) and (opts.get("indexed") or opts.get("unique")):
                idx = idx_def.setdefault(field, {})  # value -> list[rowid]
                val = row.get(field)
                if val is None:
                    continue
                key = json.dumps(val, ensure_ascii=False, separators=(",", ":"))
                bucket = idx.setdefault(key, [])
                if opts.get("unique") and bucket:
                    raise MpdbError(f"Unique constraint failed: {self.name}.{field}={val}")
                bucket.append(int(rowid))
        # indexes stored in meta; persisted via tx.set_meta(self.db._meta)

    def _try_index(self, where: Dict[str, Any]) -> Optional[set[int]]:
        with self.db._lock:
            idx_def = self.db._meta.get(META_INDEXES, {}).get(self.name, {})
            # pick first available indexed field in where
            for k, v in where.items():
                idx = idx_def.get(k)
                if not idx:
                    continue
                key = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
                rowids = idx.get(key)
                if rowids:
                    return set(map(int, rowids))
                return set()
        return None


def _iter_records(payload: bytes) -> Iterator[Tuple[int, Dict[str, Any]]]:
    """
    Records: [u32 len][json bytes]...
    """
    p = 0
    n = len(payload)
    while p + 4 <= n:
        (ln,) = struct.unpack_from("<I", payload, p)
        p += 4
        if ln <= 0 or p + ln > n:
            return
        raw = payload[p:p+ln]
        p += ln
        obj = json.loads(raw.decode("utf-8"))
        rowid = int(obj.get("rowid", 0))
        data = obj.get("data", {})
        yield rowid, data


def _match(row: Dict[str, Any], where: Dict[str, Any]) -> bool:
    for k, v in where.items():
        if row.get(k) != v:
            return False
    return True
