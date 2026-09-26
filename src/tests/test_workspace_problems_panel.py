from PySide6.QtWidgets import QApplication

from src.ui_qt.i18n import t
from src.ui_qt.widgets.workspace_problems_panel import WorkspaceProblemsPanel


def _diagnostics() -> list[dict]:
    return [
        {
            "code": "unresolved_member",
            "severity": "error",
            "message": "Exported member was not found",
            "module_guid": "module-a",
            "owner_title": "Settings server",
            "line": 12,
        },
        {
            "code": "lexer_partial",
            "severity": "warning",
            "message": "Unknown lexer tokens",
            "module_guid": "module-b",
            "owner_title": "Client module",
            "line": 0,
            "unknown_count": 4,
        },
    ]


def test_workspace_problems_panel_filters_and_exposes_compact_state() -> None:
    QApplication.instance() or QApplication([])
    panel = WorkspaceProblemsPanel()
    emitted: list[list[dict]] = []
    panel.diagnosticsChanged.connect(lambda rows: emitted.append(list(rows)))

    panel.set_diagnostics(_diagnostics(), generation=4)

    assert emitted and emitted[-1][0]["module_guid"] == "module-a"
    assert panel.model.rowCount() == 2
    assert panel.state(include_diagnostics=False) == {
        "loading": False,
        "generation": 4,
        "count": 2,
        "visible_count": 2,
        "error_count": 1,
        "warning_count": 1,
        "last_error": "",
        "current_row": -1,
    }

    panel.severity_filter.setCurrentIndex(1)
    assert panel.model.rowCount() == 1
    panel.severity_filter.setCurrentIndex(0)
    panel.search.setText("client")
    assert panel.model.rowCount() == 1
    assert panel.model.item(0, 4).text() == "lexer_partial"
    assert panel.model.item(0, 1).text() == t(
        "workspace_problem_lexer_partial"
    ).format(count=4)
    panel.deleteLater()


def test_workspace_problems_panel_opens_module_and_line() -> None:
    QApplication.instance() or QApplication([])
    panel = WorkspaceProblemsPanel()
    opened: list[tuple[str, str, int]] = []
    panel.openRequested.connect(
        lambda module_guid, title, line: opened.append(
            (module_guid, title, line)
        )
    )
    panel.set_diagnostics(_diagnostics())

    row = next(
        index
        for index in range(panel.model.rowCount())
        if panel.model.item(index, 4).text() == "unresolved_member"
    )
    panel._open_index(panel.model.index(row, 0))

    assert opened == [("module-a", "Settings server", 12)]
    panel.deleteLater()


def test_workspace_problems_panel_localizes_symbol_suggestions() -> None:
    diagnostic = {
        "code": "unresolved_callable",
        "severity": "error",
        "name": "RefresForm",
        "candidates": ["RefreshForm"],
    }

    message = WorkspaceProblemsPanel._display_message(diagnostic)

    assert t("workspace_problem_unresolved_callable").format(
        name="RefresForm"
    ) in message
    assert "RefreshForm" in message


def test_workspace_problems_panel_cycles_visible_diagnostics() -> None:
    QApplication.instance() or QApplication([])
    panel = WorkspaceProblemsPanel()
    opened: list[str] = []
    panel.openRequested.connect(
        lambda module_guid, _title, _line: opened.append(module_guid)
    )
    panel.set_diagnostics(_diagnostics())
    visible = [
        str(panel.model.item(row, 0).data(panel._ROLE_DIAGNOSTIC)["module_guid"])
        for row in range(panel.model.rowCount())
    ]

    assert panel.navigate(1) is True
    assert panel.navigate(1) is True
    assert panel.navigate(1) is True
    assert opened == [visible[0], visible[1], visible[0]]
    assert panel.state(include_diagnostics=False)["current_row"] == 0
    assert (
        panel.state(include_diagnostics=False)["current_diagnostic"]["module_guid"]
        == visible[0]
    )

    assert panel.navigate(-1) is True
    assert opened[-1] == visible[1]
    panel.deleteLater()


def test_workspace_problems_panel_queues_navigation_until_async_load() -> None:
    app = QApplication.instance() or QApplication([])
    panel = WorkspaceProblemsPanel()
    opened: list[str] = []
    panel.openRequested.connect(
        lambda module_guid, _title, _line: opened.append(module_guid)
    )
    panel.set_loader(lambda: {"generation": 2, "diagnostics": _diagnostics()})

    assert panel.navigate(1) is False
    while panel.state(include_diagnostics=False)["loading"]:
        app.processEvents()

    first = panel.model.item(0, 0).data(panel._ROLE_DIAGNOSTIC)["module_guid"]
    assert opened == [first]
    assert panel.state(include_diagnostics=False)["generation"] == 2
    panel.deleteLater()
