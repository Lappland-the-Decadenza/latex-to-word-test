"""Native canonical LaTeX adapters and the AI shadow profile."""

from .parse import parse, parse_with_diagnostics
from .preamble import build_preamble, required_packages, serialize_document
from .serialize import NodeSpan, SerializedDocument, serialize, serialize_with_spans
from .profile import AI_SHADOW_PROFILE_V1
from .validate import validate_fragment, validate_shadow

__all__ = [
    "AI_SHADOW_PROFILE_V1", "NodeSpan", "SerializedDocument", "build_preamble",
    "parse", "parse_with_diagnostics", "required_packages", "serialize",
    "serialize_document", "serialize_with_spans",
    "validate_fragment", "validate_shadow",
]
