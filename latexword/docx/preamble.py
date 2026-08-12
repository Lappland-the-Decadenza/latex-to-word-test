"""Generate the native LaTeX envelope for the DOCX reader."""

import re


def _base_preamble():
    return [
        "\\documentclass{article}",
        "\\usepackage{amsmath,amssymb,amsfonts,mathtools}",
    ]


def _append_conditional_packages(preamble, body_text):
    uses_color = bool(
        re.search(r"\\(?:textcolor|colorbox)(?:\[HTML\])?\{", body_text)
    )
    uses_highlight = "\\hl{" in body_text
    uses_sout = "\\sout{" in body_text
    uses_cellcolor = "\\cellcolor{" in body_text
    if uses_color or uses_highlight or uses_cellcolor:
        preamble.append(
            "\\usepackage[table]{xcolor}" if uses_cellcolor
            else "\\usepackage{xcolor}"
        )
    if "\\multirow{" in body_text:
        preamble.append("\\usepackage{multirow}")
    if uses_sout:
        preamble.append("\\usepackage[normalem]{ulem}")
    if "\\begin{justify}" in body_text:
        preamble.append("\\usepackage{ragged2e}")
    if "\\href{" in body_text:
        preamble.append("\\usepackage{hyperref}")
    if "\\includegraphics" in body_text:
        preamble.append("\\usepackage{graphicx}")
    if "\\begin{multicols}" in body_text:
        preamble.append("\\usepackage{multicol}")
    if re.search(r"\\begin\{enumerate\}\[label=", body_text):
        preamble.append("\\usepackage{enumitem}")
    if "\\endnote{" in body_text:
        preamble.append("\\usepackage{endnotes}")
    if "\\todo" in body_text:
        preamble.append("\\usepackage{todonotes}")
    if "\\genfrac" in body_text:
        preamble.append("\\usepackage{amsmath}")
    if "\\sfrac" in body_text:
        preamble.append("\\usepackage{xfrac}")
    if uses_highlight:
        preamble.append("\\usepackage{soul}")
    if uses_highlight and not body_text.isascii():
        preamble.append("\\makeatletter")
        preamble.append("\\def\\lTwoWHighlightColor{yellow}")
        preamble.append(
            "\\renewcommand{\\sethlcolor}[1]{\\def\\lTwoWHighlightColor{#1}}"
        )
        preamble.append(
            "\\renewcommand{\\hl}[1]{\\colorbox{\\lTwoWHighlightColor}{#1}}"
        )
        preamble.append("\\makeatother")


def build_preamble(body_text, title_text=None, author_text=None):
    """Return ``(preamble_lines, endnotes_tail)`` for native body text."""
    preamble = _base_preamble()
    if not body_text.isascii():
        preamble.append("% !TEX program = xelatex")
        preamble.append("\\usepackage{fontspec}")
        preamble.append("\\setmainfont{DejaVu Serif}")
        preamble.append("\\setmonofont{DejaVu Sans Mono}")
    _append_conditional_packages(preamble, body_text)
    if title_text:
        preamble.append(f"\\title{{{title_text}}}")
    if author_text:
        preamble.append(f"\\author{{{author_text}}}")
    preamble.append("\\begin{document}")
    if title_text:
        preamble.append("\\maketitle")
    tail = "\\theendnotes\n\n" if "\\endnote{" in body_text else ""
    return preamble, tail
