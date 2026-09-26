from src.dsl.languages import EN_PROFILE, MIXED_PROFILE, UK_PROFILE
from src.dsl.lexer import lex


def test_lexer_supports_assign_colon_equal() -> None:
    toks = lex("x := 1", UK_PROFILE)
    assert [t.type for t in toks[:3]] == ["IDENT", "ASSIGN", "NUMBER"]


def test_lexer_rejects_russian_undefined_as_keyword() -> None:
    toks = lex("неопределено", UK_PROFILE)
    assert toks[0].type == "IDENT"


def test_lexer_supports_english_undefined_literal() -> None:
    toks = lex("undefined", EN_PROFILE)
    assert toks[0].type == "UNDEFINED"


def test_lexer_supports_russian_keywords_in_mixed_profile() -> None:
    toks = lex("Если Истина Тогда Вернуть Ложь КонецЕсли", MIXED_PROFILE)
    assert [tok.type for tok in toks[:-1]] == [
        "KW_IF",
        "TRUE",
        "KW_THEN",
        "KW_RETURN",
        "FALSE",
        "KW_ENDIF",
    ]


def test_lexer_recognizes_ukrainian_for_each_in_operator() -> None:
    toks = lex("Для Кожного Елемент З Колекція Цикл КінецьЦиклу", MIXED_PROFILE)

    assert [tok.type for tok in toks[:-1]] == [
        "KW_FOR",
        "KW_EACH",
        "IDENT",
        "KW_IN",
        "IDENT",
        "KW_DO",
        "KW_ENDDO",
    ]


def test_lexer_supports_russian_preprocessor_endregion_in_mixed_profile() -> None:
    toks = lex("#Область Test\n#КонецОбласти", MIXED_PROFILE)
    assert [tok.type for tok in toks[:-1]] == [
        "KW_REGION",
        "IDENT",
        "KW_ENDREGION",
    ]


def test_preprocessor_words_are_identifiers_without_hash_prefix() -> None:
    mixed = lex("Область = 1", MIXED_PROFILE)
    english = lex("Region = 1", EN_PROFILE)
    ukrainian = lex("Використати = 1", UK_PROFILE)

    assert mixed[0].type == "IDENT"
    assert english[0].type == "IDENT"
    assert ukrainian[0].type == "IDENT"


def test_lexer_treats_backslash_as_literal_bsl_string_character() -> None:
    toks = lex(r'"C:\Temp\file.txt"', MIXED_PROFILE)

    assert toks[0].type == "STRING"
    assert toks[0].text == r"C:\Temp\file.txt"


def test_lexer_supports_bsl_doubled_quotes_and_apostrophe() -> None:
    toks = lex('"Ім\'я: ""файл"""', MIXED_PROFILE)

    assert toks[0].type == "STRING"
    assert toks[0].text == 'Ім\'я: "файл"'


def test_lexer_preserves_import_compatible_single_quoted_string() -> None:
    toks = lex("'ru=''Помилка'''", MIXED_PROFILE)

    assert toks[0].type == "STRING"
    assert toks[0].text == "ru='Помилка'"


def test_lexer_supports_bsl_number_with_trailing_decimal_point() -> None:
    toks = lex("Value = 0.; Other = 1.Property", MIXED_PROFILE)

    assert [(tok.type, tok.text) for tok in toks[:4]] == [
        ("IDENT", "Value"),
        ("EQ", "="),
        ("NUMBER", "0."),
        ("SEMICOLON", ";"),
    ]
    assert [(tok.type, tok.text) for tok in toks[6:10]] == [
        ("NUMBER", "1"),
        ("DOT", "."),
        ("IDENT", "Property"),
        ("EOF", ""),
    ]


def test_lexer_supports_bsl_multiline_string_with_source_comment() -> None:
    toks = lex(
        '"SELECT\n'
        '// source comment with "quoted-name"\n'
        '|FROM Table\n'
        '|WHERE Active"',
        MIXED_PROFILE,
    )

    assert toks[0].type == "STRING"
    assert toks[0].text == "SELECT\nFROM Table\nWHERE Active"
    assert toks[1].type == "EOF"
