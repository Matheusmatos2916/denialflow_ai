from __future__ import annotations

from crewai.tools import BaseTool

from denialflow_ai.rag.sync_search import retrieve_sync


class PolicyAppealSearchTool(BaseTool):
    name: str = "policy_and_appeal_search"
    description: str = (
        "Search internal payer policies and archived appeals/snippets relevant to a denial. "
        "Input: a concise natural-language question including denial code/reason context."
    )

    def _run(self, question: str) -> str:  # type: ignore[override]
        res = retrieve_sync(question, top_k=6)
        return res.model_dump_json()
