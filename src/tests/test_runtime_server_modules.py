from types import SimpleNamespace
import threading
import time

import src.runtime.server_handlers_modules as modules_handler
from src.dsl.workspace_symbols import WorkspaceDiagnostic, WorkspaceSemanticIndex
from src.runtime.server_handlers_modules import handle_modules_action
from src.runtime.server_handlers_modules import (
    ModuleResolutionMemoryCache,
    ModuleSourceMemoryCache,
    WorkspaceSemanticIndexMemoryCache,
)


def test_modules_get_list_and_update_actions_delegate_to_runtime_db(monkeypatch) -> None:
    db = object()
    handler = SimpleNamespace(_require_db=lambda _payload: db)
    updates: list[tuple[object, str, str, str]] = []

    monkeypatch.setattr(
        modules_handler,
        "get_module_text",
        lambda actual_db, *, module_guid: "source" if actual_db is db and module_guid == "module-1" else "",
    )
    monkeypatch.setattr(
        modules_handler,
        "list_modules_by_owner",
        lambda actual_db, *, owner_guid: [{"module_guid": "module-1", "owner_guid": owner_guid}]
        if actual_db is db
        else [],
    )
    monkeypatch.setattr(
        modules_handler,
        "update_module_text",
        lambda actual_db, *, module_guid, text, updated_by: updates.append(
            (actual_db, module_guid, text, updated_by)
        ),
    )
    monkeypatch.setattr(
        modules_handler,
        "resolve_common_module",
        lambda actual_db, *, name: {
            "module_guid": "module-1",
            "owner_title": name,
            "text": "source",
        }
        if actual_db is db
        else None,
    )
    monkeypatch.setattr(
        modules_handler,
        "search_module_sources",
        lambda sources, **kwargs: [
            {
                "module_guid": kwargs.get("module_guid") or "module-1",
                "line": 3,
                "preview": kwargs["term"],
            }
        ]
        if sources == [{"module_guid": "module-1", "source_text": "Helper.Run"}]
        else [],
    )
    monkeypatch.setattr(modules_handler, "_active_db_key", lambda _payload: ("db-1", "test.mpdb"))
    monkeypatch.setattr(
        modules_handler.STATE_MODULE_SOURCE_CACHE,
        "get_or_build",
        lambda db_uid, db_path, actual_db: [{"module_guid": "module-1", "source_text": "Helper.Run"}]
        if (db_uid, db_path, actual_db) == ("db-1", "test.mpdb", db)
        else [],
    )

    get_result = handle_modules_action(handler, "modules.get_text", {"module_guid": "module-1"})
    list_result = handle_modules_action(handler, "modules.list_by_owner", {"owner_guid": "owner-1"})
    resolve_result = handle_modules_action(handler, "modules.resolve", {"name": "Helper"})
    search_result = handle_modules_action(
        handler,
        "modules.search_text",
        {"term": "Helper.Run", "whole_word": True},
    )
    update_result = handle_modules_action(
        handler,
        "modules.update_text",
        {"module_guid": "module-1", "text": "new source", "updated_by": "tester"},
    )

    assert get_result is not None and get_result.status == "ok"
    assert get_result.data["text"] == "source"
    assert list_result is not None and list_result.data["modules"][0]["owner_guid"] == "owner-1"
    assert resolve_result is not None and resolve_result.data["module"]["owner_title"] == "Helper"
    assert search_result is not None and search_result.data["hits"][0]["preview"] == "Helper.Run"
    assert update_result is not None and update_result.data["updated"] is True
    assert updates == [(db, "module-1", "new source", "tester")]


def test_modules_workspace_rename_plan_uses_cached_sources_and_manifest_aliases(
    monkeypatch,
) -> None:
    db = object()
    handler = SimpleNamespace(_require_db=lambda _payload: db)
    declaration = (
        "Function LoadSettings() Export\n"
        "    Return 1;\n"
        "EndFunction\n"
    )
    caller = "Value = SettingsServer.LoadSettings();\n"
    sources = [
        {
            "module_guid": "module-1",
            "owner_guid": "owner-1",
            "name": "Module",
            "source_text": declaration,
        },
        {
            "module_guid": "module-2",
            "owner_guid": "owner-2",
            "name": "Module",
            "source_text": caller,
        },
        {
            "module_guid": "module-3",
            "owner_guid": "owner-3",
            "name": "Unrelated",
            "source_text": "SettingsServer.LoadSettings();\n",
        },
    ]
    monkeypatch.setattr(
        modules_handler,
        "_active_db_key",
        lambda _payload: ("db-1", "test.mpdb"),
    )
    monkeypatch.setattr(
        modules_handler.STATE_MODULE_SOURCE_CACHE,
        "get_or_build",
        lambda db_uid, db_path, actual_db: sources
        if (db_uid, db_path, actual_db) == ("db-1", "test.mpdb", db)
        else [],
    )
    monkeypatch.setattr(
        modules_handler,
        "_cached_manifest_rows",
        lambda _payload: [
            {
                "guid": "owner-1",
                "name": "settings_server",
                "title": "SettingsServer",
                "payload": {"metadata_ref": "CommonModule.SettingsServer"},
            },
            {
                "guid": "owner-2",
                "name": "caller",
                "title": "ApplicationModule",
                "payload": {},
            },
        ],
    )
    semantic_index = SimpleNamespace(
        resolve=lambda qualifier, name: (
            SimpleNamespace(module_guid="module-1"),
            SimpleNamespace(symbol_id="symbol-target"),
        )
        if qualifier.casefold() == "settingsserver"
        and name.casefold() == "loadsettings"
        else None,
        references=[
            SimpleNamespace(
                target_symbol_id="symbol-target",
                module_guid="module-2",
            )
        ],
    )
    monkeypatch.setattr(
        modules_handler.STATE_WORKSPACE_SEMANTIC_INDEX,
        "get_if_current",
        lambda db_uid, db_path: semantic_index
        if (db_uid, db_path) == ("db-1", "test.mpdb")
        else None,
    )

    result = handle_modules_action(
        handler,
        "modules.rename_symbol_plan",
        {
            "module_guid": "module-1",
            "symbol_name": "LoadSettings",
            "new_name": "ReadSettings",
        },
    )

    assert result is not None and result.status == "ok"
    assert result.data["module_count"] == 2
    assert result.data["occurrence_count"] == 2
    assert result.data["qualifier_names"] == [
        "settings_server",
        "SettingsServer",
    ]
    assert result.data["modules"][1]["module_guid"] == "module-2"
    assert result.data["modules"][1]["module_name"] == "ApplicationModule"
    assert result.data["modules"][1]["occurrences"][0]["line"] == 1
    assert "updated_source" not in result.data["modules"][1]


def test_modules_completion_members_returns_only_exported_callable_symbols(
    monkeypatch,
) -> None:
    db = object()
    handler = SimpleNamespace(_require_db=lambda _payload: db)
    source = (
        "Procedure Refresh(Value) Export\n"
        "EndProcedure\n"
        "Function ReadSettings() Export\n"
        "    Return 1;\n"
        "EndFunction\n"
        "Procedure InternalOnly()\n"
        "EndProcedure\n"
    )
    monkeypatch.setattr(modules_handler, "_active_db_key", lambda _payload: None)
    monkeypatch.setattr(
        modules_handler,
        "_resolve_common_module_cached",
        lambda actual_db, _payload, name: {
            "module_guid": "module-1",
            "owner_guid": "owner-1",
            "owner_name": "settings_server",
            "owner_title": name,
            "text": source,
        }
        if actual_db is db
        else None,
    )

    result = handle_modules_action(
        handler,
        "modules.completion_members",
        {"name": "SettingsServer"},
    )

    assert result is not None and result.status == "ok"
    assert result.data["found"] is True
    assert result.data["module_guid"] == "module-1"
    assert [item["name"] for item in result.data["members"]] == [
        "ReadSettings",
        "Refresh",
    ]
    assert result.data["members"][0]["kind"] == "function"
    assert result.data["members"][1]["params"] == ["Value"]
    assert "text" not in result.data


def test_modules_workspace_semantic_index_serves_completion_definition_and_references(
    monkeypatch,
) -> None:
    db = object()
    handler = SimpleNamespace(_require_db=lambda _payload: db)
    sources = [
        {
            "module_guid": "module-settings",
            "owner_guid": "owner-settings",
            "module_kind": "module",
            "source_text": (
                "Function ReadSettings(Name) Export\n"
                "    Return Name;\n"
                "EndFunction\n"
            ),
        },
        {
            "module_guid": "module-client",
            "owner_guid": "owner-client",
            "module_kind": "module",
            "source_text": "Value = SettingsServer.ReadSettings(\"theme\");\n",
        },
    ]
    manifest = [
        {
            "guid": "owner-settings",
            "type": "common_module",
            "name": "SettingsServer",
            "title": "SettingsServer",
            "payload": {"metadata_ref": "CommonModule.SettingsServer"},
        },
        {
            "guid": "owner-client",
            "type": "configuration",
            "name": "Client",
            "title": "Client",
            "payload": {},
        },
    ]
    monkeypatch.setattr(
        modules_handler,
        "_active_db_key",
        lambda _payload: ("db-semantic", "semantic.mpdb"),
    )
    monkeypatch.setattr(
        modules_handler.STATE_MODULE_SOURCE_CACHE,
        "get_or_build",
        lambda *_args: sources,
    )
    monkeypatch.setattr(
        modules_handler,
        "_cached_manifest_rows",
        lambda _payload: manifest,
    )
    modules_handler.STATE_WORKSPACE_SEMANTIC_INDEX.invalidate("db-semantic")
    modules_handler.STATE_MODULE_COMPLETION_CACHE.invalidate("db-semantic")

    info = handle_modules_action(
        handler,
        "modules.semantic_index_info",
        {"wait": True},
    )
    completion = handle_modules_action(
        handler,
        "modules.completion_members",
        {"name": "SettingsServer"},
    )
    definition = handle_modules_action(
        handler,
        "modules.semantic_definition",
        {"qualifier": "SettingsServer", "name": "ReadSettings"},
    )
    references = handle_modules_action(
        handler,
        "modules.semantic_references",
        {"qualifier": "SettingsServer", "name": "ReadSettings"},
    )
    diagnostics = handle_modules_action(
        handler,
        "modules.semantic_diagnostics",
        {},
    )

    assert info is not None and info.status == "ok"
    assert info.data == {
        "ready": True,
        "building": False,
        "generation": 1,
        "modules": 2,
        "symbols": 1,
        "exported_symbols": 1,
        "references": 1,
        "ambiguous_aliases": 0,
        "diagnostics": 0,
        "unresolved_references": 0,
        "unresolved_modules": 0,
        "unresolved_callables": 0,
        "unresolved_requisites": 0,
        "ambiguous_references": 0,
        "form_shadow_diagnostics_filtered": 0,
        "partial_modules": 0,
        "source_gaps": 0,
    }
    assert completion is not None
    assert [row["name"] for row in completion.data["members"]] == ["ReadSettings"]
    assert definition is not None and definition.data["found"] is True
    assert definition.data["target"]["module_guid"] == "module-settings"
    assert references is not None
    assert [row["declaration"] for row in references.data["hits"]] == [True, False]
    assert references.data["hits"][1]["module_guid"] == "module-client"
    assert references.data["hits"][0]["target_symbol_id"].startswith("symbol:")
    assert diagnostics is not None and diagnostics.data["diagnostics"] == []


def test_modules_workspace_rename_apply_recomputes_and_commits_runtime_texts(
    monkeypatch,
) -> None:
    db = object()
    handler = SimpleNamespace(_require_db=lambda _payload: db)
    occurrence = SimpleNamespace(
        start=0,
        end=12,
        line=1,
        col=1,
        preview="Function ReadSettings() Export",
        declaration=True,
    )
    module = SimpleNamespace(
        module_guid="module-1",
        module_name="SettingsServer",
        source_hash="source-hash",
        updated_hash="updated-hash",
        updated_source="Function ReadSettings() Export\nEndFunction\n",
        occurrences=[occurrence],
    )
    plan = SimpleNamespace(
        declaration_module_guid="module-1",
        old_name="LoadSettings",
        new_name="ReadSettings",
        symbol_kind="function",
        qualifier_names=("SettingsServer",),
        modules=[module],
        occurrence_count=1,
    )
    applied: list[tuple[object, list[dict], str]] = []
    invalidated: list[tuple[str, str]] = []
    monkeypatch.setattr(
        modules_handler,
        "_workspace_rename_plan",
        lambda actual_db, _payload: (("db-1", "test.mpdb"), plan)
        if actual_db is db
        else None,
    )
    monkeypatch.setattr(
        modules_handler,
        "apply_module_text_updates_atomic",
        lambda actual_db, updates, *, updated_by: (
            applied.append((actual_db, list(updates), updated_by))
            or {"updated": 1, "module_guids": ["module-1"]}
        ),
    )
    monkeypatch.setattr(
        modules_handler.STATE_MODULE_RESOLUTION_CACHE,
        "invalidate",
        lambda db_uid: invalidated.append(("resolution", db_uid)),
    )
    monkeypatch.setattr(
        modules_handler.STATE_MODULE_SOURCE_CACHE,
        "invalidate",
        lambda db_uid: invalidated.append(("source", db_uid)),
    )

    result = handle_modules_action(
        handler,
        "modules.rename_symbol_apply",
        {
            "module_guid": "module-1",
            "symbol_name": "LoadSettings",
            "new_name": "ReadSettings",
            "modules": [
                {
                    "module_guid": "module-1",
                    "source_hash": "source-hash",
                    "updated_hash": "updated-hash",
                }
            ],
        },
    )

    assert result is not None and result.status == "ok"
    assert result.data["applied"] is True
    assert result.data["updated"] == 1
    assert applied == [
        (
            db,
            [
                {
                    "module_guid": "module-1",
                    "source_hash": "source-hash",
                    "updated_hash": "updated-hash",
                    "text": "Function ReadSettings() Export\nEndFunction\n",
                }
            ],
            "workspace_rename",
        )
    ]
    assert invalidated == [("resolution", "db-1"), ("source", "db-1")]


def test_modules_workspace_rename_apply_rejects_stale_preview(monkeypatch) -> None:
    db = object()
    handler = SimpleNamespace(_require_db=lambda _payload: db)
    module = SimpleNamespace(
        module_guid="module-1",
        module_name="SettingsServer",
        source_hash="current-source",
        updated_hash="current-updated",
        updated_source="updated source",
        occurrences=[],
    )
    plan = SimpleNamespace(
        declaration_module_guid="module-1",
        old_name="LoadSettings",
        new_name="ReadSettings",
        symbol_kind="function",
        qualifier_names=("SettingsServer",),
        modules=[module],
        occurrence_count=0,
    )
    monkeypatch.setattr(
        modules_handler,
        "_workspace_rename_plan",
        lambda _db, _payload: (("db-1", "test.mpdb"), plan),
    )
    monkeypatch.setattr(
        modules_handler,
        "apply_module_text_updates_atomic",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("stale preview must not be applied")
        ),
    )

    result = handle_modules_action(
        handler,
        "modules.rename_symbol_apply",
        {
            "module_guid": "module-1",
            "symbol_name": "LoadSettings",
            "new_name": "ReadSettings",
            "modules": [
                {
                    "module_guid": "module-1",
                    "source_hash": "stale-source",
                    "updated_hash": "stale-updated",
                }
            ],
        },
    )

    assert result is not None and result.status == "error"
    assert "stale" in str(result.error).lower()


def test_module_resolution_memory_cache_tracks_database_file(tmp_path) -> None:
    db_path = tmp_path / "cache.mpdb"
    db_path.write_bytes(b"one")
    cache = ModuleResolutionMemoryCache()
    module = {"module_guid": "module-1", "text": "source"}

    cache.put("db-1", str(db_path), "Helper", module)

    assert cache.get("db-1", str(db_path), "helper") == (True, module)
    db_path.write_bytes(b"changed")
    assert cache.get("db-1", str(db_path), "Helper") == (False, None)


def test_module_source_memory_cache_reuses_hydrated_sources(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "source-cache.mpdb"
    db_path.write_bytes(b"one")
    selects: list[bool] = []
    hydrations: list[str] = []
    table = SimpleNamespace(
        select=lambda where=None: selects.append(True) or [{"module_guid": "module-1", "text": "source"}]
    )
    db = SimpleNamespace(table=lambda _name: table)
    monkeypatch.setattr(
        modules_handler,
        "get_module_text_from_row",
        lambda _db, row: hydrations.append(str(row.get("module_guid") or ""))
        or str(row.get("text") or ""),
    )
    cache = ModuleSourceMemoryCache()

    first = cache.get_or_build("db-1", str(db_path), db)
    second = cache.get_or_build("db-1", str(db_path), db)
    db_path.write_bytes(b"changed")
    third = cache.get_or_build("db-1", str(db_path), db)

    assert first[0]["source_text"] == "source"
    assert second == first
    assert third == first
    assert len(selects) == 2
    assert hydrations == ["module-1"]


def test_workspace_index_status_does_not_wait_for_builder_lock(
    tmp_path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "semantic-cache.mpdb"
    db_path.write_bytes(b"db")
    entered = threading.Event()
    release = threading.Event()
    built = WorkspaceSemanticIndex(modules=(), symbols=(), references=())

    def _build(*_args, **_kwargs):
        entered.set()
        assert release.wait(2.0)
        return built

    monkeypatch.setattr(modules_handler, "build_workspace_semantic_index", _build)
    cache = WorkspaceSemanticIndexMemoryCache()
    worker = threading.Thread(
        target=lambda: cache.get_or_build(
            "db-1",
            str(db_path),
            sources=[{"module_guid": "module-1", "sha256": "hash", "version": 1}],
            manifest_rows=[],
        )
    )
    worker.start()
    assert entered.wait(1.0)

    started = time.perf_counter()
    assert cache.get_if_current("db-1", str(db_path)) is None
    elapsed = time.perf_counter() - started

    release.set()
    worker.join(timeout=2.0)
    assert elapsed < 0.1
    assert cache.get_if_current("db-1", str(db_path)) is built


def test_workspace_index_build_is_single_flight(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "semantic-single-flight.mpdb"
    db_path.write_bytes(b"db")
    entered = threading.Event()
    release = threading.Event()
    build_count = 0

    def _build(*_args, **_kwargs):
        nonlocal build_count
        build_count += 1
        entered.set()
        assert release.wait(2.0)
        return WorkspaceSemanticIndex(modules=(), symbols=(), references=())

    monkeypatch.setattr(modules_handler, "build_workspace_semantic_index", _build)
    cache = WorkspaceSemanticIndexMemoryCache()
    kwargs = {
        "sources": [{"module_guid": "module-1", "sha256": "hash", "version": 1}],
        "manifest_rows": [],
    }
    results: list[WorkspaceSemanticIndex] = []
    first = threading.Thread(
        target=lambda: results.append(
            cache.get_or_build("db-1", str(db_path), **kwargs)
        )
    )
    second = threading.Thread(
        target=lambda: results.append(
            cache.get_or_build("db-1", str(db_path), **kwargs)
        )
    )
    first.start()
    assert entered.wait(1.0)
    second.start()
    release.set()
    first.join(timeout=2.0)
    second.join(timeout=2.0)

    assert build_count == 1
    assert len(results) == 2
    assert results[0] is results[1]


def test_workspace_index_cache_rebuilds_when_manifest_schema_changes(
    tmp_path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "semantic-manifest-cache.mpdb"
    db_path.write_bytes(b"db")
    builds: list[list[dict]] = []

    def _build(_sources, *, owners_by_guid):
        builds.append([dict(item) for item in owners_by_guid.values()])
        return WorkspaceSemanticIndex(modules=(), symbols=(), references=())

    monkeypatch.setattr(modules_handler, "build_workspace_semantic_index", _build)
    cache = WorkspaceSemanticIndexMemoryCache()
    sources = [{"module_guid": "module-1", "sha256": "hash", "version": 1}]
    first_manifest = [
        {
            "guid": "owner-1",
            "type": "document",
            "name": "Sales",
            "payload": {"requisites": [{"name": "Organization"}]},
        }
    ]
    second_manifest = [
        {
            "guid": "owner-1",
            "type": "document",
            "name": "Sales",
            "payload": {"requisites": [{"name": "Warehouse"}]},
        }
    ]

    first = cache.get_or_build(
        "db-1",
        str(db_path),
        sources=sources,
        manifest_rows=first_manifest,
    )
    cached = cache.get_or_build(
        "db-1",
        str(db_path),
        sources=sources,
        manifest_rows=first_manifest,
    )
    rebuilt = cache.get_or_build(
        "db-1",
        str(db_path),
        sources=sources,
        manifest_rows=second_manifest,
    )

    assert cached is first
    assert rebuilt is not first
    assert len(builds) == 2


def test_workspace_index_hydrates_only_diagnostic_form_owners(
    tmp_path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "semantic-form-shadow.mpdb"
    db_path.write_bytes(b"db")
    diagnostic = WorkspaceDiagnostic(
        code="unresolved_member",
        severity="warning",
        message="Missing exported member",
        module_guid="module-form",
        owner_guid="owner-form",
        line=5,
        qualifier="Users",
        name="Clear",
    )
    monkeypatch.setattr(
        modules_handler,
        "build_workspace_semantic_index",
        lambda *_args, **_kwargs: WorkspaceSemanticIndex(
            modules=(),
            symbols=(),
            references=(),
            diagnostics=(diagnostic,),
        ),
    )
    loaded: list[str] = []
    cache = WorkspaceSemanticIndexMemoryCache()

    index = cache.get_or_build(
        "db-1",
        str(db_path),
        sources=[],
        manifest_rows=[
            {"guid": "owner-form", "type": "form", "payload": {}},
            {"guid": "owner-document", "type": "document", "payload": {}},
        ],
        owner_payload_loader=lambda guid: (
            loaded.append(guid)
            or {
                "form_model": {
                    "root": {
                        "name": "Form",
                        "children": [{"name": "Users", "children": []}],
                    }
                }
            }
        ),
    )

    assert index.list_diagnostics() == []
    assert index.stats()["form_shadow_diagnostics_filtered"] == 1
    assert loaded == ["owner-form"]


def test_semantic_owner_loader_fetches_form_model_ref_from_raw_manifest(
    monkeypatch,
) -> None:
    raw_payload = {
        "metadata_ref": "DataProcessor.Sample",
        "form_model_ref": "manifest-payload/form/form_model.json",
    }
    hydrated_payload = {
        **raw_payload,
        "form_model": {"root": {"name": "Form", "children": []}},
    }

    class _Table:
        def select(self, *, where):
            assert where == {"guid": "owner-form"}
            return [{"guid": "owner-form", "payload": raw_payload}]

    db = SimpleNamespace(table=lambda _name: _Table())
    monkeypatch.setattr(
        "src.configurator.persistence.manifest_io._hydrate_manifest_payload",
        lambda actual_db, payload: (
            hydrated_payload
            if actual_db is db and payload == raw_payload
            else dict(payload or {})
        ),
    )

    loader = modules_handler._semantic_owner_payload_loader(
        db,
        [
            {
                "guid": "owner-form",
                "type": "form",
                "payload": {"metadata_ref": "DataProcessor.Sample"},
            }
        ],
    )

    assert loader("owner-form") == hydrated_payload
