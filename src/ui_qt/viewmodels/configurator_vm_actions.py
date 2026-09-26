from __future__ import annotations

"""Compatibility composition layer for ConfiguratorViewModel actions."""

from .configurator_vm_editor_actions import ConfiguratorVmEditorActionsMixin
from .configurator_vm_object_actions import ConfiguratorVmObjectActionsMixin


class ConfiguratorVmActionsMixin(
    ConfiguratorVmEditorActionsMixin,
    ConfiguratorVmObjectActionsMixin,
):
    """Backward-compatible action mixin kept as a stable import path."""


__all__ = ["ConfiguratorVmActionsMixin"]
