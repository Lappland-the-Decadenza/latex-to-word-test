"""DOCX table topology and reverse rendering.

The paragraph renderer is injected so this module owns table geometry without
owning inline or document-level LaTeX policy.
"""

import hashlib
import re

from ..document.identity import NodeId
from ..document.text import prose_escape as _prose_escape


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{" + W_NS + "}"
TWIPS_PER_CM = 1440 / 2.54
NO_BORDER = {"none", "nil"}


def _q(name):
    return W + name


def _ln(element):
    return element.tag.rsplit("}", 1)[-1]


def _cell_grid_plan(tbl):
    rows = []
    for tr in tbl.findall(_q("tr")):
        plan = []
        col = 0
        for tc in tr.findall(_q("tc")):
            tcpr = tc.find(_q("tcPr"))
            span = 1
            vm = None
            if tcpr is not None:
                gs = tcpr.find(_q("gridSpan"))
                if gs is not None:
                    try:
                        span = max(1, int(gs.get(_q("val")) or 1))
                    except ValueError:
                        pass
                vme = tcpr.find(_q("vMerge"))
                if vme is not None:
                    vm = vme.get(_q("val")) or "continue"
            plan.append((col, span, tc, vm))
            col += span
        rows.append(plan)
    return rows


def _border_on(element):
    return element is not None and (
        (element.get(_q("val")) or "single").strip().lower() not in NO_BORDER
    )


def _table_rules(tbl, plan):
    tblpr = tbl.find(_q("tblPr"))
    borders = tblpr.find(_q("tblBorders")) if tblpr is not None else None

    def edge(name):
        return _border_on(borders.find(_q(name)) if borders is not None else None)

    top, bottom = edge("top"), edge("bottom")
    inside_h, inside_v = edge("insideH"), edge("insideV")
    left, right = edge("left"), edge("right")
    nrows = len(plan)
    ncols = max((row[-1][0] + row[-1][1] for row in plan), default=0)
    for row_index, row in enumerate(plan):
        for col, span, tc, _vm in row:
            tcpr = tc.find(_q("tcPr"))
            cell_borders = (
                tcpr.find(_q("tcBorders")) if tcpr is not None else None
            )

            def cell_edge(name):
                return _border_on(
                    cell_borders.find(_q(name))
                    if cell_borders is not None
                    else None
                )

            if cell_edge("top"):
                top = top or row_index == 0
                inside_h = inside_h or row_index > 0
            if cell_edge("bottom"):
                bottom = bottom or row_index == nrows - 1
                inside_h = inside_h or row_index < nrows - 1
            if cell_edge("left"):
                left = left or col == 0
                inside_v = inside_v or col > 0
            if cell_edge("right"):
                right = right or col + span == ncols
                inside_v = inside_v or col + span < ncols
    return top, bottom, inside_h, left, right, inside_v


def _table_dimensions(tbl):
    grid = tbl.find(_q("tblGrid"))
    cols = len(grid.findall(_q("gridCol"))) if grid is not None else 0
    width_twips = 0
    if grid is not None:
        for grid_col in grid.findall(_q("gridCol")):
            try:
                width_twips += int(grid_col.get(_q("w")) or 0)
            except ValueError:
                pass
    rows = tbl.findall(_q("tr"))
    if cols == 0:
        cols = max((len(row.findall(_q("tc"))) for row in rows), default=0)
    height_twips = 0
    for row in rows:
        row_pr = row.find(_q("trPr"))
        height = row_pr.find(_q("trHeight")) if row_pr is not None else None
        try:
            height_twips += int(height.get(_q("val")) or 0) if height is not None else 0
        except ValueError:
            pass
    return len(rows), cols, width_twips, height_twips


def _cell_width_cm(tc, grid_widths, start_col, span):
    tcpr = tc.find(_q("tcPr"))
    if tcpr is not None:
        tcw = tcpr.find(_q("tcW"))
        if tcw is not None and tcw.get(_q("type")) in (None, "dxa"):
            try:
                value = int(tcw.get(_q("w")) or 0)
            except ValueError:
                value = 0
            if value > 0:
                return value / TWIPS_PER_CM
    total = sum(grid_widths[start_col:start_col + span])
    return total / TWIPS_PER_CM if total > 0 else 4.0


def _render_cell_text(
    tc,
    warnings,
    rels,
    img_ctx,
    index,
    paragraph_renderer,
    table_renderer,
    style_wrapper,
    notes_ctx,
    comments_ctx,
):
    blocks = [child for child in tc if _ln(child) in ("p", "tbl")]
    paragraphs = [child for child in blocks if _ln(child) == "p"]
    has_break = any(next(paragraph.iter(_q("br")), None) is not None for paragraph in paragraphs)
    rendered = []
    for paragraph_index, paragraph in enumerate(paragraphs):
        rendered_text = paragraph_renderer(
            paragraph, warnings, rels, index, img_ctx, notes_ctx, comments_ctx
        )
        if len(paragraphs) > 1:
            if paragraph_index == 0:
                rendered_text = rendered_text.lstrip()
            elif paragraph_index == len(paragraphs) - 1:
                rendered_text = rendered_text.rstrip()
        else:
            rendered_text = rendered_text.strip()
        rendered.append(rendered_text)

    parts = []
    paragraph_index = 0
    for child in blocks:
        if _ln(child) == "tbl":
            parts.append(
                table_renderer(
                    child,
                    warnings,
                    rels,
                    img_ctx,
                    index,
                    paragraph_renderer=paragraph_renderer,
                    style_wrapper=style_wrapper,
                    notes_ctx=notes_ctx,
                    comments_ctx=comments_ctx,
                )
            )
            continue
        text = rendered[paragraph_index]
        paragraph_index += 1
        if not text:
            continue
        if parts:
            lead = len(text) - len(text.lstrip(" "))
            if lead:
                text = "\\ " * lead + text[lead:]
        parts.append(text)
    text = "\\\\".join(parts)
    alignments = set()
    for paragraph in paragraphs:
        ppr = paragraph.find(_q("pPr"))
        alignment = ppr.find(_q("jc")) if ppr is not None else None
        if alignment is not None:
            alignments.add(alignment.get(_q("val")))
    return text, len(paragraphs), has_break, alignments


def _cell_latex(
    tc,
    start_col,
    span,
    grid_widths,
    warnings,
    rels,
    img_ctx,
    index,
    paragraph_renderer,
    table_renderer,
    style_wrapper,
    notes_ctx,
    comments_ctx,
):
    text, paragraph_count, has_break, alignments = _render_cell_text(
        tc,
        warnings,
        rels,
        img_ctx,
        index,
        paragraph_renderer,
        table_renderer,
        style_wrapper,
        notes_ctx,
        comments_ctx,
    )
    if paragraph_count > 1 or has_break:
        width = _cell_width_cm(tc, grid_widths, start_col, span)
        text = f"\\parbox{{{width:.2f}cm}}{{{text}}}"
    tcpr = tc.find(_q("tcPr"))
    if tcpr is not None:
        shading = tcpr.find(_q("shd"))
        fill = shading.get(_q("fill")) if shading is not None else None
        if fill and fill.strip().lower() not in ("auto",):
            text = f"\\cellcolor{{{fill}}}{text}"
    align = "l"
    if len(alignments) == 1:
        value = next(iter(alignments))
        if value == "center":
            align = "c"
        elif value in ("right", "end"):
            align = "r"
    return text, align


def _row_cell_at(row_plan, col):
    for start, span, tc, vmerge in row_plan:
        if start == col:
            return span, tc, vmerge
    return None


def _native_table_fallback(tbl, warnings, index, object_store=None):
    rows, cols, width_twips, height_twips = _table_dimensions(tbl)
    visible = _prose_escape(
        " ".join(node.text or "" for node in tbl.iter(_q("t")))
    )
    if object_store is not None:
        object_id = object_store.capture(tbl, kind="table-shape", context="block")
        object_store.attach(
            "table-shape",
            {"object_id": object_id, "rows": rows, "cols": cols},
            owner_id=NodeId.allocate(max(0, index)),
            owner_semantic_hash=hashlib.sha256(visible.encode("utf-8")).hexdigest(),
            position="inside",
            ordinal=index,
            content_type="application/json",
            object_id=object_id,
        )
    warnings.append(
        f"table at block {index} ({rows}x{cols}) has a shape plain tabular "
        "cannot spell (nested table or display math in a cell); visible "
        "native fallback kept and exact structure is in the sidecar"
    )
    return f"\\begin{{quote}}{visible}\\end{{quote}}"


def _table_row_to_latex(
    plan,
    row_index,
    row,
    nrows,
    grid_widths,
    warnings,
    rels,
    img_ctx,
    index,
    paragraph_renderer,
    style_wrapper,
    notes_ctx,
    comments_ctx,
):
    cells = []
    cell_index = 0
    while cell_index < len(row):
        col, span, tc, vmerge = row[cell_index]
        cell_text, align = _cell_latex(
            tc, col, span, grid_widths, warnings, rels, img_ctx,
            index, paragraph_renderer, table_to_latex, style_wrapper,
            notes_ctx, comments_ctx,
        )
        if vmerge == "continue":
            content_only = re.sub(r"\\cellcolor\{[^{}]*\}", "", cell_text)
            if content_only.strip():
                cell_text = ""
                warnings.append(
                    f"vMerge continue cell at row {row_index} has content; "
                    "the merge start's cell carries the text"
                )
            fill = ""
            tcpr = tc.find(_q("tcPr"))
            if tcpr is not None:
                shading = tcpr.find(_q("shd"))
                value = shading.get(_q("fill")) if shading is not None else None
                if value and value.strip().lower() != "auto":
                    fill = f"\\cellcolor{{{value}}}"
            cells.append(
                f"\\multicolumn{{{span}}}{{l}}{{{fill}}}"
                if span > 1 else fill
            )
        else:
            if vmerge == "restart":
                count = 1
                while row_index + count < nrows:
                    following = _row_cell_at(plan[row_index + count], col)
                    if following is None or following[2] != "continue":
                        break
                    count += 1
                if count > 1:
                    cell_text = f"\\multirow{{{count}}}{{*}}{{{cell_text}}}"
            if span > 1:
                cell_text = f"\\multicolumn{{{span}}}{{{align}}}{{{cell_text}}}"
            cells.append(cell_text)
        cell_index += 1
    return " & ".join(cells) + " \\\\"


def table_to_latex(
    tbl,
    warnings,
    rels,
    img_ctx,
    index,
    *,
    paragraph_renderer,
    style_wrapper,
    notes_ctx=None,
    comments_ctx=None,
    object_store=None,
):
    plan = _cell_grid_plan(tbl)
    for row in plan:
        for _col, _span, tc, _vm in row:
            if any(_ln(child) not in ("tcPr", "p", "tbl") for child in tc):
                return _native_table_fallback(tbl, warnings, index, object_store)
    nrows = len(plan)
    ncols = max((row[-1][0] + row[-1][1] for row in plan), default=0)
    grid = tbl.find(_q("tblGrid"))
    grid_widths = []
    if grid is not None:
        for grid_col in grid.findall(_q("gridCol")):
            try:
                grid_widths.append(int(grid_col.get(_q("w")) or 0))
            except ValueError:
                grid_widths.append(0)
    top, bottom, inside_h, left, right, vlines = _table_rules(tbl, plan)

    row_texts = []
    for row_index, row in enumerate(plan):
        row_texts.append(
            _table_row_to_latex(
                plan,
                row_index,
                row,
                nrows,
                grid_widths,
                warnings,
                rels,
                img_ctx,
                index,
                paragraph_renderer,
                style_wrapper,
                notes_ctx,
                comments_ctx,
            )
        )

    parts = ["l"] * ncols
    colspec = (
        ("|" if left else "") + "|".join(parts) + ("|" if right else "")
        if vlines else
        ("|" if left else "") + "".join(parts) + ("|" if right else "")
    )
    lines = [f"\\begin{{tabular}}{{{colspec}}}"]
    if top:
        lines.append("\\hline")
    for row_index, row_text in enumerate(row_texts):
        if row_index > 0 and inside_h:
            lines.append("\\hline")
        lines.append(row_text)
    if bottom:
        lines.append("\\hline")
    lines.append("\\end{tabular}")
    output = "\n".join(lines)

    tblpr = tbl.find(_q("tblPr"))
    style_id = None
    if tblpr is not None:
        style = tblpr.find(_q("tblStyle"))
        if style is not None:
            style_id = style.get(_q("val")) or None
    return style_wrapper(style_id, output) if style_wrapper else output
