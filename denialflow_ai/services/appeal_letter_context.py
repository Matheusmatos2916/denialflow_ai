from __future__ import annotations

import re
from datetime import date
from typing import Any

from denialflow_ai.schemas import AppealLetterContext

_BRACKET_PLACEHOLDER = re.compile(r"\[[^\]]{2,80}\]")
_DOC_ID_PAREN = re.compile(r"\s*\(doc_id:\s*[^)]+\)", re.IGNORECASE)
_DOC_ID_INLINE = re.compile(r"\s*doc_id=[^\s,;)]+", re.IGNORECASE)


def _s(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def build_letter_context(row: dict[str, Any]) -> AppealLetterContext:
    """Build letterhead context from a claim DB row or CSV dict."""
    letter_date = _s(row.get("letter_date"))
    if not letter_date:
        letter_date = date.today().isoformat()
    return AppealLetterContext(
        provider_name=_s(row.get("provider_name")),
        provider_address=_s(row.get("provider_address")),
        provider_city=_s(row.get("provider_city")),
        provider_state=_s(row.get("provider_state")),
        provider_zip=_s(row.get("provider_zip")),
        signer_name=_s(row.get("signer_name")),
        signer_title=_s(row.get("signer_title")),
        provider_npi=_s(row.get("provider_npi")),
        payer_name=_s(row.get("payer")),
        payer_address=_s(row.get("payer_address")),
        payer_city=_s(row.get("payer_city")),
        payer_state=_s(row.get("payer_state")),
        payer_zip=_s(row.get("payer_zip")),
        letter_date=letter_date,
    )


def _city_state_zip(city: str, state: str, zip_code: str) -> str:
    parts = [p for p in (city, state) if p]
    line = ", ".join(parts) if parts else ""
    if zip_code:
        line = f"{line} {zip_code}".strip() if line else zip_code
    return line


def format_letter_context_block(ctx: AppealLetterContext) -> str:
    """Format letterhead for LLM prompts (English labels, values from CSV)."""
    lines = [
        f"letter_date: {ctx.letter_date}",
        f"provider_name: {ctx.provider_name}",
        f"provider_address: {ctx.provider_address}",
        f"provider_city_state_zip: {_city_state_zip(ctx.provider_city, ctx.provider_state, ctx.provider_zip)}",
        f"provider_npi: {ctx.provider_npi}",
        f"signer_name: {ctx.signer_name}",
        f"signer_title: {ctx.signer_title}",
        f"payer_name: {ctx.payer_name}",
        f"payer_address: {ctx.payer_address}",
        f"payer_city_state_zip: {_city_state_zip(ctx.payer_city, ctx.payer_state, ctx.payer_zip)}",
    ]
    return "\n".join(lines)


def has_bracket_placeholders(text: str) -> bool:
    """True if appeal text still contains [placeholder] style tokens."""
    return bool(_BRACKET_PLACEHOLDER.search(text))


def strip_confidence_line(text: str) -> str:
    """Remove CrewAI trailing CONFIDENCE: line from appeal body (score stored separately)."""
    lines: list[str] = []
    for line in text.splitlines():
        if line.strip().upper().startswith("CONFIDENCE:"):
            continue
        lines.append(line)
    return "\n".join(lines).rstrip()


def strip_doc_id_citations(text: str) -> str:
    """Remove internal RAG doc_id references from appeal letter prose."""
    out = _DOC_ID_PAREN.sub("", text)
    return _DOC_ID_INLINE.sub("", out)


def strip_bracket_placeholder_lines(text: str) -> str:
    """Remove lines that are only [placeholder] template tokens."""
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and (
            _BRACKET_PLACEHOLDER.fullmatch(stripped)
            or (stripped.startswith("[") and stripped.endswith("]") and _BRACKET_PLACEHOLDER.search(stripped))
        ):
            continue
        kept.append(line)
    return "\n".join(kept)


def _collapse_leading_blank_lines(text: str) -> str:
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    return "\n".join(lines).rstrip()


def sanitize_appeal_body(text: str) -> str:
    """Clean appeal text for storage, API display, and outbound email."""
    cleaned = strip_confidence_line(text or "")
    cleaned = strip_doc_id_citations(cleaned)
    cleaned = strip_bracket_placeholder_lines(cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return _collapse_leading_blank_lines(cleaned)
