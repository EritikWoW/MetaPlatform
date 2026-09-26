from __future__ import annotations

from typing import Dict, Set

from src.mpdb.mpdb import META_INDEXES, META_TABLES, Mpdb, _decode_index_node


def _collect_index_tree_pages(db: Mpdb, root_page_id: int, seen: Set[int]) -> None:
    pid = int(root_page_id or 0)
    if pid <= 0 or pid in seen:
        return
    seen.add(pid)
    node = _decode_index_node(db._read_page(pid))  # noqa: SLF001 - storage-level traversal
    if int(node.get("leaf", 0)) == 1:
        return
    for child_pid in node.get("children", []) or []:
        _collect_index_tree_pages(db, int(child_pid), seen)


def collect_table_owned_pages(db: Mpdb, table_name: str) -> Set[int]:
    """Return all data and index pages owned by a table."""

    tinfo = db._meta.get(META_TABLES, {}).get(table_name) or {}  # noqa: SLF001
    owned: Set[int] = {
        int(pid)
        for pid in (tinfo.get("data_pages") or [])
        if int(pid or 0) > 0
    }
    rowid_root = int(tinfo.get("rowid_index_root") or 0)
    if rowid_root > 0:
        _collect_index_tree_pages(db, rowid_root, owned)

    idx_def = db._meta.get(META_INDEXES, {}).get(table_name) or {}  # noqa: SLF001
    for idef in idx_def.values():
        if not isinstance(idef, dict):
            continue
        root_pid = int(idef.get("root") or 0)
        if root_pid > 0:
            _collect_index_tree_pages(db, root_pid, owned)
    return owned


def reset_table_storage(db: Mpdb, table_name: str, *, drop_table: bool = False) -> bool:
    """Clear a table and return its data/index pages to the free-page pool."""

    tables = db._meta.get(META_TABLES, {})  # noqa: SLF001
    if table_name not in tables:
        return False

    owned_pages = collect_table_owned_pages(db, table_name)

    with db.transaction() as tx:
        for pid in sorted(owned_pages):
            db._free_page_id(tx, int(pid))  # noqa: SLF001 - explicit page reuse

        tables = db._meta.setdefault(META_TABLES, {})  # noqa: SLF001
        indexes = db._meta.setdefault(META_INDEXES, {})  # noqa: SLF001
        if drop_table:
            tables.pop(table_name, None)
            indexes.pop(table_name, None)
        else:
            tinfo: Dict[str, object] = tables[table_name]
            tinfo["data_pages"] = []
            tinfo["next_rowid"] = 1
            tinfo["rowid_index_root"] = 0
            indexes[table_name] = {}
        tx.set_meta(db._meta)
    return True


__all__ = ["collect_table_owned_pages", "reset_table_storage"]
