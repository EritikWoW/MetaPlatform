from __future__ import annotations

from src.infra.onec.physical_mapping import (
    PHYSICAL_MAPPING_ASSET_KEY,
    build_physical_mapping_report_from_catalogs,
    store_physical_mapping_asset,
)
from src.mpdb.mpdb import Mpdb
from src.tools.onec_import import run_import_on_db


def _xml_objects_fixture() -> list[dict]:
    return [
        {
            "family": "catalog",
            "name": "Products",
            "slug": "products",
            "source_path": "XMLConf/Catalogs/Products",
            "target_tables": ["data_catalog_products"],
        },
        {
            "family": "document",
            "name": "Invoice",
            "slug": "invoice",
            "source_path": "XMLConf/Documents/Invoice",
            "target_tables": ["data_document_invoice"],
        },
        {
            "family": "constant",
            "name": "CompanyName",
            "slug": "companyname",
            "source_path": "XMLConf/Constants/CompanyName",
            "target_tables": ["data_constants"],
        },
    ]


def _onecd_tables_fixture() -> list[dict]:
    return [
        {
            "name": "_Reference42",
            "family": "catalog",
            "table_kind": "object",
            "table_token": "_REFERENCE42",
            "field_count": 4,
            "index_count": 1,
            "row_size": 128,
            "data_object_id": 101,
            "fields": ["_IDRREF", "_MARKED", "_CODE", "_DESCRIPTION"],
            "indexes": ["PK_Reference42"],
            "field_mappings": [
                {
                    "source_field": "_IDRREF",
                    "slot": "guid",
                    "target_field": "_guid",
                    "category": "system",
                    "confidence": "high",
                },
                {
                    "source_field": "_MARKED",
                    "slot": "deleted",
                    "target_field": "_deleted",
                    "category": "system",
                    "confidence": "high",
                },
                {
                    "source_field": "_CODE",
                    "slot": "code",
                    "target_field": "_code",
                    "category": "system",
                    "confidence": "high",
                },
                {
                    "source_field": "_DESCRIPTION",
                    "slot": "description",
                    "target_field": "_description",
                    "category": "system",
                    "confidence": "high",
                },
            ],
        },
        {
            "name": "_Document77_VT80",
            "family": "document",
            "table_kind": "tabular_part",
            "table_token": "_DOCUMENT77",
            "field_count": 3,
            "index_count": 0,
            "row_size": 96,
            "data_object_id": 102,
            "fields": ["_Document77_IDRREF", "_LineNo77", "_FLD81"],
            "indexes": [],
            "field_mappings": [
                {
                    "source_field": "_Document77_IDRREF",
                    "slot": "owner_ref",
                    "target_field": "_doc_guid",
                    "category": "system",
                    "confidence": "high",
                },
                {
                    "source_field": "_LineNo77",
                    "slot": "line_no",
                    "target_field": "_line_no",
                    "category": "system",
                    "confidence": "high",
                },
                {
                    "source_field": "_FLD81",
                    "slot": "custom_value",
                    "target_field": "",
                    "category": "custom",
                    "confidence": "low",
                },
            ],
        },
        {
            "name": "_Const10",
            "family": "constant",
            "table_kind": "constant_value",
            "table_token": "_CONST10",
            "field_count": 2,
            "index_count": 0,
            "row_size": 64,
            "data_object_id": 103,
            "fields": ["_RECORDKEY", "_FLD11"],
            "indexes": [],
            "field_mappings": [
                {
                    "source_field": "_RECORDKEY",
                    "slot": "key",
                    "target_field": "key",
                    "category": "system",
                    "confidence": "high",
                },
                {
                    "source_field": "_FLD11",
                    "slot": "value",
                    "target_field": "value",
                    "category": "custom",
                    "confidence": "medium",
                },
            ],
        },
    ]


def _snapshot_fixture() -> dict:
    return {
        "available_sources": ["1cd", "dt", "xml"],
        "compatibility": {
            "has_xmlconf": True,
            "has_dt_container": True,
            "has_physical_schema": True,
        },
    }


def test_build_physical_mapping_report_from_catalogs() -> None:
    report = build_physical_mapping_report_from_catalogs(
        source_path="fixture.dt",
        related_paths={"dt": "fixture.dt", "1cd": "fixture.1CD", "xml": "XMLConf"},
        snapshot=_snapshot_fixture(),
        xml_objects=_xml_objects_fixture(),
        onecd_tables=_onecd_tables_fixture(),
    )

    assert report["summary"]["xml_object_count"] == 3
    assert report["summary"]["onecd_table_count"] == 3
    assert report["family_templates"]["catalog.object"]["target_fields"]["guid"] == "_guid"
    assert report["object_migration_blueprints"][0]["target_tables"] == ["data_catalog_products"]


def test_store_physical_mapping_asset_persists_json(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "physical_mapping_asset.mpdb"))
    report = build_physical_mapping_report_from_catalogs(
        source_path="fixture.dt",
        related_paths={"dt": "fixture.dt", "1cd": "fixture.1CD", "xml": "XMLConf"},
        snapshot=_snapshot_fixture(),
        xml_objects=_xml_objects_fixture(),
        onecd_tables=_onecd_tables_fixture(),
    )

    asset_key = store_physical_mapping_asset(db, report)
    payload, mime = db.get_asset(asset_key)

    assert asset_key == PHYSICAL_MAPPING_ASSET_KEY
    assert mime == "application/json"
    assert b'"family_templates"' in payload


def test_run_import_on_db_includes_physical_mapping_summary(tmp_path, monkeypatch) -> None:
    xml_root = tmp_path / "XMLConf"
    xml_root.mkdir(parents=True, exist_ok=True)
    (xml_root / "ConfigDumpInfo.xml").write_text("<ConfigDumpInfo/>", encoding="utf-8")
    db = Mpdb(str(tmp_path / "physical_mapping_import.mpdb"))

    monkeypatch.setattr("src.tools.onec_import.import_manifest_objects", lambda *args, **kwargs: {})
    monkeypatch.setattr("src.tools.onec_import._enrich_objects_with_requisites", lambda db_obj, source: 0)
    monkeypatch.setattr(
        "src.tools.onec_import._build_and_store_source_snapshot",
        lambda db_obj, source_path, source_kind: (_snapshot_fixture(), "onec_analysis/source_snapshot.json", ""),
    )
    monkeypatch.setattr(
        "src.tools.onec_import._build_and_store_storage_alignment",
        lambda db_obj, snapshot, source_path: (
            {"coverage": {"overall_score": 0.73, "migration_readiness": "medium"}},
            "onec_analysis/storage_alignment.json",
            "",
        ),
    )
    monkeypatch.setattr(
        "src.tools.onec_import._build_and_store_physical_mapping",
        lambda db_obj, source_path, source_kind, snapshot: (
            {
                "summary": {
                    "xml_object_count": 3,
                    "onecd_table_count": 3,
                    "object_blueprint_count": 3,
                }
            },
            PHYSICAL_MAPPING_ASSET_KEY,
            "",
        ),
    )

    stats = run_import_on_db(
        db,
        source_path=str(xml_root),
        source_kind="xml",
        mode="hard",
        wipe_prefixes=False,
        prune_missing_assets=False,
        store_raw_assets=False,
        store_binary_assets=False,
        store_raw_asset_keys=False,
        store_modules_in_table=False,
    )

    assert stats["physical_mapping_summary"]["xml_object_count"] == 3
    assert stats["physical_mapping_asset"] == PHYSICAL_MAPPING_ASSET_KEY
    assert stats["physical_mapping_error"] == ""
