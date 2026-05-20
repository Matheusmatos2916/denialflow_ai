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
from denialflow_ai.tools.rag_tool import PolicyAppealSearchTool


def run_research_and_appeal(
    claim_payload: str,
    classification_summary: str,
    prioritization_summary: str,
) -> tuple[str, float, str]:
    """
    Crew C: research (tool) + appeal drafting.
    Returns (appeal_markdown, confidence_0_1, model_label).
    """
    ensure_groq_env()
    ensure_openai_env()
    tool = PolicyAppealSearchTool()

    def _build_crew(model: str | None) -> tuple[Crew, object]:
        llm = build_llm(model=model, temperature=0.25)
        researcher = Agent(
            role="Internal policy and precedent researcher",
            goal=(
                "Use the policy/appeal search tool to gather relevant internal snippets that support "
                "an appeal strategy."
            ),
            backstory=(
                "You are meticulous about citing retrieved document titles/ids in your notes. "
                "You do not fabricate citations."
            ),
            tools=[tool],
            llm=llm,
            allow_delegation=False,
        )
        writer = Agent(
            role="Appeal letter author",
            goal=(
                "Draft a professional payer appeal suitable for human review, grounded in research "
                "notes and claim facts."
            ),
            backstory=(
                "You write in enterprise RCM tone: clear, respectful, structured sections, and "
                "explicit requests for reconsideration."
            ),
            llm=llm,
            allow_delegation=False,
        )
        research_task = Task(
            description=(
                "Research internal precedents for this denial.\n\n"
                f"CLAIM:\n{claim_payload}\n\n"
                f"CLASSIFICATION:\n{classification_summary}\n\n"
                f"PRIORITIZATION:\n{prioritization_summary}\n\n"
                "Call the tool with a focused question including denial code/reason. "
                "Summarize retrieved hits with doc_ids and why they matter."
            ),
            expected_output="Research notes with doc references and appeal angles.",
            agent=researcher,
        )
        appeal_task = Task(
            description=(
                "Using the research notes and claim facts, draft the appeal letter.\n\n"
                "End with a line exactly like: CONFIDENCE: 0.## (two decimals) estimating appeal "
                "strength given evidence quality."
            ),
            expected_output="A complete appeal draft plus confidence line.",
            agent=writer,
            context=[research_task],
        )
        crew = Crew(
            agents=[researcher, writer],
            tasks=[research_task, appeal_task],
            process=Process.sequential,
            verbose=False,
        )
        return crew, llm

    try:
        out, model_label = kickoff_crew_with_model_fallback(build=_build_crew)
        text = getattr(out, "raw", None) or str(out)
        appeal = str(text)
    except Exception:
        client = get_llm_client()
        sys = (
            "You draft professional healthcare payer appeal letters in enterprise RCM tone. "
            "End with a line exactly like: CONFIDENCE: 0.## (two decimals)."
        )
        user = (
            f"CLAIM:\n{claim_payload}\n\n"
            f"CLASSIFICATION:\n{classification_summary}\n\n"
            f"PRIORITIZATION:\n{prioritization_summary}"
        )
        appeal, model_label = asyncio.run(
            client.appeal_text(system=sys, user=user, allow_fallback=True)
        )
    confidence = 0.55
    for line in appeal.splitlines():
        if line.strip().upper().startswith("CONFIDENCE:"):
            try:
                part = line.split(":", 1)[1].strip().split()[0]
                confidence = float(part)
            except Exception:  # noqa: BLE001
                confidence = 0.55
            break
    confidence = max(0.0, min(1.0, confidence))
    return appeal, confidence, model_label
