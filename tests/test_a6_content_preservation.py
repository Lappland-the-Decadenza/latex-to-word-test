r"""A6 (PLAN.md §6.3) -- content preservation for the forward direction.

A2 proves the fixed point (generations 2..5 are textually identical).
§6.3 asks the *meaning* question: gen 1 -> gen 2 may change spelling
(that is canonicalisation), but not meaning. Compare the ASTs, not the
strings -- any difference in the AST is a real loss; a difference in
text alone is canonicalisation. Report per file, and list every file
failing either property (the convergence property is A1/A2's job; this
file is the content half).

The `.docx` corpus already has its AST-level check against the
*original* document (tests/fidelity.py classifies every math zone); this
is the `.tex` corpus's own criterion. Both generations being compared are
our own output, so the zone structure must be stable: zones are paired
by document order, and a count mismatch is itself a failure (an equation
vanished, split, or merged).

Zone shapes the reverse pass emits (docx/read.py): inline `$...$`,
display `\[\n...\n\]` -- nothing else. `\$` (prose-escaped dollar) is
not a zone opener, and backslash escapes are skipped when scanning for a
closer, the same way the forward pass's block scanner reads them.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from latexword.math import latex2omml as L  # noqa: E402


def _tex_math_zones(text):
    """Math zones of a document the *reverse pass* produced, in document
    order, as raw contents. Raises on an unbalanced zone -- that is a
    real defect of the converter, not a measurement problem."""
    zones = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\" and text[i + 1:i + 2] == "[":
            # display zone `\[ ... \]` -- backslash first, and it must be
            # checked before the generic escape skip below, which would
            # swallow the opener.
            j = i + 2
            while j < n:
                if text[j] == "\\":
                    if text[j + 1:j + 2] == "]":
                        break
                    j += 2
                    continue
                j += 1
            if j >= n:
                raise AssertionError(f"unclosed \\[ zone at {i}: {text[i:i + 60]!r}")
            zones.append(text[i + 2:j])
            i = j + 2
            continue
        if c == "\\":
            i += 2
            continue
        if c == "$":
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "$":
                    break
                j += 1
            if j >= n:
                raise AssertionError(f"unclosed $ zone at {i}: {text[i:i + 60]!r}")
            zones.append(text[i + 1:j])
            i = j + 1
            continue
        i += 1
    return zones


def _zone_ast(zone):
    """AST of a zone, or the raw text when it does not parse: a failed
    expression is emitted as monospaced literal LaTeX by both passes, so
    text equality is the right comparison there (and a failure on one
    generation only is still caught)."""
    try:
        return L.parse(zone)
    except L.LatexParseError:
        return zone


def test_content_preserved_across_canonicalisation(corpus, roundtrip_chains):
    failures = []
    for doc in corpus:
        if doc["kind"] != "tex":
            # .docx items: fidelity.py owns the AST-level comparison
            # against the *original* document.
            continue
        name = doc["name"]
        generations = roundtrip_chains[name][0]
        zones1 = _tex_math_zones(generations[1])
        zones2 = _tex_math_zones(generations[2])
        if len(zones1) != len(zones2):
            failures.append(
                f"{name}: {len(zones1)} math zones at gen1 vs {len(zones2)} "
                f"at gen2 -- an equation vanished, split, or merged")
            continue
        for k, (z1, z2) in enumerate(zip(zones1, zones2)):
            if _zone_ast(z1) != _zone_ast(z2):
                failures.append(
                    f"{name}: zone {k} changed AST (spelling may change, "
                    f"meaning may not):\n"
                    f"    gen1 {z1[:100]!r}\n"
                    f"    gen2 {z2[:100]!r}")
    assert not failures, (
        "content loss between gen1 and gen2 (PLAN.md §6.3):\n"
        + "\n".join(failures))
