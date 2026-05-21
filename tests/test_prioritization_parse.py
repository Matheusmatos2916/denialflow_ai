"""Regression tests for PrioritizationResult coercion and JSON extraction."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from denialflow_ai.crews.prioritization import (
    _coerce_prioritization_result,
    _deterministic_fallback_result,
    _normalize_prioritization_dict,
    _parse_prioritization,
)
from denialflow_ai.llm import _extract_prioritization_json
from denialflow_ai.schemas import PrioritizationResult


def test_claim_echo_gets_defaults() -> None:
    bad = {
        "claim_id": "CLM-DF-2025001",
        "denial_reason_text": "authorization missing",
    }
    result = _coerce_prioritization_result(bad)
    assert isinstance(result, PrioritizationResult)
    assert result.priority_score == 50.0
    assert result.urgency == 0.5
    assert result.reversal_probability == 0.5
    assert len(result.recommended_action) >= 5


def test_aliases_mapped() -> None:
    data = {
        "priority": 80,
        "recoverable_revenue": 1200.0,
        "urgency_score": 0.7,
        "reversal_prob": 0.5,
        "recommendation": "File appeal with documentation",
    }
    result = _coerce_prioritization_result(data)
    assert result.priority_score == 80.0
    assert result.estimated_recoverable_revenue == 1200.0
    assert result.urgency == 0.7
    assert result.reversal_probability == 0.5
    assert "appeal" in result.recommended_action.lower()


def test_null_fields_get_defaults() -> None:
    data = {
        "priority_score": None,
        "estimated_recoverable_revenue": None,
        "urgency": None,
        "reversal_probability": None,
        "recommended_action": None,
    }
    normalized = _normalize_prioritization_dict(data)
    result = PrioritizationResult.model_validate(normalized)
    assert result.priority_score == 50.0
    assert result.estimated_recoverable_revenue == 0.0


def test_derive_revenue_from_claim_amounts() -> None:
    data = {
        "billed_amount": 10000.0,
        "allowed_amount": 3000.0,
        "recommendation": "Submit corrected authorization",
    }
    normalized = _normalize_prioritization_dict(data)
    assert normalized["estimated_recoverable_revenue"] == 7000.0


def test_extract_prioritization_json_picks_scoring_object() -> None:
    claim = (
        '{"claim_id": "CLM-DF-2025001", "denial_reason_text": "authorization missing"}'
    )
    scores = (
        '{"priority_score": 72.5, "estimated_recoverable_revenue": 1840.0, '
        '"urgency": 0.6, "reversal_probability": 0.45, '
        '"recommended_action": "Submit appeal with documentation"}'
    )
    text = f"Analysis based on claim {claim} prioritization: {scores}"
    extracted = _extract_prioritization_json(text)
    assert extracted["priority_score"] == 72.5
    assert extracted["recommended_action"].startswith("Submit appeal")


def test_parse_prioritization_from_raw_text() -> None:
    raw = (
        '{"priority_score": 55, "estimated_recoverable_revenue": 900, '
        '"urgency": 0.4, "reversal_probability": 0.3, '
        '"recommended_action": "Submit appeal now"}'
    )
    result = _parse_prioritization(raw)
    assert result.priority_score == 55.0


def test_deterministic_fallback_never_raises() -> None:
    invalid = {"priority_score": "not-a-number", "urgency": "high"}
    result = _deterministic_fallback_result(
        invalid,
        classification_summary="authorization (0.85): missing auth number",
    )
    assert isinstance(result, PrioritizationResult)
    assert len(result.recommended_action) >= 5


def test_coerce_invalid_types_falls_back() -> None:
    result = _coerce_prioritization_result(
        {"priority_score": "invalid", "urgency": object()},
        classification_summary="test category",
    )
    assert result.priority_score == 50.0


def test_model_validate_without_normalize_still_fails() -> None:
    """Document that raw claim echo must go through coerce."""
    bad = {"claim_id": "CLM-DF-2025001", "recommendation": "appeal"}
    with pytest.raises(ValidationError):
        PrioritizationResult.model_validate(bad)
