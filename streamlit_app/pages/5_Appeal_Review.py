from __future__ import annotations

import streamlit as st

from api_client import api_request, render_auth_sidebar

st.set_page_config(page_title="Appeal review — DenialFlow AI", layout="wide")
render_auth_sidebar()


def _render_ai_review(review: dict) -> None:
    st.metric("Score (Bedrock)", f"{float(review.get('overall_score', 0.0)):.2f}")
    st.caption(f"Model: {review.get('model_used', '')}")
    ready = review.get("ready_to_submit", False)
    st.write(f"**Ready to submit:** {'Yes' if ready else 'No'}")
    st.write(f"**Recommendation:** `{review.get('recommended_action', '')}`")
    if review.get("agrees_with_crewai_confidence") is not None:
        agree = "Yes" if review["agrees_with_crewai_confidence"] else "No"
        st.write(f"**Agrees with CrewAI confidence:** {agree}")
    st.write("**Summary**")
    st.markdown(review.get("summary", ""))
    st.write("**Citation check**")
    st.markdown(review.get("citation_check", ""))
    issues = review.get("issues") or []
    if issues:
        st.write("**Issues**")
        for item in issues:
            st.markdown(f"- {item}")
    missing = review.get("missing_elements") or []
    if missing:
        st.write("**Missing elements**")
        for item in missing:
            st.markdown(f"- {item}")
    edits = review.get("suggested_edits") or []
    if edits:
        st.write("**Suggested edits**")
        for item in edits:
            st.markdown(f"- {item}")


st.title("Appeal review (human-in-the-loop)")
st.caption(
    "1st opinion: CrewAI/Groq. 2nd opinion: Bedrock reviews the draft + RAG documents from the store. "
    "Final decision is human."
)

try:
    items = api_request("GET", "/v1/appeals", params={"limit": 50}, timeout=15.0).json().get(
        "items", []
    )
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
    detail = api_request("GET", f"/v1/appeals/{appeal_id}", timeout=20.0).json()
except Exception as e:  # noqa: BLE001
    st.error(str(e))
    st.stop()

claim_label = detail.get("claim_id", appeal_id[:8])
st.subheader(f"Appeal review — claim {claim_label}")

c1, c2, c3 = st.columns(3)
c1.metric("Confidence (CrewAI)", f"{detail.get('confidence', 0.0):.2f}")
c2.metric("Status", detail.get("status", ""))
c3.metric("Model (Groq)", detail.get("model_used", ""))

st.subheader("1st opinion (CrewAI / Groq)")
st.caption(f"Model: {detail.get('model_used', '')} · Confidence: {detail.get('confidence', 0.0):.2f}")
st.markdown(detail.get("draft_text", ""))

st.subheader("RAG documents")
for h in detail.get("citations", []) or []:
    with st.expander(f"{h.get('title')} — score {float(h.get('score', 0.0)):.3f}"):
        st.code(h.get("snippet", ""), language="markdown")

st.subheader("2nd opinion (Bedrock)")
ai_review = detail.get("ai_review")

if ai_review:
    _render_ai_review(ai_review)
    if detail.get("ai_review_at"):
        st.caption(f"Generated at: {detail['ai_review_at']}")
else:
    with st.expander("Request second opinion", expanded=True):
        st.caption(
            "Bedrock reviews the 1st-opinion draft and the RAG documents saved on the appeal "
            "(Chroma/embeddings store). It does not generate a new appeal."
        )
        if st.button("Generate Bedrock analysis", type="primary", key="btn_ai_review"):
            with st.spinner("Bedrock reviewing CrewAI draft…"):
                try:
                    r = api_request(
                        "POST",
                        f"/v1/appeals/{appeal_id}/ai-review",
                        timeout=120.0,
                    )
                    if r.status_code >= 400:
                        try:
                            err = r.json()
                            err_detail = err.get("detail", r.text)
                        except Exception:  # noqa: BLE001
                            err_detail = r.text
                        if r.status_code == 429 or "bedrock_quota_exceeded" in str(err_detail):
                            st.error(
                                "Daily Amazon Bedrock quota exhausted for this model/region. "
                                "The limit usually resets at midnight UTC. You can request an increase "
                                "in **AWS Console → Bedrock → Model access / Quotas**, switch "
                                "`BEDROCK_MODEL_REVIEW` to a model with higher quota, or set "
                                "`BEDROCK_REVIEW_FALLBACK_GROQ=true` in `.env`."
                            )
                            st.caption(str(err_detail))
                        else:
                            st.error(err_detail)
                    else:
                        st.session_state[f"ai_review_{appeal_id}"] = r.json()
                        st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(str(e))

with st.expander("Structured AI outputs (classification / prioritization)"):
    st.write("Classification")
    st.json(detail.get("classification") or {})
    st.write("Prioritization")
    st.json(detail.get("prioritization") or {})

st.divider()
st.subheader("Human decision")
b1, b2, b3 = st.columns(3)
with b1:
    if st.button("Approve", type="primary"):
        r = api_request("POST", f"/v1/appeals/{appeal_id}/approve", timeout=20.0)
        st.write(r.json())
        st.success("Approved")
with b2:
    reason = st.text_input("Reject reason", key="rej_reason")
    if st.button("Reject"):
        r = api_request(
            "POST",
            f"/v1/appeals/{appeal_id}/reject",
            json={"reason": reason or "rejected"},
            timeout=20.0,
        )
        st.write(r.json())
        st.warning("Rejected")
with b3:
    edited = st.text_area("Edited appeal text", value=detail.get("draft_text", ""), height=260)
    er = st.text_input("Edit reason", key="edit_reason")
    if st.button("Submit edit"):
        r = api_request(
            "POST",
            f"/v1/appeals/{appeal_id}/edit",
            json={"final_text": edited, "reason": er},
            timeout=30.0,
        )
        st.write(r.json())
        st.success("Edited appeal saved")
