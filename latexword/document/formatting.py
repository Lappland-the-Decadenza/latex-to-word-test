"""Carried semantic formatting values.

Only author-chosen formatting belongs here. Template definitions and arbitrary
OOXML paragraph properties stay in the document adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class RunFormat:
    style_id: str | None = None
    bold: bool = False
    italic: bool = False
    underline: str | None = None
    strikethrough: bool = False
    highlight: str | None = None
    color: str | None = None
    shading: str | None = None
    small_caps: bool = False
    monospace: bool = False
    superscript: bool = False
    subscript: bool = False


@dataclass(frozen=True)
class ParagraphFormat:
    alignment: Literal["left", "center", "right", "justify"] | None = None
    heading_level: int | None = None
    list_level: int | None = None
    list_numfmt: str | None = None
    page_break_before: bool = False


__all__ = ["ParagraphFormat", "RunFormat"]
