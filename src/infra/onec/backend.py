"""The single, bundled .1CD backend used by MetaPlatform import services."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import threading
from typing import Any

_BACKEND_LOCK = threading.Lock()

@dataclass(frozen=True)
class Parse1CDBackend:
    parser_root: Path
    database_parser: Any
    schema_reader: Any
    reference_resolver: Any
    value_decoder: Any


def _load_backend() -> Parse1CDBackend:
    """Load our package without searching external installs or global modules.

    Configuration inspection and business-data migration deliberately share
    the same module and physical layout rules. The bundled reader opens source
    files read-only; source selection belongs to the caller, not to this loader.
    """
    from .parser import database_parser, reference_resolver, schema_reader, value_decoder

    return Parse1CDBackend(
        parser_root=Path(database_parser.__file__).resolve().parent,
        database_parser=database_parser,
        schema_reader=schema_reader,
        reference_resolver=reference_resolver,
        value_decoder=value_decoder,
    )


@lru_cache(maxsize=1)
def load_backend() -> Parse1CDBackend:
    # functools.lru_cache permits duplicate work during simultaneous first
    # calls. Keep the identity stable because callers share this backend.
    with _BACKEND_LOCK:
        return _load_backend()
