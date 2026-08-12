"""Stateful inline LaTeX scanner used by the DOCX adapter."""

import re

import docx
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import RGBColor

from ..document.text import href_unescape as _href_unescape
from .inline import (
    DROPPED_CMDS,
    DROPPED_CMDS_2ARG,
    ESCAPES,
    HIGHLIGHT_NAME_TO_WD,
    LITERAL_CMDS,
    SCRIPT_CMDS,
    STYLE_CMDS,
    TRANSPARENT_CMDS,
    _INLINE_MATH,
    _add_bookmark,
    _add_comment,
    _add_field,
    _add_hyperlink,
    _add_note,
    _apply_shading,
    _apply_text_replacements_outside_math,
    _ensure_character_style,
    _find_brace,
    _find_bracket,
    _resolve_color,
    _set_character_style,
    parse_image_args,
)


class InlineRenderer:
    """Render one inline LaTeX stream while carrying scanner state."""

    def __init__(self, paragraph, text, styles, warnings, img_base,
                 math_renderer, image_adder):
        self.paragraph = paragraph
        self.text = _apply_text_replacements_outside_math(text)
        self.styles = {} if styles is None else dict(styles)
        self.warnings = warnings
        self.img_base = img_base
        self.math_renderer = math_renderer
        self.image_adder = image_adder
        self.i = 0
        self.buf = []

    def render(self):
        while self.i < len(self.text):
            match = _INLINE_MATH.match(self.text, self.i)
            if match:
                self._consume_math(match)
                continue
            if self.text[self.i] == "\\":
                self._consume_backslash()
                continue
            if self._consume_group_or_space():
                continue
            self.buf.append(self.text[self.i])
            self.i += 1
        self.flush()

    def style_run(self, run):
        rstyle = self.styles.get("rstyle")
        if self.styles.get("hyperlink") is True and not rstyle:
            rstyle = "Hyperlink"
        if rstyle:
            doc = self.paragraph.part.document
            reference = bool(getattr(doc, "_latexword_reference_doc", False))
            if _ensure_character_style(doc, rstyle, create=not reference):
                _set_character_style(run, rstyle)
            elif self.warnings is not None:
                missing = getattr(doc, "_latexword_missing_character_styles", set())
                if rstyle not in missing:
                    missing.add(rstyle)
                    doc._latexword_missing_character_styles = missing
                    self.warnings.append(
                        f"reference character style {rstyle!r} not found; content kept without style"
                    )
        if self.styles.get("hyperlink") is False:
            run.font.color.rgb = RGBColor(0x05, 0x63, 0xC1)
            run.underline = True
        for key, attr in (("bold", "bold"), ("italic", "italic"),
                          ("underline", "underline"), ("strike", "strike"),
                          ("smallcaps", "small_caps"),
                          ("superscript", "superscript"),
                          ("subscript", "subscript"), ("hidden", "hidden")):
            if self.styles.get(key):
                setattr(run.font if key in (
                    "strike", "smallcaps", "superscript", "subscript", "hidden"
                ) else run,
                        attr, True)
        if self.styles.get("mono"):
            run.font.name = "Consolas"
        if self.styles.get("color"):
            run.font.color.rgb = RGBColor.from_string(self.styles["color"])
        if self.styles.get("highlight") is not None:
            run.font.highlight_color = self.styles["highlight"]
        if self.styles.get("shading"):
            _apply_shading(run, self.styles["shading"])

    def flush(self):
        if not self.buf:
            return
        chunk = "".join(self.buf)
        self.buf.clear()
        if not chunk:
            return
        run = self.paragraph.add_run(chunk)
        self.style_run(run)
        t_el = run._element.find(qn("w:t"))
        if t_el is not None:
            t_el.set(qn("xml:space"), "preserve")

    def recurse(self, arg, styles=None):
        from .inline import add_inline_latex

        add_inline_latex(
            self.paragraph, arg, self.styles if styles is None else styles,
            self.warnings, self.img_base, math_renderer=self.math_renderer,
            image_adder=self.image_adder,
        )

    def _consume_backslash(self):
        two = self.text[self.i:self.i + 2]
        if two == r"\-":
            self.flush()
            run = self.paragraph.add_run()
            self.style_run(run)
            run._element.append(OxmlElement("w:softHyphen"))
            self.i += 2
            return
        if two in ESCAPES:
            self.buf.append(ESCAPES[two])
            self.i += 2
            return
        if two == "\\\\":
            self.flush()
            run = self.paragraph.add_run()
            self.style_run(run)
            run.add_break()
            self.i += 2
            while self.i < len(self.text) and self.text[self.i] in " \t":
                self.i += 1
            return
        match = re.match(r"\\([a-zA-Z]+)\*?", self.text[self.i:])
        if not match:
            self.i += 1
            return
        cmd = match.group(1)
        pos = self.i + len(match.group(0))
        if cmd in LITERAL_CMDS:
            self.buf.append(LITERAL_CMDS[cmd])
            self.i = pos + 2 if self.text[pos:pos + 2] == "{}" else pos
            return
        self.i = self._dispatch_command(cmd, pos)

    def _dispatch_command(self, cmd, pos):
        if cmd in DROPPED_CMDS:
            return _find_brace(self.text, pos)[1]
        if cmd in DROPPED_CMDS_2ARG:
            pos = _find_brace(self.text, pos)[1]
            pos = _find_bracket(self.text, pos)[1]
            return _find_brace(self.text, pos)[1]
        if cmd == "begin":
            return self._command_begin(pos)
        if cmd in STYLE_CMDS:
            return self._command_style(cmd, pos)
        if cmd in SCRIPT_CMDS:
            return self._command_wrapped_style(cmd, pos)
        if cmd in ("textcolor", "colorbox"):
            return self._command_color(cmd, pos)
        if cmd in ("sethlcolor", "hl"):
            return self._command_highlight(cmd, pos)
        if cmd in TRANSPARENT_CMDS:
            arg, pos = _find_brace(self.text, pos)
            if arg is not None:
                self.buf.append(arg)
            return pos
        return self._dispatch_content_command(cmd, pos)

    def _command_begin(self, pos):
        env, pos = _find_brace(self.text, pos)
        if env is not None:
            self.buf.append(f"\\begin{{{env}}}")
        return pos

    def _command_style(self, cmd, pos):
        arg, pos = _find_brace(self.text, pos)
        self.flush()
        if arg is not None:
            styles = dict(self.styles)
            styles[STYLE_CMDS[cmd]] = True
            self.recurse(arg, styles)
        return pos

    def _command_wrapped_style(self, cmd, pos):
        arg, pos = _find_brace(self.text, pos)
        self.flush()
        if arg is None:
            return pos
        styles = dict(self.styles)
        styles["superscript"] = False
        styles["subscript"] = False
        styles[SCRIPT_CMDS[cmd]] = True
        self.recurse(arg, styles)
        return pos

    def _command_color(self, cmd, pos):
        model, pos = _find_bracket(self.text, pos)
        colorarg, pos = _find_brace(self.text, pos)
        arg, pos = _find_brace(self.text, pos)
        self.flush()
        hexval = _resolve_color(colorarg, model)
        if arg is None:
            return pos
        styles = dict(self.styles)
        if hexval:
            styles["color" if cmd == "textcolor" else "shading"] = hexval
        elif self.warnings is not None and colorarg is not None:
            self.warnings.append(f"unrecognised colour \\{cmd}{{{colorarg}}}")
        self.recurse(arg, styles)
        return pos

    def _command_highlight(self, cmd, pos):
        arg, pos = _find_brace(self.text, pos)
        self.flush()
        if cmd == "sethlcolor":
            wd = HIGHLIGHT_NAME_TO_WD.get((arg or "").strip().lower())
            if wd is not None:
                self.styles["highlight"] = wd
            elif self.warnings is not None:
                self.warnings.append(f"unrecognised highlight colour {arg!r}")
            return pos
        if arg is not None:
            if self._append_wrapped_display_math(arg):
                return pos
            styles = dict(self.styles)
            styles["highlight"] = self.styles.get("highlight", WD_COLOR_INDEX.YELLOW)
            self.recurse(arg, styles)
        return pos

    def _append_wrapped_display_math(self, arg):
        """Render a display zone nested inside a formatting command."""

        value = arg.strip()
        if value.startswith(r"\[") and value.endswith(r"\]"):
            return self._append_math(value[2:-2], display=True)
        if value.startswith("$$") and value.endswith("$$"):
            return self._append_math(value[2:-2], display=True)
        return False

    def _apply_math_styles(self, omml):
        if not any(self.styles.get(key) is not None for key in (
                "color", "highlight", "shading")):
            return

        def apply_word_properties(word_rpr):
            if self.styles.get("color"):
                color = OxmlElement("w:color")
                color.set(qn("w:val"), self.styles["color"])
                word_rpr.append(color)
            if self.styles.get("highlight") is not None:
                highlight = OxmlElement("w:highlight")
                value = self.styles["highlight"]
                name = next(
                    (key for key, item in HIGHLIGHT_NAME_TO_WD.items()
                     if item == value),
                    str(value).split()[0].lower(),
                )
                highlight.set(qn("w:val"), str(name).lower())
                word_rpr.append(highlight)
            if self.styles.get("shading"):
                shading = OxmlElement("w:shd")
                shading.set(qn("w:val"), "clear")
                shading.set(qn("w:color"), "auto")
                shading.set(qn("w:fill"), self.styles["shading"])
                word_rpr.append(shading)

        for math_run in omml.iter(qn("m:r")):
            rpr = math_run.find(qn("m:rPr"))
            word_rpr = math_run.find(qn("w:rPr"))
            if word_rpr is None:
                word_rpr = OxmlElement("w:rPr")
                insert_at = 0
                if rpr is not None:
                    insert_at = list(math_run).index(rpr) + 1
                math_run.insert(insert_at, word_rpr)
            apply_word_properties(word_rpr)

        # Word applies range formatting to the non-visible control characters
        # as well (fraction bars, delimiters, scripts, accents).  Without
        # these properties, each visible math run gets an isolated rectangle
        # instead of one continuous highlighted range.
        control_parents = {
            "accPr", "dPr", "fPr", "funcPr", "mPr", "naryPr", "radPr",
            "sSubPr", "sSubSupPr", "sSupPr",
        }
        structure_properties = {
            "acc": "accPr", "bar": "barPr", "borderBox": "borderBoxPr",
            "box": "boxPr", "d": "dPr", "eqArr": "eqArrPr",
            "f": "fPr", "func": "funcPr", "groupChr": "groupChrPr",
            "limLow": "limLowPr", "limUpp": "limUppPr", "m": "mPr",
            "nary": "naryPr", "rad": "radPr", "sPre": "sPrePr",
            "sSub": "sSubPr", "sSubSup": "sSubSupPr", "sSup": "sSupPr",
        }
        for structure in omml.iter():
            property_name = structure_properties.get(
                structure.tag.rsplit("}", 1)[-1]
            )
            if property_name is None:
                continue
            properties = structure.find(qn("m:" + property_name))
            if properties is None:
                properties = OxmlElement("m:" + property_name)
                structure.insert(0, properties)
        for parent in omml.iter():
            if parent.tag.rsplit("}", 1)[-1] not in control_parents:
                continue
            control = parent.find(qn("m:ctrlPr"))
            if control is None:
                control = OxmlElement("m:ctrlPr")
                parent.append(control)
            word_rpr = control.find(qn("w:rPr"))
            if word_rpr is None:
                word_rpr = OxmlElement("w:rPr")
                control.append(word_rpr)
            apply_word_properties(word_rpr)

    def _append_math(self, math_tex, *, display=False):
        if self.math_renderer is None:
            return False
        try:
            omml = self.math_renderer(
                math_tex, "block" if display else "inline", self.warnings,
            )
            self._apply_math_styles(omml)
            if display:
                para = OxmlElement("m:oMathPara")
                properties = OxmlElement("m:oMathParaPr")
                alignment = OxmlElement("m:jc")
                alignment.set(qn("m:val"), "center")
                properties.append(alignment)
                para.append(properties)
                para.append(omml)
                self.paragraph._element.append(para)
            else:
                self.paragraph._element.append(omml)
            return True
        except Exception as exc:
            if self.warnings is not None:
                self.warnings.append(f"inline math failed ({exc}): {math_tex[:60]}")
            self.paragraph.add_run(f"${math_tex}$")
            return True

    def _dispatch_content_command(self, cmd, pos):
        if cmd == "cite":
            arg, pos = _find_brace(self.text, pos)
            self.buf.append(f"[{arg}]" if arg else "")
            return pos
        if cmd in ("ref", "eqref", "pageref"):
            return self._command_reference(cmd, pos)
        if cmd == "label":
            return self._command_label(pos)
        if cmd in ("footnote", "endnote"):
            return self._command_note(cmd, pos)
        if cmd == "todo":
            return self._command_todo(pos)
        if cmd == "theendnotes":
            return pos
        if cmd in ("newpage", "clearpage"):
            self.flush()
            self.paragraph.add_run().add_break(docx.enum.text.WD_BREAK.PAGE)
            return pos
        if cmd == "href":
            return self._command_href(pos)
        if cmd == "includegraphics":
            return self._command_image(pos)
        return self._command_unknown(cmd, pos)

    def _command_reference(self, cmd, pos):
        arg, pos = _find_brace(self.text, pos)
        self.flush()
        if arg is not None:
            kind = "PAGEREF" if cmd == "pageref" else "REF"
            _add_field(self.paragraph, kind, arg)
        return pos

    def _command_label(self, pos):
        name, pos = _find_brace(self.text, pos)
        self.flush()
        if name is not None:
            _add_bookmark(self.paragraph, name, self.warnings)
        return pos

    def _command_note(self, cmd, pos):
        arg, pos = _find_brace(self.text, pos)
        self.flush()
        if arg is not None:
            _add_note(
                self.paragraph, arg, cmd, self.styles, self.warnings, self.img_base,
                self.math_renderer, self.image_adder,
            )
        return pos

    def _command_todo(self, pos):
        options, pos = _find_bracket(self.text, pos)
        text, pos = _find_brace(self.text, pos)
        if text is None:
            return pos
        self.flush()
        author = ""
        date = ""
        for option in (options or "").split(","):
            key, _, value = option.partition("=")
            if key.strip() == "author":
                author = value.strip()
            elif key.strip() == "date":
                date = value.strip()
        _add_comment(
            self.paragraph, _href_unescape(author), _href_unescape(date), text,
            self.styles, self.warnings, self.img_base, self.math_renderer,
            self.image_adder,
        )
        return pos

    def _command_href(self, pos):
        url, pos = _find_brace(self.text, pos)
        arg, pos = _find_brace(self.text, pos)
        self.flush()
        if arg is not None:
            _add_hyperlink(
                self.paragraph, _href_unescape(url or ""), _href_unescape(arg),
                self.styles, self.warnings, self.img_base,
                self.math_renderer, self.image_adder,
            )
        return pos

    def _command_image(self, pos):
        opts, path, metadata, pos = parse_image_args(self.text, pos)
        self.flush()
        if self.image_adder is None:
            if self.warnings is not None:
                self.warnings.append(f"image dispatch unavailable: {path}")
        else:
            self.image_adder(
                self.paragraph, path, opts, self.img_base, self.warnings, metadata,
            )
        return pos

    def _command_unknown(self, cmd, pos):
        arg, pos = _find_brace(self.text, pos)
        if arg is not None:
            if self.warnings is not None:
                self.warnings.append(f"unknown text command \\{cmd}")
            self.flush()
            self.recurse(arg)
        elif self.warnings is not None:
            self.warnings.append(f"dropped \\{cmd}")
        return pos

    def _consume_math(self, match):
        self.flush()
        math_tex = match.group(1) if match.group(1) is not None else match.group(2)
        display = math_tex.lstrip().startswith(r"\displaystyle")
        if display:
            math_tex = re.sub(r"^\s*\\displaystyle\s*", "", math_tex, count=1)
        if self.math_renderer is None:
            if self.warnings is not None:
                self.warnings.append(f"inline math dispatch unavailable: {math_tex[:60]}")
            self.paragraph.add_run(f"${math_tex}$")
        else:
            self._append_math(math_tex, display=display)
        self.i = match.end()

    def _consume_group_or_space(self):
        ch = self.text[self.i]
        if ch == "{" and not (self.i + 1 < len(self.text) and self.text[self.i + 1] == "}"):
            arg, pos = _find_brace(self.text, self.i)
            if arg is not None:
                self.flush()
                self.recurse(arg, dict(self.styles))
                self.i = pos
                return True
        if ch == "~":
            self.buf.append("\u00a0")
            self.i += 1
            return True
        if ch == "{" and self.i + 1 < len(self.text) and self.text[self.i + 1] == "}":
            self.i += 2
            return True
        return False
