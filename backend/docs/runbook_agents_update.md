# Runbook: Agents & Workflow Migration Notes

This runbook summarizes the recent agent and workflow additions, migration steps, and quick commands for local verification.

Files added:
- `backend/migrations/030_workflow_tables.sql` — creates `workflow_jobs`, `replenishment_requests`, `batch_status_locks`, `chain_of_custody_events`, `credit_risk_actions`.
- `backend/src/agents/*` — several new agents: `import_clearance`, `expiry_monitoring`, `cold_room_capacity`, `cold_chain_integrity`, `logistics_optimization`, plus earlier agents.
- `backend/src/workflow/*` — helpers for `batch_locking`, `chain_of_custody`, `expiry_prevention`, `credit_risk`.
- `backend/src/routers/*` — API endpoints for `workflow`, `custody`, `promotions`, and `cache` UI.

Local verification steps:

1. Apply DB migrations (Postgres):

```bash
psql $DATABASE_URL -f backend/migrations/000_full_schema_with_rls.sql
psql $DATABASE_URL -f backend/migrations/030_workflow_tables.sql
```

2. Run tests locally:

```bash
pip install -r backend/requirements.txt
pytest -q backend
```

3. Start backend for manual testing:

```bash
cd backend
uvicorn app:app --reload
```

Notes & Recommendations:
- Review `TABLE_*` names in `src/constants.py` before deploying to ensure they match your production schema.
- The `batch_locking` helpers call Supabase SDK; if you migrate off Supabase, replace with direct DB/ORM calls.
- The shared TTL cache used by agents is in `src/routers/cache_ui.py` and `src/utils/ttl_cache.py` — ensure the UI reads from `/cache/get/{key}`.
- Add monitoring/alerts for the `workflow_jobs` table to detect stuck or failed jobs.

Security:
- Ensure `JWT_SECRET` and other secrets are populated in environment; do not commit real secrets.
- Protect the new routers (`/workflow/*`, `/custody/*`, `/promotions/*`, `/cache/*`) with role checks in middleware before production deployment.
