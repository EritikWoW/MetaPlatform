# MetaPlatform/platform/launcher_app.py
from __future__ import annotations

import sys
import subprocess
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

from .ui_style import apply_theme
from .db_catalog import load_catalog, add_db, remove_db, DbEntry
from .paths import DB_EXT
from .window_chrome import ChromeWindow

from src.ui_qt.i18n import (
    init_i18n,
    t,
    bind,
    set_lang,
    get_lang,
    DISPLAY_TO_LANG,
    lang_display,
)


def _file_exists(p: str) -> bool:
    return Path(p).exists()


def _open_in_explorer(path: Path) -> None:
    subprocess.Popen(["explorer", str(path)])


def _norm_path(p: str) -> str:
    try:
        return Path(p).resolve().as_posix().lower()
    except Exception:
        return str(p).replace("\\", "/").lower()


class LauncherApp(ChromeWindow):
    def __init__(self):
        init_i18n(default_lang="en")

        super().__init__(title="MetaPlatform", fade_in=True, show_maximize=False)
        apply_theme(self)

        self.geometry("760x420")
        self.minsize(720, 400)

        self.dbs: list[DbEntry] = load_catalog()
        self._filtered_dbs: list[DbEntry] = []
        self._last_selected_path: str | None = None

        # Treeview column fit
        self._col_fit_job: str | None = None

        self._build_ui()

        # global i18n updates
        bind(self._apply_texts, widget=self)
        self._apply_texts()

        self._refresh()

    def _build_ui(self):
        # layout root content
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=0)  # header
        self.content.rowconfigure(1, weight=1)  # main
        self.content.rowconfigure(2, weight=0)  # bottom

        # ===== Header =====
        top = ttk.Frame(self.content, padding=(12, 10, 12, 6))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        top.columnconfigure(1, weight=0)

        self._subtitle_label = ttk.Label(top, text="", style="Subtle.TLabel")
        self._subtitle_label.grid(row=0, column=0, sticky="w")

        # Language selector (global)
        self.lang_var = tk.StringVar(value=lang_display(get_lang()))
        self.lang_box = ttk.Combobox(
            top,
            textvariable=self.lang_var,
            state="readonly",
            width=12,
            values=["English", "Українська"],
            style="App.TCombobox",
        )
        self.lang_box.grid(row=0, column=1, sticky="e")
        self.lang_box.bind("<<ComboboxSelected>>", self._on_lang_changed)
        from .ui_style import bind_combobox_popdown_styling
        bind_combobox_popdown_styling(self, self.lang_box)

        # ===== Main =====
        main = ttk.Frame(self.content, padding=(12, 6, 12, 10))
        main.grid(row=1, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=0)
        main.rowconfigure(0, weight=1)

        # ===== Left =====
        left = ttk.Frame(main)
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=0)
        left.columnconfigure(1, weight=1)
        left.rowconfigure(1, weight=1)

        self._list_label = ttk.Label(left, text="", style="H2.TLabel")
        self._list_label.grid(row=0, column=0, sticky="w", padx=(0, 10), pady=(0, 6))

        self.search_var = tk.StringVar(value="")
        self.search_entry = ttk.Entry(left, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=1, sticky="ew", pady=(0, 6))
        self.search_entry.bind("<KeyRelease>", lambda _e: self._refresh())

        # Table wrap
        table_wrap = ttk.Frame(left, style="Card.TFrame", padding=8)
        table_wrap.grid(row=1, column=0, columnspan=2, sticky="nsew")
        table_wrap.columnconfigure(0, weight=1)
        table_wrap.rowconfigure(0, weight=1)

        columns = ("name", "path", "status")
        self.tree = ttk.Treeview(
            table_wrap,
            columns=columns,
            show="headings",
            selectmode="browse",
            style="Data.Treeview",
        )

        self.tree.heading("name", text="")
        self.tree.heading("path", text="")
        self.tree.heading("status", text="")

        # Initial sizes (auto-fit will correct)
        self.tree.column("name", width=180, anchor="w", stretch=False)
        self.tree.column("path", width=420, anchor="w", stretch=True)
        self.tree.column("status", width=90, anchor="center", stretch=False)

        vsb = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns", padx=(8, 0))

        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())
        self.tree.bind("<Double-1>", lambda _e: self.run_client())

        # Auto-fit (right column sometimes invisible at start)
        self.tree.bind("<Configure>", self._schedule_fit_columns, add="+")
        self.after(0, self._fit_tree_columns)
        self.after(120, self._fit_tree_columns)

        # Info
        # self.exists_var = tk.StringVar(value="")

        info = ttk.Frame(left)
        info.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        info.columnconfigure(1, weight=1)

        # self._info_status_label = ttk.Label(info, text="", style="Subtle.TLabel")
        # self._info_status_label.grid(row=0, column=0, sticky="w")
        # ttk.Label(info, textvariable=self.exists_var).grid(row=0, column=1, sticky="w", padx=(8, 0))

        # ===== Right =====
        right = ttk.Frame(main)
        right.grid(row=0, column=1, sticky="n", padx=(14, 0))
        right.columnconfigure(0, weight=1)

        self.btn_client = ttk.Button(right, text="", width=22, style="Primary.TButton", command=self.run_client)
        self.btn_client.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self.btn_config = ttk.Button(right, text="", width=22, style="Secondary.TButton", command=self.run_configurator)
        self.btn_config.grid(row=1, column=0, sticky="ew", pady=(0, 14))

        ttk.Separator(right).grid(row=2, column=0, sticky="ew", pady=(0, 10))

        self.btn_add = ttk.Button(right, text="", width=22, command=self.add_db_ui)
        self.btn_add.grid(row=3, column=0, sticky="ew", pady=(0, 8))

        self.btn_remove = ttk.Button(right, text="", width=22, command=self.remove_db_ui)
        self.btn_remove.grid(row=4, column=0, sticky="ew", pady=(0, 8))

        self.btn_open = ttk.Button(right, text="", width=22, command=self.open_db_folder)
        self.btn_open.grid(row=5, column=0, sticky="ew")

        # ===== Bottom =====
        bottom = ttk.Frame(self.content, padding=(12, 0, 12, 10))
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)

        self.status_var = tk.StringVar(value=t("status_ready"))
        ttk.Label(bottom, textvariable=self.status_var, style="Subtle.TLabel").grid(row=0, column=0, sticky="w")

    # ---------------- Localization ----------------
    def _on_lang_changed(self, _e=None):
        disp = self.lang_var.get()
        code = DISPLAY_TO_LANG.get(disp, "en")
        set_lang(code)  # triggers bound callbacks

    def _apply_texts(self):
        # keep combobox in sync (e.g. when loaded from settings)
        self.lang_var.set(lang_display(get_lang()))

        self.set_title(t("launcher_title"))
        self._subtitle_label.configure(text=t("launcher_subtitle"))

        self._list_label.configure(text=t("list_label"))
        # self._info_status_label.configure(text=t("lbl_status"))

        self.tree.heading("name", text=t("col_name"))
        self.tree.heading("path", text=t("col_path"))
        self.tree.heading("status", text=t("col_status"))

        self.btn_client.configure(text=t("btn_client"))
        self.btn_config.configure(text=t("btn_config"))
        self.btn_add.configure(text=t("btn_add"))
        self.btn_remove.configure(text=t("btn_remove"))
        self.btn_open.configure(text=t("btn_open_folder"))

        # refresh table text (statuses) and bottom line
        self._refresh()

    # ---------------- Treeview columns auto-fit ----------------
    def _schedule_fit_columns(self, _e=None):
        if self._col_fit_job is not None:
            try:
                self.after_cancel(self._col_fit_job)
            except Exception:
                pass
        self._col_fit_job = self.after(25, self._fit_tree_columns)

    def _fit_tree_columns(self):
        self._col_fit_job = None

        w = int(self.tree.winfo_width() or 0)
        if w < 50:
            return

        name_w = 180
        status_w = 90
        reserve = 24  # чтобы правая колонка не "съедалась" при первом layout

        path_w = max(200, w - name_w - status_w - reserve)

        self.tree.column("name", width=name_w, minwidth=140, stretch=False)
        self.tree.column("status", width=status_w, minwidth=80, stretch=False)
        self.tree.column("path", width=path_w, minwidth=200, stretch=True)

    # ---------------- Data refresh ----------------
    def _refresh(self):
        q = self.search_var.get().strip().lower() if hasattr(self, "search_var") else ""
        all_dbs = list(self.dbs)

        if q:
            all_dbs = [x for x in all_dbs if q in x.name.lower() or q in x.path.lower()]

        self._filtered_dbs = all_dbs

        # current = self._selected_db()
        # if current:
        #     self._last_selected_path = current.path

        for item in self.tree.get_children():
            self.tree.delete(item)

        for i, db in enumerate(self._filtered_dbs):
            exists = _file_exists(db.path)
            status = t("status_ok") if exists else t("status_no_file")
            self.tree.insert("", "end", iid=str(i), values=(db.name, db.path, status))

        if self._last_selected_path:
            self._select_by_path(self._last_selected_path)

        # if not self._selected_db():
        #     self.exists_var.set("—")

        self._sync_action_buttons()

        self.status_var.set(t("count_line", total=len(self.dbs), shown=len(self._filtered_dbs)))
        self.after(0, self._fit_tree_columns)

    def _select_by_path(self, path: str) -> None:
        target = _norm_path(path)
        for i, db in enumerate(self._filtered_dbs):
            if _norm_path(db.path) == target:
                self.tree.selection_set(str(i))
                self.tree.focus(str(i))
                self.tree.see(str(i))
                self._on_select()
                return

    def _selected_index(self) -> int | None:
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except ValueError:
            return None

    def _selected_db(self) -> DbEntry | None:
        idx = self._selected_index()
        if idx is None:
            return None
        if not (0 <= idx < len(self._filtered_dbs)):
            return None
        return self._filtered_dbs[idx]

    def _sync_action_buttons(self):
        db = self._selected_db()
        enabled = bool(db and _file_exists(db.path))
        state = "normal" if enabled else "disabled"
        self.btn_client.configure(state=state)
        self.btn_config.configure(state=state)

    def _on_select(self):
        db = self._selected_db()
        if not db:
            # self.exists_var.set("—")
            self._sync_action_buttons()
            return

        # self.exists_var.set(t("status_file_found") if _file_exists(db.path) else t("status_file_missing"))
        self._last_selected_path = db.path
        self._sync_action_buttons()

    # ---------------- Actions ----------------
    def add_db_ui(self):
        action = messagebox.askyesno(
            t("dlg_add_title"),
            t("dlg_add_question"),
        )

        if action:
            file_path = filedialog.askopenfilename(
                title=t("dlg_pick_db"),
                filetypes=[("MetaPlatform DB", f"*{DB_EXT}"), ("All files", "*.*")],
            )
            if not file_path:
                return
        else:
            file_path = filedialog.asksaveasfilename(
                title=t("dlg_create_db"),
                defaultextension=DB_EXT,
                filetypes=[("MetaPlatform DB", f"*{DB_EXT}")],
            )
            if not file_path:
                return
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            Path(file_path).touch(exist_ok=True)

        default_name = Path(file_path).stem
        name = simpledialog.askstring(
            t("dlg_db_name_title"),
            t("dlg_db_name_prompt"),
            initialvalue=default_name,
        )
        if not name:
            return

        self.dbs = add_db(self.dbs, name=name, db_path=file_path)
        self._last_selected_path = str(Path(file_path).resolve())
        self._refresh()
        self.status_var.set(t("status_added", name=name))

    def remove_db_ui(self):
        db = self._selected_db()
        if not db:
            messagebox.showinfo(t("dlg_remove_title"), t("dlg_remove_pick"))
            return

        if not messagebox.askyesno(
            t("dlg_remove_confirm_title"),
            t("dlg_remove_confirm_text", name=db.name),
        ):
            return

        norm = _norm_path(db.path)
        idx_real = next((i for i, x in enumerate(self.dbs) if _norm_path(x.path) == norm), None)
        if idx_real is not None:
            self.dbs = remove_db(self.dbs, idx_real)

        self._last_selected_path = None
        self._refresh()
        self.status_var.set(t("status_removed", name=db.name))

    def open_db_folder(self):
        db = self._selected_db()
        if not db:
            messagebox.showinfo(t("dlg_open_title"), t("dlg_open_pick"))
            return

        p = Path(db.path)
        if p.exists():
            _open_in_explorer(p.parent)
        else:
            messagebox.showwarning(t("dlg_open_title"), t("dlg_open_missing"))

    def _spawn_module(self, module: str, db_path: str):
        src_dir = Path(__file__).resolve().parents[2]
        cmd = [sys.executable, "-m", module, "--db", db_path]
        subprocess.Popen(cmd, cwd=str(src_dir))

    def run_client(self):
        db = self._selected_db()
        if not db:
            messagebox.showinfo(t("dlg_client_title"), t("dlg_pick_db_first"))
            return
        if not _file_exists(db.path):
            messagebox.showwarning(t("dlg_client_title"), t("dlg_bad_db_file"))
            return
        self._spawn_module("MetaPlatform.client.client_app", db.path)

    def run_configurator(self):
        db = self._selected_db()
        if not db:
            messagebox.showinfo(t("dlg_config_title"), t("dlg_pick_db_first"))
            return
        if not _file_exists(db.path):
            messagebox.showwarning(t("dlg_config_title"), t("dlg_bad_db_file"))
            return
        self._spawn_module("MetaPlatform.configurator.configurator_app", db.path)


def main():
    app = LauncherApp()
    app.mainloop()


if __name__ == "__main__":
    main()
