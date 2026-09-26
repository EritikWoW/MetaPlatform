from src.dsl.workspace_symbols import (
    WorkspaceDiagnostic,
    WorkspaceSemanticIndex,
    build_workspace_semantic_index,
    filter_form_shadow_diagnostics,
)


def test_workspace_index_accepts_onec_platform_global_api() -> None:
    index = build_workspace_semantic_index(
        [
            {
                "module_guid": "module-runtime-api",
                "owner_guid": "owner-runtime-api",
                "module_kind": "module",
                "source_text": (
                    "Процедура Start()\n"
                    "    ЗаписьЖурналаРегистрации(\"start\");\n"
                    "    ПоказатьОповещениеПользователя(\"ready\");\n"
                    "    ПоместитьВоВременноеХранилище(\"value\");\n"
                    "КонецПроцедуры\n"
                ),
            }
        ],
        owners_by_guid={
            "owner-runtime-api": _owner(
                "owner-runtime-api", "RuntimeApi"
            )
        },
    )

    assert not [
        item
        for item in index.diagnostics
        if item.code == "unresolved_callable"
    ]


def test_workspace_index_resolves_unique_onec_module_split_alias() -> None:
    index = build_workspace_semantic_index(
        [
            {
                "module_guid": "module-implementation",
                "owner_guid": "owner-implementation",
                "source_text": (
                    "Функция CodeLanguage() Экспорт\n"
                    "    Возврат \"uk\";\n"
                    "КонецФункции\n"
                ),
            },
            {
                "module_guid": "module-client",
                "owner_guid": "owner-client",
                "source_text": "Value = LegacyFacade.CodeLanguage();\n",
            },
        ],
        owners_by_guid={
            "owner-implementation": _owner(
                "owner-implementation", "ClientServerImplementation"
            ),
            "owner-client": _owner("owner-client", "Client"),
        },
    )

    assert not [
        item
        for item in index.diagnostics
        if item.code == "unresolved_member"
    ]


def test_workspace_index_uses_explicit_onec_member_aliases() -> None:
    index = build_workspace_semantic_index(
        [
            {
                "module_guid": "module-client-server",
                "owner_guid": "owner-client-server",
                "source_text": (
                    "Процедура СообщитьПользователю(Текст) Экспорт\n"
                    "КонецПроцедуры\n"
                ),
            },
            {
                "module_guid": "module-address",
                "owner_guid": "owner-address",
                "source_text": (
                    "Функция ТипыОбъектовАдресацииАдреса() Экспорт\n"
                    "    Возврат Новый Массив;\n"
                    "КонецФункции\n"
                ),
            },
            {
                "module_guid": "module-caller",
                "owner_guid": "owner-caller",
                "source_text": (
                    "ОбщегоНазначения.СообщитьПользователю(\"ready\");\n"
                    "КонтактнаяИнформацияКлиентСерверПовтИсп."
                    "ТипыОбъектовАдресацииАдресаРФ();\n"
                ),
            },
        ],
        owners_by_guid={
            "owner-client-server": _owner(
                "owner-client-server", "ОбщегоНазначенияКлиентСервер"
            ),
            "owner-address": _owner(
                "owner-address", "КонтактнаяИнформацияКлиентСерверПовтИсп"
            ),
            "owner-caller": _owner("owner-caller", "Caller"),
        },
    )

    assert not [
        item
        for item in index.diagnostics
        if item.code == "unresolved_member"
    ]


def test_workspace_index_marks_missing_external_onec_api_as_source_gap() -> None:
    index = build_workspace_semantic_index(
        [
            {
                "module_guid": "module-caller",
                "owner_guid": "owner-caller",
                "source_text": (
                    "СтандартныеПодсистемыПовтИсп.ЭтоФоновоеЗадание();\n"
                ),
            }
        ],
        owners_by_guid={
            "owner-caller": _owner("owner-caller", "Caller"),
        },
    )

    assert [item.code for item in index.diagnostics] == ["source_gap"]
    assert index.stats()["unresolved_references"] == 0
    assert index.stats()["source_gaps"] == 1


def _owner(guid: str, name: str) -> dict:
    return {
        "guid": guid,
        "type": "common_module",
        "name": name,
        "title": name,
        "payload": {"metadata_ref": f"CommonModule.{name}"},
    }


def test_workspace_index_resolves_exported_api_and_ignores_private_members() -> None:
    index = build_workspace_semantic_index(
        [
            {
                "module_guid": "module-settings",
                "owner_guid": "owner-settings",
                "module_kind": "module",
                "source_text": (
                    "Функція ReadSettings(Name) Експорт\n"
                    "    Повернути Name;\n"
                    "КінецьФункції\n"
                    "Процедура ResetCache()\n"
                    "КінецьПроцедури\n"
                ),
            }
        ],
        owners_by_guid={"owner-settings": _owner("owner-settings", "SettingsServer")},
    )

    resolved = index.resolve("SettingsServer", "ReadSettings")
    assert resolved is not None
    module, symbol = resolved
    assert module.module_guid == "module-settings"
    assert symbol.params == ("Name",)
    assert symbol.line == 1
    assert symbol.col > 0
    assert symbol.symbol_id.startswith("symbol:")
    assert resolved[1].symbol_id == index.resolve("SettingsServer", "ReadSettings")[1].symbol_id
    assert index.resolve("SettingsServer", "ResetCache") is None
    assert [row["name"] for row in index.exported_members("SettingsServer")] == [
        "ReadSettings"
    ]


def test_workspace_index_recovers_exported_declarations_after_corrupt_body() -> None:
    index = build_workspace_semantic_index(
        [
            {
                "module_guid": "module-settings",
                "owner_guid": "owner-settings",
                "module_kind": "module",
                "source_text": (
                    "Procedure BeforeCorruption() Export\n"
                    "EndProcedure\n"
                    "d/*A\\x02PqWB\\x02text\n"
                    "Функция Recovered(\n"
                    "    Знач First,\n"
                    "    Second = Undefined) Экспорт\n"
                    "КонецФункции\n"
                ),
            }
        ],
        owners_by_guid={
            "owner-settings": _owner("owner-settings", "SettingsServer")
        },
    )

    recovered = index.resolve("SettingsServer", "Recovered")

    assert recovered is not None
    assert recovered[1].line == 4
    assert recovered[1].params == ("First", "Second")
    assert sorted(
        row["name"] for row in index.exported_members("SettingsServer")
    ) == ["BeforeCorruption", "Recovered"]


def test_workspace_index_tracks_qualified_references_without_comments_or_strings() -> None:
    index = build_workspace_semantic_index(
        [
            {
                "module_guid": "module-settings",
                "owner_guid": "owner-settings",
                "module_kind": "module",
                "source_text": (
                    "Функція ReadSettings() Експорт\n"
                    "КінецьФункції\n"
                ),
            },
            {
                "module_guid": "module-client",
                "owner_guid": "owner-client",
                "module_kind": "module",
                "source_text": (
                    "// SettingsServer.ReadSettings()\n"
                    'Text = "SettingsServer.ReadSettings()";\n'
                    "Value = SettingsServer.ReadSettings();\n"
                ),
            },
        ],
        owners_by_guid={
            "owner-settings": _owner("owner-settings", "SettingsServer"),
            "owner-client": _owner("owner-client", "ClientModule"),
        },
    )

    hits = index.find_references("SettingsServer", "ReadSettings")

    assert len(hits) == 2
    assert hits[0]["declaration"] is True
    assert hits[0]["target_symbol_id"] == hits[1]["target_symbol_id"]
    assert hits[1]["declaration"] is False
    assert hits[1]["module_guid"] == "module-client"
    assert hits[1]["line"] == 3
    assert "Value = SettingsServer.ReadSettings()" in hits[1]["preview"]


def test_workspace_index_rejects_ambiguous_module_alias() -> None:
    index = build_workspace_semantic_index(
        [
            {
                "module_guid": "module-a",
                "owner_guid": "owner-a",
                "source_text": "Procedure Run() Export\nEndProcedure\n",
            },
            {
                "module_guid": "module-b",
                "owner_guid": "owner-b",
                "source_text": "Procedure Run() Export\nEndProcedure\n",
            },
        ],
        owners_by_guid={
            "owner-a": _owner("owner-a", "Shared"),
            "owner-b": _owner("owner-b", "Shared"),
        },
    )

    assert index.module_for_qualifier("Shared") is None
    assert index.resolve("Shared", "Run") is None
    assert index.stats()["ambiguous_aliases"] == 2


def test_workspace_index_reports_known_unresolved_and_ambiguous_references() -> None:
    index = build_workspace_semantic_index(
        [
            {
                "module_guid": "module-settings",
                "owner_guid": "owner-settings",
                "source_text": "Function ReadSettings() Export\nEndFunction\n",
            },
            {
                "module_guid": "module-shared-a",
                "owner_guid": "owner-shared-a",
                "source_text": "Procedure Run() Export\nEndProcedure\n",
            },
            {
                "module_guid": "module-shared-b",
                "owner_guid": "owner-shared-b",
                "source_text": "Procedure Run() Export\nEndProcedure\n",
            },
            {
                "module_guid": "module-client",
                "owner_guid": "owner-client",
                "source_text": (
                    "// SettingsServer.Missing()\n"
                    'Text = "Shared.Run()";\n'
                    "SettingsServer.Missing();\n"
                    "SettingsServer.ConfigurationValue;\n"
                    "Shared.Run();\n"
                    "UnknownObject.Property;\n"
                ),
            },
        ],
        owners_by_guid={
            "owner-settings": _owner("owner-settings", "SettingsServer"),
            "owner-shared-a": _owner("owner-shared-a", "Shared"),
            "owner-shared-b": _owner("owner-shared-b", "Shared"),
            "owner-client": {
                "guid": "owner-client",
                "type": "configuration",
                "name": "Client",
                "title": "Client",
                "payload": {},
            },
        },
    )

    diagnostics = index.list_diagnostics(module_guid="module-client")

    assert [item["code"] for item in diagnostics] == [
        "unresolved_member",
        "ambiguous_qualifier",
    ]
    assert diagnostics[0]["line"] == 3
    assert diagnostics[0]["qualifier"] == "SettingsServer"
    assert diagnostics[1]["line"] == 5
    assert diagnostics[1]["candidates"] == [
        "module-shared-a",
        "module-shared-b",
    ]
    assert index.stats()["unresolved_references"] == 1
    assert index.stats()["ambiguous_references"] == 1


def test_workspace_index_collects_local_callables_for_every_module_type() -> None:
    index = build_workspace_semantic_index(
        [
            {
                "module_guid": "form-module",
                "owner_guid": "form-owner",
                "module_kind": "form_module",
                "source_text": (
                    "Процедура RefreshForm()\n"
                    "КінецьПроцедури\n"
                ),
            }
        ],
        owners_by_guid={
            "form-owner": {
                "guid": "form-owner",
                "type": "form",
                "name": "DocumentForm",
                "title": "Document form",
                "payload": {},
            }
        },
    )

    symbol = index.local_callable("form-module", "RefreshForm")

    assert symbol is not None
    assert symbol.kind == "procedure"
    assert symbol.exported is False


def test_unresolved_member_reports_exact_declaration_in_another_module() -> None:
    index = build_workspace_semantic_index(
        [
            {
                "module_guid": "module-wrong",
                "owner_guid": "owner-wrong",
                "source_text": (
                    "Procedure Run()\n"
                    "    WrongServer.LoadData();\n"
                    "EndProcedure\n"
                ),
            },
            {
                "module_guid": "module-right",
                "owner_guid": "owner-right",
                "source_text": (
                    "Function LoadData() Export\n"
                    "    Return 1;\n"
                    "EndFunction\n"
                ),
            },
        ],
        owners_by_guid={
            "owner-wrong": _owner("owner-wrong", "WrongServer"),
            "owner-right": _owner("owner-right", "RightServer"),
        },
    )

    diagnostics = index.list_diagnostics(module_guid="module-wrong")

    assert len(diagnostics) == 1
    assert diagnostics[0]["code"] == "unresolved_member"
    assert diagnostics[0]["candidates"] == ["RightServer.LoadData"]


def test_diagnostic_projection_repairs_cp1251_mojibake_identifiers() -> None:
    broken_module = "ПродажиСервер".encode("cp1251").decode("latin1")
    broken_member = "ПолучитьОтветственного".encode("cp1251").decode("latin1")
    diagnostic = WorkspaceDiagnostic(
        code="unresolved_member",
        severity="warning",
        message="Missing exported member",
        module_guid="module-client",
        owner_guid="owner-client",
        qualifier=broken_module,
        name=broken_member,
        candidates=(f"PurchasesServer.{broken_member}",),
    )

    projected = diagnostic.as_dict()

    assert projected["qualifier"] == "ПродажиСервер"
    assert projected["name"] == "ПолучитьОтветственного"
    assert projected["candidates"] == [
        "PurchasesServer.ПолучитьОтветственного"
    ]


def test_workspace_index_reports_close_local_callable_and_module_typos() -> None:
    index = build_workspace_semantic_index(
        [
            {
                "module_guid": "module-settings",
                "owner_guid": "owner-settings",
                "source_text": (
                    "Procedure ReadSettings() Export\n"
                    "EndProcedure\n"
                ),
            },
            {
                "module_guid": "module-client",
                "owner_guid": "owner-client",
                "source_text": (
                    "Procedure RefreshForm()\n"
                    "    RefresForm();\n"
                    "    SettingServer.ReadSettings();\n"
                    "EndProcedure\n"
                ),
            },
        ],
        owners_by_guid={
            "owner-settings": _owner("owner-settings", "SettingsServer"),
            "owner-client": {
                "guid": "owner-client",
                "type": "form",
                "name": "ClientForm",
                "title": "Client form",
                "payload": {},
            },
        },
    )

    diagnostics = index.list_diagnostics(module_guid="module-client")

    assert [item["code"] for item in diagnostics] == [
        "unresolved_callable",
        "unresolved_module",
    ]
    assert diagnostics[0]["candidates"] == ["RefreshForm"]
    assert "SettingsServer" in diagnostics[1]["candidates"]


def test_workspace_index_does_not_report_standard_platform_callable() -> None:
    index = build_workspace_semantic_index(
        [
            {
                "module_guid": "module-client",
                "owner_guid": "owner-client",
                "source_text": (
                    "Procedure Run()\n"
                    "    RoleAvailable = РольДоступна(\"Administrator\");\n"
                    "    ЗаполнитьЗначенияСвойств(Target, Source);\n"
                    "EndProcedure\n"
                ),
            }
        ],
        owners_by_guid={
            "owner-client": {
                "guid": "owner-client",
                "type": "form",
                "name": "ClientForm",
                "title": "Client form",
                "payload": {},
            },
        },
    )

    assert index.list_diagnostics(module_guid="module-client") == []


def test_workspace_index_resolves_normalized_exported_method_alias() -> None:
    index = build_workspace_semantic_index(
        [
            {
                "module_guid": "module-tools",
                "owner_guid": "owner-tools",
                "source_text": (
                    "Функція Очистить() Експорт\n"
                    "    Повернути 42\n"
                    "КінецьФункції\n"
                ),
            },
            {
                "module_guid": "module-client",
                "owner_guid": "owner-client",
                "source_text": (
                    "Процедура Run()\n"
                    "    Tools.Очистити();\n"
                    "КінецьПроцедури\n"
                ),
            },
        ],
        owners_by_guid={
            "owner-tools": _owner("owner-tools", "Tools"),
            "owner-client": {
                "guid": "owner-client",
                "type": "form",
                "name": "ClientForm",
                "title": "Client form",
                "payload": {},
            },
        },
    )

    assert index.list_diagnostics(module_guid="module-client") == []
    references = index.find_references("Tools", "Очистить")
    assert [item["line"] for item in references] == [1, 2]


def test_workspace_index_does_not_treat_shadowed_module_alias_as_module() -> None:
    index = build_workspace_semantic_index(
        [
            {
                "module_guid": "module-settings",
                "owner_guid": "owner-settings",
                "source_text": (
                    "Procedure ReadSettings() Export\n"
                    "EndProcedure\n"
                ),
            },
            {
                "module_guid": "module-client",
                "owner_guid": "owner-client",
                "source_text": (
                    "Procedure Run(SettingsServer)\n"
                    "    SettingsServer.Missing();\n"
                    "EndProcedure\n"
                ),
            },
        ],
        owners_by_guid={
            "owner-settings": _owner("owner-settings", "SettingsServer"),
            "owner-client": {
                "guid": "owner-client",
                "type": "form",
                "name": "ClientForm",
                "title": "Client form",
                "payload": {},
            },
        },
    )

    assert index.list_diagnostics(module_guid="module-client") == []


def test_workspace_index_does_not_treat_nested_object_member_as_module() -> None:
    index = build_workspace_semantic_index(
        [
            {
                "module_guid": "module-users",
                "owner_guid": "owner-users",
                "source_text": (
                    "Procedure Read() Export\n"
                    "EndProcedure\n"
                ),
            },
            {
                "module_guid": "module-client",
                "owner_guid": "owner-client",
                "source_text": (
                    "Procedure Run()\n"
                    "    RecordSet.Filter.Users.Set(Undefined);\n"
                    "EndProcedure\n"
                ),
            },
        ],
        owners_by_guid={
            "owner-users": _owner("owner-users", "Users"),
            "owner-client": {
                "guid": "owner-client",
                "type": "form",
                "name": "ClientForm",
                "title": "Client form",
                "payload": {},
            },
        },
    )

    assert index.list_diagnostics(module_guid="module-client") == []


def test_form_payload_filters_module_alias_collision() -> None:
    diagnostic = WorkspaceDiagnostic(
        code="unresolved_member",
        severity="warning",
        message="Missing exported member",
        module_guid="module-form",
        owner_guid="owner-form",
        line=10,
        qualifier="Users",
        name="Clear",
    )
    index = WorkspaceSemanticIndex(
        modules=(),
        symbols=(),
        references=(),
        diagnostics=(diagnostic,),
    )

    filtered = filter_form_shadow_diagnostics(
        index,
        {
            "owner-form": {
                "form_model": {
                    "root": {
                        "name": "Form",
                        "children": [
                            {
                                "name": "Users",
                                "binding": "Users",
                                "children": [],
                            }
                        ],
                    }
                }
            }
        },
    )

    assert filtered.list_diagnostics() == []


def test_workspace_index_validates_object_requisites_from_form_owner_schema() -> None:
    index = build_workspace_semantic_index(
        [
            {
                "module_guid": "form-module",
                "owner_guid": "form-owner",
                "module_kind": "form_module",
                "source_text": (
                    "Procedure Fill()\n"
                    "    Value = Object.Organizaton;\n"
                    "    Existing = Object.Organization;\n"
                    "    Object.Write();\n"
                    "EndProcedure\n"
                ),
            }
        ],
        owners_by_guid={
            "form-owner": {
                "guid": "form-owner",
                "type": "form",
                "name": "DocumentForm",
                "payload": {"owner_guid": "document-owner"},
            },
            "document-owner": {
                "guid": "document-owner",
                "type": "document",
                "name": "Sales",
                "payload": {
                    "requisites": [
                        {"name": "Organization"},
                        {"name": "Date"},
                    ],
                    "tabular_parts": [{"name": "Goods"}],
                },
            },
        },
    )

    diagnostics = index.list_diagnostics(module_guid="form-module")

    assert [item["code"] for item in diagnostics] == [
        "unresolved_requisite"
    ]
    assert diagnostics[0]["name"] == "Organizaton"
    assert diagnostics[0]["candidates"] == ["Organization"]


def test_workspace_index_skips_requisite_check_without_complete_schema() -> None:
    index = build_workspace_semantic_index(
        [
            {
                "module_guid": "form-module",
                "owner_guid": "form-owner",
                "module_kind": "form_module",
                "source_text": (
                    "Procedure Fill()\n"
                    "    Value = Object.UnknownField;\n"
                    "EndProcedure\n"
                ),
            }
        ],
        owners_by_guid={
            "form-owner": {
                "guid": "form-owner",
                "type": "form",
                "name": "DocumentForm",
                "payload": {},
            }
        },
    )

    assert index.list_diagnostics(module_guid="form-module") == []
