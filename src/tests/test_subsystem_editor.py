from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.ui_qt.widgets.subsystem_editor import (
    SubsystemEditorWidget,
    _SubsystemCommandInterfaceDialog,
    _SubsystemHelpInfoDialog,
)


class _FakeVm:
    def list_objects(self):
        return [
            SimpleNamespace(
                guid="cm-1",
                type="common_module",
                name="SessionModule",
                title="SessionModule",
                kind="object",
            ),
            SimpleNamespace(
                guid="cat-1",
                type="catalog",
                name="Products",
                title="Товари",
                kind="object",
            ),
            SimpleNamespace(
                guid="dp-1",
                type="data_processor",
                name="YntehratsyyaS1SDokumentooborot",
                title="Інтеграція 1С Документообіг",
                kind="object",
                payload={
                    "metadata_ref": "DataProcessor.ІнтеграціяС1СДокументооборот",
                    "imported": {
                        "origin": "DataProcessors/ІнтеграціяС1СДокументооборот.xml",
                    }
                },
            ),
            SimpleNamespace(
                guid="doc-1",
                type="document",
                name="SalesOrder",
                title="Замовлення",
                kind="object",
            ),
            SimpleNamespace(
                guid="sub-1",
                type="subsystem",
                name="Administration",
                title="Адміністрування",
                kind="object",
            ),
        ]


def test_subsystem_editor_groups_selected_objects_and_preserves_help_contents() -> None:
    app = QApplication.instance() or QApplication([])
    widget = SubsystemEditorWidget(
        title="Адміністрування",
        payload={
            "name": "Administration",
            "title": "Адміністрування",
            "help_pages": ["uk", "en"],
            "help_contents": {
                "uk": "<h1>Адміністрування</h1>",
                "en": "<h1>Administration</h1>",
            },
            "objects": ["cat-1", "doc-1"],
        },
        vm=_FakeVm(),
        obj_guid="sub-1",
    )
    widget.show()
    app.processEvents()

    assert widget._tree_selected_objects.topLevelItemCount() == 2
    assert sum(
        widget._tree_selected_objects.topLevelItem(index).childCount()
        for index in range(widget._tree_selected_objects.topLevelItemCount())
    ) == 2

    patch = widget._collect_payload()
    assert patch["help_contents"]["uk"] == "<h1>Адміністрування</h1>"
    assert patch["help_contents"]["en"] == "<h1>Administration</h1>"


def test_subsystem_editor_excludes_common_modules_from_available_objects() -> None:
    app = QApplication.instance() or QApplication([])
    widget = SubsystemEditorWidget(
        title="Адміністрування",
        payload={"name": "Administration", "title": "Адміністрування", "objects": []},
        vm=_FakeVm(),
        obj_guid="sub-1",
    )
    widget.show()
    app.processEvents()

    labels = []
    for i in range(widget._tree_objects.topLevelItemCount()):
        top = widget._tree_objects.topLevelItem(i)
        for j in range(top.childCount()):
            labels.append(top.child(j).text(0))

    assert "SessionModule" not in labels
    assert "Products" in labels
    assert "Товари" not in labels


def test_subsystem_editor_resolves_selected_objects_from_content_refs() -> None:
    app = QApplication.instance() or QApplication([])
    widget = SubsystemEditorWidget(
        title="Адміністрування",
        payload={
            "name": "Administration",
            "title": "Адміністрування",
            "content_refs": [
                "Catalog.Products",
                "Document.SalesOrder",
                "DataProcessor.ІнтеграціяС1СДокументооборот",
            ],
            "objects": [],
        },
        vm=_FakeVm(),
        obj_guid="sub-1",
    )
    widget.show()
    app.processEvents()

    assert widget._tree_selected_objects.topLevelItemCount() == 3
    collected = widget._collect_payload()
    assert collected["objects"] == ["cat-1", "doc-1", "dp-1"]
    assert set(collected["content_refs"]) == {
        "Catalog.Products",
        "Document.SalesOrder",
        "DataProcessor.ІнтеграціяС1СДокументооборот",
    }


def test_subsystem_command_interface_dialog_groups_commands_and_saves_visibility() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = _SubsystemCommandInterfaceDialog(
        title="Адміністрування",
        command_interface={
            "commands_visibility": [
                {"name": "DataProcessor.Admin.Command.GeneralSettings", "common": True},
            ],
            "commands_placement": [
                {
                    "name": "DataProcessor.Admin.Command.GeneralSettings",
                    "command_group": "NavigationPanelOrdinary",
                    "placement": "Auto",
                },
                {
                    "name": "CommonCommand.CryptoSetup",
                    "command_group": "CommandGroup.Настройки",
                    "placement": "Auto",
                },
            ],
            "commands_order": [
                {
                    "name": "DataProcessor.Admin.Command.GeneralSettings",
                    "command_group": "NavigationPanelOrdinary",
                },
                {
                    "name": "CommonCommand.CryptoSetup",
                    "command_group": "CommandGroup.Настройки",
                },
            ],
            "groups_order": ["NavigationPanelOrdinary", "CommandGroup.Настройки"],
        },
    )
    dialog.show()
    app.processEvents()

    assert dialog._tree.topLevelItemCount() == 2
    first_group = dialog._tree.topLevelItem(0)
    first_command = first_group.child(0)
    assert first_command.text(0) == "GeneralSettings"
    assert first_command.checkState(1) == Qt.CheckState.Checked

    first_command.setCheckState(1, Qt.CheckState.Unchecked)
    result = dialog.result_command_interface()
    visibility = {item["name"]: item["common"] for item in result["commands_visibility"]}
    assert visibility["DataProcessor.Admin.Command.GeneralSettings"] is False
    assert visibility["CommonCommand.CryptoSetup"] is False


def test_subsystem_help_dialog_shows_notice_when_html_not_imported() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = _SubsystemHelpInfoDialog(
        title="Адміністрування",
        help_pages=["uk"],
        help_contents={},
    )
    dialog.show()
    app.processEvents()

    assert dialog._lbl_missing.isVisible()
    assert dialog._lbl_missing.text()


def test_subsystem_command_interface_dialog_fallback_groups_old_payload() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = _SubsystemCommandInterfaceDialog(
        title="Адміністрування",
        command_interface={
            "commands_visibility": [
                {
                    "name": "DataProcessor.AdminPanel.Command.GeneralSettings",
                    "common": True,
                },
                {
                    "name": "CommonCommand.CryptoSetup",
                    "common": False,
                },
            ],
        },
    )
    dialog.show()
    app.processEvents()

    assert dialog._tree.topLevelItemCount() == 2


def test_subsystem_editor_recovers_service_payload_from_last_import(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])

    monkeypatch.setattr(
        "src.ui_qt.widgets.subsystem_editor._recover_help_contents_from_last_import",
        lambda **kwargs: {"uk": "<h1>Recovered</h1>"},
    )
    monkeypatch.setattr(
        "src.ui_qt.widgets.subsystem_editor._recover_command_interface_from_last_import",
        lambda **kwargs: {
            "commands_visibility": [{"name": "CommonCommand.CryptoSetup", "common": False}],
            "commands_order": [{"name": "CommonCommand.CryptoSetup", "command_group": "CommandGroup.Настройки"}],
            "groups_order": ["CommandGroup.Настройки"],
        },
    )

    widget = SubsystemEditorWidget(
        title="Адміністрування",
        payload={
            "name": "Administration",
            "title": "Адміністрування",
            "help_pages": ["uk"],
            "help_contents": {},
            "command_interface": {
                "commands_visibility": [{"name": "CommonCommand.CryptoSetup", "common": False}],
            },
            "imported": {
                "help_origin": "Subsystems/Administration/Ext/Help.xml",
                "command_interface_origin": "Subsystems/Administration/Ext/CommandInterface.xml",
            },
        },
        vm=_FakeVm(),
        obj_guid="sub-1",
    )
    widget.show()
    app.processEvents()

    widget._ensure_service_payload_recovered()
    assert widget._payload.help_contents["uk"] == "<h1>Recovered</h1>"
    assert widget._payload.command_interface["groups_order"] == ["CommandGroup.Настройки"]
