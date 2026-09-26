from src.configurator.persistence.manifest_io import (
    add_objects_bulk,
    build_manifest_schema_index,
    bulk_update_payloads,
    ensure_manifest_table,
    list_objects,
    make_object,
    update_payload,
)
import src.configurator.persistence.manifest_io as manifest_io
from src.configurator.manifest_schema import MANIFEST_TABLE
from src.mpdb.mpdb import Mpdb


def test_bulk_update_payloads_updates_multiple_rows_in_one_pass(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "bulk_manifest.mpdb"))
    ensure_manifest_table(db)

    table = db.table(MANIFEST_TABLE)
    table.insert(
        {
            "guid": "g-1",
            "type": "catalog",
            "name": "Products",
            "title": "Products",
            "kind": "object",
            "parent_guid": "",
            "payload": {"a": 1},
        }
    )
    table.insert(
        {
            "guid": "g-2",
            "type": "document",
            "name": "Sales",
            "title": "Sales",
            "kind": "object",
            "parent_guid": "",
            "payload": {"b": 2},
        }
    )

    updated = bulk_update_payloads(
        db,
        {
            "g-1": {"x": 10},
            "g-2": {"y": 20},
        },
    )

    assert updated == 2

    rows = {str(r.get("guid") or ""): r for r in table.select()}
    assert rows["g-1"]["payload"] == {"x": 10}
    assert rows["g-2"]["payload"] == {"y": 20}
    manifest_indexes = set(db._meta.get("indexes", {}).get(MANIFEST_TABLE, {}).keys())
    assert manifest_indexes == {"guid", "parent_guid"}


def test_add_objects_bulk_externalizes_large_form_model_payload(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "bulk_manifest_form_payload.mpdb"))
    ensure_manifest_table(db)

    big_form_model = {
        "title": "Big form",
        "root": {
            "id": "root",
            "children": [{"id": f"n{i}", "type": "Input", "props": {"caption": "X" * 200}} for i in range(150)],
        },
    }
    mo = make_object(
        obj_type="form",
        name="BigForm",
        title="Big Form",
        parent_guid="",
        payload={"form_model": big_form_model, "subtype": "object_form"},
    )

    inserted = add_objects_bulk(db, [mo])
    assert inserted == 1

    raw_row = db.table(MANIFEST_TABLE).select(where={"guid": mo.guid})[0]
    raw_payload = raw_row["payload"]
    assert "form_model" not in raw_payload
    assert str(raw_payload.get("form_model_ref") or "").startswith("manifest-payload/")

    obj = next(item for item in list_objects(db) if item.guid == mo.guid)
    assert obj.payload["form_model"]["title"] == "Big form"
    assert len(obj.payload["form_model"]["root"]["children"]) == 150


def test_add_objects_bulk_can_refresh_existing_import_identity(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "bulk_manifest_refresh.mpdb"))
    ensure_manifest_table(db)
    original = make_object(
        guid="source-guid",
        obj_type="common_module",
        name="StandartnyePodsystemyPovtYsp",
        title="Old title",
        parent_guid="folder",
        payload={"imported": {"source": "1c"}},
    )
    assert add_objects_bulk(db, [original]) == 1

    refreshed = make_object(
        guid="source-guid",
        obj_type="common_module",
        name="СтандартныеПодсистемыПовтИсп",
        title="Стандартні підсистеми повт вик",
        parent_guid="folder",
        payload={
            "imported": {"source": "1c"},
            "code_ref_uk": "ЗагальнийМодуль.СтандартніПідсистемиПовтВик",
            "code_ref_en": "CommonModule.StandardSubsystemsReuse",
        },
    )
    assert add_objects_bulk(db, [refreshed], update_existing=True) == 1

    row = db.table(MANIFEST_TABLE).select(where={"guid": "source-guid"})[0]
    assert row["name"] == "СтандартныеПодсистемыПовтИсп"
    assert row["title"] == "Стандартні підсистеми повт вик"
    assert row["payload"]["code_ref_en"] == "CommonModule.StandardSubsystemsReuse"


def test_add_objects_bulk_externalizes_large_requisites_payload(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "bulk_manifest_requisites_payload.mpdb"))
    ensure_manifest_table(db)

    big_requisites = [
        {
            "name": f"Req{i}",
            "title": "R" * 120,
            "type": "String",
            "comment": "X" * 220,
        }
        for i in range(220)
    ]
    mo = make_object(
        obj_type="document",
        name="BigDocument",
        title="Big Document",
        parent_guid="",
        payload={"requisites": big_requisites, "title": "Big Document"},
    )

    inserted = add_objects_bulk(db, [mo])
    assert inserted == 1

    raw_row = db.table(MANIFEST_TABLE).select(where={"guid": mo.guid})[0]
    raw_payload = raw_row["payload"]
    assert "requisites" not in raw_payload
    assert str(raw_payload.get("requisites_ref") or "").startswith("manifest-payload/")

    db.close()
    db = Mpdb(str(tmp_path / "bulk_manifest_requisites_payload.mpdb"))
    obj = next(item for item in list_objects(db) if item.guid == mo.guid)
    assert len(obj.payload["requisites"]) == 220


def test_manifest_schema_index_reads_only_tree_schema_assets(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "manifest_schema_index.mpdb"))
    ensure_manifest_table(db)

    mo = make_object(
        obj_type="document",
        name="AdvanceReport",
        title="Advance report",
        parent_guid="",
        payload={
            "requisites": [{"name": "Organization", "title": {"uk": "Організація"}}],
            "attributes": [{"name": "number", "title": {"uk": "Номер"}}],
            "tabular_parts": [
                {
                    "name": "Items",
                    "title": {"uk": "Товари"},
                    "columns": [{"name": "Amount", "title": {"uk": "Сума"}}],
                }
            ],
            "form_model": {"root": {"children": [{"id": "must-not-load"}]}},
        },
    )
    add_objects_bulk(db, [mo])
    slim_rows = [
        {
            "guid": mo.guid,
            "type": mo.type,
            "kind": mo.kind,
            "name": mo.name,
            "title": mo.title,
            "parent_guid": mo.parent_guid,
            "payload": {},
        }
    ]

    index = build_manifest_schema_index(db, slim_rows)

    assert len(index) == 1
    payload = index[0]["payload"]
    assert payload["requisites"][0]["name"] == "Organization"
    assert payload["attributes"][0]["name"] == "number"
    assert payload["tabular_parts"][0]["columns"][0]["name"] == "Amount"
    assert "form_model" not in payload


def test_add_objects_bulk_batches_externalized_payload_asset_writes(tmp_path, monkeypatch) -> None:
    db = Mpdb(str(tmp_path / "bulk_manifest_batch_assets.mpdb"))
    ensure_manifest_table(db)

    objects = [
        make_object(
            obj_type="form",
            name=f"Form{i}",
            title=f"Form {i}",
            parent_guid="",
            payload={
                "subtype": "object_form",
                "form_model": {
                    "title": f"Form {i}",
                    "root": {
                        "id": f"root-{i}",
                        "children": [
                            {"id": f"n{i}-{j}", "type": "Input", "props": {"caption": "X" * 120}}
                            for j in range(40)
                        ],
                    },
                },
            },
        )
        for i in range(3)
    ]

    def _fail_put_asset(*_args, **_kwargs):
        raise AssertionError("add_objects_bulk should batch manifest payload assets via put_assets_bulk")

    monkeypatch.setattr(db, "put_asset", _fail_put_asset)

    inserted = add_objects_bulk(db, objects)

    assert inserted == 3
    loaded = list_objects(db)
    assert len(loaded) == 3
    assert all(item.payload["form_model"]["root"]["children"][0]["type"] == "Input" for item in loaded)


def test_list_objects_prefetches_externalized_payload_assets_in_batch(tmp_path, monkeypatch) -> None:
    db = Mpdb(str(tmp_path / "bulk_manifest_prefetch.mpdb"))
    ensure_manifest_table(db)

    objects = [
        make_object(
            obj_type="form",
            name=f"Form{i}",
            title=f"Form {i}",
            parent_guid="",
            payload={
                "subtype": "object_form",
                "form_model": {
                    "root": {
                        "id": f"root-{i}",
                        "children": [{"id": f"n{i}", "type": "Input"}],
                    }
                },
            },
        )
        for i in range(3)
    ]
    add_objects_bulk(db, objects)

    def _fail_get_asset(*_args, **_kwargs):
        raise AssertionError("list_objects should prefetch manifest payload assets without per-ref get_asset calls")

    monkeypatch.setattr(db, "get_asset", _fail_get_asset)

    loaded = list_objects(db)

    assert len(loaded) == 3
    assert all(obj.payload["form_model"]["root"]["children"][0]["type"] == "Input" for obj in loaded)


def test_update_payload_fast_path_reuses_externalized_layout_asset_without_manifest_rebuild(tmp_path, monkeypatch) -> None:
    db = Mpdb(str(tmp_path / "bulk_manifest_fast_layout_update.mpdb"))
    ensure_manifest_table(db)

    mo = make_object(
        obj_type="layout",
        name="Layout1",
        title="Layout 1",
        parent_guid="",
        payload={
            "layout_kind": "spreadsheet_document",
            "layout_model": {
                "kind": "spreadsheet_document",
                "row_count": 1,
                "column_count": 1,
                "cells": [{"row": 0, "col": 0, "text": "before"}],
            },
        },
    )
    add_objects_bulk(db, [mo])

    raw_row = db.table(MANIFEST_TABLE).select(where={"guid": mo.guid})[0]
    raw_payload = raw_row["payload"]
    layout_ref = str(raw_payload.get("layout_model_ref") or "")
    assert layout_ref.startswith("manifest-payload/")

    def _fail_rebuild(*_args, **_kwargs):
        raise AssertionError("manifest rebuild should not happen for externalized-only layout update")

    monkeypatch.setattr(manifest_io, "_rebuild_manifest", _fail_rebuild)

    update_payload(
        db,
        mo.guid,
        {
            "layout_kind": "spreadsheet_document",
            "layout_model_ref": layout_ref,
            "layout_model": {
                "kind": "spreadsheet_document",
                "row_count": 1,
                "column_count": 1,
                "cells": [{"row": 0, "col": 0, "text": "after"}],
            },
        },
    )

    raw_row_after = db.table(MANIFEST_TABLE).select(where={"guid": mo.guid})[0]
    assert raw_row_after["payload"]["layout_model_ref"] == layout_ref
    obj = next(item for item in list_objects(db) if item.guid == mo.guid)
    assert obj.payload["layout_model"]["cells"][0]["text"] == "after"


def test_bulk_update_payloads_externalizes_large_subsystem_objects_payload(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "bulk_manifest_subsystem_objects.mpdb"))
    ensure_manifest_table(db)

    mo = make_object(
        obj_type="subsystem",
        name="BigSubsystem",
        title="Big Subsystem",
        parent_guid="",
        payload={"include_in_command_interface": True},
    )
    add_objects_bulk(db, [mo])

    big_objects = [f"guid-{i:05d}" for i in range(2500)]
    updated = bulk_update_payloads(
        db,
        {
            mo.guid: {
                "include_in_command_interface": True,
                "objects": big_objects,
            }
        },
    )

    assert updated == 1

    raw_row = db.table(MANIFEST_TABLE).select(where={"guid": mo.guid})[0]
    raw_payload = raw_row["payload"]
    assert "objects" not in raw_payload
    assert str(raw_payload.get("objects_ref") or "").startswith("manifest-payload/")

    obj = next(item for item in list_objects(db) if item.guid == mo.guid)
    assert obj.payload["objects"][:3] == ["guid-00000", "guid-00001", "guid-00002"]
    assert len(obj.payload["objects"]) == 2500


def test_update_payload_externalizes_large_subsystem_objects_payload(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "update_payload_subsystem_objects.mpdb"))
    ensure_manifest_table(db)

    mo = make_object(
        obj_type="subsystem",
        name="EditorSubsystem",
        title="Editor Subsystem",
        parent_guid="",
        payload={"include_in_command_interface": False},
    )
    add_objects_bulk(db, [mo])

    big_objects = [f"guid-{i:05d}" for i in range(1800)]
    update_payload(
        db,
        mo.guid,
        {
            "include_in_command_interface": False,
            "objects": big_objects,
        },
    )

    raw_row = db.table(MANIFEST_TABLE).select(where={"guid": mo.guid})[0]
    raw_payload = raw_row["payload"]
    assert "objects" not in raw_payload
    assert str(raw_payload.get("objects_ref") or "").startswith("manifest-payload/")

    obj = next(item for item in list_objects(db) if item.guid == mo.guid)
    assert obj.payload["objects"][-1] == "guid-01799"
    assert len(obj.payload["objects"]) == 1800


def test_bulk_update_payloads_externalizes_large_register_dimension_payloads(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "bulk_manifest_register_dimensions.mpdb"))
    ensure_manifest_table(db)

    mo = make_object(
        obj_type="register_accum",
        name="BigRegister",
        title="Big Register",
        parent_guid="",
        payload={"include_in_command_interface": True},
    )
    add_objects_bulk(db, [mo])

    dimensions = [
        {
            "name": f"Dimension{i}",
            "title": "D" * 80,
            "type": "CatalogRef.Products",
            "comment": "X" * 120,
        }
        for i in range(80)
    ]
    resources = [
        {
            "name": f"Resource{i}",
            "title": "R" * 80,
            "type": "Number",
            "comment": "Y" * 120,
        }
        for i in range(80)
    ]
    attributes = [
        {
            "name": f"Attribute{i}",
            "title": "A" * 80,
            "type": "String",
            "comment": "Z" * 120,
        }
        for i in range(80)
    ]

    updated = bulk_update_payloads(
        db,
        {
            mo.guid: {
                "include_in_command_interface": True,
                "dimensions": dimensions,
                "resources": resources,
                "attributes": attributes,
            }
        },
    )

    assert updated == 1

    raw_row = db.table(MANIFEST_TABLE).select(where={"guid": mo.guid})[0]
    raw_payload = raw_row["payload"]
    assert "dimensions" not in raw_payload
    assert "resources" not in raw_payload
    assert "attributes" not in raw_payload
    assert str(raw_payload.get("dimensions_ref") or "").startswith("manifest-payload/")
    assert str(raw_payload.get("resources_ref") or "").startswith("manifest-payload/")
    assert str(raw_payload.get("attributes_ref") or "").startswith("manifest-payload/")

    obj = next(item for item in list_objects(db) if item.guid == mo.guid)
    assert len(obj.payload["dimensions"]) == 80
    assert len(obj.payload["resources"]) == 80
    assert len(obj.payload["attributes"]) == 80
