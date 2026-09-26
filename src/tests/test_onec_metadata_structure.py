from src.configurator.persistence.manifest_io import (
    add_objects_bulk,
    ensure_manifest_table,
    list_objects,
    make_object,
)
from src.configurator.manifest_schema import MANIFEST_TABLE
from src.infra.onec.metadata_structure import (
    apply_onec_structural_metadata,
    build_metadata_structure,
)
from src.mpdb.mpdb import Mpdb


def _mapping_report_fixture() -> dict:
    return {
        "family_templates": {
            "catalog.object": {
                "slot_examples": {
                    "guid": ["_IDRREF"],
                    "code": ["_CODE"],
                    "description": ["_DESCRIPTION"],
                },
                "target_fields": {
                    "guid": "_guid",
                    "code": "_code",
                    "description": "_description",
                },
            }
        },
        "meta_platform_templates": {
            "catalog": {
                "target_table_pattern": "data_catalog_<name>",
                "system_fields": ["_guid", "_code", "_description", "_deleted"],
            }
        },
        "object_migration_blueprints": [
            {
                "family": "catalog",
                "name": "Products",
                "target_tables": ["data_catalog_products"],
                "preferred_source_kind": "object",
                "template_key": "catalog.object",
                "observed_source_tables": {
                    "count": 1,
                    "examples": ["_Reference92"],
                    "token_examples": ["_REFERENCE92"],
                },
                "mapping_confidence": "template",
            }
        ],
    }


def test_build_metadata_structure_compacts_large_collections() -> None:
    payload = {
        "requisites": [{"name": f"Req{i}"} for i in range(8)],
        "objects": [f"guid-{i:04d}" for i in range(100)],
        "content_refs": [f"Catalog.Ref{i}" for i in range(40)],
    }

    structure = build_metadata_structure(
        obj_type="subsystem",
        name="Administration",
        payload=payload,
        metadata_ref="Subsystem.Administration",
    )

    composition = next(section for section in structure["sections"] if section["key"] == "composition")
    objects_item = next(item for item in composition["items"] if item["key"] == "objects")
    refs_item = next(item for item in composition["items"] if item["key"] == "content_refs")

    assert objects_item["count"] == 100
    assert len(objects_item["preview"]) <= 5
    assert refs_item["count"] == 40
    assert len(refs_item["preview"]) <= 5


def test_apply_onec_structural_metadata_enriches_imported_catalog_payload(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "onec_structural_metadata.mpdb"))
    ensure_manifest_table(db)

    mo = make_object(
        obj_type="catalog",
        name="Products",
        title="Products",
        parent_guid="",
        payload={
            "imported": {
                "source": "1c",
                "src_uuid": "cat-1",
                "origin": "Catalogs/Products.xml",
            },
            "requisites": [{"name": "Description", "type": "string"}],
            "tabular_parts": [{"name": "Prices", "columns": [{"name": "Amount", "type": "number"}]}],
            "default_list_form": "Catalog.Products.Form.ListForm",
        },
    )
    add_objects_bulk(db, [mo])

    updated = apply_onec_structural_metadata(db, _mapping_report_fixture())
    assert updated == 1

    raw_row = db.table(MANIFEST_TABLE).select(where={"guid": mo.guid})[0]
    raw_payload = raw_row["payload"]
    assert str(raw_payload.get("storage_profile_ref") or "").startswith("manifest-payload/")
    assert str(raw_payload.get("metadata_structure_ref") or "").startswith("manifest-payload/")

    obj = next(item for item in list_objects(db) if item.guid == mo.guid)
    assert obj.payload["metadata_ref"] == "Catalog.Products"
    assert obj.payload["storage_profile"]["family"] == "catalog"
    assert obj.payload["storage_profile"]["target_tables"] == ["data_catalog_products"]

    sections = {
        section["key"]: section["items"]
        for section in obj.payload["metadata_structure"]["sections"]
    }
    assert "schema" in sections
    assert "storage" in sections
    schema_items = {item["key"]: item for item in sections["schema"]}
    assert schema_items["requisites"]["count"] == 1
    assert schema_items["tabular_parts"]["count"] == 1
