"""Keyboard-friendly code templates for the MetaScript editor."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class CodeTemplate:
    key: str
    label: str
    trigger: str
    body: str


def _identifiers(source: str) -> set[str]:
    return {item.casefold() for item in re.findall(
        r"[A-Za-zА-Яа-яЁёІіЇїЄєҐґ_][A-Za-zА-Яа-яЁёІіЇїЄєҐґ0-9_]*", source or ""
    )}


def templates_for(language: str, source: str = "") -> tuple[CodeTemplate, ...]:
    """Return localized templates with a counter not already used in source."""
    en = str(language or "").casefold().startswith("en")
    used = _identifiers(source)
    counter = "Counter" if en else "Счетчик"
    if counter.casefold() in used:
        counter = "I" if en else "Сч"
    item = "Item" if en else "Элемент"
    return (
        CodeTemplate("procedure", "Procedure", "Procedure" if en else "Процедура",
                     "Procedure Name()\n    \nEndProcedure" if en else "Процедура ИмяПроцедуры()\n    \nКінецьПроцедури"),
        CodeTemplate("function", "Function", "Function" if en else "Функція",
                     "Function Name()\n    \nEndFunction" if en else "Функція ІмяФункції()\n    \nКінецьФункції"),
        CodeTemplate("if", "If condition", "If" if en else "Якщо",
                     "If Condition Then\n    \nEndIf" if en else "Якщо Умова Тоді\n    \nКінецьЯкщо"),
        CodeTemplate("for", "For counter", "For" if en else "Для",
                     f"For {counter} = 0 To Value Do\n    \nEndDo" if en else f"Для {counter} = 0 По Значення Цикл\n    \nКінецьЦиклу"),
        CodeTemplate("foreach", "For each", "For Each" if en else "Для Кожного",
                     f"For Each {item} In Collection Do\n    \nEndDo" if en else f"Для Кожного {item} З Колекція Цикл\n    \nКінецьЦиклу"),
        CodeTemplate("while", "While loop", "While" if en else "Поки",
                     "While Condition Do\n    \nEndWhile" if en else "Поки Умова Цикл\n    \nКінецьПоки"),
        CodeTemplate("try", "Try / except", "Try" if en else "Спроба",
                     "Try\n    \nExcept\n    \nEndTry" if en else "Спроба\n    \nВиняток\n    \nКінецьСпроби"),
    )


def expand_template(template: CodeTemplate) -> tuple[str, int]:
    """Return snippet text and cursor offset at the first editable placeholder."""
    text = template.body
    placeholders = ("Name", "ІмяФункції", "ИмяПроцедуры", "Condition", "Умова", "Value", "Значення", "Collection", "Колекція")
    positions = [(text.find(value), value) for value in placeholders if text.find(value) >= 0]
    if positions:
        position, value = min(positions)
        return text, position + len(value)
    marker = text.find("    ")
    return text, marker if marker >= 0 else len(text)
