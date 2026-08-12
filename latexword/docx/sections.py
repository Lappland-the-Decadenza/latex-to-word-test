"""Section-layout readers used by the reverse document pipeline."""

from ..math.omml2latex import ln, qw


def section_columns(sectpr):
    """Return the column count declared by one ``w:sectPr``."""
    if sectpr is None:
        return 1
    cols = sectpr.find(qw("cols"))
    if cols is None:
        return 1
    num = cols.get(qw("num"))
    if num and num.isdigit():
        return max(1, int(num))
    return max(1, len(cols.findall(qw("col"))))


def column_layout(children, body):
    """Return the section column count applying to each body child.

    Word stores a section's properties on the last paragraph in that
    section, so a boundary applies forward from the preceding block.
    """
    out = [1] * len(children)
    start = 0
    for idx, element in enumerate(children):
        if ln(element) != "p":
            continue
        ppr = element.find(qw("pPr"))
        sectpr = ppr.find(qw("sectPr")) if ppr is not None else None
        if sectpr is None:
            continue
        columns = section_columns(sectpr)
        for position in range(start, idx + 1):
            out[position] = columns
        start = idx + 1
    trailing = section_columns(body.find(qw("sectPr")))
    for position in range(start, len(children)):
        out[position] = trailing
    return out
