"""Command-line orchestration for the reverse converter."""

import os
import sys

from .read import docx_to_latex
from . import read as _read
from . import write as _write
from .write import DocxPackageError, convert_latex_to_docx


def main(argv):
    if len(argv) < 2:
        print(_read.__doc__)
        return 1
    docx_path = argv[1]
    tex_path = (
        argv[2]
        if len(argv) > 2
        else os.path.splitext(docx_path)[0] + "_reversed.tex"
    )
    tex, warnings = docx_to_latex(docx_path, tex_path)
    with open(tex_path, "w", encoding="utf-8") as output:
        output.write(tex)
    print(f"Converted: {docx_path} -> {tex_path}")
    if warnings:
        print(f"{len(warnings)} warning(s):")
        seen = set()
        for warning in warnings:
            if warning not in seen:
                seen.add(warning)
                print(f"  - {warning}")
    return 0


def main_forward(argv):
    args = argv[1:]
    positionals = []
    reference_doc = None
    reference_mode = "rewrite"
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--reference-doc":
            if i + 1 >= len(args):
                print("--reference-doc requires a .docx path", file=sys.stderr)
                return 1
            reference_doc = args[i + 1]
            i += 2
            continue
        if arg.startswith("--reference-doc="):
            reference_doc = arg.split("=", 1)[1]
            if not reference_doc:
                print("--reference-doc requires a .docx path", file=sys.stderr)
                return 1
            i += 1
            continue
        if arg == "--reference-mode":
            if i + 1 >= len(args):
                print("--reference-mode requires rewrite or copy", file=sys.stderr)
                return 1
            reference_mode = args[i + 1]
            i += 2
            continue
        if arg.startswith("--reference-mode="):
            reference_mode = arg.split("=", 1)[1]
            if not reference_mode:
                print("--reference-mode requires rewrite or copy", file=sys.stderr)
                return 1
            i += 1
            continue
        if arg.startswith("-"):
            print(f"unknown option: {arg}", file=sys.stderr)
            return 1
        positionals.append(arg)
        i += 1
    if not 1 <= len(positionals) <= 2:
        print(_write.__doc__)
        return 1
    if reference_mode not in ("rewrite", "copy"):
        print("--reference-mode must be rewrite or copy", file=sys.stderr)
        return 1
    if reference_mode == "copy" and reference_doc is None:
        print("--reference-mode=copy requires --reference-doc", file=sys.stderr)
        return 1
    tex_path = positionals[0]
    docx_path = positionals[1] if len(positionals) > 1 else None
    try:
        out, warnings = convert_latex_to_docx(
            tex_path, docx_path, reference_doc, reference_mode
        )
    except DocxPackageError as exc:
        for issue in exc.issues:
            print(issue, file=sys.stderr)
        return 1
    print(f"Converted: {tex_path} -> {out}")
    if warnings:
        print(f"{len(warnings)} warning(s):")
        seen = set()
        for warning in warnings:
            if warning not in seen:
                seen.add(warning)
                print(f"  - {warning}")
    return 0
