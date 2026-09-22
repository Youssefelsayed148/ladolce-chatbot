"""Structured (JSON) logging setup.

Per the design doc's "structured logging from day one" decision: every log line
is JSON with a timestamp, level, logger name, and message, plus any extra fields
(request_id, conversation_id, tool call info) attached at log time. A stdlib
logging filter injects the per-request request_id so it rides along on every
line emitted while handling that request.
"""

import logging
from contextvars import ContextVar

from pythonjsonlogger import jsonlogger

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s",
            rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
        )
    )
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Uvicorn has its own handlers; route them through ours for uniform output.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
