"""Operator-name vocabulary and n-ary body boundaries (PLAN.md §5.3).

One-directional character-level sets: which multi-letter names are
operators (`LIMIT_OPS`), which of those are big operators semantically
(`BIG_OP_NAMES`), which names are standard LaTeX macros (`KNOWN_FUNC_MACROS`),
and which characters end an n-ary operator's body in the forward parser
(`NARY_BODY_*`). Re-exported by `latexword/mathsyms.py`; import from there,
never from here.
"""

# Multi-letter operators with "movable limits": in display style their
# scripts render underneath the name (\lim_{n\to\infty}), not as an ordinary
# subscript to the right.
LIMIT_OPS = {
    "lim", "max", "min", "sup", "inf", "limsup", "liminf",
    "argmax", "argmin", "gcd", "lcm", "colim", "injlim", "projlim",
}

# Defect 2/3 Task B (CANONICAL.md rule 16): the subset of LIMIT_OPS that are
# big operators *semantically*, even though OMML/mathast represent them as
# `m:func` -- `\lim_{n\to\infty} a_n b_n` conventionally takes both factors
# as its operand, the same convention `\sum`/`\prod` already get (the
# run-to-boundary rule), not the plain single-atom Rule 2 adjacency rule
# every other function keeps (`\sin x \cos y` must stay `sin(x)*cos(y)`, so
# ordinary functions are deliberately excluded from this set).
BIG_OP_NAMES = {"lim", "limsup", "liminf", "max", "min", "sup", "inf"}

# Function names that are standard LaTeX macros in their own right, rather
# than needing \operatorname{...}.
KNOWN_FUNC_MACROS = {
    name: "\\" + name
    for name in (
        "sin", "cos", "tan", "cot", "sec", "csc",
        "sinh", "cosh", "tanh", "coth",
        "arcsin", "arccos", "arctan",
        "arg", "deg", "det", "dim", "exp", "gcd", "hom", "ker",
        "lg", "ln", "log", "Pr",
        # §6.2, measured on the .tex corpus (48 AI-written files): the
        # inverse-hyperbolic and signum spellings the corpus actually uses.
        "arsinh", "arcosh", "artanh", "sech", "sgn",
    )
}
for _name in LIMIT_OPS:
    KNOWN_FUNC_MACROS.setdefault(_name, "\\" + _name)


# Defect 2/3: an n-ary operator's *body* (its operand, when not written as an
# explicit `{...}` group) is a maximal run of scripted atoms, stopping before
# a top-level relation or binary +/- -- the classical typographic reading
# (`\int f dx = g` is `(\int f dx) = g`, `\int f dx + C` is `(\int f dx) +
# C`), not "the rest of the enclosing row" (which used to swallow an `=` and
# everything after it, corrupting the parse -- see latex2omml._Parser
# .parse_nary_body). Kept a `set` per the membership-test gotcha the rest of
# this module's documentation already records ("" in "abc" is True).
NARY_BODY_RELATION_CHARS = set("=<>≤≥≠≈≡∼→⇒∈⊂")
# `+`/`-` are handled separately from the relation set above: they are a
# *binary* boundary (Rule: a top-level `+`/`-` ends the body), not a
# relation, and this project's SYMBOL_MAP maps unary minus to the same glyph
# ("-") as the ASCII binary one, so this set intentionally holds exactly the
# two ASCII characters, not a derived Unicode form.
NARY_BODY_BINARY_CHARS = set("+-")
