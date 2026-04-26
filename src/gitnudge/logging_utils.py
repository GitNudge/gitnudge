"""Structured logging for GitNudge."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

_API_KEY_PATTERN = re.compile(r"sk-(?:ant-)?[A-Za-z0-9_\-]{6,}")


class _RedactingFilter(logging.Filter):
    """Redacts secrets from log records (message text and args)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
            record.args = ()

        redacted = _API_KEY_PATTERN.sub("sk-***REDACTED***", msg)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        elif record.args:
            new_args: list[Any] = []
            changed = False
            for a in record.args if isinstance(record.args, tuple) else (record.args,):
                s = str(a)
                r = _API_KEY_PATTERN.sub("sk-***REDACTED***", s)
                if r != s:
                    changed = True
                    new_args.append(r)
                else:
                    new_args.append(a)
            if changed:
                record.args = tuple(new_args)
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
