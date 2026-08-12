"""Adapter-neutral request and result contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from .diagnostics import Diagnostic
from .identity import NodeId
from .model import Document


class SidecarHandle(Protocol):
    """Opaque sidecar capability kept outside the semantic document model."""


@dataclass(frozen=True, slots=True)
class ImportResult:
    document: Document
    diagnostics: tuple[Diagnostic, ...] = ()
    sidecar: SidecarHandle | None = None


@dataclass(frozen=True, slots=True)
class ExportRequest:
    document: Document
    sidecar: SidecarHandle | None = None
    reference_docx: Path | None = None


@dataclass(frozen=True, slots=True)
class Attachment:
    payload_id: str
    position: Literal["before", "after", "inside"]
    owner_id: NodeId
    ordinal: int
    owner_semantic_hash: str


__all__ = ["Attachment", "ExportRequest", "ImportResult", "SidecarHandle"]
