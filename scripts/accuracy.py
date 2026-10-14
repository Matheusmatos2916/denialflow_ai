from __future__ import annotations

import json
import os
import random
from pathlib import Path

import chromadb
import pandas as pd

from groq import Groq
from openai import OpenAI
from dotenv import load_dotenv
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

# =========================================================
# CONFIG
# =========================================================

load_dotenv()

ROOT = Path(
    r"C:\Users\mathe\OneDrive\Área de Trabalho\python\EVA - PROJETO"
)

DATASET_PATH = ROOT / "data" / "sample_denials.csv"

RESULTS_PATH = ROOT / "classification_results.csv"

CHROMA_PATH = ROOT / "data" / "chroma"

COLLECTION_NAME = "denialflow_corpus_test"

MODEL = os.getenv("GROQ_MODEL_PRIMARY", "llama-3.3-70b-versatile")
MODEL_GROQ_FALLBACK = os.getenv("GROQ_MODEL_FALLBACK", "llama-3.1-8b-instant")

client = Groq()
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

random.seed(42)

# Number of samples to process for this experiment
SAMPLE_SIZE = int(os.getenv("ACCURACY_SAMPLE_SIZE", "500"))

# =========================================================
# CHROMA
# =========================================================

print("\nConectando ao ChromaDB...")

chroma_client = chromadb.PersistentClient(
    path=str(CHROMA_PATH)
)

collection = chroma_client.get_collection(
    COLLECTION_NAME
)

# OpenAI embedding function para queries
embedding_function = OpenAIEmbeddingFunction(
    api_key=os.getenv("OPENAI_API_KEY"),
    model_name="text-embedding-3-small",
)

print("Chroma conectado.")

# =========================================================
# VALID LABELS
# =========================================================

VALID_CLASSES = [
    "medical_necessity",
    "missing_information",
    "duplicate_claim",
    "authorization_issue",
    "bundled_service",
    "documentation_required",
    "non_covered_service",
]

# =========================================================
# PROMPT
# =========================================================

SYSTEM_PROMPT = """
You are an expert healthcare RCM denial classifier.

You receive:
- denial code
- denial reason
- payer policy excerpts retrieved from a vector database

Your task:
Classify the denial into ONLY one category.

VALID CATEGORIES:
- medical_necessity
- missing_information
- duplicate_claim
- authorization_issue
- bundled_service
- documentation_required
- non_covered_service

Return ONLY valid JSON.

FORMAT:
{
  "category": "medical_necessity",
  "confidence": 0.95
}
"""

# =========================================================
# RAG SEARCH
# =========================================================

def retrieve_context(query: str, k: int = 3):

    # Generate embedding for query using OpenAI
    query_embedding = embedding_function([query])

    result = collection.query(
        query_embeddings=query_embedding,
        n_results=k,
    )

    docs = result["documents"][0]

    return docs

# =========================================================
# CLASSIFICATION
# =========================================================

def classify_with_rag(
    denial_code: str,
    denial_reason: str,
):

    query = f"""
    Denial code: {denial_code}
    Reason: {denial_reason}
    """

    retrieved_docs = retrieve_context(query)

    rag_context = "\n\n".join(retrieved_docs)

    user_prompt = f"""
DENIAL CODE:
{denial_code}

DENIAL REASON:
{denial_reason}

RAG CONTEXT:
{rag_context}
"""

    # Cascade: Groq Primary → Groq Fallback → OpenAI
    
    # 1. Try Groq Primary
    result = _classify_with_groq(user_prompt, retrieved_docs, MODEL)
    if result[0] != "error":
        return result

    # 2. Try Groq Fallback
    print("    → Falling back to Groq (small model)...")
    result = _classify_with_groq(user_prompt, retrieved_docs, MODEL_GROQ_FALLBACK)
    if result[0] != "error":
        return result

    # 3. Try OpenAI
    print("    → Falling back to OpenAI...")
    result = _classify_with_openai(user_prompt, retrieved_docs)
    
    return result


def _classify_with_groq(user_prompt: str, retrieved_docs: list, model: str):
    """Try classification with Groq."""
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
        )

        raw = response.choices[0].message.content.strip()

        # Clean markdown code blocks if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as je:
            print(f"    JSON Parse Error ({model}): {je}")
            return (
                "unparseable",
                0.0,
                retrieved_docs,
            )

        category = data.get("category", "error")
        confidence = float(data.get("confidence", 0.0))

        if category not in VALID_CLASSES:
            category = "invalid_prediction"

        return (
            category,
            confidence,
            retrieved_docs,
        )

    except Exception as e:
        error_msg = str(e)
        # Check if it's a rate limit error
        if "rate_limit" in error_msg.lower() or "429" in error_msg:
            print(f"    Groq Rate Limit ({model}): {e}")
        else:
            print(f"    Groq Error ({model}): {e}")
        
        # Return error to trigger fallback
        return (
            "error",
            0.0,
            [],
        )


def _classify_with_openai(user_prompt: str, retrieved_docs: list):
    """Fallback classification with OpenAI."""
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
        )

        raw = response.choices[0].message.content.strip()

        # Clean markdown code blocks if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as je:
            print(f"    OpenAI JSON Parse Error: {je}")
            return (
                "unparseable",
                0.0,
                retrieved_docs,
            )

        category = data.get("category", "error")
        confidence = float(data.get("confidence", 0.0))

        if category not in VALID_CLASSES:
            category = "invalid_prediction"

        return (
            category,
            confidence,
            retrieved_docs,
        )

    except Exception as e:
        print(f"    OpenAI Error (final fallback failed): {e}")
        return (
            "error",
            0.0,
            [],
        )

# =========================================================
# EXECUTION
# =========================================================

def run():
    df = pd.read_csv(DATASET_PATH)

    # limit dataset to SAMPLE_SIZE for this experiment
    df = df.head(SAMPLE_SIZE)

    results = []
    groq_count = 0
    openai_count = 0

    total = len(df)

    for idx, row in df.iterrows():

        print(
            f"[{idx+1}/{total}] "
            f"{row['claim_id']}"
        )

        predicted, confidence, docs = classify_with_rag(
            row["denial_code"],
            row["denial_reason_text"],
        )

        results.append(
            {
                "claim_id": row["claim_id"],
                "denial_code": row["denial_code"],
                "denial_reason": row["denial_reason_text"][:100],
                "predicted_category":
                    predicted,

                "confidence":
                    confidence,

                "retrieved_docs_count":
                    len(docs),
            }
        )

    out = pd.DataFrame(results)

    out.to_csv(RESULTS_PATH, index=False)

    print(
        f"\n✅ Resultados salvos em:"
        f"\n{RESULTS_PATH}"
    )

    print(f"Processed {total} samples (SAMPLE_SIZE={SAMPLE_SIZE})")

    return out

# =========================================================
# METRICS
# =========================================================

def evaluate(df):

    valid = df[
        ~df["predicted_category"].isin(
            ["error", "invalid_prediction", "unparseable"]
        )
    ]

    print("\n" + "="*70)
    print("CLASSIFICATION RESULTS")
    print("="*70)

    print(f"\nTotal claims: {len(df)}")
    print(f"Valid predictions: {len(valid)}")
    print(f"Errors/Unparseable: {len(df) - len(valid)}")

    # Category distribution
    category_counts = valid["predicted_category"].value_counts()
    
    print("\nPredicted Category Distribution:")
    print("-"*70)
    
    for category, count in category_counts.items():
        pct = (count / len(valid)) * 100
        avg_confidence = valid[
            valid["predicted_category"] == category
        ]["confidence"].mean()
        
        print(
            f"{category:<25} "
            f"Count: {count:<4} "
            f"({pct:>5.1f}%) "
            f"Avg Confidence: {avg_confidence:.4f}"
        )

    # Overall stats
    avg_confidence = valid["confidence"].mean()
    
    print("\n" + "-"*70)
    print(f"Overall Average Confidence: {avg_confidence:.4f}")
    print("="*70 + "\n")

# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    print("\nExecutando experimento...\n")

    results = run()

    evaluate(results)

    print("\nExperimento finalizado.")