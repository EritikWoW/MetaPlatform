from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional

# Имя таблицы манифеста в mpdb
MANIFEST_TABLE: str = "manifest"

# ---------------------------------------------------------------------------
# ObjectType — полный список типов узлов дерева (аналог 1С)
#
# Группы (group-узлы в дереве, отображаются как ветки):
#   configuration     — корень «Конфигурация»
#   common            — «Загальні / General»
#   constants         — «Константи / Constants»
#   catalog           — «Довідники / Catalogs»
#   document          — «Документи / Documents»
#   journal           — «Журнали документів / Document journals»
#   enumeration       — «Перерахування / Enumerations»
#   report            — «Звіти / Reports»
#   data_processor    — «Обробки / Data processors»
#   chart_of_characteristic_types — «Плани видів характеристик»
#   chart_of_accounts             — «Плани рахунків»
#   chart_of_calculation_types    — «Плани видів розрахунку»
#   register_info     — «Регістри відомостей / Information registers»
#   register_accum    — «Регістри накопичення / Accumulation registers»
#   register_accounting — «Регістри бухгалтерії / Accounting registers»
#   register_calc     — «Регістри розрахунку / Calculation registers»
#   business_process  — «Бізнес-процеси / Business processes»
#   task              — «Завдання / Tasks»
#   external_sources  — «Зовнішні джерела даних / External data sources»
#
# Підвузли «Загальні»:
#   subsystem, common_module, session_param, role, common_attribute,
#   exchange_plan, selection_criterion, event_subscription, scheduled_job,
#   bot, functional_option, functional_option_param, defined_type,
#   settings_storage, common_command, command_group, common_form,
#   common_layout, common_picture, xdto_package, web_service,
#   http_service, ws_link, websocket_client, integration_service,
#   style_element, style, language
#
# Об'єкти конкретних типів:
#   catalog_obj, document_obj, enumeration_obj, report_obj, ...
# ---------------------------------------------------------------------------
ObjectType = str   # строка — открытый тип для расширяемости

# Константы типов для удобства импорта
OBJ_CONFIGURATION          = "configuration"
OBJ_COMMON                 = "common"
OBJ_CONSTANTS              = "constants"
OBJ_CATALOG                = "catalog"
OBJ_DOCUMENT               = "document"
OBJ_JOURNAL                = "journal"
OBJ_ENUMERATION            = "enumeration"
OBJ_REPORT                 = "report"
OBJ_DATA_PROCESSOR         = "data_processor"
OBJ_CHART_CHAR_TYPES       = "chart_of_characteristic_types"
OBJ_CHART_ACCOUNTS         = "chart_of_accounts"
OBJ_CHART_CALC_TYPES       = "chart_of_calculation_types"
OBJ_REGISTER_INFO          = "register_info"
OBJ_REGISTER_ACCUM         = "register_accum"
OBJ_REGISTER_ACCOUNTING    = "register_accounting"
OBJ_REGISTER_CALC          = "register_calc"
OBJ_BUSINESS_PROCESS       = "business_process"
OBJ_TASK                   = "task"
OBJ_EXTERNAL_SOURCES       = "external_sources"

# Загальні підтипи
OBJ_SUBSYSTEM              = "subsystem"
OBJ_COMMON_MODULE          = "common_module"
OBJ_SESSION_PARAM          = "session_param"
OBJ_ROLE                   = "role"
OBJ_COMMON_ATTRIBUTE       = "common_attribute"
OBJ_EXCHANGE_PLAN          = "exchange_plan"
OBJ_SELECTION_CRITERION    = "selection_criterion"
OBJ_EVENT_SUBSCRIPTION     = "event_subscription"
OBJ_SCHEDULED_JOB          = "scheduled_job"
OBJ_BOT                    = "bot"
OBJ_FUNCTIONAL_OPTION      = "functional_option"
OBJ_FUNC_OPTION_PARAM      = "functional_option_param"
OBJ_DEFINED_TYPE           = "defined_type"
OBJ_SETTINGS_STORAGE       = "settings_storage"
OBJ_COMMON_COMMAND         = "common_command"
OBJ_COMMAND_GROUP          = "command_group"
OBJ_COMMON_FORM            = "common_form"
OBJ_COMMON_LAYOUT          = "common_layout"
OBJ_COMMON_PICTURE         = "common_picture"
OBJ_XDTO_PACKAGE           = "xdto_package"
OBJ_WEB_SERVICE            = "web_service"
OBJ_HTTP_SERVICE           = "http_service"
OBJ_WS_LINK                = "ws_link"
OBJ_WEBSOCKET_CLIENT       = "websocket_client"
OBJ_INTEGRATION_SERVICE    = "integration_service"
OBJ_STYLE_ELEMENT          = "style_element"
OBJ_STYLE                  = "style"
OBJ_LANGUAGE               = "language"

# Компоненти об'єктів
OBJ_FORM                   = "form"
OBJ_COMMAND                = "command"
OBJ_LAYOUT                 = "layout"
OBJ_MODULE                 = "module"
OBJ_FORM_MODULE            = "form_module"

# Що именно це за вузол в дереві
# root/group/folder/object — як у конфігураторі
NodeKind = Literal["root", "group", "folder", "object"]

# Мови інтерфейсу (EN/UK)
Language = Literal["en", "uk"]


@dataclass(frozen=True)
class ManifestObject:
    """Одиниця метаданих у маніфесті.

    guid        — глобальний ідентифікатор (UUID)
    type        — категорія для групування в дереві
    name        — внутрішнє ім'я (код), унікальне в межах parent
    title       — відображувана назва (локалізована або технічна)
    kind        — root/group/folder/object
    parent_guid — GUID батька (якщо це підпорядкований вузол)
    payload     — довільні метадані (JSON-сумісний dict)
    """

    guid: str
    type: ObjectType
    name: str
    title: str
    kind: NodeKind = "object"
    parent_guid: str = ""
    payload: Optional[Dict[str, Any]] = None
