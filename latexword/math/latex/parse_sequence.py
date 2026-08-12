from . import parse_shared as _shared
globals().update({name: getattr(_shared, name) for name in _shared.__all__})
from .parse_handlers import _is_opname_expr


class _SequenceParserMixin:
    def parse_sequence(self, stop, opener=None, eof_ok=False):
        """Parse sibling atoms until `stop` says to halt (the stopping token
        is left unconsumed). `opener` is the token that opened this scope, so
        an unexpected EOF can point at it. `eof_ok` closes the scope at the
        end of the expression instead of failing -- the Ãƒâ€šÃ‚Â§6.2 lenient
        fixed-size delimiters use it (an unmatched `\\bigl(` ends as
        `\\right.`); `\\left` stays strict."""
        items = []
        while True:
            t = self.peek()
            if t.kind == "eof" and stop is not _stop_eof:
                if eof_ok:
                    break
                self.fail(UnbalancedDelimiterError,
                          "unexpected end of input, unclosed group", opener or t)
            if stop(t):
                break
            node = self.parse_scripted()
            if node is None:
                # Ãƒâ€šÃ‚Â§6.2 tolerated no-op: nothing to append.
                continue
            if isinstance(node, _NaryHead):
                body = self.parse_nary_body(node.op, stop, opener)
                items.append(Nary(node.op, node.sub, node.sup, body, node.limits))
                continue
            if _is_opname_expr(node):
                node = self.parse_func_chain(node, stop)
            items.append(fold_linear_fraction(self, node, stop))
        return Row(tuple(items))

    def _peek_starts_nary(self, t):
        """True if `t` is the macro token that would open a *new* n-ary
        operator, without consuming anything -- the boundary-body helpers
        below need to know this *before* parsing, unlike every other
        boundary (relation/binary glyph), because the n-ary head itself
        already consumes its own scripts (`_h_nary`) and stopping only after
        that would swallow them into the wrong body."""
        if t.kind != "macro":
            return False
        macro = _MACRO_ALIASES.get(t.text, t.text)
        entry = MACRO_TO_CONSTRUCT.get(macro)
        return entry is not None and entry[0].name == "nary"

    def _nary_body_boundary_char(self, t):
        """The character `t` would parse to, if it is a plain relation/+-/
        glyph token (char literal or a SYMBOL_MAP-derived macro) -- else
        None. Used by the boundary-body helpers to decide whether `t` is a
        boundary without actually consuming/parsing it."""
        if t.kind == "char":
            return t.text
        if t.kind == "macro":
            macro = _MACRO_ALIASES.get(t.text, t.text)
            return MACRO_TO_CHAR.get(macro)
        return None

    def _is_relation_or_binary_boundary(self, t):
        ch = self._nary_body_boundary_char(t)
        return ch is not None and (
            ch in NARY_BODY_RELATION_CHARS or ch in NARY_BODY_BINARY_CHARS
        )

    def _parse_one_body_atom(self, stop):
        """Parse exactly one atom for a boundary-limited body (an n-ary
        operand or a big-operator function operand): a scripted atom, with
        a nested n-ary head completed into a real `Nary` (bounded the same
        way) and an operator-name expression allowed to claim its own
        operand first (Rule 2), exactly as the generic sequence loop does.
        The caller is responsible for having already checked that the next
        token is not itself a boundary."""
        t = self.peek()
        node = self.parse_scripted()
        if isinstance(node, _NaryHead):
            body = self.parse_nary_body(node.op, stop, t)
            node = Nary(node.op, node.sub, node.sup, body, node.limits)
        if _is_opname_expr(node):
            node = self.parse_func_chain(node, stop)
        return fold_linear_fraction(self, node, stop)

    def parse_bounded_body(self, stop, opener, use_differential):
        """Shared entry point for every "operand that is not the rest of the
        row" case (CANONICAL.md rule 16): an n-ary's body, or a big
        operator's (`\\lim`/`\\max`/...) function operand. Braces are always
        authoritative -- if the next token is `{`, that braced group is the
        body, full stop, and none of the heuristics below run at all."""
        t = self.peek()
        if t.kind == "lbrace":
            self.advance()
            row = self.parse_sequence(_stop_rbrace, opener=t)
            self.advance()  # the '}'
            return row
        if use_differential:
            return self._parse_integral_body(stop, opener)
        return self._parse_relation_bounded_body(stop, opener)

    def parse_nary_body(self, op_char, stop, opener=None):
        """Defect 2/3 (CANONICAL.md rule 16): an n-ary operator's body, when
        not an explicit `{...}` group. Sums/products/unions (`op_char` in
        `mathsyms.NARY_UNDOVR`) keep the run-to-boundary (relation/top-level
        +-) rule: `\\sum_k \\frac{1}{k}x^k` and `\\sum_k a_k b_k` are single
        terms by convention, and stopping at one atom would cut them in
        half. Integrals get the differential-driven rule instead (Task B) --
        see `_parse_integral_body`."""
        use_differential = op_char not in NARY_UNDOVR
        return self.parse_bounded_body(stop, opener, use_differential)

    def _parse_relation_bounded_body(self, stop, opener):
        """A maximal run of scripted atoms, stopping *before* a top-level
        relation, a top-level binary +/-, another n-ary head, or wherever
        `stop` already stops -- not "the rest of the enclosing row" (the old
        behaviour, which swallowed `= g` in `\\int f dx = g` into the
        integrand). Used directly for sums/products, and as the integral
        rule's fallback when no differential is found."""
        items = []
        while True:
            t = self.peek()
            if t.kind == "eof":
                if stop is not _stop_eof:
                    self.fail(UnbalancedDelimiterError,
                              "unexpected end of input, unclosed group", opener or t)
                break
            if stop(t):
                break
            if self._peek_starts_nary(t):
                break
            if self._is_relation_or_binary_boundary(t):
                break
            items.append(self._parse_one_body_atom(stop))
        return Row(tuple(items))

    # -- integrals: differential-driven scope (Task B) --

    _DIFFERENTIAL_IDENT_CHARS = frozenset("dÃƒÂ¢Ã‹â€ Ã¢â‚¬Å¡ÃƒÂ¢Ã¢â‚¬Â¦Ã¢â‚¬Â ")

    def _is_differential_marker(self, node):
        """Pattern (a)'s left half: is `node` one of the glyphs a
        differential is conventionally spelled with (`d`, `\\partial`,
        U+2146 DOUBLE-STRUCK ITALIC SMALL D, `\\mathrm{d}`, `\\text{d}`)?
        This alone does not mean "this is a differential" -- see
        `_parse_integral_body`, which also requires a *following* atom in
        the same row: a lone `d` with nothing after it (the thickness
        variable in `\\rho\\frac{d}{S}`, a real and frequent corpus pattern)
        is not one, and relaxing this guard misreads it."""
        if isinstance(node, Ident) and node.char in self._DIFFERENTIAL_IDENT_CHARS:
            return True
        if isinstance(node, Op) and node.char == "ÃƒÂ¢Ã‹â€ Ã¢â‚¬Å¡":
            return True
        if isinstance(node, OpName) and node.is_mathrm and node.name == "d":
            return True
        if isinstance(node, Text) and node.s == "d":
            return True
        return False

    def _row_has_differential(self, items):
        """Plain (no leading-position exception) adjacency scan: does this
        sequence of siblings contain a `d`-like atom immediately followed by
        another atom? Unlike the top-level scan in `_parse_integral_body`,
        no physics-ordering carve-out applies here -- `\\frac{dx}{x}`'s
        numerator row *is* `[d, x]` with the marker at position 0, and it
        must still count (that is the entire point of pattern (b))."""
        return any(
            self._is_differential_marker(items[i])
            for i in range(len(items) - 1)
        )

    def _atom_contains_differential(self, node):
        """Pattern (b): does `node` contain pattern (a) somewhere inside its
        own row(s) -- the differential-inside-a-fraction case,
        `\\int \\frac{dx}{x}` and `\\int \\frac{y_s(s)\\,ds}{\\cos\\varphi}`.
        Recurses through every child, treating a `Row` child as a sibling
        sequence (adjacency-checked) and any other child as a further
        nesting level to search."""
        if isinstance(node, Row):
            if self._row_has_differential(node.items):
                return True
            return any(self._atom_contains_differential(c) for c in node.items)
        for child in node.children():
            if self._atom_contains_differential(child):
                return True
        return False

    def _absorb_consecutive_differentials(self, items, stop):
        """After `_parse_integral_body` has just completed one differential
        pair, greedily absorb any further *consecutive* ones (`\\iint
        f\\,dx\\,dy` must take both) -- skipping over `Space` atoms (`\\,`)
        between them, since those separate consecutive differentials without
        being one themselves. Every attempt is fully speculative: if the
        next non-space atom is not a `d`-like marker, or nothing legal
        follows it, every token examined in that attempt (including any
        skipped spaces) is rewound and left for the caller."""
        while True:
            save = self.i
            pending = []
            while True:
                t = self.peek()
                if t.kind == "eof" or stop(t) or self._peek_starts_nary(t):
                    self.i = save
                    return
                node = self._parse_one_body_atom(stop)
                if isinstance(node, Space):
                    pending.append(node)
                    continue
                candidate = node
                break
            if not self._is_differential_marker(candidate):
                self.i = save
                return
            t2 = self.peek()
            if t2.kind == "eof" or stop(t2) or self._peek_starts_nary(t2):
                self.i = save
                return
            follower = self._parse_one_body_atom(stop)
            items.extend(pending)
            items.append(candidate)
            items.append(follower)

    def _parse_integral_body(self, stop, opener):
        """Integrals (defect 2/3, Task B): the body ends at the end of the
        first differential run, not at the next relation/+-/n-ary boundary
        (`_parse_relation_bounded_body`, used here only as a fallback when
        no differential is ever found in the scanned span). A differential
        run is pattern (a) -- a `d`-like atom immediately followed by
        another atom in the same row -- or pattern (b), an atom that
        contains pattern (a) inside its own nested row(s)
        (`\\frac{dx}{x}`). Consecutive differentials are then absorbed
        (`\\iint f\\,dx\\,dy`).

        Pattern (a)'s "not the very first atom of this body" exception is
        the physics-ordering guard: `\\int dx\\, f(x)` puts the differential
        before the integrand, so finding it in leading position must not
        end the body there -- only a *later* occurrence, once an integrand
        has already been collected, is the terminator. This exception does
        NOT apply to pattern (b): `\\int \\frac{y_s(s)\\,ds}{\\cos\\varphi}
        \\cdot h` must still stop right after the (leading, and only) `Frac`
        atom, excluding `\\cdot h`."""
        items = []
        while True:
            t = self.peek()
            if t.kind == "eof":
                if stop is not _stop_eof:
                    self.fail(UnbalancedDelimiterError,
                              "unexpected end of input, unclosed group", opener or t)
                return Row(tuple(items))
            if stop(t):
                return Row(tuple(items))
            if self._peek_starts_nary(t):
                return Row(tuple(items))
            if self._is_relation_or_binary_boundary(t):
                return Row(tuple(items))

            node = self._parse_one_body_atom(stop)
            items.append(node)

            prev_idx = len(items) - 2
            if prev_idx >= 1 and self._is_differential_marker(items[prev_idx]):
                self._absorb_consecutive_differentials(items, stop)
                return Row(tuple(items))
            if self._atom_contains_differential(node):
                return Row(tuple(items))

    def parse_func_chain(self, name_node, stop):
        """Rule 2 function application, right-associated: `\\ln \\tan X`
        must read as `\\ln(\\tan(X))`, not "ln's operand is \\tan, and X
        floats alongside" (defect D1 in the R3 rendering-oracle sweep). The
        adjacency rule itself is unchanged -- an operand is still exactly
        one scripted atom (`try_parse_operand`) -- but when that operand is
        itself an operator-name expression, it has not yet claimed *its own*
        operand, so recursing here lets it do so before this call wraps
        it. A plain operand (Ident, Frac, ...) is the base case and returns
        unchanged.

        NOT DONE: `mathsyms.BIG_OP_NAMES` (`\\lim`, `\\max`, ...) was meant
        to widen this to the same boundary-limited body an n-ary gets
        (`\\lim_{n\\to\\infty} a_n b_n` taking both factors), same idea as
        the differential rule below. Reverted: wiring it in broke
        `test_r3_emitter.test_deliberate_difference_limlow_vs_ssub`
        (`\\sup_{x} f(x)` against the old-pipeline oracle -- the operand
        widened from one atom (`f`) to two (`f`, `(x)`), a real, intentional
        behaviour change this task's own instructions said to report and
        stop on rather than paper over by changing the oracle test's
        expectation unilaterally. `BIG_OP_NAMES` stays defined in
        `mathsyms.py`, unused, for whoever picks this back up."""
        operand = self.try_parse_operand(stop)
        if operand is None:
            return name_node
        if _is_opname_expr(operand):
            operand = self.parse_func_chain(operand, stop)
        return Func(name_node, operand)

    def try_parse_operand(self, stop):
        """Rule 2 function application: return the next scripted atom if it
        can be an operand, else None (and consume nothing).

        Implemented by speculative parse + rewind rather than by a lookahead
        table, because "can this token start an operand" is a property of the
        resulting *node* (an `Op` glyph and a `Space` cannot be an operand;
        everything else can), and the node is what the table describes.

        An n-ary is a valid operand (defect B): `\\ln \\sum_{k} a_k` means the
        logarithm of the whole sum, exactly what the source says, and is what
        `math.load._load_func` produces reading `m:func(name=ln,
        argument=m:nary)` back. `_NaryHead` marks an n-ary operator before its
        body (bounded the same way `parse_sequence` bounds it) has been
        parsed -- so here, unlike the reject-and-rewind path below, the head
        is completed into a real `Nary` and returned rather than treated as
        "cannot be an operand". This does not consume anything `stop` should
        have kept: `parse_sequence` builds the identical `Nary` node from the
        identical span when no function name precedes the operator."""
        t = self.peek()
        # Ãƒâ€šÃ‚Â§6.2: tolerated no-ops (`\label`, `\hspace`, `\!`) are
        # transparent to Rule 2 function application -- `\ln\!x` is ln(x),
        # TeX treats them as no-ops, and an empty placeholder between name
        # and operand used to break the application (the Func re-formed on
        # the next generation: an AST difference). Consumed here with
        # their warnings; the reject-and-rewind below lands *after* them,
        # so the warning is recorded once.
        while t.kind == "macro" and t.text in _TOLERATED:
            self._consume_tolerated(t)
            t = self.peek()
        after_noops = self.i
        if t.kind in ("eof", "rbrace", "amp", "rowsep", "sub", "sup", "prime", "end"):
            return None
        if stop(t):
            return None
        node = self.parse_scripted()
        if isinstance(node, _NaryHead):
            body = self.parse_nary_body(node.op, stop, t)
            return Nary(node.op, node.sub, node.sup, body, node.limits)
        if node is None or isinstance(node, (Op, Space)):
            self.i = after_noops
            return None
        return node

    # -- scripts --
