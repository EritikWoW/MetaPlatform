from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List

from src.platform.paths import get_user_config_dir

from pathlib import Path
from src.mpdb.mpdb import Mpdb
from src.configurator.manifest_io import ensure_manifest


@dataclass(frozen=True)
class DbEntry:
    name: str
    kind: str = "local"  # local|remote
    path: str = ""       # for local
    runtime_url: str = "http://127.0.0.1:8765"
    autostart: bool = True
    db_uid: str = ""     # stable DB identity (uuid)


_CATALOG_PATH = get_user_config_dir() / "db_catalog.json"



def load_catalog() -> List[DbEntry]:
    try:
        if _CATALOG_PATH.exists():
            data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
            rows = data.get("dbs") if isinstance(data, dict) else data
            out: List[DbEntry] = []
            if isinstance(rows, list):
                for x in rows:
                    if not isinstance(x, dict):
                        continue
                    name = str(x.get("name") or "").strip()
                    if not name:
                        continue
                    kind = str(x.get("kind") or "local").strip().lower()
                    runtime_url = str(x.get("runtime_url") or "http://127.0.0.1:8765").strip().rstrip("/")
                    autostart = bool(x.get("autostart", True))
                    db_uid = str(x.get("db_uid") or "").strip()
                    path = str(x.get("path") or "").strip()
                    # Backward compatibility: old format had only name/path.
                    if kind == "local":
                        if path:
                            out.append(DbEntry(name=name, kind="local", path=path, runtime_url=runtime_url,
                                              autostart=autostart, db_uid=db_uid))
                    else:
                        # remote may be saved without db_uid yet (first bind later)
                        out.append(DbEntry(name=name, kind="remote", path="", runtime_url=runtime_url,
                                          autostart=False, db_uid=db_uid))
            return out
    except Exception:
        pass
    return []

def save_catalog(dbs: List[DbEntry]) -> None:
    _CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"dbs": [
        {
            "name": x.name,
            "kind": x.kind,
            "path": x.path,
            "runtime_url": x.runtime_url,
            "autostart": bool(x.autostart),
            "db_uid": x.db_uid,
        } for x in dbs
    ]}
    _CATALOG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def add_entry(dbs: List[DbEntry], entry: DbEntry) -> List[DbEntry]:
    # Local: de-dup by path (case-insensitive). Remote: de-dup by (runtime_url, db_uid or name).
    out: List[DbEntry] = []
    if entry.kind == "local":
        norm_new = str(Path(entry.path).resolve()).lower()
        found = False
        for x in dbs:
            if x.kind == "local":
                norm_x = str(Path(x.path).resolve()).lower()
                if norm_x == norm_new:
                    found = True
                    out.append(entry)
                    continue
            out.append(x)
        if not found:
            out.append(entry)
        return out

    # remote
    key_new = (entry.runtime_url.rstrip("/"), entry.db_uid or entry.name)
    found = False
    for x in dbs:
        if x.kind == "remote":
            key_x = (x.runtime_url.rstrip("/"), x.db_uid or x.name)
            if key_x == key_new:
                found = True
                out.append(entry)
                continue
        out.append(x)
    if not found:
        out.append(entry)
    return out


def remove_entry_by_path(dbs: List[DbEntry], path: str) -> List[DbEntry]:
    norm = str(Path(path).resolve()).lower()
    return [x for x in dbs if str(Path(x.path).resolve()).lower() != norm]


# ---------------------------------------------------------------------------
# Public API expected by LauncherApp
# ---------------------------------------------------------------------------


def add_db(dbs: List[DbEntry], *, name: str, db_path: str) -> List[DbEntry]:
    """Add DB entry to catalog and persist.

    Launcher imports add_db/remove_db. Keep these wrappers stable.
    """
    entry = DbEntry(name=str(name).strip(), path=str(db_path).strip())
    out = add_entry(dbs, entry)
    save_catalog(out)
    return out


def remove_db(dbs: List[DbEntry], index: int, *, delete_file: bool = False) -> List[DbEntry]:
    """Remove DB entry by index and persist.

    If delete_file=True, also попытаться удалить файл БД с диска.
    """
    if index < 0 or index >= len(dbs):
        return dbs

    entry = dbs[index]
    out = [x for i, x in enumerate(dbs) if i != index]
    save_catalog(out)

    if delete_file:
        try:
            p = Path(entry.path)
            if p.exists() and p.is_file():
                p.unlink()
        except Exception:
            # удаление файла может не получиться (lock на Windows) — это не должно ломать UI
            pass

    return out



def _seed_assets(db: Mpdb) -> None:
    """Store bundled UI assets (PNG/SVG/ICO) inside the database.

    This keeps the runtime self-contained: no mandatory dependency on loose files.
    """
    root = Path(__file__).resolve().parents[1]  # .../src
    assets_dir = root / "assets"
    if not assets_dir.exists():
        return

    def mime_for(path: Path) -> str:
        ext = path.suffix.lower()
        if ext == ".svg":
            return "image/svg+xml"
        if ext == ".png":
            return "image/png"
        if ext == ".ico":
            return "image/x-icon"
        return "application/octet-stream"

    # Persist all assets under keys like: assets/icons/svg/xxx.svg
    # IMPORTANT: bulk-write in a single transaction (dramatically faster).
    items: list[tuple[str, bytes, str]] = []
    for fp in assets_dir.rglob("*"):
        if not fp.is_file():
            continue
        if fp.suffix.lower() not in {".svg", ".png", ".ico"}:
            continue
        rel_key = fp.relative_to(root).as_posix()  # assets/...
        # IMPORTANT: do not embed huge icon packs into META mapping.
        # META is stored in a single page in mpdb MVP; storing thousands of
        # asset keys would overflow it. Icon packs can be embedded later via a
        # dedicated assets table/index. For now, keep only small core assets.
        if rel_key.startswith("assets/icons/"):
            continue
        try:
            items.append((rel_key, fp.read_bytes(), mime_for(fp)))
        except Exception:
            continue

    try:
        db.put_assets_bulk(items)
    except Exception:
        # Seeding assets must not break DB creation.
        pass

def init_new_database_file(db_file: Path) -> None:
    db_file.parent.mkdir(parents=True, exist_ok=True)

    # ВАЖНО: не делаем "touch 0 байт". Открываем mpdb — он сам запишет header/meta.
    db = Mpdb(str(db_file))
    try:
        # 1) создаём системные таблицы (пока MVP: через ensure_manifest или отдельный ensure_sys_tables)
        ensure_manifest(db, seed_defaults=True)  # или ensure_sys_tables(db) + seed_system_config(db)

        # 2) seed bundled assets (PNG/SVG/ICO) into mpdb
        _seed_assets(db)

        # 3) желательно: принудительная фиксация/компакция, чтобы всё точно оказалось в основном файле
        db.compact()
    finally:
        db.close()


def create_new_metadb_in_directory(base_dir: Path) -> Path:
    """Create a new MetaPlatform DB *structure* in the given directory.

    The directory is expected to be chosen by the user (1C-like "Catalog").
    We create a "MetaDB" subfolder and put the main mpdb file there.

    Returns the full path to the created mpdb file.
    """

    base_dir = Path(base_dir).expanduser().resolve()
    meta_dir = base_dir / "MetaDB"
    if meta_dir.exists():
        # Keep message text in UI (launcher) for a localized error.
        raise FileExistsError(str(meta_dir))

    # Reserve folders (future: WAL/logs/tmp, etc.)
    (meta_dir / "logs").mkdir(parents=True, exist_ok=True)
    (meta_dir / "tmp").mkdir(parents=True, exist_ok=True)
    (meta_dir / "wal").mkdir(parents=True, exist_ok=True)

    db_file = meta_dir / "metabase.mpdb"
    init_new_database_file(db_file)
    return db_file
