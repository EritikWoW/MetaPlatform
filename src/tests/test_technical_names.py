from src.configurator.domain.technical_names import technical_object_name
from src.ui_qt.viewmodels.configurator_vm_state import ConfiguratorVmStateMixin


def test_source_identity_survives_slim_snapshot_without_loading_full_payload():
    payload = {"metadata_ref": "Document.ActualSource", "title": "Synonym", "form_model": {"large": True}}
    assert technical_object_name("PhysicalAlias", payload=payload) == "ActualSource"
    slim = ConfiguratorVmStateMixin._tree_payload_snapshot(payload)
    assert "form_model" not in slim
    assert technical_object_name("PhysicalAlias", payload=slim) == "ActualSource"


def test_source_name_wins_over_alias_and_synonym():
    assert technical_object_name("Alias", payload={"source_name": "Source", "synonym": "User label"}) == "Source"
    assert technical_object_name("NormalName", payload={"synonym": "User label"}) == "NormalName"
