"""Style identity, authored character formatting, and list numbering.

This module is intentionally independent of the document facades.  It owns
style IDs and the closed carried formatting set, while template definitions
remain package-level data supplied by ``package.py``.
"""

import re
from dataclasses import dataclass
from enum import Enum

import docx
import docx.enum.style
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import RGBColor


class SemanticRole(str, Enum):
    BODY = "body"
    HEADING = "heading"
    LIST = "list"
    TABLE = "table"
    FIGURE = "figure"
    MATH = "math"
    QUOTE = "quote"


class StyleRole(str, Enum):
    TITLE = "title"
    AUTHOR = "author"
    CAPTION = "caption"
    BODY = "body"
    HEADING = "heading"
    LIST = "list"


@dataclass(frozen=True, slots=True)
class StyleIdentity:
    style_id: str
    role: SemanticRole = SemanticRole.BODY


def heading_level(style_id):
    """Return the semantic heading level encoded by a paragraph style ID."""
    if not style_id:
        return None
    if style_id == "Title":
        return 0
    normalized = re.sub(r"[^a-z0-9]", "", style_id.lower())
    if normalized.endswith("title"):
        return 0
    for suffix, level in (
        ("subsubsection", 3), ("subsection", 2), ("section", 1),
    ):
        if normalized.endswith(suffix):
            return level
    match = re.fullmatch(r"heading([1-9])", normalized)
    return int(match.group(1)) if match else None


STYLE_CMDS = {
    "textbf": "bold", "bf": "bold", "textit": "italic", "emph": "italic",
    "it": "italic", "texttt": "mono", "textsc": "smallcaps",
    "underline": "underline", "sout": "strike",
}
SCRIPT_CMDS = {"textsuperscript": "superscript", "textsubscript": "subscript"}

HIGHLIGHT_NAME_TO_WD = {
    "black": WD_COLOR_INDEX.BLACK, "blue": WD_COLOR_INDEX.BLUE,
    "cyan": WD_COLOR_INDEX.TURQUOISE, "darkblue": WD_COLOR_INDEX.DARK_BLUE,
    "darkcyan": WD_COLOR_INDEX.TEAL, "darkgray": WD_COLOR_INDEX.GRAY_50,
    "darkgreen": WD_COLOR_INDEX.GREEN, "darkmagenta": WD_COLOR_INDEX.VIOLET,
    "darkred": WD_COLOR_INDEX.DARK_RED, "darkyellow": WD_COLOR_INDEX.DARK_YELLOW,
    "green": WD_COLOR_INDEX.BRIGHT_GREEN, "lightgray": WD_COLOR_INDEX.GRAY_25,
    "magenta": WD_COLOR_INDEX.PINK, "red": WD_COLOR_INDEX.RED,
    "white": WD_COLOR_INDEX.WHITE, "yellow": WD_COLOR_INDEX.YELLOW,
}

HIGHLIGHT_NAME_TO_LATEX = {
    "black": "black", "blue": "blue", "cyan": "cyan",
    "darkblue": "blue", "darkcyan": "cyan", "darkgray": "darkgray",
    "darkgreen": "green", "darkmagenta": "magenta", "darkred": "red",
    "darkyellow": "olive", "green": "green", "lightgray": "lightgray",
    "magenta": "magenta", "red": "red", "white": "white",
    "yellow": "yellow",
}

NAMED_COLORS = {
    "red": "FF0000", "green": "00FF00", "blue": "0000FF", "cyan": "00FFFF",
    "magenta": "FF00FF", "yellow": "FFFF00", "black": "000000",
    "white": "FFFFFF", "gray": "808080", "darkgray": "A9A9A9",
    "lightgray": "D3D3D3", "brown": "BF8040", "lime": "BFFF00",
    "olive": "808000", "orange": "FF8000", "pink": "FFBFBF",
    "purple": "BF0040", "teal": "008080", "violet": "800080",
}

_HEX6_RE = re.compile(r"^[0-9A-Fa-f]{6}$")


def _resolve_color(value, model):
    """Resolve a colour argument to an RRGGBB value or ``None``."""
    if value is None:
        return None
    value = value.strip()
    if model is not None and model.strip().upper() == "HTML":
        return value.upper() if _HEX6_RE.match(value) else None
    if _HEX6_RE.match(value):
        return value.upper()
    return NAMED_COLORS.get(value.lower())


def _apply_shading(run, hexval):
    """Append authored run shading; python-docx has no Font API for it."""
    rPr = run._element.get_or_add_rPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hexval)
    rPr.append(shd)


def _ensure_hyperlink_style(doc):
    """Ensure the character style used by relationship-backed hyperlinks."""
    styles = doc.styles
    try:
        styles["Hyperlink"]
        return True
    except KeyError:
        pass
    if getattr(doc, "_latexword_reference_doc", False):
        return False
    style = styles.add_style("Hyperlink", docx.enum.style.WD_STYLE_TYPE.CHARACTER)
    style.font.color.rgb = RGBColor(0x05, 0x63, 0xC1)
    style.font.underline = True
    return True

def _ensure_named_style(doc, style_id, create=True):
    """Ensure a paragraph style ID exists, without copying its definition."""
    if doc.styles.element.get_by_id(style_id) is not None:
        return True
    if not create:
        return False
    doc.styles.add_style(style_id, docx.enum.style.WD_STYLE_TYPE.PARAGRAPH)
    return True


def _ensure_character_style(doc, style_id, create=True):
    """Ensure ``style_id`` names a character style in the target package."""
    if not style_id:
        return True
    # python-docx resolves by display name, while the XML helper below
    # resolves by raw styleId.  Template and built-in styles do not always
    # use the same value for both; Hyperlink commonly reaches this path after
    # its relationship helper has created it by name.
    try:
        style = doc.styles[style_id]
    except KeyError:
        style = None
    if style is not None:
        return style.type == docx.enum.style.WD_STYLE_TYPE.CHARACTER
    element = doc.styles.element.get_by_id(style_id)
    if element is not None:
        return element.get(qn("w:type")) in (None, "character")
    if not create:
        return False
    doc.styles.add_style(style_id, docx.enum.style.WD_STYLE_TYPE.CHARACTER)
    return True


def _set_character_style(run, style_id):
    """Set the raw ``w:rStyle`` ID without depending on a display name."""
    if not style_id:
        return
    rpr = run._element.get_or_add_rPr()
    rstyle = rpr.find(qn("w:rStyle"))
    if rstyle is None:
        rstyle = OxmlElement("w:rStyle")
        rpr.insert(0, rstyle)
    rstyle.set(qn("w:val"), style_id)


def _set_paragraph_style_id(paragraph, style_id):
    """Write a raw ``w:pStyle`` ID rather than looking up a display name."""
    paragraph._p.style = style_id


def _style_supplies_numbering(doc, style_id):
    """Whether a bound template style owns the paragraph's numbering."""
    seen = set()
    while style_id and style_id not in seen:
        seen.add(style_id)
        style = doc.styles.element.get_by_id(style_id)
        if style is None:
            return False
        num_id = style.find(qn("w:pPr") + "/" + qn("w:numPr") + "/" + qn("w:numId"))
        if num_id is not None:
            value = num_id.get(qn("w:val"))
            return value not in (None, "0")
        based_on = style.find(qn("w:basedOn"))
        style_id = based_on.get(qn("w:val")) if based_on is not None else None
    return False


def _ensure_table_style(doc, style_id, create=True):
    """Ensure a table style ID exists, without copying its definition."""
    if doc.styles.element.get_by_id(style_id) is not None:
        return True
    if not create:
        return False
    doc.styles.add_style(style_id, docx.enum.style.WD_STYLE_TYPE.TABLE)
    return True
