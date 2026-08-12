"""Construct handlers used by the recursive-descent parser."""

from . import parse_shared as _shared
globals().update({name: getattr(_shared, name) for name in _shared.__all__})


def _h_frac(p, t, macro, props):
    p.advance()
    if macro == _GENFRAC:
        consume_no_rule_parameters(p, t)
    num = p.parse_argument()
    den = p.parse_argument()
    return Frac(num, den, props["type"], props.get("paren", False))


def _h_rad(p, t, macro, props):
    p.advance()
    degree = p.parse_optional_argument()
    return Rad(p.parse_argument(), degree)


def _h_accent(p, t, macro, props):
    p.advance()
    return Accent(macro[1:], p.parse_argument())


def _h_bar(p, t, macro, props):
    p.advance()
    return Bar(p.parse_argument(), props["pos"])


def _h_groupchr(p, t, macro, props):
    p.advance()
    return GroupChr(p.parse_argument(), props["chr"], props["pos"])


def _h_boxed(p, t, macro, props):
    p.advance()
    return Boxed(p.parse_argument())


def _h_phantom(p, t, macro, props):
    p.advance()
    return Phantom(p.parse_argument())


def _h_limit(p, t, macro, props):
    p.advance()
    lim = p.parse_argument()
    base = p.parse_argument()
    return Limit(base, lim, props["pos"])


def _h_prescript(p, t, macro, props):
    p.advance()
    sup = p.parse_argument()
    sub = p.parse_argument()
    base = p.parse_argument()
    return PreScript(base, sub, sup)


# Defect C: a \text{} argument is captured verbatim by the tokenizer (text
# mode is not math-mode LaTeX, so it is never re-tokenized by this parser),
# but its content can still carry the standard text-mode escapes -- \%, \&,
# \_, \$, \#, \{, \}, plus the two that spell characters with no literal
# form at all, \textasciitilde and \textasciicircum. Left undecoded, "\%"
# reaches the OMML run as two literal characters (backslash, percent)
# instead of "%": broken for every escape in this class, not only the
# tilde whose loss (defect C) surfaced it. The two named macros may be
# terminated by an empty group or a space (`\textasciitilde{}`,
# `\textasciitilde `) -- both must be consumed along with the macro, or the
# terminator survives as stray content.
_TEXT_NAMED_ESCAPE_RE = re.compile(r"\\(textasciitilde|textasciicircum)(\{\}| )?")
_TEXT_PUNCT_ESCAPE_RE = re.compile(r"\\([%&_$#{}])")


def _decode_text_escapes(s):
    s = _TEXT_NAMED_ESCAPE_RE.sub(
        lambda m: TEXT_ESCAPE_TO_CHAR[m.group(1)], s)
    s = _TEXT_PUNCT_ESCAPE_RE.sub(
        lambda m: TEXT_ESCAPE_TO_CHAR[m.group(1)], s)
    return s


def _h_text(p, t, macro, props):
    p.advance()
    arg = p.advance()
    if arg.kind != "rawarg":  # pragma: no cover - tokenizer pairs these
        p.fail(MalformedArgumentError, "\\text without {...}", t)
    return Text(_decode_text_escapes(arg.text))


def _h_space(p, t, macro, props):
    p.advance()
    return Space(props["width"])


def _h_opname(p, t, macro, props):
    p.advance()
    return OpName(macro[1:])


def _h_nary(p, t, macro, props):
    p.advance()
    # Rule 4: a `\limits`/`\nolimits` modifier is legal only directly after
    # the operator token, before any scripts. Consumed here, not through
    # MACRO_TO_CONSTRUCT, so a copy anywhere else falls through to
    # `parse_macro`'s explicit misplaced-modifier check. "Last one wins" on
    # a repeated/conflicting run (`\int\limits\nolimits`) rather than
    # raising -- CANONICAL.md's n-ary rule says so explicitly.
    limits = None
    while True:
        nxt = p.peek()
        if nxt.kind == "macro" and nxt.text == _NARY_LIMITS_MODIFIER:
            p.advance()
            limits = True
            continue
        if nxt.kind == "macro" and nxt.text == _NARY_NOLIMITS_MODIFIER:
            p.advance()
            limits = False
            continue
        break
    sub = sup = None
    while True:
        nxt = p.peek()
        if nxt.kind == "sub":
            if sub is not None:
                p.fail(MalformedArgumentError, "double subscript", nxt)
            p.advance()
            sub = p.parse_argument()
        elif nxt.kind == "sup":
            if sup is not None:
                p.fail(MalformedArgumentError, "double superscript", nxt)
            p.advance()
            sup = p.parse_argument()
        else:
            break
    return _NaryHead(props["chr"], sub, sup, limits)


def _h_delim(p, t, macro, props):
    """A delimiter spelled as a macro but written *bare* (`\\{ x \\}`)."""
    if macro in _BARE_PAIRS:
        return p.parse_bare_delim(t)
    if macro in _BARE_CLOSERS:
        p.fail(UnbalancedDelimiterError, f"{macro} with no matching opener", t)
    # `|`, `\|` and `.`: self-paired or null, unclassifiable bare (Rule 0
    # forbids a content heuristic), so they stay plain glyphs.
    p.advance()
    ch = DELIM_SPELLING_TO_CHAR[macro]
    if not ch:
        p.fail(UnexpectedTokenError, "'.' is only valid after \\left/\\right", t)
    return Op(ch)


_MACRO_HANDLERS = {
    "frac": _h_frac,
    "rad": _h_rad,
    "accent": _h_accent,
    "bar": _h_bar,
    "groupchr": _h_groupchr,
    "boxed": _h_boxed,
    "phantom": _h_phantom,
    "limit": _h_limit,
    "prescript": _h_prescript,
    "text": _h_text,
    "space": _h_space,
    "opname": _h_opname,
    "nary": _h_nary,
    "delim": _h_delim,
}


def _is_opname_expr(node):
    """Rule 2: can this node head an `m:func`? An `OpName`, or a script /
    limit wrapper around one -- `\\sin^{2}`, `\\limsup_{n\\to\\infty}` (see
    `mathast.Func` and the loader's scripted-name unwrapping).

    `OpName.is_mathrm` is excluded: `\\mathrm{d}x` is upright text sitting
    next to `x`, not a named function applied to it -- unlike `\\sin x`,
    nothing about `\\mathrm{...}` means "the following atom is my
    argument", so it must not be swallowed into an `m:func`."""
    if isinstance(node, OpName):
        return not node.is_mathrm
    if isinstance(node, Script):
        return _is_opname_expr(node.base)
    if isinstance(node, Limit):
        return _is_opname_expr(node.base)
    return False


def _apply_variant(node, variant, parser, tok):
    """Rule 10 lowered to the character level: `\\mathbf{ABC}` becomes three
    Mathematical-Alphanumerics idents, exactly what `fix_mathvariant` used to
    produce and what `word2latex` reads back."""

    def conv(n):
        if isinstance(n, Row):
            return Row(tuple(conv(x) for x in n.items))
        if isinstance(n, (Ident, Op)):
            return type(n)(_variant_of(n.char, variant, parser, tok))
        if isinstance(n, Num):
            return Row(tuple(
                Num(_variant_of(c, variant, parser, tok)) for c in n.text))
        if isinstance(n, Accent):
            # ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â§6.2: `\mathbf{\hat{z}}` -- LaTeX bolds the accent's base and
            # leaves the mark alone, so the variant recurses into the base
            # (measured on the .tex corpus, latex22). Other wrappers
            # (Bar, GroupChr, ...) still fail loudly below.
            return Accent(n.mark, conv(n.base))
        parser.fail(UnsupportedConstructError,
                    f"\\{variant} styling cannot be applied to "
                    f"{type(n).__name__}", tok)

    return conv(node)


def _variant_of(ch, variant, parser, tok):
    existing = VARIANT_REVERSE.get(ch)
    if existing is not None:
        base, old = existing
        combined = _VARIANT_COMBINE.get((old, variant))
        if combined is None:
            parser.fail(UnsupportedConstructError,
                        f"variant {variant!r} nested inside {old!r} has no "
                        f"Unicode Mathematical Alphanumerics form", tok)
        ch, variant = base, combined
    # No variant form (punctuation, or a digit in a variant with no digit
    # range): LaTeX's own \mathbf leaves those unstyled too.
    return _VARIANT_CHAR.get((ch, variant), ch)
