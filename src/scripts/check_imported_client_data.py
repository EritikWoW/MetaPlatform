"""Exercise Runtime RPC and the real form renderer on an explicit diagnostic DB copy.

The copy must be inside .artifacts; live/source databases are never opened.
No form module is executed and no business records are written.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import threading
import time
from http.server import ThreadingHTTPServer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-copy", type=Path, required=True)
    parser.add_argument("--document-guid", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2] / ".artifacts"
    if not args.db_copy.resolve().is_relative_to(root.resolve()) or not args.db_copy.is_file():
        parser.error("--db-copy must be an existing file inside the workspace .artifacts directory")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase, QFont
    from PySide6.QtCore import Qt
    from src.runtime.server import RuntimeHandler, STATE_DBS
    from src.runtime.gateway import RuntimeGateway, GatewayDb
    from src.client.client_window_runtime import ClientWindowRuntimeMixin
    from src.client.forms.form_runtime_widget import FormRuntimeWidget, ObjContext
    import src.ui_qt.i18n as i18n

    i18n._lang = "uk"
    server = ThreadingHTTPServer(("127.0.0.1", 0), RuntimeHandler)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True)
    worker.start()
    gateway = RuntimeGateway(f"http://127.0.0.1:{server.server_port}")
    report = {"database": str(args.db_copy.resolve()), "timings_sec": {}}

    def timed(name, action):
        start = time.perf_counter()
        result = action()
        report["timings_sec"][name] = round(time.perf_counter() - start, 4)
        return result

    try:
        assert gateway.health(), "Runtime health check failed"
        timed("open", lambda: gateway.open_by_path(str(args.db_copy.resolve())))
        timed("navigation", gateway.manifest_nav)
        context = timed("object_context", lambda: gateway.manifest_object_context(args.document_guid))
        timed("object_context_warm", lambda: gateway.manifest_object_context(args.document_guid))
        owner = {**context["row"], "payload": context["payload"]}
        table = "data_document_" + owner["name"].lower()
        rows = timed("first_page", lambda: gateway.table_select(table, limit=5))
        all_rows = timed("all_imported_rows", lambda: gateway.table_select(table))
        report.update(first_page_count=len(rows), imported_count=len(all_rows),
                      import_status=gateway.last_table_status.get(table),
                      form_names=[row["name"] for row in context.get("forms", [])])
        assert all_rows and len(rows) == min(5, len(all_rows))
        last = timed("point_lookup_after_page", lambda: gateway.table_select(table, {"_guid": all_rows[-1]["_guid"]}))
        assert last and last[0]["_guid"] == all_rows[-1]["_guid"]
        semantic_names = [r["name"] for r in context["payload"].get("requisites", [])]
        report["mapped_requisites"] = [n for n in semantic_names if n in rows[0]]
        report["unmapped_requisites"] = [n for n in semantic_names if n not in rows[0]]

        app = QApplication.instance() or QApplication([])
        for font in ("segoeui.ttf", "consola.ttf", "consolab.ttf", "consolai.ttf"):
            path = Path("C:/Windows/Fonts") / font
            if path.exists():
                QFontDatabase.addApplicationFont(str(path))
        app.setFont(QFont("Segoe UI", 10))

        probe = ClientWindowRuntimeMixin()
        probe._db = GatewayDb(gateway)
        probe._manifest_by_guid_cache = {owner["guid"]: owner}
        form = probe._find_form_model_for_owner_guid(owner["guid"], "list_form", context=context)
        report["has_imported_list_form"] = bool(form)
        if not form:
            raise RuntimeError("Imported list form is unavailable; not substituting a mock form")
        widget = FormRuntimeWidget(model=form, db=probe._db, manifest_rows=[owner],
            ctx=ObjContext(obj_guid=owner["guid"], obj_name=owner["name"], obj_type="document",
                           obj_title=owner["title"], form_kind="list_form"))
        widget.resize(1600, 850)
        widget.show()
        app.processEvents()
        report["list_bindings"] = widget._list_col_bindings
        table_view = widget._list_table
        if table_view is not None:
            model = table_view.model()
            report["nonempty_first_row_columns"] = [model.headerData(c, Qt.Orientation.Horizontal)
                for c in range(model.columnCount()) if model.index(0, c).data() not in (None, "")]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        assert widget.grab().save(str(args.output))
        widget.close()
        widget.deleteLater()
        app.processEvents()
        report["screenshot"] = str(args.output.resolve())
        object_form = probe._find_form_model_for_owner_guid(owner["guid"], "object_form", context=context)
        report["has_imported_object_form"] = bool(object_form)
        if object_form:
            card = timed("object_form_build", lambda: FormRuntimeWidget(
                model=object_form, db=probe._db, manifest_rows=[owner],
                ctx=ObjContext(obj_guid=owner["guid"], obj_name=owner["name"], obj_type="document",
                               obj_title=owner["title"], form_kind="object_form", rec_guid=rows[0]["_guid"])))
            card.resize(1600, 950)
            card.show()
            app.processEvents()
            report["object_loaded"] = card._record.get("_guid") == rows[0]["_guid"]
            report["object_bound_input_count"] = len(card._bound_inputs)
            for binding in ("Number", "Date"):
                control = card._bound_inputs.get(binding)
                if control is not None:
                    expected = card._record_value_for_binding(rows[0], binding)
                    actual = card._get_val(control)
                    if binding == "Date":
                        expected = str(expected)[:10]
                    report[f"object_{binding.lower()}_matches"] = str(actual) == str(expected)
                    assert report[f"object_{binding.lower()}_matches"], f"Incorrect {binding} editor value"
            report["tabular_parts"] = {name: {"rows": view.model().rowCount(),
                                              "columns": card._tp_col_bindings.get(name, [])}
                                       for name, view in card._tp_tables.items() if view.model() is not None}
            object_path = args.output.with_stem(args.output.stem + "-object")
            assert card.grab().save(str(object_path))
            report["object_screenshot"] = str(object_path.resolve())
            card.close()
            card.deleteLater()
            app.processEvents()
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        args.output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        gateway.close_session()
        server.shutdown()
        server.server_close()
        worker.join(2)
        for _path, db, _last in list(STATE_DBS._dbs.values()):
            db.close()


if __name__ == "__main__":
    main()
