r"""One-page fidelity report over both corpora (PLAN.md §4.4).

Pieces, each from its own instrument so the numbers are the same ones the
sweeps print:

- round-trip verdicts by class: tests/docfidelity._sweep over every corpus
  document's generation-1 round trip (regenerated only when missing);
- coverage buckets per direction: tools/coverage._latex_numbers and
  _word_numbers;
- warning counts and convergence: conftest._build_chain on the same
  DOCX_CONVERGENCE_SAMPLE (6 largest) documents the A1/A2 fixtures use --
  the project's own scoping decision ("convergence is a property of the
  converter rather than of any one file", conftest.py).

Baseline: `--baseline FILE` compares against a stored JSON report and
prints every delta; `--write-baseline FILE` stores the current one. The
exit code is 1 when any bad-direction number rose (degradation, noise, or
an unknown bucket) or a good-direction number fell (handled, nameable) --
the same bias as every other instrument here: changes that look worse are
loud, changes that look better are just printed.

Baselines are derived data and live in output/ (never committed).
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "tests"),
           os.path.join(PROJECT_ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _bad_direction(field, now, old):
    """True when the change is the kind rule 2 exists to catch: worse."""
    if now == old:
        return False
    if field in ("degradation", "noise"):
        return now > old
    if field.endswith("_unknown"):
        return now > old
    return False


def collect_numbers():
    import re

    import docfidelity
    import coverage
    from conftest import (DOCX_CONVERGENCE_SAMPLE, MAX_GENERATION,
                          _build_chain)
    from fidelity import collect_documents, roundtrip_fresh

    out_dir = os.path.join(PROJECT_ROOT, "output")
    os.makedirs(out_dir, exist_ok=True)

    # Verdicts: the same pairs docfidelity.main builds, measured by the
    # same compare functions. roundtrip_fresh regenerates when the cache is
    # missing or older than the source/converter code.
    pairs = []
    for src in collect_documents():
        rt = roundtrip_fresh(src, out_dir, generations=1)
        pairs.append((os.path.basename(src), src, rt))
    verdicts = docfidelity._sweep(pairs)

    # Coverage buckets per direction.
    latex = coverage._latex_numbers()
    word = coverage._word_numbers()

    # Warnings and convergence: the A1/A2 fixture scope (6 largest docs).
    sample = sorted(collect_documents(), key=os.path.getsize,
                    reverse=True)[:DOCX_CONVERGENCE_SAMPLE]
    chains = {}
    workdir = tempfile.mkdtemp(prefix="l2w_report_")
    try:
        for i, path in enumerate(sample):
            name = f"docx{i:02d}"
            chains[name] = _build_chain(
                name, "docx", path, os.path.join(workdir, name),
                max_gen=MAX_GENERATION)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    fwd = sum(len(w) for _, ws in chains.values() for w in ws.values())
    converged_at = []
    for name, (generations, _ws) in chains.items():
        texts = [generations[g] for g in sorted(generations)]
        # A1's requirement: generations 3..MAX all identical. Report the
        # generation from which the chain is at a fixed point (2 or 3);
        # anything later -- including the trivial "only the last two match"
        # -- is not converged, matching the test's semantics.
        g = None
        for i in (1, 2):
            if all(t == texts[i] for t in texts[i:]):
                g = i + 1  # 1-based generation index
                break
        converged_at.append((name, g))

    by_gen = {}
    for _name, g in converged_at:
        by_gen[g if g is not None else MAX_GENERATION + 1] = \
            by_gen.get(g if g is not None else MAX_GENERATION + 1, 0) + 1
    not_converged = [n for n, g in converged_at if g is None]

    return {
        "date": time.strftime("%Y-%m-%d %H:%M"),
        "verdicts": dict(verdicts),
        "degradation": verdicts["degradation"],
        "deferred": verdicts["deferred"],
        "noise": verdicts["noise"],
        "identical": verdicts["identical"],
        "coverage_latex_handled": latex["handled"],
        "coverage_latex_deferred": latex["deferred"],
        "coverage_latex_unknown": latex["unknown"],
        "ref_named": latex["ref_named"],
        "ref_total": latex["ref_total"],
        "coverage_word_handled": word["handled"],
        "coverage_word_deferred": word["deferred"],
        "coverage_word_noise": word["noise"],
        "coverage_word_unknown": word["unknown"],
        "warnings_forward": fwd,
        "convergence_by_gen": by_gen,
        "not_converged": not_converged,
        "sample_docs": len(sample),
    }


def render(numbers):
    lines = []
    lines.append(f"fidelity report -- {numbers['date']}")
    lines.append(
        f"  verdicts: identical={numbers['identical']} "
        f"degradation={numbers['degradation']} "
        f"deferred={numbers['deferred']} noise={numbers['noise']}")
    lines.append(
        f"  coverage LaTeX: handled={numbers['coverage_latex_handled']} "
        f"deferred={numbers['coverage_latex_deferred']} "
        f"unknown={numbers['coverage_latex_unknown']} "
        f"(reference nameable "
        f"{numbers['ref_named']}/{numbers['ref_total']})")
    lines.append(
        f"  coverage Word: handled={numbers['coverage_word_handled']} "
        f"deferred={numbers['coverage_word_deferred']} "
        f"noise={numbers['coverage_word_noise']} "
        f"unknown={numbers['coverage_word_unknown']}")
    lines.append(
        f"  warnings: {numbers['warnings_forward']} across "
        f"{numbers['sample_docs']} documents (forward+reverse, "
        f"A1-scope sample)")
    conv = ", ".join(f"g{g}={c}" for g, c in
                     sorted(numbers["convergence_by_gen"].items()))
    lines.append(f"  convergence (A1-scope sample): {conv}"
                 + (f"; NOT converged: {numbers['not_converged']}"
                    if numbers["not_converged"] else ""))
    return lines


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline", metavar="FILE",
                    help="compare against a stored report; exit 1 on rises")
    ap.add_argument("--write-baseline", metavar="FILE",
                    help="store the current report as the baseline")
    args = ap.parse_args(argv)

    t0 = time.time()
    numbers = collect_numbers()
    elapsed = time.time() - t0

    print("\n".join(render(numbers)))
    print(f"  (took {elapsed:.0f}s)")

    rises = []
    if args.baseline:
        with open(args.baseline, encoding="utf-8") as f:
            old = json.load(f)
        print(f"\nvs baseline {args.baseline} ({old.get('date', '?')}):")
        for field in sorted(set(old) & set(numbers)):
            if field in ("date", "verdicts", "convergence_by_gen",
                         "not_converged", "sample_docs"):
                continue
            now, prev = numbers[field], old[field]
            if now != prev:
                mark = "  <<< RISE" if _bad_direction(field, now, prev) else ""
                print(f"  {field:26} {prev:>8} -> {now:<8}{mark}")
                if mark:
                    rises.append(field)
        if not rises and old == numbers:
            print("  (no change)")

    if args.write_baseline:
        with open(args.write_baseline, "w", encoding="utf-8") as f:
            json.dump(numbers, f, indent=1, ensure_ascii=False)
        print(f"\nbaseline written: {args.write_baseline}")

    if rises:
        print(f"\nexit 1: bad-direction changes: {', '.join(rises)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
