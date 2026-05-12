"""Runtime compatibility shims for dependency edge cases."""

from __future__ import annotations

import sys


def ensure_importlib_resources() -> None:
    """Expose the backport as importlib.resources if a runtime is missing it.

    Some dependency stacks import ``importlib.resources`` lazily when the first
    HTTPS request is made. Modern Python includes it, but this keeps camera
    refresh from failing in older or stripped-down local runtimes.
    """
    try:
        import importlib.resources  # noqa: F401
    except ModuleNotFoundError:
        import importlib_resources

        sys.modules.setdefault("importlib.resources", importlib_resources)

