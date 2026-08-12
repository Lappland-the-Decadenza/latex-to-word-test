"""OMML run-to-AST leaf loader."""

from . import load_shared as _shared
globals().update({name: getattr(_shared, name) for name in _shared.__all__})

_ASCII_MATH_ESCAPES = {
    "%": "\\%", "#": "\\#", "&": "\\&", "$": "\\$",
    "_": "\\_", "{": "\\{", "}": "\\}",
}
_GREEK_BLOCK = range(0x0370, 0x0400)

def _is_literal_text_char(ch):
    """Alphabetic non-ASCII, not Greek, not a variant character, not a known
    symbol: prose that happens to sit in a math zone (see the old walker's
    B8b analysis)."""
    if not ch.isalpha() or ch.isascii():
        return False
    if ord(ch) in _GREEK_BLOCK:
        return False
    if ch in VARIANT_REVERSE:
        return False
    if ch in SYMBOL_MAP:
        return False
    return True


# Alias space glyph -> the canonical glyph it means, derived once from the
# tables (SPACE_CHAR_ALIASES maps alias glyph -> the canonical macro
# spelling; SPACE_TO_LATEX maps canonical glyph -> that same spelling).
_SPACE_ALIAS_TO_GLYPH = {}
for _alias, _spelling in SPACE_CHAR_ALIASES.items():
    for _glyph, _canonical in SPACE_TO_LATEX.items():
        if _canonical == _spelling:
            _SPACE_ALIAS_TO_GLYPH[_alias] = _glyph
            break


def _space_node(ch):
    """One space glyph -> `Space`. Alias glyphs resolve to their canonical
    width; `qquad` (two consecutive U+2003) is recognised at run level, not
    here (see `_load_run`)."""
    canonical = _SPACE_ALIAS_TO_GLYPH.get(ch, ch)
    return Space(canonical)


def _atom(ch):
    """The ordinary leaf for a bare character: `Ident` for a letter, `Num`
    for a digit, `Op` otherwise."""
    if ch.isalpha():
        return Ident(ch)
    if ch.isdigit():
        return Num(ch)
    return Op(ch)


def _load_plain_text(text):
    """Character-level run content -> nodes. The mirror of the old walker's
    `_convert_text_run` scan, emitting nodes: literal-text groups become
    `Text`, primes become `Op(PRIME)` runs, space glyphs `Space`, variant
    characters keep their full character (the row serializer groups and
    wraps them), symbols and ASCII escapes stay `Op` (the serializer's
    `_char_latex` re-escapes), and digit runs accumulate into one `Num`."""
    out = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if _is_literal_text_char(ch):
            # Accumulate the maximal literal run including interior
            # spaces/hyphens; trim a trailing separator that is not followed
            # by more text (matches the old walker's grouping exactly).
            j = i
            while j < n and (_is_literal_text_char(text[j]) or text[j] in " -"):
                j += 1
            k = j
            while k > i and text[k - 1] in " -":
                k -= 1
            out.append(Text(text[i:k]))
            i = k
            continue
        if ch == PRIME:
            j = i
            while j < n and text[j] == PRIME:
                j += 1
            out.extend(Op(PRIME) for _ in range(j - i))
            i = j
            continue
        if ch in _COMPOUND_PRIMES:
            out.extend(Op(PRIME) for _ in range(len(_COMPOUND_PRIMES[ch])))
            i += 1
            continue
        if ch in SPACE_CHARS or ch in SPACE_CHAR_ALIASES:
            out.append(_space_node(ch))
            i += 1
            continue
        variant_info = VARIANT_REVERSE.get(ch)
        if variant_info:
            base, variant = variant_info
            j = i
            while j < n:
                vi = VARIANT_REVERSE.get(text[j])
                if vi and vi[1] == variant:
                    j += 1
                else:
                    break
            out.extend(_variant_atom(text[m], base) for m in range(i, j))
            i = j
            continue
        if ch in SYMBOL_MAP:
            out.append(Op(ch))
            i += 1
            continue
        if ch in _ASCII_MATH_ESCAPES:
            out.append(Op(ch))
            i += 1
            continue
        if ch == "'":
            # Word's equation editor writes primes as ASCII apostrophes in
            # the OMML (the forward parser reads "'" as the prime token too
            # -- `f''` is Script(f, sup=Row(Op(PRIME), Op(PRIME)))).
            out.append(Op(PRIME))
            i += 1
            continue
        if ch == "~":
            # A literal tilde: \text{\textasciitilde} is the canonical
            # spelling (CANONICAL.md rule 7.6); the Text serializer escapes
            # "~" itself.
            out.append(Text("~"))
            i += 1
            continue
        if ch.isdigit():
            j = i
            while j < n and text[j].isdigit():
                j += 1
            out.append(Num(text[i:j]))
            i = j
            continue
        out.append(_atom(ch))
        i += 1
    return Row(tuple(out)) if out else None


def _variant_atom(ch, base):
    """A Mathematical-Alphanumerics character as the node its base letter
    would be -- `Ident`/`Num`/`Op` carrying the *variant* character, which
    the row serializer's variant grouping reconstructs into \\mathbf{...}."""
    if base.isdigit():
        return Num(ch)
    if base.isalpha():
        return Ident(ch)
    return Op(ch)


def _is_space_run(text):
    return bool(text) and set(text) <= (SPACE_CHARS | set(SPACE_CHAR_ALIASES))


def _is_known_opname(text):
    compact = text.replace("\u2006", "").replace(" ", "")
    return compact.isalpha() and compact.isascii() and compact in KNOWN_FUNC_MACROS


def _load_upright_mixed_run(text):
    """Defect 4's segmentation for a sty="p" run whose whole-run check
    failed: maximal alphabetic ASCII segments become `OpName`, everything
    else goes through the ordinary character-level scan."""
    out = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isalpha():
            j = i
            while j < n and text[j].isalpha():
                j += 1
            segment = text[i:j]
            if len(segment) > 1 and segment.isascii():
                if segment in KNOWN_FUNC_MACROS:
                    out.append(OpName(segment))
                else:
                    out.append(OpName(segment, is_mathrm=True))
            else:
                out.append(_load_plain_text(segment))
            i = j
            continue
        node = _load_plain_text(ch)
        if node is not None:
            out.extend(node.items if isinstance(node, Row) else (node,))
        i += 1
    return Row(tuple(out)) if out else None


def _load_run(el):
    """`m:r` -> a leaf node or `Row` of them, mirroring the old walker's
    `_convert_run` decision order: empty, space run, literal text (m:nor),
    sty="p" (whole run, then segmented), plain character scan."""
    rpr = _find(el, "rPr")
    sty = None
    is_literal_text = False
    if rpr is not None:
        sty_el = _find(rpr, "sty")
        sty = _attr(sty_el, "val") if sty_el is not None else None
        is_literal_text = _find(rpr, "nor") is not None
    text = "".join(t.text or "" for t in el.iter(qm("t")))
    if not text:
        if is_literal_text:
            return Text("")
        return None
    if _is_space_run(text):
        if text == "\u2003" * 2:
            return Space("qquad")
        return Row(tuple(_space_node(ch) for ch in text))
    if is_literal_text:
        return Text(text)
    if sty == "p":
        compact = text.replace("\u2006", "").replace(" ", "")
        if compact.isalpha() and compact.isascii():
            if compact in KNOWN_FUNC_MACROS:
                return OpName(compact)
            return OpName(text.strip(), is_mathrm=True)
        return _load_upright_mixed_run(text)
    return _load_plain_text(text)


# --- Structural loaders ------------------------------------------------------
#
# Each mirrors the old walker's converter for that element, producing a
# node. The rule-16 bracing decisions are computed here (where the OMML
# context still exists) and carried on the node.
