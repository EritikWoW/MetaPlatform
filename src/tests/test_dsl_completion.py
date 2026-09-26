from src.dsl.completion import completion_context, semantic_completion_candidates
from src.ui_qt.widgets.code_editor_widget import completion_candidates_for_editor


def test_completion_context_tracks_dotted_chain_and_replacement() -> None:
    source = "Значення = Метадані.Довідники.Тов"
    context = completion_context(source, len(source))

    assert context.chain == ("Метадані", "Довідники")
    assert context.prefix == "Тов"
    assert context.replace_length == 3


def test_metadata_completion_exposes_categories_objects_and_members() -> None:
    root = completion_context("Метадані.", len("Метадані."))
    collection = completion_context("Метадані.Довідники.", len("Метадані.Довідники."))
    obj = completion_context("Metadata.Catalogs.Products.", len("Metadata.Catalogs.Products."))

    assert "Довідники" in semantic_completion_candidates(root, [])
    assert "Products" in semantic_completion_candidates(
        collection,
        [],
        metadata_objects={"catalog": ["Products"]},
    )
    assert "FullName" in semantic_completion_candidates(obj, [])


def test_common_module_namespace_completion_uses_runtime_members() -> None:
    context = completion_context(
        "SettingsServer.Re",
        len("SettingsServer.Re"),
    )

    candidates = semantic_completion_candidates(
        context,
        [],
        namespace_members={
            "settingsserver": ("ReadSettings", "ResetCache"),
        },
    )

    assert context.chain == ("SettingsServer",)
    assert context.prefix == "Re"
    assert candidates == ["ReadSettings", "ResetCache"]


def test_editor_completion_includes_current_scope_parameters_and_locals() -> None:
    class _Edit:
        _autocomplete_words = set()
        _autocomplete_namespace_members = {}
        _autocomplete_metadata_objects = {}
        _autocomplete_namespace_provider = None
        _autocomplete_language = "uk"

    source = (
        "Процедура Обробити(Параметр)\n"
        "    Змін Локальна;\n"
        "    Локальна = Параметр\n"
        "    Ло\n"
        "КінецьПроцедури"
    )
    candidates = completion_candidates_for_editor(_Edit(), source, source.index("Ло") + 2)

    assert "Локальна" in candidates
    assert "Параметр" in candidates
