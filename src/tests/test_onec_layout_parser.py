from src.infra.onec.layout_parser import build_onec_layout_model


def test_build_onec_layout_model_parses_spreadsheet_document() -> None:
    xml = """\
<document xmlns="http://v8.1c.ru/8.2/data/spreadsheet" xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <columns>
    <size>3</size>
    <columnsItem><index>0</index><column><formatIndex>0</formatIndex></column></columnsItem>
    <columnsItem><index>1</index><column><formatIndex>1</formatIndex></column></columnsItem>
    <columnsItem><index>2</index><column><formatIndex>1</formatIndex></column></columnsItem>
  </columns>
  <rowsItem>
    <index>0</index>
    <row>
      <c><c><f>0</f><tl><v8:item><v8:lang>uk</v8:lang><v8:content>Заголовок</v8:content></v8:item></tl></c></c>
      <c><c><f>1</f></c></c>
      <c><c><f>1</f></c></c>
    </row>
  </rowsItem>
  <rowsItem>
    <index>1</index>
    <row>
      <c><c><f>1</f><tl><v8:item><v8:lang>ru</v8:lang><v8:content>[Параметр]</v8:content></v8:item></tl></c></c>
    </row>
  </rowsItem>
  <merge><r>0</r><c>0</c><w>2</w></merge>
  <namedItem xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="NamedItemCells">
    <name>Шапка</name>
    <area><type>Cells</type><beginRow>0</beginRow><endRow>1</endRow><beginColumn>0</beginColumn><endColumn>2</endColumn></area>
  </namedItem>
  <format><width>80</width><horizontalAlignment>Center</horizontalAlignment><font>0</font></format>
  <format><width>120</width><font>0</font></format>
  <font faceName="Arial" height="10" bold="true" italic="false" underline="false" />
</document>
""".encode("utf-8")

    model = build_onec_layout_model(body_bytes=xml, mime="application/xml", origin="Templates/Test/Ext/Template.xml")

    assert isinstance(model, dict)
    assert model["kind"] == "spreadsheet_document"
    assert model["row_count"] == 2
    assert model["column_count"] == 3
    assert model["cells"][0]["text"] == "Заголовок"
    assert model["parameters"] == []
    assert model["merges"][0] == {"row": 0, "col": 0, "rowspan": 1, "colspan": 3}
    assert model["named_areas"][0]["name"] == "Шапка"


def test_build_onec_layout_model_collects_parameter_cells() -> None:
    xml = """\
<document xmlns="http://v8.1c.ru/8.2/data/spreadsheet">
  <columns>
    <size>1</size>
    <columnsItem><index>0</index><column><formatIndex>0</formatIndex></column></columnsItem>
  </columns>
  <rowsItem>
    <index>0</index>
    <row>
      <c><c><f>0</f><parameter>DocumentNumber</parameter></c></c>
    </row>
  </rowsItem>
  <format><width>20</width><fillType>Parameter</fillType></format>
</document>
""".encode("utf-8")

    model = build_onec_layout_model(body_bytes=xml, mime="application/xml", origin="Templates/Test/Ext/Template.xml")

    assert isinstance(model, dict)
    assert model["kind"] == "spreadsheet_document"
    assert model["cells"][0]["parameter"] == "DocumentNumber"
    assert model["parameters"][0]["name"] == "DocumentNumber"
    assert model["parameters"][0]["fill_type"] == "Parameter"


def test_build_onec_layout_model_honors_sparse_cell_indexes() -> None:
    xml = """\
<document xmlns="http://v8.1c.ru/8.2/data/spreadsheet" xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <columns>
    <size>18</size>
    <columnsItem><index>0</index><column><formatIndex>0</formatIndex></column></columnsItem>
    <columnsItem><index>16</index><column><formatIndex>0</formatIndex></column></columnsItem>
  </columns>
  <rowsItem>
    <index>0</index>
    <row>
      <c><c><f>0</f><tl><v8:item><v8:lang>uk</v8:lang><v8:content>Ліворуч</v8:content></v8:item></tl></c></c>
      <c><i>16</i><c><f>0</f><tl><v8:item><v8:lang>uk</v8:lang><v8:content>Праворуч</v8:content></v8:item></tl></c></c>
    </row>
  </rowsItem>
  <format><width>40</width></format>
</document>
""".encode("utf-8")

    model = build_onec_layout_model(body_bytes=xml, mime="application/xml", origin="Templates/Test/Ext/Template.xml")

    assert isinstance(model, dict)
    assert model["kind"] == "spreadsheet_document"
    assert model["column_count"] == 18
    assert model["cells"] == [
        {"row": 0, "col": 0, "format_index": 0, "text": "Ліворуч"},
        {"row": 0, "col": 16, "format_index": 0, "text": "Праворуч"},
    ]
    assert model["named_areas"] == []


def test_build_onec_layout_model_keeps_named_area_columns_id() -> None:
    xml = """\
<document xmlns="http://v8.1c.ru/8.2/data/spreadsheet">
  <columns>
    <id>main</id>
    <size>1</size>
    <columnsItem><index>0</index><column><formatIndex>0</formatIndex></column></columnsItem>
  </columns>
  <rowsItem>
    <index>0</index>
    <row>
      <columnsID>main</columnsID>
      <c><c><f>0</f></c></c>
    </row>
  </rowsItem>
  <namedItem>
    <name>Заголовок</name>
    <area>
      <type>Rows</type>
      <beginRow>0</beginRow>
      <endRow>0</endRow>
      <beginColumn>-1</beginColumn>
      <endColumn>-1</endColumn>
      <columnsID>main</columnsID>
    </area>
  </namedItem>
  <format><width>20</width></format>
</document>
""".encode("utf-8")

    model = build_onec_layout_model(body_bytes=xml, mime="application/xml", origin="Templates/Test/Ext/Template.xml")

    assert isinstance(model, dict)
    assert model["named_areas"][0]["columns_id"] == "main"


def test_build_onec_layout_model_parses_side_borders_as_ints() -> None:
    xml = """\
<document xmlns="http://v8.1c.ru/8.2/data/spreadsheet">
  <columns>
    <size>1</size>
    <columnsItem><index>0</index><column><formatIndex>0</formatIndex></column></columnsItem>
  </columns>
  <rowsItem>
    <index>0</index>
    <row>
      <c><c><f>0</f></c></c>
    </row>
  </rowsItem>
  <format>
    <width>20</width>
    <topBorder>1</topBorder>
    <bottomBorder>2</bottomBorder>
    <leftBorder>3</leftBorder>
    <rightBorder>4</rightBorder>
  </format>
</document>
""".encode("utf-8")

    model = build_onec_layout_model(body_bytes=xml, mime="application/xml", origin="Templates/Test/Ext/Template.xml")

    assert isinstance(model, dict)
    fmt = model["formats"][0]
    assert fmt["topBorder"] == 1
    assert fmt["bottomBorder"] == 2
    assert fmt["leftBorder"] == 3
    assert fmt["rightBorder"] == 4


def test_build_onec_layout_model_classifies_dcs_templates() -> None:
    xml = """\
<DataCompositionSchema xmlns="http://v8.1c.ru/8.1/data-composition-system/schema">
  <dataSource><name>Source1</name></dataSource>
  <dataSet><name>Set1</name></dataSet>
  <parameter><name>Param1</name></parameter>
  <settingsVariant><name>Main</name></settingsVariant>
</DataCompositionSchema>
""".encode("utf-8")

    model = build_onec_layout_model(body_bytes=xml, mime="application/xml", origin="Templates/Test/Ext/Template.xml")

    assert isinstance(model, dict)
    assert model["kind"] == "data_composition_schema"
    assert model["data_sets"] == ["Set1"]
    assert model["parameters"] == ["Param1"]


def test_build_onec_layout_model_classifies_ole_binary_templates() -> None:
    data = bytes.fromhex("d0cf11e0a1b11ae1") + b"\x00" * 32

    model = build_onec_layout_model(body_bytes=data, mime="application/octet-stream", origin="Templates/Test/Ext/Template.bin")

    assert isinstance(model, dict)
    assert model["kind"] == "binary_ole_template"
    assert model["container"] == "ole_compound"
    assert model["signature"] == "D0 CF 11 E0 A1 B1 1A E1"
    assert model["preview_head_hex"].startswith("D0 CF 11 E0 A1 B1 1A E1")
    assert model["preview_head_ascii"].startswith("........")


def test_build_onec_layout_model_includes_preview_excerpt_for_binary_templates() -> None:
    data = b"\x01\x02Hello\x7f"

    model = build_onec_layout_model(body_bytes=data, mime="application/octet-stream", origin="Templates/Test/Ext/Template.bin")

    assert isinstance(model, dict)
    assert model["kind"] == "binary_template"
    assert model["preview_head_ascii"] == "..Hello."
    assert "01 02 48 65 6C 6C 6F 7F" in model["preview_head_hex"]
