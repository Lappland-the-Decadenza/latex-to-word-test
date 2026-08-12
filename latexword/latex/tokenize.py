"""Lexical layer for the closed native document grammar."""

from __future__ import annotations

from dataclasses import dataclass
import re


_COMMAND = re.compile(r"\\(?:[A-Za-z]+|.)")


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    value: str
    start: int
    end: int


def tokenize(source: str) -> tuple[Token, ...]:
    """Tokenize document syntax while retaining exact source positions."""
    tokens = []
    i = 0
    text_start = 0
    while i < len(source):
        if source[i] not in "\\{}[]$%":
            i += 1
            continue
        if text_start < i:
            tokens.append(Token("text", source[text_start:i], text_start, i))
        if source[i] == "%":
            end = source.find("\n", i)
            end = len(source) if end < 0 else end
            tokens.append(Token("comment", source[i:end], i, end))
            i = end
        elif source[i] == "\\":
            match = _COMMAND.match(source, i)
            if match is None:
                tokens.append(Token("text", source[i], i, i + 1))
                i += 1
            else:
                value = match.group(0)
                kind = "break" if value == r"\\" else "command"
                tokens.append(Token(kind, value, i, match.end()))
                i = match.end()
        else:
            tokens.append(Token(source[i], source[i], i, i + 1))
            i += 1
        text_start = i
    if text_start < len(source):
        tokens.append(Token("text", source[text_start:], text_start, len(source)))
    return tuple(tokens)


__all__ = ["Token", "tokenize"]
