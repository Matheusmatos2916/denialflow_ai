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
from denialflow_ai.llm import get_llm_client
from denialflow_ai.rag import get_classification_cache
from denialflow_ai.schemas import ClassificationResult


def _parse_classification(raw: str) -> ClassificationResult:
    return get_llm_client().parse_json_blob(raw, ClassificationResult)


def _deterministic_classification(payload: str) -> ClassificationResult:
    """Keep a malformed model response from terminating the whole workflow."""
    text = payload.lower()
    rules: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("authorization", ("authorization", "prior auth", "preauthorization", "referral")),
        ("duplicate_claim", ("duplicate", "duplicated", "same claim")),
        ("coding_issue", ("coding", "cpt", "hcpcs", "modifier", "unbundl")),
        ("medical_necessity", ("medical necessity", "not medically necessary")),
        ("incomplete_documentation", ("documentation", "operative report", "missing record")),
    )
    for category, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return ClassificationResult(
                category=category,
                confidence=0.35,
                explanation=(
                    "Deterministic fallback based on denial text; model output was incomplete. "
                    f"Matched category signal: {category}."
                ),
            )
    return ClassificationResult(
        category="incomplete_documentation",
        confidence=0.2,
        explanation=(
            "Deterministic fallback used because the model response was incomplete; "
            "manual classification review is required."
        ),
    )


def _coerce_classification(data: dict[str, Any], payload: str) -> ClassificationResult:
    try:
        return ClassificationResult.model_validate(data)
    except ValidationError:
        return _deterministic_classification(payload)


def run_denial_classification(claim_payload: str) -> tuple[ClassificationResult, str]:
    """Run classification via CrewAI with JSON parsing; falls back to direct OpenAI JSON."""
    ensure_groq_env()
    ensure_openai_env()
    cache = get_classification_cache()
    cached = cache.get(claim_payload)
    if cached:
        return ClassificationResult.model_validate(cached), "cache"

    def _build_crew(model: str | None) -> tuple[Crew, object]:
        llm = build_llm(model=model, temperature=0.1)
        agent = Agent(
            role="Denial classification specialist",
            goal=(
                "Map payer denial narratives to exactly one canonical category with calibrated "
                "confidence and a concise, auditable explanation."
            ),
            backstory=(
                "You are a senior US healthcare revenue cycle analyst. You only use the claim "
                "facts provided; you do not invent policy citations."
            ),
            llm=llm,
        )
        task = Task(
            description=(
                "Classify the following claim/denial record.\n\n"
                f"{claim_payload}\n\n"
                "Return ONLY a JSON object with keys: "
                "category (one of: coding_issue, authorization, duplicate_claim, "
                "medical_necessity, incomplete_documentation), "
                "confidence (0-1 float), explanation (string)."
            ),
            expected_output="A single JSON object with category, confidence, explanation.",
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
            build=_build_crew, crew_name="classification"
        )
        raw = getattr(out, "raw", None) or str(out)
        result = _parse_classification(str(raw))
        cache.set(claim_payload, result.model_dump())
        return result, model_label
    except Exception:
        oai = get_llm_client()
        sys = (
            "You classify healthcare claim denials. Output strict JSON matching the schema."
        )
        user = f"Claim record:\n{claim_payload}"
        data = asyncio.run(oai.chat_json(system=sys, user=user, allow_fallback=True))
        result = _coerce_classification(data, claim_payload)
        cache.set(claim_payload, result.model_dump())
        return result, "llm_fallback_json"
