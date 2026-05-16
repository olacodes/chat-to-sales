"""
Structured logging setup.

- Development: plain text with timestamps (human-readable)
- Production: JSON lines (machine-parseable, works with CloudWatch/Datadog/etc.)

Request ID middleware adds a unique ID to every log line for request tracing.
"""

import json
import logging
import sys
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import get_settings

_settings = get_settings()

# ── Request ID context ───────────────────────────────────────────────────────

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID to every request for log tracing."""

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request_id_var.set(rid)
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response


# ── JSON formatter (production) ──────────────────────────────────────────────

class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get("-"),
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


# ── Plain formatter (development) ────────────────────────────────────────────

class PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rid = request_id_var.get("-")
        base = f"{self.formatTime(record, '%Y-%m-%dT%H:%M:%S')} | {record.levelname:<8} | {record.name} | [{rid}] {record.getMessage()}"
        if record.exc_info and record.exc_info[1]:
            base += "\n" + self.formatException(record.exc_info)
        return base


# ── Setup ────────────────────────────────────────────────────────────────────

LOG_LEVEL = logging.DEBUG if _settings.is_development else logging.INFO

_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(
    PlainFormatter() if _settings.is_development else JSONFormatter()
)

logging.basicConfig(
    level=LOG_LEVEL,
    handlers=[_handler],
)

# Silence noisy third-party loggers in production
if _settings.is_production:
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Call at module level: logger = get_logger(__name__)"""
    return logging.getLogger(name)
