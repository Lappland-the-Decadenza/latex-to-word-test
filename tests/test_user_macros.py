"""§6.2 user macros (`latexword/compat/macros.py`): declaration vocabulary,
token-level expansion, and the beyond-the-subset rejections.

PLAN.md §6.2: `\newcommand`, `\renewcommand`, `\def`, `\DeclareMathOperator`,
`\ensuremath` expand at parse time with an expansion-depth limit and a cycle
guard; only the argument-substitution subset is supported, and anything
beyond it is reported (whole-expression fallback), never mis-parsed. The
serializer learns none of it: `\R` canonicalizes to its expansion, and the
declaration itself produces no output. The corpus (48 files) declares no
user macro -- this vocabulary is coverage-complete but corpus-empty, which
is exactly why it needs its own pins.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from latexword.math import latex2omml as L  # noqa: E402


def _canon(tex):
    return L.canonicalize(tex)


def _fails_with(tex, fragment):
    with pytest.raises(L.LatexParseError) as exc:
        _canon(tex)
    assert fragment in exc.value.message


# --- expansion ----------------------------------------------------------------


def test_zero_argument_expansion():
    assert _canon(r"\newcommand{\R}{\mathbb{R}}\R") == r"\mathbb{R}"


def test_argument_substitution():
    assert _canon(r"\newcommand{\foo}[1]{x^{#1}}\foo{2}") == r"x^{2}"
    assert _canon(r"\def\p#1#2{#1^{#2}}\p{x}{n}") == r"x^{n}"


def test_declaration_produces_no_output_and_use_after():
    # A declaration is a side effect: nothing before/after it survives as
    # content, and later uses in the same expression expand.
    assert _canon(r"x\newcommand{\z}{1}\z y") == r"x1y"


def test_lazy_body_nested_macros():
    # The body is not tokenized at declaration: a macro defined after its
    # use inside another body still expands.
    assert _canon(r"\newcommand{\a}{1}\newcommand{\b}{\a+2}\b") == r"1+2"


def test_renewcommand():
    assert _canon(r"\newcommand{\f}{a}\renewcommand{\f}{b}\f") == r"b"


def test_declare_math_operator():
    assert _canon(
        r"\DeclareMathOperator{\esssup}{ess\,sup}\esssup(x)"
    ) == r"\operatorname{ess\,sup}\left(x\right)"


def test_ensuremath_is_a_group():
    # \ensuremath{x} is {x} in math mode: one atom for script binding.
    assert _canon(r"a_{\ensuremath{bc}}") == r"a_{bc}"


def test_definition_is_lazy_tex_style():
    # \def's body is kept as text and tokenized at every use -- the same
    # body used twice expands twice.
    assert _canon(r"\newcommand{\f}[1]{#1+#1}\f{a}") == r"a+a"


def test_empty_body():
    assert _canon(r"\newcommand{\n}{}\n x") == r"x"


# --- beyond the supported subset ----------------------------------------------


def test_default_argument_form_rejected():
    _fails_with(r"\newcommand{\f}[2][a]{#1#2}\f{b}", "default-argument")


def test_declare_math_operator_star_rejected():
    _fails_with(r"\DeclareMathOperator*{\f}{F}\f", "beyond the supported subset")


def test_recursive_macro_rejected():
    _fails_with(r"\newcommand{\a}{\a}\a", "recursive macro expansion")


def test_mutual_recursion_rejected():
    _fails_with(r"\newcommand{\a}{\b}\newcommand{\b}{\a}\a",
                "recursive macro expansion")


def test_depth_limit():
    chain = "".join(
        r"\newcommand{\d%s}{\d%s}" % (chr(ord("A") + k), chr(ord("A") + k + 1))
        for k in range(24)
    ) + r"\newcommand{\dY}{z}\dA"
    _fails_with(chain, "depth limit")


def test_undeclared_macro_still_unknown():
    _fails_with(r"\foobar{x}", "unknown macro")


def test_reserved_name_rejected():
    _fails_with(r"\newcommand{\text}{x}", "reserved macro name")


# --- hygiene ------------------------------------------------------------------


def test_env_does_not_leak_between_parses():
    _canon(r"\newcommand{\a}{1}\a")
    _fails_with(r"\a", "unknown macro")


def test_redefinition_warns_but_parses():
    warnings = []
    node = L.parse(r"\newcommand{\f}{a}\newcommand{\f}{b}\f", warnings=warnings)
    assert L.serialize(node) == r"b"
    assert any("redefined" in w for w in warnings)


def test_emitted_omml_is_plain_math():
    # The expansion produces ordinary math -- no trace of the macro
    # machinery survives in the OMML, and no m:r prose fallback appears.
    om = L.emit(L.parse(r"\newcommand{\R}{\mathbb{R}}\R"))
    assert [c.tag.split("}", 1)[-1] for c in om] == ["r"]
