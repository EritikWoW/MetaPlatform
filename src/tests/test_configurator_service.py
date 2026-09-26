import pytest

from src.configurator.application.service import ConfiguratorService
from src.configurator.manifest_schema import ManifestObject


def test_merge_schema_index_restores_requisites_and_tabular_parts() -> None:
    objects = [
        ManifestObject(
            guid="doc-1",
            type="document",
            name="AdvanceReport",
            title="Advance report",
            payload={"metadata_ref": "Document.AdvanceReport"},
        )
    ]
    schema_rows = [
        {
            "guid": "doc-1",
            "payload": {
                "requisites": [{"name": "Organization"}],
                "tabular_parts": [{"name": "Items", "columns": [{"name": "Amount"}]}],
            },
        }
    ]

    merged = ConfiguratorService._merge_schema_index(objects, schema_rows)

    assert merged[0].payload["metadata_ref"] == "Document.AdvanceReport"
    assert merged[0].payload["requisites"][0]["name"] == "Organization"
    assert merged[0].payload["tabular_parts"][0]["columns"][0]["name"] == "Amount"


def test_open_db_uses_manifest_list_for_non_empty_db_on_cache_miss(monkeypatch) -> None:
    calls: list[str] = []

    class FakeGateway:
        def __init__(self, base_url: str) -> None:
            self.base_url = base_url

        def open_by_uid(self, db_uid: str):
            calls.append(f"open_by_uid:{db_uid}")
            return {"db_uid": db_uid}

        def manifest_info(self) -> dict:
            calls.append("manifest_info")
            return {
                "db_uid": "db-1",
                "db_path": r"F:\tmp\demo.mpdb",
                "structure_hash": "hash-1",
                "object_count": 2,
                "generated_at": 123,
            }

        def manifest_list(self) -> list[dict]:
            calls.append("manifest_list")
            return [
                {
                    "guid": "g-1",
                    "parent_guid": "",
                    "type": "configuration",
                    "name": "Configuration",
                    "title": "Configuration",
                    "kind": "root",
                    "payload": {"system": True},
                },
                {
                    "guid": "g-2",
                    "parent_guid": "g-1",
                    "type": "catalog",
                    "name": "Products",
                    "title": "Products",
                    "kind": "object",
                    "payload": {},
                },
            ]

        def manifest_open(self, *, seed_defaults: bool = True) -> list[dict]:
            calls.append(f"manifest_open:{seed_defaults}")
            raise AssertionError("open_db should use manifest_list for non-empty DB cache miss")

    monkeypatch.setattr("src.configurator.application.service.RuntimeGateway", FakeGateway)
    monkeypatch.setattr(
        "src.configurator.application.service.load_structure_cache",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.configurator.application.service.save_structure_cache",
        lambda *args, **kwargs: None,
    )

    svc = ConfiguratorService()
    res = svc.open_db("http://127.0.0.1:8765", "db-1")

    assert res.loaded_from_cache is False
    assert len(res.objects) == 2
    assert "manifest_list" in calls
    assert not any(call.startswith("manifest_open") for call in calls)


def test_open_db_schedules_background_cache_compaction_for_legacy_cache(monkeypatch) -> None:
    scheduled: list[dict] = []

    class FakeGateway:
        def __init__(self, base_url: str) -> None:
            self.base_url = base_url

        def open_by_uid(self, db_uid: str):
            return {"db_uid": db_uid}

        def manifest_info(self) -> dict:
            return {
                "db_uid": "db-1",
                "db_path": r"F:\tmp\demo.mpdb",
                "structure_hash": "hash-1",
                "object_count": 1,
                "generated_at": 123,
            }

    cached_objects = [
        {
            "guid": "g-1",
            "parent_guid": "",
            "type": "configuration",
            "name": "Configuration",
            "title": "Configuration",
            "kind": "root",
            "payload": {"system": True},
        }
    ]

    monkeypatch.setattr("src.configurator.application.service.RuntimeGateway", FakeGateway)
    monkeypatch.setattr(
        "src.configurator.application.service.load_structure_cache",
        lambda *args, **kwargs: cached_objects,
    )
    monkeypatch.setattr(
        "src.configurator.application.service.cache_needs_compaction",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        ConfiguratorService,
        "_schedule_structure_cache_compaction",
        lambda self, **kwargs: scheduled.append(kwargs),
    )

    svc = ConfiguratorService()
    res = svc.open_db("http://127.0.0.1:8765", "db-1")

    assert res.loaded_from_cache is True
    assert res.cache_validated is True
    assert len(res.objects) == 1
    assert len(scheduled) == 1
    assert scheduled[0]["cache_db_path"] == r"F:\tmp\demo.mpdb"
    assert scheduled[0]["structure_hash"] == "hash-1"


def test_open_db_falls_back_to_open_path_when_uid_registry_missing(monkeypatch) -> None:
    calls: list[str] = []

    class FakeGateway:
        def __init__(self, base_url: str) -> None:
            self.base_url = base_url

        def open_by_uid(self, db_uid: str):
            calls.append(f"open_by_uid:{db_uid}")
            raise RuntimeError("registry missing")

        def list_open_databases(self) -> list[dict]:
            calls.append("list_open_databases")
            return [{"db_uid": "db-1", "path": r"F:\tmp\demo.1cd"}]

        def open_by_path(self, path: str):
            calls.append(f"open_by_path:{path}")
            return {"db_uid": "db-1", "name": "Demo"}

        def manifest_info(self) -> dict:
            calls.append("manifest_info")
            return {
                "db_uid": "db-1",
                "db_path": r"F:\tmp\demo.1cd",
                "structure_hash": "hash-1",
                "object_count": 0,
                "generated_at": 123,
            }

        def manifest_open(self, *, seed_defaults: bool = True) -> list[dict]:
            calls.append(f"manifest_open:{seed_defaults}")
            return []

    monkeypatch.setattr("src.configurator.application.service.RuntimeGateway", FakeGateway)
    monkeypatch.setattr(
        "src.configurator.application.service.load_structure_cache",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.configurator.application.service.save_structure_cache",
        lambda *args, **kwargs: None,
    )

    svc = ConfiguratorService()
    res = svc.open_db("http://127.0.0.1:8765", "db-1")

    assert res.loaded_from_cache is False
    assert any(call.startswith("open_by_path:") for call in calls)
    assert "list_open_databases" in calls


def test_manifest_get_payload_propagates_runtime_failure() -> None:
    class FailingGateway:
        def manifest_get_payload(self, guid: str) -> dict:
            raise TimeoutError(f"payload timeout: {guid}")

    svc = ConfiguratorService()
    svc._gw = FailingGateway()

    with pytest.raises(TimeoutError, match="payload timeout"):
        svc.manifest_get_payload("form-guid")


def test_manifest_info_timeout_uses_read_only_list_recovery(monkeypatch) -> None:
    calls: list[str] = []

    class FakeGateway:
        def __init__(self, _base_url: str) -> None:
            pass

        def open_by_uid(self, db_uid: str) -> dict:
            return {"db_uid": db_uid}

        def manifest_info(self) -> dict:
            calls.append("manifest_info")
            raise TimeoutError("manifest.info timed out")

        def manifest_list(self) -> list[dict]:
            calls.append("manifest_list")
            return [
                {
                    "guid": "g-root",
                    "parent_guid": "",
                    "type": "configuration",
                    "name": "Configuration",
                    "title": "Configuration",
                    "kind": "root",
                    "payload": {"system": True},
                }
            ]

        def manifest_open(self, *, seed_defaults: bool = True) -> list[dict]:
            raise AssertionError("manifest.info failure must not trigger manifest.open")

    monkeypatch.setattr("src.configurator.application.service.RuntimeGateway", FakeGateway)

    result = ConfiguratorService().open_db("http://127.0.0.1:8765", "db-1")

    assert [obj.guid for obj in result.objects] == ["g-root"]
    assert calls == ["manifest_info", "manifest_list"]
