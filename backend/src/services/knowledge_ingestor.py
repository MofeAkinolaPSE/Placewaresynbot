"""knowledge_ingestor.py — backend-callable service for knowledge base ingestion.

This module wraps the core ingestion logic and is designed to be imported by
other backend services (document_engine, knowledge_router).  It does NOT
depend on FastAPI or any HTTP layer — it is pure business logic.

Key entry points
─────────────────
  ingest_file(filepath, source)         — ingest a file on disk
  ingest_text(content, filename, meta)  — ingest raw text (e.g. generated reports)
  ingest_bytes(data, filename, meta)    — ingest file bytes (e.g. PDF from memory)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal imports — the ingestion pipeline lives in the standalone pipeline
# folder.  We import the pure utility functions directly so this service
# works from within the backend package without duplicating logic.
# ---------------------------------------------------------------------------

def _get_pipeline():
    """Lazy import of the ingestion pipeline module.

    The pipeline folder may not always be on sys.path, so we locate it
    relative to this file and add it if needed.
    """
    import sys
    pipeline_dir = str(
        Path(__file__).resolve().parents[3]
        / "Synbot Knowledge Ingestion pipeline"
    )
    if pipeline_dir not in sys.path:
        sys.path.insert(0, pipeline_dir)
    import ingestion as _pipeline  # type: ignore[import]
    return _pipeline


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest_file(filepath: str, source: str = "manual") -> dict[str, Any]:
    """Ingest a file that already exists on disk.

    Args:
        filepath: Absolute or relative path to the document.
        source:   Tag stored in chunk metadata ('manual'|'generated'|'upload').

    Returns:
        Summary dict: {'status': 'ok'|'skipped'|'error', 'chunks': int, ...}
    """
    pipeline = _get_pipeline()
    try:
        return pipeline.ingest_document(filepath, source=source)
    except Exception as exc:
        logger.exception("ingest_file failed for %s: %s", filepath, exc)
        return {"status": "error", "reason": str(exc), "file": filepath}


def ingest_text(
    content: str,
    filename: str,
    metadata: dict[str, Any] | None = None,
    source: str = "generated",
) -> dict[str, Any]:
    """Ingest raw text content (e.g. a generated report string).

    Writes content to a temporary file, ingests it, then deletes the temp file.

    Args:
        content:  Plain text to ingest.
        filename: Logical filename for display / metadata detection purposes.
        metadata: Optional metadata override dict (document_type, department, …).
        source:   Source tag for chunk metadata.

    Returns:
        Summary dict from the ingestion pipeline.
    """
    if not content or not content.strip():
        logger.warning("ingest_text called with empty content for %s", filename)
        return {"status": "skipped", "reason": "empty_content"}

    pipeline = _get_pipeline()

    # Write to a temp file with the logical filename so detect_metadata works
    suffix = Path(filename).suffix or ".txt"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=suffix, delete=False
    ) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = pipeline.ingest_document(tmp_path, source=source)

        # If custom metadata was provided, patch the DB record after ingest
        if metadata and result.get("status") == "ok":
            _patch_document_metadata(result["document_id"], metadata)

        # Rename the stored file_name to the logical filename for readability
        if result.get("status") == "ok":
            _patch_document_filename(result["document_id"], filename)

        return result
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def ingest_bytes(
    data: bytes,
    filename: str,
    metadata: dict[str, Any] | None = None,
    source: str = "generated",
) -> dict[str, Any]:
    """Ingest raw bytes (e.g. a PDF generated in memory by document_engine).

    Args:
        data:     Raw file bytes.
        filename: Logical filename (used for extension detection and display).
        metadata: Optional metadata override.
        source:   Source tag.

    Returns:
        Summary dict from the ingestion pipeline.
    """
    if not data:
        logger.warning("ingest_bytes called with empty bytes for %s", filename)
        return {"status": "skipped", "reason": "empty_bytes"}

    suffix = Path(filename).suffix or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        pipeline = _get_pipeline()
        result = pipeline.ingest_document(tmp_path, source=source)

        if metadata and result.get("status") == "ok":
            _patch_document_metadata(result["document_id"], metadata)

        if result.get("status") == "ok":
            _patch_document_filename(result["document_id"], filename)

        return result
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_db_conn():
    """Open a database connection via DATABASE_URL."""
    import psycopg2
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return psycopg2.connect(dsn)


def _patch_document_metadata(document_id: str, metadata: dict[str, Any]) -> None:
    """Merge custom metadata into the ingested_documents record."""
    try:
        conn = _get_db_conn()
        cur  = conn.cursor()
        cur.execute(
            """
            UPDATE ingested_documents
            SET
                document_type = COALESCE(%s, document_type),
                department    = COALESCE(%s, department),
                source        = COALESCE(%s, source),
                metadata      = metadata || %s::jsonb
            WHERE document_id = %s
            """,
            (
                metadata.get("document_type"),
                metadata.get("department"),
                metadata.get("source"),
                json.dumps(metadata),
                document_id,
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:
        logger.warning("Could not patch metadata for %s: %s", document_id, exc)


def _patch_document_filename(document_id: str, filename: str) -> None:
    """Update the display filename for a document."""
    try:
        conn = _get_db_conn()
        cur  = conn.cursor()
        cur.execute(
            "UPDATE ingested_documents SET file_name = %s WHERE document_id = %s",
            (filename, document_id),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:
        logger.warning("Could not patch filename for %s: %s", document_id, exc)
