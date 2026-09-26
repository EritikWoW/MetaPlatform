from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from mpdb import Mpdb


_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")


def _norm_name(name: str) -> str:
    name = str(name).strip()
    if not _NAME_RE.match(name):
        raise ValueError(f"Invalid object name: {name!r}")
    return name


def _table(name: str) -> str:
    # mpdb tables are stored in META; keep stable, simple naming.
    return name


@dataclass(frozen=True)
class Catalog:
    name: str
    table: str


@dataclass(frozen=True)
class Document:
    name: str
    header_table: str
    rows_table: str


@dataclass(frozen=True)
class Register:
    """Accumulation register (append-only movements journal).

    MVP semantics:
    - Movements are immutable records.
    - Query helpers (balance/turnover) aggregate in Python.
    - Indexes are created on `period` and each dimension field.
    """

    name: str
    table: str
    dimensions: Tuple[str, ...]
    resources: Tuple[str, ...]


class MpPlatform:
    """Minimal platform layer.

    This is a pragmatic v1.0 scaffold to unblock UI/Configurator development.
    It provides stable logical constructs without changing mpdb internals.
    """

    def __init__(self, db: Mpdb):
        self.db = db

    # ------------------------- catalogs -------------------------

    def create_catalog(self, name: str) -> Catalog:
        name = _norm_name(name)
        tbl = _table(f"cat_{name}")
        # Flexible 'data' field keeps custom реквизиты without schema churn.
        schema = {
            "fields": {
                "code": "str",
                "name": "str",
                "data": "json",
            }
        }
        try:
            self.db.create_table(tbl, schema)
        except Exception:
            # Idempotent: table may already exist.
            pass
        return Catalog(name=name, table=tbl)

    def catalog_insert(self, catalog: Catalog, *, code: str, name: str, data: Optional[Dict[str, Any]] = None) -> int:
        t = self.db.table(catalog.table)
        rec = {"code": str(code), "name": str(name), "data": data or {}}
        return int(t.insert(rec))

    def catalog_get(self, catalog: Catalog, rec_id: int) -> Optional[Dict[str, Any]]:
        t = self.db.table(catalog.table)
        rows = t.select(where={"rowid": int(rec_id)})
        return rows[0] if rows else None

    def catalog_find(self, catalog: Catalog, where: Optional[Dict[str, Any]] = None, *, order_by: Optional[str] = None) -> List[Dict[str, Any]]:
        t = self.db.table(catalog.table)
        return t.select(where=where, order_by=order_by)

    def catalog_update(self, catalog: Catalog, rec_id: int, *, code: Optional[str] = None, name: Optional[str] = None, data: Optional[Dict[str, Any]] = None) -> None:
        t = self.db.table(catalog.table)
        patch: Dict[str, Any] = {}
        if code is not None:
            patch["code"] = str(code)
        if name is not None:
            patch["name"] = str(name)
        if data is not None:
            patch["data"] = data
        if patch:
            t.update({"rowid": int(rec_id)}, patch)

    def catalog_delete(self, catalog: Catalog, rec_id: int) -> None:
        t = self.db.table(catalog.table)
        t.delete({"rowid": int(rec_id)})

    # ------------------------- documents -------------------------

    def create_document(self, name: str) -> Document:
        name = _norm_name(name)
        hdr = _table(f"doc_{name}_hdr")
        rows = _table(f"doc_{name}_rows")
        hdr_schema = {
            "fields": {
                "number": "str",
                "date": "int",  # unix ms
                "data": "json",
            }
        }
        rows_schema = {
            "fields": {
                "doc_id": "int",
                "line_no": "int",
                "data": "json",
            }
        }
        try:
            self.db.create_table(hdr, hdr_schema)
        except Exception:
            pass
        try:
            self.db.create_table(rows, rows_schema)
        except Exception:
            pass
        return Document(name=name, header_table=hdr, rows_table=rows)

    def document_create(self, doc: Document, *, header: Dict[str, Any], rows: List[Dict[str, Any]]) -> int:
        """Create document with rows in a single transaction."""
        hdr_t = self.db.table(doc.header_table)
        rows_t = self.db.table(doc.rows_table)

        with self.db.transaction():
            doc_id = int(hdr_t.insert({
                "number": str(header.get("number", "")),
                "date": int(header.get("date", 0)),
                "data": header.get("data", {}),
            }))
            for i, row in enumerate(rows, start=1):
                rows_t.insert({"doc_id": doc_id, "line_no": i, "data": row})
        return doc_id

    def document_read(self, doc: Document, doc_id: int) -> Optional[Tuple[Dict[str, Any], List[Dict[str, Any]]]]:
        hdr_t = self.db.table(doc.header_table)
        rows_t = self.db.table(doc.rows_table)
        hdr = hdr_t.select(where={"rowid": int(doc_id)})
        if not hdr:
            return None
        rows = rows_t.select(where={"doc_id": int(doc_id)}, order_by="line_no")
        # return normalized payloads
        header = hdr[0]
        row_payloads = [r.get("data", {}) for r in rows]
        return header, row_payloads

    # ------------------------- registers -------------------------

    def create_register(self, name: str, *, dimensions: List[str], resources: List[str]) -> Register:
        """Create an accumulation register.

        Storage model (single table):
        - period: int (unix ms)
        - doc_id: int (optional binding)
        - dim_<name>: scalar (str/int/bool) per declared dimension
        - res_<name>: number (int/float) per declared resource

        Indexes:
        - period (indexed)
        - each dim_* (indexed)
        """
        name = _norm_name(name)
        tbl = _table(f"reg_{name}")
        dims = tuple(_norm_name(d) for d in dimensions)
        ress = tuple(_norm_name(r) for r in resources)

        # Flat schema mapping enables mpdb secondary indexes.
        schema: Dict[str, Any] = {
            "period": {"type": "int", "indexed": True},
            "doc_id": {"type": "int", "indexed": True},
        }
        for d in dims:
            schema[f"dim_{d}"] = {"type": "scalar", "indexed": True}
        for r in ress:
            schema[f"res_{r}"] = {"type": "number"}

        try:
            self.db.create_table(tbl, schema)
        except Exception:
            pass
        return Register(name=name, table=tbl, dimensions=dims, resources=ress)

    def register_post(
        self,
        reg: Register,
        *,
        period: int,
        doc_id: int = 0,
        dimensions: Optional[Dict[str, Any]] = None,
        resources: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Append a single movement."""
        dimensions = dimensions or {}
        resources = resources or {}

        row: Dict[str, Any] = {
            "period": int(period),
            "doc_id": int(doc_id),
        }
        for d in reg.dimensions:
            if d in dimensions:
                row[f"dim_{d}"] = dimensions[d]
        for r in reg.resources:
            if r in resources:
                row[f"res_{r}"] = resources[r]

        t = self.db.table(reg.table)
        return int(t.insert(row))

    def register_find(
        self,
        reg: Register,
        where: Optional[Dict[str, Any]] = None,
        *,
        order_by: Optional[str] = "period",
    ) -> List[Dict[str, Any]]:
        """Low-level query helper."""
        t = self.db.table(reg.table)
        return t.select(where=where, order_by=order_by)

    def register_balance(
        self,
        reg: Register,
        *,
        as_of: Optional[int] = None,
        dimensions: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, float]:
        """Compute balance by summing resources up to `as_of` (inclusive)."""
        dimensions = dimensions or {}
        # MVP: scan and aggregate; can be optimized later with persistent aggregates.
        rows = self.register_find(reg, where=None, order_by=None)
        out = {r: 0.0 for r in reg.resources}
        for row in rows:
            p = int(row.get("period", 0))
            if as_of is not None and p > int(as_of):
                continue
            ok = True
            for d, v in dimensions.items():
                d = _norm_name(d)
                if row.get(f"dim_{d}") != v:
                    ok = False
                    break
            if not ok:
                continue
            for r in reg.resources:
                val = row.get(f"res_{r}")
                if val is None:
                    continue
                out[r] += float(val)
        return out

    def register_turnover(
        self,
        reg: Register,
        *,
        start: int,
        end: int,
        dimensions: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, float]:
        """Compute turnover (sum of resources) for [start, end]."""
        dimensions = dimensions or {}
        rows = self.register_find(reg, where=None, order_by=None)
        out = {r: 0.0 for r in reg.resources}
        for row in rows:
            p = int(row.get("period", 0))
            if p < int(start) or p > int(end):
                continue
            ok = True
            for d, v in dimensions.items():
                d = _norm_name(d)
                if row.get(f"dim_{d}") != v:
                    ok = False
                    break
            if not ok:
                continue
            for r in reg.resources:
                val = row.get(f"res_{r}")
                if val is None:
                    continue
                out[r] += float(val)
        return out
