"""Closed-document publication, recoverable history and Word live detection."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..docx.package import validate_docx_package
from ..docx.read import docx_to_latex_with_blocks
from ..workspace.diagnostics import append_diagnostics


@dataclass(frozen=True, slots=True)
class PublicationResult:
    code: str
    source: str
    candidate: str
    backup: str | None = None
    history: str | None = None


def word_document_is_open(path):
    """Ask desktop Word for a matching open document without touching it."""

    if os.name != "nt":
        return False
    try:
        import win32com.client
        application = win32com.client.GetActiveObject("Word.Application")
        target = str(Path(path).resolve()).lower()
        return any(str(document.FullName).lower() == target for document in application.Documents)
    except (ImportError, OSError, AttributeError, RuntimeError):
        return False


def _verify(path, *, temporary_root):
    if validate_docx_package(path):
        raise ValueError("candidate package validation failed")
    temporary_root = Path(temporary_root).resolve()
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="publication-verify-", dir=temporary_root) as directory:
        return docx_to_latex_with_blocks(
            str(path), str(Path(directory) / "verify.tex")
        )


def publish_candidate(source, candidate, *, history_root=None):
    source = Path(source).resolve()
    candidate = Path(candidate).resolve()
    service_tmp = candidate.parent / ".tmp"
    verification = _verify(candidate, temporary_root=service_tmp)
    append_diagnostics(candidate.parent, "candidate-verify", verification.warnings)
    if word_document_is_open(source):
        return PublicationResult("word-live-update-not-implemented", str(source), str(candidate))
    history = Path(history_root or source.parent / ".latexword-history").resolve()
    # Path + string precedence is intentionally avoided below for Windows paths.
    history.mkdir(parents=True, exist_ok=True)
    entry = history / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + str(uuid.uuid4()))
    entry.mkdir(parents=True, exist_ok=False)
    backup = entry / "before.docx"
    shutil.copyfile(source, backup)
    (entry / "metadata.json").write_text(json.dumps({
        "source": str(source), "candidate": str(candidate), "backup": str(backup),
    }, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    temporary_root = history.parent / ".tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    temporary = temporary_root / f"{source.name}.publish-{uuid.uuid4()}"
    try:
        shutil.copyfile(candidate, temporary)
        os.replace(temporary, source)
        verification = _verify(source, temporary_root=service_tmp)
        append_diagnostics(candidate.parent, "published-verify", verification.warnings)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        shutil.copyfile(backup, source)
        raise
    return PublicationResult("published", str(source), str(candidate), str(backup), str(entry))


def undo_publication(source, history_entry):
    source = Path(source).resolve()
    entry = Path(history_entry).resolve()
    backup = entry / "before.docx"
    if not backup.is_file():
        raise ValueError("history backup is missing")
    temporary_root = entry.parent.parent / ".tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    temporary = temporary_root / f"{source.name}.undo-{uuid.uuid4()}"
    shutil.copyfile(backup, temporary)
    try:
        verification = _verify(temporary, temporary_root=temporary_root)
        append_diagnostics(temporary_root.parent, "undo-verify", verification.warnings)
        os.replace(temporary, source)
        verification = _verify(source, temporary_root=temporary_root)
        append_diagnostics(temporary_root.parent, "undo-published-verify", verification.warnings)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    return str(source)


__all__ = ["PublicationResult", "publish_candidate", "undo_publication", "word_document_is_open"]
