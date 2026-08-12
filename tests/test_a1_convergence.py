"""A1 -- convergence property test.

For every corpus document, the round-trip chain must reach a byte-identical
fixed point by generation 3 and stay there: gen N == gen N+1 for every
N >= 3 up to MAX_GENERATION.

History: extending the corpus (A4) with .tex sources carrying
\\title/\\author (as SKILL.md recommends) initially surfaced a real
instability -- B5's title/author duplication bug re-inserted the rendered
title+author block into the body on every generation, so length grew
without bound instead of converging. That defect is fixed (see
word2latex.py's preamble ordering and latex2word.py's brace-aware
\\title/\\author/\\date stripping); the property now holds for the whole
corpus and the test is a single check again.
"""

from conftest import MAX_GENERATION


def test_reaches_fixed_point_by_generation_3(corpus, roundtrip_chains):
    failures = []
    for doc in corpus:
        name = doc["name"]
        generations, _ = roundtrip_chains[name]
        for n in range(3, MAX_GENERATION):
            if generations[n] != generations[n + 1]:
                failures.append(
                    f"{name}: generation {n} != generation {n + 1} "
                    f"(len {len(generations[n])} vs {len(generations[n + 1])})"
                )
    assert not failures, "not converged:\n" + "\n".join(failures)


def test_generation_1_through_5_are_produced(corpus, roundtrip_chains):
    # Sanity: the chain builder must actually produce every generation
    # (a truncated chain would make the convergence check above vacuous).
    for doc in corpus:
        generations, _ = roundtrip_chains[doc["name"]]
        assert set(generations.keys()) == set(range(1, MAX_GENERATION + 1))
        for n, text in generations.items():
            assert isinstance(text, str) and text.strip(), (
                f"{doc['name']} generation {n} is empty"
            )
