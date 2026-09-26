from mpdb import Mpdb
from mp_platform import MpPlatform


def test_register_balance_and_turnover(tmp_path):
    db = Mpdb(str(tmp_path / "r.mpdb"))
    plat = MpPlatform(db)

    reg = plat.create_register(
        "Stock",
        dimensions=["warehouse", "sku"],
        resources=["qty", "amount"],
    )

    plat.register_post(
        reg,
        period=1,
        doc_id=1,
        dimensions={"warehouse": "WH1", "sku": "A"},
        resources={"qty": 10, "amount": 100},
    )
    plat.register_post(
        reg,
        period=2,
        doc_id=2,
        dimensions={"warehouse": "WH1", "sku": "A"},
        resources={"qty": -3, "amount": -30},
    )
    plat.register_post(
        reg,
        period=3,
        doc_id=3,
        dimensions={"warehouse": "WH1", "sku": "B"},
        resources={"qty": 5, "amount": 50},
    )

    bal = plat.register_balance(reg, as_of=2, dimensions={"warehouse": "WH1", "sku": "A"})
    assert bal["qty"] == 7.0
    assert bal["amount"] == 70.0

    # Turnover for warehouse within [2,3] should include both SKUs.
    turn = plat.register_turnover(reg, start=2, end=3, dimensions={"warehouse": "WH1"})
    assert turn["qty"] == 2.0
    assert turn["amount"] == 20.0

    db.close()
