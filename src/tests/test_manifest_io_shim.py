from src.configurator import manifest_io as shim_manifest_io
from src.configurator.persistence import manifest_io as persistence_manifest_io


def test_manifest_io_top_level_is_compatibility_shim() -> None:
    assert shim_manifest_io.ensure_manifest is persistence_manifest_io.ensure_manifest
    assert shim_manifest_io.list_objects is persistence_manifest_io.list_objects
    assert shim_manifest_io.add_object is persistence_manifest_io.add_object
    assert shim_manifest_io.update_payload is persistence_manifest_io.update_payload
