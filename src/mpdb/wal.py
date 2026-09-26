from __future__ import annotations

import io
import struct
import zlib
from typing import Iterator, Tuple

# NOTE: Keep these constants in sync with mpdb.mpdb
WAL_BEGIN = 1
WAL_PUT_PAGE = 2
WAL_SET_META = 3
WAL_COMMIT = 4
WAL_ABORT = 5
WAL_CHECKPOINT = 6
WAL_RELOCATE_INTENT = 7


def crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


# -------------------- Legacy v1 (backward compat) --------------------
WAL_HDR_V1 = struct.Struct("<BQII")  # 1 + 8 + 4 + 4 = 17

# -------------------- Current v2 --------------------
WAL_MAGIC = b"MPWL"
WAL_VER = 2
WAL_FLAGS_NONE = 0

# magic[4], ver:u16, rec_type:u8, flags:u8, txid:u64, length:u32, payload_crc:u32, hdr_crc:u32, reserved:u32
WAL_HDR_V2 = struct.Struct("<4sHBBQIIII")  # 32 bytes
WAL_RELOCATE_INTENT_V1 = struct.Struct("<QQQQ")


def pack_record(rec_type: int, txid: int, payload: bytes, *, flags: int = WAL_FLAGS_NONE) -> bytes:
    """Pack a WAL record in v2 format."""
    payload_crc = crc32(payload)

    hdr_wo_crc = WAL_HDR_V2.pack(
        WAL_MAGIC,
        WAL_VER,
        int(rec_type) & 0xFF,
        int(flags) & 0xFF,
        int(txid),
        int(len(payload)),
        int(payload_crc),
        0,  # hdr_crc placeholder
        0,  # reserved
    )

    # CRC of the header with hdr_crc field logically zeroed
    raw_wo = hdr_wo_crc[:-8] + b"\x00\x00\x00\x00" + hdr_wo_crc[-4:]
    hdr_crc = crc32(raw_wo)

    hdr = WAL_HDR_V2.pack(
        WAL_MAGIC,
        WAL_VER,
        int(rec_type) & 0xFF,
        int(flags) & 0xFF,
        int(txid),
        int(len(payload)),
        int(payload_crc),
        int(hdr_crc),
        0,
    )
    return hdr + payload


def pack_relocate_intent(old_start: int, old_end: int, new_start: int, new_end: int) -> bytes:
    """Pack WAL relocation intent payload.

    Payload fields:
    - old_start / old_end: source WAL byte range before relocation
    - new_start / new_end: destination WAL byte range after relocation
    """
    return WAL_RELOCATE_INTENT_V1.pack(
        int(old_start),
        int(old_end),
        int(new_start),
        int(new_end),
    )


def unpack_relocate_intent(payload: bytes) -> tuple[int, int, int, int]:
    if len(payload) != WAL_RELOCATE_INTENT_V1.size:
        raise ValueError("Invalid WAL relocation intent payload size")
    old_start, old_end, new_start, new_end = WAL_RELOCATE_INTENT_V1.unpack(payload)
    return int(old_start), int(old_end), int(new_start), int(new_end)


def iter_records(f: io.BufferedRandom, start: int, end: int) -> Iterator[Tuple[int, int, bytes]]:
    """Iterate WAL records safely.

    Stops at the first sign of corruption or partial writes. Supports both
    legacy v1 and current v2 formats.

    Yields: (rec_type, txid, payload)
    """
    pos = start
    while pos < end:
        f.seek(pos)
        head4 = f.read(4)
        if len(head4) < 4:
            return

        # v2 record
        if head4 == WAL_MAGIC:
            f.seek(pos)
            raw = f.read(WAL_HDR_V2.size)
            if len(raw) != WAL_HDR_V2.size:
                return

            magic, ver, rec_type, flags, txid, length, payload_crc, hdr_crc, _rsv = WAL_HDR_V2.unpack(raw)
            if magic != WAL_MAGIC or ver != WAL_VER:
                return

            raw_wo = raw[:-8] + b"\x00\x00\x00\x00" + raw[-4:]
            if crc32(raw_wo) != hdr_crc:
                return

            if length < 0 or pos + WAL_HDR_V2.size + length > end:
                return

            payload = f.read(length)
            if len(payload) != length:
                return
            if crc32(payload) != payload_crc:
                return

            yield int(rec_type), int(txid), payload
            pos += WAL_HDR_V2.size + length
            continue

        # legacy v1 record
        f.seek(pos)
        raw = f.read(WAL_HDR_V1.size)
        if len(raw) != WAL_HDR_V1.size:
            return

        rec_type, txid, length, crc = WAL_HDR_V1.unpack(raw)
        if rec_type == 0 and txid == 0 and length == 0 and crc == 0:
            return

        if length < 0 or pos + WAL_HDR_V1.size + length > end:
            return

        payload = f.read(length)
        if len(payload) != length:
            return
        if crc32(payload) != crc:
            return

        yield int(rec_type), int(txid), payload
        pos += WAL_HDR_V1.size + length
