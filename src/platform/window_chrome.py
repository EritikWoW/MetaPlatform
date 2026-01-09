from __future__ import annotations

import sys
import ctypes
import tkinter as tk
from tkinter import ttk
from pathlib import Path

from .ui_style import BG, PANEL_2, FG, ACCENT, BORDER


# ----------------- Windows helpers -----------------

def _get_workarea() -> tuple[int, int, int, int]:
    """Work area without taskbar (Windows)."""
    if sys.platform != "win32":
        return (0, 0, 0, 0)
    try:
        from ctypes import wintypes

        SPI_GETWORKAREA = 0x0030
        rect = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
        return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
    except Exception:
        return (0, 0, 0, 0)


def _win_get_root_hwnd(hwnd: int) -> int:
    """Ensure we have top-level HWND."""
    if sys.platform != "win32":
        return hwnd
    try:
        user32 = ctypes.windll.user32
        GA_ROOT = 2
        root = user32.GetAncestor(hwnd, GA_ROOT)
        return int(root) if root else int(hwnd)
    except Exception:
        return int(hwnd)


def _win_apply_borderless_managed(hwnd: int) -> None:
    """
    Remove system caption/frame while keeping the window a normal app window
    (Alt-Tab + taskbar). Do NOT use overrideredirect on Windows.
    """
    if sys.platform != "win32":
        return

    user32 = ctypes.windll.user32

    GWL_STYLE = -16
    GWL_EXSTYLE = -20

    WS_CAPTION = 0x00C00000
    WS_THICKFRAME = 0x00040000
    WS_BORDER = 0x00800000
    WS_DLGFRAME = 0x00400000

    WS_EX_APPWINDOW = 0x00040000
    WS_EX_TOOLWINDOW = 0x00000080

    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_NOZORDER = 0x0004
    SWP_FRAMECHANGED = 0x0020

    GetWindowLongPtrW = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
    SetWindowLongPtrW = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW

    hwnd = _win_get_root_hwnd(int(hwnd))

    style = int(GetWindowLongPtrW(hwnd, GWL_STYLE))
    exstyle = int(GetWindowLongPtrW(hwnd, GWL_EXSTYLE))

    # Remove visible non-client parts
    style &= ~(WS_CAPTION | WS_THICKFRAME | WS_BORDER | WS_DLGFRAME)

    # Ensure it's a normal app window
    exstyle = (exstyle | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW

    SetWindowLongPtrW(hwnd, GWL_STYLE, style)
    SetWindowLongPtrW(hwnd, GWL_EXSTYLE, exstyle)

    # Recompute non-client
    user32.SetWindowPos(
        hwnd, 0, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
    )


# ----------------- ChromeWindow -----------------

class ChromeWindow(tk.Tk):
    """Borderless window with custom titlebar, move + resize."""

    RESIZE_MARGIN = 7  # px
    _ICON_FONT = ("Segoe MDL2 Assets", 10)

    # Segoe MDL2 Assets glyphs
    _GLYPH_MIN = "\uE921"      # ChromeMinimize
    _GLYPH_MAX = "\uE922"      # ChromeMaximize
    _GLYPH_RESTORE = "\uE923"  # ChromeRestore
    _GLYPH_CLOSE = "\uE8BB"    # ChromeClose

    def __init__(
        self,
        title: str = "MetaPlatform",
        fade_in: bool = True,
        show_maximize: bool = True,
    ) -> None:
        super().__init__()

        ICON_PATH = Path(__file__).resolve().parents[2] / "assets" / "icon" / "mp.ico"
        self.iconbitmap(str(ICON_PATH))
        self._fade_in_enabled = bool(fade_in)
        self._show_maximize = bool(show_maximize)

        self._is_maximized = False
        self._restore_geom: str | None = None

        # Drag
        self._drag_active = False
        self._drag_off_x = 0
        self._drag_off_y = 0

        # Resize
        self._resize_mode: str | None = None
        self._resize_start = (0, 0, 0, 0, 0, 0)  # x,y,w,h,mouseX,mouseY

        # Smooth geometry
        self._geom_pending: str | None = None
        self._geom_job: str | None = None
        self._geom_last: str | None = None
        self._geom_applying = False

        self.title(title)

        # Outer 1px border
        self._border = tk.Frame(self, bg=BORDER, padx=1, pady=1)
        self._border.pack(fill="both", expand=True)

        self._surface = tk.Frame(self._border, bg=BG)
        self._surface.pack(fill="both", expand=True)

        # Titlebar
        self._titlebar = tk.Frame(self._surface, bg=PANEL_2, height=44)
        self._titlebar.pack(fill="x")
        self._titlebar.pack_propagate(False)

        self._title_var = tk.StringVar(value=title)
        icon_path = Path(__file__).resolve().parents[2] / "assets" / "icon" / "mp.png"  # 16x16 или 20x20 PNG
        self._title_icon_img = tk.PhotoImage(file=str(icon_path))

        self._title_icon = tk.Label(
            self._titlebar,
            image=self._title_icon_img,
            bg=PANEL_2,
        )
        self._title_icon.pack(side="left", padx=(10, 6), pady=0)

        self._title_label = tk.Label(
            self._titlebar,
            textvariable=self._title_var,
            bg=PANEL_2,
            fg=FG,
            font=("Segoe UI", 10, "bold"),
            padx=0,
        )
        self._title_label.pack(side="left", fill="y")

        self._title_spacer = tk.Frame(self._titlebar, bg=PANEL_2)
        self._title_spacer.pack(side="left", fill="both", expand=True)

        # Buttons
        self._btn_close = self._make_title_button(
            glyph=self._GLYPH_CLOSE,
            command=self.close,
            fg_normal=FG,
            fg_hover="#E15B5B",
        )
        self._btn_close.pack(side="right", fill="y")

        self._btn_max: tk.Label | None = None
        if self._show_maximize:
            self._btn_max = self._make_title_button(
                glyph=self._GLYPH_MAX,
                command=self.toggle_maximize,
                fg_normal=FG,
                fg_hover=ACCENT,
            )
            self._btn_max.pack(side="right", fill="y")

        self._btn_min = self._make_title_button(
            glyph=self._GLYPH_MIN,
            command=self.minimize,
            fg_normal=FG,
            fg_hover=ACCENT,
        )
        self._btn_min.pack(side="right", fill="y")

        # Content
        self.content = ttk.Frame(self._surface)
        self.content.pack(fill="both", expand=True)

        # Drag bindings (titlebar only)
        for w in (self._titlebar, self._title_label, self._title_spacer):
            w.bind("<ButtonPress-1>", self._start_move)
            w.bind("<B1-Motion>", self._do_move)
            w.bind("<ButtonRelease-1>", self._stop_move)
            if self._show_maximize:
                w.bind("<Double-Button-1>", lambda _e: self.toggle_maximize())

        # Global resize bindings (MUST NOT break Combobox)
        self.bind_all("<Motion>", self._on_global_motion, add="+")
        self.bind_all("<ButtonPress-1>", self._on_global_press, add="+")
        self.bind_all("<B1-Motion>", self._on_global_drag, add="+")
        self.bind_all("<ButtonRelease-1>", self._on_global_release, add="+")

        # Apply borderless styles after map (repeat: Tk can overwrite)
        self.bind("<Map>", self._on_map, add="+")
        self.after(0, self._apply_win_styles)
        self.after(120, self._apply_win_styles)
        self.after(420, self._apply_win_styles)

        # Fade-in
        if self._fade_in_enabled:
            try:
                self.attributes("-alpha", 0.0)
                self.after(10, self._fade_in)
            except Exception:
                self._fade_in_enabled = False

    # ----------------- event filtering (critical for Combobox) -----------------

    def _event_belongs_to_me(self, e) -> bool:
        """Ignore events from other toplevels (combobox popdown etc.)."""
        try:
            return e.widget.winfo_toplevel() is self
        except Exception:
            return False

    def _walk_parents(self, w):
        """Yield widget and its parents up to self (safe)."""
        cur = w
        while cur is not None:
            yield cur
            if cur is self:
                break
            try:
                parent_name = cur.winfo_parent()
                if not parent_name:
                    break
                cur = self.nametowidget(parent_name)
            except Exception:
                break

    def _is_in_titlebar(self, w) -> bool:
        for x in self._walk_parents(w):
            if x in (self._titlebar, self._title_label, self._title_spacer):
                return True
        return False

    def _blocks_resize(self, w) -> bool:
        """
        Widgets that must receive clicks even near resize margin.
        Fixes: Combobox doesn't open because resize handler steals the click.
        """
        if w is None:
            return False

        # walk parents: sometimes click lands on internal element of combobox
        for x in self._walk_parents(w):
            try:
                cls = x.winfo_class()
            except Exception:
                cls = ""
            if cls in ("TCombobox", "TEntry", "TSpinbox"):
                return True

        # extra safety
        try:
            return isinstance(w, (ttk.Combobox, ttk.Entry))
        except Exception:
            return False

    # ----------------- smooth geometry -----------------

    def _queue_geometry(self, geom: str, *, immediate: bool = False) -> None:
        self._geom_pending = geom
        if immediate:
            self._apply_pending_geometry(force=True)
            return
        if self._geom_job is None:
            self._geom_job = self.after(16, self._apply_pending_geometry)  # ~60fps

    def _apply_pending_geometry(self, force: bool = False) -> None:
        if self._geom_job is not None:
            try:
                self.after_cancel(self._geom_job)
            except Exception:
                pass
            self._geom_job = None

        geom = self._geom_pending
        if not geom:
            return

        if not force and self._geom_last == geom:
            return

        self._geom_last = geom

        try:
            self.geometry(geom)
        except tk.TclError:
            return

        if not self._geom_applying:
            self._geom_applying = True
            try:
                self.update_idletasks()
                self.update()
            except Exception:
                pass
            finally:
                self._geom_applying = False

    # ----------------- global mouse routing -----------------

    def _xy_in_surface(self, e) -> tuple[int, int]:
        sx = self._surface.winfo_rootx()
        sy = self._surface.winfo_rooty()
        return e.x_root - sx, e.y_root - sy

    def _on_global_motion(self, e):
        if not self._event_belongs_to_me(e):
            return
        if self._is_maximized:
            self._surface.configure(cursor="")
            return

        x, y = self._xy_in_surface(e)
        mode = self._hit_test(x, y)

        # If cursor is over Combobox/Entry (or its internal parts) -> don't show resize cursor
        if mode and self._blocks_resize(getattr(e, "widget", None)):
            self._surface.configure(cursor="")
            return

        self._set_cursor_by_mode(mode)

    def _on_global_press(self, e):
        if not self._event_belongs_to_me(e):
            return
        if self._is_maximized:
            return

        w = getattr(e, "widget", None)

        # no resize on titlebar (drag there)
        if w is not None and self._is_in_titlebar(w):
            return

        x, y = self._xy_in_surface(e)
        mode = self._hit_test(x, y)
        if not mode:
            return

        # KEY FIX: If click is on Combobox/Entry -> never start resize (let Tk handle the click)
        if self._blocks_resize(w):
            return

        self._start_resize(type("E", (), {"x": x, "y": y, "x_root": e.x_root, "y_root": e.y_root})())

    def _on_global_drag(self, e):
        if not self._event_belongs_to_me(e):
            return
        if not self._resize_mode:
            return
        self._do_resize(type("E", (), {"x_root": e.x_root, "y_root": e.y_root})())

    def _on_global_release(self, e):
        if not self._event_belongs_to_me(e):
            return
        self._stop_resize(e)

    # ----------------- Windows style apply -----------------

    def _on_map(self, _e=None):
        self.after(0, self._apply_win_styles)

    def _apply_win_styles(self):
        if sys.platform != "win32":
            return
        try:
            self.update_idletasks()
            hwnd = int(self.winfo_id())
            if hwnd:
                _win_apply_borderless_managed(hwnd)
        except Exception:
            pass

    # ----------------- Title / buttons -----------------

    def set_title(self, title: str) -> None:
        self._title_var.set(title)
        self.title(title)

    def _make_title_button(self, glyph: str, command, fg_normal: str, fg_hover: str) -> tk.Label:
        btn = tk.Label(
            self._titlebar,
            text=glyph,
            bg=PANEL_2,
            fg=fg_normal,
            font=self._ICON_FONT,
            padx=14,
            cursor="hand2",
        )

        def _enter(_):
            try:
                btn.configure(fg=fg_hover)
            except tk.TclError:
                pass

        def _leave(_):
            try:
                btn.configure(fg=fg_normal)
            except tk.TclError:
                pass

        btn.bind("<Enter>", _enter)
        btn.bind("<Leave>", _leave)
        btn.bind("<Button-1>", lambda _e: command())
        return btn

    def _fade_in(self, step: int = 0):
        a = min(1.0, step / 14)
        try:
            self.attributes("-alpha", a)
        except Exception:
            return
        if a < 1.0:
            self.after(12, lambda: self._fade_in(step + 1))

    # ---------------- Move ----------------

    def _start_move(self, e):
        if self._resize_mode:
            return
        if self._is_maximized and self._show_maximize:
            self.toggle_maximize()
        self._drag_active = True
        self._drag_off_x = e.x_root - self.winfo_x()
        self._drag_off_y = e.y_root - self.winfo_y()

    def _do_move(self, e):
        if not self._drag_active or self._is_maximized:
            return
        x = e.x_root - self._drag_off_x
        y = e.y_root - self._drag_off_y
        self._queue_geometry(f"+{x}+{y}")

    def _stop_move(self, _e):
        self._drag_active = False
        if self._geom_pending:
            self._queue_geometry(self._geom_pending, immediate=True)

    # ---------------- Resize ----------------

    def _hit_test(self, mx: int, my: int) -> str | None:
        w = self._surface.winfo_width()
        h = self._surface.winfo_height()
        m = self.RESIZE_MARGIN

        left = mx <= m
        right = mx >= w - m
        top = my <= m
        bottom = my >= h - m

        if top and left:
            return "nw"
        if top and right:
            return "ne"
        if bottom and left:
            return "sw"
        if bottom and right:
            return "se"
        if left:
            return "w"
        if right:
            return "e"
        if top:
            return "n"
        if bottom:
            return "s"
        return None

    def _set_cursor_by_mode(self, mode: str | None) -> None:
        if self._is_maximized:
            self._surface.configure(cursor="")
            return
        cursor = {
            "n": "sb_v_double_arrow",
            "s": "sb_v_double_arrow",
            "e": "sb_h_double_arrow",
            "w": "sb_h_double_arrow",
            "ne": "size_ne_sw",
            "sw": "size_ne_sw",
            "nw": "size_nw_se",
            "se": "size_nw_se",
        }.get(mode, "")
        self._surface.configure(cursor=cursor)

    def _start_resize(self, e):
        if self._is_maximized:
            return
        mode = self._hit_test(e.x, e.y)
        if not mode:
            self._resize_mode = None
            return

        self._resize_mode = mode
        self.update_idletasks()
        x = self.winfo_x()
        y = self.winfo_y()
        w = self.winfo_width()
        h = self.winfo_height()
        self._resize_start = (x, y, w, h, e.x_root, e.y_root)

    def _do_resize(self, e):
        if not self._resize_mode:
            return

        x, y, w, h, sx, sy = self._resize_start
        dx = e.x_root - sx
        dy = e.y_root - sy

        try:
            min_w, min_h = self.minsize()
        except Exception:
            min_w, min_h = (320, 240)

        min_w = max(320, int(min_w or 320))
        min_h = max(240, int(min_h or 240))

        nx, ny, nw, nh = x, y, w, h

        if "e" in self._resize_mode:
            nw = max(min_w, w + dx)
        if "s" in self._resize_mode:
            nh = max(min_h, h + dy)
        if "w" in self._resize_mode:
            nw = max(min_w, w - dx)
            nx = x + (w - nw)
        if "n" in self._resize_mode:
            nh = max(min_h, h - dy)
            ny = y + (h - nh)

        self._queue_geometry(f"{nw}x{nh}+{nx}+{ny}")

    def _stop_resize(self, _e):
        self._resize_mode = None
        if self._geom_pending:
            self._queue_geometry(self._geom_pending, immediate=True)

    # ---------------- Window controls ----------------

    def close(self):
        self.destroy()

    def minimize(self):
        self.iconify()
        self.after(250, self._apply_win_styles)

    def toggle_maximize(self):
        if not self._show_maximize:
            return

        if not self._is_maximized:
            self._restore_geom = self.geometry()
            self._maximize_to_workarea()
            self._is_maximized = True
            if self._btn_max is not None:
                self._btn_max.configure(text=self._GLYPH_RESTORE)
        else:
            if self._restore_geom:
                self.geometry(self._restore_geom)
            self._is_maximized = False
            if self._btn_max is not None:
                self._btn_max.configure(text=self._GLYPH_MAX)

        self.after(60, self._apply_win_styles)

    def _maximize_to_workarea(self):
        if sys.platform == "win32":
            x, y, w, h = _get_workarea()
            if w > 0 and h > 0:
                self.geometry(f"{w}x{h}+{x}+{y}")
                return
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{sw}x{sh}+0+0")
