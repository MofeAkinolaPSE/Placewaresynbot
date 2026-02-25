from fastapi import APIRouter, Request, HTTPException
from src.middleware import verify_jwt
import os, json, time

router = APIRouter()
RUNS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "reconciliation_runs.json")


def _load_runs():
    if not os.path.exists(RUNS_PATH):
        return []
    try:
        with open(RUNS_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return []


def _write_runs(runs):
    parent = os.path.dirname(RUNS_PATH)
    if not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(RUNS_PATH, "w", encoding="utf-8") as fh:
        json.dump(runs, fh, indent=2)


@router.post("/reconcile/trigger")
async def trigger_reconcile(request: Request):
    # admin only
    verify_jwt(request, required_role="admin")
    runs = _load_runs()
    run = {"run_id": int(time.time()), "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"), "status": "running"}
    runs.append(run)
    _write_runs(runs)
    # For now, perform a quick local stub: mark complete
    run["status"] = "complete"
    run["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_runs(runs)
    return {"status": "done", "run": run}


@router.get("/reconcile/runs")
async def list_runs(request: Request):
    verify_jwt(request)
    return _load_runs()
