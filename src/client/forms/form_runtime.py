"""src.client.forms.form_runtime — Runtime form renderer.

Рендерить FormModel збережену в БД конфігуратора.
Це єдина форма в клієнті — всі каталоги, документи, регістри
відображаються через неї. Ніяких хардкодних Python-форм.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from .form_runtime_build import FormRuntimeBuildMixin
from .form_runtime_fields import FormRuntimeFieldsMixin
from .form_runtime_state import FormRuntimeStateMixin
from .form_runtime_style import FormRuntimeStyleMixin


class FormRuntimeWidget(
    FormRuntimeStateMixin,
    FormRuntimeStyleMixin,
    FormRuntimeFieldsMixin,
    FormRuntimeBuildMixin,
    QWidget,
):
    """Єдиний рендерер форм клієнта.

    Signals:
        command(code)   — команда від кнопки (save, create, edit:<guid>, ...)
        data_changed()  — будь-яке поле змінилось
    """

    command = Signal(str)
    data_changed = Signal()
    reference_open_requested = Signal(str, str)  # metadata reference, record GUID
    list_stats_changed = Signal(int, int)  # (total_rows, selected_rows)
