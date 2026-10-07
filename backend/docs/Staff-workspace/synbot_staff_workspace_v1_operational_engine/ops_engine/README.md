# Synbot Operational Task Engine v1

Turns business/operational events into staff tasks using configurable rules.

Flow:
BUSINESS EVENT -> RULE MATCH -> ASSIGNEE RESOLUTION -> STAFF TASK -> TASK COMPLETION -> OPERATIONAL EVENT/AUDIT

This package is intentionally domain-neutral. A rule can target procurement, inventory, clinical, HR, finance, logistics, or any future module.

## Core concepts
- `operational_task_rules`: declarative rules defining which events create tasks.
- `OperationalEvent`: normalized event envelope from any Synbot business module.
- `OperationalTaskService`: evaluates rules, creates tasks idempotently, and records provenance.
- `AssigneeResolver`: resolves a staff member from explicit staff, role, team, department, or facility context.
- `entity_type/entity_id`: links the generated task to the real business object.

## Example
`shipment.received` + rule `Receive incoming shipment` -> task assigned to receiving team.

## Integration
Mount the router under `/api/v1`. Publish normalized events to `POST /api/v1/operational/events` or call `OperationalTaskService.handle_event()` from internal services/event consumers.

Production recommendation: call the service from the transaction/outbox consumer, not directly from an untrusted browser.
