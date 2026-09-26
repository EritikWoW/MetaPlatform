from copy import deepcopy

import pytest

from src.configurator.domain.posting_mapping import (
    PostingMappingSchema, generate_mapped_posting,
)


def manifest():
    return [
        dict(guid="doc", type="document", name="Invoice", payload={}),
        dict(guid="attrs", type="attributes", parent_guid="doc"),
        dict(guid="amount", type="attribute", parent_guid="attrs", name="Amount",
             payload={"source_name": "Сума", "value_type": "Number"}),
        dict(guid="parts", type="tabular_parts", parent_guid="doc"),
        dict(guid="lines", type="tabular_part", parent_guid="parts", name="Lines", payload={}),
        dict(guid="cols", type="attributes", parent_guid="lines"),
        dict(guid="qty", type="attribute", parent_guid="cols", name="Quantity", payload={"value_type": "Number"}),
        dict(guid="reg", type="register_accum", name="Stock", payload={}),
        dict(guid="resources", type="resources", parent_guid="reg"),
        dict(guid="res", type="resource", parent_guid="resources", name="Amount",
             payload={"source_name": "Сума", "value_type": "Number", "required": True}),
    ]


def mapping(source=""):
    return {"version": 1, "entries": [{
        "register": "AccumulationRegister.Stock", "source": source, "direction": "expense",
        "fields": {"Period": {"scope": "document", "field": "Date"},
                   "Сума": {"scope": "row" if source else "document", "field": "Quantity" if source else "Сума"}},
    }]}


def schema(rows=None):
    return PostingMappingSchema.from_manifest(rows or manifest(), "doc", ["AccumulationRegister.Stock"])


@pytest.mark.parametrize("language", ["uk", "en"])
@pytest.mark.parametrize("source", ["", "Lines"])
def test_mapping_generates_valid_deterministic_code(language, source):
    plan = mapping(source)
    before = deepcopy(plan)
    code = generate_mapped_posting(plan, schema(), language=language)
    assert code == generate_mapped_posting(plan, schema(), language=language)
    assert plan == before
    assert ".Сума = " in code
    assert (".Lines" in code) == bool(source)
    assert ("Quantity" in code) == bool(source)


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(version=2),
    lambda p: p["entries"].append(deepcopy(p["entries"][0])),
    lambda p: p["entries"][0].update(direction=""),
    lambda p: p["entries"][0].update(source="DeletedLines"),
    lambda p: p["entries"][0]["fields"].pop("Сума"),
    lambda p: p["entries"][0]["fields"].pop("Period"),
    lambda p: p["entries"][0]["fields"]["Сума"].update(field="Deleted"),
    lambda p: p["entries"][0]["fields"]["Сума"].update(field="Date"),
    lambda p: p["entries"][0]["fields"]["Сума"].update(scope="row"),
    lambda p: p["entries"][0]["fields"].update(Typo={"scope": "document", "field": "Сума"}),
])
def test_mapping_rejects_stale_incomplete_or_incompatible_plan(mutation):
    plan = mapping()
    mutation(plan)
    with pytest.raises(ValueError):
        generate_mapped_posting(plan, schema())


def test_mapping_rejects_ambiguous_source_identity_and_unsupported_registers():
    rows = manifest()
    rows.append(dict(guid="duplicate", type="attribute", parent_guid="attrs", name="OtherAmount",
                     payload={"source_name": "Сума"}))
    with pytest.raises(ValueError, match="Ambiguous"):
        schema(rows)
    with pytest.raises(ValueError, match="unsupported"):
        PostingMappingSchema.from_manifest(manifest(), "doc", ["AccountingRegister.Stock"])


def test_generated_temporaries_do_not_shadow_header_fields():
    rows = manifest()
    rows[2]["payload"]["source_name"] = "Movement"
    plan = mapping()
    plan["entries"][0]["fields"]["Сума"]["field"] = "Movement"
    code = generate_mapped_posting(plan, schema(rows), language="en")
    assert "Movement2 = " in code
    assert "ThisObject.Movement;" in code


def test_payload_only_tabular_metadata_can_be_used():
    rows = manifest()
    rows = [r for r in rows if r["guid"] not in {"parts", "lines", "cols", "qty"}]
    rows[0]["payload"] = {"tabular_parts": [{"name": "Lines", "columns": [{"name": "Quantity", "type": "Number"}]}]}
    assert "ThisObject.Lines" in generate_mapped_posting(mapping("Lines"), schema(rows), language="en")
