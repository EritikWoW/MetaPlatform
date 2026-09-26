from __future__ import annotations

import time
from typing import Dict

from src.mpdb.mpdb import Mpdb


MODULES_TABLE = "cfg_modules"

_MODULES_SCHEMA: Dict[str, Dict[str, object]] = {
    "module_guid": {"type": "str", "unique": True, "indexed": True},
    "owner_guid": {"type": "str", "indexed": True},
    "owner_kind": {"type": "str"},
    "module_kind": {"type": "str"},
    "name": {"type": "str"},
    "source_ref": {"type": "str"},
    "canonical_ref": {"type": "str", "indexed": True},
    "ref_uk": {"type": "str", "indexed": True},
    "ref_en": {"type": "str", "indexed": True},
    "lang": {"type": "str"},
    "text": {"type": "str"},
    "sha256": {"type": "str"},
    "version": {"type": "int"},
    "updated_at": {"type": "int"},
    "updated_by": {"type": "str"},
    "storage_kind": {"type": "str"},
    "content_ref": {"type": "str"},
    "size_bytes": {"type": "int"},
}
_MODULES_INDEX_FIELDS = {"module_guid", "owner_guid", "canonical_ref", "ref_uk", "ref_en"}


def _now_ms() -> int:
    """Milliseconds since Unix epoch."""
    return int(time.time() * 1000)


def _table_exists(db: Mpdb, name: str) -> bool:
    try:
        db.table(name)
        return True
    except Exception:
        return False


def _persist_meta(db: Mpdb) -> None:
    with db.transaction() as tx:
        tx.set_meta(db._meta)


def _reconcile_modules_schema(db: Mpdb) -> None:
    try:
        tinfo = db._meta["tables"][MODULES_TABLE]  # noqa: SLF001 - mpdb schema migration
    except Exception:
        return

    schema_raw = tinfo.get("schema", {})
    schema = schema_raw.get("fields", schema_raw) if isinstance(schema_raw, dict) else {}
    if not isinstance(schema, dict):
        return

    changed = False
    for field, opts in _MODULES_SCHEMA.items():
        cur = schema.get(field)
        if not isinstance(cur, dict):
            schema[field] = dict(opts)
            changed = True
            continue
        for key, value in opts.items():
            if cur.get(key) != value:
                cur[key] = value
                changed = True

    for field, cur in schema.items():
        if not isinstance(cur, dict) or field in _MODULES_INDEX_FIELDS:
            continue
        if cur.pop("indexed", None) is not None:
            changed = True
        if cur.pop("unique", None) is not None:
            changed = True

    idx_def = db._meta.setdefault("indexes", {}).setdefault(MODULES_TABLE, {})  # noqa: SLF001 - mpdb schema migration
    for field in list(idx_def.keys()):
        if field not in _MODULES_INDEX_FIELDS:
            idx_def.pop(field, None)
            changed = True

    if changed:
        _persist_meta(db)


def ensure_modules_tables(db: Mpdb) -> None:
    """Ensure configuration code artifacts table exists.

    The table stores editable code (primarily 1C/BAS BSL modules) as plain text.
    This avoids bloating the DB by storing the entire 1C dump as blob assets.

    Notes:
        - mpdb auto-maintains simple indexes when schema fields set
          `indexed=True` or `unique=True`.
        - We keep the schema minimal and stable.
    """

    if _table_exists(db, MODULES_TABLE):
        _reconcile_modules_schema(db)
        return

    db.create_table(
        MODULES_TABLE,
        _MODULES_SCHEMA,
    )
