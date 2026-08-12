"""Closed semantic roles shared by native and OOXML document adapters."""

from __future__ import annotations

from enum import Enum


class CharacterRole(str, Enum):
    BODY = "body"
    LINK = "link"
    CODE = "code"
    NOTE = "note"


class ParagraphRole(str, Enum):
    BODY = "body"
    HEADING = "heading"
    CAPTION = "caption"
    QUOTE = "quote"


class ListRole(str, Enum):
    BULLET = "bullet"
    ORDERED = "ordered"
    DESCRIPTION = "description"


__all__ = ["CharacterRole", "ListRole", "ParagraphRole"]
