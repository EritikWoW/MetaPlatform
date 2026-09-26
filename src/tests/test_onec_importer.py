import pytest

from src.configurator.persistence.manifest_io import ensure_manifest, list_objects
from src.configurator.persistence.modules_dao import (
    get_module_text,
    insert_modules_bulk,
    make_module_row,
    purge_all_modules,
    list_modules_by_owner,
    resolve_common_module,
)
from src.configurator.persistence.modules_tables import ensure_modules_tables
from src.configurator.persistence.modules_tables import MODULES_TABLE
from src.tools.onec_import import (
    _create_localized_module_variants,
    _enrich_objects_with_requisites,
    import_onec_configuration,
)
from src.infra.onec.importer import (
    build_import_plan,
    build_import_plan_from_dump_info,
    build_import_profiles_from_dump_info,
    build_onec_form_model_from_xml,
    import_manifest_objects,
    parse_help_page_contents,
    parse_subsystem_command_interface,
    parse_subsystem_help_pages,
)
from src.infra.onec.module_transform import normalize_module_text
from src.infra.onec.onec_requisites_model import OneCMetaObject
from src.infra.onec.onec_requisites_parser import OneCXmlParser
from src.configurator.manifest_schema import ManifestObject
from src.mpdb.mpdb import Mpdb


def test_build_import_plan_includes_top_level_group_objects() -> None:
    plan = build_import_plan(
        [
            "Catalogs/Warehouses.xml",
            "Documents/SalesOrder.xml",
            "Reports/Turnover.xml",
        ]
    )
    got = {(spec.obj_type, spec.rel_xml) for spec in plan}
    assert ("catalog", "Catalogs/Warehouses.xml") in got
    assert ("document", "Documents/SalesOrder.xml") in got
    assert ("report", "Reports/Turnover.xml") in got


def test_build_import_plan_includes_xml_based_common_pictures() -> None:
    plan = build_import_plan(
        [
            "CommonPictures/AppLogo.xml",
            "CommonPictures/AppLogo/Ext/Picture.xml",
            "CommonPictures/AppLogo/Ext/Picture/Picture.png",
        ]
    )
    pics = [spec for spec in plan if spec.obj_type == "common_picture"]
    assert len(pics) == 1
    assert pics[0].rel_xml == "CommonPictures/AppLogo.xml"


def test_build_import_plan_includes_supported_common_object_folders() -> None:
    plan = build_import_plan(
        [
            "CommonAttributes/DataArea.xml",
            "CommandGroups/Administration.xml",
            "ScheduledJobs/NightlyRecalc.xml",
            "DocumentNumerators/Sales.xml",
            "Sequences/PostSequence.xml",
        ]
    )
    got = {(spec.obj_type, spec.rel_xml) for spec in plan}
    assert ("common_attribute", "CommonAttributes/DataArea.xml") in got
    assert ("command_group", "CommandGroups/Administration.xml") in got
    assert ("scheduled_job", "ScheduledJobs/NightlyRecalc.xml") in got
    assert ("document_numerator", "DocumentNumerators/Sales.xml") in got
    assert ("sequence", "Sequences/PostSequence.xml") in got


def test_build_import_plan_from_dump_info_prefers_metadata_index() -> None:
    source = _DictSource(
        {
            "ConfigDumpInfo.xml": b"""<?xml version='1.0' encoding='utf-8'?>
<ConfigDumpInfo xmlns='http://v8.1c.ru/8.3/xcf/dumpinfo'>
  <ConfigVersions>
    <Metadata name='Catalog.Products' id='cat-1'>
      <Metadata name='Catalog.Products.Attribute.Code' id='cat-1-a'/>
    </Metadata>
    <Metadata name='Subsystem.Sales' id='sub-1'/>
    <Metadata name='Subsystem.Sales.Subsystem.Retail' id='sub-2'/>
    <Metadata name='ScheduledJob.NightlyRecalc' id='sch-1'/>
    <Metadata name='Catalog.Products.ManagerModule' id='cat-1.2'/>
  </ConfigVersions>
</ConfigDumpInfo>
""",
            "Catalogs/Products.xml": b"",
            "Subsystems/Sales.xml": b"",
            "Subsystems/Sales/Subsystems/Retail.xml": b"",
            "ScheduledJobs/NightlyRecalc.xml": b"",
        }
    )

    plan = build_import_plan_from_dump_info(source, source.list_files())
    got = {(spec.obj_type, spec.rel_xml, spec.parent_kind, spec.parent_key) for spec in plan}
    assert ("catalog", "Catalogs/Products.xml", "group", "catalog") in got
    assert ("subsystem", "Subsystems/Sales.xml", "common_folder", "subsystems") in got
    assert ("scheduled_job", "ScheduledJobs/NightlyRecalc.xml", "common_folder", "scheduled_jobs") in got
    assert (
        "subsystem",
        "Subsystems/Sales/Subsystems/Retail.xml",
        "subsystem_parent",
        "Subsystems/Sales.xml",
    ) in got


def test_build_import_plan_from_dump_info_includes_common_command_roots() -> None:
    source = _DictSource(
        {
            "ConfigDumpInfo.xml": b"""<?xml version='1.0' encoding='utf-8'?>
<ConfigDumpInfo xmlns='http://v8.1c.ru/8.3/xcf/dumpinfo'>
  <ConfigVersions>
    <Metadata name='CommonCommand.OpenSettings' id='cmd-1'/>
    <Metadata name='CommonCommand.OpenSettings.CommandModule' id='cmd-1.2'/>
  </ConfigVersions>
</ConfigDumpInfo>
""",
            "CommonCommands/OpenSettings.xml": b"",
            "CommonCommands/OpenSettings/Ext/CommandModule.bsl": b"",
        }
    )

    plan = build_import_plan_from_dump_info(source, source.list_files())
    got = {(spec.obj_type, spec.rel_xml, spec.parent_kind, spec.parent_key) for spec in plan}

    assert ("common_command", "CommonCommands/OpenSettings.xml", "common_folder", "common_commands") in got


def test_build_import_plan_skips_subsystem_service_xml() -> None:
    plan = build_import_plan(
        [
            "Subsystems/Sales.xml",
            "Subsystems/Sales/Ext/CommandInterface.xml",
            "Subsystems/Sales/Ext/Help.xml",
            "Subsystems/Sales/Subsystems/Retail.xml",
            "Subsystems/Sales/Subsystems/Retail/Ext/CommandInterface.xml",
            "Subsystems/Sales/Subsystems/Retail/Ext/Help.xml",
        ]
    )

    rels = {spec.rel_xml for spec in plan if spec.obj_type == "subsystem"}
    assert "Subsystems/Sales.xml" in rels
    assert "Subsystems/Sales/Subsystems/Retail.xml" in rels
    assert "Subsystems/Sales/Ext/CommandInterface.xml" not in rels
    assert "Subsystems/Sales/Ext/Help.xml" not in rels
    assert "Subsystems/Sales/Subsystems/Retail/Ext/CommandInterface.xml" not in rels
    assert "Subsystems/Sales/Subsystems/Retail/Ext/Help.xml" not in rels


def test_build_import_profiles_from_dump_info_collects_components() -> None:
    source = _DictSource(
        {
            "ConfigDumpInfo.xml": b"""<?xml version='1.0' encoding='utf-8'?>
<ConfigDumpInfo xmlns='http://v8.1c.ru/8.3/xcf/dumpinfo'>
  <ConfigVersions>
    <Metadata name='Catalog.Products' id='cat-1'>
      <Metadata name='Catalog.Products.Attribute.Code' id='cat-1-a'/>
    <Metadata name='Catalog.Products.TabularSection.Items' id='cat-1-t'/>
    </Metadata>
    <Metadata name='Catalog.Products.Form.ItemForm' id='form-1'/>
    <Metadata name='Catalog.Products.Form.ItemForm.Form' id='form-1.0'/>
    <Metadata name='Catalog.Products.Form.ItemForm.Help' id='form-1.1'/>
    <Metadata name='Catalog.Products.ManagerModule' id='cat-1.2'/>
    <Metadata name='Catalog.Products.Command.Print' id='cmd-1'/>
    <Metadata name='Catalog.Products.Command.Print.CommandModule' id='cmd-1.2'/>
    <Metadata name='Catalog.Products.Template.PriceLayout' id='lay-1'/>
  </ConfigVersions>
</ConfigDumpInfo>
""",
            "Catalogs/Products.xml": b"",
            "Catalogs/Products/Forms/ItemForm.xml": b"",
            "Catalogs/Products/Forms/ItemForm/Ext/Form.xml": b"",
            "Catalogs/Products/Forms/ItemForm/Ext/Help.xml": b"",
            "Catalogs/Products/Ext/ManagerModule.bsl": b"",
            "Catalogs/Products/Commands/Print/Ext/CommandModule.bsl": b"",
            "Catalogs/Products/Templates/PriceLayout.xml": b"",
        }
    )
    plan = build_import_plan_from_dump_info(source, source.list_files())
    profiles = build_import_profiles_from_dump_info(source, source.list_files(), plan)
    profile = profiles["Catalogs/Products.xml"]
    assert profile.forms == ["Catalogs/Products/Forms/ItemForm.xml"]
    assert profile.commands == ["Catalogs/Products/Commands/Print.xml"]
    assert profile.layouts == ["Catalogs/Products/Templates/PriceLayout.xml"]
    assert profile.module_origins == [("Catalogs/Products/Ext/ManagerModule.bsl", "ManagerModule")]
    assert profile.child_metadata["attribute"] == ["Code"]
    assert profile.child_metadata["tabularsection"] == ["Items"]
    assert profile.form_specs[0].ext_form_rel == "Catalogs/Products/Forms/ItemForm/Ext/Form.xml"
    assert profile.form_specs[0].help_rel == "Catalogs/Products/Forms/ItemForm/Ext/Help.xml"
    assert profile.command_specs[0].module_origins == [
        ("Catalogs/Products/Commands/Print/Ext/CommandModule.bsl", "CommandModule")
    ]


def test_parse_subsystem_service_xml_collects_help_pages_and_command_visibility() -> None:
    help_xml = b"""<?xml version='1.0' encoding='utf-8'?>
<Help xmlns='http://v8.1c.ru/8.3/xcf/extrnprops'>
  <Page>ru</Page>
  <Page>uk</Page>
</Help>
"""
    command_xml = b"""<?xml version='1.0' encoding='utf-8'?>
<CommandInterface xmlns='http://v8.1c.ru/8.3/xcf/extrnprops' xmlns:xr='http://v8.1c.ru/8.3/xcf/readable'>
  <CommandsVisibility>
    <Command name='Catalog.Products.StandardCommand.OpenList'>
      <Visibility>
        <xr:Common>false</xr:Common>
      </Visibility>
    </Command>
  </CommandsVisibility>
</CommandInterface>
"""

    assert parse_subsystem_help_pages(help_xml) == ["ru", "uk"]
    assert parse_subsystem_command_interface(command_xml) == {
        "commands_visibility": [
            {
                "name": "Catalog.Products.StandardCommand.OpenList",
                "common": False,
            }
        ]
    }

    source = _DictSource(
        {
            "Subsystems/Sales/Ext/Help.xml": help_xml,
            "Subsystems/Sales/Ext/Help/ru.html": b"<h1>RU</h1>",
            "Subsystems/Sales/Ext/Help/uk.html": b"<h1>UK</h1>",
        }
    )
    assert parse_help_page_contents(
        source,
        help_rel="Subsystems/Sales/Ext/Help.xml",
        help_pages=["ru", "uk"],
        path_set=set(source.list_files()),
    ) == {
        "ru": "<h1>RU</h1>",
        "uk": "<h1>UK</h1>",
    }


def test_parse_subsystem_command_interface_collects_order_and_placement() -> None:
    command_xml = """<?xml version='1.0' encoding='utf-8'?>
<CommandInterface xmlns='http://v8.1c.ru/8.3/xcf/extrnprops' xmlns:xr='http://v8.1c.ru/8.3/xcf/readable'>
  <CommandsVisibility>
    <Command name='DataProcessor.Admin.Command.GeneralSettings'>
      <Visibility>
        <xr:Common>true</xr:Common>
      </Visibility>
    </Command>
  </CommandsVisibility>
  <CommandsPlacement>
    <Command name='DataProcessor.Admin.Command.GeneralSettings'>
      <CommandGroup>NavigationPanelOrdinary</CommandGroup>
      <Placement>Auto</Placement>
    </Command>
  </CommandsPlacement>
  <CommandsOrder>
    <Command name='DataProcessor.Admin.Command.GeneralSettings'>
      <CommandGroup>NavigationPanelOrdinary</CommandGroup>
    </Command>
    <Command name='CommonCommand.CryptoSetup'>
      <CommandGroup>CommandGroup.Настройки</CommandGroup>
    </Command>
  </CommandsOrder>
  <SubsystemsOrder>
    <Subsystem>Subsystem.Admin.Subsystem.Settings</Subsystem>
  </SubsystemsOrder>
  <GroupsOrder>
    <Group>NavigationPanelOrdinary</Group>
    <Group>CommandGroup.Настройки</Group>
  </GroupsOrder>
</CommandInterface>
""".encode("utf-8")
    assert parse_subsystem_command_interface(command_xml) == {
        "commands_visibility": [
            {
                "name": "DataProcessor.Admin.Command.GeneralSettings",
                "common": True,
            }
        ],
        "commands_placement": [
            {
                "name": "DataProcessor.Admin.Command.GeneralSettings",
                "command_group": "NavigationPanelOrdinary",
                "placement": "Auto",
            }
        ],
        "commands_order": [
            {
                "name": "DataProcessor.Admin.Command.GeneralSettings",
                "command_group": "NavigationPanelOrdinary",
            },
            {
                "name": "CommonCommand.CryptoSetup",
                "command_group": "CommandGroup.Настройки",
            },
        ],
        "subsystems_order": ["Subsystem.Admin.Subsystem.Settings"],
        "groups_order": ["NavigationPanelOrdinary", "CommandGroup.Настройки"],
    }


def test_parse_subsystem_command_interface_strips_numeric_prefix_from_subsystems_order() -> None:
    command_xml = """\
<?xml version='1.0' encoding='utf-8'?>
<CommandInterface xmlns='http://v8.1c.ru/8.3/xcf/extrnprops'>
  <SubsystemsOrder>
    <Subsystem>2 Закупівлі</Subsystem>
    <Subsystem>2 Продажі</Subsystem>
    <Subsystem>2 Склад</Subsystem>
  </SubsystemsOrder>
</CommandInterface>
""".encode("utf-8")

    assert parse_subsystem_command_interface(command_xml) == {
        "subsystems_order": ["Закупівлі", "Продажі", "Склад"],
    }


def test_parse_subsystem_command_interface_deduplicates_subsystems_order() -> None:
    command_xml = """\
<?xml version='1.0' encoding='utf-8'?>
<CommandInterface xmlns='http://v8.1c.ru/8.3/xcf/extrnprops'>
  <SubsystemsOrder>
    <Subsystem>Закупівлі</Subsystem>
    <Subsystem>Закупівлі</Subsystem>
    <Subsystem>Продажі</Subsystem>
    <Subsystem>Склад</Subsystem>
    <Subsystem>Склад</Subsystem>
  </SubsystemsOrder>
</CommandInterface>
""".encode("utf-8")

    assert parse_subsystem_command_interface(command_xml) == {
        "subsystems_order": ["Закупівлі", "Продажі", "Склад"],
    }


def test_import_and_enrich_subsystem_keeps_service_data_inside_subsystem_object(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "import_subsystem_payload.mpdb"))
    ensure_manifest(db, seed_defaults=True)

    source = _DictSource(
        {
            "Catalogs/Products.xml": """<?xml version='1.0' encoding='utf-8'?>
<MetaDataObject xmlns='http://v8.1c.ru/8.3/MDClasses'>
  <Catalog uuid='cat-1'>
    <Properties>
      <Name>Products</Name>
      <Synonym />
    </Properties>
  </Catalog>
</MetaDataObject>
""".encode("utf-8"),
            "Subsystems/Administration.xml": """<?xml version='1.0' encoding='utf-8'?>
<MetaDataObject xmlns='http://v8.1c.ru/8.3/MDClasses' xmlns:v8='http://v8.1c.ru/8.1/data/core' xmlns:xr='http://v8.1c.ru/8.3/xcf/readable' xmlns:xsi='http://www.w3.org/2001/XMLSchema-instance'>
  <Subsystem uuid='sub-1'>
    <Properties>
      <Name>Administration</Name>
      <Synonym>
        <v8:item><v8:lang>uk</v8:lang><v8:content>Адміністрування</v8:content></v8:item>
      </Synonym>
      <IncludeHelpInContents>true</IncludeHelpInContents>
      <IncludeInCommandInterface>false</IncludeInCommandInterface>
      <UseOneCommand>true</UseOneCommand>
      <Explanation>
        <v8:item><v8:lang>uk</v8:lang><v8:content>Пояснення підсистеми</v8:content></v8:item>
      </Explanation>
      <Content>
        <xr:Item xsi:type='xr:MDObjectRef'>Catalog.Products</xr:Item>
      </Content>
    </Properties>
  </Subsystem>
</MetaDataObject>
""".encode("utf-8"),
            "Subsystems/Administration/Ext/Help.xml": """<?xml version='1.0' encoding='utf-8'?>
<Help xmlns='http://v8.1c.ru/8.3/xcf/extrnprops'>
  <Page>uk</Page>
  <Page>en</Page>
</Help>
""".encode("utf-8"),
            "Subsystems/Administration/Ext/Help/uk.html": "<h1>Адміністрування</h1>".encode("utf-8"),
            "Subsystems/Administration/Ext/Help/en.html": "<h1>Administration</h1>".encode("utf-8"),
            "Subsystems/Administration/Ext/CommandInterface.xml": """<?xml version='1.0' encoding='utf-8'?>
<CommandInterface xmlns='http://v8.1c.ru/8.3/xcf/extrnprops' xmlns:xr='http://v8.1c.ru/8.3/xcf/readable'>
  <CommandsVisibility>
    <Command name='Catalog.Products.StandardCommand.OpenList'>
      <Visibility>
        <xr:Common>false</xr:Common>
      </Visibility>
    </Command>
  </CommandsVisibility>
  <CommandsPlacement>
    <Command name='Catalog.Products.StandardCommand.OpenList'>
      <CommandGroup>NavigationPanelOrdinary</CommandGroup>
      <Placement>Auto</Placement>
    </Command>
  </CommandsPlacement>
  <CommandsOrder>
    <Command name='Catalog.Products.StandardCommand.OpenList'>
      <CommandGroup>NavigationPanelOrdinary</CommandGroup>
    </Command>
  </CommandsOrder>
  <GroupsOrder>
    <Group>NavigationPanelOrdinary</Group>
  </GroupsOrder>
</CommandInterface>
""".encode("utf-8"),
        }
    )

    import_manifest_objects(db, source, source.list_files(), store_modules_in_table=False)
    _enrich_objects_with_requisites(db, source)

    objects = list_objects(db)
    catalog = next(obj for obj in objects if obj.type == "catalog" and obj.kind == "object")
    subsystem = next(obj for obj in objects if obj.type == "subsystem" and obj.kind == "object")

    assert subsystem.payload["include_help_in_contents"] is True
    assert subsystem.payload["include_in_command_interface"] is False
    assert subsystem.payload["use_one_command"] is True
    assert subsystem.payload["help_pages"] == ["uk", "en"]
    assert subsystem.payload["help_contents"]["uk"] == "<h1>Адміністрування</h1>"
    assert subsystem.payload["help_contents"]["en"] == "<h1>Administration</h1>"
    assert subsystem.payload["content_refs"] == ["Catalog.Products"]
    assert subsystem.payload["objects"] == [catalog.guid]
    assert subsystem.payload["command_interface"]["commands_visibility"][0]["name"] == (
        "Catalog.Products.StandardCommand.OpenList"
    )
    assert subsystem.payload["command_interface"]["commands_placement"][0]["placement"] == "Auto"
    assert subsystem.payload["command_interface"]["commands_order"][0]["command_group"] == (
        "NavigationPanelOrdinary"
    )
    assert subsystem.payload["command_interface"]["groups_order"] == ["NavigationPanelOrdinary"]


def test_build_import_plan_from_dump_info_repairs_cp1251_mojibake_names() -> None:
    bad_doc_name = "АвансовыйОтчет".encode("cp1251").decode("latin1")
    bad_form_name = "ФормаДокумента".encode("cp1251").decode("latin1")
    source = _DictSource(
        {
            "ConfigDumpInfo.xml": f"""<?xml version='1.0' encoding='utf-8'?>
<ConfigDumpInfo xmlns='http://v8.1c.ru/8.3/xcf/dumpinfo'>
  <ConfigVersions>
    <Metadata name='Document.{bad_doc_name}' id='doc-1'/>
    <Metadata name='Document.{bad_doc_name}.Form.{bad_form_name}' id='form-1'/>
    <Metadata name='Document.{bad_doc_name}.Form.{bad_form_name}.Form' id='form-1.0'/>
  </ConfigVersions>
</ConfigDumpInfo>
""".encode("utf-8"),
            "Documents/АвансовыйОтчет.xml": b"",
            "Documents/АвансовыйОтчет/Forms/ФормаДокумента.xml": b"",
            "Documents/АвансовыйОтчет/Forms/ФормаДокумента/Ext/Form.xml": b"",
        }
    )

    plan = build_import_plan_from_dump_info(source, source.list_files())
    rels = {spec.rel_xml for spec in plan}
    assert "Documents/АвансовыйОтчет.xml" in rels

    profiles = build_import_profiles_from_dump_info(source, source.list_files(), plan)
    profile = profiles["Documents/АвансовыйОтчет.xml"]
    assert profile.forms == ["Documents/АвансовыйОтчет/Forms/ФормаДокумента.xml"]
    assert profile.form_specs[0].ext_form_rel == "Documents/АвансовыйОтчет/Forms/ФормаДокумента/Ext/Form.xml"


def test_onec_xml_parser_includes_constants_and_reports_progress() -> None:
    source = _DictSource(
        {
            "Constants/UseVat.xml": """<?xml version='1.0' encoding='utf-8'?>
<MetaDataObject xmlns='http://v8.1c.ru/8.3/MDClasses'>
  <Constant uuid='const-1'>
    <Properties>
      <Name>UseVat</Name>
      <Synonym xmlns:v8='http://v8.1c.ru/8.1/data/core'>
        <v8:item><v8:lang>uk</v8:lang><v8:content>Використовувати ПДВ</v8:content></v8:item>
      </Synonym>
    </Properties>
  </Constant>
</MetaDataObject>
""".encode("utf-8"),
        }
    )
    progress_events: list[tuple[int, int, str]] = []

    objects = OneCXmlParser().parse_all(
        source,
        progress=lambda current, total, message: progress_events.append((current, total, message)),
    )

    assert len(objects) == 1
    assert objects[0].obj_type == "constants"
    assert objects[0].name == "UseVat"
    assert progress_events[-1][0] == 1
    assert progress_events[-1][1] == 1


def test_build_onec_form_model_from_xml_for_list_form() -> None:
    xml = """\
<Form xmlns="http://v8.1c.ru/8.3/xcf/logform">
  <ChildItems>
    <Table name="List" id="1">
      <Representation>List</Representation>
      <DataPath>Список</DataPath>
      <ChildItems>
        <LabelField name="Description" id="2">
          <DataPath>Список.Description</DataPath>
        </LabelField>
        <CheckBoxField name="IsActive" id="3">
          <DataPath>Список.IsActive</DataPath>
        </CheckBoxField>
      </ChildItems>
    </Table>
  </ChildItems>
</Form>
"""
    model, form_kind = build_onec_form_model_from_xml(
        form_name="ФормаСписка",
        form_title="Форма списка",
        owner_title="Catalog",
        obj_type="catalog",
        ext_form_xml=xml.encode("utf-8"),
    )
    assert form_kind == "list_form"
    root = model["root"]
    table = next(node for node in root["children"] if node["type"] == "Table")
    assert table["binding"] == "items"
    assert table["props"]["columns"][0]["binding"] == "Description"
    assert table["props"]["columns"][1]["binding"] == "IsActive"


def test_build_onec_form_model_from_xml_imports_window_opening_mode() -> None:
    xml = """\
<Form xmlns="http://v8.1c.ru/8.3/xcf/logform">
  <WindowOpeningMode>LockOwnerWindow</WindowOpeningMode>
  <ChildItems>
    <InputField name="Value" id="1"><DataPath>Object.Value</DataPath></InputField>
  </ChildItems>
</Form>
"""
    model, _form_kind = build_onec_form_model_from_xml(
        form_name="ProcessorForm",
        form_title="Processor form",
        owner_title="Processor",
        obj_type="data_processor",
        ext_form_xml=xml.encode("utf-8"),
    )

    props = model["root"]["props"]
    assert props["open_mode"] == "window"
    assert props["window_lock_mode"] == "owner"
    assert props["source_window_opening_mode"] == "LockOwnerWindow"


def test_build_onec_form_model_from_xml_imports_whole_interface_lock() -> None:
    xml = """\
<Form xmlns="http://v8.1c.ru/8.3/xcf/logform">
  <WindowOpeningMode>LockWholeInterface</WindowOpeningMode>
  <ChildItems />
</Form>
"""
    model, _form_kind = build_onec_form_model_from_xml(
        form_name="ChoiceForm",
        form_title="Choice form",
        owner_title="Common form",
        obj_type="common_form",
        ext_form_xml=xml.encode("utf-8"),
    )

    assert model["root"]["props"]["open_mode"] == "window"
    assert model["root"]["props"]["window_lock_mode"] == "interface"


def test_build_onec_form_model_from_xml_for_object_form() -> None:
    xml = """\
<Form xmlns="http://v8.1c.ru/8.3/xcf/logform" xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <ChildItems>
    <UsualGroup name="MainGroup" id="10">
      <Title>
        <v8:item><v8:lang>en</v8:lang><v8:content>Main</v8:content></v8:item>
      </Title>
      <Group>Horizontal</Group>
      <ChildItems>
        <InputField name="StartDate" id="11">
          <DataPath>Объект.StartDate</DataPath>
        </InputField>
        <InputField name="Comment" id="12">
          <DataPath>Объект.Comment</DataPath>
          <MultiLine>true</MultiLine>
        </InputField>
      </ChildItems>
    </UsualGroup>
  </ChildItems>
</Form>
"""
    model, form_kind = build_onec_form_model_from_xml(
        form_name="ItemForm",
        form_title="Item form",
        owner_title="Catalog",
        obj_type="catalog",
        ext_form_xml=xml.encode("utf-8"),
    )
    assert form_kind == "object_form"
    root = model["root"]
    group = next(node for node in root["children"] if node["type"] == "Container" and node["id"] == "group_10")
    assert group["props"]["layout"] == "horizontal"
    child_types = [node["type"] for node in group["children"]]
    assert "DateBox" in child_types
    assert "TextArea" in child_types


def test_build_onec_form_model_from_xml_keeps_group_representation_and_field_metrics() -> None:
    xml = """\
<Form xmlns="http://v8.1c.ru/8.3/xcf/logform" xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <ChildItems>
    <UsualGroup name="HeaderGroup" id="10">
      <Title>
        <v8:item><v8:lang>en</v8:lang><v8:content>Header</v8:content></v8:item>
      </Title>
      <Group>Horizontal</Group>
      <Representation>None</Representation>
      <ShowTitle>false</ShowTitle>
      <ChildItems>
        <InputField name="Comment" id="11">
          <DataPath>Объект.Comment</DataPath>
          <Width>30</Width>
          <TitleLocation>Top</TitleLocation>
        </InputField>
      </ChildItems>
    </UsualGroup>
  </ChildItems>
</Form>
"""
    model, _form_kind = build_onec_form_model_from_xml(
        form_name="ItemForm",
        form_title="Item form",
        owner_title="Catalog",
        obj_type="catalog",
        ext_form_xml=xml.encode("utf-8"),
    )
    group = next(node for node in model["root"]["children"] if node["id"] == "group_10")
    assert group["props"]["representation"] == "None"
    assert group["props"]["show_title"] is False
    field = group["children"][0]
    assert field["props"]["width_chars"] == 30
    assert field["props"]["title_location"] == "Top"


def test_build_onec_form_model_from_xml_collects_generic_boolean_props() -> None:
    xml = """\
<Form xmlns="http://v8.1c.ru/8.3/xcf/logform">
  <ChildItems>
    <UsualGroup name="HeaderGroup" id="10">
      <ShowTitle>no</ShowTitle>
      <Expanded>yes</Expanded>
      <SomeMode>42</SomeMode>
      <ChildItems>
        <InputField name="Comment" id="11">
          <DataPath>Объект.Comment</DataPath>
          <MultiLine>yes</MultiLine>
          <ReadOnly>0</ReadOnly>
          <Visible>false</Visible>
          <Width>30</Width>
          <TitleLocation>Top</TitleLocation>
        </InputField>
        <Button name="Extra" id="12">
          <CommandName>Form.Command.Extra</CommandName>
          <SeparatorAfter>1</SeparatorAfter>
        </Button>
      </ChildItems>
    </UsualGroup>
  </ChildItems>
</Form>
"""
    model, _form_kind = build_onec_form_model_from_xml(
        form_name="ItemForm",
        form_title="Item form",
        owner_title="Catalog",
        obj_type="catalog",
        ext_form_xml=xml.encode("utf-8"),
    )
    group = next(node for node in model["root"]["children"] if node["id"] == "group_10")
    assert group["props"]["show_title"] is False
    assert group["props"]["expanded"] is True
    assert group["props"]["some_mode"] == 42
    field = next(node for node in group["children"] if node["name"] == "Comment")
    assert field["type"] == "TextArea"
    assert field["props"]["multi_line"] is True
    assert field["props"]["read_only"] is False
    assert field["props"]["visible"] is False
    button = next(node for node in group["children"] if node["type"] == "Button")
    assert button["props"]["separator_after"] is True


def test_build_onec_form_model_from_xml_parses_commandbars_and_document_fields() -> None:
    xml = """\
<Form xmlns="http://v8.1c.ru/8.3/xcf/logform" xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <AutoCommandBar name="MainBar" id="1">
    <ChildItems>
      <Button name="RunButton" id="2">
        <CommandName>Form.Command.Run</CommandName>
      </Button>
    </ChildItems>
  </AutoCommandBar>
  <Commands>
    <Command name="Run" id="1">
      <Title>
        <v8:item><v8:lang>en</v8:lang><v8:content>Run report</v8:content></v8:item>
      </Title>
    </Command>
  </Commands>
  <ChildItems>
    <SpreadSheetDocumentField name="Result" id="3">
      <DataPath>Result</DataPath>
    </SpreadSheetDocumentField>
  </ChildItems>
</Form>
"""
    model, form_kind = build_onec_form_model_from_xml(
        form_name="ReportForm",
        form_title="Report form",
        owner_title="Report",
        obj_type="report",
        ext_form_xml=xml.encode("utf-8"),
    )
    assert form_kind == "object_form"
    root_children = model["root"]["children"]
    command_bar = next(node for node in root_children if node["type"] == "Container" and node["props"].get("layout") == "horizontal")
    command_titles = [node["title"] for node in command_bar["children"] if node["type"] == "Button"]
    assert "Run report" in command_titles
    doc_field = next(node for node in root_children if node["name"] == "Result")
    assert doc_field["type"] == "TextArea"
    assert doc_field["props"]["read_only"] is True


def test_build_onec_form_model_from_serialized_config_stream() -> None:
    control_uuid = "02023637-7868-4a5f-8576-835a76e0c9ba"

    def control(marker, control_id, mode, name, *children):
        return [
            str(marker),
            [str(control_id), control_uuid],
            "0",
            "0",
            "1",
            ["0"],
            str(mode),
            name,
            ["1", "1", ["uk", name]],
            *children,
        ]

    fill_button = control("25", "6", "0", "Fill")
    command_bar = control("19", "5", "9", "LinesCommandBar", fill_button)
    amount_column = control("32", "4", "2", "Amount")
    amount_column.extend(["0"] * (13 - len(amount_column)))
    amount_column[12] = ["2", ["1"], ["0", "amount-uuid"]]
    table = control("48", "3", "0", "Lines", command_bar, amount_column)
    page = control("19", "2", "4", "MainPage", table)
    pages = control("19", "1", "3", "Pages", page)
    commands = [
        "0",
        "1",
        ["7", ["1", "command-uuid"], "Fill", ["1", "1", ["uk", "Заповнити"]]],
    ]
    payload = ["3", ["38", pages], "", ["0"], ["0"], commands]

    def serialize(value):
        if isinstance(value, list):
            return "{" + ",".join(serialize(item) for item in value) + "}"
        text = str(value).replace('"', '""')
        return f'"{text}"'

    serialized = serialize(payload)
    serialized = serialized[:-1] + ",{#base64:QUJD\nRA==}}"
    model, form_kind = build_onec_form_model_from_xml(
        form_name="DocumentForm",
        form_title="Document form",
        owner_title="Document",
        obj_type="document",
        ext_form_xml=serialized.encode("utf-8"),
    )

    assert form_kind == "object_form"
    pages_node = next(node for node in model["root"]["children"] if node["type"] == "Tabs")
    page_node = next(node for node in pages_node["children"] if node["name"] == "MainPage")
    table_wrap = next(node for node in page_node["children"] if node["name"] == "Lines")
    command_bar_node = next(node for node in table_wrap["children"] if node["props"].get("layout") == "horizontal")
    table_node = next(node for node in table_wrap["children"] if node["type"] == "Table")
    assert command_bar_node["children"][0]["title"] == "Заповнити"
    assert table_node["binding"] == "Lines"
    assert table_node["props"]["columns"] == [
        {"name": "Amount", "designer_name": "Amount", "title": "Amount", "binding": "Amount"}
    ]


def test_build_onec_form_model_from_serialized_keeps_group_layout_and_chrome() -> None:
    control_uuid = "02023637-7868-4a5f-8576-835a76e0c9ba"

    def control(marker, control_id, mode, name, *children):
        return [
            str(marker),
            [str(control_id), control_uuid],
            "0",
            "0",
            "1",
            ["0"],
            str(mode),
            name,
            ["1", "1", ["uk", name]],
            *children,
        ]

    field = control("32", "2", "0", "Amount")
    group = control("19", "1", "5", "Header", field)
    group.extend(["0"] * (22 - len(group)))
    group[21] = ["17", "1", "0", "3", "1"]
    payload = ["3", ["38", group], "", ["0"], ["0"], ["0"]]

    def serialize(value):
        if isinstance(value, list):
            return "{" + ",".join(serialize(item) for item in value) + "}"
        return f'"{str(value).replace(chr(34), chr(34) * 2)}"'

    model, _form_kind = build_onec_form_model_from_xml(
        form_name="DocumentForm",
        form_title="Document form",
        owner_title="Document",
        obj_type="document",
        ext_form_xml=serialize(payload).encode("utf-8"),
    )

    group_node = next(node for node in model["root"]["children"] if node["name"] == "Header")
    assert group_node["props"]["layout"] == "horizontal"
    assert group_node["props"]["representation"] == "NormalSeparation"
    assert group_node["props"]["show_title"] is True
    assert [node["name"] for node in group_node["children"]] == ["Amount"]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"MOXCEL\x00\x08\x00\x01", "Unsupported legacy 1C MOXCEL form body"),
        (b"\x7f\x00\x02\x00binary", "Unsupported binary 1C form body"),
    ],
)
def test_build_onec_form_model_reports_unsupported_binary_body(body: bytes, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build_onec_form_model_from_xml(
            form_name="LegacyForm",
            form_title="Legacy form",
            owner_title="Report",
            obj_type="report",
            ext_form_xml=body,
        )


def test_enrich_objects_with_requisites_uses_bulk_manifest_rebuild(monkeypatch, tmp_path) -> None:
    db = Mpdb(str(tmp_path / "enrich_batch.mpdb"))
    manifest_objects = [
        ManifestObject(
            guid="guid-products",
            type="catalog",
            name="Products",
            title="Products",
            kind="object",
            parent_guid="catalog-group",
            payload={"imported": {"src_uid": "uuid-products"}},
        )
    ]
    parsed_objects = [
        OneCMetaObject(
            obj_type="catalog",
            name="Products",
            synonyms={},
            uuid="uuid-products",
        )
    ]
    bulk_calls: list[dict[str, dict]] = []

    monkeypatch.setattr("src.tools.onec_import.manifest_io.list_objects", lambda _db: manifest_objects)
    monkeypatch.setattr("src.tools.onec_import.OneCXmlParser.parse_all", lambda self, source: parsed_objects)
    monkeypatch.setattr(
        "src.tools.onec_import.enrich_manifest_payload",
        lambda payload, parsed: {"imported": {"src_uid": parsed.uuid}, "title": parsed.name},
    )

    def _bulk_update(_db, payloads_by_guid):
        bulk_calls.append(dict(payloads_by_guid))
        return len(payloads_by_guid)

    monkeypatch.setattr("src.tools.onec_import.manifest_io.bulk_update_payloads", _bulk_update)

    def _update_payload_should_not_run(*_args, **_kwargs):
        raise AssertionError("per-object update_payload path must not be used")

    monkeypatch.setattr("src.tools.onec_import.manifest_io.update_payload", _update_payload_should_not_run)

    updated = _enrich_objects_with_requisites(db, _DictSource({}))

    assert updated == 1
    assert bulk_calls == [
        {
            "guid-products": {
                "imported": {"src_uid": "uuid-products"},
                "title": "Products",
            }
        }
    ]


def test_build_onec_form_model_from_xml_parses_pages_and_nested_button_groups() -> None:
    xml = """\
<Form xmlns="http://v8.1c.ru/8.3/xcf/logform" xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <ChildItems>
    <Pages name="Tabs" id="1">
      <ChildItems>
        <Page name="MainPage" id="2">
          <Title>
            <v8:item><v8:lang>en</v8:lang><v8:content>Main</v8:content></v8:item>
          </Title>
          <ChildItems>
            <ButtonGroup name="ActionGroup" id="3">
              <ChildItems>
                <Button name="Select" id="4">
                  <CommandName>Form.StandardCommand.Choose</CommandName>
                </Button>
              </ChildItems>
            </ButtonGroup>
            <LabelDecoration name="InfoText" id="5">
              <Title>
                <v8:item><v8:lang>en</v8:lang><v8:content>Helpful text</v8:content></v8:item>
              </Title>
            </LabelDecoration>
            <LabelDecoration name="LayoutSpacer" id="6">
              <Width>3</Width>
              <HorizontalStretch>false</HorizontalStretch>
            </LabelDecoration>
          </ChildItems>
        </Page>
      </ChildItems>
    </Pages>
  </ChildItems>
</Form>
"""
    model, _form_kind = build_onec_form_model_from_xml(
        form_name="WizardForm",
        form_title="Wizard",
        owner_title="Wizard owner",
        obj_type="data_processor",
        ext_form_xml=xml.encode("utf-8"),
    )
    root_children = model["root"]["children"]
    pages = next(node for node in root_children if node["name"] == "Tabs")
    assert pages["type"] == "Tabs"
    page = next(node for node in pages["children"] if node["name"] == "MainPage")
    assert page["type"] == "Container"
    action_group = next(node for node in page["children"] if node["name"] == "ActionGroup")
    button = next(node for node in action_group["children"] if node["type"] == "Button")
    assert button["title"] == "Choose"
    info = next(node for node in page["children"] if node["title"] == "Helpful text")
    assert info["type"] == "Label"
    assert info["props"]["is_decoration"] is True
    assert info["props"]["layout_spacer"] is False
    spacer = next(node for node in page["children"] if node["name"] == "LayoutSpacer")
    assert spacer["title"] == ""
    assert spacer["props"]["is_decoration"] is True
    assert spacer["props"]["decoration_kind"] == "label"
    assert spacer["props"]["layout_spacer"] is True
    assert spacer["props"]["width_chars"] == 3


def test_build_onec_form_model_keeps_document_page_tables_as_object_form() -> None:
    xml = """\
<Form xmlns="http://v8.1c.ru/8.3/xcf/logform" xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <ChildItems>
    <Pages name="Tabs" id="1">
      <PagesRepresentation>TabsOnTop</PagesRepresentation>
      <ChildItems>
        <Page name="MainPage" id="2">
          <Title>
            <v8:item><v8:lang>en</v8:lang><v8:content>Main</v8:content></v8:item>
          </Title>
          <ChildItems>
            <Table name="Lines" id="3">
              <Representation>List</Representation>
              <DataPath>Объект.Lines</DataPath>
              <AutoCommandBar name="LinesBar" id="4">
                <ChildItems>
                  <Button name="Fill" id="5">
                    <CommandName>Form.Command.Fill</CommandName>
                  </Button>
                </ChildItems>
              </AutoCommandBar>
              <ChildItems>
                <InputField name="Amount" id="6">
                  <DataPath>Объект.Lines.Amount</DataPath>
                </InputField>
              </ChildItems>
            </Table>
          </ChildItems>
        </Page>
      </ChildItems>
    </Pages>
  </ChildItems>
  <Attributes>
    <Attribute name="Объект" id="1">
      <Type><v8:Type>cfg:DocumentObject.AdvanceReport</v8:Type></Type>
      <MainAttribute>true</MainAttribute>
    </Attribute>
  </Attributes>
</Form>
"""
    model, form_kind = build_onec_form_model_from_xml(
        form_name="DocumentForm",
        form_title="Document form",
        owner_title="Advance report",
        obj_type="document",
        ext_form_xml=xml.encode("utf-8"),
    )
    assert form_kind == "object_form"
    pages = next(node for node in model["root"]["children"] if node["type"] == "Tabs")
    page = next(node for node in pages["children"] if node["name"] == "MainPage")
    table_wrap = next(node for node in page["children"] if node["name"] == "Lines")
    assert table_wrap["type"] == "Container"
    toolbar = next(node for node in table_wrap["children"] if node["type"] == "Container")
    assert any(child["type"] == "Button" for child in toolbar["children"])
    table = next(node for node in table_wrap["children"] if node["type"] == "Table")
    assert table["binding"] == "Lines"


class _DictSource:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    def list_files(self) -> list[str]:
        return sorted(self.files)

    def read_bytes(self, rel_path: str) -> bytes:
        return self.files[rel_path]


def test_import_manifest_objects_batches_manifest_and_modules(tmp_path, monkeypatch) -> None:
    db = Mpdb(str(tmp_path / "import_batch.mpdb"))
    ensure_manifest(db, seed_defaults=True)

    files = {
        "Catalogs/Products.xml": b"<Meta><Name>Products</Name><Synonym>Products</Synonym><UUID>cat-1</UUID></Meta>",
        "Catalogs/Products/Ext/ObjectModule.bsl": b"Procedure Test() EndProcedure",
        "Catalogs/Products/Commands/Print.xml": b"<Meta><Name>Print</Name><Synonym>Print</Synonym></Meta>",
        "Catalogs/Products/Templates/PriceLayout.xml": b"<Meta><Name>PriceLayout</Name><Synonym>Price layout</Synonym></Meta>",
    }
    source = _DictSource(files)
    progress_events: list[tuple[int, int, str]] = []

    def _legacy_add_object(*args, **kwargs):
        raise AssertionError("legacy manifest_io.add_object path should not be used")

    def _legacy_upsert_module(*args, **kwargs):
        raise AssertionError("legacy upsert_module path should not be used")

    monkeypatch.setattr("src.configurator.persistence.manifest_io.add_object", _legacy_add_object)
    monkeypatch.setattr("src.configurator.persistence.modules_dao.upsert_module", _legacy_upsert_module)

    guid_by_xml = import_manifest_objects(
        db,
        source,
        source.list_files(),
        store_modules_in_table=True,
        progress=lambda current, total, message: progress_events.append((current, total, message)),
    )

    assert "Catalogs/Products.xml" in guid_by_xml
    assert progress_events
    assert progress_events[-1][0] == progress_events[-1][1]

    objects = list_objects(db)
    by_type = {}
    for obj in objects:
        by_type.setdefault(obj.type, []).append(obj)

    assert any(obj.name == "Products" for obj in by_type["catalog"])
    assert any(obj.type == "command" and obj.name == "Print" for obj in objects)


def test_import_manifest_objects_merges_base_plan_with_dump_info(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "import_merge_dumpinfo.mpdb"))
    ensure_manifest(db, seed_defaults=True)

    source = _DictSource(
        {
            "ConfigDumpInfo.xml": b"""<?xml version='1.0' encoding='utf-8'?>
<ConfigDumpInfo xmlns='http://v8.1c.ru/8.3/xcf/dumpinfo'>
  <ConfigVersions>
    <Metadata name='Catalog.Products' id='cat-1'/>
  </ConfigVersions>
</ConfigDumpInfo>
""",
            "Catalogs/Products.xml": b"<Meta><Name>Products</Name><Synonym>Products</Synonym><UUID>cat-1</UUID></Meta>",
            "InformationRegisters/Stock.xml": b"<Meta><Name>Stock</Name><Synonym>Stock</Synonym><UUID>reg-1</UUID></Meta>",
        }
    )

    import_manifest_objects(db, source, source.list_files(), store_modules_in_table=False)

    objects = list_objects(db, hydrate_payload=False)
    got = {(obj.type, obj.name) for obj in objects if obj.kind == 'object'}

    assert ("catalog", "Products") in got
    assert ("register_info", "Stock") in got


def test_import_manifest_objects_sets_module_asset_key_for_common_modules(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "import_common_module.mpdb"))
    ensure_manifest(db, seed_defaults=True)

    files = {
        "CommonModules/АвтономнаяРабота.xml": (
            b"<Meta><Name>\xd0\x90\xd0\xb2\xd1\x82\xd0\xbe\xd0\xbd\xd0\xbe\xd0\xbc\xd0\xbd\xd0\xb0\xd1\x8f\xd0\xa0\xd0\xb0\xd0\xb1\xd0\xbe\xd1\x82\xd0\xb0</Name>"
            b"<Synonym>\xd0\x90\xd0\xb2\xd1\x82\xd0\xbe\xd0\xbd\xd0\xbe\xd0\xbc\xd0\xbd\xd0\xb0\xd1\x8f \xd1\x80\xd0\xb0\xd0\xb1\xd0\xbe\xd1\x82\xd0\xb0</Synonym></Meta>"
        ),
        "CommonModules/АвтономнаяРабота/Ext/Module.bsl": b"Procedure Test() EndProcedure",
    }
    source = _DictSource(files)

    import_manifest_objects(
        db,
        source,
        source.list_files(),
        store_modules_in_table=True,
    )

    common_module = next(
        obj
        for obj in list_objects(db)
        if obj.type == "common_module"
        and obj.kind == "object"
        and str((obj.payload.get("imported") or {}).get("origin") or "") == "CommonModules/АвтономнаяРабота.xml"
    )
    module_payload = common_module.payload.get("module") or {}
    assert str(module_payload.get("asset_key") or "").startswith("module://")

    module_rows = db.table(MODULES_TABLE).select(where={"owner_guid": common_module.guid}) or []
    assert len(module_rows) == 1
    assert get_module_text(db, module_guid=str(module_rows[0]["module_guid"])) == "Процедура Test() КінецьПроцедури"


def test_import_manifest_objects_sets_module_asset_key_for_forms(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "import_form_module.mpdb"))
    ensure_manifest(db, seed_defaults=True)

    files = {
        "Documents/АвансовыйОтчет.xml": (
            b"<Meta><Name>\xd0\x90\xd0\xb2\xd0\xb0\xd0\xbd\xd1\x81\xd0\xbe\xd0\xb2\xd1\x8b\xd0\xb9\xd0\x9e\xd1\x82\xd1\x87\xd0\xb5\xd1\x82</Name>"
            b"<Synonym>\xd0\x90\xd0\xb2\xd0\xb0\xd0\xbd\xd1\x81\xd0\xbe\xd0\xb2\xd1\x8b\xd0\xb9 \xd0\xbe\xd1\x82\xd1\x87\xd0\xb5\xd1\x82</Synonym></Meta>"
        ),
        "Documents/АвансовыйОтчет/Forms/ФормаДокумента.xml": (
            b"<Meta><Name>\xd0\xa4\xd0\xbe\xd1\x80\xd0\xbc\xd0\xb0\xd0\x94\xd0\xbe\xd0\xba\xd1\x83\xd0\xbc\xd0\xb5\xd0\xbd\xd1\x82\xd0\xb0</Name>"
            b"<Synonym>\xd0\xa4\xd0\xbe\xd1\x80\xd0\xbc\xd0\xb0 \xd0\xb4\xd0\xbe\xd0\xba\xd1\x83\xd0\xbc\xd0\xb5\xd0\xbd\xd1\x82\xd0\xb0</Synonym></Meta>"
        ),
        "Documents/АвансовыйОтчет/Forms/ФормаДокумента/Ext/Module.bsl": b"Procedure TestForm() EndProcedure",
    }
    source = _DictSource(files)

    import_manifest_objects(
        db,
        source,
        source.list_files(),
        store_modules_in_table=True,
    )

    form_obj = next(
        obj
        for obj in list_objects(db)
        if obj.type == "form"
        and obj.kind == "object"
        and str((obj.payload.get("imported") or {}).get("origin") or "") == "Documents/АвансовыйОтчет/Forms/ФормаДокумента.xml"
    )
    module_payload = form_obj.payload.get("module") or {}
    assert str(module_payload.get("asset_key") or "").startswith("module://")

    module_rows = db.table(MODULES_TABLE).select(where={"owner_guid": form_obj.guid}) or []
    assert len(module_rows) == 1
    assert get_module_text(db, module_guid=str(module_rows[0]["module_guid"])) == "Процедура TestForm() КінецьПроцедури"


def test_import_manifest_objects_sets_module_asset_key_for_forms_in_ext_form_subdir(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "import_form_module_ext_form.mpdb"))
    ensure_manifest(db, seed_defaults=True)

    files = {
        "Documents/АвансовыйОтчет.xml": (
            b"<Meta><Name>\xd0\x90\xd0\xb2\xd0\xb0\xd0\xbd\xd1\x81\xd0\xbe\xd0\xb2\xd1\x8b\xd0\xb9\xd0\x9e\xd1\x82\xd1\x87\xd0\xb5\xd1\x82</Name>"
            b"<Synonym>\xd0\x90\xd0\xb2\xd0\xb0\xd0\xbd\xd1\x81\xd0\xbe\xd0\xb2\xd1\x8b\xd0\xb9 \xd0\xbe\xd1\x82\xd1\x87\xd0\xb5\xd1\x82</Synonym></Meta>"
        ),
        "Documents/АвансовыйОтчет/Forms/ФормаДокумента.xml": (
            b"<Meta><Name>\xd0\xa4\xd0\xbe\xd1\x80\xd0\xbc\xd0\xb0\xd0\x94\xd0\xbe\xd0\xba\xd1\x83\xd0\xbc\xd0\xb5\xd0\xbd\xd1\x82\xd0\xb0</Name>"
            b"<Synonym>\xd0\xa4\xd0\xbe\xd1\x80\xd0\xbc\xd0\xb0 \xd0\xb4\xd0\xbe\xd0\xba\xd1\x83\xd0\xbc\xd0\xb5\xd0\xbd\xd1\x82\xd0\xb0</Synonym></Meta>"
        ),
        "Documents/АвансовыйОтчет/Forms/ФормаДокумента/Ext/Form/Module.bsl": b"Procedure TestFormExt() EndProcedure",
    }
    source = _DictSource(files)

    import_manifest_objects(
        db,
        source,
        source.list_files(),
        store_modules_in_table=True,
    )

    form_obj = next(
        obj
        for obj in list_objects(db)
        if obj.type == "form"
        and obj.kind == "object"
        and str((obj.payload.get("imported") or {}).get("origin") or "") == "Documents/АвансовыйОтчет/Forms/ФормаДокумента.xml"
    )
    module_payload = form_obj.payload.get("module") or {}
    assert str(module_payload.get("asset_key") or "").startswith("module://")

    module_rows = db.table(MODULES_TABLE).select(where={"owner_guid": form_obj.guid}) or []
    assert len(module_rows) == 1
    assert get_module_text(db, module_guid=str(module_rows[0]["module_guid"])) == "Процедура TestFormExt() КінецьПроцедури"


def test_import_manifest_objects_updates_pending_form_payload_without_manifest_rebuild(monkeypatch, tmp_path) -> None:
    db = Mpdb(str(tmp_path / "import_form_module_no_manifest_rebuild.mpdb"))
    ensure_manifest(db, seed_defaults=True)

    files = {
        "Documents/АвансовыйОтчет.xml": (
            b"<Meta><Name>\xd0\x90\xd0\xb2\xd0\xb0\xd0\xbd\xd1\x81\xd0\xbe\xd0\xb2\xd1\x8b\xd0\xb9\xd0\x9e\xd1\x82\xd1\x87\xd0\xb5\xd1\x82</Name>"
            b"<Synonym>\xd0\x90\xd0\xb2\xd0\xb0\xd0\xbd\xd1\x81\xd0\xbe\xd0\xb2\xd1\x8b\xd0\xb9 \xd0\xbe\xd1\x82\xd1\x87\xd0\xb5\xd1\x82</Synonym></Meta>"
        ),
        "Documents/АвансовыйОтчет/Forms/ФормаДокумента.xml": (
            b"<Meta><Name>\xd0\xa4\xd0\xbe\xd1\x80\xd0\xbc\xd0\xb0\xd0\x94\xd0\xbe\xd0\xba\xd1\x83\xd0\xbc\xd0\xb5\xd0\xbd\xd1\x82\xd0\xb0</Name>"
            b"<Synonym>\xd0\xa4\xd0\xbe\xd1\x80\xd0\xbc\xd0\xb0 \xd0\xb4\xd0\xbe\xd0\xba\xd1\x83\xd0\xbc\xd0\xb5\xd0\xbd\xd1\x82\xd0\xb0</Synonym></Meta>"
        ),
        "Documents/АвансовыйОтчет/Forms/ФормаДокумента/Ext/Form/Module.bsl": b"Procedure TestFormExt() EndProcedure",
    }
    source = _DictSource(files)

    def _bulk_update_should_not_run(*_args, **_kwargs):
        raise AssertionError("bulk_update_payloads should not rebuild manifest for pending form payload updates")

    monkeypatch.setattr("src.infra.onec.importer.manifest_io.bulk_update_payloads", _bulk_update_should_not_run)

    import_manifest_objects(
        db,
        source,
        source.list_files(),
        store_modules_in_table=True,
    )

    form_obj = next(
        obj
        for obj in list_objects(db)
        if obj.type == "form"
        and obj.kind == "object"
        and str((obj.payload.get("imported") or {}).get("origin") or "") == "Documents/АвансовыйОтчет/Forms/ФормаДокумента.xml"
    )
    assert str(((form_obj.payload.get("module") or {}).get("asset_key")) or "").startswith("module://")


def test_import_manifest_objects_sets_module_asset_key_for_common_forms_in_ext_form_subdir(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "import_common_form_module_ext_form.mpdb"))
    ensure_manifest(db, seed_defaults=True)

    files = {
        "CommonForms/АвтономнаяРабота.xml": (
            b"<Meta><Name>\xd0\x90\xd0\xb2\xd1\x82\xd0\xbe\xd0\xbd\xd0\xbe\xd0\xbc\xd0\xbd\xd0\xb0\xd1\x8f\xd0\xa0\xd0\xb0\xd0\xb1\xd0\xbe\xd1\x82\xd0\xb0</Name>"
            b"<Synonym>\xd0\x90\xd0\xb2\xd1\x82\xd0\xbe\xd0\xbd\xd0\xbe\xd0\xbc\xd0\xbd\xd0\xb0\xd1\x8f \xd1\x80\xd0\xb0\xd0\xb1\xd0\xbe\xd1\x82\xd0\xb0</Synonym></Meta>"
        ),
        "CommonForms/АвтономнаяРабота/Ext/Form/Module.bsl": b"Procedure CommonFormModule() EndProcedure",
    }
    source = _DictSource(files)

    import_manifest_objects(
        db,
        source,
        source.list_files(),
        store_modules_in_table=True,
    )

    common_form = next(
        obj
        for obj in list_objects(db)
        if obj.type == "common_form"
        and obj.kind == "object"
        and str((obj.payload.get("imported") or {}).get("origin") or "") == "CommonForms/АвтономнаяРабота.xml"
    )
    module_payload = common_form.payload.get("module") or {}
    assert str(module_payload.get("asset_key") or "").startswith("module://")

    module_rows = db.table(MODULES_TABLE).select(where={"owner_guid": common_form.guid}) or []
    assert len(module_rows) == 1
    assert get_module_text(db, module_guid=str(module_rows[0]["module_guid"])) == "Процедура CommonFormModule() КінецьПроцедури"


def test_import_manifest_objects_seeds_default_form_modules_for_generated_forms(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "import_default_form_modules.mpdb"))
    ensure_manifest(db, seed_defaults=True)

    object_module_text = "Процедура ОбработкаЗаполнения(ДанныеЗаполнения, СтандартнаяОбработка)\nКонецПроцедуры"
    form_module_text = "#Область ПрограммныйИнтерфейс\nПроцедура ПоказатьПериод(Форма)\nКонецПроцедуры"
    files = {
        "Documents/АвансовыйОтчет.xml": (
            b"<Meta><Name>\xd0\x90\xd0\xb2\xd0\xb0\xd0\xbd\xd1\x81\xd0\xbe\xd0\xb2\xd1\x8b\xd0\xb9\xd0\x9e\xd1\x82\xd1\x87\xd0\xb5\xd1\x82</Name>"
            b"<Synonym>\xd0\x90\xd0\xb2\xd0\xb0\xd0\xbd\xd1\x81\xd0\xbe\xd0\xb2\xd1\x8b\xd0\xb9 \xd0\xbe\xd1\x82\xd1\x87\xd0\xb5\xd1\x82</Synonym></Meta>"
        ),
        "Documents/АвансовыйОтчет/Ext/ObjectModule.bsl": object_module_text.encode("utf-8"),
        "Documents/АвансовыйОтчет/Ext/Form/Module.bsl": form_module_text.encode("utf-8"),
    }
    source = _DictSource(files)

    import_manifest_objects(
        db,
        source,
        source.list_files(),
        store_modules_in_table=True,
    )

    owner = next(
        obj
        for obj in list_objects(db)
        if obj.type == "document"
        and obj.kind == "object"
        and str((obj.payload.get("imported") or {}).get("origin") or "") == "Documents/АвансовыйОтчет.xml"
    )
    forms = {
        str((obj.payload.get("subtype") or "")).strip().lower(): obj
        for obj in list_objects(db)
        if obj.type == "form"
        and obj.kind == "object"
        and str(obj.payload.get("owner_guid") or "") == owner.guid
    }
    object_module_text_uk = normalize_module_text(object_module_text, language="uk").text
    form_module_text_uk = normalize_module_text(form_module_text, language="uk").text
    assert forms["list_form"].payload.get("form_module") == object_module_text_uk
    assert forms["object_form"].payload.get("form_module") == form_module_text_uk

    module_rows = list_modules_by_owner(db, owner_guid=owner.guid)
    by_kind = {str(row.get("module_kind") or ""): row for row in module_rows}
    assert get_module_text(db, module_guid=str(by_kind["ObjectModule"]["module_guid"])) == object_module_text_uk
    assert get_module_text(db, module_guid=str(by_kind["FormModule"]["module_guid"])) == form_module_text_uk


def test_import_manifest_objects_imports_configuration_root_modules(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "import_configuration_root_modules.mpdb"))
    ensure_manifest(db, seed_defaults=True)

    files = {
        "Ext/ManagedApplicationModule.bsl": b"Procedure OnStart() EndProcedure",
        "Ext/SessionModule.bsl": b"Procedure OnSession() EndProcedure",
    }
    source = _DictSource(files)

    import_manifest_objects(
        db,
        source,
        source.list_files(),
        store_modules_in_table=True,
    )

    objects = list_objects(db)
    app_module = next(obj for obj in objects if obj.type == "common_module" and obj.name == "AppModule")
    session_module = next(obj for obj in objects if obj.type == "common_module" and obj.name == "SessionModule")

    assert str((app_module.payload.get("module") or {}).get("asset_key") or "").startswith("module://")
    assert str(((app_module.payload.get("imported") or {}).get("origin")) or "") == "Ext/ManagedApplicationModule.bsl"
    assert str((session_module.payload.get("module") or {}).get("asset_key") or "").startswith("module://")
    assert str(((session_module.payload.get("imported") or {}).get("origin")) or "") == "Ext/SessionModule.bsl"

    app_rows = db.table(MODULES_TABLE).select(where={"owner_guid": app_module.guid}) or []
    session_rows = db.table(MODULES_TABLE).select(where={"owner_guid": session_module.guid}) or []
    assert len(app_rows) == 1
    assert len(session_rows) == 1
    assert app_rows[0]["module_kind"] == "ManagedApplicationModule"
    assert session_rows[0]["module_kind"] == "SessionModule"


def test_import_manifest_objects_tracks_layout_body_origin(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "import_layout_body.mpdb"))
    ensure_manifest(db, seed_defaults=True)

    files = {
        "Catalogs/Products.xml": b"<Meta><Name>Products</Name><Synonym>Products</Synonym></Meta>",
        "Catalogs/Products/Templates/PriceLayout.xml": b"<Meta><Name>PriceLayout</Name><Synonym>Price layout</Synonym></Meta>",
        "Catalogs/Products/Templates/PriceLayout/Ext/Template.xml": b"""<?xml version='1.0' encoding='utf-8'?>
<document xmlns='http://v8.1c.ru/8.2/data/spreadsheet' xmlns:v8='http://v8.1c.ru/8.1/data/core'>
  <columns>
    <size>1</size>
    <columnsItem><index>0</index><column><formatIndex>0</formatIndex></column></columnsItem>
  </columns>
  <rowsItem>
    <index>0</index>
    <row>
      <c><c><f>0</f><tl><v8:item><v8:lang>uk</v8:lang><v8:content>Hello</v8:content></v8:item></tl></c></c>
    </row>
  </rowsItem>
  <format><width>100</width></format>
</document>
""",
    }
    source = _DictSource(files)

    import_manifest_objects(
        db,
        source,
        source.list_files(),
        store_modules_in_table=False,
    )

    layout = next(obj for obj in list_objects(db) if obj.type == "layout" and obj.name == "PriceLayout")
    imported = layout.payload.get("imported") or {}
    assert imported["layout_body_origin"] == "Catalogs/Products/Templates/PriceLayout/Ext/Template.xml"
    assert imported["layout_body_mime"] == "application/xml"
    assert layout.payload["layout_kind"] == "spreadsheet_document"
    assert layout.payload["layout_model"]["kind"] == "spreadsheet_document"
    assert layout.payload["layout_model"]["cells"][0]["text"] == "Hello"


def test_import_manifest_objects_uses_dump_info_for_forms(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "import_dump_forms.mpdb"))
    ensure_manifest(db, seed_defaults=True)

    files = {
        "ConfigDumpInfo.xml": b"""<?xml version='1.0' encoding='utf-8'?>
<ConfigDumpInfo xmlns='http://v8.1c.ru/8.3/xcf/dumpinfo'>
  <ConfigVersions>
    <Metadata name='Catalog.Products' id='cat-1'/>
    <Metadata name='Catalog.Products.Form.ItemForm' id='form-1'/>
    <Metadata name='Catalog.Products.Form.ItemForm.Form' id='form-1.0'/>
  </ConfigVersions>
</ConfigDumpInfo>
""",
        "Catalogs/Products.xml": b"<Meta><Name>Products</Name><Synonym>Products</Synonym></Meta>",
        "Catalogs/Products/Forms/ItemForm.xml": b"<Meta><Name>ItemForm</Name><Synonym>Item form</Synonym></Meta>",
        "Catalogs/Products/Forms/ItemForm/Ext/Form.xml": b"<Form xmlns='http://v8.1c.ru/8.3/xcf/logform'/>",
    }
    source = _DictSource(files)

    import_manifest_objects(db, source, source.list_files(), store_modules_in_table=False)
    objects = list_objects(db)
    assert any(obj.type == "form" and obj.name == "ItemForm" for obj in objects)


def test_import_manifest_objects_uses_dump_info_for_command_modules(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "import_dump_command_modules.mpdb"))
    ensure_manifest(db, seed_defaults=True)

    files = {
        "ConfigDumpInfo.xml": b"""<?xml version='1.0' encoding='utf-8'?>
<ConfigDumpInfo xmlns='http://v8.1c.ru/8.3/xcf/dumpinfo'>
  <ConfigVersions>
    <Metadata name='Catalog.Products' id='cat-1'/>
    <Metadata name='Catalog.Products.Command.Print' id='cmd-1'/>
    <Metadata name='Catalog.Products.Command.Print.CommandModule' id='cmd-1.2'/>
  </ConfigVersions>
</ConfigDumpInfo>
""",
        "Catalogs/Products.xml": b"<Meta><Name>Products</Name><Synonym>Products</Synonym></Meta>",
        "Catalogs/Products/Commands/Print/Ext/CommandModule.bsl": b"Procedure Run() EndProcedure",
    }
    source = _DictSource(files)

    import_manifest_objects(db, source, source.list_files(), store_modules_in_table=True)
    objects = list_objects(db)

    command = next(obj for obj in objects if obj.type == "command" and obj.name == "Print")
    command_modules = [obj for obj in objects if obj.parent_guid == command.guid and obj.type == "module"]
    assert command_modules == []
    modules_folder = next(obj for obj in objects if obj.parent_guid == command.guid and obj.kind == "folder" and obj.name == "modules")
    command_module_nodes = [obj for obj in objects if obj.parent_guid == modules_folder.guid and obj.type == "module"]
    assert len(command_module_nodes) == 1

    module_rows = db.table(MODULES_TABLE).select(where={"owner_guid": command.guid}) or []
    assert len(module_rows) == 1
    assert module_rows[0]["module_kind"] == "CommandModule"


def test_reimport_keeps_source_guid_and_refreshes_localized_module_aliases(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "localized_common_module_reimport.mpdb"))
    ensure_manifest(db, seed_defaults=True)
    module_guid = "f41d01ec-983a-4b39-9c11-a6d25d08df4f"
    files = {
        "CommonModules/СтандартныеПодсистемыПовтИсп.xml": f"""<?xml version='1.0' encoding='utf-8'?>
<MetaDataObject xmlns='http://v8.1c.ru/8.3/MDClasses' xmlns:v8='http://v8.1c.ru/8.1/data/core'>
  <CommonModule uuid='{module_guid}'>
    <Properties>
      <Name>СтандартныеПодсистемыПовтИсп</Name>
      <Synonym>
        <v8:item><v8:lang>uk</v8:lang><v8:content>Стандартні підсистеми повт вик</v8:content></v8:item>
      </Synonym>
    </Properties>
  </CommonModule>
</MetaDataObject>
""".encode("utf-8"),
        "CommonModules/СтандартныеПодсистемыПовтИсп/Ext/Module.bsl": (
            "Функція Версія() Експорт\nПовернути 1;\nКінецьФункції"
        ).encode("utf-8"),
    }
    source = _DictSource(files)

    first = import_manifest_objects(db, source, source.list_files(), store_modules_in_table=True)
    second = import_manifest_objects(db, source, source.list_files(), store_modules_in_table=True)

    assert first["CommonModules/СтандартныеПодсистемыПовтИсп.xml"] == module_guid
    assert second["CommonModules/СтандартныеПодсистемыПовтИсп.xml"] == module_guid
    owners = [obj for obj in list_objects(db) if obj.type == "common_module" and obj.guid == module_guid]
    assert len(owners) == 1
    assert owners[0].payload["source_name"] == "СтандартныеПодсистемыПовтИсп"
    assert owners[0].payload["code_ref_uk"] == "ЗагальнийМодуль.СтандартныеПодсистемыПовтИсп"
    assert owners[0].payload["code_ref_en"] == "CommonModule.StandartnyePodsystemyReuseYsp"

    rows = db.table(MODULES_TABLE).select(where={"owner_guid": module_guid}) or []
    assert len(rows) == 1
    assert rows[0]["ref_uk"] == "ЗагальнийМодуль.СтандартныеПодсистемыПовтИсп.Модуль"
    assert rows[0]["ref_en"] == "CommonModule.StandartnyePodsystemyReuseYsp.Module"
    assert resolve_common_module(db, name="СтандартныеПодсистемыПовтИсп")["module_guid"] == rows[0]["module_guid"]


def test_import_disambiguates_duplicate_localized_module_references(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "duplicate_module_aliases.mpdb"))
    ensure_manifest(db, seed_defaults=True)
    files = {
        "CommonCommands/FirstCommand.xml": (
            "<MetaDataObject><CommonCommand uuid='11111111-1111-4111-8111-111111111111'>"
            "<Properties><Name>FirstCommand</Name><Synonym><item><lang>uk</lang>"
            "<content>Спільна команда</content></item><item><lang>en</lang>"
            "<content>Shared command</content></item></Synonym></Properties>"
            "</CommonCommand></MetaDataObject>"
        ).encode("utf-8"),
        "CommonCommands/FirstCommand/Ext/CommandModule.bsl": b"Procedure Run() Export\nEndProcedure",
        "CommonCommands/SecondCommand.xml": (
            "<MetaDataObject><CommonCommand uuid='22222222-2222-4222-8222-222222222222'>"
            "<Properties><Name>SecondCommand</Name><Synonym><item><lang>uk</lang>"
            "<content>Спільна команда</content></item><item><lang>en</lang>"
            "<content>Shared command</content></item></Synonym></Properties>"
            "</CommonCommand></MetaDataObject>"
        ).encode("utf-8"),
        "CommonCommands/SecondCommand/Ext/CommandModule.bsl": b"Procedure Run() Export\nEndProcedure",
    }

    source = _DictSource(files)
    import_manifest_objects(db, source, source.list_files(), store_modules_in_table=True)
    rows = [
        row for row in db.table(MODULES_TABLE).select()
        if str(row.get("source_ref") or "").startswith("CommonCommands/")
    ]

    assert len(rows) == 2
    assert len({str(row["ref_uk"]).casefold() for row in rows}) == 2
    assert len({str(row["ref_en"]).casefold() for row in rows}) == 2
    assert all("_11111111" in row["ref_uk"] or "_22222222" in row["ref_uk"] for row in rows)

def test_import_manifest_objects_stores_oversized_modules_via_content_ref(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "import_big_module.mpdb"))
    ensure_manifest(db, seed_defaults=True)

    big_text = ("Procedure X()\n" + ("A" * 40000) + "\nEndProcedure").encode("utf-8")
    files = {
        "Catalogs/Products.xml": b"<Meta><Name>Products</Name><Synonym>Products</Synonym></Meta>",
        "Catalogs/Products/Ext/ObjectModule.bsl": big_text,
    }
    source = _DictSource(files)

    guid_by_xml = import_manifest_objects(
        db,
        source,
        source.list_files(),
        store_modules_in_table=True,
    )

    assert "Catalogs/Products.xml" in guid_by_xml

    objects = list_objects(db)
    module_nodes = [obj for obj in objects if obj.type == "module"]
    assert module_nodes
    ensure_modules_tables(db)
    module_rows = db.table(MODULES_TABLE).select() or []
    assert len(module_rows) == 1
    assert module_rows[0]["storage_kind"] == "asset"
    assert str(module_rows[0]["content_ref"]).startswith("module-src/")
    assert get_module_text(db, module_guid=str(module_rows[0]["module_guid"])) == normalize_module_text(
        big_text.decode("utf-8"), language="uk"
    ).text


def test_import_manifest_objects_skips_constants_module_nodes_but_keeps_module_rows(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "import_constants_value_manager.mpdb"))
    ensure_manifest(db, seed_defaults=True)

    files = {
        "Constants/Flag.xml": b"<Meta><Name>Flag</Name><Synonym>Flag</Synonym></Meta>",
        "Constants/Flag/Ext/ValueManagerModule.bsl": b"Procedure Test() EndProcedure",
    }
    source = _DictSource(files)

    import_manifest_objects(
        db,
        source,
        source.list_files(),
        store_modules_in_table=True,
    )

    objects = list_objects(db)
    constant = next(obj for obj in objects if obj.type == "constants" and obj.name == "Flag")
    assert [obj for obj in objects if obj.parent_guid == constant.guid and obj.kind == "folder" and obj.name == "modules"] == []
    assert [obj for obj in objects if obj.parent_guid == constant.guid and obj.type == "module"] == []

    module_rows = db.table(MODULES_TABLE).select(where={"owner_guid": constant.guid}) or []
    assert len(module_rows) == 1
    assert module_rows[0]["module_kind"] == "ValueManagerModule"


def test_create_localized_module_variants_creates_batched_rows(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "localized_modules.mpdb"))
    ensure_modules_tables(db)
    insert_modules_bulk(
        db,
        [
            make_module_row(
                owner_guid="owner-1",
                owner_kind="catalog",
                module_kind="ObjectModule",
                name="ObjectModule",
                text="Procedure Test() EndProcedure",
            )
        ],
    )

    created = _create_localized_module_variants(db)

    rows = db.table(MODULES_TABLE).select() or []
    langs = sorted(str(row.get("lang") or "") for row in rows)
    assert created == 2
    assert langs == ["", "en", "uk"]
    by_lang = {str(row.get("lang") or ""): row for row in rows}
    assert get_module_text(db, module_guid=str(by_lang["uk"]["module_guid"])) == "Процедура Test() КінецьПроцедури"
    assert get_module_text(db, module_guid=str(by_lang["en"]["module_guid"])) == "Procedure Test() EndProcedure"


def test_import_onec_configuration_reuses_existing_runtime_session(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeGateway:
        def __init__(self, base_url: str) -> None:
            captured["base_url"] = str(base_url)
            self.session_id = None
            self.ensure_calls = 0

        def ensure_session(self) -> str:
            self.ensure_calls += 1
            self.session_id = "created-session"
            captured["ensure_calls"] = self.ensure_calls
            return str(self.session_id)

        def _sid(self) -> str:
            return str(self.session_id or "")

        def open_by_uid(self, db_uid: str) -> dict[str, object]:
            captured["opened_db_uid"] = str(db_uid)
            captured["session_id_at_open"] = str(self.session_id or "")
            return {}

        def _call(self, action: str, payload: dict, *, timeout: float = 30.0) -> dict[str, object]:
            captured["action"] = str(action)
            captured["payload"] = dict(payload)
            captured["timeout"] = float(timeout)
            return {
                "imported_files": 1,
                "enriched": 0,
                "wiped": 0,
                "pruned_raw": 0,
                "pruned_sem": 0,
                "mode": "hard",
                "store_raw": False,
                "store_modules": True,
            }

    monkeypatch.setattr("src.runtime.gateway.RuntimeGateway", _FakeGateway)

    msg = import_onec_configuration(
        db_path="",
        source_path="F:/ConfigDumpInfo.xml",
        source_kind="xml",
        runtime_url="http://127.0.0.1:8765",
        db_uid="db-uid-1",
        session_id="sid-existing",
    )

    assert "1C/BAS configuration import completed." in msg
    assert captured["base_url"] == "http://127.0.0.1:8765"
    assert captured["opened_db_uid"] == "db-uid-1"
    assert captured["session_id_at_open"] == "sid-existing"
    assert captured["action"] == "onec.import"
    assert captured["payload"] == {
        "session_id": "sid-existing",
        "source_path": "F:/ConfigDumpInfo.xml",
        "source_kind": "xml",
        "mode": "hard",
        "wipe_prefixes": True,
        "prune_missing_assets": True,
        "store_raw_assets": False,
        "store_binary_assets": False,
        "store_raw_asset_keys": False,
        "store_modules_in_table": True,
    }
    assert captured["timeout"] == 3600.0
    assert captured.get("ensure_calls", 0) == 0


def test_import_onec_configuration_uses_long_runtime_timeout_for_data_migration(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeGateway:
        def __init__(self, _base_url: str) -> None:
            self.session_id = "sid"

        def ensure_session(self) -> str:
            return self.session_id

        def _sid(self) -> str:
            return self.session_id

        def open_by_uid(self, _db_uid: str) -> dict[str, object]:
            return {}

        def _call(self, action: str, payload: dict, *, timeout: float = 30.0) -> dict[str, object]:
            captured["action"] = str(action)
            captured["payload"] = dict(payload)
            captured["timeout"] = float(timeout)
            return {
                "imported_files": 1,
                "enriched": 0,
                "wiped": 0,
                "pruned_raw": 0,
                "pruned_sem": 0,
                "mode": "hard",
                "store_raw": False,
                "store_modules": True,
            }

    monkeypatch.setattr("src.runtime.gateway.RuntimeGateway", _FakeGateway)

    import_onec_configuration(
        db_path="",
        source_path="F:/base/1Cv8.1CD",
        source_kind="1cd",
        runtime_url="http://127.0.0.1:8765",
        db_uid="db-uid-1",
        migrate_data=True,
    )

    assert captured["action"] == "onec.import"
    assert captured["timeout"] == 86400.0
    assert captured["payload"]["migrate_data"] is True
    assert captured["payload"]["data_batch_size"] == 5000
    assert captured["payload"]["data_storage_mode"] == "packed"


def test_import_onec_configuration_reports_runtime_safe_import_backup(monkeypatch) -> None:
    class _FakeGateway:
        def __init__(self, _base_url: str) -> None:
            self.session_id = "sid"

        def ensure_session(self) -> str:
            return self.session_id

        def _sid(self) -> str:
            return self.session_id

        def open_by_uid(self, _db_uid: str) -> dict[str, object]:
            return {}

        def _call(self, _action: str, _payload: dict, *, timeout: float = 30.0) -> dict[str, object]:
            return {
                "imported_files": 1,
                "enriched": 0,
                "wiped": 0,
                "pruned_raw": 0,
                "pruned_sem": 0,
                "mode": "hard",
                "store_raw": False,
                "store_modules": True,
                "safe_import": True,
                "safe_import_mode": "backup-staging-validate-swap",
                "backup_path": "F:/db/main.backup-20260525.mpdb",
            }

    monkeypatch.setattr("src.runtime.gateway.RuntimeGateway", _FakeGateway)

    msg = import_onec_configuration(
        db_path="",
        source_path="F:/base/1Cv8.1CD",
        source_kind="1cd",
        runtime_url="http://127.0.0.1:8765",
        db_uid="db-uid-1",
    )

    assert "Safe import mode: backup-staging-validate-swap" in msg
    assert "Runtime backup created: F:/db/main.backup-20260525.mpdb" in msg


def test_purge_all_modules_removes_asset_backed_rows_and_assets(tmp_path) -> None:
    db = Mpdb(str(tmp_path / "purge_modules.mpdb"))
    ensure_modules_tables(db)
    insert_modules_bulk(
        db,
        [
            make_module_row(
                owner_guid="owner-1",
                owner_kind="catalog",
                module_kind="ObjectModule",
                name="ObjectModule",
                text="Procedure X()\n" + ("A" * 40000) + "\nEndProcedure",
            )
        ],
    )
    assert db.table(MODULES_TABLE).select()
    assert db.list_assets(prefix="module-src/")

    deleted = purge_all_modules(db)

    assert deleted == 1
    assert db.table(MODULES_TABLE).select() == []
    assert db.list_assets(prefix="module-src/") == []
    schema = db._meta.get("tables", {}).get(MODULES_TABLE, {}).get("schema", {})
    assert bool(schema.get("module_guid", {}).get("indexed"))
    assert bool(schema.get("module_guid", {}).get("unique"))
    assert bool(schema.get("owner_guid", {}).get("indexed"))
    assert not bool(schema.get("module_kind", {}).get("indexed"))

def test_identifier_number_names_are_not_inferred_as_numeric():
    import xml.etree.ElementTree as ET
    from src.infra.onec.importer import _field_type_from_input, _serialized_field_type
    for name in ("Number", "InvoiceNumber", "ContractNumber"):
        node = ET.fromstring(f'<InputField name="{name}"><DataPath>Object.{name}</DataPath></InputField>')
        assert _field_type_from_input(node) == "TextBox"
        assert _serialized_field_type([], name) == "TextBox"
