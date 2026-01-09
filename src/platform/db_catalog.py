from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List

from src.platform.paths import get_user_config_dir


@dataclass(frozen=True)
class DbEntry:
    name: str
    path: str


_CATALOG_PATH = get_user_config_dir() / "db_catalog.json"


def load_catalog() -> List[DbEntry]:
    try:
        if _CATALOG_PATH.exists():
            data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
            rows = data.get("dbs") if isinstance(data, dict) else data
            out: List[DbEntry] = []
            if isinstance(rows, list):
                for x in rows:
                    if isinstance(x, dict):
                        name = str(x.get("name") or "").strip()
                        path = str(x.get("path") or "").strip()
                        if name and path:
                            out.append(DbEntry(name=name, path=path))
            return out
    except Exception:
        pass
    return []


def save_catalog(dbs: List[DbEntry]) -> None:
    _CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"dbs": [{"name": x.name, "path": x.path} for x in dbs]}
    _CATALOG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def add_entry(dbs: List[DbEntry], entry: DbEntry) -> List[DbEntry]:
    # Не допускаем дубликаты по пути (case-insensitive для Windows)
    norm_new = str(Path(entry.path).resolve()).lower()
    out: List[DbEntry] = []
    found = False
    for x in dbs:
        norm_x = str(Path(x.path).resolve()).lower()
        if norm_x == norm_new:
            found = True
            out.append(entry)  # обновим имя/путь
        else:
            out.append(x)
    if not found:
        out.append(entry)
    return out


def remove_entry_by_path(dbs: List[DbEntry], path: str) -> List[DbEntry]:
    norm = str(Path(path).resolve()).lower()
    return [x for x in dbs if str(Path(x.path).resolve()).lower() != norm]
