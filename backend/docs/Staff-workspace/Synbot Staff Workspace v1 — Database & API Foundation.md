# Synbot Staff Workspace v1 — Database & API Foundation

I’ve now anchored the design against the existing RoyanHealth database rather than creating a completely disconnected model. The existing architecture already has separate **Silver operational**, **Gold analytics**, and **Staff & Operations** layers, with `royan_staff`, `royan_timesheets`, `royan_procurement_shipments`, and `royan_operations_events` identified but currently unpopulated.  

I would therefore add the new workspace as a **generic Synbot application layer**, while allowing Royan-specific operational tables to plug into it.

---

## 1. Final ERD direction

This is the relationship model I'd freeze for v1:

```text
                         ┌────────────────┐
                         │  organizations │
                         └───────┬────────┘
                                 │
                         ┌───────▼────────┐
                         │    companies   │
                         └───────┬────────┘
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
             ┌─────────────┐          ┌─────────────┐
             │ subsidiaries│          │  facilities │
             └──────┬──────┘          └──────┬──────┘
                    │                         │
                    └────────────┬────────────┘
                                 ▼
                         ┌─────────────┐
                         │ departments │
                         └──────┬──────┘
                                ▼
                         ┌─────────────┐
                         │    teams    │
                         └──────┬──────┘
                                │
                         ┌──────▼──────┐
                         │    staff    │
                         └──────┬──────┘
                                │
       ┌────────────────────────┼────────────────────────┐
       │                        │                        │
       ▼                        ▼                        ▼
 staff_preferences       staff_memberships        staff_time_sessions
       │
       │
       └──────────────────────┐
                              ▼
                        ┌─────────────┐
                        │ staff_tasks │
                        └──────┬──────┘
             ┌─────────────────┼─────────────────┐
             ▼                 ▼                 ▼
      task_checklists   task_comments      task_activity
             │
             │
             ▼
      operational entity
      ┌────────┬────────┬────────┐
      ▼        ▼        ▼        ▼
    PO      Invoice   Patient  Shipment
```

And separately:

```text
staff
 │
 ├── staff_requests
 │      └── request_messages
 │
 ├── staff_notifications
 │
 ├── staff_reminders
 │
 └── staff_work_events
```

That's the core.

---

# 2. One change from our previous design

I want to make one architectural improvement before we write SQL.

Instead of putting:

```text
company_id
subsidiary_id
facility_id
department_id
team_id
```

directly into **every** workspace object indiscriminately, we'll use organisational scope where it actually matters.

For example, a task needs organisational context:

```text
staff_tasks
 ├── organization_id
 ├── company_id
 ├── subsidiary_id
 ├── facility_id
 ├── department_id
 └── team_id
```

But a personal reminder doesn't necessarily need all six.

This prevents the schema becoming bloated.

---

# 3. UUIDs vs integers

For the new workspace layer:

**Use UUID primary keys.**

Existing Royan clinical tables use `bigint` IDs, so we don't change those.

Instead:

```text
Synbot Workspace
UUID
   ↓
entity_type
entity_id
   ↓
Existing business table
BIGINT
```

For example:

```text
staff_task.entity_type = 'purchase_order'
staff_task.entity_id   = '1024'
```

That allows the generic workspace to connect to existing systems without forcing a migration of the clinical database.

---

# 4. PostgreSQL migration — foundation

The first migration should establish the organisational layer.

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL
        REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    code TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (organization_id, code)
);

CREATE TABLE subsidiaries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL
        REFERENCES companies(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    code TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (company_id, code)
);

CREATE TABLE facilities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL
        REFERENCES companies(id) ON DELETE CASCADE,
    subsidiary_id UUID
        REFERENCES subsidiaries(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    code TEXT,
    address TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE departments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL
        REFERENCES companies(id) ON DELETE CASCADE,
    facility_id UUID
        REFERENCES facilities(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    code TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE teams (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL
        REFERENCES companies(id) ON DELETE CASCADE,
    department_id UUID
        REFERENCES departments(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

# 5. Staff layer

```sql
CREATE TABLE staff (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    user_id UUID,

    organization_id UUID NOT NULL
        REFERENCES organizations(id),

    company_id UUID
        REFERENCES companies(id),

    subsidiary_id UUID
        REFERENCES subsidiaries(id),

    facility_id UUID
        REFERENCES facilities(id),

    department_id UUID
        REFERENCES departments(id),

    primary_team_id UUID
        REFERENCES teams(id),

    staff_number TEXT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    display_name TEXT,

    email TEXT,
    phone TEXT,

    designation TEXT,
    employment_status TEXT DEFAULT 'active',

    avatar_url TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (organization_id, staff_number)
);
```

### Multiple-company membership

```sql
CREATE TABLE staff_company_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    staff_id UUID NOT NULL
        REFERENCES staff(id) ON DELETE CASCADE,

    company_id UUID NOT NULL
        REFERENCES companies(id) ON DELETE CASCADE,

    subsidiary_id UUID
        REFERENCES subsidiaries(id) ON DELETE SET NULL,

    facility_id UUID
        REFERENCES facilities(id) ON DELETE SET NULL,

    department_id UUID
        REFERENCES departments(id) ON DELETE SET NULL,

    role_id UUID,

    is_primary BOOLEAN NOT NULL DEFAULT false,
    status TEXT NOT NULL DEFAULT 'active',

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (staff_id, company_id, subsidiary_id)
);
```

This is the part that will make the Atiat architecture work properly later.

---

# 6. Task engine

```sql
CREATE TABLE staff_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    organization_id UUID NOT NULL
        REFERENCES organizations(id),

    company_id UUID
        REFERENCES companies(id),

    subsidiary_id UUID
        REFERENCES subsidiaries(id),

    facility_id UUID
        REFERENCES facilities(id),

    department_id UUID
        REFERENCES departments(id),

    team_id UUID
        REFERENCES teams(id),

    created_by UUID NOT NULL
        REFERENCES staff(id),

    assigned_to UUID
        REFERENCES staff(id),

    title TEXT NOT NULL,
    description TEXT,

    status TEXT NOT NULL DEFAULT 'inbox',
    priority TEXT NOT NULL DEFAULT 'normal',

    source_type TEXT NOT NULL DEFAULT 'manual',

    entity_type TEXT,
    entity_id TEXT,

    start_at TIMESTAMPTZ,
    due_at TIMESTAMPTZ,

    completed_at TIMESTAMPTZ,
    verified_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,

    is_recurring BOOLEAN NOT NULL DEFAULT false,
    recurrence_rule TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CHECK (
        status IN (
            'inbox',
            'accepted',
            'in_progress',
            'waiting',
            'completed',
            'verified',
            'closed',
            'cancelled'
        )
    ),

    CHECK (
        priority IN ('low', 'normal', 'high', 'critical')
    ),

    CHECK (
        source_type IN (
            'manual',
            'assigned',
            'operational',
            'recurring',
            'request',
            'automation',
            'ai'
        )
    )
);
```

---

# 7. Task supporting tables

```sql
CREATE TABLE staff_task_checklists (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    task_id UUID NOT NULL
        REFERENCES staff_tasks(id) ON DELETE CASCADE,

    title TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,

    is_completed BOOLEAN NOT NULL DEFAULT false,

    completed_by UUID
        REFERENCES staff(id),

    completed_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

```sql
CREATE TABLE staff_task_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    task_id UUID NOT NULL
        REFERENCES staff_tasks(id) ON DELETE CASCADE,

    author_id UUID NOT NULL
        REFERENCES staff(id),

    content TEXT NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

```sql
CREATE TABLE staff_task_activity (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    task_id UUID NOT NULL
        REFERENCES staff_tasks(id) ON DELETE CASCADE,

    actor_id UUID
        REFERENCES staff(id),

    activity_type TEXT NOT NULL,

    old_value JSONB,
    new_value JSONB,
    metadata JSONB,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

# 8. Requests

```sql
CREATE TABLE staff_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    organization_id UUID NOT NULL
        REFERENCES organizations(id),

    company_id UUID
        REFERENCES companies(id),

    subsidiary_id UUID
        REFERENCES subsidiaries(id),

    requester_id UUID NOT NULL
        REFERENCES staff(id),

    recipient_id UUID
        REFERENCES staff(id),

    team_id UUID
        REFERENCES teams(id),

    request_type TEXT NOT NULL,

    title TEXT NOT NULL,
    description TEXT,

    related_task_id UUID
        REFERENCES staff_tasks(id)
        ON DELETE SET NULL,

    entity_type TEXT,
    entity_id TEXT,

    priority TEXT NOT NULL DEFAULT 'normal',

    status TEXT NOT NULL DEFAULT 'sent',

    due_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    completed_at TIMESTAMPTZ
);
```

Request types:

```text
information
action
approval
handoff
```

---

# 9. Time engine

```sql
CREATE TABLE staff_time_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    staff_id UUID NOT NULL
        REFERENCES staff(id) ON DELETE CASCADE,

    company_id UUID
        REFERENCES companies(id),

    facility_id UUID
        REFERENCES facilities(id),

    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,

    status TEXT NOT NULL DEFAULT 'active',

    total_seconds INTEGER,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

```sql
CREATE TABLE staff_break_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    time_session_id UUID NOT NULL
        REFERENCES staff_time_sessions(id)
        ON DELETE CASCADE,

    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,

    break_type TEXT DEFAULT 'break',

    duration_seconds INTEGER,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

# 10. Notifications

```sql
CREATE TABLE staff_notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    staff_id UUID NOT NULL
        REFERENCES staff(id) ON DELETE CASCADE,

    notification_type TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'normal',

    title TEXT NOT NULL,
    message TEXT,

    entity_type TEXT,
    entity_id TEXT,

    is_read BOOLEAN NOT NULL DEFAULT false,
    read_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

# 11. Work events

```sql
CREATE TABLE staff_work_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    organization_id UUID NOT NULL
        REFERENCES organizations(id),

    company_id UUID
        REFERENCES companies(id),

    subsidiary_id UUID
        REFERENCES subsidiaries(id),

    facility_id UUID
        REFERENCES facilities(id),

    staff_id UUID
        REFERENCES staff(id),

    event_type TEXT NOT NULL,

    entity_type TEXT,
    entity_id TEXT,

    metadata JSONB,

    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

This is our **activity spine**.

A completed task, shipment received, invoice approved, request answered, etc. can all become work events.

---

# 12. Indexes

The most important initial indexes:

```sql
CREATE INDEX idx_tasks_assignee_status
ON staff_tasks (assigned_to, status);

CREATE INDEX idx_tasks_assignee_due
ON staff_tasks (assigned_to, due_at);

CREATE INDEX idx_tasks_team_status
ON staff_tasks (team_id, status);

CREATE INDEX idx_tasks_company_status
ON staff_tasks (company_id, status);

CREATE INDEX idx_tasks_entity
ON staff_tasks (entity_type, entity_id);

CREATE INDEX idx_notifications_staff_unread
ON staff_notifications (staff_id, is_read, created_at DESC);

CREATE INDEX idx_requests_recipient_status
ON staff_requests (recipient_id, status);

CREATE INDEX idx_requests_requester_status
ON staff_requests (requester_id, status);

CREATE INDEX idx_time_staff_started
ON staff_time_sessions (staff_id, started_at DESC);

CREATE INDEX idx_work_events_staff_time
ON staff_work_events (staff_id, occurred_at DESC);
```

---

# 13. FastAPI contract

Now let's translate that into the API.

## Workspace

```http
GET /api/v1/workspace
```

Response:

```json
{
  "staff": {},
  "company_context": {},
  "summary": {
    "tasks": 7,
    "due_today": 3,
    "waiting": 2,
    "work_seconds": 16320
  },
  "today": [],
  "attention": [],
  "reminders": [],
  "operational_widgets": [],
  "recent_activity": []
}
```

This endpoint is deliberately aggregated.

**One request → most of My Day.**

---

# 14. Tasks API

```text
GET    /api/v1/tasks
POST   /api/v1/tasks
GET    /api/v1/tasks/{id}
PATCH  /api/v1/tasks/{id}

POST   /api/v1/tasks/{id}/accept
POST   /api/v1/tasks/{id}/start
POST   /api/v1/tasks/{id}/wait
POST   /api/v1/tasks/{id}/complete
POST   /api/v1/tasks/{id}/verify
POST   /api/v1/tasks/{id}/reopen
```

And:

```text
GET  /api/v1/tasks/{id}/activity
GET  /api/v1/tasks/{id}/comments
POST /api/v1/tasks/{id}/comments

GET  /api/v1/tasks/{id}/checklist
POST /api/v1/tasks/{id}/checklist
PATCH /api/v1/tasks/{id}/checklist/{item_id}
```

---

# 15. Requests API

```text
GET  /api/v1/requests
POST /api/v1/requests

GET  /api/v1/requests/{id}

POST /api/v1/requests/{id}/acknowledge
POST /api/v1/requests/{id}/respond
POST /api/v1/requests/{id}/close

GET  /api/v1/requests/{id}/messages
POST /api/v1/requests/{id}/messages
```

---

# 16. Time API

```text
GET  /api/v1/time/today

POST /api/v1/time/start
POST /api/v1/time/pause
POST /api/v1/time/resume
POST /api/v1/time/end

GET /api/v1/time/history
GET /api/v1/time/summary
```

---

# 17. Team API

```text
GET /api/v1/team
GET /api/v1/team/{staff_id}
GET /api/v1/team/workload
```

And collaboration shortcuts:

```text
POST /api/v1/team/{staff_id}/message
POST /api/v1/team/{staff_id}/request
```

---

# 18. Progress API

```text
GET /api/v1/progress
GET /api/v1/progress/daily
GET /api/v1/progress/weekly
GET /api/v1/activity
```

The backend calculates:

* completed tasks
* on-time completion
* active work
* waiting work
* requests handled
* work time
* operational events

rather than storing every metric as an independent manually maintained number.

---

# 19. Pydantic model example

The API layer should have strict schemas.

```python
class TaskCreate(BaseModel):
    title: str
    description: str | None = None

    assigned_to: UUID | None = None

    company_id: UUID | None = None
    subsidiary_id: UUID | None = None
    facility_id: UUID | None = None
    department_id: UUID | None = None
    team_id: UUID | None = None

    priority: Literal[
        "low",
        "normal",
        "high",
        "critical"
    ] = "normal"

    due_at: datetime | None = None

    source_type: Literal[
        "manual",
        "assigned",
        "operational",
        "recurring",
        "request",
        "automation",
        "ai"
    ] = "manual"

    entity_type: str | None = None
    entity_id: str | None = None
```

Then:

```python
class TaskResponse(TaskCreate):
    id: UUID
    status: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime
```

---

# 20. Service layer

I don't want the FastAPI route directly manipulating SQL.

Use:

```text
Route
 ↓
Service
 ↓
Repository
 ↓
PostgreSQL
```

For example:

```text
/api/v1/tasks/{id}/complete
          ↓
TaskService.complete_task()
          ↓
TaskRepository.update()
          ↓
PostgreSQL
          ↓
WorkEventService.record()
          ↓
NotificationService
```

That will become very important when operational transactions enter the picture.

---

# 21. Completing a task

The logic should eventually look conceptually like:

```python
def complete_task(task_id, staff_id):

    task = task_repository.get(task_id)

    authorize_completion(task, staff_id)

    task_repository.mark_completed(task_id)

    activity_service.record(
        task_id=task_id,
        actor_id=staff_id,
        event="task_completed"
    )

    work_event_service.record(
        staff_id=staff_id,
        event_type="task_completed",
        entity_type="task",
        entity_id=str(task_id)
    )

    if task.entity_type:
        operational_service.handle_completion(task)

    return task
```

This is the bridge between **Staff Workspace** and **real business operations**.

---

# 22. The most important architectural boundary

I want us to keep this very clean:

```text
             STAFF WORKSPACE
                    │
                    │
             "I completed this"
                    │
                    ▼
             WORK EVENT LAYER
                    │
                    ▼
          OPERATIONAL SERVICE
                    │
        ┌───────────┼────────────┐
        ▼           ▼            ▼
    Inventory     Finance      Clinical
```

The Staff Workspace should **not** directly manipulate inventory, finance or clinical tables.

It emits an action/event.

The appropriate business service decides what that action means.

That prevents the workspace becoming a giant monolithic system.

---

# 23. How this plugs into Royan

We already have:

```text
royan_staff
royan_timesheets
royan_procurement_shipments
royan_operations_events
```

in the existing design. 

So the migration strategy should be:

```text
Existing Royan
      │
      ├── royan_staff
      │        ↓
      │   staff mapping
      │
      ├── royan_timesheets
      │        ↑
      │   workspace time engine
      │
      ├── royan_procurement_shipments
      │        ↑
      │   operational tasks
      │
      └── royan_operations_events
               ↑
          staff_work_events
```

We're **extending the existing architecture**, not throwing it away.

---

# 24. First operational integration

I would make **Procurement → Shipment → Inventory** our first real integration.

Why?

Because it demonstrates the entire concept:

```text
Purchase Order
      ↓
Shipment Expected
      ↓
Staff Task Created
      ↓
Employee Workspace
      ↓
Employee Starts Task
      ↓
Receives Shipment
      ↓
Records Quantity / Batch / Expiry
      ↓
Complete
      ↓
Inventory Update
      ↓
Work Event
      ↓
Analytics
```

And your existing database design already has `royan_procurement_shipments` waiting for operational data. 

---

# 25. Development sequence from here

I would now use this order:

### Step 1 — Database

Create:

```text
organizations
companies
subsidiaries
facilities
departments
teams
staff
staff_company_memberships
staff_preferences
```

### Step 2 — Workspace engine

Create:

```text
staff_tasks
staff_task_checklists
staff_task_comments
staff_task_activity
staff_reminders
```

### Step 3 — Collaboration

```text
staff_requests
staff_request_messages
staff_notifications
```

### Step 4 — Time

```text
staff_time_sessions
staff_break_sessions
```

### Step 5 — Activity

```text
staff_work_events
```

### Step 6 — FastAPI

Build the endpoints against these tables.

### Step 7 — React

Build:

```text
My Day
My Work
Inbox
Team
Progress
```

### Step 8 — First operational integration

```text
Procurement → Staff Workspace
```

### Step 9 — AI

Only after the structured system works:

```text
Ask Synbot
```

---

## One thing I would lock before we code

**The database above is the foundation, but we should not immediately run it against the existing Royan database.**

The current Royan schema is a 42-table system with populated clinical Silver tables and empty Staff & Operations tables.  

So the clean implementation is:

```text
                    SYNBOT WORKSPACE SCHEMA
                             │
                 ┌───────────┴───────────┐
                 │                       │
             Atiat DB                Royan DB
                 │                       │
          company context          royan_staff mapping
          staff/tasks               royan_timesheets
          collaboration             procurement
          time                      clinical
                 │                       │
                 └───────────┬───────────┘
                             │
                       Synbot API
                             │
                       React Workspace
```

That gives us a **portable Staff Workspace engine** instead of accidentally making the new architecture dependent on Royan.

### Next build artifact

The next piece should be the **actual SQL migration package + seed data + ERD relationship map**, including:

* PostgreSQL enums
* UUID/FK constraints
* indexes
* updated-at triggers
* initial roles/permissions
* demo company/subsidiary/team/staff records
* migration strategy for existing `royan_staff`
* sample tasks and operational events

Once that is in place, we can move directly into the **FastAPI repository/service implementation** and then React.
