"""Resolve a document ObjectModule and edit its existing workspace buffer.

Only manifest/module reads go through Runtime. Insertion never saves, creates a
module, or accesses mpdb directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from src.ui_qt.i18n import t
from src.configurator.domain.technical_names import technical_object_name


@dataclass(frozen=True)
class ObjectModuleTarget:
    document_guid: str
    manifest_guid: str
    module_guid: str
    asset_key: str
    title: str


def _field(row: Any, name: str, default: Any = "") -> Any:
    return row.get(name, default) if isinstance(row, Mapping) else getattr(row, name, default)


def resolve_document_object_module(vm, document_guid: str) -> ObjectModuleTarget:
    """Resolve exactly one ObjectModule via Runtime, or raise ValueError.

    ``vm._service.list_objects/list_modules_by_owner/manifest_get_payload`` are
    ConfiguratorService RPC APIs. Do not use the generic owner-to-module helper:
    it can select ManagerModule. The executable key comes from the hydrated
    manifest module node, not its GUID, display title, or a storage-cache path.
    """
    document_guid = str(document_guid or "").strip()
    service = vm._service
    objects = list(vm.list_objects())
    document = next(
        (row for row in objects if str(_field(row, "guid")) == document_guid), None
    )
    if document is None or str(_field(document, "type")).casefold() != "document":
        raise ValueError(t("posting_module_missing"))

    folders = {
        str(_field(row, "guid"))
        for row in objects
        if str(_field(row, "parent_guid")) == document_guid
        and (
            str(_field(row, "type")).casefold() in {"modules", "modules_folder"}
            or (
                str(_field(row, "kind")).casefold() == "folder"
                and str(_field(row, "name")).casefold() == "modules"
            )
        )
    }
    runtime_rows = list(service.list_modules_by_owner(document_guid))
    runtime_by_guid = {
        str(row.get("module_guid") or "").strip(): row for row in runtime_rows
    }
    candidates: dict[str, ObjectModuleTarget] = {}
    for row in objects:
        if str(_field(row, "type")).casefold() not in {"module", "object_module"}:
            continue
        if str(_field(row, "parent_guid")) not in folders | {document_guid}:
            continue
        manifest_guid = str(_field(row, "guid"))
        payload = service.manifest_get_payload(manifest_guid)
        owner_guid = str(payload.get("owner_guid") or "").strip()
        if owner_guid and owner_guid != document_guid:
            continue
        module = payload.get("module")
        asset_key = str(module.get("asset_key") or "").strip() if isinstance(module, dict) else ""
        module_guid = asset_key.removeprefix("module://") if asset_key.startswith("module://") else ""
        runtime_row = runtime_by_guid.get(module_guid)
        if runtime_row is not None:
            # Runtime's exact kind takes precedence over imported display names.
            is_object_module = str(runtime_row.get("module_kind") or "").casefold() == "objectmodule"
            if str(runtime_row.get("owner_guid") or document_guid) != document_guid:
                is_object_module = False
        else:
            imported = payload.get("imported") or {}
            origin = str(imported.get("origin") or "").replace("\\", "/") if isinstance(imported, dict) else ""
            kind = str(payload.get("module_kind") or "").casefold()
            is_object_module = kind == "objectmodule" if kind else (
                str(_field(row, "name")).casefold() in {"objectmodule", "ext_objectmodule"}
                or origin.casefold().endswith("/ext/objectmodule.bsl")
            )
        if not is_object_module:
            continue
        if not module_guid or module_guid == document_guid or (runtime_rows and runtime_row is None):
            raise ValueError(t("posting_module_invalid_ref"))
        candidates[asset_key] = ObjectModuleTarget(
            document_guid=document_guid,
            manifest_guid=manifest_guid,
            module_guid=module_guid,
            asset_key=asset_key,
            title=f"{technical_object_name(_field(document, 'name'), payload=_field(document, 'payload'))}: ObjectModule",
        )
    if not candidates:
        raise ValueError(t("posting_module_missing"))
    if len(candidates) != 1:
        raise ValueError(t("posting_module_ambiguous"))
    return next(iter(candidates.values()))


def insert_document_posting_handler(host, document_guid: str, code: str) -> bool:
    """Signal-slot adapter for Configurator: resolve, activate, insert, not save.

    Wire ``postingModuleRequested.connect(lambda code: ... (host, guid, code))``.
    ``host`` supplies ``_vm``, ``_open_windows``, ``mdi``,
    ``_open_module_by_guid`` and ``show_warning``. False means no text inserted.
    """
    from src.ui_qt.widgets.code_editor_widget import CodeEditorWidget

    try:
        target = resolve_document_object_module(host._vm, document_guid)

        def matching_editors():
            matches = []
            seen = set()
            for sub in host._open_windows.values():
                editor = sub.widget()
                if not isinstance(editor, CodeEditorWidget) or id(editor) in seen:
                    continue
                seen.add(id(editor))
                key = str(editor._state.resolved_key or editor._state.asset_key or "").strip()
                if key == target.asset_key:
                    matches.append((sub, editor))
            return matches

        matches = matching_editors()
        if not matches:
            host._open_module_by_guid(target.module_guid, target.title)
            matches = matching_editors()
        if len(matches) > 1:
            raise ValueError(t("posting_module_multiple_editors"))
        if not matches:
            raise ValueError(t("posting_module_open_failed"))
        sub, editor = matches[0]
        host.mdi.setActiveSubWindow(sub)
        sub.showNormal()
        return editor.insert_posting_handler(code)
    except Exception as exc:
        host.show_warning(t("dlg_error_title"), t("posting_module_failed", error=str(exc)))
        return False
