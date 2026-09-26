from __future__ import annotations

"""Lazy metadata object exposed consistently to MetaScript runtimes."""

from typing import Any, Callable, Iterable

from src.dsl.module_introspection import repair_cp1251_mojibake_name
from src.dsl.platform_symbols import METADATA_CATEGORIES


class MetadataObjectProxy:
    def __init__(self, row: dict[str, Any]) -> None:
        self._row = dict(row or {})
        self._payload = self._row.get("payload") if isinstance(self._row.get("payload"), dict) else {}

    def __getitem__(self, key: str):
        return self._row[key]

    def get(self, key: str, default=None):
        return self._row.get(key, default)

    @property
    def Name(self) -> str:
        return str(self._row.get("name") or self._row.get("title") or "")

    Имя = property(lambda self: self.Name)
    Назва = property(lambda self: self.Name)
    @property
    def Synonym(self) -> str:
        title = str(self._row.get("title") or self.Name)
        return repair_cp1251_mojibake_name(title) or title

    Синоним = property(lambda self: self.Synonym)
    Синонім = property(lambda self: self.Synonym)
    Guid = property(lambda self: str(self._row.get("guid") or ""))
    GUID = property(lambda self: self.Guid)
    Type = property(lambda self: str(self._row.get("type") or ""))
    Тип = property(lambda self: self.Type)
    Parent = property(lambda self: str(self._row.get("parent_guid") or ""))
    Родитель = property(lambda self: self.Parent)
    Батько = property(lambda self: self.Parent)

    @property
    def FullName(self) -> str:
        return str(self._payload.get("metadata_ref") or f"{self.Type}.{self.Name}".strip("."))

    ПолноеИмя = property(lambda self: self.FullName)
    ПовнеІмя = property(lambda self: self.FullName)
    Properties = property(lambda self: dict(self._payload))
    Свойства = property(lambda self: self.Properties)
    Властивості = property(lambda self: self.Properties)

    def __getattr__(self, name: str):
        if str(name or "").startswith("_"):
            raise AttributeError(name)
        target = str(name or "").casefold()
        for source in (self._row, self._payload):
            for key, value in source.items():
                if str(key).casefold() == target:
                    return value
        raise AttributeError(name)


class MetadataCollectionProxy:
    def __init__(self, rows: Iterable[dict[str, Any]]) -> None:
        self._items = [MetadataObjectProxy(row) for row in rows if isinstance(row, dict)]

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, name: str):
        return self.Find(name)

    def __getattr__(self, name: str):
        if str(name or "").startswith("_"):
            raise AttributeError(name)
        return self.Find(name)

    def Count(self) -> int:
        return len(self._items)

    Количество = Count
    Кількість = Count

    def Find(self, name: str):
        target = str(name or "").casefold()
        return next(
            (
                item
                for item in self._items
                if target
                in {
                    item.Name.casefold(),
                    item.Synonym.casefold(),
                    str(item.get("title") or "").casefold(),
                }
            ),
            None,
        )

    Найти = Find
    Знайти = Find


class MetadataProxy:
    _ALIASES = {
        alias: category.type_name
        for category in METADATA_CATEGORIES
        for alias in category.names
    }

    def __init__(
        self,
        *,
        resolver: Callable[[str], list[dict[str, Any]]] | None = None,
        configuration: dict[str, Any] | None = None,
    ) -> None:
        self._resolver = resolver
        self._configuration = dict(configuration or {})
        self._collections: dict[str, MetadataCollectionProxy] = {}

    Name = property(lambda self: str(self._configuration.get("name") or self._configuration.get("title") or ""))
    Имя = property(lambda self: self.Name)
    Назва = property(lambda self: self.Name)

    @property
    def Version(self) -> str:
        payload = self._configuration.get("payload") if isinstance(self._configuration.get("payload"), dict) else {}
        return str(payload.get("version") or payload.get("Version") or "0.0.0.0")

    Версия = property(lambda self: self.Version)
    Версія = property(lambda self: self.Version)

    def __getattr__(self, name: str):
        type_name = self._ALIASES.get(str(name or ""), "")
        if not type_name:
            raise AttributeError(name)
        if type_name not in self._collections:
            rows = self._resolver(type_name) if callable(self._resolver) else []
            self._collections[type_name] = MetadataCollectionProxy(rows or [])
        return self._collections[type_name]

    def Find(self, ref: str):
        for category in METADATA_CATEGORIES:
            found = getattr(self, category.names[0]).Find(ref)
            if found is not None:
                return found
        return None

    Найти = Find
    Знайти = Find


def build_metadata_context(db, configuration: dict[str, Any] | None = None) -> dict[str, Any]:
    gateway = getattr(db, "_gw", None)

    def resolve(type_name: str) -> list[dict[str, Any]]:
        if gateway is None or not hasattr(gateway, "manifest_lookup"):
            return []
        try:
            return [
                dict(row)
                for row in gateway.manifest_lookup(type_name=str(type_name or ""), limit=10000)
                if isinstance(row, dict)
                and str(row.get("kind") or "object").strip().lower() == "object"
            ]
        except Exception:
            return []

    metadata = MetadataProxy(resolver=resolve, configuration=configuration)
    return {"Метадані": metadata, "Метаданные": metadata, "Metadata": metadata}
