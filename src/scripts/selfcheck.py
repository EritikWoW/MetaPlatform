"""Lightweight regression self-check.

Run:
    python -m src.scripts.selfcheck

Goal: catch the most painful regressions quickly, without introducing a full
test framework requirement.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import List


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)
    raise SystemExit(1)


def _ok(msg: str) -> None:
    print(f"[OK] {msg}")


def _check_no_legacy_folders(objs, parent_guid: str, label: str) -> None:
    bad = [o for o in objs if str(o.kind) == "folder" and str(o.parent_guid) == parent_guid and str(o.name) in ("forms", "commands", "layouts")]
    if bad:
        names = ", ".join(sorted({str(o.name) for o in bad}))
        _fail(f"{label}: unexpected legacy folders under object ({names})")
    _ok(f"{label}: no legacy folders")


def _check_debug_smoke() -> None:
    from src.runtime.script.compiler import CodeObject, Instruction, LOAD_CONST, RETURN_NONE, STORE_NAME, ModuleCode
    from src.runtime.script.debugger import BreakpointStore, DebugSession, create_debug_session_from_env
    from src.runtime.script.vm import run_module

    with tempfile.TemporaryDirectory(prefix="mp_debug_selfcheck_") as td:
        prev_debug_dir = os.environ.get("META_DEBUG_DIR")
        prev_debug_enabled = os.environ.get("META_DEBUG_ENABLED")
        prev_client_debug = os.environ.get("META_CLIENT_DEBUG")
        try:
            os.environ["META_DEBUG_DIR"] = td
            os.environ["META_DEBUG_ENABLED"] = "1"
            os.environ["META_CLIENT_DEBUG"] = "0"

            store = BreakpointStore()
            module_id = "module://selfcheck-debug-module"
            store.set_lines(module_id, {3})

            env_session = create_debug_session_from_env()
            if env_session is None:
                _fail("debug smoke: create_debug_session_from_env returned None")
            loaded_items = env_session.breakpoints.get(module_id, set())
            loaded_lines = {int(getattr(item, "line", item)) for item in loaded_items}
            if 3 not in loaded_lines:
                _fail("debug smoke: breakpoint store was not loaded from env")

            pauses: list[tuple[str, str, int]] = []

            def _pause_handler(pause):
                pauses.append((pause.module_id, pause.code_name, pause.line))
                return "continue"

            session = DebugSession(
                breakpoints={module_id: {3}},
                pause_handler=_pause_handler,
            )
            main = CodeObject(
                name="Main",
                params=[],
                by_value=[],
                defaults=[],
                instructions=[
                    Instruction(op=LOAD_CONST, arg=True, lineno=3),
                    Instruction(op=STORE_NAME, arg="Cancel", lineno=3),
                    Instruction(op=RETURN_NONE, lineno=4),
                ],
                locals_=[],
                exported=False,
                is_function=False,
            )
            module = ModuleCode(
                name=module_id,
                procedures={"Main": main},
                functions={},
                module_vars=[],
            )
            run_module(module, entry="Main", initial_globals={"Cancel": False}, debugger=session)
            if pauses != [(module_id, "Main", 3)]:
                _fail(f"debug smoke: expected one pause, got {pauses!r}")
            _ok("Debug smoke")
        finally:
            if prev_debug_dir is None:
                os.environ.pop("META_DEBUG_DIR", None)
            else:
                os.environ["META_DEBUG_DIR"] = prev_debug_dir
            if prev_debug_enabled is None:
                os.environ.pop("META_DEBUG_ENABLED", None)
            else:
                os.environ["META_DEBUG_ENABLED"] = prev_debug_enabled
            if prev_client_debug is None:
                os.environ.pop("META_CLIENT_DEBUG", None)
            else:
                os.environ["META_CLIENT_DEBUG"] = prev_client_debug


def main() -> int:
    # Ensure headless Qt doesn't crash if it's imported somewhere.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    # Local imports to keep startup fast and errors clear.
    from src.mpdb.mpdb import Mpdb
    from src.configurator.manifest_io import ensure_manifest, list_objects, add_object

    with tempfile.TemporaryDirectory(prefix="mp_selfcheck_") as td:
        db_path = Path(td) / "selfcheck.mpdb"
        db = Mpdb(db_path)
        try:
            # Seed defaults (creates system tree).
            ensure_manifest(db, seed_defaults=True)

            # 1) Create a picture object and ensure it doesn't get object folders.
            # Find system folder for pictures: type=common, name=common_pictures
            objs = list_objects(db)
            pictures_folder_guid = ""
            for o in objs:
                if str(o.kind) in ("folder", "group") and str(o.type) == "common" and str(o.name) == "common_pictures":
                    pictures_folder_guid = str(o.guid)
                    break
            if not pictures_folder_guid:
                _fail("System folder common_pictures not found")

            pic = add_object(
                db,
                obj_type="common_picture",
                name="selfcheck_picture",
                title="SelfcheckPicture",
                parent_guid=pictures_folder_guid,
                kind="object",
                payload={"format": "svg"},
            )

            objs = list_objects(db)
            _check_no_legacy_folders(objs, str(pic.guid), "common_picture")

            # 2) Create a palette-like object using the contract flag.
            pal = add_object(
                db,
                obj_type="palette",
                name="selfcheck_palette",
                title="SelfcheckPalette",
                parent_guid=pictures_folder_guid,
                kind="object",
                payload={"no_object_folders": True},
            )

            objs = list_objects(db)
            _check_no_legacy_folders(objs, str(pal.guid), "palette (no_object_folders)")

            _ok("Manifest policies")

            # 3) SVG var(token) resolving (palette-driven icons must render deterministically).
            from src.ui_qt.services.svg_var_resolver import SvgVarResolver

            sample_svg = (
                '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
                '<defs><linearGradient id="g"><stop offset="0" stop-color="var(primary)"/>'
                '<stop offset="1" stop-color="var(--accent, #00ff00)"/></linearGradient></defs>'
                '<rect x="2" y="2" width="20" height="20" rx="4" fill="url(#g)" stroke="var(border)" stroke-width="2"/>'
                '</svg>'
            )
            palette = {"primary": "#112233", "accent": "#aabbcc", "border": "#445566"}
            rr = SvgVarResolver.resolve(sample_svg, palette)
            if rr.replaced < 3:
                _fail(f"SvgVarResolver: expected >=3 replacements, got {rr.replaced}")
            if "var(" in rr.text:
                _fail("SvgVarResolver: unresolved var(...) remained in output")
            for expected in ("#112233", "#aabbcc", "#445566"):
                if expected.lower() not in rr.text.lower():
                    _fail(f"SvgVarResolver: missing expected color {expected}")
            _ok("SvgVarResolver")

            # 4) Optional: headless SVG render should not be blank (if Qt is available).
            try:
                from PySide6.QtCore import Qt
                from PySide6.QtGui import QImage, QPainter
                from PySide6.QtSvg import QSvgRenderer
            except Exception:
                _ok("Qt render check: SKIPPED (PySide6 not available)")
            else:
                img = QImage(64, 64, QImage.Format_ARGB32)
                img.fill(Qt.GlobalColor.transparent)
                r = QSvgRenderer(rr.text.encode("utf-8"))
                if not r.isValid():
                    _fail("QSvgRenderer: invalid SVG after var() resolving")
                p = QPainter(img)
                r.render(p)
                p.end()
                # Detect any non-transparent pixel.
                any_pixel = False
                for y in range(img.height()):
                    for x in range(img.width()):
                        if (img.pixelColor(x, y).alpha() or 0) > 0:
                            any_pixel = True
                            break
                    if any_pixel:
                        break
                if not any_pixel:
                    _fail("QSvgRenderer: rendered image is blank")
                _ok("Qt SVG render")

            _check_debug_smoke()
        finally:
            db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
