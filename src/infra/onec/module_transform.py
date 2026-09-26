from __future__ import annotations

"""Conservative 1C/BSL -> MetaPlatform keyword normalization.

This is intentionally minimal and safe: it rewrites only language keywords and
literals outside string literals/comments. User identifiers are preserved.
The result is a normalized source variant for UK/EN, while the original source
remains stored unchanged.
"""

from dataclasses import dataclass
import re

from src.dsl.languages import get_normalization_identifier_profile, get_normalization_keyword_map


@dataclass(frozen=True, slots=True)
class ModuleTransformResult:
    language: str
    text: str
    changed: bool

_BSL_BINARY_ARTIFACT_LINE_RE = re.compile(r"^[ \t]*[0-9a-fA-F]{8}[ \t]+[0-9a-fA-F]{8}[ \t]+7fffffff[ \t]*$")
_BSL_CONTROL_ARTIFACT_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffd]")
_WORD_CHARS = set("_0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyzАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюяІіЇїЄєҐґ")


def _is_word_char(ch: str) -> bool:
    return ch in _WORD_CHARS


def _is_space(ch: str) -> bool:
    return ch in (" ", "\t", "\r", "\n")


def _next_nonspace(src: str, start: int) -> str:
    i = int(start)
    n = len(src)
    while i < n and _is_space(src[i]):
        i += 1
    return src[i] if i < n else ""


def _split_line_ending(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n") or line.endswith("\r"):
        return line[:-1], line[-1]
    return line, ""


def sanitize_imported_module_text(text: str) -> str:
    """Remove serialized 1C binary prelude artifacts from imported module text."""

    src = str(text or "")
    if not src:
        return ""

    out: list[str] = []
    for raw_line in src.splitlines(keepends=True):
        line = raw_line.replace("\ufeff", "")
        core, ending = _split_line_ending(line)
        stripped = core.strip()
        if not stripped:
            out.append(core + ending)
            continue
        if _BSL_BINARY_ARTIFACT_LINE_RE.fullmatch(stripped):
            out.append(ending)
            continue
        if _BSL_CONTROL_ARTIFACT_RE.search(core) is not None:
            # These are table-file stream separators, not source code. Keeping
            # their printable tail produces identifiers such as "MBtext".
            out.append(ending)
            continue
        out.append(core + ending)

    return "".join(out)


def normalize_module_text(text: str, language: str = "uk") -> ModuleTransformResult:
    language = str(language or "uk").lower()
    raw_src = str(text or "")
    if language not in {"uk", "en"}:
        sanitized = sanitize_imported_module_text(raw_src)
        return ModuleTransformResult(language=language, text=sanitized, changed=sanitized != raw_src)
    kw_map = get_normalization_keyword_map(language)
    ident_profile = get_normalization_identifier_profile(language)

    src = sanitize_imported_module_text(raw_src)
    out: list[str] = []
    i = 0
    n = len(src)
    changed = src != raw_src
    state = "code"  # code | string | line_comment
    last_token_kind = ""

    while i < n:
        ch = src[i]
        nxt = src[i + 1] if i + 1 < n else ""

        if state == "line_comment":
            out.append(ch)
            if ch == "\n":
                state = "code"
            i += 1
            continue

        if state == "string":
            out.append(ch)
            if ch == '"':
                # doubled quote inside string -> escape, stay in string
                if nxt == '"':
                    out.append(nxt)
                    i += 2
                    continue
                state = "code"
            i += 1
            continue

        # code state
        if ch == "/" and nxt == "/":
            state = "line_comment"
            out.append(ch)
            out.append(nxt)
            i += 2
            continue
        if ch == "'":
            state = "line_comment"
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            state = "string"
            out.append(ch)
            i += 1
            continue

        if _is_word_char(ch):
            j = i + 1
            while j < n and _is_word_char(src[j]):
                j += 1
            word = src[i:j]
            lower = word.lower()
            repl = kw_map.get(lower, word)
            if repl == word:
                next_sig = _next_nonspace(src, j)
                if last_token_kind == "new":
                    repl = ident_profile.constructors.get(lower, word)
                elif last_token_kind == "dot" and next_sig == "(":
                    repl = ident_profile.methods.get(lower, word)
                elif next_sig == "(":
                    repl = ident_profile.callables.get(lower, word)
            if repl != word:
                changed = True
            out.append(repl)
            if repl in {"Новий", "New"}:
                last_token_kind = "new"
            else:
                last_token_kind = "word"
            i = j
            continue

        out.append(ch)
        if not _is_space(ch):
            last_token_kind = "dot" if ch == "." else "symbol"
        i += 1

    return ModuleTransformResult(language=language, text="".join(out), changed=changed)
