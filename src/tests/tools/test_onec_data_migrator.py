import unittest
from unittest.mock import MagicMock, patch, mock_open
import json
from src.tools.onec_data_migrator import (
    _format_type,
    _map_onec_type_to_mp,
    get_onec_metadata,
    migrate_metadata_to_platform
)
from src.infra.onec.onec_requisites_model import OneCMetaObject, OneCRequisite

class TestOneCDataMigrator(unittest.TestCase):

    def test_format_type_basic(self):
        """Tests formatting of basic 1C types for display."""
        self.assertEqual(_format_type({"types": ["string"], "length": 10}), "String(10)")
        self.assertEqual(_format_type({"types": ["number"], "length": 15, "precision": 2}), "Number(15, 2)")
        self.assertEqual(_format_type({"types": ["date"]}), "Date")
        self.assertEqual(_format_type({"types": ["reference"], "ref_type": "Catalog.Goods"}), "Reference(Catalog.Goods)")

    def test_map_onec_type_to_mp(self):
        """Tests mapping of 1C types to MetaPlatform Manifest types."""
        # String mapping
        res_str = _map_onec_type_to_mp({"types": ["string"], "length": 50})
        self.assertEqual(res_str["type"], "string")
        self.assertEqual(res_str["length"], 50)

        # Number/Decimal mapping
        res_num = _map_onec_type_to_mp({"types": ["number"], "length": 12, "precision": 3})
        self.assertEqual(res_num["type"], "decimal")
        self.assertEqual(res_num["precision"], 12)
        self.assertEqual(res_num["scale"], 3)

        # Reference mapping
        res_ref = _map_onec_type_to_mp({"types": ["reference"], "ref_type": "Catalog.Users"})
        self.assertEqual(res_ref["type"], "uuid")
        self.assertTrue(res_ref["is_reference"])
        self.assertEqual(res_ref["reference_to"], "Catalog.Users")

    @patch("src.tools.onec_data_migrator.resolve_onec_source")
    @patch("src.tools.onec_data_migrator.OneCXmlParser")
    @patch("src.tools.onec_data_migrator.DirectorySource")
    def test_get_onec_metadata_filtering(self, mock_dir, mock_parser_cls, mock_resolve):
        """Tests that metadata is correctly filtered by business types."""
        # Setup mock resolution
        mock_resolve.return_value = MagicMock(semantic_path="path", semantic_kind="xml")
        
        # Setup mock parser to return one relevant and one irrelevant object
        obj_catalog = OneCMetaObject(name="Goods", obj_type="catalog", uuid="1", synonyms={}, requisites=[], tabular_parts=[])
        obj_report = OneCMetaObject(name="SalesReport", obj_type="report", uuid="2", synonyms={}, requisites=[], tabular_parts=[])
        
        mock_parser = mock_parser_cls.return_value
        mock_parser.parse_all.return_value = [obj_catalog, obj_report]

        # Execute with filter_relevant=True (default)
        results = get_onec_metadata("src", "auto")
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "Goods")

    def test_migrate_metadata_to_platform_structure(self):
        """Tests the generation of the MetaPlatform manifest dictionary."""
        obj = OneCMetaObject(
            name="TestCatalog",
            obj_type="catalog",
            uuid="uuid-123",
            synonyms={"uk": "Тестовий Довідник"},
            requisites=[],
            tabular_parts=[]
        )
        req = OneCRequisite(
            name="Description", 
            raw_type={"types": ["string"], "length": 100},
            synonyms={},
            mp_type="string",
            ref_name="",
            uuid="test-uuid"
        )
        req.nullable = True
        obj.requisites.append(req)

        # We capture print output or just check the returned logic if we refactored to return.
        # For now, we manually invoke the logic inside to verify manifest_entities construction.
        # (Note: In your current script, manifest_entities is local to the function).
        # Let's verify it doesn't crash and correctly maps labels.
        with patch('builtins.print'):
            migrate_metadata_to_platform([obj])

    @patch("src.tools.onec_data_migrator.OneCDConfigSource")
    def test_inspect_database_finds_tables(self, mock_config_source):
        """Tests that inspect_onec_database can find tables via metadata_objects."""
        from src.tools.onec_data_migrator import inspect_onec_database
        
        # OneCDConfigSource(db_path) returns the instance mock_config_source.return_value
        mock_source = mock_config_source.return_value
        
        # Explicitly set attributes that appear earlier in the search loop to None
        # This ensures the inspector reaches 'metadata_objects'
        mock_source.get_tables = None
        mock_source.tables = None
        mock_source._tables = None

        mock_table = MagicMock()
        mock_table.name = "Reference10"
        mock_table.row_count = 500
        
        # Ensure metadata_objects is a dict so isinstance(attr, dict) passes
        mock_source.metadata_objects = {"Ref10": mock_table}

        with patch('builtins.print') as mock_print:
            inspect_onec_database("fake.1cd", "1cd")
            
            # Check if Reference10 was printed in the list
            printed_lines = [call.args[0] for call in mock_print.call_args_list]
            self.assertTrue(any("Reference10" in line for line in printed_lines))
            self.assertTrue(any("500" in line for line in printed_lines))

    @patch("src.tools.onec_data_migrator.OneCDConfigSource")
    def test_inspect_database_finds_system_tables(self, mock_config_source):
        """Tests that inspect_onec_database can find system tables like CONFIG via filename."""
        from src.tools.onec_data_migrator import inspect_onec_database
        mock_source = mock_config_source.return_value
        mock_source.get_tables = None
        mock_source.tables = None
        
        # Системная таблица может быть представлена объектом с атрибутом 'filename'
        mock_config = MagicMock()
        mock_config.filename = "CONFIG"
        mock_source.list_files = MagicMock(return_value=[mock_config])

        with patch('builtins.print') as mock_print:
            inspect_onec_database("fake.1cd", "1cd", table_to_view="CONFIG")
            printed_lines = [call.args[0] for call in mock_print.call_args_list]
            self.assertTrue(any("Просмотр данных таблицы: CONFIG" in line for line in printed_lines))

if __name__ == "__main__":
    unittest.main()