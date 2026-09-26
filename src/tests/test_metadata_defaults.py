from __future__ import annotations

from src.configurator.domain.default_requisites import merge_requisites
from src.configurator.domain.metadata_defaults import ensure_payload_defaults


def test_merge_requisites_preserves_imported_name_based_entries() -> None:
    imported = {
        "name": "Организация",
        "title": {"uk": "Організація"},
        "type": "ref",
        "ref_name": "Организации",
        "required": True,
        "imported": {"source": "1c", "src_uuid": "req-1"},
    }

    merged = merge_requisites([imported], [{"code": "Number", "type": "string"}])

    assert merged == [imported, {"code": "Number", "type": "string"}]
    assert merged[0] is imported


def test_merge_requisites_deduplicates_code_and_name_case_insensitively() -> None:
    first = {"name": "Organization", "type": "ref"}
    duplicate = {"code": "organization", "type": "string"}

    assert merge_requisites([first, duplicate], []) == [first]


def test_document_defaults_do_not_drop_imported_onec_requisites() -> None:
    imported = {
        "name": "Организация",
        "title": {"uk": "Організація"},
        "type": "ref",
        "fill_checking": "ShowError",
        "hint": {"uk": "Організація підприємства"},
    }

    payload = ensure_payload_defaults(
        payload={"requisites": [imported]},
        obj_type="document",
    )

    assert payload["requisites"][0] == imported
    assert [item["code"] for item in payload["requisites"][1:]] == [
        "Number",
        "Date",
        "Posted",
        "DeletionMark",
        "Comment",
    ]
