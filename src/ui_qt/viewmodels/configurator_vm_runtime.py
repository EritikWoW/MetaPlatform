from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtCore import QTimer

from src.configurator.application.manifest_editor import ManifestEditorService
from src.configurator.persistence.system_tables import AUDIT_LOG_TABLE, USERS_TABLE
from src.ui_qt.i18n import t
from src.platform.logging_setup import get_logger

_log = get_logger("configurator.vm")


class ConfiguratorVmRuntimeMixin:
    def manifest_get_payload(self, guid: str) -> Dict[str, Any]:
        """Return an authoritative full payload through Runtime RPC."""

        return dict(self._service.manifest_get_payload(guid) or {})


    def manifest_get_objects(self, guid: str) -> List[str]:
        """Return subsystem membership through Runtime RPC."""

        return list(self._service.manifest_get_objects(guid) or [])


    @staticmethod
    def _is_functional_ref(ref: str) -> bool:
        text = str(ref or "").strip()
        return text.startswith("FunctionalOption.") or text.startswith("FunctionalOptionsParameter.")

    @staticmethod
    def _metadata_ref_for_object(obj: Any, *, origin_path: str = "") -> str:
        try:
            from src.infra.onec.onec_requisites_enrich import (
                metadata_ref_from_import_origin,
                metadata_ref_for_manifest_object,
            )

            metadata_ref = ""
            if origin_path:
                metadata_ref = metadata_ref_from_import_origin(origin_path)
            if not metadata_ref:
                metadata_ref = metadata_ref_for_manifest_object(
                    obj_type=str(getattr(obj, "type", "") or "").strip(),
                    name=str(getattr(obj, "name", "") or "").strip(),
                    origin_path=origin_path,
                )
            return str(metadata_ref or "").strip()
        except Exception:
            return ""

    @staticmethod
    def get_active_palette_map() -> Dict[str, str]:
        """Return active palette tokens -> colors.

        The project currently does not persist a token palette in manifest.
        Theme-aware SVG tinting is handled separately via QApplication
        palette roles and the ``mp_theme`` property, so this provider stays
        empty until a real manifest-backed palette source exists.
        """
        return {}


    def _startup_progress(self, percent: int, text: str) -> None:
        cb = self._startup_progress_cb
        if cb is None:
            return
        try:
            cb(int(percent), str(text or ""))
        except Exception:
            pass


    def list_users(self, *, active_only: bool = False) -> List[Dict[str, Any]]:
        """Return users from system tables.

        Args:
            active_only: When True, returns only active users.

        Returns:
            List of dict rows from sys_users.
        """

        try:
            tbl = self.db.table(USERS_TABLE)
        except Exception:
            return []

        where = {"is_active": True} if active_only else None
        rows = tbl.select(where, order_by="created_at")
        # Stable, UI-friendly ordering: newest first.
        rows.sort(key=lambda r: int(r.get("created_at") or 0), reverse=True)
        return rows


    def list_audit_log(self, *, limit: int = 500) -> List[Dict[str, Any]]:
        """Return last audit log entries.

        Args:
            limit: Max number of rows to return.

        Returns:
            Rows from sys_audit_log ordered by ts desc.
        """

        try:
            tbl = self.db.table(AUDIT_LOG_TABLE)
        except Exception:
            return []

        rows = tbl.select(None, order_by="ts")
        rows.sort(key=lambda r: int(r.get("ts") or 0), reverse=True)
        if limit and len(rows) > int(limit):
            rows = rows[: int(limit)]
        return rows


    def show_info(self, title: str, text: str) -> None:
        """Показать информационный диалог через View (без зависимости от QWidget)."""
        try:
            self._dialogs.show_info(title, text)
        except (AttributeError, RuntimeError, TypeError) as e:
            pass


    def show_warning(self, title: str, text: str) -> None:
        """Показать предупреждение через View (без зависимости от QWidget)."""
        try:
            self._dialogs.show_warning(title, text)
        except (AttributeError, RuntimeError, TypeError):
            pass


    def open_common_list(self, kind: str, cfg_guid: str) -> None:
        """Открыть “общий список” (1С-стиль) по коду раздела.
        Сейчас реализовано только для библиотеки картинок.
        """
        if kind in ("pictures", "common_pictures"):
            self.openPicturesGalleryRequested.emit()
            return
        if kind == "access_restrictions":
            try:
                from src.configurator.ui.widgets import NodeInfo

                info = NodeInfo(
                    kind="object",
                    name=t("ctx_all_access_restrictions"),
                    guid="virtual:access_restrictions",
                    obj_type="access_restrictions",
                )
                self.openEditorRequested.emit(info)
                return
            except Exception:
                pass
        # Subsystems, Roles, Common modules → open as filtered tree/list
        if kind in ("subsystems", "roles", "common_modules",
                    "exchange_plans", "scheduled_jobs", "event_subscriptions"):
            # Emit open request for the folder node itself
            try:
                db = self._service.require_db()
                rows = db.table("manifest").select() or []
                folder = next(
                    (r for r in rows
                     if str(r.get("name") or "").lower() == kind.lower()
                     and str(r.get("kind") or "") == "folder"),
                    None,
                )
                if folder:
                    from src.configurator.ui.widgets import NodeInfo
                    info = NodeInfo(
                        kind="folder",
                        name=str(folder.get("title") or folder.get("name") or kind),
                        guid=str(folder.get("guid") or ""),
                        obj_type=str(folder.get("type") or ""),
                    )
                    self.openEditorRequested.emit(info)
                    return
            except Exception:
                pass
        self.show_info(t("info_title"), t("info_not_implemented"))


    def close_db(self) -> None:
        """Close current mpdb connection (needed for destructive imports)."""
        self._runtime_refresh_epoch = int(getattr(self, "_runtime_refresh_epoch", 0)) + 1
        self._runtime_refresh_in_flight = False
        try:
            self._service.close()
        except Exception:
            pass
        self.db = None


    def reopen_db(self) -> None:
        """Re-open DB connection after it was closed/reset."""
        self._runtime_refresh_epoch = int(getattr(self, "_runtime_refresh_epoch", 0)) + 1
        self._runtime_refresh_in_flight = False
        res = self._service.open_db(
            self.runtime_url,
            self.db_uid,
            db_path=str(getattr(self, "db_path", "") or ""),
            seed_defaults_if_empty=True,
        )
        self.db = res.db
        self._editor = ManifestEditorService(self._service)
        self._populate_tree(res.objects)
        self.statusChanged.emit(t("status_ready"))
        if res.loaded_from_cache and not bool(getattr(res, "cache_validated", False)):
            QTimer.singleShot(0, self.start_background_runtime_refresh)


    def runtime_session_id(self) -> str:
        """Return the current runtime session id used by the configurator."""
        try:
            return self._service.current_session_id()
        except Exception:
            return ""


    def import_onec_dump(self, *, source_path: str, source_kind: str, mode: str = 'hard', wipe_prefixes: bool = True, prune_missing_assets: bool = True, migrate_data: bool = False) -> str:
        """Import 1C/BAS configuration dump through Runtime RPC.

        In client-server mode the configurator must never write mpdb directly.
        The heavy import runs on the runtime server via ``onec.import`` and the
        DB is reopened afterwards to refresh the manifest snapshot.
        """
        from src.tools.onec_import import import_onec_configuration
        import os

        # Optional: preserved only for CLI/local fallback inside import_onec_configuration.
        local_db_path = os.environ.get("META_DB_PATH", "").strip()

        self.close_db()
        try:
            return import_onec_configuration(
                db_path=local_db_path,
                source_path=source_path,
                source_kind=source_kind,
                mode=mode,
                wipe_prefixes=wipe_prefixes,
                prune_missing_assets=prune_missing_assets,
                migrate_data=migrate_data,
                runtime_url=self.runtime_url,
                db_uid=self.db_uid,
                session_id=self.runtime_session_id(),
            )
        finally:
            try:
                self.reopen_db()
            except Exception:
                pass


    def list_objects(self) -> List[Any]:
        """Return current manifest objects snapshot.

        This helper exists primarily for UI code that needs a lightweight way
        to access all objects (e.g., storage snapshot, pick-lists).
        """
        if self._objects_snapshot:
            return list(self._objects_snapshot)
        try:
            objs = list(self._service.list_objects())
        except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError):
            return []
        self._remember_objects_snapshot(objs)
        return list(objs)


    def list_objects_by_type(self, *types: str) -> List[Any]:
        """Return manifest objects filtered by type from the current snapshot."""
        if not types:
            return self.list_objects()
        wanted = {
            str(obj_type or "").strip().lower()
            for obj_type in types
            if str(obj_type or "").strip()
        }
        if not wanted:
            return self.list_objects()
        objs = self.list_objects()
        return [
            obj
            for obj in objs
            if str(getattr(obj, "type", "") or "").strip().lower() in wanted
        ]


    def list_subsystems(self) -> List[Dict[str, Any]]:
        """Return subsystem objects as a UI-friendly list.

        Shape:
            [{guid, name, title}]
        """
        if self._subsystems_cache:
            return [dict(x) for x in self._subsystems_cache]
        self._rebuild_subsystems_cache()
        return [dict(x) for x in self._subsystems_cache]


    def diagnose_subsystem_membership(
        self,
        *,
        guid: str = "",
        name: str = "",
        title: str = "",
    ) -> dict[str, Any]:
        """Return a membership comparison report for subsystems."""

        selected_guid = str(guid or "").strip()
        selected_name = str(name or "").strip()
        selected_title = str(title or "").strip()

        objects = list(self.list_objects() or [])
        refs_by_guid: dict[str, str] = {}
        guids_by_ref: dict[str, str] = {}
        for obj in objects:
            if str(getattr(obj, "kind", "") or "").strip().lower() != "object":
                continue
            obj_guid = str(getattr(obj, "guid", "") or "").strip()
            if not obj_guid:
                continue
            payload = getattr(obj, "payload", None)
            payload = dict(payload or {}) if isinstance(payload, dict) else {}
            metadata_ref = str(payload.get("metadata_ref") or "").strip()
            origin_path = ""
            imported = payload.get("imported")
            if isinstance(imported, dict):
                origin_path = str(imported.get("origin") or "").strip()
            if not metadata_ref:
                metadata_ref = ConfiguratorVmRuntimeMixin._metadata_ref_for_object(obj, origin_path=origin_path)
            if metadata_ref:
                refs_by_guid[obj_guid] = metadata_ref
                guids_by_ref.setdefault(metadata_ref, obj_guid)

        report: list[dict[str, Any]] = []
        scanned = 0
        mismatched = 0
        for obj in objects:
            if str(getattr(obj, "type", "") or "").strip().lower() != "subsystem":
                continue
            if str(getattr(obj, "kind", "") or "").strip().lower() != "object":
                continue
            obj_guid = str(getattr(obj, "guid", "") or "").strip()
            obj_name = str(getattr(obj, "name", "") or "").strip()
            obj_title = str(getattr(obj, "title", "") or "").strip()
            if selected_guid and obj_guid != selected_guid:
                continue
            if selected_name and obj_name != selected_name and obj_title != selected_name:
                continue
            if selected_title and obj_title != selected_title and obj_name != selected_title:
                continue
            scanned += 1
            payload = self.manifest_get_payload(obj_guid)
            current_objects = [str(x).strip() for x in list(payload.get("objects") or []) if str(x).strip()]
            current_refs = [str(x).strip() for x in list(payload.get("content_refs") or []) if str(x).strip()]
            resolved_objects: list[str] = []
            resolved_refs: list[str] = []
            seen_objects: set[str] = set()
            seen_refs: set[str] = set()

            def add_object(item: str) -> None:
                item = str(item or "").strip()
                if not item or item in seen_objects:
                    return
                seen_objects.add(item)
                resolved_objects.append(item)

            def add_ref(item: str) -> None:
                item = str(item or "").strip()
                if not item or item in seen_refs:
                    return
                seen_refs.add(item)
                resolved_refs.append(item)

            for item in current_objects:
                add_object(item)
                add_ref(refs_by_guid.get(item, ""))
            for item in current_refs:
                add_ref(item)
                if not ConfiguratorVmRuntimeMixin._is_functional_ref(item):
                    guid_item = guids_by_ref.get(item, "")
                    if guid_item:
                        add_object(guid_item)

            if not resolved_objects and resolved_refs:
                for item in resolved_refs:
                    if ConfiguratorVmRuntimeMixin._is_functional_ref(item):
                        continue
                    guid_item = guids_by_ref.get(item, "")
                    if guid_item:
                        add_object(guid_item)

            if not resolved_refs and resolved_objects:
                for item in resolved_objects:
                    add_ref(refs_by_guid.get(item, ""))

            if resolved_objects != current_objects or resolved_refs != current_refs:
                mismatched += 1

            report.append(
                {
                    "guid": obj_guid,
                    "name": obj_name,
                    "title": obj_title,
                    "objects_count": len(resolved_objects),
                    "content_refs_count": len(resolved_refs),
                    "objects_before": current_objects,
                    "objects_after": resolved_objects,
                    "content_refs_before": current_refs,
                    "content_refs_after": resolved_refs,
                    "missing_objects": [ref for ref in current_refs if not ConfiguratorVmRuntimeMixin._is_functional_ref(ref) and ref not in guids_by_ref],
                    "missing_refs": [refs_by_guid.get(item, "") for item in current_objects if refs_by_guid.get(item, "") not in current_refs],
                    "has_mismatch": resolved_objects != current_objects or resolved_refs != current_refs,
                }
            )

        return {
            "scanned": scanned,
            "mismatched": mismatched,
            "items": report,
        }


    def repair_subsystem_membership(
        self,
        *,
        guid: str = "",
        name: str = "",
        title: str = "",
    ) -> dict[str, Any]:
        """Repair subsystem membership using the current runtime snapshot."""

        diag = ConfiguratorVmRuntimeMixin.diagnose_subsystem_membership(self, guid=guid, name=name, title=title)
        items = list(diag.get("items") or [])
        changed = 0
        repaired: list[dict[str, Any]] = []
        payloads_by_guid: dict[str, dict[str, Any]] = {}
        for item in items:
            obj_guid = str(item.get("guid") or "").strip()
            if not obj_guid:
                continue
            objects_after = [str(x).strip() for x in list(item.get("objects_after") or []) if str(x).strip()]
            refs_after = [str(x).strip() for x in list(item.get("content_refs_after") or []) if str(x).strip()]
            payload = dict(self.manifest_get_payload(obj_guid) or {})
            if payload.get("objects") == objects_after and payload.get("content_refs") == refs_after:
                continue
            payload["objects"] = objects_after
            payload["content_refs"] = refs_after
            payloads_by_guid[obj_guid] = payload
            repaired.append(
                {
                    "guid": obj_guid,
                    "objects": objects_after,
                    "content_refs": refs_after,
                }
            )

        if payloads_by_guid:
            bulk_update = getattr(self._service, "update_object_payloads", None)
            if callable(bulk_update):
                changed = int(bulk_update(payloads_by_guid) or 0)
            else:
                for obj_guid, payload in payloads_by_guid.items():
                    self._service.update_object_payload(obj_guid, payload)
                changed = len(payloads_by_guid)

        if changed:
            try:
                self.reopen_db()
            except Exception:
                pass
            try:
                self.refresh_from_runtime()
            except Exception:
                try:
                    self.start_background_runtime_refresh()
                except Exception:
                    pass

        return {
            "scanned": int(diag.get("scanned") or 0),
            "changed": changed,
            "mismatched": int(diag.get("mismatched") or 0),
            "repaired": repaired,
        }

    def sync_subsystem_membership(
        self,
        *,
        guid: str = "",
        name: str = "",
        title: str = "",
    ) -> dict[str, Any]:
        """Diagnose subsystem membership, repair mismatches, and return the final report."""

        before = ConfiguratorVmRuntimeMixin.diagnose_subsystem_membership(self, guid=guid, name=name, title=title)
        repair: dict[str, Any] = {"scanned": int(before.get("scanned") or 0), "changed": 0, "mismatched": int(before.get("mismatched") or 0), "repaired": []}
        if int(before.get("mismatched") or 0):
            repair_fn = getattr(self, "repair_subsystem_membership", None)
            if callable(repair_fn):
                repair = dict(repair_fn(guid=guid, name=name, title=title) or {})
            else:
                repair = dict(
                    ConfiguratorVmRuntimeMixin.repair_subsystem_membership(self, guid=guid, name=name, title=title)  # type: ignore[misc]
                    or {}
                )
        after = ConfiguratorVmRuntimeMixin.diagnose_subsystem_membership(self, guid=guid, name=name, title=title)
        after["before"] = before
        after["repair"] = repair
        after["auto_repaired"] = bool(int(repair.get("changed") or 0))
        after["changed"] = int(repair.get("changed") or 0)
        after["mismatched_before"] = int(before.get("mismatched") or 0)
        after["mismatched_after"] = int(after.get("mismatched") or 0)
        return after

    def repair_source_structure(
        self,
        *,
        source_path: str = "",
        source_kind: str = "",
    ) -> dict[str, Any]:
        """Repair subtree structure based on a source structure compare report."""

        compare_fn = getattr(self, "compare_source_structure", None)
        if callable(compare_fn):
            report = compare_fn(source_path=source_path, source_kind=source_kind)
        else:
            report = ConfiguratorVmRuntimeMixin.compare_source_structure(
                self,
                source_path=source_path,
                source_kind=source_kind,
            )
        items = list(report.get("flattened_subtrees") or [])
        if not items:
            return {
                "changed": 0,
                "scanned": 0,
                "repaired": [],
                "unresolved": [],
                "report": report,
            }

        db_objects = list(self.list_objects() or [])
        db_by_guid = {
            str(getattr(obj, "guid", "") or "").strip(): obj
            for obj in db_objects
            if str(getattr(obj, "guid", "") or "").strip()
        }

        changed = 0
        repaired: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []

        for entry in items:
            parent_guid = str(entry.get("parent_guid") or "").strip()
            parent_obj = db_by_guid.get(parent_guid)
            source_child_names = [
                str(x).strip()
                for x in list(entry.get("source_child_names") or [])
                if str(x).strip()
            ]
            relocated_children = list(entry.get("relocated_children") or [])
            if parent_obj is None:
                unresolved.append(
                    {
                        "parent_guid": parent_guid,
                        "parent_title": str(entry.get("parent_title") or "").strip(),
                        "relocated_children": relocated_children,
                        "reason": "missing_parent",
                    }
                )
                continue

            parent_payload = dict(self.manifest_get_payload(parent_guid) or {})
            current_children = [
                str(x).strip()
                for x in list(parent_payload.get("child_subsystems") or [])
                if str(x).strip()
            ]
            if source_child_names and current_children != source_child_names:
                parent_payload["child_subsystems"] = source_child_names
                self._service.update_object_fields(parent_guid, parent_guid=str(getattr(parent_obj, "parent_guid", "") or ""), payload=parent_payload)
                changed += 1
                repaired.append(
                    {
                        "kind": "parent_children",
                        "parent_guid": parent_guid,
                        "child_subsystems_before": current_children,
                        "child_subsystems_after": source_child_names,
                    }
                )

            for child in relocated_children:
                child_guid = str(child.get("guid") or "").strip()
                if not child_guid or child_guid not in db_by_guid:
                    unresolved.append(
                        {
                            "parent_guid": parent_guid,
                            "child_guid": child_guid,
                            "reason": "missing_child",
                        }
                    )
                    continue
                child_obj = db_by_guid[child_guid]
                current_parent = str(getattr(child_obj, "parent_guid", "") or "").strip()
                if current_parent == parent_guid:
                    continue
                child_payload = self.manifest_get_payload(child_guid)
                self._service.update_object_fields(
                    child_guid,
                    parent_guid=parent_guid,
                    payload=child_payload if isinstance(child_payload, dict) else {},
                )
                changed += 1
                repaired.append(
                    {
                        "kind": "child_parent",
                        "guid": child_guid,
                        "parent_guid_before": current_parent,
                        "parent_guid_after": parent_guid,
                    }
                )

        if changed:
            try:
                self.reopen_db()
            except Exception:
                pass
            try:
                self.refresh_from_runtime()
            except Exception:
                try:
                    self.start_background_runtime_refresh()
                except Exception:
                    pass

        return {
            "changed": changed,
            "scanned": len(items),
            "repaired": repaired,
            "unresolved": unresolved,
            "report": report,
        }

    def compare_source_structure(
        self,
        *,
        source_path: str = "",
        source_kind: str = "",
    ) -> dict[str, Any]:
        """Compare imported source structure with the current manifest snapshot."""

        src_path = str(source_path or "").strip()
        src_kind = str(source_kind or "").strip() or "auto"
        if not src_path:
            try:
                from src.platform.onec_import_state import load_last_onec_import

                last = load_last_onec_import()
                src_path = str(last.get("source_path") or "").strip()
                if not source_kind:
                    src_kind = str(last.get("source_kind") or src_kind).strip() or src_kind
            except Exception:
                src_path = ""
        if not src_path:
            raise RuntimeError("source_path is required")

        from src.infra.onec.source_structure_compare import build_source_structure_compare_report

        db_objects = list(self.list_objects() or [])
        return build_source_structure_compare_report(
            source_path=src_path,
            source_kind=src_kind,
            db_objects=db_objects,
            db_payload_getter=lambda guid: dict(self.manifest_get_payload(guid) or {}),
        )
