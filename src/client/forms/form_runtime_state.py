from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QDateEdit, QFrame, QLabel, QScrollArea, QSizePolicy, QVBoxLayout

from src.configurator.domain.form_model import FormModel
from src.client.data_tables import data_table_name as _data_table
from src.ui_qt.i18n import t

from .form_runtime_types import CommandHandler, ObjContext

AccessChecker = Callable[[str], bool]

# Commands handled by the window/platform — not delegated to form module
_BUILTIN_COMMANDS: frozenset[str] = frozenset({
    "save", "form.save", "saveandclose", "save_close", "form.saveandclose",
    "post", "form.post", "unpost", "form.unpost",
    "close", "form.close", "back", "form.back",
    "refresh", "form.refresh",
    "create", "edit", "delete", "print", "form.print",
    "all_actions", "write", "markdelete",
    "tp_add", "tp_delete", "tp_up", "tp_down", "tp_fill", "tp_all_actions",
})


class FormRuntimeStateMixin:
    _BINDING_ALIASES: dict[str, tuple[str, ...]] = {
        "ref": ("_guid", "ref"),
        "code": ("_code", "code"),
        "description": ("_description", "description", "name"),
        "deletionmark": ("_deleted", "deletionmark", "deleted", "marked"),
        "deletion_mark": ("_deleted", "deletion_mark", "deleted", "marked"),
        "deleted": ("_deleted", "deleted", "marked"),
        "predefined": ("_predefined", "predefined"),
        "number": ("_number", "number"),
        "numberprefix": ("_number_prefix", "numberprefix", "number_prefix"),
        "number_prefix": ("_number_prefix", "number_prefix", "numberprefix"),
        "date": ("_date", "date", "date_time"),
        "datetime": ("_date", "datetime", "date", "date_time"),
        "posted": ("_posted", "posted"),
        "comment": ("comment", "_comment"),
        "period": ("_period", "period"),
        "recorder": ("_recorder", "_doc_guid", "_owner_guid", "recorder"),
        "lineno": ("_line_no", "lineno", "line_no"),
        "linenumber": ("_line_no", "linenumber", "line_no"),
        "line_no": ("_line_no", "line_no", "lineno"),
        "owner": ("_owner_guid", "_doc_guid", "owner"),
        "active": ("_active", "active"),
        "recordkind": ("_record_kind", "recordkind", "record_kind"),
        "record_kind": ("_record_kind", "record_kind", "recordkind"),
        "kind": ("_kind", "kind"),
    }

    def __init__(
        self,
        *,
        model: Dict[str, Any] | FormModel,
        db=None,
        ctx: ObjContext | None = None,
        manifest_rows: List[Dict] | None = None,
        on_command: CommandHandler | None = None,
        access_checker: AccessChecker | None = None,
        embedded: bool = False,
        show_hidden_controls: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._db    = db
        self._ctx   = ctx or ObjContext()
        self._mrows = manifest_rows or []
        self._on_command = on_command
        self._access_checker = access_checker
        self._embedded = bool(embedded)
        self._show_hidden_controls = bool(show_hidden_controls)

        # Form module runner (attached externally after build)
        self._module_runner: Any = None

        # tabular-part tables: binding → QTableView
        self._tp_tables: Dict[str, Any] = {}
        # tabular-part column bindings: binding → [col_name, ...]
        self._tp_col_bindings: Dict[str, List[str]] = {}

        # record data: для object_form — поточний запис
        self._record: Dict[str, Any] = {}
        if self._ctx.rec_guid and self._db and self._ctx.obj_name:
            self._record = self._load_record(self._ctx.rec_guid)
        elif self._ctx.form_kind == "object_form" and not self._ctx.rec_guid:
            # New record — prefill sensible defaults
            self._record = self._default_record_values()

        # binding_name → input widget
        self._bound_inputs: Dict[str, QWidget] = {}
        # list table widget (list_form)
        self._list_table: Optional[QTableView] = None
        self._list_col_bindings: List[str] = []

        self._model = (
            model if isinstance(model, FormModel)
            else FormModel.from_dict(dict(model or {}))
        )

        root_l = QVBoxLayout(self)
        root_l.setContentsMargins(0, 0, 0, 0)
        root_l.setSpacing(0)

        if self._embedded:
            self._form_scroll = None
            self._host_l = root_l
        else:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            root_l.addWidget(scroll, 1)
            self._form_scroll = scroll

            host = QFrame()
            host.setFrameShape(QFrame.Shape.NoFrame)
            host.setMinimumWidth(0)
            host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            scroll.setWidget(host)

            self._host_l = QVBoxLayout(host)
            self._host_l.setContentsMargins(0, 0, 0, 0)
            self._host_l.setSpacing(0)

        self._rebuild()

    def _is_action_allowed(self, action: str) -> bool:
        checker = getattr(self, "_access_checker", None)
        if checker is None:
            return True
        try:
            return bool(checker(str(action or "").strip()))
        except Exception:
            return True

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key  = event.key()
        mods = event.modifiers()
        no_mod = mods == Qt.KeyboardModifier.NoModifier
        ctrl   = mods == Qt.KeyboardModifier.ControlModifier
        if key == Qt.Key.Key_Escape and no_mod:
            self._emit_command("close")
        elif key == Qt.Key.Key_S and ctrl:
            self._emit_command("save")
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and ctrl:
            self._emit_command("saveandclose")
        else:
            super().keyPressEvent(event)


    @staticmethod
    def _binding_key(binding: str) -> str:
        return re.sub(r"[^a-z0-9_]+", "", str(binding or "").strip().casefold())


    @classmethod
    def _binding_candidates(cls, binding: str) -> list[str]:
        raw = str(binding or "").strip()
        if not raw:
            return []
        if raw.startswith("_"):
            return [raw]
        key = cls._binding_key(raw)
        candidates: list[str] = []
        for candidate in cls._BINDING_ALIASES.get(key, ()):
            candidate = str(candidate or "").strip()
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        if raw not in candidates:
            candidates.append(raw)
        if key and key not in candidates:
            candidates.append(key)
        return candidates


    @classmethod
    def _record_value_for_binding(cls, record: Dict[str, Any], binding: str) -> Any:
        if not isinstance(record, dict):
            return ""
        candidates = cls._binding_candidates(binding)
        for candidate in candidates:
            if candidate in record:
                return record.get(candidate)
            for key, value in record.items():
                if str(key or "").casefold() == candidate.casefold():
                    return value
        data = record.get("data")
        if isinstance(data, dict):
            for candidate in candidates:
                if candidate in data:
                    return data.get(candidate)
                for key, value in data.items():
                    if str(key or "").casefold() == candidate.casefold():
                        return value
        return record.get(binding, "")


    @classmethod
    def _record_key_for_binding(cls, binding: str) -> str:
        candidates = cls._binding_candidates(binding)
        return candidates[0] if candidates else str(binding or "")


    def reload_list(self) -> None:
        """Перезавантажити дані в list_form таблиці."""
        if self._list_table is None or self._db is None:
            return
        self._fill_list_table(self._list_table, self._list_col_bindings)


    def collect(self) -> Dict[str, Any]:
        """Зібрати значення всіх bound-полів."""
        self._ui_to_record()
        return dict(self._record)


    def set_record(self, data: Dict[str, Any]) -> None:
        self._record = dict(data)
        self._record_to_ui()


    def selected_rec_guid(self) -> str:
        """Для list_form — GUID виділеного рядка."""
        if self._list_table is None:
            return ""
        idx = self._list_table.currentIndex()
        if not idx.isValid():
            return ""
        model = self._list_table.model()
        # Unwrap proxy model to access source data correctly
        if hasattr(model, "mapToSource"):
            src = model.mapToSource(idx)
            source_m = model.sourceModel() if hasattr(model, "sourceModel") else model
        else:
            src = idx
            source_m = model
        item_idx = source_m.index(src.row(), 0) if hasattr(source_m, "index") else src
        val = source_m.data(item_idx, Qt.ItemDataRole.UserRole)
        return str(val or "")


    def _on_ref_choose(self, binding: str) -> None:
        """Open a picker for a reference-type field."""
        if self._db is None:
            return

        meta = self._binding_schema_meta(binding)
        ref_name = str(meta.get("ref_name") or "").strip()
        ref_targets: list = meta.get("ref_targets") or []

        # Resolve catalog/document name from ref metadata
        catalog_name = ""
        for candidate in ([ref_name] + [str(t) for t in ref_targets]):
            if candidate:
                # Strip "Catalog." / "Document." prefix
                catalog_name = candidate.split(".")[-1].strip().lower()
                break

        if not catalog_name:
            return

        rows: list[dict] = []
        for prefix in ("data_catalog_", "data_document_"):
            try:
                all_rows = self._db.table(f"{prefix}{catalog_name}").select() or []
                rows = [r for r in all_rows if not r.get("_deleted")]
                if rows:
                    break
            except Exception:
                continue

        from .ref_picker_dialog import RefPickerDialog
        dlg = RefPickerDialog(title=catalog_name.capitalize(), rows=rows, parent=self)
        if dlg.exec() != RefPickerDialog.DialogCode.Accepted or not dlg.selected_row:
            return

        title = dlg.selected_title
        guid = dlg.selected_guid

        # Update the visible input widget
        w = self._bound_inputs.get(binding)
        if w is not None:
            self._set_val(w, title)

        # Update record
        key = self._record_key_for_binding(binding)
        self._record[key] = title
        if guid:
            self._record[f"{key}_guid"] = guid
        self.data_changed.emit()


    def _on_ref_open(self, binding: str) -> None:
        """Compatibility alias for extensions that used the old picker name."""
        self._on_ref_choose(binding)


    def _on_ref_open_current(self, binding: str) -> None:
        """Open the selected reference, or choose one when the field is empty."""
        meta = self._binding_schema_meta(binding)
        ref_name = str(meta.get("ref_name") or "").strip()
        if not ref_name:
            targets = meta.get("ref_targets") if isinstance(meta.get("ref_targets"), list) else []
            ref_name = str(targets[0] if targets else "").strip()
        key = self._record_key_for_binding(binding)
        record_guid = str(self._record.get(f"{key}_guid") or "").strip()
        if not record_guid:
            self._on_ref_choose(binding)
            return
        self.reference_open_requested.emit(ref_name, record_guid)


    def _rebuild(self) -> None:
        while self._host_l.count():
            item = self._host_l.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._bound_inputs.clear()
        self._list_table = None
        self._list_col_bindings = []
        self._tp_tables.clear()
        self._tp_col_bindings.clear()

        # Корневий контейнер будуємо без chrome (groupbox/frame)
        self._is_root_build = True
        w = self._build_node(self._model.root)
        self._is_root_build = False
        try:
            w.setProperty("mp_form_surface_root", True)
            w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        except Exception:
            pass

        # Banner for non-embedded object forms
        if (self._ctx.form_kind == "object_form"
                and self._ctx.obj_title
                and not self._embedded):
            banner = QLabel(self._ctx.obj_title)
            banner.setStyleSheet(
                "font-size: 13pt; font-weight: 700; color: #1A2744;"
                "padding: 16px 20px 8px 20px; background: transparent;"
            )
            self._host_l.addWidget(banner)

        self.setStyleSheet(self._form_surface_stylesheet())
        self._host_l.addWidget(w, 1)
        self._host_l.addStretch(1)

        self._record_to_ui()
        # Auto-focus the first editable input for object forms
        if self._ctx.form_kind == "object_form" and self._bound_inputs:
            first_w = next(iter(self._bound_inputs.values()), None)
            if first_w is not None:
                from PySide6.QtCore import QTimer as _QTimer
                _QTimer.singleShot(50, first_w.setFocus)


    def _record_to_ui(self) -> None:
        for name, w in self._bound_inputs.items():
            self._set_val(w, self._record_value_for_binding(self._record, name))


    def _ui_to_record(self) -> None:
        for name, w in self._bound_inputs.items():
            value = self._get_val(w)
            previous = self._record_value_for_binding(self._record, name)
            if isinstance(w, QDateEdit) and value and isinstance(previous, str):
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?", previous):
                    value += previous[10:]
            self._record[self._record_key_for_binding(name)] = value


    def attach_module_runner(self, runner: Any) -> None:
        """Attach a form module runner and fire OnOpen."""
        self._module_runner = runner
        if not runner.is_loaded:
            if runner.has_errors:
                import logging
                logging.getLogger("client.form_module").warning(
                    "Form module not loaded due to errors: %s", runner.errors)
            return
        for name in ("OnOpen", "ПриВідкритті", "ПриОткрытии", "OnFormOpen"):
            found, _ = runner.call_handler(name)
            if found:
                break
        self._record_to_ui()


    def _on_field_changed(self, *_args: Any) -> None:
        old_record = dict(self._record)
        self._ui_to_record()
        self.data_changed.emit()
        runner = self._module_runner
        if runner is None or not runner.is_loaded:
            return
        for key, new_val in self._record.items():
            if new_val != old_record.get(key):
                field = key.lstrip("_")
                for prefix in ("OnChange_", "ПриЗміні_", "ПриИзменении_"):
                    found, _ = runner.call_handler(f"{prefix}{field}")
                    if found:
                        self._record_to_ui()
                        break


    def _emit_command_raw(self, code: str) -> None:
        """Emit command bypassing module hooks (used by FormContext)."""
        c = str(code or "").strip()
        if not c:
            return
        self.command.emit(c)
        if self._on_command:
            self._on_command(c)


    def _emit_command(self, code: str) -> None:
        c = str(code or "").strip()
        if not c:
            return

        c_lower = c.lower()
        # Base command name for prefix-based commands like "tp_add:binding"
        c_base = c_lower.split(":")[0]

        # Sync UI → record before write-related commands
        if c_base in ("save", "form.save", "saveandclose", "save_close", "post", "form.post", "write"):
            self._ui_to_record()

        # Handle TP commands inside the form widget (add/delete rows)
        if c_base in ("tp_add", "tp_delete", "tp_up", "tp_down"):
            binding = c.split(":", 1)[1] if ":" in c else ""
            self._handle_tp_command(c_base, binding)
            return

        runner = self._module_runner

        # BeforeWrite hook
        if runner is not None and runner.is_loaded and c_base in (
            "save", "form.save", "saveandclose", "save_close", "form.saveandclose", "write"
        ):
            for name in ("BeforeWrite", "ПередЗаписом", "ПередЗаписью"):
                found, _ = runner.call_handler(name)
                if found:
                    break

        # Custom (non-builtin) commands: try module procedure first
        if runner is not None and runner.is_loaded and c_base not in _BUILTIN_COMMANDS:
            for proc in (c, c.replace(".", "_"), c.replace(" ", "_")):
                found, _ = runner.call_handler(proc)
                if found:
                    self._record_to_ui()
                    return

        self.command.emit(c)
        if self._on_command:
            self._on_command(c)


    def _handle_tp_command(self, action: str, binding: str) -> None:
        """Handle tabular-part add/delete/move inside the form widget."""
        from PySide6.QtGui import QStandardItem
        tv = self._tp_tables.get(binding)
        if tv is None:
            return
        m = tv.model()
        if m is None:
            return

        if action == "tp_add":
            col_count = m.columnCount()
            row = [QStandardItem("") for _ in range(col_count)]
            m.appendRow(row)
            new_idx = m.index(m.rowCount() - 1, 0)
            tv.setCurrentIndex(new_idx)
            tv.scrollToBottom()

        elif action == "tp_delete":
            idx = tv.currentIndex()
            if idx.isValid():
                m.removeRow(idx.row())

        elif action == "tp_up":
            idx = tv.currentIndex()
            row = idx.row()
            if row > 0:
                items = m.takeRow(row)
                m.insertRow(row - 1, items)
                tv.setCurrentIndex(m.index(row - 1, idx.column()))

        elif action == "tp_down":
            idx = tv.currentIndex()
            row = idx.row()
            if row < m.rowCount() - 1:
                items = m.takeRow(row)
                m.insertRow(row + 1, items)
                tv.setCurrentIndex(m.index(row + 1, idx.column()))


    def _default_record_values(self) -> Dict[str, Any]:
        """Default field values for a brand-new record."""
        import datetime
        today = datetime.date.today().isoformat()
        obj_type = self._ctx.obj_type.lower()
        defaults: Dict[str, Any] = {"_deleted": False}
        if obj_type in ("document", "business_process", "task"):
            defaults["_date"]   = today
            defaults["_posted"] = False
        elif obj_type == "catalog":
            defaults["_predefined"] = False
            defaults["_is_folder"]  = False
        return defaults


    def _load_record(self, rec_guid: str) -> Dict[str, Any]:
        ctx = self._ctx
        if not ctx.obj_name or not rec_guid or not self._db:
            return {}
        try:
            rows = self._db.table(_data_table(ctx.obj_type, ctx.obj_name)).select(
                where={"_guid": rec_guid}) or []
            return dict(rows[0]) if rows else {}
        except Exception:
            return {}
