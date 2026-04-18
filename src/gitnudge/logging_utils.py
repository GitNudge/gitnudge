"""Structured logging for GitNudge."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

_API_KEY_PATTERN = re.compile(r"sk-(?:ant-)?[A-Za-z0-9_\-]{6,}")


class _RedactingFilter(logging.Filter):
    """Redacts secrets from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        redacted = _API_KEY_PATTERN.sub("sk-***REDACTED***", msg)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


def redact_secrets(value: Any) -> str:
    """Redact API keys from a string."""
    text = str(value)
    return _API_KEY_PATTERN.sub("sk-***REDACTED***", text)


def get_logger(name: str = "gitnudge") -> logging.Logger:
    """Return a configured logger with secret redaction."""
    logger = logging.getLogger(name)
    if getattr(logger, "_gitnudge_configured", False):
        return logger

    level_name = os.environ.get("GITNUDGE_LOG_LEVEL", "WARNING").upper()
    level = getattr(logging, level_name, logging.WARNING)
    logger.setLevel(level)

    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    handler.addFilter(_RedactingFilter())

    logger.addHandler(handler)
    logger.propagate = False
    logger._gitnudge_configured = True  # type: ignore[attr-defined]
    return logger
