from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtGui import QIcon, QStandardItemModel

from src.configurator.application.service import ConfiguratorService
from src.configurator.application.manifest_editor import ManifestEditorService, ManifestEditorState
from src.platform.logging_setup import get_logger
from src.ui_qt.i18n import t
from src.ui_qt.services.icon_provider import IconProvider

from .configurator_vm_actions import ConfiguratorVmActionsMixin
from .configurator_vm_assets import ConfiguratorVmAssetsMixin
from .configurator_vm_generation import ConfiguratorVmGenerationMixin
from .configurator_vm_runtime import ConfiguratorVmRuntimeMixin
from .configurator_vm_state import ConfiguratorVmStateMixin
from .configurator_vm_tree import ConfiguratorVmTreeMixin
from .configurator_vm_types import Dialogs, NodeInfo, ObjectLike

_log = get_logger("configurator.vm")


class ConfiguratorViewModel(
    ConfiguratorVmRuntimeMixin,
    ConfiguratorVmAssetsMixin,
    ConfiguratorVmActionsMixin,
    ConfiguratorVmGenerationMixin,
    ConfiguratorVmStateMixin,
    ConfiguratorVmTreeMixin,
    QObject,
    ):
    statusChanged = Signal(str)
    propertiesRowsChanged = Signal(list)
    editorStateChanged = Signal(object)
    expandDefaultRequested = Signal()
    openEditorRequested = Signal(object)
    openEditorNewRequested = Signal(object)
    openPicturesGalleryRequested = Signal()
    openSvgEditorRequested = Signal(str, str)
    openPictureEditorRequested = Signal(str, str, str)
    runtimeRefreshReady = Signal(object, float)
    runtimeRefreshFailed = Signal(str, float)

    ROLE_KIND = Qt.ItemDataRole.UserRole + 1
    ROLE_META = Qt.ItemDataRole.UserRole + 2

    def __init__(self, runtime_url: str, db_uid: str, dialogs: Dialogs,
                 icon_provider: Callable[[dict], QIcon],
                 *,
                 db_path: str = "",
                 startup_progress_cb: Optional[Callable[[int, str], None]] = None,
                 eager_runtime_refresh: bool = False,
                 preopened: tuple[ConfiguratorService, Any] | None = None):
        """Створити ViewModel і відкрити базу через Runtime RPC."""
        super().__init__()
        self.runtime_url = runtime_url
        self.db_uid      = db_uid
        self.db_path     = db_path
        self._dialogs    = dialogs
        self._startup_progress_cb = startup_progress_cb

        self.icon_provider = IconProvider(self.get_active_palette_map, tree_icon_provider=icon_provider)
        self._icon_for_meta = self.icon_provider.tree_icon

        self._search: str = ""
        self._subsystem_filter_guid: str = ""
        self._service = preopened[0] if preopened is not None else ConfiguratorService()
        self._runtime_refresh_in_flight = False
        self._runtime_refresh_epoch = 0
        self._objects_snapshot: List[ObjectLike] = []
        self._objects_by_guid: Dict[str, ObjectLike] = {}
        self._meta_by_guid: Dict[str, Dict[str, Any]] = {}
        self._payload_overrides_by_guid: Dict[str, Dict[str, Any]] = {}
        self._subsystems_cache: List[Dict[str, Any]] = []
        self._tree_icon_cache: Dict[Tuple[str, str, str], QIcon] = {}
        self._before_tree_rebuild: Optional[Callable[[], None]] = None
        self._after_tree_rebuild: Optional[Callable[[], None]] = None
        self.runtimeRefreshReady.connect(self._on_runtime_refresh_ready)
        self.runtimeRefreshFailed.connect(self._on_runtime_refresh_failed)
        if preopened is None:
            self._startup_progress(28, t("startup_runtime_connect"))
            res = self._service.open_db(runtime_url, db_uid, db_path=db_path)
        else:
            res = preopened[1]
        self.db_uid = str(getattr(self._service, "db_uid", "") or db_uid or "")
        self.db_path = str(db_path or "")
        _log.info("viewmodel.init source=%s objects=%d", "cache" if res.loaded_from_cache else "runtime", len(res.objects))

        self._editor = ManifestEditorService(self._service)
        self._schema_editor_state = ManifestEditorState()
        self._schema_editor_context: Dict[str, Any] = {}
        self.db = res.db
        self.tree_model = QStandardItemModel()

        self._startup_progress(52, t("startup_tree_build"))
        self._populate_tree(res.objects)

        cache_already_fresh = bool(getattr(res, "loaded_from_cache", False) and getattr(res, "cache_validated", False))

        if res.loaded_from_cache and eager_runtime_refresh and not cache_already_fresh:
            self._startup_progress(72, t("startup_runtime_sync"))
            try:
                objs = self._service.list_objects()
            except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                _log.warning("startup runtime refresh failed: %s", exc)
            else:
                if objs:
                    self._startup_progress(84, t("startup_tree_finalize"))
                    self._populate_tree(objs)
                else:
                    _log.warning("startup runtime refresh returned 0 objects; keeping cache snapshot")

        self.statusChanged.emit(t("status_ready"))
        if res.loaded_from_cache and not eager_runtime_refresh and not cache_already_fresh:
            QTimer.singleShot(0, self.start_background_runtime_refresh)
