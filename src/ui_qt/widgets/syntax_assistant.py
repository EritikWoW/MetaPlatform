"""MetaScript Syntax Assistant — 1C-style signature popup.

Shows a floating tooltip with:
  - Function / procedure signature
  - Parameter descriptions
  - Return value (for functions)
  - Brief description in UK + EN

Activated:
  - When user types an opening parenthesis after a known function name
  - When user moves cursor inside a function call
  - Via Ctrl+Shift+Space shortcut

Design:
  - Language-aware (shows UK if editor is set to UK, EN otherwise)
  - Highlights current parameter as user moves through arguments
  - Dark/Light theme aware
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
import threading
import time
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QPoint, QSize, QTimer, QObject, QEvent, Signal
from PySide6.QtGui import QColor, QFont, QPalette, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit,
    QScrollArea, QVBoxLayout, QWidget,
)
from src.dsl.signature_help import CallableSignature, SignatureDocument


# ---------------------------------------------------------------------------
# Function database
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ParamInfo:
    name_uk: str
    name_en: str
    type_hint: str = ""
    optional: bool = False
    description_uk: str = ""
    description_en: str = ""
    by_value: bool | None = None
    default_text: str | None = None


@dataclass(frozen=True, slots=True)
class FunctionInfo:
    name_uk: str
    name_en: str
    params: Tuple[ParamInfo, ...] = field(default_factory=tuple)
    return_type: str = ""
    description_uk: str = ""
    description_en: str = ""
    category_uk: str = ""
    category_en: str = ""
    is_procedure: bool = False


# ---------------------------------------------------------------------------
# Existing built-in help catalog (not a guarantee of runtime API coverage)
# ---------------------------------------------------------------------------

_FUNCTIONS: List[FunctionInfo] = [
    # ---- Type conversion ----
    FunctionInfo(
        name_uk="Рядок", name_en="String",
        params=(ParamInfo("Значення", "Value", "Довільний", description_uk="Значення для перетворення", description_en="Value to convert"),),
        return_type="Рядок / String",
        description_uk="Перетворює значення у рядок.",
        description_en="Converts a value to a string.",
        category_uk="Перетворення типів", category_en="Type Conversion",
    ),
    FunctionInfo(
        name_uk="Число", name_en="Number",
        params=(ParamInfo("Значення", "Value", "Рядок / Число", description_uk="Рядок або число", description_en="String or number"),),
        return_type="Число / Number",
        description_uk="Перетворює рядок або значення на число.",
        description_en="Converts a string or value to a number.",
        category_uk="Перетворення типів", category_en="Type Conversion",
    ),
    FunctionInfo(
        name_uk="Логічне", name_en="Boolean",
        params=(ParamInfo("Значення", "Value", "Довільний", description_uk="Значення", description_en="Value"),),
        return_type="Логічне / Boolean",
        description_uk="Перетворює значення у логічне (True/False).",
        description_en="Converts a value to a boolean (True/False).",
        category_uk="Перетворення типів", category_en="Type Conversion",
    ),
    FunctionInfo(
        name_uk="ТипЗнч", name_en="TypeOf",
        params=(ParamInfo("Значення", "Value", "Довільний", description_uk="Значення", description_en="Value"),),
        return_type="Рядок / String",
        description_uk="Повертає тип значення у вигляді рядка.",
        description_en="Returns the type of a value as a string.",
        category_uk="Перетворення типів", category_en="Type Conversion",
    ),

    # ---- String functions ----
    FunctionInfo(
        name_uk="Дл", name_en="Len",
        params=(ParamInfo("Рядок", "String", "Рядок", description_uk="Вхідний рядок", description_en="Input string"),),
        return_type="Число / Number",
        description_uk="Повертає довжину рядка в символах.",
        description_en="Returns the length of a string in characters.",
        category_uk="Рядкові функції", category_en="String Functions",
    ),
    FunctionInfo(
        name_uk="Лів", name_en="Left",
        params=(
            ParamInfo("Рядок", "String", "Рядок", description_uk="Вхідний рядок", description_en="Input string"),
            ParamInfo("Кількість", "Count", "Число", description_uk="Кількість символів зліва", description_en="Number of characters from the left"),
        ),
        return_type="Рядок / String",
        description_uk="Повертає перші N символів рядка.",
        description_en="Returns the first N characters of a string.",
        category_uk="Рядкові функції", category_en="String Functions",
    ),
    FunctionInfo(
        name_uk="Прав", name_en="Right",
        params=(
            ParamInfo("Рядок", "String", "Рядок", description_uk="Вхідний рядок", description_en="Input string"),
            ParamInfo("Кількість", "Count", "Число", description_uk="Кількість символів справа", description_en="Number of characters from the right"),
        ),
        return_type="Рядок / String",
        description_uk="Повертає останні N символів рядка.",
        description_en="Returns the last N characters of a string.",
        category_uk="Рядкові функції", category_en="String Functions",
    ),
    FunctionInfo(
        name_uk="Сер", name_en="Mid",
        params=(
            ParamInfo("Рядок", "String", "Рядок", description_uk="Вхідний рядок", description_en="Input string"),
            ParamInfo("Початок", "Start", "Число", description_uk="Початкова позиція (1-based)", description_en="Start position (1-based)"),
            ParamInfo("Довжина", "Length", "Число", optional=True, description_uk="Кількість символів (за замовч. — до кінця)", description_en="Number of characters (default: to end)"),
        ),
        return_type="Рядок / String",
        description_uk="Повертає підрядок з позиції Start довжиною Length символів.",
        description_en="Returns a substring starting at Start with Length characters.",
        category_uk="Рядкові функції", category_en="String Functions",
    ),
    FunctionInfo(
        name_uk="Знайти", name_en="Find",
        params=(
            ParamInfo("Рядок", "String", "Рядок", description_uk="Рядок для пошуку у", description_en="String to search in"),
            ParamInfo("Підрядок", "Substring", "Рядок", description_uk="Що шукати", description_en="What to search for"),
        ),
        return_type="Число / Number",
        description_uk="Знаходить позицію підрядка у рядку. Повертає 0, якщо не знайдено.",
        description_en="Finds the position of a substring in a string. Returns 0 if not found.",
        category_uk="Рядкові функції", category_en="String Functions",
    ),
    FunctionInfo(
        name_uk="ВРег", name_en="Upper",
        params=(ParamInfo("Рядок", "String", "Рядок", description_uk="Вхідний рядок", description_en="Input string"),),
        return_type="Рядок / String",
        description_uk="Перетворює рядок у верхній регістр.",
        description_en="Converts a string to uppercase.",
        category_uk="Рядкові функції", category_en="String Functions",
    ),
    FunctionInfo(
        name_uk="НРег", name_en="Lower",
        params=(ParamInfo("Рядок", "String", "Рядок", description_uk="Вхідний рядок", description_en="Input string"),),
        return_type="Рядок / String",
        description_uk="Перетворює рядок у нижній регістр.",
        description_en="Converts a string to lowercase.",
        category_uk="Рядкові функції", category_en="String Functions",
    ),
    FunctionInfo(
        name_uk="СкрПробіли", name_en="TrimAll",
        params=(ParamInfo("Рядок", "String", "Рядок", description_uk="Вхідний рядок", description_en="Input string"),),
        return_type="Рядок / String",
        description_uk="Видаляє пробіли на початку та в кінці рядка.",
        description_en="Removes leading and trailing spaces from a string.",
        category_uk="Рядкові функції", category_en="String Functions",
    ),
    FunctionInfo(
        name_uk="СкрЛіво", name_en="TrimLeft",
        params=(ParamInfo("Рядок", "String", "Рядок", description_uk="Вхідний рядок", description_en="Input string"),),
        return_type="Рядок / String",
        description_uk="Видаляє пробіли на початку рядка.",
        description_en="Removes leading spaces from a string.",
        category_uk="Рядкові функції", category_en="String Functions",
    ),
    FunctionInfo(
        name_uk="СкрПраво", name_en="TrimRight",
        params=(ParamInfo("Рядок", "String", "Рядок", description_uk="Вхідний рядок", description_en="Input string"),),
        return_type="Рядок / String",
        description_uk="Видаляє пробіли в кінці рядка.",
        description_en="Removes trailing spaces from a string.",
        category_uk="Рядкові функції", category_en="String Functions",
    ),
    FunctionInfo(
        name_uk="СтрЗамінити", name_en="Replace",
        params=(
            ParamInfo("Рядок", "String", "Рядок", description_uk="Вхідний рядок", description_en="Input string"),
            ParamInfo("Що", "What", "Рядок", description_uk="Що замінити", description_en="What to replace"),
            ParamInfo("Чим", "With", "Рядок", description_uk="На що замінити", description_en="Replace with"),
        ),
        return_type="Рядок / String",
        description_uk="Замінює всі входження підрядка в рядку.",
        description_en="Replaces all occurrences of a substring in a string.",
        category_uk="Рядкові функції", category_en="String Functions",
    ),
    FunctionInfo(
        name_uk="СтрРозділити", name_en="StrSplit",
        params=(
            ParamInfo("Рядок", "String", "Рядок", description_uk="Вхідний рядок", description_en="Input string"),
            ParamInfo("Роздільник", "Separator", "Рядок", optional=True, description_uk="Роздільник (за замовч. ',')", description_en="Separator (default ',')"),
        ),
        return_type="Масив / Array",
        description_uk="Розбиває рядок на масив підрядків по роздільнику.",
        description_en="Splits a string into an array of substrings by separator.",
        category_uk="Рядкові функції", category_en="String Functions",
    ),
    FunctionInfo(
        name_uk="Формат", name_en="Format",
        params=(
            ParamInfo("Значення", "Value", "Довільний", description_uk="Значення для форматування", description_en="Value to format"),
            ParamInfo("Рядок формату", "FormatString", "Рядок", description_uk="Рядок формату (напр. 'ЧЦ=10.2')", description_en="Format string (e.g. 'ND=10.2')"),
        ),
        return_type="Рядок / String",
        description_uk="Форматує значення за рядком формату (подібно до 1С Format()).",
        description_en="Formats a value using a format string (similar to 1C Format()).",
        category_uk="Рядкові функції", category_en="String Functions",
    ),

    # ---- Math functions ----
    FunctionInfo(
        name_uk="Модуль", name_en="Abs",
        params=(ParamInfo("Число", "Number", "Число", description_uk="Вхідне число", description_en="Input number"),),
        return_type="Число / Number",
        description_uk="Повертає абсолютне значення числа.",
        description_en="Returns the absolute value of a number.",
        category_uk="Математичні функції", category_en="Math Functions",
    ),
    FunctionInfo(
        name_uk="Макс", name_en="Max",
        params=(
            ParamInfo("Значення1", "Value1", "Число", description_uk="Перше значення", description_en="First value"),
            ParamInfo("Значення2", "Value2", "Число", description_uk="Друге значення", description_en="Second value"),
        ),
        return_type="Число / Number",
        description_uk="Повертає максимальне з двох значень.",
        description_en="Returns the maximum of two values.",
        category_uk="Математичні функції", category_en="Math Functions",
    ),
    FunctionInfo(
        name_uk="Мін", name_en="Min",
        params=(
            ParamInfo("Значення1", "Value1", "Число", description_uk="Перше значення", description_en="First value"),
            ParamInfo("Значення2", "Value2", "Число", description_uk="Друге значення", description_en="Second value"),
        ),
        return_type="Число / Number",
        description_uk="Повертає мінімальне з двох значень.",
        description_en="Returns the minimum of two values.",
        category_uk="Математичні функції", category_en="Math Functions",
    ),
    FunctionInfo(
        name_uk="Округл", name_en="Round",
        params=(
            ParamInfo("Число", "Number", "Число", description_uk="Число для округлення", description_en="Number to round"),
            ParamInfo("Знаки", "Digits", "Число", optional=True, description_uk="Кількість знаків після коми (за замовч. 0)", description_en="Decimal digits (default 0)"),
        ),
        return_type="Число / Number",
        description_uk="Округлює число до вказаної кількості знаків.",
        description_en="Rounds a number to the specified number of digits.",
        category_uk="Математичні функції", category_en="Math Functions",
    ),
    FunctionInfo(
        name_uk="Ціле", name_en="Int",
        params=(ParamInfo("Число", "Number", "Число", description_uk="Число", description_en="Number"),),
        return_type="Число / Number",
        description_uk="Повертає цілу частину числа (відкидає дробову).",
        description_en="Returns the integer part of a number (truncates fractional part).",
        category_uk="Математичні функції", category_en="Math Functions",
    ),

    # ---- Date functions ----
    FunctionInfo(
        name_uk="ПоточнаДата", name_en="CurrentDate",
        params=(),
        return_type="Дата / Date",
        description_uk="Повертає поточну дату та час.",
        description_en="Returns the current date and time.",
        category_uk="Дата і час", category_en="Date & Time",
    ),
    FunctionInfo(
        name_uk="Дата", name_en="Date",
        params=(
            ParamInfo("Рік", "Year", "Число", description_uk="Рік", description_en="Year"),
            ParamInfo("Місяць", "Month", "Число", description_uk="Місяць (1–12)", description_en="Month (1–12)"),
            ParamInfo("День", "Day", "Число", description_uk="День (1–31)", description_en="Day (1–31)"),
        ),
        return_type="Дата / Date",
        description_uk="Створює об'єкт дати з рік, місяць, день.",
        description_en="Creates a date object from year, month, day.",
        category_uk="Дата і час", category_en="Date & Time",
    ),
    FunctionInfo(
        name_uk="Рік", name_en="Year",
        params=(ParamInfo("Дата", "Date", "Дата", description_uk="Дата", description_en="Date"),),
        return_type="Число / Number",
        description_uk="Повертає рік із дати.",
        description_en="Returns the year from a date.",
        category_uk="Дата і час", category_en="Date & Time",
    ),
    FunctionInfo(
        name_uk="Місяць", name_en="Month",
        params=(ParamInfo("Дата", "Date", "Дата", description_uk="Дата", description_en="Date"),),
        return_type="Число / Number",
        description_uk="Повертає місяць із дати (1–12).",
        description_en="Returns the month from a date (1–12).",
        category_uk="Дата і час", category_en="Date & Time",
    ),
    FunctionInfo(
        name_uk="День", name_en="Day",
        params=(ParamInfo("Дата", "Date", "Дата", description_uk="Дата", description_en="Date"),),
        return_type="Число / Number",
        description_uk="Повертає день із дати (1–31).",
        description_en="Returns the day from a date (1–31).",
        category_uk="Дата і час", category_en="Date & Time",
    ),

    # ---- Collections ----
    FunctionInfo(
        name_uk="Масив", name_en="Array",
        params=(),
        return_type="Масив / Array",
        description_uk="Створює новий порожній масив (Масив з 1-based індексацією).",
        description_en="Creates a new empty array (1-based indexing).",
        category_uk="Колекції", category_en="Collections",
    ),
    FunctionInfo(
        name_uk="НовийМасив", name_en="NewArray",
        params=(ParamInfo("Розмір", "Size", "Число", optional=True, description_uk="Початковий розмір (заповнюється Невизначено)", description_en="Initial size (filled with Undefined)"),),
        return_type="Масив / Array",
        description_uk="Створює масив заданого розміру.",
        description_en="Creates an array of the given size.",
        category_uk="Колекції", category_en="Collections",
    ),
    FunctionInfo(
        name_uk="Відповідність", name_en="Map",
        params=(),
        return_type="Відповідність / Map",
        description_uk="Створює нову порожню відповідність (ключ → значення).",
        description_en="Creates a new empty map (key → value).",
        category_uk="Колекції", category_en="Collections",
    ),

    # ---- Check functions ----
    FunctionInfo(
        name_uk="ЄNull", name_en="IsNull",
        params=(ParamInfo("Значення", "Value", "Довільний", description_uk="Значення для перевірки", description_en="Value to check"),),
        return_type="Логічне / Boolean",
        description_uk="Перевіряє, чи значення є Null.",
        description_en="Checks if the value is Null.",
        category_uk="Перевірки", category_en="Checks",
    ),
    FunctionInfo(
        name_uk="ЄНевизначено", name_en="IsUndefined",
        params=(ParamInfo("Значення", "Value", "Довільний", description_uk="Значення для перевірки", description_en="Value to check"),),
        return_type="Логічне / Boolean",
        description_uk="Перевіряє, чи значення є Невизначено.",
        description_en="Checks if the value is Undefined.",
        category_uk="Перевірки", category_en="Checks",
    ),
    FunctionInfo(
        name_uk="ПустеЗнч", name_en="IsEmpty",
        params=(ParamInfo("Значення", "Value", "Довільний", description_uk="Значення для перевірки", description_en="Value to check"),),
        return_type="Логічне / Boolean",
        description_uk="Перевіряє, чи значення є порожнім (0, '', Невизначено, Null).",
        description_en="Checks if the value is empty (0, '', Undefined, Null).",
        category_uk="Перевірки", category_en="Checks",
    ),
    FunctionInfo(
        name_uk="ЗаповненеЗнч", name_en="IsFilled",
        params=(ParamInfo("Значення", "Value", "Довільний", description_uk="Значення для перевірки", description_en="Value to check"),),
        return_type="Логічне / Boolean",
        description_uk="Перевіряє, чи значення не є порожнім.",
        description_en="Checks if the value is not empty.",
        category_uk="Перевірки", category_en="Checks",
    ),

    # ---- I/O ----
    FunctionInfo(
        name_uk="Повідомлення", name_en="Message",
        params=(ParamInfo("Текст", "Text", "Рядок", description_uk="Текст повідомлення", description_en="Message text"),),
        return_type="",
        description_uk="Виводить повідомлення в консоль / рядок статусу.",
        description_en="Outputs a message to the console / status line.",
        category_uk="Введення / Виведення", category_en="I/O",
        is_procedure=True,
    ),
    FunctionInfo(
        name_uk="Попередження", name_en="Alert",
        params=(ParamInfo("Текст", "Text", "Рядок", description_uk="Текст попередження", description_en="Warning text"),),
        return_type="",
        description_uk="Виводить попередження (аналог Alert).",
        description_en="Outputs a warning (similar to Alert).",
        category_uk="Введення / Виведення", category_en="I/O",
        is_procedure=True,
    ),
]


# ---------------------------------------------------------------------------
# Lookup table: lower(name) → FunctionInfo
# ---------------------------------------------------------------------------

_FUNC_LOOKUP: Dict[str, FunctionInfo] = {}
for _f in _FUNCTIONS:
    _FUNC_LOOKUP[_f.name_uk.lower()] = _f
    _FUNC_LOOKUP[_f.name_en.lower()] = _f


def get_function_info(name: str) -> Optional[FunctionInfo]:
    """Look up function info by name (case-insensitive)."""
    return _FUNC_LOOKUP.get(name.lower())


def get_all_completions() -> List[str]:
    """Return all function names (UK + EN) for autocomplete."""
    names: List[str] = []
    for f in _FUNCTIONS:
        names.append(f.name_uk)
        if f.name_en != f.name_uk:
            names.append(f.name_en)
    return sorted(set(names))


# ---------------------------------------------------------------------------
# Signature popup widget
# ---------------------------------------------------------------------------

class SyntaxAssistantPopup(QFrame):
    """Floating popup showing function signature and parameter help.

    Similar to the 1C Syntax Assistant but embedded as a lightweight
    tooltip-style panel attached to the editor.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, Qt.WindowType.ToolTip)
        self._language = "uk"
        self._current_param = 0

        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # Function name + signature
        self._lbl_signature = QLabel()
        self._lbl_signature.setTextFormat(Qt.TextFormat.RichText)
        self._lbl_signature.setWordWrap(True)
        sig_font = QFont()
        sig_font.setFamilies(["Cascadia Code", "Consolas", "Courier New"])
        sig_font.setPointSize(10)
        self._lbl_signature.setFont(sig_font)
        layout.addWidget(self._lbl_signature)

        # Current parameter description
        self._lbl_param_desc = QLabel()
        self._lbl_param_desc.setWordWrap(True)
        self._lbl_param_desc.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self._lbl_param_desc)

        # Function description
        self._lbl_desc = QLabel()
        self._lbl_desc.setWordWrap(True)
        self._lbl_desc.setTextFormat(Qt.TextFormat.RichText)
        desc_font = QFont()
        desc_font.setPointSize(9)
        self._lbl_desc.setFont(desc_font)
        layout.addWidget(self._lbl_desc)

        # Return type
        self._lbl_return = QLabel()
        self._lbl_return.setTextFormat(Qt.TextFormat.RichText)
        self._lbl_return.setFont(desc_font)
        layout.addWidget(self._lbl_return)

        self.setMinimumWidth(350)
        self.setMaximumWidth(600)
        self.hide()

    def set_language(self, lang: str) -> None:
        self._language = lang

    def _is_dark(self) -> bool:
        bg = self.palette().color(QPalette.ColorRole.Base)
        return bg.lightness() < 128

    def show_for(self, func: FunctionInfo, active_param: int = 0,
                 pos: Optional[QPoint] = None) -> None:
        """Display the popup for the given function, highlighting active_param."""
        self._current_param = active_param
        lang_uk = self._language in ("uk", "mixed")

        # Colors
        if self._is_dark():
            kw_color = "#C792EA"
            name_color = "#82AAFF"
            active_color = "#FFCB6B"
            muted_color = "#91A4B8"
            type_color = "#89DDFF"
            desc_color = "#B0BEC5"
            ret_color = "#C3E88D"
        else:
            kw_color = "#7C3AED"
            name_color = "#1D4ED8"
            active_color = "#D97706"
            muted_color = "#526175"
            type_color = "#0E7490"
            desc_color = "#374151"
            ret_color = "#15803D"

        func_name = escape(func.name_uk if lang_uk else func.name_en)
        kw_text = "Процедура" if func.is_procedure else "Функція"
        kw_en = "Procedure" if func.is_procedure else "Function"
        kw = kw_text if lang_uk else kw_en

        # Build signature HTML
        sig_parts: List[str] = []
        for i, p in enumerate(func.params):
            pname = escape(p.name_uk if lang_uk else p.name_en)
            if p.by_value:
                pname = ("Знач " if lang_uk else "Val ") + pname
            ptype = escape(p.type_hint)
            part = ""
            if p.optional:
                part = f"[{pname}"
                if ptype:
                    part += f": <span style='color:{type_color}'>{ptype}</span>"
                part += "]"
            else:
                part = pname
                if ptype:
                    part += f": <span style='color:{type_color}'>{ptype}</span>"
            if p.default_text is not None:
                part += " = " + escape(p.default_text[:180])
            if i == active_param:
                part = f"<b><span style='color:{active_color}'>{part}</span></b>"
            else:
                part = f"<span style='color:{muted_color}'>{part}</span>"
            sig_parts.append(part)

        params_html = ", ".join(sig_parts)
        if not func.params:
            params_html = f"<span style='color:{muted_color}'></span>"

        sig_html = (
            f"<span style='color:{kw_color}'>{kw}</span> "
            f"<span style='color:{name_color}'><b>{func_name}</b></span>"
            f"({params_html})"
        )
        if func.return_type and not func.is_procedure:
            sig_html += f" → <span style='color:{ret_color}'>{escape(func.return_type)}</span>"
        self._lbl_signature.setText(sig_html)
        metrics = QTextDocument()
        metrics.setDefaultFont(self._lbl_signature.font())
        metrics.setHtml(sig_html)
        self.setFixedWidth(max(350, min(600, int(metrics.idealWidth()) + 20)))

        # Active param description
        if func.params and 0 <= active_param < len(func.params):
            p = func.params[active_param]
            pdesc = escape(p.description_uk if lang_uk else p.description_en)
            pname = escape(p.name_uk if lang_uk else p.name_en)
            if pdesc:
                self._lbl_param_desc.setText(
                    f"<b><span style='color:{active_color}'>{pname}</span></b>"
                    f"<span style='color:{desc_color}'> — {pdesc}</span>"
                )
                self._lbl_param_desc.show()
            else:
                self._lbl_param_desc.hide()
        else:
            message = (f"Аргумент {active_param + 1}; параметрів: {len(func.params)}" if lang_uk
                       else f"Argument {active_param + 1}; parameters: {len(func.params)}")
            if not func.params:
                message = "Без параметрів" if lang_uk else "No parameters"
            self._lbl_param_desc.setText(message)
            self._lbl_param_desc.show()

        # Description
        fdesc = func.description_uk if lang_uk else func.description_en
        if fdesc:
            self._lbl_desc.setText(f"<span style='color:{desc_color}'>{escape(fdesc)}</span>")
            self._lbl_desc.show()
        else:
            self._lbl_desc.hide()

        # Category
        cat = func.category_uk if lang_uk else func.category_en
        if cat:
            self._lbl_return.setText(
                f"<span style='color:{muted_color}'>{escape(cat)}</span>"
            )
            self._lbl_return.show()
        else:
            self._lbl_return.hide()

        self.adjustSize()
        if pos is not None:
            self.move(pos)
        self.show()
        self.raise_()


# ---------------------------------------------------------------------------
# Controller — attaches to a QPlainTextEdit and manages the popup
# ---------------------------------------------------------------------------

class _SignatureSignals(QObject):
    resolved = Signal(int, str, object)
    snapshot_ready = Signal(int, object)


def _local_function_info(signature: CallableSignature) -> FunctionInfo:
    return FunctionInfo(
        signature.name, signature.name,
        tuple(ParamInfo(p.name, p.name, by_value=p.by_value, default_text=p.default_text)
              for p in signature.parameters),
        category_uk="Поточний модуль", category_en="Current module",
        is_procedure=signature.kind == "procedure",
    )


class SyntaxAssistantController(QObject):
    """Attaches to a QPlainTextEdit and manages the syntax assistant popup.

    Usage:
        controller = SyntaxAssistantController(edit_widget, parent_widget)
        controller.set_language("uk")
        # The controller hooks into textChanged and cursorPositionChanged
        # and shows/hides the popup automatically.
    """

    def __init__(self, edit: QPlainTextEdit, parent: QWidget) -> None:
        super().__init__(edit)
        self._edit = edit
        self._popup = SyntaxAssistantPopup(parent)
        self._popup.setPalette(edit.palette())
        self._popup.setStyleSheet("QFrame { background: #111827; border: 1px solid #334155; border-radius: 6px; } QLabel { border: none; color: #E6EEF8; }")
        self._language = "uk"
        self._active_func: Optional[FunctionInfo] = None
        self._snapshot: SignatureDocument | None = None
        self._snapshot_pending = False
        self._snapshot_failed_source: str | None = None
        self._provider = None
        self._generation = 0
        self._request_id = 0
        self._pending: dict[str, int] = {}
        self._cache: dict[str, tuple[float, dict]] = {}
        self._dismissed_opening: int | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._update_popup)
        self._signals = _SignatureSignals(self)
        self._signals.resolved.connect(self._on_resolved)
        self._signals.snapshot_ready.connect(self._on_snapshot_ready)
        edit.installEventFilter(self)
        edit.viewport().installEventFilter(self)
        edit.cursorPositionChanged.connect(self._schedule)
        edit.textChanged.connect(self._schedule)
        edit.verticalScrollBar().valueChanged.connect(self._schedule)
        edit.horizontalScrollBar().valueChanged.connect(self._schedule)

    def set_language(self, lang: str) -> None:
        self._language = lang
        self._popup.set_language(lang)
        self._schedule()

    def set_namespace_provider(self, provider) -> None:
        self._provider = provider
        self.invalidate()

    def invalidate(self) -> None:
        self._generation += 1
        self._cache.clear()
        self._snapshot = None
        self._snapshot_failed_source = None
        self._dismissed_opening = None
        self.hide()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        kind = event.type()
        if kind in (QEvent.Type.FocusOut, QEvent.Type.Hide, QEvent.Type.WindowDeactivate):
            self.hide()
        elif kind == QEvent.Type.FocusIn:
            self._schedule()
        elif kind in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            manual = event.key() == Qt.Key.Key_Space and event.modifiers() == (
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
            if manual:
                event.accept()
                if kind == QEvent.Type.KeyPress:
                    self.trigger_manually()
                return True
            completer = getattr(self._edit, "_autocomplete_completer", None)
            completing = completer is not None and completer.popup().isVisible()
            if kind == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape and self._popup.isVisible() and not completing:
                self._dismissed_opening = getattr(self, "_current_opening", None)
                self.hide()
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def _schedule(self) -> None:
        self._timer.start()

    def hide(self) -> None:
        self._timer.stop()
        self._popup.hide()
        self._active_func = None

    def trigger_manually(self) -> None:
        """Force-show the assistant for current cursor position (Ctrl+Shift+Space)."""
        self._dismissed_opening = None
        self._generation += 1
        self._cache.clear()
        self._timer.stop()
        self._update_popup()

    def _request_snapshot(self, source: str) -> None:
        if self._snapshot_pending or source == self._snapshot_failed_source:
            return
        self._snapshot_pending = True
        generation, signals = self._generation, self._signals

        def worker():
            try:
                result = SignatureDocument(source)
            except Exception:
                result = None
            try:
                signals.snapshot_ready.emit(generation, (source, result))
            except RuntimeError:
                pass

        threading.Thread(target=worker, name="MetaSignatureSnapshot", daemon=True).start()

    def _on_snapshot_ready(self, generation: int, response) -> None:
        self._snapshot_pending = False
        source, document = response
        if generation == self._generation and source == self._edit.toPlainText():
            if document is None:
                self._snapshot_failed_source = source
            else:
                self._snapshot = document
        self._update_popup()

    def _request_namespace(self, namespace: str) -> None:
        key = namespace.casefold()
        if not callable(self._provider) or key in self._pending or len(self._pending) >= 2:
            return
        self._request_id += 1
        request_id = self._request_id
        generation = self._generation
        self._pending[key] = request_id
        provider, signals = self._provider, self._signals

        def worker():
            try:
                result = dict(provider(namespace) or {})
            except Exception:
                result = {}
            try:
                signals.resolved.emit(request_id, key, (generation, result))
            except RuntimeError:
                pass  # The editor was closed while the RPC was running.

        threading.Thread(target=worker, name="MetaSignatureHelp", daemon=True).start()

    def _on_resolved(self, request_id: int, key: str, response) -> None:
        if self._pending.get(key) != request_id:
            return
        del self._pending[key]
        generation, result = response
        if generation == self._generation:
            if len(self._cache) >= 64:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = (time.monotonic() + (5.0 if result.get("found") else 1.0), result)
        self._update_popup()

    def _resolve(self, context, position: int) -> FunctionInfo | None:
        document = self._snapshot
        chain = context.chain
        if len(chain) == 1:
            name = chain[0]
            if document.is_shadowed(name, position):
                return None
            local = document.signatures.get(name.casefold(), [])
            if local:
                return _local_function_info(local[0]) if len(local) == 1 else None
            return None if name.casefold() in document.callable_names else get_function_info(name)
        if document.is_shadowed(chain[0], position):
            return None
        if len(chain) == 3 and chain[0].casefold() in {"commonmodule", "загальниймодуль"}:
            namespace, name = chain[1:]
        elif len(chain) == 2:
            namespace, name = chain
        else:
            return None
        key = namespace.casefold()
        expires, result = self._cache.get(key, (0, {}))
        if expires <= time.monotonic():
            self._request_namespace(namespace)
            return None
        if not result.get("found"):
            return None
        matches = [member for member in result.get("members", []) if isinstance(member, dict)
                   and str(member.get("name", "")).casefold() == name.casefold()
                   and member.get("kind") in {"function", "procedure"}]
        if len(matches) != 1:
            return None
        member = matches[0]
        title = ".".join((*chain[:-1], str(member["name"])))
        return FunctionInfo(title, title,
                            tuple(ParamInfo(str(p), str(p)) for p in member.get("params", [])),
                            category_uk="Загальний модуль", category_en="Common module",
                            is_procedure=member["kind"] == "procedure")

    def _update_popup(self) -> None:
        """Analyse current cursor context and update the popup."""
        try:
            if not self._edit.isVisible() or not self._edit.hasFocus():
                self.hide()
                return
            cursor = self._edit.textCursor()
            rect = self._edit.cursorRect(cursor)
            if not self._edit.viewport().rect().intersects(rect):
                self.hide()
                return
            source = self._edit.toPlainText()
            if self._snapshot is None or self._snapshot.source != source:
                if len(source) > 32_000:
                    self._request_snapshot(source)
                    self.hide()
                    return
                self._snapshot = SignatureDocument(source)
            position = len(source.encode("utf-16-le")[:cursor.position() * 2].decode("utf-16-le"))
            context = self._snapshot.context_at(position)
            if context is None:
                self._dismissed_opening = None
                self.hide()
                return
            self._current_opening = context.opening_position
            if self._dismissed_opening == context.opening_position:
                self.hide()
                return
            func = self._resolve(context, position)
            if func is None:
                self.hide()
                return

            self._active_func = func
            self._popup.set_language(self._language)

            anchor = self._edit.viewport().mapToGlobal(rect.topLeft())
            self._popup.show_for(func, context.active_parameter)
            screen = self._edit.screen().availableGeometry()
            x = max(screen.left(), min(anchor.x(), screen.right() - self._popup.width()))
            y = anchor.y() - self._popup.height() - 6
            if y < screen.top():
                y = anchor.y() + rect.height() + 4
            y = max(screen.top(), min(y, screen.bottom() - self._popup.height()))
            self._popup.move(x, y)

        except Exception:
            self.hide()  # Never retain a stale signature after a failed lookup.


# ---------------------------------------------------------------------------
# Context analyser
# ---------------------------------------------------------------------------

def _analyse_call_context(
    line: str, cursor_pos: int
) -> Tuple[str, int, bool]:
    """Compatibility wrapper; accepts multiline source and Python offsets."""
    context = SignatureDocument(line).context_at(cursor_pos)
    return (".".join(context.chain), context.active_parameter, True) if context else ("", 0, False)


# ---------------------------------------------------------------------------
# Full Syntax Assistant Panel (dockable, like 1C)
# ---------------------------------------------------------------------------

class SyntaxAssistantPanel(QWidget):
    """Full-featured Syntax Assistant panel — shows function list + details.

    This is the expanded version (like 1C's right-side assistant panel).
    Can be shown as a side panel in the configurator.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._language = "uk"
        self._build_ui()
        self._populate()

    def set_language(self, lang: str) -> None:
        self._language = lang
        self._populate()

    def _build_ui(self) -> None:
        from PySide6.QtWidgets import QListWidget, QSplitter, QLineEdit
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # Search bar
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍 Пошук функції / Search function...")
        self._search.textChanged.connect(self._on_search)
        root.addWidget(self._search)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # Function list
        self._list = QListWidget()
        self._list.currentTextChanged.connect(self._on_func_selected)
        splitter.addWidget(self._list)

        # Detail panel
        self._detail = QLabel()
        self._detail.setWordWrap(True)
        self._detail.setTextFormat(Qt.TextFormat.RichText)
        self._detail.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._detail.setContentsMargins(6, 6, 6, 6)

        detail_scroll = QScrollArea()
        detail_scroll.setWidget(self._detail)
        detail_scroll.setWidgetResizable(True)
        splitter.addWidget(detail_scroll)

        splitter.setSizes([200, 300])
        root.addWidget(splitter, 1)

    def _populate(self, filter_text: str = "") -> None:
        self._list.clear()
        fl = filter_text.lower()
        for f in _FUNCTIONS:
            name = f.name_uk if self._language in ("uk", "mixed") else f.name_en
            alt = f.name_en if self._language in ("uk", "mixed") else f.name_uk
            if fl and fl not in name.lower() and fl not in alt.lower():
                continue
            self._list.addItem(name)

    def _on_search(self, text: str) -> None:
        self._populate(text)

    def _on_func_selected(self, name: str) -> None:
        if not name:
            return
        func = get_function_info(name)
        if not func:
            self._detail.setText("")
            return

        lang_uk = self._language in ("uk", "mixed")
        fname = func.name_uk if lang_uk else func.name_en
        fdesc = func.description_uk if lang_uk else func.description_en
        cat = func.category_uk if lang_uk else func.category_en
        kw = ("Процедура" if func.is_procedure else "Функція") if lang_uk else \
             ("Procedure" if func.is_procedure else "Function")

        html = f"<h3 style='margin:0;color:#82AAFF'>{fname}</h3>"
        html += f"<p style='color:#9CA3AF;margin:2px 0'><b>{cat}</b> · {kw}</p>"
        html += f"<p style='margin:4px 0'>{fdesc}</p>"

        if func.params:
            params_label = "Параметри:" if lang_uk else "Parameters:"
            html += f"<p><b>{params_label}</b></p><ul style='margin:0;padding-left:16px'>"
            for p in func.params:
                pname = p.name_uk if lang_uk else p.name_en
                pdesc = p.description_uk if lang_uk else p.description_en
                opt_mark = " <i>(опц.)</i>" if p.optional else ""
                html += f"<li><b style='color:#FFCB6B'>{pname}</b>"
                if p.type_hint:
                    html += f": <span style='color:#89DDFF'>{p.type_hint}</span>"
                html += opt_mark
                if pdesc:
                    html += f" — {pdesc}"
                html += "</li>"
            html += "</ul>"

        if func.return_type:
            ret_label = "Повертає:" if lang_uk else "Returns:"
            html += f"<p><b>{ret_label}</b> <span style='color:#C3E88D'>{func.return_type}</span></p>"

        # Show both names
        if func.name_uk != func.name_en:
            also = f"Також: <code>{func.name_en if lang_uk else func.name_uk}</code>"
            html += f"<p style='color:#546E7A;font-size:9pt'>{also}</p>"

        self._detail.setText(html)
