from __future__ import annotations

"""Canonical IDE-facing catalog of MetaScript platform symbols."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MetadataCategory:
    type_name: str
    names: tuple[str, ...]


METADATA_ROOTS: tuple[str, ...] = ("Метадані", "Метаданные", "Metadata")

METADATA_CATEGORIES: tuple[MetadataCategory, ...] = (
    MetadataCategory("catalog", ("Довідники", "Справочники", "Catalogs")),
    MetadataCategory("document", ("Документи", "Документы", "Documents")),
    MetadataCategory("enumeration", ("Перерахування", "Перечисления", "Enums")),
    MetadataCategory("report", ("Звіти", "Отчеты", "Reports")),
    MetadataCategory("data_processor", ("Обробки", "Обработки", "DataProcessors")),
    MetadataCategory("constants", ("Константи", "Константы", "Constants")),
    MetadataCategory("register_info", ("РегістриВідомостей", "РегистрыСведений", "InformationRegisters")),
    MetadataCategory("register_accum", ("РегістриНакопичення", "РегистрыНакопления", "AccumulationRegisters")),
    MetadataCategory("register_accounting", ("РегістриБухгалтерії", "РегистрыБухгалтерии", "AccountingRegisters")),
    MetadataCategory("register_calc", ("РегістриРозрахунку", "РегистрыРасчета", "CalculationRegisters")),
    MetadataCategory("exchange_plan", ("ПланиОбміну", "ПланыОбмена", "ExchangePlans")),
    MetadataCategory("chart_of_characteristic_types", ("ПланиВидівХарактеристик", "ПланыВидовХарактеристик", "ChartsOfCharacteristicTypes")),
    MetadataCategory("chart_of_accounts", ("ПланиРахунків", "ПланыСчетов", "ChartsOfAccounts")),
    MetadataCategory("chart_of_calculation_types", ("ПланиВидівРозрахунку", "ПланыВидовРасчета", "ChartsOfCalculationTypes")),
    MetadataCategory("business_process", ("БізнесПроцеси", "БизнесПроцессы", "BusinessProcesses")),
    MetadataCategory("task", ("Завдання", "Задачи", "Tasks")),
    MetadataCategory("role", ("Ролі", "Роли", "Roles")),
    MetadataCategory("session_parameter", ("ПараметриСеансу", "ПараметрыСеанса", "SessionParameters")),
    MetadataCategory("common_form", ("СпільніФорми", "ОбщиеФормы", "CommonForms")),
    MetadataCategory("common_module", ("СпільніМодулі", "ОбщиеМодули", "CommonModules")),
    MetadataCategory("subsystem", ("Підсистеми", "Подсистемы", "Subsystems")),
)

METADATA_ROOT_MEMBERS: tuple[str, ...] = (
    "Назва", "Имя", "Name", "Версія", "Версия", "Version",
    "Знайти", "Найти", "Find", "Обєкти", "Объекты", "Objects",
)
METADATA_COLLECTION_MEMBERS: tuple[str, ...] = (
    "Знайти", "Найти", "Find", "Кількість", "Количество", "Count",
)
METADATA_OBJECT_MEMBERS: tuple[str, ...] = (
    "Назва", "Имя", "Name", "Синонім", "Синоним", "Synonym",
    "ПовнеІмя", "ПолноеИмя", "FullName", "Тип", "Type", "GUID", "Guid",
    "Батько", "Родитель", "Parent", "Властивості", "Свойства", "Properties",
)


def metadata_category_for_name(name: str) -> MetadataCategory | None:
    target = str(name or "").casefold()
    for category in METADATA_CATEGORIES:
        if any(alias.casefold() == target for alias in category.names):
            return category
    return None


def metadata_root_members() -> tuple[str, ...]:
    categories = [alias for category in METADATA_CATEGORIES for alias in category.names]
    return tuple(dict.fromkeys([*categories, *METADATA_ROOT_MEMBERS]))


def standard_runtime_names() -> tuple[str, ...]:
    names = [*METADATA_ROOTS, *metadata_root_members()]
    names.extend(
        (
            "Символи", "Символы", "Chars", "НСтр", "NStr",
            "ВРег", "Upper", "НРег", "Lower",
            "ПоточнаДата", "ТекущаяДата", "CurrentDate",
            "ЗаповнитиЗначенняВластивостей", "ЗаполнитьЗначенияСвойств",
            "FillPropertyValues",
            "КаталогДокументів", "КаталогДокументов", "DocumentsDirectory",
            "ПереміститиФайл", "ПереместитьФайл", "MoveFile",
            "ОтриматиЗТимчасовогоСховища", "ПолучитьИзВременногоХранилища",
            "GetFromTemporaryStorage",
            "РобочийКаталогДанихКористувача",
            "РабочийКаталогДанныхПользователя", "UserDataWorkDirectory",
            "РольДоступна", "RoleAvailable",
            "ВидалитиФайли", "УдалитьФайлы", "DeleteFiles",
            "ВстановитиБезпечнийРежим", "УстановитьБезопасныйРежим",
            "SetSafeMode",
            # 1C-compatible platform procedures/functions. These names are
            # global runtime API, not declarations expected in a workspace
            # module, so the semantic index must not report them as missing.
            "ПоказатьОповещениеПользователя", "ПоказатиСповіщенняКористувача",
            "ShowUserNotification",
            "КонфигурацияБазыДанныхИзмененаДинамически",
            "КонфігураціюБазиДанихЗміненоДинамічно",
            "DatabaseConfigurationChangedDynamically",
            "ЗаблокироватьДанныеДляРедактирования",
            "ЗаблокуватиДаніДляРедагування",
            "LockDataForEditing",
            "РазблокироватьДанныеДляРедактирования",
            "РозблокуватиДаніДляРедагування",
            "UnlockDataForEditing",
            "ЗаписьЖурналаРегистрации", "ЗаписатиВЖурналРеєстрації",
            "WriteToEventLog",
            "ОткрытьЗначение", "ВідкритиЗначення", "OpenValue",
            "ПоместитьВоВременноеХранилище", "ПоміститиУТимчасовеСховище",
            "PutToTemporaryStorage",
        )
    )
    return tuple(dict.fromkeys(names))
