from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from src.ui_qt.widgets.meta_object_shell import EditorSection


@dataclass(frozen=True, slots=True)
class EditorPageSpec:
    key: str
    title_i18n: str


def _page(key: str, title_i18n: str) -> EditorPageSpec:
    return EditorPageSpec(key=key, title_i18n=title_i18n)


EDITOR_PAGE_PROFILES: dict[str, tuple[EditorPageSpec, ...]] = {
    "catalog": (
        _page("main", "obj.section.main"),
        _page("subsystems", "obj.section.subsystems"),
        _page("data", "obj.section.data"),
        _page("attributes", "obj.section.attributes"),
        _page("tabular_parts", "obj.section.tabular_parts"),
        _page("modules", "obj.section.modules"),
        _page("forms", "obj.section.forms"),
        _page("commands", "obj.section.commands"),
        _page("layouts", "obj.section.layouts"),
    ),
    "chart_plan": (
        _page("main", "obj.section.main"),
        _page("subsystems", "obj.section.subsystems"),
        _page("data", "obj.section.data"),
        _page("attributes", "obj.section.attributes"),
        _page("tabular_parts", "obj.section.tabular_parts"),
        _page("modules", "obj.section.modules"),
        _page("commands", "obj.section.commands"),
        _page("layouts", "obj.section.layouts"),
    ),
    "document": (
        _page("main", "obj.section.main"),
        _page("subsystems", "obj.section.subsystems"),
        _page("functional_options", "obj.section.functional_options"),
        _page("data", "obj.section.data"),
        _page("numbering", "obj.section.numbering"),
        _page("movements", "obj.section.movements"),
        _page("sequences", "obj.section.sequences"),
        _page("journals", "obj.section.journals"),
        _page("forms", "obj.section.forms"),
        _page("input_by_string", "obj.section.input_by_string"),
        _page("commands", "obj.section.commands"),
        _page("layouts", "obj.section.layouts"),
        _page("based_on", "obj.section.based_on"),
        _page("rights", "obj.section.rights"),
        _page("exchange", "obj.section.exchange"),
        _page("other", "obj.section.other"),
    ),
    "register": (
        _page("main", "obj.section.main"),
        _page("dimensions", "register.dimensions"),
        _page("resources", "register.resources"),
        _page("attributes", "obj.section.attributes"),
    ),
    "enumeration": (
        _page("main", "obj.section.main"),
        _page("values", "enum.values"),
    ),
    "subsystem": (
        _page("main", "obj.section.main"),
        _page("functional_options", "obj.section.functional_options"),
        _page("objects", "subsystem.objects"),
        _page("other", "obj.section.other"),
    ),
    "role": (
        _page("main", "obj.section.main"),
        _page("rights", "role.rights"),
    ),
    "scheduled_job": (
        _page("main", "obj.section.main"),
        _page("schedule", "scheduled_job.schedule"),
    ),
    "event_subscription": (
        _page("main", "obj.section.main"),
        _page("event", "event_subscription.event"),
    ),
    "simple": (
        _page("main", "obj.section.main"),
    ),
}


PROFILE_ALIASES: dict[str, str] = {
    "business_process": "catalog",
    "chart_of_accounts": "chart_plan",
    "chart_of_calculation_types": "chart_plan",
    "chart_of_characteristic_types": "catalog",
    "data_processor": "catalog",
    "exchange_plan": "catalog",
    "register_info": "register",
    "register_accum": "register",
    "register_accounting": "register",
    "register_calc": "register",
    "report": "catalog",
    "task": "catalog",
}


def normalize_editor_profile_key(obj_type: str) -> str:
    key = str(obj_type or "").strip().lower()
    return PROFILE_ALIASES.get(key, key)


def get_editor_page_specs(obj_type: str) -> tuple[EditorPageSpec, ...]:
    profile_key = normalize_editor_profile_key(obj_type)
    return EDITOR_PAGE_PROFILES.get(profile_key, EDITOR_PAGE_PROFILES["simple"])


def build_editor_sections(
    obj_type: str,
    page_factories: Mapping[str, Callable[[], object]],
) -> list[EditorSection]:
    sections: list[EditorSection] = []
    for spec in get_editor_page_specs(obj_type):
        build = page_factories.get(spec.key)
        if build is None:
            continue
        sections.append(EditorSection(key=spec.key, title_i18n=spec.title_i18n, build=build))
    return sections
