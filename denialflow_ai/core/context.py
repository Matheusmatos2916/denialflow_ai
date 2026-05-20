from __future__ import annotations

import contextvars
import uuid
from typing import Any

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id",
    default="",
)
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id",
    default="",
)


def new_request_id() -> str:
    rid = str(uuid.uuid4())
    request_id_var.set(rid)
    return rid


def get_request_id() -> str:
    return request_id_var.get() or ""


def new_trace_id() -> str:
    tid = str(uuid.uuid4())
    trace_id_var.set(tid)
    return tid


def get_trace_id() -> str:
    return trace_id_var.get() or ""


def bind_context(**kwargs: Any) -> dict[str, Any]:
    """Merge identifiers for structured logging."""
    out = {k: v for k, v in kwargs.items() if v is not None}
    rid = get_request_id()
    tid = get_trace_id()
    if rid:
        out.setdefault("request_id", rid)
    if tid:
        out.setdefault("trace_id", tid)
    return out
