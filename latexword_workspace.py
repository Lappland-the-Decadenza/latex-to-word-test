"""CLI shim for the LaTeXWord workspace commands."""

from latexword.cli.encoding import configure_utf8_stdio
from latexword.cli.workspace import main


if __name__ == "__main__":
    configure_utf8_stdio()
    raise SystemExit(main())
