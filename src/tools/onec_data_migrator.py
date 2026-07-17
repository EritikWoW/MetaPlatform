from __future__ import annotations

import sys
import os
# Добавляем корень проекта в пути поиска модулей
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.infra.onec.importer import DirectorySource, ZipSource
from src.infra.onec.onecd_source import OneCDConfigSource
from src.infra.onec.onec_requisites_parser import OneCXmlParser
from src.infra.onec.onec_requisites_model import ( # Исправлено: импортируем правильные классы
    OneCMetaObject,
    OneCRequisite,
    OneCTabularPart,
)
from src.infra.onec.source_compat import resolve_onec_source


def _format_type(req_type: Dict[str, Any]) -> str:
    """
    Форматирует тип реквизита для вывода в читаемом виде.
    """
    types = req_type.get("types", [])
    if not types:
        return "UNKNOWN"
    
    formatted_types = []
    for t in types:
        if t == "string":
            length = req_type.get("length", 0)
            return f"String({length})"
        elif t == "number":
            length = req_type.get("length", 0)
            precision = req_type.get("precision", 0)
            return f"Number({length}, {precision})"
        elif t == "date":
            return "Date"
        elif t == "boolean":
            return "Boolean"
        elif t == "uuid":
            return "UUID"
        elif t == "reference":
            ref_type = req_type.get("ref_type", "Any")
            return f"Reference({ref_type})"
        else:
            formatted_types.append(t)
    
    if formatted_types:
        return "|".join(formatted_types)
    return "UNKNOWN"


def _map_onec_type_to_mp(req_type: Dict[str, Any]) -> Dict[str, Any]:
    """
    Преобразует тип 1С в тип MetaPlatform для Манифеста.
    """
    types = req_type.get("types", [])
    if not types:
        return {"type": "string", "length": 255}

    primary_type = types[0]
    
    if primary_type == "string" or primary_type == "enum":
        # Перечисления в манифесте часто представляются как строки или UUID
        return {"type": "string", "length": req_type.get("length", 255)}
    elif primary_type == "number":
        return {
            "type": "decimal", 
            "precision": req_type.get("length", 15) if req_type.get("length") else 15, 
            "scale": req_type.get("precision", 0) if req_type.get("precision") else 0
        }
    elif primary_type == "date":
        return {"type": "datetime"}
    elif primary_type == "boolean":
        return {"type": "boolean"}
    elif primary_type in ["reference", "chart_of_accounts", "chart_of_characteristic_types"]:
        # Ссылочные типы 1С -> UUID в MetaPlatform
        return {
            "type": "uuid", 
            "is_reference": True, 
            "reference_to": req_type.get("ref_type", "Any")
        }
    elif primary_type in ["uuid", "value_storage"]:
        # Хранилище значений пока мапим в uuid или blob (в зависимости от реализации mpdb)
        return {"type": "uuid"}
        
    return {"type": "string", "length": 255}


def get_onec_metadata(
    source_path: str, 
    source_kind: str, 
    filter_relevant: bool = True
) -> List[OneCMetaObject]:
    """
    Извлекает список объектов метаданных из источника 1С.
    """
    relevant_types = {
        "catalog", "document", "information_register", "accumulation_register",
        "accounting_register", "calculation_register", "constant", "enum", 
        "chart_of_characteristic_types", "chart_of_accounts", "chart_of_calculation_types"
    }
    
    resolved = resolve_onec_source(source_path, source_kind)
    effective_path = str(resolved.semantic_path or source_path)
    effective_kind = str(resolved.semantic_kind or source_kind or "xml")

    print(f"Используется путь: {effective_path}, формат: {effective_kind}")

    source = None
    try:
        if effective_kind.lower() in ["zip", "dt"]:
            source = ZipSource(effective_path)
        elif effective_kind.lower() == "1cd" or effective_path.endswith(".1CD"):
            source = OneCDConfigSource(effective_path)
        else:
            root_dir = effective_path
            if Path(root_dir).is_file():
                root_dir = str(Path(root_dir).parent)
            source = DirectorySource(root_dir)
        
        if source:
            with source:
                onec_parser = OneCXmlParser()
                parsed_objects = onec_parser.parse_all(source)
                
                if not filter_relevant:
                    return parsed_objects

                # Фильтруем и сортируем
                relevant = [obj for obj in parsed_objects if obj.obj_type in relevant_types]
                priority = list(relevant_types)
                relevant.sort(key=lambda o: (
                    priority.index(o.obj_type) if o.obj_type in relevant_types else 99,
                    o.name or ""
                ))
                return relevant
    except Exception as e:
        print(f"Ошибка при чтении источника {source_path}: {e}")
        raise
    finally:
        if source and hasattr(source, 'close'):
            source.close()
    return []


def export_raw_metadata(source_path: str, source_kind: str, output_file: str) -> None:
    """
    Вытягивает абсолютно все доступные метаданные и сохраняет их в JSON.
    Это "сырой" слепок базы 1С.
    """
    print(f"Выполнение полного дампа метаданных из {source_path}...")
    all_meta = get_onec_metadata(source_path, source_kind, filter_relevant=False)
    
    dump_data = []
    for obj in all_meta:
        obj_dump = {
            "name": obj.name,
            "type": obj.obj_type,
            "uuid": obj.uuid,
            "synonyms": obj.synonyms,
            "requisites": [
                {
                    "name": r.name,
                    "type": r.raw_type,
                    "nullable": r.nullable
                } for r in obj.requisites
            ],
            "tabular_parts": [
                {
                    "name": tp.name,
                    "requisites": [{"name": r.name, "type": r.raw_type} for r in tp.requisites]
                } for tp in obj.tabular_parts
            ]
        }
        dump_data.append(obj_dump)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(dump_data, f, ensure_ascii=False, indent=2)
    print(f"Дамп завершен. Сохранено объектов: {len(dump_data)} в файл {output_file}")


def migrate_metadata_to_platform(objects: List[OneCMetaObject]) -> None:
    """
    Трансформирует метаданные 1С в структуру MetaPlatform.
    """
    print(f"Начало миграции {len(objects)} объектов в MetaPlatform...")
    
    manifest_entities = {}

    for obj in objects:
        entity_name = obj.name
        entity_data = {
            "type": obj.obj_type,
            "uuid": obj.uuid,
            "label": obj.synonyms.get('uk') or obj.synonyms.get('en') or obj.name,
            "fields": {},
            "collections": {}
        }

        # Добавляем реквизиты как поля
        for req in obj.requisites:
            entity_data["fields"][req.name] = {
                "meta": _map_onec_type_to_mp(req.raw_type),
                "nullable": req.nullable
            }

        # Добавляем табличные части как коллекции
        for tp in obj.tabular_parts:
            tp_fields = {}
            for tp_req in tp.requisites:
                tp_fields[tp_req.name] = {
                    "meta": _map_onec_type_to_mp(tp_req.raw_type),
                    "nullable": tp_req.nullable
                }
            entity_data["collections"][tp.name] = {"fields": tp_fields}

        manifest_entities[entity_name] = entity_data
        print(f"  - Подготовлена структура объекта: {entity_name}")

    # В будущем здесь будет вызов Runtime RPC для сохранения манифеста в mpdb
    # save_manifest_to_mpdb(manifest_entities)
    
    print(f"\nСформирован манифест для {len(manifest_entities)} сущностей.")
    print("Миграция структуры завершена. Следующий шаг: инициализация таблиц и перенос данных.")
    return manifest_entities


def analyze_onec_metadata(source_path: str, source_kind: str) -> None:
    """
    Анализирует метаданные 1С и выводит их логическую схему в консоль.
    """
    print(f"Анализ метаданных 1С из источника: {source_path} (тип: {source_kind})\n")

    try:
        relevant_objects = get_onec_metadata(source_path, source_kind)

        if not relevant_objects:
            print("Не найдено релевантных бизнес-объектов.")
            return

        print(f"Обнаружено {len(relevant_objects)} объектов для анализа.\n")
        print("--- Логическая схема бизнес-объектов 1С ---\n")
        
        for obj in relevant_objects:
            print(f"Объект: {obj.name} (Тип: {obj.obj_type}, UUID: {obj.uuid})")
            print(f"  Заголовок: {obj.synonyms.get('uk') or obj.synonyms.get('en') or obj.name}")
            
            if obj.requisites:
                print("  Реквизиты:")
                for req in obj.requisites:
                    type_str = _format_type(req.raw_type)
                    print(f"    - {req.name}: {type_str} (Nullable: {req.nullable})")
            
            if obj.tabular_parts:
                print("  Табличные части:")
                for tp in obj.tabular_parts:
                    print(f"    - {tp.name}:")
                    for req in tp.requisites:
                        type_str = _format_type(req.raw_type)
                        print(f"      - {req.name}: {type_str} (Nullable: {req.nullable})")
            print("-" * 40 + "\n")
            
    except Exception as e:
        print(f"Произошла ошибка при анализе метаданных: {e}")


def _discover_tables(source: Any) -> List[Any]:
    """
    Helper to find the table list within different OneCD source implementations.
    """
    method_names = {"get_tables", "metadata_objects", "list_files", "get_files"}
    attr_names = {"tables", "_tables", "_objects", "metadata_objects"}

    def _materialize(value: Any) -> List[Any]:
        if value is None:
            return []
        if isinstance(value, dict):
            return list(value.values())
        if isinstance(value, (list, tuple)):
            return list(value)
        if isinstance(value, str):
            return [value]
        try:
            if value.__class__.__module__.startswith("unittest.mock"):
                return []
        except Exception:
            pass
        try:
            return list(value)
        except TypeError:
            return []

    # 1. Check direct attributes and methods. Added 'list_files' for raw 1CD access.
    for attr_name in ['get_tables', 'tables', '_tables', 'metadata_objects', '_objects', 'list_files', 'get_files']:
        attr = getattr(source, attr_name, None)
        if attr is None:
            continue

        if callable(attr) and attr_name in method_names:
            rows = _materialize(attr())
        elif attr_name in attr_names:
            rows = _materialize(attr)
        else:
            rows = []
        if rows:
            return rows

    # 2. Check nested objects (proxies/wrappers)
    for db_attr in ['db', '_db', 'database', 'base', 'metadata_catalog']:
        db_obj = getattr(source, db_attr, None)
        if not db_obj:
            continue
        
        for t_name in ['tables', 'objects', 'metadata_objects']:
            t_attr = getattr(db_obj, t_name, None)
            rows = _materialize(t_attr)
            if rows:
                return rows
    return []


def inspect_onec_database(source_path: str, source_kind: str, table_to_view: Optional[str] = None, limit: int = 20) -> None:
    """
    Позволяет просматривать физические таблицы и данные внутри .1CD файла.
    """
    print(f"Инспекция базы данных: {source_path}\n")
    
    # Для инспекции данных нам нужен именно бинарный файл .1CD.
    # Игнорируем resolve_onec_source, если у нас уже есть файл БД.
    db_path = source_path
    if not db_path.lower().endswith(".1cd"):
        resolved = resolve_onec_source(source_path, source_kind)
        if resolved.semantic_kind == "1cd" and resolved.semantic_path:
            db_path = str(resolved.semantic_path)
        else:
            print("Ошибка: Просмотр данных возможен только для файлов формата .1CD")
            return

    source = OneCDConfigSource(db_path)
    try:
        with source:
            # Пытаемся получить список таблиц разными способами
            tables = _discover_tables(source)
            
            if not table_to_view:
                print(f"{'№':<4} | {'Физическое имя':<35} | {'Записей':<10}")
                print("-" * 55)
                for i, table in enumerate(tables, 1):
                    name = getattr(table, 'name', None) or getattr(table, '_name', None) or (table if isinstance(table, str) else 'Unknown')
                    
                    # Пытаемся получить количество записей более надежными способами
                    count = 0
                    if hasattr(table, 'row_count'):
                        count = table.row_count
                    elif hasattr(table, '__len__'):
                        try:
                            count = len(table)
                        except:
                            count = 0
                    
                    # Если все еще 0, пробуем проверить наличие строк в объекте rows
                    if not count and hasattr(table, 'rows'):
                         try:
                             count = len(table.rows)
                         except:
                             count = '?'
                    print(f"{i:<4} | {name:<35} | {count:<10}")
                
                if not tables:
                    print("\n[!] Таблицы не найдены.")
                    print(f"Доступные атрибуты источника: {[a for a in dir(source) if not a.startswith('__')]}")
                    if hasattr(source, 'metadata_catalog'):
                        mc = source.metadata_catalog
                        print(f"Атрибуты metadata_catalog: {[a for a in dir(mc) if not a.startswith('__')]}")
                    return

                print(f"\nВсего таблиц: {len(tables)}")
                print("Используйте --view-table <имя>, чтобы посмотреть содержимое.")
            else:
                # Ищем нужную таблицу
                target = None
                for t in tables:
                    # Пытаемся получить имя таблицы из разных свойств
                    names_to_check = [
                        getattr(t, 'name', None),
                        getattr(t, '_name', None),
                        getattr(t, 'filename', None), # Для системных файлов в 1CD
                        t if isinstance(t, str) else None
                    ]
                    
                    if any(str(n).lower() == table_to_view.lower() for n in names_to_check if n):
                        target = t
                        break
                
                if not target:
                    print(f"Таблица/Объект '{table_to_view}' не найден. Проверьте список через --list-tables")
                    return

                print(f"Просмотр данных таблицы: {table_to_view} (первые {limit} строк)\n")
                
                # Получаем колонки
                fields = []
                if hasattr(target, 'get_fields'):
                    fields = target.get_fields()
                elif hasattr(target, 'fields'):
                    fields = target.fields
                
                field_names = [getattr(f, 'name', str(f)) for f in fields]
                header = " | ".join(field_names)
                print(header)
                print("-" * len(header))

                # Читаем записи
                rows_count = 0
                # Пытаемся получить записи через разные методы
                records = []
                if hasattr(target, 'get_records'):
                    records = target.get_records()
                elif hasattr(target, 'rows'):
                    records = target.rows
                elif hasattr(target, 'select'):
                    records = target.select()

                for row in records:
                    if rows_count >= limit:
                        break
                    
                    # row может быть как словарем, так и объектом
                    values = [str(row[name] if isinstance(row, dict) else getattr(row, name, '')) for name in field_names]
                    print(" | ".join(values))
                    rows_count += 1

    except Exception as e:
        print(f"Ошибка при доступе к данным 1CD: {e}")
    finally:
        if hasattr(source, 'close'):
            source.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Анализ метаданных 1С для определения структуры бизнес-объектов.")
    parser.add_argument("--src", required=True, help="Путь к источнику 1С (XMLConf, ConfigFiles.zip, 1Cv8.1CD)")
    parser.add_argument("--kind", choices=["auto", "zip", "xml", "1cd"], default="auto",
                        help="Тип источника 1С. 'auto' попытается определить автоматически.")
    parser.add_argument("--migrate", action="store_true", help="Запустить процесс миграции в MetaPlatform")
    parser.add_argument("--dump", help="Путь к JSON файлу для полного дампа всех метаданных")
    parser.add_argument("--db", help="Путь к mpdb для импорта физических данных .1CD")
    parser.add_argument("--import-data", action="store_true", help="Импортировать физические таблицы .1CD в mpdb")
    parser.add_argument("--table", action="append", help="Физическая таблица .1CD для импорта; можно указать несколько раз")
    parser.add_argument("--include-service", action="store_true", help="Включать служебные таблицы .1CD")
    parser.add_argument("--include-deleted", action="store_true", help="Включать помеченные удаленными строки")
    parser.add_argument("--no-ref-index", action="store_true", help="Не строить индекс ссылок _IDRRef")
    parser.add_argument("--read-blobs", action="store_true", help="Читать полные BLOB-значения вместо preview")
    parser.add_argument("--target-prefix", default="onec", help="Префикс таблиц назначения в mpdb")
    parser.add_argument("--batch-size", type=int, default=500, help="Размер batch insert для mpdb")
    parser.add_argument("--storage-mode", choices=["packed", "per_table"], default="packed", help="Схема хранения строк в mpdb")
    
    # Новые аргументы для инспекции данных
    parser.add_argument("--list-tables", action="store_true", help="Показать список всех физических таблиц в .1CD")
    parser.add_argument("--view-table", help="Показать содержимое конкретной таблицы")
    parser.add_argument("--limit", type=int, default=20, help="Лимит строк для просмотра (по умолчанию 20)")
    
    args = parser.parse_args()

    if args.import_data:
        if not args.db:
            parser.error("--db is required with --import-data")
        from src.infra.onec.data_migration import migrate_onecd_data_to_mpdb
        from src.mpdb.mpdb import Mpdb

        target_db = Mpdb(args.db)
        try:
            result = migrate_onecd_data_to_mpdb(
                target_db,
                args.src,
                table_names=args.table,
                limit_per_table=args.limit if args.limit and args.limit > 0 else None,
                include_service=bool(args.include_service),
                include_deleted=bool(args.include_deleted),
                build_refs=not bool(args.no_ref_index),
                read_blobs=bool(args.read_blobs),
                target_prefix=str(args.target_prefix or "onec"),
                batch_size=max(1, int(args.batch_size or 1)),
                storage_mode=str(args.storage_mode or "packed"),
            )
            print(json.dumps(result.get("summary") or {}, ensure_ascii=False, indent=2))
            print(f"Манифест миграции сохранен в asset: {result.get('asset_key')}")
        finally:
            target_db.close()
    elif args.list_tables:
        inspect_onec_database(args.src, args.kind)
    elif args.view_table:
        inspect_onec_database(args.src, args.kind, table_to_view=args.view_table, limit=args.limit)
    elif args.dump:
        export_raw_metadata(args.src, args.kind, args.dump)
    elif args.migrate:
        meta = get_onec_metadata(args.src, args.kind)
        migrate_metadata_to_platform(meta)
    else:
        analyze_onec_metadata(args.src, args.kind)
