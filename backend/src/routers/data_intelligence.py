"""data_intelligence.py — ACE Data Intelligence Layer API.

Exposes the Relationship/Orphan Auditor, Table Classification, and Field
Coverage Matrix (Data Lineage Engine) as read-only, admin-only endpoints.

See data-assimilation/docs.md/ACE-Data-Intelligence-Layer.md for the full
design. Report-only surface — nothing here writes to the database.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from src.middleware import require_role
from src.services import lineage_service, relationship_auditor_service

log = logging.getLogger(__name__)
router = APIRouter(prefix="/data-intel", tags=["data-intelligence"])

_require_admin = require_role("admin")


@router.get("/tables")
def get_table_classification(_u=Depends(_require_admin)):
    return relationship_auditor_service.classify_tables()


@router.get("/relationships")
def get_relationships(_u=Depends(_require_admin)):
    return {
        "soft_relationships": relationship_auditor_service.scan_soft_relationships(),
        "real_foreign_keys": relationship_auditor_service.scan_information_schema(),
    }


@router.get("/relationships/{name}/orphans")
def get_relationship_orphans(
    name: str,
    limit: int = Query(default=50, ge=1, le=500),
    _u=Depends(_require_admin),
):
    try:
        return relationship_auditor_service.sample_orphans(name, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/integrity-score")
def get_integrity_score(_u=Depends(_require_admin)):
    return relationship_auditor_service.integrity_score()


@router.get("/coverage")
def get_coverage(_u=Depends(_require_admin)):
    report = lineage_service.field_coverage_report()
    return {
        **report,
        "missing_columns": lineage_service.missing_columns_report(),
    }
