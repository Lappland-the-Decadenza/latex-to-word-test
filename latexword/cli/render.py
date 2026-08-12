"""Human-readable rendering helpers for CLI results."""

from __future__ import annotations

import json


def render_json(value) -> str:
    """Render a result object using stable human-readable JSON."""

    payload = value.to_json_obj() if hasattr(value, "to_json_obj") else value
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


__all__ = ["render_json"]
