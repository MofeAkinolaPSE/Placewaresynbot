# Synbot Staff Workspace v1 — FastAPI foundation

This package is the first backend implementation slice for the Staff Workspace.

## Included
- `GET /health`
- `GET /api/v1/workspace` — personalised My Day aggregation
- Tasks: list, create, read, patch, accept/start/wait/complete/verify/close/reopen/cancel
- Time: today/start/pause/resume/end
- Notifications: list + mark read
- SQLAlchemy 2.x async models
- Repository/service separation
- Organisation boundary and company context carried from the authenticated staff identity

## Integration
1. Apply `synbot_staff_workspace_v1_migration.sql` to the target PostgreSQL database.
2. Copy `backend/app` into the existing FastAPI application or mount these modules under its API package.
3. Set `DATABASE_URL` to an async PostgreSQL URL such as `postgresql+asyncpg://...`.
4. Replace `app.core.auth.get_current_staff` with the existing Synbot JWT/session dependency. The header resolver is only a development integration seam.
5. Run with `uvicorn app.main:app --reload`.

## Security rule
The frontend must never define organisation/company scope as the authority. The authenticated identity is the source of truth, and every repository query must constrain by organisation and staff membership. Company switching should additionally validate the requested company against `staff_company_memberships` before setting the active context.

## Next backend slice
Add the collaboration/request engine, checklist/comments/activity, operational task rules, RBAC permission checks, and WebSocket event delivery. Then connect the workspace to Procurement/Inventory/Clinical business services.
