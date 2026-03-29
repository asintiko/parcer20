"""Centralized logging configuration for API and workers."""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler


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
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
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
        root.addHandler(file_handler)

    # Quiet noisy frameworks by default.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    root._tbsparcer_configured = True  # type: ignore[attr-defined]

