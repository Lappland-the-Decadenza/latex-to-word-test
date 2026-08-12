"""Shared fixtures for the round-trip test harness.

Conversions are slow (real documents run to hundreds of equations), so the
whole generation chain for every corpus document is computed exactly once per
pytest session and cached. Individual tests only slice into the cached
results.

Generation numbering matches ``legacy/docs/roundtrip-measurement.md``:

- A ``.tex`` source is first converted forward to a ``.docx`` (gen 0 -> d1),
  then reverse-converted back to ``.tex`` (d1 -> r1 == "generation 1").
- A hand-authored ``.docx`` source has no forward step for generation 1: it is
  reverse-converted directly (source docx -> r1 == "generation 1").
- From generation 1 onward, every further generation is
  ``reverse(forward(gen_i)) == gen_{i+1}``.

This keeps "generation N" meaning the same thing for every corpus item: the
Nth LaTeX text produced by the reverse converter.
"""

import os
import sys
import shutil
import tempfile

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
for _p in (PROJECT_ROOT, _TESTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fidelity  # noqa: E402
from latexword.docx import write as latex2word  # noqa: E402
from latexword.docx import read as word2latex  # noqa: E402

MAX_GENERATION = 5

# How many `.docx` the five-generation convergence fixtures use. Every
# document would be more thorough, but the fixture costs O(documents x
# generations) full conversions and convergence is a property of the
# converter rather than of any one file -- the whole-corpus checks live in
# the fidelity sweeps instead. The *largest* documents are taken: they
# exercise the most constructs, and size is a name-free, stable selector.
DOCX_CONVERGENCE_SAMPLE = 6

# Pytest's default `%TEMP%\pytest-of-<user>` can be left with a sandbox
# security owner after an interrupted agent run.  Pytest scans that parent
# before creating `tmp_path`, so one stale protected child can make the whole
# suite fail.  Use a fresh user-owned directory outside the repository and
# remove it after the session instead of touching any pre-existing temp tree.
_SESSION_BASETEMP = None


def pytest_configure(config):
    global _SESSION_BASETEMP
    if config.option.basetemp is None:
        _SESSION_BASETEMP = tempfile.mkdtemp(prefix="latexword-pytest-")
        config.option.basetemp = _SESSION_BASETEMP


def pytest_sessionfinish(session, exitstatus):
    if _SESSION_BASETEMP:
        shutil.rmtree(_SESSION_BASETEMP, ignore_errors=True)


def _descriptors(paths, kind, prefix):
    """Label corpus files positionally. Never by filename -- corpus documents
    are private and get renamed, so a name-derived label would both leak
    content into failure reports and rot on the next rename."""
    return [{"name": "%s%02d" % (prefix, i), "kind": kind, "path": p}
            for i, p in enumerate(paths)]


CORPUS = (
    _descriptors(fidelity.collect_fixtures(), "tex", "fixture")
    + _descriptors(
        sorted(fidelity.collect_documents(), key=os.path.getsize,
               reverse=True)[:DOCX_CONVERGENCE_SAMPLE],
        "docx", "docx")
)


@pytest.fixture(scope="session")
def corpus():
    """The list of corpus document descriptors (name/kind/path)."""
    return CORPUS


def _write_tex(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _build_chain(name, kind, path, workdir, max_gen=MAX_GENERATION):
    """Compute generations 1..max_gen of the round-trip chain for one doc.

    Returns (generations, warnings_between) where ``generations`` maps
    generation index -> LaTeX text, and ``warnings_between`` maps
    (i, i+1) -> list of warnings collected while producing generation i+1
    from generation i (forward-conversion warnings followed by
    reverse-conversion warnings for that step).
    """
    generations = {}
    warnings_between = {}
    reference_doc = path if kind == "docx" else None

    r_path = os.path.join(workdir, f"{name}_r1.tex")

    if kind == "tex":
        d_path = os.path.join(workdir, f"{name}_d1.docx")
        _, fwd_warnings = latex2word.convert_latex_to_docx(path, d_path)
        text, rev_warnings = word2latex.docx_to_latex(d_path, tex_path=r_path)
        generations[1] = text
        # Warnings that could explain a 1->1 "self" step are not needed;
        # A2 only ever compares generation 1 against generation 2.
    elif kind == "docx":
        # tex_path is required, not optional, here: without it figures extract
        # next to the *private source document* (PLAN.md Appendix B).
        text, rev_warnings = word2latex.docx_to_latex(path, tex_path=r_path)
        generations[1] = text
    else:
        raise ValueError(f"unknown corpus kind: {kind!r}")

    _write_tex(r_path, generations[1])

    for i in range(2, max_gen + 1):
        d_path = os.path.join(workdir, f"{name}_d{i}.docx")
        _, fwd_warnings = latex2word.convert_latex_to_docx(
            r_path, d_path, reference_doc,
            reference_mode="copy" if reference_doc else "rewrite",
        )
        next_r_path = os.path.join(workdir, f"{name}_r{i}.tex")
        # The D-stage object sidecar is keyed by the final LaTeX path.  Use
        # that path for reverse conversion before writing the returned text;
        # otherwise the next generation receives the text without its private
        # Word-object payloads.
        text, rev_warnings = word2latex.docx_to_latex(
            d_path, tex_path=next_r_path
        )
        generations[i] = text
        warnings_between[(i - 1, i)] = list(fwd_warnings) + list(rev_warnings)
        r_path = next_r_path
        _write_tex(r_path, text)

    return generations, warnings_between


@pytest.fixture(scope="session")
def roundtrip_workdir():
    d = tempfile.mkdtemp(prefix="l2w_tests_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(scope="session")
def roundtrip_chains(corpus, roundtrip_workdir):
    """Session-cached {doc_name: (generations, warnings_between)} for every
    corpus document. Computed once; every test that needs conversions reads
    from here instead of re-running the pipeline.
    """
    chains = {}
    for doc in corpus:
        workdir = os.path.join(roundtrip_workdir, doc["name"])
        os.makedirs(workdir, exist_ok=True)
        chains[doc["name"]] = _build_chain(
            doc["name"], doc["kind"], doc["path"], workdir
        )
    return chains
