from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


def get_registry_path() -> Path:
    """Return path to runtime DB registry JSON."""
    env = os.environ.get("META_RUNTIME_DB_REGISTRY")
    if env:
        return Path(env).expanduser().resolve()

    program_data = os.environ.get("PROGRAMDATA") or os.environ.get("ProgramData")
    if program_data:
        return (Path(program_data) / "MetaPlatform" / "runtime" / "db_registry.json").resolve()

    return (Path.home() / ".config" / "MetaPlatform" / "runtime" / "db_registry.json").resolve()


@dataclass
class RegistryDb:
    db_uid: str
    name: str
    path: str
    enabled: bool = True


class DbRegistry:
    """Server-side registry of known databases.

    This is the source of truth for a remote runtime: clients must not send paths.
    """

    def __init__(self, items: Optional[List[RegistryDb]] = None) -> None:
        self.items: List[RegistryDb] = items or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "databases": [
                {
                    "db_uid": x.db_uid,
                    "name": x.name,
                    "path": x.path,
                    "enabled": bool(x.enabled),
                }
                for x in self.items
            ]
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "DbRegistry":
        out: List[RegistryDb] = []
        rows = d.get("databases") if isinstance(d, dict) else None
        if isinstance(rows, list):
            for r in rows:
                if not isinstance(r, dict):
                    continue
                db_uid = str(r.get("db_uid") or "").strip()
                name = str(r.get("name") or "").strip()
                path = str(r.get("path") or "").strip()
                enabled = bool(r.get("enabled", True))
                if db_uid and path:
                    out.append(RegistryDb(db_uid=db_uid, name=name or db_uid, path=path, enabled=enabled))
        return DbRegistry(out)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "DbRegistry":
        p = path or get_registry_path()
        try:
            if p.exists():
                return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
        return cls([])

    def save(self, path: Optional[Path] = None) -> None:
        p = path or get_registry_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def upsert(self, item: RegistryDb) -> None:
        for i, x in enumerate(self.items):
            if x.db_uid == item.db_uid:
                self.items[i] = item
                return
        self.items.append(item)

    def remove(self, db_uid: str) -> bool:
        before = len(self.items)
        self.items = [x for x in self.items if x.db_uid != db_uid]
        return len(self.items) != before

    def get(self, db_uid: str) -> Optional[RegistryDb]:
        for x in self.items:
            if x.db_uid == db_uid:
                return x
        return None

    def list_enabled(self) -> List[RegistryDb]:
        return [x for x in self.items if x.enabled]
