from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


DT_SIGNATURE = b"1CIBDmpF"
ONECDB_SIGNATURE = b"1CDBMSV8"
KNOWN_XMLCONF_TYPE_FOLDERS = {
    "Catalogs",
    "Documents",
    "DocumentJournals",
    "Enums",
    "Reports",
    "DataProcessors",
    "ChartsOfCharacteristicTypes",
    "ChartsOfAccounts",
    "ChartsOfCalculationTypes",
    "InformationRegisters",
    "AccumulationRegisters",
    "AccountingRegisters",
    "CalculationRegisters",
    "BusinessProcesses",
    "Tasks",
    "ExternalDataSources",
    "Subsystems",
    "CommonModules",
    "CommonForms",
    "CommonCommands",
    "CommonTemplates",
    "CommonLayouts",
    "CommonPictures",
    "Roles",
    "Languages",
}


@dataclass(frozen=True, slots=True)
class ResolvedOneCSource:
    requested_kind: str
    detected_kind: str
    semantic_kind: str
    semantic_path: str
    original_path: str
    analysis: Dict[str, Any] = field(default_factory=dict)


def normalize_source_kind(source_kind: str) -> str:
    kind = str(source_kind or "").strip().lower()
    if kind in {"", "auto"}:
        return "auto"
    if kind in {"archive", "zip"}:
        return "zip"
    if kind in {"xml", "dir", "directory", "folder"}:
        return "xml"
    if kind in {"1cd", ".1cd"}:
        return "1cd"
    if kind in {"dt", ".dt"}:
        return "dt"
    return kind


def _read_signature(path: Path) -> bytes:
    try:
        with path.open("rb") as fh:
            return fh.read(8)
    except Exception:
        return b""


def inspect_dt_header(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    sig = _read_signature(p)
    version_byte = None
    try:
        with p.open("rb") as fh:
            fh.seek(8)
            raw = fh.read(1)
            version_byte = raw[0] if raw else None
    except Exception:
        version_byte = None
    return {
        "path": str(p),
        "format": "dt",
        "signature": sig.decode("ascii", errors="replace"),
        "version_byte": version_byte,
        "size": p.stat().st_size if p.exists() else 0,
    }


def inspect_1cd_header(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    sig = _read_signature(p)
    version = ""
    total_pages = 0
    page_size = 0
    try:
        with p.open("rb") as fh:
            raw = fh.read(24)
        if len(raw) >= 24:
            ver = list(raw[8:12])
            version = ".".join(str(int(x)) for x in ver)
            total_pages = int.from_bytes(raw[12:16], "little", signed=False)
            ps_raw = int.from_bytes(raw[20:24], "little", signed=False)
            if ps_raw in (4096, 8192, 16384, 32768, 65536):
                page_size = ps_raw
    except Exception:
        version = ""
    return {
        "path": str(p),
        "format": "1cd",
        "signature": sig.decode("ascii", errors="replace"),
        "version": version,
        "total_pages": total_pages,
        "page_size": page_size,
        "size": p.stat().st_size if p.exists() else 0,
    }


def _looks_like_xmlconf_root(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    if (path / "ConfigDumpInfo.xml").exists():
        return True
    if (path / "Configuration.xml").exists():
        return True
    child_names = {child.name for child in path.iterdir() if child.is_dir()}
    return bool(child_names & KNOWN_XMLCONF_TYPE_FOLDERS)


def find_xmlconf_root(path: str | Path) -> Optional[Path]:
    p = Path(path)

    candidates: list[Path] = []
    if p.is_dir():
        candidates.extend([p, p / "XMLConf"])
    else:
        candidates.extend([p.parent, p.parent / "XMLConf"])
        if p.name.lower() in {"configdumpinfo.xml", "configuration.xml"}:
            candidates.insert(0, p.parent)

    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        if resolved in seen:
            continue
        seen.add(resolved)
        if _looks_like_xmlconf_root(candidate):
            return candidate
    return None


def detect_onec_source_kind(source_path: str, source_kind: str = "") -> str:
    requested = normalize_source_kind(source_kind)
    p = Path(str(source_path or "").strip())

    if p.exists() and p.is_file():
        sig = _read_signature(p)
        ext = p.suffix.lower()
        if sig == DT_SIGNATURE or ext == ".dt":
            return "dt"
        if sig == ONECDB_SIGNATURE or ext == ".1cd":
            return "1cd"
        if ext == ".zip":
            return "zip"
        if ext == ".xml":
            return "xml"

    if p.exists() and p.is_dir():
        if _looks_like_xmlconf_root(p) or _looks_like_xmlconf_root(p / "XMLConf"):
            return "xml"

    if requested != "auto":
        return requested
    return "xml"


def resolve_onec_source(source_path: str, source_kind: str = "") -> ResolvedOneCSource:
    original_path = str(source_path or "").strip()
    if not original_path:
        raise ValueError("source_path is required")

    requested = normalize_source_kind(source_kind)
    detected = detect_onec_source_kind(original_path, requested)
    analysis: Dict[str, Any] = {}

    if detected == "dt":
        analysis = inspect_dt_header(original_path)
        xml_root = find_xmlconf_root(original_path)
        if xml_root is None:
            raise ValueError(
                "DT source detected, but XMLConf root was not found рядом. "
                "Для semantic import сейчас нужен распакованный XMLConf."
            )
        return ResolvedOneCSource(
            requested_kind=requested,
            detected_kind=detected,
            semantic_kind="xml",
            semantic_path=str(xml_root),
            original_path=original_path,
            analysis=analysis,
        )

    if detected == "1cd":
        analysis = inspect_1cd_header(original_path)
        xml_root = find_xmlconf_root(original_path)
        if xml_root is None or requested == "1cd":
            return ResolvedOneCSource(
                requested_kind=requested,
                detected_kind=detected,
                semantic_kind="1cd",
                semantic_path=original_path,
                original_path=original_path,
                analysis=analysis,
            )
        return ResolvedOneCSource(
            requested_kind=requested,
            detected_kind=detected,
            semantic_kind="xml",
            semantic_path=str(xml_root),
            original_path=original_path,
            analysis=analysis,
        )

    if detected == "zip":
        p = Path(original_path)
        return ResolvedOneCSource(
            requested_kind=requested,
            detected_kind=detected,
            semantic_kind="zip",
            semantic_path=str(p),
            original_path=original_path,
            analysis={
                "path": str(p),
                "format": "zip",
                "size": p.stat().st_size if p.exists() else 0,
            },
        )

    xml_root = find_xmlconf_root(original_path)
    semantic_path = str(xml_root or Path(original_path))
    return ResolvedOneCSource(
        requested_kind=requested,
        detected_kind=detected,
        semantic_kind="xml",
        semantic_path=semantic_path,
        original_path=original_path,
        analysis={
            "path": semantic_path,
            "format": "xml",
        },
    )


__all__ = [
    "DT_SIGNATURE",
    "ONECDB_SIGNATURE",
    "ResolvedOneCSource",
    "detect_onec_source_kind",
    "find_xmlconf_root",
    "inspect_1cd_header",
    "inspect_dt_header",
    "normalize_source_kind",
    "resolve_onec_source",
]
