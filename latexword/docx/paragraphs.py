"""Paragraph and run-level OOXML import helpers."""

import hashlib
import re

from ..math.omml2latex import _prose_escape, ln, qm, qw, to_latex
from ..document.identity import NodeId
from .images import PICTURE_URI
from .notes import INTERNAL_BOOKMARK
from .objects import iter_skip_fallback
from .paragraph_context import ParagraphContext as _ParagraphContext
from .styles import HIGHLIGHT_NAME_TO_LATEX


MONO_FONTS = {
    "consolas", "courier new", "courier", "lucida console", "monaco",
    "dejavu sans mono", "cascadia mono", "cascadia code",
}
OFF_VALUES = ("0", "false", "off", "none", "auto")

_LITERAL_HYPHEN_RUN_RE = re.compile("-{2,}")
_HYPHEN_PLACEHOLDER = chr(0xE000)
_HYPHEN_PLACEHOLDER_RUN_RE = re.compile(_HYPHEN_PLACEHOLDER + "+")
_QUOTE_PLACEHOLDER = chr(0xE001)
_SOFT_HYPHEN_PLACEHOLDER = chr(0xE002)
_MULTISPACE_RE = re.compile(" {2,}")

_KNOWN_SYM_CHARS = {
    ("symbol", "F061"): "α",
    ("symbol", "F062"): "β",
    ("symbol", "F067"): "γ",
    ("symbol", "F070"): "π",
    ("symbol", "F073"): "σ",
    ("symbol", "F077"): "ω",
}


def run_flag(rpr, name):
    if rpr is None:
        return False
    element = rpr.find(qw(name))
    if element is None:
        return False
    value = element.get(qw("val"))
    return value is None or value.strip().lower() not in OFF_VALUES


def _mask_literal_hyphens(text):
    return _LITERAL_HYPHEN_RUN_RE.sub(
        lambda match: _HYPHEN_PLACEHOLDER * len(match.group(0)), text
    )


def _unmask_literal_hyphens(escaped):
    return _HYPHEN_PLACEHOLDER_RUN_RE.sub(
        lambda match: "-{}" * (len(match.group(0)) - 1) + "-", escaped
    )


def _color_hex(rpr, tag_name):
    if rpr is None:
        return None
    element = rpr.find(qw(tag_name))
    if element is None:
        return None
    value = element.get(qw("val"))
    if not value or value.lower() in OFF_VALUES:
        return None
    return value.upper()


def _shading_hex(rpr):
    if rpr is None:
        return None
    element = rpr.find(qw("shd"))
    if element is None:
        return None
    fill = element.get(qw("fill"))
    if not fill or fill.lower() in OFF_VALUES:
        return None
    return fill.upper()


def _highlight_name(rpr):
    if rpr is None:
        return None
    element = rpr.find(qw("highlight"))
    if element is None:
        return None
    value = element.get(qw("val"))
    if not value or value.lower() in OFF_VALUES:
        return None
    return value


def _spell_multispace(escaped):
    return _MULTISPACE_RE.sub(
        lambda match: " " + "\\ " * (len(match.group(0)) - 1), escaped
    )


def _known_sym_char(sym):
    font = (sym.get(qw("font")) or "").strip().lower()
    char = (sym.get(qw("char")) or "").strip().upper()
    return _KNOWN_SYM_CHARS.get((font, char))


def run_raw_text(r_el):
    parts = []

    def visit(node):
        for child in node:
            if ln(child) == "Fallback":
                continue
            tag = ln(child)
            if tag in {"drawing", "pict", "object", "sdt", "AlternateContent"}:
                continue
            if tag == "t":
                parts.append(child.text or "")
            elif tag == "tab":
                parts.append("\t")
            elif tag == "softHyphen":
                parts.append("\\-")
            elif tag == "sym":
                value = _known_sym_char(child)
                if value is not None:
                    parts.append(value)
            elif tag != "rPr":
                visit(child)

    visit(r_el)
    return "".join(parts)


def _record_run_state(r_el, object_store, index, run_index=None,
                      text_offset=None):
    if object_store is None:
        return
    rpr = r_el.find(qw("rPr"))
    values = _run_style_values(rpr)
    rstyle = values[-1]
    hidden = values[-2]
    if not rstyle or rstyle.strip().lower() == "hyperlink":
        rstyle = None
    if not rstyle and not hidden:
        return
    visible = run_raw_text(r_el)
    object_store.attach(
        "character-state",
        {
            "style_id": rstyle,
            "hidden": bool(hidden),
            "text": visible,
            "run_index": run_index,
            "text_offset": text_offset,
        },
        owner_id=NodeId.allocate(max(0, index)),
        owner_semantic_hash=hashlib.sha256(visible.encode("utf-8")).hexdigest(),
        position="inside",
        ordinal=index,
        content_type="application/json",
    )
def paragraph_inline_latex(
    p_el, warnings, rels=None, index=0, img_ctx=None,
    notes_ctx=None, comments_ctx=None, object_store=None, *,
    field_renderer, plain_run_renderer, hyperlink_renderer,
    opaque_renderer, alternate_renderer, drawing_renderer, pict_renderer,
):
    context = _ParagraphContext(
        p_el, warnings, rels, index, img_ctx, notes_ctx, comments_ctx,
        object_store, field_renderer, plain_run_renderer, hyperlink_renderer,
        opaque_renderer, alternate_renderer, drawing_renderer, pict_renderer,
    )
    ppr = p_el.find(qw("pPr"))
    if ppr is not None and ppr.find(qw("pageBreakBefore")) is not None:
        context.parts.append("\\newpage{}")
    for child in p_el:
        _consume_paragraph_child(context, child)
    if context.field_instr is not None:
        warnings.append(
            f"unterminated field at paragraph {index}; kept as text"
        )
        context.parts.append("".join(context.field_cached))
    return "".join(context.parts)


def _consume_field_run(context, child):
    visible = run_raw_text(child)
    _record_run_state(
        child, context.object_store, context.index, context.run_index,
        context.text_offset,
    )
    context.run_index += 1
    context.text_offset += len(visible)
    fcs = child.findall(qw("fldChar"))
    instr = "".join(
        t.text or "" for t in iter_skip_fallback(child) if ln(t) == "instrText"
    )
    if not (fcs or instr):
        if context.field_instr is not None:
            context.field_cached.append(run_prose_to_latex(child))
        else:
            context.parts.append(context.plain_run_renderer(
                child, context.warnings, context.index, context.img_ctx,
                context.notes_ctx, context.comments_ctx, context.object_store,
            ))
        return
    types = {fc.get(qw("fldCharType")) for fc in fcs}
    if "begin" in types:
        context.field_instr, context.field_cached = instr, []
    elif "separate" in types:
        pass
    elif "end" in types:
        context.parts.append(context.field_renderer(
            context.field_instr, context.field_cached, context.warnings,
            context.index, cached_latex=True, object_store=context.object_store,
        ))
        context.field_instr = None
    elif context.field_instr is not None:
        if instr:
            context.field_instr += instr
        else:
            context.field_cached.append(run_prose_to_latex(child))
    else:
        context.parts.append(context.plain_run_renderer(
            child, context.warnings, context.index, context.img_ctx,
            context.notes_ctx, context.comments_ctx, context.object_store,
        ))


def _consume_annotation(context, child):
    tag = ln(child)
    if tag == "bookmarkStart":
        name = child.get(qw("name")) or ""
        if name and not INTERNAL_BOOKMARK.match(name):
            context.parts.append(f"\\label{{{name}}}")
    elif tag == "bookmarkEnd":
        return
    elif tag == "commentRangeStart":
        cid = child.get(qw("id"))
        if cid is not None:
            context.open_comment_ranges[cid] = len(context.parts)
    elif tag == "commentRangeEnd":
        cid = child.get(qw("id"))
        snapshot = context.open_comment_ranges.pop(cid, None)
        if snapshot is None:
            if cid is not None:
                context.warnings.append(
                    f"comment range id={cid} spans paragraphs; the "
                    "highlight is not carried (L* \\todo anchors a point)"
                )
        elif len(context.parts) > snapshot:
            context.warnings.append(
                f"comment range id={cid} covers text; the highlight is "
                "not carried (L* \\todo anchors a point)"
            )


def _append_inline_math(context, child):
    try:
        tex = to_latex(child)
    except Exception as exc:  # pragma: no cover - defensive
        context.warnings.append(f"inline math conversion failed: {exc}")
        return
    if tex.strip():
        context.parts.append("$" + tex + "$")
    else:
        context.parts.append("$\\text{}$")


def _append_display_math(context, child):
    for om in child.findall(qm("oMath")):
        try:
            tex = to_latex(om)
        except Exception as exc:  # pragma: no cover - defensive
            context.warnings.append(f"display math conversion failed: {exc}")
            tex = ""
        leading = (
            "" if context.parts and context.parts[-1].strip().startswith("$")
            else "\n"
        )
        context.parts.append(f"{leading}\\[\n{tex}\n\\]")


def _consume_paragraph_child(context, child):
    tag = ln(child)
    if tag == "r":
        _consume_field_run(context, child)
    elif tag == "fldSimple":
        instr = child.get(qw("instr")) or ""
        cached = [
            run_prose_to_latex(r) for r in child if ln(r) == "r"
        ]
        context.parts.append(context.field_renderer(
            instr, cached, context.warnings, context.index, cached_latex=True,
            object_store=context.object_store,
        ))
    elif tag in {
        "bookmarkStart", "bookmarkEnd", "commentRangeStart", "commentRangeEnd"
    }:
        _consume_annotation(context, child)
    elif tag == "oMath":
        _append_inline_math(context, child)
    elif tag == "hyperlink":
        # A hyperlink is a container, so its runs do not pass through the
        # ordinary paragraph-child ``w:r`` branch. Capture their authored
        # character styles explicitly; the forward \\href renderer creates
        # the same nested runs and the builder reapplies these states from
        # the sidecar.
        for run in child.iter(qw("r")):
            visible = run_raw_text(run)
            _record_run_state(
                run, context.object_store, context.index, context.run_index,
                context.text_offset,
            )
            context.run_index += 1
            context.text_offset += len(visible)
        context.parts.append(context.hyperlink_renderer(
            child, context.rels, context.warnings, context.index
        ))
    elif tag in {"sdt", "object"}:
        opaque = context.opaque_renderer(
            child, context.object_store, context.warnings, context.index
        )
        if opaque:
            context.parts.append(opaque)
    elif tag == "AlternateContent":
        live = context.alternate_renderer(
            child, context.warnings, context.index, context.img_ctx,
            context.notes_ctx, context.comments_ctx, context.object_store,
        )
        opaque = live if live is not None else context.opaque_renderer(
            child, context.object_store, context.warnings, context.index
        )
        if opaque:
            context.parts.append(opaque)
    elif tag == "br":
        context.parts.append(
            "\\newpage{}" if child.get(qw("type")) == "page" else "\\\\"
        )
    elif tag == "oMathPara":
        _append_display_math(context, child)
    elif tag == "drawing":
        img_tex = context.drawing_renderer(
            child, context.img_ctx, context.warnings, context.index,
            context.object_store,
        )
        if img_tex:
            context.parts.append(img_tex)
    elif tag == "pict":
        img_tex = context.pict_renderer(
            child, context.img_ctx, context.warnings, context.index,
            context.object_store,
        )
        if img_tex:
            context.parts.append(img_tex)
    elif tag == "tab":
        context.parts.append("\t")

def _run_style_values(rpr):
    bold = run_flag(rpr, "b")
    italic = run_flag(rpr, "i")
    underline = run_flag(rpr, "u")
    strike = run_flag(rpr, "strike") or run_flag(rpr, "dstrike")
    smallcaps = run_flag(rpr, "smallCaps")
    vertalign = None
    if rpr is not None:
        element = rpr.find(qw("vertAlign"))
        if element is not None and element.get(qw("val")) in (
            "superscript", "subscript"
        ):
            vertalign = element.get(qw("val"))
    mono = False
    if rpr is not None:
        fonts = rpr.find(qw("rFonts"))
        if fonts is not None:
            ascii_font = (fonts.get(qw("ascii")) or "").strip().lower()
            mono = ascii_font in MONO_FONTS
    color = _color_hex(rpr, "color")
    highlight = _highlight_name(rpr)
    shading = _shading_hex(rpr)
    hidden = run_flag(rpr, "vanish")
    rstyle = None
    if rpr is not None:
        style = rpr.find(qw("rStyle"))
        rstyle = style.get(qw("val")) if style is not None else None
    return (
        bold, italic, underline, strike, smallcaps, vertalign, mono,
        color, highlight, shading, hidden, rstyle,
    )


def _escape_run_text(text):
    text = text.replace("\\-", _SOFT_HYPHEN_PLACEHOLDER)
    text = text.replace("''", _QUOTE_PLACEHOLDER * 2)
    escaped = _spell_multispace(_prose_escape(_mask_literal_hyphens(text)))
    escaped = _unmask_literal_hyphens(escaped)
    escaped = escaped.replace(_SOFT_HYPHEN_PLACEHOLDER, "\\-")
    return escaped.replace(_QUOTE_PLACEHOLDER, "\\textquotesingle{}")


def run_prose_to_latex(r_el, breaks=()):
    """Convert one run to canonical LaTeX with its character formatting."""
    text = run_raw_text(r_el)
    if not text and not breaks:
        return "".join(breaks)
    values = _run_style_values(r_el.find(qw("rPr")))
    (
        bold, italic, underline, strike, smallcaps, vertalign, mono,
        color, highlight, shading, hidden, rstyle,
    ) = values
    escaped = _escape_run_text(text)
    prefix = "".join(breaks)
    boxed = bool(vertalign or underline or strike or highlight or shading)
    if not text and boxed:
        return prefix
    out = escaped if boxed else prefix + escaped
    if vertalign == "superscript":
        out = f"\\textsuperscript{{{out}}}"
    elif vertalign == "subscript":
        out = f"\\textsubscript{{{out}}}"
    if smallcaps:
        out = f"\\textsc{{{out}}}"
    if strike:
        out = f"\\sout{{{out}}}"
    if underline:
        out = f"\\underline{{{out}}}"
    if italic:
        out = f"\\textit{{{out}}}"
    if bold:
        out = f"\\textbf{{{out}}}"
    if mono:
        out = f"\\texttt{{{out}}}"
    if highlight:
        latex_color = HIGHLIGHT_NAME_TO_LATEX.get(highlight.lower(), "yellow")
        if latex_color == "yellow":
            out = f"\\hl{{{out}}}"
        else:
            out = f"{{\\sethlcolor{{{latex_color}}}\\hl{{{out}}}}}"
    elif shading:
        out = f"\\colorbox[HTML]{{{shading}}}{{{out}}}"
    if color:
        out = f"\\textcolor[HTML]{{{color}}}{{{out}}}"
    # Character style identity and hidden state are Word-only. The visible
    # text stays in the clean semantic stream; the reader records those
    # properties through the sidecar attachment seam.
    return prefix + out if boxed else out


def run_breaks_to_latex(r_el, warnings, index):
    parts = []
    for br in r_el.findall(qw("br")):
        if br.get(qw("type")) == "page":
            parts.append("\\newpage{}")
        else:
            parts.append("\\\\")
    return parts


def simple_alternate_content_latex(element, warnings, index,
                                   hyperlink_renderer):
    choice = next(
        (child for child in element if ln(child) == "Choice"),
        None,
    )
    if choice is None:
        return None
    unsupported = {
        "drawing", "pict", "object", "sdt", "txbx", "txbxContent",
        "textbox", "AlternateContent",
    }
    if any(ln(node) in unsupported for node in iter_skip_fallback(choice)):
        return None
    parts = []
    for child in choice:
        if ln(child) == "r":
            parts.append(run_prose_to_latex(
                child, run_breaks_to_latex(child, warnings, index)
            ))
        elif ln(child) == "hyperlink":
            parts.append(hyperlink_renderer(child, {}, warnings, index))
        elif ln(child) not in {"proofErr", "permStart", "permEnd"}:
            return None
    return "".join(parts)


def plain_run_latex(r_el, warnings, index, img_ctx, notes_ctx, comments_ctx,
                    object_store, drawing_renderer, pict_renderer,
                    opaque_renderer, hyperlink_renderer, alternate_renderer,
                    note_renderer, comment_renderer):
    """Render one field-free run and its attached inline objects/marks."""
    parts = [run_prose_to_latex(
        r_el, run_breaks_to_latex(r_el, warnings, index)
    )]
    for child in r_el:
        tag = ln(child)
        if tag == "drawing":
            value = drawing_renderer(child, img_ctx, warnings, index, object_store)
        elif tag == "pict":
            value = pict_renderer(child, img_ctx, warnings, index, object_store)
        elif tag in {"object", "sdt"}:
            value = opaque_renderer(child, object_store, warnings, index)
        elif tag == "AlternateContent":
            picture = next(
                (
                    node for node in iter_skip_fallback(child)
                    if ln(node) == "drawing"
                    and any(
                        descendant.tag.rsplit("}", 1)[-1] == "graphicData"
                        and descendant.get("uri") == PICTURE_URI
                        for descendant in node.iter()
                    )
                    and any(
                        descendant.tag.rsplit("}", 1)[-1] == "blip"
                        for descendant in node.iter()
                    )
                ),
                None,
            )
            if picture is not None:
                value = drawing_renderer(
                    picture, img_ctx, warnings, index, object_store
                )
            else:
                value = alternate_renderer(
                    child, warnings, index, img_ctx,
                    notes_ctx, comments_ctx, object_store,
                )
                if value is None:
                    value = opaque_renderer(
                        child, object_store, warnings, index
                    )
        else:
            value = None
        if value:
            parts.append(value)
    if notes_ctx or comments_ctx:
        if notes_ctx:
            for reference in r_el.findall(qw("footnoteReference")):
                parts.append(note_renderer(
                    reference, "footnote", warnings, index, notes_ctx, img_ctx
                ))
            for reference in r_el.findall(qw("endnoteReference")):
                parts.append(note_renderer(
                    reference, "endnote", warnings, index, notes_ctx, img_ctx
                ))
        for reference in r_el.findall(qw("commentReference")):
            parts.append(comment_renderer(
                reference, warnings, index, comments_ctx, img_ctx,
                object_store,
            ))
    return "".join(parts)
