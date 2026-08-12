"""Fidelity: does math in a hand-authored `.docx` survive a round trip?

Every other check in this project compares our output against our own output
(A1 fixed point, A2 gen1-vs-gen2, A3 a table property). None of them uses the
*original* document as the baseline, so a system that degrades a formula
consistently in both directions stays green in all of them. That is not
hypothetical: the lost n-ary `limLoc`/`grow`/`subHide` properties were found by
the R3 oracle -- the one check with an external baseline -- while A1 and A2
were passing.

This module supplies the missing baseline. It pairs each `m:oMath` in the
original document with the same one after N round trips and *classifies* the
difference instead of testing equality, because equality is the wrong bar:
cosmetic change is acceptable, deliberate improvement is wanted, and only
degradation is a failure.

    identical    the trees match
    improvement  a listed, intended transformation (see IMPROVEMENTS)
    neutral      run splitting, explicit-vs-default properties, whitespace
    degradation  content or structure lost -- this is what must be zero

`collect_documents` takes a directory, so more `.docx` can simply be dropped
in `tests/corpus_docx/` and they are reported individually.
"""

import os
import re
import sys
import zipfile
from collections import Counter, namedtuple
from difflib import SequenceMatcher

from lxml import etree

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
VAL = M + "val"

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

# The two corpus directories. Both are discovered by scanning: nothing in this
# project may name a corpus document. The documents are the user's own private
# files, they get renamed for privacy and new ones get added, and a literal
# filename anywhere in the tree is both a privacy leak and a reference that
# silently rots the next time the corpus changes. Identify a document at
# runtime by its basename if a report needs to name it; never in source.
DOCX_CORPUS_DIR = os.path.join(TESTS_DIR, "corpus_docx")
TEX_CORPUS_DIR = os.path.join(TESTS_DIR, "corpus")


def _scan(directory, suffix):
    """Every file with `suffix` in `directory`, sorted, Word lock files
    (`~$...`) excluded. Empty list if the directory does not exist -- a
    checkout without the private corpus must still import and run."""
    if not os.path.isdir(directory):
        return []
    return [os.path.join(directory, n) for n in sorted(os.listdir(directory))
            if n.lower().endswith(suffix) and not n.startswith("~$")]


def collect_documents():
    """Every `.docx` to be checked, found by scanning `tests/corpus_docx/`."""
    return _scan(DOCX_CORPUS_DIR, ".docx")


def collect_fixtures():
    """The checked-in `.tex` fixtures -- project-authored, no private content,
    and the conformance baseline the parser must never regress on."""
    return _scan(os.path.join(TESTS_DIR, "fixtures"), ".tex")


def collect_tex_corpus():
    """The `.tex` tolerance benchmark in `tests/corpus/`: arbitrary,
    AI-generated, non-canonical LaTeX. Separate from `collect_fixtures`
    because this set is allowed to contain input the parser cannot yet
    handle -- it measures how far tolerance has to go, it is not a pass/fail
    baseline."""
    return _scan(TEX_CORPUS_DIR, ".tex")


# --- reading math out of a .docx --------------------------------------------


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _in_generated_toc(el):
    """Is this math zone part of an auto-generated table of contents?

    Word builds the TOC from the headings and rebuilds it on demand, so a
    formula appearing there is a *copy* of one in a heading, not authored
    content. Comparing it means measuring the same formula twice and, worse,
    demanding that the converter transcribe a field it should be regenerating
    (`\\tableofcontents`) instead.

    Keyed on the paragraph style rather than on the `w:sdt` wrapper, so a
    hand-styled TOC is caught too and an ordinary content control is not.
    """
    node = el
    while node is not None:
        if node.tag == W + "p":
            style = node.find(W + "pPr/" + W + "pStyle")
            val = style.get(W + "val") if style is not None else ""
            return bool(val) and val.upper().startswith("TOC")
        node = node.getparent()
    return False


def read_math_zones(docx_path):
    """Every authored `m:oMath` element in the document, in body order.

    Read straight from `word/document.xml` rather than through python-docx:
    the point is to see exactly what is stored, with no library normalising
    anything on the way past.
    """
    with zipfile.ZipFile(docx_path) as z:
        xml = z.read("word/document.xml")
    root = etree.fromstring(xml)
    return [z for z in root.findall(".//" + M + "oMath")
            if not _in_generated_toc(z)]


def tag(el):
    t = el.tag
    return t[len(M):] if isinstance(t, str) and t.startswith(M) else str(t)


# Character-level normalisations that are *not* content changes. Each one is
# a rewrite we make deliberately and would make again; listing them here is
# what keeps them from being counted as damage, and keeps anything unlisted
# from being waved through.
#
# U+002D -> U+2212 is the big one: a hand-typed hyphen-minus becoming the real
# mathematical minus sign. Word's own equation editor produces U+2212, so this
# moves *toward* what Word would have written, not away from it.
TEXT_EQUIVALENCES = {
    "-": "−",   # hyphen-minus -> minus sign
    "·": "⋅",   # middle dot -> dot operator
    "’": "′",   # right single quote -> prime
    # ASCII apostrophe -> prime: Word's own equation editor autocorrects a
    # typed "'" to U+2032 PRIME, same reasoning as the hyphen-minus entry
    # above -- this moves *toward* what Word would have written, not away
    # from it. Added only after confirming (post defect-1 fix, which
    # resolved the two zones where this used to co-occur with real prose-
    # replacement corruption) that every remaining zone in this class differs
    # from the original *solely* by this swap, with nothing else lost or
    # gained -- see DEFECTS.md defect 3.
    "'": "′",
}


def _normalise_text(s):
    for a, b in TEXT_EQUIVALENCES.items():
        s = s.replace(a, b)
    # Run splitting legitimately moves whitespace between runs, and Word
    # renders math spacing from structure rather than from space characters.
    return re.sub(r"\s+", "", s)


# Word's default delimiters when `m:d` carries no `begChr`/`endChr`.
_D_DEFAULTS = ("(", ")")


def _text_parts(el, out):
    """Walk a math zone collecting every character Word actually *draws*.

    `m:t` runs are not the whole story: an `m:d` stores its brackets as
    properties (`m:begChr`/`m:endChr`), not as text. Counting only `m:t`
    therefore reports a formula whose bare `(`/`)` runs became a real
    delimiter object -- the D2 improvement this project deliberately makes --
    as *losing* two characters. That is a defect in the measurement, not in
    the converter, and it accounted for 7 of the reported degradations.

    Only `m:d` is unfolded here. An n-ary's operator or an accent's mark are
    also drawn-but-not-`m:t`, but losing either is already caught as an object
    loss by `object_census`, so folding them in would double-count rather than
    reveal anything new.
    """
    for child in el:
        t = tag(child)
        if t == "t":
            out.append(child.text or "")
        elif t.endswith("Pr"):
            continue
        elif t == "d":
            pr = child.find(M + "dPr")
            beg, end = _D_DEFAULTS
            if pr is not None:
                b, e = pr.find(M + "begChr"), pr.find(M + "endChr")
                if b is not None:
                    beg = b.get(VAL) or ""
                if e is not None:
                    end = e.get(VAL) or ""
            out.append(beg)
            _text_parts(child, out)
            out.append(end)
        else:
            _text_parts(child, out)


def text_of(el, normalise=False):
    """Every character the zone draws. Character loss is the most damaging
    failure mode and the easiest to detect, so it is measured separately
    from structure."""
    parts = []
    _text_parts(el, parts)
    s = "".join(parts)
    return _normalise_text(s) if normalise else s


# OOXML booleans accept 1/0, on/off and true/false interchangeably. Comparing
# them as raw strings reports a property as "lost" when it is merely spelled
# differently, which is noise, not a finding.
_BOOL_TRUE = {"1", "on", "true"}
_BOOL_FALSE = {"0", "off", "false"}

# ...but only for properties that *are* booleans. `m:count` is a column count,
# so blanket normalisation turned a one-column matrix into `count=on` -- an
# unreadable finding, and one that would have compared equal to `count=true`.
_NUMERIC_PROPS = frozenset({"count"})


def _norm_val(v, prop=None):
    if v is None:
        return None
    if prop in _NUMERIC_PROPS:
        return v.strip()
    lv = v.strip().lower()
    if lv in _BOOL_TRUE:
        return "on"
    if lv in _BOOL_FALSE:
        return "off"
    return v


# Property children whose absence changes how Word lays the formula out. These
# are the ones whose loss is a degradation rather than a cosmetic difference:
# `limLoc` moves n-ary limits between beside and above/below, `grow` decides
# whether the operator stretches to its operand, `count`/`mcJc` define a
# matrix's columns, and the `*Hide` family suppresses Word's dotted
# placeholder boxes.
LAYOUT_PROPS = frozenset({
    "limLoc", "grow", "subHide", "supHide", "degHide", "plcHide",
    "count", "mcJc", "baseJc", "pos", "type", "begChr", "endChr", "chr",
})

# Element types that are real Word equation objects. One of these turning into
# plain runs is the D1 failure mode -- structurally valid, visibly wrong.
OBJECT_TAGS = frozenset({
    "sSub", "sSup", "sSubSup", "sPre", "f", "rad", "nary", "d", "func",
    "acc", "bar", "limLow", "limUpp", "groupChr", "m",
})


def object_census(el):
    """How many of each real equation object the zone contains."""
    return Counter(tag(x) for x in el.iter() if tag(x) in OBJECT_TAGS)


def scope_census(el):
    """For every equation object, *what it covers* -- (tag, its subtree text).

    `object_census` counts tags and `text_of` flattens the whole zone, so
    between them they are blind to the single most damaging failure mode this
    converter has: re-parenting. Moving a factor out of `m:func/m:e` (the
    limit stops applying to it) or sweeping the rest of the row into
    `m:nary/m:e` (the integral swallows the `=` and everything after it)
    changes neither the tag multiset nor the flattened character sequence, so
    both were classified `identical` while Word rendered a different formula.
    Two such corruptions shipped undetected.

    Keying each object by the text it spans makes scope a first-class part of
    the comparison: the `m:func` that used to cover `lim...(2w+ht)(w-ht)` and
    now covers only `lim...(2w+ht)` is a *lost* entry, not a matching one.
    """
    return Counter(
        (tag(x), text_of(x, normalise=True))
        for x in el.iter() if tag(x) in OBJECT_TAGS
    )


# Whitespace width classes. `_normalise_text` strips whitespace entirely --
# correct for the character-loss check, since run splitting legitimately moves
# spaces between runs, but it also made a literal space rewritten as an EM
# space (a visibly huge gap in Word) and a dropped EM QUAD both invisible.
# Width, not identity, is what a reader sees, so spaces are compared as a
# multiset of width buckets: same bucket is noise, different bucket is damage.
_SPACE_WIDTHS = {
    " ": "thin", " ": "thin", " ": "thin",
    " ": "mid", " ": "mid", " ": "mid",
    " ": "wide", " ": "wide", " ": "mid",
    " ": "normal", " ": "normal", " ": "normal",
    " ": "thin", "\t": "wide",
}


def space_census(el):
    """Multiset of whitespace width classes the zone draws."""
    out = Counter()
    for ch in text_of(el):
        if ch.isspace() or ch in _SPACE_WIDTHS:
            out[_SPACE_WIDTHS.get(ch, "normal")] += 1
    return out


def layout_census(el):
    """Layout-affecting property values present in the zone."""
    out = Counter()
    for x in el.iter():
        t = tag(x)
        if t in LAYOUT_PROPS:
            out[f"{t}={_norm_val(x.get(VAL), t)}"] += 1
    return out


# --- classification ----------------------------------------------------------

# Transformations we intend. Each is a (gained, lost) predicate on the object
# census, written down so that an *unlisted* change can never be mistaken for
# one of these. Keep this list short and specific; a broad entry here would
# defeat the whole check.
IMPROVEMENTS = [
    (
        "bare delimiters become a real m:d",
        lambda gained, lost, _o, _n: gained.get("d", 0) > 0 and not lost,
    ),
    (
        "loose operator-name runs become m:func (D1)",
        lambda gained, lost, _o, _n: gained.get("func", 0) > 0 and not lost,
    ),
    (
        "brace-glyph limLow/limUpp becomes m:groupChr (D3)",
        lambda gained, lost, _o, _n: (
            gained.get("groupChr", 0) > 0
            and set(lost) <= {"limLow", "limUpp"}
        ),
    ),
]

# Closing delimiters a script can be attached to in a hand-authored document.
_CLOSERS = set(")]}|⟩⌋⌉")

_SCRIPT_TAGS = frozenset({"sSub", "sSup", "sSubSup"})


def _intended_scope_change(entry, n_scope):
    """Is this widened span the B1 scripted-closer improvement?

    Word lets an author attach a subscript to the bare `]` run of `[f(y)]`,
    so the script's base is the closing bracket alone. We rebuild the bracket
    as a real `m:d` and attach the script to the whole delimiter object, which
    is what the author meant and what LaTeX can express -- see
    `tests/test_b1_scripted_closer.py`.

    Deliberately narrow: the tag must be a script, the old span must *start*
    with a closing delimiter, and the new span must end with the old one. A
    looser test here would forgive exactly the re-parenting this census exists
    to catch.
    """
    t, span = entry
    if t not in _SCRIPT_TAGS or not span or span[0] not in _CLOSERS:
        return False
    return any(tg == t and s != span and s.endswith(span) for tg, s in n_scope)


Finding = namedtuple("Finding", "index verdict detail")


def classify(original, roundtripped):
    """Classify one math zone's round trip. Returns (verdict, detail)."""
    o_obj, n_obj = object_census(original), object_census(roundtripped)
    o_lay, n_lay = layout_census(original), layout_census(roundtripped)
    o_scope, n_scope = scope_census(original), scope_census(roundtripped)
    o_sp, n_sp = space_census(original), space_census(roundtripped)

    # 1. Text loss is unconditionally a degradation -- no improvement removes
    #    characters, so this is checked before anything else. Whitespace and
    #    the listed character equivalences are normalised away first; what
    #    remains is real content change.
    o_sq, n_sq = text_of(original, True), text_of(roundtripped, True)
    if o_sq != n_sq:
        return "degradation", (
            f"text changed: {text_of(original)[:80]!r} -> "
            f"{text_of(roundtripped)[:80]!r}"
        )

    gained = n_obj - o_obj
    lost = o_obj - n_obj
    lay_lost = o_lay - n_lay

    # 2. A real equation object disappearing is the D1 failure mode.
    if lost and not gained:
        return "degradation", f"equation objects lost: {dict(lost)}"

    # 3. A layout property dropped changes what Word draws even when the tree
    #    is otherwise intact -- this is the n-ary limLoc/grow class.
    if lay_lost:
        return "degradation", f"layout properties lost: {dict(lay_lost)}"

    # 4. An object that used to cover a different span of characters is a
    #    re-parenting: the tree is intact, every object is still there, every
    #    character is still there, and Word draws a different formula. Tags
    #    that disappeared outright are excluded here because steps 2/5 own
    #    that case -- otherwise the D3 groupChr improvement, which really does
    #    retire a limLow/limUpp, would be reported twice.
    scope_lost = Counter({k: v for k, v in (o_scope - n_scope).items()
                          if k[0] not in lost
                          and not _intended_scope_change(k, n_scope)})
    if scope_lost:
        (t, span), _ = scope_lost.most_common(1)[0]
        # Report the *nearest* surviving object of the same type, not an
        # arbitrary one -- a zone with three m:func nodes would otherwise
        # blame whichever sorted first and read like an unrelated formula.
        candidates = [s for (tg, s) in n_scope if tg == t]
        now = max(candidates,
                  key=lambda s: SequenceMatcher(None, span, s).ratio(),
                  default=None)
        return "degradation", (
            f"scope changed: m:{t} covered {span[:60]!r}, "
            f"now covers {(now[:60] if now is not None else '<nothing>')!r}"
        )

    # 5. Whitespace the reader can see. Compared by width class, not by
    #    identity, so a space merely moving between runs stays invisible while
    #    a space rewritten to a different width -- or dropped -- does not.
    sp_lost, sp_gained = o_sp - n_sp, n_sp - o_sp
    if sp_lost:
        return "degradation", (
            f"spacing changed: lost {dict(sp_lost)}, gained {dict(sp_gained)}"
        )

    if not gained and not lost:
        return "identical" if o_obj == n_obj else "neutral", ""

    for name, pred in IMPROVEMENTS:
        if pred(gained, lost, o_obj, n_obj):
            return "improvement", name

    if lost:
        return "degradation", f"objects changed: -{dict(lost)} +{dict(gained)}"
    return "neutral", f"objects gained: {dict(gained)}"


def compare(original_path, roundtripped_path):
    """Pair the math zones of two documents and classify each pair.

    Pairing is by content alignment, not by index. A single dropped zone
    shifts every later index by one, and naive positional pairing then reports
    every remaining formula as damaged -- hundreds of findings from one real
    defect, with the real defect buried. Aligning on normalised text isolates
    the drop and lets the rest be compared honestly.
    """
    import difflib

    a = read_math_zones(original_path)
    b = read_math_zones(roundtripped_path)
    ka = [text_of(x, True) for x in a]
    kb = [text_of(y, True) for y in b]

    findings = []
    sm = difflib.SequenceMatcher(None, ka, kb, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for off in range(i2 - i1):
                verdict, detail = classify(a[i1 + off], b[j1 + off])
                findings.append(Finding(i1 + off, verdict, detail))
        elif op == "replace":
            # Same count on both sides: a genuine content change, compared
            # pairwise. Different counts: zones were merged or split.
            n = min(i2 - i1, j2 - j1)
            for off in range(n):
                verdict, detail = classify(a[i1 + off], b[j1 + off])
                findings.append(Finding(i1 + off, verdict, detail))
            for k in range(i1 + n, i2):
                findings.append(Finding(k, "degradation", "math zone lost"))
            for k in range(j1 + n, j2):
                findings.append(Finding(k, "degradation", "math zone appeared"))
        elif op == "delete":
            for k in range(i1, i2):
                findings.append(Finding(
                    k, "degradation",
                    f"math zone lost: {text_of(a[k])[:80]!r}"))
        elif op == "insert":
            for k in range(j1, j2):
                findings.append(Finding(
                    k, "degradation",
                    f"math zone appeared: {text_of(b[k])[:80]!r}"))
    return findings


def roundtrip(docx_path, out_dir, generations=1):
    """docx -> tex -> docx, `generations` times. Returns the final .docx path."""
    from latexword.docx import write as latex2word
    from latexword.docx import read as word2latex

    os.makedirs(out_dir, exist_ok=True)
    stem = re.sub(r"[^\w]+", "_", os.path.splitext(os.path.basename(docx_path))[0])
    current = docx_path
    for gen in range(1, generations + 1):
        tex_path = os.path.join(out_dir, f"{stem}_g{gen}.tex")
        # tex_path is required, not optional: without it figures extract next
        # to the *private source document* (PLAN.md Appendix B).
        tex, _warnings = word2latex.docx_to_latex(current, tex_path=tex_path)
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex)
        docx_out = os.path.join(out_dir, f"{stem}_g{gen}.docx")
        latex2word.convert_latex_to_docx(
            tex_path, docx_out, docx_path, reference_mode="copy"
        )
        current = docx_out
    return current


def _newest_converter_mtime():
    """The newest mtime among the files a round trip is derived from: the
    `latexword` package plus this module's own `roundtrip` implementation.
    One global bound, not per-file -- a one-line change anywhere in the
    converter makes every cached generation stale."""
    newest = os.path.getmtime(os.path.abspath(__file__))
    for base in ("latexword",):
        pkg = os.path.join(PROJECT_ROOT, base)
        for root, _dirs, files in os.walk(pkg):
            for name in files:
                if name.endswith(".py"):
                    newest = max(newest, os.path.getmtime(
                        os.path.join(root, name)))
    return newest


def roundtrip_fresh(docx_path, out_dir, generations=1):
    """`roundtrip` when the cached output is missing or stale, else the
    cached path. Stale means the cached file predates the source document
    or any line of converter code: the round trips measure the *converter*,
    and re-reading a cached file silently re-measures yesterday's code
    (that happened twice during §7.3 before the cache was noticed)."""
    stem = re.sub(r"[^\w]+", "_",
                  os.path.splitext(os.path.basename(docx_path))[0])
    rt = os.path.join(out_dir, f"{stem}_g{generations}.docx")
    if (not os.path.exists(rt)
            or os.path.getmtime(rt) < os.path.getmtime(docx_path)
            or os.path.getmtime(rt) < _newest_converter_mtime()):
        return roundtrip(docx_path, out_dir, generations)
    return rt
