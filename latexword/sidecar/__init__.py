"""Detached Word-only state carried beside canonical LaTeX."""

from .model import (
    SidecarAttachment,
    SidecarContext,
    SidecarObject,
    SidecarPart,
    SidecarRelationship,
)
from .store import ObjectStore

__all__ = [
    "ObjectStore",
    "SidecarAttachment",
    "SidecarContext",
    "SidecarObject",
    "SidecarPart",
    "SidecarRelationship",
]
