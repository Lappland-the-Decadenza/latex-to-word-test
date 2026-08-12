"""Argument parsing and rendering for workspace commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .jsonout import failure, success
from .progress import Progress
from ..session.commands import (
    SessionError, edit_apply, edit_start, turn_start, workspace_apply,
    workspace_check, workspace_diff,
)
from ..session.editdir import EditDirError
from ..workspace.create import WorkspaceError, create_workspace
from ..workspace.create import document_workspace_path
from ..workspace.diagnostics import append_event


def _common(command):
    command.add_argument("--json", action="store_true")


def _parser():
    parser = argparse.ArgumentParser(prog="latexword-workspace")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--progress", choices=("none", "stage", "verbose"), default="stage")
    parser.add_argument("--debug", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("workspace-create")
    create.add_argument("source")
    create.add_argument("workspace")
    _common(create)
    start_edit = commands.add_parser("edit-start")
    start_edit.add_argument("source")
    _common(start_edit)
    apply_edit = commands.add_parser("edit-apply")
    apply_edit.add_argument("source")
    _common(apply_edit)
    check = commands.add_parser("workspace-check")
    check.add_argument("path", nargs="?", default="shadow.tex")
    _common(check)
    start = commands.add_parser("turn-start")
    start.add_argument("workspace")
    _common(start)
    diff = commands.add_parser("workspace-diff")
    diff.add_argument("workspace")
    _common(diff)
    apply = commands.add_parser("workspace-apply")
    apply.add_argument("workspace")
    apply.add_argument("--output", required=True)
    apply.add_argument("--current")
    _common(apply)
    return parser


def _render(args, value):
    if args.json:
        print(json.dumps(success(args.command, value), ensure_ascii=False, sort_keys=True))
    elif args.command == "workspace-create":
        print(value["workspace"])
    elif args.command == "edit-start":
        print(value["workspace"])
    elif args.command == "edit-apply":
        publication = value.get("publication", {})
        print(f"{publication.get('code', 'applied')}: {value.get('output', '')}")
    elif isinstance(value, dict):
        print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    else:
        print(value)


def _dispatch(args, progress):
    if args.command == "workspace-create":
        return {"workspace": str(create_workspace(args.source, args.workspace, reporter=progress).path)}
    if args.command == "edit-start":
        return edit_start(args.source, reporter=progress)
    if args.command == "edit-apply":
        return edit_apply(args.source, reporter=progress)
    if args.command == "workspace-check":
        with progress.stage("check"):
            result = workspace_check(args.path)
        if not result.valid:
            first = next(item for item in result.diagnostics if item["severity"] == "error")
            raise SessionError(f"shadow-invalid line={first['line']} column={first['column']}: {first['message']}")
        return result
    if args.command == "turn-start":
        surface = turn_start(args.workspace)
        return {"edit_dir": str(surface.path)}
    if args.command == "workspace-diff":
        edit_result, edit = workspace_diff(args.workspace)
        return {
            "changed": edit_result.changed, "answer": edit_result.answer_text,
            "changed_blocks": 0 if edit is None else len(edit.edited),
        }
    if args.command == "workspace-apply":
        return workspace_apply(args.workspace, args.output, current=args.current)


def _diagnostic_service(args):
    candidates = []
    if args.command in {"edit-start", "edit-apply"}:
        candidates.append(document_workspace_path(args.source))
    for name in ("workspace", "path"):
        value = getattr(args, name, None)
        if value:
            candidates.append(Path(value).resolve())
    for value in candidates:
        root = value if value.is_dir() else value.parent
        for candidate in (root, *root.parents):
            service = candidate / ".service"
            if service.is_dir():
                return service
    return None


def main(argv=None):
    args = _parser().parse_args(argv)
    progress = Progress("none" if args.quiet else args.progress)
    try:
        result = _dispatch(args, progress)
        _render(args, result)
        return 0
    except (WorkspaceError, EditDirError, SessionError, ValueError) as exc:
        if args.debug:
            raise
        stage = progress.current or progress.last_failed or "workspace"
        category = getattr(exc, "code", None) or type(exc).__name__.lower()
        service = _diagnostic_service(args)
        if service is not None:
            append_event(service, "error", str(exc), event=args.command)
        if args.json:
            print(json.dumps(failure(args.command, category, str(exc)), ensure_ascii=False, sort_keys=True))
        else:
            print(f"stage={stage} category={category} reason={exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        if args.debug:
            raise
        stage = progress.current or progress.last_failed or "workspace"
        reason = "interrupted; no document was published"
        service = _diagnostic_service(args)
        if service is not None:
            append_event(service, "error", reason, event=args.command)
        if args.json:
            print(json.dumps(failure(args.command, "interrupted", reason), ensure_ascii=False, sort_keys=True))
        else:
            print(f"stage={stage} category=interrupted reason={reason}", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
