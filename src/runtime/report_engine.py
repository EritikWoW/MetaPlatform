"""src.runtime.report_engine — MetaScript-driven report execution engine.

A Report object in the manifest has:
    - Parameters folder: parameter definitions (name, type, default)
    - Modules/Module: MetaScript code that runs and returns result rows
    - Forms: optional designed output form

The engine:
    1. Accepts a dict of parameter values
    2. Executes the report's main module (OnGenerate or the only module)
    3. Returns ReportResult with column defs + data rows
    4. Optionally exports to CSV / XLSX

Usage:
    engine = ReportEngine(db, manifest_rows)
    result = engine.run("SalesSummary", params={"DateFrom": "2024-01-01"})
    csv_text = result.to_csv()
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ─────────────────────────────────── domain ────────────────────────────────

@dataclass
class ReportColumn:
    key:     str
    title:   str
    type:    str = "str"   # str | number | date | bool
    width:   int = 120


@dataclass
class ReportResult:
    """Computed report: column definitions + data rows."""

    report_name:  str
    title:        str
    columns:      List[ReportColumn]
    rows:         List[Dict[str, Any]]
    params_used:  Dict[str, Any]
    messages:     List[str] = field(default_factory=list)
    ok:           bool = True

    # ── export ────────────────────────────────────────────────────────

    def to_csv(self, *, delimiter: str = ";") -> str:
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=delimiter)
        w.writerow([c.title for c in self.columns])
        for row in self.rows:
            w.writerow([row.get(c.key, "") for c in self.columns])
        return buf.getvalue()

    def to_json(self) -> str:
        return json.dumps(
            {
                "report":  self.report_name,
                "title":   self.title,
                "columns": [{"key": c.key, "title": c.title, "type": c.type}
                            for c in self.columns],
                "rows":    self.rows,
            },
            ensure_ascii=False,
            default=str,
        )

    def to_xlsx_bytes(self) -> bytes:
        """Export to XLSX bytes (requires openpyxl)."""
        try:
            import openpyxl
            from openpyxl.styles import Font
        except ImportError:
            raise RuntimeError(
                "openpyxl is not installed — run: pip install openpyxl"
            )
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = self.title[:31] if self.title else self.report_name

        # Header row
        header = [c.title for c in self.columns]
        ws.append(header)
        for cell in ws[1]:
            cell.font = Font(bold=True)

        # Data rows
        for row in self.rows:
            ws.append([row.get(c.key, "") for c in self.columns])

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()


# ─────────────────────────────────── engine ────────────────────────────────

class ReportEngine:
    """Execute reports defined in the manifest.

    Parameters
    ----------
    db : Mpdb
        Open database handle.
    manifest_rows : list
        Pre-loaded manifest rows (avoids repeated DB reads).
    """

    def __init__(self, db, manifest_rows: list) -> None:
        self._db    = db
        self._mrows = manifest_rows

    # ── public ──────────────────────────────────────────────────────────────

    def run(self, report_name: str,
            params: Optional[Dict[str, Any]] = None) -> ReportResult:
        """Run a named report and return the result."""
        params = dict(params or {})
        result = ReportResult(
            report_name=report_name,
            title="",
            columns=[],
            rows=[],
            params_used=params,
        )

        # Find manifest object
        obj = self._find_report(report_name)
        if obj is None:
            result.ok = False
            result.messages.append(
                f"Report '{report_name}' not found in manifest"
            )
            return result

        result.title = self._i18n(obj.get("payload") or {},
                                  "title", report_name)

        # Resolve parameters (merge defaults + provided values)
        param_defs = self._load_param_defs(str(obj.get("guid") or ""))
        params = self._resolve_params(param_defs, params)
        result.params_used = params

        # Find and execute module
        script_spec = self._load_module(str(obj.get("guid") or ""))
        if not script_spec:
            # Fallback: generic table dump
            return self._fallback_table(result, obj)
        script, module_guid = script_spec

        # Build execution context
        rows_out: list = []
        columns_out: list = []

        def _add_row(row_dict: dict) -> None:
            rows_out.append(dict(row_dict))

        def _set_columns(cols: list) -> None:
            columns_out.clear()
            columns_out.extend(cols)

        ctx: Dict[str, Any] = {
            "Params":     params,
            "AddRow":     _add_row,
            "SetColumns": _set_columns,
            "DB":         self._db,
            "Message":    lambda msg: result.messages.append(str(msg)),
            # Convenience helpers
            "Query":      self._make_query_fn(),
        }

        try:
            from src.runtime.script.vm import execute_script
            execute_script(script, context=ctx, module_name=f"module://{module_guid}" if module_guid else "")
        except Exception as e:
            result.ok = False
            result.messages.append(f"Report execution error: {e}")
            return result

        # Auto-detect columns from first row if SetColumns wasn't called
        if not columns_out and rows_out:
            for key in rows_out[0].keys():
                if not key.startswith("_"):
                    columns_out.append({"key": key, "title": key})

        result.columns = [
            ReportColumn(
                key=c.get("key", c.get("name", "")),
                title=c.get("title", c.get("key", "")),
                type=c.get("type", "str"),
                width=int(c.get("width", 120)),
            )
            for c in columns_out
        ]
        result.rows = rows_out
        return result

    def list_reports(self) -> List[Dict[str, Any]]:
        """Return all report objects from manifest."""
        out = []
        for r in self._mrows:
            if (str(r.get("type") or "").strip().lower() == "report"
                    and str(r.get("kind") or "") == "object"):
                pay = r.get("payload") or {}
                out.append({
                    "guid":  str(r.get("guid") or ""),
                    "name":  str(r.get("name") or ""),
                    "title": self._i18n(pay if isinstance(pay, dict) else {},
                                        "title", str(r.get("name") or "")),
                })
        return out

    # ── private ─────────────────────────────────────────────────────────────

    def _find_report(self, name: str) -> Optional[dict]:
        name_l = name.strip().lower()
        for r in self._mrows:
            if (str(r.get("type") or "").strip().lower() == "report"
                    and str(r.get("kind") or "") == "object"
                    and str(r.get("name") or "").strip().lower() == name_l):
                return dict(r)
        return None

    def _load_param_defs(self, owner_guid: str) -> List[dict]:
        """Load parameter definitions from manifest."""
        params_folder = next(
            (str(r.get("guid") or "")
             for r in self._mrows
             if str(r.get("parent_guid") or "") == owner_guid
             and str(r.get("type") or "").lower() in (
                 "parameters", "parameters_folder")),
            None,
        )
        if not params_folder:
            return []
        return [
            dict(r)
            for r in self._mrows
            if str(r.get("parent_guid") or "") == params_folder
        ]

    def _resolve_params(self, param_defs: list,
                        provided: Dict[str, Any]) -> Dict[str, Any]:
        """Merge defaults with provided values."""
        result: Dict[str, Any] = {}
        for pdef in param_defs:
            name = str(pdef.get("name") or "").strip()
            if not name:
                continue
            pay = pdef.get("payload") or {}
            default = pay.get("default") if isinstance(pay, dict) else None
            result[name] = provided.get(name, default)
        # Pass through provided params not in defs
        result.update(provided)
        return result

    def _load_module(self, owner_guid: str) -> Optional[tuple[str, str]]:
        """Find OnGenerate module text (or any module under this report)."""
        modules_folder = next(
            (str(r.get("guid") or "")
             for r in self._mrows
             if str(r.get("parent_guid") or "") == owner_guid
             and str(r.get("type") or "").lower() in (
                 "modules", "modules_folder")),
            None,
        )
        if not modules_folder:
            return None
        # Prefer OnGenerate, else take the first module
        module_guid: Optional[str] = None
        first_guid: Optional[str] = None
        for r in self._mrows:
            if str(r.get("parent_guid") or "") != modules_folder:
                continue
            g = str(r.get("guid") or "")
            if first_guid is None:
                first_guid = g
            if str(r.get("name") or "").strip().lower() in (
                    "ongenerate", "generate", "main"):
                module_guid = g
                break
        target = module_guid or first_guid
        if not target:
            return None
        try:
            from src.configurator.persistence.modules_dao import get_module_text
            return get_module_text(self._db, module_guid=target), target
        except Exception:
            return None

    def _make_query_fn(self):
        """Return a Query(table, where=None, order_by=None) helper for scripts."""
        db = self._db

        def _query(table: str, where=None, order_by: str | None = None):
            try:
                rows = db.table(table).select(where=where, order_by=order_by)
                return rows or []
            except Exception:
                return []

        return _query

    def _fallback_table(self, result: ReportResult, obj: dict) -> ReportResult:
        """If no module: look for a data_report_* table and dump it."""
        name = str(obj.get("name") or "").strip().lower()
        tbl = f"data_report_{name}"
        try:
            rows = self._db.table(tbl).select() or []
            if rows:
                keys = [k for k in rows[0] if not k.startswith("_")]
                result.columns = [ReportColumn(key=k, title=k) for k in keys]
                result.rows = [
                    {k: r.get(k) for k in keys} for r in rows
                ]
        except Exception:
            pass
        if not result.columns:
            result.ok = False
            result.messages.append("No module and no fallback table found")
        return result

    @staticmethod
    def _i18n(payload: dict, key: str, fallback: str = "") -> str:
        val = payload.get(key, {})
        if isinstance(val, dict):
            return str(val.get("uk") or val.get("en") or fallback)
        return str(val or fallback)
