"""Stable, adapter-independent node identifiers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NodeId:
    """Opaque identifier stable within one conversion artefact."""

    value: str

    def __post_init__(self):
        if not isinstance(self.value, str) or not self.value or self.value != self.value.strip():
            raise ValueError("NodeId must contain a non-empty opaque value")

    @classmethod
    def allocate(cls, ordinal: int) -> "NodeId":
        if ordinal < 0:
            raise ValueError("NodeId ordinal must be non-negative")
        return cls(f"n{ordinal:08d}")


__all__ = ["NodeId"]
