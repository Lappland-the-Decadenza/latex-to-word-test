from . import parse_shared as _shared
globals().update({name: getattr(_shared, name) for name in _shared.__all__})


class _EnvironmentParserMixin:
    def parse_array_cols(self, opener):
        """CANONICAL.md's array rule: `\\begin{array}` is always followed by
        a mandatory `{...}` column-spec argument of `l`/`c`/`r` letters
        (one per column) -- nothing else is in the Rule 0 target inventory,
        so any other letter is a located, typed parse error rather than a
        silent drop."""
        t = self.peek()
        if t.kind != "lbrace":
            self.fail(MalformedArgumentError,
                      "\\begin{array} without a column spec", t)
        self.advance()
        letters = []
        while True:
            tok = self.peek()
            if tok.kind == "rbrace":
                self.advance()
                break
            if tok.kind == "eof":
                self.fail(UnbalancedDelimiterError,
                          "unterminated array column spec", opener)
            if tok.kind == "char" and tok.text in ("l", "c", "r"):
                letters.append(tok.text)
                self.advance()
                continue
            self.fail(MalformedArgumentError,
                      f"unsupported array column spec character {tok.text!r} "
                      f"-- only l/c/r are in the Rule 0 target inventory", tok)
        if not letters:
            self.fail(MalformedArgumentError, "empty array column spec", opener)
        return tuple(letters)

    def parse_environment(self):
        t = self.advance()
        raw_env = t.text
        env = _ENV_ALIASES.get(raw_env, raw_env)
        if env not in _MATRIX_ENVS:
            self.fail(UnsupportedConstructError,
                      f"environment {raw_env!r} is not in the Rule 5 "
                      f"multi-row set", t)
        cols = self.parse_array_cols(t) if env == "array" else None

        def stop(tok):
            return tok.kind in ("amp", "rowsep") or (
                tok.kind == "end" and _ENV_ALIASES.get(tok.text, tok.text) == env)

        rows = []
        cells = []
        while True:
            cells.append(self.parse_sequence(stop, opener=t))
            nxt = self.peek()
            if nxt.kind == "amp":
                self.advance()
                continue
            if nxt.kind == "rowsep":
                self.advance()
                rows.append(tuple(cells))
                cells = []
                continue
            if nxt.kind == "end":
                self.advance()
                break
            self.fail(UnbalancedDelimiterError,
                      f"\\begin{{{raw_env}}} with no \\end", t)
        if cells and not (len(cells) == 1 and not cells[0].items):
            rows.append(tuple(cells))
        if cols is not None:
            # Rule 5's mismatch clause: a column spec whose width disagrees
            # with the rows is a located, typed parse error, never a silent
            # pad/truncate.
            ncols = max((len(row) for row in rows), default=0)
            if ncols != len(cols):
                self.fail(
                    MalformedArgumentError,
                    f"\\begin{{array}}{{{''.join(cols)}}} declares "
                    f"{len(cols)} column(s) but the rows have {ncols}", t)
        return Matrix(tuple(rows), env, cols)
