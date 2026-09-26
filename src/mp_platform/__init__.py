"""Platform layer built on top of mpdb.

This package contains higher-level constructs inspired by 1C:
- Catalogs (Справочники)
- Documents (Документы)
- Registers (Регистры)

The platform layer never changes mpdb on-disk formats.
"""

from .platform import MpPlatform, Catalog, Document, Register

__all__ = ["MpPlatform", "Catalog", "Document", "Register"]
