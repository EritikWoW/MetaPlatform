from __future__ import annotations

import sys
import ctypes
from ctypes import wintypes

import tkinter as tk
from tkinter import ttk

# ----------------- Палитра -----------------
BG = "#0B1020"          # фон окна
PANEL = "#0F172A"       # карточки/панели
PANEL_2 = "#111C33"     # второй слой
FG = "#E7EAF0"          # основной текст
SUBTLE = "#9AA4B2"      # вторичный текст
BORDER = "#22304A"      # границы
ACCENT = "#5B5BD6"      # индиго
ACCENT_2 = "#2DD4BF"    # бирюза

FONT_BASE = ("Segoe UI", 10)
FONT_H1 = ("Segoe UI", 14, "bold")
FONT_H2 = ("Segoe UI", 11, "bold")


# ----------------- Windows: dark titlebar -----------------
def try_enable_dark_titlebar(tk_window) -> bool:
    """Включает тёмный title bar на Windows (если поддерживается)."""
    if sys.platform != "win32":
        return False

    try:
        tk_window.update_idletasks()
        hwnd = wintypes.HWND(tk_window.winfo_id())
        dwmapi = ctypes.windll.dwmapi

        # На разных сборках Windows используется 19 или 20
        DWMWA_USE_IMMERSIVE_DARK_MODE_20 = 20
        DWMWA_USE_IMMERSIVE_DARK_MODE_19 = 19

        value = ctypes.c_int(1)
        res = dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE_20,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
        if res != 0:
            res = dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_USE_IMMERSIVE_DARK_MODE_19,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
        return res == 0
    except Exception:
        return False


# ----------------- Scrollbar styling (ttk) -----------------
def _style_scrollbars(style: ttk.Style) -> None:
    """Минималистичные скроллбары (без стрелок) в едином стиле."""

    trough = PANEL
    thumb = PANEL_2
    thumb_active = "#1A2A4A"   # hover
    thumb_pressed = ACCENT     # pressed

    # Убираем стрелки полностью (современный минимализм)
    style.layout(
        "Vertical.TScrollbar",
        [
            ("Vertical.Scrollbar.trough", {
                "sticky": "nswe",
                "children": [
                    ("Vertical.Scrollbar.thumb", {"unit": "1", "sticky": "nswe"})
                ],
            })
        ],
    )
    style.layout(
        "Horizontal.TScrollbar",
        [
            ("Horizontal.Scrollbar.trough", {
                "sticky": "nswe",
                "children": [
                    ("Horizontal.Scrollbar.thumb", {"unit": "1", "sticky": "nswe"})
                ],
            })
        ],
    )

    # Важно: bordercolor = trough, чтобы не появлялись светлые линии
    style.configure(
        "Vertical.TScrollbar",
        troughcolor=trough,
        background=thumb,
        bordercolor=trough,
        lightcolor=thumb,
        darkcolor=thumb,
        relief="flat",
        gripcount=0,
        width=10,
    )
    style.configure(
        "Horizontal.TScrollbar",
        troughcolor=trough,
        background=thumb,
        bordercolor=trough,
        lightcolor=thumb,
        darkcolor=thumb,
        relief="flat",
        gripcount=0,
        width=10,
    )

    style.map(
        "Vertical.TScrollbar",
        background=[("active", thumb_active), ("pressed", thumb_pressed)],
    )
    style.map(
        "Horizontal.TScrollbar",
        background=[("active", thumb_active), ("pressed", thumb_pressed)],
    )


# ----------------- Treeview: убрать рамку поля -----------------
def _style_treeview_flat(style: ttk.Style, stylename: str) -> None:
    """Жёстко убирает рамку Treeview на Windows/clam.

    Причина «рамки» в ttk обычно не в borderwidth, а в layout-элементе темы (Treeview.field).
    Самый надёжный способ — заменить layout на чистый treearea.
    """

    style.configure(stylename, borderwidth=0, relief="flat")

    # Самый рабочий вариант: только treearea — без field/padding (они и дают обводку)
    try:
        style.layout(stylename, [("Treeview.treearea", {"sticky": "nswe"})])
    except tk.TclError:
        # Fallback для редких сборок Tcl/Tk
        style.layout(
            stylename,
            [
                ("Treeview.field", {
                    "sticky": "nswe",
                    "border": 0,
                    "children": [
                        ("Treeview.treearea", {"sticky": "nswe"})
                    ],
                })
            ],
        )


# ----------------- Theme -----------------
def apply_theme(root: tk.Tk | tk.Toplevel) -> ttk.Style:
    """Применяет темную тему ко всему приложению (clam нужен для нормальной кастомизации ttk)."""

    root.configure(bg=BG)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    # Базовые виджеты
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=PANEL, borderwidth=0, relief="flat")

    style.configure("TLabel", background=BG, foreground=FG, font=FONT_BASE)
    style.configure("Subtle.TLabel", background=BG, foreground=SUBTLE, font=FONT_BASE)
    style.configure("H1.TLabel", background=BG, foreground=FG, font=FONT_H1)
    style.configure("H2.TLabel", background=BG, foreground=FG, font=FONT_H2)

    style.configure("TSeparator", background=BORDER)

    # Кнопки
    style.configure(
        "TButton",
        background=PANEL_2,
        foreground=FG,
        borderwidth=0,
        padding=(12, 8),
        focusthickness=1,
        focuscolor=ACCENT,
        font=FONT_BASE,
    )
    style.map(
        "TButton",
        background=[("active", "#162445"), ("disabled", PANEL)],
        foreground=[("disabled", SUBTLE)],
    )

    style.configure(
        "Primary.TButton",
        background=ACCENT,
        foreground="#FFFFFF",
        padding=(12, 9),
        font=FONT_H2,
    )
    style.map(
        "Primary.TButton",
        background=[("active", "#6C6CFF"), ("disabled", PANEL)],
        foreground=[("disabled", SUBTLE)],
    )

    style.configure(
        "Secondary.TButton",
        background=PANEL_2,
        foreground=FG,
        padding=(12, 9),
        font=FONT_H2,
    )
    style.map(
        "Secondary.TButton",
        background=[("active", "#162445"), ("disabled", PANEL)],
        foreground=[("disabled", SUBTLE)],
    )

    # Поля ввода
    style.configure(
        "TEntry",
        fieldbackground=PANEL,
        background=PANEL,
        foreground=FG,
        insertcolor=FG,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        padding=(8, 6),
    )

    # Scrollbars (важно до Treeview)
    _style_scrollbars(style)

    # Treeview базовый
    style.configure(
        "Treeview",
        background=PANEL,
        fieldbackground=PANEL,
        foreground=FG,
        bordercolor=PANEL,  # чтобы не рисовало линию «вокруг»
        rowheight=28,
        font=FONT_BASE,
    )
    style.map(
        "Treeview",
        background=[("selected", ACCENT)],
        foreground=[("selected", "#FFFFFF")],
    )

    style.configure(
        "Treeview.Heading",
        background=PANEL_2,
        foreground=FG,
        relief="flat",
        borderwidth=0,
        font=FONT_H2,
        padding=(8, 8),
    )
    style.map(
        "Treeview.Heading",
        background=[("active", "#162445")],
        foreground=[("active", FG)],
    )

    # Твой стиль (launcher_app.py: style="Data.Treeview")
    style.configure(
        "Data.Treeview",
        background=PANEL,
        fieldbackground=PANEL,
        foreground=FG,
        bordercolor=PANEL,
        borderwidth=0,
        relief="flat",
        rowheight=28,
    )
    style.map(
        "Data.Treeview",
        background=[("selected", ACCENT)],
        foreground=[("selected", "#FFFFFF")],
    )

    style.configure(
        "Data.Treeview.Heading",
        background=PANEL_2,
        foreground=FG,
        relief="flat",
        borderwidth=0,
        padding=(8, 6),
        font=FONT_H2,
    )
    style.map(
        "Data.Treeview.Heading",
        background=[("active", PANEL_2)],
        foreground=[("active", FG)],
    )

    # Ключ: убираем «рамку поля» темы
    _style_treeview_flat(style, "Treeview")
    _style_treeview_flat(style, "Data.Treeview")
    _style_combobox(style)
    install_combobox_popdown_defaults(root)

    root.option_add("*TCombobox*Listbox.background", PANEL)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")

    try_enable_dark_titlebar(root)
    return style

# ----------------- tk.Combobox styling -----------------
def _style_combobox(style: ttk.Style) -> None:
    # Стиль самого комбобокса (поле + стрелка)
    style.configure(
        "App.TCombobox",
        foreground=FG,
        fieldbackground=PANEL,
        background=PANEL_2,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        arrowcolor=FG,
        padding=(8, 6),
        relief="flat",
    )

    style.map(
        "App.TCombobox",
        fieldbackground=[("readonly", PANEL), ("!readonly", PANEL)],
        foreground=[("disabled", SUBTLE), ("!disabled", FG)],
        bordercolor=[("focus", ACCENT), ("!focus", BORDER)],
        arrowcolor=[("disabled", SUBTLE), ("!disabled", FG)],
    )

    # Важно: фон контейнера popdown (иначе справа часто "белит")
    style.configure(
        "ComboboxPopdownFrame",
        background=PANEL,
        borderwidth=0,
        relief="flat",
    )


def install_combobox_popdown_defaults(root: tk.Misc) -> None:
    """
    Глобальные дефолты для Listbox внутри ttk.Combobox popdown.
    Это убирает белую рамку/фон у списка и делает цвета как в теме.
    """
    root.option_add("*TCombobox*Listbox.background", PANEL)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")

    # убрать "системную" белую рамку listbox
    root.option_add("*TCombobox*Listbox.borderWidth", 0)
    root.option_add("*TCombobox*Listbox.highlightThickness", 1)
    root.option_add("*TCombobox*Listbox.highlightBackground", BORDER)
    root.option_add("*TCombobox*Listbox.highlightColor", ACCENT)
    root.option_add("*TCombobox*Listbox.relief", "flat")
    root.option_add("*TCombobox*Listbox.selectBorderWidth", 0)


def style_combobox_popdown_now(root: tk.Misc, combo: ttk.Combobox) -> None:
    """
    Достилизация уже созданного popdown окна (фон справа + скроллбар).
    Вызывать после открытия (через after(0, ...)).
    """
    try:
        popdown = root.tk.eval(f"ttk::combobox::PopdownWindow {str(combo)}")

        # popdown toplevel
        try:
            top = root.nametowidget(popdown)
            top.configure(bg=PANEL)
        except Exception:
            pass

        # frame внутри popdown (обычно popdown.f)
        try:
            frame = root.nametowidget(popdown + ".f")
            frame.configure(style="ComboboxPopdownFrame")
        except Exception:
            frame = None

        # listbox (обычно popdown.f.l)
        try:
            lb = root.nametowidget(popdown + ".f.l")
            lb.configure(
                background=PANEL,
                foreground=FG,
                selectbackground=ACCENT,
                selectforeground="#FFFFFF",
                borderwidth=0,
                relief="flat",
                highlightthickness=1,
                highlightbackground=BORDER,
                highlightcolor=ACCENT,
            )
        except Exception:
            pass

        # scrollbar (обычно popdown.f.sb)
        # Иногда белая полоса справа — это фон frame за скроллбаром или сам trough.
        try:
            sb = root.nametowidget(popdown + ".f.sb")
            # Если это ttk.Scrollbar — стиль берётся из твоего _style_scrollbars.
            # Но на некоторых сборках помогает явно задать стиль:
            if isinstance(sb, ttk.Scrollbar):
                sb.configure(style="Vertical.TScrollbar")
        except Exception:
            pass

        # на всякий случай — чтобы фон справа точно был тёмный
        if frame is not None:
            try:
                frame.configure(style="ComboboxPopdownFrame")
            except Exception:
                pass

    except Exception:
        # popdown ещё не создан или другой путь — просто молча выходим
        return


def bind_combobox_popdown_styling(root: tk.Misc, combo: ttk.Combobox) -> None:
    """
    Привязываем авто-достилизацию popdown при каждом открытии.
    """
    def _apply(_e=None):
        combo.after(0, lambda: style_combobox_popdown_now(root, combo))

    # мышь
    combo.bind("<Button-1>", _apply, add="+")
    # клавиатура (Alt+Down / Down)
    combo.bind("<KeyRelease-Down>", _apply, add="+")

# ----------------- tk.Listbox styling -----------------
def style_listbox(lb: tk.Listbox) -> None:
    """Listbox не ttk, поэтому красим отдельно."""

    lb.configure(
        bg=PANEL,
        fg=FG,
        selectbackground=ACCENT,
        selectforeground="#FFFFFF",
        relief="flat",
        borderwidth=0,
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=ACCENT,
        activestyle="none",
    )
