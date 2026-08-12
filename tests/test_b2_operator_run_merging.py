"""B2 / D4 -- adjacent operator-name runs must not fuse.

``fix_function_application`` (``mathml_normalize.py``) pairs a function name
with its argument via an invisible U+2061 application character, so the XSL
builds a real ``m:func`` object instead of loose text runs. A single
left-to-right pass over an ``mrow`` only pairs the *rightmost* name with a
real operand: when the scan reaches ``cosh`` in
``\\cosh \\ln \\tan \\frac{\\varphi}{2}``, its next sibling is ``ln`` --
itself a function name, so ``_is_valid_operand`` rejects it as an operand,
and ``cosh`` is left bare. Same for ``ln`` -> ``tan``. Left bare, ``cosh``
and ``ln`` reach the XSL as two identically-styled ``mi`` siblings, which it
fuses into a single ``m:t`` text run ("coshln") instead of two distinct,
selectable objects.

The fix repeats the pairing pass over each ``mrow`` until it stops changing:
each pass turns a name+operand pair into an ``mrow`` wrapper that is itself
a valid operand (but not itself a function name) for whatever name precedes
it, so the fix-point after N passes is N correctly nested ``m:func``
objects.

These tests run the legacy forward pipeline
(``latex2word.legacy_latex_math_to_omml``, which chains ``latex2mathml`` ->
``mathml_normalize.normalize`` -> the XSL) and assert on the sequence of
``m:t`` text runs in the produced OMML -- that is what actually shows
whether names got fused, unlike comparing the round-tripped LaTeX string
alone (which can look identical whether or not the underlying objects are
nested/fused, e.g. for single-mi arguments).

R4 (``REWRITE_FORWARD.md``) moved ``latex_math_to_omml`` itself onto the new
``latex2omml`` emitter, which never merges runs at all (Rule 3 holds by
construction: every token is its own ``m:r``), so this specific defect and
fix no longer apply to the live seam. The regression coverage stays useful
against the legacy chain, which is kept, import-only, for foreign ``.tex``.
The full-corpus test at the bottom exercises the real, current forward path
via ``convert_latex_to_docx`` and is unaffected by this distinction.
"""

import os
import zipfile

from lxml import etree

from latexword.docx.write import convert_latex_to_docx, legacy_latex_math_to_omml as latex_math_to_omml
import pytest

import fidelity
from latexword.mathsyms import KNOWN_FUNC_MACROS
from latexword.docx.read import docx_to_latex

M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mt_texts(omml):
    return [el.text for el in omml.iter(M + "t")]


def test_three_adjacent_operator_names_do_not_fuse():
    omml = latex_math_to_omml(r"\cosh \ln \tan \frac{\varphi}{2}", "inline")
    assert _mt_texts(omml) == ["cosh", "ln", "tan", "φ", "2"]


def test_two_adjacent_operator_names_do_not_fuse():
    omml = latex_math_to_omml(r"\log \log n", "inline")
    assert _mt_texts(omml) == ["log", "log", "n"]


def test_single_operator_name_with_separate_argument_run():
    # This is B7's forward-side precondition: \tanh f must already produce a
    # real m:func(tanh, f), not a fused "tanhf" -- B7 itself is a reverse-path
    # defect (word2latex dropping the space when re-emitting a standalone
    # name), out of scope here, but the forward object must be right first.
    omml = latex_math_to_omml(r"\tanh f", "inline")
    assert _mt_texts(omml) == ["tanh", "f"]


def test_non_name_single_char_argument_does_not_trigger_nesting():
    # theta is a single codepoint, not a multi-character name -- sin/cos
    # must each pair with their own theta and never merge into one run.
    omml = latex_math_to_omml(r"\sin \theta \cos \theta", "inline")
    assert _mt_texts(omml) == ["sin", "θ", "cos", "θ"]


def test_operator_names_separated_by_a_relation_stay_separate():
    omml = latex_math_to_omml(r"\sin x + \cos y", "inline")
    assert _mt_texts(omml) == ["sin", "x", "+", "cos", "y"]


def test_lim_with_limit_and_trailing_operator_name():
    omml = latex_math_to_omml(r"\lim_{n \to \infty} \sin \frac{1}{n}", "inline")
    assert _mt_texts(omml) == ["lim", "n", "→∞", "sin", "1", "n"]


@pytest.mark.parametrize(
    "index", range(len(fidelity.collect_documents())))
def test_corpus_survives_full_round_trip_without_fusing_operator_names(
        index, tmp_path):
    """Real-document evidence, stronger than the synthetic cases above.

    A hand-authored Word document containing ``= \ln \cosh f`` used to come
    back wrong: ``\ln``'s next sibling was ``\cosh`` -- itself a function
    name and therefore an invalid operand -- so ``\ln`` stayed a bare ``mi``.
    Because ``fix_operator_style`` makes every bare ``mo`` upright too, the
    preceding ``=`` ended up carrying identical styling and the XSL fused the
    two into one run: measured ``'=ln'`` and ``'coshln'`` instead of clean
    ``'ln'`` runs -- silently losing the equals sign on round-trip.

    Stated as a property over the whole corpus rather than pinned to one file
    and one expected run count: the count was a fact about a document, and a
    document is exactly the thing that may be renamed, edited or replaced.
    """
    src = fidelity.collect_documents()[index]
    text, _ = docx_to_latex(src, str(tmp_path / "g1.tex"))
    r1_path = tmp_path / "g1.tex"
    r1_path.write_text(text, encoding="utf-8")

    d1_path = tmp_path / "g1.docx"
    convert_latex_to_docx(str(r1_path), str(d1_path))

    with zipfile.ZipFile(d1_path) as z:
        xml = z.read("word/document.xml")
    root = etree.fromstring(xml)

    # A run whose text contains a known operator name must be *exactly* that
    # name -- never that name glued to a neighbouring token (an operator or
    # relation like '=', or another operator name like 'cosh').
    #
    # One legitimate exception has to be carved out: "arc" + a known
    # hyperbolic/trig name (arcsinh, arccosh, arctanh -- arcsin/arccos/arctan
    # themselves are already whole entries in known_names) is the standard
    # \operatorname spelling for an inverse function and is a single,
    # correctly-formed identifier, not a fusion artifact, even though it
    # contains "cosh"/"sinh"/"tanh" as a literal substring. Detected
    # structurally ("arc" as a prefix with a known name as the exact
    # remainder), not via a fixed word list, so it covers whichever member of
    # the family the corpus happens to use.
    known_names = {name for name in KNOWN_FUNC_MACROS if name.isalpha()}

    def _is_arc_form(text):
        return text.startswith("arc") and text[3:] in known_names

    violations = [
        t.text
        for t in root.iter(M + "t")
        if t.text
        and t.text not in known_names
        and not _is_arc_form(t.text)
        and any(name in t.text for name in known_names)
    ]
    assert not violations, f"fused operator-name run(s): {violations}"
