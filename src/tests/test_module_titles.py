from src.ui_qt.i18n import set_lang
from src.ui_qt.module_titles import localized_code_name, localized_module_title


def test_system_module_title_follows_ui_language() -> None:
    try:
        set_lang("uk")
        assert localized_module_title("ObjectModule", fallback="Object module") == "Модуль об'єкта"
        assert localized_module_title("FormModule", fallback="FormModule") == "Модуль форми"

        set_lang("en")
        assert localized_module_title("ObjectModule", fallback="Модуль объекта") == "Object module"
        assert localized_module_title("SessionModule", fallback="SessionModule") == "Session module"
    finally:
        set_lang("en")


def test_business_module_name_is_not_translated() -> None:
    set_lang("uk")
    assert localized_module_title(
        "CommonModule",
        payload={"system": False},
        fallback="ФінансиКлієнт",
    ) == "ФінансиКлієнт"


def test_common_module_code_name_follows_selected_language() -> None:
    payload = {
        "code_refs": {
            "uk": "ЗагальнийМодуль.СтандартніПідсистемиПовтВик",
            "en": "CommonModule.StandardSubsystemsReuse",
        }
    }
    try:
        set_lang("uk")
        assert localized_code_name(payload, "internal-guid") == "СтандартніПідсистемиПовтВик"
        set_lang("en")
        assert localized_code_name(payload, "internal-guid") == "StandardSubsystemsReuse"
    finally:
        set_lang("en")


def test_common_module_source_name_is_not_replaced_by_synonym_alias() -> None:
    payload = {
        "source_name": "ПодключаемоеОборудованиеАтолЭлектронныеВесыКлиент",
        "code_refs": {
            "uk": "ЗагальнийМодуль.ОбробникДрайвера_deadbeef",
            "en": "CommonModule.DriverHandler_deadbeef",
        },
    }
    try:
        set_lang("uk")
        assert localized_code_name(payload, "internal-guid") == payload["source_name"]
        set_lang("en")
        assert localized_code_name(payload, "internal-guid") == payload["source_name"]
    finally:
        set_lang("en")
