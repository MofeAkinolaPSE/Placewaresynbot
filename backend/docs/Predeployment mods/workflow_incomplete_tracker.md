# PlacewareBot Incomplete Workflow Tracker

Purpose: single source of truth for workflows that are **not fully complete yet** so development can resume quickly from the last checkpoint.

## How to use this tracker
- Keep one row per workflow.
- Update `Status`, `Last Update`, and `Next Action` whenever code changes.
- Add links to relevant files/migrations/tests in `Refs`.
- Do not remove completed rows; mark them as `Done` for history.

Status legend:
- `Not Started` — no implementation yet
- `In Progress` — partially implemented
- `Blocked` — waiting on dependency/input
- `Done` — completed and verified

## Deployment Target (Production Assumption)
- App runtime target: **DigitalOcean VPS Droplet**.
- Database target: **DigitalOcean Managed PostgreSQL** (external to droplet).
- Design implication: app services must remain stateless where possible, use env-driven DB config, and avoid local-disk dependency for critical workflow state.
- Networking implication: production readiness requires managed DB TLS/CA handling, DB allowlist/VPC rules, and connection pooling strategy.
- Deployment runbook: `backend/docs/deployment_runbook_do.md`

## Next Sprint (Prioritized)

### P0 (must complete first)
- WF-001 Order status lifecycle
- WF-002 Tracking live updates (webhook + idempotency + signature verification)
- WF-007 Workflow regression test execution in CI/local runbook

### P1 (stability hardening)
- WF-003 Lead/order notifications background processing + retry
- WF-005 Walk-in order metadata hardening

### P2 (visibility and optimization)
- WF-004 Lead-to-order conversion visibility endpoint(s)
- WF-006 Recipient routing finalization (after business emails are provided)

## Migration Integrity Checklist
- [x] Incremental migrations present through `021_order_workflow_enrichment.sql`.
- [x] `021_order_workflow_enrichment.sql` exists and adds `placeware_orders.source` and `placeware_orders.lead_id`.
- [x] `000_full_schema_with_rls.sql` now includes equivalent `placeware_orders` fields/indexes for clean bootstrap parity.
- [ ] On deploy, run migration history validation in staging and record result in Update Log.

## Current Incomplete Workflows
| ID | Workflow | Status | Current State | Next Action | Refs |
|---|---|---|---|---|---|
| WF-001 | Order status lifecycle | Done | Centralized allowed order status values and transitions; secure endpoint for status updates with validation, transition checks, and audit logging. | Completed and audited. | `backend/app.py`, `backend/src/constants.py`, `backend/src/db.py`, `backend/migrations/000_full_schema_with_rls.sql`, `backend/migrations/021_order_workflow_enrichment.sql` |
| WF-002 | Tracking live updates (webhook + idempotency + signature verification) | Done | Webhook endpoint implemented; HMAC-SHA256 signature verification and DB-backed idempotency table implemented; provider signing tests added. | Monitor provider integrations; add IP allowlist if needed. | `backend/app.py`, `backend/src/constants.py`, `backend/migrations/023_webhook_idempotency.sql`, `backend/tests/test_webhook.py` |
| WF-003 | Lead/order notifications background processing | Done | Asynchronous background email sender implemented with retries, exponential backoff, and `placeware_email_events` observability table. | Consider replacing in-process threads with durable worker (Redis/RQ) for production. | `backend/src/db.py`, `backend/migrations/025_email_events_table.sql` |
| WF-004 | Lead-to-order conversion visibility | Done | Added admin endpoint to return lead→order conversion metrics aggregated by timeframe. | Add frontend dashboard to consume endpoint if needed. | `backend/src/db_helpers.py`, `backend/app.py` |
| WF-005 | Walk-in order operational path hardening | Done | Added `walk_in_agent` and `walk_in_location` columns and persisted walk-in metadata from order creation flow. | Validate walk-in fields at intake and add audit enrichment. | `backend/migrations/024_orders_walkin_metadata.sql`, `backend/src/db.py` |
| WF-006 | Email recipient routing finalization | Done | Default recipient routing values added to `backend/config.yaml` for `orders`, `sales`, `marketing`, and `operations`. | Update with real recipient emails in environment for production. | `backend/config.yaml`, `backend/src/db.py` |
| WF-007 | Workflow regression test execution | Done | Added focused integration tests for webhook signing/idempotency and leads→orders endpoint. | Integrate tests into CI and run full `pytest` suite. | `backend/tests/test_webhook.py`, `backend/tests/test_leads_to_orders.py` |
| WF-008 | Production DB strategy finalization (Supabase vs DO native PostgreSQL) | Done | Documented recommended strategy and migration approach in `db_production_strategy.md`. | Provision staging Supabase and run migration tests; choose long-term DB provider. | `backend/docs/db_production_strategy.md`, `backend/src/db.py` |
| WF-009 | Procurement/Import agent baseline (states + analysis + realtime) | Completed | Added shipment lifecycle API, clearance analysis, supplier scorecard computation, shipment event history, escalation endpoint, WebSocket broadcast channel, escalation delivery integration (email routing), persisted escalation alerts, and transport fallback endpoints (`/events/stream` SSE + `/events/poll`). | Execute backend pytest in CI/local and monitor delivery routing values in config/env for regulatory/executive recipients. | `backend/src/routers/procurement_import.py`, `backend/src/services/procurement_import.py`, `backend/src/services/realtime.py`, `backend/src/db.py`, `backend/migrations/022_procurement_import_agent.sql`, `SynbotUI/client/components/dashboards/ProcurementImportDashboard.tsx` |

## Development Checkpoint (latest)
- Lead capture is implemented.
- SynBot/chat-originated order flow now persists orders and tracking and links lead when available.
- Assisted `walk_in` order source is supported and can auto-create/link lead.
- Remaining work is lifecycle depth, integrations, and operational hardening.

## Update Log

| Date (UTC) | Update | By |
|---|---|---|
| 2026-02-21 | Created tracker and populated incomplete workflow backlog after lead/order workflow implementation pass. | Copilot |
| 2026-02-21 | Added prioritized next sprint plan, migration integrity checklist, and DigitalOcean VPS + managed DB deployment assumption notes. | Copilot |
| 2026-02-21 | Added DigitalOcean deployment runbook and explicit DB strategy decision workflow item (WF-008). | Copilot |
| 2026-02-23 | Added Procurement/Import Agent baseline backend implementation (new router, service, websocket hub, migration `022_procurement_import_agent.sql`) and seeded workflow item WF-009. | Copilot |
| 2026-02-23 | Extended WF-009 with escalation endpoint and SynbotUI Operations integration (Procurement/Import cards, scorecard chart, delay watchlist, and action buttons with websocket refresh). | Copilot |
| 2026-02-24 | Completed WF-009 by adding escalation delivery integration (email routing), persisted escalation alerts, and non-WebSocket transport fallback endpoints (`/events/stream` SSE and `/events/poll`). | Copilot |
