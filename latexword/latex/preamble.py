"""Package and document-envelope generation for native LaTeX."""

from __future__ import annotations

from ..document.model import (
    Cell, Document, Hyperlink, ImageBlock, ImageInline, ListBlock, Math, Paragraph, Todo, Text,
)
from .profile import PACKAGE_WHITELIST
from .serialize import serialize


def _walk(value):
    if isinstance(value, (tuple, list)):
        for child in value:
            yield from _walk(child)
    elif hasattr(value, "__dataclass_fields__"):
        yield value
        for name in value.__dataclass_fields__:
            yield from _walk(getattr(value, name))


def required_packages(document: Document) -> tuple[str, ...]:
    """Return the closed package set required by represented nodes."""
    packages = set()
    for node in _walk(document):
        if isinstance(node, Math):
            packages.update({"amsmath", "amssymb"})
        elif isinstance(node, (ImageBlock, ImageInline)):
            packages.add("graphicx")
        elif isinstance(node, ListBlock):
            packages.add("enumitem")
        elif isinstance(node, Paragraph) and node.format.alignment == "justify":
            packages.add("ragged2e")
        elif isinstance(node, Hyperlink):
            packages.add("hyperref")
        elif isinstance(node, Todo):
            packages.add("todonotes")
        elif isinstance(node, Cell):
            if node.shading:
                packages.add("xcolor")
            if node.row_span > 1:
                packages.add("multirow")
        elif isinstance(node, Text):
            if node.format.highlight:
                packages.add("soul")
            if node.format.color or node.format.shading:
                packages.add("xcolor")
            if node.format.strikethrough:
                packages.add("ulem")
    return tuple(sorted(packages & PACKAGE_WHITELIST))


def build_preamble(document: Document, *, title=None, author=None, date=None):
    """Build the native document envelope without Word-specific definitions."""
    lines = [r"\documentclass{article}"]
    for package in required_packages(document):
        lines.append(r"\usepackage{" + package + "}")
    if title:
        lines.append(r"\title{" + title + "}")
    if author:
        lines.append(r"\author{" + author + "}")
    if date:
        lines.append(r"\date{" + date + "}")
    lines.extend([r"\begin{document}"])
    if title or author or date:
        lines.append(r"\maketitle")
    return lines


def serialize_document(document: Document, **metadata) -> str:
    """Return one clean, standalone native LaTeX document."""
    return "\n".join(build_preamble(document, **metadata)) + "\n\n" + serialize(document) + "\n\n\\end{document}\n"


__all__ = ["build_preamble", "required_packages", "serialize_document"]
