from src.ui_qt.services.object_editor_profiles import (
    build_editor_sections,
    get_editor_page_specs,
    normalize_editor_profile_key,
)


def test_document_profile_contains_expected_pages() -> None:
    keys = [spec.key for spec in get_editor_page_specs("document")]
    assert keys[:6] == [
        "main",
        "subsystems",
        "functional_options",
        "data",
        "numbering",
        "movements",
    ]
    assert "rights" in keys
    assert "exchange" in keys


def test_register_alias_uses_shared_profile_order() -> None:
    assert normalize_editor_profile_key("register_accum") == "register"
    sections = build_editor_sections(
        "register_accum",
        {
            "main": lambda: object(),
            "resources": lambda: object(),
        },
    )
    assert [section.key for section in sections] == ["main", "resources"]


def test_subsystem_profile_contains_expected_pages() -> None:
    keys = [spec.key for spec in get_editor_page_specs("subsystem")]
    assert keys == [
        "main",
        "functional_options",
        "objects",
        "other",
    ]
