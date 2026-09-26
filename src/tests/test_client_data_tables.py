from src.client.data_tables import data_table_name, infer_data_table_name


def test_data_table_name_uses_document_prefix_for_documents() -> None:
    assert data_table_name("document", "AdvanceReport") == "data_document_advancereport"


def test_data_table_name_uses_catalog_prefix_for_non_documents() -> None:
    assert data_table_name("catalog", "Partners") == "data_catalog_partners"
    assert data_table_name("report", "Sales") == "data_catalog_sales"
    assert data_table_name("chart_of_accounts", "Main") == "data_catalog_main"


def test_data_table_name_uses_document_prefix_for_document_like_objects() -> None:
    assert data_table_name("business_process", "Approval") == "data_document_approval"
    assert data_table_name("task", "ApproveInvoice") == "data_document_approveinvoice"


def test_infer_data_table_name_uses_date_field_as_document_marker() -> None:
    assert infer_data_table_name("AdvanceReport", {"_date": "2026-03-09"}) == "data_document_advancereport"
    assert infer_data_table_name("Partners", {"name": "Test"}) == "data_catalog_partners"
    assert infer_data_table_name("Approval", {"_number_prefix": "BP"}) == "data_document_approval"
