import pytest

from src.configurator.domain.posting_constructor import find_posting_handler, generate_posting_handler
from src.dsl.languages import get_profile
from src.dsl.parser import parse


def test_generate_posting_handler_uses_selected_registers() -> None:
    code = generate_posting_handler([
        "AccumulationRegister.Sales",
        "InformationRegister.Totals",
        "AccumulationRegister.Sales",
    ])

    assert code.startswith("Процедура ОбробкаПроведення(Відмова, РежимПроведення)")
    assert code.count("Рухи.Sales.Записувати = Істина;") == 1
    assert "Рухи.Totals.Записувати = Істина;" in code
    assert code.endswith("КінецьПроцедури")


@pytest.mark.parametrize("language", ["uk", "en"])
def test_generated_handler_parses_in_supported_locale(language):
    code = generate_posting_handler(["AccumulationRegister.Sales"], language=language)
    _program, diagnostics = parse(code, get_profile(language))
    assert not diagnostics
    assert find_posting_handler(code) == 1


@pytest.mark.parametrize("refs", [
    [], ["Sales"], ["Document.Sales"], ["AccumulationRegister.Sales;Delete()"],
    ["AccumulationRegister.A.B"], ["AccumulationRegister.For"],
    ["AccumulationRegister.Sales", "InformationRegister.Sales"],
])
def test_constructor_rejects_unsafe_or_ambiguous_references(refs):
    with pytest.raises(ValueError):
        generate_posting_handler(refs)


@pytest.mark.parametrize("signature,ending", [
    ("Процедура ОбработкаПроведения(Отказ, РежимПроведения)", "КонецПроцедуры"),
    ("Процедура ОбробкаПроведення(Відмова, РежимПроведення)", "КінецьПроцедури"),
    ("Procedure Posting(Cancel, PostingMode)", "EndProcedure"),
])
def test_handler_lookup_handles_imported_and_supported_code(signature, ending):
    assert find_posting_handler("// comment\n" + signature + "\n" + ending) == 2


def test_handler_lookup_does_not_match_comments_or_string_literals():
    assert find_posting_handler('// Procedure Posting()\nText = "Procedure Posting()";') == 0


def test_handler_lookup_rejects_damaged_or_duplicate_code():
    code = generate_posting_handler(["AccumulationRegister.Sales"])
    with pytest.raises(ValueError):
        find_posting_handler(code + "\n" + code)
    with pytest.raises(ValueError):
        find_posting_handler('Text = "unterminated')
