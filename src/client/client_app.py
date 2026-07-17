from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase

from src.platform.locale_detect import detect_system_lang
from src.platform.logging_setup import setup_logging
from src.ui_qt.i18n import init_i18n, t
from src.ui_qt.theme import apply_hybrid_theme, set_app_icon

from .runtime_context import RuntimeContext
from .client_window import ClientWindow


# ── Roboto font loader ────────────────────────────────────────────────────────

def _apply_roboto_font(app: QApplication) -> None:
    """Load Roboto from bundled assets and set as default app font."""
    fonts_dir = Path(__file__).resolve().parents[1] / "assets" / "fonts"
    loaded = False
    for fname in ("Roboto-Regular.ttf", "Roboto-Bold.ttf", "Roboto-Medium.ttf"):
        fpath = fonts_dir / fname
        if fpath.exists():
            QFontDatabase.addApplicationFont(str(fpath))
            loaded = True

    # Try to download fonts if not present yet
    if not loaded:
        _try_download_roboto(fonts_dir)
        for fname in ("Roboto-Regular.ttf", "Roboto-Bold.ttf", "Roboto-Medium.ttf"):
            fpath = fonts_dir / fname
            if fpath.exists():
                QFontDatabase.addApplicationFont(str(fpath))
                loaded = True

    font = QFont("Roboto" if loaded else "Segoe UI", 10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)


def _try_download_roboto(fonts_dir: Path) -> None:
    """Download Roboto fonts in a background thread — never blocks startup."""
    import threading

    def _worker():
        try:
            import urllib.request
            fonts_dir.mkdir(parents=True, exist_ok=True)
            base = "https://github.com/google/fonts/raw/main/apache/roboto/static"
            for name in ("Roboto-Regular.ttf", "Roboto-Bold.ttf", "Roboto-Medium.ttf"):
                dest = fonts_dir / name
                if not dest.exists():
                    urllib.request.urlretrieve(f"{base}/{name}", dest)
        except Exception:
            pass  # Offline — graceful fallback to system font

    threading.Thread(target=_worker, daemon=True).start()


# ── Entry points ──────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--runtime", dest="runtime", default="",
                   help="Runtime server URL, e.g. http://127.0.0.1:8765")
    p.add_argument("--db-uid", dest="db_uid", default="",
                   help="Database UID as registered on the runtime server")
    args = p.parse_args(argv)

    runtime_url = args.runtime.strip() or os.environ.get("META_RUNTIME_URL", "").strip()
    db_uid      = args.db_uid.strip()  or os.environ.get("META_DB_UID",      "").strip()
    session_id  = os.environ.get("META_SESSION_ID", "").strip()
    db_name     = os.environ.get("META_DB_NAME",    "").strip()

    if not runtime_url or not db_uid:
        p.error(
            "Provide --runtime <url> --db-uid <uid>  "
            "or set META_RUNTIME_URL + META_DB_UID env vars"
        )

    app = QApplication(sys.argv)
    setup_logging(detect_system_lang())
    init_i18n(default_lang=detect_system_lang())
    app.setQuitOnLastWindowClosed(True)
    apply_hybrid_theme(app)
    set_app_icon(app)
    _apply_roboto_font(app)

    runtime = RuntimeContext(
        runtime_url=runtime_url,
        session_id=session_id,
        db_name=db_name,
        db_uid=db_uid,
    )

    w = ClientWindow(runtime=runtime, db_path=None)
    try:
        startup_ok = True
        if hasattr(w, "_run_startup_modules"):
            startup_ok = bool(w._run_startup_modules(phase="pre"))  # type: ignore[misc]
        if not startup_ok:
            return 0
    except Exception:
        pass
    w.show()

    return app.exec()


def run(runtime_url: str = "", db_uid: str = "") -> int:
    """Run client in-process (launcher mode)."""
    from PySide6.QtCore import QEventLoop

    if not runtime_url:
        runtime_url = os.environ.get("META_RUNTIME_URL", "").strip()
    if not db_uid:
        db_uid = os.environ.get("META_DB_UID", "").strip()

    if not runtime_url or not db_uid:
        raise RuntimeError(
            "Client requires runtime_url + db_uid "
            "(pass as args or set META_RUNTIME_URL + META_DB_UID)"
        )

    session_id = os.environ.get("META_SESSION_ID", "").strip()
    db_name    = os.environ.get("META_DB_NAME",    "").strip()

    had_app = QApplication.instance() is not None
    app = QApplication.instance() or QApplication(sys.argv)
    setup_logging(detect_system_lang())
    init_i18n(default_lang=detect_system_lang())
    app.setQuitOnLastWindowClosed(True)
    apply_hybrid_theme(app)
    set_app_icon(app)
    _apply_roboto_font(app)

    runtime = RuntimeContext(
        runtime_url=runtime_url,
        session_id=session_id,
        db_name=db_name,
        db_uid=db_uid,
    )

    w = ClientWindow(runtime=runtime, db_path=None)
    try:
        startup_ok = True
        if hasattr(w, "_run_startup_modules"):
            startup_ok = bool(w._run_startup_modules(phase="pre"))  # type: ignore[misc]
        if not startup_ok:
            return 0
    except Exception:
        pass
    w.show()

    if had_app:
        loop = QEventLoop()
        try:
            w.destroyed.connect(loop.quit)
        except Exception:
            pass
        loop.exec()
        return 0

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
