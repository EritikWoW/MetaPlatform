from __future__ import annotations

import base64
import zlib

import src.infra.onec.onecd_source as onecd_source

from src.infra.onec.onecd_source import (
    ONECD_METADATA_KIND_MAP,
    ONECD_PLATFORM_GROUP_KIND_FALLBACK,
    OneCDMetadataObject,
    _collect_standard_subsystem_guid_order,
    _decode_table_file_payload,
    _extract_bsl_source,
    _extract_subsystem_help_pages,
    _extract_config_group_members,
    _extract_guid_refs,
    _extract_owned_child_refs,
    _extract_params_metadata_index,
    _infer_config_group_kind,
    _looks_like_common_form_name,
    _looks_like_common_picture_name,
    _metadata_xml_bytes,
    _normalize_subsystem_label,
    _owned_child_ref_scores,
    _select_configuration_root_module_texts,
    _select_primary_module_texts,
    _subsystem_command_interface_xml_bytes,
    _subsystem_help_xml_bytes,
    _validated_bsl_source,
)
from src.infra.onec.importer import parse_subsystem_command_interface, parse_subsystem_help_pages
from src.infra.onec.onec_requisites_parser import OneCXmlParser


def test_extract_owned_child_refs_uses_only_collection_prefix() -> None:
    owner = "cc9cedf1-410d-414a-a05f-f167b8908470"
    child = "65b82f4a-2dce-4b2c-84df-946af4e1d332"
    grouped_child = "11111111-2222-3333-4444-555555555555"
    default_child = "12345678-1234-1234-1234-123456789abc"
    collection = "99999999-8888-7777-6666-555555555555"
    referenced = "aae429a9-3e2f-4074-822e-24bb401b2639"
    text = (
        "{1," + child + ","
        "{0,{1,{0,0," + owner + '},"Owner",{1,"uk","Owner"},"",0,0},'
        + default_child + ","
        + "{" + collection + ",1," + grouped_child + "},"
        + referenced + ",0}}"
    )

    assert _extract_owned_child_refs(text, owner) == [grouped_child, child]
    assert _owned_child_ref_scores(text, owner) == {
        grouped_child: 1,
        child: 2,
        default_child: 3,
    }


def test_extract_params_metadata_index_maps_child_to_owner_and_name() -> None:
    child = "b1c1c2eb-f9cd-468a-8398-b0b7f611f832"
    owner = "0adf02da-940a-4bfc-afa5-59605494a169"
    text = (
        'prefix,' + child + ',' + owner + ',39,"Изменить",\r\n'
        '{1,2,{"uk","Змінити"}}'
    )

    assert _extract_params_metadata_index(text) == {
        child: (owner, 39, "Изменить")
    }


def test_onecd_metadata_xml_is_compatible_with_requisites_parser() -> None:
    obj = OneCDMetadataObject(
        uuid="b56f25d2-72a9-4d80-8998-77ac3097c873",
        dbname_kind="Reference",
        folder="Catalogs",
        xml_tag="Catalog",
        family="catalog",
        dump_root="Catalog",
        name="КлассификаторБанков",
        title="Класифікатор банків",
        synonyms={"uk": "Класифікатор банків", "ru": "Классификатор банков"},
        order=20,
        origin="1cd://Config/b56f25d2-72a9-4d80-8998-77ac3097c873",
    )

    parsed = OneCXmlParser().parse_bytes_map(
        {"Catalogs/КлассификаторБанков.xml": _metadata_xml_bytes(obj)}
    )

    assert len(parsed) == 1
    assert parsed[0].obj_type == "catalog"
    assert parsed[0].name == "КлассификаторБанков"
    assert parsed[0].uuid == obj.uuid
    assert parsed[0].synonyms["uk"] == "Класифікатор банків"


def test_onecd_subsystem_metadata_xml_emits_content_refs_and_child_subsystems() -> None:
    obj = OneCDMetadataObject(
        uuid="b56f25d2-72a9-4d80-8998-77ac3097c873",
        dbname_kind="Subsystem",
        folder="Subsystems",
        xml_tag="Subsystem",
        family="subsystem",
        dump_root="Subsystem",
        name="Администрирование",
        title="Адміністрування",
        synonyms={"uk": "Адміністрування", "ru": "Администрирование"},
        order=1,
        origin="1cd://Config/b56f25d2-72a9-4d80-8998-77ac3097c873",
        child_subsystems=["НастройкаПараметровСистемы"],
        content_refs=["Catalog.Products", "CommonCommand.OpenSettings"],
    )

    parsed = OneCXmlParser().parse_bytes_map(
        {"Subsystems/Администрирование.xml": _metadata_xml_bytes(obj)}
    )

    assert len(parsed) == 1
    payload = parsed[0].to_mp_payload()
    assert payload["content_refs"] == ["Catalog.Products", "CommonCommand.OpenSettings"]
    assert payload["child_subsystems"] == ["НастройкаПараметровСистемы"]


def test_onecd_sync_subsystem_metadata_links_merges_child_and_content_refs() -> None:
    parent = OneCDMetadataObject(
        uuid="sub-1",
        dbname_kind="Subsystem",
        folder="Subsystems",
        xml_tag="Subsystem",
        family="subsystem",
        dump_root="Subsystem",
        name="Administration",
        title="Administration",
        synonyms={},
        order=1,
        origin="1cd://Config/sub-1",
        child_subsystems=["ExistingChild"],
        content_refs=["CommonCommand.OpenSettings"],
    )
    child = OneCDMetadataObject(
        uuid="sub-2",
        dbname_kind="Subsystem",
        folder="Subsystems",
        xml_tag="Subsystem",
        family="subsystem",
        dump_root="Subsystem",
        name="NestedSubsystem",
        title="NestedSubsystem",
        synonyms={},
        order=2,
        origin="1cd://Config/sub-2",
    )

    onecd_source._sync_subsystem_metadata_links(
        {"sub-1": parent, "sub-2": child},
        {"sub-1": ["sub-2"]},
        {"sub-1": ["Catalog.Products", "CommonCommand.OpenSettings"]},
    )

    assert parent.child_subsystems == ["ExistingChild", "NestedSubsystem"]
    assert parent.content_refs == ["CommonCommand.OpenSettings", "Catalog.Products"]
    assert child.child_subsystems == []
    assert child.content_refs == []


def test_onecd_metadata_objects_keep_subsystem_tree_order_and_parent_links() -> None:
    source = onecd_source.OneCDConfigSource("dummy")
    root = OneCDMetadataObject(
        uuid="sub-root",
        dbname_kind="Subsystem",
        folder="Subsystems",
        xml_tag="Subsystem",
        family="subsystem",
        dump_root="Subsystem",
        name="Root",
        title="Root",
        synonyms={},
        order=1,
        origin="1cd://Config/sub-root",
    )
    child = OneCDMetadataObject(
        uuid="sub-child",
        dbname_kind="Subsystem",
        folder="Subsystems",
        xml_tag="Subsystem",
        family="subsystem",
        dump_root="Subsystem",
        name="Child",
        title="Child",
        synonyms={},
        order=2,
        origin="1cd://Config/sub-child",
    )
    other = OneCDMetadataObject(
        uuid="cat-1",
        dbname_kind="Reference",
        folder="Catalogs",
        xml_tag="Catalog",
        family="catalog",
        dump_root="Catalog",
        name="Products",
        title="Products",
        synonyms={},
        order=3,
        origin="1cd://Config/cat-1",
    )

    onecd_source._sync_subsystem_metadata_links(
        {"sub-root": root, "sub-child": child},
        {"sub-root": ["sub-child"]},
        {"sub-root": []},
    )
    object.__setattr__(root, "parent_guid", "")
    object.__setattr__(child, "parent_guid", "sub-root")

    objects = [other, root, child]
    ordered = [other, root, child]
    assert [obj.uuid for obj in ordered] == ["cat-1", "sub-root", "sub-child"]
    assert root.parent_guid == ""
    assert child.parent_guid == "sub-root"


def test_onecd_subsystem_tree_paths_are_derived_from_parent_links() -> None:
    root = OneCDMetadataObject(
        uuid="sub-root",
        dbname_kind="Subsystem",
        folder="Subsystems",
        xml_tag="Subsystem",
        family="subsystem",
        dump_root="Subsystem",
        name="Administration",
        title="Administration",
        synonyms={},
        order=1,
        origin="1cd://Config/sub-root",
    )
    child = OneCDMetadataObject(
        uuid="sub-child",
        dbname_kind="Subsystem",
        folder="Subsystems",
        xml_tag="Subsystem",
        family="subsystem",
        dump_root="Subsystem",
        name="Integration",
        title="Integration",
        synonyms={},
        order=2,
        origin="1cd://Config/sub-child",
    )
    onecd_source._sync_subsystem_metadata_links(
        {"sub-root": root, "sub-child": child},
        {"sub-root": ["sub-child"]},
        {"sub-root": []},
    )
    object.__setattr__(root, "parent_guid", "")
    object.__setattr__(child, "parent_guid", "sub-root")
    object.__setattr__(root, "tree_path", "Administration")
    object.__setattr__(child, "tree_path", "Administration/Integration")

    assert root.tree_path == "Administration"
    assert child.tree_path == "Administration/Integration"


def test_onecd_metadata_catalog_includes_virtual_and_tree_metadata() -> None:
    obj = OneCDMetadataObject(
        uuid="sub-virt",
        dbname_kind="Subsystem",
        folder="Subsystems",
        xml_tag="Subsystem",
        family="subsystem",
        dump_root="Subsystem",
        name="Virtual",
        title="Virtual",
        synonyms={},
        order=1,
        origin="1cd://Config/sub-virt",
        parent_guid="sub-root",
        tree_path="Root/Virtual",
        is_virtual=True,
        virtual_reason="alias-root:Root",
    )

    src = onecd_source.OneCDConfigSource("dummy")
    object.__setattr__(src, "_objects", [obj])
    object.__setattr__(src, "_files", {})

    catalog = src.metadata_catalog()

    assert catalog[0]["parent_guid"] == "sub-root"
    assert catalog[0]["tree_path"] == "Root/Virtual"
    assert catalog[0]["is_virtual"] is True
    assert catalog[0]["virtual_reason"] == "alias-root:Root"


def test_onecd_common_type_heuristics_cover_obvious_general_nodes() -> None:
    assert _looks_like_common_form_name("ФормаСписка")
    assert _looks_like_common_form_name("ОсновнаяФорма")
    assert _looks_like_common_picture_name("ПиктограммаТренда")
    assert _looks_like_common_picture_name("КартинкаПометка")


def test_onecd_classifies_serialized_managed_form_without_form_api_calls() -> None:
    assert onecd_source._classify_owner_child(
        "ФайлСуществует",
        {0: "{3,\n{38,0,0,0,0,1,0,0,00000000-0000-0000-0000-000000000000,1,{0}}"},
    ) == "form"


def test_onecd_extract_bsl_source_strips_serialized_1c_prelude() -> None:
    raw = (
        "\x00\x01\x02\x03 header bytes\r\n"
        "00000018 00000018 7fffffff \r\n"
        "G\x00\x00\x00A\x00\x00\x00 binary chunk\r\n"
        '\ufeff{3,1,0,"",0}///////////////////////////////////////////////////////////////////////////\r\n'
        "\r\n"
        "#Область ПрограммныйИнтерфейс\r\n"
        "00000020 00000020 7fffffff\r\n"
        "\ufffdB|\ufffdMB\ufffdtext\r\n"
        "Процедура Тест() Экспорт\r\n"
        "\tВозврат;\r\n"
        "КонецПроцедуры\r\n"
    )

    extracted = _extract_bsl_source(raw)

    assert extracted.startswith("#Область ПрограммныйИнтерфейс")
    assert "Процедура Тест() Экспорт" in extracted
    assert "00000020 00000020 7fffffff" not in extracted
    assert "\ufffd" not in extracted
    assert not extracted.startswith("{3,")


def test_normalize_subsystem_label_strips_numeric_prefix() -> None:
    assert _normalize_subsystem_label("2 Закупівлі") == "Закупівлі"
    assert _normalize_subsystem_label("Закупівлі") == "Закупівлі"


def test_onecd_extract_bsl_source_returns_plain_module_text_unchanged() -> None:
    raw = "Процедура Тест() Экспорт\r\n\tВозврат;\r\nКонецПроцедуры\r\n"

    extracted = _extract_bsl_source(raw)

    assert extracted == raw.strip()


def test_onecd_extract_bsl_source_selects_complete_stream_after_truncated_preview() -> None:
    raw = (
        "Процедура ПередЗаписью(Отказ)\r\n"
        "\tЕсли Отказ Тогда\r\n"
        "\x10w\x7fMB\x02\x10K,OB\x02text\r\n"
        "#Область ОбработчикиСобытий\r\n"
        "Процедура ПередЗаписью(Отказ)\r\n"
        "\tЕсли Отказ Тогда\r\n"
        "\t\tВозврат;\r\n"
        "\tКонецЕсли;\r\n"
        "КонецПроцедуры\r\n"
        "#КонецОбласти\r\n"
    )

    extracted = _extract_bsl_source(raw)

    assert extracted.startswith("#Область ОбработчикиСобытий")
    assert extracted.count("Процедура ПередЗаписью") == 1
    assert extracted.count("КонецПроцедуры") == 1
    assert "MB" not in extracted
    assert not any(ord(ch) < 0x20 and ch not in "\t\r\n" for ch in extracted)


def test_onecd_extract_bsl_source_selects_complete_segment_between_multiple_streams() -> None:
    raw = (
        "Процедура Первая()\r\n"
        "\x02preview text\r\n"
        "Процедура Целевая()\r\n"
        "\tВозврат;\r\n"
        "КонецПроцедуры\r\n"
        "\x02next text\r\n"
        "Процедура Последняя()\r\n"
    )

    extracted = _extract_bsl_source(raw)

    assert "Процедура Целевая" in extracted
    assert "Процедура Первая" not in extracted
    assert "Процедура Последняя" not in extracted


def test_onecd_extract_bsl_source_recognizes_utf16_like_text_marker() -> None:
    raw = (
        "Процедура Обрезанная()\r\n"
        "\x10w\x7f\ufffdMB\x02\x00\x10K\ufffd,OB\x02\x00\x00t\x00e\x00x\x00t\x00\x00\r\n"
        "Процедура Полная()\r\n"
        "КонецПроцедуры\r\n"
    )

    extracted = _extract_bsl_source(raw)

    assert "Процедура Полная" in extracted
    assert "Процедура Обрезанная" not in extracted


def test_onecd_extract_bsl_source_rejects_truncated_preview() -> None:
    raw = "#Область ОбработчикиСобытий\r\nПроцедура ПередЗаписью(Отказ)\r\n\tВозврат;\r\n"

    assert _extract_bsl_source(raw) == ""


def test_onecd_extract_bsl_source_trims_serialized_form_tail() -> None:
    raw = (
        "#Область ОбработчикиСобытий\r\n"
        "Процедура СписокВыбор()\r\n"
        '\tЕсли Параметры.Свойство(""АвтоТест"") Тогда\r\n'
        "\tКонецЕсли;\r\n"
        "КонецПроцедуры\r\n"
        "#КонецОбласти\r\n"
        '",\r\n'
        "{4,1,{9,{1},0,\"Список\"}}\r\n"
    )

    extracted = _extract_bsl_source(raw, serialized_container=True)

    assert extracted.endswith("#КонецОбласти")
    assert "{4,1" not in extracted
    assert 'Свойство("АвтоТест")' in extracted


def test_onecd_validated_bsl_source_preserves_multiline_query_separator() -> None:
    raw = (
        "Функция ПолучитьДанные() Экспорт\r\n"
        "\tЗапрос = Новый Запрос;\r\n"
        "\tЗапрос.Текст =\r\n"
        '\t\t"ВЫБРАТЬ\r\n'
        '\t\t|\tТаблица.Поле\r\n'
        '\t\t|ИЗ Таблица",\r\n'
        "\tВозврат Запрос.Выполнить();\r\n"
        "КонецФункции\r\n"
        "\r\n"
        "Процедура Продолжение() Экспорт\r\n"
        "КонецПроцедуры\r\n"
    )

    extracted = _validated_bsl_source(raw)

    assert "ИЗ Таблица" in extracted
    assert "Процедура Продолжение" in extracted


def test_onecd_extract_bsl_source_trims_tail_attached_to_end_region() -> None:
    raw = (
        "#Область ОбработчикиСобытий\r\n"
        "Процедура Тест()\r\n"
        "КонецПроцедуры\r\n"
        '#КонецОбласти",\r\n'
        "{4,3,{9,{1}}}\r\n"
    )

    extracted = _extract_bsl_source(raw, serialized_container=True)

    assert extracted.endswith("#КонецОбласти")
    assert "{4,3" not in extracted


def test_onecd_extract_bsl_source_trims_preview_fragment_after_last_region() -> None:
    raw = (
        "#Область ОбработчикиСобытий\r\n"
        "Процедура Тест()\r\n"
        "КонецПроцедуры\r\n"
        "#КонецОбласти\r\n"
        "ник,\r\n"
    )

    extracted = _extract_bsl_source(raw)

    assert extracted.endswith("#КонецОбласти")
    assert "ник," not in extracted


def test_onecd_extract_bsl_source_trims_preview_after_last_procedure() -> None:
    raw = (
        "Процедура ОбработкаКоманды()\r\n"
        "\tВозврат;\r\n"
        "КонецПроцедуры\r\n"
        "\tПараметрыВыполненияКоманды.Источник,\r\n"
        "\tНовый УникальныйИдентификатор(\"00000\r\n"
    )

    extracted = _extract_bsl_source(raw)

    assert extracted.endswith("КонецПроцедуры")
    assert "ПараметрыВыполненияКоманды" not in extracted


def test_onecd_validated_bsl_source_recovers_complete_duplicate_stream() -> None:
    raw = (
        "Процедура Выполнить()\r\n"
        "КонецПроцедуры\r\n"
        "\t| damaged preview\r\n\r\n"
        "#Если Сервер Тогда\r\n"
        "#Область Обработчики\r\n"
        "Процедура Выполнить()\r\n"
        "КонецПроцедуры\r\n"
        "#КонецОбласти\r\n"
        "#КонецЕсли\r\n"
    )

    extracted = _validated_bsl_source(raw)

    assert extracted.startswith("#Если Сервер Тогда")
    assert extracted.count("Процедура Выполнить") == 1
    assert "damaged preview" not in extracted


def test_onecd_validated_bsl_source_prefers_complete_api_stream() -> None:
    raw = (
        "Процедура Короткая() Экспорт\r\n"
        "КонецПроцедуры\r\n"
        "\x10w\x7fMB\x02\x10K,OB\x02text\r\n"
        "Процедура Короткая() Экспорт\r\n"
        "КонецПроцедуры\r\n"
        "\r\n"
        "Функция Полная() Экспорт\r\n"
        "\tВозврат 1;\r\n"
        "КонецФункции\r\n"
    )

    extracted = _validated_bsl_source(raw)

    assert extracted.count("Процедура Короткая") == 1
    assert "Функция Полная" in extracted


def test_onecd_validated_bsl_source_joins_module_split_by_binary_marker() -> None:
    raw = (
        "Процедура Первая() Экспорт\r\n"
        "КонецПроцедуры\r\n"
        "\x10w\x7fMB\x02\x10K,OB\x02text\r\n"
        "Функция Вторая() Экспорт\r\n"
        "\tВозврат 2;\r\n"
        "КонецФункции\r\n"
    )

    extracted = _validated_bsl_source(raw)

    assert "Процедура Первая" in extracted
    assert "Функция Вторая" in extracted
    assert "MB" not in extracted


def test_onecd_validated_bsl_source_rejects_unrecoverable_fragment() -> None:
    raw = (
        "Процедура Поврежденная()\r\n"
        "\tЕсли Истина Тогда\r\n"
        "\t\tВозврат;\r\n"
    )

    assert _validated_bsl_source(raw) == ""


def test_onecd_extract_bsl_source_preserves_terminal_preprocessor_closures() -> None:
    raw = (
        "#Если Сервер Тогда\r\n"
        "#Область Обработчики\r\n"
        "Процедура Тест()\r\n"
        "КонецПроцедуры\r\n"
        "#КонецОбласти\r\n"
        "#КонецЕсли\r\n"
    )

    extracted = _extract_bsl_source(raw)

    assert extracted.endswith("#КонецЕсли")
    assert "#КонецОбласти" in extracted


def test_onecd_validated_bsl_source_preserves_declaration_after_region() -> None:
    raw = (
        "#Область ПубличныйИнтерфейс\r\n"
        "Процедура Первая() Экспорт\r\n"
        "КонецПроцедуры\r\n"
        "#КонецОбласти\r\n"
        "\r\n"
        "Функция Вторая() Экспорт\r\n"
        "\tВозврат 2;\r\n"
        "КонецФункции\r\n"
    )

    extracted = _validated_bsl_source(raw)

    assert "Процедура Первая" in extracted
    assert "Функция Вторая" in extracted


def test_onecd_extract_bsl_source_unescapes_detected_quote_layer_without_tail() -> None:
    raw = (
        "Процедура ПриСоздании()\r\n"
        '\tЕсли Параметры.Свойство(""АвтоТест"") Тогда\r\n'
        "\tКонецЕсли;\r\n"
        "КонецПроцедуры\r\n"
    )

    assert 'Свойство("АвтоТест")' in _extract_bsl_source(raw, serialized_container=True)


def test_onecd_extract_bsl_source_preserves_native_empty_and_escaped_strings() -> None:
    raw = (
        "Процедура Тест()\r\n"
        '\tПустая = "";\r\n'
        '\tТекст = "Он сказал ""Да""";\r\n'
        "КонецПроцедуры\r\n"
    )

    extracted = _extract_bsl_source(raw)

    assert 'Пустая = ""' in extracted
    assert '"Он сказал ""Да"""' in extracted


def test_onecd_extract_subsystem_help_pages_decodes_base64_pages() -> None:
    ru_html = "<html><body>ru</body></html>"
    uk_html = "<html><body>uk</body></html>"
    raw = (
        '{5,2,"ru",'
        f'{{#base64:{base64.b64encode(ru_html.encode("utf-8")).decode("ascii")}}},'
        '"uk",'
        f'{{#base64:{base64.b64encode(uk_html.encode("utf-8")).decode("ascii")}}}'
        "}"
    )

    pages = _extract_subsystem_help_pages(raw)

    assert pages == {"ru": ru_html, "uk": uk_html}


def test_onecd_subsystem_help_xml_round_trips_page_names() -> None:
    xml_bytes = _subsystem_help_xml_bytes(["ru", "uk"])

    assert parse_subsystem_help_pages(xml_bytes) == ["ru", "uk"]


def test_onecd_subsystem_command_interface_xml_emits_subsystem_order() -> None:
    obj = OneCDMetadataObject(
        uuid="b56f25d2-72a9-4d80-8998-77ac3097c873",
        dbname_kind="Subsystem",
        folder="Subsystems",
        xml_tag="Subsystem",
        family="subsystem",
        dump_root="Subsystem",
        name="Администрирование",
        title="Адміністрування",
        synonyms={"uk": "Адміністрування", "ru": "Администрирование"},
        order=1,
        origin="1cd://Config/b56f25d2-72a9-4d80-8998-77ac3097c873",
        child_subsystems=["НастройкаПараметровСистемы", "НастройкаИнтеграции"],
    )

    parsed = parse_subsystem_command_interface(_subsystem_command_interface_xml_bytes(obj))

    assert parsed["subsystems_order"] == [
        "Subsystem.Администрирование.Subsystem.НастройкаПараметровСистемы",
        "Subsystem.Администрирование.Subsystem.НастройкаИнтеграции",
    ]


def test_onecd_extract_guid_refs_preserves_order_and_deduplicates() -> None:
    text = (
        "prefix 0421b67e-ed26-491d-ab98-ec59002ed4ce middle "
        "7d8acec9-f5a9-411e-921c-446ed0dd3332 middle "
        "0421b67e-ed26-491d-ab98-ec59002ed4ce tail "
        "cdbd26b1-9583-46e8-adf7-8cc705639892"
    )

    assert _extract_guid_refs(text) == [
        "0421b67e-ed26-491d-ab98-ec59002ed4ce",
        "7d8acec9-f5a9-411e-921c-446ed0dd3332",
        "cdbd26b1-9583-46e8-adf7-8cc705639892",
    ]


def test_onecd_collect_standard_subsystem_guid_order_uses_standard_row(monkeypatch) -> None:
    standard_guid = "0421b67e-ed26-491d-ab98-ec59002ed4ce"
    ref_a = "7d8acec9-f5a9-411e-921c-446ed0dd3332"
    ref_b = "cdbd26b1-9583-46e8-adf7-8cc705639892"
    ref_c = "c0e38c3e-7088-4e35-9d84-2d0ab9655402"
    sample_text = (
        "{1,\r\n"
        "{3,\r\n"
        "{1,\r\n"
        f'{{0,0,{standard_guid}}},"СтандартныеПодсистемы",\r\n'
        '{2,"ru","Стандартні підсистеми","uk","Стандартні підсистеми"},"",0,0}\r\n'
        "},0}\r\n"
        f"{ref_a} {ref_b} {standard_guid} {ref_c}\r\n"
    )
    rows = [
        {"FILENAME": standard_guid},
        {"FILENAME": ref_a},
        {"FILENAME": ref_b},
        {"FILENAME": ref_c},
    ]

    monkeypatch.setattr(
        onecd_source,
        "_read_blob_from_raw",
        lambda raw, row: sample_text.encode("utf-8") if row.get("FILENAME") == standard_guid else b"",
    )

    order = _collect_standard_subsystem_guid_order(rows, b"")

    assert order == [ref_a, ref_b, ref_c]


def test_onecd_metadata_kind_map_supports_scheduled_jobs() -> None:
    kind = ONECD_METADATA_KIND_MAP["ScheduledJobs"]

    assert kind.family == "scheduled_job"
    assert kind.folder == "ScheduledJobs"
    assert kind.xml_tag == "ScheduledJob"


def test_onecd_select_primary_module_texts_prefers_object_and_form_chunks() -> None:
    object_raw = (
        "00000018 00000018 7fffffff\r\n"
        "#Область ОбработчикиСобытий\r\n"
        "Процедура ОбработкаЗаполнения(ДанныеЗаполнения, СтандартнаяОбработка)\r\n"
        "КонецПроцедуры\r\n"
    )
    form_raw = (
        "00000018 00000018 7fffffff\r\n"
        "#Область ПрограммныйИнтерфейс\r\n"
        "Процедура ПоказатьПериод(Форма)\r\n"
        "КонецПроцедуры\r\n"
    )

    object_text, form_text = _select_primary_module_texts([object_raw, form_raw, "<html>help</html>"])

    assert "ОбработкаЗаполнения" in object_text
    assert "ПрограммныйИнтерфейс" in form_text
    assert object_text != form_text


def test_onecd_select_configuration_root_module_texts_prefers_root_signatures() -> None:
    managed_noise = (
        "#Область ПрограммныйИнтерфейс\r\n"
        "Функция ПараметрыФормыОшибкиОбращения(КонтекстВзаимодействия)\r\n"
        "\tВозврат Неопределено;\r\n"
        "КонецФункции\r\n"
    )
    managed_root = (
        "Перем глПодключаемоеОборудование Экспорт; // для кэширования на клиенте\r\n"
        "Перем глДоступныеТипыОборудования Экспорт;\r\n"
        "Перем ПараметрыПодсистемыОбменБанками Экспорт;\r\n"
        "Перем СообщенияДляЖурналаРегистрации Экспорт;\r\n"
        "Перем ПараметрыПриЗапускеИЗавершенииПрограммы Экспорт;\r\n"
        "Перем ПараметрыПодтвержденияЗакрытияФормы Экспорт;\r\n"
    )
    session_root = (
        "#Область ПрограммныйИнтерфейс\r\n"
        "Функция УстановкаПараметровСеанса(ИменаПараметровСеанса) Экспорт\r\n"
        "\tПередЗапускомПрограммы();\r\n"
        "КонецФункции\r\n"
    )
    external_root = (
        "#Область ПрограммныйИнтерфейс\r\n"
        "Функция АвторизованныйПользователь() Экспорт\r\n"
        "#Если Сервер Или ТолстыйКлиентОбычноеПриложение Или ВнешнееСоединение Тогда\r\n"
        "\tВозврат ПараметрыСеанса.ТекущийВнешнийПользователь;\r\n"
        "#КонецЕсли\r\n"
        "КонецФункции\r\n"
    )
    ordinary_root = (
        "#Область ПрограммныйИнтерфейс\r\n"
        "// Возвращает структуру параметров, необходимых для работы конфигурации на клиенте при запуске\r\n"
        "Функция ПараметрыРаботыКлиентаПриЗапуске() Экспорт\r\n"
        "\tЕсли ТипЗнч(ПараметрыПриЗапускеИЗавершенииПрограммы) <> Тип(\"Структура\") Тогда\r\n"
        "\t\tПараметрыПриЗапускеИЗавершенииПрограммы = Новый Структура;\r\n"
        "\tКонецЕсли;\r\n"
        "КонецФункции\r\n"
    )

    selected = _select_configuration_root_module_texts(
        {
            "managed-noise.0": managed_noise,
            "managed-root.0": managed_root,
            "session-root.0": session_root,
            "external-root.0": external_root,
            "ordinary-root.0": ordinary_root,
        }
    )

    assert selected["ManagedApplicationModule.bsl"] == managed_root.strip()
    assert selected["SessionModule.bsl"] == session_root.strip()
    assert selected["ExternalConnectionModule.bsl"] == external_root.strip()
    assert selected["OrdinaryApplicationModule.bsl"] == ordinary_root.strip()


def test_onecd_decode_deflated_bsl_payload_with_binary_prelude() -> None:
    compressed = zlib.compressobj(wbits=-15)
    source_utf8 = b"Procedure HandleCommand(CommandParameter)"
    raw = (
        b"\xff\xff\xff\x7f\x00\x02\r\n00000018 00000018 7fffffff\r\n"
        + source_utf8
    )
    payload = compressed.compress(raw) + compressed.flush()

    decoded = _decode_table_file_payload(payload)

    assert "00000018" in decoded
    assert "Procedure HandleCommand" in decoded
    assert "\ufffd" not in decoded
    assert "\ufffd" not in decoded


def test_onecd_decode_cp1251_payload_before_lossy_utf8_fallback() -> None:
    expected = "\u041f\u0440\u043e\u0446\u0435\u0434\u0443\u0440\u0430 \u0422\u0435\u0441\u0442\u043e\u0432\u0430\u044f\u041f\u0440\u043e\u0446\u0435\u0434\u0443\u0440\u0430()\r\n\u041a\u043e\u043d\u0435\u0446\u041f\u0440\u043e\u0446\u0435\u0434\u0443\u0440\u044b"
    payload = expected.encode("cp1251")

    decoded = _decode_table_file_payload(payload)

    assert decoded == expected
    assert "�" not in decoded


def test_onecd_extract_bsl_source_trims_corrupt_duplicate_after_balanced_region() -> None:
    source = (
        "#Область ОбработчикиСобытий\r\n"
        "Процедура ОбработкаКоманды()\r\n"
        "КонецПроцедуры\r\n"
        "#КонецОбласти\r\n"
        "\ufffdповрежденный хвост\r\n"
        "КонецПроцедуры\r\n"
    )

    extracted = _extract_bsl_source(source)

    assert extracted.endswith("#КонецОбласти")
    assert extracted.count("КонецПроцедуры") == 1
    assert "поврежденный хвост" not in extracted


def test_onecd_extract_config_group_members_is_shape_based() -> None:
    group_guid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    member_a = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    member_b = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    text = f"{{{group_guid},2,{member_a},{member_b}}}"

    groups = _extract_config_group_members(text)

    assert groups == {group_guid: [member_a, member_b]}


def test_onecd_group_inference_prefers_dbnames_for_physical_groups() -> None:
    member_guid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    kind = _infer_config_group_kind(
        group_guid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        members=[member_guid],
        primary_by_guid={member_guid: (ONECD_METADATA_KIND_MAP["Reference"], 10)},
        read_base_text=lambda _guid: "",
        suffix_texts_for_guid=lambda _guid: {},
    )

    assert kind == ONECD_METADATA_KIND_MAP["Reference"]


def test_onecd_group_inference_uses_platform_collection_id_not_member_guids() -> None:
    member_guid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    group_guid = "0fe48980-252d-11d6-a3c7-0050bae0a776"

    kind = _infer_config_group_kind(
        group_guid=group_guid,
        members=[member_guid],
        primary_by_guid={},
        read_base_text=lambda _guid: "",
        suffix_texts_for_guid=lambda _guid: {},
    )

    assert ONECD_PLATFORM_GROUP_KIND_FALLBACK[group_guid] == ONECD_METADATA_KIND_MAP["CommonModule"]
    assert kind == ONECD_METADATA_KIND_MAP["CommonModule"]
