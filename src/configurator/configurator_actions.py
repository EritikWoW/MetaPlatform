from __future__ import annotations

import os
import json
import csv
import re
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QThread, Qt, QTimer
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFileDialog,
    QMdiSubWindow,
    QMessageBox,
    QProgressDialog,
)

from src.configurator.ui.widgets import NodeInfo
from src.configurator.configurator_window_support import _OnecImportWorker
from src.platform.paths import get_user_config_dir
from src.platform.onec_import_state import load_last_onec_import
from src.ui_qt.i18n import get_lang, t
from src.ui_qt.widgets.admin_audit_log_dialog import AuditLogDialog
from src.ui_qt.widgets.admin_settings_dialogs import (
    AuthSettingsDialog,
    InforbaseParamsDialog,
    LogSettingsDialog,
    RegionalSettingsDialog,
    TestRepairDialog,
)
from src.ui_qt.widgets.admin_users_dialog import UsersAdminDialog
from src.ui_qt.widgets.code_editor_widget import CodeEditorWidget
from src.ui_qt.widgets.code_templates_dialog import CodeTemplatesDialog
from src.ui_qt.widgets.circular_progress_dialog import CircularProgressDialog
from src.ui_qt.widgets.external_image_viewer import ExternalImageViewerWidget
from src.ui_qt.widgets.external_text_file_editor import ExternalTextFileEditorWidget
from src.ui_qt.widgets.global_search_dialog import GlobalSearchDialog, GlobalSearchHit, GlobalSearchOptions
from src.ui_qt.widgets.load_config_dialog import LoadConfigDialog
from src.ui_qt.widgets.metadata_search_dialog import MetadataSearchDialog, MetadataSearchOptions
from src.ui_qt.widgets.new_document_dialog import NewDocumentDialog
from src.ui_qt.widgets.syntax_helper_widget import SyntaxHelperWidget
from src.ui_qt.widgets.windows_list_dialog import WindowsListDialog

_ONEC_IMPORT_SCOPE_RE = re.compile(r"^Import manifest:\s*(?P<scope>.+?)(?:\s*->\s*.+)?$")
_ONEC_IMPORT_TYPE_MAP = {
    "Catalogs": "Catalog",
    "Documents": "Document",
    "DocumentJournals": "DocumentJournal",
    "Enums": "Enum",
    "Reports": "Report",
    "DataProcessors": "DataProcessor",
    "ChartsOfCharacteristicTypes": "ChartOfCharacteristicTypes",
    "ChartsOfAccounts": "ChartOfAccounts",
    "ChartsOfCalculationTypes": "ChartOfCalculationTypes",
    "InformationRegisters": "InformationRegister",
    "AccumulationRegisters": "AccumulationRegister",
    "AccountingRegisters": "AccountingRegister",
    "CalculationRegisters": "CalculationRegister",
    "BusinessProcesses": "BusinessProcess",
    "Tasks": "Task",
    "ExternalDataSources": "ExternalDataSource",
    "Subsystems": "Subsystem",
    "CommonModules": "CommonModule",
    "CommonForms": "CommonForm",
    "CommonCommands": "CommonCommand",
    "CommonTemplates": "CommonTemplate",
    "CommonLayouts": "CommonLayout",
    "CommonPictures": "CommonPicture",
    "Roles": "Role",
    "Languages": "Language",
    "Constants": "Constant",
}


class ConfiguratorActionsMixin:
    def _install_debug_client_shortcuts(self) -> None:
        from PySide6.QtGui import QKeySequence, QShortcut

        shortcuts = list(getattr(self, "_debug_client_shortcuts", []) or [])
        for shortcut in shortcuts:
            try:
                shortcut.deleteLater()
            except Exception:
                pass
        self._debug_client_shortcuts = []

        bindings = {
            "F5": self._debug_f5_action,
            "Shift+F5": self._debug_shift_f5_action,
        }
        for key, handler in bindings.items():
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(handler)
            self._debug_client_shortcuts.append(shortcut)

    def _active_code_editor(self) -> CodeEditorWidget | None:
        try:
            sub = self.mdi.activeSubWindow()
        except Exception:
            sub = None
        if sub is None:
            return None
        try:
            widget = sub.widget()
        except Exception:
            widget = None
        if isinstance(widget, CodeEditorWidget):
            return widget
        try:
            for child in widget.findChildren(CodeEditorWidget):
                return child
        except Exception:
            pass
        return None

    def _paused_code_editor(self) -> CodeEditorWidget | None:
        """Return the editor owned by the active debug pause, if any."""

        for editor in self.findChildren(CodeEditorWidget):
            try:
                if getattr(editor, "_current_debug_pause", None) is not None:
                    return editor
            except Exception:
                continue
        return None

    def _abort_debug_pause(self) -> bool:
        bridge = getattr(self, "_control_bridge", None)
        aborted = False
        abort = getattr(bridge, "abort_debug_pause", None)
        if callable(abort):
            try:
                aborted = bool(abort())
            except Exception:
                aborted = False
        for editor in self.findChildren(CodeEditorWidget):
            clear = getattr(editor, "_clear_debug_pause_banner", None)
            if callable(clear):
                try:
                    clear()
                except Exception:
                    pass
        return aborted

    def _debug_f5_action(self) -> None:
        now = time.monotonic()
        if float(getattr(self, "_debug_f5_guard_until", 0.0) or 0.0) > now:
            return
        self._debug_f5_guard_until = now + 0.35
        editor = self._paused_code_editor()
        if editor is not None:
            try:
                editor._request_debug_command("continue")
                return
            except Exception:
                pass
        self._launch_or_restart_debug_client()

    def _debug_shift_f5_action(self) -> None:
        self._stop_debug_client(force=True, notify=True)

    def _debug_client_is_running(self) -> bool:
        proc = getattr(self, "_debug_client_process", None)
        if proc is None:
            return False
        try:
            return proc.poll() is None
        except Exception:
            return False

    def _launch_or_restart_debug_client(self) -> None:
        if self._debug_client_is_running():
            answer = QMessageBox.question(
                self,
                t("debug_restart_title"),
                t("debug_restart_body"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self._stop_debug_client(force=True, notify=False)
        self._launch_client(debug=True)

    def _stop_debug_client(self, *, force: bool = False, notify: bool = False) -> None:
        pause_aborted = self._abort_debug_pause()
        proc = getattr(self, "_debug_client_process", None)
        if proc is None:
            if notify:
                key = "debug_client_stopped" if pause_aborted else "debug_client_not_running"
                self.statusBar().showMessage(t(key), 4000)
            return
        running = False
        try:
            running = proc.poll() is None
        except Exception:
            running = False
        if not running:
            self._debug_client_process = None
            if notify:
                self.statusBar().showMessage(t("debug_client_not_running"), 4000)
            return
        try:
            if force:
                proc.kill()
            else:
                proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except Exception:
                if proc.poll() is None:
                    if notify:
                        QMessageBox.warning(self, t("dlg_client_title"), t("debug_client_stop_failed"))
                    return
        except Exception as exc:
            if notify:
                QMessageBox.warning(self, t("dlg_client_title"), str(exc))
            return
        self._debug_client_process = None
        if notify:
            self.statusBar().showMessage(t("debug_client_stopped"), 4000)

    def _subsystem_membership_report_paths(self) -> list[Path]:
        paths: list[Path] = [get_user_config_dir() / "subsystem_membership_report.json"]
        try:
            state = load_last_onec_import()
        except Exception:
            state = {}
        source_path = str(state.get("source_path") or os.environ.get("META_LAST_ONEC_SOURCE_PATH") or "").strip()
        if source_path:
            source = Path(source_path)
            base_dir = source.parent if source.suffix else source
            paths.append(base_dir / "subsystem_membership_report.json")
        uniq: list[Path] = []
        seen: set[str] = set()
        for path in paths:
            key = str(path.resolve()) if path.is_absolute() else str(path)
            if key in seen:
                continue
            seen.add(key)
            uniq.append(path)
        return uniq

    def _source_structure_compare_report_paths(self) -> list[Path]:
        paths: list[Path] = [get_user_config_dir() / "source_structure_compare_report.json"]
        try:
            state = load_last_onec_import()
        except Exception:
            state = {}
        source_path = str(state.get("source_path") or os.environ.get("META_LAST_ONEC_SOURCE_PATH") or "").strip()
        if source_path:
            source = Path(source_path)
            base_dir = source.parent if source.suffix else source
            paths.append(base_dir / "source_structure_compare_report.json")
        uniq: list[Path] = []
        seen: set[str] = set()
        for path in paths:
            key = str(path.resolve()) if path.is_absolute() else str(path)
            if key in seen:
                continue
            seen.add(key)
            uniq.append(path)
        return uniq

    def _save_subsystem_membership_report(self, report: dict[str, Any]) -> Path:
        saved: Path | None = None
        for path in self._subsystem_membership_report_paths():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            saved = path
        return saved or (get_user_config_dir() / "subsystem_membership_report.json")

    def _save_source_structure_compare_report(self, report: dict[str, Any]) -> Path:
        saved: Path | None = None
        for path in self._source_structure_compare_report_paths():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            saved = path
        return saved or (get_user_config_dir() / "source_structure_compare_report.json")

    def _export_subsystem_membership_report_csv(self, report: dict[str, Any], path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = list(report.get("items") or [])
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "guid",
                    "name",
                    "title",
                    "objects_count",
                    "content_refs_count",
                    "has_mismatch",
                    "missing_objects",
                    "missing_refs",
                ],
            )
            writer.writeheader()
            for item in rows:
                writer.writerow(
                    {
                        "guid": str(item.get("guid") or ""),
                        "name": str(item.get("name") or ""),
                        "title": str(item.get("title") or ""),
                        "objects_count": int(item.get("objects_count") or 0),
                        "content_refs_count": int(item.get("content_refs_count") or 0),
                        "has_mismatch": bool(item.get("has_mismatch") or False),
                        "missing_objects": ";".join([str(x) for x in item.get("missing_objects") or [] if str(x).strip()]),
                        "missing_refs": ";".join([str(x) for x in item.get("missing_refs") or [] if str(x).strip()]),
                    }
                )
        return path

    def _export_source_structure_compare_report_csv(self, report: dict[str, Any], path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = list(report.get("items") or [])
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "guid",
                    "type",
                    "name",
                    "title",
                    "order",
                    "parent_guid",
                    "tree_path",
                    "is_virtual",
                    "virtual_reason",
                    "status",
                    "has_mismatch",
                    "source_payload_keys",
                    "db_payload_keys",
                    "diff_keys",
                ],
            )
            writer.writeheader()
            for item in rows:
                source_row = dict(item.get("source") or {})
                db_row = dict(item.get("db") or {})
                diffs = dict(item.get("diffs") or {})
                writer.writerow(
                    {
                        "guid": str(item.get("guid") or ""),
                        "type": str(item.get("type") or ""),
                        "name": str(item.get("name") or ""),
                        "title": str(item.get("title") or ""),
                        "order": str((item.get("source") or {}).get("order") or (item.get("db") or {}).get("order") or ""),
                        "parent_guid": str((item.get("source") or {}).get("parent_guid") or (item.get("db") or {}).get("parent_guid") or ""),
                        "tree_path": str((item.get("source") or {}).get("tree_path") or (item.get("db") or {}).get("tree_path") or ""),
                        "is_virtual": bool(item.get("is_virtual") or False),
                        "virtual_reason": str((item.get("source") or {}).get("virtual_reason") or (item.get("db") or {}).get("virtual_reason") or ""),
                        "status": str(item.get("status") or ""),
                        "has_mismatch": bool(item.get("has_mismatch") or False),
                        "source_payload_keys": ";".join(sorted([str(x) for x in (source_row.get("payload") or {}).keys()])),
                        "db_payload_keys": ";".join(sorted([str(x) for x in (db_row.get("payload") or {}).keys()])),
                        "diff_keys": ";".join(sorted([str(x) for x in diffs.keys()])),
                    }
                )
        return path

    def _format_subsystem_membership_report(self, report: dict[str, Any]) -> str:
        items = list(report.get("items") or [])
        total = len(items)
        mismatched = int(report.get("mismatched") or 0)
        lines = [
            f"Total subsystems: {total}",
            f"Mismatched: {mismatched}",
            "",
        ]
        for item in items:
            title = str(item.get("title") or item.get("name") or item.get("guid") or "").strip()
            lines.append(f"- {title}")
            lines.append(f"  objects: {item.get('objects_count', 0)}")
            lines.append(f"  content_refs: {item.get('content_refs_count', 0)}")
            missing_objects = list(item.get("missing_objects") or [])
            missing_refs = list(item.get("missing_refs") or [])
            if missing_objects:
                lines.append(f"  missing_objects: {', '.join(missing_objects)}")
            if missing_refs:
                lines.append(f"  missing_refs: {', '.join(missing_refs)}")
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def _format_source_structure_compare_report(self, report: dict[str, Any]) -> str:
        summary = dict(report.get("summary") or {})
        source = dict(report.get("source") or {})
        items = list(report.get("items") or [])
        parent_child_mismatches = list(report.get("parent_child_mismatches") or [])
        flattened_subtrees = list(report.get("flattened_subtrees") or [])
        lines = [
            f"Source path: {source.get('path', '')}",
            f"Detected kind: {source.get('detected_kind', '')} / {source.get('semantic_kind', '')}",
            f"Requested kind: {source.get('requested_kind', '')}",
            "",
            f"Source objects: {int(summary.get('source_count') or 0)}",
            f"DB objects: {int(summary.get('db_count') or 0)}",
            f"Source real rows: {int(summary.get('source_real_rows') or 0)}",
            f"DB real rows: {int(summary.get('db_real_rows') or 0)}",
            f"Matched: {int(summary.get('matched') or 0)}",
            f"Mismatched: {int(summary.get('mismatched') or 0)}",
            f"Missing in DB: {int(summary.get('missing_in_db') or 0)}",
            f"Extra in DB: {int(summary.get('extra_in_db') or 0)}",
            f"Missing parent links in source: {int(summary.get('missing_parent_links_source') or 0)}",
            f"Missing parent links in DB: {int(summary.get('missing_parent_links_db') or 0)}",
            f"Parent-child mismatches: {int(summary.get('parent_child_mismatch_count') or 0)}",
            f"Flattened subtrees: {int(summary.get('flattened_subtree_count') or 0)}",
            f"Coverage: {summary.get('coverage_ratio', 0)}",
            f"Real coverage: {summary.get('coverage_ratio_real', 0)}",
            "",
        ]
        if parent_child_mismatches:
            lines.append("Parent-child mismatches:")
            for entry in parent_child_mismatches[:40]:
                parent_guid = str(entry.get("parent_guid") or "").strip() or "<root>"
                lines.append(f"- parent: {parent_guid}")
                lines.append(f"  source_count: {int(entry.get('source_count') or 0)}")
                lines.append(f"  db_count: {int(entry.get('db_count') or 0)}")
                source_titles = list(entry.get("source_child_titles") or [])
                db_titles = list(entry.get("db_child_titles") or [])
                if source_titles:
                    lines.append(f"  source_children: {', '.join([str(x) for x in source_titles if str(x).strip()])}")
                if db_titles:
                    lines.append(f"  db_children: {', '.join([str(x) for x in db_titles if str(x).strip()])}")
                missing_in_db = list(entry.get("missing_in_db") or [])
                missing_in_source = list(entry.get("missing_in_source") or [])
                if missing_in_db:
                    lines.append(f"  missing_in_db: {', '.join(missing_in_db)}")
                if missing_in_source:
                    lines.append(f"  missing_in_source: {', '.join(missing_in_source)}")
            lines.append("")
        if flattened_subtrees:
            lines.append("Flattened subtrees:")
            for entry in flattened_subtrees[:40]:
                parent_title = str(entry.get("parent_title") or entry.get("parent_guid") or "<root>").strip()
                lines.append(f"- parent: {parent_title}")
                lines.append(f"  tree_path: {str(entry.get('tree_path') or '').strip()}")
                lines.append(f"  source_child_count: {int(entry.get('source_child_count') or 0)}")
                lines.append(f"  relocated_child_count: {int(entry.get('relocated_child_count') or 0)}")
                relocated_children = list(entry.get("relocated_children") or [])
                for child in relocated_children[:20]:
                    lines.append(
                        f"  child: {str(child.get('title') or child.get('guid') or '').strip()} -> "
                        f"{str(child.get('db_parent_title') or child.get('db_parent_guid') or '<root>').strip()}"
                    )
            lines.append("")
        for idx, item in enumerate(items[:80], start=1):
            title = str(item.get("title") or item.get("name") or item.get("guid") or "").strip()
            status = str(item.get("status") or "").strip()
            lines.append(f"{idx}. {title} [{status}]")
            lines.append(f"   guid: {item.get('guid', '')}")
            lines.append(f"   type: {item.get('type', '')}")
            order = str((item.get("source") or {}).get("order") or (item.get("db") or {}).get("order") or "").strip()
            if order:
                lines.append(f"   order: {order}")
            parent_guid = str((item.get("source") or {}).get("parent_guid") or (item.get("db") or {}).get("parent_guid") or "").strip()
            if parent_guid:
                lines.append(f"   parent_guid: {parent_guid}")
            tree_path = str((item.get("source") or {}).get("tree_path") or (item.get("db") or {}).get("tree_path") or "").strip()
            if tree_path:
                lines.append(f"   tree_path: {tree_path}")
            lines.append(f"   is_virtual: {bool(item.get('is_virtual') or False)}")
            virtual_reason = str((item.get("source") or {}).get("virtual_reason") or (item.get("db") or {}).get("virtual_reason") or "").strip()
            if virtual_reason:
                lines.append(f"   virtual_reason: {virtual_reason}")
            diffs = dict(item.get("diffs") or {})
            for key, diff in diffs.items():
                source_value = diff.get("source")
                db_value = diff.get("db")
                lines.append(f"   {key}:")
                lines.append(f"     source: {source_value}")
                lines.append(f"     db: {db_value}")
            lines.append("")
        if len(items) > 80:
            lines.append(f"... truncated {len(items) - 80} more items")
        return "\n".join(lines).strip() + "\n"

    def _resolve_compare_source(self) -> tuple[str, str]:
        try:
            state = load_last_onec_import()
        except Exception:
            state = {}
        source_path = str(state.get("source_path") or os.environ.get("META_LAST_ONEC_SOURCE_PATH") or "").strip()
        source_kind = str(state.get("source_kind") or os.environ.get("META_LAST_ONEC_SOURCE_KIND") or "").strip() or "auto"
        return source_path, source_kind

    def _pick_compare_source_path(self, current_path: str = "") -> str:
        current = str(current_path or "").strip()
        if current:
            path = Path(current)
            if path.is_dir():
                selected = QFileDialog.getExistingDirectory(
                    self,
                    t("cfg_source_structure_compare_choose_source"),
                    str(path),
                )
                return str(selected or "").strip()
            selected, _ = QFileDialog.getOpenFileName(
                self,
                t("cfg_source_structure_compare_choose_source"),
                str(path.parent if path.parent.exists() else path),
                "All files (*)",
            )
            return str(selected or "").strip()
        selected, _ = QFileDialog.getOpenFileName(
            self,
            t("cfg_source_structure_compare_choose_source"),
            "",
            "All files (*)",
        )
        if selected:
            return str(selected).strip()
        selected_dir = QFileDialog.getExistingDirectory(self, t("cfg_source_structure_compare_choose_source"), "")
        return str(selected_dir or "").strip()

    def _show_source_structure_compare_report(self) -> None:
        vm = getattr(self, "_vm", None)
        if vm is None or not hasattr(vm, "compare_source_structure"):
            self.show_warning(t("dlg_error_title"), t("dlg_vm_not_ready"))
            return

        from PySide6.QtWidgets import QDialogButtonBox, QPlainTextEdit, QVBoxLayout

        source_path, source_kind = self._resolve_compare_source()
        if not source_path:
            source_path = self._pick_compare_source_path("")
            source_kind = "auto"
        if not source_path:
            self.show_warning(t("dlg_error_title"), t("cfg_source_structure_compare_no_source"))
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(t("cfg_source_structure_compare_title"))
        dlg.resize(1120, 760)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        text = QPlainTextEdit(dlg)
        text.setReadOnly(True)
        layout.addWidget(text, 1)

        buttons = QDialogButtonBox(dlg)
        btn_refresh = buttons.addButton(t("btn_reload"), QDialogButtonBox.ButtonRole.ActionRole)
        btn_choose = buttons.addButton(t("cfg_source_structure_compare_choose_source"), QDialogButtonBox.ButtonRole.ActionRole)
        btn_repair = buttons.addButton(t("cfg_source_structure_compare_repair"), QDialogButtonBox.ButtonRole.ActionRole)
        btn_export_json = buttons.addButton(t("report_save_json"), QDialogButtonBox.ButtonRole.ActionRole)
        btn_export_csv = buttons.addButton(t("report_save_csv"), QDialogButtonBox.ButtonRole.ActionRole)
        btn_close = buttons.addButton(t("btn_close"), QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(buttons)
        last_report: dict[str, Any] = {}
        current_source_path = str(source_path or "").strip()
        current_source_kind = str(source_kind or "auto").strip() or "auto"

        def _refresh() -> dict[str, Any]:
            nonlocal last_report
            report = vm.compare_source_structure(source_path=current_source_path, source_kind=current_source_kind)
            last_report = dict(report or {})
            text.setPlainText(self._format_source_structure_compare_report(report))
            summary = dict(report.get("summary") or {})
            btn_repair.setEnabled(bool(int(summary.get("flattened_subtree_count") or 0) or int(summary.get("parent_child_mismatch_count") or 0)))
            return report

        def _choose_source() -> None:
            nonlocal current_source_path, current_source_kind
            chosen = self._pick_compare_source_path(current_source_path)
            if not chosen:
                return
            current_source_path = chosen
            current_source_kind = "auto"
            _refresh()

        def _repair() -> None:
            if not hasattr(vm, "repair_source_structure"):
                self.show_warning(t("dlg_error_title"), t("dlg_vm_not_ready"))
                return
            try:
                result = vm.repair_source_structure(source_path=current_source_path, source_kind=current_source_kind)
                self._save_source_structure_compare_report(result.get("report") or last_report or {})
                self.show_info(
                    t("info_title"),
                    f"{t('cfg_source_structure_compare_repaired')}: {int(result.get('changed') or 0)}",
                )
            except Exception as exc:
                self.show_warning(t("dlg_error_title"), str(exc))
                return
            _refresh()

        def _export_json() -> None:
            if not last_report:
                return
            default_json = self._source_structure_compare_report_paths()[0] if self._source_structure_compare_report_paths() else get_user_config_dir() / "source_structure_compare_report.json"
            path, _ = QFileDialog.getSaveFileName(
                dlg,
                t("report_save_json"),
                str(default_json),
                "JSON (*.json)",
            )
            if not path:
                return
            try:
                self._save_source_structure_compare_report(last_report)
                if Path(path) not in self._source_structure_compare_report_paths():
                    Path(path).write_text(json.dumps(last_report, ensure_ascii=False, indent=2), encoding="utf-8")
                self.show_info(t("info_title"), str(path))
            except Exception as exc:
                self.show_warning(t("dlg_error_title"), str(exc))

        def _export_csv() -> None:
            if not last_report:
                return
            default_csv = (self._source_structure_compare_report_paths()[0] if self._source_structure_compare_report_paths() else get_user_config_dir() / "source_structure_compare_report.json").with_suffix(".csv")
            path, _ = QFileDialog.getSaveFileName(
                dlg,
                t("report_save_csv"),
                str(default_csv),
                "CSV (*.csv)",
            )
            if not path:
                return
            try:
                self._export_source_structure_compare_report_csv(last_report, Path(path))
                self.show_info(t("info_title"), str(path))
            except Exception as exc:
                self.show_warning(t("dlg_error_title"), str(exc))

        btn_refresh.clicked.connect(_refresh)
        btn_choose.clicked.connect(_choose_source)
        btn_repair.clicked.connect(_repair)
        btn_export_json.clicked.connect(_export_json)
        btn_export_csv.clicked.connect(_export_csv)
        btn_close.clicked.connect(dlg.reject)

        report = _refresh()
        dlg.exec()

        try:
            self._save_source_structure_compare_report(last_report or report)
        except Exception:
            pass

    def _repair_source_structure_from_last_import(self) -> None:
        vm = getattr(self, "_vm", None)
        if vm is None or not hasattr(vm, "repair_source_structure"):
            self.show_warning(t("dlg_error_title"), t("dlg_vm_not_ready"))
            return

        source_path, source_kind = self._resolve_compare_source()
        if not source_path:
            source_path = self._pick_compare_source_path("")
            source_kind = "auto"
        if not source_path:
            self.show_warning(t("dlg_error_title"), t("cfg_source_structure_compare_no_source"))
            return

        try:
            result = vm.repair_source_structure(source_path=source_path, source_kind=source_kind or "auto")
            report = dict(result.get("report") or {})
            if report:
                self._save_source_structure_compare_report(report)
            self.show_info(
                t("info_title"),
                f"{t('cfg_source_structure_compare_repaired')}: {int(result.get('changed') or 0)}",
            )
        except Exception as exc:
            self.show_warning(t("dlg_error_title"), str(exc))
            return

        try:
            self._show_source_structure_compare_report()
        except Exception:
            pass

    def _show_subsystem_membership_report(self) -> None:
        vm = getattr(self, "_vm", None)
        if vm is None or not hasattr(vm, "diagnose_subsystem_membership"):
            self.show_warning(t("dlg_error_title"), t("dlg_vm_not_ready"))
            return

        from PySide6.QtWidgets import QDialogButtonBox, QPlainTextEdit, QVBoxLayout

        dlg = QDialog(self)
        dlg.setWindowTitle(t("cfg_subsystem_membership_report_title"))
        dlg.resize(980, 720)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        text = QPlainTextEdit(dlg)
        text.setReadOnly(True)
        layout.addWidget(text, 1)

        buttons = QDialogButtonBox(dlg)
        btn_refresh = buttons.addButton(t("btn_reload"), QDialogButtonBox.ButtonRole.ActionRole)
        btn_repair = buttons.addButton(t("cfg_subsystem_membership_report_repair"), QDialogButtonBox.ButtonRole.ActionRole)
        btn_export_json = buttons.addButton(t("report_save_json"), QDialogButtonBox.ButtonRole.ActionRole)
        btn_export_csv = buttons.addButton(t("report_save_csv"), QDialogButtonBox.ButtonRole.ActionRole)
        btn_close = buttons.addButton(t("btn_close"), QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(buttons)
        last_report: dict[str, Any] = {}

        def _refresh() -> dict[str, Any]:
            nonlocal last_report
            report = vm.diagnose_subsystem_membership()
            last_report = dict(report or {})
            text.setPlainText(self._format_subsystem_membership_report(report))
            btn_repair.setEnabled(bool(int(report.get("mismatched") or 0)))
            return report

        def _repair() -> None:
            if not hasattr(vm, "repair_subsystem_membership"):
                return
            rep = vm.repair_subsystem_membership()
            text.setPlainText(self._format_subsystem_membership_report(vm.diagnose_subsystem_membership()))
            btn_repair.setEnabled(False)
            self.show_info(t("info_title"), f"{t('cfg_subsystem_membership_report_repaired')}: {int(rep.get('changed') or 0)}")

        def _export_json() -> None:
            if not last_report:
                return
            default_json = self._subsystem_membership_report_paths()[0] if self._subsystem_membership_report_paths() else get_user_config_dir() / "subsystem_membership_report.json"
            path, _ = QFileDialog.getSaveFileName(
                dlg,
                t("report_save_json"),
                str(default_json),
                "JSON (*.json)",
            )
            if not path:
                return
            try:
                self._save_subsystem_membership_report(last_report)
                if Path(path) not in self._subsystem_membership_report_paths():
                    Path(path).write_text(json.dumps(last_report, ensure_ascii=False, indent=2), encoding="utf-8")
                self.show_info(t("info_title"), str(path))
            except Exception as exc:
                self.show_warning(t("dlg_error_title"), str(exc))

        def _export_csv() -> None:
            if not last_report:
                return
            default_csv = (self._subsystem_membership_report_paths()[0] if self._subsystem_membership_report_paths() else get_user_config_dir() / "subsystem_membership_report.json").with_suffix(".csv")
            path, _ = QFileDialog.getSaveFileName(
                dlg,
                t("report_save_csv"),
                str(default_csv),
                "CSV (*.csv)",
            )
            if not path:
                return
            try:
                self._export_subsystem_membership_report_csv(last_report, Path(path))
                self.show_info(t("info_title"), str(path))
            except Exception as exc:
                self.show_warning(t("dlg_error_title"), str(exc))

        btn_refresh.clicked.connect(_refresh)
        btn_repair.clicked.connect(_repair)
        btn_export_json.clicked.connect(_export_json)
        btn_export_csv.clicked.connect(_export_csv)
        btn_close.clicked.connect(dlg.reject)

        report = _refresh()
        dlg.exec()

        try:
            self._save_subsystem_membership_report(last_report or report)
        except Exception:
            pass

    def _auto_open_report_object(self, report: dict[str, Any]) -> None:
        items = list(report.get("items") or [])
        if not items:
            return
        target = None
        for item in items:
            if bool(item.get("has_mismatch")):
                target = item
                break
        if target is None:
            target = items[0]
        guid = str(target.get("guid") or "").strip()
        if not guid:
            return
        title = str(target.get("title") or target.get("name") or guid).strip() or guid
        node = NodeInfo(kind="object", guid=guid, name=title, obj_type="subsystem")
        try:
            self.open_object_tab(node)
        except Exception:
            pass

    def _compact_onec_import_message(self, message: str) -> str:
        raw = str(message or "").strip()
        if not raw:
            return t("dlg_onec_import_progress_body")
        match = _ONEC_IMPORT_SCOPE_RE.match(raw)
        if not match:
            return raw
        scope = str(match.group("scope") or "").strip().replace("\\", "/")
        parts = [part for part in scope.split("/") if part]
        if len(parts) < 2:
            return raw
        type_name = _ONEC_IMPORT_TYPE_MAP.get(parts[0], parts[0].rstrip("s"))
        item_name = parts[-1]
        return t("dlg_onec_import_loading_item", item=f"{type_name}.{item_name}")

    def _normalize_modules_to_current_locale(self) -> None:
        vm = getattr(self, "_vm", None)
        service = getattr(vm, "_service", None)
        if vm is None or service is None:
            self.show_warning(t("dlg_error_title"), t("dlg_vm_not_ready"))
            return

        language = str(get_lang() or "uk").strip().lower()
        if language not in {"uk", "en"}:
            language = "uk"

        if not self.confirm(
            t("cfg_modules_normalize_title"),
            t("cfg_modules_normalize_confirm", language=t(f"lang_name_{language}")),
        ):
            return

        try:
            stats = service.normalize_modules_language(language)
        except Exception as e:
            err_text = str(e or "")
            if "Unknown action: modules.normalize_language" in err_text:
                self.show_warning(
                    t("cfg_modules_normalize_title"),
                    t("cfg_modules_normalize_restart_runtime"),
                )
                return
            self.show_warning(t("dlg_error_title"), err_text)
            return

        self.show_info(
            t("cfg_modules_normalize_title"),
            t(
                "cfg_modules_normalize_done",
                language=t(f"lang_name_{str(stats.get('language') or language)}"),
                changed=int(stats.get("changed") or 0),
                eligible=int(stats.get("eligible") or 0),
                skipped=int(stats.get("skipped") or 0),
            ),
        )

    def _on_new_document(self) -> None:
        dlg = NewDocumentDialog(self)
        try:
            for i in range(dlg.list.count()):
                it = dlg.list.item(i)
                tid = str(it.data(Qt.ItemDataRole.UserRole) or "")
                if tid == "text":
                    it.setIcon(self._tb_icon("file-text"))
                elif tid == "picture":
                    it.setIcon(self._tb_icon("file-image"))
                elif tid == "html":
                    it.setIcon(self._tb_icon("file-code"))
        except Exception:
            pass

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        tp = str(dlg.selected_type_id or "")
        if tp == "text":
            self._open_external_text_editor(None)
        elif tp == "templates":
            self._on_templates()
        else:
            self._on_open_file()

    def _on_open_file(self) -> None:
        filters = [
            t("file_filter_1c_all"),
            t("file_filter_text_doc"),
            t("file_filter_picture"),
            t("file_filter_xml"),
            t("file_filter_ext_proc"),
            t("file_filter_ext_report"),
            t("file_filter_html"),
            t("file_filter_pdf"),
            t("file_filter_all"),
        ]
        dlg = QFileDialog(self, t("dlg_open_title"))
        dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
        dlg.setNameFilters(filters)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        path = dlg.selectedFiles()[0] if dlg.selectedFiles() else ""
        if not path:
            return
        p = Path(path)
        ext = p.suffix.lower()
        if ext in (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".ico", ".webp"):
            self._open_external_image_viewer(p)
            return
        self._open_external_text_editor(p)

    def _save_editor_widget(self, widget) -> bool:
        save = getattr(widget, "save", None)
        if not callable(save):
            return True
        try:
            return save() is not False
        except Exception as exc:
            self.show_warning(t("dlg_error_title"), str(exc))
            return False

    def _save_viewmodel_state(self) -> bool:
        save = getattr(getattr(self, "_vm", None), "on_save", None)
        if callable(save):
            try:
                return save() is not False
            except Exception as exc:
                self.show_warning(t("dlg_error_title"), str(exc))
                return False
        try:
            self.saveRequested.emit()
            return True
        except Exception as exc:
            self.show_warning(t("dlg_error_title"), str(exc))
            return False

    def _save_all_open_editors(self) -> bool:
        seen: set[int] = set()
        for sub in list(getattr(self, "_open_windows", {}).values()):
            try:
                widget = sub.widget()
            except Exception:
                widget = None
            if widget is None or id(widget) in seen:
                continue
            seen.add(id(widget))
            if not self._save_editor_widget(widget):
                return False
        if not self._save_viewmodel_state():
            return False
        return True

    def _on_save(self) -> bool:
        w = self._active_editor_widget()
        if w is not None and hasattr(w, "save") and callable(getattr(w, "save")):
            if not self._save_editor_widget(w):
                self._update_save_enabled()
                return False
            try:
                reload_fn = getattr(w, "reload_from_vm", None)
                if callable(reload_fn):
                    try:
                        reload_fn()
                    except Exception:
                        pass
                else:
                    refresh_fn = getattr(w, "refresh", None)
                    if callable(refresh_fn):
                        try:
                            refresh_fn()
                        except Exception:
                            pass
                refresh_requested = getattr(self, "refreshRequested", None)
                if callable(getattr(refresh_requested, "emit", None)):
                    try:
                        refresh_requested.emit()
                    except Exception:
                        pass
                self._update_save_enabled()
                return True
            except Exception:
                return False
        return self._save_viewmodel_state()

    def _on_print(self, *, preview: bool) -> None:
        focus = QApplication.focusWidget()
        doc = None
        try:
            if hasattr(focus, "document") and callable(getattr(focus, "document")):
                doc = focus.document()
        except Exception:
            doc = None
        if doc is None:
            return

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        if preview:
            dlg = QPrintPreviewDialog(printer, self)
            dlg.paintRequested.connect(lambda p: doc.print_(p))
            dlg.exec()
            return

        dlg = QPrintDialog(printer, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            try:
                doc.print_(printer)
            except Exception:
                pass

    def _on_global_search(self) -> None:
        dlg = GlobalSearchDialog(self, search_fn=self._global_search_provider, open_hit_fn=self._open_global_search_hit)
        dlg.exec()

    def _global_search_provider(self, term: str, opts: GlobalSearchOptions):
        if self._vm is None:
            return []
        term = str(term or "")
        if not term:
            return []
        service = getattr(self._vm, "_service", None)
        semantic_search = getattr(service, "find_workspace_references", None)
        use_semantic = (
            bool(opts.whole_word)
            and not str(getattr(opts, "module_guid", "") or "").strip()
            and len([part for part in term.split(".") if part.strip()]) >= 2
            and callable(semantic_search)
        )
        search = (
            semantic_search
            if use_semantic
            else getattr(service, "search_module_text", None)
        )
        if not callable(search):
            return []
        if use_semantic:
            rows = search(
                term,
                limit=int(getattr(opts, "limit", 500) or 500),
                include_declaration=True,
            )
        else:
            rows = search(
                term,
                match_case=bool(opts.match_case),
                whole_word=bool(opts.whole_word),
                module_guid=str(getattr(opts, "module_guid", "") or ""),
                limit=int(getattr(opts, "limit", 500) or 500),
            )
        hits = []
        for r in rows:
            owner_guid = str(r.get("owner_guid") or "")
            owner_title = owner_guid
            try:
                if self._vm is not None and owner_guid:
                    meta = self._vm.get_meta_by_guid(owner_guid)
                    if isinstance(meta, dict):
                        payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
                        if str(meta.get("type") or "").strip().lower() == "common_module":
                            from src.ui_qt.module_titles import localized_code_name
                            owner_title = localized_code_name(payload, meta.get("name") or owner_guid)
                        else:
                            owner_title = str(meta.get("title") or meta.get("name") or owner_guid)
            except Exception:
                pass

            module_guid = str(r.get("module_guid") or "")
            mod_kind = str(r.get("module_kind") or r.get("name") or "module")

            hits.append(
                GlobalSearchHit(
                    title=owner_title,
                    where=mod_kind,
                    line=int(r.get("line") or 0),
                    col=int(r.get("col") or 0),
                    preview=str(r.get("preview") or ""),
                    payload={"module_guid": module_guid, "owner_guid": owner_guid},
                )
            )
        return hits

    def _open_global_search_hit(self, hit: GlobalSearchHit) -> None:
        module_guid = str((hit.payload or {}).get("module_guid") or "")
        if not module_guid or self._vm is None:
            return
        title = f"{hit.title} / {hit.where}"
        self._open_module_by_guid(module_guid, title, line=int(hit.line or 0))

    def _meta_find_from_toolbar(self) -> None:
        text = str(getattr(self, "_tb_find_edit", None).text() if getattr(self, "_tb_find_edit", None) is not None else "").strip()
        if not text:
            return
        self._meta_search_start(
            text,
            MetadataSearchOptions(in_names=True, in_synonyms=False, in_comments=False, match_case=False, whole_word=False),
        )

    def _open_meta_search_dialog(self) -> None:
        dlg = MetadataSearchDialog(self, on_search=self._meta_search_start)
        dlg.exec()

    def _meta_search_start(self, text: str, opts: MetadataSearchOptions) -> None:
        self._meta_find_term = str(text or "")
        self._meta_find_opts = opts
        self._meta_find_matches = self._collect_meta_matches(self._meta_find_term, opts)
        self._meta_find_pos = -1
        self._meta_find_next(prev=False)

    def _meta_find_next(self, *, prev: bool) -> None:
        matches = getattr(self, "_meta_find_matches", []) or []
        if not matches:
            return
        pos = int(getattr(self, "_meta_find_pos", -1))
        if prev:
            pos = (pos - 1) % len(matches)
        else:
            pos = (pos + 1) % len(matches)
        self._meta_find_pos = pos
        idx = matches[pos]
        try:
            self.tree.setCurrentIndex(idx)
            self.tree.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)
            par = idx.parent()
            while par.isValid():
                self.tree.expand(par)
                par = par.parent()
        except Exception:
            pass

    def _collect_meta_matches(self, text: str, opts: MetadataSearchOptions):
        text = str(text or "")
        if not text:
            return []
        needle = text if opts.match_case else text.lower()

        def _match(s: str) -> bool:
            if not s:
                return False
            hay = s if opts.match_case else s.lower()
            if opts.whole_word:
                import re

                return re.search(r"\b" + re.escape(needle) + r"\b", hay) is not None
            return needle in hay

        res = []
        m = self.tree_model
        if m is None:
            return res

        def walk(item):
            if item is None:
                return
            meta = item.data(self.ROLE_META)
            title = item.text() or ""
            ok = False
            if opts.in_names and _match(title):
                ok = True
            if not ok and isinstance(meta, dict):
                payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
                if opts.in_synonyms:
                    syn = payload.get("synonyms") or payload.get("synonym")
                    if isinstance(syn, list):
                        syn = " ".join([str(x) for x in syn])
                    if isinstance(syn, str) and _match(syn):
                        ok = True
                if not ok and opts.in_comments:
                    cmt = payload.get("comment") or payload.get("comments")
                    if isinstance(cmt, str) and _match(cmt):
                        ok = True

            if ok:
                res.append(item.index())

            for i in range(item.rowCount()):
                child = item.child(i)
                if child is not None:
                    walk(child)

        for r in range(m.rowCount()):
            it = m.item(r)
            if it is not None:
                walk(it)

        return res

    def _on_windows_list(self) -> None:
        dlg = WindowsListDialog(self, mdi=self.mdi)
        dlg.exec()

    def _on_syntax_helper(self) -> None:
        key = "syntax_helper"
        if key in self._open_windows:
            self.mdi.setActiveSubWindow(self._open_windows[key])
            self._open_windows[key].showNormal()
            return
        w = SyntaxHelperWidget(self)
        sub = QMdiSubWindow()
        sub.setWidget(w)
        sub.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        sub.setWindowTitle(t("act_syntax_help"))

        def _on_destroyed():
            self._open_windows.pop(key, None)

        sub.destroyed.connect(_on_destroyed)
        self.mdi.addSubWindow(sub)
        sub.resize(900, 620)
        sub.show()
        self._open_windows[key] = sub

    def _on_syntax_helper_search(self) -> None:
        self._on_syntax_helper()
        sub = self._open_windows.get("syntax_helper")
        if sub is None:
            return
        w = sub.widget()
        if w is None or not hasattr(w, "tabs"):
            return
        try:
            w.tabs.setCurrentIndex(2)
            q = str(getattr(self, "_tb_find_edit", None).text() if getattr(self, "_tb_find_edit", None) is not None else "").strip()
            if q and hasattr(w, "ed_search"):
                w.ed_search.setText(q)
        except Exception:
            pass

    def _on_templates(self) -> None:
        dlg = CodeTemplatesDialog(self, insert_fn=lambda text: self._insert_text_to_focus(text))
        dlg.exec()

    def _insert_text_to_focus(self, text: str) -> None:
        w = QApplication.focusWidget()
        if w is None:
            return
        for meth in ("insertPlainText", "insertText"):
            fn = getattr(w, meth, None)
            if callable(fn):
                try:
                    fn(str(text))
                    return
                except Exception:
                    pass
        try:
            tc = getattr(w, "textCursor", None)
            if callable(tc):
                cur = tc()
                cur.insertText(str(text))
        except Exception:
            pass

    def _on_about(self) -> None:
        import platform

        ver = platform.python_version()
        QMessageBox.information(self, t("about_title"), t("about_text", version=ver))

    def _open_external_text_editor(self, path: Path | None) -> None:
        key = f"file:{str(path)}" if path else f"file:untitled:{id(self)}:{self.mdi.subWindowList().__len__()}"
        if path and key in self._open_windows:
            self.mdi.setActiveSubWindow(self._open_windows[key])
            self._open_windows[key].showNormal()
            return
        w = ExternalTextFileEditorWidget(path=path)
        sub = QMdiSubWindow()
        sub.setWidget(w)
        sub.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        sub.setWindowTitle(w.title())

        def _on_destroyed():
            self._open_windows.pop(key, None)

        sub.destroyed.connect(_on_destroyed)
        try:
            w.dirtyChanged.connect(lambda _d: sub.setWindowTitle(w.title() + (" *" if w.is_dirty() else "")))
        except Exception:
            pass
        self.mdi.addSubWindow(sub)
        sub.resize(860, 560)
        sub.show()
        self._open_windows[key] = sub
        self._update_save_enabled()

    def _open_external_image_viewer(self, path: Path) -> None:
        key = f"img:{str(path)}"
        if key in self._open_windows:
            self.mdi.setActiveSubWindow(self._open_windows[key])
            self._open_windows[key].showNormal()
            return
        w = ExternalImageViewerWidget(path=path)
        sub = QMdiSubWindow()
        sub.setWidget(w)
        sub.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        sub.setWindowTitle(w.title())

        def _on_destroyed():
            self._open_windows.pop(key, None)

        sub.destroyed.connect(_on_destroyed)
        self.mdi.addSubWindow(sub)
        sub.resize(900, 620)
        sub.show()
        self._open_windows[key] = sub

    def set_status(self, text: str) -> None:
        self.statusBar().showMessage(text)

    def _set_onec_import_progress(self, *, progress: int, message: str, phase_text: str = "") -> None:
        pct = max(0, min(100, int(progress)))
        msg = self._compact_onec_import_message(str(message or "").strip() or t("dlg_onec_import_progress_body"))

        # Бар зліва
        self._import_progress_bar.setValue(pct)

        # Текст праворуч: відсоток + коротке повідомлення
        label_text = f"{pct}%"
        if msg:
            # елідуємо до 40 символів
            short_msg = msg if len(msg) <= 40 else msg[:37] + "…"
            label_text = f"{pct}%  {short_msg}"
        self._import_progress_label.setText(label_text)
        self._import_progress_label.setToolTip(msg)

        # Показуємо host
        host = getattr(self, "_import_progress_host", None)
        if host is not None:
            host.setVisible(True)
        anim = getattr(self, "_import_pulse_anim", None)
        if anim is not None:
            try:
                anim.start()
            except Exception:
                pass

        # Діалог
        if self._import_progress_dialog is not None:
            self._import_progress_dialog.setValue(pct)
            self._import_progress_dialog.setLabelText(msg)
            if hasattr(self._import_progress_dialog, "setPhaseText") and phase_text:
                try:
                    self._import_progress_dialog.setPhaseText(str(phase_text or "").strip())
                except Exception:
                    pass

        self.set_status(msg)

    def _begin_onec_import_ui(self, *, runtime_url: str, session_id: str) -> None:
        self._import_session_id = str(session_id or "").strip()
        self._import_status_gateway = None
        runtime_url = str(runtime_url or "").strip()
        if runtime_url and self._import_session_id:
            from src.runtime.gateway import RuntimeGateway

            self._import_status_gateway = RuntimeGateway(runtime_url)
            self._import_status_gateway.session_id = self._import_session_id

        prog = CircularProgressDialog(self)
        prog.setWindowTitle(t("dlg_onec_import_progress_title"))
        prog.setValue(0)
        prog.setLabelText(t("dlg_onec_import_progress_body"))
        prog.show()
        self._import_progress_dialog = prog
        self._set_onec_import_progress(progress=0, message=t("dlg_onec_import_progress_body"))
        if self._import_status_gateway is not None:
            self._import_status_timer.start()

    def _end_onec_import_ui(self) -> None:
        try:
            self._import_status_timer.stop()
        except Exception:
            pass
        self._import_status_gateway = None
        self._import_session_id = ""
        self._import_progress_bar.setValue(0)
        self._import_progress_label.setText("")
        anim = getattr(self, "_import_pulse_anim", None)
        if anim is not None:
            try:
                anim.stop()
            except Exception:
                pass
        host = getattr(self, "_import_progress_host", None)
        if host is not None:
            host.setVisible(False)
        if self._import_progress_dialog is not None:
            try:
                self._import_progress_dialog.close()
                self._import_progress_dialog.deleteLater()
            except Exception:
                pass
        self._import_progress_dialog = None

    def _poll_onec_import_status(self) -> None:
        gw = self._import_status_gateway
        sid = str(self._import_session_id or "").strip()
        if gw is None or not sid:
            return
        try:
            state = gw.onec_import_status(session_id=sid)
        except Exception:
            return
        if not isinstance(state, dict) or not state:
            return
        phase = str(state.get("phase") or "").strip().lower()
        phase_text = {
            "start": "Підготовка",
            "reset": "Скидання",
            "manifest": "Імпорт manifest",
            "parse": "Парсинг XML",
            "enrich": "Збагачення",
            "data": "Міграція даних",
            "finalize": "Фіналізація",
            "done": "Готово",
            "failed": "Помилка",
        }.get(phase, "")
        self._set_onec_import_progress(
            progress=int(state.get("progress") or 0),
            message=str(state.get("message") or t("dlg_onec_import_progress_body")),
            phase_text=phase_text,
        )

    def _cleanup_onec_import_worker(self) -> None:
        self._import_worker = None
        self._import_thread = None

    def _onec_import_finished(self, message: str) -> None:
        vm = getattr(self, "_vm", None)
        self._set_onec_import_progress(progress=100, message=t("dlg_onec_import_refreshing"))
        try:
            if vm is not None:
                vm.reopen_db()
            refresh_requested = getattr(self, "refreshRequested", None)
            if refresh_requested is not None and hasattr(refresh_requested, "emit"):
                refresh_requested.emit()
            self._auto_open_subsystem_membership_report()
            self._auto_repair_source_structure_after_import()
        except Exception as exc:
            self._end_onec_import_ui()
            self._cleanup_onec_import_worker()
            self.show_warning(t("dlg_error_title"), f"{t('dlg_load_cfg_failed')}\n\n{exc}")
            return
        self._end_onec_import_ui()
        self._cleanup_onec_import_worker()
        self.show_info(t("info_title"), message or t("dlg_load_cfg_result_ok"))

    def _onec_import_failed(self, error_text: str) -> None:
        vm = getattr(self, "_vm", None)
        try:
            if vm is not None:
                vm.reopen_db()
                try:
                    vm.refresh_from_runtime()
                except Exception:
                    try:
                        vm.start_background_runtime_refresh()
                    except Exception:
                        pass
            refresh_requested = getattr(self, "refreshRequested", None)
            if refresh_requested is not None and hasattr(refresh_requested, "emit"):
                refresh_requested.emit()
        except Exception:
            pass
        self._end_onec_import_ui()
        self._cleanup_onec_import_worker()
        self.show_warning(t("dlg_error_title"), f"{t('dlg_load_cfg_failed')}\n\n{error_text}")

    def _auto_open_subsystem_membership_report(self) -> None:
        vm = getattr(self, "_vm", None)
        if vm is None:
            return

        def _run() -> None:
            try:
                sync_fn = getattr(vm, "sync_subsystem_membership", None)
                if callable(sync_fn):
                    report = sync_fn()
                else:
                    report = vm.diagnose_subsystem_membership()
                self._save_subsystem_membership_report(report)
                if int(report.get("changed") or 0) > 0:
                    refresh_requested = getattr(self, "refreshRequested", None)
                    if refresh_requested is not None and hasattr(refresh_requested, "emit"):
                        refresh_requested.emit()
                self._auto_open_report_object(report)
                self._show_subsystem_membership_report()
            except Exception:
                pass

        QTimer.singleShot(0, _run)

    def _auto_open_source_structure_compare_report(self) -> None:
        vm = getattr(self, "_vm", None)
        if vm is None or not hasattr(vm, "compare_source_structure"):
            return

        def _run() -> None:
            try:
                source_path, source_kind = self._resolve_compare_source()
                if not source_path:
                    return
                report = vm.compare_source_structure(source_path=source_path, source_kind=source_kind or "auto")
                self._save_source_structure_compare_report(report)
                self._show_source_structure_compare_report()
            except Exception:
                pass

        QTimer.singleShot(0, _run)

    def _auto_repair_source_structure_after_import(self) -> None:
        vm = getattr(self, "_vm", None)
        if vm is None:
            return

        compare_fn = getattr(vm, "compare_source_structure", None)
        repair_fn = getattr(vm, "repair_source_structure", None)
        if not callable(compare_fn) or not callable(repair_fn):
            return

        def _run() -> None:
            try:
                source_path, source_kind = self._resolve_compare_source()
                if not source_path:
                    return
                report = compare_fn(source_path=source_path, source_kind=source_kind or "auto")
                self._save_source_structure_compare_report(report)
                summary = dict(report.get("summary") or {})
                has_issues = bool(
                    int(summary.get("flattened_subtree_count") or 0)
                    or int(summary.get("parent_child_mismatch_count") or 0)
                )
                if not has_issues:
                    return
                result = repair_fn(source_path=source_path, source_kind=source_kind or "auto")
                repaired_report = dict(result.get("report") or {})
                if repaired_report:
                    self._save_source_structure_compare_report(repaired_report)
                try:
                    refresh_requested = getattr(self, "refreshRequested", None)
                    if refresh_requested is not None and hasattr(refresh_requested, "emit"):
                        refresh_requested.emit()
                except Exception:
                    pass
                final_report = compare_fn(source_path=source_path, source_kind=source_kind or "auto")
                self._save_source_structure_compare_report(final_report)
                self._show_source_structure_compare_report()
            except Exception:
                pass

        QTimer.singleShot(0, _run)

    def _start_onec_import(
        self,
        *,
        source_path: str,
        source_kind: str,
        wipe_prefixes: bool,
        migrate_data: bool = False,
        interactive: bool = True,
    ) -> dict[str, object]:
        def _reject(message: str) -> dict[str, object]:
            if interactive:
                self.show_warning(t("dlg_error_title"), message)
            return {"started": False, "session_id": "", "error": message}

        vm = getattr(self, "_vm", None)
        if vm is None:
            return _reject(t("dlg_vm_not_ready"))
        if self._import_thread is not None and self._import_thread.isRunning():
            return _reject(t("dlg_onec_import_close_blocked"))

        runtime_url = str(self.runtime_url or "").strip()
        db_uid = str(self.db_uid_str or "").strip()
        local_db_path = str(
            getattr(self, "db_path", None)
            or getattr(vm, "db_path", None)
            or os.environ.get("META_DB_PATH", "")
        ).strip()
        if not runtime_url or not db_uid:
            return _reject(t("dlg_load_cfg_failed"))

        # The configurator session is closed before a destructive import. Use a
        # dedicated session so the worker never receives an invalidated id.
        import_gateway = None
        try:
            from src.runtime.gateway import RuntimeGateway

            import_gateway = RuntimeGateway(runtime_url)
            session_id = str(import_gateway.ensure_session() or "").strip()
            # Runtime's UID registry is process-local and the DB UID may
            # change after a staging swap. The canonical path is therefore
            # authoritative whenever Configurator has it.
            if local_db_path:
                open_info = import_gateway.open_by_path(local_db_path)
            else:
                open_info = import_gateway.open_by_uid(db_uid)
            resolved_db_uid = str((open_info or {}).get("db_uid") or "").strip()
            if resolved_db_uid:
                db_uid = resolved_db_uid
                self.db_uid_str = resolved_db_uid
        except Exception as exc:
            if import_gateway is not None:
                import_gateway.close_session()
            return _reject(f"{type(exc).__name__}: {exc}")
        if not session_id:
            return _reject(t("dlg_load_cfg_failed"))

        try:
            from src.platform.onec_import_state import remember_last_onec_import

            remember_last_onec_import(source_path=source_path, source_kind=source_kind)
        except Exception:
            pass
        try:
            os.environ["META_LAST_ONEC_SOURCE_PATH"] = str(source_path or "").strip()
            os.environ["META_LAST_ONEC_SOURCE_KIND"] = str(source_kind or "").strip()
        except Exception:
            pass

        vm.close_db()
        self._begin_onec_import_ui(runtime_url=runtime_url, session_id=session_id)

        worker = _OnecImportWorker(
            db_path=local_db_path,
            source_path=source_path,
            source_kind=source_kind,
            runtime_url=runtime_url,
            db_uid=db_uid,
            session_id=session_id,
            wipe_prefixes=wipe_prefixes,
            migrate_data=migrate_data,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._onec_import_finished)
        worker.failed.connect(self._onec_import_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_onec_import_worker)
        self._import_worker = worker
        self._import_thread = thread
        thread.start()
        return {"started": True, "session_id": session_id, "error": ""}

    def show_info(self, title: str, text: str) -> None:
        QMessageBox.information(self, title, text)

    def show_warning(self, title: str, text: str) -> None:
        QMessageBox.warning(self, title, text)

    def confirm(self, title: str, text: str) -> bool:
        return (
            QMessageBox.question(
                self,
                title,
                text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        )

    def open_admin_users(self, *, active_only: bool = False) -> None:
        vm = getattr(self, "_vm", None)
        if vm is None or not hasattr(vm, "list_users"):
            self.show_info(t("info_title"), t("info_not_implemented"))
            return
        rows = vm.list_users(active_only=active_only)
        title = t("admin_users") if not active_only else t("admin_active_users")
        db = getattr(vm, "db", None)
        dlg = UsersAdminDialog(self, title=title, rows=rows, db=db)
        dlg.exec()

    def open_admin_audit_log(self) -> None:
        vm = getattr(self, "_vm", None)
        if vm is None or not hasattr(vm, "list_audit_log") or not hasattr(vm, "list_users"):
            self.show_info(t("info_title"), t("info_not_implemented"))
            return
        rows = vm.list_audit_log(limit=500)
        users = vm.list_users(active_only=False)
        user_map = {str(u.get("user_id") or ""): str(u.get("login") or u.get("display_name") or "") for u in users}
        dlg = AuditLogDialog(self, title=t("admin_reg_log"), rows=rows, user_map=user_map)
        dlg.exec()

    def _get_admin_db(self):
        vm = getattr(self, "_vm", None)
        if vm is None:
            return None
        return getattr(vm, "db", None)

    def _open_log_settings(self) -> None:
        dlg = LogSettingsDialog(self, db=self._get_admin_db())
        dlg.exec()

    def _open_regional_settings(self) -> None:
        dlg = RegionalSettingsDialog(self, db=self._get_admin_db())
        dlg.exec()

    def _open_auth_settings(self) -> None:
        dlg = AuthSettingsDialog(self, db=self._get_admin_db())
        dlg.exec()

    def _wire_code_editor_definition_navigation(self, editor: CodeEditorWidget) -> None:
        if bool(editor.property("mp_definition_navigation_wired")):
            return
        editor.definitionRequested.connect(self._open_definition_target)
        editor.usagesRequested.connect(self._open_usages_target)
        editor.saved.connect(
            lambda _asset_key: QTimer.singleShot(
                0,
                self._refresh_workspace_problems_if_visible,
            )
        )
        panel = getattr(self, "workspace_problems", None)
        state = getattr(panel, "state", None)
        if callable(state):
            editor.set_workspace_diagnostics(
                list(
                    (state(include_diagnostics=True) or {}).get(
                        "diagnostics",
                        [],
                    )
                )
            )
        editor.setProperty("mp_definition_navigation_wired", True)

    def _open_usages_target(self, query: dict) -> None:
        term = str((query or {}).get("term") or "").strip()
        if not term:
            return
        options = GlobalSearchOptions(
            match_case=bool((query or {}).get("match_case", False)),
            whole_word=bool((query or {}).get("whole_word", True)),
            module_guid=str((query or {}).get("module_guid") or "").strip(),
            limit=int((query or {}).get("limit") or 500),
        )
        dlg = GlobalSearchDialog(
            self,
            search_fn=self._global_search_provider,
            open_hit_fn=self._open_global_search_hit,
            initial_term=term,
            initial_options=options,
            auto_start=True,
        )
        dlg.setModal(False)
        dialogs = getattr(self, "_usage_search_dialogs", None)
        if dialogs is None:
            dialogs = []
            self._usage_search_dialogs = dialogs
        dialogs.append(dlg)

        def _forget_dialog(*_args) -> None:
            if dlg in dialogs:
                dialogs.remove(dlg)

        dlg.finished.connect(_forget_dialog)
        dlg.destroyed.connect(_forget_dialog)
        dlg.show()

    def _open_definition_target(self, target: dict) -> None:
        kind = str((target or {}).get("kind") or "").strip().lower()
        line = int((target or {}).get("line") or 0)
        title = str((target or {}).get("title") or (target or {}).get("name") or "").strip()
        if kind == "module":
            module_guid = str((target or {}).get("module_guid") or (target or {}).get("guid") or "").strip()
            self._open_module_by_guid(module_guid, title or module_guid, line=line)
            return
        if kind == "metadata":
            guid = str((target or {}).get("guid") or "").strip()
            if not guid:
                return
            self.open_object_tab(
                NodeInfo(
                    kind="object",
                    name=title or guid,
                    guid=guid,
                    obj_type=str((target or {}).get("obj_type") or ""),
                )
            )

    def _open_module_by_guid(self, module_guid: str, title: str = "", *, line: int = 0) -> None:
        if not module_guid:
            return
        info = NodeInfo(kind="object", name=title or module_guid, guid=module_guid, obj_type="common_module")
        # All metadata documents must use the same workspace factory. This
        # keeps module tabs consistent with forms: one lifecycle, one dirty
        # guard, one title/icon policy, and one properties context.
        self.open_object_tab(info)
        sub = self._open_windows.get(module_guid)
        w = sub.widget() if sub is not None else None
        if line > 0 and isinstance(w, CodeEditorWidget):
            QTimer.singleShot(0, lambda editor=w, target_line=line: editor.navigate_to_line(target_line))

    def _open_module_ref(self, module_ref: str, title: str = "") -> None:
        ref = str(module_ref or "").strip()
        if not ref:
            return
        if ref.startswith("module://"):
            ref = ref.split("://", 1)[1].strip()
        if not ref:
            return
        label = str(title or ref).replace("_", " ").strip()
        self._open_module_by_guid(ref, label or ref)

    def _open_cfg_module(self, module_name: str, title: str = "") -> None:
        if self._vm is None:
            return
        try:
            db = self._vm._service.require_db()
            rows = db.table("manifest").select() or []
            row = next(
                (
                    r
                    for r in rows
                    if str(r.get("name") or "").strip().lower() == module_name.strip().lower()
                    and str(r.get("type") or "").strip().lower() == "common_module"
                ),
                None,
            )
            if row:
                self._open_module_by_guid(str(row["guid"]), title or module_name)
                return
        except Exception:
            pass
        reply = QMessageBox.question(
            self,
            title or module_name,
            t("dlg_module_not_found_create").format(name=module_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            if self._vm:
                self._vm.create_common_module(module_name, title=title)
        except Exception as e:
            self.show_warning(t("dlg_error_title"), str(e))

    def _open_infobase_params(self) -> None:
        vm = getattr(self, "_vm", None)
        db_path = ""
        if vm is not None:
            try:
                db_path = str(getattr(vm, "db_path", "") or "")
            except Exception:
                pass
        dlg = InforbaseParamsDialog(self, db=self._get_admin_db(), db_path=db_path)
        dlg.exec()

    def _open_module_browser(self) -> None:
        key = "module_browser"
        if key in self._open_windows:
            self.mdi.setActiveSubWindow(self._open_windows[key])
            self._open_windows[key].showNormal()
            return
        from src.ui_qt.widgets.module_browser import ModuleBrowserWidget

        w = ModuleBrowserWidget(vm=self._vm)
        w.open_module_requested.connect(self._open_module_by_guid)
        sub = QMdiSubWindow()
        sub.setWidget(w)
        sub.setWindowTitle(t("admin_module_browser"))
        sub.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        sub.destroyed.connect(lambda: self._open_windows.pop(key, None))
        self.mdi.addSubWindow(sub)
        sub.resize(700, 500)
        sub.show()
        self._open_windows[key] = sub

    def _run_unload_db(self) -> None:
        db = self._get_admin_db()
        if db is None:
            self.show_warning(t("dlg_error_title"), t("dlg_vm_not_ready"))
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            t("admin_unload_db"),
            f"metaplatform_backup_{__import__('time').strftime('%Y%m%d_%H%M%S')}.zip",
            "ZIP Archive (*.zip)",
        )
        if not path:
            return

        prog = QProgressDialog(t("admin_unload_progress"), None, 0, 0, self)
        prog.setWindowTitle(t("admin_unload_db"))
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        prog.setValue(0)
        try:
            from src.configurator.persistence.db_export import DbExporter

            report = DbExporter(db).export_zip(path)
            prog.close()
            if report.errors:
                self.show_warning(t("admin_unload_db"), "\n".join(report.errors[:10]))
            else:
                self.show_info(
                    t("admin_unload_db"),
                    t("admin_unload_ok").format(tables=len(report.tables_exported), rows=report.rows_exported, path=path),
                )
        except Exception as e:
            prog.close()
            self.show_warning(t("dlg_error_title"), str(e))

    def _run_load_db(self) -> None:
        db = self._get_admin_db()
        if db is None:
            self.show_warning(t("dlg_error_title"), t("dlg_vm_not_ready"))
            return

        path, _ = QFileDialog.getOpenFileName(self, t("admin_load_db"), "", "ZIP Archive (*.zip)")
        if not path:
            return

        reply = QMessageBox.warning(
            self,
            t("admin_load_db"),
            t("admin_load_db_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        prog = QProgressDialog(t("admin_load_progress"), None, 0, 0, self)
        prog.setWindowTitle(t("admin_load_db"))
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        prog.setValue(0)
        try:
            from src.configurator.persistence.db_export import DbImporter

            report = DbImporter(db).import_zip(path, replace=False)
            prog.close()
            if hasattr(self, "_vm") and self._vm:
                try:
                    self._vm.on_refresh()
                except Exception:
                    pass
            if report.errors:
                self.show_warning(t("admin_load_db"), "\n".join(report.errors[:10]))
            else:
                self.show_info(
                    t("admin_load_db"),
                    t("admin_load_ok").format(tables=len(report.tables_imported), rows=report.rows_imported),
                )
        except Exception as e:
            prog.close()
            self.show_warning(t("dlg_error_title"), str(e))

    def _run_update_db(self) -> None:
        vm = getattr(self, "_vm", None)
        if vm is None:
            self.show_warning(t("dlg_error_title"), t("dlg_vm_not_ready"))
            return

        prog = QProgressDialog(t("admin_update_db_progress"), None, 0, 0, self)
        prog.setWindowTitle(t("admin_update_db"))
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        prog.setValue(0)

        try:
            report = dict(vm._service.deploy_schema() or {})
            prog.close()

            errors = list(report.get("errors") or [])
            if errors:
                err_text = "\n".join(f"• {e}" for e in errors[:10])
                self.show_warning(
                    t("admin_update_db"),
                    f"{t('admin_update_db_errors').format(n=len(errors))}\n\n{err_text}",
                )
            else:
                self.show_info(
                    t("admin_update_db"),
                    t("admin_update_db_ok").format(
                        created=int(report.get("created") or 0),
                        existing=int(report.get("existing") or 0),
                    ),
                )
        except Exception as e:
            prog.close()
            self.show_warning(t("dlg_error_title"), str(e))

    def _open_test_repair(self) -> None:
        dlg = TestRepairDialog(self, db=self._get_admin_db())
        dlg.exec()

    def _load_configuration_from_files(self, *_args, initial_mode: str = "") -> None:
        vm = getattr(self, "_vm", None)
        if vm is None:
            self.show_warning(t("dlg_error_title"), t("dlg_vm_not_ready"))
            return

        dlg = LoadConfigDialog(self, initial_mode=initial_mode)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        src_kind, src_path = dlg.get_result()
        migrate_data = False
        try:
            migrate_data = bool(dlg.should_import_data())
        except Exception:
            migrate_data = False
        src_kind = str(src_kind or "").strip().lower()
        src_path = str(src_path or "").strip()
        if not src_path:
            return

        mb = QMessageBox(self)
        mb.setIcon(QMessageBox.Icon.Warning)
        mb.setWindowTitle(t("dlg_onec_import_hard_title"))
        mb.setText(t("dlg_onec_import_hard_body"))
        cb = QCheckBox(t("dlg_onec_import_opt_wipe_prefixes"))
        cb.setChecked(True)
        try:
            mb.setCheckBox(cb)
        except Exception:
            cb = None
        mb.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if mb.exec() != QMessageBox.StandardButton.Yes:
            return

        wipe_prefixes = True
        try:
            if cb is not None:
                wipe_prefixes = bool(cb.isChecked())
        except Exception:
            wipe_prefixes = True

        self._start_onec_import(
            source_path=src_path,
            source_kind=("zip" if src_kind in {"archive", "zip"} else src_kind or "auto"),
            wipe_prefixes=wipe_prefixes,
            migrate_data=migrate_data,
        )

    def _load_onecd_database(self) -> None:
        self._load_configuration_from_files(initial_mode="1cd")

    def _launch_client(self, *, debug: bool) -> None:
        runtime_url = str(self.runtime_url or os.environ.get("META_RUNTIME_URL", "")).strip()
        db_uid = str(self.db_uid_str or os.environ.get("META_DB_UID", "")).strip()
        if not runtime_url or not db_uid:
            QMessageBox.warning(self, t("dlg_client_title"), "Runtime URL or DB UID is missing.")
            return
        if not self._save_all_open_editors():
            return
        env = os.environ.copy()
        env["META_RUNTIME_URL"] = runtime_url
        env["META_DB_UID"] = db_uid
        env["META_CONTROL_API_HOST"] = str(os.environ.get("META_CONTROL_API_HOST", "127.0.0.1") or "127.0.0.1").strip() or "127.0.0.1"
        env["META_CONTROL_API_PORT"] = str(int(os.environ.get("META_CONTROL_API_PORT", "8766") or "8766"))
        vm = getattr(self, "_vm", None)
        try:
            session_id = str(vm.runtime_session_id() or "").strip() if vm is not None else ""
        except Exception:
            session_id = ""
        if session_id:
            env["META_SESSION_ID"] = session_id
        db_name = str(env.get("META_DB_NAME") or "").strip()
        if not db_name:
            env["META_DB_NAME"] = db_uid
        if debug:
            env["META_DEBUG_ENABLED"] = "1"
            env["META_CLIENT_DEBUG"] = "1"
        else:
            env.pop("META_DEBUG_ENABLED", None)
            env.pop("META_CLIENT_DEBUG", None)
        project_root = Path(__file__).resolve().parents[2]
        proc = subprocess.Popen(
            [sys.executable, "-m", "src.client.client_app", "--runtime", runtime_url, "--db-uid", db_uid],
            cwd=str(project_root),
            env=env,
        )
        if debug:
            self._debug_client_process = proc
