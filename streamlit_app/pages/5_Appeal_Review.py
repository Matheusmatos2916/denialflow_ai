from __future__ import annotations

import os

import httpx
import streamlit as st

st.set_page_config(page_title="Appeal review — DenialFlow AI", layout="wide")


def base() -> str:
    return os.getenv("DENIALFLOW_API_BASE", "http://127.0.0.1:8000").rstrip("/")


st.title("Appeal review (human-in-the-loop)")
st.caption("Approve, edit, or reject AI-drafted appeals. All actions are audit logged.")

try:
    items = httpx.get(f"{base()}/v1/appeals", params={"limit": 50}, timeout=15.0).json().get("items", [])
except Exception as e:  # noqa: BLE001
    st.error(str(e))
    st.stop()

if not items:
    st.info("No appeals in queue.")
    st.stop()

labels = {f"{a['id']} — claim internal {a['claim_internal_id'][:8]}…": a["id"] for a in items}
choice = st.selectbox("Select appeal", options=list(labels.keys()))
appeal_id = labels[choice]

try:
    detail = httpx.get(f"{base()}/v1/appeals/{appeal_id}", timeout=20.0).json()
except Exception as e:  # noqa: BLE001
    st.error(str(e))
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("Confidence", f"{detail.get('confidence', 0.0):.2f}")
c2.metric("Status", detail.get("status", ""))
c3.metric("Model", detail.get("model_used", ""))

st.subheader("Generated appeal")
st.markdown(detail.get("draft_text", ""))

st.subheader("Documents used (RAG retrieval)")
for h in detail.get("citations", []) or []:
    with st.expander(f"{h.get('title')} — score {float(h.get('score', 0.0)):.3f}"):
        st.code(h.get("snippet", ""), language="markdown")

with st.expander("Structured AI outputs"):
    st.write("Classification")
    st.json(detail.get("classification") or {})
    st.write("Prioritization")
    st.json(detail.get("prioritization") or {})

st.divider()
b1, b2, b3 = st.columns(3)
with b1:
    if st.button("Approve", type="primary"):
        r = httpx.post(f"{base()}/v1/appeals/{appeal_id}/approve", timeout=20.0)
        st.write(r.json())
        st.success("Approved")
with b2:
    reason = st.text_input("Reject reason", key="rej_reason")
    if st.button("Reject"):
        r = httpx.post(
            f"{base()}/v1/appeals/{appeal_id}/reject",
            json={"reason": reason or "rejected"},
            timeout=20.0,
        )
        st.write(r.json())
        st.warning("Rejected")
with b3:
    edited = st.text_area("Edited appeal text", value=detail.get("draft_text", ""), height=260)
    er = st.text_input("Edit reason", key="edit_reason")
    if st.button("Submit edit"):
        r = httpx.post(
            f"{base()}/v1/appeals/{appeal_id}/edit",
            json={"final_text": edited, "reason": er},
            timeout=30.0,
        )
        st.write(r.json())
        st.success("Edited appeal saved")
