from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from src.ui_qt.i18n import t
from src.ui_qt.widgets.svg_preview import SvgPreview
from src.ui_qt.widgets.svg_syntax_assistant import SvgSyntaxAssistant


@dataclass
class SvgEditorState:
    asset_key: str
    title: str
    mime: str = "image/svg+xml"


class SvgEditorWidget(QWidget):
    """A simple SVG editor based on QPlainTextEdit + QSvgRenderer preview.

    This is intentionally lightweight (no Qt WebEngine).
    """

    def __init__(self, *, vm, asset_key: str, title: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._vm = vm
        self._state = SvgEditorState(asset_key=asset_key, title=title or asset_key)

        self._dirty = False
        self._reload_guard = False

        self._toolbar = QToolBar(self)
        self._toolbar.setIconSize(self._toolbar.iconSize())
        self._toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)

        self._act_save = QAction(t("svg_save"), self)
        self._act_reload = QAction(t("svg_reload"), self)
        self._act_validate = QAction(t("svg_validate"), self)
        self._act_pretty = QAction(t("svg_pretty"), self)
        self._act_minify = QAction(t("svg_minify"), self)

        # Shortcuts (1C-like: fast access, minimal chrome)
        self._act_save.setShortcut("Ctrl+S")
        self._act_reload.setShortcut("Ctrl+R")
        self._act_validate.setShortcut("Ctrl+E")
        self._act_pretty.setShortcut("Ctrl+Alt+F")
        self._act_minify.setShortcut("Ctrl+Alt+M")

        for a in (self._act_save, self._act_reload, self._act_validate):
            self._toolbar.addAction(a)
        self._toolbar.addSeparator()
        for a in (self._act_pretty, self._act_minify):
            self._toolbar.addAction(a)

        self._info = QLabel("", self)
        self._info.setWordWrap(True)
        self._info.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self._editor = QPlainTextEdit(self)
        self._editor.setTabStopDistance(4 * self._editor.fontMetrics().horizontalAdvance(' '))
        self._assistant = SvgSyntaxAssistant(target_editor=self._editor, vm=self._vm, parent=self)
        self._preview = SvgPreview(self)

        split = QSplitter(Qt.Orientation.Horizontal, self)
        split.addWidget(self._assistant)
        split.addWidget(self._editor)
        split.addWidget(self._preview)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        split.setStretchFactor(2, 2)

        lay = QVBoxLayout(self)
        lay.addWidget(self._toolbar)
        lay.addWidget(self._info)
        lay.addWidget(split, 1)
        self.setLayout(lay)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(250)

        # signals
        self._act_save.triggered.connect(self.save)
        self._act_reload.triggered.connect(self.reload)
        self._act_validate.triggered.connect(self.validate)
        self._act_pretty.triggered.connect(self.pretty)
        self._act_minify.triggered.connect(self.minify)
        self._editor.textChanged.connect(self._on_text_changed)
        self._refresh_timer.timeout.connect(self._render_preview)

        self.reload()

    def title(self) -> str:
        return self._state.title

    def validate(self) -> None:
        """Validate current SVG text."""
        try:
            txt = self._editor.toPlainText().encode("utf-8", errors="replace")
            r = QSvgRenderer(txt)
            if r.isValid():
                self._info.setText(t("svg_status_ready"))
            else:
                self._info.setText(t("svg_status_invalid"))
        except Exception as e:
            self._info.setText(f"{t('svg_status_invalid')}: {e}")

    # ---------------- loading / saving ----------------
    def reload(self) -> None:
        try:
            data, mime = self._vm.get_picture_asset(self._state.asset_key)
            self._state.mime = mime or "image/svg+xml"
        except Exception as e:
            self._vm.show_warning(t("pictures_title"), f"{t('svg_load_failed')}: {e}")
            data = b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'/>"

        text = self._decode_svg(data)
        self._reload_guard = True
        try:
            self._editor.setPlainText(text)
            self._dirty = False
        finally:
            self._reload_guard = False
        self._render_preview()
        self._update_info()

    def reload_from_vm(self) -> None:
        self.reload()

    def save(self) -> None:
        text = self._editor.toPlainText()
        ok, err = self._validate_svg_text(text)
        if not ok:
            self._vm.show_warning(t("pictures_title"), err)
            return

        data = text.encode("utf-8")
        try:
            self._vm.save_picture_asset(self._state.asset_key, data, "image/svg+xml")
            self._dirty = False
            self._update_info(saved=True)
            self.reload_from_vm()
        except Exception as e:
            self._vm.show_warning(t("pictures_title"), f"{t('svg_save_failed')}: {e}")

    # ---------------- transforms ----------------
    def pretty(self) -> None:
        text = self._editor.toPlainText()
        try:
            import xml.dom.minidom as minidom
            dom = minidom.parseString(text.encode("utf-8"))
            pretty = dom.toprettyxml(indent="  ")
            # minidom adds a xml decl and lots of blank lines; keep it clean
            pretty = "\n".join([ln for ln in pretty.splitlines() if ln.strip()])
            self._editor.setPlainText(pretty)
        except Exception as e:
            self._vm.show_warning(t("pictures_title"), f"{t('svg_format_failed')}: {e}")

    def minify(self) -> None:
        text = self._editor.toPlainText()
        # Remove xml decl, comments, excessive whitespace between tags
        text = re.sub(r"^\s*<\?xml[^>]*\?>\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
        text = re.sub(r">\s+<", "><", text)
        text = re.sub(r"\s{2,}", " ", text)
        self._editor.setPlainText(text.strip())

    def normalize_viewbox(self) -> None:
        text = self._editor.toPlainText()
        ok, err = self._validate_svg_text(text)
        if not ok:
            self._vm.show_warning(t("pictures_title"), err)
            return
        try:
            root = ET.fromstring(text)
            if self._strip_ns(root.tag) != "svg":
                raise ValueError("Root element is not <svg>")

            vb = root.get("viewBox")
            if not vb:
                w = self._num(root.get("width"))
                h = self._num(root.get("height"))
                if w and h:
                    root.set("viewBox", f"0 0 {w:g} {h:g}")
                    # remove width/height for scalability
                    root.attrib.pop("width", None)
                    root.attrib.pop("height", None)

            self._editor.setPlainText(self._et_to_text(root))
        except Exception as e:
            self._vm.show_warning(t("pictures_title"), f"{t('svg_normalize_failed')}: {e}")

    def clear_paints(self) -> None:
        text = self._editor.toPlainText()
        ok, err = self._validate_svg_text(text)
        if not ok:
            self._vm.show_warning(t("pictures_title"), err)
            return
        try:
            root = ET.fromstring(text)
            for el in root.iter():
                for attr in ("fill", "stroke"):
                    v = el.get(attr)
                    if not v:
                        continue
                    v = v.strip()
                    # keep gradients/patterns
                    if v.startswith("url(") or v == "none":
                        continue
                    el.attrib.pop(attr, None)
            self._editor.setPlainText(self._et_to_text(root))
        except Exception as e:
            self._vm.show_warning(t("pictures_title"), f"{t('svg_clear_paints_failed')}: {e}")

    # ---------------- internals ----------------
    def _on_text_changed(self) -> None:
        if self._reload_guard:
            return
        self._dirty = True
        self._refresh_timer.start()
        self._update_info()

    def _render_preview(self) -> None:
        data = self._editor.toPlainText().encode("utf-8", errors="ignore")
        self._preview.set_svg_bytes(data)

    def _update_info(self, saved: bool = False) -> None:
        status = t("svg_status_saved") if saved else (t("svg_status_dirty") if self._dirty else t("svg_status_clean"))
        self._info.setText(f"{self._state.asset_key} — {status}")

    @staticmethod
    def _decode_svg(data: bytes) -> str:
        for enc in ("utf-8", "utf-8-sig", "utf-16", "cp1251"):
            try:
                return data.decode(enc)
            except Exception:
                continue
        return data.decode("utf-8", errors="replace")

    @staticmethod
    def _validate_svg_text(text: str) -> tuple[bool, str]:
        text = (text or "").strip()
        if not text:
            return False, t("svg_empty")
        try:
            root = ET.fromstring(text)
        except Exception as e:
            return False, f"{t('svg_parse_error')}: {e}"
        if SvgEditorWidget._strip_ns(root.tag) != "svg":
            return False, t("svg_root_error")
        return True, ""

    @staticmethod
    def _strip_ns(tag: str) -> str:
        if "}" in tag:
            return tag.split("}", 1)[1]
        return tag

    @staticmethod
    def _num(v: str | None) -> float | None:
        if not v:
            return None
        v = v.strip()
        v = re.sub(r"px$", "", v, flags=re.IGNORECASE)
        try:
            return float(v)
        except Exception:
            return None

    @staticmethod
    def _et_to_text(root: ET.Element) -> str:
        # Keep xmlns if missing
        if "xmlns" not in root.attrib:
            root.set("xmlns", "http://www.w3.org/2000/svg")
        return ET.tostring(root, encoding="unicode")
