"""OpenAI embeddings only — Groq has no embed API."""

from __future__ import annotations

from openai import AsyncOpenAI, OpenAI

from denialflow_ai.core.config import get_settings


def require_openai_api_key_for_embeddings() -> None:
    if not get_settings().openai_api_key.strip():
        raise ValueError(
            "OPENAI_API_KEY is required for embeddings (RAG/Chroma). "
            "Groq does not provide an embeddings API — set OPENAI_API_KEY and "
            "OPENAI_EMBEDDING_MODEL (e.g. text-embedding-3-small) in .env."
        )


async def embed_texts(inputs: list[str]) -> list[list[float]]:
    """Vectorize text with OPENAI_EMBEDDING_MODEL (never Groq)."""
    require_openai_api_key_for_embeddings()
    s = get_settings()
    client = AsyncOpenAI(api_key=s.openai_api_key)
    resp = await client.embeddings.create(
        model=s.openai_embedding_model,
        input=inputs,
    )
    return [d.embedding for d in resp.data]


def embed_texts_sync(inputs: list[str]) -> list[list[float]]:
    """Sync variant for CrewAI tools."""
    require_openai_api_key_for_embeddings()
    s = get_settings()
    client = OpenAI(api_key=s.openai_api_key)
    resp = client.embeddings.create(
        model=s.openai_embedding_model,
        input=inputs,
    )
    return [d.embedding for d in resp.data]
