# How the Placeware / ACE system was designed and connected

A replication guide for RoyanHealth (Synbot Health)

Status as of 30 Sep 2026. Covers User Access, HR and My Workspace, Operations, CRM, Frontdesk,
Inventory & Quality, the Logistics Calendar, the Executive Overview, Reports, and ACE (the chat).
Accounting (ACE Books) is mentioned only as the source the other modules read from. It has its
own handover document at `backend/docs/Financial-engine/ACE-Books.md`.

Read with:
- `backend/docs/ACE-Workspace-Standard.md`: the page-layout standard, which itself came from RoyanHealth's UDWS.
- `backend/docs/ACe guide/`: ACE's behaviour, grounding and evaluation.
- `backend/docs/Staff-workspace/IMPLEMENTED.md`: the research behind My Workspace, mapped to code.

---

## 1. The ideas that shaped every module

These rules matter more than any single screen. Every module below follows them. RoyanHealth should adopt them first and design its screens second.

1. **Enter a fact once; every page reads it from the module that owns it.**
   - Money lives in ACE Books.
   - Batches and quality status live in Inventory & Quality.
   - Stock orders and suppliers live in Operations.
   - Customers and deals live in CRM.
   - People and hours live in HR and My Workspace.

   No page keeps its own copy. Old pages that recorded the same thing twice were removed or turned into redirects: Customer Receipts, Vendor Payments, Budget, Staff Dashboard, Time Tracker, Collaboration and `/admin/leads`.

2. **Each module has one "hub" service with the same shape.** It exposes:
   - `overview()`, which feeds the module's KPI cards
   - a list or directory
   - a detail or profile for one record
   - the actions

   Examples: `crm_hub.py`, `hr_hub.py`, `quality_hub.py`, `stock_orders.py`, `executive.py`, `staff_workspace.py`. Other modules and ACE call these services. They never query another module's tables directly.

3. **Every number is real, and says how fresh it is.**
   - There are no fabricated trends, sparklines or "+34%" badges. Round 7 removed exactly these.
   - An empty result shows as 0 or "none recorded", never as a plausible-looking figure.
   - When data is stale, the page says so. For example, the Executive Overview ages receivables at the day before cut-over and shows "July–September not yet loaded" rather than letting everything appear 90+ days overdue.

4. **Every card and every attention item links to the page that fixes it.** A number is a doorway, not decoration. The Executive Overview is built entirely on this rule.

5. **Work flows across roles as a chain, and each step belongs to one role.** Order to cash, procure to pay and a batch's life each move through several departments. Each step appears automatically in the next person's queue: their My Day, "For your role".

6. **Operational items close themselves.** A person "takes" an item such as a batch to release, so it becomes their task. When the record is dealt with in its own module, the task closes automatically. No one ticks it off by hand.

7. **Access is enforced on the server and mirrored in the UI.**
   - One role list (`roles.py`).
   - The sidebar hides what a role can't open.
   - Route guards and API checks enforce it anyway.
   - ACE's live lookups follow the same roles.

8. **Missing data is shown as missing.** "No expiry recorded" is not "doesn't expire", and "no account owner recorded" is not "no owner". The same rule applies to screens, reports and ACE.

9. **Changes are tested before they ship.** Every module has a flow test that exercises the real routers inside a transaction that is rolled back, plus a Playwright screenshot pass. No test data is left in the live database.

---

## 2. Navigation: how pages were grouped

### 2.1 The sidebar (`SynbotUI/client/components/Sidebar.tsx`, `NAV_ITEMS`)

| Group | Children | Who sees it |
|---|---|---|
| My Workspace | (tabs inside) My Day, My Work, Inbox, Messages, Team, Progress | everyone |
| Dashboard | ACE Workstation with department tabs | everyone |
| Executive Overview | one page | admin, management, finance |
| ACE Books | Finance Control Tower, Sales & Receivables, Purchases & Payables, Stock, Banking, Journals & Ledger, Financial Statements, Report Center, Credit Control & Alerts, Fixed Assets, Close & Controls, Setup & Migration, Sage Import / Export | admin, finance, management |
| HR | (tabs) Overview, Staff directory, Timesheets | admin, hr, management |
| Inventory & Quality | Overview, Stock, Quality Control\*, Compliance & QMS\* | ops, procurement, finance, sales, QA, management, admin (\* QA/management/admin; Compliance also ops) |
| Operations | Overview, Project Controls\*, Suppliers, Stock Orders & Purchases, Logistics Monitor | ops, procurement, management, admin (\* not procurement) |
| CRM | Overview, Customers, Customer Workspace, Sales Pipeline, Leads & Prospecting | sales, finance, management, admin |
| Frontdesk | tabs Today's queue, New walk-in, All invoices, Reports | frontdesk, sales, finance, ops, QA, management, admin |
| Logistics Calendar | one page | everyone |
| Reports | Generate Report, Report Library | all working roles |
| Workflow, User Access, Data Intelligence, Settings | admin tools | admin |
| Ask ACE, Agent Stack | chat; agents | everyone; admin and management |

### 2.2 Grouping rules we followed

- **Group by the job a person does, not by the database.**
  - "Inventory & Quality" puts stock, batch release, recalls and compliance together, because the same people act on them and one batch status connects them all.
  - "Operations" is buying and moving stock: stock orders, suppliers, logistics.
  - The Finance group was dissolved into "ACE Books", so accounting is one place.
- **Each group opens on an Overview.** It holds the KPI cards and a "needs attention" list for that area, then the working pages.
- **The personal page comes first.** My Workspace sits at the top of the sidebar because every role starts its day there.
- **One page is better than several near-duplicates.** Staff Dashboard, Time Tracker and Collaboration became tabs of My Workspace. AR Ageing in two places became one canonical view.
- **Old links redirect** to the new home, so bookmarks keep working and nothing is lost.
- **Children can carry their own roles.** For example, Project Controls is hidden from procurement even though the rest of Operations isn't.
- **`visibleNav(roles)` is exported,** so User Access can show exactly which menus a new user will see before the account is created (see §4).

**RoyanHealth:** the same shape works. Suggested groups:
- My Workspace
- Executive / Medical Director overview
- Billing & Accounts (the ledger)
- HR
- Pharmacy & Stores + Quality
- Procurement & Facilities
- Patient Relations (HMO / corporate accounts)
- Reception
- Calendar
- Reports
- Admin

Keep clinical work (encounters, wards, lab) as its own group, because it is a distinct job.

---

## 3. The shared UI kit and page anatomy

### 3.1 Components (`SynbotUI/client/components/workspace/` and per-module kits)

| Component | Use |
|---|---|
| `PageHeader` | icon, title, one-line subtitle saying where the data comes from, header actions |
| `KpiStrip` | row of metric cards directly under the header |
| `FilterBar` | search box plus dropdown filters; owns the "all" sentinel so callers see `""` |
| `DetailSheet` | the only side panel (shadcn `Sheet`), used for a record's full detail and for any multi-field create form |
| `EntityAutocomplete` | typeahead for large catalogues (customers, products, suppliers, staff); small fixed lists use a plain `Select` |
| `ReportButton` | "Write report" on any record, opens the report composer at the review step |
| Module kits | `components/crm/crm-kit.tsx`, `components/staff/ws-kit.tsx`, `components/books/kit.tsx`, `components/quality/*`, `components/hr/hr-panels.tsx` hold the module's own cards, badges and panels |

### 3.2 Page anatomy (the order is the same on every module page)

```
PageHeader            title · "from ACE Books / live" subtitle · 1–2 primary actions
KpiStrip              4 (sometimes 6–8) metric cards, each clickable
Tabs (?tab= in URL)   the module's working views; the URL keeps the tab so links can deep-link
  List / table        FilterBar on top; each row opens the record
  Detail              inline Detail Workspace (3-column pages) or DetailSheet (list pages)
Sheets / dialogs      create forms in DetailSheet; single-input confirmations (reason, void) in Dialog
```

Rules from `ACE-Workspace-Standard.md`:
- Prefer inline editing, then a side panel, then a dialog, then a new page.
- A selected record stays selected.
- Every action is audited.
- Money posts are deliberate and confirmed, never auto-saved.

A full List/Detail/Actions workspace is used only when a record has more to show than its row. Flat registries get just `KpiStrip`, `FilterBar` and `DetailSheet`.

### 3.3 How cards are arranged

- **Four headline cards per module overview.** They are ordered: size of the business, then money at stake, then what's at risk, then what needs action.
  - CRM: Active customers · Sales, last 30 days · Owed by customers · Follow-ups due. The second row holds Open deals · Won, last 90 days · Gross margin, 12 months · New leads this week.
- **Each card has a label, one value, and a short "sub" line.** The sub line gives the context that makes the number meaningful: as-of date, count behind a value, or share of total. Tone is used sparingly: red for danger, amber for warning, green for good.
- **Labels are plain English, with the period in the label.** For example "Sales, last 30 days" and "Won, last 90 days", never just "Sales".
- **The Executive Overview is a grid, not a strip:**
  - a row of 8 `Tile`s (money)
  - a wide "Needs your attention" panel and a sales-trend chart
  - then one `Panel` per department, each a list of `Row`s (label · value · tone · link)

  This `Tile` / `Panel` / `Row` trio is the reusable pattern for any control-centre page.
- **Realtime refresh uses channels, not polling.** `useRealtimeChannel("<module>_updates")` invalidates the page's queries when another user changes something. Channels: `frontdesk_updates`, `workspace_updates`, `staff_updates`, `crm_updates`, `finance_updates`, `inventory_updates`, `logistics_updates`, `calendar_tasks`, `alerts_updates`.
- **Server state** lives in TanStack Query; there is no global store.

---

## 4. User Access (admin)

**Purpose:** create logins, give each person one or more roles, reset passwords, and change access later. Everything else (HR profile, Team card, sidebar) follows from here.

**UI (`pages/AdminUsers.tsx`, `components/admin/RolePicker.tsx`)**
- **Create user:** email, password, role checkboxes (multi-select), optional name, department and job title, and a required reason (audited).
- **`RolePicker`:** one checkbox per role, with a one-line description of each. Picking any real role removes "viewer".
- **`AccessPreview`:** lists exactly which sidebar menus the chosen roles will see. It is computed with the same `visibleNav(roles)` the sidebar uses, so it can't drift.
- **Edit access** on an existing user: change roles, give a reason. It takes effect when their session next refreshes.
- **Departments** come from the server, so HR and User Access always agree.

**Backend**
- **`backend/src/roles.py`:** the single `ROLE_CATALOG`.
  - roles: frontdesk, sales, finance, ops, procurement, quality_assurance, hr, management, admin, viewer
  - `LEGACY_ALIASES` (`qa`)
  - `ALLOWED_ROLES`
- **`GET /users/roles`** returns roles and departments.
- **`PUT /users/{id}/roles`:** admin only, reason required, cannot remove your own admin, audited.
- **`POST /users`** always calls `staff_workspace.ensure_profile`, which creates the HR profile (name from the email, department from the role). The person immediately appears in HR and on the Team tab.
- **Migration 127** added the Frontdesk department.

**Key decision:** a person can hold several roles; access is the union of them. Don't create combined roles such as "sales+finance".

**RoyanHealth:** the same model, with a hospital role catalogue:
- reception
- nurse
- doctor
- pharmacist
- lab
- billing
- store
- quality
- hr
- management
- admin

Keep one catalogue file and one `visibleNav` preview.

---

## 5. HR and My Workspace (people, hours, work)

These two are designed as a pair:
- **My Workspace is where each person works.** They clock in, see their day, do tasks, answer requests and send messages.
- **HR is the management view of the same records.** Who is in, hours per person, timesheet approval, profiles.

Nothing in HR is typed twice. Hours come from the work clock.

### 5.1 My Workspace (`pages/StaffWorkspace.tsx`, `components/staff/ws-kit.tsx`, `ws-panels.tsx`)

It replaced three pages: Staff Dashboard, Time Tracker and Collaboration.

| Tab | What it shows |
|---|---|
| My Day | clock card (Start work / Break / End work), timeline of what's due today, "For your role" operational items, requests to answer, waiting on others, "my day so far" journal |
| My Work | all my tasks: filters, statuses (open, in progress, waiting, done), checklists, repeat |
| Inbox | notifications and requests, with filter all / action / unread |
| Messages | direct and team threads (`dm:a:b`, `team:all`), @mentions |
| Team | a card per colleague: online / on the clock, open work, Ask, Message |
| Progress | tasks completed, on time %, requests answered, hours worked (from real records) |

KPI cards on My Day: My open tasks · Due today · To answer · Waiting on others. Progress: Tasks completed · On time · Requests answered · Hours worked.

**Top bar on every page:** a `ClockPill` (clock state and Start/End work from anywhere) and an inbox bell.

**Typing a task:** the QuickAdd bar parses a sentence into a task, reminder or request. It is deterministic, with no AI (`task_language.parse`). Examples:
- "Remind me to call Skylark every Monday at 10am"
- "Ask Tayo to send timesheets by Friday, urgent"

**Recurrence:** daily, weekly, monthly and similar, with an end date. The next occurrence is created when the current one is done.

**Escalation chains:** per subject (task or request) and priority, in `staff_escalation_policy`. When work passes its due time the chain fires step by step: the assignee, then whoever gave it, then management, at configured hours. It is set in My Workspace → Customise → Escalation rules (admin, management, hr). A server loop runs every 5 minutes.

Seeded chains:
- task critical: 0h assignee, 2h giver, 8h management
- task high: 0h, 24h, 72h
- request: 0h recipient, 24h requester, 72h management

**"For your role" (the connecting mechanism).** `RULES` in `services/staff_workspace.py` is a table of live signals. Each signal is a query over another module plus the roles that should see it:

| Rule | Label | Seen by |
|---|---|---|
| `stock.to_order` | Stock orders to place | ops, procurement |
| `stock.deliveries` | Deliveries due | ops, quality |
| `quality.due` | Quality & compliance due (batches to release, audits, deviations, maintenance, recalls) | quality |
| `stock.expired` | Expired stock still sellable | quality, finance |
| `finance.bills_due` | Supplier payments due this week | finance |
| `crm.follow_ups` | Customer follow-ups due | the owner (personal) |
| `crm.cold_deals` | Proposals going cold | the owner (personal) |
| `hr.timesheets` | Timesheets to approve | hr |
| `hr.long_clocks` | Clocks left running | hr |

"Take it" turns an item into a task linked to the record (`entity_*`, `link`). Each time the rule runs, items that have disappeared from the signal close their task with "resolved in …". The person never marks it done by hand.

**Backend**
- `services/staff_workspace.py`: people, `ensure_profile`, clock, tasks and transitions, requests, inbox, messages, team, progress, journal, `my_day`, preferences, `RULES`.
- `services/task_language.py`, `services/workspace_automation.py` (recurrence, escalation).
- Router `/workspace`; realtime channel `workspace_updates`.

**Tables** (migrations 124–125):
- `staff_time_sessions` (one open session per user)
- `placeware_timesheets` (plus `user_id`, `session_id`, `source`, `status` submitted / approved / rejected)
- `placeware_tasks` (plus `kind`, `department`, `entity_*`, `link`, `checklist`, `waiting_on`, `recurrence`, `series_id`, escalation fields)
- `staff_task_activity`, `staff_requests` plus `staff_request_messages`, `staff_notifications`, `staff_work_events`, `staff_preferences`, `staff_escalation_policy`

**Clock logic:**
- The clock runs on the server; the browser only shows it.
- Break time is excluded.
- Sessions that cross midnight are split per day.
- A session over 16 hours asks for the real end time.
- "End work" writes the timesheet row as `submitted`.

"Overdue" means past the due **time**, not the due day.

### 5.2 HR (`pages/HR.tsx`, `components/hr/hr-panels.tsx`)

| Tab | Content |
|---|---|
| Overview | Online now · On the clock now · Hours recorded this week (saved timesheets plus clocks still running, summed) · Awaiting approval; a per-person hours grid for the week |
| Staff directory | everyone created in User Access, with profile, department and status; click a person for the `PersonSheet` (profile, hours, recent activity, Edit) |
| Timesheets | entries by week and person, with status; Approve / Reject (with note) / Adjust / Add hours / Approve week / Export CSV |

Header action: "Add staff record" (admin, hr).

Hours are shown in two parts: "Running now (not yet saved)" and saved hours. The headline is honest while people are still on the clock.

**Backend:** `services/hr_hub.py` (overview, directory, person, `update_person`, `create_person`, timesheets, `add_entry`, `review`, `approve_week`, csv); router `/hr`; channels `staff_updates` and `workspace_updates`.

**RoyanHealth:** this carries over directly. It is not domain-specific. Add rule rows for hospital signals, for example:
- patients waiting over N minutes (reception, nurse)
- lab results to review (doctor)
- prescriptions to dispense (pharmacy)
- drugs expiring (pharmacy)
- HMO claims to submit (billing)

Shift rosters and leave are not built here (leave is a known gap). A hospital will need both, so add them to HR in the same pattern.

---

## 6. Operations (buying and moving stock)

| Page | Content |
|---|---|
| Overview (`Operations.tsx`) | cards: Items in stock · Stock value at cost · Items to order now · Expiring within 90 days; tabs Inventory / Logistics / Procurement (import shipments: at port → under clearance → released → delivered to warehouse) / Settings |
| Stock Orders & Purchases (`PurchaseOrders.tsx`, `components/operations/stock-orders.tsx`) | tabs **Reorder plan** (needs ordering, order soon, expiry risk, healthy, no recent sales), **Stock orders** (requested → approved → with supplier → received / cancelled), **Supplier invoices**; tab labels carry live counts |
| Suppliers | cards: Active suppliers · Bought in the last 12 months · We owe suppliers · Suppliers in credit; filters Bought from in 12 months / We owe / All; Add supplier; per-supplier what we owe, buy and how often |
| Project Controls | active projects, stage board, deliveries, stock orders; create project (ops, management) |
| Logistics Monitor | deliveries (new delivery, start, status, GPS pings), riders (rider app sign-in), live map; customers get a tracking link |

**Reorder plan logic** (`services/stock_orders.reorder_plan`):
- Planning is per **product family**, never per lot code. The client's Sage used one item code per lot, so `FAMILY_SQL` strips the trailing "(A)".
- Demand is average daily sales over the last 180 days.
- Reorder when stock won't cover 30 days of supplier lead time plus 14 days of safety stock.
- The suggested quantity tops cover up to 60 days.
- Statuses: out_of_stock / reorder_now / reorder_soon / healthy / no_recent_sales. Each row carries an expiry-risk flag.

**Stock order lifecycle:**
- requested → approved (by procurement, ops, finance, management or admin) → ordered (expected date) → received.
- Nobody marks an order "received" by hand. It becomes received automatically when finance posts the supplier bill for any lot of that product in ACE Books.

**Backend:**
- `services/stock_orders.py`: summary, reorder plan, orders, supplier directory, supplier invoices.
- Routes `/procurement/stock-orders*`, `/reorder-plan`, `/purchases`, `/suppliers`, `/ops/overview`.
- Migration 121.

**Lesson:** the Sage "purchase orders" were really supplier-invoice history, so they were retired from all screens. Check what legacy data actually is before building on it.

**RoyanHealth:** this becomes Procurement & Stores. Map products to drugs and consumables, and suppliers to vendors. The same reorder formula works per drug per store. Logistics maps to internal transfers or ambulance dispatch if needed.

---

## 7. CRM (customers, pipeline, prospecting)

| Page | Content |
|---|---|
| Overview (`CRM.tsx`) | cards: Active customers · Sales, last 30 days · Owed by customers · Follow-ups due / Open deals · Won, last 90 days · Gross margin, 12 months · New leads this week; charts from real monthly sales (no invented forecast points) |
| Customers (`CRMCustomers.tsx`) | cards: Buying customers · Sales, 12 months · Owed by customers · At risk. Filters: Buying, At risk, Due to reorder, Owes past due, Lapsing, Lapsed, Never bought. Click a customer for a panel with tabs **Sales**, **What they buy**, **Invoices**, **Account (ACE Books)**, **Contact & deals**; buttons Log call/visit, Reminder, New deal, New request, Edit, Report |
| Customer Workspace | search-first single customer: raise a request or order, see sales, invoices and deals (`?customer=id` deep link) |
| Sales Pipeline (`SalesCRM.tsx`) | tabs Pipeline (New → Qualified → Proposal → Won / Lost), Reminders, Weekly report (CSV/print), Targets, Leaderboard, Ask ACE; Message customers (bulk) |
| Leads & Prospecting | find businesses by GPS or area (type, radius), worked prospects, website enquiries; "Add to pipeline" |

**Definitions** (they matter because other modules reuse them):
- **Segments:**
  - active: bought in the last 90 days
  - new: first order in the last 90 days
  - lapsing: last order 3–12 months ago
  - lapsed: over 12 months ago
  - never bought
- **At risk:** sales down 30% or more on last year, well past their usual reorder gap, or owing 60+ days overdue.
- **"Slipping" (Executive Overview):** the same, **excluding** the debt-only reason, so the sales view isn't inflated by collections problems.
- **Reorder cycle:** the average gap between a customer's orders. "Next order due in N days" follows from it.

**Connections:**
- Sales, margin and balances come from ACE Books views (`v_sales_lines`, `v_customer_invoices`, `v_ar_open`), not from CRM tables.
- A deal is marked **won automatically** when an ACE Books invoice posts for its customer.
- Winning a deal creates the customer.
- The credit limit is edited in CRM (admin, finance, management) and enforced by ACE Books when invoicing.

**Backend:**
- `services/crm_hub.py` + router `/crm/*`: overview, directory, customer/{id}, pipeline, deals, reminders, prospects, inbound, weekly-report, targets, leaderboard, reps, new-customer.
- Migration 123 archived imported fake leads.

**RoyanHealth:** CRM becomes Patient Relations / Accounts.
- Customers map to HMOs, corporate clients and self-pay patients.
- The pipeline maps to HMO or corporate contracts.
- "What they buy" maps to services used.
- "Account" is the billing ledger.
- The segment and at-risk definitions translate to "patients or HMOs not seen in N months" and "claims overdue".

---

## 8. Frontdesk (the order-to-cash entry point)

**Tabs:** Today's queue · New walk-in · All invoices · Reports. Header cards show:
- Walk-ins Today
- Invoices Raised
- Pending QC
- Pending Finance
- Revenue Today

**Flow (each step belongs to one role and appears in that role's queue live):**

```
New walk-in (customer + line items, stock check per line: in stock / low / out)
  -> registered / invoice raised
  -> QC checks it            (quality role)        pending_qc
  -> Finance approves it     (finance role)        pending_finance -> finance_approved | finance_rejected
       -> invoice posts to ACE Books (credit limit enforced; override needs a reason)
  -> Dispatch                                      dispatched -> delivery created in Logistics Monitor
  -> completed / delivered   (customer tracking link)
  -> payment recorded in ACE Books -> drops out of receivables
```

**UI pattern:** the All invoices tab is a full 3-column workspace (list | detail | actions). The detail is role-aware: QC sees the QC action, finance sees approve/reject, and so on. It was the first retrofit to the Workspace Standard.

**Realtime:** `frontdesk_updates` is broadcast on every status change, so the QC and finance queues refresh without polling.

**Reports tab:** an Activity report written through the standard report sequence (§12).

**RoyanHealth:** Frontdesk is Reception.
- A walk-in becomes a patient registration or visit.
- Line items become services.
- The QC → Finance → Dispatch chain becomes Triage/Consult → Billing/Cashier → Pharmacy dispense.

Keep "each step is one role's queue, refreshed live", and "the bill posts to the ledger at the approval step".

---

## 9. Inventory & Quality

| Page | Content |
|---|---|
| Overview (`QualityHub.tsx`) | cards: Stock at cost · Held from sale · Expired or expiring ≤30 days · Won't sell before expiry · Open recalls · Open deviations · Audits · Maintenance. Below: "needs attention now" and "next 14 days" (recalls, deliveries, incoming batches, audits, maintenance, deviations, CAPA, expiry) |
| Stock (`Inventory.tsx`) | cards: Live Families in Stock · Low / Critical Families · Out of Stock Alerts · Pending Reorders · Value at Expiry Risk; Receive stock, Log stock adjustment (sent for finance approval), analytics tabs Already expired / No expiry recorded / Expiry exposure / Dead stock / Needs reorder / Reorders in flight; Request / cancel reorder |
| Quality Control | tabs Release queue (Release / Reject incoming batches), Expiry (by product: quarantine, release, write off, recall a lot), Recalls (open, trace customers, record returns, close), Temperature (manual until the sensor system is connected) |
| Compliance & QMS | tabs Audits (schedule, findings, complete; next one auto-scheduled), Deviations & CAPA, Maintenance (equipment, schedule, complete), SOPs, Documents |

**Batch status connects everything.** The same lot status in ACE Books drives sales, quality and the ledger:
- **AVAILABLE:** can be sold.
- **QUARANTINED:** held, for example awaiting release or rejected.
- **RECALLED:** frozen.

Selling always takes the oldest available unexpired lot. A named expired batch is refused. SALE and loan issues skip recalled, quarantined and expired lots.

**Batch release:** a registered incoming batch is QUARANTINED until QC decides. Release makes it sellable. Reject keeps it held and **automatically raises a deviation**.

**Recall:** opened once, recorded in both the QMS case (reason, authority, documents) and ACE Books (batch frozen, every buyer traced, returns tracked). Closing it closes both.

**Compliance score (shown here and on the Executive Overview):** 100 minus deductions for what is overdue today:
- 8 per overdue audit
- 3 per open deviation, plus 3 more if overdue
- 4 per overdue maintenance
- 5 per open recall

**Stock writes:** direct stock edits are refused for items the ledger manages (`StockInBooksError` → 409). Receive, adjust and write-off create ACE Books documents that another person approves (maker-checker). This keeps the stock value and the ledger identical.

**Backend:**
- `services/quality_hub.py` + router `/quality`: overview, recalls, deviations, batches, calendar feed, reschedule.
- `QualityActionsProvider` supplies the shared "schedule / initiate" forms used from several pages.
- Migration 122.

**RoyanHealth:** this is Pharmacy & Stores + Quality, and it maps almost 1:1.
- Drug lots, expiry, quarantine, release on receipt inspection and recalls are the same.
- Deviations become incident reports.
- Audits, equipment maintenance and SOPs are the same.
- Temperature monitoring (vaccine fridges, blood bank) matters even more.

---

## 10. Logistics Calendar

One calendar over the **real records**, not a separate diary (`pages/LogisticsCalendar.tsx`). It shows:
- stock deliveries (stock orders placed with suppliers)
- incoming batches for QC
- recall returns
- audits
- maintenance
- deviation close dates and CAPA actions
- lots expiring
- other events

**Moving an item moves the record itself.** Dragging it to another day, or picking a date in its panel, calls `quality_hub.reschedule()` on the source record. "Schedule" creates the real record (recall, audit, maintenance, batch), which then appears here and on its own page.

**Backend:** `GET /quality/calendar` (`quality_hub.calendar_feed`); channel `calendar_tasks`.

**Design choice:** a calendar that owns its own events drifts from reality. A calendar that is a view over the records can't.

**RoyanHealth:** the same idea for appointments, theatre bookings, equipment maintenance, audits, drug expiry and staff rosters. Every entry is a record owned by its module.

---

## 11. Executive Overview (the control centre)

One page for the CEO/CFO (admin, management, finance) (`pages/Executive.tsx` ← `GET /dashboard/executive` ← `services/executive.py`, cached 5 min, `?refresh=true`).

**Layout (top to bottom)**

1. **8 money tiles:**
   - Revenue this year (to date)
   - Gross profit this year
   - Net profit this year
   - Cash & bank
   - Customers owe us (at date)
   - We owe suppliers (at date)
   - Stock (cost)
   - Working capital

   Each tile links to its ACE Books page. Tone: red for net loss; amber when more than 30% of receivables are over 90 days, or supplier bills are overdue.
2. **Needs your attention:** a ranked list of cross-module issues, critical first. It shows 6 items with "Show all", and each item opens the page that fixes it. Next to it, **Sales by month**, with margin and last year's line.
3. **Receivables ageing** (0–30 / 31–60 / 61–90 / 90+ bar), customers over their credit limit, supplier bills past due or due in the next 30 days.
4. **Cash by account.**
5. **Books & controls:**
   - last trading posted
   - months still to load
   - past months still open
   - bank accounts reconciled (x of y)
   - last reconciliation
   - drafts not yet posted
6. **Top customers** (and the top-10 share of sales) and **Top products**, last 12 months.
7. **One panel per department, each a list of rows that link through:**
   - **Customers & pipeline:** active, new, lapsing, slipping regulars, open pipeline, win rate.
   - **Stock & purchasing:** value, days of cover, out of stock, to reorder, open orders, overdue deliveries, 12-month purchases.
   - **Quality & compliance:** score, expired stock, expiring in 90 days, open recalls, open deviations, audits overdue or due, batches awaiting release.
   - **People & work:** team members, online / on the clock, hours this week, timesheets to approve, open and overdue tasks, done in 7 days, open and late requests.

**How it connects:** `executive.py` calls each module's hub service, never its tables:
- `_finance` reads ACE Books: income statement for the year to date, cash by GL account, ageing, credit breaches, controls.
- `_sales` reads `v_sales_lines`.
- `_customers` reads the CRM directory.
- `_stock` reads `stock_orders.summary`.
- `_quality` reads `quality_hub.overview`.
- `_people` reads `hr_hub.overview` and workspace counts.
- `_attention` merges the urgent items from each.

It adds no new data, only composition.

**Honesty rules on this page:**
- Stale books are aged at the cut-over minus 1 day, with a banner.
- Only bank accounts that hold cash are counted in "x of y reconciled".
- "Slipping" excludes debt-only risk.
- The reports button writes an Executive report through the standard sequence.

**RoyanHealth:** a Medical Director / CEO overview with the same skeleton:
- money tiles (revenue, collections, HMO receivables, cash)
- an attention list
- panels per department:
  - Patients: visits, admissions, bed occupancy, waiting times
  - Pharmacy: stock-outs, expiry
  - Quality: incidents, audits
  - People: on shift, hours

---

## 12. Reports: one sequence everywhere

Every report in the app is written **about a chosen record**, in four steps (`pages/ReportComposer.tsx` at `/reports/new`):

1. **What kind of report:** deviation, CAPA, recall, audit, maintenance, batch, sales/invoice, customer, product, stock order, P&L or period, executive.
2. **About exactly what:** the deviation, the sale, the customer, the product, the month.
3. **Review what ACE gathered:** every fact from the module that owns the record, tables, and an explicit list of what is **not recorded**. The author adds notes.
4. **Generate:** the report is written only from that record, and the record is attached as the appendix. Download Word, or approve as final.

**Shortcuts:** a `ReportButton` on any record opens the composer at step 3 (`/reports/new?type=deviation&kind=deviation&id=…`). It appears on:
- deviation, recall, audit, maintenance and decided-batch panels
- the customer panel
- Frontdesk
- the Executive Overview

**Report Library** lists every report with its subject (click to reopen the record), type and status (draft / complete / approved).

**Backend:**
- `services/report_subjects.py`:
  - `REPORT_TYPES`
  - a lister per kind (for step 2)
  - `dossier()` per kind: facts, tables and what's missing (for step 3)
  - `SECTIONS`, `sections_for`
  - `dossier_markdown` (the appendix)
- `agents/report_generation_agent.py` takes the dossier, sections, title and subject; the facts are ground truth.
- Routes `/reports/catalog`, `/subjects/{kind}`, `/dossier`, `/from-record`, `/for-record`.
- Migration 126 adds subject columns to `placeware_report_memory`.

**Why:** reports generated from "everything" hallucinate and wander. Reports about one record, with its facts shown for review first, are accurate and auditable.

**RoyanHealth:** this carries over directly for:
- incident reports
- audit reports
- recall reports
- patient-account statements
- monthly department reports

Clinical documents (discharge summaries, referral letters) follow the same sequence, with the encounter as the record. They still need clinician sign-off.

---

## 13. ACE, the assistant across all modules

ACE is the conversational layer over everything above. Full detail is in `backend/docs/ACe guide/06_ACE_Synbot_Standards_Applied.md`. What matters for replication:

- **ACE knows the app.** `services/app_guide.py` holds:
  - the sidebar map with roles
  - a feature index of every page, tab and button, generated by scanning the screens
  - synonyms (lend = loan = borrow)
  - the 11 end-to-end workflows
  - live settings (alert rules, escalation chains, compliance score, reorder policy)

  It must be updated whenever screens change.
- **ACE reads live data through the same hub services,** via 11 narrow tools (`services/ace_tools.py`):
  - executive overview
  - cash
  - customer account
  - supplier account
  - product stock
  - quality status
  - stock orders
  - stock loans
  - pipeline
  - team
  - my work

  They are gated by the same roles as the screens.
- **Every lookup comes back with a status:** ok, not found, ambiguous, denied, or unavailable. So ACE says "outside your access" or "I couldn't find it" instead of "none".
- **Voice:** answer first, plain text, length chosen by need, no AI filler (`services/ace_voice.py`).
- **Questions never trigger actions.** Actions from chat are read-before-write; reorders are read-only and point to the page.
- **Quality gate:** `backend/eval/ace_eval.py`, 38 cases with severities; the release gate requires no critical or high failures. A trace record is written per turn.

**RoyanHealth:** reuse the core, voice, evidence and eval unchanged. Replace `app_guide.py` and `ace_tools.py` with hospital equivalents (patient lookup, queue, bill, drug stock, ward occupancy). Add clinical safety rules: recorded facts only, and no diagnosis.

---

## 14. How the whole system connects

### 14.1 Who owns what, and who reads it

| Fact | Owner (writes) | Readers |
|---|---|---|
| Invoices, receipts, bills, payments, cash, stock value, lots | ACE Books | Executive, CRM (sales, balance, "what they buy"), Inventory, Frontdesk, Suppliers, ACE |
| Batch status, recalls, deviations, audits, maintenance | Inventory & Quality | ACE Books (lot status), Calendar, Executive, My Day, ACE |
| Stock orders, reorder plan, suppliers | Operations | Calendar (deliveries), My Day, Executive, ACE |
| Customers, deals, reminders, credit limit | CRM | ACE Books (credit limit at invoicing), Frontdesk, Executive, My Day, ACE |
| Walk-ins and requests | Frontdesk | QC / finance queues, ACE Books (on approval), Logistics |
| Logins and roles | User Access | everything (sidebar, APIs, ACE tools), HR (profile auto-created) |
| Clock, tasks, requests, messages | My Workspace | HR (hours, timesheets), Executive (people & work), ACE |

### 14.2 The four chains

```
ORDER TO CASH   Frontdesk walk-in -> QC -> Finance approves -> invoice posts (ACE Books, credit limit)
                -> dispatch (Logistics) -> receipt (ACE Books) -> CRM deal auto-won, receivables drop

PROCURE TO PAY  Reorder plan -> stock order (request -> approve -> ordered) -> incoming batch (QC register)
                -> supplier bill in ACE Books (receives stock, closes the order) -> QC release -> pay supplier

BATCH LIFE      registered -> QUARANTINED -> released (sellable, FIFO) | rejected (+ deviation)
                -> expiry watch (My Day, Expiry tab) -> write-off | recall (frozen, buyers traced, returns)

PEOPLE          User Access login -> HR profile -> My Workspace clock -> timesheet -> HR approval
                -> Executive people panel; overdue work -> escalation chain
```

### 14.3 The glue, in code

| Mechanism | Where |
|---|---|
| Hub services that call each other, never each other's tables | `services/*_hub.py`, `stock_orders.py`, `executive.py` |
| Finance read model and shared views | `src/fin/readmodel.py`, `services/books_analytics.py`, views `v_sales_lines`, `v_customer_invoices`, `v_ar_open`, `v_customer_sales_summary`, `v_gl_monthly` (migration 120) |
| Operational signals into people's day | `staff_workspace.RULES` → My Day "For your role" → tasks close themselves |
| Realtime | `realtime_hub.broadcast("<module>_updates")` → `useRealtimeChannel` invalidates queries |
| Calendar over records | `quality_hub.calendar_feed` / `reschedule` |
| Reports about records | `report_subjects.dossier` |
| Names everywhere | `services/people.py` resolves user and staff ids to names (never show a UUID) |
| Roles | `roles.py` (server), `Sidebar.visibleNav` + `ProtectedRoute` (client), tool role sets (ACE) |
| Audit | `audit_event()` on every mutation; reason required for access changes, overrides and voids |

---

## 15. Backend patterns to copy

- **One service module per area,** with pure functions (`overview`, `directory`, `profile`, actions). The router is thin: auth, role check, call the service.
- **Raw SQL helpers** (`q`, `q1`, `ex`, `tx` in `src/fin/db.py`), one transaction per request. Cheap overview calls are cached 60 s–5 min (executive 5 min, with `?refresh=true`).
- **Numbered SQL migrations** (`backend/migrations/1xx_*.sql`), applied with `psql -v ON_ERROR_STOP=1`. Add columns; don't rewrite tables. Archive junk rather than delete it.
- **Status enums with CHECK constraints,** kept identical to the Python constants. A mismatch here caused real 500s; see the Workspace Standard §9.10.
- **Server-side time.** Clocks, due times and overdue are computed on the server in the business time zone (Africa/Lagos).
- **nginx** proxies an explicit list of API prefixes. Every new top-level router prefix must be added to `SynbotUI/nginx.conf`.
- **Deploy:** images bake in the source, so rebuild with `docker compose build backend frontend && docker compose up -d backend frontend`.

**Testing per module:**
- A flow script exercises the real routers inside one transaction and then rolls back: `workspace_flow.py` (48 checks), `crm_flow.py` (29), `quality_flow.py` (27), `stock_order_flow.py`, `automation_flow.py` (37), `roles_test.py` (19), `cards_scan.py` (44 card values against the database).
- A Playwright pass screenshots every page per role.
- The ACE eval.

---

## 16. Build order for RoyanHealth

The order below is the one that worked. Each step gives the next one real data to show.

1. **Roles and User Access:** a role catalogue file, multi-role users, a `visibleNav` preview, and an automatic HR profile on user creation.
2. **The ledger:** billing and accounts, the source of every money figure. Build its read model and views before any dashboard.
3. **The stock and lot model** with statuses (available, quarantined, recalled) and FIFO issue, owned by the ledger.
4. **Reception (the entry point)** with the role-step chain and realtime queues.
5. **Quality and Pharmacy/Stores** on the same lot status: release, expiry, recalls, incidents, audits, maintenance.
6. **Procurement:** the reorder plan, orders received by the supplier bill, suppliers.
7. **Patient Relations / Accounts** (the CRM equivalent), reading the ledger.
8. **My Workspace + HR:** clock, tasks, requests, messages, the `RULES` table with hospital signals, escalation.
9. **Calendar** over the records.
10. **Executive overview**, composed only from the hub services.
11. **Reports:** the four-step sequence, with a dossier per record kind.
12. **ACE:** app guide, live tools on the hub services, eval set.

**Definition of done for each module:**
- Overview cards show real numbers with as-of dates.
- Every card links to its fix.
- The module's hub service is used by the executive overview and by ACE.
- A rolled-back flow test passes.
- The app guide is updated.
- There is no duplicate entry point for the same fact.

---

## 17. Lessons (what went wrong and what to avoid)

- **Fake trend badges and sparklines erode trust faster than empty cards.** Remove them; show one real current value.
- **Legacy data is not always what its name says.** The "purchase orders" were supplier invoices; the old stock view counted every item twice.
- **Watch the ID fields.** The login ID sent as `staff_id` broke clock-out. Link the profile to the login (`user_id`) and resolve names on the server.
- **Keep the same rules in the same order across layers.** "Overdue" used two definitions (table row vs. KPI card), and a status was allowed in Python but blocked by a DB constraint. Define each rule once, on the server.
- **An unauthenticated or wrong-shape endpoint can go unnoticed for months.** Examples: `/calendar` with no auth, and KPI cards reading `data.kpi` that didn't exist. Live flow tests catch these.
- **Frontend prewarm calls must be role-aware.** Otherwise every page load fires 403s and LLM cost.
- **Don't edit source files through PowerShell 5 `Get-Content`/`Set-Content`.** It corrupts non-ASCII characters.
- **Check keyword matching boundaries.** A chat planner keyword "ar" matched every "are".
- **A question is not a command.** Chat must never turn "what do we need to reorder?" into a database write.
