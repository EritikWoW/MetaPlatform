from __future__ import annotations

import re
import contextlib
import io
import logging
from typing import Any


_FILES_RE = re.compile(r'"Files"\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)', re.IGNORECASE)


def _set_table_files(table: Any, files: tuple[int, int, int]) -> None:
    data_oid, blob_oid, index_oid = files
    table.files = [str(data_oid), str(blob_oid), str(index_oid)]
    table.data_object_id = int(data_oid) or None
    table.blob_object_id = int(blob_oid) or None
    table.index_object_id = int(index_oid) or None


def _recover_missing_83_table_files(db: Any) -> int:
    """Recover 8.3 table `Files` descriptors split/noised across catalog pages.

    Some 8.3 descriptor pages contain binary separators inside decoded UTF-8
    text. The upstream parser can still find the table/fields, but brace
    matching may stop before the `{"Files", data, blob, index}` section. This
    pass scans descriptor pages around known table names and restores object ids
    without relying on configuration-specific GUIDs or table names.
    """
    tables = getattr(db, "tables", {}) or {}
    missing = {
        str(name): table
        for name, table in tables.items()
        if not int(getattr(table, "data_object_id", 0) or 0)
    }
    if not missing:
        return 0

    header = getattr(db, "header", None)
    total_pages = int(getattr(header, "total_pages", 0) or 0)
    if total_pages <= 2:
        return 0

    recovered = 0
    encoded_names = {name: name.encode("utf-8", errors="ignore") for name in missing}
    for page_num in range(2, total_pages):
        try:
            page = db._read_page(page_num)
        except Exception:
            continue
        if not page:
            continue
        candidates = [name for name, raw in encoded_names.items() if raw and raw in page]
        if not candidates:
            continue
        raw_window = bytearray(page)
        for offset in range(1, 5):
            if page_num + offset >= total_pages:
                break
            try:
                next_page = db._read_page(page_num + offset)
            except Exception:
                break
            if not next_page:
                break
            raw_window.extend(next_page)
            if len(raw_window) >= 65536:
                break
        if b'"Files"' not in raw_window:
            continue
        try:
            text = bytes(raw_window).decode("utf-8", errors="ignore")
        except Exception:
            continue
        for name in list(candidates):
            table = missing.get(name)
            if table is None:
                continue
            pos = text.find(name)
            if pos < 0:
                continue
            match = _FILES_RE.search(text[pos : pos + 16384])
            if not match:
                continue
            _set_table_files(table, tuple(int(group) for group in match.groups()))
            missing.pop(name, None)
            encoded_names.pop(name, None)
            recovered += 1
        if not missing:
            break
    if missing:
        recovered += _recover_missing_83_table_files_from_alternate_parser(db, missing)
    return recovered


def _recover_missing_83_table_files_from_alternate_parser(db: Any, missing: dict[str, Any]) -> int:
    """Let legacy readers recover descriptors through the bundled core."""
    source_path = str(getattr(db, "filepath", "") or "").strip()
    if not source_path:
        return 0
    try:
        from src.infra.onec.data_migration import _load_parse1cd_backend

        backend = _load_parse1cd_backend()
        alt_cls = backend.database_parser.OneCDatabase
        if isinstance(db, alt_cls):
            return 0
    except Exception:
        return 0

    try:
        alt_db = alt_cls(source_path)
    except Exception:
        return 0

    recovered = 0
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            opened = bool(alt_db.open())
        if not opened:
            return 0
        for name, table in list(missing.items()):
            try:
                alt_table = alt_db.get_table_info(name)
            except Exception:
                alt_table = None
            files_raw = list(getattr(alt_table, "files", []) or []) if alt_table is not None else []
            if len(files_raw) < 3:
                continue
            try:
                files = tuple(int(value or 0) for value in files_raw[:3])
            except Exception:
                continue
            if int(files[0] or 0) <= 0:
                continue
            _set_table_files(table, files)
            missing.pop(name, None)
            recovered += 1
    finally:
        try:
            alt_db.close()
        except Exception:
            pass
    return recovered


def patch_parse1cd_database_parser(database_parser: Any) -> None:
    cls = getattr(database_parser, "OneCDatabase", None)
    if cls is None or bool(getattr(cls, "_metaplatform_83_link_patch", False)):
        return

    if not hasattr(cls, "_collect_data_pages_83_from_header") or not hasattr(cls, "_read_page"):
        cls._metaplatform_83_link_patch = True
        return

    page_sig_83 = getattr(database_parser, "PAGE_SIG_83", b"\x1c\xfd")

    def _link_data_83(self) -> None:
        """Patched 8.3 data linker with descriptor recovery for split tables."""
        _recover_missing_83_table_files(self)
        for tbl in (getattr(self, "tables", {}) or {}).values():
            if (getattr(self, "_table_data_pages", {}) or {}).get(tbl.name):
                continue
            oid = int(getattr(tbl, "data_object_id", 0) or 0)
            if oid <= 0:
                continue
            if oid >= int(getattr(getattr(self, "header", None), "total_pages", 0) or 0):
                continue
            page = self._read_page(oid)
            if not page:
                continue

            if page[:2] == page_sig_83:
                pages = self._collect_data_pages_83_from_header(page)
                if pages:
                    self._table_data_pages[tbl.name] = pages
                    continue

            if not all(byte == 0 for byte in page[:32]):
                try:
                    text = page[:200].decode("utf-8", errors="ignore")
                    if '{"' not in text or '"Fields"' not in text:
                        self._table_data_pages[tbl.name] = [oid]
                except Exception:
                    pass

        linked = sum(1 for value in (getattr(self, "_table_data_pages", {}) or {}).values() if value)
        logging.getLogger(__name__).debug(
            "Linked %s/%s legacy 1CD tables", linked, len(getattr(self, "tables", {}) or {})
        )

    cls._link_data_83 = _link_data_83
    cls._metaplatform_83_link_patch = True


__all__ = ["patch_parse1cd_database_parser"]
