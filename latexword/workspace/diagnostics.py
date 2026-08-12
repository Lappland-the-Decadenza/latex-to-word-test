"""Small UTF-8 diagnostic log for one managed document."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def append_event(service, severity, message, *, event="workspace"):
    """Append one concise event without ever writing outside ``.service``."""

    target = Path(service).resolve() / "diagnostics.log"
    target.parent.mkdir(parents=True, exist_ok=True)
    clean = " ".join(str(message).splitlines()).strip()
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{stamp}\t{severity.upper()}\t{event}\t{clean}\n")


def append_diagnostics(service, event, diagnostics, *, severity="warning"):
    for diagnostic in diagnostics:
        append_event(service, severity, diagnostic, event=event)


__all__ = ["append_diagnostics", "append_event"]
