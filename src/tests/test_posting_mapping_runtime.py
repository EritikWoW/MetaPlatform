import pytest

from src.configurator.manifest_schema import MANIFEST_TABLE
from src.configurator.domain.posting_mapping import generate_mapped_posting
from src.tests.test_posting_mapping import manifest, mapping, schema
from src.tests.test_runtime_posting import setup_db, source, header, movements
from src.tests.test_runtime_posting import EN
from src.runtime.posting_engine import PostingEngine


@pytest.mark.parametrize("language", ["uk", "en"])
@pytest.mark.parametrize("part", ["", "Lines"])
def test_generated_source_executes_with_distinct_source_and_storage_fields(setup_db, language, part):
    db, _ = setup_db
    rows = manifest()
    for row in rows:
        if row["guid"] not in {"doc", "reg"}:
            db.table(MANIFEST_TABLE).insert(row)
    db.create_table("data_tp_invoice_lines", {"Quantity": {"type": "float"}})
    for guid, qty in [("rec", 3), ("rec", 8), ("other", 999)]:
        db.table("data_tp_invoice_lines").insert({"_doc_guid": guid, "Quantity": qty, "_line_no": qty})
    code = generate_mapped_posting(mapping(part), schema(rows), language=language)
    source(db, code)
    result = PostingEngine(db).post(doc_name="Invoice", doc_guid="rec")
    assert result.ok, result.messages
    assert [r["Amount"] for r in movements(db)] == ([3, 8] if part else [42])
    assert all("Сума" not in r for r in movements(db))
    assert header(db)["_posted"]
    assert PostingEngine(db).unpost(doc_name="Invoice", doc_guid="rec").ok
    assert not movements(db)


@pytest.mark.parametrize("mode", ["forbid", "not_supported"])
def test_configurator_posting_disabled_values_are_enforced(setup_db, mode):
    db, _ = setup_db
    db.table(MANIFEST_TABLE).update({"guid": "doc"}, {"payload": {"posting": mode}})
    result = PostingEngine(db).post(doc_name="Invoice", doc_guid="rec")
    assert not result.ok and "disabled" in str(result.messages)
    assert not header(db)["_posted"] and not movements(db)


@pytest.mark.parametrize("target,expected", [("Movement.Amount", "ok"), ("ThisObject.Amount", "read-only")])
def test_posting_reference_helpers_respect_snapshot_write_boundary(setup_db, target, expected):
    db, _ = setup_db
    text = EN.replace("Movement.Amount = ThisObject.Amount;", f"Fill({target});")
    text += "\nProcedure Fill(Value)\nValue = 18;\nEndProcedure"
    source(db, text)
    result = PostingEngine(db).post(doc_name="Invoice", doc_guid="rec")
    if expected == "ok":
        assert result.ok, result.messages
        assert movements(db)[0]["Amount"] == 18
    else:
        assert not result.ok and expected in str(result.messages)
        assert not header(db)["_posted"] and not movements(db)


def test_cancellation_from_nested_helper_rolls_back_prepared_movements(setup_db):
    db, _ = setup_db
    text = EN.replace("EndProcedure", "StopPosting(Cancel);\nEndProcedure")
    text += "\nProcedure StopPosting(Output)\nOutput = True;\nEndProcedure"
    source(db, text)
    result = PostingEngine(db).post(doc_name="Invoice", doc_guid="rec")
    assert not result.ok and "cancelled" in str(result.messages)
    assert not header(db)["_posted"] and not movements(db)
