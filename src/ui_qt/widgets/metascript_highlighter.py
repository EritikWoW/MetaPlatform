"""MetaScript syntax highlighter for QPlainTextEdit.

Highlights:
  - Keywords (UK + EN, case-insensitive)
  - Built-in functions / identifiers
  - String literals (single and double quote)
  - Numbers
  - Comments (// # /* ... */)
  - Preprocessor directives (#Область, #Якщо ...)
  - Operators
  - Class-like names (CamelCase → type color)

Color scheme adapts to dark (default) or light background.
"""

from __future__ import annotations

import re
from typing import List, Tuple

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import (
    QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextDocument,
)

from src.dsl.languages import get_all_keywords
from src.dsl.editor_syntax import scan_editor_line


# ---------------------------------------------------------------------------
# Token patterns
# ---------------------------------------------------------------------------

# All UK + EN keywords in one flat list (case-insensitive)
_KEYWORDS = [
    # Control flow — UK
    "якщо", "тоді", "то", "інакшеякщо", "інакше", "кінецьякщо", "кінцяякщо",
    "для", "кожного", "виконати", "цикл", "кінецьциклу", "кінцяциклу",
    "поки", "перервати", "продовжити", "повернути",
    "спроба", "виняток", "викинути", "кінецьспроби",
    "процедура", "кінецьпроцедури", "функція", "кінецьфункції",
    "змін", "перем", "експорт", "знач", "новий", "нове", "видалити",
    "якщо", "перейти",
    # Control flow — EN
    "if", "then", "elseif", "elsif", "else", "endif",
    "for", "each", "in", "to", "do", "loop", "enddo", "endloop",
    "while", "endwhile", "break", "continue", "return",
    "try", "except", "raise", "throw", "endtry",
    "procedure", "endprocedure", "function", "endfunction",
    "var", "export", "val", "byval", "new", "delete", "goto",
    # DSL — UK
    "довідник", "документ", "регістр", "перерахування", "форма",
    "реквізити", "таблична частина", "табличначастина", "таблиця",
    "виміри", "ресурси", "модуль", "підсистема", "роль",
    # DSL — EN
    "catalog", "document", "register", "enum", "form",
    "fields", "table", "dimensions", "resources", "module", "subsystem", "role",
]
_KEYWORDS = sorted(set(_KEYWORDS) | {word.casefold() for word in get_all_keywords()})

_LITERALS = [
    "правда", "хиба", "невизначено", "нуль",
    "true", "false", "undefined", "null",
]
_LITERALS = sorted(set(_LITERALS) | {word for word, token in get_all_keywords().items()
                                   if token in {"TRUE", "FALSE", "UNDEFINED", "NULL"}})

_OPERATORS_LOGICAL = ["та", "або", "не", "and", "or", "not"]
_OPERATORS_LOGICAL = sorted(set(_OPERATORS_LOGICAL) | {word for word, token in get_all_keywords().items()
                                                     if token in {"AND", "OR", "NOT"}})

_BUILTINS = [
    # EN
    "string", "number", "boolean", "typeof", "format",
    "array", "map", "newarray",
    "message", "alert", "print", "write",
    "abs", "max", "min", "round", "int", "sqrt", "log", "pow",
    "len", "left", "right", "mid", "find", "upper", "lower",
    "trimall", "trimleft", "trimright", "replace",
    "strconcat", "strsplit", "strrepeat", "strstartswith", "strendswith",
    "char", "charcode",
    "currentdate", "year", "month", "day", "hour", "minute", "second", "date",
    "isnull", "isundefined", "isempty", "isfilled",
    # UK
    "рядок", "число", "логічне", "типзнч",
    "масив", "відповідність", "новиймасив",
    "повідомлення", "попередження",
    "модуль", "макс", "мін", "округл", "ціле",
    "дл", "лів", "прав", "сер", "знайти", "врег", "нрег",
    "скрпробіли", "скрліво", "скрправо", "стрзамінити",
    "поточнадата",
    "єnull", "єневизначено", "пустезнч", "заповненезнч",
]

def _word_re(words: List[str]) -> str:
    """Build a case-insensitive alternation regex for whole words."""
    escaped = sorted(set(re.escape(w) for w in words), key=len, reverse=True)
    return r"(?<!\w)(" + "|".join(escaped) + r")(?!\w)"


# ---------------------------------------------------------------------------
# Color palettes
# ---------------------------------------------------------------------------

class _Palette:
    """Color values for syntax highlighting."""

    DARK = {
        "keyword":     "#C792EA",   # purple
        "literal":     "#F78C6C",   # orange
        "builtin":     "#82AAFF",   # blue
        "logical_op":  "#89DDFF",   # cyan
        "number":      "#F78C6C",   # orange
        "string":      "#C3E88D",   # green
        "comment":     "#546E7A",   # gray
        "preprocessor": "#FFCB6B",  # yellow
        "operator":    "#89DDFF",   # cyan
        "type_name":   "#FFCB6B",   # yellow (CamelCase)
        "label":       "#F07178",   # red (~ labels)
    }

    LIGHT = {
        "keyword":     "#7C3AED",   # purple
        "literal":     "#D6552E",   # dark orange
        "builtin":     "#1D4ED8",   # blue
        "logical_op":  "#0E7490",   # teal
        "number":      "#B45309",   # amber
        "string":      "#15803D",   # green
        "comment":     "#6B7280",   # gray
        "preprocessor": "#92400E",  # brown
        "operator":    "#0E7490",   # teal
        "type_name":   "#92400E",   # brown
        "label":       "#B91C1C",   # red
    }


# ---------------------------------------------------------------------------
# Highlighter
# ---------------------------------------------------------------------------

class MetaScriptHighlighter(QSyntaxHighlighter):
    """QSyntaxHighlighter for MetaScript (BSL-compatible, EN+UK)."""

    def __init__(self, document: QTextDocument, dark: bool = True) -> None:
        super().__init__(document)
        self._dark = dark
        self._rules: List[Tuple[QRegularExpression, QTextCharFormat]] = []
        self._build_rules()

    def set_dark(self, dark: bool) -> None:
        if dark != self._dark:
            self._dark = dark
            self._build_rules()
            self.rehighlight()

    def _fmt(self, color_key: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
        palette = _Palette.DARK if self._dark else _Palette.LIGHT
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(palette[color_key]))
        if bold:
            fmt.setFontWeight(QFont.Weight.Bold)
        if italic:
            fmt.setFontItalic(True)
        return fmt

    def _rule(self, pattern: str, fmt: QTextCharFormat,
              flags: QRegularExpression.PatternOption = QRegularExpression.PatternOption.NoPatternOption,
              ) -> Tuple[QRegularExpression, QTextCharFormat]:
        rx = QRegularExpression(pattern, QRegularExpression.PatternOption.CaseInsensitiveOption
                                | QRegularExpression.PatternOption.UseUnicodePropertiesOption | flags)
        return rx, fmt

    def _build_rules(self) -> None:
        self._rules = []

        kw_fmt     = self._fmt("keyword", bold=True)
        lit_fmt    = self._fmt("literal", bold=True)
        bi_fmt     = self._fmt("builtin")
        logic_fmt  = self._fmt("logical_op", bold=True)
        num_fmt    = self._fmt("number")
        str_fmt    = self._fmt("string")
        cmt_fmt    = self._fmt("comment", italic=True)
        pp_fmt     = self._fmt("preprocessor")
        op_fmt     = self._fmt("operator")
        type_fmt   = self._fmt("type_name")
        lbl_fmt    = self._fmt("label")

        # Identifiers have lower precedence than keywords and built-ins.
        self._rules.append((QRegularExpression(
            r"\b[A-ZІЇЄҐА-Я][a-zіїєґа-яA-ZІЇЄҐА-Я0-9_]+\b",
            QRegularExpression.PatternOption.UseUnicodePropertiesOption), type_fmt))

        # Labels: ~LabelName
        self._rules.append(self._rule(r"~\w+", lbl_fmt))

        # Built-in functions — before general identifiers
        self._rules.append(self._rule(_word_re(_BUILTINS), bi_fmt))

        # Keywords win when a name also appears in the legacy built-in list.
        self._rules.append(self._rule(_word_re(_KEYWORDS), kw_fmt))

        self._rules.append(self._rule(_word_re(_OPERATORS_LOGICAL), logic_fmt))
        self._rules.append(self._rule(_word_re(_LITERALS), lit_fmt))

        # Numbers: float or int, with optional _ separator
        self._rules.append(self._rule(r"\b\d[\d_]*(\.\d[\d_]*)?\b", num_fmt))

        # Operators
        self._rules.append(self._rule(r"[+\-*/%=<>!&]|<>|<=|>=", op_fmt))

        self._lexical_formats = {"comment": cmt_fmt, "string": str_fmt, "directive": pp_fmt}

    def highlightBlock(self, text: str) -> None:
        # Single-line rules
        for rx, fmt in self._rules:
            it = rx.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)

        scanned = scan_editor_line(text, self.previousBlockState())
        self.setCurrentBlockState(scanned.state)
        # QSyntaxHighlighter uses UTF-16 offsets, unlike Python's code points.
        offsets = [0]
        for ch in text:
            offsets.append(offsets[-1] + (2 if ord(ch) > 0xFFFF else 1))
        for span in scanned.spans:
            self.setFormat(offsets[span.start], offsets[span.end] - offsets[span.start],
                           self._lexical_formats[span.kind])
