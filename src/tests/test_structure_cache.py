import time

from src.configurator.cache.structure_cache import (
    cache_needs_compaction,
    cache_meta_path_for_db,
    compute_structure_hash,
    drop_structure_cache,
    load_structure_cache,
    load_structure_cache_meta,
    save_structure_cache_meta_only,
    save_structure_cache_snapshot,
)
from src.configurator.manifest_schema import ManifestObject
from src.configurator.persistence.manifest_io import add_objects_bulk, list_objects
from src.mpdb.mpdb import Mpdb


def test_structure_cache_roundtrip_and_db_stat_guard(tmp_path):
    db_path = tmp_path / "demo.mpdb"
    db_path.write_bytes(b"demo")

    objects = [
        ManifestObject(
            guid="g-root",
            parent_guid="",
            type="configuration",
            name="Configuration",
            title="Configuration",
            kind="root",
            payload={"system": True},
        ),
        ManifestObject(
            guid="g-cat",
            parent_guid="g-root",
            type="catalog",
            name="Products",
            title="Products",
            kind="object",
            payload={"attributes": [{"name": "code"}]},
        ),
    ]

    meta = save_structure_cache_snapshot(db_path, db_uid="db-1", generated_at=123, objects=objects)
    assert meta.structure_hash
    assert meta.object_count == 2

    loaded_meta = load_structure_cache_meta(db_path, db_uid="db-1")
    assert loaded_meta is not None
    assert loaded_meta.structure_hash == meta.structure_hash

    loaded_objects = load_structure_cache(db_path, db_uid="db-1", structure_hash=meta.structure_hash)
    assert loaded_objects is not None
    assert [o.guid for o in loaded_objects] == ["g-root", "g-cat"]

    time.sleep(0.01)
    db_path.write_bytes(b"demo-updated")

    assert load_structure_cache_meta(db_path, db_uid="db-1") is None
    assert load_structure_cache(db_path, db_uid="db-1", structure_hash=meta.structure_hash) is None


def test_structure_cache_rejects_legacy_snapshot_without_cache_version(tmp_path):
    db_path = tmp_path / "legacy.mpdb"
    db_path.write_bytes(b"demo")
    cache_path = db_path.with_suffix(db_path.suffix + ".structure_cache.json")
    cache_path.write_text(
        '{"meta":{"db_uid":"db-1","structure_hash":"old"},"objects":[]}',
        encoding="utf-8",
    )

    assert load_structure_cache_meta(db_path, db_uid="db-1", verify_db_state=False) is None
    assert load_structure_cache(db_path, db_uid="db-1", structure_hash="old", verify_db_state=False) is None


def test_structure_hash_is_order_independent():
    a = {"guid": "2", "parent_guid": "1", "type": "catalog", "name": "B", "title": "B", "kind": "object", "payload": {"x": 1}}
    b = {"guid": "1", "parent_guid": "", "type": "configuration", "name": "A", "title": "A", "kind": "root", "payload": {}}

    assert compute_structure_hash([a, b]) == compute_structure_hash([b, a])


def test_structure_cache_meta_uses_sidecar_and_survives_broken_main_cache(tmp_path):
    db_path = tmp_path / "demo.mpdb"
    db_path.write_bytes(b"demo")
    objects = [
        ManifestObject(
            guid="g-root",
            parent_guid="",
            type="configuration",
            name="Configuration",
            title="Configuration",
            kind="root",
            payload={"system": True},
        ),
    ]

    meta = save_structure_cache_snapshot(db_path, db_uid="db-1", generated_at=123, objects=objects)
    meta_path = cache_meta_path_for_db(db_path)

    assert meta_path.exists()

    cache_path = db_path.with_suffix(db_path.suffix + ".structure_cache.json")
    cache_path.write_text("{broken json", encoding="utf-8")

    loaded_meta = load_structure_cache_meta(db_path, db_uid="db-1")

    assert loaded_meta is not None
    assert loaded_meta.structure_hash == meta.structure_hash


def test_structure_cache_can_be_loaded_without_db_stat_verification(tmp_path):
    db_path = tmp_path / "demo.mpdb"
    db_path.write_bytes(b"demo")
    objects = [
        ManifestObject(
            guid="g-root",
            parent_guid="",
            type="configuration",
            name="Configuration",
            title="Configuration",
            kind="root",
            payload={"system": True},
        ),
    ]

    meta = save_structure_cache_snapshot(db_path, db_uid="db-1", generated_at=123, objects=objects)
    db_path.write_bytes(b"demo-updated")

    assert load_structure_cache_meta(db_path, db_uid="db-1") is None
    loaded_meta = load_structure_cache_meta(db_path, db_uid="db-1", verify_db_state=False)
    assert loaded_meta is not None
    assert loaded_meta.structure_hash == meta.structure_hash

    loaded_objects = load_structure_cache(
        db_path,
        db_uid="db-1",
        structure_hash=meta.structure_hash,
        verify_db_state=False,
    )
    assert loaded_objects is not None
    assert [o.guid for o in loaded_objects] == ["g-root"]


def test_drop_structure_cache_removes_both_cache_files(tmp_path):
    db_path = tmp_path / "demo.mpdb"
    db_path.write_bytes(b"demo")
    save_structure_cache_snapshot(
        db_path,
        db_uid="db-1",
        generated_at=123,
        objects=[],
    )

    assert cache_meta_path_for_db(db_path).exists()
    assert db_path.with_suffix(db_path.suffix + ".structure_cache.json").exists()

    drop_structure_cache(db_path)

    assert not cache_meta_path_for_db(db_path).exists()
    assert not db_path.with_suffix(db_path.suffix + ".structure_cache.json").exists()


def test_structure_cache_snapshot_is_written_as_compact_json(tmp_path):
    db_path = tmp_path / "compact_cache.mpdb"
    db_path.write_bytes(b"demo")

    save_structure_cache_snapshot(
        db_path,
        db_uid="db-1",
        generated_at=123,
        objects=[
            ManifestObject(
                guid="g-root",
                parent_guid="",
                type="configuration",
                name="Configuration",
                title="Configuration",
                kind="root",
                payload={"system": True, "attributes": [{"name": "Code"}]},
            )
        ],
    )

    cache_text = db_path.with_suffix(db_path.suffix + ".structure_cache.json").read_text(encoding="utf-8")
    meta_text = cache_meta_path_for_db(db_path).read_text(encoding="utf-8")

    assert '\n  "' not in cache_text
    assert '\n  "' not in meta_text


def test_cache_needs_compaction_detects_legacy_pretty_cache(tmp_path):
    db_path = tmp_path / "legacy_cache.mpdb"
    db_path.write_bytes(b"demo")
    cache_path = db_path.with_suffix(db_path.suffix + ".structure_cache.json")

    cache_path.write_text('{\n  "meta": {},\n  "objects": []\n}', encoding="utf-8")
    assert cache_needs_compaction(db_path) is True

    cache_path.write_text('{"meta":{},"objects":[]}', encoding="utf-8")
    assert cache_needs_compaction(db_path) is False


def test_structure_cache_snapshot_works_with_raw_manifest_payload_refs(tmp_path):
    db_path = tmp_path / "raw_payload_cache.mpdb"
    db_path.write_bytes(b"demo")
    db = Mpdb(str(db_path))
    add_objects_bulk(
        db,
        [
            ManifestObject(
                guid="g-form",
                parent_guid="g-root",
                type="form",
                name="ItemForm",
                title="Item form",
                kind="object",
                payload={
                    "subtype": "object_form",
                    "form_model": {
                        "root": {
                            "id": "root",
                            "type": "Container",
                            "children": [],
                        }
                    },
                },
            ),
        ],
    )

    raw_objects = list_objects(db, hydrate_payload=False)
    assert raw_objects[0].payload.get("form_model") is None
    assert str(raw_objects[0].payload.get("form_model_ref") or "").startswith("manifest-payload/")

    meta = save_structure_cache_snapshot(
        db_path,
        db_uid="db-1",
        generated_at=123,
        objects=raw_objects,
    )

    assert load_structure_cache(db_path, db_uid="db-1", structure_hash=meta.structure_hash) is None


def test_structure_cache_snapshot_works_with_hydrated_manifest_payload_refs(tmp_path):
    db_path = tmp_path / "hydrated_payload_cache.mpdb"
    db_path.write_bytes(b"demo")
    db = Mpdb(str(db_path))
    add_objects_bulk(
        db,
        [
            ManifestObject(
                guid="g-form",
                parent_guid="g-root",
                type="form",
                name="ItemForm",
                title="Item form",
                kind="object",
                payload={
                    "subtype": "object_form",
                    "form_model": {
                        "root": {
                            "id": "root",
                            "children": [{"id": "field", "type": "Input"}],
                        }
                    },
                },
            ),
        ],
    )

    hydrated_objects = list_objects(db)
    meta = save_structure_cache_snapshot(
        db_path,
        db_uid="db-1",
        generated_at=123,
        objects=hydrated_objects,
    )

    loaded = load_structure_cache(db_path, db_uid="db-1", structure_hash=meta.structure_hash)

    assert loaded is not None
    assert loaded[0].payload["form_model"]["root"]["children"][0]["type"] == "Input"


def test_structure_cache_tolerates_sparse_unresolved_payload_refs(tmp_path):
    db_path = tmp_path / "sparse_unresolved_cache.mpdb"
    db_path.write_bytes(b"demo")

    objects = [
        ManifestObject(
            guid=f"g-{idx}",
            parent_guid="g-root" if idx else "",
            type="catalog" if idx else "configuration",
            name=f"Object{idx}",
            title=f"Object {idx}",
            kind="object" if idx else "root",
            payload={"system": idx == 0},
        )
        for idx in range(25)
    ]
    sparse = [
        {
            "guid": "g-form",
            "parent_guid": "g-root",
            "type": "form",
            "name": "ItemForm",
            "title": "Item form",
            "kind": "object",
            "payload": {
                "form_model_ref": "manifest-payload/g-form/form_model.json",
                "subtype": "object_form",
            },
        }
    ]

    meta = save_structure_cache_snapshot(
        db_path,
        db_uid="db-1",
        generated_at=123,
        objects=[*objects, *sparse],
    )

    loaded = load_structure_cache(db_path, db_uid="db-1", structure_hash=meta.structure_hash)

    assert loaded is not None
    assert len(loaded) == 26


def test_save_structure_cache_meta_only_removes_stale_full_cache(tmp_path):
    db_path = tmp_path / "meta_only_cache.mpdb"
    db_path.write_bytes(b"demo")
    save_structure_cache_snapshot(
        db_path,
        db_uid="db-1",
        generated_at=111,
        objects=[
            ManifestObject(
                guid="g-old",
                parent_guid="",
                type="configuration",
                name="Configuration",
                title="Configuration",
                kind="root",
                payload={"system": True},
            )
        ],
    )

    meta = save_structure_cache_meta_only(
        db_path,
        db_uid="db-1",
        structure_hash="new-hash",
        object_count=77,
        generated_at=222,
    )

    assert meta.structure_hash == "new-hash"
    assert meta.object_count == 77
    assert load_structure_cache(db_path, db_uid="db-1", structure_hash="new-hash") is None
