from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from denialflow_ai.core.context import (
    get_trace_id,
    new_trace_id,
    request_id_var,
)
from denialflow_ai.observability import get_metrics


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        import uuid

        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        request_id_var.set(rid)
        new_trace_id()
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=rid,
            trace_id=get_trace_id(),
        )
        request.state.request_id = rid
        m = get_metrics()
        m.inc_request()
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            m.inc_error()
            raise
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            m.observe_latency_ms(elapsed_ms)
        response.headers["x-request-id"] = rid
        return response
