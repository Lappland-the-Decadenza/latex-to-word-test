"""Stable semantic projection for native adapter equivalence checks."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from hashlib import sha256


_IGNORED_FIELDS = {"context", "data", "relationship"}


def semantic_key(value):
    """Return a JSON-like immutable key without adapter or source metadata."""
    if isinstance(value, (tuple, list)):
        return tuple(semantic_key(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((key, semantic_key(item)) for key, item in value.items()))
    if is_dataclass(value):
        return (
            type(value).__name__,
            tuple(
                (field.name, semantic_key(getattr(value, field.name)))
                for field in fields(value)
                if field.name not in _IGNORED_FIELDS
            ),
        )
    if isinstance(value, bytes):
        return ("bytes", sha256(value).hexdigest())
    if isinstance(value, Enum):
        return value.value
    return value


def semantic_equal(left, right):
    """Compare two model values while ignoring source locations and payload bytes."""
    return semantic_key(left) == semantic_key(right)


__all__ = ["semantic_equal", "semantic_key"]
