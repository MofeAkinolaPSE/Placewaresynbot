# Synbot Staff Workspace v1

### Screen-by-screen product and UX specification

I think we have enough clarity now to stop thinking of this as “a dashboard” and start treating it as a **core Synbot product module**.

The design principle is:

> **One workspace. One place to start the day. Everything I need to know, do, communicate, and track from there.**

And because Synbot is eventually serving multiple companies/subsidiaries, we're designing this as a **reusable workspace engine**, not a Royan-specific page.

---

# 1. Overall application structure

I would keep the global navigation extremely small.

```text
┌───────────────────────────────────────────────────────────────┐
│ SYNBOT                                   🔔  💬  Mofe ▾       │
├──────────────┬────────────────────────────────────────────────┤
│              │                                                │
│  MY WORK     │                                                │
│              │                                                │
│  🏠 My Day   │              STAFF WORKSPACE                   │
│  ✓ My Work   │                                                │
│  💬 Inbox    │                                                │
│  👥 Team     │                                                │
│  📊 Progress │                                                │
│              │                                                │
│              │                                                │
│  ──────────  │                                                │
│              │                                                │
│  COMPANY     │                                                │
│  Atiat ▾     │                                                │
│              │                                                │
│  Operations  │                                                │
│  Reports     │                                                │
│              │                                                │
│  ──────────  │                                                │
│              │                                                │
│  ⚙ Settings │                                                │
└──────────────┴────────────────────────────────────────────────┘
```

But there is an important distinction:

### The employee's workspace is not the whole application.

The employee can still access:

* Clinical
* Finance
* Procurement
* Inventory
* HR
* Operations
* Reports

depending on their permissions.

The **Staff Workspace is their home base**.

---

# 2. Global Header

This should remain visible throughout the workspace.

```text
┌─────────────────────────────────────────────────────────────────┐
│ ☰  SYNBOT      Search...             ● Working  04:32:18   🔔 M │
└─────────────────────────────────────────────────────────────────┘
```

### Left

**Synbot logo**

Optional:

`☰`

for collapsing navigation.

### Centre

Global search:

> Search people, tasks, patients, orders, suppliers...

This becomes extremely powerful later.

### Right

#### Work status

```text
● Working
04:32:18
```

Clicking opens:

```text
Work Session

Started       08:42
Duration      04:32
Break         00:38

[Take Break]
[End Work]
```

#### Notifications

Bell opens **Needs Attention**.

#### Profile

```text
Mofe Akinola
AI Engineer
Atiat Limited

My Profile
Preferences
Availability
Sign out
```

---

# 3. Screen 1 — My Day

This is the **default landing page**.

The first thing the employee sees every morning.

---

## Header

```text
Good morning, Mofe 👋

Tuesday, 29 September

Here's what needs your attention today.
```

Underneath:

```text
[ + Add Task ]   [ + Reminder ]   [ Request ]   [ Message ]
```

These four actions should be extremely easy to access.

---

# 4. My Day — personal summary

Then four small contextual cards.

Not random company metrics.

```text
┌───────────────┐ ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│ MY TASKS      │ │ DUE TODAY     │ │ WAITING       │ │ WORK TIME     │
│               │ │               │ │               │ │               │
│      7        │ │      3        │ │      2        │ │    4h 32m     │
│               │ │               │ │               │ │               │
└───────────────┘ └───────────────┘ └───────────────┘ └───────────────┘
```

Notice:

**These metrics are about the person.**

---

# 5. My Day — Today timeline

This becomes the heart of the screen.

```text
TODAY

08:30 ─────────────────────────────────

✓ Start work

09:00
┌─────────────────────────────────────┐
│ 🔴 Verify supplier shipment          │
│ Procurement                          │
│ Due 10:30                            │
└─────────────────────────────────────┘

10:30
┌─────────────────────────────────────┐
│ 🟠 Review invoice #1024              │
│ Finance                              │
└─────────────────────────────────────┘

12:00
☕ Lunch / Break

14:00
┌─────────────────────────────────────┐
│ Team meeting                         │
│ Procurement                         │
└─────────────────────────────────────┘
```

The timeline can eventually incorporate:

* tasks
* meetings
* reminders
* appointments
* operational events
* deadlines

---

# 6. My Day — Needs Attention

Right side.

```text
NEEDS ATTENTION

🔴 Action required
Finance requested information
10 min ago

🟠 Approval
PO #1024 awaiting your review

🔵 Mention
Sarah mentioned you

🟡 Reminder
Supplier call in 30 minutes
```

The idea is that the employee can scan this in **five seconds** and understand what matters.

---

# 7. My Day — Quick Add

Clicking:

**+ Add Task**

should NOT navigate to another page.

Open a side drawer.

```text
┌──────────────────────────────────┐
│ New Task                     ×   │
├──────────────────────────────────┤
│ What needs to be done?           │
│                                  │
│ Verify supplier shipment         │
│                                  │
│ Assigned to                      │
│ Me ▾                             │
│                                  │
│ Due                              │
│ Today · 10:30                    │
│                                  │
│ Priority                         │
│ ● High                           │
│                                  │
│ Company                          │
│ Atiat Limited ▾                  │
│                                  │
│ Department                       │
│ Procurement ▾                    │
│                                  │
│ [ Create Task ]                  │
└──────────────────────────────────┘
```

Simple.

---

# 8. Natural task creation

Later, Synbot should support natural language.

Employee types:

> Follow up with Finance about PO 1024 tomorrow morning.

Synbot interprets:

```text
Task:
Follow up with Finance about PO 1024

Due:
Tomorrow · 9:00 AM

Department:
Finance

Assigned:
Mofe
```

Then:

**Create**

This is one of the first places where AI becomes useful without making the entire system AI-dependent.

---

# 9. Screen 2 — My Work

This is the employee's complete personal work centre.

I would use five sections.

```text
MY WORK

[All] [Today] [Upcoming] [Waiting] [Completed]
```

---

### Today

```text
🔴 Verify supplier shipment
🟠 Review invoice
🟡 Respond to Finance
```

### Upcoming

```text
Monthly reconciliation
Supplier review
Quarterly inventory check
```

### Waiting

```text
Waiting for Sarah — Finance confirmation
Waiting for supplier — delivery note
```

### Completed

```text
✓ Shipment received
✓ Invoice reviewed
✓ Stock adjustment completed
```

---

# 10. Task cards

Each task card should expose useful information without opening it.

```text
┌─────────────────────────────────────────────────────┐
│ 🔴 Verify supplier shipment                         │
│                                                     │
│ PO-1024 · ABC Supplies                              │
│ Procurement                                         │
│                                                     │
│ Due 10:30       Assigned to me      💬 2            │
│                                                     │
│                         [Start]   ⋮                 │
└─────────────────────────────────────────────────────┘
```

Clicking the task opens the **Task Workspace**.

---

# 11. Screen 3 — Task Workspace

This is extremely important.

A task shouldn't just be:

> title + checkbox.

It should become a mini workspace.

```text
┌─────────────────────────────────────────────────────────┐
│ ← My Work                                               │
│                                                         │
│ Verify supplier shipment                                │
│ PO-1024 · ABC Supplies                                  │
│                                                         │
│ 🔴 High     Due 10:30     Procurement                   │
├──────────────────────────────┬──────────────────────────┤
│                              │                          │
│ DETAILS                      │ ACTIVITY                 │
│                              │                          │
│ Description                  │ Mofe started task        │
│                              │ 10:02                    │
│ Expected: 100 units          │                          │
│                              │ Sarah commented          │
│ Assigned: Mofe               │ 09:58                    │
│                              │                          │
│ Due: Today                   │ Supplier updated PO      │
│                              │ 09:42                    │
│                              │                          │
│ CHECKLIST                    │                          │
│                              │                          │
│ ☑ Confirm PO                 │                          │
│ ☐ Verify quantity            │                          │
│ ☐ Verify batch               │                          │
│ ☐ Verify expiry              │                          │
│                              │                          │
│ [Complete Task]              │                          │
└──────────────────────────────┴──────────────────────────┘
```

Now the task becomes a **work object**.

---

# 12. Task Activity

Every task gets an activity history.

```text
09:42
PO updated by Procurement

09:58
Sarah commented:
"Please check the batch number."

10:02
Mofe started task

10:17
Quantity confirmed

10:21
Batch confirmed
```

This gives us:

* transparency
* auditability
* collaboration
* operational history

without creating another separate audit screen.

---

# 13. Operational completion

This is where Synbot becomes much more interesting.

Suppose the task is:

> Receive shipment.

Click:

**Complete Task**

Instead of simply marking it done:

```text
Confirm Shipment

Expected quantity
100

Received quantity
98

Batch
B2026-09

Expiry
2028-09

Condition
○ Good
○ Damaged
○ Partial

Notes
____________________

[Confirm Receipt]
```

Then:

```text
Task → Completed
        ↓
Inventory transaction
        ↓
Stock updated
        ↓
Activity recorded
        ↓
Finance event if applicable
```

This fits the existing system direction where operational activity such as inventory movements should ultimately connect into accounting and reporting rather than existing as isolated actions.  

---

# 14. Screen 4 — Inbox

This is **not notifications**.

It is the employee's **attention centre**.

```text
INBOX

[All] [Action Required] [Requests] [Mentions] [Updates]

──────────────────────────────────────

🔴 Sarah requested information
   "Can you confirm the supplier payment?"
   5 min ago

🟠 PO #1024 requires approval
   Procurement
   20 min ago

🔵 You were mentioned
   "Mofe can confirm this."
   34 min ago

🟢 Shipment received
   Automated update
   1 hour ago
```

Unread indicators should be subtle.

---

# 15. Request system

Click:

**Request Information**

```text
┌───────────────────────────────────────┐
│ Request Information                ×  │
├───────────────────────────────────────┤
│ To                                    │
│ Finance Team ▾                        │
│                                       │
│ What do you need?                     │
│                                       │
│ Please confirm if PO-1024 has         │
│ been paid.                            │
│                                       │
│ Related task                          │
│ Verify supplier shipment              │
│                                       │
│ Due                                   │
│ Today · 2:00 PM                       │
│                                       │
│ [Send Request]                        │
└───────────────────────────────────────┘
```

Now Finance gets an actual request.

---

# 16. Request lifecycle

```text
SENT
 ↓
ACKNOWLEDGED
 ↓
IN PROGRESS
 ↓
RESPONDED
 ↓
CLOSED
```

And the requester sees:

> **Waiting for Finance**

This is much better than sending a WhatsApp message and forgetting about it.

---

# 17. Screen 5 — Team

This should feel lightweight.

Not an organisational chart.

```text
MY TEAM

Procurement · 8 members

🟢 Sarah
Finance Liaison
Available

🟢 John
Procurement Officer
Available

🟡 David
Procurement Lead
In meeting

🔴 Amaka
Offline
```

Click someone:

```text
Sarah
Finance Liaison

[Message]
[Request Information]
[Assign Task]
```

---

# 18. Team workload

A useful secondary view:

```text
TEAM WORKLOAD

Sarah       ███████░░░   4 active
John        █████░░░░░   3 active
David       █████████░   7 active
Amaka       ██░░░░░░░░   2 active
```

But this must respect permissions and shouldn't become a simplistic "who is working hardest" scoreboard.

It's primarily for:

> **Who has capacity to help?**

---

# 19. Screen 6 — My Progress

This replaces the current meaningless metrics page.

Header:

> **Your work, over time.**

Then:

```text
THIS WEEK

Tasks completed          18
On-time completion       94%
Requests handled          7
Tasks waiting             2
Work time               31h
```

Then a simple trend:

```text
COMPLETED TASKS

Mon  ████
Tue  ██████
Wed  █████
Thu  ███████
Fri  ███
```

Then:

### What you worked on

```text
Procurement       42%
Finance            21%
Operations         18%
Administration     19%
```

Then:

### Recent accomplishments

```text
✓ Completed monthly stock reconciliation
✓ Processed 12 supplier shipments
✓ Resolved 7 internal requests
```

This gives the employee something genuinely useful at the end of the week.

---

# 20. Screen 7 — Work Journal

I'd make this accessible from Progress rather than the main navigation.

```text
MY JOURNAL

Today

10:42  ✓ Shipment received
10:21  ✓ Batch verified
10:02  ▶ Shipment task started
09:51  💬 Finance request answered
09:32  ⏸ Break
08:42  ● Work started
```

Filters:

`Today | This Week | This Month`

This can eventually become:

> **"Summarise my work this week."**

And Synbot can generate the summary.

---

# 21. Screen 8 — Reminders

I don't think reminders deserve a major navigation item.

They live inside **My Day** and **My Work**.

But clicking:

> View reminders

opens:

```text
REMINDERS

Today
────────────────────────────

10:30
Call ABC Supplies

14:00
Follow up with Finance

Tomorrow
────────────────────────────

09:00
Check reorder status

Friday
────────────────────────────

Review supplier report
```

Creation remains extremely fast:

> `+ Reminder`

---

# 22. Screen 9 — Personalisation

The employee should be able to customise the workspace.

```text
WORKSPACE PREFERENCES

My Workspace

☑ Show calendar
☑ Show work journal
☑ Show team workload
☑ Show reminders
☑ Show progress

Default view
○ My Day
○ My Work

Task ordering
○ Priority
● Due date
○ Manual

Notifications

☑ Task assignments
☑ Requests
☑ Mentions
☐ Non-critical updates
```

This makes the dashboard genuinely **personal**.

---

# 23. Role-based widgets

Now we connect the employee's role to the workspace.

For example, a procurement employee's My Day might automatically include:

```text
OPERATIONAL SNAPSHOT

Shipments expected      3
POs awaiting action     2
Supplier requests       4
Low stock alerts        2
```

Finance:

```text
OPERATIONAL SNAPSHOT

Invoices awaiting       6
Payment requests        3
Approvals               2
Reconciliations         1
```

Clinical:

```text
OPERATIONAL SNAPSHOT

Patients today          12
Notes pending            3
Lab results              4
Follow-ups               2
```

The **workspace framework stays identical**.

The operational widgets change.

---

# 24. The Company Context Switcher

This becomes especially important for Atiat.

At the top:

```text
Atiat Limited ▾
```

Click:

```text
MY ORGANISATIONS

✓ Atiat Limited

  Insurance
  Mobility
  Travel
  Proof of Funds

  All Companies
```

If a staff member belongs to multiple subsidiaries, they can switch context.

But the workspace doesn't reset.

It simply changes the operational context.

---

# 25. "All Companies" mode

For authorised users:

```text
ALL COMPANIES

My Tasks              14
Requests               6
Approvals              3
Active Work             5
```

Then:

```text
Atiat Insurance
   5 tasks

Atiat Mobility
   4 tasks

Atiat Travel
   3 tasks

Atiat POF
   2 tasks
```

This will be very useful for the central/admin side of the multi-company Synbot architecture.

---

# 26. Mobile behaviour

We should design desktop first because this is primarily an enterprise workstation.

But the Staff Workspace should collapse beautifully into mobile.

Mobile:

```text
┌─────────────────────────┐
│ ☰  Synbot       🔔      │
├─────────────────────────┤
│                         │
│ Good morning, Mofe 👋   │
│                         │
│ ● Working  04:32        │
│                         │
│ ┌───────┐ ┌───────┐     │
│ │  7    │ │  3    │     │
│ │ Tasks │ │ Due   │     │
│ └───────┘ └───────┘     │
│                         │
│ TODAY                   │
│                         │
│ 🔴 Verify shipment      │
│ 🟠 Review invoice       │
│ 🟡 Finance request      │
│                         │
│ ─────────────────────   │
│                         │
│ Needs Attention         │
│                         │
├─────────────────────────┤
│ 🏠    ✓    💬    👥   │
│ Day   Work  Inbox Team │
└─────────────────────────┘
```

---

# 27. The command bar

Eventually, I would add one particularly powerful feature.

Press:

**Ctrl + K**

or click search.

```text
What do you want to do?

> Create task
> Create reminder
> Find Sarah
> Find PO-1024
> Request information
> Show my tasks
> Show what I'm waiting for
> Ask Synbot
```

This becomes the bridge between traditional UI and AI.

---

# 28. Synbot AI panel

Then:

```text
┌───────────────────────────────────────┐
│ Ask Synbot                         ×  │
├───────────────────────────────────────┤
│                                       │
│ What do you need help with?           │
│                                       │
│ "What should I focus on today?"       │
│                                       │
│ ───────────────────────────────────   │
│                                       │
│ Based on your work:                   │
│                                       │
│ 1. Supplier shipment — due 10:30      │
│ 2. Finance request — waiting          │
│ 3. Invoice review — due today         │
│                                       │
│ You also have a supplier call at      │
│ 2:00 PM.                              │
│                                       │
│ [Create my plan]                      │
└───────────────────────────────────────┘
```

This is where the Synbot name starts making sense at the employee level.

---

# 29. Notification architecture

We should define this now.

Four levels:

### Critical

Immediate.

Examples:

* urgent operational issue
* approval deadline
* failed critical process

### Action Required

Needs employee action.

Examples:

* assigned task
* information request
* approval

### Informational

Useful but not urgent.

Examples:

* shipment received
* task completed by teammate

### Social

Collaboration.

Examples:

* mention
* comment
* direct message

The employee should be able to control notification preferences.

---

# 30. The most important UX rule

I would establish this as a Synbot design rule:

> **Never make the employee open a different page when the action can be completed in context.**

Examples:

Task appears → start it there.

Request appears → answer it there.

Reminder appears → snooze it there.

Shipment task → record receipt there.

Message appears → respond there.

Approval appears → approve there.

This is consistent with the existing workflow philosophy in the Royan work: the dashboard was intended as the main place where staff work, with actions leading directly into the relevant workflow. 

---

# 31. Backend structure

Now we can map the UI into actual services/tables.

I'd create a generic workspace layer roughly like this:

```text
staff
staff_profiles
staff_preferences
staff_roles
staff_teams
staff_company_memberships

staff_tasks
staff_task_comments
staff_task_checklists
staff_task_activity

staff_reminders

staff_requests
staff_request_messages
staff_request_activity

staff_notifications

staff_time_sessions
staff_break_sessions

staff_work_events

staff_metrics
```

Then operational systems connect into it:

```text
procurement
inventory
finance
clinical
hr
orders
shipments
```

---

# 32. One critical field: `source`

Every task should know **where it came from**.

For example:

```text
source_type:
    manual
    assigned
    operational
    recurring
    request
    automation
    ai
```

So Synbot can distinguish:

> Mofe created this task manually.

from:

> This task was automatically generated because a shipment arrived.

That becomes extremely valuable for analytics and AI.

---

# 33. One critical field: `entity_reference`

Tasks should also optionally point to a real business object.

```text
task
 ├── source_type
 ├── entity_type
 └── entity_id
```

Example:

```text
entity_type = purchase_order
entity_id   = PO-1024
```

or:

```text
entity_type = patient
entity_id   = PAT-000928
```

or:

```text
entity_type = invoice
entity_id   = INV-3041
```

Now the task isn't floating independently from the business system.

It is **attached to reality**.

---

# 34. The complete task model

Conceptually:

```text
STAFF TASK

Identity
 ├─ id
 ├─ title
 └─ description

Ownership
 ├─ created_by
 ├─ assigned_to
 ├─ team_id
 └─ department_id

Organisation
 ├─ company_id
 ├─ subsidiary_id
 └─ facility_id

Planning
 ├─ priority
 ├─ due_at
 ├─ start_at
 └─ status

Business Context
 ├─ source_type
 ├─ entity_type
 └─ entity_id

Collaboration
 ├─ comments
 ├─ requests
 ├─ attachments
 └─ mentions

Audit
 ├─ created_at
 ├─ updated_at
 └─ activity
```

This is the foundation.

---

# 35. The task state machine

I'd lock this in now:

```text
                    ┌─────────────┐
                    │    INBOX    │
                    └──────┬──────┘
                           ↓
                    ┌─────────────┐
                    │  ACCEPTED   │
                    └──────┬──────┘
                           ↓
                    ┌─────────────┐
                    │ IN PROGRESS │
                    └──────┬──────┘
                           │
              ┌────────────┴────────────┐
              ↓                         ↓
       ┌─────────────┐          ┌─────────────┐
       │   WAITING   │ ───────→ │ IN PROGRESS │
       └─────────────┘          └──────┬──────┘
                                       ↓
                                ┌─────────────┐
                                │  COMPLETED  │
                                └──────┬──────┘
                                       ↓
                                ┌─────────────┐
                                │  VERIFIED   │
                                └──────┬──────┘
                                       ↓
                                ┌─────────────┐
                                │    CLOSED   │
                                └─────────────┘
```

That gives us a proper workflow engine rather than a checkbox system.

---

# 36. What v1 should actually look like

If we're building this now, **I would not build all nine screens immediately.**

The first usable release should contain:

### Navigation

* My Day
* My Work
* Inbox
* Team
* Progress

### My Day

* personalised greeting
* work timer
* today's tasks
* reminders
* needs attention
* quick actions
* operational widgets

### My Work

* tasks
* filters
* Waiting
* Completed
* task drawer
* task workspace

### Inbox

* requests
* mentions
* assignments
* notifications

### Team

* people
* availability
* message
* request
* assign

### Progress

* personal metrics
* work journal
* weekly activity

That is enough to create a **real Staff Workspace**, rather than another dashboard prototype.

---

# 37. And then the big evolution

Once that works, we connect:

```text
                 SYNBOT STAFF WORKSPACE
                          │
          ┌───────────────┼────────────────┐
          │               │                │
       PERSONAL       COLLABORATION      TIME
          │               │                │
          └───────────────┼────────────────┘
                          │
                   OPERATIONAL ENGINE
                          │
        ┌─────────┬───────┼───────┬──────────┐
        │         │       │       │          │
      HR       FINANCE  STOCK   SALES    CLINICAL
        │         │       │       │          │
        └─────────┴───────┼───────┴──────────┘
                          │
                    COMPANY DATA
                          │
                         AI
```

That is the part I really like about this direction.

We're **not building another Asana, Slack, or Monday**.

We're building a work interface that understands the actual operations of the organisation.

---

## My recommendation for the next build step

Before touching React, I would now freeze the **Staff Workspace v1 UX contract** and translate this into three technical artefacts:

1. **Frontend component hierarchy** — exactly what React components/pages we need.
2. **PostgreSQL schema** — tables, relationships, indexes, company/subsidiary/role structure.
3. **FastAPI API contract** — endpoints for tasks, requests, notifications, time, teams and activity.

Then we can build the frontend against a stable backend contract instead of designing screens and changing the database underneath them.

And importantly, we'll design the schema with **Atiat's multi-company structure from day one**, while keeping the actual Staff Workspace generic enough to reuse across RoyanHealth, Placeware, Atiat and future Synbot deployments.
