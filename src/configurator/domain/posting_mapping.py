"""Explicit movement mappings. No synonym matching or guessed business rules."""
from __future__ import annotations

from dataclasses import dataclass

from .posting_constructor import generate_posting_handler, validate_posting_handler
from .technical_names import technical_object_name
from src.dsl.languages import get_profile
from src.dsl.lexer import Lexer


@dataclass(frozen=True)
class PostingField:
    name: str
    storage_name: str
    value_type: str
    required: bool = False


FIELD_SECTIONS = {
    "attributes", "fields_folder", "tabular_part_fields", "dimensions",
    "dimensions_folder", "resources", "resources_folder",
}


def field_definitions(rows, owner):
    folders = {r["guid"] for r in rows if owner.get("guid") and r.get("parent_guid") == owner.get("guid")
               and r.get("type") in FIELD_SECTIONS}
    children = [r for r in rows if r.get("parent_guid") in folders
                and r.get("type") in {"attribute", "field", "dimension", "resource", "measure"}]
    if not children:
        payload = owner.get("payload") or {}
        for section in ("attributes", "requisites", "dimensions", "resources", "fields", "columns"):
            if payload.get(section + "_ref") and section not in payload:
                raise ValueError(f"Load posting metadata first: {owner.get('name')}.{section}")
            for item in payload.get(section) or []:
                if isinstance(item, dict):
                    children.append(dict(item, payload=item))
    fields = []
    by_storage = {}
    for row in children:
        payload = row.get("payload") or {}
        storage = str(row.get("name") or "")
        if not storage:
            raise ValueError("Unnamed posting field")
        spec = PostingField(
            technical_object_name(storage, payload=payload), storage,
            str(payload.get("value_type") or payload.get("type") or "String"),
            bool(payload.get("required") or payload.get("nullable") is False),
        )
        old = by_storage.get(storage.casefold())
        if old is not None and old != spec:
            raise ValueError(f"Ambiguous posting field: {storage}")
        if old is None:
            fields.append(spec)
            by_storage[storage.casefold()] = spec
    field_aliases(fields)
    return fields


def field_aliases(fields):
    aliases = {}
    for field in fields:
        for name in (field.name, field.storage_name):
            key = name.casefold()
            if key in aliases and aliases[key] != field.storage_name:
                raise ValueError(f"Ambiguous posting field alias: {name}")
            aliases[key] = field.storage_name
    return aliases


def tabular_definitions(rows, owner):
    folders = {r["guid"] for r in rows if owner.get("guid") and r.get("parent_guid") == owner.get("guid")
               and r.get("type") in {"tabular_parts", "tabular_parts_folder"}}
    parts = [r for r in rows if r.get("parent_guid") in folders
             and r.get("kind", "object") == "object"]
    if not parts:
        payload = owner.get("payload") or {}
        if payload.get("tabular_parts_ref") and "tabular_parts" not in payload:
            raise ValueError(f"Load posting metadata first: {owner.get('name')}.tabular_parts")
        parts = [dict(p, payload=p) for p in (owner.get("payload") or {}).get("tabular_parts", [])
                 if isinstance(p, dict)]
    return [(p, field_definitions(rows, p)) for p in parts]


def _identifier(name):
    if (not isinstance(name, str) or not name.isidentifier() or name.startswith("_")
            or Lexer(name, get_profile("mixed"), strict=True).tokenize()[0].type != "IDENT"):
        raise ValueError(f"Invalid code identifier: {name}")
    return name


def _type(value):
    value = str(value).strip().casefold()
    for canonical, aliases in {
        "number": {"number", "float", "decimal", "число", "дробове"},
        "integer": {"int", "integer", "ціле"},
        "string": {"str", "string", "text", "рядок", "текст", "строка"},
        "date": {"date", "datetime", "дата"},
        "boolean": {"bool", "boolean", "логічне", "булево"},
    }.items():
        if value in aliases:
            return canonical
    return value


def code_field(field, *, uk):
    if uk:
        return {"_date": "Дата", "_number": "Номер", "_guid": "Посилання", "_period": "Період"}.get(field.storage_name, field.name)
    return field.name


def compatible(source, target):
    return _type(source) == _type(target) or (_type(source) == "integer" and _type(target) == "number")


@dataclass
class PostingMappingSchema:
    document: list[PostingField]
    tabular_parts: dict[str, list[PostingField]]
    registers: dict[str, list[PostingField]]

    @classmethod
    def from_manifest(cls, rows, document_guid, register_refs):
        documents = [r for r in rows if r.get("guid") == document_guid and r.get("type") == "document"]
        if len(documents) != 1:
            raise ValueError("Document metadata not found or ambiguous")
        document = documents[0]
        doc_fields = [PostingField("Date", "_date", "Date"), PostingField("Number", "_number", "String"),
                      PostingField("Ref", "_guid", "String"), *field_definitions(rows, document)]
        parts = {}
        for part, fields in tabular_definitions(rows, document):
            name = technical_object_name(part.get("name"), payload=part.get("payload"))
            if name.casefold() in {n.casefold() for n in parts}:
                raise ValueError(f"Ambiguous tabular part: {name}")
            parts[name] = fields
        registers = {}
        types = {"register_info": "InformationRegister", "register_accum": "AccumulationRegister"}
        for ref in register_refs:
            matches = []
            for row in rows:
                prefix = types.get(row.get("type"))
                if not prefix or row.get("kind", "object") != "object":
                    continue
                payload = row.get("payload") or {}
                aliases = {str(payload.get("metadata_ref") or ""), f"{prefix}.{row.get('name')}",
                           f"{prefix}.{technical_object_name(row.get('name'), payload=payload)}"}
                if ref.casefold() in {a.casefold() for a in aliases}:
                    matches.append(row)
            if len(matches) != 1:
                raise ValueError(f"Register missing, ambiguous or unsupported: {ref}")
            registers[ref] = [PostingField("Period", "_period", "Date", True),
                              *field_definitions(rows, matches[0])]
        for fields in (doc_fields, *parts.values(), *registers.values()):
            field_aliases(fields)
        return cls(doc_fields, parts, registers)


def validate_mapping_shape(plan):
    if not isinstance(plan, dict) or plan.get("version") != 1 or not isinstance(plan.get("entries"), list):
        raise ValueError("Unsupported posting mapping format")
    for entry in plan["entries"]:
        if (not isinstance(entry, dict) or not isinstance(entry.get("register"), str)
                or not isinstance(entry.get("source", ""), str)
                or not isinstance(entry.get("direction", ""), str)
                or not isinstance(entry.get("fields"), dict)):
            raise ValueError("Invalid posting mapping entry")
        for target, binding in entry["fields"].items():
            if (not isinstance(target, str) or not isinstance(binding, dict)
                    or not isinstance(binding.get("scope"), str)
                    or not isinstance(binding.get("field"), str)):
                raise ValueError("Invalid posting field binding")
    refs = [entry["register"] for entry in plan["entries"]]
    if len(set(refs)) != len(refs):
        raise ValueError("Duplicate register mappings")


def generate_mapped_posting(plan, schema, *, language="uk"):
    """Validate a persisted plan against current metadata before generating code."""
    validate_mapping_shape(plan)
    entries = plan["entries"]
    refs = [e.get("register") for e in entries if isinstance(e, dict)]
    if (len(refs) != len(entries) or any(not isinstance(r, str) for r in refs)
            or len(set(refs)) != len(refs) or set(refs) != set(schema.registers)):
        raise ValueError("Mappings must cover exactly the selected registers")
    starter = generate_posting_handler(refs, language=language)
    uk = language == "uk"
    movements, write, add, true = ("Рухи", "Записувати", "Додати", "Істина") if uk else ("Movements", "Write", "Add", "True")
    obj = "ЦейОбєкт" if uk else "ThisObject"
    lines = [starter.splitlines()[0], ""]
    used_names = {f.name.casefold() for f in schema.document}
    used_names.update(n.casefold() for n in schema.tabular_parts)
    used_names.update({"відмова", "режимпроведення", "cancel", "postingmode"})

    def temporary(base):
        candidate, index = base, 1
        while candidate.casefold() in used_names:
            index += 1
            candidate = f"{base}{index}"
        used_names.add(candidate.casefold())
        return candidate

    for entry in entries:
        ref = entry["register"]
        name = _identifier(ref.split(".", 1)[1])
        source = entry.get("source", "")
        if not isinstance(source, str):
            raise ValueError("Invalid tabular source")
        if source and source not in schema.tabular_parts:
            raise ValueError(f"Tabular source no longer exists: {source}")
        direction = entry.get("direction", "")
        if ref.startswith("AccumulationRegister.") and direction not in {"receipt", "expense"}:
            raise ValueError(f"Choose Receipt or Expense: {ref}")
        if ref.startswith("InformationRegister.") and direction:
            raise ValueError(f"Information register has no movement direction: {ref}")
        mapping = entry.get("fields")
        if not isinstance(mapping, dict):
            raise ValueError(f"Missing field mappings: {ref}")
        targets = {f.name: f for f in schema.registers[ref]}
        if set(mapping) - set(targets):
            raise ValueError(f"Unknown target fields: {ref}")
        for field in targets.values():
            if field.required and field.name not in mapping:
                raise ValueError(f"Required mapping missing: {ref}.{field.name}")
        movement = temporary("Рух" if uk else "Movement")
        row = temporary("РядокРуху" if uk else "MovementRow")
        lines.append(f"    {movements}.{name}.{write} = {true};")
        indent = "    "
        if source:
            _identifier(source)
            lines.append(f"    Для Кожного {row} З {obj}.{source} Цикл" if uk else
                         f"    For Each {row} In {obj}.{source} Do")
            indent += "    "
        lines.append(f"{indent}{movement} = {movements}.{name}.{add}();")
        if direction:
            kind = ("Прихід" if direction == "receipt" else "Витрата") if uk else ("Receipt" if direction == "receipt" else "Expense")
            lines.append(f"{indent}{movement}." + (f"ВидРуху = ВидРухуНакопичення.{kind};" if uk else f"RecordType = AccumulationRecordType.{kind};"))
        for target in targets:
            if target not in mapping:
                continue
            binding = mapping[target]
            if not isinstance(binding, dict) or binding.get("scope") not in {"document", "row"}:
                raise ValueError(f"Invalid source binding: {target}")
            scope = binding["scope"]
            available = schema.document if scope == "document" else schema.tabular_parts.get(source, [])
            field = next((f for f in available if f.name == binding.get("field")), None)
            if field is None or not compatible(field.value_type, targets[target].value_type):
                raise ValueError(f"Missing or incompatible source: {ref}.{target}")
            lines.append(f"{indent}{movement}.{_identifier(code_field(targets[target], uk=uk))} = {obj if scope == 'document' else row}.{_identifier(code_field(field, uk=uk))};")
        if source:
            lines.append("    КінецьЦиклу;" if uk else "    EndDo;")
        lines.append("")
    lines.append(starter.splitlines()[-1])
    code = "\n".join(lines)
    validate_posting_handler(code)
    return code
