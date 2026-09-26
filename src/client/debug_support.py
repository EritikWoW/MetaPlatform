from __future__ import annotations

import json
import os
import logging
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut

from src.dsl.expression_eval import evaluate_expression, normalize_expression
from src.dsl.module_introspection import repair_cp1251_mojibake_name
from src.ui_qt.i18n import t

_LAST_DEBUG_PAUSE = None
_DEBUG_HOSTS: list[object] = []
_LOGGER = logging.getLogger("client.debug")


def _fmt(value: Any) -> str:
    if value is None:
        return t("dbg_value_undefined")
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(value)


def _normalize_debug_expression(expression: str) -> str:
    return normalize_expression(expression)


def _debug_eval_context(pause) -> dict[str, Any]:
    context: dict[str, Any] = {}
    context.update(getattr(pause, "globals", {}) or {})
    context.update(getattr(pause, "locals", {}) or {})
    context.update(getattr(pause, "globals_raw", {}) or {})
    context.update(getattr(pause, "locals_raw", {}) or {})
    for key, value in list(context.items()):
        repaired = repair_cp1251_mojibake_name(str(key))
        if repaired and repaired not in context:
            context[repaired] = value
    context.setdefault("Отказ", False)
    context.setdefault("Cancel", False)
    return context


def _debug_context_names(pause) -> list[str]:
    names: list[str] = []
    for source in (
        getattr(pause, "locals_raw", {}) or {},
        getattr(pause, "globals_raw", {}) or {},
        getattr(pause, "locals", {}) or {},
        getattr(pause, "globals", {}) or {},
    ):
        for key in source:
            name = str(key or "").strip()
            if name and name not in names:
                names.append(name)
            repaired = repair_cp1251_mojibake_name(name)
            if repaired and repaired not in names:
                names.append(repaired)
    return sorted(names, key=str.casefold)


def remember_debug_pause(pause) -> None:
    global _LAST_DEBUG_PAUSE
    _LAST_DEBUG_PAUSE = pause


def get_last_debug_pause():
    return _LAST_DEBUG_PAUSE


def forget_debug_pause(pause) -> None:
    """Discard a snapshot once its VM is no longer paused."""

    global _LAST_DEBUG_PAUSE
    if pause is not None and _LAST_DEBUG_PAUSE is pause:
        _LAST_DEBUG_PAUSE = None


def register_debug_host(host: object) -> None:
    if host is None:
        return
    if host not in _DEBUG_HOSTS:
        _DEBUG_HOSTS.append(host)


def unregister_debug_host(host: object) -> None:
    try:
        _DEBUG_HOSTS.remove(host)
    except ValueError:
        pass


def _pause_module_guid(pause) -> str:
    module_id = str(getattr(pause, "module_id", "") or "").strip()
    if module_id.startswith("module://"):
        return module_id.split("://", 1)[1].strip()
    return module_id


def _pause_module_ref(pause) -> str:
    module_id = str(getattr(pause, "module_id", "") or "").strip()
    return module_id


def _find_debug_targets():
    app = QApplication.instance()
    if app is None:
        return []
    try:
        return list(app.topLevelWidgets() or [])
    except Exception:
        return []


def _debug_hosts() -> list[object]:
    hosts: list[object] = []
    hosts.extend(list(_DEBUG_HOSTS or []))
    for top in _find_debug_targets():
        if top not in hosts:
            hosts.append(top)
    return hosts


def _focus_code_editor_widget(widget, pause, line: int) -> bool:
    try:
        asset_key = str(getattr(getattr(widget, "state", None), "asset_key", "") or "").strip()
    except Exception:
        asset_key = ""
    target_ref = _pause_module_ref(pause)
    target_guid = _pause_module_guid(pause)
    matches = False
    if asset_key and target_ref and asset_key == target_ref:
        matches = True
    elif asset_key and target_guid and asset_key.endswith(target_guid):
        matches = True
    elif asset_key and target_ref and target_ref.endswith(asset_key):
        matches = True
    if not matches:
        return False
    focus = getattr(widget, "focus_debug_location", None)
    if callable(focus):
        try:
            focus(int(line or 0), pause=pause)
            return True
        except Exception:
            return False
    return False


def _open_pause_target_in_host(pause) -> bool:
    line = int(getattr(pause, "line", 0) or 0)
    module_ref = _pause_module_ref(pause)
    module_guid = _pause_module_guid(pause)
    target_title = str(getattr(pause, "code_name", "") or module_ref or module_guid or "<module>")

    found = False
    for top in _debug_hosts():
        if not isinstance(top, QWidget):
            continue
        # First, prefer already-open code editor tabs.
        try:
            for child in top.findChildren(QWidget):
                if _focus_code_editor_widget(child, pause, line):
                    found = True
                    break
        except Exception:
            pass
        if found:
            break

    if found:
        return True

    if _open_pause_target_via_control_api(pause):
        return True

    for top in _debug_hosts():
        if not isinstance(top, QWidget):
            continue
        opener = getattr(top, "_open_module_by_guid", None)
        if callable(opener) and module_guid:
            try:
                opener(module_guid, target_title)
                found = True
                break
            except Exception:
                pass
        opener = getattr(top, "_open_module_ref", None)
        if callable(opener) and module_ref:
            try:
                opener(module_ref, target_title)
                found = True
                break
            except Exception:
                pass
        opener = getattr(top, "open_object_tab", None)
        if callable(opener) and module_guid:
            try:
                from src.configurator.ui.widgets import NodeInfo

                opener(NodeInfo(kind="object", name=target_title, guid=module_guid, obj_type="common_module"))
                found = True
                break
            except Exception:
                pass
    if not found:
        return False

    # Give Qt a moment to finish constructing the editor, then reveal the line.
    def _retry_reveal(remaining_ms: int = 400) -> None:
        for top in _debug_hosts():
            try:
                for child in top.findChildren(QWidget):
                    if _focus_code_editor_widget(child, pause, line):
                        return
            except Exception:
                pass
        if remaining_ms > 0:
            QTimer.singleShot(50, lambda: _retry_reveal(remaining_ms - 50))

    try:
        _retry_reveal()
    except Exception:
        pass
    return True


def _open_pause_target_via_control_api(pause) -> bool:
    module_ref = _pause_module_ref(pause)
    module_guid = _pause_module_guid(pause)
    if not module_ref and not module_guid:
        return False
    host = str(os.environ.get("META_CONTROL_API_HOST", "127.0.0.1") or "127.0.0.1").strip() or "127.0.0.1"
    try:
        port = int(os.environ.get("META_CONTROL_API_PORT", "8766") or "8766")
    except Exception:
        port = 8766
    payload = {
        "action": "open_debug_module",
        "payload": {
            "module_ref": module_ref,
            "module_guid": module_guid,
            "code_name": str(getattr(pause, "code_name", "") or ""),
            "title": str(getattr(pause, "code_name", "") or module_ref or module_guid or "<module>"),
            "line": int(getattr(pause, "line", 0) or 0),
            "depth": int(getattr(pause, "depth", 0) or 0),
        },
    }
    try:
        _LOGGER.info(
            "debug.control_api.open module_ref=%s module_guid=%s line=%s",
            module_ref,
            module_guid,
            int(getattr(pause, "line", 0) or 0),
        )
        req = Request(
            f"http://{host}:{port}/command",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urlopen(req, timeout=1.5) as resp:
            resp.read()
        return True
    except (URLError, TimeoutError, OSError, ValueError):
        return False
    except Exception:
        return False


def _debug_pause_via_control_api(pause) -> str:
    module_ref = _pause_module_ref(pause)
    module_guid = _pause_module_guid(pause)
    if not module_ref and not module_guid:
        return ""
    host = str(os.environ.get("META_CONTROL_API_HOST", "127.0.0.1") or "127.0.0.1").strip() or "127.0.0.1"
    try:
        port = int(os.environ.get("META_CONTROL_API_PORT", "8766") or "8766")
    except Exception:
        port = 8766
    payload = {
        "action": "debug_pause",
        "payload": {
            "module_ref": module_ref,
            "module_guid": module_guid,
            "code_name": str(getattr(pause, "code_name", "") or ""),
            "title": str(getattr(pause, "code_name", "") or module_ref or module_guid or "<module>"),
            "line": int(getattr(pause, "line", 0) or 0),
            "depth": int(getattr(pause, "depth", 0) or 0),
            "stack": list(getattr(pause, "stack", []) or []),
            "locals": dict(getattr(pause, "locals", {}) or {}),
            "globals": dict(getattr(pause, "globals", {}) or {}),
        },
    }
    try:
        _LOGGER.info(
            "debug.control_api.pause module_ref=%s module_guid=%s line=%s",
            module_ref,
            module_guid,
            int(getattr(pause, "line", 0) or 0),
        )
        req = Request(
            f"http://{host}:{port}/command",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urlopen(req, timeout=86400.0) as resp:
            raw = resp.read()
        parsed = json.loads(raw.decode("utf-8")) if raw else {}
        if str(parsed.get("status") or "").lower() != "ok":
            return ""
        data = parsed.get("data") if isinstance(parsed.get("data"), dict) else {}
        cmd = str((data or {}).get("command") or "").strip().lower()
        if cmd in {"continue", "step", "step_into", "step_over", "step_out"}:
            return cmd
    except (URLError, TimeoutError, OSError, ValueError):
        return ""
    except Exception:
        return ""
    return ""


def _rows_for_value(value: Any, *, limit: int = 50) -> list[tuple[str, Any, str]]:
    if value is None:
        return [(t("dbg_expr_value"), None, t("dbg_type_undefined"))]
    if isinstance(value, dict):
        rows = []
        for key, item in list(value.items())[:limit]:
            rows.append((str(key), item, type(item).__name__))
        return rows or [("Value", value, type(value).__name__)]
    if isinstance(value, (list, tuple)):
        rows = []
        for idx, item in enumerate(list(value)[:limit], start=1):
            rows.append((str(idx), item, type(item).__name__))
        return rows or [("Value", value, type(value).__name__)]
    if hasattr(value, "__dict__"):
        rows = []
        try:
            for key, item in list(vars(value).items())[:limit]:
                if key.startswith("_"):
                    continue
                rows.append((str(key), item, type(item).__name__))
        except Exception:
            rows = []
        if rows:
            return rows
    return [("Value", value, type(value).__name__)]


def evaluate_debug_expression(pause, expression: str) -> tuple[Any, list[str]]:
    expr = _normalize_debug_expression(expression)
    if not expr:
        return None, [t("dbg_expr_empty")]
    context = _debug_eval_context(pause)
    return evaluate_expression(
        expr,
        context=context,
        module_name=str(getattr(pause, "module_id", "") or "<debug-expression>"),
    )


def _fill_result_table(table: QTableWidget, rows: list[tuple[str, Any, str]]) -> None:
    table.setRowCount(0)
    table.setRowCount(len(rows))
    for row_idx, (prop, value, type_name) in enumerate(rows):
        table.setItem(row_idx, 0, QTableWidgetItem(str(prop)))
        table.setItem(row_idx, 1, QTableWidgetItem(_fmt(value)))
        table.setItem(row_idx, 2, QTableWidgetItem(str(type_name)))


def _create_data_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget()
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.horizontalHeader().setStretchLastSection(True)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    return table


def _selected_table_text(table: QTableWidget) -> str:
    ranges = table.selectedRanges()
    if not ranges:
        row = table.currentRow()
        if row < 0:
            return ""
        values = []
        for col in range(table.columnCount()):
            item = table.item(row, col)
            values.append(item.text() if item is not None else "")
        return "\t".join(values).strip()
    lines: list[str] = []
    for selection in ranges:
        for row in range(selection.topRow(), selection.bottomRow() + 1):
            values = []
            for col in range(selection.leftColumn(), selection.rightColumn() + 1):
                item = table.item(row, col)
                values.append(item.text() if item is not None else "")
            lines.append("\t".join(values).rstrip())
    return "\n".join(lines).strip()


def _install_table_copy(table: QTableWidget) -> None:
    table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
    table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def _copy() -> None:
        text = _selected_table_text(table)
        if text:
            QApplication.clipboard().setText(text)

    shortcut = QShortcut(QKeySequence.StandardKey.Copy, table)
    shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
    shortcut.activated.connect(_copy)
    table._mp_copy_shortcut = shortcut  # keep shortcut alive

    def _menu(pos) -> None:
        menu = QMenu(table)
        action = menu.addAction(t("act_copy"))
        action.triggered.connect(_copy)
        menu.exec(table.viewport().mapToGlobal(pos))

    table.customContextMenuRequested.connect(_menu)


def _fill_data_rows(table: QTableWidget, rows: list[tuple[Any, ...]]) -> None:
    table.setRowCount(0)
    table.setRowCount(len(rows))
    for r_idx, row in enumerate(rows):
        for c_idx, value in enumerate(row):
            table.setItem(r_idx, c_idx, QTableWidgetItem(_fmt(value)))


class _DebugExpressionDialog(QDialog):
    def __init__(self, pause, expression: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pause = pause
        self.setWindowTitle(t("dbg_expr_title"))
        self.resize(860, 620)

        root = QHBoxLayout(self)

        left = QVBoxLayout()
        root.addLayout(left, 1)

        expr_row = QHBoxLayout()
        self._expression = QLineEdit(self)
        self._expression.setPlaceholderText(t("dbg_expr_label"))
        self._expression.setText(str(expression or ""))
        self._install_expression_completer()
        expr_row.addWidget(self._expression, 1)
        self._calc_btn = QPushButton(t("dbg_calc"), self)
        self._calc_btn.clicked.connect(self._on_calculate)
        expr_row.addWidget(self._calc_btn)
        left.addLayout(expr_row)

        self._status = QLabel("", self)
        left.addWidget(self._status)

        self._result = QTableWidget(self)
        self._result.setColumnCount(3)
        self._result.setHorizontalHeaderLabels(
            [t("dbg_expr_prop"), t("dbg_expr_value"), t("dbg_expr_type")]
        )
        self._result.horizontalHeader().setStretchLastSection(True)
        self._result.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._result.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        _install_table_copy(self._result)
        left.addWidget(self._result, 1)

        left.addWidget(QLabel(t("dbg_expr_include_title"), self))
        self._watch = QTableWidget(self)
        self._watch.setColumnCount(3)
        self._watch.setHorizontalHeaderLabels(
            [t("dbg_expr_prop"), t("dbg_expr_value"), t("dbg_expr_type")]
        )
        self._watch.horizontalHeader().setStretchLastSection(True)
        self._watch.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._watch.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        _install_table_copy(self._watch)
        left.addWidget(self._watch, 1)

        right = QVBoxLayout()
        root.addLayout(right)
        right.addStretch(1)
        btn_include = QPushButton(t("dbg_expr_include"), self)
        btn_include.clicked.connect(self._on_include)
        right.addWidget(btn_include)
        btn_close = QPushButton(t("btn_close"), self)
        btn_close.clicked.connect(self.accept)
        right.addWidget(btn_close)
        btn_help = QPushButton(t("btn_help"), self)
        btn_help.clicked.connect(self._on_help)
        right.addWidget(btn_help)
        right.addStretch(2)

        if str(expression or "").strip():
            self._on_calculate()

    def _install_expression_completer(self) -> None:
        names = _debug_context_names(self._pause)
        if not names:
            return
        try:
            from PySide6.QtWidgets import QCompleter

            completer = QCompleter(names, self._expression)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            self._expression.setCompleter(completer)
            self._expression._mp_completer = completer  # keep completer alive
        except Exception:
            pass

    def _on_calculate(self) -> None:
        result, errors = evaluate_debug_expression(self._pause, self._expression.text())
        if errors:
            self._status.setText("\n".join(errors))
            self._status.setStyleSheet("color: #E35D6A;")
            self._result.setRowCount(0)
            return
        rows = _rows_for_value(result)
        _fill_result_table(self._result, rows)
        self._status.setText(t("dbg_expr_ok"))
        self._status.setStyleSheet("")

    def _on_include(self) -> None:
        if self._result.rowCount() <= 0:
            return
        row = self._result.currentRow()
        if row < 0:
            row = 0
        items = [
            self._result.item(row, 0),
            self._result.item(row, 1),
            self._result.item(row, 2),
        ]
        if not all(items):
            return
        insert_at = self._watch.rowCount()
        self._watch.insertRow(insert_at)
        for col, item in enumerate(items):
            self._watch.setItem(insert_at, col, QTableWidgetItem(item.text()))

    def _on_help(self) -> None:
        self._status.setText(t("dbg_expr_help"))
        self._status.setStyleSheet("")


def show_debug_expression(pause, expression: str = "", parent: QWidget | None = None) -> str:
    app = QApplication.instance()
    if app is None:
        return "continue"
    dlg = _DebugExpressionDialog(pause, expression=expression, parent=parent)
    dlg.exec()
    return "continue"


class _DebugPauseDialog(QDialog):
    def __init__(self, pause, parent=None) -> None:
        super().__init__(parent)
        self._pause = pause
        self._command = "continue"
        remember_debug_pause(pause)
        self.setWindowTitle("MetaPlatform Debugger")
        self.resize(820, 620)

        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"{t('dbg_module')}: {pause.module_id or '<unknown>'}"))
        root.addWidget(QLabel(f"{t('dbg_procedure')}: {pause.code_name}"))
        root.addWidget(QLabel(f"{t('dbg_line')}: {pause.line}"))
        root.addWidget(QLabel(f"{t('dbg_depth')}: {getattr(pause, 'depth', 0)}"))

        tabs = QTabWidget(self)
        stack = _create_data_table([t("dbg_expr_prop"), t("dbg_expr_value"), t("dbg_expr_type")])
        _fill_data_rows(
            stack,
            [
                (
                    item.get("code_name", ""),
                    item.get("line", 0),
                    "",
                )
                for item in list(getattr(pause, "stack", []) or [])
                if isinstance(item, dict)
            ],
        )
        tabs.addTab(stack, t("dbg_stack"))

        locals_view = _create_data_table([t("dbg_expr_prop"), t("dbg_expr_value"), t("dbg_expr_type")])
        _fill_data_rows(
            locals_view,
            [
                (key, value, type(value).__name__)
                for key, value in list(getattr(pause, "locals", {}) or {}).items()
            ],
        )
        tabs.addTab(locals_view, t("dbg_locals"))

        globals_view = _create_data_table([t("dbg_expr_prop"), t("dbg_expr_value"), t("dbg_expr_type")])
        _fill_data_rows(
            globals_view,
            [
                (key, value, type(value).__name__)
                for key, value in list(getattr(pause, "globals", {}) or {}).items()
            ],
        )
        tabs.addTab(globals_view, t("dbg_globals"))
        root.addWidget(tabs, 1)

        buttons = QDialogButtonBox(self)
        btn_continue = buttons.addButton(t("dbg_continue"), QDialogButtonBox.ButtonRole.AcceptRole)
        btn_step_into = buttons.addButton(t("dbg_step_into"), QDialogButtonBox.ButtonRole.ActionRole)
        btn_step_over = buttons.addButton(t("dbg_step_over"), QDialogButtonBox.ButtonRole.ActionRole)
        btn_step_out = buttons.addButton(t("dbg_step_out"), QDialogButtonBox.ButtonRole.ActionRole)
        btn_expr = buttons.addButton(t("dbg_expr"), QDialogButtonBox.ButtonRole.ActionRole)
        btn_continue.clicked.connect(self._accept_continue)
        btn_step_into.clicked.connect(self._accept_step_into)
        btn_step_over.clicked.connect(self._accept_step_over)
        btn_step_out.clicked.connect(self._accept_step_out)
        btn_expr.clicked.connect(self._open_expression)
        root.addWidget(buttons)

        self._install_shortcuts()

    def _install_shortcuts(self) -> None:
        shortcut_map = {
            "continue": ["F5", "Esc"],
            "step_over": ["F10"],
            "step_into": ["F11"],
            "step_out": ["Shift+F11"],
            "expr": ["Shift+F9"],
        }
        for command, keys in shortcut_map.items():
            for key in keys:
                sc = QShortcut(QKeySequence(key), self)
                sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                if command == "continue":
                    sc.activated.connect(self._accept_continue)
                elif command == "step_over":
                    sc.activated.connect(self._accept_step_over)
                elif command == "step_into":
                    sc.activated.connect(self._accept_step_into)
                elif command == "step_out":
                    sc.activated.connect(self._accept_step_out)
                else:
                    sc.activated.connect(self._open_expression)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_F5:
            self._accept_continue()
            return
        if event.key() == Qt.Key.Key_F10:
            self._accept_step_over()
            return
        if event.key() == Qt.Key.Key_F11 and not bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self._accept_step_into()
            return
        if event.key() == Qt.Key.Key_F11 and bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self._accept_step_out()
            return
        if event.key() == Qt.Key.Key_F9 and bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self._open_expression()
            return
        super().keyPressEvent(event)

    def _accept_continue(self) -> None:
        self._command = "continue"
        self.accept()

    def _accept_step_into(self) -> None:
        self._command = "step_into"
        self.accept()

    def _accept_step_over(self) -> None:
        self._command = "step_over"
        self.accept()

    def _accept_step_out(self) -> None:
        self._command = "step_out"
        self.accept()

    def _open_expression(self) -> None:
        show_debug_expression(self._pause, parent=self)

    @property
    def command(self) -> str:
        return self._command


def show_debug_pause(pause) -> str:
    app = QApplication.instance()
    if app is None:
        return "continue"
    remember_debug_pause(pause)
    _LOGGER.info(
        "debug.pause.enter module=%s code=%s line=%s depth=%s",
        getattr(pause, "module_id", ""),
        getattr(pause, "code_name", ""),
        getattr(pause, "line", 0),
        getattr(pause, "depth", 0),
    )
    cmd = _debug_pause_via_control_api(pause)
    if cmd:
        _LOGGER.info(
            "debug.pause.exit module=%s code=%s line=%s cmd=%s source=control_api",
            getattr(pause, "module_id", ""),
            getattr(pause, "code_name", ""),
            getattr(pause, "line", 0),
            cmd,
        )
        return cmd
    _open_pause_target_in_host(pause)
    dlg = _DebugPauseDialog(pause)
    dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
    dlg.setModal(True)
    try:
        dlg.raise_()
        dlg.activateWindow()
    except Exception:
        pass
    try:
        dlg.exec()
    except Exception as exc:
        _LOGGER.exception("debug.pause.exec_failed: %s", exc)
        return "continue"
    _LOGGER.info(
        "debug.pause.exit module=%s code=%s line=%s cmd=%s",
        getattr(pause, "module_id", ""),
        getattr(pause, "code_name", ""),
        getattr(pause, "line", 0),
        dlg.command,
    )
    return dlg.command
