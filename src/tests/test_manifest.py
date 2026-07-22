from src.configurator.persistence.manifest_io import list_object_rows


def test_list_object_rows_recovers_from_rowid_index_when_full_scan_fails() -> None:
    source = {
        1: {"guid": "root", "type": "configuration", "name": "Configuration", "title": "Config", "kind": "root", "parent_guid": "", "payload": {}},
        2: {"guid": "module", "type": "common_module", "name": "Helper", "title": "Helper", "kind": "object", "parent_guid": "root", "payload": {}},
    }

    class _Table:
        def select(self, where=None, order_by=None):
            if where is None:
                raise RuntimeError("Page id mismatch")
            row = source.get(int((where or {}).get("rowid") or 0))
            return [dict(row)] if row else []

    class _Db:
        _meta = {"tables": {"manifest": {"next_rowid": 3}}}

        def table(self, name: str):
            assert name == "manifest"
            return _Table()

    rows = list_object_rows(_Db())

    assert {row["guid"] for row in rows} == {"root", "module"}
