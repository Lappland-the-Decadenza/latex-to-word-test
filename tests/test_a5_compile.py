"""A5 -- compile check.

Compiles the final, converged generation of each corpus document with
``xelatex -interaction=nonstopmode`` (MiKTeX). Two independent assertions
per document:

(a) ``xelatex`` exits 0.
(b) the resulting ``.log`` contains zero "Missing character" lines.

(a) used to fail on one corpus document (defect B7 -- a standalone operator-name run
reconstructed with no trailing space glued onto the next run: ``\\tanh`` +
``f`` -> ``\\tanhf``, an undefined control sequence). Fixed in
``word2latex._convert_run`` -- see ``tests/test_b7_operator_name_spacing.py``.

(b) used to fail on every document containing non-Latin (in this corpus:
Cyrillic) text, in two layers. First, the generated preamble had no
``fontspec`` support at all (defect B8); fixed by adding ``fontspec`` + a
Unicode-covering main font (``DejaVu Serif``) plus an xelatex engine
declaration to the preamble whenever the emitted LaTeX is non-ASCII -- see
``word2latex.docx_to_latex``. That alone cleared one corpus document but not
two others: both have literal Cyrillic text sitting directly
inside math mode with no ``\\text{}`` wrapper, which ``\\setmainfont`` does
not reach (it only affects the *text* font, not ``cmmi10``, the math italic
font OMML/LaTeX math mode actually uses) -- defect B8b. Fixed per
``CANONICAL.md`` Rule 9 by wrapping maximal runs of non-mathematical,
non-ASCII alphabetic text in ``\\text{...}`` during reverse conversion --
see ``word2latex._convert_text_run`` / ``_is_literal_text_char``.

Cleanly skipped (not failed) if ``xelatex`` is not on PATH.
"""

import os
import shutil
import subprocess
import base64

import pytest

from conftest import MAX_GENERATION
from latexword.latex import validate_shadow

XELATEX = shutil.which("xelatex")
REAL_TEX_ENGINE = next(
    (shutil.which(name) for name in ("xelatex", "pdflatex", "lualatex") if shutil.which(name)),
    None,
)

_V1_FIXTURE = r"""\documentclass{article}
\usepackage{amsmath,amssymb,graphicx,xcolor,soul,ulem,enumitem,booktabs,multirow,hyperref,todonotes,xfrac}
\begin{document}
\section{Section}\subsection{Subsection}\subsubsection{Subsubsection}\paragraph{Paragraph}
plain \textbf{bold} \emph{italic} \textit{italic} \texttt{mono} \textsc{small} \underline{under} \sout{strike}
\textsuperscript{up} \textsubscript{down} \textcolor[HTML]{008000}{green} \colorbox[HTML]{FFFF00}{fill} \hl{highlight}
\href{https://example.test}{link} \url{https://example.test} \footnote{note} \label{anchor} \ref{anchor} \pageref{anchor} \cite{key}
\todo[inline,color=red]{todo} inline math $x^2$ and a hard break\\ followed by a soft\linebreak{}break.
\begin{itemize}\item item\begin{enumerate}[label=\alph*.,start=2]\item nested\end{enumerate}\end{itemize}
\begin{description}\item[Term] described\end{description}
\begin{quote}quoted\end{quote}\begin{quotation}quoted\end{quotation}
\begin{center}centered\end{center}\begin{flushleft}left\end{flushleft}\begin{flushright}right\end{flushright}
\begin{table}\caption{Table caption}\begin{tabular}{ll}\toprule a & b \\\midrule \multicolumn{2}{l}{c} \\\multirow{2}{*}{d} & e \\\bottomrule\end{tabular}\end{table}
\begin{figure}\includegraphics{owned.png}\caption{Figure caption}\label{figure}\end{figure}
\begin{verbatim}literal\end{verbatim}\newpage
\begin{equation}x=\genfrac{}{}{0pt}{}{a}{b}\end{equation}
\begin{equation*}x=\sfrac{a}{b}\end{equation*}\begin{align}x\end{align}\begin{align*}x\end{align*}
\begin{gather}x\end{gather}\begin{gather*}x\end{gather*}
\end{document}
"""

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _compile(tex_path, workdir, engine="xelatex"):
    proc = subprocess.run(
        [
            engine,
            "-interaction=nonstopmode",
            "-no-shell-escape",
            "-output-directory",
            workdir,
            tex_path,
        ],
        cwd=workdir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    log_path = os.path.splitext(tex_path)[0] + ".log"
    missing_char_lines = 0
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            missing_char_lines = sum(1 for line in f if "Missing character" in line)
    return proc.returncode, missing_char_lines


def test_every_v1_production_compiles_when_a_tex_engine_is_available(tmp_path):
    assert not validate_shadow(_V1_FIXTURE, known_resources={"owned.png"})
    if REAL_TEX_ENGINE is None:
        pytest.skip("no real TeX engine found on PATH")
    tex_path = tmp_path / "v1_fixture.tex"
    tex_path.write_text(_V1_FIXTURE, encoding="utf-8")
    (tmp_path / "owned.png").write_bytes(_PNG)
    exit_code, missing_char_lines = _compile(
        str(tex_path), str(tmp_path), engine=REAL_TEX_ENGINE
    )
    log_path = tex_path.with_suffix(".log")
    log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    assert exit_code == 0
    assert missing_char_lines == 0
    assert "Undefined control sequence" not in log


def test_v1_accepts_supported_prose_control_symbols():
    source = r"""\documentclass{article}
\begin{document}
text\ text\,text\;text\-text
\end{document}
"""
    assert not validate_shadow(source)


@pytest.fixture(scope="session")
def compile_results(corpus, roundtrip_chains, roundtrip_workdir):
    if XELATEX is None:
        pytest.skip("xelatex not found on PATH")
    results = {}
    for doc in corpus:
        name = doc["name"]
        generations, _ = roundtrip_chains[name]
        final_tex = generations[MAX_GENERATION]
        doc_workdir = os.path.join(roundtrip_workdir, name)
        workdir = os.path.join(doc_workdir, "a5_compile")
        os.makedirs(workdir, exist_ok=True)
        tex_path = os.path.join(workdir, "final.tex")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(final_tex)
        # PLAN_DOCLAYER.md stage 3: docx_to_latex extracted any images into a
        # "<stem>.figures/" directory sibling to the .docx it read (the same
        # directory every generation of this chain lives in), not sibling to
        # "final.tex" itself -- copy them alongside so a relative
        # \includegraphics path in the copied-out final.tex still resolves.
        if os.path.isdir(doc_workdir):
            for entry in os.listdir(doc_workdir):
                if entry.endswith(".figures") and os.path.isdir(os.path.join(doc_workdir, entry)):
                    dest = os.path.join(workdir, entry)
                    if not os.path.isdir(dest):
                        shutil.copytree(os.path.join(doc_workdir, entry), dest)
        exit_code, missing_char_lines = _compile(tex_path, workdir)
        results[name] = (exit_code, missing_char_lines)
    return results


def test_compiles_with_exit_code_zero(corpus, compile_results):
    failures = [
        f"{name}: exit code {exit_code}"
        for name in (d["name"] for d in corpus)
        for exit_code, _ in [compile_results[name]]
        if exit_code != 0
    ]
    assert not failures, "xelatex failed:\n" + "\n".join(failures)


def test_compiles_without_missing_characters(corpus, compile_results):
    failures = [
        f"{name}: {missing_char_lines} 'Missing character' line(s)"
        for name in (d["name"] for d in corpus)
        for _, missing_char_lines in [compile_results[name]]
        if missing_char_lines
    ]
    assert not failures, "missing characters in compiled PDF:\n" + "\n".join(failures)
