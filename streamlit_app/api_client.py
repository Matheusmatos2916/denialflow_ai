from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

_APP_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _APP_DIR.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

import httpx
import streamlit as st


def api_base() -> str:
    return os.getenv("DENIALFLOW_API_BASE", "http://127.0.0.1:8000").rstrip("/")


@lru_cache(maxsize=1)
def _load_api_access_token() -> str:
    """Resolve Bearer token from environment / project .env (no sidebar input)."""
    token = os.getenv("API_ACCESS_TOKEN", "").strip()
    if token:
        return token
    try:
        from denialflow_ai.core.config import get_settings

        return get_settings().api_access_token.strip()
    except Exception:
        return ""


def get_access_token() -> str:
    if "_api_access_token_resolved" not in st.session_state:
        st.session_state["_api_access_token_resolved"] = _load_api_access_token()
    return str(st.session_state["_api_access_token_resolved"]).strip()


def get_auth_headers() -> dict[str, str]:
    token = get_access_token()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def render_auth_sidebar() -> None:
    # Manual API access (sidebar) — disabled; token comes from API_ACCESS_TOKEN in .env.
    # with st.sidebar:
    #     st.markdown("### API access")
    #     token = st.text_input(
    #         "API access token",
    #         value=get_access_token(),
    #         type="password",
    #         key="api_access_token_input",
    #         help="Same value as API_ACCESS_TOKEN in .env",
    #     )
    #     if token:
    #         st.session_state["api_access_token"] = str(token).strip()
    return


def api_request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    url = f"{api_base()}{path}"
    headers = dict(kwargs.pop("headers", {}) or {})
    headers.update(get_auth_headers())
    timeout = kwargs.pop("timeout", 30.0)
    with httpx.Client() as client:
        response = client.request(method, url, headers=headers, timeout=timeout, **kwargs)
    if response.status_code == 401:
        raise httpx.HTTPStatusError(
            "API returned 401 — set API_ACCESS_TOKEN in .env (see scripts/generate_api_token.py)",
            request=response.request,
            response=response,
        )
    return response
