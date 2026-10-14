from __future__ import annotations

from typing import Any, Callable

from langchain_text_splitters import RecursiveCharacterTextSplitter

from denialflow_ai.llm.embeddings import embed_texts_sync

_splitter = RecursiveCharacterTextSplitter(chunk_size=900, chunk_overlap=120)


def ingest_text(
    collection: Any,
    content: str,
    filename: str,
    embed_batch: Callable[[list[str]], list[list[float]]] = embed_texts_sync,
) -> dict[str, Any]:
    """Chunk, embed, and upsert a source using the canonical seed pipeline."""
    chunks = _splitter.split_text(content)
    if not chunks:
        raise ValueError("document_has_no_extractable_text")

    source = filename.strip()[:200] or "document.md"
    stem = source.rsplit(".", 1)[0]
    title = stem.replace("_", " ").title()
    ids = [f"{stem}:{index}" for index in range(len(chunks))]
    metadatas = [
        {"source": source, "title": title, "chunk": str(index)}
        for index in range(len(chunks))
    ]

    # Replace the source atomically from the collection's point of view.
    previous = collection.get(where={"source": source}, include=["metadatas"])
    previous_ids = previous.get("ids") or []
    if previous_ids:
        collection.delete(ids=previous_ids)

    vectors: list[list[float]] = []
    for start in range(0, len(chunks), 64):
        vectors.extend(embed_batch(chunks[start : start + 64]))
    collection.upsert(
        ids=ids,
        documents=chunks,
        metadatas=metadatas,
        embeddings=vectors,
    )
    return {"filename": source, "title": title, "chunks": len(chunks), "ids": ids}
