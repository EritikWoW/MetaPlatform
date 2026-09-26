from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeContext:
    """Runtime connection context exported by the launcher."""

    runtime_url: str
    session_id: str
    db_name: str = ""
    db_path: str = ""   # legacy bridge — local path for non-RPC code
    db_uid:  str = ""   # UID of the active database on the server

    @classmethod
    def from_env(cls) -> "RuntimeContext | None":
        url  = (os.environ.get("META_RUNTIME_URL") or "").strip()
        sid  = (os.environ.get("META_SESSION_ID")  or "").strip()
        name = (os.environ.get("META_DB_NAME")     or "").strip()
        path = (os.environ.get("META_DB_PATH")     or "").strip()
        uid  = (os.environ.get("META_DB_UID")      or "").strip()
        if not url or not sid:
            return None
        return cls(runtime_url=url, session_id=sid, db_name=name,
                   db_path=path, db_uid=uid)

    def as_status_text(self) -> str:
        return f"Runtime: {self.runtime_url} | session: {self.session_id}"
