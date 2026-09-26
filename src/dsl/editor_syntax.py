"""Tolerant, Qt-free lexical context and whitespace-only editor indentation.

This is not a validating parser. Incomplete buffers must remain editable; the
compiler lexer remains authoritative for syntax and string values.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .languages import get_source_keyword_aliases, get_source_preprocessor_aliases


CODE, BLOCK_COMMENT, DOUBLE_STRING, SINGLE_STRING, LINE_COMMENT = range(5)
_KEYWORDS = get_source_keyword_aliases("mixed")
_DIRECTIVES = get_source_preprocessor_aliases("mixed")
_WORD = re.compile(r"[^\W\d]\w*", re.UNICODE)
_TOKENS = re.compile(r"[^\W\d]\w*|[^\s]", re.UNICODE)


@dataclass(frozen=True)
class EditorSpan:
    start: int
    end: int
    kind: str


@dataclass(frozen=True)
class EditorLine:
    spans: tuple[EditorSpan, ...]
    state: int

    def masked_code(self, text: str) -> str:
        chars = list(text)
        for span in self.spans:
            if span.kind == "directive":
                continue
            chars[span.start:span.end] = " " * (span.end - span.start)
            if span.kind == "string" and span.end > span.start:
                chars[span.start] = "0"
        return "".join(chars)


def scan_editor_line(text: str, state: int = CODE) -> EditorLine:
    """Scan one physical line, with Python offsets and BSL doubled quotes.

    Backslashes are literal. A comment between multiline string continuation
    lines is skipped by the compiler lexer, including quotes inside it.
    """
    if state not in (BLOCK_COMMENT, DOUBLE_STRING, SINGLE_STRING):
        state = CODE
    spans: list[EditorSpan] = []
    i, size = 0, len(text)
    if state in (DOUBLE_STRING, SINGLE_STRING) and text.lstrip().startswith("//"):
        return EditorLine((EditorSpan(0, size, "comment"),), state)
    while i < size:
        start = i
        if state == BLOCK_COMMENT or text.startswith("/*", i):
            end = text.find("*/", i if state == BLOCK_COMMENT else i + 2)
            i = size if end < 0 else end + 2
            state = BLOCK_COMMENT if end < 0 else CODE
            spans.append(EditorSpan(start, i, "comment"))
        elif state in (DOUBLE_STRING, SINGLE_STRING) or text[i] in ('"', "'"):
            if state == CODE:
                state = DOUBLE_STRING if text[i] == '"' else SINGLE_STRING
                i += 1
            quote = '"' if state == DOUBLE_STRING else "'"
            while i < size:
                if text[i] == quote:
                    i += 1
                    if i < size and text[i] == quote:
                        i += 1
                        continue
                    state = CODE
                    break
                i += 1
            spans.append(EditorSpan(start, i, "string"))
        elif text.startswith("//", i):
            spans.append(EditorSpan(i, size, "comment"))
            state = LINE_COMMENT
            break
        elif text[i] == "#":
            word = _WORD.match(text, i + 1)
            if word and word.group().lower() in _DIRECTIVES:
                i = word.end()
                spans.append(EditorSpan(start, i, "directive"))
            else:
                spans.append(EditorSpan(i, size, "comment"))
                state = LINE_COMMENT
                break
        else:
            i += 1
    return EditorLine(tuple(spans), state)


@dataclass(frozen=True)
class LineIndent:
    level: int
    next_level: int
    protected: bool
    structural: bool


_OPEN = {"KW_PROCEDURE": "procedure", "KW_FUNCTION": "function",
         "KW_IF": "if", "KW_FOR": "loop", "KW_WHILE": "loop", "KW_TRY": "try"}
_CLOSE = {"KW_ENDPROCEDURE": "procedure", "KW_ENDFUNCTION": "function",
          "KW_ENDIF": "if", "KW_ENDDO": "loop", "KW_ENDWHILE": "loop", "KW_ENDTRY": "try"}
_BRANCH = {"KW_ELSE": "if", "KW_ELSEIF": "if", "KW_EXCEPT": "try"}
_PAIRS = {"(": ")", "[": "]", "{": "}"}


def indentation_plan(source: str) -> list[LineIndent]:
    """Plan indentation from tokens, not keyword-like identifier prefixes.

    The plan is zero-based by physical line. It never rewrites text. Directives
    do not add indentation; conditional alternatives start with the same scope.
    """
    blocks: list[tuple[str, int]] = []
    delimiters: list[tuple[str, int]] = []
    conditions: list[tuple[list, list, list]] = []
    state = CODE
    result = []

    def depth() -> int:
        return max(blocks[-1][1] + 1 if blocks else 0,
                   delimiters[-1][1] + 1 if delimiters else 0)

    def matching(stack, kind):
        return next((i for i in range(len(stack) - 1, -1, -1) if stack[i][0] == kind), None)

    for raw in source.split("\n"):
        text = raw.removesuffix("\r")
        protected = state in (BLOCK_COMMENT, DOUBLE_STRING, SINGLE_STRING)
        scanned = scan_editor_line(text, state)
        state = scanned.state
        code = scanned.masked_code(text).lstrip("\ufeff \t")
        level = depth()
        directive = next((s for s in scanned.spans if s.kind == "directive"), None)
        if directive is not None and code.startswith("#"):
            token = _DIRECTIVES[text[directive.start + 1:directive.end].lower()]
            if token == "KW_IF_COMPILE":
                conditions.append((blocks.copy(), delimiters.copy(), []))
            elif token in ("KW_ELSE_COMPILE", "KW_ELSEIF_COMPILE") and conditions:
                entry_blocks, entry_delimiters, ends = conditions[-1]
                ends.append((blocks.copy(), delimiters.copy()))
                blocks, delimiters = entry_blocks.copy(), entry_delimiters.copy()
                level = depth()
            elif token == "KW_ENDIF_COMPILE" and conditions:
                entry_blocks, entry_delimiters, ends = conditions.pop()
                current = (blocks.copy(), delimiters.copy())
                # Never carry a branch-specific unclosed block into other code.
                if ends and any(end != current for end in ends):
                    blocks, delimiters = entry_blocks, entry_delimiters
                level = max(entry_blocks[-1][1] + 1 if entry_blocks else 0,
                            entry_delimiters[-1][1] + 1 if entry_delimiters else 0)
            result.append(LineIndent(level, depth(), protected, True))
            continue

        tokens = [_KEYWORDS.get(word.lower(), word) for word in _TOKENS.findall(code)]
        structural = False
        if tokens:
            first = tokens[0]
            kind = _CLOSE.get(first) or _BRANCH.get(first)
            if not delimiters:
                kind = kind or {"KW_THEN": "if", "KW_DO": "loop"}.get(first)
            stack = blocks if kind else delimiters
            kind = kind or (first if first in _PAIRS.values() else None)
            match = matching(stack, kind)
            if match is not None:
                level = stack[match][1]
                structural = True

        statement_start = True
        for token in tokens:
            in_expression = any(close != "}" for close, _level in delimiters)
            if statement_start and token in _OPEN and not in_expression:
                blocks.append((_OPEN[token], depth()))
            elif statement_start and token in _CLOSE and not in_expression:
                match = matching(blocks, _CLOSE[token])
                if match is not None:
                    del blocks[match:]
            elif statement_start and token in _BRANCH and not in_expression:
                match = matching(blocks, _BRANCH[token])
                if match is not None:
                    del blocks[match + 1:]
            elif token in _PAIRS:
                delimiters.append((_PAIRS[token], level))
            elif token in _PAIRS.values():
                match = matching(delimiters, token)
                if match is not None:
                    del delimiters[match:]
            statement_start = token in {";", "KW_THEN", "KW_DO", "KW_ELSE", "KW_TRY", "KW_EXCEPT"}
        result.append(LineIndent(level, depth(), protected, structural))
    return result


def format_indentation(source: str, *, start_line: int = 0, end_line: int | None = None,
                       indent: str = "    ") -> str:
    """Change only leading code whitespace, preserving line endings/literals."""
    lines = source.split("\n")
    last = len(lines) - 1 if end_line is None else end_line
    for index, plan in enumerate(indentation_plan(source)):
        if not start_line <= index <= last or plan.protected:
            continue
        raw = lines[index]
        bom = "\ufeff" if index == 0 and raw.startswith("\ufeff") else ""
        content = raw[len(bom):].lstrip(" \t")
        if content.strip("\r"):
            lines[index] = bom + indent * plan.level + content
    return "\n".join(lines)
