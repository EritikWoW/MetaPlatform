from __future__ import annotations

from types import SimpleNamespace

from src.infra.onec.parse1cd_compat import patch_parse1cd_database_parser


def test_parse1cd_patch_recovers_files_for_split_83_descriptor() -> None:
    class FakeDatabase:
        def __init__(self):
            self.header = SimpleNamespace(total_pages=8)
            self.tables = {
                "_INFORG11571": SimpleNamespace(
                    name="_INFORG11571",
                    files=["0", "0", "0"],
                    data_object_id=None,
                    blob_object_id=None,
                    index_object_id=None,
                )
            }
            self._table_data_pages = {}

        def _read_page(self, page_num: int) -> bytes:
            if page_num == 2:
                return (
                    b'\x00\x00{"_INFORG11571",0,{"Fields",{"_FLD1","N",0,10,0,"CS"}},'
                    b'{"Indexes",{"_IDX",0,{"_FLD1",0}}},{"Recordlock","0"},{"Files",5,0,7}}'
                )
            if page_num == 5:
                return b"\x1c\xfd" + b"\x00" * 100
            return b""

        def _collect_data_pages_83_from_header(self, _page: bytes):
            return [6]

    database_parser = SimpleNamespace(OneCDatabase=FakeDatabase, PAGE_SIG_83=b"\x1c\xfd")

    patch_parse1cd_database_parser(database_parser)

    db = FakeDatabase()
    db._link_data_83()

    table = db.tables["_INFORG11571"]
    assert table.data_object_id == 5
    assert table.blob_object_id is None
    assert table.index_object_id == 7
    assert db._table_data_pages["_INFORG11571"] == [6]
