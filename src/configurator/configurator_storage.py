from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtGui import QAction, QStandardItem
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMenu, QMessageBox

from src.configurator.application import repo_bridge
from src.configurator.application.repo_bridge import CheckoutRequest
from src.ui_qt.i18n import t
from src.ui_qt.widgets.dsl_editor_dialog import DslEditorDialog


class ConfiguratorStorageMixin:
    def _repo_get_main_db_path(self) -> str:
        return str(self._settings.value("repo/main_db_path", "") or "").strip()

    def configure_main_db_for_repo(self) -> None:
        current = self._repo_get_main_db_path()
        path, _ = QFileDialog.getOpenFileName(
            self,
            t("admin_repo_configure"),
            current or str(self.db_path.parent),
            "MPDB (*.mpdb);;All files (*.*)",
        )
        path = str(path or "").strip()
        if not path:
            return
        self._settings.setValue("repo/main_db_path", path)
        self.set_status(t("admin_repo_main_db_set"))

    def _repo_pick_component(self) -> tuple[str, str]:
        items = ["Object", "ObjectModule", "Form", "FormModule"]
        ct, ok = QInputDialog.getItem(self, t("admin_repo_component"), t("admin_repo_component"), items, 0, False)
        if not ok:
            return "", ""
        ct = str(ct or "").strip()
        cid = "-"
        if ct in {"Form", "FormModule"}:
            cid, ok = QInputDialog.getText(self, t("admin_repo_component_id"), t("admin_repo_component_id"))
            if not ok:
                return "", ""
            cid = str(cid or "").strip() or "-"
        return ct, cid

    def _repo_get_selected_meta(self) -> Optional[dict]:
        idx = self.tree.currentIndex()
        if not idx.isValid():
            return None
        try:
            meta = idx.data(self.ROLE_META)
        except Exception:
            meta = None
        return meta if isinstance(meta, dict) else None

    def repo_checkout_selected(self) -> None:
        main_db = self._repo_get_main_db_path()
        if not main_db:
            self.configure_main_db_for_repo()
            main_db = self._repo_get_main_db_path()
            if not main_db:
                return
        meta = self._repo_get_selected_meta()
        if not meta:
            self.show_warning(t("warn_title"), t("warn_select_object"))
            return
        ct, cid = self._repo_pick_component()
        if not ct:
            return
        obj_id = str(meta.get("guid") or "").strip()
        obj_type = str(meta.get("type") or meta.get("obj_type") or "Object").strip() or "Object"
        if not obj_id:
            self.show_warning(t("warn_title"), t("warn_select_object"))
            return
        comment, _ok = QInputDialog.getText(self, t("admin_repo_comment"), t("admin_repo_comment"))
        comment = str(comment or "").strip()
        try:
            lock_key = repo_bridge.checkout(
                CheckoutRequest(
                    repo_db_path=str(self.db_path),
                    main_db_path=main_db,
                    user_id="system",
                    object_type=obj_type,
                    object_id=obj_id,
                    component_type=ct,
                    component_id=cid,
                    comment=comment,
                )
            )
            self.set_status(t("admin_repo_checkout_ok") + f": {lock_key}")
            self.refreshRequested.emit()
        except Exception as e:
            self.show_warning(t("warn_title"), f"{t('admin_repo_checkout_failed')}: {e}")

    def repo_submit_selected(self) -> None:
        meta = self._repo_get_selected_meta()
        if not meta:
            self.show_warning(t("warn_title"), t("warn_select_object"))
            return
        ct, cid = self._repo_pick_component()
        if not ct:
            return
        obj_id = str(meta.get("guid") or "").strip()
        if not obj_id:
            self.show_warning(t("warn_title"), t("warn_select_object"))
            return
        if not self.confirm(t("admin_repo_submit"), t("admin_repo_confirm_submit")):
            return
        try:
            repo_bridge.submit(
                repo_db_path=str(self.db_path),
                object_id=obj_id,
                component_type=ct,
                component_id=cid,
                user_id="system",
                force=False,
            )
            self.set_status(t("admin_repo_submit_ok"))
        except Exception as e:
            self.show_warning(t("warn_title"), f"{t('admin_repo_submit_failed')}: {e}")

    def repo_force_unlock_selected(self) -> None:
        main_db = self._repo_get_main_db_path()
        if not main_db:
            self.configure_main_db_for_repo()
            main_db = self._repo_get_main_db_path()
            if not main_db:
                return
        meta = self._repo_get_selected_meta()
        if not meta:
            self.show_warning(t("warn_title"), t("warn_select_object"))
            return
        ct, cid = self._repo_pick_component()
        if not ct:
            return
        obj_id = str(meta.get("guid") or "").strip()
        obj_type = str(meta.get("type") or meta.get("obj_type") or "Object").strip() or "Object"
        lock_key = f"{obj_type}/{obj_id}/{ct}/{cid or '-'}"
        if not self.confirm(t("admin_repo_force_unlock"), t("admin_repo_confirm_force_unlock") + f"\n\n{lock_key}"):
            return
        try:
            ok = repo_bridge.force_unlock(main_db_path=main_db, lock_key=lock_key, user_id="system")
            if ok:
                self.set_status(t("admin_repo_force_unlock_ok"))
            else:
                self.show_warning(t("warn_title"), t("admin_repo_force_unlock_failed"))
        except Exception as e:
            self.show_warning(t("warn_title"), f"{t('admin_repo_force_unlock_failed')}: {e}")

    def _maybe_add_config_storage_submenu(self, menu: QMenu, item: QStandardItem, meta: dict) -> None:
        if not isinstance(meta, dict):
            return
        kind = str(meta.get("kind") or "")
        if kind != "object":
            return
        sub = menu.addMenu(t("ctx_storage_menu"))
        conn = self._config_storage.connection()
        if conn is None:
            act_connect = sub.addAction(t("ctx_storage_connect"))
            act_connect.triggered.connect(self._storage_connect_dialog)
            return
        target = self._resolve_storage_target(item, meta)
        if target is None:
            sub.setEnabled(False)
            return
        object_type, object_id, default_component_type, component_id = target

        def lk(ct: str, cid: str | None) -> str:
            return f"{object_type}/{object_id}/{(ct or '').strip() or 'Object'}/{(cid or '-').strip() or '-'}"

        act_take_obj = sub.addAction(t("ctx_storage_checkout_object"))
        act_take_obj.triggered.connect(
            lambda _=False, ot=object_type, oid=object_id: self._storage_checkout(ot, oid, "Object", "-")
        )
        act_take_mod = sub.addAction(t("ctx_storage_checkout_object_module"))
        act_take_mod.triggered.connect(
            lambda _=False, ot=object_type, oid=object_id: self._storage_checkout(ot, oid, "ObjectModule", "-")
        )
        if default_component_type == "Form":
            act_take_form_mod = sub.addAction(t("ctx_storage_checkout_form_module"))
            act_take_form_mod.triggered.connect(
                lambda _=False, ot=object_type, oid=object_id, cid=component_id: self._storage_checkout(
                    ot, oid, "FormModule", cid
                )
            )

        sub.addSeparator()

        put_menu = sub.addMenu(t("ctx_storage_put"))
        put_any = False

        def _add_put(ct: str, cid: str | None, title: str) -> None:
            nonlocal put_any
            k = lk(ct, cid)
            a = put_menu.addAction(title)
            token = self._config_storage.local_lock_token(k)
            a.setEnabled(bool(token))
            if token:
                put_any = True
            a.triggered.connect(lambda _=False, key=k: self._storage_put(key, meta))

        _add_put("Object", "-", t("ctx_storage_put_object"))
        _add_put("ObjectModule", "-", t("ctx_storage_put_object_module"))
        if default_component_type == "Form":
            _add_put("FormModule", component_id, t("ctx_storage_put_form_module"))
        if not put_any:
            put_menu.setEnabled(False)

        get_menu = sub.addMenu(t("ctx_storage_get"))

        def _add_get(ct: str, cid: str | None, title: str) -> None:
            k = lk(ct, cid)
            a = get_menu.addAction(title)
            a.triggered.connect(lambda _=False, key=k: self._storage_get(key, meta))

        _add_get("Object", "-", t("ctx_storage_get_object"))
        _add_get("ObjectModule", "-", t("ctx_storage_get_object_module"))
        if default_component_type == "Form":
            _add_get("FormModule", component_id, t("ctx_storage_get_form_module"))

        hist_menu = sub.addMenu(t("ctx_storage_history"))

        def _add_hist(ct: str, cid: str | None, title: str) -> None:
            k = lk(ct, cid)
            a = hist_menu.addAction(title)
            a.triggered.connect(lambda _=False, key=k: self._storage_history(key))

        _add_hist("Object", "-", t("ctx_storage_history_object"))
        _add_hist("ObjectModule", "-", t("ctx_storage_history_object_module"))
        if default_component_type == "Form":
            _add_hist("FormModule", component_id, t("ctx_storage_history_form_module"))

        act_abandon = sub.addAction(t("ctx_storage_abandon"))
        act_abandon.triggered.connect(
            lambda _=False, ot=object_type, oid=object_id: self._storage_abandon_all_for_object(ot, oid)
        )
        act_force = sub.addAction(t("ctx_storage_force_unlock"))
        act_force.triggered.connect(
            lambda _=False, ot=object_type, oid=object_id: self._storage_force_unlock_dialog(ot, oid)
        )

    def _resolve_storage_target(self, item: QStandardItem, meta: dict) -> Optional[tuple[str, str, str, str]]:
        try:
            tpe = str(meta.get("type") or "").strip()
            guid = str(meta.get("guid") or "").strip()
            name = str(meta.get("name") or meta.get("title") or "").strip()
            if not tpe or not guid:
                return None
            if tpe in ("form", "common_form"):
                owner = self._find_owner_object_for_form(item)
                if owner is not None:
                    ot = str(owner.get("type") or "").strip() or tpe
                    oid = str(owner.get("guid") or "").strip() or guid
                    cid = name or guid
                    return (ot, oid, "Form", cid)
            return (tpe, guid, "Object", "-")
        except Exception:
            return None

    def _find_owner_object_for_form(self, item: QStandardItem) -> Optional[dict]:
        cur = item
        for _ in range(8):
            try:
                cur = cur.parent()
            except Exception:
                return None
            if cur is None:
                return None
            m = cur.data(self.ROLE_META) or {}
            if not isinstance(m, dict):
                continue
            if str(m.get("kind") or "") != "object":
                continue
            payload = m.get("payload") if isinstance(m.get("payload"), dict) else {}
            if payload.get("system"):
                continue
            return m
        return None

    def _open_dsl_editor(self) -> None:
        dlg = DslEditorDialog(self)
        dlg.exec()

    def _storage_connect_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("dlg_storage_pick"), str(Path.home()), "*.mpdb")
        if not path:
            return
        try:
            self._config_storage.connect(Path(path))
            try:
                self._storage_hb_timer.start()
            except Exception:
                pass
            QMessageBox.information(self, t("dlg_storage_title"), t("dlg_storage_connected"))
        except Exception as e:
            QMessageBox.warning(self, t("dlg_error_title"), f"{t('dlg_storage_connect_failed')}\n\n{e}")

    def _cfg_storage_disconnect(self) -> None:
        try:
            self._config_storage.disconnect()
            try:
                self._storage_hb_timer.stop()
            except Exception:
                pass
            QMessageBox.information(self, t("dlg_storage_title"), t("dlg_storage_disconnected"))
        except Exception as e:
            QMessageBox.warning(self, t("dlg_error_title"), f"{t('dlg_storage_disconnect_failed')}\n\n{e}")

    def _cfg_storage_status(self) -> None:
        conn = self._config_storage.connection()
        if conn is None:
            QMessageBox.information(self, t("dlg_storage_title"), t("dlg_storage_not_connected"))
            return
        QMessageBox.information(self, t("dlg_storage_title"), t("dlg_storage_status_path").format(path=str(conn.path)))

    def _cfg_storage_history_storage(self) -> None:
        try:
            commits = self._config_storage.list_storage_commits(limit=30)
            if not commits:
                QMessageBox.information(self, t("dlg_storage_history_title"), t("dlg_storage_history_empty"))
                return
            from datetime import datetime

            lines = []
            for c in commits:
                ts = int(c.get("ts") or 0)
                dt = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M:%S") if ts else "-"
                user = str(c.get("user_id") or "")
                cid = str(c.get("commit_id") or "")[:8]
                msg = str(c.get("message") or "")
                lines.append(f"{dt}  {user}  {cid}  {msg}")
            QMessageBox.information(self, t("dlg_storage_history_title"), "\n".join(lines))
        except Exception as e:
            QMessageBox.warning(self, t("dlg_error_title"), f"{e}")

    def _cfg_storage_admin(self) -> None:
        try:
            locks = self._config_storage.list_active_locks()
        except Exception as e:
            QMessageBox.warning(self, t("dlg_error_title"), f"{e}")
            return
        if not locks:
            QMessageBox.information(self, t("dlg_storage_admin_title"), t("dlg_storage_admin_no_locks"))
            return
        from datetime import datetime

        lines = []
        for r in locks:
            lk = str(r.get("lock_key") or "")
            who = str(r.get("locked_by") or "")
            active = bool(r.get("session_is_active") or r.get("session_active"))
            last_seen = int(r.get("session_last_seen_at") or r.get("session_last_seen_at") or 0)
            last_seen_s = datetime.fromtimestamp(last_seen / 1000).strftime("%Y-%m-%d %H:%M:%S") if last_seen else "-"
            flag = t("storage_session_active") if active else t("storage_session_stale")
            lines.append(f"{lk}  [{who}]  {flag}  {t('storage_session_last_seen')}={last_seen_s}")
        res = QMessageBox.question(
            self,
            t("dlg_storage_admin_title"),
            t("dlg_storage_admin_list").format(items="\n".join(lines)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if res != QMessageBox.StandardButton.Yes:
            return
        lk, ok = QInputDialog.getText(self, t("dlg_storage_admin_title"), t("dlg_storage_admin_force_prompt"))
        if not ok:
            return
        lk = str(lk or "").strip()
        if not lk:
            return
        try:
            ok2 = self._config_storage.force_release_lock(lock_key=lk, user_id="SYSTEM")
            if ok2:
                QMessageBox.information(self, t("dlg_storage_admin_title"), t("dlg_storage_admin_force_done"))
            else:
                QMessageBox.information(self, t("dlg_storage_admin_title"), t("dlg_storage_admin_force_not_found"))
        except Exception as e:
            QMessageBox.warning(self, t("dlg_error_title"), f"{e}")

    def _storage_checkout(self, object_type: str, object_id: str, component_type: str, component_id: str) -> None:
        comment, ok = QInputDialog.getText(self, t("dlg_storage_title"), t("dlg_storage_comment"))
        if not ok:
            return
        try:
            self._config_storage.checkout(
                object_type=object_type,
                object_id=object_id,
                component_type=component_type,
                component_id=component_id,
                comment=str(comment or ""),
            )
            QMessageBox.information(self, t("dlg_storage_title"), t("dlg_storage_checked_out"))
            refresh_requested = getattr(self, "refreshRequested", None)
            if refresh_requested is not None and hasattr(refresh_requested, "emit"):
                refresh_requested.emit()
        except Exception as e:
            QMessageBox.warning(self, t("dlg_error_title"), f"{t('dlg_storage_checkout_failed')}\n\n{e}")

    def _storage_abandon_all_for_object(self, object_type: str, object_id: str) -> None:
        try:
            released = self._config_storage.release_my_locks_for_object(object_type=object_type, object_id=object_id)
            QMessageBox.information(self, t("dlg_storage_title"), t("dlg_storage_abandoned").format(count=released))
            refresh_requested = getattr(self, "refreshRequested", None)
            if refresh_requested is not None and hasattr(refresh_requested, "emit"):
                refresh_requested.emit()
        except Exception as e:
            QMessageBox.warning(self, t("dlg_error_title"), f"{t('dlg_storage_abandon_failed')}\n\n{e}")

    def _storage_force_unlock_dialog(self, object_type: str, object_id: str) -> None:
        res = QMessageBox.question(
            self,
            t("dlg_storage_title"),
            t("dlg_storage_force_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if res != QMessageBox.StandardButton.Yes:
            return
        try:
            released = self._config_storage.force_release_locks_for_object(object_type=object_type, object_id=object_id)
            QMessageBox.information(self, t("dlg_storage_title"), t("dlg_storage_force_done").format(count=released))
            refresh_requested = getattr(self, "refreshRequested", None)
            if refresh_requested is not None and hasattr(refresh_requested, "emit"):
                refresh_requested.emit()
        except Exception as e:
            QMessageBox.warning(self, t("dlg_error_title"), f"{t('dlg_storage_force_failed')}\n\n{e}")

    def _storage_put(self, lock_key: str, meta: dict) -> None:
        if self._vm is None:
            return
        guid = str((meta or {}).get("guid") or "").strip()
        if not guid:
            QMessageBox.warning(self, t("dlg_error_title"), t("msg_guid_missing"))
            return
        msg, ok = QInputDialog.getText(self, t("dlg_storage_title"), t("dlg_storage_put_comment"))
        if not ok:
            return
        try:
            from src.configurator.persistence.object_locks import parse_lock_key

            obj = None
            for o in self._vm.list_objects():
                if getattr(o, "guid", "") == guid:
                    obj = o
                    break
            full_payload = obj.payload if (obj is not None and isinstance(obj.payload, dict)) else (
                meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
            )

            lk = parse_lock_key(lock_key)
            ct = str(lk.component_type if lk is not None else "Object")
            cid = str(lk.component_id if lk is not None else "-")

            if ct == "FormModule":
                payload = {}
                for k in ("form_model", "form_module", "module"):
                    if k in full_payload:
                        payload[k] = full_payload.get(k)
            elif ct == "ObjectModule":
                payload = {}
                for k in ("module", "object_module"):
                    if k in full_payload:
                        payload[k] = full_payload.get(k)
            else:
                payload = dict(full_payload or {})

            snapshot = {
                "guid": guid,
                "type": str(meta.get("type") or ""),
                "name": str(meta.get("name") or ""),
                "title": str(meta.get("title") or meta.get("name") or ""),
                "component": {"component_type": ct, "component_id": cid},
                "payload": payload or {},
            }
            self._config_storage.submit(lock_key=lock_key, payload=snapshot, message=str(msg or ""), user_id="SYSTEM")
            QMessageBox.information(self, t("dlg_storage_title"), t("dlg_storage_put_done"))
        except Exception as e:
            QMessageBox.warning(self, t("dlg_error_title"), f"{t('dlg_storage_put_failed')}\n\n{e}")

    def _storage_get(self, lock_key: str, meta: dict) -> None:
        if self._vm is None:
            return
        guid = str((meta or {}).get("guid") or "").strip()
        if not guid:
            QMessageBox.warning(self, t("dlg_error_title"), t("msg_guid_missing"))
            return
        try:
            from src.configurator.persistence.object_locks import parse_lock_key

            snap = self._config_storage.get_latest(lock_key=lock_key)
            if not isinstance(snap, dict):
                QMessageBox.information(self, t("dlg_storage_title"), t("dlg_storage_get_none"))
                return
            res = QMessageBox.question(
                self,
                t("dlg_storage_title"),
                t("dlg_storage_get_confirm"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if res != QMessageBox.StandardButton.Yes:
                return
            payload_patch = snap.get("payload") if isinstance(snap.get("payload"), dict) else None
            if payload_patch is None:
                QMessageBox.information(self, t("dlg_storage_title"), t("dlg_storage_get_none"))
                return

            lk = parse_lock_key(lock_key)
            ct = str(lk.component_type if lk is not None else "Object")

            if ct == "Object":
                new_payload = payload_patch
            else:
                existing = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
                new_payload = dict(existing)
                new_payload.update(payload_patch)

            self._vm.set_object_payload(guid, new_payload)
            QMessageBox.information(self, t("dlg_storage_title"), t("dlg_storage_get_done"))
        except Exception as e:
            QMessageBox.warning(self, t("dlg_error_title"), f"{t('dlg_storage_get_failed')}\n\n{e}")

    def _storage_history(self, lock_key: str) -> None:
        try:
            rows = self._config_storage.history(lock_key=lock_key, limit=20)
            if not rows:
                QMessageBox.information(self, t("dlg_storage_history_title"), t("dlg_storage_get_none"))
                return
            from datetime import datetime

            lines = []
            for r in rows:
                ts = int(r.get("ts") or 0)
                dt = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M:%S") if ts else "-"
                user_id = str(r.get("user_id") or "")
                msg = str(r.get("message") or "")
                cid = str(r.get("commit_id") or "")[:8]
                lines.append(f"{dt}  {user_id}  {cid}  {msg}")
            QMessageBox.information(self, t("dlg_storage_history_title"), "\n".join(lines))
        except Exception as e:
            QMessageBox.warning(self, t("dlg_error_title"), f"{e}")
