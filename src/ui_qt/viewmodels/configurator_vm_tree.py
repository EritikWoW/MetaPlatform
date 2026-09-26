from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QStandardItem, QStandardItemModel

from src.core.object_policies import section_i18n_key
from src.configurator.application.service import ConfiguratorService
from src.configurator.domain.technical_names import technical_object_name
from src.ui_qt.i18n import t
from src.ui_qt.services.tree_builder import build_tree_model, prepare_tree_objects
from src.platform.logging_setup import get_logger
from src.ui_qt.viewmodels.configurator_vm_types import ObjectLike

_log = get_logger("configurator.vm")


class _ConfiguratorVmTreeContract:
    _service: ConfiguratorService
    statusChanged: Any
    runtimeRefreshReady: Any
    runtimeRefreshFailed: Any
    expandDefaultRequested: Any
    _runtime_refresh_in_flight: bool
    _runtime_refresh_epoch: int
    _search: str
    _subsystem_filter_guid: str
    _meta_by_guid: Dict[str, Dict[str, Any]]
    _payload_overrides_by_guid: Dict[str, Dict[str, Any]]
    _tree_icon_cache: Dict[Tuple[str, str, str], QIcon]
    _before_tree_rebuild: Optional[Callable[[], None]]
    _after_tree_rebuild: Optional[Callable[[], None]]
    tree_model: QStandardItemModel
    _icon_for_meta: Callable[[Dict[str, Any]], QIcon]
    ROLE_KIND: int
    ROLE_META: int

    def _remember_objects_snapshot(self, objs: List[ObjectLike]) -> None: ...
    def _tree_payload_snapshot(self, payload: Any) -> Dict[str, Any]: ...


class ConfiguratorVmTreeMixin(_ConfiguratorVmTreeContract):

    def reload(self) -> None:
        """Перезагрузить данные manifest и пересобрать дерево конфигурации."""
        objs = self._service.list_objects()
        self._populate_tree(objs)
        self.statusChanged.emit(t("status_ready"))


    def refresh_from_runtime(self) -> None:
        """Refresh tree from runtime on the UI thread (fallback path)."""
        started_at = time.perf_counter()
        try:
            objs = self._service.list_objects()
        except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            _log.warning("refresh_from_runtime failed in %.3fs: %s", time.perf_counter() - started_at, exc)
            return
        self._populate_tree(objs)
        self.statusChanged.emit(t("status_ready"))
        _log.info("refresh_from_runtime done objects=%d in %.3fs", len(objs), time.perf_counter() - started_at)


    def start_background_runtime_refresh(self) -> None:
        """Fetch manifest in a background thread after cache-based startup."""
        if self._runtime_refresh_in_flight:
            return
        self._runtime_refresh_in_flight = True
        self._runtime_refresh_epoch = int(getattr(self, "_runtime_refresh_epoch", 0)) + 1
        refresh_epoch = self._runtime_refresh_epoch
        self.statusChanged.emit("Synchronizing configuration structure...")

        def worker() -> None:
            started_at = time.perf_counter()
            try:
                objs = self._service.list_objects()
            except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                self.runtimeRefreshFailed.emit(str(exc), time.perf_counter() - started_at)
                return
            self.runtimeRefreshReady.emit((refresh_epoch, objs), time.perf_counter() - started_at)

        threading.Thread(target=worker, name="configurator-runtime-refresh", daemon=True).start()


    def _on_runtime_refresh_ready(self, objs: object, duration: float) -> None:
        refresh_epoch = int(getattr(self, "_runtime_refresh_epoch", 0))
        if isinstance(objs, tuple) and len(objs) == 2:
            response_epoch, objs = objs
            try:
                response_epoch = int(response_epoch)
            except (TypeError, ValueError):
                response_epoch = -1
            if response_epoch != refresh_epoch:
                _log.info(
                    "background runtime refresh ignored stale response epoch=%s current=%s",
                    response_epoch,
                    refresh_epoch,
                )
                return
        self._runtime_refresh_in_flight = False
        rows = list(objs) if isinstance(objs, list) else []
        if rows:
            self._populate_tree(rows)
        else:
            _log.warning("background runtime refresh returned 0 objects; keeping current tree")
        self.statusChanged.emit(t("status_ready"))
        _log.info("background runtime refresh done objects=%d in %.3fs", len(rows), duration)


    def _on_runtime_refresh_failed(self, error: str, duration: float) -> None:
        self._runtime_refresh_in_flight = False
        self.statusChanged.emit(t("status_ready"))
        _log.warning("background runtime refresh failed in %.3fs: %s", duration, error)


    def _populate_tree(self, objs: List[ObjectLike]) -> None:
        """Пересобрать дерево конфигурации из manifest-объектов (с учётом поиска)."""
        started_at = time.perf_counter()
        self._remember_objects_snapshot(objs)
        self._meta_by_guid = {}
        self._payload_overrides_by_guid = {}
        self._tree_icon_cache = {}
        # Важный инвариант стабилизации:
        # логика фильтрации legacy-папок и поиска должна быть единой
        # для ViewModel и Controller. Поэтому используем TreeBuilder.
        objs2 = prepare_tree_objects(
            objs,
            search_text=self._search,
            subsystem_filter_guid=getattr(self, "_subsystem_filter_guid", ""),
        )
        prepared_at = time.perf_counter()
        if self._before_tree_rebuild is not None:
            try:
                self._before_tree_rebuild()
            except Exception:
                pass
        try:
            result = build_tree_model(
                self.tree_model,
                objs2,
                mk_item=self._mk_item,
            )
        finally:
            if self._after_tree_rebuild is not None:
                try:
                    self._after_tree_rebuild()
                except Exception:
                    pass
        built_at = time.perf_counter()
        _log.info(
            "populate_tree input=%d prepared=%d built=%d orphans=%d prepare=%.3fs build=%.3fs total=%.3fs unique_icons=%d",
            len(objs),
            len(objs2),
            result.built,
            result.orphans,
            prepared_at - started_at,
            built_at - prepared_at,
            built_at - started_at,
            len(self._tree_icon_cache),
        )
        self.expandDefaultRequested.emit()


    def _mk_item(self, o: ObjectLike) -> QStandardItem:
        """Создать QStandardItem для узла manifest и заполнить метаданные (ROLE_META/ROLE_KIND)."""
        title = o.title or o.name or o.guid

        try:
            payload = o.payload if isinstance(o.payload, dict) else {}
            is_system = bool(payload.get("system")) or o.kind == "root"

            if is_system:
                if o.kind == "root":
                    # Корінь конфігурації — i18n або title з payload
                    cfg_title = t("cfg_tree_title")
                    if cfg_title:
                        title = cfg_title

                elif o.kind == "group":
                    # Головні групи (Довідники, Документи...) — group.TYPE
                    i18n_key = f"group.{o.type}"
                    localized = t(i18n_key)
                    if localized and localized != i18n_key:
                        title = localized

                elif o.kind == "folder":
                    # 1) Папки «Загальні» (subsystems, roles, ...) — folder.NAME
                    i18n_key = f"folder.{o.name}"
                    localized = t(i18n_key)
                    if localized and localized != i18n_key:
                        title = localized
                    else:
                        # 2) Системні підпапки всередині об'єктів (forms/commands/...) — tree.KEY
                        key = section_i18n_key(str(o.name))
                        if key:
                            title = t(key)

                elif o.kind == "schema":
                    # Віртуальні схемні секції (Виміри, Ресурси, ...)
                    key = section_i18n_key(str(o.name))
                    if key:
                        title = t(key)

            if o.kind == "object":
                title = technical_object_name(o.name, payload=payload)

        except (TypeError, ValueError, AttributeError, KeyError):
            pass

        it = QStandardItem(title)

        meta: Dict[str, Any] = {
            "guid": o.guid,
            "type": str(o.type),
            "name": o.name,
            "title": o.title,
            "kind": o.kind,
            "parent_guid": o.parent_guid,
            "payload": self._tree_payload_snapshot(o.payload),
        }
        # Selection must use the same source name as the rendered tree, even
        # when the shared lightweight snapshot omits imported metadata fields.
        if isinstance(o.payload, dict) and isinstance(o.payload.get("source_name"), str):
            meta["payload"]["source_name"] = o.payload["source_name"]
        self._meta_by_guid[str(o.guid)] = meta

        it.setData(o.kind, self.ROLE_KIND)
        it.setData(meta, self.ROLE_META)

        try:
            icon_key = self._icon_cache_key(meta)
            icon = self._tree_icon_cache.get(icon_key)
            if icon is None:
                icon = self._icon_for_meta(meta)
                self._tree_icon_cache[icon_key] = icon
            it.setIcon(icon)
        except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError):
            pass

        # editable only for objects (keep conservative)
        it.setEditable(o.kind in ("object", "folder"))
        return it


    @staticmethod
    def _icon_cache_key(meta: Dict[str, Any]) -> Tuple[str, str, str]:
        """Return a semantic cache key for tree icons."""
        kind = str(meta.get("kind") or "")
        obj_type = str(meta.get("type") or "")
        name = str(meta.get("name") or "")
        payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}

        if kind == "root":
            return ("root", "", "")
        if kind == "group":
            return ("group", obj_type, "")
        if kind == "object":
            return ("object", obj_type, "")
        if kind == "schema":
            schema_kind = str(payload.get("schema_item_kind") or payload.get("section") or name or "").strip()
            return ("schema", schema_kind, obj_type)
        if kind == "folder":
            if bool(payload.get("system") or payload.get("virtual")):
                return ("folder-system", name, obj_type)
            return ("folder", obj_type, "")
        return (kind, obj_type, "")
