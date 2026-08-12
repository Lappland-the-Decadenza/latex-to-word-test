"""The closed grammar contract for AI-authored shadow LaTeX.

This module declares vocabulary and package ownership only.  It deliberately
does not parse LaTeX or import an adapter; those responsibilities belong to
the later native-LaTeX split.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping


PROFILE_NAME: Final = "AI_SHADOW_PROFILE_V1"

PACKAGE_WHITELIST: Final[frozenset[str]] = frozenset(
    {
        "amsmath",
        "amssymb",
        "amsfonts",
        "mathtools",
        "graphicx",
        "xcolor",
        "soul",
        "ulem",
        "enumitem",
        "booktabs",
        "multirow",
        "hyperref",
        "todonotes",
        "xfrac",
        "multicol",
        "ragged2e",
        "endnotes",
        "fontspec",
    }
)

ENVELOPE: Final[tuple[str, ...]] = (
    "documentclass",
    "generated-preamble",
    "title",
    "author",
    "date",
    "maketitle",
    "begin{document}",
    "end{document}",
)

BLOCK_VOCABULARY: Final[frozenset[str]] = frozenset(
    {
        "paragraph",
        "section",
        "subsection",
        "subsubsection",
        "itemize",
        "enumerate",
        "description",
        "quote",
        "quotation",
        "center",
        "flushleft",
        "flushright",
        "justify",
        "table",
        "tabular",
        "toprule",
        "midrule",
        "bottomrule",
        "multicolumn",
        "multirow",
        "figure",
        "includegraphics",
        "caption",
        "label",
        "verbatim",
        "newpage",
        "equation",
        "equation*",
        "align",
        "align*",
        "gather",
        "gather*",
        "multicols",
        "multicols*",
    }
)

INLINE_VOCABULARY: Final[frozenset[str]] = frozenset(
    {
        "unicode-prose",
        "textbf",
        "emph",
        "textit",
        "texttt",
        "textsc",
        "underline",
        "sout",
        "textsuperscript",
        "textsubscript",
        "textcolor",
        "colorbox",
        "hl",
        "href",
        "url",
        "footnote",
        "label",
        "ref",
        "pageref",
        "cite",
        "todo",
        "inline-math",
        "hard-line-break",
        "soft-line-break",
    }
)

MATH_EXTENSIONS: Final[frozenset[str]] = frozenset({"genfrac", "sfrac"})
ALLOWED_ENVIRONMENTS: Final[frozenset[str]] = frozenset(
    {
        "document", "itemize", "enumerate", "description", "quote",
        "quotation", "center", "flushleft", "flushright", "table",
        "tabular", "tabular*", "figure", "figure*", "verbatim",
        "equation", "equation*", "align", "align*", "gather", "gather*",
        "multicols", "multicols*", "justify",
    }
)
FORBIDDEN_MATH_CARRIERS: Final[frozenset[str]] = frozenset(
    {"linfrac", "skwfrac", "nobarfrac", "hlight"}
)

FRAGMENT_KINDS: Final[frozenset[str]] = frozenset(
    {"document", "block", "inline", "math", "resource-reference"}
)
MAX_LIST_DEPTH: Final[int] = 4
ENUMITEM_OPTION_KEYS: Final[frozenset[str]] = frozenset({"label", "start"})
TODO_OPTION_KEYS: Final[frozenset[str]] = frozenset({"inline", "color"})

ALLOWED_NESTING: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "document": frozenset({"block"}),
        "block": frozenset({"paragraph", "heading", "list", "quote", "table", "figure", "math", "verbatim"}),
        "list": frozenset({"list", "paragraph", "math"}),
        "table": frozenset({"table-cell", "paragraph", "math"}),
        "figure": frozenset({"resource-reference", "caption", "label"}),
        "inline": frozenset({"inline", "math"}),
    }
)

PACKAGE_REQUIREMENTS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "textcolor": "xcolor",
        "colorbox": "xcolor",
        "cellcolor": "xcolor",
        "hl": "soul",
        "sout": "ulem",
        "itemize": "enumitem",
        "enumerate": "enumitem",
        "description": "enumitem",
        "toprule": "booktabs",
        "midrule": "booktabs",
        "bottomrule": "booktabs",
        "multirow": "multirow",
        "equation": "amsmath",
        "align": "amsmath",
        "gather": "amsmath",
        "genfrac": "amsmath",
        "sfrac": "xfrac",
        "includegraphics": "graphicx",
        "href": "hyperref",
        "url": "hyperref",
        "todo": "todonotes",
        "endnote": "endnotes",
        "setmainfont": "fontspec",
        "setmonofont": "fontspec",
        "multicols": "multicol",
        "justify": "ragged2e",
    }
)

REJECTION_CODES: Final[frozenset[str]] = frozenset(
    {
        "unknown-command",
        "unapproved-package",
        "macro-definition",
        "custom-environment",
        "broken-environment",
        "invalid-fragment-kind",
        "invalid-nesting",
        "new-resource",
        "forbidden-word-carrier",
        "unknown-math-command",
    }
)

OUTSIDE_PROFILE: Final[frozenset[str]] = frozenset(
    {
        "input",
        "include",
        "subfile",
        "newcommand",
        "renewcommand",
        "newenvironment",
        "tikzpicture",
        "shell-escape",
        "bibliography-project",
        "opaque-payload",
        "ooxml",
        "word-id",
    }
)


@dataclass(frozen=True)
class ShadowProfile:
    """Immutable, machine-readable profile metadata consumed by adapters."""

    name: str
    packages: frozenset[str]
    envelope: tuple[str, ...]
    blocks: frozenset[str]
    inline: frozenset[str]
    math_extensions: frozenset[str]
    fragment_kinds: frozenset[str]
    allowed_nesting: Mapping[str, frozenset[str]]
    package_requirements: Mapping[str, str]
    rejection_codes: frozenset[str]

    def allows_package(self, package: str) -> bool:
        return package in self.packages

    def allows_block(self, production: str) -> bool:
        return production in self.blocks

    def allows_inline(self, production: str) -> bool:
        return production in self.inline

    def required_package(self, production: str) -> str | None:
        return self.package_requirements.get(production)

    def validate(self, source: str, fragment_kind: str = "document", known_resources=None):
        """Validate source against this exact profile declaration."""
        if self is not AI_SHADOW_PROFILE_V1:
            raise ValueError("only the published V1 validator is available")
        from .validate import validate_shadow
        return validate_shadow(source, fragment_kind, known_resources)


AI_SHADOW_PROFILE_V1: Final[ShadowProfile] = ShadowProfile(
    name=PROFILE_NAME,
    packages=PACKAGE_WHITELIST,
    envelope=ENVELOPE,
    blocks=BLOCK_VOCABULARY,
    inline=INLINE_VOCABULARY,
    math_extensions=MATH_EXTENSIONS,
    fragment_kinds=FRAGMENT_KINDS,
    allowed_nesting=ALLOWED_NESTING,
    package_requirements=PACKAGE_REQUIREMENTS,
    rejection_codes=REJECTION_CODES,
)


__all__ = [
    "AI_SHADOW_PROFILE_V1",
    "ALLOWED_NESTING",
    "ALLOWED_ENVIRONMENTS",
    "BLOCK_VOCABULARY",
    "ENVELOPE",
    "FORBIDDEN_MATH_CARRIERS",
    "FRAGMENT_KINDS",
    "ENUMITEM_OPTION_KEYS",
    "INLINE_VOCABULARY",
    "MAX_LIST_DEPTH",
    "MATH_EXTENSIONS",
    "OUTSIDE_PROFILE",
    "PACKAGE_REQUIREMENTS",
    "PACKAGE_WHITELIST",
    "PROFILE_NAME",
    "REJECTION_CODES",
    "ShadowProfile",
    "TODO_OPTION_KEYS",
]
