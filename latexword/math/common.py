# Shared vocabulary and derived lookups.

import re
from typing import Optional

from lxml import etree

from .ast import (
    Accent, Bar, Boxed, Delim, Frac, Func, GroupChr, Ident, Limit, Matrix,
    Nary, Num, Op, OpName, Phantom, PreScript, Rad, Row, Script, Space, Text,
    CONSTRUCTS_BY_NAME, MACRO_TO_CONSTRUCT, qm,
)
from ..mathsyms import (
    CLOSE_CHARS,
    DELIM_LEFTRIGHT,
    DELIM_SPELLING_TO_CHAR,
    KNOWN_FUNC_MACROS,
    LIMIT_OPS,
    MACRO_TO_CHAR,
    NARY_BODY_BINARY_CHARS,
    NARY_BODY_RELATION_CHARS,
    NARY_UNDOVR,
    NBSP_CHAR,
    OPEN_CHARS,
    SYMBOL_MAP,
    TEXT_ESCAPE_TO_CHAR,
    VARIANT_REVERSE,
    _VARIANT_BASES,
    _VARIANT_HOLES,
)
from ..compat.tolerated import (
    TOLERATED as _TOLERATED,
    TOLERATED_WITH_ARG as _TOLERATED_WITH_ARG,
    STYLE_NOOPS as _STYLE_NOOPS,
)
from ..compat.macros import (
    MacroDefinitionError,
    MacroEnv,
    _MAX_EXPANSION_DEPTH,
    substitute as _macro_substitute,
)


# --- Errors ---------------------------------------------------------------


class LatexParseError(Exception):
    """Base of every parse/validation failure. Always carries the source
    position and the offending token, so a corpus run can group failures by
    cause instead of reporting "it didn't work"."""

    def __init__(self, message, source="", pos=0, token=""):
        self.message = message
        self.source = source
        self.pos = pos
        self.token = token
        context = source[max(0, pos - 25):pos + 25].replace("\n", " ")
        super().__init__(
            f"{message} (at offset {pos}, token {token!r}) ... {context!r}"
        )


class UnknownMacroError(LatexParseError):
    """A macro outside the declared vocabulary. Rule 15: a validation
    error, not a guess."""


class UnsupportedConstructError(LatexParseError):
    """A macro/environment we recognise but that has no representation in
    the Rule 0 target inventory. Distinguished from `UnknownMacroError` so a
    corpus report can tell "we never heard of this" from "we know this and
    deliberately cannot express it"."""


class UnbalancedDelimiterError(LatexParseError):
    """A `\\left` with no `\\right`, a bare `(` with no `)`, a `{` with no
    `}`, or a closer with no opener."""


class MalformedArgumentError(LatexParseError):
    """A macro whose argument list is missing, truncated or doubled (`x^1^2`)."""


class UnexpectedTokenError(LatexParseError):
    """A token that is syntactically fine elsewhere but not here -- `&` or
    `\\\\` outside a multi-row environment, `\\right` with no `\\left`."""


# --- Facts that could not be driven from mathast.MACRO_TO_CONSTRUCT -------
#
# Every entry here is a place where the construct table did not carry the
# fact the parser needed. Kept as one auditable list rather than scattered
# comments: a listed special case is a decision, a hidden one is drift.

_TABLE_GAPS = {
    "\\operatorname": (
        "CANONICAL.md Rule 2 names \\operatorname{name} as the canonical "
        "spelling for any operator outside the standard list, but the "
        "`opname` construct's `variants` is derived from "
        "mathsyms.KNOWN_FUNC_MACROS, which holds only the standard macros. "
        "\\operatorname itself is in no table."
    ),
    "variant fonts": (
        "CANONICAL.md Rule 10 (\\mathbf/\\mathcal/\\mathbb/...) has no AST "
        "node and no construct-table entry: variants are carried in the "
        "*character* (mathsyms._VARIANT_BASES -> Unicode Mathematical "
        "Alphanumerics), so macro -> variant-name is declared here."
    ),
    "spelling aliases": (
        "Rule 8 says the canonicalizer rewrites alternate spellings of one "
        "glyph to the canonical macro, but no forward alias table exists "
        "(mathsyms.SYMBOL_MAP is reverse-only)."
    ),
    "non-canonical environments": (
        "Rule 5 lists which multi-row environments collapse to matrix; that "
        "list is prose in CANONICAL.md and appears in no table."
    ),
}


# --- Vocabulary declared here, with its reason -----------------------------

# Rule 2's other half (see _TABLE_GAPS).
_OPERATORNAME = "\\operatorname"

# The n-ary `limLoc` override modifiers (see CANONICAL.md's n-ary rule and
# mathast.Nary.limits). Legal in exactly one position -- directly after an
# n-ary operator token, before any scripts -- so they are consumed inline by
# `_h_nary` rather than dispatched through `MACRO_TO_CONSTRUCT`; encountering
# either one anywhere else falls through to `parse_macro`'s explicit check
# below and is a located `UnexpectedTokenError`, not a silent drop or an
# `UnknownMacroError` (they are known macros, just misplaced).
_NARY_LIMITS_MODIFIER = "\\limits"
_NARY_NOLIMITS_MODIFIER = "\\nolimits"

# Macros whose single mandatory argument is *not* math and must be captured
# verbatim by the tokenizer rather than parsed (`\text` switches to text
# mode; `\operatorname`'s argument is a literal name; `\mathrm`'s argument is
# likewise a literal upright name -- see the `\mathrm` handling below).
_MATHRM = "\\mathrm"
_RAW_ARG_MACROS = {"\\text", _OPERATORNAME, _MATHRM,
                   "\\label", "\\hspace",  # Â§6.2 tolerated, braced arg
                   "\\ensuremath"}  # Â§6.2 user macros: expands to its arg

# Â§6.2 user macros (latexword/compat/macros.py): the declaration family.
# The tokenizer captures each declaration whole as one `defspec` token;
# `tokenize_with_macros` consumes them and expands defined macros, so the
# parser never sees either.
_GENFRAC = "\\genfrac"
_SFRAC = "\\sfrac"

_DEF_MACROS = {
    "\\newcommand", "\\renewcommand", "\\def", "\\DeclareMathOperator",
}

# One scan for the whole macro family, used by the tokenize_with_macros
# fast path (five separate `in` scans per equation measurably cost more
# than the pass they skip).
_DEFS_RE = re.compile(r"\\(?:newcommand|renewcommand|def|"
                      r"DeclareMathOperator|ensuremath)\b")

# Rule 10. macro -> `mathsyms._VARIANT_BASES` variant name.
_VARIANT_MACROS = {
    "\\mathbf": "bold",
    "\\mathit": "italic",
    "\\mathcal": "script",
    "\\mathscr": "script",
    "\\mathfrak": "fraktur",
    "\\mathbb": "double-struck",
    "\\mathsf": "sans-serif",
    "\\mathtt": "monospace",
    "\\boldsymbol": "bold-italic",
    "\\bm": "bold-italic",
}

# Serialization side of Rule 10: one macro per variant where LaTeX has one,
# nesting for the compound variants (Rule 10 calls that a known lossy point,
# not a defect). Mirrors word2latex.VARIANT_MACRO/VARIANT_COMPOUND.
_VARIANT_SPELLING = {
    "bold": ("mathbf",),
    "italic": ("mathit",),
    "script": ("mathcal",),
    "fraktur": ("mathfrak",),
    "double-struck": ("mathbb",),
    "sans-serif": ("mathsf",),
    "monospace": ("mathtt",),
    "bold-italic": ("boldsymbol",),
    "bold-script": ("boldsymbol", "mathcal"),
    "bold-fraktur": ("boldsymbol", "mathfrak"),
    "bold-sans-serif": ("boldsymbol", "mathsf"),
    "sans-serif-italic": ("mathsf",),
    "sans-serif-bold-italic": ("boldsymbol", "mathsf"),
}

# Nesting one variant macro inside another (`\boldsymbol{\mathcal{L}}`).
_VARIANT_COMBINE = {
    ("script", "bold"): "bold-script",
    ("fraktur", "bold"): "bold-fraktur",
    ("sans-serif", "bold"): "bold-sans-serif",
    ("sans-serif", "italic"): "sans-serif-italic",
    ("italic", "bold"): "bold-italic",
    ("bold", "italic"): "bold-italic",
}

# Rule 8: alternate spellings of a glyph the canon already names. The
# canonical macro is whichever one mathsyms.SYMBOL_MAP maps that codepoint
# back to, so rewriting here is what makes serialize(parse(x)) a projection.
_MACRO_ALIASES = {
    "\\rightarrow": "\\to",
    "\\longrightarrow": "\\to",
    "\\le": "\\leq",
    "\\ge": "\\geq",
    "\\implies": "\\Rightarrow",
    "\\ne": "\\neq",
    "\\land": "\\wedge",
    "\\lor": "\\vee",
    "\\lnot": "\\neg",
    "\\varnothing": "\\emptyset",
    "\\dots": "\\ldots",
    "\\lbrace": "\\{",
    "\\rbrace": "\\}",
    "\\vert": "|",
    "\\Vert": "\\|",
}

# Â§6.2 fixed-size delimiters: `\bigl( x \bigr)` parses as a `\left`-class
# group and serializes canonically as `\left( x \right)` -- the size is
# deliberately not carried (L*: "the serializer learns none of it").
# `\big`/`\Big`/`\bigg`/`\Bigg` are ambiguous: the delimiter character that
# follows them decides whether they open (`\big(`) or close (`\big)`).
# `\middle` is a plain sized-bar spelling of the separator: the loader
# reads an `m:d`'s separator as an ordinary `Op` in the content row, so
# the canonical form of `\left\{ x \middle| y \right\}` is
# `\left\{ x | y \right\}` and no separator machinery is needed.
_BIG_SIZERS = {"\\big", "\\Big", "\\bigg", "\\Bigg",
               "\\bigl", "\\Bigl", "\\biggl", "\\Biggl"}
_BIG_CLOSER_ONLY = {"\\bigr", "\\Bigr", "\\biggr", "\\Biggr"}

# Rule 5: undelimited multi-row environments that are not in L* and
# canonicalize to `matrix` -- an undelimited `m:m` carries nothing that
# distinguishes an aligned equation system from a plain matrix, so exactly
# one spelling can be canonical, and `matrix` is it (what `word2latex.py`'s
# `_matrix_to_latex` has always actually produced for this shape; see
# `mathast.Matrix`'s docstring and CANONICAL.md Rule 5). `align*` is an
# input alias like every other name here, not the fold target.
_ENV_ALIASES = {
    "align": "matrix", "align*": "matrix", "aligned": "matrix",
    "gather": "matrix", "gather*": "matrix", "gathered": "matrix",
    "eqnarray": "matrix", "eqnarray*": "matrix", "multline": "matrix",
    "multline*": "matrix", "split": "matrix", "alignat": "matrix",
    "alignat*": "matrix", "flalign": "matrix", "flalign*": "matrix",
}

# Recognised but not representable in the Rule 0 inventory -> a loud
# UnsupportedConstructError rather than a quiet approximation.
#
# \mathrm is NOT in this table (any more): upright math styling *is*
# representable -- `m:rPr/m:sty val="p"` is exactly the run property
# `CONSTRUCTS["opname"]` already emits for `\sin`/`\operatorname{...}`, so
# `\mathrm{abc}` reuses that same OMML shape (see `_h_mathrm` below and
# `mathast.OpName.is_mathrm`) instead of being rejected. This closes the
# "`\mathrm{d}` loses its upright styling" entry in CLAUDE.md's known
# limitations.
_UNSUPPORTED = {
    # `\!` was here (negative width, no Unicode glyph) until Â§6.2 moved it
    # to compat/tolerated.py: the width is dropped *with a named warning*,
    # and a whole-equation fallback was the wrong punishment for a
    # typographic nicety (measured 10 times on the .tex corpus).
    "\\substack": "no element in the Rule 0 target inventory represents \\substack",
    "\\atop": "no element in the Rule 0 target inventory represents \\atop",
    "\\over": "no element in the Rule 0 target inventory represents \\over",
}

# ASCII characters allowed as literal math content. Anything else ASCII is a
# validation error rather than a pass-through (Rule 15).
_ASCII_CONTENT = set("+-=<>/:;,.!?*|()[]abcdefghijklmnopqrstuvwxyz"
                     "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")

# LaTeX-escaped literals: `\%` etc. are the character, not a macro.
_ESCAPED_LITERALS = {
    "\\%": "%", "\\#": "#", "\\&": "&", "\\$": "$", "\\_": "_",
}

PRIME = "\u2032"


# --- Derived lookups -------------------------------------------------------
#
# The forward lookups are the registry's generated inverses (PLAN.md Â§5.2):
# `mathsyms.MACRO_TO_CHAR` (macro -> canonical codepoint, the aliases
# deliberately excluded) and `mathsyms.DELIM_SPELLING_TO_CHAR` (spelling ->
# canonical character). Before the registry these were first-wins inversions
# of the reverse tables, with the winner picked by insertion order; the
# registry declares the winner at each collision site instead.

_DELIM_CONSTRUCT = CONSTRUCTS_BY_NAME["delim"]
# Opening spellings that may also appear *bare* (no \left) and be paired by
# nesting. Derived from the construct table: a pair whose open and close
# characters differ is unambiguous, so it can be matched positionally. `|`
# and `\|` are their own closers, so a bare one cannot be classified without
# a heuristic -- Rule 0 forbids that, and they stay ordinary `Op` glyphs
# unless written with \left/\right.
_BARE_PAIRS = {
    spelling: DELIM_LEFTRIGHT[props["endChr"]]
    for spelling, props in _DELIM_CONSTRUCT.variants.items()
    if props["begChr"] is not None and props["begChr"] != props["endChr"]
}
_BARE_CLOSERS = set(_BARE_PAIRS.values())

_MATRIX_CONSTRUCT = CONSTRUCTS_BY_NAME["matrix"]
_MATRIX_ENVS = set(_MATRIX_CONSTRUCT.variants)

# The `delim` construct's parse-time responsibility mathast.Matrix's
# docstring names but nothing before R3 implemented: a delimiter pair whose
# sole content is a matrix environment must fold into the matching
# pmatrix-family environment (Rule 5) instead of producing Delim(Matrix).
# OMML carries no environment name -- math.load._load_delim already folds
# any sole `m:m` inside `m:d` this way, by delimiter characters alone -- so
# the parser must do the same regardless of which environment (`align*`,
# aliased by Rule 5 to `matrix`, or any other) produced the inner Matrix
# node, or the round-trip property fails on exactly this shape.
_ENV_FOR_DELIM_CHARS = {
    (props["begChr"], props["endChr"]): env
    for env, props in _MATRIX_CONSTRUCT.variants.items()
    if props["begChr"] is not None and props["endChr"] is not None
}


def _fold_delim_matrix(open_ch, close_ch, row):
    """`None` if the delimiter pair does not wrap a sole matrix environment
    (the ordinary case); otherwise the `Matrix` to use *instead of* wrapping
    `row` in a `Delim` -- the delimiter's own characters pick the env.

    A genuine `array` column spec (CANONICAL.md Rule 5a: at least one
    column not `center`) has nowhere to live on `pmatrix`/`bmatrix`/... --
    those environments carry no per-column justification at all -- so
    folding it in would silently drop the spec (clause 3 of the Phase 0
    goal: never mutate content silently). `\\left(\\begin{array}{rl}...
    \\end{array}\\right)` is kept explicit instead in that case. An
    all-`center` `cols` (or no `cols` at all) carries nothing Rule 5a needs
    recorded, so it still folds -- matching `_emit_matrix`'s own "only a
    genuine non-centre column switches shape" discipline."""
    if len(row.items) != 1 or not isinstance(row.items[0], Matrix):
        return None
    inner = row.items[0]
    if inner.cols is not None and any(c != "c" for c in inner.cols):
        return None
    env = _ENV_FOR_DELIM_CHARS.get((open_ch, close_ch))
    if env is None:
        return None
    return Matrix(inner.rows, env)

_SPACE_CONSTRUCT = CONSTRUCTS_BY_NAME["space"]
_SPACE_SPELLING = {
    props["width"]: macro for macro, props in _SPACE_CONSTRUCT.variants.items()
}

# \pmod{n} sugar (see _h_pmod): the widths mathml_normalize.fix_spaces
# documents as \pmod's own built-in gaps -- EM (\quad's width) before the
# parenthesis, FOUR_PER_EM (\:'s width) between "mod" and its argument --
# rather than invented values, so the expansion matches what the still-live
# old pipeline already produces for the same source.
_PMOD_OUTER_WIDTH = _SPACE_CONSTRUCT.variants["\\quad"]["width"]
_PMOD_INNER_WIDTH = _SPACE_CONSTRUCT.variants["\\:"]["width"]

_NARY_CONSTRUCT = CONSTRUCTS_BY_NAME["nary"]

# Rule 10 forward direction: (plain character, variant) -> variant character.
_VARIANT_CHAR = {}
for _variant, (_uc, _lc, _dg) in _VARIANT_BASES.items():
    for _i in range(26):
        if _uc:
            _VARIANT_CHAR[(chr(ord("A") + _i), _variant)] = chr(_uc + _i)
        if _lc:
            _VARIANT_CHAR[(chr(ord("a") + _i), _variant)] = chr(_lc + _i)
    if _dg:
        for _i in range(10):
            _VARIANT_CHAR[(chr(ord("0") + _i), _variant)] = chr(_dg + _i)
for _variant, _holes in _VARIANT_HOLES.items():
    for _base, _chv in _holes.items():
        _VARIANT_CHAR[(_base, _variant)] = _chv




__all__ = [name for name in globals() if not name.startswith("__")]
