from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Any


@dataclass
class LatencySample:
    count: int = 0
    total_ms: float = 0.0

    def record(self, ms: float) -> None:
        self.count += 1
        self.total_ms += ms

    @property
    def avg_ms(self) -> float | None:
        if self.count == 0:
            return None
        return self.total_ms / self.count


class InMemoryMetrics:
    """Lightweight metrics for dashboard demos (not HA)."""

    def __init__(self) -> None:
        self._lock = Lock()
        self.requests_total = 0
        self.errors_total = 0
        self.workflow_runs_total = 0
        self._latencies: deque[float] = deque(maxlen=500)

    def inc_request(self) -> None:
        with self._lock:
            self.requests_total += 1

    def inc_error(self) -> None:
        with self._lock:
            self.errors_total += 1

    def inc_workflow(self) -> None:
        with self._lock:
            self.workflow_runs_total += 1

    def observe_latency_ms(self, ms: float) -> None:
        with self._lock:
            self._latencies.append(ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            lat = list(self._latencies)
        avg = sum(lat) / len(lat) if lat else None
        return {
            "requests_total": self.requests_total,
            "errors_total": self.errors_total,
            "workflow_runs_total": self.workflow_runs_total,
            "avg_latency_ms_recent": avg,
        }


_metrics = InMemoryMetrics()


def get_metrics() -> InMemoryMetrics:
    return _metrics


@dataclass
class Span:
    name: str
    started: float = field(default_factory=time.perf_counter)

    def end(self) -> float:
        return (time.perf_counter() - self.started) * 1000.0
