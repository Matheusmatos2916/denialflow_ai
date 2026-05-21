"""
One-time OAuth setup for personal Gmail (testescursor46@gmail.com).

1. In Google Cloud Console → APIs → Gmail API (enabled).
2. OAuth client (Web) → Authorized redirect URIs must include:
   http://localhost:8080/
   http://127.0.0.1:8080/
3. Run from project root:

   python scripts/gmail_authorize.py

4. Sign in as the Gmail account that will send mail (GMAIL_IMPERSONATE_USER).
5. Token saved to gcp/gmail_token.json (gitignored).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from denialflow_ai.core.config import get_settings

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


def main() -> None:
    settings = get_settings()
    client_path = settings.gmail_service_account_file
    token_path = settings.gmail_oauth_token_file

    if not client_path.is_file():
        print(f"Missing OAuth client file: {client_path}")
        sys.exit(1)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Install: pip install google-auth-oauthlib")
        sys.exit(1)

    print(f"Client secrets: {client_path}")
    print(f"Token will be saved to: {token_path}")
    print(f"Sign in as: {settings.gmail_impersonate_user or '(your Gmail account)'}")
    print("Opening browser for authorization...\n")

    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_path),
        scopes=[GMAIL_SEND_SCOPE],
    )
    creds = flow.run_local_server(port=8080, prompt="consent")
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"\nSaved token to {token_path}")
    print("Set GMAIL_NOTIFY_ENABLED=true and restart the API.")


if __name__ == "__main__":
    main()
