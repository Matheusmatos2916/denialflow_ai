"""Unit tests for Gmail appeal notification helpers."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from denialflow_ai.core.config import Settings
from denialflow_ai.services import gmail_notify


def test_parse_gmail_recipients() -> None:
    assert gmail_notify.parse_gmail_recipients("a@x.com, b@y.com") == [
        "a@x.com",
        "b@y.com",
    ]
    assert gmail_notify.parse_gmail_recipients("a@x.com;b@y.com") == ["a@x.com", "b@y.com"]
    assert gmail_notify.parse_gmail_recipients("") == []


def test_build_email_bodies_includes_edit_reason() -> None:
    subject, html_body, plain_body = gmail_notify._build_email_bodies(
        appeal_id="app-1",
        claim_id="CLM-1",
        decision="edited",
        body_text="Dear payer,\nAppeal text.",
        edit_reason="Tone adjustment",
    )
    assert "CLM-1" in subject
    assert "Edited" in subject
    assert "Edit reason: Tone adjustment" in plain_body
    assert "Dear payer" in plain_body
    assert "Edit reason" in html_body


def test_build_email_html_structure() -> None:
    _, html_body, plain_body = gmail_notify._build_email_bodies(
        appeal_id="app-1",
        claim_id="CLM-1",
        decision="approved",
        body_text="Dear payer,\nAppeal text.",
        edit_reason=None,
    )
    assert "<!DOCTYPE html>" in html_body
    assert 'lang="en"' in html_body
    assert "Final appeal letter text" in html_body
    assert "Final appeal letter text" in plain_body
    assert "Hello," in html_body
    assert "Decision" in html_body
    assert "—" * 40 not in plain_body


def test_build_email_escapes_html_in_letter() -> None:
    _, html_body, _plain = gmail_notify._build_email_bodies(
        appeal_id="app-1",
        claim_id="CLM-1",
        decision="approved",
        body_text="<script>alert(1)</script>",
        edit_reason=None,
    )
    assert "<script>" not in html_body
    assert "&lt;script&gt;" in html_body


def test_detect_oauth_client_mode(tmp_path: Path) -> None:
    path = tmp_path / "web.json"
    path.write_text(
        json.dumps({"web": {"client_id": "x", "client_secret": "y"}}),
        encoding="utf-8",
    )
    data = gmail_notify.load_credentials_json(path)
    assert gmail_notify.detect_credentials_mode(data) == "oauth_client"


def test_validate_service_account_rejects_oauth_web(tmp_path: Path) -> None:
    path = tmp_path / "web.json"
    path.write_text(
        json.dumps({"web": {"client_id": "x", "client_secret": "y"}}),
        encoding="utf-8",
    )
    err = gmail_notify.validate_service_account_file(path)
    assert err is not None
    assert "service_account" in err


def test_oauth_skipped_without_token(tmp_path: Path) -> None:
    client = tmp_path / "client.json"
    client.write_text(
        json.dumps({"web": {"client_id": "x", "client_secret": "y"}}),
        encoding="utf-8",
    )
    settings = Settings(
        GMAIL_NOTIFY_ENABLED=True,
        GMAIL_SERVICE_ACCOUNT_FILE=client,
        GMAIL_OAUTH_TOKEN_FILE=tmp_path / "missing_token.json",
        GMAIL_IMPERSONATE_USER="testescursor46@gmail.com",
        GMAIL_TO="testescursor46@gmail.com",
    )
    result = gmail_notify.send_appeal_decision_email_sync(
        appeal_id="a1",
        claim_id="C1",
        decision="approved",
        body_text="Body",
        settings=settings,
    )
    assert result["sent"] is False
    assert "oauth_token_missing" in result["reason"]


def test_validate_service_account_accepts_sa(tmp_path: Path) -> None:
    path = tmp_path / "sa.json"
    path.write_text(
        json.dumps(
            {
                "type": "service_account",
                "private_key": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n",
                "client_email": "svc@proj.iam.gserviceaccount.com",
            }
        ),
        encoding="utf-8",
    )
    assert gmail_notify.validate_service_account_file(path) is None


def test_send_skipped_when_disabled() -> None:
    settings = Settings(
        GMAIL_NOTIFY_ENABLED=False,
        GMAIL_IMPERSONATE_USER="sender@test.com",
        GMAIL_TO="rcm@test.com",
    )
    result = gmail_notify.send_appeal_decision_email_sync(
        appeal_id="a1",
        claim_id="C1",
        decision="approved",
        body_text="Appeal body",
        settings=settings,
    )
    assert result["sent"] is False
    assert result["reason"] == "disabled"


@patch("denialflow_ai.services.gmail_notify._send_gmail_sync")
def test_send_calls_gmail_when_enabled(mock_send: MagicMock, tmp_path: Path) -> None:
    sa_path = tmp_path / "sa.json"
    sa_path.write_text(
        json.dumps(
            {
                "type": "service_account",
                "private_key": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n",
                "client_email": "svc@proj.iam.gserviceaccount.com",
            }
        ),
        encoding="utf-8",
    )
    mock_send.return_value = {"to": ["rcm@test.com"], "from": "sender@test.com"}
    settings = Settings(
        GMAIL_NOTIFY_ENABLED=True,
        GMAIL_SERVICE_ACCOUNT_FILE=sa_path,
        GMAIL_IMPERSONATE_USER="sender@test.com",
        GMAIL_TO="rcm@test.com",
    )
    result = gmail_notify.send_appeal_decision_email_sync(
        appeal_id="a1",
        claim_id="C1",
        decision="approved",
        body_text="Final appeal letter.",
        settings=settings,
    )
    assert result["sent"] is True
    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args.kwargs
    assert "C1" in call_kwargs["subject"]
    assert "Final appeal letter." in call_kwargs["plain_body"]
