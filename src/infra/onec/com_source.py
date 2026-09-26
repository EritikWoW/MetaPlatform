"""1C COM connector for metadata and data extraction.

Requires pywin32 (pip install pywin32) and comcntr.dll registered:
    regsvr32 "C:\\Program Files\\1cv8\\<version>\\bin\\comcntr.dll"

Connection string examples:
    File='F:\\path\\to\\base_dir'           # file-based DB (directory with 1Cv8.1CD)
    Srvr='server'; Ref='base_name'         # server DB
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Generator, Iterator, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Optional import — graceful fallback when pywin32 is not installed
# ---------------------------------------------------------------------------

try:
    import win32com.client as _win32com
    _HAS_WIN32COM = True
except ImportError:
    _win32com = None  # type: ignore[assignment]
    _HAS_WIN32COM = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CYRILLIC_RE = re.compile(r"[а-яёА-ЯЁіїєІЇЄ]")

_UK_SYNONYMS = ("uk", "ua", "украін", "укр")
_EN_SYNONYMS = ("en", "eng", "english")


def _best_synonym(synonym_obj: Any) -> Dict[str, str]:
    """Extract uk/en titles from 1C LocalStringType (synonym object)."""
    result: Dict[str, str] = {}
    if synonym_obj is None:
        return result
    try:
        count = int(synonym_obj.Count())
    except Exception:
        try:
            raw = str(synonym_obj)
            if raw.strip():
                result["uk"] = raw.strip()
                result["en"] = raw.strip()
        except Exception:
            pass
        return result
    for i in range(count):
        try:
            item = synonym_obj.Get(i)
            lang = str(getattr(item, "LanguageCode", "") or "").lower().strip()
            content = str(getattr(item, "Content", "") or "").strip()
            if not content:
                continue
            if lang in ("ru", "ru_ru"):
                result.setdefault("_ru", content)
            elif lang in ("uk", "uk_ua"):
                result["uk"] = content
            elif lang in ("en", "en_us", "en_gb"):
                result["en"] = content
            else:
                result.setdefault("uk", content)
        except Exception:
            continue
    if "uk" not in result and "_ru" in result:
        result["uk"] = result["_ru"]
    if "en" not in result and "uk" in result:
        result["en"] = result["uk"]
    result.pop("_ru", None)
    return result


def _str_prop(obj: Any, prop: str, default: str = "") -> str:
    try:
        val = getattr(obj, prop, None)
        return str(val or "").strip() if val is not None else default
    except Exception:
        return default


def _count(coll: Any) -> int:
    try:
        return int(coll.Count())
    except Exception:
        return 0


def _iterate(coll: Any) -> Iterator[Any]:
    n = _count(coll)
    for i in range(n):
        try:
            yield coll.Get(i)
        except Exception:
            continue


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class COMRequisite:
    name: str
    synonyms: Dict[str, str]
    mp_type: str
    ref_name: str = ""
    uuid: str = ""

    def to_payload(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "title": self.synonyms,
            "type": self.mp_type,
            "ref_name": self.ref_name,
            "imported": {"source": "1c_com", "src_uuid": self.uuid},
        }


@dataclass
class COMTabularSection:
    name: str
    synonyms: Dict[str, str]
    columns: List[COMRequisite] = field(default_factory=list)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "title": self.synonyms,
            "fields": [c.to_payload() for c in self.columns],
        }


@dataclass
class COMMetaObject:
    obj_type: str          # "catalog", "document", etc.
    name: str              # technical name (ASCII or Cyrillic)
    synonyms: Dict[str, str]
    uuid: str
    comment: str = ""
    requisites: List[COMRequisite] = field(default_factory=list)
    tabular_sections: List[COMTabularSection] = field(default_factory=list)
    forms: List[str] = field(default_factory=list)
    commands: List[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        return self.synonyms.get("uk") or self.synonyms.get("en") or self.name

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "imported": {"source": "1c_com", "src_uuid": self.uuid},
        }
        if self.synonyms:
            payload["title"] = self.synonyms
        if self.requisites:
            payload["requisites"] = [r.to_payload() for r in self.requisites]
        if self.tabular_sections:
            payload["tabular_parts"] = [ts.to_payload() for ts in self.tabular_sections]
        if self.forms:
            payload["com_forms"] = self.forms
        if self.comment:
            payload["comment"] = self.comment
        return payload


# ---------------------------------------------------------------------------
# Type mapping: 1C type → MetaPlatform type
# ---------------------------------------------------------------------------

_1C_TYPE_MAP: Dict[str, str] = {
    "String": "string",
    "Number": "number",
    "Boolean": "boolean",
    "Date": "date",
    "Undefined": "any",
    "Type": "any",
    "ValueStorage": "binary",
    "UUID": "uuid",
}


def _resolve_type(type_desc: Any) -> Tuple[str, str]:
    """Return (mp_type, ref_name) from a 1C TypeDescription object."""
    if type_desc is None:
        return "string", ""
    try:
        types = type_desc.Types()
        n = _count(types)
        if n == 0:
            return "string", ""
        # single primitive type
        if n == 1:
            t = types.Get(0)
            name = _str_prop(t, "__str__") or str(t)
            # 1C type names come as "CatalogRef.Name", "DocumentRef.Name" etc.
            if "." in name:
                kind, ref = name.split(".", 1)
                kind_lower = kind.lower()
                if "catalogref" in kind_lower:
                    return "ref", f"Catalog.{ref}"
                if "documentref" in kind_lower:
                    return "ref", f"Document.{ref}"
                if "enumref" in kind_lower:
                    return "ref", f"Enum.{ref}"
                return "ref", name
            mp = _1C_TYPE_MAP.get(name, "string")
            return mp, ""
        # composite type (multiple types) - use "any"
        ref_name = ""
        for i in range(n):
            try:
                t = types.Get(i)
                name = str(t)
                if "." in name and "Ref" in name:
                    ref_name = name
                    break
            except Exception:
                continue
        if ref_name:
            kind, ref = ref_name.split(".", 1)
            return "ref", ref_name
        return "any", ""
    except Exception:
        return "string", ""


# ---------------------------------------------------------------------------
# OneCCOMConnection
# ---------------------------------------------------------------------------
# Module-level collection map (also used by com_1cd_bridge)
# ---------------------------------------------------------------------------

_COM_COLLECTION_MAP: List[Tuple[str, str]] = [
    # (1C metadata collection attr name, MetaPlatform obj_type)
    # --- Main object groups ---
    ("Constants",                        "constants"),
    ("Catalogs",                         "catalog"),
    ("Documents",                        "document"),
    ("DocumentJournals",                 "journal"),
    ("Enums",                            "enumeration"),
    ("Reports",                          "report"),
    ("DataProcessors",                   "data_processor"),
    ("ChartsOfCharacteristicTypes",      "chart_of_characteristic_types"),
    ("ChartsOfAccounts",                 "chart_of_accounts"),
    ("ChartsOfCalculationTypes",         "chart_of_calculation_types"),
    ("InformationRegisters",             "register_info"),
    ("AccumulationRegisters",            "register_accum"),
    ("AccountingRegisters",              "register_accounting"),
    ("CalculationRegisters",             "register_calc"),
    ("BusinessProcesses",                "business_process"),
    ("Tasks",                            "task"),
    ("ExternalDataSources",              "external_sources"),
    # --- General / Common objects ---
    ("Subsystems",                       "subsystem"),
    ("CommonModules",                    "common_module"),
    ("SessionParameters",                "session_parameter"),
    ("Roles",                            "role"),
    ("CommonAttributes",                 "common_attribute"),
    ("ExchangePlans",                    "exchange_plan"),
    ("FilterCriteria",                   "selection_criteria"),
    ("EventSubscriptions",               "event_subscription"),
    ("ScheduledJobs",                    "scheduled_job"),
    ("FunctionalOptions",                "functional_option"),
    ("FunctionalOptionsParameters",      "functional_option_param"),
    ("DefinedTypes",                     "defined_type"),
    ("SettingsStorages",                 "settings_storage"),
    ("CommonCommands",                   "common_command"),
    ("CommandGroups",                    "command_group"),
    ("CommonForms",                      "common_form"),
    ("CommonTemplates",                  "common_layout"),
    ("CommonPictures",                   "common_picture"),
    ("XDTOPackages",                     "xdto_package"),
    ("WebServices",                      "web_service"),
    ("HTTPServices",                     "http_service"),
    ("WSReferences",                     "ws_link"),
    ("StyleItems",                       "style_element"),
    ("Styles",                           "style"),
    ("Languages",                        "language"),
    ("DocumentNumerators",               "document_numerator"),
    ("Sequences",                        "sequence"),
]

# Public alias for external consumers
COLLECTION_MAP = _COM_COLLECTION_MAP

# ---------------------------------------------------------------------------

class OneCCOMConnection:
    """Thin wrapper around a 1C COM connection.

    Use via context manager:
        with OneCCOMConnection.connect("File='...'") as c:
            objects = c.list_all_metadata()
    """

    def __init__(self, connection: Any) -> None:
        self._conn = connection
        self._meta = connection.Metadata

    # ---- Factory ----

    @classmethod
    def connect(
        cls,
        db_path: str,
        *,
        user: str = "",
        password: str = "",
        connector_name: str = "V83.COMConnector",
    ) -> "OneCCOMConnection":
        if not _HAS_WIN32COM:
            raise ImportError(
                "pywin32 is not installed. Run: pip install pywin32"
            )
        # If it looks like a ready-made connection string — pass it as-is
        if "=" in db_path and ("File=" in db_path or "Srvr=" in db_path):
            conn_str = db_path
        else:
            # File-based database — point to the directory containing 1Cv8.1CD
            p = Path(db_path)
            dir_path = str(p if p.is_dir() else p.parent)
            parts = [f"File='{dir_path}'"]
            if user:
                parts.append(f"Usr='{user}'")
                parts.append(f"Pwd='{password}'")
            conn_str = ";".join(parts) + ";"

        connector = _win32com.Dispatch(connector_name)
        connection = connector.Connect(conn_str)
        return cls(connection)

    def __enter__(self) -> "OneCCOMConnection":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._conn = None
            self._meta = None
        except Exception:
            pass

    # ---- Configuration info ----

    @property
    def config_name(self) -> str:
        return _str_prop(self._meta, "Name")

    @property
    def config_version(self) -> str:
        return _str_prop(self._meta, "Version")

    # ---- Generic metadata collection reader ----

    def _read_requisite(self, attr: Any) -> COMRequisite:
        name = _str_prop(attr, "Name")
        synonyms = _best_synonym(getattr(attr, "Synonym", None))
        uuid = _str_prop(attr, "UUID")
        try:
            mp_type, ref_name = _resolve_type(getattr(attr, "Type", None))
        except Exception:
            mp_type, ref_name = "string", ""
        return COMRequisite(name=name, synonyms=synonyms, mp_type=mp_type,
                            ref_name=ref_name, uuid=uuid)

    def _read_tabular_section(self, ts: Any) -> COMTabularSection:
        name = _str_prop(ts, "Name")
        synonyms = _best_synonym(getattr(ts, "Synonym", None))
        columns: List[COMRequisite] = []
        try:
            attrs = getattr(ts, "Attributes", None)
            if attrs:
                for col in _iterate(attrs):
                    columns.append(self._read_requisite(col))
        except Exception:
            pass
        return COMTabularSection(name=name, synonyms=synonyms, columns=columns)

    def _read_meta_object(
        self, obj: Any, obj_type: str
    ) -> COMMetaObject:
        name = _str_prop(obj, "Name")
        synonyms = _best_synonym(getattr(obj, "Synonym", None))
        uuid = _str_prop(obj, "UUID")
        comment = _str_prop(obj, "Comment")

        requisites: List[COMRequisite] = []
        tabular_sections: List[COMTabularSection] = []
        forms: List[str] = []
        commands: List[str] = []

        # Attributes / Requisites / Dimensions / Resources
        for attr_key in ("Attributes", "Requisites", "Dimensions", "Resources", "Measures"):
            try:
                coll = getattr(obj, attr_key, None)
                if coll and _count(coll) > 0:
                    for item in _iterate(coll):
                        requisites.append(self._read_requisite(item))
            except Exception:
                continue

        # Tabular sections
        try:
            ts_coll = getattr(obj, "TabularSections", None)
            if ts_coll and _count(ts_coll) > 0:
                for ts in _iterate(ts_coll):
                    tabular_sections.append(self._read_tabular_section(ts))
        except Exception:
            pass

        # Forms
        try:
            form_coll = getattr(obj, "Forms", None)
            if form_coll and _count(form_coll) > 0:
                for form in _iterate(form_coll):
                    forms.append(_str_prop(form, "Name"))
        except Exception:
            pass

        # Commands
        try:
            cmd_coll = getattr(obj, "Commands", None)
            if cmd_coll and _count(cmd_coll) > 0:
                for cmd in _iterate(cmd_coll):
                    commands.append(_str_prop(cmd, "Name"))
        except Exception:
            pass

        return COMMetaObject(
            obj_type=obj_type,
            name=name,
            synonyms=synonyms,
            uuid=uuid,
            comment=comment,
            requisites=requisites,
            tabular_sections=tabular_sections,
            forms=forms,
            commands=commands,
        )

    # ---- Collection readers ----

    _COLLECTION_MAP = _COM_COLLECTION_MAP  # module-level alias

    def list_all_metadata(self, *, include_attrs: bool = True) -> List[COMMetaObject]:
        """Return all metadata objects from all collections."""
        result: List[COMMetaObject] = []
        for coll_name, mp_type in self._COLLECTION_MAP:
            result.extend(self.list_collection(coll_name, mp_type, include_attrs=include_attrs))
        return result

    def list_collection(
        self,
        collection_name: str,
        mp_obj_type: str,
        *,
        include_attrs: bool = True,
    ) -> List[COMMetaObject]:
        out: List[COMMetaObject] = []
        try:
            coll = getattr(self._meta, collection_name, None)
            if coll is None or _count(coll) == 0:
                return out
            for obj in _iterate(coll):
                if include_attrs:
                    out.append(self._read_meta_object(obj, mp_obj_type))
                else:
                    name = _str_prop(obj, "Name")
                    synonyms = _best_synonym(getattr(obj, "Synonym", None))
                    uuid = _str_prop(obj, "UUID")
                    out.append(COMMetaObject(
                        obj_type=mp_obj_type, name=name, synonyms=synonyms, uuid=uuid
                    ))
        except Exception as exc:
            # Collection not available in this configuration
            pass
        return out

    # ---- Counts ----

    def counts(self) -> Dict[str, int]:
        """Return {1c_collection_name: count} for quick overview."""
        result: Dict[str, int] = {}
        for coll_name, _ in self._COLLECTION_MAP:
            try:
                coll = getattr(self._meta, coll_name, None)
                result[coll_name] = _count(coll) if coll else 0
            except Exception:
                result[coll_name] = 0
        return result

    # ---- Data access ----

    def query(self, text: str) -> List[Dict[str, Any]]:
        """Execute a 1C query and return rows as dicts."""
        try:
            q = self._conn.NewObject("Query")
            q.Text = text
            result = q.Execute()
            selection = result.Choose()
            rows: List[Dict[str, Any]] = []
            while selection.Next():
                row: Dict[str, Any] = {}
                for col_idx in range(result.Columns.Count()):
                    col_name = str(result.Columns.Get(col_idx).Name)
                    try:
                        # 1C COM query selections expose columns as dynamic
                        # properties under pywin32.  Indexing by string returns
                        # no value for ordinary query results and aggregates.
                        val = getattr(selection, col_name)
                        row[col_name] = str(val) if val is not None else None
                    except Exception:
                        row[col_name] = None
                rows.append(row)
            return rows
        except Exception as exc:
            raise RuntimeError(f"1C query failed: {exc}") from exc

    def catalog_data(
        self, catalog_name: str, *, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Fetch up to `limit` rows from a catalog."""
        text = (
            f"SELECT TOP {limit} Ref, Code, Description "
            f"FROM Catalog.{catalog_name}"
        )
        return self.query(text)

    def document_data(
        self, document_name: str, *, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Fetch up to `limit` rows from a document register."""
        text = (
            f"SELECT TOP {limit} Ref, Number, Date, Posted "
            f"FROM Document.{document_name}"
        )
        return self.query(text)


# ---------------------------------------------------------------------------
# Context manager factory
# ---------------------------------------------------------------------------

@contextmanager
def connect_1c(
    db_path: str,
    *,
    user: str = "",
    password: str = "",
    connector: str = "V83.COMConnector",
) -> Generator[OneCCOMConnection, None, None]:
    """Context manager for 1C COM connection.

    Args:
        db_path: Path to the database DIRECTORY (for file-based DB),
                 or a full connection string like "Srvr='...'; Ref='...'".
        user: Username (empty string for no auth).
        password: Password.
        connector: COM ProgID of the connector.

    Example:
        with connect_1c("F:/base_dir") as c:
            objs = c.list_all_metadata()
    """
    conn = OneCCOMConnection.connect(
        db_path, user=user, password=password, connector_name=connector
    )
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Import plan builder (feeds into import_manifest_objects pipeline)
# ---------------------------------------------------------------------------

# Map: mp_obj_type → (parent_kind, parent_key)
_TYPE_TO_PARENT: Dict[str, Tuple[str, str]] = {
    # Group-parented objects
    "constants":                     ("group", "constants"),
    "catalog":                       ("group", "catalog"),
    "document":                      ("group", "document"),
    "journal":                       ("group", "journal"),
    "enumeration":                   ("group", "enumeration"),
    "report":                        ("group", "report"),
    "data_processor":                ("group", "data_processor"),
    "chart_of_characteristic_types": ("group", "chart_of_characteristic_types"),
    "chart_of_accounts":             ("group", "chart_of_accounts"),
    "chart_of_calculation_types":    ("group", "chart_of_calculation_types"),
    "register_info":                 ("group", "register_info"),
    "register_accum":                ("group", "register_accum"),
    "register_accounting":           ("group", "register_accounting"),
    "register_calc":                 ("group", "register_calc"),
    "business_process":              ("group", "business_process"),
    "task":                          ("group", "task"),
    "external_sources":              ("group", "external_sources"),
    # Common-folder-parented objects
    "subsystem":                     ("common_folder", "subsystems"),
    "common_module":                 ("common_folder", "common_modules"),
    "session_parameter":             ("common_folder", "session_params"),
    "role":                          ("common_folder", "roles"),
    "common_attribute":              ("common_folder", "common_attributes"),
    "exchange_plan":                 ("common_folder", "exchange_plans"),
    "selection_criteria":            ("common_folder", "selection_criteria"),
    "event_subscription":            ("common_folder", "event_subscriptions"),
    "scheduled_job":                 ("common_folder", "scheduled_jobs"),
    "functional_option":             ("common_folder", "functional_options"),
    "functional_option_param":       ("common_folder", "functional_options_params"),
    "defined_type":                  ("common_folder", "defined_types"),
    "settings_storage":              ("common_folder", "settings_storages"),
    "common_command":                ("common_folder", "common_commands"),
    "command_group":                 ("common_folder", "command_groups"),
    "common_form":                   ("common_folder", "common_forms"),
    "common_layout":                 ("common_folder", "common_layouts"),
    "common_picture":                ("common_folder", "common_pictures"),
    "ws_link":                       ("common_folder", "ws_links"),
    "xdto_package":                  ("common_folder", "xdto_packages"),
    "web_service":                   ("common_folder", "web_services"),
    "http_service":                  ("common_folder", "http_services"),
    "ws_link":                       ("common_folder", "ws_links"),
    "style_element":                 ("common_folder", "style_elements"),
    "style":                         ("common_folder", "styles"),
    "language":                      ("common_folder", "languages"),
    "document_numerator":            ("common_folder", "document_numerators"),
    "sequence":                      ("common_folder", "sequences"),
}


def build_com_payload(obj: COMMetaObject) -> Dict[str, Any]:
    """Convert COMMetaObject to a manifest payload dict."""
    payload = obj.to_payload()
    # Map requisites → attributes (MetaPlatform convention)
    if "requisites" in payload:
        attrs = payload.pop("requisites")
        payload["attributes"] = payload.get("attributes", []) + attrs
    return payload


def diagnose_vs_manifest(
    com_objects: List[COMMetaObject],
    manifest_objects: list,  # list of ManifestObject
) -> Dict[str, Any]:
    """Compare COM metadata with what's already in the manifest.

    Returns a report dict with:
      - total_in_1c: count from COM
      - total_in_manifest: count of imported objects
      - missing: list of objects in 1C but not in manifest
      - extra: list in manifest but not in 1C
      - by_type: per-type breakdown
    """
    # Index manifest objects by (type, name)
    manifest_index: Dict[Tuple[str, str], Any] = {}
    for mo in manifest_objects:
        if getattr(mo, "kind", "") != "object":
            continue
        key = (str(getattr(mo, "type", "") or "").strip(),
               str(getattr(mo, "name", "") or "").strip().lower())
        manifest_index[key] = mo

    com_index: Dict[Tuple[str, str], COMMetaObject] = {}
    for obj in com_objects:
        key = (obj.obj_type, obj.name.lower())
        com_index[key] = obj

    missing: List[Dict[str, str]] = []
    for key, obj in com_index.items():
        if key not in manifest_index:
            missing.append({"obj_type": obj.obj_type, "name": obj.name, "title": obj.title})

    extra: List[Dict[str, str]] = []
    for key, mo in manifest_index.items():
        if key not in com_index:
            # Check if it's an imported object (not a system object)
            payload = getattr(mo, "payload", {}) or {}
            if isinstance(payload, dict) and payload.get("imported"):
                extra.append({"obj_type": key[0], "name": key[1]})

    # Per-type breakdown
    com_by_type: Dict[str, int] = {}
    for obj in com_objects:
        com_by_type[obj.obj_type] = com_by_type.get(obj.obj_type, 0) + 1

    manifest_by_type: Dict[str, int] = {}
    for mo in manifest_objects:
        if getattr(mo, "kind", "") != "object":
            continue
        t = str(getattr(mo, "type", "") or "")
        manifest_by_type[t] = manifest_by_type.get(t, 0) + 1

    by_type: List[Dict[str, Any]] = []
    all_types = sorted(set(list(com_by_type.keys()) + list(manifest_by_type.keys())))
    for t in all_types:
        in_1c = com_by_type.get(t, 0)
        in_mp = manifest_by_type.get(t, 0)
        if in_1c != in_mp:
            by_type.append({
                "type": t,
                "in_1c": in_1c,
                "in_manifest": in_mp,
                "diff": in_1c - in_mp,
            })

    return {
        "total_in_1c": len(com_objects),
        "total_in_manifest": sum(1 for mo in manifest_objects if getattr(mo, "kind", "") == "object"),
        "missing_count": len(missing),
        "extra_count": len(extra),
        "missing": missing[:200],
        "extra": extra[:50],
        "by_type": by_type,
    }
