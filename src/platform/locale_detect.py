from __future__ import annotations

import locale
import os
from typing import Optional

def _norm(s: Optional[str]) -> str:
    return (s or "").replace("-", "_").strip()

def detect_system_lang() -> str:
    """Return 'uk' if system/UI locale indicates Ukrainian/Ukraine, else 'en'."""
    candidates: list[str] = []

    # Env vars (common on Unix, sometimes set on Windows shells)
    for k in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        v = os.environ.get(k)
        if v:
            candidates.append(v)

    # Python locale APIs
    try:
        loc = locale.getlocale()  # ('uk_UA', 'UTF-8') or (None, None)
        if loc and loc[0]:
            candidates.append(loc[0])
    except Exception:
        pass

    # Windows UI language (best signal for "interface language")
    try:
        import ctypes  # type: ignore
        # Ukrainian (Ukraine) LANGID = 0x0422
        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        if int(langid) == 0x0422:
            return "uk"
    except Exception:
        pass

    for c in candidates:
        c = _norm(c).lower()
        # Examples: uk_UA, uk, ua_UA, Ukrainian_Ukraine
        if c.startswith("uk") or c.startswith("ua") or "uk_ua" in c or c.endswith("_ua"):
            return "uk"
    return "en"
