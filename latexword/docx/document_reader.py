"""Document-level reverse conversion orchestration.

The public API remains in read.py; this module coordinates package loading,
block extraction, and final document assembly through component readers.
"""

from dataclasses import dataclass

from ..document.identity import NodeId

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"


@dataclass(frozen=True, slots=True)
class ElementOrigin:
    """An element captured while the reverse reader is visiting it."""

    element: object
    part: str = "/word/document.xml"


@dataclass(frozen=True, slots=True)
class ConvertedBlock:
    latex: str
    part: str
    elements: tuple[ElementOrigin, ...]
    block_kind: str
    style_hint: str | None = None
    language_hint: str | None = None
    spacing_hint: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentReadResult:
    latex: str
    warnings: tuple[str, ...]
    blocks: tuple[ConvertedBlock, ...]


class _ReaderState:
    def __init__(
        self, api, root, body, rels, numbering, style_num, notes_ctx,
        comments_ctx, object_store, img_ctx,
    ):
        self.api = api
        self.root = root
        self.body = body
        self.rels = rels
        self.numbering = numbering
        self.style_num = style_num
        self.notes_ctx = notes_ctx
        self.comments_ctx = comments_ctx
        self.object_store = object_store
        self.img_ctx = img_ctx
        self.warnings = []
        self.lines = []
        self.blocks = []
        self.list_entries = []
        self.title_text = None
        self.author_text = None
        self.children = list(body)
        self.columns_at = api._column_layout_external(self.children, body)
        self.open_columns = 1
        self.in_toc_field = False


def _block(state, latex, elements, kind, style_hint=None):
    """Append one emitted block and retain the source elements immediately."""

    language_counts = {}
    has_ascii_double_space = False
    for element in elements:
        for node in element.iter(f"{{{W_NS}}}lang"):
            value = node.get(f"{{{W_NS}}}val")
            if value:
                language_counts[value] = language_counts.get(value, 0) + 1
        for node in element.iter(f"{{{M_NS}}}t"):
            if "  " in (node.text or "") and "\u2003" not in (node.text or ""):
                has_ascii_double_space = True
    language_hint = max(language_counts, key=language_counts.get, default=None)
    state.lines.append(latex)
    state.blocks.append(ConvertedBlock(
        latex, "/word/document.xml",
        tuple(ElementOrigin(item) for item in elements), kind, style_hint,
        language_hint, "word-double-space" if has_ascii_double_space else None,
    ))


def _load_state(api, docx_path, tex_path):
    with api.zipfile.ZipFile(docx_path) as archive:
        xml = archive.read("word/document.xml")
        rels = api._read_rels(archive)
        numbering = api._read_numbering(archive)
        style_num = api._read_style_numbering(archive)
        media_rels = api._read_media_rels(archive)
        media_bytes = {
            name: archive.read(name)
            for name in archive.namelist()
            if name.startswith("word/media/")
        }
        notes_ctx = {
            part: (defs, api._read_part_rels(archive, part))
            for part, defs in api._read_notes(archive).items()
        }
        comments_defs = api._read_comments(archive)
        comments_ctx = None
        if comments_defs:
            comments_ctx = (
                comments_defs,
                api._read_part_rels(archive, "word/comments.xml"),
            )

    root = api.etree.fromstring(xml)
    body = root.find(api.qw("body"))
    sidecar_tex_path = (
        tex_path
        or api.os.path.splitext(docx_path)[0] + "_reversed.tex"
    )
    object_store = api.ObjectStore.for_write(sidecar_tex_path, archive)
    api._ACTIVE_OBJECT_STORE = object_store
    _capture_glossary(api, object_store)
    source_path = tex_path or docx_path
    stem = api.os.path.splitext(api.os.path.basename(source_path))[0]
    stem = api.re.sub(r"_[dr]\d+$", "", stem) or stem
    figures_dirname = stem + ".figures"
    figures_dir_abs = api.os.path.join(
        api.os.path.dirname(api.os.path.abspath(source_path)),
        figures_dirname,
    )
    img_ctx = api._ImageContext(
        media_rels, media_bytes, figures_dirname, figures_dir_abs
    )
    return _ReaderState(
        api, root, body, rels, numbering, style_num, notes_ctx,
        comments_ctx, object_store, img_ctx,
    )


def _capture_glossary(api, object_store):
    if "word/glossary/document.xml" not in object_store.archive.namelist():
        return
    rel_root = api.etree.fromstring(
        object_store.archive.read("word/_rels/document.xml.rels")
    )
    glossary_rel = next(
        (
            rel for rel in rel_root
            if rel.get("Target") == "glossary/document.xml"
        ),
        None,
    )
    if glossary_rel is not None:
        object_store.capture_package_part(
            "word/glossary/document.xml", glossary_rel.get("Type", "")
        )


def _flush_list(state):
    if state.list_entries:
        latex = state.api._build_nested_list(
            state.list_entries, object_store=state.object_store
        )
        elements = [state.children[item[-1]] for item in state.list_entries]
        _block(state, latex, elements, "list")
        state.list_entries.clear()


def _set_columns(state, target):
    if target == state.open_columns:
        return
    _flush_list(state)
    if state.open_columns > 1:
        state.lines.append("\\end{multicols}\n")
    if target > 1:
        state.lines.append("\\begin{multicols}{%d}\n" % target)
    state.open_columns = target


def _render_non_paragraph(state, index, element):
    api = state.api
    tag = api.ln(element)
    if tag == "tbl":
        _flush_list(state)
        latex = api._table_to_latex(
            element, state.warnings, state.rels, state.img_ctx, index,
            paragraph_renderer=api._paragraph_inline_latex,
            style_wrapper=lambda style, text: api._named_table_style_wrap(
                style, text, state.object_store, NodeId.allocate(index), index
            ),
            notes_ctx=state.notes_ctx,
            comments_ctx=state.comments_ctx,
            object_store=state.object_store,
        ) + "\n"
        _block(state, latex, (element,), "table")
    elif tag == "sdt":
        _flush_list(state)
        # Word commonly stores a generated table of contents in an SDT.  Its
        # cached entry paragraphs are not authored document content; the
        # field instruction is the semantic object and must become the native
        # LaTeX command, not an opaque text dump of stale page numbers.
        instr = "".join(
            text.text or "" for text in element.iter(api.qw("instrText"))
        )
        if "TOC" in instr.upper():
            _block(state, "\\tableofcontents\n", (element,), "p")
        else:
            opaque = api._opaque_latex(
                element, state.object_store, state.warnings, index, context="block"
            )
            if opaque:
                _block(state, opaque + "\n", (element,), "opaque")
    elif tag in {"bookmarkStart", "bookmarkEnd",
                 "commentRangeStart", "commentRangeEnd"}:
        pass
    elif tag != "sectPr":
        state.warnings.append(
            f"skipped unrecognised block <{tag}> at block {index}"
        )
    return index + 1


def _consume_toc_field(state, index, element):
    api = state.api
    instr_texts = "".join(
        text.text or "" for text in element.iter(api.qw("instrText"))
    )
    has_begin = any(
        field.get(api.qw("fldCharType")) == "begin"
        for field in element.iter(api.qw("fldChar"))
    )
    if not state.in_toc_field and has_begin and "TOC" in instr_texts.upper():
        state.in_toc_field = True
        _flush_list(state)
        _block(state, "\\tableofcontents\n", (element,), "p")
        return index + 1
    if state.in_toc_field:
        has_end = any(
            field.get(api.qw("fldCharType")) == "end"
            for field in element.iter(api.qw("fldChar"))
        )
        if has_end:
            state.in_toc_field = False
        return index + 1
    return None


def _paragraph_parts(state, element, index):
    api = state.api
    ppr = element.find(api.qw("pPr"))
    style_el = ppr.find(api.qw("pStyle")) if ppr is not None else None
    style_id = style_el.get(api.qw("val")) if style_el is not None else None
    level = api._style_heading_level(style_id)
    return ppr, style_id, level


def _render_heading(state, index, element, ppr, style_id, level):
    api = state.api
    _flush_list(state)
    text = api._paragraph_inline_latex(
        element, state.warnings, state.rels, index, state.img_ctx,
        state.notes_ctx, state.comments_ctx, state.object_store,
    )
    if level == 0:
        # A level-0 Word paragraph is still an authored body block. Moving it
        # into LaTeX's preamble (and grouping the following italic paragraph
        # as ``\\author``) reorders documents whose title page starts with a
        # label, and shifts every later sidecar ordinal. Keep the paragraph in
        # the body stream; users may still write explicit ``\\title``/``\\author``
        # in hand-authored LaTeX, but DOCX recovery must preserve block order.
        body_text = text if text.strip() else f"\\mbox{{{text}}}\\par"
        _block(state, api._named_style_wrap(
            style_id, body_text, state.object_store, NodeId.allocate(index), index,
            owner_text=text,
        ) + "\n", (element,), "heading", style_id)
        return index + 1
    command = api.HEADING_LEVEL_CMD.get(level, "subparagraph")
    _block(state, api._named_style_wrap(
        style_id, f"\\{command}{{{text}}}", state.object_store,
        NodeId.allocate(index), index, owner_text=text,
    ) + "\n", (element,), "heading", style_id)
    return index + 1


def _render_list_item(state, index, element, ppr, style_id):
    api = state.api
    list_info = api._paragraph_list_info(
        ppr, style_id, state.numbering, state.style_num
    )
    if list_info is None:
        return None
    env, level, numfmt = list_info
    text = api._paragraph_inline_latex(
        element, state.warnings, state.rels, index, state.img_ctx,
        state.notes_ctx, state.comments_ctx, state.object_store,
    )
    item_align = api._paragraph_align_env(ppr, element)
    if item_align and text.strip():
        text = f"\\begin{{{item_align}}}{text}\\end{{{item_align}}}"
    state.list_entries.append((env, level, numfmt, text, style_id, index))
    return index + 1


def _paragraph_text(state, element, index):
    return state.api._paragraph_inline_latex(
        element, state.warnings, state.rels, index, state.img_ctx,
        state.notes_ctx, state.comments_ctx, state.object_store,
    )


def _append_nonempty_paragraph(state, index, element, style_id, align_env, text):
    api = state.api
    stripped = text.strip()
    next_index = index + 1
    caption_text = None
    if (
        api._IMG_ONLY_RE.match(stripped)
        and next_index < len(state.children)
        and api.ln(state.children[next_index]) == "p"
    ):
        following = state.children[next_index]
        next_ppr = following.find(api.qw("pPr"))
        cap_style_el = (
            next_ppr.find(api.qw("pStyle"))
            if next_ppr is not None else None
        )
        cap_style = (
            cap_style_el.get(api.qw("val"))
            if cap_style_el is not None else None
        )
        if cap_style and cap_style.strip().lower() == "caption":
            caption_text = _paragraph_text(state, following, next_index).strip()
            next_index += 1
    if caption_text:
        _block(state, f"\\begin{{figure}}[h]\\centering {stripped}"
               f"\\caption{{{caption_text}}}\\end{{figure}}\n",
               (element, following), "figure", style_id)
    elif align_env:
        _block(state, api._named_style_wrap(
            style_id, f"\\begin{{{align_env}}}{text}\\end{{{align_env}}}",
            state.object_store, NodeId.allocate(index), index, owner_text=text,
        ) + "\n", (element,), "p", style_id)
    else:
        _block(state, api._named_style_wrap(
            style_id, text, state.object_store, NodeId.allocate(index), index,
        ) + "\n", (element,), "p", style_id)
    return next_index


def _render_body_paragraph(state, index, element, ppr, style_id):
    api = state.api
    _flush_list(state)
    text = _paragraph_text(state, element, index)
    align_env = api._paragraph_align_env(ppr, element)
    if text.strip():
        return _append_nonempty_paragraph(
            state, index, element, style_id, align_env, text
        )
    empty = f"\\mbox{{{text}}}\\par"
    if align_env:
        empty = f"\\begin{{{align_env}}}{empty}\\end{{{align_env}}}"
    _block(state, api._named_style_wrap(
        style_id, empty, state.object_store, NodeId.allocate(index), index,
        owner_text=text,
    ) + "\n", (element,), "p", style_id)
    return index + 1


def _scan_paragraph(state, index, element):
    toc_index = _consume_toc_field(state, index, element)
    if toc_index is not None:
        return toc_index
    ppr, style_id, level = _paragraph_parts(state, element, index)
    if level is not None:
        return _render_heading(state, index, element, ppr, style_id, level)
    list_index = _render_list_item(state, index, element, ppr, style_id)
    if list_index is not None:
        return list_index
    return _render_body_paragraph(state, index, element, ppr, style_id)


def _scan_blocks(state):
    index = 0
    while index < len(state.children):
        _set_columns(state, state.columns_at[index])
        element = state.children[index]
        if state.api.ln(element) != "p":
            index = _render_non_paragraph(state, index, element)
        else:
            index = _scan_paragraph(state, index, element)
    _flush_list(state)
    _set_columns(state, 1)


def _append_unreferenced_warnings(state):
    api = state.api
    for part, (defs, _) in state.notes_ctx.items():
        tag = "footnote" if "footnotes" in part else "endnote"
        used = {
            element.get(api.qw("id"))
            for element in state.root.iter(api.qw(tag + "Reference"))
        }
        for note_id in defs:
            if note_id not in used:
                state.warnings.append(
                    f"unreferenced {tag} definition id={note_id} not emitted"
                )
    if state.comments_ctx:
        defs, _ = state.comments_ctx
        used = {
            element.get(api.qw("id"))
            for element in state.root.iter(api.qw("commentReference"))
        }
        for comment_id in defs:
            if comment_id not in used:
                state.warnings.append(
                    f"unreferenced comment id={comment_id} not emitted"
                )


def _assemble(state):
    body_text = "\n\n".join(state.lines)
    if state.title_text:
        body_text += state.title_text
    if state.author_text:
        body_text += state.author_text
    preamble, tail = state.api.build_preamble(
        body_text, state.title_text, state.author_text
    )
    labelled = []
    block_index = 0
    next_label = 1
    for line in state.lines:
        if (block_index < len(state.blocks)
                and line == state.blocks[block_index].latex):
            block = state.blocks[block_index]
            prefix = f"%lw:{block.block_kind}:{next_label}\n"
            next_label += 1
            if block.block_kind == "list":
                item_label = next_label
                def mark_item(match):
                    nonlocal item_label
                    value = f"%lw:item:{item_label}\n\\item"
                    item_label += 1
                    return value
                line = __import__("re").sub(r"\\item\b", mark_item, line)
                next_label = item_label
            labelled.append(prefix + line)
            block_index += 1
        else:
            labelled.append(line)
    return (
        "\n".join(preamble) + "\n\n"
        + "\n\n".join(labelled) + "\n\n"
        + tail + "\\end{document}\n"
    )


def document_to_latex_with_blocks(docx_path, tex_path=None):
    from . import read as api
    state = _load_state(api, docx_path, tex_path)
    try:
        _scan_blocks(state)
        _append_unreferenced_warnings(state)
        return DocumentReadResult(
            _assemble(state), tuple(state.warnings), tuple(state.blocks)
        )
    finally:
        state.object_store.close()
        api._ACTIVE_OBJECT_STORE = None


def document_to_latex(docx_path, tex_path=None):
    result = document_to_latex_with_blocks(docx_path, tex_path)
    return result.latex, list(result.warnings)
