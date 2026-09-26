from __future__ import annotations

from pathlib import Path
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QStandardItem
from PySide6.QtWidgets import QFileDialog, QMdiSubWindow, QWidget

from src.configurator.persistence.object_locks import make_lock_key
from src.configurator.domain.technical_names import technical_object_name
from src.configurator.ui.widgets import NodeInfo, ObjectStructureWidget
from src.ui_qt.i18n import t
from src.ui_qt.widgets.catalog_editor import CatalogEditorWidget
from src.ui_qt.widgets.access_restrictions_widget import AccessRestrictionsProjectionWidget
from src.ui_qt.widgets.code_editor_widget import CodeEditorWidget
from src.ui_qt.widgets.constant_properties import ConstantPropertiesWidget
from src.ui_qt.widgets.document_editor import DocumentEditorWidget
from src.ui_qt.widgets.enumeration_editor import EnumerationEditorWidget
from src.ui_qt.widgets.form_designer_widget import FormDesignerWidget, FormLockTarget
from src.ui_qt.widgets.layout_preview_widget import LayoutPreviewWidget
from src.ui_qt.widgets.pictures_gallery import PicturesGalleryWidget
from src.ui_qt.widgets.raster_image_editor import RasterImageEditorWidget
from src.ui_qt.widgets.register_editor import RegisterEditorWidget
from src.ui_qt.widgets.simple_object_editor import (
    EventSubscriptionEditorWidget,
    RoleEditorWidget,
    ScheduledJobEditorWidget,
)
from src.ui_qt.widgets.subsystem_editor import SubsystemEditorWidget
from src.ui_qt.widgets.svg_editor import SvgEditorWidget
from src.platform.logging_setup import get_logger


_log = get_logger("configurator.editors")


class _TimingMdiSubWindow(QMdiSubWindow):
    def __init__(self, *, timing_key: str, timing_title: str) -> None:
        super().__init__()
        self._timing_key = str(timing_key or "")
        self._timing_title = str(timing_title or "")
        self._close_started_at: float | None = None

    def closeEvent(self, event) -> None:  # noqa: N802
        started = time.perf_counter()
        self._close_started_at = started
        try:
            widget = self.widget()
            widget_name = type(widget).__name__ if widget is not None else "None"
            _log.info(
                "editor.close.start key=%s title=%r widget=%s",
                self._timing_key,
                self._timing_title,
                widget_name,
            )
        except Exception:
            pass
        try:
            if widget is not None:
                confirm = getattr(widget, "confirm_close", None)
                if callable(confirm) and not bool(confirm()):
                    event.ignore()
                    return
        except Exception as exc:
            _log.warning(
                "editor.close.confirm_failed key=%s title=%r error=%s",
                self._timing_key,
                self._timing_title,
                exc,
            )
            event.ignore()
            return
        try:
            if widget is not None:
                prepare = getattr(widget, "prepare_for_close", None)
                if callable(prepare):
                    prep_started = time.perf_counter()
                    prepare()
                    _log.info(
                        "editor.close.prepare_done key=%s title=%r widget=%s took=%.3fs",
                        self._timing_key,
                        self._timing_title,
                        widget_name,
                        time.perf_counter() - prep_started,
                    )
        except Exception as exc:
            _log.warning(
                "editor.close.prepare_failed key=%s title=%r error=%s",
                self._timing_key,
                self._timing_title,
                exc,
            )
        try:
            super().closeEvent(event)
        finally:
            try:
                _log.info(
                    "editor.close.event_done key=%s title=%r accepted=%s took=%.3fs",
                    self._timing_key,
                    self._timing_title,
                    bool(getattr(event, "isAccepted", lambda: True)()),
                    time.perf_counter() - started,
                )
            except Exception:
                pass


class ConfiguratorEditorsMixin:
    @staticmethod
    def _payload_display_text(value) -> str:
        if isinstance(value, str):
            return str(value or "").strip()
        if isinstance(value, dict):
            for lang in ("uk", "en", "ru"):
                text = str(value.get(lang) or "").strip()
                if text:
                    return text
            for raw in value.values():
                text = str(raw or "").strip()
                if text:
                    return text
        return ""

    def _payload_and_title_for_node(self, info: NodeInfo) -> tuple[dict, str]:
        payload: dict = {}
        title = info.name
        if self._vm is not None and info.guid:
            meta = self._vm.get_meta_by_guid(info.guid)
            if isinstance(meta, dict):
                payload = dict(meta.get("payload") or {}) if isinstance(meta.get("payload"), dict) else {}
                title = technical_object_name(meta.get("name"), payload=payload, fallback=info.name)
                payload["name"] = title
                if "title" not in payload:
                    payload["title"] = meta.get("title") or ""
                if not str(payload.get("synonym") or "").strip():
                    synonym = self._payload_display_text(payload.get("title"))
                    if synonym:
                        payload["synonym"] = synonym
        return payload, title

    def _technical_node_info(self, info: NodeInfo) -> NodeInfo:
        if info.kind != "object" or self._vm is None or not info.guid:
            return info
        meta = self._vm.get_meta_by_guid(info.guid)
        if not isinstance(meta, dict):
            return info
        return NodeInfo(
            kind=info.kind,
            name=technical_object_name(meta.get("name"), payload=meta.get("payload"), fallback=info.name),
            guid=info.guid,
            obj_type=info.obj_type,
        )

    def _resolve_code_editor_asset_key(self, info: NodeInfo, payload: dict | None) -> str:
        payload = payload if isinstance(payload, dict) else {}
        asset_key = ""
        resolve_for_owner = None
        if self._vm is not None:
            resolve_for_owner = getattr(self._vm, "resolve_module_asset_key_for_owner", None)
        if isinstance(payload.get("module"), dict):
            asset_key = str(payload["module"].get("asset_key") or "")
        if not asset_key and isinstance(payload.get("code"), dict):
            asset_key = str(payload["code"].get("asset_key") or "")
        if not asset_key:
            asset_key = str(payload.get("asset_key") or payload.get("module_asset_key") or "")
        if asset_key.startswith("module://") and info.guid:
            semantic_guid = asset_key.split("://", 1)[1].strip()
            owner_guid = str(info.guid or "").strip()
            if semantic_guid == owner_guid and callable(resolve_for_owner):
                try:
                    resolved_asset_key = str(resolve_for_owner(owner_guid) or "").strip()
                except Exception:
                    resolved_asset_key = ""
                if resolved_asset_key:
                    asset_key = resolved_asset_key
        if not asset_key and info.guid and callable(resolve_for_owner):
            try:
                asset_key = str(resolve_for_owner(str(info.guid or "")) or "")
            except Exception:
                asset_key = ""
        if not asset_key and info.guid:
            asset_key = f"module://{info.guid}"
        return str(asset_key or "").strip()

    def _available_subsystems(self):
        if self._vm is None:
            return None
        list_subsystems = getattr(self._vm, "list_subsystems", None)
        if not callable(list_subsystems):
            return []
        try:
            return list_subsystems()
        except Exception:
            return []

    def _close_editor_widget(self, w: QWidget) -> None:
        try:
            sub = w.parent()
            if isinstance(sub, QMdiSubWindow):
                sub.close()
            else:
                w.close()
        except Exception:
            return

    def _apply_object_patch_and_reload(self, widget: QWidget, guid: str, patch: dict) -> bool:
        if self._vm is not None and guid:
            save = getattr(self._vm, "save_object_payload_patch", None)
            if callable(save):
                if not bool(save(guid, dict(patch or {}), reload=False)):
                    return False
            else:
                update = getattr(self._vm, "update_object_payload", None)
                if not callable(update) or update(guid, dict(patch or {})) is False:
                    return False
        reload_fn = getattr(widget, "reload_from_vm", None)
        if callable(reload_fn):
            QTimer.singleShot(0, reload_fn)
        refresh_requested = getattr(self, "refreshRequested", None)
        if callable(getattr(refresh_requested, "emit", None)):
            try:
                refresh_requested.emit()
            except Exception:
                pass
        return True

    def _create_editor_for_node(self, info: NodeInfo) -> QWidget:
        info = self._technical_node_info(info)
        ot = (info.obj_type or "").lower()
        if ot in ("constants", "constant"):
            payload = {}
            if self._vm is not None and info.guid:
                meta = self._vm.get_meta_by_guid(info.guid)
                if isinstance(meta, dict):
                    payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
                    payload = {**payload, "title": str(meta.get("title") or info.name or "")}
            w = ConstantPropertiesWidget(info.name, payload=payload, vm=self._vm, obj_guid=str(info.guid or ""))
            if self._vm is not None and info.guid:
                w.applyRequested.connect(lambda patch, g=info.guid, widget=w: self._apply_object_patch_and_reload(widget, g, patch))
            return w
        if ot == "common_picture":
            if self._vm is not None and info.guid:
                meta = self._vm.get_meta_by_guid(info.guid)
                if isinstance(meta, dict):
                    p = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
                    pic = p.get("picture") if isinstance(p.get("picture"), dict) else {}
                    asset_key = str(pic.get("asset_key") or "").strip()
                    mime = str(pic.get("mime") or "").strip().lower()
                    if asset_key:
                        title = technical_object_name(meta.get("name"), payload=p, fallback=info.name)
                        if asset_key.lower().endswith(".svg") or mime == "image/svg+xml":
                            return SvgEditorWidget(vm=self._vm, asset_key=asset_key, title=title)
                        if mime.startswith("image/") or asset_key.lower().endswith(
                            (".png", ".jpg", ".jpeg", ".ico", ".bmp", ".webp")
                        ):
                            return RasterImageEditorWidget(vm=self._vm, asset_key=asset_key, title=title)

        if ot in (
            "catalog",
            "catalogs",
            "chart_of_accounts",
            "chart_of_calculation_types",
            "chart_of_characteristic_types",
            "report",
            "data_processor",
            "business_process",
            "task",
            "exchange_plan",
        ):
            payload, title = self._payload_and_title_for_node(info)

            w = CatalogEditorWidget(
                title=title,
                payload=payload,
                obj_type=ot,
                available_subsystems=self._available_subsystems(),
                vm=self._vm,
                obj_guid=(str(info.guid) if info.kind == "object" else ""),
            )
            if self._vm is not None and info.guid:
                w.applyRequested.connect(lambda patch, g=info.guid, widget=w: self._apply_object_patch_and_reload(widget, g, patch))
            w.closeRequested.connect(lambda _w=w: self._close_editor_widget(_w))
            return w

        if ot in ("document", "documents"):
            payload, title = self._payload_and_title_for_node(info)

            w = DocumentEditorWidget(
                title=title,
                payload=payload,
                available_subsystems=self._available_subsystems(),
                vm=self._vm,
                obj_guid=(str(info.guid) if info.kind == "object" else ""),
            )
            if self._vm is not None and info.guid:
                w.applyRequested.connect(lambda patch, g=info.guid, widget=w: self._apply_object_patch_and_reload(widget, g, patch))
                from src.ui_qt.services.posting_module_editor import insert_document_posting_handler

                w.postingModuleRequested.connect(
                    lambda code, guid=info.guid: insert_document_posting_handler(self, guid, code)
                )
            w.closeRequested.connect(lambda _w=w: self._close_editor_widget(_w))
            return w

        if ot in ("subsystem", "subsystems"):
            payload, title = self._payload_and_title_for_node(info)

            w = SubsystemEditorWidget(
                title=title,
                payload=payload,
                vm=self._vm,
                obj_guid=(str(info.guid) if info.kind == "object" else ""),
            )
            if self._vm is not None and info.guid:
                w.applyRequested.connect(lambda patch, g=info.guid, widget=w: self._apply_object_patch_and_reload(widget, g, patch))
            w.closeRequested.connect(lambda _w=w: self._close_editor_widget(_w))
            return w
        if ot in (
            "register",
            "registers",
            "register_info",
            "register_accum",
            "register_accounting",
            "register_calc",
        ):
            payload, title = self._payload_and_title_for_node(info)
            w = RegisterEditorWidget(
                title=title,
                payload=payload,
                obj_type=ot,
                vm=self._vm,
                obj_guid=(str(info.guid) if info.kind == "object" else ""),
            )
            if self._vm is not None and info.guid:
                w.applyRequested.connect(lambda patch, g=info.guid, widget=w: self._apply_object_patch_and_reload(widget, g, patch))
            w.closeRequested.connect(lambda _w=w: self._close_editor_widget(_w))
            return w
        if ot in ("enumeration", "enumerations"):
            payload, title = self._payload_and_title_for_node(info)
            w = EnumerationEditorWidget(
                title=title,
                payload=payload,
                vm=self._vm,
                obj_guid=(str(info.guid) if info.kind == "object" else ""),
            )
            if self._vm is not None and info.guid:
                w.applyRequested.connect(lambda patch, g=info.guid, widget=w: self._apply_object_patch_and_reload(widget, g, patch))
            w.closeRequested.connect(lambda _w=w: self._close_editor_widget(_w))
            return w
        if ot in ("role", "roles"):
            payload, title = self._payload_and_title_for_node(info)
            w = RoleEditorWidget(
                title=title,
                payload=payload,
                vm=self._vm,
                obj_guid=(str(info.guid) if info.kind == "object" else ""),
            )
            if self._vm is not None and info.guid:
                w.applyRequested.connect(lambda patch, g=info.guid, widget=w: self._apply_object_patch_and_reload(widget, g, patch))
            w.closeRequested.connect(lambda _w=w: self._close_editor_widget(_w))
            return w
        if ot in ("access_restrictions",):
            w = AccessRestrictionsProjectionWidget(vm=self._vm, title=info.name)
            w.openRoleRequested.connect(
                lambda role_guid, role_name: self.open_object_tab(
                    NodeInfo(kind="object", name=role_name, guid=role_guid, obj_type="role")
                )
            )
            return w
        if ot in ("scheduled_job", "scheduled_jobs"):
            payload, title = self._payload_and_title_for_node(info)
            w = ScheduledJobEditorWidget(
                title=title,
                payload=payload,
                vm=self._vm,
                obj_guid=(str(info.guid) if info.kind == "object" else ""),
            )
            if self._vm is not None and info.guid:
                w.applyRequested.connect(lambda patch, g=info.guid, widget=w: self._apply_object_patch_and_reload(widget, g, patch))
            w.closeRequested.connect(lambda _w=w: self._close_editor_widget(_w))
            return w
        if ot in ("event_subscription", "event_subscriptions"):
            payload, title = self._payload_and_title_for_node(info)
            w = EventSubscriptionEditorWidget(
                title=title,
                payload=payload,
                vm=self._vm,
                obj_guid=(str(info.guid) if info.kind == "object" else ""),
            )
            if self._vm is not None and info.guid:
                w.applyRequested.connect(lambda patch, g=info.guid, widget=w: self._apply_object_patch_and_reload(widget, g, patch))
            w.closeRequested.connect(lambda _w=w: self._close_editor_widget(_w))
            return w

        if "module" in ot or "code" in ot:
            asset_key = ""
            title = info.name
            if self._vm is not None and info.guid:
                meta = self._vm.get_meta_by_guid(info.guid)
                if isinstance(meta, dict):
                    payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
                    title = technical_object_name(meta.get("name"), payload=payload, fallback=info.name)
                    asset_key = self._resolve_code_editor_asset_key(info, payload)
            if not asset_key:
                asset_key = self._resolve_code_editor_asset_key(info, None)

            try:
                _log.info(
                    "module.editor.init guid=%s title=%r asset_key=%s type=%s",
                    str(info.guid or ""),
                    str(title or info.name or ""),
                    str(asset_key or ""),
                    ot,
                )
            except Exception:
                pass

            w = CodeEditorWidget(vm=self._vm, asset_key=str(asset_key or "").strip(), title=title or info.name)
            wire_definition = getattr(self, "_wire_code_editor_definition_navigation", None)
            if callable(wire_definition):
                wire_definition(w)
            w.closeRequested.connect(lambda _w=w: self._close_editor_widget(_w))
            return w
        if ot in ("form", "common_form"):
            return self._create_form_designer(info)
        if ot in ("layout", "common_layout"):
            payload, title = self._payload_and_title_for_node(info)
            return LayoutPreviewWidget(title=title, payload=payload, vm=self._vm, obj_guid=str(info.guid or ""))
        return ObjectStructureWidget(info.name)

    def _create_form_designer(self, info: NodeInfo) -> QWidget:
        payload: dict = {}
        meta: dict = {}
        if self._vm is not None and info.guid:
            m = self._vm.get_meta_by_guid(info.guid)
            if isinstance(m, dict):
                meta = m
                payload = m.get("payload") if isinstance(m.get("payload"), dict) else {}
            # Tree rows are intentionally slim. A form must be opened from
            # the full manifest payload so externalized form_model refs are
            # available even when the tree cache does not contain them.
            get_payload = getattr(self._vm, "manifest_get_payload", None)
            if callable(get_payload):
                try:
                    full_payload = get_payload(info.guid)
                except Exception:
                    full_payload = {}
                if isinstance(full_payload, dict) and full_payload:
                    merged = dict(full_payload)
                    merged.update(payload)
                    payload = merged
                    meta = dict(meta or {})
                    meta["payload"] = payload

        try:
            module_payload = payload.get("module") if isinstance(payload.get("module"), dict) else {}
            _log.info(
                "form.editor.init guid=%s title=%r payload_keys=%s has_form_model=%s has_form_module=%s module_asset=%s",
                str(info.guid or ""),
                str(info.name or ""),
                sorted(payload.keys()),
                bool(payload.get("form_model")),
                bool(payload.get("form_module")),
                str(module_payload.get("asset_key") or payload.get("module_asset_key") or payload.get("form_module_ref") or ""),
            )
        except Exception:
            pass

        lock_target: FormLockTarget | None = None
        try:
            if self._vm is not None and info.guid and isinstance(meta, dict):
                form_meta = meta
                if not form_meta:
                    form_meta = self._vm.get_meta_by_guid(info.guid) or {}
                forms_folder_guid = str(form_meta.get("parent_guid") or "").strip()
                forms_folder_meta = self._vm.get_meta_by_guid(forms_folder_guid) if forms_folder_guid else {}
                owner_guid = str((forms_folder_meta or {}).get("parent_guid") or "").strip()
                owner_meta = self._vm.get_meta_by_guid(owner_guid) if owner_guid else {}
                if isinstance(owner_meta, dict) and owner_guid:
                    ot = str(owner_meta.get("type") or "").strip() or str(info.obj_type or "")
                    oid = str(owner_meta.get("guid") or "").strip() or owner_guid
                    cid = str(info.name or info.guid or "").strip() or str(info.guid or "-")
                    lk = make_lock_key(
                        object_type=ot,
                        object_id=oid,
                        component_type="FormModule",
                        component_id=cid,
                    ).as_string()
                    lock_target = FormLockTarget(lock_key=lk, description=f"{ot}:{oid} FormModule {cid}")
        except Exception:
            lock_target = None

        w = FormDesignerWidget(
            vm=self._vm,
            form_guid=info.guid,
            form_title=technical_object_name(meta.get("name"), payload=payload, fallback=info.name),
            form_meta_payload=payload,
            storage_service=self._config_storage,
            lock_target=lock_target,
        )
        if self._vm is not None and info.guid:
            w.saveRequested.connect(lambda patch, g=info.guid, widget=w: self._apply_object_patch_and_reload(widget, g, patch))
        definition_signal = getattr(w, "definitionRequested", None)
        definition_handler = getattr(self, "_open_definition_target", None)
        if callable(getattr(definition_signal, "connect", None)) and callable(definition_handler):
            definition_signal.connect(definition_handler)
        usages_signal = getattr(w, "usagesRequested", None)
        usages_handler = getattr(self, "_open_usages_target", None)
        if callable(getattr(usages_signal, "connect", None)) and callable(usages_handler):
            usages_signal.connect(usages_handler)
        return w

    def open_object_tab(self, info: NodeInfo, *, force_new: bool = False) -> None:
        info = self._technical_node_info(info)
        started_at = time.perf_counter()
        _log.info(
            "editor.open.start kind=%s guid=%s type=%s title=%r force_new=%s",
            str(info.kind or ""),
            str(info.guid or ""),
            str(info.obj_type or ""),
            str(info.name or ""),
            bool(force_new),
        )
        section_key = ""
        parent_guid = ""
        if info.kind == "schema" and str(info.guid or "").startswith("virtual:"):
            try:
                parts = str(info.guid).split(":")
                if len(parts) >= 3:
                    parent_guid = parts[1]
                    section_key = parts[2]
                else:
                    parent_guid = ""
                    section_key = ""
            except Exception:
                parent_guid = ""
                section_key = ""
        elif info.kind == "folder" and self._vm is not None and info.guid:
            meta = self._vm.get_meta_by_guid(str(info.guid))
            if isinstance(meta, dict):
                payload = meta.get("payload")
                if not isinstance(payload, dict):
                    payload = {}
                if bool(payload.get("system")):
                    nm = str(meta.get("name") or "").strip().lower()
                    if nm in ("forms", "commands", "layouts", "modules"):
                        parent_guid = str(meta.get("parent_guid") or "").strip()
                        section_key = nm

        if parent_guid and section_key and self._vm is not None:
            parent_meta = self._vm.get_meta_by_guid(parent_guid) or {}
            parent_title = technical_object_name(parent_meta.get("name"), payload=parent_meta.get("payload"))
            parent_type = str(parent_meta.get("type") or info.obj_type or "")
            parent_info = NodeInfo(kind="object", name=parent_title, guid=parent_guid, obj_type=parent_type)
            self.open_object_tab(parent_info, force_new=False)
            sub = self._open_windows.get(parent_guid)
            if sub is not None:
                w = sub.widget()
                if hasattr(w, "set_current_section"):
                    try:
                        w.set_current_section(section_key)
                    except Exception:
                        pass
            return
        base_key = info.guid or f"{info.kind}:{info.name}"
        key = base_key
        if not force_new and key in self._open_windows:
            self.mdi.setActiveSubWindow(self._open_windows[key])
            self._open_windows[key].showNormal()
            _log.info(
                "editor.open.done key=%s guid=%s title=%r widget=%s reused=True took=%.3fs",
                key,
                str(info.guid or ""),
                str(info.name or ""),
                type(self._open_windows[key].widget()).__name__ if self._open_windows[key].widget() is not None else "None",
                time.perf_counter() - started_at,
            )
            return
        if force_new:
            n = 2
            while key in self._open_windows:
                key = f"{base_key}#{n}"
                n += 1
        editor = self._create_editor_for_node(info)
        sub = _TimingMdiSubWindow(timing_key=key, timing_title=info.name)
        sub.setWidget(editor)
        sub.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        sub.setWindowTitle(info.name)
        dirty_signal = getattr(editor, "dirtyChanged", None)
        if callable(getattr(dirty_signal, "connect", None)):
            dirty_signal.connect(
                lambda dirty, window=sub, base_title=str(info.name or ""): window.setWindowTitle(
                    base_title + (" *" if bool(dirty) else "")
                )
            )
        try:
            if self._vm is not None and info.guid:
                meta = self._vm.get_meta_by_guid(str(info.guid))
                if isinstance(meta, dict):
                    sub.setWindowIcon(self._icon_provider.tree_icon(meta))
        except Exception:
            pass

        def _on_destroyed():
            try:
                started = getattr(sub, "_close_started_at", None)
                if isinstance(started, (int, float)) and started > 0:
                    _log.info(
                        "editor.close.destroyed key=%s title=%r total=%.3fs",
                        key,
                        info.name,
                        time.perf_counter() - float(started),
                    )
                else:
                    _log.info("editor.destroyed key=%s title=%r", key, info.name)
            except Exception:
                pass
            self._open_windows.pop(key, None)

        sub.destroyed.connect(_on_destroyed)
        self.mdi.addSubWindow(sub)
        sub.resize(740, 520)
        sub.show()
        self._open_windows[key] = sub
        _log.info(
            "editor.open.done key=%s guid=%s title=%r widget=%s reused=False took=%.3fs",
            key,
            str(info.guid or ""),
            str(info.name or ""),
            type(editor).__name__ if editor is not None else "None",
            time.perf_counter() - started_at,
        )

    def open_object_tab_new(self, info: NodeInfo) -> None:
        self.open_object_tab(info, force_new=True)

    def open_pictures_gallery(self) -> None:
        key = "pictures_gallery"
        if key in self._open_windows:
            self.mdi.setActiveSubWindow(self._open_windows[key])
            self._open_windows[key].showNormal()
            return
        if self._vm is None:
            return
        w = PicturesGalleryWidget(vm=self._vm)
        sub = QMdiSubWindow()
        sub.setWidget(w)
        sub.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        sub.setWindowTitle(t("pictures_title"))

        def _on_destroyed():
            self._open_windows.pop(key, None)

        sub.destroyed.connect(_on_destroyed)
        self.mdi.addSubWindow(sub)
        sub.resize(900, 560)
        sub.show()
        self._open_windows[key] = sub

    def open_svg_editor(self, asset_key: str, title: str = "") -> None:
        self.open_picture_editor(asset_key, title, "image/svg+xml")

    def open_picture_editor(self, asset_key: str, title: str = "", mime: str = "") -> None:
        asset_key = str(asset_key or "").strip()
        mime = str(mime or "").strip().lower()
        if not asset_key or self._vm is None:
            return
        is_svg = asset_key.lower().endswith(".svg") or mime == "image/svg+xml"
        key = f"picture_editor:{asset_key}"
        if key in self._open_windows:
            self.mdi.setActiveSubWindow(self._open_windows[key])
            self._open_windows[key].showNormal()
            return
        if is_svg:
            w = SvgEditorWidget(vm=self._vm, asset_key=asset_key, title=title or asset_key)
        else:
            w = RasterImageEditorWidget(vm=self._vm, asset_key=asset_key, title=title or asset_key)
        sub = QMdiSubWindow()
        sub.setWidget(w)
        sub.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        sub.setWindowTitle(title or asset_key)

        def _on_destroyed():
            self._open_windows.pop(key, None)

        sub.destroyed.connect(_on_destroyed)
        self.mdi.addSubWindow(sub)
        sub.resize(980, 640)
        sub.show()
        self._open_windows[key] = sub

    def open_picture_editor_for_selection(self) -> None:
        if self._vm is None:
            return
        idx = self.tree.currentIndex()
        if not idx.isValid():
            self.open_pictures_gallery()
            return
        meta = idx.data(self.ROLE_META) or {}
        if not isinstance(meta, dict):
            self.open_pictures_gallery()
            return
        if str(meta.get("type")) != "common_picture":
            self.open_pictures_gallery()
            return
        guid = str(meta.get("guid") or "").strip()
        if not guid:
            self.open_pictures_gallery()
            return
        self._vm.open_picture_editor_for_picture(guid)

    def open_svg_editor_for_selection(self) -> None:
        self.open_picture_editor_for_selection()

    def upload_pictures_via_dialog(self) -> None:
        if self._vm is None:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            t("pictures_upload"),
            "",
            "Images (*.svg *.png *.jpg *.jpeg *.ico);;All files (*.*)",
        )
        if not paths:
            return
        self._vm.import_pictures(list(paths))
        self.open_pictures_gallery()
