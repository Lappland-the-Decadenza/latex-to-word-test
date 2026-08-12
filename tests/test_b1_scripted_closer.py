"""B1 / D10 -- bare closing delimiter carrying a script.

``latex2mathml`` 3.81.0 does not group ``(x+y)`` into its own ``mrow`` when a
script sits on a *bare* closing delimiter (no ``\\left``/``\\right``): the
script wrapper's first child is the closing ``mo`` itself, e.g.
``msup(mo")", mrow(n))`` as a sibling of the opener rather than nested inside
it. ``_tag_implicit_fences`` in ``mathml_normalize.py`` only inspects
top-level ``mo`` siblings, so that buried closer was never tagged, and
``_wrap_tagged_pairs`` folded everything to the end of the row into the fence
with an empty closer -- silently swallowing whatever followed (``= z`` here).

These tests exercise ``mathml_normalize.fix_fences`` directly on parsed
``latex2mathml`` output, since that is where the fix lives and it pins down
the exact tree shape without going through the rest of the pipeline.
"""

import latex2mathml.converter
from lxml import etree

from legacy import mathml_normalize as mn

MML = mn.MML


def q(tag):
    return f"{{{MML}}}{tag}"


def _normalized_row(tex):
    mathml = latex2mathml.converter.convert(tex, display="inline")
    root = etree.fromstring(mathml.encode("utf-8"))
    mrow = root[0]
    mn.fix_fences(mrow)
    return mrow


def _mfenced_interior_text(mfenced):
    row = mfenced[0]
    assert row.tag == q("mrow")
    return [(c.tag.split("}")[-1], (c.text or "")) for c in row]


def test_scripted_closer_paren_does_not_swallow_tail():
    row = _normalized_row(r"(x + y)^{n} = z")
    children = list(row)

    assert [c.tag for c in children] == [q("msup"), q("mo"), q("mi")]
    assert children[1].text == "="
    assert children[2].text == "z"

    msup = children[0]
    fenced = msup[0]
    assert fenced.tag == q("mfenced")
    assert fenced.get("open") == "("
    assert fenced.get("close") == ")"
    assert _mfenced_interior_text(fenced) == [
        ("mi", "x"),
        ("mo", "+"),
        ("mi", "y"),
    ]

    # The script itself (n) must still be the msup's second child.
    assert msup[1].tag == q("mrow")
    assert msup[1][0].text == "n"


def test_scripted_closer_bracket_subscript():
    row = _normalized_row(r"[a]_{i}")
    children = list(row)

    assert len(children) == 1
    msub = children[0]
    assert msub.tag == q("msub")

    fenced = msub[0]
    assert fenced.tag == q("mfenced")
    assert fenced.get("open") == "["
    assert fenced.get("close") == "]"
    assert _mfenced_interior_text(fenced) == [("mi", "a")]

    assert msub[1][0].text == "i"


def test_scripted_closer_brace_superscript():
    row = _normalized_row(r"\{a\}^{2}")
    children = list(row)

    assert len(children) == 1
    msup = children[0]
    assert msup.tag == q("msup")

    fenced = msup[0]
    assert fenced.tag == q("mfenced")
    assert fenced.get("open") == "{"
    assert fenced.get("close") == "}"
    assert _mfenced_interior_text(fenced) == [("mi", "a")]

    assert msup[1][0].text == "2"


def test_no_regression_explicit_left_right_with_script():
    # \left(...\right)^{n} already produced a correctly-scoped mfenced before
    # this fix; must keep doing so.
    row = _normalized_row(r"\left(x+y\right)^{n}")
    children = list(row)

    assert len(children) == 1
    msup = children[0]
    assert msup.tag == q("msup")

    # latex2mathml wraps \left...\right's mfenced in an extra mrow; find the
    # mfenced beneath it either way.
    base = msup[0]
    fenced = base if base.tag == q("mfenced") else base[0]
    assert fenced.tag == q("mfenced")
    assert fenced.get("open") == "("
    assert fenced.get("close") == ")"


def test_no_regression_plain_function_call():
    row = _normalized_row(r"f(x)")
    children = list(row)

    assert children[0].tag == q("mi")
    assert children[0].text == "f"
    assert children[1].tag == q("mfenced")
    assert children[1].get("open") == "("
    assert children[1].get("close") == ")"
    assert _mfenced_interior_text(children[1]) == [("mi", "x")]
