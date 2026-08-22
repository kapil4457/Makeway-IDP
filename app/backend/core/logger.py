"""
Central logging configuration for Forge AI.

Provides JSON-structured logging with correlation ID support for async-safe
request tracing across API routes, workers, and CLI commands.

Usage:
    from core.logger import get_logger, setup_logging

    # Call once at application startup:
    setup_logging()

    # In every module:
    logger = get_logger(__name__)
    logger.info("Provisioning resource", extra={
        "extra_fields": {"resource_type": "rds", "environment": "prod"}
    })
"""

import json
import logging
import os
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def set_request_id(request_id: str) -> None:
    """Set the correlation ID for the current async context."""
    _request_id_var.set(request_id)


def get_request_id() -> str | None:
    """Get the correlation ID for the current async context, or None."""
    return _request_id_var.get()



class JsonFormatter(logging.Formatter):
    """Formats log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        request_id = get_request_id()
        if request_id is not None:
            entry["request_id"] = request_id

        if record.exc_info and record.exc_info[1]:
            entry["exception"] = self.formatException(record.exc_info)

        # Merge caller-supplied structured fields
        extra_fields: dict[str, object] | None = getattr(record, "extra_fields", None)
        if extra_fields:
            entry.update(extra_fields)

        return json.dumps(entry, default=str, ensure_ascii=False)



class RequestIdFilter(logging.Filter):
    """Attaches the current correlation ID to every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()  # type: ignore[attr-defined]
        return True

THIRD_PARTY_NOISE = {
    "uvicorn.access": logging.WARNING,
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "urllib3": logging.WARNING,
    "websockets": logging.WARNING,
}

DEFAULT_LOG_DIR: Path = Path("logs")
DEFAULT_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MB
DEFAULT_BACKUP_COUNT: int = 5
DEFAULT_LOG_FILENAME: str = "forge.jsonl"


def setup_logging() -> None:
    """
    Configure the root logger for JSON-structured output.

    Writes to **both** stdout and a rotating JSON-lines file so logs are
    available for Grafana/Loki via Promtail while also visible in the
    terminal / Docker stdout.

    Environment variables:
        LOG_LEVEL          — logging level (default: "INFO")
        FORGE_LOG_DIR      — directory for persisted logs (default: "logs/")
        FORGE_LOG_MAX_BYTES — max bytes per file before rotation (default: 10 MB)
        FORGE_LOG_BACKUPS  — number of rotated files to keep (default: 5)
    """
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    log_dir = Path(os.getenv("FORGE_LOG_DIR", str(DEFAULT_LOG_DIR)))
    max_bytes = int(os.getenv("FORGE_LOG_MAX_BYTES", str(DEFAULT_MAX_BYTES)))
    backup_count = int(os.getenv("FORGE_LOG_BACKUPS", str(DEFAULT_BACKUP_COUNT)))

    root = logging.getLogger()
    root.setLevel(level)

    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = JsonFormatter()
    request_filter = RequestIdFilter()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.addFilter(request_filter)
    root.addHandler(console)

    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        filename=str(log_dir / DEFAULT_LOG_FILENAME),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(request_filter)
    root.addHandler(file_handler)

    for name, min_level in THIRD_PARTY_NOISE.items():
        logging.getLogger(name).setLevel(min_level)



def get_logger(name: str) -> logging.Logger:
    """Return a logger for the given module name."""
    return logging.getLogger(name)