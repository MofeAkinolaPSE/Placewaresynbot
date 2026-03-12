from fastapi import APIRouter, Request, HTTPException
from src.workflow.workflow_jobs import engine
from src.middleware import verify_jwt, require_role
import uuid

router = APIRouter()


@router.get("/workflow/jobs")
async def list_jobs(request: Request):
    verify_jwt(request)
    return engine.list_jobs()


@router.get("/workflow/jobs/metrics")
async def get_workflow_metrics(request: Request):
    verify_jwt(request)
    return engine.bottleneck_metrics()


@router.get("/workflow/jobs/{job_id}")
async def get_job(request: Request, job_id: str):
    verify_jwt(request)
    j = engine.get_job(job_id)
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    return j


@router.post("/workflow/jobs/{job_id}/approve")
async def approve_job(request: Request, job_id: str):
    # require role manager or admin
    payload = verify_jwt(request)
    roles = set(payload.get("roles") or [])
    if not ("admin" in roles or "manager" in roles or "management" in roles):
        raise HTTPException(status_code=403, detail="Insufficient role to approve")
    approver = payload.get("sub") or payload.get("user_id") or "unknown"
    ok = engine.approve_job(job_id, approver)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found or not approvable")
    return {"status": "approved", "job_id": job_id}


@router.post("/workflow/trigger-discover")
async def trigger_discover(request: Request):
    verify_jwt(request, required_role="admin")
    created = engine.discover_and_enqueue()
    return {"created_jobs": created}


@router.post("/workflow/jobs/escalate/run")
async def run_workflow_escalation_pass(request: Request):
    payload = verify_jwt(request)
    roles = set(payload.get("roles") or [])
    if not ("admin" in roles or "manager" in roles or "management" in roles):
        raise HTTPException(status_code=403, detail="Insufficient role to run escalation")
    return engine.run_escalation_pass()
