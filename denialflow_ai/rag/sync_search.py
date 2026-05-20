from __future__ import annotations

import chromadb

from denialflow_ai.core.config import get_settings
from denialflow_ai.llm.embeddings import embed_texts_sync
from denialflow_ai.schemas import RagHit, RagRetrievalResult

COLLECTION_NAME = "denialflow_corpus"


def _collection():
    s = get_settings()
    s.chroma_persist_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(s.chroma_persist_dir))
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def retrieve_sync(claim_summary: str, top_k: int = 6) -> RagRetrievalResult:
    """Synchronous retrieval for CrewAI tools (OpenAI embeddings, not Groq)."""
    q = embed_texts_sync([claim_summary[:8000]])[0]
    col = _collection()
    res = col.query(
        query_embeddings=[q],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )
    hits: list[RagHit] = []
    ids = res.get("ids") or [[]]
    docs = res.get("documents") or [[]]
    metas = res.get("metadatas") or [[]]
    dists = res.get("distances") or [[]]
    if not ids or not ids[0]:
        return RagRetrievalResult(query=claim_summary, hits=[])
    for i, doc_id in enumerate(ids[0]):
        meta = (metas[0][i] if metas and metas[0] else {}) or {}
        title = str(meta.get("title") or meta.get("source") or "document")
        snippet = (docs[0][i] if docs and docs[0] else "") or ""
        dist = (dists[0][i] if dists and dists[0] else 0.0) or 0.0
        score = float(1.0 / (1.0 + float(dist)))
        if score < 0.12:
            continue
        hits.append(
            RagHit(
                doc_id=str(doc_id),
                title=title,
                snippet=snippet[:1200],
                score=score,
            )
        )
    dedup: dict[str, RagHit] = {}
    for h in hits:
        base = h.doc_id.split(":")[0]
        if base not in dedup or h.score > dedup[base].score:
            dedup[base] = h
    return RagRetrievalResult(query=claim_summary, hits=list(dedup.values())[:top_k])


def hits_to_prompt_block(result: RagRetrievalResult) -> str:
    lines: list[str] = []
    for i, h in enumerate(result.hits, start=1):
        lines.append(f"[{i}] {h.title} (doc_id={h.doc_id}, score={h.score:.3f})\n{h.snippet}\n")
    return "\n".join(lines) if lines else "(no relevant internal documents retrieved)"
