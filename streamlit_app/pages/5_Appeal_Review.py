from __future__ import annotations

import os

import httpx
import streamlit as st

st.set_page_config(page_title="Appeal review — DenialFlow AI", layout="wide")


def base() -> str:
    return os.getenv("DENIALFLOW_API_BASE", "http://127.0.0.1:8000").rstrip("/")


def _render_ai_review(review: dict) -> None:
    st.metric("Score (Bedrock)", f"{float(review.get('overall_score', 0.0)):.2f}")
    st.caption(f"Model: {review.get('model_used', '')}")
    ready = review.get("ready_to_submit", False)
    st.write(f"**Pronto para envio:** {'Sim' if ready else 'Não'}")
    st.write(f"**Recomendação:** `{review.get('recommended_action', '')}`")
    if review.get("agrees_with_crewai_confidence") is not None:
        agree = "Sim" if review["agrees_with_crewai_confidence"] else "Não"
        st.write(f"**Concorda com confidence CrewAI:** {agree}")
    st.write("**Resumo**")
    st.markdown(review.get("summary", ""))
    st.write("**Verificação de citações**")
    st.markdown(review.get("citation_check", ""))
    issues = review.get("issues") or []
    if issues:
        st.write("**Problemas**")
        for item in issues:
            st.markdown(f"- {item}")
    missing = review.get("missing_elements") or []
    if missing:
        st.write("**Elementos ausentes**")
        for item in missing:
            st.markdown(f"- {item}")
    edits = review.get("suggested_edits") or []
    if edits:
        st.write("**Sugestões de edição**")
        for item in edits:
            st.markdown(f"- {item}")


st.title("Appeal review (human-in-the-loop)")
st.caption(
    "1ª opinião: CrewAI/Groq. 2ª opinião: Bedrock analisa o rascunho + documentos RAG do banco. "
    "Decisão final é humana."
)

try:
    items = httpx.get(f"{base()}/v1/appeals", params={"limit": 50}, timeout=15.0).json().get(
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
    detail = httpx.get(f"{base()}/v1/appeals/{appeal_id}", timeout=20.0).json()
except Exception as e:  # noqa: BLE001
    st.error(str(e))
    st.stop()

claim_label = detail.get("claim_id", appeal_id[:8])
st.subheader(f"Appeal review — claim {claim_label}")

c1, c2, c3 = st.columns(3)
c1.metric("Confidence (CrewAI)", f"{detail.get('confidence', 0.0):.2f}")
c2.metric("Status", detail.get("status", ""))
c3.metric("Model (Groq)", detail.get("model_used", ""))

st.subheader("1ª opinião (CrewAI / Groq)")
st.caption(f"Model: {detail.get('model_used', '')} · Confidence: {detail.get('confidence', 0.0):.2f}")
st.markdown(detail.get("draft_text", ""))

st.subheader("Documentos RAG")
for h in detail.get("citations", []) or []:
    with st.expander(f"{h.get('title')} — score {float(h.get('score', 0.0)):.3f}"):
        st.code(h.get("snippet", ""), language="markdown")

st.subheader("2ª opinião (Bedrock)")
ai_review = detail.get("ai_review")

if ai_review:
    _render_ai_review(ai_review)
    if detail.get("ai_review_at"):
        st.caption(f"Gerada em: {detail['ai_review_at']}")
else:
    with st.expander("Solicitar segunda opinião", expanded=True):
        st.caption(
            "O Bedrock analisa o rascunho da 1ª opinião e os documentos RAG salvos no appeal "
            "(base Chroma/embeddings). Não gera um novo appeal."
        )
        if st.button("Gerar análise Bedrock", type="primary", key="btn_ai_review"):
            with st.spinner("Bedrock analisando rascunho CrewAI…"):
                try:
                    r = httpx.post(
                        f"{base()}/v1/appeals/{appeal_id}/ai-review",
                        timeout=120.0,
                    )
                    if r.status_code >= 400:
                        try:
                            err = r.json()
                            detail = err.get("detail", r.text)
                        except Exception:  # noqa: BLE001
                            detail = r.text
                        if r.status_code == 429 or "bedrock_quota_exceeded" in str(detail):
                            st.error(
                                "Cota diária do Amazon Bedrock esgotada para este modelo/região. "
                                "O limite costuma resetar à meia-noite UTC. Você pode pedir aumento "
                                "em **AWS Console → Bedrock → Model access / Quotas**, trocar "
                                "`BEDROCK_MODEL_REVIEW` por um modelo com quota maior, ou ativar "
                                "`BEDROCK_REVIEW_FALLBACK_GROQ=true` no `.env`."
                            )
                            st.caption(str(detail))
                        else:
                            st.error(detail)
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
st.subheader("Decisão humana")
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
