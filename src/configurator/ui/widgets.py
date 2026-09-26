from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QTextEdit,
    QTableWidget,
    QTreeView,
    QStyledItemDelegate,
)

from src.ui_qt.i18n import t


@dataclass(frozen=True)
class NodeInfo:
    kind: str  # root/group/folder/object
    guid: str = ""
    name: str = ""
    obj_type: Optional[str] = None


class InlineEditDelegate(QStyledItemDelegate):
    """Delegate for inline rename.

    Important: do NOT blank the display text in paint().
    In practice, State_Editing can be set in more situations than the moment
    an editor widget is actually visible, which may lead to "empty" tree rows.

    The original visual issue ("double text" during rename) is addressed by
    making the editor QLineEdit opaque in ConfiguratorWindow._tune_inline_editor().
    """

    # Keep default painting behaviour.
    pass


class FormEditorWidget(QWidget):
    def __init__(self, title: str):
        super().__init__()
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        left = QVBoxLayout()
        left.addWidget(QLabel(t("form_designer_stub")), 0)
        hint = QTextEdit()
        hint.setReadOnly(True)
        hint.setPlainText(t("form_designer_stub_hint"))
        left.addWidget(hint, 1)

        right = QVBoxLayout()
        right.addWidget(QLabel(t("form_properties")), 0)
        props = QTableWidget(0, 2)
        props.setHorizontalHeaderLabels([t("prop_name"), t("prop_value")])
        props.horizontalHeader().setStretchLastSection(True)
        props.verticalHeader().setVisible(False)
        right.addWidget(props, 1)

        root.addLayout(left, 2)
        root.addLayout(right, 1)


class ObjectStructureWidget(QWidget):
    def __init__(self, title: str):
        super().__init__()
        l = QVBoxLayout(self)
        l.setContentsMargins(8, 8, 8, 8)
        l.setSpacing(8)
        l.addWidget(QLabel(title), 0)

        tv = QTreeView()
        model = QStandardItemModel()
        model.setHorizontalHeaderLabels([t("structure_node"), t("structure_value")])

        model.appendRow([QStandardItem(t("structure_fields")), QStandardItem("")])
        model.appendRow([QStandardItem(t("structure_modules")), QStandardItem("")])
        model.appendRow([QStandardItem(t("structure_forms")), QStandardItem("")])

        tv.setModel(model)
        tv.setHeaderHidden(False)
        l.addWidget(tv, 1)
