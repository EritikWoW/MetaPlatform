"""Keyword registry for MetaScript.

Public working DSL languages are:
  - Ukrainian (``uk``)
  - English (``en``)

The internal ``mixed`` profile exists only for compatibility with imported
1C/BAS modules. It accepts Ukrainian + English + Russian source keywords so
legacy BSL can be parsed, normalized and translated, but Russian is not a
first-class project locale.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from .tokens import TokenType


DslLanguage = Literal["uk", "en", "mixed"]
TargetDslLanguage = Literal["uk", "en"]


@dataclass(frozen=True, slots=True)
class LanguageProfile:
    language: DslLanguage
    keywords: dict[str, TokenType]


@dataclass(frozen=True, slots=True)
class IdentifierNormalizationProfile:
    callables: dict[str, str]
    methods: dict[str, str]
    constructors: dict[str, str]


def _lowered(mapping: dict[str, TokenType]) -> dict[str, TokenType]:
    return {str(k).lower(): v for k, v in mapping.items()}


def _lowered_str_map(mapping: dict[str, str]) -> dict[str, str]:
    return {str(k).lower(): str(v) for k, v in mapping.items()}


# ---------------------------------------------------------------------------
# Canonical target surfaces for real project locales.
# These are the only surfaces we generate during module normalization.
# ---------------------------------------------------------------------------

_UK_TARGETS: dict[TokenType, str] = {
    "TRUE": "Істина",
    "FALSE": "Хибність",
    "UNDEFINED": "Невизначено",
    "NULL": "Нуль",
    "NOT": "Не",
    "AND": "Та",
    "OR": "Або",
    "KW_IF": "Якщо",
    "KW_THEN": "Тоді",
    "KW_ELSEIF": "ІнакшеЯкщо",
    "KW_ELSE": "Інакше",
    "KW_ENDIF": "КінецьЯкщо",
    "KW_FOR": "Для",
    "KW_EACH": "Кожного",
    "KW_IN": "З",
    "KW_TO": "По",
    "KW_DO": "Цикл",
    "KW_ENDDO": "КінецьЦиклу",
    "KW_WHILE": "Поки",
    "KW_ENDWHILE": "КінецьПоки",
    "KW_BREAK": "Перервати",
    "KW_CONTINUE": "Продовжити",
    "KW_RETURN": "Повернути",
    "KW_TRY": "Спроба",
    "KW_EXCEPT": "Виняток",
    "KW_RAISE": "Викинути",
    "KW_ENDTRY": "КінецьСпроби",
    "KW_PROCEDURE": "Процедура",
    "KW_ENDPROCEDURE": "КінецьПроцедури",
    "KW_FUNCTION": "Функція",
    "KW_ENDFUNCTION": "КінецьФункції",
    "KW_VAR": "Змін",
    "KW_EXPORT": "Експорт",
    "KW_VAL": "Знач",
    "KW_NEW": "Новий",
    "KW_DELETE": "Видалити",
    "KW_GOTO": "Перейти",
    "KW_IF_COMPILE": "Якщо",
    "KW_THEN_COMPILE": "Тоді",
    "KW_ELSEIF_COMPILE": "ІнакшеЯкщо",
    "KW_ELSE_COMPILE": "Інакше",
    "KW_ENDIF_COMPILE": "КінецьЯкщо",
    "KW_REGION": "Область",
    "KW_ENDREGION": "КінецьОбласті",
    "KW_USE": "Використати",
    "KW_CATALOG": "Довідник",
    "KW_DOCUMENT": "Документ",
    "KW_REGISTER": "Регістр",
    "KW_ENUM": "Перерахування",
    "KW_FORM": "Форма",
    "KW_FIELDS": "Реквізити",
    "KW_TABLE": "Таблиця",
    "KW_DIMENSIONS": "Виміри",
    "KW_RESOURCES": "Ресурси",
    "KW_MODULE": "Модуль",
    "KW_SUBSYSTEM": "Підсистема",
    "KW_ROLE": "Роль",
}

_EN_TARGETS: dict[TokenType, str] = {
    "TRUE": "True",
    "FALSE": "False",
    "UNDEFINED": "Undefined",
    "NULL": "Null",
    "NOT": "Not",
    "AND": "And",
    "OR": "Or",
    "KW_IF": "If",
    "KW_THEN": "Then",
    "KW_ELSEIF": "ElsIf",
    "KW_ELSE": "Else",
    "KW_ENDIF": "EndIf",
    "KW_FOR": "For",
    "KW_EACH": "Each",
    "KW_IN": "In",
    "KW_TO": "To",
    "KW_DO": "Do",
    "KW_ENDDO": "EndDo",
    "KW_WHILE": "While",
    "KW_ENDWHILE": "EndWhile",
    "KW_BREAK": "Break",
    "KW_CONTINUE": "Continue",
    "KW_RETURN": "Return",
    "KW_TRY": "Try",
    "KW_EXCEPT": "Except",
    "KW_RAISE": "Raise",
    "KW_ENDTRY": "EndTry",
    "KW_PROCEDURE": "Procedure",
    "KW_ENDPROCEDURE": "EndProcedure",
    "KW_FUNCTION": "Function",
    "KW_ENDFUNCTION": "EndFunction",
    "KW_VAR": "Var",
    "KW_EXPORT": "Export",
    "KW_VAL": "Val",
    "KW_NEW": "New",
    "KW_DELETE": "Delete",
    "KW_GOTO": "Goto",
    "KW_IF_COMPILE": "If",
    "KW_THEN_COMPILE": "Then",
    "KW_ELSEIF_COMPILE": "ElsIf",
    "KW_ELSE_COMPILE": "Else",
    "KW_ENDIF_COMPILE": "EndIf",
    "KW_REGION": "Region",
    "KW_ENDREGION": "EndRegion",
    "KW_USE": "Use",
    "KW_CATALOG": "Catalog",
    "KW_DOCUMENT": "Document",
    "KW_REGISTER": "Register",
    "KW_ENUM": "Enum",
    "KW_FORM": "Form",
    "KW_FIELDS": "Fields",
    "KW_TABLE": "Table",
    "KW_DIMENSIONS": "Dimensions",
    "KW_RESOURCES": "Resources",
    "KW_MODULE": "Module",
    "KW_SUBSYSTEM": "Subsystem",
    "KW_ROLE": "Role",
}


# ---------------------------------------------------------------------------
# Source keyword aliases by language family.
# Ukrainian and English are real DSL languages.
# Russian aliases are import-compatibility only.
# ---------------------------------------------------------------------------

_UK_ALIASES = _lowered({
    "Правда": "TRUE",
    "Істина": "TRUE",
    "Хиба": "FALSE",
    "Хибність": "FALSE",
    "Невизначено": "UNDEFINED",
    "Нуль": "NULL",
    "Не": "NOT",
    "Та": "AND",
    "Або": "OR",
    "Якщо": "KW_IF",
    "Тоді": "KW_THEN",
    "То": "KW_THEN",
    "ІнакшеЯкщо": "KW_ELSEIF",
    "Інакше": "KW_ELSE",
    "КінецьЯкщо": "KW_ENDIF",
    "КінцяЯкщо": "KW_ENDIF",
    "Для": "KW_FOR",
    "Кожного": "KW_EACH",
    "З": "KW_IN",
    "По": "KW_TO",
    "До": "KW_TO",
    "Виконати": "KW_DO",
    "Цикл": "KW_DO",
    "КінецьЦиклу": "KW_ENDDO",
    "КінцяЦиклу": "KW_ENDDO",
    "Поки": "KW_WHILE",
    "КінецьПоки": "KW_ENDWHILE",
    "Перервати": "KW_BREAK",
    "Продовжити": "KW_CONTINUE",
    "Повернути": "KW_RETURN",
    "Спроба": "KW_TRY",
    "Виняток": "KW_EXCEPT",
    "Викинути": "KW_RAISE",
    "КінецьСпроби": "KW_ENDTRY",
    "Процедура": "KW_PROCEDURE",
    "КінецьПроцедури": "KW_ENDPROCEDURE",
    "Функція": "KW_FUNCTION",
    "КінецьФункції": "KW_ENDFUNCTION",
    "Змін": "KW_VAR",
    "Перем": "KW_VAR",
    "Експорт": "KW_EXPORT",
    "Знач": "KW_VAL",
    "Новий": "KW_NEW",
    "Нове": "KW_NEW",
    "Видалити": "KW_DELETE",
    "Перейти": "KW_GOTO",
    "Довідник": "KW_CATALOG",
    "Документ": "KW_DOCUMENT",
    "Регістр": "KW_REGISTER",
    "Перерахування": "KW_ENUM",
    "Форма": "KW_FORM",
    "Реквізити": "KW_FIELDS",
    "Таблиця": "KW_TABLE",
    "ТабличнаЧастина": "KW_TABLE",
    "Таблична": "KW_TABLE",
    "Виміри": "KW_DIMENSIONS",
    "Ресурси": "KW_RESOURCES",
    "Модуль": "KW_MODULE",
    "Підсистема": "KW_SUBSYSTEM",
    "Роль": "KW_ROLE",
})

_EN_ALIASES = _lowered({
    "True": "TRUE",
    "False": "FALSE",
    "Undefined": "UNDEFINED",
    "Null": "NULL",
    "Not": "NOT",
    "And": "AND",
    "Or": "OR",
    "If": "KW_IF",
    "Then": "KW_THEN",
    "ElseIf": "KW_ELSEIF",
    "ElsIf": "KW_ELSEIF",
    "Else": "KW_ELSE",
    "EndIf": "KW_ENDIF",
    "EndIfStatement": "KW_ENDIF",
    "For": "KW_FOR",
    "Each": "KW_EACH",
    "In": "KW_IN",
    "To": "KW_TO",
    "Do": "KW_DO",
    "Loop": "KW_DO",
    "EndDo": "KW_ENDDO",
    "EndLoop": "KW_ENDDO",
    "While": "KW_WHILE",
    "EndWhile": "KW_ENDWHILE",
    "Break": "KW_BREAK",
    "Continue": "KW_CONTINUE",
    "Return": "KW_RETURN",
    "Try": "KW_TRY",
    "Except": "KW_EXCEPT",
    "Raise": "KW_RAISE",
    "Throw": "KW_RAISE",
    "EndTry": "KW_ENDTRY",
    "Procedure": "KW_PROCEDURE",
    "EndProcedure": "KW_ENDPROCEDURE",
    "Function": "KW_FUNCTION",
    "EndFunction": "KW_ENDFUNCTION",
    "Var": "KW_VAR",
    "Export": "KW_EXPORT",
    "Val": "KW_VAL",
    "ByVal": "KW_VAL",
    "New": "KW_NEW",
    "Delete": "KW_DELETE",
    "Goto": "KW_GOTO",
    "Catalog": "KW_CATALOG",
    "Document": "KW_DOCUMENT",
    "Register": "KW_REGISTER",
    "Enum": "KW_ENUM",
    "Form": "KW_FORM",
    "Fields": "KW_FIELDS",
    "Table": "KW_TABLE",
    "Dimensions": "KW_DIMENSIONS",
    "Resources": "KW_RESOURCES",
    "Module": "KW_MODULE",
    "Subsystem": "KW_SUBSYSTEM",
    "Role": "KW_ROLE",
})

_RU_IMPORT_ALIASES = _lowered({
    "Истина": "TRUE",
    "Ложь": "FALSE",
    "Неопределено": "UNDEFINED",
    "Нуль": "NULL",
    "Не": "NOT",
    "И": "AND",
    "Или": "OR",
    "Если": "KW_IF",
    "Тогда": "KW_THEN",
    "ИначеЕсли": "KW_ELSEIF",
    "Иначе": "KW_ELSE",
    "КонецЕсли": "KW_ENDIF",
    "Для": "KW_FOR",
    "Каждого": "KW_EACH",
    "Из": "KW_IN",
    "По": "KW_TO",
    "Выполнить": "KW_DO",
    "Цикл": "KW_DO",
    "КонецЦикла": "KW_ENDDO",
    "Пока": "KW_WHILE",
    "КонецПока": "KW_ENDWHILE",
    "Прервать": "KW_BREAK",
    "Продолжить": "KW_CONTINUE",
    "Вернуть": "KW_RETURN",
    "Возврат": "KW_RETURN",
    "Попытка": "KW_TRY",
    "Исключение": "KW_EXCEPT",
    "ВызватьИсключение": "KW_RAISE",
    "КонецПопытки": "KW_ENDTRY",
    "Процедура": "KW_PROCEDURE",
    "КонецПроцедуры": "KW_ENDPROCEDURE",
    "Функция": "KW_FUNCTION",
    "КонецФункции": "KW_ENDFUNCTION",
    "Перем": "KW_VAR",
    "Экспорт": "KW_EXPORT",
    "Знач": "KW_VAL",
    "Новый": "KW_NEW",
    "Удалить": "KW_DELETE",
    "Перейти": "KW_GOTO",
    "Справочник": "KW_CATALOG",
    "Документ": "KW_DOCUMENT",
    "Регистр": "KW_REGISTER",
    "Перечисление": "KW_ENUM",
    "Форма": "KW_FORM",
    "Реквизиты": "KW_FIELDS",
    "ТабличнаяЧасть": "KW_TABLE",
    "Таблица": "KW_TABLE",
    "Измерения": "KW_DIMENSIONS",
    "Ресурсы": "KW_RESOURCES",
    "Модуль": "KW_MODULE",
    "Подсистема": "KW_SUBSYSTEM",
    "Роль": "KW_ROLE",
})

_UK_PP_ALIASES = _lowered({
    "Якщо": "KW_IF_COMPILE",
    "Тоді": "KW_THEN_COMPILE",
    "ІнакшеЯкщо": "KW_ELSEIF_COMPILE",
    "Інакше": "KW_ELSE_COMPILE",
    "КінецьЯкщо": "KW_ENDIF_COMPILE",
    "Область": "KW_REGION",
    "КінецьОбласті": "KW_ENDREGION",
    "Використати": "KW_USE",
})

_EN_PP_ALIASES = _lowered({
    "If": "KW_IF_COMPILE",
    "Then": "KW_THEN_COMPILE",
    "ElsIf": "KW_ELSEIF_COMPILE",
    "ElseIf": "KW_ELSEIF_COMPILE",
    "Else": "KW_ELSE_COMPILE",
    "EndIf": "KW_ENDIF_COMPILE",
    "Region": "KW_REGION",
    "EndRegion": "KW_ENDREGION",
    "Use": "KW_USE",
})

_RU_PP_IMPORT_ALIASES = _lowered({
    "Если": "KW_IF_COMPILE",
    "Тогда": "KW_THEN_COMPILE",
    "ИначеЕсли": "KW_ELSEIF_COMPILE",
    "Иначе": "KW_ELSE_COMPILE",
    "КонецЕсли": "KW_ENDIF_COMPILE",
    "Область": "KW_REGION",
    "КонецОбласти": "KW_ENDREGION",
    "Использовать": "KW_USE",
})


def _merge_keyword_maps(*maps: dict[str, TokenType]) -> dict[str, TokenType]:
    merged: dict[str, TokenType] = {}
    for item in maps:
        merged.update(item)
    return merged


_UK = _merge_keyword_maps(_UK_ALIASES)
_EN = _merge_keyword_maps(_EN_ALIASES)
_MIXED = _merge_keyword_maps(_UK_ALIASES, _EN_ALIASES, _RU_IMPORT_ALIASES)
_UK_PP = _merge_keyword_maps(_UK_PP_ALIASES)
_EN_PP = _merge_keyword_maps(_EN_PP_ALIASES)
_MIXED_PP = _merge_keyword_maps(_UK_PP_ALIASES, _EN_PP_ALIASES, _RU_PP_IMPORT_ALIASES)


UK_PROFILE = LanguageProfile(language="uk", keywords=_UK)
EN_PROFILE = LanguageProfile(language="en", keywords=_EN)
MIXED_PROFILE = LanguageProfile(language="mixed", keywords=_MIXED)

_TARGET_SURFACES: dict[TargetDslLanguage, dict[TokenType, str]] = {
    "uk": _UK_TARGETS,
    "en": _EN_TARGETS,
}


_UK_CALLABLE_TARGETS = _lowered_str_map({
    "Format": "Формат",
    "Формат": "Формат",
    "Left": "Лів",
    "Лев": "Лів",
    "Лів": "Лів",
    "Right": "Прав",
    "Прав": "Прав",
    "Mid": "Сер",
    "Сред": "Сер",
    "Сер": "Сер",
    "Find": "Знайти",
    "Найти": "Знайти",
    "Знайти": "Знайти",
    "Replace": "СтрЗамінити",
    "СтрЗаменить": "СтрЗамінити",
    "СтрЗамінити": "СтрЗамінити",
    "TrimAll": "СкрПробіли",
    "СокрЛП": "СкрПробіли",
    "СкрПробіли": "СкрПробіли",
    "CurrentDate": "ПоточнаДата",
    "ТекущаяДата": "ПоточнаДата",
    "ПоточнаДата": "ПоточнаДата",
    "IsFilled": "ЗаповненеЗнч",
    "ЗначениеЗаполнено": "ЗаповненеЗнч",
    "ЗаповненеЗнч": "ЗаповненеЗнч",
    "IsBlankString": "ПорожнійРядок",
    "ПустаяСтрока": "ПорожнійРядок",
    "ПорожнійРядок": "ПорожнійРядок",
    "NStr": "НСтр",
    "НСтр": "НСтр",
    "TypeOf": "ТипЗнч",
    "ТипЗнч": "ТипЗнч",
    "Round": "Округл",
    "Окр": "Округл",
    "Округл": "Округл",
    "Int": "Ціле",
    "Цел": "Ціле",
    "Ціле": "Ціле",
})

_EN_CALLABLE_TARGETS = _lowered_str_map({
    "Format": "Format",
    "Формат": "Format",
    "Left": "Left",
    "Лев": "Left",
    "Лів": "Left",
    "Right": "Right",
    "Прав": "Right",
    "Mid": "Mid",
    "Сред": "Mid",
    "Сер": "Mid",
    "Find": "Find",
    "Найти": "Find",
    "Знайти": "Find",
    "Replace": "Replace",
    "СтрЗаменить": "Replace",
    "СтрЗамінити": "Replace",
    "TrimAll": "TrimAll",
    "СокрЛП": "TrimAll",
    "СкрПробіли": "TrimAll",
    "CurrentDate": "CurrentDate",
    "ТекущаяДата": "CurrentDate",
    "ПоточнаДата": "CurrentDate",
    "IsFilled": "IsFilled",
    "ЗначениеЗаполнено": "IsFilled",
    "ЗаповненеЗнч": "IsFilled",
    "IsBlankString": "IsBlankString",
    "ПустаяСтрока": "IsBlankString",
    "ПорожнійРядок": "IsBlankString",
    "NStr": "NStr",
    "НСтр": "NStr",
    "TypeOf": "TypeOf",
    "ТипЗнч": "TypeOf",
    "Round": "Round",
    "Окр": "Round",
    "Округл": "Round",
    "Int": "Int",
    "Цел": "Int",
    "Ціле": "Int",
})

_UK_METHOD_TARGETS = _lowered_str_map({
    "Add": "Додати",
    "Добавить": "Додати",
    "Додати": "Додати",
    "Get": "Отримати",
    "Получить": "Отримати",
    "Отримати": "Отримати",
    "Set": "Встановити",
    "Установить": "Встановити",
    "Встановити": "Встановити",
    "Count": "Кількість",
    "Количество": "Кількість",
    "Кількість": "Кількість",
    "Clear": "Очистити",
    "Очистить": "Очистити",
    "Очистити": "Очистити",
    "Delete": "Видалити",
    "Удалить": "Видалити",
    "Видалити": "Видалити",
    "Insert": "Вставити",
    "Вставить": "Вставити",
    "Вставити": "Вставити",
})

_EN_METHOD_TARGETS = _lowered_str_map({
    "Add": "Add",
    "Добавить": "Add",
    "Додати": "Add",
    "Get": "Get",
    "Получить": "Get",
    "Отримати": "Get",
    "Set": "Set",
    "Установить": "Set",
    "Встановити": "Set",
    "Count": "Count",
    "Количество": "Count",
    "Кількість": "Count",
    "Clear": "Clear",
    "Очистить": "Clear",
    "Очистити": "Clear",
    "Delete": "Delete",
    "Удалить": "Delete",
    "Видалити": "Delete",
    "Insert": "Insert",
    "Вставить": "Insert",
    "Вставити": "Insert",
})

_UK_CONSTRUCTOR_TARGETS = _lowered_str_map({
    "Array": "Масив",
    "Массив": "Масив",
    "Масив": "Масив",
    "Map": "Відповідність",
    "Соответствие": "Відповідність",
    "Відповідність": "Відповідність",
    "Structure": "Структура",
    "Структура": "Структура",
})

_EN_CONSTRUCTOR_TARGETS = _lowered_str_map({
    "Array": "Array",
    "Массив": "Array",
    "Масив": "Array",
    "Map": "Map",
    "Соответствие": "Map",
    "Відповідність": "Map",
    "Structure": "Structure",
    "Структура": "Structure",
})

_IDENTIFIER_TARGETS: dict[TargetDslLanguage, IdentifierNormalizationProfile] = {
    "uk": IdentifierNormalizationProfile(
        callables=_UK_CALLABLE_TARGETS,
        methods=_UK_METHOD_TARGETS,
        constructors=_UK_CONSTRUCTOR_TARGETS,
    ),
    "en": IdentifierNormalizationProfile(
        callables=_EN_CALLABLE_TARGETS,
        methods=_EN_METHOD_TARGETS,
        constructors=_EN_CONSTRUCTOR_TARGETS,
    ),
}

_SOURCE_ALIASES: dict[DslLanguage, dict[str, TokenType]] = {
    "uk": _UK_ALIASES,
    "en": _EN_ALIASES,
    "mixed": _MIXED,
}

_SOURCE_PP_ALIASES: dict[DslLanguage, dict[str, TokenType]] = {
    "uk": _UK_PP,
    "en": _EN_PP,
    "mixed": _MIXED_PP,
}


def get_profile(language: DslLanguage) -> LanguageProfile:
    if language == "uk":
        return UK_PROFILE
    if language == "en":
        return EN_PROFILE
    return MIXED_PROFILE


def get_all_keywords() -> dict[str, TokenType]:
    """Return the combined keyword table for syntax highlighters."""
    return dict(_MIXED)


def get_keyword_surfaces(language: TargetDslLanguage) -> dict[TokenType, str]:
    """Return canonical target surfaces for a real DSL language."""
    return dict(_TARGET_SURFACES[language])


def get_source_keyword_aliases(language: DslLanguage = "mixed") -> dict[str, TokenType]:
    """Return source keyword aliases accepted by the lexer/normalizer."""
    return dict(_SOURCE_ALIASES[language])


def get_source_preprocessor_aliases(language: DslLanguage = "mixed") -> dict[str, TokenType]:
    """Return preprocessor aliases accepted after ``#`` directives."""
    return dict(_SOURCE_PP_ALIASES[language])


def get_normalization_keyword_map(language: TargetDslLanguage) -> dict[str, str]:
    """Return alias_lower -> canonical_surface for module normalization."""
    targets = _TARGET_SURFACES[language]
    aliases = _merge_keyword_maps(_SOURCE_ALIASES["mixed"], _SOURCE_PP_ALIASES["mixed"])
    normalized: dict[str, str] = {}
    for alias, token in aliases.items():
        surface = targets.get(token)
        if surface:
            normalized[str(alias).lower()] = surface
    # Canonical UK/EN surfaces should normalize to themselves as well.
    for token, surface in targets.items():
        normalized[str(surface).lower()] = str(surface)
    return normalized


def get_normalization_identifier_profile(language: TargetDslLanguage) -> IdentifierNormalizationProfile:
    """Return canonical identifier translation tables for builtin calls/methods/types."""
    prof = _IDENTIFIER_TARGETS[language]
    return IdentifierNormalizationProfile(
        callables=dict(prof.callables),
        methods=dict(prof.methods),
        constructors=dict(prof.constructors),
    )


@lru_cache(maxsize=None)
def _identifier_alias_groups(category: str) -> dict[str, tuple[str, ...]]:
    """Build connected identifier alias groups once per category."""
    adjacency: dict[str, set[str]] = {}
    for profile in _IDENTIFIER_TARGETS.values():
        for source, target in getattr(profile, category).items():
            source_key = str(source or "").casefold()
            target_key = str(target or "").casefold()
            if not source_key or not target_key:
                continue
            adjacency.setdefault(source_key, set()).add(target_key)
            adjacency.setdefault(target_key, set()).add(source_key)

    groups: dict[str, tuple[str, ...]] = {}
    for start in adjacency:
        if start in groups:
            continue
        pending = [start]
        component: set[str] = set()
        while pending:
            key = pending.pop()
            if key in component:
                continue
            component.add(key)
            pending.extend(adjacency.get(key, ()))
        aliases = tuple(sorted(component))
        for key in component:
            groups[key] = aliases
    return groups


def get_identifier_alias_keys(name: str, category: str) -> tuple[str, ...]:
    """Return case-folded UK/EN/import aliases connected to an identifier.

    The normalizer rewrites standard callable, method and constructor names.
    Semantic resolution and Runtime dispatch must therefore use the same
    equivalence classes instead of comparing only the rendered surface.
    """

    category_s = str(category or "").strip().lower()
    if category_s not in {"callables", "methods", "constructors"}:
        raise ValueError(f"Unsupported identifier alias category: {category}")
    name_key = str(name or "").strip().casefold()
    if not name_key:
        return ()
    return _identifier_alias_groups(category_s).get(name_key, (name_key,))
