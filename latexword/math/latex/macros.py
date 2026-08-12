# User macro expansion

from ..common import (
    _DEF_MACROS, _DEFS_RE, _RAW_ARG_MACROS, LatexParseError,
    MalformedArgumentError,
)
from .tokenize import _MACRO_RE, _Token, tokenize
from ...compat.macros import (
    MacroDefinitionError, MacroEnv, _MAX_EXPANSION_DEPTH,
    substitute as _macro_substitute,
)

# --- Â§6.2 user macros: the expansion pass ------------------------------------
#
# `tokenize_with_macros` is the tokenizer used by `parse`: tokenize, then
# walk the stream once, left to right -- exactly TeX's temporal order --
# consuming declarations (`defspec` tokens) into the `MacroEnv` and
# expanding every use of a declared macro (substitute, deliberately
# re-tokenize, splice). `compat/` is vocabulary, not a second grammar:
# nothing here rewrites raw text; the substituted body re-enters the
# tokenizer as markup by design, which is what "expansion" means.


def tokenize_with_macros(src, warnings=None):
    """`tokenize` plus the Â§6.2 user-macro pass. Returns
    (tokens, env) with every declaration consumed and every expansion
    resolved -- the parser downstream never sees a declaration or an
    unexpanded defined macro. Raises `LatexParseError` for declarations
    outside the supported subset, recursive expansion, and runaway depth.

    Fast path: a source containing none of the declaration macros and no
    `\\ensuremath` can produce no `defspec` token, and with an empty env
    the pass is a pure copy of the token list -- so plain `tokenize` is
    returned directly. Semantically identical (nothing else in the pass
    can fire). The corpus has zero declarations, so this keeps the
    common case free of the extra pass."""
    env = MacroEnv(warnings)
    if _DEFS_RE.search(src) is None:
        return tokenize(src), env
    reserved = _RAW_ARG_MACROS | _DEF_MACROS | {"\\begin", "\\end"}
    return _expand_tokens(tokenize(src), src, env, reserved, []), env


def _body_tokens(text):
    """Tokenize a substitution body without its trailing `eof` token: the
    splice must not truncate the surrounding stream (a body's own eof in
    the middle of the output would end the parse there)."""
    return tokenize(text)[:-1]


def _expand_tokens(toks, src, env, reserved, stack):
    out = []
    i = 0
    n = len(toks)
    while i < n:
        t = toks[i]
        if t.kind == "defspec":
            m = _MACRO_RE.match(t.text)
            kind = m.group(0) if m is not None else ""
            try:
                env.declare_spec(kind, t.text[len(kind):], reserved)
            except MacroDefinitionError as e:
                raise LatexParseError(str(e), src, t.pos, t.text) from e
            i += 1
            continue
        if t.kind == "macro" and t.text == "\\ensuremath":
            # \ensuremath{x} is {x} in math mode: splice the argument as a
            # group, so script binding sees one atom. The tokenizer paired
            # the rawarg, so the next token is guaranteed to be it.
            arg = toks[i + 1]
            inner = _expand_tokens(
                _body_tokens(arg.text), src, env, reserved, stack)
            out.append(_Token("lbrace", "{", arg.pos))
            out.extend(inner)
            out.append(_Token("rbrace", "}", arg.pos))
            i += 2
            continue
        if t.kind == "macro":
            m = env.lookup(t.text)
            if m is not None:
                if t.text in stack:
                    raise LatexParseError(
                        f"recursive macro expansion: "
                        f"{' -> '.join(stack + [t.text])}",
                        src, t.pos, t.text)
                if len(stack) >= _MAX_EXPANSION_DEPTH:
                    raise LatexParseError(
                        f"macro expansion exceeds the depth limit of "
                        f"{_MAX_EXPANSION_DEPTH} nested user macros",
                        src, t.pos, t.text)
                args = []
                k = i + 1
                for _ in range(m.argc):
                    if k >= n or toks[k].kind in ("eof", "rbrace"):
                        raise MalformedArgumentError(
                            f"{t.text} needs {m.argc} argument(s), "
                            f"got {len(args)}", src, t.pos, t.text)
                    tk = toks[k]
                    if tk.kind == "lbrace":
                        depth = 1
                        parts = []
                        k += 1
                        while depth:
                            if k >= n:
                                raise MalformedArgumentError(
                                    f"{t.text}: unterminated argument group",
                                    src, t.pos, t.text)
                            tk2 = toks[k]
                            if tk2.kind == "lbrace":
                                depth += 1
                                parts.append(tk2.text)
                            elif tk2.kind == "rbrace":
                                depth -= 1
                                if depth:
                                    parts.append(tk2.text)
                            else:
                                parts.append(tk2.text)
                            k += 1
                        args.append("".join(parts))
                    else:
                        args.append(tk.text)
                        k += 1
                body = _macro_substitute(m.body, args)
                out.extend(_expand_tokens(
                    _body_tokens(body), src, env, reserved, stack + [t.text]))
                i = k
                continue
        out.append(t)
        i += 1
    return out




__all__ = [name for name in globals() if not name.startswith("__")]
