r"""Coverage instrument (PLAN.md §4.3): rule 6's three buckets, per direction.

LaTeX side, against a reference macro inventory:

- how many reference macros the parser can name (handled), how many it
  deliberately declines with a written reason (deferred -- `_UNSUPPORTED`),
  and the rest of the reference as the open backlog;
- every macro appearing in math zones of `tests/corpus/` that the parser
  cannot name, with occurrence counts, sorted by frequency;
- every environment name likewise, classified against the document layer's
  known environments.

Word side, over `tests/corpus_docx/`:

- every OOXML element reachable in the corpus parts, classified
  handled / deferred / noise / unknown;
- the same for `w:rPr` and `w:pPr` children specifically.

The unknown bucket is the deliverable. It must print in under a page, and it
must be empty at the end of Stage 4.

Classification sources:

- *handled* on the Word side is "mentioned anywhere in the converter or the
  docfidelity instrument" -- a literal scan of the code for `qw("tag")` /
  `qm("tag")` / `W + "tag"` spellings. Mentioned is a superset of handled:
  a tag that no code mentions is certainly unknown, which is the direction
  that matters.
- *deferred* and *noise* come from `tests/docfidelity.py`'s DEFERRED/NOISE
  tables -- the single authorised membership lists (PLAN.md §4.2). The
  DEFERRED table's keys map to the tags they name; NOISE is exactly the
  five §4.2 members.
- The reference inventory is the active symbol registry. It is deliberately
  read from source rather than a detached snapshot, so this report cannot
  silently depend on a deleted scratch file.
"""

import os
import posixpath
import re
import sys
import zipfile
from collections import Counter

from lxml import etree

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "tests"),
           os.path.join(PROJECT_ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

REFERENCE_FILES = ("latexword/symbols/registry.py",)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

_MACRO_RE = re.compile(r"\\[a-zA-Z]+")
_BEGIN_ENV_RE = re.compile(r"\\begin\{([a-zA-Z*]+)\}")

# Regex-escape and unicode-escape words that a source-doc scan picks up but
# that are not LaTeX macros (appear in the code samples inside the reference
# files). Single-letter control sequences that ARE real LaTeX (`\,` `\;`
# `\:` `\!` `\ ` and the `\$`-class literals) carry punctuation, so no
# letter-only macro is lost by excluding these.
_REGEX_NOISE = set("nrtswdbASWDuzx")


def _scan_macros(text):
    return [m.group(0) for m in _MACRO_RE.finditer(text)]


def _reference_inventory():
    r"""Every `\name` spelling in the reference files, with occurrence counts.

    Counts come from the raw scan, so prose mentions count; an inventory is
    deliberately inclusive -- a spelling that only appears in prose still
    names a macro the parser may need to handle.
    """
    out = Counter()
    for rel in REFERENCE_FILES:
        with open(os.path.join(PROJECT_ROOT, rel), encoding="utf-8") as f:
            for name in _scan_macros(f.read()):
                if name[1:] not in _REGEX_NOISE:
                    out[name] += 1
    return out


def _parser_nameable():
    r"""The parser's macro vocabulary, read from its own resolution tables.

    `latex2omml.parse_macro` consults exactly these, in order: aliases,
    unsupported (declined), n-ary limits modifiers, the special-cased
    `\left`/`\right`/`\pmod`/`\operatorname`/`\mathrm`, variant macros, the
    construct table, escaped literals, and `mathsyms` symbol spellings.

    `\begin`/`\end` are added too: they are document-layer structure -- the
    environment splitter consumes them before the math parser ever sees the
    zone body -- so a zone containing `\begin{aligned}` is not an unknown
    macro. The `\\text{}` escape family (mathsyms.TEXT_ESCAPE_TO_CHAR) is
    scanner-resolved (`_TEXT_NAMED_ESCAPE_RE` in latex2omml), so `parse_macro`
    never dispatches on it; the spellings are still the parser's vocabulary
    and count as nameable.
    """
    from latexword.math import latex2omml as L
    from latexword.mathsyms import TEXT_ESCAPE_TO_CHAR

    out = set(L._MACRO_ALIASES.values())
    # The alias *keys* are part of the vocabulary too: parse_macro rewrites
    # them to their canonical at the top of the chain, so `\rightarrow`
    # (→ \to) and `\le` (→ \leq) are parsed, not unknown.
    out |= set(L._MACRO_ALIASES)
    out |= set(L.MACRO_TO_CHAR)
    out |= set(L._ESCAPED_LITERALS)
    out |= set(L._VARIANT_MACROS)
    out |= set(L.MACRO_TO_CONSTRUCT)
    # The §6.2 fixed-size delimiter family and its separator: parsed by
    # dedicated branches in parse_macro, not by the tables above.
    out |= set(L._BIG_SIZERS)
    out |= set(L._BIG_CLOSER_ONLY)
    out |= {f"\\{spelling}" for spelling in TEXT_ESCAPE_TO_CHAR}
    out |= {"\\left", "\\right", "\\middle", "\\pmod", "\\operatorname",
            "\\mathrm", "\\limits", "\\nolimits",
            "\\begin", "\\end"}  # document-layer structure, see docstring
    return out


def _parser_declined():
    """`_UNSUPPORTED` plus the §6.2 tolerated table: recognised but
    deliberately declined, each with a written reason -- the math side's
    `deferred` bucket (rule 6). (Tolerated macros parse as no-ops with a
    warning; they are declined in the same sense, and their reasons live
    in compat/tolerated.py.)

    The corpus also contains a small amount of pre-separation generated
    input whose preamble declares ``\\linfrac``. That spelling is a removed
    Word carrier, not part of the native parser vocabulary: it is deliberately
    classified here as deferred so the report names the legacy input without
    adding an alias to production parsing or serialization."""
    from latexword.math import latex2omml as L
    from latexword.compat.tolerated import TOLERATED
    declined = dict(L._UNSUPPORTED)
    declined.update(TOLERATED)
    declined[r"\linfrac"] = (
        "legacy generated Word-carrier input; native linear fractions use "
        "a/b and the carrier is rejected by the shadow profile"
    )
    return declined


def _known_environments():
    """Environment names the document layer knows (docx_write consumes what
    docx_read emits, so the consumer's sets are the contract)."""
    from latexword.docx import write as W_
    out = set(W_.MATH_ENVS) | set(W_.MATH_ENVS_KEEP_WRAPPER) | set(W_.LIST_ENVS)
    out |= set(W_.ALIGN_ENVS) | set(W_.MULTICOL_ENVS)
    out |= set(W_.FIGURE_ENVS) | set(W_.TABULAR_ENVS) | set(W_.TRANSPARENT_ENVS)
    out |= {"wstyle"}
    return out


def _latex_numbers():
    """The LaTeX side's structured counts; shared by the renderer and the
    fidelity report's baseline."""
    import mathcorpus
    from fidelity import collect_tex_corpus

    ref = _reference_inventory()
    nameable = _parser_nameable()
    declined = _parser_declined()

    # "how many reference macros the parser can name". nameable mixes
    # spellings with and without a leading backslash ('(', '.', 'Bmatrix'
    # in MACRO_TO_CONSTRUCT alongside '\\alpha', '\\,'), so compare both
    # forms; the bare-name set is built once, not per macro.
    bare_nameable = {k.lstrip("\\") for k in nameable}

    def known(m):
        return m in nameable or m.lstrip("\\") in bare_nameable

    named = {m for m in ref if known(m)}
    backlog = sorted(m for m in ref if not known(m))

    # Corpus macros: every macro inside math zones of tests/corpus/.
    occurrences = Counter()
    envs = Counter()
    zone_count = 0
    for path in collect_tex_corpus():
        with open(path, encoding="utf-8") as f:
            text = f.read()
        zone_count += len(mathcorpus.extract_math(text, source="<corpus>"))
        for zone in mathcorpus.extract_math(text, source="<corpus>"):
            occurrences.update(_scan_macros(zone.tex))
        envs.update(m.group(1) for m in _BEGIN_ENV_RE.finditer(text))

    # The buckets are disjoint: handled + deferred + unknown = total. A
    # declined macro (the deferred bucket) is not unknown -- the old
    # `not known(m)` alone double-counted it once the §6.2 tolerated table
    # made the deferred bucket non-empty for the corpus.
    unknown = Counter({m: c for m, c in occurrences.items()
                       if not known(m) and m not in declined})
    return {
        "ref_total": len(ref),
        "ref_named": len(named & set(ref)),
        "ref_declined": len([m for m in ref if m in declined]),
        "ref_backlog": len(backlog),
        "backlog": [(m, ref[m]) for m in backlog[:25]],
        "backlog_more": len(backlog) - 25,
        "corpus_files": len(list(collect_tex_corpus())),
        "zones": zone_count,
        "distinct": len(occurrences),
        "handled": sum(c for m, c in occurrences.items() if known(m)),
        "deferred": sum(c for m, c in occurrences.items() if m in declined),
        "unknown": sum(unknown.values()),
        "unknown_distinct": len(unknown),
        "unknown_macros": list(unknown.items()),
        "unknown_envs": sorted(
            ((e, c) for e, c in envs.items() if e not in _known_environments()
             and e != "document"), key=lambda kv: -kv[1]),
    }


def latex_side():
    """The LaTeX-side report as text lines."""
    n = _latex_numbers()
    lines = []
    lines.append(f"reference inventory: {n['ref_total']} distinct macros "
                 f"({', '.join(REFERENCE_FILES)})")
    lines.append(f"  parser can name: {n['ref_named']} "
                 f"({100 * n['ref_named'] / n['ref_total']:.1f}%)")
    lines.append(f"  deferred (declined with reason, _UNSUPPORTED): "
                 f"{n['ref_declined']}")
    lines.append(f"  backlog (in reference, not nameable): {n['ref_backlog']}")
    for m, c in n["backlog"]:
        lines.append(f"    {m}   x{c}")
    if n["backlog_more"] > 0:
        lines.append(f"    ... {n['backlog_more']} more")

    lines.append(
        f"\ncorpus tests/corpus/: {n['corpus_files']} files, "
        f"{n['zones']} math zones, {n['distinct']} distinct macros "
        f"({n['handled'] + n['deferred'] + n['unknown']} occurrences)")
    lines.append(f"  handled: {n['handled']}   "
                 f"deferred: {n['deferred']}   "
                 f"unknown: {n['unknown']} ({n['unknown_distinct']} distinct)")
    lines.append("\n  unknown macros (the deliverable), by frequency:")
    for m, c in sorted(n["unknown_macros"], key=lambda kv: -kv[1]):
        lines.append(f"    {c:6}  {m}")
    if not n["unknown_macros"]:
        lines.append("    (none)")

    lines.append(f"\n  environments: {len(n['unknown_envs'])} unknown:")
    for e, c in n["unknown_envs"]:
        lines.append(f"    {c:6}  {e}")
    if not n["unknown_envs"]:
        lines.append("    (none)")
    return lines


# --- Word side ---------------------------------------------------------------

M_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
# Drawing namespaces the image machinery writes and the document layer reads
# (inline pictures, VML picts, their fallbacks). Losses on this surface are
# measured by docfidelity's images-changed findings, so these count as
# handled-with-measured-loss, not silent.
DRAWING_NS = (
    "{http://schemas.openxmlformats.org/drawingml/2006/main}",
    "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}",
    "{http://schemas.openxmlformats.org/drawingml/2006/picture}",
    "{urn:schemas-microsoft-com:vml}",
    "{urn:schemas-microsoft-com:office:office}",
    "{http://schemas.openxmlformats.org/markup-compatibility/2006}",
)

# Parts the round trip regenerates from the python-docx template: their
# every element carries the template's defaults, not the author's choice
# (the docfidelity docProps finding is the same decision at part level).
TEMPLATE_PARTS = frozenset({
    "settings.xml", "webSettings.xml", "fontTable.xml",
    "theme1.xml", "core.xml", "app.xml",
})


def _deferred_tag_names():
    """Element names the docfidelity DEFERRED table invoices: its keys are
    attribute paths like `w:rFonts/w:sz`; every `w:`-prefixed segment names
    an element."""
    import docfidelity
    out = set()
    for key in docfidelity.DEFERRED:
        out.update(re.findall(r"w:([A-Za-z0-9]+)", key))
    return out


# Element-level deferrals beyond docfidelity.DEFERRED's attribute surface.
# Same rule families, decided here so every corpus element gets a class.
# A tag belongs here only when the reason is a true statement about Word
# or about the plan; anything doubtful stays unknown.
WORD_DEFERRED = {
    "ctrlPr": ("Word's per-math-object w:rPr wrapper: carries only rFonts/sz "
               "(§3.3), Word's automatic math italic, and NOISE members; the "
               "rare authored b/color/highlight/strike (122 in the corpus) is "
               "dropped -- invoiced here, not silent", "§3.3/§4.2"),
    "proofErr": ("Word's proofing-status cache, stamped by Word itself",
                 "bookkeeping"),
    "lastRenderedPageBreak": ("Word's page-layout cache, regenerated on save",
                              "bookkeeping"),
    "separator": ("footnote separator: Word's own bookkeeping element",
                  "bookkeeping"),
    "continuationSeparator": ("footnote continuation separator: Word's own "
                              "bookkeeping element", "bookkeeping"),
    # style definitions and the latent-style registry: §3.4 carries style
    # names only, never definitions; the registry is Word's own bookkeeping.
    "styles": ("style definitions are not carried; only names are", "§3.4"),
    "docDefaults": ("style definitions are not carried; only names are", "§3.4"),
    "latentStyles": ("style definitions are not carried; only names are", "§3.4"),
    "lsdException": ("latent-style registry entry: Word's own bookkeeping", "§3.4"),
    "rPrDefault": ("style definitions are not carried; only names are", "§3.4"),
    "pPrDefault": ("style definitions are not carried; only names are", "§3.4"),
    "basedOn": ("style definitions are not carried; only names are", "§3.4"),
    "next": ("style definitions are not carried; only names are", "§3.4"),
    "link": ("style definitions are not carried; only names are", "§3.4"),
    "uiPriority": ("style definitions are not carried; only names are", "§3.4"),
    "qFormat": ("style definitions are not carried; only names are", "§3.4"),
    "semiHidden": ("style definitions are not carried; only names are", "§3.4"),
    "unhideWhenUsed": ("style definitions are not carried; only names are", "§3.4"),
    "webHidden": ("style definitions are not carried; only names are", "§3.4"),
    "altName": ("style definitions are not carried; only names are", "§3.4"),
    # paragraph layout controls: the §3.1 borderline rule decides these the
    # same way docfidelity's keepNext/contextualSpacing entries do.
    "keepLines": ("keep-with-next: a Word layout control", "§3.1"),
    "widowControl": ("widow/orphan control: a Word layout control", "§3.1"),
    "wordWrap": ("word wrap: a Word layout control", "§3.1"),
    "adjustRightInd": ("hyphenation bookkeeping: a Word layout control", "§3.1"),
    "suppressAutoHyphens": ("auto-hyphenation state: a Word layout control", "§3.1"),
    "textAlignment": ("vertical text alignment in line: a Word layout control", "§3.1"),
    "autoSpaceDE": ("CJK auto-spacing: Word's own bookkeeping", "§3.1"),
    "autoSpaceDN": ("CJK auto-spacing: Word's own bookkeeping", "§3.1"),
    "outlineLvl": ("outline level: navigation structure; heading levels are "
                   "carried via style names (§3.2)", "§3.1"),
    "docGrid": ("page grid: a Word layout control", "§3.1"),
    "headerReference": ("headers/footers: part-level content not carried in "
                        "Plan 1", "§3.1"),
    "footerReference": ("headers/footers: part-level content not carried in "
                        "Plan 1", "§3.1"),
    "kern": ("kerning: raised/lowered position and kerning", "§3.3"),
    "caps": ("all-caps: a run text-case effect, not on §3.2's carried list",
             "§3.2"),
    "ligatures": ("OpenType font-feature state, written by Word itself",
                  "bookkeeping"),
    "rsid": ("revision-save tracking id, stamped by Word itself on save",
             "bookkeeping"),
    "footnotePr": ("footnote properties: Word's own bookkeeping", "bookkeeping"),
    "tblLook": ("table style lookup flags: Word's own bookkeeping", "bookkeeping"),
    "tblCellMar": ("cell margins: table layout, not carried", "§7.3"),
    "tblInd": ("table indent: table layout, not carried", "§7.3"),
    "tblW": ("table width: table structure is carried, widths are not", "§7.3"),
    "tblStylePr": ("conditional table style: style definitions are not "
                   "carried", "§3.4"),
    "vAlign": ("cell vertical alignment", "§7.3"),
    "top": ("cell-margin/div extent value: table layout, not carried", "§7.3"),
    "bottom": ("cell-margin/div extent value: table layout, not carried", "§7.3"),
    "left": ("cell-margin/div extent value: table layout, not carried", "§7.3"),
    "right": ("cell-margin/div extent value: table layout, not carried", "§7.3"),
    # §7.3 table-property families the new table machinery reads or defers.
    # The border machinery reads tblBorders and tcBorders (spelled through
    # qw() in docx/read.py, so handled is auto-detected); these are the
    # elements the table layer deliberately does not carry.
    "hideMark": ("cell-merge display marker: Word's own bookkeeping",
                 "bookkeeping"),
    "noWrap": ("cell no-wrap: plain tabular has no per-cell no-wrap",
               "§7.3"),
    "tcMar": ("cell margins: table layout, not carried", "§7.3"),
    "cantSplit": ("row keep-together: a Word layout control", "§3.1"),
    "tblLayout": ("table layout mode: table layout, not carried", "§7.3"),
    "tblCellSpacing": ("cell spacing: table layout, not carried", "§7.3"),
    "autoRedefine": ("table style redefinition flag: Word's own bookkeeping",
                     "bookkeeping"),
    "tblpPr": ("floating table position: table layout, not carried", "§7.3"),
    "tblHeader": ("repeat header row: longtable-level structure, not "
                  "carried", "§7.3"),
    "tblPrEx": ("exceptional row properties: Word's own bookkeeping",
                "bookkeeping"),
    "textDirection": ("cell text direction: not carried", "§7.3"),
    "snapToGrid": ("document-grid snapping: a Word layout control", "§3.1"),
    # m: layout and automatic-styling elements the reverse walker drops with
    # its property-container rule or reads past.
    "maxDist": ("array column geometry: layout, not carried", "§3.3"),
    "scr": ("math script-style marker: Word's automatic math styling",
            "bookkeeping"),
    "eqArr": ("equation array: the walker's fallback keeps the text; "
              "alignment structure is not carried", "many-to-one"),
    "wrapIndent": ("math line-wrap indent: Word's math layout, not carried",
                   "§3.3"),
    "wrapRight": ("math line-wrap side: Word's math layout, not carried",
                  "§3.3"),
    "plcHide": ("placeholder-hide flag on math objects: Word's own "
                "bookkeeping", "bookkeeping"),
    # numbering.xml level detail: markers are re-derived from numFmt; the
    # corpus's 730 level texts are standard Word markers (bullet / %1. /
    # %2.) that re-derive identically, plus 3 authored exceptions
    # ("Appendix %1. ", "%1..%3.") that do not survive.
    "lvlText": ("level marker text: re-derived from numFmt; standard markers "
                "match, the corpus's 3 authored exceptions do not survive",
                "§7.3 lists"),
    "lvlJc": ("level justification: re-derived from numFmt", "§7.3 lists"),
    "start": ("level start value: re-derived; non-1 starts do not survive",
              "§7.3 lists"),
    "suff": ("level suffix: re-derived from numFmt", "§7.3 lists"),
    "nsid": ("numbering template id: Word's own bookkeeping", "bookkeeping"),
    "multiLevelType": ("numbering template id: Word's own bookkeeping",
                       "bookkeeping"),
    "tmpl": ("numbering template id: Word's own bookkeeping", "bookkeeping"),
    "lvlOverride": ("per-document numbering override (restart values): "
                    "re-derived from numFmt; non-default restarts do not "
                    "survive", "§7.3 lists"),
    "startOverride": ("per-document numbering override (restart values): "
                      "re-derived from numFmt; non-default restarts do not "
                      "survive", "§7.3 lists"),
    "legacy": ("numbering compatibility flag: Word's definition bookkeeping", "bookkeeping"),
    "locked": ("style lock flag: Word's definition bookkeeping", "bookkeeping"),
}


def _code_mentioned_tags():
    """Tag spellings the code mentions, across the converters, the reverse
    walker (the OMML->AST loader that replaced the old hand-written walker)
    and the docfidelity instrument: the `qw("x")`-class helpers, the
    `_run_flag(el, "x")` / `_val(el, "x")` / `_find(el, "x")` / `_attr(el,
    "x")` reader helpers, `W + "x"`-style namespace concatenation, and
    `tag == "x"` / `tag in ("a", "b", ...)` dispatches. The loader
    dispatches in tuples (`tag in ("sSub", "sSup", "sSubSup")`), so every
    quoted string inside a `tag in (...)` counts -- the old speller's
    one-tag-per-`==` chain never had a second member to lose."""
    from latexword.docx import read, write
    import importlib
    from latexword.math import ast, latex2omml, omml2latex
    load = importlib.import_module("latexword.math.omml.load")
    import docfidelity
    out = set()
    helper = re.compile(
        r'(?:qw|qm|qn|qa|qwp|qv|_m|_mk)\s*\(\s*["\']([A-Za-z0-9]+)["\']')
    reader = re.compile(
        r'\b(?:run_flag|_run_flag|_val|_find|_attr|_arg)\s*\(\s*[\w.]+\s*,\s*["\']'
        r'([A-Za-z0-9]+)["\']')
    concat = re.compile(r'\b(?:W|M|A|OMML)\s*\+\s*"([A-Za-z0-9]+)"')
    dispatch = re.compile(r'\btag\s*==\s*"([A-Za-z0-9]+)"')
    # One-line `tag in ("a", "b")` tuples only (the loader's style).
    tuple_dispatch = re.compile(r'\btag\s+in\s*\(([^)]*)\)')
    tag_literal = re.compile(r'"([A-Za-z0-9]+)"')
    source_paths = [
        read.__file__, write.__file__, latex2omml.__file__, ast.__file__,
        load.__file__, omml2latex.__file__, docfidelity.__file__,
    ]
    # The document layer is now split by responsibility.  Coverage must
    # inspect every owner, not just the two public facades, or moving a
    # handled dispatch into a component would manufacture thousands of
    # false unknowns (for example run-level `b` and `i`).
    docx_dir = os.path.dirname(read.__file__)
    source_paths.extend(
        os.path.join(docx_dir, name)
        for name in os.listdir(docx_dir)
        if name.endswith(".py")
    )
    for path in source_paths:
        src = open(path, encoding="utf-8").read()
        for pat in (helper, reader, concat, dispatch):
            out.update(pat.findall(src))
        for m in tuple_dispatch.finditer(src):
            out.update(tag_literal.findall(m.group(1)))
    return out


# Tags that are demonstrably handled but never spelled as literals: the
# measurement instrument counts them, or the converter navigates them
# structurally. Each needs a reason.
HANDLED_EXTRA = {
    "r": "runs (w:r/m:r) are the converter's core structure",
    "t": "text (w:t/m:t) is the converter's core structure",
    "p": "paragraphs (w:p/m:p) are the converter's core structure",
    "hyperlink": "read and written; URL escaping is fixed and measured",
    "bookmarkStart": "authored anchors: read as \\label, written as bookmarks (§7.1); Word-generated families are noise",
    "bookmarkEnd": "range close: the start carries the name (§7.1)",
    "footnoteReference": "read by the reverse, written by the forward (§7.1)",
    "footnoteRef": "note mark: written by the forward; read and dropped by the reverse (LaTeX auto-numbers)",
    "sectPr": "read by the document layer; section geometry is measured",
    "cols": "read by the document layer; column count is carried",
    "footnote": "note definition: read and written (§7.1)",
    "endnote": "note definition: read and written (§7.1)",
    "footnotes": "footnote part: read and written (§7.1)",
    "endnotes": "endnote part: read and written (§7.1)",
    "endnoteReference": "read by the reverse, written by the forward (§7.1)",
    "endnoteRef": "note mark: written by the forward; read and dropped by the reverse (LaTeX auto-numbers)",
    "fldChar": "REF/PAGEREF/HYPERLINK fields read and written (§7.1); SEQ and unknown fields keep their cached text with a named warning",
    "instrText": "same as fldChar (§7.1)",
    "fldSimple": "the one-element field form: resolved like the run-group form (§7.1)",
    "vanish": "hidden text: its loss is measured as a degradation",
    "specVanish": "hidden text: its loss is measured as a degradation",
    "document": "part root of the main document, written by the builder",
    "numbering": "numbering part root, read and re-emitted for lists",
    "hdr": "header part root, deferred at part level",
    "ftr": "footer part root, deferred at part level",
    "name": "style names: the §3.4 day-one carried surface",
    "body": "document body: the builder's core structure",
    "tbl": "tables are carried and compared (§7.3)",
    "tr": "table rows are carried and compared (§7.3)",
    "tc": "table cells are carried and compared (§7.3)",
    "tblGrid": "table column grid is carried and compared (§7.3)",
    "gridCol": "table column grid is carried and compared (§7.3)",
    "tcPr": "cell property container, managed by the table machinery (§7.3)",
    "trPr": "row property container, managed by the table machinery (§7.3)",
    "insideH": "interior horizontal borders: the §7.3 union rule reads them "
    "and the border machinery writes them",
    "insideV": "interior vertical borders: the §7.3 union rule reads them "
    "and the border machinery writes them",
    "glossaryDocument": "glossary package content is preserved through the Word-object sidecar",
    "object": "embedded OLE roots are preserved through the Word-object sidecar",
}


def _part_policy(part_name):
    """None: classify per element. A reason string: the whole part is
    deferred at part level."""
    base = os.path.basename(part_name)
    if base in TEMPLATE_PARTS:
        return ("regenerated from the python-docx template: carries the "
                "template's defaults, not the author's choice", "§3.3")
    if base.startswith("header") or base.startswith("footer"):
        return ("part-level content not carried in Plan 1", "§3.1")
    return None


def _corpus_parts():
    """(part_name, root) for every xml part under word/ in each corpus doc."""
    from fidelity import collect_documents
    for path in collect_documents():
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.startswith("word/") and name.endswith(".xml") \
                        and "/_rels/" not in name:
                    yield name, etree.fromstring(z.read(name))


def _opaque_package_parts():
    """Return XML parts reached from a handled object relationship graph.

    This is the coverage equivalent of the sidecar's transitive closure. It
    is deliberately relationship-driven: chart and embedding parts are not
    blanket-allowlisted by directory name.
    """
    from fidelity import collect_documents

    out = set()
    rel_ns = "{http://schemas.openxmlformats.org/package/2006/relationships}"
    r_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

    def rels_for(archive, source):
        folder, base = posixpath.split(source)
        name = posixpath.join(folder, "_rels", base + ".rels")
        if name not in archive.namelist():
            return []
        root = etree.fromstring(archive.read(name))
        result = []
        for rel in root.findall(rel_ns + "Relationship"):
            target = rel.get("Target", "")
            if (rel.get("TargetMode") or "").lower() == "external":
                resolved = None
            else:
                raw = target.replace("\\", "/")
                candidate = raw.lstrip("/") if raw.startswith("/") else posixpath.join(
                    posixpath.dirname(source), raw
                )
                resolved = posixpath.normpath(candidate)
            result.append((rel.get("Id"), resolved))
        return result

    for path in collect_documents():
        with zipfile.ZipFile(path) as archive:
            if "word/glossary/document.xml" in archive.namelist():
                out.update(
                    name for name in archive.namelist()
                    if name.startswith("word/glossary/") and name.endswith(".xml")
                )
            root = etree.fromstring(archive.read("word/document.xml"))
            used = set()
            for element in root.iter():
                if element.tag.rsplit("}", 1)[-1] not in {
                    "sdt", "object", "drawing", "pict", "AlternateContent",
                }:
                    continue
                for descendant in element.iter():
                    for attr, value in descendant.attrib.items():
                        if attr.startswith(r_ns) and attr.rsplit("}", 1)[-1] in {
                            "id", "embed", "link",
                        }:
                            used.add(value)
            pending = [("word/document.xml", used)]
            seen = set()
            while pending:
                source, wanted = pending.pop()
                if source in seen:
                    continue
                seen.add(source)
                for rid, target in rels_for(archive, source):
                    if rid not in wanted or target is None or target not in archive.namelist():
                        continue
                    out.add(target)
                    try:
                        target_root = etree.fromstring(archive.read(target))
                    except etree.XMLSyntaxError:
                        continue
                    nested = set()
                    for descendant in target_root.iter():
                        for attr, value in descendant.attrib.items():
                            if attr.startswith(r_ns) and attr.rsplit("}", 1)[-1] in {
                                "id", "embed", "link",
                            }:
                                nested.add(value)
                    pending.append((target, nested))
    return out


def _word_numbers():
    """The Word side's structured counts; shared by the renderer and the
    fidelity report's baseline.

    Elements are classified by (namespace, local name): `r` in the w:
    namespace and in m: are different surfaces. Parts regenerated from the
    python-docx template (theme, settings, ...) and header/footer parts are
    deferred at part level -- their elements never reach unknown."""
    import docfidelity
    mentioned = _code_mentioned_tags()
    deferred = set(_deferred_tag_names()) | set(WORD_DEFERRED)
    handled_extra = set(HANDLED_EXTRA)
    noise = set(docfidelity.NOISE)

    elements = Counter()
    owned_counts = Counter()
    opaque_parts = _opaque_package_parts()
    part_deferred = Counter()
    rpr_children = Counter()
    ppr_children = Counter()
    for part, root in _corpus_parts():
        policy = _part_policy(part)
        for el in root.iter():
            ns, name = el.tag.rsplit("}", 1)
            if policy is not None:
                part_deferred[(ns, name)] += 1
                continue
            elements[(ns, name)] += 1
            if part in opaque_parts:
                owned_counts[(ns, name)] += 1
                continue
            parent = el.getparent()
            while parent is not None:
                if parent.tag.rsplit("}", 1)[-1] in {
                    "sdt", "object", "drawing", "pict", "AlternateContent",
                    "glossaryDocument",
                }:
                    owned_counts[(ns, name)] += 1
                    break
                parent = parent.getparent()
        if policy is None:
            for rpr in root.iter(W + "rPr"):
                for child in rpr:
                    rpr_children[child.tag.rsplit("}", 1)[-1]] += 1
            for ppr in root.iter(W + "pPr"):
                for child in ppr:
                    ppr_children[child.tag.rsplit("}", 1)[-1]] += 1

    def classify(name, ns):
        # Word's own extension namespaces (w14:/w15:/w16:, the Microsoft
        # wordml and drawingml namespaces) carry the same element semantics
        # as their w:/a: parents -- classify them identically.
        if ns.startswith("{http://schemas.microsoft.com/office/word/"):
            ns = W[:-1]
        if ns.startswith("{http://schemas.microsoft.com/office/drawing/"):
            return "handled"  # drawing extensions: image machinery, measured
        if ns == W[:-1]:
            if name in noise:
                return "noise"
            if name in deferred or name in handled_extra:
                return "handled" if name in handled_extra else "deferred"
            if name in mentioned:
                return "handled"
            return "unknown"
        if ns == M_NS[:-1]:
            if name.endswith("Pr"):
                # the walker's property-container rule (to_latex:
                # `tag.endswith("Pr")` returns "") consumes these
                return "handled"
            if name in deferred or name in mentioned:
                return "deferred" if name in deferred else "handled"
            return "unknown"
        if ns in (d[:-1] for d in DRAWING_NS):
            return "handled"  # image machinery, loss measured as images-changed
        return "unknown"

    by_class = Counter()
    unknown = Counter()
    for (ns, name), count in elements.items():
        owned = min(owned_counts[(ns, name)], count)
        by_class["handled"] += owned
        cls = classify(name, ns)
        remaining = count - owned
        by_class[cls] += remaining
        if cls == "unknown" and remaining:
            unknown[(ns, name)] += remaining

    rpr_by = Counter()
    for name, count in rpr_children.items():
        rpr_by[classify(name, W[:-1])] += count
    ppr_by = Counter()
    for name, count in ppr_children.items():
        ppr_by[classify(name, W[:-1])] += count

    def _unknown_list(counter):
        return sorted(((n, c) for n, c in counter.items()
                       if classify(n, W[:-1]) == "unknown"),
                      key=lambda kv: -kv[1])

    return {
        "distinct": len(elements),
        "handled": by_class["handled"],
        "deferred": by_class["deferred"],
        "noise": by_class["noise"],
        "unknown": by_class["unknown"],
        "part_deferred": sum(part_deferred.values()),
        "unknown_items": sorted(unknown.items(), key=lambda kv: -kv[1]),
        "rpr": dict(rpr_by),
        "ppr": dict(ppr_by),
        "rpr_unknown": _unknown_list(rpr_children),
        "ppr_unknown": _unknown_list(ppr_children),
    }


def word_side():
    """The Word-side report as text lines."""
    n = _word_numbers()
    lines = []
    lines.append(
        f"all elements: {n['distinct']} distinct (ns, tag) pairs, "
        + "  ".join(f"{k}={n[k]}" for k in
                    ("handled", "deferred", "noise", "unknown"))
        + f"  part-deferred={n['part_deferred']}")
    lines.append("  unknown (the deliverable):")
    for (ns, name), count in n["unknown_items"]:
        short_ns = {W[:-1]: "w:", M_NS[:-1]: "m:"}.get(ns, "?")
        lines.append(f"    {count:6}  {short_ns}{name}")
    if not n["unknown_items"]:
        lines.append("    (none)")

    for title, key, ukey in (("w:rPr children", "rpr", "rpr_unknown"),
                             ("w:pPr children", "ppr", "ppr_unknown")):
        by = n[key]
        lines.append(f"{title}: {sum(by.values())} occurrences, "
                     + "  ".join(f"{k}={by.get(k, 0)}" for k in
                                 ("handled", "deferred", "noise", "unknown")))
        lines.append("  unknown:")
        for n_, c in n[ukey]:
            lines.append(f"    {c:6}  {n_}")
        if not n[ukey]:
            lines.append("    (none)")
    return lines


if __name__ == "__main__":
    print("\n".join(latex_side()))
    print("\nWord side (corpus_docx):")
    print("\n".join(word_side()))
