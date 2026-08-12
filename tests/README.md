# Test harness (Phase 0, workstream A)

Run from the project root:

```powershell
.venv\Scripts\python.exe -m pytest tests/ -v
```

Round-trip generations are slow (real documents, hundreds of equations), so
`conftest.py` computes the whole chain for every corpus document exactly
once per session (`roundtrip_chains` fixture) and every test reads from that
cache instead of re-converting.

Corpus (`conftest.CORPUS`): project fixtures discovered by scanning,
`tests/corpus/skill_conformant.tex` (LaTeX written per `SKILL.md`'s rules,
included specifically because it is known to degrade), plus three real
hand-authored, private Word documents (gitignored, under `tests/corpus_docx/`).

- **`test_a1_convergence.py`** -- asserts every document reaches a
  byte-identical fixed point in the round-trip chain by generation 3 and
  stays there through generation 5. Currently passes for the whole corpus.
- **`test_a2_silent_corruption.py`** -- compares generation 1 and generation
  2 LaTeX (whitespace normalised away) and fails if a semantic difference
  isn't covered by an emitted warning. `xfail(strict=True)`: today's
  converters corrupt content silently (D10, D4, B3).
- **`test_a3_symbol_bijectivity.py`** -- checks that every LaTeX macro
  `word2latex.SYMBOL_MAP` claims to reconstruct actually round-trips through
  `latex2mathml`'s own forward symbol table. `xfail(strict=True)`: several
  macros are not bijective (B3), printed in full on run.
- **`test_a5_compile.py`** -- compiles each document's final converged
  LaTeX with real `xelatex`; asserts exit code 0 and zero "Missing
  character" lines in the log, as two separate `xfail(strict=True)` tests
  (B7, B8). Skipped cleanly if `xelatex` is not on `PATH`.

When workstream B fixes a defect, its test flips from `xfail` to passing;
`strict=True` turns that XPASS into a hard failure, which is the signal to
remove the now-stale `xfail` marker.
