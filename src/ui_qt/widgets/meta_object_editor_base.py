from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QDialog, QLabel, QPushButton, QHBoxLayout, QSizePolicy, QTabWidget

from src.ui_qt.i18n import t
from src.configurator.domain.technical_names import technical_object_name
from src.ui_qt.viewmodels.configurator_vm import ConfiguratorViewModel

from .generate_dialog import GenerateDialog
from .meta_object_shell import MetaObjectEditorShell


class PayloadModelWithSubsystems(Protocol):
    """Typed payload view that provides subsystems selection."""

    subsystems: list[str]


@dataclass(frozen=True, slots=True)
class EditorContext:
    """Context for meta-object editors."""

    obj_type: str
    obj_guid: str
    title: str
    payload: dict


class MetaObjectEditorBase(QWidget):
    """Base class for metadata object editors.

    Goals:
        - Keep a single universal shell (MetaObjectEditorShell).
        - Centralize Generate workflow and post-generate reload.
        - Provide a thin set of hooks for concrete object editors.

    Concrete editors MUST implement:
        - _rebuild_model_from_payload
        - _load_to_ui
        - _build_sections
    """

    applyRequested = Signal(dict)
    closeRequested = Signal()

    def __init__(
        self,
        *,
        title: str,
        payload: dict | None = None,
        vm: ConfiguratorViewModel | None = None,
        obj_guid: str = "",
        obj_type: str = "",
        available_subsystems: list[dict] | None = None,
    ) -> None:
        super().__init__()

        self._vm = vm
        self._obj_guid = str(obj_guid or "").strip()
        self._obj_type = str(obj_type or "").strip().lower()
        self._available_subsystems = list(available_subsystems or [])

        self._payload_raw: dict = payload if isinstance(payload, dict) else {}

        self._shell = MetaObjectEditorShell(title=title)
        self._shell.applyRequested.connect(self._on_apply_requested)
        self._shell.closeRequested.connect(self.closeRequested.emit)
        self._shell.generateRequested.connect(self._on_generate_clicked)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._shell, 1)

        # Concrete editors will parse payload into their own typed model.
        self._rebuild_model_from_payload(self._payload_raw)

        self._build_sections()
        self._load_to_ui()

    def set_current_section(self, key: str) -> None:
        self._shell.set_current_section(key)

    # ---------------- hooks ----------------

    def _rebuild_model_from_payload(self, payload: dict) -> None:
        """Rebuild a strongly-typed payload view from raw payload."""

        raise NotImplementedError

    def _load_to_ui(self) -> None:
        """Load current model into UI widgets."""

        raise NotImplementedError

    def _build_sections(self) -> None:
        """Build sections list/pages inside the universal shell."""

        raise NotImplementedError

    # ---------------- modules page (shared) ----------------

    def _build_modules_page(self) -> "QWidget":
        """Module stubs list with Open button — shared by Catalog, Document, etc."""
        from PySide6.QtWidgets import QListWidget, QListWidgetItem, QHBoxLayout as _HBL
        from PySide6.QtCore import Qt as _Qt
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        hint = QLabel(t("obj.modules_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("metaHint")
        layout.addWidget(hint)

        bar = _HBL()
        self._btn_module_open = QPushButton(t("obj.modules_open"))
        self._btn_module_open.setEnabled(False)
        bar.addWidget(self._btn_module_open)
        bar.addStretch(1)
        layout.addLayout(bar)

        self._lst_modules = QListWidget()
        self._lst_modules.setObjectName("metaModulesList")
        layout.addWidget(self._lst_modules, 1)

        self._btn_module_open.clicked.connect(self._on_open_selected_module)
        self._lst_modules.itemDoubleClicked.connect(lambda _: self._on_open_selected_module())
        self._lst_modules.currentItemChanged.connect(
            lambda cur, _: self._btn_module_open.setEnabled(cur is not None)
        )

        setattr(w, "_on_section_shown", self._refresh_modules_list)
        return w

    def _refresh_modules_list(self) -> None:
        if not hasattr(self, "_lst_modules"):
            return
        from PySide6.QtWidgets import QListWidgetItem
        from PySide6.QtCore import Qt as _Qt
        self._lst_modules.clear()
        vm  = getattr(self, "_vm", None)
        obj_guid = getattr(self, "_obj_guid", "")
        if vm is None or not obj_guid:
            return
        try:
            all_objs = vm.list_objects() or []
            modules_folder = next(
                (o for o in all_objs
                 if str(getattr(o, "kind", "")) == "folder"
                 and str(getattr(o, "parent_guid", "")) == obj_guid
                 and str(getattr(o, "name", "")).lower() == "modules"),
                None,
            )
            if modules_folder is None:
                return
            mf_guid = str(getattr(modules_folder, "guid", ""))
            module_nodes = [
                o for o in all_objs
                if str(getattr(o, "parent_guid", "")) == mf_guid
                and str(getattr(o, "type", "")).lower() == "module"
            ]
            for m in module_nodes:
                title = technical_object_name(getattr(m, "name", ""), payload=getattr(m, "payload", None))
                guid  = str(getattr(m, "guid", ""))
                it = QListWidgetItem(title)
                it.setData(_Qt.ItemDataRole.UserRole, guid)
                it.setData(_Qt.ItemDataRole.UserRole + 1, title)
                self._lst_modules.addItem(it)
        except Exception:
            pass

    def _on_open_selected_module(self) -> None:
        from PySide6.QtCore import Qt as _Qt
        if not hasattr(self, "_lst_modules"):
            return
        it = self._lst_modules.currentItem()
        if it is None:
            return
        guid  = str(it.data(_Qt.ItemDataRole.UserRole) or "")
        title = str(it.data(_Qt.ItemDataRole.UserRole + 1) or it.text())
        if not guid:
            return
        parent = self.parent()
        depth  = 0
        while parent is not None and depth < 20:
            if hasattr(parent, "_open_module_by_guid"):
                parent._open_module_by_guid(guid, title)
                return
            parent = parent.parent()
            depth += 1
        vm = getattr(self, "_vm", None)
        if vm is not None and hasattr(vm, "openEditorRequested"):
            from src.configurator.ui.widgets import NodeInfo
            info = NodeInfo(kind="object", name=title, guid=guid, obj_type="module")
            vm.openEditorRequested.emit(info)

    # ---------------- common generate workflow ----------------

    def _on_generate_clicked(self) -> None:
        if self._vm is None or not self._obj_guid or not self._obj_type:
            return

        dlg = GenerateDialog(
            self,
            preview_provider=lambda o: self._vm.generate_preview_for_object(
                self._obj_guid,
                self._obj_type,
                generate_schema=o.schema,
                generate_forms=o.forms,
                generate_commands=o.commands,
                overwrite=o.overwrite,
            ),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        opts = dlg.options()
        self._vm.generate_for_object(
            self._obj_guid,
            self._obj_type,
            generate_schema=opts.schema,
            generate_forms=opts.forms,
            generate_commands=opts.commands,
            overwrite=opts.overwrite,
        )

        # Reload to reflect generated content immediately.
        self._reload_from_vm()

    def _on_apply_requested(self, patch: dict) -> None:
        self._apply_patch(dict(patch or {}))

    def _apply_patch(self, patch: dict) -> bool:
        patch = dict(patch or {})
        if not patch:
            self.applyRequested.emit({})
            if self._vm is not None and self._obj_guid:
                QTimer.singleShot(0, self._reload_from_vm)
            return True
        if self._vm is not None and self._obj_guid:
            save = getattr(self._vm, "save_object_payload_patch", None)
            if not callable(save) or not bool(save(self._obj_guid, patch, reload=False)):
                return False
            self._shell.clear_pending_patch()
            QTimer.singleShot(0, self._reload_from_vm)
            return True
        self.applyRequested.emit(patch)
        self._shell.clear_pending_patch()
        return True

    def save(self) -> bool:
        """Persist pending profile-editor fields through Runtime RPC."""

        return self._apply_patch(self._shell.pending_patch())

    def _reload_from_vm(self) -> None:
        if self._vm is None or not self._obj_guid:
            return
        meta = self._vm.get_meta_by_guid(self._obj_guid)
        if not isinstance(meta, dict):
            return

        title = technical_object_name(meta.get("name"), payload=meta.get("payload"))
        payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}

        self._payload_raw = dict(payload)
        self._payload_raw["name"] = title
        if title:
            self._shell.set_title(title)

        self._rebuild_model_from_payload(self._payload_raw)
        self._load_to_ui()
        clear_pending_patch = getattr(self._shell, "clear_pending_patch", None)
        if callable(clear_pending_patch):
            try:
                clear_pending_patch()
            except Exception:
                pass

    def reload_from_vm(self) -> None:
        self._reload_from_vm()
