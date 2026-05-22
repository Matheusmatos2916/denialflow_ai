from __future__ import annotations

import asyncio
from typing import Any

from crewai import Agent, Crew, Process, Task
from pydantic import ValidationError

from denialflow_ai.crews.llm_config import (
    build_llm,
    ensure_groq_env,
    ensure_openai_env,
    kickoff_crew_with_model_fallback,
)
from denialflow_ai.llm import _extract_prioritization_json, get_llm_client
from denialflow_ai.schemas import PrioritizationResult

_PRIORITIZATION_JSON_KEYS = (
    "priority_score (0-100 float), "
    "estimated_recoverable_revenue (USD float >= 0), "
    "urgency (0-1 float), "
    "reversal_probability (0-1 float), "
    "recommended_action (string, 5-2000 chars)"
)

_PRIORITIZATION_SYSTEM_PROMPT = (
    "You prioritize denied US healthcare claims for revenue cycle collections. "
    "Respond with a single JSON object containing ONLY these keys — do not echo claim "
    "fields such as claim_id, payer, or denial_code:\n"
    f"{_PRIORITIZATION_JSON_KEYS}."
)

_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "priority_score": ("priority", "score", "priorityScore"),
    "estimated_recoverable_revenue": (
        "recoverable_revenue",
        "estimated_revenue",
        "recoverable",
        "estimatedRecoverableRevenue",
    ),
    "urgency": ("urgency_score", "urgencyScore"),
    "reversal_probability": (
        "reversal_prob",
        "probability_of_reversal",
        "reversalProbability",
    ),
    "recommended_action": (
        "recommendation",
        "action",
        "next_action",
        "recommendedAction",
    ),
}

_NUMERIC_DEFAULTS: dict[str, float] = {
    "priority_score": 50.0,
    "estimated_recoverable_revenue": 0.0,
    "urgency": 0.5,
    "reversal_probability": 0.5,
}


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _derive_recoverable_revenue(data: dict[str, Any]) -> float:
    billed = _as_float(data.get("billed_amount"))
    allowed = _as_float(data.get("allowed_amount"))
    if billed is not None and allowed is not None:
        return max(0.0, billed - allowed)
    patient = _as_float(data.get("patient_balance"))
    if patient is not None:
        return max(0.0, patient)
    return 0.0


def _normalize_prioritization_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Map common LLM key variants onto PrioritizationResult field names."""
    out = dict(data)

    for canonical, aliases in _FIELD_ALIASES.items():
        if out.get(canonical) is not None:
            continue
        for alt in aliases:
            if out.get(alt) is not None:
                out[canonical] = out[alt]
                break

    for field, default in _NUMERIC_DEFAULTS.items():
        if out.get(field) is None:
            out[field] = default

    if out.get("estimated_recoverable_revenue") in (None, 0, 0.0):
        derived = _derive_recoverable_revenue(out)
        if derived > 0:
            out["estimated_recoverable_revenue"] = derived

    action = out.get("recommended_action")
    if not action or not str(action).strip():
        for alt in ("recommendation", "explanation", "denial_reason_text"):
            candidate = out.get(alt)
            if candidate and str(candidate).strip():
                out["recommended_action"] = str(candidate).strip()[:2000]
                break
    if not out.get("recommended_action") or len(str(out["recommended_action"]).strip()) < 5:
        out["recommended_action"] = "Manual review required."

    return out


def _deterministic_fallback_result(
    data: dict[str, Any] | None = None,
    *,
    classification_summary: str = "",
) -> PrioritizationResult:
    normalized = _normalize_prioritization_dict(data or {})
    action = str(normalized.get("recommended_action", "")).strip()
    if len(action) < 5 and classification_summary.strip():
        action = f"Review denial: {classification_summary.strip()[:1900]}"
    if len(action) < 5:
        action = "Manual review required."

    def _num(field: str, default: float, lo: float, hi: float) -> float:
        val = _as_float(normalized.get(field))
        if val is None:
            return default
        return max(lo, min(hi, val))

    return PrioritizationResult(
        priority_score=_num("priority_score", 50.0, 0.0, 100.0),
        estimated_recoverable_revenue=_num("estimated_recoverable_revenue", 0.0, 0.0, 1e12),
        urgency=_num("urgency", 0.5, 0.0, 1.0),
        reversal_probability=_num("reversal_probability", 0.5, 0.0, 1.0),
        recommended_action=action[:2000],
    )


def _coerce_prioritization_result(
    data: dict[str, Any],
    *,
    classification_summary: str = "",
) -> PrioritizationResult:
    normalized = _normalize_prioritization_dict(data)
    try:
        return PrioritizationResult.model_validate(normalized)
    except ValidationError:
        return _deterministic_fallback_result(
            normalized,
            classification_summary=classification_summary,
        )


def _parse_prioritization(raw: str, *, classification_summary: str = "") -> PrioritizationResult:
    data = _extract_prioritization_json(raw)
    return _coerce_prioritization_result(data, classification_summary=classification_summary)


def _crew_prioritization_result(out: object) -> PrioritizationResult | None:
    direct = getattr(out, "pydantic", None)
    if isinstance(direct, PrioritizationResult):
        return direct
    for task_out in getattr(out, "tasks_output", None) or []:
        parsed = getattr(task_out, "pydantic", None)
        if isinstance(parsed, PrioritizationResult):
            return parsed
    return None


def _fallback_prioritization(
    claim_payload: str,
    classification_summary: str,
) -> PrioritizationResult:
    client = get_llm_client()
    user = (
        f"Claim record:\n{claim_payload}\n\n"
        f"Classification summary:\n{classification_summary}\n\n"
        "Score this claim for collections priority. "
        "Return only the five required JSON keys; no claim_id or other claim fields."
    )
    retry_user = (
        f"{user}\n\n"
        "Example shape:\n"
        '{"priority_score":72.5,"estimated_recoverable_revenue":1840.0,'
        '"urgency":0.6,"reversal_probability":0.45,'
        '"recommended_action":"Submit corrected claim with supporting documentation."}'
    )

    for prompt in (user, retry_user):
        try:
            data = asyncio.run(
                client.chat_json(
                    system=_PRIORITIZATION_SYSTEM_PROMPT,
                    user=prompt,
                    allow_fallback=True,
                )
            )
            if isinstance(data, dict):
                return _coerce_prioritization_result(
                    data,
                    classification_summary=classification_summary,
                )
        except Exception:  # noqa: BLE001 — try retry or deterministic fallback
            continue

    return _deterministic_fallback_result(
        classification_summary=classification_summary,
    )


def run_financial_prioritization(
    claim_payload: str,
    classification_summary: str,
) -> tuple[PrioritizationResult, str]:
    ensure_groq_env()
    ensure_openai_env()

    def _build_crew(model: str | None) -> tuple[Crew, object]:
        llm = build_llm(model=model, temperature=0.15)

        agent = Agent(
            role="RCM financial prioritization analyst",
            goal=(
                "Quantify financial impact, urgency, and reversal likelihood; "
                "recommend the next best operational action for denial resolution."
            ),
            backstory=(
                "You combine actuarial thinking with operational RCM playbooks. "
                "You keep outputs numeric where requested and avoid PHI beyond "
                "what is provided."
            ),
            llm=llm,
        )

        task = Task(
            description=(
                "Prioritize the claim using the INPUT sections below. "
                "Your OUTPUT must be a separate JSON object — do not echo INPUT fields.\n\n"
                "### INPUT — CLAIM DATA\n"
                f"{claim_payload}\n\n"
                "### INPUT — CLASSIFICATION SUMMARY\n"
                f"{classification_summary}\n\n"
                "### OUTPUT — REQUIRED JSON KEYS ONLY\n"
                "- priority_score\n"
                "- estimated_recoverable_revenue\n"
                "- urgency\n"
                "- reversal_probability\n"
                "- recommended_action\n\n"
                "Rules:\n"
                "- Do not omit any required field\n"
                "- Do not return markdown\n"
                "- Do not include explanations outside JSON\n"
                "- Do not echo claim_id, payer, denial_code, billed_amount, or other claim fields\n"
                "- Do not include extra fields\n"
                "- priority_score must be between 0 and 100\n"
                "- urgency must be between 0 and 1\n"
                "- reversal_probability must be between 0 and 1\n"
                "- estimated_recoverable_revenue must be >= 0\n\n"
                "Example OUTPUT:\n"
                '{"priority_score":72.5,"estimated_recoverable_revenue":1840.0,'
                '"urgency":0.6,"reversal_probability":0.45,'
                '"recommended_action":"Submit corrected claim with supporting documentation."}'
            ),
            expected_output=(
                "A valid JSON object containing only: "
                "priority_score, estimated_recoverable_revenue, "
                "urgency, reversal_probability, recommended_action."
            ),
            output_pydantic=PrioritizationResult,
            agent=agent,
        )

        crew = Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
        )

        return crew, llm

    try:
        out, model_label = kickoff_crew_with_model_fallback(
            build=_build_crew, crew_name="prioritization"
        )
        structured = _crew_prioritization_result(out)
        if structured is not None:
            return structured, model_label
        raw = getattr(out, "raw", None) or str(out)
        result = _parse_prioritization(
            str(raw),
            classification_summary=classification_summary,
        )
        return result, model_label
    except (ValidationError, ValueError, Exception):  # noqa: BLE001 — crew/parse failures
        return _fallback_prioritization(claim_payload, classification_summary), "llm_fallback_json"
