#!/usr/bin/env python3
"""Generate a long-lived JWT for API_ACCESS_TOKEN (static Bearer auth)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from denialflow_ai.api.auth import create_access_token
from denialflow_ai.core.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate DenialFlow API bearer JWT")
    parser.add_argument("--subject", default="api", help="JWT sub claim")
    parser.add_argument("--days", type=int, default=365, help="Token validity in days")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.jwt_secret.strip():
        print("Error: set JWT_SECRET in .env before generating a token.", file=sys.stderr)
        sys.exit(1)

    token = create_access_token(subject=args.subject, expires_days=args.days)
    print("Add to .env (Streamlit loads it automatically):")
    print(f"API_ACCESS_TOKEN={token}")
    print()
    print("Use in requests:")
    print(f'Authorization: Bearer {token}')


if __name__ == "__main__":
    main()
