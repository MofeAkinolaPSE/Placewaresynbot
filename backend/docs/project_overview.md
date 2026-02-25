# PlacewareBot Backend — Architecture & Services Overview

> Workflow backlog tracker: [backend/docs/workflow_incomplete_tracker.md](./workflow_incomplete_tracker.md)
> Deployment runbook (DigitalOcean): [backend/docs/deployment_runbook_do.md](./deployment_runbook_do.md)

This document is the canonical guide to the current backend: endpoints, services, data contracts, environment configuration, security posture, and a pragmatic feature roadmap. It’s intended to help contributors extend the system safely and coherently.

## Architecture

- FastAPI application with modular routers layered over service modules and adapters.
- RAG chat pipeline: user question → 384‑dim embedding → Supabase pgvector RPC → context → DeepSeek LLM → pharma disclaimer.
- Supabase used for storage (leads, audit logs, snapshots, analytics) and RPC (`match_documents`).
- CSV import pipelines for Sage snapshots, HR, Ops, CRM with header validation, normalization, snapshot persistence, and auditing.
- Centralized constants for branding, env keys, table names, and disclaimers in [backend/src/constants.py](../src/constants.py).

## Core Endpoints

- Health: [backend/app.py](../app.py#L163) — `GET /` returns a simple status.
- Chat: [backend/app.py](../app.py#L167) — `POST /chat` RAG + LLM answer with appended disclaimer; saves chat history.
- Lead capture: [backend/app.py](../app.py#L224) — `POST /submit_lead` inserts into Supabase and sends notification email.

### Inventory & Analytics
- Stock snapshot: [backend/app.py](../app.py#L233) — `GET /stock` latest inventory snapshot.
- Stock query: [backend/app.py](../app.py#L245) — `POST /stock` filter by SKUs.
- AR trends: [backend/app.py](../app.py#L260) — `GET /analytics/ar_trends` summary over recent periods.
- KPIs: [backend/app.py](../app.py#L271) — `GET /analytics/kpis` core financial/ops KPIs.
- AR aging: [backend/app.py](../app.py#L281) — `GET /reports/ar_aging` JSON or CSV buckets.
- AR aging customers: [backend/app.py](../app.py#L300) — `GET /reports/ar_aging/customers` detail per customer.
- AR balance forecast: [backend/app.py](../app.py#L315) — `GET /analytics/forecast/ar_balance` rolling + forecasted series.

### Workflow & Audit
- Intent: [backend/app.py](../app.py#L331) — `POST /workflow/intent` create orchestration intents with basic recommendations.
- Approval: [backend/app.py](../app.py#L361) — `POST /workflow/approve` persist approvals; updates intent status.
- Pending intents: [backend/app.py](../app.py#L377) — `GET /workflow/pending` list pending intents.
- Audit logs: [backend/app.py](../app.py#L384) — `GET /audit/logs` recent audit entries.

### Auth & Orders
- Dev token: [backend/app.py](../app.py#L394) — `POST /auth/dev_token` issues JWT for local/testing (guarded by env).
- Submit order: [backend/app.py](../app.py#L404) — `POST /submit_order` validates items, captures optional lead linkage/source, persists order + initial tracking, and emits audit logs.
- Track order: [backend/app.py](../app.py#L422) — `GET /track/{tracking_id}` returns persisted tracking status.

### Sage Adapter
- Import: [backend/app.py](../app.py#L441) — `POST /sage/import` CSV bundle (customers, AR, AP, GL, inventory, staff); validates headers, normalizes, persists snapshots, audits, duplicate detection, and staff sync.
- History: [backend/app.py](../app.py#L564) — `GET /sage/history` filtered audit summaries of imports.

### HR Analytics
- Import: [backend/app.py](../app.py#L601) — `POST /hr/import` payroll + absences CSV; validate + snapshot.
- Summary: [backend/app.py](../app.py#L632) — `GET /hr/analytics/summary` periods-based HR analytics.

### Operations Analytics
- Import: [backend/app.py](../app.py#L642) — `POST /ops/import` orders + downtime CSV; validate + snapshot.
- KPIs: [backend/app.py](../app.py#L673) — `GET /ops/kpis` ops performance indicators.
- Stock turnover forecast: [backend/app.py](../app.py#L681) — `GET /ops/forecast/stock_turnover` rolling + forecast series.

### CRM Risk Scoring
- Import: [backend/app.py](../app.py#L691) — `POST /crm/import` CRM pipeline CSV; validate + snapshot.
- Scores: [backend/app.py](../app.py#L718) — `GET /crm/risk_scores` risk scoring output.

## Data Contracts (Pydantic Models)
Defined in [backend/app.py](../app.py):
- `Lead`: name, email, phone, message, optional service/company_size/contact_pref.
- `StockQuery`: optional `skus: list[str]` to filter stock.
- `OrderItem`: `sku`, `quantity` (must be > 0).
- `SubmitOrder`: customer details + `items: list[OrderItem]` + optional `notes`.
- `TrackingResponse`: id, status, last_update, eta.
- `IntentRequest`: `intent_type`, arbitrary `payload`.
- `ApprovalRequest`: `intent_id`, `approved`, optional `approver_note`.

## Services & Responsibilities

### Retrieval & LLM
- Retrieval: [backend/src/retrieval.py](../src/retrieval.py) — `QnARetriever.retrieve()` calls Supabase RPC `match_documents(query_embedding, match_threshold, match_count)` and returns `(question, answer)` pairs.
- LLM: [backend/src/deepseek.py](../src/deepseek.py) — `DeepSeek.generate_response(context, question, instruction?)` calls DeepSeek chat completions with a compliant system prompt; model name via `DEEPSEEK_MODEL`.
- Disclaimer handling: [backend/src/constants.py](../src/constants.py) — `append_disclaimer(text)` to consistently apply NAFDAC disclaimer.

### Persistence & Audit
- DB utilities: [backend/src/db.py](../src/db.py) — lead storage + email, audit logging, stock cache upsert, snapshot inserts, workflow persistence (`save_intent`, `save_approval`, `list_pending_intents`), duplicate import detection, chat history storage, audit retrieval.

### Sage Adapter (Domain/Pharma)
- Schemas: [backend/src/services/sage_adapter/schemas.py](../src/services/sage_adapter/schemas.py) — pydantic models `ImportMeta`, `CustomerRow`, `ARRow`, `APRow`, `GLRow`, `InventoryRow`, `StaffRow`, `ImportBundle`.
- Validation: [backend/src/services/sage_adapter/validators.py](../src/services/sage_adapter/validators.py) — header validation.
- Parsing: [backend/src/services/sage_adapter/parser.py](../src/services/sage_adapter/parser.py) — CSV → list[dict].
- Normalization: [backend/src/services/sage_adapter/normalizer.py](../src/services/sage_adapter/normalizer.py) — dict rows → schema models.
- Service: [backend/src/services/sage_adapter/service.py](../src/services/sage_adapter/service.py) — inventory snapshots, AR summaries, KPIs, aging buckets, customers, GL snapshot.

### Analytics & Intelligence
- Finance forecasting: [backend/src/services/forecasting.py](../src/services/forecasting.py) — rolling average, AR series + forecast.
- HR analytics: [backend/src/services/hr.py](../src/services/hr.py) — payroll + absence period summaries.
- Ops analytics: [backend/src/services/ops.py](../src/services/ops.py) — ops KPIs; stock turnover series + forecast.
- CRM analytics: [backend/src/services/crm.py](../src/services/crm.py) — risk scores and stats.
- Intelligence: [backend/src/services/intelligence.py](../src/services/intelligence.py) — inventory/workforce dashboards, alert creation and retrieval, executive briefing generation.
- Staff ops: [backend/src/services/staff_ops.py](../src/services/staff_ops.py) — staff registry, department views, timesheet entries, batch sync, latest staff snapshot.
- Inventory ops: [backend/src/services/inventory.py](../src/services/inventory.py) — inventory event recording, real‑time stock, summary, movements, latest batch counts.

## Security & Middleware

- JWT roles required for admin/role‑gated endpoints; issuance for local dev via [backend/app.py](../app.py#L394).
- CORS configured via `CORS_ALLOW_ORIGINS` in [backend/src/constants.py](../src/constants.py).
- Rate limiting enforced in middleware: [backend/src/middleware.py](../src/middleware.py) and called per endpoint (e.g., `/chat`, `/stock`).
- Disclaimer appended to all LLM answers to meet pharma compliance.
- Secrets loaded via `.env` and never logged; emails sent via SSL.

## Environment Configuration

Primary `.env` keys consumed (see [backend/src/constants.py](../src/constants.py)):
- Supabase: `SUPABASE_URL`, `SUPABASE_KEY`.
- LLM: `LLM_PROVIDER` (`deepseek` or `service`), `LLM_SERVICE_URL`, `LLM_API_KEY`, `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`.
- Security: `JWT_SECRET`, `RATE_LIMIT`, `DEV_TOKEN_ENABLED`, `CORS_ALLOW_ORIGINS`.
- Email: `EMAIL_FROM`, `EMAIL_PASS`.
- Optional integrations: `SAGE_API_KEY`, `HF_API_URL`, `HF_API_KEY`.

## Data Flow (Chat Path)

1. Client posts `{ question, embedding? }` to `/chat`.
2. If embedding missing, backend calls embedding proxy to obtain 384‑dim vector.
3. `QnARetriever` calls Supabase RPC `match_documents` with threshold and `top_k`.
4. `DeepSeek.generate_response` returns an answer from context + question.
5. `append_disclaimer` adds NAFDAC disclaimer; chat history is saved.
6. Response: `{ answer, bot, sources }`.

## Testing & Local Dev

- Run tests: `pytest -q backend` via the VS Code task.
- Start app locally: `python -m uvicorn app:app --reload` (cwd: `backend/`).
- HF Space embedding proxy available under `gradio-embed/` for offline dev; can stub a 384‑vector.

## Current State (Summary)

- RAG chat path implemented with DeepSeek and Supabase retrieval.
- Inventory, analytics, workflow, HR, Ops, CRM endpoints are scaffolded with validation, snapshot persistence, and audit logs.
- JWT dev issuance, CORS, rate limiting, and disclaimers are in place.
- Placeware‑branded constants centralize bot identity and table names.

## Feature Roadmap (Prioritized)

1. Chat history API: list and fetch chats per `user_id`; filters and pagination.
2. Background email & tasks: move lead/process emails to background tasks; add retries and telemetry.
3. Embedding service hardening: local stub, timeout handling, and observability; consider HF Inference integration.
4. Supabase schema migration completion: ensure all `placeware_*` tables exist; add indexes (especially on audit and snapshots).
5. Role‑based dashboards: aggregate endpoints for admin, HR, Ops, Sales; unify with the `/dashboard` router.
6. Order lifecycle expansion: add status-transition workflows and courier/provider webhooks.
7. Alerts & briefing: persist executive briefings and alert rules; add CRUD endpoints.
8. WP plugin namespace migration: rename `neurolayer-synbot-admin` assets and REST prefix to `placewarebot`.
9. Observability: structured logging, request IDs, minimal metrics (requests/min, errors, latency).
10. CI tests: pytest suite mocking DeepSeek, Supabase RPC for deterministic runs.

## Implementation Notes & Risks

- Validate all CSV headers and rows; reject on mismatch to prevent silent data drift.
- Keep pharma disclaimer centralized; avoid duplicating strings across modules.
- Avoid logging secrets or raw PII; use IDs and counts in logs.
- Maintain least privilege in JWT role checks; never expose admin routes publicly.
- Use Supabase RPC abstraction for retrieval; avoid embedding SQL logic in code.

## Next Steps

- Add `.env.example` (sanitized) reflecting keys in constants.
- Implement chat history listing endpoint + tests.
- Finalize Supabase migrations for `placeware_*` tables per [backend/migrations](../migrations).
- WP plugin rename and REST namespace alignment.
