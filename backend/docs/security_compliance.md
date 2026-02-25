# Security & Compliance Mapping (Nigeria)

This document maps PlacewareBot controls to Nigerian regulatory bodies and NDPC data protection obligations, with actionable implementation steps.

## NDPC (Nigerian Data Protection Commission)
- Lawful basis & consent: Capture consent and purpose on lead forms; log timestamp and source.
- Data minimization: Collect only necessary PII; avoid unnecessary free-form sensitive data.
- Retention & deletion: Define retention periods; implement deletion/anonymization jobs and DSR workflows (access/erase/export).
- Security: TLS 1.2+ everywhere, HSTS; AES-256-GCM at rest for PII; key management via KMS/Vault with rotation; encrypted backups.
- Transparency: Privacy notice endpoint and versioned policy; breach notification runbook.

Implementation Notes:
- Add `AT_REST_KEY` (base64 32-byte) for AES-GCM; encrypted fields in `placeware_leads`.
- Harden JWT (exp/iat/aud) and role-based access; audit sensitive operations.
- Create `/privacy` route serving policy from config.
- Add DSR endpoints and admin workflows.

## NAFDAC (Pharmaceutical Controls)
- Content controls: Prohibit diagnostic/prescriptive guidance; maintain pharma disclaimer on all LLM outputs.
- Product info governance: Track batch/expiry and changes with audit trails; advertising content approval workflow.
- Safety: Flag near-expiry stock for safe clearance and quality checks.

Implementation Notes:
- Persist `batch_id` and `expiry_date`; compute days-to-expiry and alert thresholds.
- Add `/inventory/expiring` and alerting via email/webhook; integrate marketing discount templates.

## PCN (Pharmacy Council of Nigeria)
- Professional practice: Restrict pharmacist-only actions (clinical advice, dispensing decisions) to licensed roles.
- Premises & licensing: Record and verify premises identifiers for distribution/retail modules.

Implementation Notes:
- Role gates for pharmacist actions; store license identifiers in staff registry.
- Add approval workflows for any clinical-adjacent features.

## Operational Security Controls
- Secrets: `.env`/Vault, no hard-coded credentials; rotate regularly.
- Input validation: OWASP validation/sanitization; prevent injection/XSS.
- Logging: Redact PII; structured logs with request IDs.
- Monitoring: Rate limiting, anomaly detection, alerts.

## Roadmap Items
- DSR endpoints/tests; privacy notice endpoint.
- Batch/expiry in inventory schema and expiring-stock alerts.
- Background tasks for email/alerts; metrics on compliance events.
