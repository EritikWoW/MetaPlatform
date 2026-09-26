from __future__ import annotations

import zlib
from pathlib import Path

from src.infra.onec.physical_schema import (
    build_onec_compatibility_snapshot,
    summarize_xmlconf_root,
)
from src.infra.onec.source_compat import DT_SIGNATURE, ONECDB_SIGNATURE
from src.mpdb.mpdb import Mpdb
from src.tools.onec_import import run_import_on_db


def _write_raw_deflate_dt(path: Path, payload: bytes) -> None:
    compressor = zlib.compressobj(level=6, wbits=-15)
    body = compressor.compress(payload) + compressor.flush()
    path.write_bytes(DT_SIGNATURE + bytes([51]) + body)


def _write_minimal_1cd(path: Path) -> None:
    header = bytearray(64)
    header[:8] = ONECDB_SIGNATURE
    header[8:12] = bytes([8, 3, 8, 0])
    header[12:16] = (123).to_bytes(4, "little", signed=False)
    header[20:24] = (8192).to_bytes(4, "little", signed=False)
    path.write_bytes(bytes(header))


def _write_xmlconf_fixture(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "ConfigDumpInfo.xml").write_text("<ConfigDumpInfo/>", encoding="utf-8")
    (root / "Catalogs" / "Products" / "Forms" / "ItemForm").mkdir(parents=True, exist_ok=True)
    (root / "Catalogs" / "Products" / "Commands" / "Print").mkdir(parents=True, exist_ok=True)
    (root / "Documents" / "Invoice" / "Forms" / "ObjectForm").mkdir(parents=True, exist_ok=True)
    (root / "CommonForms" / "MainForm").mkdir(parents=True, exist_ok=True)
    ext_root = root / "Ext"
    ext_root.mkdir(parents=True, exist_ok=True)
    (ext_root / "ManagedApplicationModule.bsl").write_text("Procedure Test() EndProcedure", encoding="utf-8")
    (root / "Catalogs" / "Products" / "Ext").mkdir(parents=True, exist_ok=True)
    (root / "Catalogs" / "Products" / "Ext" / "ObjectModule.bsl").write_text(
        "Procedure Test() EndProcedure",
        encoding="utf-8",
    )


def test_summarize_xmlconf_root_counts_nested_content(tmp_path) -> None:
    xml_root = tmp_path / "XMLConf"
    _write_xmlconf_fixture(xml_root)

    summary = summarize_xmlconf_root(xml_root)

    assert summary["family_counts"]["catalog"] == 1
    assert summary["family_counts"]["document"] == 1
    assert summary["family_counts"]["common_form"] == 1
    assert summary["totals"]["metadata_objects"] == 3
    assert summary["totals"]["nested_forms"] == 2
    assert summary["totals"]["nested_commands"] == 1
    assert summary["totals"]["ext_modules"] == 1
    assert summary["totals"]["root_modules"] == 1
    assert summary["samples"]["Catalogs"] == ["Products"]


def test_build_onec_compatibility_snapshot_discovers_sibling_sources(tmp_path, monkeypatch) -> None:
    dt_path = tmp_path / "1Cv8.dt"
    onecd_path = tmp_path / "1Cv8.1CD"
    xml_root = tmp_path / "XMLConf"
    _write_raw_deflate_dt(dt_path, b"Folder DBNames UsersSpr")
    _write_minimal_1cd(onecd_path)
    _write_xmlconf_fixture(xml_root)

    monkeypatch.setattr(
        "src.infra.onec.physical_schema.inspect_1cd_database",
        lambda path, sample_limit=25: {
            "path": str(path),
            "parser_backend": "fake",
            "tables_count": 3,
            "family_counts": {"catalog": 2, "document": 1},
        },
    )

    snapshot = build_onec_compatibility_snapshot(str(dt_path), "auto")

    assert snapshot["available_sources"] == ["1cd", "dt", "xml"]
    assert snapshot["compatibility"]["has_dt_container"] is True
    assert snapshot["compatibility"]["has_xmlconf"] is True
    assert snapshot["compatibility"]["has_physical_schema"] is True
    assert snapshot["family_alignment"]["matched_families"] == ["catalog", "document"]
    assert Path(snapshot["paths"]["dt"]) == dt_path
    assert Path(snapshot["paths"]["1cd"]) == onecd_path
    assert Path(snapshot["paths"]["xml"]) == xml_root


def test_run_import_on_db_includes_source_snapshot(tmp_path, monkeypatch) -> None:
    dt_path = tmp_path / "1Cv8.dt"
    xml_root = tmp_path / "XMLConf"
    _write_raw_deflate_dt(dt_path, b"Folder Config")
    _write_xmlconf_fixture(xml_root)

    db = Mpdb(str(tmp_path / "physical_snapshot.mpdb"))

    monkeypatch.setattr("src.tools.onec_import.import_manifest_objects", lambda *args, **kwargs: {})
    monkeypatch.setattr("src.tools.onec_import._enrich_objects_with_requisites", lambda db_obj, source: 0)
    monkeypatch.setattr(
        "src.tools.onec_import._build_and_store_source_snapshot",
        lambda db_obj, source_path, source_kind: (
            {
                "compatibility": {
                    "has_xmlconf": True,
                    "has_dt_container": True,
                    "has_physical_schema": False,
                }
            },
            "onec_analysis/source_snapshot.json",
            "",
        ),
    )

    stats = run_import_on_db(
        db,
        source_path=str(dt_path),
        source_kind="auto",
        mode="hard",
        wipe_prefixes=False,
        prune_missing_assets=False,
        store_raw_assets=False,
        store_binary_assets=False,
        store_raw_asset_keys=False,
        store_modules_in_table=False,
    )

    assert stats["source_snapshot"]["compatibility"]["has_dt_container"] is True
    assert stats["source_snapshot_asset"] == "onec_analysis/source_snapshot.json"
    assert stats["source_snapshot_error"] == ""
