from __future__ import annotations

import getpass
import json
import logging
import os
import re
import time
import threading
from typing import Dict, Optional

from PySide6.QtWidgets import QInputDialog, QMessageBox, QTabWidget, QVBoxLayout, QWidget

from src.client.data_tables import data_table_name as _data_table, infer_data_table_name
from src.configurator.persistence.system_tables import ROLES_TABLE, USER_ROLES_TABLE, USERS_TABLE
from src.dsl.platform_symbols import METADATA_CATEGORIES
from src.client.forms.constants_form import ConstantsForm
from src.client.forms.form_runtime_widget import FormRuntimeWidget, ObjContext
from src.client.forms.form_runtime_window import FormRuntimeWindow
from src.client.forms.print_form import PrintPreviewForm
from src.client.forms.register_viewer import RegisterViewerWidget
from src.client.forms.report_form import ReportResultForm
from src.client.forms.structure_inspector import StructureInspectorWidget
from src.runtime.script.catalog_proxy import build_global_context
from src.runtime.script.debugger import create_debug_session_from_env
from src.runtime.script.module_registry import CommonModuleRegistry
from src.configurator.domain.form_model import (
    normalize_form_open_mode,
    normalize_form_window_lock_mode,
)
from src.ui_qt.i18n import t

logger = logging.getLogger("client.window")

_STRUCTURE_EXTERNALIZED_KEYS = (
    "content_refs",
    "form_model",
    "layout_model",
    "metadata_structure",
    "objects",
    "requisites",
    "tabular_parts",
)

_STARTUP_MODULE_PAYLOAD_KEYS = (
    "managed_application_module",
    "session_module",
    "external_connection_module",
    "ordinary_application_module",
    "startup_modules",
    "startup_module_refs",
    "startup_module_ref",
    "startup_module",
    "modules_on_startup",
    "startup",
)

_OBJECT_REF_ROOTS = {
    "business_process": "BusinessProcess",
    "catalog": "Catalog",
    "chart_of_accounts": "ChartOfAccounts",
    "chart_of_calculation_types": "ChartOfCalculationTypes",
    "chart_of_characteristic_types": "ChartOfCharacteristicTypes",
    "common_attribute": "CommonAttribute",
    "common_command": "CommonCommand",
    "common_form": "CommonForm",
    "common_layout": "CommonTemplate",
    "common_module": "CommonModule",
    "common_picture": "CommonPicture",
    "command_group": "CommandGroup",
    "constants": "Constant",
    "data_processor": "DataProcessor",
    "document": "Document",
    "document_numerator": "DocumentNumerator",
    "enumeration": "Enum",
    "exchange_plan": "ExchangePlan",
    "functional_option": "FunctionalOption",
    "functional_option_param": "FunctionalOptionsParameter",
    "journal": "DocumentJournal",
    "language": "Language",
    "register_accum": "AccumulationRegister",
    "register_accounting": "AccountingRegister",
    "register_calc": "CalculationRegister",
    "register_info": "InformationRegister",
    "report": "Report",
    "role": "Role",
    "sequence": "Sequence",
    "session_param": "SessionParameter",
    "subsystem": "Subsystem",
    "task": "Task",
}


class _MetadataObjectProxy:
    """Stable, attribute-based view over one manifest row."""

    def __init__(self, row: dict) -> None:
        self._row = dict(row or {})
        self._payload = self._row.get("payload") if isinstance(self._row.get("payload"), dict) else {}

    def __getitem__(self, key: str):
        return self._row[key]

    def get(self, key: str, default=None):
        return self._row.get(key, default)

    @property
    def Name(self) -> str:
        return str(self._row.get("name") or self._row.get("title") or "")

    @property
    def Имя(self) -> str:
        return self.Name

    @property
    def Назва(self) -> str:
        return self.Name

    @property
    def Synonym(self) -> str:
        return str(self._row.get("title") or self.Name)

    @property
    def Синоним(self) -> str:
        return self.Synonym

    @property
    def Синонім(self) -> str:
        return self.Synonym

    @property
    def Guid(self) -> str:
        return str(self._row.get("guid") or "")

    @property
    def GUID(self) -> str:
        return self.Guid

    @property
    def Type(self) -> str:
        return str(self._row.get("type") or "")

    @property
    def Тип(self) -> str:
        return self.Type

    @property
    def FullName(self) -> str:
        return str(self._payload.get("metadata_ref") or f"{self.Type}.{self.Name}".strip("."))

    @property
    def ПолноеИмя(self) -> str:
        return self.FullName

    @property
    def ПовнеІмя(self) -> str:
        return self.FullName

    @property
    def Properties(self) -> dict:
        return dict(self._payload)

    @property
    def Свойства(self) -> dict:
        return self.Properties

    @property
    def Властивості(self) -> dict:
        return self.Properties

    def __getattr__(self, name: str):
        if str(name or "").startswith("_"):
            raise AttributeError(name)
        target = str(name or "").casefold()
        for source in (self._row, self._payload):
            for key, value in source.items():
                if str(key).casefold() == target:
                    return value
        raise AttributeError(name)


class _MetadataCollectionProxy:
    def __init__(self, rows: list[dict], type_name: str) -> None:
        self._rows = [dict(row) for row in rows if str(row.get("type") or "") == str(type_name or "")]
        self._items = [_MetadataObjectProxy(row) for row in self._rows]

    def __iter__(self):
        return iter(self._items)

    def __getitem__(self, name: str):
        return self.Find(name)

    def __getattr__(self, name: str):
        if str(name or "").startswith("_"):
            raise AttributeError(name)
        return self.Find(name)

    def __len__(self):
        return len(self._rows)

    def Count(self):
        return len(self._rows)

    def Количество(self):
        return len(self._rows)

    def Кількість(self):
        return len(self._rows)

    def Find(self, name: str):
        target = str(name or "").casefold()
        for item in self._items:
            if item.Name.casefold() == target or item.Synonym.casefold() == target:
                return item
        return None

    def Найти(self, name: str):
        return self.Find(name)

    def Знайти(self, name: str):
        return self.Find(name)


class _MetadataSubsystemProxy:
    def __init__(self, row: dict) -> None:
        self._row = dict(row or {})
        payload = self._row.get("payload") if isinstance(self._row.get("payload"), dict) else {}
        self._children = _MetadataSubsystemCollection([])
        self.Name = str(self._row.get("title") or self._row.get("name") or "")
        self.Имя = self.Name
        self.Назва = self.Name
        include = payload.get("include_in_command_interface")
        if include is None:
            include = payload.get("IncludeInCommandInterface")
        self.IncludeInCommandInterface = bool(include)
        self.ВключатьВКомандныйИнтерфейс = bool(include)
        self.ВключатиДоКомандногоІнтерфейсу = bool(include)

    @property
    def Subsystems(self):
        return self._children

    @property
    def Подсистемы(self):
        return self._children

    @property
    def Підсистеми(self):
        return self._children


class _MetadataSubsystemCollection:
    def __init__(self, items: list[_MetadataSubsystemProxy]) -> None:
        self._items = list(items)

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)

    def __getitem__(self, name: str):
        return self.Find(name)

    def Count(self):
        return len(self._items)

    def Количество(self):
        return len(self._items)

    def Кількість(self):
        return len(self._items)

    def Find(self, name: str):
        target = str(name or "").casefold()
        return next(
            (
                item
                for item in self._items
                if item.Name.casefold() == target
                or str(item._row.get("name") or "").casefold() == target
            ),
            None,
        )

    def Найти(self, name: str):
        return self.Find(name)

    def Знайти(self, name: str):
        return self.Find(name)


def _metadata_subsystems(rows: list[dict]) -> _MetadataSubsystemCollection:
    subsystem_rows = [
        dict(row)
        for row in rows
        if isinstance(row, dict) and str(row.get("type") or "") == "subsystem"
    ]
    proxies = {
        str(row.get("guid") or "").strip(): _MetadataSubsystemProxy(row)
        for row in subsystem_rows
        if str(row.get("guid") or "").strip()
    }
    child_rows: dict[str, list[_MetadataSubsystemProxy]] = {guid: [] for guid in proxies}
    roots: list[_MetadataSubsystemProxy] = []
    for row in subsystem_rows:
        guid = str(row.get("guid") or "").strip()
        item = proxies.get(guid)
        if item is None:
            continue
        parent_guid = str(row.get("parent_guid") or "").strip()
        if parent_guid in proxies and parent_guid != guid:
            child_rows[parent_guid].append(item)
        else:
            roots.append(item)
    for guid, item in proxies.items():
        item._children = _MetadataSubsystemCollection(child_rows.get(guid, []))
    return _MetadataSubsystemCollection(roots)


class _MetadataEnumNamespace:
    def __getattr__(self, name: str):
        if str(name or "").startswith("_"):
            raise AttributeError(name)
        return str(name or "")


class _MetadataObjectPropertiesProxy:
    def __getattr__(self, name: str):
        if str(name or "").startswith("_"):
            raise AttributeError(name)
        return _MetadataEnumNamespace()


class _MetadataProxy:
    _ALIASES = {
        alias: category.type_name
        for category in METADATA_CATEGORIES
        for alias in category.names
    } | {
        "ОбщиеРеквизиты": "common_attribute",
        "СпільніРеквізити": "common_attribute",
        "CommonAttributes": "common_attribute",
    }

    def __init__(
        self,
        rows: list[dict],
        configuration: dict | None = None,
        resolver=None,
    ) -> None:
        self._rows = [dict(row) for row in rows if isinstance(row, dict)]
        self._configuration = dict(configuration or {})
        self._resolver = resolver
        self._collections: dict[str, _MetadataCollectionProxy] = {}
        self._object_properties = _MetadataObjectPropertiesProxy()

    @property
    def Имя(self) -> str:
        return str(self._configuration.get("title") or self._configuration.get("name") or "")

    @property
    def Назва(self) -> str:
        return self.Имя

    @property
    def Name(self) -> str:
        return str(self._configuration.get("name") or self._configuration.get("title") or "")

    @property
    def Версия(self) -> str:
        payload = self._configuration.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        return str(payload.get("version") or payload.get("Version") or "0.0.0.0")

    @property
    def Версія(self) -> str:
        return self.Версия

    @property
    def Version(self) -> str:
        return self.Версия

    def __getattr__(self, name: str):
        if str(name or "") in {
            "СвойстваОбъектов",
            "ВластивостіОбєктів",
            "ObjectProperties",
        }:
            return self._object_properties
        type_name = self._ALIASES.get(str(name or ""), "")
        if type_name:
            cached = self._collections.get(type_name)
            if cached is not None:
                return cached
            rows = list(self._rows)
            if callable(self._resolver):
                try:
                    resolved = self._resolver(type_name)
                    if isinstance(resolved, list):
                        by_guid = {
                            str(row.get("guid") or "").strip(): dict(row)
                            for row in rows
                            if isinstance(row, dict) and str(row.get("guid") or "").strip()
                        }
                        for row in resolved:
                            if not isinstance(row, dict):
                                continue
                            guid = str(row.get("guid") or "").strip()
                            if guid:
                                by_guid[guid] = dict(row)
                        rows = list(by_guid.values())
                except Exception:
                    pass
            collection = _MetadataCollectionProxy(rows, type_name)
            if type_name == "subsystem":
                collection = _metadata_subsystems(rows)
            self._collections[type_name] = collection
            return collection
        raise AttributeError(name)

    def Objects(self):
        return list(self._rows)

    def Объекты(self):
        return self.Objects()

    def Обєкти(self):
        return self.Objects()

    def Find(self, ref: str):
        target = str(ref or "").casefold()
        for row in self._rows:
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            candidates = [
                row.get("guid"),
                row.get("name"),
                row.get("title"),
                payload.get("metadata_ref"),
            ]
            if any(str(item or "").casefold() == target for item in candidates):
                return row
        return None

    def Найти(self, ref: str):
        return self.Find(ref)

    def Знайти(self, ref: str):
        return self.Find(ref)


class ClientWindowRuntimeMixin:
    @staticmethod
    def _form_kind_for_open_mode(mode: str, owner_type: str = "") -> str:
        normalized = str(mode or "list").strip().lower()
        obj_type = str(owner_type or "").strip().lower()
        if normalized == "list" and obj_type in {"data_processor", "data_processors", "common_form", "common_forms"}:
            return "object_form"
        return "object_form" if normalized == "object" or normalized.startswith("object:") else "list_form"

    @staticmethod
    def _resolve_form_open_mode(model: dict | None, owner_type: str = "") -> str:
        root = model.get("root") if isinstance(model, dict) else {}
        props = root.get("props") if isinstance(root, dict) and isinstance(root.get("props"), dict) else {}
        mode = normalize_form_open_mode(props.get("open_mode"))
        if mode in {"workspace", "window"}:
            return mode
        if normalize_form_window_lock_mode(props.get("window_lock_mode")) != "none":
            return "window"
        obj_type = str(owner_type or "").strip().lower()
        if obj_type in {"data_processor", "data_processors", "common_form", "common_forms"}:
            return "window"
        return "workspace"

    @staticmethod
    def _resolve_form_window_lock_mode(model: dict | None) -> str:
        root = model.get("root") if isinstance(model, dict) else {}
        props = root.get("props") if isinstance(root, dict) and isinstance(root.get("props"), dict) else {}
        return normalize_form_window_lock_mode(props.get("window_lock_mode"))

    def _runtime_form_widget(self, view_id: str):
        view = self._views.get(view_id)
        if view is not None:
            return getattr(view, "_form_widget", view)
        window = getattr(self, "_form_windows", {}).get(view_id)
        if window is not None:
            return getattr(window, "form_widget", None)
        return None

    def _activate_form_window(self, view_id: str) -> bool:
        window = getattr(self, "_form_windows", {}).get(view_id)
        if window is None:
            return False
        try:
            window.activate()
            return True
        except RuntimeError:
            getattr(self, "_form_windows", {}).pop(view_id, None)
            return False

    def _present_form(
        self,
        *,
        view_id: str,
        widget: QWidget,
        title: str,
        model: dict,
        owner_type: str = "",
    ) -> None:
        if self._resolve_form_open_mode(model, owner_type) == "workspace":
            self._register_view(view_id, widget)
            self._select_view(view_id)
            return

        windows = getattr(self, "_form_windows", None)
        if not isinstance(windows, dict):
            windows = {}
            self._form_windows = windows
        existing = windows.get(view_id)
        if existing is not None:
            widget.deleteLater()
            self._activate_form_window(view_id)
            return

        window = FormRuntimeWindow(
            view_id=view_id,
            title=title,
            content_widget=widget,
            model=model,
            lock_mode=self._resolve_form_window_lock_mode(model),
            parent=self,
        )
        windows[view_id] = window
        self._titles[view_id] = title
        form_widget = getattr(window, "form_widget", None)
        if form_widget is not None:
            try:
                form_widget.data_changed.connect(window.set_dirty)
            except Exception:
                pass
            try:
                form_widget.list_stats_changed.connect(self._on_list_stats_changed)
            except Exception:
                pass

        def _forget_window(*_args) -> None:
            current = getattr(self, "_form_windows", {}).get(view_id)
            if current is window:
                self._form_windows.pop(view_id, None)
                self._titles.pop(view_id, None)

        window.destroyed.connect(_forget_window)
        window.activate()

    def _close_presented_form(self, view_id: str, *, fallback_view_id: str = "dashboard") -> None:
        window = getattr(self, "_form_windows", {}).get(view_id)
        if window is not None:
            window.close()
            return
        self._select_view(fallback_view_id if fallback_view_id in self._views else "dashboard")

    def _set_presented_form_title(self, view_id: str, title: str) -> None:
        self._titles[view_id] = str(title or "")
        view = self._views.get(view_id)
        if view is not None:
            view.title = str(title or "")  # type: ignore[attr-defined]
            index = self._tab_widget.indexOf(view)
            if index >= 0:
                self._tab_widget.setTabText(index, str(title or ""))
        window = getattr(self, "_form_windows", {}).get(view_id)
        if window is not None:
            window.set_base_title(str(title or ""))

    def _deploy_schema_on_open(self) -> None:
        """Deploy physical data tables via RPC in a background thread. Idempotent."""
        if self._db is None:
            return
        import threading
        db = self._db

        def _run():
            try:
                db._gw.schema_deploy()
            except Exception:
                pass

        threading.Thread(target=_run, daemon=True).start()


    def _load_manifest_structure(self, *, force: bool = False) -> None:
        """Load manifest rows on demand for nav/IDE views."""
        if hasattr(self, "_start_manifest_bootstrap"):
            try:
                self._start_manifest_bootstrap(force=force)  # type: ignore[misc]
            except TypeError:
                self._start_manifest_bootstrap()  # type: ignore[misc]


    def _manifest_rows(self) -> list:
        """Return all manifest rows from the current DB (or empty list)."""
        if self._manifest_rows_cache:
            return list(self._manifest_rows_cache)
        if self._db is None:
            return []
        lock = getattr(self, "_manifest_rows_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._manifest_rows_lock = lock
        if not lock.acquire(blocking=False):
            return []
        try:
            started = time.perf_counter()
            gw = getattr(self._db, "_gw", None)
            if gw is not None and hasattr(gw, "manifest_list"):
                # Startup path: fetch slim rows only. Detailed payload is loaded
                # on demand via _row_payload()/manifest_get_payload().
                self._manifest_rows_cache = gw.manifest_list(slim=True) or []
            else:
                self._manifest_rows_cache = self._db.table("manifest").select() or []
            self._manifest_by_guid_cache = {
                str(r.get("guid") or "").strip(): dict(r)
                for r in self._manifest_rows_cache
                if isinstance(r, dict) and str(r.get("guid") or "").strip()
            }
            logger.info(
                "manifest_rows.loaded rows=%s total=%.3fs",
                len(self._manifest_rows_cache),
                time.perf_counter() - started,
            )
            return list(self._manifest_rows_cache)
        except Exception:
            return []
        finally:
            try:
                lock.release()
            except Exception:
                pass


    def _manifest_refresh_key(self) -> str:
        """Return a lightweight fingerprint of the runtime manifest state."""
        if self._db is None:
            return ""
        try:
            gw = getattr(self._db, "_gw", None)
            if gw is None or not hasattr(gw, "manifest_info"):
                return ""
            info = gw.manifest_info()
        except Exception:
            return ""
        if not isinstance(info, dict) or not info:
            return ""
        parts = [
            str(info.get("db_uid") or ""),
            str(info.get("structure_hash") or ""),
            str(info.get("object_count") or ""),
        ]
        return "|".join(parts)


    def _row_payload(self, row: dict[str, object] | None) -> dict[str, object]:
        """Return payload for a manifest row, fetching from server if slim mode."""
        payload = row.get("payload") if isinstance(row, dict) else None
        if isinstance(payload, dict) and payload:
            return payload
        # slim mode — payload absent, fetch on-demand from server
        guid = str(row.get("guid") or "").strip() if isinstance(row, dict) else ""
        if not guid or self._db is None:
            return {} if not isinstance(payload, dict) else payload
        try:
            gw = getattr(self._db, "_gw", None)
            if gw is not None and hasattr(gw, "manifest_get_payload"):
                fetched = gw.manifest_get_payload(guid)
                if isinstance(fetched, dict) and fetched:
                    row["payload"] = fetched  # cache back so we don't re-fetch
                    return fetched
        except Exception:
            pass
        return {} if not isinstance(payload, dict) else payload


    def _manifest_payload_for_row(self, row: dict[str, object] | None) -> dict[str, object]:
        """Return a hydrated manifest payload for a single manifest row."""
        if not isinstance(row, dict):
            return {}
        payload = dict(self._row_payload(row))
        if not payload:
            return {}
        guid = str(row.get("guid") or "").strip()
        if not guid or self._db is None:
            return payload

        missing = [
            key for key in _STRUCTURE_EXTERNALIZED_KEYS
            if key not in payload and str(payload.get(f"{key}_ref") or "").strip()
        ]
        if not missing:
            return payload

        try:
            gw = getattr(self._db, "_gw", None)
            if gw is not None and hasattr(gw, "manifest_get_payload"):
                fetched = gw.manifest_get_payload(guid)
                if isinstance(fetched, dict) and fetched:
                    payload.update(fetched)
                    row["payload"] = dict(payload)
                    cached = self._manifest_by_guid_cache.get(guid)
                    if isinstance(cached, dict):
                        cached["payload"] = dict(payload)
                    return payload
        except Exception:
            pass
        return payload


    def _module_text_for_payload(self, payload: dict[str, object] | None) -> tuple[str, str]:
        """Resolve module text directly from hydrated payload or module asset refs."""
        if not isinstance(payload, dict) or self._db is None:
            return "", "uk"
        module_payload = payload.get("module") if isinstance(payload.get("module"), dict) else {}
        candidates = [
            str(module_payload.get("asset_key") or "").strip(),
            str(payload.get("module_asset_key") or "").strip(),
            str(payload.get("form_module_ref") or "").strip(),
        ]
        for asset_key in candidates:
            if not asset_key:
                continue
            try:
                data, _mime = self._db.get_asset(asset_key)
                text = data.decode("utf-8")
                if text.strip():
                    lang = str(module_payload.get("lang") or payload.get("module_lang") or "uk").strip().lower() or "uk"
                    return text, lang
            except Exception:
                continue
        return "", "uk"


    def _form_structure_payload(self, guid: str) -> dict[str, object]:
        """Return a hydrated payload bundle for forms/layouts/modules of one object."""
        row = self._manifest_row_by_guid(guid)
        if not isinstance(row, dict):
            return {}
        payload = self._manifest_payload_for_row(row)
        if not isinstance(payload, dict) or not payload:
            return {}
        bundle = dict(payload)
        form_model = payload.get("form_model")
        if isinstance(form_model, dict):
            bundle["form_model"] = form_model
        layout_model = payload.get("layout_model")
        if isinstance(layout_model, dict):
            bundle["layout_model"] = layout_model
        module_text, module_lang = self._module_text_for_payload(payload)
        if module_text.strip():
            bundle["module_text"] = module_text
            bundle["module_lang"] = module_lang
        return bundle

    def _object_context_for_guid(self, guid: str) -> dict[str, object]:
        """Load one object context through Runtime and cache it by GUID."""
        key = str(guid or "").strip()
        if not key or self._db is None:
            return {}
        cache = getattr(self, "_object_context_cache", None)
        if cache is None:
            cache = {}
            self._object_context_cache = cache
        cached = cache.get(key)
        if isinstance(cached, dict):
            return dict(cached)
        try:
            gw = getattr(self._db, "_gw", None)
            if gw is not None and hasattr(gw, "manifest_object_context"):
                context = gw.manifest_object_context(key)
                if isinstance(context, dict) and context:
                    cache[key] = dict(context)
                    return dict(context)
        except Exception:
            logger.exception("client.object_context.failed guid=%s", key)
        # Backward-compatible fallback for old runtime processes.
        row = self._manifest_row_by_guid(key)
        payload = self._manifest_payload_for_row(row) if isinstance(row, dict) else {}
        return {"guid": key, "row": row or {}, "payload": payload, "forms": [], "modules": []}


    @staticmethod
    def _row_title(row: dict[str, object]) -> str:
        """Return localized display title for a manifest row.

        Priority:
          1. payload.synonym  ← localized dict {uk/en} set by configurator
          2. payload.title    ← fallback localized dict
          3. row[title]       ← plain string (row-level, usually Ukrainian)
          4. row[name]        ← internal name
          5. row[guid]
        """
        from src.ui_qt.i18n import get_lang
        lang = get_lang()

        def _resolve(val: object) -> str:
            """Resolve a value that may be a plain string or {uk/en} dict."""
            if isinstance(val, dict):
                for l in (lang, "uk", "en", "ru"):
                    v = str(val.get(l) or "").strip()
                    if v:
                        return v
                for v in val.values():
                    s = str(v or "").strip()
                    if s:
                        return s
                return ""
            return str(val or "").strip()

        # 1. payload.synonym (локалізований синонім з конфігуратора)
        payload = row.get("payload")
        if isinstance(payload, dict):
            v = _resolve(payload.get("synonym"))
            if v:
                return v
            v = _resolve(payload.get("title"))
            if v:
                return v

        # 2. row-level title (plain string — зазвичай з активної мови конфігуратора)
        v = _resolve(row.get("title"))
        if v:
            return v

        # 3. internal name
        v = _resolve(row.get("name"))
        if v:
            return v

        return str(row.get("guid") or "")


    def _manifest_row_by_guid(self, guid: str) -> dict[str, object] | None:
        if not guid:
            return None
        key = str(guid).strip()
        row = self._manifest_by_guid_cache.get(key)
        if isinstance(row, dict):
            return dict(row)
        nav_rows = list(getattr(self, "_manifest_nav_rows_cache", []) or [])
        for candidate in nav_rows:
            if not isinstance(candidate, dict):
                continue
            if str(candidate.get("guid") or "").strip() != key:
                continue
            self._manifest_by_guid_cache[key] = dict(candidate)
            return dict(candidate)
        if self._db is not None:
            try:
                gw = getattr(self._db, "_gw", None)
                if gw is not None and hasattr(gw, "manifest_get_row"):
                    fetched = gw.manifest_get_row(key)
                    if isinstance(fetched, dict) and fetched:
                        self._manifest_by_guid_cache[key] = dict(fetched)
                        return dict(fetched)
            except Exception:
                pass
        return None


    def _manifest_subtree_for_guid(self, guid: str) -> list[dict[str, object]]:
        """Return a hydrated manifest subtree for one object GUID."""
        target = str(guid or "").strip()
        if not target:
            return []
        if self._db is not None:
            try:
                gw = getattr(self._db, "_gw", None)
                if gw is not None and hasattr(gw, "manifest_get_subtree"):
                    rows = gw.manifest_get_subtree(target)
                    return [dict(r) for r in rows if isinstance(r, dict)]
            except Exception:
                pass
        row = self._manifest_row_by_guid(target)
        return [row] if isinstance(row, dict) else []


    def _refresh_runtime_data(self) -> None:
        """Pull fresh manifest data from runtime and refresh top-level views."""
        if self._db is None:
            return
        if not self._manifest_rows_cache:
            return
        if getattr(self, "_manifest_bootstrap_active", False):
            return
        if getattr(self, "_manifest_rows_lock", None) is not None and getattr(self._manifest_rows_lock, "locked", lambda: False)():
            return
        key = self._manifest_refresh_key()
        if not key:
            return
        if key == str(getattr(self, "_manifest_refresh_fingerprint", "") or "") and self._manifest_rows_cache:
            return
        self._manifest_rows_cache = []
        self._manifest_by_guid_cache = {}
        # Object contexts contain hydrated form models and module ownership;
        # invalidate them together with the manifest generation.
        getattr(self, "_object_context_cache", {}).clear()
        self._load_manifest_structure(force=True)
        # The bootstrap thread will rebuild the navigation tree and refresh
        # visible views once the manifest rows are loaded again.
        return


    def _load_form_module_text(
        self, obj_guid: str, form_kind: str, extra_owner_guids: list[str] | None = None,
        *, context: dict[str, object] | None = None,
    ) -> tuple[str, str]:
        """Load form module source text from cfg_modules. Returns (text, language)."""
        if self._db is None:
            return "", "uk"
        try:
            context_modules = context.get("modules") if isinstance(context, dict) else None
            if isinstance(context_modules, list):
                candidates = [item for item in context_modules if isinstance(item, dict)]
                target = str(form_kind or "").strip().casefold()
                form_owner_guids: set[str] = set()
                for item in context.get("forms") or []:
                    if not isinstance(item, dict):
                        continue
                    item_payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
                    item_guid = str(item.get("guid") or "").strip()
                    if item_guid and str(item_payload.get("subtype") or "").strip().casefold() == target:
                        form_owner_guids.add(item_guid)
                selected = next(
                    (item for item in candidates
                     if str(item.get("module_kind") or "").strip().casefold() == "form_module"
                     and str(item.get("owner_guid") or "").strip() in (form_owner_guids or {str(obj_guid or "").strip()})),
                    None,
                )
                if selected is None:
                    selected = next(
                        (item for item in candidates
                         if str(item.get("module_kind") or "").strip().casefold() == "form_module"
                         and str(item.get("name") or "").strip().casefold() in {target, target.replace("_", "")}),
                        None,
                    )
                if isinstance(selected, dict):
                    module_guid = str(selected.get("module_guid") or "").strip()
                    gw = getattr(self._db, "_gw", None)
                    if module_guid and gw is not None and hasattr(gw, "module_get_text"):
                        text = gw.module_get_text(module_guid)
                        if str(text or "").strip():
                            return str(text), str(selected.get("lang") or "uk").strip().lower() or "uk"

            from src.configurator.persistence.modules_tables import MODULES_TABLE, ensure_modules_tables
            from src.configurator.persistence.modules_dao import get_module_text

            try:
                ensure_modules_tables(self._db)
            except Exception:
                return "", "uk"

            tbl = self._db.table(MODULES_TABLE)
            search_guids = [obj_guid] + list(extra_owner_guids or [])
            all_candidates: list[dict] = []
            for owner_guid in search_guids:
                rows = tbl.select(where={"owner_guid": owner_guid, "module_kind": "form_module"}) or []
                all_candidates.extend(rows)

            if not all_candidates:
                return "", "uk"

            row: dict | None = None
            fk_lower = form_kind.lower()
            for c in all_candidates:
                cname = str(c.get("name") or "").lower()
                if cname in (fk_lower, fk_lower.replace("_", "")):
                    row = c
                    break
            if row is None:
                row = all_candidates[0]

            text = get_module_text(self._db, module_guid=str(row.get("module_guid") or ""))
            lang = str(row.get("lang") or "uk").strip().lower() or "uk"
            return text, lang
        except Exception:
            return "", "uk"


    def _manifest_nav_rows(self) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
        rows: list[dict[str, object]] = []
        if self._db is not None:
            try:
                gw = getattr(self._db, "_gw", None)
                if gw is not None and hasattr(gw, "manifest_nav"):
                    rows = [r for r in gw.manifest_nav() if isinstance(r, dict)]
            except Exception:
                rows = []
        if not rows:
            rows = [
                r for r in getattr(self, "_manifest_nav_rows_cache", [])
                if isinstance(r, dict)
            ]
        if not rows:
            rows = [
                r for r in getattr(self, "_manifest_rows_cache", [])
                if isinstance(r, dict)
            ]
        user_rows: list[dict[str, object]] = []
        subsystem_rows: list[dict[str, object]] = []
        report_rows: list[dict[str, object]] = []
        for row in rows:
            kind = str(row.get("kind") or "").lower()
            type_name = str(row.get("type") or "").lower()
            if kind != "object":
                continue
            # Use inline payload only — avoid per-row RPC calls during nav build.
            # system flag is always stored inline; large keys (attributes, objects)
            # are externalized but not needed here.
            inline_payload = row.get("payload") if isinstance(row, dict) else {}
            if not isinstance(inline_payload, dict):
                inline_payload = {}
            if inline_payload.get("system"):
                continue
            payload = inline_payload
            if type_name == "subsystem":
                subsystem_rows.append(row)
                continue
            if type_name == "report":
                report_rows.append(row)
            if type_name in {"catalog", "document", "report", "register_accum", "register_info"}:
                user_rows.append(row)
        return user_rows, subsystem_rows, report_rows


    def _configuration_manifest_row(self) -> dict[str, object] | None:
        try:
            from src.configurator.persistence.manifest_io import _sys_guid
        except Exception:
            _sys_guid = None

        if _sys_guid is not None:
            try:
                root_row = self._manifest_row_by_guid(_sys_guid("root:configuration"))
                if isinstance(root_row, dict) and str(root_row.get("type") or "").strip().lower() == "configuration":
                    return dict(root_row)
            except Exception:
                pass

        rows = list(getattr(self, "_manifest_rows_cache", []) or [])
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("type") or "").strip().lower() == "configuration":
                return dict(row)
        return None


    def _object_ref_for_row(self, row: dict[str, object] | None) -> str:
        if not isinstance(row, dict):
            return ""
        obj_type = str(row.get("type") or "").strip().lower()
        name = str(row.get("name") or "").strip()
        root = _OBJECT_REF_ROOTS.get(obj_type, "")
        if not root or not name:
            return ""
        return f"{root}.{name}"


    def _current_user_candidate_ids(self) -> list[str]:
        candidates: list[str] = []
        for raw in (
            os.environ.get("META_USER_ID", ""),
            os.environ.get("META_USER_LOGIN", ""),
            getpass.getuser(),
            "system",
        ):
            value = str(raw or "").strip()
            if not value:
                continue
            if value not in candidates:
                candidates.append(value)
        return candidates


    def _current_user_row(self) -> dict[str, object] | None:
        if self._db is None:
            return None
        try:
            rows = self._db.table(USERS_TABLE).select() or []
        except Exception:
            return None
        if not rows:
            return None
        candidates = self._current_user_candidate_ids()
        for candidate in candidates:
            key = candidate.casefold()
            for row in rows:
                if not isinstance(row, dict):
                    continue
                user_id = str(row.get("user_id") or "").strip()
                login = str(row.get("login") or "").strip()
                if key in {user_id.casefold(), login.casefold()}:
                    return dict(row)
        for row in rows:
            if isinstance(row, dict) and str(row.get("login") or "").strip().casefold() == "system":
                return dict(row)
        return dict(rows[0]) if isinstance(rows[0], dict) else None


    def _current_user_role_names(self) -> list[str]:
        if self._db is None:
            return []
        user_row = self._current_user_row()
        if not isinstance(user_row, dict):
            return []
        user_keys = {
            str(user_row.get("user_id") or "").strip(),
            str(user_row.get("login") or "").strip(),
        }
        user_keys = {item for item in user_keys if item}
        if not user_keys:
            return []
        try:
            role_links = self._db.table(USER_ROLES_TABLE).select() or []
            roles = self._db.table(ROLES_TABLE).select() or []
        except Exception:
            return []

        role_ids = {
            str(link.get("role_id") or "").strip()
            for link in role_links
            if isinstance(link, dict) and str(link.get("user_id") or "").strip() in user_keys
        }
        role_name_by_id = {
            str(role.get("role_id") or "").strip(): str(role.get("name") or "").strip()
            for role in roles
            if isinstance(role, dict) and str(role.get("role_id") or "").strip()
        }
        out: list[str] = []
        for role_id in role_ids:
            name = role_name_by_id.get(role_id, "").strip()
            if name and name not in out:
                out.append(name)
        return out


    def _role_manifest_rows(self) -> list[dict[str, object]]:
        rows = list(getattr(self, "_manifest_rows_cache", []) or [])
        if not rows and self._db is not None:
            try:
                gw = getattr(self._db, "_gw", None)
                if gw is not None and hasattr(gw, "manifest_list"):
                    rows = [r for r in gw.manifest_list(slim=True) if isinstance(r, dict) and str(r.get("type") or "").strip().lower() == "role"]
                else:
                    rows = self._db.table("manifest").select(where={"type": "role"}) or []
            except Exception:
                rows = []
        role_names = {name.casefold() for name in self._current_user_role_names()}
        if not role_names:
            return []
        out: list[dict[str, object]] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("type") or "").strip().lower() != "role":
                continue
            name = str(row.get("name") or "").strip()
            title = str(row.get("title") or "").strip()
            if name.casefold() not in role_names and title.casefold() not in role_names:
                continue
            guid = str(row.get("guid") or "").strip()
            if not guid or guid in seen:
                continue
            seen.add(guid)
            out.append(dict(row))
        return out


    def _role_allows_object_right(self, role_row: dict[str, object], object_ref: str, required_rights: tuple[str, ...]) -> bool:
        if not isinstance(role_row, dict):
            return False
        payload = self._manifest_payload_for_row(role_row)
        rights = payload.get("rights") if isinstance(payload, dict) else []
        if not isinstance(rights, list):
            return False
        required = {str(item or "").strip().casefold() for item in required_rights if str(item or "").strip()}
        object_key = str(object_ref or "").strip().casefold()
        for entry in rights:
            if not isinstance(entry, dict):
                continue
            entry_object = str(entry.get("object") or "").strip().casefold()
            if not entry_object or entry_object != object_key:
                continue
            rights_map = entry.get("rights") if isinstance(entry.get("rights"), dict) else {}
            for right_name, enabled in rights_map.items():
                if not bool(enabled):
                    continue
                if str(right_name or "").strip().casefold() in required:
                    return True
        return False


    def _can_access_row(self, row: dict[str, object] | None, *, action: str = "open") -> bool:
        if not isinstance(row, dict):
            return False
        role_names = {name.casefold() for name in self._current_user_role_names()}
        if role_names & {"admin", "configmaintainer"}:
            return True
        object_ref = self._object_ref_for_row(row)
        if not object_ref:
            return True
        obj_type = str(row.get("type") or "").strip().lower()
        required: tuple[str, ...]
        action_key = str(action or "").strip().lower()
        if action_key in {"create", "new", "copy"}:
            required = ("Insert", "Create", "Write", "Update")
        elif action_key in {"edit", "save", "write"}:
            required = ("Write", "Update", "Read")
        elif action_key in {"delete", "remove"}:
            required = ("Delete",)
        elif action_key in {"post"}:
            required = ("Posting",)
        elif action_key in {"unpost"}:
            required = ("UndoPosting",)
        elif action_key in {"execute", "report", "print"}:
            required = ("Execute", "Use", "Read")
        else:
            required = ("Read", "Use", "Execute")
        if obj_type in {"report"}:
            required = ("Execute", "Use", "Read")
        if obj_type in {"role"}:
            required = ("Read", "Use", "Execute")
        for role_row in self._role_manifest_rows():
            if self._role_allows_object_right(role_row, object_ref, required):
                return True
        # No explicit restriction found: keep legacy permissive behavior.
        return True


    def _deny_access(self, title: str, obj_title: str) -> None:
        QMessageBox.warning(self, title, t("client_err_access_denied").format(title=obj_title))


    def _module_text_for_owner(
        self,
        owner_guid: str,
        module_name: str = "",
        *,
        module_kind: str = "",
    ) -> tuple[str, str, str]:
        """Resolve module source text for a manifest owner."""
        if self._db is None:
            return "", "uk", ""
        try:
            gw = getattr(self._db, "_gw", None)
            if gw is not None and hasattr(gw, "modules_list_by_owner"):
                rows = gw.modules_list_by_owner(str(owner_guid or "").strip()) or []
                selected = None
                target_name = str(module_name or "").strip().casefold()
                target_kind = str(module_kind or "").strip().casefold()
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    if target_kind and str(row.get("module_kind") or "").strip().casefold() != target_kind:
                        continue
                    if target_name and str(row.get("name") or "").strip().casefold() != target_name:
                        continue
                    selected = row
                    break
                if selected is None:
                    selected = next((row for row in rows if isinstance(row, dict)), None)
                if isinstance(selected, dict):
                    module_guid = str(selected.get("module_guid") or "").strip()
                    if module_guid and hasattr(gw, "module_get_text"):
                        return (
                            str(gw.module_get_text(module_guid) or ""),
                            str(selected.get("lang") or "uk").strip().lower() or "uk",
                            module_guid,
                        )

            from src.configurator.persistence.modules_tables import MODULES_TABLE, ensure_modules_tables
            from src.configurator.persistence.modules_dao import get_module_text

            ensure_modules_tables(self._db)
            tbl = self._db.table(MODULES_TABLE)
            rows = tbl.select(where={"owner_guid": str(owner_guid or "").strip()}) or []
            if not rows:
                return "", "uk", ""

            selected: dict | None = None
            target_name = str(module_name or "").strip().lower()
            target_kind = str(module_kind or "").strip().lower()
            for row in rows:
                if target_kind and str(row.get("module_kind") or "").strip().lower() != target_kind:
                    continue
                if target_name and str(row.get("name") or "").strip().lower() != target_name:
                    continue
                selected = row
                break
            if selected is None:
                selected = rows[0]

            module_guid = str(selected.get("module_guid") or "").strip()
            if not module_guid:
                return "", str(selected.get("lang") or "uk").strip().lower() or "uk", ""

            text = get_module_text(self._db, module_guid=module_guid)
            lang = str(selected.get("lang") or "uk").strip().lower() or "uk"
            return text, lang, module_guid
        except Exception:
            return "", "uk", ""


    def _module_text_for_guid(self, module_guid: str) -> tuple[str, str, str]:
        """Load one ``module://`` target through the runtime-backed DB facade."""
        module_guid = str(module_guid or "").strip()
        if not module_guid or self._db is None:
            return "", "uk", module_guid
        try:
            gw = getattr(self._db, "_gw", None)
            if gw is not None and hasattr(gw, "module_get_text"):
                return str(gw.module_get_text(module_guid) or ""), "uk", module_guid

            from src.configurator.persistence.modules_dao import get_module_text_from_row
            from src.configurator.persistence.modules_tables import MODULES_TABLE

            rows = self._db.table(MODULES_TABLE).select(where={"module_guid": module_guid}) or []
            module_row = next((item for item in rows if isinstance(item, dict)), None)
            if not isinstance(module_row, dict):
                return "", "uk", module_guid
            text = get_module_text_from_row(self._db, module_row)
            lang = str(module_row.get("lang") or "uk").strip().lower() or "uk"
            return text, lang, module_guid
        except Exception:
            return "", "uk", module_guid


    @staticmethod
    def _parse_startup_module_refs(value: object) -> list[str]:
        refs: list[str] = []
        if isinstance(value, list):
            items = value
        elif isinstance(value, dict):
            items = (
                value.get("startup_modules")
                or value.get("modules")
                or value.get("refs")
                or value.get("items")
                or value.values()
            )
        elif isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = None
            if isinstance(parsed, (list, dict)):
                return ClientWindowRuntimeMixin._parse_startup_module_refs(parsed)
            items = [chunk.strip() for chunk in text.replace("\n", ",").split(",")]
        else:
            return []

        for item in items:
            if isinstance(item, str):
                ref = item.strip()
            elif isinstance(item, dict):
                ref = str(
                    item.get("asset_key")
                    or item.get("module_asset_key")
                    or item.get("guid")
                    or item.get("module_guid")
                    or item.get("ref")
                    or item.get("name")
                    or item.get("title")
                    or ""
                ).strip()
            else:
                ref = str(item or "").strip()
            if ref.startswith("module://"):
                ref = ref.split("://", 1)[1].strip()
            if ref:
                refs.append(ref)
        # preserve order but drop duplicates
        out: list[str] = []
        seen: set[str] = set()
        for ref in refs:
            key = ref.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(ref)
        return out


    @staticmethod
    def _bind_startup_cancel_parameter(source: str, entry: str) -> str:
        """Bind the conventional pre-start parameter to the persistent context.

        The shared VM currently treats procedure parameters as local values.  A
        declaration such as ``BeforeApplicationStart(Cancel)`` would therefore
        hide the context flag inspected by the client.  Removing only that
        conventional parameter at compile time preserves source line numbers
        while making assignments observable by the startup coordinator.
        """
        text = str(source or "")
        entry = str(entry or "").strip()
        if not text or not entry:
            return text
        pattern = re.compile(
            rf"(?im)^(?P<prefix>[ \t]*(?:Procedure|Процедура)[ \t]+{re.escape(entry)}[ \t]*)"
            r"\((?P<params>[^)\r\n]*)\)",
        )
        cancel_names = {"cancel", "отказ", "відмова"}

        def _replace(match: re.Match[str]) -> str:
            params = str(match.group("params") or "").strip()
            if not params or "," in params:
                return match.group(0)
            declaration = params.split("=", 1)[0].strip()
            parts = declaration.split()
            if len(parts) > 1 and parts[0].casefold() in {"знач", "value", "значення"}:
                declaration = parts[-1]
            if declaration.casefold() not in cancel_names:
                return match.group(0)
            return f"{match.group('prefix')}()"

        return pattern.sub(_replace, text, count=1)


    def _startup_manifest_rows(self) -> list[dict[str, object]]:
        """Return manifest rows referenced by configuration startup properties."""
        config_row = self._configuration_manifest_row()
        if not isinstance(config_row, dict):
            return []
        payload = config_row.get("payload") if isinstance(config_row.get("payload"), dict) else {}
        if not isinstance(payload, dict):
            payload = {}

        refs: list[str] = []
        for key in _STARTUP_MODULE_PAYLOAD_KEYS:
            refs.extend(self._parse_startup_module_refs(payload.get(key)))

        if not refs:
            # ``manifest.get_row`` is intentionally slim.  Fetch only the root
            # payload instead of forcing manifest.list for the whole database.
            config_payload: dict[str, object] = {}
            config_guid = str(config_row.get("guid") or "").strip()
            try:
                gw = getattr(self._db, "_gw", None) if self._db is not None else None
                if config_guid and gw is not None and hasattr(gw, "manifest_get_payload"):
                    fetched = gw.manifest_get_payload(config_guid)
                    if isinstance(fetched, dict):
                        config_payload = dict(fetched)
            except Exception:
                config_payload = {}
            if not config_payload:
                config_payload = self._manifest_payload_for_row(config_row)
            if isinstance(config_payload, dict):
                for key in _STARTUP_MODULE_PAYLOAD_KEYS:
                    refs.extend(self._parse_startup_module_refs(config_payload.get(key)))
            if not refs:
                rows = list(getattr(self, "_manifest_rows_cache", []) or [])
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("type") or "").strip().lower() != "common_module":
                        continue
                    row_payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
                    if not isinstance(row_payload, dict):
                        row_payload = {}
                    if row_payload.get("system"):
                        continue
                    name = str(row.get("name") or "").strip()
                    title = str(row.get("title") or "").strip()
                    if name.casefold() in {"appmodule", "модульпрограми"} or title.casefold() in {"appmodule", "модульпрограми"}:
                        refs.append(str(row.get("guid") or "").strip())
                        break

        if not refs:
            return []

        rows = list(getattr(self, "_manifest_rows_cache", []) or [])

        by_guid = {
            str(row.get("guid") or "").strip(): row
            for row in rows
            if isinstance(row, dict) and str(row.get("guid") or "").strip()
        }
        by_name = {
            str(row.get("name") or "").strip().casefold(): row
            for row in rows
            if isinstance(row, dict)
            and str(row.get("type") or "").strip().lower() == "common_module"
            and str(row.get("name") or "").strip()
        }

        out: list[dict[str, object]] = []
        seen: set[str] = set()
        for ref in refs:
            row = by_guid.get(ref)
            module_guid = ""
            if row is None:
                row = by_name.get(ref.casefold())
            if row is None and self._db is not None:
                try:
                    # Startup resolution must also work through GatewayDb.
                    # Do not call the local schema bootstrap here: it expects
                    # an Mpdb handle and silently discarded remote modules.
                    from src.configurator.persistence.modules_tables import MODULES_TABLE

                    module_rows = self._db.table(MODULES_TABLE).select(where={"module_guid": ref}) or []
                    module_row = next((item for item in module_rows if isinstance(item, dict)), None)
                    if isinstance(module_row, dict):
                        owner_guid = str(module_row.get("owner_guid") or "").strip()
                        owner_row = by_guid.get(owner_guid) if owner_guid else None
                        row = dict(owner_row) if isinstance(owner_row, dict) else {
                            "guid": owner_guid or ref,
                            "type": "common_module",
                            "kind": "object",
                            "name": str(module_row.get("name") or module_row.get("module_kind") or ref),
                            "title": str(module_row.get("name") or module_row.get("module_kind") or ref),
                            "payload": {},
                        }
                        module_guid = str(module_row.get("module_guid") or ref).strip()
                except Exception:
                    row = None
            if not isinstance(row, dict):
                continue
            if str(row.get("type") or "").strip().lower() != "common_module":
                continue
            row_payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            if isinstance(row_payload, dict) and row_payload.get("system"):
                continue
            if module_guid:
                row = dict(row)
                payload = dict(row_payload or {})
                payload["_startup_module_guid"] = module_guid
                row["payload"] = payload
            guid = str(row.get("guid") or "").strip()
            identity = module_guid or guid
            if not guid or not identity or identity in seen:
                continue
            seen.add(identity)
            out.append(dict(row))
        return out


    @staticmethod
    def _startup_entries_for_phase(phase: str) -> tuple[str, ...]:
        phase = str(phase or "").strip().lower()
        if phase == "pre":
            return (
                "ПередНачаломРаботыСистемы",
                "ПередПочаткомРоботиСистеми",
                "BeforeApplicationStart",
                "BeforeSystemStart",
            )
        return (
            "ПриНачалеРаботыСистемы",
            "ПриПочаткуРоботиСистеми",
            "OnSystemStartup",
            "Main",
            "Головна",
        )


    def _startup_debug_session(self):
        session = getattr(self, "_startup_debug_session_cache", None)
        if session is not None:
            return session
        try:
            session = create_debug_session_from_env()
        except Exception:
            session = None
        self._startup_debug_session_cache = session
        return session


    def _resolve_startup_common_module(self, name: str) -> dict[str, object] | None:
        """Resolve one imported common module through Runtime RPC on demand."""

        if self._db is None:
            return None
        target = str(name or "").strip()
        if not target:
            return None
        try:
            gateway = getattr(self._db, "_gw", None)
            if gateway is not None and hasattr(gateway, "module_resolve"):
                resolved = gateway.module_resolve(target)
                return dict(resolved) if isinstance(resolved, dict) and resolved else None
        except Exception as exc:
            logger.info("startup.common_module.resolve_failed name=%r error=%s", target, exc)
            return None
        try:
            from src.configurator.persistence.modules_dao import resolve_common_module

            resolved = resolve_common_module(self._db, name=target)
            return dict(resolved) if isinstance(resolved, dict) and resolved else None
        except Exception as exc:
            logger.info("startup.common_module.resolve_failed name=%r error=%s", target, exc)
            return None


    def _resolve_startup_metadata_rows(self, type_name: str) -> list[dict[str, object]]:
        if self._db is None:
            return []
        try:
            gateway = getattr(self._db, "_gw", None)
            if gateway is not None and hasattr(gateway, "manifest_lookup"):
                return [
                    dict(row)
                    for row in gateway.manifest_lookup(type_name=str(type_name or ""), limit=5000)
                    if isinstance(row, dict)
                ]
        except Exception as exc:
            logger.info("startup.metadata.lookup_failed type=%r error=%s", type_name, exc)
        return []


    def _run_startup_modules(self, *, phase: str = "post") -> bool:
        """Run application startup procedures once per manifest fingerprint.

        ``phase='pre'`` is executed before the post-startup phase. The client
        schedules it after the first window paint so slow user code cannot make
        the process appear to fail during launch.
        ``phase='post'`` is executed after the navigation/manifest bootstrap.
        """
        if self._db is None:
            return True
        phase = str(phase or "post").strip().lower()
        if phase not in {"pre", "post"}:
            phase = "post"
        fingerprint = self._manifest_refresh_key()
        if not fingerprint:
            fingerprint = str(getattr(self, "_manifest_refresh_fingerprint", "") or "")
        if not fingerprint:
            fingerprint = "startup"
        fingerprints = getattr(self, "_startup_modules_fingerprints", {})
        if not isinstance(fingerprints, dict):
            fingerprints = {}
        if fingerprints.get(phase) == fingerprint:
            return True

        rows = self._startup_manifest_rows()
        if not rows:
            fingerprints[phase] = fingerprint
            self._startup_modules_fingerprints = fingerprints
            return True

        from src.runtime.script.vm import execute_script

        globals_patch = build_global_context(self._db)
        metadata_proxy = _MetadataProxy(
            rows,
            self._configuration_manifest_row(),
            resolver=self._resolve_startup_metadata_rows,
        )
        globals_patch["Метаданные"] = metadata_proxy
        globals_patch["Метадані"] = metadata_proxy
        globals_patch["Metadata"] = metadata_proxy
        try:
            gw = getattr(self._db, "_gw", None)
            raw_db = getattr(gw, "db", None) if gw is not None else None
        except Exception:
            raw_db = None
        if raw_db is not None:
            globals_patch["DB"] = raw_db
            globals_patch["БД"] = raw_db

        entries = self._startup_entries_for_phase(phase)
        debug_session = self._startup_debug_session()
        startup_contexts = getattr(self, "_startup_module_contexts", None)
        if not isinstance(startup_contexts, dict):
            startup_contexts = {}
            self._startup_module_contexts = startup_contexts
        shared_context = getattr(self, "_startup_shared_context", None)
        if not isinstance(shared_context, dict):
            shared_context = next(
                (item for item in startup_contexts.values() if isinstance(item, dict)),
                None,
            )
        if not isinstance(shared_context, dict):
            shared_context = dict(globals_patch)
        self._startup_shared_context = shared_context
        for key, value in globals_patch.items():
            shared_context.setdefault(key, value)
        shared_context.setdefault("Cancel", False)
        shared_context.setdefault("Отказ", False)
        shared_context.setdefault("Відмова", False)
        registry_fingerprint = getattr(self, "_startup_common_module_registry_fingerprint", "")
        common_modules = getattr(self, "_startup_common_module_registry", None)
        if not isinstance(common_modules, CommonModuleRegistry) or registry_fingerprint != fingerprint:
            common_modules = CommonModuleRegistry(
                self._resolve_startup_common_module,
                shared_context=shared_context,
                extra_builtins=globals_patch,
                debug_session=debug_session,
            )
            self._startup_common_module_registry = common_modules
            self._startup_common_module_registry_fingerprint = fingerprint
        for row in rows:
            owner_guid = str(row.get("guid") or "").strip()
            owner_name = str(row.get("name") or "").strip()
            title = str(row.get("title") or owner_name or owner_guid).strip()
            row_payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            direct_module_guid = str(row_payload.get("_startup_module_guid") or "").strip() if isinstance(row_payload, dict) else ""
            if direct_module_guid:
                text, lang, module_guid = self._module_text_for_guid(direct_module_guid)
            else:
                text, lang, module_guid = self._module_text_for_owner(owner_guid, owner_name)
            if not text.strip():
                continue
            module_name = f"module://{module_guid or owner_guid}"
            ctx = shared_context
            startup_contexts[module_name] = ctx
            for entry in entries:
                common_modules.install_source_names(ctx, text)
                executable_text = self._bind_startup_cancel_parameter(text, entry) if phase == "pre" else text
                result, errors = execute_script(
                    executable_text,
                    language=lang or "uk",
                    entry=entry,
                    extra_builtins=globals_patch,
                    context=ctx,
                    module_name=module_name,
                    debug_session=debug_session,
                    strict_entry=True,
                )
                if errors:
                    logger.info(
                        "startup.module.failed guid=%s title=%r entry=%s errors=%s",
                        owner_guid,
                        title,
                        entry,
                        errors[:3],
                    )
                    continue
                if phase == "pre" and (
                    bool(ctx.get("Cancel"))
                    or bool(ctx.get("Отказ"))
                    or bool(ctx.get("Відмова"))
                    or bool(result)
                ):
                    fingerprints[phase] = fingerprint
                    self._startup_modules_fingerprints = fingerprints
                    logger.info(
                        "startup.module.cancelled guid=%s title=%r entry=%s",
                        owner_guid,
                        title,
                        entry,
                    )
                    return False
                logger.info(
                    "startup.module.ran guid=%s title=%r entry=%s result=%r",
                    owner_guid,
                    title,
                    entry,
                    result,
                )
                break
        fingerprints[phase] = fingerprint
        self._startup_modules_fingerprints = fingerprints
        return True


    def _build_runtime_form_view(
        self, *, title: str, guid: str, model: dict,
        ctx: ObjContext | None = None,
    ) -> QWidget:
        host = QWidget()
        l = QVBoxLayout(host)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(0)

        owner_row = self._manifest_row_by_guid(guid)
        if isinstance(owner_row, dict):
            owner_row = dict(owner_row)
            owner_row["payload"] = self._manifest_payload_for_row(owner_row)
        manifest = [owner_row] if isinstance(owner_row, dict) else []
        structure_payload = self._form_structure_payload(guid)
        if not structure_payload:
            row = self._manifest_row_by_guid(guid)
            if isinstance(row, dict):
                structure_payload = self._manifest_payload_for_row(row)

        def on_command(code: str) -> None:
            form_ctx = ctx or ObjContext(obj_guid=guid, obj_title=title)
            self._dispatch_runtime_command(
                code, form_guid=guid, form_widget=w,
                doc_name=str(form_ctx.obj_name or ""),
            )

        w = FormRuntimeWidget(
            model=model,
            db=self._db,
            ctx=ctx or ObjContext(obj_guid=guid, obj_title=title),
            manifest_rows=manifest,
            on_command=on_command,
            embedded=False,
            parent=host,
        )
        w.reference_open_requested.connect(self._open_reference_record)
        # Store reference for dispatch
        host._form_widget = w      # type: ignore[attr-defined]
        host._doc_name    = str((ctx.obj_name if ctx else "") or "")   # type: ignore[attr-defined]
        mode_tabs = QTabWidget(host)
        mode_tabs.setObjectName("ClientFormTabs")
        mode_tabs.setDocumentMode(True)
        mode_tabs.addTab(w, title)
        inspector = StructureInspectorWidget(
            title=title,
            guid=guid,
            payload=structure_payload if isinstance(structure_payload, dict) else {},
            parent=mode_tabs,
        )
        mode_tabs.addTab(inspector, t("client_structure_tab"))

        l.addWidget(mode_tabs, 1)
        self._titles[f"form:{guid}"] = title
        return host


    def _build_structure_inspector_view(self, *, title: str, guid: str) -> QWidget:
        host = QWidget()
        l = QVBoxLayout(host)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(0)

        row = self._manifest_row_by_guid(guid)
        payload = self._manifest_payload_for_row(row) if isinstance(row, dict) else {}
        if isinstance(payload, dict):
            structure_payload = dict(payload)
        else:
            structure_payload = {}
        if isinstance(row, dict) and not structure_payload:
            structure_payload = dict(row.get("payload") or {}) if isinstance(row.get("payload"), dict) else {}
        if isinstance(structure_payload, dict) and not structure_payload.get("module_text"):
            module_text, module_lang = self._module_text_for_payload(structure_payload)
            if module_text.strip():
                structure_payload["module_text"] = module_text
                structure_payload["module_lang"] = module_lang

        inspector = StructureInspectorWidget(
            title=title,
            guid=guid,
            payload=structure_payload,
            parent=host,
        )
        l.addWidget(inspector, 1)
        self._titles[f"struct:{guid}"] = title
        return host


    def _open_structure_for_guid(self, guid: str) -> None:
        """Open or focus a dedicated structure inspector for a manifest object."""
        target = str(guid or "").strip()
        if not target:
            return
        row = self._manifest_row_by_guid(target)
        if not isinstance(row, dict):
            return
        title = str(row.get("title") or row.get("name") or target)
        view_id = f"struct:{target}"
        if view_id not in self._views:
            view = self._build_structure_inspector_view(title=title, guid=target)
            if hasattr(self, "_register_view"):
                self._register_view(view_id, view)
            else:
                self._views[view_id] = view
                self._titles[view_id] = title
        if hasattr(self, "_select_view"):
            self._select_view(view_id)


    def _payload_form_model(self, payload: dict) -> Optional[Dict]:
        if not isinstance(payload, dict):
            return None
        model = payload.get("form_model")
        if isinstance(model, dict) and model:
            return model
        ref = str(payload.get("form_model_ref") or "").strip()
        if not ref or self._db is None:
            return None
        try:
            data, _mime = self._db.get_asset(ref)
            loaded = json.loads(data.decode("utf-8"))
            if isinstance(loaded, dict) and loaded:
                return loaded
        except Exception:
            return None
        return None


    def _dispatch_runtime_command(
        self, code: str, *, form_guid: str,
        form_widget=None, doc_name: str = "",
    ) -> bool | None:
        c = str(code or "").strip().lower()
        if not c:
            return

        # ── Navigation ────────────────────────────────────────────────────
        if c in ("close", "closeform", "form.close"):
            self._close_presented_form(f"form:{form_guid}")
            return

        if c in ("back", "form.back"):
            # Try to go back to list view
            if doc_name:
                for view_id in list(self._views):
                    if view_id.startswith(("catalog_list:", "doc_journal:")):
                        self._close_presented_form(f"form:{form_guid}", fallback_view_id=view_id)
                        self._select_view(view_id)
                        return
            self._close_presented_form(f"form:{form_guid}")
            return

        # ── Refresh ───────────────────────────────────────────────────────
        if c in ("refresh", "form.refresh"):
            try:
                row   = self._manifest_row_by_guid(form_guid)
                pay   = self._manifest_payload_for_row(row) if isinstance(row, dict) else {}
                model = self._payload_form_model(pay) if isinstance(pay, dict) else None
                if isinstance(model, dict):
                    view_id = f"form:{form_guid}"
                    title   = str(row.get("title") or row.get("name") or form_guid) if isinstance(row, dict) else form_guid
                    # Preserve record data across refresh
                    rec = {}
                    if form_widget is not None:
                        rec = form_widget.collect()
                    old = self._views.get(view_id)
                    if old:
                        old_index = self._tab_widget.indexOf(old)
                        if old_index >= 0:
                            self._tab_widget.removeTab(old_index)
                        self._views.pop(view_id, None)
                        old.deleteLater()
                    old_window = getattr(self, "_form_windows", {}).pop(view_id, None)
                    if old_window is not None:
                        old_window.discard_and_close()
                    new_host = self._build_runtime_form_view(
                        title=title, guid=form_guid, model=model, ctx=None)
                    new_form = getattr(new_host, "_form_widget", None)
                    if rec and new_form is not None:
                        new_form.set_record(rec)
                    self._present_form(
                        view_id=view_id,
                        widget=new_host,
                        title=title,
                        model=model,
                        owner_type=str(row.get("type") or "") if isinstance(row, dict) else "",
                    )
            except Exception:
                pass
            return

        # ── Save ──────────────────────────────────────────────────────────
        if c in ("save", "form.save", "writeobject"):
            if self._db is None or form_widget is None:
                QMessageBox.warning(self, t("dlg_error_title"), t("client_status_no_db"))
                return
            try:
                rec = form_widget.collect()
                if not doc_name:
                    return
                import uuid as _uuid
                tbl_name = infer_data_table_name(doc_name, rec)
                guid_val = str(rec.get("_guid") or "")
                is_new   = not guid_val
                if is_new:
                    rec["_guid"]    = str(_uuid.uuid4())
                    rec["_deleted"] = False
                    if doc_name and infer_data_table_name(doc_name, rec).startswith("data_catalog_"):
                        rec.setdefault("_predefined", False)
                        rec.setdefault("_is_folder", False)
                    if doc_name and infer_data_table_name(doc_name, rec).startswith("data_document_"):
                        rec.setdefault("_posted", False)
                    self._db.table(tbl_name).insert(rec)
                else:
                    if self._db.table(tbl_name).update({"_guid": guid_val}, rec) != 1:
                        raise RuntimeError("Document record was not saved: missing or ambiguous GUID")
                self.statusBar().showMessage(t("status_saved"), 3000)
                form_widget.set_record(rec)
                direct_window = getattr(self, "_form_windows", {}).get(f"form:{form_guid}")
                if direct_window is not None:
                    direct_window.clear_dirty()
                return True
            except Exception as e:
                QMessageBox.warning(self, t("dlg_error_title"), str(e))
                return False

        # ── Save & Close ──────────────────────────────────────────────────
        if c in ("saveandclose", "form.saveandclose"):
            saved = self._dispatch_runtime_command(
                "save", form_guid=form_guid,
                form_widget=form_widget, doc_name=doc_name)
            if saved is not True:
                return False
            self._close_presented_form(f"form:{form_guid}")
            return True

        # ── Post / Unpost ─────────────────────────────────────────────────
        if c in ("post", "form.post"):
            if self._db is None or form_widget is None:
                return
            try:
                rec = form_widget.collect()
                doc_guid_val = str(rec.get("_guid") or "")
                direct_window = getattr(self, "_form_windows", {}).get(f"form:{form_guid}")
                if direct_window is not None and direct_window.is_dirty:
                    QMessageBox.warning(self, t("dlg_error_title"), t("client_post_save_changes"))
                    return
                if not doc_guid_val or not doc_name:
                    QMessageBox.warning(self, t("dlg_error_title"), t("client_err_save_first"))
                    return
                result = self._db.document_post(
                    doc_name=doc_name, doc_guid=doc_guid_val)
                if result.ok:
                    self.statusBar().showMessage(t("client_doc_post_ok"), 3000)
                    # Update _posted flag in UI
                    rec["_posted"] = True
                    form_widget.set_record(rec)
                else:
                    QMessageBox.warning(self, t("dlg_error_title"),
                        "\n".join(result.messages) or t("client_doc_post_failed"))
            except Exception as e:
                QMessageBox.warning(self, t("dlg_error_title"), str(e))
            return

        if c in ("unpost", "form.unpost"):
            if self._db is None or form_widget is None:
                return
            try:
                rec = form_widget.collect()
                doc_guid_val = str(rec.get("_guid") or "")
                if not doc_guid_val or not doc_name:
                    return
                result = self._db.document_post(
                    doc_name=doc_name, doc_guid=doc_guid_val, post=False)
                if result.ok:
                    self.statusBar().showMessage(t("status_saved"), 3000)
                    rec["_posted"] = False
                    form_widget.set_record(rec)
                else:
                    QMessageBox.warning(self, t("dlg_error_title"),
                        "\n".join(result.messages) or t("client_doc_post_failed"))
            except Exception as e:
                QMessageBox.warning(self, t("dlg_error_title"), str(e))
            return

        # ── Print ─────────────────────────────────────────────────────────
        if c in ("print", "form.print", "printdocument"):
            if self._db is None or form_widget is None:
                return
            try:
                rec = form_widget.collect()
                doc_guid_val = str(rec.get("_guid") or "")
                if not doc_guid_val or not doc_name:
                    QMessageBox.information(self, t("print_btn_print"), t("client_err_save_first"))
                    return
                from src.runtime.print_engine import PrintEngine
                manifest = self._manifest_subtree_for_guid(form_guid)
                if not manifest:
                    row = self._manifest_row_by_guid(form_guid)
                    manifest = [row] if isinstance(row, dict) else []
                html = PrintEngine(self._db, manifest).render_document(doc_name, doc_guid_val)
                from src.client.forms.print_form import PrintPreviewForm
                view_id = f"print:{doc_guid_val}"
                if view_id not in self._views:
                    pv = PrintPreviewForm()
                    self._register_view(view_id, pv)
                pv = self._views[view_id]
                pv.load_html(html, title=doc_name)
                self._select_view(view_id)
            except Exception as e:
                QMessageBox.warning(self, t("dlg_error_title"), str(e))
            return

        # ── Delete ────────────────────────────────────────────────────────
        if c in ("delete", "form.delete", "markdelete"):
            if self._db is None or form_widget is None:
                return
            try:
                rec = form_widget.collect()
                guid_val = str(rec.get("_guid") or "")
                if not guid_val or not doc_name:
                    return
                reply = QMessageBox.question(
                    self, t("dlg_confirm_title"), t("client_confirm_delete"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
                tbl_name = infer_data_table_name(doc_name, rec)
                self._db.table(tbl_name).update({"_guid": guid_val}, {"_deleted": True})
                self.statusBar().showMessage(t("status_saved"), 3000)
                self._close_presented_form(f"form:{form_guid}")
            except Exception as e:
                QMessageBox.warning(self, t("dlg_error_title"), str(e))
            return

        # Unknown command — log silently
        self.statusBar().showMessage(f"⚡ {code}", 2000)


    def _open_reference_record(self, metadata_ref: str, record_guid: str) -> None:
        """Resolve a metadata reference and open its selected record."""
        raw_ref = str(metadata_ref or "").strip()
        rec_guid = str(record_guid or "").strip()
        if not raw_ref or not rec_guid:
            return
        parts = [part.strip() for part in raw_ref.replace("::", ".").split(".") if part.strip()]
        target_name = parts[-1].casefold() if parts else ""
        prefix = parts[0].casefold() if len(parts) > 1 else ""
        type_aliases = {
            "catalog": "catalog", "довідник": "catalog", "справочник": "catalog",
            "document": "document", "документ": "document",
            "chartofcharacteristictypes": "characteristic_plan",
            "планвидовхарактеристик": "characteristic_plan",
        }
        target_type = type_aliases.get(prefix, "")
        rows = list(getattr(self, "_manifest_nav_rows_cache", []) or [])
        if not rows:
            try:
                user_rows, subsystem_rows, report_rows = self._manifest_nav_rows()
                rows = [*user_rows, *subsystem_rows, *report_rows]
                self._manifest_nav_rows_cache = list(rows)
            except Exception:
                rows = []
        target = next(
            (
                row for row in rows
                if isinstance(row, dict)
                and str(row.get("name") or "").strip().casefold() == target_name
                and (not target_type or str(row.get("type") or "").strip().lower() == target_type)
            ),
            None,
        )
        if isinstance(target, dict):
            self._open_meta_object(str(target.get("guid") or ""), mode=f"object:{rec_guid}")


    def _open_meta_object(self, obj_guid: str, *, mode: str = "list") -> None:
        """Відкрити форму для метаоб'єкта.

        Форма ЗАВЖДИ береться з маніфесту (спроектована в конфігураторі).
        Якщо форму ще не згенеровано — генеруємо автоматично на льоту.

        mode: "list" → list_form, "object:<rec_guid>" → object_form
        """
        if self._db is None:
            return

        guid = str(obj_guid or "").strip()
        if not guid:
            return

        context = self._object_context_for_guid(guid)
        owner = context.get("row") if isinstance(context.get("row"), dict) else self._manifest_row_by_guid(guid)
        if not isinstance(owner, dict):
            return
        if not self._can_access_row(owner, action="execute" if mode.startswith("object:") else "open"):
            self._deny_access(t("dlg_error_title"), str(owner.get("title") or owner.get("name") or guid))
            return

        owner_row = dict(owner)
        owner_row["payload"] = dict(context.get("payload") or self._manifest_payload_for_row(owner_row))
        manifest = [owner_row]

        obj_type  = str(owner.get("type") or "").strip().lower()
        obj_name  = str(owner.get("name") or "").strip()
        obj_title = self._row_title(owner)
        owner_payload = self._manifest_payload_for_row(owner)
        nav_rows = list(getattr(self, "_manifest_nav_rows_cache", []) or [])
        if not nav_rows:
            try:
                user_rows, subsystem_rows, report_rows = self._manifest_nav_rows()
                nav_rows = [*user_rows, *subsystem_rows, *report_rows]
                self._manifest_nav_rows_cache = list(nav_rows)
            except Exception:
                nav_rows = []

        # Спеціальні типи — не потребують форм дизайнера
        if obj_type in ("constants", "constant"):
            view_id = "constants_form"
            if view_id not in self._views:
                w = ConstantsForm(db=self._db, manifest_rows=manifest)
                w.saved.connect(lambda: self.statusBar().showMessage(t("status_saved"), 3000))
                self._register_view(view_id, w)
            self._select_view(view_id)
            return

        if obj_type in ("register_accum", "register_info"):
            view_id = f"register:{guid}"
            if view_id not in self._views:
                w = RegisterViewerWidget(
                    reg_name=obj_name, reg_title=obj_title,
                    reg_type=obj_type, db=self._db, manifest_rows=manifest)
                w.title = obj_title  # type: ignore[attr-defined]
                self._register_view(view_id, w)
            self._select_view(view_id)
            return

        if obj_type == "report":
            view_id = f"report:{guid}"
            if view_id not in self._views:
                report_rows = self._manifest_subtree_for_guid(guid) or nav_rows
                w = ReportResultForm(db=self._db, manifest_rows=report_rows)
                w.title = obj_title  # type: ignore[attr-defined]
                try:
                    from src.runtime.report_engine import ReportEngine
                    w.display(ReportEngine(self._db, report_rows).run(obj_name))
                except Exception:
                    pass
                self._register_view(view_id, w)
            self._select_view(view_id)
            return

        # Для catalog і document — беремо форму з маніфесту
        # Розбираємо mode: "list" або "object:<rec_guid>"
        rec_guid = ""
        if mode.startswith("object:"):
            rec_guid = mode[len("object:"):]
        form_kind = self._form_kind_for_open_mode(mode, obj_type)

        # Шукаємо форму в маніфесті
        form_model = self._find_form_model_for_owner_guid(
            guid, form_kind, context=context
        )

        # Якщо форми немає або вона не містить полів, генеруємо автоматично
        if self._should_auto_generate_form(form_model, form_kind, obj_type):
            form_model = self._auto_generate_form(owner, nav_rows, form_kind)

        ctx = ObjContext(
            obj_guid=guid, obj_name=obj_name, obj_type=obj_type,
            obj_title=obj_title, rec_guid=rec_guid, form_kind=form_kind,
        )

        # view_id: для list — один на об'єкт, для object — один на запис
        if form_kind == "list_form":
            view_id = f"list:{guid}"
        else:
            view_id = f"obj:{guid}:{rec_guid or 'new'}"

        def on_cmd(code: str) -> None:
            self._handle_form_command(code, ctx=ctx, view_id=view_id)

        if view_id in self._views:
            self._select_view(view_id)
            return
        if self._activate_form_window(view_id):
            return

        w = FormRuntimeWidget(
            model=form_model, db=self._db,
            ctx=ctx, manifest_rows=manifest, on_command=on_cmd,
            access_checker=lambda action, row=dict(owner_row): self._can_access_row(row, action=action),
        )
        w.reference_open_requested.connect(self._open_reference_record)

        # Tab/window title: for object forms show "ObjectType: RecordName".
        form_title = obj_title
        if form_kind == "object_form":
            if rec_guid:
                try:
                    rec_rows = self._db.table(
                        _data_table(obj_type, obj_name)
                    ).select(where={"_guid": rec_guid}) or []
                    if rec_rows:
                        r = rec_rows[0]
                        desc = str(
                            r.get("_description") or r.get("description") or
                            r.get("_name") or r.get("name") or r.get("_code") or ""
                        ).strip()
                        if desc:
                            form_title = f"{obj_title}: {desc}"
                except Exception:
                    pass
            else:
                form_title = f"{obj_title} (новий)"
        w.title = form_title  # type: ignore[attr-defined]

        # Attach form module runner if a module exists for this object.
        module_text, module_lang = self._load_form_module_text(guid, form_kind, context=context)
        if not module_text.strip():
            module_text, module_lang = self._module_text_for_payload(owner_payload)
        if module_text.strip():
            from src.client.forms.form_module_runner import FormContext, FormModuleRunner
            runner = FormModuleRunner(
                module_text,
                FormContext(w),
                language=module_lang,
                extra_builtins=build_global_context(self._db),
            )
            w.attach_module_runner(runner)
            if runner.has_errors:
                logger.warning("Form module errors (%s/%s): %s", obj_name, form_kind, runner.errors)

        self._present_form(
            view_id=view_id,
            widget=w,
            title=form_title,
            model=form_model,
            owner_type=obj_type,
        )


    def _find_form_model_for_owner_guid(
        self, owner_guid: str, form_kind: str, *, context: dict[str, object] | None = None,
    ) -> Optional[Dict]:
        """Find FormModel by targeted manifest queries for one owner."""
        if isinstance(context, dict):
            candidates: list[tuple[dict, dict]] = []
            for row in context.get("forms") or []:
                if not isinstance(row, dict):
                    continue
                pay = row.get("payload") if isinstance(row.get("payload"), dict) else {}
                model = self._payload_form_model(pay)
                if isinstance(model, dict) and model:
                    candidates.append((row, model))

            # Do not return the first row with a matching subtype.  1C keeps
            # several object forms together (selection, status, document,
            # etc.), and the manifest order is not the default-form order.
            # Prefer the canonical form name, then use subtype as a fallback.
            if candidates:
                def score(item: tuple[dict, dict]) -> tuple[int, str]:
                    row, _model = item
                    name = str(row.get("name") or "").casefold()
                    if form_kind == "list_form":
                        rank = 0 if any(token in name for token in ("spyska", "spis", "list")) else 2
                    else:
                        rank = 0 if any(token in name for token in ("dokumenta", "elementa", "object", "obek")) else 2
                    if str((row.get("payload") or {}).get("subtype") or "").strip().lower() != form_kind:
                        rank += 1
                    return rank, name

                candidates.sort(key=score)
                return candidates[0][1]
        if self._db is None:
            return None
        try:
            rows = self._db.table("manifest").select(where={"parent_guid": owner_guid}) or []
            forms_folder = next(
                (r for r in rows
                 if str(r.get("name") or "").lower() == "forms"
                 and str(r.get("kind") or "").lower() == "folder"), None)
            if not forms_folder:
                return None
            ff_guid = str(forms_folder.get("guid") or "")
            rows = self._db.table("manifest").select(where={"parent_guid": ff_guid}) or []
            candidates: list[tuple[dict, dict]] = []
            for r in rows:
                pay = self._manifest_payload_for_row(r)
                if not isinstance(pay, dict):
                    continue
                model = self._payload_form_model(pay)
                if isinstance(model, dict) and model:
                    candidates.append((r, model))
            if candidates:
                def score(item: tuple[dict, dict]) -> tuple[int, str]:
                    row, _model = item
                    name = str(row.get("name") or "").casefold()
                    if form_kind == "list_form":
                        rank = 0 if any(token in name for token in ("spyska", "spis", "list")) else 2
                    else:
                        rank = 0 if any(token in name for token in ("dokumenta", "elementa", "object", "obek")) else 2
                    if str((row.get("payload") or {}).get("subtype") or "").strip().lower() != form_kind:
                        rank += 1
                    return rank, name

                candidates.sort(key=score)
                return candidates[0][1]
        except Exception:
            pass
        return None


    @staticmethod
    def _form_model_has_fields(model: Dict | None, form_kind: str) -> bool:
        if not isinstance(model, dict):
            return False

        def _walk(node: object) -> bool:
            if not isinstance(node, dict):
                return False
            node_type = str(node.get("type") or "").strip()
            if node_type in {"Table", "TablePanel"}:
                props = node.get("props") if isinstance(node.get("props"), dict) else {}
                cols = props.get("columns") if isinstance(props, dict) and isinstance(props.get("columns"), list) else []
                if cols:
                    return True
            if form_kind == "object_form" and node_type in {"TextBox", "TextArea", "NumberBox", "DateBox", "CheckBox", "ComboBox"}:
                if str(node.get("binding") or node.get("name") or "").strip():
                    return True
            children = node.get("children") if isinstance(node.get("children"), list) else []
            return any(_walk(ch) for ch in children)

        return _walk(model.get("root"))


    @classmethod
    def _should_auto_generate_form(
        cls, model: Dict | None, form_kind: str, owner_type: str,
    ) -> bool:
        if not isinstance(model, dict) or not model:
            return True
        obj_type = str(owner_type or "").strip().lower()
        if obj_type in {"data_processor", "data_processors", "common_form", "common_forms"}:
            return False
        return not cls._form_model_has_fields(model, form_kind)


    def _auto_generate_form(
        self, owner: dict, rows: list, form_kind: str
    ) -> Dict:
        """Автогенерація FormModel по схемі об'єкта якщо дизайнерська форма відсутня."""
        from src.configurator.domain.form_templates import (
            build_list_form_model, build_object_form_model)
        from src.configurator.domain.default_commands import default_commands_for_context
        from src.configurator.domain.default_schema import default_attributes_for_object

        obj_type  = str(owner.get("type") or "").lower()
        obj_name  = str(owner.get("name") or "")
        obj_title = str(owner.get("title") or obj_name)
        pay = owner.get("payload") or {}
        attrs = []
        if isinstance(pay, dict):
            attrs = pay.get("attributes") or pay.get("requisites") or []
        if not attrs:
            attrs = default_attributes_for_object(
                obj_type=obj_type,
                subtype=str(pay.get("subtype") or "") if isinstance(pay, dict) else "",
            )
        cmds  = default_commands_for_context(obj_type=obj_type, context=form_kind)

        if form_kind == "list_form":
            return build_list_form_model(
                form_name=f"{obj_name}_list",
                owner_title=obj_title,
                attributes=attrs,
                commands=cmds,
            )
        return build_object_form_model(
            form_name=f"{obj_name}_obj",
            owner_title=obj_title,
            attributes=attrs,
            commands=cmds,
        )


    def _handle_form_command(self, code: str, *, ctx: ObjContext, view_id: str) -> None:
        """Обробка команд від FormRuntimeWidget."""
        import uuid as _uuid
        c = code.strip().lower()

        # ── Навігація ─────────────────────────────────────────────────────
        if c in ("close", "form.close"):
            # Повертаємось до list_form або dashboard
            list_id = f"list:{ctx.obj_guid}"
            self._close_presented_form(
                view_id,
                fallback_view_id=list_id if list_id in self._views else "dashboard",
            )
            return

        if c in ("refresh", "form.refresh"):
            w = self._runtime_form_widget(view_id)
            if w and hasattr(w, "reload_list"):
                w.reload_list()
            return

        # ── List form команди ──────────────────────────────────────────────
        if c == "create":
            if not self._can_access_row(self._manifest_row_by_guid(ctx.obj_guid), action="create"):
                self._deny_access(t("dlg_error_title"), ctx.obj_title)
                return
            self._open_meta_object(ctx.obj_guid, mode="object:")
            return

        if c == "edit":
            w = self._runtime_form_widget(view_id)
            rec_guid = w.selected_rec_guid() if w else ""
            if rec_guid:
                if not self._can_access_row(self._manifest_row_by_guid(ctx.obj_guid), action="edit"):
                    self._deny_access(t("dlg_error_title"), ctx.obj_title)
                    return
                self._open_meta_object(ctx.obj_guid, mode=f"object:{rec_guid}")
            return

        if c == "delete":
            w = self._runtime_form_widget(view_id)
            rec_guid = w.selected_rec_guid() if w else ""
            if not rec_guid or not self._db:
                return
            if not self._can_access_row(self._manifest_row_by_guid(ctx.obj_guid), action="delete"):
                self._deny_access(t("dlg_error_title"), ctx.obj_title)
                return
            from PySide6.QtWidgets import QMessageBox as _MB
            if _MB.question(self, t("dlg_confirm_title"), t("client_confirm_delete"),
                            _MB.StandardButton.Yes | _MB.StandardButton.No
                            ) != _MB.StandardButton.Yes:
                return
            try:
                tbl = _data_table(ctx.obj_type, ctx.obj_name)
                self._db.table(tbl).update({"_guid": rec_guid}, {"_deleted": True})
                w.reload_list()
            except Exception as e:
                QMessageBox.warning(self, t("dlg_error_title"), str(e))
            return

        # ── Copy record ───────────────────────────────────────────────────
        if c in ("copy", "copyelement", "form.copy"):
            w = self._runtime_form_widget(view_id)
            rec_guid = w.selected_rec_guid() if (w and hasattr(w, "selected_rec_guid")) else ""
            if not rec_guid and ctx.rec_guid:
                rec_guid = ctx.rec_guid
            if rec_guid:
                self._copy_record(ctx, rec_guid)
            return

        # ── Object form команди ────────────────────────────────────────────
        if c in ("save", "write", "form.save"):
            if not self._can_access_row(self._manifest_row_by_guid(ctx.obj_guid), action="save"):
                self._deny_access(t("dlg_error_title"), ctx.obj_title)
                return
            self._form_save(ctx, view_id)
            # Refresh open list for this object (live feedback without close)
            list_id = f"list:{ctx.obj_guid}"
            if list_id in self._views:
                lw = self._views[list_id]
                if hasattr(lw, "reload_list"):
                    lw.reload_list()
            return

        if c in ("saveandclose", "save_close", "form.saveandclose"):
            if not self._can_access_row(self._manifest_row_by_guid(ctx.obj_guid), action="save"):
                self._deny_access(t("dlg_error_title"), ctx.obj_title)
                return
            if not self._form_save(ctx, view_id):
                return
            # Якщо збережено — закриваємо і оновлюємо список
            list_id = f"list:{ctx.obj_guid}"
            if list_id in self._views:
                lw = self._views[list_id]
                if hasattr(lw, "reload_list"):
                    lw.reload_list()
            self._close_presented_form(
                view_id,
                fallback_view_id=list_id if list_id in self._views else "dashboard",
            )
            return

        if c in ("post", "form.post"):
            if not self._can_access_row(self._manifest_row_by_guid(ctx.obj_guid), action="post"):
                self._deny_access(t("dlg_error_title"), ctx.obj_title)
                return
            self._form_post(ctx, view_id, post=True)
            return

        if c in ("post_and_close", "postandclose", "form.postandclose"):
            if not self._can_access_row(self._manifest_row_by_guid(ctx.obj_guid), action="post"):
                self._deny_access(t("dlg_error_title"), ctx.obj_title)
                return
            if not self._form_post(ctx, view_id, post=True):
                return
            list_id = f"list:{ctx.obj_guid}"
            if list_id in self._views:
                lw = self._views[list_id]
                if hasattr(lw, "reload_list"):
                    lw.reload_list()
            self._close_presented_form(
                view_id,
                fallback_view_id=list_id if list_id in self._views else "dashboard",
            )
            return

        if c in ("unpost", "form.unpost"):
            if not self._can_access_row(self._manifest_row_by_guid(ctx.obj_guid), action="unpost"):
                self._deny_access(t("dlg_error_title"), ctx.obj_title)
                return
            self._form_post(ctx, view_id, post=False)
            return

        if c in ("print", "form.print"):
            self._form_print(ctx, view_id)
            return

        # Невідома команда — тихо логуємо
        self.statusBar().showMessage(f"⚡ {code}", 2000)


    def _copy_record(self, ctx: ObjContext, src_guid: str) -> None:
        """Відкриває нову об'єктну форму з даними скопійованого запису."""
        if self._db is None or not src_guid:
            return
        try:
            rows = self._db.table(_data_table(ctx.obj_type, ctx.obj_name)).select(
                where={"_guid": src_guid}) or []
            if not rows:
                return
            src_rec = dict(rows[0])
        except Exception as e:
            QMessageBox.warning(self, t("dlg_error_title"), str(e))
            return

        # Open a "new record" form
        self._open_meta_object(ctx.obj_guid, mode="object:")

        # Find the newly opened view and pre-fill it with the copied data
        new_view_id = f"obj:{ctx.obj_guid}:new"
        w = self._runtime_form_widget(new_view_id)
        if w is None:
            return
        # Strip identity fields — new record must get its own
        copy_rec = {k: v for k, v in src_rec.items()
                    if k not in ("_guid", "_posted", "_number", "_number_prefix", "_date")}
        copy_rec["_guid"] = ""
        copy_rec.setdefault("_deleted", False)
        if hasattr(w, "set_record"):
            w.set_record(copy_rec)
        # Update tab title hint
        desc = str(src_rec.get("_description") or src_rec.get("description") or "").strip()
        new_title = f"{ctx.obj_title} (копія{': ' + desc if desc else ''})"
        w.title = new_title  # type: ignore[attr-defined]
        self._set_presented_form_title(new_view_id, new_title)


    def _form_save(self, ctx: ObjContext, view_id: str) -> bool:
        """Зберегти запис об'єктної форми."""
        import uuid as _uuid
        if self._db is None:
            return False
        w = self._runtime_form_widget(view_id)
        if not w or not hasattr(w, "collect"):
            return False
        rec = w.collect()
        try:
            tbl_name = _data_table(ctx.obj_type, ctx.obj_name)
            is_new = not bool(ctx.rec_guid)
            if is_new:
                rec["_guid"] = str(_uuid.uuid4())
                rec.setdefault("_deleted", False)
                if ctx.obj_type == "catalog":
                    rec.setdefault("_predefined", False)
                    rec.setdefault("_is_folder", False)
                if ctx.obj_type == "document":
                    rec.setdefault("_posted", False)
                if ctx.obj_type == "document" and not rec.get("_number"):
                    try:
                        from src.runtime.numerator import Numerator
                        rec["_number"] = Numerator(self._db).next(ctx.obj_name, width=6)
                    except Exception:
                        pass
                if ctx.obj_type == "catalog" and not rec.get("_code"):
                    try:
                        from src.runtime.numerator import Numerator
                        rec["_code"] = str(Numerator(self._db).next(
                            ctx.obj_name + "_code", width=4))
                    except Exception:
                        pass
                self._db.table(tbl_name).insert(rec)
                ctx.rec_guid = rec["_guid"]
            else:
                if self._db.table(tbl_name).update({"_guid": ctx.rec_guid}, rec) != 1:
                    raise RuntimeError("Object record was not saved: missing or ambiguous GUID")
            w.set_record(rec)
            # Save tabular parts
            self._save_tp_data(w, ctx)
            window = getattr(self, "_form_windows", {}).get(view_id)
            if window is not None:
                window.clear_dirty()

            # Remove dirty marker from tab title
            idx = self._tab_widget.indexOf(w)
            if idx >= 0:
                title = self._tab_widget.tabText(idx)
                if title.startswith("* "):
                    self._tab_widget.setTabText(idx, title[2:])

            self.statusBar().showMessage(t("status_saved"), 3000)

            # Update tab title with record description after save
            desc = str(
                rec.get("_description") or rec.get("description") or
                rec.get("_name") or rec.get("name") or rec.get("_code") or ""
            ).strip()
            if desc:
                new_title = f"{ctx.obj_title}: {desc}"
                self._set_presented_form_title(view_id, new_title)

            # AfterWrite hook
            runner = getattr(w, "_module_runner", None)
            if runner is not None and runner.is_loaded:
                for name in ("AfterWrite", "ПісляЗапису", "ПослеЗаписи"):
                    found, _ = runner.call_handler(name)
                    if found:
                        break
            return True
        except Exception as e:
            QMessageBox.warning(self, t("dlg_error_title"), str(e))
            return False


    def _save_tp_data(self, form_widget, ctx: ObjContext) -> None:
        """Зберегти рядки табличних частин після збереження головного запису."""
        from src.client.forms.form_runtime_types import _tp_table
        if self._db is None or not ctx.rec_guid:
            return
        tp_tables: dict = getattr(form_widget, "_tp_tables", {})
        tp_col_bindings: dict = getattr(form_widget, "_tp_col_bindings", {})
        if not tp_tables:
            return
        for binding, tv in tp_tables.items():
            if tv is None:
                continue
            m = tv.model()
            if m is None:
                continue
            col_bindings: list = tp_col_bindings.get(binding) or []
            tbl_name = _tp_table(ctx.obj_name, binding)
            try:
                # Ensure TP table exists
                try:
                    self._db.table(tbl_name).select(where={"_doc_guid": "x"})
                except Exception:
                    gw = getattr(self._db, "_gw", None)
                    if gw is not None:
                        try:
                            gw.schema_deploy()
                        except Exception:
                            pass
                # Delete old rows, insert new ones
                self._db.table(tbl_name).delete({"_doc_guid": ctx.rec_guid})
                for row_idx in range(m.rowCount()):
                    row: dict = {
                        "_doc_guid": ctx.rec_guid,
                        "_line_no":  row_idx + 1,
                        "_deleted":  False,
                    }
                    for ci, col in enumerate(col_bindings):
                        item = m.item(row_idx, ci)
                        row[col] = item.text() if item else ""
                    # Skip fully empty rows
                    user_vals = [str(row.get(c, "")).strip() for c in col_bindings
                                 if not c.startswith("_")]
                    if not any(user_vals):
                        continue
                    self._db.table(tbl_name).insert(row)
            except Exception as exc:
                logger.warning("TP save failed (%s/%s): %s", ctx.obj_name, binding, exc)
                raise


    def _form_post(self, ctx: ObjContext, view_id: str, *, post: bool) -> bool:
        """Провести або скасувати проведення документа."""
        if self._db is None:
            return False
        window = getattr(self, "_form_windows", {}).get(view_id)
        dirty = window is not None and window.is_dirty
        widget = self._runtime_form_widget(view_id)
        tabs = getattr(self, "_tab_widget", None)
        if tabs is not None and widget is not None:
            index = tabs.indexOf(widget)
            dirty = dirty or (index >= 0 and tabs.tabText(index).startswith("* "))
        if not ctx.rec_guid or (post and dirty):
            QMessageBox.warning(self, t("dlg_error_title"), t("client_post_save_changes"))
            return False
        try:
            result = self._db.document_post(doc_name=ctx.obj_name, doc_guid=ctx.rec_guid, post=post)
            if result.ok:
                self.statusBar().showMessage(
                    t("client_doc_post_ok") if post else t("status_saved"), 3000)
                w = self._runtime_form_widget(view_id)
                if w and hasattr(w, "set_record"):
                    rec = w.collect()
                    rec["_posted"] = post
                    w.set_record(rec)
                return True
            else:
                QMessageBox.warning(self, t("dlg_error_title"),
                    "\n".join(result.messages) or t("client_doc_post_failed"))
        except Exception as e:
            QMessageBox.warning(self, t("dlg_error_title"), str(e))
        return False


    def _form_print(self, ctx: ObjContext, view_id: str) -> None:
        """Друк документа через PrintEngine."""
        if self._db is None or not ctx.rec_guid:
            QMessageBox.information(self, t("print_btn_print"), t("client_err_save_first"))
            return
        try:
            from src.runtime.print_engine import PrintEngine
            mrows = self._manifest_subtree_for_guid(ctx.obj_guid)
            if not mrows:
                row = self._manifest_row_by_guid(ctx.obj_guid)
                mrows = [row] if isinstance(row, dict) else []
            html = PrintEngine(self._db, mrows).render_document(ctx.obj_name, ctx.rec_guid)
            pv_id = f"print:{ctx.rec_guid}"
            if pv_id not in self._views:
                pv = PrintPreviewForm()
                self._register_view(pv_id, pv)
            self._views[pv_id].load_html(html, title=ctx.obj_name)
            self._select_view(pv_id)
        except Exception as e:
            QMessageBox.warning(self, t("dlg_error_title"), str(e))
