"""
Провайдер иконок (IconProvider)

Назначение
----------
IconProvider — единая точка (Single Source of Truth) для построения:

1) Иконок узлов дерева конфигурации (QIcon):
   - для типов объектов (Константы, Справочники, Документы, Папки и т.п.)
   - чтобы VM и Controller не содержали дублирующуюся маппинг-логику

2) Превью/иконок ресурсов-картинок (SVG/PNG/JPEG/…):
   - из bytes -> QPixmap -> QIcon
   - с поддержкой SVG-переменных вида var(token) / var(--token)
     через палитру проекта (palette_provider)

Почему это важно
----------------
Ранее логика генерации иконок расползалась по виджетам, VM и контроллерам.
В результате любое изменение рендера SVG/палитры/preview приводило к регрессиям:
"починили в одном месте — сломали в другом".
IconProvider концентрирует всё в одном модуле и позволяет стабильно переиспользовать
рендеринг иконок в галерее, формах и дереве конфигурации.

Источники данных
----------------
- palette_provider (опционально): функция без параметров, возвращающая словарь:
  { token: "#RRGGBB"}
  Применяется для подстановки var(token) в SVG перед рендерингом.

- tree_icon_provider (опционально): функция (meta: dict) -> QIcon
  Используется для назначения "типовых" иконок узлам дерева конфигурации.
  Если провайдер не задан или возвращает пустой QIcon, применяется безопасный fallback
  на стандартную иконку Qt (без предупреждений/ошибок).

Инварианты
----------
- IconProvider не должен показывать пользователю предупреждения/ошибки сам по себе.
  Любые проблемы (битый SVG, пустой pixmap) решаются "тихо":
  возвращается None / пустая иконка / стандартная иконка Qt.

- Логика подстановки var(...) должна быть единообразной во всех местах UI,
  поэтому resolve выполняется здесь (SvgVarResolver).

- IconProvider не хранит состояние UI и не зависит от конкретных виджетов.
  Он — сервисный слой, который можно дергать из VM/Controller/виджетов.

Ограничения
-----------
- svg_bytes_to_pixmap() рендерит SVG в квадрат opts.size × opts.size.
  Это подходит для иконок/превью. Для "точного" рендера с учетом viewBox и
  оригинальных пропорций может потребоваться расширение (позже).

- raster_bytes_to_pixmap() масштабирует с KeepAspectRatio + SmoothTransformation,
  что является хорошим стандартом для UI-иконок.

См. также
---------
- SvgVarResolver: подстановка var(token) / var(--token) в SVG
- object_policies / tree_builder: инфраструктура дерева (не должна тянуть иконки внутрь)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QStyle
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QPainter

from src.ui_qt.services.svg_var_resolver import SvgVarResolver


@dataclass(frozen=True)
class IconRenderOptions:
    """
       Настройки рендеринга превью/иконок.

       Атрибуты:
           size:
               Размер целевого квадрата (ширина и высота) в пикселях.
               Для SVG и raster превью применяется одинаково.

           transparent:
               Прозрачный фон для SVG-иконок.
               - True: фон заливается прозрачным (Qt.GlobalColor.transparent)
               - False: фон заливается белым

       Примечание:
           Логически это bool-флаг. Сейчас у тебя стоит int=True — это допустимо,
           но лучше использовать bool для ясности.
    """
    size: int = 96
    transparent: int = True  # Кстати, тут лучше bool, если это флаг


class IconProvider:
    """Centralized icon/pixmap builder.

    This is part of "stabilization": when icon rendering logic is scattered
    across widgets, regressions happen easily. By concentrating SVG/raster
    rendering here we can reuse it in the gallery, forms, etc.
    """

    def __init__(self,
                 palette_provider: Optional[Callable[[], Dict[str, str]]] = None,
                 tree_icon_provider: Optional[Callable[[dict], QIcon]] = None,
                 ):
        """Создать провайдер иконок.

        Args:
            palette_provider:
                Функция, возвращающая словарь токенов палитры (token -> '#RRGGBB').
                Используется для подстановки ``var(token)`` в SVG.

            tree_icon_provider:
                Функция, которая по метаданным узла дерева (dict) возвращает `QIcon`.
                Это *не* про превью картинок, а про иконки типов (Константы, Справочники,
                Папка, и т.д.).

        Примечание:
            Мы сознательно держим один "центр" получения иконок:
            - превью SVG/PNG строится здесь же (через bytes -> QPixmap)
            - иконки дерева тоже запрашиваются здесь, чтобы VM/Controller не имели дублей.
        """

        self._palette_provider = palette_provider
        self._tree_icon_provider = tree_icon_provider

    def tree_icon(self, meta: dict) -> QIcon:
        """
        Вернуть иконку для узла дерева конфигурации.

        Аргументы:
            meta:
                Метаданные узла дерева (dict), которые обычно хранятся в item.data(ROLE_META).
                Ожидаемые ключи зависят от реализации дерева (kind/type/payload и т.п.).

        Возвращает:
            QIcon:
                - Иконку от tree_icon_provider(meta), если она задана и вернула валидную иконку.
                - Иначе "безопасную" стандартную иконку Qt (SP_FileIcon).
                - В крайнем случае — пустой QIcon().

        Политика устойчивости:
            Метод специально не выбрасывает исключения наружу.
            Мы перехватываем ожидаемые ошибки логики провайдера (TypeError/KeyError/…)
            и делаем fallback, чтобы UI не падал из-за одной некорректной записи в meta.
        """
        if self._tree_icon_provider is not None:
            try:
                ico = self._tree_icon_provider(meta)
                if isinstance(ico, QIcon) and not ico.isNull():
                    return ico
            except (TypeError, AttributeError, KeyError, ValueError):
                # Перехватываем только ожидаемые ошибки логики провайдера
                pass

        app = QApplication.instance()
        if isinstance(app, QApplication):
            style = app.style()

            # В Qt 6 используем StandardPixmap, в Qt 5 откатываемся к атрибуту класса
            icon_type = getattr(QStyle.StandardPixmap, "SP_FileIcon",
                                getattr(QStyle, "SP_FileIcon", None))

            if icon_type is not None:
                return style.standardIcon(icon_type)

        return QIcon()

    def svg_bytes_to_pixmap(self, data: bytes, *, opts: IconRenderOptions) -> QPixmap:
        """
        Преобразовать SVG (bytes) в QPixmap заданного размера.

        Пайплайн:
            1) bytes -> str (decode errors="replace")
            2) подстановка var(token) через SvgVarResolver и палитру проекта
            3) str -> bytes
            4) QSvgRenderer(bytes)
            5) Рендер в QPixmap(opts.size, opts.size) через QPainter

        Аргументы:
            data:
                Исходные SVG-данные в bytes.
            opts:
                Настройки рендеринга (размер, прозрачность фона).

        Возвращает:
            QPixmap:
                Сформированный pixmap. Может быть пустым (pm.isNull()) в случае ошибок рендера.

        Примечание:
            Мы намеренно не показываем QMessageBox/лог UI отсюда.
            Ошибки рендера обрабатываются выше: build_icon() вернёт None.
        """
        text = data.decode(errors="replace")
        palette = self._palette_provider() if self._palette_provider else {}
        text = SvgVarResolver.resolve(text, palette).text
        # Lucide and many monochrome SVG icons use stroke/fill="currentColor".
        # Replace currentColor with a palette-appropriate foreground to keep icons visible
        # on both dark and light themes.
        try:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtGui import QPalette
            app = QApplication.instance()
            if app is not None:
                theme = ""
                try:
                    theme = str(app.property("mp_theme") or "")
                except Exception:
                    theme = ""

                if theme.lower() == "dark":
                    fg = "#ffffff"
                elif theme.lower() == "light":
                    fg = "#0b1020"
                else:
                    c = app.palette().color(QPalette.ColorRole.ButtonText)
                    fg = f"#{c.red():02x}{c.green():02x}{c.blue():02x}"

                # Replace both currentColor and currentcolor (some svg generators vary case)
                text = text.replace("currentColor", fg).replace("currentcolor", fg)
        except Exception:
            # If palette isn't available (early startup), keep SVG as-is.
            pass
        b = text.encode()

        r = QSvgRenderer(b)
        pm = QPixmap(opts.size, opts.size)
        pm.fill(Qt.GlobalColor.transparent if opts.transparent else Qt.GlobalColor.white)
        p = QPainter(pm)
        r.render(p)
        p.end()
        return pm

    @staticmethod
    def raster_bytes_to_pixmap(data: bytes, *, opts: IconRenderOptions) -> QPixmap:
        """
        Преобразовать raster (PNG/JPEG/WEBP/…) в QPixmap заданного размера.

        Аргументы:
            data:
                Бинарные данные изображения.
            opts:
                Настройки рендеринга (целевой размер).

        Возвращает:
            QPixmap:
                Масштабированный pixmap с KeepAspectRatio + SmoothTransformation.
                Если загрузка не удалась — пустой QPixmap().
        """
        pm = QPixmap()
        pm.loadFromData(data)
        if pm.isNull():
            return QPixmap()
        return pm.scaled(
            opts.size,
            opts.size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

    def build_icon(self, *, data: bytes, mime: str, asset_key: str, size: int = 96) -> QIcon | None:
        """
        Построить QIcon по данным ресурса (SVG или raster).

        Аргументы:
            data:
                Бинарные данные ресурса (SVG текст в bytes или raster bytes).
            mime:
                MIME-тип (например "image/svg+xml", "image/png"). Может быть пустым.
            asset_key:
                Ключ ассета/имя файла. Используется как fallback-детектор для ".svg".
            size:
                Целевой размер (квадрат) для иконки.

        Возвращает:
            QIcon | None:
                - QIcon, если удалось построить pixmap (pm не null)
                - None, если рендер не удался / данные битые

        Логика выбора рендера:
            - SVG: если mime == image/svg+xml ИЛИ asset_key заканчивается на ".svg"
            - Иначе raster

        Политика устойчивости:
            Метод не должен падать и не должен показывать предупреждения.
            При проблемах возвращает None.
        """
        opts = IconRenderOptions(size=size)
        m = (mime or "").lower()
        if m == "image/svg+xml" or asset_key.lower().endswith(".svg"):
            pm = self.svg_bytes_to_pixmap(data, opts=opts)
        else:
            pm = self.raster_bytes_to_pixmap(data, opts=opts)
        if pm.isNull():
            return None
        return QIcon(pm)
