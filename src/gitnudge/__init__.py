"""GitNudge - AI-Powered Git Rebase Assistant."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from gitnudge.config import Config
from gitnudge.core import GitNudge

try:
    __version__ = _pkg_version("gitnudge")
except PackageNotFoundError:
    __version__ = "0.0.0+local"

__author__ = "GitNudge Contributors"

__all__ = ["GitNudge", "Config", "__version__"]
