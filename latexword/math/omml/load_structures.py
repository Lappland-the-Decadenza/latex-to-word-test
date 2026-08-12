"""OMML structural element-to-AST loaders."""

from . import load_shared as _shared
globals().update({name: getattr(_shared, name) for name in _shared.__all__})

def _is_single_atom(node):
    """True if the node serializes to exactly one top-level item of the
    forward parser -- the same check the old walker ran on the *string*,
    run here on the node via its own serialization."""
    # Every non-Row AST node is an atom in the construct table.  A Row is
    # the only node that can contain more than one top-level atom; keeping
    # this test structural prevents the OMML loader from importing the
    # native-LaTeX parser and preserves the adapter boundary.
    return not isinstance(node, Row) or len(node.items) == 1


def _has_following_content_sibling(el):
    """Task A: whether anything real (not a `*Pr` property child) follows
    `el` in its parent row -- the only fact that decides whether a bare
    single-atom operand is safe to leave unbraced."""
    parent = el.getparent()
    if parent is None:
        return False
    siblings = list(parent)
    idx = siblings.index(el)
    for sib in siblings[idx + 1:]:
        if not ln(sib).endswith("Pr"):
            return True
    return False


def _body_braced(el, node):
    """The walker's rule-16 decision for an n-ary/function operand: brace
    unless it is a single atom AND nothing follows it in the OMML row."""
    if _is_single_atom(node) and not _has_following_content_sibling(el):
        return False
    return True


def _script_slot(el, name):
    """A script slot's content: the single child itself (matching the
    forward parser's `x^{2}` -> `Num("2")` shape), except for a prime run --
    the serializer's prime idiom (`f''`, never `f^{'}` -- a hard parse
    failure) needs the flat `Row` of `Op(PRIME)` items the forward parser
    itself produces for `f''`. Run-level Rows are flattened (`'` and `''`
    in separate runs is still a plain prime run)."""
    slot = _find(el, name)
    if slot is None:
        return None
    items = []
    for c in slot:
        node = load(c)
        if node is None:
            continue
        if isinstance(node, Row):
            items.extend(node.items)
        else:
            items.append(node)
    if not items:
        return None
    if len(items) == 1 and not (isinstance(items[0], Op)
                                and items[0].char == PRIME):
        return items[0]
    return Row(tuple(items))


def _load_script(el):
    base_el = _find(el, "e")
    base = _row_or_single(base_el) if base_el is not None else None
    base = base if base is not None else Row(())
    sub = _script_slot(el, "sub")
    sup = _script_slot(el, "sup")
    return Script(base, sub, sup)


def _load_frac(el):
    fpr = _find(el, "fPr")
    type_el = _find(fpr, "type") if fpr is not None else None
    ftype = _attr(type_el, "val", "bar") if type_el is not None else "bar"
    num = _arg(el, "num") or Row(())
    den = _arg(el, "den") or Row(())
    return Frac(num, den, ftype)


def _load_rad(el):
    radpr = _find(el, "radPr")
    hide_el = _find(radpr, "degHide") if radpr is not None else None
    hidden = _attr(hide_el, "val") == "on" if hide_el is not None else False
    e = _arg(el, "e") or Row(())
    if hidden:
        return Rad(e, None)
    deg = _arg(el, "deg")
    if deg is None:
        return Rad(e, None)
    return Rad(e, deg)


def _load_nary(el):
    narypr = _find(el, "naryPr")
    chr_el = _find(narypr, "chr") if narypr is not None else None
    limloc_el = _find(narypr, "limLoc") if narypr is not None else None
    sub_hide_el = _find(narypr, "subHide") if narypr is not None else None
    sup_hide_el = _find(narypr, "supHide") if narypr is not None else None
    ch = _attr(chr_el, "val", "\u222b") if chr_el is not None else "\u222b"
    sub_hidden = (_attr(sub_hide_el, "val") == "on"
                  if sub_hide_el is not None else False)
    sup_hidden = (_attr(sup_hide_el, "val") == "on"
                  if sup_hide_el is not None else False)

    sub = _arg(el, "sub")
    sup = _arg(el, "sup")
    body = _arg(el, "e")
    body = body if body is not None else Row(())

    # The schema default for an absent limLoc is subSup -- not the
    # character's own default -- and the tri-state carries the fact so the
    # serializer writes \limits/\nolimits exactly when the placement
    # differs from the character's default (mirrors the old walker).
    limloc = (_attr(limloc_el, "val", "subSup")
              if limloc_el is not None else "subSup")
    limits = limloc == "undOvr"

    return Nary(
        ch,
        sub if not sub_hidden else None,
        sup if not sup_hidden else None,
        body,
        limits,
        _body_braced(el, body),
    )


# Opening delimiter pair -> environment name, derived from the construct
# table's matrix variants (the old walker's ENV_FOR_DELIMS).
_ENV_FOR_DELIMS = {
    (props["begChr"], props["endChr"] if props["endChr"] is not None else ""): env
    for env, props in ast.CONSTRUCTS_BY_NAME["matrix"].variants.items()
    if props["begChr"] is not None
}


def _load_delim(el):
    dpr = _find(el, "dPr")
    beg = _attr(_find(dpr, "begChr"), "val", "(") if dpr is not None else "("
    end = _attr(_find(dpr, "endChr"), "val", ")") if dpr is not None else ")"
    sep = _attr(_find(dpr, "sepChr"), "val", ",") if dpr is not None else ","
    e_children = el.findall(qm("e"))

    if len(e_children) == 1:
        inner_kids = list(e_children[0])
        if len(inner_kids) == 1:
            sole = inner_kids[0]
            if ln(sole) == "m":
                env = _ENV_FOR_DELIMS.get((beg, end))
                if env:
                    matrix = _load_matrix(sole, env)
                    if matrix.cols is not None and any(
                            c != "c" for c in matrix.cols):
                        # CANONICAL.md's array rule: a non-centred matrix
                        # keeps its delimiters explicitly around the array.
                        return Delim(beg or None, end or None,
                                     (Row((matrix,)),))
                    return matrix
            if ln(sole) == "eqArr":
                env = _ENV_FOR_DELIMS.get((beg, end))
                if env:
                    return _load_eqarr(sole, env)
            if ln(sole) == "f" and beg == "(" and end == ")":
                fpr = _find(sole, "fPr")
                type_el = _find(fpr, "type") if fpr is not None else None
                ftype = (_attr(type_el, "val", "bar")
                         if type_el is not None else "bar")
                if ftype == "noBar":
                    return Frac(_arg(sole, "num"), _arg(sole, "den"),
                                "noBar", paren=True)

    # The separator is content in the reverse spelling ("a , b"), so it
    # becomes an Op inside the single item row -- exactly what the old
    # walker's "sep"-joined text parses to.
    items = []
    for i, e in enumerate(e_children):
        if i:
            items.append(Op(sep))
        content = _row_or_single(e)
        if content is not None:
            items.append(content)
    content = Row(tuple(items)) if items else Row(())

    return Delim(beg or None, end or None, (content,))


def _upright_name_node(text, is_mathrm=False):
    """A sty="p" name as an `OpName`: known names compact to their macro
    spelling ("lim sup" -> "limsup"); unknown names keep their text and
    serialize as \\operatorname (or \\mathrm when `is_mathrm`)."""
    compact = text.replace("\u2006", "").replace(" ", "")
    if compact in KNOWN_FUNC_MACROS:
        return OpName(compact)
    return OpName(text.strip(), is_mathrm=is_mathrm)


def _load_func(el):
    fname_el = _find(el, "fName")
    e_el = _find(el, "e")
    inner = list(fname_el)[0] if fname_el is not None and len(fname_el) else None
    if inner is not None and ln(inner) == "r":
        text = "".join(t.text or "" for t in inner.iter(qm("t")))
        name = _upright_name_node(text)
    elif inner is not None and ln(inner) in ("sSup", "sSub", "sSubSup"):
        base_el = _find(inner, "e")
        base_el = list(base_el)[0] if base_el is not None and len(base_el) else None
        if base_el is not None and ln(base_el) == "r":
            base = _upright_name_node(
                "".join(t.text or "" for t in base_el.iter(qm("t"))))
            name = Script(base, _arg(inner, "sub"), _arg(inner, "sup"))
        else:
            name = load(inner) if inner is not None else None
    else:
        name = load(inner) if inner is not None else None
    name = name if name is not None else Row(())
    operand = _row_or_single(e_el) if e_el is not None else None
    if operand is None:
        operand = Row(())
    return Func(name, operand, _body_braced(el, operand))


def _load_acc(el):
    accpr = _find(el, "accPr")
    chr_el = _find(accpr, "chr") if accpr is not None else None
    ch = _attr(chr_el, "val") if chr_el is not None else "\u0302"  # \hat default
    cmd = ACCENT_REVERSE.get(ch) or ACCENT_REVERSE_ALIASES.get(ch)
    if cmd is None:
        # Unknown accent mark: the old walker dropped the mark and returned
        # the bare base -- keep that behaviour.
        return _arg(el, "e")
    return Accent(cmd, _arg(el, "e") or Row(()))


def _load_bar(el):
    barpr = _find(el, "barPr")
    pos_el = _find(barpr, "pos") if barpr is not None else None
    pos = _attr(pos_el, "val", "top") if pos_el is not None else "top"
    return Bar(_arg(el, "e") or Row(()), pos)


def _load_borderbox(el):
    # Â§6.2: m:borderBox -> \boxed. Word's borderBoxPr can carry a real
    # border style; the target inventory keeps only the frame itself, so
    # the pr is dropped (the box is the content, the style is presentation,
    # same call the forward direction's construct table makes).
    return Boxed(_arg(el, "e") or Row(()))


def _load_phant(el):
    # Â§6.2: m:phant -> \phantom. Word's phantPr can carry a `show`
    # property (which pieces render); the corpus only uses the default
    # hidden form, so a shown phantom reads back as the plain phantom with
    # the visibility lost -- an unrecognised property, degraded exactly
    # like the other unrecognised properties in this pipeline (see the
    # construct table's comment on "phantom").
    return Phantom(_arg(el, "e") or Row(()))


# \overbrace/\underbrace as a legacy brace glyph in a lim slot (D3): the
# old forward pipeline emitted munder/mover with the brace character.
BRACE_MARKS = {"\u23de": "overbrace", "\u23df": "underbrace"}


def _plain_name_text(el):
    if el is not None and ln(el) == "r":
        text = "".join(t.text or "" for t in el.iter(qm("t")))
        compact = text.replace("\u2006", "").replace(" ", "")
        if compact.isalpha():
            return text
    return None


def _sole_char_text(el):
    if el is None:
        return None
    text = "".join(t.text or "" for t in el.iter(qm("t"))).strip()
    return text if text else None


def _load_lim(el, under):
    e_child = _find(el, "e")
    lim_child = _find(el, "lim")
    lim = _arg(el, "lim")
    inner = list(e_child)[0] if e_child is not None and len(e_child) else None

    lim_text = _sole_char_text(lim_child)
    if lim_text in BRACE_MARKS:
        return GroupChr(_arg(el, "e"), lim_text,
                        "bot" if lim_text == "\u23df" else "top")

    if inner is not None and ln(inner) in ("limLow", "limUpp"):
        inner_lim_text = _sole_char_text(_find(inner, "lim"))
        if inner_lim_text in BRACE_MARKS:
            base = _arg(inner, "e")
            brace = GroupChr(base, inner_lim_text,
                             "bot" if inner_lim_text == "\u23df" else "top")
            return Script(brace, lim if under else None,
                          lim if not under else None)

        # Movable limits on both sides: nested limLow/limUpp flatten to one
        # scripted operator-name base.
        if ln(inner) != ln(el):
            inner_e = _find(inner, "e")
            base_el = (list(inner_e)[0]
                       if inner_e is not None and len(inner_e) else None)
            base_text = _plain_name_text(base_el)
            if base_text is not None:
                base = _upright_name_node(base_text)
                inner_lim = _arg(inner, "lim")
                if ln(el) == "limLow":
                    return Script(base, lim, inner_lim)
                return Script(base, inner_lim, lim)

    base_text = _plain_name_text(inner)
    if base_text is not None:
        base = _upright_name_node(base_text)
        return Limit(base, lim, "low" if under else "upp")

    return Limit(_arg(el, "e"), lim, "low" if under else "upp")


def _load_groupchr(el):
    pr = _find(el, "groupChrPr")
    pos_el = _find(pr, "pos") if pr is not None else None
    pos = _attr(pos_el, "val", "top") if pos_el is not None else "top"
    return GroupChr(_arg(el, "e"), "\u23de", pos)


def _load_matrix(el, env="matrix"):
    rows = []
    ncols = 0
    for mr in el.findall(qm("mr")):
        cells = tuple(_row_or_single(e) or Row(())
                      for e in mr.findall(qm("e")))
        ncols = max(ncols, len(cells))
        rows.append(cells)
    cols = _matrix_col_spec(el, ncols)
    # CANONICAL.md's array rule: a non-centred column spec spells `array`,
    # whatever environment the surrounding m:d implied -- `_ser_matrix`
    # reads `cols` only when env == "array" (mirrors the old walker's
    # `_matrix_to_latex`, which returned the array spelling regardless of
    # the env it was given).
    if cols is not None:
        env = "array"
    return Matrix(tuple(rows), env, cols)


def _load_eqarr(el, env="matrix"):
    """m:eqArr -- the equation array Word writes for aligned/gathered
    formulas: m:e rows with no m:mr grid, one cell per row. Loaded as a
    one-column matrix so the row breaks survive; a delimiter-wrapped eqArr
    spells the matrix variant env (`_ENV_FOR_DELIMS`), so |...| callouts
    keep their bars stretching over all rows instead of one line."""
    rows = tuple(
        (_row_or_single(e) or Row(()),) for e in el.findall(qm("e")))
    return Matrix(rows, env, None)


# mcJc -> the array column-spec letter (the schema only allows these three).
_MCJC_TO_COL = {"left": "l", "center": "c", "right": "r"}


def _matrix_col_spec(m_el, ncols):
    """Read `m:mPr/m:mcs`: a column-letter tuple when at least one column's
    justification is not `center` (CANONICAL.md's array rule), else `None`."""
    mpr = _find(m_el, "mPr")
    mcs = _find(mpr, "mcs") if mpr is not None else None
    if mcs is None:
        return None
    cols = []
    for mc in mcs.findall(qm("mc")):
        mcpr = _find(mc, "mcPr")
        count = (int(_attr(_find(mcpr, "count"), "val", "1"))
                 if mcpr is not None else 1)
        jc = (_attr(_find(mcpr, "mcJc"), "val", "center")
              if mcpr is not None else "center")
        cols.extend([_MCJC_TO_COL.get(jc, "c")] * max(count, 1))
    if not cols or all(c == "c" for c in cols):
        return None
    if len(cols) < ncols:
        cols += ["c"] * (ncols - len(cols))
    return tuple(cols[:ncols]) if ncols else tuple(cols)


# --- The dispatcher ----------------------------------------------------------
