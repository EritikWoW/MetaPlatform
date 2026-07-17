"""Compatibility shim for manifest persistence.

Canonical manifest storage lives in ``src.configurator.persistence.manifest_io``.
This module remains only to preserve older import paths.
"""

from .persistence.manifest_io import *  # noqa: F401,F403
