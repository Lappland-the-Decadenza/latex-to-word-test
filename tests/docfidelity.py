"""Fidelity of the *document* layer: does a round trip preserve everything
about a .docx that is not a formula?

This is `fidelity.py`'s sibling. Same contract, same baseline discipline:
the user's own `.docx` is the reference, never our own output, because a
check that compares our output against our output cannot detect a
systematic error.

Six verdicts (PLAN.md §4.2 added the last two):

    identical    the trees match
    improvement  a listed, intended transformation (see IMPROVEMENTS)
    neutral      run splitting, explicit-vs-default properties, whitespace
    degradation  content or structure lost -- this is what must be zero
    deferred     understood, deliberately not carried -- a standing invoice,
                 listed in `DEFERRED` with a reason and a plan reference;
                 never folded into neutral
    noise        not authored -- Word wrote it itself, comparing it measures
                 Word's bookkeeping, not our fidelity (`NOISE`, the one
                 authorised list, PLAN.md §4.2)

It exists in this shape because `fidelity.py` shipped with two blind spots
that between them hid 540 real defects while reporting zero:

  1. it compared a *multiset of element types*, so moving a node from one
     parent to another -- which changes what Word draws -- compared equal;
  2. it normalised whitespace away, so spaces that were dropped or inflated
     into an em-space compared equal.

Both mistakes have the same shape: measuring *what exists* instead of *what
covers what*. So every census here is span-keyed -- each formatting state,
each image, each hyperlink is recorded together with the text it applies to.
A bold range that shrinks by three words is then a lost entry, not a matching
one.

Three further rules follow from that experience:

  - Nothing a reader can see is normalised away. Whitespace is compared, and
    colour is compared as an exact hex, never bucketed into "some colour".
  - `IMPROVEMENTS` is a short, explicit list of intended transformations.
    Anything not on it that changes the document is a degradation. A broad
    entry here would defeat the whole instrument, which is exactly how the
    math comparator came to report zero.
  - Legitimate representational freedom is removed *before* comparing, not
    forgiven afterwards: adjacent runs carrying identical formatting are
    coalesced first, because "hello world" as one run and as two runs with
    the same properties are the same document, while a bold range that
    covers different words is not.

Run directly to sweep the corpus:

    .venv\\Scripts\\python.exe tests\\docfidelity.py            # original vs. output/
    .venv\\Scripts\\python.exe tests\\docfidelity.py a.docx b.docx
"""

import hashlib
import os
import re
import sys
import zipfile
from collections import Counter, namedtuple
from difflib import SequenceMatcher

from lxml import etree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fidelity  # noqa: E402  -- corpus collection and the math-zone reader


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
PICTURE_URI = "http://schemas.openxmlformats.org/drawingml/2006/picture"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"

VAL = W + "val"

# A display-math paragraph often has no prose at all. Alignment keys still need
# to tell one apart from an empty paragraph, so math contributes a marker.
MATH_MARK = "∅"

# Word's own default. A run that says nothing about a property is not the same
# as a run that says "off", but it renders the same, so both normalise to None.
_OFF = frozenset({"0", "false", "off", "none", "auto"})

MONO_FONTS = frozenset({
    "consolas", "courier new", "courier", "lucida console", "monaco",
    "dejavu sans mono", "cascadia mono", "cascadia code",
})

# --- verdict classes for understood, deliberate loss (PLAN.md §4.2) --------

# `deferred`: an attribute the converter understands and deliberately does
# not carry. Differences in these are reported in their own verdict class,
# never folded into `neutral` -- a standing invoice, not a dismissal. The
# decision_ref points at the plan section that decided it; the reason is one
# line so the invoice stays readable in the sweep output.
DEFERRED = {
    # §3.3: the template decides these, not the author.
    "w:rFonts/w:sz": ("per-run font family and size: only the "
                      "monospace/not-monospace distinction is carried", "§3.3"),
    "w:position/w:spacing": ("raised/lowered position and kerning", "§3.3"),
    "w:ind": ("left/right and first-line indents", "§3.3"),
    "w:spacing@para": ("space before/after and line spacing", "§3.3"),
    "w:pBdr": ("paragraph borders", "§3.3"),
    "w:tabs": ("tab stops", "§3.3"),
    "w:pgSz": ("page size", "§3.3"),
    "w:pgMar": ("page margins", "§3.3"),
    "revision marks": ("w:ins/w:del change tracking", "§3.3"),
    # Not on §3.2's carried list, no canonical LaTeX spelling; the borderline
    # rule (§3.1 -- authorship and boundedness) decides these the same way.
    "w:keepNext": ("keep-with-next: a Word layout control", "§3.1"),
    "w:contextualSpacing": ("auto spacing between same-styled paragraphs", "§3.1"),
    "w:shd@para": ("paragraph shading has no spelling; run shading is carried", "§3.1"),
    "section break type": ("section boundaries beyond column changes", "§3.1"),
    "w:titlePg": ("different first page", "§3.1"),
    "w:pgNumType": ("page numbering format", "§3.1"),
    "headers/footers": ("part-level content not carried in Plan 1", "§3.1"),
    "docProps": ("core document metadata", "§3.1"),
    # §7.3: table structure is carried; column widths are not.
    "w:tcW": ("cell width: column widths are not carried", "§7.3"),
    "w:trHeight": ("row height", "§7.3"),
    "cell vAlign": ("cell vertical alignment", "§7.3"),
}

# `noise`: not authored. Exactly this list and no more. The plan is explicit
# that nothing may be added without evidence that Word writes it without user
# action -- "it produces a lot of failures" is not evidence, that is the
# symptom rule 2 exists to catch. When in doubt it goes in `DEFERRED`, which
# is visible, not here, which is not.
NOISE = frozenset({
    # Word writes a complex-script duplicate of b/i/sz on runs by itself,
    # with no user action: 3615 of 3854 direct-formatting occurrences in the
    # corpus are these. Comparing them measures Word's bookkeeping, not our
    # fidelity.
    "bCs", "iCs", "szCs",
    # Language and proofing state are assigned by Word's own detection.
    "lang", "noProof",
})


def ln(el):
    """Local name of an element tag."""
    t = el.tag
    return t.rsplit("}", 1)[-1] if isinstance(t, str) else ""


# --- reading -----------------------------------------------------------------


def _flag(rpr, name):
    """A toggle property: present and not switched off."""
    if rpr is None:
        return False
    el = rpr.find(W + name)
    if el is None:
        return False
    v = el.get(VAL)
    return v is None or v.strip().lower() not in _OFF


def _val(parent, name, attr=VAL):
    if parent is None:
        return None
    el = parent.find(W + name)
    if el is None:
        return None
    v = el.get(attr)
    if v is None or v.strip().lower() in _OFF:
        return None
    return v.strip()


def _color(rpr):
    """Text colour as an exact six-hex string.

    Deliberately not bucketed into a colour *name*: Word stores the hex, the
    LaTeX must carry the hex back, and "close enough" here would license the
    converter to change the colour the reader sees.
    """
    v = _val(rpr, "color")
    return v.upper() if v else None


def _run_props(r_el):
    """Everything about a run that a reader can see, as one hashable tuple.

    A tuple rather than the old if/elif ladder because Word's properties are
    independent and simultaneous: bold+italic+coloured+highlighted is one run,
    and a comparison that can only report the first of those is how formatting
    loss goes unnoticed.

    `w:rtl` (right-to-left direction), `w:vanish` (hidden text) and
    `w:rStyle` (a character style name -- §3.4 requires style names to
    round-trip) were added in Stage 1; `w:lang` and the `*Cs` duplicates are
    deliberately absent: they are `NOISE` (PLAN.md §4.2), read by Word's own
    machinery, and the per-run font family/size beyond the mono boolean are
    `_run_deferred`'s business, not this tuple's.
    """
    rpr = r_el.find(W + "rPr")
    fonts = rpr.find(W + "rFonts") if rpr is not None else None
    ascii_font = (fonts.get(W + "ascii") or "") if fonts is not None else ""
    shd = rpr.find(W + "shd") if rpr is not None else None
    fill = shd.get(W + "fill") if shd is not None else None
    if fill and fill.strip().lower() in _OFF:
        fill = None
    rstyle = (_val(rpr, "rStyle") or "").strip().lower() or None
    if rstyle == "hyperlink":
        # Word applies this built-in style to HYPERLINK field caches.  It is
        # structural link presentation, not an authored character style; the
        # canonical carrier intentionally does not reproduce it as \wrstyle.
        rstyle = None
    return (
        _flag(rpr, "b"),
        _flag(rpr, "i"),
        _val(rpr, "u") or None,
        _flag(rpr, "strike") or _flag(rpr, "dstrike"),
        _flag(rpr, "smallCaps"),
        _flag(rpr, "caps"),
        _val(rpr, "vertAlign"),
        ascii_font.strip().lower() in MONO_FONTS,
        _color(rpr),
        (_val(rpr, "highlight") or "").lower() or None,
        fill.upper() if fill else None,
        _flag(rpr, "rtl"),
        _flag(rpr, "vanish"),
        rstyle,
    )


PROP_NAMES = ("bold", "italic", "underline", "strike", "smallcaps", "allcaps",
              "vertalign", "mono", "color", "highlight", "shading",
              "rtl", "vanish", "rstyle")


def _run_deferred(rpr):
    """The §3.3-deferred run properties, read for the deferred census only:
    the font family string (the mono boolean above is compared), the point
    size, the raised/lowered position, and kerning. None of these may ever
    become a degradation -- the plan decided they are the template's job,
    not the author's -- but they must still be *read*, or a lost face or size
    would be invisible rather than invoiced."""
    fonts = rpr.find(W + "rFonts") if rpr is not None else None
    family = (fonts.get(W + "ascii") or "") if fonts is not None else ""
    return (
        family.strip().lower(),
        # `or ""`: a run may carry rFonts without w:sz (or vice versa), and
        # the census keys on these pairs -- a None would crash the sorted()
        # at the end of _read_paragraph.
        (_val(rpr, "sz") or ""),
        _val(rpr, "position"),
        _val(rpr, "spacing"),
    )


def _describe_props(props):
    on = [f"{n}={v!r}" if not isinstance(v, bool) else n
          for n, v in zip(PROP_NAMES, props) if v]
    return "+".join(on) if on else "plain"


def _iter_skip_fallback(node):
    """Iterate a subtree in document order, pruning ``mc:Fallback``.

    ``mc:AlternateContent`` carries the same content twice -- the live
    ``mc:Choice`` branch (what Word renders) and a compatibility
    ``mc:Fallback`` duplicate. ``docx_read._iter_skip_fallback`` applies the
    identical rule, so the two instruments read the same text (measured: a
    "Рис. 1" caption text box came back twice, "Рис. 1Рис. 1")."""
    pending = [node]
    while pending:
        el = pending.pop()
        if el.tag == MC + "Fallback":
            continue
        yield el
        pending.extend(reversed(list(el)))


def _run_text(r_el):
    out = []
    for node in _iter_skip_fallback(r_el):
        t = ln(node)
        if t == "t":
            out.append(node.text or "")
        elif t == "tab":
            out.append("\t")
        elif t == "br":
            out.append("\n")
    return "".join(out)


class _Package:
    """One .docx, opened once: relationships, numbering and media hashes are
    needed by nearly every paragraph, so they are resolved up front."""

    def __init__(self, path):
        self.path = path
        with zipfile.ZipFile(path) as z:
            self.names = set(z.namelist())
            self.document = etree.fromstring(z.read("word/document.xml"))
            self.rels = self._read_rels(z)
            self.numbering = self._read_numbering(z)
            self.style_num = self._read_style_numbering(z)
            self.media = {
                n: hashlib.sha1(z.read(n)).hexdigest()[:12]
                for n in self.names if n.startswith("word/media/")
            }

    def _read_rels(self, z):
        name = "word/_rels/document.xml.rels"
        if name not in self.names:
            return {}
        root = etree.fromstring(z.read(name))
        out = {}
        for rel in root.findall(PR + "Relationship"):
            out[rel.get("Id")] = (rel.get("Target") or "",
                                  rel.get("TargetMode") or "Internal")
        return out

    def _read_numbering(self, z):
        """numId -> {ilvl: (numFmt, level text, list indentation)}.

        Raw numIds are writer-assigned and cannot be compared. The rendered
        level can: ``%1.`` and ``%1.%2`` are not the same numbering, and the
        level's hanging indent is exactly what positions its text. Comparing
        only numFmt let a template heading change from ``2.1`` to a flat
        synthetic ``1.`` with a much larger indent while reporting identical.
        """
        if "word/numbering.xml" not in self.names:
            return {}
        root = etree.fromstring(z.read("word/numbering.xml"))
        abstract = {}
        for an in root.findall(W + "abstractNum"):
            aid = an.get(W + "abstractNumId")
            levels = {}
            for lvl in an.findall(W + "lvl"):
                ppr = lvl.find(W + "pPr")
                ind = ppr.find(W + "ind") if ppr is not None else None
                levels[lvl.get(W + "ilvl") or "0"] = (
                    _val(lvl, "numFmt") or "bullet",
                    _val(lvl, "lvlText") or "",
                    _val(ind, "left") if ind is not None else None,
                    _val(ind, "hanging") if ind is not None else None,
                )
            abstract[aid] = levels
        out = {}
        for num in root.findall(W + "num"):
            nid = num.get(W + "numId")
            aid_el = num.find(W + "abstractNumId")
            aid = aid_el.get(VAL) if aid_el is not None else None
            out[nid] = abstract.get(aid, {})
        return out

    def _read_style_numbering(self, z):
        """styleId -> (numId, ilvl) for styles that carry numbering themselves.

        Word attaches list numbering to a paragraph either directly or through
        its style; a reader that only looks at the paragraph misses every list
        written the second way.
        """
        if "word/styles.xml" not in self.names:
            return {}
        root = etree.fromstring(z.read("word/styles.xml"))
        out = {}
        for st in root.findall(W + "style"):
            sid = st.get(W + "styleId")
            ppr = st.find(W + "pPr")
            numpr = ppr.find(W + "numPr") if ppr is not None else None
            if numpr is None:
                continue
            out[sid] = (_val(numpr, "numId"), _val(numpr, "ilvl") or "0")
        return out

    def media_hash(self, rid):
        target, mode = self.rels.get(rid, ("", "Internal"))
        if not target:
            return None
        name = target if target.startswith("word/") else "word/" + target.lstrip("/")
        return self.media.get(name)

    def rel_target(self, rid):
        return self.rels.get(rid, ("", ""))[0]


Block = namedtuple("Block", "kind key para table")

# Section geometry as one signature per paragraph (PLAN.md §4.1, section
# level). `cols` is compared (multi-column layout is carried); the rest are
# deferred (page geometry is the template's job, §3.3/§3.1).
SectionSig = namedtuple("SectionSig", "cols pgsz pgmar titlepg pgnumtype breaktype")

# The §3.3/§3.1-deferred paragraph and run properties, read for the deferred
# census only (see `_run_deferred` and the DEFERRED table). `revision` marks
# w:ins/w:del presence -- the deleted text itself is *not* read, because it
# is exactly the content §3.3 defers, and counting it as ordinary text would
# report every stripped revision mark as a text-change degradation instead
# of as the deferred item it is.
DeferredSig = namedtuple(
    "DeferredSig",
    "ind pspacing keepnext tabs pbdr pshd ctxspacing rfonts rpos revision")

Para = namedtuple(
    "Para",
    "text heading style align listfmt pagebreak runs images links breaks math "
    "section deferred bookmarks fields")
Table = namedtuple(
    "Table",
    "rows cols width cells gridspan vmerge borders shd tblstyle tcw trh valigns")


_HEADING_RE = re.compile(r"^(?:heading|заголовок|berschrift)\s*(\d)$", re.I)


def _heading_level(style_id, ppr):
    """Semantic heading level, from whichever signal the document carries.

    Compared instead of the raw style id because "Heading1", "Heading 1" and a
    localised "Заголовок 1" are the same heading to a reader, while a style id
    that merely round-trips as a different string is not a defect.
    """
    if style_id:
        s = style_id.strip()
        if s.lower() in ("title", "название"):
            return 0
        m = _HEADING_RE.match(s.replace(" ", " "))
        if m:
            return int(m.group(1))
    lvl = _val(ppr, "outlineLvl")
    if lvl is not None and lvl.isdigit() and int(lvl) < 9:
        return int(lvl) + 1
    return None


_ALIGN_ALIASES = {"start": "left", "end": "right", "centerGroup": "center",
                  "distribute": "both"}


def _read_align(p_el, ppr):
    """Paragraph alignment as *rendered*, defaults resolved.

    A display-math paragraph is the trap here. Word writes `m:oMathPara` with
    no `m:jc` and renders it centred, because `centerGroup` is the schema
    default for that element -- while a paragraph with no `w:jc` renders left.
    Reading the absent property as "left" therefore reported every single
    display equation in the corpus as newly centred: 1257 findings, all of them
    defects in this file rather than in the converter. Resolving each element's
    own default is the difference between an instrument and a noise source.
    """
    omp = p_el.find(M + "oMathPara")
    if omp is not None:
        mpr = omp.find(M + "oMathParaPr")
        mjc = mpr.find(M + "jc") if mpr is not None else None
        raw = mjc.get(M + "val") if mjc is not None else None
        return _ALIGN_ALIASES.get(raw or "centerGroup", raw or "center")
    raw = _val(ppr, "jc") or "left"
    return _ALIGN_ALIASES.get(raw, raw)


def _read_paragraph(p_el, pkg):
    ppr = p_el.find(W + "pPr")
    style_id = _val(ppr, "pStyle")
    align = _read_align(p_el, ppr)

    numpr = ppr.find(W + "numPr") if ppr is not None else None
    numid = _val(numpr, "numId") if numpr is not None else None
    ilvl = (_val(numpr, "ilvl") or "0") if numpr is not None else "0"
    if numid is None and style_id in pkg.style_num:
        numid, ilvl = pkg.style_num[style_id]
    listfmt = None
    if numid is not None:
        levels = pkg.numbering.get(numid, {})
        listfmt = (levels.get(ilvl, ("bullet", "", None, None)), ilvl)

    # The §3.3-deferred paragraph properties, read for the deferred census.
    ind = ppr.find(W + "ind") if ppr is not None else None
    ind_sig = (
        _val(ind, "left") if ind is not None else None,
        _val(ind, "right") if ind is not None else None,
        _val(ind, "firstLine") if ind is not None else None,
        _val(ind, "hanging") if ind is not None else None,
    )
    spacing = ppr.find(W + "spacing") if ppr is not None else None
    pspacing = (
        _val(spacing, "before") if spacing is not None else None,
        _val(spacing, "after") if spacing is not None else None,
        _val(spacing, "line") if spacing is not None else None,
    )
    tabs = ()
    if ppr is not None:
        tab_el = ppr.find(W + "tabs")
        if tab_el is not None:
            tabs = tuple(
                (t.get(W + "pos"), t.get(W + "val"))
                for t in tab_el.findall(W + "tab"))
    pbdr = ppr is not None and ppr.find(W + "pBdr") is not None
    pshd = None
    if ppr is not None:
        shd = ppr.find(W + "shd")
        pshd = shd.get(W + "fill") if shd is not None else None
        if pshd and pshd.strip().lower() in _OFF:
            pshd = None
    ctxspacing = _flag(ppr, "contextualSpacing")
    keepnext = _flag(ppr, "keepNext")

    # §3.2's explicit page break has two Word spellings: a w:br type="page"
    # run (read below) and w:pPr/pageBreakBefore. The reverse converter
    # carries both as \newpage{}, which comes back as the run form -- so the
    # pPr form must count here too or a carried page break reads as newly
    # appearing (measured: 27 corpus paragraphs, §7.3).
    pagebreak = (ppr is not None
                 and ppr.find(W + "pageBreakBefore") is not None)
    text_parts = []
    runs = []          # (props, text) in document order, before coalescing
    rfonts = Counter()       # (family, sz) across runs -- deferred census
    rpos = Counter()         # (position, kerning) across runs -- deferred
    images = []
    links = []
    breaks = []
    math_count = 0
    bookmarks = 0
    fields = False
    active_field_kind = None
    # ``w:fldChar begin`` normally precedes the ``w:instrText`` run, so the
    # streaming walk cannot know that first run is a HYPERLINK until after it
    # has already seen it.  Pre-scan the paragraph's field instructions for
    # that one native equivalent; ordinary field kinds remain measured.
    has_hyperlink_field = any(
        (item.text or "").strip().split(None, 1)[0].upper() == "HYPERLINK"
        for item in p_el.iter(W + "instrText")
        if (item.text or "").strip()
    )
    revision = False

    # NOISE bookmark families: names Word (or a converter) generated, not
    # the author -- _TocNNN (TOC-field hyperlink targets), _HlkNNN
    # (hyperlink targets), _GoBack (navigation bookkeeping), and X<long
    # hex> (converter artifacts). Comparing them would measure Word, not
    # us -- the same §4.2 argument as the NOISE rPr members above.
    # _RefNNN stays in the census: it is the target a cross-reference
    # resolves to and must survive the round trip. The reverse's
    # `_INTERNAL_BOOKMARK` applies the identical family, so the two
    # instruments agree (PLAN.md §7.1 record).
    _BOOKMARK_NOISE = re.compile(r"^(?:_(?:GoBack|Toc\d+|Hlk\d+)|X[0-9a-f]{20,})$")

    def walk(node, link_target=None):
        nonlocal pagebreak, math_count, bookmarks, fields, revision
        nonlocal active_field_kind
        for child in node:
            t = ln(child)
            if t == "r":
                txt = _run_text(child)
                rpr = child.find(W + "rPr")
                # NOISE members (bCs/iCs/szCs/lang/noProof) are never read
                # into any census: they are Word's own bookkeeping, and
                # comparing them would measure Word, not us (PLAN.md §4.2).
                for br in child.findall(W + "br"):
                    kind = br.get(W + "type") or "textWrapping"
                    breaks.append(kind)
                    if kind == "page":
                        pagebreak = True
                instr = "".join(
                    item.text or ""
                    for item in child.iter(W + "instrText")
                ).strip()
                if instr and active_field_kind is None:
                    active_field_kind = instr.split(None, 1)[0].upper()
                if child.find(W + "fldChar") is not None:
                    # HYPERLINK fields have a native, semantically equivalent
                    # representation in the converter: a relationship-backed
                    # hyperlink produced from \href.  They are not lost field
                    # codes when the output uses that representation.
                    if active_field_kind != "HYPERLINK" and not (
                        active_field_kind is None and has_hyperlink_field
                    ):
                        fields = True
                    if any(
                        fc.get(W + "fldCharType") == "end"
                        for fc in child.findall(W + "fldChar")
                    ):
                        active_field_kind = None
                for drawing in child.iter(W + "drawing"):
                    image = _read_drawing(drawing, pkg)
                    if image is not None:
                        images.append(image)
                for pict in child.iter(W + "pict"):
                    image = _read_vml(pict, pkg)
                    if image is not None:
                        images.append(image)
                if txt:
                    props = _run_props(child)
                    runs.append((props, txt))
                    text_parts.append(txt)
                    if rpr is not None:
                        family, sz, pos, kern = _run_deferred(rpr)
                        rfonts[(family, sz)] += 1
                        if pos is not None or kern is not None:
                            rpos[(pos, kern)] += 1
                    if link_target is not None:
                        link_text = txt.strip()
                        if links and links[-1][0] == link_target:
                            links[-1] = (link_target, links[-1][1] + link_text)
                        else:
                            links.append((link_target, link_text))
            elif t == "hyperlink":
                rid = child.get(R + "id")
                target = pkg.rel_target(rid) if rid else (
                    "#" + (child.get(W + "anchor") or ""))
                walk(child, link_target=target)
            elif t in ("oMath", "oMathPara"):
                math_count += len(child.findall(M + "oMath")) or 1
                text_parts.append(MATH_MARK)
            elif t == "bookmarkStart":
                if not _BOOKMARK_NOISE.match(child.get(W + "name") or ""):
                    bookmarks += 1
            elif t == "ins":
                revision = True
                walk(child, link_target)
            elif t == "del":
                # Deferred content (§3.3): presence only, never the deleted
                # text -- see the DeferredSig comment.
                revision = True
            elif t in ("smartTag", "sdt", "sdtContent",
                       "proofErr", "fldSimple"):
                walk(child, link_target)

    walk(p_el)

    return Para(
        text="".join(text_parts),
        heading=_heading_level(style_id, ppr),
        style=(style_id or "").strip().lower().replace(" ", ""),
        align=align,
        listfmt=listfmt,
        pagebreak=pagebreak,
        runs=tuple(runs),
        images=tuple(images),
        links=tuple(links),
        breaks=tuple(breaks),
        math=math_count,
        # Filled in by `read_blocks`, which is the only place that can see
        # which section a paragraph belongs to.
        section=None,
        deferred=DeferredSig(
            ind=ind_sig, pspacing=pspacing, keepnext=keepnext, tabs=tabs,
            pbdr=pbdr, pshd=pshd, ctxspacing=ctxspacing,
            rfonts=tuple(sorted(rfonts.items())),
            rpos=tuple(sorted(rpos.items())),
            revision=revision),
        bookmarks=bookmarks,
        fields=fields,
    )


def _read_drawing(drawing, pkg):
    """One image as (content hash, width EMU, height EMU, anchored, wrap,
    alt text, crop, rotation).

    §4.1 asks for the full surface -- inline vs. anchored, wrap mode, alt
    text, crop, rotation -- not just the extent: a round trip that pins an
    inline figure or drops its alt text changes what Word draws (and what a
    screen reader reads) with the same pixels. All fields are compared.
    """
    graphic_data = drawing.find(".//" + A + "graphicData")
    if (graphic_data is None
            or graphic_data.get("uri") != PICTURE_URI
            or drawing.find(".//" + A + "blip") is None):
        # Charts, shapes, text boxes and grouped drawings are not image
        # records.  They remain visible to the Word coverage/warning
        # instrument and belong to the opaque-object stage, not C5.
        return None

    extent = drawing.find(".//" + WP + "extent")
    cx = int(extent.get("cx") or 0) if extent is not None else 0
    cy = int(extent.get("cy") or 0) if extent is not None else 0
    blip = drawing.find(".//" + A + "blip")
    rid = blip.get(R + "embed") if blip is not None else None
    anchor = drawing.find(WP + "anchor")
    inline = drawing.find(WP + "inline")
    wrap = "inline"
    if anchor is not None:
        for wrap_el in anchor:
            t = ln(wrap_el)
            if t.startswith("wrap"):
                wrap = t[4:].lower() or "None"
                break
        else:
            wrap = "none"
    elif inline is None:
        wrap = None
    docpr = drawing.find(".//" + WP + "docPr")
    alt = docpr.get("descr") if docpr is not None else None
    src_rect = drawing.find(".//" + A + "srcRect")
    crop = None
    if src_rect is not None:
        crop = tuple(
            (src_rect.get(k) or "0") for k in ("l", "t", "r", "b"))
    rot = None
    xfrm = drawing.find(".//" + A + "xfrm")
    if xfrm is not None and xfrm.get("rot"):
        rot = xfrm.get("rot")
    return (pkg.media_hash(rid) if rid else None, cx, cy, anchor is not None,
            wrap, (alt or "").strip(), crop, rot)


def _read_vml(pict, pkg):
    """Legacy VML picture (`w:pict`). Older documents and pasted images use it;
    ignoring it would silently drop a visible picture. VML carries no
    extent/wrap/alt data worth trusting here, so those fields stay None
    (compared as None on both sides unless the round trip converts the image
    to a modern drawing, which the anchored flag change then reports)."""
    for el in pict.iter():
        rid = el.get(R + "id")
        if rid:
            return (pkg.media_hash(rid), 0, 0, True, None, None, None, None)
    # VML shapes/text boxes without imagedata are opaque objects, not
    # zero-sized images.  Do not let them contaminate the C5 image census.
    return None


def _read_table(tbl, pkg):
    grid = tbl.find(W + "tblGrid")
    cols = len(grid.findall(W + "gridCol")) if grid is not None else 0
    width = 0
    if grid is not None:
        for gc in grid.findall(W + "gridCol"):
            try:
                width += int(gc.get(W + "w") or 0)
            except ValueError:
                pass
    rows = tbl.findall(W + "tr")
    gridspan = 0
    vmerge = 0
    valigns = set()
    trh = 0
    cells = []
    for tr in rows:
        if tr.find(W + "trHeight") is not None:
            trh += 1
        row = []
        for tc in tr.findall(W + "tc"):
            # Paragraph boundaries and w:br in a cell are the §7.3 \parbox
            # shape; neither contributes text, so the join is over all w:t
            # with no separator -- a "space" between paragraphs is not in
            # the author's text and must not be manufactured here.
            row.append(_norm_ws("".join(
                t.text or "" for t in tc.iter(W + "t"))))
            tcpr = tc.find(W + "tcPr")
            if tcpr is not None:
                gs = tcpr.find(W + "gridSpan")
                if gs is not None:
                    try:
                        gridspan = max(gridspan, int(gs.get(VAL) or 1))
                    except ValueError:
                        pass
                if tcpr.find(W + "vMerge") is not None:
                    vmerge += 1
                va = _val(tcpr, "vAlign")
                if va:
                    valigns.add(va)
        cells.append(tuple(row))
    tcw = tbl.find(".//" + W + "tcW") is not None
    # w:tblBorders lives inside w:tblPr -- tbl.find(W+"tblBorders") matches
    # nothing in any valid document and measured table-level borders as
    # always absent (instrument-truth fix, §7.3).
    borders = (tbl.find(W + "tblPr/" + W + "tblBorders") is not None
               or tbl.find(".//" + W + "tcBorders") is not None)
    # Same "no fill" filter as paragraph shading above: w:shd with
    # w:fill="auto" (val=clear) is Word's own no-fill spelling -- measured
    # on 54+ cells of one corpus table where the author never shaded a
    # thing -- and comparing it would measure Word's bookkeeping, not cell
    # shading. The paragraph-level read applies _OFF; the table read must
    # apply the identical rule or the two disagree.
    # Cell shading is the tcPr/w:shd the converter carries (§7.3); an
    # author who white-shaded cell *paragraphs* (w:pPr/w:shd) exercised the
    # deferred "paragraph shading has no spelling" item, and counting it
    # here would invoice a permanent false degradation. (Instrument-truth
    # fix, measured on one corpus table's calculation cells.)
    shd = tuple(sorted({
        s.get(W + "fill") for s in tbl.iter(W + "shd")
        if etree.QName(s.getparent()).localname == "tcPr"
        and s.get(W + "fill")
        and s.get(W + "fill").strip().lower() not in _OFF}))
    tblpr = tbl.find(W + "tblPr")
    tblstyle = (_val(tblpr, "tblStyle") or "").strip().lower() or None
    return Table(rows=len(rows), cols=cols, width=width,
                 cells=tuple(cells), gridspan=gridspan, vmerge=vmerge,
                 borders=borders, shd=shd, tblstyle=tblstyle,
                 tcw=tcw, trh=trh, valigns=tuple(sorted(valigns)))


def _read_section(sectpr):
    """Everything §4.1 asks the section level to report, as one signature.

    `cols` is carried (multi-column layout survives a round trip); the rest
    -- page size, margins, title-page flag, page-number format, break type --
    are deferred, because page geometry is the template's decision, not the
    author's (§3.3). Absent `w:type` means nextPage, the schema default.
    """
    if sectpr is None:
        return SectionSig(1, None, None, False, None, "nextPage")
    cols = sectpr.find(W + "cols")
    ncols = 1
    if cols is not None:
        num = cols.get(W + "num")
        if num and num.isdigit():
            ncols = int(num)
        else:
            n = len(cols.findall(W + "col"))
            ncols = n if n > 1 else 1
    pgsz = sectpr.find(W + "pgSz")
    pgmar = sectpr.find(W + "pgMar")
    return SectionSig(
        cols=ncols,
        pgsz=((pgsz.get(W + "w"), pgsz.get(W + "h")))
        if pgsz is not None else None,
        pgmar=tuple(
            (pgmar.get(W + k) or None) for k in ("top", "right", "bottom", "left"))
        if pgmar is not None else None,
        titlepg=_flag(sectpr, "titlePg"),
        pgnumtype=_val(sectpr, "pgNumType"),
        breaktype=_val(sectpr, "type") or "nextPage",
    )


def read_blocks(path):
    """Every body-level block of a document, in order.

    Column layout is attached to each paragraph rather than counted per
    section. A document that loses its two-column body still has the same
    number of sections and the same text, so a census of section objects
    would report nothing -- the same blindness that let re-parented equations
    pass as identical. Recording how many columns the text a reader sees is
    laid out in makes the loss visible on exactly the paragraphs it affects.

    Word stores a section's properties in the `w:sectPr` of the *last*
    paragraph of that section, with the final section's in `w:body` itself,
    so the count is resolved by looking forward to the next boundary.
    """
    pkg = _Package(path)
    body = pkg.document.find(W + "body")
    out = []
    if body is None:
        return out
    pending = []       # blocks since the last section boundary
    for el in body:
        t = ln(el)
        if t == "p":
            # A generated TOC field is the native Word representation of the
            # same semantic block as an SDT-backed TOC in the source. Its
            # cached result is deliberately not content: Word regenerates it
            # from headings. Exclude only this exact field shape; ordinary
            # paragraphs and unknown fields remain measured.
            toc_instr = "".join(
                item.text or "" for item in el.iter(W + "instrText")
            )
            if "TOC" in toc_instr.upper():
                continue
            para = _read_paragraph(el, pkg)
            pending.append(Block("p", _norm_ws(para.text), para, None))
            ppr = el.find(W + "pPr")
            sectpr = ppr.find(W + "sectPr") if ppr is not None else None
            if sectpr is not None:
                out.extend(_with_section(pending, _read_section(sectpr)))
                pending = []
        elif t == "tbl":
            table = _read_table(el, pkg)
            key = "TBL:" + "|".join("/".join(r) for r in table.cells)[:200]
            pending.append(Block("tbl", key, None, table))
    out.extend(_with_section(pending, _read_section(body.find(W + "sectPr"))))
    # An empty paragraph is still a visible Word block: it can provide the
    # deliberate vertical separation between content. Keep it in the census
    # so deleting one cannot shift past the comparator unnoticed.
    return out


def _with_section(blocks, sig):
    return [b if b.para is None else b._replace(para=b.para._replace(section=sig))
            for b in blocks]


# --- comparison --------------------------------------------------------------


def _norm_ws(s):
    """Collapse whitespace -- for *alignment keys and content identity only*.

    Whitespace itself is compared separately and exactly (see `_ws_signature`).
    Folding it away here and nowhere else is what keeps a dropped double space
    from hiding behind a matching sentence.
    """
    return re.sub(r"\s+", " ", s or "").strip()


def _ws_signature(s):
    """The whitespace a reader can see: the length of every run of spaces,
    in order. `"a,  b"` and `"a, b"` differ; `"a, b"` and `"a, b"` do not."""
    return tuple(len(m.group(0)) for m in re.finditer(r"[ \t ]+", s or ""))


def coalesce(runs):
    """Merge adjacent runs carrying identical formatting.

    Splitting a run is not a defect -- Word splits on spell-check state, language
    and revision boundaries, and any writer re-splits differently. What matters
    is which *text* carries which formatting, so the comparison is made on the
    merged form. Doing this before the census, rather than forgiving mismatches
    after it, is what keeps the check strict enough to be worth running.
    """
    out = []
    for props, text in runs:
        if out and out[-1][0] == props:
            out[-1][1].append(text)
        else:
            out.append((props, [text]))
    return [(p, "".join(parts)) for p, parts in out]


def run_census(para):
    """Span-keyed formatting: (properties, the text they cover).

    The lesson from the math comparator: counting *how many* bold runs exist
    cannot detect a bold range that moved or shrank. Keying each formatting
    state by its own text can.
    """
    return Counter(
        (props, _norm_ws(text))
        for props, text in coalesce(para.runs) if _norm_ws(text)
    )


Finding = namedtuple("Finding", "index jndex verdict detail")

# Transformations we intend, stated narrowly. Anything not listed that changes
# the document is a degradation -- keep this list short and specific.
IMPROVEMENTS = [
    (
        "paragraph gained an explicit heading level from its outline level",
        lambda o, n: o.heading is None and n.heading is not None
        and _norm_ws(o.text) == _norm_ws(n.text),
    ),
]


def classify(o, n):
    """Classify one paragraph pair. Returns (verdict, detail)."""
    # 1. Content first. Everything else is formatting *of* this text, so a
    #    text change makes the rest meaningless to report.
    if _norm_ws(o.text) != _norm_ws(n.text):
        return "degradation", (
            f"text changed: {o.text[:70]!r} -> {n.text[:70]!r}")

    # 2. Whitespace the reader can see -- the defect class that a whitespace-
    #    normalising comparator is structurally unable to find.
    if _ws_signature(o.text) != _ws_signature(n.text):
        return "degradation", (
            f"spacing changed: runs {_ws_signature(o.text)} -> "
            f"{_ws_signature(n.text)} in {o.text[:60]!r}")

    # 3. Block role: heading level, list membership, alignment, page break.
    if o.heading != n.heading:
        for name, pred in IMPROVEMENTS:
            if pred(o, n):
                return "improvement", name
        return "degradation", f"heading level {o.heading} -> {n.heading}"
    if o.listfmt != n.listfmt:
        return "degradation", f"list {o.listfmt} -> {n.listfmt}"
    if o.align != n.align:
        return "degradation", f"alignment {o.align} -> {n.align}"
    if o.pagebreak != n.pagebreak:
        return "degradation", f"page break {o.pagebreak} -> {n.pagebreak}"
    if o.section.cols != n.section.cols:
        return "degradation", f"columns {o.section.cols} -> {n.section.cols}"

    # 3b. Anchors and field codes: §3.2 promises bookmarks and cross-
    #     references; a round trip that drops them is a degradation even
    #     though no visible text changed.
    if o.bookmarks != n.bookmarks:
        return "degradation", f"bookmarks {o.bookmarks} -> {n.bookmarks}"
    if o.fields != n.fields:
        return "degradation", (
            f"field codes {'present' if o.fields else 'absent'} -> "
            f"{'present' if n.fields else 'absent'}")

    # 4. Formatting, span-keyed. A lost entry means some range of text no
    #    longer carries the formatting it had.
    o_runs, n_runs = run_census(o), run_census(n)
    lost = o_runs - n_runs
    if lost:
        # Report the *cause*, not its wake. Losing one highlighted range makes
        # its two plain neighbours coalesce into one, so their spans change
        # too and the paragraph offers several lost entries that all describe
        # the same defect. Ranking by how much formatting an entry carries
        # puts the highlight first and the collateral plain spans nowhere --
        # otherwise half the findings name "plain" and point at nothing
        # actionable.
        props, span = max(
            lost, key=lambda e: (sum(1 for v in e[0] if v), len(e[1])))
        gained = n_runs - o_runs
        now = [p for p, s in gained if _overlaps(span, s)]
        return "degradation", (
            f"formatting lost: {_describe_props(props)} covered {span[:50]!r}"
            + (f", now {_describe_props(now[0])}" if now else ", now nothing")
        )

    # 5. Embedded objects.
    o_img, n_img = Counter(o.images), Counter(n.images)
    if o_img != n_img:
        li, gi = o_img - n_img, n_img - o_img
        return "degradation", f"images changed: lost {list(li)}, gained {list(gi)}"
    o_lnk, n_lnk = Counter(o.links), Counter(n.links)
    if o_lnk - n_lnk:
        return "degradation", f"hyperlinks lost: {list(o_lnk - n_lnk)[:3]}"
    if o.math != n.math:
        return "degradation", f"math zone count {o.math} -> {n.math}"

    # 6. The named Word style (`w:pStyle` -> `word/styles.xml`). A style is
    #    how the author said "this paragraph is a caption / a quote / body
    #    text", and it carries its own font, size, spacing and indents, so
    #    losing it silently reformats the paragraph even when every run
    #    property compared above matches. This was reported as `neutral`
    #    until D11 -- the reason a whole capability could read as "0
    #    degradations" while not being implemented at all.
    if o.style != n.style:
        return "degradation", f"style {o.style!r} -> {n.style!r}"

    # 7. Deferred attributes (PLAN.md §4.2): understood, deliberately not
    #    carried. A difference is reported in its own verdict class with the
    #    reason from the DEFERRED table -- a standing invoice, never folded
    #    into `neutral`, never silently dropped. Section geometry is compared
    #    per *section* in `_compare_sections`, not here: the signature is
    #    attached to every paragraph of its section, so a per-block check
    #    would invoice the same difference once per paragraph.
    for attr, ov, nv in _deferred_diffs(o.deferred, n.deferred):
        return "deferred", _deferred_detail(attr, ov, nv)

    if o_runs == n_runs and Counter(o.breaks) == Counter(n.breaks):
        return "identical", ""
    return "neutral", "breaks re-spelled"


_DEFERRED_FIELD_KEY = {
    "ind": "w:ind", "pspacing": "w:spacing@para", "keepnext": "w:keepNext",
    "tabs": "w:tabs", "pbdr": "w:pBdr", "pshd": "w:shd@para",
    "ctxspacing": "w:contextualSpacing", "rfonts": "w:rFonts/w:sz",
    "rpos": "w:position/w:spacing", "revision": "revision marks",
}
_SECTION_DEFERRED_FIELDS = {
    "pgsz": "w:pgSz", "pgmar": "w:pgMar", "titlepg": "w:titlePg",
    "pgnumtype": "w:pgNumType", "breaktype": "section break type",
}


def _deferred_diffs(o, n):
    """(attribute, o_val, n_val) for every paragraph/run deferred attribute
    that differs, keyed as in the DEFERRED table. `rfonts`/`rpos` are
    multisets of run-property tuples, so their values are summarised as
    distinct-counts when they change; the rest are small value tuples."""
    for field in DeferredSig._fields:
        ov, nv = getattr(o, field), getattr(n, field)
        if ov != nv:
            if field in ("rfonts", "rpos"):
                ov, nv = f"{len(ov)} distinct", f"{len(nv)} distinct"
            yield _DEFERRED_FIELD_KEY[field], ov, nv


def _section_deferred_diffs(o, n):
    """Section geometry beyond the compared column count (PLAN.md §4.1)."""
    if o is None or n is None:
        return
    for key, attr in _SECTION_DEFERRED_FIELDS.items():
        ov, nv = getattr(o, key), getattr(n, key)
        if ov != nv:
            yield attr, ov, nv


def _deferred_detail(attr, ov, nv):
    reason, ref = DEFERRED.get(attr, ("", ""))
    return f"{attr} {ov!r} -> {nv!r} ({reason}; {ref})".strip()


def _overlaps(a, b):
    return bool(a) and bool(b) and SequenceMatcher(None, a, b).ratio() > 0.5


def _classify_table(o, n):
    """§4.1's table level: structure is compared (merges, style, shading,
    borders -- §7.3), column widths and row heights are deferred (§7.3)."""
    if (o.rows, o.cols) != (n.rows, n.cols):
        return "degradation", (
            f"table {o.rows}x{o.cols} -> {n.rows}x{n.cols}")
    if o.cells != n.cells:
        return "degradation", "table cell text changed"
    if o.gridspan != n.gridspan:
        return "degradation", (
            f"merged cells changed: max span {o.gridspan} -> {n.gridspan}")
    if o.vmerge != n.vmerge:
        return "degradation", (
            f"vertically merged cells {o.vmerge} -> {n.vmerge}")
    if o.tblstyle != n.tblstyle:
        return "degradation", f"table style {o.tblstyle!r} -> {n.tblstyle!r}"
    if o.shd != n.shd:
        return "degradation", f"cell shading {o.shd} -> {n.shd}"
    if o.borders != n.borders:
        return "degradation", (
            f"table borders {'present' if o.borders else 'absent'} -> "
            f"{'present' if n.borders else 'absent'}")
    if (o.tcw, o.trh, o.valigns) != (n.tcw, n.trh, n.valigns):
        changed = []
        if o.tcw != n.tcw:
            changed.append(f"w:tcW {o.tcw} -> {n.tcw}")
        if o.trh != n.trh:
            changed.append(f"w:trHeight {o.trh} -> {n.trh}")
        if o.valigns != n.valigns:
            changed.append(f"cell vAlign {o.valigns} -> {n.valigns}")
        return "deferred", "; ".join(changed) + " (§7.3)"
    return "identical", ""


def compare(original_path, roundtripped_path):
    """Pair the blocks of two documents and classify each pair.

    Aligned on normalised block text rather than by index, for the same reason
    `fidelity.compare` is: one dropped paragraph shifts every later index, and
    positional pairing would then report the entire rest of the document as
    damaged, burying the one real defect in hundreds of false ones.
    """
    a = read_blocks(original_path)
    b = read_blocks(roundtripped_path)
    ka = [x.kind + ":" + x.key for x in a]
    kb = [y.kind + ":" + y.key for y in b]

    findings = []
    sm = SequenceMatcher(None, ka, kb, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op in ("equal", "replace"):
            for off in range(min(i2 - i1, j2 - j1)):
                x, y = a[i1 + off], b[j1 + off]
                if x.kind != y.kind:
                    findings.append(Finding(i1 + off, j1 + off, "degradation",
                        f"block became a {y.kind} (was {x.kind})"))
                elif x.kind == "tbl":
                    v, d = _classify_table(x.table, y.table)
                    findings.append(Finding(i1 + off, j1 + off, v, d))
                else:
                    v, d = classify(x.para, y.para)
                    findings.append(Finding(i1 + off, j1 + off, v, d))
            n = min(i2 - i1, j2 - j1)
            for k in range(i1 + n, i2):
                findings.append(Finding(k, None, "degradation", _lost_detail(a[k])))
            for k in range(j1 + n, j2):
                findings.append(Finding(None, k, "degradation",
                                        f"block appeared: {b[k].key[:60]!r}"))
        elif op == "delete":
            for k in range(i1, i2):
                findings.append(Finding(k, None, "degradation", _lost_detail(a[k])))
        elif op == "insert":
            for k in range(j1, j2):
                findings.append(Finding(None, k, "degradation",
                                        f"block appeared: {b[k].key[:60]!r}"))
    findings.extend(_compare_sections(a, b))
    return findings


def _compare_sections(a, b):
    """Section geometry, one finding per mismatched section.

    Every paragraph carries its section's signature, so the per-section
    comparison is the consecutive-distinct run of those signatures. Without
    the dedupe, one changed margin invoices itself once per paragraph
    (thousands of findings for a single section property).
    """
    def sections(blocks):
        sigs, last = [], None
        for blk in blocks:
            if blk.para is None:
                continue
            if blk.para.section != last:
                sigs.append(blk.para.section)
                last = blk.para.section
        return sigs

    o, n = sections(a), sections(b)
    findings = []
    for i, (os_, ns) in enumerate(zip(o, n), 1):
        if os_ == ns:
            continue
        for attr, ov, nv in _section_deferred_diffs(os_, ns):
            findings.append(Finding(None, None, "deferred",
                                    f"section {i}: "
                                    + _deferred_detail(attr, ov, nv)))
    if len(o) != len(n):
        findings.append(Finding(None, None, "deferred",
                                f"section count {len(o)} -> {len(n)}"
                                " (section geometry; §3.3)"))
    return findings


def _lost_detail(block):
    if block.kind == "tbl":
        return f"table lost: {block.table.rows}x{block.table.cols}"
    if block.para.images:
        return f"block lost with {len(block.para.images)} image(s)"
    return f"block lost: {block.key[:60]!r}"


# --- document level (PLAN.md §4.1) ------------------------------------------


def _part_count(pkg, part_name):
    return 1 if part_name in pkg.names else 0


def _real_notes(pkg, part):
    """Real note definitions of one notes part: id -> text.

    "Real" = no ``w:type`` attribute -- the separator/continuationSeparator
    bookkeeping entries Word writes carry one, and the ids themselves are
    not a safe discriminator (Word hands the bookkeeping entries -1/0 but a
    real note may take any id, measured: a corpus footnote with id 1).
    """
    if part not in pkg.names:
        return {}
    with zipfile.ZipFile(pkg.path) as z:
        root = etree.fromstring(z.read(part))
    tag = "footnote" if "footnotes" in part else "endnote"
    out = {}
    for el in root.iter(W + tag):
        if el.get(W + "type") is not None:
            continue
        nid = el.get(W + "id")
        if nid is not None:
            out[nid] = "".join(t.text or "" for t in el.iter(W + "t"))
    return out


def _real_comments(pkg):
    """Comment definitions of word/comments.xml: id -> (author, date, text).

    Unlike the notes parts, comments.xml has no bookkeeping entries -- every
    w:comment element is real (PLAN.md §7.1). Author and date are compared
    with the text: a round trip that keeps the reference count but loses
    either is a degradation.
    """
    if "word/comments.xml" not in pkg.names:
        return {}
    with zipfile.ZipFile(pkg.path) as z:
        root = etree.fromstring(z.read("word/comments.xml"))
    out = {}
    for el in root.iter(W + "comment"):
        cid = el.get(W + "id")
        if cid is not None:
            out[cid] = (el.get(W + "author") or "",
                        el.get(W + "date") or "",
                        "".join(t.text or "" for t in el.iter(W + "t")))
    return out


def compare_document(original_path, roundtripped_path):
    """Findings no paragraph census can see: footnotes, endnotes, comments,
    headers/footers, docProps.

    Footnotes and endnotes are compared as *degradations* -- §3.2 calls them
    text, not formatting, and the single highest-value item in the plan; a
    round trip that drops them must be visible today, not after Stage 4
    lands. Headers/footers and docProps are deferred (the DEFERRED table).
    """
    a = _Package(original_path)
    b = _Package(roundtripped_path)
    findings = []

    def count_refs(root, tag):
        return len(list(root.iter(W + tag)))

    da = a.document
    db = b.document
    for tag, label in (("footnoteReference", "footnotes"),
                       ("endnoteReference", "endnotes")):
        ca, cb = count_refs(da, tag), count_refs(db, tag)
        if ca != cb:
            findings.append(Finding(None, None, "degradation",
                                    f"{label} {ca} -> {cb}"))
    # §7.1: the definitions themselves are text, not decoration -- a round
    # trip that keeps the reference count but empties the note must be
    # visible. Compared by id -> text (the mark run and bookkeeping entries
    # carry no w:t, so real-note text is all that remains).
    for part, label in (("word/footnotes.xml", "footnotes"),
                        ("word/endnotes.xml", "endnotes")):
        na, nb = _real_notes(a, part), _real_notes(b, part)
        if na != nb:
            if len(na) != len(nb):
                findings.append(Finding(None, None, "degradation",
                                        f"{label} definitions {len(na)} -> {len(nb)}"))
            else:
                findings.append(Finding(None, None, "degradation",
                                        f"{label} content changed"))
    comments_a = count_refs(da, "commentReference")
    comments_b = count_refs(db, "commentReference")
    if comments_a != comments_b:
        findings.append(Finding(None, None, "degradation",
                                f"comment references {comments_a} -> {comments_b}"))
    # §7.1: the definitions themselves are text, not decoration -- author,
    # date and body must survive a round trip, not just the reference count.
    # Compared by id -> (author, date, text) like the notes.
    ca, cb = _real_comments(a), _real_comments(b)
    if ca != cb:
        if len(ca) != len(cb):
            findings.append(Finding(None, None, "degradation",
                                    f"comment definitions {len(ca)} -> {len(cb)}"))
        else:
            findings.append(Finding(None, None, "degradation",
                                    f"comment content changed"))

    for part, label in (("word/header1.xml", "header"),
                        ("word/footer1.xml", "footer")):
        if _part_count(a, part) != _part_count(b, part):
            reason, ref = DEFERRED["headers/footers"]
            findings.append(Finding(None, None, "deferred",
                                    f"{label} part {_part_count(a, part)} -> "
                                    f"{_part_count(b, part)} ({reason}; {ref})"))
    props_a = _doc_props(a)
    props_b = _doc_props(b)
    if props_a != props_b:
        reason, ref = DEFERRED["docProps"]
        findings.append(Finding(None, None, "deferred",
                                f"docProps {props_a!r} -> {props_b!r} "
                                f"({reason}; {ref})"))

    noise_a, noise_b = _noise_count(da), _noise_count(db)
    if noise_a != noise_b:
        findings.append(Finding(None, None, "noise",
                                f"noise attributes {noise_a} -> {noise_b}"))
    return findings


def _noise_count(root):
    """Occurrences of NOISE members (PLAN.md §4.2) across all runs.

    Compared as one aggregate per document, never per block: the round trip
    is expected to carry zero (our converter writes none of them), so a
    per-run comparison would emit thousands of identical findings. The count
    keeps the exclusion visible and its "3615 of 3854" justification
    live-measurable -- if a real document's share ever drifts far from it,
    the exclusion's evidence needs re-examination.
    """
    return sum(
        1 for rpr in root.iter(W + "rPr")
        for tag in NOISE if rpr.find(W + tag) is not None
    )


def _doc_props(pkg):
    """(title, creator) from docProps/core.xml, if present."""
    name = "docProps/core.xml"
    if name not in pkg.names:
        return None
    with zipfile.ZipFile(pkg.path) as z:
        root = etree.fromstring(z.read(name))
    core = "{http://purl.org/dc/elements/1.1/}"

    def text(tag):
        el = root.find(core + tag)
        return (el.text or "").strip() if el is not None and el.text else ""

    return (text("title"), text("creator"))


# --- driver ------------------------------------------------------------------


_VERDICT_ORDER = ("identical", "neutral", "improvement",
                  "degradation", "deferred", "noise")


def _sweep(pairs):
    verdicts = Counter()
    kinds = Counter()
    deferred_kinds = Counter()
    per_doc = Counter()
    samples = []
    deferred_samples = []
    for name, src, rt in pairs:
        try:
            findings = compare(src, rt) + compare_document(src, rt)
        except Exception as exc:
            print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
            continue
        for f in findings:
            verdicts[f.verdict] += 1
            if f.verdict == "degradation":
                per_doc[name] += 1
                kinds[f.detail.split(":")[0]] += 1
                if len(samples) < 40:
                    samples.append((name, f.index, f.detail[:130]))
            elif f.verdict == "deferred":
                deferred_kinds[f.detail.split()[0]] += 1
                if len(deferred_samples) < 40:
                    deferred_samples.append((name, f.index, f.detail[:130]))

    print("\nverdicts: " + "  ".join(
        f"{v}={verdicts[v]}" for v in _VERDICT_ORDER))
    print("\ndegradation kinds:")
    for k, v in kinds.most_common():
        print(f"  {v:5}  {k}")
    print("\ndeferred kinds (the standing invoice):")
    for k, v in deferred_kinds.most_common():
        print(f"  {v:5}  {k}")
    print("\nper document (degradations):")
    for k, v in per_doc.most_common():
        print(f"  {v:5}  {k}")
    print("\nsamples:")
    for name, i, d in samples:
        print(f"  [{name}] block {i}: {d}")
    print("\ndeferred samples:")
    for name, i, d in deferred_samples:
        print(f"  [{name}] block {i}: {d}")
    return verdicts


def main(argv):
    if len(argv) >= 3:
        _sweep([(os.path.basename(argv[1]), argv[1], argv[2])])
        return 0
    out_dir = os.path.join(fidelity.PROJECT_ROOT, "output")
    pairs = []
    for src in fidelity.collect_documents():
        stem = os.path.splitext(os.path.basename(src))[0]
        # The same generation-1 files fidelity.py measures, so the two
        # instruments read the same round trips. Derived files live in
        # output/ and are never committed. roundtrip_fresh regenerates when
        # the cache is missing or older than the source/converter code --
        # never measure yesterday's converter (fidelity.roundtrip_stale).
        rt = fidelity.roundtrip_fresh(src, out_dir, generations=1)
        pairs.append((stem, src, rt))
    if not pairs:
        print("no corpus documents found")
        return 1
    _sweep(pairs)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
