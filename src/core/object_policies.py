"""src.core.object_policies

Единый источник правил (policies) для объектов manifest.

В MetaPlatform часть объектов ведут себя как "объекты 1С" — внутри них есть
системные разделы/подузлы (Формы, Команды, Макеты и т.д.). Другие объекты
(например, картинки/палитры) *не должны* получать эти подпапки.

Этот модуль фиксирует:

1) Реестр секций (SECTIONS) — какие "разделы" вообще существуют.
2) Политику объекта (ObjectPolicy) — какие секции разрешены конкретному типу.
3) Утилиты для принятия решения: создавать ли системные подпапки и какие
   legacy-узлы нужно скрывать в дереве.

Важно:
    Здесь нет UI-логики (иконки, виджеты и т.д.). Только правила.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Iterable, Optional


@dataclass(frozen=True, slots=True)
class SectionSpec:
    """Описание секции/раздела внутри объекта.

    Attributes:
        kind:
            Тип секции:
            - "folder" — секция представляется как папка (в manifest это узел kind=folder).
            - "schema" — секция является структурой/схемой (может быть визуальным узлом,
              но не обязана храниться как отдельный manifest-объект).

        i18n:
            Ключ локализации (только uk/en).
    """

    kind: str
    i18n: str


# Единый реестр всех поддерживаемых секций.
SECTIONS: Dict[str, SectionSpec] = {
    # Базовые секции
    "dimensions": SectionSpec(kind="schema", i18n="tree.dimensions"),
    "resources": SectionSpec(kind="schema", i18n="tree.resources"),
    "attributes": SectionSpec(kind="schema", i18n="tree.attributes"),
    "forms": SectionSpec(kind="folder", i18n="tree.forms"),
    "modules": SectionSpec(kind="folder", i18n="tree.modules"),
    "commands": SectionSpec(kind="folder", i18n="tree.commands"),
    "layouts": SectionSpec(kind="folder", i18n="tree.layouts"),
    "tabular_parts": SectionSpec(kind="schema", i18n="tree.tabularParts"),

    # Расширенные секции (для регистров/аналитики/Схем)
    "graphs": SectionSpec(kind="schema", i18n="tree.graphs"),
    "values": SectionSpec(kind="schema", i18n="tree.values"),
    "recalculations": SectionSpec(kind="schema", i18n="tree.recalculations"),
    # Реквизиты адресации (актуально для "Задач")
    "addressing_attributes": SectionSpec(kind="schema", i18n="tree.addressingAttributes"),
    "tables": SectionSpec(kind="schema", i18n="tree.tables"),
    "cubes": SectionSpec(kind="schema", i18n="tree.cubes"),
    "functions": SectionSpec(kind="schema", i18n="tree.functions"),

    # Доп. секции по структурам 1С (расширяемость через policy+sections)
    "columns": SectionSpec(kind="schema", i18n="tree.columns"),
    "totals": SectionSpec(kind="schema", i18n="tree.totals"),
    "recalculations_data": SectionSpec(kind="schema", i18n="tree.recalculationsData"),
    "recalculation_attributes": SectionSpec(kind="schema", i18n="tree.recalculationAttributes"),
}

_SECTION_DISPLAY_ORDER: tuple[str, ...] = (
    "forms",
    "layouts",
    "commands",
    "modules",
    "tabular_parts",
    "attributes",
    "dimensions",
    "resources",
    "graphs",
    "values",
    "recalculations",
    "addressing_attributes",
    "tables",
    "cubes",
    "functions",
    "columns",
    "totals",
    "recalculations_data",
    "recalculation_attributes",
)
_SECTION_DISPLAY_ORDER_INDEX: Dict[str, int] = {
    key: idx for idx, key in enumerate(_SECTION_DISPLAY_ORDER)
}


@dataclass(frozen=True, slots=True)
class ObjectPolicy:
    """Политика объекта manifest.

    Attributes:
        sections:
            Набор разрешённых секций для этого типа объекта.
            Пример: {"dimensions", "resources", "forms"}.

        has_object_folders:
            Совместимость со старым API. Если False — системные папки не создаются.
            Если True — системные папки создаются *только* для секций kind="folder",
            которые присутствуют в sections.
    """

    sections: FrozenSet[str]
    has_object_folders: bool = True


def _fs(items: Iterable[str]) -> FrozenSet[str]:
    return frozenset(str(x).strip() for x in items if str(x).strip())


# Политики типов объектов.
#
# ВАЖНО:
#   Набор folder/schema-секций должен соответствовать реальной структуре 1С,
#   иначе UI скрывает секцию как "лишнюю", а дочерние узлы теряют корректного
#   родителя в дереве.
OBJECT_POLICIES: Dict[str, ObjectPolicy] = {
    # Константы (в дереве не имеют разделов)
    "constants": ObjectPolicy(sections=_fs([])),

    # Справочники / документы (без форм)
    # В manifest тип создаваемого объекта обычно совпадает с типом группы,
    # поэтому поддерживаем и "ед." и "мн." варианты ключей.
    "catalog": ObjectPolicy(sections=_fs(["attributes", "tabular_parts", "forms", "modules", "commands", "layouts"])),
    "catalogs": ObjectPolicy(sections=_fs(["attributes", "tabular_parts", "forms", "modules", "commands", "layouts"])),

    "document": ObjectPolicy(sections=_fs(["attributes", "tabular_parts", "forms", "modules", "commands", "layouts"])),
    "documents": ObjectPolicy(sections=_fs(["attributes", "tabular_parts", "forms", "modules", "commands", "layouts"])),

    # Журналы документов: есть "Графы" + формы + системные папки
    "journal": ObjectPolicy(sections=_fs(["graphs", "forms", "modules", "commands", "layouts"])),
    "document_journals": ObjectPolicy(sections=_fs(["graphs", "forms", "modules", "commands", "layouts"])),

    # Перечисления: есть "Значения" + формы выбора + системные папки
    "enumeration": ObjectPolicy(sections=_fs(["values", "forms", "modules", "commands", "layouts"])),
    "enumerations": ObjectPolicy(sections=_fs(["values", "forms", "modules", "commands", "layouts"])),

    # Отчёты/обработки/планы/прочее (как минимум реквизиты/табличные части/формы/макеты/команды)
    "report": ObjectPolicy(sections=_fs(["attributes", "tabular_parts", "forms", "modules", "commands", "layouts"])),
    "reports": ObjectPolicy(sections=_fs(["attributes", "tabular_parts", "forms", "modules", "commands", "layouts"])),

    "data_processor": ObjectPolicy(sections=_fs(["attributes", "tabular_parts", "forms", "modules", "commands", "layouts"])),
    "data_processors": ObjectPolicy(sections=_fs(["attributes", "tabular_parts", "forms", "modules", "commands", "layouts"])),

    "chart_of_characteristic_types": ObjectPolicy(sections=_fs(["attributes", "tabular_parts", "forms", "modules", "commands", "layouts"])),

    "chart_of_accounts": ObjectPolicy(sections=_fs(["attributes", "tabular_parts", "modules", "commands", "layouts"])),

    "chart_of_calculation_types": ObjectPolicy(sections=_fs(["attributes", "tabular_parts", "modules", "commands", "layouts"])),

    # Бизнес-процессы/задачи
    "business_process": ObjectPolicy(sections=_fs(["attributes", "tabular_parts", "forms", "modules", "commands", "layouts"])),
    "business_processes": ObjectPolicy(sections=_fs(["attributes", "tabular_parts", "forms", "modules", "commands", "layouts"])),

    "task": ObjectPolicy(sections=_fs(["addressing_attributes", "attributes", "tabular_parts", "forms", "modules", "commands", "layouts"])),
    "tasks": ObjectPolicy(sections=_fs(["addressing_attributes", "attributes", "tabular_parts", "forms", "modules", "commands", "layouts"])),

    # Внешние источники данных
    "external_sources": ObjectPolicy(sections=_fs(["tables", "cubes", "functions"])),
    "external_data_sources": ObjectPolicy(sections=_fs(["tables", "cubes", "functions"])),

    # Регистры (форма есть)
    "register_info": ObjectPolicy(sections=_fs(["dimensions", "resources", "attributes", "forms", "modules", "commands", "layouts"])),
    "info_registers": ObjectPolicy(sections=_fs(["dimensions", "resources", "attributes", "forms", "modules", "commands", "layouts"])),

    "register_accum": ObjectPolicy(sections=_fs(["dimensions", "resources", "attributes", "forms", "modules", "commands", "layouts"])),
    "accumulation_registers": ObjectPolicy(sections=_fs(["dimensions", "resources", "attributes", "forms", "modules", "commands", "layouts"])),

    "register_accounting": ObjectPolicy(sections=_fs(["dimensions", "resources", "attributes", "forms", "modules", "commands", "layouts"])),
    "accounting_registers": ObjectPolicy(sections=_fs(["dimensions", "resources", "attributes", "forms", "modules", "commands", "layouts"])),

    "register_calc": ObjectPolicy(sections=_fs(["dimensions", "resources", "attributes", "recalculations", "forms", "modules", "commands", "layouts"])),
    "calculation_registers": ObjectPolicy(sections=_fs(["dimensions", "resources", "attributes", "recalculations", "forms", "modules", "commands", "layouts"])),

    # Ресурсные сущности (никаких подпапок)
    "common_picture": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "palette": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "common_palette": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "project_palette": ObjectPolicy(sections=_fs([]), has_object_folders=False),

    # ---- Загальні підтипи / Common subtypes ----

    # Підсистеми — без системних папок форми/команди; склад редагується окремо.
    "subsystem": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "subsystems": ObjectPolicy(sections=_fs([]), has_object_folders=False),

    # Загальні модулі — тільки модуль
    "common_module": ObjectPolicy(sections=_fs(["modules"])),
    "common_modules": ObjectPolicy(sections=_fs(["modules"])),

    # Параметри сеансу — без вкладених секцій
    "session_param": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "session_params": ObjectPolicy(sections=_fs([]), has_object_folders=False),

    # Ролі — без вкладених секцій
    "role": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "roles": ObjectPolicy(sections=_fs([]), has_object_folders=False),

    # Загальні реквізити — без вкладених секцій
    "common_attribute": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "common_attributes": ObjectPolicy(sections=_fs([]), has_object_folders=False),

    # Нумератори документів — без вкладених секцій
    "document_numerator": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "document_numerators": ObjectPolicy(sections=_fs([]), has_object_folders=False),

    # Плани обміну — реквізити + табличні частини + форми + модулі
    "exchange_plan": ObjectPolicy(sections=_fs(["attributes", "tabular_parts", "forms", "modules", "commands", "layouts"])),
    "exchange_plans": ObjectPolicy(sections=_fs(["attributes", "tabular_parts", "forms", "modules", "commands", "layouts"])),

    # Критерії відбору — без секцій
    "selection_criterion": ObjectPolicy(sections=_fs(["forms"])),
    "selection_criteria": ObjectPolicy(sections=_fs(["forms"])),

    # Підписки на події — без секцій
    "event_subscription": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "event_subscriptions": ObjectPolicy(sections=_fs([]), has_object_folders=False),

    # Регламентні завдання — без секцій
    "scheduled_job": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "scheduled_jobs": ObjectPolicy(sections=_fs([]), has_object_folders=False),

    # Послідовності — без вкладених секцій
    "sequence": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "sequences": ObjectPolicy(sections=_fs([]), has_object_folders=False),

    # Боти — без секцій
    "bot": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "bots": ObjectPolicy(sections=_fs([]), has_object_folders=False),

    # Функціональні опції — без секцій
    "functional_option": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "functional_options": ObjectPolicy(sections=_fs([]), has_object_folders=False),

    # Параметри функціональних опцій — без секцій
    "functional_option_param": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "functional_options_params": ObjectPolicy(sections=_fs([]), has_object_folders=False),

    # Визначені типи — без секцій
    "defined_type": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "defined_types": ObjectPolicy(sections=_fs([]), has_object_folders=False),

    # Сховища налаштувань — без секцій
    "settings_storage": ObjectPolicy(sections=_fs(["forms"])),
    "settings_storages": ObjectPolicy(sections=_fs(["forms"])),

    # Загальні команди — модуль команди
    "common_command": ObjectPolicy(sections=_fs(["modules"])),
    "common_commands": ObjectPolicy(sections=_fs(["modules"])),

    # Групи команд — без секцій
    "command_group": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "command_groups": ObjectPolicy(sections=_fs([]), has_object_folders=False),

    # Загальні форми — форма + модуль
    "common_form": ObjectPolicy(sections=_fs(["modules"])),
    "common_forms": ObjectPolicy(sections=_fs(["modules"])),

    # Загальні макети — без секцій
    "common_layout": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "common_layouts": ObjectPolicy(sections=_fs([]), has_object_folders=False),

    # XDTO-пакети — без секцій
    "xdto_package": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "xdto_packages": ObjectPolicy(sections=_fs([]), has_object_folders=False),

    # Web-сервіси — операції
    "web_service": ObjectPolicy(sections=_fs(["functions", "modules"])),
    "web_services": ObjectPolicy(sections=_fs(["functions", "modules"])),

    # HTTP-сервіси — методи
    "http_service": ObjectPolicy(sections=_fs(["functions", "modules"])),
    "http_services": ObjectPolicy(sections=_fs(["functions", "modules"])),

    # WS-посилання — без секцій
    "ws_link": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "ws_links": ObjectPolicy(sections=_fs([]), has_object_folders=False),

    # WebSocket-клієнти — без секцій
    "websocket_client": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "websocket_clients": ObjectPolicy(sections=_fs([]), has_object_folders=False),

    # Сервіси інтеграції — без секцій
    "integration_service": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "integration_services": ObjectPolicy(sections=_fs([]), has_object_folders=False),

    # Елементи стилю / Стилі — без секцій
    "style_element": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "style_elements": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "style": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "styles": ObjectPolicy(sections=_fs([]), has_object_folders=False),

    # Мови — без секцій
    "language": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "languages": ObjectPolicy(sections=_fs([]), has_object_folders=False),

    # Форма / Команда / Макет / Модуль як окремі вузли
    "form": ObjectPolicy(sections=_fs(["modules"])),
    "command": ObjectPolicy(sections=_fs(["modules"])),
    "layout": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "module": ObjectPolicy(sections=_fs([]), has_object_folders=False),
    "form_module": ObjectPolicy(sections=_fs([]), has_object_folders=False),
}


def get_object_policy(obj_type: str, payload: Any) -> ObjectPolicy:
    """Получить политику по типу объекта и payload.

    Правила:
        1) payload.no_object_folders == True => отключить подпапки.
        2) Явная политика из OBJECT_POLICIES, если есть.
        3) По умолчанию: подпапки включены, но список секций пуст.

    Примечание:
        Пустой список секций + has_object_folders=True означает "ничего не создаём",
        но сохраняем совместимость поведения по умолчанию.
    """

    p: Dict[str, Any] = payload if isinstance(payload, dict) else {}
    if bool(p.get("no_object_folders")):
        return ObjectPolicy(sections=_fs([]), has_object_folders=False)

    t = str(obj_type or "").strip()

    # Особый случай: "common" содержит подтипы объектов в payload.subtype.
    # Чтобы можно было задавать более точные политики, сначала пробуем subtype.
    if t == "common":
        subtype = str(p.get("subtype") or "").strip()
        if subtype:
            pol2 = OBJECT_POLICIES.get(subtype)
            if pol2 is not None:
                return pol2

    pol = OBJECT_POLICIES.get(t)
    if pol is not None:
        return pol

    return ObjectPolicy(sections=_fs([]), has_object_folders=True)


def should_create_object_folders(obj_type: str, payload: Any) -> bool:
    """Совместимый API: нужно ли создавать системные подпапки внутри объекта."""
    pol = get_object_policy(obj_type, payload)
    if not pol.has_object_folders:
        return False
    # Создаём подпапки только если есть хотя бы одна folder-секция.
    for sec in ordered_object_sections(obj_type, payload, kind="folder"):
        spec = SECTIONS.get(sec)
        if spec and spec.kind == "folder":
            return True
    return False


def is_legacy_object_folder_node(node_name: str) -> bool:
    """Проверить, что узел является legacy-папкой старого бага."""
    return str(node_name) in ("forms", "modules", "commands", "layouts")


def is_allowed_object_section(obj_type: str, payload: Any, section_key: str) -> bool:
    """True если секция разрешена политикой для данного объекта."""
    pol = get_object_policy(obj_type, payload)
    return str(section_key or "") in pol.sections


def section_i18n_key(section_key: str) -> Optional[str]:
    """Вернуть i18n-ключ для секции или None, если секция неизвестна."""
    spec = SECTIONS.get(str(section_key or ""))
    return spec.i18n if spec else None


def section_kind(section_key: str) -> Optional[str]:
    """Вернуть kind секции ("folder"/"schema") или None."""
    spec = SECTIONS.get(str(section_key or ""))
    return spec.kind if spec else None


def ordered_object_sections(obj_type: str, payload: Any, *, kind: Optional[str] = None) -> tuple[str, ...]:
    """Return policy sections in stable UI/storage order.

    ``ObjectPolicy.sections`` is a frozenset, so iterating over it directly can
    produce unstable section ordering in the tree and auto-created folders.
    """

    pol = get_object_policy(obj_type, payload)
    ordered = sorted(
        (str(sec or "").strip() for sec in pol.sections if str(sec or "").strip()),
        key=lambda sec: (_SECTION_DISPLAY_ORDER_INDEX.get(sec, 10_000), sec),
    )
    if kind is None:
        return tuple(ordered)
    return tuple(sec for sec in ordered if section_kind(sec) == kind)
