from pathlib import Path

import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QDialog

from src.configurator.configurator_app import _icon_provider_factory
from src.ui_qt.theme import set_app_icon


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def _qt_app_for_icon_tests():
    _ensure_app()
    yield


def _alpha_bounds(icon_kind: str, icon_type: str) -> tuple[int, int, int, int]:
    _ensure_app()
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")
    icon = provider({"kind": icon_kind, "type": icon_type, "name": "Sample", "payload": {}})
    pm = icon.pixmap(16, 16)
    image = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    xs: list[int] = []
    ys: list[int] = []
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 0:
                xs.append(x)
                ys.append(y)
    assert xs and ys
    return min(xs), min(ys), max(xs), max(ys)


def test_icon_provider_uses_schema_icons_for_virtual_schema_nodes() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    req_icon = provider(
        {
            "kind": "schema",
            "name": "Organization",
            "payload": {"section": "attributes", "schema_item_kind": "attribute"},
        }
    )
    table_icon = provider(
        {
            "kind": "schema",
            "name": "ReceivedAdvances",
            "payload": {"section": "tabular_parts", "schema_item_kind": "tabular_part"},
        }
    )

    assert not req_icon.isNull()
    assert not table_icon.isNull()


def test_icon_provider_uses_custom_subsystem_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    subsystem_icon = provider(
        {
            "kind": "object",
            "type": "subsystem",
            "name": "Sales",
            "payload": {},
        }
    )
    generic_object_icon = provider(
        {
            "kind": "object",
            "type": "document",
            "name": "SomeDocument",
            "payload": {},
        }
    )

    assert not subsystem_icon.isNull()
    assert not generic_object_icon.isNull()
    assert subsystem_icon.pixmap(16, 16).cacheKey() != generic_object_icon.pixmap(16, 16).cacheKey()


def test_custom_tree_icons_are_normalized_to_common_canvas() -> None:
    for icon_type in ("subsystem", "web_service", "http_service", "ws_link", "websocket_client"):
        left, top, right, bottom = _alpha_bounds("object", icon_type)
        assert left >= 1
        assert top >= 1
        assert right <= 14
        assert bottom <= 14


def test_icon_provider_uses_custom_common_module_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    common_module_icon = provider(
        {
            "kind": "object",
            "type": "common_module",
            "name": "CommonServer",
            "payload": {},
        }
    )
    document_icon = provider(
        {
            "kind": "object",
            "type": "document",
            "name": "SomeDocument",
            "payload": {},
        }
    )

    assert not common_module_icon.isNull()
    assert not document_icon.isNull()
    assert common_module_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()


def test_icon_provider_uses_custom_common_command_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    common_command_icon = provider(
        {
            "kind": "object",
            "type": "common_command",
            "name": "CloseForm",
            "payload": {},
        }
    )
    document_icon = provider(
        {
            "kind": "object",
            "type": "document",
            "name": "SomeDocument",
            "payload": {},
        }
    )

    assert not common_command_icon.isNull()
    assert not document_icon.isNull()
    assert common_command_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()


def test_icon_provider_uses_custom_common_form_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    common_form_icon = provider(
        {
            "kind": "object",
            "type": "common_form",
            "name": "SelectionForm",
            "payload": {},
        }
    )
    document_icon = provider(
        {
            "kind": "object",
            "type": "document",
            "name": "SomeDocument",
            "payload": {},
        }
    )

    assert not common_form_icon.isNull()
    assert not document_icon.isNull()
    assert common_form_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()


def test_icon_provider_uses_custom_common_layout_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    common_layout_icon = provider(
        {
            "kind": "object",
            "type": "common_layout",
            "name": "PrintTemplate",
            "payload": {},
        }
    )
    document_icon = provider(
        {
            "kind": "object",
            "type": "document",
            "name": "SomeDocument",
            "payload": {},
        }
    )

    assert not common_layout_icon.isNull()
    assert not document_icon.isNull()
    assert common_layout_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()


def test_icon_provider_uses_custom_common_picture_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    common_picture_icon = provider(
        {
            "kind": "object",
            "type": "common_picture",
            "name": "Logo",
            "payload": {},
        }
    )
    document_icon = provider(
        {
            "kind": "object",
            "type": "document",
            "name": "SomeDocument",
            "payload": {},
        }
    )

    assert not common_picture_icon.isNull()
    assert not document_icon.isNull()
    assert common_picture_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()


def test_icon_provider_uses_custom_xdto_package_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    xdto_package_icon = provider(
        {
            "kind": "object",
            "type": "xdto_package",
            "name": "IntegrationSchema",
            "payload": {},
        }
    )
    document_icon = provider(
        {
            "kind": "object",
            "type": "document",
            "name": "SomeDocument",
            "payload": {},
        }
    )

    assert not xdto_package_icon.isNull()
    assert not document_icon.isNull()
    assert xdto_package_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()


def test_icon_provider_uses_custom_web_service_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    web_service_icon = provider(
        {
            "kind": "object",
            "type": "web_service",
            "name": "CatalogSyncService",
            "payload": {},
        }
    )
    document_icon = provider(
        {
            "kind": "object",
            "type": "document",
            "name": "SomeDocument",
            "payload": {},
        }
    )

    assert not web_service_icon.isNull()
    assert not document_icon.isNull()
    assert web_service_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()


def test_set_app_icon_applies_to_new_top_level_dialogs() -> None:
    app = _ensure_app()
    set_app_icon(app)

    dialog = QDialog()
    dialog.setWindowTitle("Icon probe")
    dialog.show()
    app.processEvents()

    assert not dialog.windowIcon().isNull()
    dialog.close()


def test_icon_provider_uses_custom_http_service_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    http_service_icon = provider(
        {
            "kind": "object",
            "type": "http_service",
            "name": "HttpCatalogSyncService",
            "payload": {},
        }
    )
    document_icon = provider(
        {
            "kind": "object",
            "type": "document",
            "name": "SomeDocument",
            "payload": {},
        }
    )

    assert not http_service_icon.isNull()
    assert not document_icon.isNull()
    assert http_service_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()


def test_icon_provider_uses_custom_ws_link_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    ws_link_icon = provider(
        {
            "kind": "object",
            "type": "ws_link",
            "name": "OrderStatusWsReference",
            "payload": {},
        }
    )
    document_icon = provider(
        {
            "kind": "object",
            "type": "document",
            "name": "SomeDocument",
            "payload": {},
        }
    )

    assert not ws_link_icon.isNull()
    assert not document_icon.isNull()
    assert ws_link_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()


def test_icon_provider_uses_custom_websocket_client_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    websocket_client_icon = provider(
        {
            "kind": "object",
            "type": "websocket_client",
            "name": "RealtimeClient",
            "payload": {},
        }
    )
    document_icon = provider(
        {
            "kind": "object",
            "type": "document",
            "name": "SomeDocument",
            "payload": {},
        }
    )

    assert not websocket_client_icon.isNull()
    assert not document_icon.isNull()
    assert websocket_client_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()


def test_icon_provider_uses_custom_integration_service_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    integration_service_icon = provider(
        {
            "kind": "object",
            "type": "integration_service",
            "name": "MarketplaceSync",
            "payload": {},
        }
    )
    document_icon = provider(
        {
            "kind": "object",
            "type": "document",
            "name": "SomeDocument",
            "payload": {},
        }
    )

    assert not integration_service_icon.isNull()
    assert not document_icon.isNull()
    assert integration_service_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()


def test_icon_provider_uses_custom_style_element_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    style_element_icon = provider(
        {
            "kind": "object",
            "type": "style_element",
            "name": "PrimaryAccent",
            "payload": {},
        }
    )
    document_icon = provider(
        {
            "kind": "object",
            "type": "document",
            "name": "SomeDocument",
            "payload": {},
        }
    )

    assert not style_element_icon.isNull()
    assert not document_icon.isNull()
    assert style_element_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()


def test_icon_provider_uses_custom_style_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    style_icon = provider(
        {
            "kind": "object",
            "type": "style",
            "name": "CorporateStyle",
            "payload": {},
        }
    )
    document_icon = provider(
        {
            "kind": "object",
            "type": "document",
            "name": "SomeDocument",
            "payload": {},
        }
    )

    assert not style_icon.isNull()
    assert not document_icon.isNull()
    assert style_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()


def test_icon_provider_uses_custom_session_param_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    session_param_icon = provider(
        {
            "kind": "object",
            "type": "session_param",
            "name": "CurrentUser",
            "payload": {},
        }
    )
    document_icon = provider(
        {
            "kind": "object",
            "type": "document",
            "name": "SomeDocument",
            "payload": {},
        }
    )

    assert not session_param_icon.isNull()
    assert not document_icon.isNull()
    assert session_param_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()


def test_icon_provider_uses_custom_constants_icon_and_key_round_for_roles() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    constants_icon = provider(
        {
            "kind": "group",
            "type": "constants",
            "name": "constants",
            "payload": {},
        }
    )
    role_icon = provider(
        {
            "kind": "object",
            "type": "role",
            "name": "Admin",
            "payload": {},
        }
    )
    document_icon = provider(
        {
            "kind": "object",
            "type": "document",
            "name": "SomeDocument",
            "payload": {},
        }
    )

    assert not constants_icon.isNull()
    assert not role_icon.isNull()
    assert not document_icon.isNull()
    assert constants_icon.pixmap(16, 16).cacheKey() != role_icon.pixmap(16, 16).cacheKey()
    assert role_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()


def test_icon_provider_tints_custom_constants_icon_light() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    constants_icon = provider(
        {
            "kind": "group",
            "type": "constants",
            "name": "constants",
            "payload": {},
        }
    )

    assert not constants_icon.isNull()

    img = constants_icon.pixmap(16, 16).toImage()
    rgb_samples = []
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() > 0:
                rgb_samples.append((c.red(), c.green(), c.blue()))

    assert rgb_samples
    assert max(max(rgb) for rgb in rgb_samples) >= 190
    avg_channel = sum(sum(rgb) for rgb in rgb_samples) / (len(rgb_samples) * 3)
    assert avg_channel >= 170


def test_icon_provider_uses_requisite_icon_for_common_attributes() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    common_attribute_icon = provider(
        {
            "kind": "object",
            "type": "common_attribute",
            "name": "DataArea",
            "payload": {},
        }
    )
    schema_attribute_icon = provider(
        {
            "kind": "schema",
            "name": "Organization",
            "payload": {"section": "attributes", "schema_item_kind": "attribute"},
        }
    )

    assert not common_attribute_icon.isNull()
    assert not schema_attribute_icon.isNull()
    assert common_attribute_icon.pixmap(16, 16).cacheKey() == schema_attribute_icon.pixmap(16, 16).cacheKey()


def test_icon_provider_uses_custom_settings_storage_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    settings_storage_icon = provider(
        {
            "kind": "object",
            "type": "settings_storage",
            "name": "UserSettings",
            "payload": {},
        }
    )
    document_icon = provider(
        {
            "kind": "object",
            "type": "document",
            "name": "SomeDocument",
            "payload": {},
        }
    )

    assert not settings_storage_icon.isNull()
    assert not document_icon.isNull()
    assert settings_storage_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()


def test_icon_provider_uses_custom_exchange_plan_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    exchange_plan_icon = provider(
        {
            "kind": "object",
            "type": "exchange_plan",
            "name": "SyncPlan",
            "payload": {},
        }
    )
    document_icon = provider(
        {
            "kind": "object",
            "type": "document",
            "name": "SomeDocument",
            "payload": {},
        }
    )

    assert not exchange_plan_icon.isNull()
    assert not document_icon.isNull()
    assert exchange_plan_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()


def test_icon_provider_uses_custom_sequence_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    sequence_icon = provider(
        {
            "kind": "object",
            "type": "sequence",
            "name": "DocumentsOrder",
            "payload": {},
        }
    )
    document_icon = provider({"kind": "object", "type": "document", "name": "Doc", "payload": {}})

    assert not sequence_icon.isNull()
    assert not document_icon.isNull()
    assert sequence_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()


def test_icon_provider_uses_custom_document_numerator_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    document_numerator_icon = provider(
        {
            "kind": "object",
            "type": "document_numerator",
            "name": "InvoiceNumbers",
            "payload": {},
        }
    )
    document_icon = provider(
        {
            "kind": "object",
            "type": "document",
            "name": "SomeDocument",
            "payload": {},
        }
    )

    assert not document_numerator_icon.isNull()
    assert not document_icon.isNull()
    assert document_numerator_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()


def test_icon_provider_uses_custom_bot_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    bot_icon = provider(
        {
            "kind": "object",
            "type": "bot",
            "name": "AssistantBot",
            "payload": {},
        }
    )
    document_icon = provider(
        {
            "kind": "object",
            "type": "document",
            "name": "SomeDocument",
            "payload": {},
        }
    )

    assert not bot_icon.isNull()
    assert not document_icon.isNull()
    assert bot_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()


def test_icon_provider_uses_custom_scheduled_job_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    scheduled_job_icon = provider(
        {
            "kind": "object",
            "type": "scheduled_job",
            "name": "NightlySync",
            "payload": {},
        }
    )
    document_icon = provider(
        {
            "kind": "object",
            "type": "document",
            "name": "SomeDocument",
            "payload": {},
        }
    )

    assert not scheduled_job_icon.isNull()
    assert not document_icon.isNull()
    assert scheduled_job_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()


def test_icon_provider_uses_custom_event_subscription_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    event_subscription_icon = provider(
        {
            "kind": "object",
            "type": "event_subscription",
            "name": "OnPost",
            "payload": {},
        }
    )
    document_icon = provider({"kind": "object", "type": "document", "name": "Doc", "payload": {}})

    assert not event_subscription_icon.isNull()
    assert not document_icon.isNull()
    assert event_subscription_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()


def test_icon_provider_uses_custom_selection_criterion_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    selection_criterion_icon = provider(
        {
            "kind": "object",
            "type": "selection_criterion",
            "name": "ByCustomer",
            "payload": {},
        }
    )
    document_icon = provider(
        {
            "kind": "object",
            "type": "document",
            "name": "SomeDocument",
            "payload": {},
        }
    )

    assert not selection_criterion_icon.isNull()
    assert not document_icon.isNull()
    assert selection_criterion_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()


def test_icon_provider_uses_custom_command_group_icon() -> None:
    provider = _icon_provider_factory(Path(__file__).resolve().parents[1] / "configurator")

    command_group_icon = provider(
        {
            "kind": "object",
            "type": "command_group",
            "name": "UIActions",
            "payload": {},
        }
    )
    document_icon = provider(
        {
            "kind": "object",
            "type": "document",
            "name": "SomeDocument",
            "payload": {},
        }
    )

    assert not command_group_icon.isNull()
    assert not document_icon.isNull()
    assert command_group_icon.pixmap(16, 16).cacheKey() != document_icon.pixmap(16, 16).cacheKey()
