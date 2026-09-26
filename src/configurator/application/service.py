from __future__ import annotations

from dataclasses import dataclass
import json
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from src.configurator.manifest_schema import ManifestObject
from src.configurator.cache.structure_cache import (
    cache_needs_compaction,
    load_structure_cache,
    save_structure_cache,
)
from src.runtime.gateway import RuntimeGateway, GatewayDb
from src.platform.logging_setup import get_logger


@dataclass
class OpenResult:
    db: GatewayDb
    objects: List[ManifestObject]
    loaded_from_cache: bool = False
    cache_validated: bool = False


_log = get_logger("configurator.service")


class ConfiguratorService:
    """Business logic for Configurator — all DB operations go via Runtime RPC.

    No direct Mpdb access. The GatewayDb is a drop-in Mpdb replacement that
    delegates every call to the runtime server over HTTP.
    """

    def __init__(self) -> None:
        self._gw:  Optional[RuntimeGateway] = None
        self._db:  Optional[GatewayDb]      = None
        self._db_uid: str = ""
        self._cache_compaction_threads: set[str] = set()

    @staticmethod
    def _merge_schema_index(
        objects: List[ManifestObject],
        schema_rows: List[Dict[str, Any]],
    ) -> List[ManifestObject]:
        patches = {
            str(row.get("guid") or "").strip(): dict(row.get("payload") or {})
            for row in schema_rows or []
            if isinstance(row, dict)
            and str(row.get("guid") or "").strip()
            and isinstance(row.get("payload"), dict)
        }
        if not patches:
            return list(objects or [])
        merged: List[ManifestObject] = []
        for obj in objects or []:
            patch = patches.get(str(obj.guid or "").strip())
            if not patch:
                merged.append(obj)
                continue
            payload = dict(obj.payload or {})
            payload.update(patch)
            merged.append(
                ManifestObject(
                    guid=obj.guid,
                    type=obj.type,
                    name=obj.name,
                    title=obj.title,
                    kind=obj.kind,
                    parent_guid=obj.parent_guid,
                    payload=payload,
                )
            )
        return merged

    @staticmethod
    def _schema_index(gw: Any) -> List[Dict[str, Any]]:
        getter = getattr(gw, "manifest_schema_index", None)
        if not callable(getter):
            return []
        rows = getter()
        return [dict(row) for row in list(rows or []) if isinstance(row, dict)]

    @property
    def db_uid(self) -> str:
        return self._db_uid

    def open_db(
        self,
        runtime_url: str,
        db_uid: str = "",
        *,
        db_path: str = "",
        seed_defaults_if_empty: bool = True,
    ) -> OpenResult:
        """Open a database through the runtime server.

        Prefer ``db_path`` for local/background startup because it works even
        when the runtime registry has not been populated yet.

        Args:
            runtime_url: HTTP URL of the runtime server, e.g. 'http://127.0.0.1:8765'
            db_uid:      UID of the database as registered on the server.
            db_path:     Path to a local .1CD/mpdb file.
            seed_defaults_if_empty: seed the manifest when the DB is blank.
        """
        started_at = time.perf_counter()
        _log.info("open_db.start runtime=%s db_uid=%s db_path=%s", runtime_url, db_uid, db_path)
        gw = RuntimeGateway(runtime_url)
        db_path = str(db_path or "").strip()
        db_uid = str(db_uid or "").strip()
        if db_path:
            open_info = gw.open_by_path(db_path)
            db_uid = str(open_info.get("db_uid") or db_uid).strip()
        else:
            try:
                gw.open_by_uid(db_uid)
            except Exception as exc:
                open_rows = []
                try:
                    open_rows = gw.list_open_databases()
                except Exception:
                    open_rows = []
                matched_path = ""
                if db_uid:
                    for row in open_rows:
                        if str(row.get("db_uid") or "").strip() == db_uid:
                            matched_path = str(row.get("path") or "").strip()
                            break
                elif len(open_rows) == 1:
                    matched_path = str(open_rows[0].get("path") or "").strip()
                    db_uid = str(open_rows[0].get("db_uid") or "").strip()
                if matched_path:
                    open_info = gw.open_by_path(matched_path)
                    db_uid = str(open_info.get("db_uid") or db_uid).strip()
                else:
                    raise RuntimeError(
                        f"{exc}. Provide db_path or ensure the runtime has an open DB"
                    ) from exc
        db = GatewayDb(gw)

        manifest_info_started = time.perf_counter()
        manifest_info = {}
        manifest_info_error: Exception | None = None
        try:
            manifest_info = gw.manifest_info()
            _log.info(
                "open_db.manifest_info ok in %.3fs object_count=%s generated_at=%s",
                time.perf_counter() - manifest_info_started,
                manifest_info.get("object_count"),
                manifest_info.get("generated_at"),
            )
        except Exception as exc:
            _log.warning("open_db.manifest_info failed in %.3fs: %s", time.perf_counter() - manifest_info_started, exc)
            manifest_info = {}
            manifest_info_error = exc

        cache_db_path = str(manifest_info.get("db_path") or "").strip()
        structure_hash = str(manifest_info.get("structure_hash") or "").strip()
        objects = None
        loaded_from_cache = False
        cache_validated = False
        if cache_db_path and structure_hash:
            cache_started = time.perf_counter()
            objects = load_structure_cache(
                cache_db_path,
                db_uid=str(manifest_info.get("db_uid") or db_uid),
                structure_hash=structure_hash,
                verify_db_state=True,
            )
            loaded_from_cache = objects is not None
            # A hit is already validated against both the live runtime
            # structure hash and the current DB file state. Do not schedule a
            # redundant full manifest.list immediately after startup.
            cache_validated = loaded_from_cache
            _log.info(
                "open_db.cache %s in %.3fs path=%s structure_hash=%s",
                "hit" if loaded_from_cache else "miss",
                time.perf_counter() - cache_started,
                cache_db_path,
                structure_hash[:12],
            )

        if objects is None:
            manifest_open_started = time.perf_counter()
            object_count = int(manifest_info.get("object_count") or 0)
            fetch_mode = "manifest_open"
            if manifest_info_error is not None:
                # A telemetry/read timeout is not proof that the database is
                # empty. Recover through a read-only list and never trigger
                # ensure/seed mutations from this failure path.
                raw_objs = gw.manifest_list()
                fetch_mode = "manifest_list_recovery"
            elif object_count > 0:
                raw_objs = gw.manifest_list()
                fetch_mode = "manifest_list"
            else:
                raw_objs = gw.manifest_open(seed_defaults=seed_defaults_if_empty)
            objects = [_dict_to_mo(r) for r in raw_objs]
            _log.info(
                "open_db.%s fetched %d objects in %.3fs",
                fetch_mode,
                len(objects),
                time.perf_counter() - manifest_open_started,
            )
            if cache_db_path and structure_hash:
                try:
                    save_structure_cache(
                        cache_db_path,
                        db_uid=str(manifest_info.get("db_uid") or db_uid),
                        structure_hash=structure_hash,
                        generated_at=int(manifest_info.get("generated_at") or 0),
                        objects=objects,
                    )
                except Exception as exc:
                    _log.warning("open_db.save_structure_cache failed: %s", exc)
        elif cache_db_path and structure_hash and cache_needs_compaction(cache_db_path):
            self._schedule_structure_cache_compaction(
                cache_db_path=cache_db_path,
                db_uid=str(manifest_info.get("db_uid") or db_uid),
                structure_hash=structure_hash,
                generated_at=int(manifest_info.get("generated_at") or 0),
                objects=objects,
            )

        schema_started_at = time.perf_counter()
        try:
            schema_rows = self._schema_index(gw)
            objects = self._merge_schema_index(objects, schema_rows)
            _log.info(
                "open_db.schema_index objects=%d owners=%d took=%.3fs",
                len(objects),
                len(schema_rows),
                time.perf_counter() - schema_started_at,
            )
        except Exception as exc:
            _log.warning("open_db.schema_index failed in %.3fs: %s", time.perf_counter() - schema_started_at, exc)

        self._gw     = gw
        self._db     = db
        self._db_uid = db_uid
        _log.info(
            "open_db.done source=%s objects=%d total=%.3fs",
            "cache" if loaded_from_cache else "runtime",
            len(objects),
            time.perf_counter() - started_at,
        )
        return OpenResult(
            db=db,
            objects=objects,
            loaded_from_cache=loaded_from_cache,
            cache_validated=cache_validated,
        )

    def _schedule_structure_cache_compaction(
        self,
        *,
        cache_db_path: str,
        db_uid: str,
        structure_hash: str,
        generated_at: int,
        objects: List[ManifestObject],
    ) -> None:
        cache_db_path = str(cache_db_path or "").strip()
        if not cache_db_path:
            return
        if cache_db_path in self._cache_compaction_threads:
            return
        self._cache_compaction_threads.add(cache_db_path)

        snapshot = list(objects or [])

        def _worker() -> None:
            started_at = time.perf_counter()
            try:
                save_structure_cache(
                    cache_db_path,
                    db_uid=db_uid,
                    structure_hash=structure_hash,
                    generated_at=generated_at,
                    objects=snapshot,
                )
                _log.info(
                    "open_db.cache_compaction done path=%s objects=%d took=%.3fs",
                    cache_db_path,
                    len(snapshot),
                    time.perf_counter() - started_at,
                )
            except Exception as exc:
                _log.warning("open_db.cache_compaction failed path=%s error=%s", cache_db_path, exc)
            finally:
                self._cache_compaction_threads.discard(cache_db_path)

        try:
            threading.Thread(
                target=_worker,
                name="mp-structure-cache-compact",
                daemon=True,
            ).start()
            _log.info("open_db.cache_compaction scheduled path=%s objects=%d", cache_db_path, len(snapshot))
        except Exception as exc:
            self._cache_compaction_threads.discard(cache_db_path)
            _log.warning("open_db.cache_compaction schedule failed path=%s error=%s", cache_db_path, exc)

    def close(self) -> None:
        db = self._db
        self._db     = None
        self._gw     = None
        self._db_uid = ""
        if db is not None:
            db.close()

    def require_db(self) -> GatewayDb:
        if self._db is None:
            raise RuntimeError("DB is not opened")
        return self._db

    def _gw_required(self) -> RuntimeGateway:
        if self._gw is None:
            raise RuntimeError("DB is not opened")
        return self._gw

    def current_session_id(self) -> str:
        """Return the current runtime RPC session id."""
        return str(self._gw_required().ensure_session() or "")

    # ── assets ────────────────────────────────────────────────────────────

    def list_assets(self, prefix: str = "") -> list[str]:
        return self._gw_required().asset_list(prefix)

    def get_asset(self, key: str) -> tuple[bytes, str]:
        return self._gw_required().asset_get(key)

    def put_json_asset(self, key: str, value: object) -> None:
        asset_key = str(key or "").replace("\\", "/").strip()
        if not asset_key:
            raise ValueError("Empty asset key")
        data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._gw_required().asset_put(asset_key, data, "application/json")

    # ── manifest CRUD ──────────────────────────────────────────────────────

    def list_objects(self) -> List[ManifestObject]:
        started_at = time.perf_counter()
        gw = self._gw_required()
        rows = gw.manifest_list()
        objects = [_dict_to_mo(r) for r in rows]
        try:
            schema_rows = self._schema_index(gw)
            objects = self._merge_schema_index(objects, schema_rows)
        except Exception as exc:
            _log.warning("list_objects.schema_index failed: %s", exc)
        _log.info("list_objects fetched %d objects in %.3fs", len(objects), time.perf_counter() - started_at)
        return objects

    def manifest_get_payload(self, guid: str) -> dict:
        """Fetch a single object payload directly from the runtime."""

        guid = str(guid or "").strip()
        if not guid:
            return {}
        payload = self._gw_required().manifest_get_payload(guid)
        return dict(payload or {})

    def manifest_get_objects(self, guid: str) -> list[str]:
        """Fetch subsystem membership object guids directly from the runtime."""

        guid = str(guid or "").strip()
        if not guid:
            return []
        try:
            values = self._gw_required().manifest_get_objects(guid)
        except Exception as exc:
            _log.warning("manifest_get_objects failed guid=%s error=%s", guid, exc)
            return []
        return [str(x).strip() for x in values if str(x).strip()]

    def _reload(self) -> List[ManifestObject]:
        return self.list_objects()

    def add_object(
        self,
        *,
        obj_type: str,
        name: str,
        title: str,
        parent_guid: str,
        payload: Optional[dict] = None,
        kind: str = "object",
    ) -> ManifestObject:
        raw = self._gw_required().manifest_add({
            "type":        obj_type,
            "name":        name,
            "title":       title,
            "parent_guid": parent_guid,
            "payload":     payload or {},
            "kind":        kind,
        })
        return _dict_to_mo(raw)

    def delete_object(self, guid: str) -> None:
        self._gw_required().manifest_delete(guid)

    def rename_object(self, guid: str, new_title: str) -> None:
        self._gw_required().manifest_update_title(guid, new_title)

    def update_object_payload(self, guid: str, payload: dict) -> None:
        started_at = time.perf_counter()
        self._gw_required().manifest_update_payload(guid, payload or {})
        _log.info(
            "update_object_payload guid=%s keys=%s took=%.3fs",
            str(guid or ""),
            sorted((payload or {}).keys()),
            time.perf_counter() - started_at,
        )

    def update_object_payloads(self, payloads: dict[str, dict]) -> int:
        started_at = time.perf_counter()
        normalized = {
            str(guid): dict(payload or {})
            for guid, payload in dict(payloads or {}).items()
            if str(guid or "").strip()
        }
        updated = self._gw_required().manifest_bulk_update_payloads(normalized)
        _log.info(
            "update_object_payloads requested=%d updated=%d took=%.3fs",
            len(normalized),
            updated,
            time.perf_counter() - started_at,
        )
        return updated

    def update_object_fields(
        self,
        guid: str,
        *,
        obj_type: str | None = None,
        name: str | None = None,
        title: str | None = None,
        parent_guid: str | None = None,
        payload: dict | None = None,
    ) -> None:
        fields: dict = {}
        if obj_type is not None:
            fields["obj_type"] = obj_type
        if name is not None:
            fields["name"] = name
        if title is not None:
            fields["title"] = title
        if parent_guid is not None:
            fields["parent_guid"] = parent_guid
        if payload is not None:
            fields["payload"] = payload
        self._gw_required().manifest_update_fields(guid, **fields)

    def normalize_modules_language(self, language: str) -> dict[str, object]:
        started_at = time.perf_counter()
        result = self._gw_required().modules_normalize_language(str(language or "").strip().lower())
        _log.info(
            "normalize_modules_language language=%s changed=%s eligible=%s took=%.3fs",
            str(result.get("language") or language or ""),
            result.get("changed"),
            result.get("eligible"),
            time.perf_counter() - started_at,
        )
        return result

    def get_module_text(self, module_guid: str) -> str:
        return self._gw_required().module_get_text(module_guid)

    def list_modules_by_owner(self, owner_guid: str) -> list[dict]:
        return self._gw_required().modules_list_by_owner(owner_guid)

    def get_common_module_completion(self, name: str) -> dict[str, object]:
        return dict(self._gw_required().module_completion_members(name) or {})

    def get_workspace_semantic_index_info(self, *, wait: bool = False) -> dict[str, object]:
        return dict(
            self._gw_required().workspace_semantic_index_info(wait=wait)
            or {}
        )

    def resolve_workspace_symbol(self, qualifier: str, name: str) -> dict[str, object]:
        return dict(
            self._gw_required().workspace_semantic_definition(qualifier, name)
            or {}
        )

    def find_workspace_references(
        self,
        term: str,
        *,
        limit: int = 500,
        include_declaration: bool = True,
    ) -> list[dict]:
        parts = [
            part.strip()
            for part in str(term or "").split(".")
            if part.strip()
        ]
        if len(parts) < 2:
            return []
        return self._gw_required().workspace_semantic_references(
            parts[0],
            parts[1],
            limit=limit,
            include_declaration=include_declaration,
        )

    def get_workspace_semantic_diagnostics(
        self,
        *,
        module_guid: str = "",
        code: str = "",
        limit: int = 500,
    ) -> list[dict]:
        return self._gw_required().workspace_semantic_diagnostics(
            module_guid=module_guid,
            code=code,
            limit=limit,
        )

    def search_module_text(
        self,
        term: str,
        *,
        match_case: bool = False,
        whole_word: bool = False,
        module_guid: str = "",
        limit: int = 500,
    ) -> list[dict]:
        return self._gw_required().modules_search_text(
            term,
            match_case=match_case,
            whole_word=whole_word,
            module_guid=module_guid,
            limit=limit,
        )

    def update_module_text(self, module_guid: str, text: str, *, updated_by: str = "user") -> None:
        self._gw_required().module_update_text(module_guid, text, updated_by=updated_by)

    def plan_workspace_symbol_rename(
        self,
        module_guid: str,
        *,
        new_name: str,
        cursor_position: int | None = None,
        symbol_name: str = "",
        module_name: str = "",
    ) -> dict[str, object]:
        return dict(
            self._gw_required().modules_rename_symbol_plan(
                module_guid,
                new_name=new_name,
                cursor_position=cursor_position,
                symbol_name=symbol_name,
                module_name=module_name,
            )
            or {}
        )

    def apply_workspace_symbol_rename(
        self,
        module_guid: str,
        *,
        new_name: str,
        modules: list[dict],
        cursor_position: int | None = None,
        symbol_name: str = "",
        module_name: str = "",
        updated_by: str = "workspace_rename",
    ) -> dict[str, object]:
        return dict(
            self._gw_required().modules_rename_symbol_apply(
                module_guid,
                new_name=new_name,
                modules=modules,
                cursor_position=cursor_position,
                symbol_name=symbol_name,
                module_name=module_name,
                updated_by=updated_by,
            )
            or {}
        )

    def deploy_schema(self) -> dict[str, object]:
        return dict(self._gw_required().schema_deploy() or {})

    # ── pictures library ───────────────────────────────────────────────────

    PICTURES_PREFIX = "pictures/"

    def list_picture_objects(self) -> List[ManifestObject]:
        return [o for o in self.list_objects()
                if str(o.type) == "common_picture" and o.kind == "object"]

    def find_common_pictures_folder_guid(self) -> str:
        for o in self.list_objects():
            if (o.kind in ("folder", "group") and str(o.type) == "common"
                    and str(o.name) == "common_pictures"):
                return str(o.guid)
        return ""

    def ensure_common_pictures_folder_guid(self) -> str:
        guid = self.find_common_pictures_folder_guid()
        if guid:
            return guid
        common_guid = ""
        for o in self.list_objects():
            if str(o.kind) == "group" and str(o.type) == "common" and str(o.name) == "common":
                common_guid = str(o.guid)
                break
        if not common_guid:
            raise RuntimeError("common group not found")
        mo = self.add_object(
            obj_type="common", name="common_pictures",
            title="Общие картинки", parent_guid=common_guid,
            kind="folder",
            payload={"system": True, "protected": True, "seed": True, "menu": "add_only"},
        )
        return str(mo.guid)

    def put_picture_asset(self, asset_key: str, data: bytes, mime: str) -> None:
        asset_key = str(asset_key).replace("\\", "/").strip()
        if not asset_key:
            raise ValueError("Empty asset key")
        self._gw_required().asset_put(asset_key, data, mime)

    def get_picture_asset(self, asset_key: str) -> tuple[bytes, str]:
        return self._gw_required().asset_get(asset_key)

    def delete_picture_asset(self, asset_key: str) -> bool:
        return self._gw_required().asset_delete(asset_key)

    # ── auto-naming (pure logic, no DB needed) ────────────────────────────

    AUTO_TITLE_PREFIX = {
        "catalog": "Справочник", "document": "Документ",
        "report": "Отчет", "data_processor": "Обработка",
        "register_info": "РегистрСведений", "register_accum": "РегистрНакопления",
        "register_accounting": "РегистрБухгалтерии", "register_calc": "РегистрРасчета",
        "journal": "ЖурналДокументов", "enumeration": "Перечисление",
        "constants": "Константы", "business_process": "БизнесПроцесс",
        "task": "Задача", "external_sources": "ИсточникДанных",
        "common_picture": "Картинка", "common": "Объект",
        "form": "Форма", "command": "Команда", "layout": "Макет",
    }
    AUTO_CODE_PREFIX = {
        "catalog": "catalog", "document": "document", "report": "report",
        "data_processor": "data_processor", "register_info": "register_info",
        "register_accum": "register_accum", "register_accounting": "register_accounting",
        "register_calc": "register_calc", "journal": "journal",
        "enumeration": "enumeration", "constants": "constants",
        "business_process": "business_process", "task": "task",
        "external_sources": "external_sources", "common_picture": "picture",
        "common": "common", "form": "form", "command": "command", "layout": "layout",
    }
    AUTO_SUBTYPE_TITLE_PREFIX = {
        "common_module": "ОбщийМодуль", "common_form": "ОбщаяФорма",
        "common_command": "Команда", "list_form": "ФормаСписка",
        "object_form": "ФормаОбъекта",
    }
    AUTO_SUBTYPE_CODE_PREFIX = {
        "common_module": "common_module", "common_form": "common_form",
        "common_command": "common_command", "list_form": "list_form",
        "object_form": "object_form",
    }

    def next_auto_name(self, obj_type: str,
                       objects: List[ManifestObject]) -> Tuple[str, str]:
        obj_type = (obj_type or "").strip()
        prefix_title = self.AUTO_TITLE_PREFIX.get(obj_type, "Объект")
        prefix_code  = self.AUTO_CODE_PREFIX.get(obj_type, "object")
        used_titles: set[str] = set()
        used_codes:  set[str] = set()
        for o in objects:
            if o.kind != "object" or str(o.type) != obj_type:
                continue
            used_titles.add((o.title or "").strip().lower())
            used_codes.add((o.name or "").strip().lower())
        n = 1
        while True:
            t, c = f"{prefix_title}{n}", f"{prefix_code}{n}"
            if t.lower() not in used_titles and c.lower() not in used_codes:
                return t, c
            n += 1

    def next_auto_name_with_subtype(self, obj_type: str, subtype: str | None,
                                    objects: List[ManifestObject]) -> Tuple[str, str]:
        st = (subtype or "").strip()
        if not st:
            return self.next_auto_name(obj_type, objects)
        prefix_title = self.AUTO_SUBTYPE_TITLE_PREFIX.get(
            st, self.AUTO_TITLE_PREFIX.get(obj_type, "Объект"))
        prefix_code  = self.AUTO_SUBTYPE_CODE_PREFIX.get(
            st, self.AUTO_CODE_PREFIX.get(obj_type, "object"))
        used_titles: set[str] = set()
        used_codes:  set[str] = set()
        for o in objects:
            if o.kind != "object" or str(o.type) != str(obj_type):
                continue
            p = o.payload if isinstance(o.payload, dict) else {}
            if str(p.get("subtype") or "").strip() != st:
                continue
            used_titles.add((o.title or "").strip().lower())
            used_codes.add((o.name or "").strip().lower())
        n = 1
        while True:
            t, c = f"{prefix_title}{n}", f"{prefix_code}{n}"
            if t.lower() not in used_titles and c.lower() not in used_codes:
                return t, c
            n += 1


# ── helpers ───────────────────────────────────────────────────────────────

def _dict_to_mo(d: dict) -> ManifestObject:
    from src.configurator.manifest_schema import ManifestObject
    payload = dict(d.get("payload") or {}) if isinstance(d.get("payload"), dict) else {}
    if isinstance(d.get("objects"), list) and "objects" not in payload:
        payload["objects"] = [str(x).strip() for x in d.get("objects") or [] if str(x).strip()]
    return ManifestObject(
        guid=str(d.get("guid") or ""),
        type=str(d.get("type") or "common"),
        kind=str(d.get("kind") or "object"),
        name=str(d.get("name") or ""),
        title=str(d.get("title") or ""),
        parent_guid=str(d.get("parent_guid") or ""),
        payload=payload,
    )
