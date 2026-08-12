"""Reopen and validate an authoritative-shadow workspace."""

from __future__ import annotations

from pathlib import Path

from ..docx.package import validate_docx_package
from .block_schema import BlockMap, BlockSession, digest_bytes, read_json
from .import_docx import WorkspaceError
from .shadow_blocks import read_shadow_blocks


def open_workspace(path):
    root = Path(path).resolve()
    public_root = root.parent if root.name == ".service" else root
    service = public_root / ".service"
    if not service.is_dir():
        service = public_root
    from .create import _migrate_legacy_workspace
    _migrate_legacy_workspace(public_root)
    shadow_path = service / "shadow.tex"
    if not shadow_path.is_file():
        shadow_path = public_root / "shadow.tex"
    try:
        session = BlockSession.from_json(read_json(service / "session.json"))
        block_map = BlockMap.from_json(read_json(service / "shadow.map.json"))
        shadow_bytes = shadow_path.read_bytes()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise WorkspaceError("invalid authoritative workspace metadata") from exc
    if session.shadow_sha256 != digest_bytes(shadow_bytes):
        raise WorkspaceError("shadow.tex hash mismatch")
    map_bytes = (service / "shadow.map.json").read_bytes()
    if session.map_sha256 != digest_bytes(map_bytes):
        raise WorkspaceError("shadow.map.json hash mismatch")
    if session.source_docx_sha256 != block_map.source_docx_sha256:
        raise WorkspaceError("workspace source hash mismatch")
    current = service / "current.docx"
    original = service / "original.docx"
    if digest_bytes(current.read_bytes()) != session.source_docx_sha256:
        raise WorkspaceError("current.docx hash mismatch")
    if validate_docx_package(current):
        raise WorkspaceError("workspace current.docx package is invalid")
    if not original.is_file() or validate_docx_package(original):
        raise WorkspaceError("workspace original.docx package is invalid")
    blocks = read_shadow_blocks(shadow_bytes.decode("utf-8"))
    labels = tuple(item.label for item in blocks if item.label is not None)
    expected = tuple(item.label for item in block_map.records)
    if labels != expected:
        raise WorkspaceError("shadow and block map labels differ")
    from .create import Workspace
    return Workspace(public_root, session, block_map)


__all__ = ["open_workspace"]
