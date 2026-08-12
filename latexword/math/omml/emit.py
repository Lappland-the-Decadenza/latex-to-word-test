# AST to OMML emitter

from lxml import etree
from ..ast import (
    Accent, Bar, Boxed, CONSTRUCTS_BY_NAME, Delim, Frac, Func, GroupChr,
    Ident, Limit, Matrix, Nary, Num, Op, OpName, Phantom, PreScript, Rad,
    Row, Script, Space, Text, qm,
)

# --- R3: AST -> OMML --------------------------------------------------------
#
# `emit(ast) -> m:oMath` is the forward twin of `serialize`: same shape
# (dispatch on node type, recurse into children first, hand the *results* to
# the construct table's declared/callable `emit`), driven by
# `mathast.CONSTRUCTS_BY_NAME` rather than a hand-written per-node
# `if isinstance(...)` chain. `Row` is not itself emitted -- it flattens into
# however many sibling elements its items produce, exactly mirroring how it
# is not itself serialized either (`_ser_row` joins its items' text).


def emit_seq(node):
    """AST node -> the list of sibling OMML elements it becomes. A `Row`
    flattens (its items are direct siblings of whatever holds the row, same
    rule `Row`'s own docstring states); every other node is exactly one
    element."""
    if isinstance(node, Row):
        out = []
        for item in node.items:
            out.extend(emit_seq(item))
        return out
    return [_emit(node)]


def _opt_seq(node):
    return None if node is None else emit_seq(node)


# macro-name (no backslash) -> accent combining character, derived from
# CONSTRUCTS_BY_NAME["accent"].variants rather than re-imported from
# mathsyms directly, so it cannot drift from what the parser/serializer use
# for the same lookup.
_ACCENT_CHAR = {
    macro[1:]: props["chr"]
    for macro, props in CONSTRUCTS_BY_NAME["accent"].variants.items()
}

_EMIT = {
    Ident: lambda n: CONSTRUCTS_BY_NAME["ident"].emit(n.char),
    Num: lambda n: CONSTRUCTS_BY_NAME["num"].emit(n.text),
    Op: lambda n: CONSTRUCTS_BY_NAME["op"].emit(n.char),
    Text: lambda n: CONSTRUCTS_BY_NAME["text"].emit(n.s),
    OpName: lambda n: CONSTRUCTS_BY_NAME["opname"].emit(n.name),
    Space: lambda n: CONSTRUCTS_BY_NAME["space"].emit(n.width),
    Script: lambda n: CONSTRUCTS_BY_NAME["script"].emit(
        emit_seq(n.base), _opt_seq(n.sub), _opt_seq(n.sup)),
    PreScript: lambda n: CONSTRUCTS_BY_NAME["prescript"].emit(
        emit_seq(n.sub), emit_seq(n.sup), emit_seq(n.base)),
    Frac: lambda n: CONSTRUCTS_BY_NAME["frac"].emit(
        emit_seq(n.num), emit_seq(n.den), n.kind, n.paren),
    Rad: lambda n: CONSTRUCTS_BY_NAME["rad"].emit(
        _opt_seq(n.degree), emit_seq(n.radicand)),
    Nary: lambda n: CONSTRUCTS_BY_NAME["nary"].emit(
        _opt_seq(n.sub), _opt_seq(n.sup), emit_seq(n.body), n.op, n.limits),
    Delim: lambda n: CONSTRUCTS_BY_NAME["delim"].emit(
        [emit_seq(item) for item in n.items], n.open, n.close),
    Func: lambda n: CONSTRUCTS_BY_NAME["func"].emit(
        emit_seq(n.name), emit_seq(n.arg)),
    Accent: lambda n: CONSTRUCTS_BY_NAME["accent"].emit(
        emit_seq(n.base), _ACCENT_CHAR[n.mark]),
    Bar: lambda n: CONSTRUCTS_BY_NAME["bar"].emit(emit_seq(n.base), n.pos),
    Limit: lambda n: CONSTRUCTS_BY_NAME["limit"].emit(
        emit_seq(n.base), emit_seq(n.lim), n.pos),
    GroupChr: lambda n: CONSTRUCTS_BY_NAME["groupchr"].emit(
        emit_seq(n.base), n.chr, n.pos),
    Boxed: lambda n: CONSTRUCTS_BY_NAME["boxed"].emit(emit_seq(n.base)),
    Phantom: lambda n: CONSTRUCTS_BY_NAME["phantom"].emit(emit_seq(n.base)),
    Matrix: lambda n: CONSTRUCTS_BY_NAME["matrix"].emit(
        [[emit_seq(cell) for cell in row] for row in n.rows], n.env, n.cols),
}


def _emit(node):
    fn = _EMIT.get(type(node))
    if fn is None:  # pragma: no cover - _EMIT covers every non-Row node type
        raise TypeError(f"no emitter for AST node {type(node).__name__}")
    return fn(node)


def emit(node):
    """AST -> `m:oMath`. The R3 twin of `parse`: `word2latex.to_latex(emit(x))
    == serialize(x)` is Rule 0 turned into an executable property (see
    `tests/test_r3_emitter.py`). Wrapping in `m:oMathPara` for display math is
    a document-layer decision (inline vs. block), out of scope here per
    `REWRITE_FORWARD.md` -- that is `latex2word.py`'s job at R4."""
    om = etree.Element(qm("oMath"))
    for el in emit_seq(node):
        om.append(el)
    return om


__all__ = [name for name in globals() if not name.startswith("__")]
