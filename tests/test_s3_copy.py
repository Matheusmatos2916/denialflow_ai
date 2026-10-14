from __future__ import annotations

import asyncio
import io
from typing import Any

from fastapi import UploadFile

from aws.s3_copy import copy_document
from denialflow_ai.api.routers import knowledge
from denialflow_ai.core.config import reset_settings_cache


def test_copy_document_uploads_to_collection_key(monkeypatch):
    monkeypatch.setenv("AWS_S3_BUCKET", "denialflow-test")
    monkeypatch.setenv("AWS_S3_PREFIX", "collections")
    reset_settings_cache()
    calls: list[dict[str, Any]] = []

    class FakeS3:
        def put_object(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    monkeypatch.setattr("aws.s3_copy.boto3.client", lambda *args, **kwargs: FakeS3())

    result = copy_document("medical_policies", "../policy final.md", b"content")

    assert result == {
        "copied": True,
        "status": "uploaded",
        "bucket": "denialflow-test",
        "key": "collections/medical_policies/policy_final.md",
    }
    assert calls == [
        {
            "Bucket": "denialflow-test",
            "Key": "collections/medical_policies/policy_final.md",
            "Body": b"content",
        }
    ]
    reset_settings_cache()


def test_upload_document_indexes_and_copies_original_file(monkeypatch):
    indexed: list[tuple[Any, str, str]] = []
    copied: list[tuple[str, str, bytes]] = []
    fake_collection = object()

    def fake_ingest(collection: Any, content: str, filename: str) -> dict[str, Any]:
        indexed.append((collection, content, filename))
        return {"filename": filename, "chunks": 1}

    def fake_copy(
        collection_name: str,
        filename: str,
        content: bytes,
        *,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        copied.append((collection_name, filename, content))
        return {"copied": True, "status": "uploaded"}

    monkeypatch.setattr(knowledge, "_get_collection", lambda name: fake_collection)
    monkeypatch.setattr(knowledge, "ingest_text", fake_ingest)
    monkeypatch.setattr(knowledge, "copy_document", fake_copy)

    original = b"# Sample policy\nOriginal bytes"
    upload = UploadFile(filename="policy.md", file=io.BytesIO(original))
    result = asyncio.run(knowledge.upload_document("policies", upload))

    assert indexed == [(fake_collection, "# Sample policy\nOriginal bytes", "policy.md")]
    assert copied == [("policies", "policy.md", original)]
    assert result["s3"] == {"copied": True, "status": "uploaded"}