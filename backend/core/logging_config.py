"""Centralized logging configuration for API and workers.

Adds:
- contextvars-based request_id propagation into log records
- secret redaction filter (Authorization, X-Internal-Api-Key, X-System-Access values)
- structured one-line text format with request_id slot
"""
from __future__ import annotations

import logging
import os
import re
import sys
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from typing import Optional


# --------------------------------------------------------------------------- #
# Request-ID context (set by middleware / worker entrypoint, read everywhere)
# --------------------------------------------------------------------------- #
_request_id_ctx: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


def set_request_id(value: Optional[str]) -> None:
    _request_id_ctx.set(value or None)


def get_request_id() -> Optional[str]:
    return _request_id_ctx.get()


class _RequestIdFilter(logging.Filter):
    """Inject request_id from contextvars into every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        if not getattr(record, "request_id", None):
            record.request_id = _request_id_ctx.get() or "-"
        return True


# --------------------------------------------------------------------------- #
# Secret redaction filter
# --------------------------------------------------------------------------- #
_SECRET_PATTERNS = [
    # Authorization: Bearer <token>
    re.compile(r"(authorization\s*[:=]\s*bearer\s+)([A-Za-z0-9\-_.+/=]+)", re.IGNORECASE),
    # generic header values: x-internal-api-key=<value>
    re.compile(r"(x-internal-api-key\s*[:=]\s*)([A-Za-z0-9\-_.+/=]{6,})", re.IGNORECASE),
    re.compile(r"(x-system-access\s*[:=]\s*)([A-Za-z0-9\-_.+/=]{6,})", re.IGNORECASE),
    re.compile(r"(x-launch-session\s*[:=]\s*)([A-Za-z0-9\-_.+/=]{6,})", re.IGNORECASE),
    re.compile(r"(x-access-token\s*[:=]\s*)([A-Za-z0-9\-_.+/=]{6,})", re.IGNORECASE),
    # generic Bearer in any context
    re.compile(r"(bearer\s+)([A-Za-z0-9\-_.+/=]{20,})", re.IGNORECASE),
    # Telegram bot token in URL: api.telegram.org/bot<digits>:<token>
    re.compile(r"(api\.telegram\.org/bot)(\d+:[A-Za-z0-9_-]+)", re.IGNORECASE),
]


# Card-shaped (12-19 digits with optional spaces/dashes) — masks all but last 4
_CARD_PII_REGEX = re.compile(r"(?<!\d)(?:\d[ -]?){12,19}(?!\d)")


def _mask_card_match(match: "re.Match[str]") -> str:
    digits = re.sub(r"\D", "", match.group(0))
    if len(digits) < 12:
        return match.group(0)
    return f"***{digits[-4:]}"


def _redact(text: str) -> str:
    if not text or "***" in text and len(text) < 256:
        return text
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub(lambda m: f"{m.group(1)}***REDACTED***", out)
    out = _CARD_PII_REGEX.sub(_mask_card_match, out)
    return out


class _SecretRedactFilter(logging.Filter):
    """Redact secret-shaped substrings before formatting."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        try:
            if isinstance(record.msg, str):
                record.msg = _redact(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: _redact(str(v)) for k, v in record.args.items()}
                elif isinstance(record.args, tuple):
                    record.args = tuple(_redact(str(a)) if isinstance(a, str) else a for a in record.args)
        except Exception:  # noqa: BLE001 — filter must never break logging
            pass
        return True


# --------------------------------------------------------------------------- #
def _level_from_env(default: str = "INFO") -> int:
    raw = str(os.getenv("LOG_LEVEL", default)).strip().upper()
    return getattr(logging, raw, logging.INFO)


def setup_logging() -> None:
    """
    Configure root logger once.
    Keeps a consistent format across uvicorn, API modules, and celery workers.
    """
    root = logging.getLogger()
    if getattr(root, "_tbsparcer_configured", False):
        return

    level = _level_from_env()
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(request_id)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    rid_filter = _RequestIdFilter()
    redact_filter = _SecretRedactFilter()

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(rid_filter)
    stream_handler.addFilter(redact_filter)
    root.handlers.clear()
    root.addHandler(stream_handler)
    root.setLevel(level)

    log_file = str(os.getenv("LOG_FILE", "")).strip()
    if log_file:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max(1, int(os.getenv("LOG_FILE_MAX_BYTES", str(50 * 1024 * 1024)))),
            backupCount=max(1, int(os.getenv("LOG_FILE_BACKUP_COUNT", "5"))),
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(rid_filter)
        file_handler.addFilter(redact_filter)
        root.addHandler(file_handler)

    # Quiet noisy frameworks by default.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    root._tbsparcer_configured = True  # type: ignore[attr-defined]
