"""Process-level Runtime smoke test used by CI."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from src.mpdb.mpdb import Mpdb
from src.runtime.gateway import RuntimeGateway


BUDGETS = {
    "startup": 15.0,
    "open_db": 15.0,
    "point_read": 5.0,
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


def main() -> int:
    port = _free_port()
    runtime_url = f"http://127.0.0.1:{port}"
    timings: dict[str, float] = {}

    with tempfile.TemporaryDirectory(prefix="metaplatform-runtime-smoke-") as tmp:
        db_path = Path(tmp) / "smoke.mpdb"
        db = Mpdb(str(db_path))
        try:
            db.create_table(
                "smoke",
                {
                    "key": {"type": "str", "indexed": True, "unique": True},
                    "value": {"type": "str"},
                },
            )
            db.table("smoke").insert({"key": "health", "value": "ok"})
            db.checkpoint(durable=True, keep_wal_bytes=0)
        finally:
            db.close()

        proc = subprocess.Popen(
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
        try:
            started = time.perf_counter()
            deadline = started + BUDGETS["startup"]
            while time.perf_counter() < deadline and not gateway.health(timeout=0.5):
                if proc.poll() is not None:
                    output = proc.stdout.read() if proc.stdout else ""
                    raise RuntimeError(
                        f"Runtime exited before health check: code={proc.returncode}\n{output}"
                    )
                time.sleep(0.1)
            if not gateway.health(timeout=0.5):
                raise TimeoutError("Runtime did not become healthy before startup budget")
            timings["startup"] = time.perf_counter() - started

            opened, timings["open_db"] = _timed(
                "open_db", lambda: gateway.open_by_path(str(db_path))
            )
            if not str(opened.get("db_uid") or ""):
                raise AssertionError(f"db.open_by_path returned no db_uid: {opened!r}")

            rows, timings["point_read"] = _timed(
                "point_read",
                lambda: gateway.table_select("smoke", {"key": "health"}, limit=1),
            )
            if len(rows) != 1 or rows[0].get("value") != "ok":
                raise AssertionError(f"unexpected point-read result: {rows!r}")

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
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    print(json.dumps({"status": "ok", "timings_sec": timings}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
