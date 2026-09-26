"""Runtime proxy objects for 1C-style global namespace.

Provides:
  Довідники.НазваДовідника.*      (CatalogsProxy / CatalogProxy)
  Документи.НазваДокумента.*      (DocumentsProxy / DocumentProxy)

Usage in scripts:
  Рез = Довідники.Товари.НайтиПоКоду("001");
  Рез = Довідники.Товари.НайтиПоНайменуванню("Молоко");
  Рез = Довідники.Товари.ПустаяСсилка();
  Рез = Довідники.Товари.Список();
  Довідники.Товари.Вставити("002", "Масло", {"ціна": 50});
"""
from __future__ import annotations
import re
import getpass
import os
from typing import Any, Callable, Dict, List, Optional

from src.dsl.vm import MsArray, MsMap


class _EnumValues:
    """Small attribute-based enum namespace used by platform globals."""

    def __init__(self, **values: Any) -> None:
        self._values = dict(values)

    def __getattr__(self, name: str) -> Any:
        if str(name or "").startswith("_"):
            raise AttributeError(name)
        return self._values.get(name, str(name or ""))


class SystemInformationProxy:
    """Portable subset of the 1C/BAS SystemInformation object."""

    def __init__(self) -> None:
        import platform

        machine = platform.machine().lower()
        is_64 = "64" in machine
        system = platform.system().lower()
        if system == "linux":
            platform_type = "Linux_x86_64" if is_64 else "Linux_x86"
        elif system == "darwin":
            platform_type = "MacOS_x86_64" if is_64 else "MacOS_x86"
        else:
            platform_type = "Windows_x86_64" if is_64 else "Windows_x86"
        self.PlatformType = platform_type
        self.ТипПлатформы = platform_type
        self.ТипПлатформи = platform_type


class SessionParametersProxy:
    """Per-client values exposed through the BSL SessionParameters global."""

    def __init__(self) -> None:
        self.ClientParametersOnServer = MsMap()
        self.ПараметрыКлиентаНаСервере = self.ClientParametersOnServer
        self.ПараметриКлієнтаНаСервері = self.ClientParametersOnServer

    def __getattr__(self, name: str) -> Any:
        if str(name or "").startswith("_"):
            raise AttributeError(name)
        return None


def _to_runtime_value(value: Any) -> Any:
    if isinstance(value, dict):
        result = MsMap()
        for key, item in value.items():
            result[str(key)] = _to_runtime_value(item)
        return result
    if isinstance(value, list):
        return MsArray([_to_runtime_value(item) for item in value])
    return value


class _ValueStorageProxy:
    """False-safe representation of an imported 1C ValueStorage value."""

    def __init__(self, value: Any = None) -> None:
        self._value = _to_runtime_value(value)

    def Get(self) -> Any:
        return self._value

    def Получить(self) -> Any:
        return self.Get()

    def Отримати(self) -> Any:
        return self.Get()

    def __bool__(self) -> bool:
        return bool(self._value)

    def __str__(self) -> str:
        return "" if self._value is None else str(self._value)


class ConstantValueProxy:
    def __init__(self, db, name: str) -> None:
        self._db = db
        self._name = str(name or "").strip()

    def _row(self) -> Dict[str, Any] | None:
        try:
            table = self._db.table("data_constants")
            rows = table.select(where={"key": self._name}) or []
            if not rows:
                rows = table.select() or []
        except Exception:
            return None
        key = self._name.casefold()
        for row in rows:
            if isinstance(row, dict) and str(row.get("key") or "").strip().casefold() == key:
                return dict(row)
        return None

    def Get(self) -> Any:
        row = self._row()
        value = row.get("value") if isinstance(row, dict) else None
        if value is None or isinstance(value, (dict, list)):
            return _ValueStorageProxy(value)
        return _to_runtime_value(value)

    def Получить(self) -> Any:
        return self.Get()

    def Отримати(self) -> Any:
        return self.Get()

    def Set(self, value: Any) -> None:
        table = self._db.table("data_constants")
        row = self._row()
        if isinstance(row, dict):
            table.update({"key": row.get("key")}, {"value": value})
        else:
            table.insert({"key": self._name, "value": value})

    def Установить(self, value: Any) -> None:
        self.Set(value)

    def Встановити(self, value: Any) -> None:
        self.Set(value)

    def CreateValueManager(self):
        return ConstantValueManagerProxy(self)

    def СоздатьМенеджерЗначения(self):
        return self.CreateValueManager()

    def СтворитиМенеджерЗначення(self):
        return self.CreateValueManager()


class ConstantValueManagerProxy:
    def __init__(self, constant: ConstantValueProxy) -> None:
        self._constant = constant

    def Get(self) -> Any:
        return self._constant.Get()

    Получить = Get
    Отримати = Get

    def Set(self, value: Any) -> None:
        self._constant.Set(value)

    Установить = Set
    Встановити = Set

    def Refresh(self) -> None:
        return None

    Обновить = Refresh
    Оновити = Refresh


class ConstantsProxy:
    def __init__(self, db) -> None:
        self._db = db
        self._cache: Dict[str, ConstantValueProxy] = {}

    def _value(self, name: str) -> ConstantValueProxy:
        key = str(name or "").strip()
        folded = key.casefold()
        if folded not in self._cache:
            self._cache[folded] = ConstantValueProxy(self._db, key)
        return self._cache[folded]

    def __getitem__(self, name: str) -> ConstantValueProxy:
        return self._value(name)

    def __getattr__(self, name: str) -> ConstantValueProxy:
        if str(name or "").startswith("_"):
            raise AttributeError(name)
        return self._value(name)


class _PlatformNamespaceValue:
    """Non-persistent placeholder for a platform manager not deployed yet."""

    def __getattr__(self, name: str):
        if str(name or "").startswith("_"):
            raise AttributeError(name)
        return self

    def __call__(self, *_args, **_kwargs):
        return self

    def __getitem__(self, _key):
        return self

    def __iter__(self):
        return iter(())

    def __len__(self) -> int:
        return 0

    def __bool__(self) -> bool:
        return False

    def __eq__(self, other: object) -> bool:
        return other is None or other is False or other == "" or other == 0

    def Count(self) -> int:
        return 0

    Количество = Count
    Кількість = Count


class PlatformNamespaceProxy(_PlatformNamespaceValue):
    pass


class AccessControlProxy:
    """Read current MetaPlatform role grants through the Runtime-owned DB."""

    def __init__(self, db) -> None:
        self._db = db

    def _current_user(self) -> dict[str, Any] | None:
        try:
            users = self._db.table("sys_users").select() or []
        except Exception:
            return None
        candidates = [
            os.environ.get("META_USER_ID", ""),
            os.environ.get("META_USER_LOGIN", ""),
            getpass.getuser(),
            "system",
        ]
        for candidate in candidates:
            target = str(candidate or "").strip().casefold()
            if not target:
                continue
            for user in users:
                if not isinstance(user, dict):
                    continue
                aliases = {
                    str(user.get("user_id") or "").strip().casefold(),
                    str(user.get("login") or "").strip().casefold(),
                }
                if target in aliases and bool(user.get("is_active", True)):
                    return dict(user)
        return None

    def role_names(self) -> set[str]:
        user = self._current_user()
        if not isinstance(user, dict):
            return set()
        user_keys = {
            str(user.get("user_id") or "").strip(),
            str(user.get("login") or "").strip(),
        }
        try:
            links = self._db.table("sys_user_roles").select() or []
            roles = self._db.table("sys_roles").select() or []
        except Exception:
            return set()
        role_ids = {
            str(link.get("role_id") or "").strip()
            for link in links
            if isinstance(link, dict) and str(link.get("user_id") or "").strip() in user_keys
        }
        return {
            str(role.get("name") or "").strip().casefold()
            for role in roles
            if isinstance(role, dict) and str(role.get("role_id") or "").strip() in role_ids
        }

    def has_right(self, right: Any, *_args: Any) -> bool:
        roles = self.role_names()
        if "admin" in roles:
            return True
        target = str(right or "").strip().casefold()
        if target in {"администрирование", "administration", "адміністрування"}:
            return "configmaintainer" in roles
        return target in roles

    def role_available(self, role: Any) -> bool:
        return str(role or "").strip().casefold() in self.role_names()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tbl_catalog(name: str) -> str:
    return f"data_catalog_{name.lower()}"


def _tbl_doc_hdr(name: str) -> str:
    return f"data_document_{name.lower()}"


def _tbl_doc_rows(name: str) -> str:
    return f"data_document_{name.lower()}_rows"


# ---------------------------------------------------------------------------
# CatalogRef  — lightweight reference returned by lookups
# ---------------------------------------------------------------------------

class CatalogRef:
    """Reference to a single catalog row.  Behaves like a dict with attribute access."""

    EMPTY_ID = 0

    def __init__(self, name: str, db, row: Optional[Dict[str, Any]] = None):
        self._name = name
        self._db = db
        self._row: Dict[str, Any] = row or {}

    # Attribute access: ref.Код, ref.Найменування, ref.data
    def __getattr__(self, item: str):
        if item.startswith("_"):
            raise AttributeError(item)
        key_map = {
            # UK aliases
            "Код": "code", "Найменування": "name", "Дані": "data",
            # RU aliases
            "Код": "code", "Наименование": "name", "Данные": "data",
            # EN aliases
            "Code": "code", "Name": "name", "Data": "data",
        }
        key = key_map.get(item, item.lower())
        if key in self._row:
            return self._row[key]
        if "data" in self._row and isinstance(self._row["data"], dict):
            if item in self._row["data"]:
                return self._row["data"][item]
        return None

    def __bool__(self):
        return bool(self._row) and self._row.get("rowid", self.EMPTY_ID) != self.EMPTY_ID

    def __repr__(self):
        if not self._row:
            return f"<{self._name}: ПустаяСсилка>"
        return f"<{self._name}: {self._row.get('code','')} / {self._row.get('name','')}>"

    def __str__(self):
        return self._row.get("name") or self._row.get("code") or ""

    # ---- methods callable from script ----

    def ПустаяСсилка(self) -> bool:
        """ПустаяСсилка() → True якщо посилання порожнє."""
        return not bool(self)

    def EmptyRef(self) -> bool:
        return self.ПустаяСсилка()

    def ОтриматиОбʼєкт(self):
        """ОтриматиОбʼєкт() → повертає себе (для сумісності)."""
        return self

    def GetObject(self):
        return self.ОтриматиОбʼєкт()

    def ЗначенняПоля(self, field: str):
        return self.__getattr__(field)

    def FieldValue(self, field: str):
        return self.ЗначенняПоля(field)


# ---------------------------------------------------------------------------
# CatalogProxy  — Довідники.НазваДовідника
# ---------------------------------------------------------------------------

class CatalogProxy:
    """Proxy for a single catalog: Довідники.Товари.*"""

    def __init__(self, name: str, db):
        self._name = name
        self._db = db
        self._tbl = _tbl_catalog(name)

    def _table(self):
        try:
            return self._db.table(self._tbl)
        except Exception:
            return None

    def _wrap(self, row: Optional[Dict[str, Any]]) -> CatalogRef:
        return CatalogRef(self._name, self._db, row)

    # ---- ПустаяСсилка ----

    def ПустаяСсилка(self) -> CatalogRef:
        """Повертає порожнє посилання."""
        return CatalogRef(self._name, self._db, None)

    def EmptyRef(self) -> CatalogRef:
        return self.ПустаяСсилка()

    # ---- Список / GetList ----

    def Список(self, where: Optional[Dict] = None) -> List[CatalogRef]:
        """Повертає всі записи довідника."""
        t = self._table()
        if t is None:
            return []
        try:
            rows = t.select(where=where)
            return [self._wrap(r) for r in rows]
        except Exception:
            return []

    def GetList(self, where=None):
        return self.Список(where)

    # ---- НайтиПоКоду / FindByCode ----

    def НайтиПоКоду(self, code: str) -> CatalogRef:
        t = self._table()
        if t is None:
            return self.ПустаяСсилка()
        try:
            rows = t.select(where={"code": str(code)})
            return self._wrap(rows[0]) if rows else self.ПустаяСсилка()
        except Exception:
            return self.ПустаяСсилка()

    def FindByCode(self, code: str) -> CatalogRef:
        return self.НайтиПоКоду(code)

    # ---- НайтиПоНайменуванню / FindByName ----

    def НайтиПоНайменуванню(self, name: str) -> CatalogRef:
        t = self._table()
        if t is None:
            return self.ПустаяСсилка()
        try:
            rows = t.select(where={"name": str(name)})
            return self._wrap(rows[0]) if rows else self.ПустаяСсилка()
        except Exception:
            return self.ПустаяСсилка()

    def FindByName(self, name: str) -> CatalogRef:
        return self.НайтиПоНайменуванню(name)

    # ---- НайтиПоРеквізиту / FindByField ----

    def НайтиПоРеквізиту(self, field: str, value) -> CatalogRef:
        t = self._table()
        if t is None:
            return self.ПустаяСсилка()
        try:
            rows = t.select(where={field: value})
            return self._wrap(rows[0]) if rows else self.ПустаяСсилка()
        except Exception:
            return self.ПустаяСсилка()

    def FindByField(self, field: str, value) -> CatalogRef:
        return self.НайтиПоРеквізиту(field, value)

    # ---- Вставити / Insert ----

    def Вставити(self, code: str, name: str, data: Optional[Dict] = None) -> CatalogRef:
        t = self._table()
        if t is None:
            return self.ПустаяСсилка()
        try:
            rec = {"code": str(code), "name": str(name), "data": data or {}}
            rowid = int(t.insert(rec))
            rec["rowid"] = rowid
            return self._wrap(rec)
        except Exception:
            return self.ПустаяСсилка()

    def Insert(self, code: str, name: str, data=None) -> CatalogRef:
        return self.Вставити(code, name, data)

    # ---- Отримати / GetById ----

    def Отримати(self, rec_id: int) -> CatalogRef:
        t = self._table()
        if t is None:
            return self.ПустаяСсилка()
        try:
            rows = t.select(where={"rowid": int(rec_id)})
            return self._wrap(rows[0]) if rows else self.ПустаяСсилка()
        except Exception:
            return self.ПустаяСсилка()

    def GetById(self, rec_id: int) -> CatalogRef:
        return self.Отримати(rec_id)

    # ---- Видалити / Delete ----

    def Видалити(self, ref) -> None:
        t = self._table()
        if t is None:
            return
        try:
            rec_id = ref._row.get("rowid") if isinstance(ref, CatalogRef) else int(ref)
            if rec_id:
                t.delete({"rowid": int(rec_id)})
        except Exception:
            pass

    def Delete(self, ref) -> None:
        return self.Видалити(ref)

    def __repr__(self):
        return f"<CatalogProxy: {self._name}>"


# ---------------------------------------------------------------------------
# CatalogsProxy  — Довідники
# ---------------------------------------------------------------------------

class CatalogsProxy:
    """Top-level proxy: Довідники.НазваДовідника.Метод().

    Attribute access on this object returns a CatalogProxy for that catalog.
    Works purely by name — no manifest lookup required.
    """

    def __init__(self, db):
        self._db = db
        self._cache: Dict[str, CatalogProxy] = {}

    def __getattr__(self, name: str) -> CatalogProxy:
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._cache:
            self._cache[name] = CatalogProxy(name, self._db)
        return self._cache[name]

    def __repr__(self):
        return "<CatalogsProxy>"


# ---------------------------------------------------------------------------
# DocumentProxy  — Документи.НазваДокумента
# ---------------------------------------------------------------------------

class DocumentRef:
    """Reference to a single document header row."""

    def __init__(self, name: str, db, row: Optional[Dict[str, Any]] = None):
        self._name = name
        self._db = db
        self._row: Dict[str, Any] = row or {}

    def __bool__(self):
        return bool(self._row)

    def __getattr__(self, item: str):
        if item.startswith("_"):
            raise AttributeError(item)
        if item in self._row:
            return self._row[item]
        return None

    def __str__(self):
        return str(self._row.get("rowid", ""))

    def ПустаяСсилка(self) -> bool:
        return not bool(self)

    def EmptyRef(self) -> bool:
        return self.ПустаяСсилка()


class DocumentProxy:
    """Proxy for a single document type: Документи.Накладна.*"""

    def __init__(self, name: str, db):
        self._name = name
        self._db = db
        self._tbl_hdr = _tbl_doc_hdr(name)

    def _table(self):
        try:
            return self._db.table(self._tbl_hdr)
        except Exception:
            return None

    def _wrap(self, row):
        return DocumentRef(self._name, self._db, row)

    def ПустаяСсилка(self) -> DocumentRef:
        return DocumentRef(self._name, self._db, None)

    def EmptyRef(self) -> DocumentRef:
        return self.ПустаяСсилка()

    def Список(self) -> List[DocumentRef]:
        t = self._table()
        if t is None:
            return []
        try:
            return [self._wrap(r) for r in t.select()]
        except Exception:
            return []

    def GetList(self):
        return self.Список()

    def Отримати(self, doc_id: int) -> DocumentRef:
        t = self._table()
        if t is None:
            return self.ПустаяСсилка()
        try:
            rows = t.select(where={"rowid": int(doc_id)})
            return self._wrap(rows[0]) if rows else self.ПустаяСсилка()
        except Exception:
            return self.ПустаяСсилка()

    def GetById(self, doc_id: int) -> DocumentRef:
        return self.Отримати(doc_id)

    def __repr__(self):
        return f"<DocumentProxy: {self._name}>"


# ---------------------------------------------------------------------------
# DocumentsProxy  — Документи
# ---------------------------------------------------------------------------

class DocumentsProxy:
    """Top-level proxy: Документи.НазваДокумента.Метод()."""

    def __init__(self, db):
        self._db = db
        self._cache: Dict[str, DocumentProxy] = {}

    def __getattr__(self, name: str) -> DocumentProxy:
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._cache:
            self._cache[name] = DocumentProxy(name, self._db)
        return self._cache[name]

    def __repr__(self):
        return "<DocumentsProxy>"


class QueryResultProxy:
    """Small 1C-compatible query result used by startup/configuration code."""

    def __init__(self, rows: Optional[List[Dict[str, Any]]] = None) -> None:
        self._rows = list(rows or [])

    def Empty(self) -> bool:
        return not self._rows

    def Пустой(self) -> bool:
        return self.Empty()

    def Порожній(self) -> bool:
        return self.Empty()

    def Select(self):
        return iter(self._rows)

    def Выбрать(self):
        return self.Select()

    def Обрати(self):
        return self.Select()

    def Unload(self):
        return ValueTableProxy(self._rows)

    def Выгрузить(self):
        return self.Unload()

    def Вивантажити(self):
        return self.Unload()


class ValueTableProxy:
    """Zero-based row collection returned by BSL QueryResult.Unload()."""

    def __init__(self, rows: Optional[List[Dict[str, Any]]] = None) -> None:
        self._rows = [dict(row) for row in list(rows or []) if isinstance(row, dict)]

    def __iter__(self):
        return iter(self._rows)

    def __len__(self):
        return len(self._rows)

    def __getitem__(self, index: int):
        return self._rows[int(index)]

    def Count(self) -> int:
        return len(self._rows)

    def Количество(self) -> int:
        return len(self._rows)

    def Кількість(self) -> int:
        return len(self._rows)


class NotificationDescriptionProxy:
    """Runtime value for 1C ``ОписаниеОповещения`` callbacks."""

    def __init__(self, handler: str = "", target: Any = None, parameters: Any = None) -> None:
        self.ИмяПроцедуры = str(handler or "")
        self.Объект = target
        self.ДополнительныеПараметры = parameters

        self.HandlerName = self.ИмяПроцедуры
        self.Target = target
        self.Parameters = parameters


class QueryProxy:
    """Execute the metadata-existence SELECTs used by imported startup code.

    This is deliberately a narrow storage adapter, not a second SQL engine.
    It resolves register references through manifest GUID metadata and reads the
    deployed ``data_reg_*`` tables through the runtime-owned DB facade.
    """

    _REGISTER_REF = re.compile(
        r"(?:InformationRegister|РегистрСведений|Регіст(?:р|ри)Відомостей)\.([^\W\d]\w*)",
        flags=re.IGNORECASE | re.UNICODE,
    )

    def __init__(
        self,
        db,
        text: str = "",
        manifest_lookup: Callable[[str], Dict[str, Any] | None] | None = None,
    ) -> None:
        self._db = db
        self.Текст = str(text or "")
        self.Параметры = MsMap()
        self._manifest_lookup = manifest_lookup

    def SetParameter(self, name: str, value: Any) -> None:
        self.Параметры[str(name or "")] = value

    def УстановитьПараметр(self, name: str, value: Any) -> None:
        self.SetParameter(name, value)

    def ВстановитиПараметр(self, name: str, value: Any) -> None:
        self.SetParameter(name, value)

    def _manifest_register(self, name: str) -> Dict[str, Any] | None:
        if self._manifest_lookup is not None:
            return self._manifest_lookup(str(name or ""))
        try:
            manifest = self._db.table("manifest")
        except Exception:
            return None
        for field in ("name", "title"):
            try:
                rows = manifest.select(where={field: str(name or "").strip()}) or []
            except Exception:
                rows = []
            for row in rows:
                if str(row.get("type") or "").strip().lower() in {
                    "register",
                    "register_info",
                }:
                    return dict(row)
        return None

    def Execute(self) -> QueryResultProxy:
        rows: List[Dict[str, Any]] = []
        seen_tables: set[str] = set()
        for match in self._REGISTER_REF.finditer(str(self.Текст or "")):
            metadata = self._manifest_register(str(match.group(1) or ""))
            if not isinstance(metadata, dict):
                continue
            internal_name = str(metadata.get("name") or "").strip().lower()
            table_name = f"data_reg_{internal_name}" if internal_name else ""
            if not table_name or table_name in seen_tables:
                continue
            seen_tables.add(table_name)
            try:
                selected = self._db.table(table_name).select() or []
            except Exception:
                selected = []
            rows.extend(dict(row) for row in selected if isinstance(row, dict))
        return QueryResultProxy(rows)

    def Выполнить(self) -> QueryResultProxy:
        return self.Execute()

    def Виконати(self) -> QueryResultProxy:
        return self.Execute()

    def Цикл(self) -> QueryResultProxy:
        # Historical imported modules used this normalized alias for Execute.
        return self.Execute()

    def ExecuteBatch(self) -> MsArray:
        """Execute semicolon-separated 1C query statements independently."""

        statements = [part.strip() for part in str(self.Текст or "").split(";") if part.strip()]
        if not statements:
            return MsArray([self.Execute()])
        results = MsArray()
        for statement in statements:
            query = QueryProxy(self._db, statement, self._manifest_lookup)
            query.Параметры = MsMap(self.Параметры)
            results.Add(query.Execute())
        return results

    def ВыполнитьПакет(self) -> MsArray:
        return self.ExecuteBatch()

    def ВиконатиПакет(self) -> MsArray:
        return self.ExecuteBatch()


# ---------------------------------------------------------------------------
# build_global_context — call from _on_run to inject all global objects
# ---------------------------------------------------------------------------

def build_global_context(db) -> Dict[str, Any]:
    """Build the dict of global runtime objects to inject into execute_script.

    Returns a dict ready to be merged into builtins_patch.
    """
    catalogs = CatalogsProxy(db)
    documents = DocumentsProxy(db)
    constants = ConstantsProxy(db)
    exchange_plans = PlatformNamespaceProxy()
    information_base_users = PlatformNamespaceProxy()
    register_metadata_cache: Dict[str, Dict[str, Any] | None] = {}

    def resolve_register_metadata(name: str) -> Dict[str, Any] | None:
        key = str(name or "").strip().casefold()
        if key in register_metadata_cache:
            return register_metadata_cache[key]
        gateway = getattr(db, "_gw", None)
        if gateway is None or not hasattr(gateway, "manifest_lookup"):
            return None
        try:
            rows = gateway.manifest_lookup(type_name="register_info", name=str(name or ""), limit=10)
        except Exception:
            rows = []
        row = next((dict(item) for item in rows if isinstance(item, dict)), None)
        register_metadata_cache[key] = row
        return row

    query_lookup = resolve_register_metadata if getattr(db, "_gw", None) is not None else None
    query_factory = lambda text="": QueryProxy(db, text, query_lookup)
    notification_factory = lambda *args: NotificationDescriptionProxy(*args)
    set_privileged_mode = lambda _enabled=True: None
    privileged_mode = lambda: False
    system_information_factory = lambda: SystemInformationProxy()
    session_parameters = SessionParametersProxy()
    platform_types = _EnumValues(
        Linux_x86="Linux_x86",
        Linux_x86_64="Linux_x86_64",
        Windows_x86="Windows_x86",
        Windows_x86_64="Windows_x86_64",
        MacOS_x86="MacOS_x86",
        MacOS_x86_64="MacOS_x86_64",
    )
    symbols = _EnumValues(
        ВК="\r",
        ПС="\n",
        ВТаб="\v",
        НПП="\u00a0",
        ПФ="\f",
        Таб="\t",
        CR="\r",
        LF="\n",
        CRLF="\r\n",
        Tab="\t",
        NonBreakingSpace="\u00a0",
    )
    connection_string = lambda: str(getattr(db, "db_uid", "") or "")
    fixed_map_factory = lambda value=None: MsMap(value)
    functional_option = lambda _name: False
    set_safe_mode = lambda _enabled=True: None
    set_safe_data_separation_mode = lambda _name, _enabled=True: None
    predefined_data_update = {"value": "UpdateAutomatically"}
    get_predefined_data_update = lambda: predefined_data_update["value"]

    def set_predefined_data_update(value: Any) -> None:
        predefined_data_update["value"] = value

    predefined_data_update_modes = _EnumValues(
        НеОбновлятьАвтоматически="DoNotUpdateAutomatically",
        НеОновлюватиАвтоматично="DoNotUpdateAutomatically",
        DoNotUpdateAutomatically="DoNotUpdateAutomatically",
        ОбновлятьАвтоматически="UpdateAutomatically",
        ОновлюватиАвтоматично="UpdateAutomatically",
        UpdateAutomatically="UpdateAutomatically",
    )
    transaction_state = {"depth": 0}

    def begin_transaction() -> None:
        transaction_state["depth"] += 1

    def commit_transaction() -> None:
        transaction_state["depth"] = max(0, transaction_state["depth"] - 1)

    def rollback_transaction() -> None:
        transaction_state["depth"] = 0

    transaction_active = lambda: transaction_state["depth"] > 0
    exclusive_state = {"value": False}
    exclusive_mode = lambda: bool(exclusive_state["value"])

    def set_exclusive_mode(value: Any = True) -> None:
        exclusive_state["value"] = bool(value)

    refresh_reusable_values = lambda: None
    access_control = AccessControlProxy(db)
    context = {
        # Ukrainian
        "Довідники":  catalogs,
        "Документи":  documents,
        # Russian
        "Справочники": catalogs,
        "Документы":   documents,
        # English
        "Catalogs":   catalogs,
        "Documents":  documents,
        "Константы": constants,
        "Константи": constants,
        "Constants": constants,
        "ПланыОбмена": exchange_plans,
        "ПланиОбміну": exchange_plans,
        "ExchangePlans": exchange_plans,
        "ПользователиИнформационнойБазы": information_base_users,
        "КористувачіІнформаційноїБази": information_base_users,
        "InformationBaseUsers": information_base_users,
        "Запрос": query_factory,
        "Запит": query_factory,
        "Query": query_factory,
        "ОписаниеОповещения": notification_factory,
        "ОписСповіщення": notification_factory,
        "NotificationDescription": notification_factory,
        "УстановитьПривилегированныйРежим": set_privileged_mode,
        "ВстановитиПривілейованийРежим": set_privileged_mode,
        "SetPrivilegedMode": set_privileged_mode,
        "ПривилегированныйРежим": privileged_mode,
        "ПривілейованийРежим": privileged_mode,
        "PrivilegedMode": privileged_mode,
        "СистемнаяИнформация": system_information_factory,
        "СистемнаІнформація": system_information_factory,
        "SystemInformation": system_information_factory,
        "ТипПлатформы": platform_types,
        "ТипПлатформи": platform_types,
        "PlatformType": platform_types,
        "Символы": symbols,
        "Символи": symbols,
        "Symbols": symbols,
        "СтрокаСоединенияИнформационнойБазы": connection_string,
        "РядокЗєднанняІнформаційноїБази": connection_string,
        "InformationBaseConnectionString": connection_string,
        "ПараметрыСеанса": session_parameters,
        "ПараметриСеансу": session_parameters,
        "SessionParameters": session_parameters,
        "ФиксированноеСоответствие": fixed_map_factory,
        "ФіксованаВідповідність": fixed_map_factory,
        "FixedMap": fixed_map_factory,
        "ФиксированнаяСтруктура": fixed_map_factory,
        "ФіксованаСтруктура": fixed_map_factory,
        "FixedStructure": fixed_map_factory,
        "ПолучитьФункциональнуюОпцию": functional_option,
        "ОтриматиФункціональнуОпцію": functional_option,
        "GetFunctionalOption": functional_option,
        "УстановитьБезопасныйРежим": set_safe_mode,
        "ВстановитиБезпечнийРежим": set_safe_mode,
        "SetSafeMode": set_safe_mode,
        "УстановитьБезопасныйРежимРазделенияДанных": set_safe_data_separation_mode,
        "ВстановитиБезпечнийРежимРозділенняДаних": set_safe_data_separation_mode,
        "SetSafeDataSeparationMode": set_safe_data_separation_mode,
        "ПолучитьОбновлениеПредопределенныхДанныхИнформационнойБазы": get_predefined_data_update,
        "ОтриматиОновленняПередвизначенихДанихІнформаційноїБази": get_predefined_data_update,
        "GetPredefinedDataUpdate": get_predefined_data_update,
        "УстановитьОбновлениеПредопределенныхДанныхИнформационнойБазы": set_predefined_data_update,
        "ВстановитиОновленняПередвизначенихДанихІнформаційноїБази": set_predefined_data_update,
        "SetPredefinedDataUpdate": set_predefined_data_update,
        "ОбновлениеПредопределенныхДанных": predefined_data_update_modes,
        "ОновленняПередвизначенихДаних": predefined_data_update_modes,
        "PredefinedDataUpdate": predefined_data_update_modes,
        "МонопольныйРежим": exclusive_mode,
        "МонопольнийРежим": exclusive_mode,
        "ExclusiveMode": exclusive_mode,
        "УстановитьМонопольныйРежим": set_exclusive_mode,
        "ВстановитиМонопольнийРежим": set_exclusive_mode,
        "SetExclusiveMode": set_exclusive_mode,
        "НачатьТранзакцию": begin_transaction,
        "ПочатиТранзакцію": begin_transaction,
        "BeginTransaction": begin_transaction,
        "ЗафиксироватьТранзакцию": commit_transaction,
        "ЗафіксуватиТранзакцію": commit_transaction,
        "CommitTransaction": commit_transaction,
        "ОтменитьТранзакцию": rollback_transaction,
        "СкасуватиТранзакцію": rollback_transaction,
        "RollbackTransaction": rollback_transaction,
        "ТранзакцияАктивна": transaction_active,
        "ТранзакціяАктивна": transaction_active,
        "TransactionActive": transaction_active,
        "ОбновитьПовторноИспользуемыеЗначения": refresh_reusable_values,
        "ОновитиПовторноВикористовуваніЗначення": refresh_reusable_values,
        "RefreshReusableValues": refresh_reusable_values,
        "ПравоДоступа": access_control.has_right,
        "ПравоДоступу": access_control.has_right,
        "AccessRight": access_control.has_right,
        "РольДоступна": access_control.role_available,
        "РольДоступнаКористувачу": access_control.role_available,
        "RoleAvailable": access_control.role_available,
        "ПараметрЗапуска": "",
        "ПараметрЗапуску": "",
        "StartupParameter": "",
    }
    from src.runtime.script.metadata_proxy import build_metadata_context

    context.update(build_metadata_context(db))
    return context
