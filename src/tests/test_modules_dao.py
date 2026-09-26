from src.configurator.persistence import modules_dao
from src.configurator.persistence.modules_dao import (
    apply_module_text_updates_atomic,
    get_module_text,
    get_module_text_from_row,
    list_modules_by_owner,
    normalize_modules_language,
    resolve_common_module,
    search_module_text,
    upsert_module,
    write_module_reference_map,
)
from src.configurator.persistence.manifest_io import ensure_manifest_table
from src.configurator.persistence.modules_tables import MODULES_TABLE, ensure_modules_tables
from src.mpdb.mpdb import Mpdb


def test_module_reference_registry_preserves_localized_aliases(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "module_refs.mpdb"))
    guid = upsert_module(
        db,
        owner_guid="owner",
        owner_kind="common_module",
        module_kind="Module",
        name="Module",
        text="",
        source_ref="CommonModules/СтандартныеПодсистемыПовтИсп/Ext/Module.bsl",
        canonical_ref="CommonModule.СтандартныеПодсистемыПовтИсп.Module",
        ref_uk="ЗагальнийМодуль.СтандартніПідсистемиПовтВик.Модуль",
        ref_en="CommonModule.StandardSubsystemsReuse.Module",
    )

    row = db.table(MODULES_TABLE).select(where={"module_guid": guid})[0]
    assert row["ref_uk"].startswith("ЗагальнийМодуль.")
    assert row["ref_en"].startswith("CommonModule.")
    assert write_module_reference_map(db) == 1
    payload, _mime = db.get_asset("system/module-reference-map.json")
    assert guid.encode("utf-8") in payload
    assert "СтандартніПідсистемиПовтВик".encode("utf-8") in payload


def test_normalize_modules_language_uses_bulk_replace_and_preserves_asset_rows(tmp_path, monkeypatch) -> None:
    db = Mpdb(str(tmp_path / "modules_normalize.mpdb"))

    inline_guid = upsert_module(
        db,
        owner_guid="owner-inline",
        owner_kind="common_module",
        module_kind="module",
        name="InlineModule",
        text="If Value Then\nEndIf",
        updated_by="test",
    )
    asset_guid = upsert_module(
        db,
        owner_guid="owner-asset",
        owner_kind="common_module",
        module_kind="module",
        name="AssetModule",
        text=("If Value Then\nEndIf\n" * 3000),
        updated_by="test",
    )

    asset_row_before = list_modules_by_owner(db, owner_guid="owner-asset")[0]
    asset_ref_before = str(asset_row_before.get("content_ref") or "")
    assert str(asset_row_before.get("storage_kind") or "") == "asset"
    assert asset_ref_before.startswith("module-src/")

    def _fail_update(*_args, **_kwargs):
        raise AssertionError("normalize_modules_language must not use per-row update_module_text")

    monkeypatch.setattr(modules_dao, "update_module_text", _fail_update)

    stats = normalize_modules_language(db, language="uk", updated_by="normalize")

    assert stats["changed"] == 2
    assert "Якщо" in get_module_text(db, module_guid=inline_guid)
    assert "Якщо" in get_module_text(db, module_guid=asset_guid)

    asset_row_after = list_modules_by_owner(db, owner_guid="owner-asset")[0]
    assert str(asset_row_after.get("storage_kind") or "") == "asset"
    assert str(asset_row_after.get("content_ref") or "") == asset_ref_before
    assert int(asset_row_after.get("version") or 0) == int(asset_row_before.get("version") or 0) + 1


def test_get_module_text_cleans_raw_artifact_lines(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "modules_clean.mpdb"))
    ensure_modules_tables(db)
    raw_text = (
        "\ufeff////////////////////////////////////////////////////////////////////////////////\n"
        "00000018 00000018 7fffffff\n"
        "\ufffdB|\ufffdMB\ufffdtext\n"
        "#Область ПрограммныйИнтерфейс\n"
        "Процедура Тест() Экспорт\n"
        "КонецПроцедуры\n"
    )
    db.table(MODULES_TABLE).insert(
        {
            "module_guid": "11111111-2222-3333-4444-555555555555",
            "owner_guid": "owner",
            "owner_kind": "common_module",
            "module_kind": "module",
            "name": "Test",
            "lang": "",
            "text": raw_text,
            "sha256": "raw-sha",
            "version": 1,
            "updated_at": 1,
            "updated_by": "test",
            "storage_kind": "inline",
            "content_ref": "",
            "size_bytes": len(raw_text.encode("utf-8")),
        }
    )

    cleaned = get_module_text(db, module_guid="11111111-2222-3333-4444-555555555555")
    cleaned_from_row = get_module_text_from_row(
        db,
        db.table(MODULES_TABLE).select(where={"module_guid": "11111111-2222-3333-4444-555555555555"})[0],
    )

    assert "00000018 00000018 7fffffff" not in cleaned
    assert "\ufffd" not in cleaned
    assert "Процедура Тест() Экспорт" in cleaned
    assert cleaned == cleaned_from_row


def test_apply_module_text_updates_atomic_updates_all_rows(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "modules_atomic.mpdb"))
    first_guid = upsert_module(
        db,
        owner_guid="owner-one",
        owner_kind="common_module",
        module_kind="module",
        name="Module",
        text="Procedure First()\nEndProcedure\n",
        updated_by="test",
    )
    second_guid = upsert_module(
        db,
        owner_guid="owner-two",
        owner_kind="common_module",
        module_kind="module",
        name="Module",
        text="Procedure Second()\nEndProcedure\n",
        updated_by="test",
    )
    first_before = get_module_text(db, module_guid=first_guid)
    second_before = get_module_text(db, module_guid=second_guid)

    result = apply_module_text_updates_atomic(
        db,
        [
            {
                "module_guid": first_guid,
                "source_hash": modules_dao._sha256_text(first_before),
                "text": first_before.replace("First", "RenamedFirst"),
            },
            {
                "module_guid": second_guid,
                "source_hash": modules_dao._sha256_text(second_before),
                "text": second_before.replace("Second", "RenamedSecond"),
            },
        ],
        updated_by="rename-test",
    )

    assert result == {
        "updated": 2,
        "module_guids": [first_guid, second_guid],
    }
    assert "RenamedFirst" in get_module_text(db, module_guid=first_guid)
    assert "RenamedSecond" in get_module_text(db, module_guid=second_guid)
    first_row = list_modules_by_owner(db, owner_guid="owner-one")[0]
    second_row = list_modules_by_owner(db, owner_guid="owner-two")[0]
    assert int(first_row["version"]) == 2
    assert int(second_row["version"]) == 2
    assert first_row["updated_by"] == "rename-test"


def test_apply_module_text_updates_atomic_rejects_stale_plan_without_changes(
    tmp_path,
) -> None:
    db = Mpdb(str(tmp_path / "modules_atomic_stale.mpdb"))
    first_guid = upsert_module(
        db,
        owner_guid="owner-one",
        owner_kind="common_module",
        module_kind="module",
        name="Module",
        text="Procedure First()\nEndProcedure\n",
        updated_by="test",
    )
    second_guid = upsert_module(
        db,
        owner_guid="owner-two",
        owner_kind="common_module",
        module_kind="module",
        name="Module",
        text="Procedure Second()\nEndProcedure\n",
        updated_by="test",
    )
    first_before = get_module_text(db, module_guid=first_guid)
    second_before = get_module_text(db, module_guid=second_guid)

    import pytest

    with pytest.raises(ValueError, match="changed after preview"):
        apply_module_text_updates_atomic(
            db,
            [
                {
                    "module_guid": first_guid,
                    "source_hash": modules_dao._sha256_text(first_before),
                    "text": first_before.replace("First", "RenamedFirst"),
                },
                {
                    "module_guid": second_guid,
                    "source_hash": "stale-hash",
                    "text": second_before.replace("Second", "RenamedSecond"),
                },
            ],
        )

    assert get_module_text(db, module_guid=first_guid) == first_before
    assert get_module_text(db, module_guid=second_guid) == second_before


def test_apply_module_text_updates_atomic_keeps_large_assets_immutable(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "modules_atomic_assets.mpdb"))
    source = "Procedure Large()\n" + ("Message(\"old\");\n" * 4000) + "EndProcedure\n"
    module_guid = upsert_module(
        db,
        owner_guid="owner-large",
        owner_kind="common_module",
        module_kind="module",
        name="Module",
        text=source,
        updated_by="test",
    )
    row_before = list_modules_by_owner(db, owner_guid="owner-large")[0]
    ref_before = str(row_before["content_ref"])
    updated = source.replace('"old"', '"new"')

    apply_module_text_updates_atomic(
        db,
        [
            {
                "module_guid": module_guid,
                "source_hash": modules_dao._sha256_text(source),
                "updated_hash": modules_dao._sha256_text(updated),
                "text": updated,
            }
        ],
    )

    row_after = list_modules_by_owner(db, owner_guid="owner-large")[0]
    ref_after = str(row_after["content_ref"])
    assert ref_after != ref_before
    assert ref_after.startswith(f"module-src/{module_guid}-")
    old_asset, _ = db.get_asset(ref_before)
    assert b'"old"' in old_asset
    assert '"new"' in get_module_text(db, module_guid=module_guid)


def test_resolve_common_module_matches_imported_title_and_returns_source(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "modules_resolve.mpdb"))
    ensure_manifest_table(db)
    db.table("manifest").insert(
        {
            "guid": "owner-guid",
            "type": "common_module",
            "kind": "object",
            "name": "StartupHelper",
            "title": "СтартовыйПомощник",
            "parent_guid": "common",
            "payload": {"metadata_ref": "CommonModule.СтартовыйПомощник"},
        }
    )
    module_guid = upsert_module(
        db,
        owner_guid="owner-guid",
        owner_kind="meta_object",
        module_kind="Module",
        name="Module",
        text="Функція Value() Експорт\nПовернути 42\nКінецьФункції",
        canonical_ref="CommonModule.СтартовыйПомощник.Module",
        ref_uk="ЗагальнийМодуль.СтартовийПомічник.Модуль",
        ref_en="CommonModule.StartupAssistant.Module",
        updated_by="test",
    )

    resolved = resolve_common_module(db, name="СтартовыйПомощник")
    cached_resolved = resolve_common_module(
        db,
        name="СтартовыйПомощник",
        manifest_rows=[
            {
                "guid": "owner-guid",
                "type": "common_module",
                "kind": "object",
                "name": "StartupHelper",
                "title": "СтартовыйПомощник",
                "parent_guid": "common",
                "payload": {"metadata_ref": "CommonModule.СтартовыйПомощник"},
            }
        ],
    )

    assert resolved is not None
    assert resolved["module_guid"] == module_guid
    assert resolved["owner_name"] == "StartupHelper"
    assert "Повернути 42" in resolved["text"]
    assert cached_resolved is not None
    assert cached_resolved["module_guid"] == module_guid
    assert resolve_common_module(db, name="СтартовийПомічник")["module_guid"] == module_guid
    assert resolve_common_module(db, name="StartupAssistant")["module_guid"] == module_guid


def test_search_module_text_returns_all_unicode_identifier_hits(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "modules_search.mpdb"))
    first_guid = upsert_module(
        db,
        owner_guid="owner-one",
        owner_kind="meta_object",
        module_kind="Module",
        name="Module",
        text=(
            "Функція ОтриматиДані() Експорт\n"
            "Повернути 1;\n"
            "КінецьФункції\n"
            "Значення = СпільнийСервер.ОтриматиДані();"
        ),
        updated_by="test",
    )
    upsert_module(
        db,
        owner_guid="owner-two",
        owner_kind="meta_object",
        module_kind="Module",
        name="Module",
        text="Результат = СпільнийСервер.ОтриматиДані(); // ОтриматиДаніДодатково",
        updated_by="test",
    )

    qualified = search_module_text(
        db,
        term="СпільнийСервер.ОтриматиДані",
        whole_word=True,
    )
    local = search_module_text(
        db,
        term="ОтриматиДані",
        whole_word=True,
        module_guid=first_guid,
    )

    assert len(qualified) == 2
    assert {hit["owner_guid"] for hit in qualified} == {"owner-one", "owner-two"}
    assert [hit["line"] for hit in local] == [1, 4]
    assert all("ОтриматиДаніДодатково" not in hit["preview"] for hit in local)
