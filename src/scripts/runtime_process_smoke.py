"""Process-level Runtime, Configurator and Client acceptance smoke used by CI."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

from src.configurator.persistence.db_seed import GUID_GROUP_DOCUMENT
from src.configurator.persistence.manifest_io import add_object, ensure_manifest
from src.mpdb.mpdb import Mpdb
from src.runtime.gateway import GatewayDb, RuntimeGateway


CONFIGURATOR_CYCLES = 3
LIST_ROWS = 50
BUDGETS = {
    "startup": 15.0,
    "open_db": 15.0,
    "manifest_point_read": 5.0,
    "point_read": 5.0,
    "list_load": 5.0,
    "configurator_startup": 20.0,
    "configurator_open": 5.0,
    "object_form": 5.0,
    "configurator_shutdown": 5.0,
    "close_session": 5.0,
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _timed(name: str, fn):
    started = time.perf_counter()
    value = fn()
    elapsed = time.perf_counter() - started
    if elapsed > BUDGETS[name]:
        raise AssertionError(
            f"{name} exceeded budget: {elapsed:.3f}s > {BUDGETS[name]:.3f}s"
        )
    return value, elapsed


def _http_json(url: str, *, payload: dict | None = None, timeout: float = 2.0) -> dict:
    body = None
    headers = {}
    method = "GET"
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    request = Request(url, data=body, headers=headers, method=method)
    with urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    if data.get("status") == "error":
        raise RuntimeError(str(data.get("error") or "HTTP command failed"))
    return data


def _wait_health(url: str, proc: subprocess.Popen[str], budget: float, label: str) -> float:
    started = time.perf_counter()
    deadline = started + budget
    last_error = ""
    while time.perf_counter() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(
                f"{label} exited before health check: code={proc.returncode}\n{output}"
            )
        try:
            _http_json(url, timeout=0.5)
            return time.perf_counter() - started
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(0.1)
    raise TimeoutError(f"{label} did not become healthy: {last_error}")


def _seed_smoke_db(db_path: Path) -> tuple[str, str, dict]:
    db = Mpdb(str(db_path))
    try:
        ensure_manifest(db, seed_defaults=True)
        form_model = {
            "schema_version": 1,
            "root": {
                "id": "root",
                "type": "Container",
                "children": [
                    {"id": "number", "type": "TextBox", "binding": "Number"},
                    {"id": "amount", "type": "NumberBox", "binding": "Amount"},
                    {
                        "id": "items",
                        "type": "TablePanel",
                        "binding": "Items",
                        "props": {"columns": [{"name": "Quantity"}]},
                    },
                ],
            },
        }
        doc = add_object(
            db,
            "document",
            "SmokeDoc",
            "Smoke document",
            GUID_GROUP_DOCUMENT,
            payload={
                "requisites": [{"name": "Amount", "type": "number"}],
                "tabular_parts": [
                    {
                        "name": "Items",
                        "columns": [{"name": "Quantity", "type": "number"}],
                    }
                ],
                "form_model": form_model,
            },
        )
        db.create_table(
            "data_document_smokedoc",
            {
                "_guid": {"type": "str", "indexed": True, "unique": True},
                "_number": {"type": "str"},
                "Amount": {"type": "float"},
            },
        )
        db.create_table(
            "data_tp_smokedoc_items",
            {
                "_doc_guid": {"type": "str", "indexed": True},
                "_line_no": {"type": "int"},
                "Quantity": {"type": "float"},
            },
        )
        record_guid = "smoke-record-1"
        documents = db.table("data_document_smokedoc")
        documents.insert(
            {"_guid": record_guid, "_number": "SMK-0001", "Amount": 12.5}
        )
        for index in range(2, LIST_ROWS + 1):
            documents.insert(
                {
                    "_guid": f"smoke-record-{index}",
                    "_number": f"SMK-{index:04d}",
                    "Amount": float(index),
                }
            )
        db.table("data_tp_smokedoc_items").insert(
            {"_doc_guid": record_guid, "_line_no": 1, "Quantity": 3.0}
        )
        db.checkpoint(durable=True, keep_wal_bytes=0)
        return doc.guid, record_guid, form_model
    finally:
        db.close()


def _build_object_form(
    gateway: RuntimeGateway,
    *,
    form_model: dict,
    doc_guid: str,
    record_guid: str,
    payload: dict,
) -> bool:
    from PySide6.QtWidgets import QApplication

    from src.client.forms.form_runtime_widget import FormRuntimeWidget, ObjContext

    app = QApplication.instance() or QApplication([])
    card = FormRuntimeWidget(
        model=form_model,
        db=GatewayDb(gateway),
        manifest_rows=[
            {
                "guid": doc_guid,
                "name": "SmokeDoc",
                "title": "Smoke document",
                "type": "document",
                "payload": payload,
            }
        ],
        ctx=ObjContext(
            obj_guid=doc_guid,
            obj_name="SmokeDoc",
            obj_type="document",
            obj_title="Smoke document",
            form_kind="object_form",
            rec_guid=record_guid,
        ),
    )
    card.show()
    app.processEvents()
    try:
        if card._record.get("_guid") != record_guid:
            raise AssertionError(f"object form did not load record: {card._record!r}")
        if float(card._record.get("Amount") or 0.0) != 12.5:
            raise AssertionError(f"object form lost requisite: {card._record!r}")
        items = card._tp_tables.get("Items")
        if items is None or items.model() is None or items.model().rowCount() != 1:
            raise AssertionError("object form did not load tabular part")
    finally:
        card.close()
        card.deleteLater()
        app.processEvents()
    return True


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    port = _free_port()
    runtime_url = f"http://127.0.0.1:{port}"
    timings: dict[str, float] = {}

    with tempfile.TemporaryDirectory(prefix="metaplatform-runtime-smoke-") as tmp:
        db_path = Path(tmp) / "smoke.mpdb"
        doc_guid, record_guid, form_model = _seed_smoke_db(db_path)

        runtime_proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "src.scripts.run_runtime_server_cmd",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        gateway = RuntimeGateway(runtime_url)
        configurator_proc: subprocess.Popen[str] | None = None
        try:
            timings["startup"] = _wait_health(
                f"{runtime_url}/health", runtime_proc, BUDGETS["startup"], "Runtime"
            )

            opened, timings["open_db"] = _timed(
                "open_db", lambda: gateway.open_by_path(str(db_path))
            )
            db_uid = str(opened.get("db_uid") or "")
            if not db_uid:
                raise AssertionError(f"db.open_by_path returned no db_uid: {opened!r}")

            payload, timings["manifest_point_read"] = _timed(
                "manifest_point_read", lambda: gateway.manifest_get_payload(doc_guid)
            )
            if [x.get("name") for x in payload.get("requisites", [])] != ["Amount"]:
                raise AssertionError(f"unexpected manifest payload: {payload!r}")
            if [x.get("name") for x in payload.get("tabular_parts", [])] != ["Items"]:
                raise AssertionError(f"unexpected tabular metadata: {payload!r}")

            rows, timings["point_read"] = _timed(
                "point_read",
                lambda: gateway.table_select(
                    "data_document_smokedoc", {"_guid": record_guid}, limit=1
                ),
            )
            if len(rows) != 1 or rows[0].get("Amount") != 12.5:
                raise AssertionError(f"unexpected point-read result: {rows!r}")

            list_rows, timings["list_load"] = _timed(
                "list_load",
                lambda: gateway.table_select(
                    "data_document_smokedoc", {}, limit=100
                ),
            )
            if len(list_rows) != LIST_ROWS:
                raise AssertionError(
                    f"unexpected list row count: {len(list_rows)} != {LIST_ROWS}"
                )

            env = {
                **os.environ,
                "QT_QPA_PLATFORM": "offscreen",
                "PYTHONUTF8": "1",
            }
            for cycle in range(1, CONFIGURATOR_CYCLES + 1):
                control_port = _free_port()
                control_url = f"http://127.0.0.1:{control_port}"
                configurator_proc = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "src.configurator.configurator_app",
                        "--runtime",
                        runtime_url,
                        "--db-uid",
                        db_uid,
                        "--db-path",
                        str(db_path),
                        "--control-api-host",
                        "127.0.0.1",
                        "--control-api-port",
                        str(control_port),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                )
                timings[f"configurator_startup_{cycle}"] = _wait_health(
                    f"{control_url}/health",
                    configurator_proc,
                    BUDGETS["configurator_startup"],
                    f"Configurator cycle {cycle}",
                )

                state, open_elapsed = _timed(
                    "configurator_open",
                    lambda: _http_json(
                        f"{control_url}/command",
                        payload={"action": "open", "payload": {"guid": doc_guid}},
                        timeout=BUDGETS["configurator_open"],
                    ).get("data", {}),
                )
                timings[f"configurator_open_{cycle}"] = open_elapsed
                if doc_guid not in list(state.get("open_windows") or []):
                    raise AssertionError(
                        f"Configurator cycle {cycle} did not open smoke document: {state!r}"
                    )

                if cycle == 1:
                    _, timings["object_form"] = _timed(
                        "object_form",
                        lambda: _build_object_form(
                            gateway,
                            form_model=form_model,
                            doc_guid=doc_guid,
                            record_guid=record_guid,
                            payload=payload,
                        ),
                    )

                close_result = _http_json(
                    f"{control_url}/command",
                    payload={
                        "action": "close",
                        "payload": {"discard_unsaved_changes": True},
                    },
                    timeout=BUDGETS["configurator_shutdown"],
                ).get("data", {})
                if not close_result.get("accepted"):
                    raise AssertionError(
                        f"Configurator cycle {cycle} rejected close: {close_result!r}"
                    )
                started_shutdown = time.perf_counter()
                configurator_proc.wait(timeout=BUDGETS["configurator_shutdown"])
                shutdown_elapsed = time.perf_counter() - started_shutdown
                timings[f"configurator_shutdown_{cycle}"] = shutdown_elapsed
                if shutdown_elapsed > BUDGETS["configurator_shutdown"]:
                    raise AssertionError(
                        f"configurator_shutdown exceeded budget in cycle {cycle}: "
                        f"{shutdown_elapsed:.3f}s > {BUDGETS['configurator_shutdown']:.3f}s"
                    )
                if configurator_proc.returncode != 0:
                    output = configurator_proc.stdout.read() if configurator_proc.stdout else ""
                    raise RuntimeError(
                        f"Configurator cycle {cycle} exited with "
                        f"{configurator_proc.returncode}\n{output}"
                    )
                configurator_proc = None

            closed, timings["close_session"] = _timed(
                "close_session", gateway.close_session
            )
            if not closed:
                raise AssertionError("session.close did not confirm closure")
        finally:
            try:
                gateway.close_session()
            except Exception:
                pass
            if configurator_proc is not None:
                configurator_proc.terminate()
                try:
                    configurator_proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    configurator_proc.kill()
                    configurator_proc.wait(timeout=3)
            runtime_proc.terminate()
            try:
                runtime_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                runtime_proc.kill()
                runtime_proc.wait(timeout=5)

    print(json.dumps({"status": "ok", "timings_sec": timings}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
