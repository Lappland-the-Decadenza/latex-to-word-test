"""Forward-only accent marks (PLAN.md §5.3).

The bidirectional accent vocabulary (macro <-> combining character) lives in
the registry; these are the one-directional *input* marks -- a source "¯"
that must become the combining form (`ACCENT_CHARS`) -- and the bars, which
are structurally different (`m:bar`) from diacritics (`m:acc`). Re-exported
by `latexword/mathsyms.py`; import from there, never from here.
"""

# The XSL only emits m:acc when @accent="true" is present, and Word expects
# the *combining* form of the mark. latex2mathml supplies neither for most
# accent commands, so \vec and \ddot degrade into m:limUpp (a limit above the
# base), which Word lays out with limit spacing instead of as a diacritic.
ACCENT_CHARS = {
    "→": "⃗",  # \vec        rightwards arrow -> combining
    "¨": "̈",  # \ddot       diaeresis
    "^": "̂",  # \hat        circumflex
    "ˆ": "̂",  # \hat        modifier circumflex
    "˙": "̇",  # \dot        dot above
    "·": "̇",  # \dot        middle dot
    "¯": "̄",  # \bar        macron
    "ˉ": "̄",  # \bar        modifier macron
    "~": "̃",  # \tilde      tilde
    "˜": "̃",  # \tilde      small tilde
    "ˇ": "̌",  # \check      caron
    "´": "́",  # \acute
    "`": "̀",  # \grave
    "˘": "̆",  # \breve
    "⃛": "⃛",  # \dddot
    "⃜": "⃜",  # \ddddot
}

# Overline/underline are bars, not diacritics: a combining mark sits over a
# single character, whereas \overline{AB} must span the whole base. These are
# routed to m:bar in the OMML pass, so they are recognised but not rewritten
# into combining form here.
BAR_CHARS = {"―", "_", "‾", "–", "—"}
