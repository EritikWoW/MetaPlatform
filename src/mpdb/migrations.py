from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Tuple


META_ROOT = "root"
META_TABLES = "tables"
META_INDEXES = "indexes"
META_NEXT_PAGE_ID = "next_page_id"
META_FREE_PAGES = "free_pages"
META_FREELIST = "freelist"
META_STRINGS = "strings"
META_NEXT_STR_ID = "next_str_id"
META_ASSETS = "assets"
META_AUTOCHECKPOINT = "autocheckpoint"
META_LSN = "lsn"
META_WAL = "wal"


def ensure_supported_format_rev(fmt_rev: int, *, current_rev: int) -> None:
    """Validate that the on-disk minor revision can be opened by this build."""
    if int(fmt_rev) > int(current_rev):
        raise ValueError(f"Unsupported format revision: {fmt_rev}")


def _migrate_meta_rev_0_to_1(meta: Dict[str, Any], *, page_size: int) -> Dict[str, Any]:
    migrated = deepcopy(meta)
    migrated.setdefault(META_ROOT, 1)
    migrated.setdefault(META_TABLES, {})
    migrated.setdefault(META_INDEXES, {})
    migrated.setdefault(META_NEXT_PAGE_ID, 2)
    migrated.setdefault(META_FREE_PAGES, [])
    migrated.setdefault(META_FREELIST, {"head": 0, "count": 0})
    migrated.setdefault(META_STRINGS, {})
    migrated.setdefault(META_NEXT_STR_ID, 1)
    migrated.setdefault(META_ASSETS, {})
    migrated.setdefault(META_AUTOCHECKPOINT, {
        "wal_bytes": 16 * 1024 * 1024,
        "commits": 200,
        "keep_wal_bytes": 0,
    })
    migrated.setdefault(META_LSN, 0)
    migrated.setdefault(META_WAL, {"start": 128 + int(page_size), "end": 128 + int(page_size)})
    return migrated


def _migrate_meta_rev_1_to_2(meta: Dict[str, Any], *, page_size: int) -> Dict[str, Any]:
    migrated = deepcopy(meta)
    migrated.setdefault(META_TABLES, {})
    migrated.setdefault(META_INDEXES, {})
    return migrated


def _migrate_meta_rev_2_to_3(meta: Dict[str, Any], *, page_size: int) -> Dict[str, Any]:
    # v3 changes the on-disk compaction strategy only. The semantic META shape
    # is still the same after expansion, so this is a structural no-op.
    return deepcopy(meta)


def _migrate_meta_rev_3_to_4(meta: Dict[str, Any], *, page_size: int) -> Dict[str, Any]:
    # v4 only changes how META is compressed on disk and introduces a stronger
    # compression codec for META slots. The expanded semantic shape is unchanged.
    return deepcopy(meta)


def migrate_meta_to_format(meta: Dict[str, Any], *, from_rev: int, to_rev: int, page_size: int) -> Tuple[Dict[str, Any], bool]:
    """Apply in-place format migrations conceptually, returning (meta, changed)."""
    cur = int(from_rev)
    target = int(to_rev)
    out = deepcopy(meta)
    changed = False

    while cur < target:
        if cur == 0:
            out = _migrate_meta_rev_0_to_1(out, page_size=int(page_size))
            changed = True
            cur = 1
            continue
        if cur == 1:
            out = _migrate_meta_rev_1_to_2(out, page_size=int(page_size))
            cur = 2
            continue
        if cur == 2:
            out = _migrate_meta_rev_2_to_3(out, page_size=int(page_size))
            cur = 3
            continue
        if cur == 3:
            out = _migrate_meta_rev_3_to_4(out, page_size=int(page_size))
            cur = 4
            continue
        raise ValueError(f"No migration path from format_rev {cur} to {target}")

    return out, changed
