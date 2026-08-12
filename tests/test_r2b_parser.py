"""R2b: the LaTeX-math parser and the canonical serializer.

Three properties, in order of how much they would cost us if they broke:

1. **The corpus parses.** Every math expression the project has must reach an
   AST, except for a short allowlist of expressions that are genuinely outside
   the canon. The allowlist is two-sided (see `test_known_failures_still_fail`)
   so that fixing one of them is a loud event rather than a silent shrink.

2. **`serialize(parse(x))` is idempotent.** This is what makes `serialize` a
   canonicalizer rather than merely a printer, and it is also the standing
   evidence that the parser's fixed rules -- notably Rule 2 function adjacency,
   "exactly one scripted atom" -- do not guess. A rule that guessed would
   re-parse its own output differently and show up here.

3. **Grouping survives.** `{a+b}^2` and `a+b^2` must not collapse together.
   Losing grouping is the D10 defect class that motivated the rewrite.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mathcorpus
from latexword.math import latex2omml as L


# Expressions that do not parse, each with the reason it is not a parser bug.
# Keyed by a distinctive substring rather than the full text, because the
# `_r1` sources are regenerated from the `.docx` on every run.
#
# Currently empty, and that is the point: the last entry (a literal `~` inside
# math, emitted by the reverse converter against Rule 7.6) was removed when
# `test_known_failures_still_fail` reported it had started parsing. An
# allowlist that is never emptied is an allowlist nobody reads.
KNOWN_UNPARSEABLE = {}


def _reason_for(tex):
    for needle, reason in KNOWN_UNPARSEABLE.items():
        if needle in tex:
            return reason
    return None


@pytest.fixture(scope="module")
def corpus():
    return mathcorpus.collect()


@pytest.fixture(scope="module")
def parsed(corpus):
    """(expr, ast) for everything that parses, plus (expr, exc) for what does
    not -- computed once, since reverse-converting the three `.docx` is slow."""
    ok, bad = [], []
    for e in corpus:
        try:
            ok.append((e, L.parse(e.tex)))
        except Exception as exc:  # noqa: BLE001 - classifying, then re-raising in the test
            bad.append((e, exc))
    return ok, bad


def test_corpus_is_not_empty(corpus):
    # A silently empty corpus would make every other test in this file pass
    # vacuously, which is the one failure mode a parse-rate test cannot see.
    assert len(corpus) > 500, f"corpus collapsed to {len(corpus)} expressions"


def test_corpus_parses(parsed):
    _ok, bad = parsed
    unexplained = [(e, exc) for e, exc in bad if _reason_for(e.tex) is None]
    assert not unexplained, "\n".join(
        f"[{e.source}#{e.index}] {e.tex[:120]!r}\n    {type(exc).__name__}: {exc}"
        for e, exc in unexplained
    )


def test_known_failures_still_fail(parsed):
    """The allowlist is two-sided: an entry that starts parsing must be
    removed deliberately, the same discipline as `xfail(strict=True)`
    elsewhere in this suite. Otherwise a canon decision could land and leave
    a stale exemption behind that hides the next regression."""
    ok, _bad = parsed
    leaked = [
        (e, _reason_for(e.tex)) for e, _ast in ok if _reason_for(e.tex) is not None
    ]
    assert not leaked, "\n".join(
        f"[{e.source}#{e.index}] {e.tex[:120]!r} now parses -- remove its "
        f"KNOWN_UNPARSEABLE entry.\n    was: {reason}"
        for e, reason in leaked
    )


def test_failures_are_typed_and_located(parsed):
    """Clause 3 of the Phase 0 goal: reject loudly, never mutate silently. A
    bare `Exception` would mean something escaped the diagnostic path."""
    _ok, bad = parsed
    for e, exc in bad:
        assert isinstance(exc, L.LatexParseError), (
            f"[{e.source}#{e.index}] raised {type(exc).__name__}, "
            f"not a LatexParseError: {exc}"
        )
        assert str(exc).strip(), f"[{e.source}#{e.index}] raised an empty diagnostic"


def test_serialize_is_idempotent(parsed):
    ok, _bad = parsed
    violations = []
    for e, ast in ok:
        once = L.serialize(ast)
        twice = L.serialize(L.parse(once))
        if once != twice:
            violations.append((e, once, twice))
    assert not violations, "\n".join(
        f"[{e.source}#{e.index}] {e.tex[:90]!r}\n    1st: {a[:110]!r}\n    2nd: {b[:110]!r}"
        for e, a, b in violations
    )


def test_grouping_survives():
    # The D10 class: if grouping is flattened at parse time it can never be
    # recovered downstream, so this is checked on the AST, not on the output.
    assert L.parse(r"{a+b}^2") != L.parse(r"a+b^2")


@pytest.mark.parametrize(
    "spaced,braced",
    [
        (r"\sin x", r"\sin{x}"),
        (r"\ln \cos x", r"\ln{\cos{x}}"),
        (r"\sin x + y", r"\sin{x} + y"),
    ],
)
def test_brace_spelling_is_accepted(spaced, braced):
    """Both spellings of Rule 2 must canonicalize to the same text.

    This is not decoration: `REWRITE_FORWARD.md` records the brace-delimited
    canon as a live fallback, and its cheapness depends entirely on the parser
    already accepting braces. If this breaks, the fallback silently becomes a
    parser rewrite instead of a `serialize()` template change.
    """
    assert L.serialize(L.parse(spaced)) == L.serialize(L.parse(braced))
