from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from src.ui_qt.i18n import t


class ConfiguratorVmAssetsMixin:
    REF_MIME = "application/x-mpx-asset-ref+json"
    REF_MAX_DEPTH = 8

    @staticmethod
    def _preferred_module_row(rows: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        if not rows:
            return None
        return next((row for row in rows if not str(row.get("lang") or "").strip()), rows[0])

    def _resolve_module_guid_compat(self, module_guid_or_owner_guid: str) -> tuple[str, Dict[str, Any] | None]:
        """Resolve a semantic module target to an actual cfg_modules row.

        Older manifests may store ``module://<owner-guid>`` where ``owner-guid`` is
        the manifest object GUID rather than the real ``cfg_modules.module_guid``.
        If that owner has module rows, prefer the canonical base-language row.
        """

        guid = str(module_guid_or_owner_guid or "").strip()
        if not guid:
            return "", None
        try:
            rows = self._service.list_modules_by_owner(guid) or []
        except Exception:
            rows = []
        row = self._preferred_module_row(rows)
        resolved_guid = str((row or {}).get("module_guid") or "").strip()
        if resolved_guid:
            return resolved_guid, row
        return guid, None

    def list_pictures(self) -> List[Dict[str, Any]]:
        """Return picture objects: [{guid,title,asset_key,mime}]."""
        out: List[Dict[str, Any]] = []
        for o in self._service.list_picture_objects():
            p = o.payload if isinstance(o.payload, dict) else {}
            pic = p.get("picture") if isinstance(p.get("picture"), dict) else {}
            meta = pic.get("meta") if isinstance(pic.get("meta"), dict) else {}
            asset_key = str(pic.get("asset_key") or "").strip()
            mime = str(pic.get("mime") or "").strip()
            out.append({
                "guid": str(o.guid),
                "title": str(o.title or o.name or o.guid),
                "name": str(o.name or ""),
                "asset_key": asset_key,
                "mime": mime,
                "tags": str(meta.get("tags") or ""),
                "category": str(meta.get("category") or ""),
            })
        return out


    def _normalize_asset_key(self, asset_key: str) -> str:
        """Normalize asset key to a stable mpdb key."""
        return str(asset_key or "").replace('\\', '/').strip()


    def _resolve_asset(self, asset_key: str) -> tuple[str, bytes, str]:
        """Resolve possible semantic ref chain.

        Returns:
            (resolved_key, data, mime)

        Raises:
            ValueError for empty key.
            RuntimeError for loops/bad refs/too deep.
            Underlying mpdb errors for missing assets.
        """
        key = self._normalize_asset_key(asset_key)
        if not key:
            raise ValueError("Empty asset key")

        visited: set[str] = set()
        for _ in range(int(self.REF_MAX_DEPTH)):
            if key in visited:
                raise RuntimeError(f"Asset ref loop detected: {key}")
            visited.add(key)

            data, mime = self._service.get_asset(key)
            mime = str(mime or "").strip()
            if mime != self.REF_MIME:
                return key, data, mime

            # Parse ref JSON
            try:
                payload = json.loads((data or b"").decode("utf-8", errors="replace"))
            except Exception as e:
                raise RuntimeError(f"Bad asset ref at {key}: {e}")

            ref = str(payload.get("ref") or "").strip()
            if not ref:
                raise RuntimeError(f"Bad asset ref at {key}: empty ref")
            key = self._normalize_asset_key(ref)

        raise RuntimeError("Asset ref depth exceeded")


    def resolve_asset_key(self, asset_key: str) -> str:
        """Return raw asset key after resolving possible semantic refs."""
        rk, _data, _mime = self._resolve_asset(asset_key)
        return rk


    def get_text_asset(self, asset_key: str) -> tuple[str, str, str]:
        """Load a text asset.

        Returns:
            (text, mime, resolved_key)
        """
        k = self._normalize_asset_key(asset_key)
        if k.startswith('module://'):
            module_guid = k.split('://', 1)[1].strip()
            direct_error: Exception | None = None
            try:
                # Fast path: the GUID is already a real cfg_modules.module_guid.
                try:
                    txt = self._service.get_module_text(module_guid)
                    if txt:
                        return txt, "text/plain", k
                except Exception as exc:
                    direct_error = exc

                # Compatibility path for owner GUIDs: try the manifest payload
                # first so common modules can resolve their actual module asset
                # without a slow owner-scan fallback.
                resolved_guid = ""
                try:
                    manifest_get_payload = getattr(self._service, "manifest_get_payload", None)
                    payload = manifest_get_payload(module_guid) if callable(manifest_get_payload) else {}
                except Exception:
                    payload = {}

                if isinstance(payload, dict):
                    module_payload = payload.get("module") if isinstance(payload.get("module"), dict) else {}
                    asset_key = str(
                        module_payload.get("asset_key")
                        or payload.get("module_asset_key")
                        or payload.get("asset_key")
                        or ""
                    ).strip()
                    if asset_key.startswith("module://"):
                        resolved_guid = asset_key.split("://", 1)[1].strip()
                        if resolved_guid and resolved_guid != module_guid:
                            try:
                                txt = self._service.get_module_text(resolved_guid)
                                if txt:
                                    return txt, "text/plain", f"module://{resolved_guid}"
                            except Exception:
                                pass

                resolved_guid, row = self._resolve_module_guid_compat(module_guid)
                txt = self._service.get_module_text(resolved_guid)

                if not txt and direct_error is not None:
                    raise direct_error
            except Exception as e:
                raise RuntimeError(f"Failed to load module text for {module_guid}: {e}") from e
            semantic_key = f"module://{resolved_guid}" if resolved_guid else k
            return txt, 'text/plain', semantic_key

        rk, data, mime = self._resolve_asset(k)
        try:
            txt = (data or b"").decode("utf-8")
        except Exception:
            txt = (data or b"").decode("utf-8", errors="replace")
        return txt, str(mime or ""), rk


    def resolve_module_asset_key_for_owner(self, owner_guid: str) -> str:
        """Return semantic module:// key for a metadata owner, if one exists.

        This is primarily used as a compatibility path for older imports where
        a top-level ``common_module`` object may not have ``payload.module`` but
        still has a row in ``cfg_modules`` owned by the manifest object GUID.
        """
        owner_guid = str(owner_guid or "").strip()
        if not owner_guid:
            return ""
        try:
            rows = self._service.list_modules_by_owner(owner_guid) or []
        except Exception:
            return ""
        if not rows:
            return ""
        # Prefer the canonical source row without localized suffixes.
        preferred = next((row for row in rows if not str(row.get("lang") or "").strip()), rows[0])
        module_guid = str(preferred.get("module_guid") or "").strip()
        return f"module://{module_guid}" if module_guid else ""


    def save_text_asset(self, asset_key: str, text: str, *, mime: str = "text/plain") -> None:
        """Save text (UTF-8) into an asset.

        Behavior:
            - If asset_key is a semantic REF, writes to the resolved raw key.
            - If asset_key does not exist yet, treats it as raw key and creates it.
        """
        k = self._normalize_asset_key(asset_key)
        if not k:
            raise ValueError("Empty asset key")

        if k.startswith('module://'):
            module_guid = k.split('://', 1)[1].strip()
            try:
                resolved_guid, _row = self._resolve_module_guid_compat(module_guid)
                self._service.update_module_text(
                    resolved_guid or module_guid,
                    str(text or ''),
                    updated_by="user",
                )
            except Exception as e:
                raise RuntimeError(f"Failed to save module text for {module_guid}: {e}") from e
            return

        try:
            rk = self.resolve_asset_key(k)
        except Exception:
            rk = k

        data = (text or "").encode("utf-8")
        self._service.require_db().put_asset(rk, data, mime=str(mime or "text/plain"))


    def get_picture_asset(self, asset_key: str) -> tuple[bytes, str]:
        """Получить бинарные данные ассета картинки и её MIME-тип по ключу.

        Поддерживает semantic REF-ключи (переадресацию на raw asset key).
        """
        _rk, data, mime = self._resolve_asset(asset_key)
        return data, mime


    def save_picture_asset(self, asset_key: str, data: bytes, mime: str) -> None:
        """Сохранить (перезаписать) бинарные данные ассета картинки в mpdb.

        Если asset_key является semantic REF, запись выполняется в resolved raw key.
        Если ассет ещё не существует, ключ рассматривается как raw.
        """
        try:
            rk = self.resolve_asset_key(asset_key)
        except Exception:
            rk = self._normalize_asset_key(asset_key)
        self._service.put_picture_asset(rk, data, mime)


    def update_picture_metadata(self, guid: str, *,
                                title: str | None = None,
                                tags: str | None = None,
                                category: str | None = None) -> None:
        """Update user-editable metadata for a picture object.

        Stored in manifest payload:
          payload.picture.meta = {tags, category}
        """
        guid = str(guid or "").strip()
        if not guid:
            return

        if title is not None:
            title2 = str(title).strip()
            if title2:
                self._service.rename_object(guid, title2)

        objs = self._service.list_objects()
        o = next((x for x in objs if str(x.guid) == guid), None)
        if o is None:
            return

        payload = o.payload if isinstance(o.payload, dict) else {}
        payload = dict(payload)
        pic = payload.get("picture") if isinstance(payload.get("picture"), dict) else {}
        pic = dict(pic)
        meta = pic.get("meta") if isinstance(pic.get("meta"), dict) else {}
        meta = dict(meta)

        if tags is not None:
            meta["tags"] = str(tags)
        if category is not None:
            meta["category"] = str(category)

        pic["meta"] = meta
        payload["picture"] = pic
        self._service.update_object_payload(guid, payload)


    def import_pictures(self, paths: List[str]) -> List[str]:
        return self.import_picture_files(paths)


    def open_svg_editor_for_picture(self, guid: str) -> None:
        return self.request_open_svg_editor(guid)


    def open_picture_editor_for_picture(self, guid: str) -> None:
        return self.request_open_picture_editor(guid)


    def import_picture_files(self, paths: List[str]) -> List[str]:
        """Import files into mpdb and create manifest objects under 'Общие картинки'.

        Returns list of created picture GUIDs.
        """
        try:
            # Do not rely on "seed defaults only when empty" behavior.
            # Some existing DBs may miss this system folder.
            folder_guid = self._service.ensure_common_pictures_folder_guid()
        except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            self.show_warning(t("dlg_error_title"), str(e) or t("pictures_common_missing"))
            return []

        created: List[str] = []
        try:
            objs = self._service.list_objects()
        except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError):
            objs = []

        import mimetypes
        from pathlib import Path as _P

        for p in paths or []:
            try:
                fp = _P(p)
                if not fp.exists() or not fp.is_file():
                    continue
                data = fp.read_bytes()
                mime, _ = mimetypes.guess_type(str(fp))
                mime = mime or ("image/svg+xml" if fp.suffix.lower() == ".svg" else "application/octet-stream")

                title = fp.stem
                # Create manifest object first to get GUID
                title_auto, name_auto = self._service.next_auto_name("common_picture", objs)
                # Use filename as a more friendly default title
                title_final = title or title_auto
                mo = self._service.add_object(
                    obj_type="common_picture",
                    name=name_auto,
                    title=title_final,
                    parent_guid=folder_guid,
                    payload={"user_created": True},
                    kind="object",
                )

                ext = fp.suffix.lower().lstrip(".") or "bin"
                asset_key = f"pictures/{mo.guid}.{ext}"
                self._service.put_picture_asset(asset_key, data, mime)

                payload = mo.payload if isinstance(mo.payload, dict) else {}
                payload = dict(payload)
                payload["picture"] = {
                    "asset_key": asset_key,
                    "mime": mime,
                    "filename": fp.name,
                }
                self._service.update_object_payload(mo.guid, payload)

                created.append(str(mo.guid))
                objs.append(mo)
            except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
                self.show_warning(t("dlg_error_title"), t("pictures_import_failed").format(path=p, error=e))

        if created:
            pass
        return created


    def request_open_svg_editor(self, picture_guid: str) -> None:
        """Открыть SVG-редактор для картинки по GUID (если тип действительно SVG)."""
        picture_guid = str(picture_guid or "").strip()
        if not picture_guid:
            return
        try:
            objs = self._service.list_objects()
            o = next((x for x in objs if str(x.guid) == picture_guid), None)
            if o is None:
                return
            p = o.payload if isinstance(o.payload, dict) else {}
            pic = p.get("picture") if isinstance(p.get("picture"), dict) else {}
            asset_key = str(pic.get("asset_key") or "").strip()
            mime = str(pic.get("mime") or "").strip().lower()
            if not asset_key:
                self.show_warning(t("dlg_error_title"), t("pictures_no_data"))
                return
            if not (asset_key.lower().endswith(".svg") or mime == "image/svg+xml"):
                # keep old behavior but route user to the generic picture editor
                self.request_open_picture_editor(picture_guid)
                return
            self.openSvgEditorRequested.emit(asset_key, str(o.title or o.name or o.guid))
        except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError):
            return


    def request_open_picture_editor(self, picture_guid: str) -> None:
        """Open an editor suitable for the picture type (SVG or raster)."""
        picture_guid = str(picture_guid or "").strip()
        if not picture_guid:
            return
        try:
            objs = self._service.list_objects()
            o = next((x for x in objs if str(x.guid) == picture_guid), None)
            if o is None:
                return
            p = o.payload if isinstance(o.payload, dict) else {}
            pic = p.get("picture") if isinstance(p.get("picture"), dict) else {}
            asset_key = str(pic.get("asset_key") or "").strip()
            mime = str(pic.get("mime") or "").strip().lower()
            if not asset_key:
                self.show_warning(t("dlg_error_title"), t("pictures_no_data"))
                return
            self.openPictureEditorRequested.emit(asset_key, str(o.title or o.name or o.guid), mime)
        except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError):
            return
