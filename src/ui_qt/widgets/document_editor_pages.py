from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.ui_qt.i18n import get_lang, t

from .document_editor_payload import (
    _localized_enum_label,
    _merge_named_items,
    _merge_tabular_parts,
)
from .schema_editors import AttributesEditorWidget, TabularPartsEditorWidget
from .catalog_editor_pages import _SubsystemsPageMixin


class DocumentEditorPagesMixin(_SubsystemsPageMixin):
    def _add_enum_items(self, combo: QComboBox, group: str, values: tuple[str, ...] | list[str]) -> None:
        for value in values:
            combo.addItem(_localized_enum_label(group, value), value)

    def _build_main_page(self) -> QWidget:
        w = QWidget()
        page = QGridLayout(w)
        page.setContentsMargins(10, 10, 10, 10)
        page.setHorizontalSpacing(12)
        page.setVerticalSpacing(10)
        page.setColumnStretch(1, 1)

        self.ed_name = QLineEdit()
        self.ed_synonym = QLineEdit()
        self.ed_comment = QLineEdit()
        self.ed_object_presentation = QLineEdit()
        self.ed_object_presentation_ext = QLineEdit()
        self.ed_list_presentation = QLineEdit()
        self.ed_list_presentation_ext = QLineEdit()

        for ed in (
            self.ed_name,
            self.ed_synonym,
            self.ed_comment,
            self.ed_object_presentation,
            self.ed_object_presentation_ext,
            self.ed_list_presentation,
            self.ed_list_presentation_ext,
        ):
            ed.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        lbl_name = QLabel(t("catalog_field_name"))
        lbl_syn = QLabel(t("catalog_field_synonym"))
        lbl_comment = QLabel(t("catalog_field_comment"))
        lbl_obj = QLabel(t("prop_object_presentation"))
        lbl_obj_ext = QLabel(t("prop_object_presentation_ext"))
        lbl_list = QLabel(t("prop_list_presentation"))
        lbl_list_ext = QLabel(t("prop_list_presentation_ext"))
        lbl_explanation = QLabel(t("prop_explanation"))
        for lbl in (lbl_name, lbl_syn, lbl_comment, lbl_obj, lbl_obj_ext, lbl_list, lbl_list_ext):
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl_explanation.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)

        self.ed_explanation = QPlainTextEdit()
        self.ed_explanation.setPlaceholderText(t("catalog_hint_placeholder"))
        self.ed_explanation.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.ed_explanation.setMinimumHeight(140)

        r = 0
        page.addWidget(lbl_name, r, 0)
        page.addWidget(self.ed_name, r, 1)
        r += 1

        page.addWidget(lbl_syn, r, 0)
        page.addWidget(self.ed_synonym, r, 1)
        r += 1

        page.addWidget(lbl_comment, r, 0)
        page.addWidget(self.ed_comment, r, 1)
        r += 1

        for lbl, ed in (
            (lbl_obj, self.ed_object_presentation),
            (lbl_obj_ext, self.ed_object_presentation_ext),
            (lbl_list, self.ed_list_presentation),
            (lbl_list_ext, self.ed_list_presentation_ext),
        ):
            page.addWidget(lbl, r, 0)
            page.addWidget(ed, r, 1)
            r += 1

        page.addWidget(lbl_explanation, r, 0)
        page.addWidget(self.ed_explanation, r, 1)
        page.setRowStretch(r, 1)

        for ed, key in (
            (self.ed_name, "name"),
            (self.ed_synonym, "synonym"),
            (self.ed_comment, "comment"),
            (self.ed_object_presentation, "object_presentation"),
            (self.ed_object_presentation_ext, "extended_object_presentation"),
            (self.ed_list_presentation, "list_presentation"),
            (self.ed_list_presentation_ext, "extended_list_presentation"),
        ):
            ed.textEdited.connect(
                lambda _txt, k=key, e=ed: self._shell.set_pending_patch({k: e.text()})
            )

        self.ed_explanation.textChanged.connect(
            lambda: self._shell.set_pending_patch(
                {"explanation": self.ed_explanation.toPlainText()}
            )
        )

        return w

    def _build_attributes_page(self) -> QWidget:
        widget = AttributesEditorWidget(initial=self._model.requisites)
        widget.patchChanged.connect(
            lambda patch: self._shell.set_pending_patch(
                {"requisites": _merge_named_items(self._model.requisites, patch.get("attributes"))}
            )
        )
        return widget

    def _build_tabular_parts_page(self) -> QWidget:
        widget = TabularPartsEditorWidget(initial=self._model.tabular_parts)
        widget.patchChanged.connect(
            lambda patch: self._shell.set_pending_patch(
                {
                    "tabular_parts": _merge_tabular_parts(
                        self._model.tabular_parts,
                        patch.get("tabular_parts"),
                    )
                }
            )
        )
        return widget

    def _build_data_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        hint = QLabel(t("doc.data_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("metaHint")
        layout.addWidget(hint)

        req_group = QGroupBox(t("tree.attributes"))
        req_layout = QVBoxLayout(req_group)
        req_bar = QHBoxLayout()
        req_bar.setSpacing(8)
        self.btn_req_add = QPushButton(t("schema.action.add_requisite"))
        self.btn_req_delete = QPushButton(t("schema.action.delete"))
        req_bar.addWidget(self.btn_req_add)
        req_bar.addWidget(self.btn_req_delete)
        req_bar.addStretch(1)
        req_layout.addLayout(req_bar)
        self.tree_requisites = QTreeWidget()
        self.tree_requisites.setHeaderHidden(True)
        self.tree_requisites.setIndentation(16)
        self.tree_requisites.setUniformRowHeights(True)
        req_layout.addWidget(self.tree_requisites, 1)

        tp_group = QGroupBox(t("tree.tabularParts"))
        tp_layout = QVBoxLayout(tp_group)
        tp_bar = QHBoxLayout()
        tp_bar.setSpacing(8)
        self.btn_tp_add = QPushButton(t("schema.action.add_table"))
        self.btn_tp_add_column = QPushButton(t("schema.action.add_table_requisite"))
        self.btn_tp_delete = QPushButton(t("schema.action.delete"))
        tp_bar.addWidget(self.btn_tp_add)
        tp_bar.addWidget(self.btn_tp_add_column)
        tp_bar.addWidget(self.btn_tp_delete)
        tp_bar.addStretch(1)
        tp_layout.addLayout(tp_bar)
        self.tree_tabular_parts = QTreeWidget()
        self.tree_tabular_parts.setHeaderHidden(True)
        self.tree_tabular_parts.setIndentation(16)
        self.tree_tabular_parts.setUniformRowHeights(True)
        tp_layout.addWidget(self.tree_tabular_parts, 1)

        layout.addWidget(req_group, 1)
        layout.addWidget(tp_group, 1)

        self.tree_requisites.currentItemChanged.connect(self._on_requisite_selected)
        self.tree_tabular_parts.currentItemChanged.connect(self._on_tabular_part_selected)
        self.btn_req_add.clicked.connect(self._on_add_requisite)
        self.btn_req_delete.clicked.connect(self._on_delete_selected_requisite)
        self.btn_tp_add.clicked.connect(self._on_add_tabular_part)
        self.btn_tp_add_column.clicked.connect(self._on_add_tabular_part_column)
        self.btn_tp_delete.clicked.connect(self._on_delete_selected_tabular_item)
        return w

    def _build_functional_options_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        hint = QLabel(t("doc.functional_options_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("metaHint")
        layout.addWidget(hint)

        self.lst_functional_options = QListWidget()
        layout.addWidget(self.lst_functional_options, 1)
        return w

    def _build_numbering_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        grp = QGroupBox(t("doc_group_numbering"))
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(12)

        self.chk_autonumbering = QCheckBox()
        self.ed_numerator = QLineEdit()
        self.sp_number_length = QSpinBox()
        self.sp_number_length.setRange(1, 128)
        self.chk_check_unique = QCheckBox()
        self.cb_number_type = QComboBox()
        self._add_enum_items(self.cb_number_type, "number_type", ("string", "number"))
        self.cb_number_periodicity = QComboBox()
        self._add_enum_items(
            self.cb_number_periodicity,
            "number_periodicity",
            ("year", "quarter", "month", "day", "none"),
        )

        form.addRow(t("prop_autonumber"), self.chk_autonumbering)
        form.addRow(t("prop_numerator"), self.ed_numerator)
        form.addRow(t("prop_number_len"), self.sp_number_length)
        form.addRow(t("prop_check_unique"), self.chk_check_unique)
        form.addRow(t("prop_number_type"), self.cb_number_type)
        form.addRow(t("prop_number_period"), self.cb_number_periodicity)

        layout.addWidget(grp)
        layout.addStretch(1)

        self.chk_autonumbering.stateChanged.connect(
            lambda _s: self._on_value_changed("autonumbering", self.chk_autonumbering.isChecked())
        )
        self.ed_numerator.textEdited.connect(lambda text: self._on_text_changed("numerator", text))
        self.sp_number_length.valueChanged.connect(
            lambda v: self._on_value_changed("number_length", int(v))
        )
        self.chk_check_unique.stateChanged.connect(
            lambda _s: self._on_value_changed("check_unique", self.chk_check_unique.isChecked())
        )
        self.cb_number_type.currentIndexChanged.connect(
            lambda _i: self._on_value_changed(
                "number_type",
                str(self.cb_number_type.currentData() or "string"),
            )
        )
        self.cb_number_periodicity.currentIndexChanged.connect(
            lambda _i: self._on_value_changed(
                "number_periodicity",
                str(self.cb_number_periodicity.currentData() or "year"),
            )
        )
        return w

    def _build_movements_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        top = QGroupBox(t("doc_group_movements"))
        form = QFormLayout(top)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(12)

        self.cb_posting = QComboBox()
        self.cb_real_time_posting = QComboBox()
        for combo in (self.cb_posting, self.cb_real_time_posting):
            self._add_enum_items(combo, "posting", ("allow", "forbid", "not_supported"))
        self.cb_register_records_deletion = QComboBox()
        self._add_enum_items(
            self.cb_register_records_deletion,
            "register_records_deletion",
            ("auto_delete_off", "auto_delete_on"),
        )
        self.cb_register_records_writing = QComboBox()
        self._add_enum_items(
            self.cb_register_records_writing,
            "register_records_writing",
            ("write_selected", "write_all"),
        )

        form.addRow(t("prop_posting"), self.cb_posting)
        form.addRow(t("prop_real_time_posting"), self.cb_real_time_posting)
        form.addRow(t("prop_register_records_deletion"), self.cb_register_records_deletion)
        form.addRow(t("prop_register_records_writing"), self.cb_register_records_writing)

        regs = QGroupBox(t("doc_group_register_records"))
        regs_layout = QVBoxLayout(regs)
        self.ed_register_search = QLineEdit()
        self.ed_register_search.setPlaceholderText(t("doc_register_search"))
        regs_layout.addWidget(self.ed_register_search)
        self.tree_register_records = QTreeWidget()
        self.tree_register_records.setObjectName("treeRegisterRecords")
        self.tree_register_records.setHeaderHidden(True)
        self.tree_register_records.setIndentation(16)
        self.tree_register_records.setUniformRowHeights(True)
        regs_layout.addWidget(self.tree_register_records, 1)

        movement_box = QGroupBox(t("doc_group_movements_preview"))
        movement_layout = QVBoxLayout(movement_box)
        self.table_movements = QTableWidget(0, 2)
        self.table_movements.setHorizontalHeaderLabels(
            [t("doc_register_name"), t("doc_movement_action")]
        )
        self.table_movements.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_movements.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_movements.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table_movements.horizontalHeader().setStretchLastSection(False)
        self.table_movements.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_movements.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        movement_layout.addWidget(self.table_movements, 1)
        constructor_bar = QHBoxLayout()
        self.btn_remove_movement = QPushButton(t("doc.action.remove"))
        constructor_bar.addWidget(self.btn_remove_movement)
        constructor_bar.addStretch(1)
        self.cb_posting_language = QComboBox()
        self.cb_posting_language.addItem("UK", "uk")
        self.cb_posting_language.addItem("EN", "en")
        self.cb_posting_language.setCurrentIndex(1 if get_lang() == "en" else 0)
        constructor_bar.addWidget(self.cb_posting_language)
        self.btn_configure_posting = QPushButton(t("posting_map_title"))
        constructor_bar.addWidget(self.btn_configure_posting)
        self.btn_generate_posting = QPushButton(t("doc_generate_posting"))
        constructor_bar.addWidget(self.btn_generate_posting)
        self.btn_insert_posting = QPushButton(t("doc_insert_posting"))
        constructor_bar.addWidget(self.btn_insert_posting)
        movement_layout.addLayout(constructor_bar)
        from .code_editor_widget import create_metascript_code_edit

        self.ed_posting_handler, self._posting_highlighter = create_metascript_code_edit()
        self.ed_posting_handler.setObjectName("postingHandlerEditor")
        self.ed_posting_handler.setPlaceholderText(t("doc_posting_handler_placeholder"))
        movement_layout.addWidget(self.ed_posting_handler, 1)
        hint = QLabel(t("doc_posting_starter_hint"))
        hint.setWordWrap(True)
        movement_layout.addWidget(hint)

        layout.addWidget(top)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(regs)
        splitter.addWidget(movement_box)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

        self.cb_posting.currentIndexChanged.connect(
            lambda _i: self._on_value_changed("posting", str(self.cb_posting.currentData() or "allow"))
        )
        self.cb_real_time_posting.currentIndexChanged.connect(
            lambda _i: self._on_value_changed(
                "real_time_posting",
                str(self.cb_real_time_posting.currentData() or "allow"),
            )
        )
        self.cb_register_records_deletion.currentIndexChanged.connect(
            lambda _i: self._on_value_changed(
                "register_records_deletion",
                str(self.cb_register_records_deletion.currentData() or "auto_delete_off"),
            )
        )
        self.cb_register_records_writing.currentIndexChanged.connect(
            lambda _i: self._on_value_changed(
                "register_records_writing_on_post",
                str(self.cb_register_records_writing.currentData() or "write_selected"),
            )
        )
        self.tree_register_records.itemChanged.connect(self._on_register_record_item_changed)
        self.ed_register_search.textChanged.connect(self._filter_registers)
        self.btn_generate_posting.clicked.connect(self._generate_posting_handler)
        self.btn_configure_posting.clicked.connect(self._configure_posting_mappings)
        self.btn_remove_movement.clicked.connect(self._remove_selected_movements)
        self.table_movements.itemSelectionChanged.connect(self._update_posting_buttons)
        self.btn_insert_posting.clicked.connect(self._insert_posting_handler)
        self.ed_posting_handler.textChanged.connect(self._on_posting_text_changed)
        return w

    def _build_sequences_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        form = QFormLayout()
        self.cb_sequence_filling = QComboBox()
        self._add_enum_items(
            self.cb_sequence_filling,
            "sequence_filling",
            ("auto_fill_off", "auto_fill_on"),
        )
        form.addRow(t("prop_sequence_filling"), self.cb_sequence_filling)
        layout.addLayout(form)

        hint = QLabel(t("doc.sequences_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("metaHint")
        layout.addWidget(hint)

        self.lst_sequences = QListWidget()
        self.lst_sequences.itemChanged.connect(self._on_sequence_item_changed)
        layout.addWidget(self.lst_sequences, 1)
        self.cb_sequence_filling.currentIndexChanged.connect(
            lambda _i: self._on_value_changed(
                "sequence_filling",
                str(self.cb_sequence_filling.currentData() or "auto_fill_off"),
            )
        )
        return w

    def _build_journals_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        hint = QLabel(t("doc.journals_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("metaHint")
        layout.addWidget(hint)

        self.lst_journals = QListWidget()
        self.lst_journals.itemChanged.connect(self._on_journal_item_changed)
        layout.addWidget(self.lst_journals, 1)
        return w

    def _build_input_by_string_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        form = QFormLayout()
        self.cb_create_on_input = QComboBox()
        self._add_enum_items(self.cb_create_on_input, "toggle_mode", ("use", "dont_use", "auto"))
        field_row = QWidget()
        field_row_layout = QHBoxLayout(field_row)
        field_row_layout.setContentsMargins(0, 0, 0, 0)
        field_row_layout.setSpacing(6)
        self.ed_input_by_string_field = QLineEdit()
        self.btn_input_by_string_pick = QPushButton("...")
        self.btn_input_by_string_pick.setFixedWidth(34)
        self.btn_input_by_string_clear = QPushButton("×")
        self.btn_input_by_string_clear.setFixedWidth(34)
        field_row_layout.addWidget(self.ed_input_by_string_field, 1)
        field_row_layout.addWidget(self.btn_input_by_string_pick)
        field_row_layout.addWidget(self.btn_input_by_string_clear)
        self.cb_search_string_mode = QComboBox()
        self._add_enum_items(self.cb_search_string_mode, "search_string_mode", ("begin", "any_part"))
        self.cb_full_text_search_on_input = QComboBox()
        self._add_enum_items(self.cb_full_text_search_on_input, "toggle_mode", ("use", "dont_use", "auto"))
        self.cb_choice_data_get_mode = QComboBox()
        self._add_enum_items(self.cb_choice_data_get_mode, "choice_data_get_mode", ("directly", "on_demand"))
        self.cb_choice_history_on_input = QComboBox()
        self._add_enum_items(self.cb_choice_history_on_input, "toggle_mode", ("use", "dont_use", "auto"))

        form.addRow(t("prop_create_on_input"), self.cb_create_on_input)
        form.addRow(t("prop_input_by_string_field"), field_row)
        form.addRow(t("prop_search_string_mode_on_input"), self.cb_search_string_mode)
        form.addRow(t("prop_full_text_search_on_input"), self.cb_full_text_search_on_input)
        form.addRow(t("prop_choice_data_get_mode"), self.cb_choice_data_get_mode)
        form.addRow(t("prop_choice_history_on_input"), self.cb_choice_history_on_input)
        layout.addLayout(form)
        layout.addStretch(1)

        self.cb_create_on_input.currentIndexChanged.connect(
            lambda _i: self._on_value_changed(
                "create_on_input",
                str(self.cb_create_on_input.currentData() or "use"),
            )
        )
        self.ed_input_by_string_field.textEdited.connect(
            lambda text: self._on_text_changed("input_by_string_field", text)
        )
        self.btn_input_by_string_pick.clicked.connect(self._on_pick_input_by_string_field)
        self.btn_input_by_string_clear.clicked.connect(self._on_clear_input_by_string_field)
        self.cb_search_string_mode.currentIndexChanged.connect(
            lambda _i: self._on_value_changed(
                "search_string_mode_on_input_by_string",
                str(self.cb_search_string_mode.currentData() or "begin"),
            )
        )
        self.cb_full_text_search_on_input.currentIndexChanged.connect(
            lambda _i: self._on_value_changed(
                "full_text_search_on_input_by_string",
                str(self.cb_full_text_search_on_input.currentData() or "dont_use"),
            )
        )
        self.cb_choice_data_get_mode.currentIndexChanged.connect(
            lambda _i: self._on_value_changed(
                "choice_data_get_mode_on_input_by_string",
                str(self.cb_choice_data_get_mode.currentData() or "directly"),
            )
        )
        self.cb_choice_history_on_input.currentIndexChanged.connect(
            lambda _i: self._on_value_changed(
                "choice_history_on_input",
                str(self.cb_choice_history_on_input.currentData() or "dont_use"),
            )
        )
        return w

    def _build_based_on_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        grp_in = QGroupBox(t("doc_group_based_on"))
        in_layout = QVBoxLayout(grp_in)
        in_bar = QHBoxLayout()
        in_bar.setSpacing(8)
        self.btn_based_on_add = QPushButton(t("doc.action.add"))
        self.btn_based_on_remove = QPushButton(t("doc.action.remove"))
        in_bar.addWidget(self.btn_based_on_add)
        in_bar.addWidget(self.btn_based_on_remove)
        in_bar.addStretch(1)
        in_layout.addLayout(in_bar)
        self.lst_based_on = QListWidget()
        in_layout.addWidget(self.lst_based_on)

        grp_out = QGroupBox(t("doc_group_based_for"))
        out_layout = QVBoxLayout(grp_out)
        self.lst_based_for = QListWidget()
        out_layout.addWidget(self.lst_based_for)

        layout.addWidget(grp_in, 1)
        layout.addWidget(grp_out, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.btn_based_on_constructor = QPushButton(t("doc.based_on_constructor"))
        bottom.addWidget(self.btn_based_on_constructor)
        layout.addLayout(bottom)

        self.btn_based_on_add.clicked.connect(self._on_add_based_on)
        self.btn_based_on_remove.clicked.connect(self._on_remove_based_on)
        self.btn_based_on_constructor.clicked.connect(self._on_open_based_on_constructor)
        self.lst_based_on.currentItemChanged.connect(lambda *_args: self._update_based_on_buttons())
        self._update_based_on_buttons()
        return w

    def _build_rights_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        hint = QLabel(t("doc.rights_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("metaHint")
        layout.addWidget(hint)

        body = QHBoxLayout()
        grp_roles = QGroupBox(t("doc_group_roles"))
        roles_layout = QVBoxLayout(grp_roles)
        self.lst_roles = QListWidget()
        roles_layout.addWidget(self.lst_roles, 1)

        grp_role_rights = QGroupBox(t("doc_group_role_rights"))
        role_rights_layout = QVBoxLayout(grp_role_rights)
        self.lst_role_rights = QListWidget()
        role_rights_layout.addWidget(self.lst_role_rights, 1)
        self.lbl_role_rights_info = QLabel("")
        self.lbl_role_rights_info.setWordWrap(True)
        self.lbl_role_rights_info.setObjectName("metaHint")
        role_rights_layout.addWidget(self.lbl_role_rights_info)

        body.addWidget(grp_roles, 1)
        body.addWidget(grp_role_rights, 1)
        layout.addLayout(body, 1)

        grp_restrictions = QGroupBox(t("doc_group_access_restrictions"))
        restrictions_layout = QVBoxLayout(grp_restrictions)
        self.tree_role_restrictions = QTreeWidget()
        self.tree_role_restrictions.setRootIsDecorated(False)
        self.tree_role_restrictions.setUniformRowHeights(True)
        self.tree_role_restrictions.setColumnCount(2)
        self.tree_role_restrictions.setHeaderLabels(
            [t("doc.restrictions_field_column"), t("doc.restrictions_rule_column")]
        )
        restrictions_layout.addWidget(self.tree_role_restrictions, 1)
        layout.addWidget(grp_restrictions, 1)

        self.chk_post_privileged = QCheckBox(t("prop_post_in_privileged_mode"))
        self.chk_unpost_privileged = QCheckBox(t("prop_unpost_in_privileged_mode"))
        layout.addWidget(self.chk_post_privileged)
        layout.addWidget(self.chk_unpost_privileged)

        self.lst_roles.currentItemChanged.connect(lambda *_args: self._reload_role_rights_view())
        self.chk_post_privileged.stateChanged.connect(
            lambda _s: self._on_value_changed(
                "post_in_privileged_mode",
                self.chk_post_privileged.isChecked(),
            )
        )
        self.chk_unpost_privileged.stateChanged.connect(
            lambda _s: self._on_value_changed(
                "unpost_in_privileged_mode",
                self.chk_unpost_privileged.isChecked(),
            )
        )
        return w

    def _build_exchange_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        hint = QLabel(t("doc.exchange_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("metaHint")
        layout.addWidget(hint)

        self.tree_exchange_plans = QTreeWidget()
        self.tree_exchange_plans.setRootIsDecorated(False)
        self.tree_exchange_plans.setUniformRowHeights(True)
        self.tree_exchange_plans.setAlternatingRowColors(False)
        self.tree_exchange_plans.setColumnCount(2)
        self.tree_exchange_plans.setHeaderLabels(
            [t("doc.exchange_plan_column"), t("doc.exchange_auto_record_column")]
        )
        layout.addWidget(self.tree_exchange_plans, 1)
        self.tree_exchange_plans.itemChanged.connect(self._on_exchange_plan_item_changed)
        return w

    def _build_other_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        form = QFormLayout()
        self.cb_full_text_search = QComboBox()
        self.cb_data_history = QComboBox()
        for combo in (self.cb_full_text_search, self.cb_data_history):
            self._add_enum_items(combo, "toggle_mode", ("use", "dont_use", "auto"))
        self.chk_update_data_history = QCheckBox()
        self.chk_execute_after_write_history = QCheckBox()
        self.chk_include_help_in_contents = QCheckBox()
        data_lock_row = QWidget()
        data_lock_layout = QHBoxLayout(data_lock_row)
        data_lock_layout.setContentsMargins(0, 0, 0, 0)
        data_lock_layout.setSpacing(6)
        self.ed_data_lock_fields = QLineEdit()
        self.btn_data_lock_fields_pick = QPushButton("...")
        self.btn_data_lock_fields_pick.setFixedWidth(34)
        self.btn_data_lock_fields_clear = QPushButton("×")
        self.btn_data_lock_fields_clear.setFixedWidth(34)
        data_lock_layout.addWidget(self.ed_data_lock_fields, 1)
        data_lock_layout.addWidget(self.btn_data_lock_fields_pick)
        data_lock_layout.addWidget(self.btn_data_lock_fields_clear)
        self.cb_data_lock_control_mode = QComboBox()
        self._add_enum_items(
            self.cb_data_lock_control_mode,
            "data_lock_control_mode",
            ("automatic", "managed"),
        )

        form.addRow(t("prop_full_text_search"), self.cb_full_text_search)
        form.addRow(t("prop_data_history"), self.cb_data_history)
        form.addRow(t("prop_update_data_history"), self.chk_update_data_history)
        form.addRow(t("prop_execute_after_write_history"), self.chk_execute_after_write_history)
        form.addRow(t("prop_include_help"), self.chk_include_help_in_contents)
        form.addRow(t("prop_data_lock_fields"), data_lock_row)
        form.addRow(t("prop_data_lock_control_mode"), self.cb_data_lock_control_mode)
        layout.addLayout(form)

        hint = QLabel(t("doc.other_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("metaHint")
        layout.addWidget(hint)
        layout.addStretch(1)

        self.cb_full_text_search.currentIndexChanged.connect(
            lambda _i: self._on_value_changed(
                "full_text_search",
                str(self.cb_full_text_search.currentData() or "dont_use"),
            )
        )
        self.cb_data_history.currentIndexChanged.connect(
            lambda _i: self._on_value_changed(
                "data_history",
                str(self.cb_data_history.currentData() or "dont_use"),
            )
        )
        self.chk_update_data_history.stateChanged.connect(
            lambda _s: self._on_value_changed(
                "update_data_history_immediately_after_write",
                self.chk_update_data_history.isChecked(),
            )
        )
        self.chk_execute_after_write_history.stateChanged.connect(
            lambda _s: self._on_value_changed(
                "execute_after_write_data_history_version_processing",
                self.chk_execute_after_write_history.isChecked(),
            )
        )
        self.chk_include_help_in_contents.stateChanged.connect(
            lambda _s: self._on_value_changed(
                "include_help_in_contents",
                self.chk_include_help_in_contents.isChecked(),
            )
        )
        self.ed_data_lock_fields.textEdited.connect(
            lambda text: self._on_text_changed("data_lock_fields", text)
        )
        self.btn_data_lock_fields_pick.clicked.connect(self._on_pick_data_lock_fields)
        self.btn_data_lock_fields_clear.clicked.connect(self._on_clear_data_lock_fields)
        self.cb_data_lock_control_mode.currentIndexChanged.connect(
            lambda _i: self._on_value_changed(
                "data_lock_control_mode",
                str(self.cb_data_lock_control_mode.currentData() or "automatic"),
            )
        )
        return w

    def _build_forms_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        form_defaults = QFormLayout()
        self.ed_default_object_form = QComboBox()
        self.ed_default_object_form.setEditable(False)
        self.ed_default_list_form = QComboBox()
        self.ed_default_list_form.setEditable(False)
        self.ed_default_choice_form = QComboBox()
        self.ed_default_choice_form.setEditable(False)
        form_defaults.addRow(t("prop_default_object_form"), self.ed_default_object_form)
        form_defaults.addRow(t("prop_default_list_form"), self.ed_default_list_form)
        form_defaults.addRow(t("prop_default_choice_form"), self.ed_default_choice_form)
        layout.addLayout(form_defaults)

        hint = QLabel(t("obj.forms_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("metaHint")
        layout.addWidget(hint)

        bar = QHBoxLayout()
        bar.setSpacing(8)

        self.btn_form_new = QPushButton(t("obj.forms_new"))
        self.btn_form_open = QPushButton(t("obj.forms_open"))
        self.btn_form_delete = QPushButton(t("obj.forms_delete"))
        self.btn_form_refresh = QPushButton(t("obj.forms_refresh"))

        bar.addWidget(self.btn_form_new)
        bar.addWidget(self.btn_form_open)
        bar.addWidget(self.btn_form_delete)
        bar.addStretch(1)
        bar.addWidget(self.btn_form_refresh)
        layout.addLayout(bar)

        self.lst_forms = QListWidget()
        self.lst_forms.setObjectName("metaFormsList")
        layout.addWidget(self.lst_forms, 1)

        self.lbl_forms_info = QLabel("")
        self.lbl_forms_info.setWordWrap(True)
        self.lbl_forms_info.setObjectName("metaHint")
        layout.addWidget(self.lbl_forms_info)

        self.btn_form_new.clicked.connect(self._on_create_form)
        self.btn_form_open.clicked.connect(self._on_open_selected_form)
        self.btn_form_delete.clicked.connect(self._on_delete_selected_form)
        self.btn_form_refresh.clicked.connect(self._refresh_forms_list)
        self.lst_forms.itemDoubleClicked.connect(lambda _it: self._on_open_selected_form())
        self.lst_forms.currentItemChanged.connect(lambda *_args: self._update_forms_buttons())
        self.ed_default_object_form.currentIndexChanged.connect(
            lambda _idx: self._on_default_form_changed("default_object_form", self.ed_default_object_form)
        )
        self.ed_default_list_form.currentIndexChanged.connect(
            lambda _idx: self._on_default_form_changed("default_list_form", self.ed_default_list_form)
        )
        self.ed_default_choice_form.currentIndexChanged.connect(
            lambda _idx: self._on_default_form_changed("default_choice_form", self.ed_default_choice_form)
        )

        def _load_once(page: QWidget = w) -> None:
            if bool(getattr(page, "_mp_section_loaded", False)):
                return
            self._refresh_forms_list()

        setattr(w, "_on_section_shown", _load_once)
        return w

    def _build_commands_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.chk_use_standard_commands = QCheckBox(t("prop_use_std_commands"))
        layout.addWidget(self.chk_use_standard_commands)

        hint = QLabel(t("obj.commands_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("metaHint")
        layout.addWidget(hint)

        bar = QHBoxLayout()
        bar.setSpacing(8)

        self.btn_cmd_new = QPushButton(t("obj.commands_new"))
        self.btn_cmd_open = QPushButton(t("obj.commands_open"))
        self.btn_cmd_delete = QPushButton(t("obj.commands_delete"))
        self.btn_cmd_refresh = QPushButton(t("obj.commands_refresh"))

        bar.addWidget(self.btn_cmd_new)
        bar.addWidget(self.btn_cmd_open)
        bar.addWidget(self.btn_cmd_delete)
        bar.addStretch(1)
        bar.addWidget(self.btn_cmd_refresh)
        layout.addLayout(bar)

        self.lst_cmds = QListWidget()
        self.lst_cmds.setObjectName("metaCommandsList")
        layout.addWidget(self.lst_cmds, 1)

        self.lbl_cmds_info = QLabel("")
        self.lbl_cmds_info.setWordWrap(True)
        self.lbl_cmds_info.setObjectName("metaHint")
        layout.addWidget(self.lbl_cmds_info)

        self.btn_cmd_new.clicked.connect(self._on_create_command)
        self.btn_cmd_open.clicked.connect(self._on_open_selected_command)
        self.btn_cmd_delete.clicked.connect(self._on_delete_selected_command)
        self.btn_cmd_refresh.clicked.connect(self._refresh_commands_list)
        self.lst_cmds.itemDoubleClicked.connect(lambda _it: self._on_open_selected_command())
        self.lst_cmds.currentItemChanged.connect(lambda *_args: self._update_commands_buttons())
        self.chk_use_standard_commands.stateChanged.connect(
            lambda _s: self._on_value_changed(
                "use_standard_commands",
                self.chk_use_standard_commands.isChecked(),
            )
        )

        def _load_once(page: QWidget = w) -> None:
            if bool(getattr(page, "_mp_section_loaded", False)):
                return
            self._refresh_commands_list()

        setattr(w, "_on_section_shown", _load_once)
        return w

    def _build_layouts_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        hint = QLabel(t("obj.layouts_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("metaHint")
        layout.addWidget(hint)

        bar = QHBoxLayout()
        bar.setSpacing(8)

        self.btn_layout_new = QPushButton(t("obj.layouts_new"))
        self.btn_layout_open = QPushButton(t("obj.layouts_open"))
        self.btn_layout_delete = QPushButton(t("obj.layouts_delete"))
        self.btn_layout_refresh = QPushButton(t("obj.layouts_refresh"))

        bar.addWidget(self.btn_layout_new)
        bar.addWidget(self.btn_layout_open)
        bar.addWidget(self.btn_layout_delete)
        bar.addStretch(1)
        bar.addWidget(self.btn_layout_refresh)
        layout.addLayout(bar)

        self.lst_layouts = QListWidget()
        self.lst_layouts.setObjectName("metaLayoutsList")
        layout.addWidget(self.lst_layouts, 1)

        self.lbl_layouts_info = QLabel("")
        self.lbl_layouts_info.setWordWrap(True)
        self.lbl_layouts_info.setObjectName("metaHint")
        layout.addWidget(self.lbl_layouts_info)

        self.btn_layout_new.clicked.connect(self._on_create_layout)
        self.btn_layout_open.clicked.connect(self._on_open_selected_layout)
        self.btn_layout_delete.clicked.connect(self._on_delete_selected_layout)
        self.btn_layout_refresh.clicked.connect(self._refresh_layouts_list)
        self.lst_layouts.itemDoubleClicked.connect(lambda _it: self._on_open_selected_layout())
        self.lst_layouts.currentItemChanged.connect(lambda *_args: self._update_layouts_buttons())

        def _load_once(page: QWidget = w) -> None:
            if bool(getattr(page, "_mp_section_loaded", False)):
                return
            self._refresh_layouts_list()

        setattr(w, "_on_section_shown", _load_once)
        return w
