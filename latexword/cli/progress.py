"""Stage progress reporting for workspace commands."""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager

REQUIRED_STAGES = (
    "package-validate", "convert", "parse", "profile", "project", "anchors",
    "persist", "provenance", "reopen", "agent", "check", "verify", "publish",
    "verify", "publish",
)


class Progress:
    """Write elapsed stage events to stderr."""

    def __init__(self, mode: str = "stage", *, stream=None):
        if mode not in {"none", "stage", "verbose"}:
            raise ValueError("progress must be none, stage, or verbose")
        self.mode = mode
        self.stream = stream or sys.stderr
        self.current = None
        self.last_failed = None

    @contextmanager
    def stage(self, name: str):
        started = time.perf_counter()
        previous = self.current
        self.current = name
        if self.mode != "none":
            print(f"stage={name} started", file=self.stream, flush=True)
        try:
            yield
        except Exception:
            self.last_failed = name
            elapsed = (time.perf_counter() - started) * 1000
            if self.mode != "none":
                print(f"stage={name} failed elapsed_ms={elapsed:.1f}", file=self.stream, flush=True)
            raise
        else:
            elapsed = (time.perf_counter() - started) * 1000
            if self.mode != "none":
                print(f"stage={name} elapsed_ms={elapsed:.1f}", file=self.stream, flush=True)
        finally:
            self.current = previous

    def note(self, name: str, message: str):
        if self.mode == "verbose":
            print(f"stage={name} {message}", file=self.stream, flush=True)


__all__ = ["Progress", "REQUIRED_STAGES"]
