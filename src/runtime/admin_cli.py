from __future__ import annotations

import argparse
from pathlib import Path

from src.mpdb.mpdb import Mpdb
from src.runtime.db_registry import DbRegistry, RegistryDb, get_registry_path


def _get_db_uid(db_path: str) -> str:
    db = Mpdb(db_path)
    try:
        uid = db.db_uid
        name = str(db.meta.get("name") or "") if hasattr(db, "meta") else ""
    finally:
        db.close()
    if not uid:
        raise RuntimeError("DB uid is empty; cannot register")
    return uid


def _load() -> DbRegistry:
    return DbRegistry.load()


def _save(reg: DbRegistry) -> None:
    reg.save()


def _print(reg: DbRegistry) -> None:
    rows = reg.items
    if not rows:
        print("(registry is empty)")
        return
    for x in rows:
        mark = "EN" if x.enabled else "DIS"
        print(f"{mark} {x.db_uid}  {x.name}  {x.path}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="meta-runtime-admin", description="MetaPlatform runtime registry admin")
    p.add_argument("--registry", default=str(get_registry_path()), help="Path to db_registry.json")

    sub = p.add_subparsers(dest="cmd", required=True)

    s_list = sub.add_parser("list", help="List registered databases")

    s_add = sub.add_parser("add", help="Add or update database by path")
    s_add.add_argument("path", help="Path to .mpdb file")
    s_add.add_argument("--name", default="", help="Display name")
    s_add.add_argument("--disable", action="store_true", help="Add disabled")

    s_remove = sub.add_parser("remove", help="Remove database by uid")
    s_remove.add_argument("db_uid")

    s_enable = sub.add_parser("enable", help="Enable database by uid")
    s_enable.add_argument("db_uid")

    s_disable = sub.add_parser("disable", help="Disable database by uid")
    s_disable.add_argument("db_uid")

    args = p.parse_args(argv)

    reg_path = Path(args.registry).expanduser().resolve()
    reg = DbRegistry.load(reg_path)

    if args.cmd == "list":
        _print(reg)
        return 0

    if args.cmd == "add":
        db_path = str(Path(args.path).expanduser().resolve())
        uid = _get_db_uid(db_path)
        name = (args.name or "").strip() or Path(db_path).stem
        item = RegistryDb(db_uid=uid, name=name, path=db_path, enabled=not bool(args.disable))
        reg.upsert(item)
        reg.save(reg_path)
        print(f"OK added: {uid} ({name})")
        return 0

    if args.cmd == "remove":
        ok = reg.remove(str(args.db_uid))
        reg.save(reg_path)
        print("OK" if ok else "NOT FOUND")
        return 0

    if args.cmd in {"enable", "disable"}:
        uid = str(getattr(args, "db_uid"))
        item = reg.get(uid)
        if not item:
            print("NOT FOUND")
            return 2
        item.enabled = (args.cmd == "enable")
        reg.upsert(item)
        reg.save(reg_path)
        print("OK")
        return 0

    print("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
