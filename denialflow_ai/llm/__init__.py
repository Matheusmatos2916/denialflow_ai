from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from openai import AsyncOpenAI
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from denialflow_ai.core.config import get_settings
from denialflow_ai.crews.llm_config import (
    ensure_groq_env,
    groq_model_chain,
    langchain_groq_model_id,
    with_groq_70b_rate_limit_retry_async,
)
from denialflow_ai.llm.embeddings import require_openai_api_key_for_embeddings

__all__ = [
    "GroqLangChainClient",
    "OpenAIClient",
    "get_embeddings_client",
    "get_llm_client",
    "get_openai_client",
    "require_openai_api_key_for_embeddings",
]

T = TypeVar("T", bound=BaseModel)


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no_json_object_in_model_output")
    return json.loads(text[start : end + 1])


class GroqLangChainClient:
    """Async JSON/text chat via langchain_groq.ChatGroq."""

    def __init__(self) -> None:
        ensure_groq_env()
        s = get_settings()
        self._primary = s.groq_model_primary
        self._fallback = s.groq_model_fallback
        self._appeal = s.groq_model_appeal
        self._api_key = s.groq_api_key or None

    def _resolve_models(
        self,
        model: str | None,
        *,
        allow_fallback: bool,
        include_appeal: bool = False,
    ) -> list[str]:
        if not allow_fallback:
            return [langchain_groq_model_id(model or self._primary)]
        return [langchain_groq_model_id(m) for m in groq_model_chain(
            preferred=model,
            include_appeal=include_appeal,
        )]

    def _chat_model(self, model: str, *, json_mode: bool, temperature: float) -> ChatGroq:
        llm = ChatGroq(
            model=langchain_groq_model_id(model),
            temperature=temperature,
            groq_api_key=self._api_key,
        )
        if json_mode:
            return llm.bind(response_format={"type": "json_object"})
        return llm

    async def _ainvoke(self, model: str, llm: ChatGroq, messages: list) -> Any:
        return await with_groq_70b_rate_limit_retry_async(
            model,
            lambda: llm.ainvoke(messages),
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=8))
    async def chat_json(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
        allow_fallback: bool = True,
    ) -> dict[str, Any]:
        models = self._resolve_models(model, allow_fallback=allow_fallback)
        last_err: Exception | None = None
        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        for m in models:
            try:
                llm = self._chat_model(m, json_mode=True, temperature=0.2)
                resp = await self._ainvoke(m, llm, messages)
                content = resp.content if isinstance(resp.content, str) else str(resp.content)
                return json.loads(content)
            except Exception as e:  # noqa: BLE001 — demo resilience
                last_err = e
                continue
        assert last_err is not None
        raise last_err

    async def chat_text(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
        allow_fallback: bool = True,
    ) -> tuple[str, str]:
        models = self._resolve_models(model, allow_fallback=allow_fallback)
        last_err: Exception | None = None
        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        for m in models:
            try:
                llm = self._chat_model(m, json_mode=False, temperature=0.3)
                resp = await self._ainvoke(m, llm, messages)
                text = resp.content if isinstance(resp.content, str) else str(resp.content)
                return text, m
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue
        assert last_err is not None
        raise last_err

    async def appeal_text(
        self,
        *,
        system: str,
        user: str,
        allow_fallback: bool = True,
    ) -> tuple[str, str]:
        models = self._resolve_models(
            self._appeal,
            allow_fallback=allow_fallback,
            include_appeal=True,
        )
        last_err: Exception | None = None
        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        for m in models:
            try:
                llm = self._chat_model(m, json_mode=False, temperature=0.3)
                resp = await self._ainvoke(m, llm, messages)
                text = resp.content if isinstance(resp.content, str) else str(resp.content)
                return text, m
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue
        assert last_err is not None
        raise last_err

    def parse_pydantic(self, data: dict[str, Any], model: type[T]) -> T:
        return model.model_validate(data)

    def parse_json_blob(self, text: str, model: type[T]) -> T:
        return model.model_validate(_extract_json(text))

    async def embed(self, inputs: list[str]) -> list[list[float]]:
        """Groq has no embeddings — always delegate to OpenAI."""
        from denialflow_ai.llm.embeddings import embed_texts

        return await embed_texts(inputs)

    def embed_sync(self, inputs: list[str]) -> list[list[float]]:
        from denialflow_ai.llm.embeddings import embed_texts_sync

        return embed_texts_sync(inputs)


class OpenAIClient:
    """Async OpenAI helper with retries and optional JSON-to-Pydantic parsing."""

    def __init__(self) -> None:
        s = get_settings()
        self._client = AsyncOpenAI(api_key=s.openai_api_key or None)
        self._primary = s.openai_model_primary
        self._fallback = s.openai_model_fallback
        self._appeal = s.openai_model_appeal

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=8))
    async def chat_json(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
        allow_fallback: bool = True,
    ) -> dict[str, Any]:
        models = [model or self._primary]
        if allow_fallback and self._fallback not in models:
            models.append(self._fallback)
        last_err: Exception | None = None
        for m in models:
            try:
                resp = await self._client.chat.completions.create(
                    model=m,
                    temperature=0.2,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                content = resp.choices[0].message.content or "{}"
                return json.loads(content)
            except Exception as e:  # noqa: BLE001 — demo resilience
                last_err = e
                continue
        assert last_err is not None
        raise last_err

    async def chat_text(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
        allow_fallback: bool = True,
    ) -> tuple[str, str]:
        models = [model or self._primary]
        if allow_fallback and self._fallback not in models:
            models.append(self._fallback)
        last_err: Exception | None = None
        for m in models:
            try:
                resp = await self._client.chat.completions.create(
                    model=m,
                    temperature=0.3,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                text = resp.choices[0].message.content or ""
                return text, m
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue
        assert last_err is not None
        raise last_err

    async def appeal_text(
        self,
        *,
        system: str,
        user: str,
        allow_fallback: bool = True,
    ) -> tuple[str, str]:
        s = get_settings()
        return await self.chat_text(
            system=system,
            user=user,
            model=s.openai_model_appeal,
            allow_fallback=allow_fallback,
        )

    def parse_pydantic(self, data: dict[str, Any], model: type[T]) -> T:
        return model.model_validate(data)

    def parse_json_blob(self, text: str, model: type[T]) -> T:
        return model.model_validate(_extract_json(text))

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=8))
    async def embed(self, inputs: list[str]) -> list[list[float]]:
        from denialflow_ai.llm.embeddings import embed_texts

        return await embed_texts(inputs)

    def embed_sync(self, inputs: list[str]) -> list[list[float]]:
        from denialflow_ai.llm.embeddings import embed_texts_sync

        return embed_texts_sync(inputs)


_chat_client_singleton: OpenAIClient | GroqLangChainClient | None = None
_embeddings_client_singleton: OpenAIClient | None = None


def get_llm_client() -> OpenAIClient | GroqLangChainClient:
    """Chat/JSON fallback client — Groq or OpenAI per LLM_PROVIDER."""
    global _chat_client_singleton
    if _chat_client_singleton is None:
        provider = get_settings().llm_provider.strip().lower()
        _chat_client_singleton = (
            GroqLangChainClient() if provider == "groq" else OpenAIClient()
        )
    return _chat_client_singleton


def get_embeddings_client() -> OpenAIClient:
    """Chat-capable OpenAI client; prefer embed_texts() from denialflow_ai.llm.embeddings for vectors."""
    global _embeddings_client_singleton
    if _embeddings_client_singleton is None:
        from denialflow_ai.llm.embeddings import require_openai_api_key_for_embeddings

        require_openai_api_key_for_embeddings()
        _embeddings_client_singleton = OpenAIClient()
    return _embeddings_client_singleton


def get_openai_client() -> OpenAIClient | GroqLangChainClient:
    """Chat/JSON only (Groq or OpenAI). For vectors use denialflow_ai.llm.embeddings.embed_texts."""
    return get_llm_client()
