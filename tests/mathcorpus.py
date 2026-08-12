r"""The shared math-expression corpus: every math-mode expression the project
has: the checked-in `.tex` fixtures plus the generation-1 `.tex` produced by
reverse-converting every hand-authored `.docx` in the corpus directory. Both
sets are discovered by scanning -- see `fidelity.collect_fixtures` /
`fidelity.collect_documents` for why nothing here may name a file.

R2b parses these, R3 emits OMML for them and R4 integrates -- all three
stages read the same list from here rather than each re-deriving it, so
"the corpus" means one thing across the whole rewrite.

Extraction is deliberately *syntactic and dumb*: it finds math zones
(`$...$`, `$$...$$`, `\[...\]`, `\(...\)` and the math environments) and
hands back their source text verbatim. It does not parse, normalise or
repair anything -- that is exactly the job under test.

Two classes of environment, because they mean different things to Rule 5:

- `equation`/`equation*`/`displaymath`/`math` are pure *wrappers* around one
  expression (Rule 4 canonicalises them all to `\[...\]`), so the wrapper is
  stripped and the body is the expression.
- `align`/`align*`/`gather*`/`cases`/`pmatrix`/... are *content*: the
  environment name carries the multi-row structure (Rule 5), so the whole
  `\begin{...}...\end{...}` is the expression.
"""

import os
import re
import sys
from collections import namedtuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
for _p in (PROJECT_ROOT, _TESTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fidelity import collect_documents, collect_fixtures


# A math expression together with enough provenance to name it in a failure
# report: which file it came from, its ordinal within that file, and whether
# it was written as display or inline math.
MathExpr = namedtuple("MathExpr", "source index display tex")


def _sources(paths, prefix):
    """Label each discovered corpus file positionally (`tex03`, `docx11`).

    Positional rather than by filename: the corpus documents are private and
    renamed for privacy, so a label derived from the name would leak content
    into every failure report and change under the maintainer's feet. The
    label only has to be stable within one run and point back at a file, which
    `path` already does.
    """
    return [("%s%02d" % (prefix, i), p) for i, p in enumerate(paths)]


TEX_SOURCES = _sources(collect_fixtures(), "fixture")
DOCX_SOURCES = _sources(collect_documents(), "docx")


# Environments whose name is a wrapper only: the expression is the body.
WRAPPER_ENVS = ("equation", "displaymath", "math")
# Environments whose name is content: the expression is the whole block.
STRUCTURE_ENVS = (
    "align", "alignat", "aligned", "gather", "gathered", "eqnarray",
    "multline", "split", "flalign",
)

_ENV_ALT = "|".join(
    [re.escape(e) + r"\*?" for e in WRAPPER_ENVS + STRUCTURE_ENVS]
)

# The `$...$` branch must lex `\\` as one token, never as an escape of the
# following character: the reverse converter emits a run-level `w:br` as `\\`
# directly before a following inline math zone (`prose\\$x$`), and `\\.` would
# read the second backslash as escaping the `$` -- so the opening `$` looked
# escaped, the zone was not extracted, and its *closing* `$` then paired with
# the next zone's opening `$`, cascading prose into a garbage zone for the
# rest of the document (measured on a corpus document with two
# break-then-math paragraphs). Two delimiters are unescaped `$`: one preceded
# by a non-backslash, and one preceded by exactly `\\`.
_MATH_RE = re.compile(
    r"\\begin\{(?P<env>" + _ENV_ALT + r")\}(?P<envbody>.*?)\\end\{(?P=env)\}"
    r"|\\\[(?P<disp>.*?)\\\]"
    r"|\\\((?P<inl>.*?)\\\)"
    r"|\$\$(?P<dd>.*?)\$\$"
    r"|(?:(?<!\\)|(?<=\\\\))\$(?P<d>(?:\\\\|[^\\$]|\\[^\\])*?)(?<!\\)\$",
    re.S,
)

# `\verb|...|` can contain literal `$` and backslashes that are not math and
# not macros; drop those spans before scanning (skill_conformant.tex has
# `\verb|\left|`).
_VERB_RE = re.compile(r"\\verb(.)(.*?)\1", re.S)

# An unescaped `%` starts a comment. `\%` does not.
_COMMENT_RE = re.compile(r"(?<!\\)%[^\n]*")


def _strip_noise(text):
    text = _VERB_RE.sub("", text)
    text = _COMMENT_RE.sub("", text)
    return text


def _trim(tex):
    r"""Strip the padding around a math zone without eating a trailing control
    space.

    A plain `.strip()` turns `... \mu \ ` into `... \mu \` -- a lone backslash,
    which is not valid LaTeX and which the parser correctly rejects. That read
    as 7 corpus-wide parse failures that were entirely an artifact of this
    function: the converter's output was fine. The space after `\` is content
    (Rule 7's control space), not padding, so it is put back.
    """
    tex = tex.strip()
    if tex.endswith("\\") and not tex.endswith("\\\\"):
        tex += " "
    return tex


def extract_math(text, source="<text>"):
    """Yield every math expression in one LaTeX document, in source order."""
    text = _strip_noise(text)
    out = []
    for i, m in enumerate(_MATH_RE.finditer(text)):
        env = m.group("env")
        if env is not None:
            base = env.rstrip("*")
            if base in WRAPPER_ENVS:
                tex, display = m.group("envbody"), True
            else:
                tex, display = m.group(0), True
        elif m.group("disp") is not None:
            tex, display = m.group("disp"), True
        elif m.group("dd") is not None:
            tex, display = m.group("dd"), True
        elif m.group("inl") is not None:
            tex, display = m.group("inl"), False
        else:
            tex, display = m.group("d"), False
        if tex is not None and tex.strip():
            out.append(MathExpr(source, len(out), display, _trim(tex)))
    return out


def _generation_1_tex(docx_path):
    """Reverse-convert one `.docx` -- "generation 1" as `conftest.py` defines
    it. Produced live rather than from a checked-in snapshot so the corpus
    always tracks the current reverse converter, which is the reference the
    parser must accept.
    """
    from latexword.docx import read as word2latex

    tex, _warnings = word2latex.docx_to_latex(docx_path)
    return tex


_CACHE = None


def collect():
    """Every math expression in the whole corpus. Cached per process --
    reverse-converting the `.docx` documents is the slow part and its result
    never changes within a run."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    exprs = []
    for name, path in TEX_SOURCES:
        with open(path, encoding="utf-8") as f:
            exprs.extend(extract_math(f.read(), name))
    for name, path in DOCX_SOURCES:
        exprs.extend(extract_math(_generation_1_tex(path), name + "_r1"))
    _CACHE = exprs
    return exprs
