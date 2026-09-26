from types import SimpleNamespace

import src.configurator.persistence.schema_deployment as schema_deployment
from src.runtime.server_handlers_table import handle_table_action


def test_schema_deploy_returns_full_report_from_runtime(monkeypatch) -> None:
    db = object()
    handler = SimpleNamespace(_require_db=lambda _payload: db)
    report = SimpleNamespace(created=2, existing=4, skipped=1, errors=["warning"])

    class FakeDeploymentService:
        def __init__(self, actual_db) -> None:
            assert actual_db is db

        def deploy_all(self):
            return report

    monkeypatch.setattr(schema_deployment, "SchemaDeploymentService", FakeDeploymentService)

    result = handle_table_action(handler, "schema.deploy", {"session_id": "sid-1"})

    assert result is not None and result.status == "ok"
    assert result.data == {
        "created": 2,
        "existing": 4,
        "skipped": 1,
        "errors": ["warning"],
    }
