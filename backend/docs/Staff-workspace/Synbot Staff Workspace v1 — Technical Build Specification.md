# Synbot Staff Workspace v1 — Technical Build Specification

This is the point where I’d move from UX design into an implementation contract.

The architecture below deliberately separates **the reusable Staff Workspace engine** from the business modules it plugs into. That means Procurement, Finance, HR, Clinical, Inventory, etc. can generate work for the same employee workspace without each module inventing its own task system.

---

# 1. Architecture

At the highest level:

```text
                         SYNBOT
                           │
             ┌─────────────┴─────────────┐
             │                           │
       STAFF WORKSPACE             BUSINESS MODULES
             │                           │
     ┌───────┼────────┐        ┌─────────┼──────────┐
     │       │        │        │         │          │
   Tasks  Inbox     Time     Finance   Inventory  Clinical
     │       │        │        │         │          │
     └───────┴────────┘        └─────────┼──────────┘
                 │                       │
                 └───────────┬───────────┘
                             │
                         EVENT LAYER
                             │
                         PostgreSQL
                             │
                       Analytics / AI
```

The important distinction is:

### Workspace Engine

Knows:

* staff
* teams
* tasks
* requests
* reminders
* notifications
* time
* activity
* preferences

### Operational Modules

Know:

* patients
* invoices
* purchase orders
* inventory
* shipments
* leave
* payroll
* insurance
* etc.

The two communicate through **events and references**.

---

# 2. Frontend architecture

Assuming we're continuing with the React/Vite direction already used in Synbot, I'd structure it approximately like this:

```text
src/
│
├── app/
│   ├── router/
│   ├── providers/
│   └── layout/
│
├── features/
│   │
│   ├── workspace/
│   │   ├── pages/
│   │   │   ├── MyDayPage.jsx
│   │   │   ├── MyWorkPage.jsx
│   │   │   ├── InboxPage.jsx
│   │   │   ├── TeamPage.jsx
│   │   │   └── ProgressPage.jsx
│   │   │
│   │   ├── components/
│   │   │   ├── WorkspaceHeader.jsx
│   │   │   ├── WorkTimer.jsx
│   │   │   ├── AttentionPanel.jsx
│   │   │   ├── TodayTimeline.jsx
│   │   │   ├── OperationalSnapshot.jsx
│   │   │   ├── ActivityFeed.jsx
│   │   │   └── QuickActions.jsx
│   │   │
│   │   └── hooks/
│   │
│   ├── tasks/
│   │   ├── components/
│   │   │   ├── TaskCard.jsx
│   │   │   ├── TaskDrawer.jsx
│   │   │   ├── TaskWorkspace.jsx
│   │   │   ├── TaskChecklist.jsx
│   │   │   ├── TaskComments.jsx
│   │   │   └── TaskActivity.jsx
│   │   └── hooks/
│   │
│   ├── collaboration/
│   │   ├── RequestDrawer.jsx
│   │   ├── MessagePanel.jsx
│   │   └── MentionList.jsx
│   │
│   ├── time/
│   │   ├── WorkTimer.jsx
│   │   └── TimeSummary.jsx
│   │
│   ├── notifications/
│   │   ├── NotificationCenter.jsx
│   │   └── NotificationItem.jsx
│   │
│   ├── team/
│   │   ├── TeamMember.jsx
│   │   ├── TeamWorkload.jsx
│   │   └── MemberProfile.jsx
│   │
│   └── ai/
│       ├── SynbotAssistant.jsx
│       ├── CommandBar.jsx
│       └── AssistantDrawer.jsx
│
├── components/
│   ├── ui/
│   ├── forms/
│   └── modals/
│
├── services/
│   ├── api/
│   │   ├── tasks.js
│   │   ├── workspace.js
│   │   ├── requests.js
│   │   ├── time.js
│   │   ├── notifications.js
│   │   └── team.js
│   │
│   └── websocket/
│
├── stores/
│   ├── authStore.js
│   ├── workspaceStore.js
│   └── notificationStore.js
│
└── utils/
```

The major point is that **workspace**, **tasks**, **collaboration**, and **time** are separate features.

We're not putting everything into one giant `StaffDashboard.jsx`.

---

# 3. Application shell

The shell should look roughly like:

```text
App
│
└── AuthenticatedLayout
    │
    ├── Sidebar
    │
    ├── Header
    │
    └── MainContent
        │
        ├── MyDay
        ├── MyWork
        ├── Inbox
        ├── Team
        └── Progress
```

Then task drawers, request drawers and the AI assistant operate as **overlays**, rather than navigation away from the workspace.

That's important for the "everything happens in context" principle.

---

# 4. Routes

I'd start with:

```text
/workspace
/workspace/work
/workspace/inbox
/workspace/team
/workspace/progress
```

Task:

```text
/workspace/tasks/:taskId
```

Team member:

```text
/workspace/team/:staffId
```

But for desktop UX, task details should usually open as a drawer/modal over the current page rather than forcing a full navigation.

---

# 5. PostgreSQL architecture

Now the important part.

Because the wider Synbot platform is becoming multi-company, I don't want:

```text
royan_staff_tasks
royan_staff_requests
royan_staff_notifications
```

as the fundamental design.

Instead:

```text
staff
staff_tasks
staff_requests
staff_notifications
```

with organisational context built into the records.

That lets Royan, Atiat, Placeware, etc. use the same engine.

---

# 6. Organisation hierarchy

I'd establish:

```text
organization
    │
    └── company
          │
          └── subsidiary
                │
                └── facility
                      │
                      └── department
                            │
                            └── team
                                  │
                                  └── staff
```

But we should allow some organisations to skip levels.

For example:

```text
Atiat
 ├── Insurance
 ├── Mobility
 ├── Travel
 └── Proof of Funds
```

while Royan may have:

```text
Royan Health
 └── Ikeja Facility
      ├── Pathology
      ├── Radiology
      ├── Dialysis
      └── Cardiology
```

---

# 7. Core organisation tables

### `organizations`

```text
id
name
slug
status
created_at
updated_at
```

### `companies`

```text
id
organization_id
name
code
status
created_at
updated_at
```

### `subsidiaries`

```text
id
company_id
name
code
status
created_at
updated_at
```

### `facilities`

```text
id
company_id
subsidiary_id
name
code
address
status
created_at
updated_at
```

### `departments`

```text
id
company_id
facility_id
name
code
status
created_at
updated_at
```

### `teams`

```text
id
company_id
department_id
name
description
status
created_at
updated_at
```

---

# 8. Staff

The existing Royan design already has a `royan_staff` concept containing staff registry information such as staff number, department and designation. 

For the generic Synbot engine:

### `staff`

```text
id UUID PK

user_id UUID

organization_id UUID
company_id UUID
subsidiary_id UUID
facility_id UUID
department_id UUID
primary_team_id UUID

staff_number
first_name
last_name
display_name
email
phone

designation
employment_status

avatar_url

created_at
updated_at
```

Then:

### `staff_company_memberships`

Allows someone to belong to multiple companies/subsidiaries.

```text
id
staff_id
company_id
subsidiary_id
facility_id
department_id
role_id

is_primary
status

created_at
```

This is important for Atiat.

---

# 9. Roles

### `roles`

```text
id
organization_id
name
code
description
```

### `permissions`

```text
id
resource
action
```

Example:

```text
task:create
task:assign
task:complete

request:create
request:respond

team:view
team:manage

timesheet:view
timesheet:manage
```

Then:

### `role_permissions`

```text
role_id
permission_id
```

This keeps workspace permissions separate from business permissions.

---

# 10. Staff preferences

### `staff_preferences`

```text
id
staff_id

default_workspace
task_sort
timezone

show_calendar
show_progress
show_team
show_journal

notify_assignments
notify_requests
notify_mentions
notify_updates

quiet_hours_start
quiet_hours_end

created_at
updated_at
```

Now the workspace genuinely becomes personal.

---

# 11. The task table

This is the centre of the system.

### `staff_tasks`

```text
id UUID PK

organization_id
company_id
subsidiary_id
facility_id
department_id
team_id

created_by
assigned_to

title
description

status
priority

source_type
entity_type
entity_id

start_at
due_at
completed_at
verified_at
closed_at

is_recurring
recurrence_rule

created_at
updated_at
```

---

# 12. Task statuses

Use an enum:

```text
inbox
accepted
in_progress
waiting
completed
verified
closed
cancelled
overdue
```

But I would **not** permanently store `overdue` as a normal state unless necessary.

Overdue can often be derived:

```text
status NOT IN ('completed', 'verified', 'closed')
AND due_at < NOW()
```

This avoids state inconsistencies.

---

# 13. Task source

Enum:

```text
manual
assigned
operational
recurring
request
automation
ai
```

This gives us useful analytics.

We can eventually answer:

> How many tasks are employees creating themselves?

> How many are generated from business operations?

> How many are generated by automation?

> How many came from Synbot AI?

---

# 14. Business entity reference

This is one of the most important fields.

```text
entity_type
entity_id
```

Examples:

```text
purchase_order / PO-1024

invoice / INV-3012

shipment / SHP-882

patient / PAT-00928

leave_request / LV-102
```

The workspace therefore doesn't need to understand every business object.

It only needs to know:

> "This task relates to that object."

---

# 15. Task checklist

### `staff_task_checklists`

```text
id
task_id
title
position
is_completed
completed_by
completed_at
created_at
```

This supports:

```text
☑ Confirm PO
☑ Check quantity
☐ Check batch
☐ Check expiry
```

---

# 16. Task comments

### `staff_task_comments`

```text
id
task_id
author_id

content

created_at
updated_at
```

Eventually attachments:

### `staff_task_attachments`

```text
id
task_id
uploaded_by

file_name
file_url
mime_type
file_size

created_at
```

---

# 17. Task activity

### `staff_task_activity`

```text
id
task_id
actor_id

activity_type

old_value
new_value

metadata JSONB

created_at
```

Examples:

```text
task_created
task_assigned
task_started
task_paused
task_waiting
comment_added
checklist_completed
task_completed
task_verified
task_reopened
```

This gives us our audit trail.

---

# 18. Reminders

### `staff_reminders`

```text
id

staff_id

title
description

remind_at

related_task_id

status

created_at
completed_at
```

Simple and independent.

---

# 19. Collaboration requests

### `staff_requests`

```text
id UUID PK

organization_id
company_id
subsidiary_id

requester_id
recipient_id
team_id

request_type

title
description

related_task_id
entity_type
entity_id

priority
status

due_at

created_at
updated_at
completed_at
```

Request types:

```text
information
action
approval
handoff
```

---

# 20. Request lifecycle

```text
draft
sent
acknowledged
in_progress
responded
closed
cancelled
```

This gives us a proper collaboration workflow.

---

# 21. Request messages

### `staff_request_messages`

```text
id
request_id
sender_id

message

created_at
```

This means the conversation stays attached to the request.

---

# 22. Notifications

### `staff_notifications`

```text
id

staff_id

notification_type
priority

title
message

entity_type
entity_id

is_read
read_at

created_at
```

Types:

```text
task_assigned
task_due
task_overdue
request_received
request_response
mention
message
approval
operational_event
system
```

---

# 23. Time engine

The existing Royan design already anticipates `royan_timesheets` for clock-in/out, shifts, overtime and absence. 

For the generic workspace:

### `staff_time_sessions`

```text
id

staff_id

company_id
facility_id

started_at
ended_at

status

total_seconds

created_at
updated_at
```

### `staff_break_sessions`

```text
id

time_session_id

started_at
ended_at

break_type

duration_seconds
```

Statuses:

```text
active
paused
completed
```

---

# 24. Time flow

Employee presses:

**Start Work**

```text
POST /workspace/time/start
```

Creates:

```text
staff_time_sessions
```

Pause:

```text
POST /workspace/time/pause
```

Resume:

```text
POST /workspace/time/resume
```

End:

```text
POST /workspace/time/end
```

Then a background process can aggregate this into the organisation's HR/timesheet structure.

For Royan, that could eventually feed the existing `royan_timesheets` layer rather than replacing it.

---

# 25. Work events

### `staff_work_events`

This is the bridge between workspace activity and the wider Synbot operational engine.

```text
id

organization_id
company_id
subsidiary_id
facility_id

staff_id

event_type

entity_type
entity_id

metadata JSONB

occurred_at
```

Examples:

```text
task_completed
shipment_received
invoice_approved
patient_followup_completed
request_resolved
stock_adjusted
leave_requested
```

This is where the existing `royan_operations_events` concept can connect into the broader architecture. 

---

# 26. API architecture

FastAPI:

```text
/api/v1
```

Then:

```text
/workspace
/tasks
/requests
/time
/notifications
/team
/progress
/reminders
/ai
```

---

# 27. Workspace endpoints

### Get workspace

```http
GET /api/v1/workspace
```

Returns the personalised landing page.

Example:

```json
{
  "staff": {},
  "company_context": {},
  "summary": {},
  "today": [],
  "attention": [],
  "reminders": [],
  "operational_widgets": [],
  "recent_activity": []
}
```

One call should populate most of My Day.

This is important for performance.

We don't want the frontend making 17 API requests just to render the dashboard.

---

# 28. Task endpoints

```http
GET    /api/v1/tasks
POST   /api/v1/tasks
GET    /api/v1/tasks/{task_id}
PATCH  /api/v1/tasks/{task_id}
DELETE /api/v1/tasks/{task_id}
```

Actions:

```http
POST /api/v1/tasks/{id}/accept
POST /api/v1/tasks/{id}/start
POST /api/v1/tasks/{id}/pause
POST /api/v1/tasks/{id}/wait
POST /api/v1/tasks/{id}/complete
POST /api/v1/tasks/{id}/verify
POST /api/v1/tasks/{id}/reopen
```

---

# 29. Task comments

```http
GET  /api/v1/tasks/{id}/comments
POST /api/v1/tasks/{id}/comments
```

Checklist:

```http
GET   /api/v1/tasks/{id}/checklist
POST  /api/v1/tasks/{id}/checklist
PATCH /api/v1/tasks/{id}/checklist/{item_id}
```

---

# 30. Collaboration API

```http
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

# 31. Time API

```http
GET  /api/v1/time/today

POST /api/v1/time/start
POST /api/v1/time/pause
POST /api/v1/time/resume
POST /api/v1/time/end

GET /api/v1/time/history
GET /api/v1/time/summary
```

---

# 32. Team API

```http
GET /api/v1/team
GET /api/v1/team/{staff_id}
GET /api/v1/team/workload

POST /api/v1/team/{staff_id}/message
POST /api/v1/team/{staff_id}/request
```

Workload data must be permission-controlled.

---

# 33. Progress API

```http
GET /api/v1/progress
GET /api/v1/progress/daily
GET /api/v1/progress/weekly
GET /api/v1/activity
```

The backend calculates metrics from actual work events rather than letting the frontend invent them.

---

# 34. Real-time layer

I would add WebSockets, but **not in the first implementation if it complicates the MVP**.

Eventually:

```text
WebSocket
/ws/workspace
```

Events:

```text
task_assigned
task_updated
request_received
request_responded
notification_created
team_status_changed
operational_event
```

Example:

Sarah assigns Mofe a task.

Backend:

```text
task_assigned
```

WebSocket:

```text
Mofe's browser
```

UI immediately displays:

> **New task assigned by Sarah**

No refresh.

---

# 35. Event-driven operational integration

This is where I would eventually introduce a lightweight internal event bus.

Example:

```text
PurchaseOrderCreated
        ↓
Operational Event
        ↓
Task Generator
        ↓
"Verify incoming shipment"
        ↓
staff_tasks
```

Another:

```text
InvoiceRequiresApproval
        ↓
Task Generator
        ↓
Finance employee
```

Another:

```text
EmployeeLeaveRequested
        ↓
HR approval task
```

This gives us a common mechanism for every Synbot product.

---

# 36. Operational task configuration

We should **not hard-code every task generation rule into Python**.

Eventually have configurable rules:

```text
operational_task_rules
```

Example:

```text
event:
purchase_order.approved

condition:
shipment_expected = true

assign_to:
procurement_team

task:
"Verify incoming shipment"

priority:
high
```

This makes Synbot configurable per client.

---

# 37. AI integration

The AI should not directly mutate everything.

Initially:

```text
User
 ↓
AI Assistant
 ↓
Intent
 ↓
Structured API
 ↓
Database
```

Example:

> "Remind me to call Sarah tomorrow."

AI:

```text
intent = create_reminder

staff_id = current_user

title = "Call Sarah"

remind_at = tomorrow
```

Then it calls:

```text
POST /api/v1/reminders
```

The AI doesn't write directly to PostgreSQL.

That separation is important.

---

# 38. AI permissions

The assistant must inherit the user's permissions.

If Mofe cannot access:

```text
Payroll
```

then asking:

> "Show me Sarah's salary."

must not bypass the application permissions simply because the request went through the LLM.

The architecture should be:

```text
User
 ↓
Authentication
 ↓
RBAC / Scope
 ↓
AI
 ↓
Permitted tools
 ↓
Business API
```

Not:

```text
User
 ↓
LLM
 ↓
Database
```

---

# 39. Multi-company security

Every important workspace query should be scoped.

Conceptually:

```sql
WHERE organization_id = :organization_id
AND company_id IN (:allowed_companies)
```

And where applicable:

```text
subsidiary_id
facility_id
department_id
team_id
```

The backend determines these scopes from the authenticated user's memberships.

**Never trust the frontend to tell the API which company the user belongs to.**

---

# 40. Database indexing

For `staff_tasks`, I'd prioritise:

```text
INDEX assigned_to + status

INDEX assigned_to + due_at

INDEX company_id + status

INDEX team_id + status

INDEX entity_type + entity_id

INDEX created_by + created_at
```

For notifications:

```text
INDEX staff_id + is_read + created_at
```

For requests:

```text
INDEX recipient_id + status
INDEX requester_id + status
```

For time:

```text
INDEX staff_id + started_at
```

These correspond directly to the queries our workspace will make most frequently.

---

# 41. My Day performance

This is particularly important because the existing dashboard experience has already raised concerns about sluggishness.

We should **not** build My Day as:

```text
10 database queries
+
6 API calls
+
3 external service calls
```

Instead:

```text
GET /workspace
        ↓
Workspace aggregation service
        ↓
parallel database queries
        ↓
single response
```

Potentially cache:

* team availability
* static profile information
* role configuration
* operational widget definitions

But personal tasks and attention data should remain appropriately fresh.

---

# 42. First database migration

I would implement the schema in this order:

### Migration 001

```text
organizations
companies
subsidiaries
facilities
departments
teams
```

### Migration 002

```text
staff
staff_company_memberships
roles
permissions
role_permissions
staff_preferences
```

### Migration 003

```text
staff_tasks
staff_task_checklists
staff_task_comments
staff_task_activity
```

### Migration 004

```text
staff_reminders
staff_requests
staff_request_messages
staff_notifications
```

### Migration 005

```text
staff_time_sessions
staff_break_sessions
staff_work_events
```

### Migration 006

```text
operational_task_rules
```

Then connect existing business modules.

---

# 43. First frontend milestone

Once migrations/API are ready:

### Sprint 1

Build:

```text
AuthenticatedLayout
      ↓
Sidebar
      ↓
Header
      ↓
MyDayPage
```

with:

* profile
* company context
* timer
* summary cards
* today's tasks
* attention panel
* reminders
* activity

No AI yet.

---

### Sprint 2

Build:

```text
MyWorkPage
```

with:

* task list
* filters
* task drawer
* task workspace
* checklist
* comments
* activity
* lifecycle

---

### Sprint 3

Build:

```text
Inbox
Team
Requests
```

---

### Sprint 4

Build:

```text
Progress
Time history
Work journal
```

---

### Sprint 5

Connect first real operational module.

For example:

```text
Procurement
     ↓
Purchase Order
     ↓
Operational Task
     ↓
Staff Workspace
     ↓
Shipment Receipt
     ↓
Inventory
```

This would prove the architecture.

---

# 44. What I would NOT build yet

I want to deliberately keep these out of v1:

* complicated calendar
* full chat replacement for Slack/Teams
* video calling
* AI-generated productivity scores
* elaborate employee ranking
* heavy project-management/Gantt features
* complex workflow designer
* AI autonomous agents modifying business records
* excessive notifications

Those can come later.

The first objective is:

> **Make the employee's daily work dramatically easier to manage.**

---

# 45. The first "killer workflow"

I think this should be our demonstration workflow.

### Scenario

A manager verbally tells an employee:

> "We're expecting a reorder from ABC Supplies tomorrow."

Employee opens Synbot.

Clicks:

**+ Reminder**

or simply types:

> "Remind me tomorrow morning that ABC Supplies reorder is coming."

Synbot creates:

```text
Reminder
ABC Supplies reorder expected

Tomorrow · 9:00 AM
```

Next day:

```text
🔔 ABC Supplies reorder expected
```

Employee converts it:

**Create Task**

```text
Receive ABC Supplies reorder
```

When the shipment arrives:

```text
Start Task
```

Employee records:

```text
Expected: 100
Received: 98
Batch: B2026-09
Expiry: 2028-09
```

Clicks:

**Complete**

Synbot:

```text
✓ Task completed

Inventory updated
Shipment recorded
Activity logged
Finance event generated
```

Employee's workspace:

```text
Tasks completed +1
```

Manager's operational view:

```text
Shipment received
98 units
Received by Mofe
10:42
```

**That is the Staff Workspace we should build.**

It connects the human workflow to the business workflow.

---

# 46. Final architecture decision

So I would now officially define this module as:

## **Synbot Staff Workspace**

**Purpose:**
A personalised employee operating environment for managing daily work, tasks, reminders, collaboration, time, operational actions and personal work history.

**Core principle:**

> **The workspace is personal; the underlying operations are organisational.**

**Core engines:**

```text
Personal Work
Collaboration
Time & Attendance
Operational Tasks
Activity & Metrics
AI Assistant
```

**Core navigation:**

```text
My Day
My Work
Inbox
Team
Progress
```

**Core backend:**

```text
FastAPI
PostgreSQL
WebSocket (later)
Event-driven operational integration
RBAC
AI tool layer
```

**Core organisational model:**

```text
Organization
 → Company
   → Subsidiary
     → Facility
       → Department
         → Team
           → Staff
```

This also fits the existing database direction: the current Royan design already separates operational/staff data from the clinical layers and includes staff, timesheets, procurement shipments, import jobs and operational events.  The new layer effectively turns those currently isolated operational concepts into a proper employee-facing work system.

### The next logical build artifact

The next thing I'd produce is the **actual database ERD + SQL migration specification** for this architecture, followed by the **FastAPI Pydantic schemas and endpoint contracts**. Once those are fixed, the React implementation becomes relatively mechanical rather than us repeatedly changing the architecture while coding.
