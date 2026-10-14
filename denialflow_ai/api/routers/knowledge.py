from __future__ import annotations

import io
import re
from typing import Any

import chromadb
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from pypdf import PdfReader

from aws.s3_copy import copy_document
from denialflow_ai.core.config import get_settings
from denialflow_ai.rag.ingest import ingest_text

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class CollectionCreate(BaseModel):
    name: str = Field(min_length=3, max_length=63)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CollectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=63)
    metadata: dict[str, Any] | None = None


def _client() -> chromadb.ClientAPI:
    path = get_settings().chroma_persist_dir
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path))


def _clean_name(value: str) -> str:
    name = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{2,62}", name):
        raise HTTPException(status_code=422, detail="invalid_collection_name")
    return name


def _collection_payload(collection: Any) -> dict[str, Any]:
    return {
        "name": collection.name,
        "metadata": collection.metadata or {},
        "count": collection.count(),
    }


def _get_collection(name: str) -> Any:
    try:
        return _client().get_collection(name=_clean_name(name))
    except Exception as exc:
        raise HTTPException(status_code=404, detail="collection_not_found") from exc


@router.get("/collections")
async def list_collections() -> dict[str, list[dict[str, Any]]]:
    client = _client()
    items = []
    for item in client.list_collections():
        collection = item if hasattr(item, "name") else client.get_collection(name=str(item))
        items.append(_collection_payload(collection))
    return {"items": items}


@router.post("/collections")
async def create_collection(payload: CollectionCreate) -> dict[str, Any]:
    name = _clean_name(payload.name)
    metadata = payload.metadata or {"hnsw:space": "cosine", "managed_by": "denialflow"}
    try:
        collection = _client().create_collection(name=name, metadata=metadata)
    except Exception as exc:
        message = str(exc).lower()
        if "already exists" in message or "duplicate" in message or "unique constraint" in message:
            raise HTTPException(status_code=409, detail="collection_already_exists") from exc
        raise HTTPException(status_code=500, detail=f"collection_create_failed: {exc}") from exc
    return _collection_payload(collection)


@router.post("/collections/{name}/activate")
async def activate_collection(name: str) -> dict[str, Any]:
    client = _client()
    collection = _get_collection(name)
    for item in client.list_collections():
        other = item if hasattr(item, "name") else client.get_collection(name=str(item))
        metadata = dict(other.metadata or {})
        metadata["active"] = other.name == collection.name
        if not metadata.get("hnsw:space"):
            metadata["hnsw:space"] = "cosine"
        other.modify(metadata=metadata)
    return _collection_payload(collection)


@router.patch("/collections/{name}")
async def update_collection(name: str, payload: CollectionUpdate) -> dict[str, Any]:
    collection = _get_collection(name)
    new_name = _clean_name(payload.name) if payload.name else None
    if new_name and new_name != collection.name:
        try:
            collection.modify(name=new_name)
        except Exception as exc:
            raise HTTPException(status_code=409, detail="collection_name_unavailable") from exc
        collection = _client().get_collection(name=new_name)
    if payload.metadata is not None:
        collection.modify(metadata=payload.metadata)
    return _collection_payload(collection)


@router.delete("/collections/{name}")
async def delete_collection(name: str) -> dict[str, str]:
    collection = _get_collection(name)
    _client().delete_collection(collection.name)
    return {"name": collection.name, "status": "deleted"}


@router.get("/collections/{name}/documents")
async def list_documents(name: str) -> dict[str, list[dict[str, Any]]]:
    collection = _get_collection(name)
    result = collection.get(include=["documents", "metadatas"])
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []
    ids = result.get("ids") or []
    return {
        "items": [
            {
                "id": doc_id,
                "document": documents[index] or "",
                "metadata": (metadatas[index] or {}) if index < len(metadatas) else {},
            }
            for index, doc_id in enumerate(ids)
        ]
    }


@router.post("/collections/{name}/documents")
async def add_document(
    name: str,
    content: str = Form(..., min_length=1),
    filename: str = Form("document.txt"),
) -> dict[str, Any]:
    collection = _get_collection(name)
    document = content.strip()
    safe_filename = filename.strip()[:200] or "document.md"
    try:
        result = ingest_text(collection, document, safe_filename)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result["s3"] = copy_document(
        name,
        safe_filename,
        document.encode("utf-8"),
        content_type="text/plain; charset=utf-8",
    )
    return result


@router.post("/collections/{name}/files")
async def upload_document(name: str, file: UploadFile = File(...)) -> dict[str, Any]:
    collection = _get_collection(name)
    filename = file.filename or "document.md"
    extension = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if extension not in {"md", "pdf"}:
        raise HTTPException(status_code=415, detail="only_md_and_pdf_files_are_supported")
    raw = await file.read()
    if extension == "pdf":
        try:
            reader = PdfReader(io.BytesIO(raw))
            content = "\n\n".join(page.extract_text() or "" for page in reader.pages).strip()
        except Exception as exc:
            raise HTTPException(status_code=422, detail="pdf_text_extraction_failed") from exc
    else:
        content = raw.decode("utf-8-sig")
    if not content.strip():
        raise HTTPException(status_code=422, detail="document_has_no_extractable_text")
    try:
        result = ingest_text(collection, content.strip(), filename.strip()[:200] or "document.md")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result["s3"] = copy_document(name, filename, raw, content_type=file.content_type)
    return result


@router.put("/collections/{name}/documents/{document_id}")
async def update_document(
    name: str,
    document_id: str,
    content: str = Form(..., min_length=1),
    filename: str = Form("document.txt"),
) -> dict[str, Any]:
    collection = _get_collection(name)
    existing = collection.get(ids=[document_id], include=["metadatas"])
    if not existing.get("ids"):
        raise HTTPException(status_code=404, detail="document_not_found")
    safe_filename = filename.strip()[:200] or "document.md"
    document = content.strip()
    try:
        result = ingest_text(collection, document, safe_filename)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result["s3"] = copy_document(
        name,
        safe_filename,
        document.encode("utf-8"),
        content_type="text/plain; charset=utf-8",
    )
    return result


@router.delete("/collections/{name}/documents/{document_id}")
async def delete_document(name: str, document_id: str) -> dict[str, str]:
    collection = _get_collection(name)
    existing = collection.get(ids=[document_id])
    if not existing.get("ids"):
        raise HTTPException(status_code=404, detail="document_not_found")
    collection.delete(ids=[document_id])
    return {"id": document_id, "status": "deleted"}