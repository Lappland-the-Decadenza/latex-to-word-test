"""Convert a LaTeX document into a .docx with native, editable Word equations.

Production pipeline: LaTeX -> AST -> OMML -> python-docx.  The optional old
MathML/XSL pipeline is kept only for development-time rendering comparisons;
it is never imported by the production path.

Usage:  python latex2word.py input.tex [output.docx] [--reference-doc template.docx]
         [--reference-mode rewrite|copy]
"""

import os
import re
from copy import deepcopy

import docx
import docx.enum.style
from docx import Document
from docx.table import _Cell
from docx.text.paragraph import Paragraph
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.opc.constants import CONTENT_TYPE
from docx.opc.packuri import PackURI
from docx.opc.part import XmlPart
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.shared import Cm, Emu, Pt, RGBColor
from lxml import etree

from ..math import latex2omml
from ..math.errors import MathError
from ..document.text import href_unescape as _href_unescape
from .package import (
    DocxPackageError,
    clear_reference_body as _clear_reference_body,
    validate_docx_package,
)
from ..document.model import paragraph_from_text, paragraph_text
from .inline import (
    add_inline_latex as _render_inline_latex,
    _find_brace as _inline_find_brace,
    _find_bracket as _inline_find_bracket,
    parse_image_args as _parse_inline_image_args,
    strip_comments as _inline_strip_comments,
)
from . import tables as _tables
from . import blocks as _blocks
from .images import add_inline_picture as _insert_inline_picture
from .numbering import (
    ENUM_DEFAULT_NUMFMT_BY_DEPTH, LABEL_TO_NUMFMT, apply_list_level,
    parse_list_label,
)
from .state import BuilderState
from ..math.omml.repair import postprocess_omml as _repair_omml
from ..sidecar import ObjectStore
from .styles import (
    HIGHLIGHT_NAME_TO_WD,
    SCRIPT_CMDS,
    STYLE_CMDS,
    _apply_shading,
    _ensure_hyperlink_style,
    _ensure_named_style,
    _ensure_table_style,
    _resolve_color,
    _set_paragraph_style_id,
    _style_supplies_numbering,
)

OMML_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"

_XSL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "legacy", "MML2OMML.XSL",
)
_transform = None


def _m(tag):
    return f"{{{OMML_NS}}}{tag}"


def _get_transform():
    global _transform
    if _transform is None:
        _transform = etree.XSLT(etree.parse(_XSL_PATH))
    return _transform


def _postprocess_omml(root):
    return _repair_omml(root)


# --- Math conversion --------------------------------------------------------
def legacy_latex_math_to_omml(tex, display="inline"):
    """The pre-R4 pipeline: ``latex2mathml`` -> ``mathml_normalize`` ->
    ``MML2OMML.XSL``. **Not on the sync path.** Per ``REWRITE_FORWARD.md``
    (stage R4), ``latex_math_to_omml`` below now goes through
    ``latex2omml.emit(latex2omml.parse(tex))`` instead. This function is
    kept, unrenamed in behaviour, purely as an import-only path for foreign
    ``.tex`` whose input is genuinely arbitrary (not authored to the
    ``CANONICAL.md`` grammar `latex2omml.parse` accepts) -- see the
    "Module layout" section of ``REWRITE_FORWARD.md``. Do not call this from
    anywhere on the forward-conversion path used by ``DocxBuilder``.

    Never raises: every step from ``latex2mathml`` parsing through the XSL
    transform is covered by one broad ``except Exception``, not just the
    two calls historically wrapped here. ``latex2mathml`` 3.81.0 emits
    invalid XML (a raw, unescaped ``&`` inside an ``<mi>``) for
    ``\\begin{aligned}``/``\\begin{gathered}`` -- an upstream bug -- which
    used to escape as an uncaught ``XMLSyntaxError`` from ``etree.fromstring``
    below and kill the conversion of the entire document over one bad
    formula (defect B9). Every caller of this function already falls back
    to literal monospaced LaTeX plus a warning on ``MathError``; the fix is
    making sure every failure mode actually becomes one.
    """
    tex = tex.strip()
    if not tex:
        raise MathError("empty math")
    try:
        # This oracle is intentionally optional.  The active converter is the
        # direct AST -> OMML path below and must work without the private
        # legacy tree or its MathML dependency.
        import latex2mathml.converter as legacy_converter
        from legacy.mathml_normalize import normalize as legacy_normalize

        mathml = legacy_converter.convert(tex, display=display)
        root = etree.fromstring(mathml.encode("utf-8"))
        legacy_normalize(root, display)
        omml = _get_transform()(root).getroot()
    except MathError:
        raise
    except Exception as exc:
        raise MathError(f"math conversion failed: {exc}") from exc
    if omml is None:
        raise MathError("stylesheet produced no output")
    return _postprocess_omml(omml)


def _strip_math(tex):
    """Trim whitespace around a math expression without eating a control space.

    ``\\ `` is one token: the space *is* the command's argument. A plain
    ``.strip()`` on an expression ending in one leaves a lone backslash,
    which fails to parse -- and a failed parse drops the whole equation to
    literal monospaced LaTeX. Measured on real documents: a Word run holding
    "μ " came back as ``\\mu \\ `` and lost the entire zone.
    """
    stripped = tex.strip()
    trailing_backslashes = len(stripped) - len(stripped.rstrip("\\"))
    return stripped + " " if trailing_backslashes % 2 else stripped


def latex_math_to_omml(tex, display="inline", warnings=None):
    """Return an ``m:oMath`` element for one LaTeX math expression.

    R4 seam switch (``REWRITE_FORWARD.md``): this now runs
    ``latex2omml.emit(latex2omml.parse(tex))`` -- the direct LaTeX -> AST ->
    OMML emitter -- instead of the old ``latex2mathml`` / ``MML2OMML.XSL``
    chain (kept as ``legacy_latex_math_to_omml`` above, import-only).
    ``warnings`` is the §6.2 sink for tolerated macros (\\label & co.).

    Never raises, exactly like the function it replaces: a
    ``latex2omml.LatexParseError`` (or any other failure) becomes a
    ``MathError`` whose message *names the parse diagnostic* -- the whole
    point of the new parser is a precise error, so it must not be swallowed
    into a generic "math conversion failed". Every caller already falls
    back to literal monospaced LaTeX plus a warning on ``MathError``.
    """
    tex = _strip_math(tex)
    if not tex:
        raise MathError("empty math")
    try:
        ast = latex2omml.parse(tex, warnings)
        omml = latex2omml.emit(ast)
    except MathError:
        raise
    except latex2omml.LatexParseError as exc:
        raise MathError(str(exc)) from exc
    except Exception as exc:
        raise MathError(f"math conversion failed: {exc}") from exc
    return omml


def _omath_para(omml, align=None):
    para = etree.Element(_m("oMathPara"))
    pr = etree.SubElement(para, _m("oMathParaPr"))
    values = {
        WD_ALIGN_PARAGRAPH.LEFT: "left",
        WD_ALIGN_PARAGRAPH.CENTER: "center",
        WD_ALIGN_PARAGRAPH.RIGHT: "right",
        WD_ALIGN_PARAGRAPH.JUSTIFY: "both",
    }
    etree.SubElement(pr, _m("jc")).set(
        _m("val"), values.get(align, "center")
    )
    para.append(omml)
    return para


# Inline scanning is implemented in inline.py. These aliases keep the
# historical private helpers available to the block facade during the staged
# extraction.
_find_brace = _inline_find_brace
_find_bracket = _inline_find_bracket
_find_env_end = _blocks.find_env_end
_split_top_level_items = _blocks.split_top_level_items
_strip_preamble_metadata = _blocks.strip_preamble_metadata

# Text replacement and comment stripping live with the inline scanner.
strip_comments = _inline_strip_comments
_parse_image_args = _parse_inline_image_args


def add_inline_latex(paragraph, text, styles=None, warnings=None, img_base=None):
    """Compatibility facade for the extracted inline renderer."""
    return _render_inline_latex(
        paragraph, text, styles, warnings, img_base,
        math_renderer=latex_math_to_omml,
        image_adder=_insert_inline_picture,
    )


def _table_math_renderer(tex, warnings):
    return latex_math_to_omml(tex, "block", warnings)


# --- Document structure -----------------------------------------------------

MATH_ENVS = {
    "equation", "equation*", "displaymath", "align", "align*", "aligned",
    "gather", "gather*", "multline", "multline*", "eqnarray", "eqnarray*",
    "alignat", "alignat*", "split", "cases", "array",
    "matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix",
}
# Environments passed to latex2mathml with their \begin/\end intact, because the
# environment name itself carries layout meaning (alignment columns, delimiters).
MATH_ENVS_KEEP_WRAPPER = MATH_ENVS - {"equation", "equation*", "displaymath"}

LIST_ENVS = {"itemize", "enumerate", "description"}
# Alignment environments (CANONICAL.md doc-layer section 2.2): a genuine
# deviation from LaTeX's justified default, each carrying an explicit
# WD_ALIGN_PARAGRAPH override that recurses into add_paragraph_text.
ALIGN_ENVS = {
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "flushleft": WD_ALIGN_PARAGRAPH.LEFT,
    "flushright": WD_ALIGN_PARAGRAPH.RIGHT,
    # Marks a paragraph the source explicitly set to justified (w:jc="both")
    # -- distinct from the *unmarked* default, which stays Word's own
    # left. See add_paragraph_text's `align` handling above.
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}
TRANSPARENT_ENVS = {"quote", "quotation", "abstract", "document", "sloppypar"}

# `multicols` takes the column count as a mandatory argument; the starred
# form differs only in balancing, which Word has no equivalent for.
MULTICOL_ENVS = {"multicols", "multicols*"}
# "figure"/"figure*" (images, PLAN_DOCLAYER.md stage 3) and "tabular"/
# "tabular*" (simple text tables, stage 4.1) get dedicated handling in
# _handle_block below -- they carry real, reconstructible content, unlike
# the environments left here that this converter has no representation for.
SKIPPED_ENVS = {"table", "table*",
                "tikzpicture", "verbatim", "lstlisting", "thebibliography"}
FIGURE_ENVS = {"figure", "figure*"}
TABULAR_ENVS = {"tabular", "tabular*"}

HEADINGS = {
    "part": 1, "chapter": 1, "section": 1, "subsection": 2,
    "subsubsection": 3, "paragraph": 4, "subparagraph": 5,
}

_BLOCK_RE = re.compile(
    r"\\begin\{([A-Za-z*]+)\}"
    r"|\\\["
    r"|\$\$"
    r"|\\(part|chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?\s*\{"
    r"|\\item\b"
    r"|\\tableofcontents\b"
    r"|\\mbox\{(?:[ \t]|\\ )*\}\\par\b"
    r"|\\theendnotes\b"
)


# --- Nested lists (PLAN_DOCLAYER.md stage 2.1) ------------------------------
#
# The numbering owner emits enumitem overrides when a Word level's authored
# marker differs from plain LaTeX's default. This facade keeps the historical
# constants imported above as compatibility seams for older callers.
from .builder import DocxBuilder


def convert_latex_to_docx(tex_path, docx_path=None, reference_doc=None, reference_mode="rewrite"):
    with open(tex_path, "r", encoding="utf-8") as f:
        raw = f.read()

    if docx_path is None:
        docx_path = os.path.splitext(tex_path)[0] + ".docx"

    content = strip_comments(raw)

    builder = DocxBuilder(reference_doc, reference_mode)
    object_store = ObjectStore.for_read(tex_path) if tex_path else None
    if object_store is not None:
        builder.doc._latexword_object_store = object_store
        builder.doc.part._latexword_object_store = object_store
    # PLAN_DOCLAYER.md stage 3: a relative \includegraphics{...} path is
    # relative to the .tex file it appears in, not the process cwd -- this
    # is where docx_read.py actually wrote the sibling "<stem>.figures/".
    builder.img_base = os.path.dirname(os.path.abspath(tex_path))

    title = re.search(r"\\title\s*\{", content)
    if title:
        text, _ = _find_brace(content, title.end() - 1)
        if text:
            builder.add_heading(text, 0)
    author = re.search(r"\\author\s*\{", content)
    if author:
        text, _ = _find_brace(content, author.end() - 1)
        if text:
            p = builder.doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            add_inline_latex(p, text, {"italic": True}, builder.warnings, builder.img_base)

    begin = re.search(r"\\begin\{document\}", content)
    if begin:
        # Search from *after* \begin{document}: _find_env_end counts nesting, so
        # including the opening tag would leave it looking for a second \end.
        start, _ = _find_env_end(content, "document", begin.end())
        body = content[begin.end() : start] if start != -1 else content[begin.end() :]
    else:
        body = content

    # Preamble-only directive that may survive inside the body: \maketitle
    # has no argument and the title/author heading it would produce is
    # already emitted above from the preamble copy, so it is dropped here.
    # \newpage/\clearpage/\tableofcontents are handled by the block parser
    # below (page breaks and the TOC field), not stripped.
    body = re.sub(r"\\maketitle\b", "", body)
    body = _strip_preamble_metadata(body, _find_brace)

    builder.parse(body)
    builder.doc.save(docx_path)
    issues = validate_docx_package(docx_path)
    if issues:
        raise DocxPackageError(issues)
    return docx_path, builder.warnings
