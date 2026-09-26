from __future__ import annotations

import pytest

from src.dsl.vm import MsException
from src.runtime.script.module_registry import CommonModuleRegistry


def test_common_module_error_keeps_real_module_procedure_and_line() -> None:
    registry = CommonModuleRegistry(
        lambda _name: {
            "module_guid": "helper-guid",
            "lang": "uk",
            "text": (
                "Функція Run() Експорт\n"
                "    Missing = Невизначено\n"
                "    Повернути Missing()\n"
                "КінецьФункції\n"
            ),
        }
    )

    with pytest.raises(MsException) as raised:
        registry.call("Helper", "Run", [])

    assert str(raised.value) == (
        "'None' is not callable at module://helper-guid:Run:L3"
    )
    assert raised.value.module_id == "module://helper-guid"
    assert raised.value.procedure == "Run"
    assert raised.value.line == 3


def test_missing_platform_namespace_behaves_like_undefined() -> None:
    registry = CommonModuleRegistry(lambda _name: None)
    value = registry.namespace("SessionParameters").UnknownProperty

    assert not value
    assert value == None  # noqa: E711 - explicit MetaScript Undefined comparison
    assert value == ""
    assert value == 0
    assert list(value) == []


def test_dynamic_evaluate_returns_debuggable_common_module_namespace() -> None:
    sources = {
        "wrapper": (
            "Функція Run() Експорт\n"
            "    Повернути Вычислить(\"Target\").Value()\n"
            "КінецьФункції\n"
        ),
        "target": (
            "Функція Value() Експорт\n"
            "    Повернути 42\n"
            "КінецьФункції\n"
        ),
    }

    def resolve(name: str):
        source = sources.get(name.casefold())
        if source is None:
            return None
        return {"module_guid": f"{name.casefold()}-guid", "lang": "uk", "text": source}

    registry = CommonModuleRegistry(resolve)

    assert registry.call("Wrapper", "Run", []) == 42


def test_common_module_dispatch_uses_normalized_method_aliases() -> None:
    registry = CommonModuleRegistry(
        lambda _name: {
            "module_guid": "tools-guid",
            "lang": "uk",
            "text": (
                "Функція Очистить() Експорт\n"
                "    Повернути 42\n"
                "КінецьФункції\n"
            ),
        }
    )

    assert registry.call("Tools", "Очистити", []) == 42
