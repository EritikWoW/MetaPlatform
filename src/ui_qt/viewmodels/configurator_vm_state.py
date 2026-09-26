from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.platform.logging_setup import get_logger
from src.configurator.domain.technical_names import technical_object_name
from src.ui_qt.i18n import t
from .configurator_vm_types import ObjectLike


_log = get_logger("configurator.vm")
_EXTERNALIZED_PAYLOAD_KEYS = (
    "attributes",
    "dimensions",
    "dump_info_children",
    "enum_values",
    "form_model",
    "help_contents",
    "layout_model",
    "requisites",
    "resources",
    "tabular_parts",
)

if TYPE_CHECKING:
    from PySide6.QtGui import QStandardItemModel

    from src.configurator.application.service import ConfiguratorService
    from .configurator_vm_types import Dialogs


def _subsystem_tree_parents(parent_guids: Dict[str, str]) -> Dict[str, str]:
    """Build a display-only forest without changing manifest parent links."""
    parents = {
        guid: parent if parent in parent_guids and parent != guid else ""
        for guid, parent in parent_guids.items()
    }
    visited: set[str] = set()
    for guid in parents:
        chain: list[str] = []
        positions: dict[str, int] = {}
        current = guid
        while current and current not in visited:
            if current in positions:
                # Choose the same break point regardless of snapshot ordering.
                parents[min(chain[positions[current]:])] = ""
                break
            positions[current] = len(chain)
            chain.append(current)
            current = parents[current]
        visited.update(chain)
    return parents


class _ConfiguratorVmStateContract:
    _service: "ConfiguratorService"
    _dialogs: "Dialogs"
    statusChanged: Any
    _payload_overrides_by_guid: Dict[str, Dict[str, Any]]
    _meta_by_guid: Dict[str, Dict[str, Any]]
    _objects_by_guid: Dict[str, ObjectLike]
    _objects_snapshot: List[ObjectLike]
    _subsystems_cache: List[Dict[str, Any]]
    tree_model: "QStandardItemModel"
    ROLE_META: int

    def reload(self) -> None: ...


class ConfiguratorVmStateMixin(_ConfiguratorVmStateContract):

    def _manifest_payload_for_guid(self, guid: str) -> Dict[str, Any]:
        """Fetch a full manifest payload on demand.

        Tree snapshots intentionally keep only lightweight fields, so editors
        may need to hydrate the real payload from the runtime when opening
        module-backed objects.
        """

        guid = str(guid or "").strip()
        if not guid:
            return {}
        try:
            getter = getattr(self._service, "manifest_get_payload", None)
            if not callable(getter):
                return {}
            payload = getter(guid)
        except Exception:
            return {}
        return dict(payload) if isinstance(payload, dict) else {}

    def set_object_payload(self, guid: str, payload: Dict[str, Any]) -> None:
        """Replace object payload entirely.

        Unlike :meth:`update_object_payload`, this method does not merge values.
        It writes the provided payload as-is (empty dict allowed).
        """

        guid = (guid or "").strip()
        if not guid:
            return
        self.save_object_payload(guid, payload or {}, reload=True)


    def _remember_payload_override(self, guid: str, payload: Dict[str, Any]) -> None:
        guid = str(guid or "").strip()
        if not guid:
            return
        normalized = dict(payload or {})
        self._payload_overrides_by_guid[guid] = normalized
        objects_by_guid = getattr(self, "_objects_by_guid", {})
        obj = objects_by_guid.get(guid) if isinstance(objects_by_guid, dict) else None
        if obj is not None:
            try:
                setattr(obj, "payload", normalized)
            except Exception:
                pass
        meta = self._meta_by_guid.get(guid)
        if isinstance(meta, dict):
            meta["payload"] = self._tree_payload_snapshot(normalized)


    def save_object_payload(self, guid: str, payload: Dict[str, Any], *, reload: bool = True) -> bool:
        """Persist full payload and optionally rebuild the tree.

        Editors that mutate large embedded models (forms/layouts) can use
        ``reload=False`` to avoid a full tree rebuild on each keystroke.
        """

        guid = (guid or "").strip()
        if not guid:
            return False
        started_at = time.perf_counter()
        try:
            normalized = dict(payload or {})
            _log.info(
                "vm.save_object_payload.start guid=%s reload=%s keys=%s",
                guid,
                bool(reload),
                sorted(normalized.keys()),
            )
            self._service.update_object_payload(guid, normalized)
            self._remember_payload_override(guid, normalized)
            self.statusChanged.emit(t("status_saved"))
            if reload:
                self.reload()
            _log.info(
                "vm.save_object_payload.done guid=%s reload=%s took=%.3fs",
                guid,
                bool(reload),
                time.perf_counter() - started_at,
            )
            return True
        except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            _log.warning(
                "vm.save_object_payload.failed guid=%s reload=%s took=%.3fs error=%s",
                guid,
                bool(reload),
                time.perf_counter() - started_at,
                e,
            )
            msg = str(t("err_save_failed") or "").strip()
            if "{error}" in msg:
                text = msg.format(error=e)
            else:
                text = f"{msg} {e}".strip()
            self._dialogs.show_warning(t("dlg_error_title"), text)
            return False


    def save_externalized_payload_asset(
        self,
        guid: str,
        payload: Dict[str, Any],
        *,
        key: str,
        reload: bool = False,
    ) -> bool:
        """Persist an externalized heavy payload key directly to its asset ref.

        This bypasses manifest row rebuild for editors that only mutate
        asset-backed models like ``layout_model`` / ``form_model``.
        """

        guid = (guid or "").strip()
        if not guid:
            return False
        normalized = dict(payload or {})
        ref_key = f"{str(key or '').strip()}_ref"
        asset_ref = str(normalized.get(ref_key) or "").strip()
        if not asset_ref:
            return self.save_object_payload(guid, normalized, reload=reload)

        started_at = time.perf_counter()
        try:
            _log.info(
                "vm.save_externalized_payload_asset.start guid=%s key=%s ref=%s reload=%s",
                guid,
                key,
                asset_ref,
                bool(reload),
            )
            self._service.put_json_asset(asset_ref, normalized.get(key))
            # Keep the hydrated value in the editor cache. The manifest/tree
            # remain slim, while reopening the object in this session must
            # show the model that was just persisted to the external asset.
            self._remember_payload_override(guid, normalized)
            self.statusChanged.emit(t("status_saved"))
            if reload:
                self.reload()
            _log.info(
                "vm.save_externalized_payload_asset.done guid=%s key=%s reload=%s took=%.3fs",
                guid,
                key,
                bool(reload),
                time.perf_counter() - started_at,
            )
            return True
        except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            _log.warning(
                "vm.save_externalized_payload_asset.failed guid=%s key=%s reload=%s took=%.3fs error=%s",
                guid,
                key,
                bool(reload),
                time.perf_counter() - started_at,
                e,
            )
            msg = str(t("err_save_failed") or "").strip()
            if "{error}" in msg:
                text = msg.format(error=e)
            else:
                text = f"{msg} {e}".strip()
            self._dialogs.show_warning(t("dlg_error_title"), text)
            return False


    def save_object_payload_patch(self, guid: str, payload_patch: Dict[str, Any], *, reload: bool = True) -> bool:
        guid = (guid or "").strip()
        if not guid:
            return False
        try:
            getter = getattr(self._service, "manifest_get_payload", None)
            if callable(getter):
                # A patch must start from an authoritative payload. Treat an
                # RPC failure as a save failure instead of overwriting the
                # object with a partial tree/cache snapshot.
                base = dict(getter(guid) or {})
                local_override = self._payload_overrides_by_guid.get(guid)
                if isinstance(local_override, dict):
                    base.update(local_override)
            else:
                base = self._payload_for_guid(guid)
            if not base and not callable(getter):
                objs = self._service.list_objects()
                o = next((x for x in objs if str(x.guid) == guid), None)
                base = o.payload if (o is not None and isinstance(o.payload, dict)) else {}
            merged = dict(base or {})
            patch = dict(payload_patch or {})
            for key in _EXTERNALIZED_PAYLOAD_KEYS:
                if key in patch:
                    continue
                ref_key = f"{key}_ref"
                if str(merged.get(ref_key) or "").strip():
                    merged.pop(key, None)
            merged.update(patch)
            return self.save_object_payload(guid, merged, reload=reload)
        except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            msg = str(t("err_save_failed") or "").strip()
            if "{error}" in msg:
                text = msg.format(error=e)
            else:
                text = f"{msg} {e}".strip()
            self._dialogs.show_warning(t("dlg_error_title"), text)
            return False


    def get_meta_by_guid(self, guid: str) -> Optional[Dict[str, Any]]:
        """Return current meta dict for guid with the full object payload.

        Tree items intentionally store only a lightweight payload snapshot so
        large blobs (for example imported ``form_model``) do not bloat the tree
        model. Editors, however, need the full payload. This method therefore
        merges the current tree meta with the latest in-memory object snapshot.
        """
        guid = (guid or "").strip()
        if not guid:
            return None

        def with_full_payload(meta: Dict[str, Any]) -> Dict[str, Any]:
            out = dict(meta)
            full_payload = self._payload_for_guid(guid)
            if full_payload:
                out["payload"] = full_payload
            elif isinstance(out.get("payload"), dict):
                out["payload"] = dict(out["payload"])
            else:
                out["payload"] = {}
            return out

        meta = self._meta_by_guid.get(guid)
        if isinstance(meta, dict):
            return with_full_payload(meta)

        m = self.tree_model
        root = m.invisibleRootItem()

        def walk(it):
            """Метод: walk."""
            for r in range(it.rowCount()):
                child = it.child(r)
                meta = child.data(self.ROLE_META)
                if isinstance(meta, dict) and str(meta.get("guid") or "") == guid:
                    return with_full_payload(meta)
                found = walk(child)
                if found:
                    return found
            return None

        return walk(root)


    def _payload_for_guid(self, guid: str) -> Dict[str, Any]:
        """Return full payload for guid from the current object snapshot."""
        guid = str(guid or "").strip()
        override = self._payload_overrides_by_guid.get(guid)
        obj = self._objects_by_guid.get(guid)
        payload = getattr(obj, "payload", None) if obj is not None else None
        if isinstance(override, dict):
            payload_dict = dict(override)
        else:
            payload_dict = dict(payload) if isinstance(payload, dict) else {}
        obj_type = str(getattr(obj, "type", "") or "").strip().lower() if obj is not None else ""
        if not obj_type:
            meta = self._meta_by_guid.get(guid)
            if isinstance(meta, dict):
                obj_type = str(meta.get("type") or "").strip().lower()

        needs_manifest_payload = False
        if obj_type == "configuration":
            needs_manifest_payload = True
        if obj_type in {"common_module", "module"} and not payload_dict.get("module"):
            needs_manifest_payload = True
        if obj_type in {"form", "common_form"}:
            if not payload_dict.get("form_module") or not payload_dict.get("form_model"):
                needs_manifest_payload = True
        if obj_type == "subsystem":
            if not payload_dict.get("content_refs") or not payload_dict.get("objects"):
                needs_manifest_payload = True
        if any(
            str(payload_dict.get(f"{key}_ref") or "").strip() and key not in payload_dict
            for key in _EXTERNALIZED_PAYLOAD_KEYS
        ):
            needs_manifest_payload = True

        if needs_manifest_payload:
            full_payload = self._manifest_payload_for_guid(guid)
            if full_payload:
                merged_payload = dict(full_payload)
                merged_payload.update(payload_dict)
                full_payload = merged_payload
                if obj_type == "subsystem" and not full_payload.get("objects"):
                    objects_getter = getattr(self._service, "manifest_get_objects", None)
                    if callable(objects_getter):
                        try:
                            objects = objects_getter(guid)
                        except Exception:
                            objects = []
                        if objects:
                            full_payload = dict(full_payload)
                            full_payload["objects"] = list(objects)
                self._remember_payload_override(guid, full_payload)
                return dict(full_payload)
        if obj_type == "subsystem":
            objects_getter = getattr(self._service, "manifest_get_objects", None)
            if callable(objects_getter):
                try:
                    objects = objects_getter(guid)
                except Exception:
                    objects = []
                if objects:
                    merged = dict(payload_dict)
                    merged["objects"] = list(objects)
                    self._remember_payload_override(guid, merged)
                    return merged

        return payload_dict


    def _remember_objects_snapshot(self, objs: List[ObjectLike]) -> None:
        self._objects_snapshot = list(objs or [])
        self._objects_by_guid = {
            str(getattr(o, "guid", "") or ""): o
            for o in self._objects_snapshot
            if str(getattr(o, "guid", "") or "")
        }
        self._rebuild_subsystems_cache()


    def _rebuild_subsystems_cache(self) -> None:
        by_guid = {
            str(getattr(o, "guid", "") or "").strip(): o
            for o in self._objects_snapshot
            if str(getattr(o, "guid", "") or "").strip()
            and str(getattr(o, "type", "") or "").strip().lower() == "subsystem"
            and str(getattr(o, "kind", "") or "").strip().lower() == "object"
        }
        parent_guids = {
            guid: str(getattr(obj, "parent_guid", "") or "").strip()
            for guid, obj in by_guid.items()
        }
        parents = _subsystem_tree_parents(parent_guids)
        path_cache: Dict[str, str] = {}

        def _label(obj: Any) -> str:
            return str(getattr(obj, "title", "") or getattr(obj, "name", "") or getattr(obj, "guid", "")).strip()

        def _path_for(guid: str) -> str:
            chain: list[str] = []
            current = guid
            while current and current not in path_cache:
                chain.append(current)
                current = parents[current]
            path = path_cache.get(current, "")
            for current in reversed(chain):
                own = _label(by_guid[current]) or current
                path = f"{path} / {own}" if path else own
                path_cache[current] = path
            return path_cache[guid]

        out: List[Dict[str, Any]] = []
        for guid, o in by_guid.items():
            title = _label(o)
            out.append(
                {
                    "guid": guid,
                    "name": technical_object_name(getattr(o, "name", ""), payload=getattr(o, "payload", None)),
                    "title": title,
                    "path": _path_for(guid),
                    "parent_guid": parent_guids[guid],
                }
            )
        out.sort(key=lambda r: (str(r.get("path") or r.get("title") or r.get("name") or "")).casefold())
        self._subsystems_cache = out


    @staticmethod
    def _tree_payload_snapshot(payload: Any) -> Dict[str, Any]:
        """Keep only lightweight flags/text needed by tree interactions."""
        if not isinstance(payload, dict):
            return {}
        keys = (
            "auto",
            "comment",
            "comments",
            "i18n",
            "menu",
            "metadata_ref",
            "order",
            "protected",
            "schema_item",
            "schema_item_kind",
            "section",
            "seed",
            "subtype",
            "source_name",
            "synonym",
            "synonyms",
            "system",
            "tabular_part",
            "virtual",
        )
        return {key: payload[key] for key in keys if key in payload}


    def delete_object(self, meta: Dict[str, Any]) -> bool:
        """Удалить объект/папку по meta (с подтверждением и защитой системных узлов)."""
        guid = str(meta.get("guid") or "").strip()
        if not guid:
            self._dialogs.show_warning(t("dlg_error_title"), t("err_missing_guid"))
            return False

        payload = meta.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        if payload.get("system") or payload.get("protected") or payload.get("seed"):
            self._dialogs.show_warning(t("dlg_error_title"), t("err_delete_protected"))
            return False

        title = str(meta.get("title") or meta.get("name") or "объект")
        if not self._dialogs.confirm(
            t("dlg_confirm_title"),
            t("dlg_confirm_delete_object").format(title=title),
        ):
            return False

        try:
            self._service.delete_object(guid)
            self.reload()
            self.statusChanged.emit(t("status_deleted"))
            return True
        except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            self._dialogs.show_warning(t("dlg_error_title"), f"Не удалось удалить: {e}")
            return False
