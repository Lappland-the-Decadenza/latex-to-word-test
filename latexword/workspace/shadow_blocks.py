"""Lexical, recoverable block boundaries for the AI editing surface."""

from __future__ import annotations

import re
from dataclasses import dataclass


_LABEL = re.compile(r"[ \t]*%lw:(?P<kind>[A-Za-z][\w-]*):(?P<label>\d+)[ \t]*(?:\r?\n|$)")
_TOKEN = re.compile(r"\\(?:begin|end)\s*\{([^{}]+)\}")
_HEADING = re.compile(r"\\(?:part|chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?\s*\{")
_ANY_LABEL = re.compile(r"%lw:(?P<kind>[A-Za-z][\w-]*):(?P<label>\d+)")


@dataclass(frozen=True, slots=True)
class BlockWarning:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ShadowBlock:
    label: int | None
    kind: str
    latex: str
    start: int
    end: int
    warnings: tuple[BlockWarning, ...] = ()


class ShadowMetadataError(ValueError):
    """The shadow contains invalid program-owned label metadata."""


def _document_body(source):
    match = re.search(r"\\begin\s*\{document\}", source)
    if not match:
        return 0, len(source)
    end = source.rfind(r"\end{document}")
    return match.end(), len(source) if end < match.end() else end


def _balanced_brace(source, opening):
    depth = 0
    escaped = False
    for index in range(opening, len(source)):
        char = source[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1, None
    return len(source), "unbalanced braces"


def _environment_end(source, start, limit):
    opening = re.match(r"\\begin\s*\{([^{}]+)\}", source[start:limit])
    if not opening:
        return start, None
    stack = [opening.group(1)]
    cursor = start + opening.end()
    while cursor < limit:
        token = _TOKEN.search(source, cursor, limit)
        if token is None:
            return limit, "unterminated environment " + stack[-1]
        name = token.group(1)
        if token.group(0).startswith(r"\begin"):
            stack.append(name)
        elif stack[-1] == name:
            stack.pop()
            if not stack:
                return token.end(), None
        else:
            return token.end(), f"mismatched environment end {name}"
        cursor = token.end()
    return limit, "unterminated environment " + stack[-1]


def _paragraph_end(source, start, limit):
    next_label = re.search(r"(?m)^[ \t]*%lw:", source[start + 1:limit])
    label_end = start + 1 + next_label.start() if next_label else limit
    cursor = start
    depth = 0
    escaped = False
    while cursor < label_end:
        if source[cursor] == "\\" and not escaped:
            escaped = True
            cursor += 1
            continue
        if escaped:
            escaped = False
            cursor += 1
            continue
        char = source[cursor]
        if char == "{":
            depth += 1
        elif char == "}" and depth:
            depth -= 1
        if depth == 0 and source[cursor] == "\n":
            following = re.match(r"[ \t]*\n", source[cursor + 1:limit])
            if following:
                return cursor + 1, None
        cursor += 1
    return label_end, "unbalanced braces" if depth else None


def _recover_end(source, start, limit):
    match = re.search(r"\n[ \t]*\n", source[start + 1:limit])
    return start + 1 + match.start() + 1 if match else limit


def _kind(source, start):
    if _HEADING.match(source, start):
        return "heading"
    environment = re.match(r"\\begin\s*\{([^{}]+)\}", source[start:])
    if environment:
        name = environment.group(1).rstrip("*")
        if name in {"itemize", "enumerate", "description"}:
            return "list"
        if name in {"tabular", "table"}:
            return "table"
        if name in {"figure"}:
            return "figure"
        if name in {"equation", "displaymath", "align", "gather"}:
            return "equation"
    if source.startswith((r"\[", "$$"), start):
        return "equation"
    if r"\includegraphics" in source[start:start + 160]:
        return "figure"
    return "p"


def read_shadow_blocks(source: str) -> tuple[ShadowBlock, ...]:
    """Find blocks without requiring successful AST parsing."""

    body_start, body_end = _document_body(source)
    blocks = []
    cursor = body_start
    pending = None
    while cursor < body_end:
        whitespace = re.match(r"\s*", source[cursor:body_end])
        cursor += whitespace.end()
        if cursor >= body_end:
            break
        label_match = _LABEL.match(source, cursor, body_end)
        if label_match:
            if pending is not None:
                raise ShadowMetadataError("label is not followed by a block")
            pending = (label_match.group("kind"), int(label_match.group("label")))
            cursor = label_match.end()
            continue
        structural = re.match(
            r"\\(?:begin\s*\{multicols\*?\}(?:\s*\{[^{}]*\})?|end\s*\{multicols\*?\})",
            source[cursor:body_end],
        )
        if structural:
            cursor += structural.end()
            continue
        start = cursor
        warnings = []
        if source.startswith(r"\begin", start):
            end, warning = _environment_end(source, start, body_end)
            if warning and end == body_end:
                end = _recover_end(source, start, body_end)
        elif source.startswith(r"\[", start):
            close = source.find(r"\]", start + 2, body_end)
            if close < 0:
                end = _recover_end(source, start, body_end)
                warning = "unterminated display math"
            else:
                end, warning = close + 2, None
        elif source.startswith("$$", start):
            close = source.find("$$", start + 2, body_end)
            if close < 0:
                end = _recover_end(source, start, body_end)
                warning = "unterminated display math"
            else:
                end, warning = close + 2, None
        elif _HEADING.match(source, start):
            opening = source.find("{", start)
            end, warning = _balanced_brace(source, opening)
        else:
            end, warning = _paragraph_end(source, start, body_end)
        if warning:
            warnings.append(BlockWarning("malformed-shadow", warning))
        raw = source[start:end].strip()
        if not raw:
            cursor = max(end, start + 1)
            continue
        kind = _kind(source, start)
        if pending is not None:
            label_kind, label = pending
            if label_kind not in {kind, "p" if kind == "heading" else kind}:
                warnings.append(BlockWarning("label-kind-mismatch", f"{label_kind} before {kind}"))
            pending = None
        else:
            label = None
        blocks.append(ShadowBlock(label, kind, raw, start, end, tuple(warnings)))
        cursor = max(end, start + 1)
    if pending is not None:
        raise ShadowMetadataError(f"label has no following block: {pending}")
    labels = [block.label for block in blocks if block.label is not None]
    if len(labels) != len(set(labels)):
        raise ShadowMetadataError("duplicate block label")
    return tuple(blocks)


def typed_labels(source: str):
    """Return every typed comment, including list-item comments."""

    return tuple((item.group("kind"), int(item.group("label"))) for item in _ANY_LABEL.finditer(source))


__all__ = ["BlockWarning", "ShadowBlock", "ShadowMetadataError", "read_shadow_blocks", "typed_labels"]
