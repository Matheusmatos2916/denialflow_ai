"""Groq model chain fallback for appeal second-opinion review."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from denialflow_ai.crews import appeal_review
from denialflow_ai.schemas import AppealAIReview, AppealDetail


def _minimal_review(model_used: str) -> AppealAIReview:
    return AppealAIReview(
        overall_score=0.8,
        ready_to_submit=False,
        issues=[],
        missing_elements=[],
        citation_check="ok",
        suggested_edits=[],
        recommended_action="edit",
        summary="Review looks acceptable overall.",
        model_used=model_used,
        analyzed_crewai_model="groq/primary",
    )


def _detail() -> AppealDetail:
    return AppealDetail(
        id="a1",
        claim_internal_id="c1",
        claim_id="CLM-1",
        status="draft",
        draft_text="Appeal body for review.",
        final_text=None,
        confidence=0.8,
        citations=[],
        model_used="groq/llama-3.3-70b-versatile",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def test_groq_review_tries_fallback_models_on_rate_limit() -> None:
    detail = _detail()
    calls: list[str] = []

    def fake_review(
        _detail: AppealDetail,
        groq_model: str,
        *,
        letter_context: str = "",
    ) -> AppealAIReview:
        calls.append(groq_model)
        if groq_model == "llama-3.3-70b-versatile":
            raise Exception(
                'RateLimitError: GroqException - {"error":{"code":"rate_limit_exceeded"}}'
            )
        return _minimal_review(f"groq-fallback:{groq_model}")

    with patch.object(appeal_review, "_groq_litellm_review", side_effect=fake_review):
        with patch.object(
            appeal_review,
            "groq_model_chain",
            return_value=["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
        ):
            review = appeal_review._groq_litellm_review_with_fallback(detail)

    assert calls == ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
    assert "llama-3.1-8b-instant" in review.model_used


def test_groq_review_raises_when_all_models_rate_limited() -> None:
    detail = _detail()

    def always_limit(*_args, **_kwargs) -> AppealAIReview:
        raise Exception("rate_limit_exceeded")

    with patch.object(appeal_review, "_groq_litellm_review", side_effect=always_limit):
        with patch.object(
            appeal_review,
            "groq_model_chain",
            return_value=["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
        ):
            with pytest.raises(Exception, match="rate_limit_exceeded"):
                appeal_review._groq_litellm_review_with_fallback(detail)
