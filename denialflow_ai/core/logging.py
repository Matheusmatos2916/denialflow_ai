from __future__ import annotations

import io
import logging
import sys
from typing import Any, TextIO

import structlog

from denialflow_ai.core.config import get_settings


def configure_stdout_utf8() -> None:
    """Avoid UnicodeEncodeError on Windows when logs contain emoji (e.g. AgentOps)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError, ValueError):
                pass


def _utf8_stdio_wrapper(stream: TextIO) -> TextIO:
    """Wrap a text stream so writes never raise UnicodeEncodeError on Windows."""
    buffer = getattr(stream, "buffer", None)
    if buffer is None or isinstance(stream, io.TextIOWrapper) and stream.encoding == "utf-8":
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
                return stream
            except (AttributeError, OSError, ValueError):
                pass
        return stream
    return io.TextIOWrapper(buffer, encoding="utf-8", errors="replace", line_buffering=True)


def patch_stream_handler_encoding(logger_name: str) -> None:
    """Re-bind StreamHandler streams after libraries (e.g. AgentOps) replace handlers."""
    configure_stdout_utf8()
    log = logging.getLogger(logger_name)
    for handler in log.handlers:
        if not isinstance(handler, logging.StreamHandler):
            continue
        try:
            handler.setStream(_utf8_stdio_wrapper(handler.stream))
        except (AttributeError, OSError, ValueError):
            pass


def patch_agentops_stdio_encoding() -> None:
    patch_stream_handler_encoding("agentops")


def configure_logging() -> None:
    configure_stdout_utf8()
    settings = get_settings()
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        timestamper,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if settings.log_json:
        structlog.configure(
            processors=[
                *shared,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
            cache_logger_on_first_use=True,
        )
    else:
        structlog.configure(
            processors=[
                *shared,
                structlog.dev.ConsoleRenderer(colors=True),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
            cache_logger_on_first_use=True,
        )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
