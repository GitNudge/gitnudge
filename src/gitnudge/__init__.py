"""GitNudge - AI-Powered Git Rebase Assistant."""

__version__ = "0.1.0"
__author__ = "GitNudge Contributors"

from gitnudge.config import Config
from gitnudge.core import GitNudge

__all__ = ["GitNudge", "Config", "__version__"]
