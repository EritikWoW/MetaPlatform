from src.configurator.persistence.manifest_io import ensure_manifest
from src.infra.onec.importer import import_manifest_objects
from src.mpdb.mpdb import Mpdb


class _DictSource:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    def list_files(self) -> list[str]:
        return sorted(self.files)

    def read_bytes(self, rel_path: str) -> bytes:
        return self.files[rel_path]


def test_import_manifest_objects_reports_staged_progress() -> None:
    db = Mpdb(":memory:")
    ensure_manifest(db, seed_defaults=True)
    source = _DictSource(
        {
            "Catalogs/Products.xml": b"<Meta><Name>Products</Name><Synonym>Products</Synonym></Meta>",
            "Catalogs/Products/Forms/ItemForm.xml": b"<Meta><Name>ItemForm</Name><Synonym>Item form</Synonym></Meta>",
            "Catalogs/Products/Forms/ItemForm/Ext/Module.bsl": b"Procedure TestForm() EndProcedure",
            "Catalogs/Products/Templates/PriceLayout.xml": b"<Meta><Name>PriceLayout</Name><Synonym>Price layout</Synonym></Meta>",
            "Catalogs/Products/Ext/ObjectModule.bsl": b"Procedure TestObject() EndProcedure",
        }
    )
    progress_events: list[tuple[int, int, str]] = []

    import_manifest_objects(
        db,
        source,
        source.list_files(),
        store_modules_in_table=True,
        progress=lambda current, total, message: progress_events.append((current, total, message)),
    )

    messages = [message for _current, _total, message in progress_events]
    assert messages == [
        "Import manifest: Catalogs/Products -> Object",
        "Import manifest: Catalogs/Products -> Forms",
        "Import manifest: Catalogs/Products -> Form modules",
        "Import manifest: Catalogs/Products -> Templates",
        "Import manifest: Catalogs/Products -> Object modules",
    ]


def test_import_manifest_objects_queues_forms_before_object_modules(tmp_path, monkeypatch) -> None:
    db = Mpdb(str(tmp_path / "import_stage_order.mpdb"))
    ensure_manifest(db, seed_defaults=True)
    source = _DictSource(
        {
            "Catalogs/Products.xml": b"<Meta><Name>Products</Name><Synonym>Products</Synonym></Meta>",
            "Catalogs/Products/Forms/ItemForm.xml": b"<Meta><Name>ItemForm</Name><Synonym>Item form</Synonym></Meta>",
            "Catalogs/Products/Forms/ItemForm/Ext/Module.bsl": b"Procedure TestForm() EndProcedure",
            "Catalogs/Products/Ext/ObjectModule.bsl": b"Procedure TestObject() EndProcedure",
        }
    )
    captured_order: list[tuple[str, str, str, str]] = []

    from src.configurator.persistence import manifest_io as manifest_io_module

    original_add_objects_bulk = manifest_io_module.add_objects_bulk

    def _capture_add_objects_bulk(db_obj, objects, **kwargs):
        captured_order.extend(
            (str(obj.type), str(obj.kind), str(obj.name), str(obj.title))
            for obj in objects
        )
        return original_add_objects_bulk(db_obj, objects, **kwargs)

    monkeypatch.setattr(manifest_io_module, "add_objects_bulk", _capture_add_objects_bulk)

    import_manifest_objects(
        db,
        source,
        source.list_files(),
        store_modules_in_table=True,
    )

    form_index = next(
        index
        for index, item in enumerate(captured_order)
        if item[0] == "form" and item[1] == "object" and item[2] == "ItemForm"
    )
    object_module_index = next(
        index
        for index, item in enumerate(captured_order)
        if item[0] == "module" and item[1] == "object" and item[3] == "ObjectModule"
    )

    assert form_index < object_module_index
