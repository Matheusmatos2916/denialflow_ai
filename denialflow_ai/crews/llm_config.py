from __future__ import annotations

import os
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from crewai import Crew, LLM

from denialflow_ai.core.config import get_settings
from denialflow_ai.observability.agentops_client import crew_kickoff_context

T = TypeVar("T")

GROQ_LLAMA_70B_MODEL = "llama-3.3-70b-versatile"
GROQ_LLAMA_70B_CREW_MODEL = f"groq/{GROQ_LLAMA_70B_MODEL}"
RATE_LIMIT_RETRY_SLEEP_SEC = 2
RATE_LIMIT_MAX_RETRIES = 3


def ensure_openai_env() -> None:
    s = get_settings()
    if s.openai_api_key:
        os.environ.setdefault("OPENAI_API_KEY", s.openai_api_key)


def ensure_groq_env() -> None:
    s = get_settings()
    if s.groq_api_key:
        os.environ.setdefault("GROQ_API_KEY", s.groq_api_key)


def _strip_env_quotes(value: str) -> str:
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1].strip()
    return v


def ensure_bedrock_env() -> None:
    """Propagate AWS region and credentials for LiteLLM/CrewAI Bedrock (appeal review only)."""
    s = get_settings()
    region = (s.aws_region or "us-east-1").strip()
    if region:
        os.environ.setdefault("AWS_REGION", region)
        os.environ.setdefault("AWS_REGION_NAME", region)
        os.environ.setdefault("AWS_DEFAULT_REGION", region)
    access_key = _strip_env_quotes(s.aws_access_key_id)
    if access_key:
        os.environ.setdefault("AWS_ACCESS_KEY_ID", access_key)
    secret_key = _strip_env_quotes(s.aws_secret_access_key)
    if secret_key:
        os.environ.setdefault("AWS_SECRET_ACCESS_KEY", secret_key)
    session_token = _strip_env_quotes(s.aws_session_token)
    if session_token:
        os.environ.setdefault("AWS_SESSION_TOKEN", session_token)


def _with_provider_prefix(provider: str, model_id: str) -> str:
    """CrewAI expects provider/model (e.g. groq/llama-3.3-70b-versatile)."""
    if "/" in model_id:
        return model_id
    return f"{provider}/{model_id}"


def langchain_groq_model_id(model_id: str) -> str:
    """ChatGroq model id — strip only the groq/ prefix, keep e.g. openai/gpt-oss-120b."""
    mid = model_id.strip()
    if mid.lower().startswith("groq/"):
        return mid[5:]
    return mid


def _dedupe_models(models: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in models:
        mid = raw.strip()
        if not mid:
            continue
        key = mid.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(mid)
    return out


def groq_model_chain(
    *,
    preferred: str | None = None,
    include_appeal: bool = False,
) -> list[str]:
    """Ordered Groq models for automatic fallback (primary → fallback → appeal)."""
    s = get_settings()
    candidates: list[str] = []
    if preferred:
        candidates.append(preferred)
    candidates.extend([s.groq_model_primary, s.groq_model_fallback])
    if include_appeal:
        candidates.append(s.groq_model_appeal)
    return _dedupe_models(candidates)


def _normalize_groq_model_key(model_id: str) -> str:
    mid = model_id.strip().lower()
    if mid.startswith("groq/"):
        return mid[5:]
    return mid


def is_groq_llama_70b(model_id: str) -> bool:
    """True for groq/llama-3.3-70b-versatile and bare llama-3.3-70b-versatile."""
    return _normalize_groq_model_key(model_id) == GROQ_LLAMA_70B_MODEL


def is_groq_rate_limit_error(exc: BaseException) -> bool:
    """litellm.RateLimitError or Groq rate_limit_exceeded payload."""
    try:
        from litellm import RateLimitError

        if isinstance(exc, RateLimitError):
            return True
    except ImportError:
        pass
    if type(exc).__name__ == "RateLimitError":
        return True
    return "rate_limit_exceeded" in str(exc).lower()


def is_bedrock_rate_limit_error(exc: BaseException) -> bool:
    """Daily/token Bedrock quotas surfaced as litellm RateLimitError or BedrockException."""
    msg = str(exc).lower()
    if (
        "too many tokens per day" in msg
        or "too many tokens, please wait" in msg
        or "throttlingexception" in msg
        or "context window exceeded" in msg
        or "bedrockexception" in msg
        or ("bedrock" in msg and "rate" in msg)
    ):
        return True
    if is_groq_rate_limit_error(exc) and "bedrock" in msg:
        return True
    return False


def with_groq_70b_rate_limit_retry(model_id: str, fn: Callable[[], T]) -> T:
    """Retry the same request after 2s on rate limit — only for llama-3.3-70b-versatile."""
    if not is_groq_llama_70b(model_id):
        return fn()

    last_err: Exception | None = None
    for attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if is_groq_rate_limit_error(e) and attempt < RATE_LIMIT_MAX_RETRIES:
                time.sleep(RATE_LIMIT_RETRY_SLEEP_SEC)
                last_err = e
                continue
            raise
    assert last_err is not None
    raise last_err


async def with_groq_70b_rate_limit_retry_async(
    model_id: str,
    coro_fn: Callable[[], Awaitable[T]],
) -> T:
    """Async variant of with_groq_70b_rate_limit_retry."""
    if not is_groq_llama_70b(model_id):
        return await coro_fn()

    last_err: Exception | None = None
    for attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
        try:
            return await coro_fn()
        except Exception as e:  # noqa: BLE001
            if is_groq_rate_limit_error(e) and attempt < RATE_LIMIT_MAX_RETRIES:
                time.sleep(RATE_LIMIT_RETRY_SLEEP_SEC)
                last_err = e
                continue
            raise
    assert last_err is not None
    raise last_err


def kickoff_crew_with_model_fallback(
    *,
    build: Callable[[str | None], tuple[Crew, LLM]],
    crew_name: str = "crew",
) -> tuple[Any, str]:
    """Run crew.kickoff(), trying each GROQ_MODEL_* when provider is groq."""
    s = get_settings()
    provider = s.llm_provider.strip().lower()

    if provider != "groq":
        crew, llm = build(None)
        model_name = resolve_model_name(llm)
        with crew_kickoff_context(crew_name=crew_name, model=model_name):
            return crew.kickoff(), model_name

    last_err: Exception | None = None
    for model in groq_model_chain():
        try:
            crew, llm = build(model)
            model_name = resolve_model_name(llm)
            with crew_kickoff_context(crew_name=crew_name, model=model_name):
                out = with_groq_70b_rate_limit_retry(model, crew.kickoff)
            return out, model_name
        except Exception as e:  # noqa: BLE001 — try next model in chain
            last_err = e
            continue
    assert last_err is not None
    raise last_err


def build_llm(model: str | None = None, temperature: float = 0.2) -> LLM:
    """Return a CrewAI LLM instance (required by Agent — not langchain ChatGroq)."""
    s = get_settings()
    provider = s.llm_provider.strip().lower()

    if provider == "groq":
        ensure_groq_env()
        model_id = _with_provider_prefix("groq", model or s.groq_model_primary)
        return LLM(model=model_id, temperature=temperature)

    ensure_openai_env()
    model_id = _with_provider_prefix("openai", model or s.openai_model_primary)
    return LLM(model=model_id, temperature=temperature)


def resolve_model_name(llm: Any) -> str:
    return str(getattr(llm, "model", None) or getattr(llm, "model_name", "llm"))


def build_llm_bedrock(model: str | None = None, temperature: float = 0.1) -> LLM:
    """Bedrock LLM for appeal second-opinion review only — not used by workflow crews."""
    ensure_bedrock_env()
    s = get_settings()
    model_id = _with_provider_prefix("bedrock", model or s.bedrock_model_review)
    max_tokens = max(1, s.bedrock_review_max_tokens)
    return LLM(model=model_id, temperature=temperature, max_tokens=max_tokens)
