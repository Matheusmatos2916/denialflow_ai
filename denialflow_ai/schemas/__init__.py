from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

DenialCategory = Literal[
    "coding_issue",
    "authorization",
    "duplicate_claim",
    "medical_necessity",
    "incomplete_documentation",
]


class ClaimStatus(StrEnum):
    PENDING = "pending"
    CLASSIFIED = "classified"
    PRIORITIZED = "prioritized"
    RETRIEVED = "retrieved"
    DRAFT_APPEAL = "draft_appeal"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"
    FAILED = "failed"


class AppealStatus(StrEnum):
    DRAFT = "draft"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"


class WorkflowRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ClaimRow(BaseModel):
    """Single row from CSV upload — validated before persistence."""

    claim_id: str = Field(..., min_length=3, max_length=64)
    payer: str = Field(default="", max_length=128)
    denial_code: str = Field(default="", max_length=32)
    denial_reason_text: str = Field(default="", max_length=4000)
    billed_amount: float = Field(default=0.0, ge=0)
    allowed_amount: float = Field(default=0.0, ge=0)
    patient_balance: float = Field(default=0.0, ge=0)
    aging_days: int = Field(default=0, ge=0)
    specialty: str = Field(default="", max_length=128)
    cpt_codes: str = Field(default="", max_length=512)
    icd10_codes: str = Field(default="", max_length=512)
    service_date: str = Field(default="", max_length=32)
    remark_codes: str = Field(default="", max_length=256)
    # Letterhead / cadastro (optional; recommended for appeal drafts)
    provider_name: str = Field(default="", max_length=256)
    provider_address: str = Field(default="", max_length=512)
    provider_city: str = Field(default="", max_length=128)
    provider_state: str = Field(default="", max_length=32)
    provider_zip: str = Field(default="", max_length=16)
    signer_name: str = Field(default="", max_length=128)
    signer_title: str = Field(default="", max_length=128)
    provider_npi: str = Field(default="", max_length=32)
    payer_address: str = Field(default="", max_length=512)
    payer_city: str = Field(default="", max_length=128)
    payer_state: str = Field(default="", max_length=32)
    payer_zip: str = Field(default="", max_length=16)
    letter_date: str = Field(default="", max_length=32)

    @field_validator("claim_id")
    @classmethod
    def strip_claim(cls, v: str) -> str:
        return v.strip()


class AppealLetterContext(BaseModel):
    """Provider/payer letterhead fields passed to appeal drafting."""

    provider_name: str = ""
    provider_address: str = ""
    provider_city: str = ""
    provider_state: str = ""
    provider_zip: str = ""
    signer_name: str = ""
    signer_title: str = ""
    provider_npi: str = ""
    payer_name: str = ""
    payer_address: str = ""
    payer_city: str = ""
    payer_state: str = ""
    payer_zip: str = ""
    letter_date: str = ""


class ClassificationResult(BaseModel):
    category: DenialCategory
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str = Field(min_length=10, max_length=8000)


class PrioritizationResult(BaseModel):
    priority_score: float = Field(ge=0.0, le=100.0)
    estimated_recoverable_revenue: float = Field(ge=0.0)
    urgency: float = Field(ge=0.0, le=1.0)
    reversal_probability: float = Field(ge=0.0, le=1.0)
    recommended_action: str = Field(min_length=5, max_length=2000)


class RagHit(BaseModel):
    doc_id: str
    title: str
    snippet: str
    score: float


class RagRetrievalResult(BaseModel):
    query: str
    hits: list[RagHit]


class AppealDraft(BaseModel):
    appeal_text: str = Field(min_length=50, max_length=20000)
    confidence: float = Field(ge=0.0, le=1.0)
    cited_doc_ids: list[str] = Field(default_factory=list)


class UploadValidationError(BaseModel):
    row_index: int
    field: str | None = None
    message: str


class ClaimsUploadResponse(BaseModel):
    batch_id: str
    filename: str
    accepted_rows: int
    errors: list[UploadValidationError]


class ParsedCsv(BaseModel):
    filename: str
    rows: list[dict[str, Any]]
    errors: list[UploadValidationError]


class WorkflowRunRequest(BaseModel):
    batch_id: str
    max_claims: int = Field(default=25, ge=1, le=200)


class WorkflowRunResponse(BaseModel):
    run_id: str
    batch_id: str
    status: WorkflowRunStatus


class AppealReviewEditRequest(BaseModel):
    final_text: str = Field(min_length=20, max_length=20000)
    reason: str = Field(default="", max_length=2000)


class AppealRejectRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


ReviewRecommendedAction = Literal["approve", "edit", "reject"]


class AppealAIReview(BaseModel):
    """Structured second opinion from Bedrock on a CrewAI/Groq appeal draft."""

    overall_score: float = Field(ge=0.0, le=1.0)
    ready_to_submit: bool
    issues: list[str] = Field(default_factory=list)
    missing_elements: list[str] = Field(default_factory=list)
    citation_check: str = Field(min_length=1, max_length=4000)
    suggested_edits: list[str] = Field(default_factory=list)
    recommended_action: ReviewRecommendedAction
    summary: str = Field(min_length=10, max_length=8000)
    analyzed_crewai_model: str = Field(default="", max_length=256)
    agrees_with_crewai_confidence: bool | None = None
    model_used: str = Field(default="", max_length=256)


class DashboardMetrics(BaseModel):
    total_claims: int
    denial_rate_proxy: float
    recoverable_revenue_sum: float
    awaiting_review: int
    avg_run_duration_ms: float | None
    runs_last_24h: int
    priority_queue_top: list[dict[str, Any]]


class ClaimSummary(BaseModel):
    internal_id: str
    claim_id: str
    payer: str
    denial_reason: str
    ai_category: str | None
    classification_confidence: float | None
    priority_score: float | None
    recoverable_amount: float | None
    recommended_action: str | None
    status: str
    appeal_id: str | None = None


class AppealDetail(BaseModel):
    id: str
    claim_internal_id: str
    claim_id: str
    status: str
    draft_text: str
    final_text: str | None
    confidence: float
    citations: list[RagHit]
    classification: ClassificationResult | None = None
    prioritization: PrioritizationResult | None = None
    model_used: str
    created_at: str
    updated_at: str
    ai_review: AppealAIReview | None = None
    ai_review_at: str | None = None


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
