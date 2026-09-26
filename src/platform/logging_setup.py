from __future__ import annotations

import logging
from typing import Optional

def setup_logging(lang: str = "en", level: int = logging.INFO) -> None:
    """Configure root logging once.

    Language affects only our own message templates (use i18n.t for texts).
    """
    root = logging.getLogger()
    if getattr(root, "_mpdb_inited", False):
        return

    root.setLevel(level)

    handler = logging.StreamHandler()
    fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    handler.setFormatter(logging.Formatter(fmt=fmt, datefmt="%Y-%m-%d %H:%M:%S"))
    root.addHandler(handler)

    root._mpdb_inited = True  # type: ignore[attr-defined]

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
