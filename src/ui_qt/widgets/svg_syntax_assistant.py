from __future__ import annotations

import re
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.ui_qt.i18n import t


@dataclass(frozen=True)
class _Snippet:
    title_key: str
    text: str


def _pick_palette_icon(style: QStyle) -> QIcon:
    """Pick a reasonable 'palette' icon that exists across platforms."""
    ico = QIcon()

    # Theme icons first.
    for name in ("color-picker", "palette", "preferences-desktop-theme", "applications-graphics"):
        themed = QIcon.fromTheme(name)
        if not themed.isNull():
            return themed

    # Qt standard pixmaps fallback (guarded for Qt builds that miss some enums).
    for sp_name in (
        "SP_DialogOpenButton",
        "SP_DialogApplyButton",
        "SP_FileDialogDetailedView",
        "SP_FileDialogContentsView",
        "SP_DesktopIcon",
    ):
        sp = getattr(QStyle, sp_name, None)
        if sp is None:
            continue
        try:
            ico = style.standardIcon(sp)
            if not ico.isNull():
                return ico
        except Exception:
            continue

    return QIcon()


def _pick_remove_icon(style: QStyle) -> QIcon:
    """Pick a small 'remove/clear' icon."""
    for name in ("edit-clear", "edit-delete", "window-close"):
        themed = QIcon.fromTheme(name)
        if not themed.isNull():
            return themed

    for sp_name in ("SP_DialogCancelButton", "SP_TrashIcon", "SP_DockWidgetCloseButton"):
        sp = getattr(QStyle, sp_name, None)
        if sp is None:
            continue
        try:
            ico = style.standardIcon(sp)
            if not ico.isNull():
                return ico
        except Exception:
            continue

    return QIcon()


class _AttrRow(QWidget):
    """A line edit + (optional) picker button + remove button.

    Removal is explicit: user clicks the 'x' button. Empty input means 'do not change'.
    """

    def __init__(
        self,
        *,
        kind: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._kind = kind
        self._remove_requested = False

        self._edit = QLineEdit(self)
        self._btn_pick: QToolButton | None = None

        style = QApplication.instance().style() if QApplication.instance() else self.style()

        if kind == "color":
            self._btn_pick = QToolButton(self)
            self._btn_pick.setIcon(_pick_palette_icon(style))
            self._btn_pick.setToolTip(t("svg_color_pick"))

        self._btn_remove = QToolButton(self)
        self._btn_remove.setIcon(_pick_remove_icon(style))
        self._btn_remove.setToolTip(t("svg_attr_remove"))
        self._btn_remove.clicked.connect(self.request_remove)

        # If user starts typing after marking "remove", treat that as an explicit value.
        self._edit.textEdited.connect(self._on_text_edited)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self._edit, 1)
        if self._btn_pick is not None:
            lay.addWidget(self._btn_pick, 0)
        lay.addWidget(self._btn_remove, 0)
        self.setLayout(lay)

    def lineEdit(self) -> QLineEdit:
        return self._edit

    def text(self) -> str:
        return self._edit.text()

    def setText(self, v: str) -> None:  # noqa: N802 (Qt API)
        # Programmatic value fill should cancel any pending-remove state.
        self.clear_remove_pending()
        self._edit.setText(v or "")

    def _on_text_edited(self, _text: str) -> None:
        if self._edit.property("removePending"):
            self.clear_remove_pending()

    def hasFocusDeep(self) -> bool:
        return self._edit.hasFocus()

    def bind_color_picker(self, on_pick) -> None:
        if self._btn_pick is not None:
            self._btn_pick.clicked.connect(on_pick)

    def request_remove(self) -> None:
        self._remove_requested = True
        # Visual hint: clear and set placeholder.
        self._edit.setText("")
        self._edit.setPlaceholderText(t("svg_attr_will_remove"))
        # Strong visual cue: red border while removal is pending.
        self._edit.setProperty("removePending", True)
        self._edit.setStyleSheet('QLineEdit[removePending="true"] { border: 1px solid #d9534f; }')

    def consume_remove_requested(self) -> bool:
        v = self._remove_requested
        self._remove_requested = False
        # Restore placeholder to default (empty).
        self._edit.setPlaceholderText("")
        # Clear visual cue.
        self._edit.setProperty("removePending", False)
        self._edit.setStyleSheet("")
        return v

    def clear_remove_pending(self) -> None:
        """Clear the pending-remove state when user inputs an explicit value."""
        self._remove_requested = False
        self._edit.setProperty("removePending", False)
        self._edit.setStyleSheet("")
        self._edit.setPlaceholderText("")


class SvgSyntaxAssistant(QWidget):
    """Lightweight helper for editing SVG: snippets + common attribute editor."""

    def __init__(self, *, target_editor, vm, parent: QWidget | None = None):
        super().__init__(parent)
        self._editor = target_editor
        self._vm = vm

        self._tabs = QTabWidget(self)

        # -------- Snippets --------
        snip_page = QWidget(self)
        snip_lay = QVBoxLayout(snip_page)

        self._snip_search = QLineEdit(self)
        self._snip_search.setPlaceholderText(t("svg_assistant_search"))
        self._snip_list = QListWidget(self)
        self._snip_list.setAlternatingRowColors(True)

        snip_lay.addWidget(self._snip_search)
        snip_lay.addWidget(self._snip_list, 1)
        snip_page.setLayout(snip_lay)

        # -------- Attributes --------
        attr_page = QWidget(self)
        attr_lay = QVBoxLayout(attr_page)

        self._el_label = QLabel(t("svg_assistant_no_element"), self)
        self._el_label.setWordWrap(True)
        self._el_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        box = QGroupBox(t("svg_assistant_attr_box"), self)
        form = QFormLayout(box)

        self._a_fill = _AttrRow(kind="color", parent=self)
        self._a_stroke = _AttrRow(kind="color", parent=self)
        self._a_stroke_w = _AttrRow(kind="text", parent=self)
        self._a_opacity = _AttrRow(kind="text", parent=self)
        self._a_transform = _AttrRow(kind="text", parent=self)

        self._a_fill.bind_color_picker(lambda: self._pick_color_into(self._a_fill))
        self._a_stroke.bind_color_picker(lambda: self._pick_color_into(self._a_stroke))

        form.addRow(t("svg_attr_fill"), self._a_fill)
        form.addRow(t("svg_attr_stroke"), self._a_stroke)
        form.addRow(t("svg_attr_stroke_width"), self._a_stroke_w)
        form.addRow(t("svg_attr_opacity"), self._a_opacity)
        form.addRow(t("svg_attr_transform"), self._a_transform)
        box.setLayout(form)

        self._btn_apply = QPushButton(t("svg_assistant_apply"), self)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self._btn_apply)
        btn_row.addStretch(1)

        attr_lay.addWidget(self._el_label)
        attr_lay.addWidget(box)
        attr_lay.addLayout(btn_row)
        attr_lay.addStretch(1)
        attr_page.setLayout(attr_lay)

        self._tabs.addTab(snip_page, t("svg_assistant_tab_snippets"))
        self._tabs.addTab(attr_page, t("svg_assistant_tab_attributes"))

        root = QVBoxLayout(self)
        root.addWidget(self._tabs, 1)
        self.setLayout(root)
        self.setMinimumWidth(260)

        # data
        self._snippets: list[_Snippet] = [
            _Snippet("svg_snip_svg_root", '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">\n  \n</svg>'),
            _Snippet("svg_snip_group", "<g>\n  \n</g>"),
            _Snippet("svg_snip_path", '<path d="" fill="currentColor"/>'),
            _Snippet("svg_snip_rect", '<rect x="0" y="0" width="64" height="64" rx="8"/>'),
            _Snippet("svg_snip_circle", '<circle cx="32" cy="32" r="16"/>'),
            _Snippet(
                "svg_snip_linear_gradient",
                "<defs>\n  <linearGradient id=\"grad1\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"1\">\n    <stop offset=\"0\" stop-color=\"#00D4FF\"/>\n    <stop offset=\"1\" stop-color=\"#4F46E5\"/>\n  </linearGradient>\n</defs>",
            ),
            _Snippet(
                "svg_snip_radial_gradient",
                "<defs>\n  <radialGradient id=\"grad2\" cx=\"0.5\" cy=\"0.5\" r=\"0.5\">\n    <stop offset=\"0\" stop-color=\"#FFFFFF\" stop-opacity=\"0.8\"/>\n    <stop offset=\"1\" stop-color=\"#000000\" stop-opacity=\"0\"/>\n  </radialGradient>\n</defs>",
            ),
        ]
        self._rebuild_snip_list()

        # signals
        self._snip_search.textChanged.connect(lambda *_: self._rebuild_snip_list())
        self._snip_list.itemDoubleClicked.connect(self._insert_selected_snippet)
        self._btn_apply.clicked.connect(self._apply_attrs)
        self._editor.cursorPositionChanged.connect(self._sync_attr_fields)
        self._editor.textChanged.connect(lambda: self._sync_attr_fields(soft=True))

        self._sync_attr_fields(soft=True)

    # ---------------- snippets ----------------
    def _rebuild_snip_list(self) -> None:
        q = (self._snip_search.text() or "").strip().lower()
        self._snip_list.clear()
        for s in self._snippets:
            title = t(s.title_key)
            if q and q not in title.lower() and q not in s.text.lower():
                continue
            it = QListWidgetItem(title)
            it.setData(Qt.ItemDataRole.UserRole, s)
            self._snip_list.addItem(it)
        if self._snip_list.count() and not self._snip_list.selectedItems():
            self._snip_list.setCurrentRow(0)

    def _insert_selected_snippet(self) -> None:
        it = self._snip_list.currentItem()
        if not it:
            return
        s: _Snippet | None = it.data(Qt.ItemDataRole.UserRole)
        if not isinstance(s, _Snippet):
            return
        cur = self._editor.textCursor()
        cur.insertText(s.text)
        self._editor.setTextCursor(cur)

    # ---------------- colors ----------------
    def _pick_color_into(self, row: _AttrRow) -> None:
        cur = (row.text() or "").strip()
        start = QColor(cur) if cur else QColor("#000000")
        col = QColorDialog.getColor(start, self, t("svg_select_color_title"))
        if not col.isValid():
            return
        row.setText(col.name(QColor.HexRgb))

    # ---------------- attributes ----------------
    def _attr_fields_have_focus(self) -> bool:
        return any(
            w.hasFocusDeep() for w in (self._a_fill, self._a_stroke, self._a_stroke_w, self._a_opacity, self._a_transform)
        )

    def _clear_attr_fields(self) -> None:
        for w in (self._a_fill, self._a_stroke, self._a_stroke_w, self._a_opacity, self._a_transform):
            w.setText("")

    def _sync_attr_fields(self, soft: bool = False) -> None:
        """Load current element attributes into the form (best-effort)."""
        if soft and self._attr_fields_have_focus():
            return

        info = self._find_target_tag_for_attrs()
        if info is None:
            self._el_label.setText(t("svg_assistant_no_element"))
            if not soft:
                self._clear_attr_fields()
            return

        tag_name, tag_text, *_ = info
        self._el_label.setText(f"{t('svg_assistant_element')}: <{tag_name}>")

        def _get(attr: str, from_text: str) -> str:
            m = re.search(rf"\b{re.escape(attr)}\s*=\s*(['\"])(.*?)\1", from_text)
            return (m.group(2) if m else "").strip()

        root_tag = self._find_svg_root_open_tag()

        fill = _get("fill", tag_text) or _get("fill", root_tag)
        stroke = _get("stroke", tag_text) or _get("stroke", root_tag)
        stroke_w = _get("stroke-width", tag_text) or _get("stroke-width", root_tag)
        opacity = _get("opacity", tag_text) or _get("opacity", root_tag)
        transform = _get("transform", tag_text)

        self._a_fill.setText(fill)
        self._a_stroke.setText(stroke)
        self._a_stroke_w.setText(stroke_w)
        self._a_opacity.setText(opacity)
        self._a_transform.setText(transform)

    def _apply_attrs(self) -> None:
        info = self._find_target_tag_for_attrs()
        if info is None:
            return
        _tag_name, tag_text, start, end = info

        removals = {
            "fill": self._a_fill.consume_remove_requested(),
            "stroke": self._a_stroke.consume_remove_requested(),
            "stroke-width": self._a_stroke_w.consume_remove_requested(),
            "opacity": self._a_opacity.consume_remove_requested(),
            "transform": self._a_transform.consume_remove_requested(),
        }

        def _set_attr(src: str, name: str, value: str, remove: bool) -> str:
            value = (value or "").strip()

            # explicit remove overrides everything
            if remove:
                return re.sub(rf"\s+{re.escape(name)}\s*=\s*(['\"]).*?\1", "", src)

            # empty => do not change
            if not value:
                return src

            if re.search(rf"\b{re.escape(name)}\s*=", src):
                return re.sub(
                    rf"({re.escape(name)}\s*=\s*)(['\"]).*?\2",
                    lambda m: f"{m.group(1)}\"{value}\"",
                    src,
                )

            # insert before end of tag
            if src.endswith("/>"):
                return src[:-2] + f" {name}=\"{value}\"/>"
            if src.endswith(">"):
                return src[:-1] + f" {name}=\"{value}\">"
            return src + f" {name}=\"{value}\""

        new_tag = tag_text
        new_tag = _set_attr(new_tag, "fill", self._a_fill.text(), removals["fill"])
        new_tag = _set_attr(new_tag, "stroke", self._a_stroke.text(), removals["stroke"])
        new_tag = _set_attr(new_tag, "stroke-width", self._a_stroke_w.text(), removals["stroke-width"])
        new_tag = _set_attr(new_tag, "opacity", self._a_opacity.text(), removals["opacity"])
        new_tag = _set_attr(new_tag, "transform", self._a_transform.text(), removals["transform"])

        if new_tag == tag_text:
            return

        # Apply via QTextCursor to keep undo/redo.
        doc = self._editor.document()
        cur = QTextCursor(doc)
        cur.setPosition(start)
        cur.setPosition(end, QTextCursor.KeepAnchor)
        cur.insertText(new_tag)

        # place caret near updated tag
        cur2 = self._editor.textCursor()
        cur2.setPosition(min(start + len(new_tag), doc.characterCount() - 1))
        self._editor.setTextCursor(cur2)

        # sync UI after apply
        self._sync_attr_fields(soft=True)

    def _find_target_tag_for_attrs(self) -> tuple[str, str, int, int] | None:
        """Prefer tag under cursor; otherwise fallback to root <svg ...>."""
        info = self._find_tag_under_cursor()
        if info is not None and not info[1].lstrip().startswith("</"):
            return info

        # fallback: root svg
        text = self._editor.toPlainText()
        m = re.search(r"<\s*svg\b[^>]*>", text, flags=re.IGNORECASE)
        if not m:
            return None
        tag_text = m.group(0)
        return ("svg", tag_text, m.start(), m.end())

    def _find_tag_under_cursor(self) -> tuple[str, str, int, int] | None:
        """Return (tag_name, full_tag_text, start_index, end_index) best-effort."""
        text = self._editor.toPlainText()
        pos = self._editor.textCursor().position()
        if pos < 0 or pos > len(text):
            return None

        lt = text.rfind("<", 0, pos)
        if lt < 0:
            return None
        gt = text.find(">", lt)
        if gt < 0:
            return None

        if not (lt <= pos <= gt + 1):
            lt2 = text.rfind("<", 0, lt)
            if lt2 < 0:
                return None
            gt2 = text.find(">", lt2)
            if gt2 < 0:
                return None
            lt, gt = lt2, gt2

        tag_text = text[lt : gt + 1]
        if tag_text.startswith("<!--") or tag_text.startswith("<?"):
            return None
        if tag_text.lstrip().startswith("</"):
            return None

        m = re.match(r"<\s*([A-Za-z_][\w:.-]*)\b", tag_text)
        if not m:
            return None
        tag_name = m.group(1)
        return (tag_name, tag_text, lt, gt + 1)

    def _find_svg_root_open_tag(self) -> str:
        text = self._editor.toPlainText()
        m = re.search(r"<\s*svg\b[^>]*>", text, flags=re.IGNORECASE)
        return m.group(0) if m else ""
