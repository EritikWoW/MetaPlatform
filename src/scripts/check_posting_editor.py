"""Read-only Runtime check and offscreen render of a document's movements page.

Never saves metadata, module text, or business data. The only output is a PNG.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", default="http://127.0.0.1:8875")
    parser.add_argument("--db-uid", required=True)
    parser.add_argument("--document-guid", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--language", choices=("uk", "en"), default="uk")
    args = parser.parse_args()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication
    from src.configurator.application.service import ConfiguratorService
    from src.configurator.domain.posting_constructor import find_posting_handler, generate_posting_handler
    from src.configurator.domain.technical_names import technical_object_name
    from src.runtime.gateway import RuntimeGateway
    from src.ui_qt.services.posting_module_editor import resolve_document_object_module
    from src.ui_qt.theme import apply_dark_theme
    from src.ui_qt.widgets.document_editor import DocumentEditorWidget
    import src.ui_qt.i18n as i18n

    # Process-local locale for the render; do not write the user's settings.
    i18n._lang = args.language

    gateway = RuntimeGateway(args.runtime)
    try:
        gateway.open_by_uid(args.db_uid)
        rows = gateway.manifest_list(slim=True)
        by_guid = {row["guid"]: row for row in rows}
        document = by_guid[args.document_guid]
        payload = gateway.manifest_get_payload(args.document_guid)
        objects = [SimpleNamespace(**row) for row in rows]
        subsystems = [
            {**row, "name": technical_object_name(row.get("name"), payload=row.get("payload"))}
            for row in rows if row.get("type") == "subsystem" and row.get("kind") == "object"
        ]
        service = ConfiguratorService()
        service._gw = gateway
        vm = SimpleNamespace(
            _service=service, list_objects=lambda: objects,
            list_subsystems=lambda: subsystems,
            get_meta_by_guid=lambda guid: by_guid.get(guid),
        )
        target = resolve_document_object_module(vm, args.document_guid)
        text = gateway.module_get_text(target.module_guid)
        report = {"snapshot_objects": len(rows), "module_guid": target.module_guid,
                  "source_chars": len(text)}
        try:
            report["existing_handler_line"] = find_posting_handler(text)
        except ValueError as exc:
            report["insertion_blocked"] = str(exc)

        app = QApplication.instance() or QApplication([])
        apply_dark_theme(app)
        widget = DocumentEditorWidget(
            technical_object_name(document.get("name"), payload=payload),
            payload=payload, vm=vm, obj_guid=args.document_guid, available_subsystems=subsystems,
        )
        widget.resize(1400, 1000)
        widget._shell.set_current_section("movements")
        widget.show()
        app.processEvents()
        selected = widget._checked_register_records()
        report["stored_registers"] = len(payload.get("register_records", []))
        report["selected_registers"] = len(selected)
        report["unique_selection"] = len(set(selected)) == len(selected)
        report["selection_preserved"] = set(selected) == set(payload.get("register_records", []))
        report["visible_movements"] = widget.table_movements.rowCount()
        code = generate_posting_handler(selected, language=args.language)
        report["constructor_chars"] = len(code)
        widget._payload_raw["posting_handler_registers"] = selected
        widget.ed_posting_handler.setPlainText(code)
        app.processEvents()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if not widget.grab().save(str(args.output)):
            raise RuntimeError("Unable to write screenshot")
        report["screenshot"] = str(args.output.resolve())
        print(json.dumps(report, ensure_ascii=False, indent=2))
        widget.deleteLater()
        app.processEvents()
    finally:
        gateway.close_session()


if __name__ == "__main__":
    main()
