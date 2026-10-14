from __future__ import annotations

import re
from typing import Any

import boto3

from denialflow_ai.core.config import get_settings


def _safe_filename(filename: str) -> str:
    name = filename.strip().replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name[:200] or "document.md"


def copy_document(
    collection_name: str,
    filename: str,
    content: bytes,
    *,
    content_type: str | None = None,
) -> dict[str, Any]:
    """Copy a collection document to S3 without changing the local index."""
    settings = get_settings()
    bucket = settings.aws_s3_bucket.strip()
    if not bucket:
        return {"copied": False, "status": "disabled"}

    safe_collection = re.sub(r"[^A-Za-z0-9_-]", "_", collection_name.strip())
    key = f"{settings.aws_s3_prefix.strip('/')}/{safe_collection}/{_safe_filename(filename)}"
    try:
        client = boto3.client(
            "s3",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id or None,
            aws_secret_access_key=settings.aws_secret_access_key or None,
            aws_session_token=settings.aws_session_token or None,
        )
        arguments: dict[str, Any] = {"Bucket": bucket, "Key": key, "Body": content}
        if content_type:
            arguments["ContentType"] = content_type
        client.put_object(**arguments)
    except Exception as exc:
        return {"copied": False, "status": "failed", "error": str(exc)}
    return {"copied": True, "status": "uploaded", "bucket": bucket, "key": key}