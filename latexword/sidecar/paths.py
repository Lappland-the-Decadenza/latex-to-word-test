"""Validated OPC and sidecar path handling."""

from __future__ import annotations

import posixpath
import re
from urllib.parse import unquote, urlsplit


_SAFE_REL = re.compile(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$")


def rels_name(part_name):
    folder, base = posixpath.split(part_name)
    return posixpath.join(folder, "_rels", base + ".rels")


def resolve_target(source, target):
    parsed = urlsplit(target or "")
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        return None
    raw = unquote(parsed.path).replace("\\", "/")
    if not raw or raw.startswith("/"):
        return None
    candidate = posixpath.join(posixpath.dirname(source), raw)
    resolved = posixpath.normpath(candidate)
    if resolved in ("", ".", "..") or resolved.startswith("../"):
        return None
    return resolved


def validate_relative(value):
    if not isinstance(value, str) or not value or value.startswith(("/", "\\")):
        raise ValueError("invalid sidecar relative path")
    normal = value.replace("\\", "/")
    if not _SAFE_REL.fullmatch(normal) or any(part == ".." for part in normal.split("/")):
        raise ValueError("invalid sidecar relative path")
    return normal
