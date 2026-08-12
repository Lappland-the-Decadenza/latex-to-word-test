"""LaTeX solidus handling for native Word fraction shapes."""

from ..ast import Frac, Op, Space


def fold_linear_fraction(parser, node, stop):
    """Fold a bare solidus into Word's native ``m:f type=lin`` shape."""
    while True:
        slash = parser.peek()
        if slash.kind != "char" or slash.text != "/":
            return node
        save = parser.i
        parser.advance()
        if parser.peek().kind in (
                "eof", "rbrace", "amp", "rowsep", "sub", "sup",
                "prime", "end") or stop(parser.peek()):
            parser.i = save
            return node
        denominator = parser.parse_scripted()
        if denominator is None or isinstance(denominator, Space):
            parser.i = save
            return node
        if isinstance(denominator, Op) and denominator.char in "/+-=<>":
            parser.i = save
            return node
        node = Frac(node, denominator, "lin")


__all__ = ["fold_linear_fraction"]
