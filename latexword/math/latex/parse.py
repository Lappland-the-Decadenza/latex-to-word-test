"""Recursive-descent parser assembled from focused parser mixins."""

from .parse_shared import UnexpectedTokenError, _stop_eof, tokenize, tokenize_with_macros
from .parse_handlers import _is_opname_expr
from .parse_sequence import _SequenceParserMixin
from .parse_atoms import _AtomParserMixin
from .parse_environment import _EnvironmentParserMixin


class _Parser(_SequenceParserMixin, _AtomParserMixin, _EnvironmentParserMixin):
    def __init__(self, src, warnings=None, toks=None):
        self.src = src
        self.toks = tokenize(src) if toks is None else toks
        self.i = 0
        self.warnings = warnings

    def peek(self, k=0):
        j = min(self.i + k, len(self.toks) - 1)
        return self.toks[j]

    def advance(self):
        t = self.toks[self.i]
        if t.kind != "eof":
            self.i += 1
        return t

    def fail(self, cls, message, tok=None):
        tok = tok if tok is not None else self.peek()
        raise cls(message, self.src, tok.pos, tok.text)


def parse(tex, warnings=None):
    """Parse native math LaTeX into the structural AST.
    declared vocabulary. `warnings` is the optional ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â§6.2 sink: tolerated
    """
    toks, _env = tokenize_with_macros(tex, warnings)
    p = _Parser(tex, warnings, toks)
    row = p.parse_sequence(_stop_eof)
    if p.peek().kind != "eof":  # pragma: no cover - parse_sequence guarantees
        p.fail(UnexpectedTokenError, "trailing input")
    return row




__all__ = [name for name in globals() if not name.startswith("__")]
