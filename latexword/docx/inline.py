"""Inline LaTeX rendering for the DOCX document layer.

The module owns prose scanning and the inline Word constructs that require
package parts (links, fields, notes, comments and bookmarks).  Math and image
insertion are injected callbacks so this implementation stays independent of
the public ``write`` facade and can be tested in isolation.
"""

import os
import re

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.opc.constants import CONTENT_TYPE, RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import XmlPart
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.shared import RGBColor
from docx.text.paragraph import Paragraph
from lxml import etree

from .styles import (
    HIGHLIGHT_NAME_TO_WD,
    SCRIPT_CMDS,
    STYLE_CMDS,
    _apply_shading,
    _ensure_hyperlink_style,
    _ensure_character_style,
    _resolve_color,
    _set_character_style,
)

OMML_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

TEXT_REPLACEMENTS = [
    (r"(?:\\ldots|\\dots|\\cdots)(?:\{\})?", "…"),
    (r"\\LaTeX(?:\{\})?", "LaTeX"),
    (r"\\TeX(?:\{\})?", "TeX"),
    (r"---", "—"),
    (r"--", "–"),
    (r"``", "“"),
    (r"''", "”"),
]

LITERAL_CMDS = {
    "textbackslash": "\\",
    "textasciitilde": "~",
    "textasciicircum": "^",
    "textquotesingle": "'",
}
ESCAPES = {
    r"\%": "%", r"\&": "&", r"\_": "_", r"\$": "$", r"\#": "#",
    r"\{": "{", r"\}": "}", r"\ ": " ", r"\,": " ", r"\;": " ",
}
TRANSPARENT_CMDS = {"mbox", "text", "textrm", "textnormal", "mathrm"}
DROPPED_CMDS = {"index", "vspace", "hspace", "nonumber", "notag", "centering"}
DROPPED_CMDS_2ARG = {
    "setlength", "addtolength", "renewcommand", "newcommand", "providecommand"
}


def _find_brace(s, start):
    """Return ``(content, index_after)`` for a braced group."""
    if start >= len(s) or s[start] != "{":
        return None, start
    depth = 0
    for i in range(start, len(s)):
        escaped = False
        if i:
            backslashes = 0
            j = i - 1
            while j >= 0 and s[j] == "\\":
                backslashes += 1
                j -= 1
            escaped = backslashes % 2 == 1
        if s[i] == "{" and not escaped:
            depth += 1
        elif s[i] == "}" and not escaped:
            depth -= 1
            if depth == 0:
                return s[start + 1:i], i + 1
    return s[start + 1:], len(s)


def _find_bracket(s, start):
    """Return ``(content, index_after)`` for a simple optional argument."""
    if start >= len(s) or s[start] != "[":
        return None, start
    end = s.find("]", start)
    if end == -1:
        return s[start + 1:], len(s)
    return s[start + 1:end], end + 1


def _add_hyperlink(paragraph, url, text, styles, warnings, img_base=None,
                   math_renderer=None, image_adder=None):
    """Emit a real external ``w:hyperlink`` relationship."""
    has_style = _ensure_hyperlink_style(paragraph.part.document)
    hyperlink = OxmlElement("w:hyperlink")
    if url.startswith("#"):
        hyperlink.set(qn("w:anchor"), url[1:])
    else:
        r_id = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
        hyperlink.set(qn("r:id"), r_id)
    if has_style:
        styles = dict(styles or {})
        styles.setdefault("hyperlink", True)
    else:
        styles = dict(styles or {})
        styles.setdefault("hyperlink", False)
    # A Paragraph wrapper over the hyperlink element lets the normal inline
    # scanner compose direct formatting and character styles without making
    # relationship-backed links a special, lossy rendering path.
    proxy = Paragraph(hyperlink, paragraph._parent)
    add_inline_latex(
        proxy, text, styles, warnings, img_base,
        math_renderer=math_renderer, image_adder=image_adder,
    )
    paragraph._element.append(hyperlink)


class _NotesPart(XmlPart):
    """Live footnotes/endnotes part; python-docx has no notes API."""

    def __init__(self, partname, content_type, package, kind):
        self.kind = kind
        self._ids = 0
        root = etree.Element(
            qn("w:" + ("footnotes" if kind == "footnote" else "endnotes")),
            nsmap={"w": W_NS, "r": R_NS, "m": OMML_NS},
        )
        for wtype, wid in (("separator", "-1"), ("continuationSeparator", "0")):
            note = etree.SubElement(root, qn("w:" + kind))
            note.set(qn("w:type"), wtype)
            note.set(qn("w:id"), wid)
            p = etree.SubElement(note, qn("w:p"))
            r = etree.SubElement(p, qn("w:r"))
            etree.SubElement(r, qn("w:" + wtype))
        super().__init__(partname, content_type, root, package)

    @property
    def document(self):
        return self.package.main_document_part.document

    def get_style_id(self, style_or_name, wd_type):
        return self.package.main_document_part.get_style_id(style_or_name, wd_type)

    def add_note(self, body, styles, warnings, img_base, math_renderer, image_adder):
        self._ids += 1
        nid = str(self._ids)
        note = etree.SubElement(self._element, qn("w:" + self.kind))
        note.set(qn("w:id"), nid)
        p = parse_xml(f'<w:p xmlns:w="{W_NS}"/>')
        note.append(p)
        mark_r = etree.SubElement(p, qn("w:r"))
        mark_rpr = etree.SubElement(mark_r, qn("w:rPr"))
        va = etree.SubElement(mark_rpr, qn("w:vertAlign"))
        va.set(qn("w:val"), "superscript")
        etree.SubElement(mark_r, qn("w:" + self.kind + "Ref"))
        add_inline_latex(
            Paragraph(p, self), body, styles, warnings, img_base,
            math_renderer=math_renderer, image_adder=image_adder,
        )
        return nid


def _get_notes_part(paragraph, kind):
    doc_part = paragraph.part
    reltype = RT.FOOTNOTES if kind == "footnote" else RT.ENDNOTES
    try:
        return doc_part.rels.part_with_reltype(reltype)
    except KeyError:
        pass
    part = _NotesPart(
        PackURI("/word/%ss.xml" % kind),
        CONTENT_TYPE.WML_FOOTNOTES if kind == "footnote" else CONTENT_TYPE.WML_ENDNOTES,
        doc_part.package, kind,
    )
    doc_part.relate_to(part, reltype)
    return part


def _add_note(paragraph, body, kind, styles, warnings, img_base, math_renderer, image_adder):
    if isinstance(paragraph.part, _NotesPart):
        if warnings is not None:
            warnings.append(f"nested \\{kind} dropped (LaTeX forbids nested notes)")
        add_inline_latex(
            paragraph, body, styles, warnings, img_base,
            math_renderer=math_renderer, image_adder=image_adder,
        )
        return
    part = _get_notes_part(paragraph, kind)
    nid = part.add_note(body, styles, warnings, img_base, math_renderer, image_adder)
    r = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    va = OxmlElement("w:vertAlign")
    va.set(qn("w:val"), "superscript")
    rpr.append(va)
    r.append(rpr)
    ref = OxmlElement("w:" + kind + "Reference")
    ref.set(qn("w:id"), nid)
    r.append(ref)
    paragraph._element.append(r)


class _CommentsPart(XmlPart):
    """Live comments part; each comment receives a monotonically increasing id."""

    def __init__(self, partname, content_type, package):
        self._ids = 0
        root = etree.Element(qn("w:comments"), nsmap={"w": W_NS, "r": R_NS, "m": OMML_NS})
        super().__init__(partname, content_type, root, package)

    @property
    def document(self):
        return self.package.main_document_part.document

    def get_style_id(self, style_or_name, wd_type):
        return self.package.main_document_part.get_style_id(style_or_name, wd_type)

    def add_comment(self, author, date, body, styles, warnings, img_base, math_renderer, image_adder):
        self._ids += 1
        cid = str(self._ids)
        comment = etree.SubElement(self._element, qn("w:comment"))
        comment.set(qn("w:id"), cid)
        comment.set(qn("w:author"), author)
        comment.set(qn("w:date"), date)
        comment.set(qn("w:initials"), "")
        p = parse_xml(f'<w:p xmlns:w="{W_NS}"/>')
        comment.append(p)
        add_inline_latex(
            Paragraph(p, self), body, styles, warnings, img_base,
            math_renderer=math_renderer, image_adder=image_adder,
        )
        return cid


def _get_comments_part(paragraph):
    doc_part = paragraph.part
    try:
        return doc_part.rels.part_with_reltype(RT.COMMENTS)
    except KeyError:
        pass
    part = _CommentsPart(PackURI("/word/comments.xml"), CONTENT_TYPE.WML_COMMENTS, doc_part.package)
    doc_part.relate_to(part, RT.COMMENTS)
    return part


def _add_comment(paragraph, author, date, body, styles, warnings, img_base, math_renderer, image_adder):
    part = _get_comments_part(paragraph)
    cid = part.add_comment(author, date, body, styles, warnings, img_base, math_renderer, image_adder)
    start = OxmlElement("w:commentRangeStart")
    start.set(qn("w:id"), cid)
    paragraph._element.append(start)
    end = OxmlElement("w:commentRangeEnd")
    end.set(qn("w:id"), cid)
    paragraph._element.append(end)
    ref = OxmlElement("w:commentReference")
    ref.set(qn("w:id"), cid)
    r = OxmlElement("w:r")
    r.append(ref)
    paragraph._element.append(r)


_bookmark_ids = 0


def _add_bookmark(paragraph, name, warnings):
    global _bookmark_ids
    if not name:
        return
    if re.search(r"[}\%#&$^~\s]", name):
        if warnings is not None:
            warnings.append(
                f"bookmark name {name!r} cannot be referenced from LaTeX; dropped"
            )
        return
    _bookmark_ids += 1
    nid = str(_bookmark_ids)
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), nid)
    start.set(qn("w:name"), name)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), nid)
    paragraph._element.append(start)
    paragraph._element.append(end)


def _add_field(paragraph, kind, name):
    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {kind} {name} \\h \\* MERGEFORMAT "
    run._element.append(fld_begin)
    run._element.append(instr)
    run2 = paragraph.add_run()
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    fld_text = OxmlElement("w:t")
    fld_text.text = "?"
    run2._element.append(fld_sep)
    run2._element.append(fld_text)
    run3 = paragraph.add_run()
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run3._element.append(fld_end)


def strip_comments(text):
    out = []
    for line in text.split("\n"):
        i = 0
        while True:
            i = line.find("%", i)
            if i == -1:
                break
            if i > 0 and line[i - 1] == "\\":
                i += 1
                continue
            line = line[:i]
            break
        out.append(line)
    return "\n".join(out)


_INLINE_MATH = re.compile(r"\$(?!\$)(.+?)(?<!\\)\$|\\\((.+?)\\\)", re.DOTALL)
_HREF_URL_RE = re.compile(r"\\href\{[^{}]*\}")


def _apply_text_replacements(text):
    for pattern, repl in TEXT_REPLACEMENTS:
        text = re.sub(pattern, lambda _m, r=repl: r, text)
    return text


def _apply_text_replacements_outside_math(text):
    protected = []
    for match in _INLINE_MATH.finditer(text):
        protected.append((match.start(), match.end()))
    for match in _HREF_URL_RE.finditer(text):
        protected.append((match.start(), match.end()))
    if not protected:
        return _apply_text_replacements(text)
    protected.sort()
    out = []
    pos = 0
    for start, end in protected:
        if start < pos:
            continue
        out.append(_apply_text_replacements(text[pos:start]))
        out.append(text[start:end])
        pos = end
    out.append(_apply_text_replacements(text[pos:]))
    return "".join(out)


def add_inline_latex(
    paragraph, text, styles=None, warnings=None, img_base=None,
    *, math_renderer=None, image_adder=None,
):
    """Append LaTeX inline content using the injected document callbacks."""
    from .inline_renderer import InlineRenderer

    return InlineRenderer(
        paragraph, text, styles, warnings, img_base, math_renderer, image_adder,
    ).render()


def parse_image_args(text, pos):
    """Parse an image command's optional arguments without owning image IO."""
    opts, pos = _find_bracket(text, pos)
    path, pos = _find_brace(text, pos)
    return opts, path, None, pos
