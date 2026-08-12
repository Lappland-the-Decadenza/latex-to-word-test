# Tokenizer

import re

from ..common import (
    _DEF_MACROS, _GENFRAC, _RAW_ARG_MACROS, LatexParseError,
    MalformedArgumentError,
)

# --- Tokenizer -------------------------------------------------------------

# Whitespace carries no meaning in math mode (Rule 7), so it is dropped
# here: nothing downstream can accidentally depend on it.

_MACRO_RE = re.compile(r"\\(?:[a-zA-Z]+|.)", re.S)
_DIGITS_RE = re.compile(r"[0-9]+")


class _Token:
    __slots__ = ("kind", "text", "pos")

    def __init__(self, kind, text, pos):
        self.kind = kind
        self.text = text
        self.pos = pos

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"<{self.kind} {self.text!r} @{self.pos}>"


def _read_balanced_group(src, i):
    """Read `{...}` starting at `src[i] == '{'`; return (content, end_index)."""
    depth = 0
    j = i
    n = len(src)
    while j < n:
        c = src[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[i + 1:j], j + 1
        j += 1
    raise UnbalancedDelimiterError("unterminated group", src, i, "{")


def _defspec_end(macro, src, j):
    """End index of a Â§6.2 declaration starting at `src[j]` (just past the
    declaration macro). Scans only the *shape* -- `{name}[n]{body}` for the
    braced family, `\\name#1#2{body}` for `\\def` -- so the whole
    declaration becomes one raw `defspec` token; semantic validation
    (which shapes are inside the supported subset) lives in
    `compat/macros.py`. Raises a located `MalformedArgumentError` on a
    shape no declaration can have."""

    def ws(k):
        while k < len(src) and src[k].isspace():
            k += 1
        return k

    if macro == "\\def":
        k = ws(j)
        m = _MACRO_RE.match(src, k)
        if m is None or not m.group(0)[1:].isalpha():
            raise MalformedArgumentError("\\def without a macro name", src, j, macro)
        k = ws(m.end())
        while k < len(src) and src[k] == "#":
            if k + 1 >= len(src) or not src[k + 1].isdigit():
                raise MalformedArgumentError(
                    "\\def: parameters must be #1..#9", src, k, macro)
            k = ws(k + 2)
        if k >= len(src) or src[k] != "{":
            raise MalformedArgumentError("\\def without a body", src, j, macro)
        return _read_balanced_group(src, k)[1]

    k = ws(j)
    if macro == "\\DeclareMathOperator" and k < len(src) and src[k] == "*":
        raise MalformedArgumentError(
            "\\DeclareMathOperator* (limits form) is beyond the supported "
            "subset", src, k, macro)
    if k >= len(src) or src[k] != "{":
        raise MalformedArgumentError(
            f"{macro} without a braced macro name", src, j, macro)
    _, k = _read_balanced_group(src, k)
    while True:
        k = ws(k)
        if k >= len(src) or src[k] != "[":
            break
        j2 = src.find("]", k)
        if j2 < 0:
            raise MalformedArgumentError(
                f"{macro}: unterminated [argument count]", src, k, macro)
        k = j2 + 1
    if k >= len(src) or src[k] != "{":
        raise MalformedArgumentError(f"{macro} without a body", src, j, macro)
    return _read_balanced_group(src, k)[1]


def _append_genfrac(toks, src, start, pos):
    for _ in range(4):
        while pos < len(src) and src[pos].isspace():
            pos += 1
        if pos >= len(src) or src[pos] != "{":
            raise MalformedArgumentError(
                "\\genfrac without a braced parameter", src, start, _GENFRAC
            )
        content, pos = _read_balanced_group(src, pos)
        toks.append(_Token("rawarg", content, start))
    return pos


def tokenize(src):
    toks = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
            continue
        if c == "\\":
            m = _MACRO_RE.match(src, i)
            if m is None:
                raise LatexParseError("lone backslash at end of input", src, i, "\\")
            macro = m.group(0)
            j = m.end()
            if macro == "\\\\":
                toks.append(_Token("rowsep", macro, i))
                i = j
                continue
            if macro in ("\\begin", "\\end"):
                while j < n and src[j].isspace():
                    j += 1
                if j >= n or src[j] != "{":
                    raise MalformedArgumentError(
                        f"{macro} without an environment name", src, i, macro)
                name, j = _read_balanced_group(src, j)
                toks.append(_Token(macro[1:], name.strip(), i))
                i = j
                continue
            if macro == _GENFRAC:
                toks.append(_Token("macro", macro, i))
                i = _append_genfrac(toks, src, i, j)
                continue
            if macro in _RAW_ARG_MACROS:
                toks.append(_Token("macro", macro, i))
                while j < n and src[j].isspace():
                    j += 1
                if j >= n or src[j] != "{":
                    raise MalformedArgumentError(
                        f"{macro} without a braced argument", src, i, macro)
                content, j = _read_balanced_group(src, j)
                toks.append(_Token("rawarg", content, i))
                i = j
                continue
            if macro in _DEF_MACROS:
                # Â§6.2 user macros: the whole declaration is captured as one
                # raw token (never tokenized or expanded at declaration time
                # -- lazy, like TeX). `_defspec_end` scans only the shape;
                # semantic validation lives in compat/macros.py.
                end = _defspec_end(macro, src, j)
                toks.append(_Token("defspec", src[i:end], i))
                i = end
                continue
            toks.append(_Token("macro", macro, i))
            i = j
            continue
        if c == "{":
            toks.append(_Token("lbrace", c, i))
        elif c == "}":
            toks.append(_Token("rbrace", c, i))
        elif c == "_":
            toks.append(_Token("sub", c, i))
        elif c == "^":
            toks.append(_Token("sup", c, i))
        elif c == "'":
            toks.append(_Token("prime", c, i))
        elif c == "&":
            toks.append(_Token("amp", c, i))
        elif c.isdigit():
            m = _DIGITS_RE.match(src, i)
            toks.append(_Token("digits", m.group(0), i))
            i = m.end()
            continue
        else:
            toks.append(_Token("char", c, i))
        i += 1
    toks.append(_Token("eof", "", n))
    return toks




__all__ = [name for name in globals() if not name.startswith("__")]
