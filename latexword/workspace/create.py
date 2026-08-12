"""Transactional creation of an authoritative-shadow workspace."""

from __future__ import annotations

import os
import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..docx.package import validate_docx_package
from .block_schema import BlockMap, BlockSession, read_json
from .import_docx import WorkspaceError, import_docx


@dataclass(frozen=True, slots=True)
class Workspace:
    path: Path
    session: BlockSession
    block_map: BlockMap

    @property
    def service_path(self):
        """Return the private service directory for this document workspace."""

        service = self.path / ".service"
        return service if service.is_dir() else self.path

    @property
    def shadow_path(self):
        """Return the agent-facing shadow, kept at the workspace root."""

        shadow = self.path / "shadow.tex"
        return shadow if shadow.is_file() else self.service_path / "shadow.tex"

    @property
    def canonical_shadow_path(self):
        """Return the immutable shadow used for workspace integrity checks."""

        shadow = self.service_path / "shadow.tex"
        return shadow if shadow.is_file() else self.shadow_path

    @property
    def current_path(self):
        """Return the latest document version represented by the shadow."""

        return self.service_path / "current.docx"

    @property
    def original_path(self):
        """Return the first document imported into this managed workspace."""

        return self.service_path / "original.docx"

    @property
    def shadow_map(self):
        """Compatibility name for callers that only need the persisted map."""
        return self.block_map


def create_workspace(
    source_docx: os.PathLike | str,
    destination: os.PathLike | str,
    *,
    original_source: os.PathLike | str | None = None,
    reporter=None,
):
    source = Path(source_docx).resolve()
    target = Path(destination).resolve()
    if not source.is_file():
        raise WorkspaceError(f"source DOCX does not exist: {source}")
    if target.exists():
        raise WorkspaceError("workspace destination already exists")
    with (reporter.stage("package-validate") if reporter else _null()):
        if validate_docx_package(source):
            raise WorkspaceError("source DOCX package is invalid")
    target.mkdir(parents=False)
    service = target / ".service"
    staging = target / f".service.staging-{uuid.uuid4()}"
    staging.mkdir(parents=False)
    try:
        session, block_map = import_docx(
            staging, source, original_source=original_source, reporter=reporter
        )
        shutil.copyfile(staging / "shadow.tex", target / "shadow.tex")
        _write_manifest(staging, session.source_docx_sha256)
        staging.rename(service)
        with (reporter.stage("reopen") if reporter else _null()):
            state = open_workspace(target)
        return state
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if service.exists():
            shutil.rmtree(service, ignore_errors=True)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        raise


class _null:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def open_workspace(path):
    from .open import open_workspace as reopen
    return reopen(path)


MANAGED_SCHEMA = "latexword-managed-document/v1"


def document_workspace_path(source_docx: os.PathLike | str):
    """Choose the first default per-document folder not owned by another item."""

    source = Path(source_docx).resolve()
    base = source.with_suffix(".latexword")
    candidate = base
    number = 2
    while candidate.exists() and not _is_managed(candidate):
        candidate = base.with_name(f"{base.name}-{number}")
        number += 1
    return candidate


def ensure_workspace(source_docx: os.PathLike | str, destination=None, *, reporter=None):
    """Open or safely rebuild the managed workspace for a source DOCX."""

    source = Path(source_docx).resolve()
    if not source.is_file():
        raise WorkspaceError(f"source DOCX does not exist: {source}")
    target = (Path(destination).resolve() if destination is not None
              else document_workspace_path(source))
    source_hash = _hash_file(source)
    if not target.exists():
        return create_workspace(source, target, reporter=reporter)
    if not _is_managed(target):
        if destination is not None:
            raise WorkspaceError("workspace destination is not a LaTeXWord folder")
        target = document_workspace_path(source)
        return create_workspace(source, target, reporter=reporter)
    _migrate_legacy_workspace(target)
    try:
        state = open_workspace(target)
        if state.session.source_docx_sha256 == source_hash:
            return state
    except (OSError, ValueError, KeyError, TypeError, WorkspaceError):
        pass
    if (target / ".service" / "pending-publication.json").is_file():
        raise WorkspaceError("verified candidate is waiting for the source document to close")
    if (target / ".service" / "active-edit.json").exists():
        raise WorkspaceError("workspace has an active edit and cannot be refreshed")
    return _rebuild_workspace(source, target, source_hash, reporter=reporter)


def _hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_managed(path):
    try:
        value = json.loads((Path(path) / ".service" / "manifest.json").read_text(encoding="utf-8"))
        return value.get("schema") == MANAGED_SCHEMA
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
        return False


def _migrate_legacy_workspace(path):
    """Upgrade pre-current workspaces without losing their first source."""

    service = Path(path) / ".service"
    legacy = service / "base.docx"
    current = service / "current.docx"
    original = service / "original.docx"
    if not current.is_file() and legacy.is_file():
        legacy.rename(current)
    if original.is_file() or not current.is_file():
        return
    backups = sorted(service.glob("history/*/before.docx"))
    shutil.copyfile(backups[0] if backups else current, original)


def _write_manifest(service, source_hash):
    (Path(service) / "manifest.json").write_text(json.dumps({
        "schema": MANAGED_SCHEMA,
        "source_sha256": source_hash,
    }, ensure_ascii=False, sort_keys=True), encoding="utf-8", newline="\n")


def _rebuild_workspace(source, target, source_hash, *, reporter=None):
    staging = target / f".service.staging-{uuid.uuid4()}"
    staged_shadow = target / f".shadow.staging-{uuid.uuid4()}.tex"
    old_service = target / f".service.old-{uuid.uuid4()}"
    old_shadow = target / f".shadow.old-{uuid.uuid4()}.tex"
    staging.mkdir(parents=False)
    try:
        previous_service = target / ".service"
        original = previous_service / "original.docx"
        import_docx(
            staging, source,
            original_source=original if original.is_file() else source,
            reporter=reporter,
        )
        _write_manifest(staging, source_hash)
        shutil.copyfile(staging / "shadow.tex", staged_shadow)
        previous_service.rename(old_service)
        (target / "shadow.tex").rename(old_shadow)
        staging.rename(target / ".service")
        staged_shadow.rename(target / "shadow.tex")
        state = open_workspace(target)
    except Exception:
        if (target / ".service").exists() and not old_service.exists():
            (target / ".service").rename(old_service)
        if (target / "shadow.tex").exists() and not old_shadow.exists():
            (target / "shadow.tex").rename(old_shadow)
        if old_service.exists():
            old_service.rename(target / ".service")
        if old_shadow.exists():
            old_shadow.rename(target / "shadow.tex")
        raise
    finally:
        for path in (staging, staged_shadow):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.exists():
                path.unlink()
    shutil.rmtree(old_service, ignore_errors=True)
    if old_shadow.exists():
        old_shadow.unlink()
    return state


__all__ = [
    "MANAGED_SCHEMA", "Workspace", "WorkspaceError", "create_workspace",
    "document_workspace_path", "ensure_workspace", "open_workspace",
]
