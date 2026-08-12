"""Deterministic validation for the closed AI shadow grammar."""

from __future__ import annotations

import posixpath
import re

from ..document.diagnostics import Diagnostic, DiagnosticCode, Severity, SourceReference
from .profile import (
    AI_SHADOW_PROFILE_V1, ALLOWED_ENVIRONMENTS, BLOCK_VOCABULARY,
    FORBIDDEN_MATH_CARRIERS,
    INLINE_VOCABULARY, MAX_LIST_DEPTH, ENUMITEM_OPTION_KEYS,
    PACKAGE_WHITELIST, TODO_OPTION_KEYS,
)


_COMMAND = re.compile(r"\\([A-Za-z]+|.)")
_BEGIN_END = re.compile(r"\\(begin|end)\{([A-Za-z*]+)\}")
_ENV_OPEN = re.compile(r"\\begin\{(itemize|enumerate|description)\}(?:\[([^]]*)\])?")
_PACKAGE = re.compile(r"\\usepackage(?:\[[^]]*\])?\s*\{([^{}]+)\}")
_CLASS = re.compile(r"\\documentclass(?:\[[^]]*\])?\s*\{([^{}]+)\}")
_RESOURCE = re.compile(r"\\includegraphics(?:\[[^]]*\])?\s*\{([^{}]+)\}")
# These control symbols are consumed by the prose renderer as text escapes or
# a soft hyphen. Keep the validator aligned with that supported syntax.
_ALLOWED_SINGLE = frozenset("%&_#$~{}^\\[]-,; ")
_ALLOWED_COMMANDS = frozenset(
    {
        "begin", "end", "usepackage", "documentclass", "title", "author",
        "date", "maketitle", "item", "newpage", "tableofcontents",
        "sethlcolor", "includegraphics", "centering", "textbackslash",
        "textasciitilde", "textasciicircum", "ldots", "mbox", "par",
        "linebreak", "textquotesingle",
        "setmainfont", "setmonofont", "makeatletter", "makeatother",
        "arabic", "alph", "Alph", "roman", "Roman",
        "hline", "caption", "label", "url", "href", "ref", "pageref",
        "cite", "footnote", "endnote", "todo", "textbf", "textit", "emph", "texttt",
        "textsc", "underline", "sout", "textsuperscript", "textsubscript",
        "textcolor", "colorbox", "cellcolor", "parbox", "hl", "multicolumn", "multirow", "quad",
        "qquad", "theendnotes",
    }
    | BLOCK_VOCABULARY
    | INLINE_VOCABULARY
)
_DEFINITIONS = re.compile(r"\\(newcommand|renewcommand|providecommand|def|gdef|edef|let)\b")
_CUSTOM_DEFINITIONS = re.compile(r"\\(newenvironment|renewenvironment)\b")
_GENERATED_UNICODE_HIGHLIGHT = re.compile(
    r"\\makeatletter\s*"
    r"\\def\\lTwoWHighlightColor\{yellow\}\s*"
    r"\\renewcommand\{\\sethlcolor\}\[1\]\{\\def\\lTwoWHighlightColor\{#1\}\}\s*"
    r"\\renewcommand\{\\hl\}\[1\]\{\\colorbox\{\\lTwoWHighlightColor\}\{#1\}\}\s*"
    r"\\makeatother",
    re.DOTALL,
)
_FORBIDDEN = re.compile(
    r"\\(?:wstyle|wrstyle|word[A-Za-z]*|"
    + "|".join(re.escape(item) for item in sorted(FORBIDDEN_MATH_CARRIERS))
    + r")\b"
)


def _diag(code, message, index):
    return Diagnostic(
        DiagnosticCode(code), Severity.ERROR, message,
        SourceReference(part="native-latex", index=index),
    )


def _ranges(source):
    """Return ranges in which document commands are math, not shadow syntax."""
    found = []
    dollar_start = None
    index = 0
    while index < len(source):
        if source[index] == "\\" and index + 1 < len(source):
            if source.startswith(r"\[", index):
                end = source.find(r"\]", index + 2)
                if end >= 0:
                    found.append((index, end + 2, source[index + 2:end]))
                    index = end + 2
                    continue
            index += 2
            continue
        if source[index] == "$":
            if dollar_start is None:
                dollar_start = index
            else:
                found.append((dollar_start, index + 1, source[dollar_start + 1:index]))
                dollar_start = None
        index += 1
    for match in re.finditer(r"\\begin\{(equation\*?|align\*?|gather\*?)\}(.*?)\\end\{\1\}", source, re.S):
        found.append((match.start(), match.end(), match.group(2)))
    return sorted(found, key=lambda item: (item[0], -item[1]))


def _inside(index, ranges):
    return next((body for start, end, body in ranges if start <= index < end), None)


def _package_names(source):
    values = []
    for match in _PACKAGE.finditer(source):
        values.extend((item.strip(), match.start()) for item in match.group(1).split(","))
    return values


def _environment_diagnostics(source):
    diagnostics, stack = [], []
    math_ranges = _ranges(source)
    for match in _BEGIN_END.finditer(source):
        if _inside(match.start(), math_ranges) is not None:
            continue
        action, name = match.groups()
        if action == "begin":
            if name not in ALLOWED_ENVIRONMENTS:
                diagnostics.append(_diag("custom-environment", f"environment {name} is outside V1", match.start()))
            stack.append((name, match.start()))
        elif not stack or stack[-1][0] != name:
            diagnostics.append(_diag("broken-environment", f"unmatched \\end{{{name}}}", match.start()))
        else:
            stack.pop()
    diagnostics.extend(
        _diag("broken-environment", f"unclosed environment {name}", index)
        for name, index in stack
    )
    return diagnostics


def _environment_package_diagnostics(source, packages, fragment_kind):
    if fragment_kind != "document":
        return []
    diagnostics = []
    for match in _BEGIN_END.finditer(source):
        if match.group(1) != "begin":
            continue
        name = match.group(2)
        required = AI_SHADOW_PROFILE_V1.required_package(name.rstrip("*"))
        if required is not None and required not in packages:
            diagnostics.append(_diag(
                "unapproved-package",
                f"environment {name} requires package {required}",
                match.start(),
            ))
    return diagnostics


def _resource_diagnostics(source, known_resources):
    diagnostics = []
    if known_resources is None:
        return diagnostics
    known = {posixpath.normpath(str(item).replace("\\", "/")) for item in known_resources}
    for match in _RESOURCE.finditer(source):
        raw = match.group(1).strip().replace("\\", "/")
        normalized = posixpath.normpath(raw)
        if raw.startswith(("/", "//")) or re.match(r"^[A-Za-z]:/", raw) or normalized == ".." or normalized.startswith("../"):
            diagnostics.append(_diag("new-resource", f"unsafe resource path {raw}", match.start()))
        elif normalized not in known:
            diagnostics.append(_diag("new-resource", f"resource {raw} is not owned by the artefact", match.start()))
    return diagnostics


def _option_diagnostics(source):
    diagnostics = []
    for match in _ENV_OPEN.finditer(source):
        options = match.group(2)
        if options is None:
            continue
        for item in options.split(","):
            key, _, value = item.partition("=")
            key = key.strip()
            value = value.strip()
            if key not in ENUMITEM_OPTION_KEYS or not value:
                diagnostics.append(_diag("unknown-command", f"invalid enumitem option {item.strip()}", match.start()))
            elif key == "start" and not value.isdigit():
                diagnostics.append(_diag("unknown-command", f"invalid enumitem start {value}", match.start()))
            elif key == "label" and not re.fullmatch(
                r"(?:\\(?:arabic|alph|Alph|roman|Roman)(?:\*|\{[A-Za-z]+\})?|"
                r"\\(?:textbf|emph|textit|texttt|textsc|underline|sout)\{[^{}]*\}|"
                r"[^\\{}\s,])+",
                value,
            ):
                diagnostics.append(_diag("unknown-command", f"invalid enumitem label {value}", match.start()))
    for match in re.finditer(r"\\todo(?:\[([^]]*)\])?", source):
        options = match.group(1)
        if options is None:
            continue
        for item in options.split(","):
            key, _, value = item.partition("=")
            key = key.strip()
            if key not in TODO_OPTION_KEYS or (key == "color" and not value.strip()):
                diagnostics.append(_diag("unknown-command", f"invalid todo option {item.strip()}", match.start()))
    return diagnostics


def _list_depth_diagnostics(source):
    diagnostics, depth = [], 0
    for match in _BEGIN_END.finditer(source):
        name = match.group(2)
        if name not in {"itemize", "enumerate", "description"}:
            continue
        if match.group(1) == "begin":
            depth += 1
            if depth > MAX_LIST_DEPTH:
                diagnostics.append(_diag("invalid-nesting", f"list depth exceeds {MAX_LIST_DEPTH}", match.start()))
        else:
            depth = max(0, depth - 1)
    return diagnostics


def _mask_generated_envelope(source):
    """Hide the converter's exact Unicode highlight shim from grammar scans."""
    return _GENERATED_UNICODE_HIGHLIGHT.sub(lambda match: " " * len(match.group()), source)


def validate_shadow(source: str, fragment_kind: str = "document", known_resources=None):
    """Validate a complete shadow or a declared V1 fragment.

    The result is stable, typed diagnostics; callers decide whether an error
    is fatal. A missing resource inventory means paths are syntax-checked but
    not ownership-checked, which is useful for standalone grammar fixtures.
    """
    diagnostics = []
    if fragment_kind not in AI_SHADOW_PROFILE_V1.fragment_kinds:
        diagnostics.append(_diag("invalid-fragment-kind", f"unknown fragment kind {fragment_kind}", 0))
        return tuple(diagnostics)
    if fragment_kind == "document":
        if not _CLASS.search(source):
            diagnostics.append(_diag("invalid-fragment-kind", "document fragment lacks documentclass", 0))
        begin = re.search(r"\\begin\{document\}", source)
        end = re.search(r"\\end\{document\}", source)
        if begin is None or end is None or (begin and end and begin.end() > end.start()):
            diagnostics.append(_diag("broken-environment", "document fragment lacks a valid document envelope", 0))
    packages = {package for package, _ in _package_names(source)}
    for package, index in _package_names(source):
        if package not in PACKAGE_WHITELIST:
            diagnostics.append(_diag("unapproved-package", f"package {package} is not in V1", index))
    scan_source = _mask_generated_envelope(source)
    for pattern, code in ((_DEFINITIONS, "macro-definition"), (_CUSTOM_DEFINITIONS, "custom-environment")):
        diagnostics.extend(_diag(code, f"{pattern.pattern} is outside V1", match.start()) for match in pattern.finditer(scan_source))
    diagnostics.extend(_diag("forbidden-word-carrier", "Word-specific carrier is forbidden", match.start()) for match in _FORBIDDEN.finditer(source))
    diagnostics.extend(_environment_diagnostics(source))
    diagnostics.extend(_environment_package_diagnostics(source, packages, fragment_kind))
    diagnostics.extend(_resource_diagnostics(source, known_resources))
    diagnostics.extend(_option_diagnostics(source))
    diagnostics.extend(_list_depth_diagnostics(source))
    ranges = _ranges(scan_source)
    if fragment_kind == "inline" and ("\\begin{" in scan_source or "\\end{" in scan_source or re.search(r"\\(?:section|subsection|subsubsection|item|newpage)\b", scan_source)):
        diagnostics.append(_diag("invalid-nesting", "block production in inline fragment", 0))
    if fragment_kind == "math" and not ranges:
        diagnostics.append(_diag("invalid-nesting", "math fragment contains no math region", 0))
    for match in _COMMAND.finditer(scan_source):
        name = match.group(1)
        if name in _ALLOWED_SINGLE or name in {"begin", "end"}:
            continue
        math_body = _inside(match.start(), ranges)
        if math_body is not None:
            continue
        if name in {"newcommand", "renewcommand", "providecommand", "def", "gdef", "edef", "let"}:
            continue
        if name in {"newenvironment", "renewenvironment"}:
            continue
        if name not in _ALLOWED_COMMANDS:
            diagnostics.append(_diag("unknown-command", f"unknown shadow command \\{name}", match.start()))
        required = AI_SHADOW_PROFILE_V1.required_package(name)
        if (
            required is not None
            and fragment_kind == "document"
            and required not in packages
        ):
            diagnostics.append(_diag(
                "unapproved-package",
                f"command \\{name} requires package {required}",
                match.start(),
            ))
    from ..math import latex2omml
    for start, _, body in ranges:
        try:
            # Word emits a final matrix/array row separator before the
            # closing delimiter.  It is structural punctuation, not a
            # second empty row, and the native serializer preserves it.
            math_body = re.sub(r"(?:\\\\\s*)+$", "", body)
            latex2omml.parse(math_body)
        except Exception as exc:
            # A small set of Word equations carries a lone continuation
            # slash after the closing delimiter.  It is preserved in the
            # shadow but protected from targeting; validate the meaningful
            # expression without that non-semantic terminal marker.
            if "lone backslash at end of input" in str(exc) and body.rstrip().endswith("\\"):
                try:
                    latex2omml.parse(body.rstrip()[:-1].rstrip())
                    continue
                except Exception:
                    pass
            diagnostics.append(_diag("unknown-math-command", str(exc), start))
    return tuple(diagnostics)


def validate_fragment(source: str, fragment_kind: str, known_resources=None):
    """Alias with the fragment-first call shape used by adapters."""
    return validate_shadow(source, fragment_kind, known_resources)


__all__ = ["validate_fragment", "validate_shadow"]
