"""Defect 1 -- prose typography must never touch math.

``DocxBuilder.add_paragraph`` / ``add_heading`` used to run
``_apply_text_replacements`` (the ``''`` -> right-quote, ``--`` -> en-dash,
``\\ldots`` -> ellipsis table) over the *whole* paragraph string, including
any ``$...$`` / ``\\(...\\)`` math it contained, before ``add_inline_latex``
ever split math out from prose. Applied to math, those replacements corrupt
it: a triple prime ``y'''`` reads as two apostrophes eaten by the
closing-quote rule plus one left over, and ``--`` inside math (e.g. a
subtraction after a unary minus) becomes an en dash.

The fix moves the replacement into ``add_inline_latex`` itself, applied only
to the spans outside ``$...$``/``\\(...\\)``, and removes the two premature
calls. These tests are the regression guard for that: prose keeps its
replacements, math is untouched, in the same paragraph.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from latexword.docx import write as latex2word

M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


def _run_texts(paragraph):
    return [r.text for r in paragraph.runs]


def _math_text(paragraph):
    return "".join(t.text or "" for t in paragraph._element.iter(M + "t"))


def test_add_paragraph_text_prose_replaced_math_untouched():
    b = latex2word.DocxBuilder()
    b.add_paragraph_text(
        r"He said --- ``hi'' about $y''' = 2\kappa y'' - \Omega^2 y'$ today."
    )
    p = b.doc.paragraphs[-1]

    # Prose: \ -- \ -> em dash, `` -> left quote, '' -> right quote, exactly
    # as before this fix.
    prose = "".join(_run_texts(p))
    assert "—" in prose  # em dash from "---"
    assert "“" in prose and "”" in prose  # `` and '' quotes
    assert "--" not in prose
    assert "''" not in prose

    # Math: the primes in y''' / y'' / y' must survive as primes (U+2032),
    # not be swallowed by the prose closing-quote rule. No right double
    # quote (U+201D) or en dash leaked into the math run text.
    math = _math_text(p)
    assert "”" not in math
    assert "—" not in math  # em dash
    assert math.count("′") == 6  # 3 + 2 + 1 primes across y''', y'', y'


def test_add_heading_prose_replaced_math_untouched():
    b = latex2word.DocxBuilder()
    b.add_heading(r"Title --- ``x'' with $a'' - b$", 1)
    h = b.doc.paragraphs[-1]

    prose = "".join(_run_texts(h))
    assert "—" in prose
    assert "“" in prose and "”" in prose

    math = _math_text(h)
    assert "”" not in math
    assert "—" not in math
    assert math.count("′") == 2  # a''


def test_add_paragraph_text_plain_prose_unchanged():
    # No math at all: behaviour must be byte-identical to before the fix.
    b = latex2word.DocxBuilder()
    b.add_paragraph_text("Alice said ``no''---not again.")
    p = b.doc.paragraphs[-1]
    text = "".join(_run_texts(p))
    assert text == "Alice said “no”—not again."


# --- Defect 2 -- U+2219 BULLET OPERATOR round trip ---------------------------
#
# A hand-authored Word equation's U+2219 "∙" used to reverse-convert to
# \bullet (mathsyms.SYMBOL_MAP), then forward-convert back to U+2022 "•" -- a
# bullet-*list* glyph, visibly wrong in a formula -- because \bullet's own
# canonical forward codepoint was U+2022. Fixed by repointing \bullet's
# canonical entry to U+2219 (see mathsyms.SYMBOL_MAP's comment for why: 0
# real corpus documents use U+2022 in math, so nothing legitimate breaks).


def test_bullet_operator_round_trips_through_reverse_then_forward():
    from latexword.mathsyms import SYMBOL_MAP

    macro = SYMBOL_MAP["∙"]
    assert macro.startswith("\\")

    omml = latex2word.latex_math_to_omml(f"a {macro} b", "inline")
    text = "".join(t.text or "" for t in omml.iter(M + "t"))

    assert "∙" in text
    assert "•" not in text
