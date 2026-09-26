import struct
from concurrent.futures import ThreadPoolExecutor

import pytest


from mpdb.mpdb import (
    AdaptiveCompressor,
    CT_NONE,
    CT_LZMA,
    CT_ZSTD,
    CT_ZLIB,
    pack_page_slot,
    unpack_page_slot,
    PAGE_HDR_V0_STRUCT,
    PAGE_HDR_V0_SIZE,
)


def test_v1_roundtrip_none() -> None:
    c = AdaptiveCompressor(level=1)
    page_size = 16384
    payload = b"hello" * 100

    slot = pack_page_slot(page_size, 123, 2, CT_NONE, payload, c, lsn=42)
    page_id, page_type, comp_type, out, lsn = unpack_page_slot(page_size, slot, c)

    assert page_id == 123
    assert page_type == 2
    assert comp_type == CT_NONE
    assert out == payload
    assert lsn == 42


def test_v1_roundtrip_zstd() -> None:
    c = AdaptiveCompressor(level=3)
    page_size = 16384
    payload = (b"a" * 1024) + (b"b" * 2048) + (b"c" * 4096)

    # If zstandard isn't available, AdaptiveCompressor will fall back to zlib.
    comp_type = CT_ZSTD if c.algo == "zstd" else CT_LZMA if c.algo == "lzma" else CT_ZLIB
    slot = pack_page_slot(page_size, 77, 10, comp_type, payload, c, lsn=7)
    page_id, page_type, comp_type, out, lsn = unpack_page_slot(page_size, slot, c)

    assert page_id == 77
    assert page_type == 10
    assert comp_type in (CT_ZSTD, CT_ZLIB, CT_LZMA)
    assert out == payload
    assert lsn == 7


def test_zstd_decompression_is_safe_for_concurrent_readers() -> None:
    c = AdaptiveCompressor(level=3)
    if c.algo != "zstd":
        pytest.skip("zstandard is not available")
    page_size = 16384
    slots = [
        pack_page_slot(page_size, page_id, 2, CT_ZSTD, bytes([page_id]) * 4096, c, lsn=1)
        for page_id in (1, 2)
    ]

    def read(slot: bytes) -> bytes:
        return unpack_page_slot(page_size, slot, c)[3]

    with ThreadPoolExecutor(max_workers=16) as pool:
        payloads = list(pool.map(read, slots * 100))
    assert len(payloads) == 200


def test_v1_corrupt_header_crc_detected() -> None:
    c = AdaptiveCompressor(level=1)
    page_size = 16384
    payload = b"x" * 128
    comp_type = CT_ZSTD if c.algo == "zstd" else CT_LZMA if c.algo == "lzma" else CT_ZLIB
    slot = bytearray(pack_page_slot(page_size, 1, 2, comp_type, payload, c, lsn=1))

    # Flip one byte inside the header area.
    slot[8] ^= 0xFF

    with pytest.raises(Exception):
        unpack_page_slot(page_size, bytes(slot), c)


def test_v1_corrupt_payload_crc_detected() -> None:
    c = AdaptiveCompressor(level=1)
    page_size = 16384
    payload = b"x" * 2048
    slot = bytearray(pack_page_slot(page_size, 9, 2, CT_NONE, payload, c, lsn=1))

    # Flip a byte in the payload area (past header).
    slot[64] ^= 0xAA

    with pytest.raises(Exception):
        unpack_page_slot(page_size, bytes(slot), c)


def test_v1_comp_size_exceeds_page_detected() -> None:
    c = AdaptiveCompressor(level=1)
    page_size = 4096
    payload = b"abcd" * 100
    slot = bytearray(pack_page_slot(page_size, 11, 2, CT_NONE, payload, c, lsn=1))

    # Overwrite comp_size to something impossible.
    # v1 header layout: ... comp_size(u32) starts at offset 4+2+1+1+8+8 = 24
    import struct
    struct.pack_into("<I", slot, 24, 0x7FFFFFFF)

    with pytest.raises(Exception):
        unpack_page_slot(page_size, bytes(slot), c)


def test_v1_empty_payload_roundtrip() -> None:
    c = AdaptiveCompressor(level=1)
    page_size = 4096
    payload = b""
    slot = pack_page_slot(page_size, 1234, 2, CT_NONE, payload, c, lsn=0)
    page_id, page_type, comp_type, out, lsn = unpack_page_slot(page_size, slot, c)
    assert page_id == 1234
    assert page_type == 2
    assert comp_type == CT_NONE
    assert out == b""
    assert lsn == 0


def test_legacy_v0_unpacked() -> None:
    c = AdaptiveCompressor(level=1)
    page_size = 4096
    payload = b"legacy" * 50
    comp_data = c.compress(payload)
    comp_size = len(comp_data)
    orig_size = len(payload)
    orig_crc = struct.unpack("<I", struct.pack("<I", 0))[0]  # dummy init

    import zlib

    orig_crc = zlib.crc32(payload) & 0xFFFFFFFF
    comp_type = CT_ZSTD if c.algo == "zstd" else CT_LZMA if c.algo == "lzma" else CT_ZLIB
    hdr = PAGE_HDR_V0_STRUCT.pack(5, 3, comp_type, comp_size, orig_size, orig_crc)
    slot = hdr + comp_data
    slot += b"\x00" * (page_size - len(slot))

    page_id, page_type, comp_type, out, lsn = unpack_page_slot(page_size, slot, c)
    assert page_id == 5
    assert page_type == 3
    assert comp_type in (CT_ZSTD, CT_ZLIB, CT_LZMA)
    assert out == payload
    assert lsn == 0


def test_legacy_v0_none_unpacked() -> None:
    c = AdaptiveCompressor(level=1)
    page_size = 4096
    payload = b"legacy-none" * 40
    comp_type = CT_NONE
    hdr = PAGE_HDR_V0_STRUCT.pack(6, 3, comp_type, len(payload), len(payload), __import__("zlib").crc32(payload) & 0xFFFFFFFF)
    slot = hdr + payload
    slot += b"\x00" * (page_size - len(slot))

    page_id, page_type, ct, out, lsn = unpack_page_slot(page_size, slot, c)
    assert page_id == 6
    assert page_type == 3
    assert ct == CT_NONE
    assert out == payload
    assert lsn == 0


def test_legacy_v0_bad_crc_detected() -> None:
    c = AdaptiveCompressor(level=1)
    page_size = 4096
    payload = b"legacy" * 50
    comp_data = c.compress(payload)
    comp_type = CT_ZSTD if c.algo == "zstd" else CT_LZMA if c.algo == "lzma" else CT_ZLIB
    hdr = PAGE_HDR_V0_STRUCT.pack(7, 3, comp_type, len(comp_data), len(payload), 0xDEADBEEF)
    slot = hdr + comp_data
    slot += b"\x00" * (page_size - len(slot))
    with pytest.raises(Exception):
        unpack_page_slot(page_size, slot, c)
