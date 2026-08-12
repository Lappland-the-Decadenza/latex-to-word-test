"""Regression test for the last measured fidelity degradation: a two-column
`m:m` whose `m:mPr/m:mcs` carries per-column `m:mcJc` (right, left) instead
of the ordinary single all-columns-share-one-alignment shape. The old
reverse converter always emitted `\\begin{matrix}` (no column-alignment
concept in LaTeX), silently discarding both `mcJc` values -- 1 formula
measured across the corpus (one hand-authored corpus document).

CANONICAL.md's array rule: the standard `array` environment with a column
spec (`\\begin{array}{rl}`) is the explicit LaTeX spelling, written only
when at least one column's justification is not `center` (Rule 0's "never a
redundant override" discipline).
"""

import os
import sys

from lxml import etree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from latexword.math import ast as A
from latexword.math import latex2omml as L
from latexword.math import omml2latex as W

M = A.M_NS


def qm(tag):
    return f"{{{M}}}{tag}"


def _cell(text):
    e = etree.Element(qm("e"))
    r = etree.SubElement(e, qm("r"))
    t = etree.SubElement(r, qm("t"))
    t.text = text
    return e


def _build_m_with_col_jc(jcs, rows):
    """Build a bare `m:m` element whose `m:mPr/m:mcs` has one `m:mc` per
    entry in `jcs` (each `count="1"`), and the given row-major text cells."""
    m = etree.Element(qm("m"))
    pr = etree.SubElement(m, qm("mPr"))
    etree.SubElement(pr, qm("baseJc")).set(qm("val"), "center")
    etree.SubElement(pr, qm("plcHide")).set(qm("val"), "on")
    mcs = etree.SubElement(pr, qm("mcs"))
    for jc in jcs:
        mc = etree.SubElement(mcs, qm("mc"))
        mcPr = etree.SubElement(mc, qm("mcPr"))
        etree.SubElement(mcPr, qm("count")).set(qm("val"), "1")
        etree.SubElement(mcPr, qm("mcJc")).set(qm("val"), jc)
    for row in rows:
        mr = etree.SubElement(m, qm("mr"))
        for text in row:
            mr.append(_cell(text))
    return m


def test_omml_with_nondefault_column_jc_reverses_to_array():
    m = _build_m_with_col_jc(["right", "left"], [["a", "b"], ["c", "d"]])
    tex = W.to_latex(m)
    assert tex.startswith(r"\begin{array}{rl}")
    assert r"\end{array}" in tex
    assert "a" in tex and "b" in tex and "c" in tex and "d" in tex


def test_omml_with_all_centre_column_jc_keeps_plain_env():
    """No churn: an ordinary all-`center` `m:mcs` (whether the single-`m:mc`
    shape or an explicit one-per-column all-`center` shape) must not become
    `array` -- Rule 0's discipline against a redundant override."""
    m = _build_m_with_col_jc(["center", "center"], [["a", "b"], ["c", "d"]])
    tex = W.to_latex(m)
    assert tex.startswith(r"\begin{matrix}")


def test_full_round_trip_omml_to_array_and_back_to_omml():
    """OMML (per-column mcJc) -> `\\begin{array}{rl}` (word2latex) ->
    re-parse -> re-emit (latex2omml) must reproduce identical column
    properties -- the round trip this defect broke."""
    m = _build_m_with_col_jc(["right", "left"], [["a", "b"], ["c", "d"]])
    tex = W.to_latex(m)

    ast = L.parse(tex)
    assert isinstance(ast, A.Row) and len(ast.items) == 1
    ast = ast.items[0]
    assert isinstance(ast, A.Matrix)
    assert ast.env == "array"
    assert ast.cols == ("r", "l")

    om = L.emit(ast)
    m2 = om.find(qm("m"))
    mcs = m2.find(qm("mPr")).find(qm("mcs"))
    mc_list = mcs.findall(qm("mc"))
    assert len(mc_list) == 2
    jcs = [mc.find(qm("mcPr")).find(qm("mcJc")).get(qm("val")) for mc in mc_list]
    counts = [mc.find(qm("mcPr")).find(qm("count")).get(qm("val")) for mc in mc_list]
    assert jcs == ["right", "left"]
    assert counts == ["1", "1"]


def test_array_inside_delimiters_keeps_left_right():
    """CANONICAL.md's array rule, clause 4: array carries no delimiters of
    its own, so a matrix that would otherwise have been `pmatrix` but has
    non-centred columns keeps its `\\left(`/`\\right)` explicitly rather
    than losing them."""
    m = _build_m_with_col_jc(["right", "left"], [["a", "b"], ["c", "d"]])
    d = etree.Element(qm("d"))
    dpr = etree.SubElement(d, qm("dPr"))
    etree.SubElement(dpr, qm("begChr")).set(qm("val"), "(")
    etree.SubElement(dpr, qm("endChr")).set(qm("val"), ")")
    e = etree.SubElement(d, qm("e"))
    e.append(m)
    tex = W.to_latex(d)
    assert tex.startswith(r"\left(")
    assert tex.endswith(r"\right)")
    assert r"\begin{array}{rl}" in tex
