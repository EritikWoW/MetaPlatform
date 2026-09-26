from PySide6.QtWidgets import QApplication

from src.ui_qt.widgets.access_restrictions_widget import (
    AccessRestrictionsProjectionWidget,
    build_access_restrictions_projection,
)


class _Obj:
    def __init__(self, *, guid: str, name: str, title: str, obj_type: str, kind: str = "object") -> None:
        self.guid = guid
        self.name = name
        self.title = title
        self.type = obj_type
        self.kind = kind


class _VmStub:
    def list_objects(self):
        return [
            _Obj(guid="role-guid", name="Admin", title="Адміністратор", obj_type="role"),
            _Obj(guid="catalog-guid", name="Products", title="Products", obj_type="catalog"),
        ]

    def get_meta_by_guid(self, guid: str):
        if guid != "role-guid":
            return None
        return {
            "guid": guid,
            "title": "Адміністратор",
            "payload": {
                "rights": [
                    {
                        "object": "Catalog.Products",
                        "rights": {"Read": True},
                        "restrictions": [
                            {"right": "Read", "field": "Code", "condition": "ГДЕ Истина"}
                        ],
                    }
                ],
                "restriction_templates": [
                    {"name": "ByValue", "condition": "ГДЕ Т.Склад = &Склад"}
                ],
            },
        }


def test_build_access_restrictions_projection_collects_roles() -> None:
    restrictions, templates = build_access_restrictions_projection(_VmStub())

    assert restrictions == [
        {
            "role_guid": "role-guid",
            "role_name": "Адміністратор",
            "role_code": "Admin",
            "object_ref": "Catalog.Products",
            "right_name": "Read",
            "field_name": "Code",
            "condition": "ГДЕ Истина",
        }
    ]
    assert templates == [
        {
            "role_guid": "role-guid",
            "role_name": "Адміністратор",
            "role_code": "Admin",
            "template_name": "ByValue",
            "condition": "ГДЕ Т.Склад = &Склад",
        }
    ]


def test_access_restrictions_widget_opens_role_for_selected_row() -> None:
    app = QApplication.instance() or QApplication([])
    emitted: list[tuple[str, str]] = []

    widget = AccessRestrictionsProjectionWidget(vm=_VmStub(), title="All Access Restrictions")
    widget.openRoleRequested.connect(lambda guid, title: emitted.append((guid, title)))
    app.processEvents()

    assert widget._restrictions_table.rowCount() == 1
    assert widget._templates_table.rowCount() == 1

    widget._restrictions_table.selectRow(0)
    widget._open_selected_role()
    app.processEvents()

    assert emitted == [("role-guid", "Адміністратор")]
