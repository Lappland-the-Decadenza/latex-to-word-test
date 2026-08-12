"""LaTeX table parsing and DOCX table construction.

The functions accept a builder-like object instead of importing ``write``.
That preserves the builder's document/state ownership while keeping table
grammar and OOXML table mechanics outside the public facade.
"""

import re

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm
from docx.table import _Cell

from .inline import _find_brace


OMML_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def _tcpr_insert(tcpr, el):
    tcpr.insert_element_before(
        el, "w:tcBorders", "w:shd", "w:noWrap", "w:tcMar",
        "w:textDirection", "w:tcFitText", "w:vAlign",
        "w:hideMark", "w:headers", "w:cellIns", "w:cellDel",
        "w:cellMerge", "w:tcPrChange",
    )


def _set_cell_shading(tcpr, fill):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    _tcpr_insert(tcpr, shd)


def _set_table_borders(table, top, bottom, inside_h, left, right, inside_v):
    if not any((top, bottom, inside_h, left, right, inside_v)):
        return
    tblpr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for name, on in (
        ("top", top), ("left", left), ("bottom", bottom),
        ("right", right), ("insideH", inside_h), ("insideV", inside_v),
    ):
        if on:
            edge = OxmlElement("w:" + name)
            edge.set(qn("w:val"), "single")
            edge.set(qn("w:sz"), "4")
            edge.set(qn("w:space"), "0")
            edge.set(qn("w:color"), "auto")
            borders.append(edge)
    tblpr.insert_element_before(
        borders, "w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook"
    )


def _parse_colspec(colspec):
    s = colspec.strip()
    right = s.endswith("|")
    if right:
        s = s[:-1].rstrip()
    left = s.startswith("|")
    ncols = len(re.findall(r"[lcr]", s))
    inside = "|" in (s[1:] if left else s)
    return ncols, left, right, inside


_HLINE_RE = re.compile(r"\\(?:hline|cline(?:\s*\[[^\]]*\])?\{[^{}]*\})")


def _split_table_rows(body):
    rows = []
    top = inside = bottom = False
    pieces = []
    piece_start = 0
    piece_had_rule = False
    depth = 0
    env_depth = 0
    math = False
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\":
            if body.startswith("\\begin{", i):
                _, i = _find_brace(body, i + len("\\begin"))
                env_depth += 1
                continue
            if body.startswith("\\end{", i):
                _, i = _find_brace(body, i + len("\\end"))
                env_depth = max(0, env_depth - 1)
                continue
            if not math and depth == 0 and env_depth == 0:
                match = _HLINE_RE.match(body, i)
                if match:
                    piece_had_rule = True
                    i = match.end()
                    piece_start = i
                    continue
            if body[i:i + 2] == "\\\\" and not math and depth == 0 and env_depth == 0:
                pieces.append((body[piece_start:i], piece_had_rule))
                piece_start = i + 2
                piece_had_rule = False
                i += 2
                continue
            i += 2 if body[i:i + 2] == "\\\\" else 1
            continue
        if ch == "{" and not math:
            depth += 1
        elif ch == "}" and not math:
            depth = max(0, depth - 1)
        elif ch == "$" and depth == 0:
            math = not math
        i += 1
    pieces.append((body[piece_start:], piece_had_rule))
    for idx, (text, has_rule) in enumerate(pieces):
        if idx == 0 and has_rule:
            top = True
        elif has_rule and idx == len(pieces) - 1:
            bottom = True
        elif has_rule:
            inside = True
        text = text.strip()
        if text:
            rows.append(text)
    return rows, top, inside, bottom


def _split_row_cells(row):
    cells = []
    depth = 0
    math = False
    env_depth = 0
    start = 0
    i = 0
    while i < len(row):
        ch = row[i]
        if ch == "\\":
            if row.startswith("\\begin{", i):
                _, i = _find_brace(row, i + len("\\begin"))
                env_depth += 1
                continue
            if row.startswith("\\end{", i):
                _, i = _find_brace(row, i + len("\\end"))
                env_depth = max(0, env_depth - 1)
                continue
            i += 2 if row[i:i + 2] == "\\\\" else 1
            continue
        if ch == "{" and not math:
            depth += 1
        elif ch == "}" and not math:
            depth = max(0, depth - 1)
        elif ch == "$" and depth == 0:
            math = not math
        elif ch == "&" and not math and depth == 0 and env_depth == 0:
            cells.append(row[start:i].strip())
            start = i + 1
        i += 1
    cells.append(row[start:].strip())
    return cells


def _parse_cell(s):
    spec = {
        "shading": None, "vmerge": None, "span": 1, "align": None,
        "parbox_w": None, "text": "",
    }
    s = s.strip()
    if s.startswith("\\cellcolor{"):
        fill, after = _find_brace(s, len("\\cellcolor"))
        if fill is not None:
            spec["shading"] = fill.strip()
            s = s[after:].lstrip()
    if s.startswith("\\multirow{"):
        n, after = _find_brace(s, len("\\multirow"))
        _, after = _find_brace(s, after)
        content, after = _find_brace(s, after)
        if n is not None and content is not None:
            try:
                spec["vmerge"] = max(1, int(n.strip()))
            except ValueError:
                pass
            inner = _parse_cell(content)
            for key in ("shading", "span", "align", "parbox_w", "text"):
                if inner[key]:
                    spec[key] = inner[key]
            s = s[after:].lstrip()
    if s.startswith("\\multicolumn{"):
        n, after = _find_brace(s, len("\\multicolumn"))
        align, after = _find_brace(s, after)
        content, after = _find_brace(s, after)
        if n is not None and content is not None:
            try:
                spec["span"] = max(1, int(n.strip()))
            except ValueError:
                pass
            if align:
                spec["align"] = align.strip()
            inner = _parse_cell(content)
            for key in ("shading", "parbox_w", "text", "vmerge"):
                if inner[key]:
                    spec[key] = inner[key]
            s = s[after:].lstrip()
    if s.startswith("\\parbox{"):
        width, after = _find_brace(s, len("\\parbox"))
        content, after = _find_brace(s, after)
        if width is not None and content is not None:
            spec["parbox_w"] = width.strip()
            spec["text"] = content
            return spec
    if s:
        spec["text"] = s
    return spec


def _find_env_end(text, env, start):
    begin = re.compile(r"\\begin\{" + re.escape(env) + r"\}")
    end = re.compile(r"\\end\{" + re.escape(env) + r"\}")
    depth = 0
    pos = start
    while pos < len(text):
        mb = begin.search(text, pos)
        me = end.search(text, pos)
        if me is None:
            return -1, -1
        if mb is not None and mb.start() < me.start():
            depth += 1
            pos = mb.end()
            continue
        if depth == 0:
            return me.start(), me.end()
        depth -= 1
        pos = me.end()
    return -1, -1


def _append_cell_math(paragraph, tex, math_renderer, warnings):
    if math_renderer is None:
        if warnings is not None:
            warnings.append("display math in table cell has no renderer")
        return
    try:
        omml = math_renderer(tex, warnings)
    except Exception as exc:  # pragma: no cover - defensive boundary
        if warnings is not None:
            warnings.append(f"display math in table cell failed ({exc})")
        return
    omath_para = OxmlElement("m:oMathPara")
    pr = OxmlElement("m:oMathParaPr")
    jc = OxmlElement("m:jc")
    jc.set(qn("m:val"), "center")
    pr.append(jc)
    omath_para.append(pr)
    omath_para.append(omml)
    paragraph._p.append(omath_para)


def _render_cell_content(builder, cell, text, inline_renderer,
                         math_renderer):
    """Render cell prose, display math and nested tabular blocks in order."""
    paragraph = cell.paragraphs[0]
    pos = 0
    first = True
    tokens = re.compile(r"\\begin\{(tabular\*?)\}|\\\[|\$\$")
    while pos < len(text):
        match = tokens.search(text, pos)
        if match is None:
            tail = text[pos:]
            if tail and (tail.strip() or first):
                inline_renderer(
                    paragraph, tail, None, builder.warnings, builder.img_base,
                )
            break
        prefix = text[pos:match.start()]
        if prefix.strip():
            inline_renderer(
                paragraph, prefix, None, builder.warnings, builder.img_base,
            )
            first = False
        token = match.group(0)
        if token.startswith("\\begin"):
            env = match.group(1)
            end_start, end_stop = _find_env_end(text, env, match.end())
            if end_start < 0:
                builder.warnings.append(
                    f"unterminated nested table environment {env}"
                )
                inline_renderer(
                    paragraph, text[match.start():], None,
                    builder.warnings, builder.img_base,
                )
                break
            handle_tabular(
                builder, text[match.end():end_start], None, inline_renderer,
                math_renderer=math_renderer, container=cell,
            )
            paragraph = cell.add_paragraph()
            first = True
            pos = end_stop
            continue
        if token == "\\[":
            end = text.find("\\]", match.end())
            end = len(text) if end < 0 else end
            _append_cell_math(
                paragraph, text[match.end():end], math_renderer, builder.warnings,
            )
            pos = min(len(text), end + 2)
            first = False
            continue
        end = text.find("$$", match.end())
        end = len(text) if end < 0 else end
        _append_cell_math(
            paragraph, text[match.end():end], math_renderer, builder.warnings,
        )
        pos = min(len(text), end + 2)
        first = False


def _mark_cell(cell, written):
    written.add(cell._tc)
    cell.text = ""


def _populate_table(builder, table, row_strs, ncols, inline_renderer,
                    math_renderer):
    def cell_at(row, col):
        tr = table.rows[row]._tr
        return _Cell(tr.findall(qn("w:tc"))[col], table)

    pending = {}
    for row, row_s in enumerate(row_strs):
        specs = []
        cursor = 0
        for cell_s in _split_row_cells(row_s):
            spec = _parse_cell(cell_s)
            specs.append((cursor, spec))
            cursor += spec["span"]
        specmap = dict(specs)
        written = set()
        col = 0
        while col < ncols:
            pending_merge = pending.get(col)
            if pending_merge is not None:
                rows_left, span = pending_merge
                cell = cell_at(row, col)
                _mark_cell(cell, written)
                tcpr = cell._tc.get_or_add_tcPr()
                _tcpr_insert(tcpr, OxmlElement("w:vMerge"))
                if span > 1:
                    tcpr.get_or_add_gridSpan().val = span
                spec = specmap.get(col)
                if spec is not None and spec["shading"]:
                    _set_cell_shading(tcpr, spec["shading"])
                if spec is not None and spec["text"]:
                    builder.warnings.append(
                        f"multirow continuation at row {row} has content; "
                        "the merge start's cell carries the text"
                    )
                rows_left -= 1
                if rows_left <= 0:
                    del pending[col]
                else:
                    pending[col] = (rows_left, span)
                col += span
                continue
            spec = specmap.get(col)
            if spec is None:
                cell = cell_at(row, col)
                _mark_cell(cell, written)
                col += 1
                continue
            span = spec["span"]
            cell = cell_at(row, col)
            _mark_cell(cell, written)
            tcpr = cell._tc.get_or_add_tcPr()
            if spec["shading"]:
                _set_cell_shading(tcpr, spec["shading"])
            if span > 1:
                tcpr.get_or_add_gridSpan().val = span
            if spec["vmerge"] and spec["vmerge"] > 1:
                vme = OxmlElement("w:vMerge")
                vme.set(qn("w:val"), "restart")
                _tcpr_insert(tcpr, vme)
                pending[col] = (spec["vmerge"] - 1, span)
            if spec["align"] == "c":
                cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            elif spec["align"] == "r":
                cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
            if spec["parbox_w"]:
                try:
                    cell.width = Cm(float(spec["parbox_w"].rstrip("cm ")))
                except ValueError:
                    builder.warnings.append(
                        f"malformed \\parbox width {spec['parbox_w']!r}"
                    )
            if spec["text"] and inline_renderer is not None:
                _render_cell_content(
                    builder, cell, spec["text"], inline_renderer, math_renderer,
                )
            col += span
        for tc in table.rows[row]._tr.findall(qn("w:tc")):
            if tc not in written:
                tc.getparent().remove(tc)


def handle_tabular(builder, content, pstyle_id=None, inline_renderer=None,
                   *, math_renderer=None, container=None):
    pos = 0
    if pos < len(content) and content[pos] == "{":
        probe, after = _find_brace(content, pos)
        if probe is not None and re.fullmatch(r"[lcr|\s]*", probe or ""):
            colspec, pos = probe, after
        else:
            _, pos = _find_brace(content, pos)
            colspec, pos = _find_brace(content, pos)
    else:
        colspec, pos = _find_brace(content, pos)
    ncols, left_v, right_v, inside_v = _parse_colspec(colspec or "")
    row_strs, top_r, inside_r, bottom_r = _split_table_rows(content[pos:])
    if ncols == 0:
        ncols = max((len(_split_row_cells(row)) for row in row_strs), default=1)
    nrows = len(row_strs) or 1
    owner = container if container is not None else builder.doc
    table = owner.add_table(rows=nrows, cols=ncols)
    if pstyle_id is None:
        pstyle_id = builder._sidecar_table_style()
    if pstyle_id:
        builder._bind_table_style(table, pstyle_id)
    _set_table_borders(table, top_r, bottom_r, inside_r, left_v, right_v, inside_v)

    _populate_table(
        builder, table, row_strs, ncols, inline_renderer, math_renderer,
    )
    builder._last_para = None
