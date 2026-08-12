"""Validate one or more DOCX package files."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from latexword.docx.package import validate_docx_package


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if len(argv) < 2:
        print(f"usage: {argv[0]} FILE [FILE ...]", file=sys.stderr)
        return 2

    status = 0
    for path in argv[1:]:
        issues = validate_docx_package(path)
        if issues:
            status = 1
            for issue in issues:
                print(f"{path}: {issue}")
    return status


if __name__ == "__main__":
    sys.exit(main())
