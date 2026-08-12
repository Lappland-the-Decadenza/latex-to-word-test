"""B9 -- the forward converter must never raise on bad math.

CLAUDE.md documents the intended contract: "The converter never raises on
bad math: a failed expression is emitted as monospaced literal LaTeX and
reported in the warning summary printed at the end of a run." That was
aspirational, not true under the old ``latex2mathml`` chain: 3.81.0 emits
invalid XML (a raw, unescaped ``&`` inside an ``<mi>``) for
``\\begin{aligned}`` and ``\\begin{gathered}`` when they contain a column
separator -- an upstream bug -- and the resulting ``XMLSyntaxError`` from
``etree.fromstring`` used to escape ``latex_math_to_omml`` uncaught, killing
conversion of the whole document over one bad formula.

R4 (``REWRITE_FORWARD.md``) switched ``latex_math_to_omml`` to
``latex2omml``, whose parser reads ``aligned``/``gathered`` cleanly (Rule 5
aliases both to ``align*`` in the construct table) -- that specific upstream
crash is gone, a genuine improvement, not something to special-case back in.
So this test now exercises three constructs that are still genuinely
malformed for the *new* parser: a ``\\begin``/``\\end`` environment-name
mismatch that does not collapse to the same canonical environment
(``cases`` vs. ``pmatrix``), an unknown macro, and a brace-unbalanced
``\\frac``. The property under test -- the whole document still converts,
with no exception, and every failed construct reported as its own warning
-- is unchanged.
"""

import os

from latexword.docx.write import convert_latex_to_docx

DOC = r"""
\documentclass{article}
\usepackage{amsmath}
\begin{document}

\[
\begin{cases}
a & b \\
c & d
\end{pmatrix}
\]

Unknown macro: $\unknownmacroxyz$

Malformed inline math: $\frac{1}{$

\end{document}
"""


def test_document_with_multiple_bad_math_converts_without_raising(tmp_path):
    tex_path = tmp_path / "b9_bad_math.tex"
    tex_path.write_text(DOC, encoding="utf-8")
    docx_path = tmp_path / "b9_bad_math.docx"

    # Must not raise -- this is the whole point of B9. Letting an exception
    # propagate out of this call is itself a test failure.
    out_path, warnings = convert_latex_to_docx(str(tex_path), str(docx_path))

    assert os.path.exists(out_path)
    assert os.path.getsize(out_path) > 0

    # One warning per failed construct: the mismatched cases/pmatrix
    # environment, the unknown macro, and the malformed inline \frac.
    failure_warnings = [w for w in warnings if "math failed" in w]
    assert len(failure_warnings) == 3, (
        f"expected 3 math-failure warnings, got {len(failure_warnings)}: "
        f"{failure_warnings}"
    )

    joined = "\n".join(failure_warnings)
    assert "pmatrix" in joined
    assert "unknownmacroxyz" in joined
    assert r"\frac" in joined
