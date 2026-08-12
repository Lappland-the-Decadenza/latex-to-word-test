"""A2 -- silent-corruption test: does repeated conversion keep changing the
document?

The dangerous failure mode is not "the first pass changes something" -- the
first pass is *supposed* to change things, because it rewrites a hand-authored
document into the canonical subset (`CANONICAL.md`): bare `(`/`)` become a
real `m:d` and reverse as `\\left(`/`\\right)`, a `matrix` wrapped in
delimiters becomes `pmatrix`, a literal tilde gains its sanctioned spelling.
The dangerous failure mode is a converter that changes something on *every*
pass, because that damage is invisible in any single run and compounds.

So this test asserts the fixed point, not equality with generation 1:

    generation 2 == generation 3 == generation 4 == generation 5

Generation 1 is read from the *original* document; generation 2 onward are
read from documents we produced. Comparing 1 against 2 measures
canonicalisation, which is intended behaviour, and that is exactly what this
test used to do -- it was marked `xfail(strict=True)` and blamed defects
(D10, D4, symbol-table asymmetry) that have since been fixed, while the real
reason it failed was the wrong comparison. The gen1->gen2 delta is still
reported below, because a sudden jump there is worth seeing; it just is not
asserted on.

Whether canonicalisation *damaged* anything is a separate question, and it is
not answered by comparing our output against our output. It is answered by
`tests/fidelity.py`, which uses the original `.docx` as the baseline and
classifies every math zone. Both checks are needed; neither substitutes for
the other.

Whitespace is normalised away first (`re.sub(r"\\s+", "", s)` per line, matching
the methodology of legacy/docs/roundtrip-measurement.md) since it is cosmetic
and must never count as corruption.
"""

import re
import difflib


# The first generation that is read from a document we produced ourselves,
# i.e. the first one that should already be canonical.
FIRST_SETTLED_GENERATION = 2


def _semantic_diff_lines(text1, text2):
    """(count, sample) of lines that differ ignoring whitespace."""
    lines1 = text1.splitlines()
    lines2 = text2.splitlines()
    norm1 = [re.sub(r"\s+", "", line) for line in lines1]
    norm2 = [re.sub(r"\s+", "", line) for line in lines2]
    sm = difflib.SequenceMatcher(None, norm1, norm2, autojunk=False)
    changed = 0
    sample = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        changed += max(i2 - i1, j2 - j1)
        if len(sample) < 3:
            before = lines1[i1][:120] if i1 < len(lines1) else ""
            after = lines2[j1][:120] if j1 < len(lines2) else ""
            sample.append(f"      -{before!r}\n      +{after!r}")
    return changed, sample


def test_conversion_reaches_a_fixed_point(corpus, roundtrip_chains):
    """From generation 2 on, nothing may move. A converter that keeps
    rewriting its own output corrupts a document a little on every pass."""
    failures = []
    report = []
    for doc in corpus:
        name = doc["name"]
        generations, _warnings = roundtrip_chains[name]
        settled = sorted(g for g in generations if g >= FIRST_SETTLED_GENERATION)
        assert len(settled) >= 2, (
            f"{name}: need at least two settled generations to check a fixed "
            f"point, got {settled} -- raise MAX_GENERATION in conftest.py"
        )

        base = settled[0]
        canonicalised, _ = _semantic_diff_lines(
            generations[1], generations[base])
        report.append(f"{name}: canonicalised at gen1->gen{base}: "
                      f"{canonicalised} line(s)")

        for g in settled[1:]:
            changed, sample = _semantic_diff_lines(
                generations[base], generations[g])
            report.append(f"{name}: gen{base} vs gen{g}: {changed} line(s)")
            if changed:
                failures.append(
                    f"{name}: generation {g} still differs from generation "
                    f"{base} in {changed} line(s) -- conversion has not "
                    f"settled:\n" + "\n".join(sample))

    print("\n".join(report))
    assert not failures, (
        "conversion never reaches a fixed point:\n" + "\n\n".join(failures))
