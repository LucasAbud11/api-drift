"""Centralized logging configuration.

Kept deliberately small: one function you call once at process
startup (CLI, server entrypoint, or test session) to get consistent
formatting across the codebase.
"""
from __future__ import annotations

import logging
import sys

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger("opsmesh")
    if root.handlers:
        # Already configured (e.g. re-entrant call from tests) - just
        # update the level and move on.
        root.setLevel(level.upper())
        return

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
    root.setLevel(level.upper())
    root.propagate = False
