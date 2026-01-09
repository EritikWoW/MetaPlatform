from __future__ import annotations

import argparse
from pathlib import Path
import tkinter as tk
from tkinter import ttk

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="Путь к файлу БД (.mpdb)")
    args = parser.parse_args()

    db_file = Path(args.db).resolve()

    root = tk.Tk()
    root.title("MetaPlatform — Клиентская часть")
    root.geometry("520x220")
    root.minsize(520, 220)

    frm = ttk.Frame(root, padding=12)
    frm.pack(fill="both", expand=True)

    ttk.Label(frm, text="Клиентская часть", font=("Segoe UI", 12, "bold")).pack(anchor="w")
    ttk.Label(frm, text="БД-файл: {db_file}", wraplength=480).pack(anchor="w", pady=(10, 0))

    ttk.Separator(frm).pack(fill="x", pady=12)
    ttk.Button(frm, text="Закрыть", command=root.destroy).pack(anchor="e")

    root.mainloop()

if __name__ == "__main__":
    main()
