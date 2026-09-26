from src.client.forms.form_runtime_style import FormRuntimeStyleMixin
from src.client.forms.form_runtime_style import build_form_surface_stylesheet
from src.ui_qt.theme import build_dark_theme_stylesheet, build_hybrid_theme_stylesheet


def test_dark_theme_stylesheet_assembles_widget_fragments() -> None:
    qss = build_dark_theme_stylesheet()

    assert "QMenu::item" in qss
    assert "QComboBox::down-arrow" in qss
    assert "QHeaderView::section" in qss


def test_hybrid_theme_stylesheet_assembles_widget_fragments() -> None:
    qss = build_hybrid_theme_stylesheet()

    assert "QMdiArea#Workspace" in qss
    assert "QFrame#FormWindowClient QDateEdit" in qss
    assert "QFrame#FormWindowClient QPushButton" in qss


def test_form_surface_stylesheet_assembles_widget_fragments() -> None:
    qss = build_form_surface_stylesheet(calendar_icon="calendar.svg")

    assert 'QDateEdit[mp_form_editor="true"]::down-arrow' in qss
    assert 'QPushButton[mp_form_command="true"]' in qss
    assert 'QTableView[mp_form_table="true"]' in qss


def test_form_surface_stylesheet_is_cached() -> None:
    calls = {"count": 0}

    def _fake_builder(*, calendar_icon: str) -> str:
        calls["count"] += 1
        return f"icon={calendar_icon}"

    original = FormRuntimeStyleMixin._form_surface_stylesheet
    FormRuntimeStyleMixin._form_surface_stylesheet.cache_clear()  # type: ignore[attr-defined]
    try:
        import src.client.forms.form_runtime_style as mod

        mod.build_form_surface_stylesheet = _fake_builder  # type: ignore[assignment]
        first = FormRuntimeStyleMixin._form_surface_stylesheet()
        second = FormRuntimeStyleMixin._form_surface_stylesheet()
    finally:
        import src.client.forms.form_runtime_style as mod

        mod.build_form_surface_stylesheet = build_form_surface_stylesheet  # type: ignore[assignment]
        FormRuntimeStyleMixin._form_surface_stylesheet.cache_clear()  # type: ignore[attr-defined]

    assert first == second
    assert calls["count"] == 1
