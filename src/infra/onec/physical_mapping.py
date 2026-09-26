from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable

from src.configurator.persistence.schema_deployment import (
    _CATALOG_SYSTEM_FIELDS,
    _CONSTANTS_SCHEMA,
    _DOC_SYSTEM_FIELDS,
    _REG_SYSTEM_FIELDS,
    _TP_OWNER_GUID_SYSTEM_FIELDS,
    _TP_SYSTEM_FIELDS,
)

from .physical_schema import (
    XMLCONF_DIR_TO_FAMILY,
    _classify_onecd_table_family,
    _load_parse1cd_backend,
    _make_read_only_onecd_class,
    build_onec_compatibility_snapshot,
    discover_related_onec_sources,
)
from .onecd_source import collect_onecd_metadata_catalog
from .source_compat import find_xmlconf_root, resolve_onec_source


PHYSICAL_MAPPING_ASSET_KEY = "onec_analysis/physical_mapping.json"

_CATALOG_LIKE_FAMILIES = {
    "catalog",
    "chart_of_accounts",
    "chart_of_characteristic_types",
}
_DOCUMENT_LIKE_FAMILIES = {
    "document",
    "business_process",
    "task",
}
_REGISTER_LIKE_FAMILIES = {
    "accumulation_register",
    "information_register",
    "accounting_register",
    "calculation_register",
}
_OBJECT_FAMILY_ORDER = (
    "constant",
    "catalog",
    "document",
    "accumulation_register",
    "information_register",
    "accounting_register",
    "calculation_register",
    "chart_of_accounts",
    "chart_of_characteristic_types",
    "business_process",
    "task",
)

_VT_RE = re.compile(r"_VT\d+$", re.IGNORECASE)
_FIELD_LINENO_RE = re.compile(r"^_LINENO\d*$", re.IGNORECASE)
_FIELD_OWNER_REF_RE = re.compile(r"^_(REFERENCE|DOCUMENT|CHRC)\d+_IDRREF$", re.IGNORECASE)
_FIELD_CUSTOM_RE = re.compile(r"^_FLD(\d+)(RREF|RRREF|RTREF|TYPE|N|T|S|L)?$", re.IGNORECASE)
_TABLE_DIGIT_TOKEN_RE = re.compile(
    r"_(REFERENCE|DOCUMENT|CONST|ACCUMRG|INFORG|ACCRG|CHRC)"
    r"(?:OPT|T|DLK|BFK|AGGDIMS|AGGDICT\d+H|SINF|CHNGR)?(\d+)",
    re.IGNORECASE,
)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").strip().lower())


def _target_tables_for_object(family: str, name: str) -> list[str]:
    obj_name = str(name or "").strip().lower()
    if not obj_name:
        return []
    if family == "constant":
        return ["data_constants"]
    if family in _CATALOG_LIKE_FAMILIES:
        return [f"data_catalog_{obj_name}"]
    if family in _DOCUMENT_LIKE_FAMILIES:
        return [f"data_document_{obj_name}"]
    if family in _REGISTER_LIKE_FAMILIES:
        return [f"data_reg_{obj_name}"]
    return []


def collect_xmlconf_object_catalog(path: str | Path) -> list[dict[str, Any]]:
    root = find_xmlconf_root(path)
    if root is None or not root.exists() or not root.is_dir():
        return []

    out: list[dict[str, Any]] = []
    for top_dir_name, family in XMLCONF_DIR_TO_FAMILY.items():
        top_dir = root / top_dir_name
        if not top_dir.is_dir():
            continue
        for obj_dir in sorted((child for child in top_dir.iterdir() if child.is_dir()), key=lambda p: p.name.lower()):
            out.append(
                {
                    "family": family,
                    "name": obj_dir.name,
                    "slug": _slug(obj_dir.name),
                    "source_path": str(obj_dir),
                    "target_tables": _target_tables_for_object(family, obj_dir.name),
                }
            )
    return out


def _table_kind(family: str, table_name: str, fields: Iterable[str]) -> str:
    upper_name = str(table_name or "").upper()
    field_set = {str(field or "").upper() for field in fields}

    if family == "constant":
        return "constant_value"
    if _VT_RE.search(upper_name):
        return "tabular_part"
    if "JOURNAL" in upper_name:
        return "journal"
    if "OPT" in upper_name:
        return "options"
    if any(token in upper_name for token in ("SINF", "CHNGR", "DLK", "BFK", "AGG", "DICT")):
        return "auxiliary"

    if family in _REGISTER_LIKE_FAMILIES:
        if "_PERIOD" in field_set or "_ACTIVE" in field_set or "_RECORDERRREF" in field_set:
            return "register_data"
        return "auxiliary"

    if family in _DOCUMENT_LIKE_FAMILIES:
        if any(field in field_set for field in ("_DOCUMENTRREF", "_IDRREF", "_NUMBER", "_DATE_TIME", "_POSTED")):
            return "object"
        return "auxiliary"

    if family in _CATALOG_LIKE_FAMILIES:
        if any(field in field_set for field in ("_IDRREF", "_MARKED", "_CODE", "_DESCRIPTION", "_PREDEFINEDID", "_FOLDER")):
            return "object"
        return "auxiliary"

    return "auxiliary"


def _field_mapping_for(
    family: str,
    table_kind: str,
    field_name: str,
) -> dict[str, Any]:
    field = str(field_name or "")
    upper_field = field.upper()

    target_field = ""
    slot = ""
    category = "custom"
    confidence = "low"

    if family == "constant":
        if upper_field == "_RECORDKEY":
            target_field = "key"
            slot = "key"
            category = "system"
            confidence = "high"
        elif upper_field.startswith("_FLD"):
            target_field = "value"
            slot = "value"
            category = "custom"
            confidence = "medium"
        else:
            slot = "service"
            category = "service"
    elif upper_field == "_IDRREF":
        target_field = "_guid"
        slot = "guid"
        category = "system"
        confidence = "high"
    elif upper_field == "_DOCUMENTRREF":
        target_field = "_guid"
        slot = "guid"
        category = "system"
        confidence = "high"
    elif upper_field == "_MARKED":
        target_field = "_deleted"
        slot = "deleted"
        category = "system"
        confidence = "high"
    elif upper_field == "_CODE":
        target_field = "_code"
        slot = "code"
        category = "system"
        confidence = "high"
    elif upper_field == "_DESCRIPTION":
        target_field = "_description"
        slot = "description"
        category = "system"
        confidence = "high"
    elif upper_field == "_PREDEFINEDID":
        target_field = "_predefined"
        slot = "predefined"
        category = "system"
        confidence = "medium"
    elif upper_field == "_PARENTIDRREF":
        target_field = "_parent_guid"
        slot = "parent_ref"
        category = "system"
        confidence = "high"
    elif upper_field == "_OWNERIDRREF":
        target_field = "_owner_guid"
        slot = "owner_ref"
        category = "system"
        confidence = "high"
    elif upper_field == "_FOLDER":
        target_field = "_is_folder"
        slot = "is_folder"
        category = "system"
        confidence = "high"
    elif upper_field in {"_DATE_TIME", "_DATE"}:
        target_field = "_date"
        slot = "date"
        category = "system"
        confidence = "high"
    elif upper_field == "_NUMBER":
        target_field = "_number"
        slot = "number"
        category = "system"
        confidence = "high"
    elif upper_field == "_POSTED":
        target_field = "_posted"
        slot = "posted"
        category = "system"
        confidence = "high"
    elif upper_field == "_PERIOD":
        target_field = "_period"
        slot = "period"
        category = "system"
        confidence = "high"
    elif upper_field == "_ACTIVE":
        target_field = "_active"
        slot = "active"
        category = "system"
        confidence = "high"
    elif _FIELD_LINENO_RE.match(upper_field):
        target_field = "_line_no"
        slot = "line_no"
        category = "system"
        confidence = "high"
    elif upper_field == "_RECORDERRREF" or re.match(r"^_RECORDER.*(RREF|RRREF)$", upper_field):
        target_field = "_recorder"
        slot = "recorder"
        category = "system"
        confidence = "medium"
    elif upper_field == "_RECORDERTREF" or re.match(r"^_RECORDER.*(TREF|RTREF)$", upper_field):
        target_field = ""
        slot = "recorder_type"
        category = "service"
        confidence = "medium"
    elif upper_field == "_RECORDKEY":
        target_field = "key"
        slot = "key"
        category = "system"
        confidence = "high"
    elif upper_field == "_KEYFIELD":
        target_field = ""
        slot = "key_field"
        category = "service"
        confidence = "medium"
    elif _FIELD_OWNER_REF_RE.match(upper_field):
        target_field = "_doc_guid" if family in _DOCUMENT_LIKE_FAMILIES else "_owner_guid"
        slot = "owner_ref"
        category = "system"
        confidence = "high"
    elif upper_field in {
        "_REGID",
        "_ACTUALPERIOD",
        "_PERIODICITY",
        "_REPETITIONFACTOR",
        "_USETOTALS",
        "_USESPLITTER",
        "_MINCALCULATEDPERIOD",
        "_DIMKEY",
        "_SPLITTER",
        "_PDUPDMODE",
        "_PDINITIALIZED",
        "_SLICEUSING",
        "_VERSION",
        "_FLD7919",
    }:
        slot = "service"
        category = "service"
        confidence = "low"
    else:
        custom = _FIELD_CUSTOM_RE.match(upper_field)
        if custom:
            suffix = str(custom.group(2) or "").upper()
            if suffix in {"RREF", "RRREF"}:
                slot = "custom_reference"
            elif suffix in {"RTREF", "TYPE"}:
                slot = "custom_variant_type"
            elif suffix in {"N", "T", "S", "L"}:
                slot = "custom_variant_value"
            else:
                slot = "custom_value"
            category = "custom"
            confidence = "low"
        else:
            slot = "unclassified"

    return {
        "source_field": field,
        "slot": slot,
        "target_field": target_field,
        "category": category,
        "confidence": confidence,
    }


def _table_token(name: str) -> str:
    value = str(name or "").upper()
    if "_VT" in value:
        return value.split("_VT", 1)[0]
    match = _TABLE_DIGIT_TOKEN_RE.search(value)
    if match:
        return f"_{match.group(1).upper()}{match.group(2)}"
    return value


def inspect_1cd_table_catalog(path: str | Path) -> list[dict[str, Any]]:
    onecd_path = Path(path)
    if not onecd_path.exists():
        return []
    parser_root, backend = _load_parse1cd_backend()
    db_cls = _make_read_only_onecd_class(backend.OneCDatabase)
    db = db_cls(str(onecd_path))
    opened = db.open()
    if not opened:
        return []

    try:
        out: list[dict[str, Any]] = []
        for name, table in sorted((getattr(db, "tables", {}) or {}).items(), key=lambda item: str(item[0]).lower()):
            fields = [str(getattr(field, "name", "") or "") for field in list(getattr(table, "fields", []) or [])]
            indexes = [str(getattr(index, "name", "") or "") for index in list(getattr(table, "indexes", []) or [])]
            family = _classify_onecd_table_family(str(name))
            table_kind = _table_kind(family, str(name), fields)
            field_mappings = [_field_mapping_for(family, table_kind, field_name) for field_name in fields]
            out.append(
                {
                    "name": str(name),
                    "family": family,
                    "table_kind": table_kind,
                    "table_token": _table_token(str(name)),
                    "field_count": len(fields),
                    "index_count": len(indexes),
                    "row_size": int(getattr(table, "row_size", 0) or 0),
                    "data_object_id": int(getattr(table, "data_object_id", 0) or 0),
                    "fields": fields,
                    "indexes": indexes,
                    "field_mappings": field_mappings,
                }
            )
        return out
    finally:
        try:
            db.close()
        except Exception:
            pass


def _observed_patterns(onecd_tables: list[dict[str, Any]], family: str, table_kind: str, limit: int = 5) -> dict[str, Any]:
    matches = [
        table
        for table in onecd_tables
        if str(table.get("family") or "") == family and str(table.get("table_kind") or "") == table_kind
    ]
    return {
        "count": len(matches),
        "examples": [str(table.get("name") or "") for table in matches[:limit]],
        "token_examples": sorted({str(table.get("table_token") or "") for table in matches[:limit]}),
    }


def _family_template_key(family: str, table_kind: str) -> str:
    return f"{family}.{table_kind}"


def _build_family_templates(onecd_tables: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for table in onecd_tables:
        key = _family_template_key(str(table.get("family") or ""), str(table.get("table_kind") or ""))
        groups[key].append(table)

    templates: dict[str, dict[str, Any]] = {}
    for key, tables in groups.items():
        slot_examples: dict[str, set[str]] = defaultdict(set)
        target_fields: dict[str, str] = {}
        for table in tables:
            for item in list(table.get("field_mappings") or []):
                slot = str(item.get("slot") or "")
                if not slot:
                    continue
                source_field = str(item.get("source_field") or "")
                target_field = str(item.get("target_field") or "")
                if source_field:
                    slot_examples[slot].add(source_field)
                if target_field and slot not in target_fields:
                    target_fields[slot] = target_field
        templates[key] = {
            "table_count": len(tables),
            "slot_examples": {slot: sorted(values)[:8] for slot, values in sorted(slot_examples.items())},
            "target_fields": target_fields,
        }
    return templates


def _meta_platform_templates() -> dict[str, dict[str, Any]]:
    return {
        "constant": {
            "target_table_pattern": "data_constants",
            "system_fields": list((_CONSTANTS_SCHEMA.get("fields") or {}).keys()),
        },
        "catalog": {
            "target_table_pattern": "data_catalog_<name>",
            "system_fields": list(_CATALOG_SYSTEM_FIELDS.keys()),
        },
        "chart_of_accounts": {
            "target_table_pattern": "data_catalog_<name>",
            "system_fields": list(_CATALOG_SYSTEM_FIELDS.keys()),
        },
        "chart_of_characteristic_types": {
            "target_table_pattern": "data_catalog_<name>",
            "system_fields": list(_CATALOG_SYSTEM_FIELDS.keys()),
        },
        "document": {
            "target_table_pattern": "data_document_<name>",
            "system_fields": list(_DOC_SYSTEM_FIELDS.keys()),
        },
        "business_process": {
            "target_table_pattern": "data_document_<name>",
            "system_fields": list(_DOC_SYSTEM_FIELDS.keys()),
        },
        "task": {
            "target_table_pattern": "data_document_<name>",
            "system_fields": list(_DOC_SYSTEM_FIELDS.keys()),
        },
        "tabular_part": {
            "target_table_pattern": "data_tp_<owner>_<part>",
            "system_fields": sorted(set(_TP_SYSTEM_FIELDS.keys()) | set(_TP_OWNER_GUID_SYSTEM_FIELDS.keys())),
        },
        "register": {
            "target_table_pattern": "data_reg_<name>",
            "system_fields": list(_REG_SYSTEM_FIELDS.keys()),
        },
    }


def build_physical_mapping_report_from_catalogs(
    *,
    source_path: str,
    related_paths: dict[str, str],
    snapshot: dict[str, Any] | None,
    xml_objects: list[dict[str, Any]],
    onecd_tables: list[dict[str, Any]],
) -> dict[str, Any]:
    xml_family_counts = Counter(str(item.get("family") or "") for item in xml_objects)
    onecd_family_counts = Counter(str(item.get("family") or "") for item in onecd_tables)
    onecd_kind_counts: dict[str, dict[str, int]] = {}
    for table in onecd_tables:
        family = str(table.get("family") or "")
        table_kind = str(table.get("table_kind") or "")
        onecd_kind_counts.setdefault(family, {})
        onecd_kind_counts[family][table_kind] = int(onecd_kind_counts[family].get(table_kind) or 0) + 1

    family_templates = _build_family_templates(onecd_tables)
    object_blueprints: list[dict[str, Any]] = []
    for item in xml_objects:
        family = str(item.get("family") or "")
        preferred_kind = "object"
        if family == "constant":
            preferred_kind = "constant_value"
        elif family in _REGISTER_LIKE_FAMILIES:
            preferred_kind = "register_data"
        template_key = _family_template_key(family, preferred_kind)
        observed = _observed_patterns(onecd_tables, family, preferred_kind)
        object_blueprints.append(
            {
                "family": family,
                "name": str(item.get("name") or ""),
                "target_tables": list(item.get("target_tables") or []),
                "preferred_source_kind": preferred_kind,
                "template_key": template_key,
                "observed_source_tables": observed,
                "mapping_confidence": "template" if int(observed.get("count") or 0) > 0 else "semantic_only",
            }
        )

    recommendations: list[str] = []
    for family in ("catalog", "chart_of_characteristic_types"):
        tabular_count = int((onecd_kind_counts.get(family) or {}).get("tabular_part") or 0)
        if tabular_count > 0:
            recommendations.append(
                f"{family} has observed 1C tabular-part tables ({tabular_count}), but MetaPlatform still needs explicit data migration support for non-document tabular parts."
            )
    for family in _OBJECT_FAMILY_ORDER:
        xml_count = int(xml_family_counts.get(family) or 0)
        physical_count = int(onecd_family_counts.get(family) or 0)
        if xml_count > 0 and physical_count == 0:
            recommendations.append(
                f"{family} exists in XMLConf, but no physical 1CD tables were identified; this likely requires deeper DBNames/config decoding or parser improvements."
            )

    summary = {
        "xml_object_count": len(xml_objects),
        "onecd_table_count": len(onecd_tables),
        "xml_family_counts": dict(sorted(xml_family_counts.items())),
        "onecd_family_counts": dict(sorted(onecd_family_counts.items())),
        "onecd_table_kind_counts": {family: dict(sorted(counts.items())) for family, counts in sorted(onecd_kind_counts.items())},
        "template_count": len(family_templates),
        "object_blueprint_count": len(object_blueprints),
    }

    return {
        "source_path": str(source_path),
        "paths": {
            "dt": str(related_paths.get("dt") or ""),
            "1cd": str(related_paths.get("1cd") or ""),
            "xml": str(related_paths.get("xml") or ""),
        },
        "snapshot_summary": {
            "available_sources": list((snapshot or {}).get("available_sources") or []),
            "compatibility": dict((snapshot or {}).get("compatibility") or {}),
        },
        "summary": summary,
        "meta_platform_templates": _meta_platform_templates(),
        "family_templates": family_templates,
        "xml_objects": xml_objects,
        "onecd_tables": onecd_tables,
        "object_migration_blueprints": object_blueprints,
        "recommendations": recommendations,
    }


def build_physical_mapping_report(
    source_path: str,
    source_kind: str = "",
    *,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = resolve_onec_source(source_path, source_kind)
    related = discover_related_onec_sources(source_path, semantic_path=resolved.semantic_path)
    current_snapshot = snapshot or build_onec_compatibility_snapshot(source_path, source_kind)
    xml_objects = collect_xmlconf_object_catalog(related.get("xml") or "")
    if not xml_objects and related.get("1cd"):
        xml_objects = collect_onecd_metadata_catalog(related.get("1cd") or "")
    onecd_tables = inspect_1cd_table_catalog(related.get("1cd") or "") if related.get("1cd") else []
    return build_physical_mapping_report_from_catalogs(
        source_path=source_path,
        related_paths=related,
        snapshot=current_snapshot,
        xml_objects=xml_objects,
        onecd_tables=onecd_tables,
    )


def store_physical_mapping_asset(
    db,
    report: dict[str, Any],
    *,
    asset_key: str = PHYSICAL_MAPPING_ASSET_KEY,
) -> str:
    payload = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
    db.put_assets_bulk([(asset_key, payload, "application/json")])
    return asset_key


__all__ = [
    "PHYSICAL_MAPPING_ASSET_KEY",
    "build_physical_mapping_report",
    "build_physical_mapping_report_from_catalogs",
    "collect_xmlconf_object_catalog",
    "inspect_1cd_table_catalog",
    "store_physical_mapping_asset",
]
