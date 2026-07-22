from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Callable

from PySide6.QtCore import QObject, Qt, QSize, QElapsedTimer, QRectF
from PySide6.QtGui import QIcon, QPainter, QPixmap, QStandardItem, QColor, QImage
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QMenu, QStyle, QApplication

from src.ui_qt.i18n import t
from src.core.object_policies import section_i18n_key
from src.ui_qt.services.tree_builder import build_tree_model, prepare_tree_objects
from src.ui_qt.services.icon_provider import IconProvider

from .configurator_window import ConfiguratorWindow, NodeInfo
from .manifest_schema import ManifestObject
from .application.service import ConfiguratorService
# ------------------------------------------------------------
def _find_project_root(start: Path) -> Path:
    p = start.resolve()
    for _ in range(12):
        if (p / "src" / "assets").exists():
            return p
        if (p / "assets").exists():
            return p
        if p.parent == p:
            break
        p = p.parent
    return start.resolve()


def _find_icons_dir(start: Path) -> Path:
    candidates: list[Path] = []
    p = start.resolve()
    for _ in range(14):
        candidates.extend(
            [
                p / "src" / "assets" / "icons" / "svg",
                p / "assets" / "icons" / "svg",
                p / ".." / "src" / "assets" / "icons" / "svg",
                p / ".." / "assets" / "icons" / "svg",
            ]
        )
        if p.parent == p:
            break
        p = p.parent

    for c in candidates:
        try:
            if c.exists() and c.is_dir():
                return c.resolve()
        except Exception:
            continue

    root = _find_project_root(start)
    return (root / "src" / "assets" / "icons" / "svg").resolve()


# ------------------------------------------------------------
# SVG icon pack (Lucide)
# ------------------------------------------------------------
@dataclass(frozen=True)
class SvgIconPackConfig:
    size_px: int = 16
    color_hex: str = "#C8D0DA"


class SvgIconPack:
    """Render SVG icons to QIcon with fixed size, with currentColor replacement."""

    def __init__(self, base_dir: Path, cfg: SvgIconPackConfig | None = None) -> None:
        self.base_dir = base_dir
        self.cfg = cfg or SvgIconPackConfig()
        self._cache: Dict[tuple[str, int, str], QIcon] = {}

    def _svg_bytes(self, name: str, color_hex: str) -> Optional[bytes]:
        fname = name if name.lower().endswith(".svg") else f"{name}.svg"
        p = self.base_dir / fname
        if not p.exists():
            return None
        data = p.read_bytes()
        if b"currentColor" in data:
            data = data.replace(b"currentColor", color_hex.encode("utf-8"))
        return data

    def icon(self, name: str, *, size_px: Optional[int] = None, color_hex: Optional[str] = None) -> QIcon:
        size = int(size_px or self.cfg.size_px)
        color = (color_hex or self.cfg.color_hex).strip() or self.cfg.color_hex
        key = (name, size, color)
        if key in self._cache:
            return self._cache[key]

        svg = self._svg_bytes(name, color)
        if not svg:
            ic = QIcon()
            self._cache[key] = ic
            return ic

        renderer = QSvgRenderer(svg)
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        renderer.render(p)
        p.end()

        ic = QIcon(pm)
        self._cache[key] = ic
        return ic


def _alpha_bounding_rect(image: QImage) -> Optional[tuple[int, int, int, int]]:
    xs: list[int] = []
    ys: list[int] = []
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 0:
                xs.append(x)
                ys.append(y)
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _fit_rect_into_square(src_w: float, src_h: float, *, size_px: int, padding_px: int) -> QRectF:
    inner = max(1.0, float(size_px - (padding_px * 2)))
    if src_w <= 0 or src_h <= 0:
        return QRectF(float(padding_px), float(padding_px), inner, inner)
    scale = min(inner / float(src_w), inner / float(src_h))
    w = max(1.0, float(src_w) * scale)
    h = max(1.0, float(src_h) * scale)
    x = (float(size_px) - w) / 2.0
    y = (float(size_px) - h) / 2.0
    return QRectF(x, y, w, h)


def _normalize_custom_icon_pixmap(pm: QPixmap, *, size_px: int, padding_px: int = 1) -> QPixmap:
    image = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    bounds = _alpha_bounding_rect(image)
    if not bounds:
        return pm

    x0, y0, x1, y1 = bounds
    cropped = pm.copy(x0, y0, (x1 - x0) + 1, (y1 - y0) + 1)
    target_rect = _fit_rect_into_square(
        cropped.width(),
        cropped.height(),
        size_px=size_px,
        padding_px=padding_px,
    )

    normalized = QPixmap(size_px, size_px)
    normalized.fill(Qt.GlobalColor.transparent)
    painter = QPainter(normalized)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.drawPixmap(target_rect, cropped, QRectF(cropped.rect()))
    painter.end()
    return normalized


def _render_custom_svg_icon(path: Path, *, size_px: int = 16, color_hex: str = "#C8D0DA") -> QIcon:
    """Render a project-local SVG icon with a forced monochrome tint.

    User-provided SVG assets often come with hardcoded black fills/strokes.
    Tree icons are shown on a dark background, so load-time recoloring is
    required to keep custom assets visually consistent with the Lucide pack.
    """

    try:
        data = path.read_bytes()
    except Exception:
        return QIcon()

    color = color_hex.encode("utf-8")
    for needle in (
        b"currentColor",
        b"#000000",
        b"#000000ff",
        b"#000",
        b"fill:#000000",
        b"fill:#000000ff",
        b"fill:#000",
        b"stroke:#000000",
        b"stroke:#000000ff",
        b"stroke:#000",
        b'fill="#000000"',
        b'fill="#000000ff"',
        b'fill="#000"',
        b'stroke="#000000"',
        b'stroke="#000000ff"',
        b'stroke="#000"',
    ):
        data = data.replace(needle, color)

    renderer = QSvgRenderer(data)
    render_size = max(64, size_px * 4)
    pm = QPixmap(render_size, render_size)
    pm.fill(Qt.GlobalColor.transparent)

    view_box = renderer.viewBoxF()
    if not view_box.isValid() or view_box.width() <= 0 or view_box.height() <= 0:
        default_size = renderer.defaultSize()
        view_w = float(default_size.width() or 1)
        view_h = float(default_size.height() or 1)
    else:
        view_w = float(view_box.width())
        view_h = float(view_box.height())
    target_rect = _fit_rect_into_square(view_w, view_h, size_px=render_size, padding_px=4)

    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter, target_rect)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pm.rect(), QColor(color_hex))
    painter.end()
    return QIcon(_normalize_custom_icon_pixmap(pm, size_px=size_px))


# ------------------------------------------------------------
# Controller
# ------------------------------------------------------------
class ConfiguratorController(QObject):
    """Связка View (ConfiguratorWindow) <-> manifest в mpdb."""

    AUTO_TITLE_PREFIX: Dict[str, str] = {
        "catalog": "Справочник",
        "document": "Документ",
        "report": "Отчет",
        "data_processor": "Обработка",
        "register_info": "РегистрСведений",
        "register_accum": "РегистрНакопления",
        "register_accounting": "РегистрБухгалтерии",
        "register_calc": "РегистрРасчета",
        "journal": "ЖурналДокументов",
        "enumeration": "Перечисление",
        "constants": "Константы",
        "business_process": "БизнесПроцесс",
        "task": "Задача",
        "external_sources": "ИсточникДанных",
        "common": "Объект",
    }

    AUTO_CODE_PREFIX: Dict[str, str] = {
        "catalog": "catalog",
        "document": "document",
        "report": "report",
        "data_processor": "data_processor",
        "register_info": "register_info",
        "register_accum": "register_accum",
        "register_accounting": "register_accounting",
        "register_calc": "register_calc",
        "journal": "journal",
        "enumeration": "enumeration",
        "constants": "constants",
        "business_process": "business_process",
        "task": "task",
        "external_sources": "external_sources",
        "common": "common",
    }

    ICON_MAP: Dict[str, str] = {
        # root / groups
        "configuration": "boxes",
        "common": "settings",
        "constants": "key-round",
        "role": "key-round",
        "roles": "key-round",
        "catalog": "book-open",
        "document": "file-text",
        "journal": "notebook-text",
        "enumeration": "list-ordered",
        "report": "bar-chart-3",
        "data_processor": "wrench",
        "chart_of_characteristic_types": "sliders-horizontal",
        "chart_of_accounts": "calculator",
        "chart_of_calculation_types": "sigma",
        "register_info": "database",
        "register_accum": "database",
        "register_accounting": "landmark",
        "register_calc": "sigma",
        "business_process": "workflow",
        "task": "check-square",
        "external_sources": "plug",
        # standard folders inside objects
        "attributes": "badge-check",
        "tabular_sections": "table",
        "dimensions": "ruler",
        "resources": "layers",
        "forms": "layout-template",
        "commands": "terminal",
        "layouts": "panel-top",
        # generic
        "folder": "folder",
        "object": "file",
    }

    def __init__(
        self,
        view: ConfiguratorWindow,
        db_path: Path,
        progress_cb: Optional[Callable[[int, str], None]] = None,
    ) -> None:
        super().__init__(view)

        self.view = view
        self.db_path = db_path
        self._progress_cb = progress_cb

        self._search: str = ""
        self._building: bool = False

        # throttle for UI updates (splash/progress)
        self._ui_timer = QElapsedTimer()
        self._ui_timer.start()

        # 1) Open DB
        self._progress(5, "Открываю базу…")
        self._service = ConfiguratorService()
        res = self._service.open_db("", db_path=str(db_path), seed_defaults_if_empty=True)
        self.db = res.db

        # 2) Manifest
        self._progress(20, "Готовлю конфигурацию…")
        # Важно: при подключении существующей БД конфигуратор не должен
        # повторно создавать системные ветки (это приводит к дублированию в UI
        # на старых базах). Seed выполняем только если manifest пустой.
        # 3) Icons
        here = Path(__file__).resolve()
        icons_dir = _find_icons_dir(here.parent)
        self.icons = SvgIconPack(icons_dir, SvgIconPackConfig(size_px=16, color_hex="#C8D0DA"))
        schema_icons_dir = here.parents[1] / "ui_qt" / "assets" / "icons"
        self._schema_req_icon = _render_custom_svg_icon(schema_icons_dir / "schema_requisite.svg")
        self._schema_table_icon = _render_custom_svg_icon(schema_icons_dir / "schema_table.svg")
        self._subsystem_icon = _render_custom_svg_icon(schema_icons_dir / "subsystem.svg")
        self._common_module_icon = _render_custom_svg_icon(schema_icons_dir / "common_module.svg")
        self._common_command_icon = _render_custom_svg_icon(schema_icons_dir / "common_command.svg")
        self._common_form_icon = _render_custom_svg_icon(schema_icons_dir / "common_form.svg")
        self._common_layout_icon = _render_custom_svg_icon(schema_icons_dir / "common_layout.svg")
        self._common_picture_icon = _render_custom_svg_icon(schema_icons_dir / "common_picture.svg")
        self._xdto_package_icon = _render_custom_svg_icon(schema_icons_dir / "xdto_package.svg")
        self._web_service_icon = _render_custom_svg_icon(schema_icons_dir / "web_service.svg")
        self._http_service_icon = _render_custom_svg_icon(schema_icons_dir / "http_service.svg")
        self._ws_link_icon = _render_custom_svg_icon(schema_icons_dir / "ws_link.svg")
        self._websocket_client_icon = _render_custom_svg_icon(schema_icons_dir / "websocket_client.svg")
        self._integration_service_icon = _render_custom_svg_icon(schema_icons_dir / "integration_service.svg")
        self._style_element_icon = _render_custom_svg_icon(schema_icons_dir / "style_element.svg")
        self._style_icon = _render_custom_svg_icon(schema_icons_dir / "style.svg")
        self._session_param_icon = _render_custom_svg_icon(schema_icons_dir / "session_param.svg")
        self._constants_icon = _render_custom_svg_icon(schema_icons_dir / "constants.svg")
        self._settings_storage_icon = _render_custom_svg_icon(schema_icons_dir / "settings_storage.svg")
        self._exchange_plan_icon = _render_custom_svg_icon(schema_icons_dir / "exchange_plan.svg")
        self._sequence_icon = _render_custom_svg_icon(schema_icons_dir / "sequence.svg")
        self._document_numerator_icon = _render_custom_svg_icon(schema_icons_dir / "document_numerator.svg")
        self._bot_icon = _render_custom_svg_icon(schema_icons_dir / "bot.svg")
        self._scheduled_job_icon = _render_custom_svg_icon(schema_icons_dir / "scheduled_job.svg")
        self._event_subscription_icon = _render_custom_svg_icon(schema_icons_dir / "event_subscription.svg")
        self._selection_criterion_icon = _render_custom_svg_icon(schema_icons_dir / "selection_criterion.svg")
        self._command_group_icon = _render_custom_svg_icon(schema_icons_dir / "command_group.svg")
        try:
            self.view.tree.setIconSize(QSize(16, 16))
        except Exception:
            pass

        # Стабилизация: единый источник иконок для дерева.
        # Алгоритм выбора конкретной иконки по meta остаётся в _icon_for_node,
        # но VM и Controller обращаются к нему через общий IconProvider.
        self.icon_provider = IconProvider(palette_provider=None, tree_icon_provider=self._icon_for_node)

        # 4) Close DB when window closes
        try:
            self.view.destroyed.connect(lambda: self.db.close())
        except Exception:
            pass

        # 5) Hooks
        self.view.refreshRequested.connect(self.reload)
        self.view.saveRequested.connect(self.on_save)
        self.view.checkRequested.connect(self.on_check)
        self.view.searchChanged.connect(self.on_search)
        self.view.treeOpenRequested.connect(self.on_open_object)
        self.view.treeSelectChanged.connect(self.on_select)
        self.view.treeContextMenuRequested.connect(self.on_tree_context_menu)
        self.view.itemRenamed.connect(self.on_item_renamed)

        # 6) First load
        self._progress(35, "Читаю объекты…")
        self.reload()

    # ---------------- progress / ui pulse ----------------
    def _progress(self, percent: int, text: str = "") -> None:
        cb = self._progress_cb
        if not cb:
            return
        try:
            cb(int(percent), str(text or ""))
        except Exception:
            pass

    def _pulse_ui(self, force: bool = False) -> None:
        app = QApplication.instance()
        if not app:
            return
        if force or self._ui_timer.elapsed() >= 16:  # ~60 FPS max
            try:
                app.processEvents()
            except Exception:
                pass
            self._ui_timer.restart()

    # ---------------- icons helpers (NO dependency on view.* helpers) ----------------
    def _std_icon(self, sp: QStyle.StandardPixmap) -> QIcon:
        app = QApplication.instance()
        style = app.style() if app else self.view.style()
        return style.standardIcon(sp)

    def _plus_green_icon(self) -> QIcon:
        ic = QIcon.fromTheme("list-add")
        if not ic.isNull():
            return ic

        size = 16
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)

        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#22C55E"))
        p.drawRoundedRect(size // 2 - 2, 2, 4, size - 4, 2, 2)
        p.drawRoundedRect(2, size // 2 - 2, size - 4, 4, 2, 2)
        p.end()

        return QIcon(pm)

    # ---------------- lifecycle ----------------
    def reload(self) -> None:
        self._progress(60, "Читаю объекты…")
        self._pulse_ui(True)

        objs = self._service.list_objects()

        self._progress(70, "Подготавливаю дерево…")
        self._pulse_ui(True)

        self._populate_tree(objs)
        self._refresh_active_editor_widget()

        self._progress(100, "Готово")
        self.view.set_status("Готово")
        self._pulse_ui(True)

    # ---------------- actions ----------------
    def on_save(self) -> None:
        self._refresh_active_editor_widget()
        self.reload()
        self.view.set_status("Сохранено")

    def _refresh_active_editor_widget(self) -> None:
        try:
            active = self.view._active_editor_widget()
        except Exception:
            active = None
        if active is None:
            return
        reload_fn = getattr(active, "reload_from_vm", None)
        if not callable(reload_fn):
            reload_fn = getattr(active, "refresh", None)
        if callable(reload_fn):
            try:
                reload_fn()
            except Exception:
                pass

    def on_check(self) -> None:
        self.view.show_info("Проверка", "Проверка (заглушка).")

    def on_search(self, text: str) -> None:
        self._search = (text or "").strip().lower()
        self.reload()

    def on_select(self, info: NodeInfo) -> None:
        rows: List[Tuple[str, str]] = [
            ("GUID", info.guid),
            ("Имя", info.name),
            ("Тип", info.obj_type or info.kind),
        ]
        self.view.set_properties_rows(rows)

    def on_open_object(self, info: NodeInfo) -> None:
        self.view.open_object_tab(info)

    # ---------------- icons (tree nodes) ----------------
    def _icon(self, key: str) -> QIcon:
        name = self.ICON_MAP.get(key)
        if not name:
            return QIcon()
        return self.icons.icon(name)

    def _icon_for_node(self, meta: Dict[str, Any]) -> QIcon:
        kind = str(meta.get("kind") or "")
        if kind == "root":
            return self._icon("configuration")
        if kind == "group":
            if str(meta.get("type") or "") == "constants":
                return self._constants_icon
            ic = self._icon(str(meta.get("type") or ""))
            return ic if not ic.isNull() else self._icon("folder")
        if kind == "schema":
            payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
            section = str(payload.get("section") or meta.get("name") or "").strip().lower()
            schema_item_kind = str(payload.get("schema_item_kind") or "").strip().lower()
            if schema_item_kind in ("requisite", "attribute", "column") or section == "attributes":
                return self._schema_req_icon
            if schema_item_kind == "tabular_part" or section == "tabular_parts":
                return self._schema_table_icon
            return self._icon("object")
        if kind == "folder":
            nm = str(meta.get("name") or "folder")
            if nm == "subsystems":
                return self._subsystem_icon
            if nm == "common_modules":
                return self._common_module_icon
            if nm == "common_commands":
                return self._common_command_icon
            if nm == "common_forms":
                return self._common_form_icon
            if nm == "common_layouts":
                return self._common_layout_icon
            if nm == "common_pictures":
                return self._common_picture_icon
            if nm == "xdto_packages":
                return self._xdto_package_icon
            if nm == "web_services":
                return self._web_service_icon
            if nm == "http_services":
                return self._http_service_icon
            if nm == "ws_links":
                return self._ws_link_icon
            if nm == "websocket_clients":
                return self._websocket_client_icon
            if nm == "integration_services":
                return self._integration_service_icon
            if nm == "style_elements":
                return self._style_element_icon
            if nm == "styles":
                return self._style_icon
            if nm == "session_params":
                return self._session_param_icon
            if nm == "common_attributes":
                return self._schema_req_icon
            if nm == "settings_storages":
                return self._settings_storage_icon
            if nm == "exchange_plans":
                return self._exchange_plan_icon
            if nm == "sequences":
                return self._sequence_icon
            if nm == "document_numerators":
                return self._document_numerator_icon
            if nm == "bots":
                return self._bot_icon
            if nm == "scheduled_jobs":
                return self._scheduled_job_icon
            if nm == "event_subscriptions":
                return self._event_subscription_icon
            if nm == "selection_criteria":
                return self._selection_criterion_icon
            if nm == "command_groups":
                return self._command_group_icon
            ic = self._icon(nm)
            return ic if not ic.isNull() else self._icon("folder")
        if kind == "object":
            tp = str(meta.get("type") or "object")
            if tp == "subsystem":
                return self._subsystem_icon
            if tp == "common_module":
                return self._common_module_icon
            if tp in ("common_command", "common_commands"):
                return self._common_command_icon
            if tp in ("common_form", "common_forms"):
                return self._common_form_icon
            if tp in ("common_layout", "common_layouts"):
                return self._common_layout_icon
            if tp in ("common_picture", "common_pictures"):
                return self._common_picture_icon
            if tp in ("xdto_package", "xdto_packages"):
                return self._xdto_package_icon
            if tp in ("web_service", "web_services"):
                return self._web_service_icon
            if tp in ("http_service", "http_services"):
                return self._http_service_icon
            if tp in ("ws_link", "ws_links", "ws_reference", "ws_references"):
                return self._ws_link_icon
            if tp in ("websocket_client", "websocket_clients"):
                return self._websocket_client_icon
            if tp in ("integration_service", "integration_services"):
                return self._integration_service_icon
            if tp in ("style_element", "style_elements"):
                return self._style_element_icon
            if tp in ("style", "styles"):
                return self._style_icon
            if tp in ("session_param", "session_params"):
                return self._session_param_icon
            if tp in ("common_attribute", "common_attributes"):
                return self._schema_req_icon
            if tp in ("settings_storage", "settings_storages"):
                return self._settings_storage_icon
            if tp in ("exchange_plan", "exchange_plans"):
                return self._exchange_plan_icon
            if tp in ("sequence", "sequences"):
                return self._sequence_icon
            if tp in ("document_numerator", "document_numerators"):
                return self._document_numerator_icon
            if tp in ("bot", "bots"):
                return self._bot_icon
            if tp in ("scheduled_job", "scheduled_jobs"):
                return self._scheduled_job_icon
            if tp in ("event_subscription", "event_subscriptions"):
                return self._event_subscription_icon
            if tp in ("selection_criterion", "selection_criteria"):
                return self._selection_criterion_icon
            if tp in ("command_group", "command_groups"):
                return self._command_group_icon
            if tp == "constants":
                return self._constants_icon
            ic = self._icon(tp)
            return ic if not ic.isNull() else self._icon("object")
        return QIcon()

    # ---------------- tree building ----------------
    def _populate_tree(self, objs: List[ManifestObject]) -> None:
        # Важный инвариант стабилизации:
        # логика фильтрации legacy-папок и поиска должна быть единой
        # для ViewModel и Controller. Поэтому используем TreeBuilder.
        objs2 = prepare_tree_objects(
            objs,
            search_text=self._search,
            hide_legacy_object_folders=True,
        )

        self._building = True
        try:
            last_pct = -1
            update_every = 25

            def on_progress(built: int, total: int) -> None:
                """Callback прогресса построения дерева.

                Контроллер отвечает за UX (progress/pulse UI),
                а алгоритм построения дерева вынесен в TreeBuilder.
                """

                nonlocal last_pct

                # Обновляем не на каждом узле, чтобы не фризить UI.
                force = built >= total
                if not force and (built % update_every != 0):
                    return

                pct = 70 + int(22 * (built / max(1, total)))  # 70..92
                if pct == last_pct and not force:
                    return
                last_pct = pct

                self._progress(pct, f"Строю дерево… {built}/{total}")
                self._pulse_ui(False)

            build_tree_model(
                self.view.tree_model,
                objs2,
                mk_item=self._mk_item,
                progress=on_progress,
                safety_limit=10000,
            )

            # Итоговое восстановление UI-состояния
            self.view.expand_default()
            self._pulse_ui(True)
        finally:
            self._building = False

    def _mk_item(self, o: ManifestObject) -> QStandardItem:
        title = o.title or o.name or o.guid

        # Системные подпапки (forms/commands/layouts/...)
        # показываем локализованно по реестру секций.
        try:
            payload = o.payload if isinstance(o.payload, dict) else {}
            if o.kind == "root":
                title = t("cfg_tree_title")
            elif o.kind == "folder" and payload.get("system"):
                k = section_i18n_key(str(o.name))
                if k:
                    title = t(k)
        except (TypeError, KeyError, AttributeError, ValueError):
            pass
        it = QStandardItem(title)

        meta: Dict[str, Any] = {
            "guid": o.guid,
            "type": o.type,
            "name": o.name,
            "title": o.title,
            "kind": o.kind,
            "parent_guid": o.parent_guid,
            "payload": o.payload or {},
        }
        it.setData(o.kind, self.view.ROLE_KIND)
        it.setData(meta, self.view.ROLE_META)
        # Единая точка получения иконок.
        it.setIcon(self.icon_provider.tree_icon(meta))

        # Inline rename: editable only for non-system objects
        editable = False
        if o.kind == "object":
            payload = o.payload if isinstance(o.payload, dict) else {}
            editable = not bool(payload.get("system") or payload.get("protected") or payload.get("seed"))
        it.setEditable(editable)
        return it

    # ---------------- context menu ----------------
    def on_tree_context_menu(self, kind: str, item, info: Optional[NodeInfo], global_pos) -> None:
        meta = item.data(self.view.ROLE_META) or {}
        if not isinstance(meta, dict):
            return

        if kind in ("root", "group", "folder"):
            self._show_add_only_menu(meta, global_pos)
        elif kind == "object":
            self._show_object_menu(meta, global_pos)

    def _show_add_only_menu(self, meta: dict, global_pos) -> None:
        obj_type = str(meta.get("type") or "")
        parent_guid = str(meta.get("guid") or "")
        if not obj_type or not parent_guid:
            return

        menu = QMenu(self.view)
        act_add = menu.addAction(self._plus_green_icon(), t("ctx_add"))
        act_add.setShortcut("Ins")
        act_add.triggered.connect(lambda: self._create_object_quick(obj_type, parent_guid))
        menu.exec(global_pos)

    def _show_object_menu(self, meta: dict, global_pos) -> None:
        menu = QMenu(self.view)

        act_rename = menu.addAction(self._std_icon(QStyle.SP_FileDialogDetailedView), t("ctx_rename"))
        act_rename.setShortcut("F2")
        act_rename.triggered.connect(lambda: self.view.begin_inline_rename(str(meta.get("guid") or "")))

        act_delete = menu.addAction(self._std_icon(QStyle.SP_TrashIcon), t("ctx_delete"))
        act_delete.setShortcut("Del")
        act_delete.triggered.connect(lambda: self._delete_object(meta))

        menu.exec(global_pos)

    # ---------------- create / rename / delete ----------------
    def _create_object_quick(self, obj_type: str, parent_guid: str) -> None:
        obj_type = (obj_type or "").strip()
        parent_guid = (parent_guid or "").strip()
        if not obj_type or not parent_guid:
            return

        objs = self._service.list_objects()
        title, name = self._next_auto_name(obj_type, objs)

        try:
            mo = self._service.add_object(obj_type=obj_type, title=title, name=name, parent_guid=parent_guid)
            self.reload()
            self.view.begin_inline_rename(mo.guid)
        except Exception as e:
            self.view.show_warning("Ошибка", f"Не удалось создать объект: {e}")

    def _next_auto_name(self, obj_type: str, objs: List[ManifestObject]) -> Tuple[str, str]:
        prefix_title = self.AUTO_TITLE_PREFIX.get(obj_type, "Объект")
        prefix_code = self.AUTO_CODE_PREFIX.get(obj_type, "object")

        used_titles: set[str] = set()
        used_codes: set[str] = set()
        for o in objs:
            if o.kind != "object" or o.type != obj_type:
                continue
            used_titles.add((o.title or "").strip().lower())
            used_codes.add((o.name or "").strip().lower())

        n = 1
        while True:
            title = f"{prefix_title}{n}"
            code = f"{prefix_code}{n}"
            if title.lower() not in used_titles and code.lower() not in used_codes:
                return title, code
            n += 1

    def on_item_renamed(self, guid: str, new_title: str) -> None:
        if self._building:
            return
        guid = (guid or "").strip()
        new_title = (new_title or "").strip()
        if not guid or not new_title:
            return
        try:
            self._service.rename_object(guid, new_title)
            self.view.set_status("Переименовано")
        except Exception as e:
            self.view.show_warning("Ошибка", f"Не удалось переименовать: {e}")
            self.reload()

    def _delete_object(self, meta: dict) -> None:
        guid = str(meta.get("guid") or "").strip()
        if not guid:
            self.view.show_warning("Удалить", "Не удалось определить GUID объекта")
            return

        payload = meta.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        if payload.get("system") or payload.get("protected") or payload.get("seed"):
            self.view.show_warning("Удаление запрещено", "Этот элемент системный и не может быть удалён")
            return

        title = str(meta.get("title") or meta.get("name") or "объект")
        if not self.view.confirm(
            "Подтверждение удаления",
            f"Удалить «{title}»?\n\nБудут удалены также все вложенные пользовательские элементы.",
        ):
            return

        try:
            self._service.delete_object(guid)
            self.reload()
            self.view.set_status("Удалено")
        except Exception as e:
            self.view.show_warning("Ошибка", f"Не удалось удалить: {e}")
