"""Atomic, Runtime-owned posting from saved ObjectModule code.

Scripts receive snapshots and movement buffers, never a live DB handle.
"""
from __future__ import annotations

import uuid

from .posting_script import MovementSet, Namespace, PostingBudget, PostingError, execute_posting, snapshot
from .posting_modules import PostingModuleRegistry
from src.configurator.domain.posting_mapping import field_aliases, field_definitions, tabular_definitions


class PostingResult:
    def __init__(self, *, doc_guid, action):
        self.doc_guid, self.action = doc_guid, action
        self.ok = True
        self.messages = []
        self.movements_written = 0

    def fail(self, message):
        self.ok = False
        self.messages.append(str(message))

    def info(self, message):
        self.messages.append(str(message))

    def to_dict(self):
        return dict(doc_guid=self.doc_guid, action=self.action, ok=self.ok,
                    messages=self.messages, movements_written=self.movements_written)

    @classmethod
    def from_dict(cls, data):
        result = cls(doc_guid=data["doc_guid"], action=data["action"])
        result.ok = data["ok"] is True
        result.messages = list(data.get("messages") or [])
        result.movements_written = int(data.get("movements_written") or 0)
        return result


REGISTER_TYPES = {
    "register_info": "InformationRegister", "register_accum": "AccumulationRegister",
    "register_accounting": "AccountingRegister", "register_calc": "CalculationRegister",
}


def _payload(db, row):
    from src.configurator.persistence.manifest_io import _load_manifest_payload_asset
    payload = dict(row.get("payload") or {})
    # Execution cannot ignore unreadable metadata as presentation hydration can.
    for key in ("register_records", "attributes", "requisites", "dimensions", "resources", "fields", "columns", "tabular_parts"):
        ref = payload.get(f"{key}_ref")
        if key not in payload and ref:
            payload[key] = _load_manifest_payload_asset(db, ref=ref)
    return payload


def _aliases(row):
    payload = row.get("payload") or {}
    names = {str(row.get("name") or ""), str(payload.get("source_name") or "")}
    ref = str(payload.get("metadata_ref") or "")
    if ref:
        names.add(ref.rsplit(".", 1)[-1])
    localized = payload.get("localized_names")
    if isinstance(localized, dict):
        names.update(str(v) for v in localized.values())
    return {n for n in names if n}


def _table_name(prefix, name):
    if not name or not name.isidentifier():
        raise PostingError(f"Invalid physical metadata name: {name}")
    return prefix + name.lower()


class PostingEngine:
    def __init__(self, db, manifest_rows=None):
        self._db, self._mrows = db, manifest_rows

    def post(self, *, doc_name, doc_guid):
        return self._change(doc_name=doc_name, doc_guid=doc_guid, action="post")

    def unpost(self, *, doc_name, doc_guid):
        return self._change(doc_name=doc_name, doc_guid=doc_guid, action="unpost")

    def _change(self, *, doc_name, doc_guid, action):
        result = PostingResult(doc_guid=doc_guid, action=action)
        try:
            if not doc_guid or not doc_name:
                raise PostingError("Document name and record GUID are required")
            if not callable(getattr(self._db, "transaction", None)):
                raise PostingError("Posting must execute inside Runtime")
            with self._db.transaction() as tx:
                self._execute(tx, doc_name, doc_guid, action, result)
        except Exception as exc:
            result.movements_written = 0
            result.fail(f"{type(exc).__name__}: {exc}")
            return result
        from .onec_virtual_tables import invalidate_native_rows
        invalidate_native_rows(self._db)
        result.info(f"Document {doc_guid}: {action} committed")
        return result

    def _execute(self, tx, doc_name, doc_guid, action, result):
        from src.configurator.manifest_schema import MANIFEST_TABLE
        db = self._db
        rows = self._mrows if self._mrows is not None else db.table(MANIFEST_TABLE).select()
        docs = [r for r in rows if r.get("type") == "document"
                and r.get("kind", "object") == "object"
                and doc_name.casefold() in {n.casefold() for n in _aliases(r)}]
        if len(docs) != 1:
            raise PostingError("Document metadata not found or ambiguous")
        document = dict(docs[0])
        document["payload"] = _payload(db, document)
        if action == "post" and str(document["payload"].get("posting") or "").casefold() in {
            "deny", "false", "disallow", "forbid", "not_supported", "заборонити",
        }:
            raise PostingError("Posting is disabled for this document")
        table_name = _table_name("data_document_", document["name"])
        if table_name not in db._meta.get("tables", {}):
            raise PostingError("Document has no native writable table; materialize imported data first")
        table = db.table(table_name)
        headers = table.select(where={"_guid": doc_guid})
        if len(headers) != 1:
            raise PostingError("Document record not found or ambiguous in native storage")
        header = dict(headers[0])
        for key in db._table_schema_fields(table_name, db._meta["tables"][table_name]):
            header.setdefault(key, None)
        if not isinstance(header.get("_posted", False), bool):
            raise PostingError("Invalid persisted Posted flag")
        if header.get("_deleted") and action == "post":
            raise PostingError("Cannot post a deleted document")
        if bool(header.get("_posted")) == (action == "post"):
            raise PostingError("Document is already posted" if action == "post" else "Document is not posted")
        if action == "unpost" and not isinstance(header.get("_posting_registers"), list):
            raise PostingError("Legacy posting has no register inventory; validate/migrate it before unposting")
        registers = self._registers(rows, document, header, action)
        modules = self._modules(document["guid"])
        objects = [r for r in modules if str(r.get("module_kind") or "").casefold() == "objectmodule"]
        if len(objects) != 1:
            raise PostingError("Exactly one saved ObjectModule is required")
        buffers, names = {}, {}
        for register in registers:
            register = dict(register, payload=_payload(db, register))
            reg_table = _table_name("data_reg_", register["name"])
            if reg_table not in db._meta.get("tables", {}):
                raise PostingError(f"Missing native register table: {reg_table}")
            if register["type"] not in {"register_info", "register_accum"}:
                raise PostingError(f"Posting for {register['type']} is not implemented yet")
            schema = db._table_schema_fields(reg_table, db._meta["tables"][reg_table])
            buffer = MovementSet(schema, header.get("_date"), require_kind=register["type"] == "register_accum",
                                 field_aliases=field_aliases(field_definitions(rows, register)))
            buffers[reg_table] = (register, buffer)
            for name in _aliases(register):
                key = name.casefold()
                if key in names and names[key] is not buffer:
                    raise PostingError(f"Ambiguous register alias: {name}")
                names[key] = buffer
        movements = Namespace(names)
        context = self._context(rows, document, header, movements, result)
        budget = PostingBudget()
        common_context = {name: context[name] for name in (
            "Message", "Повідомити", "Сообщить", "AccumulationRecordType",
            "ВидРухуНакопичення", "ВидДвиженияНакопления",
        )}
        registry = PostingModuleRegistry(rows, modules=self._modules, source=self._source,
                                         budget=budget, context=common_context)
        self._hook(modules, "BeforePost" if action == "post" else "BeforeUnpost", context, budget, registry)
        execute_posting(self._source(objects[0]), module_guid=objects[0]["module_guid"],
                        context=context, action=action, budget=budget, registry=registry)
        after_context = self._context(rows, document, dict(header, _posted=action == "post"), movements, result)
        self._hook(modules, "AfterPost" if action == "post" else "AfterUnpost", after_context, budget, registry)
        pending = {}
        for name, (_, buffer) in buffers.items():
            entries = buffer.validated()
            if action == "unpost" and entries:
                raise PostingError("Unposting handlers cannot add movements")
            if action == "post" and buffer._write:
                if not entries:
                    raise PostingError(f"Write enabled but no movements generated: {name}")
                pending[name] = entries
        if action == "post" and registers and not pending:
            raise PostingError("No movements generated for the document's selected registers")
        # Header and movements use the same transaction; no nested table commits.
        written_guids = [buffers[name][0]["guid"] for name in pending]
        if table.update_tx(tx, {"_guid": doc_guid}, {
            "_posted": action == "post", "_posting_registers": written_guids,
        }) != 1:
            raise PostingError("Document flag update failed")
        for name in buffers:
            target = db.table(name)
            if action == "unpost":
                target.delete_tx(tx, {"_recorder": doc_guid})
            elif target.select(where={"_recorder": doc_guid}):
                raise PostingError(f"Unposted document already has movements in {name}")
            for number, row in enumerate(pending.get(name, []), 1):
                target.insert_tx(tx, dict(row, _rec_guid=str(uuid.uuid4()),
                                          _recorder=doc_guid, _line_no=number))
                result.movements_written += 1

    def _registers(self, rows, document, header, action):
        refs = document["payload"].get("register_records") or []
        if not isinstance(refs, list) or any(not isinstance(r, str) for r in refs):
            raise PostingError("Invalid selected register references")
        registers = [r for r in rows if r.get("type") in REGISTER_TYPES
                     and r.get("kind", "object") == "object"]
        selected = {}
        for ref in refs:
            matches = [r for r in registers if ref.casefold() in {
                (REGISTER_TYPES[r["type"]] + "." + n).casefold() for n in _aliases(r)
            }]
            if len(matches) != 1:
                raise PostingError(f"Selected register missing or ambiguous: {ref}")
            selected[matches[0]["guid"]] = matches[0]
        if action == "unpost":
            for guid in header.get("_posting_registers") or []:
                matches = [r for r in registers if r["guid"] == guid]
                if len(matches) != 1:
                    raise PostingError(f"Previously written register missing: {guid}")
                selected[guid] = matches[0]
        return list(selected.values())

    def _modules(self, owner_guid):
        from src.configurator.persistence.modules_tables import MODULES_TABLE
        if MODULES_TABLE not in self._db._meta.get("tables", {}):
            return []
        return self._db.table(MODULES_TABLE).select(where={"owner_guid": owner_guid})

    def _source(self, row):
        if row.get("storage_kind") == "asset":
            source, _ = self._db.get_asset(row["content_ref"])
            return source.decode("utf-8-sig")
        text = row.get("text")
        if not isinstance(text, str) or not text.strip():
            raise PostingError(f"Module source unavailable: {row.get('module_guid')}")
        return text

    def _hook(self, modules, name, context, budget, registry):
        matches = [r for r in modules if name.casefold() in {
            str(r.get("module_kind") or "").casefold(), str(r.get("name") or "").casefold(),
        }]
        if len(matches) > 1:
            raise PostingError(f"Ambiguous hook: {name}")
        if matches:
            execute_posting(self._source(matches[0]), module_guid=matches[0]["module_guid"],
                            context=context, hook=name, budget=budget, registry=registry)

    def _context(self, rows, document, header, movements, result):
        values = dict(header)
        for row, fields in tabular_definitions(rows, document):
            table = _table_name("data_tp_", document["name"] + "_" + row["name"])
            records = self._db.table(table).select(where={"_doc_guid": header["_guid"]}, order_by="_line_no")
            schema = self._db._table_schema_fields(table, self._db._meta["tables"][table])
            records = [{**dict.fromkeys(schema), **record} for record in records]
            for alias in _aliases(row):
                if alias in values:
                    raise PostingError(f"Ambiguous tabular part alias: {alias}")
                values[alias] = tuple(snapshot(r, field_aliases(fields)) for r in records)
        document_fields = field_definitions(rows, document)
        obj = snapshot(values, field_aliases(document_fields))
        for alias in ("movements", "рухи", "движения"):
            obj._values[alias] = movements
        context = {name: getattr(obj, name) for name in values if not name.startswith("_") and name != "rowid"}
        context.update({field.name: getattr(obj, field.name) for field in document_fields})
        from .posting_script import FIELD_ALIASES
        for key, aliases in FIELD_ALIASES.items():
            if key in header:
                for alias in aliases:
                    context.setdefault(alias, header[key])
        for alias in ("ThisObject", "ЦейОбєкт", "ЭтотОбъект", "Объект", "Обєкт", "Object"):
            context[alias] = obj
        for alias in ("Movements", "Рухи", "Движения"):
            context[alias] = movements
        kinds = Namespace({"Receipt": "+", "Expense": "-", "Прихід": "+", "Витрата": "-", "Приход": "+", "Расход": "-"})
        for alias in ("AccumulationRecordType", "ВидРухуНакопичення", "ВидДвиженияНакопления"):
            context[alias] = kinds
        for alias in ("Message", "Повідомити", "Сообщить"):
            context[alias] = result.info
        for alias in ("Cancel", "Відмова", "Отказ"):
            context[alias] = False
        return context
