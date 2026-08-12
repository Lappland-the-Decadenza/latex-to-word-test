"""Shared imports and parser primitives.

Parser mixins keep the recursive descent owner modules below the architecture
limit while preserving one parser class and one set of globals.
"""

from ..ast import Accent, Bar, Boxed, Delim, Frac, Func, GroupChr, Ident, Limit, Matrix, Nary, Num, Op, OpName, Phantom, PreScript, Rad, Row, Script, Space, Text
from ..common import _ASCII_CONTENT, _BARE_CLOSERS, _BARE_PAIRS, _BIG_CLOSER_ONLY, _BIG_SIZERS, _ENV_ALIASES, _ESCAPED_LITERALS, _GENFRAC, _MACRO_ALIASES, _MATHRM, _MATRIX_ENVS, _NARY_LIMITS_MODIFIER, _NARY_NOLIMITS_MODIFIER, _OPERATORNAME, _PMOD_INNER_WIDTH, _PMOD_OUTER_WIDTH, _STYLE_NOOPS, _TOLERATED, _TOLERATED_WITH_ARG, _UNSUPPORTED, _VARIANT_CHAR, _VARIANT_COMBINE, _VARIANT_MACROS, _fold_delim_matrix, PRIME, LatexParseError, MalformedArgumentError, UnbalancedDelimiterError, UnexpectedTokenError, UnknownMacroError, UnsupportedConstructError, MACRO_TO_CONSTRUCT, re
from .genfrac import consume_no_rule_parameters
from .fractions import fold_linear_fraction
from ...mathsyms import CLOSE_CHARS, DELIM_SPELLING_TO_CHAR, LIMIT_OPS, MACRO_TO_CHAR, NARY_BODY_BINARY_CHARS, NARY_BODY_RELATION_CHARS, NARY_UNDOVR, NBSP_CHAR, SYMBOL_MAP, TEXT_ESCAPE_TO_CHAR, VARIANT_REVERSE
from .tokenize import tokenize
from .macros import tokenize_with_macros

class _NaryHead:
    """Internal marker for an n-ary operator before its body is parsed."""
    __slots__ = ("op", "sub", "sup", "limits")

    def __init__(self, op, sub, sup, limits=None):
        self.op = op
        self.sub = sub
        self.sup = sup
        self.limits = limits


def _stop_eof(t):
    return t.kind == "eof"


def _stop_rbrace(t):
    return t.kind == "rbrace"


__all__ = [name for name in globals() if name not in {"__name__", "__package__", "__loader__", "__spec__", "__builtins__"}]
