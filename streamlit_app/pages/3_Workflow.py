from __future__ import annotations

import os
import time

import httpx
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Workflow — DenialFlow AI", layout="wide")


def base() -> str:
    return os.getenv("DENIALFLOW_API_BASE", "http://127.0.0.1:8000").rstrip("/")


st.title("Processing workflow")
st.caption("Live-ish view of workflow runs and structured agent logs")

rid = st.text_input("Run ID", value=st.session_state.get("last_run_id", ""))
auto = st.toggle("Auto-refresh (5s)", value=False)

if not rid:
    st.info("Paste a run id from Upload, or query recent runs below.")
else:
    col1, col2 = st.columns([1, 2])
    with col1:
        try:
            run = httpx.get(f"{base()}/v1/workflows/{rid}", timeout=10.0).json()
            st.json(run)
        except Exception as e:  # noqa: BLE001
            st.error(str(e))
    with col2:
        try:
            ev = httpx.get(f"{base()}/v1/workflows/{rid}/events", timeout=10.0).json().get("items", [])
            st.dataframe(pd.DataFrame(ev), use_container_width=True, hide_index=True)
        except Exception as e:  # noqa: BLE001
            st.error(str(e))

st.subheader("Recent runs")
try:
    runs = httpx.get(f"{base()}/v1/workflows", timeout=10.0).json().get("items", [])
    st.dataframe(pd.DataFrame(runs), use_container_width=True, hide_index=True)
except Exception as e:  # noqa: BLE001
    st.error(str(e))

if auto:
    time.sleep(5)
    st.rerun()
