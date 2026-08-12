"""Create and collect the managed editing surface."""

from __future__ import annotations

import hashlib
import os
import sys
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path


class EditDirError(ValueError):
    """The editing surface is missing or invalid."""


@dataclass(frozen=True, slots=True)
class EditDir:
    path: Path
    original_sha256: str


@dataclass(frozen=True, slots=True)
class EditResult:
    changed: bool
    shadow_text: str
    answer_text: str
    resources: tuple[tuple[str, Path], ...] = ()


_RESOURCE = re.compile(r"\\includegraphics(?:\[[^]]*\])?\s*\{([^{}]+)\}")
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff"}


def _launcher(directory: Path):
    root = Path(__file__).resolve().parents[2]
    script = root / "latexword_workspace.py"
    python = Path(sys.executable).resolve()
    if os.name == "nt":
        (directory / "check.sh").unlink(missing_ok=True)
        text = f'@echo off\r\n"{python}" "{script}" workspace-check shadow.tex\r\n'
        (directory / "check.cmd").write_text(text, encoding="utf-8", newline="")
    else:
        (directory / "check.cmd").unlink(missing_ok=True)
        text = f'#!/bin/sh\nexec "{python}" "{script}" workspace-check shadow.tex\n'
        target = directory / "check.sh"
        target.write_text(text, encoding="utf-8", newline="\n")
        target.chmod(0o700)


def create_edit_dir(shadow_text: str, *, root=None, reuse=False) -> EditDir:
    """Prepare the managed-folder root as the agent's editing surface."""

    if root is None:
        raise EditDirError("edit directory root is required")
    else:
        path = Path(root).resolve()
        try:
            path.mkdir(parents=True, exist_ok=reuse)
        except FileExistsError as exc:
            raise EditDirError("edit directory already exists") from exc
        except OSError as exc:
            raise EditDirError(f"edit directory unavailable: {exc}") from exc
    try:
        (path / "shadow.tex").write_text(shadow_text, encoding="utf-8", newline="\n")
        if reuse:
            (path / "ANSWER.md").unlink(missing_ok=True)
            (path / "TASK.md").unlink(missing_ok=True)
        _launcher(path)
    except Exception:
        if not reuse:
            for item in (path / "shadow.tex", path / "check.cmd", path / "check.sh"):
                item.unlink(missing_ok=True)
            path.rmdir()
        raise
    digest = hashlib.sha256(shadow_text.encode("utf-8")).hexdigest()
    return EditDir(path, digest)


def collect(edit_dir: EditDir) -> EditResult:
    """Read agent outputs and referenced, edit-directory-owned images only."""

    shadow = edit_dir.path / "shadow.tex"
    if not shadow.is_file():
        raise EditDirError("working-copy-missing")
    try:
        text = shadow.read_text(encoding="utf-8")
        answer_path = edit_dir.path / "ANSWER.md"
        answer = answer_path.read_text(encoding="utf-8") if answer_path.is_file() else ""
    except (OSError, UnicodeError) as exc:
        raise EditDirError("working-copy-missing") from exc
    resources = []
    root = edit_dir.path.resolve()
    for match in _RESOURCE.finditer(text):
        raw = match.group(1).strip().replace("\\", "/")
        name = posixpath.normpath(raw)
        if (raw.startswith(("/", "//")) or re.match(r"^[A-Za-z]:/", raw)
                or name == ".." or name.startswith("../")):
            raise EditDirError(f"unsafe-resource-path: {raw}")
        candidate = (root / Path(name)).resolve()
        if root not in candidate.parents:
            raise EditDirError(f"unsafe-resource-path: {raw}")
        if not candidate.is_file():
            # Images extracted from the immutable source are workspace-owned;
            # new resources must be supplied in the edit directory.
            if name.startswith("shadow.figures/"):
                continue
            raise EditDirError(f"missing-resource: {raw}")
        if candidate.suffix.lower() not in _IMAGE_SUFFIXES:
            raise EditDirError(f"unsupported-image-type: {name}")
        resources.append((name, candidate))
    changed = hashlib.sha256(text.encode("utf-8")).hexdigest() != edit_dir.original_sha256
    return EditResult(changed, text, answer, tuple(dict(resources).items()))


__all__ = ["EditDir", "EditDirError", "EditResult", "collect", "create_edit_dir"]
