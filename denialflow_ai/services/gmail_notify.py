"""Send appeal decision emails via Gmail API (OAuth user or service account)."""

from __future__ import annotations

import asyncio
import base64
import html
import json
import re
from datetime import UTC, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Literal

from denialflow_ai.core.config import Settings, get_settings
from denialflow_ai.core.logging import get_logger
from denialflow_ai.services.appeal_letter_context import sanitize_appeal_body

logger = get_logger(__name__)

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
AppealDecision = Literal["approved", "edited"]
CredentialsMode = Literal["service_account", "oauth_client", "unknown"]

_DECISION_LABEL = {
    "approved": "Approved",
    "edited": "Edited",
}


def parse_gmail_recipients(raw: str) -> list[str]:
    """Split GMAIL_TO on comma or semicolon."""
    if not raw.strip():
        return []
    parts = re.split(r"[,;]", raw)
    return [p.strip() for p in parts if p.strip()]


def load_credentials_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def detect_credentials_mode(data: dict[str, Any]) -> CredentialsMode:
    if data.get("type") == "service_account":
        return "service_account"
    if "installed" in data or "web" in data:
        return "oauth_client"
    return "unknown"


def validate_service_account_file(path: Path) -> str | None:
    """Return error message if SA credentials are invalid; None if OK."""
    if not path.is_file():
        return f"service_account_file_not_found: {path}"
    try:
        info = load_credentials_json(path)
    except (OSError, json.JSONDecodeError) as e:
        return f"service_account_file_unreadable: {e}"
    if info.get("type") != "service_account":
        return (
            "gmail_credentials_invalid_format: expected JSON with "
            '"type": "service_account"'
        )
    if not info.get("private_key") or not info.get("client_email"):
        return "gmail_credentials_invalid_format: missing private_key or client_email"
    return None


def _sender_address(settings: Settings) -> str:
    return settings.gmail_impersonate_user.strip()


def _email_context(
    *,
    appeal_id: str,
    claim_id: str,
    decision: AppealDecision,
    body_text: str,
    edit_reason: str | None,
) -> dict[str, str]:
    letter = sanitize_appeal_body(body_text)
    return {
        "appeal_id": appeal_id,
        "claim_id": claim_id,
        "decision_label": _DECISION_LABEL[decision],
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "edit_reason": (edit_reason or "").strip(),
        "letter": letter,
    }


def _build_email_plain(ctx: dict[str, str]) -> str:
    lines = [
        "DenialFlow — Appeal review notification",
        "",
        "Hello,",
        "",
        "A human review decision was recorded for the claim below.",
        "",
        f"  Claim: {ctx['claim_id']}",
        f"  Decision: {ctx['decision_label']}",
        f"  Appeal ID: {ctx['appeal_id']}",
        f"  Date (UTC): {ctx['timestamp']}",
    ]
    if ctx["edit_reason"]:
        lines.append(f"  Edit reason: {ctx['edit_reason']}")
    lines.extend(
        [
            "",
            "────────────────────────",
            "Final appeal letter text",
            "────────────────────────",
            "",
            ctx["letter"],
        ]
    )
    return "\n".join(lines)


def _build_email_html(ctx: dict[str, str]) -> str:
    edit_row = ""
    if ctx["edit_reason"]:
        edit_row = (
            "<tr>"
            '<td style="padding:6px 0;color:#64748b;width:140px;">Edit reason</td>'
            f"<td>{html.escape(ctx['edit_reason'])}</td>"
            "</tr>"
        )
    letter_html = html.escape(ctx["letter"])
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:Segoe UI,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:24px 16px;">
      <table role="presentation" width="600" style="max-width:600px;background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08);">
        <tr><td style="background:#1e3a5f;color:#ffffff;padding:20px 24px;font-size:18px;font-weight:600;">
          DenialFlow — Appeal review notification
        </td></tr>
        <tr><td style="padding:24px;color:#1a1a1a;font-size:14px;line-height:1.5;">
          <p style="margin:0 0 16px;">Hello,</p>
          <p style="margin:0 0 20px;">A human review decision was recorded for the claim below.</p>
          <table role="presentation" style="width:100%;margin:0 0 24px;font-size:14px;">
            <tr><td style="padding:6px 0;color:#64748b;width:140px;">Claim</td><td><strong>{html.escape(ctx['claim_id'])}</strong></td></tr>
            <tr><td style="padding:6px 0;color:#64748b;">Decision</td><td><strong>{html.escape(ctx['decision_label'])}</strong></td></tr>
            <tr><td style="padding:6px 0;color:#64748b;">Appeal ID</td><td>{html.escape(ctx['appeal_id'])}</td></tr>
            <tr><td style="padding:6px 0;color:#64748b;">Date (UTC)</td><td>{html.escape(ctx['timestamp'])}</td></tr>
            {edit_row}
          </table>
          <h2 style="margin:24px 0 12px;font-size:15px;color:#1e3a5f;border-bottom:1px solid #e2e8f0;padding-bottom:8px;">
            Final appeal letter text
          </h2>
          <pre style="margin:0;padding:16px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;white-space:pre-wrap;word-wrap:break-word;font-family:Consolas,monospace;font-size:13px;color:#334155;">{letter_html}</pre>
        </td></tr>
        <tr><td style="padding:16px 24px;background:#f8fafc;font-size:12px;color:#94a3b8;border-top:1px solid #e2e8f0;">
          Automated message from DenialFlow. Do not reply to this email.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _build_email_bodies(
    *,
    appeal_id: str,
    claim_id: str,
    decision: AppealDecision,
    body_text: str,
    edit_reason: str | None,
) -> tuple[str, str, str]:
    ctx = _email_context(
        appeal_id=appeal_id,
        claim_id=claim_id,
        decision=decision,
        body_text=body_text,
        edit_reason=edit_reason,
    )
    subject = f"[DenialFlow] Appeal {claim_id} — {ctx['decision_label']}"
    return subject, _build_email_html(ctx), _build_email_plain(ctx)


def _gmail_send_raw(
    creds: Any,
    *,
    subject: str,
    html_body: str,
    plain_body: str,
    recipients: list[str],
    sender: str,
) -> dict[str, Any]:
    from googleapiclient.discovery import build

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    message = MIMEMultipart("alternative")
    message.attach(MIMEText(plain_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))
    message["to"] = ", ".join(recipients)
    message["from"] = sender
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return {"to": recipients, "from": sender}


def _load_oauth_credentials(settings: Settings) -> Any:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token_path = settings.gmail_oauth_token_file
    if not token_path.is_file():
        raise FileNotFoundError(f"oauth_token_not_found: {token_path}")

    creds = Credentials.from_authorized_user_file(str(token_path), [GMAIL_SEND_SCOPE])
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
    if not creds.valid:
        raise ValueError("oauth_token_invalid: run python scripts/gmail_authorize.py")
    return creds


def _send_via_service_account(
    settings: Settings,
    *,
    subject: str,
    html_body: str,
    plain_body: str,
    recipients: list[str],
) -> dict[str, Any]:
    from google.oauth2 import service_account

    sa_path = settings.gmail_service_account_file
    creds = service_account.Credentials.from_service_account_file(
        str(sa_path),
        scopes=[GMAIL_SEND_SCOPE],
    )
    delegated = creds.with_subject(_sender_address(settings))
    sender = _sender_address(settings)
    return _gmail_send_raw(
        delegated,
        subject=subject,
        html_body=html_body,
        plain_body=plain_body,
        recipients=recipients,
        sender=sender,
    )


def _send_via_oauth(
    settings: Settings,
    *,
    subject: str,
    html_body: str,
    plain_body: str,
    recipients: list[str],
) -> dict[str, Any]:
    creds = _load_oauth_credentials(settings)
    sender = _sender_address(settings)
    return _gmail_send_raw(
        creds,
        subject=subject,
        html_body=html_body,
        plain_body=plain_body,
        recipients=recipients,
        sender=sender,
    )


def _send_gmail_sync(
    settings: Settings,
    *,
    subject: str,
    html_body: str,
    plain_body: str,
    recipients: list[str],
    mode: CredentialsMode,
) -> dict[str, Any]:
    if mode == "oauth_client":
        return _send_via_oauth(
            settings,
            subject=subject,
            html_body=html_body,
            plain_body=plain_body,
            recipients=recipients,
        )
    return _send_via_service_account(
        settings,
        subject=subject,
        html_body=html_body,
        plain_body=plain_body,
        recipients=recipients,
    )


def _resolve_credentials(settings: Settings) -> tuple[CredentialsMode | None, str | None]:
    """Return (mode, error). Exactly one of mode or error is non-None on failure paths."""
    cred_path = settings.gmail_service_account_file
    if not cred_path.is_file():
        return None, f"credentials_file_not_found: {cred_path}"
    try:
        data = load_credentials_json(cred_path)
    except (OSError, json.JSONDecodeError) as e:
        return None, f"credentials_file_unreadable: {e}"
    mode = detect_credentials_mode(data)
    if mode == "unknown":
        return None, "gmail_credentials_unknown_format"
    return mode, None


def _skip_reason(settings: Settings) -> str | None:
    if not settings.gmail_notify_enabled:
        return "disabled"
    if not _sender_address(settings):
        return "missing_sender"
    recipients = parse_gmail_recipients(settings.gmail_to)
    if not recipients:
        return "missing_recipients"

    mode, err = _resolve_credentials(settings)
    if err:
        return err

    if mode == "service_account":
        return validate_service_account_file(settings.gmail_service_account_file)

    if not settings.gmail_oauth_token_file.is_file():
        return (
            "oauth_token_missing: run once: python scripts/gmail_authorize.py "
            f"(sign in as {_sender_address(settings)})"
        )
    return None


def send_appeal_decision_email_sync(
    *,
    appeal_id: str,
    claim_id: str,
    decision: AppealDecision,
    body_text: str,
    edit_reason: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """
    Send email with approved/edited appeal text. Returns metadata dict.
    Raises on API errors when configured to send; returns skipped dict otherwise.
    """
    cfg = settings or get_settings()
    reason = _skip_reason(cfg)
    if reason:
        logger.info("gmail_notify_skipped", reason=reason, appeal_id=appeal_id)
        return {"sent": False, "reason": reason}

    if not (body_text or "").strip():
        logger.info("gmail_notify_skipped", reason="empty_body", appeal_id=appeal_id)
        return {"sent": False, "reason": "empty_body"}

    mode, cred_err = _resolve_credentials(cfg)
    if cred_err or mode is None:
        logger.info("gmail_notify_skipped", reason=cred_err, appeal_id=appeal_id)
        return {"sent": False, "reason": cred_err or "gmail_credentials_unknown_format"}

    recipients = parse_gmail_recipients(cfg.gmail_to)
    subject, html_body, plain_body = _build_email_bodies(
        appeal_id=appeal_id,
        claim_id=claim_id,
        decision=decision,
        body_text=body_text,
        edit_reason=edit_reason,
    )
    meta = _send_gmail_sync(
        cfg,
        subject=subject,
        html_body=html_body,
        plain_body=plain_body,
        recipients=recipients,
        mode=mode,
    )
    logger.info(
        "gmail_notify_sent",
        appeal_id=appeal_id,
        claim_id=claim_id,
        decision=decision,
        auth_mode=mode,
        to=meta["to"],
    )
    return {"sent": True, "decision": decision, "auth_mode": mode, **meta}


async def send_appeal_decision_email(
    *,
    appeal_id: str,
    claim_id: str,
    decision: AppealDecision,
    body_text: str,
    edit_reason: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        send_appeal_decision_email_sync,
        appeal_id=appeal_id,
        claim_id=claim_id,
        decision=decision,
        body_text=body_text,
        edit_reason=edit_reason,
        settings=settings,
    )
