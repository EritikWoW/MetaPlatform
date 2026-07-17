"""src.configurator.persistence.db_seed

Первинне заповнення нової бази даних MetaPlatform.
Виконується один раз — при створенні нової БД.

Що заповнюється:
  1. Системна структура дерева метаданих (корінь + всі гілки як у 1С)
  2. Стандартні мови (Ukrainian, English)
  3. Стандартна роль «Адміністратор / Administrator»
  4. Загальний модуль «МодульПрограми / AppModule» (точка входу)
  5. Параметри сеансу за замовчуванням
  6. Властивості конфігурації (назва, версія, автор, ...)

Усі GUID системних об'єктів — детерміновані (UUIDv5-подібні через SHA-1),
щоб seed був ідемпотентним: повторний запуск не створить дублікатів.

EN/UK підтримка:
  Назви груп зберігаються у payload як {"title_en": "...", "title_uk": "..."},
  щоб UI міг локалізовано показувати їх незалежно від мови збереження.

Ієрархія:
    Конфігурація (root)
    ├── Загальні / General (group)
    │   ├── Підсистеми / Subsystems (folder)
    │   ├── Загальні модулі / Common modules (folder)
    │   │   └── МодульПрограми (object, seed)
    │   ├── Параметри сеансу / Session parameters (folder)
    │   ├── Ролі / Roles (folder)
    │   │   └── Адміністратор (object, seed)
    │   ├── Загальні реквізити / Common attributes (folder)
    │   ├── Плани обміну / Exchange plans (folder)
    │   ├── ... (всі стандартні папки)
    │   └── Мови / Languages (folder)
    │       ├── Ukrainian (object, seed)
    │       └── English (object, seed)
    ├── Константи / Constants (group)
    ├── Довідники / Catalogs (group)
    ├── Документи / Documents (group)
    ├── ... (всі групи)
    └── Зовнішні джерела даних / External data sources (group)
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, List, Optional, Tuple

from src.mpdb.mpdb import Mpdb
from src.configurator.manifest_schema import MANIFEST_TABLE


# ---------------------------------------------------------------------------
# GUID helpers (детерміновані, без stdlib uuid)
# ---------------------------------------------------------------------------

_SYS_GUID_NS_HEX = "1f8e4b8c2c6f4a3c9a2a3b7c9d2a1b10"  # 16 bytes — НЕ змінювати!


def _fmt_uuid(b: bytes) -> str:
    h = b.hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _sys_guid(key: str) -> str:
    """Детермінований GUID (UUIDv5-подібний через SHA-1).

    Однаковий ключ → однаковий GUID при будь-якому запуску.
    Це забезпечує ідемпотентність seed.
    """
    ns = bytes.fromhex(_SYS_GUID_NS_HEX)
    name = (key or "").encode("utf-8")
    digest = hashlib.sha1(ns + name).digest()[:16]
    b = bytearray(digest)
    b[6] = (b[6] & 0x0F) | 0x50  # version 5
    b[8] = (b[8] & 0x3F) | 0x80
    return _fmt_uuid(bytes(b))


def _new_guid() -> str:
    """Random UUIDv4 без stdlib uuid."""
    b = bytearray(os.urandom(16))
    b[6] = (b[6] & 0x0F) | 0x40
    b[8] = (b[8] & 0x3F) | 0x80
    return _fmt_uuid(bytes(b))


# ---------------------------------------------------------------------------
# GUID константи для стандартних вузлів
# (обчислюються один раз при завантаженні модуля)
# ---------------------------------------------------------------------------

GUID_ROOT              = _sys_guid("root:configuration")
GUID_GROUP_COMMON      = _sys_guid("group:common")
GUID_GROUP_CONSTANTS   = _sys_guid("group:constants")
GUID_GROUP_CATALOG     = _sys_guid("group:catalog")
GUID_GROUP_DOCUMENT    = _sys_guid("group:document")
GUID_GROUP_JOURNAL     = _sys_guid("group:journal")
GUID_GROUP_ENUM        = _sys_guid("group:enumeration")
GUID_GROUP_REPORT      = _sys_guid("group:report")
GUID_GROUP_PROCESSOR   = _sys_guid("group:data_processor")
GUID_GROUP_CHART_CHAR  = _sys_guid("group:chart_of_characteristic_types")
GUID_GROUP_CHART_ACC   = _sys_guid("group:chart_of_accounts")
GUID_GROUP_CHART_CALC  = _sys_guid("group:chart_of_calculation_types")
GUID_GROUP_REG_INFO    = _sys_guid("group:register_info")
GUID_GROUP_REG_ACCUM   = _sys_guid("group:register_accum")
GUID_GROUP_REG_ACCT    = _sys_guid("group:register_accounting")
GUID_GROUP_REG_CALC    = _sys_guid("group:register_calc")
GUID_GROUP_BP          = _sys_guid("group:business_process")
GUID_GROUP_TASK        = _sys_guid("group:task")
GUID_GROUP_EXT_SRC     = _sys_guid("group:external_sources")

# Стандартні папки в «Загальні»
GUID_FOLDER_SUBSYSTEMS         = _sys_guid("common:subsystems")
GUID_FOLDER_COMMON_MODULES     = _sys_guid("common:common_modules")
GUID_FOLDER_SESSION_PARAMS     = _sys_guid("common:session_params")
GUID_FOLDER_ROLES              = _sys_guid("common:roles")
GUID_FOLDER_COMMON_ATTRS       = _sys_guid("common:common_attributes")
GUID_FOLDER_EXCHANGE_PLANS     = _sys_guid("common:exchange_plans")
GUID_FOLDER_SELECTION_CRIT     = _sys_guid("common:selection_criteria")
GUID_FOLDER_EVENT_SUBS         = _sys_guid("common:event_subscriptions")
GUID_FOLDER_SCHED_JOBS         = _sys_guid("common:scheduled_jobs")
GUID_FOLDER_BOTS               = _sys_guid("common:bots")
GUID_FOLDER_FUNC_OPTIONS       = _sys_guid("common:functional_options")
GUID_FOLDER_FUNC_OPT_PARAMS    = _sys_guid("common:functional_options_params")
GUID_FOLDER_DEFINED_TYPES      = _sys_guid("common:defined_types")
GUID_FOLDER_SETTINGS_STORAGES  = _sys_guid("common:settings_storages")
GUID_FOLDER_COMMON_COMMANDS    = _sys_guid("common:common_commands")
GUID_FOLDER_COMMAND_GROUPS     = _sys_guid("common:command_groups")
GUID_FOLDER_COMMON_FORMS       = _sys_guid("common:common_forms")
GUID_FOLDER_COMMON_LAYOUTS     = _sys_guid("common:common_layouts")
GUID_FOLDER_COMMON_PICTURES    = _sys_guid("common:common_pictures")
GUID_FOLDER_XDTO_PACKAGES      = _sys_guid("common:xdto_packages")
GUID_FOLDER_WEB_SERVICES       = _sys_guid("common:web_services")
GUID_FOLDER_HTTP_SERVICES      = _sys_guid("common:http_services")
GUID_FOLDER_WS_LINKS           = _sys_guid("common:ws_links")
GUID_FOLDER_WS_CLIENTS         = _sys_guid("common:websocket_clients")
GUID_FOLDER_INTEGRATION        = _sys_guid("common:integration_services")
GUID_FOLDER_STYLE_ELEMENTS     = _sys_guid("common:style_elements")
GUID_FOLDER_STYLES             = _sys_guid("common:styles")
GUID_FOLDER_LANGUAGES          = _sys_guid("common:languages")
GUID_FOLDER_DOC_NUMERATORS     = _sys_guid("common:document_numerators")
GUID_FOLDER_SEQUENCES          = _sys_guid("common:sequences")

# Стандартні об'єкти-насіння
GUID_LANG_UK               = _sys_guid("language:Ukrainian")
GUID_LANG_EN               = _sys_guid("language:English")
GUID_ROLE_ADMIN            = _sys_guid("role:Administrator")
GUID_MODULE_APP            = _sys_guid("common_module:AppModule")


# ---------------------------------------------------------------------------
# Low-level: вставка рядка якщо його немає
# ---------------------------------------------------------------------------

def _insert_if_missing(db: Mpdb, row: Dict[str, Any]) -> bool:
    """Вставити рядок в manifest. Повертає True якщо вставлено, False якщо вже є.

    Ідемпотентний: duplicate GUID → не падає, просто пропускає.
    """
    try:
        db.table(MANIFEST_TABLE).insert(row)
        return True
    except Exception:
        return False


def _make_row(
    guid: str,
    obj_type: str,
    name: str,
    title: str,
    kind: str,
    parent_guid: str,
    *,
    order: int = 0,
    system: bool = True,
    protected: bool = True,
    seed: bool = True,
    menu: str = "add_only",
    extra: Optional[Dict[str, Any]] = None,
    title_en: str = "",
    title_uk: str = "",
) -> Dict[str, Any]:
    """Сформувати рядок для manifest з усіма полями."""
    payload: Dict[str, Any] = {
        "order": order,
    }
    if system:
        payload["system"] = True
    if protected:
        payload["protected"] = True
    if seed:
        payload["seed"] = True
    if menu:
        payload["menu"] = menu
    # Зберігаємо обидві локалізації в payload щоб UI міг перемкнутись
    if title_en:
        payload["title_en"] = title_en
    if title_uk:
        payload["title_uk"] = title_uk
    if extra:
        payload.update(extra)

    return {
        "guid": guid,
        "type": obj_type,
        "name": name,
        "title": title,
        "kind": kind,
        "parent_guid": parent_guid,
        "payload": payload,
    }


# ---------------------------------------------------------------------------
# Seed: корінь + основні групи (як у 1С)
# ---------------------------------------------------------------------------

# Дані груп: (type_code, order, title_uk, title_en)
_MAIN_GROUPS: List[Tuple[str, str, int, str, str]] = [
    # (guid_const_name, type_code, order, title_uk, title_en)
    # Порядок — як у 1С Конфігураторі
    ("common",                        "common",                        10,  "Загальні",                      "General"),
    ("constants",                     "constants",                     20,  "Константи",                     "Constants"),
    ("catalog",                       "catalog",                       30,  "Довідники",                     "Catalogs"),
    ("document",                      "document",                      40,  "Документи",                     "Documents"),
    ("journal",                       "journal",                       50,  "Журнали документів",             "Document journals"),
    ("enumeration",                   "enumeration",                   60,  "Перерахування",                 "Enumerations"),
    ("report",                        "report",                        70,  "Звіти",                         "Reports"),
    ("data_processor",                "data_processor",                80,  "Обробки",                       "Data processors"),
    ("chart_of_characteristic_types", "chart_of_characteristic_types", 90,  "Плани видів характеристик",     "Characteristic type charts"),
    ("chart_of_accounts",             "chart_of_accounts",            100,  "Плани рахунків",                "Chart of accounts"),
    ("chart_of_calculation_types",    "chart_of_calculation_types",   110,  "Плани видів розрахунку",        "Calculation type charts"),
    ("register_info",                 "register_info",                120,  "Регістри відомостей",           "Information registers"),
    ("register_accum",                "register_accum",               130,  "Регістри накопичення",          "Accumulation registers"),
    ("register_accounting",           "register_accounting",          140,  "Регістри бухгалтерії",          "Accounting registers"),
    ("register_calc",                 "register_calc",                150,  "Регістри розрахунку",           "Calculation registers"),
    ("business_process",              "business_process",             160,  "Бізнес-процеси",                "Business processes"),
    ("task",                          "task",                         170,  "Завдання",                      "Tasks"),
    ("external_sources",              "external_sources",             180,  "Зовнішні джерела даних",        "External data sources"),
]

# Папки у «Загальні»: (guid, name, order, title_uk, title_en, subtype)
_COMMON_FOLDERS: List[Tuple[str, str, int, str, str, str]] = [
    (GUID_FOLDER_SUBSYSTEMS,        "subsystems",               10,  "Підсистеми",                         "Subsystems",                    "subsystem"),
    (GUID_FOLDER_COMMON_MODULES,    "common_modules",           20,  "Загальні модулі",                    "Common modules",                "common_module"),
    (GUID_FOLDER_SESSION_PARAMS,    "session_params",           30,  "Параметри сеансу",                   "Session parameters",            "session_param"),
    (GUID_FOLDER_ROLES,             "roles",                    40,  "Ролі",                               "Roles",                         "role"),
    (GUID_FOLDER_COMMON_ATTRS,      "common_attributes",        50,  "Загальні реквізити",                 "Common attributes",             "common_attribute"),
    (GUID_FOLDER_EXCHANGE_PLANS,    "exchange_plans",           60,  "Плани обміну",                       "Exchange plans",                "exchange_plan"),
    (GUID_FOLDER_SELECTION_CRIT,    "selection_criteria",       70,  "Критерії відбору",                   "Selection criteria",            "selection_criterion"),
    (GUID_FOLDER_EVENT_SUBS,        "event_subscriptions",      80,  "Підписки на події",                  "Event subscriptions",           "event_subscription"),
    (GUID_FOLDER_SCHED_JOBS,        "scheduled_jobs",           90,  "Регламентні завдання",               "Scheduled jobs",                "scheduled_job"),
    (GUID_FOLDER_BOTS,              "bots",                    100,  "Боти",                               "Bots",                          "bot"),
    (GUID_FOLDER_FUNC_OPTIONS,      "functional_options",      110,  "Функціональні опції",                "Functional options",            "functional_option"),
    (GUID_FOLDER_FUNC_OPT_PARAMS,   "functional_options_params",120, "Параметри функціональних опцій",     "Functional option parameters",  "functional_option_param"),
    (GUID_FOLDER_DEFINED_TYPES,     "defined_types",           130,  "Визначені типи",                    "Defined types",                 "defined_type"),
    (GUID_FOLDER_SETTINGS_STORAGES, "settings_storages",       140,  "Сховища налаштувань",                "Settings storages",             "settings_storage"),
    (GUID_FOLDER_COMMON_COMMANDS,   "common_commands",         150,  "Загальні команди",                   "Common commands",               "common_command"),
    (GUID_FOLDER_COMMAND_GROUPS,    "command_groups",          160,  "Групи команд",                       "Command groups",                "command_group"),
    (GUID_FOLDER_COMMON_FORMS,      "common_forms",            170,  "Загальні форми",                     "Common forms",                  "common_form"),
    (GUID_FOLDER_COMMON_LAYOUTS,    "common_layouts",          180,  "Загальні макети",                    "Common layouts",                "common_layout"),
    (GUID_FOLDER_COMMON_PICTURES,   "common_pictures",         190,  "Загальні картинки",                  "Common pictures",               "common_picture"),
    (GUID_FOLDER_XDTO_PACKAGES,     "xdto_packages",           200,  "XDTO-пакети",                       "XDTO packages",                 "xdto_package"),
    (GUID_FOLDER_WEB_SERVICES,      "web_services",            210,  "Web-сервіси",                        "Web services",                  "web_service"),
    (GUID_FOLDER_HTTP_SERVICES,     "http_services",           220,  "HTTP-сервіси",                       "HTTP services",                 "http_service"),
    (GUID_FOLDER_WS_LINKS,          "ws_links",                230,  "WS-посилання",                       "WS links",                      "ws_link"),
    (GUID_FOLDER_WS_CLIENTS,        "websocket_clients",       240,  "WebSocket-клієнти",                  "WebSocket clients",             "websocket_client"),
    (GUID_FOLDER_INTEGRATION,       "integration_services",    250,  "Сервіси інтеграції",                 "Integration services",          "integration_service"),
    (GUID_FOLDER_STYLE_ELEMENTS,    "style_elements",          260,  "Елементи стилю",                     "Style elements",                "style_element"),
    (GUID_FOLDER_STYLES,            "styles",                  270,  "Стилі",                              "Styles",                        "style"),
    (GUID_FOLDER_LANGUAGES,         "languages",               280,  "Мови",                               "Languages",                     "language"),
    (GUID_FOLDER_DOC_NUMERATORS,    "document_numerators",     290,  "Нумератори документів",              "Document numerators",           "document_numerator"),
    (GUID_FOLDER_SEQUENCES,         "sequences",               300,  "Послідовності",                      "Sequences",                     "sequence"),
]


def _seed_tree_structure(db: Mpdb) -> None:
    """Засіяти дерево метаданих: корінь + групи + папки Загальні.

    Ідемпотентно: повторний виклик нічого не ламає.
    """
    # Корінь «Конфігурація»
    _insert_if_missing(db, _make_row(
        guid=GUID_ROOT,
        obj_type="configuration",
        name="Configuration",
        title="Конфігурація",
        kind="root",
        parent_guid="",
        order=0,
        title_en="Configuration",
        title_uk="Конфігурація",
        extra={
            "version": "1.0.0",
            "author": "",
            "description_en": "",
            "description_uk": "",
            "vendor": "",
            "update_address": "",
            "default_language": "uk",
            "compatibility_mode": "1.0",
            "managed_application_module": f"module://{GUID_MODULE_APP}",
            "session_module": "",
            "external_connection_module": "",
            "ordinary_application_module": "",
            "startup_modules": [f"module://{GUID_MODULE_APP}"],
        },
    ))

    # Основні групи
    for type_code, _, order, title_uk, title_en in _MAIN_GROUPS:
        guid = _sys_guid(f"group:{type_code}")
        _insert_if_missing(db, _make_row(
            guid=guid,
            obj_type=type_code,
            name=type_code,
            title=title_uk,       # дефолт — українська
            kind="group",
            parent_guid=GUID_ROOT,
            order=order,
            title_en=title_en,
            title_uk=title_uk,
        ))

    # Папки у «Загальні»
    for (folder_guid, name, order, title_uk, title_en, subtype) in _COMMON_FOLDERS:
        _insert_if_missing(db, _make_row(
            guid=folder_guid,
            obj_type="common",
            name=name,
            title=title_uk,
            kind="folder",
            parent_guid=GUID_GROUP_COMMON,
            order=order,
            title_en=title_en,
            title_uk=title_uk,
            extra={"subtype": subtype},
        ))


# ---------------------------------------------------------------------------
# Seed: стандартні мови
# ---------------------------------------------------------------------------

def _seed_languages(db: Mpdb) -> None:
    """Засіяти стандартні мови: Ukrainian (uk) та English (en)."""

    languages = [
        (GUID_LANG_UK, "Ukrainian", "Українська", "uk",
         {"code": "uk", "title_uk": "Українська",    "title_en": "Ukrainian",   "default": True}),
        (GUID_LANG_EN, "English",   "Англійська",   "en",
         {"code": "en", "title_uk": "Англійська",    "title_en": "English",     "default": False}),
    ]

    for guid, name, title_uk, code, extra in languages:
        _insert_if_missing(db, _make_row(
            guid=guid,
            obj_type="language",
            name=name,
            title=title_uk,
            kind="object",
            parent_guid=GUID_FOLDER_LANGUAGES,
            order=languages.index((guid, name, title_uk, code, extra)),
            title_uk=title_uk,
            title_en=name,
            extra=extra,
        ))


# ---------------------------------------------------------------------------
# Seed: стандартні ролі
# ---------------------------------------------------------------------------

def _seed_roles(db: Mpdb) -> None:
    """Засіяти базову роль Адміністратор / Administrator."""

    _insert_if_missing(db, _make_row(
        guid=GUID_ROLE_ADMIN,
        obj_type="role",
        name="Administrator",
        title="Адміністратор",
        kind="object",
        parent_guid=GUID_FOLDER_ROLES,
        order=0,
        title_uk="Адміністратор",
        title_en="Administrator",
        extra={
            "description_uk": "Повний доступ до всіх об'єктів конфігурації",
            "description_en": "Full access to all configuration objects",
            "is_admin": True,
            "permissions": {
                "all_objects": "full",
                "interactive": True,
                "output": True,
            },
        },
    ))


# ---------------------------------------------------------------------------
# Seed: загальний модуль «МодульПрограми / AppModule»
# ---------------------------------------------------------------------------

_APP_MODULE_TEMPLATE_UK = """\
// МодульПрограми — точка входу конфігурації.
// Викликається при запуску клієнтського застосунку.
//
// Процедура ПриПочаткуРоботиСистеми()
//     // Ваш код ініціалізації
// КінецьПроцедури

Процедура ПриПочаткуРоботиСистеми()

КінецьПроцедури
"""

_APP_MODULE_TEMPLATE_EN = """\
// AppModule — configuration entry point.
// Called when the client application starts.
//
// Procedure OnSystemStartup()
//     // Your initialization code
// EndProcedure

Procedure OnSystemStartup()

EndProcedure
"""


def _seed_common_modules(db: Mpdb) -> None:
    """Засіяти загальний модуль МодульПрограми / AppModule."""

    _insert_if_missing(db, _make_row(
        guid=GUID_MODULE_APP,
        obj_type="common_module",
        name="AppModule",
        title="МодульПрограми",
        kind="object",
        parent_guid=GUID_FOLDER_COMMON_MODULES,
        order=0,
        title_uk="МодульПрограми",
        title_en="AppModule",
        extra={
            "description_uk": "Точка входу — виконується при старті застосунку",
            "description_en": "Entry point — runs on application startup",
            "server": False,
            "client": True,
            "external_connection": False,
            "global": True,
            "privileged": False,
            "return_values_reuse": "dont_use",
            # Код зберігається як asset у mpdb, але шаблон кладемо в payload
            # для першого відкриття редактора коду
            "module_template_uk": _APP_MODULE_TEMPLATE_UK,
            "module_template_en": _APP_MODULE_TEMPLATE_EN,
        },
    ))


# ---------------------------------------------------------------------------
# Seed: параметри сеансу
# ---------------------------------------------------------------------------

def _seed_session_params(db: Mpdb) -> None:
    """Засіяти базові параметри сеансу."""

    params = [
        ("CurrentUser",     "ПоточнийКористувач", "Поточний користувач",  "Current user",
         {"type": "CatalogRef", "type_ref": "Users", "description_uk": "Поточний користувач системи"}),
        ("CurrentLanguage",  "ПоточнаМова",        "Поточна мова",          "Current language",
         {"type": "String",    "length": 5,          "description_uk": "Код мови: uk або en"}),
    ]

    for i, (name_en, name_uk, title_uk, title_en, extra) in enumerate(params):
        _insert_if_missing(db, _make_row(
            guid=_sys_guid(f"session_param:{name_en}"),
            obj_type="session_param",
            name=name_en,
            title=title_uk,
            kind="object",
            parent_guid=GUID_FOLDER_SESSION_PARAMS,
            order=i,
            title_uk=title_uk,
            title_en=title_en,
            extra={**extra, "name_uk": name_uk, "name_en": name_en},
        ))


# ---------------------------------------------------------------------------
# Властивості конфігурації (зберігаються в payload кореня)
# ---------------------------------------------------------------------------

def _patch_root_properties(db: Mpdb, *, name: str = "NewConfiguration") -> None:
    """Оновити властивості кореня конфігурації після створення.

    Це корекція дефолтного name який вводить користувач у wizard.
    Якщо ім'я не задано — залишаємо «NewConfiguration».
    """
    try:
        rows = db.table(MANIFEST_TABLE).select() or []
        for r in rows:
            if str(r.get("guid", "")) == GUID_ROOT:
                payload = r.get("payload") or {}
                if isinstance(payload, dict):
                    current_name = payload.get("config_name", "")
                    if not current_name:
                        # Оновлення через rebuild — делегуємо manifest_io
                        pass  # буде оновлено через update_root_properties()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Головний entry point
# ---------------------------------------------------------------------------

def run_full_seed(db: Mpdb, *, config_name: str = "NewConfiguration") -> None:
    """Повне первинне заповнення нової бази даних.

    Послідовність важлива:
    1. Структура дерева (корінь + групи + папки) — перед усім іншим,
       бо seed-об'єкти посилаються на GUID папок.
    2. Мови — одні з перших об'єктів, потрібні для локалізації.
    3. Ролі — потрібні для системи прав.
    4. Загальні модулі — точка входу конфігурації.
    5. Параметри сеансу — базові параметри runtime.

    Ідемпотентний: безпечно викликати повторно.
    """
    _seed_tree_structure(db)
    _seed_languages(db)
    _seed_roles(db)
    _seed_common_modules(db)
    _seed_session_params(db)
    _patch_root_properties(db, name=config_name)


# ---------------------------------------------------------------------------
# Утиліти для доступу до GUID стандартних вузлів
# (використовується з інших модулів)
# ---------------------------------------------------------------------------

def get_group_guid(type_code: str) -> str:
    """Повернути GUID стандартної групи за кодом типу.

    Наприклад: get_group_guid("catalog") → GUID_GROUP_CATALOG
    """
    return _sys_guid(f"group:{type_code}")


def get_common_folder_guid(folder_name: str) -> str:
    """Повернути GUID стандартної папки в «Загальні» за іменем.

    Наприклад: get_common_folder_guid("roles") → GUID_FOLDER_ROLES
    """
    return _sys_guid(f"common:{folder_name}")


def get_root_guid() -> str:
    """Повернути GUID кореня конфігурації."""
    return GUID_ROOT


# Словник для зручного пошуку GUID папок «Загальні» за subtype
COMMON_FOLDER_BY_SUBTYPE: Dict[str, str] = {
    subtype: folder_guid
    for (folder_guid, _name, _order, _uk, _en, subtype) in _COMMON_FOLDERS
}

# Словник назв груп: type_code → {uk, en}
GROUP_TITLES: Dict[str, Dict[str, str]] = {
    type_code: {"uk": title_uk, "en": title_en}
    for (type_code, _, _order, title_uk, title_en) in _MAIN_GROUPS
}

# Словник назв папок «Загальні»: name → {uk, en}
COMMON_FOLDER_TITLES: Dict[str, Dict[str, str]] = {
    name: {"uk": title_uk, "en": title_en}
    for (_guid, name, _order, title_uk, title_en, _subtype) in _COMMON_FOLDERS
}
