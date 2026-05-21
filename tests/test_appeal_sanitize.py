"""Tests for appeal letter body sanitization."""

from __future__ import annotations

from denialflow_ai.services.appeal_letter_context import (
    sanitize_appeal_body,
    strip_bracket_placeholder_lines,
    strip_doc_id_citations,
)


def test_strip_doc_id_citations() -> None:
    raw = (
        "Per policy (doc_id: archived_appeal_df_arc_0208:0) we request review. "
        "Also see doc_id=apex_health:0 for rules."
    )
    out = strip_doc_id_citations(raw)
    assert "doc_id" not in out
    assert "we request review" in out


def test_strip_bracket_placeholder_lines() -> None:
    raw = "[Your Company Logo]\n[Your Company Name]\n\nDear Payer,\nBody."
    out = strip_bracket_placeholder_lines(raw)
    assert "[Your Company" not in out
    assert "Dear Payer" in out


def test_sanitize_preserves_appeal_body() -> None:
    raw = """CONFIDENCE: 0.82
[Your Company Name]
Dear Horizon National,

Appeal body here (doc_id: archived_appeal_df_arc_0142:0).
"""
    out = sanitize_appeal_body(raw)
    assert "CONFIDENCE" not in out
    assert "[Your Company Name]" not in out
    assert "doc_id" not in out
    assert "Dear Horizon National" in out
    assert "Appeal body here" in out
