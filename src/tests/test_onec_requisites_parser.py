from src.infra.onec.onec_config_parser import extract_config_type_aliases, parse_config_text
from src.infra.onec.onec_requisites_parser import OneCXmlParser, enrich_manifest_payload, parse_object_xml


def test_parse_object_xml_extracts_document_level_properties() -> None:
    xml = """\
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <Document uuid="doc-1">
    <Properties>
      <Name>AdvanceReport</Name>
      <Synonym>
        <v8:item><v8:lang>uk</v8:lang><v8:content>Авансовий звіт</v8:content></v8:item>
      </Synonym>
      <UseStandardCommands>true</UseStandardCommands>
      <NumberType>String</NumberType>
      <NumberLength>11</NumberLength>
      <NumberAllowedLength>Fixed</NumberAllowedLength>
      <NumberPeriodicity>Year</NumberPeriodicity>
      <CheckUnique>true</CheckUnique>
      <Autonumbering>true</Autonumbering>
      <Posting>Allow</Posting>
      <RealTimePosting>Allow</RealTimePosting>
      <BasedOn><Item>Document.BaseDoc</Item></BasedOn>
      <InputByString><Field>Document.AdvanceReport.StandardAttribute.Number</Field></InputByString>
      <CreateOnInput>Use</CreateOnInput>
      <SearchStringModeOnInputByString>Begin</SearchStringModeOnInputByString>
      <FullTextSearchOnInputByString>DontUse</FullTextSearchOnInputByString>
      <ChoiceDataGetModeOnInputByString>Directly</ChoiceDataGetModeOnInputByString>
      <ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>
      <DefaultObjectForm>Document.AdvanceReport.Form.ObjectForm</DefaultObjectForm>
      <DefaultListForm>Document.AdvanceReport.Form.ListForm</DefaultListForm>
      <DefaultChoiceForm>Document.AdvanceReport.Form.ChoiceForm</DefaultChoiceForm>
      <RegisterRecordsDeletion>AutoDeleteOff</RegisterRecordsDeletion>
      <RegisterRecordsWritingOnPost>WriteSelected</RegisterRecordsWritingOnPost>
      <SequenceFilling>AutoFillOff</SequenceFilling>
      <RegisterRecords>
        <Item>AccumulationRegister.Cash</Item>
        <Item>InformationRegister.DocSums</Item>
      </RegisterRecords>
      <PostInPrivilegedMode>true</PostInPrivilegedMode>
      <UnpostInPrivilegedMode>false</UnpostInPrivilegedMode>
      <IncludeHelpInContents>true</IncludeHelpInContents>
      <DataLockFields><Field>Document.AdvanceReport.StandardAttribute.Number</Field></DataLockFields>
      <DataLockControlMode>Automatic</DataLockControlMode>
      <ListPresentation>
        <v8:item><v8:lang>uk</v8:lang><v8:content>Авансові звіти</v8:content></v8:item>
      </ListPresentation>
      <Explanation>
        <v8:item><v8:lang>uk</v8:lang><v8:content>Пояснення</v8:content></v8:item>
      </Explanation>
      <ToolTip>
        <v8:item><v8:lang>uk</v8:lang><v8:content>Підказка</v8:content></v8:item>
      </ToolTip>
      <FullTextSearch>Use</FullTextSearch>
      <DataHistory>DontUse</DataHistory>
      <UpdateDataHistoryImmediatelyAfterWrite>false</UpdateDataHistoryImmediatelyAfterWrite>
      <ExecuteAfterWriteDataHistoryVersionProcessing>true</ExecuteAfterWriteDataHistoryVersionProcessing>
    </Properties>
  </Document>
</MetaDataObject>
"""

    obj = parse_object_xml(xml.encode("utf-8"), origin_path="Documents/AdvanceReport.xml")

    assert obj is not None
    payload = obj.to_mp_payload()
    assert payload["use_standard_commands"] is True
    assert payload["number_type"] == "string"
    assert payload["number_length"] == 11
    assert payload["number_allowed_length"] == "fixed"
    assert payload["number_periodicity"] == "year"
    assert payload["check_unique"] is True
    assert payload["autonumbering"] is True
    assert payload["posting"] == "allow"
    assert payload["real_time_posting"] == "allow"
    assert payload["based_on"] == ["Document.BaseDoc"]
    assert payload["input_by_string"] == "Document.AdvanceReport.StandardAttribute.Number"
    assert payload["create_on_input"] == "use"
    assert payload["search_string_mode_on_input_by_string"] == "begin"
    assert payload["full_text_search_on_input_by_string"] == "dont_use"
    assert payload["choice_data_get_mode_on_input_by_string"] == "directly"
    assert payload["choice_history_on_input"] == "auto"
    assert payload["default_object_form"] == "Document.AdvanceReport.Form.ObjectForm"
    assert payload["default_list_form"] == "Document.AdvanceReport.Form.ListForm"
    assert payload["default_choice_form"] == "Document.AdvanceReport.Form.ChoiceForm"
    assert payload["register_records_deletion"] == "auto_delete_off"
    assert payload["register_records_writing_on_post"] == "write_selected"
    assert payload["sequence_filling"] == "auto_fill_off"
    assert payload["register_records"] == ["AccumulationRegister.Cash", "InformationRegister.DocSums"]
    assert payload["post_in_privileged_mode"] is True
    assert payload["unpost_in_privileged_mode"] is False
    assert payload["include_help_in_contents"] is True
    assert payload["data_lock_fields"] == "Document.AdvanceReport.StandardAttribute.Number"
    assert payload["data_lock_control_mode"] == "automatic"
    assert payload["list_presentation"]["uk"] == "Авансові звіти"
    assert payload["explanation"]["uk"] == "Пояснення"
    assert payload["hint"]["uk"] == "Підказка"
    assert payload["full_text_search"] == "use"
    assert payload["data_history"] == "dont_use"
    assert payload["update_data_history_immediately_after_write"] is False
    assert payload["execute_after_write_data_history_version_processing"] is True


def test_enrich_manifest_payload_merges_document_level_properties() -> None:
    xml = """\
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <Document uuid="doc-1">
    <Properties>
      <Name>AdvanceReport</Name>
      <NumberLength>9</NumberLength>
      <Autonumbering>false</Autonumbering>
      <DefaultListForm>Document.AdvanceReport.Form.ListForm</DefaultListForm>
    </Properties>
  </Document>
</MetaDataObject>
"""

    obj = parse_object_xml(xml.encode("utf-8"), origin_path="Documents/AdvanceReport.xml")

    assert obj is not None
    enriched = enrich_manifest_payload({"comment": "Existing"}, obj)

    assert enriched["comment"] == "Existing"
    assert enriched["number_length"] == 9
    assert enriched["autonumbering"] is False
    assert enriched["default_list_form"] == "Document.AdvanceReport.Form.ListForm"


def test_parse_object_xml_extracts_full_requisite_property_profile() -> None:
    xml = """\
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Document uuid="doc-1">
    <Properties><Name>AdvanceReport</Name></Properties>
    <ChildObjects>
      <Attribute uuid="attribute-1">
        <Properties>
          <Name>Organization</Name>
          <Synonym><v8:item><v8:lang>uk</v8:lang><v8:content>Організація</v8:content></v8:item></Synonym>
          <Type><v8:Type>cfg:CatalogRef.Organizations</v8:Type></Type>
          <Format>DF=yyyy-MM-dd</Format>
          <EditFormat>DF=dd.MM.yyyy</EditFormat>
          <ToolTip><v8:item><v8:lang>uk</v8:lang><v8:content>Організація документа</v8:content></v8:item></ToolTip>
          <MarkNegatives>false</MarkNegatives>
          <Mask>AAA-999</Mask>
          <MultiLine>false</MultiLine>
          <PasswordMode>false</PasswordMode>
          <ExtendedEdit>true</ExtendedEdit>
          <FillFromFillingValue>true</FillFromFillingValue>
          <FillValue xsi:type="xr:DesignTimeRef">Catalog.Organizations.EmptyRef</FillValue>
          <FillChecking>ShowError</FillChecking>
          <ChoiceFoldersAndItems>Items</ChoiceFoldersAndItems>
          <ChoiceParameterLinks><Item>Owner=Organization</Item></ChoiceParameterLinks>
          <ChoiceParameters><Item>Status=Active</Item></ChoiceParameters>
          <QuickChoice>Auto</QuickChoice>
          <CreateOnInput>Auto</CreateOnInput>
          <ChoiceForm>Catalog.Organizations.Form.ChoiceForm</ChoiceForm>
          <LinkByType>DefinedType.Organization</LinkByType>
          <ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>
          <Indexing>DontIndex</Indexing>
          <FullTextSearch>Use</FullTextSearch>
          <DataHistory>Use</DataHistory>
        </Properties>
      </Attribute>
    </ChildObjects>
  </Document>
</MetaDataObject>
"""

    obj = parse_object_xml(xml.encode("utf-8"), origin_path="Documents/AdvanceReport.xml")

    assert obj is not None
    requisite = obj.to_mp_payload()["requisites"][0]
    assert requisite["name"] == "Organization"
    assert requisite["format"] == "DF=yyyy-MM-dd"
    assert requisite["editing_format"] == "DF=dd.MM.yyyy"
    assert requisite["hint"]["uk"] == "Організація документа"
    assert requisite["mark_negatives"] is False
    assert requisite["mask"] == "AAA-999"
    assert requisite["extended_edit"] is True
    assert requisite["fill_from_filling_value"] is True
    assert requisite["fill_value"] == "Catalog.Organizations.EmptyRef"
    assert requisite["fill_checking"] == "ShowError"
    assert requisite["choice_groups_elements"] == "Items"
    assert requisite["parameter_links"] == ["Owner=Organization"]
    assert requisite["choice_parameters"] == ["Status=Active"]
    assert requisite["quick_choice"] == "Auto"
    assert requisite["create_on_input"] == "Auto"
    assert requisite["choice_form"] == "Catalog.Organizations.Form.ChoiceForm"
    assert requisite["type_link"] == "DefinedType.Organization"
    assert requisite["choice_history_on_input"] == "Auto"
    assert requisite["indexing"] == "DontIndex"
    assert requisite["full_text_search"] == "Use"
    assert requisite["data_history"] == "Use"


def test_parse_object_xml_extracts_subsystem_properties_and_content() -> None:
    xml = """\
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Subsystem uuid="sub-1">
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
      <Picture>
        <xr:Ref>CommonPicture.Admin48</xr:Ref>
      </Picture>
      <Content>
        <xr:Item xsi:type="xr:MDObjectRef">Catalog.Products</xr:Item>
        <xr:Item xsi:type="xr:MDObjectRef">CommonCommand.OpenSettings</xr:Item>
      </Content>
    </Properties>
    <ChildObjects>
      <Subsystem>NestedSubsystem</Subsystem>
    </ChildObjects>
  </Subsystem>
</MetaDataObject>
"""

    obj = parse_object_xml(xml.encode("utf-8"), origin_path="Subsystems/Administration.xml")

    assert obj is not None
    payload = obj.to_mp_payload()
    assert payload["include_help_in_contents"] is True
    assert payload["include_in_command_interface"] is False
    assert payload["use_one_command"] is True
    assert payload["picture_ref"] == "CommonPicture.Admin48"
    assert payload["content_refs"] == ["Catalog.Products", "CommonCommand.OpenSettings"]
    assert payload["child_subsystems"] == ["NestedSubsystem"]
    assert payload["explanation"]["uk"] == "Пояснення підсистеми"


def test_parse_object_xml_strips_numeric_prefix_from_subsystem_names() -> None:
    xml = """\
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <Subsystem uuid="sub-1">
    <Properties>
      <Name>2 Закупівлі</Name>
      <Synonym>
        <v8:item><v8:lang>uk</v8:lang><v8:content>2 Закупівлі</v8:content></v8:item>
      </Synonym>
    </Properties>
    <ChildObjects>
      <Subsystem>2 Продажі</Subsystem>
    </ChildObjects>
  </Subsystem>
</MetaDataObject>
"""

    obj = parse_object_xml(xml.encode("utf-8"), origin_path="Subsystems/2 Закупівлі.xml")

    assert obj is not None
    assert obj.name == "Закупівлі"
    assert obj.synonyms["uk"] == "Закупівлі"
    assert obj.child_subsystems == ["Продажі"]


def test_parse_object_xml_deduplicates_subsystem_content_and_children() -> None:
    xml = """\
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Subsystem uuid="sub-1">
    <Properties>
      <Name>Sales</Name>
      <Content>
        <xr:Item xsi:type="xr:MDObjectRef">Catalog.Products</xr:Item>
        <xr:Item xsi:type="xr:MDObjectRef">Catalog.Products</xr:Item>
        <xr:Item xsi:type="xr:MDObjectRef">CommonCommand.OpenSettings</xr:Item>
      </Content>
    </Properties>
    <ChildObjects>
      <Subsystem>Marketing</Subsystem>
      <Subsystem>Marketing</Subsystem>
      <Subsystem>Inventory</Subsystem>
      <Subsystem>Inventory</Subsystem>
    </ChildObjects>
  </Subsystem>
</MetaDataObject>
"""

    obj = parse_object_xml(xml.encode("utf-8"), origin_path="Subsystems/Sales.xml")

    assert obj is not None
    payload = obj.to_mp_payload()
    assert payload["content_refs"] == [
        "Catalog.Products",
        "CommonCommand.OpenSettings",
    ]
    assert payload["child_subsystems"] == ["Marketing", "Inventory"]


def test_parse_config_text_collects_subsystem_children() -> None:
    text = (
        '{0,0,11111111-1111-1111-1111-111111111111},"Sales",{0},"",0,0}'
        '{0,0,22222222-2222-2222-2222-222222222222},"Retail",{0},"",0,0}'
        '{0,0,33333333-3333-3333-3333-333333333333},"Stock",{0},"",0,0}'
    )

    obj = parse_config_text(
        text,
        object_uuid="11111111-1111-1111-1111-111111111111",
        object_family="subsystem",
    )

    assert obj is not None
    assert obj.child_subsystems == ["Retail", "Stock"]


def test_parse_config_text_extracts_real_onecd_requisite_properties() -> None:
    zero = "00000000-0000-0000-0000-000000000000"
    document_uuid = "11111111-1111-1111-1111-111111111111"
    requisite_uuid = "22222222-2222-2222-2222-222222222222"
    ref_uuid = "33333333-3333-3333-3333-333333333333"
    text = (
        f'{{3,{{1,0,{document_uuid}}},"AdvanceReport",'
        f'{{1,"uk","Авансовий звіт"}},"",0,0,{zero},0}},'
        f'{{6,{{27,{{2,{{3,{{1,0,{requisite_uuid}}},"Organization",'
        f'{{1,"uk","Організація"}},"",0,0,{zero},0}},'
        f'{{"Pattern",{{"#",{ref_uuid}}}}}}},0,{{0}},'
        f'{{1,"uk","Організація підприємства"}},0,"",0,{{"U"}},{{"U"}},'
        f'0,{zero},2,1,{{5006,0}},{{3,0,0}},{{0,0}},0,{{0}},'
        f'{{"#",5c14e26f-099b-4d37-84a6-b433d87400da,{{0,{ref_uuid},{zero}}}}},'
        f'1,0,0}},0,1,1,0,{{1,{zero}}}}}'
    )

    obj = parse_config_text(
        text,
        object_uuid=document_uuid,
        object_family="document",
        ref_uuid_to_name={ref_uuid: ("catalog", "Organizations")},
    )

    assert obj is not None
    assert len(obj.requisites) == 1
    requisite = obj.requisites[0].to_mp_payload()
    assert requisite["name"] == "Organization"
    assert requisite["type"] == "ref"
    assert requisite["ref_name"] == "Organizations"
    assert requisite["required"] is True
    assert requisite["fill_checking"] == "ShowError"
    assert requisite["fill_value"] == "Catalog.Organizations.EmptyRef"
    assert requisite["hint"] == {"uk": "Організація підприємства"}
    assert requisite["fill_from_filling_value"] is True
    assert requisite["choice_groups_elements"] == "Items"
    assert requisite["quick_choice"] == "Auto"
    assert requisite["create_on_input"] == "Auto"
    assert requisite["indexing"] == "DontIndex"
    assert requisite["full_text_search"] == "Use"
    assert requisite["data_history"] == "Use"


def test_extract_config_type_aliases_reads_root_type_guid_vector() -> None:
    aliases = extract_config_type_aliases(
        "{1,{3,aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa,"
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb,{0,{3}}},0}"
    )

    assert aliases == [
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    ]


def test_onec_xml_parser_includes_subsystems_from_folder_sources() -> None:
    objects = OneCXmlParser().parse_bytes_map(
        {
            "Subsystems/Administration.xml": """<?xml version='1.0' encoding='utf-8'?>
<MetaDataObject xmlns='http://v8.1c.ru/8.3/MDClasses'>
  <Subsystem uuid='sub-1'>
    <Properties>
      <Name>Administration</Name>
    </Properties>
  </Subsystem>
</MetaDataObject>
""".encode("utf-8")
        }
    )

    assert len(objects) == 1
    assert objects[0].obj_type == "subsystem"
    assert objects[0].name == "Administration"


def test_onec_xml_parser_includes_nested_subsystems_from_folder_sources() -> None:
    objects = OneCXmlParser().parse_bytes_map(
        {
            "Subsystems/Administration.xml": """<?xml version='1.0' encoding='utf-8'?>
<MetaDataObject xmlns='http://v8.1c.ru/8.3/MDClasses'>
  <Subsystem uuid='sub-1'>
    <Properties>
      <Name>Administration</Name>
    </Properties>
  </Subsystem>
</MetaDataObject>
""".encode("utf-8"),
            "Subsystems/Administration/Subsystems/Settings.xml": """<?xml version='1.0' encoding='utf-8'?>
<MetaDataObject xmlns='http://v8.1c.ru/8.3/MDClasses'>
  <Subsystem uuid='sub-2'>
    <Properties>
      <Name>Settings</Name>
    </Properties>
  </Subsystem>
</MetaDataObject>
""".encode("utf-8"),
        }
    )

    got = {(obj.obj_type, obj.name) for obj in objects}
    assert ("subsystem", "Administration") in got
    assert ("subsystem", "Settings") in got


def test_parse_object_xml_extracts_register_dimensions_resources_and_attributes() -> None:
    xml = """\
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <InformationRegister uuid="reg-1">
    <Properties>
      <Name>StockBalances</Name>
    </Properties>
    <ChildObjects>
      <Dimension uuid="dim-1">
        <Properties>
          <Name>Warehouse</Name>
          <Synonym>
            <v8:item><v8:lang>uk</v8:lang><v8:content>Склад</v8:content></v8:item>
          </Synonym>
          <Type><v8:Type>cfg:CatalogRef.Warehouses</v8:Type></Type>
          <FillChecking>DontCheck</FillChecking>
        </Properties>
      </Dimension>
      <Resource uuid="res-1">
        <Properties>
          <Name>Quantity</Name>
          <Synonym>
            <v8:item><v8:lang>uk</v8:lang><v8:content>Кількість</v8:content></v8:item>
          </Synonym>
          <Type>
            <v8:Type>xs:decimal</v8:Type>
            <v8:NumberQualifiers>
              <v8:Digits>15</v8:Digits>
              <v8:FractionDigits>3</v8:FractionDigits>
            </v8:NumberQualifiers>
          </Type>
          <FillChecking>DontCheck</FillChecking>
        </Properties>
      </Resource>
      <Attribute uuid="attr-1">
        <Properties>
          <Name>CommentText</Name>
          <Type><v8:Type>xs:string</v8:Type></Type>
          <FillChecking>DontCheck</FillChecking>
        </Properties>
      </Attribute>
    </ChildObjects>
  </InformationRegister>
</MetaDataObject>
"""

    obj = parse_object_xml(xml.encode("utf-8"), origin_path="InformationRegisters/StockBalances.xml")

    assert obj is not None
    payload = obj.to_mp_payload()
    assert payload["dimensions"][0]["name"] == "Warehouse"
    assert payload["dimensions"][0]["ref_name"] == "Warehouses"
    assert payload["resources"][0]["name"] == "Quantity"
    assert payload["resources"][0]["number_qualifiers"]["fraction_digits"] == 3
    assert payload["attributes"][0]["name"] == "CommentText"
    assert "requisites" not in payload


def test_enrich_manifest_payload_merges_register_schema_sections() -> None:
    xml = """\
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <AccumulationRegister uuid="reg-1">
    <Properties>
      <Name>Bonuses</Name>
    </Properties>
    <ChildObjects>
      <Dimension uuid="dim-1">
        <Properties>
          <Name>LoyaltyProgram</Name>
          <Type><v8:Type>cfg:CatalogRef.LoyaltyPrograms</v8:Type></Type>
          <FillChecking>DontCheck</FillChecking>
        </Properties>
      </Dimension>
      <Resource uuid="res-1">
        <Properties>
          <Name>Amount</Name>
          <Type>
            <v8:Type>xs:decimal</v8:Type>
            <v8:NumberQualifiers>
              <v8:Digits>15</v8:Digits>
              <v8:FractionDigits>2</v8:FractionDigits>
            </v8:NumberQualifiers>
          </Type>
          <FillChecking>DontCheck</FillChecking>
        </Properties>
      </Resource>
    </ChildObjects>
  </AccumulationRegister>
</MetaDataObject>
"""

    obj = parse_object_xml(xml.encode("utf-8"), origin_path="AccumulationRegisters/Bonuses.xml")

    assert obj is not None
    enriched = enrich_manifest_payload({"comment": "Existing"}, obj)

    assert enriched["comment"] == "Existing"
    assert enriched["dimensions"][0]["name"] == "LoyaltyProgram"
    assert enriched["resources"][0]["name"] == "Amount"


def test_onec_xml_parser_merges_role_companion_rights_xml() -> None:
    objects = OneCXmlParser().parse_bytes_map(
        {
            "Roles/Admin.xml": """<?xml version='1.0' encoding='utf-8'?>
<MetaDataObject xmlns='http://v8.1c.ru/8.3/MDClasses' xmlns:v8='http://v8.1c.ru/8.1/data/core'>
  <Role uuid='role-1'>
    <Properties>
      <Name>Admin</Name>
      <Synonym>
        <v8:item><v8:lang>uk</v8:lang><v8:content>Адміністратор</v8:content></v8:item>
      </Synonym>
    </Properties>
  </Role>
</MetaDataObject>
""".encode("utf-8"),
            "Roles/Admin/Ext/Rights.xml": """<?xml version='1.0' encoding='utf-8'?>
<Rights xmlns='http://v8.1c.ru/8.2/roles'>
  <setForNewObjects>false</setForNewObjects>
  <setForAttributesByDefault>true</setForAttributesByDefault>
  <independentRightsOfChildObjects>false</independentRightsOfChildObjects>
  <object>
    <name>Catalog.Products</name>
    <right>
      <name>Read</name>
      <value>true</value>
      <restrictionByCondition>
        <field>Code</field>
        <condition>ГДЕ Истина</condition>
      </restrictionByCondition>
    </right>
    <right>
      <name>Update</name>
      <value>false</value>
    </right>
  </object>
  <restrictionTemplate>
    <name>ByValue</name>
    <condition>ГДЕ Т.Склад = &amp;Склад</condition>
  </restrictionTemplate>
</Rights>
""".encode("utf-8"),
        }
    )

    assert len(objects) == 1
    assert objects[0].obj_type == "role"
    assert objects[0].name == "Admin"

    payload = objects[0].to_mp_payload()
    assert payload["set_for_new_objects"] is False
    assert payload["set_for_attributes_by_default"] is True
    assert payload["independent_rights_of_child_objects"] is False
    assert payload["rights"][0]["object"] == "Catalog.Products"
    assert payload["rights"][0]["rights"]["Read"] is True
    assert payload["rights"][0]["rights"]["Update"] is False
    assert payload["rights"][0]["restrictions"][0]["right"] == "Read"
    assert payload["rights"][0]["restrictions"][0]["field"] == "Code"
    assert "ГДЕ Истина" in payload["rights"][0]["restrictions"][0]["condition"]
    assert payload["restriction_templates"][0]["name"] == "ByValue"


def test_common_module_refs_use_source_name_and_localized_namespaces() -> None:
    from src.infra.onec.onec_requisites_enrich import module_refs_from_import_origin

    refs = module_refs_from_import_origin(
        "CommonModules/СтандартныеПодсистемыПовтИсп/Ext/Module.bsl",
        module_kind="Module",
        owner_title_uk="Стандартні підсистеми повт вик",
        owner_title_en="Standard subsystems reuse",
    )

    assert refs["canonical_ref"] == "CommonModule.СтандартныеПодсистемыПовтИсп.Module"
    assert refs["ref_uk"] == "ЗагальнийМодуль.СтандартныеПодсистемыПовтИсп.Модуль"
    assert refs["ref_en"] == "CommonModule.StandartnyePodsystemyReuseYsp.Module"


def test_common_module_refs_do_not_build_identity_from_ukrainian_synonym() -> None:
    from src.infra.onec.onec_requisites_enrich import module_refs_from_import_origin

    refs = module_refs_from_import_origin(
        "CommonModules/СтандартныеПодсистемыПовтИсп/Ext/Module.bsl",
        module_kind="Module",
        owner_name="СтандартныеПодсистемыПовтИсп",
        owner_title_uk="Стандартні підсистеми повт вик",
    )

    assert refs["canonical_ref"] == "CommonModule.СтандартныеПодсистемыПовтИсп.Module"
    assert refs["ref_uk"] == "ЗагальнийМодуль.СтандартныеПодсистемыПовтИсп.Модуль"
    assert refs["ref_en"] == "CommonModule.StandartnyePodsystemyReuseYsp.Module"


def test_common_module_refs_ignore_english_synonym_for_identity() -> None:
    from src.infra.onec.onec_requisites_enrich import module_refs_from_import_origin

    refs = module_refs_from_import_origin(
        "CommonModules/СтандартныеПодсистемыПовтИсп/Ext/Module.bsl",
        module_kind="Module",
        owner_name="СтандартныеПодсистемыПовтИсп",
        owner_title_uk="Стандартні підсистеми повт вик",
        owner_title_en="СтандартныеПодсистемыПовтИсп",
    )

    assert refs["ref_en"] == "CommonModule.StandartnyePodsystemyReuseYsp.Module"


def test_common_module_source_name_keeps_underscores_and_case() -> None:
    from src.infra.onec.onec_requisites_enrich import module_refs_from_import_origin

    source_name = "СообщенияОбменаДаннымиОбработчикСообщения_2_1_2_1"
    refs = module_refs_from_import_origin(
        f"CommonModules/{source_name}/Ext/Module.bsl",
        module_kind="Module",
        owner_name=source_name,
        owner_title_uk="Обробник повідомлень",
    )

    assert refs["ref_uk"] == f"ЗагальнийМодуль.{source_name}.Модуль"
    assert refs["ref_en"] == "CommonModule.SoobshchenyyaObmenaDannymyObrabotchykSoobshchenyya2121.Module"


def test_nested_module_refs_include_parent_and_child_identity() -> None:
    from src.infra.onec.onec_requisites_enrich import module_refs_from_import_origin

    first = module_refs_from_import_origin(
        "Documents/Замовлення/Forms/ФормаСписка/Ext/Form/Module.bsl",
        module_kind="FormModule",
        owner_name="ФормаСписка",
        owner_title_uk="Форма списку",
    )
    second = module_refs_from_import_origin(
        "Documents/Реализация/Forms/ФормаСписка/Ext/Form/Module.bsl",
        module_kind="FormModule",
        owner_name="ФормаСписка",
        owner_title_uk="Форма списку",
    )

    assert first["canonical_ref"] == "Document.Замовлення.Form.ФормаСписка.FormModule"
    assert first["ref_uk"] == "Документ.Замовлення.Форма.ФормаСписку.МодульФорми"
    assert first["ref_en"] == "Document.Zamovlennya.Form.FormSpysku.FormModule"
    assert first["canonical_ref"] != second["canonical_ref"]
    assert first["ref_en"] != second["ref_en"]
