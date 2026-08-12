r"""User macro declarations (PLAN.md §6.2): `\newcommand`, `\renewcommand`,
`\def`, `\DeclareMathOperator`, `\ensuremath`.

Expansion happens at parse time, on the token stream -- never on raw text
(compat/ is vocabulary, not a second grammar: a replacement whose output
is re-read *as text* into the grammar is exactly how `\textbackslash{}`
grew one copy per generation). A declaration is captured by the tokenizer
as one raw token, so its body is neither tokenized nor expanded at
declaration time -- lazy, as in TeX. At each use the body is substituted
and deliberately re-tokenized; that re-tokenization is what "expansion"
means, not a corruption.

Scope: one `MacroEnv` per `parse()` call. Document-level declarations (a
preamble `\newcommand` used by later equations) would need the document
layer to collect declarations across expressions; that is not implemented.
Measured corpus occurrences of any user macro: zero -- the 48-file .tex
corpus never declares one. A declaration outside the current expression
leaves the macro unknown there, and the unknown-macro path reports it
honestly (whole-expression fallback, not a silent approximation).

Beyond the argument-substitution subset -- `\newcommand`'s default-argument
form (`[n][d]`), non-contiguous or non-digit parameters, `\DeclareMathOperator*`,
`##` beyond the escape, conditionals, `\expandafter` and friends -- is
*not* implemented: such a declaration raises `MacroDefinitionError` and
the expression fails, falling back to monospaced literal LaTeX with a
warning, exactly the unknown-vocabulary path. Never mis-parse it.

Positions in diagnostics are approximate when the failure is *inside*
expanded text: the offending token's position indexes the substitution
string, not the source.
"""

# Hard ceiling on nested user-macro expansions (TeX has no limit; the
# corpus has no macros at all, so this only guards a runaway source).
_MAX_EXPANSION_DEPTH = 16

import re


class MacroDefinitionError(ValueError):
    """A declaration is outside the supported argument-substitution subset.
    Raised by `MacroEnv.declare_spec`; `latex2omml` wraps it in a
    `LatexParseError` with source position."""


_NAME_RE = re.compile(r"\\[a-zA-Z]+")


class UserMacro:
    """One declared macro. `name` includes the backslash; `argc` is 0..9;
    `body` is the replacement text, kept as text and tokenized at every use
    (lazy expansion, like TeX)."""

    __slots__ = ("name", "argc", "body")

    def __init__(self, name, argc, body):
        self.name = name
        self.argc = argc
        self.body = body

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"<UserMacro {self.name} [{self.argc}]>"


def _read_balanced(text, i):
    """`text[i] == '{'`: return (content, index_after_closing_brace)."""
    depth = 0
    j = i
    n = len(text)
    while j < n:
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[i + 1:j], j + 1
        j += 1
    raise MacroDefinitionError("unterminated group in macro declaration")


def _skip_ws(text, i):
    while i < len(text) and text[i].isspace():
        i += 1
    return i


class MacroEnv:
    """The declaration registry for one `parse()` call. `warnings` is the
    §6.2 sink: a redefinition (`\renewcommand`) records what it did there,
    so nothing is dropped silently."""

    def __init__(self, warnings=None):
        self.macros = {}
        self.warnings = warnings

    def lookup(self, name):
        return self.macros.get(name)

    def declare(self, name, argc, body, redef=False):
        if name in self.macros and not redef:
            if self.warnings is not None:
                self.warnings.append(
                    f"{name}: redefined (\\newcommand of an existing macro; "
                    "\\renewcommand is the standard spelling)")
        if self.warnings is not None and redef and name not in self.macros:
            self.warnings.append(
                f"{name}: \\renewcommand of an undefined macro "
                "(defined as new)")
        self.macros[name] = UserMacro(name, argc, body)

    def declare_spec(self, kind, spec, reserved=()):
        """Parse and register one declaration; `kind` is the declaration
        macro (`\\newcommand`, `\\def`, ...), `spec` is the raw text the
        tokenizer captured after it, and `reserved` the names the caller's
        tokenizer treats specially (raw-argument pairing, declaration
        capture -- redefining those would corrupt the token stream).
        Raises `MacroDefinitionError` for anything beyond the supported
        subset."""
        if kind in ("\\newcommand", "\\renewcommand", "\\DeclareMathOperator"):
            name, argc, body = self._parse_braced(kind, spec)
        elif kind == "\\def":
            name, argc, body = self._parse_def(spec)
        else:  # pragma: no cover - the tokenizer only emits known kinds
            raise MacroDefinitionError(f"unknown declaration {kind}")
        if name in reserved:
            raise MacroDefinitionError(
                f"{name}: reserved macro name, cannot be declared")
        self.declare(name, argc, body, redef=(kind == "\\renewcommand"))

    # -- the two declaration shapes -----------------------------------------

    def _parse_braced(self, kind, spec):
        i = _skip_ws(spec, 0)
        if i >= len(spec) or spec[i] != "{":
            raise MacroDefinitionError(
                f"{kind} without a braced macro name")
        name, i = _read_balanced(spec, i)
        name = name.strip()
        if not _NAME_RE.fullmatch(name):
            raise MacroDefinitionError(
                f"{kind}: macro name {name!r} is not a backslash-letter name")
        argc = 0
        if kind == "\\newcommand" or kind == "\\renewcommand":
            i = _skip_ws(spec, i)
            if i < len(spec) and spec[i] == "[":
                j = spec.find("]", i)
                if j < 0 or not spec[i + 1:j].isdigit():
                    raise MacroDefinitionError(
                        f"{kind}: argument count [n] must be a digit string")
                argc = int(spec[i + 1:j])
                if argc > 9:
                    raise MacroDefinitionError(
                        f"{kind}: argument count {argc} exceeds the "
                        "supported subset (max 9)")
                i = _skip_ws(spec, j + 1)
                if i < len(spec) and spec[i] == "[":
                    raise MacroDefinitionError(
                        f"{kind}: the default-argument form [n][d] is "
                        "beyond the supported subset")
            if argc and (i >= len(spec) or spec[i] != "{"):
                raise MacroDefinitionError(
                    f"{kind}: missing body for a {argc}-argument macro")
        else:  # \DeclareMathOperator
            if i < len(spec) and spec[i] == "*":
                raise MacroDefinitionError(
                    "\\DeclareMathOperator* (limits form) is beyond the "
                    "supported subset")
        if i >= len(spec) or spec[i] != "{":
            raise MacroDefinitionError(f"{kind} without a body")
        body, i = _read_balanced(spec, i)
        tail = _skip_ws(spec, i)
        if tail != len(spec):
            raise MacroDefinitionError(
                f"{kind}: trailing content after the declaration body")
        if kind == "\\DeclareMathOperator":
            body = "\\operatorname{%s}" % body
        return name, argc, body

    def _parse_def(self, spec):
        i = _skip_ws(spec, 0)
        if i >= len(spec) or spec[i] != "\\":
            raise MacroDefinitionError("\\def without a macro name")
        m = _NAME_RE.match(spec, i)
        if m is None:
            raise MacroDefinitionError("\\def: macro name must be letters")
        name = m.group(0)
        i = _skip_ws(spec, m.end())
        params = []
        while i < len(spec) and spec[i] == "#":
            if i + 1 >= len(spec) or not spec[i + 1].isdigit():
                raise MacroDefinitionError(
                    "\\def: parameter must be #1..#9")
            params.append(int(spec[i + 1]))
            i = _skip_ws(spec, i + 2)
        if params and (params != list(range(1, len(params) + 1))):
            raise MacroDefinitionError(
                "\\def: parameters must be #1..#N in order")
        if i >= len(spec) or spec[i] != "{":
            raise MacroDefinitionError("\\def without a body")
        body, i = _read_balanced(spec, i)
        tail = _skip_ws(spec, i)
        if tail != len(spec):
            raise MacroDefinitionError("\\def: trailing content after the body")
        return name, len(params), body


def substitute(body, args):
    """The argument-substitution subset: `#1`..#N are replaced by `args`
    (texts, braces already stripped for group arguments); `##` is the
    literal `#` escape. Any other `#` is left as-is and will fail the
    parse -- TeX errors on a bare `#` in math too."""
    if "#" not in body:
        return body
    out = []
    i = 0
    n = len(body)
    while i < n:
        c = body[i]
        if c != "#":
            out.append(c)
            i += 1
            continue
        if i + 1 < n and body[i + 1] == "#":
            out.append("#")
            i += 2
            continue
        if i + 1 < n and body[i + 1].isdigit():
            k = int(body[i + 1])
            if 1 <= k <= len(args):
                out.append(args[k - 1])
            else:
                out.append(body[i:i + 2])
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)
