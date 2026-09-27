from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from src.infra.onec.onecd_source import OneCDConfigSource
from src.mpdb.mpdb import Mpdb


ONECD_DATA_MIGRATION_ASSET_KEY = "onec_data_migration/manifest.json"
_PACKED_TABLE_FALLBACK = "onec__data_rows"

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
    "information_register",
    "accumulation_register",
    "accounting_register",
    "calculation_register",
}
_DATA_TABLE_RE = re.compile(r"^data_(catalog|document|reg)_(.+)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class VirtualObjectRef:
    family: str
    name: str
    order: int
    source_table: str
    logical_table: str
    kind: str


@dataclass
class VirtualOneCDataTables:
    db: Mpdb
    enabled: bool = False
    packed_table: str = ""
    source_path: str = ""
    object_refs_by_table: dict[str, list[VirtualObjectRef]] = field(default_factory=dict)
    tabular_refs_by_table: dict[str, list[VirtualObjectRef]] = field(default_factory=dict)
    constant_refs: list[VirtualObjectRef] = field(default_factory=list)
    source_alias_by_key: dict[tuple[str, str], str] = field(default_factory=dict)
    physical_source_path_by_key: dict[tuple[str, str], str] = field(default_factory=dict)
    manifest_alias_by_origin: dict[str, str] = field(default_factory=dict)
    manifest_alias_by_metadata_ref: dict[str, str] = field(default_factory=dict)
    # UUID is the stable join key between ConfigDumpInfo/DBNames and the
    # translated manifest name. Names are not safe here: imported XML may be
    # mojibaked or transliterated differently from the .1CD catalog.
    manifest_alias_by_uuid: dict[str, str] = field(default_factory=dict)
    source_rows_cache: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    physical_rows_cache: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    asset_cache: dict[str, bytes] = field(default_factory=dict)
    manifest_tables_by_source: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Packed rows are appended in migration-manifest order.  Keeping the
    # physical rowid interval lets a virtual table use point reads instead of
    # scanning the whole packed table for every document/catalog request.
    source_rowid_ranges: dict[str, tuple[int, int]] = field(default_factory=dict)
    physical_slot_map_by_source: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)
    packed_rows_cache: list[dict[str, Any]] = field(default_factory=list)
    constant_rows_cache: list[dict[str, Any]] = field(default_factory=list)
    document_source_path_by_logical: dict[str, str] = field(default_factory=dict)
    packed_rows_loaded: bool = False
    constant_rows_loaded: bool = False

    def __post_init__(self) -> None:
        # Initialise non-dataclass private caches here so they are always present
        self._overlay_schema_cache: dict[str, dict[str, Any]] = {}
        self._metadata_by_uuid: dict[str, dict[str, Any]] = {}
        self._storage_bindings: dict[str, dict[str, int]] | None = None
        self._binding_error = ""
        self._field_aliases: dict[str, dict[str, list[tuple[str, str]]]] = {}
        self._migration_limit: int | None = None
        self._reference_presentation_cache: dict[str, str] | None = None
        self._load_context()

    # ------------------------------------------------------------------
    # Context / catalog
    # ------------------------------------------------------------------

    def _load_context(self) -> None:
        try:
            payload, _mime = self.db.get_asset(ONECD_DATA_MIGRATION_ASSET_KEY)
            manifest = json.loads(payload.decode("utf-8"))
        except Exception:
            return

        if str(manifest.get("storage_mode") or "").strip().lower() != "packed":
            return

        self._migration_limit = manifest.get("limit_per_table")
        if isinstance(manifest.get("storage_bindings"), dict):
            self._storage_bindings = manifest["storage_bindings"]

        self.packed_table = str(manifest.get("packed_table") or _PACKED_TABLE_FALLBACK).strip() or _PACKED_TABLE_FALLBACK
        self.source_path = str(manifest.get("source_path") or "").strip()
        if not self.source_path:
            return

        source = Path(self.source_path)
        migration_tables = [
            entry for entry in list(manifest.get("tables") or [])
            if isinstance(entry, dict) and str(entry.get("source_table") or "").strip()
        ]
        if not source.exists() and not migration_tables:
            return

        try:
            manifest_rows = self.db.table("manifest").select() or []
        except Exception:
            manifest_rows = []

        objects: list[Any] = []
        # The data migration manifest already contains the physical table,
        # metadata UUID, family, role and row count.  Do not parse the entire
        # .1CD/XML catalog on every first client data request.
        if not migration_tables:
            try:
                catalog = OneCDConfigSource(source)
                objects = catalog.metadata_objects()
            except Exception:
                return

        for row in manifest_rows:
            if not isinstance(row, dict):
                continue
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            imported = payload.get("imported") if isinstance(payload.get("imported"), dict) else {}
            for uid in (
                row.get("guid"),
                imported.get("src_uuid"),
                imported.get("src_uid"),
            ):
                uid_key = str(uid or "").strip().casefold()
                if uid_key:
                    self.manifest_alias_by_uuid[uid_key] = str(row.get("name") or "").strip()
                    self._metadata_by_uuid[uid_key] = row
            origin = str(imported.get("origin") or "").strip()
            if origin:
                self.manifest_alias_by_origin[self._origin_key(origin)] = str(row.get("name") or "").strip()
            metadata_ref = str(payload.get("metadata_ref") or "").strip()
            if metadata_ref:
                self.manifest_alias_by_metadata_ref[metadata_ref.casefold()] = str(row.get("name") or "").strip()

        self.manifest_tables_by_source = {
            str(entry.get("source_table") or "").strip(): dict(entry)
            for entry in list(manifest.get("tables") or [])
            if isinstance(entry, dict) and str(entry.get("source_table") or "").strip()
        }
        packed_rowid = 1
        for entry in list(manifest.get("tables") or []):
            if not isinstance(entry, dict):
                continue
            source_table = str(entry.get("source_table") or "").strip()
            imported_rows = max(0, int(entry.get("imported_rows") or 0))
            if source_table and imported_rows:
                self.source_rowid_ranges[source_table] = (
                    packed_rowid,
                    packed_rowid + imported_rows - 1,
                )
                packed_rowid += imported_rows

        try:
            payload, _mime = self.db.get_asset("onec_analysis/physical_mapping.json")
            physical = json.loads(payload.decode("utf-8"))
        except Exception:
            physical = {}

        for item in list(physical.get("xml_objects") or []):
            if not isinstance(item, dict):
                continue
            family = str(item.get("family") or "").strip().lower()
            name = str(item.get("name") or "").strip()
            source_path = str(item.get("source_path") or "").strip()
            if not family or not name or not source_path:
                continue
            self.physical_source_path_by_key[(family, name.casefold())] = source_path
            alias = self._alias_for_source_path(source_path)
            if alias:
                self.source_alias_by_key[(family, name.casefold())] = alias

        if migration_tables:
            for entry in migration_tables:
                family = self._family_from_migration_entry(entry)
                source_table = str(entry.get("source_table") or "").strip()
                role = str(entry.get("table_role") or "").strip().lower()
                if not family or not source_table or role not in {"object", "main", "", "tabular_part"}:
                    continue
                source_uuid = str(entry.get("metadata_uuid") or "").strip().casefold()
                alias = self.manifest_alias_by_uuid.get(source_uuid, "") if source_uuid else ""
                alias = alias or str(entry.get("logical_name") or "").strip()
                logical_table = self._logical_table_name(family, alias)
                if not logical_table:
                    continue
                ref = VirtualObjectRef(
                    family=family,
                    name=str(entry.get("logical_name") or alias),
                    order=int(entry.get("metadata_order") or self._source_order(source_table) or 0),
                    source_table=source_table,
                    logical_table=logical_table,
                    kind=self._family_kind(family),
                )
                if role == "tabular_part":
                    continue
                aliases = {logical_table.lower()}
                source_name = str(entry.get("logical_name") or "").strip()
                if source_name:
                    source_alias = self._logical_table_name(family, source_name)
                    if source_alias:
                        aliases.add(source_alias.lower())
                for table_alias in aliases:
                    self.object_refs_by_table.setdefault(table_alias, []).append(ref)
            self._load_tabular_refs_from_migration_manifest(migration_tables)

        for obj in objects:
            family = str(getattr(obj, "family", "") or "").strip().lower()
            name = str(getattr(obj, "name", "") or "").strip()
            # `order` is the semantic/XML order. Physical 1CD tables use the
            # DBNames order (`_DOCUMENT174`, not the semantic order such as
            # 2100092). Prefer the physical order whenever the catalog has it.
            order = int(
                getattr(obj, "dbname_order", 0)
                or getattr(obj, "order", 0)
                or 0
            )
            if not name or order <= 0:
                continue
            source_uuid = str(getattr(obj, "uuid", "") or "").strip().casefold()
            alias = self.manifest_alias_by_uuid.get(source_uuid, "") if source_uuid else ""
            if not alias:
                alias = self._alias_for_source_object(family, name)
            logical_table = self._logical_table_name(family, alias or name)
            source_table = self._source_table_name(family, order)
            if not logical_table or not source_table:
                continue
            ref = VirtualObjectRef(
                family=family,
                name=name,
                order=order,
                source_table=source_table,
                logical_table=logical_table,
                kind=self._family_kind(family),
            )
            if family == "constant":
                self.constant_refs.append(ref)
            else:
                aliases = {logical_table.lower()}
                if alias:
                    source_table_alias = self._logical_table_name(family, name)
                    if source_table_alias:
                        aliases.add(source_table_alias.lower())
                for table_alias in aliases:
                    self.object_refs_by_table.setdefault(table_alias, []).append(ref)

        for table_name, refs in list(self.object_refs_by_table.items()):
            refs.sort(key=lambda item: (self._family_priority(item.family), item.order, item.name.casefold()))
            self.object_refs_by_table[table_name] = refs
        self.constant_refs.sort(key=lambda item: (item.order, item.name.casefold()))
        if not migration_tables:
            self._load_document_tabular_refs(manifest, objects)
        self.enabled = True

    @staticmethod
    def _source_order(source_table: str) -> int:
        match = re.search(r"(?:_DOCUMENT|_REFS|_ACCUMRG|_INFOREG|_CHART|_TASK|_BIZPROC)(\d+)", str(source_table or ""), re.IGNORECASE)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _family_from_migration_entry(entry: dict[str, Any]) -> str:
        kind = str(entry.get("kind") or "").strip().lower()
        if kind in _CATALOG_LIKE_FAMILIES or kind in _DOCUMENT_LIKE_FAMILIES or kind in _REGISTER_LIKE_FAMILIES:
            return kind
        if kind in {"catalog", "reference", "enum"}:
            return "catalog"
        if kind in {"constant", "constants"}:
            return "constant"
        return ""

    def _load_tabular_refs_from_migration_manifest(self, entries: list[dict[str, Any]]) -> None:
        grouped: dict[str, list[VirtualObjectRef]] = {}
        for entry in entries:
            if str(entry.get("table_role") or "").strip().lower() != "tabular_part":
                continue
            family = self._family_from_migration_entry(entry)
            if family != "document":
                continue
            source_table = str(entry.get("source_table") or "").strip()
            uid = str(entry.get("metadata_uuid") or "").strip().casefold()
            alias = self.manifest_alias_by_uuid.get(uid, "") or str(entry.get("logical_name") or "").strip()
            if not source_table or not alias:
                continue
            ref = VirtualObjectRef(
                family="tabular_part",
                name=str(entry.get("logical_table") or source_table),
                order=int(entry.get("metadata_order") or 0),
                source_table=source_table,
                logical_table=f"data_document_{alias.lower()}_rows",
                kind="tabular_part",
            )
            grouped.setdefault(alias.lower(), []).append(ref)
        for alias, refs in grouped.items():
            refs.sort(key=lambda item: (item.order, item.source_table.casefold()))
            self.tabular_refs_by_table[f"data_document_{alias}_rows"] = refs

    @staticmethod
    def _logical_table_name(family: str, name: str) -> str:
        family = str(family or "").strip().lower()
        obj_name = str(name or "").strip().lower()
        if not obj_name:
            return ""
        if family == "constant":
            return "data_constants"
        if family in _CATALOG_LIKE_FAMILIES:
            return f"data_catalog_{obj_name}"
        if family in _DOCUMENT_LIKE_FAMILIES:
            return f"data_document_{obj_name}"
        if family in _REGISTER_LIKE_FAMILIES:
            return f"data_reg_{obj_name}"
        return ""

    @staticmethod
    def _origin_key(origin: str) -> str:
        text = str(origin or "").strip().replace("\\", "/")
        if not text:
            return ""
        return text.casefold()

    @staticmethod
    def _origin_key_from_xmlconf_path(source_path: str) -> str:
        path = Path(str(source_path or "").strip())
        if not str(path):
            return ""
        parts = list(path.parts)
        xmlconf_idx = next((idx for idx, part in enumerate(parts) if part.casefold() == "xmlconf"), -1)
        if xmlconf_idx < 0:
            return ""
        rel = Path(*parts[xmlconf_idx + 1 :])
        if not rel.parts:
            return ""
        if rel.suffix.lower() != ".xml":
            rel = rel.with_suffix(".xml")
        return rel.as_posix().casefold()

    def _alias_for_source_path(self, source_path: str) -> str:
        origin_key = self._origin_key_from_xmlconf_path(source_path)
        if not origin_key:
            return ""
        return str(self.manifest_alias_by_origin.get(origin_key) or "").strip()

    def _alias_for_source_object(self, family: str, name: str) -> str:
        family_key = str(family or "").strip().lower()
        name_key = str(name or "").strip().casefold()
        if not family_key or not name_key:
            return ""
        alias = self.source_alias_by_key.get((family_key, name_key))
        if alias:
            return str(alias).strip()
        source_path = self.physical_source_path_by_key.get((family_key, name_key), "")
        if source_path:
            alias = self._alias_for_source_path(source_path)
            if alias:
                self.source_alias_by_key[(family_key, name_key)] = alias
                return alias
        return ""

    @staticmethod
    def _source_table_name(family: str, order: int) -> str:
        family = str(family or "").strip().lower()
        order = int(order or 0)
        if order <= 0:
            return ""
        prefix_map = {
            "catalog": "_REFERENCE",
            "chart_of_accounts": "_ACC",
            "chart_of_characteristic_types": "_CHRC",
            "document": "_DOCUMENT",
            "business_process": "_BPR",
            "task": "_TASK",
            "constant": "_CONST",
            "information_register": "_INFORG",
            "accumulation_register": "_ACCUMRG",
            "accounting_register": "_ACCRG",
            "calculation_register": "_CRG",
        }
        prefix = prefix_map.get(family)
        if not prefix:
            return ""
        return f"{prefix}{order}"

    @staticmethod
    def _family_kind(family: str) -> str:
        family = str(family or "").strip().lower()
        if family == "constant":
            return "constant"
        if family in _CATALOG_LIKE_FAMILIES:
            return "catalog"
        if family in _DOCUMENT_LIKE_FAMILIES:
            return "document"
        if family in _REGISTER_LIKE_FAMILIES:
            return "register"
        return family

    @staticmethod
    def _family_priority(family: str) -> int:
        family = str(family or "").strip().lower()
        return {
            "catalog": 10,
            "chart_of_accounts": 11,
            "chart_of_characteristic_types": 12,
            "document": 20,
            "business_process": 21,
            "task": 22,
            "tabular_part": 23,
            "constant": 30,
            "information_register": 40,
            "accumulation_register": 41,
            "accounting_register": 42,
            "calculation_register": 43,
        }.get(family, 99)

    def _is_physical_table(self, table_name: str) -> bool:
        if not table_name:
            return False
        if table_name in self.physical_rows_cache:
            return True
        try:
            self.db.table(table_name)
            return True
        except Exception:
            return False

    def _load_document_tabular_refs(self, manifest: dict[str, Any], objects: list[Any]) -> None:
        try:
            payload, _mime = self.db.get_asset("onec_analysis/physical_mapping.json")
            physical = json.loads(payload.decode("utf-8"))
        except Exception:
            physical = {}

        for item in list(physical.get("onecd_tables") or []):
            if not isinstance(item, dict):
                continue
            source_table = str(item.get("name") or "").strip()
            if not source_table:
                continue
            slot_map: dict[str, dict[str, str]] = {}
            for fm in list(item.get("field_mappings") or []):
                if not isinstance(fm, dict):
                    continue
                slot = str(fm.get("slot") or "").strip()
                if not slot:
                    continue
                slot_map[slot] = {
                    "source_field": str(fm.get("source_field") or "").strip(),
                    "target_field": str(fm.get("target_field") or "").strip(),
                }
            if slot_map:
                self.physical_slot_map_by_source[source_table] = slot_map

        for obj in objects:
            family = str(getattr(obj, "family", "") or "").strip().lower()
            if family != "document":
                continue
            name = str(getattr(obj, "name", "") or "").strip()
            order = int(getattr(obj, "order", 0) or 0)
            if not name or order <= 0:
                continue
            alias = self._alias_for_source_object(family, name) or name
            logical_table = self._logical_table_name(family, alias).lower()
            source_path = self.physical_source_path_by_key.get((family, name.casefold()), "")
            if not source_path:
                continue
            form_parts = self._document_form_part_names(Path(source_path))
            source_tables = self._document_tabular_source_tables(manifest, order)
            if not form_parts or not source_tables:
                continue
            refs: list[VirtualObjectRef] = []
            for index, (part_name, source_table) in enumerate(zip(form_parts, source_tables), start=1):
                part_alias = f"data_tp_{alias.lower()}_{part_name.strip().lower()}"
                ref = VirtualObjectRef(
                    family="tabular_part",
                    name=part_name,
                    order=index,
                    source_table=source_table,
                    logical_table=part_alias,
                    kind="tabular_part",
                )
                self.tabular_refs_by_table[part_alias.lower()] = [ref]
                source_alias_part = f"data_tp_{name.lower()}_{part_name.strip().lower()}"
                if source_alias_part.lower() != part_alias.lower():
                    self.tabular_refs_by_table[source_alias_part.lower()] = [ref]
                refs.append(ref)
            if refs:
                self.tabular_refs_by_table[f"data_document_{alias.lower()}_rows"] = list(refs)
                source_alias_rows = f"data_document_{name.lower()}_rows"
                if source_alias_rows.lower() != f"data_document_{alias.lower()}_rows":
                    self.tabular_refs_by_table[source_alias_rows.lower()] = list(refs)
                self.document_source_path_by_logical[logical_table] = source_path
                source_logical_table = self._logical_table_name(family, name).lower()
                if source_logical_table and source_logical_table != logical_table:
                    self.document_source_path_by_logical[source_logical_table] = source_path

    @staticmethod
    def _document_form_part_names(source_path: Path) -> list[str]:
        forms_dir = source_path / "Forms"
        if not forms_dir.exists():
            return []
        candidates: list[tuple[int, Path]] = []
        for file_path in list(forms_dir.rglob("Form.xml")) + list(forms_dir.glob("*.xml")):
            if not file_path.is_file():
                continue
            try:
                text = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            score = len(re.findall(r"<TitleDataPath>Объект\.([^.<>]+)\.RowsCount</TitleDataPath>", text))
            if score <= 0:
                score = len(re.findall(r"<DataPath>Объект\.([^.<>]+)</DataPath>", text))
            if score > 0:
                candidates.append((score, file_path))
        if not candidates:
            return []
        candidates.sort(key=lambda item: (-item[0], str(item[1]).casefold()))
        try:
            text = candidates[0][1].read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []
        parts = re.findall(r"<TitleDataPath>Объект\.([^.<>]+)\.RowsCount</TitleDataPath>", text)
        if not parts:
            parts = re.findall(r"<DataPath>Объект\.([^.<>]+)</DataPath>", text)
        ordered: list[str] = []
        seen: set[str] = set()
        for part in parts:
            name = str(part or "").strip()
            key = name.casefold()
            if not name or key in seen:
                continue
            seen.add(key)
            ordered.append(name)
        return ordered

    @staticmethod
    def _document_tabular_source_tables(manifest: dict[str, Any], order: int) -> list[str]:
        prefix = rf"^_DOCUMENT{int(order)}_VT(\d+)$"
        matches: list[tuple[int, str]] = []
        for item in list(manifest.get("tables") or []):
            if not isinstance(item, dict):
                continue
            source_table = str(item.get("source_table") or "").strip()
            if not source_table:
                continue
            m = re.match(prefix, source_table, re.IGNORECASE)
            if not m:
                continue
            matches.append((int(m.group(1) or 0), source_table))
        matches.sort(key=lambda item: item[0])
        return [source_table for _suffix, source_table in matches]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def handle_select(
        self, table_name: str, where: dict | None = None,
        order_by: str | None = None, *, limit: int | None = None,
        offset: int = 0,
    ) -> tuple[bool, list[dict[str, Any]]]:
        table = str(table_name or "").strip()
        if not self.enabled or not self._is_supported_table(table):
            return False, []

        # The client list view requests a bounded first page.  Keep the bound
        # at the source-table read; materializing every migrated 1C row here
        # was the main reason an empty-looking list took tens of seconds.
        source_limit = None
        if limit is not None and not where and not order_by and not self._is_physical_table(table):
            source_limit = max(1, int(limit)) + max(0, int(offset))
        rows = self._select_virtual_rows(table, limit=source_limit)
        if self._is_physical_table(table):
            rows = self._merge_rows(rows, self._load_physical_rows(table))
        rows = self._apply_where(rows, where)
        rows = self._apply_order(rows, order_by)
        if limit is not None:
            rows = rows[max(0, int(offset)): max(0, int(offset)) + max(1, int(limit))]
        return True, rows

    def handle_insert(self, table_name: str, row: dict[str, Any]) -> tuple[bool, int]:
        table = str(table_name or "").strip()
        if not self.enabled or not self._is_supported_table(table):
            return False, 0
        inserted = self._insert_overlay_row(table, dict(row or {}))
        return True, inserted

    def handle_update(self, table_name: str, where: dict[str, Any], values: dict[str, Any]) -> tuple[bool, int]:
        table = str(table_name or "").strip()
        if not self.enabled or not self._is_supported_table(table):
            return False, 0
        updated = self._update_overlay_rows(table, dict(where or {}), dict(values or {}))
        return True, updated

    def handle_delete(self, table_name: str, where: dict[str, Any]) -> tuple[bool, int]:
        table = str(table_name or "").strip()
        if not self.enabled or not self._is_supported_table(table):
            return False, 0
        deleted = self._delete_overlay_rows(table, dict(where or {}))
        return True, deleted

    # ------------------------------------------------------------------
    # Virtual rows
    # ------------------------------------------------------------------

    def _is_supported_table(self, table_name: str) -> bool:
        lower = str(table_name or "").strip().lower()
        return bool(lower == "data_constants" or self._logical_refs_for_table(lower))

    def _logical_refs_for_table(self, table_name: str) -> list[VirtualObjectRef]:
        lower = str(table_name or "").strip().lower()
        refs = list(self.object_refs_by_table.get(lower) or [])
        if refs:
            return refs
        if lower.startswith("data_tp_") and lower not in self.tabular_refs_by_table:
            self._bind_tabular_table(lower)
        return list(self.tabular_refs_by_table.get(lower) or [])

    def _ensure_storage_bindings(self) -> dict[str, dict[str, int]]:
        if self._storage_bindings is None:
            try:
                from src.infra.onec.storage_bindings import load_storage_bindings
                self._storage_bindings = load_storage_bindings(self.source_path)
            except Exception as exc:
                self._storage_bindings = {}
                self._binding_error = str(exc)
                logging.getLogger(__name__).warning("Legacy data bindings unavailable: %s", exc)
        return self._storage_bindings

    def _metadata_collection(self, uid: str, key: str) -> list[dict[str, Any]]:
        row = self._metadata_by_uuid.get(uid.casefold(), {})
        payload = row.get("payload") or {}
        value = payload.get(key)
        if not isinstance(value, list) and payload.get(key + "_ref"):
            raw = self._load_asset_bytes(str(payload[key + "_ref"]))
            if raw:
                value = json.loads(raw)
                # This private snapshot is not written back to the manifest.
                payload[key] = value
        return [item for item in (value or []) if isinstance(item, dict)] if isinstance(value, list) else []

    @staticmethod
    def _source_uuid(item: dict[str, Any]) -> str:
        imported = item.get("imported") or {}
        return str(imported.get("src_uuid") or imported.get("src_uid") or item.get("uuid") or "").casefold()

    def _part_for_source(self, source: str, uid: str) -> dict[str, Any]:
        match = re.search(r"_VT(\d+)$", source, re.IGNORECASE)
        if not match:
            return {}
        bindings = self._ensure_storage_bindings()
        parts = self._metadata_collection(uid, "tabular_parts")
        matches = [p for p in parts if bindings.get(self._source_uuid(p), {}).get("VT") == int(match[1])]
        return matches[0] if len(matches) == 1 else {}

    def _bind_tabular_table(self, table: str) -> None:
        # Resolve a named tabular part through its UUID/VT suffix. Numeric
        # table order is unrelated to the order of tabular parts in a form.
        for aggregate, refs in list(self.tabular_refs_by_table.items()):
            if not aggregate.startswith("data_document_") or not aggregate.endswith("_rows"):
                continue
            owner_alias = aggregate[len("data_document_"):-len("_rows")]
            for ref in refs:
                entry = self.manifest_tables_by_source.get(ref.source_table, {})
                uid = str(entry.get("metadata_uuid") or "").casefold()
                source_name = str(entry.get("logical_name") or "").casefold()
                if not any(table.startswith(f"data_tp_{alias}_") for alias in (owner_alias, source_name) if alias):
                    continue
                part = self._part_for_source(ref.source_table, uid)
                part_name = str(part.get("name") or "").casefold()
                if part_name and table in {f"data_tp_{alias}_{part_name}" for alias in (owner_alias, source_name)}:
                    self.tabular_refs_by_table[table] = [ref]
                    return

    def _aliases_for_source(self, ref: VirtualObjectRef) -> dict[str, list[tuple[str, str]]]:
        if ref.source_table in self._field_aliases:
            return self._field_aliases[ref.source_table]
        entry = self.manifest_tables_by_source.get(ref.source_table, {})
        uid = str(entry.get("metadata_uuid") or "").casefold()
        bindings = self._ensure_storage_bindings()
        if ref.kind == "tabular_part":
            part = self._part_for_source(ref.source_table, uid)
            fields = part.get("requisites") or part.get("columns") or part.get("attributes") or []
        else:
            fields = self._metadata_collection(uid, "requisites")
            fields += self._metadata_collection(uid, "dimensions")
            fields += self._metadata_collection(uid, "resources")
        by_suffix: dict[int, set[str]] = {}
        for item in fields:
            if not isinstance(item, dict):
                continue
            suffix = bindings.get(self._source_uuid(item), {}).get("Fld")
            name = str(item.get("name") or "").strip()
            if suffix is not None and name:
                by_suffix.setdefault(int(suffix), set()).add(name)
        aliases: dict[str, list[tuple[str, str]]] = {}
        for physical, stored in (entry.get("field_map") or {}).items():
            match = re.fullmatch(r"_FLD(\d+)_?(RREF|RRREF|N|T|S|L)?", str(physical), re.IGNORECASE)
            if not match:
                continue
            names = by_suffix.get(int(match[1]), set())
            if len(names) == 1:
                aliases.setdefault(next(iter(names)), []).append((str(stored), (match[2] or "").upper()))
        self._field_aliases[ref.source_table] = aliases
        return aliases

    def _add_semantic_fields(self, row: dict[str, Any], payload: dict[str, Any], ref: VirtualObjectRef) -> None:
        for name, columns in self._aliases_for_source(ref).items():
            # Multi-storage variants need a discriminator, never choose the
            # first nonempty column: inactive storage slots can contain values.
            if len(columns) != 1:
                continue
            stored, _suffix = columns[0]
            if stored not in payload:
                continue
            value = payload[stored]
            row.setdefault(name, self._ui_value_with_reference_resolution(value))
            if isinstance(value, dict):
                row.setdefault(f"_{name.casefold()}_raw", dict(value))
                guid = self._extract_ref_uuid(value)
                if guid and guid.replace("-", "").strip("0"):
                    row.setdefault(f"{name}_guid", guid)

    def import_status(self, table_name: str) -> dict[str, Any]:
        refs = self._logical_refs_for_table(table_name)
        if not refs:
            return {}
        entries = [self.manifest_tables_by_source.get(r.source_table, {}) for r in refs]
        return {
            "limited": bool(self._migration_limit),
            "limit_per_table": self._migration_limit,
            "imported_rows": sum(int(e.get("imported_rows") or 0) for e in entries),
            "source_rows": sum(int(e.get("source_rows") or 0) for e in entries),
            "binding_error": self._binding_error,
        }

    def _select_virtual_rows(self, table_name: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        lower = str(table_name or "").strip().lower()
        if lower == "data_constants":
            return self._select_constants_rows()
        refs = self._logical_refs_for_table(lower)
        if not refs:
            return []
        rows: list[dict[str, Any]] = []
        for ref in refs:
            remaining = None if limit is None else max(0, int(limit) - len(rows))
            rows.extend(self._load_source_rows(ref, limit=remaining))
            if limit is not None and len(rows) >= int(limit):
                break
        rows.sort(key=lambda row: int(row.get("rowid") or 0))
        return rows

    def _select_constants_rows(self) -> list[dict[str, Any]]:
        if self.constant_rows_loaded:
            return [dict(row) for row in self.constant_rows_cache]

        packed_rows = self._load_all_packed_rows()
        first_by_source: dict[str, dict[str, Any]] = {}
        for packed_row in packed_rows:
            source_table = str(packed_row.get("__source_table") or "").strip()
            if not source_table or not source_table.upper().startswith("_CONST"):
                continue
            first_by_source.setdefault(source_table, dict(packed_row))

        rows: list[dict[str, Any]] = []
        for ref in self.constant_refs:
            packed_row = first_by_source.get(str(ref.source_table or "").strip())
            if not packed_row:
                continue
            row = self._materialize_source_row(ref, dict(packed_row))
            if row:
                rows.append(row)
        rows.sort(key=lambda row: str(row.get("key") or "").casefold())
        self.constant_rows_cache = [dict(row) for row in rows]
        self.constant_rows_loaded = True
        return rows

    def _load_source_rows(self, ref: VirtualObjectRef, *, limit: int | None = None) -> list[dict[str, Any]]:
        source_key = str(ref.source_table or "").strip()
        if not source_key:
            return []
        cached = self.source_rows_cache.get(source_key)
        if cached is not None:
            return [dict(row) for row in (cached if limit is None else cached[:limit])]

        if not self.packed_table:
            self.source_rows_cache[source_key] = []
            return []

        packed_rows: list[dict[str, Any]] = []
        # The importer appends packed rows in manifest order and records the
        # imported count for every source table.  Point reads use the primary
        # rowid index and remain fast even when the requested source table is
        # near the end of a large migration.
        rowid_range = self.source_rowid_ranges.get(source_key)
        if rowid_range:
            first_rowid, last_rowid = rowid_range
            target = None if limit is None else max(0, int(limit))
            try:
                packed_table = self.db.table(self.packed_table)
                range_reader = getattr(packed_table, "select_rowid_range", None)
                if callable(range_reader):
                    candidate_rows = range_reader(
                        int(first_rowid), int(last_rowid), limit=target
                    ) or []
                else:
                    candidate_rows = []
                    for rowid in range(int(first_rowid), int(last_rowid) + 1):
                        found = packed_table.select(where={"rowid": rowid}, limit=1) or []
                        if found:
                            candidate_rows.append(found[0])
                        if target is not None and len(candidate_rows) >= target:
                            break
                for candidate in candidate_rows:
                    row = dict(candidate)
                    if str(row.get("__source_table") or "").strip() != source_key:
                        continue
                    packed_rows.append(row)
                    if target is not None and len(packed_rows) >= target:
                        break
            except Exception as exc:
                raise RuntimeError(f"Cannot read imported table {source_key}") from exc
        else:
            try:
                packed_rows = self.db.table(self.packed_table).select(
                    where={"__source_table": source_key}, limit=limit
                ) or []
            except Exception as exc:
                raise RuntimeError(f"Cannot read imported table {source_key}") from exc

        materialized: list[dict[str, Any]] = []
        for packed_row in packed_rows:
            row = self._materialize_source_row(ref, dict(packed_row or {}))
            if row:
                materialized.append(row)
        materialized.sort(key=lambda row: int(row.get("rowid") or 0))
        # A first-page request must not poison later pages or point lookups.
        if limit is None or len(packed_rows) < limit:
            self.source_rows_cache[source_key] = [dict(row) for row in materialized]
        return [dict(row) for row in materialized]

    def _load_asset_bytes(self, asset_key: str) -> bytes:
        asset_key = str(asset_key or "").strip()
        if not asset_key:
            return b""
        cached = self.asset_cache.get(asset_key)
        if cached is not None:
            return cached
        try:
            data, _mime = self.db.get_asset(asset_key)
        except Exception as exc:
            raise RuntimeError(f"Cannot read imported data asset {asset_key}") from exc
        self.asset_cache[asset_key] = bytes(data or b"")
        return self.asset_cache[asset_key]

    def _load_all_packed_rows(self) -> list[dict[str, Any]]:
        if self.packed_rows_loaded:
            return [dict(row) for row in self.packed_rows_cache]
        if not self.packed_table:
            self.packed_rows_loaded = True
            self.packed_rows_cache = []
            return []
        try:
            rows = self.db.table(self.packed_table).select() or []
        except Exception:
            rows = []
        materialized = [dict(row) for row in rows if isinstance(row, dict)]
        self.packed_rows_cache = [dict(row) for row in materialized]
        self.packed_rows_loaded = True
        return [dict(row) for row in materialized]

    @staticmethod
    def _row_payload(packed_row: dict[str, Any]) -> dict[str, Any]:
        data = packed_row.get("data")
        if isinstance(data, dict) and data:
            return dict(data)
        asset_key = str(packed_row.get("data_asset") or "").strip()
        if not asset_key:
            return {}
        offset = int(packed_row.get("data_offset") or 0)
        size = int(packed_row.get("data_size") or 0)
        raw = packed_row.get("_asset_bytes")
        if (not isinstance(raw, (bytes, bytearray)) or size <= 0
                or offset < 0 or offset + size > len(raw)):
            raise RuntimeError(f"Invalid imported row range in {asset_key}")
        chunk = bytes(raw[offset: offset + size])
        try:
            result = json.loads(chunk.decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise RuntimeError(f"Invalid imported row payload in {asset_key}") from exc
        if not isinstance(result, dict):
            raise RuntimeError(f"Imported row in {asset_key} must be an object")
        return result

    def _materialize_source_row(self, ref: VirtualObjectRef, packed_row: dict[str, Any]) -> dict[str, Any]:
        asset_key = str(packed_row.get("data_asset") or "").strip()
        if asset_key:
            packed_row["_asset_bytes"] = self._load_asset_bytes(asset_key)
        payload = self._row_payload(packed_row)
        if not isinstance(payload, dict):
            payload = {}
        row: dict[str, Any] = {}
        for key, value in payload.items():
            row[str(key)] = self._ui_value_with_reference_resolution(value)
            if isinstance(value, dict):
                row[f"_{str(key).lower()}_raw"] = dict(value)
        self._add_semantic_fields(row, payload, ref)
        row["__source_table"] = str(packed_row.get("__source_table") or ref.source_table or "")
        row["__source_row_index"] = int(packed_row.get("__source_row_index") or 0)
        row["__deleted__"] = bool(packed_row.get("__deleted__") or payload.get("marked") or False)
        row["rowid"] = self._stable_rowid(row["__source_table"], row["__source_row_index"])

        if ref.kind == "catalog":
            self._decorate_catalog_row(row, payload)
        elif ref.kind == "document":
            self._decorate_document_row(row, payload)
        elif ref.kind == "register":
            self._decorate_register_row(row, payload)
        elif ref.kind == "tabular_part":
            self._decorate_tabular_part_row(row, payload, ref)
        elif ref.kind == "constant":
            self._decorate_constant_row(row, payload, ref.name)

        return row

    @staticmethod
    def _stable_rowid(source_table: str, source_row_index: int) -> int:
        raw = hashlib.sha1(str(source_table or "").encode("utf-8", errors="ignore")).digest()
        prefix = int.from_bytes(raw[:6], "big")
        return (prefix << 20) | max(0, int(source_row_index or 0))

    def _reference_presentations(self) -> dict[str, str]:
        """Build a UUID -> presentation map from imported catalog/enum rows.

        Parse1CD normally provides resolved_name on reference values. Some
        configurations omit it for enum/reference variants, so Runtime keeps a
        deterministic fallback sourced from the imported target rows instead
        of showing a raw UUID to the user.
        """
        cached = self._reference_presentation_cache
        if cached is not None:
            return cached

        catalog_sources = {
            str(ref.source_table or "").strip()
            for refs in self.object_refs_by_table.values()
            for ref in refs
            if ref.kind == "catalog" and str(ref.source_table or "").strip()
        }
        presentations: dict[str, str] = {}
        if catalog_sources:
            try:
                packed_rows = self._load_all_packed_rows()
            except Exception:
                packed_rows = []
            for packed_row in packed_rows:
                source_table = str(packed_row.get("__source_table") or "").strip()
                if source_table not in catalog_sources:
                    continue
                try:
                    payload = self._row_payload(dict(packed_row))
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                uid = self._extract_ref_uuid(payload.get("idrref")).strip()
                if not uid or not uid.replace("-", "").strip("0"):
                    continue
                display = ""
                for key in ("description", "name", "title", "code"):
                    candidate = self._ui_value(payload.get(key))
                    if candidate not in (None, ""):
                        display = str(candidate)
                        break
                if display:
                    presentations.setdefault(uid.casefold(), display)

        self._reference_presentation_cache = presentations
        return presentations

    def _ui_value_with_reference_resolution(self, value: Any) -> Any:
        shown = self._ui_value(value)
        if not isinstance(value, dict):
            return shown
        uid = self._extract_ref_uuid(value).strip()
        if not uid or not uid.replace("-", "").strip("0"):
            return shown
        raw_candidates = {
            str(value.get("uuid") or ""),
            str(value.get("uuid_1c") or ""),
            str(value.get("raw_hex") or ""),
            "",
        }
        if str(shown or "") not in raw_candidates:
            return shown
        return self._reference_presentations().get(uid.casefold(), shown)

    @staticmethod
    def _ui_value(value: Any) -> Any:
        if isinstance(value, dict):
            uid = str(value.get("uuid") or value.get("uuid_1c") or "")
            if uid and not uid.replace("-", "").strip("0"):
                return ""
            for key in ("resolved_name", "name", "title", "uuid", "uuid_1c", "raw_hex"):
                candidate = value.get(key)
                if candidate not in (None, ""):
                    return candidate
            try:
                return json.dumps(value, ensure_ascii=False, default=str)
            except Exception:
                return str(value)
        if isinstance(value, list):
            try:
                return json.dumps(value, ensure_ascii=False, default=str)
            except Exception:
                return str(value)
        return value

    @staticmethod
    def _extract_ref_uuid(value: Any) -> str:
        if isinstance(value, dict):
            for key in ("uuid", "uuid_1c", "raw_hex"):
                candidate = str(value.get(key) or "").strip()
                if candidate:
                    return candidate
        return str(value or "").strip()

    def _decorate_catalog_row(self, row: dict[str, Any], payload: dict[str, Any]) -> None:
        ref_value = payload.get("idrref")
        guid = self._extract_ref_uuid(ref_value)
        if guid:
            row.setdefault("_guid", guid)
        code = row.get("code")
        desc = row.get("description")
        if code is not None:
            row.setdefault("_code", code)
        if desc is not None:
            row.setdefault("name", desc)
            row.setdefault("_description", desc)
        elif row.get("name") is not None:
            row.setdefault("_description", row.get("name"))
        parent = payload.get("parentidrref")
        if parent is not None:
            row.setdefault("_parent_guid", self._extract_ref_uuid(parent) or None)
        if "folder" in payload:
            row.setdefault("_is_folder", bool(payload.get("folder")))
        if "predefinedid" in payload:
            row.setdefault("_predefined", bool(str(payload.get("predefinedid") or "").strip() and str(payload.get("predefinedid")).strip("0")))
        row.setdefault("data", {k: v for k, v in payload.items() if k not in {"idrref", "code", "description", "marked", "folder", "parentidrref", "predefinedid"}})

    def _decorate_document_row(self, row: dict[str, Any], payload: dict[str, Any]) -> None:
        ref_value = payload.get("idrref")
        guid = self._extract_ref_uuid(ref_value)
        if guid:
            row.setdefault("_guid", guid)
        if "marked" in payload:
            row.setdefault("_deleted", bool(payload.get("marked")))
        if "posted" in payload:
            row.setdefault("_posted", bool(payload.get("posted")))
        if "date_time" in payload:
            row.setdefault("_date", payload.get("date_time"))
        elif "date" in payload:
            row.setdefault("_date", payload.get("date"))
        if "number" in payload:
            row.setdefault("_number", payload.get("number"))
        if "numberprefix" in payload:
            row.setdefault("_number_prefix", payload.get("numberprefix"))
        row.setdefault("data", {k: v for k, v in payload.items() if k not in {"idrref", "marked", "posted", "date_time", "date", "number", "numberprefix"}})

    def _decorate_register_row(self, row: dict[str, Any], payload: dict[str, Any]) -> None:
        regid = str(payload.get("regid") or "").strip()
        if regid:
            row.setdefault("_guid", regid)
            row.setdefault("_rec_guid", regid)
        if "period" in payload:
            row.setdefault("_period", payload.get("period"))
        if "actualperiod" in payload:
            row.setdefault("_active", bool(payload.get("actualperiod")))
        elif "active" in payload:
            row.setdefault("_active", bool(payload.get("active")))
        if "recordkind" in payload:
            row.setdefault("_record_kind", payload.get("recordkind"))

    def _decorate_tabular_part_row(self, row: dict[str, Any], payload: dict[str, Any], ref: VirtualObjectRef) -> None:
        source_table = str(ref.source_table or "").strip()
        row.setdefault("_deleted", bool(payload.get("marked") or payload.get("_deleted") or False))

        field_map = dict(self.manifest_tables_by_source.get(source_table, {}).get("field_map") or {})
        slot_map = dict(self.physical_slot_map_by_source.get(source_table, {}))

        owner_payload_key = ""
        owner_slot = slot_map.get("owner_ref") or {}
        owner_source_field = str(owner_slot.get("source_field") or "").strip()
        if owner_source_field:
            owner_payload_key = str(field_map.get(owner_source_field) or "").strip()
        if not owner_payload_key:
            for key in payload:
                if str(key or "").lower().endswith("idrref") or "owner" in str(key or "").lower():
                    owner_payload_key = str(key)
                    break
        if owner_payload_key:
            owner_value = payload.get(owner_payload_key)
            owner_guid = self._extract_ref_uuid(owner_value)
            if owner_guid:
                row.setdefault("_doc_guid", owner_guid)
                row["_owner_guid"] = owner_guid

        line_payload_key = ""
        line_slot = slot_map.get("line_no") or {}
        line_source_field = str(line_slot.get("source_field") or "").strip()
        if line_source_field:
            line_payload_key = str(field_map.get(line_source_field) or "").strip()
        if not line_payload_key:
            for key in payload:
                lower = str(key or "").lower()
                if lower.startswith("lineno") or lower.endswith("line_no"):
                    line_payload_key = str(key)
                    break
        if line_payload_key:
            try:
                row.setdefault("_line_no", int(payload.get(line_payload_key) or 0))
            except Exception:
                pass

        if "_row_guid" not in row:
            digest = hashlib.sha1(f"{source_table}:{row.get('__source_row_index') or 0}".encode("utf-8", errors="ignore")).hexdigest()
            row["_row_guid"] = digest[:32]

    def _decorate_constant_row(self, row: dict[str, Any], payload: dict[str, Any], const_name: str) -> None:
        key = str(const_name or "").strip()
        if key:
            row.setdefault("key", key)
            row.setdefault("_guid", key)
        value = self._constant_value_from_row(payload)
        row.setdefault("value", value)

    @staticmethod
    def _constant_value_from_row(payload: dict[str, Any]) -> Any:
        items = [(k, v) for k, v in payload.items() if str(k or "").lower() != "recordkey"]
        if not items:
            return None
        if len(items) == 1:
            return VirtualOneCDataTables._ui_value(items[0][1])
        return {str(k): VirtualOneCDataTables._ui_value(v) for k, v in items}

    # ------------------------------------------------------------------
    # Physical overlay support
    # ------------------------------------------------------------------

    def _load_physical_rows(self, table_name: str) -> list[dict[str, Any]]:
        lower = str(table_name or "").strip().lower()
        cached = self.physical_rows_cache.get(lower)
        if cached is not None:
            return [dict(row) for row in cached]
        try:
            rows = self.db.table(table_name).select() or []
            loaded = True
        except Exception:
            rows = []
            loaded = False
        materialized = [dict(row) for row in rows if isinstance(row, dict)]
        if loaded:
            self.physical_rows_cache[lower] = [dict(row) for row in materialized]
        return [dict(row) for row in materialized]

    def _merge_rows(self, virtual_rows: list[dict[str, Any]], physical_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: dict[tuple[str, str], dict[str, Any]] = {}
        order: list[tuple[str, str]] = []
        for row in virtual_rows:
            ident = self._row_identity(row)
            if ident not in merged:
                order.append(ident)
            merged[ident] = dict(row)
        for row in physical_rows:
            ident = self._row_identity(row)
            if ident not in merged:
                order.append(ident)
            merged[ident] = dict(row)
        return [merged[ident] for ident in order]

    @staticmethod
    def _row_identity(row: dict[str, Any]) -> tuple[str, str]:
        key = str(row.get("key") or "").strip()
        if key:
            return ("key", key)
        guid = str(row.get("_guid") or row.get("_rec_guid") or "").strip()
        if guid:
            return ("guid", guid)
        rowid = row.get("rowid")
        return ("rowid", str(rowid) if rowid is not None else "")

    @staticmethod
    def _apply_where(rows: list[dict[str, Any]], where: dict | None) -> list[dict[str, Any]]:
        if not where:
            return rows
        out: list[dict[str, Any]] = []
        for row in rows:
            if all(VirtualOneCDataTables._value_matches(row.get(str(key)), value) for key, value in where.items()):
                out.append(row)
        return out

    @staticmethod
    def _value_matches(actual: Any, expected: Any) -> bool:
        if actual == expected:
            return True
        if actual is None or expected is None:
            return actual is expected
        return str(actual) == str(expected)

    @staticmethod
    def _apply_order(rows: list[dict[str, Any]], order_by: str | None) -> list[dict[str, Any]]:
        if not order_by:
            return rows
        key = str(order_by or "").strip()
        reverse = False
        if key.startswith("-"):
            reverse = True
            key = key[1:]
        if not key:
            return rows
        return sorted(rows, key=lambda row: VirtualOneCDataTables._sort_key(row.get(key)), reverse=reverse)

    @staticmethod
    def _sort_key(value: Any) -> tuple[int, Any]:
        if value is None:
            return (1, "")
        if isinstance(value, bool):
            return (0, int(value))
        if isinstance(value, (int, float)):
            return (0, value)
        return (0, str(value))

    def _overlay_table_schema(self, table_name: str, sample_row: dict[str, Any]) -> dict[str, Any]:
        lower = str(table_name or "").strip().lower()
        # Lazy-init cache in case dataclass field init failed
        if not hasattr(self, "_overlay_schema_cache") or self._overlay_schema_cache is None:
            self._overlay_schema_cache = {}
        cached = self._overlay_schema_cache.get(lower)
        if cached is not None:
            return cached
        if lower == "data_constants":
            schema = {
                "fields": {
                    "key": {"type": "str", "unique": True, "indexed": True},
                    "value": {"type": "json"},
                }
            }
            self._overlay_schema_cache[lower] = schema
            return schema

        fields: dict[str, dict[str, Any]] = {}
        for key, value in sample_row.items():
            field = str(key or "").strip()
            if not field or field.startswith("__") or field == "rowid":
                continue
            schema_item: dict[str, Any] = {"type": self._infer_field_type(value)}
            if field in {"_guid", "_rec_guid", "key"}:
                schema_item["unique"] = True
                schema_item["indexed"] = True
            fields[field] = schema_item
        if "_deleted" not in fields:
            fields["_deleted"] = {"type": "bool", "indexed": True}
        schema = {"fields": fields}
        self._overlay_schema_cache[lower] = schema
        return schema

    @staticmethod
    def _infer_field_type(value: Any) -> str:
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int) and not isinstance(value, bool):
            return "int"
        if isinstance(value, float):
            return "float"
        if isinstance(value, (dict, list, tuple)):
            return "json"
        if value is None:
            return "json"
        return "str"

    def _ensure_overlay_table(self, table_name: str, sample_row: dict[str, Any]) -> None:
        if self._is_physical_table(table_name):
            return
        schema = self._overlay_table_schema(table_name, sample_row)
        try:
            self.db.create_table(table_name, schema, external_schema=True)
        except Exception as exc:
            if "exists" not in str(exc).lower():
                raise
        self.physical_rows_cache.pop(str(table_name or "").strip().lower(), None)

    def _insert_overlay_row(self, table_name: str, row: dict[str, Any]) -> int:
        self._ensure_overlay_table(table_name, row)
        try:
            return int(self.db.table(table_name).insert(row) or 0)
        finally:
            self.physical_rows_cache.pop(str(table_name or "").strip().lower(), None)

    def _update_overlay_rows(self, table_name: str, where: dict[str, Any], values: dict[str, Any]) -> int:
        physical_exists = self._is_physical_table(table_name)
        if physical_exists:
            try:
                updated = int(self.db.table(table_name).update(where, values) or 0)
                if updated:
                    self.physical_rows_cache.pop(str(table_name or "").strip().lower(), None)
                    return updated
            except Exception:
                pass

        matches = self._apply_where(self._select_virtual_rows(table_name), where)
        if not matches:
            return 0
        updated = 0
        for row in matches:
            merged = dict(row)
            merged.update(values)
            self._ensure_overlay_table(table_name, merged)
            try:
                self.db.table(table_name).insert(merged)
                updated += 1
            except Exception:
                continue
        if updated:
            self.physical_rows_cache.pop(str(table_name or "").strip().lower(), None)
        return updated

    def _delete_overlay_rows(self, table_name: str, where: dict[str, Any]) -> int:
        physical_exists = self._is_physical_table(table_name)
        if physical_exists:
            try:
                deleted = int(self.db.table(table_name).delete(where) or 0)
                if deleted:
                    self.physical_rows_cache.pop(str(table_name or "").strip().lower(), None)
                    return deleted
            except Exception:
                pass

        matches = self._apply_where(self._select_virtual_rows(table_name), where)
        if not matches:
            return 0
        deleted = 0
        for row in matches:
            tombstone = dict(row)
            tombstone["_deleted"] = True
            self._ensure_overlay_table(table_name, tombstone)
            try:
                self.db.table(table_name).insert(tombstone)
                deleted += 1
            except Exception:
                continue
        if deleted:
            self.physical_rows_cache.pop(str(table_name or "").strip().lower(), None)
        return deleted


_ADAPTERS: dict[int, VirtualOneCDataTables] = {}


def invalidate_native_rows(db: Mpdb) -> None:
    """Drop only native-row projections after a direct transactional write."""
    adapter = _ADAPTERS.get(id(db))
    cache = getattr(adapter, "physical_rows_cache", None)
    if isinstance(cache, dict):
        cache.clear()


def get_virtual_data_tables(db: Mpdb) -> VirtualOneCDataTables:
    """Return (or create) the VirtualOneCDataTables adapter for *db*.

    The adapter is keyed by ``id(db)``.  If the cached instance is missing
    ``_overlay_schema_cache`` (created before the fix) it is discarded so a
    fresh one is built.
    """
    key = id(db)
    adapter = _ADAPTERS.get(key)
    migration_asset_present = False
    if adapter is not None and not getattr(adapter, "enabled", False):
        # An import can replace the migration asset while the Runtime keeps
        # the same opened DB object. Rebuild the adapter on the next query so
        # the first client refresh sees newly imported business rows.
        try:
            db.get_asset(ONECD_DATA_MIGRATION_ASSET_KEY)
            migration_asset_present = True
        except Exception:
            pass
    if (
        adapter is None
        or not hasattr(adapter, "_overlay_schema_cache")
        or migration_asset_present
    ):
        adapter = VirtualOneCDataTables(db)
        _ADAPTERS[key] = adapter
    return adapter
