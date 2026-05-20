from __future__ import annotations

import asyncio

from crewai import Agent, Crew, Process, Task

from denialflow_ai.crews.llm_config import (
    build_llm,
    ensure_groq_env,
    ensure_openai_env,
    kickoff_crew_with_model_fallback,
)
from denialflow_ai.llm import get_llm_client
from denialflow_ai.schemas import PrioritizationResult


def _parse_prioritization(raw: str) -> PrioritizationResult:
    return get_llm_client().parse_json_blob(raw, PrioritizationResult)


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
                "Quantify financial impact, urgency, and reversal likelihood; recommend the next "
                "best operational action for denial resolution."
            ),
            backstory=(
                "You combine actuarial thinking with operational RCM playbooks. You keep outputs "
                "numeric where requested and avoid PHI beyond what is provided."
            ),
            llm=llm,
        )
        task = Task(
            description=(
                "Prioritize the claim using the record and the AI classification summary.\n\n"
                f"CLAIM:\n{claim_payload}\n\nCLASSIFICATION_SUMMARY:\n{classification_summary}\n\n"
                "Return ONLY JSON with keys: "
                "priority_score (0-100), estimated_recoverable_revenue (USD float), "
                "urgency (0-1), reversal_probability (0-1), recommended_action (string)."
            ),
            expected_output="JSON object with numeric scores and recommended_action.",
            agent=agent,
        )
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
        return crew, llm

    try:
        out, model_label = kickoff_crew_with_model_fallback(build=_build_crew)
        raw = getattr(out, "raw", None) or str(out)
        result = _parse_prioritization(str(raw))
        return result, model_label
    except Exception:
        oai = get_llm_client()
        sys = "You prioritize denied healthcare claims for collections. Output strict JSON."
        user = f"{claim_payload}\n\n{classification_summary}"
        data = asyncio.run(oai.chat_json(system=sys, user=user, allow_fallback=True))
        result = oai.parse_pydantic(data, PrioritizationResult)
        return result, "llm_fallback_json"
