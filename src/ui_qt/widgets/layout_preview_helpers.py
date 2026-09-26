from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from src.infra.onec.layout_parser import build_onec_layout_model


def _workspace_layout_candidate_paths(body_origin: str) -> list[Path]:
    rel = str(body_origin or "").strip()
    if not rel:
        return []

    raw = Path(rel)
    repo_root = Path(__file__).resolve().parents[3]
    cwd = Path.cwd()

    candidates = [
        raw,
        repo_root / raw,
        repo_root / "XMLConf" / raw,
        cwd / raw,
        cwd / "XMLConf" / raw,
    ]

    out: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            key = str(candidate.resolve(strict=False)).lower()
        except Exception:
            key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


def _load_layout_model_from_workspace(*, body_origin: str, body_mime: str = "") -> Dict[str, Any]:
    for candidate in _workspace_layout_candidate_paths(body_origin):
        try:
            if not candidate.exists() or not candidate.is_file():
                continue
            body = candidate.read_bytes()
        except Exception:
            continue
        model = build_onec_layout_model(
            body_bytes=body,
            mime=str(body_mime or ""),
            origin=str(body_origin or candidate.as_posix()),
        )
        if isinstance(model, dict) and model:
            return model
    return {}


def _layout_cell_display_text(cell: Dict[str, Any]) -> str:
    text = str(cell.get("text") or "")
    if text:
        return text
    parameter_name = str(cell.get("parameter") or "").strip()
    if parameter_name:
        return f"[{parameter_name}]"
    return ""
