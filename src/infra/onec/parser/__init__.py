"""Internal read-only Parse1CD backend used by MetaPlatform import services.

Derived from the Parse1CD data reader; no GUI, source database writer, or
machine-specific module search path is part of this package.
"""

from .database_parser import OneCDatabase

__all__ = ["OneCDatabase"]
