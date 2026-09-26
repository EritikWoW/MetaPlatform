from pathlib import Path
from types import SimpleNamespace

import pytest

from src.runtime.server_handlers_manifest import (
    ManifestInfoMemoryCache,
    STATE_MANIFEST_LIST_CACHE,
    STATE_MANIFEST_SCHEMA_CACHE,
    handle_manifest_action,
    warm_manifest_caches,
)
from src.runtime.server_state import RpcResponse


def test_manifest_info_memory_cache_returns_current_entry_and_invalidates_on_file_change(tmp_path):
    db_path = tmp_path / "demo.mpdb"
    db_path.write_bytes(b"demo")

    cache = ManifestInfoMemoryCache()
    stat = db_path.stat()
    payload = {
        "db_uid": "db-1",
        "db_path": str(db_path),
        "structure_hash": "abc",
        "object_count": 10,
        "generated_at": 123,
        "db_mtime_ns": int(stat.st_mtime_ns),
        "db_size": int(stat.st_size),
    }
    cache.put("db-1", payload)

    loaded = cache.get_if_current("db-1", str(db_path))
    assert loaded is not None
    assert loaded["structure_hash"] == "abc"

    db_path.write_bytes(b"demo-updated")

    assert cache.get_if_current("db-1", str(db_path)) is None


def test_manifest_get_payload_uses_single_row_lookup(monkeypatch):
    class _Table:
        def select(self, where=None, order_by=None):
            assert where == {"guid": "g-1"}
            return [{"guid": "g-1", "payload": {"title": "Object Title", "kind": "demo"}}]

    class _DB:
        def table(self, name):
            assert name
            return _Table()

    fake_db = _DB()
    handler = SimpleNamespace(_require_db=lambda _payload: fake_db)

    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest.list_object_rows",
        lambda _db: pytest.fail("manifest.get_payload must not scan manifest rows"),
        raising=False,
    )
    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest.list_objects",
        lambda _db: pytest.fail("manifest.get_payload must not hydrate full manifest"),
    )
    monkeypatch.setattr(
        "src.configurator.persistence.manifest_io._ensure_configuration_root_module_refs",
        lambda _db: pytest.fail("manifest.get_payload must not mutate configuration"),
    )

    response = handle_manifest_action(handler, "manifest.get_payload", {"guid": "g-1"})

    assert isinstance(response, RpcResponse)
    assert response.status == "ok"
    assert response.data["guid"] == "g-1"
    assert response.data["payload"]["title"] == "Object Title"


def test_manifest_object_context_returns_hydrated_forms_and_module_metadata(monkeypatch):
    rows = {
        "owner": {"guid": "owner", "type": "document", "name": "Demo", "payload": {"owner": True}},
        "form": {"guid": "form", "type": "form", "parent_guid": "owner", "payload": {}},
    }

    class _Table:
        def select(self, where=None, order_by=None):
            if where == {"guid": "owner"}:
                return [rows["owner"]]
            if where == {"guid": "form"}:
                return [rows["form"]]
            if where == {"parent_guid": "owner"}:
                return [rows["form"]]
            if where == {"parent_guid": "form"}:
                return []
            raise AssertionError(where)

    fake_db = SimpleNamespace(table=lambda _name: _Table())
    handler = SimpleNamespace(_require_db=lambda _payload: fake_db)
    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest._manifest_payload_for_guid",
        lambda _db, guid: {"form_model": {"root": {"children": []}}} if guid == "form" else {"title": "Demo"},
    )
    monkeypatch.setattr(
        "src.configurator.persistence.modules_dao.list_modules_by_owner",
        lambda _db, *, owner_guid: [{"module_guid": "m-form", "owner_guid": owner_guid, "module_kind": "form_module"}]
        if owner_guid == "form" else [],
    )

    response = handle_manifest_action(handler, "manifest.object_context", {"guid": "owner"})

    assert isinstance(response, RpcResponse)
    assert response.status == "ok"
    assert response.data["row"]["guid"] == "owner"
    assert response.data["forms"][0]["payload"]["form_model"]
    assert response.data["modules"][0]["module_guid"] == "m-form"


def test_manifest_bulk_update_payloads_writes_once_and_invalidates(monkeypatch):
    fake_db = SimpleNamespace()
    handler = SimpleNamespace(_require_db=lambda _payload: fake_db)
    calls = []
    invalidations = []
    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest.bulk_update_payloads",
        lambda db, payloads: calls.append((db, payloads)) or len(payloads),
    )
    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest._invalidate_for_payload",
        lambda payload, drop_disk_cache=False: invalidations.append((payload, drop_disk_cache)),
    )

    request = {
        "session_id": "sid-1",
        "payloads": {"form-1": {"form_model": {"schema_version": 1}}},
    }
    response = handle_manifest_action(handler, "manifest.bulk_update_payloads", request)

    assert isinstance(response, RpcResponse)
    assert response.status == "ok"
    assert response.data == {"updated": 1}
    assert calls == [(fake_db, request["payloads"])]
    assert invalidations == [(request, True)]


def test_manifest_get_objects_uses_single_row_lookup(monkeypatch):
    class _Table:
        def select(self, where=None, order_by=None):
            assert where == {"guid": "g-2"}
            return [{"guid": "g-2", "payload": {"objects_ref": "asset-ref"}}]

    class _DB:
        def table(self, name):
            assert name
            return _Table()

    fake_db = _DB()
    handler = SimpleNamespace(_require_db=lambda _payload: fake_db)

    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest._load_manifest_payload_asset",
        lambda _db, *, ref: ["o-1", "o-2"] if ref == "asset-ref" else pytest.fail("unexpected ref"),
    )
    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest.list_objects",
        lambda _db: pytest.fail("manifest.get_objects must not hydrate full manifest"),
    )

    response = handle_manifest_action(handler, "manifest.get_objects", {"guid": "g-2"})

    assert isinstance(response, RpcResponse)
    assert response.status == "ok"
    assert response.data["guid"] == "g-2"
    assert response.data["objects"] == ["o-1", "o-2"]


def test_manifest_get_row_uses_single_row_lookup(monkeypatch):
    class _Table:
        def select(self, where=None, order_by=None):
            assert where == {"guid": "g-3"}
            return [{"guid": "g-3", "name": "Demo", "payload": {"metadata_ref": "Catalog.Demo"}}]

    class _DB:
        def table(self, name):
            assert name
            return _Table()

    fake_db = _DB()
    handler = SimpleNamespace(_require_db=lambda _payload: fake_db)

    response = handle_manifest_action(handler, "manifest.get_row", {"guid": "g-3"})

    assert isinstance(response, RpcResponse)
    assert response.status == "ok"
    assert response.data["guid"] == "g-3"
    assert response.data["row"]["guid"] == "g-3"
    assert response.data["row"]["payload"]["metadata_ref"] == "Catalog.Demo"


def test_manifest_get_subtree_uses_targeted_parent_queries(monkeypatch):
    class _Table:
        def __init__(self):
            self.calls: list[dict | None] = []

        def select(self, where=None, order_by=None):
            self.calls.append(where)
            if where == {"guid": "root-1"}:
                return [{"guid": "root-1", "kind": "object", "type": "report", "name": "Demo", "title": "Demo", "parent_guid": "", "payload": {}}]
            if where == {"parent_guid": "root-1"}:
                return [{"guid": "child-1", "kind": "object", "type": "parameters", "name": "Params", "title": "Params", "parent_guid": "root-1", "payload": {}}]
            if where == {"parent_guid": "child-1"}:
                return [{"guid": "child-2", "kind": "object", "type": "report_module", "name": "Module", "title": "Module", "parent_guid": "child-1", "payload": {}}]
            return []

    table = _Table()

    class _DB:
        def table(self, name):
            assert name
            return table

    fake_db = _DB()
    handler = SimpleNamespace(_require_db=lambda _payload: fake_db)

    response = handle_manifest_action(handler, "manifest.get_subtree", {"guid": "root-1"})

    assert isinstance(response, RpcResponse)
    assert response.status == "ok"
    assert [r["guid"] for r in response.data["rows"]] == ["root-1", "child-1", "child-2"]
    assert table.calls == [
        {"guid": "root-1"},
        {"parent_guid": "root-1"},
        {"parent_guid": "child-1"},
        {"parent_guid": "child-2"},
    ]


def test_manifest_list_slim_includes_subsystem_membership(monkeypatch):
    fake_db = SimpleNamespace()
    handler = SimpleNamespace(_require_db=lambda _payload: fake_db)

    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest.list_object_rows",
        lambda _db: [
            {"guid": "s-1", "type": "subsystem", "kind": "object", "name": "Sub", "title": "Sub", "parent_guid": "", "payload": {"objects": ["o-1"], "imported": {"origin": "Subsystems/Sub.xml"}}},
            {"guid": "c-1", "type": "catalog", "kind": "folder", "name": "forms", "title": "forms", "parent_guid": "", "payload": {"metadata_ref": "Catalog.Cat", "system": True, "protected": True, "menu": "add_only", "order": 10}},
        ],
    )

    response = handle_manifest_action(handler, "manifest.list", {"slim": True, "session_id": "sid-1"})

    assert isinstance(response, RpcResponse)
    assert response.status == "ok"
    assert response.data["objects"][0]["objects"] == ["o-1"]
    assert response.data["objects"][0]["payload"]["imported"]["origin"] == "Subsystems/Sub.xml"
    assert response.data["objects"][1]["payload"]["metadata_ref"] == "Catalog.Cat"
    assert response.data["objects"][1]["payload"]["system"] is True
    assert response.data["objects"][1]["payload"]["protected"] is True
    assert response.data["objects"][1]["payload"]["menu"] == "add_only"
    assert response.data["objects"][1]["payload"]["order"] == 10
    assert "objects" not in response.data["objects"][1]


def test_manifest_schema_index_builds_from_cached_structure_rows(monkeypatch, tmp_path):
    db_path = tmp_path / "schema.mpdb"
    db_path.write_bytes(b"schema")
    fake_db = SimpleNamespace()
    handler = SimpleNamespace(_require_db=lambda _payload: fake_db)
    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest._active_db_info",
        lambda _payload: ("schema-db", str(db_path)),
    )
    STATE_MANIFEST_LIST_CACHE.put(
        "schema-db",
        str(db_path),
        [{"guid": "doc-1", "type": "document", "kind": "object", "name": "Doc", "payload": {}}],
    )
    STATE_MANIFEST_SCHEMA_CACHE.invalidate("schema-db")
    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest.build_manifest_schema_index",
        lambda db, rows: [
            {
                "guid": "doc-1",
                "payload": {
                    "requisites": [{"name": "Organization"}],
                    "tabular_parts": [{"name": "Items", "columns": [{"name": "Amount"}]}],
                },
            }
        ],
    )

    response = handle_manifest_action(handler, "manifest.schema_index", {"session_id": "sid"})

    assert isinstance(response, RpcResponse)
    assert response.status == "ok"
    assert response.data["objects"][0]["payload"]["requisites"][0]["name"] == "Organization"
    assert response.data["objects"][0]["payload"]["tabular_parts"][0]["columns"][0]["name"] == "Amount"


def test_manifest_schema_index_uses_memory_cache(monkeypatch, tmp_path):
    db_path = tmp_path / "schema-cache.mpdb"
    db_path.write_bytes(b"schema")
    fake_db = SimpleNamespace()
    handler = SimpleNamespace(_require_db=lambda _payload: fake_db)
    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest._active_db_info",
        lambda _payload: ("schema-cache-db", str(db_path)),
    )
    STATE_MANIFEST_SCHEMA_CACHE.put(
        "schema-cache-db",
        str(db_path),
        [{"guid": "doc-1", "payload": {"requisites": [{"name": "Organization"}]}}],
    )
    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest.build_manifest_schema_index",
        lambda *_args, **_kwargs: pytest.fail("schema index must use the memory cache"),
    )

    response = handle_manifest_action(handler, "manifest.schema_index", {"session_id": "sid"})

    assert isinstance(response, RpcResponse)
    assert response.status == "ok"
    assert response.data["objects"][0]["guid"] == "doc-1"


def test_manifest_list_slim_uses_memory_cache(monkeypatch, tmp_path):
    db_path = tmp_path / "demo.mpdb"
    db_path.write_bytes(b"demo")

    fake_db = SimpleNamespace()
    handler = SimpleNamespace(_require_db=lambda _payload: fake_db)

    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest._active_db_info",
        lambda _payload: ("db-1", str(db_path)),
    )
    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest.list_object_rows",
        lambda _db: pytest.fail("manifest.list slim must use memory cache when available"),
    )

    STATE_MANIFEST_LIST_CACHE.put(
        "db-1",
        str(db_path),
        [
            {"guid": "s-1", "type": "subsystem", "kind": "object", "name": "Sub", "title": "Sub", "parent_guid": "", "objects": ["o-1"]},
        ],
    )

    response = handle_manifest_action(handler, "manifest.list", {"slim": True, "session_id": "sid-1"})

    assert isinstance(response, RpcResponse)
    assert response.status == "ok"
    assert response.data["objects"][0]["guid"] == "s-1"
    assert response.data["objects"][0]["objects"] == ["o-1"]


def test_manifest_nav_filters_memory_cache_without_db_scan(monkeypatch, tmp_path):
    db_path = tmp_path / "nav.mpdb"
    db_path.write_bytes(b"nav")
    fake_db = SimpleNamespace()
    handler = SimpleNamespace(_require_db=lambda _payload: fake_db)
    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest._active_db_info",
        lambda _payload: ("nav-db", str(db_path)),
    )
    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest._build_manifest_list_slim",
        lambda _db: pytest.fail("manifest.nav must filter the warm structure index"),
    )
    STATE_MANIFEST_LIST_CACHE.put(
        "nav-db",
        str(db_path),
        [
            {"guid": "c-1", "type": "catalog", "kind": "object", "name": "Products"},
            {"guid": "s-1", "type": "subsystem", "kind": "object", "name": "Sales"},
            {"guid": "r-1", "type": "role", "kind": "object", "name": "Admin"},
            {"guid": "a-1", "type": "catalog_attribute", "kind": "object", "name": "Code"},
        ],
    )

    response = handle_manifest_action(handler, "manifest.nav", {"session_id": "sid"})

    assert isinstance(response, RpcResponse)
    assert response.status == "ok"
    assert [row["guid"] for row in response.data["objects"]] == ["c-1", "s-1"]


def test_manifest_lookup_filters_memory_index_without_scanning(monkeypatch, tmp_path):
    db_path = tmp_path / "lookup.mpdb"
    db_path.write_bytes(b"lookup")
    fake_db = SimpleNamespace()
    handler = SimpleNamespace(_require_db=lambda _payload: fake_db)
    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest._active_db_info",
        lambda _payload: ("lookup-db", str(db_path)),
    )
    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest._build_manifest_list_slim",
        lambda _db: pytest.fail("manifest.lookup must use the warm structure index"),
    )
    STATE_MANIFEST_LIST_CACHE.put(
        "lookup-db",
        str(db_path),
        [
            {"guid": "a-1", "type": "common_attribute", "name": "DataArea", "title": "ОбластьДанных"},
            {"guid": "c-1", "type": "catalog", "name": "Products", "title": "Товары"},
        ],
    )

    response = handle_manifest_action(
        handler,
        "manifest.lookup",
        {"session_id": "sid", "type": "common_attribute", "limit": 10},
    )

    assert isinstance(response, RpcResponse)
    assert response.status == "ok"
    assert [row["guid"] for row in response.data["objects"]] == ["a-1"]


def test_manifest_list_slim_uses_disk_cache_before_db_scan(monkeypatch, tmp_path):
    db_path = tmp_path / "demo.mpdb"
    db_path.write_bytes(b"demo")

    fake_db = SimpleNamespace()
    handler = SimpleNamespace(_require_db=lambda _payload: fake_db)

    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest._active_db_info",
        lambda _payload: ("db-2", str(db_path)),
    )
    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest.list_object_rows",
        lambda _db: pytest.fail("manifest.list slim must use disk cache before DB scan"),
    )
    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest.load_structure_cache_meta",
        lambda *args, **kwargs: SimpleNamespace(object_count=2),
    )
    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest.load_structure_cache_payload",
        lambda *args, **kwargs: SimpleNamespace(
            objects=[
                {"guid": "s-1", "type": "subsystem", "kind": "object", "name": "Sub", "title": "Sub", "parent_guid": "", "payload": {"objects": ["o-1"]}},
                {"guid": "c-1", "type": "catalog", "kind": "object", "name": "Cat", "title": "Cat", "parent_guid": "", "payload": {"metadata_ref": "Catalog.Cat"}},
            ]
        ),
    )

    response = handle_manifest_action(handler, "manifest.list", {"slim": True, "session_id": "sid-1"})

    assert isinstance(response, RpcResponse)
    assert response.status == "ok"
    assert response.data["objects"][0]["guid"] == "s-1"
    assert response.data["objects"][0]["objects"] == ["o-1"]
    assert response.data["objects"][1]["payload"]["metadata_ref"] == "Catalog.Cat"


def test_warm_manifest_caches_uses_disk_cache_before_db_scan(monkeypatch, tmp_path):
    db_path = tmp_path / "demo.mpdb"
    db_path.write_bytes(b"demo")

    fake_db = SimpleNamespace()
    meta = SimpleNamespace(
        db_uid="db-3",
        structure_hash="hash-3",
        object_count=2,
        generated_at=123,
        db_mtime_ns=int(db_path.stat().st_mtime_ns),
        db_size=int(db_path.stat().st_size),
    )

    monkeypatch.setattr("src.runtime.server_handlers_manifest.ensure_system_tables", lambda _db: None)
    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest.ensure_manifest",
        lambda _db, seed_defaults=False: None,
    )
    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest.list_object_rows",
        lambda _db: pytest.fail("warm_manifest_caches must use disk cache before DB scan"),
    )
    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest.load_structure_cache_meta",
        lambda *args, **kwargs: meta,
    )
    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest.load_structure_cache_payload",
        lambda *args, **kwargs: SimpleNamespace(
            objects=[
                {
                    "guid": "s-1",
                    "type": "subsystem",
                    "kind": "object",
                    "name": "Sub",
                    "title": "Sub",
                    "parent_guid": "",
                    "payload": {"objects": ["o-1"]},
                },
                {
                    "guid": "c-1",
                    "type": "catalog",
                    "kind": "object",
                    "name": "Cat",
                    "title": "Cat",
                    "parent_guid": "",
                    "payload": {"metadata_ref": "Catalog.Cat"},
                },
            ]
        ),
    )

    warm_manifest_caches(fake_db, db_uid="db-3", db_path=str(db_path))

    info = STATE_MANIFEST_LIST_CACHE.get_if_current("db-3", str(db_path))
    assert info is not None
    assert info[0]["guid"] == "s-1"
    assert info[0]["objects"] == ["o-1"]


def test_warm_manifest_caches_skips_database_closed_before_worker_runs(monkeypatch, tmp_path):
    db_path = tmp_path / "closed.mpdb"
    db_path.write_bytes(b"closed")
    monkeypatch.setattr(
        "src.runtime.server_handlers_manifest.ensure_system_tables",
        lambda _db: pytest.fail("closed database must not be warmed"),
    )

    warm_manifest_caches(
        SimpleNamespace(_opened=False),
        db_uid="db-closed",
        db_path=str(db_path),
    )
