from __future__ import annotations

"""Optional 1C COM data audit for direct .1CD imports.

The production import remains Parse1CD/.1CD based.  This module is a diagnostic
bridge: it asks 1C through COM what data objects and row counts are visible, then
compares that with the direct .1CD data migration manifest.
"""

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable


ONEC_COM_DATA_AUDIT_ASSET_KEY = "onec_com_data_audit/report.json"


@dataclass(frozen=True)
class QuerySource:
    english: str
    russian: str


_QUERY_SOURCES: dict[str, tuple[str, str]] = {
    "catalog": ("Catalog", "Справочник"),
    "document": ("Document", "Документ"),
    "enumeration": ("Enum", "Перечисление"),
    "register_info": ("InformationRegister", "РегистрСведений"),
    "register_accum": ("AccumulationRegister", "РегистрНакопления"),
    "register_accounting": ("AccountingRegister", "РегистрБухгалтерии"),
    "register_calc": ("CalculationRegister", "РегистрРасчета"),
    "chart_of_accounts": ("ChartOfAccounts", "ПланСчетов"),
    "chart_of_characteristic_types": ("ChartOfCharacteristicTypes", "ПланВидовХарактеристик"),
    "chart_of_calculation_types": ("ChartOfCalculationTypes", "ПланВидовРасчета"),
    "business_process": ("BusinessProcess", "БизнесПроцесс"),
    "task": ("Task", "Задача"),
    "exchange_plan": ("ExchangePlan", "ПланОбмена"),
}

_UNQUERYABLE_TYPES = {
    "constants": "constants are scalar values, not row-backed object tables",
    "report": "reports do not expose object rows",
    "data_processor": "data processors do not expose object rows",
    "common_module": "common modules do not expose object rows",
    "role": "roles do not expose object rows",
    "subsystem": "subsystems are metadata-only for this audit",
    "common_form": "common forms are metadata-only for this audit",
    "common_layout": "common layouts are metadata-only for this audit",
    "common_picture": "common pictures are metadata-only for this audit",
}

_DIRECT_KIND_ALIASES = {
    "constant": "constants",
    "enum": "enumeration",
    "reference": "catalog",
    "catalog": "catalog",
    "document": "document",
    "information_register": "register_info",
    "accumulation_register": "register_accum",
    "accounting_register": "register_accounting",
    "calculation_register": "register_calc",
    "chart_of_accounts": "chart_of_accounts",
    "chart_of_characteristic_types": "chart_of_characteristic_types",
    "chart_of_calculation_types": "chart_of_calculation_types",
    "business_process": "business_process",
    "task": "task",
    "exchange_plan": "exchange_plan",
}


def _normalize_direct_kind(kind: Any) -> str:
    value = str(kind or "unknown").strip() or "unknown"
    return _DIRECT_KIND_ALIASES.get(value, value)


def _source_for(obj_type: str, name: str) -> QuerySource | None:
    pair = _QUERY_SOURCES.get(str(obj_type or "").strip())
    clean_name = str(name or "").strip()
    if not pair or not clean_name:
        return None
    return QuerySource(
        english=f"{pair[0]}.{clean_name}",
        russian=f"{pair[1]}.{clean_name}",
    )


def _count_queries(src: QuerySource) -> list[str]:
    return [
        f"SELECT COUNT(*) AS RowCount FROM {src.english}",
        f"ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК RowCount ИЗ {src.russian}",
    ]


def _sample_queries(src: QuerySource, limit: int) -> list[str]:
    n = max(1, int(limit or 1))
    return [
        f"SELECT TOP {n} * FROM {src.english}",
        f"ВЫБРАТЬ ПЕРВЫЕ {n} * ИЗ {src.russian}",
    ]


def _try_queries(conn: Any, queries: Iterable[str]) -> tuple[list[dict[str, Any]], str, str]:
    errors: list[str] = []
    for query in queries:
        text = str(query or "").strip()
        if not text:
            continue
        try:
            rows = conn.query(text)
            return list(rows or []), text, ""
        except Exception as exc:
            errors.append(f"{text}: {exc}")
    return [], "", "; ".join(errors)


def _extract_count(rows: list[dict[str, Any]]) -> int | None:
    if not rows:
        return None
    first = rows[0]
    if not isinstance(first, dict):
        return None
    preferred = ("RowCount", "rowcount", "Количество", "Count", "count")
    values: list[Any] = []
    for key in preferred:
        if key in first:
            values.append(first.get(key))
    values.extend(first.values())
    for value in values:
        try:
            text = str(value).replace("\xa0", "").replace(" ", "").strip()
            if not text:
                continue
            return int(float(text.replace(",", ".")))
        except Exception:
            continue
    return None


def _object_title(obj: Any) -> str:
    title = getattr(obj, "title", "")
    if title:
        return str(title)
    synonyms = getattr(obj, "synonyms", None)
    if isinstance(synonyms, dict):
        return str(synonyms.get("uk") or synonyms.get("en") or "")
    return str(getattr(obj, "name", "") or "")


def _group_direct_migration(direct_migration: dict[str, Any] | None) -> dict[str, Any]:
    by_kind: dict[str, dict[str, Any]] = {}
    if not isinstance(direct_migration, dict):
        return {"summary": {}, "by_kind": by_kind}
    for table in direct_migration.get("tables") or []:
        if not isinstance(table, dict):
            continue
        kind = _normalize_direct_kind(table.get("kind"))
        role = str(table.get("table_role") or "data").strip() or "data"
        bucket = by_kind.setdefault(
            kind,
            {"tables": 0, "source_rows": 0, "imported_rows": 0, "errors": 0, "roles": {}},
        )
        bucket["tables"] += 1
        bucket["source_rows"] += int(table.get("source_rows") or 0)
        bucket["imported_rows"] += int(table.get("imported_rows") or 0)
        if table.get("errors"):
            bucket["errors"] += 1
        roles = bucket.setdefault("roles", {})
        role_bucket = roles.setdefault(role, {"tables": 0, "source_rows": 0, "imported_rows": 0, "errors": 0})
        role_bucket["tables"] += 1
        role_bucket["source_rows"] += int(table.get("source_rows") or 0)
        role_bucket["imported_rows"] += int(table.get("imported_rows") or 0)
        if table.get("errors"):
            role_bucket["errors"] += 1
    return {
        "summary": dict(direct_migration.get("summary") or {}),
        "storage_mode": str(direct_migration.get("storage_mode") or ""),
        "packed_table": str(direct_migration.get("packed_table") or ""),
        "by_kind": by_kind,
    }


def _build_com_by_type(entries: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    by_type: dict[str, dict[str, int]] = {}
    for entry in entries:
        obj_type = str(entry.get("obj_type") or "unknown")
        bucket = by_type.setdefault(
            obj_type,
            {"objects": 0, "counted_objects": 0, "rows": 0, "errors": 0, "unsupported": 0},
        )
        bucket["objects"] += 1
        if entry.get("unsupported"):
            bucket["unsupported"] += 1
        if entry.get("error"):
            bucket["errors"] += 1
        if entry.get("row_count") is not None:
            bucket["counted_objects"] += 1
            bucket["rows"] += int(entry.get("row_count") or 0)
    return by_type


def _compare_by_type(
    *,
    com_by_type: dict[str, dict[str, int]],
    direct_by_kind: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    primary_roles = {
        "catalog": {"object"},
        "document": {"object"},
        "business_process": {"object"},
        "task": {"object"},
        "exchange_plan": {"object"},
        "chart_of_accounts": {"object"},
        "chart_of_characteristic_types": {"object"},
        "chart_of_calculation_types": {"object"},
        "register_info": {"register_data"},
        "register_accum": {"register_data"},
        "register_accounting": {"register_data"},
        "register_calc": {"register_data"},
        "enumeration": {"data"},
        "constants": {"constant_value"},
        "journal": {"journal"},
        "sequence": {"data"},
    }

    def _primary_imported(kind: str, direct: dict[str, Any]) -> int:
        roles = direct.get("roles") if isinstance(direct, dict) else {}
        wanted = primary_roles.get(kind)
        if not isinstance(roles, dict) or not wanted:
            return int((direct or {}).get("imported_rows") or 0)
        found = 0
        matched = False
        for role in wanted:
            role_bucket = roles.get(role)
            if isinstance(role_bucket, dict):
                matched = True
                found += int(role_bucket.get("imported_rows") or 0)
        return found if matched else int((direct or {}).get("imported_rows") or 0)

    out: list[dict[str, Any]] = []
    for kind in sorted(set(com_by_type) | set(direct_by_kind)):
        com_rows = int((com_by_type.get(kind) or {}).get("rows") or 0)
        direct = direct_by_kind.get(kind) or {}
        direct_rows = int(direct.get("imported_rows") or 0)
        direct_primary_rows = _primary_imported(kind, direct)
        direct_source_rows = int(direct.get("source_rows") or 0)
        if com_rows == direct_rows and com_rows == direct_source_rows and com_rows == direct_primary_rows:
            continue
        out.append(
            {
                "type": kind,
                "com_rows": com_rows,
                "direct_source_rows": direct_source_rows,
                "direct_imported_rows": direct_rows,
                "direct_primary_imported_rows": direct_primary_rows,
                "diff_vs_imported": com_rows - direct_rows,
                "diff_vs_primary_imported": com_rows - direct_primary_rows,
                "com": com_by_type.get(kind) or {},
                "direct": direct,
            }
        )
    return out


def build_com_data_audit(
    conn: Any,
    *,
    direct_migration: dict[str, Any] | None = None,
    include_samples: bool = False,
    sample_limit: int = 3,
    include_types: Iterable[str] | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Build a COM visibility report and compare it with .1CD migration output."""

    started = time.time()
    allowed_types = {str(t).strip() for t in include_types or [] if str(t).strip()}
    objects = list(conn.list_all_metadata(include_attrs=False) or [])
    entries: list[dict[str, Any]] = []

    if progress is not None:
        try:
            progress({"stage": "metadata", "total_objects": len(objects)})
        except Exception:
            pass

    for index, obj in enumerate(objects, start=1):
        obj_type = str(getattr(obj, "obj_type", "") or "").strip()
        name = str(getattr(obj, "name", "") or "").strip()
        if allowed_types and obj_type not in allowed_types:
            continue

        entry: dict[str, Any] = {
            "obj_type": obj_type,
            "name": name,
            "title": _object_title(obj),
            "uuid": str(getattr(obj, "uuid", "") or ""),
        }
        src = _source_for(obj_type, name)
        if src is None:
            entry["unsupported"] = True
            entry["reason"] = _UNQUERYABLE_TYPES.get(obj_type, "no 1C query source mapping")
            entries.append(entry)
            continue

        entry["query_source"] = {"english": src.english, "russian": src.russian}
        rows, query_used, error = _try_queries(conn, _count_queries(src))
        row_count = _extract_count(rows)
        entry["count_query"] = query_used
        if row_count is None:
            entry["row_count"] = None
            entry["error"] = error or "count query returned no scalar row count"
        else:
            entry["row_count"] = row_count

        if include_samples and row_count:
            sample_rows, sample_query, sample_error = _try_queries(conn, _sample_queries(src, sample_limit))
            entry["sample_query"] = sample_query
            entry["sample_rows"] = sample_rows[: max(0, int(sample_limit or 0))]
            if sample_error and not entry.get("error"):
                entry["sample_error"] = sample_error

        entries.append(entry)
        if progress is not None and (index == len(objects) or index % 25 == 0):
            try:
                progress({"stage": "objects", "current": index, "total": len(objects), "object": name})
            except Exception:
                pass

    com_by_type = _build_com_by_type(entries)
    direct_grouped = _group_direct_migration(direct_migration)
    comparison = {
        "direct": direct_grouped,
        "by_type": _compare_by_type(
            com_by_type=com_by_type,
            direct_by_kind=dict(direct_grouped.get("by_kind") or {}),
        ),
    }

    counted = sum(1 for entry in entries if entry.get("row_count") is not None)
    errors = sum(1 for entry in entries if entry.get("error"))
    unsupported = sum(1 for entry in entries if entry.get("unsupported"))
    total_rows = sum(int(entry.get("row_count") or 0) for entry in entries if entry.get("row_count") is not None)

    return {
        "asset_key": ONEC_COM_DATA_AUDIT_ASSET_KEY,
        "started_at": started,
        "finished_at": time.time(),
        "config_name": str(getattr(conn, "config_name", "") or ""),
        "config_version": str(getattr(conn, "config_version", "") or ""),
        "summary": {
            "metadata_objects_seen": len(objects),
            "objects_audited": len(entries),
            "counted_objects": counted,
            "unsupported_objects": unsupported,
            "objects_with_errors": errors,
            "rows_visible_via_com": total_rows,
        },
        "by_type": com_by_type,
        "comparison": comparison,
        "objects": entries,
    }


def store_com_data_audit_asset(
    db: Any,
    report: dict[str, Any],
    *,
    asset_key: str = ONEC_COM_DATA_AUDIT_ASSET_KEY,
) -> str:
    payload = json.dumps(report, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    db.put_assets_bulk([(asset_key, payload, "application/json")])
    return asset_key
