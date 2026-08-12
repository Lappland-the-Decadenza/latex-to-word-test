"""Thin CLI shim -- the implementation lives in ``latexword.docx.write``.

Usage:  python latex2word.py input.tex [output.docx] [--reference-doc template.docx]
"""

import sys

from latexword.cli.encoding import configure_utf8_stdio
from latexword.docx.cli import main_forward as main

if __name__ == "__main__":
    configure_utf8_stdio()
    sys.exit(main(sys.argv))
