from pathlib import Path

import src.scripts.audit_dsl_corpus as audit_module
from src.scripts.audit_dsl_corpus import audit_corpus, main


def test_audit_corpus_reports_parse_failures(tmp_path: Path) -> None:
    (tmp_path / "Good.bsl").write_text(
        "Функция Main() Возврат 1; КонецФункции",
        encoding="utf-8",
    )
    (tmp_path / "Broken.bsl").write_text(
        "Функция Broken( Возврат 1;",
        encoding="utf-8",
    )

    report = audit_corpus(tmp_path)

    assert report["total"] == 2
    assert report["passed"] == 1
    assert report["failed"] == 1
    assert report["failures"][0]["path"] == "Broken.bsl"
    assert report["failures"][0]["stage"] == "parse"


def test_audit_corpus_rejects_replacement_and_control_characters(tmp_path: Path) -> None:
    (tmp_path / "Broken.bsl").write_text(
        "Процедура Main()\n\ufffd\x02\nКонецПроцедуры",
        encoding="utf-8",
    )

    report = audit_corpus(tmp_path)

    assert report["failed"] == 1
    assert report["failures"][0]["stage"] == "source"
    assert report["failures"][0]["line"] == 2
    assert "U+FFFD" in report["failures"][0]["message"]


def test_audit_corpus_cli_returns_success_for_clean_tree(tmp_path: Path) -> None:
    (tmp_path / "Good.bsl").write_text(
        "Процедура Main() КонецПроцедуры",
        encoding="utf-8",
    )

    assert main([str(tmp_path)]) == 0


def test_audit_corpus_cli_rejects_missing_root(tmp_path: Path) -> None:
    assert main([str(tmp_path / "missing")]) == 2


def test_audit_corpus_reads_modules_from_direct_onecd_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    onecd_path = tmp_path / "1Cv8.1CD"
    onecd_path.write_bytes(b"test")

    class FakeOneCDConfigSource:
        def __init__(self, path: Path) -> None:
            assert path == onecd_path

        def list_files(self) -> list[str]:
            return ["CommonModules/Test/Ext/Module.bsl", "CommonModules/Test.xml"]

        def read_bytes(self, path: str) -> bytes:
            assert path.endswith("Module.bsl")
            return "Процедура Main() КонецПроцедуры".encode("utf-8")

    monkeypatch.setattr(audit_module, "OneCDConfigSource", FakeOneCDConfigSource)

    report = audit_corpus(onecd_path)

    assert report["total"] == 1
    assert report["passed"] == 1
    assert report["failed"] == 0
