r"""Tolerated macros (PLAN.md §6.2): recognised vocabulary with no OMML
representation, consumed without failing the expression.

`_UNSUPPORTED` in latex2omml rejects loudly -- the whole expression fails
and falls back to monospaced literal LaTeX. That is right for constructs
whose *meaning* would be silently lost (`\substack` has no target
element at all). For document-layer metadata that legitimately cannot
live inside an equation (`\label`'s anchor, `\nonumber`'s numbering) --
and for `\\!`, whose backward width no Unicode codepoint can spell --
a whole-equation fallback is the wrong punishment: the formula itself is
perfectly representable, only the one effect is not. These are consumed
as no-ops -- with a warning naming the reason, so nothing is dropped
silently (PLAN.md §2 rule 6) -- and the coverage tool counts them in the
deferred bucket alongside `_UNSUPPORTED`.

The argument forms (`\label{name}`, `\hspace{1em}`) consume their braced
argument along with the macro; the argument's content is dropped with the
same warning (there is nowhere to store it: OMML carries no anchors, no
numbering state, and no lengths).
"""

# macro -> reason, named in the warning and in the coverage deferred bucket
TOLERATED = {
    "\\label": (
        "document anchor; a Word bookmark is a paragraph-level element and "
        "cannot sit inside an OMML equation, so a label inside math is "
        "dropped (document-layer \\label writes a real bookmark, §7.1)"
    ),
    "\\nonumber": (
        "equation numbering is document-layer state, not math content"
    ),
    "\\hspace": (
        "no length storage in the Rule 0 target inventory; the spacing is "
        "dropped"
    ),
    "\\!": (
        "negative thin space has no Unicode space glyph -- every other "
        "spacing macro maps to a positive-width proportional space "
        "character, but there is no codepoint for 'move backward'; the "
        "backward width is dropped, named here (measured 10 times on the "
        ".tex corpus; a whole-equation fallback was the wrong punishment "
        "for a typographic nicety)"
    ),
}

# Macros that also consume a braced argument after the macro itself.
TOLERATED_WITH_ARG = {"\\label", "\\hspace"}

# Math display-style declarations are redundant once the document layer has
# already identified the math zone.  They are nevertheless emitted by common
# LaTeX writers, so consuming them here keeps a valid expression from falling
# back to visible source text.
STYLE_NOOPS = {"\\displaystyle"}
