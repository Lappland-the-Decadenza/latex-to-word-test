"""Console encoding setup for the command-line entry points."""

import sys


def configure_utf8_stdio() -> None:
    """Make this Python process read and write console text as UTF-8."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
