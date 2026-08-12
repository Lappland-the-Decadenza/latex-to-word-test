"""Block-level traversal shared by the DOCX builder facade.

The block dispatcher remains a method because it owns the builder's stateful
cursors.  Stateless traversal and paragraph flushing live here so the facade
does not own another parser loop.
"""

import re

from docx.enum.text import WD_ALIGN_PARAGRAPH


_ENV_TOKEN_RE = re.compile(
    r"\\begin\{[A-Za-z*]+\}|\\end\{[A-Za-z*]+\}|\\item\b"
)
_PREAMBLE_METADATA_RE = re.compile(r"\\(title|author|date)\s*\{")


def strip_preamble_metadata(text, find_brace):
    """Remove title metadata that belongs in the generated preamble."""
    out = []
    position = 0
    while True:
        match = _PREAMBLE_METADATA_RE.search(text, position)
        if not match:
            out.append(text[position:])
            break
        out.append(text[position:match.start()])
        _, position = find_brace(text, match.end() - 1)
    return "".join(out)


def split_top_level_items(content):
    """Split list content on items outside nested environments."""
    parts = []
    buf_start = 0
    depth = 0
    for match in _ENV_TOKEN_RE.finditer(content):
        token = match.group(0)
        if token.startswith("\\begin{"):
            depth += 1
        elif token.startswith("\\end{"):
            depth = max(0, depth - 1)
        elif depth == 0:
            parts.append(content[buf_start:match.start()])
            buf_start = match.end()
    parts.append(content[buf_start:])
    return parts


def find_env_end(text, env, start):
    """Find the matching environment end while honoring nesting."""
    begin = re.compile(r"\\begin\{" + re.escape(env) + r"\}")
    end = re.compile(r"\\end\{" + re.escape(env) + r"\}")
    depth = 0
    position = start
    while position < len(text):
        begin_match = begin.search(text, position)
        end_match = end.search(text, position)
        if end_match is None:
            return -1, -1
        if begin_match is not None and begin_match.start() < end_match.start():
            depth += 1
            position = begin_match.end()
            continue
        if depth == 0:
            return end_match.start(), end_match.end()
        depth -= 1
        position = end_match.end()
    return -1, -1


def flush_prose(builder, text, align=None, level=-1, numfmt=None, pstyle_id=None):
    """Flush prose chunks while preserving paragraph/math merge semantics."""
    chunks = re.split(r"\n\s*\n", text)
    merge = builder._merge_next_prose and bool(chunks) and chunks[0].strip() != ""
    if len(chunks) > 1 or chunks[0].strip() != "":
        builder._merge_next_prose = False
    for idx, chunk in enumerate(chunks):
        if chunk.strip():
            builder.add_paragraph_text(
                chunk, align=align,
                append=(idx == 0 and merge), level=level, numfmt=numfmt,
                pstyle_id=pstyle_id,
            )
    if chunks and chunks[-1].strip():
        builder._merge_next_prose = True


def parse(builder, body, align=None, level=-1, numfmt=None, enum_depth=0,
          pstyle_id=None, block_re=None):
    """Traverse body text and delegate each recognized block to the builder."""
    if block_re is None:
        raise TypeError("block_re is required")
    pos = 0
    while pos < len(body):
        match = block_re.search(body, pos)
        if match is None:
            flush_prose(builder, body[pos:], align, level, numfmt, pstyle_id)
            return
        # The newline immediately before a recognized block is source
        # formatting, not paragraph content. Preserve a deliberate space
        # before it, but do not turn the structural newline into a trailing
        # Word text run.
        prefix = body[pos:match.start()]
        if match.group(1) in {"itemize", "enumerate", "description"}:
            prefix = re.sub(r"\n[ \t\n]*$", "", prefix)
        flush_prose(builder, prefix, align, level, numfmt, pstyle_id)
        # `_last_para` is a document-wide cursor and may still point at the
        # preceding source paragraph.  The dispatcher records this block's
        # actual prefix so handlers can distinguish "starts a paragraph"
        # from "continues the paragraph just flushed".
        builder._pending_block_prefix = prefix
        pos = builder._handle_block(
            body, match, align, level, numfmt, enum_depth, pstyle_id
        )


def handle_multicols(builder, content, align, level, numfmt, enum_depth,
                     pstyle_id, find_brace):
    content = content.lstrip()
    ncols = 2
    if content.startswith("{"):
        arg, after = find_brace(content, 0)
        content = content[after:]
        try:
            ncols = max(1, int((arg or "").strip()))
        except ValueError:
            builder.warnings.append(
                f"malformed multicols column count {arg!r}; assuming 2"
            )
    builder._end_section(1)
    builder.parse(
        content, align, level=level, numfmt=numfmt,
        enum_depth=enum_depth, pstyle_id=pstyle_id,
    )
    builder._end_section(ncols)


def handle_figure(builder, content, find_brace, parse_image_args, image_adder,
                  inline_renderer):
    content = re.sub(r"\\centering\b", "", content)
    match = re.search(r"\\includegraphics(\[[^\]]*\])?\{", content)
    if not match:
        builder.warnings.append("figure environment with no image; skipped")
        return
    opts, path, metadata, after = parse_image_args(
        content, match.start() + len("\\includegraphics")
    )
    paragraph = builder.doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    builder._last_para = paragraph
    image_adder(paragraph, path, opts, builder.img_base, builder.warnings, metadata)
    caption_match = re.search(r"\\caption\{", content[after:])
    if caption_match:
        caption, _ = find_brace(content, after + caption_match.end() - 1)
        try:
            caption_paragraph = builder.doc.add_paragraph(style="Caption")
        except KeyError:
            caption_paragraph = builder.doc.add_paragraph()
        builder._last_para = caption_paragraph
        inline_renderer(
            caption_paragraph, caption or "", None,
            builder.warnings, builder.img_base,
        )
