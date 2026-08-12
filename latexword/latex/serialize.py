"""Canonical native-LaTeX serializer for the semantic document model."""

from __future__ import annotations

from dataclasses import dataclass

from ..document.model import (
    Bookmark, BlockNode, Cell, Comment, Document, Endnote, Field, Footnote,
    Hyperlink, ImageBlock, ImageInline, LineBreak, ListBlock, ListItem, Math,
    OpaqueBlock, OpaqueInline, Paragraph, Quote, Row, SectionBreak, Table,
    Text, Todo,
)
from ..document.text import href_escape, prose_escape


@dataclass(frozen=True, slots=True)
class NodeSpan:
    kind: str
    start: int
    end: int
    # Kept as an in-memory capability for workspace map construction.  It is
    # never serialized into LaTeX or persisted in shadow.map.json.
    node: object | None = None


@dataclass(frozen=True, slots=True)
class SerializedDocument:
    text: str
    spans: tuple[NodeSpan, ...]


def _brace(value):
    return "{" + value + "}"


def _format(value, format_):
    if format_.bold:
        value = r"\textbf{" + value + "}"
    if format_.italic:
        value = r"\textit{" + value + "}"
    if format_.monospace:
        value = r"\texttt{" + value + "}"
    if format_.small_caps:
        value = r"\textsc{" + value + "}"
    if format_.underline:
        value = r"\underline{" + value + "}"
    if format_.strikethrough:
        value = r"\sout{" + value + "}"
    if format_.superscript:
        value = r"\textsuperscript{" + value + "}"
    if format_.subscript:
        value = r"\textsubscript{" + value + "}"
    if format_.shading:
        value = r"\colorbox[HTML]{" + format_.shading + "}{" + value + "}"
    if format_.highlight:
        if format_.highlight.lower() == "yellow":
            value = r"\hl{" + value + "}"
        else:
            value = (
                r"{\sethlcolor{" + format_.highlight + r"}\hl{" + value + "}}"
            )
    if format_.color:
        value = r"\textcolor[HTML]{" + format_.color + "}{" + value + "}"
    return value


class _Writer:
    def __init__(self):
        self.parts = []
        self.spans = []
        self.anchor_ordinal = 0

    @property
    def text(self):
        return "".join(self.parts)

    def write(self, value):
        self.parts.append(value)

    def mark(self, node, emit):
        start = len(self.text.encode("utf-8"))
        emit()
        end = len(self.text.encode("utf-8"))
        if end > start:
            self.spans.append(NodeSpan(type(node).__name__, start, end, node))

    def anchor(self):
        """Emit the generation-local marker immediately before one block."""
        self.anchor_ordinal += 1
        self.write(f"%lw{self.anchor_ordinal}\n")


def _inline(writer, node):
    if isinstance(node, Text):
        def emit_text():
            value = _format(prose_escape(node.value), node.format)
            wrapped = node.value and (node.value[0].isspace() or node.value[-1].isspace())
            writer.write("{" + value + "}" if wrapped else value)
        writer.mark(node, emit_text)
    elif isinstance(node, Math):
        def emit_math():
            writer.write(r"\[" + node.latex + r"\]" if node.display else "$" + node.latex + "$")
        writer.mark(node, emit_math)
    elif isinstance(node, LineBreak):
        writer.mark(node, lambda: writer.write(r"\\" if node.hard else r"\linebreak{}"))
    elif isinstance(node, Hyperlink):
        def emit_link():
            writer.write(r"\href{" + href_escape(node.target) + "}{")
            for child in node.children:
                _inline(writer, child)
            writer.write("}")
        writer.mark(node, emit_link)
    elif isinstance(node, Field):
        def emit_field():
            kind = (node.spec.kind or "").upper()
            if kind in {"REF", "PAGEREF"}:
                writer.write("\\" + kind.lower() + _brace(node.spec.instruction))
            elif kind == "CITE":
                writer.write(r"\cite{" + node.spec.instruction + "}")
            else:
                for child in node.display:
                    _inline(writer, child)
        writer.mark(node, emit_field)
    elif isinstance(node, Bookmark):
        def emit_bookmark():
            writer.write(r"\label{" + href_escape(node.name) + "}")
            for child in node.children:
                _inline(writer, child)
        writer.mark(node, emit_bookmark)
    elif isinstance(node, Footnote):
        def emit_note():
            writer.write(r"\footnote{")
            _blocks(writer, node.blocks, separator=" ")
            writer.write("}")
        writer.mark(node, emit_note)
    elif isinstance(node, (Endnote, Comment)):
        # These Word identities remain sidecar-only; their visible note body
        # still has a native projection when a caller explicitly serializes it.
        def emit_note_body():
            writer.write(r"\footnote{")
            _blocks(writer, node.blocks, separator=" ")
            writer.write("}")
        writer.mark(node, emit_note_body)
    elif isinstance(node, Todo):
        def emit_todo():
            options = []
            if node.inline:
                options.append("inline")
            if node.color:
                options.append("color=" + node.color)
            writer.write(r"\todo" + ("[" + ",".join(options) + "]" if options else "") + "{")
            for child in node.children:
                _inline(writer, child)
            writer.write("}")
        writer.mark(node, emit_todo)
    elif isinstance(node, ImageInline):
        path = node.spec.source_path or ""
        writer.mark(node, lambda: writer.write(
            r"\includegraphics{" + prose_escape(path) + "}" if path else ""
        ))
    elif isinstance(node, OpaqueInline):
        return
    elif hasattr(node, "children"):
        for child in node.children:
            _inline(writer, child)


def _paragraph(writer, node):
    if not node.inlines:
        alignment = node.format.alignment
        if alignment in {"center", "left", "right", "justify"}:
            env = {"center": "center", "left": "flushleft", "right": "flushright", "justify": "justify"}[alignment]
            writer.write(f"\\begin{{{env}}}" + r"\mbox{}\par" + f"\\end{{{env}}}")
            return
        writer.write(r"\mbox{}\par")
        return
    if len(node.inlines) == 1 and isinstance(node.inlines[0], Math) and node.inlines[0].display:
        environment = {"center": "center", "left": "flushleft", "right": "flushright", "justify": "justify"}.get(node.format.alignment)
        if environment:
            writer.write(f"\\begin{{{environment}}}")
        writer.write(r"\begin{equation*}")
        writer.mark(node.inlines[0], lambda: writer.write(node.inlines[0].latex))
        writer.write(r"\end{equation*}")
        if environment:
            writer.write(f"\\end{{{environment}}}")
        return
    level = node.format.heading_level
    if level is not None:
        command = {1: "section", 2: "subsection", 3: "subsubsection"}.get(level, "paragraph")
        writer.write("\\" + command + "{")
        for child in node.inlines:
            _inline(writer, child)
        writer.write("}")
        return
    alignment = node.format.alignment
    if alignment in {"center", "left", "right", "justify"}:
        env = {"center": "center", "left": "flushleft", "right": "flushright", "justify": "justify"}[alignment]
        writer.write(f"\\begin{{{env}}}")
        for child in node.inlines:
            _inline(writer, child)
        writer.write(f"\\end{{{env}}}")
        return
    for child in node.inlines:
        _inline(writer, child)


def _cell_body(writer, cell):
    if cell.shading:
        writer.write(r"\cellcolor{" + cell.shading + "}")
    if cell.row_span > 1:
        writer.write(r"\multirow{" + str(cell.row_span) + r"}{*}{")
    if cell.col_span > 1:
        writer.write(r"\multicolumn{" + str(cell.col_span) + r"}{l}{")
    if cell.blocks:
        _blocks(writer, cell.blocks, separator=" ")
    else:
        writer.write(r"\mbox{}")
    if cell.col_span > 1:
        writer.write("}")
    if cell.row_span > 1:
        writer.write("}")


def _block(writer, node):
    if isinstance(node, Paragraph):
        writer.mark(node, lambda: _paragraph(writer, node))
    elif isinstance(node, ListBlock):
        def emit_list():
            env = "description" if node.description else ("enumerate" if node.ordered else "itemize")
            options = []
            if node.label:
                options.append("label=" + node.label)
            if node.start is not None:
                options.append("start=" + str(node.start))
            suffix = "[" + ",".join(options) + "]" if options else ""
            writer.write(f"\\begin{{{env}}}{suffix}\n")
            for index, item in enumerate(node.items):
                if index:
                    writer.write("\n")
                _block(writer, item)
            writer.write(f"\n\\end{{{env}}}")
        writer.mark(node, emit_list)
    elif isinstance(node, ListItem):
        def emit_item():
            writer.write(r"\item")
            if node.label:
                writer.write("[")
                for child in node.label:
                    _inline(writer, child)
                writer.write("]")
            writer.write(" ")
            _blocks(writer, node.blocks, separator="\n\n")
        writer.mark(node, emit_item)
    elif isinstance(node, Quote):
        def emit_quote():
            writer.write(f"\\begin{{{node.environment}}}\n")
            _blocks(writer, node.blocks, separator="\n\n")
            writer.write(f"\n\\end{{{node.environment}}}")
        writer.mark(node, emit_quote)
    elif isinstance(node, Table):
        def emit_table():
            count = max((len(row.cells) for row in node.rows), default=1)
            writer.write(r"\begin{tabular}{" + "l" * count + "}" + "\n")
            if "top" in node.borders:
                writer.write(r"\hline" + "\n")
            for index, row in enumerate(node.rows):
                if index:
                    if "inside" in node.borders:
                        writer.write(r"\hline" + "\n")
                    writer.write("\n")
                writer.anchor()
                writer.mark(row, lambda row=row: _row(writer, row))
            if "bottom" in node.borders:
                writer.write("\n" + r"\hline")
            writer.write("\n" + r"\end{tabular}")
        writer.mark(node, emit_table)
    elif isinstance(node, ImageBlock):
        def emit_image():
            path = node.spec.source_path or ""
            writer.write(r"\begin{figure}")
            writer.write(r"\includegraphics{" + prose_escape(path) + "}" if path else "")
            if node.caption:
                writer.write(r"\caption{")
                for child in node.caption:
                    _inline(writer, child)
                writer.write("}")
            writer.write(r"\end{figure}")
        writer.mark(node, emit_image)
    elif isinstance(node, SectionBreak):
        writer.mark(node, lambda: writer.write(r"\newpage"))
    elif isinstance(node, OpaqueBlock):
        return


def _blocks(writer, nodes, separator="\n\n"):
    for index, node in enumerate(nodes):
        if index:
            writer.write(separator)
        writer.anchor()
        _block(writer, node)


def _row(writer, row):
    for index, cell in enumerate(row.cells):
        if index:
            writer.write(" & ")
        writer.mark(cell, lambda cell=cell: _cell_body(writer, cell))
    writer.write(r" \\")


def serialize_with_spans(document: Document) -> SerializedDocument:
    """Serialize using UTF-8 byte offsets and report every emitted node."""
    writer = _Writer()
    start = len(writer.text.encode("utf-8"))
    for index, node in enumerate(document.children):
        if index:
            writer.write("\n\n")
        writer.anchor()
        _block(writer, node)
    end = len(writer.text.encode("utf-8"))
    if end > start:
        writer.spans.append(NodeSpan("Document", start, end, document))
    return SerializedDocument(writer.text, tuple(writer.spans))


def serialize(document: Document) -> str:
    """Serialize a document to clean, package-native LaTeX body syntax."""
    return serialize_with_spans(document).text


__all__ = ["NodeSpan", "SerializedDocument", "serialize", "serialize_with_spans"]
