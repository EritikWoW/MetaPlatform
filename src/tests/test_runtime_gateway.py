from src.runtime.gateway import RuntimeGateway


def test_close_session_releases_rpc_session_and_clears_local_id(monkeypatch) -> None:
    captured: list[tuple[str, dict]] = []
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"

    def _fake_call(action: str, payload: dict, *, timeout: float = 30.0):
        captured.append((str(action), dict(payload)))
        return {"closed": True}

    monkeypatch.setattr(gw, "_call", _fake_call)

    assert gw.close_session() is True
    assert gw.session_id is None
    assert captured == [("session.close", {"session_id": "sid-1"})]


def test_close_session_is_best_effort_when_runtime_is_unavailable(monkeypatch) -> None:
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"
    monkeypatch.setattr(gw, "_call", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")))

    assert gw.close_session() is False
    assert gw.session_id is None


def test_manifest_info_calls_runtime_rpc_with_session(monkeypatch) -> None:
    captured: list[tuple[str, dict, float]] = []
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"

    def _fake_call(action: str, payload: dict, *, timeout: float = 30.0):
        captured.append((str(action), dict(payload), float(timeout)))
        return {"structure_hash": "abc", "object_count": 10}

    monkeypatch.setattr(gw, "_call", _fake_call)

    info = gw.manifest_info()

    assert info == {"structure_hash": "abc", "object_count": 10}
    assert captured == [
        (
            "manifest.info",
            {"session_id": "sid-1"},
            30.0,
        )
    ]


def test_manifest_schema_index_uses_dedicated_rpc(monkeypatch) -> None:
    captured: list[tuple[str, dict, float]] = []
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"

    def _fake_call(action: str, payload: dict, *, timeout: float = 30.0):
        captured.append((str(action), dict(payload), float(timeout)))
        return {"objects": [{"guid": "doc-1", "payload": {"requisites": [{"name": "Organization"}]}}]}

    monkeypatch.setattr(gw, "_call", _fake_call)

    rows = gw.manifest_schema_index()

    assert rows[0]["payload"]["requisites"][0]["name"] == "Organization"
    assert captured == [("manifest.schema_index", {"session_id": "sid-1"}, 120.0)]


def test_manifest_open_uses_extended_timeout(monkeypatch) -> None:
    captured: list[tuple[str, dict, float]] = []
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"

    def _fake_call(action: str, payload: dict, *, timeout: float = 30.0):
        captured.append((str(action), dict(payload), float(timeout)))
        return {"objects": []}

    monkeypatch.setattr(gw, "_call", _fake_call)

    result = gw.manifest_open(seed_defaults=False)

    assert result == []
    assert captured == [
        (
            "manifest.open",
            {"session_id": "sid-1", "seed_defaults": False},
            300.0,
        )
    ]


def test_manifest_get_objects_uses_session_and_default_timeout(monkeypatch) -> None:
    captured: list[tuple[str, dict, float]] = []
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"

    def _fake_call(action: str, payload: dict, *, timeout: float = 30.0):
        captured.append((str(action), dict(payload), float(timeout)))
        return {"objects": ["o-1", "o-2"]}

    monkeypatch.setattr(gw, "_call", _fake_call)

    result = gw.manifest_get_objects("guid-1")

    assert result == ["o-1", "o-2"]
    assert captured == [
        (
            "manifest.get_objects",
            {"session_id": "sid-1", "guid": "guid-1"},
            30.0,
        )
    ]


def test_manifest_get_row_uses_session_and_default_timeout(monkeypatch) -> None:
    captured: list[tuple[str, dict, float]] = []
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"

    def _fake_call(action: str, payload: dict, *, timeout: float = 30.0):
        captured.append((str(action), dict(payload), float(timeout)))
        return {"row": {"guid": "guid-1", "name": "Demo"}}

    monkeypatch.setattr(gw, "_call", _fake_call)

    result = gw.manifest_get_row("guid-1")

    assert result == {"guid": "guid-1", "name": "Demo"}
    assert captured == [
        (
            "manifest.get_row",
            {"session_id": "sid-1", "guid": "guid-1"},
            30.0,
        )
    ]


def test_manifest_lookup_uses_session_and_filters(monkeypatch) -> None:
    captured: list[tuple[str, dict, float]] = []
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"

    def _fake_call(action: str, payload: dict, *, timeout: float = 30.0):
        captured.append((str(action), dict(payload), float(timeout)))
        return {"objects": [{"guid": "attr-1", "type": "common_attribute"}]}

    monkeypatch.setattr(gw, "_call", _fake_call)

    result = gw.manifest_lookup(type_name="common_attribute", limit=25)

    assert result == [{"guid": "attr-1", "type": "common_attribute"}]
    assert captured == [
        (
            "manifest.lookup",
            {
                "session_id": "sid-1",
                "type": "common_attribute",
                "name": "",
                "limit": 25,
            },
            30.0,
        )
    ]


def test_manifest_get_subtree_uses_session_and_default_timeout(monkeypatch) -> None:
    captured: list[tuple[str, dict, float]] = []
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"

    def _fake_call(action: str, payload: dict, *, timeout: float = 30.0):
        captured.append((str(action), dict(payload), float(timeout)))
        return {"rows": [{"guid": "guid-1"}, {"guid": "child-1"}]}

    monkeypatch.setattr(gw, "_call", _fake_call)

    result = gw.manifest_get_subtree("guid-1")

    assert result == [{"guid": "guid-1"}, {"guid": "child-1"}]
    assert captured == [
        (
            "manifest.get_subtree",
            {"session_id": "sid-1", "guid": "guid-1"},
            60.0,
        )
    ]


def test_manifest_update_payload_uses_extended_timeout(monkeypatch) -> None:
    captured: list[tuple[str, dict, float]] = []
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"

    def _fake_call(action: str, payload: dict, *, timeout: float = 30.0):
        captured.append((str(action), dict(payload), float(timeout)))
        return {}

    monkeypatch.setattr(gw, "_call", _fake_call)

    gw.manifest_update_payload("guid-1", {"layout_kind": "spreadsheet_document"})

    assert captured == [
        (
            "manifest.update_payload",
            {
                "session_id": "sid-1",
                "guid": "guid-1",
                "payload": {"layout_kind": "spreadsheet_document"},
            },
            300.0,
        )
    ]


def test_manifest_bulk_update_payloads_uses_extended_timeout(monkeypatch) -> None:
    captured: list[tuple[str, dict, float]] = []
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"

    def _fake_call(action: str, payload: dict, *, timeout: float = 30.0):
        captured.append((str(action), dict(payload), float(timeout)))
        return {"updated": 2}

    monkeypatch.setattr(gw, "_call", _fake_call)

    updated = gw.manifest_bulk_update_payloads({"form-1": {}, "form-2": {"subtype": "object_form"}})

    assert updated == 2
    assert captured == [
        (
            "manifest.bulk_update_payloads",
            {
                "session_id": "sid-1",
                "payloads": {"form-1": {}, "form-2": {"subtype": "object_form"}},
            },
            600.0,
        )
    ]


def test_manifest_update_fields_uses_extended_timeout(monkeypatch) -> None:
    captured: list[tuple[str, dict, float]] = []
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"

    def _fake_call(action: str, payload: dict, *, timeout: float = 30.0):
        captured.append((str(action), dict(payload), float(timeout)))
        return {}

    monkeypatch.setattr(gw, "_call", _fake_call)

    gw.manifest_update_fields("guid-2", payload={"x": 1})

    assert captured == [
        (
            "manifest.update_fields",
            {
                "session_id": "sid-1",
                "guid": "guid-2",
                "payload": {"x": 1},
            },
            300.0,
        )
    ]


def test_modules_normalize_language_uses_extended_timeout(monkeypatch) -> None:
    captured: list[tuple[str, dict, float]] = []
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"

    def _fake_call(action: str, payload: dict, *, timeout: float = 30.0):
        captured.append((str(action), dict(payload), float(timeout)))
        return {"language": "uk", "changed": 2}

    monkeypatch.setattr(gw, "_call", _fake_call)

    result = gw.modules_normalize_language("uk")

    assert result == {"language": "uk", "changed": 2}
    assert captured == [
        (
            "modules.normalize_language",
            {"session_id": "sid-1", "language": "uk"},
            300.0,
        )
    ]


def test_manifest_object_context_rpc_uses_active_session(monkeypatch) -> None:
    captured = []
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"

    def _fake_call(action: str, payload: dict, *, timeout: float = 30.0):
        captured.append((action, payload, timeout))
        return {"guid": "owner-1", "row": {"guid": "owner-1"}, "forms": [], "modules": []}

    monkeypatch.setattr(gw, "_call", _fake_call)

    assert gw.manifest_object_context("owner-1")["guid"] == "owner-1"
    assert captured == [
        ("manifest.object_context", {"session_id": "sid-1", "guid": "owner-1"}, 30.0)
    ]


def test_module_text_rpc_methods_use_active_session(monkeypatch) -> None:
    captured: list[tuple[str, dict, float]] = []
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"

    def _fake_call(action: str, payload: dict, *, timeout: float = 30.0):
        captured.append((str(action), dict(payload), float(timeout)))
        if action == "modules.get_text":
            return {"text": "module text"}
        if action == "modules.list_by_owner":
            return {"modules": [{"module_guid": "module-1"}]}
        if action == "modules.resolve":
            return {"found": True, "module": {"module_guid": "module-2", "owner_title": "Helper"}}
        return {"updated": True}

    monkeypatch.setattr(gw, "_call", _fake_call)

    assert gw.module_get_text("module-1") == "module text"
    assert gw.modules_list_by_owner("owner-1") == [{"module_guid": "module-1"}]
    assert gw.module_resolve("Helper") == {"module_guid": "module-2", "owner_title": "Helper"}
    gw.module_update_text("module-1", "new text", updated_by="tester")

    assert captured == [
        (
            "modules.get_text",
            {"session_id": "sid-1", "module_guid": "module-1"},
            30.0,
        ),
        (
            "modules.list_by_owner",
            {"session_id": "sid-1", "owner_guid": "owner-1"},
            30.0,
        ),
        (
            "modules.resolve",
            {"session_id": "sid-1", "name": "Helper"},
            30.0,
        ),
        (
            "modules.update_text",
            {
                "session_id": "sid-1",
                "module_guid": "module-1",
                "text": "new text",
                "updated_by": "tester",
            },
            300.0,
        ),
    ]


def test_workspace_semantic_rpc_methods_use_active_session(monkeypatch) -> None:
    captured: list[tuple[str, dict, float]] = []
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"

    def _fake_call(action: str, payload: dict, *, timeout: float = 30.0):
        captured.append((str(action), dict(payload), float(timeout)))
        if action == "modules.semantic_index_info":
            return {"modules": 2, "symbols": 3}
        if action == "modules.semantic_definition":
            return {"found": True, "target": {"module_guid": "module-1", "line": 4}}
        if action == "modules.semantic_diagnostics":
            return {"diagnostics": [{"module_guid": "module-2", "code": "unresolved_member"}]}
        return {"hits": [{"module_guid": "module-2", "line": 8}]}

    monkeypatch.setattr(gw, "_call", _fake_call)

    assert gw.workspace_semantic_index_info()["modules"] == 2
    assert gw.workspace_semantic_definition("Helper", "Run")["line"] == 4
    assert gw.workspace_semantic_references("Helper", "Run", limit=25)[0]["line"] == 8
    assert gw.workspace_semantic_diagnostics(
        module_guid="module-2",
        code="unresolved_member",
        limit=10,
    )[0]["code"] == "unresolved_member"
    assert captured == [
        (
            "modules.semantic_index_info",
            {"session_id": "sid-1", "wait": False},
            120.0,
        ),
        (
            "modules.semantic_definition",
            {
                "session_id": "sid-1",
                "qualifier": "Helper",
                "name": "Run",
            },
            120.0,
        ),
        (
            "modules.semantic_references",
            {
                "session_id": "sid-1",
                "qualifier": "Helper",
                "name": "Run",
                "limit": 25,
                "include_declaration": True,
            },
            120.0,
        ),
        (
            "modules.semantic_diagnostics",
            {
                "session_id": "sid-1",
                "module_guid": "module-2",
                "code": "unresolved_member",
                "limit": 10,
            },
            120.0,
        ),
    ]


def test_workspace_rename_plan_uses_runtime_session_and_timeout(monkeypatch) -> None:
    captured: list[tuple[str, dict, float]] = []
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"

    def _fake_call(action: str, payload: dict, *, timeout: float = 30.0):
        captured.append((str(action), dict(payload), float(timeout)))
        return {"module_count": 2, "occurrence_count": 3}

    monkeypatch.setattr(gw, "_call", _fake_call)

    result = gw.modules_rename_symbol_plan(
        "module-1",
        new_name="ReadSettings",
        cursor_position=42,
        module_name="SettingsServer",
    )

    assert result == {"module_count": 2, "occurrence_count": 3}
    assert captured == [
        (
            "modules.rename_symbol_plan",
            {
                "session_id": "sid-1",
                "module_guid": "module-1",
                "new_name": "ReadSettings",
                "symbol_name": "",
                "module_name": "SettingsServer",
                "cursor_position": 42,
            },
            120.0,
        )
    ]


def test_common_module_completion_uses_runtime_session(monkeypatch) -> None:
    captured: list[tuple[str, dict, float]] = []
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"

    def _fake_call(action: str, payload: dict, *, timeout: float = 30.0):
        captured.append((str(action), dict(payload), float(timeout)))
        return {
            "found": True,
            "members": [{"name": "ReadSettings", "kind": "function"}],
        }

    monkeypatch.setattr(gw, "_call", _fake_call)

    result = gw.module_completion_members("SettingsServer")

    assert result["members"][0]["name"] == "ReadSettings"
    assert captured == [
        (
            "modules.completion_members",
            {"session_id": "sid-1", "name": "SettingsServer"},
            30.0,
        )
    ]


def test_workspace_rename_apply_sends_only_preview_hashes(monkeypatch) -> None:
    captured: list[tuple[str, dict, float]] = []
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"

    def _fake_call(action: str, payload: dict, *, timeout: float = 30.0):
        captured.append((str(action), dict(payload), float(timeout)))
        return {"applied": True, "updated": 2}

    monkeypatch.setattr(gw, "_call", _fake_call)

    result = gw.modules_rename_symbol_apply(
        "module-1",
        new_name="ReadSettings",
        symbol_name="LoadSettings",
        module_name="SettingsServer",
        modules=[
            {
                "module_guid": "module-1",
                "source_hash": "source-1",
                "updated_hash": "updated-1",
                "updated_source": "must not cross RPC",
            },
            {
                "module_guid": "module-2",
                "source_hash": "source-2",
                "updated_hash": "updated-2",
            },
        ],
    )

    assert result == {"applied": True, "updated": 2}
    assert captured == [
        (
            "modules.rename_symbol_apply",
            {
                "session_id": "sid-1",
                "module_guid": "module-1",
                "new_name": "ReadSettings",
                "symbol_name": "LoadSettings",
                "module_name": "SettingsServer",
                "updated_by": "workspace_rename",
                "modules": [
                    {
                        "module_guid": "module-1",
                        "source_hash": "source-1",
                        "updated_hash": "updated-1",
                    },
                    {
                        "module_guid": "module-2",
                        "source_hash": "source-2",
                        "updated_hash": "updated-2",
                    },
                ],
            },
            300.0,
        )
    ]


def test_schema_deploy_returns_runtime_report(monkeypatch) -> None:
    captured: list[tuple[str, dict, float]] = []
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"

    def _fake_call(action: str, payload: dict, *, timeout: float = 30.0):
        captured.append((str(action), dict(payload), float(timeout)))
        return {"created": 2, "existing": 3, "skipped": 1, "errors": []}

    monkeypatch.setattr(gw, "_call", _fake_call)

    assert gw.schema_deploy() == {"created": 2, "existing": 3, "skipped": 1, "errors": []}
    assert captured == [("schema.deploy", {"session_id": "sid-1"}, 300.0)]


def test_onec_import_status_uses_short_poll_timeout(monkeypatch) -> None:
    captured: list[tuple[str, dict, float]] = []
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"

    def _fake_call(action: str, payload: dict, *, timeout: float = 30.0):
        captured.append((str(action), dict(payload), float(timeout)))
        return {"progress": 42, "message": "enriching"}

    monkeypatch.setattr(gw, "_call", _fake_call)

    result = gw.onec_import_status(session_id="sid-import")

    assert result == {"progress": 42, "message": "enriching"}
    assert captured == [
        (
            "onec.import_status",
            {"session_id": "sid-import", "history_limit": 20},
            10.0,
        )
    ]


def test_onec_import_sessions_uses_short_timeout(monkeypatch) -> None:
    captured: list[tuple[str, dict, float]] = []
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"

    def _fake_call(action: str, payload: dict, *, timeout: float = 30.0):
        captured.append((str(action), dict(payload), float(timeout)))
        return {"sessions": [{"session_id": "sid-import", "status": "active"}]}

    monkeypatch.setattr(gw, "_call", _fake_call)

    result = gw.onec_import_sessions(active_only=True, history_limit=4)

    assert result == [{"session_id": "sid-import", "status": "active"}]
    assert captured == [
        (
            "onec.import_sessions",
            {"active_only": True, "history_limit": 4},
            10.0,
        )
    ]


def test_onec_import_attach_prefers_explicit_session_and_falls_back_to_latest_active(monkeypatch) -> None:
    captured: list[tuple[str, dict, float]] = []
    gw = RuntimeGateway("http://127.0.0.1:8765")
    gw.session_id = "sid-1"

    def _fake_call(action: str, payload: dict, *, timeout: float = 30.0):
        captured.append((str(action), dict(payload), float(timeout)))
        if action == "onec.import_sessions":
            return {"sessions": [{"session_id": "sid-active", "status": "active"}]}
        return {"session_id": "sid-explicit", "progress": 77}

    monkeypatch.setattr(gw, "_call", _fake_call)

    explicit = gw.onec_import_attach(session_id="sid-explicit", history_limit=3)
    implicit = gw.onec_import_attach(history_limit=5)

    assert explicit == {"session_id": "sid-explicit", "progress": 77}
    assert implicit == {"session_id": "sid-active", "status": "active"}
    assert captured == [
        (
            "onec.import_status",
            {"session_id": "sid-explicit", "history_limit": 3},
            10.0,
        ),
        (
            "onec.import_sessions",
            {"active_only": True, "history_limit": 5},
            10.0,
        ),
    ]


def test_post_correlates_request_id_in_body_and_header(monkeypatch) -> None:
    import json

    captured = {}

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            body = json.loads(captured["request"].data.decode("utf-8"))
            captured["body"] = body
            return json.dumps(
                {"id": body["id"], "status": "ok", "data": {"value": 1}, "error": None}
            ).encode("utf-8")

    def _urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("src.runtime.gateway.urllib.request.urlopen", _urlopen)
    gw = RuntimeGateway("http://127.0.0.1:8765")
    result = gw._post("manifest.info", {"session_id": "sid"}, timeout=2.5)

    assert result.status == "ok"
    assert result.data == {"value": 1}
    assert result.request_id == captured["body"]["id"]
    assert captured["request"].get_header("X-request-id") == result.request_id
    assert captured["timeout"] == 2.5
