"""B7 -- a standalone operator-name run must not glue onto the next run.

Root cause is on the reverse path only: when an operator name arrives *not*
wrapped in ``m:func`` -- which is what natively hand-authored Word equations
look like (no ``fix_function_application`` ever touched them; e.g. a
hand-authored corpus document) -- ``_convert_run`` (``word2latex.py``) took the
``sty="p"`` branch and returned a bare macro from ``_upright_name_to_latex``
with no trailing space. ``to_latex`` joins sibling ``m:r`` runs with no
separator, so the following run concatenated directly onto it:
``\\tanh`` + ``f`` -> ``\\tanhf``, an undefined control sequence and a hard
``xelatex`` compile failure. This is a direct violation of
``CANONICAL.md`` Rule 2 ("operator names carry an explicit trailing space,
never braces ... the space is mandatory").

The forward path was never the problem: ``\\tanh f`` already produces a
correct ``m:func(fName=tanh, e=f)``, and ``_convert_func`` already inserts
the separating space itself when reconstructing from that object.
"""

from lxml import etree

from latexword.math.omml2latex import to_latex

M_MATH_URI = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def _standalone_name_omath(name, next_text):
    """Build a minimal oMath with two independent top-level runs: a bare
    ``sty="p"`` operator-name run followed by a separate run -- exactly the
    shape a hand-authored Word equation produces when it has never gone
    through ``fix_function_application`` (no ``m:func`` object at all).
    """
    xml = f"""
    <m:oMath xmlns:m="{M_MATH_URI}" xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
        <m:r>
            <m:rPr><m:sty m:val="p"/></m:rPr>
            <m:t>{name}</m:t>
        </m:r>
        <m:r>
            <m:t>{next_text}</m:t>
        </m:r>
    </m:oMath>
    """
    return etree.fromstring(xml.encode("utf-8"))


def test_standalone_operator_name_gets_a_separating_space():
    omath = _standalone_name_omath("tanh", "f")
    result = to_latex(omath)
    assert result == "\\tanh f", result
    assert "\\tanhf" not in result


def test_standalone_operator_name_before_punctuation_still_compiles():
    # Rule 7.1's join-safety space is needed only before a letter/digit
    # (the case the first test asserts); before punctuation the single
    # speller emits no space, and "\sin+" is syntactically sane -- a macro
    # followed by an operator glyph, not glued onto a letter.
    omath = _standalone_name_omath("sin", "+")
    result = to_latex(omath)
    assert result == "\\sin+", result


def test_unrecognised_standalone_name_becomes_mathrm():
    # An unrecognised multi-letter *standalone* (not m:func-wrapped) name
    # cannot be told apart from \mathrm{...} at the OMML level -- both are
    # the same bare m:r/sty="p" shape -- so CANONICAL.md's \mathrm note
    # (item 3) picks \mathrm{...} as the one canonical reverse spelling
    # here, not \operatorname{...} (which stays reachable, but only via the
    # m:func-wrapped path -- see test_r6_mathrm_d_survives_roundtrip and
    # CANONICAL.md's Rule 2 note). \mathrm{...} already ends in a closing
    # brace and needs no separating space to compile.
    omath = _standalone_name_omath("foo", "x")
    result = to_latex(omath)
    assert result == "\\mathrm{foo}x", result
