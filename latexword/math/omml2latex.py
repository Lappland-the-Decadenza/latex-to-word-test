"""OMML -> LaTeX, math only: the public reverse API.

PLAN.md §5.1 killed the second LaTeX speller: this module no longer owns a
hand-written tree walker or a second LaTeX grammar. ``to_latex`` converts
via ``load`` (``math/load.py``: OMML tree -> AST) and
``latex2omml.serialize`` (AST -> canonical LaTeX) -- the very same
serializer the forward canonicalizer uses, so both directions share one
speller. The imports are made inside the function because ``math.load``
reaches back into ``latex2omml`` for its single-atom check; keeping them
local makes that dependency explicit and this module importable from
anywhere in the package.

What remains here:

- the OMML/Word namespace constants and the ``qm``/``qw``/``ln`` helpers,
  shared with the document layer;
- ``to_latex`` itself;
- the prose-escaping helpers, shared with ``docx_read.py`` (reverse) and
  ``docx_write.py`` (forward): a ``\\text{}`` body or ``\\href`` argument
  must escape the same LaTeX-special characters, and the helpers must stay
  next to the tables they read.

Character-level truth (SYMBOL_MAP, KNOWN_FUNC_MACROS, ...) lives in
``mathsyms.py``; structural truth in ``mathast.py``.
"""

import re

from lxml import etree
from ..document.text import (
    href_escape as _text_href_escape,
    href_unescape as _text_href_unescape,
    prose_escape as _text_prose_escape,
)

M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def qm(tag):
    return f"{{{M}}}{tag}"


def qw(tag):
    return f"{{{W}}}{tag}"


def ln(el):
    return etree.QName(el).localname


def to_latex(el):
    """OMML -> canonical LaTeX (L*).

    The single speller (PLAN.md §5.1): `load` converts the tree to
    the AST and `latex2omml.serialize` spells it -- the very same serializer
    the forward canonicalizer uses, so the reverse direction no longer owns
    a second LaTeX grammar. Never raises on a construct it doesn't
    recognise: unknown OMML tags are recursed into by `load` (their text
    survives, structure may not). The document layer (`docx_read.py`)
    records such fallbacks in its warning list -- same philosophy as
    `docx_write.py`."""
    from .latex.serialize import serialize
    from .omml.load import load
    node = load(el)
    if node is None:
        return ""
    return serialize(node)


# --- Prose escaping (shared with docx_read.py) -----------------------------

PROSE_ESCAPE_CHARS = {
    "\\": "\\textbackslash{}", "{": "\\{", "}": "\\}", "$": "\\$",
    "&": "\\&", "#": "\\#", "_": "\\_", "%": "\\%",
    "~": "\\textasciitilde{}", "^": "\\textasciicircum{}",
}
PROSE_REVERSE_REPLACEMENTS = [
    ("—", "---"), ("–", "--"),
    ("“", "``"), ("”", "''"),
    (" ", "~"),
]

# The braces terminate the control word without manufacturing whitespace.
# A previous canonical spelling always appended a space, which changed
# authored text such as "…оскільки" to "… оскільки" on a round trip.
_ELLIPSIS_RE = re.compile("…")


def _prose_escape(text):
    return _text_prose_escape(text)


def _href_escape(url):
    """Escape a ``\\href`` URL argument for emission (PLAN.md §4.5).

    Same character set as prose escaping, but deliberately *not* the prose
    idiom replacements (---/--/''/~): a URL is a verbatim-ish argument, and
    dashes and quotes are not prose idioms there. hyperref reads the first
    ``\\href`` argument as an ordinary macro argument and unescapes exactly
    this set itself, so the emitted LaTeX compiles for any URL containing
    one of these characters.
    """
    return _text_href_escape(url)


_HREF_UNESCAPE_SEQUENCES = sorted(
    ((v, k) for k, v in PROSE_ESCAPE_CHARS.items()),
    key=lambda item: len(item[0]), reverse=True,
)


def _href_unescape(text):
    """Inverse of :func:`_href_escape`, for the forward direction.

    Applies to *both* ``\\href`` arguments before they leave the parser: the
    URL must be restored before it lands in the package rels, and the display
    text before it lands in a run. A display text left escaped (the old
    behaviour) grew one extra copy of its escape sequence every generation,
    because the reverse pass escaped what was already an escape sequence --
    ``\\_`` became ``\\textbackslash{}\\_`` and never stopped. An unknown
    ``\\cmd`` sequence passes through untouched and stays stable, because the
    reverse pass re-escapes it and this pass undoes exactly that.
    """
    return _text_href_unescape(text)
