"""Convert a .docx back into a full, compilable LaTeX document.

This is the reverse of ``docx_write.py``: prose (bold/italic/underline runs,
headings, lists) is reconstructed by walking ``word/document.xml`` directly,
and each ``m:oMath``/``m:oMathPara`` zone is handed to ``omml2latex.to_latex``.

Several forward transforms are lossy by construction, so exact source
recovery is not possible in general; see the docstring of ``docx_to_latex``
for what specifically cannot round-trip.

Usage: python word2latex.py SOURCE.docx [OUTPUT.tex]
"""

import hashlib
import os
import re
import zipfile

from lxml import etree

from ..math.omml2latex import M, W, qm, qw, ln, to_latex
from ..document.text import href_escape as _href_escape, prose_escape as _prose_escape
from ..document.identity import NodeId
from ..document.model import Paragraph as ModelParagraph, StyleRef, Text
from .preamble import build_preamble
from .objects import (
    iter_skip_fallback as _iter_skip_fallback,
    object_kind as _object_kind_external,
    object_visible_text as _object_visible_text_external,
    opaque_latex as _opaque_latex_external,
    unsupported_object_warning,
)
from .notes import (
    INTERNAL_BOOKMARK as _INTERNAL_BOOKMARK,
    comment_to_latex as _comment_to_latex_external,
    note_to_latex as _note_to_latex_external,
    read_comments as _read_comments_external,
    read_notes as _read_notes_external,
    resolve_field as _resolve_field_external,
    wordfield_latex as _wordfield_latex_external,
)
from .table_read import table_to_latex as _table_to_latex
from .package import (
    read_document_relationships as _read_rels_external,
    read_media_relationships as _read_media_rels_external,
    read_part_relationships as _read_part_rels_external,
    relationship_target as _rel_target_external,
)
from .paragraphs import (
    run_breaks_to_latex as _run_breaks_latex,
    run_flag as _run_flag,
    plain_run_latex as _plain_run_external,
    paragraph_inline_latex as _paragraph_inline_external,
    run_prose_to_latex as _run_prose_to_latex,
    simple_alternate_content_latex as _simple_alt_external,
)
from .images import (
    ImageContext as _ImageContext,
    PICTURE_URI as _PICTURE_URI,
    drawing_to_latex as _drawing_to_latex_external,
    pict_to_latex as _pict_to_latex_external,
)
from .sections import column_layout as _column_layout_external
from .styles import heading_level as _heading_level_external
from .document_reader import (
    document_to_latex as _document_to_latex,
    document_to_latex_with_blocks as _document_to_latex_with_blocks,
)
from ..sidecar import ObjectStore
from .numbering import (
    build_nested_list as _build_nested_list_external,
    paragraph_list_info as _paragraph_list_info_external,
    read_numbering as _read_numbering_external,
    read_style_numbering as _read_style_numbering_external,
)


R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"

# The one graphicData/@uri MML2OMML-style drawings actually carry a raster
# image under -- anything else (a DrawingML shape, a chart, ...) has no blip
# to extract and is not an image at all, just something that happens to look
# like one in the object census.
_ACTIVE_OBJECT_STORE = None

def qr(name):
    return f"{{{R_NS}}}{name}"


def qa(name):
    return f"{{{A_NS}}}{name}"


def _rel_target(rels, rid):
    return _rel_target_external(rels, rid)


def _read_media_rels(z):
    """``r:id -> "media/imageN.ext"`` for every *internal* relationship whose
    target lives under ``word/media/`` -- the indirection ``a:blip/@r:embed``
    and ``v:imagedata/@r:id`` both go through. Kept separate from
    ``_read_rels`` (external-only, used for hyperlinks) because an internal
    media target has no ``TargetMode`` attribute at all in a typical
    document, and conflating the two tables would make a hyperlink and a
    picture relationship indistinguishable."""
    return _read_media_rels_external(z)


def _opaque_latex(root, object_store, warnings, index, *, context="inline"):
    return _opaque_latex_external(
        root, object_store, warnings, index, context=context,
        active_store=_ACTIVE_OBJECT_STORE,
    )


def _drawing_latex(drawing, img_ctx, warnings, index, object_store=None):
    return _drawing_to_latex_external(
        drawing, img_ctx, warnings, index, object_store,
        opaque_renderer=_opaque_latex,
    )


def _pict_latex(pict, img_ctx, warnings, index, object_store=None):
    return _pict_to_latex_external(
        pict, img_ctx, warnings, index, object_store,
        opaque_renderer=_opaque_latex,
    )


def _simple_alternate_content_latex(element, warnings, index, img_ctx,
                                    notes_ctx, comments_ctx, object_store):
    return _simple_alt_external(
        element, warnings, index, _hyperlink_latex,
    )


def _hyperlink_latex(link_el, rels, warnings, index):
    """``w:hyperlink`` -> ``\\href{url}{text}`` (hyperref); an internal
    bookmark anchor (no ``r:id``, only ``w:anchor``) has no external URL to
    resolve, so it is emitted as a bare styled run with a warning rather than
    a fabricated link target."""
    rid = link_el.get(qr("id"))
    url = _rel_target(rels, rid) if rid else None
    inner = "".join(
        _run_prose_to_latex(sub) for sub in link_el if ln(sub) == "r"
    )
    if url:
        # The URL argument is escaped, not interpolated raw: a DOI containing
        # `_` (or `%`, `#`, `&`, `~`, ...) is a verbatim-ish argument, and
        # hyperref unescapes this exact set when it reads the argument back.
        # docx_write.py's `_href_unescape` is the symmetric inverse (PLAN.md
        # §4.5); without the pair, the escape sequence in the display text
        # grew one copy per generation and the document never converged.
        return f"\\href{{{_href_escape(url)}}}{{{inner}}}"
    anchor = link_el.get(qw("anchor"))
    if anchor:
        return f"\\href{{{_href_escape('#' + anchor)}}}{{{inner}}}"
    warnings.append(f"internal hyperlink without anchor dropped in paragraph {index}")
    return inner


def _note_to_latex(ref_el, kind, warnings, index, notes_ctx, img_ctx):
    """The ``\\footnote{...}``/``\\endnote{...}`` spelling of one reference.

    The definition's paragraphs render through the same paragraph machinery
    as body text (formatting, hyperlinks, math all work), with the notes
    part's *own* rels so ``\\href`` targets resolve. LaTeX auto-numbers
    notes, so the definition's own ``w:footnoteRef`` mark run renders as
    nothing. A dangling reference and a multi-paragraph definition are
    named, never silent (§7.1).
    """
    return _note_to_latex_external(
        ref_el, kind, warnings, index, notes_ctx, img_ctx,
        _paragraph_inline_latex,
    )


def _comment_to_latex(ref_el, warnings, index, comments_ctx, img_ctx,
                      object_store=None):
    """Render one comment reference in the standard note form.

    The definition's paragraphs render through the same paragraph machinery
    as body text (formatting, hyperlinks, math all work), with the comments
    part's *own* rels so ``\\href`` targets resolve. A dangling reference, a
    multi-paragraph definition and a reply are named, never silent (§7.1).
    The author and date are escaped with the ``\\href`` argument set -- the
    same invertible pair the forward side undoes before they land in the
    ``w:author``/``w:date`` attributes.
    """
    return _comment_to_latex_external(
        ref_el, warnings, index, comments_ctx, img_ctx,
        _paragraph_inline_latex, object_store,
    )


# Bookmarks Word (or a converter) generated, not the author: ``_TocNNN`` are
# the TOC field's hyperlink targets, ``_HlkNNN`` are hyperlink-target
# anchors, ``_GoBack`` is navigation bookkeeping, and ``X<long hex>`` are
# converter artifacts (LibreOffice-style naming). They are consumed
# silently -- the same §4.2 argument that excludes Word's own rPr
# bookkeeping from the fidelity census -- and docfidelity's bookmark
# counter applies the identical family, so the two instruments agree.
# ``_RefNNN`` is *not* in the family: it is the target a cross-reference
# resolves to, and dropping it would leave ``\ref{...}`` with nothing to
# point at. Everything else is an authored anchor and round-trips as
# ``\label{name}``.

# Field instructions this converter models. REF/PAGEREF are the plan's §7.1
# contract (``\ref``/``\pageref``); HYPERLINK is the field form of ``\href``
# and carries the same content; anything else is reported, never guessed.
def _resolve_field(instr, cached, warnings, index, cached_latex=False,
                   object_store=None):
    r"""The LaTeX spelling of one completed field (instruction text plus the
    cached-result text collected across its runs), or the cached text with
    a named warning when the instruction is not one the converter models.

    The cached result of a REF/PAGEREF field is *not* emitted: it is a
    stale number, and the ``\ref`` regenerates it. HYPERLINK's cached text
    is the display text of the link. SEQ has no LaTeX equivalent
    (``\caption`` auto-numbers instead), so its displayed number survives
    as literal text and the loss of auto-numbering is named.
    """
    return _resolve_field_external(
        instr, cached, warnings, index, cached_latex, object_store
    )


def _wordfield_latex(instr, cached, cached_latex=False):
    return _wordfield_latex_external(instr, cached, cached_latex)


def _plain_run_latex(r_el, warnings, index, img_ctx, notes_ctx, comments_ctx,
                     object_store=None):
    return _plain_run_external(
        r_el, warnings, index, img_ctx, notes_ctx, comments_ctx,
        object_store, _drawing_latex, _pict_latex, _opaque_latex,
        _hyperlink_latex, _simple_alternate_content_latex,
        _note_to_latex, _comment_to_latex,
    )


def _paragraph_inline_latex(p_el, warnings, rels=None, index=0, img_ctx=None,
                            notes_ctx=None, comments_ctx=None,
                            object_store=None):
    return _paragraph_inline_external(
        p_el, warnings, rels, index, img_ctx, notes_ctx, comments_ctx,
        object_store, field_renderer=_resolve_field,
        plain_run_renderer=_plain_run_latex,
        hyperlink_renderer=_hyperlink_latex,
        opaque_renderer=_opaque_latex,
        alternate_renderer=_simple_alternate_content_latex,
        drawing_renderer=_drawing_latex,
        pict_renderer=_pict_latex,
    )



# --- Paragraph alignment (CANONICAL.md doc-layer section 2.2) -------------

_ALIGN_WRAP = {
    "right": "flushright", "end": "flushright",
    "left": "flushleft", "start": "flushleft",
}


def _paragraph_align_env(ppr, paragraph=None):
    """The alignment wrapper environment for a paragraph, or ``None`` when it
    should stay unwrapped.

    A missing ``w:jc`` is Word's own default (left) and needs no markup --
    ``docx_write.py`` leaves an unwrapped paragraph's alignment unset, which
    renders the same way. An *explicit* ``w:jc="both"/"justify"/
    "distribute"`` is a genuine deviation from that default and gets the
    ``justify`` wrapper so it round-trips back to an explicit w:jc, not
    Word's default left (measured: most corpus paragraphs never write a
    w:jc at all, so treating "missing" and "explicitly both" the same way
    -- an earlier version of this fix -- turned ~1200 of them into new
    degradations).
    """
    math_para = paragraph.find(qm("oMathPara")) if paragraph is not None else None
    if math_para is not None:
        math_pr = math_para.find(qm("oMathParaPr"))
        math_jc = math_pr.find(qm("jc")) if math_pr is not None else None
        val = math_jc.get(qm("val")) if math_jc is not None else None
        if val in ("left", "start"):
            return "flushleft"
        if val == "right":
            return "flushright"
        if val in ("both", "justify", "distribute"):
            return "justify"
        if val in ("center", "centerGroup"):
            return "center"
        # The math schema defaults to centered when its jc is absent.
        return "center"
    if ppr is None:
        return None
    jc = ppr.find(qw("jc"))
    if jc is None:
        return None
    val = jc.get(qw("val"))
    if val is None:
        return None
    if val in ("both", "justify", "distribute"):
        return "justify"
    if val == "center":
        return "center"
    return _ALIGN_WRAP.get(val)


# --- Named paragraph styles (D11, CANONICAL.md Rule 17) --------------------
#
# Word's own body-role signals already have a LaTeX spelling by the time
# execution reaches this helper's call site: heading level
# (_style_heading_level), list membership (_paragraph_list_info), and the
# alignment environments above. Anything else a *named* w:pStyle records --
# "Caption", "Quote", a journal template's "CustomAbstract"/"TextBodyIndent" --
# has none, so it used to be thrown away entirely (D11): a document whose
# author used such a style came back as plain body text, with docfidelity
# reporting it as `style 'customabstract' -> ''`.
#
def _named_style_wrap(style_id, text, object_store=None, owner_id=None,
                      ordinal=0, owner_text=None):
    if object_store is not None:
        owner_id = owner_id or NodeId.allocate(max(0, ordinal))
        object_store.attach(
            "paragraph-style",
            {
                "style_id": style_id,
                "text": owner_text if owner_text is not None else text,
            },
            owner_id=owner_id,
            owner_semantic_hash=hashlib.sha256(
                (owner_text if owner_text is not None else text).encode("utf-8")
            ).hexdigest(),
            position="inside",
            ordinal=ordinal,
            content_type="application/json",
        )
    if not style_id:
        return text
    paragraph = ModelParagraph((Text(text),), style=StyleRef(style_id))
    return text


def _named_table_style_wrap(style_id, text, object_store=None, owner_id=None,
                            ordinal=0):
    """Record one table slot, including an explicitly unstyled table.

    A table style is not a paragraph style: putting it in the paragraph-style
    stream made the forward parser apply it to whichever paragraph happened
    to have the nearest LaTeX hash.  The slot stream keeps table metadata on
    the table side of the native-LaTeX/sidecar boundary and preserves the
    order of nested tables as well.
    """
    if object_store is not None:
        owner_id = owner_id or NodeId.allocate(max(0, ordinal))
        object_store.attach(
            "table-style",
            {"style_id": style_id},
            owner_id=owner_id,
            owner_semantic_hash=hashlib.sha256(
                text.encode("utf-8")
            ).hexdigest(),
            position="inside",
            ordinal=ordinal,
            content_type="application/json",
        )
    return text


# --- Lists: real w:numPr, not a style-name guess ---------------------------


def _read_part_rels(z, part_name):
    """External relationship targets of one part (its `word/_rels/*.rels`).

    Hyperlinks are resolved per part: a footnote body's ``\\href`` targets
    live in ``footnotes.xml.rels``, not ``document.xml.rels`` (§7.1).
    """
    return _read_part_rels_external(z, part_name)


def _read_rels(z):
    return _read_rels_external(z)


def _read_notes(z):
    """Real footnote/endnote definitions: ``{part: {id: [w:p, ...]}}``.

    ``word/footnotes.xml`` (and the endnotes twin) carries the document's
    note definitions plus two *typed* bookkeeping entries Word writes
    itself (``separator``, ``continuationSeparator``). The ``w:type``
    attribute is the discriminator -- not the id: Word hands the
    bookkeeping entries ids -1/0 and the real notes simply take the next
    free id, so an id-based filter misreads a note whose id collides with
    the conventional separator ids (measured: a corpus footnote with id 1).
    """
    return _read_notes_external(z)


def _read_comments(z):
    """Comment definitions: ``{id: (author, date, parent, [w:p, ...])}``.

    ``word/comments.xml`` has no bookkeeping entries -- unlike the notes
    parts, every ``w:comment`` element is real. ``w:parent`` (a reply) is
    kept so the reader can name the lost threading instead of dropping it
    silently (§7.1).
    """
    return _read_comments_external(z)


def _read_numbering(z):
    """``numId -> {ilvl: numFmt}``, resolved through ``abstractNumId`` --
    PLAN_DOCLAYER.md stage 2.1. ``numbering.xml`` is the only place with
    this indirection; nothing downstream ever sees a raw numId."""
    return _read_numbering_external(z)


def _read_style_numbering(z):
    """``styleId -> (numId, ilvl)`` for numbering attached through a
    paragraph style rather than the paragraph itself -- this is how
    python-docx's own "List Bullet"/"List Number" styles carry it, so a
    document this converter produced round-trips through the same path a
    hand-authored one does."""
    return _read_style_numbering_external(z)


def _paragraph_list_info(ppr, style_id, numbering, style_num):
    """``(env, level, numfmt)`` for a list-item paragraph, or ``None``.

    ``numfmt`` carries the effective ``w:numFmt`` and ``w:lvlText`` at this
    paragraph's own level, so the reverse spelling can preserve authored
    marker punctuation and custom bullet glyphs (PLAN_DOCLAYER.md stage 2.1).
    """
    return _paragraph_list_info_external(ppr, style_id, numbering, style_num)


# The numbering owner also converts Word's ``%N`` level placeholders to valid
# LaTeX counter references. Keeping that conversion there prevents the forward
# comment stripper from mistaking a marker template for a source comment.
def _build_nested_list(entries, object_store=None):
    """``[(env, level, numfmt, item_text), ...]`` -> nested
    ``itemize``/``enumerate`` LaTeX, one ``\\item`` per entry, opening/
    closing environments as the level (and, at the same level, the marker
    format) changes.

    A paragraph can arrive at ``level`` N with **no sibling ever seen at any
    level below N** -- measured on numbered section/subsection headings
    styled through a single multilevel Word list (``sectionstyle``/
    ``subsectionstyle``, ilvl 0/1 on the same numId): the ilvl-1 style shows
    up on its own, surrounded by ordinary body-text paragraphs, never
    adjacent to an ilvl-0 sibling. There is no LaTeX syntax for "this item is
    at depth 1" other than actually nesting it inside something at depth 0,
    so a placeholder level is synthesised: an environment opened with a
    single content-free ``\\item`` whose "body" is nothing but the deeper
    environment. ``docx_write.py``'s own empty-text guard on
    ``add_paragraph_text`` means that placeholder never produces a paragraph
    of its own on the way back in, so it costs nothing round-trip-wise --
    only the genuine ilvl-N item does."""
    return _build_nested_list_external(entries, object_store=object_store)


def _style_heading_level(style_id):
    return _heading_level_external(style_id)


HEADING_LEVEL_CMD = {
    1: "section", 2: "subsection", 3: "subsubsection",
    4: "paragraph", 5: "subparagraph",
}

# A paragraph whose only content is one image (PLAN_DOCLAYER.md stage 3):
# matches "\includegraphics{...}" or "\includegraphics[opts]{...}" with
# nothing else around it.
_IMG_ONLY_RE = re.compile(
    r"^\\includegraphics(?:\[^\]]*\])?\{[^{}]*\}$"
)

def docx_to_latex(docx_path, tex_path=None):
    """Convert one DOCX into canonical LaTeX and collected diagnostics."""
    return _document_to_latex(docx_path, tex_path)


def docx_to_latex_with_blocks(docx_path, tex_path=None):
    """Return LaTeX together with source elements captured during one walk."""
    return _document_to_latex_with_blocks(docx_path, tex_path)
