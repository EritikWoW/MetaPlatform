from __future__ import annotations

import json
import mimetypes
import hashlib
import os
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Protocol, Sequence, Tuple

from src.configurator.domain.default_commands import default_commands_for_context
from src.configurator.domain.default_schema import ensure_schema_defaults
from src.configurator.domain.form_templates import build_list_form_model, build_object_form_model
from src.configurator.domain.form_model import normalize_form_window_lock_mode
from src.configurator.domain.metadata_defaults import ensure_payload_defaults
from src.configurator.persistence import manifest_io
from src.configurator.persistence.db_seed import GUID_FOLDER_COMMON_MODULES, GUID_MODULE_APP, GUID_ROOT
from src.infra.onec.module_transform import normalize_module_text
from src.mpdb.mpdb import Mpdb

from .layout_parser import build_onec_layout_model
from .model import MPXConfig, MPXObject
from .onec_config_parser import _BraceValueParser
from .onec_requisites_enrich import metadata_ref_for_manifest_object, module_refs_from_import_origin


# ------------------------------------------------------------
# Sources
# ------------------------------------------------------------


class OneCSource(Protocol):
    """Abstract source of 1C/BAS configuration dump files."""

    def list_files(self) -> List[str]:
        """Return relative file paths (POSIX, no leading slash)."""

    def read_bytes(self, rel_path: str) -> bytes:
        """Read file bytes by relative path."""


def _norm_rel(p: str) -> str:
    p = str(p or "").replace("\\", "/")
    p = p.lstrip("/")
    p = posixpath.normpath(p)
    if p == ".":
        return ""
    return p


class DirectorySource:
    def __init__(self, root_dir: str) -> None:
        self.root = Path(root_dir)

    def list_files(self) -> List[str]:
        out: List[str] = []
        if not self.root.exists():
            return out
        for p in self.root.rglob("*"):
            if p.is_file():
                rel = p.relative_to(self.root).as_posix()
                out.append(_norm_rel(rel))
        out.sort()
        return out

    def read_bytes(self, rel_path: str) -> bytes:
        p = self.root / Path(rel_path)
        return p.read_bytes()


# Папки типов объектов 1С — используется для автодетекции
_KNOWN_TYPE_FOLDERS = {
    "Catalogs", "Documents", "DocumentJournals", "Enums",
    "Reports", "DataProcessors", "ChartsOfCharacteristicTypes",
    "ChartsOfAccounts", "ChartsOfCalculationTypes",
    "InformationRegisters", "AccumulationRegisters",
    "AccountingRegisters", "CalculationRegisters",
    "BusinessProcesses", "Tasks", "ExternalDataSources",
    "Subsystems", "CommonModules", "CommonForms", "CommonCommands",
    "CommonTemplates", "CommonLayouts", "CommonPictures", "Roles", "Languages",
}


class PrefixedDirectorySource:
    """DirectorySource с виртуальным префиксом.

    Используется когда пользователь выбирает подпапку дампа напрямую
    (например C:/dump/Catalogs/) вместо корня конфигурации.
    Все пути возвращаются с префиксом: "Catalogs/ИмяОбъекта.xml"
    чтобы build_import_plan их распознал.
    """

    def __init__(self, root_dir: str, prefix: str) -> None:
        self.root   = Path(root_dir)
        self.prefix = prefix.rstrip("/") + "/"

    def list_files(self) -> List[str]:
        out: List[str] = []
        if not self.root.exists():
            return out
        for p in self.root.rglob("*"):
            if p.is_file():
                rel = p.relative_to(self.root).as_posix()
                out.append(_norm_rel(self.prefix + rel))
        out.sort()
        return out

    def read_bytes(self, rel_path: str) -> bytes:
        # Убираем виртуальный префикс перед чтением файла
        rel = rel_path
        if rel.startswith(self.prefix):
            rel = rel[len(self.prefix):]
        p = self.root / Path(rel)
        return p.read_bytes()


def make_directory_source(path: str) -> "DirectorySource | PrefixedDirectorySource":
    """Создаёт правильный Source для директории.

    Автоматически определяет — указан ли корень дампа или подпапка типа.
    Если пользователь выбрал C:/dump/Catalogs/ — возвращает
    PrefixedDirectorySource с prefix="Catalogs".
    """
    p = Path(path)
    folder_name = p.name  # последняя часть пути

    if folder_name in _KNOWN_TYPE_FOLDERS:
        return PrefixedDirectorySource(str(p), prefix=folder_name)

    # Корень дампа — используем обычный DirectorySource
    return DirectorySource(str(p))


class ZipSource:
    def __init__(self, zip_path: str) -> None:
        self.zip_path = str(zip_path)
        self._zf: Optional[zipfile.ZipFile] = None
        self._prefix: str = ""

        # We keep ZipFile opened for the whole import to avoid expensive reopen.
        self._zf = zipfile.ZipFile(self.zip_path, "r")
        self._prefix = self._detect_prefix(self._zf)

    def close(self) -> None:
        if self._zf is not None:
            try:
                self._zf.close()
            finally:
                self._zf = None

    def __enter__(self) -> "ZipSource":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @staticmethod
    def _detect_prefix(zf: zipfile.ZipFile) -> str:
        """Try to detect a common root directory inside the zip.

        Typical dumps come as:
            ConfigFiles/... (or) someRoot/ConfigFiles/...

        We detect the shortest prefix that ends with 'ConfigFiles/'.
        If not found, use empty prefix.
        """
        best: Optional[str] = None
        for info in zf.infolist():
            name = (info.filename or "").replace("\\", "/")
            if not name or name.endswith("/"):
                continue
            parts = name.split("/")
            for i, part in enumerate(parts[:-1]):
                if part.lower() == "configfiles":
                    cand = "/".join(parts[: i + 1]) + "/"
                    if best is None or len(cand) < len(best):
                        best = cand
        return best or ""

    def list_files(self) -> List[str]:
        assert self._zf is not None
        out: List[str] = []
        for info in self._zf.infolist():
            name = (info.filename or "").replace("\\", "/")
            if not name or name.endswith("/"):
                continue
            if self._prefix and name.startswith(self._prefix):
                rel = name[len(self._prefix) :]
            else:
                rel = name
            rel = _norm_rel(rel)
            if rel:
                out.append(rel)
        out.sort()
        return out

    def read_bytes(self, rel_path: str) -> bytes:
        assert self._zf is not None
        rel = _norm_rel(rel_path)
        full = self._prefix + rel if self._prefix else rel
        with self._zf.open(full, "r") as f:
            return f.read()


def guess_mime(rel_path: str) -> str:
    # Prefer known text formats
    ext = (Path(rel_path).suffix or "").lower()
    if ext in (".bsl", ".txt", ".md"):
        return "text/plain"
    if ext in (".xml",):
        return "application/xml"
    if ext in (".json",):
        return "application/json"
    mime, _ = mimetypes.guess_type(rel_path)
    return mime or "application/octet-stream"


# ------------------------------------------------------------
# Parsing helpers
# ------------------------------------------------------------


_XML_NAME_RE = re.compile(r"^[^/]+/([^/]+)\.xml$", re.IGNORECASE)


def _decode_text(data: bytes) -> str:
    """Best-effort decode (UTF-8 BOM -> UTF-8 -> CP1251)."""
    if not data:
        return ""
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return data.decode(enc)
        except Exception:
            continue
    # last resort
    return data.decode("utf-8", errors="replace")


def make_fallback_module_guid(owner_guid: str, module_kind: str, origin: str) -> str:
    """Best-effort deterministic id when DAO is unavailable.

    We intentionally avoid importing stdlib `uuid` here.
    """

    base = f"{owner_guid}:{module_kind}:{origin}"
    h = hashlib.sha1(base.encode("utf-8", errors="replace")).hexdigest()
    # Format as a UUID-like string (not a real RFC uuid, but stable).
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _xml_find_first_text(root: Any, tag_names: Sequence[str]) -> str:
    """Namespace-agnostic search for the first matching element text."""
    try:
        import xml.etree.ElementTree as ET

        # Try direct tag match (no namespace)
        for tn in tag_names:
            el = root.find(f".//{tn}")
            if el is not None and (el.text or "").strip():
                return (el.text or "").strip()

        # Fallback: match by localname
        wanted = {str(t).lower() for t in tag_names}
        for el in root.iter():
            tag = str(getattr(el, "tag", ""))
            if "}" in tag:
                tag = tag.split("}", 1)[1]
            if tag.lower() in wanted and (el.text or "").strip():
                return (el.text or "").strip()
    except Exception:
        return ""
    return ""


def parse_xml_synonyms(xml_bytes: bytes) -> Dict[str, str]:
    synonyms: Dict[str, str] = {}
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return synonyms
    for item in root.iter():
        local_name = str(getattr(item, "tag", "")).rsplit("}", 1)[-1].lower()
        if local_name != "item":
            continue
        lang = ""
        content = ""
        for child in item.iter():
            child_name = str(getattr(child, "tag", "")).rsplit("}", 1)[-1].lower()
            if child_name == "lang":
                lang = str(child.text or "").strip().lower()
            elif child_name == "content":
                content = str(child.text or "").strip()
        if lang and content:
            synonyms.setdefault(lang, content)
    return synonyms


def parse_basic_xml_fields(xml_bytes: bytes) -> Tuple[str, str, str]:
    """Return (name, title, uuid_or_empty)."""
    name = ""
    title = ""
    uid = ""
    try:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(xml_bytes)
        # Name
        name = _xml_find_first_text(root, ["Name", "name"])
        # Title / synonym
        synonyms = parse_xml_synonyms(xml_bytes)
        title = next(
            (synonyms[lang] for lang in ("uk", "en", "ru") if synonyms.get(lang)),
            "",
        )
        if not title:
            title = _xml_find_first_text(root, ["Presentation", "presentation", "Title", "title"])
        # UUID/GUID
        uid = _xml_find_first_text(root, ["UUID", "Uuid", "GUID", "Guid", "Ref", "ref"])
        # sometimes uuid is in attributes
        if not uid:
            # Exported metadata wraps the actual object in <MetaDataObject>;
            # the stable UUID belongs to that first object element, not to the
            # wrapper. Walk in document order and take the first identity.
            for element in root.iter():
                for k in ("uuid", "UUID", "guid", "Guid"):
                    v = element.attrib.get(k)
                    if v:
                        uid = str(v).strip()
                        break
                if uid:
                    break
    except Exception:
        pass

    # If title is empty, use name
    if not title:
        title = name
    return name.strip(), title.strip(), uid.strip()


_SUBSYSTEM_PREFIX_RE = re.compile(r"^\s*\d+\s+(.+?)\s*$")


def _normalize_subsystem_label(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = _SUBSYSTEM_PREFIX_RE.match(text)
    if match is not None:
        return match.group(1).strip()
    return text


def parse_subsystem_help_pages(xml_bytes: bytes) -> list[str]:
    try:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(xml_bytes)
    except Exception:
        return []

    out: list[str] = []
    seen: set[str] = set()
    for el in root.iter():
        tag = str(getattr(el, "tag", ""))
        if "}" in tag:
            tag = tag.split("}", 1)[1]
        if tag != "Page":
            continue
        value = str(el.text or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _decode_help_html(xml_bytes: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "latin1"):
        try:
            return xml_bytes.decode(encoding)
        except Exception:
            continue
    return xml_bytes.decode("utf-8", errors="replace")


def parse_help_page_contents(
    source,
    *,
    help_rel: str,
    help_pages: list[str],
    path_set: set[str],
) -> dict[str, str]:
    help_rel = _norm_rel(help_rel)
    base_dir = _norm_rel(posixpath.join(posixpath.dirname(help_rel), "Help"))
    out: dict[str, str] = {}

    ordered_pages: list[str] = []
    seen_pages: set[str] = set()
    for page in help_pages:
        page_key = str(page or "").strip()
        if not page_key or page_key in seen_pages:
            continue
        seen_pages.add(page_key)
        ordered_pages.append(page_key)

    if not ordered_pages:
        prefix = f"{base_dir}/"
        for rel in sorted(path for path in path_set if path.startswith(prefix) and path.lower().endswith(".html")):
            page_key = Path(rel).stem
            if page_key and page_key not in seen_pages:
                seen_pages.add(page_key)
                ordered_pages.append(page_key)

    for page_key in ordered_pages:
        rel = _norm_rel(f"{base_dir}/{page_key}.html")
        if rel not in path_set:
            continue
        try:
            html = _decode_help_html(source.read_bytes(rel))
        except Exception:
            continue
        if str(html or "").strip():
            out[page_key] = html
    return out


def parse_subsystem_command_interface(xml_bytes: bytes) -> dict[str, Any]:
    try:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(xml_bytes)
    except Exception:
        return {}

    def _local_tag(el: Any) -> str:
        tag = str(getattr(el, "tag", ""))
        return tag.split("}", 1)[1] if "}" in tag else tag

    def _find_child_text(parent: Any, child_name: str) -> str:
        for child in list(parent):
            if _local_tag(child) != child_name:
                continue
            return str(child.text or "").strip()
        return ""

    def _find_bool_descendant(parent: Any, child_name: str) -> bool | None:
        for child in parent.iter():
            if _local_tag(child) != child_name:
                continue
            raw = str(child.text or "").strip().lower()
            if raw in {"true", "1", "yes"}:
                return True
            if raw in {"false", "0", "no"}:
                return False
        return None

    out: dict[str, Any] = {}
    for section in list(root):
        section_name = _local_tag(section)
        if section_name == "CommandsVisibility":
            entries: list[dict[str, Any]] = []
            for command in list(section):
                if _local_tag(command) != "Command":
                    continue
                name = str(command.attrib.get("name") or "").strip()
                if not name:
                    continue
                item: dict[str, Any] = {"name": name}
                visibility_common = _find_bool_descendant(command, "Common")
                if visibility_common is not None:
                    item["common"] = visibility_common
                entries.append(item)
            if entries:
                out["commands_visibility"] = entries
        elif section_name == "CommandsPlacement":
            entries = []
            for command in list(section):
                if _local_tag(command) != "Command":
                    continue
                name = str(command.attrib.get("name") or "").strip()
                if not name:
                    continue
                item = {"name": name}
                command_group = _find_child_text(command, "CommandGroup")
                placement = _find_child_text(command, "Placement")
                if command_group:
                    item["command_group"] = command_group
                if placement:
                    item["placement"] = placement
                entries.append(item)
            if entries:
                out["commands_placement"] = entries
        elif section_name == "CommandsOrder":
            entries = []
            for command in list(section):
                if _local_tag(command) != "Command":
                    continue
                name = str(command.attrib.get("name") or "").strip()
                if not name:
                    continue
                item = {"name": name}
                command_group = _find_child_text(command, "CommandGroup")
                if command_group:
                    item["command_group"] = command_group
                entries.append(item)
            if entries:
                out["commands_order"] = entries
        elif section_name == "GroupsOrder":
            groups = [
                str(group.text or "").strip()
                for group in list(section)
                if _local_tag(group) == "Group" and str(group.text or "").strip()
            ]
            if groups:
                out["groups_order"] = groups
        elif section_name == "SubsystemsOrder":
            subsystems: list[str] = []
            seen_subsystems: set[str] = set()
            for subsystem in list(section):
                if _local_tag(subsystem) != "Subsystem":
                    continue
                value = _normalize_subsystem_label(str(subsystem.text or "").strip())
                if not value or value in seen_subsystems:
                    continue
                seen_subsystems.add(value)
                subsystems.append(value)
            if subsystems:
                out["subsystems_order"] = subsystems

    return out


def _extract_subsystem_content_refs(xml_bytes: bytes) -> list[str]:
    """Extract MDObjectRef entries from a subsystem metadata XML Content block."""

    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return []

    refs: list[str] = []
    seen: set[str] = set()
    for item in root.findall(
        ".//{http://v8.1c.ru/8.3/MDClasses}Content/{http://v8.1c.ru/8.3/xcf/readable}Item"
    ):
        ref = str(item.text or "").strip()
        if not ref or ref in seen:
            continue
        seen.add(ref)
        refs.append(ref)
    return refs


def to_ascii_identifier(s: str) -> str:
    """Create a stable ASCII identifier for internal 'name' fields.

    - transliterates UA/RU Cyrillic to Latin (best-effort)
    - keeps [a-zA-Z0-9_]
    - collapses separators to '_'
    """

    s = str(s or "").strip()
    if not s:
        return "obj"

    # Basic UA/RU transliteration mapping (not perfect, but stable)
    m = {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "h",
        "ґ": "g",
        "д": "d",
        "е": "e",
        "є": "ye",
        "ж": "zh",
        "з": "z",
        "и": "y",
        "і": "i",
        "ї": "yi",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "kh",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "shch",
        "ь": "",
        "ю": "yu",
        "я": "ya",
        "ъ": "",
        "ы": "y",
        "э": "e",
        "ё": "yo",
    }

    out: List[str] = []
    for ch in s:
        low = ch.lower()
        if low in m:
            tr = m[low]
            # preserve case roughly
            if ch.isupper():
                tr = tr.capitalize()
            out.append(tr)
        else:
            out.append(ch)

    raw = "".join(out)
    # replace non-alnum with underscores
    cleaned: List[str] = []
    prev_us = False
    for ch in raw:
        if ch.isalnum():
            cleaned.append(ch)
            prev_us = False
        else:
            if not prev_us:
                cleaned.append("_")
                prev_us = True
    res = "".join(cleaned).strip("_")
    if not res:
        res = "obj"
    if res[0].isdigit():
        res = "obj_" + res
    return res


# ------------------------------------------------------------
# Deep import plan
# ------------------------------------------------------------


@dataclass(frozen=True)
class ImportObjectSpec:
    obj_type: str
    parent_kind: str  # "group" or "common_folder" or "object_section" or "subsystem_parent"
    parent_key: str   # group type for group, folder name for common_folder, section key for object_section
    rel_xml: str
    rel_dir_prefix: str


@dataclass(frozen=True)
class FormImportSpec:
    rel_xml: str
    ext_form_rel: str = ""
    help_rel: str = ""
    dump_info_id: str = ""


@dataclass(frozen=True)
class CommandImportSpec:
    rel_xml: str
    module_origins: List[Tuple[str, str]]
    dump_info_id: str = ""


@dataclass(frozen=True)
class LayoutImportSpec:
    rel_xml: str
    body_rel: str = ""
    dump_info_id: str = ""


@dataclass(frozen=True)
class ImportObjectProfile:
    rel_xml: str
    forms: List[str]
    commands: List[str]
    layouts: List[str]
    module_origins: List[Tuple[str, str]]
    child_metadata: Dict[str, List[str]]
    form_specs: List[FormImportSpec]
    command_specs: List[CommandImportSpec]
    layout_specs: List[LayoutImportSpec]


def _sort_import_specs(specs: Sequence[ImportObjectSpec]) -> List[ImportObjectSpec]:
    def key_of(spec: ImportObjectSpec) -> Tuple[int, str, str]:
        depth = spec.rel_xml.count("/")
        return (depth, spec.obj_type, spec.rel_xml.lower())

    return sorted(specs, key=key_of)


EXPORT_GROUP_MAP: Dict[str, Tuple[str, str]] = {
    # 1C folder -> (mp group/object type, destination group type)
    "Constants": ("constants", "constants"),
    "Catalogs": ("catalog", "catalog"),
    "Documents": ("document", "document"),
    "DocumentJournals": ("journal", "journal"),
    "Enums": ("enumeration", "enumeration"),
    "Reports": ("report", "report"),
    "DataProcessors": ("data_processor", "data_processor"),
    "ChartsOfCharacteristicTypes": ("chart_of_characteristic_types", "chart_of_characteristic_types"),
    "ChartsOfAccounts": ("chart_of_accounts", "chart_of_accounts"),
    "ChartsOfCalculationTypes": ("chart_of_calculation_types", "chart_of_calculation_types"),
    "InformationRegisters": ("register_info", "register_info"),
    "AccumulationRegisters": ("register_accum", "register_accum"),
    "AccountingRegisters": ("register_accounting", "register_accounting"),
    "CalculationRegisters": ("register_calc", "register_calc"),
    "BusinessProcesses": ("business_process", "business_process"),
    "Tasks": ("task", "task"),
    "ExternalDataSources": ("external_sources", "external_sources"),
}


EXPORT_COMMON_MAP: Dict[str, Tuple[str, str]] = {
    # 1C folder -> (obj_type, destination common folder name)
    "Subsystems": ("subsystem", "subsystems"),
    "CommonAttributes": ("common_attribute", "common_attributes"),
    "CommandGroups": ("command_group", "command_groups"),
    "ScheduledJobs": ("scheduled_job", "scheduled_jobs"),
    "CommonModules": ("common_module", "common_modules"),
    "CommonForms": ("common_form", "common_forms"),
    "CommonCommands": ("common_command", "common_commands"),
    "CommonTemplates": ("common_layout", "common_layouts"),
    "CommonLayouts": ("common_layout", "common_layouts"),
    "CommonPictures": ("common_picture", "common_pictures"),
    "DocumentNumerators": ("document_numerator", "document_numerators"),
    "Roles": ("role", "roles"),
    "Sequences": ("sequence", "sequences"),
    "Languages": ("language", "languages"),
    # Common objects registered in DBNames but previously missing from the map
    "ExchangePlans": ("exchange_plan", "exchange_plans"),
    "SessionParameters": ("session_parameter", "session_params"),
    "EventSubscriptions": ("event_subscription", "event_subscriptions"),
    "FunctionalOptions": ("functional_option", "functional_options"),
    "FunctionalOptionsParameters": ("functional_option_param", "functional_options_params"),
    "DefinedTypes": ("defined_type", "defined_types"),
    "SettingsStorages": ("settings_storage", "settings_storages"),
    "WebServices": ("web_service", "web_services"),
    "HTTPServices": ("http_service", "http_services"),
    "WSReferences": ("ws_reference", "ws_links"),
    "StyleItems": ("style_element", "style_elements"),
    "Styles": ("style", "styles"),
    "SelectionCriteria": ("selection_criteria", "selection_criteria"),
    # Aliases used by some 1C dump versions
    "FilterCriteria": ("selection_criteria", "selection_criteria"),
    "XDTOPackages": ("xdto_package", "xdto_packages"),
}


def build_import_plan(paths: Sequence[str]) -> List[ImportObjectSpec]:
    """Discover objects to import by scanning file paths."""

    specs: List[ImportObjectSpec] = []

    # Group-based objects (top-level only)
    for folder, (obj_type, group_type) in EXPORT_GROUP_MAP.items():
        for rel in paths:
            if not rel.lower().startswith(folder.lower() + "/"):
                continue
            # only direct xml: Folder/Name.xml
            m = _XML_NAME_RE.match(rel)
            if not m:
                continue
            if rel.split("/")[0] != folder:
                continue
            name = m.group(1)
            rel_dir = f"{folder}/{name}/"
            specs.append(
                ImportObjectSpec(
                    obj_type=obj_type,
                    parent_kind="group",
                    parent_key=group_type,
                    rel_xml=rel,
                    rel_dir_prefix=rel_dir,
                )
            )

    # Common folder-based objects
    for folder, (obj_type, common_folder) in EXPORT_COMMON_MAP.items():
        for rel in paths:
            if not rel.lower().startswith(folder.lower() + "/"):
                continue

            if obj_type == "common_picture":
                parts = rel.split("/")
                if len(parts) != 2:
                    continue
                ext = Path(rel).suffix.lower()
                if ext == ".xml":
                    stem = Path(rel).stem
                elif ext in (".png", ".jpg", ".jpeg", ".svg", ".webp", ".bmp"):
                    stem = Path(rel).stem
                else:
                    continue
                specs.append(
                    ImportObjectSpec(
                        obj_type=obj_type,
                        parent_kind="common_folder",
                        parent_key=common_folder,
                        rel_xml=rel,
                        rel_dir_prefix=f"{folder}/{stem}/",
                    )
                )
                continue

            # xml-based: Folder/Name.xml (Subsystems can be nested)
            if not rel.lower().endswith(".xml"):
                continue
            parts = rel.split("/")
            if parts[0] != folder:
                continue

            if folder == "Subsystems":
                # allow nested: Subsystems/A.xml or Subsystems/A/Subsystems/B.xml...
                if len(parts) < 2:
                    continue
                # Only real subsystem definition xml files are importable here:
                # - Subsystems/Name.xml
                # - Subsystems/Parent/Subsystems/Child.xml
                # Skip service xml under Ext/, Help.xml and any other nested files.
                if len(parts) != 2 and parts[-2] != "Subsystems":
                    continue
                # last element is file name
                fn = parts[-1]
                if not fn.lower().endswith(".xml"):
                    continue
                stem = fn[:-4]
                rel_dir = f"{posixpath.dirname(rel)}/{stem}/"
                # determine parent kind
                if len(parts) >= 4 and parts[-2] == "Subsystems":
                    # parent subsystem xml path is .../<Parent>.xml
                    parent_xml = f"{'/'.join(parts[:-2])}.xml"
                    specs.append(
                        ImportObjectSpec(
                            obj_type=obj_type,
                            parent_kind="subsystem_parent",
                            parent_key=parent_xml,
                            rel_xml=rel,
                            rel_dir_prefix=rel_dir,
                        )
                    )
                else:
                    specs.append(
                        ImportObjectSpec(
                            obj_type=obj_type,
                            parent_kind="common_folder",
                            parent_key=common_folder,
                            rel_xml=rel,
                            rel_dir_prefix=rel_dir,
                        )
                    )
                continue

            # non-hierarchical common objects: only direct Folder/Name.xml
            if len(parts) != 2:
                continue
            stem = Path(rel).stem
            rel_dir = f"{folder}/{stem}/"
            specs.append(
                ImportObjectSpec(
                    obj_type=obj_type,
                    parent_kind="common_folder",
                    parent_key=common_folder,
                    rel_xml=rel,
                    rel_dir_prefix=rel_dir,
                )
            )

    return _sort_import_specs(specs)


_DUMPINFO_ROOT_MAP: Dict[str, Tuple[str, str, str]] = {
    "Catalog": ("catalog", "Catalogs", "catalog"),
    "Document": ("document", "Documents", "document"),
    "DocumentJournal": ("journal", "DocumentJournals", "journal"),
    "DocumentNumerator": ("document_numerator", "DocumentNumerators", "document_numerators"),
    "Enum": ("enumeration", "Enums", "enumeration"),
    "Subsystem": ("subsystem", "Subsystems", "subsystems"),
    "ScheduledJob": ("scheduled_job", "ScheduledJobs", "scheduled_jobs"),
    "Report": ("report", "Reports", "report"),
    "DataProcessor": ("data_processor", "DataProcessors", "data_processor"),
    "Constant": ("constants", "Constants", "constants"),
    "AccumulationRegister": ("register_accum", "AccumulationRegisters", "register_accum"),
    "InformationRegister": ("register_info", "InformationRegisters", "register_info"),
    "AccountingRegister": ("register_accounting", "AccountingRegisters", "register_accounting"),
    "CalculationRegister": ("register_calc", "CalculationRegisters", "register_calc"),
    "BusinessProcess": ("business_process", "BusinessProcesses", "business_process"),
    "Task": ("task", "Tasks", "task"),
    "ChartOfAccounts": ("chart_of_accounts", "ChartsOfAccounts", "chart_of_accounts"),
    "ChartOfCharacteristicTypes": ("chart_of_characteristic_types", "ChartsOfCharacteristicTypes", "chart_of_characteristic_types"),
    "ChartOfCalculationTypes": ("chart_of_calculation_types", "ChartsOfCalculationTypes", "chart_of_calculation_types"),
    "ExchangePlan": ("exchange_plan", "ExchangePlans", "exchange_plans"),
    "CommonModule": ("common_module", "CommonModules", "common_modules"),
    "CommonForm": ("common_form", "CommonForms", "common_forms"),
    "CommonCommand": ("common_command", "CommonCommands", "common_commands"),
    "CommonTemplate": ("common_layout", "CommonTemplates", "common_layouts"),
    "CommonPicture": ("common_picture", "CommonPictures", "common_pictures"),
    "CommandGroup": ("command_group", "CommandGroups", "command_groups"),
    "Role": ("role", "Roles", "roles"),
    "Language": ("language", "Languages", "languages"),
    "EventSubscription": ("event_subscription", "EventSubscriptions", "event_subscriptions"),
    "FunctionalOption": ("functional_option", "FunctionalOptions", "functional_options"),
    "FunctionalOptionsParameter": ("functional_option_param", "FunctionalOptionsParameters", "functional_options_params"),
    "DefinedType": ("defined_type", "DefinedTypes", "defined_types"),
    "SettingsStorage": ("settings_storage", "SettingsStorages", "settings_storages"),
    "WebService": ("web_service", "WebServices", "web_services"),
    "HTTPService": ("http_service", "HTTPServices", "http_services"),
    "WSReference": ("ws_reference", "WSReferences", "ws_links"),
    "StyleItem": ("style_element", "StyleItems", "style_elements"),
    "Style": ("style", "Styles", "styles"),
    "FilterCriterion": ("selection_criteria", "FilterCriteria", "selection_criteria"),
    "XDTOPackage": ("xdto_package", "XDTOPackages", "xdto_packages"),
}
_ROOT_MODULE_SUFFIXES = {
    "ManagerModule": "ManagerModule",
    "ObjectModule": "ObjectModule",
    "RecordSetModule": "RecordSetModule",
    "ValueManagerModule": "ValueManagerModule",
    "CommandModule": "CommandModule",
    "Module": "Module",
}
_CONFIGURATION_ROOT_MODULES: Tuple[Tuple[str, str, str, str | None], ...] = (
    ("ManagedApplicationModule.bsl", "AppModule", "МодульПрограми", GUID_MODULE_APP),
    ("SessionModule.bsl", "SessionModule", "SessionModule", None),
    ("ExternalConnectionModule.bsl", "ExternalConnectionModule", "ExternalConnectionModule", None),
    ("OrdinaryApplicationModule.bsl", "OrdinaryApplicationModule", "OrdinaryApplicationModule", None),
)


def _tag_name(tag: str) -> str:
    return str(tag or "").split("}")[-1]


def _find_child_text(node: ET.Element | None, name: str, default: str = "") -> str:
    if node is None:
        return default
    child = node.find(f"./{{*}}{name}")
    if child is None or child.text is None:
        return default
    return str(child.text).strip()


def _find_child_bool(node: ET.Element | None, name: str, default: bool = False) -> bool:
    text = _find_child_text(node, name, "")
    if not text:
        return bool(default)
    return text.strip().lower() in {"1", "true", "yes", "y", "да", "так"}


def _find_child_int(node: ET.Element | None, name: str, default: int = 0) -> int:
    try:
        return int(float(_find_child_text(node, name, str(default)) or default))
    except Exception:
        return int(default)


_XML_BOOL_TRUE = {"1", "true", "yes", "y", "да", "так"}
_XML_BOOL_FALSE = {"0", "false", "no", "n", "нет", "ні", "ни"}
_XML_INT_RE = re.compile(r"^[+-]?(0|[1-9]\d*)$")
_XML_CAMEL_1_RE = re.compile(r"(.)([A-Z][a-z]+)")
_XML_CAMEL_2_RE = re.compile(r"([a-z0-9])([A-Z])")


def _xml_prop_key(name: str) -> str:
    raw = str(name or "").strip().replace("-", "_")
    if not raw:
        return ""
    raw = _XML_CAMEL_1_RE.sub(r"\1_\2", raw)
    raw = _XML_CAMEL_2_RE.sub(r"\1_\2", raw)
    raw = raw.replace("__", "_")
    return raw.strip("_").lower()


def _xml_scalar_value(text: str) -> Any:
    raw = str(text or "").strip()
    if not raw:
        return ""
    low = raw.lower()
    if low in _XML_BOOL_TRUE:
        return True
    if low in _XML_BOOL_FALSE:
        return False
    if _XML_INT_RE.match(raw):
        try:
            return int(raw)
        except Exception:
            pass
    return raw


def _collect_node_props(node: ET.Element | None, *, skip: set[str] | None = None) -> Dict[str, Any]:
    if node is None:
        return {}
    skip_names = {str(name or "").strip().lower() for name in (skip or set())}
    props: Dict[str, Any] = {}
    for child in list(node):
        tag = _tag_name(child.tag)
        tag_key = _xml_prop_key(tag)
        if not tag_key or tag_key in skip_names:
            continue
        if list(child):
            continue
        value = _xml_scalar_value(child.text or "")
        if value == "" and not (child.text or "").strip():
            continue
        props[tag_key] = value
    return props


def _local_string_value(node: ET.Element | None) -> str:
    if node is None:
        return ""
    items = []
    for item in node.findall(".//{*}item"):
        lang = _find_child_text(item, "lang", "").lower()
        content = _find_child_text(item, "content", "")
        items.append((lang, content))
    for preferred in ("uk", "en"):
        for lang, content in items:
            if lang == preferred and content:
                return content
    for _lang, content in items:
        if content:
            return content
    return str(node.text or "").strip()


def _repair_mojibake_component(text: str) -> str:
    raw = str(text or "")
    try:
        repaired = raw.encode("latin1").decode("cp1251")
    except Exception:
        return raw
    if repaired != raw and any("\u0400" <= ch <= "\u04FF" for ch in repaired):
        return repaired
    return raw


def _split_metadata_owner(name: str) -> Tuple[str, List[str], List[str]]:
    parts = [_repair_mojibake_component(part) for part in str(name or "").split(".") if part]
    if len(parts) < 2:
        return "", [], []
    root_type = parts[0]
    owner_parts = [parts[1]]
    idx = 2
    if root_type == "Subsystem":
        while idx + 1 < len(parts) and parts[idx] == "Subsystem":
            owner_parts.append(parts[idx + 1])
            idx += 2
    return root_type, owner_parts, parts[idx:]


def _rel_xml_for_metadata_owner(root_type: str, owner_parts: List[str]) -> str:
    mapping = _DUMPINFO_ROOT_MAP.get(root_type)
    if not mapping or not owner_parts:
        return ""
    _obj_type, folder, _parent_key = mapping
    rel = f"{folder}/{owner_parts[0]}.xml"
    if root_type == "Subsystem" and len(owner_parts) > 1:
        for part in owner_parts[1:]:
            rel = f"{posixpath.splitext(rel)[0]}/Subsystems/{part}.xml"
    return rel


def _rel_dir_for_metadata_owner(root_type: str, owner_parts: List[str]) -> str:
    rel_xml = _rel_xml_for_metadata_owner(root_type, owner_parts)
    if not rel_xml:
        return ""
    stem = Path(rel_xml).stem
    base_dir = posixpath.dirname(rel_xml)
    return _norm_rel(f"{base_dir}/{stem}/") + "/"


def _parse_dump_info_entries(source: OneCSource) -> List[Tuple[str, str]]:
    try:
        raw = source.read_bytes("ConfigDumpInfo.xml")
    except Exception:
        return []
    try:
        root = ET.fromstring(raw)
    except Exception:
        return []
    out: List[Tuple[str, str]] = []
    for node in root.findall(".//{*}Metadata"):
        name = str(node.attrib.get("name") or "").strip()
        dump_id = str(node.attrib.get("id") or "").strip()
        if name:
            out.append((name, dump_id))
    return out


def build_import_plan_from_dump_info(source: OneCSource, paths: Sequence[str]) -> List[ImportObjectSpec]:
    path_set = {str(p or "") for p in paths}
    specs_by_xml: Dict[str, ImportObjectSpec] = {}
    for name, _dump_id in _parse_dump_info_entries(source):
        root_type, owner_parts, remainder = _split_metadata_owner(name)
        if not root_type or not owner_parts or remainder:
            continue
        mapping = _DUMPINFO_ROOT_MAP.get(root_type)
        if not mapping:
            continue
        obj_type, _folder, parent_key = mapping
        rel_xml = _rel_xml_for_metadata_owner(root_type, owner_parts)
        if not rel_xml or rel_xml not in path_set:
            continue
        if root_type == "Subsystem" and len(owner_parts) > 1:
            parent_rel = _rel_xml_for_metadata_owner(root_type, owner_parts[:-1])
            parent_kind = "subsystem_parent"
            parent_ref = parent_rel
        elif root_type == "Subsystem":
            parent_kind = "common_folder"
            parent_ref = parent_key
        elif _folder in EXPORT_COMMON_MAP:
            # Folder is under the "Общие" section, not a top-level group.
            parent_kind = "common_folder"
            parent_ref = parent_key
        else:
            parent_kind = "group"
            parent_ref = parent_key
        specs_by_xml[rel_xml] = ImportObjectSpec(
            obj_type=obj_type,
            parent_kind=parent_kind,
            parent_key=parent_ref,
            rel_xml=rel_xml,
            rel_dir_prefix=_rel_dir_for_metadata_owner(root_type, owner_parts),
        )
    return _sort_import_specs(list(specs_by_xml.values()))


def merge_import_plans(
    base_plan: Sequence[ImportObjectSpec],
    dump_info_plan: Sequence[ImportObjectSpec],
) -> List[ImportObjectSpec]:
    merged: Dict[str, ImportObjectSpec] = {spec.rel_xml: spec for spec in base_plan}
    for spec in dump_info_plan:
        merged[spec.rel_xml] = spec
    return _sort_import_specs(list(merged.values()))


def build_import_profiles_from_dump_info(
    source: OneCSource,
    paths: Sequence[str],
    plan: Sequence[ImportObjectSpec],
) -> Dict[str, ImportObjectProfile]:
    path_set = {str(p or "") for p in paths}
    profiles: Dict[str, Dict[str, Any]] = {
        spec.rel_xml: {
            "rel_xml": spec.rel_xml,
            "forms": [],
            "commands": [],
            "layouts": [],
            "module_origins": [],
            "child_metadata": {},
            "form_specs": {},
            "command_specs": {},
            "layout_specs": {},
        }
        for spec in plan
    }

    for name, dump_id in _parse_dump_info_entries(source):
        root_type, owner_parts, remainder = _split_metadata_owner(name)
        owner_rel = _rel_xml_for_metadata_owner(root_type, owner_parts)
        if owner_rel not in profiles:
            continue
        owner_dir = _rel_dir_for_metadata_owner(root_type, owner_parts)
        profile = profiles[owner_rel]
        if not remainder:
            continue

        head = remainder[0]
        if head == "Attribute" and len(remainder) >= 2:
            profile["child_metadata"].setdefault("attribute", []).append(remainder[1])
            continue
        if head == "TabularSection" and len(remainder) >= 2:
            profile["child_metadata"].setdefault("tabularsection", []).append(remainder[1])
            continue
        if head == "Form" and len(remainder) >= 2:
            form_name = remainder[1]
            form_rel = _norm_rel(f"{owner_dir}Forms/{form_name}.xml")
            spec = profile["form_specs"].setdefault(
                form_rel,
                {
                    "rel_xml": form_rel,
                    "ext_form_rel": "",
                    "help_rel": "",
                    "dump_info_id": "",
                },
            )
            if form_rel not in profile["forms"]:
                profile["forms"].append(form_rel)
            if len(remainder) == 2:
                spec["dump_info_id"] = dump_id
            elif len(remainder) >= 3 and remainder[2] == "Form":
                ext_rel = _norm_rel(f"{owner_dir}Forms/{form_name}/Ext/Form.xml")
                if ext_rel in path_set:
                    spec["ext_form_rel"] = ext_rel
            elif len(remainder) >= 3 and remainder[2] == "Help":
                help_rel = _norm_rel(f"{owner_dir}Forms/{form_name}/Ext/Help.xml")
                if help_rel in path_set:
                    spec["help_rel"] = help_rel
            continue
        if head == "Command" and len(remainder) >= 2:
            command_name = remainder[1]
            command_rel = _norm_rel(f"{owner_dir}Commands/{command_name}.xml")
            spec = profile["command_specs"].setdefault(
                command_rel,
                {
                    "rel_xml": command_rel,
                    "module_origins": [],
                    "dump_info_id": "",
                },
            )
            if command_rel not in profile["commands"]:
                profile["commands"].append(command_rel)
            if len(remainder) == 2:
                spec["dump_info_id"] = dump_id
            elif len(remainder) >= 3 and remainder[2] == "CommandModule":
                mod_rel = _norm_rel(f"{owner_dir}Commands/{command_name}/Ext/CommandModule.bsl")
                if mod_rel in path_set:
                    spec["module_origins"].append((mod_rel, "CommandModule"))
            continue
        if head in {"Template", "Layout"} and len(remainder) >= 2:
            layout_name = remainder[1]
            layout_rel = _norm_rel(f"{owner_dir}Templates/{layout_name}.xml")
            spec = profile["layout_specs"].setdefault(
                layout_rel,
                {
                    "rel_xml": layout_rel,
                    "body_rel": "",
                    "dump_info_id": dump_id if len(remainder) == 2 else "",
                },
            )
            if layout_rel not in profile["layouts"]:
                profile["layouts"].append(layout_rel)
            for ext in ("xml", "txt", "bin"):
                body_rel = _norm_rel(f"{owner_dir}Templates/{layout_name}/Ext/Template.{ext}")
                if body_rel in path_set:
                    spec["body_rel"] = body_rel
                    break
            continue
        if len(remainder) == 1 and remainder[0] in _ROOT_MODULE_SUFFIXES:
            suffix = remainder[0]
            mod_rel = _norm_rel(f"{owner_dir}Ext/{suffix}.bsl")
            if mod_rel in path_set:
                profile["module_origins"].append((mod_rel, suffix))

    out: Dict[str, ImportObjectProfile] = {}
    for rel_xml, raw in profiles.items():
        child_metadata = {
            key: sorted(set(values), key=lambda v: v.lower())
            for key, values in raw["child_metadata"].items()
        }
        out[rel_xml] = ImportObjectProfile(
            rel_xml=rel_xml,
            forms=sorted(set(raw["forms"]), key=str.lower),
            commands=sorted(set(raw["commands"]), key=str.lower),
            layouts=sorted(set(raw["layouts"]), key=str.lower),
            module_origins=sorted(set(raw["module_origins"]), key=lambda item: item[0].lower()),
            child_metadata=child_metadata,
            form_specs=[
                FormImportSpec(**spec)
                for _, spec in sorted(raw["form_specs"].items(), key=lambda item: item[0].lower())
            ],
            command_specs=[
                CommandImportSpec(
                    rel_xml=spec["rel_xml"],
                    module_origins=list(spec["module_origins"]),
                    dump_info_id=spec["dump_info_id"],
                )
                for _, spec in sorted(raw["command_specs"].items(), key=lambda item: item[0].lower())
            ],
            layout_specs=[
                LayoutImportSpec(**spec)
                for _, spec in sorted(raw["layout_specs"].items(), key=lambda item: item[0].lower())
            ],
        )
    return out


def _binding_from_data_path(data_path: str) -> str:
    data_path = str(data_path or "").strip()
    if not data_path:
        return ""
    part = data_path.split(".")[-1]
    return part.strip()


def _field_type_from_input(node: ET.Element) -> str:
    data_path = _find_child_text(node, "DataPath", "")
    binding = _binding_from_data_path(data_path).lower()
    name = str(node.attrib.get("name") or "").strip().lower()
    if _find_child_bool(node, "MultiLine", False):
        return "TextArea"
    if "date" in binding or "date" in name or "дата" in binding or "дата" in name:
        return "DateBox"
    # Document numbers and external reference numbers can contain letters.
    # A name containing "number" is not evidence of a numeric data type.
    return "TextBox"


def _form_node_title(node: ET.Element, default: str = "") -> str:
    return _local_string_value(node.find("./{*}Title")) or str(default or "")


_ONEC_FORM_CONTROL_UUID = "02023637-7868-4a5f-8576-835a76e0c9ba"


def _serialized_localized_text(value: Any, default: str = "") -> str:
    translations: Dict[str, str] = {}

    def visit(current: Any) -> None:
        if not isinstance(current, list):
            return
        if len(current) >= 2:
            lang = str(current[0] or "").strip().lower()
            content = str(current[1] or "").strip() if not isinstance(current[1], list) else ""
            if lang in {"uk", "en", "ru"} and content:
                translations.setdefault(lang, content)
        for child in current:
            visit(child)

    visit(value)
    return translations.get("uk") or translations.get("en") or translations.get("ru") or str(default or "")


def _serialized_form_control_name(node: Any) -> str:
    if not isinstance(node, list) or not node:
        return ""
    marker = str(node[0] or "")
    candidate_indexes = (6, 7) if marker in {"25", "48"} else (7, 6)
    for index in candidate_indexes:
        if index >= len(node) or isinstance(node[index], list):
            continue
        value = str(node[index] or "").strip()
        if value and not value.lstrip("-").isdigit():
            return value
    return ""


def _is_serialized_form_control(value: Any) -> bool:
    return bool(
        isinstance(value, list)
        and len(value) > 7
        and isinstance(value[1], list)
        and len(value[1]) > 1
        and str(value[1][1] or "").strip().lower() == _ONEC_FORM_CONTROL_UUID
    )


def _serialized_form_children(node: Any) -> List[List[Any]]:
    if not isinstance(node, list):
        return []
    children: List[List[Any]] = []
    for value in node:
        if not _is_serialized_form_control(value):
            continue
        name = _serialized_form_control_name(value)
        low = name.casefold()
        if low.endswith(("extendedtooltip", "расширеннаяподсказка", "контекстноеменю", "contextmenu")):
            continue
        if any(token in low for token in ("строкапоиска", "состояниепросмотра", "управлениепоиском")):
            continue
        children.append(value)
    return children


def _serialized_control_id(node: List[Any], name: str, prefix: str) -> str:
    raw_id = ""
    if len(node) > 1 and isinstance(node[1], list) and node[1]:
        raw_id = str(node[1][0] or "").strip()
    safe_id = re.sub(r"[^0-9A-Za-z_-]+", "_", raw_id or name or prefix).strip("_")
    return f"{prefix}_{safe_id or 'control'}"


def _serialized_field_type(node: List[Any], name: str) -> str:
    mode = ""
    if len(node) > 6 and not isinstance(node[6], list):
        mode = str(node[6] or "").strip()
    low = name.casefold()
    if mode == "3":
        return "CheckBox"
    if mode == "4":
        return "Picture"
    if mode == "5":
        return "ComboBox"
    if "дата" in low or "date" in low:
        return "DateBox"
    if "сумм" in low or "кількіст" in low or "количеств" in low:
        return "NumberBox"
    return "TextBox"


def build_onec_form_model_from_serialized(
    *,
    form_name: str,
    form_title: str,
    owner_title: str,
    obj_type: str,
    serialized_form: bytes,
) -> Tuple[Dict[str, Any], str]:
    """Build an editable form model from the brace stream stored in Config.* files."""

    del owner_title
    text = bytes(serialized_form or b"").decode("utf-8-sig", errors="replace")
    root_value = _BraceValueParser(text).parse_value()
    if not isinstance(root_value, list) or len(root_value) < 2 or not isinstance(root_value[1], list):
        raise ValueError("Unsupported serialized 1C form structure")
    form_data = root_value[1]

    command_titles: Dict[str, str] = {}
    if len(root_value) > 5 and isinstance(root_value[5], list):
        for value in root_value[5]:
            if not isinstance(value, list) or len(value) < 4:
                continue
            name = str(value[2] or "").strip() if not isinstance(value[2], list) else ""
            if name:
                command_titles[name] = _serialized_localized_text(value[3], name)

    form_kind = "object_form"

    def build_node(node: List[Any], *, table_binding: str = "") -> Optional[Dict[str, Any]]:
        nonlocal form_kind
        marker = str(node[0] or "")
        name = _serialized_form_control_name(node)
        if not name:
            return None
        props: Dict[str, Any] = {
            "visible": str(node[4] if len(node) > 4 else "1") != "0",
            "designer_name": name,
        }

        if marker == "19":
            mode = str(node[6] or "") if len(node) > 6 and not isinstance(node[6], list) else ""
            title_value = node[8] if len(node) > 8 else None
            title = _serialized_localized_text(title_value, name)
            group_props = node[21] if len(node) > 21 and isinstance(node[21], list) else []
            children = [
                child
                for raw_child in _serialized_form_children(node)
                if (child := build_node(raw_child, table_binding=table_binding)) is not None
            ]
            if mode == "9":
                props["layout"] = "horizontal"
                return {
                    "id": _serialized_control_id(node, name, "bar"),
                    "name": name,
                    "title": title,
                    "type": "Container",
                    "props": props,
                    "children": children,
                }
            if mode == "3":
                props["pages_representation"] = "TabsOnTop"
                return {
                    "id": _serialized_control_id(node, name, "pages"),
                    "name": name,
                    "title": title,
                    "type": "Tabs",
                    "props": props,
                    "children": children,
                }
            # Ordinary-group layout and chrome are stored in the nested
            # group-property record, not in the control mode. Mode 5 is used
            # for both horizontal and vertical groups.
            orientation = str(group_props[1] or "") if len(group_props) > 1 else ""
            props["layout"] = "horizontal" if orientation == "1" else "vertical"
            representation_code = str(group_props[3] or "") if len(group_props) > 3 else ""
            props["representation"] = {
                "0": "None",
                "1": "WeakSeparation",
                "2": "Usual",
                "3": "NormalSeparation",
                "4": "StrongSeparation",
            }.get(representation_code, "Usual")
            props["show_title"] = (
                str(group_props[4] or "") != "0" if len(group_props) > 4 else bool(title)
            )
            if mode == "4":
                props["page"] = True
            return {
                "id": _serialized_control_id(node, name, "group"),
                "name": name,
                "title": title,
                "type": "Container",
                "props": props,
                "children": children,
            }

        if marker == "48":
            binding = name
            controls = _serialized_form_children(node)
            command_bar = next(
                (
                    built
                    for child in controls
                    if str(child[0] or "") == "19"
                    and len(child) > 6
                    and str(child[6] or "") == "9"
                    and (built := build_node(child, table_binding=binding)) is not None
                ),
                None,
            )
            columns: List[Dict[str, Any]] = []
            for child in controls:
                if str(child[0] or "") != "32":
                    continue
                data_path = child[12] if len(child) > 12 else None
                if not isinstance(data_path, list) or not data_path or str(data_path[0] or "") == "0":
                    continue
                column_name = _serialized_form_control_name(child)
                if not column_name:
                    continue
                local_binding = column_name
                if local_binding.casefold().startswith(binding.casefold()) and len(local_binding) > len(binding):
                    local_binding = local_binding[len(binding):]
                if local_binding.casefold() in {"номерстроки", "linenumber"}:
                    local_binding = "LineNumber"
                columns.append(
                    {
                        "name": column_name,
                        "designer_name": column_name,
                        "title": _serialized_localized_text(child[10] if len(child) > 10 else None, local_binding),
                        "binding": local_binding,
                    }
                )
            table = {
                "id": _serialized_control_id(node, name, "table"),
                "name": name,
                "title": name,
                "type": "Table",
                "binding": "items" if name.casefold() in {"список", "list"} else binding,
                "props": {**props, "columns": columns},
                "children": [],
            }
            if name.casefold() in {"список", "list"} and obj_type != "document":
                form_kind = "list_form"
            if command_bar is None:
                return table
            return {
                "id": _serialized_control_id(node, name, "wrap"),
                "name": name,
                "title": name,
                "type": "Container",
                "props": {"layout": "vertical", "visible": props["visible"]},
                "children": [command_bar, table],
            }

        if marker == "25":
            title = command_titles.get(name) or name
            return {
                "id": _serialized_control_id(node, name, "button"),
                "name": name,
                "title": title,
                "type": "Button",
                "props": props,
                "children": [],
            }

        if marker == "32":
            binding = name
            if table_binding and binding.casefold().startswith(table_binding.casefold()) and len(binding) > len(table_binding):
                binding = binding[len(table_binding):]
            return {
                "id": _serialized_control_id(node, name, "field"),
                "name": name,
                "title": _serialized_localized_text(node[10] if len(node) > 10 else None, binding),
                "type": _serialized_field_type(node, name),
                "binding": binding,
                "props": props,
                "children": [],
            }

        if marker == "8":
            is_picture = len(node) > 6 and str(node[6] or "") == "1"
            title = _serialized_localized_text(node[8] if len(node) > 8 else None, "")
            if not is_picture:
                props.update(
                    {
                        "is_decoration": True,
                        "decoration_kind": "label",
                        "layout_spacer": not bool(title.strip()),
                    }
                )
            return {
                "id": _serialized_control_id(node, name, "label"),
                "name": name,
                "title": title,
                "type": "Picture" if is_picture else "Label",
                "props": props,
                "children": [],
            }
        return None

    root_children = [
        child
        for raw_child in _serialized_form_children(form_data)
        if (child := build_node(raw_child)) is not None
    ]
    if not root_children:
        raise ValueError("Serialized 1C form contains no supported controls")
    return (
        {
            "schema_version": 1,
            "title": str(form_title or form_name),
            "form_kind": form_kind,
            "root": {
                "id": "root",
                "name": str(form_name or ""),
                "title": str(form_title or form_name),
                "type": "Container",
                "props": {"layout": "vertical"},
                "children": root_children,
            },
        },
        form_kind,
    )


def build_onec_form_model_from_xml(
    *,
    form_name: str,
    form_title: str,
    owner_title: str,
    obj_type: str,
    ext_form_xml: bytes,
) -> Tuple[Dict[str, Any], str]:
    del owner_title
    raw = bytes(ext_form_xml or b"")
    stripped = raw.lstrip(b"\xef\xbb\xbf\x00\t\r\n ")
    if stripped.startswith(b"{"):
        return build_onec_form_model_from_serialized(
            form_name=form_name,
            form_title=form_title,
            owner_title="",
            obj_type=obj_type,
            serialized_form=raw,
        )
    if raw.startswith(b"MOXCEL"):
        raise ValueError("Unsupported legacy 1C MOXCEL form body")
    if not stripped.startswith(b"<"):
        raise ValueError("Unsupported binary 1C form body")
    root = ET.fromstring(raw or b"<Form/>")
    commands: Dict[str, str] = {}
    for cmd in root.findall(".//{*}Commands/{*}Command"):
        name = str(cmd.attrib.get("name") or "").strip()
        if not name:
            continue
        commands[name] = _form_node_title(cmd, name)

    form_kind = "object_form"

    def build_button(node: ET.Element) -> Dict[str, Any]:
        command_name = _find_child_text(node, "CommandName", "")
        command_key = command_name.split(".")[-1] if command_name else ""
        title = commands.get(command_key) or command_key or str(node.attrib.get("name") or "Button")
        props = _collect_node_props(node, skip={"child_items", "title"})
        return {
            "id": f"button_{node.attrib.get('id') or node.attrib.get('name') or 'btn'}",
            "name": str(node.attrib.get("name") or ""),
            "title": title,
            "type": "Button",
            "props": props,
            "children": [],
        }

    def build_table(node: ET.Element) -> Dict[str, Any]:
        nonlocal form_kind
        data_path = _find_child_text(node, "DataPath", "")
        binding = _binding_from_data_path(data_path)
        props = _collect_node_props(node, skip={"child_items", "title"})
        props.setdefault("columns", [])
        table = {
            "id": f"table_{node.attrib.get('id') or node.attrib.get('name') or 'table'}",
            "name": str(node.attrib.get("name") or ""),
            "title": _form_node_title(node, str(node.attrib.get("name") or "")),
            "type": "Table",
            "binding": "items" if data_path.startswith("Список") else binding,
            "props": props,
            "children": [],
        }
        for child in node.findall("./{*}ChildItems/*"):
            col_binding = _binding_from_data_path(_find_child_text(child, "DataPath", ""))
            if col_binding:
                table["props"]["columns"].append(
                    {
                        "title": _form_node_title(child, col_binding),
                        "binding": col_binding,
                    }
                )
        if _find_child_text(node, "Representation", "") == "List" and data_path.startswith("Список") and obj_type != "document":
            form_kind = "list_form"
        auto_bar = node.find("./{*}AutoCommandBar")
        if auto_bar is not None:
            wrap = {
                "id": f"wrap_{node.attrib.get('id') or node.attrib.get('name') or 'table'}",
                "name": str(node.attrib.get("name") or ""),
                "title": _form_node_title(node, str(node.attrib.get("name") or "")),
                "type": "Container",
                "props": {"layout": "vertical"},
                "children": [build_node(auto_bar), table],
            }
            return wrap
        return table

    def build_node(node: ET.Element) -> Dict[str, Any]:
        tag = _tag_name(node.tag)
        name = str(node.attrib.get("name") or "").strip()
        title = _form_node_title(node, name or tag)
        if tag in {"UsualGroup", "Page", "ButtonGroup"}:
            layout = "horizontal" if _find_child_text(node, "Group", "").lower() == "horizontal" else "vertical"
            props = _collect_node_props(node, skip={"child_items", "title"})
            props.update(
                {
                    "layout": layout,
                    "representation": _find_child_text(node, "Representation", ""),
                    "show_title": _find_child_bool(node, "ShowTitle", True),
                }
            )
            return {
                "id": f"group_{node.attrib.get('id') or name or tag}",
                "name": name,
                "title": title,
                "type": "Container",
                "props": props,
                "children": [build_node(child) for child in node.findall("./{*}ChildItems/*")],
            }
        if tag == "Pages":
            props = _collect_node_props(node, skip={"child_items", "title"})
            props.setdefault("pages_representation", _find_child_text(node, "PagesRepresentation", "TabsOnTop"))
            return {
                "id": f"pages_{node.attrib.get('id') or name or 'pages'}",
                "name": name,
                "title": title,
                "type": "Tabs",
                "props": props,
                "children": [build_node(child) for child in node.findall("./{*}ChildItems/{*}Page")],
            }
        if tag in {"AutoCommandBar", "CommandBar"}:
            props = _collect_node_props(node, skip={"child_items", "title"})
            props.setdefault("layout", "horizontal")
            bar_children = []
            for child in node.findall("./{*}ChildItems/*"):
                if _tag_name(child.tag) == "Button":
                    bar_children.append(build_button(child))
            return {
                "id": f"bar_{node.attrib.get('id') or name or 'bar'}",
                "name": name,
                "title": title,
                "type": "Container",
                "props": props,
                "children": bar_children,
            }
        if tag == "Button":
            return build_button(node)
        if tag == "Table":
            return build_table(node)
        if tag == "InputField":
            props = _collect_node_props(node, skip={"child_items", "title"})
            props.setdefault("width_chars", _find_child_int(node, "Width", 0))
            props.setdefault("title_location", _find_child_text(node, "TitleLocation", "Left"))
            return {
                "id": f"field_{node.attrib.get('id') or name or 'field'}",
                "name": name,
                "title": title,
                "type": _field_type_from_input(node),
                "binding": _binding_from_data_path(_find_child_text(node, "DataPath", "")),
                "props": props,
                "children": [],
            }
        if tag == "CheckBoxField":
            props = _collect_node_props(node, skip={"child_items", "title"})
            return {
                "id": f"checkbox_{node.attrib.get('id') or name or 'checkbox'}",
                "name": name,
                "title": title,
                "type": "CheckBox",
                "binding": _binding_from_data_path(_find_child_text(node, "DataPath", "")),
                "props": props,
                "children": [],
            }
        if tag in {"LabelField", "LabelDecoration"}:
            props = _collect_node_props(node, skip={"child_items", "title"})
            if tag == "LabelDecoration":
                title = _form_node_title(node, "")
                props.update(
                    {
                        "is_decoration": True,
                        "decoration_kind": "label",
                        "layout_spacer": not bool(title.strip()),
                    }
                )
                props.setdefault("width_chars", _find_child_int(node, "Width", 0))
                props.setdefault("height_rows", _find_child_int(node, "Height", 0))
            return {
                "id": f"label_{node.attrib.get('id') or name or 'label'}",
                "name": name,
                "title": title,
                "type": "Label",
                "binding": _binding_from_data_path(_find_child_text(node, "DataPath", "")),
                "props": props,
                "children": [],
            }
        if tag in {"SpreadSheetDocumentField", "HTMLDocumentField", "FormattedDocumentField", "TextDocumentField"}:
            props = _collect_node_props(node, skip={"child_items", "title"})
            props.setdefault("read_only", _find_child_bool(node, "ReadOnly", True))
            return {
                "id": f"doc_{node.attrib.get('id') or name or 'doc'}",
                "name": name,
                "title": title,
                "type": "TextArea",
                "binding": _binding_from_data_path(_find_child_text(node, "DataPath", "")),
                "props": props,
                "children": [],
            }
        props = _collect_node_props(node, skip={"child_items", "title"})
        props.setdefault("layout", "vertical")
        return {
            "id": f"node_{node.attrib.get('id') or name or tag}",
            "name": name,
            "title": title,
            "type": "Container",
            "props": props,
            "children": [build_node(child) for child in node.findall("./{*}ChildItems/*")],
        }

    root_children: List[Dict[str, Any]] = []
    for child in root.findall("./{*}ChildItems/*"):
        root_children.append(build_node(child))
    for child in root.findall("./{*}AutoCommandBar"):
        root_children.insert(0, build_node(child))

    model = {
        "schema_version": 1,
        "title": str(form_title or form_name),
        "form_kind": form_kind,
        "root": {
            "id": "root",
            "name": str(form_name or ""),
            "title": str(form_title or form_name),
            "type": "Container",
            "props": {"layout": "vertical"},
            "children": root_children,
        },
    }
    window_opening_mode = _find_child_text(root, "WindowOpeningMode", "")
    if window_opening_mode:
        # In managed 1C forms these values describe a separate blocking
        # window. Placement and locking remain separate MetaPlatform props so
        # a developer may later choose a non-modal independent window.
        model["root"]["props"]["open_mode"] = "window"
        model["root"]["props"]["window_lock_mode"] = normalize_form_window_lock_mode(
            window_opening_mode
        )
        model["root"]["props"]["source_window_opening_mode"] = window_opening_mode
    return model, form_kind


# ------------------------------------------------------------
# Legacy importer (kept for compatibility)
# ------------------------------------------------------------


class OneCConfigImporter:
    """Legacy importer that extracts minimal structure only.

    Kept for compatibility with earlier scripts.
    New code should use tools.onec_import.import_onec_configuration which performs
    a deep import (raw assets + manifest objects).
    """

    FOLDER_MAP = {
        "Catalogs": "catalog",
        "Documents": "document",
        "Enums": "enumeration",
        "Reports": "report",
        "DataProcessors": "data_processor",
    }

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir)

    def import_config(self) -> MPXConfig:
        cfg = MPXConfig(objects=[])

        for folder, obj_type in self.FOLDER_MAP.items():
            p = self.root_dir / folder
            if not p.exists() or not p.is_dir():
                continue

            for xml_file in p.glob("*.xml"):
                name = xml_file.stem
                title = name
                try:
                    name2, title2, _uid = parse_basic_xml_fields(xml_file.read_bytes())
                    if name2:
                        name = name2
                    if title2:
                        title = title2
                except Exception:
                    pass

                cfg.objects.append(
                    MPXObject(
                        obj_type=obj_type,
                        name=name,
                        title=title,
                        parent_uid="",
                        subsystems=[],
                        origin=str(xml_file.relative_to(self.root_dir).as_posix()),
                    )
                )

        return cfg


# ------------------------------------------------------------
# Deep import execution
# ------------------------------------------------------------


def ensure_object_section_folder(db: Mpdb, *, parent_guid: str, parent_type: str, section_key: str, order: int) -> str:
    """Ensure a system folder (forms/commands/layouts) exists inside object."""
    guid = manifest_io.sys_object_folder_guid(parent_guid=parent_guid, section_key=section_key)
    manifest_io._insert_raw_if_missing(  # type: ignore[attr-defined]
        db,
        {
            "guid": guid,
            "type": parent_type,
            "name": section_key,
            "title": section_key,
            "kind": "folder",
            "parent_guid": parent_guid,
            "payload": {
                "system": True,
                "protected": True,
                "auto": True,
                "menu": "add_only",
                "order": order,
            },
        },
    )
    return guid


def import_manifest_objects(
    db: Mpdb,
    source: OneCSource,
    paths: Sequence[str],
    *,
    raw_prefix: str = "onec_raw/",
    store_raw_asset_keys: bool = False,
    store_picture_assets: bool = False,
    store_modules_in_table: bool = True,
    progress: Callable[[int, int, str], None] | None = None,
) -> Dict[str, str]:
    """Create manifest objects based on discovered 1C metadata.

    Returns mapping rel_xml -> created object guid.
    """

    objs = manifest_io.list_objects(db, hydrate_payload=False)
    path_set = {str(p or "") for p in paths}

    group_by_type: Dict[str, str] = {o.type: o.guid for o in objs if o.kind == "group"}
    common_group_guid = group_by_type.get("common", "")
    common_folder_by_name: Dict[str, str] = {
        o.name: o.guid
        for o in objs
        if o.kind == "folder" and o.type == "common" and o.parent_guid == common_group_guid
    }
    common_modules_by_name: Dict[str, Any] = {
        str(o.name or "").strip().lower(): o
        for o in objs
        if o.kind == "object" and o.type == "common_module"
    }

    # Build plan
    dump_info_plan: List[ImportObjectSpec] = []
    dump_profiles: Dict[str, ImportObjectProfile] = {}
    if "ConfigDumpInfo.xml" in path_set:
        dump_info_plan = build_import_plan_from_dump_info(source, paths)
        if dump_info_plan:
            dump_profiles = build_import_profiles_from_dump_info(source, paths, dump_info_plan)
    base_plan = build_import_plan(paths)
    if dump_info_plan:
        plan = merge_import_plans(base_plan, dump_info_plan)
    else:
        plan = base_plan

    fallback_forms_by_owner: Dict[str, List[str]] = {}
    fallback_commands_by_owner: Dict[str, List[str]] = {}
    fallback_layouts_by_owner: Dict[str, List[str]] = {}
    for rel in path_set:
        if not str(rel or "").lower().endswith(".xml"):
            continue
        parts = str(rel).split("/")
        if len(parts) >= 4 and parts[-2] == "Forms":
            owner_prefix = "/".join(parts[:-2]) + "/"
            fallback_forms_by_owner.setdefault(owner_prefix, []).append(rel)
        elif len(parts) >= 4 and parts[-2] == "Commands":
            owner_prefix = "/".join(parts[:-2]) + "/"
            fallback_commands_by_owner.setdefault(owner_prefix, []).append(rel)
        elif len(parts) >= 4 and parts[-2] in ("Templates", "Layouts"):
            owner_prefix = "/".join(parts[:-2]) + "/"
            fallback_layouts_by_owner.setdefault(owner_prefix, []).append(rel)

    for mapping in (fallback_forms_by_owner, fallback_commands_by_owner, fallback_layouts_by_owner):
        for key, values in list(mapping.items()):
            mapping[key] = sorted(set(values), key=str.lower)

    # First pass: create non-dependent objects, plus remember subsystems for second pass
    guid_by_xml: Dict[str, str] = {}
    payload_updates_by_guid: Dict[str, Dict[str, Any]] = {}
    pending_objects: List[Any] = []
    pending_object_by_guid: Dict[str, Any] = {}
    pending_module_rows: List[Dict[str, Any]] = []
    startup_module_guids: list[str] = []
    root_module_refs: Dict[str, str] = {}
    queued_folder_guids: set[str] = set()
    stage_labels = {
        "object": "Object",
        "forms": "Forms",
        "form_modules": "Form modules",
        "commands": "Commands",
        "command_modules": "Command modules",
        "layouts": "Templates",
        "object_modules": "Object modules",
    }

    def emit_progress(current: int, total: int, message: str) -> None:
        if progress is None:
            return
        try:
            progress(int(current), int(total), str(message or ""))
        except Exception:
            pass

    def queue_manifest_object(
        *,
        obj_type: str,
        name: str,
        title: str,
        parent_guid: str,
        payload: Optional[Dict[str, Any]] = None,
        kind: str = "object",
        guid: str | None = None,
    ) -> Any:
        mo = manifest_io.make_object(
            obj_type=obj_type,
            name=name,
            title=title,
            parent_guid=parent_guid,
            payload=payload,
            kind=kind,
            guid=guid,
        )
        pending_objects.append(mo)
        pending_object_by_guid[str(mo.guid or "").strip()] = mo
        return mo

    def queue_payload_update(*, guid: str, payload: Optional[Dict[str, Any]]) -> None:
        obj_guid = str(guid or "").strip()
        if not obj_guid:
            return
        # Callers commonly mutate ``mo.payload`` and pass that same dict back.
        # Snapshot it before clearing the pending object or all fields vanish.
        updated_payload = dict(payload or {})
        pending = pending_object_by_guid.get(obj_guid)
        if pending is not None and isinstance(getattr(pending, "payload", None), dict):
            pending.payload.clear()
            pending.payload.update(updated_payload)
            return
        payload_updates_by_guid[obj_guid] = updated_payload

    def queue_section_folder(*, parent_guid: str, parent_type: str, section_key: str, order: int) -> str:
        guid = manifest_io.sys_object_folder_guid(parent_guid=parent_guid, section_key=section_key)
        if guid in queued_folder_guids:
            return guid
        queued_folder_guids.add(guid)
        queue_manifest_object(
            guid=guid,
            obj_type=parent_type,
            name=section_key,
            title=section_key,
            parent_guid=parent_guid,
            kind="folder",
            payload={
                "system": True,
                "protected": True,
                "auto": True,
                "menu": "add_only",
                "order": int(order),
            },
        )
        return guid

    def disambiguate_localized_module_refs() -> None:
        """Make every localized executable reference deterministic and unique.

        Synonyms are presentation text and are not unique in real 1C dumps
        (for example, many device modules are all titled "Driver handler").
        Keep the readable alias, but qualify every colliding owner with a
        stable fragment of its source GUID.
        """

        for field, lang in (("ref_uk", "uk"), ("ref_en", "en")):
            groups: Dict[str, List[Dict[str, Any]]] = {}
            for row in pending_module_rows:
                reference = str(row.get(field) or "").strip()
                if reference:
                    groups.setdefault(reference.casefold(), []).append(row)
            for rows in groups.values():
                if len(rows) < 2:
                    continue
                for row in rows:
                    reference = str(row.get(field) or "").strip()
                    parts = reference.split(".")
                    if len(parts) < 2:
                        continue
                    owner_index = -2
                    suffix = str(row.get("owner_guid") or "").replace("-", "")[:8]
                    if not suffix:
                        continue
                    old_owner_ref = ".".join(parts[:-1])
                    parts[owner_index] = f"{parts[owner_index]}_{suffix}"
                    row[field] = ".".join(parts)

                    pending = pending_object_by_guid.get(str(row.get("owner_guid") or "").strip())
                    payload = getattr(pending, "payload", None) if pending is not None else None
                    if not isinstance(payload, dict):
                        continue
                    refs = payload.get("code_refs") if isinstance(payload.get("code_refs"), dict) else {}
                    if str(payload.get(f"code_ref_{lang}") or refs.get(lang) or "") != old_owner_ref:
                        continue
                    updated_refs = dict(refs)
                    updated_refs[lang] = ".".join(parts[:-1])
                    payload["code_refs"] = updated_refs
                    payload[f"code_ref_{lang}"] = updated_refs[lang]

    def generate_default_ui_children_if_needed(
        *,
        owner_guid: str,
        owner_type: str,
        owner_name: str,
        owner_title: str,
        owner_payload: Dict[str, Any],
        has_forms: bool,
        has_commands: bool,
    ) -> Dict[str, str]:
        default_form_guids: Dict[str, str] = {}
        owner_type_norm = str(owner_type or "").strip().lower()
        if owner_type_norm not in {"catalog", "document"}:
            return default_form_guids

        owner_ref = metadata_ref_for_manifest_object(
            obj_type=owner_type_norm,
            name=owner_name,
            origin_path=spec.rel_xml,
        )

        if not has_commands:
            defaults: list[dict[str, Any]] = []
            seen_codes: set[str] = set()
            for ctx in ("list_form", "object_form"):
                for item in default_commands_for_context(obj_type=owner_type_norm, context=ctx):
                    code = str(item.get("code") or "").strip()
                    if not code or code in seen_codes:
                        continue
                    defaults.append(item)
                    seen_codes.add(code)

            if defaults:
                commands_folder_guid = queue_section_folder(
                    parent_guid=owner_guid,
                    parent_type=owner_type_norm,
                    section_key="commands",
                    order=20,
                )
                for item in defaults:
                    code = str(item.get("code") or "").strip()
                    if not code:
                        continue
                    title = item.get("title")
                    title_uk = code
                    if isinstance(title, dict):
                        title_uk = str(title.get("uk") or title.get("en") or code).strip() or code
                    elif title:
                        title_uk = str(title).strip() or code
                    payload = dict(item)
                    payload.setdefault("owner_guid", owner_guid)
                    queue_manifest_object(
                        obj_type="command",
                        name=to_ascii_identifier(f"cmd_{code.lower()}"),
                        title=title_uk,
                        parent_guid=commands_folder_guid,
                        payload=payload,
                        kind="object",
                    )

        if has_forms:
            return default_form_guids

        forms_folder_guid = queue_section_folder(
            parent_guid=owner_guid,
            parent_type=owner_type_norm,
            section_key="forms",
            order=10,
        )
        attrs = owner_payload.get("attributes") if isinstance(owner_payload, dict) else None

        list_model = build_list_form_model(
            form_name="ListForm",
            owner_title=str(owner_title or ""),
            attributes=attrs,
            commands=default_commands_for_context(obj_type=owner_type_norm, context="list_form"),
        )
        object_model = build_object_form_model(
            form_name="ObjectForm",
            owner_title=str(owner_title or ""),
            attributes=attrs,
            commands=default_commands_for_context(obj_type=owner_type_norm, context="object_form"),
        )

        list_name = "list_form1"
        object_name = "object_form1"
        list_form = queue_manifest_object(
            obj_type="form",
            name=list_name,
            title="Форма списку",
            parent_guid=forms_folder_guid,
            payload={
                "user_created": True,
                "subtype": "list_form",
                "owner_guid": owner_guid,
                "form_model": list_model,
                "form_module": "",
            },
            kind="object",
        )
        default_form_guids["list_form"] = str(list_form.guid or "")
        object_form = queue_manifest_object(
            obj_type="form",
            name=object_name,
            title="Форма об'єкта",
            parent_guid=forms_folder_guid,
            payload={
                "user_created": True,
                "subtype": "object_form",
                "owner_guid": owner_guid,
                "form_model": object_model,
                "form_module": "",
            },
            kind="object",
        )
        default_form_guids["object_form"] = str(object_form.guid or "")

        if owner_ref:
            updated_payload = dict(owner_payload or {})
            updated_payload.setdefault("default_list_form", f"{owner_ref}.Form.{list_name}")
            updated_payload.setdefault("default_object_form", f"{owner_ref}.Form.{object_name}")
            queue_payload_update(guid=owner_guid, payload=updated_payload)

        return default_form_guids

    def make_imported_module_guid(
        *,
        owner_guid: str,
        owner_kind: str,
        module_kind: str,
        name: str,
        text: str,
        origin: str,
        owner_name: str = "",
        owner_title_uk: str = "",
        owner_title_en: str = "",
    ) -> str:
        if not store_modules_in_table:
            return ""
        try:
            from src.configurator.persistence.modules_dao import make_module_row

            refs = module_refs_from_import_origin(
                origin,
                module_kind=module_kind,
                owner_name=owner_name or name,
                owner_title_uk=owner_title_uk,
                owner_title_en=owner_title_en,
            )
            row = make_module_row(
                owner_guid=owner_guid,
                owner_kind=owner_kind,
                module_kind=module_kind,
                name=name,
                text=text,
                lang="",
                updated_by="import",
                **refs,
            )
            pending_module_rows.append(row)
            return str(row.get("module_guid") or "")
        except Exception:
            return ""

    def read_module_text(rel: str) -> str:
        try:
            return normalize_module_text(_decode_text(source.read_bytes(rel)), language="uk").text
        except Exception:
            return ""

    def ensure_configuration_module(
        *,
        file_name: str,
        object_name: str,
        object_title: str,
        fixed_guid: str | None,
    ) -> None:
        rel = _norm_rel(f"Ext/{file_name}")
        if rel not in path_set:
            return

        common_modules_folder = common_folder_by_name.get("common_modules", GUID_FOLDER_COMMON_MODULES)
        existing = common_modules_by_name.get(object_name.strip().lower())
        payload: Dict[str, Any] = dict(getattr(existing, "payload", {}) or {})
        imported_payload = dict(payload.get("imported") or {})
        imported_payload.update({"source": "1c", "origin": rel})
        if store_raw_asset_keys:
            imported_payload["raw_asset"] = f"{raw_prefix}{rel}"
        payload["imported"] = imported_payload

        if existing is not None:
            owner_guid = str(existing.guid or "").strip()
        else:
            created = queue_manifest_object(
                guid=fixed_guid,
                obj_type="common_module",
                name=object_name,
                title=object_title,
                parent_guid=common_modules_folder,
                payload=payload,
                kind="object",
            )
            owner_guid = str(created.guid or "").strip()
            common_modules_by_name[object_name.strip().lower()] = created

        module_text = read_module_text(rel)

        module_kind = Path(file_name).stem
        module_refs = module_refs_from_import_origin(
            rel,
            module_kind=module_kind,
            owner_name=object_name,
            owner_title_uk=object_title,
        )
        module_guid = make_imported_module_guid(
            owner_guid=owner_guid,
            owner_kind="common_module",
            module_kind=module_kind,
            name=object_name,
            text=module_text,
            origin=rel,
            owner_name=object_name,
            owner_title_uk=object_title,
        )
        if not module_guid:
            module_guid = make_fallback_module_guid(owner_guid, module_kind, rel)
        payload["module"] = {
            "asset_key": f"module://{module_guid}",
            "mime": "text/plain",
        }
        payload["code_refs"] = {
            lang: str(module_refs.get(f"ref_{lang}") or "").rsplit(".", 1)[0]
            for lang in ("uk", "en")
        }
        payload["code_ref_uk"] = payload["code_refs"]["uk"]
        payload["code_ref_en"] = payload["code_refs"]["en"]
        queue_payload_update(guid=owner_guid, payload=payload)
        root_module_refs[file_name] = owner_guid
        if owner_guid not in startup_module_guids and module_text.strip():
            startup_module_guids.append(owner_guid)
        guid_by_xml[rel] = owner_guid

    def resolve_parent(spec: ImportObjectSpec) -> str:
        if spec.parent_kind == "group":
            return group_by_type.get(spec.parent_key, "")
        if spec.parent_kind == "common_folder":
            return common_folder_by_name.get(spec.parent_key, "")
        if spec.parent_kind == "subsystem_parent":
            return guid_by_xml.get(spec.parent_key, common_folder_by_name.get("subsystems", ""))
        return ""

    def progress_scope(spec: ImportObjectSpec) -> str:
        rel = str(spec.rel_xml or "")
        return posixpath.splitext(rel)[0] if rel.lower().endswith(".xml") else rel

    def emit_stage_progress(spec: ImportObjectSpec, stage_key: str, current: int, total: int) -> None:
        emit_progress(
            current,
            total,
            f"Import manifest: {progress_scope(spec)} -> {stage_labels.get(stage_key, stage_key)}",
        )

    # Diagnostic output to help trace import issues
    print(f"[import_manifest_objects] plan specs: {len(plan)}", flush=True)
    print(f"[import_manifest_objects] group_by_type keys: {list(group_by_type.keys())}", flush=True)
    if plan:
        skipped_no_parent = sum(1 for s in plan if not resolve_parent(s))
        print(f"[import_manifest_objects] specs skipped (no parent): {skipped_no_parent}", flush=True)
        print(f"[import_manifest_objects] sample: {[(s.obj_type, s.parent_key, s.rel_xml) for s in plan[:3]]}", flush=True)

    for file_name, object_name, object_title, fixed_guid in _CONFIGURATION_ROOT_MODULES:
        ensure_configuration_module(
            file_name=file_name,
            object_name=object_name,
            object_title=object_title,
            fixed_guid=fixed_guid,
        )

    total_specs = max(len(plan), 1)
    for spec_index, spec in enumerate(plan, start=1):
        parent_guid = resolve_parent(spec)
        if not parent_guid:
            # Skip if parent doesn't exist (should not happen for system tree)
            continue

        payload: Dict[str, Any] = {
            "imported": {
                "source": "1c",
                "origin": spec.rel_xml,
            }
        }
        profile = dump_profiles.get(spec.rel_xml)
        if profile and profile.child_metadata:
            payload["dump_info_children"] = dict(profile.child_metadata)

        if store_raw_asset_keys:
            payload["imported"]["raw_asset"] = f"{raw_prefix}{spec.rel_xml}"

        # Pictures are stored differently
        if spec.obj_type == "common_picture":
            if not store_picture_assets:
                continue
            title = Path(spec.rel_xml).stem
            name = to_ascii_identifier(title)
            payload["picture"] = {
                "asset_key": f"{raw_prefix}{spec.rel_xml}",
                "mime": guess_mime(spec.rel_xml),
            }
            mo = queue_manifest_object(
                obj_type="common_picture",
                name=name,
                title=title,
                parent_guid=parent_guid,
                payload=payload,
                kind="object",
            )
            guid_by_xml[spec.rel_xml] = mo.guid
            emit_stage_progress(spec, "object", spec_index, total_specs)
            continue

        # Regular XML objects
        xml_bytes = b""
        try:
            xml_bytes = source.read_bytes(spec.rel_xml)
        except Exception:
            xml_bytes = b""

        raw_name, raw_title, raw_uid = parse_basic_xml_fields(xml_bytes)
        localized_titles = parse_xml_synonyms(xml_bytes)
        title = raw_title or raw_name or Path(spec.rel_xml).stem
        name = (
            raw_name
            if spec.obj_type == "common_module" and raw_name
            else to_ascii_identifier(raw_name or title)
        )
        if raw_uid:
            payload["imported"]["src_uid"] = raw_uid
        if raw_name:
            payload["source_name"] = raw_name

        # Read 1CD-parsed metadata sidecar (.onec_meta.json) generated by OneCDConfigSource.
        # It contains the real tabular_parts / requisites / attributes from the Config BLOB
        # so that ensure_schema_defaults does not overwrite them with placeholder "Items".
        sidecar_path = _norm_rel(spec.rel_dir_prefix + ".onec_meta.json")
        if sidecar_path in path_set:
            try:
                sidecar_data = json.loads(_decode_text(source.read_bytes(sidecar_path)))
                for _key in ("tabular_parts", "requisites", "attributes", "dimensions", "resources", "enum_values"):
                    _val = sidecar_data.get(_key)
                    if isinstance(_val, list) and _val:
                        payload[_key] = _val
            except Exception:
                pass

        payload = ensure_payload_defaults(payload=payload, obj_type=spec.obj_type)
        payload = ensure_schema_defaults(payload=payload, obj_type=spec.obj_type)

        if spec.obj_type == "subsystem":
            content_refs = _extract_subsystem_content_refs(xml_bytes)
            if content_refs:
                payload["content_refs"] = content_refs
            command_interface_rel = _norm_rel(f"{spec.rel_dir_prefix}Ext/CommandInterface.xml")
            help_rel = _norm_rel(f"{spec.rel_dir_prefix}Ext/Help.xml")
            if command_interface_rel in path_set:
                payload["imported"]["command_interface_origin"] = command_interface_rel
                try:
                    command_interface_model = parse_subsystem_command_interface(
                        source.read_bytes(command_interface_rel)
                    )
                    if command_interface_model:
                        payload["command_interface"] = command_interface_model
                except Exception:
                    pass
            if help_rel in path_set:
                payload["imported"]["help_origin"] = help_rel
                try:
                    help_pages = parse_subsystem_help_pages(source.read_bytes(help_rel))
                    if help_pages:
                        payload["help_pages"] = help_pages
                    help_contents = parse_help_page_contents(
                        source,
                        help_rel=help_rel,
                        help_pages=help_pages,
                        path_set=path_set,
                    )
                    if help_contents:
                        payload["help_contents"] = help_contents
                except Exception:
                    pass

        # Common modules (BSL) are stored as raw assets; we create module nodes that reference them.
        module_origins: list[tuple[str, str]] = list(profile.module_origins) if profile else []
        if not module_origins:
            # Heuristic list of candidate files (we may have more than one module per object).
            candidates: list[tuple[str, str]] = [
                (f"{spec.rel_dir_prefix}Ext/ObjectModule.bsl", "ObjectModule"),
                (f"{spec.rel_dir_prefix}Ext/ManagerModule.bsl", "ManagerModule"),
                (f"{spec.rel_dir_prefix}Ext/RecordSetModule.bsl", "RecordSetModule"),
                (f"{spec.rel_dir_prefix}Ext/ValueManagerModule.bsl", "ValueManagerModule"),
                (f"{spec.rel_dir_prefix}Ext/CommandModule.bsl", "CommandModule"),
                (f"{spec.rel_dir_prefix}Ext/Form/Module.bsl", "FormModule"),
                (f"{posixpath.splitext(spec.rel_xml)[0]}/Ext/Form/Module.bsl", "FormModule"),
                (f"{spec.rel_dir_prefix}Ext/Module.bsl", "Module"),
                (f"{spec.rel_dir_prefix}Module.bsl", "Module"),
                (f"{posixpath.splitext(spec.rel_xml)[0]}.bsl", "Module"),
            ]
            for cand, title_hint in candidates:
                cand = _norm_rel(cand)
                if cand in path_set:
                    module_origins.append((cand, title_hint))

            if module_origins:
                payload.setdefault("imported", {})["module_origins"] = [p for p, _t in module_origins]
                first_origin, first_kind = module_origins[0]
                object_refs = module_refs_from_import_origin(
                    first_origin,
                    module_kind=str(first_kind or "Module"),
                    owner_name=raw_name or name,
                    owner_title_uk=title,
                    owner_title_en=str(localized_titles.get("en") or ""),
                )
                previous_code_refs = payload.get("code_refs") if isinstance(payload.get("code_refs"), dict) else {}
                legacy_code_refs = {
                    lang: str(previous_code_refs.get(lang) or payload.get(f"code_ref_{lang}") or "").strip()
                    for lang in ("uk", "en")
                }
                legacy_code_refs = {lang: value for lang, value in legacy_code_refs.items() if value}
                if legacy_code_refs:
                    payload["legacy_code_refs"] = legacy_code_refs
                payload["localized_names"] = {
                    "uk": str(localized_titles.get("uk") or title),
                    "en": str(localized_titles.get("en") or raw_name or title),
                }
                payload["code_refs"] = {
                    lang: str(object_refs.get(f"ref_{lang}") or "").rsplit(".", 1)[0]
                    for lang in ("uk", "en")
                }
                payload["code_ref_uk"] = payload["code_refs"]["uk"]
                payload["code_ref_en"] = payload["code_refs"]["en"]

        mo = queue_manifest_object(
            obj_type=spec.obj_type,
            name=name,
            title=title,
            parent_guid=parent_guid,
            payload=payload,
            kind="object",
            guid=raw_uid or None,
        )
        guid_by_xml[spec.rel_xml] = mo.guid
        emit_stage_progress(spec, "object", spec_index, total_specs)

        # If this object has child forms/commands/layouts in the dump, create placeholder nodes
        # The raw files are already persisted in assets.
        obj_prefix = spec.rel_dir_prefix

        # Forms
        form_specs: List[FormImportSpec] = list(profile.form_specs) if profile else []
        forms: List[str] = [item.rel_xml for item in form_specs]
        if not forms:
            forms = list(fallback_forms_by_owner.get(obj_prefix, ()))
            form_specs = [FormImportSpec(rel_xml=rel) for rel in forms]
        has_form_modules = False
        if forms:
            forms_folder_guid = queue_section_folder(
                parent_guid=mo.guid,
                parent_type=mo.type,
                section_key="forms",
                order=10,
            )
            form_spec_map = {item.rel_xml: item for item in form_specs}
            for fxml in sorted(set(forms)):
                fbytes = b""
                try:
                    fbytes = source.read_bytes(fxml)
                except Exception:
                    fbytes = b""
                fn, ft, fuid = parse_basic_xml_fields(fbytes)
                ftitle = ft or fn or Path(fxml).stem
                fname = to_ascii_identifier(fn or ftitle)
                fpayload: Dict[str, Any] = {
                    "owner_guid": mo.guid,
                    "imported": {
                        "source": "1c",
                        "origin": fxml,
                    },
                }

                if store_raw_asset_keys:
                    fpayload["imported"]["raw_asset"] = f"{raw_prefix}{fxml}"

                form_spec = form_spec_map.get(fxml)
                if form_spec and form_spec.dump_info_id:
                    fpayload["imported"]["dump_info_id"] = form_spec.dump_info_id
                ext_form_rel = form_spec.ext_form_rel if form_spec else ""
                if ext_form_rel:
                    fpayload["imported"]["form_body_origin"] = ext_form_rel
                    try:
                        ext_form_xml = source.read_bytes(ext_form_rel)
                        form_model, form_kind = build_onec_form_model_from_xml(
                            form_name=fn or Path(fxml).stem,
                            form_title=ftitle,
                            owner_title=title,
                            obj_type=spec.obj_type,
                            ext_form_xml=ext_form_xml,
                        )
                        fpayload["form_model"] = form_model
                        fpayload["subtype"] = form_kind
                        fpayload["imported"].pop("form_body_error", None)
                    except Exception as exc:
                        fpayload["imported"]["form_body_error"] = f"{type(exc).__name__}: {exc}"
                help_rel = form_spec.help_rel if form_spec else ""
                if help_rel:
                    fpayload["imported"]["help_origin"] = help_rel

                # form module candidate(s): store as child module nodes (assets), not inline text
                form_module_origins: list[tuple[str, str]] = []
                fdir = f"{posixpath.dirname(fxml)}/{Path(fxml).stem}/"
                for cand, title_hint in (
                    (f"{fdir}Ext/Form/Module.bsl", "FormModule"),
                    (f"{fdir}Ext/FormModule.bsl", "FormModule"),
                    (f"{fdir}Ext/Module.bsl", "Module"),
                    (f"{fdir}Module.bsl", "Module"),
                ):
                    cand = _norm_rel(cand)
                    if cand in path_set:
                        form_module_origins.append((cand, title_hint))

                if form_module_origins:
                    has_form_modules = True
                    fpayload.setdefault("imported", {})["module_origins"] = [p for p, _t in form_module_origins]

                fmo = queue_manifest_object(
                    obj_type="form",
                    name=fname,
                    title=ftitle,
                    parent_guid=forms_folder_guid,
                    payload=fpayload,
                    kind="object",
                    guid=fuid or None,
                )

                # Add module nodes under the form (semantic REF key -> raw asset).
                if form_module_origins:
                    first_form_module_asset_key = ""
                    try:
                        modules_folder_guid = queue_section_folder(
                            parent_guid=fmo.guid,
                            parent_type="form",
                            section_key="modules",
                            order=15,
                        )
                        for mrel, th in form_module_origins:
                            mtitle = str(th or Path(mrel).stem)

                            module_text = read_module_text(mrel)

                            module_guid = make_imported_module_guid(
                                owner_guid=fmo.guid,
                                owner_kind="form",
                                module_kind=str(th or "Module"),
                                name=str(th or "Module"),
                                text=module_text,
                                origin=mrel,
                                owner_name=fname,
                                owner_title_uk=ftitle,
                            )
                            if not module_guid:
                                module_guid = make_fallback_module_guid(fmo.guid, str(th or "Module"), mrel)
                            if not first_form_module_asset_key and module_guid:
                                first_form_module_asset_key = f"module://{module_guid}"
                            p = Path(mrel)
                            mname = to_ascii_identifier(f"{p.parent.name}_{p.stem}")
                            mpayload: Dict[str, Any] = {
                                "owner_guid": fmo.guid,
                                "module": {
                                    "asset_key": f"module://{module_guid}",
                                    "mime": "text/plain",
                                },
                                "imported": {
                                    "source": "1c",
                                    "origin": mrel,
                                },
                                "module_refs": module_refs_from_import_origin(
                                    mrel,
                                    module_kind=str(th or "Module"),
                                    owner_name=fname,
                                    owner_title_uk=ftitle,
                                ),
                            }
                            queue_manifest_object(
                                obj_type="form_module",
                                name=mname,
                                title=mtitle,
                                parent_guid=modules_folder_guid,
                                payload=mpayload,
                                kind="object",
                                guid=module_guid,
                            )
                    except Exception:
                        pass
                    if first_form_module_asset_key:
                        updated_form_payload = dict(fpayload)
                        updated_form_payload["module"] = {
                            "asset_key": first_form_module_asset_key,
                            "mime": "text/plain",
                        }
                        queue_payload_update(guid=fmo.guid, payload=updated_form_payload)
            emit_stage_progress(spec, "forms", spec_index, total_specs)
            if has_form_modules:
                emit_stage_progress(spec, "form_modules", spec_index, total_specs)

        # Commands
        command_specs: List[CommandImportSpec] = list(profile.command_specs) if profile else []
        commands: List[str] = [item.rel_xml for item in command_specs]
        if not commands:
            commands = list(fallback_commands_by_owner.get(obj_prefix, ()))
            command_specs = [CommandImportSpec(rel_xml=rel, module_origins=[]) for rel in commands]
        has_command_modules = False
        if commands:
            cmd_folder_guid = queue_section_folder(
                parent_guid=mo.guid,
                parent_type=mo.type,
                section_key="commands",
                order=20,
            )
            command_spec_map = {item.rel_xml: item for item in command_specs}
            for cxml in sorted(set(commands)):
                cbytes = b""
                try:
                    cbytes = source.read_bytes(cxml)
                except Exception:
                    cbytes = b""
                cn, ct, cuid = parse_basic_xml_fields(cbytes)
                ctitle = ct or cn or Path(cxml).stem
                cname = to_ascii_identifier(cn or ctitle)
                cpayload: Dict[str, Any] = {
                    "owner_guid": mo.guid,
                    "imported": {
                        "source": "1c",
                        "origin": cxml,
                    },
                }
                if store_raw_asset_keys:
                    cpayload["imported"]["raw_asset"] = f"{raw_prefix}{cxml}"
                command_spec = command_spec_map.get(cxml)
                if command_spec and command_spec.dump_info_id:
                    cpayload["imported"]["dump_info_id"] = command_spec.dump_info_id
                cmo = queue_manifest_object(
                    obj_type="command",
                    name=cname,
                    title=ctitle,
                    parent_guid=cmd_folder_guid,
                    payload=cpayload,
                    kind="object",
                    guid=cuid or None,
                )
                if command_spec and command_spec.module_origins:
                    has_command_modules = True
                    try:
                        modules_folder_guid = queue_section_folder(
                            parent_guid=cmo.guid,
                            parent_type="command",
                            section_key="modules",
                            order=15,
                        )
                        for mrel, th in command_spec.module_origins:
                            module_text = read_module_text(mrel)
                            module_guid = make_imported_module_guid(
                                owner_guid=cmo.guid,
                                owner_kind="command",
                                module_kind=str(th or "CommandModule"),
                                name=str(th or "CommandModule"),
                                text=module_text,
                                origin=mrel,
                                owner_name=cname,
                                owner_title_uk=ctitle,
                            )
                            if not module_guid:
                                module_guid = make_fallback_module_guid(cmo.guid, str(th or "CommandModule"), mrel)
                            queue_manifest_object(
                                obj_type="module",
                                name=to_ascii_identifier(str(th or "CommandModule")),
                                title=str(th or "CommandModule"),
                                parent_guid=modules_folder_guid,
                                payload={
                                    "owner_guid": cmo.guid,
                                    "module": {"asset_key": f"module://{module_guid}", "mime": "text/plain"},
                                    "imported": {"source": "1c", "origin": mrel},
                                    "module_refs": module_refs_from_import_origin(
                                        mrel,
                                        module_kind=str(th or "CommandModule"),
                                        owner_name=cname,
                                        owner_title_uk=ctitle,
                                    ),
                                },
                                kind="object",
                                guid=module_guid,
                            )
                    except Exception:
                        pass
            emit_stage_progress(spec, "commands", spec_index, total_specs)
            if has_command_modules:
                emit_stage_progress(spec, "command_modules", spec_index, total_specs)

        # Layouts/Templates
        layout_specs: List[LayoutImportSpec] = list(profile.layout_specs) if profile else []
        layouts: List[str] = [item.rel_xml for item in layout_specs]
        if not layouts:
            layouts = list(fallback_layouts_by_owner.get(obj_prefix, ()))
            inferred_layout_specs: List[LayoutImportSpec] = []
            for rel in layouts:
                body_rel = ""
                base_dir = f"{posixpath.dirname(rel)}/{Path(rel).stem}/Ext"
                for ext in ("xml", "txt", "bin"):
                    candidate = _norm_rel(f"{base_dir}/Template.{ext}")
                    if candidate in path_set:
                        body_rel = candidate
                        break
                inferred_layout_specs.append(LayoutImportSpec(rel_xml=rel, body_rel=body_rel))
            layout_specs = inferred_layout_specs
        if layouts:
            lay_folder_guid = queue_section_folder(
                parent_guid=mo.guid,
                parent_type=mo.type,
                section_key="layouts",
                order=30,
            )
            layout_spec_map = {item.rel_xml: item for item in layout_specs}
            for lxml in sorted(set(layouts)):
                lbytes = b""
                try:
                    lbytes = source.read_bytes(lxml)
                except Exception:
                    lbytes = b""
                ln, lt, luid = parse_basic_xml_fields(lbytes)
                ltitle = lt or ln or Path(lxml).stem
                lname = to_ascii_identifier(ln or ltitle)
                lpayload: Dict[str, Any] = {
                    "owner_guid": mo.guid,
                    "imported": {
                        "source": "1c",
                        "origin": lxml,
                    },
                }
                if store_raw_asset_keys:
                    lpayload["imported"]["raw_asset"] = f"{raw_prefix}{lxml}"
                layout_spec = layout_spec_map.get(lxml)
                if layout_spec and layout_spec.dump_info_id:
                    lpayload["imported"]["dump_info_id"] = layout_spec.dump_info_id
                body_rel = layout_spec.body_rel if layout_spec else ""
                if body_rel:
                    try:
                        body_bytes = source.read_bytes(body_rel)
                        body_mime = guess_mime(body_rel)
                        layout_model = build_onec_layout_model(
                            body_bytes=body_bytes,
                            mime=body_mime,
                            origin=body_rel,
                        )
                        if layout_model:
                            lpayload["layout_model"] = layout_model
                            lpayload["layout_kind"] = str(layout_model.get("kind") or "")
                        lpayload["imported"]["layout_body_origin"] = body_rel
                        lpayload["imported"]["layout_body_mime"] = body_mime
                    except Exception:
                        pass
                queue_manifest_object(
                    obj_type="layout",
                    name=lname,
                    title=ltitle,
                    parent_guid=lay_folder_guid,
                    payload=lpayload,
                    kind="object",
                    guid=luid or None,
                )
            emit_stage_progress(spec, "layouts", spec_index, total_specs)

        default_form_guids = generate_default_ui_children_if_needed(
            owner_guid=mo.guid,
            owner_type=spec.obj_type,
            owner_name=name,
            owner_title=title,
            owner_payload=payload,
            has_forms=bool(forms),
            has_commands=bool(commands),
        )

        module_texts_by_hint: Dict[str, str] = {}
        for mrel, th in module_origins:
            hint = str(th or "").strip()
            if not hint or hint in module_texts_by_hint:
                continue
            module_text = read_module_text(mrel)
            if module_text.strip():
                module_texts_by_hint[hint] = module_text

        if default_form_guids and not forms:
            list_form_guid = str(default_form_guids.get("list_form") or "").strip()
            object_form_guid = str(default_form_guids.get("object_form") or "").strip()
            list_form_module_text = (
                module_texts_by_hint.get("ObjectModule")
                or module_texts_by_hint.get("Module")
                or module_texts_by_hint.get("FormModule")
                or ""
            )
            object_form_module_text = (
                module_texts_by_hint.get("FormModule")
                or module_texts_by_hint.get("ObjectModule")
                or module_texts_by_hint.get("Module")
                or ""
            )
            if list_form_guid and list_form_module_text:
                pending = pending_object_by_guid.get(list_form_guid)
                if pending is not None and isinstance(getattr(pending, "payload", None), dict):
                    updated_payload = dict(pending.payload or {})
                    updated_payload["form_module"] = list_form_module_text
                    queue_payload_update(guid=list_form_guid, payload=updated_payload)
            if object_form_guid and object_form_module_text:
                pending = pending_object_by_guid.get(object_form_guid)
                if pending is not None and isinstance(getattr(pending, "payload", None), dict):
                    updated_payload = dict(pending.payload or {})
                    updated_payload["form_module"] = object_form_module_text
                    queue_payload_update(guid=object_form_guid, payload=updated_payload)

        if module_origins:
            try:
                modules_folder_guid = ""
                if spec.obj_type != "constants":
                    modules_folder_guid = queue_section_folder(
                        parent_guid=mo.guid,
                        parent_type=mo.type,
                        section_key="modules",
                        order=15,
                    )
                for index, (mrel, th) in enumerate(module_origins):
                    title_hint = th or Path(mrel).stem
                    mtitle = str(title_hint)

                    module_text = read_module_text(mrel)

                    module_guid = make_imported_module_guid(
                        owner_guid=mo.guid,
                        owner_kind="meta_object",
                        module_kind=str(th or "Module"),
                        name=str(th or "Module"),
                        text=module_text,
                        origin=mrel,
                        owner_name=str(raw_name or getattr(mo, "name", "") or spec.name or ""),
                        owner_title_uk=str(getattr(mo, "title", "") or ""),
                        owner_title_en=str(localized_titles.get("en") or ""),
                    )
                    if not module_guid:
                        module_guid = make_fallback_module_guid(mo.guid, str(th or "Module"), mrel)
                    if spec.obj_type in {"common_module", "common_form"} and index == 0:
                        updated_payload = dict(mo.payload or {})
                        updated_payload["module"] = {
                            "asset_key": f"module://{module_guid}",
                            "mime": "text/plain",
                        }
                        queue_payload_update(guid=mo.guid, payload=updated_payload)
                    if spec.obj_type == "constants":
                        continue
                    p = Path(mrel)
                    mname = to_ascii_identifier(f"{p.parent.name}_{p.stem}")
                    mpayload: Dict[str, Any] = {
                        "owner_guid": mo.guid,
                        "module": {
                            "asset_key": f"module://{module_guid}",
                            "mime": "text/plain",
                        },
                        "imported": {
                            "source": "1c",
                            "origin": mrel,
                        },
                        "module_refs": module_refs_from_import_origin(
                            mrel,
                            module_kind=str(th or "Module"),
                            owner_name=str(raw_name or getattr(mo, "name", "") or spec.name or ""),
                            owner_title_uk=str(getattr(mo, "title", "") or ""),
                            owner_title_en=str(localized_titles.get("en") or ""),
                        ),
                    }
                    if store_raw_asset_keys:
                        mpayload["imported"]["raw_asset"] = f"{raw_prefix}{mrel}"
                    queue_manifest_object(
                        obj_type="module",
                        name=mname,
                        title=mtitle,
                        parent_guid=modules_folder_guid,
                        payload=mpayload,
                        kind="object",
                        guid=module_guid,
                    )
            except Exception:
                pass
            emit_stage_progress(spec, "object_modules", spec_index, total_specs)

    disambiguate_localized_module_refs()

    if pending_objects:
        manifest_io.add_objects_bulk(db, pending_objects, update_existing=True)

    if pending_module_rows:
        try:
            from src.configurator.persistence.modules_dao import insert_modules_bulk, write_module_reference_map

            insert_modules_bulk(db, pending_module_rows, update_existing=True)
            write_module_reference_map(db)
        except Exception:
            pass

    if payload_updates_by_guid:
        try:
            manifest_io.bulk_update_payloads(db, payload_updates_by_guid)
        except Exception:
            pass

    if startup_module_guids:
        try:
            root_rows = db.table(manifest_io.MANIFEST_TABLE).select(where={"guid": GUID_ROOT}) or []
            root_payload = dict(root_rows[0].get("payload") or {}) if root_rows else {}
            root_payload["managed_application_module"] = f"module://{root_module_refs.get('ManagedApplicationModule.bsl', '')}" if root_module_refs.get('ManagedApplicationModule.bsl') else root_payload.get("managed_application_module", "")
            root_payload["session_module"] = f"module://{root_module_refs.get('SessionModule.bsl', '')}" if root_module_refs.get('SessionModule.bsl') else root_payload.get("session_module", "")
            root_payload["external_connection_module"] = f"module://{root_module_refs.get('ExternalConnectionModule.bsl', '')}" if root_module_refs.get('ExternalConnectionModule.bsl') else root_payload.get("external_connection_module", "")
            root_payload["ordinary_application_module"] = f"module://{root_module_refs.get('OrdinaryApplicationModule.bsl', '')}" if root_module_refs.get('OrdinaryApplicationModule.bsl') else root_payload.get("ordinary_application_module", "")
            root_payload["startup_modules"] = [f"module://{ref}" if not str(ref).startswith("module://") else str(ref) for ref in startup_module_guids]
            manifest_io.bulk_update_payloads(db, {GUID_ROOT: root_payload})
        except Exception:
            pass

    return guid_by_xml
