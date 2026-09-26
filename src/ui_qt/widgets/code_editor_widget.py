"""MetaScript code editor widget.

Features:
  - Syntax highlighting (MetaScript EN+UK via MetaScriptHighlighter)
  - Line numbers gutter
  - Parse / syntax check with inline error markers
  - Run button — executes the module via MetaScript VM
  - Save / Reload from mpdb asset
  - Language selector (UK / EN)
  - Monospace font, tab = 4 spaces, word-wrap off
  - Dark/Light aware (follows QPlainTextEdit background)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import List, Optional

from PySide6.QtCore import QByteArray, QEventLoop, QPoint, QRect, QSize, QSettings, Qt, Signal
from PySide6.QtGui import (
    QAction, QColor, QFont, QKeySequence, QPainter, QTextCharFormat, QTextCursor, QTextFormat, QPalette, QShortcut,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QInputDialog,
    QPushButton, QSizePolicy, QSpinBox, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QToolButton, QVBoxLayout, QWidget,
)
from PySide6.QtCore import QTimer

from pathlib import Path
from src.client.debug_support import (
    forget_debug_pause,
    get_last_debug_pause,
    remember_debug_pause,
    show_debug_expression,
)
from src.dsl.module_introspection import introspect_module_source, repair_cp1251_mojibake_name
from src.dsl.completion import completion_context, semantic_completion_candidates
from src.dsl.code_templates import CodeTemplate, expand_template, templates_for
from src.dsl.editor_syntax import (
    CODE, BLOCK_COMMENT, DOUBLE_STRING, SINGLE_STRING,
    format_indentation, indentation_plan, scan_editor_line,
)
from src.dsl.platform_symbols import METADATA_CATEGORIES, METADATA_ROOTS, metadata_category_for_name
from src.runtime.script.debugger import BreakpointSpec, BreakpointStore, DebugSession
from src.infra.onec.module_transform import normalize_module_text
from src.ui_qt.i18n import t

# ---------------------------------------------------------------------------
# Icon helper — PNG assets + QImage pixel approach (no Qt SVG plugin needed)
# ---------------------------------------------------------------------------
_CE_ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets" / "icons"
_CE_PNG_DIR = _CE_ASSETS_DIR / "png"
_CE_SVG_DIR = _CE_ASSETS_DIR / "svg"
_ce_icon_cache: dict = {}
_CE_HAS_QTSVG: bool = False
try:
    from PySide6.QtSvg import QSvgRenderer as _CE_SVG
    _CE_HAS_QTSVG = True
except Exception:
    pass

def _ce_icon(name: str, color: str = "#9AAFC8", size: int = 16) -> "QIcon":
    from PySide6.QtGui import QIcon, QPixmap
    k = (name, color, size)
    cached = _ce_icon_cache.get(k)
    if cached is not None:
        return cached
    def _store(ico):
        _ce_icon_cache[k] = ico; return ico
    png_p = _CE_PNG_DIR / f"{name}.png"
    if png_p.exists():
        try:
            from PIL import Image as _PI
            from PySide6.QtGui import QImage as _QImg, QColor as _QCol
            r_h=int(color[1:3],16); g_h=int(color[3:5],16); b_h=int(color[5:7],16)
            img = _PI.open(png_p).convert("RGBA").resize((size,size), _PI.LANCZOS)
            qimg = _QImg(size, size, _QImg.Format.Format_ARGB32_Premultiplied)
            qimg.fill(Qt.GlobalColor.transparent)
            pix = img.load()
            for y in range(size):
                for x in range(size):
                    pr,pg,pb,pa = pix[x,y]
                    if pa>0:
                        lum=(pr+pg+pb)/(3*255)
                        qimg.setPixelColor(x,y,_QCol(
                            min(255,int(r_h*lum)),
                            min(255,int(g_h*lum)),
                            min(255,int(b_h*lum)), pa))
            px=QPixmap.fromImage(qimg)
            if not px.isNull():
                return _store(QIcon(px))
        except Exception:
            pass
    svg_p = _CE_SVG_DIR / f"{name}.svg"
    if _CE_HAS_QTSVG and svg_p.exists():
        try:
            svg = svg_p.read_text(encoding="utf-8").replace("currentColor", str(color))
            renderer = _CE_SVG(QByteArray(svg.encode("utf-8")))
            px = QPixmap(size, size)
            px.fill(Qt.GlobalColor.transparent)
            painter = QPainter(px)
            renderer.render(painter)
            painter.end()
            if not px.isNull():
                return _store(QIcon(px))
        except Exception:
            pass
    return QIcon()
from src.ui_qt.widgets.metascript_highlighter import MetaScriptHighlighter


def _source_cursor_position(edit: QPlainTextEdit) -> int:
    return len(edit.toPlainText().encode("utf-16-le")[:edit.textCursor().position() * 2].decode("utf-16-le"))


def _cursor_lexical_context(edit: QPlainTextEdit) -> int:
    cursor = edit.textCursor()
    block = cursor.block()
    previous = block.previous()
    state = previous.userState() if previous.isValid() else CODE
    if state < 0:
        # Plain editors without a highlighter are also supported by the helper.
        state = CODE
        preceding = edit.document().firstBlock()
        while preceding.isValid() and preceding != block:
            state = scan_editor_line(preceding.text(), state).state
            preceding = preceding.next()
    prefix = block.text().encode("utf-16-le")[:cursor.positionInBlock() * 2].decode("utf-16-le")
    return scan_editor_line(prefix, state).state


def configure_metascript_editor(
    edit: QPlainTextEdit,
    *,
    placeholder: str = "",
    dark: bool | None = None,
    autocomplete: bool = True,
) -> MetaScriptHighlighter:
    """Apply shared MetaScript editor chrome and attach syntax highlighting."""

    font = QFont("Cascadia Code, Fira Code, Consolas, Courier New, monospace")
    font.setFamily("Cascadia Code")
    font.setPointSize(11)
    font.setFixedPitch(True)
    edit.setFont(font)
    edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    try:
        edit.setTabStopDistance(4 * edit.fontMetrics().horizontalAdvance(" "))
    except Exception:
        pass
    edit.setPlaceholderText(str(placeholder or ""))
    edit.setStyleSheet(
        """
        QPlainTextEdit {
            background: #0B1020;
            color: #E6EEF8;
            border: 1px solid #243247;
            border-radius: 10px;
            padding: 8px 10px;
            selection-background-color: rgba(37, 99, 235, 0.45);
            selection-color: #FFFFFF;
        }
        QPlainTextEdit:focus {
            border: 1px solid #3B82F6;
        }
        """
    )

    # The editor's stylesheet is dark even when the OS palette is light.
    # Match Base explicitly so gutter/current-line colors use the same surface.
    palette = edit.palette()
    palette.setColor(QPalette.ColorRole.Base, QColor("#0B1020"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#E6EEF8"))
    edit.setPalette(palette)
    refresh_line = getattr(edit, "_highlight_current_line", None)
    if callable(refresh_line):
        refresh_line()
    is_dark = bool(dark)
    if dark is None:
        try:
            is_dark = edit.palette().color(QPalette.ColorRole.Base).lightness() < 128
        except Exception:
            is_dark = True
    highlighter = MetaScriptHighlighter(edit.document(), dark=is_dark)
    if autocomplete:
        _install_autocomplete(edit)
    if getattr(edit, "_syntax_assistant", None) is None:
        from src.ui_qt.widgets.syntax_assistant import SyntaxAssistantController
        edit._syntax_assistant = SyntaxAssistantController(edit, edit)
    return highlighter


def create_metascript_code_edit(
    *,
    parent: QWidget | None = None,
    placeholder: str = "",
    dark: bool | None = None,
    autocomplete: bool = True,
) -> tuple[QPlainTextEdit, MetaScriptHighlighter]:
    """Create a shared MetaScript editor surface with line-number gutter."""

    edit = _CodeEdit(parent)
    highlighter = configure_metascript_editor(
        edit,
        placeholder=placeholder,
        dark=dark,
        autocomplete=autocomplete,
    )
    return edit, highlighter


# ---------------------------------------------------------------------------
# Line numbers gutter
# ---------------------------------------------------------------------------

class _LineNumberArea(QWidget):
    """Thin margin widget that draws line numbers."""

    def __init__(self, editor: "_CodeEdit") -> None:
        super().__init__(editor)
        self._editor = editor
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor.paint_line_numbers(event)

    def mousePressEvent(self, event) -> None:
        self._editor.toggle_breakpoint_at_y(int(event.position().y()))
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        self.setToolTip(
            self._editor.diagnostic_tooltip_at_y(int(event.position().y()))
        )
        super().mouseMoveEvent(event)


class _CodeEdit(QPlainTextEdit):
    """QPlainTextEdit with line number gutter."""

    _BREAKPOINT_GUTTER_WIDTH = 16
    _GUTTER_RIGHT_PAD = 2
    _BREAKPOINT_MARKER_SIZE = 8
    _DEBUG_MARKER_SIZE = 10
    _INDENT = "    "

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._gutter = _LineNumberArea(self)
        self._breakpoints: set[int] = set()
        self._breakpoint_meta: dict[int, BreakpointSpec] = {}
        self._debug_line: int = 0
        self._workspace_diagnostics: dict[int, list[dict]] = {}
        self.breakpointToggled = None
        self._autocomplete_handler = None
        self._autocomplete_insert_handler = None
        self._definition_handler = None
        self._usages_handler = None
        self._rename_handler = None
        self._suspend_completion = False
        self._format_action = QAction(t("code_editor_format_indentation"), self)
        self._format_action.setShortcut(QKeySequence("Ctrl+Alt+L"))
        self._format_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self._format_action.triggered.connect(lambda: self.format_code_indentation())
        self.addAction(self._format_action)

        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._highlight_current_line)

        self._update_gutter_width(0)
        self._highlight_current_line()

    def line_number_area_width(self) -> int:
        digits = max(3, len(str(self.blockCount())))
        return (
            self._BREAKPOINT_GUTTER_WIDTH
            + self.fontMetrics().horizontalAdvance("9") * digits
            + self._GUTTER_RIGHT_PAD
        )

    def _update_gutter_width(self, _) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_gutter(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width(0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._gutter.setGeometry(QRect(cr.left(), cr.top(),
                                       self.line_number_area_width(), cr.height()))

    def _highlight_current_line(self) -> None:
        extra: list = []
        for line_no, diagnostics in self._workspace_diagnostics.items():
            block = self.document().findBlockByNumber(int(line_no) - 1)
            if not block.isValid():
                continue
            sel = QTextEdit_ExtraSelection()
            sel.cursor = QTextCursor(block)
            sel.cursor.select(QTextCursor.SelectionType.LineUnderCursor)
            has_error = any(
                str(item.get("severity") or "") == "error"
                for item in diagnostics
            )
            sel.format.setUnderlineStyle(
                QTextCharFormat.UnderlineStyle.WaveUnderline
            )
            sel.format.setUnderlineColor(
                QColor("#F87171" if has_error else "#FBBF24")
            )
            extra.append(sel)
        if not self.isReadOnly():
            sel = QTextEdit_ExtraSelection()
            line_color = QColor(self.palette().color(QPalette.ColorRole.Base))
            if line_color.lightness() < 128:
                line_color = line_color.lighter(130)
            else:
                line_color = line_color.darker(105)
            sel.format.setBackground(line_color)
            sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            sel.cursor = self.textCursor()
            sel.cursor.clearSelection()
            extra.append(sel)
        if self._debug_line > 0:
            block = self.document().findBlockByNumber(int(self._debug_line) - 1)
            if block.isValid():
                sel = QTextEdit_ExtraSelection()
                debug_color = QColor("#2D4C7C")
                debug_color = debug_color.lighter(125) if debug_color.lightness() < 128 else debug_color.darker(110)
                sel.format.setBackground(debug_color)
                sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                sel.cursor = QTextCursor(block)
                sel.cursor.clearSelection()
                extra.append(sel)
        self.setExtraSelections(extra)

    def _position_line(self, line: int) -> None:
        line_no = int(line or 0)
        if line_no <= 0:
            return
        block = self.document().findBlockByNumber(line_no - 1)
        if not block.isValid():
            return
        cursor = self.textCursor()
        cursor.setPosition(block.position())
        cursor.clearSelection()
        self.setTextCursor(cursor)
        self.centerCursor()

    def navigate_to_line(self, line: int) -> None:
        self._position_line(line)
        self._highlight_current_line()
        self._gutter.update()

    def reveal_line(self, line: int) -> None:
        line_no = int(line or 0)
        if line_no <= 0:
            return
        self._debug_line = line_no
        self._position_line(line_no)
        self._highlight_current_line()
        self._gutter.update()

    def clear_debug_line(self) -> None:
        self._debug_line = 0
        self._highlight_current_line()
        self._gutter.update()

    def _editor_host(self) -> QWidget | None:
        host = self.parentWidget()
        while host is not None:
            if callable(getattr(host, "_handle_debug_shortcut", None)):
                return host
            host = host.parentWidget()
        return None

    def _handle_debug_key_event(self, event) -> None:
        event.setAccepted(False)
        parent = self._editor_host()
        handler = getattr(parent, "_handle_debug_shortcut", None)
        if callable(handler):
            if event.key() == Qt.Key.Key_F5 and bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                handler("force_stop_debug")
                event.accept()
                return
            if event.key() == Qt.Key.Key_F5:
                handler("continue_or_run")
                event.accept()
                return
            if event.key() == Qt.Key.Key_F9 and bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier) and not bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                handler("expr")
                event.accept()
                return
            if event.key() == Qt.Key.Key_F9 and bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier) and bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                handler("toggle_breakpoints_enabled")
                event.accept()
                return
            if event.key() == Qt.Key.Key_F9 and bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                handler("breakpoint_params")
                event.accept()
                return
            if event.key() == Qt.Key.Key_F9 and not bool(event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier)):
                handler("toggle_breakpoint")
                event.accept()
                return
            if event.key() == Qt.Key.Key_Up and bool(event.modifiers() & Qt.KeyboardModifier.AltModifier) and bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                handler("move_breakpoint_up")
                event.accept()
                return
            if event.key() == Qt.Key.Key_Down and bool(event.modifiers() & Qt.KeyboardModifier.AltModifier) and bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                handler("move_breakpoint_down")
                event.accept()
                return
            if event.key() == Qt.Key.Key_X and bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier) and bool(event.modifiers() & Qt.KeyboardModifier.AltModifier):
                handler("cut_breakpoint")
                event.accept()
                return
            if event.key() == Qt.Key.Key_K and bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier) and bool(event.modifiers() & Qt.KeyboardModifier.AltModifier):
                handler("copy_breakpoint")
                event.accept()
                return
            if event.key() == Qt.Key.Key_V and bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier) and bool(event.modifiers() & Qt.KeyboardModifier.AltModifier):
                handler("paste_breakpoint")
                event.accept()
                return
            if event.key() == Qt.Key.Key_F10:
                handler("step_over")
                event.accept()
                return
            if event.key() == Qt.Key.Key_F11 and bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                handler("step_out")
                event.accept()
                return
            if event.key() == Qt.Key.Key_F11:
                handler("step_into")
                event.accept()
                return

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self._gutter)
        bg = self.palette().color(QPalette.ColorRole.Base)
        is_dark = bg.lightness() < 128
        gutter_bg = bg.lighter(115) if is_dark else bg.darker(103)
        painter.fillRect(event.rect(), gutter_bg)
        fg = QColor("#AFC4E6") if is_dark else QColor("#64748B")

        block = self.firstVisibleBlock()
        block_num = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                line_no = block_num + 1
                diagnostics = self._workspace_diagnostics.get(line_no, [])
                if diagnostics:
                    has_error = any(
                        str(item.get("severity") or "") == "error"
                        for item in diagnostics
                    )
                    painter.fillRect(
                        0,
                        top,
                        3,
                        self.fontMetrics().height(),
                        QColor("#F87171" if has_error else "#FBBF24"),
                    )
                if line_no == self._debug_line:
                    painter.setBrush(QColor("#FBBF24"))
                    painter.setPen(Qt.PenStyle.NoPen)
                    marker = self._DEBUG_MARKER_SIZE
                    x = 2
                    y_mid = top + max(1, self.fontMetrics().height() // 2)
                    painter.drawPolygon(
                        [
                            QPoint(x, y_mid - marker // 2),
                            QPoint(x + marker, y_mid),
                            QPoint(x, y_mid + marker // 2),
                        ]
                    )
                spec = self._breakpoint_meta.get(int(line_no))
                if line_no in self._breakpoints:
                    color = "#E35D6A"
                    if spec is not None and not bool(spec.enabled):
                        color = "#64748B"
                    elif spec is not None and str(spec.condition or "").strip():
                        color = "#F59E0B"
                    painter.setBrush(QColor(color))
                    painter.setPen(Qt.PenStyle.NoPen)
                    bp_x = 13 if line_no == self._debug_line else 5
                    bp_y = top + max(2, (self.fontMetrics().height() - self._BREAKPOINT_MARKER_SIZE) // 2)
                    painter.drawEllipse(
                        bp_x,
                        bp_y,
                        self._BREAKPOINT_MARKER_SIZE,
                        self._BREAKPOINT_MARKER_SIZE,
                    )
                painter.setPen(fg)
                painter.drawText(
                    self._BREAKPOINT_GUTTER_WIDTH, top,
                    self._gutter.width() - self._BREAKPOINT_GUTTER_WIDTH - self._GUTTER_RIGHT_PAD,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    str(line_no),
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_num += 1

    def set_workspace_diagnostics(self, diagnostics: list[dict]) -> None:
        grouped: dict[int, list[dict]] = {}
        for item in list(diagnostics or []):
            if not isinstance(item, dict):
                continue
            line = int(item.get("line") or 0)
            if line > 0:
                grouped.setdefault(line, []).append(dict(item))
        self._workspace_diagnostics = grouped
        self._highlight_current_line()
        self._gutter.update()

    def diagnostic_tooltip_at_y(self, y: int) -> str:
        block = self.firstVisibleBlock()
        top = int(
            self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        )
        while block.isValid():
            bottom = top + int(self.blockBoundingRect(block).height())
            if top <= y <= bottom:
                diagnostics = self._workspace_diagnostics.get(
                    block.blockNumber() + 1,
                    [],
                )
                return "\n".join(
                    str(item.get("display_message") or item.get("message") or item.get("code") or "")
                    for item in diagnostics
                )
            if top > y:
                break
            block = block.next()
            top = bottom
        return ""

    def set_breakpoints(self, lines: set[int]) -> None:
        self._breakpoints = {int(x) for x in lines if int(x) > 0}
        self._breakpoint_meta = {line: BreakpointSpec(line=line) for line in self._breakpoints}
        self._gutter.update()

    def set_breakpoint_specs(self, specs: list[BreakpointSpec]) -> None:
        self._breakpoint_meta = {int(bp.line): bp for bp in specs if int(bp.line) > 0}
        self._breakpoints = set(self._breakpoint_meta.keys())
        self._gutter.update()

    def breakpoint_lines(self) -> set[int]:
        return set(self._breakpoints)

    def toggle_breakpoint_at_y(self, y: int) -> None:
        block = self.firstVisibleBlock()
        block_num = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        while block.isValid():
            if top <= y <= bottom:
                line_no = block_num + 1
                if line_no in self._breakpoints:
                    self._breakpoints.remove(line_no)
                else:
                    self._breakpoints.add(line_no)
                self._gutter.update()
                cb = getattr(self, "breakpointToggled", None)
                if callable(cb):
                    cb(line_no, line_no in self._breakpoints)
                return
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_num += 1

    def trigger_autocomplete(self, *, force: bool = False) -> None:
        handler = getattr(self, "_autocomplete_handler", None)
        if callable(handler):
            handler(bool(force))

    def set_autocomplete_words(self, words: set[str] | list[str] | tuple[str, ...]) -> None:
        clean = {str(item).strip() for item in (words or []) if str(item).strip()}
        all_words = sorted(set(_ALL_KEYWORDS) | clean)
        self._autocomplete_words = set(all_words)
        completer = getattr(self, "_autocomplete_completer", None)
        if completer is not None:
            try:
                from PySide6.QtCore import QStringListModel

                model = completer.model()
                if hasattr(model, "setStringList"):
                    model.setStringList(all_words)
                else:
                    completer.setModel(QStringListModel(all_words, completer))
            except Exception:
                pass

    def set_autocomplete_metadata_objects(self, objects_by_type: dict[str, list[str]]) -> None:
        self._autocomplete_metadata_objects = {
            str(type_name): tuple(str(name).strip() for name in names if str(name).strip())
            for type_name, names in dict(objects_by_type or {}).items()
        }

    def set_autocomplete_namespace_provider(self, provider) -> None:
        self._autocomplete_namespace_provider = provider
        self._autocomplete_namespace_members = {}

    def apply_autocomplete_completion(self, completion: str) -> None:
        handler = getattr(self, "_autocomplete_insert_handler", None)
        if callable(handler):
            handler(str(completion or ""))

    def _selected_blocks_range(self) -> tuple[int, int] | None:
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return None
        start = min(cursor.selectionStart(), cursor.selectionEnd())
        end = max(cursor.selectionStart(), cursor.selectionEnd())
        if end > start:
            end -= 1
        start_block = self.document().findBlock(start)
        end_block = self.document().findBlock(end)
        if not start_block.isValid() or not end_block.isValid():
            return None
        return int(start_block.blockNumber()), int(end_block.blockNumber())

    def _set_block_selection(self, start_block_no: int, end_block_no: int) -> None:
        doc = self.document()
        start_block = doc.findBlockByNumber(int(start_block_no))
        end_block = doc.findBlockByNumber(int(end_block_no))
        if not start_block.isValid() or not end_block.isValid():
            return
        cursor = self.textCursor()
        cursor.setPosition(start_block.position())
        end_pos = end_block.position() + len(end_block.text())
        cursor.setPosition(end_pos, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)

    def _indent_blocks(self, *, reverse: bool = False) -> bool:
        if self.isReadOnly():
            return False
        block_range = self._selected_blocks_range()
        if block_range is None:
            cursor = self.textCursor()
            if reverse:
                block = cursor.block()
                if not block.isValid():
                    return False
                text = block.text()
                remove = 0
                if text.startswith("\t"):
                    remove = 1
                else:
                    while remove < min(4, len(text)) and text[remove] == " ":
                        remove += 1
                if remove <= 0:
                    return False
                edit = QTextCursor(block)
                edit.beginEditBlock()
                try:
                    edit.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                    for _ in range(remove):
                        edit.deleteChar()
                finally:
                    edit.endEditBlock()
                return True
            cursor.insertText(self._INDENT)
            return True

        start_block_no, end_block_no = block_range
        doc = self.document()
        block = doc.findBlockByNumber(int(start_block_no))
        if not block.isValid():
            return False

        changed = False
        edit = QTextCursor(doc)
        edit.beginEditBlock()
        try:
            while block.isValid() and block.blockNumber() <= int(end_block_no):
                line_cursor = QTextCursor(block)
                line_cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                text = block.text()
                if reverse:
                    remove = 0
                    if text.startswith("\t"):
                        remove = 1
                    else:
                        while remove < min(4, len(text)) and text[remove] == " ":
                            remove += 1
                    if remove > 0:
                        for _ in range(remove):
                            line_cursor.deleteChar()
                        changed = True
                else:
                    line_cursor.insertText(self._INDENT)
                    changed = True
                block = block.next()
        finally:
            edit.endEditBlock()

        if changed:
            self._set_block_selection(start_block_no, end_block_no)
        return changed

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        self._format_action.setEnabled(not self.isReadOnly())
        menu.addAction(self._format_action)
        assistant = getattr(self, "_syntax_assistant", None)
        if assistant is not None:
            signature_action = menu.addAction(t("code_editor_signature_help") + "\tCtrl+Shift+Space")
            signature_action.triggered.connect(assistant.trigger_manually)
        menu.exec(event.globalPos())
        menu.deleteLater()

    def setReadOnly(self, read_only: bool) -> None:  # noqa: N802
        super().setReadOnly(read_only)
        if hasattr(self, "_format_action"):
            self._format_action.setEnabled(not read_only)

    def _source_cursor_position(self) -> int:
        return _source_cursor_position(self)

    def _lexical_context(self) -> int:
        return _cursor_lexical_context(self)

    def format_code_indentation(self) -> bool:
        """Reindent selected lines, or the document, as one reversible edit."""
        if self.isReadOnly():
            return False
        source = self.toPlainText()
        selected = self._selected_blocks_range()
        first, last = selected or (0, self.blockCount() - 1)
        formatted = format_indentation(source, start_line=first, end_line=last, indent=self._INDENT)
        if formatted == source:
            return False
        old_lines, new_lines = source.split("\n"), formatted.split("\n")
        cursor = self.textCursor()
        endpoints = []
        for position in (cursor.anchor(), cursor.position()):
            block = self.document().findBlock(position)
            line = block.blockNumber()
            column = position - block.position()
            delta = len(new_lines[line]) - len(old_lines[line])
            endpoints.append((line, max(0, column + delta) if column else 0))
        vertical, horizontal = self.verticalScrollBar().value(), self.horizontalScrollBar().value()
        self._suspend_completion = True
        completer = getattr(self, "_autocomplete_completer", None)
        if completer is not None:
            completer.popup().hide()
        edit = QTextCursor(self.document())
        edit.beginEditBlock()
        try:
            for index in range(last, first - 1, -1):
                old, new = old_lines[index], new_lines[index]
                if old == new:
                    continue
                bom = 1 if old.startswith("\ufeff") else 0
                old_indent = len(old[bom:]) - len(old[bom:].lstrip(" \t"))
                new_indent = len(new[bom:]) - len(new[bom:].lstrip(" \t"))
                position = self.document().findBlockByNumber(index).position() + bom
                edit.setPosition(position)
                edit.setPosition(position + old_indent, QTextCursor.MoveMode.KeepAnchor)
                edit.insertText(new[bom:bom + new_indent])
        finally:
            edit.endEditBlock()
            self._suspend_completion = False
        restored = self.textCursor()
        for index, (line, column) in enumerate(endpoints):
            position = self.document().findBlockByNumber(line).position() + column
            restored.setPosition(position, QTextCursor.MoveMode.KeepAnchor if index else QTextCursor.MoveMode.MoveAnchor)
        self.setTextCursor(restored)
        self.verticalScrollBar().setValue(vertical)
        self.horizontalScrollBar().setValue(horizontal)
        return True

    def _insert_indented_newline(self) -> None:
        cursor = self.textCursor()
        if self._lexical_context() in (BLOCK_COMMENT, DOUBLE_STRING, SINGLE_STRING):
            cursor.insertText("\n")
            self.setTextCursor(cursor)
            return
        source = self.toPlainText().encode("utf-16-le")[:cursor.position() * 2].decode("utf-16-le")
        plan = indentation_plan(source)[-1]
        prefix = source.rsplit("\n", 1)[-1]
        indent = re.match(r"[ \t]*", prefix).group(0)
        cursor.beginEditBlock()
        try:
            if plan.structural:
                leading = QTextCursor(cursor.block())
                leading.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, len(indent))
                indent = self._INDENT * plan.level
                leading.insertText(indent)
            delta = plan.next_level - plan.level
            next_indent = indent + self._INDENT * delta if delta >= 0 else self._INDENT * plan.next_level
            cursor.insertText("\n" + next_indent)
        finally:
            cursor.endEditBlock()
        self.setTextCursor(cursor)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtCore import Qt as _Qt
        completer = getattr(self, "_autocomplete_completer", None)
        if completer is not None and completer.popup().isVisible():
            popup = completer.popup()
            if event.key() == Qt.Key.Key_Escape:
                popup.hide()
                event.accept()
                return
            accept = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab)
            accept = accept or (event.key() == Qt.Key.Key_Space and event.modifiers() == Qt.KeyboardModifier.ControlModifier)
            if accept and not self.isReadOnly():
                index = popup.currentIndex()
                if not index.isValid():
                    index = completer.completionModel().index(0, 0)
                completion = index.data()
                popup.hide()
                if completion:
                    self.apply_autocomplete_completion(str(completion))
                event.accept()
                return
            if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down) and not event.modifiers():
                step = 1 if event.key() == Qt.Key.Key_Down else -1
                row = (popup.currentIndex().row() + step) % max(1, completer.completionCount())
                popup.setCurrentIndex(completer.completionModel().index(row, 0))
                event.accept()
                return
        self._handle_debug_key_event(event)
        if event.isAccepted():
            return
        if (
            not self.isReadOnly()
            and not event.modifiers() & (_Qt.KeyboardModifier.ControlModifier | _Qt.KeyboardModifier.AltModifier)
            and not self.textCursor().hasSelection()
        ):
            pair = {"(": ")", "[": "]", "{": "}"}.get(event.text())
            cursor = self.textCursor()
            suffix_cursor = QTextCursor(cursor)
            suffix_cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor)
            suffix = suffix_cursor.selectedText()
            if event.text() in (")", "]", "}") and suffix == event.text() and self._lexical_context() == CODE:
                cursor.movePosition(QTextCursor.MoveOperation.Right)
                self.setTextCursor(cursor)
                event.accept()
                return
            if event.key() == Qt.Key.Key_Backspace and self._lexical_context() == CODE:
                previous = QTextCursor(cursor)
                previous.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor)
                if {"(": ")", "[": "]", "{": "}"}.get(previous.selectedText()) == suffix and suffix:
                    cursor.beginEditBlock()
                    cursor.deletePreviousChar()
                    cursor.deleteChar()
                    cursor.endEditBlock()
                    self.setTextCursor(cursor)
                    event.accept()
                    return
            if pair and self._lexical_context() == CODE:
                cursor = self.textCursor()
                cursor.beginEditBlock()
                cursor.insertText(event.text() + pair)
                cursor.movePosition(QTextCursor.MoveOperation.Left)
                cursor.endEditBlock()
                self.setTextCursor(cursor)
                event.accept()
                return
            if event.key() in {_Qt.Key.Key_Return, _Qt.Key.Key_Enter}:
                self._insert_indented_newline()
                event.accept()
                return
        if event.key() == Qt.Key.Key_Tab and not bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            if self._indent_blocks(reverse=False):
                event.accept()
                return
        if event.key() == Qt.Key.Key_Backtab:
            if self._indent_blocks(reverse=True):
                event.accept()
                return
        if (
            event.key() == Qt.Key.Key_Space
            and bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            and bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
        ):
            self._show_code_template_menu()
            event.accept()
            return
        if (
            event.key() == Qt.Key.Key_Space
            and bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        ):
            self.trigger_autocomplete(force=True)
            event.accept()
            return
        if event.key() == Qt.Key.Key_F12 and bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            handler = getattr(self, "_usages_handler", None)
            if callable(handler):
                handler()
                event.accept()
                return
        if event.key() == Qt.Key.Key_F6 and bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            handler = getattr(self, "_rename_handler", None)
            if callable(handler):
                handler()
                event.accept()
                return
        if event.key() == Qt.Key.Key_F12 and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            handler = getattr(self, "_definition_handler", None)
            if callable(handler):
                handler()
                event.accept()
                return
        if event.key() == _Qt.Key.Key_F9 and bool(event.modifiers() & _Qt.KeyboardModifier.ShiftModifier):
            parent = self._editor_host()
            handler = getattr(parent, "_open_debug_expression_dialog", None)
            if callable(handler):
                handler()
                event.accept()
                return
        super().keyPressEvent(event)

    def _show_code_template_menu(self) -> None:
        """Open a constructor menu; QMenu provides arrow-key navigation."""
        if self.isReadOnly():
            return
        menu = QMenu(self)
        language = str(getattr(self, "_autocomplete_language", "uk") or "uk")
        for template in templates_for(language, self.toPlainText()):
            action = menu.addAction(template.label)
            action.setData(template)
        chosen = menu.exec(self.mapToGlobal(self.cursorRect().bottomRight()))
        template = chosen.data() if chosen is not None else None
        if not isinstance(template, CodeTemplate):
            return
        text, caret_offset = expand_template(template)
        cursor = self.textCursor()
        start = cursor.position()
        cursor.insertText(text)
        cursor.setPosition(start + caret_offset)
        self.setTextCursor(cursor)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        if (
            event.button() == Qt.MouseButton.LeftButton
            and bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        ):
            cursor = self.cursorForPosition(event.position().toPoint())
            self.setTextCursor(cursor)
            handler = getattr(self, "_definition_handler", None)
            if callable(handler):
                handler()


# Use the real PySide6 ExtraSelection type
from PySide6.QtWidgets import QTextEdit as _QTE_for_sel
QTextEdit_ExtraSelection = _QTE_for_sel.ExtraSelection



# ---------------------------------------------------------------------------
# Keyword autocomplete
# ---------------------------------------------------------------------------

_MS_KEYWORDS_UK = [
    "Процедура", "КінецьПроцедури", "Функція", "КінецьФункції",
    "Повернути", "Якщо", "Тоді", "Інакше", "КінецьЯкщо", "ЯкщоІнакше",
    "Для", "Кожного", "З", "По", "Цикл", "КінецьЦиклу", "Поки",
    "Перервати", "Продовжити", "Спробувати", "Виняток", "KінецьСпроби",
    "Новий", "Не", "І", "Або", "Правда", "Хиба", "Невизначено", "Null",
    "Повідомлення", "Рядок", "Число", "Логічне", "Масив", "Відповідність",
    "ПоточнаДата", "Формат", "Лів", "Прав", "Сер", "Знайти", "ВРег", "НРег",
    "Дл", "СкрПробіли", "Модуль", "Округл", "Ціле", "Макс", "Мін",
    "ЄNull", "ЄНевизначено", "ПустеЗнч",
]

_MS_KEYWORDS_EN = [
    "Procedure", "EndProcedure", "Function", "EndFunction",
    "Return", "If", "Then", "Else", "EndIf", "ElsIf",
    "For", "Each", "In", "To", "Do", "EndDo", "While",
    "Break", "Continue", "Try", "Except", "EndTry",
    "New", "Not", "And", "Or", "True", "False", "Undefined", "Null",
    "Message", "String", "Number", "Boolean", "Array", "Map",
    "CurrentDate", "Format", "Left", "Right", "Mid", "Find", "Upper", "Lower",
    "Len", "TrimAll", "Abs", "Round", "Int", "Max", "Min",
    "IsNull", "IsUndefined", "IsEmpty",
]

_ALL_KEYWORDS = sorted(set(_MS_KEYWORDS_UK + _MS_KEYWORDS_EN))
_IDENTIFIER_CHAIN_RE = re.compile(
    r"[^\W\d]\w*(?:\s*\.\s*[^\W\d]\w*)*",
    flags=re.UNICODE,
)


@dataclass(frozen=True, slots=True)
class DefinitionTarget:
    kind: str
    name: str
    line: int = 0
    guid: str = ""
    module_guid: str = ""
    title: str = ""
    obj_type: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "name": self.name,
            "line": int(self.line or 0),
            "guid": self.guid,
            "module_guid": self.module_guid,
            "title": self.title,
            "obj_type": self.obj_type,
        }


def identifier_chain_at(source: str, position: int) -> tuple[str, ...]:
    """Return the dotted identifier chain under the caret."""

    text = str(source or "")
    pos = max(0, min(int(position or 0), len(text)))
    probes = {pos}
    if pos > 0:
        probes.add(pos - 1)
    for match in _IDENTIFIER_CHAIN_RE.finditer(text):
        if any(match.start() <= probe < match.end() for probe in probes):
            return tuple(
                part.strip()
                for part in re.split(r"\s*\.\s*", match.group(0))
                if part.strip()
            )
    return ()


def _definition_snapshot_rows(vm) -> list[dict[str, object]]:
    rows = getattr(vm, "_objects_snapshot", ()) or ()
    out: list[dict[str, object]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(dict(row))
            continue
        out.append(
            {
                "guid": str(getattr(row, "guid", "") or ""),
                "type": str(getattr(row, "type", "") or ""),
                "kind": str(getattr(row, "kind", "") or ""),
                "name": str(getattr(row, "name", "") or ""),
                "title": str(getattr(row, "title", "") or ""),
                "payload": getattr(row, "payload", {}) or {},
            }
        )
    return out


def _definition_row_aliases(row: dict[str, object]) -> set[str]:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    metadata_ref = str(payload.get("metadata_ref") or "").strip()
    values = {
        str(row.get("name") or "").strip(),
        str(row.get("title") or "").strip(),
        str(payload.get("source_name") or "").strip(),
        metadata_ref,
        metadata_ref.rsplit(".", 1)[-1],
    }
    for key in ("localized_names", "code_refs", "legacy_code_refs"):
        extra = payload.get(key)
        if isinstance(extra, dict):
            values.update(str(value or "").strip() for value in extra.values())
        elif isinstance(extra, (list, tuple, set)):
            values.update(str(value or "").strip() for value in extra)
    aliases: set[str] = set()
    for value in values:
        if not value:
            continue
        aliases.add(value.casefold())
        repaired = repair_cp1251_mojibake_name(value)
        if repaired:
            aliases.add(repaired.casefold())
    return aliases


def _module_guid_for_owner(vm, owner_guid: str) -> str:
    resolver = getattr(vm, "resolve_module_asset_key_for_owner", None)
    if callable(resolver):
        try:
            asset_key = str(resolver(owner_guid) or "").strip()
            if asset_key.startswith("module://"):
                return asset_key.split("://", 1)[1].strip()
        except Exception:
            pass
    service = getattr(vm, "_service", None)
    list_modules = getattr(service, "list_modules_by_owner", None)
    if callable(list_modules):
        try:
            rows = list_modules(owner_guid) or []
        except Exception:
            rows = []
        if rows:
            preferred = next(
                (row for row in rows if not str(row.get("lang") or "").strip()),
                rows[0],
            )
            return str(preferred.get("module_guid") or "").strip()
    return ""


def resolve_definition_target(
    source: str,
    position: int,
    *,
    introspection,
    vm,
) -> DefinitionTarget | None:
    """Resolve a local symbol, common-module call or metadata object."""

    chain = identifier_chain_at(source, position)
    if not chain:
        return None

    if len(chain) == 1 and introspection is not None:
        symbol = getattr(introspection, "symbol_by_name", {}).get(chain[0])
        if symbol is None:
            symbol = getattr(introspection, "symbol_by_name", {}).get(chain[0].casefold())
        line = int(getattr(symbol, "line", 0) or 0) if symbol is not None else 0
        if line > 0 and str(getattr(symbol, "kind", "") or "") != "runtime":
            return DefinitionTarget(
                kind="local",
                name=str(getattr(symbol, "name", "") or chain[0]),
                line=line,
            )

    metadata_chain = (
        len(chain) >= 3
        and chain[0].casefold() in {root.casefold() for root in METADATA_ROOTS}
    )
    semantic_resolver = getattr(
        getattr(vm, "_service", None),
        "resolve_workspace_symbol",
        None,
    )
    semantic_checked = False
    if len(chain) >= 2 and not metadata_chain and callable(semantic_resolver):
        semantic_checked = True
        try:
            target = dict(semantic_resolver(chain[0], chain[1]) or {})
        except Exception:
            target = {}
        if target:
            return DefinitionTarget(
                kind="module",
                name=str(target.get("name") or chain[1]),
                line=int(target.get("line") or 0),
                guid=str(target.get("owner_guid") or ""),
                module_guid=str(target.get("module_guid") or ""),
                title=str(
                    target.get("owner_title")
                    or target.get("owner_name")
                    or chain[0]
                ),
                obj_type=str(target.get("owner_type") or "common_module"),
            )

    rows = _definition_snapshot_rows(vm)
    if len(chain) >= 3 and chain[0].casefold() in {root.casefold() for root in METADATA_ROOTS}:
        category = metadata_category_for_name(chain[1])
        if category is not None:
            folded = chain[2].casefold()
            row = next(
                (
                    item
                    for item in rows
                    if str(item.get("type") or "").strip() == category.type_name
                    and str(item.get("kind") or "").strip().lower() in {"", "object"}
                    and folded in _definition_row_aliases(item)
                ),
                None,
            )
            if row is not None:
                return DefinitionTarget(
                    kind="metadata",
                    name=str(row.get("name") or chain[2]),
                    guid=str(row.get("guid") or ""),
                    title=str(row.get("title") or row.get("name") or chain[2]),
                    obj_type=str(row.get("type") or ""),
                )

    if len(chain) >= 2 and not semantic_checked:
        folded = chain[0].casefold()
        owner = next(
            (
                item
                for item in rows
                if str(item.get("type") or "").strip().lower() == "common_module"
                and str(item.get("kind") or "").strip().lower() in {"", "object"}
                and folded in _definition_row_aliases(item)
            ),
            None,
        )
        if owner is not None:
            owner_guid = str(owner.get("guid") or "").strip()
            module_guid = _module_guid_for_owner(vm, owner_guid) or owner_guid
            line = 0
            try:
                module_text, _mime, _resolved = vm.get_text_asset(f"module://{module_guid}")
                module_info = introspect_module_source(module_text, language="mixed")
                symbol = module_info.symbol_by_name.get(chain[1])
                if symbol is None:
                    symbol = module_info.symbol_by_name.get(chain[1].casefold())
                line = int(getattr(symbol, "line", 0) or 0) if symbol is not None else 0
            except Exception:
                pass
            return DefinitionTarget(
                kind="module",
                name=chain[1],
                line=line,
                guid=owner_guid,
                module_guid=module_guid,
                title=str(owner.get("title") or owner.get("name") or chain[0]),
                obj_type="common_module",
            )

    return None


def _install_autocomplete(edit: "_CodeEdit") -> None:
    """Install context-aware MetaScript completion on a QPlainTextEdit."""
    try:
        from PySide6.QtWidgets import QCompleter
        from PySide6.QtCore import Qt
        completer = QCompleter(_ALL_KEYWORDS, edit)
        edit._autocomplete_words = set(_ALL_KEYWORDS)
        edit._autocomplete_metadata_objects = {}
        edit._autocomplete_namespace_members = {}
        edit._autocomplete_namespace_provider = None
        edit._autocomplete_completer = completer
        completer.setWidget(edit)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        try:
            popup = completer.popup()
            popup.setObjectName("MetaScriptCompleter")
            popup.setStyleSheet(
                """
                QAbstractItemView#MetaScriptCompleter {
                    background: #111827;
                    color: #E6EEF8;
                    border: 1px solid #243247;
                    border-radius: 8px;
                    outline: none;
                    padding: 4px;
                    selection-background-color: #1F2A44;
                    selection-color: #FFFFFF;
                }
                QAbstractItemView#MetaScriptCompleter::item {
                    min-height: 26px;
                    padding: 4px 10px;
                    border-radius: 6px;
                }
                """
            )
        except Exception:
            pass

        def _show_completions(force: bool = False):
            if getattr(edit, "_suspend_completion", False) or edit.isReadOnly() or _cursor_lexical_context(edit) != CODE:
                completer.popup().hide()
                return
            cursor = edit.textCursor()
            position = _source_cursor_position(edit)
            context = completion_context(edit.toPlainText(), position)
            prefix = context.prefix
            if not context.chain and len(prefix) < 2 and not force:
                completer.popup().hide()
                return
            candidates = completion_candidates_for_editor(
                edit,
                edit.toPlainText(),
                position,
            )
            # Once the token is complete, textChanged must not reopen the
            # popup. Explicit Ctrl+Space still forces a lookup.
            if not force and prefix and any(
                str(candidate).casefold() == prefix.casefold()
                for candidate in candidates
            ):
                completer.popup().hide()
                return
            from PySide6.QtCore import QStringListModel

            model = completer.model()
            if hasattr(model, "setStringList"):
                model.setStringList(candidates)
            else:
                completer.setModel(QStringListModel(candidates, completer))
            completer.setCompletionPrefix(prefix)
            if completer.completionCount() == 0:
                completer.popup().hide()
                return
            if force:
                completer.setCurrentRow(0)
                popup = completer.popup()
                if popup is not None:
                    popup.setCurrentIndex(completer.completionModel().index(0, 0))
            rect = edit.cursorRect()
            rect.setWidth(completer.popup().sizeHintForColumn(0)
                          + completer.popup().verticalScrollBar().sizeHint().width())
            completer.complete(rect)

        def _on_activated(completion: str):
            if edit.isReadOnly():
                return
            cursor = edit.textCursor()
            context = completion_context(edit.toPlainText(), _source_cursor_position(edit))
            if context.replace_length > 0:
                cursor.movePosition(
                    QTextCursor.MoveOperation.Left,
                    QTextCursor.MoveMode.KeepAnchor,
                    context.replace_length,
                )
            cursor.insertText(str(completion or ""))

        edit._autocomplete_handler = _show_completions
        edit._autocomplete_insert_handler = _on_activated
        edit.textChanged.connect(lambda: _show_completions(False))
        completer.activated.connect(_on_activated)
    except Exception:
        pass  # autocomplete is optional


def common_module_completion_members_from_vm(
    vm,
    namespace: str,
) -> list[str] | None:
    service = getattr(vm, "_service", None)
    resolver = getattr(service, "get_common_module_completion", None)
    if not callable(resolver):
        return []
    try:
        result = dict(resolver(str(namespace or "").strip()) or {})
    except Exception:
        return None
    return [
        str(item.get("name") or "").strip()
        for item in list(result.get("members") or [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]


def completion_candidates_for_editor(
    edit,
    source: str,
    cursor_position: int,
) -> list[str]:
    context = completion_context(source, cursor_position)
    # Include declarations from the current document.  This keeps completion
    # useful while editing a procedure before the module has been saved.
    visible = set(getattr(edit, "_autocomplete_words", set(_ALL_KEYWORDS)))
    try:
        info = introspect_module_source(
            source,
            language=str(getattr(edit, "_autocomplete_language", "mixed") or "mixed"),
        )
        for symbol in info.symbols:
            name = str(getattr(symbol, "name", "") or "").strip()
            if name:
                visible.add(name)
            visible.update(str(alias).strip() for alias in getattr(symbol, "aliases", ()) or ())
        for scope in info.scopes:
            if scope.contains_line(context.line):
                visible.update(scope.params)
                visible.update(scope.locals)
                break
    except Exception:
        # Completion must never make typing fail on an incomplete document.
        pass
    namespace_members = getattr(edit, "_autocomplete_namespace_members", {})
    if context.chain:
        root = str(context.chain[0] or "").strip()
        root_key = root.casefold()
        metadata_roots = {name.casefold() for name in METADATA_ROOTS}
        if root_key not in metadata_roots and root_key not in namespace_members:
            provider = getattr(edit, "_autocomplete_namespace_provider", None)
            if callable(provider):
                loaded = provider(root)
                if loaded is not None:
                    namespace_members[root_key] = tuple(
                        str(item).strip()
                        for item in loaded
                        if str(item).strip()
                    )
                    edit._autocomplete_namespace_members = namespace_members
    return semantic_completion_candidates(
        context,
        visible,
        metadata_objects=getattr(edit, "_autocomplete_metadata_objects", {}),
        namespace_members=namespace_members,
    )


def metadata_completion_objects_from_vm(vm) -> dict[str, list[str]]:
    """Build completion names from the Configurator's existing structure cache."""

    allowed = {category.type_name for category in METADATA_CATEGORIES}
    rows = getattr(vm, "_objects_snapshot", ()) or ()
    out: dict[str, list[str]] = {type_name: [] for type_name in allowed}
    seen: dict[str, set[str]] = {type_name: set() for type_name in allowed}
    for row in rows:
        if isinstance(row, dict):
            type_name = str(row.get("type") or "").strip()
            name = str(row.get("name") or row.get("title") or "").strip()
            title = str(row.get("title") or "").strip()
            kind = str(row.get("kind") or "").strip().lower()
        else:
            type_name = str(getattr(row, "type", "") or "").strip()
            name = str(getattr(row, "name", "") or getattr(row, "title", "") or "").strip()
            title = str(getattr(row, "title", "") or "").strip()
            kind = str(getattr(row, "kind", "") or "").strip().lower()
        if type_name not in allowed or (kind and kind != "object"):
            continue
        repaired_title = repair_cp1251_mojibake_name(title)
        aliases = (name, repaired_title or title)
        for alias in aliases:
            alias = str(alias or "").strip()
            if not alias or not alias.isidentifier() or alias.casefold() in seen[type_name]:
                continue
            seen[type_name].add(alias.casefold())
            out[type_name].append(alias)
    return {type_name: sorted(names, key=str.casefold) for type_name, names in out.items() if names}


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class CodeEditorState:
    asset_key: str
    resolved_key: str = ""
    mime: str = "text/metascript"
    is_dirty: bool = False
    is_loaded: bool = False
    last_load_error: str = ""
    language: str = "uk"   # public editor locales: uk | en


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------

class CodeEditorWidget(QWidget):
    """Full-featured MetaScript code editor.

    Signals:
        closeRequested(QWidget) — emitted when user closes the tab
        dirtyChanged(bool)      — emitted when dirty state changes
    """

    closeRequested = Signal(QWidget)
    dirtyChanged   = Signal(bool)
    saved = Signal(str)
    debugCommandRequested = Signal(str)
    definitionRequested = Signal(dict)
    usagesRequested = Signal(dict)

    def __init__(self, *, vm, asset_key: str, title: str = "",
                 language: str = "uk") -> None:
        super().__init__()
        self._vm = vm
        self._state = CodeEditorState(
            asset_key=str(asset_key or "").strip(),
            language=language,
        )
        self._title = title or t("tree.modules")
        self._current_debug_pause = None
        self._module_introspection = None
        self._workspace_diagnostics: list[dict] = []
        self._local_diagnostics: list[dict] = []
        self._introspection_timer = QTimer(self)
        self._introspection_timer.setSingleShot(True)
        self._introspection_timer.setInterval(350)
        self._introspection_timer.timeout.connect(self._refresh_module_introspection)
        self._diagnostics_timer = QTimer(self)
        self._diagnostics_timer.setSingleShot(True)
        self._diagnostics_timer.setInterval(700)
        self._diagnostics_timer.timeout.connect(self._refresh_local_diagnostics)
        self.setObjectName("CodeEditorWidget")

        self._build_ui()
        self._edit._definition_handler = self._go_to_definition
        self._edit._usages_handler = self._find_usages
        self._edit._rename_handler = self._rename_symbol
        self._edit.set_autocomplete_metadata_objects(metadata_completion_objects_from_vm(self._vm))
        self._edit.set_autocomplete_namespace_provider(
            lambda namespace: common_module_completion_members_from_vm(
                self._vm,
                namespace,
            )
        )
        self._edit._syntax_assistant.set_language(self._state.language)
        self._edit._syntax_assistant.set_namespace_provider(
            getattr(getattr(self._vm, "_service", None), "get_common_module_completion", None)
        )
        self.reload()
        self._load_breakpoints()

    # ---- Build UI ----

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- toolbar ----
        toolbar = QWidget()
        self._toolbar = toolbar
        toolbar.setObjectName("CodeEditorToolbar")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(8, 4, 8, 4)
        tb_layout.setSpacing(6)

        self._lbl_title = QLabel(self._title)
        self._lbl_title.setObjectName("CodeEditorDocumentTitle")
        self._lbl_title.setMinimumWidth(72)
        self._lbl_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        tb_layout.addWidget(self._lbl_title)

        # Language selector
        self._lang_combo = QComboBox()
        self._lang_combo.setObjectName("CodeEditorLanguage")
        self._lang_combo.addItems(["UK", "EN"])
        _lang_map = {"uk": 0, "en": 1}
        self._lang_combo.setCurrentIndex(_lang_map.get(self._state.language, 0))
        self._lang_combo.setToolTip(t("code_editor_lang_tooltip"))
        self._lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        self._lang_combo.setFixedWidth(70)
        tb_layout.addWidget(self._lang_combo)

        # Document symbols make large imported modules navigable without
        # opening a separate browser.  The list is rebuilt from the same
        # introspection snapshot used by completion and definition lookup.
        self._symbol_combo = QComboBox()
        self._symbol_combo.setObjectName("CodeEditorSymbols")
        # Keep the toolbar usable in a narrow dock; the full symbol name is
        # still available through the combo popup and its tooltip.
        self._symbol_combo.setMinimumWidth(120)
        self._symbol_combo.setMaximumWidth(190)
        self._symbol_combo.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._symbol_combo.setToolTip(t("code_editor_symbols_tooltip"))
        self._symbol_combo.currentIndexChanged.connect(self._on_symbol_selected)
        tb_layout.addWidget(self._symbol_combo)

        # Icon-only buttons
        _ss = """
            QPushButton {
                background: transparent; border: none; border-radius: 4px;
                padding: 2px; min-width: 26px; min-height: 26px;
            }
            QPushButton:hover   { background: rgba(255,255,255,0.12); }
            QPushButton:pressed { background: rgba(255,255,255,0.22); }
            QPushButton:checked { background: rgba(91,91,214,0.35); }
        """

        def _ibtn(icon_name, tooltip, checkable=False, color="#9AAFC8"):
            b = QPushButton()
            ico = _ce_icon(icon_name, color)
            b.setIcon(ico)
            b.setIconSize(QSize(16, 16))
            b.setFixedSize(28, 28)
            b.setToolTip(tooltip)
            b.setCheckable(checkable)
            b.setStyleSheet(_ss)
            return b

        def _vsep():
            from PySide6.QtWidgets import QFrame
            f = QFrame()
            f.setFrameShape(QFrame.Shape.VLine)
            f.setStyleSheet("color: rgba(255,255,255,0.12); margin: 3px 1px;")
            f.setFixedWidth(8)
            return f

        self._btn_check = _ibtn("check-circle", t("code_editor_check") + "  (Ctrl+F7)")
        self._btn_check.clicked.connect(self._on_check)
        tb_layout.addWidget(self._btn_check)

        self._btn_run = _ibtn("play", t("code_editor_run") + "  (F5)", color="#86EFAC")
        self._btn_run.clicked.connect(self._on_run)
        tb_layout.addWidget(self._btn_run)

        tb_layout.addWidget(_vsep())

        self._btn_reload = _ibtn("refresh-cw", t("btn_reload"))
        self._btn_reload.clicked.connect(self.reload)
        tb_layout.addWidget(self._btn_reload)

        self._btn_save = _ibtn("save", t("btn_save") + "  (Ctrl+S)", color="#7DD3FC")
        self._btn_save.clicked.connect(self.save)
        tb_layout.addWidget(self._btn_save)

        tb_layout.addWidget(_vsep())

        self._btn_find = _ibtn("search", t("code_editor_find") + "  (Ctrl+F)")
        self._btn_find.clicked.connect(self._on_find)
        tb_layout.addWidget(self._btn_find)

        tb_layout.addWidget(_vsep())

        self._btn_bp_toggle = _ibtn("circle", t("dbg_bp_toggle") + "  (F9)", color="#E35D6A")
        self._btn_bp_toggle.clicked.connect(self._toggle_current_breakpoint)
        tb_layout.addWidget(self._btn_bp_toggle)

        self._btn_bp_params = _ibtn("sliders-horizontal", t("dbg_bp_params") + "  (Ctrl+F9)", color="#F59E0B")
        self._btn_bp_params.clicked.connect(self._open_current_breakpoint_params)
        tb_layout.addWidget(self._btn_bp_params)

        self._btn_bp_enable = _ibtn("power", t("dbg_bp_enable_toggle") + "  (Ctrl+Shift+F9)", checkable=True, color="#7DD3FC")
        self._btn_bp_enable.setChecked(BreakpointStore().breakpoints_enabled())
        self._btn_bp_enable.clicked.connect(self._toggle_breakpoints_enabled)
        tb_layout.addWidget(self._btn_bp_enable)

        self._btn_bp_clear = _ibtn("trash-2", t("dbg_bp_clear_all"), color="#F87171")
        self._btn_bp_clear.clicked.connect(self._clear_all_breakpoints)
        tb_layout.addWidget(self._btn_bp_clear)

        self._btn_bp_move_up = _ibtn("arrow-up", t("dbg_bp_move_up") + "  (Alt+Shift+Up)")
        self._btn_bp_move_up.clicked.connect(self._move_current_breakpoint_up)
        tb_layout.addWidget(self._btn_bp_move_up)

        self._btn_bp_move_down = _ibtn("arrow-down", t("dbg_bp_move_down") + "  (Alt+Shift+Down)")
        self._btn_bp_move_down.clicked.connect(self._move_current_breakpoint_down)
        tb_layout.addWidget(self._btn_bp_move_down)

        self._btn_bp_cut = _ibtn("scissors", t("dbg_bp_cut") + "  (Ctrl+Alt+X)")
        self._btn_bp_cut.clicked.connect(self._cut_current_breakpoint)
        tb_layout.addWidget(self._btn_bp_cut)

        self._btn_bp_copy = _ibtn("copy", t("dbg_bp_copy") + "  (Ctrl+Alt+K)")
        self._btn_bp_copy.clicked.connect(self._copy_current_breakpoint)
        tb_layout.addWidget(self._btn_bp_copy)

        self._btn_bp_paste = _ibtn("clipboard", t("dbg_bp_paste") + "  (Ctrl+Alt+V)")
        self._btn_bp_paste.clicked.connect(self._paste_breakpoint)
        tb_layout.addWidget(self._btn_bp_paste)

        self._breakpoint_toolbar_buttons = [
            ("toggle", self._btn_bp_toggle, t("dbg_bp_toggle")),
            ("params", self._btn_bp_params, t("dbg_bp_params")),
            ("enable", self._btn_bp_enable, t("dbg_bp_enable_toggle")),
            ("clear", self._btn_bp_clear, t("dbg_bp_clear_all")),
            ("move_up", self._btn_bp_move_up, t("dbg_bp_move_up")),
            ("move_down", self._btn_bp_move_down, t("dbg_bp_move_down")),
            ("cut", self._btn_bp_cut, t("dbg_bp_cut")),
            ("copy", self._btn_bp_copy, t("dbg_bp_copy")),
            ("paste", self._btn_bp_paste, t("dbg_bp_paste")),
        ]
        self._migrate_breakpoint_toolbar_defaults()
        self._apply_breakpoint_toolbar_visibility()
        self._btn_bp_toolbar_menu = self._build_breakpoint_toolbar_menu()
        tb_layout.addWidget(self._btn_bp_toolbar_menu)

        tb_layout.addWidget(_vsep())

        self._btn_close = _ibtn("x", t("btn_close"), color="#F87171")
        self._btn_close.clicked.connect(lambda: self.closeRequested.emit(self))
        tb_layout.addWidget(self._btn_close)

        self._code_toolbar_buttons = [
            ("check", self._btn_check, t("code_editor_check")),
            ("run", self._btn_run, t("code_editor_run")),
            ("reload", self._btn_reload, t("btn_reload")),
            ("save", self._btn_save, t("btn_save")),
            ("find", self._btn_find, t("code_editor_find")),
            ("close", self._btn_close, t("btn_close")),
        ]
        self._apply_code_toolbar_visibility()
        self._btn_code_toolbar_menu = self._build_code_toolbar_menu()
        tb_layout.addWidget(self._btn_code_toolbar_menu)

        # Find bar (hidden by default)
        self._find_bar = self._build_find_bar()
        self._find_bar.hide()

        root.addWidget(toolbar)
        root.addWidget(self._find_bar)

        self._debug_banner = QLabel("")
        self._debug_banner.setVisible(False)
        self._debug_banner.setStyleSheet(
            "QLabel {"
            "  padding: 6px 10px;"
            "  margin: 6px 8px 4px 8px;"
            "  border-radius: 8px;"
            "  background: rgba(91, 91, 214, 0.18);"
            "  color: #DCE7FF;"
            "  border: 1px solid rgba(91, 91, 214, 0.45);"
            "}"
        )
        root.addWidget(self._debug_banner)

        self._debug_controls = QWidget(self)
        dbg_layout = QHBoxLayout(self._debug_controls)
        dbg_layout.setContentsMargins(8, 0, 8, 4)
        dbg_layout.setSpacing(6)
        self._btn_dbg_continue = QPushButton(t("dbg_continue"), self._debug_controls)
        self._btn_dbg_step_into = QPushButton(t("dbg_step_into"), self._debug_controls)
        self._btn_dbg_step_over = QPushButton(t("dbg_step_over"), self._debug_controls)
        self._btn_dbg_step_out = QPushButton(t("dbg_step_out"), self._debug_controls)
        self._btn_dbg_expr = QPushButton(t("dbg_expr"), self._debug_controls)
        for btn, command in (
            (self._btn_dbg_continue, "continue"),
            (self._btn_dbg_step_into, "step_into"),
            (self._btn_dbg_step_over, "step_over"),
            (self._btn_dbg_step_out, "step_out"),
        ):
            btn.clicked.connect(lambda _checked=False, cmd=command: self._request_debug_command(cmd))
            dbg_layout.addWidget(btn)
        self._btn_dbg_expr.clicked.connect(self._open_debug_expression_dialog)
        dbg_layout.addWidget(self._btn_dbg_expr)
        dbg_layout.addStretch(1)
        self._debug_controls.setVisible(False)
        root.addWidget(self._debug_controls)
        self._install_debug_shortcuts()

        # ---- editor ----
        self._edit = _CodeEdit(self)
        self._edit.setObjectName("CodeEditorSurface")
        self._edit.breakpointToggled = self._on_breakpoint_toggled
        self._edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._edit.textChanged.connect(self._on_text_changed)

        self._highlighter = configure_metascript_editor(self._edit)

        self._workbench_split = QSplitter(Qt.Orientation.Vertical, self)
        self._workbench_split.setObjectName("CodeEditorWorkbench")
        self._workbench_split.setChildrenCollapsible(True)
        self._workbench_split.setHandleWidth(5)
        self._workbench_split.addWidget(self._edit)

        self._debug_context_tabs = QTabWidget(self)
        self._debug_context_tabs.setObjectName("CodeEditorDebugContext")
        self._debug_context_tabs.setMaximumHeight(190)
        self._debug_stack_table = self._create_debug_context_table(
            [t("dbg_procedure"), t("dbg_line"), t("dbg_module")]
        )
        self._debug_locals_table = self._create_debug_context_table(
            [t("dbg_expr_prop"), t("dbg_expr_value"), t("dbg_expr_type")]
        )
        self._debug_globals_table = self._create_debug_context_table(
            [t("dbg_expr_prop"), t("dbg_expr_value"), t("dbg_expr_type")]
        )
        self._debug_stack_table.cellDoubleClicked.connect(self._on_debug_stack_row_activated)
        self._debug_context_tabs.addTab(self._debug_stack_table, t("dbg_stack"))
        self._debug_context_tabs.addTab(self._debug_locals_table, t("dbg_locals"))
        self._debug_context_tabs.addTab(self._debug_globals_table, t("dbg_globals"))
        self._debug_context_tabs.setVisible(False)

        self._workbench_split.addWidget(self._debug_context_tabs)

        # Diagnostics is a resizable IDE output pane, not a fixed footer.
        self._diag_panel = QPlainTextEdit()
        self._diag_panel.setObjectName("CodeEditorDiagnostics")
        self._diag_panel.setReadOnly(True)
        self._diag_panel.setMinimumHeight(72)
        self._diag_panel.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        diag_font = QFont(self._edit.font())
        diag_font.setPointSize(9)
        self._diag_panel.setFont(diag_font)
        self._diag_panel.setPlaceholderText(t("code_editor_diag_placeholder"))
        self._diag_panel.setToolTip(t("code_editor_diag_click_hint"))
        self._diag_panel.cursorPositionChanged.connect(self._on_diag_clicked)
        self._diag_panel.hide()
        self._workbench_split.addWidget(self._diag_panel)
        self._workbench_split.setStretchFactor(0, 1)
        self._workbench_split.setStretchFactor(1, 0)
        self._workbench_split.setStretchFactor(2, 0)
        self._workbench_split.setSizes([720, 170, 110])
        root.addWidget(self._workbench_split, 1)

        # ---- status bar ----
        status_bar = QWidget()
        status_bar.setObjectName("CodeEditorStatusBar")
        sb_layout = QHBoxLayout(status_bar)
        sb_layout.setContentsMargins(8, 2, 8, 2)
        sb_layout.setSpacing(8)

        self._status = QLabel("")
        self._status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sb_layout.addWidget(self._status)

        self._lbl_pos = QLabel(self._format_position_label(1, 1))
        self._lbl_pos.setAlignment(Qt.AlignmentFlag.AlignRight)
        sb_layout.addWidget(self._lbl_pos)

        root.addWidget(status_bar)

        # Cursor position tracking
        self._edit.cursorPositionChanged.connect(self._on_cursor_moved)

        self._apply_editor_chrome()

    def _apply_editor_chrome(self) -> None:
        """Keep document identity, workbench and output panes visually distinct."""

        self.setStyleSheet(
            """
            QWidget#CodeEditorWidget {
                background: #08101F;
            }
            QWidget#CodeEditorToolbar {
                background: #0D1729;
                border-bottom: 1px solid #243247;
            }
            QLabel#CodeEditorDocumentTitle {
                color: #E6EEF8;
                font-weight: 600;
                padding-left: 4px;
            }
            QComboBox#CodeEditorLanguage {
                background: #111E33;
                color: #DCE7F7;
                border: 1px solid #2A3B55;
                border-radius: 6px;
                padding: 3px 8px;
            }
            QSplitter#CodeEditorWorkbench::handle {
                background: #243247;
            }
            QTabWidget#CodeEditorDebugContext::pane {
                border: 1px solid #243247;
                border-radius: 6px;
                background: #0B1425;
            }
            QTabWidget#CodeEditorDebugContext QTabBar::tab {
                background: #0D1729;
                color: #91A4BE;
                border: 1px solid transparent;
                padding: 5px 12px;
            }
            QTabWidget#CodeEditorDebugContext QTabBar::tab:selected {
                color: #F2F7FF;
                background: #14233A;
                border-bottom-color: #4C8DFF;
            }
            QPlainTextEdit#CodeEditorDiagnostics {
                background: #0B1425;
                color: #D7E2F2;
                border: 1px solid #243247;
                border-radius: 6px;
                padding: 6px 8px;
            }
            QWidget#CodeEditorStatusBar {
                background: #0D1729;
                border-top: 1px solid #243247;
            }
            """
        )

    # ---- Properties ----

    @property
    def state(self) -> CodeEditorState:
        return self._state

    def set_status(self, msg: str, error: bool = False) -> None:
        self._status.setText(str(msg or ""))
        color = "#F07178" if error else ""
        self._status.setStyleSheet(f"color: {color};" if color else "")

    def _format_position_label(self, line: int, col: int) -> str:
        return t("code_editor_pos", line=int(line), col=int(col))

    def _code_toolbar_settings(self) -> QSettings:
        return QSettings("MetaPlatform", "CodeEditor")

    def _code_button_setting_key(self, key: str) -> str:
        return f"toolbar/codeEditor/{str(key or '').strip()}"

    def _code_button_visible(self, key: str) -> bool:
        try:
            value = self._code_toolbar_settings().value(self._code_button_setting_key(key), True)
            if isinstance(value, str):
                return value.strip().lower() not in {"0", "false", "no", "off"}
            return bool(value)
        except Exception:
            return True

    def _set_code_button_visible(self, key: str, visible: bool) -> None:
        key = str(key or "").strip()
        self._code_toolbar_settings().setValue(self._code_button_setting_key(key), bool(visible))
        for item_key, button, _label in getattr(self, "_code_toolbar_buttons", []) or []:
            if item_key == key:
                button.setVisible(bool(visible))
                break

    def _apply_code_toolbar_visibility(self) -> None:
        for key, button, _label in getattr(self, "_code_toolbar_buttons", []) or []:
            button.setVisible(self._code_button_visible(key))

    def _reset_code_toolbar(self) -> None:
        settings = self._code_toolbar_settings()
        actions = getattr(self, "_code_toolbar_actions", {}) or {}
        for key, button, _label in getattr(self, "_code_toolbar_buttons", []) or []:
            settings.setValue(self._code_button_setting_key(key), True)
            button.setVisible(True)
            action = actions.get(key)
            if action is not None:
                action.blockSignals(True)
                action.setChecked(True)
                action.blockSignals(False)
        self.set_status(t("code_toolbar_reset_done"))

    def _build_code_toolbar_menu(self) -> QToolButton:
        button = QToolButton(self)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setIcon(_ce_icon("chevron-down", "#9AAFC8"))
        button.setIconSize(QSize(16, 16))
        button.setFixedSize(22, 28)
        button.setToolTip(t("code_toolbar_menu"))
        button.setStyleSheet(
            """
            QToolButton {
                background: transparent; border: none; border-radius: 4px;
                padding: 2px; min-width: 22px; min-height: 26px;
            }
            QToolButton:hover { background: rgba(255,255,255,0.12); }
            QToolButton:pressed { background: rgba(255,255,255,0.22); }
            """
        )
        menu = QMenu(button)
        self._code_toolbar_actions = {}
        for key, _widget, label in getattr(self, "_code_toolbar_buttons", []) or []:
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(self._code_button_visible(key))
            action.toggled.connect(lambda checked, item_key=key: self._set_code_button_visible(item_key, checked))
            menu.addAction(action)
            self._code_toolbar_actions[key] = action
        menu.addSeparator()
        reset_action = QAction(t("code_toolbar_reset"), menu)
        reset_action.triggered.connect(self._reset_code_toolbar)
        menu.addAction(reset_action)
        settings_action = QAction(t("code_toolbar_settings"), menu)
        settings_action.triggered.connect(lambda: self.set_status(t("code_toolbar_settings_hint")))
        menu.addAction(settings_action)
        button.setMenu(menu)
        return button

    def _breakpoint_toolbar_settings(self) -> QSettings:
        return QSettings("MetaPlatform", "CodeEditor")

    def _breakpoint_button_setting_key(self, key: str) -> str:
        return f"debug/breakpointToolbar/{str(key or '').strip()}"

    def _breakpoint_button_visible(self, key: str) -> bool:
        try:
            default_visible = str(key or "") in {"toggle", "params", "enable"}
            value = self._breakpoint_toolbar_settings().value(
                self._breakpoint_button_setting_key(key),
                default_visible,
            )
            if isinstance(value, str):
                return value.strip().lower() not in {"0", "false", "no", "off"}
            return bool(value)
        except Exception:
            return True

    def _migrate_breakpoint_toolbar_defaults(self) -> None:
        settings = self._breakpoint_toolbar_settings()
        version_key = "debug/breakpointToolbar/layoutVersion"
        try:
            version = int(settings.value(version_key, 0) or 0)
        except Exception:
            version = 0
        if version >= 2:
            return
        primary = {"toggle", "params", "enable"}
        for key, _button, _label in getattr(self, "_breakpoint_toolbar_buttons", []) or []:
            settings.setValue(self._breakpoint_button_setting_key(key), key in primary)
        settings.setValue(version_key, 2)

    def _set_breakpoint_button_visible(self, key: str, visible: bool) -> None:
        key = str(key or "").strip()
        self._breakpoint_toolbar_settings().setValue(self._breakpoint_button_setting_key(key), bool(visible))
        for item_key, button, _label in getattr(self, "_breakpoint_toolbar_buttons", []) or []:
            if item_key == key:
                button.setVisible(bool(visible))
                break

    def _apply_breakpoint_toolbar_visibility(self) -> None:
        for key, button, _label in getattr(self, "_breakpoint_toolbar_buttons", []) or []:
            button.setVisible(self._breakpoint_button_visible(key))

    def _reset_breakpoint_toolbar(self) -> None:
        settings = self._breakpoint_toolbar_settings()
        actions = getattr(self, "_breakpoint_toolbar_actions", {}) or {}
        for key, button, _label in getattr(self, "_breakpoint_toolbar_buttons", []) or []:
            settings.setValue(self._breakpoint_button_setting_key(key), True)
            button.setVisible(True)
            action = actions.get(key)
            if action is not None:
                action.blockSignals(True)
                action.setChecked(True)
                action.blockSignals(False)
        self.set_status(t("dbg_bp_toolbar_reset_done"))

    def _build_breakpoint_toolbar_menu(self) -> QToolButton:
        button = QToolButton(self)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setIcon(_ce_icon("chevron-down", "#9AAFC8"))
        button.setIconSize(QSize(16, 16))
        button.setFixedSize(22, 28)
        button.setToolTip(t("dbg_bp_toolbar_menu"))
        button.setStyleSheet(
            """
            QToolButton {
                background: transparent; border: none; border-radius: 4px;
                padding: 2px; min-width: 22px; min-height: 26px;
            }
            QToolButton:hover { background: rgba(255,255,255,0.12); }
            QToolButton:pressed { background: rgba(255,255,255,0.22); }
            """
        )
        menu = QMenu(button)
        self._breakpoint_toolbar_actions = {}
        for key, _widget, label in getattr(self, "_breakpoint_toolbar_buttons", []) or []:
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(self._breakpoint_button_visible(key))
            action.toggled.connect(lambda checked, item_key=key: self._set_breakpoint_button_visible(item_key, checked))
            menu.addAction(action)
            self._breakpoint_toolbar_actions[key] = action
        menu.addSeparator()
        reset_action = QAction(t("dbg_bp_toolbar_reset"), menu)
        reset_action.triggered.connect(self._reset_breakpoint_toolbar)
        menu.addAction(reset_action)
        settings_action = QAction(t("dbg_bp_toolbar_settings"), menu)
        settings_action.triggered.connect(lambda: self.set_status(t("dbg_bp_toolbar_settings_hint")))
        menu.addAction(settings_action)
        button.setMenu(menu)
        return button

    def _install_debug_shortcuts(self) -> None:
        self._debug_shortcuts = []
        bindings = {
            "Ctrl+S": "save",
            "Ctrl+F": "find",
            "Ctrl+F7": "check",
            "Shift+F9": "expr",
            "F9": "toggle_breakpoint",
            "Ctrl+F9": "breakpoint_params",
            "Ctrl+Shift+F9": "toggle_breakpoints_enabled",
            "Alt+Shift+Up": "move_breakpoint_up",
            "Alt+Shift+Down": "move_breakpoint_down",
            "Ctrl+Alt+X": "cut_breakpoint",
            "Ctrl+Alt+K": "copy_breakpoint",
            "Ctrl+Alt+V": "paste_breakpoint",
            "F10": "step_over",
            "F11": "step_into",
            "Shift+F11": "step_out",
            "F12": "go_to_definition",
            "Shift+F12": "find_usages",
            "Shift+F6": "rename_symbol",
            "Ctrl+Shift+F6": "rename_workspace_preview",
        }
        for key, command in bindings.items():
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda cmd=command: self._handle_debug_shortcut(cmd))
            self._debug_shortcuts.append(shortcut)

    def _is_debug_paused(self) -> bool:
        return bool(self._debug_controls.isVisible())

    def _handle_debug_shortcut(self, command: str) -> None:
        command = str(command or "").strip()
        if command == "save":
            self.save()
            return
        if command == "find":
            self._on_find()
            return
        if command == "check":
            self._on_check()
            return
        if command == "continue_or_run":
            window_handler = getattr(self.window(), "_debug_f5_action", None)
            if callable(window_handler):
                window_handler()
                return
            if self._is_debug_paused():
                self._request_debug_command("continue")
            else:
                self._on_run()
            return
        if command == "force_stop_debug":
            window_handler = getattr(self.window(), "_debug_shift_f5_action", None)
            if callable(window_handler):
                window_handler()
            return
        if command == "toggle_breakpoint":
            self._toggle_current_breakpoint()
            return
        if command == "breakpoint_params":
            self._open_current_breakpoint_params()
            return
        if command == "toggle_breakpoints_enabled":
            self._toggle_breakpoints_enabled()
            return
        if command == "move_breakpoint_up":
            self._move_current_breakpoint_up()
            return
        if command == "move_breakpoint_down":
            self._move_current_breakpoint_down()
            return
        if command == "cut_breakpoint":
            self._cut_current_breakpoint()
            return
        if command == "copy_breakpoint":
            self._copy_current_breakpoint()
            return
        if command == "paste_breakpoint":
            self._paste_breakpoint()
            return
        if command == "expr":
            self._open_debug_expression_dialog()
            return
        if command == "go_to_definition":
            self._go_to_definition()
            return
        if command == "find_usages":
            self._find_usages()
            return
        if command == "rename_symbol":
            self._rename_symbol()
            return
        if command == "rename_workspace_preview":
            self._preview_workspace_rename()
            return
        if self._is_debug_paused() and command in {"step_into", "step_over", "step_out"}:
            self._request_debug_command(command)

    # ---- Events ----

    def _on_text_changed(self) -> None:
        if not self._state.is_dirty:
            self._state.is_dirty = True
            self._update_title()
            self.dirtyChanged.emit(True)
        try:
            self._introspection_timer.start()
        except Exception:
            pass
        try:
            self._diagnostics_timer.start()
        except Exception:
            pass

    def _on_cursor_moved(self) -> None:
        cursor = self._edit.textCursor()
        line = cursor.blockNumber() + 1
        col = cursor.columnNumber() + 1
        self._lbl_pos.setText(self._format_position_label(line, col))

    def _on_lang_changed(self, idx: int) -> None:
        mapping = {0: "uk", 1: "en"}
        self._state.language = mapping.get(idx, "uk")
        self._edit._autocomplete_language = self._state.language
        self._edit._syntax_assistant.set_language(self._state.language)
        self._refresh_module_introspection()

    def _on_symbol_selected(self, index: int) -> None:
        if index < 0:
            return
        line = self._symbol_combo.itemData(index)
        if line is None:
            return
        try:
            line_i = int(line)
        except (TypeError, ValueError):
            return
        if line_i > 0:
            self.navigate_to_line(line_i)

    def _effective_introspection_language(self) -> str:
        return "mixed" if self._is_module_asset() else str(self._state.language or "uk")

    def _refresh_module_introspection(self) -> None:
        try:
            info = introspect_module_source(
                self._edit.toPlainText(),
                language=self._effective_introspection_language(),
            )
            self._module_introspection = info
            combo = getattr(self, "_symbol_combo", None)
            if combo is not None:
                combo.blockSignals(True)
                try:
                    combo.clear()
                    combo.addItem(t("code_editor_symbols_placeholder"), 0)
                    for symbol in info.symbols:
                        kind = str(getattr(symbol, "kind", "") or "")
                        if kind not in {"procedure", "function"}:
                            continue
                        name = str(getattr(symbol, "name", "") or "").strip()
                        if name:
                            combo.addItem(f"{name}  [{kind}]", int(getattr(symbol, "line", 0) or 0))
                finally:
                    combo.setCurrentIndex(0)
                    combo.blockSignals(False)
            words: set[str] = set(info.runtime_names)
            for symbol in info.symbols:
                words.add(symbol.name)
                words.update(symbol.aliases)
            current_line = self._edit.textCursor().blockNumber() + 1
            for scope in getattr(info, "scopes", ()) or ():
                words.add(str(getattr(scope, "name", "") or ""))
                words.update(getattr(scope, "aliases", ()) or ())
                if scope.contains_line(current_line):
                    words.update(str(name) for name in (getattr(scope, "params", ()) or ()) if str(name).strip())
                    words.update(str(name) for name in (getattr(scope, "locals", ()) or ()) if str(name).strip())
            self._edit.set_autocomplete_words(words)
        except Exception:
            pass

    def _go_to_definition(self) -> None:
        self._refresh_module_introspection()
        target = resolve_definition_target(
            self._edit.toPlainText(),
            self._edit.textCursor().position(),
            introspection=self._module_introspection,
            vm=self._vm,
        )
        if target is None:
            self.set_status(t("code_editor_definition_not_found"))
            return
        if target.kind == "local" and target.line > 0:
            self.navigate_to_line(target.line)
            self.set_status(
                t("code_editor_definition_local").format(
                    name=target.name,
                    line=target.line,
                )
            )
            return
        self.definitionRequested.emit(target.as_dict())

    def _find_usages(self) -> None:
        self._refresh_module_introspection()
        source = self._edit.toPlainText()
        position = self._edit.textCursor().position()
        chain = identifier_chain_at(source, position)
        if not chain:
            self.set_status(t("code_editor_definition_not_found"))
            return
        term = ".".join(chain)
        module_guid = ""
        if len(chain) == 1:
            current_line = self._edit.textCursor().blockNumber() + 1
            local_names: set[str] = set()
            for scope in getattr(self._module_introspection, "scopes", ()) or ():
                if scope.contains_line(current_line):
                    local_names.update(str(name).casefold() for name in (*scope.params, *scope.locals))
            if chain[0].casefold() in local_names:
                asset_key = str(self._state.resolved_key or self._state.asset_key or "")
                if asset_key.startswith("module://"):
                    module_guid = asset_key.split("://", 1)[1].strip()
        self.usagesRequested.emit(
            {
                "term": term,
                "whole_word": True,
                "module_guid": module_guid,
                "title": t("code_editor_find_usages"),
            }
        )

    def _rename_symbol(self) -> None:
        from src.ui_qt.widgets.semantic_rename_dialog import (
            apply_semantic_rename_plan,
            request_semantic_rename,
        )

        try:
            plan = request_semantic_rename(
                source=self._edit.toPlainText(),
                cursor_position=self._edit.textCursor().position(),
                language=self._effective_introspection_language(),
                parent=self,
            )
        except Exception as exc:
            self.set_status(t("rename_symbol_failed").format(error=exc), error=True)
            return
        if plan is None:
            return
        apply_semantic_rename_plan(self._edit, plan)
        self._refresh_module_introspection()
        self.set_status(
            t("rename_symbol_done").format(
                old=plan.old_name,
                new=plan.new_name,
                count=len(plan.occurrences),
            )
        )

    def _preview_workspace_rename(self) -> None:
        if self.is_dirty():
            self.set_status(t("rename_workspace_unsaved"), error=True)
            return
        source = self._edit.toPlainText()
        position = self._edit.textCursor().position()
        from src.dsl.semantic_rename import symbol_name_at

        old_name = symbol_name_at(source, position, language="mixed")
        if not old_name:
            self.set_status(t("rename_symbol_error_caret"), error=True)
            return
        info = introspect_module_source(source, language="mixed")
        symbol = (
            info.symbol_by_name.get(old_name)
            or info.symbol_by_name.get(old_name.casefold())
        )
        if (
            symbol is None
            or str(symbol.kind or "") not in {"procedure", "function"}
            or not bool(symbol.exported)
        ):
            self.set_status(t("rename_workspace_requires_exported"), error=True)
            return
        new_name, accepted = QInputDialog.getText(
            self,
            t("rename_workspace_preview_title"),
            t("rename_symbol_new_name"),
            QLineEdit.EchoMode.Normal,
            old_name,
        )
        if not accepted:
            return
        service = getattr(self._vm, "_service", None)
        planner = getattr(service, "plan_workspace_symbol_rename", None)
        if not callable(planner):
            self.set_status(t("rename_workspace_service_unavailable"), error=True)
            return
        asset_key = str(self.state.resolved_key or self.state.asset_key or "")
        module_guid = asset_key.split("://", 1)[-1].strip()
        try:
            plan = planner(
                module_guid,
                new_name=str(new_name or ""),
                symbol_name=old_name,
                module_name=str(self._title or self.windowTitle() or ""),
            )
        except Exception as exc:
            self.set_status(t("rename_symbol_failed").format(error=exc), error=True)
            return
        from src.ui_qt.widgets.semantic_rename_dialog import (
            request_workspace_rename_apply,
        )

        if not request_workspace_rename_apply(plan, parent=self):
            return
        affected_guids = {
            str(item.get("module_guid") or "").strip()
            for item in list(plan.get("modules") or [])
            if isinstance(item, dict)
        }
        root: QWidget = self
        while root.parentWidget() is not None:
            root = root.parentWidget()
        affected_editors: list[CodeEditorWidget] = []
        dirty_titles: list[str] = []
        editors = [self]
        editors.extend(
            editor
            for editor in root.findChildren(CodeEditorWidget)
            if editor is not self
        )
        for editor in editors:
            editor_key = str(
                editor.state.resolved_key or editor.state.asset_key or ""
            ).strip()
            editor_guid = editor_key.split("://", 1)[-1].strip()
            if editor_guid not in affected_guids:
                continue
            affected_editors.append(editor)
            if editor.is_dirty():
                dirty_titles.append(
                    str(
                        getattr(editor, "_title", "")
                        or editor.windowTitle()
                        or editor_guid
                    )
                )
        if dirty_titles:
            self.set_status(
                t("rename_workspace_dirty_modules").format(
                    modules=", ".join(dirty_titles)
                ),
                error=True,
            )
            return
        applier = getattr(service, "apply_workspace_symbol_rename", None)
        if not callable(applier):
            self.set_status(t("rename_workspace_service_unavailable"), error=True)
            return
        try:
            result = applier(
                module_guid,
                new_name=str(new_name or ""),
                symbol_name=old_name,
                module_name=str(self._title or self.windowTitle() or ""),
                modules=list(plan.get("modules") or []),
            )
        except Exception as exc:
            self.set_status(t("rename_symbol_failed").format(error=exc), error=True)
            return
        for editor in affected_editors:
            editor.reload()
        self.set_status(
            t("rename_workspace_done").format(
                modules=int(result.get("updated") or result.get("module_count") or 0),
                count=int(result.get("occurrence_count") or 0),
            )
        )

    def _format_debug_cell(self, value) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            return str(value)

    def _create_debug_context_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(self)
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels([str(item) for item in headers])
        table.horizontalHeader().setStretchLastSection(True)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        def _selected_text() -> str:
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

        def _copy() -> None:
            text = _selected_text()
            if text:
                from PySide6.QtWidgets import QApplication

                QApplication.clipboard().setText(text)

        copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, table)
        copy_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        copy_shortcut.activated.connect(_copy)
        table._mp_copy_shortcut = copy_shortcut

        def _menu(pos) -> None:
            menu = QMenu(table)
            action = menu.addAction(t("act_copy"))
            action.triggered.connect(_copy)
            menu.exec(table.viewport().mapToGlobal(pos))

        table.customContextMenuRequested.connect(_menu)
        return table

    def _fill_debug_table(self, table: QTableWidget, rows: list[tuple]) -> None:
        table.setRowCount(0)
        table.setRowCount(len(rows))
        for row_idx, row in enumerate(rows):
            for col_idx, value in enumerate(row):
                table.setItem(row_idx, col_idx, QTableWidgetItem(self._format_debug_cell(value)))
        try:
            table.resizeColumnsToContents()
            table.horizontalHeader().setStretchLastSection(True)
        except Exception:
            pass

    def _populate_debug_context(self, pause) -> None:
        stack_rows: list[tuple] = []
        for item in list(getattr(pause, "stack", []) or []):
            if not isinstance(item, dict):
                continue
            stack_rows.append(
                (
                    item.get("code_name", ""),
                    item.get("line", 0),
                    item.get("module_id", getattr(pause, "module_id", "")),
                )
            )
        if not stack_rows:
            stack_rows.append(
                (
                    str(getattr(pause, "code_name", "") or ""),
                    int(getattr(pause, "line", 0) or 0),
                    str(getattr(pause, "module_id", "") or ""),
                )
            )
        local_rows = [
            (key, value, type(value).__name__)
            for key, value in list((getattr(pause, "locals", {}) or {}).items())
        ]
        global_rows = [
            (key, value, type(value).__name__)
            for key, value in list((getattr(pause, "globals", {}) or {}).items())
        ]
        self._fill_debug_table(self._debug_stack_table, stack_rows)
        self._fill_debug_table(self._debug_locals_table, local_rows)
        self._fill_debug_table(self._debug_globals_table, global_rows)
        self._debug_context_tabs.setVisible(True)

    def _on_debug_stack_row_activated(self, row: int, _column: int) -> None:
        try:
            item = self._debug_stack_table.item(int(row), 1)
            line = int(item.text()) if item is not None else 0
        except Exception:
            line = 0
        if line > 0:
            self.focus_debug_location(line, pause=self._current_debug_pause)

    def _set_debug_pause_banner(self, pause) -> None:
        # A debug session has one instruction pointer. When execution moves to
        # another module, remove the stale marker from every sibling editor in
        # the same Configurator window before exposing the new pause.
        root: QWidget = self
        while root.parentWidget() is not None:
            root = root.parentWidget()
        for editor in root.findChildren(CodeEditorWidget):
            if editor is self:
                continue
            if getattr(editor, "_current_debug_pause", None) is not None:
                editor._clear_debug_pause_banner()

        self._current_debug_pause = pause
        try:
            remember_debug_pause(pause)
        except Exception:
            pass
        module_id = str(getattr(pause, "module_id", "") or "").strip() or "<unknown>"
        code_name = str(getattr(pause, "code_name", "") or "").strip() or "<entry>"
        line = int(getattr(pause, "line", 0) or 0)
        depth = int(getattr(pause, "depth", 0) or 0)
        self._debug_banner.setText(
            f"{t('dbg_paused')}: {module_id}  |  {code_name}  |  {t('dbg_line')}: {line}  |  {t('dbg_depth')}: {depth}"
        )
        self._debug_banner.setVisible(True)
        self._debug_controls.setVisible(True)
        self._populate_debug_context(pause)
        self._edit.reveal_line(line)
        self._lbl_pos.setText(self._format_position_label(line, 1))

    def _request_debug_command(self, command: str) -> None:
        normalized = str(command or "continue").strip().lower() or "continue"
        self.debugCommandRequested.emit(normalized)
        if normalized in {"continue", "step_into", "step_over", "step_out"}:
            self._clear_debug_pause_banner()

    def focus_debug_location(self, line: int, pause=None) -> None:
        if pause is not None:
            self._set_debug_pause_banner(pause)
        else:
            self._edit.reveal_line(line)
            self._lbl_pos.setText(self._format_position_label(int(line or 0), 1))
        try:
            self.raise_()
            self.activateWindow()
        except Exception:
            pass
        try:
            self._edit.setFocus()
        except Exception:
            pass

    def navigate_to_line(self, line: int) -> None:
        self._edit.navigate_to_line(line)
        self._lbl_pos.setText(self._format_position_label(int(line or 0), 1))
        try:
            self._edit.setFocus()
        except Exception:
            pass

    def set_workspace_diagnostics(self, diagnostics: list[dict]) -> None:
        asset_key = str(
            self._state.resolved_key or self._state.asset_key or ""
        ).strip()
        module_guid = (
            asset_key.split("://", 1)[1].strip()
            if asset_key.startswith("module://")
            else ""
        )
        if not module_guid:
            self._workspace_diagnostics = []
            self._apply_editor_diagnostics()
            return
        normalized_guid = module_guid.casefold()
        self._workspace_diagnostics = [
            dict(item)
            for item in list(diagnostics or [])
            if isinstance(item, dict)
            and str(item.get("module_guid") or "").strip().casefold()
            == normalized_guid
        ]
        self._apply_editor_diagnostics()

    def _apply_editor_diagnostics(self) -> None:
        self._edit.set_workspace_diagnostics(
            [*self._local_diagnostics, *self._workspace_diagnostics]
        )

    def _refresh_local_diagnostics(self) -> None:
        """Parse the current buffer and highlight syntax errors without saving."""
        try:
            from src.dsl.languages import get_profile
            from src.dsl.parser import parse

            profile = get_profile(self._effective_module_language())  # type: ignore[arg-type]
            _program, diagnostics = parse(self._edit.toPlainText(), profile)
            self._set_local_diagnostics(diagnostics)
        except Exception as exc:
            self._local_diagnostics = [
                {
                    "source": "parser",
                    "code": "parser.internal",
                    "severity": "error",
                    "line": 1,
                    "col": 1,
                    "message": str(exc),
                    "display_message": str(exc),
                }
            ]
            self._apply_editor_diagnostics()

    def _set_local_diagnostics(self, diagnostics) -> None:
        self._local_diagnostics = [
            {
                "source": "parser",
                "code": "parser",
                "severity": str(diag.severity or "error"),
                "line": int(diag.span.line or 1),
                "col": int(diag.span.col or 1),
                "message": str(diag.message or ""),
                "display_message": str(diag.message or ""),
            }
            for diag in diagnostics
        ]
        self._apply_editor_diagnostics()

    def _clear_debug_pause_banner(self) -> None:
        previous_pause = self._current_debug_pause
        self._current_debug_pause = None
        if previous_pause is not None:
            try:
                forget_debug_pause(previous_pause)
            except Exception:
                pass
        self._debug_banner.clear()
        self._debug_banner.setVisible(False)
        self._debug_controls.setVisible(False)
        self._debug_context_tabs.setVisible(False)
        self._edit.clear_debug_line()

    def _debug_expression_from_cursor(self) -> str:
        cursor = self._edit.textCursor()
        if cursor.hasSelection():
            selected = cursor.selectedText().replace("\u2029", " ").strip()
            if selected:
                match = re.search(r"[A-Za-z_А-Яа-яІіЇїЄєҐґ][A-Za-z_А-Яа-яІіЇїЄєҐґ0-9.]*", selected)
                if match:
                    return match.group(0).strip()
                return selected
        block = cursor.block().text()
        pos = cursor.positionInBlock()
        if pos < 0:
            return ""
        left = pos
        right = pos
        allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_0123456789А-Яа-яІіЇїЄєҐґ.")
        while left > 0 and block[left - 1] in allowed:
            left -= 1
        while right < len(block) and block[right] in allowed:
            right += 1
        return block[left:right].strip()

    def _open_debug_expression_dialog(self) -> None:
        pause = self._current_debug_pause or get_last_debug_pause()
        if pause is None:
            self.set_status(t("dbg_expr_help"), error=True)
            return
        expression = self._debug_expression_from_cursor()
        show_debug_expression(pause, expression=expression, parent=self)

    def _handle_debug_pause(self, pause) -> str:
        self._set_debug_pause_banner(pause)
        command = {"value": "continue"}
        loop = QEventLoop(self)

        def _on_command(cmd: str) -> None:
            command["value"] = str(cmd or "continue").strip().lower() or "continue"
            try:
                self.debugCommandRequested.disconnect(_on_command)
            except Exception:
                pass
            loop.quit()

        self.debugCommandRequested.connect(_on_command)
        loop.exec()
        return command["value"]

    def _update_title(self) -> None:
        dirty_mark = " *" if self._state.is_dirty else ""
        self._lbl_title.setText(self._title + dirty_mark)

    # ---- Find Bar ----

    def _build_find_bar(self) -> QWidget:
        """Build the inline find/replace bar."""
        bar = QWidget()
        bar.setObjectName("CodeEditorFindBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(4)

        lay.addWidget(QLabel(t("code_editor_find") + ":"))
        self._find_edit = QLineEdit()
        self._find_edit.setPlaceholderText(t("code_editor_find_placeholder"))
        self._find_edit.returnPressed.connect(self._on_find_next)
        lay.addWidget(self._find_edit, 1)

        lay.addWidget(QLabel(t("code_editor_replace") + ":"))
        self._replace_edit = QLineEdit()
        self._replace_edit.setPlaceholderText(t("code_editor_replace_placeholder"))
        lay.addWidget(self._replace_edit, 1)

        btn_next = QPushButton(t("code_editor_find_next"))
        btn_next.clicked.connect(self._on_find_next)
        lay.addWidget(btn_next)

        btn_replace = QPushButton(t("code_editor_replace_one"))
        btn_replace.clicked.connect(self._on_replace_one)
        lay.addWidget(btn_replace)

        btn_replace_all = QPushButton(t("code_editor_replace_all"))
        btn_replace_all.clicked.connect(self._on_replace_all)
        lay.addWidget(btn_replace_all)

        btn_close_find = QPushButton("✕")
        btn_close_find.setFixedWidth(24)
        btn_close_find.clicked.connect(lambda: self._find_bar.hide())
        lay.addWidget(btn_close_find)

        return bar

    def _on_find(self) -> None:
        """Show find bar and focus search field."""
        self._find_bar.show()
        self._find_edit.setFocus()
        # Pre-fill with selected text if any
        sel = self._edit.textCursor().selectedText().strip()
        if sel and "\n" not in sel:
            self._find_edit.setText(sel)
        self._find_edit.selectAll()

    def _on_find_next(self) -> None:
        term = self._find_edit.text()
        if not term:
            return
        doc = self._edit.document()
        cursor = self._edit.textCursor()
        found = doc.find(term, cursor)
        if found.isNull():
            # Wrap around
            from PySide6.QtGui import QTextCursor as _TC
            found = doc.find(term, _TC(doc))
        if not found.isNull():
            self._edit.setTextCursor(found)
        else:
            self.set_status(t("code_editor_not_found").format(term=term), error=True)

    def _on_replace_one(self) -> None:
        term    = self._find_edit.text()
        replace = self._replace_edit.text()
        if not term:
            return
        cursor = self._edit.textCursor()
        if cursor.selectedText() == term:
            cursor.insertText(replace)
        self._on_find_next()

    def _on_replace_all(self) -> None:
        term    = self._find_edit.text()
        replace = self._replace_edit.text()
        if not term:
            return
        src = self._edit.toPlainText()
        new_src = src.replace(term, replace)
        if new_src != src:
            self._edit.setPlainText(new_src)
            n = src.count(term)
            self.set_status(t("code_editor_replaced").format(n=n))

    def _on_diag_clicked(self) -> None:
        """Jump to line in editor when user clicks a diagnostic message."""
        try:
            cursor = self._diag_panel.textCursor()
            cursor.select(cursor.SelectionType.LineUnderCursor)
            line_text = cursor.selectedText()
            # Parse "✗ L12:5  message" or "L12:5" or "line 12"
            import re as _re
            m = _re.search(r"L(\d+)[:\s]", line_text)
            if not m:
                m = _re.search(r"line[: ]+(\d+)", line_text, _re.I)
            if m:
                ln = int(m.group(1))
                self._jump_to_line(ln)
        except Exception:
            pass

    def _jump_to_line(self, line: int) -> None:
        """Move cursor to the given 1-based line in the editor."""
        doc = self._edit.document()
        block = doc.findBlockByLineNumber(max(0, line - 1))
        if block.isValid():
            cursor = QTextCursor(block)
            self._edit.setTextCursor(cursor)
            self._edit.setFocus()

    def _is_module_asset(self) -> bool:
        return str(self._state.asset_key or "").strip().startswith("module://")

    def _looks_like_legacy_bsl_source(self, src: str) -> bool:
        """Return True when source contains 1C/BSL constructs unsupported by our DSL parser.

        We intentionally keep this heuristic conservative:
        - region pragmas (`#Область`, `#Region`)
        - skipped positional arguments (`,,,`)
        - multilingual `NStr`-style payloads (`;uk='...'`, `;en='...'`, `;ru='...'`)
        """

        text = str(src or "")
        if not text:
            return False
        if re.search(r"(?im)^\s*#\s*(область|конецобласти|region|endregion)\b", text):
            return True
        if ",,," in text or re.search(r",\s*,", text):
            return True
        if re.search(r";\s*(uk|en|ru)\s*='", text, flags=re.IGNORECASE):
            return True
        return False

    def _show_unsupported_bsl_diagnostics(self) -> None:
        self._diag_panel.setPlainText(t("code_editor_bsl_diag_unsupported"))
        self._diag_panel.show()
        self.set_status(t("code_editor_bsl_diag_status"))

    def _effective_module_language(self) -> str:
        # Imported modules may contain mixed UK/EN/RU 1C syntax.
        # Parsing/checking/running them through MIXED keeps the editor functional
        # while the UI selector still controls normalization workflows elsewhere.
        if self._is_module_asset():
            return "mixed"
        return str(self._state.language or "uk")

    # ---- Keyboard shortcuts ----

    def keyPressEvent(self, event) -> None:
        from PySide6.QtCore import Qt as _Qt
        if event.key() == _Qt.Key.Key_F and (event.modifiers() & _Qt.KeyboardModifier.ControlModifier):
            self._on_find()
            return
        if event.key() == _Qt.Key.Key_G and (event.modifiers() & _Qt.KeyboardModifier.ControlModifier):
            current = self._edit.textCursor().blockNumber() + 1
            line, accepted = QInputDialog.getInt(
                self,
                t("code_editor_goto_line_title"),
                t("code_editor_goto_line_prompt"),
                max(1, current),
                1,
                max(1, self._edit.blockCount()),
            )
            if accepted:
                self.navigate_to_line(line)
            return
        if event.key() == _Qt.Key.Key_S and (event.modifiers() & _Qt.KeyboardModifier.ControlModifier):
            self.save()
            return
        super().keyPressEvent(event)

    # ---- Check / Run ----

    def _on_check(self) -> None:
        """Parse the code and show diagnostics."""
        try:
            from src.dsl.languages import get_profile
            from src.dsl.parser import parse
            from src.dsl.compiler import compile_module

            src = self._edit.toPlainText()
            profile = get_profile(self._effective_module_language())  # type: ignore[arg-type]
            prog, diags = parse(src, profile)
            self._set_local_diagnostics(diags)

            if prog is not None and not any(d.severity == "error" for d in diags):
                compile_module(
                    prog,
                    module_name=self._state.asset_key or self._state.title or "<module>",
                )

            if not diags:
                self._diag_panel.hide()
                self.set_status(t("code_editor_ok"))
                return

            lines = []
            for d in diags:
                icon = "✗" if d.severity == "error" else "⚠"
                lines.append(f"{icon} L{d.span.line}:{d.span.col}  {d.message}")

            self._diag_panel.setPlainText("\n".join(lines))
            self._diag_panel.show()

            errors = [d for d in diags if d.severity == "error"]
            warns  = [d for d in diags if d.severity == "warning"]
            self.set_status(
                t("code_editor_summary").format(
                    errors=len(errors), warnings=len(warns)
                ),
                error=bool(errors),
            )

        except Exception as e:
            self.set_status(f"{t('code_editor_internal_error')}: {e}", error=True)

    def _on_run(self) -> None:
        """Execute the module's entry procedure with optional DB context."""
        try:
            from src.runtime.script.vm import execute_script

            src = self._edit.toPlainText()
            lang = self._effective_module_language()

            # Collect all output via Message() hook
            output_lines: List[str] = []
            import time as _time
            t_start = _time.perf_counter()

            def _capture_message(x):
                output_lines.append(str(x) if x is not None else "")

            builtins_patch: dict = {
                "Message":       _capture_message,
                "Повідомлення":  _capture_message,
                "Alert":         _capture_message,
                "Попередження":  _capture_message,
                "Print":         _capture_message,
                "print":         _capture_message,
            }

            # Inject DB if VM has one open
            db = None
            try:
                if self._vm is not None and hasattr(self._vm, "_service"):
                    db = self._vm._service.require_db()
            except Exception:
                pass
            if db is not None:
                from src.runtime.numerator import Numerator
                builtins_patch.update({
                    "DB":        db,
                    "БД":        db,
                    "Numerator": Numerator,
                    "Нумератор": Numerator,
                })

            debugger = self._build_debug_session()

            # Try common entry points
            result = None
            errors: List[str] = []
            entry_tried: Optional[str] = None
            for entry in (
                "ПередНачаломРаботыСистемы",
                "ПередПочаткомРоботиСистеми",
                "OnSystemStartup",
                "ПриПочаткуРоботиСистеми",
                "Main",
                "Головна",
                "OnGenerate",
                "ПриФормуванні",
            ):
                result, errors = execute_script(
                    src, language=lang, entry=entry,
                    extra_builtins=builtins_patch,
                    module_name=self._breakpoint_module_id() or self._title,
                    debug_session=debugger,
                    strict_entry=True,
                )
                if not errors:
                    entry_tried = entry
                    break

            elapsed_ms = int((_time.perf_counter() - t_start) * 1000)
            out = "\n".join(output_lines)

            if errors:
                diag_text = (
                    f"─── {t('code_editor_run_errors')} ({elapsed_ms}ms) ───\n"
                    + "\n".join(errors)
                )
                if out:
                    diag_text = out + "\n\n" + diag_text
                self._diag_panel.setStyleSheet("color: #F07178;")
            else:
                header = f"─── {t('code_editor_run_ok')} [{entry_tried}] {elapsed_ms}ms ───"
                diag_text = header
                if out:
                    diag_text += "\n" + out
                if result is not None:
                    diag_text += f"\n→ {result}"
                self._diag_panel.setStyleSheet("")

            self._diag_panel.setPlainText(diag_text)
            self._diag_panel.show()
            self.set_status(
                f"{t('code_editor_run_ok')} ({elapsed_ms}ms)" if not errors
                else t("code_editor_run_failed"),
                error=bool(errors),
            )

        except Exception as e:
            self.set_status(f"{t('status_error')}: {e}", error=True)

    def _breakpoint_module_id(self) -> str:
        return str(self._state.resolved_key or self._state.asset_key or "").strip()

    def _build_debug_session(self) -> DebugSession:
        module_id = self._breakpoint_module_id()
        store = BreakpointStore()
        raw = store.load_specs() if store.breakpoints_enabled() else {}
        breakpoints = {key: list(lines) for key, lines in raw.items()}
        session = DebugSession(breakpoints=breakpoints, pause_handler=self._handle_debug_pause)
        if module_id and module_id in breakpoints:
            session.update_breakpoints({module_id: breakpoints[module_id]})
        return session

    def _load_breakpoints(self) -> None:
        module_id = self._breakpoint_module_id()
        if not module_id:
            return
        store = BreakpointStore()
        self._edit.set_breakpoint_specs(store.specs_for(module_id))
        try:
            self._btn_bp_enable.setChecked(store.breakpoints_enabled())
        except Exception:
            pass

    def _save_breakpoints(self) -> None:
        module_id = self._breakpoint_module_id()
        if not module_id:
            return
        store = BreakpointStore()
        specs = []
        existing = {int(bp.line): bp for bp in store.specs_for(module_id)}
        for line in sorted(self._edit.breakpoint_lines()):
            specs.append(existing.get(int(line), BreakpointSpec(line=int(line))))
        store.set_specs(module_id, specs)

    def _on_breakpoint_toggled(self, line: int, enabled: bool) -> None:
        self._save_breakpoints()
        self._load_breakpoints()
        state = t("code_editor_breakpoint_on" if enabled else "code_editor_breakpoint_off")
        self.set_status(t("code_editor_breakpoint_status", state=state, line=int(line)))

    def _current_editor_line(self) -> int:
        return int(self._edit.textCursor().blockNumber() + 1)

    def _toggle_current_breakpoint(self) -> None:
        line = self._current_editor_line()
        lines = self._edit.breakpoint_lines()
        enabled = line not in lines
        if enabled:
            lines.add(line)
        else:
            lines.remove(line)
        self._edit.set_breakpoints(lines)
        self._on_breakpoint_toggled(line, enabled)

    def _open_current_breakpoint_params(self) -> None:
        module_id = self._breakpoint_module_id()
        if not module_id:
            return
        line = self._current_editor_line()
        store = BreakpointStore()
        specs = {int(bp.line): bp for bp in store.specs_for(module_id)}
        spec = specs.get(line, BreakpointSpec(line=line))
        dialog = QDialog(self)
        dialog.setWindowTitle(t("dbg_bp_params_title"))
        layout = QVBoxLayout(dialog)
        enabled = QCheckBox(t("dbg_bp_enabled"), dialog)
        enabled.setChecked(bool(spec.enabled))
        layout.addWidget(enabled)
        layout.addWidget(QLabel(t("dbg_bp_condition"), dialog))
        condition = QTextEdit(dialog)
        condition.setAcceptRichText(False)
        condition.setPlainText(str(spec.condition or ""))
        condition.setMinimumHeight(90)
        layout.addWidget(condition)
        form = QFormLayout()
        caller_name = QLineEdit(str(spec.caller_name or ""), dialog)
        form.addRow(t("dbg_bp_caller"), caller_name)
        hit_row = QWidget(dialog)
        hit_layout = QHBoxLayout(hit_row)
        hit_layout.setContentsMargins(0, 0, 0, 0)
        hit_operator = QComboBox(hit_row)
        hit_operator.addItems([">=", "=", ">"])
        current_operator = str(spec.hit_operator or ">=")
        hit_operator.setCurrentText(current_operator if current_operator in {">=", "=", ">"} else ">=")
        hit_target = QSpinBox(hit_row)
        hit_target.setRange(0, 1_000_000_000)
        hit_target.setValue(max(0, int(spec.hit_target or 0)))
        hit_layout.addWidget(hit_operator)
        hit_layout.addWidget(hit_target, 1)
        form.addRow(t("dbg_bp_hit_count"), hit_row)
        description = QLineEdit(str(spec.description or ""), dialog)
        form.addRow(t("dbg_bp_description"), description)
        action_expression = QLineEdit(str(spec.action_expression or ""), dialog)
        form.addRow(t("dbg_bp_action_expression"), action_expression)
        layout.addLayout(form)
        hits_row = QHBoxLayout()
        hits_label = QLabel(t("dbg_bp_current_hits", count=int(spec.hits or 0)), dialog)
        reset_hits = QPushButton(t("dbg_bp_reset_hits"), dialog)
        def _reset_hit_counter() -> None:
            spec.hits = 0
            hits_label.setText(t("dbg_bp_current_hits", count=0))

        reset_hits.clicked.connect(_reset_hit_counter)
        hits_row.addWidget(hits_label)
        hits_row.addStretch(1)
        hits_row.addWidget(reset_hits)
        layout.addLayout(hits_row)
        log_message = QCheckBox(t("dbg_bp_log_message"), dialog)
        log_message.setChecked(bool(spec.log_message))
        log_call_stack = QCheckBox(t("dbg_bp_log_call_stack"), dialog)
        log_call_stack.setChecked(bool(spec.log_call_stack))
        log_hit_count = QCheckBox(t("dbg_bp_log_hit_count"), dialog)
        log_hit_count.setChecked(bool(spec.log_hit_count))
        continue_execution = QCheckBox(t("dbg_bp_continue_execution"), dialog)
        continue_execution.setChecked(bool(spec.continue_execution))
        layout.addWidget(log_message)
        layout.addWidget(log_call_stack)
        layout.addWidget(log_hit_count)
        layout.addWidget(continue_execution)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        spec.enabled = bool(enabled.isChecked())
        spec.condition = condition.toPlainText().strip()
        spec.caller_name = caller_name.text().strip()
        spec.hit_operator = hit_operator.currentText().strip() if hit_target.value() > 0 else ""
        spec.hit_target = int(hit_target.value())
        spec.description = description.text().strip()
        spec.action_expression = action_expression.text().strip()
        spec.log_message = bool(log_message.isChecked())
        spec.log_call_stack = bool(log_call_stack.isChecked())
        spec.log_hit_count = bool(log_hit_count.isChecked())
        spec.continue_execution = bool(continue_execution.isChecked())
        specs[line] = spec
        store.set_specs(module_id, list(specs.values()))
        self._load_breakpoints()
        self.set_status(t("dbg_bp_params_saved", line=int(line)))

    def _toggle_breakpoints_enabled(self) -> None:
        store = BreakpointStore()
        enabled = not store.breakpoints_enabled()
        store.set_breakpoints_enabled(enabled)
        try:
            self._btn_bp_enable.setChecked(enabled)
        except Exception:
            pass
        self.set_status(t("dbg_bp_enabled_status" if enabled else "dbg_bp_disabled_status"))

    def _clear_all_breakpoints(self) -> None:
        if QMessageBox.question(self, t("dlg_confirm"), t("dbg_bp_clear_confirm")) != QMessageBox.StandardButton.Yes:
            return
        BreakpointStore().clear_all()
        self._load_breakpoints()
        self.set_status(t("dbg_bp_cleared"))

    def _move_current_breakpoint_up(self) -> None:
        self._move_current_breakpoint(-1)

    def _move_current_breakpoint_down(self) -> None:
        self._move_current_breakpoint(1)

    def _move_current_breakpoint(self, delta: int) -> None:
        module_id = self._breakpoint_module_id()
        if not module_id:
            return
        line = self._current_editor_line()
        store = BreakpointStore()
        specs = {int(bp.line): bp for bp in store.specs_for(module_id)}
        spec = specs.pop(line, None)
        if spec is None:
            self.set_status(t("dbg_bp_no_breakpoint"), error=True)
            return
        max_line = max(1, int(self._edit.blockCount()))
        new_line = max(1, min(max_line, int(line) + int(delta)))
        if new_line == int(line):
            specs[line] = spec
            self.set_status(t("dbg_bp_target_busy"), error=True)
            return
        if new_line in specs:
            self.set_status(t("dbg_bp_target_busy"), error=True)
            specs[line] = spec
            return
        spec.line = new_line
        specs[new_line] = spec
        store.set_specs(module_id, list(specs.values()))
        self._load_breakpoints()
        self._edit.reveal_line(new_line)
        self.set_status(t("dbg_bp_moved", line=int(new_line)))

    def _breakpoint_clipboard(self) -> BreakpointSpec | None:
        spec = getattr(self, "_copied_breakpoint_spec", None)
        if isinstance(spec, BreakpointSpec):
            return BreakpointSpec.from_raw(spec.to_raw())
        return None

    def _copy_current_breakpoint(self) -> None:
        module_id = self._breakpoint_module_id()
        if not module_id:
            return
        line = self._current_editor_line()
        specs = {int(bp.line): bp for bp in BreakpointStore().specs_for(module_id)}
        spec = specs.get(line)
        if spec is None:
            self.set_status(t("dbg_bp_no_breakpoint"), error=True)
            return
        self._copied_breakpoint_spec = BreakpointSpec.from_raw(spec.to_raw())
        self.set_status(t("dbg_bp_copied", line=int(line)))

    def _cut_current_breakpoint(self) -> None:
        module_id = self._breakpoint_module_id()
        if not module_id:
            return
        line = self._current_editor_line()
        store = BreakpointStore()
        specs = {int(bp.line): bp for bp in store.specs_for(module_id)}
        spec = specs.pop(line, None)
        if spec is None:
            self.set_status(t("dbg_bp_no_breakpoint"), error=True)
            return
        self._copied_breakpoint_spec = BreakpointSpec.from_raw(spec.to_raw())
        store.set_specs(module_id, list(specs.values()))
        self._load_breakpoints()
        self.set_status(t("dbg_bp_cut_status", line=int(line)))

    def _paste_breakpoint(self) -> None:
        module_id = self._breakpoint_module_id()
        if not module_id:
            return
        spec = self._breakpoint_clipboard()
        if spec is None:
            self.set_status(t("dbg_bp_clipboard_empty"), error=True)
            return
        line = self._current_editor_line()
        store = BreakpointStore()
        specs = {int(bp.line): bp for bp in store.specs_for(module_id)}
        if line in specs:
            self.set_status(t("dbg_bp_target_busy"), error=True)
            return
        spec.line = int(line)
        specs[int(line)] = spec
        store.set_specs(module_id, list(specs.values()))
        self._load_breakpoints()
        self.set_status(t("dbg_bp_pasted", line=int(line)))

    # ---- Load / Save ----

    def _apply_loaded_text(self, text: str, mime: str, resolved_key: str) -> None:
        """Commit a successful remote read without producing a local edit."""

        self._edit._syntax_assistant.invalidate()
        was_blocked = self._edit.blockSignals(True)
        try:
            self._edit.setPlainText(str(text or ""))
        finally:
            self._edit.blockSignals(was_blocked)
        self._state.mime = str(mime or "text/metascript")
        self._state.resolved_key = str(resolved_key or self._state.asset_key)
        self._state.is_dirty = False
        self._state.is_loaded = True
        self._state.last_load_error = ""
        self._update_title()
        self.dirtyChanged.emit(False)
        self._clear_debug_pause_banner()
        self._load_breakpoints()
        self._refresh_module_introspection()

    def reload(self) -> bool:
        ak = str(self._state.asset_key or "").strip()
        if not ak:
            was_blocked = self._edit.blockSignals(True)
            try:
                self._edit.setPlainText("")
            finally:
                self._edit.blockSignals(was_blocked)
            self._state.is_dirty = False
            self._state.is_loaded = False
            self._state.last_load_error = ""
            self._update_title()
            self.dirtyChanged.emit(False)
            self._clear_debug_pause_banner()
            self.set_status(t("status_no_asset"))
            return False
        try:
            text, mime, resolved = self._vm.get_text_asset(ak)
            self._apply_loaded_text(text, mime, resolved or ak)
            self.set_status(f"{t('status_loaded')}: {self._state.resolved_key}")
            return True
        except Exception as e:
            # A transport/runtime failure is not an edit. Keep the last known
            # buffer and dirty state so a stale service cannot erase user work.
            self._state.last_load_error = str(e)
            self.set_status(f"{t('status_error')}: {e}", error=True)
            return False

    def reload_from_vm(self) -> bool:
        return self.reload()

    def save(self) -> bool:
        ak = str(self._state.resolved_key or self._state.asset_key or "").strip()
        if not ak:
            self.set_status(t("status_no_asset"), error=True)
            return False
        try:
            data = self._edit.toPlainText()
            mime = self._state.mime or "text/metascript"
            self._vm.save_text_asset(ak, data, mime=mime)
            persisted_text, mime2, resolved = self._vm.get_text_asset(ak)
            self._apply_loaded_text(
                persisted_text,
                mime2 or mime,
                resolved or self._state.resolved_key or ak,
            )
            self.set_status(f"{t('status_saved')}: {self._state.resolved_key}")
            self.saved.emit(str(self._state.resolved_key or ak))
            return True
        except Exception as e:
            self.set_status(f"{t('status_error')}: {e}", error=True)
            return False

    def insert_posting_handler(self, code: str) -> bool:
        """Append a posting handler as one undoable edit, never reload or save."""
        from src.configurator.domain.posting_constructor import find_posting_handler, validate_posting_handler

        if not self._state.is_loaded or self._state.last_load_error:
            self.set_status(t("posting_module_not_loaded"), error=True)
            return False
        if self._edit.isReadOnly():
            self.set_status(t("posting_module_read_only"), error=True)
            return False
        source = self._edit.toPlainText()
        try:
            line = find_posting_handler(source)
            if line:
                self.navigate_to_line(line)
                self.set_status(t("posting_handler_exists", line=line), error=True)
                return False
            validate_posting_handler(code)
        except ValueError as exc:
            self.set_status(t("posting_handler_unsafe", error=str(exc)), error=True)
            return False

        separator = "" if not source or source.endswith("\n\n") else ("\n" if source.endswith("\n") else "\n\n")
        inserted_line = (source + separator).count("\n") + 1
        cursor = self._edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.beginEditBlock()
        try:
            cursor.insertText(separator + code)
        finally:
            cursor.endEditBlock()
        self._edit.setTextCursor(cursor)
        self.navigate_to_line(inserted_line)
        self.set_status(t("posting_handler_inserted"))
        return True

    def is_dirty(self) -> bool:
        return bool(self._state.is_dirty)

    def confirm_close(self) -> bool:
        if not self._state.is_dirty:
            return True
        reply = QMessageBox.question(
            self,
            t("dlg_unsaved_title"),
            t("dlg_unsaved_text"),
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Save:
            return bool(self.save())
        if reply == QMessageBox.StandardButton.Discard:
            self._state.is_dirty = False
            self._update_title()
            self.dirtyChanged.emit(False)
            return True
        return False

    def closeEvent(self, event) -> None:
        if not self.confirm_close():
            event.ignore()
            return
        super().closeEvent(event)
