"""
Резолвер CSS-подобных переменных `var(...)` внутри SVG.

Модуль предназначен для подстановки значений палитры проекта в SVG-файлы.
Типичный сценарий: SVG содержит `stroke="var(primary)"`, а палитра определяет
`primary -> #RRGGBB`. Перед рендерингом SVG (QSvgRenderer) мы заменяем `var(...)`
на конкретные HEX-значения.

Ограничения:
- fallback в `var(name, fallback)` парсится до первой закрывающей скобки `)`.
  То есть сложные fallback'и вида `rgb(1,2,3)` могут быть обработаны некорректно.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict

#: Регулярное выражение для поиска `var(name)` и `var(name, fallback)`.
#: Поддерживаются имена вида `primary`, `--primary`, `--color_accent`, `border-1` и т.п.
_VAR_RE = re.compile(
    r"var\(\s*(?P<name>(?:--)?[a-zA-Z0-9_-]+)\s*(?:,\s*(?P<fallback>[^)]+?)\s*)?\)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SvgVarResolveResult:
    """
    Результат подстановки `var(...)` в SVG.

    Атрибуты:
        text:
            Итоговый SVG-текст после подстановок.
        replaced:
            Сколько замен выполнено (включая использование fallback).
    """

    text: str
    replaced: int


class SvgVarResolver:
    """
    Резолвер CSS-подобных `var(...)` внутри SVG XML.

    Основная задача — заменить ссылки вида:
        - var(primary)
        - var(--primary)
        - var(primary, #fff)

    на значение из палитры проекта либо на fallback.
    """

    @staticmethod
    def resolve(text: str, palette: Dict[str, str]) -> SvgVarResolveResult:
        """
        Выполнить подстановку `var(...)` в SVG-тексте.

        Аргументы:
            text:
                Исходный SVG как строка.
            palette:
                Словарь палитры {token: "#RRGGBB"}.
                Допускаются ключи вида "primary" или "--primary" — оба будут нормализованы.

        Возвращает:
            SvgVarResolveResult:
                `text` — обновлённый SVG,
                `replaced` — количество произведённых замен.
        """
        replaced = 0
        norm = {k.lstrip("-"): v for k, v in (palette or {}).items() if v}

        def repl(m: re.Match[str]) -> str:
            """
            Callback для re.sub: вычисляет строку-замену для одного совпадения `var(...)`.

            Логика:
            - если имя есть в палитре — подставляем значение палитры
            - иначе, если указан fallback — подставляем fallback
            - иначе возвращаем исходный текст совпадения без изменений
            """
            nonlocal replaced
            raw = (m.group("name") or "").strip()
            name = raw.lstrip("-")
            fb = (m.group("fallback") or "").strip()

            val = norm.get(name)
            if val:
                replaced += 1
                return val
            if fb:
                replaced += 1
                return fb
            return m.group()

        out = _VAR_RE.sub(repl, text)
        return SvgVarResolveResult(text=out, replaced=replaced)
