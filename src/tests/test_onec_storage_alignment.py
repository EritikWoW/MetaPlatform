from __future__ import annotations

from src.configurator.persistence.schema_deployment import SchemaDeploymentService
from src.infra.onec.storage_alignment import (
    STORAGE_ALIGNMENT_ASSET_KEY,
    build_storage_alignment_report,
    build_storage_alignment_report_from_snapshot,
    store_storage_alignment_asset,
)
from src.mpdb.mpdb import Mpdb
from src.tools.onec_import import run_import_on_db


def _snapshot_fixture() -> dict:
    return {
        "available_sources": ["1cd", "dt", "xml"],
        "paths": {"original": "F:/MetaPlatform/WorkedData/1Cv8.dt"},
        "compatibility": {
            "has_xmlconf": True,
            "has_dt_container": True,
            "has_physical_schema": True,
        },
        "xmlconf": {
            "family_counts": {
                "constant": 12,
                "catalog": 20,
                "document": 9,
                "accumulation_register": 5,
                "information_register": 7,
                "accounting_register": 1,
                "chart_of_accounts": 1,
                "chart_of_characteristic_types": 2,
                "business_process": 1,
                "task": 1,
            }
        },
        "onecd": {"family_counts": {"catalog": 20, "document": 9}},
    }


def test_build_storage_alignment_report_uses_snapshot_profiles(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.infra.onec.storage_alignment.build_onec_compatibility_snapshot",
        lambda source_path, source_kind="": _snapshot_fixture(),
    )

    report = build_storage_alignment_report("F:/MetaPlatform/WorkedData/1Cv8.dt", "auto")

    assert report["coverage"]["migration_readiness"] in {"medium", "high"}
    family_status = {row["family"]: row["status"] for row in report["family_support"]}
    assert family_status["catalog"] == "supported"
    assert family_status["chart_of_accounts"] == "partial"
    assert family_status["business_process"] == "partial"
    assert report["field_alignment"]["catalog"]["coverage_ratio"] == 1.0


def test_store_storage_alignment_asset_persists_json(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "storage_alignment_asset.mpdb"))
    report = build_storage_alignment_report_from_snapshot(_snapshot_fixture(), source_path="fixture.dt")

    asset_key = store_storage_alignment_asset(db, report)
    payload, mime = db.get_asset(asset_key)

    assert asset_key == STORAGE_ALIGNMENT_ASSET_KEY
    assert mime == "application/json"
    assert b'"coverage"' in payload


def test_run_import_on_db_includes_storage_alignment(tmp_path, monkeypatch) -> None:
    xml_root = tmp_path / "XMLConf"
    xml_root.mkdir(parents=True, exist_ok=True)
    (xml_root / "ConfigDumpInfo.xml").write_text("<ConfigDumpInfo/>", encoding="utf-8")
    db = Mpdb(str(tmp_path / "storage_alignment_import.mpdb"))

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
            STORAGE_ALIGNMENT_ASSET_KEY,
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

    assert stats["storage_alignment"]["coverage"]["overall_score"] == 0.73
    assert stats["storage_alignment_asset"] == STORAGE_ALIGNMENT_ASSET_KEY
    assert stats["storage_alignment_error"] == ""


def test_schema_deployment_supports_1c_compatible_object_profiles(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "storage_alignment_profiles.mpdb"))
    rows = [
        {"guid": "const-1", "kind": "object", "type": "constants", "name": "CompanyName"},
        {"guid": "chart-1", "kind": "object", "type": "chart_of_accounts", "name": "MainPlan"},
        {"guid": "bp-1", "kind": "object", "type": "business_process", "name": "ApprovalProc"},
        {"guid": "task-1", "kind": "object", "type": "task", "name": "ReviewTask"},
    ]

    report = SchemaDeploymentService(db).deploy_all(rows)

    assert report.errors == []
    assert db.table("data_constants") is not None
    assert db.table("data_catalog_mainplan") is not None
    assert db.table("data_document_approvalproc") is not None
    assert db.table("data_document_reviewtask") is not None


def test_schema_deployment_creates_catalog_tabular_part_table_with_owner_guid(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "storage_alignment_catalog_tp.mpdb"))
    rows = [
        {"guid": "cat-1", "kind": "object", "type": "catalog", "name": "Partners"},
        {"guid": "tp-folder-1", "kind": "folder", "type": "tabular_parts", "name": "TabularParts", "parent_guid": "cat-1"},
        {"guid": "tp-1", "kind": "object", "type": "tabular_part", "name": "Contacts", "parent_guid": "tp-folder-1"},
        {"guid": "tp-fields-1", "kind": "folder", "type": "fields_folder", "name": "Fields", "parent_guid": "tp-1"},
        {
            "guid": "tp-col-1",
            "kind": "object",
            "type": "field",
            "name": "Phone",
            "parent_guid": "tp-fields-1",
            "payload": {"value_type": "String"},
        },
    ]

    report = SchemaDeploymentService(db).deploy_all(rows)
    schema = db._table_schema_fields("data_tp_partners_contacts", db._meta["tables"]["data_tp_partners_contacts"])

    assert report.errors == []
    assert db.table("data_tp_partners_contacts") is not None
    assert "_owner_guid" in schema
    assert "_doc_guid" not in schema
    assert "Phone" in schema


def test_schema_deployment_keeps_document_tabular_part_table_on_doc_guid(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "storage_alignment_document_tp.mpdb"))
    rows = [
        {"guid": "doc-1", "kind": "object", "type": "document", "name": "SalesOrder"},
        {"guid": "tp-folder-1", "kind": "folder", "type": "tabular_parts", "name": "TabularParts", "parent_guid": "doc-1"},
        {"guid": "tp-1", "kind": "object", "type": "tabular_part", "name": "Lines", "parent_guid": "tp-folder-1"},
        {"guid": "tp-fields-1", "kind": "folder", "type": "fields_folder", "name": "Fields", "parent_guid": "tp-1"},
        {
            "guid": "tp-col-1",
            "kind": "object",
            "type": "field",
            "name": "Amount",
            "parent_guid": "tp-fields-1",
            "payload": {"value_type": "Number"},
        },
    ]

    report = SchemaDeploymentService(db).deploy_all(rows)
    schema = db._table_schema_fields("data_tp_salesorder_lines", db._meta["tables"]["data_tp_salesorder_lines"])

    assert report.errors == []
    assert db.table("data_tp_salesorder_lines") is not None
    assert "_doc_guid" in schema
    assert "_owner_guid" not in schema
    assert "Amount" in schema
