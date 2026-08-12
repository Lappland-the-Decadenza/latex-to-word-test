"""Parser for the closed, native document-level LaTeX grammar."""

from __future__ import annotations

from dataclasses import replace
import re

from ..document.diagnostics import Diagnostic, DiagnosticCode, Severity, SourceReference
from ..document.formatting import ParagraphFormat, RunFormat
from ..document.text import href_unescape, prose_unescape
from ..document.model import (
    Bookmark, Cell, Document, Field, FieldSpec, Footnote, Hyperlink, ImageBlock,
    ImageInline, ImageSpec, LineBreak, ListBlock, ListItem, Math, Paragraph,
    Quote, Row, SectionBreak, Table, Text, Todo,
)


_HEADING = re.compile(r"\\(section|subsection|subsubsection|paragraph)\*?\s*\{")
_ENV = re.compile(r"\\begin\{([A-Za-z*]+)\}")
_ENV_TOKEN = re.compile(r"\\(begin|end)\{([A-Za-z*]+)\}|\\item\b")
_TABLE_RULE = re.compile(r"\\(?:hline|cline(?:\s*\[[^\]]*\])?\{[^{}]*\})")
_INLINE_COMMANDS = {
    "textbf": "bold", "textit": "italic", "emph": "italic",
    "texttt": "monospace", "textsc": "small_caps", "underline": "underline",
    "sout": "strikethrough", "textsuperscript": "superscript",
    "textsubscript": "subscript",
}
_LITERALS = {
    "textbackslash": "\\", "textasciitilde": "~", "textasciicircum": "^",
    "ldots": "…", "quad": " ", "qquad": " ", ",": " ", ";": " ",
    ":": " ", "!": " ", " ": " ", "%": "%", "&": "&", "_": "_",
    "#": "#", "$": "$", "{": "{", "}": "}", "~": "~",
    "textquotesingle": "'",
}


def _group(source, start, opener="{", closer="}"):
    if start >= len(source) or source[start] != opener:
        return None, start
    depth = 1
    index = start + 1
    while index < len(source):
        if source[index] == "\\":
            index += 2
            continue
        if source[index] == opener:
            depth += 1
        elif source[index] == closer:
            depth -= 1
            if depth == 0:
                return source[start + 1:index], index + 1
        index += 1
    return None, len(source)


def _diagnostic(code, message, index):
    return Diagnostic(
        DiagnosticCode(code), Severity.ERROR, message,
        SourceReference(part="native-latex", index=index),
    )


def _strip_comments(source):
    lines = []
    for line in source.splitlines(keepends=True):
        match = re.search(r"(?<!\\)(?:\\\\)*%", line)
        lines.append(line if match is None else line[:match.start()])
    return "".join(lines)


def _command(source, position):
    match = re.match(r"\\([A-Za-z]+|.)", source[position:])
    return (match.group(1), position + match.end()) if match else ("", position + 1)


def _inline_group(source, after, diagnostics, offset, format_, name):
    content, end = _group(source, after)
    if content is None:
        diagnostics.append(_diagnostic("invalid-input", f"malformed \\{name}", offset))
        return [], after
    child_format = replace(format_, **{_INLINE_COMMANDS[name]: True})
    return _inline(content, diagnostics, offset + after + 1, child_format), end


def _inline_link(source, after, diagnostics, offset, format_, url=False):
    target, target_end = _group(source, after)
    if target is None:
        diagnostics.append(_diagnostic("invalid-input", "malformed hyperlink", offset))
        return [], after
    target = href_unescape(target)
    if url:
        return [Hyperlink(target, (Text(target, format_),))], target_end
    text, end = _group(source, target_end)
    if text is None:
        diagnostics.append(_diagnostic("invalid-input", "malformed \\href", offset))
        return [], after
    return [Hyperlink(target, tuple(_inline(text, diagnostics, offset, format_)))], end


def _inline_color(source, after, diagnostics, offset, format_, name):
    color_start = after
    if color_start < len(source) and source[color_start] == "[":
        _, color_start = _group(source, color_start, "[", "]")
    color, color_end = _group(source, color_start)
    body, end = _group(source, color_end)
    if color is None or body is None:
        diagnostics.append(_diagnostic("invalid-input", f"malformed \\{name}", offset))
        return [], after
    key = "color" if name == "textcolor" else "shading"
    return _inline(body, diagnostics, offset, replace(format_, **{key: color})), end


def _inline_command(source, name, after, diagnostics, offset, format_):
    if name in {"", "\\"}:
        return [LineBreak(True)], after
    if name == "-":
        return [Text("-", format_)], after
    if name == "par":
        return [LineBreak(False)], after
    if name == "newpage":
        return [LineBreak(False)], after
    if name == "linebreak":
        return [LineBreak(False)], after
    if name in _INLINE_COMMANDS:
        return _inline_group(source, after, diagnostics, offset, format_, name)
    if name in {"href", "url"}:
        return _inline_link(source, after, diagnostics, offset, format_, name == "url")
    if name == "includegraphics":
        path_start = after
        if path_start < len(source) and source[path_start] == "[":
            _, path_start = _group(source, path_start, "[", "]")
        path, end = _group(source, path_start)
        if path is None:
            diagnostics.append(_diagnostic("invalid-input", "malformed \\includegraphics", offset))
            return [], after
        return [ImageInline(ImageSpec(source_path=path))], end
    if name in {"textcolor", "colorbox"}:
        return _inline_color(source, after, diagnostics, offset, format_, name)
    if name == "hl":
        body, end = _group(source, after)
        if body is None:
            diagnostics.append(_diagnostic("invalid-input", "malformed \\hl", offset))
            return [], after
        return _inline(body, diagnostics, offset, replace(format_, highlight="yellow")), end
    if name == "mbox":
        body, end = _group(source, after)
        return (_inline(body, diagnostics, offset, format_), end) if body is not None else ([], after)
    if name == "footnote":
        body, end = _group(source, after)
        if body is None:
            diagnostics.append(_diagnostic("invalid-input", "malformed \\footnote", offset))
            return [], after
        return [Footnote(_blocks(body, diagnostics))], end
    if name == "label":
        label, end = _group(source, after)
        return ([Bookmark(href_unescape(label))] if label is not None else []), end
    if name in {"ref", "pageref", "cite"}:
        value, end = _group(source, after)
        if value is None:
            diagnostics.append(_diagnostic("invalid-input", f"malformed \\{name}", offset))
            return [], after
        return [Field(FieldSpec(value, name.upper()))], end
    if name == "todo":
        option_end = after
        options = ""
        if option_end < len(source) and source[option_end] == "[":
            options, option_end = _group(source, option_end, "[", "]")
        body, end = _group(source, option_end)
        if body is None:
            diagnostics.append(_diagnostic("invalid-input", "malformed \\todo", offset))
            return [], after
        values = [item.strip() for item in (options or "").split(",") if item.strip()]
        inline = "inline" in values
        color = next((item.split("=", 1)[1] for item in values if item.startswith("color=")), None)
        return [Todo(tuple(_inline(body, diagnostics, offset, format_)), inline, color)], end
    if name in _LITERALS:
        return [Text(_LITERALS[name], format_)], after
    diagnostics.append(_diagnostic("unknown-command", f"unknown native command \\{name}", offset))
    return None, after


def _inline(source, diagnostics, offset=0, format_=None):
    format_ = format_ or RunFormat()
    nodes, plain, position = [], [], 0

    def flush():
        if plain:
            nodes.append(Text(prose_unescape("".join(plain)), format_, SourceReference(part="native-latex", index=offset + position)))
            plain.clear()

    while position < len(source):
        if source[position] == "{" :
            body, end = _group(source, position)
            if body is not None:
                flush()
                scoped = re.fullmatch(r"\\sethlcolor\{([^{}]+)\}\\hl\{(.*)\}", body, re.S)
                if scoped:
                    nodes.extend(_inline(scoped.group(2), diagnostics, offset + position, replace(format_, highlight=scoped.group(1))))
                else:
                    nodes.extend(_inline(body, diagnostics, offset + position + 1, format_))
                position = end
                continue
        if source[position] == "$" or source.startswith(r"\[", position):
            flush()
            display = source.startswith(r"\[", position)
            opener = 2 if display else 1
            closer = r"\]" if display else "$"
            end = source.find(closer, position + opener)
            if end < 0:
                diagnostics.append(_diagnostic("invalid-input", "unclosed math", offset + position))
                plain.append(source[position:])
                break
            nodes.append(Math(source[position + opener:end], display, SourceReference(part="native-latex", index=offset + position)))
            position = end + len(closer)
            continue
        if source[position] != "\\":
            plain.append(source[position])
            position += 1
            continue
        name, after = _command(source, position)
        result, end = _inline_command(source, name, after, diagnostics, offset + position, format_)
        if name == "\\":
            while end < len(source) and source[end].isspace():
                end += 1
            if end < len(source) and source[end] == "*":
                end += 1
                while end < len(source) and source[end].isspace():
                    end += 1
            if end < len(source) and source[end] == "[":
                _length, end = _group(source, end, "[", "]")
                while end < len(source) and source[end].isspace():
                    end += 1
        if result is None:
            plain.append(source[position:after])
        else:
            flush()
            nodes.extend(result)
        position = end
    flush()
    merged = []
    for node in nodes:
        if isinstance(node, Text) and not node.value:
            continue
        if (
            merged and isinstance(merged[-1], Text) and isinstance(node, Text)
            and merged[-1].format == node.format
        ):
            previous = merged[-1]
            merged[-1] = Text(previous.value + node.value, previous.format, previous.context)
        else:
            merged.append(node)
    return merged


def _environment(source, start, name):
    depth = 1
    pattern = re.compile(r"\\(?:begin|end)\{" + re.escape(name) + r"\}")
    for match in pattern.finditer(source, start):
        depth += -1 if match.group(0).startswith(r"\end") else 1
        if depth == 0:
            return source[start:match.start()], match.end()
    return None, len(source)


def _top_level_items(body):
    positions, depth = [], 0
    for match in _ENV_TOKEN.finditer(body):
        token = match.group(0)
        if token.startswith(r"\begin"):
            depth += 1
        elif token.startswith(r"\end"):
            depth = max(0, depth - 1)
        elif depth == 0:
            positions.append(match.start())
    return positions


def _list_items(body, diagnostics, ordered, description=False, label=None, start=None):
    positions = _top_level_items(body)
    items = []
    for number, position in enumerate(positions):
        end = positions[number + 1] if number + 1 < len(positions) else len(body)
        cursor = position + len(r"\item")
        item_label = ()
        if cursor < len(body) and body[cursor] == "[":
            value, cursor = _group(body, cursor, "[", "]")
            item_label = tuple(_inline(value or "", diagnostics))
        content = body[cursor:end].strip()
        children = _blocks(content, diagnostics)
        if not children and content:
            children = (Paragraph(tuple(_inline(content, diagnostics))),)
        items.append(ListItem(tuple(children), level=0, numfmt="decimal" if ordered else "bullet", label=item_label))
    return ListBlock(tuple(items), ordered=ordered, description=description, label=label, start=start)


def _split_top(source, delimiter):
    parts, start, depth, env_depth, math = [], 0, 0, 0, False
    index = 0
    while index < len(source):
        if source[index] == "\\":
            if source.startswith(r"\begin{", index):
                _, index = _group(source, index + len(r"\begin"))
                env_depth += 1
                continue
            if source.startswith(r"\end{", index):
                _, index = _group(source, index + len(r"\end"))
                env_depth = max(0, env_depth - 1)
                continue
            index += 2
            continue
        if source[index] == "{" and not math:
            depth += 1
        elif source[index] == "}" and not math:
            depth = max(0, depth - 1)
        elif source[index] == "$" and depth == 0:
            math = not math
        elif source.startswith(delimiter, index) and depth == 0 and env_depth == 0 and not math:
            parts.append(source[start:index])
            start = index + len(delimiter)
            index = start
            continue
        index += 1
    parts.append(source[start:])
    return parts


def _table_rows(body):
    rows, start, depth, env_depth, math = [], 0, 0, 0, False
    index = 0
    while index < len(body):
        if body[index] == "\\":
            if body.startswith(r"\begin{", index):
                _, index = _group(body, index + len(r"\begin"))
                env_depth += 1
                continue
            if body.startswith(r"\end{", index):
                _, index = _group(body, index + len(r"\end"))
                env_depth = max(0, env_depth - 1)
                continue
            if body.startswith(r"\\", index) and not depth and not env_depth and not math:
                after = body[index + 2:]
                if not after or after[0].isspace() or after.lstrip().startswith(r"\hline"):
                    rows.append(body[start:index])
                    start = index + 2
                    index = start
                    continue
            index += 2
            continue
        if body[index] == "{" and not math:
            depth += 1
        elif body[index] == "}" and not math:
            depth = max(0, depth - 1)
        elif body[index] == "$" and not depth:
            math = not math
        index += 1
    rows.append(body[start:])
    return rows


def _table(body, diagnostics):
    rows = []
    borders = []
    for raw_row in _table_rows(body.strip()):
        if not raw_row.strip():
            continue
        rules = tuple(_TABLE_RULE.finditer(raw_row))
        leading_rule = bool(rules) and not raw_row[:rules[0].start()].strip()
        trailing_rule = bool(rules) and not raw_row[rules[-1].end():].strip()
        raw_row = _TABLE_RULE.sub("", raw_row).strip()
        if leading_rule and raw_row:
            borders.append("top" if not rows else "inside")
        if trailing_rule:
            borders.append("bottom")
        if not raw_row:
            continue
        cells = []
        for raw_cell in _split_top(raw_row, "&"):
            text = raw_cell.strip()
            shading = None
            if text.startswith(r"\cellcolor"):
                shading, after = _group(text, len(r"\cellcolor"))
                if shading is not None:
                    text = text[after:].lstrip()
            col_span = row_span = 1
            while True:
                match = re.match(r"\\multicolumn\{(\d+)\}\{[^{}]*\}\{(.*)\}\s*$", text, re.S)
                if match:
                    col_span, text = int(match.group(1)), match.group(2)
                    continue
                match = re.match(r"\\multirow\{(\d+)\}\{[^{}]*\}\{(.*)\}\s*$", text, re.S)
                if match:
                    row_span, text = int(match.group(1)), match.group(2)
                    continue
                break
            if text.startswith(r"\cellcolor"):
                inner_shading, after = _group(text, len(r"\cellcolor"))
                if inner_shading is not None:
                    shading = shading or inner_shading
                    text = text[after:].lstrip()
            if text.startswith(r"\parbox"):
                _, after = _group(text, len(r"\parbox"))
                content, _ = _group(text, after)
                if content is not None:
                    text = content
            if text == r"\mbox{}":
                children = ()
            else:
                children = _blocks(text, diagnostics) or ((Paragraph(tuple(_inline(text, diagnostics))),) if text else ())
            cells.append(Cell(tuple(children), row_span=row_span, col_span=col_span, shading=shading.strip() if shading else None))
        rows.append(Row(tuple(cells)))
    return Table(tuple(rows), borders=tuple(dict.fromkeys(borders)))


def _next_boundary(source, start):
    candidates = []
    depth, math, index = 0, False, start
    while index < len(source):
        if source.startswith(r"\[", index):
            math = True
            index += 2
            continue
        if source.startswith(r"\]", index):
            math = False
            index += 2
            continue
        if source.startswith("$$", index):
            math = not math
            index += 2
            continue
        if source[index] == "$":
            math = not math
            index += 1
            continue
        if not depth and not math:
            heading = _HEADING.match(source, index)
            environment = _ENV.match(source, index)
            if heading:
                candidates.append(index)
                break
            if environment:
                candidates.append(index)
                break
            if source.startswith(r"\newpage", index) or source.startswith(r"\tableofcontents", index):
                candidates.append(index)
                break
        if source[index] == "\\":
            index += 2
            continue
        if not math and source[index] == "{":
            depth += 1
        elif not math and source[index] == "}":
            depth = max(0, depth - 1)
        index += 1
    blank = re.search(r"\n\s*\n", source[start:])
    if blank:
        candidates.append(start + blank.start())
    return min(candidates, default=len(source))


def _environment_options(source, end):
    if end < len(source) and source[end] == "[":
        return _group(source, end, "[", "]")
    return None, end


def _display_math(source, position, diagnostics):
    marker = r"\[" if source.startswith(r"\[", position) else "$$"
    closing = r"\]" if marker == r"\[" else "$$"
    start = position + len(marker)
    end = source.find(closing, start)
    if end < 0:
        diagnostics.append(_diagnostic("invalid-input", "unclosed math", position))
        return None
    return Paragraph((Math(source[start:end].strip(), True),)), end + len(closing)


def _heading_block(source, position, diagnostics):
    heading = _HEADING.match(source, position)
    if not heading:
        return None
    title, end = _group(source, heading.end() - 1)
    if title is None:
        diagnostics.append(_diagnostic("broken-environment", "unclosed heading", position))
        return None
    level = {"section": 1, "subsection": 2, "subsubsection": 3, "paragraph": 4}[heading.group(1)]
    return Paragraph(tuple(_inline(title, diagnostics, position)), format=ParagraphFormat(heading_level=level)), end


def _environment_block(source, position, diagnostics, match):
    name, body_start = match.group(1), match.end()
    if name in {"tabular", "tabular*", "multicols", "multicols*"} and body_start < len(source) and source[body_start] == "{":
        _, body_start = _group(source, body_start)
    options, body_start = _environment_options(source, body_start)
    body, end = _environment(source, body_start, name)
    if body is None:
        diagnostics.append(_diagnostic("broken-environment", f"unclosed environment {name}", position))
        return None
    option_values = {}
    for item in (options or "").split(","):
        if "=" in item:
            key, value = item.split("=", 1)
            option_values[key.strip()] = value.strip()
    if name in {"itemize", "enumerate", "description"}:
        value = option_values.get("start", "")
        return _list_items(body, diagnostics, name == "enumerate", name == "description", option_values.get("label"), int(value) if value.isdigit() else None), end
    if name in {"quote", "quotation"}:
        return Quote(_blocks(body, diagnostics), name), end
    if name in {"center", "flushleft", "flushright", "justify"}:
        children = _blocks(body, diagnostics)
        alignment = {"center": "center", "flushleft": "left", "flushright": "right", "justify": "justify"}[name]
        if not children or body.strip() in {r"\mbox{}\par", ""}:
            children = (Paragraph((), format=ParagraphFormat(alignment=alignment)),)
        else:
            children = tuple(replace(child, format=replace(child.format, alignment=alignment)) if isinstance(child, Paragraph) else child for child in children)
        return children, end
    if name in {"multicols", "multicols*"}:
        children = list(_blocks(options, diagnostics)) if options else []
        children.extend(_blocks(body, diagnostics))
        return tuple(children), end
    if name in {"tabular", "tabular*"}:
        return _table(body, diagnostics), end
    if name in {"figure", "figure*"}:
        caption, caption_match = (), re.search(r"\\caption\s*\{", body)
        if caption_match:
            caption_text, caption_end = _group(body, caption_match.end() - 1)
            caption = tuple(_inline(caption_text or "", diagnostics, position))
            body = body[:caption_match.start()] + body[caption_end:]
        inline = _inline(body, diagnostics, position)
        image = next((child for child in inline if isinstance(child, ImageInline)), None)
        return ImageBlock(image.spec if image else ImageSpec(), tuple(caption)), end
    if name in {"equation", "equation*", "align", "align*", "gather", "gather*"}:
        return Paragraph((Math(body.strip(), True),)), end
    if name == "verbatim":
        return Paragraph((Text(body),)), end
    diagnostics.append(_diagnostic("invalid-input", f"unsupported block environment {name}", position))
    return (), end


def _blocks(source, diagnostics):
    result, position = [], 0
    while position < len(source):
        while position < len(source) and source[position].isspace():
            position += 1
        if position >= len(source):
            break
        if source.startswith((r"\[", "$$"), position):
            parsed = _display_math(source, position, diagnostics)
            if parsed is None:
                break
            block, position = parsed
            result.append(block)
            continue
        parsed = _heading_block(source, position, diagnostics)
        if parsed is not None:
            block, position = parsed
            result.append(block)
            continue
        if source.startswith(r"\newpage", position):
            result.append(SectionBreak())
            position += len(r"\newpage")
            continue
        if source.startswith(r"\mbox{}\par", position):
            result.append(Paragraph(()))
            position += len(r"\mbox{}\par")
            continue
        environment = _ENV.match(source, position)
        if environment:
            parsed = _environment_block(source, position, diagnostics, environment)
            if parsed is None:
                break
            block, position = parsed
            result.extend(block if isinstance(block, tuple) else (block,))
            continue
        end = _next_boundary(source, position)
        content = source[position:end].strip()
        if content:
            result.append(Paragraph(tuple(_inline(content, diagnostics, position))))
        position = end if end > position else position + 1
    return tuple(result)


def parse_with_diagnostics(source: str):
    """Parse native LaTeX and return the model plus typed diagnostics."""
    diagnostics = []
    source = _strip_comments(source)
    begin = source.find(r"\begin{document}")
    end = source.rfind(r"\end{document}")
    start = begin + len(r"\begin{document}") if begin >= 0 else 0
    body = source[start:end if end >= 0 else len(source)]
    return Document(_blocks(body, diagnostics)), tuple(diagnostics)


def parse(source: str, diagnostics=None) -> Document:
    """Parse native LaTeX into the format-neutral document model."""
    document, found = parse_with_diagnostics(source)
    if diagnostics is not None:
        diagnostics.extend(found)
    return document


__all__ = ["parse", "parse_with_diagnostics"]
