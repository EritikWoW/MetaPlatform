import os
import sys
import argparse
from pathlib import Path

from src.platform.locale_detect import detect_system_lang
from src.platform.logging_setup import setup_logging
from src.ui_qt.i18n import init_i18n, t

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon, QPixmap

from src.ui_qt.splash import AppSplash
from src.ui_qt.theme import apply_hybrid_theme, set_app_icon
from .configurator_window import ConfiguratorWindow
from src.ui_qt.viewmodels.configurator_vm import ConfiguratorViewModel
from .configurator_controller import (
    SvgIconPack,
    SvgIconPackConfig,
    _find_icons_dir,
    _render_custom_svg_icon,
    ConfiguratorController,  # legacy (kept for reference)
)


def _resolve_runtime_and_uid() -> tuple[str, str]:
    """Read META_RUNTIME_URL and META_DB_UID from environment."""
    url = os.environ.get("META_RUNTIME_URL", "").strip()
    uid = os.environ.get("META_DB_UID", "").strip()
    return url, uid


def _resolve_db_path() -> str:
    """Read META_DB_PATH from environment."""
    return os.environ.get("META_DB_PATH", "").strip()


def _icon_provider_factory(here: Path):
    icons_dir = _find_icons_dir(here)
    icons = SvgIconPack(icons_dir, SvgIconPackConfig(size_px=16, color_hex="#C8D0DA"))
    schema_icons_dir = here.parent / "ui_qt" / "assets" / "icons"
    schema_req_icon = _render_custom_svg_icon(schema_icons_dir / "schema_requisite.svg")
    schema_table_icon = _render_custom_svg_icon(schema_icons_dir / "schema_table.svg")
    subsystem_icon = _render_custom_svg_icon(schema_icons_dir / "subsystem.svg")
    common_module_icon = _render_custom_svg_icon(schema_icons_dir / "common_module.svg")
    common_command_icon = _render_custom_svg_icon(schema_icons_dir / "common_command.svg")
    common_form_icon = _render_custom_svg_icon(schema_icons_dir / "common_form.svg")
    common_layout_icon = _render_custom_svg_icon(schema_icons_dir / "common_layout.svg")
    common_picture_icon = _render_custom_svg_icon(schema_icons_dir / "common_picture.svg")
    xdto_package_icon = _render_custom_svg_icon(schema_icons_dir / "xdto_package.svg")
    web_service_icon = _render_custom_svg_icon(schema_icons_dir / "web_service.svg")
    http_service_icon = _render_custom_svg_icon(schema_icons_dir / "http_service.svg")
    ws_link_icon = _render_custom_svg_icon(schema_icons_dir / "ws_link.svg")
    websocket_client_icon = _render_custom_svg_icon(schema_icons_dir / "websocket_client.svg")
    integration_service_icon = _render_custom_svg_icon(schema_icons_dir / "integration_service.svg")
    style_element_icon = _render_custom_svg_icon(schema_icons_dir / "style_element.svg")
    style_icon = _render_custom_svg_icon(schema_icons_dir / "style.svg")
    session_param_icon = _render_custom_svg_icon(schema_icons_dir / "session_param.svg")
    constants_icon = _render_custom_svg_icon(schema_icons_dir / "constants.svg")
    settings_storage_icon = _render_custom_svg_icon(schema_icons_dir / "settings_storage.svg")
    exchange_plan_icon = _render_custom_svg_icon(schema_icons_dir / "exchange_plan.svg")
    sequence_icon = _render_custom_svg_icon(schema_icons_dir / "sequence.svg")
    document_numerator_icon = _render_custom_svg_icon(schema_icons_dir / "document_numerator.svg")
    bot_icon = _render_custom_svg_icon(schema_icons_dir / "bot.svg")
    scheduled_job_icon = _render_custom_svg_icon(schema_icons_dir / "scheduled_job.svg")
    event_subscription_icon = _render_custom_svg_icon(schema_icons_dir / "event_subscription.svg")
    selection_criterion_icon = _render_custom_svg_icon(schema_icons_dir / "selection_criterion.svg")
    command_group_icon = _render_custom_svg_icon(schema_icons_dir / "command_group.svg")

    def icon_provider(meta: dict):
        kind = str(meta.get("kind") or "object")
        payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
        if kind == "schema":
            section = str(payload.get("section") or meta.get("name") or "").strip().lower()
            schema_item_kind = str(payload.get("schema_item_kind") or "").strip().lower()
            if schema_item_kind in ("requisite", "attribute", "column") or section == "attributes":
                return schema_req_icon
            if schema_item_kind == "tabular_part" or section == "tabular_parts":
                return schema_table_icon
        if kind in ("root", "group"):
            tp   = str(meta.get("type") or "")
            name = (tp or "configuration").strip() or "configuration"
            if tp == "constants":
                return constants_icon
            return icons.icon(ConfiguratorController.ICON_MAP.get(name, name))
        if kind == "folder":
            nm = str(meta.get("name") or "folder")
            if nm == "subsystems":
                return subsystem_icon
            if nm == "common_modules":
                return common_module_icon
            if nm == "common_commands":
                return common_command_icon
            if nm == "common_forms":
                return common_form_icon
            if nm == "common_layouts":
                return common_layout_icon
            if nm == "common_pictures":
                return common_picture_icon
            if nm == "xdto_packages":
                return xdto_package_icon
            if nm == "web_services":
                return web_service_icon
            if nm == "http_services":
                return http_service_icon
            if nm == "ws_links":
                return ws_link_icon
            if nm == "websocket_clients":
                return websocket_client_icon
            if nm == "integration_services":
                return integration_service_icon
            if nm == "style_elements":
                return style_element_icon
            if nm == "styles":
                return style_icon
            if nm == "session_params":
                return session_param_icon
            if nm == "common_attributes":
                return schema_req_icon
            if nm == "settings_storages":
                return settings_storage_icon
            if nm == "exchange_plans":
                return exchange_plan_icon
            if nm == "sequences":
                return sequence_icon
            if nm == "document_numerators":
                return document_numerator_icon
            if nm == "bots":
                return bot_icon
            if nm == "scheduled_jobs":
                return scheduled_job_icon
            if nm == "event_subscriptions":
                return event_subscription_icon
            if nm == "selection_criteria":
                return selection_criterion_icon
            if nm == "command_groups":
                return command_group_icon
            return icons.icon(ConfiguratorController.ICON_MAP.get(nm, nm))
        if kind == "object":
            tp = str(meta.get("type") or "object")
            if tp == "subsystem":
                return subsystem_icon
            if tp == "common_module":
                return common_module_icon
            if tp in ("common_command", "common_commands"):
                return common_command_icon
            if tp in ("common_form", "common_forms"):
                return common_form_icon
            if tp in ("common_layout", "common_layouts"):
                return common_layout_icon
            if tp in ("common_picture", "common_pictures"):
                return common_picture_icon
            if tp in ("xdto_package", "xdto_packages"):
                return xdto_package_icon
            if tp in ("web_service", "web_services"):
                return web_service_icon
            if tp in ("http_service", "http_services"):
                return http_service_icon
            if tp in ("ws_link", "ws_links", "ws_reference", "ws_references"):
                return ws_link_icon
            if tp in ("websocket_client", "websocket_clients"):
                return websocket_client_icon
            if tp in ("integration_service", "integration_services"):
                return integration_service_icon
            if tp in ("style_element", "style_elements"):
                return style_element_icon
            if tp in ("style", "styles"):
                return style_icon
            if tp in ("session_param", "session_params"):
                return session_param_icon
            if tp in ("common_attribute", "common_attributes"):
                return schema_req_icon
            if tp in ("settings_storage", "settings_storages"):
                return settings_storage_icon
            if tp in ("exchange_plan", "exchange_plans"):
                return exchange_plan_icon
            if tp in ("sequence", "sequences"):
                return sequence_icon
            if tp in ("document_numerator", "document_numerators"):
                return document_numerator_icon
            if tp in ("bot", "bots"):
                return bot_icon
            if tp in ("scheduled_job", "scheduled_jobs"):
                return scheduled_job_icon
            if tp in ("event_subscription", "event_subscriptions"):
                return event_subscription_icon
            if tp in ("selection_criterion", "selection_criteria"):
                return selection_criterion_icon
            if tp in ("command_group", "command_groups"):
                return command_group_icon
            if tp == "constants":
                return constants_icon
            return icons.icon(ConfiguratorController.ICON_MAP.get(tp, tp))
        return icons.icon("file")

    return icon_provider



def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--runtime", dest="runtime", default="",
                   help="Runtime server URL, e.g. http://127.0.0.1:8765")
    p.add_argument("--db-uid", dest="db_uid", default="",
                   help="Database UID as registered on the runtime server")
    p.add_argument("--db-path", dest="db_path", default="",
                   help="Local database path (.1CD/mpdb) to open through runtime")
    p.add_argument("--control-api-port", dest="control_api_port", type=int, default=8766,
                   help="Local configurator control API port on 127.0.0.1")
    p.add_argument("--control-api-host", dest="control_api_host", default="127.0.0.1",
                   help="Local configurator control API host")
    args = p.parse_args()

    runtime_url = args.runtime.strip() or os.environ.get("META_RUNTIME_URL", "").strip()
    db_uid      = args.db_uid.strip()  or os.environ.get("META_DB_UID",      "").strip()
    db_path     = args.db_path.strip() or _resolve_db_path()
    control_api_host = str(args.control_api_host or os.environ.get("META_CONTROL_API_HOST", "127.0.0.1")).strip() or "127.0.0.1"
    try:
        control_api_port = int(args.control_api_port or int(os.environ.get("META_CONTROL_API_PORT", "8766")))
    except Exception:
        control_api_port = 8766
    os.environ["META_CONTROL_API_HOST"] = control_api_host
    os.environ["META_CONTROL_API_PORT"] = str(int(control_api_port))

    if not runtime_url:
        # Legacy fallback for direct-launch during development
        p.error(
            "Provide --runtime <url> or set META_RUNTIME_URL in the environment"
        )

    app = QApplication(sys.argv)
    setup_logging(detect_system_lang())
    init_i18n(default_lang=detect_system_lang())
    app.setQuitOnLastWindowClosed(True)
    apply_hybrid_theme(app)
    set_app_icon(app)

    logo_path = Path(__file__).resolve().parents[1] / "assets" / "logo.jpg"
    pm = QPixmap(str(logo_path))
    pm = pm.scaled(QSize(640, 360), Qt.AspectRatioMode.KeepAspectRatio,
                   Qt.TransformationMode.SmoothTransformation)
    splash = AppSplash(pm)
    splash.show()
    splash.set_progress(4, t("startup_launching"))

    splash.set_progress(12, t("startup_shell"))
    view = ConfiguratorWindow(runtime_url=runtime_url, db_uid=db_uid)
    try:
        view.destroyed.connect(app.quit)
    except Exception:
        pass

    here = Path(__file__).resolve()
    icon_provider = _icon_provider_factory(here.parent)

    vm = ConfiguratorViewModel(
        runtime_url,
        db_uid,
        dialogs=view,
        icon_provider=icon_provider,
        db_path=db_path,
        startup_progress_cb=splash.set_progress,
        eager_runtime_refresh=True,
    )

    splash.set_progress(90, t("startup_bind_ui"))
    view.bind(vm)
    try:
        from .control_api import start_control_api

        start_control_api(view, vm, host=control_api_host, port=control_api_port)
    except Exception as exc:
        print(f"[control] disabled: {type(exc).__name__}: {exc}", flush=True)
    view.end_tree_rebuild()
    view.expand_default()

    splash.set_progress(96, t("startup_restore_workspace"))
    view.show()
    app.processEvents()
    splash.set_progress(100, t("startup_ready"))
    splash.finish(view)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
