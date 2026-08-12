from . import parse_shared as _shared
globals().update({name: getattr(_shared, name) for name in _shared.__all__})
from .parse_handlers import _MACRO_HANDLERS, _apply_variant


class _AtomParserMixin:
    def parse_scripted(self):
        base = self.parse_atom()
        if base is None:
            # Ãƒâ€šÃ‚Â§6.2 tolerated no-op (`\label`, `\hspace`, `\!`): consumed
            # with its warning, produces no node; a script after it is a
            # separate (and in TeX meaningless) construct.
            return None
        if isinstance(base, _NaryHead):
            return base
        sub = sup = None
        primes = 0
        while True:
            t = self.peek()
            if t.kind == "prime":
                self.advance()
                primes += 1
            elif t.kind == "sub":
                if sub is not None:
                    self.fail(MalformedArgumentError, "double subscript", t)
                self.advance()
                sub = self.parse_argument()
            elif t.kind == "sup":
                if sup is not None or primes:
                    self.fail(MalformedArgumentError, "double superscript", t)
                self.advance()
                sup = self.parse_argument()
            else:
                break
        if primes:
            if sup is not None:
                self.fail(MalformedArgumentError,
                          "primes combined with an explicit superscript")
            sup = Row(tuple(Op(PRIME) for _ in range(primes)))
        if sub is None and sup is None:
            return base
        # mathast's `limit` entry: a movable-limit operator name is an
        # OpName on its own and becomes a Limit only when a subscript
        # follows. That is a parse-time structural decision the table
        # deliberately cannot state, so it is made here.
        if isinstance(base, OpName) and base.name in LIMIT_OPS:
            node = base
            if sup is not None:
                node = Limit(node, sup, "upp")
            if sub is not None:
                node = Limit(node, sub, "low")
            return node
        return Script(base, sub, sup)

    def parse_argument(self):
        """One macro/script argument: a braced group, or a single atom."""
        t = self.peek()
        if t.kind == "lbrace":
            self.advance()
            row = self.parse_sequence(_stop_rbrace, opener=t)
            self.advance()  # the '}'
            return row
        if t.kind in ("eof", "rbrace", "amp", "rowsep", "sub", "sup", "end"):
            self.fail(MalformedArgumentError, "missing argument", t)
        node = self.parse_atom()
        if node is None:
            # Ãƒâ€šÃ‚Â§6.2 tolerated no-op: it cannot BE an argument (`x_\!` has
            # no content to bind); TeX renders the empty subscript, we
            # report the honest failure instead of emitting `x_` (invalid
            # LaTeX that would re-parse differently).
            self.fail(MalformedArgumentError, "missing argument", t)
        if isinstance(node, _NaryHead):
            self.fail(MalformedArgumentError,
                      "n-ary operator cannot be a bare argument", t)
        return node

    def parse_optional_argument(self):
        """`[...]` after `\\sqrt`. Absent -> None."""
        t = self.peek()
        if t.kind == "char" and t.text == "[":
            self.advance()
            row = self.parse_sequence(
                lambda tok: tok.kind == "char" and tok.text == "]", opener=t)
            self.advance()
            return row
        return None

    # -- atoms --
    def parse_atom(self):
        t = self.peek()
        kind = t.kind

        if kind == "lbrace":
            self.advance()
            row = self.parse_sequence(_stop_rbrace, opener=t)
            self.advance()
            return row
        if kind == "rbrace":
            self.fail(UnbalancedDelimiterError, "'}' with no matching '{'", t)
        if kind == "digits":
            self.advance()
            return Num(t.text)
        if kind == "begin":
            return self.parse_environment()
        if kind == "end":
            self.fail(UnexpectedTokenError,
                      f"\\end{{{t.text}}} with no matching \\begin", t)
        if kind == "amp":
            self.fail(UnexpectedTokenError,
                      "'&' outside a multi-row environment", t)
        if kind == "rowsep":
            self.fail(UnexpectedTokenError,
                      "'\\\\' outside a multi-row environment", t)
        if kind == "rawarg":  # pragma: no cover - tokenizer pairs these
            self.fail(UnexpectedTokenError, "stray verbatim argument", t)
        if kind == "char":
            return self.parse_char(t)
        if kind == "macro":
            return self.parse_macro(t)
        self.fail(UnexpectedTokenError, f"unexpected {kind}", t)

    def parse_char(self, t):
        ch = t.text
        if ch in _BARE_PAIRS:
            return self.parse_bare_delim(t)
        if ch == "~":
            # LaTeX's tie. Spacing, not an operator -- the only spelling that
            # carries both an ordinary space's width and its no-break-here
            # meaning, which is exactly what Word stores as U+00A0 in an
            # equation run (mathsyms.NBSP_CHAR).
            self.advance()
            return Space(NBSP_CHAR)
        if ch in _BARE_CLOSERS:
            # An unmatched closer is a character, not an error. Word's
            # equation editor imposes no balance -- a stray ')' is stored as
            # an ordinary m:r run, and real documents contain them (measured:
            # equations ending '...-\alpha_n t)))'). Refusing to parse cost
            # the *whole* equation, which fell back to literal monospaced
            # LaTeX: one unbalanced bracket in the source erased a formula
            # that Word itself renders fine. Emitting the character
            # reproduces exactly what the source stored, and satisfies
            # CANONICAL.md rule 0 -- a bare m:r is what the reverse pass sees.
            self.advance()
            return Op(ch)
        self.advance()
        if ch.isalpha():
            return Ident(ch)
        if ch in _ASCII_CONTENT:
            return Op(ch)
        if ch.isascii():
            self.fail(UnknownMacroError,
                      f"literal ASCII character {ch!r} is not math content", t)
        # A literal non-ASCII glyph: preserved verbatim (see module
        # docstring). Alphabetic ones are variables, the rest are operators;
        # both are a plain m:r either way, so the split only affects Rule 2
        # operand recognition.
        return Ident(ch) if ch.isalpha() else Op(ch)

    def parse_bare_delim(self, t):
        """Rule 1: a bare `(`/`[`/`\\{` pair is still a `Delim`, so the
        canonicalizer rewrites it to `\\left`/`\\right`.

        An unmatched opener falls back to the plain character (`Op`) and
        the scan is rewound -- TeX treats a lone `[` as an ordinary math
        character (no balance rule applies to bare brackets), and the
        reverse pass reads Word's plain `[` run exactly that way, so the
        Op spelling is the Rule 0-reachable one. This is the same
        leniency the stray-closer path (`_BARE_CLOSERS`) already has:
        real documents contain unbalanced brackets (measured on the .tex
        corpus: `\\tau \\in [0, \\infty)`), and refusing to parse them
        cost the whole equation."""
        close_spelling = _BARE_PAIRS[t.text]
        save = self.i
        self.advance()

        def stop(tok):
            if (tok.kind == "char" or tok.kind == "macro") \
                    and tok.text == close_spelling:
                return True
            # The `(` scan must not cross the enclosing group boundary:
            # `{\partial(m}` is a group holding a bare `(` with no closer in
            # sight (measured: the reverse emitter's group-subscript spelling
            # `{\partial(m}_{i}M_{s})` from Word's sSub(base="ÃƒÂ¢Ã‹â€ Ã¢â‚¬Å¡(m")). The
            # rbrace is a boundary, not a closer -- fall back to Op, as
            # below.
            if tok.kind == "rbrace":
                return True
            return False

        row = self.parse_sequence(stop, opener=t, eof_ok=True)
        if self.peek().kind in ("eof", "rbrace"):
            # No closer anywhere (or none before the group ends): the opener
            # is an ordinary character. `save` points at the `[` itself,
            # which the advance at the top already consumed -- land one past
            # it, so the caller re-parses the content, not the bracket (a
            # second `[` parse would loop).
            self.i = save + 1
            return Op(DELIM_SPELLING_TO_CHAR[t.text])
        self.advance()
        open_ch = DELIM_SPELLING_TO_CHAR[t.text]
        close_ch = DELIM_SPELLING_TO_CHAR[close_spelling]
        folded = _fold_delim_matrix(open_ch, close_ch, row)
        if folded is not None:
            return folded
        return Delim(open_ch, close_ch, (row,))

    # -- macros --
    def parse_macro(self, t):
        macro = _MACRO_ALIASES.get(t.text, t.text)

        if macro in _UNSUPPORTED:
            self.fail(UnsupportedConstructError,
                      f"{macro}: {_UNSUPPORTED[macro]}", t)
        if macro in (_NARY_LIMITS_MODIFIER, _NARY_NOLIMITS_MODIFIER):
            # `_h_nary` consumes these itself when they legally follow an
            # n-ary operator; reaching this dispatch means they didn't.
            self.fail(UnexpectedTokenError,
                      f"{macro} is only valid directly after an n-ary "
                      f"operator", t)
        if macro == "\\left":
            return self.parse_left_right(t, is_left=True)
        if macro in _BIG_SIZERS:
            # Ãƒâ€šÃ‚Â§6.2: fixed-size opener; the delimiter that follows decides
            # the open character (the size is not carried -- L*).
            return self.parse_left_right(t, is_left=False)
        if macro == "\\right" or macro in _BIG_CLOSER_ONLY:
            self.fail(UnexpectedTokenError, f"{macro} with no opener", t)
        if macro == "\\middle":
            self.advance()
            return Op(self.read_delim_spec(t))
        if macro == "\\pmod":
            return self._parse_pmod(t)
        if macro == _OPERATORNAME:
            self.advance()
            arg = self.advance()
            if arg.kind != "rawarg":  # pragma: no cover - tokenizer pairs these
                self.fail(MalformedArgumentError, "\\operatorname without {name}", t)
            return OpName(arg.text.strip())
        if macro == _MATHRM:
            self.advance()
            arg = self.advance()
            if arg.kind != "rawarg":  # pragma: no cover - tokenizer pairs these
                self.fail(MalformedArgumentError, "\\mathrm without {name}", t)
            return OpName(arg.text.strip(), is_mathrm=True)
        if macro in _VARIANT_MACROS:
            self.advance()
            body = self.parse_argument()
            return _apply_variant(body, _VARIANT_MACROS[macro], self, t)

        entry = MACRO_TO_CONSTRUCT.get(macro)
        if entry is not None:
            construct, props = entry
            handler = _MACRO_HANDLERS.get(construct.name)
            if handler is None:  # pragma: no cover - table/handler mismatch
                self.fail(UnsupportedConstructError,
                          f"{macro}: construct {construct.name!r} has no parser", t)
            return handler(self, t, macro, props)

        if macro in _ESCAPED_LITERALS:
            self.advance()
            return Op(_ESCAPED_LITERALS[macro])
        if macro in MACRO_TO_CHAR:
            self.advance()
            ch = MACRO_TO_CHAR[macro]
            return Ident(ch) if ch.isalpha() else Op(ch)
        if macro in _STYLE_NOOPS:
            # The document layer already determines whether this is an
            # inline or display zone; the declaration has no further OMML
            # effect and must not make an otherwise valid expression fail.
            self.advance()
            return None
        if macro in _TOLERATED:
            # Ãƒâ€šÃ‚Â§6.2: document-layer metadata with no OMML home. Consumed as
            # a no-op (with its braced argument, when it takes one) and
            # named in the warning summary -- a dropped anchor is visible,
            # never silent. The coverage tool counts these deferred.
            # Returns `None`, not a node: an empty-Op placeholder used to
            # pollute the AST (a Row containing it serialized the same as
            # one without it, so gen1 and gen2 ASTs differed -- see Ãƒâ€šÃ‚Â§6.2
            # record), and it broke Rule 2 function application (`\ln\!x`
            # must stay one Func; `try_parse_operand` skips these).
            return self._consume_tolerated(t)
        self.fail(UnknownMacroError, f"unknown macro {macro}", t)

    def _consume_tolerated(self, t):
        """Advance past a Ãƒâ€šÃ‚Â§6.2 tolerated no-op (and its paired rawarg,
        when it takes one), record the named warning, and return `None` --
        the node that never enters the AST. Shared with `try_parse_operand`'s
        transparent skip, so a no-op between an operator name and its
        operand is warned exactly once."""
        macro = t.text
        self.advance()
        if macro in _TOLERATED_WITH_ARG and self.peek().kind == "rawarg":
            self.advance()
        if self.warnings is not None:
            self.warnings.append(f"{macro}: {_TOLERATED[macro]}")
        return None

    def parse_left_right(self, t, is_left=True):
        """A `\\left`-class delimited group: `\\left` (strict: an
        unmatched opener is an error) or a Ãƒâ€šÃ‚Â§6.2 fixed-size opener
        (`\\bigl` & co.; lenient: an unmatched opener closes at the end of
        the expression with the null delimiter, `\\right.`). The content
        runs to the next closer -- `\\right` always, a fixed-size closer
        (`\\bigr`) always, and the ambiguous sizes (`\\big`, `\\Big`,
        `\\bigg`, `\\Bigg`) when the delimiter character that follows them
        is a closing one (`\\big)` closes, `\\big(` opens a nested
        group)."""
        self.advance()
        open_ch = self.read_delim_spec(t)
        nxt = self.peek()
        if not is_left and nxt.kind in ("sub", "sup", "prime"):
            # Ãƒâ€šÃ‚Â§6.2: `\Big|_{\varphi=\pi/2}` -- a fixed-size delimiter with
            # nothing between it and a script is the evaluation-bar idiom
            # `\left.\right|_{...}` written with \Big: one standalone tall
            # glyph, script attached to it. Parsed as the null-open pair
            # with empty content, so the script lands *outside* the
            # delimiters and the canonical spelling round-trips (measured
            # on the .tex corpus, latex25/28/29). TeX does the same for
            # any lone \big delimiter atom; `\left|` stays strict.
            return Delim(None, open_ch, (Row(()),))
        row = self.parse_sequence(self._delim_stop(is_left), opener=t,
                                  eof_ok=not is_left)
        if self.peek().kind == "eof":
            if is_left:
                self.fail(UnbalancedDelimiterError, "\\left with no \\right",
                          t)
            close_ch = ""
        else:
            self.advance()  # the closer macro
            close_ch = self.read_delim_spec(t)
        folded = _fold_delim_matrix(open_ch, close_ch, row)
        if folded is not None:
            return folded
        return Delim(open_ch or None, close_ch or None, (row,))

    def _delim_stop(self, is_left):
        def stop(tok):
            if tok.kind != "macro":
                return False
            m = _MACRO_ALIASES.get(tok.text, tok.text)
            if m == "\\right" or m in _BIG_CLOSER_ONLY:
                return True
            if m in _BIG_SIZERS:
                # Ambiguous opener/closer: the delimiter that follows
                # decides. An opening char means a nested group (`\big(`);
                # a closing char (including the self-paired `|`/`ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬â€œ`)
                # means this group ends.
                nxt = self.peek(1)
                if nxt.kind in ("char", "macro"):
                    ch = DELIM_SPELLING_TO_CHAR.get(
                        _MACRO_ALIASES.get(nxt.text, nxt.text))
                    if ch is not None and ch in CLOSE_CHARS:
                        return True
            return False
        return stop

    def _parse_pmod(self, t):
        """`\\pmod{n}` is sugar, not a Rule 0 element of its own: "space, open
        paren, upright mod, argument, close paren", built entirely from
        constructs already in the inventory (`Space`, `Delim`, `OpName`) --
        see CANONICAL.md Rule 2. `mod` is not one of Rule 2's standard names
        and this `OpName("mod")` is never paired with an operand into an
        `m:func` (a `Space` sits between it and `arg`, not adjacency), so it
        is exactly the standalone-run case CANONICAL.md's `\\mathrm` note
        (item 3) covers: indistinguishable at the OMML level from
        `\\mathrm{mod}`/`\\operatorname{mod}` written directly, so it must
        canonicalize the same way they would -- `is_mathrm=True` makes
        `serialize` produce `\\mathrm{mod}` here, matching what round-tripping
        this through real OMML and back already produces regardless (OMML
        carries no record of which of the three sources it came from)."""
        self.advance()
        arg = self.parse_argument()
        inner = Row((OpName("mod", is_mathrm=True), Space(_PMOD_INNER_WIDTH), arg))
        return Row((Space(_PMOD_OUTER_WIDTH), Delim("(", ")", (inner,))))

    def read_delim_spec(self, opener):
        """The delimiter spelling following `\\left`/`\\right` -> its
        character (`""` for the null form `.`)."""
        t = self.peek()
        if t.kind in ("char", "macro"):
            spelling = _MACRO_ALIASES.get(t.text, t.text)
            if spelling in DELIM_SPELLING_TO_CHAR:
                self.advance()
                return DELIM_SPELLING_TO_CHAR[spelling]
        self.fail(MalformedArgumentError,
                  f"{t.text!r} is not a delimiter", t)

    # -- environments --
