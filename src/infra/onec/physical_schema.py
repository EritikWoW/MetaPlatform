from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import sys
import zlib
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from .source_compat import (
    DT_SIGNATURE,
    find_xmlconf_root,
    inspect_1cd_header,
    inspect_dt_header,
    resolve_onec_source,
)


KNOWN_DT_SECTIONS = (
    "Config",
    "ConfigSave",
    "Params",
    "Files",
    "DepotFiles",
    "ConfigCAS",
    "ConfigCASSave",
    "UsersSpr",
    "DBNames",
    "DBNamesVersion",
)
ASCII_TOKEN_PREFIXES = {0x5A, 0x9A, 0xFA}
ASCII_PATH_RE = re.compile(r"[A-Za-z]:\\[-A-Za-z0-9_ .(){}\[\]/\\]{6,}")
GUID_RE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:\.(\d+))?",
    re.IGNORECASE,
)
ROOT_MODULE_NAMES = (
    "ManagedApplicationModule.bsl",
    "SessionModule.bsl",
    "OrdinaryApplicationModule.bsl",
    "ExternalConnectionModule.bsl",
)
XMLCONF_DIR_TO_FAMILY = {
    "Catalogs": "catalog",
    "Documents": "document",
    "DocumentJournals": "document_journal",
    "DocumentNumerators": "document_numerator",
    "Enums": "enum",
    "Constants": "constant",
    "AccumulationRegisters": "accumulation_register",
    "InformationRegisters": "information_register",
    "AccountingRegisters": "accounting_register",
    "CalculationRegisters": "calculation_register",
    "BusinessProcesses": "business_process",
    "Tasks": "task",
    "ChartsOfAccounts": "chart_of_accounts",
    "ChartsOfCharacteristicTypes": "chart_of_characteristic_types",
    "ChartsOfCalculationTypes": "chart_of_calculation_types",
    "DataProcessors": "data_processor",
    "Reports": "report",
    "ExternalDataSources": "external_data_source",
    "CommonForms": "common_form",
    "CommonCommands": "common_command",
    "CommonModules": "common_module",
    "CommonTemplates": "common_template",
    "CommonPictures": "common_picture",
    "Languages": "language",
    "Roles": "role",
    "Subsystems": "subsystem",
}
ONECD_TABLE_PREFIX_TO_FAMILY = (
    ("_AccumRg", "accumulation_register"),
    ("_InfoRg", "information_register"),
    ("_Reference", "catalog"),
    ("_Document", "document"),
    ("_Enum", "enum"),
    ("_Const", "constant"),
    ("_AccRg", "accounting_register"),
    ("_CRg", "calculation_register"),
    ("_BProc", "business_process"),
    ("_Task", "task"),
    ("_Chrc", "chart_of_characteristic_types"),
    ("_Acc", "chart_of_accounts"),
    ("_Config", "system"),
    ("_System", "system"),
)
SOURCE_SNAPSHOT_ASSET_KEY = "onec_analysis/source_snapshot.json"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _dedupe_paths(paths: Iterable[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(path)
    return out


def _candidate_source_dirs(*paths: Optional[Path]) -> list[Path]:
    raw_dirs: list[Path] = []
    for path in paths:
        if path is None:
            continue
        if path.is_dir():
            raw_dirs.append(path)
            if path.name.lower() == "xmlconf":
                raw_dirs.append(path.parent)
        else:
            raw_dirs.append(path.parent)
    return _dedupe_paths(raw_dirs)


def discover_related_onec_sources(
    source_path: str | Path,
    *,
    semantic_path: str | Path | None = None,
) -> Dict[str, str]:
    original = Path(source_path)
    semantic = Path(semantic_path) if semantic_path else None
    result: Dict[str, str] = {}

    if original.exists():
        if original.is_file():
            ext = original.suffix.lower()
            if ext == ".dt":
                result["dt"] = str(original)
            elif ext == ".1cd":
                result["1cd"] = str(original)
        elif find_xmlconf_root(original):
            result["xml"] = str(find_xmlconf_root(original) or original)

    if semantic is not None:
        xml_root = find_xmlconf_root(semantic)
        if xml_root is not None:
            result["xml"] = str(xml_root)

    for base_dir in _candidate_source_dirs(original, semantic):
        dt_path = base_dir / "1Cv8.dt"
        if "dt" not in result and dt_path.exists():
            result["dt"] = str(dt_path)
        onecd_path = base_dir / "1Cv8.1CD"
        if "1cd" not in result and onecd_path.exists():
            result["1cd"] = str(onecd_path)
        xml_root = find_xmlconf_root(base_dir)
        if "xml" not in result and xml_root is not None:
            result["xml"] = str(xml_root)

    return result


def _extract_ascii_paths(decoded_text: str, limit: int = 20) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for match in ASCII_PATH_RE.finditer(decoded_text):
        value = match.group(0).strip()
        if value in seen or "\\" not in value:
            continue
        seen.add(value)
        out.append(value)
        if len(out) >= limit:
            break
    return out


def _find_section_offsets(data: bytes) -> Dict[str, list[int]]:
    result: Dict[str, list[int]] = {}
    for name in KNOWN_DT_SECTIONS:
        hits = [match.start() for match in re.finditer(re.escape(name.encode("ascii")), data)]
        if hits:
            result[name] = hits
    return result


def _extract_guid_stats(decoded_text: str) -> Dict[str, Any]:
    base_counts: Counter[str] = Counter()
    suffix_counts: Counter[int] = Counter()
    for match in GUID_RE.finditer(decoded_text):
        base_counts[match.group(1).lower()] += 1
        if match.group(2) is not None:
            suffix_counts[int(match.group(2))] += 1
    return {
        "unique_base_guids": len(base_counts),
        "total_guid_mentions": int(sum(base_counts.values())),
        "suffix_counts": {str(key): value for key, value in sorted(suffix_counts.items())},
    }


def _extract_utf16_strings_near(data: bytes, offset: int, span: int = 2048) -> list[str]:
    chunk = data[max(0, offset): max(0, offset) + span]
    results: list[str] = []
    for shift in range(0, min(16, len(chunk))):
        try:
            text = chunk[shift:].decode("utf-16-le", errors="ignore")
        except Exception:
            continue
        for candidate in re.findall(r"[\u0400-\u04FF][\u0400-\u04FF .]{2,60}", text):
            normalized = " ".join(candidate.split())
            if normalized and normalized not in results:
                results.append(normalized)
        if len(results) >= 20:
            break
    return results[:20]


def _extract_folder_names(data: bytes, limit: int = 20) -> list[dict[str, Any]]:
    found: Counter[str] = Counter()
    for match in re.finditer(b"Folder", data):
        window = data[match.start(): match.start() + 160]
        for shift in range(6, max(6, len(window) - 2)):
            prefix = window[shift]
            if prefix not in ASCII_TOKEN_PREFIXES:
                continue
            size = window[shift + 1]
            if not (1 <= size <= 64):
                continue
            chunk = window[shift + 2: shift + 2 + size]
            if len(chunk) != size or not all(32 <= byte < 127 for byte in chunk):
                continue
            name = chunk.decode("ascii", errors="ignore")
            if name != "Folder":
                found[name] += 1
                break
    return [{"name": name, "count": count} for name, count in found.most_common(limit)]


def inspect_dt_dump(path: str | Path) -> Dict[str, Any]:
    dt_path = Path(path)
    summary = dict(inspect_dt_header(dt_path))
    try:
        raw = dt_path.read_bytes()
        if raw[:8] != DT_SIGNATURE:
            raise ValueError(f"Unexpected DT signature: {raw[:8]!r}")
        decompressed = zlib.decompress(raw[9:], -15)
        decoded_text = decompressed.decode("latin1", errors="ignore")
        section_offsets = _find_section_offsets(decompressed)
        summary.update(
            {
                "compressed_size": len(raw),
                "decompressed_size": len(decompressed),
                "known_sections": sorted(section_offsets.keys()),
                "known_section_offsets": {name: offsets[:5] for name, offsets in section_offsets.items()},
                "guid_stats": _extract_guid_stats(decoded_text),
                "sample_paths": _extract_ascii_paths(decoded_text),
                "folder_names_top": _extract_folder_names(decompressed),
            }
        )
        if "UsersSpr" in section_offsets:
            summary["users_sample"] = _extract_utf16_strings_near(
                decompressed,
                section_offsets["UsersSpr"][0] + len("UsersSpr"),
            )
    except Exception as exc:
        summary["parse_error"] = str(exc)
    return summary


def summarize_xmlconf_root(path: str | Path, *, sample_limit: int = 5) -> Dict[str, Any]:
    xml_root = find_xmlconf_root(path)
    root = xml_root or Path(path)
    summary: Dict[str, Any] = {
        "path": str(root),
        "format": "xml",
        "exists": root.exists(),
        "top_level_counts": {},
        "family_counts": {},
        "samples": {},
        "totals": {
            "metadata_objects": 0,
            "nested_forms": 0,
            "nested_commands": 0,
            "nested_templates": 0,
            "ext_modules": 0,
            "root_modules": 0,
        },
    }
    if not root.exists() or not root.is_dir():
        return summary

    top_level_counts: Dict[str, int] = {}
    family_counts: Dict[str, int] = {}
    samples: Dict[str, list[str]] = {}
    totals = dict(summary["totals"])

    top_dirs = sorted((child for child in root.iterdir() if child.is_dir()), key=lambda p: p.name.lower())
    for top_dir in top_dirs:
        entries = sorted((child for child in top_dir.iterdir() if child.is_dir()), key=lambda p: p.name.lower())
        top_level_counts[top_dir.name] = len(entries)
        family = XMLCONF_DIR_TO_FAMILY.get(top_dir.name)
        if family:
            family_counts[family] = len(entries)
            totals["metadata_objects"] += len(entries)
        if entries:
            samples[top_dir.name] = [entry.name for entry in entries[:sample_limit]]
        for obj_dir in entries:
            forms_dir = obj_dir / "Forms"
            if forms_dir.is_dir():
                totals["nested_forms"] += sum(1 for child in forms_dir.iterdir() if child.is_dir())
            commands_dir = obj_dir / "Commands"
            if commands_dir.is_dir():
                totals["nested_commands"] += sum(1 for child in commands_dir.iterdir() if child.is_dir())
            templates_dir = obj_dir / "Templates"
            if templates_dir.is_dir():
                totals["nested_templates"] += sum(1 for child in templates_dir.iterdir() if child.is_dir())
            ext_dir = obj_dir / "Ext"
            if ext_dir.is_dir():
                totals["ext_modules"] += sum(1 for _ in ext_dir.rglob("*.bsl"))

    root_ext = root / "Ext"
    if root_ext.is_dir():
        totals["root_modules"] = sum(1 for name in ROOT_MODULE_NAMES if (root_ext / name).exists())

    summary["top_level_counts"] = top_level_counts
    summary["family_counts"] = family_counts
    summary["samples"] = samples
    summary["totals"] = totals
    return summary


def _classify_onecd_table_family(name: str) -> str:
    upper_name = str(name or "").upper()
    for prefix, family in ONECD_TABLE_PREFIX_TO_FAMILY:
        if upper_name.startswith(prefix.upper()):
            return family
    return "other"


def _load_module_from_path(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _candidate_parser_roots() -> list[Path]:
    candidates: list[Path] = []
    env_value = str(os.environ.get("META_PARSE1CD_PARSER") or "").strip()
    if env_value:
        candidates.append(Path(env_value))
    candidates.append(_repo_root() / "WorkedData" / "Parse1CD" / "parser")
    candidates.append(Path("F:/Parse1CD/parser"))

    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        if (candidate / "database_parser.py").exists():
            root = candidate
        elif (candidate / "parser" / "database_parser.py").exists():
            root = candidate / "parser"
        else:
            continue
        try:
            key = str(root.resolve()).lower()
        except Exception:
            key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        roots.append(root)
    return roots


@lru_cache(maxsize=1)
def _load_parse1cd_backend() -> tuple[Path, Any]:
    last_error: Exception | None = None
    for parser_root in _candidate_parser_roots():
        previous_modules = {
            name: sys.modules.get(name)
            for name in ("models", "utils", "value_decoder", "reference_resolver", "schema_reader", "database_parser")
        }
        try:
            sys.modules["models"] = _load_module_from_path("models", parser_root / "models.py")
            for module_name in ("utils", "value_decoder", "reference_resolver", "schema_reader"):
                module_path = parser_root / f"{module_name}.py"
                if module_path.exists():
                    sys.modules[module_name] = _load_module_from_path(module_name, module_path)
            database_parser = _load_module_from_path("database_parser", parser_root / "database_parser.py")
            from .parse1cd_compat import patch_parse1cd_database_parser

            patch_parse1cd_database_parser(database_parser)
            return parser_root, database_parser
        except Exception as exc:
            last_error = exc
        finally:
            for name, module in previous_modules.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
    raise FileNotFoundError(f"Parse1CD backend not found or could not be loaded: {last_error}")


def _make_read_only_onecd_class(base_cls):
    try:
        source_doc = str(getattr(sys.modules.get(base_cls.__module__), "__doc__", "") or "").lower()
    except Exception:
        source_doc = ""
    if "read-only" in source_doc or not hasattr(base_cls, "_parse_file_header"):
        return base_cls

    class ReadOnlyOneCDatabase(base_cls):
        def open(self) -> bool:
            try:
                if not Path(self.filepath).exists():
                    return False
                self._fh = open(self.filepath, "rb")
                self.header = self._parse_file_header()
                if not self.header:
                    return False
                if self.db_version >= (8, 3):
                    ok = self._open_83()
                else:
                    ok = self._open_82()
                return bool(ok and self.tables)
            except Exception:
                self.close()
                return False

    return ReadOnlyOneCDatabase


def inspect_1cd_database(
    path: str | Path,
    *,
    sample_limit: int = 25,
) -> Dict[str, Any]:
    onecd_path = Path(path)
    summary = dict(inspect_1cd_header(onecd_path))
    summary["read_only"] = True

    try:
        parser_root, backend = _load_parse1cd_backend()
        db_cls = _make_read_only_onecd_class(backend.OneCDatabase)
        db = db_cls(str(onecd_path))
        with contextlib.redirect_stdout(io.StringIO()):
            opened = db.open()
        summary["parser_backend"] = "Parse1CD"
        summary["parser_root"] = str(parser_root)
        summary["opened"] = bool(opened)
        if not opened:
            summary["parse_error"] = "Parse1CD backend could not open the 1CD file."
            return summary

        try:
            db_info = db.get_database_info() or {}
            tables = dict(getattr(db, "tables", {}) or {})
            data_pages = dict(getattr(db, "_table_data_pages", {}) or {})

            family_counts: Counter[str] = Counter()
            total_fields = 0
            total_indexes = 0
            total_blob_fields = 0
            tables_with_blob_fields = 0
            sample_tables: list[Dict[str, Any]] = []

            for name, table in tables.items():
                fields = list(getattr(table, "fields", []) or [])
                indexes = list(getattr(table, "indexes", []) or [])
                blob_fields = list(getattr(table, "blob_fields", []) or [])
                family = _classify_onecd_table_family(str(name))
                family_counts[family] += 1
                total_fields += len(fields)
                total_indexes += len(indexes)
                total_blob_fields += len(blob_fields)
                if blob_fields:
                    tables_with_blob_fields += 1
                sample_tables.append(
                    {
                        "name": str(name),
                        "family": family,
                        "field_count": len(fields),
                        "index_count": len(indexes),
                        "row_size": int(getattr(table, "row_size", 0) or 0),
                        "data_object_id": int(getattr(table, "data_object_id", 0) or 0),
                        "blob_field_count": len(blob_fields),
                        "data_page_count": len(data_pages.get(name, []) or []),
                        "field_preview": [str(field.name) for field in fields[:8]],
                    }
                )

            sample_tables.sort(
                key=lambda item: (
                    -int(item["field_count"]),
                    -int(item["index_count"]),
                    str(item["name"]).lower(),
                )
            )
            summary.update(
                {
                    "version": str(db_info.get("version") or summary.get("version") or ""),
                    "page_size": int(db_info.get("page_size") or summary.get("page_size") or 0),
                    "total_pages": int(db_info.get("total_pages") or summary.get("total_pages") or 0),
                    "db_format": str(db_info.get("db_format") or ""),
                    "tables_count": len(tables),
                    "tables_with_fields": sum(
                        1 for table in tables.values() if list(getattr(table, "fields", []) or [])
                    ),
                    "tables_with_data_pages": sum(1 for pages in data_pages.values() if pages),
                    "tables_with_blob_fields": tables_with_blob_fields,
                    "total_fields": total_fields,
                    "total_indexes": total_indexes,
                    "total_blob_fields": total_blob_fields,
                    "family_counts": dict(sorted(family_counts.items())),
                    "sample_tables": sample_tables[:sample_limit],
                }
            )
        finally:
            try:
                db.close()
            except Exception:
                pass
    except Exception as exc:
        summary["parse_error"] = str(exc)
    return summary


def _build_family_alignment(
    xml_summary: Optional[Dict[str, Any]],
    onecd_summary: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    xml_family_counts = dict((xml_summary or {}).get("family_counts") or {})
    physical_family_counts = dict((onecd_summary or {}).get("family_counts") or {})
    xml_families = {name for name, count in xml_family_counts.items() if int(count or 0) > 0}
    physical_families = {
        name
        for name, count in physical_family_counts.items()
        if int(count or 0) > 0 and name not in {"other", "system"}
    }
    matched = sorted(xml_families & physical_families)
    xml_only = sorted(xml_families - physical_families)
    physical_only = sorted(physical_families - xml_families)
    coverage = 0.0
    if xml_families:
        coverage = round(len(matched) / len(xml_families), 3)
    return {
        "xml_family_counts": xml_family_counts,
        "physical_family_counts": physical_family_counts,
        "matched_families": matched,
        "xml_only_families": xml_only,
        "physical_only_families": physical_only,
        "coverage_ratio": coverage,
    }


def build_onec_compatibility_snapshot(
    source_path: str,
    source_kind: str = "",
    *,
    sample_limit: int = 25,
) -> Dict[str, Any]:
    resolved = resolve_onec_source(source_path, source_kind)
    related = discover_related_onec_sources(
        source_path,
        semantic_path=resolved.semantic_path,
    )

    dt_summary = inspect_dt_dump(related["dt"]) if "dt" in related else None
    xml_summary = summarize_xmlconf_root(related["xml"], sample_limit=5) if "xml" in related else None
    onecd_summary = inspect_1cd_database(related["1cd"], sample_limit=sample_limit) if "1cd" in related else None

    compatibility = {
        "can_import_semantic": bool(resolved.semantic_path),
        "has_xmlconf": bool(xml_summary),
        "has_dt_container": bool(dt_summary),
        "has_physical_schema": bool(onecd_summary and not onecd_summary.get("parse_error")),
        "parser_backend": str((onecd_summary or {}).get("parser_backend") or ""),
    }

    snapshot = {
        "requested_source_kind": resolved.requested_kind,
        "detected_source_kind": resolved.detected_kind,
        "semantic_source_kind": resolved.semantic_kind,
        "semantic_source_path": resolved.semantic_path,
        "source_analysis": dict(resolved.analysis or {}),
        "available_sources": sorted(related.keys()),
        "paths": {
            "original": str(source_path),
            "dt": str(related.get("dt") or ""),
            "1cd": str(related.get("1cd") or ""),
            "xml": str(related.get("xml") or ""),
        },
        "compatibility": compatibility,
        "dt": dt_summary,
        "xmlconf": xml_summary,
        "onecd": onecd_summary,
        "family_alignment": _build_family_alignment(xml_summary, onecd_summary),
    }

    recommendations: list[str] = []
    if snapshot["paths"]["dt"] and not snapshot["paths"]["1cd"]:
        recommendations.append("DT is available, but a sibling 1Cv8.1CD was not found for physical schema analysis.")
    if onecd_summary and onecd_summary.get("parse_error"):
        recommendations.append(f"1CD physical schema parsing is unavailable: {onecd_summary['parse_error']}")
    if xml_summary and not onecd_summary:
        recommendations.append("Only XMLConf metadata is available; physical tables and rows require 1Cv8.1CD.")
    snapshot["recommendations"] = recommendations
    return snapshot


def store_source_snapshot_asset(
    db,
    snapshot: Dict[str, Any],
    *,
    asset_key: str = SOURCE_SNAPSHOT_ASSET_KEY,
) -> str:
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8")
    db.put_assets_bulk([(asset_key, payload, "application/json")])
    return asset_key


__all__ = [
    "SOURCE_SNAPSHOT_ASSET_KEY",
    "build_onec_compatibility_snapshot",
    "discover_related_onec_sources",
    "inspect_1cd_database",
    "inspect_dt_dump",
    "store_source_snapshot_asset",
    "summarize_xmlconf_root",
]
