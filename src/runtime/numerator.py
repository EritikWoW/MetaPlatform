"""src.runtime.numerator — Thread-safe document number sequences.

A Numerator generates unique sequential numbers for documents.

Features:
    - Per document type sequences (Invoice → INV-0001)
    - Period-based resets: yearly, monthly, or none
    - Prefix and suffix templates: {year}, {month}
    - Stored in sys_numerators table (persisted in mpdb)
    - Thread-safe via advisory lock per doc type

Usage:
    num = Numerator(db)
    code = num.next("Invoice")           # → "0001"
    code = num.next("Invoice",           # → "INV-2024-0001"
                     prefix="INV-{year}-",
                     width=4)
    num.reset("Invoice")                 # → resets to 1
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

NUMERATORS_TABLE = "sys_numerators"

# Schema for the numerators table
_NUMERATORS_SCHEMA = {
    "doc_type":      {"type": "str", "unique": True, "indexed": True},
    "current_value": {"type": "int"},
    "prefix":        {"type": "str"},
    "suffix":        {"type": "str"},
    "width":         {"type": "int"},
    "period_reset":  {"type": "str"},   # "none" | "year" | "month"
    "period_key":    {"type": "str"},   # "2024" | "2024-01" | ""
    "updated_at":    {"type": "int"},
}

# Thread-local locks per (db_uid, doc_type)
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_META = threading.Lock()


def _get_lock(key: str) -> threading.Lock:
    with _LOCKS_META:
        if key not in _LOCKS:
            _LOCKS[key] = threading.Lock()
        return _LOCKS[key]


def _now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def _period_key(reset: str) -> str:
    now = datetime.now(tz=timezone.utc)
    if reset == "year":
        return str(now.year)
    if reset == "month":
        return f"{now.year}-{now.month:02d}"
    return ""


def _fmt_prefix(template: str) -> str:
    now = datetime.now(tz=timezone.utc)
    return (
        template
        .replace("{year}",  str(now.year))
        .replace("{month}", f"{now.month:02d}")
        .replace("{day}",   f"{now.day:02d}")
    )


class Numerator:
    """Document number sequence manager.

    Parameters
    ----------
    db : Mpdb
        Open database handle.  Table ``sys_numerators`` is auto-created.
    """

    def __init__(self, db) -> None:
        self._db    = db
        self._uid   = getattr(db, "db_uid", id(db))
        self._ready = False

    # ── public ──────────────────────────────────────────────────────────────

    def next(self,
             doc_type: str,
             *,
             prefix:       str = "",
             suffix:       str = "",
             width:        int = 4,
             period_reset: str = "none") -> str:
        """Return the next number string for ``doc_type``.

        Parameters
        ----------
        doc_type:     Document type name (e.g. "Invoice").
        prefix:       Prefix template. Supports {year}, {month}, {day}.
        suffix:       Suffix appended after the number.
        width:        Zero-pad width for the integer part.
        period_reset: When to auto-reset counter: "none", "year", "month".

        Returns
        -------
        Formatted number string, e.g. "INV-2024-0001".
        """
        self._ensure_table()
        lock_key = f"{self._uid}:{doc_type}"
        with _get_lock(lock_key):
            return self._atomic_next(
                doc_type, prefix=prefix, suffix=suffix,
                width=width, period_reset=period_reset,
            )

    def reset(self, doc_type: str, *, to: int = 0) -> None:
        """Reset the counter for ``doc_type`` to ``to``."""
        self._ensure_table()
        lock_key = f"{self._uid}:{doc_type}"
        with _get_lock(lock_key):
            self._ensure_row(doc_type)
            self._db.table(NUMERATORS_TABLE).update(
                {"doc_type": doc_type},
                {"current_value": to, "updated_at": _now_ms()},
            )

    def peek(self, doc_type: str) -> int:
        """Return current counter value without incrementing."""
        self._ensure_table()
        rows = self._db.table(NUMERATORS_TABLE).select(
            where={"doc_type": doc_type}
        ) or []
        if rows:
            return int(rows[0].get("current_value") or 0)
        return 0

    def configure(self, doc_type: str, *,
                  prefix:       str = "",
                  suffix:       str = "",
                  width:        int = 4,
                  period_reset: str = "none") -> None:
        """Set default parameters for a document type."""
        self._ensure_table()
        self._ensure_row(doc_type)
        self._db.table(NUMERATORS_TABLE).update(
            {"doc_type": doc_type},
            {
                "prefix":       prefix,
                "suffix":       suffix,
                "width":        width,
                "period_reset": period_reset,
                "updated_at":   _now_ms(),
            },
        )

    # ── private ─────────────────────────────────────────────────────────────

    def _ensure_table(self) -> None:
        if self._ready:
            return
        try:
            self._db.table(NUMERATORS_TABLE)
            self._ready = True
            return
        except Exception:
            pass
        self._db.create_table(NUMERATORS_TABLE, schema=_NUMERATORS_SCHEMA)
        self._ready = True

    def _ensure_row(self, doc_type: str) -> None:
        rows = self._db.table(NUMERATORS_TABLE).select(
            where={"doc_type": doc_type}
        ) or []
        if not rows:
            self._db.table(NUMERATORS_TABLE).insert({
                "doc_type":      doc_type,
                "current_value": 0,
                "prefix":        "",
                "suffix":        "",
                "width":         4,
                "period_reset":  "none",
                "period_key":    "",
                "updated_at":    _now_ms(),
            })

    def _atomic_next(self, doc_type: str, *,
                     prefix: str, suffix: str,
                     width: int, period_reset: str) -> str:
        """Increment counter and return formatted number (must be called under lock)."""
        self._ensure_row(doc_type)

        rows = self._db.table(NUMERATORS_TABLE).select(
            where={"doc_type": doc_type}
        ) or []
        row = rows[0] if rows else {}

        # Load stored defaults if caller didn't override
        eff_prefix = prefix or str(row.get("prefix") or "")
        eff_suffix = suffix or str(row.get("suffix") or "")
        eff_width  = width if width != 4 else int(row.get("width") or 4)
        eff_reset  = period_reset if period_reset != "none" else str(
            row.get("period_reset") or "none")

        # Period reset check
        new_period_key = _period_key(eff_reset)
        old_period_key = str(row.get("period_key") or "")
        current = int(row.get("current_value") or 0)

        if eff_reset != "none" and new_period_key != old_period_key:
            current = 0  # reset

        new_value = current + 1

        self._db.table(NUMERATORS_TABLE).update(
            {"doc_type": doc_type},
            {
                "current_value": new_value,
                "period_key":    new_period_key,
                "updated_at":    _now_ms(),
            },
        )

        formatted_prefix = _fmt_prefix(eff_prefix)
        number_part = str(new_value).zfill(max(1, eff_width))
        return f"{formatted_prefix}{number_part}{eff_suffix}"
