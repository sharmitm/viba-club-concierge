"""Structured JSON logging with trace context propagation.

Every log line carries trace_id, span_id, agent, and tool fields so a single
member request can be followed across the orchestrator, sub-agents, guardrails,
and MCP tool calls. Errors are logged with full exception context.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from contextvars import ContextVar
from typing import Any

# Context propagated across async boundaries within a single request.
current_trace_id: ContextVar[str] = ContextVar("trace_id", default="-")
current_agent: ContextVar[str] = ContextVar("agent", default="-")

_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "message",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": round(record.created, 3),
            "level": record.levelname,
            "logger": record.name,
            "trace_id": current_trace_id.get(),
            "agent": current_agent.get(),
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure(level: int = logging.INFO, stream=None) -> None:
    """Configure root logging once. Idempotent."""
    root = logging.getLogger()
    if getattr(configure, "_done", False):
        return
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter())
    root.handlers[:] = [handler]
    root.setLevel(level)
    configure._done = True  # type: ignore[attr-defined]


def get_logger(name: str) -> logging.Logger:
    configure()
    return logging.getLogger(name)


class span:
    """Lightweight timing span: logs start/end with duration_ms, records errors.

    Usage:
        with span("golf.book_tee_time", tool="book_tee_time"):
            ...
    """

    def __init__(self, name: str, logger: logging.Logger | None = None, **fields: Any):
        self.name = name
        self.fields = fields
        self.logger = logger or get_logger("viba.trace")

    def __enter__(self) -> "span":
        self.start = time.perf_counter()
        self.logger.info("span.start", extra={"span": self.name, **self.fields})
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        duration_ms = round((time.perf_counter() - self.start) * 1000, 2)
        if exc is not None:
            self.logger.error(
                "span.error",
                extra={"span": self.name, "duration_ms": duration_ms, **self.fields},
                exc_info=(exc_type, exc, tb),
            )
        else:
            self.logger.info(
                "span.end",
                extra={"span": self.name, "duration_ms": duration_ms, **self.fields},
            )
        return False  # never swallow exceptions


def log_event(logger: logging.Logger, msg: str, level: int = logging.INFO, **fields: Any) -> None:
    """Log a structured event with arbitrary fields."""
    logger.log(level, msg, extra=fields)
