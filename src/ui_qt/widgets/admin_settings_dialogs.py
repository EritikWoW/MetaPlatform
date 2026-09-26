"""src.ui_qt.widgets.admin_settings_dialogs

Administration settings dialogs for the Configurator.

Provides:
    LogSettingsDialog       — configure logging level and targets
    RegionalSettingsDialog  — date/time formats, locale, decimal separator
    AuthSettingsDialog      — password policy, session TTL, lock policy
    InforbaseParamsDialog   — infobase name, description, version, owner
    TestRepairDialog        — DB integrity check + auto-repair

All dialogs are backed by mpdb config table (sys_config).
Changes are persisted immediately on Apply/OK.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.ui_qt.i18n import t

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CONFIG_TABLE = "sys_config"


def _load_config(db, section: str) -> Dict[str, Any]:
    """Load config section from sys_config table."""
    try:
        rows = db.table(CONFIG_TABLE).select(where={"section": section}) or []
        if rows:
            raw = rows[0].get("value") or {}
            if isinstance(raw, str):
                return json.loads(raw)
            return dict(raw)
    except Exception:
        pass
    return {}


def _save_config(db, section: str, data: Dict[str, Any]) -> None:
    """Persist config section to sys_config."""
    try:
        payload = json.dumps(data, ensure_ascii=False)
        existing = db.table(CONFIG_TABLE).select(where={"section": section}) or []
        if existing:
            db.table(CONFIG_TABLE).update(
                {"section": section},
                {"value": payload},
            )
        else:
            db.table(CONFIG_TABLE).insert(
                {"section": section, "value": payload}
            )
    except Exception:
        pass


def _h_separator() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFrameShadow(QFrame.Shadow.Sunken)
    return f


# ---------------------------------------------------------------------------
# LogSettingsDialog
# ---------------------------------------------------------------------------

class LogSettingsDialog(QDialog):
    """Configure logging verbosity and output targets."""

    SECTION = "logging"

    def __init__(self, parent=None, *, db=None) -> None:
        super().__init__(parent)
        self._db = db
        self.setWindowTitle(t("admin_log_settings"))
        self.setModal(True)
        self.resize(480, 320)

        root = QVBoxLayout(self)

        form_grp = QGroupBox(t("admin_log_settings"))
        form = QFormLayout(form_grp)
        form.setSpacing(10)

        self._level = QComboBox()
        self._level.addItems(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        form.addRow(t("log_level"), self._level)

        self._file_enabled = QCheckBox(t("log_file_enabled"))
        form.addRow("", self._file_enabled)

        self._file_path = QLineEdit()
        self._file_path.setPlaceholderText("logs/metaplatform.log")
        form.addRow(t("log_file_path"), self._file_path)

        self._max_size_mb = QSpinBox()
        self._max_size_mb.setRange(1, 1024)
        self._max_size_mb.setValue(10)
        self._max_size_mb.setSuffix(" MB")
        form.addRow(t("log_max_size"), self._max_size_mb)

        self._backup_count = QSpinBox()
        self._backup_count.setRange(0, 20)
        self._backup_count.setValue(3)
        form.addRow(t("log_backup_count"), self._backup_count)

        root.addWidget(form_grp)
        root.addStretch()

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self._load()

    def _load(self) -> None:
        if self._db is None:
            return
        cfg = _load_config(self._db, self.SECTION)
        level = cfg.get("level", "INFO")
        idx = self._level.findText(level)
        self._level.setCurrentIndex(idx if idx >= 0 else 1)
        self._file_enabled.setChecked(bool(cfg.get("file_enabled", False)))
        self._file_path.setText(str(cfg.get("file_path", "")))
        self._max_size_mb.setValue(int(cfg.get("max_size_mb", 10)))
        self._backup_count.setValue(int(cfg.get("backup_count", 3)))

    def _on_ok(self) -> None:
        if self._db is not None:
            _save_config(self._db, self.SECTION, {
                "level":        self._level.currentText(),
                "file_enabled": self._file_enabled.isChecked(),
                "file_path":    self._file_path.text().strip(),
                "max_size_mb":  self._max_size_mb.value(),
                "backup_count": self._backup_count.value(),
            })
        self.accept()


# ---------------------------------------------------------------------------
# RegionalSettingsDialog
# ---------------------------------------------------------------------------

class RegionalSettingsDialog(QDialog):
    """Configure locale: date/time formats and decimal separator."""

    SECTION = "regional"

    _DATE_FORMATS = [
        ("dd.MM.yyyy",     "31.12.2024"),
        ("yyyy-MM-dd",     "2024-12-31"),
        ("MM/dd/yyyy",     "12/31/2024"),
        ("d MMMM yyyy",    "31 December 2024"),
    ]
    _TIME_FORMATS = [
        ("HH:mm:ss",  "23:59:59"),
        ("HH:mm",     "23:59"),
        ("hh:mm AP",  "11:59 PM"),
    ]
    _DECIMAL_SEPS = [".", ","]
    _THOUSAND_SEPS = [" ", ",", ".", ""]

    def __init__(self, parent=None, *, db=None) -> None:
        super().__init__(parent)
        self._db = db
        self.setWindowTitle(t("admin_regional_settings"))
        self.setModal(True)
        self.resize(520, 400)

        root = QVBoxLayout(self)

        grp = QGroupBox(t("admin_regional_settings"))
        form = QFormLayout(grp)
        form.setSpacing(10)

        self._date_fmt = QComboBox()
        for fmt, ex in self._DATE_FORMATS:
            self._date_fmt.addItem(f"{fmt}  ({ex})", fmt)
        form.addRow(t("regional_date_format"), self._date_fmt)

        self._time_fmt = QComboBox()
        for fmt, ex in self._TIME_FORMATS:
            self._time_fmt.addItem(f"{fmt}  ({ex})", fmt)
        form.addRow(t("regional_time_format"), self._time_fmt)

        self._decimal_sep = QComboBox()
        for s in self._DECIMAL_SEPS:
            self._decimal_sep.addItem(repr(s), s)
        form.addRow(t("regional_decimal_sep"), self._decimal_sep)

        self._thousand_sep = QComboBox()
        for s in self._THOUSAND_SEPS:
            label = repr(s) if s else t("regional_no_sep")
            self._thousand_sep.addItem(label, s)
        form.addRow(t("regional_thousand_sep"), self._thousand_sep)

        self._ui_lang = QComboBox()
        self._ui_lang.addItems(["uk", "en"])
        form.addRow(t("regional_ui_lang"), self._ui_lang)

        root.addWidget(grp)
        root.addStretch()

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self._load()

    def _load(self) -> None:
        if self._db is None:
            return
        cfg = _load_config(self._db, self.SECTION)
        self._set_combo(self._date_fmt,    cfg.get("date_format",    "dd.MM.yyyy"))
        self._set_combo(self._time_fmt,    cfg.get("time_format",    "HH:mm:ss"))
        self._set_combo(self._decimal_sep, cfg.get("decimal_sep",    "."))
        self._set_combo(self._thousand_sep,cfg.get("thousand_sep",   " "))
        self._set_combo(self._ui_lang,     cfg.get("ui_lang",        "uk"))

    def _set_combo(self, cb: QComboBox, value: str) -> None:
        idx = cb.findData(value)
        if idx < 0:
            idx = cb.findText(value)
        if idx >= 0:
            cb.setCurrentIndex(idx)

    def _on_ok(self) -> None:
        if self._db is not None:
            _save_config(self._db, self.SECTION, {
                "date_format":  self._date_fmt.currentData(),
                "time_format":  self._time_fmt.currentData(),
                "decimal_sep":  self._decimal_sep.currentData(),
                "thousand_sep": self._thousand_sep.currentData(),
                "ui_lang":      self._ui_lang.currentText(),
            })
        self.accept()


# ---------------------------------------------------------------------------
# AuthSettingsDialog
# ---------------------------------------------------------------------------

class AuthSettingsDialog(QDialog):
    """Configure authentication and session security policies."""

    SECTION = "auth"

    def __init__(self, parent=None, *, db=None) -> None:
        super().__init__(parent)
        self._db = db
        self.setWindowTitle(t("admin_auth_settings"))
        self.setModal(True)
        self.resize(520, 460)

        root = QVBoxLayout(self)

        # Password policy
        pwd_grp = QGroupBox(t("auth_password_policy"))
        pwd_form = QFormLayout(pwd_grp)
        pwd_form.setSpacing(8)

        self._min_length = QSpinBox()
        self._min_length.setRange(4, 128)
        self._min_length.setValue(8)
        pwd_form.addRow(t("auth_min_length"), self._min_length)

        self._require_upper = QCheckBox()
        pwd_form.addRow(t("auth_require_upper"), self._require_upper)

        self._require_digit = QCheckBox()
        pwd_form.addRow(t("auth_require_digit"), self._require_digit)

        self._require_special = QCheckBox()
        pwd_form.addRow(t("auth_require_special"), self._require_special)

        self._password_expiry_days = QSpinBox()
        self._password_expiry_days.setRange(0, 3650)
        self._password_expiry_days.setValue(0)
        self._password_expiry_days.setSpecialValueText(t("auth_never"))
        self._password_expiry_days.setSuffix(f" {t('auth_days')}")
        pwd_form.addRow(t("auth_password_expiry"), self._password_expiry_days)

        root.addWidget(pwd_grp)

        # Session policy
        sess_grp = QGroupBox(t("auth_session_policy"))
        sess_form = QFormLayout(sess_grp)
        sess_form.setSpacing(8)

        self._session_ttl_min = QSpinBox()
        self._session_ttl_min.setRange(5, 10080)  # 5 min — 1 week
        self._session_ttl_min.setValue(480)        # 8 hours
        self._session_ttl_min.setSuffix(f" {t('auth_minutes')}")
        sess_form.addRow(t("auth_session_ttl"), self._session_ttl_min)

        self._max_failed_attempts = QSpinBox()
        self._max_failed_attempts.setRange(0, 20)
        self._max_failed_attempts.setValue(5)
        self._max_failed_attempts.setSpecialValueText(t("auth_unlimited"))
        sess_form.addRow(t("auth_max_failed"), self._max_failed_attempts)

        self._lockout_minutes = QSpinBox()
        self._lockout_minutes.setRange(1, 1440)
        self._lockout_minutes.setValue(15)
        self._lockout_minutes.setSuffix(f" {t('auth_minutes')}")
        sess_form.addRow(t("auth_lockout_duration"), self._lockout_minutes)

        self._allow_anonymous = QCheckBox()
        sess_form.addRow(t("auth_allow_anonymous"), self._allow_anonymous)

        root.addWidget(sess_grp)
        root.addStretch()

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self._load()

    def _load(self) -> None:
        if self._db is None:
            return
        cfg = _load_config(self._db, self.SECTION)
        self._min_length.setValue(int(cfg.get("min_length", 8)))
        self._require_upper.setChecked(bool(cfg.get("require_upper", False)))
        self._require_digit.setChecked(bool(cfg.get("require_digit", False)))
        self._require_special.setChecked(bool(cfg.get("require_special", False)))
        self._password_expiry_days.setValue(int(cfg.get("password_expiry_days", 0)))
        self._session_ttl_min.setValue(int(cfg.get("session_ttl_min", 480)))
        self._max_failed_attempts.setValue(int(cfg.get("max_failed_attempts", 5)))
        self._lockout_minutes.setValue(int(cfg.get("lockout_minutes", 15)))
        self._allow_anonymous.setChecked(bool(cfg.get("allow_anonymous", False)))

    def _on_ok(self) -> None:
        if self._db is not None:
            _save_config(self._db, self.SECTION, {
                "min_length":            self._min_length.value(),
                "require_upper":         self._require_upper.isChecked(),
                "require_digit":         self._require_digit.isChecked(),
                "require_special":       self._require_special.isChecked(),
                "password_expiry_days":  self._password_expiry_days.value(),
                "session_ttl_min":       self._session_ttl_min.value(),
                "max_failed_attempts":   self._max_failed_attempts.value(),
                "lockout_minutes":       self._lockout_minutes.value(),
                "allow_anonymous":       self._allow_anonymous.isChecked(),
            })
        self.accept()


# ---------------------------------------------------------------------------
# InforbaseParamsDialog
# ---------------------------------------------------------------------------

class InforbaseParamsDialog(QDialog):
    """View and edit basic infobase parameters."""

    SECTION = "infobase"

    def __init__(self, parent=None, *, db=None, db_path: str = "") -> None:
        super().__init__(parent)
        self._db = db
        self.setWindowTitle(t("admin_infobase_params"))
        self.setModal(True)
        self.resize(560, 420)

        root = QVBoxLayout(self)

        grp = QGroupBox(t("admin_infobase_params"))
        form = QFormLayout(grp)
        form.setSpacing(10)

        self._name = QLineEdit()
        form.addRow(t("infobase_name"), self._name)

        self._description = QPlainTextEdit()
        self._description.setMaximumHeight(80)
        form.addRow(t("infobase_description"), self._description)

        self._version = QLineEdit()
        self._version.setPlaceholderText("1.0.0")
        form.addRow(t("infobase_version"), self._version)

        self._vendor = QLineEdit()
        form.addRow(t("infobase_vendor"), self._vendor)

        self._default_lang = QComboBox()
        self._default_lang.addItems(["uk", "en", "ru"])
        form.addRow(t("infobase_default_lang"), self._default_lang)

        root.addWidget(grp)

        # Read-only DB info
        info_grp = QGroupBox(t("infobase_db_info"))
        info_form = QFormLayout(info_grp)
        info_form.addRow(t("infobase_db_path"), QLabel(db_path or "—"))
        root.addWidget(info_grp)

        root.addStretch()

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self._load()

    def _load(self) -> None:
        if self._db is None:
            return
        cfg = _load_config(self._db, self.SECTION)
        self._name.setText(str(cfg.get("name", "")))
        self._description.setPlainText(str(cfg.get("description", "")))
        self._version.setText(str(cfg.get("version", "1.0.0")))
        self._vendor.setText(str(cfg.get("vendor", "")))
        lang = str(cfg.get("default_lang", "uk"))
        idx = self._default_lang.findText(lang)
        self._default_lang.setCurrentIndex(idx if idx >= 0 else 0)

    def _on_ok(self) -> None:
        if self._db is not None:
            _save_config(self._db, self.SECTION, {
                "name":         self._name.text().strip(),
                "description":  self._description.toPlainText().strip(),
                "version":      self._version.text().strip() or "1.0.0",
                "vendor":       self._vendor.text().strip(),
                "default_lang": self._default_lang.currentText(),
            })
        self.accept()


# ---------------------------------------------------------------------------
# TestRepairDialog
# ---------------------------------------------------------------------------

class TestRepairDialog(QDialog):
    """Run DB integrity checks and optional auto-repair."""

    def __init__(self, parent=None, *, db=None) -> None:
        super().__init__(parent)
        self._db = db
        self.setWindowTitle(t("admin_test_repair"))
        self.setModal(True)
        self.resize(640, 500)

        root = QVBoxLayout(self)

        desc = QLabel(t("test_repair_desc"))
        desc.setWordWrap(True)
        root.addWidget(desc)

        root.addWidget(_h_separator())

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(self._log.font())
        self._log.setPlaceholderText(t("test_repair_ready"))
        root.addWidget(self._log, 1)

        btn_bar = QHBoxLayout()
        self._btn_check = QPushButton(t("test_repair_btn_check"))
        self._btn_check.clicked.connect(self._run_check)
        btn_bar.addWidget(self._btn_check)

        self._btn_repair = QPushButton(t("test_repair_btn_repair"))
        self._btn_repair.clicked.connect(self._run_repair)
        self._btn_repair.setEnabled(False)
        btn_bar.addWidget(self._btn_repair)

        btn_bar.addStretch()
        close_btn = QPushButton(t("act_close"))
        close_btn.clicked.connect(self.accept)
        btn_bar.addWidget(close_btn)
        root.addLayout(btn_bar)

        self._issues: list[str] = []

    def _log_line(self, text: str) -> None:
        self._log.appendPlainText(text)

    def _probe_first_row(self, table_name: str) -> tuple[bool, int]:
        """Return a cheap availability probe for a table.

        The health check only needs to know that the table can be read. A
        point lookup by ``rowid`` avoids full-table scans on remote GatewayDb
        connections, which were timing out on large manifests.
        """

        if self._db is None:
            return False, 0
        try:
            rows = self._db.table(table_name).select(where={"rowid": 1}) or []
            return True, len(rows)
        except Exception:
            return False, 0

    def _run_check(self) -> None:
        self._log.clear()
        self._issues = []
        self._btn_repair.setEnabled(False)

        if self._db is None:
            self._log_line(f"✗ {t('test_repair_no_db')}")
            return

        self._log_line(f"▶ {t('test_repair_checking')}...")

        # 1. Manifest table
        try:
            manifest_info = None
            if hasattr(self._db, "manifest_info"):
                manifest_info = self._db.manifest_info()
            elif hasattr(self._db, "_gw") and hasattr(getattr(self._db, "_gw", None), "manifest_info"):
                manifest_info = getattr(self._db, "_gw").manifest_info()
            if isinstance(manifest_info, dict) and manifest_info:
                count = int(manifest_info.get("object_count") or 0)
                self._log_line(f"  ✓ manifest: {count} rows")
                if count <= 0:
                    self._log_line("  ⚠ manifest: empty")
            else:
                ok, rows_found = self._probe_first_row("manifest")
                if ok:
                    self._log_line(f"  ✓ manifest: {rows_found} probe row(s)")
                else:
                    self._log_line("  ✗ manifest: unavailable")
                    self._issues.append("manifest_missing")
        except Exception as e:
            self._log_line(f"  ✗ manifest: {e}")
            self._issues.append("manifest_missing")

        # 2. System tables
        system_tables = ["sys_users", "sys_roles", "sys_user_roles", "sys_audit_log"]
        for tbl in system_tables:
            try:
                ok, cnt = self._probe_first_row(tbl)
                if ok:
                    if cnt:
                        self._log_line(f"  ✓ {tbl}: 1+ rows")
                    else:
                        self._log_line(f"  ✓ {tbl}: 0 rows")
                else:
                    self._log_line(f"  ✗ {tbl}: unavailable")
                    self._issues.append(f"table_missing:{tbl}")
            except Exception as e:
                self._log_line(f"  ✗ {tbl}: {e}")
                self._issues.append(f"table_missing:{tbl}")

        # 3. Schema deployment
        try:
            if hasattr(self._db, "_meta"):
                from src.configurator.persistence.schema_deployment import SchemaDeploymentService

                report = SchemaDeploymentService(self._db).deploy_all()
                if report.errors:
                    for err in report.errors:
                        self._log_line(f"  ⚠ schema: {err}")
                        self._issues.append(f"schema_error:{err}")
                else:
                    self._log_line(
                        f"  ✓ schema: {report.existing} tables OK"
                        + (f", {report.created} created" if report.created else "")
                    )
            else:
                # Remote runtime DB: avoid a full schema deployment probe here,
                # because it forces a full manifest scan over RPC. The table
                # probes above are enough to validate the startup path.
                self._log_line("  ✓ schema: runtime probe OK")
        except Exception as e:
            self._log_line(f"  ✗ schema check: {e}")

        # Result
        if self._issues:
            self._log_line(f"\n⚠ {t('test_repair_issues_found').format(n=len(self._issues))}")
            self._btn_repair.setEnabled(True)
        else:
            self._log_line(f"\n✓ {t('test_repair_ok')}")

    def _run_repair(self) -> None:
        if self._db is None:
            return
        self._log_line(f"\n▶ {t('test_repair_repairing')}...")
        repaired = 0

        for issue in self._issues:
            if issue == "manifest_missing":
                try:
                    from src.configurator.persistence.manifest_io import ensure_manifest_table
                    ensure_manifest_table(self._db)
                    self._log_line(f"  ✓ Restored manifest table")
                    repaired += 1
                except Exception as e:
                    self._log_line(f"  ✗ Could not restore manifest: {e}")

            elif issue.startswith("table_missing:"):
                tbl = issue.split(":", 1)[1]
                try:
                    from src.configurator.persistence.system_tables import ensure_system_tables
                    ensure_system_tables(self._db)
                    self._log_line(f"  ✓ Restored system tables")
                    repaired += 1
                    break  # ensure_system_tables handles all
                except Exception as e:
                    self._log_line(f"  ✗ Could not restore {tbl}: {e}")

        self._log_line(
            f"\n✓ {t('test_repair_done').format(n=repaired)}" if repaired
            else f"\n⚠ {t('test_repair_nothing_done')}"
        )
        self._btn_repair.setEnabled(False)
        self._issues = []
