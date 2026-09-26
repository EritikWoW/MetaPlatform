from __future__ import annotations

from src.runtime.script.catalog_proxy import QueryProxy, SystemInformationProxy, build_global_context


class _DbStub:
    db_uid = "db-test"

    class _Table:
        def __init__(self, rows) -> None:
            self._rows = list(rows)

        def select(self, where=None, order_by=None):
            return list(self._rows)

    def table(self, name: str):
        rows = {
            "sys_users": [
                {"user_id": "system", "login": "system", "is_active": True},
            ],
            "sys_roles": [
                {"role_id": "admin-role", "name": "Admin"},
            ],
            "sys_user_roles": [
                {"user_id": "system", "role_id": "admin-role"},
            ],
        }.get(name, [])
        return self._Table(rows)


def test_startup_platform_globals_have_stable_uk_ru_en_aliases() -> None:
    context = build_global_context(_DbStub())

    assert context["ПривилегированныйРежим"]() is False
    assert context["ПривілейованийРежим"]() is False
    assert context["PrivilegedMode"]() is False
    assert context["СтрокаСоединенияИнформационнойБазы"]() == "db-test"

    info = context["СистемнаяИнформация"]()
    assert isinstance(info, SystemInformationProxy)
    assert info.ТипПлатформы in {
        "Linux_x86",
        "Linux_x86_64",
        "Windows_x86",
        "Windows_x86_64",
        "MacOS_x86",
        "MacOS_x86_64",
    }
    assert context["ТипПлатформы"].Linux_x86 == "Linux_x86"
    assert context["Символы"].ВК + context["Символы"].ПС == "\r\n"
    assert context["ПараметрыСеанса"].ПараметрыКлиентаНаСервере.Кількість() == 0
    assert context["ПараметрыСеанса"].ОбластьДанныхИспользование is None

    source = context["ФиксированноеСоответствие"]()
    source.Вставить("Answer", 42)
    copied = context["ФиксированнаяСтруктура"](source)
    assert copied.Answer == 42
    assert context["ПолучитьФункциональнуюОпцию"]("AnyFeature") is False
    assert context["УстановитьБезопасныйРежим"](True) is None
    assert context["ПравоДоступа"]("Администрирование") is True
    assert context["Константы"]["Missing"].Получить().Получить() is None
    assert bool(context["ПланыОбмена"].ПолучитьГлавныйУзел()) is False
    assert context["ПользователиИнформационнойБазы"].ПолучитьПользователей().Количество() == 0
    mode = context["ОбновлениеПредопределенныхДанных"].НеОбновлятьАвтоматически
    context["УстановитьОбновлениеПредопределенныхДанныхИнформационнойБазы"](mode)
    assert context["ПолучитьОбновлениеПредопределенныхДанныхИнформационнойБазы"]() == mode
    assert context["МонопольныйРежим"]() is False
    context["НачатьТранзакцию"]()
    assert context["ТранзакцияАктивна"]() is True
    context["ЗафиксироватьТранзакцию"]()
    assert context["ТранзакцияАктивна"]() is False
    context["УстановитьМонопольныйРежим"](True)
    assert context["МонопольныйРежим"]() is True
    context["Константы"]["Missing"].СоздатьМенеджерЗначения().Обновить()


def test_global_context_exposes_lazy_metadata_objects() -> None:
    broken_title = "Контрагенты".encode("cp1251").decode("latin1")

    class _Gateway:
        def manifest_lookup(self, *, type_name: str = "", limit: int = 0, **_kwargs):
            assert limit > 0
            return [
                {"guid": "cat-1", "type": "catalog", "kind": "object", "name": "Products", "title": "Товари"},
                {"guid": "cat-2", "type": "catalog", "kind": "object", "name": "Kontrahenty", "title": broken_title},
            ] if type_name == "catalog" else []

    class _MetadataDb(_DbStub):
        _gw = _Gateway()

    metadata = build_global_context(_MetadataDb())["Метадані"]
    product = metadata.Довідники.Products

    assert product.GUID == "cat-1"
    assert product.Name == "Products"
    assert product.Синонім == "Товари"
    assert metadata.Довідники.Контрагенты.GUID == "cat-2"
    assert metadata.Довідники.Kontrahenty.Синонім == "Контрагенты"


def test_query_supports_parameters_and_unloaded_value_table() -> None:
    class _QueryDb:
        class _Table:
            def __init__(self, name: str) -> None:
                self._name = name

            def select(self, where=None, order_by=None):
                if self._name == "manifest":
                    return [
                        {
                            "guid": "reg-1",
                            "type": "register_info",
                            "name": "versions",
                            "title": "ВерсииПодсистем",
                        }
                    ]
                if self._name == "data_reg_versions":
                    return [{"Версия": "3.1.0"}]
                return []

        def table(self, name: str):
            return self._Table(name)

    query = QueryProxy(_QueryDb())
    query.Текст = "ВЫБРАТЬ Версия ИЗ РегистрСведений.ВерсииПодсистем"
    query.УстановитьПараметр("ИмяПодсистемы", "Configuration")

    table = query.Цикл().Выгрузить()

    assert query.Параметры.ИмяПодсистемы == "Configuration"
    assert table.Кількість() == 1
    assert table[0]["Версия"] == "3.1.0"


def test_query_execute_batch_returns_one_result_per_statement() -> None:
    class _QueryDb:
        class _Table:
            def __init__(self, name: str) -> None:
                self._name = name

            def select(self, where=None, order_by=None):
                if self._name == "manifest":
                    rows = [
                        {"type": "register_info", "name": "first", "title": "First"},
                        {"type": "register_info", "name": "second", "title": "Second"},
                    ]
                    if where:
                        return [
                            row for row in rows
                            if all(row.get(key) == value for key, value in where.items())
                        ]
                    return rows
                if self._name == "data_reg_first":
                    return [{"value": 1}]
                return []

        def table(self, name: str):
            return self._Table(name)

    query = QueryProxy(
        _QueryDb(),
        "SELECT 1 FROM InformationRegister.First; SELECT 1 FROM InformationRegister.Second",
    )

    results = query.ExecuteBatch()

    assert results.Count() == 2
    assert results[0].Empty() is False
    assert results[1].Empty() is True


def test_query_batch_reuses_runtime_manifest_lookup() -> None:
    calls: list[tuple[str, str]] = []

    class _Gateway:
        def manifest_lookup(self, *, type_name: str, name: str, limit: int):
            calls.append((type_name, name))
            return [{"type": "register_info", "name": name, "title": name}]

    class _Db:
        _gw = _Gateway()

        class _Table:
            def select(self, where=None, order_by=None):
                return []

        def table(self, _name: str):
            return self._Table()

    context = build_global_context(_Db())
    query = context["Запрос"](
        "SELECT 1 FROM InformationRegister.Versions; SELECT 1 FROM InformationRegister.Versions"
    )

    query.ExecuteBatch()

    assert calls == [("register_info", "Versions")]
