"""Typed, format-policy-neutral document nodes.

The model carries authored structure and the closed formatting set from
``PLAN.md``. Template definitions, arbitrary paragraph properties, and other
deferred layout decisions deliberately have no fields here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from .diagnostics import SourceReference
from .formatting import ParagraphFormat, RunFormat


SourceContext = SourceReference


@dataclass(frozen=True)
class StyleRef:
    style_id: str


@dataclass(frozen=True)
class ImageSpec:
    data: bytes | None = None
    extension: str | None = None
    content_type: str | None = None
    cx: int | None = None
    cy: int | None = None
    inline: bool = True
    wrap: str | None = None
    position: tuple[int, ...] = ()
    alt_text: str | None = None
    title: str | None = None
    src_rect: tuple[int, int, int, int] | None = None
    rotation: int = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False
    relationship: str | None = None
    source_path: str | None = None


@dataclass(frozen=True)
class FieldSpec:
    instruction: str
    kind: str | None = None


@dataclass(frozen=True)
class Text:
    value: str
    format: RunFormat = RunFormat()
    context: SourceContext | None = None


@dataclass(frozen=True)
class Math:
    latex: str
    display: bool = False
    context: SourceContext | None = None


@dataclass(frozen=True)
class LineBreak:
    hard: bool = False


@dataclass(frozen=True)
class Hyperlink:
    target: str
    children: tuple[InlineNode, ...]
    anchor: str | None = None
    tooltip: str | None = None


@dataclass(frozen=True)
class Field:
    spec: FieldSpec
    display: tuple[InlineNode, ...] = ()


@dataclass(frozen=True)
class Footnote:
    blocks: tuple[BlockNode, ...]


@dataclass(frozen=True)
class Endnote:
    blocks: tuple[BlockNode, ...]


@dataclass(frozen=True)
class Comment:
    author: str
    date: str
    blocks: tuple[BlockNode, ...]


@dataclass(frozen=True)
class Todo:
    children: tuple[InlineNode, ...]
    inline: bool = False
    color: str | None = None


@dataclass(frozen=True)
class Bookmark:
    name: str
    children: tuple[InlineNode, ...] = ()


@dataclass(frozen=True)
class StyledInline:
    style: StyleRef
    children: tuple[InlineNode, ...]


@dataclass(frozen=True)
class ImageInline:
    spec: ImageSpec


@dataclass(frozen=True)
class OpaqueInline:
    """An inline object with no model representation yet."""

    payload: object
    context: SourceContext | None = None


@dataclass(frozen=True)
class Paragraph:
    inlines: tuple[InlineNode, ...]
    style: StyleRef | None = None
    format: ParagraphFormat = ParagraphFormat()
    context: SourceContext | None = None


@dataclass(frozen=True)
class ListItem:
    blocks: tuple[BlockNode, ...]
    style: StyleRef | None = None
    level: int = 0
    numfmt: str = "bullet"
    label: tuple[InlineNode, ...] = ()


@dataclass(frozen=True)
class ListBlock:
    items: tuple[ListItem, ...]
    ordered: bool = False
    description: bool = False
    label: str | None = None
    start: int | None = None


@dataclass(frozen=True)
class Quote:
    blocks: tuple[BlockNode, ...]
    environment: str = "quote"


@dataclass(frozen=True)
class Cell:
    blocks: tuple[BlockNode, ...]
    row_span: int = 1
    col_span: int = 1
    shading: str | None = None


@dataclass(frozen=True)
class Row:
    cells: tuple[Cell, ...]


@dataclass(frozen=True)
class Table:
    rows: tuple[Row, ...]
    style: StyleRef | None = None
    borders: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImageBlock:
    spec: ImageSpec
    caption: tuple[InlineNode, ...] = ()


@dataclass(frozen=True)
class SectionBreak:
    section_type: str = "continuous"
    columns: int = 1


@dataclass(frozen=True)
class OpaqueBlock:
    """A block object retained for a later explicit reconstruction path."""

    payload: object
    context: SourceContext | None = None


InlineNode: TypeAlias = (
    Text
    | Math
    | LineBreak
    | Hyperlink
    | Field
    | Footnote
    | Endnote
    | Comment
    | Todo
    | Bookmark
    | StyledInline
    | ImageInline
    | OpaqueInline
)

BlockNode: TypeAlias = (
    Paragraph
    | ListBlock
    | ListItem
    | Quote
    | Table
    | Row
    | Cell
    | ImageBlock
    | SectionBreak
    | OpaqueBlock
)


@dataclass(frozen=True)
class Document:
    """A format-neutral document root owned by the semantic layer."""

    children: tuple[BlockNode, ...] = ()


def paragraph_from_text(
    text: str,
    *,
    style_id: str | None = None,
    alignment: Literal["left", "center", "right", "justify"] | None = None,
) -> Paragraph:
    """Build the first migrated seam without interpreting inline markup."""

    return Paragraph(
        inlines=(Text(text),),
        style=StyleRef(style_id) if style_id else None,
        format=ParagraphFormat(alignment=alignment),
    )


def paragraph_text(paragraph: Paragraph) -> str:
    """Return the text payload for the plain-text paragraph adapter."""

    return "".join(node.value for node in paragraph.inlines if isinstance(node, Text))
