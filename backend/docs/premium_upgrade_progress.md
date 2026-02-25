# Premium Upgrade Progress Tracker

Date baseline: 2026-02-13  
Track: Option A (Balanced) — Pipeline hardening + compliance first, then controls, then ML.

## Program Stages

### Stage 1 — Data Pipeline Hardening (In Progress)
Status: Active

Completed:
- Tolerant schema mapping with aliases and header normalization (including prefixed export cases).
- Multi-format ingestion support (CSV/JSON/XLSX).
- Row-level normalization rejection handling (valid rows continue processing).
- Import job lifecycle persistence (`placeware_import_jobs`).
- Rejection queue persistence (`placeware_import_rejections`).
- Lineage and quality diagnostics in audit + job records.
- Idempotency key support for import endpoints.
- Import job observability endpoints:
  - `GET /imports/jobs`
  - `GET /imports/jobs/{job_id}`
- Async queued processing for imports:
  - `POST /sage/import?async_mode=true`
  - `POST /hr/import?async_mode=true`
  - `POST /ops/import?async_mode=true`
  - `POST /crm/import?async_mode=true`
- Retry/backoff attempts metadata for Sage import processing.
- Quality gate policy with explicit `partial_success` status:
  - minimum quality score threshold
  - maximum rejection-rate threshold
- KPI promotion controls for downstream analytics:
  - gate-passing Sage imports promote the active KPI batch
  - `partial_success` preserves the previous promoted batch
  - analytics readers resolve promoted batch with fallback to latest succeeded import

Open items:
- None for core Stage 1 hardening scope.

### Stage 2 — Compliance & Governance Baseline
Status: Completed (Baseline)
Scope next:
- Formal data retention/version policy fields. ✅
- IFRS alignment checks for finance import domains. ✅
- Expanded audit event taxonomy for 21 CFR Part 11 style traceability. ✅
- E-signature context for high-risk actions (approval reason, attestation text, signature hash reference). ✅

### Stage 3 — Project Controls Core (Scope/Cost/Risk/Change)
Status: In Progress

### Stage 4 — Finance/Payroll Foundation
Status: In Progress

### Stage 5 — ML Baseline Layer
Status: In Progress

## Session Log

### Session 1 (Architecture Blueprint)
- Locked Option A as execution strategy.

### Session 1 Implementation Pass A
- Implemented tolerant ingestion and schema-drift resilience.

### Session 1 Implementation Pass B
- Implemented pipeline job/rejection schema and endpoint lifecycle tracking.

### Session 1 Implementation Pass C
- Added idempotency-key replay protection and job status APIs.

### Session 1 Implementation Pass D
- Added async queued execution for `sage/import` and attempt/backoff metadata tracking.

### Session 1 Implementation Pass E
- Added quality-threshold gate logic and `partial_success` status policy.
- Extended async queue mode to HR/Ops/CRM imports.

### Session 1 Implementation Pass F
- Implemented KPI promotion-gate behavior tied to quality outcomes.
- Added promotion persistence and promoted-batch analytics filtering with succeeded-batch fallback.

### Session 1 Implementation Pass G
- Standardized retry/backoff depth and attempt metadata behavior across HR/Ops/CRM async processors.
- Added targeted tests to confirm retry-attempt journaling on transient failures.

### Session 1 Implementation Pass H
- Extracted shared import retry helper and applied it to Sage/HR/Ops/CRM processors.
- Removed duplicated retry/error-path branches while preserving existing job metadata semantics.

### Session 2 Stage 2 Kickoff
- Added formal retention/version governance fields to import jobs (`schema_version`, `policy_version`, `retention_days`, `retention_expires_at`).
- Added `placeware_data_policies` governance table + admin RLS policy and seeded baseline domain policies.
- Wired `create_import_job` to resolve active policy and compute deterministic retention expiry on insert.

### Session 2 Stage 2 Pass B
- Added non-blocking IFRS baseline finance checks for Sage `ar/ap/gl` datasets.
- Persisted IFRS warning signals under import `lineage.compliance.ifrs_warnings` for audit/compliance visibility.
- Added unit tests covering anomaly detection and clean balanced-finance scenarios.

### Session 2 Stage 2 Pass C
- Expanded audit model with taxonomy fields (`event_class`, `action`, `outcome`, `reason_code`, actor/subject IDs, `trace_id`).
- Added automatic taxonomy derivation in `audit_event` while preserving backward compatibility for existing calls.
- Added migration for existing environments and unit tests for taxonomy derivation/payload insertion.

### Session 2 Stage 2 Pass D (Current)
- Added explicit e-signature audit context fields for high-risk actions (`approval_reason`, `attestation_text`, `signature_hash_ref`).
- Added deterministic signature hash derivation for attested audit events and migration support for existing environments.
- Applied signed audit context to workflow approvals and admin user-management actions.

### Session 3 Stage 3 Kickoff (Current)
- Added core project-controls schema (`projects`, `scope_items`, `cost_items`, `risk_register`, `change_requests`) with RLS policies and indexes.
- Added migration for existing environments and synced full bootstrap schema.
- Implemented admin APIs for create/list flows and approval-gated change decisions with audit coverage.

### Session 3 Stage 3 Pass B (Current)
- Added status governance rules for project-controls domain:
  - allowed status allow-lists for project/scope/cost/risk entities
  - change-request status transition graph validation (`proposed -> under_review -> approved -> implemented`, with controlled rejection/reopen path)
- Added high-impact change decision policy:
  - high-impact detection based on scope/cost/schedule thresholds
  - mandatory structured `approval_reason` codes for high-impact approvals/implementation decisions
- Added risk-score threshold controls:
  - elevated risk requires mitigation plan
  - highest-risk entries require explicit owner assignment
  - high-risk entries cannot start in `closed` status
- Added focused API tests for transition guards and policy validation paths.

### Session 3 Stage 3 Pass C (Current)
- Added explicit status-update endpoints for project controls:
  - `POST /controls/scope/{scope_item_id}/status`
  - `POST /controls/cost/{cost_item_id}/status`
  - `POST /controls/risk/{risk_id}/status`
- Added status transition policy graphs for scope/cost/risk and enforced transition guards on update endpoints.
- Added blocked-transition audit enrichment with policy metadata:
  - event: `controls_transition_denied`
  - details include `policy_code` + `rejection_reason` + attempted transition context.
- Added risk closure guardrails on status updates to enforce mitigation/owner requirements for elevated risk scores.
- Added focused tests for transition blocking, allowed transitions, and denial-audit payload validation.

### Session 3 Stage 3 Pass D (Current)
- Added project-controls rollup endpoint for control posture visibility:
  - `GET /controls/rollup` (optional `project_id` filter)
  - includes status distributions, high-risk open count, and pending change approvals
- Added compliance-oriented controls audit export endpoint:
  - `GET /controls/audit/export`
  - supports time-window and entity filters (`start_at`, `end_at`, `event_class`, `subject_type`, `event_type`) and `json|csv` output
- Added flattened CSV export fields for policy evidence (`policy_code`, `rejection_reason`) to support governance reporting.
- Added focused endpoint tests for rollup response and audit export (CSV + invalid format validation).

### Session 3 Stage 3 Pass E (Current)
- Added DB-level rollup optimization path:
  - new SQL RPC function `placeware_controls_rollup(p_project_id uuid)` via incremental migration.
  - backend rollup helper now executes RPC first and falls back to app-side aggregation when RPC is unavailable.
- Synced bootstrap schema with the same rollup RPC for fresh environment parity.
- Added signed controls export audit metadata persistence:
  - every `GET /controls/audit/export` call now records `controls_audit_exported` audit event.
  - persisted metadata includes `exported_by`, `exported_at`, `filter_hash`, applied filters, and row count.
  - signature hash reference is generated and stored for export evidence integrity.
- Added focused tests for RPC-first rollup behavior and signed export metadata auditing.

### Session 4 Stage 4 Pass A (Current)
- Added deterministic lineage-key generation for finance/payroll ingestion paths.
  - Sage and HR import processors now compute and persist `lineage_key` in job metadata and response payloads.
  - Audit events for Sage/HR imports now include lineage key for traceability joins.
- Added payroll baseline control checks (non-blocking compliance warnings):
  - negative salary detection
  - negative overtime value detection
  - absence hours range checks
- Payroll baseline warnings are attached under import `lineage.compliance` for governance visibility.
- Added focused unit tests for deterministic lineage-key stability and payroll baseline warning detection.

### Session 4 Stage 4 Pass B (Current)
- Added finance/payroll control-score rollup computation per import job:
  - warning density and severity index calculation
  - weighted penalty model converted to normalized `control_score` (0-100)
  - warning-code and severity breakdown metadata
- Integrated control rollup into import processing outputs:
  - Sage and HR processors now persist control rollup in job metadata and include it in immediate API responses.
  - lineage now carries `control_rollup` for downstream governance views.
- Exposed control rollup in `GET /imports/jobs/{job_id}`:
  - endpoint now returns `control_rollup` at top-level.
  - fallback derivation computes rollup from stored lineage/counts for older jobs without metadata.
- Added focused tests for control rollup scoring and job-detail exposure.

### Session 4 Stage 4 Pass C (Current)
- Added domain-aware control threshold policy persistence:
  - `placeware_data_policies.controls_config` JSON policy field added for scoring calibration.
  - seeded domain defaults for active policies (finance-weighted for Sage, payroll-weighted for HR, standard for Ops/CRM).
- Updated import policy resolution to retrieve and apply `controls_config` with safe code defaults when unavailable.
- Applied policy-calibrated scoring in control rollup computation:
  - severity weights and penalty caps now sourced from domain policy config.
  - rollup output includes effective policy parameters for auditability.
- Added focused tests to verify policy-sensitive scoring and stable job-detail rollup exposure.

### Session 4 Stage 4 Pass D (Current)
- Added admin what-if policy preview endpoint:
  - `POST /imports/policy/preview`
  - compares baseline control-score output against proposed policy override values before policy activation.
- Endpoint returns baseline, preview, and deltas (`control_score`, `warning_density`, `severity_index`) plus merged effective policy.
- Added domain validation guard (`sage|hr|ops|crm`) for preview requests.
- Added focused endpoint tests for preview delta output and invalid-domain rejection.

### Session 4 Stage 4 Pass E (Current)
- Added policy activation workflow endpoint:
  - `POST /imports/policy/activate`
  - promotes a previewed controls config to active policy version for a domain.
- Added activation evidence persistence fields on `placeware_data_policies`:
  - `approved_by`, `approval_reason`, `attestation_text`, `signature_hash_ref`
  - introduced incremental migration for existing environments and synced bootstrap schema.
- Activation flow now enforces controls-config validation, requires approval reason, computes deterministic signature hash, and emits signed audit event (`import_policy_activated`).
- Added focused endpoint tests for successful activation and controls-config validation failures.

### Session 4 Stage 4 Pass F (Current)
- Added policy version history endpoint:
  - `GET /imports/policy/history?domain=...&limit=...`
  - returns policy version timeline for controlled review.
- Added signed rollback endpoint:
  - `POST /imports/policy/rollback`
  - restores controls config from a target policy version by creating a new active rollback version.
- Rollback workflow includes approval attestation and deterministic signature hash evidence.
- Added DB helpers for policy version listing and targeted version retrieval.
- Added focused tests for history retrieval, rollback success path, and rollback target-not-found handling.

### Session 5 Stage 5 Pass A (Current)
- Defined ML baseline feature data contract (`ml_baseline_2026.1`) for Sage and HR domains.
- Added auditable feature snapshot export endpoint:
  - `GET /ml/features/export?domain=sage|hr&format=json|csv`
  - derives features from promoted batch (fallback to latest successful batch)
  - records signed audit event `ml_feature_snapshot_exported` with deterministic signature hash reference.
- Added bounded snapshot-row retrieval helper for batch feature extraction.
- Added focused tests for JSON export success and no-batch error handling.

### Session 5 Stage 5 Pass B (Current)
- Added ML drift baseline summary endpoint:
  - `GET /ml/features/drift/summary?domain=sage|hr`
  - compares current promoted/successful batch feature vector against prior succeeded baseline batch.
- Added feature quality summary metrics:
  - null-feature rate and zero-feature rate with numeric feature coverage.
- Added per-feature distribution deltas:
  - current vs baseline values, signed delta, absolute delta, and percent delta where baseline is non-zero.
- Added signed audit event `ml_feature_drift_summarized` with deterministic signature hash evidence.
- Added focused tests for drift summary with baseline comparison and no-prior-baseline fallback.

### Session 5 Stage 5 Pass C (Current)
- Added policy-based drift severity tagging for ML feature baselines:
  - resolved per-domain drift thresholds from policy config (`controls_config.ml_drift`) with secure defaults.
  - applied severity classification (`warning|error|critical`) across quality-rate and per-feature drift deltas.
- Extended drift summary payload with alert outputs:
  - `alerts.highest_severity`, `alerts.severity_counts`, and structured feature/quality alert entries.
- Added persisted trend-history endpoint backed by signed audit events:
  - `GET /ml/features/drift/history?domain=sage|hr&limit=...`
  - returns recent drift trend points and aggregated severity + delta summaries.
- Added focused tests for policy severity behavior and drift-history filtering/aggregation.

### Session 5 Stage 5 Pass D (Current)
- Added drift acknowledgement workflow endpoint:
  - `POST /ml/features/drift/acknowledge`
  - captures triage owner/status/remediation details with transition guardrails (`triaged|in_progress|accepted_risk|resolved`).
- Added signed remediation export endpoint:
  - `GET /ml/features/drift/remediation/export?domain=sage|hr&format=json|csv&limit=...`
  - exports acknowledgement/remediation evidence for governance reporting.
- Drift acknowledgement and remediation export both emit signed audit evidence (`ml_feature_drift_acknowledged`, `ml_feature_drift_remediation_exported`).
- Added focused tests for valid/invalid acknowledgement transitions and remediation export filtering.

### Session 5 Stage 5 Pass E (Current)
- Added drift KPI scorecard endpoint:
  - `GET /ml/features/drift/scorecard?domain=sage|hr&limit=...`
  - computes domain trend KPIs from signed drift/acknowledgement audit events.
- Added SLA breach indicators:
  - age-to-acknowledge and age-to-resolve metrics per drift batch.
  - policy-configurable SLA thresholds via `controls_config.ml_drift.sla_thresholds` with secure defaults.
- Added scorecard aggregates:
  - `open_high_severity_count`, `pending_ack_count`, `pending_resolution_count`, `ack_breach_count`, `resolve_breach_count`, plus average timing metrics.
- Added signed audit event `ml_feature_drift_scorecard_viewed` for scorecard access traceability.
- Added focused tests for scorecard KPI/SLA behavior and invalid-domain validation.

### Session 5 Stage 5 Pass F (Current)
- Added automated escalation artifacts endpoint:
  - `GET /ml/features/drift/escalations?domain=sage|hr&limit=...`
  - returns unresolved high-severity drift queue plus owner-targeted alert payload groupings.
- Added reminder scheduling preview hook:
  - `POST /ml/features/drift/reminders/preview`
  - produces reminder candidates using unresolved age threshold policy (`reminder_hours_threshold`) with optional request override.
- Added signed audit events for escalation/reminder workflows:
  - `ml_feature_drift_escalations_viewed`
  - `ml_feature_drift_reminders_previewed`
- Added focused tests for owner-grouped escalations and reminder-threshold filtering behavior.

### Session 6 Stage 6 Kickoff (Current)
- Added model registry-lite for demand forecasting using signed audit manifests (no schema churn):
  - `POST /ml/models/demand-forecast/train`
  - `POST /ml/models/demand-forecast/predict`
  - `GET /ml/models/demand-forecast/manifests`
- Implemented dependency-safe forecast model path (`linear_trend_v1`) with holdout evaluation (`mae`, `mae_ratio`) and manifest versioning.
- Added promotion-readiness checks tied to signed drift/remediation posture:
  - blocks readiness when open high-severity drift or SLA resolve/ack posture is not clean.
- Added signed model-governance audit events:
  - `ml_model_manifest_registered`
  - `ml_model_inference_executed`
- Added focused tests for train/register flow, prediction via registered manifest, and manifest listing.

## Strategic Direction (Preserved)
- Build fully in-house enterprise pipeline and ops platform (no external ETL SaaS).
- Sequence remains one stage at a time to reduce risk and rework.
- Keep compliance, IFRS/payroll readiness, and ML path tied to pipeline maturity.

## Current Recommendation
Proceed to Stage 6 Pass B:
- Add first advanced model adapters behind the same manifest contract (XGBoost/LightGBM optional path with fallback), plus offline backtest endpoint and model-comparison leaderboard.
