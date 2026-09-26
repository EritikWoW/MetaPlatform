from __future__ import annotations

import json
from typing import Any, Dict, List

from src.configurator.manifest_schema import MANIFEST_TABLE
from src.configurator.persistence.modules_tables import MODULES_TABLE
from src.configurator.persistence.schema_deployment import (
    _CATALOG_SYSTEM_FIELDS,
    _CONSTANTS_SCHEMA,
    _DOC_SYSTEM_FIELDS,
    _REG_SYSTEM_FIELDS,
    _TP_SYSTEM_FIELDS,
)

from .physical_schema import build_onec_compatibility_snapshot


STORAGE_ALIGNMENT_ASSET_KEY = "onec_analysis/storage_alignment.json"
CRITICAL_MIGRATION_FAMILIES = (
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
SUPPORTED_FAMILY_PROFILES = {
    "constant": {
        "status": "partial",
        "table_pattern": "data_constants",
        "system_fields": list((_CONSTANTS_SCHEMA.get("fields") or {}).keys()),
        "notes": "Shared key/value runtime table; closer to 1C constants semantics than before, but still not per-object physical storage.",
    },
    "catalog": {
        "status": "supported",
        "table_pattern": "data_catalog_<name>",
        "system_fields": list(_CATALOG_SYSTEM_FIELDS.keys()),
        "notes": "Separate table per metadata object; good migration target for reference catalogs.",
    },
    "document": {
        "status": "supported",
        "table_pattern": "data_document_<name>",
        "system_fields": list(_DOC_SYSTEM_FIELDS.keys()),
        "notes": "Header rows are close to 1C logical document model; tabular parts live in separate tables.",
    },
    "tabular_part": {
        "status": "supported",
        "table_pattern": "data_tp_<doc>_<part>",
        "system_fields": list(_TP_SYSTEM_FIELDS.keys()),
        "notes": "Separate tabular-part tables; line and owner linkage are explicit.",
    },
    "accumulation_register": {
        "status": "supported",
        "table_pattern": "data_reg_<name>",
        "system_fields": list(_REG_SYSTEM_FIELDS.keys()),
        "notes": "Generic register table shape is shared for all register kinds.",
    },
    "information_register": {
        "status": "supported",
        "table_pattern": "data_reg_<name>",
        "system_fields": list(_REG_SYSTEM_FIELDS.keys()),
        "notes": "Generic register table shape is shared for all register kinds.",
    },
    "accounting_register": {
        "status": "supported",
        "table_pattern": "data_reg_<name>",
        "system_fields": list(_REG_SYSTEM_FIELDS.keys()),
        "notes": "Generic register table shape is shared for all register kinds.",
    },
    "calculation_register": {
        "status": "supported",
        "table_pattern": "data_reg_<name>",
        "system_fields": list(_REG_SYSTEM_FIELDS.keys()),
        "notes": "Generic register table shape is shared for all register kinds.",
    },
    "chart_of_accounts": {
        "status": "partial",
        "table_pattern": "data_catalog_<name>",
        "system_fields": list(_CATALOG_SYSTEM_FIELDS.keys()),
        "notes": "Deployed through the catalog-like profile; migration works, but account-specific semantics still need explicit metadata.",
    },
    "chart_of_characteristic_types": {
        "status": "partial",
        "table_pattern": "data_catalog_<name>",
        "system_fields": list(_CATALOG_SYSTEM_FIELDS.keys()),
        "notes": "Deployed through the catalog-like profile; migration works, but allowed-type semantics still need explicit metadata.",
    },
    "business_process": {
        "status": "partial",
        "table_pattern": "data_document_<name>",
        "system_fields": list(_DOC_SYSTEM_FIELDS.keys()),
        "notes": "Deployed through the document-like profile; routing/state semantics still need explicit metadata.",
    },
    "task": {
        "status": "partial",
        "table_pattern": "data_document_<name>",
        "system_fields": list(_DOC_SYSTEM_FIELDS.keys()),
        "notes": "Deployed through the document-like profile; executor/state semantics still need explicit metadata.",
    },
}
EXPECTED_LOGICAL_FIELDS = {
    "constant": ["key", "value"],
    "catalog": [
        "_guid",
        "_deleted",
        "_code",
        "_description",
        "_parent_guid",
        "_owner_guid",
        "_is_folder",
        "_predefined",
    ],
    "document": ["_guid", "_deleted", "_number", "_date", "_posted"],
    "tabular_part": ["_row_guid", "_doc_guid", "_line_no"],
    "register": ["_period", "_recorder", "_line_no", "_active"],
}


def _field_alignment(actual_fields: List[str], expected_fields: List[str]) -> Dict[str, Any]:
    actual = {str(name) for name in actual_fields}
    expected = {str(name) for name in expected_fields}
    matched = sorted(actual & expected)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    coverage = 1.0
    if expected:
        coverage = round(len(matched) / len(expected), 3)
    return {
        "actual": sorted(actual),
        "expected": sorted(expected),
        "matched": matched,
        "missing": missing,
        "extra": extra,
        "coverage_ratio": coverage,
    }


def get_meta_platform_storage_profile() -> Dict[str, Any]:
    return {
        "manifest_table": MANIFEST_TABLE,
        "modules_table": MODULES_TABLE,
        "asset_tables": ["__assets", "manifest-payload/*", "module-src/*"],
        "table_patterns": {
            "constant": "data_constants",
            "catalog": "data_catalog_<name>",
            "document": "data_document_<name>",
            "tabular_part": "data_tp_<doc>_<part>",
            "register": "data_reg_<name>",
        },
        "system_fields": {
            "constant": list((_CONSTANTS_SCHEMA.get("fields") or {}).keys()),
            "catalog": list(_CATALOG_SYSTEM_FIELDS.keys()),
            "document": list(_DOC_SYSTEM_FIELDS.keys()),
            "tabular_part": list(_TP_SYSTEM_FIELDS.keys()),
            "register": list(_REG_SYSTEM_FIELDS.keys()),
        },
        "capabilities": {
            "manifest_source_of_truth": True,
            "modules_separate_from_manifest": True,
            "heavy_payload_externalized_to_assets": True,
            "human_readable_table_names": True,
            "direct_1c_table_name_copy": False,
            "schema_alter_supported": False,
        },
    }


def _source_family_counts(snapshot: Dict[str, Any]) -> Dict[str, int]:
    xml_counts = dict((snapshot.get("xmlconf") or {}).get("family_counts") or {})
    physical_counts = dict((snapshot.get("onecd") or {}).get("family_counts") or {})
    counts: Dict[str, int] = {}
    for family in CRITICAL_MIGRATION_FAMILIES:
        xml_count = int(xml_counts.get(family) or 0)
        physical_count = int(physical_counts.get(family) or 0)
        counts[family] = xml_count if xml_count > 0 else physical_count
    return counts


def _family_support_rows(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    source_counts = _source_family_counts(snapshot)
    rows: List[Dict[str, Any]] = []
    for family in CRITICAL_MIGRATION_FAMILIES:
        profile = dict(SUPPORTED_FAMILY_PROFILES.get(family) or {})
        status = str(profile.get("status") or "missing")
        rows.append(
            {
                "family": family,
                "source_count": int(source_counts.get(family) or 0),
                "supported": status in {"supported", "partial"},
                "status": status,
                "table_pattern": str(profile.get("table_pattern") or ""),
                "system_fields": list(profile.get("system_fields") or []),
                "notes": str(profile.get("notes") or ""),
            }
        )
    rows.sort(key=lambda item: (-int(item["source_count"]), str(item["family"])))
    return rows


def _field_alignment_section() -> Dict[str, Any]:
    return {
        "constant": _field_alignment(
            get_meta_platform_storage_profile()["system_fields"]["constant"],
            EXPECTED_LOGICAL_FIELDS["constant"],
        ),
        "catalog": _field_alignment(
            get_meta_platform_storage_profile()["system_fields"]["catalog"],
            EXPECTED_LOGICAL_FIELDS["catalog"],
        ),
        "document": _field_alignment(
            get_meta_platform_storage_profile()["system_fields"]["document"],
            EXPECTED_LOGICAL_FIELDS["document"],
        ),
        "tabular_part": _field_alignment(
            get_meta_platform_storage_profile()["system_fields"]["tabular_part"],
            EXPECTED_LOGICAL_FIELDS["tabular_part"],
        ),
        "register": _field_alignment(
            get_meta_platform_storage_profile()["system_fields"]["register"],
            EXPECTED_LOGICAL_FIELDS["register"],
        ),
    }


def _recommendations(snapshot: Dict[str, Any], family_rows: List[Dict[str, Any]]) -> List[str]:
    recommendations: List[str] = []
    missing_families = [
        row["family"]
        for row in family_rows
        if int(row.get("source_count") or 0) > 0 and str(row.get("status") or "") == "missing"
    ]
    if missing_families:
        recommendations.append(
            "Add physical deployment profiles for: " + ", ".join(sorted(map(str, missing_families))) + "."
        )
    recommendations.append(
        "Persist a stable storage map (manifest GUID -> table names / field aliases / source ids) so migration code does not guess physical targets."
    )
    recommendations.append(
        "Keep readable MetaPlatform table names, but add explicit 1C alias metadata instead of trying to mirror numeric 1C table names 1:1."
    )
    recommendations.append(
        "Expand type mapping beyond str/float/int: preserve fixed string length, number precision/scale, reference types and activity flags."
    )
    if not (snapshot.get("compatibility") or {}).get("has_physical_schema"):
        recommendations.append("Use sibling 1Cv8.1CD during migration analysis; XMLConf alone is not enough for physical data extraction.")
    return recommendations


def build_storage_alignment_report_from_snapshot(
    snapshot: Dict[str, Any],
    *,
    source_path: str = "",
) -> Dict[str, Any]:
    profile = get_meta_platform_storage_profile()
    family_rows = _family_support_rows(snapshot)
    field_rows = _field_alignment_section()

    total_source_objects = sum(int(row.get("source_count") or 0) for row in family_rows)
    supported_source_objects = sum(
        int(row.get("source_count") or 0)
        for row in family_rows
        if str(row.get("status") or "") in {"supported", "partial"}
    )
    source_family_coverage = 1.0
    if total_source_objects > 0:
        source_family_coverage = round(supported_source_objects / total_source_objects, 3)

    field_coverage_values = [float(section.get("coverage_ratio") or 0.0) for section in field_rows.values()]
    field_coverage = round(sum(field_coverage_values) / max(len(field_coverage_values), 1), 3)

    overall_score = round((source_family_coverage * 0.6) + (field_coverage * 0.4), 3)
    readiness = "low"
    if overall_score >= 0.75:
        readiness = "high"
    elif overall_score >= 0.45:
        readiness = "medium"

    return {
        "source_path": str(source_path or snapshot.get("paths", {}).get("original") or ""),
        "meta_platform_profile": profile,
        "onec_snapshot": snapshot,
        "family_support": family_rows,
        "field_alignment": field_rows,
        "coverage": {
            "source_family_coverage": source_family_coverage,
            "field_coverage": field_coverage,
            "overall_score": overall_score,
            "migration_readiness": readiness,
        },
        "recommendations": _recommendations(snapshot, family_rows),
    }


def build_storage_alignment_report(
    source_path: str,
    source_kind: str = "",
) -> Dict[str, Any]:
    snapshot = build_onec_compatibility_snapshot(source_path, source_kind)
    return build_storage_alignment_report_from_snapshot(snapshot, source_path=source_path)


def store_storage_alignment_asset(
    db,
    report: Dict[str, Any],
    *,
    asset_key: str = STORAGE_ALIGNMENT_ASSET_KEY,
) -> str:
    payload = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
    db.put_assets_bulk([(asset_key, payload, "application/json")])
    return asset_key


__all__ = [
    "CRITICAL_MIGRATION_FAMILIES",
    "STORAGE_ALIGNMENT_ASSET_KEY",
    "build_storage_alignment_report",
    "build_storage_alignment_report_from_snapshot",
    "get_meta_platform_storage_profile",
    "store_storage_alignment_asset",
]
