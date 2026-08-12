"""OOXML notes, comments, anchors, and field boundaries.

This module owns reverse-side rules for Word features attached to paragraphs
but defined in separate package parts. Paragraph traversal stays in ``read``;
it supplies the ordinary paragraph renderer for note and comment bodies.
"""

import hashlib
import re

from lxml import etree

from ..document.text import href_escape as _href_escape, prose_escape as _prose_escape
from ..document.identity import NodeId
from ..math.omml2latex import qw


INTERNAL_BOOKMARK = re.compile(
    r"^(?:_(?:GoBack|Toc\d+|Hlk\d+)|X[0-9a-f]{20,})$"
)
FIELD_INSTR = re.compile(r"^\s*(REF|PAGEREF|HYPERLINK|SEQ)\b\s*(.*)$", re.S)


def note_to_latex(ref_el, kind, warnings, index, notes_ctx, img_ctx,
                  render_paragraph):
    """Render one footnote/endnote reference and its detached definition."""
    nid = ref_el.get(qw("id"))
    part = "word/footnotes.xml" if kind == "footnote" else "word/endnotes.xml"
    entry = (notes_ctx or {}).get(part)
    paras = entry[0].get(nid) if entry else None
    if not paras:
        warnings.append(f"{kind} reference id={nid} has no definition, dropped")
        return ""
    rels = entry[1] if entry else {}
    rendered = [
        render_paragraph(p, warnings, rels, index, img_ctx, notes_ctx)
        for p in paras
    ]
    if len(paras) > 1:
        warnings.append(
            f"{kind} id={nid} has {len(paras)} paragraphs; the paragraph "
            "breaks are dropped (L* \\footnote holds one paragraph)"
        )
    return f"\\{kind}{{{' '.join(r for r in rendered if r)}}}"


def comment_to_latex(ref_el, warnings, index, comments_ctx, img_ctx,
                     render_paragraph, object_store=None):
    """Render one comment reference and its detached definition."""
    cid = ref_el.get(qw("id"))
    defs, rels = comments_ctx or ({}, {})
    entry = defs.get(cid)
    if not entry:
        warnings.append(f"comment reference id={cid} has no definition, dropped")
        return ""
    author, date, parent, paras = entry
    rendered = [
        render_paragraph(p, warnings, rels, index, img_ctx, comments_ctx)
        for p in paras
    ]
    if len(paras) > 1:
        warnings.append(
            f"comment id={cid} has {len(paras)} paragraphs; the paragraph "
            "breaks are dropped (the native note form holds one paragraph)"
        )
    if parent is not None:
        warnings.append(
            f"comment id={cid} is a reply to id={parent}; reply threading "
            "is not carried by native LaTeX"
        )
    body = " ".join(r for r in rendered if r)
    if object_store is not None:
        object_store.attach(
            "comment-metadata",
            {"author": author, "date": date, "parent": parent},
            owner_id=NodeId.allocate(max(0, index)),
            owner_semantic_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
            position="inside",
            ordinal=index,
            content_type="application/json",
        )
    return f"\\todo[inline]{{{body}}}"


def resolve_field(
    instr, cached, warnings, index, cached_latex=False, object_store=None
):
    """Return canonical LaTeX for a completed Word field."""
    match = FIELD_INSTR.match(instr or "")
    if not match:
        warnings.append(
            f"field instruction at paragraph {index} has no native LaTeX form; "
            "cached result kept"
        )
        _capture_field(
            instr, cached, index, cached_latex, object_store
        )
        return wordfield_latex(instr, cached, cached_latex)
    kind, rest = match.group(1), match.group(2)
    if kind in ("REF", "PAGEREF"):
        words = rest.split()
        if words:
            return f"\\{kind.lower()}{{{words[0]}}}"
    if kind == "HYPERLINK":
        url_match = re.match(r'"((?:[^"]|"")*)"', rest.strip(), re.S)
        if url_match:
            url = url_match.group(1).replace('""', '"')
            body = "".join(cached) if cached_latex else _prose_escape(
                "".join(cached)
            )
            return f"\\href{{{_href_escape(url)}}}{{{body}}}"
    warnings.append(
        f"field {kind!r} at paragraph {index} has no native LaTeX form; "
        "cached result kept"
    )
    return _capture_field(instr, cached, index, cached_latex, object_store)


def _capture_field(instr, cached, index, cached_latex, object_store):
    """Detach an unrepresentable field instruction from native LaTeX."""
    if object_store is not None:
        body = "".join(cached) if cached_latex else _prose_escape("".join(cached))
        object_store.attach(
            "field-instruction",
            {"instruction": instr or "", "display": body},
            owner_id=NodeId.allocate(max(0, index)),
            owner_semantic_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
            position="inside",
            ordinal=index,
            content_type="application/json",
        )
    return wordfield_latex(instr, cached, cached_latex)


def wordfield_latex(instr, cached, cached_latex=False):
    """Keep an unknown field's cached result as ordinary visible text."""
    display = "".join(cached) if cached_latex else _prose_escape("".join(cached))
    return display


def read_notes(z):
    """Read real footnote/endnote definitions from package parts."""
    out = {}
    for part in ("word/footnotes.xml", "word/endnotes.xml"):
        if part not in z.namelist():
            continue
        root = etree.fromstring(z.read(part))
        tag = "footnote" if "footnotes" in part else "endnote"
        defs = {}
        for element in root.iter(qw(tag)):
            if element.get(qw("type")):
                continue
            nid = element.get(qw("id"))
            if nid is not None:
                defs[nid] = element.findall(qw("p"))
        if defs:
            out[part] = defs
    return out


def read_comments(z):
    """Read comment definitions, retaining reply-parent identity."""
    if "word/comments.xml" not in z.namelist():
        return {}
    root = etree.fromstring(z.read("word/comments.xml"))
    out = {}
    for element in root.iter(qw("comment")):
        cid = element.get(qw("id"))
        if cid is not None:
            out[cid] = (
                element.get(qw("author")) or "",
                element.get(qw("date")) or "",
                element.get(qw("parent")),
                element.findall(qw("p")),
            )
    return out
