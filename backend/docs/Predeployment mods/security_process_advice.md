## Security Details & Process Advice

This document captures core security principles, operational controls, and process-level advice for the backend platform.

### Core Security Principles

- Principle of Least Privilege: grant the minimum permissions required for every identity and service.
- RBAC Everywhere: enforce role checks server-side on every API and background job.
- Immutable Event Ledger: record every business action as an immutable event with versioning and hashes for integrity.
- Schema-First Validation: validate all incoming payloads against the Schema Registry before persisting or acting.
- Never Hard-Code Secrets: store credentials, tokens and API keys in a secrets manager or environment variables; never commit them.
- Protect Sensitive Data: encrypt sensitive values at rest and in transit (TLS + DB encryption where available).
- Input & Output Encoding: validate and sanitize inputs; encode outputs to prevent injection classes.
- Audit-First Design: every approval, override, and key operation must be auditable with actor, timestamp, and evidence.

### Device / IoT Authentication

- Use pre-provisioned device keys hashed with SHA256 for storage; accept either JWT (user) or `X-Device-Key` (device) on ingestion endpoints.
- Rotate and revoke keys regularly; store only key hashes and `device_id` metadata in the DB.
- Provisioning: provide an admin-only endpoint or CLI that securely prints a single-use plain key for a device (store only the hash).

### Operational Processes

- Migrations & Releases: apply DB migrations in a controlled staging → canary → production rollout window; snapshot target DB before migration.
- Secrets Rotation: implement periodic rotation for all keys and rotate on incident; integrate with a secrets manager.
- Approvals & Escalation: workflows must capture approver identity, timestamps, and escalation timers; allow overrides only by defined admin roles and log reasons.
- Reconciliation: treat external financial systems (Sage) as source of truth — sync snapshots, lock reconciliation snapshots, and surface discrepancies rather than overwrite.

### Monitoring, Detection & Response

- Instrument agents and event streams with metrics and anomaly alerts (Risk Agent should surface anomalies into an incident queue).
- Preserve full audit trails and expose an immutable export for forensic review.
- Define an incident playbook: detection → contain → notify → investigate → remediate → rotate keys → post-mortem.

### Data Governance & Access Controls

- Segregate financial data access to finance roles only; limit export capabilities and require approval for CSV/Report extraction.
- Use field-level redaction in logs and avoid logging secrets or PII in plaintext.

### Deployment Checklist (Quick)

1. Confirm environment variables are provided via secrets manager.
2. Run test suite and migration plan against staging snapshot.
3. Apply migrations in maintenance window with backups.
4. Provision device keys and verify `iot/ingest` with a test device.
5. Validate RBAC paths with smoke tests for each role.
6. Enable monitoring dashboards and alerting for errors and anomalies.

### Short-term Recommendations

- Add an admin endpoint for device-key provisioning and revocation.
- Centralize constants (bot name, embedding dim, disclaimer) into a single `constants.py` for consistent policy enforcement.
- Add integration tests for RBAC-sensitive flows (promotions, billing, lock/unlock operations).

---

File saved: `backend/docs/security_process_advice.md`
