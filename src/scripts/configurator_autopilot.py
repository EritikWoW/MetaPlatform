from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from pathlib import Path
from typing import Any

from src.platform.paths import get_user_config_dir


def _default_report_path() -> Path:
    return get_user_config_dir() / "subsystem_membership_report.json"


def _default_compare_report_path() -> Path:
    return get_user_config_dir() / "source_structure_compare_report.json"


def _report_paths(*, source_path: str, explicit_path: str = "") -> list[Path]:
    paths: list[Path] = []
    if explicit_path:
        paths.append(Path(explicit_path))
    paths.append(_default_report_path())
    src = str(source_path or "").strip()
    if src:
        source = Path(src)
        base_dir = source.parent if source.suffix else source
        paths.append(base_dir / "subsystem_membership_report.json")
    uniq: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve()) if path.is_absolute() else str(path)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(path)
    return uniq


def _compare_report_paths(*, source_path: str, explicit_path: str = "") -> list[Path]:
    paths: list[Path] = []
    if explicit_path:
        paths.append(Path(explicit_path))
    paths.append(_default_compare_report_path())
    src = str(source_path or "").strip()
    if src:
        source = Path(src)
        base_dir = source.parent if source.suffix else source
        paths.append(base_dir / "source_structure_compare_report.json")
    uniq: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve()) if path.is_absolute() else str(path)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(path)
    return uniq


def _save_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _bootstrap_import_path() -> None:
    src_dir = Path(__file__).resolve().parents[2]
    src_str = str(src_dir)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)


def _request_json(url: str, *, method: str = "GET", payload: dict[str, Any] | None = None, timeout: float = 10.0) -> dict[str, Any]:
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _command(base_url: str, action: str, payload: dict[str, Any] | None = None, *, timeout: float = 30.0) -> dict[str, Any]:
    res = _request_json(
        base_url.rstrip("/") + "/command",
        method="POST",
        payload={"action": action, "payload": payload or {}},
        timeout=timeout,
    )
    if res.get("status") != "ok":
        raise RuntimeError(str(res.get("error") or f"command failed: {action}"))
    return dict(res.get("data") or {})


def _health(base_url: str, *, timeout: float = 5.0) -> bool:
    try:
        res = _request_json(base_url.rstrip("/") + "/health", timeout=timeout)
        return str(res.get("status") or "") == "ok"
    except Exception:
        return False


def _start_runtime(host: str, port: int) -> None:
    project_root = Path(__file__).resolve().parents[2]
    script = str((project_root / "scripts" / "run_runtime_server_cmd.py").resolve())
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [sys.executable, script, "--host", host, "--port", str(int(port))],
        cwd=str(project_root),
        env=os.environ.copy(),
        creationflags=flags,
    )


def _start_configurator(*, runtime_url: str, db_uid: str, db_path: str, control_host: str, control_port: int) -> None:
    project_root = Path(__file__).resolve().parents[2]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    cmd = [
        sys.executable,
        "-m",
        "src.configurator.configurator_app",
        "--runtime",
        runtime_url,
        "--control-api-host",
        control_host,
        "--control-api-port",
        str(int(control_port)),
    ]
    if db_uid:
        cmd.extend(["--db-uid", db_uid])
    if db_path:
        cmd.extend(["--db-path", db_path])
    env = os.environ.copy()
    env["META_RUNTIME_URL"] = runtime_url
    if db_uid:
        env["META_DB_UID"] = db_uid
    if db_path:
        env["META_DB_PATH"] = db_path
    env["META_CONTROL_API_HOST"] = control_host
    env["META_CONTROL_API_PORT"] = str(int(control_port))
    subprocess.Popen(
        cmd,
        cwd=str(project_root),
        env=env,
        creationflags=flags,
    )


def _wait_for_control(base_url: str, *, timeout: float = 60.0, interval: float = 0.5) -> None:
    started = time.time()
    while time.time() - started < timeout:
        if _health(base_url):
            return
        time.sleep(interval)
    raise TimeoutError(f"Control API not available: {base_url}")


def _wait_for_import_done(base_url: str, *, session_id: str, timeout: float = 1800.0, interval: float = 1.0) -> dict[str, Any]:
    started = time.time()
    last: dict[str, Any] = {}
    while time.time() - started < timeout:
        data = _command(base_url, "import_status", {"history_limit": 20}, timeout=10.0)
        state = dict(data.get("state") or {})
        if state:
            last = state
            status = str(state.get("status") or "").strip().lower()
            phase = str(state.get("phase") or "").strip().lower()
            if status in {"done", "failed"} or phase in {"done", "failed"} or bool(state.get("failed")):
                return state
        time.sleep(interval)
    raise TimeoutError(f"Import did not finish in time: session={session_id} last={last}")


def _wait_for_runtime_sync(base_url: str, *, timeout: float = 120.0, interval: float = 1.0) -> dict[str, Any]:
    started = time.time()
    last: dict[str, Any] = {}
    while time.time() - started < timeout:
        state = _command(base_url, "state", {"include_tree": False}, timeout=10.0)
        last = dict(state or {})
        if int(last.get("tree_count") or 0) > 0 and not bool(last.get("runtime_refresh_in_flight")):
            return last
        time.sleep(interval)
    raise TimeoutError(f"Runtime sync did not complete in time: {last}")


def main() -> int:
    _bootstrap_import_path()

    ap = argparse.ArgumentParser()
    ap.add_argument("--control-url", default="http://127.0.0.1:8766")
    ap.add_argument("--runtime-url", default="http://127.0.0.1:8765")
    ap.add_argument("--db-uid", default="")
    ap.add_argument("--db-path", default="")
    ap.add_argument("--source-path", default="")
    ap.add_argument("--source-kind", default="auto")
    ap.add_argument("--wipe-prefixes", action="store_true", default=True)
    ap.add_argument("--no-wipe-prefixes", dest="wipe_prefixes", action="store_false")
    ap.add_argument("--migrate-data", action="store_true", default=False)
    ap.add_argument("--verify-guid", default="")
    ap.add_argument("--verify-name", default="")
    ap.add_argument("--verify-title", default="")
    ap.add_argument("--restart", action="store_true", default=False)
    ap.add_argument("--wait-timeout", type=float, default=1800.0)
    ap.add_argument("--report-path", default="")
    args = ap.parse_args()

    control_url = str(args.control_url or "").strip()
    runtime_url = str(args.runtime_url or "").strip()
    db_uid = str(args.db_uid or os.environ.get("META_DB_UID", "") or "").strip()
    db_path = str(args.db_path or os.environ.get("META_DB_PATH", "") or "").strip()
    if not control_url:
        raise SystemExit("control-url is required")
    if not runtime_url:
        raise SystemExit("runtime-url is required")

    if not _health(runtime_url):
        parsed = urlparse(runtime_url)
        host = parsed.hostname or "127.0.0.1"
        port = int(parsed.port or 8765)
        _start_runtime(host, port)
        _wait_for_control(runtime_url, timeout=60.0)

    if not _health(control_url):
        parsed = urlparse(control_url)
        host = parsed.hostname or "127.0.0.1"
        port = int(parsed.port or 8766)
        _start_configurator(
            runtime_url=runtime_url,
            db_uid=db_uid,
            db_path=db_path,
            control_host=host,
            control_port=port,
        )
        _wait_for_control(control_url, timeout=120.0)

    _wait_for_control(control_url)

    import_payload: dict[str, Any] = {
        "source_path": str(args.source_path or "").strip(),
        "source_kind": str(args.source_kind or "auto").strip() or "auto",
        "wipe_prefixes": bool(args.wipe_prefixes),
        "migrate_data": bool(args.migrate_data),
    }
    import_res = _command(control_url, "import_onec", import_payload, timeout=20.0)
    session_id = str(import_res.get("session_id") or "").strip()
    if not session_id:
        import_status = _command(control_url, "import_status", {"history_limit": 5}, timeout=10.0)
        session_id = str(import_status.get("session_id") or "").strip()

    if session_id:
        final_import = _wait_for_import_done(control_url, session_id=session_id, timeout=args.wait_timeout)
    else:
        final_import = _command(control_url, "import_status", {"history_limit": 20}, timeout=10.0).get("state") or {}

    sync_state = _command(control_url, "sync_runtime", {"include_tree": True}, timeout=30.0)
    runtime_state = _wait_for_runtime_sync(control_url)

    compare_state: dict[str, Any] = {}
    audit_state: dict[str, Any] = {}
    try:
        audit_state = _command(
            control_url,
            "audit_source_structure",
            {
                "source_path": str(import_payload.get("source_path") or "").strip(),
                "source_kind": str(import_payload.get("source_kind") or "auto").strip() or "auto",
                "repair": True,
            },
            timeout=240.0,
        )
        compare_state = dict(audit_state.get("compare") or {})
    except Exception as exc:
        compare_state = {"error": f"{type(exc).__name__}: {exc}"}
        audit_state = {"error": f"{type(exc).__name__}: {exc}"}

    repair_payload = {
        "guid": str(args.verify_guid or "").strip(),
        "name": str(args.verify_name or "").strip(),
        "title": str(args.verify_title or "").strip(),
    }
    diagnose_res: dict[str, Any] = {}
    repair_res: dict[str, Any] = {}
    try:
        sync_res = _command(
            control_url,
            "sync_subsystem_membership",
            {k: v for k, v in repair_payload.items() if v},
            timeout=120.0,
        )
        diagnose_res = dict(sync_res.get("before") or sync_res)
        repair_res = dict(sync_res.get("repair") or {})
        if int(sync_res.get("changed") or 0) > 0:
            sync_state = _command(control_url, "sync_runtime", {"include_tree": True}, timeout=30.0)
            runtime_state = _wait_for_runtime_sync(control_url)
    except Exception as exc:
        repair_res = {"error": f"{type(exc).__name__}: {exc}"}

    verification: dict[str, Any] = {}
    verify_payload = {
        "guid": str(args.verify_guid or "").strip(),
        "name": str(args.verify_name or "").strip(),
        "title": str(args.verify_title or "").strip(),
    }
    if any(verify_payload.values()):
        verification = _command(control_url, "verify_subsystem", verify_payload, timeout=30.0)

    restart_result: dict[str, Any] = {}
    if args.restart:
        restart_result = _command(control_url, "restart_self", {}, timeout=10.0)

    report = {
        "runtime_url": runtime_url,
        "control_url": control_url,
        "db_uid": db_uid,
        "db_path": db_path,
        "import": final_import,
        "sync": runtime_state,
        "sync_state": sync_state,
        "compare": compare_state,
        "audit": audit_state,
        "diagnose": diagnose_res,
        "repair": repair_res,
        "verify": verification,
        "restart": restart_result,
    }
    report_path = str(args.report_path or "").strip()
    report["report_path"] = report_path or str(_default_report_path())
    report_paths = _report_paths(source_path=str(args.source_path or db_path or ""), explicit_path=report_path)
    report["report_paths"] = [str(p) for p in report_paths]
    compare_report_paths = _compare_report_paths(
        source_path=str(args.source_path or db_path or ""),
        explicit_path="",
    )
    report["compare_report_paths"] = [str(p) for p in compare_report_paths]
    errors: list[str] = []
    for path in report_paths:
        try:
            _save_report(path, report)
        except Exception as exc:
            errors.append(f"{path}: {type(exc).__name__}: {exc}")
    for path in compare_report_paths:
        try:
            _save_report(path, audit_state or compare_state)
        except Exception as exc:
            errors.append(f"{path}: {type(exc).__name__}: {exc}")
    if errors:
        report["report_path_error"] = errors
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
