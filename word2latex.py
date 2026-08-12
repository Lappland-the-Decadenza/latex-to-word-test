"""Thin CLI shim -- the implementation lives in ``latexword.docx.read``.

Usage:  python word2latex.py SOURCE.docx [OUTPUT.tex]
"""

import sys

from latexword.cli.encoding import configure_utf8_stdio
from latexword.docx.cli import main

if __name__ == "__main__":
    configure_utf8_stdio()
    sys.exit(main(sys.argv))
