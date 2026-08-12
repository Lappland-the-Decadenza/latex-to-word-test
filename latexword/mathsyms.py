"""Character-level truth, re-exported (PLAN.md §5.3).

The character tables live in `latexword/symbols/`: the bidirectional
families (symbols, delimiters, n-ary operators, accents, spaces, `\\text{}`
escapes) are declared once in `symbols/registry.py` with both directions
generated; the one-directional families sit in `symbols/variants.py`,
`symbols/accents.py` and `symbols/opnames.py`. This module is a pure facade
-- no logic -- so every consumer keeps one import surface and the
dependency rule "math imports character truth only through mathsyms" stays
structural. *Structural* truth belongs in `mathast.py`, not here.

This module must not import anything from the rest of the project except
the symbols subpackage (no circular imports): it stays near the base of
the dependency graph.
"""

from .symbols.accents import ACCENT_CHARS, BAR_CHARS
from .symbols.opnames import (
    BIG_OP_NAMES,
    KNOWN_FUNC_MACROS,
    LIMIT_OPS,
    NARY_BODY_BINARY_CHARS,
    NARY_BODY_RELATION_CHARS,
)
from .symbols.registry import (
    ACCENT_REVERSE,
    ACCENT_REVERSE_ALIASES,
    ACCENT_TO_CHAR,
    AMBIGUOUS_CHARS,
    CLOSE_CHARS,
    CONTROL_SPACE_CHAR,
    CONTROL_SPACE_LATEX,
    DELIM_LEFTRIGHT,
    DELIM_SPELLING_TO_CHAR,
    MACRO_TO_CHAR,
    NARY_CHARS,
    NARY_MACROS,
    NARY_UNDOVR,
    NBSP_CHAR,
    OPEN_CHARS,
    SPACE_CHAR_ALIASES,
    SPACE_CHARS,
    SPACE_MACRO_TO_GLYPH,
    SPACE_TO_LATEX,
    SYMBOL_MAP,
    TEXT_CHAR_TO_ESCAPE,
    TEXT_ESCAPE_TO_CHAR,
)
from .symbols.variants import (
    _COMPOUND_PRIMES,
    _VARIANT_BASES,
    _VARIANT_HOLES,
    VARIANT_REVERSE,
)
