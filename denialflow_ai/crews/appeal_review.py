from __future__ import annotations

import json
import re
from typing import Any

from denialflow_ai.core.config import get_settings
from denialflow_ai.observability.agentops_client import (
    workflow_tags,
    agentops_trace_context,
    # bedrock_review_context,  # Bedrock desativado — 2ª opinião só via Groq
)
from denialflow_ai.crews.llm_config import (
    # build_llm_bedrock,
    # ensure_bedrock_env,
    ensure_groq_env,
    groq_model_chain,
    # is_bedrock_rate_limit_error,
    is_groq_rate_limit_error,
    # resolve_model_name,
    with_groq_70b_rate_limit_retry,
)
from denialflow_ai.rag.sync_search import hits_to_prompt_block, retrieve_sync
from denialflow_ai.schemas import AppealAIReview, AppealDetail, RagHit, RagRetrievalResult

_REVIEW_SYSTEM_PROMPT = (
    "You are a senior healthcare RCM appeal QA reviewer. You receive an appeal draft "
    "from a prior AI system plus reference documents retrieved from the internal knowledge "
    "base (embeddings/Chroma). Evaluate clarity, professional tone, argument strength, "
    "completeness, and whether the draft aligns with the reference documents. "
    "Check whether the draft still contains bracket placeholders like [Your Company Name] "
    "or missing letterhead/cadastro (provider name, addresses, signer, letter date). "
    "Flag those in issues or missing_elements. "
    "Do not rewrite the full appeal. Do not invent policy citations beyond the documents "
    "provided. In citation_check, compare appeal claims to the reference documents. "
    "Output ONLY a compact JSON object with keys: overall_score (0-1), ready_to_submit (bool), "
    "issues (string array), missing_elements (string array), citation_check (string), "
    "suggested_edits (string array), recommended_action (approve|edit|reject), "
    "summary (string). Set agrees_with_crewai_confidence to null. "
    "Keep strings short (max ~80 chars each)."
)


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


def _truncate_rag_hits(hits: list[RagHit]) -> list[RagHit]:
    s = get_settings()
    max_chars = max(100, s.bedrock_review_rag_snippet_chars)
    return [
        h.model_copy(update={"snippet": (h.snippet or "")[:max_chars]})
        for h in hits
    ]


def _resolve_rag_hits(detail: AppealDetail) -> list[RagHit]:
    """
    Reference documents for Bedrock: stored appeal citations (from workflow RAG),
    or fresh Chroma retrieval via embeddings when refresh is enabled or citations are empty.
    """
    s = get_settings()
    top_k = max(1, s.bedrock_review_rag_top_k)

    if detail.citations and not s.bedrock_review_rag_refresh:
        return _truncate_rag_hits(detail.citations[:top_k])

    query = (detail.draft_text or "").strip()[:8000]
    if not query:
        return _truncate_rag_hits(detail.citations[:top_k]) if detail.citations else []

    result = retrieve_sync(query, top_k=top_k)
    if result.hits:
        return _truncate_rag_hits(result.hits)
    return _truncate_rag_hits(detail.citations[:top_k]) if detail.citations else []


def _format_rag_block(hits: list[RagHit]) -> str:
    return hits_to_prompt_block(RagRetrievalResult(query="", hits=hits))


def _build_review_payload(detail: AppealDetail, letter_context: str = "") -> str:
    """Appeal draft + knowledge-base documents (embeddings/Chroma), no classification/prioritization."""
    draft = (detail.draft_text or "").strip()
    rag_block = _format_rag_block(_resolve_rag_hits(detail))
    letter_block = ""
    if letter_context.strip():
        letter_block = f"EXPECTED_LETTERHEAD (from claim CSV):\n{letter_context.strip()}\n\n"
    return (
        f"{letter_block}"
        f"REFERENCE_DOCUMENTS (internal knowledge base):\n{rag_block}\n\n"
        f"APPEAL_DRAFT (analyze — do not rewrite entirely):\n{draft}"
    )


def _parse_ai_review(raw: str, *, crewai_model: str, reviewer_model: str) -> AppealAIReview:
    data = _extract_json(raw)
    data["analyzed_crewai_model"] = crewai_model
    data["model_used"] = reviewer_model
    data["agrees_with_crewai_confidence"] = None
    return AppealAIReview.model_validate(data)


def _finalize_review(review: AppealAIReview, *, crewai_model: str, reviewer_model: str) -> AppealAIReview:
    return review.model_copy(
        update={
            "analyzed_crewai_model": crewai_model,
            "model_used": reviewer_model or review.model_used,
            "agrees_with_crewai_confidence": None,
        }
    )


def _groq_litellm_review(
    detail: AppealDetail,
    groq_model: str,
    *,
    letter_context: str = "",
) -> AppealAIReview:
    import litellm

    ensure_groq_env()
    user = _build_review_payload(detail, letter_context)
    model = groq_model if "/" in groq_model else f"groq/{groq_model}"
    reviewer_label = f"groq:{model}"
    max_tokens = max(1, get_settings().bedrock_review_max_tokens)

    def _call() -> AppealAIReview:
        resp = litellm.completion(
            model=model,
            messages=[
                {"role": "system", "content": _REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            temperature=0.1,
            max_tokens=max_tokens,
        )
        content = resp.choices[0].message.content
        raw = content if isinstance(content, str) else str(content)
        review = _parse_ai_review(
            raw,
            crewai_model=detail.model_used,
            reviewer_model=reviewer_label,
        )
        return _finalize_review(review, crewai_model=detail.model_used, reviewer_model=reviewer_label)

    return with_groq_70b_rate_limit_retry(groq_model, _call)


def _groq_litellm_review_with_fallback(
    detail: AppealDetail,
    *,
    letter_context: str = "",
) -> AppealAIReview:
    """Try GROQ_MODEL_PRIMARY, then FALLBACK, then APPEAL on Groq rate limits."""
    last_err: Exception | None = None
    for model in groq_model_chain(include_appeal=True):
        try:
            return _groq_litellm_review(detail, model, letter_context=letter_context)
        except Exception as err:  # noqa: BLE001 — try next model in chain
            if is_groq_rate_limit_error(err):
                last_err = err
                continue
            raise
    if last_err is not None:
        raise last_err
    raise RuntimeError("groq_review_no_models_configured")


# --- Bedrock desativado: 2ª opinião usa apenas Groq (LiteLLM) ---
#
# def _bedrock_litellm_review(
#     detail: AppealDetail,
#     bedrock_model: str,
#     *,
#     letter_context: str = "",
# ) -> AppealAIReview:
#     ...
#
# def _bedrock_crewai_review(...) -> AppealAIReview:
#     ...
#
# def _on_bedrock_throttle(...) -> AppealAIReview:
#     ...


def run_appeal_second_opinion(detail: AppealDetail, letter_context: str = "") -> AppealAIReview:
    """
    Second opinion: appeal draft + RAG documents from Chroma/embeddings.
    Groq only (LiteLLM) — Bedrock path commented out.
    """
    appeal_id = getattr(detail, "appeal_id", None) or getattr(detail, "id", None)
    appeal_key = str(appeal_id) if appeal_id else None
    tags = workflow_tags(claim_id=appeal_key, phase="groq_review", extra=["groq_review"])
    with agentops_trace_context(trace_name="appeal-ai-review", tags=tags):
        s = get_settings()
        if not s.bedrock_review_enabled:
            raise RuntimeError("ai_review_disabled")

        if not (detail.draft_text or "").strip():
            raise ValueError("draft_text_empty")

        if not s.groq_api_key:
            raise RuntimeError("groq_api_key_missing")
        return _groq_litellm_review_with_fallback(detail, letter_context=letter_context)
