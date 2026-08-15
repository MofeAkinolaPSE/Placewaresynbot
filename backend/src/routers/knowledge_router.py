"""knowledge_router.py — Knowledge Engine API endpoints.

Endpoints
──────────
  POST /knowledge/ingest                   Admin/quality: upload a file to ingest
  GET  /knowledge/search                   Internal: multi-stage vector search
  GET  /api/documents                      Admin/quality: list generated/ingested docs
  GET  /api/documents/{doc_id}             Admin/quality: get full document content
  GET  /knowledge/gaps                     Admin: review knowledge gaps
  PATCH /knowledge/gaps/{gap_id}/resolve   Admin: mark a gap as resolved
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from src.constants import (
    TABLE_DOCUMENT_ARCHIVE,
    TABLE_INGESTED_DOCUMENTS,
    TABLE_KNOWLEDGE_CHUNKS,
    TABLE_KNOWLEDGE_GAPS,
)
from src.db import db
from src.middleware import verify_jwt

logger = logging.getLogger(__name__)

router = APIRouter(tags=["knowledge"])

# ---------------------------------------------------------------------------
# RBAC helpers (mirrors _require_roles in data_ingest.py)
# ---------------------------------------------------------------------------

def _require_roles(request: Request, allowed: set[str]) -> dict[str, Any]:
    payload = verify_jwt(request)
    roles = set(payload.get("roles") or [])
    if not (roles & allowed):
        raise HTTPException(
            status_code=403,
            detail=f"Role required: {sorted(allowed)}. Got: {sorted(roles)}",
        )
    return payload


ADMIN_QUALITY = {"admin", "quality", "quality_assurance", "qa"}
ADMIN_ONLY    = {"admin"}

# ---------------------------------------------------------------------------
# Supported upload extensions
# ---------------------------------------------------------------------------

_ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".csv", ".md", ".markdown", ".xlsx", ".xls"}

# 25 MB upload limit
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


# ---------------------------------------------------------------------------
# POST /knowledge/ingest  — file upload
# ---------------------------------------------------------------------------

@router.post("/knowledge/ingest")
async def ingest_document_upload(
    request: Request,
    file: UploadFile = File(...),
):
    """Upload a document file to be ingested into the SynBot knowledge base.

    Required roles: admin, quality
    Supported formats: PDF, DOCX, TXT, CSV, MD
    Max size: 25 MB
    """
    user = _require_roles(request, ADMIN_QUALITY)

    # Validate extension
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: '{suffix}'. "
                   f"Allowed: {sorted(_ALLOWED_EXTENSIONS)}",
        )

    # Read and size-check
    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(data) // 1024} KB). Max: 25 MB.",
        )

    # Write to temp file and ingest
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        from src.services.knowledge_ingestor import ingest_file
        result = ingest_file(tmp_path, source="upload")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("reason", "Ingest failed"))

    logger.info(
        "User %s uploaded & ingested: %s → %s",
        user.get("sub"),
        file.filename,
        result.get("status"),
    )
    return {
        "status":      result.get("status"),
        "document_id": result.get("document_id"),
        "chunks":      result.get("chunks", 0),
        "filename":    file.filename,
        "message":     "Document ingested successfully." if result["status"] == "ok"
                       else "Document was already in the knowledge base.",
    }


# ---------------------------------------------------------------------------
# GET /knowledge/search  — multi-stage retrieval (for agents / internal use)
# ---------------------------------------------------------------------------

@router.get("/knowledge/search")
async def knowledge_search(
    request: Request,
    q: str = Query(..., min_length=2, description="Search query"),
    department: Optional[str] = Query(None),
    doc_type: Optional[str] = Query(None),
    top_k: int = Query(5, ge=1, le=20),
):
    """Multi-stage knowledge retrieval: embed → rewrite → retrieve → re-rank.

    Returns the top-k most relevant chunks with similarity scores.
    """
    # Any authenticated user can search (used by agents internally)
    verify_jwt(request)

    try:
        from src.services.knowledge_service import KnowledgeService
        from src.deepseek import DeepSeek
        from src.constants import DEEPSEEK_API_KEY

        llm = DeepSeek(api_key=DEEPSEEK_API_KEY) if DEEPSEEK_API_KEY else None
        svc = KnowledgeService(llm=llm)

        result = svc.search(
            query=q,
            department=department,
            document_type=doc_type,
            top_k=top_k,
            deep=True,  # this endpoint's whole purpose is the full pipeline
        )
    except Exception as exc:
        logger.exception("Knowledge search error: %s", exc)
        raise HTTPException(status_code=500, detail="Knowledge search failed")

    return {
        "query":       q,
        "query_used":  result.query_used,
        "memory_hit":  result.memory_hit,
        "gap_logged":  result.gap_logged,
        "chunk_count": len(result.chunks),
        "chunks": [
            {
                "document_id": c.document_id,
                "chunk_index": c.chunk_index,
                "content":     c.content,
                "metadata":    c.metadata,
                "similarity":  round(c.similarity, 4),
            }
            for c in result.chunks
        ],
    }


# ---------------------------------------------------------------------------
# GET /api/documents  — list documents for the frontend Documents tab
# ---------------------------------------------------------------------------

@router.get("/api/documents")
async def list_documents(
    request: Request,
    doc_type: Optional[str] = Query(None, description="Filter by document type"),
    department: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List generated + ingested documents for the compliance Documents tab.

    Required roles: admin, quality
    Merges rows from document_archive (generated) and ingested_documents (uploaded).
    """
    _require_roles(request, ADMIN_QUALITY)

    offset = (page - 1) * page_size

    try:
        # ── Generated documents from document_archive ─────────────────────
        archive_q = (
            db.table(TABLE_DOCUMENT_ARCHIVE)
            .select("id, doc_type, title, format, download_url, generated_by, created_at")
            .order("created_at", desc=True)
            .range(offset, offset + page_size - 1)
        )
        if doc_type:
            archive_q = archive_q.eq("doc_type", doc_type)

        archive_resp = archive_q.execute()
        archive_rows = archive_resp.data or []

        # ── Uploaded/ingested from ingested_documents ─────────────────────
        ingest_q = (
            db.table(TABLE_INGESTED_DOCUMENTS)
            .select("document_id, file_name, document_type, department, source, ingested_at, metadata")
            .eq("source", "upload")
            .order("ingested_at", desc=True)
            .range(offset, offset + page_size - 1)
        )
        if doc_type:
            ingest_q = ingest_q.eq("document_type", doc_type)
        if department:
            ingest_q = ingest_q.eq("department", department)

        ingest_resp = ingest_q.execute()
        ingest_rows = ingest_resp.data or []

        # Normalise archive rows to a common shape
        documents = []
        for row in archive_rows:
            documents.append({
                "id":           row.get("id"),
                "title":        row.get("title"),
                "document_type": row.get("doc_type"),
                "format":       row.get("format", "pdf"),
                "department":   None,
                "source":       "generated",
                "download_url": row.get("download_url"),
                "created_at":   row.get("created_at"),
                "generated_by": row.get("generated_by"),
            })

        for row in ingest_rows:
            meta = row.get("metadata") or {}
            documents.append({
                "id":           row.get("document_id"),
                "title":        row.get("file_name"),
                "document_type": row.get("document_type"),
                "format":       Path(row.get("file_name", "")).suffix.lstrip(".") or "file",
                "department":   row.get("department"),
                "source":       "upload",
                "download_url": None,
                "created_at":   row.get("ingested_at"),
                "generated_by": meta.get("uploaded_by"),
            })

        # Sort merged list by created_at DESC
        documents.sort(
            key=lambda d: (d.get("created_at") or ""),
            reverse=True,
        )

        return {"data": documents, "page": page, "page_size": page_size}

    except Exception as exc:
        logger.exception("list_documents error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch documents")


# ---------------------------------------------------------------------------
# GET /api/documents/{doc_id}  — fetch full document content for viewer modal
# ---------------------------------------------------------------------------

@router.get("/api/documents/{doc_id}")
async def get_document(request: Request, doc_id: str):
    """Return document metadata and, where available, the first few stored chunks
    (for text rendering in the UI viewer modal).

    Required roles: admin, quality
    """
    _require_roles(request, ADMIN_QUALITY)

    # Try document_archive first (generated docs)
    try:
        archive_resp = (
            db.table(TABLE_DOCUMENT_ARCHIVE)
            .select("*")
            .eq("id", doc_id)
            .limit(1)
            .execute()
        )
        archive_rows = archive_resp.data or []
        if archive_rows:
            row = archive_rows[0]
            # Fetch the associated knowledge chunks for text preview
            chunks = _get_chunks_for_archive(doc_id)
            return {
                "id":           row.get("id"),
                "title":        row.get("title"),
                "document_type": row.get("doc_type"),
                "source":       "generated",
                "format":       row.get("format", "pdf"),
                "download_url": row.get("download_url"),
                "created_at":   row.get("created_at"),
                "generated_by": row.get("generated_by"),
                "chunks":       chunks,
            }

        # Try ingested_documents
        ingest_resp = (
            db.table(TABLE_INGESTED_DOCUMENTS)
            .select("*")
            .eq("document_id", doc_id)
            .limit(1)
            .execute()
        )
        ingest_rows = ingest_resp.data or []
        if ingest_rows:
            row = ingest_rows[0]
            chunks = _get_chunks_for_doc(doc_id)
            return {
                "id":           row.get("document_id"),
                "title":        row.get("file_name"),
                "document_type": row.get("document_type"),
                "department":   row.get("department"),
                "source":       row.get("source", "upload"),
                "format":       Path(row.get("file_name", "")).suffix.lstrip("."),
                "download_url": None,
                "created_at":   row.get("ingested_at"),
                "metadata":     row.get("metadata"),
                "chunks":       chunks,
            }

        raise HTTPException(status_code=404, detail="Document not found")

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get_document error for %s: %s", doc_id, exc)
        raise HTTPException(status_code=500, detail="Failed to fetch document")


def _get_chunks_for_doc(document_id: str, limit: int = 10) -> list[dict]:
    """Return top chunks for a given document_id from knowledge_chunks."""
    try:
        resp = (
            db.table(TABLE_KNOWLEDGE_CHUNKS)
            .select("chunk_index, content, metadata")
            .eq("document_id", document_id)
            .order("chunk_index")
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception:
        return []


def _get_chunks_for_archive(archive_id: str, limit: int = 10) -> list[dict]:
    """Return chunks whose metadata.archive_id matches the doc_archive UUID."""
    try:
        import json as _json
        # We can't do a JSONB query via Supabase client; fall back to raw SQL via db helpers
        import psycopg2
        dsn = os.getenv("DATABASE_URL")
        if not dsn:
            return []
        conn = psycopg2.connect(dsn)
        cur  = conn.cursor()
        cur.execute(
            """
            SELECT chunk_index, content, metadata
            FROM knowledge_chunks
            WHERE metadata->>'archive_id' = %s
            ORDER BY chunk_index
            LIMIT %s
            """,
            (archive_id, limit),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {"chunk_index": r[0], "content": r[1], "metadata": r[2]}
            for r in rows
        ]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# GET /knowledge/gaps  — admin: view logged knowledge gaps
# ---------------------------------------------------------------------------

@router.get("/knowledge/gaps")
async def list_knowledge_gaps(
    request: Request,
    status: Optional[str] = Query(None, description="pending | resolved | ignored"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List knowledge gaps detected by the retrieval service.

    Required roles: admin
    """
    _require_roles(request, ADMIN_ONLY)

    offset = (page - 1) * page_size
    try:
        q = (
            db.table(TABLE_KNOWLEDGE_GAPS)
            .select("*")
            .order("created_at", desc=True)
            .range(offset, offset + page_size - 1)
        )
        if status:
            q = q.eq("status", status)
        resp = q.execute()
        return {"data": resp.data or [], "page": page, "page_size": page_size}
    except Exception as exc:
        logger.exception("list_knowledge_gaps error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch knowledge gaps")


# ---------------------------------------------------------------------------
# PATCH /knowledge/gaps/{gap_id}/resolve
# ---------------------------------------------------------------------------

@router.patch("/knowledge/gaps/{gap_id}/resolve")
async def resolve_knowledge_gap(request: Request, gap_id: int):
    """Mark a knowledge gap as resolved.  Required roles: admin."""
    _require_roles(request, ADMIN_ONLY)

    try:
        db.table(TABLE_KNOWLEDGE_GAPS).update({"status": "resolved"}).eq("id", gap_id).execute()
        return {"status": "resolved", "gap_id": gap_id}
    except Exception as exc:
        logger.exception("resolve_knowledge_gap error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to resolve gap")
