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
from langchain_text_splitters import RecursiveCharacterTextSplitter  # noqa: E402
from openai import OpenAI  # noqa: E402

from denialflow_ai.core.config import get_settings  # noqa: E402

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
    # Text splitter
    # =========================
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=900,
        chunk_overlap=120,
    )

    # =========================
    # OpenAI client
    # =========================
    oai = OpenAI(
        api_key=s.openai_api_key
    )

    # =========================
    # Storage buffers
    # =========================
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []

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

    # =========================
    # Chunk documents
    # =========================
    for path in md_files:
        print(f"Processing: {path.name}")

        text = path.read_text(encoding="utf-8")

        title = path.stem.replace("_", " ").title()

        chunks = splitter.split_text(text)

        for i, chunk in enumerate(chunks):
            doc_id = f"{path.stem}:{i}"

            ids.append(doc_id)
            documents.append(chunk)

            metadatas.append(
                {
                    "source": path.name,
                    "title": title,
                    "chunk": str(i),
                }
            )

    print(f"Generated {len(documents)} chunks.")

    # =========================
    # Generate embeddings
    # =========================
    batch_size = 64

    for start in range(0, len(documents), batch_size):
        end = min(start + batch_size, len(documents))

        sub_docs = documents[start:end]

        try:
            emb = oai.embeddings.create(
                model=s.openai_embedding_model,
                input=sub_docs,
            )

            vectors = [
                item.embedding
                for item in emb.data
            ]

            coll.upsert(
                ids=ids[start:end],
                documents=sub_docs,
                metadatas=metadatas[start:end],
                embeddings=vectors,
            )

            print(
                f"Upserted {start}-{end} "
                f"of {len(documents)}"
            )

        except Exception as e:
            print(
                f"Error embedding batch "
                f"{start}-{end}: {e}"
            )

    # =========================
    # Done
    # =========================
    print(
        f"Done. "
        f"Collection={COLLECTION} "
        f"chunks={len(documents)}"
    )


if __name__ == "__main__":
    main()