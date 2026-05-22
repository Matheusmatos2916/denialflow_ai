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
from denialflow_ai.services.appeal_letter_context import (
    has_bracket_placeholders,
    strip_confidence_line,
)
from denialflow_ai.tools.rag_tool import PolicyAppealSearchTool

_LETTERHEAD_RULES = """
LETTERHEAD / CADASTRO rules for the appeal letter:
- Use the LETTERHEAD block values exactly in the letter header and signature block.
- NEVER use bracket placeholders ([Your Company Name], [Claim Number], [Payer Name], etc.).
- Do NOT open the letter with a template block of bracket fields or [Your Company Logo] lines.
- Use claim_id from the CLAIM section as the claim number in the subject line and body.
- Use payer_name from LETTERHEAD as the payer addressee name; use payer address fields for the mailing block.
- If a LETTERHEAD field is empty, omit that line — do not invent or use placeholders.
- Use letter_date from LETTERHEAD as the date on the letter.
- NEVER include doc_id, (doc_id: ...), Chroma IDs, or internal archive keys in the final letter.
- Cite policies by title only (e.g. "Apex Health Authorization Grid"), not by doc_id.
"""

_APPEAL_DRAFT_RULES = """
Final appeal letter rules:
- Write the full payer-facing letter in English using real LETTERHEAD values (provider, payer, signer).
- Start with the date and addressee using payer_name and payer address from LETTERHEAD, then "Re: ...".
- Do not copy research-note formatting or internal doc_id references into the letter.
"""


def parse_appeal_confidence(text: str) -> tuple[str, float]:
    """Parse confidence from CONFIDENCE: line and return appeal text without that line."""
    confidence = 0.55
    for line in text.splitlines():
        if line.strip().upper().startswith("CONFIDENCE:"):
            try:
                part = line.split(":", 1)[1].strip().split()[0]
                confidence = float(part)
            except Exception:  # noqa: BLE001
                confidence = 0.55
            break
    confidence = max(0.0, min(1.0, confidence))
    return strip_confidence_line(text), confidence


def _letterhead_section(letter_context: str) -> str:
    if not letter_context.strip():
        return "LETTERHEAD / CADASTRO:\n(no letterhead data provided)\n"
    return f"LETTERHEAD / CADASTRO:\n{letter_context.strip()}\n"


def run_research_and_appeal(
    claim_payload: str,
    classification_summary: str,
    prioritization_summary: str,
    letter_context: str = "",
) -> tuple[str, float, str]:
    """
    Crew C: research (tool) + appeal drafting.
    Returns (appeal_markdown, confidence_0_1, model_label).
    """
    ensure_groq_env()
    ensure_openai_env()
    tool = PolicyAppealSearchTool()
    letterhead = _letterhead_section(letter_context)

    def _build_crew(model: str | None) -> tuple[Crew, object]:
        llm = build_llm(model=model, temperature=0.25)
        researcher = Agent(
            role="Internal policy and precedent researcher",
            goal=(
                "Use the policy/appeal search tool to gather relevant internal snippets that support "
                "an appeal strategy."
            ),
            backstory=(
                "You cite doc_ids only in internal research notes for traceability. "
                "You never put doc_ids in the final appeal letter. You do not fabricate citations."
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
                "explicit requests for reconsideration. You use real LETTERHEAD names and addresses "
                "only — never bracket placeholders or internal doc_id strings."
            ),
            llm=llm,
            allow_delegation=False,
        )
        research_task = Task(
            description=(
                "Research internal precedents for this denial.\n\n"
                f"CLAIM:\n{claim_payload}\n\n"
                f"{letterhead}\n"
                f"CLASSIFICATION:\n{classification_summary}\n\n"
                f"PRIORITIZATION:\n{prioritization_summary}\n\n"
                "Call the tool with a focused question including denial code/reason. "
                "Summarize retrieved hits with doc_ids and why they matter (internal notes only)."
            ),
            expected_output="Internal research notes with doc_ids and appeal angles (not the final letter).",
            agent=researcher,
        )
        appeal_task = Task(
            description=(
                "Using the research notes and claim facts, draft the payer-facing appeal letter.\n\n"
                f"{letterhead}\n"
                f"{_LETTERHEAD_RULES}\n"
                f"{_APPEAL_DRAFT_RULES}\n"
                "End with a line exactly like: CONFIDENCE: 0.## (two decimals) estimating appeal "
                "strength given evidence quality."
            ),
            expected_output="A complete payer-facing appeal draft (no doc_ids, no bracket placeholders) plus confidence line.",
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
        out, model_label = kickoff_crew_with_model_fallback(build=_build_crew, crew_name="appeal")
        text = getattr(out, "raw", None) or str(out)
        appeal = str(text)
    except Exception:
        client = get_llm_client()
        sys = (
            "You draft professional healthcare payer appeal letters in enterprise RCM tone. "
            "Never use bracket placeholders like [Your Company Name]. "
            "Never include doc_id or (doc_id: ...) in the letter. "
            "Use only the LETTERHEAD and CLAIM data provided. "
            "End with a line exactly like: CONFIDENCE: 0.## (two decimals)."
        )
        user = (
            f"CLAIM:\n{claim_payload}\n\n"
            f"{letterhead}\n"
            f"{_LETTERHEAD_RULES}\n"
            f"CLASSIFICATION:\n{classification_summary}\n\n"
            f"PRIORITIZATION:\n{prioritization_summary}"
        )
        appeal, model_label = asyncio.run(
            client.appeal_text(system=sys, user=user, allow_fallback=True)
        )
    appeal, confidence = parse_appeal_confidence(appeal)
    if has_bracket_placeholders(appeal):
        from denialflow_ai.core.logging import get_logger

        get_logger(__name__).warning("appeal_draft_has_bracket_placeholders", model=model_label)
    return appeal, confidence, model_label
