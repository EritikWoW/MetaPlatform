from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.configurator.manifest_schema import ManifestObject
import src.infra.onec.source_structure_compare as source_structure_compare
from src.infra.onec.source_structure_compare import build_source_structure_compare_report


def test_source_structure_compare_reports_subsystem_content_and_child_subsystems(tmp_path: Path) -> None:
    xml_root = tmp_path / "XMLConf"
    (xml_root / "Subsystems").mkdir(parents=True)
    (xml_root / "Subsystems" / "Administration.xml").write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<MetaDataObject xmlns='http://v8.1c.ru/8.3/MDClasses' xmlns:v8='http://v8.1c.ru/8.1/data/core' xmlns:xr='http://v8.1c.ru/8.3/xcf/readable' xmlns:xsi='http://www.w3.org/2001/XMLSchema-instance'>
  <Subsystem uuid='sub-1'>
    <Properties>
      <Name>Administration</Name>
      <Synonym>
        <v8:item><v8:lang>uk</v8:lang><v8:content>Адміністрування</v8:content></v8:item>
      </Synonym>
      <Content>
        <xr:Item xsi:type='xr:MDObjectRef'>Catalog.Products</xr:Item>
      </Content>
    </Properties>
    <ChildObjects>
      <Subsystem>NestedSubsystem</Subsystem>
    </ChildObjects>
  </Subsystem>
</MetaDataObject>
""",
        encoding="utf-8",
    )

    source_objects = [
        ManifestObject(
            guid="sub-1",
            type="subsystem",
            name="Administration",
            title="Адміністрування",
            kind="object",
            parent_guid="",
            payload={},
        ),
        ManifestObject(
            guid="cat-1",
            type="catalog",
            name="Products",
            title="Товари",
            kind="object",
            parent_guid="",
            payload={"metadata_ref": "Catalog.Products"},
        ),
    ]

    class _Vm:
        def list_objects(self):
            return list(source_objects)

        def manifest_get_payload(self, guid: str) -> dict[str, object]:
            if guid == "sub-1":
                return {"content_refs": [], "objects": []}
            if guid == "cat-1":
                return {"metadata_ref": "Catalog.Products"}
            return {}

    report = build_source_structure_compare_report(
        source_path=str(xml_root),
        source_kind="xml",
        db_objects=source_objects,
        db_payload_getter=_Vm().manifest_get_payload,
    )

    assert report["summary"]["source_count"] == 1
    assert report["summary"]["db_count"] == 2
    assert report["items"][0]["status"] == "mismatch"
    assert report["items"][0]["diffs"]["content_refs"]["source"] == ["Catalog.Products"]
    assert report["items"][0]["diffs"]["child_subsystems"]["source"] == ["NestedSubsystem"]
    assert report["items"][0]["diffs"]["objects"]["source"] == ["cat-1"]
    assert report["summary"]["missing_parent_links_source"] == 0
    assert report["summary"]["missing_parent_links_db"] == 0
    assert report["summary"]["coverage_ratio_real"] == 0.0


def test_source_structure_compare_reports_missing_parent_links(tmp_path: Path) -> None:
    xml_root = tmp_path / "XMLConf"
    (xml_root / "Subsystems").mkdir(parents=True)
    (xml_root / "Subsystems" / "Broken.xml").write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<MetaDataObject xmlns='http://v8.1c.ru/8.3/MDClasses' xmlns:v8='http://v8.1c.ru/8.1/data/core' xmlns:xr='http://v8.1c.ru/8.3/xcf/readable' xmlns:xsi='http://www.w3.org/2001/XMLSchema-instance'>
  <Subsystem uuid='sub-2'>
    <Properties>
      <Name>Broken</Name>
      <Synonym>
        <v8:item><v8:lang>uk</v8:lang><v8:content>Broken</v8:content></v8:item>
      </Synonym>
    </Properties>
  </Subsystem>
</MetaDataObject>
""",
        encoding="utf-8",
    )

    source_objects = [
        ManifestObject(
            guid="sub-2",
            type="subsystem",
            name="Broken",
            title="Broken",
            kind="object",
            parent_guid="missing-parent",
            payload={},
        )
    ]

    report = build_source_structure_compare_report(
        source_path=str(xml_root),
        source_kind="xml",
        db_objects=source_objects,
        db_payload_getter=lambda guid: {},
    )

    assert report["summary"]["db_missing_parent_links"] == 1


def test_source_structure_compare_reports_parent_child_mismatches(monkeypatch, tmp_path: Path) -> None:
    class _SourceObj:
        def __init__(self, **kwargs) -> None:
            self.__dict__.update(kwargs)

        def to_mp_payload(self) -> dict[str, object]:
            return dict(self.payload)

    source_objects = [
        _SourceObj(
            uuid="sub-root",
            obj_type="Subsystem",
            family="subsystem",
            type="subsystem",
            name="Root",
            title="Root",
            origin_path="XMLConf/Subsystems/Root.xml",
            order=1,
            parent_guid="",
            tree_path="Root",
            is_virtual=False,
            virtual_reason="",
            payload={"child_subsystems": ["ChildA", "ChildB"], "content_refs": []},
        ),
        _SourceObj(
            uuid="sub-a",
            obj_type="Subsystem",
            family="subsystem",
            type="subsystem",
            name="ChildA",
            title="Child A",
            origin_path="XMLConf/Subsystems/Root/Subsystems/ChildA.xml",
            order=10,
            parent_guid="sub-root",
            tree_path="Root/ChildA",
            is_virtual=False,
            virtual_reason="",
            payload={},
        ),
        _SourceObj(
            uuid="sub-b",
            obj_type="Subsystem",
            family="subsystem",
            type="subsystem",
            name="ChildB",
            title="Child B",
            origin_path="XMLConf/Subsystems/Root/Subsystems/ChildB.xml",
            order=20,
            parent_guid="sub-root",
            tree_path="Root/ChildB",
            is_virtual=False,
            virtual_reason="",
            payload={},
        ),
    ]

    db_objects = [
        ManifestObject(
            guid="sub-root",
            type="subsystem",
            name="Root",
            title="Root",
            kind="object",
            parent_guid="",
            payload={"objects": []},
        ),
        ManifestObject(
            guid="sub-a",
            type="subsystem",
            name="ChildA",
            title="Child A",
            kind="object",
            parent_guid="sub-root",
            payload={"order": 10},
        ),
    ]

    monkeypatch.setattr(
        source_structure_compare,
        "_load_source_objects",
        lambda source_path, source_kind: (
            {
                "resolved": SimpleNamespace(requested_kind="xml", detected_kind="xml", semantic_kind="xml"),
                "effective_path": source_path,
            },
            source_objects,
        ),
    )

    report = build_source_structure_compare_report(
        source_path=str(tmp_path / "XMLConf"),
        source_kind="xml",
        db_objects=db_objects,
        db_payload_getter=lambda guid: {"order": 10} if guid == "sub-a" else {},
    )

    assert report["summary"]["parent_child_mismatch_count"] == 1
    mismatch = report["parent_child_mismatches"][0]
    assert mismatch["parent_guid"] == "sub-root"
    assert mismatch["source_count"] == 2
    assert mismatch["db_count"] == 1
    assert mismatch["missing_in_db"] == ["sub-b"]


def test_source_structure_compare_reports_flattened_subtrees(monkeypatch, tmp_path: Path) -> None:
    class _SourceObj:
        def __init__(self, **kwargs) -> None:
            self.__dict__.update(kwargs)

        def to_mp_payload(self) -> dict[str, object]:
            return dict(self.payload)

    source_objects = [
        _SourceObj(
            uuid="sub-root",
            obj_type="Subsystem",
            family="subsystem",
            type="subsystem",
            name="Root",
            title="Root",
            origin_path="XMLConf/Subsystems/Root.xml",
            order=1,
            parent_guid="",
            tree_path="Root",
            is_virtual=False,
            virtual_reason="",
            payload={"child_subsystems": ["Child"], "content_refs": []},
        ),
        _SourceObj(
            uuid="sub-child",
            obj_type="Subsystem",
            family="subsystem",
            type="subsystem",
            name="Child",
            title="Child",
            origin_path="XMLConf/Subsystems/Root/Subsystems/Child.xml",
            order=10,
            parent_guid="sub-root",
            tree_path="Root/Child",
            is_virtual=False,
            virtual_reason="",
            payload={},
        ),
    ]

    db_objects = [
        ManifestObject(
            guid="sub-child",
            type="subsystem",
            name="Child",
            title="Child",
            kind="object",
            parent_guid="",
            payload={"order": 10},
        )
    ]

    monkeypatch.setattr(
        source_structure_compare,
        "_load_source_objects",
        lambda source_path, source_kind: (
            {
                "resolved": SimpleNamespace(requested_kind="xml", detected_kind="xml", semantic_kind="xml"),
                "effective_path": source_path,
            },
            source_objects,
        ),
    )

    report = build_source_structure_compare_report(
        source_path=str(tmp_path / "XMLConf"),
        source_kind="xml",
        db_objects=db_objects,
        db_payload_getter=lambda guid: {"order": 10} if guid == "sub-child" else {},
    )

    assert report["summary"]["flattened_subtree_count"] == 1
    subtree = report["flattened_subtrees"][0]
    assert subtree["parent_guid"] == "sub-root"
    assert subtree["source_child_count"] == 1
    assert subtree["relocated_child_count"] == 1
    assert subtree["relocated_children"][0]["guid"] == "sub-child"
