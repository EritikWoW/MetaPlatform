from mpdb import Mpdb
from mp_platform import MpPlatform


def test_catalog_crud(tmp_path):
    db = Mpdb(str(tmp_path / "p.mpdb"))
    plat = MpPlatform(db)
    cat = plat.create_catalog("Nomenclature")

    rec_id = plat.catalog_insert(cat, code="A1", name="Item", data={"x": 1})
    row = plat.catalog_get(cat, rec_id)
    assert row is not None
    assert row["code"] == "A1"

    plat.catalog_update(cat, rec_id, name="Item2")
    row2 = plat.catalog_get(cat, rec_id)
    assert row2 is not None
    assert row2["name"] == "Item2"

    plat.catalog_delete(cat, rec_id)
    assert plat.catalog_get(cat, rec_id) is None
    db.close()


def test_document_create_read(tmp_path):
    db = Mpdb(str(tmp_path / "p2.mpdb"))
    plat = MpPlatform(db)
    doc = plat.create_document("Receipt")

    doc_id = plat.document_create(
        doc,
        header={"number": "0001", "date": 1700000000000, "data": {"org": "X"}},
        rows=[{"sku": "A1", "qty": 2}, {"sku": "B2", "qty": 1}],
    )

    out = plat.document_read(doc, doc_id)
    assert out is not None
    hdr, rows = out
    assert hdr["number"] == "0001"
    assert len(rows) == 2
    assert rows[0]["sku"] == "A1"
    db.close()