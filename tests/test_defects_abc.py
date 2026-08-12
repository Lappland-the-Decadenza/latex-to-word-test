"""Regression tests for three independent defects, all measured against the
user's 18 real Word documents (see the task brief that accompanied this
change):

- Defect A: the bar accent (``\\bar``) was dropped entirely on the reverse
  path because Word's own combining character (U+0305 COMBINING OVERLINE)
  had no entry in ``mathsyms.ACCENT_REVERSE``.
- Defect B: ``\\ln \\sum_{k} a_k`` lost its ``m:func`` object because the R2b
  function-application operand rule did not accept an n-ary as an operand.
- Defect C: a literal ``~`` inside a Word math run was silently rewritten to
  ``\\quad`` (whitespace) instead of surviving as the character it is.
"""

import os
import sys

from lxml import etree

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from latexword.math import ast as A
from latexword.math import latex2omml as L
from latexword.math import omml2latex as W

M = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def qm(tag):
    return f"{{{M}}}{tag}"


def _build_acc_element(chr_val, base_text="x"):
    acc_el = etree.Element(qm("acc"))
    pr = etree.SubElement(acc_el, qm("accPr"))
    c = etree.SubElement(pr, qm("chr"))
    c.set(qm("val"), chr_val)
    e = etree.SubElement(acc_el, qm("e"))
    r = etree.SubElement(e, qm("r"))
    t = etree.SubElement(r, qm("t"))
    t.text = base_text
    return acc_el


# --- Defect A: bar accent -----------------------------------------------


def test_bar_emits_combining_overline():
    """`\\bar{x}` must emit `m:acc` with `chr` = U+0305 COMBINING OVERLINE
    -- what Word actually writes for its bar accent (see the census in
    mathsyms.ACCENT_REVERSE's comment), not U+0304 COMBINING MACRON."""
    om = L.emit(L.parse(r"\bar{x}"))
    acc = om.find(qm("acc"))
    assert acc is not None
    chr_el = acc.find(qm("accPr")).find(qm("chr"))
    assert chr_el.get(qm("val")) == "̅"


def test_macron_still_reverses_to_bar():
    """A document written with the older/rarer U+0304 COMBINING MACRON must
    still reverse to `\\bar` (mathsyms.ACCENT_REVERSE_ALIASES)."""
    acc_el = _build_acc_element("̄")
    assert W.to_latex(acc_el) == r"\bar{x}"


def test_overline_char_also_reverses_to_bar():
    """U+0305 itself (the now-canonical forward spelling) must also reverse
    correctly through the primary ACCENT_REVERSE table."""
    acc_el = _build_acc_element("̅")
    assert W.to_latex(acc_el) == r"\bar{x}"


def test_overline_macro_still_emits_m_bar_not_m_acc():
    """`\\overline{x}` is a structurally different construct (`Bar` -> `m:bar`,
    spans the whole base) from `\\bar{x}` (`Accent` -> `m:acc`, one character).
    This must not regress while fixing the accent character."""
    om = L.emit(L.parse(r"\overline{x}"))
    assert om.find(qm("bar")) is not None
    assert om.find(qm("acc")) is None


# --- Defect B: function application over an n-ary ------------------------


def test_ln_sum_keeps_m_func_around_the_nary():
    """`\\ln \\sum_{k} a_k` must produce one `m:func(name=ln, argument=nary)`,
    not a bare `ln` run beside a separate `m:nary`."""
    tree = L.parse(r"\ln \sum_{k} a_k")
    assert len(tree.items) == 1
    outer = tree.items[0]
    assert isinstance(outer, A.Func)
    assert isinstance(outer.name, A.OpName) and outer.name.name == "ln"
    assert isinstance(outer.arg, A.Nary), (
        f"the sum must be \\ln's operand, not a sibling: got {outer.arg!r}"
    )

    om = L.emit(L.parse(r"\ln \sum_{k} a_k"))
    func = om.find(qm("func"))
    assert func is not None
    assert om.find(qm("nary")) is None, (
        "the nary must be nested inside m:func's argument, not a top-level "
        "sibling"
    )
    e_el = func.find(qm("e"))
    assert e_el.find(qm("nary")) is not None


def test_ln_tan_chain_still_right_associates():
    """Pinned behaviour (test_defect1_operator_name_chains_right_associate in
    test_r3_emitter.py): the n-ary operand fix must not disturb the ordinary
    operator-name chaining rule."""
    tree = L.parse(r"\ln \tan x")
    outer = tree.items[0]
    assert isinstance(outer, A.Func)
    assert isinstance(outer.name, A.OpName) and outer.name.name == "ln"
    assert isinstance(outer.arg, A.Func)
    assert outer.arg.name.name == "tan"


# --- Defect C: literal tilde ----------------------------------------------


def test_literal_tilde_word_run_round_trips_through_text():
    """A literal U+007E in a Word math run must survive a reverse-then-
    forward round trip as U+007E, not become whitespace."""
    om_el = etree.Element(qm("oMath"))
    r = etree.SubElement(om_el, qm("r"))
    t = etree.SubElement(r, qm("t"))
    t.text = "h ~ 0.1"

    tex = W.to_latex(om_el)
    assert "\\quad" not in tex, "the tilde must not be rewritten to whitespace"
    assert "\\textasciitilde" in tex

    ast = L.parse(tex)
    rendered_omml = L.emit(ast)
    text_content = "".join(
        el.text or "" for el in rendered_omml.iter(qm("t"))
    )
    assert "~" in text_content


def test_text_tilde_serializes_and_reparses_stably():
    tex = r"\text{\textasciitilde}"
    ast = L.parse(tex)
    assert isinstance(ast.items[0], A.Text)
    assert ast.items[0].s == "~"
    canon = L.serialize(ast)
    assert L.parse(canon).items[0].s == "~"


# --- \text{} escape decoding ------------------------------------------------


def test_text_escape_decoding():
    """`\\text{}` content must decode the standard text-mode escapes to the
    characters they mean, not pass the backslash-spelling through literally
    (defect C's root cause, not just the tilde case it was found through)."""
    cases = {
        r"\text{50\%}": "50%",
        r"\text{a\&b}": "a&b",
        r"\text{a\_b}": "a_b",
        r"\text{\$5}": "$5",
        r"\text{\#1}": "#1",
        r"\text{\{x\}}": "{x}",
        r"\text{\textasciitilde}": "~",
        r"\text{\textasciicircum}": "^",
        r"\text{\textasciitilde{}0.1}": "~0.1",
    }
    for tex, expected in cases.items():
        node = L.parse(tex).items[0]
        assert isinstance(node, A.Text)
        assert node.s == expected, f"{tex!r} decoded to {node.s!r}, expected {expected!r}"


def test_text_escape_round_trips_through_omml():
    """The decoded characters must reach the OMML run literally (so Word
    renders "50%", not the backslash-escaped source), and the emitted OMML
    must re-parse back through word2latex to compilable, escaped LaTeX."""
    om = L.emit(L.parse(r"\text{50\%}"))
    text_content = "".join(el.text or "" for el in om.iter(qm("t")))
    assert text_content == "50%"
