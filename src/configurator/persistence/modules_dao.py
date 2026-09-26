from __future__ import annotations

import bisect
import hashlib
import json
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.infra.onec.module_transform import normalize_module_text, sanitize_imported_module_text
from src.mpdb.mpdb import Mpdb
from src.mpdb.mpdb import PAGE_HDR_SIZE, _data_page_can_fit

from .modules_tables import MODULES_TABLE, ensure_modules_tables
from .table_storage import reset_table_storage


# ---------------------------------------------------------------------------
# Deterministic UUIDv5 (without importing stdlib uuid)
# ---------------------------------------------------------------------------


_UUID_NS_DNS = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"  # RFC4122 DNS namespace
MODULE_ASSET_PREFIX = "module-src/"
MODULE_REFERENCE_MAP_ASSET = "system/module-reference-map.json"
_MODULE_ASSET_MIME = "text/plain"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _hex_to_bytes(h: str) -> bytes:
    h = str(h or "").strip().replace("-", "")
    return bytes.fromhex(h)


def _uuid5(namespace_uuid: str, name: str) -> str:
    """RFC4122 UUIDv5 (SHA1), implemented without importing stdlib `uuid`.

    Args:
        namespace_uuid: UUID string for namespace.
        name: name string.
    """

    ns = _hex_to_bytes(namespace_uuid)
    b = hashlib.sha1(ns + (name or "").encode("utf-8")).digest()
    u = bytearray(b[:16])
    # version 5
    u[6] = (u[6] & 0x0F) | 0x50
    # variant RFC4122
    u[8] = (u[8] & 0x3F) | 0x80
    h = bytes(u).hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def make_module_guid(
    *,
    owner_guid: str,
    owner_kind: str,
    module_kind: str,
    name: str,
    lang: str = "",
) -> str:
    """Create stable module GUID (uuid5) from module identity."""

    key = f"{owner_guid}:{owner_kind}:{module_kind}:{name}:{lang}".strip()
    return _uuid5(_UUID_NS_DNS, key)


def _sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def module_content_ref(*, module_guid: str) -> str:
    module_guid = str(module_guid or "").strip()
    return f"{MODULE_ASSET_PREFIX}{module_guid}.bsl" if module_guid else ""


def _prepare_module_row_storage(
    db: Mpdb,
    row: Dict[str, Any],
    *,
    preserve_asset_storage: bool = False,
) -> Tuple[Dict[str, Any], Optional[Tuple[str, Tuple[bytes, str]]]]:
    """Normalize module row storage.

    Small modules stay inline in cfg_modules.text.
    Oversized modules are moved to asset storage and cfg_modules keeps only metadata.
    """

    normalized = {
        "module_guid": str(row.get("module_guid") or "").strip(),
        "owner_guid": str(row.get("owner_guid") or ""),
        "owner_kind": str(row.get("owner_kind") or ""),
        "module_kind": str(row.get("module_kind") or ""),
        "name": str(row.get("name") or ""),
        "source_ref": str(row.get("source_ref") or ""),
        "canonical_ref": str(row.get("canonical_ref") or ""),
        "ref_uk": str(row.get("ref_uk") or ""),
        "ref_en": str(row.get("ref_en") or ""),
        "lang": str(row.get("lang") or ""),
        "text": str(row.get("text") or ""),
        "sha256": str(row.get("sha256") or ""),
        "version": int(row.get("version") or 1),
        "updated_at": int(row.get("updated_at") or _now_ms()),
        "updated_by": str(row.get("updated_by") or ""),
        "storage_kind": str(row.get("storage_kind") or ""),
        "content_ref": str(row.get("content_ref") or ""),
        "size_bytes": int(row.get("size_bytes") or 0),
    }
    text = sanitize_imported_module_text(str(normalized.get("text") or ""))
    normalized["text"] = text
    normalized["sha256"] = _sha256_text(text)
    data = text.encode("utf-8")
    normalized["size_bytes"] = int(len(data))

    probe = dict(normalized)
    probe["storage_kind"] = "inline"
    probe["content_ref"] = ""
    if preserve_asset_storage and str(normalized.get("storage_kind") or "").strip().lower() == "asset":
        asset_key = str(normalized.get("content_ref") or "").strip() or module_content_ref(
            module_guid=str(normalized.get("module_guid") or "")
        )
        normalized["storage_kind"] = "asset"
        normalized["content_ref"] = asset_key
        normalized["text"] = ""
        return normalized, (asset_key, (data, _MODULE_ASSET_MIME))
    if can_store_module_row(db, probe):
        normalized["storage_kind"] = "inline"
        normalized["content_ref"] = ""
        return normalized, None

    asset_key = str(normalized.get("content_ref") or "").strip() or module_content_ref(
        module_guid=str(normalized.get("module_guid") or "")
    )
    normalized["storage_kind"] = "asset"
    normalized["content_ref"] = asset_key
    normalized["text"] = ""
    return normalized, (asset_key, (data, _MODULE_ASSET_MIME))


# ---------------------------------------------------------------------------
# DAO
# ---------------------------------------------------------------------------


def upsert_module(
    db: Mpdb,
    *,
    owner_guid: str,
    owner_kind: str,
    module_kind: str,
    name: str,
    text: str,
    lang: str = "",
    source_ref: str = "",
    canonical_ref: str = "",
    ref_uk: str = "",
    ref_en: str = "",
    updated_by: str = "import",
) -> str:
    """Insert or update a module record; returns module_guid."""

    ensure_modules_tables(db)

    owner_guid = str(owner_guid or "").strip()
    owner_kind = str(owner_kind or "").strip()
    module_kind = str(module_kind or "").strip()
    name = str(name or "").strip()
    lang = str(lang or "").strip()
    text = sanitize_imported_module_text(str(text or ""))

    module_guid = make_module_guid(
        owner_guid=owner_guid,
        owner_kind=owner_kind,
        module_kind=module_kind,
        name=name,
        lang=lang,
    )

    sha = _sha256_text(text)
    tbl = db.table(MODULES_TABLE)
    existing = tbl.select(where={"module_guid": module_guid})

    now = _now_ms()
    base_row = {
        "module_guid": module_guid,
        "owner_guid": owner_guid,
        "owner_kind": owner_kind,
        "module_kind": module_kind,
        "name": name,
        "source_ref": str(source_ref or ""),
        "canonical_ref": str(canonical_ref or ""),
        "ref_uk": str(ref_uk or ""),
        "ref_en": str(ref_en or ""),
        "lang": lang,
        "text": text,
        "sha256": sha,
        "version": 1,
        "updated_at": now,
        "updated_by": str(updated_by or ""),
    }
    if existing:
        row = existing[0]
        prev_sha = str(row.get("sha256") or "")
        prev_ver = int(row.get("version") or 1)

        refs_changed = any(
            str(row.get(field) or "") != str(base_row.get(field) or "")
            for field in ("source_ref", "canonical_ref", "ref_uk", "ref_en")
        )
        if prev_sha == sha and not refs_changed:
            return module_guid

        prepared, asset_item = _prepare_module_row_storage(
            db,
            {
                **base_row,
                "version": int(prev_ver) + 1,
                "content_ref": str(row.get("content_ref") or ""),
            },
        )
        if asset_item is not None:
            db.put_asset(asset_item[0], asset_item[1][0], mime=asset_item[1][1])
        tbl.update(
            {"module_guid": module_guid},
            {
                "owner_guid": prepared["owner_guid"],
                "owner_kind": prepared["owner_kind"],
                "module_kind": prepared["module_kind"],
                "name": prepared["name"],
                "source_ref": prepared["source_ref"],
                "canonical_ref": prepared["canonical_ref"],
                "ref_uk": prepared["ref_uk"],
                "ref_en": prepared["ref_en"],
                "lang": prepared["lang"],
                "text": prepared["text"],
                "sha256": prepared["sha256"],
                "version": prepared["version"],
                "updated_at": prepared["updated_at"],
                "updated_by": prepared["updated_by"],
                "storage_kind": prepared["storage_kind"],
                "content_ref": prepared["content_ref"],
                "size_bytes": prepared["size_bytes"],
            },
        )
        return module_guid

    prepared, asset_item = _prepare_module_row_storage(db, base_row)
    if asset_item is not None:
        db.put_asset(asset_item[0], asset_item[1][0], mime=asset_item[1][1])
    tbl.insert(prepared)
    return module_guid


def make_module_row(
    *,
    owner_guid: str,
    owner_kind: str,
    module_kind: str,
    name: str,
    text: str,
    lang: str = "",
    source_ref: str = "",
    canonical_ref: str = "",
    ref_uk: str = "",
    ref_en: str = "",
    updated_by: str = "import",
) -> Dict[str, Any]:
    """Build a cfg_modules row with deterministic module_guid."""

    owner_guid = str(owner_guid or "").strip()
    owner_kind = str(owner_kind or "").strip()
    module_kind = str(module_kind or "").strip()
    name = str(name or "").strip()
    lang = str(lang or "").strip()
    text = sanitize_imported_module_text(str(text or ""))
    now = _now_ms()
    return {
        "module_guid": make_module_guid(
            owner_guid=owner_guid,
            owner_kind=owner_kind,
            module_kind=module_kind,
            name=name,
            lang=lang,
        ),
        "owner_guid": owner_guid,
        "owner_kind": owner_kind,
        "module_kind": module_kind,
        "name": name,
        "source_ref": str(source_ref or ""),
        "canonical_ref": str(canonical_ref or ""),
        "ref_uk": str(ref_uk or ""),
        "ref_en": str(ref_en or ""),
        "lang": lang,
        "text": text,
        "sha256": _sha256_text(text),
        "version": 1,
        "updated_at": now,
        "updated_by": str(updated_by or ""),
        "storage_kind": "inline",
        "content_ref": "",
        "size_bytes": len(text.encode("utf-8")),
    }


def can_store_module_row(db: Mpdb, row: Dict[str, Any]) -> bool:
    """Return True if the module row fits into a single mpdb table record."""

    packed_obj = {
        "rowid": 1,
        "data": db._intern_strings(dict(row)),  # noqa: SLF001 - exact size check against mpdb insert path
    }
    blob = json.dumps(packed_obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    max_payload = db.page_size - PAGE_HDR_SIZE
    return bool(_data_page_can_fit(max_payload, len(blob)))


def insert_modules_bulk(
    db: Mpdb,
    rows: List[Dict[str, Any]],
    *,
    progress: Optional[Callable[[int, int, str], None]] = None,
    update_existing: bool = False,
) -> int:
    """Insert module rows, optionally refreshing existing import identities.

    Oversized modules are transparently moved to asset storage.
    """

    if not rows:
        return 0

    def _emit_progress(current: int, total: int, message: str) -> None:
        if progress is None:
            return
        try:
            progress(int(current), int(total), str(message or ""))
        except Exception:
            pass

    ensure_modules_tables(db)
    table = db.table(MODULES_TABLE)
    existing_rows = {
        str(item.get("module_guid") or ""): dict(item)
        for item in (table.select() or [])
        if str(item.get("module_guid") or "")
    }
    prepared: List[Dict[str, Any]] = []
    updated_guids: set[str] = set()
    asset_batch: Dict[str, Tuple[bytes, str]] = {}
    seen: set[str] = set()
    for row in rows:
        module_guid = str(row.get("module_guid") or "").strip()
        if not module_guid or module_guid in seen:
            continue
        seen.add(module_guid)
        previous = existing_rows.get(module_guid)
        if previous is not None and not update_existing:
            continue
        if previous is not None:
            row = {
                **previous,
                **row,
                "version": int(previous.get("version") or 1) + (
                    1 if str(previous.get("sha256") or "") != str(row.get("sha256") or "") else 0
                ),
            }
        normalized, asset_item = _prepare_module_row_storage(db, row)
        if previous is not None:
            identity_fields = (
                "sha256", "source_ref", "canonical_ref", "ref_uk", "ref_en",
                "owner_guid", "owner_kind", "module_kind", "name", "lang",
            )
            if all(str(previous.get(field) or "") == str(normalized.get(field) or "") for field in identity_fields):
                continue
            updated_guids.add(module_guid)
        if asset_item is not None:
            asset_batch[asset_item[0]] = asset_item[1]
        prepared.append(
            normalized
        )

    if not prepared:
        return 0

    total_work = len(prepared) + len(asset_batch)
    done_work = 0

    if asset_batch:
        db.put_assets_bulk(
            [(key, data, mime) for key, (data, mime) in asset_batch.items()],
            progress=lambda current, total: _emit_progress(
                current,
                total_work,
                "Import manifest: Writing module assets",
            ),
        )
        done_work += len(asset_batch)

    with db.transaction() as tx:
        row_total = len(prepared)
        for index, row in enumerate(prepared, start=1):
            if str(row.get("module_guid") or "") in updated_guids:
                table.delete_tx(
                    tx,
                    {"module_guid": str(row.get("module_guid") or "")},
                    set_meta=False,
                )
            table.insert_tx(tx, row, set_meta=False)
            if index == row_total or index % 250 == 0:
                _emit_progress(
                    done_work + index,
                    total_work,
                    "Import manifest: Writing module rows",
                )
        tx.set_meta(db._meta)
    return len(prepared)


def replace_modules_bulk(db: Mpdb, rows: List[Dict[str, Any]]) -> int:
    """Replace cfg_modules contents with prepared rows in a single transaction."""

    ensure_modules_tables(db)
    reset_table_storage(db, MODULES_TABLE, drop_table=True)
    ensure_modules_tables(db)
    if not rows:
        return 0

    table = db.table(MODULES_TABLE)
    with db.transaction() as tx:
        for row in rows:
            table.insert_tx(tx, row, set_meta=False)
        tx.set_meta(db._meta)
    return int(len(rows))


def write_module_reference_map(db: Mpdb) -> int:
    """Publish the GUID-to-reference registry used by IDE and runtime resolvers."""

    ensure_modules_tables(db)
    rows = db.table(MODULES_TABLE).select(where=None, order_by="module_guid") or []
    entries: List[Dict[str, str]] = []
    for row in rows:
        module_guid = str(row.get("module_guid") or "").strip()
        if not module_guid:
            continue
        entries.append(
            {
                "id": module_guid,
                "source": str(row.get("source_ref") or ""),
                "canonical": str(row.get("canonical_ref") or ""),
                "uk": str(row.get("ref_uk") or ""),
                "en": str(row.get("ref_en") or ""),
            }
        )
    payload = {
        "version": 1,
        "kind": "module-reference-map",
        "count": len(entries),
        "modules": entries,
    }
    db.put_asset(
        MODULE_REFERENCE_MAP_ASSET,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        mime="application/json",
    )
    return len(entries)


def update_module_text(db: Mpdb, *, module_guid: str, text: str, updated_by: str = "user") -> None:
    ensure_modules_tables(db)
    module_guid = str(module_guid or "").strip()
    if not module_guid:
        return

    text = sanitize_imported_module_text(str(text or ""))
    sha = _sha256_text(text)
    tbl = db.table(MODULES_TABLE)
    existing = tbl.select(where={"module_guid": module_guid})
    if not existing:
        # Unknown module -> create minimal ownerless row (best-effort)
        upsert_module(
            db,
            owner_guid="",
            owner_kind="",
            module_kind="",
            name="",
            text=text,
            updated_by=updated_by,
        )
        return

    row = existing[0]
    prev_sha = str(row.get("sha256") or "")
    prev_ver = int(row.get("version") or 1)
    if prev_sha == sha:
        return

    prepared, asset_item = _prepare_module_row_storage(
        db,
        {
            **row,
            "module_guid": module_guid,
            "owner_guid": str(row.get("owner_guid") or ""),
            "owner_kind": str(row.get("owner_kind") or ""),
            "module_kind": str(row.get("module_kind") or ""),
            "name": str(row.get("name") or ""),
            "lang": str(row.get("lang") or ""),
            "text": text,
            "sha256": sha,
            "version": int(prev_ver) + 1,
            "updated_at": _now_ms(),
            "updated_by": str(updated_by or ""),
            "content_ref": str(row.get("content_ref") or ""),
        },
    )
    if asset_item is not None:
        db.put_asset(asset_item[0], asset_item[1][0], mime=asset_item[1][1])
    tbl.update(
        {"module_guid": module_guid},
        {
            "owner_guid": prepared["owner_guid"],
            "owner_kind": prepared["owner_kind"],
            "module_kind": prepared["module_kind"],
            "name": prepared["name"],
            "lang": prepared["lang"],
            "text": prepared["text"],
            "sha256": prepared["sha256"],
            "version": prepared["version"],
            "updated_at": prepared["updated_at"],
            "updated_by": prepared["updated_by"],
            "storage_kind": prepared["storage_kind"],
            "content_ref": prepared["content_ref"],
            "size_bytes": prepared["size_bytes"],
        },
    )


def apply_module_text_updates_atomic(
    db: Mpdb,
    updates: List[Dict[str, Any]],
    *,
    updated_by: str = "workspace_rename",
) -> Dict[str, Any]:
    """Optimistically replace multiple module texts as one visible commit.

    Oversized texts are written to immutable, hash-addressed assets first.
    Module rows switch to those assets in one cfg_modules transaction, so a
    failed row commit cannot expose a partial workspace refactoring.
    """

    ensure_modules_tables(db)
    requested = [
        dict(item)
        for item in list(updates or [])
        if isinstance(item, dict) and str(item.get("module_guid") or "").strip()
    ]
    if not requested:
        return {"updated": 0, "module_guids": []}
    guids = [str(item.get("module_guid") or "").strip() for item in requested]
    if len(set(guids)) != len(guids):
        raise ValueError("Duplicate module_guid in atomic module update")

    table = db.table(MODULES_TABLE)
    rows_by_guid: Dict[str, Dict[str, Any]] = {}
    for guid in guids:
        rows = table.select(where={"module_guid": guid}) or []
        if not rows:
            raise ValueError(f"Module was not found: {guid}")
        rows_by_guid[guid] = dict(rows[0])

    prepared_rows: List[Dict[str, Any]] = []
    asset_items: List[Tuple[str, bytes, str]] = []
    now = _now_ms()
    for item in requested:
        guid = str(item.get("module_guid") or "").strip()
        row = rows_by_guid[guid]
        current_text = get_module_text_from_row(db, row)
        current_hash = _sha256_text(current_text)
        expected_hash = str(item.get("source_hash") or "").strip()
        if expected_hash and current_hash != expected_hash:
            raise ValueError(
                f"Module source changed after preview: {guid}"
            )
        text = sanitize_imported_module_text(str(item.get("text") or ""))
        updated_hash = _sha256_text(text)
        expected_updated_hash = str(item.get("updated_hash") or "").strip()
        if expected_updated_hash and updated_hash != expected_updated_hash:
            raise ValueError(
                f"Updated module hash does not match preview: {guid}"
            )
        content_ref = (
            f"{MODULE_ASSET_PREFIX}{guid}-{updated_hash[:20]}.bsl"
        )
        prepared, asset_item = _prepare_module_row_storage(
            db,
        {
                **row,
                "module_guid": guid,
                "owner_guid": str(row.get("owner_guid") or ""),
                "owner_kind": str(row.get("owner_kind") or ""),
                "module_kind": str(row.get("module_kind") or ""),
                "name": str(row.get("name") or ""),
                "lang": str(row.get("lang") or ""),
                "text": text,
                "sha256": updated_hash,
                "version": int(row.get("version") or 1) + 1,
                "updated_at": now,
                "updated_by": str(updated_by or ""),
                "storage_kind": str(row.get("storage_kind") or ""),
                "content_ref": content_ref,
            },
            preserve_asset_storage=(
                str(row.get("storage_kind") or "").strip().lower() == "asset"
            ),
        )
        prepared_rows.append(prepared)
        if asset_item is not None:
            asset_items.append(
                (asset_item[0], asset_item[1][0], asset_item[1][1])
            )

    if asset_items:
        db.put_assets_bulk(asset_items)
    with db.transaction() as tx:
        for guid, prepared in zip(guids, prepared_rows):
            deleted = table.delete_tx(
                tx,
                {"module_guid": guid},
                set_meta=False,
            )
            if deleted != 1:
                raise ValueError(
                    f"Atomic module update expected one row for {guid}, got {deleted}"
                )
            table.insert_tx(tx, prepared, set_meta=False)
        tx.set_meta(db._meta)
    return {
        "updated": len(prepared_rows),
        "module_guids": guids,
    }


def get_module_text(db: Mpdb, *, module_guid: str) -> str:
    ensure_modules_tables(db)
    module_guid = str(module_guid or "").strip()
    if not module_guid:
        return ""
    rows = db.table(MODULES_TABLE).select(where={"module_guid": module_guid})
    if not rows:
        return ""
    row = rows[0]
    content_ref = str(row.get("content_ref") or "").strip()
    storage_kind = str(row.get("storage_kind") or "").strip().lower()
    if content_ref and storage_kind == "asset":
        try:
            data, _mime = db.get_asset(content_ref)
            return sanitize_imported_module_text(data.decode("utf-8"))
        except Exception:
            return ""
    return sanitize_imported_module_text(str(row.get("text") or ""))


def get_module_text_from_row(db: Mpdb, row: Dict[str, Any]) -> str:
    """Load module text using an already fetched cfg_modules row."""

    if not isinstance(row, dict):
        return ""
    content_ref = str(row.get("content_ref") or "").strip()
    storage_kind = str(row.get("storage_kind") or "").strip().lower()
    if content_ref and storage_kind == "asset":
        try:
            data, _mime = db.get_asset(content_ref)
            return sanitize_imported_module_text(data.decode("utf-8"))
        except Exception:
            return ""
    return sanitize_imported_module_text(str(row.get("text") or ""))


def list_modules_by_owner(db: Mpdb, *, owner_guid: str) -> List[Dict[str, Any]]:
    ensure_modules_tables(db)
    owner_guid = str(owner_guid or "").strip()
    if not owner_guid:
        return []
    return db.table(MODULES_TABLE).select(where={"owner_guid": owner_guid}, order_by="module_kind")


def search_module_text(
    db: Mpdb,
    *,
    term: str,
    match_case: bool = False,
    whole_word: bool = False,
    module_guid: str = "",
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """Search module sources inside Runtime and return compact line hits."""

    ensure_modules_tables(db)
    target_guid = str(module_guid or "").strip()
    where = {"module_guid": target_guid} if target_guid else None
    rows = db.table(MODULES_TABLE).select(where=where) or []
    sources = []
    for row in rows:
        item = dict(row)
        item["source_text"] = get_module_text_from_row(db, row)
        sources.append(item)
    return search_module_sources(
        sources,
        term=term,
        match_case=match_case,
        whole_word=whole_word,
        module_guid=target_guid,
        limit=limit,
    )


def search_module_sources(
    sources: List[Dict[str, Any]],
    *,
    term: str,
    match_case: bool = False,
    whole_word: bool = False,
    module_guid: str = "",
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """Search an already hydrated Runtime module-source cache."""

    term = str(term or "").strip()
    if not term:
        return []
    limit = max(1, min(int(limit or 500), 5000))
    target_guid = str(module_guid or "").strip()
    needle = term if match_case else term.casefold()
    hits: List[Dict[str, Any]] = []
    for row in sources:
        if target_guid and str(row.get("module_guid") or "").strip() != target_guid:
            continue
        text = str(row.get("source_text") or "")
        if not text:
            continue
        haystack = text if match_case else str(row.get("_source_text_casefold") or text.casefold())
        positions: List[int] = []
        offset = 0
        while True:
            position = haystack.find(needle, offset)
            if position < 0:
                break
            end = position + len(needle)
            if not whole_word or (
                (position == 0 or not _is_identifier_char(haystack[position - 1]))
                and (end >= len(haystack) or not _is_identifier_char(haystack[end]))
            ):
                positions.append(position)
            offset = max(end, position + 1)
        if not positions:
            continue
        line_starts = [0]
        line_starts.extend(match.end() for match in re.finditer(r"\n", text))
        lines = text.splitlines()
        for position in positions:
            line_index = max(0, bisect.bisect_right(line_starts, position) - 1)
            line_start = line_starts[line_index]
            hits.append(
                {
                    "module_guid": str(row.get("module_guid") or ""),
                    "owner_guid": str(row.get("owner_guid") or ""),
                    "module_kind": str(row.get("module_kind") or row.get("name") or "module"),
                    "name": str(row.get("name") or ""),
                    "line": line_index + 1,
                    "col": position - line_start + 1,
                    "preview": lines[line_index].strip() if line_index < len(lines) else "",
                }
            )
            if len(hits) >= limit:
                return hits
    return hits


def _is_identifier_char(value: str) -> bool:
    return bool(value) and (value == "_" or value.isalnum())


def resolve_common_module(
    db: Mpdb,
    *,
    name: str,
    manifest_rows: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any] | None:
    """Resolve one common-module namespace without hydrating the manifest.

    Imported 1C configurations keep a transliterated internal ``name`` while
    source code addresses the original Cyrillic metadata name stored in
    ``title``.  Both identities, plus ``CommonModule.<name>`` references, are
    accepted here.
    """

    requested = str(name or "").strip()
    if not requested:
        return None
    requested_aliases = {requested.casefold()}
    target = requested
    if "." in requested:
        prefix, suffix = requested.split(".", 1)
        if prefix.casefold() in {"commonmodule", "common_module"}:
            target = suffix.strip()
            requested_aliases.add(target.casefold())
    if target.casefold().endswith(".module"):
        requested_aliases.add(target.rsplit(".", 1)[0].casefold())
    if not target:
        return None

    from .manifest_io import list_object_rows

    candidates: List[Dict[str, Any]] = []
    strong_candidates: List[Dict[str, Any]] = []
    folded = target.casefold()
    rows = manifest_rows if manifest_rows is not None else list_object_rows(db)
    module_aliases_by_owner: Dict[str, set[str]] = {}
    ensure_modules_tables(db)
    for module_row in db.table(MODULES_TABLE).select() or []:
        owner_guid = str(module_row.get("owner_guid") or "").strip()
        if not owner_guid:
            continue
        aliases = module_aliases_by_owner.setdefault(owner_guid, set())
        for field in ("canonical_ref", "ref_uk", "ref_en"):
            reference = str(module_row.get(field) or "").strip()
            if not reference:
                continue
            aliases.add(reference.casefold())
            ref_parts = [part for part in reference.split(".") if part]
            if len(ref_parts) >= 3:
                aliases.add(".".join(ref_parts[:-1]).casefold())
                aliases.add(ref_parts[-2].casefold())
    for row in rows:
        if str(row.get("type") or "").strip().lower() != "common_module":
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        metadata_ref = str(payload.get("metadata_ref") or "").strip()
        aliases = {
            str(row.get("name") or "").strip().casefold(),
            str(row.get("title") or "").strip().casefold(),
            metadata_ref.casefold(),
            metadata_ref.rsplit(".", 1)[-1].casefold(),
            str(payload.get("source_name") or "").strip().casefold(),
        }
        strong_aliases = {
            str(row.get("name") or "").strip().casefold(),
            metadata_ref.casefold(),
            metadata_ref.rsplit(".", 1)[-1].casefold(),
            str(payload.get("source_name") or "").strip().casefold(),
        }
        localized_names = payload.get("localized_names") if isinstance(payload.get("localized_names"), dict) else {}
        aliases.update(str(value or "").strip().casefold() for value in localized_names.values())
        legacy_refs = payload.get("legacy_code_refs")
        if isinstance(legacy_refs, dict):
            legacy_values = legacy_refs.values()
        elif isinstance(legacy_refs, list):
            legacy_values = legacy_refs
        else:
            legacy_values = ()
        for value in legacy_values:
            reference = str(value or "").strip()
            if not reference:
                continue
            aliases.add(reference.casefold())
            aliases.add(reference.rsplit(".", 1)[-1].casefold())
        aliases.update(module_aliases_by_owner.get(str(row.get("guid") or "").strip(), set()))
        if folded in aliases or not requested_aliases.isdisjoint(aliases):
            candidates.append(dict(row))
            if folded in strong_aliases or not requested_aliases.isdisjoint(
                strong_aliases | module_aliases_by_owner.get(str(row.get("guid") or "").strip(), set())
            ):
                strong_candidates.append(dict(row))

    # A synonym is allowed only when it is unique. Never select the first
    # module for a repeated presentation name; callers must use Source Name or
    # a localized code reference in that case.
    if len(strong_candidates) == 1:
        candidates = strong_candidates
    elif len(strong_candidates) > 1:
        return None
    elif len(candidates) != 1:
        return None

    owner = next(
        (
            row
            for row in candidates
            if str(row.get("type") or "").strip().lower() == "common_module"
        ),
        None,
    )
    if not isinstance(owner, dict):
        return None
    owner_guid = str(owner.get("guid") or "").strip()
    if not owner_guid:
        return None

    modules = list_modules_by_owner(db, owner_guid=owner_guid)
    if not modules:
        return None
    module = next(
        (
            row
            for row in modules
            if str(row.get("module_kind") or "").strip().casefold() == "module"
        ),
        modules[0],
    )
    result = dict(module)
    result["owner_name"] = str(owner.get("name") or "")
    result["owner_title"] = str(owner.get("title") or "")
    result["owner_type"] = str(owner.get("type") or "")
    result["text"] = get_module_text_from_row(db, module)
    return result


def purge_all_modules(db: Mpdb) -> int:
    """Delete all module records."""
    try:
        ensure_modules_tables(db)
    except Exception:
        return 0
    tbl = db.table(MODULES_TABLE)
    rows = tbl.select(where=None)
    if not rows:
        try:
            db.delete_assets_by_prefixes(MODULE_ASSET_PREFIX)
        except Exception:
            pass
        return 0
    deleted = len(rows)
    try:
        db.delete_assets_by_prefixes(MODULE_ASSET_PREFIX)
    except Exception:
        pass
    reset_table_storage(db, MODULES_TABLE, drop_table=True)
    ensure_modules_tables(db)
    return int(deleted)


def normalize_modules_language(
    db: Mpdb,
    *,
    language: str,
    updated_by: str = "user",
) -> Dict[str, Any]:
    """Normalize stored module syntax to target UI language.

    Only base/original module rows are rewritten. Materialized localized variants
    are skipped because they either already match the target locale or are
    regenerated on demand.
    """

    ensure_modules_tables(db)
    target_language = str(language or "uk").strip().lower()
    if target_language not in {"uk", "en"}:
        raise ValueError(f"Unsupported language: {language}")

    rows = db.table(MODULES_TABLE).select(where=None, order_by="module_guid") or []
    total = int(len(rows))
    eligible = 0
    changed = 0
    unchanged = 0
    skipped = 0

    prepared_rows: List[Dict[str, Any]] = []
    changed_assets: Dict[str, Tuple[bytes, str]] = {}

    for row in rows:
        row_lang = str(row.get("lang") or "").strip().lower()
        if row_lang not in {"", target_language}:
            skipped += 1
            prepared_rows.append(dict(row))
            continue

        eligible += 1
        module_guid = str(row.get("module_guid") or "").strip()
        if not module_guid:
            skipped += 1
            prepared_rows.append(dict(row))
            continue

        original_text = get_module_text_from_row(db, row)
        result = normalize_module_text(original_text, language=target_language)
        if not result.changed:
            unchanged += 1
            prepared_rows.append(dict(row))
            continue

        prepared, asset_item = _prepare_module_row_storage(
            db,
            {
                **row,
                "module_guid": module_guid,
                "owner_guid": str(row.get("owner_guid") or ""),
                "owner_kind": str(row.get("owner_kind") or ""),
                "module_kind": str(row.get("module_kind") or ""),
                "name": str(row.get("name") or ""),
                "lang": str(row.get("lang") or ""),
                "text": str(result.text or ""),
                "sha256": _sha256_text(result.text),
                "version": int(row.get("version") or 1) + 1,
                "updated_at": _now_ms(),
                "updated_by": str(updated_by or ""),
                "storage_kind": str(row.get("storage_kind") or ""),
                "content_ref": str(row.get("content_ref") or ""),
                "size_bytes": int(row.get("size_bytes") or 0),
            },
            preserve_asset_storage=True,
        )
        if asset_item is not None:
            changed_assets[asset_item[0]] = asset_item[1]
        prepared_rows.append(prepared)
        changed += 1

    if changed_assets:
        db.put_assets_bulk([(key, data, mime) for key, (data, mime) in changed_assets.items()])
    if changed > 0:
        replace_modules_bulk(db, prepared_rows)

    return {
        "language": target_language,
        "total": total,
        "eligible": eligible,
        "changed": changed,
        "unchanged": unchanged,
        "skipped": skipped,
    }
