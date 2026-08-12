"""The single Word numbering owner."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

from ..math.omml2latex import qw
from ..document.identity import NodeId


NUMFMT_TO_LABEL = {
    "decimal": "\\arabic*.",
    "lowerLetter": "\\alph*.",
    "upperLetter": "\\Alph*.",
    "lowerRoman": "\\roman*.",
    "upperRoman": "\\Roman*.",
}
LABEL_TO_NUMFMT = {value: key for key, value in NUMFMT_TO_LABEL.items()}
NUMFMT_TO_COUNTER = {
    "decimal": r"\arabic*",
    "lowerLetter": r"\alph*",
    "upperLetter": r"\Alph*",
    "lowerRoman": r"\roman*",
    "upperRoman": r"\Roman*",
}
ENUM_DEFAULT_NUMFMT_BY_DEPTH = {
    1: "decimal", 2: "lowerLetter", 3: "lowerRoman", 4: "upperLetter",
}
BULLET_LEVELS = (("\uf0b7", "Symbol"), ("o", "Courier New"),
                 ("\uf0a7", "Wingdings"))
ENUM_COUNTER_NAMES = (
    "enumi", "enumii", "enumiii", "enumiv", "enumv", "enumvi",
    "enumvii", "enumviii", "enumix",
)
_LABEL_COUNTER_RE = re.compile(
    r"\\(arabic|alph|Alph|roman|Roman)"
    r"\{(enumi|enumii|enumiii|enumiv|enumv|enumvi|enumvii|enumviii|enumix)\}"
)
_LABEL_PLACEHOLDER_RE = re.compile(r"%([1-9][0-9]*)")
_COUNTER_TO_NUMFMT = {
    "arabic": "decimal", "alph": "lowerLetter", "Alph": "upperLetter",
    "roman": "lowerRoman", "Roman": "upperRoman",
}


@dataclass(frozen=True)
class ListLevel:
    """Effective Word list format plus its authored marker template."""

    numfmt: str
    lvl_text: str | None = None


def as_list_level(value):
    """Normalize legacy format strings at the DOCX/LaTeX seam."""
    if isinstance(value, ListLevel):
        return value
    return ListLevel(value or "bullet")


def _counter_name(index):
    return ENUM_COUNTER_NAMES[min(max(index, 1), len(ENUM_COUNTER_NAMES)) - 1]


def _counter_macro(numfmt, index):
    macro = NUMFMT_TO_COUNTER.get(numfmt, r"\arabic*")
    return macro.replace("*", "{" + _counter_name(index) + "}")


def _placeholder_numfmt(index):
    return ENUM_DEFAULT_NUMFMT_BY_DEPTH.get(index, "decimal")


def parse_list_label(label, word_level=None):
    """Resolve an enumitem label into a format and marker declaration."""
    label = label or ""
    if label in LABEL_TO_NUMFMT:
        return ListLevel(LABEL_TO_NUMFMT[label])
    counters = list(_LABEL_COUNTER_RE.finditer(label))
    if counters:
        current_name = _counter_name((word_level or 0) + 1)
        current = next(
            (match for match in reversed(counters)
             if match.group(2) == current_name),
            counters[-1],
        )
        return ListLevel(_COUNTER_TO_NUMFMT[current.group(1)], label)
    for numfmt, counter in NUMFMT_TO_COUNTER.items():
        if label.startswith(counter):
            return ListLevel(numfmt, label)
    if label:
        return ListLevel("bullet", label)
    return None


def latex_label(level, word_level=0, enum_depth=None):
    """Return the enumitem spelling for one effective list level."""
    spec = as_list_level(level)
    if spec.lvl_text is None:
        return NUMFMT_TO_LABEL.get(spec.numfmt)
    if spec.numfmt == "bullet":
        return spec.lvl_text or None
    current_index = enum_depth or word_level + 1
    return _LABEL_PLACEHOLDER_RE.sub(
        lambda match: _counter_macro(
            spec.numfmt if int(match.group(1)) == current_index
            else _placeholder_numfmt(int(match.group(1))),
            int(match.group(1)),
        ),
        spec.lvl_text,
    )


def word_label(level, word_level):
    """Return the Word marker text to write for one abstract level."""
    spec = as_list_level(level)
    if spec.lvl_text is not None:
        label = _LABEL_COUNTER_RE.sub(
            lambda match: f"%{ENUM_COUNTER_NAMES.index(match.group(2)) + 1}",
            spec.lvl_text,
        )
        if spec.numfmt != "bullet":
            label = label.replace(
                NUMFMT_TO_COUNTER.get(spec.numfmt, r"\arabic*"),
                f"%{word_level + 1}",
            )
        return label
    return f"%{word_level + 1}." if spec.numfmt != "bullet" else None


def build_multilevel_abstract_num(abstract_id, numfmt):
    """Build the genuine nine-level numbering definition used by nested lists."""
    spec = as_list_level(numfmt)
    abstract = OxmlElement("w:abstractNum")
    abstract.set(qn("w:abstractNumId"), str(abstract_id))
    multi = OxmlElement("w:multiLevelType")
    multi.set(qn("w:val"), "multilevel")
    abstract.append(multi)
    for level in range(9):
        level_el = OxmlElement("w:lvl")
        level_el.set(qn("w:ilvl"), str(level))
        start_el = OxmlElement("w:start")
        start_el.set(qn("w:val"), "1")
        level_el.append(start_el)
        fmt_el = OxmlElement("w:numFmt")
        fmt_el.set(qn("w:val"), spec.numfmt)
        level_el.append(fmt_el)
        text_el = OxmlElement("w:lvlText")
        bullet_text, bullet_font = BULLET_LEVELS[level % len(BULLET_LEVELS)]
        marker = word_label(spec, level)
        text_el.set(qn("w:val"), marker or bullet_text)
        level_el.append(text_el)
        jc_el = OxmlElement("w:lvlJc")
        jc_el.set(qn("w:val"), "left")
        level_el.append(jc_el)
        ppr_el = OxmlElement("w:pPr")
        ind_el = OxmlElement("w:ind")
        ind_el.set(qn("w:left"), str(720 * (level + 1)))
        ind_el.set(qn("w:hanging"), "360")
        ppr_el.append(ind_el)
        level_el.append(ppr_el)
        if spec.numfmt == "bullet":
            rpr_el = OxmlElement("w:rPr")
            rfonts_el = OxmlElement("w:rFonts")
            rfonts_el.set(qn("w:ascii"), bullet_font)
            rfonts_el.set(qn("w:hAnsi"), bullet_font)
            rpr_el.append(rfonts_el)
            level_el.append(rpr_el)
        abstract.append(level_el)
    return abstract


def ensure_list_numbering(doc, numfmt):
    """Return a cached, noncolliding numbering ID for ``numfmt``."""
    numfmt = as_list_level(numfmt)
    numbering_part = doc.part.numbering_part
    root = numbering_part.element
    cache = getattr(numbering_part, "_doclayer_list_numids", None)
    if cache is None:
        cache = {}
        numbering_part._doclayer_list_numids = cache
    if numfmt in cache:
        return cache[numfmt]
    existing_ids = [
        int(element.get(qn("w:abstractNumId")))
        for element in root.findall(qn("w:abstractNum"))
    ]
    abstract_id = max(existing_ids, default=-1) + 1
    abstract = build_multilevel_abstract_num(abstract_id, numfmt)
    first_num = root.find(qn("w:num"))
    if first_num is not None:
        first_num.addprevious(abstract)
    else:
        root.append(abstract)
    existing_num_ids = [
        int(element.get(qn("w:numId")))
        for element in root.findall(qn("w:num"))
        if element.get(qn("w:numId")) is not None
    ]
    numid = max(existing_num_ids, default=-1) + 1
    num_el = OxmlElement("w:num")
    num_el.set(qn("w:numId"), str(numid))
    abstract_ref = OxmlElement("w:abstractNumId")
    abstract_ref.set(qn("w:val"), str(abstract_id))
    num_el.append(abstract_ref)
    root.append(num_el)
    cache[numfmt] = numid
    return numid


def apply_list_level(doc, paragraph, level, numfmt):
    """Apply direct list membership and nesting depth to a paragraph."""
    numid = ensure_list_numbering(doc, as_list_level(numfmt))
    ppr = paragraph._p.get_or_add_pPr()
    numpr = ppr.get_or_add_numPr()
    numpr.get_or_add_ilvl().val = min(level, 8)
    numpr.get_or_add_numId().val = numid


def read_numbering(z):
    """Resolve ``numId`` and ``ilvl`` to their effective number formats."""
    if "word/numbering.xml" not in z.namelist():
        return {}
    root = etree.fromstring(z.read("word/numbering.xml"))
    abstract = {}
    for element in root.findall(qw("abstractNum")):
        aid = element.get(qw("abstractNumId"))
        levels = {}
        for level in element.findall(qw("lvl")):
            fmt_el = level.find(qw("numFmt"))
            level_id = level.get(qw("ilvl")) or "0"
            marker_el = level.find(qw("lvlText"))
            levels[level_id] = ListLevel(
                fmt_el.get(qw("val")) if fmt_el is not None else "bullet",
                marker_el.get(qw("val")) if marker_el is not None else None,
            )
        abstract[aid] = levels
    out = {}
    for element in root.findall(qw("num")):
        nid = element.get(qw("numId"))
        aid_el = element.find(qw("abstractNumId"))
        aid = aid_el.get(qw("val")) if aid_el is not None else None
        out[nid] = abstract.get(aid, {})
    return out


def read_style_numbering(z):
    """Read numbering attached through paragraph styles."""
    if "word/styles.xml" not in z.namelist():
        return {}
    root = etree.fromstring(z.read("word/styles.xml"))
    out = {}
    for style in root.findall(qw("style")):
        sid = style.get(qw("styleId"))
        ppr = style.find(qw("pPr"))
        numpr = ppr.find(qw("numPr")) if ppr is not None else None
        if numpr is None:
            continue
        numid_el = numpr.find(qw("numId"))
        ilvl_el = numpr.find(qw("ilvl"))
        numid = numid_el.get(qw("val")) if numid_el is not None else None
        ilvl = ilvl_el.get(qw("val")) if ilvl_el is not None else "0"
        if sid:
            out[sid] = (numid, ilvl)
    return out


def paragraph_list_info(ppr, style_id, numbering, style_num):
    """Return ``(environment, level, format)`` for one list paragraph."""
    numpr = ppr.find(qw("numPr")) if ppr is not None else None
    numid = None
    ilvl = "0"
    if numpr is not None:
        numid_el = numpr.find(qw("numId"))
        ilvl_el = numpr.find(qw("ilvl"))
        numid = numid_el.get(qw("val")) if numid_el is not None else None
        ilvl = ilvl_el.get(qw("val")) if ilvl_el is not None else "0"
    if (numid is None or numid == "0") and style_id in style_num:
        numid, ilvl = style_num[style_id]
    if numid and numid != "0":
        fmt = as_list_level(numbering.get(numid, {}).get(ilvl, "bullet"))
        env = "itemize" if fmt.numfmt == "bullet" else "enumerate"
        try:
            level = int(ilvl)
        except (TypeError, ValueError):
            level = 0
        return env, level, fmt
    if style_id in ("ListBullet", "List Bullet", "ListNumber", "List Number"):
        is_bullet = "Bullet" in style_id
        return (
            "itemize" if is_bullet else "enumerate",
            0,
            ListLevel("bullet" if is_bullet else "decimal"),
        )
    return None


def build_nested_list(entries, object_store=None):
    """Convert resolved Word list entries into nested LaTeX environments."""
    lines = []
    stack = []
    enum_depth = 0

    def close_top():
        nonlocal enum_depth
        top_env, _, _ = stack.pop()
        lines.append(f"\\end{{{top_env}}}")
        if top_env == "enumerate":
            enum_depth -= 1

    def open_level(open_env, open_level_num, open_numfmt, placeholder):
        nonlocal enum_depth
        spec = as_list_level(open_numfmt)
        if open_env == "enumerate":
            enum_depth += 1
            default_fmt = ENUM_DEFAULT_NUMFMT_BY_DEPTH.get(enum_depth, "decimal")
            label = latex_label(spec, open_level_num, enum_depth)
            default_label = NUMFMT_TO_LABEL.get(default_fmt)
            if label is not None and (
                spec.numfmt != default_fmt or label != default_label
            ):
                lines.append(f"\\begin{{{open_env}}}[label={label}]")
            else:
                lines.append(f"\\begin{{{open_env}}}")
        else:
            label = latex_label(spec, open_level_num)
            default_bullet = BULLET_LEVELS[open_level_num % len(BULLET_LEVELS)][0]
            if spec.lvl_text == default_bullet:
                label = None
            if label:
                lines.append(f"\\begin{{{open_env}}}[label={label}]")
            else:
                lines.append(f"\\begin{{{open_env}}}")
        stack.append((open_env, open_level_num, spec))
        if placeholder:
            lines.append("\\item")

    for ordinal, entry in enumerate(entries):
        env, level, numfmt, text, style_id = entry[:5]
        source_ordinal = entry[5] if len(entry) > 5 else ordinal
        if style_id and object_store is not None:
            object_store.attach(
                "paragraph-style",
                {"style_id": style_id, "text": text},
                owner_id=NodeId.allocate(max(0, source_ordinal)),
                owner_semantic_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                position="inside",
                ordinal=source_ordinal,
                content_type="application/json",
            )
        while stack and stack[-1][1] > level:
            close_top()
        spec = as_list_level(numfmt)
        if stack and stack[-1][1] == level and (
            stack[-1][0] != env or stack[-1][2] != spec
        ):
            close_top()
        while len(stack) < level:
            open_level("enumerate", len(stack), "decimal", placeholder=True)
        if not stack or stack[-1][1] < level:
            open_level(env, level, spec, placeholder=False)
        lines.append(f"\\item {text}")
    while stack:
        close_top()
    return "\n".join(lines) + "\n"
