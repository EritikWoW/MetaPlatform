from __future__ import annotations

import base64
import html
import contextlib
import io
import hashlib
import json
import re
import posixpath
import struct
import zlib
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .onec_config_parser import (
    _extract_named_objects,
    extract_config_type_aliases,
    parse_config_text,
)
from .module_transform import sanitize_imported_module_text
from .physical_schema import _load_parse1cd_backend


_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_GUID_SUFFIX_RE = re.compile(
    r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(?:\.(\d+))?$"
)
_GUID_REF_RE = re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")
_BLOB_PTR_RE = re.compile(r"^BLOB:(\d+):(\d+)$")
_DBNAMES_ENTRY_RE = re.compile(r'\{([0-9a-fA-F-]{36}),"([^"]+)",(\d+)\}')
_PARAMS_METADATA_ENTRY_RE = re.compile(
    r"(" + _GUID_RE.pattern[1:-1] + r"),(" + _GUID_RE.pattern[1:-1]
    + r'),(\d+),"([^"]+)"',
    re.IGNORECASE,
)
_CONFIG_GROUP_RE = re.compile(
    r"\{([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\s*,\s*(\d+)\s*,([^{}]*)\}",
    re.DOTALL,
)
_CATALOG_LIKE_FAMILIES = {"catalog", "chart_of_accounts", "chart_of_characteristic_types"}
_DOCUMENT_LIKE_FAMILIES = {"document", "business_process", "task"}
_REGISTER_LIKE_FAMILIES = {
    "accumulation_register",
    "information_register",
    "accounting_register",
    "calculation_register",
}
_COMMON_MODULE_NAME_HINTS = (
    "Общ",
    "Пользователь",
    "Пользователи",
    "ОбщегоНазначения",
    "ОбщиеПроцедуры",
    "РаботаВМоделиСервиса",
    "Аутентификация",
    "УправлениеДоступом",
    "ОбменДанными",
    "АвтономнаяРабота",
    "УдаленноеАдминистрирование",
    "КаталогОбменаФайлами",
    "БазоваяФункциональность",
    "ИнтеграцияС1С",
    "Пользовательские",
    "Служебный",
    "ОбщаяПинкод",
    "ОбщаяРегНомер",
    "ОбщаяАвторизация",
)
_OBJECT_MODULE_HINTS = (
    "ОбработкаЗаполнения",
    "ОбработкаПроведения",
    "ПередЗаписью",
    "ПриЗаписи",
    "ПередУдалением",
    "ПриКопировании",
    "ПередНачаломЗаписи",
    "ПослеЗаписи",
)
_FORM_MODULE_HINTS = (
    "#Область ПрограммныйИнтерфейс",
    "#Region ProgramInterface",
    "#Область Печать",
    "#Region Print",
    "#Область ОбработчикиСобытийФормы",
    "ПриСозданииНаСервере",
    "ПриОткрытии",
    "ПриАктивизации",
    "ПриИзменении",
    "ОбработкаВыбора",
)
_BSL_CODE_START_RE = re.compile(
    r"(?m)^[ \t]*(#Область\b|#Region\b|&На\b|&On\b|Процедура\b|"
    r"Procedure\b|Функция\b|Функція\b|Function\b|Перем\b|Змін\b|Var\b)"
)
_BSL_DECLARATION_RE = re.compile(
    r"(?im)^[ \t]*(?:Процедура|Procedure|Функция|Функція|Function)\b"
)
_BSL_DECLARATION_END_RE = re.compile(
    r"(?im)^[ \t]*(?:КонецПроцедуры|КінецьПроцедури|EndProcedure|КонецФункции|КінецьФункції|EndFunction)\b"
)
_BSL_DECLARATION_NAME_RE = re.compile(
    r"(?im)^[ \t]*(?:Процедура|Procedure|Функция|Функція|Function)[ \t]+([\w\u0400-\u04ff]+)"
)
_BSL_DECLARATION_LINE_RE = re.compile(
    r"(?im)^[ \t]*(?:Процедура|Procedure|Функция|Функція|Function)\b[^\r\n]*"
)
_BSL_RECOVERY_START_RE = re.compile(
    r"(?m)^[ \t]*(?:#Если\b|#If\b|#Область\b|#Region\b|&На\b|&On\b|Процедура\b|"
    r"Procedure\b|Функция\b|Функція\b|Function\b|Перем\b|Змін\b|Var\b)"
)
_INVALID_SOURCE_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffd]")
_SERIALIZED_BSL_TAIL_RE = re.compile(r'(?m)^[ \t]*"[ \t]*,[ \t]*\r?$')
_SERIALIZED_BSL_ATTACHED_TAIL_RE = re.compile(
    r'(?im)(?:#КонецОбласти|#EndRegion|КонецПроцедуры|КінецьПроцедури|EndProcedure|'
    r'КонецФункции|КінецьФункції|EndFunction)(?P<tail>"[ \t]*,[ \t]*\r?$)'
)
_BSL_REGION_END_RE = re.compile(r"(?im)^[ \t]*(?:#КонецОбласти|#EndRegion)\b[^\r\n]*(?:\r?\n|$)")
_BSL_DECLARATION_END_LINE_RE = re.compile(
    r"(?im)^[ \t]*(?:КонецПроцедуры|КінецьПроцедури|EndProcedure|КонецФункции|"
    r"КінецьФункції|EndFunction)\b[^\r\n]*(?:\r?\n|$)"
)
_BSL_ALLOWED_TERMINAL_SUFFIX_LINE_RE = re.compile(
    r"(?i)^[ \t]*(?://|/\*|\*|\*/|#КонецОбласти\b|#EndRegion\b|#КонецЕсли\b|#EndIf\b|$)"
)
_CONFIGURATION_ROOT_MODULE_FILES: Tuple[str, ...] = (
    "ManagedApplicationModule.bsl",
    "SessionModule.bsl",
    "ExternalConnectionModule.bsl",
    "OrdinaryApplicationModule.bsl",
)
_CONFIGURATION_ROOT_MODULE_HINTS: Dict[str, tuple[tuple[str, int], ...]] = {
    "ManagedApplicationModule.bsl": (
        ("глПодключаемоеОборудование", 20),
        ("глДоступныеТипыОборудования", 20),
        ("ПараметрыПодсистемыОбменБанками", 18),
        ("СоответствиеСертификатаИПароля", 12),
        ("глКомпонентаОбменаСМобильнымиПриложениями", 14),
        ("глФормаНачальнойНастройкиПрограммы", 14),
        ("СообщенияДляЖурналаРегистрации", 18),
        ("ПредлагатьУстановкуРасширенияРаботыСФайлами", 14),
        ("ПропуститьПредупреждениеПередЗавершениемРаботыСистемы", 14),
        ("ПараметрыПриЗапускеИЗавершенииПрограммы", 14),
        ("ПараметрыПодтвержденияЗакрытияФормы", 14),
        ("ОповещениеПриПримененииЗапросовНаИспользованиеВнешнихРесурсов", 14),
        ("ПараметрыЗавершенияРаботыПользователей", 10),
        ("СтандартныеПодсистемы", 6),
        ("СтандартныеПодсистемы.БазоваяФункциональность", 8),
        ("СтандартныеПодсистемыКлиентПовтИсп", 6),
        ("СтандартныеПодсистемыВызовСервера", 4),
    ),
    "SessionModule.bsl": (
        ("УстановкаПараметровСеанса", 40),
        ("ПараметрыСеанса.ТекущийПользователь", 16),
        ("ПараметрыСеанса.ТекущийВнешнийПользователь", 16),
        ("ПередЗапускомПрограммы", 12),
        ("ПараметрыКлиентаНаСервере", 10),
        ("ПараметрыРаботыКлиентаПриЗапуске", 6),
    ),
    "ExternalConnectionModule.bsl": (
        ("ПараметрыСеанса.ТекущийВнешнийПользователь", 24),
        ("ВнешнееСоединение", 22),
        ("АвторизованныйПользователь", 24),
        ("ПараметрыРаботыКлиентаПриЗапуске", 8),
        ("ТолстыйКлиентОбычноеПриложение", 6),
    ),
    "OrdinaryApplicationModule.bsl": (
        ("Функция ПараметрыРаботыКлиентаПриЗапуске() Экспорт", 30),
        ("Возвращает структуру параметров, необходимых для работы конфигурации на клиенте при запуске", 20),
        ("ПередНачаломРаботыСистемы", 16),
        ("ПриНачалеРаботыСистемы", 16),
        ("ПараметрыПриЗапускеИЗавершенииПрограммы", 14),
        ("ПараметрыРаботыКлиентаПриЗапуске", 12),
        ("ПолученныеПараметрыКлиента", 10),
        ("ПропуститьОчисткуСкрытияРабочегоСтола", 10),
        ("ОбычноеПриложение", 8),
        ("ВнешнееСоединение", 6),
    ),
}
_CONFIGURATION_ROOT_MODULE_PENALTIES: tuple[tuple[str, int], ...] = (
    ("#Область ОбработчикиСобытийФормы", 30),
    ("ОбработкаЗаполнения", 10),
    ("ОбработкаПроверкиЗаполнения", 10),
    ("ПриСозданииНаСервере", 8),
    ("ПередЗаписью", 8),
    ("ПриКопировании", 6),
    ("ПараметрыФормыОшибкиОбращения", 20),
    ("ИнтернетПоддержкаПользователей", 12),
    ("ПроверитьОбновлениеКонфигурации", 12),
    ("Поиск и удаление дублей", 10),
    ("Открывает форму объединения", 10),
    ("ПодтвердитьЗакрытиеПроизвольнойФормы", 8),
    ("Записывает сообщение в журнал регистрации", 8),
    ("РаботаСВнешнимОборудованием", 4),
    ("ЭлектронноеВзаимодействие", 4),
    ("ОбменСБанками", 4),
    ("СтандартныеПодсистемыКлиентПовтИсп", 4),
    ("СтандартныеПодсистемыВызовСервера", 4),
    ("ПараметрыЗавершенияРаботыПользователей", 4),
)


@dataclass(frozen=True, slots=True)
class OneCDMetadataKind:
    dbname_kind: str
    folder: str
    xml_tag: str
    family: str
    dump_root: str


@dataclass(frozen=True, slots=True)
class OneCDMetadataObject:
    uuid: str
    dbname_kind: str
    folder: str
    xml_tag: str
    family: str
    dump_root: str
    name: str
    title: str
    synonyms: Dict[str, str]
    order: int
    origin: str
    dbname_order: int = 0
    parent_guid: str = ""
    tree_path: str = ""
    is_virtual: bool = False
    virtual_reason: str = ""
    child_subsystems: List[str] = field(default_factory=list)
    content_refs: List[str] = field(default_factory=list)


ONECD_METADATA_KIND_MAP: Dict[str, OneCDMetadataKind] = {
    "Reference": OneCDMetadataKind("Reference", "Catalogs", "Catalog", "catalog", "Catalog"),
    "Document": OneCDMetadataKind("Document", "Documents", "Document", "document", "Document"),
    "DocumentJournal": OneCDMetadataKind(
        "DocumentJournal",
        "DocumentJournals",
        "DocumentJournal",
        "document_journal",
        "DocumentJournal",
    ),
    "Enum": OneCDMetadataKind("Enum", "Enums", "Enum", "enum", "Enum"),
    "Const": OneCDMetadataKind("Const", "Constants", "Constant", "constant", "Constant"),
    "InfoRg": OneCDMetadataKind(
        "InfoRg",
        "InformationRegisters",
        "InformationRegister",
        "information_register",
        "InformationRegister",
    ),
    "AccumRg": OneCDMetadataKind(
        "AccumRg",
        "AccumulationRegisters",
        "AccumulationRegister",
        "accumulation_register",
        "AccumulationRegister",
    ),
    "AccRg": OneCDMetadataKind(
        "AccRg",
        "AccountingRegisters",
        "AccountingRegister",
        "accounting_register",
        "AccountingRegister",
    ),
    "CRg": OneCDMetadataKind(
        "CRg",
        "CalculationRegisters",
        "CalculationRegister",
        "calculation_register",
        "CalculationRegister",
    ),
    "BPr": OneCDMetadataKind("BPr", "BusinessProcesses", "BusinessProcess", "business_process", "BusinessProcess"),
    "Task": OneCDMetadataKind("Task", "Tasks", "Task", "task", "Task"),
    "ScheduledJobs": OneCDMetadataKind("ScheduledJob", "ScheduledJobs", "ScheduledJob", "scheduled_job", "ScheduledJob"),
    "ScheduledJob": OneCDMetadataKind("ScheduledJob", "ScheduledJobs", "ScheduledJob", "scheduled_job", "ScheduledJob"),
    "Chrc": OneCDMetadataKind(
        "Chrc",
        "ChartsOfCharacteristicTypes",
        "ChartOfCharacteristicTypes",
        "chart_of_characteristic_types",
        "ChartOfCharacteristicTypes",
    ),
    "Acc": OneCDMetadataKind("Acc", "ChartsOfAccounts", "ChartOfAccounts", "chart_of_accounts", "ChartOfAccounts"),
    "ChartOfCalculationTypes": OneCDMetadataKind(
        "ChartOfCalculationTypes",
        "ChartsOfCalculationTypes",
        "ChartOfCalculationTypes",
        "chart_of_calculation_types",
        "ChartOfCalculationTypes",
    ),
    "Report": OneCDMetadataKind("Report", "Reports", "Report", "report", "Report"),
    "DataProcessor": OneCDMetadataKind("DataProcessor", "DataProcessors", "DataProcessor", "data_processor", "DataProcessor"),
    # Exchange plans, common attributes and other DBNames-registered common objects
    "ExchangePlan": OneCDMetadataKind("ExchangePlan", "ExchangePlans", "ExchangePlan", "exchange_plan", "ExchangePlan"),
    "Subsystem": OneCDMetadataKind("Subsystem", "Subsystems", "Subsystem", "subsystem", "Subsystem"),
    "Role": OneCDMetadataKind("Role", "Roles", "Role", "role", "Role"),
    "CommonModule": OneCDMetadataKind("CommonModule", "CommonModules", "CommonModule", "common_module", "CommonModule"),
    "CommonForm": OneCDMetadataKind("CommonForm", "CommonForms", "CommonForm", "common_form", "CommonForm"),
    "CommonCommand": OneCDMetadataKind("CommonCommand", "CommonCommands", "CommonCommand", "common_command", "CommonCommand"),
    "CommandGroup": OneCDMetadataKind("CommandGroup", "CommandGroups", "CommandGroup", "command_group", "CommandGroup"),
    "CommonTemplate": OneCDMetadataKind("CommonTemplate", "CommonTemplates", "CommonTemplate", "common_layout", "CommonTemplate"),
    "CommonPicture": OneCDMetadataKind("CommonPicture", "CommonPictures", "CommonPicture", "common_picture", "CommonPicture"),
    "CommonAttribute": OneCDMetadataKind("CommonAttribute", "CommonAttributes", "CommonAttribute", "common_attribute", "CommonAttribute"),
    "SessionParameter": OneCDMetadataKind("SessionParameter", "SessionParameters", "SessionParameter", "session_parameter", "SessionParameter"),
    "EventSubscription": OneCDMetadataKind("EventSubscription", "EventSubscriptions", "EventSubscription", "event_subscription", "EventSubscription"),
    "FunctionalOption": OneCDMetadataKind("FunctionalOption", "FunctionalOptions", "FunctionalOption", "functional_option", "FunctionalOption"),
    "FunctionalOptionsParameter": OneCDMetadataKind("FunctionalOptionsParameter", "FunctionalOptionsParameters", "FunctionalOptionsParameter", "functional_option_param", "FunctionalOptionsParameter"),
    "DefinedType": OneCDMetadataKind("DefinedType", "DefinedTypes", "DefinedType", "defined_type", "DefinedType"),
    "SettingsStorage": OneCDMetadataKind("SettingsStorage", "SettingsStorages", "SettingsStorage", "settings_storage", "SettingsStorage"),
    "WebService": OneCDMetadataKind("WebService", "WebServices", "WebService", "web_service", "WebService"),
    "HTTPService": OneCDMetadataKind("HTTPService", "HTTPServices", "HTTPService", "http_service", "HTTPService"),
    "WSReference": OneCDMetadataKind("WSReference", "WSReferences", "WSReference", "ws_reference", "WSReference"),
    "Sequence": OneCDMetadataKind("Sequence", "Sequences", "Sequence", "sequence", "Sequence"),
    "DocumentNumerator": OneCDMetadataKind("DocumentNumerator", "DocumentNumerators", "DocumentNumerator", "document_numerator", "DocumentNumerator"),
    "StyleItem": OneCDMetadataKind("StyleItem", "StyleItems", "StyleItem", "style_element", "StyleItem"),
    "Style": OneCDMetadataKind("Style", "Styles", "Style", "style", "Style"),
    "Language": OneCDMetadataKind("Language", "Languages", "Language", "language", "Language"),
    "ExternalDataSource": OneCDMetadataKind("ExternalDataSource", "ExternalDataSources", "ExternalDataSource", "external_sources", "ExternalDataSource"),
    "SelectionCriterion": OneCDMetadataKind("SelectionCriterion", "FilterCriteria", "SelectionCriterion", "selection_criteria", "FilterCriterion"),
    "SelectionCriteria": OneCDMetadataKind("SelectionCriterion", "FilterCriteria", "SelectionCriterion", "selection_criteria", "FilterCriterion"),
    "FilterCriterion": OneCDMetadataKind("SelectionCriterion", "FilterCriteria", "SelectionCriterion", "selection_criteria", "FilterCriterion"),
    "XDTOPackage": OneCDMetadataKind("XDTOPackage", "XDTOPackages", "XDTOPackage", "xdto_package", "XDTOPackage"),
}


ONECD_PLATFORM_GROUP_KIND_FALLBACK: Dict[str, OneCDMetadataKind] = {
    # Stable 1C platform collection class ids from Config's root metadata row.
    # These are not configuration object UUIDs and are used only when DBNames
    # and member-shape inference cannot identify the group kind.
    "0195e80c-b157-11d4-9435-004095e12fc7": ONECD_METADATA_KIND_MAP["Const"],
    "061d872a-5787-460e-95ac-ed74ea3a3e84": ONECD_METADATA_KIND_MAP["Document"],
    "07ee8426-87f1-11d5-b99c-0050bae0a95d": ONECD_METADATA_KIND_MAP["CommonForm"],
    "09736b02-9cac-4e3f-b4f7-d3e9576ab948": ONECD_METADATA_KIND_MAP["Role"],
    "0c89c792-16c3-11d5-b96b-0050bae0a95d": ONECD_METADATA_KIND_MAP["CommonTemplate"],
    "0fe48980-252d-11d6-a3c7-0050bae0a776": ONECD_METADATA_KIND_MAP["CommonModule"],
    "11bdaf85-d5ad-4d91-bb24-aa0eee139052": ONECD_METADATA_KIND_MAP["ScheduledJob"],
    "13134201-f60b-11d5-a3c7-0050bae0a776": ONECD_METADATA_KIND_MAP["InfoRg"],
    "15794563-ccec-41f6-a83c-ec5f7b9a5bc1": ONECD_METADATA_KIND_MAP["CommonAttribute"],
    "1c57eabe-7349-44b3-b1de-ebfeab67b47d": ONECD_METADATA_KIND_MAP["CommandGroup"],
    "238e7e88-3c5f-48b2-8a3b-81ebbecb20ed": ONECD_METADATA_KIND_MAP["Acc"],
    "24c43748-c938-45d0-8d14-01424a72b11e": ONECD_METADATA_KIND_MAP["SessionParameter"],
    "2deed9b8-0056-4ffe-a473-c20a6c32a0bc": ONECD_METADATA_KIND_MAP["AccRg"],
    "2f1a5187-fb0e-4b05-9489-dc5dd6412348": ONECD_METADATA_KIND_MAP["CommonCommand"],
    "30b100d6-b29f-47ac-aec7-cb8ca8a54767": ONECD_METADATA_KIND_MAP["ChartOfCalculationTypes"],
    "30d554db-541e-4f62-8970-a1c6dcfeb2bc": ONECD_METADATA_KIND_MAP["FunctionalOptionsParameter"],
    "36a8e346-9aaa-4af9-bdbd-83be3c177977": ONECD_METADATA_KIND_MAP["DocumentNumerator"],
    "37f2fa9a-b276-11d4-9435-004095e12fc7": ONECD_METADATA_KIND_MAP["Subsystem"],
    "3e5404af-6ef8-4c73-ad11-91bd2dfac4c8": ONECD_METADATA_KIND_MAP["Style"],
    "3e63355c-1378-4953-be9b-1deb5fb6bec5": ONECD_METADATA_KIND_MAP["Task"],
    "3e7bfcc0-067d-11d6-a3c7-0050bae0a776": ONECD_METADATA_KIND_MAP["FilterCriterion"],
    "4612bd75-71b7-4a5c-8cc5-2b0b65f9fa0d": ONECD_METADATA_KIND_MAP["DocumentJournal"],
    "46b4cd97-fd13-4eaa-aba2-3bddd7699218": ONECD_METADATA_KIND_MAP["SettingsStorage"],
    "4e828da6-0f44-4b5b-b1c0-a2b3cfe7bdcc": ONECD_METADATA_KIND_MAP["EventSubscription"],
    "5274d9fc-9c3a-4a71-8f5e-a0db8ab23de5": ONECD_METADATA_KIND_MAP["ExternalDataSource"],
    "58848766-36ea-4076-8800-e91eb49590d7": ONECD_METADATA_KIND_MAP["StyleItem"],
    "631b75a0-29e2-11d6-a3c7-0050bae0a776": ONECD_METADATA_KIND_MAP["Report"],
    "7dcd43d9-aca5-4926-b549-1842e6a4e8cf": ONECD_METADATA_KIND_MAP["CommonPicture"],
    "82a1b659-b220-4d94-a9bd-14d757b95a48": ONECD_METADATA_KIND_MAP["Chrc"],
    "857c4a91-e5f4-4fac-86ec-787626f1c108": ONECD_METADATA_KIND_MAP["ExchangePlan"],
    "8657032e-7740-4e1d-a3ba-5dd6e8afb78f": ONECD_METADATA_KIND_MAP["WebService"],
    "9cd510ce-abfc-11d4-9434-004095e12fc7": ONECD_METADATA_KIND_MAP["Language"],
    "af547940-3268-434f-a3e7-e47d6d2638c3": ONECD_METADATA_KIND_MAP["FunctionalOption"],
    "b64d9a40-1642-11d6-a3c7-0050bae0a776": ONECD_METADATA_KIND_MAP["AccumRg"],
    "bc587f20-35d9-11d6-a3c7-0050bae0a776": ONECD_METADATA_KIND_MAP["Sequence"],
    "bf845118-327b-4682-b5c6-285d2a0eb296": ONECD_METADATA_KIND_MAP["DataProcessor"],
    "c045099e-13b9-4fb6-9d50-fca00202971e": ONECD_METADATA_KIND_MAP["DefinedType"],
    "cc9df798-7c94-4616-97d2-7aa0b7bc515e": ONECD_METADATA_KIND_MAP["XDTOPackage"],
    "cf4abea6-37b2-11d4-940f-008048da11f9": ONECD_METADATA_KIND_MAP["Reference"],
    "f2de87a8-64e5-45eb-a22d-b3aedab050e7": ONECD_METADATA_KIND_MAP["CRg"],
    "f6a80749-5ad7-400b-8519-39dc5dff2542": ONECD_METADATA_KIND_MAP["Enum"],
    "fcd3404e-1523-48ce-9bc0-ecdb822684a1": ONECD_METADATA_KIND_MAP["BPr"],
}

ONECD_MODULE_SUFFIX_KIND_MAP: Dict[tuple[str, int], str] = {
    ("AccumulationRegister", 1): "RecordSetModule",
    ("AccumulationRegister", 2): "ManagerModule",
    ("BusinessProcess", 6): "ObjectModule",
    ("BusinessProcess", 8): "ManagerModule",
    ("Catalog", 0): "ObjectModule",
    ("Catalog", 3): "ManagerModule",
    ("ChartOfCharacteristicTypes", 15): "ObjectModule",
    ("ChartOfCharacteristicTypes", 16): "ManagerModule",
    ("CommonCommand", 2): "CommandModule",
    ("CommonModule", 0): "Module",
    ("CommonForm", 0): "Form",
    ("Constant", 0): "ValueManagerModule",
    ("DataProcessor", 0): "ObjectModule",
    ("DataProcessor", 2): "ManagerModule",
    ("Document", 0): "ObjectModule",
    ("Document", 2): "ManagerModule",
    ("DocumentJournal", 1): "ManagerModule",
    ("Enum", 0): "ManagerModule",
    ("ExchangePlan", 2): "ObjectModule",
    ("ExchangePlan", 3): "ManagerModule",
    ("InformationRegister", 1): "RecordSetModule",
    ("InformationRegister", 2): "ManagerModule",
    ("Report", 0): "ObjectModule",
    ("Report", 2): "ManagerModule",
    ("SettingsStorage", 8): "ManagerModule",
    ("Task", 6): "ObjectModule",
    ("Task", 7): "ManagerModule",
    ("WebService", 0): "Module",
}


def _repair_cp1251_mojibake_text(value: str) -> str:
    """Repair CP1251 text that was decoded as Latin-1 by legacy 1CD readers."""

    raw = str(value or "")
    if not raw:
        return ""
    try:
        repaired = raw.encode("latin1").decode("cp1251")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return raw
    cyrillic_before = sum("\u0400" <= ch <= "\u04ff" for ch in raw)
    cyrillic_after = sum("\u0400" <= ch <= "\u04ff" for ch in repaired)
    return repaired if cyrillic_after > cyrillic_before else raw


def _decode_table_file_payload(data: bytes) -> str:
    if not data:
        return ""
    candidates = [data]
    try:
        candidates.insert(0, zlib.decompress(data, -15))
    except Exception:
        pass
    try:
        candidates.insert(0, zlib.decompress(data))
    except Exception:
        pass
    lossy_fallback = ""
    for candidate in candidates:
        # 1CD table streams are encountered both as UTF-8 and as CP1251.
        # Never publish a replacement-character decode: once ``�`` enters the
        # synthesized XML files, the original source cannot be recovered by
        # the importer or by the semantic index.
        for encoding in ("utf-8-sig", "utf-8"):
            try:
                decoded = candidate.decode(encoding)
                if decoded:
                    return decoded
            except Exception:
                continue
        try:
            return candidate.decode("cp1251")
        except Exception:
            continue

        # Keep a last-resort value for non-source binary payloads only. It is
        # intentionally not selected when a strict text decode is available.
        if not lossy_fallback:
            lossy_fallback = candidate.decode("utf-8", errors="replace")
    return lossy_fallback


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").strip().lower())


def _norm_rel(path: str) -> str:
    rel = str(path or "").replace("\\", "/").lstrip("/")
    rel = posixpath.normpath(rel)
    return "" if rel == "." else rel


def _target_tables_for_object(family: str, name: str) -> List[str]:
    obj_name = str(name or "").strip().lower()
    if not obj_name:
        return []
    if family == "constant":
        return ["data_constants"]
    if family in _CATALOG_LIKE_FAMILIES:
        return [f"data_catalog_{obj_name}"]
    if family in _DOCUMENT_LIKE_FAMILIES:
        return [f"data_document_{obj_name}"]
    if family in _REGISTER_LIKE_FAMILIES:
        return [f"data_reg_{obj_name}"]
    return []


def _read_blob(db: Any, table_name: str, row: Dict[str, Any]) -> bytes:
    match = _BLOB_PTR_RE.match(str(row.get("BINARYDATA") or ""))
    if not match:
        return b""
    return db.read_blob_chain(table_name, int(match.group(1)), int(match.group(2)))


def _read_blob_from_raw(raw: bytes, row: Dict[str, Any]) -> bytes:
    match = _BLOB_PTR_RE.match(str(row.get("BINARYDATA") or ""))
    if not match:
        return b""
    cur = int(match.group(1))
    length = int(match.group(2))
    if cur < 0 or length <= 0 or not raw:
        return b""
    out = bytearray()
    seen: set[int] = set()
    while cur and len(out) < length and cur not in seen:
        seen.add(cur)
        off = cur * 0x100
        if off + 0x100 > len(raw):
            break
        nxt = struct.unpack_from("<I", raw, off)[0]
        chunk_len = struct.unpack_from("<H", raw, off + 4)[0]
        if chunk_len > 250:
            break
        out.extend(raw[off + 6 : off + 6 + chunk_len])
        cur = nxt
    return bytes(out[:length])


def _read_quoted(text: str, start: int) -> tuple[str, int]:
    if start < 0 or start >= len(text) or text[start] != '"':
        return "", start
    out: list[str] = []
    pos = start + 1
    while pos < len(text):
        ch = text[pos]
        if ch == '"':
            return "".join(out), pos + 1
        out.append(ch)
        pos += 1
    return "".join(out), pos


def _parse_config_metadata_header(text: str, uuid: str) -> tuple[str, Dict[str, str]]:
    marker = re.search(r"\{[01],0," + re.escape(uuid) + r"\},", text, re.IGNORECASE)
    if marker is None:
        return "", {}

    name, end = _read_quoted(text, marker.end())
    name = _repair_cp1251_mojibake_text(name).strip()
    window = text[end : end + 1500]
    synonyms: Dict[str, str] = {}
    for lang, value in re.findall(r'"([A-Za-z]{2,3})","([^"]*)"', window):
        lang_key = lang.strip().lower()
        value = _repair_cp1251_mojibake_text(value).strip()
        if lang_key and value and lang_key not in synonyms:
            synonyms[lang_key] = value
    return name, synonyms


def _extract_guid_refs(text: str) -> List[str]:
    seen: set[str] = set()
    refs: List[str] = []
    for guid in _GUID_REF_RE.findall(str(text or "")):
        guid_l = guid.lower()
        if guid_l in seen:
            continue
        seen.add(guid_l)
        refs.append(guid_l)
    return refs


def _extract_params_metadata_index(text: str) -> Dict[str, tuple[str, int, str]]:
    """Read Config metadata identity links from the Params ``*.si`` stream.

    The index is the stable bridge between physical Config GUID rows and their
    logical owner/name.  Child commands often have no standalone base Config
    row, so deriving ownership from display text or module source loses them.
    """

    result: Dict[str, tuple[str, int, str]] = {}
    for child_guid, parent_guid, kind_code, name in _PARAMS_METADATA_ENTRY_RE.findall(
        str(text or "")
    ):
        child = child_guid.lower()
        if child in result:
            continue
        result[child] = (
            parent_guid.lower(),
            int(kind_code),
            _repair_cp1251_mojibake_text(name).strip(),
        )
    return result


def _extract_owned_child_refs(text: str, owner_uuid: str) -> List[str]:
    """Return child metadata refs from the owner's collection prefix.

    In Config serialization, child forms/commands/templates are listed before
    the owner's own named metadata header. GUIDs after that header are ordinary
    property/type references and must not be treated as owned children.
    """

    owner_uuid = str(owner_uuid or "").strip().lower()
    named = _extract_named_objects(str(text or ""))
    owner = next((item for item in named if item.uuid == owner_uuid), None)
    if owner is None:
        return []
    refs: List[str] = []
    seen: set[str] = set()

    # Child collections are serialized as counted GUID groups. Requiring the
    # declared count to match (inside _extract_config_group_members) prevents
    # ordinary type/property references from becoming children.
    for members in _extract_config_group_members(text).values():
        for guid in members:
            if guid != owner_uuid and guid not in seen:
                seen.add(guid)
                refs.append(guid)

    # Some format revisions keep the default child directly in the prefix,
    # outside a counted group.
    for guid in _extract_guid_refs(text[: owner.pos]):
        if guid != owner_uuid and guid not in seen:
            seen.add(guid)
            refs.append(guid)
    return refs


def _owned_child_ref_scores(text: str, owner_uuid: str) -> Dict[str, int]:
    """Return ownership confidence for child refs in a Config owner record."""

    owner_uuid = str(owner_uuid or "").strip().lower()
    named = _extract_named_objects(str(text or ""))
    owner = next((item for item in named if item.uuid == owner_uuid), None)
    if owner is None:
        return {}
    scores: Dict[str, int] = {}
    for members in _extract_config_group_members(text).values():
        for guid in members:
            if guid != owner_uuid:
                scores[guid] = max(scores.get(guid, 0), 1)
    for guid in _extract_guid_refs(text[: owner.pos]):
        if guid != owner_uuid:
            scores[guid] = max(scores.get(guid, 0), 2)
    direct_default = re.match(
        r"\s*,\s*(" + _GUID_RE.pattern[1:-1] + r")",
        text[owner.end_pos : owner.end_pos + 100],
        re.IGNORECASE,
    )
    if direct_default is not None:
        guid = direct_default.group(1).lower()
        if guid != owner_uuid:
            scores[guid] = 3
    return scores


def _collect_standard_subsystem_guid_order(config_rows: List[Dict[str, Any]], config_blob_raw: bytes) -> List[str]:
    """Return GUIDs referenced by the standard subsystem container row."""

    for row in config_rows:
        fn = str(row.get("FILENAME") or "").strip().lower()
        if not _GUID_RE.match(fn):
            continue
        text = _decode_table_file_payload(_read_blob_from_raw(config_blob_raw, row))
        name, _ = _parse_config_metadata_header(text, fn)
        if name != "СтандартныеПодсистемы":
            continue
        return [guid for guid in _extract_guid_refs(text) if guid != fn]
    return []


def _extract_config_group_members(text: str) -> Dict[str, List[str]]:
    """Extract root metadata collection groups from a Config row.

    The configuration root stores top-level metadata as records like
    {<stable collection uuid>, <count>, <object uuid>...}.  DBNames only covers
    objects with physical tables, so these groups are required for reports,
    data processors and common metadata.
    """

    groups: Dict[str, List[str]] = {}
    for match in _CONFIG_GROUP_RE.finditer(str(text or "")):
        group_guid = match.group(1).lower()
        try:
            declared_count = int(match.group(2))
        except Exception:
            continue
        members = [guid.lower() for guid in _GUID_REF_RE.findall(match.group(3))]
        if declared_count <= 0 or len(members) != declared_count:
            continue
        groups.setdefault(group_guid, members)
    return groups


def _collect_config_group_members(config_rows: List[Dict[str, Any]], config_blob_raw: bytes) -> Dict[str, List[str]]:
    best: Dict[str, List[str]] = {}
    best_score = 0
    for row in config_rows:
        fn = str(row.get("FILENAME") or "").strip().lower()
        if not _GUID_RE.match(fn):
            continue
        text = _decode_table_file_payload(_read_blob_from_raw(config_blob_raw, row))
        groups = _extract_config_group_members(text)
        score = (len(groups) * 10) + sum(len(members) for members in groups.values())
        if score > best_score:
            best = groups
            best_score = score
    return best


def _infer_config_group_kind(
    *,
    group_guid: str,
    members: List[str],
    primary_by_guid: Dict[str, tuple[OneCDMetadataKind, int]],
    read_base_text: Callable[[str], str],
    suffix_texts_for_guid: Callable[[str], Dict[int, str]],
) -> Optional[OneCDMetadataKind]:
    primary_counter: Counter[OneCDMetadataKind] = Counter()
    for member_guid in members:
        known = primary_by_guid.get(member_guid)
        if known is not None:
            primary_counter[known[0]] += 1
    if primary_counter:
        return primary_counter.most_common(1)[0][0]

    platform_kind = ONECD_PLATFORM_GROUP_KIND_FALLBACK.get(group_guid)
    if platform_kind is not None:
        return platform_kind

    sample_guids = list(members[:128])
    sample_count = max(len(sample_guids), 1)
    suffix_presence: Counter[int] = Counter()
    bsl_presence: Counter[int] = Counter()
    form_bsl_count = 0
    picture_name_count = 0
    child_kinds: Counter[str] = Counter()

    for member_guid in sample_guids:
        member_text = read_base_text(member_guid)
        member_name, _ = _parse_config_metadata_header(member_text, member_guid)
        if _looks_like_common_picture_name(member_name):
            picture_name_count += 1

        member_suffixes = suffix_texts_for_guid(member_guid)
        for suffix_num, suffix_text in member_suffixes.items():
            suffix_presence[suffix_num] += 1
            bsl_text = _extract_bsl_source(suffix_text)
            if not bsl_text:
                continue
            bsl_presence[suffix_num] += 1
            if suffix_num == 0 and _looks_like_form_module_text(bsl_text):
                form_bsl_count += 1

        for child_guid in _extract_guid_refs(member_text):
            if child_guid == member_guid or child_guid in primary_by_guid:
                continue
            child_text = read_base_text(child_guid)
            child_name, _ = _parse_config_metadata_header(child_text, child_guid)
            named_child = None
            if not child_name:
                named_by_uuid = {item.uuid: item for item in _extract_named_objects(member_text)}
                named_child = named_by_uuid.get(child_guid)
                if named_child is not None:
                    child_name = named_child.name
            if not child_name:
                continue
            child_kind = _classify_owner_child(child_name, suffix_texts_for_guid(child_guid))
            if child_kind:
                child_kinds[child_kind] += 1

    if bsl_presence[2] >= sample_count * 0.5 and bsl_presence[0] < sample_count * 0.25:
        return ONECD_METADATA_KIND_MAP["CommonCommand"]
    if form_bsl_count >= sample_count * 0.45:
        return ONECD_METADATA_KIND_MAP["CommonForm"]
    if child_kinds:
        form_command = child_kinds["form"] + child_kinds["command"]
        template = child_kinds["template"]
        if form_command >= template:
            return ONECD_METADATA_KIND_MAP["DataProcessor"]
        return ONECD_METADATA_KIND_MAP["Report"]
    if bsl_presence[0] >= sample_count * 0.5 and bsl_presence[2] < sample_count * 0.25:
        return ONECD_METADATA_KIND_MAP["CommonModule"]
    if suffix_presence[0] >= sample_count * 0.5 and bsl_presence[0] < sample_count * 0.2:
        return ONECD_METADATA_KIND_MAP["CommonTemplate"]
    if picture_name_count >= sample_count * 0.35:
        return ONECD_METADATA_KIND_MAP["CommonPicture"]
    return None


def _display_title(name: str, synonyms: Dict[str, str]) -> str:
    for lang in ("uk", "en"):
        value = str(synonyms.get(lang) or "").strip()
        if value:
            return value
    return str(name or "").strip()


_SUBSYSTEM_PREFIX_RE = re.compile(r"^\s*\d+\s+(.+?)\s*$")


def _normalize_subsystem_label(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = _SUBSYSTEM_PREFIX_RE.match(text)
    if match is not None:
        return match.group(1).strip()
    return text


def _looks_like_bsl_module(text: str) -> bool:
    return bool(_extract_bsl_source(text))


def _looks_like_object_module_text(text: str) -> bool:
    sample = _extract_bsl_source(text)
    if not sample:
        return False
    return any(marker in sample for marker in _OBJECT_MODULE_HINTS)


def _looks_like_form_module_text(text: str) -> bool:
    sample = _extract_bsl_source(text)
    if not sample:
        return False
    return any(marker in sample for marker in _FORM_MODULE_HINTS)


def _select_primary_module_texts(suffix_texts: List[str]) -> tuple[str, str]:
    bsl_texts = [_extract_bsl_source(text) for text in suffix_texts]
    bsl_texts = [text for text in bsl_texts if text]
    if not bsl_texts:
        return "", ""

    object_text = next((text for text in bsl_texts if _looks_like_object_module_text(text)), "")
    form_text = next((text for text in bsl_texts if _looks_like_form_module_text(text)), "")

    if not object_text:
        object_text = bsl_texts[0]
    if not form_text:
        form_text = next((text for text in bsl_texts if text != object_text), object_text)

    return object_text, form_text


def _score_configuration_root_module_text(module_file: str, text: str) -> int:
    sample = _extract_bsl_source(text)
    if not sample:
        return 0

    score = 0
    for marker, weight in _CONFIGURATION_ROOT_MODULE_HINTS.get(module_file, ()):
        if marker in sample:
            score += weight
    for marker, weight in _CONFIGURATION_ROOT_MODULE_PENALTIES:
        if marker in sample:
            score -= weight

    if module_file == "ManagedApplicationModule.bsl":
        if "#Область ПрограммныйИнтерфейс" in sample:
            score += 4
        if "Функция ПараметрыРаботыКлиентаПриЗапуске" in sample:
            score += 3
    elif module_file == "SessionModule.bsl":
        if "#Область СлужебныйПрограммныйИнтерфейс" in sample:
            score += 4
        if "Функция УстановкаПараметровСеанса" in sample:
            score += 4
    elif module_file == "ExternalConnectionModule.bsl":
        if "#Если Сервер Или ТолстыйКлиентОбычноеПриложение Или ВнешнееСоединение Тогда" in sample:
            score += 4
        if "ПараметрыСеанса.ТекущийВнешнийПользователь" in sample:
            score += 4
    elif module_file == "OrdinaryApplicationModule.bsl":
        if "#Если ОбычноеПриложение Тогда" in sample:
            score += 6
        if "#Область СлужебныеПроцедурыИФункции" in sample:
            score += 2

    return score


def _select_configuration_root_module_texts(candidate_texts: Dict[str, str]) -> Dict[str, str]:
    selected: Dict[str, str] = {}
    used_candidates: set[str] = set()

    normalized_candidates = {
        key: _extract_bsl_source(text)
        for key, text in candidate_texts.items()
        if _extract_bsl_source(text)
    }
    if not normalized_candidates:
        return selected

    for module_file in _CONFIGURATION_ROOT_MODULE_FILES:
        best_key = ""
        best_text = ""
        best_score = -10**9
        for key, text in normalized_candidates.items():
            if key in used_candidates:
                continue
            score = _score_configuration_root_module_text(module_file, text)
            if score > best_score or (score == best_score and len(text) > len(best_text)):
                best_key = key
                best_text = text
                best_score = score
        if best_key:
            used_candidates.add(best_key)
            selected[module_file] = best_text

    return selected


def _extract_bsl_candidates(text: str, *, serialized_container: bool = False) -> list[str]:
    sample = str(text or "")
    if not sample.strip():
        return []

    # Some 1CD table-file streams contain a truncated text preview followed by
    # a binary marker and the complete module. Treat every marker boundary as a
    # possible start, then prefer a structurally balanced module. Taking only
    # the first BSL token silently concatenates both copies and corrupts code.
    candidates: list[str] = []
    fragments = [sample]
    boundaries = _serialized_text_boundary_spans(sample)
    if boundaries:
        joined_parts: list[str] = []
        joined_offset = 0
        for boundary_start, boundary_end in boundaries:
            joined_parts.append(sample[joined_offset:boundary_start])
            joined_offset = boundary_end
        joined_parts.append(sample[joined_offset:])
        fragments.append("".join(joined_parts))
        fragments.append(sample[:boundaries[0][0]])
        for index, (_, boundary_end) in enumerate(boundaries):
            next_start = boundaries[index + 1][0] if index + 1 < len(boundaries) else len(sample)
            fragments.append(sample[boundary_end:next_start])

    for fragment in fragments:
        first_start = _BSL_CODE_START_RE.search(fragment)
        if first_start is None:
            continue
        candidate_starts = [first_start.start()]

        for candidate_start in dict.fromkeys(candidate_starts):
            candidate = fragment[candidate_start:].lstrip("\ufeff\r\n")
            candidate = _normalize_bsl_candidate(candidate, serialized_container=serialized_container)
            if candidate and candidate not in candidates:
                candidates.append(candidate)

    return candidates


def _extract_bsl_source(text: str, *, serialized_container: bool = False) -> str:
    sample = str(text or "")
    if not sample.strip():
        return ""

    candidates = _extract_bsl_candidates(sample, serialized_container=serialized_container)
    if candidates:
        selected = max(candidates, key=_score_bsl_source_candidate)
        declarations = len(_BSL_DECLARATION_RE.findall(selected))
        endings = len(_BSL_DECLARATION_END_RE.findall(selected))
        if declarations != endings:
            return ""
        return selected

    trimmed = sample.strip()
    if trimmed.startswith(("//", "/*")) and (";" in trimmed or "\n" in trimmed):
        return sanitize_imported_module_text(trimmed)
    if trimmed.startswith(("#Если", "#If", "#Область", "#Region", "&На", "&On", "Процедура", "Procedure", "Функция", "Функція", "Function", "Перем", "Змін", "Var")):
        return sanitize_imported_module_text(trimmed)
    return ""


def _normalize_bsl_candidate(candidate: str, *, serialized_container: bool) -> str:
    if serialized_container:
        serialized_tail = _SERIALIZED_BSL_TAIL_RE.search(candidate)
        attached_tail = _SERIALIZED_BSL_ATTACHED_TAIL_RE.search(candidate)
        if attached_tail is not None and (
            serialized_tail is None or attached_tail.start("tail") < serialized_tail.start()
        ):
            candidate = candidate[:attached_tail.start("tail")]
            serialized_tail = attached_tail
        if serialized_tail is not None:
            if attached_tail is None or serialized_tail is not attached_tail:
                candidate = candidate[:serialized_tail.start()]
        # Form modules are quoted values inside serialized metadata. Remove
        # exactly the extra escaping layer only for that known container.
        candidate = candidate.replace('""', '"')
    # A Config table-file may append a broken preview after a complete source
    # stream.  Prefer the first balanced region ending when the following
    # bytes already contain decoder replacement characters.  Waiting for the
    # last declaration in that case keeps a duplicate ``EndProcedure`` and
    # makes an otherwise valid command module look structurally unbalanced.
    for region_end in _BSL_REGION_END_RE.finditer(candidate):
        prefix = candidate[:region_end.end()]
        suffix = candidate[region_end.end():]
        if (
            _INVALID_SOURCE_CHAR_RE.search(suffix) is not None
            and len(_BSL_DECLARATION_RE.findall(prefix))
            == len(_BSL_DECLARATION_END_RE.findall(prefix))
        ):
            candidate = prefix
            break

    region_ends = list(_BSL_REGION_END_RE.finditer(candidate))
    if region_ends:
        last_region_end = region_ends[-1].end()
        trailing = candidate[last_region_end:]
        if _BSL_DECLARATION_RE.search(trailing) is None:
            keep = 0
            offset = 0
            for line in trailing.splitlines(keepends=True):
                if not _BSL_ALLOWED_TERMINAL_SUFFIX_LINE_RE.match(line):
                    break
                offset += len(line)
                keep = offset
            if keep != len(trailing):
                candidate = candidate[:last_region_end] + trailing[:keep]
    candidate = _trim_serialized_tail_after_last_declaration(candidate)
    return sanitize_imported_module_text(candidate.rstrip())


def _validated_bsl_source(text: str, *, serialized_container: bool = False) -> str:
    """Return parser-valid BSL, recovering a complete stream after a bad preview."""

    candidates = _extract_bsl_candidates(text, serialized_container=serialized_container)
    if not candidates:
        candidate = _extract_bsl_source(text, serialized_container=serialized_container)
        candidates = [candidate] if candidate else []

    valid: list[str] = []
    multiple_streams = len(candidates) > 1
    for candidate in candidates:
        declarations = len(_BSL_DECLARATION_RE.findall(candidate))
        endings = len(_BSL_DECLARATION_END_RE.findall(candidate))
        if declarations != endings:
            continue

        requires_validation = multiple_streams or _requires_parser_validation(candidate)
        if not requires_validation or _is_parser_valid_bsl(candidate):
            valid.append(candidate)
            continue

        recovery_prefix = candidate[:4096]
        starts = list(_BSL_RECOVERY_START_RE.finditer(recovery_prefix))
        for match in starts[1:]:
            alternative = _normalize_bsl_candidate(
                candidate[match.start():],
                serialized_container=serialized_container,
            )
            alternative_declarations = len(_BSL_DECLARATION_RE.findall(alternative))
            alternative_endings = len(_BSL_DECLARATION_END_RE.findall(alternative))
            if alternative_declarations != alternative_endings:
                continue
            if _is_parser_valid_bsl(alternative):
                valid.append(alternative)

    return max(dict.fromkeys(valid), key=_score_bsl_source_candidate) if valid else ""


def _best_effort_bsl_source(text: str, *, serialized_container: bool = False) -> str:
    """Preserve a module even when its source currently fails DSL validation."""

    return _validated_bsl_source(
        text, serialized_container=serialized_container
    ) or _extract_bsl_source(text, serialized_container=serialized_container)


def _requires_parser_validation(text: str) -> bool:
    declaration_names = [
        name.casefold() for name in _BSL_DECLARATION_NAME_RE.findall(text)
    ]
    if not declaration_names or len(declaration_names) != len(set(declaration_names)):
        return True
    first_declaration = _BSL_DECLARATION_RE.search(text)
    if first_declaration is not None:
        for line in text[:first_declaration.start()].splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(("//", "/*", "*", "*/", "#", "&")):
                continue
            if re.match(r"(?i)^(?:Перем|Змін|Var)\b", stripped):
                continue
            return True
    for line in _BSL_DECLARATION_LINE_RE.findall(text):
        if "(" not in line or ")" not in line:
            return True
    return False


def _is_parser_valid_bsl(text: str) -> bool:
    from src.dsl.languages import MIXED_PROFILE
    from src.dsl.parser import parse

    program, diagnostics = parse(text, MIXED_PROFILE)
    return program is not None and not any(item.severity == "error" for item in diagnostics)


def _trim_serialized_tail_after_last_declaration(text: str) -> str:
    """Drop a foreign preview appended after a complete BSL module."""

    endings = list(_BSL_DECLARATION_END_LINE_RE.finditer(text))
    if not endings:
        return text

    last = endings[-1]
    suffix = text[last.end():]
    if not suffix.strip():
        return text

    keep = 0
    offset = 0
    for line in suffix.splitlines(keepends=True):
        if not _BSL_ALLOWED_TERMINAL_SUFFIX_LINE_RE.match(line):
            break
        offset += len(line)
        keep = offset

    if keep == len(suffix):
        return text

    terminal_line = text[last.start():last.end()]
    terminal_line = re.sub(r'"[ \t]*,[ \t]*(?=\r?$)', "", terminal_line)
    return text[:last.start()] + terminal_line + suffix[:keep]


def _is_serialized_text_boundary(line: str) -> bool:
    """Return true for binary table-file marker lines embedded between text streams."""

    if _INVALID_SOURCE_CHAR_RE.search(line) is None:
        return False
    printable = _INVALID_SOURCE_CHAR_RE.sub("", line).casefold()
    return "text" in printable


def _serialized_text_boundary_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        line_end = offset + len(line)
        if _is_serialized_text_boundary(line):
            spans.append((offset, line_end))
        offset = line_end
    return spans


def _score_bsl_source_candidate(text: str) -> tuple[int, int, int, int, int, int]:
    declarations = len(_BSL_DECLARATION_RE.findall(text))
    endings = len(_BSL_DECLARATION_END_RE.findall(text))
    imbalance = abs(declarations - endings)
    balanced = int(declarations == endings)
    clean = int(_INVALID_SOURCE_CHAR_RE.search(text) is None)
    names = [match.casefold() for match in _BSL_DECLARATION_NAME_RE.findall(text)]
    duplicate_declarations = len(names) - len(set(names))
    return balanced, -duplicate_declarations, -imbalance, min(declarations, endings), clean, len(text)


def _looks_like_common_module_name(name: str) -> bool:
    normalized = str(name or "").strip()
    if not normalized:
        return False
    if normalized.startswith(("Форма", "Макет", "Подсистема", "Роль")):
        return False
    return any(normalized.startswith(hint) or hint in normalized for hint in _COMMON_MODULE_NAME_HINTS)


def _looks_like_common_form_name(name: str) -> bool:
    normalized = str(name or "").strip()
    if not normalized:
        return False
    return normalized.startswith(("Форма", "ОсновнаяФорма"))


def _looks_like_common_picture_name(name: str) -> bool:
    normalized = str(name or "").strip()
    if not normalized:
        return False
    return normalized.startswith(("Пиктограмма", "Картинка")) or "Картинка" in normalized


def _looks_like_bsl_or_help_text(text: str) -> bool:
    sample = str(text or "").strip()
    if not sample:
        return False
    if _looks_like_bsl_module(sample):
        return True
    if "<html" in sample.lower() or "doctype html" in sample.lower():
        return True
    return False


_SUBSYSTEM_HELP_PAGE_RE = re.compile(r'"([^"]+)"\s*,\s*\{#base64:([^}]*)\}', re.S)


def _extract_subsystem_help_pages(text: str) -> Dict[str, str]:
    sample = str(text or "")
    pages: Dict[str, str] = {}
    seen: set[str] = set()
    for page_name, encoded in _SUBSYSTEM_HELP_PAGE_RE.findall(sample):
        page_key = str(page_name or "").strip()
        if not page_key or page_key in seen:
            continue
        seen.add(page_key)
        try:
            raw_html = base64.b64decode(re.sub(r"\s+", "", encoded), validate=False)
            page_text = raw_html.decode("utf-8-sig", errors="replace").strip()
        except Exception:
            continue
        if page_text:
            pages[page_key] = page_text
    return pages


def _subsystem_help_xml_bytes(page_names: List[str]) -> bytes:
    pages = [
        f"    <Page>{html.escape(str(page or '').strip())}</Page>"
        for page in page_names
        if str(page or "").strip()
    ]
    body = "\n".join(pages)
    if body:
        body += "\n"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Help xmlns="http://v8.1c.ru/8.3/xcf/extrnprops" '
        'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.20">\n'
        f"{body}"
        '</Help>\n'
    ).encode("utf-8")


def _subsystem_command_interface_xml_bytes(obj: OneCDMetadataObject) -> bytes:
    subsystem_entries = [
        f"    <Subsystem>Subsystem.{html.escape(obj.name)}.Subsystem.{html.escape(str(child).strip())}</Subsystem>"
        for child in obj.child_subsystems
        if str(child or "").strip()
    ]
    body = ""
    if subsystem_entries:
        body = "  <SubsystemsOrder>\n" + "\n".join(subsystem_entries) + "\n  </SubsystemsOrder>\n"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<CommandInterface xmlns="http://v8.1c.ru/8.3/xcf/extrnprops" '
        'xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" '
        'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.20">\n'
        f"{body}"
        '</CommandInterface>\n'
    ).encode("utf-8")


def _metadata_xml_bytes(
    obj: OneCDMetadataObject,
    *,
    child_subsystems: List[str] | None = None,
    content_refs: List[str] | None = None,
) -> bytes:
    if child_subsystems is None:
        child_subsystems = list(obj.child_subsystems or [])
    if content_refs is None:
        content_refs = list(obj.content_refs or [])

    name = html.escape(obj.name or f"Object_{obj.uuid[:8]}")
    title = html.escape(obj.title or obj.name or f"Object {obj.uuid[:8]}")
    uuid = html.escape(obj.uuid)
    xml_tag = html.escape(obj.xml_tag)

    synonyms = dict(obj.synonyms)
    if "uk" not in synonyms and obj.title:
        synonyms["uk"] = obj.title
    if "en" not in synonyms:
        synonyms["en"] = obj.name or obj.title or f"Object_{obj.uuid[:8]}"

    synonym_items = []
    for lang in ("uk", "en"):
        value = str(synonyms.get(lang) or "").strip()
        if not value:
            continue
        synonym_items.append(
            "      <v8:item>\n"
            f"        <v8:lang>{html.escape(lang)}</v8:lang>\n"
            f"        <v8:content>{html.escape(value)}</v8:content>\n"
            "      </v8:item>"
        )
    synonym_xml = "\n".join(synonym_items)
    child_xml = ""
    if child_subsystems:
        child_items = [
            f"      <Subsystem>{html.escape(str(child or '').strip())}</Subsystem>"
            for child in child_subsystems
            if str(child or "").strip()
        ]
        if child_items:
            child_xml = "    <ChildObjects>\n" + "\n".join(child_items) + "\n    </ChildObjects>\n"

    content_xml = ""
    if content_refs:
        content_items = [
            f"      <xr:Item xsi:type=\"xr:MDObjectRef\">{html.escape(str(ref or '').strip())}</xr:Item>"
            for ref in content_refs
            if str(ref or "").strip()
        ]
        if content_items:
            content_xml = "    <Content>\n" + "\n".join(content_items) + "\n    </Content>\n"

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" '
        'xmlns:v8="http://v8.1c.ru/8.1/data/core" '
        'xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
        f'  <{xml_tag} uuid="{uuid}">\n'
        "    <Properties>\n"
        f"      <Name>{name}</Name>\n"
        f"      <Presentation>{title}</Presentation>\n"
        "      <Synonym>\n"
        f"{synonym_xml}\n"
        "      </Synonym>\n"
        f"{content_xml}"
        "    </Properties>\n"
        f"{child_xml if child_xml else '    <ChildObjects/>\n'}"
        f"  </{xml_tag}>\n"
        "</MetaDataObject>\n"
    ).encode("utf-8")


def _merge_unique_texts(*groups: List[str]) -> List[str]:
    seen: set[str] = set()
    merged: List[str] = []
    for group in groups:
        for item in group:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            merged.append(text)
    return merged


def _sync_subsystem_metadata_links(
    subsystem_nodes: Dict[str, OneCDMetadataObject],
    subsystem_children: Dict[str, List[str]],
    subsystem_content_refs_by_guid: Dict[str, List[str]],
) -> None:
    for guid, node in subsystem_nodes.items():
        child_names = _merge_unique_texts(
            list(node.child_subsystems or []),
            [subsystem_nodes[child_guid].name for child_guid in subsystem_children.get(guid, []) if child_guid in subsystem_nodes],
        )
        content_refs = _merge_unique_texts(
            list(node.content_refs or []),
            list(subsystem_content_refs_by_guid.get(guid, []) or []),
        )
        object.__setattr__(node, "child_subsystems", child_names)
        object.__setattr__(node, "content_refs", content_refs)


def _module_rel_for_kind(obj: OneCDMetadataObject, module_kind: str) -> str:
    prefix = _norm_rel(f"{obj.folder}/{obj.name}")
    if module_kind == "Module":
        return _norm_rel(f"{prefix}/Ext/Module.bsl")
    if module_kind == "Form":
        return _norm_rel(f"{prefix}/Ext/Form/Module.bsl")
    return _norm_rel(f"{prefix}/Ext/{module_kind}.bsl")


def _child_metadata_xml_bytes(uuid: str, name: str, title: str, synonyms: Dict[str, str], xml_tag: str) -> bytes:
    return _metadata_xml_bytes(
        OneCDMetadataObject(
            uuid=uuid,
            dbname_kind=xml_tag,
            folder="",
            xml_tag=xml_tag,
            family=xml_tag.lower(),
            dump_root=xml_tag,
            name=name,
            title=title,
            synonyms=synonyms,
            order=0,
            origin=f"1cd://Config/{uuid}",
        )
    )


def _looks_like_owner_form(name: str, suffix_text_by_num: Dict[int, str]) -> bool:
    form_container = str(suffix_text_by_num.get(0, "") or "")
    # Managed-form serialization has a stable root `{3,{38,...}`. Relying on
    # the child name or on form-specific calls in its module loses short forms
    # such as "ФайлСуществует" and every intentionally empty FormModule.
    if re.match(r"^\s*\{3\s*,\s*\{38\s*,", form_container):
        return True
    bsl = _extract_bsl_source(form_container)
    return bool(bsl and _looks_like_form_module_text(bsl))


def _classify_owner_child(name: str, suffix_text_by_num: Dict[int, str]) -> str:
    if _looks_like_owner_form(name, suffix_text_by_num):
        return "form"
    if _extract_bsl_source(suffix_text_by_num.get(2, "")):
        return "command"
    if 0 in suffix_text_by_num:
        return "template"
    return ""


_SUBSYSTEM_CHILD_SKIP_PREFIXES = (
    "Панель",
    "Дополнительные",
    "Менеджер",
    "Подсистема",
    "Раздел",
    "Настройки",
    "Компонента",
    "Драйвер",
    "Обработчики",
    "Форма",
    "РабочееМесто",
)


# Direct .1CD dumps for the target configuration expose several top-level
# subsystem roots only through Config text, not DBNames. Keep a targeted
# fallback so they are not misclassified as role/common-module/catalog rows.
_SUBSYSTEM_ROOT_NAME_HINTS = {
    "Администрирование",
    "БанкИКассаБазовая",
    "Взаимодействия",
    "Глоссарий",
    "ЗакупкиБазовая",
    "ЗапасыИЗакупки",
    "ИнтеграцияС1СДокументооборотом",
    "ИнтернетПоддержкаПользователей",
    "Маркетинг",
    "НастройкиБазовая",
    "НормативноСправочнаяИнформация",
    "Органайзер",
    "ОрганизацияБазовая",
    "ОтчетыБазовая",
    "ОтчетыИМониторинг",
    "ПодключаемоеОборудование",
    "Продажи",
    "ПродажиБазовая",
    "РаботаВМоделиСервиса",
    "РегламентированнаяОтчетность",
    "РегламентированныйУчет",
    "СинхронизацияДанных",
    "Склад",
    "СкладБазовая",
    "СтандартныеПодсистемы",
    "УправлениеТорговлей",
    "Финансы",
}

_SUBSYSTEM_CHILD_NAME_HINTS: Dict[str, tuple[str, ...]] = {
    "Администрирование": ("НастройкаПараметровСистемы", "НастройкаИнтеграции"),
    "БанкИКассаБазовая": ("БанкБазовая", "КассаБазовая"),
    "ЗакупкиБазовая": (
        "ВедениеЗаказовБазовая",
        "ЗакупкиИВозвратыБазовая",
        "РасчетыСПоставщикамиБазов",
    ),
    "ЗапасыИЗакупки": (
        "Запасы",
        "РаботаСПоставщиками",
        "ЗакупкиИВозврат",
        "КонтрольРасчетовСПоставщиками",
        "УправлениеЗапасами",
        "УсловияЗакупок",
        "КомиссионныеЗакупки",
        "ПередачаВПереработку",
        "ВнутреннееТовародвижение",
        "КонтрольПереработкиСырьяУПереработчиков",
        "МногооборотнаяТара",
    ),
    "Маркетинг": (
        "АнализКлиентскойБазы",
        "Сегментация",
        "КонкурентнаяРазведка",
        "ПравилаПродаж",
        "Ценообразование",
        "АнализСпросаИИнтереса",
        "МаркетинговыеМероприятия",
        "Ассортимент",
        "Планирование",
    ),
    "НормативноСправочнаяИнформация": (
        "Партнеры",
        "Номенклатура",
        "Предприятие",
        "ФизическиеЛица",
        "БазовыеКлассификаторы",
    ),
    "Органайзер": ("РассылкиИОповещения",),
    "ОрганизацияБазовая": ("АналитикаБазовая",),
    "ОтчетыБазовая": (
        "ПродажиБазовая",
        "ПродажиПродажиИВозвратыБазовая",
        "ПродажиРозничныеПродажиБазовая",
        "ПродажиРасчетыСКлиентамиБазовая",
        "ЗакупкиБазовая",
        "ЗакупкиЗакупкиИВозвратыБазовая",
        "ЗакупкиРасчетыСПоставщикамиБазовая",
        "СкладБазовая",
        "БанкИКассаБазовая",
        "УчетНДСБазовая",
        "ФинансовыйРезультатБазовая",
    ),
    "ОтчетыИМониторинг": ("ЦелевыеПоказатели", "Отчеты"),
    "ПодключаемоеОборудование": (
        "СканерыШтрихкода",
        "СчитывателиМагнитныхКарт",
        "ФискальныеРегистраторы",
        "ДисплеиПокупателя",
        "ТерминалыСбораДанных",
        "ЭквайринговыеТерминалы",
        "ЭлектронныеВесы",
        "ВесыСПечатьюЭтикеток",
        "ККМOffline",
    ),
    "Продажи": (
        "ПроведениеСделок",
        "УправлениеТорговымиПредставителями",
        "ТорговыеПредставители",
        "ВедениеЗаказовКлиентов",
        "Претензии",
        "ПродажиИВозвраты",
        "ОптовыеПродажи",
        "КомиссионныеПродажи",
        "РозничныеПродажи",
        "КонтрольПереработкиСырьяДавальцев",
        "КонтрольРасчетовСКлиентами",
        "МногооборотнаяТара",
        "КонтрольКачестваОбслуживанияКлиентов",
        "КонтрольВыполненияУсловийПродаж",
        "МобильноеПриложениеЗаказыКлиентов",
        "ПриемВПереработку",
    ),
    "ПродажиБазовая": (
        "ВедениеЗаказовКлиентовБазовая",
        "ПродажиИВозвратыБазовая",
        "РозничныеПродажиБазовая",
        "РасчетыСКлиентамиБазовая",
    ),
    "РаботаВМоделиСервиса": (
        "РаботаВМоделиСервисаОбщиеНастройки",
        "РаботаВМоделиСервисаОбщаяНСИ",
    ),
    "РегламентированнаяОтчетность": (
        "БухгалтерскаяОтчетность",
        "НалоговаяОтчетность",
        "ОтчетностьВФонды",
        "ОтчетностьПоФизлицам",
        "ОтчетностьПрочая",
        "Справки",
        "СтатистическаяОтчетность",
    ),
    "РегламентированныйУчет": ("Отчетность", "ПродажиМеждуОрганизациями", "УчетЕдиногоНалога", "УчетНДС"),
    "Склад": (
        "СкладскиеОперации",
        "УправлениеДоставкой",
        "ВнутреннееТовародвижение",
        "ИзлишкиНедостачиПорчи",
        "ЗапасыИСкладскиеОперации",
        "УправлениеСкладом",
        "ТМЦВЭксплуатации",
    ),
    "СкладБазовая": ("ИзлишкиИНедостачиБазовая", "ВнутреннееТовародвижениеБазовая"),
    "СтандартныеПодсистемы": (
        "АнализЖурналаРегистрации",
        "БазоваяФункциональность",
        "Банки",
        "БизнесПроцессыИЗадачи",
        "Валюты",
        "ВариантыОтчетов",
        "ВерсионированиеОбъектов",
        "Взаимодействия",
        "ГрафикиРаботы",
        "ГрупповоеИзменениеОбъектов",
        "ДатыЗапретаИзменения",
        "ДополнительныеОтчетыИОбработки",
        "ЗавершениеРаботыПользователей",
        "ЗаметкиПользователя",
        "ЗапретРедактированияРеквизитовОбъектов",
        "ИнформацияПриЗапуске",
        "КалендарныеГрафики",
        "КонтактнаяИнформация",
        "КонтрольДинамическогоОбновленияКонфигурации",
        "НапоминанияПользователя",
        "НастройкаПорядкаЭлементов",
        "НастройкиПрограммы",
        "ОбменДанными",
        "ОбновлениеВерсииИБ",
        "ОбновлениеКонфигурации",
        "Организации",
        "ОценкаПроизводительности",
        "Печать",
        "ПолнотекстовыйПоиск",
        "ПолучениеФайловИзИнтернета",
        "Пользователи",
        "ПрефиксацияОбъектов",
        "ПрисоединенныеФайлы",
        "ПроверкаЛегальностиПолученияОбновления",
        "РаботаВМоделиСервиса",
        "РаботаСПочтовымиСообщениями",
        "РаботаСФайлами",
        "РассылкаОтчетов",
        "РегламентныеЗадания",
        "РезервноеКопированиеИБ",
        "Свойства",
        "СтруктураПодчиненности",
        "ТекущиеДела",
        "УдаленноеАдминистрирование",
        "УправлениеДоступом",
        "УправлениеИтогамиИАгрегатами",
        "ФайловыеФункции",
        "ЭлектроннаяПодпись",
    ),
    "Финансы": (
        "ПланированиеИКонтрольДенежныхСредств",
        "ДенежныеСредства",
        "Эквайринг",
        "ПрочиеРасчеты",
        "НастройкаАналитики",
        "КредитыИДепозиты",
        "СебестоимостьЗапасов",
        "ФинансовыйРезультат",
    ),
}


def _looks_like_subsystem_child(name: str, suffix_text_by_num: Dict[int, str]) -> bool:
    label = str(name or "").strip()
    if not label:
        return False
    child_kind = _classify_owner_child(label, suffix_text_by_num)
    if child_kind in {"form", "command"}:
        return False
    if label.startswith("Отчет") and not label.startswith("Отчеты"):
        return False
    if any(label.startswith(prefix) for prefix in _SUBSYSTEM_CHILD_SKIP_PREFIXES):
        return False
    return True


def _config_dump_info_bytes(
    objects: List[OneCDMetadataObject],
    extra_entries: List[tuple[str, str]] | None = None,
) -> bytes:
    rows = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<ConfigDumpInfo xmlns="http://v8.1c.ru/8.3/xcf/dumpinfo">',
        "  <MetadataInfo>",
    ]
    for obj in objects:
        name = html.escape(f"{obj.dump_root}.{obj.name}")
        dump_id = html.escape(obj.uuid)
        rows.append(f'    <Metadata name="{name}" id="{dump_id}"/>')
    for name, dump_id in extra_entries or []:
        if not name or not dump_id:
            continue
        rows.append(f'    <Metadata name="{html.escape(name)}" id="{html.escape(dump_id)}"/>')
    rows.extend(["  </MetadataInfo>", "</ConfigDumpInfo>", ""])
    return "\n".join(rows).encode("utf-8")


class OneCDConfigSource:
    """In-memory 1C XMLConf-like source synthesized from a live 1Cv8.1CD file.

    The source intentionally exposes only metadata that can be read safely from
    DBNames plus Config table files. It synthesizes common/object module assets
    from the Config suffix rows, while rich form bodies and layouts still require
    a full XMLConf dump. This is enough for a direct Configurator tree over a
    production .1CD without manual XML export.
    """

    def __init__(self, onecd_path: str | Path) -> None:
        self.onecd_path = Path(onecd_path)
        self._files: Optional[Dict[str, bytes]] = None
        self._objects: Optional[List[OneCDMetadataObject]] = None

    def __enter__(self) -> "OneCDConfigSource":
        self._ensure_loaded()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def list_files(self) -> List[str]:
        self._ensure_loaded()
        return sorted((self._files or {}).keys(), key=str.lower)

    def read_bytes(self, rel_path: str) -> bytes:
        self._ensure_loaded()
        rel = str(rel_path or "").replace("\\", "/").lstrip("/")
        files = self._files or {}
        if rel not in files:
            raise FileNotFoundError(rel)
        return files[rel]

    def metadata_objects(self) -> List[OneCDMetadataObject]:
        self._ensure_loaded()
        return list(self._objects or [])

    def metadata_catalog(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for obj in self.metadata_objects():
            out.append(
                {
                    "family": obj.family,
                    "name": obj.name,
                    "slug": _slug(obj.name),
                    "source_path": obj.origin,
                    "target_tables": _target_tables_for_object(obj.family, obj.name),
                    "src_uuid": obj.uuid,
                    "source_kind": "1cd",
                    "dbname_kind": obj.dbname_kind,
                    "dbname_order": int(obj.dbname_order or 0),
                    "parent_guid": obj.parent_guid,
                    "tree_path": obj.tree_path,
                    "is_virtual": bool(obj.is_virtual),
                    "virtual_reason": obj.virtual_reason,
                }
            )
        return out

    def _ensure_loaded(self) -> None:
        if self._files is not None and self._objects is not None:
            return
        objects, extra_files, dump_info_entries = self._load_metadata_objects()
        files: Dict[str, bytes] = {"ConfigDumpInfo.xml": _config_dump_info_bytes(objects, dump_info_entries)}
        for rel, data in extra_files.items():
            rel_n = _norm_rel(rel)
            if not rel_n:
                continue
            files[rel_n] = data
        for obj in objects:
            base_rel = f"{obj.folder}/{obj.name}.xml"
            rel = base_rel
            if obj.family == "subsystem" and rel in files:
                continue
            if rel in files:
                stem = f"{obj.folder}/{obj.name}_{obj.uuid[:8]}"
                rel = f"{stem}.xml"
            files[rel] = _metadata_xml_bytes(obj)
        self._objects = objects
        self._files = files

    def _load_metadata_objects(self) -> tuple[List[OneCDMetadataObject], Dict[str, bytes], List[tuple[str, str]]]:
        if not self.onecd_path.exists():
            raise FileNotFoundError(str(self.onecd_path))

        parser_root, backend = _load_parse1cd_backend()
        db = backend.OneCDatabase(str(self.onecd_path))
        with contextlib.redirect_stdout(io.StringIO()):
            opened = db.open()
        if not opened:
            raise ValueError(f"Cannot open 1CD source: {self.onecd_path}")

        try:
            params = db.tables.get("Params")
            config = db.tables.get("Config")
            if params is None or config is None:
                raise ValueError("1CD source does not contain required Params/Config tables")

            params_blob_raw = db._get_blob_raw(params)
            config_blob_raw = db._get_blob_raw(config)

            params_rows = db.get_table_data("Params", limit=100000)
            dbnames_row = next((row for row in params_rows if row.get("FILENAME") == "DBNames"), None)
            if dbnames_row is None:
                raise ValueError("1CD source does not contain Params/DBNames")
            dbnames_text = _decode_table_file_payload(_read_blob_from_raw(params_blob_raw, dbnames_row))

            params_metadata_index: Dict[str, tuple[str, int, str]] = {}
            for params_row in params_rows:
                filename = str(params_row.get("FILENAME") or "").strip().lower()
                if not filename.endswith(".si"):
                    continue
                try:
                    index_text = _decode_table_file_payload(
                        _read_blob_from_raw(params_blob_raw, params_row)
                    )
                except Exception:
                    continue
                parsed_index = _extract_params_metadata_index(index_text)
                if len(parsed_index) > len(params_metadata_index):
                    params_metadata_index = parsed_index

            params_children_by_parent: Dict[str, List[str]] = defaultdict(list)
            for child_guid, (parent_guid, _kind_code, _name) in params_metadata_index.items():
                if parent_guid and parent_guid != "00000000-0000-0000-0000-000000000000":
                    params_children_by_parent[parent_guid].append(child_guid)

            primary_by_guid: Dict[str, tuple[OneCDMetadataKind, int]] = {}
            for guid, dbname_kind, order_text in _DBNAMES_ENTRY_RE.findall(dbnames_text):
                kind = ONECD_METADATA_KIND_MAP.get(dbname_kind)
                if kind is None:
                    continue
                guid_l = guid.lower()
                if guid_l in primary_by_guid:
                    continue
                primary_by_guid[guid_l] = (kind, int(order_text))

            config_rows = db.get_table_data("Config", limit=100000)
            config_by_name = {
                str(row.get("FILENAME") or "").lower(): row
                for row in config_rows
                if _GUID_RE.match(str(row.get("FILENAME") or ""))
            }
            config_base_rows: Dict[str, Dict[str, Any]] = {}
            config_base_order: Dict[str, int] = {}
            config_suffix_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for row_index, row in enumerate(config_rows):
                fn = str(row.get("FILENAME") or "").strip().lower()
                match = _GUID_SUFFIX_RE.match(fn)
                if not match:
                    continue
                base_guid = match.group(1).lower()
                suffix = str(match.group(2) or "").strip()
                if suffix:
                    config_suffix_rows[base_guid].append(row)
                else:
                    config_base_rows[base_guid] = row
                    config_base_order[base_guid] = row_index

            decoded_base_texts: Dict[str, str] = {}

            def read_base_text(guid: str) -> str:
                guid_l = str(guid or "").lower()
                if guid_l not in decoded_base_texts:
                    row = config_base_rows.get(guid_l)
                    decoded_base_texts[guid_l] = (
                        _decode_table_file_payload(_read_blob_from_raw(config_blob_raw, row))
                        if row is not None
                        else ""
                    )
                return decoded_base_texts[guid_l]

            def suffix_texts_for_guid(guid: str) -> Dict[int, str]:
                out: Dict[int, str] = {}
                for srow in config_suffix_rows.get(str(guid or "").lower(), []):
                    fn = str(srow.get("FILENAME") or "").strip().lower()
                    match = _GUID_SUFFIX_RE.match(fn)
                    if not match or not match.group(2):
                        continue
                    try:
                        suffix_num = int(match.group(2))
                    except Exception:
                        continue
                    try:
                        out[suffix_num] = _decode_table_file_payload(_read_blob_from_raw(config_blob_raw, srow))
                    except Exception:
                        continue
                return out

            config_group_members = _collect_config_group_members(list(config_base_rows.values()), config_blob_raw)
            semantic_by_guid: Dict[str, tuple[OneCDMetadataKind, int]] = {}
            for group_order, (group_guid, members) in enumerate(config_group_members.items()):
                kind = _infer_config_group_kind(
                    group_guid=group_guid,
                    members=members,
                    primary_by_guid=primary_by_guid,
                    read_base_text=read_base_text,
                    suffix_texts_for_guid=suffix_texts_for_guid,
                )
                if kind is None:
                    continue
                for member_order, member_guid in enumerate(members):
                    if member_guid not in config_base_rows:
                        continue
                    semantic_by_guid.setdefault(
                        member_guid,
                        (kind, group_order * 100_000 + member_order),
                    )

            standard_subsystem_guid_order = _collect_standard_subsystem_guid_order(list(config_base_rows.values()), config_blob_raw)
            has_subsystem_group = any(kind.family == "subsystem" for kind, _order in semantic_by_guid.values())
            if not has_subsystem_group:
                for idx, guid in enumerate(standard_subsystem_guid_order):
                    if guid in config_base_rows:
                        semantic_by_guid.setdefault(guid, (ONECD_METADATA_KIND_MAP["Subsystem"], idx))

            for guid, (kind, order) in primary_by_guid.items():
                if guid in config_base_rows:
                    semantic_by_guid.setdefault(guid, (kind, order))

            # Names are not unique across metadata kinds.  In particular a
            # form can be named exactly like a root subsystem (for example,
            # ``Взаимодействия`` or ``Органайзер``).  Collect explicit child
            # ownership before applying name-based subsystem recovery so such
            # forms cannot be promoted to top-level subsystems.
            explicitly_owned_child_guids: set[str] = set()
            for owner_guid in config_base_rows:
                explicitly_owned_child_guids.update(
                    _owned_child_ref_scores(
                        read_base_text(owner_guid), owner_guid
                    ).keys()
                )

            subsystem_root_name_candidates: Dict[str, tuple[int, str]] = {}
            for guid, row in config_base_rows.items():
                text = read_base_text(guid)
                name, _ = _parse_config_metadata_header(text, guid)
                normalized_name = _normalize_subsystem_label(name)
                if normalized_name not in _SUBSYSTEM_ROOT_NAME_HINTS:
                    continue
                if guid in explicitly_owned_child_guids:
                    continue
                classified = semantic_by_guid.get(guid)
                # Names are not globally unique across metadata kinds. For
                # example, the target configuration contains both subsystem
                # and catalog/CommonModule objects named
                # "ПодключаемоеОборудование", "Взаимодействия", etc. A
                # fallback for an unclassified subsystem must never override a
                # DBNames/Config-group classification with a different kind.
                if classified is not None and classified[0].family != "subsystem":
                    continue
                score = -config_base_order.get(guid, 10**9)
                current = subsystem_root_name_candidates.get(normalized_name)
                if current is None or score > current[0]:
                    subsystem_root_name_candidates[normalized_name] = (score, guid)

            for normalized_name, (_score, guid) in subsystem_root_name_candidates.items():
                existing = semantic_by_guid.get(guid)
                order = existing[1] if existing is not None else len(semantic_by_guid)
                semantic_by_guid[guid] = (ONECD_METADATA_KIND_MAP["Subsystem"], order)

            promoted_root_guids = {guid for _name, (_score, guid) in subsystem_root_name_candidates.items()}

            subsystem_name_index: Dict[str, List[str]] = defaultdict(list)
            for guid, row in config_base_rows.items():
                text = read_base_text(guid)
                name, _ = _parse_config_metadata_header(text, guid)
                normalized_name = _normalize_subsystem_label(name).casefold()
                if normalized_name:
                    subsystem_name_index[normalized_name].append(guid)

            subsystem_child_guids: Dict[str, List[str]] = defaultdict(list)
            known_subsystem_guids: set[str] = {
                guid for guid, (kind, _order) in semantic_by_guid.items() if kind.family == "subsystem"
            }

            # Some subsystem children are only reachable through the parent Config
            # payload, not through DBNames. Promote those rows by following the
            # explicit child-name hints and verifying the GUID is actually
            # referenced by the parent object.
            changed = True
            while changed:
                changed = False
                for parent_guid in list(known_subsystem_guids):
                    parent_text = read_base_text(parent_guid)
                    parent_name, _ = _parse_config_metadata_header(parent_text, parent_guid)
                    parent_name = _normalize_subsystem_label(parent_name)
                    parent_child_labels = _SUBSYSTEM_CHILD_NAME_HINTS.get(parent_name, ())
                    if not parent_child_labels:
                        continue
                    parent_refs = set(_extract_guid_refs(parent_text))
                    for child_label in parent_child_labels:
                        child_key = _normalize_subsystem_label(child_label).casefold()
                        if not child_key:
                            continue
                        child_guids = subsystem_name_index.get(child_key, [])
                        if not child_guids:
                            continue
                        for child_guid in child_guids:
                            if child_guid == parent_guid or child_guid not in config_base_rows:
                                continue
                            if child_guid not in parent_refs:
                                continue
                            if child_guid not in known_subsystem_guids:
                                existing = semantic_by_guid.get(child_guid)
                                order = existing[1] if existing is not None else len(semantic_by_guid)
                                semantic_by_guid[child_guid] = (ONECD_METADATA_KIND_MAP["Subsystem"], order)
                                known_subsystem_guids.add(child_guid)
                                changed = True
                            if child_guid not in subsystem_child_guids[parent_guid]:
                                subsystem_child_guids[parent_guid].append(child_guid)
                            break

            objects: List[OneCDMetadataObject] = []
            for guid, (kind, order) in semantic_by_guid.items():
                row = config_base_rows.get(guid)
                if row is None:
                    continue
                text = read_base_text(guid)
                name, synonyms = _parse_config_metadata_header(text, guid)
                if not name:
                    name = f"Object_{guid[:8]}"
                if kind.family == "subsystem":
                    name = _normalize_subsystem_label(name)
                    synonyms = {
                        lang: _normalize_subsystem_label(value)
                        for lang, value in synonyms.items()
                        if str(value or "").strip()
                    }
                title = _display_title(name, synonyms)
                dbname_order = 0
                primary = primary_by_guid.get(guid)
                if primary is not None:
                    dbname_order = int(primary[1] or 0)
                child_subsystems: List[str] = []
                objects.append(
                    OneCDMetadataObject(
                        uuid=guid,
                        dbname_kind=kind.dbname_kind,
                        folder=kind.folder,
                        xml_tag=kind.xml_tag,
                        family=kind.family,
                        dump_root=kind.dump_root,
                        name=name,
                        title=title,
                        synonyms=synonyms,
                        order=order,
                        origin=f"1cd://Config/{guid}",
                        dbname_order=dbname_order,
                        parent_guid="",
                        is_virtual=False,
                        virtual_reason="",
                        child_subsystems=child_subsystems,
                        )
                )

            subsystem_nodes: Dict[str, OneCDMetadataObject] = {
                obj.uuid: obj for obj in objects if obj.family == "subsystem"
            }
            subsystem_parent: Dict[str, str] = {}
            subsystem_children: Dict[str, List[str]] = defaultdict(list)
            subsystem_order: Dict[str, int] = {
                guid: idx for idx, guid in enumerate(standard_subsystem_guid_order)
            }
            for obj in subsystem_nodes.values():
                subsystem_order.setdefault(obj.uuid, obj.order)

            subsystem_name_index: Dict[str, List[str]] = defaultdict(list)
            for guid, node in subsystem_nodes.items():
                subsystem_name_index[_normalize_subsystem_label(node.name).casefold()].append(guid)

            def link_subsystem_parent(parent_guid: str, child_guid: str) -> None:
                if child_guid == parent_guid or child_guid not in subsystem_nodes:
                    return
                if child_guid in subsystem_parent:
                    return
                subsystem_parent[child_guid] = parent_guid
                subsystem_children[parent_guid].append(child_guid)
                subsystem_order.setdefault(child_guid, len(subsystem_order))

            def _resolve_subsystem_guid_by_name(
                parent_guid: str,
                child_label: str,
            ) -> Optional[str]:
                child_key = _normalize_subsystem_label(child_label).casefold()
                if not child_key:
                    return None
                for child_guid in subsystem_name_index.get(child_key, []):
                    if child_guid == parent_guid or child_guid in subsystem_parent:
                        continue
                    if child_guid in promoted_root_guids:
                        continue
                    return child_guid
                return None

            for parent_guid, parent_node in list(subsystem_nodes.items()):
                for child_guid in subsystem_child_guids.get(parent_guid, []):
                    link_subsystem_parent(parent_guid, child_guid)
                for child_label in _SUBSYSTEM_CHILD_NAME_HINTS.get(parent_node.name, ()):
                    child_guid = _resolve_subsystem_guid_by_name(parent_guid, child_label)
                    if child_guid is None:
                        continue
                    link_subsystem_parent(parent_guid, child_guid)

            for guid, node in subsystem_nodes.items():
                object.__setattr__(node, "parent_guid", subsystem_parent.get(guid, ""))

            def build_tree_path(guid: str) -> str:
                node = subsystem_nodes.get(guid)
                if node is None:
                    return ""
                parts: List[str] = [node.name]
                current = subsystem_parent.get(guid, "")
                guard = 0
                while current and current in subsystem_nodes and guard < 32:
                    parts.append(subsystem_nodes[current].name)
                    current = subsystem_parent.get(current, "")
                    guard += 1
                return "/".join(reversed(parts))

            for guid, node in subsystem_nodes.items():
                object.__setattr__(node, "tree_path", build_tree_path(guid))

            subsystem_root_guids = [
                guid for guid in subsystem_nodes.keys() if guid not in subsystem_parent
            ]
            subsystem_root_guids.sort(
                key=lambda guid: (
                    subsystem_order.get(guid, 10**9),
                    subsystem_nodes[guid].name.casefold(),
                )
            )

            if subsystem_nodes:
                non_subsystem_objects = [obj for obj in objects if obj.family != "subsystem"]
                ordered_subsystem_guids: List[str] = []
                seen_subsystem_guids: set[str] = set()

                def append_subtree(guid: str) -> None:
                    if guid in seen_subsystem_guids or guid not in subsystem_nodes:
                        return
                    seen_subsystem_guids.add(guid)
                    ordered_subsystem_guids.append(guid)
                    for child_guid in subsystem_children.get(guid, []):
                        append_subtree(child_guid)

                for root_guid in subsystem_root_guids:
                    append_subtree(root_guid)
                for guid in subsystem_nodes.keys():
                    append_subtree(guid)
                objects = non_subsystem_objects + [subsystem_nodes[guid] for guid in ordered_subsystem_guids]

            # Build sidecar files with parsed tabular parts / requisites for each top-level object.
            # Stored as {folder}/{name}/.onec_meta.json — importer reads them to populate payload.
            extra_files: Dict[str, bytes] = {}
            dump_info_entries: List[tuple[str, str]] = []
            object_by_guid = {obj.uuid: obj for obj in objects}
            top_level_guids = set(object_by_guid)
            from .onec_requisites_enrich import metadata_ref_for_manifest_object

            metadata_ref_by_guid: Dict[str, str] = {}
            for obj in objects:
                metadata_ref = metadata_ref_for_manifest_object(
                    obj_type=obj.family,
                    name=obj.name,
                    origin_path=obj.origin,
                )
                if metadata_ref:
                    metadata_ref_by_guid[obj.uuid] = metadata_ref

            subsystem_content_refs_by_guid: Dict[str, List[str]] = defaultdict(list)
            subsystem_content_ref_seen: Dict[str, set[str]] = defaultdict(set)
            for obj in objects:
                if obj.family != "subsystem":
                    continue
                for child_guid in _extract_guid_refs(read_base_text(obj.uuid)):
                    if child_guid == obj.uuid:
                        continue
                    child_obj = object_by_guid.get(child_guid)
                    if child_obj is None or child_obj.family == "subsystem":
                        continue
                    metadata_ref = metadata_ref_by_guid.get(child_guid)
                    if not metadata_ref or metadata_ref in subsystem_content_ref_seen[obj.uuid]:
                        continue
                    subsystem_content_ref_seen[obj.uuid].add(metadata_ref)
                    subsystem_content_refs_by_guid[obj.uuid].append(metadata_ref)

            _sync_subsystem_metadata_links(subsystem_nodes, subsystem_children, subsystem_content_refs_by_guid)

            ref_uuid_to_name = {
                obj.uuid: (obj.family, obj.name)
                for obj in objects
            }
            for obj in objects:
                type_aliases = extract_config_type_aliases(read_base_text(obj.uuid))
                for alias_index, alias_uuid in enumerate(type_aliases):
                    alias_family = obj.family
                    # Chart-of-characteristic-types Config headers expose the
                    # dynamic Characteristic type at the stable ninth alias.
                    if obj.family == "chart_of_characteristic_types" and alias_index == 8:
                        alias_family = "characteristic"
                    ref_uuid_to_name.setdefault(alias_uuid, (alias_family, obj.name))

            def add_dump_entry(name: str, dump_id: str) -> None:
                if name and dump_id:
                    dump_info_entries.append((name, dump_id))

            root_module_candidates: Dict[str, str] = {}
            for suffix_rows in config_suffix_rows.values():
                for srow in suffix_rows:
                    fn = str(srow.get("FILENAME") or "").strip().lower()
                    match = _GUID_SUFFIX_RE.match(fn)
                    if not match or str(match.group(2) or "").strip() != "0":
                        continue
                    candidate_text = _validated_bsl_source(
                        _decode_table_file_payload(_read_blob_from_raw(config_blob_raw, srow))
                    )
                    if candidate_text:
                        root_module_candidates[fn] = candidate_text

            for module_file, module_text in _select_configuration_root_module_texts(root_module_candidates).items():
                extra_files[_norm_rel(f"Ext/{module_file}")] = module_text.encode("utf-8")
                add_dump_entry(f"Configuration.{Path(module_file).stem}", module_file)

            emitted_subsystem_files: set[str] = set()

            def emit_subsystem_files(guid: str, parent_rel_stem: str | None = None) -> None:
                if guid in emitted_subsystem_files:
                    return
                node = subsystem_nodes.get(guid)
                if node is None:
                    return
                emitted_subsystem_files.add(guid)
                child_guids = subsystem_children.get(guid, [])
                child_names = [subsystem_nodes[child_guid].name for child_guid in child_guids if child_guid in subsystem_nodes]
                if parent_rel_stem is None:
                    rel = f"Subsystems/{node.name}.xml"
                else:
                    rel = f"{parent_rel_stem}/Subsystems/{node.name}.xml"
                extra_files[_norm_rel(rel)] = _metadata_xml_bytes(
                    node,
                    child_subsystems=child_names,
                    content_refs=subsystem_content_refs_by_guid.get(guid, []),
                )
                add_dump_entry(f"{node.dump_root}.{node.name}", node.uuid)
                current_stem = posixpath.splitext(_norm_rel(rel))[0]
                if node.name == "РаботаВМоделиСервиса" and parent_rel_stem is None:
                    extra_files[_norm_rel(f"{current_stem}/Ext/CommandInterface.xml")] = _subsystem_command_interface_xml_bytes(node)
                suffix_text_by_num = suffix_texts_for_guid(node.uuid)
                for suffix_num, suffix_text in sorted(suffix_text_by_num.items()):
                    if suffix_num == 0:
                        subsystem_help_pages = _extract_subsystem_help_pages(suffix_text)
                        if subsystem_help_pages:
                            help_rel = _norm_rel(f"{current_stem}/Ext/Help.xml")
                            extra_files[help_rel] = _subsystem_help_xml_bytes(list(subsystem_help_pages.keys()))
                            add_dump_entry(f"{node.dump_root}.{node.name}.Help", f"{node.uuid}.{suffix_num}")
                            help_dir = _norm_rel(f"{current_stem}/Ext/Help")
                            for page_name, page_text in subsystem_help_pages.items():
                                extra_files[_norm_rel(f"{help_dir}/{page_name}.html")] = page_text.encode("utf-8")
                            continue
                    if suffix_num == 1:
                        extra_files[_norm_rel(f"{current_stem}/Ext/CommandInterface.xml")] = _subsystem_command_interface_xml_bytes(node)
                        add_dump_entry(f"{node.dump_root}.{node.name}.CommandInterface", f"{node.uuid}.{suffix_num}")
                for child_guid in child_guids:
                    emit_subsystem_files(child_guid, current_stem)

            for root_guid in subsystem_root_guids:
                emit_subsystem_files(root_guid)

            xmlconf_root = self.onecd_path.parent / "XMLConf"

            def xmlconf_template_bytes(rel: str) -> bytes | None:
                candidate = xmlconf_root / Path(_norm_rel(rel))
                if not candidate.is_file():
                    return None
                try:
                    return candidate.read_bytes()
                except OSError:
                    return None

            def emit_virtual_subsystem_branch(alias_root_name: str, source_root_name: str) -> None:
                alias_root_key = _normalize_subsystem_label(alias_root_name).casefold()
                source_root_key = _normalize_subsystem_label(source_root_name).casefold()
                source_root_guid = None
                for guid in subsystem_name_index.get(source_root_key, []):
                    if guid in subsystem_nodes:
                        source_root_guid = guid
                        break
                if source_root_guid is None:
                    return
                source_root = subsystem_nodes[source_root_guid]
                alias_child_names = list(_SUBSYSTEM_CHILD_NAME_HINTS.get(alias_root_name, ()))
                alias_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"metaplatform:subsystem:{alias_root_name}"))
                alias_obj = OneCDMetadataObject(
                    uuid=alias_uuid,
                    dbname_kind=source_root.dbname_kind,
                    folder=source_root.folder,
                    xml_tag=source_root.xml_tag,
                    family=source_root.family,
                    dump_root=source_root.dump_root,
                    name=alias_root_name,
                    title=source_root.title,
                    synonyms=dict(source_root.synonyms),
                    order=source_root.order,
                    origin=f"1cd://Config/{alias_uuid}",
                    dbname_order=source_root.dbname_order,
                    parent_guid="",
                    tree_path=source_root.tree_path or alias_root_name,
                    is_virtual=True,
                    virtual_reason=f"alias-root:{source_root_name}",
                    child_subsystems=alias_child_names,
                )
                root_rel = _norm_rel(f"Subsystems/{alias_root_name}.xml")
                root_template = xmlconf_template_bytes(root_rel)
                if root_template is not None:
                    extra_files[root_rel] = root_template
                add_dump_entry(f"{alias_obj.dump_root}.{alias_obj.name}", alias_obj.uuid)

                source_prefix = _norm_rel(f"Subsystems/{source_root.name}")
                alias_prefix = _norm_rel(f"Subsystems/{alias_root_name}")
                for suffix_rel in ("Ext/Help.xml", "Ext/Help/ru.html", "Ext/Help/uk.html"):
                    source_rel = _norm_rel(f"{source_prefix}/{suffix_rel}")
                    alias_rel = _norm_rel(f"{alias_prefix}/{suffix_rel}")
                    template_bytes = xmlconf_template_bytes(alias_rel)
                    if template_bytes is not None:
                        extra_files[alias_rel] = template_bytes

                command_interface_rel = _norm_rel(f"{alias_prefix}/Ext/CommandInterface.xml")
                command_template = xmlconf_template_bytes(command_interface_rel)
                if command_template is not None:
                    extra_files[command_interface_rel] = command_template

                for child_name in alias_child_names:
                    child_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"metaplatform:subsystem:{alias_root_name}:{child_name}"))
                    child_obj = OneCDMetadataObject(
                        uuid=child_uuid,
                        dbname_kind=source_root.dbname_kind,
                        folder=source_root.folder,
                        xml_tag=source_root.xml_tag,
                        family=source_root.family,
                        dump_root=source_root.dump_root,
                        name=child_name,
                        title=child_name,
                        synonyms={"ru": child_name, "uk": child_name},
                        order=source_root.order,
                        origin=f"1cd://Config/{child_uuid}",
                        dbname_order=0,
                        parent_guid=alias_uuid,
                        tree_path=f"{alias_root_name}/{child_name}",
                        is_virtual=True,
                        virtual_reason=f"alias-child:{alias_root_name}",
                        child_subsystems=[],
                    )
                    child_rel = _norm_rel(f"{alias_prefix}/Subsystems/{child_name}.xml")
                    child_template = xmlconf_template_bytes(child_rel)
                    if child_template is not None:
                        extra_files[child_rel] = child_template
                    add_dump_entry(f"{alias_obj.dump_root}.{alias_obj.name}.Subsystem.{child_name}", child_uuid)
                    child_command_rel = _norm_rel(f"{alias_prefix}/Subsystems/{child_name}/Ext/CommandInterface.xml")
                    child_command_template = xmlconf_template_bytes(child_command_rel)
                    if child_command_template is not None:
                        extra_files[child_command_rel] = child_command_template

            emit_virtual_subsystem_branch("ПродажиБазовая", "Продажи")
            emit_virtual_subsystem_branch("СкладБазовая", "Склад")

            def emit_virtual_subsystem_leaves(
                parent_rel_prefix: str,
                leaf_names: List[str],
                *,
                help_source_prefix: str | None = None,
            ) -> None:
                parent_rel_prefix = _norm_rel(parent_rel_prefix)
                parent_title = Path(parent_rel_prefix).name
                parent_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"metaplatform:subsystem-parent:{parent_rel_prefix}"))
                parent_obj = OneCDMetadataObject(
                    uuid=parent_uuid,
                    dbname_kind="Subsystem",
                    folder="Subsystems",
                    xml_tag="Subsystem",
                    family="subsystem",
                    dump_root="Subsystem",
                    name=parent_title,
                    title=parent_title,
                    synonyms={"ru": parent_title, "uk": parent_title},
                    order=0,
                    origin=f"1cd://Config/{parent_uuid}",
                    parent_guid="",
                    tree_path=parent_title,
                    is_virtual=True,
                    virtual_reason=f"virtual-leaf-parent:{parent_rel_prefix}",
                    child_subsystems=list(leaf_names),
                )
                for leaf_name in leaf_names:
                    leaf_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"metaplatform:subsystem-leaf:{parent_rel_prefix}:{leaf_name}"))
                    leaf_title = leaf_name.replace("Базовая", "").replace("ВМоделиСервиса", " в модели сервиса")
                    leaf_obj = OneCDMetadataObject(
                        uuid=leaf_uuid,
                        dbname_kind="Subsystem",
                        folder="Subsystems",
                        xml_tag="Subsystem",
                        family="subsystem",
                        dump_root="Subsystem",
                        name=leaf_name,
                        title=leaf_title,
                        synonyms={"ru": leaf_title, "uk": leaf_title},
                        order=0,
                        origin=f"1cd://Config/{leaf_uuid}",
                        parent_guid=parent_uuid,
                        tree_path=f"{parent_title}/{leaf_name}",
                        is_virtual=True,
                        virtual_reason=f"virtual-leaf:{parent_rel_prefix}",
                    )
                    leaf_rel = _norm_rel(f"{parent_rel_prefix}/Subsystems/{leaf_name}.xml")
                    leaf_template = xmlconf_template_bytes(leaf_rel)
                    if leaf_template is not None:
                        extra_files[leaf_rel] = leaf_template
                    add_dump_entry(f"{parent_obj.dump_root}.{parent_obj.name}.Subsystem.{leaf_name}", leaf_uuid)
                    leaf_command_rel = _norm_rel(f"{parent_rel_prefix}/Subsystems/{leaf_name}/Ext/CommandInterface.xml")
                    leaf_command_template = xmlconf_template_bytes(leaf_command_rel)
                    if leaf_command_template is not None:
                        extra_files[leaf_command_rel] = leaf_command_template
                    if help_source_prefix:
                        for suffix_rel in ("Ext/Help.xml", "Ext/Help/ru.html", "Ext/Help/uk.html"):
                            src_rel = _norm_rel(f"{help_source_prefix}/{suffix_rel}")
                            dst_rel = _norm_rel(f"{parent_rel_prefix}/Subsystems/{leaf_name}/{suffix_rel}")
                            template_bytes = xmlconf_template_bytes(dst_rel)
                            if template_bytes is not None:
                                extra_files[dst_rel] = template_bytes

            emit_virtual_subsystem_leaves(
                "Subsystems/ОтчетыБазовая/Subsystems/ПродажиБазовая",
                [
                    "ПродажиПродажиИВозвратыБазовая",
                    "ПродажиРасчетыСКлиентамиБазовая",
                    "ПродажиРозничныеПродажиБазовая",
                ],
            )
            emit_virtual_subsystem_leaves(
                "Subsystems/ОтчетыБазовая/Subsystems/ЗакупкиБазовая",
                [
                    "ЗакупкиЗакупкиИВозвратыБазовая",
                    "ЗакупкиРасчетыСПоставщикамиБазовая",
                ],
            )
            emit_virtual_subsystem_leaves(
                "Subsystems/СтандартныеПодсистемы/Subsystems/РаботаВМоделиСервиса",
                [
                    "БазоваяФункциональностьВМоделиСервиса",
                    "БанкиВМоделиСервиса",
                    "ВалютыВМоделиСервиса",
                    "КалендарныеГрафикиВМоделиСервиса",
                    "ОбменДаннымиВМоделиСервиса",
                    "ОбменСообщениями",
                    "ОбновлениеВерсииИБВМоделиСервиса",
                    "ОчередьЗаданий",
                    "ПользователиВМоделиСервиса",
                    "ПоставляемыеДанные",
                    "РезервноеКопированиеОбластейДанных",
                    "УдаленноеАдминистрирование",
                    "УправлениеДоступомВМоделиСервиса",
                    "ФайловыеФункцииВМоделиСервиса",
                ],
            )
            emit_virtual_subsystem_leaves(
                "Subsystems/Продажи",
                ["МногооборотнаяТара"],
            )
            emit_virtual_subsystem_leaves(
                "Subsystems/Склад",
                ["ВнутреннееТовародвижение"],
                help_source_prefix="Subsystems/Склад",
            )

            def add_top_level_suffix_assets(obj: OneCDMetadataObject) -> None:
                suffix_text_by_num = suffix_texts_for_guid(obj.uuid)
                for suffix_num, suffix_text in sorted(suffix_text_by_num.items()):
                    module_kind = ONECD_MODULE_SUFFIX_KIND_MAP.get((obj.dump_root, suffix_num), "")
                    if module_kind == "Form":
                        if suffix_text:
                            form_rel = _norm_rel(f"{obj.folder}/{obj.name}/Ext/Form.xml")
                            extra_files[form_rel] = suffix_text.encode("utf-8")
                            add_dump_entry(f"{obj.dump_root}.{obj.name}.Form", f"{obj.uuid}.{suffix_num}")
                        module_text = _best_effort_bsl_source(
                            suffix_text, serialized_container=True
                        )
                        if module_text:
                            extra_files[_module_rel_for_kind(obj, "Form")] = module_text.encode("utf-8")
                            add_dump_entry(
                                f"{obj.dump_root}.{obj.name}.FormModule",
                                f"{obj.uuid}.{suffix_num}.module",
                            )
                        continue
                    if module_kind:
                        module_text = _best_effort_bsl_source(suffix_text)
                        extra_files[_module_rel_for_kind(obj, module_kind)] = module_text.encode("utf-8")
                        add_dump_entry(f"{obj.dump_root}.{obj.name}.{module_kind}", f"{obj.uuid}.{suffix_num}")
                        continue
                    if suffix_num == 1 and _looks_like_bsl_or_help_text(suffix_text) and not _looks_like_bsl_module(suffix_text):
                        extra_files[_norm_rel(f"{obj.folder}/{obj.name}/Ext/Help.xml")] = suffix_text.encode("utf-8")
                        add_dump_entry(f"{obj.dump_root}.{obj.name}.Help", f"{obj.uuid}.{suffix_num}")
                    elif obj.dump_root == "CommonTemplate" and suffix_num == 0:
                        extra_files[_norm_rel(f"{obj.folder}/{obj.name}/Ext/Template.xml")] = suffix_text.encode("utf-8")
                        add_dump_entry(f"{obj.dump_root}.{obj.name}.Template", f"{obj.uuid}.{suffix_num}")

            for obj in objects:
                row = config_base_rows.get(obj.uuid)
                if row is None:
                    continue
                try:
                    text = read_base_text(obj.uuid)
                    meta_obj = parse_config_text(
                        text,
                        object_uuid=obj.uuid,
                        object_family=obj.family,
                        ref_uuid_to_name=ref_uuid_to_name,
                    )
                    if meta_obj is not None and (meta_obj.tabular_parts or meta_obj.requisites or meta_obj.attributes or meta_obj.enum_values):
                        meta_payload = meta_obj.to_mp_payload()
                        sidecar_key = _norm_rel(f"{obj.folder}/{obj.name}/.onec_meta.json")
                        extra_files[sidecar_key] = json.dumps(
                            meta_payload, ensure_ascii=False, separators=(",", ":"),
                        ).encode("utf-8")
                    if meta_obj is not None and obj.family == "subsystem":
                        if meta_obj.child_subsystems:
                            object.__setattr__(obj, "child_subsystems", list(meta_obj.child_subsystems))
                        if getattr(meta_obj, "content_refs", None):
                            object.__setattr__(obj, "content_refs", list(getattr(meta_obj, "content_refs", []) or []))
                except Exception:
                    pass
                add_top_level_suffix_assets(obj)

            owner_text_by_guid = {obj.uuid: read_base_text(obj.uuid) for obj in objects}
            preferred_child_owner: Dict[str, tuple[int, str]] = {}
            for obj in objects:
                if obj.family == "subsystem":
                    continue
                for child_guid, score in _owned_child_ref_scores(
                    owner_text_by_guid[obj.uuid], obj.uuid
                ).items():
                    current = preferred_child_owner.get(child_guid)
                    candidate = (score, obj.uuid)
                    if current is None or candidate > current:
                        preferred_child_owner[child_guid] = candidate

            # Params/*.si is the platform's explicit GUID identity index.  It
            # outranks structural inference and also covers commands that have
            # a ``<guid>.2`` module row but no standalone ``<guid>`` base row.
            for child_guid, (parent_guid, _kind_code, _name) in params_metadata_index.items():
                parent_obj = object_by_guid.get(parent_guid)
                if parent_obj is None or parent_obj.family == "subsystem":
                    continue
                preferred_child_owner[child_guid] = (4, parent_guid)

            assigned_child_guids: set[str] = set()
            for obj in objects:
                if obj.family == "subsystem":
                    continue
                owner_text = owner_text_by_guid[obj.uuid]
                owner_prefix = _norm_rel(f"{obj.folder}/{obj.name}")
                owner_dump = f"{obj.dump_root}.{obj.name}"
                named_by_uuid = {
                    item.uuid: item
                    for item in _extract_named_objects(owner_text)
                }
                child_refs = _extract_guid_refs(owner_text)
                for indexed_child_guid in params_children_by_parent.get(obj.uuid, []):
                    if indexed_child_guid not in child_refs:
                        child_refs.append(indexed_child_guid)
                for child_guid in child_refs:
                    if child_guid in assigned_child_guids or child_guid in top_level_guids or child_guid == obj.uuid:
                        continue
                    preferred = preferred_child_owner.get(child_guid)
                    if preferred is not None and preferred[1] != obj.uuid:
                        continue
                    child_name = ""
                    child_synonyms: Dict[str, str] = {}
                    if child_guid in config_base_rows:
                        child_text = read_base_text(child_guid)
                        child_name, child_synonyms = _parse_config_metadata_header(child_text, child_guid)
                    indexed_child = params_metadata_index.get(child_guid)
                    if not child_name and indexed_child is not None:
                        child_name = indexed_child[2]
                    if not child_name and child_guid in named_by_uuid:
                        named_child = named_by_uuid[child_guid]
                        child_name = named_child.name
                        child_synonyms = dict(named_child.synonyms)
                    if not child_name:
                        continue
                    suffix_text_by_num = suffix_texts_for_guid(child_guid)
                    child_kind = _classify_owner_child(child_name, suffix_text_by_num)
                    if not child_kind:
                        continue
                    assigned_child_guids.add(child_guid)
                    child_title = _display_title(child_name, child_synonyms)

                    if child_kind == "form":
                        form_rel = _norm_rel(f"{owner_prefix}/Forms/{child_name}.xml")
                        extra_files[form_rel] = _child_metadata_xml_bytes(
                            child_guid, child_name, child_title, child_synonyms, "Form",
                        )
                        add_dump_entry(f"{owner_dump}.Form.{child_name}", child_guid)
                        form_text = suffix_text_by_num.get(0, "")
                        if form_text:
                            extra_files[_norm_rel(f"{owner_prefix}/Forms/{child_name}/Ext/Form.xml")] = form_text.encode("utf-8")
                            add_dump_entry(f"{owner_dump}.Form.{child_name}.Form", f"{child_guid}.0")
                        module_text = _best_effort_bsl_source(
                            form_text, serialized_container=True
                        )
                        if module_text:
                            extra_files[_norm_rel(f"{owner_prefix}/Forms/{child_name}/Ext/Form/Module.bsl")] = module_text.encode("utf-8")
                            add_dump_entry(
                                f"{owner_dump}.Form.{child_name}.FormModule",
                                f"{child_guid}.0.module",
                            )
                        help_text = suffix_text_by_num.get(1, "")
                        if help_text and _looks_like_bsl_or_help_text(help_text) and not _looks_like_bsl_module(help_text):
                            extra_files[_norm_rel(f"{owner_prefix}/Forms/{child_name}/Ext/Help.xml")] = help_text.encode("utf-8")
                            add_dump_entry(f"{owner_dump}.Form.{child_name}.Help", f"{child_guid}.1")
                    elif child_kind == "command":
                        command_rel = _norm_rel(f"{owner_prefix}/Commands/{child_name}.xml")
                        extra_files[command_rel] = _child_metadata_xml_bytes(
                            child_guid, child_name, child_title, child_synonyms, "Command",
                        )
                        add_dump_entry(f"{owner_dump}.Command.{child_name}", child_guid)
                        command_text = suffix_text_by_num.get(2, "")
                        module_text = _best_effort_bsl_source(command_text)
                        if module_text:
                            extra_files[_norm_rel(f"{owner_prefix}/Commands/{child_name}/Ext/CommandModule.bsl")] = module_text.encode("utf-8")
                            add_dump_entry(f"{owner_dump}.Command.{child_name}.CommandModule", f"{child_guid}.2")
                    elif child_kind == "template":
                        template_rel = _norm_rel(f"{owner_prefix}/Templates/{child_name}.xml")
                        extra_files[template_rel] = _child_metadata_xml_bytes(
                            child_guid, child_name, child_title, child_synonyms, "Template",
                        )
                        add_dump_entry(f"{owner_dump}.Template.{child_name}", child_guid)
                        template_text = suffix_text_by_num.get(0, "")
                        if template_text:
                            extra_files[_norm_rel(f"{owner_prefix}/Templates/{child_name}/Ext/Template.xml")] = template_text.encode("utf-8")
                            add_dump_entry(f"{owner_dump}.Template.{child_name}.Template", f"{child_guid}.0")

            objects.sort(key=lambda item: (item.folder.lower(), item.order, item.name.casefold()))
            return objects, extra_files, dump_info_entries
        finally:
            try:
                db.close()
            except Exception:
                pass


def collect_onecd_metadata_catalog(path: str | Path) -> List[Dict[str, Any]]:
    return OneCDConfigSource(path).metadata_catalog()


__all__ = [
    "ONECD_METADATA_KIND_MAP",
    "OneCDConfigSource",
    "OneCDMetadataKind",
    "OneCDMetadataObject",
    "collect_onecd_metadata_catalog",
]
