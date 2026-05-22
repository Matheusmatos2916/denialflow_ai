from __future__ import annotations

import os

import httpx
import streamlit as st

from api_client import api_base, render_auth_sidebar

st.set_page_config(
    page_title="DenialFlow AI",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(ttl=10)
def health(base_url: str) -> dict:
    try:
        r = httpx.get(f"{base_url}/health", timeout=5.0)
        return {"ok": r.status_code < 500, "status": r.status_code}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


st.title("DenialFlow AI")
st.caption("AI-native denial resolution — enterprise POC")

with st.sidebar:
    st.markdown("### Environment")
    base = st.text_input("API base URL", value=api_base(), key="api_base_input")
    if base:
        os.environ["DENIALFLOW_API_BASE"] = base.rstrip("/")
    render_auth_sidebar()
    h = health(os.getenv("DENIALFLOW_API_BASE", base).rstrip("/"))
    if h.get("ok"):
        st.success("API reachable")
    else:
        st.error(f"API not reachable: {h}")

st.markdown(
    """
Welcome. Use the pages in the sidebar:

- **Dashboard** — operational + financial KPIs
- **Upload** — ingest denied claims (CSV)
- **Workflow** — agent execution timeline
- **Claims analysis** — triage table
- **Appeal review** — human-in-the-loop approvals

This POC uses synthetic data only.
"""
)
