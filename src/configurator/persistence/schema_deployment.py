"""src.configurator.persistence.schema_deployment

Schema Deployment Service — the missing link between the Configurator and the Client.

When the user clicks "Save" or "Update DB" in the configurator, this module
reads the manifest and ensures all required physical data tables exist in mpdb.

Naming convention (matches client/forms/*.py):
  Catalog   → data_catalog_<name_lower>
  Document  → data_document_<name_lower>
  TP        → data_tp_<ownername_lower>_<tpname_lower>
  Register  → data_reg_<name_lower>

Field type mapping (manifest → mpdb schema):
  String/Рядок → "str"
  Number/Число  → "float"
  Integer/Ціле  → "int"
  Boolean/Логічне → "bool"
  Date/Дата     → "str"  (ISO-8601)
  Any/unknown   → "str"

Usage:
    from src.configurator.persistence.schema_deployment import SchemaDeploymentService
    svc = SchemaDeploymentService(db)
    report = svc.deploy_all()          # idempotent full sync
    report = svc.deploy_object(guid)   # single object
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class DeployedTable:
    name: str
    created: bool   # True = newly created, False = already existed


@dataclass
class DeployResult:
    object_guid: str
    object_name: str
    object_type: str
    tables: List[DeployedTable] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class DeployReport:
    results: List[DeployResult] = field(default_factory=list)
    skipped: int = 0

    @property
    def created(self) -> int:
        return sum(1 for r in self.results for t in r.tables if t.created)

    @property
    def existing(self) -> int:
        return sum(1 for r in self.results for t in r.tables if not t.created)

    @property
    def errors(self) -> List[str]:
        return [e for r in self.results for e in r.errors]

    def summary(self) -> str:
        return (
            f"Deploy complete: {self.created} table(s) created, "
            f"{self.existing} already existed, {self.skipped} object(s) skipped, "
            f"{len(self.errors)} error(s)."
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEPLOYABLE_TYPES = frozenset({
    "catalog", "document", "constant", "constants", "register", "register_info",
    "register_accum", "register_accounting", "register_calc",
    "chart_of_accounts", "chart_of_characteristic_types",
    "business_process", "task",
})
_CATALOG_LIKE_TYPES = frozenset({
    "catalog", "chart_of_accounts", "chart_of_characteristic_types",
})
_DOCUMENT_LIKE_TYPES = frozenset({
    "document", "business_process", "task",
})

_TYPE_MAP: Dict[str, str] = {
    # EN
    "string": "str", "str": "str", "text": "str",
    "number": "float", "float": "float", "decimal": "float",
    "integer": "int", "int": "int",
    "boolean": "bool", "bool": "bool",
    "date": "str", "datetime": "str",
    "json": "json",
    # UK
    "рядок": "str", "текст": "str",
    "число": "float", "дробове": "float",
    "ціле": "int",
    "логічне": "bool",
    "дата": "str",
}


def _mpdb_type(value_type: str) -> str:
    return _TYPE_MAP.get(str(value_type or "").strip().lower(), "str")


def _table_exists(db, name: str) -> bool:
    """Check if table exists using the public API (robust to internal changes)."""
    try:
        db.table(name)
        return True
    except Exception:
        return False


def _ensure_table(db, name: str, schema: Dict[str, Any]) -> DeployedTable:
    """Create table if it doesn't exist. Returns DeployedTable(created=True/False)."""
    if _table_exists(db, name):
        return DeployedTable(name=name, created=False)
    try:
        db.create_table(name, schema)
        log.info("Created table: %s", name)
        return DeployedTable(name=name, created=True)
    except Exception as e:
        msg = str(e)
        if "exists" in msg.lower():
            return DeployedTable(name=name, created=False)
        raise


def _field_defs_from_payload(obj: Dict) -> List[Dict]:
    """Read field defs from payload arrays (used after 1C import)."""
    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
    out: List[Dict] = []
    seen: set = set()
    for key in ("requisites", "attributes"):
        for item in (payload.get(key) or []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            vtype = str(
                item.get("type") or item.get("mp_type") or item.get("value_type") or "str"
            ).strip()
            out.append({"name": name, "title": str(item.get("title") or name), "value_type": vtype, "guid": ""})
    return out


def _tp_defs_from_payload(obj: Dict) -> List[Dict]:
    """Read tabular-part defs from payload (used after 1C import)."""
    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
    tps: List[Dict] = []
    for tp in (payload.get("tabular_parts") or []):
        if not isinstance(tp, dict):
            continue
        tp_name = str(tp.get("name") or "").strip()
        if not tp_name:
            continue
        fields: List[Dict] = []
        for col in (tp.get("fields") or tp.get("columns") or []):
            if not isinstance(col, dict):
                continue
            col_name = str(col.get("name") or "").strip()
            if not col_name:
                continue
            vtype = str(col.get("type") or col.get("mp_type") or col.get("value_type") or "str").strip()
            fields.append({"name": col_name, "title": str(col.get("title") or col_name), "value_type": vtype, "guid": ""})
        tps.append({"name": tp_name, "title": str(tp.get("title") or tp_name), "guid": "", "fields": fields})
    return tps


def _get_field_defs(manifest_rows: list, parent_guid: str,
                    folder_types: Tuple[str, ...]) -> List[Dict]:
    """Walk manifest to find field definitions under parent_guid."""
    folder_guid: Optional[str] = None
    for r in manifest_rows:
        if (str(r.get("parent_guid") or "") == parent_guid and
                str(r.get("type") or "").strip().lower() in folder_types):
            folder_guid = str(r.get("guid") or "")
            break
    if not folder_guid:
        return []
    fields = []
    for r in manifest_rows:
        if str(r.get("parent_guid") or "") != folder_guid:
            continue
        tp = str(r.get("type") or "").strip().lower()
        if tp not in ("attribute", "field", "dimension", "resource", "measure"):
            continue
        pay = r.get("payload") if isinstance(r.get("payload"), dict) else {}
        fields.append({
            "name":       str(r.get("name") or ""),
            "title":      str(r.get("title") or r.get("name") or ""),
            "value_type": str(pay.get("value_type") or pay.get("type") or "String"),
            "guid":       str(r.get("guid") or ""),
        })
    return fields


def _get_tp_defs(manifest_rows: list, doc_guid: str) -> List[Dict]:
    """Return tabular part definitions [{name, guid, fields}]."""
    tp_folder: Optional[str] = None
    for r in manifest_rows:
        if (str(r.get("parent_guid") or "") == doc_guid and
                str(r.get("type") or "").strip().lower() in (
                    "tabular_parts", "tabular_parts_folder")):
            tp_folder = str(r.get("guid") or "")
            break
    if not tp_folder:
        return []
    tps = []
    for r in manifest_rows:
        if str(r.get("parent_guid") or "") != tp_folder:
            continue
        tp_guid = str(r.get("guid") or "")
        tp_fields = _get_field_defs(
            manifest_rows, tp_guid,
            ("attributes", "fields_folder", "tabular_part_fields"),
        )
        tps.append({
            "name":   str(r.get("name") or ""),
            "title":  str(r.get("title") or r.get("name") or ""),
            "guid":   tp_guid,
            "fields": tp_fields,
        })
    return tps


# ---------------------------------------------------------------------------
# Schema builders
# ---------------------------------------------------------------------------

_CATALOG_SYSTEM_FIELDS: Dict[str, Any] = {
    "_guid":        {"type": "str",  "unique": True, "indexed": True},
    "_deleted":     {"type": "bool", "indexed": True},
    "_code":        {"type": "str",  "indexed": True},
    "_description": {"type": "str",  "indexed": True},
    "_parent_guid": {"type": "str",  "indexed": True},
    "_owner_guid":  {"type": "str",  "indexed": True},
    "_is_folder":   {"type": "bool", "indexed": True},
    "_predefined":  {"type": "bool", "indexed": True},
}

_DOC_SYSTEM_FIELDS: Dict[str, Any] = {
    "_guid":    {"type": "str",  "unique": True, "indexed": True},
    "_deleted": {"type": "bool", "indexed": True},
    "_number":  {"type": "str",  "indexed": True},
    "_date":    {"type": "str",  "indexed": True},
    "_posted":  {"type": "bool", "indexed": True},
    "_posting_registers": {"type": "json"},
    "_number_prefix": {"type": "str"},
    "_operation_kind": {"type": "str"},
}

_TP_BASE_SYSTEM_FIELDS: Dict[str, Any] = {
    "_row_guid": {"type": "str",  "unique": True, "indexed": True},
    "_line_no":  {"type": "int",  "indexed": True},
    "_active":   {"type": "bool", "indexed": True},
}
_TP_SYSTEM_FIELDS: Dict[str, Any] = {
    **_TP_BASE_SYSTEM_FIELDS,
    "_doc_guid": {"type": "str",  "indexed": True},
}
_TP_OWNER_GUID_SYSTEM_FIELDS: Dict[str, Any] = {
    **_TP_BASE_SYSTEM_FIELDS,
    "_owner_guid": {"type": "str", "indexed": True},
}

_REG_SYSTEM_FIELDS: Dict[str, Any] = {
    "_rec_guid": {"type": "str",  "unique": True, "indexed": True},
    "_period":   {"type": "str",  "indexed": True},  # ISO date
    "_recorder": {"type": "str",  "indexed": True},  # doc_guid
    "_kind":     {"type": "str"},                    # "+" / "-" for accum
    "_line_no":  {"type": "int",  "indexed": True},
    "_active":   {"type": "bool", "indexed": True},
    "_record_kind": {"type": "str", "indexed": True},
}

_CONSTANTS_SCHEMA: Dict[str, Any] = {
    "fields": {
        "key": {"type": "str", "unique": True, "indexed": True},
        "value": {"type": "json"},
    }
}


def _fields_schema(custom_fields: List[Dict]) -> Dict[str, Any]:
    """Build mpdb fields dict for custom fields."""
    out: Dict[str, Any] = {}
    for fd in custom_fields:
        name = str(fd.get("name") or "").strip()
        if not name or name.startswith("_"):
            continue
        vtype = _mpdb_type(fd.get("value_type") or "str")
        out[name] = {"type": vtype}
    return out


def _catalog_schema(custom_fields: List[Dict]) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    fields.update(_CATALOG_SYSTEM_FIELDS)
    fields.update(_fields_schema(custom_fields))
    return {"fields": fields}


def _document_schema(custom_fields: List[Dict]) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    fields.update(_DOC_SYSTEM_FIELDS)
    fields.update(_fields_schema(custom_fields))
    return {"fields": fields}


def _tp_schema(custom_fields: List[Dict], *, owner_field: str = "_doc_guid") -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    fields.update(_TP_BASE_SYSTEM_FIELDS)
    fields[owner_field] = {"type": "str", "indexed": True}
    fields.update(_fields_schema(custom_fields))
    return {"fields": fields}


def _register_schema(dimensions: List[Dict], resources: List[Dict]) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    fields.update(_REG_SYSTEM_FIELDS)
    fields.update(_fields_schema(dimensions))
    fields.update(_fields_schema(resources))
    return {"fields": fields}


# ---------------------------------------------------------------------------
# SchemaDeploymentService
# ---------------------------------------------------------------------------

class SchemaDeploymentService:
    """Reads manifest metadata and creates/updates physical data tables in mpdb.

    All operations are idempotent: calling deploy_all() multiple times is safe.
    Tables that already exist are left untouched.

    Note: mpdb does not support ALTER TABLE, so adding fields to existing
    tables requires a migration strategy (future work). New tables always
    include all declared fields.
    """

    def __init__(self, db) -> None:
        self._db = db

    # ---- Public API ----

    def deploy_all(self, manifest_rows: Optional[list] = None) -> DeployReport:
        """Deploy tables for ALL deployable objects in the manifest."""
        rows = manifest_rows or self._load_manifest()
        objects = self._deployable_objects(rows)
        report = DeployReport()

        for obj in objects:
            obj_type = str(obj.get("type") or "").strip().lower()
            if obj_type not in _DEPLOYABLE_TYPES:
                report.skipped += 1
                continue
            try:
                result = self._deploy_one(obj, rows)
                report.results.append(result)
            except Exception as e:
                result = DeployResult(
                    object_guid=str(obj.get("guid") or ""),
                    object_name=str(obj.get("name") or ""),
                    object_type=obj_type,
                    errors=[f"Unexpected error: {e}"],
                )
                report.results.append(result)
                log.error("Deploy failed for %s: %s", obj.get("name"), e)

        log.info(report.summary())
        return report

    def deploy_object(self, guid: str) -> DeployResult:
        """Deploy tables for a single manifest object by GUID."""
        rows = self._load_manifest()
        obj = next(
            (r for r in rows if str(r.get("guid") or "") == guid),
            None,
        )
        if obj is None:
            return DeployResult(
                object_guid=guid, object_name="", object_type="",
                errors=[f"Object {guid} not found in manifest"],
            )
        return self._deploy_one(obj, rows)

    # ---- Internal ----

    def _load_manifest(self) -> list:
        try:
            return self._db.table("manifest").select() or []
        except Exception:
            return []

    def _deployable_objects(self, rows: list) -> list:
        return [
            r for r in rows
            if str(r.get("kind") or "").strip().lower() == "object"
            and str(r.get("type") or "").strip().lower() in _DEPLOYABLE_TYPES
        ]

    def _deploy_one(self, obj: Dict, manifest_rows: list) -> DeployResult:
        obj_type = str(obj.get("type") or "").strip().lower()
        obj_name = str(obj.get("name") or "").strip()
        obj_guid = str(obj.get("guid") or "").strip()

        result = DeployResult(
            object_guid=obj_guid,
            object_name=obj_name,
            object_type=obj_type,
        )

        if obj_type in _CATALOG_LIKE_TYPES:
            self._deploy_catalog(obj, manifest_rows, result)
        elif obj_type in ("constant", "constants"):
            self._deploy_constant(obj, manifest_rows, result)
        elif obj_type in _DOCUMENT_LIKE_TYPES:
            self._deploy_document(obj, manifest_rows, result)
        elif obj_type in ("register", "register_info", "register_accum",
                          "register_accounting", "register_calc"):
            self._deploy_register(obj, manifest_rows, result)

        return result

    def _deploy_catalog(self, obj: Dict, rows: list, result: DeployResult) -> None:
        name = str(obj.get("name") or "").strip()
        guid = str(obj.get("guid") or "").strip()
        if not name:
            result.errors.append("Catalog has no name")
            return

        tbl_name = f"data_catalog_{name.lower()}"
        custom = _get_field_defs(rows, guid, ("attributes", "fields_folder"))
        if not custom:
            custom = _field_defs_from_payload(obj)

        try:
            dt = _ensure_table(self._db, tbl_name, _catalog_schema(custom))
            result.tables.append(dt)
        except Exception as e:
            result.errors.append(f"Failed to create {tbl_name}: {e}")

        self._deploy_tabular_parts(
            owner_name=name,
            owner_guid=guid,
            rows=rows,
            result=result,
            owner_field="_owner_guid",
            obj=obj,
        )

    def _deploy_constant(self, obj: Dict, rows: list, result: DeployResult) -> None:
        name = str(obj.get("name") or "").strip()
        if not name:
            result.errors.append("Constant has no name")
            return
        try:
            dt = _ensure_table(self._db, "data_constants", _CONSTANTS_SCHEMA)
            result.tables.append(dt)
        except Exception as e:
            result.errors.append(f"Failed to create data_constants: {e}")

    def _deploy_document(self, obj: Dict, rows: list, result: DeployResult) -> None:
        name = str(obj.get("name") or "").strip()
        guid = str(obj.get("guid") or "").strip()
        if not name:
            result.errors.append("Document has no name")
            return

        hdr_name = f"data_document_{name.lower()}"
        custom = _get_field_defs(rows, guid, ("attributes", "fields_folder"))
        if not custom:
            custom = _field_defs_from_payload(obj)
        try:
            dt = _ensure_table(self._db, hdr_name, _document_schema(custom))
            result.tables.append(dt)
        except Exception as e:
            result.errors.append(f"Failed to create {hdr_name}: {e}")

        self._deploy_tabular_parts(
            owner_name=name,
            owner_guid=guid,
            rows=rows,
            result=result,
            owner_field="_doc_guid",
            obj=obj,
        )

    def _deploy_register(self, obj: Dict, rows: list, result: DeployResult) -> None:
        name = str(obj.get("name") or "").strip()
        guid = str(obj.get("guid") or "").strip()
        if not name:
            result.errors.append("Register has no name")
            return

        tbl_name = f"data_reg_{name.lower()}"
        dims = _get_field_defs(rows, guid, ("dimensions", "dimensions_folder"))
        res  = _get_field_defs(rows, guid, ("resources",  "resources_folder"))
        if not dims and not res:
            payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
            seen: set = set()
            for key in ("dimensions",):
                for item in (payload.get(key) or []):
                    if not isinstance(item, dict):
                        continue
                    n = str(item.get("name") or "").strip()
                    if n and n not in seen:
                        seen.add(n)
                        dims.append({"name": n, "title": str(item.get("title") or n),
                                     "value_type": str(item.get("type") or "str"), "guid": ""})
            seen2: set = set()
            for key in ("resources",):
                for item in (payload.get(key) or []):
                    if not isinstance(item, dict):
                        continue
                    n = str(item.get("name") or "").strip()
                    if n and n not in seen2:
                        seen2.add(n)
                        res.append({"name": n, "title": str(item.get("title") or n),
                                    "value_type": str(item.get("type") or "str"), "guid": ""})

        try:
            dt = _ensure_table(self._db, tbl_name, _register_schema(dims, res))
            result.tables.append(dt)
        except Exception as e:
            result.errors.append(f"Failed to create {tbl_name}: {e}")

    def _deploy_tabular_parts(
        self,
        *,
        owner_name: str,
        owner_guid: str,
        rows: list,
        result: DeployResult,
        owner_field: str,
        obj: Optional[Dict] = None,
    ) -> None:
        tps = _get_tp_defs(rows, owner_guid)
        if not tps and obj is not None:
            tps = _tp_defs_from_payload(obj)
        for tp in tps:
            tp_name = str(tp.get("name") or "").strip()
            if not tp_name:
                continue
            tbl_name = f"data_tp_{owner_name.lower()}_{tp_name.lower()}"
            try:
                dt = _ensure_table(
                    self._db,
                    tbl_name,
                    _tp_schema(tp.get("fields") or [], owner_field=owner_field),
                )
                result.tables.append(dt)
            except Exception as e:
                result.errors.append(f"Failed to create TP {tbl_name}: {e}")
