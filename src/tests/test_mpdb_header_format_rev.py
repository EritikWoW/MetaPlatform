import struct


from mpdb.mpdb import FORMAT_REV, HEADER_SIZE, META_AUTOCHECKPOINT, META_FREELIST, META_LSN, META_WAL, PT_META
from mpdb import Mpdb


def test_header_contains_format_rev(tmp_path):
    p = tmp_path / "t.mpdb"
    db = Mpdb(str(p))
    db.close()

    with open(p, "rb") as f:
        hdr = f.read(HEADER_SIZE)
    fmt_rev = struct.unpack_from("<H", hdr, 14)[0]
    assert fmt_rev == FORMAT_REV


def test_doctor_ok_on_fresh_db(tmp_path):
    from mpdb.doctor import check

    p = tmp_path / "t2.mpdb"
    db = Mpdb(str(p))
    db.close()

    rep = check(p)
    assert rep.ok is True
    assert rep.pages_bad == 0


def test_legacy_format_rev_zero_is_migrated_on_open(tmp_path):
    p = tmp_path / "legacy_fmt0.mpdb"
    db = Mpdb(str(p))
    db._meta.pop(META_FREELIST, None)
    db._meta.pop(META_AUTOCHECKPOINT, None)
    db._meta.pop(META_LSN, None)
    db._meta.pop(META_WAL, None)
    db._format_rev = 0
    db._write_page(1, PT_META, db._encode_meta(db._meta))
    db._write_header()
    db.close()

    db2 = Mpdb(str(p))
    try:
        assert db2._format_rev == FORMAT_REV
        assert db2._meta[META_FREELIST] == {"head": 0, "count": 0}
        assert db2._meta[META_AUTOCHECKPOINT]["commits"] == 200
        assert db2._meta[META_LSN] == 0
        assert "start" in db2._meta[META_WAL]
        assert "end" in db2._meta[META_WAL]
    finally:
        db2.close()

    with open(p, "rb") as f:
        hdr = f.read(HEADER_SIZE)
    fmt_rev = struct.unpack_from("<H", hdr, 14)[0]
    assert fmt_rev == FORMAT_REV


def test_legacy_format_rev_one_is_migrated_on_open(tmp_path):
    p = tmp_path / "legacy_fmt1.mpdb"
    db = Mpdb(str(p))
    db._format_rev = 1
    db._write_page(1, PT_META, db._encode_meta(db._meta))
    db._write_header()
    db.close()

    db2 = Mpdb(str(p))
    try:
        assert db2._format_rev == FORMAT_REV
    finally:
        db2.close()

    with open(p, "rb") as f:
        hdr = f.read(HEADER_SIZE)
    fmt_rev = struct.unpack_from("<H", hdr, 14)[0]
    assert fmt_rev == FORMAT_REV
