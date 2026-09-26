"""src.ui_qt.services.tree_builder

Единая логика построения дерева конфигурации (QStandardItemModel).

В проекте ранее существовали две реализации построения дерева:
- ViewModel (`src/ui_qt/viewmodels/configurator_vm.py`)
- Controller (`src/configurator/configurator_controller.py`)

Дублирование приводило к расхождениям (правка в одном месте ломала другое).
Этот модуль содержит общий, повторно используемый алгоритм:

1) Фильтрация устаревших автогенерируемых папок (`forms/commands/layouts`)
   с учётом `object_policies`.
2) Поиск (search): оставляем совпадения и всех предков.
3) Построение `QStandardItemModel` в несколько проходов (pending-loop)
   с безопасной обработкой "сирот" (orphaned nodes).

Важно: модуль НЕ занимается UI-обвязкой (progress bar, pulse UI, expand).\
Эти действия остаются в конкретном слое (ViewModel / Controller).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence

from PySide6.QtGui import QStandardItem, QStandardItemModel

from src.core.object_policies import (
    get_object_policy,
    is_allowed_object_section,
    is_legacy_object_folder_node,
    ordered_object_sections,
    section_kind,
    section_i18n_key,
    should_create_object_folders,
)
from src.configurator.persistence.manifest_io import sys_object_folder_guid
from src.configurator.domain.technical_names import technical_object_name

from src.ui_qt.i18n import get_lang, t


@dataclass(frozen=True)
class VirtualNode:
    """Виртуальный узел дерева.

    Используется для секций схемы (Измерения/Ресурсы/...) которые:
    - должны отображаться в дереве (как в 1С),
    - но физически не хранятся в manifest как отдельные объекты/папки.

    Виртуальные узлы создаются поверх исходного списка manifest-узлов
    и передаются в общий алгоритм build_tree_model().
    """

    guid: str
    kind: str
    type: Any
    name: str
    title: str
    parent_guid: Optional[str]
    payload: Any = None


@dataclass(frozen=True)
class ProjectedNode:
    """Projected manifest node used for UI-only parent rewrites.

    Needed when the visible tree structure should differ from the physical
    manifest parentage without mutating the storage model.
    """

    guid: str
    kind: str
    type: Any
    name: str
    title: str
    parent_guid: Optional[str]
    payload: Any = None


class _NodeProto(Protocol):
    """Минимальный протокол объекта manifest-узла.

    Используется только для типизации. Реальные классы в проекте могут быть
    разными (`ManifestObject`, `ObjectLike` и т.п.).
    """

    guid: str
    kind: str
    type: Any
    name: str
    title: str
    parent_guid: Optional[str]
    payload: Any
@dataclass(frozen=True)
class BuildResult:
    """Результат построения дерева.

    Attributes:
        total_input: Сколько узлов было на входе.
        total_after_filter: Сколько узлов осталось после фильтров.
        built: Сколько узлов реально вставлено в модель.
        orphans: Сколько узлов пришлось "прибить" к корню как сирот.
    """

    total_input: int
    total_after_filter: int
    built: int
    orphans: int


ProgressCallback = Callable[[int, int], None]


def _filter_legacy_object_folders(objs: Sequence[_NodeProto]) -> List[_NodeProto]:
    """Скрыть устаревшие автогенерируемые папки для ресурсоподобных объектов.

    Ранее из-за бага могли создаваться подпапки `forms/commands/layouts` у
    объектов, которым они не нужны (например, у картинок). Эти подпапки
    остаются в manifest старых баз, но в дереве они показываться не должны.

    Фильтрация применяется к любому набору объектов.
    """

    by_guid_all: Dict[str, _NodeProto] = {o.guid: o for o in objs}
    hidden_folder_guids: set[str] = set()

    for o in objs:
        if o.kind != "folder":
            continue
        p = by_guid_all.get(o.parent_guid or "")
        if not p or p.kind != "object":
            continue

        # 3) Секцию "modules" внутри прикладных объектов в дереве больше не
        #    показываем. Доступ к модулям остаётся через editor самого объекта.
        #    Исключение не требуется для "common_modules": это отдельная
        #    системная папка верхнего уровня с именем "common_modules",
        #    а не вложенный folder "modules" внутри объекта.
        if str(o.name or "").strip().lower() == "modules":
            hidden_folder_guids.add(o.guid)
            continue

        # 1) Скрываем legacy-узлы старого бага.
        if is_legacy_object_folder_node(o.name):
            if not should_create_object_folders(str(p.type), getattr(p, "payload", None)):
                hidden_folder_guids.add(o.guid)
                continue

        # 2) Скрываем системные folder-секции, которые не разрешены политикой.
        #    Это важно при переходах между версиями: в базе могли остаться
        #    "лишние" подпапки, но UI должен показывать только актуальные.
        if section_kind(str(o.name)) == "folder":
            if not is_allowed_object_section(str(p.type), getattr(p, "payload", None), str(o.name)):
                hidden_folder_guids.add(o.guid)

    def has_hidden_ancestor(node: _NodeProto) -> bool:
        parent_guid = str(getattr(node, "parent_guid", "") or "")
        while parent_guid:
            if parent_guid in hidden_folder_guids:
                return True
            parent = by_guid_all.get(parent_guid)
            if parent is None:
                break
            parent_guid = str(getattr(parent, "parent_guid", "") or "")
        return False

    filtered: List[_NodeProto] = []
    for o in objs:
        if str(getattr(o, "guid", "") or "") in hidden_folder_guids:
            continue
        if has_hidden_ancestor(o):
            continue
        filtered.append(o)

    return filtered


def _apply_search_keep_ancestors(objs: Sequence[_NodeProto], search_text: str) -> List[_NodeProto]:
    """Фильтрация по строке поиска.

    Оставляет:
    - узлы, у которых `search_text` найден в (title/name/type)
    - всех предков этих узлов (чтобы ветка в дереве не терялась)
    """

    s = (search_text or "").strip().lower()
    if not s:
        return list(objs)

    by_guid: Dict[str, _NodeProto] = {o.guid: o for o in objs}
    keep: set[str] = set()

    def mark_ancestors(g: str) -> None:
        """Пометить всех предков узла как видимых.

        Используется поисковой фильтрацией: если узел подходит под search,
        мы также сохраняем в дереве всех его предков, чтобы ветка не “обрывалась”.
        """
        cur = by_guid.get(g)
        while cur and cur.parent_guid:
            pg = str(cur.parent_guid)
            if pg in keep:
                break
            keep.add(pg)
            cur = by_guid.get(pg)

    for o in objs:
        technical_name = technical_object_name(getattr(o, "name", ""), payload=getattr(o, "payload", None))
        hay = f"{technical_name} {getattr(o, 'title', '')} {getattr(o, 'name', '')} {getattr(o, 'type', '')}".lower()
        if s in hay:
            keep.add(o.guid)
            mark_ancestors(o.guid)

    return [o for o in objs if o.guid in keep]


def _inject_schema_sections(objs: Sequence[_NodeProto]) -> List[_NodeProto]:
    """Добавить виртуальные "схемные" секции под объектами.

    В 1С многие типы объектов показывают в дереве логические разделы
    ("Измерения", "Ресурсы", "Реквизиты", "Перерасчёты", "Таблицы", ...).
    В нашем manifest эти разделы пока не хранятся как отдельные записи.

    Вместо этого мы строим виртуальные узлы на лету, руководствуясь
    политиками :mod:`src.core.object_policies`.

    Примечание:
        Виртуальные узлы имеют `guid` с префиксом `virtual:` и не конфликтуют
        с реальными GUID объектов.
    """

    out: List[_NodeProto] = list(objs)

    # Быстрая карта для проверки, что у объекта уже нет реального узла с таким именем.
    # (например, если когда-то появится физическое хранение schema-разделов).
    children_by_parent: Dict[str, set[str]] = {}
    for o in objs:
        pg = getattr(o, "parent_guid", None)
        if not pg:
            continue
        children_by_parent.setdefault(str(pg), set()).add(str(getattr(o, "name", "")))

    for o in objs:
        if getattr(o, "kind", "") != "object":
            continue

        pol = get_object_policy(str(getattr(o, "type", "")), getattr(o, "payload", None))
        if not pol.sections:
            continue

        used_names = children_by_parent.get(str(o.guid), set())

        # `ObjectPolicy.sections` — это набор ключей секций (строки).
        # Конкретные параметры секции (kind, i18n) лежат в реестре SECTIONS
        # в `src.core.object_policies` и доступны через helper-функции.
        for sec_key in ordered_object_sections(str(getattr(o, "type", "")), getattr(o, "payload", None)):
            sec_key = str(sec_key or "").strip()
            if not sec_key:
                continue

            # Нас интересуют только секции типа "schema".
            if section_kind(sec_key) != "schema":
                continue
            if sec_key in used_names:
                continue

            i18n_key = section_i18n_key(sec_key)
            title = t(i18n_key) if i18n_key else sec_key
            out.append(
                VirtualNode(
                    guid=f"virtual:{o.guid}:{sec_key}",
                    kind="schema",
                    type=str(getattr(o, "type", "")),
                    name=sec_key,
                    title=title,
                    parent_guid=str(o.guid),
                    payload={
                        "system": True,
                        "virtual": True,
                        "section": sec_key,
                        "i18n": i18n_key,
                    },
                )
            )

    return out


def _inject_folder_sections(objs: Sequence[_NodeProto]) -> List[_NodeProto]:
    """Add virtual system folders for allowed object sections.

    1C shows empty system folders like "Forms" even when the imported dump
    does not contain a physical folder row for them. We project those folders
    into the tree with deterministic GUIDs so navigation and creation actions
    can still target a stable parent.
    """

    by_guid: Dict[str, _NodeProto] = {
        str(getattr(node, "guid", "") or ""): node
        for node in objs
        if str(getattr(node, "guid", "") or "")
    }
    out: List[_NodeProto] = []
    for node in objs:
        parent = by_guid.get(str(getattr(node, "parent_guid", "") or ""))
        section_key = str(getattr(node, "name", "") or "").strip()
        if (
            getattr(node, "kind", "") == "folder"
            and parent is not None
            and getattr(parent, "kind", "") == "object"
            and section_kind(section_key) == "folder"
            and is_allowed_object_section(
                str(getattr(parent, "type", "") or ""),
                getattr(parent, "payload", None),
                section_key,
            )
        ):
            payload = dict(getattr(node, "payload", None) or {})
            payload.update({
                "system": True,
                "protected": True,
                "auto": True,
                "section": section_key,
            })
            payload.setdefault("menu", "add_only")
            i18n_key = section_i18n_key(section_key)
            out.append(
                ProjectedNode(
                    guid=str(getattr(node, "guid", "") or ""),
                    kind="folder",
                    type=getattr(node, "type", ""),
                    name=section_key,
                    title=t(i18n_key) if i18n_key else str(getattr(node, "title", "") or section_key),
                    parent_guid=str(getattr(node, "parent_guid", "") or ""),
                    payload=payload,
                )
            )
            continue
        out.append(node)

    children_by_parent: Dict[str, set[str]] = {}
    for o in out:
        pg = getattr(o, "parent_guid", None)
        if not pg:
            continue
        children_by_parent.setdefault(str(pg), set()).add(str(getattr(o, "name", "")))

    for o in out:
        if getattr(o, "kind", "") != "object":
            continue

        pol = get_object_policy(str(getattr(o, "type", "")), getattr(o, "payload", None))
        if not pol.sections:
            continue

        used_names = children_by_parent.get(str(o.guid), set())

        for sec_key in ordered_object_sections(str(getattr(o, "type", "")), getattr(o, "payload", None)):
            sec_key = str(sec_key or "").strip()
            if not sec_key:
                continue
            if section_kind(sec_key) != "folder":
                continue
            if sec_key in used_names:
                continue

            i18n_key = section_i18n_key(sec_key)
            title = t(i18n_key) if i18n_key else sec_key
            out.append(
                VirtualNode(
                    guid=sys_object_folder_guid(parent_guid=str(o.guid), section_key=sec_key),
                    kind="folder",
                    type=str(getattr(o, "type", "")),
                    name=sec_key,
                    title=title,
                    parent_guid=str(o.guid),
                    payload={
                        "system": True,
                        "virtual": True,
                        "protected": True,
                        "auto": True,
                        "menu": "add_only",
                        "section": sec_key,
                    },
                )
            )

    return out


_DOCUMENT_SPECIAL_FOLDERS: Dict[str, tuple[str, str]] = {
    "document_numerators": ("document_numerator", "tree.document_numerators"),
    "sequences": ("sequence", "obj.section.sequences"),
}
_DOCUMENT_SPECIAL_OBJECT_TYPES = {
    "document_numerator": "document_numerators",
    "sequence": "sequences",
}


def _special_document_folder_guid(document_group_guid: str, folder_name: str) -> str:
    return _virtual_guid(document_group_guid, "document_group_folder", folder_name)


def _project_document_special_folders(objs: Sequence[_NodeProto]) -> List[_NodeProto]:
    """Project numerators and sequences under the Documents group.

    Physical manifest rows for ``document_numerator`` and ``sequence`` may
    come from historical imports with their own top-level folders. In the UI
    they should always live under the main ``document`` group, matching the
    expected 1C-like tree.
    """

    document_groups = [
        str(getattr(o, "guid", "") or "")
        for o in objs
        if getattr(o, "kind", "") == "group" and str(getattr(o, "type", "") or "") == "document"
    ]
    if not document_groups:
        return list(objs)

    document_group_guid = document_groups[0]
    folder_guid_by_name = {
        name: _special_document_folder_guid(document_group_guid, name)
        for name in _DOCUMENT_SPECIAL_FOLDERS
    }

    out: List[_NodeProto] = []
    injected_folders = False

    def is_hidden_legacy_document_folder(node: _NodeProto) -> bool:
        if getattr(node, "kind", "") not in ("folder", "group"):
            return False
        node_name = str(getattr(node, "name", "") or "").strip()
        node_type = str(getattr(node, "type", "") or "").strip()
        return node_name in _DOCUMENT_SPECIAL_FOLDERS or node_type in _DOCUMENT_SPECIAL_FOLDERS

    for node in objs:
        if is_hidden_legacy_document_folder(node):
            continue

        if (
            not injected_folders
            and getattr(node, "kind", "") == "group"
            and str(getattr(node, "guid", "") or "") == document_group_guid
        ):
            out.append(node)
            for folder_name, (folder_type, i18n_key) in _DOCUMENT_SPECIAL_FOLDERS.items():
                out.append(
                    VirtualNode(
                        guid=folder_guid_by_name[folder_name],
                        kind="folder",
                        type=folder_type,
                        name=folder_name,
                        title=t(i18n_key),
                        parent_guid=document_group_guid,
                        payload={
                            "system": True,
                            "virtual": True,
                            "protected": True,
                            "auto": True,
                            "menu": "add_only",
                            "document_special": True,
                        },
                    )
                )
            injected_folders = True
            continue

        node_type = str(getattr(node, "type", "") or "").strip()
        target_folder_name = _DOCUMENT_SPECIAL_OBJECT_TYPES.get(node_type)
        if target_folder_name:
            out.append(
                ProjectedNode(
                    guid=str(getattr(node, "guid", "") or ""),
                    kind=str(getattr(node, "kind", "") or ""),
                    type=getattr(node, "type", ""),
                    name=str(getattr(node, "name", "") or ""),
                    title=str(getattr(node, "title", "") or ""),
                    parent_guid=folder_guid_by_name[target_folder_name],
                    payload=getattr(node, "payload", None),
                )
            )
            continue

        out.append(node)

    if not injected_folders:
        out.extend(
            VirtualNode(
                guid=folder_guid_by_name[folder_name],
                kind="folder",
                type=folder_type,
                name=folder_name,
                title=t(i18n_key),
                parent_guid=document_group_guid,
                payload={
                    "system": True,
                    "virtual": True,
                    "protected": True,
                    "auto": True,
                    "menu": "add_only",
                    "document_special": True,
                },
            )
            for folder_name, (folder_type, i18n_key) in _DOCUMENT_SPECIAL_FOLDERS.items()
        )

    return out


def _project_subsystems_under_common_folder(objs: Sequence[_NodeProto]) -> List[_NodeProto]:
    """Keep subsystem hierarchy as imported.

    Earlier versions projected all subsystem objects into a flat
    "Common -> Subsystems" bucket. That loses the nested 1C structure for
    configurations where subsystems contain child subsystems.

    The manifest already stores correct ``parent_guid`` links for nested
    subsystems, so the tree builder should preserve them unchanged.
    """

    return list(objs)


_SCHEMA_PAYLOAD_KEYS: Dict[str, tuple[str, ...]] = {
    "attributes": ("requisites", "attributes"),
    "addressing_attributes": ("addressing_attributes",),
    "tabular_parts": ("tabular_parts",),
    "dimensions": ("dimensions",),
    "resources": ("resources",),
    "values": ("enum_values", "values"),
    "graphs": ("graphs",),
    "recalculations": ("recalculations",),
    "tables": ("tables",),
    "cubes": ("cubes",),
    "functions": ("functions",),
    "columns": ("columns",),
    "totals": ("totals",),
    "recalculations_data": ("recalculations_data",),
    "recalculation_attributes": ("recalculation_attributes",),
}


def _virtual_guid(owner_guid: str, section_key: str, *parts: Any) -> str:
    base = [f"virtual:{str(owner_guid or '').strip()}:{str(section_key or '').strip()}"]
    for part in parts:
        chunk = str(part or "").strip()
        if not chunk:
            continue
        base.append(chunk.replace(":", "_"))
    return ":".join(base)


def _payload_items(payload: Any, *keys: str) -> List[Dict[str, Any]]:
    p = payload if isinstance(payload, dict) else {}

    for key in keys:
        raw = p.get(key)
        if isinstance(raw, list) and raw:
            return [dict(x) for x in raw if isinstance(x, dict)]

    for key in keys:
        raw = p.get(key)
        if isinstance(raw, list):
            return [dict(x) for x in raw if isinstance(x, dict)]

    return []


def _schema_item_name(item: Dict[str, Any], *, fallback: str) -> str:
    return technical_object_name(item.get("name"), payload=item, fallback=fallback)


def _schema_item_title(item: Dict[str, Any], *, fallback: str) -> str:
    raw_title = item.get("title")
    if isinstance(raw_title, dict):
        # Imported schema payloads keep the technical name and localized
        # presentation separately.  The tree must show the presentation while
        # preserving `name` as the stable identifier in the virtual GUID.
        for lang in (get_lang(), "uk", "en", "ru"):
            value = str(raw_title.get(lang) or "").strip()
            if value:
                return value
        for value in raw_title.values():
            text = str(value or "").strip()
            if text:
                return text
    elif str(raw_title or "").strip():
        return str(raw_title).strip()
    return str(fallback or "").strip()


def _schema_section_parents(objs: Sequence[_NodeProto]) -> Dict[tuple[str, str], str]:
    out: Dict[tuple[str, str], str] = {}
    for o in objs:
        if getattr(o, "kind", "") != "schema":
            continue
        parent_guid = str(getattr(o, "parent_guid", "") or "")
        if not parent_guid:
            continue
        payload = getattr(o, "payload", None)
        sec_key = ""
        if isinstance(payload, dict):
            sec_key = str(payload.get("section") or "").strip()
        if not sec_key:
            sec_key = str(getattr(o, "name", "") or "").strip()
        if sec_key:
            out[(parent_guid, sec_key)] = str(getattr(o, "guid", "") or "")
    return out


def _inject_schema_children(objs: Sequence[_NodeProto]) -> List[_NodeProto]:
    """Materialize child nodes for virtual schema sections from object payload.

    The importer already stores parsed requisites/tabular parts/etc. inside the
    owner object payload. This helper projects those structures into the tree so
    the configurator can display 1C-like branches:
    - Attributes/Requisites -> fields
    - Tabular parts -> parts -> columns
    - Dimensions/Resources/Values/... -> direct child items
    """

    out: List[_NodeProto] = list(objs)
    section_parents = _schema_section_parents(objs)
    used_guids = {str(getattr(o, "guid", "") or "") for o in objs}

    def add_node(node: VirtualNode) -> None:
        if node.guid in used_guids:
            return
        used_guids.add(node.guid)
        out.append(node)

    for o in objs:
        if getattr(o, "kind", "") != "object":
            continue

        owner_guid = str(getattr(o, "guid", "") or "")
        owner_type = str(getattr(o, "type", "") or "")
        payload = getattr(o, "payload", None)
        pol = get_object_policy(owner_type, payload)

        for sec_key in ordered_object_sections(owner_type, payload):
            sec_key = str(sec_key or "").strip()
            if not sec_key or section_kind(sec_key) != "schema":
                continue

            section_guid = section_parents.get((owner_guid, sec_key))
            if not section_guid:
                continue

            if sec_key == "tabular_parts":
                for idx, tp in enumerate(_payload_items(payload, "tabular_parts"), start=1):
                    tp_name = _schema_item_name(tp, fallback=f"tabular_part_{idx}")
                    tp_title = _schema_item_title(tp, fallback=tp_name)
                    tp_guid = _virtual_guid(owner_guid, sec_key, tp_name)
                    add_node(
                        VirtualNode(
                            guid=tp_guid,
                            kind="schema",
                            type=owner_type,
                            name=tp_name,
                            title=tp_title,
                            parent_guid=section_guid,
                            payload={
                                "system": True,
                                "virtual": True,
                                "section": sec_key,
                                "schema_item_kind": "tabular_part",
                                "schema_item": dict(tp),
                            },
                        )
                    )
                    for col_idx, col in enumerate(_payload_items(tp, "columns"), start=1):
                        col_name = _schema_item_name(col, fallback=f"column_{col_idx}")
                        col_title = _schema_item_title(col, fallback=col_name)
                        add_node(
                            VirtualNode(
                                guid=_virtual_guid(owner_guid, sec_key, tp_name, col_name),
                                kind="schema",
                                type=owner_type,
                                name=col_name,
                                title=col_title,
                                parent_guid=tp_guid,
                                payload={
                                    "system": True,
                                    "virtual": True,
                                    "section": sec_key,
                                    "schema_item_kind": "column",
                                    "tabular_part": tp_name,
                                    "schema_item": dict(col),
                                },
                            )
                        )
                continue

            payload_keys = _SCHEMA_PAYLOAD_KEYS.get(sec_key, (sec_key,))
            for idx, item in enumerate(_payload_items(payload, *payload_keys), start=1):
                item_name = _schema_item_name(item, fallback=f"{sec_key}_{idx}")
                item_title = _schema_item_title(item, fallback=item_name)
                add_node(
                    VirtualNode(
                        guid=_virtual_guid(owner_guid, sec_key, item_name),
                        kind="schema",
                        type=owner_type,
                        name=item_name,
                        title=item_title,
                        parent_guid=section_guid,
                        payload={
                            "system": True,
                            "virtual": True,
                            "section": sec_key,
                            "schema_item_kind": sec_key.rstrip("s"),
                            "schema_item": dict(item),
                        },
                    )
                )

    return out


def _apply_subsystem_filter(objs: Sequence[_NodeProto], subsystem_guid: str) -> List[_NodeProto]:
    """Keep only objects that belong to the given subsystem plus all their ancestors.

    Membership is determined by ``payload.subsystems`` containing *subsystem_guid*
    on the individual manifest object.  System nodes (groups, virtual folders, schema
    sections) are always kept when they are ancestors of matching objects so the tree
    path stays visible.
    """
    sg = (subsystem_guid or "").strip()
    if not sg:
        return list(objs)

    by_guid: Dict[str, _NodeProto] = {o.guid: o for o in objs}
    keep: set[str] = set()

    def _mark_ancestors(g: str) -> None:
        cur = by_guid.get(g)
        while cur and cur.parent_guid:
            pg = str(cur.parent_guid)
            if pg in keep:
                break
            keep.add(pg)
            cur = by_guid.get(pg)

    for o in objs:
        payload = getattr(o, "payload", None)
        payload = payload if isinstance(payload, dict) else {}
        subsystems = payload.get("subsystems")
        if isinstance(subsystems, list) and sg in subsystems:
            keep.add(o.guid)
            _mark_ancestors(o.guid)

    return [o for o in objs if o.guid in keep]


def prepare_tree_objects(objs: Sequence[_NodeProto],
                         *,
                         search_text: str = "",
                         subsystem_filter_guid: str = "",
                         hide_legacy_object_folders: bool = True,
                         ) -> List[_NodeProto]:
    """Подготовить список узлов для построения дерева.

    Args:
        objs: Список узлов manifest.
        search_text: Строка поиска (можно пустую).
        subsystem_filter_guid: GUID подсистемы для фильтрации (пустая строка — без фильтра).
        hide_legacy_object_folders: Если True — скрываем устаревшие папки.

    Returns:
        Список узлов, который можно безопасно отдавать в build_tree_model().
    """

    out: List[_NodeProto] = list(objs)
    if hide_legacy_object_folders:
        out = _filter_legacy_object_folders(out)
    # Добавляем виртуальные folder-секции (Формы/Команды/Макеты/...) для
    # объектов, у которых в дампе нет физической папки, но секция допустима.
    out = _inject_folder_sections(out)
    out = _project_document_special_folders(out)
    out = _project_subsystems_under_common_folder(out)
    if hide_legacy_object_folders:
        out = _filter_legacy_object_folders(out)
    # Добавляем виртуальные "схемные" узлы (Измерения/Ресурсы/...).
    out = _inject_schema_sections(out)
    out = _inject_schema_children(out)
    if subsystem_filter_guid:
        out = _apply_subsystem_filter(out, subsystem_filter_guid)
    if search_text:
        out = _apply_search_keep_ancestors(out, search_text)
    return out


def build_tree_model(
        model: QStandardItemModel,
        objs: Sequence[_NodeProto],
        *,
        mk_item: Callable[[_NodeProto], QStandardItem],
        progress: Optional[ProgressCallback] = None,
        safety_limit: int = 10000,
) -> BuildResult:
    """Построить QStandardItemModel по списку узлов.

    Args:
        model: Модель дерева, которую нужно заполнить.
        objs: Список подготовленных узлов.
        mk_item: Функция, создающая QStandardItem из объекта.
        progress: Необязательный callback `progress(built, total)`.
        safety_limit: Ограничение на число итераций для защиты от циклов.

    Returns:
        BuildResult с итоговыми счётчиками.
    """

    total_input = len(objs)

    # В build_tree_model() приходит уже *подготовленный* список узлов.
    # Поэтому на данном уровне "вход" и "после фильтров" совпадают.
    total_after_filter = len(objs)
    total_input = total_after_filter

    model.clear()
    root_item = model.invisibleRootItem()

    guid_to_item: Dict[str, QStandardItem] = {}
    guid_set = {str(getattr(o, "guid", "") or "") for o in objs}
    children_by_parent: Dict[str, List[_NodeProto]] = {}
    root_nodes: List[_NodeProto] = []

    for o in objs:
        guid = str(getattr(o, "guid", "") or "")
        if not guid:
            continue
        pg = str(getattr(o, "parent_guid", "") or "")
        if pg and pg in guid_set:
            children_by_parent.setdefault(pg, []).append(o)
        else:
            root_nodes.append(o)

    built = 0
    orphans = sum(
        1
        for o in objs
        if str(getattr(o, "parent_guid", "") or "")
        and str(getattr(o, "parent_guid", "") or "") not in guid_set
    )

    def bump() -> None:
        if progress:
            progress(built, max(1, total_after_filter))

    visited: set[str] = set()

    def attach_subtree(node: _NodeProto, parent_it: QStandardItem) -> None:
        nonlocal built
        guid = str(getattr(node, "guid", "") or "")
        if not guid or guid in visited:
            return
        visited.add(guid)
        it = mk_item(node)
        parent_it.appendRow(it)
        guid_to_item[guid] = it
        built += 1
        bump()
        for child in children_by_parent.get(guid, []):
            attach_subtree(child, it)

    for node in root_nodes:
        attach_subtree(node, root_item)

    for node in objs:
        guid = str(getattr(node, "guid", "") or "")
        if guid and guid not in visited:
            attach_subtree(node, root_item)
            orphans += 1

    if progress:
        progress(built, max(1, total_after_filter))

    return BuildResult(
        total_input=total_input,
        total_after_filter=total_after_filter,
        built=built,
        orphans=orphans,
    )
