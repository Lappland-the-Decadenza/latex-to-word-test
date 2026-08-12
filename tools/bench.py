r"""End-to-end performance budget over both corpora (PLAN.md §5.4).

One full round trip over each corpus, driven with the same calls the sweeps
use -- no benchmarking harness of its own, so the number means the same
thing the fidelity sweeps do:

- docx corpus (tests/corpus_docx/):  docx -> tex -> docx  (generation 1)
- tex corpus (tests/corpus/):        tex  -> docx -> tex  (generation 1)

Per leg, per document wall-clock time, measured with `time.perf_counter`
around the exact conversion call (the reverse leg includes writing the
extracted .tex, since the forward leg reads that file back -- that is the
real pipeline, PLAN.md Appendix B). Documents are labelled positionally
(docx00.., tex00..) in descending size order -- the same stable, name-free
selector conftest.py uses -- so a later run times the same documents.

Reported: per-direction totals, per-document averages and worst cases, and
the five slowest documents of each leg ("optimise only what the measurement
names", §5.4). No caching, no lazy loading, no C extension was added to
make this number look good; the budget is a measurement of the structure as
it stands, and Plan 2 (live sync) needs this engine on every keystroke.

Budget: `--write-baseline FILE` stores a run as the budget;
`--baseline FILE` compares and exits 1 when any recorded number is beaten.
Same bias as every other instrument here: regressions are loud,
improvements are just printed. Budgets are derived data and live in
output/ (never committed).

The comparison resolves at the report's own precision (0.01s). Below that
the numbers are machine noise -- cache temperature, antivirus, scheduler
luck -- and a budget that exits 1 on sub-millisecond jitter would fail on
every second run and teach nobody anything. Structural regressions (a new
scan per construct, an accidental re-parse loop) arrive as multiples, not
as 5ms: the per-leg totals accumulate them across the whole corpus, so a
regression too small to see on one document still clears the rounding on
the total.
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

from latexword.docx import read as word2latex
from latexword.docx import write as latex2word


def _legs(pairs, kind, workdir, results):
    """Time one leg of each round trip in `pairs` (label, source path).

    `kind` selects which leg runs first; the other leg runs on its output,
    so both corpora get one full round trip. Appends to `results` the dict
    of lists `{leg: [(label, seconds), ...]}`.
    """
    reverse, forward = results["reverse"], results["forward"]
    for label, src in pairs:
        tex_path = os.path.join(workdir, f"{label}_r1.tex")
        docx_path = os.path.join(workdir, f"{label}_d1.docx")

        if kind == "docx":
            # Reverse first: original .docx -> .tex (figures extract into
            # workdir, never next to the private source).
            t0 = time.perf_counter()
            text, _w = word2latex.docx_to_latex(src, tex_path=tex_path)
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(text)
            reverse.append((label, time.perf_counter() - t0))
            # Forward: that .tex -> .docx.
            t0 = time.perf_counter()
            latex2word.convert_latex_to_docx(
                tex_path, docx_path, src, reference_mode="copy"
            )
            forward.append((label, time.perf_counter() - t0))
        else:
            # Forward first: original .tex -> .docx, then reverse.
            t0 = time.perf_counter()
            latex2word.convert_latex_to_docx(src, docx_path)
            forward.append((label, time.perf_counter() - t0))
            t0 = time.perf_counter()
            text, _w = word2latex.docx_to_latex(docx_path, tex_path=tex_path)
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(text)
            reverse.append((label, time.perf_counter() - t0))


def _summarise(times):
    """Total, average and worst seconds from (label, seconds) pairs."""
    if not times:
        return {"total": 0.0, "avg": 0.0, "worst": 0.0}
    total = sum(t for _, t in times)
    return {"total": total, "avg": total / len(times),
            "worst": max(t for _, t in times)}


def collect_numbers():
    import fidelity

    workdir = tempfile.mkdtemp(prefix="l2w_bench_")
    try:
        docx_srcs = sorted(fidelity.collect_documents(), key=os.path.getsize,
                           reverse=True)
        tex_srcs = sorted(fidelity.collect_tex_corpus(), key=os.path.getsize,
                          reverse=True)
        docx_pairs = [(f"docx{i:02d}", p) for i, p in enumerate(docx_srcs)]
        tex_pairs = [(f"tex{i:02d}", p) for i, p in enumerate(tex_srcs)]

        docx_results = {"reverse": [], "forward": []}
        tex_results = {"reverse": [], "forward": []}
        _legs(docx_pairs, "docx", workdir, docx_results)
        _legs(tex_pairs, "tex", workdir, tex_results)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    rd, fd = _summarise(docx_results["reverse"]), _summarise(docx_results["forward"])
    rt, ft = _summarise(tex_results["reverse"]), _summarise(tex_results["forward"])
    return {
        "date": time.strftime("%Y-%m-%d %H:%M"),
        "corpus_docx": len(docx_pairs),
        "corpus_tex": len(tex_pairs),
        "reverse_docx_total": rd["total"], "reverse_docx_avg": rd["avg"],
        "reverse_docx_worst": rd["worst"],
        "forward_docx_total": fd["total"], "forward_docx_avg": fd["avg"],
        "forward_docx_worst": fd["worst"],
        "forward_tex_total": ft["total"], "forward_tex_avg": ft["avg"],
        "forward_tex_worst": ft["worst"],
        "reverse_tex_total": rt["total"], "reverse_tex_avg": rt["avg"],
        "reverse_tex_worst": rt["worst"],
        "total_seconds": rd["total"] + fd["total"] + ft["total"] + rt["total"],
        "slowest_docx_reverse": sorted(docx_results["reverse"],
                                       key=lambda it: it[1],
                                       reverse=True)[:5],
        "slowest_docx_forward": sorted(docx_results["forward"],
                                       key=lambda it: it[1],
                                       reverse=True)[:5],
        "slowest_tex_forward": sorted(tex_results["forward"],
                                      key=lambda it: it[1], reverse=True)[:5],
        "slowest_tex_reverse": sorted(tex_results["reverse"],
                                      key=lambda it: it[1], reverse=True)[:5],
    }


def render(numbers):
    lines = []
    lines.append(f"bench -- {numbers['date']}")
    lines.append(f"  corpora: {numbers['corpus_docx']} docx, "
                 f"{numbers['corpus_tex']} tex (full round trip each)")
    lines.append("  docx corpus:")
    lines.append(f"    reverse docx->tex: total={numbers['reverse_docx_total']:6.2f}s "
                 f"avg={numbers['reverse_docx_avg']:.2f}s "
                 f"worst={numbers['reverse_docx_worst']:.2f}s")
    lines.append(f"    forward tex->docx: total={numbers['forward_docx_total']:6.2f}s "
                 f"avg={numbers['forward_docx_avg']:.2f}s "
                 f"worst={numbers['forward_docx_worst']:.2f}s")
    lines.append("  tex corpus:")
    lines.append(f"    forward tex->docx: total={numbers['forward_tex_total']:6.2f}s "
                 f"avg={numbers['forward_tex_avg']:.2f}s "
                 f"worst={numbers['forward_tex_worst']:.2f}s")
    lines.append(f"    reverse docx->tex: total={numbers['reverse_tex_total']:6.2f}s "
                 f"avg={numbers['reverse_tex_avg']:.2f}s "
                 f"worst={numbers['reverse_tex_worst']:.2f}s")
    lines.append(f"  total round trip: {numbers['total_seconds']:.2f}s")
    lines.append("  slowest 5 per leg (the measurement's nominations):")
    for leg, rows in (("docx reverse", numbers["slowest_docx_reverse"]),
                      ("docx forward", numbers["slowest_docx_forward"]),
                      ("tex forward", numbers["slowest_tex_forward"]),
                      ("tex reverse", numbers["slowest_tex_reverse"])):
        if rows:
            lines.append("    " + leg + ": " + ", ".join(
                f"{label}={sec:.2f}s" for label, sec in rows))
    return lines


def _timed_fields(numbers):
    """The measured numbers the budget constrains (everything except the
    date, corpus counts and the slowest lists)."""
    return [k for k in numbers
            if k not in ("date", "corpus_docx", "corpus_tex")
            and not k.startswith("slowest_")]


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline", metavar="FILE",
                    help="compare against a stored budget; exit 1 on rises")
    ap.add_argument("--write-baseline", metavar="FILE",
                    help="store the current run as the budget")
    args = ap.parse_args(argv)

    t0 = time.time()
    numbers = collect_numbers()
    elapsed = time.time() - t0

    print("\n".join(render(numbers)))
    print(f"  (wall clock incl. report: {elapsed:.0f}s)")

    rises = []
    if args.baseline:
        with open(args.baseline, encoding="utf-8") as f:
            old = json.load(f)
        print(f"\nvs budget {args.baseline} ({old.get('date', '?')}):")
        for field in _timed_fields(numbers):
            if field not in old:
                continue
            # Round both sides to the report's 0.01s resolution: sub-10ms
            # differences are machine noise, not structure (see docstring).
            now, prev = round(numbers[field], 2), round(old[field], 2)
            if now > prev:
                print(f"  {field:24} {prev:8.2f}s -> {now:8.2f}s  <<< RISE")
                rises.append(field)
        if not rises:
            print("  (no rises — every recorded number within budget)")

    if args.write_baseline:
        with open(args.write_baseline, "w", encoding="utf-8") as f:
            json.dump(numbers, f, indent=1, ensure_ascii=False)
        print(f"\nbudget written: {args.write_baseline}")

    if rises:
        print(f"\nexit 1: over budget: {', '.join(rises)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
