"""Focused checks for the first typed document-model seam."""

from dataclasses import FrozenInstanceError

import pytest

from latexword.document.model import Paragraph, StyleRef, paragraph_from_text, paragraph_text
from latexword.document.formatting import ParagraphFormat, RunFormat
from latexword.document.identity import NodeId


def test_plain_paragraph_model_preserves_text_and_style_reference():
    node = paragraph_from_text("  body  ", style_id="BodyStyle")

    assert isinstance(node, Paragraph)
    assert node.style == StyleRef("BodyStyle")
    assert paragraph_text(node) == "  body  "
    with pytest.raises(FrozenInstanceError):
        node.style = None


def test_semantic_core_owns_formatting_and_stable_identity():
    assert Paragraph(inlines=(), format=ParagraphFormat())
    assert RunFormat(bold=True).bold
    assert NodeId.allocate(3).value == "n00000003"
