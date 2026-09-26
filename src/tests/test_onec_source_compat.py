from __future__ import annotations

import zlib
from pathlib import Path

from src.infra.onec.source_compat import (
    DT_SIGNATURE,
    ONECDB_SIGNATURE,
    detect_onec_source_kind,
    find_xmlconf_root,
    resolve_onec_source,
)
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


def _write_minimal_xmlconf(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "ConfigDumpInfo.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><ConfigDumpInfo/>",
        encoding="utf-8",
    )
    (root / "Catalogs").mkdir(exist_ok=True)
    (root / "Catalogs" / "Products.xml").write_text(
        "<Meta><Name>Products</Name><Synonym>Products</Synonym></Meta>",
        encoding="utf-8",
    )


def test_resolve_onec_source_detects_dt_and_uses_sibling_xmlconf(tmp_path) -> None:
    dt_path = tmp_path / "1Cv8.dt"
    _write_raw_deflate_dt(dt_path, b"Folder Config")
    xml_root = tmp_path / "XMLConf"
    _write_minimal_xmlconf(xml_root)

    resolved = resolve_onec_source(str(dt_path), "xml")

    assert resolved.detected_kind == "dt"
    assert resolved.semantic_kind == "xml"
    assert Path(resolved.semantic_path) == xml_root
    assert resolved.analysis["signature"] == "1CIBDmpF"
    assert resolved.analysis["version_byte"] == 51


def test_resolve_onec_source_detects_1cd_and_uses_sibling_xmlconf(tmp_path) -> None:
    db_path = tmp_path / "1Cv8.1CD"
    _write_minimal_1cd(db_path)
    xml_root = tmp_path / "XMLConf"
    _write_minimal_xmlconf(xml_root)

    resolved = resolve_onec_source(str(db_path), "auto")

    assert resolved.detected_kind == "1cd"
    assert resolved.semantic_kind == "xml"
    assert Path(resolved.semantic_path) == xml_root
    assert resolved.analysis["signature"] == "1CDBMSV8"
    assert resolved.analysis["page_size"] == 8192


def test_resolve_onec_source_respects_explicit_1cd_kind(tmp_path) -> None:
    db_path = tmp_path / "1Cv8.1CD"
    _write_minimal_1cd(db_path)
    xml_root = tmp_path / "XMLConf"
    _write_minimal_xmlconf(xml_root)

    resolved = resolve_onec_source(str(db_path), "1cd")

    assert resolved.detected_kind == "1cd"
    assert resolved.semantic_kind == "1cd"
    assert Path(resolved.semantic_path) == db_path


def test_resolve_onec_source_detects_standalone_1cd_as_semantic_source(tmp_path) -> None:
    db_path = tmp_path / "1Cv8.1CD"
    _write_minimal_1cd(db_path)

    resolved = resolve_onec_source(str(db_path), "auto")

    assert resolved.detected_kind == "1cd"
    assert resolved.semantic_kind == "1cd"
    assert Path(resolved.semantic_path) == db_path
    assert resolved.analysis["signature"] == "1CDBMSV8"


def test_find_xmlconf_root_accepts_parent_directory_with_xmlconf_child(tmp_path) -> None:
    xml_root = tmp_path / "XMLConf"
    _write_minimal_xmlconf(xml_root)

    assert find_xmlconf_root(tmp_path) == xml_root
    assert detect_onec_source_kind(str(tmp_path), "auto") == "xml"


def test_run_import_on_db_resolves_dt_to_xmlconf_before_manifest_import(tmp_path, monkeypatch) -> None:
    dt_path = tmp_path / "1Cv8.dt"
    _write_raw_deflate_dt(dt_path, b"Folder Config")
    xml_root = tmp_path / "XMLConf"
    _write_minimal_xmlconf(xml_root)

    db = Mpdb(str(tmp_path / "compat_import.mpdb"))
    captured: dict[str, object] = {}

    def _fake_import_manifest_objects(db_obj, source, paths, **kwargs):
        captured["paths"] = list(paths)
        captured["config_dump"] = source.read_bytes("ConfigDumpInfo.xml").decode("utf-8")
        return {}

    monkeypatch.setattr("src.tools.onec_import.import_manifest_objects", _fake_import_manifest_objects)
    monkeypatch.setattr("src.tools.onec_import._enrich_objects_with_requisites", lambda db_obj, source: 0)

    stats = run_import_on_db(
        db,
        source_path=str(dt_path),
        source_kind="xml",
        mode="hard",
        wipe_prefixes=False,
        prune_missing_assets=False,
        store_raw_assets=False,
        store_binary_assets=False,
        store_raw_asset_keys=False,
        store_modules_in_table=False,
    )

    assert "ConfigDumpInfo.xml" in captured["paths"]
    assert "Catalogs/Products.xml" in captured["paths"]
    assert captured["config_dump"] == "<?xml version='1.0' encoding='utf-8'?><ConfigDumpInfo/>"
    assert stats["detected_source_kind"] == "dt"
    assert stats["semantic_source_kind"] == "xml"
    assert Path(str(stats["semantic_source_path"])) == xml_root
