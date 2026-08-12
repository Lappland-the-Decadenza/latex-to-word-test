"""Session commands for the authoritative-shadow editing surface."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..docx.package import validate_docx_package
from ..docx.read import docx_to_latex_with_blocks
from ..workspace.block_diff import diff_blocks
from ..workspace.block_package import PackageConflict, assemble_docx
from ..workspace.block_schema import BlockMap, BlockSession, digest_bytes, read_json, write_json
from ..workspace.create import (
    create_workspace, document_workspace_path, ensure_workspace, open_workspace,
)
from ..workspace.diagnostics import append_diagnostics, append_event
from ..workspace.shadow_blocks import ShadowMetadataError, read_shadow_blocks
from ..latex.validate import validate_shadow
from .editdir import EditDir, collect, create_edit_dir
from .publication import publish_candidate


class SessionError(ValueError):
    """A turn cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class CheckResult:
    valid: bool
    diagnostics: tuple[dict, ...]

    def to_json_obj(self):
        return {"valid": self.valid, "diagnostics": list(self.diagnostics)}


def _check_service(path):
    value = Path(path).resolve()
    root = value if value.is_dir() else value.parent
    for candidate in (root, *root.parents):
        service = candidate / ".service"
        if service.is_dir():
            return service
    return None


def _finish_check(path, diagnostics):
    service = _check_service(path)
    if service is not None:
        for item in diagnostics:
            append_event(
                service, item["severity"],
                f'{item["code"]} line={item["line"]} column={item["column"]}: {item["message"]}',
                event="check",
            )
    return CheckResult(
        not any(item.get("severity") == "error" for item in diagnostics),
        tuple(diagnostics),
    )


def _location(source, index):
    index = max(0, min(index or 0, len(source)))
    return source.count("\n", 0, index) + 1, index - source.rfind("\n", 0, index)


def workspace_check(path, *, known_resources=None):
    try:
        source = Path(path).read_text(encoding="utf-8")
        blocks = read_shadow_blocks(source)
    except (OSError, UnicodeError) as exc:
        raise SessionError(f"working-copy-missing: {exc}") from exc
    except ShadowMetadataError as exc:
        diagnostics = ({"code": "shadow-metadata", "message": str(exc),
                        "line": 1, "column": 1, "severity": "error"},)
        return _finish_check(path, diagnostics)
    diagnostics = []
    for diagnostic in validate_shadow(source, known_resources=known_resources):
        index = diagnostic.source.index if diagnostic.source is not None else 0
        line, column = _location(source, index)
        diagnostics.append({
            "code": diagnostic.code.value,
            "message": diagnostic.message,
            "line": line,
            "column": column,
            "severity": diagnostic.severity.value,
        })
    for block in blocks:
        for warning in block.warnings:
            line, column = _location(source, block.start)
            diagnostics.append({"code": warning.code, "message": warning.message,
                                "line": line, "column": column, "severity": "warning"})
    return _finish_check(path, diagnostics)


def _state_path(workspace):
    root = Path(workspace).resolve()
    service = root / ".service"
    return (service if service.is_dir() else root) / "active-edit.json"


def turn_start(workspace):
    state = open_workspace(workspace)
    state_path = _state_path(state.path)
    if state_path.exists():
        raise SessionError("turn-already-active")
    before = state.service_path / "shadow.before.tex"
    shutil.copyfile(state.canonical_shadow_path, before)
    surface = create_edit_dir(
        state.canonical_shadow_path.read_text(encoding="utf-8"),
        root=state.path,
        reuse=True,
    )
    state_path.write_text(json.dumps({
        "edit_dir": str(surface.path), "original_sha256": surface.original_sha256,
        "before_shadow": str(before),
    }, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return surface


def _active(workspace):
    state = open_workspace(workspace)
    try:
        data = json.loads(_state_path(state.path).read_text(encoding="utf-8"))
        return state, EditDir(Path(data["edit_dir"]), data["original_sha256"])
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise SessionError("no-active-turn") from exc


def workspace_diff(workspace):
    state, surface = _active(workspace)
    result = collect(surface)
    check = workspace_check(surface.path / "shadow.tex")
    if not check.valid:
        first = next(item for item in check.diagnostics if item["severity"] == "error")
        raise SessionError(
            f"shadow-invalid line={first['line']} column={first['column']}: {first['message']}"
        )
    if not result.changed:
        return result, None
    try:
        edit = diff_blocks(
            state.block_map,
            (state.service_path / "shadow.before.tex").read_text(encoding="utf-8"),
            result.shadow_text,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise SessionError(f"shadow-invalid line=1 column=1: {exc}") from exc
    return result, edit


def _resources(state, edit_result):
    values = {name: path for name, path in edit_result.resources}
    service_figures = state.service_path / "shadow.figures"
    if service_figures.is_dir():
        for path in service_figures.rglob("*"):
            if path.is_file():
                values[f"shadow.figures/{path.relative_to(service_figures).as_posix()}"] = path
    return values


def _copy_candidate(source, output):
    output = Path(output).resolve()
    temporary = output.parent / f".{output.name}.copy-{uuid.uuid4()}"
    try:
        shutil.copyfile(source, temporary)
        if validate_docx_package(temporary):
            raise SessionError("candidate package is invalid")
        temporary.replace(output)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def _verify_candidate(path):
    if validate_docx_package(path):
        raise SessionError("candidate package validation failed")
    service = Path(path).resolve().parent
    temporary_root = service / ".tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="candidate-check-", dir=temporary_root) as directory:
        try:
            result = docx_to_latex_with_blocks(str(path), str(Path(directory) / "candidate.tex"))
        except Exception as exc:
            raise SessionError("candidate reverse projection failed") from exc
    return tuple(result.warnings)


def _advance_generation(state, candidate):
    """Make a verified candidate the new current document version."""

    staging_root = state.path / f".generation-{uuid.uuid4()}"
    staging_root.mkdir(parents=False)
    next_path = staging_root / "workspace"
    try:
        next_state = create_workspace(
            candidate, next_path, original_source=state.original_path
        )
        map_path = next_state.service_path / "shadow.map.json"
        map_value = BlockMap.from_json(read_json(map_path))
        map_value = BlockMap(
            map_value.source_docx_sha256, state.block_map.generation + 1,
            map_value.records, map_value.nested_records,
        )
        write_json(map_path, map_value.to_json())
        session_path = next_state.service_path / "session.json"
        session_value = BlockSession(
            map_value.source_docx_sha256,
            digest_bytes(next_state.canonical_shadow_path.read_bytes()),
            digest_bytes(map_path.read_bytes()), map_value.generation,
        )
        write_json(session_path, session_value.to_json())
        history = state.service_path / "history"
        if history.is_dir():
            shutil.copytree(history, next_state.service_path / "history")
        if Path(candidate).resolve().parent == state.service_path:
            shutil.copyfile(candidate, next_state.service_path / "candidate.docx")
        old_service = state.path / f".service.old-{uuid.uuid4()}"
        old_shadow = state.path / f".shadow.old-{uuid.uuid4()}.tex"
        state.service_path.rename(old_service)
        state.shadow_path.rename(old_shadow)
        try:
            next_state.service_path.rename(state.path / ".service")
            next_state.shadow_path.rename(state.path / "shadow.tex")
        except Exception:
            if (state.path / ".service").exists():
                shutil.rmtree(state.path / ".service", ignore_errors=True)
            if (state.path / "shadow.tex").exists():
                (state.path / "shadow.tex").unlink()
            old_service.rename(state.path / ".service")
            old_shadow.rename(state.path / "shadow.tex")
            raise
        next_state = open_workspace(state.path)
        shutil.rmtree(old_service, ignore_errors=True)
        return next_state
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root, ignore_errors=True)


def workspace_apply(workspace, output, *, current=None):
    state, _surface = _active(workspace)
    if current is not None:
        current_path = Path(current).resolve()
        if not current_path.is_file() or hashlib.sha256(current_path.read_bytes()).hexdigest() != state.session.source_docx_sha256:
            raise SessionError("live-document-changed: choices=apply_ai_over_live,keep_live_discard_ai,request_merge")
    edit_result, edit = workspace_diff(state.path)
    if edit is None:
        _copy_candidate(state.current_path, output)
        warnings = ()
        action_count = 0
        published_output = Path(output).resolve()
    else:
        try:
            candidate_in_service = Path(output).resolve().parent == state.service_path
            package = assemble_docx(
                state.current_path, edit, state.block_map, output,
                resources=_resources(state, edit_result),
            )
            warnings = package.warnings + _verify_candidate(package.path)
            action_count = len(edit.actions)
            next_state = _advance_generation(state, package.path)
            published_output = (
                next_state.service_path / "candidate.docx"
                if candidate_in_service
                else Path(package.path).resolve()
            )
        except (PackageConflict, OSError, ValueError) as exc:
            raise SessionError(f"publication-failed: {exc}") from exc
    _state_path(state.path).unlink(missing_ok=True)
    (state.service_path / "shadow.before.tex").unlink(missing_ok=True)
    return {"output": str(published_output), "changed_blocks": action_count,
            "answer": edit_result.answer_text, "warnings": list(warnings)}


def edit_start(source, *, reporter=None):
    state = ensure_workspace(source, reporter=reporter)
    surface = turn_start(state.path)
    return {"workspace": str(state.path), "shadow": str(surface.path / "shadow.tex")}


def edit_apply(source, *, reporter=None):
    workspace = document_workspace_path(source)
    state = open_workspace(workspace)
    candidate = state.service_path / "candidate.docx"
    if not _state_path(state.path).exists():
        source_hash = hashlib.sha256(Path(source).resolve().read_bytes()).hexdigest()
        if not candidate.is_file() or source_hash == state.session.source_docx_sha256:
            raise SessionError("no-active-turn")
        result = {"output": str(candidate), "changed_blocks": 0,
                  "answer": "", "warnings": []}
    else:
        result = workspace_apply(state.path, candidate)
    history_root = Path(result["output"]).resolve().parent / "history"
    publication = publish_candidate(source, result["output"], history_root=history_root)
    pending = Path(result["output"]).resolve().parent / "pending-publication.json"
    if publication.code == "word-live-update-not-implemented":
        pending.write_text(json.dumps({
            "source": str(Path(source).resolve()),
            "candidate": result["output"],
        }, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    else:
        pending.unlink(missing_ok=True)
    result["publication"] = {
        "code": publication.code, "source": publication.source,
        "candidate": publication.candidate, "backup": publication.backup,
        "history": publication.history,
    }
    append_diagnostics(state.service_path, "edit-apply", result["warnings"])
    append_event(state.service_path, "info", publication.code, event="publication")
    return result


__all__ = [
    "CheckResult", "SessionError", "edit_apply", "edit_start",
    "turn_start", "workspace_apply", "workspace_check", "workspace_diff",
]
