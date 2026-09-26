from pathlib import Path


def test_legacy_storage_layer_is_removed() -> None:
    assert not Path("src/storage").exists()


def test_source_tree_does_not_import_removed_storage_layer() -> None:
    forbidden = ("src.storage", "storage.filedb", "StorageInterface", "FileDBStorage")
    for path in Path("src").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if path.name == "test_no_legacy_storage_layer.py":
            continue
        text = path.read_text(encoding="utf-8")
        assert not any(token in text for token in forbidden), path.as_posix()
