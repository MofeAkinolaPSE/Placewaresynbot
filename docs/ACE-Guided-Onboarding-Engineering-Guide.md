# ACE: Welcome Tour and "Show me how"

**Engineering guide for building guided onboarding into Placeware ACE**

| | |
|---|---|
| **Audience** | Engineers joining the ACE team who will build or maintain in-app training. |
| **Scope** | `SynbotUI` (React / TypeScript) and `backend` (FastAPI). |
| **Reference implementation** | The same two features already run in the sister product (RoyanSynbot). Section 12 lists its files to copy from. |
| **Status** | Built 28 Oct 2026. Section 15 records what was built and where it differs from this specification. |

ACE gets two connected training features:

| Feature | Question it answers for a Placeware employee | When it runs |
|---|---|---|
| **Welcome tour** ("your day in ACE") | *What does my working day look like in ACE?* For example, Frontdesk starts with Today's queue; QC starts with My Day and the Release queue; finance with ACE Books. | Once, on first sign-in. Replay from the user menu. |
| **Show me how** (walkthroughs) | *How do I take one customer order, one batch or one recall through my part of ACE?* | On demand, from a button on the page it teaches. |

---

## 1. Principles

1. **Teach the job, not the menu.**
   - The tour follows a role's working day.
   - A walkthrough follows **one record** (a walk-in customer's order, an incoming batch, a stock order, a recall) through a department, and ends with the hand-off: "QC now has it", "Finance approves it next", "the rider delivers it".
2. **Train on the real screen.** Steps run over the live ACE pages.
3. **Never let training change real data.** In ACE this matters more than usual:
   - Most actions post to **ACE Books** the moment they happen: Finance approve, post invoice, record receipt, post bill.
   - **Every screen updates live for everyone**: QC queues, Today's queue, the Invoice register.
   - A training click on Approve would post a real invoice and show up on colleagues' screens immediately.

   Committing controls are therefore always **"Look, do not press"** (section 7).
4. **Learn by doing** where it is safe: opening a tab, a search box, a panel, a drop-down.
5. **Content is data, checked by tests.**
6. **One source of truth for access.** Training uses the same role rules as the sidebar and `ROLE_CATALOG`.
7. **Three sources stay in step.** Ask ACE's `APP_GUIDE` (`backend/src/services/app_guide.py`), the tour scripts and the walkthroughs describe the same flows with the same button names. When one changes, update the other two.

---

## 2. What ACE already has (and what to reuse)

| Existing piece | Where | Use it for |
|---|---|---|
| Sidebar menu definition `NAV_DEFINED` → `NAV_ITEMS` (folders A–Z, My Workspace first) | `SynbotUI/client/components/Sidebar.tsx` | Source of pages and their `roles`. **Move it into `client/lib/nav-items.ts`** (section 4.1). |
| `canView(allowed)` (inline in Sidebar) and `visibleNav(roles)` | `Sidebar.tsx` | Extract into `client/lib/nav-access.ts` so the tour, route guard and User Access preview share one rule. |
| User Access menu preview (`RolePicker`) | `client/components/admin/RolePicker.tsx` | Add "Preview onboarding" for a role (section 4.6). |
| Role catalogue: `frontdesk`, `sales`, `finance`, `ops`, `procurement`, `quality_assurance`, `hr`, `management`, `admin`, `viewer` (legacy aliases: `qa`, `operations`, `manager`) | `backend/src/roles.py` | One day script per role. Aliases map to the main role. |
| Ask ACE knowledge: `APP_GUIDE` (sidebar map, feature index, *How work flows through the system*, *What each role does day to day*) | `backend/src/services/app_guide.py` | **Content source** for the scripts. Keep the three in step. |
| Staff profile table `placeware_staff` (keyed by email) | migrations `000`, `007` | Holds `tour_state` (section 4.2). |
| Live updates (realtime hub) | backend `services/realtime.py` | Why committing clicks are dangerous: colleagues see them at once. |
| My Workspace → My Day → "For your role" | `/workspace` | The first step for most roles: where their work arrives. |

---

## 3. Architecture in ACE

```text
client/lib/nav-items.ts      (NAV_ITEMS, moved out of Sidebar.tsx)
client/lib/nav-access.ts     canView(roles, allowed) · resolveRouteRoles(path) · visibleNav(roles)
        │            used by Sidebar, ProtectedRoute, RolePicker preview, tour, Show me how
        ▼
client/lib/day-tours.ts      role -> DayStep[]       (welcome tour scripts)
client/lib/walkthroughs.ts   id   -> Walkthrough    (Show me how journeys)
        │
client/components/tour/
  TourProvider.tsx       first sign-in + replay; floating card; opens each step's page
  TourStep.tsx           the card's content (progress, page name, checklist)
  WalkthroughProvider.tsx  active walkthrough, step, minimised
  WalkthroughPlayer.tsx  spotlight, step card, click-to-advance, caution states (portal on <body>)
  ShowMeHow.tsx          the button on each page
  TourPreview.tsx        "Preview onboarding as <role>" on User Access
        │
backend
  migrations/147_staff_tour_state.sql   placeware_staff.tour_state jsonb
  routers/staff_me.py (new)             GET /staff/me (profile + tour_state), PATCH /staff/me/tour
```

---

## 4. Build steps in ACE

### 4.1 Move the menu into one shared module

`Sidebar.tsx` defines `NAV_DEFINED` and a private `canView`. Move both:

- `client/lib/nav-items.ts`:
  - `NAV_DEFINED`
  - `NAV_ITEMS` (sorted A–Z, My Workspace first)
  - `NavItem` and `NavChild` types
  - a `tourDescription?` field on items, used as the fallback when a role has no day script
- `client/lib/nav-access.ts`:
  - `canView(roles, allowed)`
  - `visibleNav(roles)`
  - `resolveRouteRoles(path)`: finds the longest matching `href` and returns its roles, so detail pages inherit their section's roles.

ACE links carry query strings, for example `/maintain?tab=items` and `/finance/books/sales?tab=register`. **Compare paths without the query string** when resolving access, but keep the query for navigation. The tour and walkthroughs rely on these deep links to open the right tab.

`Sidebar.tsx` then imports these. `ProtectedRoute` should use `resolveRouteRoles` too, so the menu and the route guard can never disagree.

### 4.2 Store tour progress (backend)

```sql
-- migrations/147_staff_tour_state.sql
ALTER TABLE placeware_staff ADD COLUMN IF NOT EXISTS tour_state jsonb;
-- {"completed": bool, "skipped": bool, "current_step": int}
```

Add a new router `routers/staff_me.py`, authenticated with the existing JWT dependency:

- `GET /staff/me` returns `{ profile, tour_state }`, looked up by the login's email (the `placeware_staff.email` key). If no row exists, create one; User Access normally creates it.
- `PATCH /staff/me/tour` merges the posted fields into `tour_state`. Only the caller's own row; never take a user id from the request body.

Add `/staff` to nginx's proxied API prefixes if it isn't already (ACE routes the API by explicit prefixes).

### 4.3 Start the tour (frontend)

In `Layout.tsx`, after authentication:

```ts
const me = await api.staff.getMe();
if (!me.tour_state?.completed && !me.tour_state?.skipped) startTourIfNeeded(primaryTourRole(roles), me.tour_state);
```

- Start it for **every** account. All ACE logins are created on User Access, so do not tie it to a profile-setup form. (The sister product made that mistake, and admin-created staff never saw the tour.)
- Add **"Take the tour again"** to the sidebar's user menu (the `MoreVertical` dropdown, next to Settings / Dark mode / Sign out). A replay never writes `tour_state`.

### 4.4 Role priority (people with several roles)

```ts
// most senior / broadest first; aliases fold into their main role
const ALIAS = { qa: "quality_assurance", operations: "ops", manager: "management" };
export const TOUR_ROLE_PRIORITY = ["admin", "management", "finance", "quality_assurance", "ops", "procurement",
                                   "sales", "frontdesk", "hr", "viewer"];
export function primaryTourRole(roles: string[]) {
  const have = new Set(roles.map((r) => ALIAS[r] ?? r));
  return TOUR_ROLE_PRIORITY.find((r) => have.has(r)) ?? "viewer";
}
```

Never use `roles[0]`. Its order is arbitrary. (`Sidebar.tsx` currently uses `roles[0]` for the avatar initials; that is harmless there, but don't copy it.)

### 4.5 Show me how on every page that has a walkthrough

Place `<ShowMeHow only={[...]}/>` next to the page title. Offer every walkthrough that **any** of the person's roles may use (role aliases folded).

### 4.6 Preview on User Access

On `AdminUsers` / `RolePicker`, add **Preview onboarding**: choose a role, then start that role's tour or list its walkthroughs. Admins can then check each role without creating test logins.

---

## 5. Data model

```ts
export type DayStep = {
  title: string;      // "Release incoming batches"
  href: string;       // "/quality-control"  (query allowed: "/finance/books/sales?tab=register")
  body: string;       // when in the day and why, 1–2 sentences
  points?: string[];  // what to press, exact on-screen names
};

export type WalkthroughStep = {
  title: string; body: string;
  anchor?: string;               // data-tour-id
  navigateTo?: string;           // route (journeys cross pages)
  action?: "click" | "observe";  // click = advances when pressed
  caution?: boolean;             // commits to ACE Books / a live queue: amber, never clickable
  cue?: string;
};

export type Walkthrough = {
  id: string; title: string; summary: string;
  roles?: string[]; homeRoute?: string; estMinutes: number;
  steps: WalkthroughStep[];
};
```

Anchors are attributes on real elements, for example `data-tour-id="frontdesk-new-walkin-tab"`. To mark a component you cannot edit, wrap it in a `<div>` that carries the attribute.

---

## 6. Welcome tour content: a day per ACE role

Each script follows the role's real day. The route and button names come from `APP_GUIDE`. Most roles end with the shared step **"Help is always one click away"**: Ask ACE, Show me how, and Take the tour again.

### Frontdesk (`frontdesk`)
1. **Start of day: Today's queue** (`/frontdesk`). Cards: Walk-ins Today, Invoices Raised, Revenue Today, Pending QC, Pending Finance, Completed. The queue updates by itself.
2. **Register a walk-in** (`/frontdesk`, New walk-in tab).
   - *Register Walk-in Client*, then the items: Product, Qty, Unit price, Batch number, Manufacture and Expiry dates (filled from Maintain).
   - Then Delivery charge (₦) and Discount allowed (₦).
   - Then the invoice details: Bill to, Ship to, Customer PO, Payment terms, Ship via.
   - Finish with *Create Invoice & Send for QC*.
3. **Check stock before promising** (`/frontdesk`). Use the stock check; the stock on a Frontdesk invoice is held so it is not sold twice.
4. **Follow the order: QC → Finance → Dispatch** (`/frontdesk`). Each step is done by its own role. Open a visit to see its stage; *Print invoice* is on the panel.
5. **Change or void before Finance approves** (`/frontdesk/invoices`).
   - *Modify invoice* (with a reason): if QC had already checked it, it goes back to QC.
   - *Void invoice*: possible until Finance approves; after that, Finance voids it.
6. **Returning customers** (`/frontdesk`). Search, then use the client history.
7. **End of day** (`/frontdesk`, Reports tab). *Activity report*.
8. **Your workspace** (`/workspace`). Start work / End work; Task, Ask, Message.

### Sales (`sales`)
1. **Your customers** (`/crm/customers`). Filters: Buying, At risk, Due to reorder, Owes past due, Lapsing, Lapsed, Never bought. Click a customer for their panel.
2. **A customer's full picture** (`/crm/customers`). Panel tabs: Sales, What they buy, Invoices, Account; buttons: Log call/visit, Reminder, New deal, New request.
3. **Raise an order for a customer** (`/customers/workspace`). *Make new request*. It follows the same QC → Finance → Dispatch route as a walk-in.
4. **Work the pipeline** (`/crm/sales`). New → Qualified → Proposal → Won/Lost. A deal is marked Won automatically when the customer's invoice posts.
5. **Find new customers** (`/crm/lead-finder`). Find (GPS or area) → call → *Add to pipeline*.
6. **Weekly report and targets** (`/crm/sales`, Weekly report and Targets tabs).
7. Walk-ins (`/frontdesk`), then your workspace.

### Finance (`finance`)
1. **Finance Control Tower** (`/finance/books`). Revenue and profit, cash, ageing, Needs attention. Note "Live since <hand-over date>".
2. **Approve Frontdesk invoices** (`/frontdesk`, Pending Finance). *Approve* posts the invoice to ACE Books: goods to sales, delivery charge to Other Income 40800, discount to 49000. A customer over their credit limit is blocked until you override with a reason.
3. **Invoice register** (`/finance/books/sales?tab=register`). Every invoice, Sage's included. Use *Add items* or *Return / remove items* on an invoice; *Void* only while it is unpaid.
4. **Record a customer receipt** (`/finance/books/sales`). *Record customer receipt*: Full or Part payment, and the WHT drop-down (2/3/5/10%).
5. **Supplier bills and payments** (`/finance/books/purchases`).
   - "Received, waiting on the supplier's bill" → *Record the bill* (lines filled) → *Post bill*.
   - *Pay supplier*.
6. **Chase overdue customers** (`/finance/ar`). AR Aging, Alert Rules, Credit Risk. Credit limits are set on CRM → Customers → Edit.
7. **Banking** (`/finance/books/banking`). Accounts, Vouchers, Reconciliation.
8. **Month end** (`/finance/books/close`). Integrity monitor, Data issues, Frontdesk postings, Periods.
9. **Sage hand-over** (`/finance/sage-import`). *Bring ACE up to date from Sage* → Check → confirm.
10. **Executive Overview** (`/executive`).

### Quality (`quality_assurance`, alias `qa`)
1. **Your day starts in My Day** (`/workspace`). "For your role": batches to release, deviations, audits, maintenance, recalls, expired stock. *Take it*.
2. **QC check of Frontdesk invoices** (`/quality-control`, Release queue). *Pass QC* or *Fail QC*. You sign with your own login. The person who raised an invoice cannot QC it.
3. **Incoming batches** (`/quality-control`, Release). *Confirm arrived* (supplier, invoice number, quantity, cost, batch on the pack, dates); the batch is QUARANTINED. Then *Release* (makes it sellable) or *Reject* (stays held and raises a deviation).
4. **Expiry** (`/quality-control`, Expiry tab). Quarantine, release, write off or recall a lot. Expired lots can never be sold.
5. **Recalls** (`/quality-control`, Recalls tab). From a customer's invoice, or from a batch: the batch is frozen and its buyers traced. Record returns, then close the recall.
6. **Temperature** (`/quality-control`, Temperature tab). New temperature reading.
7. **Compliance & QMS** (`/compliance`). Audits, Deviations & CAPA, Maintenance, SOPs, Documents. Compliance score = 100 minus the overdue deductions.
8. **Logistics Calendar** (`/calendar`). Everything due; drag to reschedule.

### Operations (`ops`, alias `operations`)
1. **Operations overview** (`/operations`). Inventory, Logistics, Procurement (import shipments: at port → clearance → released → delivered).
2. **Stock orders** (`/operations/purchase-orders`). Reorder plan, then Stock orders: requested → approved → ordered → received (received when the supplier bill posts).
3. **Deliveries and riders** (`/operations/logistics`). Deliveries (*New delivery*, assign a rider), Riders, Live map. Customers get a tracking link; riders use `/rider`.
4. **Project controls** (`/operations/project-controls`).
5. **Suppliers** (`/operations/suppliers`).
6. **Stock and compliance scheduling** (`/inventory`, `/compliance`, `/calendar`).

### Procurement (`procurement`)
1. **Reorder plan** (`/operations/purchase-orders`, Reorder plan tab). Needs ordering, order soon, expiry risk.
2. **Raise, approve and order** (Stock orders tab). Mark it ordered with the supplier and the expected date.
3. **Register the incoming batch for QC** when it must be checked. Finance records the bill when the goods arrive.
4. **Suppliers** (`/operations/suppliers`). What we owe, buy and how often.
5. **Stock levels** (`/inventory`). *Request reorder*.

### HR (`hr`)
1. **Who is in** (`/hr`, Overview).
2. **Staff directory** (`/hr`). Profiles of everyone created on User Access.
3. **Timesheets** (`/hr`). Approve, reject, adjust, add hours, export CSV.
4. **Escalation rules** (`/workspace`, Customise).

### Management (`management`): the whole company
1. **Executive Overview** (`/executive`). Revenue and profit, cash, ageing, stock, sales trend, customers, quality, people, and the Needs your attention list.
2. **How an order becomes cash**: Frontdesk (`/frontdesk`) → QC → Finance → Dispatch → receipt.
3. **The books** (`/finance/books`).
4. **Who owes us** (`/finance/ar`).
5. **Customers and sales** (`/crm`).
6. **Stock and quality** (`/quality`). Compliance score, recalls, expiry.
7. **Buying stock** (`/operations/purchase-orders`).
8. **Deliveries** (`/operations/logistics`).
9. **People** (`/hr`).
10. **What is due** (`/calendar`).
11. **Reports** (`/reports/new`).
12. **Ask ACE** (`/synbot`) and the **Agent Stack** (`/agents`).

### Admin (`admin`)
The management tour, then:
- **User Access** (`/admin/users`): Create User, tick roles (the preview shows their menus), Edit access, Deactivate.
- **Workflow** (`/workflow`).
- **Data Intelligence** (`/admin/data-intelligence`).
- **Settings and Data Backup** (`/settings`).

### Viewer (`viewer`)
Your workspace, the Dashboard, and Help.

---

## 7. Safety: what training must never press in ACE

Mark these `caution: true, action: "observe"`. The amber card says "Look, do not press".

| Area | Committing controls |
|---|---|
| Frontdesk | *Register Walk-in Client*, *Create Invoice & Send for QC*, *Modify invoice* (save), *Void invoice*, dispatch (send for delivery) |
| QC | *Pass QC* / *Fail QC*, *Confirm arrived*, *Release* / *Reject* (batch), open or close a recall, write off, *New temperature reading* (save) |
| Finance | Frontdesk *Approve* / *Reject*, *Post invoice* / *Post & print*, *Record customer receipt*, *Void* (any document), *Correct this receipt*, *Record the bill* / *Post bill*, *Pay supplier*, *Approve & post* (adjustment), *Post variances*, *Lend stock* → Post loan, Close period, Sage *Check* → confirm |
| Operations / Procurement | Approve stock order, mark ordered, *New delivery*, assign rider |
| CRM | *Make new request* / *Raise Request*, mark deal won/lost, *Message customers* (bulk) |
| Admin | *Create User*, *Save access*, *Deactivate*, *Delete*, *Back up now* |

ACE-specific reasons to be strict:
- **Postings are real.** Approving or posting writes journals in ACE Books, and stock leaves batches FIFO.
- **Separation of duties.** QC and Finance sign with their own login, and the person who raised an invoice cannot QC it. A walkthrough must explain these rules, never act them out.
- **Everyone sees it live.** A training click lands in colleagues' queues at once.

Safe to make clickable: tabs, search boxes, filters, opening a customer, invoice or batch panel, drop-downs that only open, *Print* (it only previews), CSV export.

---

## 8. Show me how catalogue for ACE

Each walkthrough follows one record. Every committing step is `caution`. Anchor ids are proposals; add them to the elements named.

| id | Title | Roles | Home page | Pages crossed |
|---|---|---|---|---|
| `journey-order-to-cash` | Follow one customer order through ACE | management, admin | `/executive` | frontdesk → quality-control → frontdesk (finance) → operations/logistics → finance/books/sales → finance/ar |
| `frontdesk-walkin` | Serving a walk-in customer | frontdesk, sales, admin, management | `/frontdesk` | frontdesk |
| `qc-invoice-check` | QC-checking an order | quality_assurance, admin, management | `/quality-control` | quality-control |
| `qc-batch-release` | Receiving and releasing an incoming batch | quality_assurance, procurement, admin | `/quality-control` | quality-control → finance/books/purchases |
| `finance-approve-post` | Approving an order and getting paid | finance, admin, management | `/frontdesk` | frontdesk → finance/books/sales → finance/ar |
| `procure-to-pay` | Buying stock, from reorder to paying the supplier | procurement, ops, finance, admin | `/operations/purchase-orders` | purchase-orders → quality-control → finance/books/purchases |
| `dispatch-delivery` | Dispatching and tracking a delivery | ops, finance, admin | `/operations/logistics` | frontdesk → operations/logistics |
| `recall` | Running a recall | quality_assurance, admin, management | `/quality-control` | quality-control → compliance → reports/new |
| `crm-request` | From a customer conversation to an order | sales, admin, management | `/crm/customers` | crm/customers → customers/workspace → crm/sales |
| `invoice-change` | Changing an invoice after it is raised | frontdesk, finance, admin | `/frontdesk/invoices` | frontdesk/invoices → finance/books/sales?tab=register |
| `month-end` | Closing a month | finance, admin | `/finance/books/close` | banking → close |
| `new-team-member` | Bringing a new person on board | admin, hr | `/admin/users` | admin/users → hr |

### 8.1 Worked example: `frontdesk-walkin` ("Serving a walk-in customer")

| # | Title | Page / anchor | Action |
|---|---|---|---|
| 1 | A customer walks in: open New walk-in | `/frontdesk` · `frontdesk-new-walkin-tab` | click ("Click New walk-in") |
| 2 | Register them | `frontdesk-walkin-form` (customer details). Body: search first; returning customers have history. | observe |
| 3 | Add the items | `frontdesk-items`. Body: Product, Qty, Unit price; batch number and dates fill from Maintain. Check stock before promising. | observe |
| 4 | Delivery charge and discount | `frontdesk-charges`. Body: delivery goes to Other Income, discount to Discount allowed. The total is goods − discount + delivery. | observe |
| 5 | Invoice details | `frontdesk-invoice-details`. Body: Bill to, Ship to, Customer PO, Payment terms, Ship via. | observe |
| 6 | Create Invoice & Send for QC | `frontdesk-create-invoice` | **caution** |
| 7 | What happens next | text only. Body: the stock is held; QC checks it (not you: whoever raised it can't QC it); then Finance approves and it posts to ACE Books; then dispatch. | — |
| 8 | Follow it in Today's queue | `frontdesk-queue-tab` | click |
| 9 | Print for the customer | `frontdesk-print-invoice`. Body: Prepared by is printed; Received by is left blank for whoever collects. | observe |

### 8.2 Worked example: `qc-batch-release`

| # | Title | Page / anchor | Action |
|---|---|---|---|
| 1 | Open the Release queue | `/quality-control` · `qc-release-tab` | click |
| 2 | Goods have arrived: Confirm arrived | `qc-confirm-arrived`. Body: supplier, their invoice number, quantity, unit cost, batch number on the pack, manufacture and expiry dates. | **caution** |
| 3 | The batch is held | text. Body: QUARANTINED; the books record goods received, with the bill to come. | — |
| 4 | Check it, then Release or Reject | `qc-release-actions`. Body: Release makes it sellable (oldest unexpired first); Reject keeps it held and raises a deviation. | **caution** |
| 5 | Finance records the bill | `navigateTo /finance/books/purchases` · `books-bills-waiting`. Body: "Received, waiting on the supplier's bill" → Record the bill → Post bill. | observe |
| 6 | Write it up | text. Body: *Report* on a decided batch opens Reports at the review step. | — |

### 8.3 Worked example: `journey-order-to-cash` (management)

| # | Page | What the step shows |
|---|---|---|
| 1 | `/frontdesk` · `frontdesk-queue-tab` (click) | A walk-in becomes an invoice; its stock is held. |
| 2 | `/quality-control` · `qc-release-tab` (observe) | QC passes or fails it, signed with their own login. |
| 3 | `/frontdesk` · `frontdesk-pending-finance` (observe) | Finance approves it: the invoice posts to ACE Books, or is blocked by the credit limit. |
| 4 | `/operations/logistics` · `logistics-deliveries-tab` (observe) | A delivery is created, a rider is assigned, and the customer tracks it. |
| 5 | `/finance/books/sales?tab=register` · `books-invoice-register` (observe) | The invoice in the register; *Record customer receipt* with WHT. |
| 6 | `/finance/ar` · `ar-aging` (observe) | It leaves Aged receivables when paid; overdue customers trigger alert rules. |
| 7 | `/executive` (text) | The day's revenue, cash and attention list. |

Write the other walkthroughs in the catalogue the same way, from `APP_GUIDE`'s *How work flows through the system* (items 1–11) and *How to*.

---

## 9. Anchors to add in ACE

| Page / component | `data-tour-id` | Element |
|---|---|---|
| `pages/Frontdesk.tsx` | `frontdesk-queue-tab`, `frontdesk-new-walkin-tab`, `frontdesk-invoices-tab` | the Today's queue, New walk-in and All invoices tab triggers |
| `pages/Frontdesk.tsx` | `frontdesk-walkin-form`, `frontdesk-items`, `frontdesk-charges`, `frontdesk-invoice-details` | the form sections |
| `pages/Frontdesk.tsx` | `frontdesk-create-invoice`, `frontdesk-pending-finance` | the *Create Invoice & Send for QC* button; the Pending Finance card |
| `components/frontdesk/*` | `frontdesk-print-invoice`, `frontdesk-modify-invoice`, `frontdesk-void-invoice`, `frontdesk-dispatch` | invoice panel buttons (confirm the dispatch button's label) |
| `pages/QualityControl.tsx` | `qc-release-tab`, `qc-expiry-tab`, `qc-recalls-tab`, `qc-temperature-tab` | tab triggers |
| `pages/QualityControl.tsx` | `qc-confirm-arrived`, `qc-release-actions`, `qc-pass-fail` | buttons |
| `pages/PurchaseOrders.tsx` | `po-reorder-plan-tab`, `po-orders-tab`, `po-raise-order` | tabs / button |
| `pages/LogisticsMonitor.tsx` | `logistics-deliveries-tab`, `logistics-riders-tab`, `logistics-livemap-tab`, `logistics-new-delivery` | tabs / button |
| `pages/books/BooksSales.tsx` | `books-invoice-register`, `books-record-receipt`, `books-new-invoice` | tab / buttons |
| `pages/books/BooksPurchases.tsx` | `books-bills-waiting`, `books-pay-supplier` | list / button |
| `pages/FinanceAR.tsx` | `ar-aging`, `ar-alert-rules-tab` | table / tab |
| `pages/CRMCustomers.tsx`, `CustomerWorkspace.tsx` | `crm-customer-filters`, `crm-customer-panel`, `crm-new-request` | filters / panel / button |
| `pages/books/BooksClose.tsx` | `close-periods-tab`, `close-data-issues-tab` | tabs |

---

## 10. Player and card behaviour (copy from the reference implementation)

### Welcome tour card
- A **floating card** in the bottom-right, not a modal, so the ACE page stays visible and usable.
- Each step **navigates to its `href`**, including `?tab=`.
- The card shows:
  - a progress bar;
  - "Step 3 of 9 · *Page name*" (the menu label);
  - the title, the body, and `points` as a checklist;
  - Skip / Back / Next / Finish.
- The content scrolls inside the card (cap at about 55% of the viewport height).
- `role="dialog"`, `aria-modal="false"`, and a labelled close button.

### Walkthrough player
- **Spotlight:** four dimmed panels around the target, with `pointer-events: none`, so the target is never covered and the page stays usable.
- **Ring and pulse:** the pulse stays in place (opacity or shadow). **Do not scale it** with a "ping" animation: on wide ACE tables it draws an oversized box offset from the target.
- **Card:** about 420px wide, placed beside the target.
  - **Header (one line):** "*walkthrough* · step 2 of 7", with the name truncated. The line opens the step list.
  - **Body:** 14px text.
  - **Cue box:** blue for a click step (with "show me"), amber for caution ("Look, do not press."), neutral for observe.
  - **Missing target:** "That control is not on screen right now — open the tab or screen it lives on."
  - **Footer:** the note "You are on the real page: safe clicks only — nothing is saved unless you save it" (wraps), then Back and Next/Skip/Done (these never shrink).
- **Click steps** attach a one-time listener to the anchor and advance on press. Next reads **Skip** on these steps.
- **`navigateTo`** navigates once per step, then re-measures the target on scroll and resize.

---

## 11. Tests (vitest, `SynbotUI/client/lib/*.spec.ts`)

| Test | Catches |
|---|---|
| Every walkthrough `anchor` exists as `data-tour-id="…"` in `client/` | Highlights pointing at nothing after a UI change. |
| Every `homeRoute` / `navigateTo` (query stripped) is a `<Route path>` in `App.tsx` | Dead buttons or navigation. |
| Every role in `ROLE_CATALOG` (mirror the keys in the spec) has a day script | New roles with no tour. |
| Every day step's page is viewable by that role (`resolveRouteRoles`, query stripped) | A tour bouncing people off ACE Books or Quality pages. |
| `getTourStepsForRole(role)` returns the day script | Silent fallback to the page list. |
| `caution` steps are never `click`; the anchors in section 7's table are `caution` | Inviting a trainee to post, approve or void. |
| Every `click` step has an anchor and a cue; every anchored walkthrough has at least one click step | Unfinishable steps; slideshows. |
| Required phrases are present, e.g. "the person who raised an invoice cannot QC it", "posts to ACE Books", "expired lots can never be sold" | A rewrite dropping a rule. |
| `primaryTourRole(["frontdesk","management"]) === "management"`; `qa` → the `quality_assurance` day | Wrong tour for multi-role and alias accounts. |
| Steps have a title over 5 characters and a body over 30 | One-word placeholders. |

---

## 12. Reference implementation (RoyanSynbot) to copy from

| File | What to take |
|---|---|
| `SynbotUI/client/lib/day-tours.ts` | DayStep type, shared steps, `primaryTourRole`, the script layout |
| `SynbotUI/client/lib/tour-config.ts` | `getTourStepsForRole` (day script first, access filter, nav fallback) |
| `SynbotUI/client/components/tour/TourProvider.tsx` and `TourStep.tsx` | Floating card, navigation per step, persistence and replay |
| `SynbotUI/client/lib/walkthroughs.ts` | Walkthrough types, the journey format, `getWalkthroughsForRoles` |
| `SynbotUI/client/components/tour/WalkthroughPlayer.tsx`, `WalkthroughProvider.tsx` and `ShowMeHow.tsx` | Spotlight, click-to-advance, caution states, fixed layout |
| `SynbotUI/client/lib/day-tours.spec.ts` and `walkthroughs.spec.ts` | The test suite |
| `SynbotUI/client/components/Layout.tsx` | Starting the tour on first sign-in for every account |

Swap Royan's content (patients, wards, HMO) for ACE's (orders, batches, recalls, ACE Books). The mechanics carry over unchanged.

---

## 13. Pitfalls (seen in the sister product, plus ACE-specific ones)

| Pitfall | Do this instead |
|---|---|
| The tour only ran after a profile form, so admin-created users never saw it | Start it from `Layout` whenever `tour_state` isn't completed or skipped. |
| `roles[0]` chose the tour | Use `primaryTourRole` with ACE's aliases (`qa`, `operations`, `manager`). |
| Access compared full URLs, and `?tab=` links failed the check | Strip the query when resolving access; keep it for navigation. |
| The menu lived inside `Sidebar.tsx`, so the tour couldn't import it cleanly | Move it to `lib/nav-items.ts` first (section 4.1). |
| A scale "ping" pulse drew a giant box on wide tables | Pulse in place. |
| Long titles wrapped and the footer pushed buttons off the card | One-line truncated header; the footer note wraps and the buttons don't shrink. |
| Content drifted from the UI | Anchor tests, plus the three-sources rule with `APP_GUIDE`. |
| A trainee pressed Approve and the invoice posted live | Section 7 table, enforced by tests. |
| Targets inside closed panels (invoice panel, batch panel) | Text-only fallback that says which panel to open. |

---

## 14. Build order and rough effort

| # | Work | Effort |
|---|---|---|
| 1 | Move the menu to `lib/nav-items.ts` and `lib/nav-access.ts`; make `ProtectedRoute` use it | 0.5 day |
| 2 | Backend: migration 147, `GET /staff/me`, `PATCH /staff/me/tour`, nginx prefix | 0.5 day |
| 3 | Port the player, providers, ShowMeHow and tour card; add the test suite | 1 day |
| 4 | Anchors (section 9) | 0.5 day |
| 5 | Day scripts for all 10 roles (section 6) | 1 day |
| 6 | Walkthroughs: the worked examples first, then the rest of the catalogue | 2–3 days |
| 7 | User Access "Preview onboarding" | 0.5 day |
| 8 | Review sessions with Frontdesk, QC, Finance and Sales staff; fix the copy | 1 day |

---

## 15. As built (28 Oct 2026)

| Piece | Where | Note |
|---|---|---|
| Menu and access | `client/lib/nav-items.ts`, `client/lib/nav-access.ts` | `ROUTE_ACCESS` (moved unchanged from `ProtectedRoute`) is the one rule for the route guard, menu, tour and walkthroughs. Added `/finance/books/invoice-print` for every role that raises or follows invoices: Frontdesk and Sales were being sent back to the Dashboard when they pressed Print invoice. |
| Tour progress | `migrations/147_user_tour_state.sql`, `routers/staff_me.py` | **Differs from 4.2:** stored on `placeware_users.tour_state` (every login has one; no HR row is created as a side effect) and served at `GET`/`PATCH /staff/me/tour` (`/staff/me` would collide with `GET /staff/{staff_id}`). |
| Welcome tour | `client/lib/day-tours.ts`, `client/lib/tour-config.ts`, `components/tour/TourProvider.tsx`, `TourStep.tsx`, `TourHost.tsx` | Day scripts for all 10 roles. Started from `Layout` for every account. User menu: *Take the tour again*, *Tour every page I can open*. |
| Show me how | `components/tour/ShowMeHow.tsx` (top bar of every page), `WalkthroughProvider.tsx`, `WalkthroughPlayer.tsx` | **Differs from 4.5:** one button in the top bar instead of one per page title. It opens a searchable panel: *On this page* (that page's tour, then journeys starting there), *Follow the work* (journeys), *Tour of any page*. |
| Content | `client/lib/tour/guides-*.ts` (a guide for every route in `App.tsx`: every tab and button, crawled from the live screens), `client/lib/tour/journeys.ts` (the 12 journeys of section 8) | |
| Targets | `client/lib/tour/find-target.ts` | **Extends section 5:** a step points at `anchor` (data-tour-id) **or** `target` (the control's on-screen label, with `kind` tab / button / field / row). `kind: "row"` means "the first clickable row of the list on screen", so a step can say "open any invoice" and the following steps explain the panel's buttons live. Panels open from list rows are searched first. |
| Other teams' pages | `stepFor()` in `client/lib/walkthroughs.ts` | A journey step on a page the learner's roles cannot open is explained, not navigated to ("This part happens on a page for finance…"). |
| Open panels | `WalkthroughPlayer.tsx` | The card keeps its own pointer and focus events, so pressing Next does not close an open invoice / bill / batch panel (modal "click outside"). |
| Preview | `components/tour/TourPreview.tsx` on User Access | Any role's tour, page tours and journeys; nothing recorded. |
| Tests | `client/lib/walkthroughs.spec.ts`, `client/lib/day-tours.spec.ts` | Section 11, plus: every App.tsx page has a guide; no learner is navigated to a page they cannot open. A browser play-through of every page tour is in the scratch tooling used for the release check. |

Bugs found and fixed while building this:
- Frontdesk / Sales "Print invoice" bounced to the Dashboard (route guard, above).
- New Walk-in step 3 asked the person who had just raised the invoice to type a name and press Pass QC, which the server always refuses (the person who raised an invoice cannot QC it). The step now hands over to QC ("Sent for QC"). The Finance step no longer requires a typed name; it signs with the login, as the server already did.
- The backend's uvicorn killed any worker that missed its 5 s health ping. A long report (the P&L takes about 5.5 s) caused this, and every request on that worker failed with 502. `--timeout-worker-healthcheck 60` (Dockerfile).
