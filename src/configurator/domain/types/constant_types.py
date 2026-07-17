# src/configurator/domain/types/constant_types.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional


@dataclass(frozen=True)
class ConstType:
    """
    Описание одного типа данных константы.
    code: стабильный код (хранится в payload/manifest)
    title: локализуемое имя для UI (ключ или уже готовая строка)
    group: категория для дерева выбора типов (как в 1С)
    kind: 'primitive' | 'reference' | 'special'
    params_schema: описание параметров типа (длина, точность, составной и т.д.)
    """
    code: str
    title: str
    group: str
    kind: str = "primitive"
    params_schema: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TypeGroup:
    code: str
    title: str
    order: int = 0


# --- Группы (как в 1С, можно расширять) ---
GROUPS: List[TypeGroup] = [
    TypeGroup("primitives", "Примитивы", 10),
    TypeGroup("references", "Ссылочные типы", 20),
    TypeGroup("special", "Специальные", 30),
]

# --- Базовые типы (примерный минимум, дальше расширяется) ---
_BASE_TYPES: List[ConstType] = [
    # primitives
    ConstType("number", "Число", "primitives", "primitive", {"precision": "int", "scale": "int"}),
    ConstType("string", "Строка", "primitives", "primitive", {"length": "int", "unlimited": "bool"}),
    ConstType("date", "Дата", "primitives", "primitive"),
    ConstType("boolean", "Булево", "primitives", "primitive"),
    ConstType("storage", "ХранилищеЗначения", "special", "special"),

    # special uuid
    ConstType("uuid", "УникальныйИдентификатор", "special", "special"),
]

# --- Ссылочные типы (почти любой объект конфигурации) ---
# В 1С это выглядит как <ВидОбъекта>Ссылка (СправочникСсылка, ДокументСсылка...).
# Здесь важен стабильный код, чтобы хранить в payload.
_REFERENCE_TYPES: List[ConstType] = [
    ConstType("ref.catalog", "СправочникСсылка", "references", "reference"),
    ConstType("ref.document", "ДокументСсылка", "references", "reference"),
    ConstType("ref.enum", "ПеречислениеСсылка", "references", "reference"),
    ConstType("ref.chart_of_characteristic_types", "ПланВидовХарактеристикСсылка", "references", "reference"),
    ConstType("ref.chart_of_accounts", "ПланСчетовСсылка", "references", "reference"),
    ConstType("ref.chart_of_calculation_types", "ПланВидовРасчетаСсылка", "references", "reference"),
    ConstType("ref.business_process", "БизнесПроцессСсылка", "references", "reference"),
    ConstType("ref.task", "ЗадачаСсылка", "references", "reference"),
    ConstType("ref.exchange_plan", "ПланОбменаСсылка", "references", "reference"),
    ConstType("ref.any", "ЛюбаяСсылка", "references", "reference"),
]

# --- Публичный реестр ---
def iter_all_types() -> Iterable[ConstType]:
    yield from _BASE_TYPES
    yield from _REFERENCE_TYPES


def get_type_registry() -> Dict[str, ConstType]:
    """code -> ConstType"""
    return {t.code: t for t in iter_all_types()}


def get_grouped_types() -> Dict[str, List[ConstType]]:
    """group_code -> [types...]"""
    grouped: Dict[str, List[ConstType]] = {}
    for t in iter_all_types():
        grouped.setdefault(t.group, []).append(t)
    # Можно сортировать внутри группы по title
    for k in list(grouped.keys()):
        grouped[k] = sorted(grouped[k], key=lambda x: x.title)
    return grouped


def find_type(code: str) -> Optional[ConstType]:
    return get_type_registry().get((code or "").strip())
