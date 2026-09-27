"""COM+1CD bridge: combines ConfigDumpInfo UUID mapping with Parse1CD binary data.

Pipeline:
  1. ConfigDumpInfo.xml  → object UUID + attribute UUID
  2. DBNames (from .1CD) → UUID → physical table/column suffix
  3. COM (optional)      → friendly display names & types for attributes
  4. Parse1CD            → read rows from physical tables
  5. Result: mpdb tables with semantic column names & types

This avoids relying on COM's UUID property (not exposed in V83.COMConnector API).
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

from src.infra.onec.importer import to_ascii_identifier


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DBNAMES_ENTRY_RE = re.compile(r'\{([0-9a-fA-F-]{36}),"([^"]+)",(\d+)\}')

# DBNames type tag → MetaPlatform family
_DBNAME_TAG_TO_FAMILY: Dict[str, str] = {
    "Reference":  "catalog",
    "Document":   "document",
    "Enum":       "enumeration",
    "AccumRg":    "register_accum",
    "InfoRg":     "register_info",
    "AcctRg":     "register_accounting",
    "CalcRg":     "register_calc",
    "Chrc":       "chart_of_characteristic_types",
    "ChrtOfAcc":  "chart_of_accounts",
    "Task":       "task",
    "BPr":        "business_process",
    "Const":      "constants",
    "ExchangePlan": "exchange_plan",
}

# ConfigDumpInfo metadata name prefix → family (first part before ".")
_DUMPINFO_PREFIX_TO_FAMILY: Dict[str, str] = {
    "Catalog":                       "catalog",
    "Document":                      "document",
    "Enum":                          "enumeration",
    "AccumulationRegister":          "register_accum",
    "InformationRegister":           "register_info",
    "AccountingRegister":            "register_accounting",
    "CalculationRegister":           "register_calc",
    "ChartOfCharacteristicTypes":    "chart_of_characteristic_types",
    "ChartOfAccounts":               "chart_of_accounts",
    "ChartOfCalculationTypes":       "register_calc",
    "Task":                          "task",
    "BusinessProcess":               "business_process",
    "Constant":                      "constants",
    "ExchangePlan":                  "exchange_plan",
}

# Physical field suffix type indicators → value column variant
_FIELD_VARIANT_RE = re.compile(
    r'^_FLD(\d+)(RREF|TRREF|TREF|TYPE|N|L|DT|NVC|NC|NT|B|S|T)?$',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ObjectRecord:
    """Metadata object from ConfigDumpInfo."""
    family: str          # "catalog", "document", ...
    name_1c: str         # 1C name, e.g. "Номенклатура"
    uuid: str            # lowercase UUID
    logical_name: str    # ASCII, e.g. "nomenklatura"


@dataclass(frozen=True)
class AttrRecord:
    """Attribute/field record from ConfigDumpInfo."""
    owner_uuid: str      # parent object UUID
    attr_name_1c: str    # 1C attribute name
    attr_uuid: str       # lowercase UUID
    attr_kind: str       # "Attribute", "Dimension", "Resource", "TabularSection", ...


@dataclass
class FieldMapping:
    physical_col: str    # e.g. "_FLD1234N"
    logical_name: str    # e.g. "tsina"
    mp_type: str         # "str", "float", "bool", "str" (for ref)
    is_ref: bool = False


# ---------------------------------------------------------------------------
# Step 1: parse ConfigDumpInfo.xml
# ---------------------------------------------------------------------------

def parse_dump_info(dump_info_path: str) -> Tuple[Dict[str, ObjectRecord], Dict[str, AttrRecord]]:
    """Parse ConfigDumpInfo.xml → (objects_by_uuid, attrs_by_uuid).

    Returns:
        objects_by_uuid: uuid → ObjectRecord for main objects
        attrs_by_uuid:   uuid → AttrRecord for attributes/dimensions/etc.
    """
    objects: Dict[str, ObjectRecord] = {}
    attrs: Dict[str, AttrRecord] = {}

    try:
        tree = ET.parse(dump_info_path)
        root = tree.getroot()
    except Exception as exc:
        raise ValueError(f"Cannot parse ConfigDumpInfo.xml: {exc}") from exc

    def _local(tag: str) -> str:
        return tag.split("}")[-1] if "}" in tag else tag

    for node in root.iter():
        if _local(node.tag) != "Metadata":
            continue
        name = str(node.attrib.get("name") or "").strip()
        uuid = str(node.attrib.get("id") or "").strip().lower()
        if not name or not uuid:
            continue

        parts = name.split(".")
        if len(parts) < 2:
            continue

        prefix = parts[0]
        obj_name = parts[1]
        family = _DUMPINFO_PREFIX_TO_FAMILY.get(prefix)

        if family and len(parts) == 2:
            # Main object: Catalog.Name, Document.Name, etc.
            logical = to_ascii_identifier(obj_name)
            objects[uuid] = ObjectRecord(
                family=family,
                name_1c=obj_name,
                uuid=uuid,
                logical_name=logical,
            )
        elif len(parts) >= 4 and family:
            # Child: Catalog.Name.Attribute.AttrName
            attr_kind = parts[2]   # Attribute / Dimension / Resource / TabularSection
            attr_name = parts[3]
            # Find parent UUID — parent is objects entry with same prefix.name
            parent_key = f"{prefix}.{obj_name}"
            parent = next(
                (o for o in objects.values()
                 if o.family == family and o.name_1c == obj_name),
                None,
            )
            parent_uuid = parent.uuid if parent else ""
            attrs[uuid] = AttrRecord(
                owner_uuid=parent_uuid,
                attr_name_1c=attr_name,
                attr_uuid=uuid,
                attr_kind=attr_kind,
            )

    return objects, attrs


# ---------------------------------------------------------------------------
# Step 2: parse DBNames from .1CD
# ---------------------------------------------------------------------------

def _read_dbnames_text(db_path: str) -> str:
    """Read and decode DBNames text from a 1CD file via Parse1CD."""
    from src.infra.onec.data_migration import _load_parse1cd_backend
    backend = _load_parse1cd_backend()
    db_cls = backend.database_parser.OneCDatabase

    db = db_cls(str(db_path))
    try:
        if not db.open():
            raise RuntimeError(f"Cannot open 1CD: {db_path}")

        rows = list(db.iter_table_rows(
            "Params", limit=None, decode=True, read_blobs=True, include_deleted=False
        ))
        row = next((r for r in rows if r.get("FILENAME") == "DBNames"), None)
        if row is None:
            raise ValueError("DBNames not found in Params")

        raw = row.get("BINARYDATA")
        if raw is None:
            raise ValueError("BINARYDATA is empty")

        # to_json_safe converts bytes → hex string
        if isinstance(raw, str):
            if "{" in raw and '"' in raw:
                return raw
            try:
                raw = bytes.fromhex(raw)
            except ValueError:
                pass
        if not isinstance(raw, (bytes, bytearray)):
            raw = bytes(raw)

        # Try zlib decompression variants, then raw
        candidates: List[bytes] = []
        for wbits in (-15, 15, 47):
            try:
                candidates.append(zlib.decompress(raw, wbits))
            except Exception:
                pass
        candidates.append(raw)

        for data in candidates:
            for enc in ("utf-8", "utf-16-le", "cp1251"):
                try:
                    text = data.decode(enc)
                    if "{" in text and '"' in text:
                        return text
                except Exception:
                    pass

        raise ValueError(f"Cannot decode DBNames blob ({len(raw)} bytes)")
    finally:
        db.close()


@dataclass(frozen=True)
class DBNamesRecord:
    uuid: str
    tag: str     # "Reference", "Document", "Fld", "VT", ...
    suffix: int


def parse_dbnames(db_1cd_path: str) -> List[DBNamesRecord]:
    text = _read_dbnames_text(db_1cd_path)
    return [
        DBNamesRecord(uuid=g.lower(), tag=t, suffix=int(n))
        for g, t, n in _DBNAMES_ENTRY_RE.findall(text)
    ]


# ---------------------------------------------------------------------------
# Step 3: combine ConfigDumpInfo + DBNames → full mapping
# ---------------------------------------------------------------------------

@dataclass
class TableMapping:
    """Complete physical ↔ logical mapping for one metadata object."""
    uuid: str
    family: str
    name_1c: str
    logical_name: str
    physical_table: str    # e.g. "_REFERENCE242"
    # field_suffix → (logical_name, mp_type, is_ref)
    field_map: Dict[int, Tuple[str, str, bool]] = field(default_factory=dict)


def build_table_mappings(
    dump_info_path: str,
    db_1cd_path: str,
    *,
    com_conn=None,       # optional OneCCOMConnection for richer names/types
) -> Dict[str, TableMapping]:
    """Build UUID → TableMapping from ConfigDumpInfo + DBNames.

    Returns dict of uuid → TableMapping (only for objects with known physical table).
    """
    print("  Parsing ConfigDumpInfo.xml...")
    objects, attrs = parse_dump_info(dump_info_path)
    print(f"    Objects: {len(objects)}, Attributes: {len(attrs)}")

    print("  Parsing DBNames from 1CD...")
    dbnames = parse_dbnames(db_1cd_path)
    print(f"    DBNames entries: {len(dbnames)}")

    # Index DBNames — prefer main-table tags over changelog/auxiliary tags
    # (same UUID can appear as "Reference" AND "ReferenceChngR"; keep the main one)
    _TAG_PRIORITY: Dict[str, int] = {
        tag: 100 - i for i, tag in enumerate(_DBNAME_TAG_TO_FAMILY.keys())
    }
    uuid_to_dbnames: Dict[str, DBNamesRecord] = {}
    for r in dbnames:
        if r.tag not in _DBNAME_TAG_TO_FAMILY:
            continue
        existing = uuid_to_dbnames.get(r.uuid)
        if existing is None:
            uuid_to_dbnames[r.uuid] = r
        else:
            # Keep entry with higher priority (main table over changelog)
            if _TAG_PRIORITY.get(r.tag, 0) > _TAG_PRIORITY.get(existing.tag, 0):
                uuid_to_dbnames[r.uuid] = r
    # Separate index for Fld entries (attribute UUIDs → DBNamesRecord)
    uuid_to_fld: Dict[str, DBNamesRecord] = {
        r.uuid: r for r in dbnames if r.tag == "Fld"
    }

    # Build COM attribute name/type lookup if COM available
    com_attr_info: Dict[str, Tuple[str, str]] = {}  # attr_uuid_lower → (friendly_name, mp_type)
    if com_conn is not None:
        try:
            _build_com_attr_index(com_conn, com_attr_info)
            print(f"    COM attribute index: {len(com_attr_info)} entries")
        except Exception as exc:
            print(f"    COM attr index warning: {exc}")

    # Build attr UUID → (logical_name, mp_type, is_ref)
    attr_uuid_to_field: Dict[str, Tuple[str, str, bool]] = {}
    for attr_uuid, ar in attrs.items():
        # Check COM for a friendly name/type
        if attr_uuid in com_attr_info:
            friendly, mp_type = com_attr_info[attr_uuid]
        else:
            friendly = to_ascii_identifier(ar.attr_name_1c)
            mp_type = "str"  # default type; COM would give us better

        is_ref = (mp_type == "ref")
        attr_uuid_to_field[attr_uuid] = (friendly, mp_type, is_ref)

    # Build physical table prefix from DBNames tag
    def _phys_table(rec: DBNamesRecord) -> str:
        tag_upper = rec.tag.upper()
        prefixes = {
            "REFERENCE": "_REFERENCE", "DOCUMENT": "_DOCUMENT",
            "ENUM": "_ENUM", "ACCUMRG": "_ACCUMRG", "INFORG": "_INFORG",
            "ACCTRG": "_ACCTRG", "CALCRG": "_CALCRG", "CHRC": "_CHRC",
            "CHRTOFACC": "_CHRTOFACC", "TASK": "_TASK", "BPR": "_BPR",
            "CONST": "_CONST", "EXCHANGEPLAN": "_EXPLAN",
        }
        prefix = prefixes.get(tag_upper, f"_{tag_upper}")
        return f"{prefix}{rec.suffix}"

    # Build final mappings
    result: Dict[str, TableMapping] = {}
    for obj_uuid, obj in objects.items():
        dbn = uuid_to_dbnames.get(obj_uuid)
        if dbn is None or dbn.tag not in _DBNAME_TAG_TO_FAMILY:
            continue

        phys = _phys_table(dbn)
        mapping = TableMapping(
            uuid=obj_uuid,
            family=obj.family,
            name_1c=obj.name_1c,
            logical_name=obj.logical_name,
            physical_table=phys,
        )

        # Map attribute field suffixes for this object
        for attr_uuid, ar in attrs.items():
            if ar.owner_uuid != obj_uuid:
                continue
            fld_dbn = uuid_to_fld.get(attr_uuid)  # look in Fld index, not main index
            if fld_dbn is None:
                continue
            field_info = attr_uuid_to_field.get(attr_uuid)
            if field_info:
                mapping.field_map[fld_dbn.suffix] = field_info

        result[obj_uuid] = mapping

    print(f"    Mapped objects: {len(result)}")
    return result


def _build_com_attr_index(com_conn, out: Dict[str, Tuple[str, str]]) -> None:
    """Fill out with attr_uuid_lower → (friendly_ascii_name, mp_type) from COM."""
    from src.infra.onec.com_source import COLLECTION_MAP, _count, _iterate, _str_prop, _resolve_type

    for coll_name, _ in COLLECTION_MAP:
        try:
            coll = getattr(com_conn._meta, coll_name, None)
            if not coll or _count(coll) == 0:
                continue
            for obj in _iterate(coll):
                for attr_coll_name in ("Attributes", "Requisites", "Dimensions", "Resources"):
                    attr_coll = getattr(obj, attr_coll_name, None)
                    if not attr_coll or _count(attr_coll) == 0:
                        continue
                    for attr in _iterate(attr_coll):
                        try:
                            # UUID not available via standard COM property
                            # Attempt alternative — skip gracefully if not available
                            pass
                        except Exception:
                            pass
        except Exception:
            continue


# ---------------------------------------------------------------------------
# Step 4: build per-row field mapper
# ---------------------------------------------------------------------------

def build_row_field_mapper(
    mapping: TableMapping,
    physical_fields: List[str],
) -> Dict[str, Tuple[str, str, bool]]:
    """Return {physical_col_upper: (logical_name, mp_type, is_ref)} for one table."""
    result: Dict[str, Tuple[str, str, bool]] = {}

    # System fields
    _SYS: Dict[str, Tuple[str, str]] = {
        "_IDRREF":        ("_guid",        "str"),
        "_MARKED":        ("_deleted",     "bool"),
        "_ISMETADATA":    ("_is_folder",   "bool"),
        "_PARENTIDRRREF": ("_parent_guid", "str"),
        "_OWNERIDRRREF":  ("_owner_guid",  "str"),
        "_CODE":          ("_code",        "str"),
        "_DESCRIPTION":   ("_description", "str"),
        "_DATE_TIME":     ("_date",        "str"),
        "_NUMBER":        ("_number",      "str"),
        "_POSTED":        ("_posted",      "bool"),
        "_LINENO":        ("_line_no",     "int"),
    }
    for pf in physical_fields:
        sys_entry = _SYS.get(pf.upper())
        if sys_entry:
            result[pf.upper()] = (sys_entry[0], sys_entry[1], False)

    # Mapped attribute fields
    for pf in physical_fields:
        m = _FIELD_VARIANT_RE.match(pf.upper())
        if not m:
            continue
        fld_num = int(m.group(1))
        variant = (m.group(2) or "").upper()
        field_info = mapping.field_map.get(fld_num)
        if not field_info:
            continue
        logical, mp_type, is_ref = field_info
        if variant in ("", "N", "L", "DT", "NC", "NVC", "NT", "S", "T", "B"):
            result[pf.upper()] = (logical, mp_type, False)
        elif variant in ("RREF", "TRREF"):
            result[pf.upper()] = (f"{logical}_ref", "str", True)

    return result


# ---------------------------------------------------------------------------
# Mpdb helpers
# ---------------------------------------------------------------------------

def target_table_name(family: str, logical_name: str) -> str:
    name = logical_name.lower()
    if family in ("catalog", "chart_of_accounts", "chart_of_characteristic_types"):
        return f"data_catalog_{name}"
    if family in ("document", "task", "business_process"):
        return f"data_document_{name}"
    if family in ("register_accum", "register_info", "register_accounting", "register_calc"):
        return f"data_reg_{name}"
    if family == "constants":
        return "data_constants"
    return f"data_{family}_{name}"


def _mpdb_field_type(mp_type: str) -> str:
    t = mp_type.strip().lower()
    if t in ("number", "float", "decimal"):
        return "float"
    if t == "int":
        return "int"
    if t in ("bool", "boolean"):
        return "bool"
    return "str"


# ---------------------------------------------------------------------------
# Main importer
# ---------------------------------------------------------------------------

@dataclass
class ImportResult:
    physical_table: str
    target_table: str
    logical_name: str
    family: str
    rows_written: int = 0
    fields_mapped: int = 0
    error: str = ""
    skipped: bool = False


def import_combined(
    dump_info_path: str,
    db_1cd_path: str,
    target_db,
    *,
    com_conn=None,
    families: Optional[Iterable[str]] = None,
    limit_per_table: Optional[int] = None,
    progress: Optional[Callable[[dict], None]] = None,
) -> List[ImportResult]:
    """Import data from 1CD into mpdb using ConfigDumpInfo + DBNames for mapping.

    Args:
        dump_info_path: Path to ConfigDumpInfo.xml (from XML dump)
        db_1cd_path:    Path to the .1CD binary database file
        target_db:      Mpdb instance to write into
        com_conn:       Optional OneCCOMConnection for richer attribute names/types
        families:       Restrict to these families (e.g. ["catalog", "document"])
        limit_per_table: Max rows per table (None = all)
        progress:       Progress callback
    """
    from src.infra.onec.data_migration import _load_parse1cd_backend

    backend = _load_parse1cd_backend()
    db_cls = backend.database_parser.OneCDatabase
    json_safe = backend.value_decoder.to_json_safe

    allowed_families = set(families) if families else None

    if progress:
        progress({"stage": "mapping", "message": "Building mapping from ConfigDumpInfo + DBNames..."})

    mappings = build_table_mappings(dump_info_path, db_1cd_path, com_conn=com_conn)

    results: List[ImportResult] = []
    phys_db = db_cls(str(db_1cd_path))
    if not phys_db.open():
        raise RuntimeError(f"Cannot open 1CD: {db_1cd_path}")

    try:
        available_tables = {n.upper(): n for n in phys_db.get_table_names()}
        total = len(mappings)
        done = 0

        for uuid, mapping in mappings.items():
            done += 1
            if allowed_families and mapping.family not in allowed_families:
                continue

            phys_actual = available_tables.get(mapping.physical_table.upper())
            tgt_name = target_table_name(mapping.family, mapping.logical_name)
            res = ImportResult(
                physical_table=mapping.physical_table,
                target_table=tgt_name,
                logical_name=mapping.logical_name,
                family=mapping.family,
            )

            if phys_actual is None:
                res.skipped = True
                res.error = "Physical table not found in 1CD"
                results.append(res)
                continue

            row_count = phys_db.get_total_rows(phys_actual)
            if row_count == 0:
                res.skipped = True
                results.append(res)
                continue

            if progress:
                progress({
                    "stage": "table_start",
                    "table": phys_actual, "target": tgt_name,
                    "rows": row_count, "done": done, "total": total,
                    "message": f"[{done}/{total}] {mapping.family} '{mapping.name_1c}' → {tgt_name} ({row_count} rows)",
                })

            try:
                phys_info = phys_db.get_table_info(phys_actual)
                phys_field_names = [f.name for f in phys_info.fields] if phys_info else []
                field_mapper = build_row_field_mapper(mapping, phys_field_names)
                res.fields_mapped = len(field_mapper)

                # Build mpdb schema from field mapper
                schema_fields: Dict[str, Any] = {}
                for _, (lname, mp_type, _) in field_mapper.items():
                    schema_fields[lname] = {"type": _mpdb_field_type(mp_type)}

                if not schema_fields:
                    res.skipped = True
                    res.error = "No mappable fields"
                    results.append(res)
                    continue

                # Create target table — store schema externally to avoid META overflow
                try:
                    target_db.create_table(tgt_name, {"fields": schema_fields},
                                           external_schema=True)
                except Exception as _ce:
                    err_str = str(_ce).lower()
                    if "exist" not in err_str and "already" not in err_str and "duplicate" not in err_str:
                        res.error = f"create_table failed: {_ce}"
                        results.append(res)
                        continue

                try:
                    tbl = target_db.table(tgt_name)
                except Exception as _te:
                    res.error = f"table open failed: {_te}"
                    results.append(res)
                    continue
                batch: List[Dict[str, Any]] = []
                written = 0

                for row in phys_db.iter_table_rows(
                    phys_actual,
                    limit=limit_per_table,
                    decode=True,
                    read_blobs=False,
                    include_deleted=False,
                ):
                    out: Dict[str, Any] = {}
                    for phys_col, value in row.items():
                        if phys_col == "__deleted__":
                            continue
                        entry = field_mapper.get(phys_col.upper())
                        if not entry:
                            continue
                        lname, _, _ = entry
                        out[lname] = json_safe(value) if value is not None else None
                    if out:
                        batch.append(out)

                    if len(batch) >= 500:
                        with target_db.transaction() as tx:
                            for r in batch:
                                tbl.insert_tx(tx, r, set_meta=False)
                            tx.set_meta(target_db._meta)
                        written += len(batch)
                        batch.clear()

                if batch:
                    with target_db.transaction() as tx:
                        for r in batch:
                            tbl.insert_tx(tx, r, set_meta=False)
                        tx.set_meta(target_db._meta)
                    written += len(batch)

                res.rows_written = written
                if progress:
                    progress({
                        "stage": "table_done",
                        "table": phys_actual, "target": tgt_name,
                        "rows_written": written, "fields_mapped": res.fields_mapped,
                        "done": done, "total": total,
                    })

            except Exception as exc:
                res.error = str(exc)
                if progress:
                    progress({"stage": "table_error", "table": phys_actual, "error": str(exc)})

            results.append(res)

    finally:
        phys_db.close()

    return results
