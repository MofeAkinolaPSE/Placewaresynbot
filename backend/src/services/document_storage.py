"""Hybrid document storage service for compliance documents.

Supports three backends controlled by the DOCUMENT_STORAGE_BACKEND env var:
  local    – writes to backend/static/documents/{doc_id}/{filename}  (default)
  supabase – uploads to a Supabase Storage bucket
  s3       – uploads to an S3-compatible bucket (DigitalOcean Spaces, AWS S3)

The `save_document()` function always returns a StorageResult with:
  file_path      – absolute local path  (local backend only, else None)
  cloud_key      – object key in bucket (cloud backends only, else None)
  storage_backend– which backend was used
  download_url   – always set: /documents/archive/{doc_id}/download (local)
                   or a pre-signed URL (cloud backends)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# ── configuration ──────────────────────────────────────────────────────────────
_BACKEND = os.getenv("DOCUMENT_STORAGE_BACKEND", "local")
_BUCKET  = os.getenv("DOCUMENT_STORAGE_BUCKET",  "compliance-documents")
_LOCAL_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "static", "documents")
)


@dataclass
class StorageResult:
    file_path:       Optional[str]
    cloud_key:       Optional[str]
    download_url:    str
    storage_backend: str


# ── public interface ────────────────────────────────────────────────────────────

def save_document(file_bytes: bytes, filename: str, doc_id: str) -> StorageResult:
    """Persist *file_bytes* under *doc_id/filename* on the configured backend.

    Automatically falls back to local storage if a cloud backend fails.
    """
    if _BACKEND == "supabase":
        try:
            return _save_supabase(file_bytes, filename, doc_id)
        except Exception as exc:
            logger.warning(
                "Supabase storage failed for doc_id=%s, falling back to local: %s",
                doc_id, exc,
            )
    elif _BACKEND == "s3":
        try:
            return _save_s3(file_bytes, filename, doc_id)
        except Exception as exc:
            logger.warning(
                "S3 storage failed for doc_id=%s, falling back to local: %s",
                doc_id, exc,
            )

    return _save_local(file_bytes, filename, doc_id)


def retrieve_document(doc_id: str, filename: str) -> Optional[bytes]:
    """Read back a locally-stored document.  Returns None if not found."""
    path = os.path.join(_LOCAL_ROOT, doc_id, filename)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as fp:
        return fp.read()


# ── backends ────────────────────────────────────────────────────────────────────

def _save_local(file_bytes: bytes, filename: str, doc_id: str) -> StorageResult:
    dir_path = os.path.join(_LOCAL_ROOT, doc_id)
    os.makedirs(dir_path, exist_ok=True)
    full_path = os.path.join(dir_path, filename)
    with open(full_path, "wb") as fp:
        fp.write(file_bytes)
    logger.info("Document saved locally: %s", full_path)
    return StorageResult(
        file_path=full_path,
        cloud_key=None,
        download_url=f"/documents/archive/{doc_id}/download",
        storage_backend="local",
    )


def _save_supabase(file_bytes: bytes, filename: str, doc_id: str) -> StorageResult:
    from src.db import db  # lazily imported to avoid circular imports at module load

    cloud_key = f"{doc_id}/{filename}"
    db.storage.from_(_BUCKET).upload(
        cloud_key, file_bytes, {"contentType": _content_type(filename)}
    )
    signed_res: dict = db.storage.from_(_BUCKET).create_signed_url(cloud_key, 604_800)
    # Supabase SDK v1 returns {"signedURL": "..."}, v2 nests under "data"
    download_url: str = (
        signed_res.get("signedURL")
        or (signed_res.get("data") or {}).get("signedUrl")
        or ""
    )
    logger.info(
        "Document saved to Supabase Storage: bucket=%s key=%s", _BUCKET, cloud_key
    )
    return StorageResult(
        file_path=None,
        cloud_key=cloud_key,
        download_url=download_url,
        storage_backend="supabase",
    )


def _save_s3(file_bytes: bytes, filename: str, doc_id: str) -> StorageResult:
    import boto3  # optional dependency: pip install boto3

    bucket       = os.getenv("S3_BUCKET", _BUCKET)
    endpoint_url = os.getenv("S3_ENDPOINT_URL")        # for DigitalOcean Spaces
    region       = os.getenv("S3_REGION", "us-east-1")
    access_key   = os.getenv("S3_ACCESS_KEY")
    secret_key   = os.getenv("S3_SECRET_KEY")

    cloud_key = f"{doc_id}/{filename}"
    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    client.put_object(
        Bucket=bucket,
        Key=cloud_key,
        Body=file_bytes,
        ContentType=_content_type(filename),
    )
    download_url: str = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": cloud_key},
        ExpiresIn=604_800,  # 7 days
    )
    logger.info("Document saved to S3/Spaces: bucket=%s key=%s", bucket, cloud_key)
    return StorageResult(
        file_path=None,
        cloud_key=cloud_key,
        download_url=download_url,
        storage_backend="s3",
    )


# ── helpers ─────────────────────────────────────────────────────────────────────

def _content_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    return {
        "pdf":  "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "csv":  "text/csv",
    }.get(ext, "application/octet-stream")
