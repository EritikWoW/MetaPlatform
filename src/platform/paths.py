from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "MetaPlatform"
DB_EXT = ".mpdb"

def get_user_config_dir() -> Path:
    r"""
    Каталог настроек платформы (список подключенных баз).
    Windows: %APPDATA%\MetaPlatform
    Fallback: ~/.metaplatform
    """
    appdata = os.environ.get("APPDATA")
    if appdata:
        p = Path(appdata) / APP_NAME
    else:
        p = Path.home() / f".{APP_NAME.lower()}"
    p.mkdir(parents=True, exist_ok=True)
    return p

def get_catalog_path() -> Path:
    return get_user_config_dir() / "db_catalog.json"
