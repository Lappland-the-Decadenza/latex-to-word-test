"""Forward document builder implementation.

The public conversion facade remains in write.py. This module receives the
facade's component seams after write.py has initialized them.
"""

from . import write as _write
from docx import Document
from .numbering import ENUM_DEFAULT_NUMFMT_BY_DEPTH, parse_list_label
from .state import BuilderState
from . import sidecar_render as _sidecar_render
from . import block_dispatch as _block_dispatch


_clear_reference_body = _write._clear_reference_body
_ensure_named_style = _write._ensure_named_style
_set_paragraph_style_id = _write._set_paragraph_style_id
_ensure_table_style = _write._ensure_table_style
paragraph_from_text = _write.paragraph_from_text
paragraph_text = _write.paragraph_text
re = _write.re
qn = _write.qn
_m = _write._m
docx = _write.docx
WD_ALIGN_PARAGRAPH = _write.WD_ALIGN_PARAGRAPH
OxmlElement = _write.OxmlElement
Pt = _write.Pt
deepcopy = _write.deepcopy
add_inline_latex = _write.add_inline_latex
latex_math_to_omml = _write.latex_math_to_omml
_table_math_renderer = _write._table_math_renderer
MathError = _write.MathError
_omath_para = _write._omath_para
_style_supplies_numbering = _write._style_supplies_numbering
apply_list_level = _write.apply_list_level
_tables = _write._tables
_blocks = _write._blocks
_find_brace = _write._find_brace
_find_bracket = _write._find_bracket
_parse_inline_image_args = _write._parse_inline_image_args
_insert_inline_picture = _write._insert_inline_picture
_find_env_end = _write._find_env_end
_split_top_level_items = _write._split_top_level_items
_BLOCK_RE = _write._BLOCK_RE
HEADINGS = _write.HEADINGS
MATH_ENVS = _write.MATH_ENVS
MATH_ENVS_KEEP_WRAPPER = _write.MATH_ENVS_KEEP_WRAPPER
LIST_ENVS = _write.LIST_ENVS
ALIGN_ENVS = _write.ALIGN_ENVS
TRANSPARENT_ENVS = _write.TRANSPARENT_ENVS
MULTICOL_ENVS = _write.MULTICOL_ENVS
SKIPPED_ENVS = _write.SKIPPED_ENVS
FIGURE_ENVS = _write.FIGURE_ENVS
TABULAR_ENVS = _write.TABULAR_ENVS
class DocxBuilder:
    def __init__(self, reference_doc=None, reference_mode="rewrite", *, _state=None):
        if _state is None:
            if reference_mode not in ("rewrite", "copy"):
                raise ValueError("reference_mode must be 'rewrite' or 'copy'")
            if reference_doc is None:
                if reference_mode == "copy":
                    raise ValueError("reference_mode='copy' requires reference_doc")
                doc = Document()
                reference_enabled = False
            elif reference_mode == "rewrite":
                doc = Document(reference_doc)
                reference_enabled = True
                _clear_reference_body(doc)
            else:
                # A reference document is the formatting authority, not just
                # a bag of w:style elements.  Style rendering also depends on
                # its section properties and package-level dependencies.
                # Reuse the coherent package and replace only body content.
                doc = Document(reference_doc)
                _clear_reference_body(doc)
                reference_enabled = True
            self._state = BuilderState(
                doc=doc,
                warnings=[],
                reference_doc=reference_enabled,
                reference_mode=reference_mode,
                missing_reference_styles=set(),
            )
            doc._latexword_reference_doc = reference_enabled
        else:
            if reference_doc is not None or reference_mode != "rewrite":
                raise TypeError("_state cannot be combined with reference arguments")
            self._state = _state

        # Word can put a display-math zone and trailing prose in the *same*
        # paragraph (measured on a corpus document: a caption sentence right
        # after an equation with no intervening blank line). `_flush_prose` checks
        # this before starting the text that immediately follows a math
        # block, and merges into `_last_para` instead of opening a new one
        # when the source had no blank line between them either.
        self._last_para = None
        self._merge_next_prose = False
        self._pending_block_prefix = ""
        # The `m:oMathPara` a still-open multi-line equation array's next
        # row should append into (see add_display_math's `append` param).
        self._last_math_para = None
        # Directory a relative \includegraphics{...} path resolves against
        # (PLAN_DOCLAYER.md stage 3) -- set by convert_latex_to_docx once the
        # source .tex path is known.

    @property
    def doc(self):
        return self._state.doc

    @property
    def warnings(self):
        return self._state.warnings

    @property
    def _reference_doc(self):
        return self._state.reference_doc

    @property
    def _reference_mode(self):
        return self._state.reference_mode

    @property
    def _missing_reference_styles(self):
        return self._state.missing_reference_styles

    @property
    def img_base(self):
        return self._state.img_base

    @img_base.setter
    def img_base(self, value):
        self._state.img_base = value

    def child_builder(self):
        return DocxBuilder(_state=self._state)

    def _bind_paragraph_style(self, paragraph, style_id):
        if _ensure_named_style(self.doc, style_id, create=not self._reference_doc):
            _set_paragraph_style_id(paragraph, style_id)
        elif style_id not in self._missing_reference_styles:
            self._missing_reference_styles.add(style_id)
            self.warnings.append(f"reference style {style_id!r} not found; content kept without style")

    def _bind_table_style(self, table, style_id):
        if _ensure_table_style(self.doc, style_id, create=not self._reference_doc):
            table._tbl.tblStyle_val = style_id
        elif style_id not in self._missing_reference_styles:
            self._missing_reference_styles.add(style_id)
            self.warnings.append(f"reference table style {style_id!r} not found; table kept without style")

    # -- emitters ----------------------------------------------------------
    def _sidecar_paragraph_style(self, ordinal, text, *, slot_fallback=False):
        return _sidecar_render.paragraph_style(
            self, ordinal, text, slot_fallback=slot_fallback
        )
        # legacy body moved to sidecar_render.py
        # legacy body moved to sidecar_render.py

    def _sidecar_table_style(self):
        return _sidecar_render.table_style(self)

    def _sidecar_opaque(self, ordinal, text):
        return _sidecar_render.opaque(self, ordinal, text)

    def add_paragraph_text(self, text, style=None, align=None, append=False,
                            level=-1, numfmt=None, pstyle_id=None,
                            allow_empty=False):
        # In LaTeX a single newline is just whitespace; only a blank line ends a
        # paragraph, and those were already split off by the caller.  Left as-is
        # the newline reaches python-docx, which turns it into a hard <w:br/>.
        #
        # A leading/trailing space is real content in Word (docfidelity's
        # whitespace signature compares it exactly), so only the newline
        # itself is folded away here -- not the whole string, which used to
        # delete an edge space the source paragraph actually had. This
        # relies on docx_read.py's alignment/list wrappers never padding
        # their content with an edge newline of their own (an earlier
        # version of that code did, and stripping *that* synthetic newline
        # here together with its surrounding whitespace ate a genuine
        # trailing space sitting right before it -- a fresh "spacing
        # changed" regression on real title-page paragraphs).
        text = re.sub(r"[ \t]*\n[ \t]*", " ", text)
        if not text.strip() and not allow_empty:
            return
        raw_text = text
        # The parser creates a typed paragraph node before the DOCX emitter
        # touches the document. Inline markup is still rendered by the
        # existing inline seam; this first migration carries the content and
        # authored style reference without changing that policy.
        node = paragraph_from_text(text, style_id=pstyle_id)
        text = paragraph_text(node)
        pstyle_id = node.style.style_id if node.style is not None else None
        ordinal = self._state.sidecar_ordinal
        if append and self._last_para is not None:
            p = self._last_para
            # Prose merging into a display-equation paragraph (the
            # `\[...\]`-then-prose shape) must not inherit the CENTER
            # alignment add_display_math set on that paragraph: in the
            # source documents the equation line is its own centered
            # block (`m:oMathPara` renders on its own line, justified by
            # its own `m:jc`) and the prose line keeps the paragraph's
            # default left alignment -- a corpus paragraph holding both
            # an `m:oMathPara` and trailing prose carries no `w:jc`
            # (measured on the document that reported the defect; 7
            # such shared paragraphs in the corpus, none of them
            # centered). Dropping the alignment leaves the equation
            # centered through `oMathParaPr`'s `m:jc` and restores the
            # prose line to left.
            ppr = p._element.get_or_add_pPr()
            if ppr.find(qn("w:jc")) is not None and \
                    p._element.find(_m("oMathPara")) is not None:
                p.alignment = None
            p._latexword_sidecar_ordinal = ordinal
            add_inline_latex(p, text, style, self.warnings, self.img_base)
            self._restore_character_state(p, ordinal)
            return
        if pstyle_id is None:
            pstyle_id = self._sidecar_paragraph_style(ordinal, raw_text)
        self._state.sidecar_ordinal += 1
        # §7.4: a list item's membership is its w:numPr, never a paragraph
        # style. python-docx's built-in "List Bullet"/"List Number" display
        # names were applied here, stamping a styleId the source never had
        # onto every round-tripped list paragraph ("style '' ->
        # 'listbullet'", 333 corpus findings). The paragraph stays
        # unstyled; `_apply_list_level` below writes the direct numPr at
        # every depth, level 0 included.
        p = self.doc.add_paragraph()
        self._last_para = p
        opaque = self._sidecar_opaque(ordinal, text)
        if opaque is not None:
            if opaque.get("context") == "block":
                if self.doc.part._latexword_object_store.restore(
                    self.doc.part, opaque["object_id"], block=True
                ):
                    self.doc._element.body.remove(p._element)
                    self._last_para = None
                    self._last_math_para = None
                    return
            elif self.doc.part._latexword_object_store.restore(
                self.doc.part, opaque["object_id"], paragraph=p
            ):
                self._last_math_para = None
                return
        # A fresh prose paragraph invalidates any still-open display-math
        # paragraph: a `\[...\]` that follows this prose (through the
        # `_merge_next_prose` flag) must join *this* paragraph, not the
        # stale `_last_math_para` from before the prose -- without this, a
        # Adjacent display equations and prose use the same merge cursor;
        # this keeps the original paragraph boundary stable.
        self._last_math_para = None
        # A named w:pStyle (D11, CANONICAL.md Rule 17): a raw styleId
        # round-trips through the oxml layer directly instead of going
        # through python-docx's style lookup, see `_set_paragraph_style_id`.
        if pstyle_id is None and raw_text != text:
            pstyle_id = self._sidecar_paragraph_style(ordinal, text)
        if pstyle_id:
            self._bind_paragraph_style(p, pstyle_id)
        # A reference style can own numbering and its indentation. Direct
        # numPr would override both, flattening 2.1-style headings into a
        # synthetic list and adding that list's hanging indent.
        if numfmt is not None and not _style_supplies_numbering(
                self.doc, pstyle_id):
            apply_list_level(self.doc, p, level, numfmt)
        # Word's own default (no w:jc at all) is left; leaving `align` unset
        # for an ordinary paragraph reproduces that exactly. Measured: most
        # corpus documents never write an explicit w:jc, so defaulting to
        # *justified* here (an earlier version of this fix) turned ~1200
        # genuinely-left paragraphs into "left -> both" degradations. A
        # paragraph the source *did* mark justified round-trips instead
        # through the explicit \begin{justify} wrapper (CANONICAL.md
        # doc-layer section 2.2), same discipline as center/flushleft/
        # flushright -- markup only for a genuine deviation from what an
        # absent w:jc already means.
        if align is not None:
            p.alignment = align
        p._latexword_sidecar_ordinal = ordinal
        add_inline_latex(p, text, style, self.warnings, self.img_base)
        self._restore_character_state(p, ordinal)

    def _restore_character_state(self, paragraph, ordinal):
        return _sidecar_render.restore_character_state(self, paragraph, ordinal)

    def add_display_math(self, tex, pstyle_id=None, append=False, align=None):
        tex = tex.strip()
        if not tex:
            return
        # Word's own multi-line equation array is one paragraph holding one
        # `m:oMathPara` with several `m:oMath` rows -- `append` (set when
        # this call is immediately preceded by another display-math block
        # with nothing but whitespace between them) reproduces that shape by
        # adding another row to the still-open `m:oMathPara` instead of
        # starting a new paragraph.
        if append and self._last_math_para is not None:
            try:
                self._last_math_para.append(
                    latex_math_to_omml(tex, "block", self.warnings))
            except MathError as exc:
                self.warnings.append(f"display math failed ({exc}): {tex[:60]}")
                run = self._last_para.add_run(tex)
                run.font.name = "Consolas"
                run.font.size = Pt(9)
            return
        if append and self._last_para is not None:
            # Prose-then-math (docx_read.py emits `prose\n\[...\]` for a
            # display zone sharing a Word paragraph with *preceding* prose
            # runs -- measured on two corpus documents, `r + r + oMathPara`
            # in one `w:p`): the zone joins the open prose paragraph instead
            # of starting a fresh one. The mirror image of the
            # `\[...\]`-then-prose merge in add_paragraph_text, and the only
            # way the paragraph boundary survives the round trip (before
            # this, the split re-registered every generation as a "text
            # changed" + "block appeared" pair). The prose paragraph was
            # created without `w:jc`, so the equation stays centered through
            # `oMathParaPr`'s `m:jc` and the prose line keeps its own
            # alignment -- the D15 discipline, with the prose side first.
            try:
                omath_para = _omath_para(
                    latex_math_to_omml(tex, "block"), align=align
                )
                self._last_para._element.append(omath_para)
                self._last_math_para = omath_para
            except MathError as exc:
                self.warnings.append(f"display math failed ({exc}): {tex[:60]}")
                run = self._last_para.add_run(tex)
                run.font.name = "Consolas"
                run.font.size = Pt(9)
                self._last_math_para = None
            return
        ordinal = self._state.sidecar_ordinal
        if pstyle_id is None:
            pstyle_id = self._sidecar_paragraph_style(
                ordinal, tex, slot_fallback=True
            )
        self._state.sidecar_ordinal += 1
        p = self.doc.add_paragraph()
        p.alignment = align if align is not None else WD_ALIGN_PARAGRAPH.CENTER
        self._last_para = p
        p._latexword_sidecar_ordinal = ordinal
        # A paragraph style travels with the paragraph, not with the math
        # inside it.
        if pstyle_id:
            self._bind_paragraph_style(p, pstyle_id)
        try:
            omath_para = _omath_para(
                latex_math_to_omml(tex, "block"), align=align
            )
            p._element.append(omath_para)
            self._last_math_para = omath_para
        except MathError as exc:
            self.warnings.append(f"display math failed ({exc}): {tex[:60]}")
            run = p.add_run(tex)
            run.font.name = "Consolas"
            run.font.size = Pt(9)
            self._last_math_para = None

    def add_heading(self, text, level):
        text = text.strip(); ordinal = self._state.sidecar_ordinal
        pstyle_id = self._sidecar_paragraph_style(ordinal, text); self._state.sidecar_ordinal += level > 0
        h = self.doc.add_paragraph() if level == 0 and pstyle_id else self.doc.add_heading("", level=min(level, 9)); (self._bind_paragraph_style(h, pstyle_id) if pstyle_id else None); h._latexword_sidecar_ordinal = ordinal; add_inline_latex(h, text, None, self.warnings, self.img_base); self._restore_character_state(h, ordinal)

    def add_page_break(self):
        p = self.doc.add_paragraph()
        p.add_run().add_break(docx.enum.text.WD_BREAK.PAGE)

    def add_toc_field(self):
        """Insert a real Word TOC field (``TOC \\o "1-3" \\h \\z \\u``), not
        frozen literal text -- so ``docx_read.py`` can recognise the field
        code on the way back and re-emit ``\\tableofcontents`` (PLAN_DOCLAYER
        stage 2 / docs/OPEN_QUESTIONS.md item 4) instead of transcribing
        whatever the last-cached TOC entries happened to say."""
        p = self.doc.add_paragraph()
        run = p.add_run()
        fld_begin = OxmlElement("w:fldChar")
        fld_begin.set(qn("w:fldCharType"), "begin")
        instr = OxmlElement("w:instrText")
        instr.set(qn("xml:space"), "preserve")
        instr.text = ' TOC \\o "1-3" \\h \\z \\u '
        fld_sep = OxmlElement("w:fldChar")
        fld_sep.set(qn("w:fldCharType"), "separate")
        fld_text = OxmlElement("w:t")
        fld_text.text = "Right-click and choose “Update Field” to build the table of contents."
        fld_end = OxmlElement("w:fldChar")
        fld_end.set(qn("w:fldCharType"), "end")
        run._element.append(fld_begin)
        run._element.append(instr)
        run2 = p.add_run()
        run2._element.append(fld_sep)
        run2._element.append(fld_text)
        run3 = p.add_run()
        run3._element.append(fld_end)

    def _end_section(self, ncols):
        paras = self.doc.paragraphs
        if not paras:
            return
        ppr = paras[-1]._element.get_or_add_pPr()
        if ppr.find(qn("w:sectPr")) is not None:
            return
        template_sect = self.doc._element.body.sectPr
        sect = deepcopy(template_sect) if template_sect is not None else OxmlElement("w:sectPr")
        kind = sect.find(qn("w:type"))
        if kind is None:
            kind = OxmlElement("w:type")
            first_layout = next(
                (i for i, child in enumerate(sect)
                 if child.tag not in {qn("w:headerReference"), qn("w:footerReference")}),
                len(sect),
            )
            sect.insert(first_layout, kind)
        kind.set(qn("w:val"), "continuous")
        cols = sect.find(qn("w:cols"))
        if cols is None:
            cols = OxmlElement("w:cols")
            sect.append(cols)
        cols.set(qn("w:num"), str(ncols))
        if cols.get(qn("w:space")) is None:
            cols.set(qn("w:space"), "720")
        ppr.append(sect)

    def _handle_multicols(self, content, align, level=-1, numfmt=None, enum_depth=0,
                           pstyle_id=None):
        return _blocks.handle_multicols(
            self, content, align, level, numfmt, enum_depth,
            pstyle_id, _find_brace,
        )

    def add_opaque_block(self, object_id, fallback=""):
        store = getattr(self.doc.part, "_latexword_object_store", None)
        if store and object_id and store.restore(self.doc.part, object_id, block=True):
            self._last_para = None
            self._last_math_para = None
            return True
        if fallback:
            self.add_paragraph_text(fallback)
        self.warnings.append(
            f"Word object {object_id!r} has no valid sidecar; visible fallback kept"
        )
        return False

    def _handle_tabular(self, content, pstyle_id=None):
        return _tables.handle_tabular(
            self, content, pstyle_id, add_inline_latex,
            math_renderer=_table_math_renderer,
        )

    def _handle_figure(self, content):
        return _blocks.handle_figure(
            self, content, _find_brace, _parse_inline_image_args,
            _insert_inline_picture, add_inline_latex,
        )

    # -- parser ------------------------------------------------------------
    #
    # `level`/`numfmt`/`enum_depth` (PLAN_DOCLAYER.md stage 2.1) thread the
    # ambient list-nesting state through the recursion so a nested
    # "\begin{itemize}"/"\begin{enumerate}" found while already inside a
    # list item gets a *deeper* w:ilvl than the item enclosing it, instead
    # of every nesting level flattening to the same ilvl=0 the paragraph
    # style alone provides. `level=-1` (not `0`) is the "not inside any
    # list item at all" sentinel -- opening a list right at the top of the
    # document must produce ilvl 0 (level+1), the same ilvl a *nested* list
    # opened inside a level-0 item must NOT get (level+1 == 1 there,
    # correctly deeper) -- level 0 alone cannot distinguish those two cases.
    # `enum_depth` counts only "enumerate" opens (not "itemize"), mirroring
    # LaTeX's own enumi/ii/iii/iv counters, so the numFmt used when no
    # explicit enumitem label was given matches what plain "enumerate"
    # would have produced at that depth (see _ENUM_DEFAULT_NUMFMT_BY_DEPTH).
    def parse(self, body, align=None, level=-1, numfmt=None, enum_depth=0,
              pstyle_id=None):
        return _blocks.parse(
            self, body, align, level, numfmt, enum_depth, pstyle_id, _BLOCK_RE,
        )

    def _flush_prose(self, text, align=None, level=-1, numfmt=None, pstyle_id=None):
        return _blocks.flush_prose(
            self, text, align, level, numfmt, pstyle_id,
        )

    def _handle_block(self, body, m, align=None, level=-1, numfmt=None, enum_depth=0,
                       pstyle_id=None):
        pending_prefix = self._pending_block_prefix
        self._pending_block_prefix = ""
        # Captured before the unconditional reset below: True here means the
        # immediately preceding block was display math with nothing but
        # whitespace since (no blank line, no prose) -- the signal that a
        # second `\[...\]`/`$$...$$` right after it is another row of the
        # same Word multi-line equation array (one `m:oMathPara`, several
        # `m:oMath` children), not a new one.
        continue_math = self._merge_next_prose
        self._merge_next_prose = False

        special = self._handle_special_block(
            body, m, align, level, numfmt, pstyle_id, continue_math,
        )
        if special is not None:
            return special

        return _block_dispatch.handle_environment(
            self, body, m, align, level, numfmt, enum_depth, pstyle_id,
            pending_prefix,
        )

    def _handle_special_block(self, body, m, align, level, numfmt, pstyle_id,
                              continue_math):
        token = m.group(0)

        if m.group(2):  # sectioning command
            title, after = _find_brace(body, m.end() - 1)
            self.add_heading(title or "", HEADINGS.get(m.group(2), 1))
            return after

        if token.startswith("\\["):
            end = body.find("\\]", m.end())
            end = len(body) if end == -1 else end
            self.add_display_math(
                body[m.end() : end], pstyle_id=pstyle_id,
                append=continue_math, align=align,
            )
            self._merge_next_prose = True
            return end + 2

        if token == "$$":
            end = body.find("$$", m.end())
            end = len(body) if end == -1 else end
            self.add_display_math(
                body[m.end() : end], pstyle_id=pstyle_id,
                append=continue_math, align=align,
            )
            self._merge_next_prose = True
            return end + 2

        if token.startswith("\\item"):
            # An \item outside a list environment: treat as a bullet anyway.
            nxt = _BLOCK_RE.search(body, m.end())
            stop = nxt.start() if nxt else len(body)
            item_text = re.sub(r"\n[ \t\n]*$", "", body[m.end() : stop])
            self.add_paragraph_text(
                item_text, align=align,
                level=level, numfmt=numfmt or "bullet", pstyle_id=pstyle_id,
                allow_empty=True,
            )
            return stop

        if token == "\\tableofcontents":
            self.add_toc_field()
            return m.end()

        if token == "\\theendnotes":
            # Document-level endnote output has no body paragraph of its own.
            # Treat it as a structural token so the surrounding blank source
            # lines do not manufacture an empty Word paragraph.
            return m.end()

        if token.startswith("\\mbox{") and token.endswith("\\par"):
            content, _ = _find_brace(token, len("\\mbox"))
            self.add_paragraph_text(
                content or "", align=align, pstyle_id=pstyle_id, allow_empty=True,
            )
            return m.end()

        return None

    def _handle_list_environment(self, body, env, content, content_start,
                                 end_stop, align, level, numfmt, enum_depth,
                                 pstyle_id):
        label_numfmt = None
        if env in ("enumerate", "itemize"):
            bracket, after_bracket = _find_bracket(body, content_start)
            if bracket is not None:
                lm = re.match(r"\s*label\s*=\s*(\S+?)\s*$", bracket)
                if lm:
                    label_numfmt = parse_list_label(
                        lm.group(1), word_level=level + 1,
                    )
                    if label_numfmt is None:
                        self.warnings.append(
                            f"unrecognised {env} label {lm.group(1)!r}; "
                            "using the default label"
                        )
                content_start = after_bracket
                end_start, end_stop = _find_env_end(body, env, content_start)
                if end_start == -1:
                    self.warnings.append(f"unterminated environment {env}")
                    return len(body)
                content = body[content_start:end_start]
        item_level = level + 1
        if env == "enumerate":
            item_enum_depth = enum_depth + 1
            item_numfmt = label_numfmt or ENUM_DEFAULT_NUMFMT_BY_DEPTH.get(
                item_enum_depth, "decimal"
            )
        else:
            item_enum_depth = enum_depth
            item_numfmt = label_numfmt or "bullet"
        # A list is a block boundary.  In particular, prose following a
        # synthetic empty parent item must not append to the last list
        # paragraph through the display-math merge cursor inherited from the
        # preceding source block.
        self._merge_next_prose = False
        self._parse_items(
            content, align, level=item_level, numfmt=item_numfmt,
            enum_depth=item_enum_depth, pstyle_id=pstyle_id,
        )
        return end_stop

    def _handle_regular_environment(self, body, m, env, content, end_stop,
                                    align, level, numfmt, enum_depth,
                                    pstyle_id):
        if env in MATH_ENVS:
            if env in MATH_ENVS_KEEP_WRAPPER:
                self.add_display_math(
                    body[m.start() : end_stop], pstyle_id=pstyle_id, align=align,
                )
            else:
                self.add_display_math(content, pstyle_id=pstyle_id, align=align)
            self._merge_next_prose = True
        elif env in ALIGN_ENVS:
            self.parse(content, align=ALIGN_ENVS[env], level=level,
                       numfmt=numfmt, enum_depth=enum_depth, pstyle_id=pstyle_id)
        elif env in MULTICOL_ENVS:
            self._handle_multicols(content, align, level, numfmt, enum_depth,
                                   pstyle_id)
        elif env in TRANSPARENT_ENVS:
            self.parse(content, align, level=level, numfmt=numfmt,
                       enum_depth=enum_depth, pstyle_id=pstyle_id)
        elif env in FIGURE_ENVS:
            self._handle_figure(content)
        elif env in TABULAR_ENVS:
            self._handle_tabular(content, pstyle_id)
        elif env in SKIPPED_ENVS:
            self.warnings.append(f"skipped environment {env}")
        else:
            self.warnings.append(f"unknown environment {env}; content kept")
            self.parse(content, align, level=level, numfmt=numfmt,
                       enum_depth=enum_depth, pstyle_id=pstyle_id)
        return end_stop

    def _parse_items(self, content, align=None, level=-1, numfmt=None,
                     enum_depth=0, pstyle_id=None):
        parts = _split_top_level_items(content)
        if parts and not parts[0].strip():
            parts = parts[1:]
        for part in parts:
            # docx_read.py's own template always separates "\item" from its
            # content with exactly one space, and one item from the next
            # with exactly one newline -- list syntax, not the item's own
            # leading/trailing whitespace. Now that add_paragraph_text
            # preserves a genuine edge space instead of stripping it (the
            # "(2.1) " fix), leaving these template artefacts in would
            # manufacture a phantom leading/trailing space on every list
            # item (measured on a corpus document's bibliography, e.g.
            # " Author... 576 pp. ").
            if part[:1] == " ":
                part = part[1:]
            if part[-1:] == "\n":
                part = part[:-1]
            # An item body may itself contain display math or a nested list.
            # A list item gets independent paragraph-merging cursors while
            # retaining the document-wide state (styles, numbering, warnings,
            # and image resolution) through the explicit child factory.
            sub = self.child_builder()
            if _BLOCK_RE.search(part):
                # ``build_nested_list`` emits a synthetic parent ``\item``
                # when Word begins at a deeper numbering level.  Keep that
                # empty parent in the DOCX; otherwise the next reverse pass
                # sees the same level-1-only sequence and synthesises the
                # parent again, so nested lists never settle.
                if re.match(r"\s*\\begin\{(?:itemize|enumerate)\}", part):
                    self.add_paragraph_text(
                        "", align=align, level=level, numfmt=numfmt,
                        pstyle_id=pstyle_id, allow_empty=True,
                    )
                sub.parse(part, align, level=level, numfmt=numfmt,
                          enum_depth=enum_depth, pstyle_id=pstyle_id)
            else:
                self.add_paragraph_text(
                    part, align=align, level=level,
                    numfmt=numfmt, pstyle_id=pstyle_id, allow_empty=True,
                )
