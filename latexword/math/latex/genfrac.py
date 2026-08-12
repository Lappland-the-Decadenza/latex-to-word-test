"""Native parameter handling for the approved no-rule fraction form."""

from ..common import MalformedArgumentError, UnsupportedConstructError


def consume_no_rule_parameters(parser, token):
    """Consume and validate ``genfrac``'s four shape parameters."""
    values = []
    for _ in range(4):
        argument = parser.advance()
        if argument.kind != "rawarg":
            parser.fail(
                MalformedArgumentError,
                "\\genfrac parameter is not braced",
                token,
            )
        values.append(argument.text)
    if values != ["", "", "0pt", ""]:
        parser.fail(
            UnsupportedConstructError,
            "only the no-rule \\genfrac form is in the native profile",
            token,
        )


__all__ = ["consume_no_rule_parameters"]
