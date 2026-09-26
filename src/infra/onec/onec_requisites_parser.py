"""
Compatibility shim for 1C XML requisites parser.

Canonical modules:
- onec_requisites_model.py
- onec_requisites_xml.py
- onec_requisites_source.py
- onec_requisites_enrich.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from .onec_requisites_enrich import enrich_manifest_payload
from .onec_requisites_model import (
    OneCEnumValue,
    OneCMetaObject,
    OneCRequisite,
    OneCTabularColumn,
    OneCTabularPart,
)
from .onec_requisites_source import OneCXmlParser
from .onec_requisites_xml import parse_object_xml

__all__ = [
    "OneCXmlParser",
    "OneCMetaObject",
    "OneCRequisite",
    "OneCTabularPart",
    "OneCTabularColumn",
    "OneCEnumValue",
    "parse_object_xml",
    "enrich_manifest_payload",
]


if __name__ == "__main__":
    import json
    import sys
    import zipfile as zf

    if len(sys.argv) < 2:
        print("Использование: python onec_requisites_parser.py <path/to/dump.zip или папка>")
        print("  или: python onec_requisites_parser.py <path/to/OneObject.xml>")
        raise SystemExit(1)

    target = sys.argv[1]
    path = Path(target)

    if path.suffix.lower() == ".xml":
        obj = parse_object_xml(path.read_bytes(), origin_path=str(path))
        if obj is None:
            print("Не удалось распознать объект конфигурации 1С")
            raise SystemExit(1)
        print(f"Объект: {obj.obj_type} / {obj.name}")
        print(f"Синонимы: {obj.synonyms}")
        print(f"Реквизитов: {len(obj.requisites)}")
        for req in obj.requisites:
            ref = f" -> {req.ref_name}" if req.ref_name else ""
            print(f"  {req.name}: {req.mp_type}{ref}  [{req.synonyms.get('ru', '')}]")
        print(f"Табличных частей: {len(obj.tabular_parts)}")
        for part in obj.tabular_parts:
            print(f"  {part.name} ({len(part.columns)} колонок): {part.synonyms.get('ru', '')}")
            for col in part.columns:
                print(f"    {col.name}: {col.mp_type}")
        if obj.enum_values:
            print(f"Значений перечисления: {len(obj.enum_values)}")
            for value in obj.enum_values[:10]:
                print(f"  [{value.order}] {value.name}: {value.synonyms.get('ru', '')}")
    elif path.suffix.lower() == ".zip":
        class ZS:
            def __init__(self, archive_path: str):
                self._zip = zf.ZipFile(archive_path)

            def list_files(self):
                return [name for name in self._zip.namelist() if not name.endswith("/")]

            def read_bytes(self, rel):
                return self._zip.read(rel)

        source = ZS(str(path))
        objects = OneCXmlParser().parse_all(source)
        print(f"Объектов найдено: {len(objects)}")
        by_type: Dict[str, int] = {}
        for obj in objects:
            by_type[obj.obj_type] = by_type.get(obj.obj_type, 0) + 1
        for obj_type, count in sorted(by_type.items()):
            print(f"  {obj_type}: {count}")
    elif path.is_dir():
        class DS:
            def __init__(self, root: str):
                self._root = Path(root)

            def list_files(self):
                return [
                    str(file.relative_to(self._root).as_posix())
                    for file in self._root.rglob("*")
                    if file.is_file()
                ]

            def read_bytes(self, rel):
                return (self._root / rel).read_bytes()

        objects = OneCXmlParser().parse_all(DS(str(path)))
        print(f"Объектов найдено: {len(objects)}")
        for obj in objects[:20]:
            print(
                f"  {obj.obj_type:30s} {obj.name:40s} "
                f"реквизитов:{len(obj.requisites):3d}  тчастей:{len(obj.tabular_parts)}"
            )
    else:
        print(f"Не поддерживается: {target}")
        raise SystemExit(1)
