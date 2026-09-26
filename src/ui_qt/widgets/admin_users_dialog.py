"""admin_users_dialog.py — Full-featured user management dialog."""
from __future__ import annotations

import os
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QSortFilterProxyModel, QTimer
from PySide6.QtGui import QStandardItem, QStandardItemModel, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox,
    QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSizePolicy,
    QTableView, QToolBar, QVBoxLayout, QWidget,
)

from src.ui_qt.i18n import t


# ── helpers ──────────────────────────────────────────────────────────────────

def _fmt_ts(ts_ms) -> str:
    try:
        ms = int(ts_ms or 0)
        if ms <= 0:
            return ""
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _hash_password(plain: str) -> str:
    if not plain:
        return ""
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def _new_guid() -> str:
    b = bytearray(os.urandom(16))
    b[6] = (b[6] & 0x0F) | 0x40
    b[8] = (b[8] & 0x3F) | 0x80
    h = bytes(b).hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _now_ms() -> int:
    import time
    return int(time.time() * 1000)


# ── User edit form ────────────────────────────────────────────────────────────

class _UserEditDialog(QDialog):
    """Create / edit a single user."""

    def __init__(self, parent=None, *, row: Optional[Dict] = None):
        super().__init__(parent)
        self._is_new = row is None
        self._original = dict(row or {})

        self.setWindowTitle(t("ctx_create") if self._is_new else t("btn_edit"))
        self.setModal(True)
        self.setMinimumWidth(400)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Form fields
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(8)

        self.ed_login = QLineEdit()
        self.ed_login.setPlaceholderText("ivan.petrenko")
        form.addRow(t("admin_col_login") + ":", self.ed_login)

        self.ed_display = QLineEdit()
        self.ed_display.setPlaceholderText(t("admin_user_display_placeholder"))
        form.addRow(t("admin_col_display_name") + ":", self.ed_display)

        self.ed_password = QLineEdit()
        self.ed_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_password.setPlaceholderText(
            "" if self._is_new else t("admin_user_password_keep_hint")
        )
        form.addRow(
            t("admin_user_password") if self._is_new else t("admin_user_new_password"),
            self.ed_password,
        )

        if not self._is_new:
            self.ed_confirm = QLineEdit()
            self.ed_confirm.setEchoMode(QLineEdit.EchoMode.Password)
            self.ed_confirm.setPlaceholderText(t("admin_user_password_confirm_hint"))
            form.addRow(t("admin_user_password_confirm"), self.ed_confirm)
        else:
            self.ed_confirm = None

        layout.addLayout(form)

        self.chk_active = QCheckBox(t("admin_col_active"))
        self.chk_active.setChecked(True)
        layout.addWidget(self.chk_active)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # Buttons
        self.bbox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.bbox.accepted.connect(self._on_accept)
        self.bbox.rejected.connect(self.reject)
        layout.addWidget(self.bbox)

        # Populate if editing
        if not self._is_new:
            self.ed_login.setText(str(row.get("login") or ""))
            self.ed_display.setText(str(row.get("display_name") or ""))
            self.chk_active.setChecked(bool(row.get("is_active", True)))
            # login immutable for existing users
            self.ed_login.setReadOnly(True)
            self.ed_login.setStyleSheet("QLineEdit { color: #64748B; }")

    def _on_accept(self) -> None:
        login = self.ed_login.text().strip()
        display = self.ed_display.text().strip()
        pwd = self.ed_password.text()

        if not login:
            QMessageBox.warning(self, t("warn_title"), t("admin_user_login_required"))
            return
        if self._is_new and not pwd:
            QMessageBox.warning(self, t("warn_title"), t("admin_user_password_required"))
            return
        if self.ed_confirm is not None and pwd:
            if pwd != self.ed_confirm.text():
                QMessageBox.warning(self, t("warn_title"), t("admin_user_password_mismatch"))
                return

        self.accept()

    def result_data(self) -> Dict[str, Any]:
        login = self.ed_login.text().strip()
        display = self.ed_display.text().strip() or login
        pwd = self.ed_password.text()
        is_active = self.chk_active.isChecked()

        data: Dict[str, Any] = {
            "login": login,
            "display_name": display,
            "is_active": is_active,
        }
        if self._is_new:
            data["user_id"] = _new_guid()
            data["created_at"] = _now_ms()
            data["password_hash"] = _hash_password(pwd)
        else:
            data["user_id"] = self._original.get("user_id", "")
            data["created_at"] = self._original.get("created_at", 0)
            if pwd:
                data["password_hash"] = _hash_password(pwd)
            else:
                data["password_hash"] = self._original.get("password_hash", "")
        return data


# ── Main dialog ───────────────────────────────────────────────────────────────

_COL_LOGIN    = 0
_COL_DISPLAY  = 1
_COL_ACTIVE   = 2
_COL_CREATED  = 3
_COL_UID      = 4
_COL_COUNT    = 5

_SYSTEM_LOGINS = {"system"}


class UsersAdminDialog(QDialog):
    """Full-featured user management dialog matching 1C UX style."""

    _CSS = """
        QDialog { background: #FFFFFF; }
        QTableView {
            background: #FFFFFF;
            alternate-background-color: #F8FAFC;
            gridline-color: rgba(0,0,0,0.06);
            selection-background-color: #DBEAFE;
            selection-color: #0F172A;
            border: 1px solid rgba(0,0,0,0.10);
            font-size: 10pt;
        }
        QTableView::item { padding: 4px 8px; }
        QHeaderView::section {
            background: #F1F5F9;
            color: #374151;
            padding: 6px 8px;
            border: none;
            border-bottom: 1px solid rgba(0,0,0,0.10);
            border-right: 1px solid rgba(0,0,0,0.06);
            font-weight: 600;
        }
        QToolBar {
            background: #F8FAFC;
            border-bottom: 1px solid rgba(0,0,0,0.08);
            spacing: 2px;
            padding: 2px 4px;
        }
        QPushButton#BtnPrimary {
            background: #2563EB; color: #FFFFFF;
            border: none; border-radius: 6px;
            padding: 4px 14px; font-weight: 600;
        }
        QPushButton#BtnPrimary:hover { background: #1D4ED8; }
        QPushButton#BtnSecondary {
            background: #FFFFFF; color: #374151;
            border: 1px solid rgba(0,0,0,0.14); border-radius: 6px;
            padding: 4px 14px;
        }
        QPushButton#BtnSecondary:hover { background: #F1F5F9; }
        QPushButton#BtnDanger {
            background: #FEF2F2; color: #DC2626;
            border: 1px solid #FECACA; border-radius: 6px;
            padding: 4px 14px;
        }
        QPushButton#BtnDanger:hover { background: #FEE2E2; }
        QLineEdit {
            border: 1px solid rgba(0,0,0,0.14); border-radius: 6px;
            padding: 4px 8px; background: #FFFFFF; color: #0F172A;
        }
        QLineEdit:focus { border-color: #2563EB; }
        QLabel#CountLabel { color: #64748B; font-size: 9pt; }
    """

    def __init__(self, parent=None, *, title: str, rows: List[Dict],
                 db=None):
        super().__init__(parent)
        self._db = db
        self._all_rows: List[Dict] = list(rows)

        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(940, 560)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setStyleSheet(self._CSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Toolbar ──────────────────────────────────────────────────────────
        toolbar = QWidget()
        toolbar.setObjectName("Toolbar")
        toolbar.setStyleSheet("QWidget#Toolbar { background:#F8FAFC; border-bottom:1px solid rgba(0,0,0,0.08); }")
        tb_l = QHBoxLayout(toolbar)
        tb_l.setContentsMargins(8, 6, 8, 6)
        tb_l.setSpacing(4)

        def _btn(label: str, obj: str) -> QPushButton:
            b = QPushButton(label)
            b.setObjectName(obj)
            b.setFixedHeight(30)
            return b

        self.btn_create = _btn("+ " + t("ctx_create"), "BtnPrimary")
        self.btn_edit   = _btn("✏  " + t("btn_edit"),   "BtnSecondary")
        self.btn_delete = _btn("🗑  " + t("btn_delete"), "BtnDanger")
        self.btn_toggle = _btn("⏸  " + t("btn_deactivate"), "BtnSecondary")
        self.btn_refresh = _btn("↻  " + t("act_refresh"), "BtnSecondary")

        for b in (self.btn_create, self.btn_edit, self.btn_delete, self.btn_toggle, self.btn_refresh):
            tb_l.addWidget(b)

        tb_l.addStretch()

        # Search
        self._search = QLineEdit()
        self._search.setPlaceholderText(t("ph_search_dots"))
        self._search.setFixedWidth(220)
        self._search.setFixedHeight(30)
        tb_l.addWidget(self._search)

        root.addWidget(toolbar)

        # ── Table ─────────────────────────────────────────────────────────────
        self._model = QStandardItemModel(0, _COL_COUNT, self)
        self._model.setHorizontalHeaderLabels([
            t("admin_col_login"),
            t("admin_col_display_name"),
            t("admin_col_active"),
            t("admin_col_created_at"),
            t("admin_col_user_id"),
        ])

        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)  # search all columns

        self.table = QTableView()
        self.table.setModel(self._proxy)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.table.horizontalHeader().setStretchLastSection(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self.table, 1)

        # ── Status bar ────────────────────────────────────────────────────────
        footer = QWidget()
        footer.setStyleSheet("QWidget { background: #F8FAFC; border-top: 1px solid rgba(0,0,0,0.08); }")
        f_l = QHBoxLayout(footer)
        f_l.setContentsMargins(10, 4, 10, 4)
        self._lbl_count = QLabel()
        self._lbl_count.setObjectName("CountLabel")
        f_l.addWidget(self._lbl_count)
        f_l.addStretch()

        close_btn = QPushButton(t("btn_close"))
        close_btn.setObjectName("BtnSecondary")
        close_btn.setFixedHeight(30)
        close_btn.clicked.connect(self.accept)
        f_l.addWidget(close_btn)

        root.addWidget(footer)

        # ── Connections ───────────────────────────────────────────────────────
        self.btn_create.clicked.connect(self._on_create)
        self.btn_edit.clicked.connect(self._on_edit)
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_toggle.clicked.connect(self._on_toggle)
        self.btn_refresh.clicked.connect(self._reload_from_db)
        self.table.doubleClicked.connect(lambda _: self._on_edit())
        self._search.textChanged.connect(self._proxy.setFilterFixedString)
        self.table.selectionModel().selectionChanged.connect(self._update_button_states)

        # Populate
        self._populate(self._all_rows)
        self._update_button_states()

    # ── Data ─────────────────────────────────────────────────────────────────

    def _populate(self, rows: List[Dict]) -> None:
        self._model.removeRows(0, self._model.rowCount())
        for r in rows:
            self._append_row(r)
        self._update_count()

    def _append_row(self, r: Dict) -> None:
        login      = str(r.get("login") or "")
        display    = str(r.get("display_name") or "")
        is_active  = bool(r.get("is_active", True))
        created_at = _fmt_ts(r.get("created_at"))
        user_id    = str(r.get("user_id") or "")

        items = [
            QStandardItem(login),
            QStandardItem(display),
            QStandardItem(t("yes") if is_active else t("no")),
            QStandardItem(created_at),
            QStandardItem(user_id),
        ]
        # Gray out inactive rows
        if not is_active:
            for it in items:
                it.setForeground(QColor("#94A3B8"))

        # Store full row data
        items[0].setData(r, Qt.ItemDataRole.UserRole)
        self._model.appendRow(items)

    def _current_row_data(self) -> Optional[Dict]:
        idxs = self.table.selectionModel().selectedRows()
        if not idxs:
            return None
        src = self._proxy.mapToSource(idxs[0])
        it = self._model.item(src.row(), 0)
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _update_count(self) -> None:
        total = self._model.rowCount()
        visible = self._proxy.rowCount()
        self._lbl_count.setText(
            t("admin_user_count").format(total=total)
            if total == visible
            else t("admin_user_count_filtered").format(total=total, visible=visible)
        )

    def _update_button_states(self) -> None:
        row = self._current_row_data()
        has = row is not None
        is_system = has and str(row.get("login") or "") in _SYSTEM_LOGINS

        self.btn_edit.setEnabled(has)
        self.btn_delete.setEnabled(has and not is_system)

        if has:
            active = bool(row.get("is_active", True))
            self.btn_toggle.setText(
                ("⏸  " + t("btn_deactivate"))
                if active else ("▶  " + t("btn_activate"))
            )
            self.btn_toggle.setEnabled(not is_system)
        else:
            self.btn_toggle.setEnabled(False)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_create(self) -> None:
        dlg = _UserEditDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.result_data()
        if self._db is not None:
            try:
                self._db.table("sys_users").insert(data)
                self._all_rows.append(data)
                self._append_row(data)
                self._update_count()
            except Exception as e:
                QMessageBox.warning(self, t("dlg_error_title"), str(e))
        else:
            self._all_rows.append(data)
            self._append_row(data)
            self._update_count()

    def _on_edit(self) -> None:
        row = self._current_row_data()
        if row is None:
            return
        dlg = _UserEditDialog(self, row=row)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.result_data()
        if self._db is not None:
            try:
                self._db.table("sys_users").update(
                    where={"user_id": data["user_id"]},
                    set_values={k: v for k, v in data.items() if k != "user_id"},
                )
            except Exception as e:
                QMessageBox.warning(self, t("dlg_error_title"), str(e))
                return
        # Update in-memory list
        for i, r in enumerate(self._all_rows):
            if str(r.get("user_id") or "") == str(data.get("user_id") or ""):
                self._all_rows[i] = data
                break
        self._populate(self._all_rows)

    def _on_delete(self) -> None:
        row = self._current_row_data()
        if row is None:
            return
        login = str(row.get("login") or "")
        if login in _SYSTEM_LOGINS:
            QMessageBox.warning(
                self,
                t("warn_title"),
                t("admin_user_system_delete_forbidden"),
            )
            return
        ans = QMessageBox.question(
            self, t("dlg_confirm_title"),
            t("admin_user_delete_confirm").format(login=login),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        uid = str(row.get("user_id") or "")
        if self._db is not None:
            try:
                self._db.table("sys_users").delete(where={"user_id": uid})
            except Exception as e:
                QMessageBox.warning(self, t("dlg_error_title"), str(e))
                return
        self._all_rows = [r for r in self._all_rows if str(r.get("user_id") or "") != uid]
        self._populate(self._all_rows)

    def _on_toggle(self) -> None:
        row = self._current_row_data()
        if row is None:
            return
        uid = str(row.get("user_id") or "")
        new_state = not bool(row.get("is_active", True))
        if self._db is not None:
            try:
                self._db.table("sys_users").update(
                    where={"user_id": uid},
                    set_values={"is_active": new_state},
                )
            except Exception as e:
                QMessageBox.warning(self, t("dlg_error_title"), str(e))
                return
        for r in self._all_rows:
            if str(r.get("user_id") or "") == uid:
                r["is_active"] = new_state
                break
        self._populate(self._all_rows)

    def _reload_from_db(self) -> None:
        if self._db is None:
            return
        try:
            rows = self._db.table("sys_users").select() or []
            self._all_rows = list(rows)
            self._populate(self._all_rows)
        except Exception as e:
            QMessageBox.warning(self, t("dlg_error_title"), str(e))
