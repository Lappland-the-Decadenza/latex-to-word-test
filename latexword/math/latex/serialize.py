# Canonical AST serializer

import re

from ..ast import (
    Accent, Bar, Boxed, CONSTRUCTS_BY_NAME, Delim, Frac, Func, GroupChr,
    Ident, Limit, Matrix, Nary, Num, Op, OpName, Phantom, PreScript, Rad,
    Row, Script, Space, Text,
)
from ..common import (
    _ESCAPED_LITERALS, _NARY_CONSTRUCT, _NARY_LIMITS_MODIFIER,
    _NARY_NOLIMITS_MODIFIER, _SPACE_SPELLING, _VARIANT_SPELLING,
    PRIME,
)
from ...mathsyms import (
    DELIM_LEFTRIGHT, KNOWN_FUNC_MACROS, NARY_UNDOVR, SYMBOL_MAP,
    VARIANT_REVERSE,
)
from .parse import parse, _is_opname_expr

# --- Serialization: this *is* canonicalize() -------------------------------

_MACRO_TAIL = re.compile(r"\\[a-zA-Z]+\Z")


def _join(parts):
    """Rule 7.1/7.2: exactly one space after a macro name followed by a
    letter or digit, none otherwise. Applied at the join, because whether a
    space is needed is a property of the *pair*, not of either token."""
    out = []
    for part in parts:
        if not part:
            continue
        if out and _MACRO_TAIL.search(out[-1]) and part[0].isalnum():
            out.append(" ")
        out.append(part)
    return "".join(out)


def _char_latex(ch):
    """One resolved character back to its canonical macro (Rule 8)."""
    if ch in _ESCAPED_LITERALS.values():
        return "\\" + ch
    if ch == PRIME:
        # The prime's canonical spelling is the ASCII apostrophe (`f''`,
        # Rule 6) -- reachable here only from a bare Op(PRIME) sitting in a
        # row (the script prime path never calls _char_latex).
        return "'"
    macro = SYMBOL_MAP.get(ch)
    if macro:
        return macro
    return ch


def _variant_group(items):
    """Split a Row's items into maximal same-variant runs (Rule 10:
    `\\mathbf{ABC}`, never `\\mathbf{A}\\mathbf{B}\\mathbf{C}`)."""
    groups = []
    for item in items:
        variant = None
        if isinstance(item, (Ident, Num, Op)):
            char = item.char if isinstance(item, (Ident, Op)) else item.text
            info = VARIANT_REVERSE.get(char) if len(char) == 1 else None
            if info is not None:
                variant = info[1]
        if variant is not None and groups and groups[-1][0] == variant:
            groups[-1][1].append(item)
        else:
            groups.append((variant, [item]))
    return groups


def _wrap_variant(text, variant):
    macros = _VARIANT_SPELLING.get(variant)
    if macros is None:  # pragma: no cover - _VARIANT_SPELLING covers the table
        return text
    out = text
    for macro in reversed(macros):
        out = "\\%s{%s}" % (macro, out)
    return out


def _ser_row(items):
    parts = []
    for variant, group in _variant_group(items):
        if variant is None:
            parts.extend(_ser(item) for item in group)
        else:
            plain = "".join(
                VARIANT_REVERSE[item.char if isinstance(item, (Ident, Op))
                                else item.text][0]
                for item in group)
            parts.append(_wrap_variant(plain, variant))
    return _join(parts)


def _braced(node):
    """A node as a macro/script argument: always braced (Rule 6)."""
    return "{%s}" % _ser(node)


def _script_base(node):
    """A script's base. Braced only when the base is not a single atom of
    the forward parser -- grouping is load-bearing there and must survive
    (`{a+b}^{2}`). The check is parse-based, not AST-shape-based, because
    several AST items can serialize into one atom: a sty="p" run "10"
    loaded as `Num("1")`, `Num("0")` serializes to `10`, which parses as
    one `Num` -- bracing that would invent braces the source never had
    (mirrors the old reverse walker's `_is_single_atom` check)."""
    latex = _ser(node)
    try:
        row = parse(latex)
    except Exception:
        return "{%s}" % latex
    if isinstance(row, Row) and len(row.items) == 1:
        return latex
    return "{%s}" % latex


def _is_prime_run(node):
    return (isinstance(node, Row) and node.items
            and all(isinstance(x, Op) and x.char == PRIME for x in node.items))


def _ser_script(node):
    base = _script_base(node.base)
    # Rule 6: primes stay literal (f''), never f^{\prime\prime} and never
    # the compound codepoints (defect D8).
    if node.sup is not None and _is_prime_run(node.sup):
        primes = "'" * len(node.sup.items)
        if node.sub is None:
            return base + primes
        return "%s%s_%s" % (base, primes, _braced(node.sub))
    out = base
    if node.sub is not None:
        out += "_" + _braced(node.sub)
    if node.sup is not None:
        out += "^" + _braced(node.sup)
    return out


def _opname_latex(node):
    """Rule 2: a standard operator uses its own macro; otherwise
    `\\operatorname{...}` for a genuine operator name or `\\mathrm{...}` for
    plain upright text (`OpName.is_mathrm`) -- both spell the identical
    `m:r`/`sty="p"` shape, so which one a *standalone* (non-`m:func`) run
    reverses to is picked by `math.load._load_run` the same way this
    mirrors it: known name wins regardless of source, `is_mathrm` breaks
    the remaining tie."""
    if node.name in KNOWN_FUNC_MACROS:
        return KNOWN_FUNC_MACROS[node.name]
    if node.is_mathrm:
        return "\\mathrm{%s}" % node.name
    return "\\operatorname{%s}" % node.name


def _ser_limit(node):
    """`\\lim_{...}` when the base is an operator name (that is the shape
    `math.load._load_lim` produces), `\\underset`/`\\overset` otherwise."""
    lim = _braced(node.lim)
    inner = node.base
    if (node.pos == "low" and isinstance(inner, Limit) and inner.pos == "upp"
            and _is_opname_expr(inner.base)):
        return "%s_%s^%s" % (_ser(inner.base), lim, _braced(inner.lim))
    if _is_opname_expr(inner):
        return "%s%s%s" % (_ser(inner), "_" if node.pos == "low" else "^", lim)
    macro = "underset" if node.pos == "low" else "overset"
    return "\\%s{%s}%s" % (macro, _ser(node.lim), _braced(node.base))


def _ser_nary(node):
    out = _NARY_SPELLING[node.op]
    # CANONICAL.md n-ary rule: write \limits/\nolimits only when the
    # explicit placement (node.limits) differs from the character's own
    # default (mathsyms.NARY_UNDOVR) -- \sum keeps writing as \sum, never
    # \sum\limits, and only a genuine override gets a modifier.
    if node.limits is not None:
        default_undovr = node.op in NARY_UNDOVR
        if node.limits != default_undovr:
            out += _NARY_LIMITS_MODIFIER if node.limits else _NARY_NOLIMITS_MODIFIER
    if node.sub is not None:
        out += "_" + _braced(node.sub)
    if node.sup is not None:
        out += "^" + _braced(node.sup)
    # Rule 16 (PLAN.md Â§5.1): body_braced is set by math.load when the
    # OMML context demands braces (multi-atom body, or a single-atom body
    # with following row content); the forward parser never sets it, so the
    # canonical forward spelling is unchanged.
    body = _ser(node.body)
    if node.body_braced or _needs_fraction_body_group(node.body):
        body = "{%s}" % body
    return _join([out, body])


def _needs_fraction_body_group(node):
    """Protect a grouped numerator when a fraction is an operand.

    ``\\int{a+b}/c`` would otherwise be reparsed as an integral whose body is
    ``a+b`` followed by a division outside the integral. The extra outer
    group keeps the linear fraction one operand of the surrounding n-ary.
    """
    candidate = (node.items[0] if isinstance(node, Row)
                 and len(node.items) == 1 else node)
    return (isinstance(candidate, Frac) and candidate.kind == "lin"
            and isinstance(candidate.num, Row)
            and len(candidate.num.items) != 1)


def _ser_frac(node):
    """Spell every Word fraction shape with native LaTeX."""
    if node.kind == "lin":
        return "%s/%s" % (_ser_linear_arg(node.num), _ser_linear_arg(node.den))
    spelling = _FRAC_SPELLING[(node.kind, node.paren)]
    if spelling == "\\genfrac":
        return "\\genfrac{}{}{0pt}{}%s%s" % (
            _braced(node.num), _braced(node.den)
        )
    return "%s%s%s" % (
        spelling, _braced(node.num), _braced(node.den)
    )


def _ser_linear_arg(node):
    """Serialize one solidus operand without losing its grouping."""
    body = _ser(node)
    if isinstance(node, Row) and len(node.items) != 1:
        return _braced(node)
    return body


def _ser_delim(node):
    # Joined through `_join`, not "%s%s": Rule 7.1 applies here exactly as it
    # does inside a row. `\left\langle` followed by content starting with a
    # letter reads as the single undefined control sequence `\langlev`, which
    # neither TeX nor this project's own parser accepts -- so the naive
    # concatenation produced LaTeX that would not round-trip.
    return _join([
        "\\left" + DELIM_LEFTRIGHT[node.open or ""],
        " , ".join(_ser(item) for item in node.items),
        "\\right" + DELIM_LEFTRIGHT[node.close or ""],
    ])


def _ser_matrix(node):
    body = " \\\\\n".join(
        " & ".join(_ser(cell) for cell in row) for row in node.rows)
    if node.env == "array":
        colspec = "".join(node.cols)
        return "\\begin{array}{%s}\n%s\n\\end{array}" % (colspec, body)
    return "\\begin{%s}\n%s\n\\end{%s}" % (node.env, body, node.env)


_NARY_SPELLING = {
    props["chr"]: macro
    for macro, props in _NARY_CONSTRUCT.variants.items()
}

# Declarative serializers taken straight from the construct table, so the
# canonical spelling of these constructs is stated once, in mathast.py.
_TABLE_SERIALIZE = {
    Text: lambda n: CONSTRUCTS_BY_NAME["text"].serialize(n.s),
    Accent: lambda n: CONSTRUCTS_BY_NAME["accent"].serialize(n.mark, _ser(n.base)),
    Bar: lambda n: CONSTRUCTS_BY_NAME["bar"].serialize(_ser(n.base), n.pos),
    GroupChr: lambda n: CONSTRUCTS_BY_NAME["groupchr"].serialize(_ser(n.base), n.pos),
    Boxed: lambda n: CONSTRUCTS_BY_NAME["boxed"].serialize(_ser(n.base)),
    Phantom: lambda n: CONSTRUCTS_BY_NAME["phantom"].serialize(_ser(n.base)),
    PreScript: lambda n: CONSTRUCTS_BY_NAME["prescript"].serialize(
        _ser(n.sub), _ser(n.sup), _ser(n.base)),
}

_SERIALIZE = {
    Row: lambda n: _ser_row(n.items),
    Ident: lambda n: _char_latex(n.char),
    Num: lambda n: n.text,
    Op: lambda n: _char_latex(n.char),
    OpName: lambda n: _opname_latex(n),
    Space: lambda n: _SPACE_SPELLING[n.width],
    Script: _ser_script,
    Frac: _ser_frac,
    Rad: lambda n: ("\\sqrt%s" % _braced(n.radicand)) if n.degree is None
    else ("\\sqrt[%s]%s" % (_ser(n.degree), _braced(n.radicand))),
    Nary: _ser_nary,
    Delim: _ser_delim,
    Func: lambda n: _join([_ser(n.name),
                           "{%s}" % _ser(n.arg) if n.operand_braced
                           else _ser(n.arg)]),
    Limit: _ser_limit,
    Matrix: _ser_matrix,
}
_SERIALIZE.update(_TABLE_SERIALIZE)

# Keyed on the full `Frac` identity -- (fPr/type, implied m:d wrapper) --
# because \binom and \genfrac share a type and differ only in the wrapper.
# `setdefault` keeps the first spelling declared for each shape canonical
# (\frac, not \dfrac/\tfrac).
_FRAC_SPELLING = {}
for _macro, _props in CONSTRUCTS_BY_NAME["frac"].variants.items():
    _FRAC_SPELLING.setdefault(
        (_props["type"], _props.get("paren", False)), _macro)


def _ser(node):
    fn = _SERIALIZE.get(type(node))
    if fn is None:
        raise TypeError(f"no serializer for AST node {type(node).__name__}")
    return fn(node)


def serialize(node):
    """AST -> canonical LaTeX (L*, `CANONICAL.md`). This is `canonicalize()`:
    `canonicalize(x) == serialize(parse(x))`, and it is idempotent."""
    return _ser(node)


def canonicalize(tex):
    """Workstream D1's canonicalizer, in the one implementation that exists."""
    return serialize(parse(tex))




__all__ = [name for name in globals() if not name.startswith("__")]
