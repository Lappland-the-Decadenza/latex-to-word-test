"""Compatibility facade for the split math conversion pipeline.

The implementation is separated by responsibility into tokenizer, macro,
parser, serializer and OMML-emitter modules.  This module intentionally keeps
the historical public and diagnostic names available to callers and tools.
"""

from .ast import MACRO_TO_CONSTRUCT, qm
from .common import (
    LatexParseError, MalformedArgumentError, UnbalancedDelimiterError,
    UnexpectedTokenError, UnknownMacroError, UnsupportedConstructError,
    PRIME, _BIG_CLOSER_ONLY, _BIG_SIZERS, _ESCAPED_LITERALS,
    _MACRO_ALIASES, _UNSUPPORTED, _VARIANT_MACROS,
)
from .latex.macros import tokenize_with_macros
from .latex.parse import parse
from .latex.serialize import canonicalize, serialize
from .omml.emit import emit, emit_seq
from ..mathsyms import MACRO_TO_CHAR

__all__ = [name for name in globals() if not name.startswith("__")]
