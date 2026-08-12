"""Typed diagnostics shared by document adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DiagnosticCode(str, Enum):
    UNKNOWN = "unknown"
    DEFERRED = "deferred"
    INVALID_INPUT = "invalid-input"
    UNSUPPORTED_OBJECT = "unsupported-object"
    UNKNOWN_COMMAND = "unknown-command"
    UNAPPROVED_PACKAGE = "unapproved-package"
    MACRO_DEFINITION = "macro-definition"
    CUSTOM_ENVIRONMENT = "custom-environment"
    BROKEN_ENVIRONMENT = "broken-environment"
    INVALID_FRAGMENT_KIND = "invalid-fragment-kind"
    INVALID_NESTING = "invalid-nesting"
    NEW_RESOURCE = "new-resource"
    FORBIDDEN_WORD_CARRIER = "forbidden-word-carrier"
    UNKNOWN_MATH_COMMAND = "unknown-math-command"


@dataclass(frozen=True, slots=True)
class SourceReference:
    part: str | None = None
    index: int | None = None


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: DiagnosticCode
    severity: Severity
    message: str
    source: SourceReference | None = None


__all__ = ["Diagnostic", "DiagnosticCode", "Severity", "SourceReference"]
