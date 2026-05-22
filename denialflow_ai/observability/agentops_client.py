from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from denialflow_ai.core.config import get_settings
from denialflow_ai.core.context import get_trace_id
from denialflow_ai.core.logging import get_logger

logger = get_logger(__name__)

_agentops_initialized = False


def mark_initialized() -> None:
    global _agentops_initialized
    _agentops_initialized = True


def is_enabled() -> bool:
    return _agentops_initialized and get_settings().agentops_should_init


def _safe_add_tags(tags: list[str]) -> None:
    if not is_enabled():
        return
    try:
        import agentops

        if hasattr(agentops, "add_tags"):
            agentops.add_tags(tags)
        elif hasattr(agentops, "update_tags"):
            agentops.update_tags(tags)
    except Exception:
        pass


def _safe_record_event(name: str, metadata: dict[str, Any]) -> None:
    if not is_enabled():
        return
    try:
        import agentops

        if hasattr(agentops, "record"):
            agentops.record(name, metadata=metadata)
    except Exception:
        pass


def workflow_tags(
    *,
    run_id: str | None = None,
    batch_id: str | None = None,
    claim_id: str | None = None,
    phase: str | None = None,
    extra: list[str] | None = None,
) -> list[str]:
    tags: list[str] = list(extra or [])
    if run_id:
        tags.append(f"run:{run_id}")
    if batch_id:
        tags.append(f"batch:{batch_id}")
    if claim_id:
        tags.append(f"claim:{claim_id}")
    if phase:
        tags.append(f"phase:{phase}")
    return tags


@contextmanager
def agentops_trace_context(
    *,
    trace_name: str,
    tags: list[str] | None = None,
) -> Iterator[None]:
    """
    One AgentOps session per workflow/review run.

    Starts a trace when crews run and ends it on exit so Session Replay is
    available in the dashboard (see AgentOps CrewAI integration docs).
    """
    if not is_enabled():
        yield
        return

    import agentops

    session = None
    end_status = "Success"
    try:
        session = agentops.start_session(tags=tags or None)
        span = getattr(session, "trace_context", None)
        span = getattr(span, "span", None) if span else None
        if span is not None:
            from agentops.helpers.dashboard import get_trace_url

            logger.info(
                "agentops_session_replay",
                trace_name=trace_name,
                session_replay_url=get_trace_url(span),
            )
        yield
    except Exception:
        end_status = "Error"
        raise
    finally:
        try:
            agentops.end_session(end_status)
        except Exception:
            pass


def bind_workflow_context(
    *,
    run_id: str | None = None,
    batch_id: str | None = None,
    claim_id: str | None = None,
    phase: str | None = None,
) -> None:
    tags = workflow_tags(
        run_id=run_id,
        batch_id=batch_id,
        claim_id=claim_id,
        phase=phase,
    )
    metadata: dict[str, Any] = {}
    if run_id:
        metadata["run_id"] = run_id
    if batch_id:
        metadata["batch_id"] = batch_id
    if claim_id:
        metadata["claim_id"] = claim_id
    if phase:
        metadata["phase"] = phase
    trace = get_trace_id()
    if trace:
        metadata["trace_id"] = trace
    if tags:
        _safe_add_tags(tags)
    if metadata:
        _safe_record_event("workflow_context", metadata)


@contextmanager
def crew_kickoff_context(*, crew_name: str, model: str | None = None) -> Iterator[None]:
    tags = [f"crew:{crew_name}"]
    if model:
        tags.append(f"model:{model}")
    _safe_add_tags(tags)
    _safe_record_event("crew_kickoff", {"crew": crew_name, "model": model or ""})
    try:
        yield
    finally:
        pass


@contextmanager
def bedrock_review_context(*, appeal_id: str | None = None) -> Iterator[None]:
    bind_workflow_context(phase="bedrock_review", claim_id=appeal_id)
    _safe_add_tags(["bedrock_review"])
    try:
        yield
    finally:
        pass
