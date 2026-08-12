"""Shared OMML loader imports and XML helpers."""

import re
from lxml import etree
from .. import ast
from ..ast import Accent, Bar, Boxed, Delim, Frac, Func, GroupChr, Ident, Limit, Matrix, Nary, Num, Op, OpName, Phantom, PreScript, Rad, Row, Script, Space, Text
from ..common import PRIME
from ...mathsyms import (
    ACCENT_REVERSE, ACCENT_REVERSE_ALIASES, CONTROL_SPACE_CHAR,
    DELIM_LEFTRIGHT, KNOWN_FUNC_MACROS, NARY_UNDOVR,
    SPACE_CHAR_ALIASES, SPACE_CHARS, SPACE_TO_LATEX, SYMBOL_MAP,
    VARIANT_REVERSE, _COMPOUND_PRIMES,
)

M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

def qm(tag):
    return f"{{{M}}}{tag}"


def qw(tag):
    return f"{{{W}}}{tag}"


def ln(el):
    return etree.QName(el).localname


# --- Small XML helpers ------------------------------------------------------


def _find(el, name):
    return el.find(qm(name))


def _attr(el, name, default=None):
    if el is None:
        return default
    v = el.get(qm(name))
    return v if v is not None else default


def _children(el):
    """`el`'s content as nodes, empty results dropped (the old walker's
    `_conv` joined empty conversions to "")."""
    out = []
    for c in el:
        node = load(c)
        if node is not None:
            out.append(node)
    return out


def _row_or_single(el):
    """A slot's content as one node: the single child itself, a `Row` of
    several, or `None` when the slot is empty or absent."""
    items = _children(el)
    if not items:
        return None
    if len(items) == 1:
        return items[0]
    return Row(tuple(items))


def _arg(el, name):
    """The named slot as a node (`None` when empty/absent)."""
    slot = _find(el, name)
    return _row_or_single(slot) if slot is not None else None


__all__ = [name for name in globals() if not name.startswith("__")]


# --- Run conversion: m:r -> leaf nodes --------------------------------------
#
# Mirrors the old walker's `_convert_run` exactly, producing nodes: the
# sty="p" two-stage logic (whole-run known name / \mathrm, then the
# mixed-run segmentation), the `m:nor` literal-text path, the space-run
# fast path, and the character-level scan (literal text, primes, spaces,
# variants, symbols, escapes).

# ASCII characters that are LaTeX-special even inside math mode.
_ASCII_MATH_ESCAPES = {
    "%": "\\%", "#": "\\#", "&": "\\&", "$": "\\$",
    "_": "\\_", "{": "\\{", "}": "\\}",
}

_GREEK_BLOCK = range(0x0370, 0x0400)
