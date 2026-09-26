from __future__ import annotations

import json
from pathlib import Path

import src.scripts.configurator_autopilot as autopilot
from src.configurator.configurator_actions import ConfiguratorActionsMixin


class _ActionsStub(ConfiguratorActionsMixin):
    def __init__(self, base: Path) -> None:
        self._base = base
        self.opened: list[tuple[str, str, str]] = []

    def _subsystem_membership_report_paths(self) -> list[Path]:
        return [self._base / "subsystem_membership_report.json"]

    def open_object_tab(self, info) -> None:
        self.opened.append(
            (
                str(getattr(info, "guid", "") or ""),
                str(getattr(info, "name", "") or ""),
                str(getattr(info, "obj_type", "") or ""),
            )
        )


def test_autopilot_saves_report_to_default_location(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(autopilot, "get_user_config_dir", lambda: tmp_path)

    path = autopilot._default_report_path()
    assert path == tmp_path / "subsystem_membership_report.json"
    assert autopilot._report_paths(source_path="") == [path]

    report = {"hello": "world", "nested": {"n": 1}}
    autopilot._save_report(path, report)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == report


def test_actions_export_membership_report_json_and_csv(tmp_path) -> None:
    stub = _ActionsStub(tmp_path)
    report = {
        "items": [
            {
                "guid": "sub-1",
                "name": "Administration",
                "title": "Адміністрування",
                "objects_count": 2,
                "content_refs_count": 2,
                "has_mismatch": True,
                "missing_objects": ["Catalog.Products"],
                "missing_refs": ["Catalog.Products"],
            }
        ]
    }

    json_path = stub._save_subsystem_membership_report(report)
    csv_path = stub._export_subsystem_membership_report_csv(report, tmp_path / "report.csv")

    assert json.loads(json_path.read_text(encoding="utf-8")) == report
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "Administration" in csv_text
    assert "Catalog.Products" in csv_text


def test_autopilot_report_paths_include_source_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(autopilot, "get_user_config_dir", lambda: tmp_path)
    src_file = tmp_path / "demo" / "source.1cd"
    expected = [
        tmp_path / "subsystem_membership_report.json",
        src_file.parent / "subsystem_membership_report.json",
    ]
    assert autopilot._report_paths(source_path=str(src_file)) == expected


def test_actions_auto_open_report_object_opens_first_mismatch(tmp_path) -> None:
    stub = _ActionsStub(tmp_path)
    report = {
        "items": [
            {"guid": "sub-1", "name": "Administration", "title": "Адміністрування", "has_mismatch": False},
            {"guid": "sub-2", "name": "Integration", "title": "Інтеграція", "has_mismatch": True},
        ]
    }

    stub._auto_open_report_object(report)

    assert stub.opened == [("sub-2", "Інтеграція", "subsystem")]


def test_autopilot_audit_command_shape(monkeypatch) -> None:
    calls: list[tuple[str, str, dict]] = []

    def _fake_command(base_url: str, action: str, payload: dict | None = None, *, timeout: float = 30.0):
        calls.append((base_url, action, dict(payload or {})))
        if action == "audit_source_structure":
            return {"compare": {"summary": {"flattened_subtree_count": 1, "parent_child_mismatch_count": 0}}, "final": {"summary": {"flattened_subtree_count": 0, "parent_child_mismatch_count": 0}}}
        if action == "import_status":
            return {"session_id": "sid", "state": {"status": "done", "phase": "done"}}
        if action == "sync_runtime":
            return {"tree_count": 1, "runtime_refresh_in_flight": False}
        if action == "state":
            return {"tree_count": 1, "runtime_refresh_in_flight": False}
        return {}

    monkeypatch.setattr(autopilot, "_command", _fake_command)
    monkeypatch.setattr(autopilot, "_wait_for_import_done", lambda *args, **kwargs: {"status": "done", "phase": "done"})
    monkeypatch.setattr(autopilot, "_wait_for_runtime_sync", lambda *args, **kwargs: {"tree_count": 1, "runtime_refresh_in_flight": False})
    monkeypatch.setattr(autopilot, "_wait_for_control", lambda *args, **kwargs: None)
    monkeypatch.setattr(autopilot, "_health", lambda *_args, **_kwargs: True)

    class _Args:
        control_url = "http://127.0.0.1:8766"
        runtime_url = "http://127.0.0.1:8765"
        db_uid = ""
        db_path = ""
        source_path = "F:/ConfigFiles"
        source_kind = "xml"
        wipe_prefixes = True
        migrate_data = False
        verify_guid = ""
        verify_name = ""
        verify_title = ""
        restart = False
        wait_timeout = 1.0
        report_path = ""

    monkeypatch.setattr(autopilot.argparse.ArgumentParser, "parse_args", lambda self: _Args())
    monkeypatch.setattr(autopilot, "_start_runtime", lambda *args, **kwargs: None)
    monkeypatch.setattr(autopilot, "_start_configurator", lambda *args, **kwargs: None)
    monkeypatch.setattr(autopilot, "_bootstrap_import_path", lambda: None)
    monkeypatch.setattr(autopilot.time, "sleep", lambda *_args, **_kwargs: None)

    assert autopilot.main() == 0
    assert any(action == "audit_source_structure" for _base, action, _payload in calls)
