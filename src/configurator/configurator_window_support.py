from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class _OnecImportWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        *,
        db_path: str,
        source_path: str,
        source_kind: str,
        runtime_url: str,
        db_uid: str,
        session_id: str,
        wipe_prefixes: bool,
        migrate_data: bool = False,
    ) -> None:
        super().__init__()
        self._db_path = str(db_path or "")
        self._source_path = str(source_path or "")
        self._source_kind = str(source_kind or "")
        self._runtime_url = str(runtime_url or "")
        self._db_uid = str(db_uid or "")
        self._session_id = str(session_id or "")
        self._wipe_prefixes = bool(wipe_prefixes)
        self._migrate_data = bool(migrate_data)

    def run(self) -> None:
        from src.tools.onec_import import import_onec_configuration

        try:
            message = import_onec_configuration(
                db_path=self._db_path,
                source_path=self._source_path,
                source_kind=self._source_kind,
                mode="hard",
                wipe_prefixes=self._wipe_prefixes,
                prune_missing_assets=True,
                migrate_data=self._migrate_data,
                runtime_url=self._runtime_url,
                db_uid=self._db_uid,
                session_id=self._session_id,
            )
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.finished.emit(str(message or ""))
