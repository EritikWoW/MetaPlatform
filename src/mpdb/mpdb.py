from __future__ import annotations

# String interning (string pool) replaces repeated strings in rows with small ids.
# It stores the global dictionary in META. For large imports (many unique strings like file paths)
# this can bloat the META page and break commits (META must fit into one page).
#
# For reliability (and to unblock 1C/BAS imports), it is disabled by default.
ENABLE_STRING_INTERNING = False

import uuid

import os
import io
import json
import tempfile
import time
import struct
import lzma
import zlib
import threading
import bisect
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Iterator, Tuple, List, Protocol, Union

try:
    import zstandard as zstd  # type: ignore
    _HAS_ZSTD = True
except Exception:  # pragma: no cover
    zstd = None  # type: ignore
    _HAS_ZSTD = False


from .wal import (
    pack_record as wal_pack_record,
    pack_relocate_intent as wal_pack_relocate_intent,
    iter_records as wal_iter_records,
    WAL_MAGIC,
    WAL_VER,
    WAL_HDR_V1,
    WAL_HDR_V2,
)
from .recovery import recover_db
from .migrations import ensure_supported_format_rev, migrate_meta_to_format
# ============================================================
# Constants / Layout
# ============================================================

MAGIC = b"PY1CDB"  # 6 bytes (historical)

# File format major version. Changing this value breaks compatibility.
VERSION = 1

# File format revision (minor, backward-compatible within VERSION).
# Any on-disk format change MUST bump this and provide a migration path.
FORMAT_REV = 4

HEADER_SIZE = 128

# Page types
PT_META = 1
PT_DATA = 2
PT_INDEX = 3
PT_BLOB = 10
PT_FREELIST = 12  # internal allocator pages (free page stack)


# Compression types
CT_NONE = 0
CT_ZSTD = 1
CT_ZLIB = 2
CT_LZMA = 3

# Legacy compression type values (older mpdb builds stored different IDs).
# Keep them for backward compatibility when opening existing *.mpdb files.
CT_ZSTD_LEGACY = 50
CT_ZLIB_LEGACY = 51


def _normalize_comp_type(comp_type: int) -> int:
    """Map legacy compression ids to the current constants."""
    if int(comp_type) == CT_ZSTD_LEGACY:
        return CT_ZSTD
    if int(comp_type) == CT_ZLIB_LEGACY:
        return CT_ZLIB
    return int(comp_type)

# WAL record types
WAL_BEGIN = 1
WAL_PUT_PAGE = 2
WAL_SET_META = 3
WAL_COMMIT = 4
WAL_ABORT = 5
WAL_CHECKPOINT = 6
WAL_RELOCATE_INTENT = 7

# Meta keys inside META JSON
META_ROOT = "root"
META_TABLES = "tables"
META_NEXT_PAGE_ID = "next_page_id"
META_FREE_PAGES = "free_pages"
META_FREELIST = "freelist"  # {head:int, count:int}
META_INDEXES = "indexes"
META_STRINGS = "strings"
META_NEXT_STR_ID = "next_str_id"
META_ASSETS = "assets"  # key -> {first_page:int, size:int, mime:str}

# New backend for assets index to avoid META bloat (see put_asset/put_assets_bulk).
ASSETS_TABLE = "__assets"
META_ASSETS_BACKEND = "assets_backend"  # informational: 'meta' | 'table'
TABLE_SCHEMA_ASSET_PREFIX = "__ts/"
TABLE_SCHEMA_ASSET_MIME = "application/vnd.mpdb.table-schema+json"

# Transparent envelope for compressible assets stored as PT_BLOB chains.
# Raw/binary assets stay unwrapped. Text/JSON/XML assets get wrapped so they
# can be restored losslessly while keeping the on-disk footprint small.
ASSET_ENVELOPE_MAGIC = b"MPAC"
ASSET_ENVELOPE_VER = 1
ASSET_ENVELOPE_STRUCT = struct.Struct("<4sBBHII")

TABLE_INFO_META_ALIASES = {
    "data_pages": "p",
    "next_rowid": "n",
    "schema": "c",
    "schema_ref": "s",
    "rowid_index_root": "r",
    "versioned": "v",
}
TABLE_INFO_META_ALIAS_TO_KEY = {v: k for k, v in TABLE_INFO_META_ALIASES.items()}


def _compress_int_ranges(values: List[int]) -> List[List[int]]:
    """Compress an ordered integer list into inclusive ranges.

    The input order is preserved. This is used for large page-id lists so META
    can stay compact without changing the in-memory representation.
    """

    seq = [int(v) for v in values]
    if not seq:
        return []

    ranges: List[List[int]] = []
    start = prev = seq[0]
    for cur in seq[1:]:
        cur = int(cur)
        if cur == prev + 1:
            prev = cur
            continue
        ranges.append([int(start), int(prev)])
        start = prev = cur
    ranges.append([int(start), int(prev)])
    return ranges


def _expand_int_ranges(value: Any) -> List[int]:
    """Expand a range-compressed integer list back into a flat list."""

    if not isinstance(value, list):
        return []

    out: List[int] = []
    for item in value:
        if isinstance(item, int):
            out.append(int(item))
            continue
        if isinstance(item, (list, tuple)) and len(item) == 2:
            try:
                start = int(item[0])
                end = int(item[1])
            except Exception:
                continue
            if end < start:
                start, end = end, start
            out.extend(range(start, end + 1))
    return out


# Auto-checkpoint policy (WAL compaction)
META_AUTOCHECKPOINT = "autocheckpoint"  # {wal_bytes:int, commits:int, keep_wal_bytes:int}

# Monotonic log sequence number (used for recovery ordering / future MVCC)
META_LSN = "lsn"

META_WAL = "wal"  # wal pointers


# -------------------- Free-list pages (allocator) --------------------
# mpdb reuses freed page ids.
#
# Legacy databases keep a JSON list META_FREE_PAGES inside META.
# To avoid META bloat, newer databases additionally maintain an on-disk
# free-list stack stored in PT_FREELIST pages.
#
# Free-list page payload layout (little-endian):
#   next_pid: u32
#   count:    u32
#   entries:  count * u32 page_ids (LIFO; last element popped first)

FREELIST_HDR = struct.Struct("<II")


def _crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


# ============================================================
# Binary sortable keys (for indexes)
# ============================================================

# Type tags (ordered). Lexicographic byte ordering is used inside the B+tree.
K_INT = 0x10
K_FLOAT = 0x20
K_STR = 0x30
K_BOOL = 0x40
K_BYTES = 0x50


def _encode_sort_key(value: Any) -> bytes:
    """Encode a scalar into a binary key with lexicographic order.

    The output bytes compare in the same order as the underlying values for
    each supported type.

    Supported types: int (signed 64-bit), float (IEEE-754), str (UTF-8),
    bool, bytes.
    """

    if isinstance(value, bool):
        return bytes([K_BOOL, 1 if value else 0])

    if isinstance(value, int):
        # 64-bit signed big-endian with sign bit flipped -> sortable.
        if value < -(1 << 63) or value > (1 << 63) - 1:
            raise ValueError("int key out of 64-bit range")
        u = (value & ((1 << 64) - 1))
        b = u.to_bytes(8, "big", signed=False)
        b0 = bytes([b[0] ^ 0x80]) + b[1:]
        return bytes([K_INT]) + b0

    if isinstance(value, float):
        # IEEE-754 sortable encoding (flip sign for negatives, flip top bit for positives).
        raw = struct.pack(">d", float(value))
        first = raw[0]
        if first & 0x80:  # negative
            adj = bytes([b ^ 0xFF for b in raw])
        else:  # positive
            adj = bytes([first ^ 0x80]) + raw[1:]
        return bytes([K_FLOAT]) + adj

    if isinstance(value, (bytes, bytearray, memoryview)):
        data = bytes(value)
        return bytes([K_BYTES]) + data

    if isinstance(value, str):
        # UTF-8 bytes with 0x00 escaping and 0x00 0x00 terminator.
        out = bytearray()
        out.append(K_STR)
        for b in value.encode("utf-8"):
            if b == 0:
                out.extend((0, 0xFF))
            else:
                out.append(b)
        out.extend((0, 0))
        return bytes(out)

    raise TypeError(f"Unsupported index key type: {type(value)!r}")


def _decode_legacy_json_key(key: str) -> Any:
    """Decode legacy JSON scalar key strings into Python scalars."""
    try:
        return json.loads(key)
    except Exception:
        # Fallback: treat as raw string.
        return key


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


"""mpdb page-slot format.

mpdb stores fixed-size *page slots* inside the main file.

We support two on-disk slot header formats:

1) Legacy v0 (no magic, 22 bytes) for backward compatibility.
2) Current v1 (32 bytes, aligned, includes magic/version/LSN/header CRC).

The slot header is never compressed.
"""

# -------------------- Legacy v0 (backward compat) --------------------
PAGE_HDR_V0_STRUCT = struct.Struct("<QBBIII")  # 8 +1+1+4+4+4 = 22
PAGE_HDR_V0_SIZE = PAGE_HDR_V0_STRUCT.size

# -------------------- Current v1 --------------------
PAGE_SLOT_MAGIC = b"MPPG"  # mpdb Page
PAGE_SLOT_FMT_VER = 1

# 32-byte aligned header:
# magic[4], ver(u16), page_type(u8), comp_type(u8),
# page_id(u64), lsn(u64),
# comp_size(u32), orig_size(u32),
# orig_crc(u32), hdr_crc(u32)
PAGE_HDR_V1_STRUCT = struct.Struct("<4sHBBQQIIII")
PAGE_HDR_V1_SIZE = PAGE_HDR_V1_STRUCT.size

# Current header size (written for new pages)
PAGE_HDR_SIZE = PAGE_HDR_V1_SIZE


def pack_page_slot(
    page_size: int,
    page_id: int,
    page_type: int,
    comp_type: int,
    original: bytes,
    compressor: Compressor,
    *,
    lsn: int = 0,
    max_orig_size: int = 64 * 1024 * 1024,
) -> bytes:
    """Pack a single page slot.

    This writes the *current* v1 slot header, with strong bounds checking
    and minimal copying (bytearray + slicing).
    """

    if not (0 <= page_type <= 255):
        raise ValueError("page_type out of range")
    # Backward-compatibility: accept legacy ids (e.g. 50) and normalize.
    comp_type = _normalize_comp_type(int(comp_type))
    if comp_type not in (CT_NONE, CT_ZSTD, CT_ZLIB, CT_LZMA):
        raise ValueError(f"Unknown compression type: {comp_type}")
    if comp_type == CT_ZSTD and not _HAS_ZSTD:
        raise ValueError("CT_ZSTD requested but zstandard is not available")

    orig_size = len(original)
    if orig_size > max_orig_size:
        raise ValueError(f"orig_size too large: {orig_size}")

    if comp_type == CT_NONE:
        comp_data = original
    else:
        comp_data = compressor.compress(original)

    comp_size = len(comp_data)
    if PAGE_HDR_V1_SIZE + comp_size > page_size:
        raise ValueError(f"Payload too large for page (need {PAGE_HDR_V1_SIZE + comp_size}, have {page_size})")

    orig_crc = _crc32(original)

    # Build header with hdr_crc placeholder
    hdr_wo_crc = PAGE_HDR_V1_STRUCT.pack(
        PAGE_SLOT_MAGIC,
        PAGE_SLOT_FMT_VER,
        page_type,
        comp_type,
        int(page_id),
        int(lsn),
        int(comp_size),
        int(orig_size),
        int(orig_crc),
        0,
    )
    hdr_crc = _crc32(hdr_wo_crc[:-4])

    hdr = PAGE_HDR_V1_STRUCT.pack(
        PAGE_SLOT_MAGIC,
        PAGE_SLOT_FMT_VER,
        page_type,
        comp_type,
        int(page_id),
        int(lsn),
        int(comp_size),
        int(orig_size),
        int(orig_crc),
        int(hdr_crc),
    )

    buf = bytearray(page_size)  # already zero-filled
    buf[:PAGE_HDR_V1_SIZE] = hdr
    buf[PAGE_HDR_V1_SIZE:PAGE_HDR_V1_SIZE + comp_size] = comp_data
    return bytes(buf)


def unpack_page_slot(
    page_size: int,
    slot: bytes,
    compressor: Compressor,
    *,
    max_orig_size: int = 64 * 1024 * 1024,
) -> Tuple[int, int, int, bytes, int]:
    """Unpack a page slot.

    Returns: (page_id, page_type, comp_type, original_payload, lsn)
    """

    if len(slot) != page_size:
        raise ValueError("Invalid page slot length")

    # Try v1 first
    if slot[:4] == PAGE_SLOT_MAGIC:
        (magic, ver, page_type, comp_type, page_id, lsn,
         comp_size, orig_size, orig_crc, hdr_crc) = PAGE_HDR_V1_STRUCT.unpack_from(slot, 0)

        if magic != PAGE_SLOT_MAGIC:
            raise ValueError("Bad page magic")
        if ver != PAGE_SLOT_FMT_VER:
            raise ValueError(f"Unsupported page slot version: {ver}")

        # Header integrity quick check
        if _crc32(slot[:PAGE_HDR_V1_SIZE - 4]) != hdr_crc:
            raise IOError(f"Header CRC mismatch page_id={page_id}")

        if page_id == 0:
            return 0, 0, 0, b"", 0

        comp_type = _normalize_comp_type(int(comp_type))
        if comp_type not in (CT_NONE, CT_ZSTD, CT_ZLIB, CT_LZMA):
            raise ValueError(f"Unknown compression type: {comp_type}")
        if comp_type == CT_ZSTD and not _HAS_ZSTD:
            raise ValueError("CT_ZSTD found on disk but zstandard is not available")
        if orig_size > max_orig_size:
            raise ValueError(f"orig_size too large: {orig_size}")
        if PAGE_HDR_V1_SIZE + comp_size > page_size:
            raise ValueError("comp_size exceeds page size")

        comp_view = memoryview(slot)[PAGE_HDR_V1_SIZE:PAGE_HDR_V1_SIZE + comp_size]
        if comp_type == CT_NONE:
            original = comp_view.tobytes()
        else:
            if comp_type == CT_LZMA:
                if getattr(compressor, "algo", None) == "lzma":
                    original = compressor.decompress(comp_view.tobytes(), orig_size)
                else:
                    original = AdaptiveCompressor(algo="lzma", level=getattr(compressor, "level", 9)).decompress(comp_view.tobytes(), orig_size)
            else:
                original = compressor.decompress(comp_view.tobytes(), orig_size)

        if len(original) != orig_size:
            raise IOError(f"orig_size mismatch page_id={page_id}")
        if _crc32(original) != orig_crc:
            raise IOError(f"Payload CRC mismatch page_id={page_id}")

        return int(page_id), int(page_type), int(comp_type), original, int(lsn)

    # Fall back to legacy v0
    page_id, page_type, comp_type, comp_size, orig_size, checksum = PAGE_HDR_V0_STRUCT.unpack_from(slot, 0)
    if page_id == 0:
        return 0, 0, 0, b"", 0

    comp_type = _normalize_comp_type(int(comp_type))
    if comp_type not in (CT_NONE, CT_ZSTD, CT_ZLIB):
        raise ValueError(f"Unknown compression type: {comp_type}")
    if comp_type == CT_ZSTD and not _HAS_ZSTD:
        raise ValueError("CT_ZSTD found on disk but zstandard is not available")
    if orig_size > max_orig_size:
        raise ValueError(f"orig_size too large: {orig_size}")
    if PAGE_HDR_V0_SIZE + comp_size > page_size:
        raise ValueError("comp_size exceeds page size")

    payload = slot[PAGE_HDR_V0_SIZE: PAGE_HDR_V0_SIZE + comp_size]
    if comp_type in (CT_ZSTD, CT_ZLIB):
        original = compressor.decompress(payload, orig_size)
    else:
        original = bytes(payload)

    if len(original) != orig_size:
        raise IOError(f"orig_size mismatch page_id={page_id}")
    if _crc32(original) != checksum:
        raise IOError(f"Page CRC mismatch page_id={page_id}")

    return int(page_id), int(page_type), int(comp_type), original, 0


# ============================================================
# Adaptive Compression (MVP)
# ============================================================

class Compressor(Protocol):
    """Compression interface used by mpdb.

    Implementations MUST be deterministic and should enforce an output bound
    during decompression (to mitigate decompression bombs / OOM).
    """

    def compress(self, data: bytes) -> bytes:  # pragma: no cover
        ...

    def decompress(self, data: bytes, orig_size: int) -> bytes:  # pragma: no cover
        ...


class AdaptiveCompressor:
    """Compression backend.

    mpdb prefers ZSTD for the best speed/compression tradeoff. However, we
    keep a built-in fallback to zlib to make the project runnable without
    external wheels.
    """

    def __init__(self, *, algo: str = "zstd", level: int = 19, allow_fallback: bool = True):
        self.algo = (algo or "").strip().lower()
        self.level = int(level)

        if self.algo == "zstd":
            if not _HAS_ZSTD:
                if allow_fallback:
                    # zlib is the fast fallback; lzma is ~100x slower and hurts import perf.
                    self.algo = "zlib"
                else:
                    raise RuntimeError("zstandard is not available but algo='zstd' was requested")
            else:
                self._cctx = zstd.ZstdCompressor(level=self.level)
                self._dctx = zstd.ZstdDecompressor()

        if self.algo == "zlib":
            # zlib level is 0..9
            self.level = max(0, min(9, self.level))
        elif self.algo == "lzma":
            # lzma preset is 0..9
            self.level = max(0, min(9, self.level))
            self._cctx = lzma.LZMACompressor(preset=self.level)
            self._dctx = None

        if self.algo not in {"zstd", "zlib", "lzma"}:
            raise ValueError(f"Unsupported compressor algo: {self.algo}")

    def compress(self, data: bytes) -> bytes:
        if self.algo == "zstd" and _HAS_ZSTD:
            return self._cctx.compress(data)
        if self.algo == "lzma":
            return lzma.compress(data, preset=self.level)
        return zlib.compress(data, level=self.level)

    def decompress(self, data: bytes, orig_size: int) -> bytes:
        if self.algo == "zstd" and _HAS_ZSTD:
            return self._dctx.decompress(data, max_output_size=orig_size)
        if self.algo == "lzma":
            out = lzma.decompress(data)
            if len(out) > orig_size:
                raise IOError("lzma stream exceeds expected output size")
            return out
        # Bound output size to avoid untrusted decompression blowing up memory.
        d = zlib.decompressobj()
        out = d.decompress(data, orig_size)
        # If there is still input left after reaching the output cap, treat it
        # as suspicious (potential zip bomb / corrupted page).
        if d.unconsumed_tail:
            raise IOError("zlib stream exceeds expected output size")
        return out


# ============================================================
# LRU Cache (pages)
# ============================================================

class LRUCache:
    def __init__(self, capacity: int):
        self.capacity = max(16, int(capacity))
        self._lock = threading.RLock()
        # OrderedDict gives O(1) bump + eviction (move_to_end / popitem).
        self._items: "OrderedDict[int, bytes]" = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: int) -> Optional[bytes]:
        with self._lock:
            if key in self._items:
                self.hits += 1
                self._items.move_to_end(key, last=True)
                return self._items[key]
            self.misses += 1
            return None

    def put(self, key: int, value: bytes) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key, last=True)

            while len(self._items) > self.capacity:
                # pop LRU
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    @property
    def size(self) -> int:
        return len(self._items)


# ============================================================
# mpdb core
# ============================================================

class MpdbError(Exception):
    pass


class MpdbCorruptionError(MpdbError):
    """Database file appears truncated or internally inconsistent."""
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
        self._delete_on_close = False
        if str(path) == ":memory:":
            tmp = tempfile.NamedTemporaryFile(prefix="mpdb_memory_", suffix=".mpdb", delete=False)
            tmp.close()
            self.path = Path(tmp.name)
            self._delete_on_close = True
        else:
            self.path = Path(path)
        self._lock = threading.RLock()

        # compression
        algo, level = self._parse_compression(compression)
        self._compressor = AdaptiveCompressor(algo=algo, level=level)
        self._meta_compressor = AdaptiveCompressor(algo="lzma", level=min(9, self._compressor.level))
        if self._compressor.algo == "zstd":
            self._comp_type = CT_ZSTD
        elif self._compressor.algo == "lzma":
            self._comp_type = CT_LZMA
        else:
            self._comp_type = CT_ZLIB

        # page size sanity
        if page_size < 4096 or page_size > 65536 or (page_size % 4096 != 0):
            raise MpdbError("page_size must be 4096..65536 and multiple of 4096")
        self.page_size = int(page_size)

        # cache
        cap_pages = max(32, int((cache_mb * 1024 * 1024) // self.page_size))
        self._cache = LRUCache(capacity=cap_pages)

        self._file: Optional[io.BufferedRandom] = None
        self._meta: Dict[str, Any] = {}
        self._table_schema_cache: Dict[str, Dict[str, Any]] = {}
        self._opened = False
        self._format_rev: int = int(FORMAT_REV)

        # Monotonic LSN counter (persisted in META).
        self._lsn: int = 0

        # WAL pointers
        self._wal_start = 0
        self._wal_end = 0

        # Auto-checkpoint policy (configured via META_AUTOCHECKPOINT)
        self._acp_wal_bytes: int = 16 * 1024 * 1024  # 16MB
        self._acp_commits: int = 200
        self._acp_keep_wal_bytes: int = 0
        self._acp_commit_counter: int = 0
        self._in_recovery: bool = False

        self._open_or_create()
        self.recover()

    # ------------------------- public API -------------------------


    @property
    def db_uid(self) -> str:
        """Stable unique id of the database, stored in META."""
        try:
            return str(self._meta.get("db_uid") or "")
        except Exception:
            return ""

    def close(self) -> None:
        path_to_delete = self.path if self._delete_on_close else None
        with self._lock:
            if self._file:
                self._file.flush()
                self._file.close()
            self._file = None
            self._opened = False
            self._cache.clear()
            self._table_schema_cache.clear()
        if path_to_delete is not None:
            try:
                path_to_delete.unlink(missing_ok=True)
            except Exception:
                pass

    def _table_schema_asset_key(self, table_name: str) -> str:
        table = str(table_name or "").strip()
        return f"{TABLE_SCHEMA_ASSET_PREFIX}{table}.json"

    def _candidate_table_meta(
        self,
        name: str,
        schema: Dict[str, Any],
        *,
        schema_ref: str = "",
    ) -> Dict[str, Any]:
        candidate = dict(self._meta)
        tables = dict(candidate.get(META_TABLES, {}))
        tinfo: Dict[str, Any] = {}
        tinfo["data_pages"] = []
        tinfo["next_rowid"] = 1
        if schema_ref:
            tinfo["schema_ref"] = str(schema_ref)
        if schema and not schema_ref:
            tinfo["schema"] = schema
        if schema_ref:
            tinfo["schema_ref"] = str(schema_ref)
        tables[str(name)] = tinfo
        candidate[META_TABLES] = tables
        return candidate

    def _meta_fits_page(self, meta: Dict[str, Any]) -> bool:
        try:
            payload = self._encode_meta(meta)
            comp_size = len(self._compressor.compress(payload))
            return PAGE_HDR_SIZE + comp_size <= self.page_size
        except Exception:
            return False

    def _load_table_schema_raw(self, table_name: str, tinfo: Dict[str, Any]) -> Dict[str, Any]:
        schema_raw = tinfo.get("schema", {})
        if isinstance(schema_raw, dict) and schema_raw:
            self._table_schema_cache[str(table_name)] = dict(schema_raw)
            return schema_raw

        cache_key = str(table_name or "").strip()
        cached = self._table_schema_cache.get(cache_key)
        if isinstance(cached, dict):
            return cached

        schema_ref = str(tinfo.get("schema_ref") or "").strip()
        if not schema_ref:
            return {}
        try:
            payload, _mime = self.get_asset(schema_ref)
            loaded = json.loads(payload.decode("utf-8"))
        except Exception as exc:
            raise MpdbError(f"Failed to load schema for table {table_name}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise MpdbError(f"Schema asset for table {table_name} is not a JSON object")
        self._table_schema_cache[cache_key] = loaded
        return loaded

    def _table_schema_fields(self, table_name: str, tinfo: Dict[str, Any]) -> Dict[str, Any]:
        schema_raw = self._load_table_schema_raw(table_name, tinfo)
        if not isinstance(schema_raw, dict):
            return {}
        fields = schema_raw.get("fields", schema_raw)
        return fields if isinstance(fields, dict) else {}

    def create_table(self, name: str, schema: Dict[str, Any], *, external_schema: bool = False) -> None:
        name = str(name or "").strip()
        if not name:
            raise MpdbError("Table name is required")

        schema_ref = ""
        schema_to_store = schema

        with self._lock:
            tables = self._meta.setdefault(META_TABLES, {})
            if name in tables:
                raise MpdbError(f"Table exists: {name}")
            if external_schema or not self._meta_fits_page(self._candidate_table_meta(name, schema)):
                schema_ref = self._table_schema_asset_key(name)

        if schema_ref:
            payload = json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.put_assets_bulk([(schema_ref, payload, TABLE_SCHEMA_ASSET_MIME)])
            schema_to_store = {}
            with self._lock:
                if not self._meta_fits_page(self._candidate_table_meta(name, schema_to_store, schema_ref=schema_ref)):
                    raise MpdbError(f"META still does not fit after externalizing schema for table {name}")

        with self.transaction() as tx:
            tables = self._meta[META_TABLES]
            if name in tables:
                raise MpdbError(f"Table exists: {name}")
            table_info: Dict[str, Any] = {}
            table_info["data_pages"] = []
            table_info["next_rowid"] = 1
            if schema_to_store:
                table_info["schema"] = schema_to_store
            if schema_ref:
                table_info["schema_ref"] = schema_ref
            tables[name] = table_info
            tx.set_meta(self._meta)
        self._table_schema_cache[name] = dict(schema)

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
                schema_ref = str((tinfo or {}).get("schema_ref") or "").strip() if isinstance(tinfo, dict) else ""
                if schema_ref:
                    _ = self.get_asset(schema_ref)
                for pid in tinfo.get("data_pages", []):
                    _ = self._read_page(pid)  # will CRC-check

            # Verify referenced index roots (best-effort for MVP)
            idx_def = meta.get(META_INDEXES, {})
            for _tname, fields in idx_def.items():
                if not isinstance(fields, dict):
                    continue
                for _field, idef in fields.items():
                    if isinstance(idef, dict) and idef.get("root"):
                        _ = self._read_page(int(idef["root"]))



    # ------------------------- assets (binary/svg/png/ico) -------------------------

    def _assets_table_exists(self) -> bool:
        with self._lock:
            tables = self._meta.get(META_TABLES, {})
            return isinstance(tables, dict) and ASSETS_TABLE in tables

    def _ensure_assets_table_tx(self, tx: "Transaction") -> None:
        """Ensure internal assets table exists.

        Legacy (old) builds stored asset locator mapping in META under META_ASSETS.
        That approach doesn't scale because META must fit into a single page.

        New builds store the locator mapping in a regular MPDB table (ASSETS_TABLE),
        while still being able to read legacy META_ASSETS as a fallback.
        """
        tables = self._meta.setdefault(META_TABLES, {})
        if ASSETS_TABLE not in tables:
            tables[ASSETS_TABLE] = {
                "schema": {
                    "key": {"type": "string", "unique": True},
                    "first_page": {"type": "int"},
                    "size": {"type": "int"},
                    "mime": {"type": "string"},
                },
            }
        # Informational flag only.
        self._meta[META_ASSETS_BACKEND] = "table"
        tx.set_meta(self._meta)

    def _drop_unique_index_key_tx(self, tx: "Transaction", table_name: str, field: str, value: Any) -> None:
        """Drop a whole unique-index key inside an outer transaction.

        This is a repair guard for historical index rows that can survive an
        overwrite path even after the old asset locator row has been tombstoned.
        """
        try:
            idx_def = self._meta.get(META_INDEXES, {}).get(str(table_name or ""), {})
            idef = idx_def.get(str(field or "")) if isinstance(idx_def, dict) else None
            root = int((idef or {}).get("root") or 0) if isinstance(idef, dict) else 0
            if root > 0:
                BTreeIndex(self, root).delete(tx, _encode_sort_key(value), None)
        except Exception:
            pass

    def _select_asset_table_rows_by_key(self, key: str) -> list[Dict[str, Any]]:
        """Return asset locator rows, tolerating old fast-mode asset indexes.

        Some historical imports inserted ``__assets`` rows while migration
        fast-mode was enabled.  The rows are present, but secondary/rowid
        indexes may be incomplete, so indexed ``where={"key": ...}`` reads can
        miss them.  Asset lookup must prefer correctness over the index here.
        """
        k = str(key).replace('\\', '/').strip()
        if not k or not self._assets_table_exists():
            return []
        try:
            rows = self.table(ASSETS_TABLE).select(where={"key": k})
            if rows:
                return list(rows)
        except Exception:
            pass
        try:
            rows = self.table(ASSETS_TABLE).select()
            return [
                r for r in rows
                if str(r.get("key") or "").replace('\\', '/').strip() == k
            ]
        except Exception:
            return []

    def _lookup_asset_info(self, key: str) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """Return (table_info, meta_info) for the given key.

        table_info/meta_info shapes:
            {first_page:int, size:int, mime:str}
        """
        k = str(key).replace('\\', '/').strip()
        table_info: Optional[Dict[str, Any]] = None
        meta_info: Optional[Dict[str, Any]] = None

        if k and self._assets_table_exists():
            try:
                rows = self._select_asset_table_rows_by_key(k)
                if rows:
                    r = rows[-1]
                    table_info = {
                        "first_page": int(r.get("first_page") or 0),
                        "size": int(r.get("size") or 0),
                        "mime": str(r.get("mime") or "application/octet-stream"),
                    }
            except Exception:
                table_info = None

        with self._lock:
            assets = self._meta.get(META_ASSETS, {})
            if k and isinstance(assets, dict):
                info = assets.get(k)
                if isinstance(info, dict):
                    meta_info = {
                        "first_page": int(info.get("first_page") or 0),
                        "size": int(info.get("size") or 0),
                        "mime": str(info.get("mime") or "application/octet-stream"),
                    }

        return table_info, meta_info

    def put_asset(self, key: str, data: bytes, *, mime: str = "application/octet-stream") -> None:
        """Store an asset (PNG/SVG/ICO/any bytes) inside mpdb.

        Assets are stored as a chain of PT_BLOB pages.
        Locator mapping key -> first_page/size/mime is stored in ASSETS_TABLE.

        Backward compatibility:
            - If database still contains legacy META_ASSETS mapping, reads will fall back to it.
            - On overwrite of a legacy key, the legacy entry is removed to gradually shrink META.
        """
        key = str(key).replace('\\', '/').strip()
        if not key:
            raise MpdbError('Empty asset key')

        if data is None:
            data = b""

        old_table, old_meta = self._lookup_asset_info(key)

        with self.transaction() as tx:
            self._ensure_assets_table_tx(tx)
            tbl = Table(self, ASSETS_TABLE)

            # Free old chains early to maximize page reuse.
            for old in (old_table, old_meta):
                if isinstance(old, dict):
                    first = int(old.get('first_page') or 0)
                    if first > 0:
                        try:
                            self._free_blob_chain(tx, first)
                        except Exception:
                            pass

            # Remove old locator entries (table + legacy META).
            try:
                tbl.delete_tx(tx, {"key": key}, set_meta=False)
            except Exception:
                pass
            self._drop_unique_index_key_tx(tx, ASSETS_TABLE, "key", key)

            with self._lock:
                assets = self._meta.get(META_ASSETS, {})
                if isinstance(assets, dict) and key in assets:
                    assets.pop(key, None)
                    self._meta[META_ASSETS] = assets

            stored = self._encode_asset_payload(key, data, mime)
            first_pid = self._write_blob_chain(tx, stored)
            tbl.insert_tx(
                tx,
                {
                    "key": key,
                    "first_page": int(first_pid),
                    "size": int(len(stored)),
                    "mime": str(mime or "application/octet-stream"),
                },
                set_meta=False,
            )

            tx.set_meta(self._meta)

    def put_assets_bulk(
        self,
        items: list[tuple[str, bytes, str]],
        *,
        progress: Optional[Callable[[int, int], None]] = None,
        progress_every: int = 64,
    ) -> None:
        """Store many assets in a single transaction.

        This is primarily used during config import to avoid thousands of tiny
        transactions (slow on Windows + fsync). Locator mapping is stored in
        ASSETS_TABLE to keep META small.

        Args:
            items: list of (key, data, mime)
        """
        if not items:
            return

        # Normalize + dedupe keys (last wins) in insertion order.
        norm: Dict[str, tuple[bytes, str]] = {}
        for key, data, mime in items:
            k = str(key).replace('\\', '/').strip()
            if not k:
                continue
            norm[k] = (data or b"", str(mime or "application/octet-stream"))
        if not norm:
            return

        def _emit_progress(current: int, total: int) -> None:
            if progress is None:
                return
            try:
                progress(int(current), int(total))
            except Exception:
                pass

        keys_set = set(norm.keys())
        total_items = len(norm)
        progress_step = max(int(progress_every or 0), 1)

        # Pre-read existing locator info (committed state).
        old_table: Dict[str, Dict[str, Any]] = {}
        if self._assets_table_exists():
            try:
                rows = self.table(ASSETS_TABLE).select()
                for r in rows:
                    k = str(r.get('key') or '')
                    if k in keys_set:
                        old_table[k] = {
                            'first_page': int(r.get('first_page') or 0),
                            'size': int(r.get('size') or 0),
                            'mime': str(r.get('mime') or 'application/octet-stream'),
                        }
            except Exception:
                old_table = {}

        old_meta: Dict[str, Dict[str, Any]] = {}
        with self._lock:
            assets = self._meta.get(META_ASSETS, {})
            if isinstance(assets, dict):
                for k in keys_set:
                    info = assets.get(k)
                    if isinstance(info, dict):
                        old_meta[k] = {
                            'first_page': int(info.get('first_page') or 0),
                            'size': int(info.get('size') or 0),
                            'mime': str(info.get('mime') or 'application/octet-stream'),
                        }

        with self.transaction() as tx:
            self._ensure_assets_table_tx(tx)
            tbl = Table(self, ASSETS_TABLE)

            # Free old chains early to maximize page reuse.
            for old in list(old_table.values()) + list(old_meta.values()):
                first = int(old.get('first_page') or 0)
                if first > 0:
                    try:
                        self._free_blob_chain(tx, first)
                    except Exception:
                        pass

            # Delete old locator rows (table) before inserting new ones (unique key).
            for k in old_table.keys():
                try:
                    tbl.delete_tx(tx, {"key": k}, set_meta=False)
                except Exception:
                    pass
            for k in keys_set:
                self._drop_unique_index_key_tx(tx, ASSETS_TABLE, "key", k)

            # Remove legacy META entries for overwritten keys (shrinks META).
            with self._lock:
                assets = self._meta.get(META_ASSETS, {})
                if isinstance(assets, dict) and old_meta:
                    for k in old_meta.keys():
                        assets.pop(k, None)
                    self._meta[META_ASSETS] = assets

            # Insert new assets
            done = 0
            for k, (data, mime) in norm.items():
                stored = self._encode_asset_payload(k, data, mime)
                first_pid = self._write_blob_chain(tx, stored)
                tbl.insert_tx(
                    tx,
                    {
                        'key': k,
                        'first_page': int(first_pid),
                        'size': int(len(stored)),
                        'mime': str(mime or 'application/octet-stream'),
                    },
                    set_meta=False,
                )
                done += 1
                if done == total_items or done % progress_step == 0:
                    _emit_progress(done, total_items)

            tx.set_meta(self._meta)

    def get_asset(self, key: str) -> tuple[bytes, str]:
        """Return (data, mime). Raises MpdbError if not found."""
        key = str(key).replace('\\', '/').strip()
        if not key:
            raise MpdbError('Empty asset key')

        # Preferred: table backend.
        if self._assets_table_exists():
            try:
                rows = self._select_asset_table_rows_by_key(key)
                if rows:
                    r = rows[-1]
                    first = int(r.get('first_page') or 0)
                    mime = str(r.get('mime') or 'application/octet-stream')
                    size = int(r.get('size') or 0)
                    data = self._read_blob_chain(first, expected_size=size)
                    return self._decode_asset_payload(data), mime
            except Exception:
                pass

        # Fallback: legacy META mapping.
        with self._lock:
            assets = self._meta.get(META_ASSETS, {})
            info = assets.get(key) if isinstance(assets, dict) else None
            if not isinstance(info, dict):
                raise MpdbError(f'Asset not found: {key}')
            first = int(info.get('first_page') or 0)
            mime = str(info.get('mime') or 'application/octet-stream')
            size = int(info.get('size') or 0)

        data = self._read_blob_chain(first, expected_size=size)
        return self._decode_asset_payload(data), mime

    def list_assets(self, prefix: str = "") -> list[str]:
        prefix = str(prefix).replace('\\', '/').strip()

        keys: set[str] = set()
        if self._assets_table_exists():
            try:
                rows = self.table(ASSETS_TABLE).select()
                for r in rows:
                    k = str(r.get('key') or '')
                    if k:
                        keys.add(k)
            except Exception:
                pass

        with self._lock:
            assets = self._meta.get(META_ASSETS, {})
            if isinstance(assets, dict):
                for k in assets.keys():
                    ks = str(k)
                    if ks:
                        keys.add(ks)

        out = sorted(keys)
        if not prefix:
            return out
        return [k for k in out if k.startswith(prefix)]

    def delete_asset(self, key: str) -> bool:
        """Delete an asset from mpdb.

        This also frees the underlying blob pages.

        Returns:
            True if asset existed and was deleted.
        """
        key = str(key).replace('\\', '/').strip()
        if not key:
            return False

        old_table, old_meta = self._lookup_asset_info(key)
        existed = bool(old_table or old_meta)
        if not existed:
            return False

        with self.transaction() as tx:
            # Free old chains early to maximize reuse.
            for old in (old_table, old_meta):
                if isinstance(old, dict):
                    first = int(old.get('first_page') or 0)
                    if first > 0:
                        try:
                            self._free_blob_chain(tx, first)
                        except Exception:
                            pass

            if self._assets_table_exists():
                try:
                    tbl = Table(self, ASSETS_TABLE)
                    tbl.delete_tx(tx, {"key": key}, set_meta=False)
                except Exception:
                    pass

            with self._lock:
                assets = self._meta.get(META_ASSETS, {})
                if isinstance(assets, dict) and key in assets:
                    assets.pop(key, None)
                    self._meta[META_ASSETS] = assets

            tx.set_meta(self._meta)

        return True


    def delete_assets_by_prefixes(self, prefixes: list[str] | tuple[str, ...] | str) -> int:
        """Delete all assets whose keys start with any of the given prefixes.

        This operation is transactional and frees underlying blob chains to allow
        page reuse (critical for repeated large imports).

        Args:
            prefixes: One prefix or a list/tuple of prefixes (POSIX-like).

        Returns:
            Number of deleted assets (best-effort).
        """
        if isinstance(prefixes, str):
            pref_list = [prefixes]
        else:
            pref_list = list(prefixes)

        pref: list[str] = []
        for p in pref_list:
            ps = str(p or '').replace('\\', '/').strip()
            if ps:
                pref.append(ps)
        if not pref:
            return 0

        def match(k: str) -> bool:
            return any(k.startswith(p) for p in pref)

        # Collect current locators (prefer table, fallback to legacy META).
        table_loc: dict[str, dict[str, Any]] = {}
        if self._assets_table_exists():
            try:
                rows = self.table(ASSETS_TABLE).select()
                for r in rows:
                    k = str(r.get('key') or '')
                    if k and match(k):
                        table_loc[k] = {
                            'first_page': int(r.get('first_page') or 0),
                            'size': int(r.get('size') or 0),
                            'mime': str(r.get('mime') or 'application/octet-stream'),
                        }
            except Exception:
                table_loc = {}

        meta_loc: dict[str, dict[str, Any]] = {}
        with self._lock:
            assets = self._meta.get(META_ASSETS, {})
            if isinstance(assets, dict):
                for k, info in assets.items():
                    ks = str(k or '')
                    if not ks or not match(ks):
                        continue
                    if isinstance(info, dict):
                        meta_loc[ks] = {
                            'first_page': int(info.get('first_page') or 0),
                            'size': int(info.get('size') or 0),
                            'mime': str(info.get('mime') or 'application/octet-stream'),
                        }

        # Merge locators by key (table wins), so we never free the same chain twice.
        merged: dict[str, dict[str, Any]] = dict(meta_loc)
        merged.update(table_loc)  # table overrides legacy for same key
        keys = sorted(merged.keys())
        if not keys:
            return 0

        with self.transaction() as tx:
            # Free chains (dedupe by first_page to avoid pushing duplicates to allocator).
            freed_first: set[int] = set()
            for k in keys:
                first = int((merged.get(k) or {}).get('first_page') or 0)
                if first > 0 and first not in freed_first:
                    try:
                        self._free_blob_chain(tx, first)
                        freed_first.add(first)
                    except Exception:
                        pass

            # Delete table rows in the same transaction
            if self._assets_table_exists():
                try:
                    tbl = Table(self, ASSETS_TABLE)
                    for k in keys:
                        try:
                            tbl.delete_tx(tx, {'key': k}, set_meta=False)
                        except Exception:
                            continue
                except Exception:
                    pass

            # Delete legacy META entries + set meta once
            with self._lock:
                assets = self._meta.get(META_ASSETS, {})
                if isinstance(assets, dict):
                    for k in keys:
                        assets.pop(k, None)
                    self._meta[META_ASSETS] = assets
            tx.set_meta(self._meta)

        return int(len(keys))


    def _should_compress_asset(self, key: str, mime: str, data: bytes) -> bool:
        """Heuristic for compressing asset payloads before writing blob pages."""

        if not data or len(data) < 1024:
            return False

        mime_l = str(mime or "").strip().lower()
        if mime_l.startswith("text/"):
            return True

        if any(token in mime_l for token in ("json", "xml", "yaml", "yml", "csv", "ndjson", "jsonlines")):
            return True

        if mime_l.endswith("+json") or mime_l.endswith("+xml"):
            return True

        # Known textual helper payloads used by the importer/runtime.
        if mime_l in {
            "application/json",
            "application/x-jsonlines",
            "application/x-ndjson",
            "application/xml",
            "application/xhtml+xml",
            "application/vnd.mpdb.table-schema+json",
        }:
            return True

        # Generic binary assets stay unwrapped.
        return False

    def _encode_asset_payload(self, key: str, data: bytes, mime: str) -> bytes:
        """Optionally wrap asset bytes in a compressed envelope."""

        raw = bytes(data or b"")
        if not self._should_compress_asset(key, mime, raw):
            return raw

        comp_type = int(self._comp_type)
        compressor = self._compressor
        comp_data = compressor.compress(raw)
        wrapped = ASSET_ENVELOPE_STRUCT.pack(
            ASSET_ENVELOPE_MAGIC,
            int(ASSET_ENVELOPE_VER),
            int(comp_type),
            0,
            int(len(raw)),
            int(_crc32(raw)),
        ) + comp_data

        # Keep only if the envelope actually wins.
        if len(wrapped) >= len(raw):
            return raw
        return wrapped

    def _decode_asset_payload(self, data: bytes) -> bytes:
        """Decode asset payload written by :meth:`_encode_asset_payload`."""

        if not data or len(data) < ASSET_ENVELOPE_STRUCT.size:
            return bytes(data or b"")

        if data[:4] != ASSET_ENVELOPE_MAGIC:
            return bytes(data)

        magic, ver, comp_type, _flags, orig_size, orig_crc = ASSET_ENVELOPE_STRUCT.unpack_from(data, 0)
        if magic != ASSET_ENVELOPE_MAGIC or int(ver) != int(ASSET_ENVELOPE_VER):
            return bytes(data)

        payload = bytes(data[ASSET_ENVELOPE_STRUCT.size :])
        comp_type = _normalize_comp_type(int(comp_type))
        if comp_type == CT_NONE:
            decoded = payload
        else:
            if comp_type == CT_ZSTD:
                algo = "zstd"
            elif comp_type == CT_ZLIB:
                algo = "zlib"
            elif comp_type == CT_LZMA:
                algo = "lzma"
            else:
                return bytes(data)
            compressor = self._compressor if int(comp_type) == int(self._comp_type) else AdaptiveCompressor(algo=algo, level=self._compressor.level)
            decoded = compressor.decompress(payload, int(orig_size))

        if len(decoded) != int(orig_size) or _crc32(decoded) != int(orig_crc):
            raise MpdbError("Asset payload corrupted")
        return bytes(decoded)


    def _write_blob_chain(self, tx: "Transaction", data: bytes) -> int:
        """Write bytes into a chain of PT_BLOB pages. Returns first page_id."""
        if data is None:
            data = b""
        # Each blob page payload: next_pid(u32 LE) + chunk
        chunk_max = self.page_size - PAGE_HDR_SIZE - 4
        if chunk_max <= 0:
            raise MpdbError('page_size too small for blob payload')

        chunks = [data[i:i+chunk_max] for i in range(0, len(data), chunk_max)]
        if not chunks:
            chunks = [b""]

        page_ids = [self._alloc_page_id() for _ in range(len(chunks))]
        for i, pid in enumerate(page_ids):
            next_pid = page_ids[i+1] if i + 1 < len(page_ids) else 0
            payload = struct.pack('<I', int(next_pid)) + chunks[i]
            tx.put_page(int(pid), PT_BLOB, payload)

        return int(page_ids[0])

    def _read_blob_chain(self, first_pid: int, *, expected_size: int | None = None) -> bytes:
        if first_pid <= 0:
            return b""
        out = bytearray()
        pid = int(first_pid)
        visited = 0
        # hard safety to avoid infinite loops on corruption
        max_pages = max(16, (expected_size // max(1, (self.page_size - PAGE_HDR_SIZE - 4))) + 8) if expected_size else 100000

        while pid:
            visited += 1
            if visited > max_pages:
                raise MpdbError('Blob chain too long or loop detected')

            payload = self._read_page(pid)
            if len(payload) < 4:
                raise MpdbError(f'Blob page corrupted pid={pid}')
            next_pid = struct.unpack_from('<I', payload, 0)[0]
            out += payload[4:]
            pid = int(next_pid)

        if expected_size is not None and len(out) != expected_size:
            # allow slight mismatch if last page had padding/extra, but here we never pad beyond chunk
            raise MpdbError(f'Blob size mismatch: expected {expected_size}, got {len(out)}')
        return bytes(out)

    def _free_blob_chain(self, tx: "Transaction", first_pid: int) -> None:
        """Free a PT_BLOB chain.

        This is done transactionally:
        - each page id is recorded into the allocator (PT_FREELIST) (best-effort)
        - each page is wiped via tx.put_page(..., empty payload)

        Note: the chain traversal reads pages from disk, so it is best-effort
        if corruption is present.
        """
        pid = int(first_pid)
        visited: set[int] = set()
        while pid and pid not in visited:
            visited.add(pid)
            payload = self._read_page(pid)
            next_pid = struct.unpack_from('<I', payload, 0)[0] if len(payload) >= 4 else 0
            self._free_page_id(tx, pid)
            pid = int(next_pid)

    def get_statistics(self) -> Stats:
        with self._lock:
            f = self._require_file()
            f.flush()
            size = self.path.stat().st_size
            pages_total = max(0, (self._wal_start - HEADER_SIZE) // self.page_size)
            legacy_free = len(self._meta.get(META_FREE_PAGES, []))
            _head, fl_count = self._freelist_head()
            used = pages_total - legacy_free - int(fl_count)
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

    # ------------------------- maintenance -------------------------

    def checkpoint(self, *, durable: bool = True, keep_wal_bytes: int = 0) -> None:
        """Create a checkpoint and compact (optionally truncate) the WAL.

        mpdb is a single-file store: a contiguous pages region followed by a WAL region.
        Normal commits append WAL records and then apply pages. Therefore, once there are
        no active transactions, it is safe to compact the WAL.

        Behavior:
        - If keep_wal_bytes <= 0: WAL is fully truncated (start=end) and the underlying
          file is physically truncated to the end of the pages region.
        - If keep_wal_bytes  > 0: keep at most the last keep_wal_bytes of WAL by moving
          that tail to a new WAL region at end_of_pages.

        This method is guarded by the DB lock.
        """
        keep = int(keep_wal_bytes)
        with self._lock:
            f = self._require_file()

            # Ensure WAL is placed after pages before we operate on it.
            self._ensure_wal_after_pages()

            end_of_pages = HEADER_SIZE + (int(self._meta[META_NEXT_PAGE_ID]) - 1) * self.page_size
            wal_start = int(self._wal_start)
            wal_end = int(self._wal_end)
            wal_size = max(0, wal_end - wal_start)

            if wal_size == 0:
                # Still ensure pointers are sane and optionally truncate file.
                self._wal_start = int(end_of_pages)
                self._wal_end = int(end_of_pages)
                self._meta[META_WAL]["start"] = int(self._wal_start)
                self._meta[META_WAL]["end"] = int(self._wal_end)
                self._write_page(1, PT_META, self._encode_meta(self._meta))
                self._write_header()
                if durable:
                    try:
                        f.flush(); os.fsync(f.fileno())
                    except Exception:
                        pass
                # Physical truncation to remove stale WAL bytes.
                try:
                    f.truncate(int(end_of_pages))
                except Exception:
                    pass
                return

            # How much WAL to keep.
            if keep <= 0:
                # Full truncate.
                self._wal_start = int(end_of_pages)
                self._wal_end = int(end_of_pages)
                self._meta[META_WAL]["start"] = int(self._wal_start)
                self._meta[META_WAL]["end"] = int(self._wal_end)
                self._write_page(1, PT_META, self._encode_meta(self._meta))
                self._write_header()
                if durable:
                    try:
                        f.flush(); os.fsync(f.fileno())
                    except Exception:
                        pass
                try:
                    f.truncate(int(end_of_pages))
                except Exception:
                    pass
                return

            # Keep a tail portion of WAL (bounded).
            keep = min(keep, wal_size)
            new_start = int(end_of_pages)
            new_end = int(new_start + keep)

            # Ensure file size for new WAL placement.
            f.seek(0, os.SEEK_END)
            if f.tell() < new_end:
                f.seek(new_end - 1)
                f.write(b"\x00")
                f.flush()

            # Copy tail forward. Since dst is after pages, and could overlap with src,
            # copy backwards.
            chunk = 1024 * 1024
            remaining = keep
            while remaining > 0:
                take = chunk if remaining >= chunk else remaining
                src_pos = wal_end - remaining
                dst_pos = new_start + (keep - remaining)
                f.seek(src_pos)
                buf = f.read(take)
                if len(buf) != take:
                    raise MpdbError("Failed to compact WAL (short read)")
                f.seek(dst_pos)
                f.write(buf)
                remaining -= take
            f.flush()

            self._wal_start = int(new_start)
            self._wal_end = int(new_end)
            self._meta[META_WAL]["start"] = int(self._wal_start)
            self._meta[META_WAL]["end"] = int(self._wal_end)
            self._write_page(1, PT_META, self._encode_meta(self._meta))
            self._write_header()

            if durable:
                try:
                    f.flush(); os.fsync(f.fileno())
                except Exception:
                    pass


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
        if s.startswith("zlib"):
            if ":" in s:
                _, lvl = s.split(":", 1)
                return "zlib", int(lvl)
            return "zlib", 6
        if s.startswith("lzma"):
            if ":" in s:
                _, lvl = s.split(":", 1)
                return "lzma", int(lvl)
            return "lzma", 9
        raise MpdbError("Unsupported compression string")

    def _next_lsn(self) -> int:
        """Allocate a new monotonic LSN and persist it in META.

        LSNs are used to order page versions for recovery. For now we keep it simple:
        one LSN per committed transaction.
        """
        self._lsn = int(self._lsn) + 1
        try:
            self._meta[META_LSN] = int(self._lsn)
        except Exception:
            # META can be temporarily unavailable during bootstrap.
            pass
        return int(self._lsn)

    def _open_or_create(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        exists = self.path.exists()
        f = open(self.path, "r+b" if exists else "w+b", buffering=0)
        self._file = io.BufferedRandom(f)
        if not exists or self.path.stat().st_size < HEADER_SIZE:
            self._init_new_file()
        else:
            file_format_rev = self._read_header()
            self._meta = self._load_meta()
            migrated_meta, migrated = migrate_meta_to_format(
                self._meta,
                from_rev=int(file_format_rev),
                to_rev=int(FORMAT_REV),
                page_size=int(self.page_size),
            )
            if migrated or int(file_format_rev) != int(FORMAT_REV):
                self._meta = migrated_meta
                self._format_rev = int(FORMAT_REV)
                self._write_page(1, PT_META, self._encode_meta(self._meta))
                self._write_header()
            # Ensure stable DB identity for anti-tamper and remote binding.
            if not self._meta.get("db_uid"):
                self._meta["db_uid"] = str(uuid.uuid4())
                # Persist immediately so future opens are stable.
                self._write_page(1, PT_META, self._encode_meta(self._meta))
                self._write_header()
            self._lsn = int(self._meta.get(META_LSN, 0))
            self._wal_start = int(self._meta[META_WAL]["start"])
            self._wal_end = int(self._meta[META_WAL]["end"])

        # Load auto-checkpoint policy from META.
        self._apply_autocheckpoint_policy_from_meta()
        self._opened = True

    def _init_new_file(self) -> None:
        # Create empty header + first META page + WAL pointers
        self._meta = {
            META_ROOT: 1,  # meta page id
            "db_uid": str(uuid.uuid4()),
            META_TABLES: {},
            META_INDEXES: {},
            META_NEXT_PAGE_ID: 2,  # 1 reserved for meta
            META_FREE_PAGES: [],
            META_FREELIST: {"head": 0, "count": 0},
            META_STRINGS: {},      # str -> id
            META_NEXT_STR_ID: 1,
            META_ASSETS: {},      # key -> {first_page,size,mime}

            META_AUTOCHECKPOINT: {
                "wal_bytes": 16 * 1024 * 1024,
                "commits": 200,
                "keep_wal_bytes": 0,
            },

            META_AUTOCHECKPOINT: {
                "wal_bytes": 16 * 1024 * 1024,
                "commits": 200,
                "keep_wal_bytes": 0,
            },

            META_LSN: 0,

            META_WAL: {
                "start": HEADER_SIZE + self.page_size * 1,  # after page area (currently 1 page)
                "end": HEADER_SIZE + self.page_size * 1,
            }
        }

        self._lsn = 0

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
    #   0..5    magic (6)
    #   6..7    ver u16 (MAJOR)
    #   8..11   page_size u32
    #   12      comp u8
    #   13      enc u8 (0)
    #   14..15  format_rev u16 (MINOR; backward-compatible within MAJOR)
    #   16..123 reserved
    #   124..127 crc32 of bytes 0..123
    def _write_header(self) -> None:
        f = self._require_file()
        buf = bytearray(HEADER_SIZE)
        buf[0:6] = MAGIC
        struct.pack_into("<H", buf, 6, VERSION)
        struct.pack_into("<I", buf, 8, self.page_size)
        struct.pack_into("<B", buf, 12, self._comp_type)
        struct.pack_into("<B", buf, 13, 0)
        struct.pack_into("<H", buf, 14, int(self._format_rev))
        # reserved: could include meta root page id, etc. but we store root in meta page.
        crc = _crc32(bytes(buf[0:124]))
        struct.pack_into("<I", buf, 124, crc)
        f.seek(0)
        f.write(buf)
        f.flush()

    def _read_header(self) -> int:
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
        comp = _normalize_comp_type(int(buf[12]))
        # format_rev was added later; old files may have 0 here.
        fmt_rev = struct.unpack_from("<H", buf, 14)[0]
        crc = struct.unpack_from("<I", buf, 124)[0]
        if _crc32(buf[0:124]) != crc:
            raise MpdbError("Header CRC mismatch")

        try:
            ensure_supported_format_rev(int(fmt_rev), current_rev=int(FORMAT_REV))
        except ValueError as e:
            raise MpdbError(str(e)) from e
        if page_size != self.page_size:
            # allow opening existing db with its own page_size
            self.page_size = int(page_size)
        if comp not in (CT_ZSTD, CT_ZLIB, CT_LZMA):
            raise MpdbError(f"Unsupported page compression in file header: {comp}")
        self._comp_type = int(comp)
        # Ensure compressor matches on-disk encoding.
        if self._comp_type == CT_ZSTD:
            self._compressor = AdaptiveCompressor(algo="zstd", level=self._compressor.level)
        elif self._comp_type == CT_ZLIB:
            self._compressor = AdaptiveCompressor(algo="zlib", level=self._compressor.level)
        elif self._comp_type == CT_LZMA:
            self._compressor = AdaptiveCompressor(algo="lzma", level=min(9, self._compressor.level))
        self._format_rev = int(fmt_rev)
        return int(fmt_rev)

    # --------------------- meta ---------------------

    def _compact_meta_for_storage(self, meta: Dict[str, Any]) -> Dict[str, Any]:
        encoded = dict(meta or {})
        tables = encoded.get(META_TABLES)
        if isinstance(tables, dict):
            compact_tables: Dict[str, Any] = {}
            for table_name, tinfo in tables.items():
                if not isinstance(tinfo, dict):
                    compact_tables[str(table_name)] = tinfo
                    continue
                compact_tinfo: Dict[str, Any] = {}
                schema_ref = str(tinfo.get("schema_ref") or "").strip()
                schema = tinfo.get("schema")
                pages = list(tinfo.get("data_pages") or [])
                next_rowid = int(tinfo.get("next_rowid") or 1)
                rowid_index_root = int(tinfo.get("rowid_index_root") or 0)
                versioned = bool(tinfo.get("versioned") or False)

                if pages:
                    compact_tinfo[TABLE_INFO_META_ALIASES["data_pages"]] = _compress_int_ranges(pages)
                if next_rowid != 1:
                    compact_tinfo[TABLE_INFO_META_ALIASES["next_rowid"]] = next_rowid
                if isinstance(schema, dict) and schema:
                    compact_tinfo[TABLE_INFO_META_ALIASES["schema"]] = schema
                if schema_ref:
                    compact_tinfo[TABLE_INFO_META_ALIASES["schema_ref"]] = schema_ref
                if rowid_index_root > 0:
                    compact_tinfo[TABLE_INFO_META_ALIASES["rowid_index_root"]] = rowid_index_root
                if versioned:
                    compact_tinfo[TABLE_INFO_META_ALIASES["versioned"]] = True
                compact_tables[str(table_name)] = compact_tinfo
            encoded[META_TABLES] = compact_tables

        free_pages = encoded.get(META_FREE_PAGES)
        if isinstance(free_pages, list) and free_pages:
            encoded[META_FREE_PAGES] = _compress_int_ranges(list(free_pages))

        indexes = encoded.get(META_INDEXES)
        if isinstance(indexes, dict):
            compact_indexes: Dict[str, Any] = {}
            for table_name, field_defs in indexes.items():
                if not isinstance(field_defs, dict):
                    compact_indexes[str(table_name)] = field_defs
                    continue
                compact_field_defs: Dict[str, Any] = {}
                for field_name, idef in field_defs.items():
                    if not isinstance(idef, dict):
                        compact_field_defs[str(field_name)] = idef
                        continue
                    compact_idef: Dict[str, Any] = {}
                    root = int(idef.get("root") or 0)
                    if root > 0:
                        compact_idef["r"] = root
                    if bool(idef.get("unique")):
                        compact_idef["u"] = 1
                    if compact_idef:
                        compact_field_defs[str(field_name)] = compact_idef
                if compact_field_defs:
                    compact_indexes[str(table_name)] = compact_field_defs
            encoded[META_INDEXES] = compact_indexes
        return encoded

    def _expand_meta_from_storage(self, meta: Dict[str, Any]) -> Dict[str, Any]:
        decoded = dict(meta or {})
        tables = decoded.get(META_TABLES)
        if isinstance(tables, dict):
            expanded_tables: Dict[str, Any] = {}
            for table_name, tinfo in tables.items():
                if not isinstance(tinfo, dict):
                    expanded_tables[str(table_name)] = tinfo
                    continue
                expanded_tinfo: Dict[str, Any] = {}
                for key, value in tinfo.items():
                    expanded_key = TABLE_INFO_META_ALIAS_TO_KEY.get(str(key), str(key))
                    if expanded_key == "data_pages":
                        expanded_tinfo[expanded_key] = _expand_int_ranges(value)
                        continue
                    if expanded_key == "next_rowid":
                        try:
                            expanded_tinfo[expanded_key] = int(value)
                        except Exception:
                            continue
                        continue
                    if expanded_key == "rowid_index_root":
                        try:
                            expanded_tinfo[expanded_key] = int(value)
                        except Exception:
                            continue
                        continue
                    if expanded_key == "versioned":
                        expanded_tinfo[expanded_key] = bool(value)
                        continue
                    expanded_tinfo[expanded_key] = value
                expanded_tinfo.setdefault("data_pages", [])
                expanded_tinfo.setdefault("next_rowid", 1)
                expanded_tables[str(table_name)] = expanded_tinfo
            decoded[META_TABLES] = expanded_tables

        free_pages = decoded.get(META_FREE_PAGES)
        if isinstance(free_pages, list):
            decoded[META_FREE_PAGES] = _expand_int_ranges(free_pages)

        indexes = decoded.get(META_INDEXES)
        if isinstance(indexes, dict):
            expanded_indexes: Dict[str, Any] = {}
            for table_name, field_defs in indexes.items():
                if not isinstance(field_defs, dict):
                    expanded_indexes[str(table_name)] = field_defs
                    continue
                expanded_field_defs: Dict[str, Any] = {}
                for field_name, idef in field_defs.items():
                    if not isinstance(idef, dict):
                        expanded_field_defs[str(field_name)] = idef
                        continue
                    expanded_idef: Dict[str, Any] = {}
                    root = idef.get("r", idef.get("root"))
                    if root not in (None, "", 0, "0"):
                        try:
                            expanded_idef["root"] = int(root)
                        except Exception:
                            pass
                    unique = idef.get("u", idef.get("unique"))
                    if unique:
                        expanded_idef["unique"] = bool(unique)
                    if expanded_idef:
                        expanded_field_defs[str(field_name)] = expanded_idef
                if expanded_field_defs:
                    expanded_indexes[str(table_name)] = expanded_field_defs
            decoded[META_INDEXES] = expanded_indexes
        return decoded

    def _encode_meta(self, meta: Dict[str, Any]) -> bytes:
        # JSON for MVP (zstd will compress). Later: MessagePack.
        return json.dumps(self._compact_meta_for_storage(meta), ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def _decode_meta(self, data: bytes) -> Dict[str, Any]:
        loaded = json.loads(data.decode("utf-8"))
        return self._expand_meta_from_storage(loaded if isinstance(loaded, dict) else {})

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
        meta.setdefault(META_ASSETS, {})
        meta.setdefault(META_LSN, 0)

        meta.setdefault(META_AUTOCHECKPOINT, {
            "wal_bytes": 16 * 1024 * 1024,
            "commits": 200,
            "keep_wal_bytes": 0,
        })

        # Auto-checkpoint defaults (WAL compaction policy)
        meta.setdefault(META_AUTOCHECKPOINT, {"wal_bytes": 16 * 1024 * 1024, "commits": 200, "keep_wal_bytes": 0})

        # New allocator structure (optional). Legacy DBs may only have META_FREE_PAGES.
        meta.setdefault(META_FREELIST, {"head": 0, "count": 0})

        meta.setdefault(META_WAL, {"start": HEADER_SIZE + self.page_size, "end": HEADER_SIZE + self.page_size})
        return meta

    def _apply_autocheckpoint_policy_from_meta(self) -> None:
        """Load auto-checkpoint policy from META into in-memory fields."""
        cfg = self._meta.get(META_AUTOCHECKPOINT, {})
        if not isinstance(cfg, dict):
            cfg = {}

        def _i(name: str, default: int) -> int:
            try:
                v = int(cfg.get(name, default))
                return v if v >= 0 else default
            except Exception:
                return default

        self._acp_wal_bytes = _i("wal_bytes", 16 * 1024 * 1024)
        self._acp_commits = _i("commits", 200)
        self._acp_keep_wal_bytes = _i("keep_wal_bytes", 0)

    # --------------------- allocator (free pages) ---------------------

    def _freelist_head(self) -> Tuple[int, int]:
        fl = self._meta.get(META_FREELIST)
        if not isinstance(fl, dict):
            fl = {"head": 0, "count": 0}
            self._meta[META_FREELIST] = fl
        head = int(fl.get("head") or 0)
        count = int(fl.get("count") or 0)
        return head, count

    def _freelist_set_head(self, head: int, count: int) -> None:
        fl = self._meta.get(META_FREELIST)
        if not isinstance(fl, dict):
            fl = {}
            self._meta[META_FREELIST] = fl
        fl["head"] = int(head)
        fl["count"] = int(count)

    def _freelist_read_page(self, pid: int) -> Tuple[int, List[int]]:
        """Return (next_pid, entries) for a PT_FREELIST page."""
        payload = self._read_page(pid)
        if len(payload) < FREELIST_HDR.size:
            return 0, []
        next_pid, count = FREELIST_HDR.unpack_from(payload, 0)
        count = int(count)
        if count <= 0:
            return int(next_pid), []
        need = FREELIST_HDR.size + count * 4
        if len(payload) < need:
            # Corruption -> treat as empty to avoid crashes.
            return int(next_pid), []
        entries = list(struct.unpack_from(f"<{count}I", payload, FREELIST_HDR.size))
        return int(next_pid), [int(x) for x in entries]

    def _freelist_write_page(self, pid: int, next_pid: int, entries: List[int], *, lsn: int = 0) -> None:
        count = len(entries)
        buf = bytearray(FREELIST_HDR.size + count * 4)
        FREELIST_HDR.pack_into(buf, 0, int(next_pid), int(count))
        if count:
            struct.pack_into(f"<{count}I", buf, FREELIST_HDR.size, *[int(x) for x in entries])
        self._write_page(pid, PT_FREELIST, bytes(buf), lsn=lsn)

    def _alloc_page_id_extend_only(self) -> int:
        """Allocate a new page id by extending the pages region (ignores free-lists)."""
        pid = int(self._meta[META_NEXT_PAGE_ID])
        self._meta[META_NEXT_PAGE_ID] = pid + 1

        f = self._require_file()
        needed = self._page_offset(pid) + self.page_size
        f.seek(0, os.SEEK_END)
        if f.tell() < needed:
            f.seek(needed - 1)
            f.write(b"\x00")
            f.flush()

        self._ensure_wal_after_pages()
        return pid

    def _freelist_push(self, page_id: int) -> None:
        """Push a freed page id into the on-disk free-list stack (best-effort)."""
        pid = int(page_id)
        if pid <= 1:
            return

        head, total = self._freelist_head()

        # If no head, allocate one free-list page.
        if head == 0:
            head = self._alloc_page_id_extend_only()
            self._freelist_write_page(head, 0, [])

        next_pid, entries = self._freelist_read_page(head)

        # Ensure we have room for one more entry.
        max_entries = max(0, (self.page_size - PAGE_HDR_SIZE - FREELIST_HDR.size) // 4)
        if len(entries) >= max_entries and max_entries > 0:
            # New head page.
            new_head = self._alloc_page_id_extend_only()
            self._freelist_write_page(new_head, head, [pid])
            self._freelist_set_head(new_head, total + 1)
            return

        entries.append(pid)
        self._freelist_write_page(head, next_pid, entries)
        self._freelist_set_head(head, total + 1)

    def _freelist_pop(self) -> Optional[int]:
        """Pop a page id from on-disk free-list stack, or None if empty."""
        head, total = self._freelist_head()
        if head == 0 or total <= 0:
            return None

        next_pid, entries = self._freelist_read_page(head)
        if not entries:
            # Head empty: move to next (if any) and retry once.
            if next_pid:
                self._freelist_set_head(next_pid, total)
                head = next_pid
                next_pid, entries = self._freelist_read_page(head)
            if not entries:
                # Treat as empty.
                self._freelist_set_head(head, 0)
                return None

        pid = int(entries.pop())
        self._freelist_write_page(head, next_pid, entries)
        self._freelist_set_head(head, max(0, total - 1))
        return pid

    # --------------------- pages ---------------------

    def _page_offset(self, page_id: int) -> int:
        # page_id starts at 1
        return HEADER_SIZE + (page_id - 1) * self.page_size

    def _read_page_slot(self, page_id: int) -> Tuple[int, int, int, bytes]:
        cached = self._cache.get(page_id)
        if cached is not None:
            try:
                pid, ptype, ctype, payload, _lsn = unpack_page_slot(self.page_size, cached, self._compressor)
            except Exception as _e:
                print(f"[mpdb._read_page_slot] ERROR from CACHE pid={page_id}: {_e}", flush=True)
                print(f"  cache slot[:16] = {cached[:16].hex()}", flush=True)
                print(f"  comp_type byte (offset 7) = {cached[7] if len(cached) > 7 else '?'}", flush=True)
                raise
            return pid, ptype, ctype, payload

        f = self._require_file()

        off = self._page_offset(page_id)
        f.seek(off)
        slot = f.read(self.page_size)
        if len(slot) != self.page_size:
            try:
                cur = f.tell()
                f.seek(0, os.SEEK_END)
                fsz = f.tell()
                f.seek(cur)
            except Exception:
                fsz = -1
            exp_end = off + self.page_size
            hint = "file truncated" if (fsz >= 0 and exp_end > fsz) else "invalid page reference"
            raise MpdbCorruptionError(
                f"Page read failed page_id={page_id} (offset={off}, need_end={exp_end}, file_size={fsz}) [{hint}]"
            )
        self._cache.put(page_id, slot)
        try:
            pid, ptype, ctype, payload, _lsn = unpack_page_slot(self.page_size, slot, self._compressor)
        except Exception as _e:
            # Slot has invalid magic/compression — likely stale WAL bytes left
            # after a WAL relocation that was not followed by _write_page.
            # Try to find the page in the current WAL region.
            _recovered = self._try_recover_page_from_wal(page_id)
            if _recovered is not None:
                # Patch the cache with the good slot so future reads don't hit disk.
                _good_pid, _good_ptype, _good_ctype, _good_payload = _recovered
                print(f"[mpdb._read_page_slot] recovered pid={page_id} from WAL (was corrupt on disk)", flush=True)
                return _recovered
            print(f"[mpdb._read_page_slot] ERROR from DISK pid={page_id}: {_e}", flush=True)
            print(f"  offset={off}  page_size={self.page_size}", flush=True)
            print(f"  slot[:16] = {slot[:16].hex()}", flush=True)
            print(f"  magic_ok={slot[:4] == PAGE_SLOT_MAGIC}  comp_type_byte={slot[7] if len(slot)>7 else '?'}", flush=True)
            f.seek(0, os.SEEK_END)
            print(f"  file_size={f.tell()}  wal_start={self._wal_start}  wal_end={self._wal_end}", flush=True)
            raise
        return pid, ptype, ctype, payload

    def _try_recover_page_from_wal(self, page_id: int):
        """Scan the WAL for the most recent committed PUT_PAGE record for page_id.

        Returns (pid, ptype, ctype, payload) tuple if found, else None.
        Used as a last-resort fallback when the page slot on disk is corrupt
        (e.g. stale WAL bytes from a failed WAL relocation).
        """
        try:
            from .wal import iter_records
            f = self._require_file()
            committed_txids: set = set()
            pending: dict = {}   # txid -> latest raw page payload for page_id

            for rec_type, txid, payload_bytes in iter_records(f, self._wal_start, self._wal_end):
                if rec_type == WAL_PUT_PAGE:
                    import struct as _struct
                    if len(payload_bytes) < 12:
                        continue
                    pid_rec, _ = _struct.unpack_from("<QI", payload_bytes, 0)
                    if int(pid_rec) == int(page_id):
                        pending[txid] = payload_bytes[12:]
                elif rec_type == WAL_COMMIT:
                    if txid in pending:
                        committed_txids.add(txid)
                elif rec_type == WAL_ABORT:
                    pending.pop(txid, None)

            # Find the last committed txid that had a write for page_id.
            last_txid = None
            for txid in committed_txids:
                if last_txid is None or txid > last_txid:
                    last_txid = txid

            if last_txid is None:
                return None

            raw_payload = pending[last_txid]
            # Build a proper page slot from the raw payload so unpack_page_slot works.
            # We need to write this payload as a page slot and re-read it.
            # Simpler: create a temporary slot via pack_page_slot.
            # pack_page_slot and PT_DATA are defined in this same module.
            pt = PT_DATA
            slot = pack_page_slot(self.page_size, int(page_id), pt, raw_payload, self._compressor, lsn=0)
            pid, ptype, ctype, payload, _lsn = unpack_page_slot(self.page_size, slot, self._compressor)
            # Update cache with recovered slot.
            self._cache.put(page_id, slot)
            return pid, ptype, ctype, payload
        except Exception:
            return None

    def _read_page(self, page_id: int) -> bytes:
        pid, _, _, payload = self._read_page_slot(page_id)
        if pid != page_id:
            raise MpdbError(f"Page id mismatch {pid} != {page_id}")
        return payload

    def _write_page(self, page_id: int, page_type: int, payload: bytes, *, lsn: int | None = None) -> None:
        f = self._require_file()
        # Performance note:
        # - BLOB pages often store already-compressed formats (PNG/ICO/SVG).
        #   Re-compressing them using a high global DB compression level is
        #   expensive and typically provides little or no gain.
        # - For durability/correctness we still wrap them into page slots with
        #   CRC, but store their payload uncompressed.
        if page_type == PT_BLOB:
            comp_type = CT_NONE
            compressor = None
        elif page_type == PT_META:
            # In migration fast-mode use the main (fast) compressor instead of
            # the dedicated LZMA meta compressor.  The comp_type in the page
            # slot header is set accordingly so decompression always matches.
            if getattr(self, "_migration_fast_mode", False):
                comp_type = self._comp_type
                compressor = self._compressor
            else:
                comp_type = CT_LZMA
                compressor = self._meta_compressor
        else:
            comp_type = self._comp_type
            compressor = self._compressor

        slot = pack_page_slot(
            self.page_size,
            page_id,
            page_type,
            comp_type,
            payload,
            compressor,
            lsn=int(lsn or 0),
        )
        off = self._page_offset(page_id)
        f.seek(off)
        f.write(slot)
        f.flush()
        self._cache.put(page_id, slot)

        # Ensure WAL is always stored strictly after the pages region.
        # Page allocation may grow the pages region; if WAL overlaps, relocate it.
        self._ensure_wal_after_pages()

    def _alloc_page_id(self) -> int:
        """Allocate a page id.

        Allocation prefers reusing freed pages (LIFO), falling back to extending
        the file. Crucially, this function also ensures WAL never overlaps the
        pages region by relocating WAL forward when the pages region grows.
        """
        # 1) Legacy in-META free list (kept for backward compatibility).
        free = self._meta.get(META_FREE_PAGES, [])
        if isinstance(free, list):
            while free:
                pid = int(free.pop())
                if pid > 1:
                    self._ensure_wal_after_pages()
                    return pid

        # 2) On-disk free-list stack (PT_FREELIST pages).
        while True:
            pid2 = self._freelist_pop()
            if pid2 is None:
                break
            if int(pid2) > 1:
                self._ensure_wal_after_pages()
                return int(pid2)

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

        # If WAL already contains records, it may now overlap the newly grown
        # pages region. Relocate WAL forward if required.
        self._ensure_wal_after_pages()
        return pid

    def _ensure_wal_after_pages(self) -> None:
        """Ensure WAL region is strictly after the pages region.

        mpdb stores pages first and then a WAL region appended after them.
        When the pages region grows (new page ids are allocated), WAL may need
        to be relocated forward to avoid overlap.

        This is an MVP implementation intended for correctness and durability.
        """
        f = self._require_file()

        # End of the pages area is based on next_page_id.
        end_of_pages = HEADER_SIZE + (int(self._meta[META_NEXT_PAGE_ID]) - 1) * self.page_size
        if self._wal_start >= end_of_pages:
            return

        wal_size = int(self._wal_end) - int(self._wal_start)
        if wal_size <= 0:
            self._wal_start = int(end_of_pages)
            self._wal_end = int(end_of_pages)
            try:
                self._meta[META_WAL]["start"] = int(self._wal_start)
                self._meta[META_WAL]["end"] = int(self._wal_end)
            except Exception:
                pass
            return

        old_start = int(self._wal_start)
        old_end = int(self._wal_end)
        new_start = int(end_of_pages)
        intent_probe = wal_pack_relocate_intent(old_start, old_end, new_start, 0)
        intent_size = len(wal_pack_record(WAL_RELOCATE_INTENT, 0, intent_probe))
        expected_new_end = int(new_start + wal_size + intent_size)
        self._wal_append(
            WAL_RELOCATE_INTENT,
            0,
            wal_pack_relocate_intent(old_start, old_end, new_start, expected_new_end),
        )
        self._wal_sync()

        wal_size = int(self._wal_end) - int(self._wal_start)
        new_end = int(new_start + wal_size)

        # Ensure file large enough for new WAL placement.
        f.seek(0, os.SEEK_END)
        if f.tell() < new_end:
            f.seek(new_end - 1)
            f.write(b"\x00")
            f.flush()

        if wal_size > 0:
            # Move WAL forward safely. Since dest starts after src, copy backwards
            # to avoid clobbering yet-to-be-copied bytes if regions overlap.
            chunk = 1024 * 1024  # 1 MiB
            remaining = wal_size
            while remaining > 0:
                take = chunk if remaining >= chunk else remaining
                src_pos = int(self._wal_start) + (remaining - take)
                dst_pos = new_start + (remaining - take)
                f.seek(src_pos)
                buf = f.read(take)
                if len(buf) != take:
                    raise MpdbError("Failed to relocate WAL (short read)")
                f.seek(dst_pos)
                f.write(buf)
                remaining -= take

            # The copied WAL must be durable before we start zeroing the old
            # overlapping bytes. If the process dies now, recovery can locate
            # the new WAL stream by scanning after end_of_pages and using the
            # relocation intent record embedded into the copied WAL.
            self._sync_file()

            # Zero-fill only the prefix of the old WAL that lives in the pages
            # area. This prevents stale MPWL bytes from being misread as page
            # slots, but happens only after the new WAL copy is durable.
            old_wal_prefix = max(0, min(old_end, new_start) - old_start)
            if old_wal_prefix > 0:
                f.seek(old_start)
                f.write(b"\x00" * old_wal_prefix)
                f.flush()

        # Update pointers.
        self._wal_start = new_start
        self._wal_end = new_end
        try:
            self._meta[META_WAL]["start"] = int(self._wal_start)
            self._meta[META_WAL]["end"] = int(self._wal_end)
        except Exception:
            pass

    def _free_page_id(self, tx: "Transaction", page_id: int) -> None:
        """Free a page id for reuse.

        Semantics:
        - Prefer pushing the page id into the on-disk allocator stack (PT_FREELIST).
        - Legacy META_FREE_PAGES is kept for backward compatibility (existing DBs).
        - Wipe the page payload via tx.put_page to avoid data leakage across reuse.
        """
        pid = int(page_id)
        if pid <= 1:
            raise MpdbError("Cannot free reserved page")

        # Push into the allocator stack (best-effort). This keeps META small.
        try:
            self._freelist_push(pid)
        except Exception:
            # Fallback to legacy list if allocator pages fail for any reason.
            free = self._meta.setdefault(META_FREE_PAGES, [])
            if pid not in free:
                free.append(pid)
        # Wipe old content to avoid data leakage across reuse.
        tx.put_page(pid, PT_META, b"")
        self._ensure_wal_after_pages()

    # --------------------- strings (dedup) MVP ---------------------

    def _intern_strings(self, obj: Any) -> Any:
        """
        Replace strings with {"$s":id} for dedup, recursively.
        """
        if not ENABLE_STRING_INTERNING:
            return obj

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
        # Use WAL v2 for new records (magic/version/header CRC). Recovery also
        # supports legacy v1 records for backward compatibility.
        data = wal_pack_record(rec_type, txid, payload)
        f.seek(self._wal_end)
        f.write(data)
        f.flush()
        pos = self._wal_end
        self._wal_end += len(data)
        self._meta[META_WAL]["end"] = self._wal_end
        return pos

    def _sync_file(self) -> None:
        """Best-effort durability barrier for the underlying DB file."""
        f = self._require_file()
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            # Best-effort: some environments may not support fsync.
            pass

    def _wal_sync(self) -> None:
        """Durability barrier for WAL writes.

        WAL v2 makes recovery robust to partial writes by design. This method
        strengthens durability by forcing the OS to flush WAL bytes to disk.
        It is intentionally used only on commit in the MVP.

        When _migration_fast_mode is True the fsync is skipped for performance.
        The caller must call checkpoint() after the bulk operation to ensure
        durability.  This is safe for re-importable data (e.g. 1CD migration).
        """
        if getattr(self, "_migration_fast_mode", False):
            try:
                self._file.flush()
            except Exception:
                pass
            return
        self._sync_file()

    def recover(self) -> None:
        """Replay WAL and apply only committed transactions.

        WAL parsing lives in mpdb.wal; recovery logic lives in mpdb.recovery.
        """
        self._in_recovery = True
        try:
            recover_db(
                self,
                PT_META=PT_META,
                META_WAL=META_WAL,
                WAL_BEGIN=WAL_BEGIN,
                WAL_PUT_PAGE=WAL_PUT_PAGE,
                WAL_SET_META=WAL_SET_META,
                WAL_COMMIT=WAL_COMMIT,
                WAL_ABORT=WAL_ABORT,
                WAL_RELOCATE_INTENT=WAL_RELOCATE_INTENT,
            )
        finally:
            self._in_recovery = False

    def _maybe_autocheckpoint_after_commit(self, *, durable: bool = False) -> None:
        """Trigger checkpoint automatically based on configured policy.

        This is a best-effort maintenance mechanism to prevent unbounded WAL growth.
        It is intentionally conservative and skips during recovery.
        """
        if self._in_recovery:
            return

        # Count commits since last auto-checkpoint.
        self._acp_commit_counter = int(self._acp_commit_counter) + 1

        wal_size = max(0, int(self._wal_end) - int(self._wal_start))
        by_size = int(self._acp_wal_bytes) > 0 and wal_size >= int(self._acp_wal_bytes)
        by_commits = int(self._acp_commits) > 0 and int(self._acp_commit_counter) >= int(self._acp_commits)
        if not (by_size or by_commits):
            return

        keep = int(self._acp_keep_wal_bytes)
        try:
            self.checkpoint(durable=durable, keep_wal_bytes=keep)
        finally:
            # Reset counter regardless of checkpoint outcome to avoid tight loops on errors.
            self._acp_commit_counter = 0


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
        self._pages: List[int] = []       # ordered unique page ids (insertion order)
        self._page_map: Dict[int, Tuple[int, bytes]] = {}  # pid -> (page_type, payload)
        self._meta_bytes: Optional[bytes] = None
        self._meta_before: Optional[bytes] = None

    def __enter__(self) -> "Transaction":
        with self.db._lock:
            self._active = True
            self._meta_before = self.db._encode_meta(self.db._meta)
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
        pid = int(page_id)
        # Track insertion order for deterministic WAL replay, but only once per page.
        if pid not in self._page_map:
            self._pages.append(pid)
        self._page_map[pid] = (int(page_type), bytes(payload))

    def read_page(self, page_id: int) -> bytes:
        """Read a page within the transaction.

        If the page has been written in this transaction, returns the pending
        payload (not yet committed). Otherwise reads the committed page.
        """
        pid = int(page_id)
        if pid in self._page_map:
            return self._page_map[pid][1]
        return self.db._read_page(pid)

    def set_meta(self, meta: Dict[str, Any]) -> None:
        if not self._active:
            raise MpdbError("Transaction not active")
        self._meta_bytes = self.db._encode_meta(meta)

    def commit(self) -> None:
        with self.db._lock:
            if not self._active:
                return

            # write WAL records — one entry per unique page (latest version only)
            for pid in self._pages:
                ptype, payload = self._page_map[pid]
                hdr = struct.pack("<QI", int(pid), int(ptype))
                self.db._wal_append(WAL_PUT_PAGE, self.txid, hdr + payload)

            if self._meta_bytes is not None:
                self.db._wal_append(WAL_SET_META, self.txid, self._meta_bytes)

            self.db._wal_append(WAL_COMMIT, self.txid, b"")
            # Make the commit durable in WAL before applying pages.
            self.db._wal_sync()

            commit_lsn = self.db._next_lsn()

            # apply changes to main file (post-commit)
            for pid in self._pages:
                ptype, payload = self._page_map[pid]
                self.db._write_page(pid, ptype, payload, lsn=commit_lsn)

            if self._meta_bytes is not None:
                self.db._meta = self.db._decode_meta(self._meta_bytes)
                # Persist the latest WAL pointers produced during this commit.
                self.db._meta.setdefault(META_WAL, {})
                self.db._meta[META_WAL]["start"] = int(self.db._wal_start)
                self.db._meta[META_WAL]["end"] = int(self.db._wal_end)
                # persist LSN inside META (it may have been updated earlier)
                self.db._meta[META_LSN] = int(self.db._lsn)
                self.db._write_page(1, PT_META, self.db._encode_meta(self.db._meta), lsn=commit_lsn)
                self.db._write_header()

            self._active = False

            # Best-effort maintenance to keep WAL bounded.
            self.db._maybe_autocheckpoint_after_commit(durable=False)

    def abort(self) -> None:
        with self.db._lock:
            if not self._active:
                return
            if self._meta_before is not None:
                self.db._meta = self.db._decode_meta(self._meta_before)
            self.db._wal_append(WAL_ABORT, self.txid, b"")
            self._active = False

    def checkpoint(self, *, durable: bool = True, keep_wal_bytes: int = 0) -> None:
        """Commit the transaction and create a DB checkpoint.

        Kept for compatibility with earlier prototypes where checkpointing was done
        inside a transaction. The new implementation commits first and then delegates
        to Mpdb.checkpoint().
        """
        if not self._active:
            raise MpdbError("Transaction not active")
        self.commit()
        self.db.checkpoint(durable=durable, keep_wal_bytes=keep_wal_bytes)


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

            pages: List[int] = tinfo.setdefault("data_pages", [])
            max_payload = self.db.page_size - PAGE_HDR_SIZE

            # Ensure the record fits on an empty page.
            if not _data_page_can_fit(max_payload, len(blob)):
                raise MpdbError(f"Record too large for page: {len(blob)} bytes")
            def _write_new_page_with_record() -> tuple[int, int]:
                pid = self.db._alloc_page_id()
                pages.append(pid)
                page_payload = _data_page_init(max_payload)
                page_payload, slot_pos = _data_page_insert(page_payload, blob)
                tx.put_page(pid, PT_DATA, page_payload)
                return int(pid), int(slot_pos)

            if not pages:
                pid, slot_pos = _write_new_page_with_record()
            else:
                last_pid = int(pages[-1])
                current = tx.read_page(last_pid)
                # Migrate legacy stream pages into slot-format on first write.
                if not _is_data_slot_page(current):
                    migrated = _data_page_init(max_payload)
                    for _rid, _data in _iter_records_legacy(current):
                        # Re-encode into the canonical on-disk record form.
                        raw = json.dumps({"rowid": int(_rid), "data": _data}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                        migrated, _ = _data_page_insert(migrated, raw)
                    current = migrated

                try:
                    new_payload, slot_pos = _data_page_insert(current, blob)
                    tx.put_page(last_pid, PT_DATA, new_payload)
                    pid = last_pid
                except MpdbError:
                    # Not enough space in the last page; allocate a new page.
                    pid, slot_pos = _write_new_page_with_record()

            # Primary rowid -> (page,slot) locator index for fast point reads
            self._put_rowid_locator(tx, tinfo, rowid, int(pid), int(slot_pos))

            # auto index (MVP): if schema says indexed=True or unique=True
            self._maybe_update_indexes(tx, tinfo, row, rowid)


            tx.set_meta(self.db._meta)

            return rowid

    def insert_tx(self, tx: "Transaction", row: Dict[str, Any], *, set_meta: bool = True) -> int:
        """Transaction-aware variant of :meth:`insert`.

        Use this to batch many inserts into a single outer transaction.
        """
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

        pages: List[int] = tinfo.setdefault("data_pages", [])
        max_payload = self.db.page_size - PAGE_HDR_SIZE

        # Ensure the record fits on an empty page.
        if not _data_page_can_fit(max_payload, len(blob)):
            raise MpdbError(f"Record too large for page: {len(blob)} bytes")

        def _write_new_page_with_record() -> tuple[int, int]:
            pid = self.db._alloc_page_id()
            pages.append(pid)
            page_payload = _data_page_init(max_payload)
            page_payload, slot_pos = _data_page_insert(page_payload, blob)
            tx.put_page(pid, PT_DATA, page_payload)
            return int(pid), int(slot_pos)

        if not pages:
            pid, slot_pos = _write_new_page_with_record()
        else:
            last_pid = int(pages[-1])
            current = tx.read_page(last_pid)
            # Migrate legacy stream pages into slot-format on first write.
            if not _is_data_slot_page(current):
                migrated = _data_page_init(max_payload)
                for _rid, _data in _iter_records_legacy(current):
                    raw = json.dumps({"rowid": int(_rid), "data": _data}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    migrated, _ = _data_page_insert(migrated, raw)
                current = migrated

            try:
                new_payload, slot_pos = _data_page_insert(current, blob)
                tx.put_page(last_pid, PT_DATA, new_payload)
                pid = last_pid
            except MpdbError:
                pid, slot_pos = _write_new_page_with_record()

        # Primary rowid -> (page,slot) locator index for fast point reads.
        # Skipped in migration fast-mode: the index is rebuilt lazily on first
        # access and is never needed during bulk import.
        skip_indexes_for_fast_mode = (
            getattr(self.db, "_migration_fast_mode", False)
            and self.name != ASSETS_TABLE
        )
        if not skip_indexes_for_fast_mode:
            self._put_rowid_locator(tx, tinfo, rowid, int(pid), int(slot_pos))

        # auto index (MVP): if schema says indexed=True or unique=True
        if not skip_indexes_for_fast_mode:
            self._maybe_update_indexes(tx, tinfo, row, rowid)

        if set_meta:
            tx.set_meta(self.db._meta)

        return rowid

    def select(self, where: Optional[Dict[str, Any]] = None, *, order_by: Optional[str] = None) -> List[Dict[str, Any]]:
        # Allow point reads by primary rowid even though rowid is not part of the stored row dict.
        if where and "rowid" in where:
            try:
                rid = int(where.get("rowid"))
            except Exception:
                raise MpdbError("rowid must be an int")

            # Fetch via primary rowid->locator index.
            row = self._fetch_row_by_rowid(int(rid))
            if row is None:
                return []

            # If there are additional predicates, apply them on the materialized row.
            where_local = dict(where)
            where_local.pop("rowid", None)
            if where_local and not _match(row, where_local):
                return []
            return [row]
        with self.db._lock:
            tables = self.db._meta[META_TABLES]
            tinfo = tables[self.name]
            pages = list(tinfo.get("data_pages", []))

            idx_def = self.db._meta.get(META_INDEXES, {}).get(self.name, {})

        ordered_rowids: Optional[List[int]] = None
        ordered_set: Optional[set[int]] = None

        # If an order_by field has a page-based index, we can iterate rowids in key order
        # without doing an in-memory sort of the full result set.
        if order_by:
            idx = idx_def.get(order_by)
            if isinstance(idx, dict) and idx.get("root"):
                btree = BTreeIndex(self.db, int(idx["root"]))
                ordered_rowids = list(btree.iter_rowids())
                ordered_set = set(ordered_rowids)

        # try index if possible
        candidate_rowids: Optional[set[int]] = None
        if where:
            candidate_rowids = self._try_index(where)

        # If we have an ordered list from index, we collect matching rows into a map
        # and then emit them in index order. Rows without the indexed field will be
        # appended at the end (preserving scan order).
        if ordered_rowids is not None and ordered_set is not None:
            out: List[Dict[str, Any]] = []
            tail: List[Dict[str, Any]] = []

            # Fast path: fetch rows by primary rowid->locator index.
            for rid in ordered_rowids:
                if candidate_rowids is not None and int(rid) not in candidate_rowids:
                    continue
                row = self._fetch_row_by_rowid(int(rid))
                if row is None:
                    continue
                if where and not _match(row, where):
                    continue
                out.append(row)

            # Rows not present in the order_by index (missing/None field) are appended.
            # We still need a scan to find them. This keeps correctness while preserving
            # the benefit of ordered index reads for the majority case.
            if where or candidate_rowids is not None:
                for pid in pages:
                    payload = self.db._read_page(pid)
                    for rowid, data in _iter_records(payload):
                        if int(rowid) in ordered_set:
                            continue
                        if candidate_rowids is not None and int(rowid) not in candidate_rowids:
                            continue
                        restored = self.db._restore_strings(data)
                        if where and not _match(restored, where):
                            continue
                        tail.append(restored)
            else:
                # no filters: only need to append unordered rows once
                for pid in pages:
                    payload = self.db._read_page(pid)
                    for rowid, data in _iter_records(payload):
                        if int(rowid) in ordered_set:
                            continue
                        tail.append(self.db._restore_strings(data))

            out.extend(tail)
            return out

        # Fallback: full scan + Python sort.
        out: List[Dict[str, Any]] = []
        for pid in pages:
            payload = self.db._read_page(pid)
            for rowid, data in _iter_records(payload):
                if candidate_rowids is not None and rowid not in candidate_rowids:
                    continue
                restored = self.db._restore_strings(data)
                if where and not _match(restored, where):
                    continue
                out.append(restored)

        if order_by:
            # Robust ordering: missing values go last.
            out.sort(key=lambda x: (x.get(order_by) is None, x.get(order_by)))
        return out

    def delete(self, where: Dict[str, Any]) -> int:
        """Delete rows matching `where`.

        MVP semantics:
        - Uses a tombstone delete: marks the data slot as deleted (len=0).
        - Removes entries from secondary indexes and from the primary rowid->locator index.
        - Does not compact data pages (space is reclaimed later by compaction).

        Returns the number of deleted rows.
        """
        if not where:
            raise MpdbError("delete() requires a non-empty where clause")

        # Allow direct rowid deletes.
        where_local = dict(where)
        direct_rowid = None
        if "rowid" in where_local:
            try:
                direct_rowid = int(where_local.pop("rowid"))
            except Exception:
                raise MpdbError("rowid must be an int")

        with self.db.transaction() as tx:
            tables = self.db._meta[META_TABLES]
            tinfo = tables[self.name]
            pages: List[int] = list(tinfo.get("data_pages", []))

            # Determine candidate rowids.
            candidate_rowids: set[int] | None = None
            if direct_rowid is not None:
                candidate_rowids = {int(direct_rowid)}
            elif where_local:
                candidate_rowids = self._try_index(where_local)

            if candidate_rowids is None:
                candidate_rowids = set()
                for pid in pages:
                    payload = self.db._read_page(int(pid))
                    for rid, data in _iter_records(payload):
                        restored = self.db._restore_strings(data)
                        if _match(restored, where_local):
                            candidate_rowids.add(int(rid))

            if not candidate_rowids:
                return 0

            deleted = 0
            idx_def = self.db._meta.get(META_INDEXES, {}).get(self.name, {})
            schema = self.db._table_schema_fields(self.name, tinfo)

            for rid in sorted(candidate_rowids):
                # Fetch full row for index maintenance (fast via rowid locator).
                row = self._fetch_row_by_rowid(int(rid))
                if row is None:
                    continue
                if where_local and not _match(row, where_local):
                    continue

                loc = self._get_rowid_locator(int(rid))
                if not loc:
                    continue
                page_id, slot_pos = loc

                # Tombstone the slot.
                page_payload = tx.read_page(int(page_id))
                if not _is_data_slot_page(page_payload):
                    # Legacy pages: cannot tombstone precisely; skip (MVP).
                    # In practice, v7+ DBs use slot pages.
                    continue
                page_payload = _data_page_mark_deleted(page_payload, int(slot_pos))
                tx.put_page(int(page_id), PT_DATA, page_payload)

                # Update secondary indexes.
                for field, opts in (schema or {}).items():
                    if not (isinstance(opts, dict) and (opts.get("indexed") or opts.get("unique"))):
                        continue
                    val = row.get(field)
                    if val is None:
                        continue
                    idef = idx_def.get(field)
                    if isinstance(idef, dict) and idef.get("root"):
                        btree = BTreeIndex(self.db, int(idef["root"]))
                        key = _encode_sort_key(val)
                        btree.delete(tx, key, int(rid))

                # Delete from primary rowid index.
                root = tinfo.get("rowid_index_root")
                if isinstance(root, int) and root > 0:
                    btree = BTreeIndex(self.db, int(root))
                    key = _encode_sort_key(int(rid))
                    packed = self._pack_locator(int(page_id), int(slot_pos))
                    btree.delete(tx, key, int(packed))

                deleted += 1

            tx.set_meta(self.db._meta)
            return int(deleted)

    def delete_tx(self, tx: "Transaction", where: Dict[str, Any], *, set_meta: bool = True) -> int:
        """Transaction-aware variant of :meth:`delete`.

        Use this to batch many deletes into a single outer transaction.
        """
        if not where:
            raise MpdbError("delete() requires a non-empty where clause")

        # Allow direct rowid deletes.
        where_local = dict(where)
        direct_rowid = None
        if "rowid" in where_local:
            try:
                direct_rowid = int(where_local.pop("rowid"))
            except Exception:
                raise MpdbError("rowid must be an int")

        tables = self.db._meta[META_TABLES]
        tinfo = tables[self.name]
        pages: List[int] = list(tinfo.get("data_pages", []))

        # Determine candidate rowids.
        candidate_rowids: set[int] | None = None
        if direct_rowid is not None:
            candidate_rowids = {int(direct_rowid)}
        elif where_local:
            candidate_rowids = self._try_index(where_local)

        if candidate_rowids is None:
            candidate_rowids = set()
            for pid in pages:
                payload = self.db._read_page(int(pid))
                for rid, data in _iter_records(payload):
                    restored = self.db._restore_strings(data)
                    if _match(restored, where_local):
                        candidate_rowids.add(int(rid))

        if not candidate_rowids:
            return 0

        deleted = 0
        idx_def = self.db._meta.get(META_INDEXES, {}).get(self.name, {})
        schema = self.db._table_schema_fields(self.name, tinfo)

        for rid in sorted(candidate_rowids):
            # Fetch full row for index maintenance (fast via rowid locator).
            row = self._fetch_row_by_rowid(int(rid))
            if row is None:
                continue
            if where_local and not _match(row, where_local):
                continue

            loc = self._get_rowid_locator(int(rid))
            if not loc:
                continue
            page_id, slot_pos = loc

            # Tombstone the slot.
            page_payload = tx.read_page(int(page_id))
            if not _is_data_slot_page(page_payload):
                continue
            page_payload = _data_page_mark_deleted(page_payload, int(slot_pos))
            tx.put_page(int(page_id), PT_DATA, page_payload)

            # Update secondary indexes.
            for field, opts in (schema or {}).items():
                if not (isinstance(opts, dict) and (opts.get("indexed") or opts.get("unique"))):
                    continue
                val = row.get(field)
                if val is None:
                    continue
                idef = idx_def.get(field)
                if isinstance(idef, dict) and idef.get("root"):
                    btree = BTreeIndex(self.db, int(idef["root"]))
                    key = _encode_sort_key(val)
                    btree.delete(tx, key, int(rid))

            # Delete from primary rowid index.
            root = tinfo.get("rowid_index_root")
            if isinstance(root, int) and root > 0:
                btree = BTreeIndex(self.db, int(root))
                key = _encode_sort_key(int(rid))
                packed = self._pack_locator(int(page_id), int(slot_pos))
                btree.delete(tx, key, int(packed))

            deleted += 1

        if set_meta:
            tx.set_meta(self.db._meta)
        return int(deleted)

    def update(self, where: Dict[str, Any], set_values: Dict[str, Any]) -> int:
        """Update rows matching `where` with `set_values`.

        MVP semantics:
        - Keeps `rowid` stable.
        - Performs tombstone+relocate: old slot is marked deleted, new record is appended
          (potentially on another page) and the primary rowid->locator index is updated.
        - Secondary indexes are maintained (delete old value, insert new value).
        - No in-page compaction; space is reclaimed later by compaction.

        Returns the number of updated rows.
        """
        if not where:
            raise MpdbError("update() requires a non-empty where clause")
        if not set_values:
            return 0

        where_local = dict(where)
        direct_rowid = None
        if "rowid" in where_local:
            try:
                direct_rowid = int(where_local.pop("rowid"))
            except Exception:
                raise MpdbError("rowid must be an int")

        with self.db.transaction() as tx:
            tables = self.db._meta[META_TABLES]
            tinfo = tables[self.name]
            pages: List[int] = list(tinfo.get("data_pages", []))

            # Determine candidate rowids.
            candidate_rowids: set[int] | None = None
            if direct_rowid is not None:
                candidate_rowids = {int(direct_rowid)}
            elif where_local:
                candidate_rowids = self._try_index(where_local)

            if candidate_rowids is None:
                candidate_rowids = set()
                for pid in pages:
                    payload = self.db._read_page(int(pid))
                    for rid, data in _iter_records(payload):
                        restored = self.db._restore_strings(data)
                        if _match(restored, where_local):
                            candidate_rowids.add(int(rid))

            if not candidate_rowids:
                return 0

            updated = 0
            idx_def = self.db._meta.get(META_INDEXES, {}).get(self.name, {})
            schema = self.db._table_schema_fields(self.name, tinfo)

            max_payload = self.db.page_size - PAGE_HDR_SIZE

            for rid in sorted(candidate_rowids):
                old_row = self._fetch_row_by_rowid(int(rid))
                if old_row is None:
                    continue
                if where_local and not _match(old_row, where_local):
                    continue

                old_loc = self._get_rowid_locator(int(rid))
                if not old_loc:
                    continue
                old_page_id, old_slot_pos = old_loc

                # Build the new row values (on the restored form).
                new_row = dict(old_row)
                for k, v in set_values.items():
                    # rowid is managed internally; allow but ignore external attempts to change it.
                    if k == "rowid":
                        continue
                    new_row[k] = v

                # Maintain secondary indexes (delete old, insert new).
                for field, opts in (schema or {}).items():
                    if not (isinstance(opts, dict) and (opts.get("indexed") or opts.get("unique"))):
                        continue
                    unique = bool(opts.get("unique"))
                    idef = idx_def.get(field)
                    if not (isinstance(idef, dict) and idef.get("root")):
                        # Index might not exist yet (lazy creation on insert). If it doesn't,
                        # we will create it when we insert the new row below.
                        continue

                    btree = BTreeIndex(self.db, int(idef["root"]))
                    old_val = old_row.get(field)
                    new_val = new_row.get(field)
                    if old_val == new_val:
                        continue
                    if old_val is not None:
                        btree.delete(tx, _encode_sort_key(old_val), int(rid))
                    if new_val is not None:
                        new_root = btree.insert(tx, _encode_sort_key(new_val), int(rid), unique=unique)
                        if int(new_root) != int(idef["root"]):
                            idef["root"] = int(new_root)

                # Tombstone the old slot.
                page_payload = tx.read_page(int(old_page_id))
                if not _is_data_slot_page(page_payload):
                    # Legacy pages: cannot tombstone precisely (MVP).
                    continue
                page_payload = _data_page_mark_deleted(page_payload, int(old_slot_pos))
                tx.put_page(int(old_page_id), PT_DATA, page_payload)

                # Encode new record with the same rowid.
                packed_obj = {
                    "rowid": int(rid),
                    "data": self.db._intern_strings(new_row),
                }
                blob = json.dumps(packed_obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                if not _data_page_can_fit(max_payload, len(blob)):
                    raise MpdbError(f"Updated record too large for page: {len(blob)} bytes")

                # Append the updated record (reuse last page if possible).
                pages_ref: List[int] = tinfo.setdefault("data_pages", [])

                def _write_new_page_with_record() -> tuple[int, int]:
                    pid = self.db._alloc_page_id()
                    pages_ref.append(pid)
                    page_payload2 = _data_page_init(max_payload)
                    page_payload2, slot_pos2 = _data_page_insert(page_payload2, blob)
                    tx.put_page(pid, PT_DATA, page_payload2)
                    return int(pid), int(slot_pos2)

                if not pages_ref:
                    new_pid, new_slot_pos = _write_new_page_with_record()
                else:
                    last_pid = int(pages_ref[-1])
                    current = tx.read_page(last_pid)
                    if not _is_data_slot_page(current):
                        migrated = _data_page_init(max_payload)
                        for _rid2, _data2 in _iter_records_legacy(current):
                            raw = json.dumps({"rowid": int(_rid2), "data": _data2}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                            migrated, _ = _data_page_insert(migrated, raw)
                        current = migrated
                    try:
                        new_payload2, new_slot_pos = _data_page_insert(current, blob)
                        tx.put_page(last_pid, PT_DATA, new_payload2)
                        new_pid = last_pid
                    except MpdbError:
                        new_pid, new_slot_pos = _write_new_page_with_record()

                # Update primary rowid index: replace old locator with the new one.
                root = self._ensure_rowid_index(tx, tinfo)
                btree_rowid = BTreeIndex(self.db, int(root))
                key = _encode_sort_key(int(rid))
                old_packed = self._pack_locator(int(old_page_id), int(old_slot_pos))
                btree_rowid.delete(tx, key, int(old_packed))
                new_packed = self._pack_locator(int(new_pid), int(new_slot_pos))
                new_root_pid = btree_rowid.insert(tx, key, int(new_packed), unique=True)
                if int(new_root_pid) != int(root):
                    tinfo["rowid_index_root"] = int(new_root_pid)

                # If some secondary indexes didn't exist yet, create+update them now.
                # IMPORTANT: avoid double-inserting into already existing indexes.
                idx_def_now = self.db._meta.get(META_INDEXES, {}).get(self.name, {})
                row_for_new_indexes = dict(new_row)
                for f, idef2 in (idx_def_now or {}).items():
                    if isinstance(idef2, dict) and idef2.get("root"):
                        # Index exists; it was already maintained above (or unchanged).
                        row_for_new_indexes[f] = None
                self._maybe_update_indexes(tx, tinfo, row_for_new_indexes, int(rid))

                updated += 1

            tx.set_meta(self.db._meta)
            return int(updated)

    def _maybe_update_indexes(self, tx: Transaction, tinfo: Dict[str, Any], row: Dict[str, Any], rowid: int) -> None:
        """Update indexes for the inserted row.

        mpdb supports two index backends:
        - Legacy (meta-only) mapping: META_INDEXES[table][field] == {json(value): [rowid...]}
        - Current (page-based) B+tree: META_INDEXES[table][field] == {"root": pid, "unique": bool}

        New databases should use the page-based index, which scales and keeps META small.
        """

        # Historical note:
        # - Early platform code stored schema as {"fields": {...}}.
        # - mpdb core expects a flat mapping: {field: {"indexed": True, ...}, ...}
        # Keep backward compatibility by accepting both shapes.
        schema = self.db._table_schema_fields(self.name, tinfo)
        idx_root = self.db._meta.setdefault(META_INDEXES, {}).setdefault(self.name, {})

        for field, opts in schema.items():
            if not (isinstance(opts, dict) and (opts.get("indexed") or opts.get("unique"))):
                continue

            val = row.get(field)
            if val is None:
                continue

            unique = bool(opts.get("unique"))
            idef = idx_root.get(field)

            # Create a new B+tree index lazily.
            if not (isinstance(idef, dict) and idef.get("root")):
                root_pid = self._create_index_root(tx)
                idef = {"root": int(root_pid), "unique": unique}
                idx_root[field] = idef

            # Page-based index insert (binary sortable key).
            key = _encode_sort_key(val)
            btree = BTreeIndex(self.db, int(idef["root"]))
            new_root = btree.insert(tx, key, int(rowid), unique=unique)
            if int(idef["root"]) != int(new_root):
                idef["root"] = int(new_root)
        # indexes stored in meta; persisted via tx.set_meta(self.db._meta)

    def _try_index(self, where: Dict[str, Any]) -> Optional[set[int]]:
        with self.db._lock:
            idx_def = self.db._meta.get(META_INDEXES, {}).get(self.name, {})
            # pick first available indexed field in where
            for k, v in where.items():
                idx = idx_def.get(k)
                if not idx:
                    continue
                key_bin = _encode_sort_key(v)
                key_json = json.dumps(v, ensure_ascii=False, separators=(",", ":"))

                # New B+tree index backend
                if isinstance(idx, dict) and idx.get("root"):
                    root_pid = int(idx["root"])
                    btree = BTreeIndex(self.db, root_pid)
                    rowids = btree.get(key_bin)
                    return set(map(int, rowids)) if rowids else set()

                # Legacy backend (meta-only)
                if isinstance(idx, dict):
                    rowids = idx.get(key_json)
                    if rowids:
                        return set(map(int, rowids))
                    return set()
        return None

    def _create_index_root(self, tx: Transaction) -> int:
        """Create an empty leaf page for a new B+tree index."""
        pid = self.db._alloc_page_id()
        node = {"leaf": 1, "next": 0, "items": []}
        tx.put_page(pid, PT_INDEX, _encode_index_node(node))
        return pid


    # -------------------- primary rowid -> locator index --------------------

    def _ensure_rowid_index(self, tx: Transaction, tinfo: Dict[str, Any]) -> int:
        """Ensure the primary rowid->locator index exists; return root pid."""
        root = tinfo.get("rowid_index_root")
        if isinstance(root, int) and root > 0:
            return int(root)
        pid = self._create_index_root(tx)
        tinfo["rowid_index_root"] = int(pid)
        return int(pid)

    @staticmethod
    def _pack_locator(page_id: int, slot_pos: int) -> int:
        """Pack (page_id, slot_pos) into a single u64.

        Layout: [ page_id << 16 | slot_pos ]
        slot_pos is u16.
        """
        if slot_pos < 0 or slot_pos > 0xFFFF:
            raise MpdbError("slot_pos out of range")
        return (int(page_id) << 16) | int(slot_pos)

    @staticmethod
    def _unpack_locator(locator: int) -> tuple[int, int]:
        page_id = int(locator) >> 16
        slot_pos = int(locator) & 0xFFFF
        return page_id, slot_pos

    def _put_rowid_locator(self, tx: Transaction, tinfo: Dict[str, Any], rowid: int, page_id: int, slot_pos: int) -> None:
        root = self._ensure_rowid_index(tx, tinfo)
        btree = BTreeIndex(self.db, int(root))
        key = _encode_sort_key(int(rowid))
        loc = self._pack_locator(int(page_id), int(slot_pos))
        new_root = btree.insert(tx, key, int(loc), unique=True)
        if int(new_root) != int(root):
            tinfo["rowid_index_root"] = int(new_root)

    def _get_rowid_locator(self, rowid: int) -> tuple[int, int] | None:
        with self.db._lock:
            tinfo = self.db._meta[META_TABLES][self.name]
            root = tinfo.get("rowid_index_root")
            if not (isinstance(root, int) and root > 0):
                return None
            btree = BTreeIndex(self.db, int(root))
            key = _encode_sort_key(int(rowid))
            bucket = btree.get(key)
            if not bucket:
                return None
            page_id, slot_pos = self._unpack_locator(int(bucket[0]))
            return int(page_id), int(slot_pos)

    def _fetch_row_by_rowid(self, rowid: int) -> Dict[str, Any] | None:
        loc = self._get_rowid_locator(int(rowid))
        if not loc:
            return None
        page_id, slot_pos = loc
        payload = self.db._read_page(int(page_id))
        raw = _data_page_get_record(payload, int(slot_pos))
        obj = json.loads(raw.decode("utf-8"))
        data = obj.get("data", {})
        return self.db._restore_strings(data)


INDEX_NODE_MAGIC = b"MPIN"  # mpdb INdex
INDEX_NODE_VER = 1

# Header:
#   magic[4], ver(u8), leaf(u8), reserved(u16), next(u64), count(u16), reserved2(u16)
INDEX_HDR = struct.Struct("<4sBBH Q H H")
INDEX_HDR_SIZE = INDEX_HDR.size


def _encode_index_node(node: Dict[str, Any]) -> bytes:
    """Encode an index node.

    Current format: compact binary with lexicographically sortable binary keys.

    Node schema:
      leaf node:
        {"leaf":1, "next":<u64>, "items":[[key_bytes, [rowid...]], ...]}
      internal node:
        {"leaf":0, "keys":[key_bytes...], "children":[pid...]}  (children count = keys+1)
    """

    leaf = int(node.get("leaf", 0))
    if leaf == 1:
        items = list(node.get("items", []))
        next_pid = int(node.get("next", 0) or 0)
        count = len(items)
        buf = bytearray()
        buf += INDEX_HDR.pack(INDEX_NODE_MAGIC, INDEX_NODE_VER, 1, 0, next_pid, count, 0)
        for k, bucket in items:
            kb = bytes(k)
            if len(kb) > 0xFFFF:
                raise MpdbError("Index key too large")
            buf += struct.pack("<H", len(kb))
            buf += kb
            b = list(map(int, bucket))
            if len(b) > 0xFFFF:
                raise MpdbError("Index bucket too large")
            buf += struct.pack("<H", len(b))
            for rid in b:
                buf += struct.pack("<Q", int(rid))
        return bytes(buf)

    # internal
    keys = list(node.get("keys", []))
    children = list(map(int, node.get("children", [])))
    if len(children) != len(keys) + 1:
        raise MpdbError("Corrupted internal index node")
    count = len(keys)
    buf = bytearray()
    buf += INDEX_HDR.pack(INDEX_NODE_MAGIC, INDEX_NODE_VER, 0, 0, 0, count, 0)
    for k in keys:
        kb = bytes(k)
        if len(kb) > 0xFFFF:
            raise MpdbError("Index key too large")
        buf += struct.pack("<H", len(kb))
        buf += kb
    # children
    buf += struct.pack("<H", len(children))
    for pid in children:
        buf += struct.pack("<Q", int(pid))
    return bytes(buf)


def _decode_index_node(payload: bytes) -> Dict[str, Any]:
    """Decode index node payload.

    Supports:
    - current binary MPIN v1
    - legacy JSON nodes (auto-converted to binary keys in-memory)
    """

    if len(payload) >= 4 and payload[:4] == INDEX_NODE_MAGIC:
        try:
            magic, ver, leaf, _r1, next_pid, count, _r2 = INDEX_HDR.unpack_from(payload, 0)
        except Exception as e:
            raise MpdbError(f"Corrupted index node header: {e}")
        if magic != INDEX_NODE_MAGIC or ver != INDEX_NODE_VER:
            raise MpdbError("Unsupported index node version")

        off = INDEX_HDR_SIZE
        if int(leaf) == 1:
            items: list[list[Any]] = []
            for _ in range(int(count)):
                if off + 2 > len(payload):
                    raise MpdbError("Corrupted index node")
                klen = struct.unpack_from("<H", payload, off)[0]
                off += 2
                if off + klen > len(payload):
                    raise MpdbError("Corrupted index node")
                key = payload[off:off + klen]
                off += klen
                if off + 2 > len(payload):
                    raise MpdbError("Corrupted index node")
                blen = struct.unpack_from("<H", payload, off)[0]
                off += 2
                bucket: list[int] = []
                if off + (8 * blen) > len(payload):
                    raise MpdbError("Corrupted index node")
                for _j in range(int(blen)):
                    rid = struct.unpack_from("<Q", payload, off)[0]
                    off += 8
                    bucket.append(int(rid))
                items.append([key, bucket])
            return {"leaf": 1, "next": int(next_pid), "items": items}

        # internal
        keys: list[bytes] = []
        for _ in range(int(count)):
            if off + 2 > len(payload):
                raise MpdbError("Corrupted index node")
            klen = struct.unpack_from("<H", payload, off)[0]
            off += 2
            if off + klen > len(payload):
                raise MpdbError("Corrupted index node")
            keys.append(payload[off:off + klen])
            off += klen
        if off + 2 > len(payload):
            raise MpdbError("Corrupted index node")
        child_count = struct.unpack_from("<H", payload, off)[0]
        off += 2
        if child_count != len(keys) + 1:
            raise MpdbError("Corrupted internal index node")
        if off + (8 * child_count) > len(payload):
            raise MpdbError("Corrupted index node")
        children: list[int] = []
        for _ in range(int(child_count)):
            pid = struct.unpack_from("<Q", payload, off)[0]
            off += 8
            children.append(int(pid))
        return {"leaf": 0, "keys": keys, "children": children}

    # Legacy JSON
    try:
        node = json.loads(payload.decode("utf-8"))
    except Exception as e:
        raise MpdbError(f"Corrupted index node: {e}")

    # Convert keys to binary in-memory.
    if int(node.get("leaf", 0)) == 1:
        items = []
        for k, bucket in node.get("items", []):
            val = _decode_legacy_json_key(str(k))
            items.append([_encode_sort_key(val), list(map(int, bucket))])
        return {"leaf": 1, "next": int(node.get("next", 0) or 0), "items": items}
    keys = []
    for k in node.get("keys", []):
        val = _decode_legacy_json_key(str(k))
        keys.append(_encode_sort_key(val))
    children = list(map(int, node.get("children", [])))
    return {"leaf": 0, "keys": keys, "children": children}


IndexKey = bytes


class BTreeIndex:
    """Minimal B+tree for key -> [rowid].

    Design goals (MVP):
    - correctness first
    - page-size bounded nodes
    - leaf linkage for future range scans
    """

    def __init__(self, db: Mpdb, root_page_id: int):
        self.db = db
        self.root = int(root_page_id)

    def get(self, key: IndexKey) -> List[int]:
        pid = self.root
        while True:
            node = _decode_index_node(self.db._read_page(pid))
            if int(node.get("leaf", 0)) == 1:
                items = node.get("items", [])
                keys = [bytes(it[0]) for it in items]
                i = bisect.bisect_left(keys, key)
                if i < len(items) and items[i][0] == key:
                    return list(map(int, items[i][1]))
                return []
            keys = list(map(bytes, node.get("keys", [])))
            children = node.get("children", [])
            i = bisect.bisect_right(keys, key)
            pid = int(children[i])

    def insert(self, tx: Transaction, key: IndexKey, rowid: int, *, unique: bool = False) -> int:
        split = self._insert_into(tx, self.root, key, rowid, unique=unique)
        if split is None:
            return int(self.root)
        split_key, new_pid = split

        # Create a new root.
        new_root = self.db._alloc_page_id()
        root_node = {
            "leaf": 0,
            "keys": [split_key],
            "children": [int(self.root), int(new_pid)],
        }
        tx.put_page(new_root, PT_INDEX, _encode_index_node(root_node))

        # Root changed.
        self.root = int(new_root)
        return int(self.root)

    def delete(self, tx: Transaction, key: IndexKey, value: int | None = None) -> bool:
        """Delete a value from the index.

        - If value is provided: remove that value from the bucket for key.
        - If value is None: remove the entire key (all bucket values).

        Returns True if something was removed.

        Notes (MVP):
        - No node merge/rebalance; empty keys are removed from leaves.
        - Separator keys in internal nodes are not adjusted; this is safe
          for our separator semantics (they may become smaller than the true
          first key of the right child, which still preserves correctness).
        """
        return bool(self._delete_from(tx, int(self.root), key, value))

    def _delete_from(self, tx: Transaction, page_id: int, key: IndexKey, value: int | None) -> bool:
        node = _decode_index_node(tx.read_page(page_id))
        if int(node.get("leaf", 0)) == 1:
            return self._delete_from_leaf(tx, page_id, node, key, value)

        keys: List[IndexKey] = list(map(bytes, node.get("keys", [])))
        children: List[int] = list(map(int, node.get("children", [])))
        if len(children) != len(keys) + 1:
            raise MpdbError("Corrupted index internal node")

        i = bisect.bisect_right(keys, key)
        child_pid = int(children[i])
        removed = self._delete_from(tx, child_pid, key, value)
        # MVP: do not rebalance even if child becomes empty.
        return removed

    def _delete_from_leaf(self, tx: Transaction, page_id: int, node: Dict[str, Any], key: IndexKey, value: int | None) -> bool:
        items: List[Any] = list(node.get("items", []))
        keys = [bytes(it[0]) for it in items]
        i = bisect.bisect_left(keys, key)
        if i >= len(items) or items[i][0] != key:
            return False

        if value is None:
            # remove whole key
            items.pop(i)
        else:
            bucket = list(map(int, items[i][1]))
            try:
                bucket.remove(int(value))
            except ValueError:
                return False
            if not bucket:
                items.pop(i)
            else:
                items[i][1] = bucket

        node["items"] = items
        tx.put_page(page_id, PT_INDEX, _encode_index_node(node))
        return True

    def _insert_into(self, tx: Transaction, page_id: int, key: IndexKey, rowid: int, *, unique: bool) -> Optional[Tuple[IndexKey, int]]:
        node = _decode_index_node(tx.read_page(page_id))
        if int(node.get("leaf", 0)) == 1:
            return self._insert_into_leaf(tx, page_id, node, key, rowid, unique=unique)
        return self._insert_into_internal(tx, page_id, node, key, rowid, unique=unique)

    def _insert_into_leaf(self, tx: Transaction, page_id: int, node: Dict[str, Any], key: IndexKey, rowid: int, *, unique: bool) -> Optional[Tuple[IndexKey, int]]:
        items: List[Any] = list(node.get("items", []))
        keys = [bytes(it[0]) for it in items]
        i = bisect.bisect_left(keys, key)
        if i < len(items) and items[i][0] == key:
            bucket = list(items[i][1])
            if unique and bucket:
                raise MpdbError(f"Unique constraint failed (index): key={key}")
            bucket.append(int(rowid))
            items[i][1] = bucket
        else:
            items.insert(i, [key, [int(rowid)]])

        node["items"] = items
        payload = _encode_index_node(node)
        if len(payload) <= self._node_capacity():
            tx.put_page(page_id, PT_INDEX, payload)
            return None

        # Split leaf.
        mid = len(items) // 2
        right_items = items[mid:]
        left_items = items[:mid]

        new_pid = self.db._alloc_page_id()
        new_node = {"leaf": 1, "next": int(node.get("next", 0)), "items": right_items}

        node["items"] = left_items
        node["next"] = int(new_pid)

        tx.put_page(page_id, PT_INDEX, _encode_index_node(node))
        tx.put_page(new_pid, PT_INDEX, _encode_index_node(new_node))

        split_key = bytes(right_items[0][0])
        return split_key, int(new_pid)

    def _insert_into_internal(self, tx: Transaction, page_id: int, node: Dict[str, Any], key: IndexKey, rowid: int, *, unique: bool) -> Optional[Tuple[IndexKey, int]]:
        keys: List[IndexKey] = list(map(bytes, node.get("keys", [])))
        children: List[int] = list(map(int, node.get("children", [])))
        if len(children) != len(keys) + 1:
            raise MpdbError("Corrupted index internal node")

        i = bisect.bisect_right(keys, key)
        child_pid = int(children[i])
        split = self._insert_into(tx, child_pid, key, rowid, unique=unique)
        if split is None:
            return None

        split_key, new_child_pid = split
        keys.insert(i, split_key)
        children.insert(i + 1, int(new_child_pid))
        node["keys"] = keys
        node["children"] = children

        payload = _encode_index_node(node)
        if len(payload) <= self._node_capacity():
            tx.put_page(page_id, PT_INDEX, payload)
            return None

        # Split internal node: promote median.
        mid = len(keys) // 2
        promote = bytes(keys[mid])

        left_keys = keys[:mid]
        right_keys = keys[mid + 1:]
        left_children = children[:mid + 1]
        right_children = children[mid + 1:]

        new_pid = self.db._alloc_page_id()
        left_node = {"leaf": 0, "keys": left_keys, "children": left_children}
        right_node = {"leaf": 0, "keys": right_keys, "children": right_children}

        tx.put_page(page_id, PT_INDEX, _encode_index_node(left_node))
        tx.put_page(new_pid, PT_INDEX, _encode_index_node(right_node))
        return promote, int(new_pid)

    def _node_capacity(self) -> int:
        # Keep some slack for future header/extensions.
        return int(self.db.page_size - PAGE_HDR_SIZE - 128)

    # -------------------- ordered scans (leaf chain) --------------------

    def iter_items(self, *, start: IndexKey | None = None, end: IndexKey | None = None) -> Iterator[Tuple[IndexKey, List[int]]]:
        """Iterate leaf items in key order.

        Keys are binary sortable keys (see _encode_sort_key).
        - start: inclusive lower bound (None = from smallest)
        - end: exclusive upper bound (None = to largest)

        Note: this reads committed pages only (no transaction overlay).
        """

        # Find leftmost leaf.
        pid = int(self.root)
        while True:
            node = _decode_index_node(self.db._read_page(pid))
            if int(node.get("leaf", 0)) == 1:
                break
            children = list(map(int, node.get("children", [])))
            if not children:
                return
            pid = int(children[0])

        # Walk leaf chain.
        current = int(pid)
        while current:
            node = _decode_index_node(self.db._read_page(current))
            if int(node.get("leaf", 0)) != 1:
                raise MpdbError("Corrupted index: leaf chain points to non-leaf")

            items = list(node.get("items", []))
            if start is not None:
                keys = [bytes(it[0]) for it in items]
                i = bisect.bisect_left(keys, start)
                items = items[i:]

            for k, bucket in items:
                kb = bytes(k)
                if end is not None and kb >= end:
                    return
                yield kb, list(map(int, bucket))

            current = int(node.get("next", 0) or 0)

    def iter_rowids(self, *, start: IndexKey | None = None, end: IndexKey | None = None) -> Iterator[int]:
        """Iterate rowids in key order (stable within key)."""
        for _k, bucket in self.iter_items(start=start, end=end):
            for rid in bucket:
                yield int(rid)


DATA_PAGE_MAGIC = b"MPDT"  # mpdb Data-page
DATA_PAGE_VER = 1

# Data page header (16 bytes):
#   magic[4], ver(u16), slot_count(u16), free_start(u16), free_end(u16), flags(u16), reserved(u16)
DATA_HDR = struct.Struct("<4sHHHHHH")
DATA_HDR_SIZE = DATA_HDR.size

# Slot entry (4 bytes): offset(u16), length(u16)
DATA_SLOT = struct.Struct("<HH")
DATA_SLOT_SIZE = DATA_SLOT.size


def _is_data_slot_page(payload: bytes) -> bool:
    return len(payload) >= DATA_HDR_SIZE and payload[:4] == DATA_PAGE_MAGIC


def _data_page_init(max_payload: int) -> bytes:
    """Create an empty slot-directory data page payload.

    The payload buffer is max_payload bytes. It will compress well due to zeros.
    """
    buf = bytearray(max_payload)
    free_start = DATA_HDR_SIZE
    free_end = max_payload
    hdr = DATA_HDR.pack(DATA_PAGE_MAGIC, DATA_PAGE_VER, 0, free_start, free_end, 0, 0)
    buf[:DATA_HDR_SIZE] = hdr
    return bytes(buf)


def _data_page_can_fit(max_payload: int, rec_len: int) -> bool:
    # Empty page must accommodate header + record + slot entry.
    return DATA_HDR_SIZE + rec_len + DATA_SLOT_SIZE <= max_payload


def _data_page_insert(payload: bytes, record: bytes) -> tuple[bytes, int]:
    """Insert record bytes into a slot-format data page.

    Returns (new_payload, slot_pos) where slot_pos is the insertion-order slot index
    (0-based, oldest=0). This slot_pos is stable for locating the record later.

    Raises MpdbError if there is not enough free space.
    """
    if not _is_data_slot_page(payload):
        raise MpdbError("Not a slot-format data page")

    if len(payload) < DATA_HDR_SIZE:
        raise MpdbError("Corrupted data page")

    magic, ver, slot_count, free_start, free_end, flags, reserved = DATA_HDR.unpack_from(payload, 0)
    if magic != DATA_PAGE_MAGIC or ver != DATA_PAGE_VER:
        raise MpdbError("Unsupported data page version")

    max_payload = len(payload)
    rec_len = len(record)

    if rec_len == 0:
        raise MpdbError("Empty record")
    if rec_len > 0xFFFF:
        raise MpdbError("Record too large for 16-bit slot length")

    def _entry_off(slot_pos: int) -> int:
        # slot_pos: 0..slot_count-1 (oldest=0). Slot entries are stored LIFO at the tail.
        return int(free_end) + (int(slot_count) - 1 - int(slot_pos)) * DATA_SLOT_SIZE

    def _try_reuse(buf: bytearray) -> tuple[bool, int]:
        """Try to reuse a tombstone slot (length==0) without growing the slot directory."""
        if int(slot_count) == 0:
            return False, -1

        # Prefer reusing the *newest* tombstone so apparent order stays append-like.
        for slot_pos in range(int(slot_count) - 1, -1, -1):
            off = _entry_off(slot_pos)
            so, sln = DATA_SLOT.unpack_from(buf, off)
            if int(sln) == 0:
                # Found tombstone slot.
                new_free_start = int(free_start) + rec_len
                if new_free_start > int(free_end):
                    return False, -1
                rec_off = int(free_start)
                if rec_off > 0xFFFF:
                    raise MpdbError("Record offset exceeds 16-bit slot limits")
                buf[rec_off:rec_off + rec_len] = record
                buf[off:off + DATA_SLOT_SIZE] = DATA_SLOT.pack(rec_off, rec_len)

                # Update header (slot_count unchanged, free_end unchanged).
                hdr = DATA_HDR.pack(
                    DATA_PAGE_MAGIC,
                    DATA_PAGE_VER,
                    int(slot_count),
                    int(new_free_start),
                    int(free_end),
                    int(flags),
                    int(reserved),
                )
                buf[:DATA_HDR_SIZE] = hdr
                return True, int(slot_pos)
        return False, -1

    def _compact_in_place(buf: bytearray) -> None:
        """Compact live records to reclaim space while keeping slot positions stable."""
        sc = int(slot_count)
        fe = int(free_end)
        write_pos = DATA_HDR_SIZE

        # Iterate slots oldest->newest by slot_pos.
        for slot_pos in range(sc):
            eoff = _entry_off(slot_pos)
            so, sln = DATA_SLOT.unpack_from(buf, eoff)
            if int(sln) == 0:
                continue
            rec_off = int(so)
            rec_len2 = int(sln)
            if rec_off < DATA_HDR_SIZE or rec_off + rec_len2 > fe:
                raise MpdbError("Corrupted slot entry during compaction")

            rec = bytes(buf[rec_off:rec_off + rec_len2])
            if write_pos + rec_len2 > fe:
                # Should not happen if the page was consistent.
                raise MpdbError("Data page compaction overflow")
            buf[write_pos:write_pos + rec_len2] = rec
            buf[eoff:eoff + DATA_SLOT_SIZE] = DATA_SLOT.pack(write_pos, rec_len2)
            write_pos += rec_len2

        # Zero the freed region for better compression.
        if write_pos < fe:
            buf[write_pos:fe] = b"\x00" * (fe - write_pos)

        hdr = DATA_HDR.pack(
            DATA_PAGE_MAGIC,
            DATA_PAGE_VER,
            int(slot_count),
            int(write_pos),
            int(free_end),
            int(flags),
            int(reserved),
        )
        buf[:DATA_HDR_SIZE] = hdr

    # First: try to reuse tombstones (fast path).
    buf = bytearray(payload)
    ok, slot_pos = _try_reuse(buf)
    if ok:
        return bytes(buf), int(slot_pos)

    # If record area is tight, compact and try reuse again.
    _compact_in_place(buf)
    magic2, ver2, sc2, fs2, fe2, flags2, reserved2 = DATA_HDR.unpack_from(buf, 0)
    # refresh locals
    slot_count = sc2
    free_start = fs2
    free_end = fe2
    flags = flags2
    reserved = reserved2

    ok, slot_pos = _try_reuse(buf)
    if ok:
        return bytes(buf), int(slot_pos)

    # No tombstones: append a new slot.
    slot_pos = int(slot_count)

    new_free_end = int(free_end) - DATA_SLOT_SIZE
    new_free_start = int(free_start) + rec_len
    if new_free_start > new_free_end:
        # One more attempt after compaction (already compacted once above).
        raise MpdbError("Data page is full")

    rec_off = int(free_start)
    if rec_off > 0xFFFF:
        raise MpdbError("Record offset exceeds 16-bit slot limits")
    buf[rec_off:rec_off + rec_len] = record

    buf[new_free_end:new_free_end + DATA_SLOT_SIZE] = DATA_SLOT.pack(rec_off, rec_len)

    slot_count = int(slot_count) + 1
    hdr = DATA_HDR.pack(
        DATA_PAGE_MAGIC,
        DATA_PAGE_VER,
        int(slot_count),
        int(new_free_start),
        int(new_free_end),
        int(flags),
        int(reserved),
    )
    buf[:DATA_HDR_SIZE] = hdr

    if len(buf) != max_payload:
        raise MpdbError("Internal error: data page size changed")
    return bytes(buf), int(slot_pos)

def _data_page_get_record(payload: bytes, slot_pos: int) -> bytes:
    """Fetch raw record bytes by insertion-order slot index.

    slot_pos: 0-based insertion order (oldest=0).
    """
    if not _is_data_slot_page(payload):
        raise MpdbError("Not a slot-format data page")
    if len(payload) < DATA_HDR_SIZE:
        raise MpdbError("Corrupted data page")

    magic, ver, slot_count, free_start, free_end, flags, reserved = DATA_HDR.unpack_from(payload, 0)
    if magic != DATA_PAGE_MAGIC or ver != DATA_PAGE_VER:
        raise MpdbError("Unsupported data page version")

    sc = int(slot_count)
    if slot_pos < 0 or slot_pos >= sc:
        raise MpdbError("slot_pos out of range")

    dir_start = int(free_end)
    entry_off = dir_start + (sc - 1 - int(slot_pos)) * DATA_SLOT_SIZE
    if entry_off + DATA_SLOT_SIZE > len(payload):
        raise MpdbError("Corrupted slot directory")

    off, ln = DATA_SLOT.unpack_from(payload, entry_off)
    if int(ln) == 0:
        raise MpdbError("Deleted/empty slot")

    rec_off = int(off)
    rec_len = int(ln)
    if rec_off < DATA_HDR_SIZE or rec_off + rec_len > dir_start:
        raise MpdbError("Corrupted slot entry")

    return payload[rec_off:rec_off + rec_len]


def _data_page_mark_deleted(payload: bytes, slot_pos: int) -> bytes:
    """Mark a slot as deleted by setting its slot length to 0.

    Notes:
    - This is a tombstone delete; it does not reclaim space.
    - Iterators (_iter_records) already skip slots with length==0.
    """
    if not _is_data_slot_page(payload):
        raise MpdbError("Not a slot-format data page")
    if len(payload) < DATA_HDR_SIZE:
        raise MpdbError("Corrupted data page")

    magic, ver, slot_count, free_start, free_end, flags, reserved = DATA_HDR.unpack_from(payload, 0)
    if magic != DATA_PAGE_MAGIC or ver != DATA_PAGE_VER:
        raise MpdbError("Unsupported data page version")

    sc = int(slot_count)
    if slot_pos < 0 or slot_pos >= sc:
        raise MpdbError("slot_pos out of range")

    dir_start = int(free_end)
    entry_off = dir_start + (sc - 1 - int(slot_pos)) * DATA_SLOT_SIZE
    if entry_off + DATA_SLOT_SIZE > len(payload):
        raise MpdbError("Corrupted slot directory")

    off, ln = DATA_SLOT.unpack_from(payload, entry_off)
    if int(ln) == 0:
        # already deleted
        return payload

    buf = bytearray(payload)
    buf[entry_off:entry_off + DATA_SLOT_SIZE] = DATA_SLOT.pack(int(off), 0)
    return bytes(buf)



def _iter_records_legacy(payload: bytes) -> Iterator[Tuple[int, Dict[str, Any]]]:
    """Legacy record stream: [u32 len][json bytes]..."""
    p = 0
    n = len(payload)
    while p + 4 <= n:
        (ln,) = struct.unpack_from("<I", payload, p)
        p += 4
        if ln <= 0 or p + ln > n:
            return
        raw = payload[p:p + ln]
        p += ln
        obj = json.loads(raw.decode("utf-8"))
        rowid = int(obj.get("rowid", 0))
        data = obj.get("data", {})
        yield rowid, data


def _iter_records(payload: bytes) -> Iterator[Tuple[int, Dict[str, Any]]]:
    """Iterate records stored in a data page payload.

    Supports:
    - Slot-directory format (v1): header + records + slot directory at the tail.
    - Legacy stream format (v0): [u32 len][json bytes]...
    """
    if not payload:
        return

    if not _is_data_slot_page(payload):
        yield from _iter_records_legacy(payload)
        return

    if len(payload) < DATA_HDR_SIZE:
        return

    magic, ver, slot_count, free_start, free_end, flags, reserved = DATA_HDR.unpack_from(payload, 0)
    if magic != DATA_PAGE_MAGIC or ver != DATA_PAGE_VER:
        return

    # Slot directory lives in [free_end .. end), slot_count entries.
    end = len(payload)
    dir_start = int(free_end)
    dir_end = dir_start + int(slot_count) * DATA_SLOT_SIZE
    if dir_end > end:
        # Corruption: slot directory exceeds payload.
        return

    # Slots are appended in insertion order (LIFO at tail). We iterate in physical order.
    # To present stable row order, we iterate from oldest to newest by reading entries in reverse.
    for i in range(int(slot_count)):
        entry_off = dir_start + (int(slot_count) - 1 - i) * DATA_SLOT_SIZE
        off, ln = DATA_SLOT.unpack_from(payload, entry_off)
        if ln == 0:
            continue
        rec_off = int(off)
        rec_len = int(ln)
        if rec_off < DATA_HDR_SIZE or rec_off + rec_len > dir_start:
            continue
        raw = payload[rec_off:rec_off + rec_len]
        try:
            obj = json.loads(raw.decode("utf-8"))
        except Exception:
            continue
        rowid = int(obj.get("rowid", 0))
        data = obj.get("data", {})
        yield rowid, data


def _match(row: Dict[str, Any], where: Dict[str, Any]) -> bool:
    for k, v in where.items():
        if row.get(k) != v:
            return False
    return True
