from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from .onec_requisites_model import OneCMetaObject
from .onec_requisites_xml import parse_object_xml, parse_role_rights_xml


_FOLDER_TO_TYPE: Dict[str, str] = {
    "Constants": "constants",
    "Catalogs": "catalog",
    "Documents": "document",
    "Enums": "enumeration",
    "InformationRegisters": "register_info",
    "AccumulationRegisters": "register_accum",
    "AccountingRegisters": "register_accounting",
    "CalculationRegisters": "register_calc",
    "Reports": "report",
    "Roles": "role",
    "DataProcessors": "data_processor",
    "ChartsOfCharacteristicTypes": "chart_of_characteristic_types",
    "ChartsOfAccounts": "chart_of_accounts",
    "ChartsOfCalculationTypes": "chart_of_calculation_types",
    "BusinessProcesses": "business_process",
    "Tasks": "task",
    "DocumentJournals": "journal",
    "Subsystems": "subsystem",
}

_ROOT_XML_RE = re.compile(r"^([^/]+)/([^/]+)\.xml$")
_SUBSYSTEM_XML_RE = re.compile(r"^Subsystems/(?:[^/]+/Subsystems/)*[^/]+\.xml$")


class OneCXmlParser:
    """Парсит набор XML-файлов из дампа конфигурации 1С."""

    def parse_all(
        self,
        source: Any,
        obj_type_hint: Optional[str] = None,
        progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> List[OneCMetaObject]:
        paths = source.list_files()
        result: List[OneCMetaObject] = []

        root_xmls = [path for path in paths if path.endswith(".xml") and "/" not in path]
        has_type_folders = any(path.split("/")[0] in _FOLDER_TO_TYPE for path in paths if "/" in path)
        candidate_paths: List[str] = []

        for rel in paths:
            matched = _ROOT_XML_RE.match(rel)
            if matched and matched.group(1) in _FOLDER_TO_TYPE:
                candidate_paths.append(rel)
                continue
            if _SUBSYSTEM_XML_RE.match(rel):
                candidate_paths.append(rel)
                continue
            if rel in root_xmls and not has_type_folders:
                candidate_paths.append(rel)

        total = max(len(candidate_paths), 1)

        for index, rel in enumerate(candidate_paths, start=1):
            try:
                xml_bytes = source.read_bytes(rel)
            except Exception:
                if progress is not None and (index == total or index % 25 == 0):
                    progress(index, total, f"Парсинг XML-об'єктів: {index}/{total}")
                continue
            obj = parse_object_xml(xml_bytes, origin_path=rel)
            if obj is None:
                if progress is not None and (index == total or index % 25 == 0):
                    progress(index, total, f"Парсинг XML-об'єктів: {index}/{total}")
                continue
            if obj.obj_type == "role":
                role_rights_rel = self._role_rights_rel(rel)
                if role_rights_rel:
                    try:
                        role_rights_bytes = source.read_bytes(role_rights_rel)
                    except Exception:
                        role_rights_bytes = b""
                    if role_rights_bytes:
                        role_payload = parse_role_rights_xml(role_rights_bytes)
                        if role_payload:
                            self._merge_role_payload(obj, role_payload)
            if obj_type_hint and not obj.obj_type:
                obj.obj_type = obj_type_hint
            result.append(obj)
            if progress is not None and (index == total or index % 25 == 0):
                progress(index, total, f"Парсинг XML-об'єктів: {index}/{total}")

        result.sort(key=lambda obj: (obj.obj_type, obj.name))
        return result

    def parse_bytes_map(self, files: Dict[str, bytes]) -> List[OneCMetaObject]:
        class _DictSource:
            def __init__(self, data: Dict[str, bytes]):
                self._data = data

            def list_files(self) -> List[str]:
                return list(self._data.keys())

            def read_bytes(self, rel_path: str) -> bytes:
                return self._data[rel_path]

        return self.parse_all(_DictSource(files))

    @staticmethod
    def _role_rights_rel(rel_path: str) -> str:
        rel = str(rel_path or "").replace("\\", "/").strip()
        matched = _ROOT_XML_RE.match(rel)
        if not matched or matched.group(1) != "Roles":
            return ""
        return f"Roles/{matched.group(2)}/Ext/Rights.xml"

    @staticmethod
    def _merge_role_payload(obj: OneCMetaObject, role_payload: Dict[str, Any]) -> None:
        if "set_for_new_objects" in role_payload:
            obj.set_for_new_objects = bool(role_payload.get("set_for_new_objects"))
        if "set_for_attributes_by_default" in role_payload:
            obj.set_for_attributes_by_default = bool(role_payload.get("set_for_attributes_by_default"))
        if "independent_rights_of_child_objects" in role_payload:
            obj.independent_rights_of_child_objects = bool(
                role_payload.get("independent_rights_of_child_objects")
            )
        if isinstance(role_payload.get("rights"), list):
            obj.rights = [
                dict(item) for item in role_payload.get("rights", []) if isinstance(item, dict)
            ]
        if isinstance(role_payload.get("restriction_templates"), list):
            obj.restriction_templates = [
                dict(item)
                for item in role_payload.get("restriction_templates", [])
                if isinstance(item, dict)
            ]


__all__ = ["OneCXmlParser"]
