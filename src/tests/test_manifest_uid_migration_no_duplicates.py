from __future__ import annotations


def test_uid_manifest_migration_does_not_duplicate_system_seed(tmp_path):
    """Regression: migrating old UID-based manifest must not produce a second SYSTEM tree.

    Scenario observed in UI: when a legacy DB is added/opened, migration assigns random GUIDs,
    then seeding (deterministic GUIDs) creates a duplicate set of standard nodes.
    """

    from src.mpdb.mpdb import Mpdb
    from src.configurator.manifest_schema import MANIFEST_TABLE
    from src.configurator.manifest_io import ensure_manifest

    db_path = tmp_path / "legacy.mpdb"
    db = Mpdb(str(db_path))
    try:
        # Create legacy UID-based manifest schema
        legacy_schema = {
            "uid": {"type": "str", "unique": True, "indexed": True},
            "type": {"type": "str", "indexed": True},
            "name": {"type": "str", "indexed": True},
            "title": {"type": "str"},
            "kind": {"type": "str", "indexed": True},
            "parent_uid": {"type": "str", "indexed": True},
            "payload": {"type": "json"},
        }
        db.create_table(MANIFEST_TABLE, schema=legacy_schema)

        t = db.table(MANIFEST_TABLE)

        # Minimal subset of SYSTEM nodes from the old world
        t.insert(
            {
                "uid": "1",
                "type": "configuration",
                "name": "Configuration",
                "title": "Конфигурация",
                "kind": "root",
                "parent_uid": "",
                "payload": {"system": True, "seed": True},
            }
        )
        t.insert(
            {
                "uid": "2",
                "type": "common",
                "name": "common",
                "title": "Общие",
                "kind": "group",
                "parent_uid": "1",
                "payload": {"system": True, "seed": True},
            }
        )
        t.insert(
            {
                "uid": "3",
                "type": "common",
                "name": "common_attributes",
                "title": "Общие реквизиты",
                "kind": "folder",
                "parent_uid": "2",
                "payload": {"system": True, "seed": True},
            }
        )

        # Trigger migration + seed
        ensure_manifest(db, seed_defaults=True)

        rows = db.table(MANIFEST_TABLE).select() or []

        def count(title: str) -> int:
            return sum(1 for r in rows if str(r.get("title") or "") == title)

        # Must be singletons
        assert count("Конфигурация") == 1
        assert count("Общие") == 1
        assert count("Общие реквизиты") == 1
    finally:
        db.close()
