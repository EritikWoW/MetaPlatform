from src.ui_qt.widgets.register_editor import RegisterPayload


def test_register_payload_from_payload_uses_title_and_number_periodicity_fallback() -> None:
    payload = RegisterPayload.from_payload(
        {
            "title": {"uk": "БонусніБали", "en": "BonusPoints"},
            "number_periodicity": "quarter",
        }
    )

    assert payload.name == "БонусніБали"
    assert payload.title == "БонусніБали"
    assert payload.synonym == "БонусніБали"
    assert payload.periodicity == "quarter"
