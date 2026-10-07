# Synbot Staff Workspace v1 — ERD & Migration Notes

## Purpose

Generic staff-workspace layer for Synbot deployments. It is intentionally separate from existing business tables so the same workspace engine can serve Atiat, RoyanHealth, Placeware and future clients.

## Core relationship map

```text
organization
  └── company
       ├── subsidiary
       ├── facility
       │    └── department
       │         └── team
       └── staff
            ├── staff_company_memberships
            ├── staff_teams
            ├── staff_preferences
            ├── staff_tasks
            │    ├── staff_task_checklists
            │    ├── staff_task_comments
            │    └── staff_task_activity
            ├── staff_requests
            │    ├── staff_request_messages
            │    └── staff_request_activity
            ├── staff_notifications
            ├── staff_reminders
            ├── staff_time_sessions
            │    └── staff_break_sessions
            └── staff_work_events
```

## Operational bridge

Tasks and work events can reference business records polymorphically:

```text
entity_type = purchase_order
entity_id   = PO-1024
```

or:

```text
entity_type = patient
entity_id   = 928
```

The workspace does not directly own the business transaction. Completion is passed to the relevant operational service.

## Existing Royan integration

Existing design already contains:

- `royan_staff`
- `royan_timesheets`
- `royan_procurement_shipments`
- `royan_operations_events`

The new workspace should map into these rather than replace them.

Recommended direction:

```text
Synbot staff
      │
      ├── time sessions ─────→ Royan timesheets adapter
      │
      ├── operational tasks ─→ Royan procurement adapter
      │
      └── work events ───────→ Royan operations events adapter
```

## Multi-company rule

A staff member may have more than one `staff_company_memberships` row.

The authenticated backend determines the staff member's permitted company/subsidiary/facility scope. The frontend must never be trusted to provide security scope.

## ID strategy

New workspace records use UUIDs.

Existing Royan clinical IDs remain unchanged.

Business references therefore use:

```text
entity_type TEXT
entity_id   TEXT
```

This allows UUID-based workspace records to reference existing bigint clinical/operational records without changing their primary keys.

## Migration safety

The supplied SQL creates new tables only. It does not alter or rename existing Royan tables.

The first production deployment should run against a staging database, validate constraints and indexes, then perform staff mapping from the existing `royan_staff` registry.

## First operational proof

Use Procurement → Shipment as the first end-to-end workflow:

```text
Purchase order
    ↓
Shipment expected
    ↓
Operational task rule
    ↓
Staff task
    ↓
Staff Workspace
    ↓
Receive shipment
    ↓
Quantity / batch / expiry
    ↓
Complete
    ↓
Operational adapter
    ↓
Inventory / finance event
    ↓
Work event + audit trail
```
