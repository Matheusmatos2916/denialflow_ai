"""
Chunk seed markdown documents, embed with OpenAI, and persist to ChromaDB.

Run from repo root:
    python scripts/seed_vectorstore.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# =========================
# Load environment variables
# =========================
ROOT = Path(__file__).resolve().parents[1]

load_dotenv(ROOT / ".env")

os.chdir(ROOT)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# =========================
# Imports
# =========================
import chromadb  # noqa: E402
from openai import OpenAI  # noqa: E402

from denialflow_ai.core.config import get_settings  # noqa: E402
from denialflow_ai.rag.ingest import ingest_text  # noqa: E402

# =========================
# Constants
# =========================
COLLECTION = "denialflow_corpus"


def main() -> None:
    # =========================
    # Settings
    # =========================
    s = get_settings()

    if not s.openai_api_key:
        raise SystemExit(
            "OPENAI_API_KEY is required to seed embeddings."
        )

    print(f"Using embedding model: {s.openai_embedding_model}")
    print(f"Chroma directory: {s.chroma_persist_dir}")

    # =========================
    # Ensure directories exist
    # =========================
    s.chroma_persist_dir.mkdir(parents=True, exist_ok=True)
    s.seed_documents_dir.mkdir(parents=True, exist_ok=True)

    # =========================
    # Initialize ChromaDB
    # =========================
    client = chromadb.PersistentClient(
        path=str(s.chroma_persist_dir)
    )

    coll = client.get_or_create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )

    # =========================
    # OpenAI client
    # =========================
    oai = OpenAI(
        api_key=s.openai_api_key
    )

    # =========================
    # Load markdown files
    # =========================
    md_files = sorted(
        s.seed_documents_dir.glob("*.md")
    )

    if not md_files:
        raise SystemExit(
            f"No markdown files found in: {s.seed_documents_dir}"
        )

    print(f"Found {len(md_files)} markdown files.")

    total_chunks = 0
    for path in md_files:
        print(f"Processing: {path.name}")
        text = path.read_text(encoding="utf-8")
        def embed_batch(batch: list[str]) -> list[list[float]]:
            response = oai.embeddings.create(
                model=s.openai_embedding_model,
                input=batch,
            )
            return [item.embedding for item in response.data]

        result = ingest_text(coll, text, path.name, embed_batch=embed_batch)
        total_chunks += result["chunks"]
        print(f"Upserted {result['chunks']} chunks from {path.name}")

    # =========================
    # Done
    # =========================
    print(
        f"Done. "
        f"Collection={COLLECTION} "
        f"chunks={total_chunks}"
    )


if __name__ == "__main__":
    main()