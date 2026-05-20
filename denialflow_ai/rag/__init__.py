from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection

from denialflow_ai.core.config import get_settings
from denialflow_ai.llm.embeddings import embed_texts
from denialflow_ai.schemas import RagHit, RagRetrievalResult


COLLECTION_NAME = "denialflow_corpus"


def _get_collection() -> Collection:
    s = get_settings()
    s.chroma_persist_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(s.chroma_persist_dir))
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


async def retrieve_for_claim(claim_summary: str, top_k: int = 6) -> RagRetrievalResult:
    """Semantic retrieval for a claim context (async embeddings + chroma query)."""
    col = _get_collection()
    vec = await embed_texts([claim_summary[:8000]])
    q = vec[0]
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


class ClassificationCache:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._data: dict[str, tuple[float, str]] = {}

    def key(self, payload: str) -> str:
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, payload: str) -> dict[str, Any] | None:
        k = self.key(payload)
        item = self._data.get(k)
        if not item:
            return None
        ts, raw = item
        if time.time() - ts > self._ttl:
            self._data.pop(k, None)
            return None
        return json.loads(raw)

    def set(self, payload: str, value: dict[str, Any]) -> None:
        k = self.key(payload)
        self._data[k] = (time.time(), json.dumps(value))


_cache: ClassificationCache | None = None


def get_classification_cache() -> ClassificationCache:
    global _cache
    if _cache is None:
        _cache = ClassificationCache(get_settings().classification_cache_ttl_seconds)
    return _cache
