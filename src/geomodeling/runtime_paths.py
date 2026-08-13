"""Resolve immutable application resources in source and frozen builds."""

from __future__ import annotations

import os
import sys
from pathlib import Path


ENV_RESOURCE_ROOT = "GEOMODELING_RESOURCE_ROOT"


def resource_root() -> Path:
    """Return the directory containing ``config/``, ``web/`` and demo data.

    PyInstaller one-directory builds expose bundled data below ``sys._MEIPASS``.
    Source checkouts keep the same logical layout at the repository root.  An
    explicit environment override is useful for packaging tests and diagnostics.
    """

    override = os.environ.get(ENV_RESOURCE_ROOT)
    if override:
        return Path(override).expanduser().resolve()
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root).resolve()
    return Path(__file__).resolve().parents[2]


def executable_root() -> Path:
    """Return the writable portable-package root or the source repository root."""

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return resource_root()


def resource_path(*parts: str) -> Path:
    return resource_root().joinpath(*parts)
