from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from src.infra.onec.importer import DirectorySource, build_import_plan_from_dump_info
from src.ui_qt.services.object_editor_profiles import (
    EDITOR_PAGE_PROFILES,
    get_editor_page_specs,
    normalize_editor_profile_key,
)


def audit_editor_profiles(xml_root: Path) -> tuple[list[str], list[str]]:
    source = DirectorySource(xml_root)
    paths = source.list_files()
    specs = build_import_plan_from_dump_info(source, paths)
    counts = Counter(spec.obj_type for spec in specs)

    lines: list[str] = []
    missing_profiles: list[str] = []

    for obj_type in sorted(counts):
        profile_key = normalize_editor_profile_key(obj_type)
        pages = [spec.key for spec in get_editor_page_specs(obj_type)]
        if profile_key not in EDITOR_PAGE_PROFILES:
            missing_profiles.append(obj_type)
        lines.append(
            f"{obj_type}: count={counts[obj_type]} profile={profile_key} pages={','.join(pages) or '-'}"
        )

    missing_profiles.sort()
    return lines, missing_profiles


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    xml_root = Path(args[0]) if args else Path.cwd() / "XMLConf"
    if not xml_root.exists():
        print(f"XML root not found: {xml_root}")
        return 2

    lines, missing_profiles = audit_editor_profiles(xml_root)
    print("OBJECT_EDITOR_PROFILES")
    for line in lines:
        print(line)

    print()
    print("MISSING_PROFILES")
    if not missing_profiles:
        print("none")
    else:
        for obj_type in missing_profiles:
            print(obj_type)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
