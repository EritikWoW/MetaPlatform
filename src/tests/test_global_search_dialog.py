from __future__ import annotations

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.ui_qt.widgets.global_search_dialog import (
    GlobalSearchDialog,
    GlobalSearchHit,
    GlobalSearchOptions,
)


def test_global_search_dialog_runs_provider_without_blocking_ui() -> None:
    app = QApplication.instance() or QApplication([])
    received: list[tuple[str, GlobalSearchOptions]] = []

    def search(term: str, options: GlobalSearchOptions) -> list[GlobalSearchHit]:
        received.append((term, options))
        return [
            GlobalSearchHit(
                title="Managed application module",
                where="module://managed",
                line=83,
                col=39,
                preview="TargetModule.TargetProcedure();",
                payload={"module_guid": "managed"},
            )
        ]

    dialog = GlobalSearchDialog(
        search_fn=search,
        open_hit_fn=lambda _hit: None,
        initial_term="TargetModule.TargetProcedure",
        initial_options=GlobalSearchOptions(
            whole_word=True,
            module_guid="managed",
            limit=25,
        ),
        auto_start=True,
    )
    dialog.setModal(False)
    dialog.show()

    for _ in range(100):
        app.processEvents()
        if dialog.table.rowCount() == 1 and dialog.btn_find.isEnabled():
            break
        QTest.qWait(10)

    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 2).text() == "83"
    assert received == [
        (
            "TargetModule.TargetProcedure",
            GlobalSearchOptions(
                whole_word=True,
                module_guid="managed",
                limit=25,
            ),
        )
    ]
    dialog.close()
    app.processEvents()
