"""The AST node types and the construct table: the single source of
*structural* truth, as `mathsyms.py` is for character-level truth.

Today a fact like "\\frac{a}{b} is m:f with children [num, den]" is written
down twice -- once in the (soon-to-be-deleted) forward pipeline
(`mathml_normalize.py` + Microsoft's `MML2OMML.XSL`) and once by hand in
`word2latex.py`'s reverse walker -- and the two can drift apart independently.
This module ends that: each construct's LaTeX spelling, AST node, OMML
element, that element's properties and its ordered child slots are declared
exactly once, in `CONSTRUCTS` below. `latex2omml.py` (R2b/R3, not yet
written) and a rewritten `word2latex.py` (R5) are both meant to be *driven*
by this table rather than hand-writing the same facts a second time.

Scope of this module, precisely: **AST node types and the construct table
only.** No tokenizer, no parser, no OMML emitter -- those are R2b and R3
(see `REWRITE_FORWARD.md`). Where a construct needs real algorithmic logic
(matrices, n-ary operators with optional limits, the legacy brace-glyph
`limLow`/`limUpp` shape), its `parse`/`emit` slot is a named callable that
is a deliberate stub here -- present so the table is structurally complete
and self-validates, but raising `NotImplementedError` until the stage that
owns the algorithm lands. A stub is not an emitter: it carries no behaviour,
only the declaration of which stage will supply it.

`CANONICAL.md` is the specification this table implements; where a
construct's canonical LaTeX spelling was unclear, the existing, tested
`word2latex.py` reverse walker was read as the reference for OMML element
names, property attributes and slot order (per `REWRITE_FORWARD.md`,
"source your facts from the existing reverse walker" -- it is the reference
until R4 lands).

This module imports from `mathsyms.py` and nothing else in the project.
"""

from dataclasses import dataclass, field
from typing import Callable, Optional, Tuple, Union

from lxml import etree

from ..mathsyms import (
    ACCENT_TO_CHAR,
    DELIM_LEFTRIGHT,
    KNOWN_FUNC_MACROS,
    NARY_MACROS,
    NARY_UNDOVR,
    SPACE_MACRO_TO_GLYPH,
    SPACE_TO_LATEX,
    TEXT_CHAR_TO_ESCAPE,
)


# --- R3 OMML-building helpers -------------------------------------------
#
# `lxml` is a third-party library, not "the rest of the project" (the module
# docstring's import restriction is about this project's own modules, to
# keep character-level/structural truth from leaking into each other -- it
# is not a ban on the generic XML library every OMML-producing module in
# this project already depends on). Each construct's `emit` callable below
# takes already-emitted child elements (or lists of them, for slots that can
# hold more than one -- a `Row` flattens to several) plus the construct's own
# scalar properties, and returns the one `lxml.etree.Element` for *this*
# construct. Recursion into children is the driver's job
# (`latex2omml.emit_seq`), exactly mirroring how `serialize`'s callables
# receive already-serialized child strings rather than doing the recursion
# themselves.

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def qm(tag):
    return f"{{{M_NS}}}{tag}"


def _mk(tag, *attrs_and_children):
    """Build one element: leading (name, value) pairs become m:-namespaced
    attributes, anything else (an Element or None) is appended as a child."""
    el = etree.Element(qm(tag))
    for item in attrs_and_children:
        if item is None:
            continue
        if isinstance(item, tuple):
            name, value = item
            el.set(qm(name), value)
        else:
            el.append(item)
    return el


def _pr_flag(tag):
    """A boolean property element (`<m:nor/>`) -- presence is the value."""
    return etree.Element(qm(tag))


def _pr_val(tag, val):
    """A valued property element (`<m:sty m:val="p"/>`)."""
    return _mk(tag, ("val", str(val)))


def _pr(container_tag, *entries):
    """`<m:xPr>` wrapping the given property elements; `None` entries are
    skipped, and the whole container is omitted (returns `None`) if nothing
    is left -- an empty `<m:fPr/>` is noise no reader needs."""
    kids = [e for e in entries if e is not None]
    if not kids:
        return None
    pr = etree.Element(qm(container_tag))
    for k in kids:
        pr.append(k)
    return pr


def _run(text, *pr_entries):
    """Every leaf primitive (Ident/Num/Op/Text/OpName/Space) is plain
    `m:r`/`m:t`, distinguished only by an optional `m:rPr` -- this is the one
    shape shared by all of them (Rule 0's `r`+`t`)."""
    t = etree.Element(qm("t"))
    t.text = text
    return _mk("r", _pr("rPr", *pr_entries), t)


def _slot(tag, elements):
    """Wrap already-emitted sibling elements in one OMML argument container
    (`m:e`, `m:num`, `m:sub`, `m:lim`, `m:fName`, `m:deg`, ...)."""
    s = etree.Element(qm(tag))
    for el in elements:
        s.append(el)
    return s


def _build(tag, pr, *slots):
    """A structural element: optional property container, then its slots in
    declared order. A `(name, elements)` pair with `elements is None` is
    skipped entirely (an absent optional slot, not an empty one --
    `Rad`/`Nary`'s hidden-but-present slots go through `_emit_rad`/
    `_emit_nary` instead, which need the slot present even when hidden)."""
    el = _mk(tag, pr)
    for name, elements in slots:
        if elements is None:
            continue
        el.append(_slot(name, elements))
    return el


# Quad-width space character, needed to spell `\qquad` as two consecutive
# quad glyphs (math.load's `_load_run` recognises the run, not a dedicated
# single character -- see CONSTRUCTS["space"]'s comment).
_QUAD_CHAR = next(ch for ch, latex in SPACE_TO_LATEX.items() if latex.strip() == "\\quad")


def _emit_rad(deg, e):
    """`\\sqrt[n]{x}` / `\\sqrt{x}`. Unlike a merely-optional slot, the degree
    slot must be *present but empty* when hidden (`radPr/degHide`), not
    absent -- Word's schema expects the `m:deg` element either way.

    `degHide="off"` for the shown-degree case is written explicitly to match
    the old XSL pipeline's output exactly, even though OOXML's own default
    for an absent `m:radPr/m:degHide` is "off" (show) already -- confirmed
    against ECMA-376 Part 1 `CT_RadPr`, whose `degHide` is a
    `CT_OnOff`-with-default-false element, so omitting it is not a rendering
    defect. Kept anyway so the R3 oracle comparison has no unexplained
    `\\sqrt[n]{}` divergence from the known-good reference."""
    hidden = deg is None
    pr = _pr("radPr", _pr_val("degHide", "on" if hidden else "off"))
    el = _mk("rad", pr)
    el.append(_slot("deg", deg or []))
    el.append(_slot("e", e))
    return el


def _emit_nary(sub, sup, e, ch, limits=None):
    """`\\int`/`\\sum`/... with optional limits. Both `m:sub`/`m:sup` are
    always present (possibly empty, then hidden via `naryPr`), matching
    `_emit_rad`'s reasoning.

    `limLoc`/`subHide`/`supHide` are not cosmetic (R3 oracle defect 2):
    omitting `limLoc` leaves Word to default to `subSup`, drawing a display
    `\\sum`'s limits beside it instead of above/below; omitting
    `subHide`/`supHide` (rather than writing `off` when a limit is present)
    leaves Word free to draw its own placeholder for a hidden-but-hollow
    limit box. `grow` is deliberately *not* written: the old XSL pipeline
    emitted `<m:grow>1</m:grow>` and the emitter mirrored it, but Word's
    own writers never do -- 0 of 851 corpus n-ary carry it -- and the
    difference is visible, not cosmetic: `grow` scales the operator glyph
    to the height of its operand, so a nested `\\sum\\sum` grew the outer
    operator and the two rendered at different sizes where the original
    shows them equal (measured on a corpus document's round trip).

    `limits` is `Nary.limits`'s tri-state: `None` falls back to the
    character default (`ch in NARY_UNDOVR`), `True`/`False` force
    `undOvr`/`subSup` explicitly -- an author-written `\\limits`/`\\nolimits`
    overriding what the operator character alone would imply."""
    undovr = (ch in NARY_UNDOVR) if limits is None else limits
    pr = _pr(
        "naryPr",
        _pr_val("chr", ch),
        _pr_val("limLoc", "undOvr" if undovr else "subSup"),
        _pr_val("subHide", "on" if sub is None else "off"),
        _pr_val("supHide", "on" if sup is None else "off"),
    )
    el = _mk("nary", pr)
    el.append(_slot("sub", sub or []))
    el.append(_slot("sup", sup or []))
    el.append(_slot("e", e))
    return el


def _emit_delim(items, open_ch, close_ch):
    """Every delimiter pair, always as `\\left`/`\\right` (Rule 1) --
    `open_ch`/`close_ch` of `None` is the one-sided null form, which still
    needs an explicit empty `begChr`/`endChr` (Word's default when the
    property is *absent* is `(`/`)`, not "no delimiter" -- omitting it would
    silently turn a one-sided delimiter into a parenthesis)."""
    pr = _pr(
        "dPr",
        _pr_val("begChr", open_ch or ""),
        _pr_val("endChr", close_ch or ""),
        _pr_val("sepChr", ",") if len(items) > 1 else None,
    )
    el = _mk("d", pr)
    for item in items:
        el.append(_slot("e", item))
    return el


def _emit_script(base, sub, sup):
    """`x_{i}`, `x^{2}`, `x_{i}^{2}` -> whichever of `sSub`/`sSup`/`sSubSup`
    the present slots select -- the one genuinely structural decision Rule 6
    leaves to the emitter."""
    if sub is not None and sup is not None:
        return _build("sSubSup", None, ("e", base), ("sub", sub), ("sup", sup))
    if sub is not None:
        return _build("sSub", None, ("e", base), ("sub", sub))
    return _build("sSup", None, ("e", base), ("sup", sup))


def _emit_frac(num, den, kind, paren=False):
    """`\\frac`/`\\dfrac`/`\\tfrac` (`bar`), `\\binom` (`noBar`, `paren`),
    the native `\\genfrac` form (`noBar`, bare). Per `Frac`'s docstring, `\\binom`'s implied
    parentheses are not a separate `Delim` node the parser ever sees, so
    wrapping in `m:d` is this callable's job, not `CONSTRUCTS["delim"]`'s --
    matching what `math.load._load_delim` already unwraps on the way back (a
    sole `noBar` `m:f` inside a `(`/`)` `m:d` goes straight to `\\binom`).

    The wrap is keyed on `paren`, not on `kind == "noBar"`: Word writes a
    *bare* `noBar` `m:f` for a stacked pair with no bar and no brackets --
    evaluation-bar limits, `\\left. f \\right|_0^3`-style -- and adding
    parentheses the source never had is a visible degradation, so that shape
    gets its own spelling (`\\genfrac`) rather than being folded into
    `\\binom`."""
    f = _build("f", _pr("fPr", _pr_val("type", kind)), ("num", num), ("den", den))
    if paren:
        return _emit_delim([[f]], "(", ")")
    return f


# CANONICAL.md's array rule: a column-spec letter's OMML justification.
# Word's own default (used everywhere else -- every non-`array` env, and an
# `array` whose columns are all `c`) is `center`, which is exactly why an
# all-`c` spec must *not* trigger the per-column shape below (Rule 0's "never
# write a redundant override" discipline, restated for matrices).
_COL_JC = {"l": "left", "c": "center", "r": "right"}


def _emit_matrix(rows, env, cols=None):
    """`pmatrix`/.../`cases`/`align*`/`array` -> `m:m`, optionally `m:d`-
    wrapped (Rule 5) -- the env->delimiter decision the `Matrix` docstring
    assigns to this callable. Looked up lazily (at call time, not at
    table-definition time) since `CONSTRUCTS_BY_NAME` does not exist until
    the whole table below has been built.

    `m:mPr` is not cosmetic (R3 oracle defect 3): without a column
    specification Word has no column count or alignment for the matrix, and
    without `plcHide="on"` an empty cell draws a dotted placeholder (the same
    class of problem `naryPr/subHide`/`supHide` solve for n-ary limits).
    Matches the old XSL pipeline's shape exactly: `baseJc="center"`,
    `plcHide="on"`, then one `m:mc` (not one per column -- every column
    shares the same alignment) whose `m:mcPr/m:count` is the row width and
    `m:mcJc="center"`.

    `cols` (only ever set for `env="array"`, per CANONICAL.md's array rule)
    is the parsed `{rl}`-style column-spec, one `l`/`c`/`r` letter per
    column. When every letter is `c` this collapses to exactly the shape
    above -- a redundant `\\begin{array}{ccc}` must not produce different
    OMML from an ordinary centred matrix. Only a genuine non-centre column
    switches to one `m:mc` per column (`count="1"` each), each carrying its
    own `mcJc`."""
    ncols = max((len(row) for row in rows), default=0)
    if cols and any(c != "c" for c in cols):
        mcs = _mk(
            "mcs",
            *[
                _mk("mc", _mk("mcPr", _pr_val("count", "1"), _pr_val("mcJc", _COL_JC[c])))
                for c in cols
            ],
        )
    else:
        mcs = _mk(
            "mcs",
            _mk("mc", _mk("mcPr", _pr_val("count", str(ncols)), _pr_val("mcJc", "center"))),
        )
    pr = _mk(
        "mPr",
        _pr_val("baseJc", "center"),
        _pr_val("plcHide", "on"),
        mcs,
    )
    m = _mk("m", pr)
    for row in rows:
        mr = etree.Element(qm("mr"))
        for cell in row:
            mr.append(_slot("e", cell))
        m.append(mr)
    props = CONSTRUCTS_BY_NAME["matrix"].variants[env]
    beg, end = props["begChr"], props["endChr"]
    if beg is None and end is None:
        return m
    return _emit_delim([[m]], beg, end)


# --- AST node types ----------------------------------------------------------
#
# Frozen dataclasses. This set is exactly the Rule 0 target inventory in
# REWRITE_FORWARD.md, no more: if a new node looks necessary, that is a sign
# the inventory itself needs revisiting, which is a decision for whoever
# owns REWRITE_FORWARD.md, not something to improvise here.
#
# Every node has a `children()` accessor returning its child *nodes* in the
# order a generic walker should visit them (not necessarily OMML slot order,
# which the construct table records separately in `Construct.slots`). Leaf
# nodes -- the ones that always bottom out at a single OMML run rather than
# containing other nodes -- return an empty tuple.


@dataclass(frozen=True)
class Row:
    """A sequence of sibling nodes. Not an OMML element in its own right --
    it is how a construct's slot ("the numerator", "the delimited content")
    holds more than one item; its children are emitted as direct siblings of
    whatever contains it (`m:e`'s children, `m:oMath`'s children, ...)."""

    items: Tuple["Node", ...]

    def children(self):
        return self.items


@dataclass(frozen=True)
class Ident:
    """A single italic variable, e.g. the `x` in `x+y`. Plain `m:r`/`m:t`
    with no style override -- upright/italic is the OMML default, not a
    property this node carries."""

    char: str

    def children(self):
        return ()


@dataclass(frozen=True)
class Num:
    """A run of digits. Also plain `m:r`/`m:t`; Word's math font renders
    digits upright by default, so (unlike Ident) no style attribute is
    needed to get that."""

    text: str

    def children(self):
        return ()


@dataclass(frozen=True)
class Op:
    """A single operator/relation/symbol glyph (`+`, `=`, `\\leq`, ...).
    The macro<->codepoint mapping itself is `mathsyms.SYMBOL_MAP` territory
    (character-level truth); this node just carries the resolved
    character."""

    char: str

    def children(self):
        return ()


@dataclass(frozen=True)
class Text:
    """`\\text{...}` -- literal prose sitting inside math. Round-trips
    through `m:r` with the `m:nor` ("no reformatting") property (Rule 9)."""

    s: str

    def children(self):
        return ()


@dataclass(frozen=True)
class OpName:
    """A standalone upright operator name (`\\sin`, `\\operatorname{rank}`)
    with no following argument recognised as its operand. `m:r` with
    `sty="p"` (Rule 2 -- and Rule 2's mandatory trailing space is a
    property of *serialization*, not of this node).

    `is_mathrm` marks a name that came from `\\mathrm{...}` rather than
    `\\operatorname{...}`/a standard macro -- same OMML shape (`m:r`,
    `sty="p"`), but `\\mathrm{d}x` must not become an `m:func` the way
    `\\sin x` does (`\\mathrm{d}` is upright text sitting next to `x`, not a
    named function applied to it), so `latex2omml._is_opname_expr`'s
    forward twin excludes it from Rule 2 function-application adjacency.
    Also changes which fallback spelling `serialize` picks when `name` is
    not one of the standard operator names: `\\mathrm{name}`, not
    `\\operatorname{name}` -- see `CANONICAL.md`'s note on `\\mathrm`."""

    name: str
    is_mathrm: bool = False

    def children(self):
        return ()


@dataclass(frozen=True)
class Script:
    """`x_{i}`, `x^{2}`, `x_{i}^{2}`. Which of `m:sSub` / `m:sSup` /
    `m:sSubSup` this becomes is a function of which of `sub`/`sup` are
    present, not a separate node per shape -- Rule 6 forces both to always
    be braced regardless."""

    base: "Node"
    sub: Optional["Node"]
    sup: Optional["Node"]

    def children(self):
        return tuple(x for x in (self.base, self.sub, self.sup) if x is not None)


@dataclass(frozen=True)
class PreScript:
    """`\\prescript{sup}{sub}{base}` -> `m:sPre`. Note the LaTeX macro's
    argument order (sup, sub, base) does not match the OOXML slot order
    (sub, sup, e) -- `Construct.slots` records the OMML order; this is
    exactly the kind of fact that drifts if written down twice."""

    base: "Node"
    sub: "Node"
    sup: "Node"

    def children(self):
        return (self.base, self.sub, self.sup)


@dataclass(frozen=True)
class Frac:
    """`\\frac` (`kind="bar"`), `\\binom` and `\\genfrac`
    (`kind="noBar"`), a linear slash (`kind="lin"`), and `\\sfrac`
    (`kind="skw"`) -- all of them `m:f` distinguished only by
    `m:fPr/m:type`. The native profile uses ordinary LaTeX or the approved
    `genfrac`/`sfrac` packages for these shapes.

    `paren` is the one piece of a `Frac` that is not an `fPr` prop: it
    records the `m:d` wrapper `\\binom` implies and a bare `noBar` stack does
    not. It is a node field rather than a separate `Delim` child because
    `\\binom{a}{b}` has no `\\left(`/`\\right)` in its source -- see
    `_emit_frac`.

    A hand-typed `a/b` in LaTeX source parses to `Frac(kind="lin")`, so the
    forward and reverse paths both preserve Word's actual linear-fraction
    object. A solidus without a valid right operand remains an ordinary
    `Op('/')` for tolerant parsing of incomplete input."""

    num: "Node"
    den: "Node"
    kind: str  # "bar" | "noBar" | "lin" | "skw"
    paren: bool = False  # \binom's implied m:d wrapper

    def children(self):
        return (self.num, self.den)


@dataclass(frozen=True)
class Rad:
    """`\\sqrt{e}` (`degree=None`) or `\\sqrt[n]{e}` -> `m:rad`, with the
    degree slot hidden (`m:radPr/m:degHide`) in the former case."""

    radicand: "Node"
    degree: Optional["Node"]

    def children(self):
        return (self.radicand,) if self.degree is None else (self.radicand, self.degree)


@dataclass(frozen=True)
class Nary:
    """`\\int`, `\\sum`, `\\prod`, `\\oint`, `\\bigcup`, ... with or without
    limits -> `m:nary`. `op` is the resolved operator character (which
    macro it is is `mathsyms` territory, same split as `Op`); `sub`/`sup`
    are `None` when the corresponding limit is hidden
    (`m:naryPr/m:subHide`/`m:supHide`), not merely empty.

    `limits` exists to close a measured fidelity defect: `m:naryPr/m:limLoc`
    ("undOvr" draws limits above/below the operator, "subSup" beside it) was
    previously derived purely from `op`'s character class
    (`mathsyms.NARY_UNDOVR`), so a hand-authored Word integral with limits
    drawn above/below silently reversed to beside on round trip -- 248
    integrals and 13 triple integrals damaged this way across the user's
    real documents, the single largest remaining fidelity degradation class.
    Character class alone cannot record it: the same document contains one
    `∫` with `undOvr` and another with `subSup`. A tri-state (`None` = use
    the character's own default, `True` = force `undOvr`, `False` = force
    `subSup`) lets the canonical LaTeX spelling (`\\limits`/`\\nolimits`,
    written only when it overrides the default) carry the fact explicitly,
    per `CANONICAL.md`'s n-ary rule.

    `body_braced` carries the reverse walker's rule-16 bracing decision
    (PLAN.md §5.1): whether `body` must be written `{...}`. It is always
    `False` on nodes the forward parser builds (a braced group in source
    *is* the body, and the bounded-run rule reproduces the unbraced
    spelling), and is set only by `math.load`, which still sees the
    OMML context -- specifically whether content follows the operand in
    its parent row (Task A) -- that the AST tree cannot. Declared last so
    the frozen dataclass keeps working with positional construction of the
    pre-existing fields."""

    op: str
    sub: Optional["Node"]
    sup: Optional["Node"]
    body: "Node"
    limits: Optional[bool] = None
    body_braced: bool = False

    def children(self):
        return tuple(x for x in (self.sub, self.sup, self.body) if x is not None)


@dataclass(frozen=True)
class Delim:
    """Every delimiter pair -> `m:d`. Rule 1: canonical LaTeX is always
    `\\left`/`\\right`, one-sided delimiters use the null form (`open` or
    `close` may be `None`, serializing as `\\left.`/`\\right.`)."""

    open: Optional[str]
    close: Optional[str]
    items: Tuple["Node", ...]

    def children(self):
        return self.items


@dataclass(frozen=True)
class Func:
    """Operator name plus argument -> `m:func`. `name` is itself a node
    (usually `OpName`, but can be a `Script` wrapping one -- `\\sin^2`,
    `\\limsup_{n\\to\\infty}` -- per the loader's `_load_func`, which
    unwraps scripted names) rather than a bare string, since the name can
    carry its own scripts."""

    name: "Node"
    arg: "Node"
    operand_braced: bool = False  # rule-16 decision, set only by math.load

    def children(self):
        return (self.name, self.arg)


@dataclass(frozen=True)
class Accent:
    """`\\vec \\hat \\dot \\ddot \\tilde \\bar \\check \\acute \\grave
    \\breve` -> `m:acc`. `mark` is the macro name (`"vec"`, `"hat"`, ...);
    the mark<->combining-character mapping is `mathsyms.ACCENT_CHARS`/
    `ACCENT_REVERSE` territory. Note `\\bar`/`\\overline` are visually
    similar but structurally distinct: `\\bar` (one character wide) is an
    `Accent`; `\\overline`/`\\underline` (spans the whole base) is `Bar`,
    below."""

    mark: str
    base: "Node"

    def children(self):
        return (self.base,)


@dataclass(frozen=True)
class Bar:
    """`\\overline{e}` (`pos="top"`) / `\\underline{e}` (`pos="bot"`) ->
    `m:bar`. A combining accent spans one character; a bar spans the whole
    base, which is why these are a distinct element from `Accent` rather
    than `\\bar`/`\\overline` sharing one node."""

    base: "Node"
    pos: str  # "top" | "bot"

    def children(self):
        return (self.base,)


@dataclass(frozen=True)
class Boxed:
    """`\\boxed{e}` -> `m:borderBox` (PLAN.md §6.2). The box is a visual
    frame with no meaning of its own; the node carries only the base."""

    base: "Node"

    def children(self):
        return (self.base,)


@dataclass(frozen=True)
class Phantom:
    """`\\phantom{e}` -> `m:phant` (PLAN.md §6.2). The content occupies
    space but is invisible; in OMML it is the `m:phant` element with the
    `show` property (absent here: the corpus only uses the default hidden
    form, so `props={"show": None}` carries no value)."""

    base: "Node"

    def children(self):
        return (self.base,)


@dataclass(frozen=True)
class Limit:
    """`\\lim_{n\\to\\infty}` (movable-limit operator names, `pos="low"`),
    `\\underset{lim}{base}` (`pos="low"`), `\\overset{lim}{base}`
    (`pos="upp"`) -> `m:limLow`/`m:limUpp`.

    Does **not** cover `\\overbrace`/`\\underbrace` -- those are `GroupChr`
    (a new, dedicated element; see D3 in `DEFECTS.md`) even though the
    *old*, still-live forward pipeline currently mis-emits them as a
    brace-glyph `limLow`/`limUpp` for lack of a `groupChr` template in
    `MML2OMML.XSL`. A document containing that legacy shape still needs to
    be *read*, though -- `word2latex.py`'s `_convert_lim` special-cases a
    brace glyph (`BRACE_MARKS`) sitting in the `lim` slot and produces the
    `\\overbrace`/`\\underbrace` spelling instead of `\\underset`/`\\overset`.
    That recognition is real logic belonging to `CONSTRUCTS["limit"]`'s
    `parse` callable (it must be able to hand back a `GroupChr` node
    instead of a `Limit` when it detects the legacy shape) -- documented
    here since it is easy to miss that one OMML element's parser can yield
    either of two node types."""

    base: "Node"
    lim: "Node"
    pos: str  # "low" | "upp"

    def children(self):
        return (self.base, self.lim)


@dataclass(frozen=True)
class GroupChr:
    """`\\overbrace{e}` (`pos="top"`) / `\\underbrace{e}` (`pos="bot"`) ->
    `m:groupChr`. Listed in `REWRITE_FORWARD.md` as "new capability,
    unreachable today" (D3): the old pipeline cannot emit this element at
    all for lack of an XSL template, which is exactly the kind of gap the
    rewrite exists to close."""

    base: "Node"
    chr: str
    pos: str  # "top" | "bot"

    def children(self):
        return (self.base,)


@dataclass(frozen=True)
class Matrix:
    """`pmatrix bmatrix Bmatrix vmatrix Vmatrix cases matrix array` -> `m:m`,
    optionally wrapped in `m:d` for the delimited environments (Rule 5).
    `rows` is a list of list of `Row` (row-major); `env` is the environment
    name and is what decides whether an `m:d` wrapper is emitted and with
    which delimiter pair -- `cases`/`matrix`/`array` get none, `pmatrix` etc.
    do. `matrix` is also the canonical fold target for the whole undelimited-
    multi-row alias family (`align*`, `align`, `aligned`, `gather*`, ...) --
    an undelimited `m:m` carries nothing that tells them apart in OMML, so
    Rule 5 picks the one spelling `word2latex.py` has always actually
    produced; `latex2omml._ENV_ALIASES` does the folding at parse time, so
    `env` here is already `"matrix"` regardless of which alias the source
    wrote. That env->delimiter decision is `CONSTRUCTS["matrix"]`'s `emit`
    callable's job, and the corresponding fold-`m:d`-around-a-sole-`m:m`-
    child-back-into-one-`Matrix`-node decision is `CONSTRUCTS["delim"]`'s
    `parse` callable's job (see `math.load._load_delim`, which already does
    this fold).

    `cols` is `array`'s own column-spec (`{rl}` -> `("r", "l")`), `None` for
    every other env -- `CANONICAL.md`'s array rule: `array` is the only
    environment whose column justification is not implicitly `center`, and
    is the explicit LaTeX spelling for `m:mPr/m:mcs`' per-column `m:mcJc`
    when a real document has one that is not all `center` (Rule 0 -- that
    property is otherwise unreachable from OMML alone, per the `matrix`
    construct's old docstring note that one `m:mc` was assumed to always
    speak for every column)."""

    rows: Tuple[Tuple["Node", ...], ...]
    env: str
    cols: Optional[Tuple[str, ...]] = None

    def children(self):
        return tuple(cell for row in self.rows for cell in row)


@dataclass(frozen=True)
class Space:
    """Explicit spacing macros (`\\,` `\\:` `\\quad` `\\qquad`) that survive
    as content per Rule 7.5, not as OMML `m:sp` (which the XSL drops
    entirely) but as a proportional Unicode space glyph inside a plain
    run -- see `mathsyms.SPACE_CHARS`/`SPACE_TO_LATEX`. `width` is the
    space's own identity ("thin", "med", "quad", "qquad"), not a physical
    dimension."""

    width: str

    def children(self):
        return ()


Node = Union[
    Row, Ident, Num, Op, Text, OpName, Script, PreScript, Frac, Rad, Nary,
    Delim, Func, Accent, Bar, Boxed, Phantom, Limit, GroupChr, Matrix, Space,
]

ALL_NODE_TYPES = (
    Row, Ident, Num, Op, Text, OpName, Script, PreScript, Frac, Rad, Nary,
    Delim, Func, Accent, Bar, Boxed, Phantom, Limit, GroupChr, Matrix, Space,
)


# --- The Rule 0 closed set of 22 OMML elements --------------------------------
# §6.2 added `borderBox` and `phant` to the original 20 (PLAN.md §6.2 record):
# measured corpus vocabulary (\boxed, \phantom) that needs OMML elements the
# original inventory never declared.

OMML_ELEMENTS = frozenset({
    "oMath", "oMathPara", "r", "t", "e",
    "sSub", "sSup", "sSubSup", "sPre",
    "f", "rad", "nary", "d", "func", "acc", "bar",
    "limLow", "limUpp", "groupChr", "m",
    "borderBox", "phant",
})


# --- N-ary macro vocabulary ----------------------------------------------
#
# Declared once in the registry (symbols/registry.py): the n-ary glyphs,
# their macros, and the under-over family. The registry asserts the same
# totality this module used to assert locally (every mathsyms.NARY_CHARS
# glyph has exactly one macro declaration), so nothing is retyped here --
# the construct table consumes the registry's NARY_MACROS directly. The
# reverse mapping (glyph -> macro) is latex2omml._NARY_SPELLING, derived
# from this very construct table's variants rather than hand-written; if a
# glyph has no variant here, the derivation simply lacks it and the
# serializer raises on use.


# Which opening delimiter character pairs with which closing one -- a
# structural fact (this module's job), not a character-level one. The
# macro *spelling* for each character is derived below from
# mathsyms.DELIM_LEFTRIGHT rather than retyped, so it cannot drift from
# what word2latex.py reads for the same characters.
_DELIM_PAIRS = (
    ("(", ")"), ("[", "]"), ("{", "}"), ("⟨", "⟩"),
    ("|", "|"), ("‖", "‖"), ("⌈", "⌉"), ("⌊", "⌋"),
)


# --- The construct table -----------------------------------------------------
#
# Sentinel for the small handful of leaf nodes that are "always plain m:r/m:t,
# distinguished only by properties/content, not by a separate element" -- Ident,
# Num, Op, Text, OpName, Space. Their `parse`/`emit`/`serialize` are simple
# enough to not need a real algorithm (they *are* the algorithm), so unlike the
# structural constructs' stubs these are given a working one-line lambda rather
# than a NotImplementedError placeholder.
#
# For every other construct, `parse`/`emit` are named stubs: the table records
# *that* the construct needs real logic and *which* OMML shape it owns, without
# writing the logic itself (out of scope for R2a). `serialize` is filled in
# declaratively wherever a fixed template exists, since the LaTeX spelling is
# already decided by CANONICAL.md and writing it down is not "an emitter".


def _stub(stage, what):
    """Return a placeholder callable that documents which future stage
    supplies real behaviour. Its presence (not its body) is what satisfies
    the self-validation invariant that every entry declares parse/emit
    somehow -- a declared-but-unimplemented callable is not itself a parser
    or an emitter."""

    def _fn(*args, **kwargs):
        raise NotImplementedError(f"{what} not implemented until {stage}")

    _fn.__name__ = f"stub_{what}"
    _fn.stage = stage
    return _fn


@dataclass(frozen=True)
class Construct:
    """One row of the construct table.

    `latex` is the canonical macro spelling per CANONICAL.md, or `None` for
    constructs with no single fixed spelling (e.g. `nary`'s operator varies
    by which n-ary symbol it is; `delim`'s open/close vary by bracket pair).
    `arity`, when set, is the node's fixed number of *slots* (not
    necessarily children -- `Rad`'s degree slot is optional) and is checked
    against `len(slots)` at import time.
    `omml` is the element name (or a tuple of names, when one node type maps
    to more than one element depending on which optional parts are present:
    `Script` -> one of `sSub`/`sSup`/`sSubSup`; `Limit` -> `limLow`/`limUpp`).
    `props` records the OMML property attributes that distinguish spellings
    sharing one element (`fPr/type`, `barPr/pos`, ...).
    `slots` is the *ordered* list of OMML child element names for the node's
    children -- this ordering is load-bearing, per REWRITE_FORWARD.md, and is
    exactly what stops the two directions drifting.
    `parse`/`emit` walk OMML<->AST; `serialize` renders AST->canonical LaTeX
    text (this *is* `canonicalize()`, see REWRITE_FORWARD.md R2). Each is
    either a fixed declaration (a string template for `serialize`; the
    presence of `omml`+`slots` for `parse`/`emit`) or an explicit callable
    override -- never neither, checked at import time.

    `latex`/`variants` (Part 4) are the LaTeX-side counterpart to `omml`: a
    construct's macro vocabulary, declared once so `MACRO_TO_CONSTRUCT`
    below can be *derived* rather than hand-written a second time by R2b's
    parser and a third time by R5's walker. Exactly one of the two is set
    for a macro-bearing construct: `latex` for a construct with one fixed
    spelling (`\\sqrt`, `\\prescript`, `\\text`); `variants` -- a dict
    mapping each concrete spelling to the OMML props it selects -- for a
    construct several macros share (`\\overline`/`\\underline` both -> `bar`,
    distinguished only by `pos`). `no_macro=True` marks the handful of
    primitives that are not invoked by any backslash macro at all (a bare
    letter, a digit, a symbol glyph resolved through `mathsyms.SYMBOL_MAP`)
    -- for those, neither `latex` nor `variants` applies, and that absence
    is itself asserted at import time rather than left ambiguous.
    """

    name: str
    node: type
    omml: Union[str, Tuple[str, ...], None]
    latex: Optional[str] = None
    variants: Optional[dict] = None
    no_macro: bool = False
    arity: Optional[int] = None
    props: dict = field(default_factory=dict)
    slots: Tuple[str, ...] = ()
    parse: Optional[Callable] = None
    emit: Optional[Callable] = None
    serialize: Optional[Union[str, Callable]] = None


CONSTRUCTS = [
    # --- Primitives: always plain m:r/m:t, distinguished by content/props ---
    Construct(
        name="row",
        node=Row,
        omml=None,  # not an element in its own right -- see Row's docstring
        no_macro=True,  # a sequence has no macro of its own; it's the glue
        slots=(),
        parse=lambda *a, **k: None,
        emit=lambda *a, **k: None,
        serialize=lambda children: "".join(children),
    ),
    Construct(
        name="ident",
        node=Ident,
        omml="r",
        no_macro=True,  # a bare letter is not invoked by any macro
        props={},
        slots=("t",),
        parse=lambda *a, **k: None,
        emit=lambda text: _run(text),
        serialize=lambda n: n,
    ),
    Construct(
        name="num",
        node=Num,
        omml="r",
        no_macro=True,  # a bare digit run is not invoked by any macro
        props={},
        slots=("t",),
        parse=lambda *a, **k: None,
        emit=lambda text: _run(text),
        serialize=lambda n: n,
    ),
    Construct(
        name="op",
        node=Op,
        omml="r",
        # A symbol glyph's own macro<->character vocabulary is
        # mathsyms.SYMBOL_MAP, not this table -- Op's own macro spelling is
        # deliberately not re-declared here as a second copy of that table
        # (see the module docstring's note on why some families are left
        # where they already live rather than duplicated).
        no_macro=True,
        # Found while building the R3 emitter's oracle comparison, not
        # carried over from an earlier stage: standard math typesetting
        # renders every operator/relation/punctuation glyph upright, never
        # italic, but OMML's default `m:r` style (no `rPr` at all) is
        # italic -- the same convention CLAUDE.md's `fix_operator_style`
        # documents for symbol operators specifically ("backwards for
        # symbol operators... with a visibly slanted glyph"). The old
        # pipeline actually applies this to *every* `mo`-derived run, ASCII
        # arithmetic/relation signs included (measured: `+`, `=`, `<`, `,`,
        # `!`, `?`, `.`, `\times`, `\in`, ... all get `sty="p"`), not only
        # the symbol-glyph subset CLAUDE.md's prose calls out. Omitting this
        # would mean every `+`/`=`/`×` in a document produced by this
        # emitter renders visibly slanted in Word -- a real rendering
        # regression the round-trip-identity property (text-only) cannot
        # see, caught only by the oracle comparing structure/properties
        # against the XSL's known-correct output.
        props={"sty": "p"},
        slots=("t",),
        parse=_stub("R2b", "op_parse"),
        # ASCII '-' is the canonical *macro* spelling for U+2212 MINUS SIGN
        # (mathsyms.SYMBOL_MAP maps "−" -> "-", the reverse direction
        # word2latex reads), but the two are visually distinct glyphs --
        # Word's math font kerns/spaces a real minus sign differently from a
        # hyphen-minus. Also found via the oracle: the old pipeline (via
        # latex2mathml) always emits the real U+2212 glyph for a LaTeX '-' in
        # math mode; emitting the literal ASCII character instead would be a
        # silent rendering regression the text-only round-trip property
        # cannot see (the codepoint substitution round-trips through
        # word2latex either way, since it does not special-case '-' itself).
        emit=lambda text: _run("−" if text == "-" else text, _pr_val("sty", "p")),
        serialize=lambda n: n,
    ),
    Construct(
        name="text",
        latex=r"\text",
        node=Text,
        omml="r",
        props={"nor": True},
        slots=("t",),
        parse=lambda *a, **k: None,
        # `s` (Text.s / the node's `t` slot) holds the *decoded* literal
        # text -- latex2omml._h_text already turned any \text{}-mode
        # escapes (\%, \textasciitilde, ...) into the characters they mean
        # (defect C; mathsyms.TEXT_ESCAPE_TO_CHAR is the decode direction).
        # `emit` therefore writes those characters straight into the OMML
        # run, and `serialize` must re-escape them (mathsyms.TEXT_CHAR_TO_
        # ESCAPE, the encode direction) to produce compilable LaTeX --
        # leaving a literal "%"/"~"/... in `\text{...}` source would either
        # start a comment or fail to parse.
        emit=lambda s: _run(s, _pr_flag("nor")),
        serialize=lambda s: "\\text{%s}" % "".join(
            TEXT_CHAR_TO_ESCAPE.get(ch, ch) for ch in s),
    ),
    Construct(
        name="opname",
        # Derived, not retyped: KNOWN_FUNC_MACROS (mathsyms.py) already
        # holds every standalone operator-name macro this project
        # recognises -- both the fixed list (\sin, \cos, ...) and the
        # movable-limit names (\lim, \max, ...) LIMIT_OPS folds into it.
        # This is also where \lim/\max/... get their base token: whether
        # that token then gets wrapped in a Limit node (a subscript
        # follows) is CONSTRUCTS["limit"]'s parse callable's job, not a
        # second macro-dispatch entry -- see CONSTRUCTS["limit"]'s comment.
        variants={macro: {} for macro in KNOWN_FUNC_MACROS.values()},
        node=OpName,
        omml="r",
        props={"sty": "p"},
        # Rule 2's mandatory trailing space before a following letter/digit
        # is a join-time concern (it depends on the *next* sibling), so it
        # is not baked into this template -- see latex2omml._join's Rule 7.1
        # comment on why the space is added at join time, not here.
        parse=_stub("R2b", "opname_parse"),
        emit=lambda name: _run(name, _pr_val("sty", "p")),
        serialize=lambda name: "\\%s" % name if name not in KNOWN_FUNC_MACROS else KNOWN_FUNC_MACROS[name],
    ),
    Construct(
        name="space",
        # Derived, not retyped: the registry declares each space once with
        # its *bare* spelling (no join-safety trailing space), and
        # SPACE_MACRO_TO_GLYPH (mathsyms.py re-exports it) is exactly this
        # construct's variant vocabulary. No strip is involved -- that is
        # the whole point: the old derivation stripped the join space back
        # off a stored spelling and truncated "\ " to a bare backslash (the
        # SPACE_TO_LATEX truncation, resolved at §5.2 by declaring the bare
        # spelling instead). U+2006 (the internal gap inside compound names
        # like "lim sup") is declared reverse-only, so it never appears
        # here -- genuinely no canonical macro, left as a gap, not invented.
        #
        # \qquad is added explicitly, not derived: it has no dedicated
        # glyph of its own in the registry -- the reverse side recognises
        # it as a *run* of two consecutive quad-width glyphs (two U+2003,
        # or two plain ASCII spaces) rather than a single character with
        # its own table entry. That run-length pattern is a genuinely
        # different shape from every other space (one glyph <-> one macro),
        # so it cannot be derived by the same one-entry-per-glyph rule;
        # declaring the macro itself here closes the gap so R2b's parser
        # has a `\qquad` entry to dispatch on, while the width value
        # ("qquad") documents that its *parse* still needs the
        # doubled-run recognition, not a plain lookup.
        variants=dict(
            {
                spelling: {"width": glyph}
                for spelling, glyph in SPACE_MACRO_TO_GLYPH.items()
            },
            **{r"\qquad": {"width": "qquad"}},
        ),
        node=Space,
        omml="r",
        props={},
        slots=("t",),
        parse=_stub("R2b", "space_parse"),
        emit=lambda width: _run(_QUAD_CHAR * 2 if width == "qquad" else width),
        serialize=_stub("R2b", "space_serialize"),
    ),

    # --- Scripts --------------------------------------------------------
    Construct(
        name="script",
        node=Script,
        # Not macro-dispatched: triggered by the `_`/`^` catcode tokens
        # (themselves not macros) at the parser level, not looked up by
        # name -- no entry in MACRO_TO_CONSTRUCT is meaningful here.
        no_macro=True,
        # Which of the three elements is used depends on which of sub/sup
        # are present -- a real decision, not a fixed spelling.
        omml=("sSub", "sSup", "sSubSup"),
        slots=("e", "sub", "sup"),
        parse=_stub("R2b", "script_parse"),
        emit=_emit_script,
        serialize=_stub("R2b", "script_serialize"),
    ),
    Construct(
        name="prescript",
        latex=r"\prescript",
        arity=3,
        node=PreScript,
        omml="sPre",
        # OOXML slot order is sub, sup, e -- note this does NOT match the
        # LaTeX macro's own argument order (sup, sub, base); see PreScript's
        # docstring.
        slots=("sub", "sup", "e"),
        parse=_stub("R2b", "prescript_parse"),
        emit=lambda sub, sup, base: _build(
            "sPre", None, ("sub", sub), ("sup", sup), ("e", base)),
        serialize=lambda sub, sup, base: "\\prescript{%s}{%s}{%s}" % (sup, sub, base),
    ),

    # --- Fractions / radicals --------------------------------------------
    Construct(
        name="frac",
        # Declared explicitly: no mathsyms table owns "which macros produce
        # which m:fPr/type" (mathsyms is character-level; this is
        # structural). \dfrac/\tfrac select the same type="bar" shape as
        # \frac (they only affect display-vs-text *style* inside the
        # fraction, which OMML's fPr/type does not distinguish -- a known,
        # accepted lossy point, not a table bug). \binom selects
        # type="noBar" directly: unlike a "genuine" parenthesised noBar
        # fraction, \binom's surrounding parentheses are implied by the
        # macro itself, not a separate Delim the parser sees -- so
        # \binom{a}{b} parses straight to Frac(kind="noBar") with no
        # wrapping Delim node, and it is this construct's `emit` callable's
        # job (not a Delim entry) to wrap that in m:d when producing OMML,
        # matching what math.load._load_delim already recognises on the way
        # back (a sole noBar m:f inside a "(" ")" m:d is unwrapped straight
        # to \binom, skipping the redundant \left(\right)) -- hence the
        # "paren" key, the only variant key that is not an fPr prop.
        # The native genfrac form is the same fPr/type with that wrapper absent: Word
        # writes a bare noBar m:f for a stacked pair with neither bar nor
        # brackets, and spelling that \binom would add parentheses the
        # source never had. The linear slash and sfrac forms are native
        # profile spellings, driven through this table like any other variant.
        variants={
            r"\frac": {"type": "bar"},
            r"\dfrac": {"type": "bar"},
            r"\tfrac": {"type": "bar"},
            r"\binom": {"type": "noBar", "paren": True},
            r"\genfrac": {"type": "noBar"},
            r"\sfrac": {"type": "skw"},
        },
        node=Frac,
        omml="f",
        props={"type": ("bar", "noBar", "lin", "skw")},
        slots=("num", "den"),
        parse=_stub("R2b", "frac_parse"),
        emit=_emit_frac,
        serialize=_stub("R2b", "frac_serialize"),
    ),
    Construct(
        name="rad",
        latex=r"\sqrt",
        node=Rad,
        omml="rad",
        # deg is present-but-hidden (radPr/degHide) for the no-degree form,
        # rather than absent -- an optional slot, hence a callable rather
        # than a fixed arity/template.
        slots=("deg", "e"),
        parse=_stub("R2b", "rad_parse"),
        emit=_emit_rad,
        serialize=_stub("R2b", "rad_serialize"),
    ),

    # --- N-ary operators --------------------------------------------------
    Construct(
        name="nary",
        # Declared once in the registry (NARY_MACROS, re-exported by
        # mathsyms) and cross-validated there against NARY_CHARS/NARY_UNDOVR;
        # this construct just reads the declaration.
        variants={
            macro: {"chr": ch, "underover": ch in NARY_UNDOVR}
            for macro, ch in NARY_MACROS.items()
        },
        node=Nary,
        omml="nary",
        props={"chr": None, "limLoc": None, "grow": None, "subHide": None, "supHide": None},
        slots=("sub", "sup", "e"),
        parse=_stub("R2b", "nary_parse"),
        emit=_emit_nary,
        serialize=_stub("R2b", "nary_serialize"),
    ),

    # --- Delimiters ---------------------------------------------------------
    Construct(
        name="delim",
        # Derived, not retyped: the macro spelling for each opening
        # character comes from mathsyms.DELIM_LEFTRIGHT (character-level
        # truth -- the same table word2latex.py now imports for the
        # identical lookup, so the two cannot drift). Only the *pairing*
        # (which opener goes with which closer, _DELIM_PAIRS above) is
        # declared here, since that is structural, not character-level.
        # The null form ("." following \left/\right, for a one-sided
        # delimiter) is DELIM_LEFTRIGHT[""].
        # This entry's `parse` is also where the "sole child is m:m ->
        # fold into a Matrix instead of Delim(Matrix)" decision belongs
        # (see Matrix's docstring) and where a sole noBar `m:f` child folds
        # into a bare \binom-like parenthesised fraction
        # (math.load._load_delim already does both folds).
        variants=dict(
            {
                DELIM_LEFTRIGHT[open_ch]: {"begChr": open_ch, "endChr": close_ch}
                for open_ch, close_ch in _DELIM_PAIRS
            },
            **{DELIM_LEFTRIGHT[""]: {"begChr": None, "endChr": None}},
        ),
        node=Delim,
        omml="d",
        props={"begChr": None, "endChr": None, "sepChr": None},
        slots=("e",),  # repeated: one or more m:e children, separator-joined
        parse=_stub("R2b", "delim_parse"),
        emit=_emit_delim,
        serialize=_stub("R2b", "delim_serialize"),
    ),

    # --- Function application ---------------------------------------------
    Construct(
        name="func",
        # Not macro-dispatched in its own right: a Func is the structural
        # combination of a name construct (an OpName token, itself in
        # MACRO_TO_CONSTRUCT via CONSTRUCTS["opname"], or \operatorname{...})
        # immediately followed by an operand -- recognised by adjacency at
        # parse time (Rule 2), not by looking up "func" as a macro.
        no_macro=True,
        node=Func,
        omml="func",
        slots=("fName", "e"),
        parse=_stub("R2b", "func_parse"),
        emit=lambda name, arg: _build("func", None, ("fName", name), ("e", arg)),
        serialize=_stub("R2b", "func_serialize"),
    ),

    # --- Accents / bars -----------------------------------------------------
    Construct(
        name="accent",
        # Derived, not retyped: the registry's ACCENT_TO_CHAR (mathsyms.py
        # re-exports it) is the declared macro -> combining-character
        # mapping; this is exactly the macro->accPr/chr vocabulary the
        # construct needs, aliases deliberately excluded (two marks per
        # macro would break MACRO_TO_CONSTRUCT's injectivity).
        # §6.2: \widehat/\widetilde (measured 49/8 on the .tex corpus) are
        # wide variants of \hat/\tilde; OMML's accPr has no width axis, so
        # they resolve to the same combining marks (U+0302/U+0303) and the
        # width distinction is lost in Word (a documented approximation).
        variants={
            "\\" + mark: {"chr": ch} for mark, ch in ACCENT_TO_CHAR.items()
        } | {
            r"\widehat": {"chr": "̂"},
            r"\widetilde": {"chr": "̃"},
        },
        node=Accent,
        omml="acc",
        props={"chr": None},
        slots=("e",),
        parse=_stub("R2b", "accent_parse"),
        emit=lambda base, ch: _build("acc", _pr("accPr", _pr_val("chr", ch)), ("e", base)),
        serialize=lambda mark, base: "\\%s{%s}" % (mark, base),
    ),
    Construct(
        name="bar",
        # Declared explicitly: only two macros exist and no mathsyms table
        # maps macro->pos for them. mathsyms.BAR_CHARS is a different fact
        # (which raw combining/line characters the *old* forward pipeline
        # should route to m:bar instead of m:acc) and is not a macro table.
        variants={
            r"\overline": {"pos": "top"},
            r"\underline": {"pos": "bot"},
        },
        node=Bar,
        omml="bar",
        props={"pos": ("top", "bot")},
        slots=("e",),
        parse=_stub("R2b", "bar_parse"),
        emit=lambda base, pos: _build("bar", _pr("barPr", _pr_val("pos", pos)), ("e", base)),
        serialize=lambda base, pos: (
            "\\underline{%s}" % base if pos == "bot" else "\\overline{%s}" % base
        ),
    ),
    Construct(
        name="boxed",
        # §6.2 (measured 35 on the .tex corpus): a border round the base.
        # Single macro, no props, no shared table.
        variants={r"\boxed": {}},
        node=Boxed,
        omml="borderBox",
        slots=("e",),
        parse=_stub("R2b", "boxed_parse"),
        emit=lambda base: _build("borderBox", None, ("e", base)),
        serialize=lambda base: "\\boxed{%s}" % base,
    ),
    Construct(
        name="phantom",
        # §6.2 (measured 3 on the .tex corpus). OMML's m:phant can carry a
        # `show` property; the corpus only uses the default hidden form, so
        # no prop is declared. The reverse loader reads a show="1" phantom
        # from a Word document as the plain hidden phantom (the visibility
        # is lost, like every other unrecognised property in the reverse
        # pipeline -- see math/load.py).
        variants={r"\phantom": {}},
        node=Phantom,
        omml="phant",
        slots=("e",),
        parse=_stub("R2b", "phantom_parse"),
        emit=lambda base: _build("phant", None, ("e", base)),
        serialize=lambda base: "\\phantom{%s}" % base,
    ),

    # --- Limits / group characters -------------------------------------
    Construct(
        name="limit",
        # Declared explicitly: \underset/\overset are the only macros that
        # unambiguously mean "produce a Limit node" on their own. The
        # movable-limit names (\lim, \max, \liminf, ...) are deliberately
        # *not* listed here even though CANONICAL.md and mathsyms.LIMIT_OPS
        # both know them -- on their own, bare \lim is just an OpName (see
        # CONSTRUCTS["opname"], derived from KNOWN_FUNC_MACROS, which
        # already includes them); a Limit is produced only when a
        # subscript follows, which is a parse-time structural decision
        # this table cannot express as a fixed macro->construct fact
        # without falsely claiming those macros always produce a Limit.
        # Listing them here as well would also break MACRO_TO_CONSTRUCT's
        # injectivity (a macro cannot be claimed by two constructs). Its
        # `parse` callable must also recognise (and hand off to GroupChr
        # instead of producing a Limit) the legacy brace-glyph shape the
        # still-live old pipeline emits for \overbrace/\underbrace -- see
        # Limit's docstring.
        variants={
            r"\underset": {"pos": "low"},
            r"\overset": {"pos": "upp"},
        },
        node=Limit,
        omml=("limLow", "limUpp"),
        slots=("e", "lim"),
        parse=_stub("R2b", "limit_parse"),
        emit=lambda base, lim, pos: _build(
            "limLow" if pos == "low" else "limUpp", None, ("e", base), ("lim", lim)),
        serialize=_stub("R2b", "limit_serialize"),
    ),
    Construct(
        name="groupchr",
        # Declared explicitly: only two macros, no shared mathsyms table
        # (the closest existing fact, BRACE_MARKS, lives in word2latex.py
        # keyed the other way -- brace glyph -> macro name -- for
        # recognising the legacy limLow/limUpp shape, not for macro
        # dispatch, and is not in mathsyms.py). New capability (D3) -- the
        # old pipeline cannot emit m:groupChr at all.
        variants={
            r"\overbrace": {"chr": "⏞", "pos": "top"},
            r"\underbrace": {"chr": "⏟", "pos": "bot"},
        },
        node=GroupChr,
        omml="groupChr",
        props={"chr": None, "pos": ("top", "bot")},
        slots=("e",),
        parse=_stub("R2b", "groupchr_parse"),
        emit=lambda base, ch, pos: _build(
            "groupChr", _pr("groupChrPr", _pr_val("chr", ch), _pr_val("pos", pos)),
            ("e", base)),
        serialize=lambda base, pos: (
            "\\underbrace{%s}" % base if pos == "bot" else "\\overbrace{%s}" % base
        ),
    ),

    # --- Matrices -------------------------------------------------------
    Construct(
        name="matrix",
        # Declared explicitly, keyed by environment name (dispatched via
        # \begin{name}, not a backslash macro, but the same role: the
        # vocabulary token the parser reads to select this construct's
        # props). No shared mathsyms table owns this either -- the closest
        # existing fact, math.load._ENV_FOR_DELIMS, is keyed the other way
        # ((begChr, endChr) -> env name) and lives in math/load.py.
        # cases/matrix carry no delimiters (Rule 5); the delimited
        # environments' begChr/endChr are what CONSTRUCTS["matrix"]'s
        # `emit` callable uses to decide whether (and with which glyphs) to
        # wrap the resulting m:m in m:d.
        #
        # "matrix" (undelimited) is the canonical spelling for an
        # undelimited multi-row structure, per CANONICAL.md Rule 5 --
        # `align*`/`align`/`aligned`/`gather*`/... all fold to it
        # (`latex2omml._ENV_ALIASES`) because an undelimited `m:m` carries
        # nothing in OMML that distinguishes "aligned equation system" from
        # "plain matrix": exactly one spelling can be canonical, and
        # `math.load._load_matrix`'s default `env="matrix"` (the same default
        # the old walker hardcoded) is what the reverse direction has always
        # actually produced. `align*` itself is not a
        # variant key here any more -- every raw environment name in the
        # alias family, "align*" included, is rewritten to "matrix" by
        # `_ENV_ALIASES` before this table is ever consulted, so this is
        # the only spelling `parse_environment` looks up for the whole
        # family.
        variants={
            "pmatrix": {"begChr": "(", "endChr": ")"},
            "bmatrix": {"begChr": "[", "endChr": "]"},
            "Bmatrix": {"begChr": "{", "endChr": "}"},
            "vmatrix": {"begChr": "|", "endChr": "|"},
            "Vmatrix": {"begChr": "‖", "endChr": "‖"},
            "cases": {"begChr": "{", "endChr": None},
            "matrix": {"begChr": None, "endChr": None},
            # CANONICAL.md's array rule: no implied delimiters of its own
            # (an author who wants parens wraps it in \left(...\right),
            # exactly like a bare `matrix`/`align*` -- see Matrix's
            # docstring), distinguished from every other entry here only by
            # also carrying a `cols` spec.
            "array": {"begChr": None, "endChr": None},
        },
        node=Matrix,
        omml="m",
        slots=("mr",),  # repeated: one or more m:mr rows, each of m:e cells
        parse=_stub("R2b", "matrix_parse"),
        emit=_emit_matrix,
        serialize=_stub("R2b", "matrix_serialize"),
    ),
]


# --- Self-validation at import time -------------------------------------

def _validate(constructs):
    seen_nodes = {}
    seen_latex = {}

    for c in constructs:
        # 1. every node type appears in exactly one entry.
        if c.node in seen_nodes:
            raise AssertionError(
                f"node type {c.node.__name__} claimed by both "
                f"{seen_nodes[c.node]!r} and {c.name!r}"
            )
        seen_nodes[c.node] = c.name

        # 2. slots length matches the node's fixed arity, when declared.
        if c.arity is not None and len(c.slots) != c.arity:
            raise AssertionError(
                f"{c.name!r}: arity={c.arity} but slots={c.slots!r} "
                f"(length {len(c.slots)})"
            )

        # 3. no two entries claim the same latex spelling.
        if c.latex is not None:
            if c.latex in seen_latex:
                raise AssertionError(
                    f"latex spelling {c.latex!r} claimed by both "
                    f"{seen_latex[c.latex]!r} and {c.name!r}"
                )
            seen_latex[c.latex] = c.name

        # 3b. exactly one of latex/variants/no_macro (Part 4): a
        # macro-bearing construct has exactly one fixed spelling or a
        # variants dict, never both and never neither; a no_macro
        # primitive has neither.
        macro_fields = (c.latex is not None) + (c.variants is not None)
        if c.no_macro:
            if macro_fields:
                raise AssertionError(
                    f"{c.name!r}: no_macro=True but latex/variants is also set"
                )
        elif macro_fields != 1:
            raise AssertionError(
                f"{c.name!r}: exactly one of latex/variants must be set "
                f"(or no_macro=True); got latex={c.latex!r} "
                f"variants={'set' if c.variants is not None else None}"
            )

        # 4. every entry has either a declaration or a callable for each of
        # parse/emit/serialize -- never neither.
        if c.parse is None:
            raise AssertionError(f"{c.name!r}: no parse declaration or callable")
        if c.emit is None:
            raise AssertionError(f"{c.name!r}: no emit declaration or callable")
        if c.serialize is None:
            raise AssertionError(f"{c.name!r}: no serialize declaration or callable")

        # 5. every OMML element name used is inside the Rule 0 closed set.
        omml_names = c.omml if isinstance(c.omml, tuple) else (c.omml,)
        for elem in omml_names:
            if elem is not None and elem not in OMML_ELEMENTS:
                raise AssertionError(
                    f"{c.name!r}: omml element {elem!r} is outside the "
                    f"Rule 0 closed set of {len(OMML_ELEMENTS)}"
                )

    missing = set(ALL_NODE_TYPES) - set(seen_nodes)
    if missing:
        raise AssertionError(
            "node types with no construct table entry: "
            + ", ".join(t.__name__ for t in missing)
        )


_validate(CONSTRUCTS)


def _build_macro_index(constructs):
    """`macro -> (Construct, props)`, derived from `latex`/`variants` --
    never hand-written a second time. Asserted injective at import: no
    macro may be claimed by two constructs, since that is exactly the
    ambiguity R2b's parser needs this index to *not* have (see
    CONSTRUCTS["limit"]'s comment for the one family, movable-limit
    operator names, deliberately left out of a construct's `variants` to
    avoid violating this)."""

    index = {}
    for c in constructs:
        if c.latex is not None:
            spellings = {c.latex: {}}
        elif c.variants is not None:
            spellings = c.variants
        else:
            continue
        for macro, props in spellings.items():
            if macro in index:
                other, _ = index[macro]
                raise AssertionError(
                    f"macro {macro!r} claimed by both {other.name!r} and "
                    f"{c.name!r} -- MACRO_TO_CONSTRUCT must be injective"
                )
            index[macro] = (c, props)
    return index


MACRO_TO_CONSTRUCT = _build_macro_index(CONSTRUCTS)

CONSTRUCTS_BY_NAME = {c.name: c for c in CONSTRUCTS}
CONSTRUCTS_BY_NODE = {c.node: c for c in CONSTRUCTS}

# Every family derived from a mathsyms table must actually produce macro
# entries -- an empty result would mean the source table was empty or
# renamed out from under this module without anyone noticing (a silent
# derivation-produces-nothing failure, exactly what the coordinator asked
# this check to catch loudly instead).
for _derived_name, _source_table in (
    ("opname", KNOWN_FUNC_MACROS),
    ("accent", ACCENT_TO_CHAR),
    ("nary", NARY_MACROS),
    ("space", SPACE_MACRO_TO_GLYPH),
):
    assert _source_table, f"{_derived_name}'s source table is empty"
    _count = sum(1 for _c, _p in MACRO_TO_CONSTRUCT.values() if _c.name == _derived_name)
    assert _count > 0, f"{_derived_name}: derived family produced no macro entries"
