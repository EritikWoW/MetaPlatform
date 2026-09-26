import json
from types import SimpleNamespace

import pytest

from src.runtime import server_handlers_manifest as manifest
from src.configurator.persistence import manifest_io
from src.configurator.manifest_schema import MANIFEST_TABLE


@pytest.fixture
def point_reads(monkeypatch, tmp_path):
    path = tmp_path / "metadata.mpdb"
    path.write_bytes(b"metadata")
    active = ("point-reads-db", str(path))
    rows = []
    assets = {}
    selects = []
    asset_reads = []

    class Table:
        def select(self, where=None):
            selects.append(where)
            return [row for row in rows if not where or all(row.get(k) == v for k, v in where.items())]

    class DB:
        def table(self, name):
            assert name == MANIFEST_TABLE, "Point reads must not scan the assets table"
            return Table()

        def get_asset(self, key):
            asset_reads.append(key)
            return json.dumps(assets[key]).encode(), "application/json"

    db = DB()
    monkeypatch.setattr(manifest, "STATE_MANIFEST_LIST_CACHE", manifest.ManifestListMemoryCache())
    monkeypatch.setattr(manifest, "STATE_MANIFEST_INFO_CACHE", manifest.ManifestInfoMemoryCache())
    monkeypatch.setattr(manifest, "STATE_MANIFEST_SCHEMA_CACHE", manifest.ManifestListMemoryCache())
    monkeypatch.setattr(manifest, "_active_db_info_for_db", lambda _db: active)
    monkeypatch.setattr(manifest, "_active_db_info", lambda _payload: active)
    monkeypatch.setattr(manifest, "ensure_manifest", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manifest, "ensure_system_tables", lambda _db: None)
    monkeypatch.setattr(manifest, "load_structure_cache_meta", lambda *args, **kwargs: None)
    monkeypatch.setattr(manifest, "load_structure_cache_payload", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        manifest_io, "_prefetch_manifest_payload_assets",
        lambda *_args: pytest.fail("Point hydration must not prefetch the whole assets table"),
    )
    handler = SimpleNamespace(_require_db=lambda _payload: db)
    return SimpleNamespace(
        db=db, handler=handler, path=path, active=active, rows=rows, assets=assets,
        selects=selects, asset_reads=asset_reads,
    )


def rpc(env, action, **payload):
    return manifest.handle_manifest_action(env.handler, action, {"session_id": "sid", **payload})


@pytest.mark.parametrize("warm_path", ["raw-list", "disk-list", "disk-info", "disk-warmup"])
def test_warm_payload_reads_retain_full_payload_and_only_hydrate_target(point_reads, monkeypatch, warm_path):
    env = point_reads
    payload = {
        "source_name": "Invoice", "custom": {"nested": ["keep"]},
        "imported": {"origin": "Documents/Invoice", "extra": "keep"},
    }
    expected = dict(payload)
    for key in manifest_io._EXTERNALIZED_PAYLOAD_KEYS:
        ref = f"custom-assets/target/{key}.json"
        payload[f"{key}_ref"] = ref
        expected[f"{key}_ref"] = ref
        expected[key] = env.assets[ref] = {"value": key}
    env.rows.extend([
        {"guid": f"unrelated-{i}", "type": "document", "payload": {"form_model_ref": "do-not-read"}}
        for i in range(5000)
    ])
    env.rows.append({"guid": "target", "type": "document", "payload": payload})
    if warm_path.startswith("disk"):
        stat = env.path.stat()
        meta = SimpleNamespace(
            db_uid=env.active[0], structure_hash="hash", object_count=len(env.rows), generated_at=1,
            db_mtime_ns=stat.st_mtime_ns, db_size=stat.st_size,
        )
        monkeypatch.setattr(manifest, "load_structure_cache_meta", lambda *args, **kwargs: meta)
        monkeypatch.setattr(
            manifest, "load_structure_cache_payload",
            lambda *args, **kwargs: SimpleNamespace(meta=meta, objects=env.rows),
        )
    if warm_path == "disk-warmup":
        manifest.warm_manifest_caches(env.db, db_uid=env.active[0], db_path=env.active[1])
    else:
        response = rpc(env, "manifest.info" if warm_path == "disk-info" else "manifest.list", slim=True)
        assert response.status == "ok"
    assert env.asset_reads == []
    env.selects.clear()
    monkeypatch.setattr(
        manifest.STATE_MANIFEST_LIST_CACHE, "get_if_current",
        lambda *_args: pytest.fail("Point reads must not copy or walk the whole cached list"),
    )

    response = rpc(env, "manifest.get_payload", guid="target")

    assert response.status == "ok"
    assert response.data["payload"] == expected
    assert env.selects == []
    assert sorted(env.asset_reads) == sorted(env.assets)
    response.data["payload"]["custom"]["nested"].append("client-edit")
    assert rpc(env, "manifest.get_payload", guid="target").data["payload"] == expected


def test_slim_only_cache_cannot_supply_full_payload(point_reads):
    env = point_reads
    env.rows.append({"guid": "target", "payload": {"source_name": "Full", "form_model_ref": "form"}})
    env.assets["form"] = {"controls": [{"name": "Field"}]}
    manifest.STATE_MANIFEST_LIST_CACHE.put(*env.active, [{"guid": "target", "payload": {"system": True}}])

    response = rpc(env, "manifest.get_payload", guid="target")

    assert response.status == "ok"
    assert response.data["payload"]["source_name"] == "Full"
    assert response.data["payload"]["form_model"] == env.assets["form"]
    assert env.selects == [{"guid": "target"}]


@pytest.mark.parametrize("invalidate", ["file-change", "explicit"])
def test_warm_payload_is_not_reused_after_invalidation(point_reads, invalidate):
    env = point_reads
    env.rows.append({"guid": "target", "payload": {"source_name": "Old"}})
    assert rpc(env, "manifest.list", slim=True).status == "ok"
    env.rows[:] = [{"guid": "target", "payload": {"source_name": "New", "requisites_ref": "new"}}]
    env.assets["new"] = [{"name": "Updated"}]
    env.selects.clear()
    if invalidate == "file-change":
        env.path.write_bytes(b"changed-generation")
    else:
        manifest._invalidate_for_payload({"session_id": "sid"})

    response = rpc(env, "manifest.get_payload", guid="target")

    assert response.status == "ok"
    assert response.data["payload"]["source_name"] == "New"
    assert response.data["payload"]["requisites"] == [{"name": "Updated"}]
    assert env.selects == [{"guid": "target"}]


def test_warm_inline_values_win_and_missing_assets_keep_refs(point_reads):
    env = point_reads
    env.rows.append({"guid": "target", "payload": {
        "form_model": {"inline": True}, "form_model_ref": "do-not-read",
        "rights_ref": "missing", "requisites_ref": "fields",
    }})
    env.assets["fields"] = [{"name": "Code"}]
    assert rpc(env, "manifest.list", slim=True).status == "ok"
    env.selects.clear()

    response = rpc(env, "manifest.get_payload", guid="target")

    assert response.status == "ok"
    assert response.data["payload"] == {
        **env.rows[0]["payload"], "requisites": env.assets["fields"],
    }
    assert env.selects == []
    assert sorted(env.asset_reads) == ["fields", "missing"]


def test_object_context_reuses_warm_payloads_for_owner_and_forms(point_reads, monkeypatch):
    env = point_reads
    env.rows.extend([
        {"guid": "owner", "type": "document", "payload": {"requisites_ref": "fields"}},
        {"guid": "forms", "type": "document", "parent_guid": "owner", "payload": {"system": True}},
        {"guid": "form", "type": "form", "parent_guid": "forms", "payload": {"form_model_ref": "model"}},
        {"guid": "modules", "type": "form", "kind": "folder", "parent_guid": "form", "payload": {"form_model_ref": "do-not-read"}},
        {"guid": "other", "type": "form", "payload": {"form_model_ref": "do-not-read"}},
    ])
    env.assets.update(fields=[{"name": "Number"}], model={"controls": [{"name": "Number"}]})
    module_owners = []
    def modules(_db, *, owner_guid):
        module_owners.append(owner_guid)
        return [{"owner_guid": owner_guid, "module_guid": owner_guid + "-code", "text": "lazy source"}]
    monkeypatch.setattr("src.configurator.persistence.modules_dao.list_modules_by_owner", modules)
    assert rpc(env, "manifest.list", slim=True).status == "ok"
    env.selects.clear()
    monkeypatch.setattr(manifest.STATE_MANIFEST_LIST_CACHE, "get_if_current",
                        lambda *_args: pytest.fail("Object context must not walk the entire cached manifest"))

    response = rpc(env, "manifest.object_context", guid="owner")

    assert response.status == "ok"
    assert response.data["payload"]["requisites"] == env.assets["fields"]
    assert [row["guid"] for row in response.data["forms"]] == ["form"]
    assert response.data["forms"][0]["payload"]["form_model"] == env.assets["model"]
    assert env.selects == []
    assert env.asset_reads == ["fields", "model"]
    assert module_owners == ["owner", "form"]
    assert all("text" not in row for row in response.data["modules"])
