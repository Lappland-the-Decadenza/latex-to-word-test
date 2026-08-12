"""Machine-readable CLI envelope rendering."""

from __future__ import annotations


SCHEMA = "lw-cli/v1"


def success(command: str, result):
    payload = result.to_json_obj() if hasattr(result, "to_json_obj") else result
    return {"schema": SCHEMA, "ok": True, "command": command, "result": payload}


def failure(command: str, category: str, reason: str):
    return {"schema": SCHEMA, "ok": False, "command": command, "error": {"category": category, "reason": reason}}


__all__ = ["SCHEMA", "failure", "success"]
