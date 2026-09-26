from __future__ import annotations

from typing import Any, Mapping

from src.ui_qt.i18n import get_lang, t


_MODULE_TITLE_KEYS = {
    "module": "module_kind_module",
    "objectmodule": "module_kind_object",
    "managermodule": "module_kind_manager",
    "recordsetmodule": "module_kind_record_set",
    "formmodule": "module_kind_form",
    "commandmodule": "module_kind_command",
    "appmodule": "module_kind_managed_application",
    "managedapplicationmodule": "module_kind_managed_application",
    "sessionmodule": "module_kind_session",
    "externalconnectionmodule": "module_kind_external_connection",
    "ordinaryapplicationmodule": "module_kind_ordinary_application",
}

_MODULE_TITLE_ALIASES = {
    "object module": "objectmodule",
    "manager module": "managermodule",
    "record-set module": "recordsetmodule",
    "record set module": "recordsetmodule",
    "form module": "formmodule",
    "command module": "commandmodule",
    "managed application module": "managedapplicationmodule",
    "session module": "sessionmodule",
    "external connection module": "externalconnectionmodule",
    "ordinary application module": "ordinaryapplicationmodule",
    "модуль объекта": "objectmodule",
    "модуль менеджера": "managermodule",
    "модуль набора записей": "recordsetmodule",
    "модуль формы": "formmodule",
    "модуль команды": "commandmodule",
    "модуль управляемого приложения": "managedapplicationmodule",
    "модуль сеанса": "sessionmodule",
    "модуль внешнего соединения": "externalconnectionmodule",
    "модуль обычного приложения": "ordinaryapplicationmodule",
}


def _canonical_module_kind(value: Any) -> str:
    raw = str(value or "").strip()
    compact = "".join(ch for ch in raw.casefold() if ch.isalnum())
    if compact in _MODULE_TITLE_KEYS:
        return compact
    return _MODULE_TITLE_ALIASES.get(raw.casefold(), "")


def localized_module_title(
    module_kind: Any,
    *,
    payload: Mapping[str, Any] | None = None,
    fallback: Any = "",
) -> str:
    """Return a UI-only title while preserving internal module identities."""

    data = payload if isinstance(payload, Mapping) else {}
    lang = get_lang() if get_lang() in {"uk", "en"} else "en"
    localized = str(data.get(f"title_{lang}") or "").strip()
    if localized:
        return localized

    fallback_text = str(fallback or "").strip()
    canonical = _canonical_module_kind(module_kind)
    fallback_canonical = _canonical_module_kind(fallback_text)
    if canonical and (bool(data.get("system")) or fallback_canonical):
        key = _MODULE_TITLE_KEYS[canonical]
        translated = t(key)
        if translated and translated != key:
            return translated
    return fallback_text or str(module_kind or "").strip()


def localized_code_name(payload: Mapping[str, Any] | None, fallback: Any = "") -> str:
    """Return the technical metadata name used by code and the Configurator."""

    data = payload if isinstance(payload, Mapping) else {}
    source_name = str(data.get("source_name") or "").strip()
    if source_name:
        return source_name
    lang = get_lang() if get_lang() in {"uk", "en"} else "en"
    refs = data.get("code_refs") if isinstance(data.get("code_refs"), Mapping) else {}
    reference = str(data.get(f"code_ref_{lang}") or refs.get(lang) or "").strip()
    if reference:
        return reference.rsplit(".", 1)[-1]
    names = data.get("localized_names") if isinstance(data.get("localized_names"), Mapping) else {}
    return str(names.get(lang) or fallback or "").strip()


__all__ = ["localized_code_name", "localized_module_title"]
