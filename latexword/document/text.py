"""Shared LaTeX escaping for document prose and hyperlink fields."""

import re


PROSE_ESCAPE_CHARS = {
    "\\": "\\textbackslash{}", "{": "\\{", "}": "\\}", "$": "\\$",
    "&": "\\&", "#": "\\#", "_": "\\_", "%": "\\%",
    "~": "\\textasciitilde{}", "^": "\\textasciicircum{}",
}
PROSE_REVERSE_REPLACEMENTS = [
    ("\u2014", "---"), ("\u2013", "--"),
    ("\u201c", "``"), ("\u201d", "''"), ("\u00a0", "~"),
]
_ELLIPSIS_RE = re.compile("\u2026")


def prose_escape(text):
    escaped = "".join(PROSE_ESCAPE_CHARS.get(ch, ch) for ch in text)
    escaped = _ELLIPSIS_RE.sub("\\\\ldots{}", escaped)
    for ch, replacement in PROSE_REVERSE_REPLACEMENTS:
        escaped = escaped.replace(ch, replacement)
    return escaped


def prose_unescape(text):
    """Interpret the canonical TeX prose spellings emitted by prose_escape."""

    return (
        text.replace("---", "\u2014").replace("--", "\u2013")
        .replace("``", "\u201c").replace("''", "\u201d")
        .replace("~", "\u00a0")
    )


def href_escape(url):
    """Escape a hyperlink argument without applying prose substitutions."""
    return "".join(PROSE_ESCAPE_CHARS.get(ch, ch) for ch in url)


_HREF_UNESCAPE_SEQUENCES = sorted(
    ((value, char) for char, value in PROSE_ESCAPE_CHARS.items()),
    key=lambda item: len(item[0]), reverse=True,
)


def href_unescape(text):
    """Undo the exact escapes emitted by :func:`href_escape`."""
    out = []
    i = 0
    while i < len(text):
        if text[i] == "\\":
            for sequence, char in _HREF_UNESCAPE_SEQUENCES:
                if text.startswith(sequence, i):
                    out.append(char)
                    i += len(sequence)
                    break
            else:
                out.append(text[i])
                i += 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)
