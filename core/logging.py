"""JSON log formatter + request_id filter.

The RequestIDMiddleware plants a ``request_id`` into a contextvar; the
filter below picks it up so every log record (web, Celery, background)
carries a traceable id without thread-local hacks.
"""

import contextvars
import json
import logging
import uuid
from datetime import datetime

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")


def set_request_id(request_id: str | None = None) -> str:
    """Set (or generate) the current request id. Returns the id in effect."""
    rid = request_id or str(uuid.uuid4())
    request_id_var.set(rid)
    return rid


def get_request_id() -> str:
    return request_id_var.get()


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """Structured JSON formatter — one object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id() or "-",
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key
            not in {
                "message",
                "asctime",
                "args",
                "exc_info",
                "exc_text",
                "stack_info",
                "request_id",
            }
            and not key.startswith("_")
        }
        if extras:
            payload["extra"] = extras
        return json.dumps(payload, default=str)
