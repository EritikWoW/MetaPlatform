from __future__ import annotations

"""Bridge layer: 1C/BAS import model -> MetaPlatform DSL.

This module introduces a canonical intermediate representation step for imports:

    1C XML/BAS dump -> OneCMetaObject -> DSL AST -> localized DSL text

The goal is to normalize imported metadata into a format native for MetaPlatform,
with Ukrainian/English rendering independent from the original 1C source language.
"""

from dataclasses import dataclass
from typing import Iterable, Sequence

from src.dsl.ast import (
    CatalogDecl,
    DocumentDecl,
    EnumDecl,
    EnumValueDecl,
    FieldDecl,
    FormDecl,
    Program,
    RegisterDecl,
    SourceSpan,
    TablePartDecl,
    TopLevelItem,
    TypeRef,
)

from .onec_requisites_parser import OneCMetaObject, OneCTabularPart, OneCRequisite

DslLanguage = str


@dataclass(frozen=True, slots=True)
class DslArtifact:
    """Localized DSL representation bound to imported metadata object."""

    language: DslLanguage
    text: str
    object_type: str
    object_name: str
    source_uuid: str
    source_origin: str = ""


_KEYWORDS = {
    "uk": {
        "catalog": "Довідник",
        "document": "Документ",
        "enum": "Перерахування",
        "register": "Регістр",
        "fields": "реквізити",
        "table": "табличнаЧастина",
        "dimensions": "виміри",
        "resources": "ресурси",
        "form": "Форма",
        "string": "Рядок",
        "number": "Число",
        "bool": "Булево",
        "date": "Дата",
        "datetime": "ДатаЧас",
        "ref": "Посилання",
        "enum_ref": "ПерерахуванняПосилання",
        "any_ref": "БудьЯкеПосилання",
        "unknown": "Невідомо",
    },
    "en": {
        "catalog": "Catalog",
        "document": "Document",
        "enum": "Enum",
        "register": "Register",
        "fields": "fields",
        "table": "tablePart",
        "dimensions": "dimensions",
        "resources": "resources",
        "form": "Form",
        "string": "String",
        "number": "Number",
        "bool": "Boolean",
        "date": "Date",
        "datetime": "DateTime",
        "ref": "Ref",
        "enum_ref": "EnumRef",
        "any_ref": "AnyRef",
        "unknown": "Unknown",
    },
}

_TYPE_MAP = {
    "catalog": "catalog",
    "document": "document",
    "enumeration": "enum",
    "register_info": "register",
    "register_accum": "register",
    "register_accounting": "register",
    "register_calc": "register",
    "form": "form",
}


def _span() -> SourceSpan:
    return SourceSpan(1, 1)


def _safe_ident(name: str) -> str:
    out = []
    prev_us = False
    for ch in str(name or ""):
        if ch.isalnum() or ch == "_":
            out.append(ch if ch.isascii() else "_")
            prev_us = False
        else:
            if not prev_us:
                out.append("_")
                prev_us = True
    s = "".join(out).strip("_") or "ImportedObject"
    if s[0].isdigit():
        s = f"_{s}"
    return s


def _type_ref_from_req(req: OneCRequisite) -> TypeRef:
    base = str(req.mp_type or "unknown")
    qual = str(req.ref_name or "").strip() or None
    if qual:
        qual = _safe_ident(qual)
    return TypeRef(name=base, qualifier=qual, span=_span())


def _field_from_req(req: OneCRequisite) -> FieldDecl:
    return FieldDecl(name=_safe_ident(req.name), type_ref=_type_ref_from_req(req), span=_span())


def _table_from_tp(tp: OneCTabularPart) -> TablePartDecl:
    return TablePartDecl(
        name=_safe_ident(tp.name),
        fields=tuple(_field_from_req(col) for col in tp.columns),
        span=_span(),
    )


def object_to_ast(meta: OneCMetaObject) -> TopLevelItem | None:
    """Convert parsed 1C metadata into DSL AST node.

    Only the subset already represented by the current DSL AST is generated.
    Other object kinds can be added incrementally without changing import storage.
    """

    obj_type = str(meta.obj_type or "")
    name = _safe_ident(meta.name)
    span = _span()

    if obj_type == "catalog":
        return CatalogDecl(
            name=name,
            fields=tuple(_field_from_req(x) for x in meta.requisites),
            tabular_parts=tuple(_table_from_tp(x) for x in meta.tabular_parts),
            span=span,
        )
    if obj_type == "document":
        return DocumentDecl(
            name=name,
            fields=tuple(_field_from_req(x) for x in meta.requisites),
            tabular_parts=tuple(_table_from_tp(x) for x in meta.tabular_parts),
            span=span,
        )
    if obj_type == "enumeration":
        return EnumDecl(
            name=name,
            values=tuple(EnumValueDecl(name=_safe_ident(v.name), span=span) for v in meta.enum_values),
            span=span,
        )
    if obj_type in {"register_info", "register_accum", "register_accounting", "register_calc"}:
        return RegisterDecl(
            name=name,
            dimensions=tuple(),
            resources=tuple(),
            attributes=tuple(_field_from_req(x) for x in meta.requisites),
            span=span,
        )
    if obj_type == "form":
        qualified = name
        return FormDecl(qualified_name=qualified, table_columns=tuple(), span=span)
    return None


def object_to_program(meta: OneCMetaObject) -> Program | None:
    item = object_to_ast(meta)
    if item is None:
        return None
    return Program(items=(item,), span=_span())


def _render_type(type_ref: TypeRef | None, language: DslLanguage) -> str:
    kw = _KEYWORDS[language]
    if type_ref is None:
        return kw["unknown"]
    base = kw.get(type_ref.name, type_ref.name)
    if type_ref.qualifier:
        return f"{base}.{type_ref.qualifier}"
    return base


def _render_fields(fields: Sequence[FieldDecl], language: DslLanguage, indent: str = "    ") -> list[str]:
    out: list[str] = []
    for fld in fields:
        out.append(f"{indent}{_safe_ident(fld.name)}: {_render_type(fld.type_ref, language)}")
    return out


def render_program(program: Program, language: DslLanguage = "uk") -> str:
    kw = _KEYWORDS[language]
    lines: list[str] = []
    for item in program.items:
        if isinstance(item, CatalogDecl):
            lines.append(f"{kw['catalog']} {_safe_ident(item.name)} {{")
            if item.fields:
                lines.append(f"  {kw['fields']}:")
                lines.extend(_render_fields(item.fields, language, indent="    "))
            for tp in item.tabular_parts:
                lines.append(f"  {kw['table']} {_safe_ident(tp.name)} {{")
                if tp.fields:
                    lines.append(f"    {kw['fields']}:")
                    lines.extend(_render_fields(tp.fields, language, indent="      "))
                lines.append("  }")
            lines.append("}")
        elif isinstance(item, DocumentDecl):
            lines.append(f"{kw['document']} {_safe_ident(item.name)} {{")
            if item.fields:
                lines.append(f"  {kw['fields']}:")
                lines.extend(_render_fields(item.fields, language, indent="    "))
            for tp in item.tabular_parts:
                lines.append(f"  {kw['table']} {_safe_ident(tp.name)} {{")
                if tp.fields:
                    lines.append(f"    {kw['fields']}:")
                    lines.extend(_render_fields(tp.fields, language, indent="      "))
                lines.append("  }")
            lines.append("}")
        elif isinstance(item, EnumDecl):
            lines.append(f"{kw['enum']} {_safe_ident(item.name)} {{")
            for val in item.values:
                lines.append(f"    {_safe_ident(val.name)}")
            lines.append("}")
        elif isinstance(item, RegisterDecl):
            lines.append(f"{kw['register']} {_safe_ident(item.name)} {{")
            if item.dimensions:
                lines.append(f"  {kw['dimensions']}:")
                lines.extend(_render_fields(item.dimensions, language, indent="    "))
            if item.resources:
                lines.append(f"  {kw['resources']}:")
                lines.extend(_render_fields(item.resources, language, indent="    "))
            if item.attributes:
                lines.append(f"  {kw['fields']}:")
                lines.extend(_render_fields(item.attributes, language, indent="    "))
            lines.append("}")
        elif isinstance(item, FormDecl):
            lines.append(f"{kw['form']} {_safe_ident(item.qualified_name)} {{")
            lines.append("}")
    return "\n".join(lines).strip() + ("\n" if lines else "")


def meta_to_artifacts(meta: OneCMetaObject, languages: Iterable[DslLanguage] = ("uk", "en")) -> list[DslArtifact]:
    program = object_to_program(meta)
    if program is None:
        return []
    out: list[DslArtifact] = []
    for lang in languages:
        lang = str(lang or "uk").lower()
        if lang not in _KEYWORDS:
            continue
        out.append(
            DslArtifact(
                language=lang,
                text=render_program(program, language=lang),
                object_type=str(meta.obj_type or ""),
                object_name=str(meta.name or ""),
                source_uuid=str(meta.uuid or ""),
                source_origin=str(meta.origin_path or ""),
            )
        )
    return out
