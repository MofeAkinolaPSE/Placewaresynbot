# ACE Books — the finance engine that replaces Sage 50

ACE Books is the double-entry accounting module inside ACE. It replaces the client's Sage 50 (2013) end to end. It covers:
- sales and receivables, purchases and payables
- stock, banking, the general ledger
- fixed assets, budgets, period close and financial statements

It supersedes the CSV bridge in [ACE-Sage-Export-Bridge.md](ACE-Sage-Export-Bridge.md). That bridge only survives as a fallback.

This document is written to be reused. §3–§6 describe patterns: one system of record, one posting path, financial lineage, and one shared record view per record type. These carry over unchanged to similar builds such as the Royan Hospital / Synbot finance module. §13 is the checklist for doing that.

The design comes from the study documents in `financial-study/` (Data Model, Database, API, Frontend, Workflow Map, Capability Matrix v2) and from the two client meetings.

---

## 1. What it is, in one paragraph

Every money-affecting event in ACE becomes one accounting document in ACE Books, for example:
- a Frontdesk sale approved by Finance
- a supplier bill
- a customer receipt
- a stock adjustment
- a bank charge

That document posts one balanced journal through one posting service. Reports, statements, ageing, stock valuation and the Control Tower are all read from those journals and their subledgers; none keeps its own numbers. Any figure on any screen can be clicked back to the document and journal that produced it.

---

## 2. How ACE Books connects to the rest of ACE

```
        OPERATIONS                                FINANCE (ACE Books, /fin)                          READ SIDE
 ┌────────────────────┐   approve    ┌──────────────────────────────────────────┐        ┌──────────────────────────┐
 │ Frontdesk invoice  │─────────────►│ integrations.post_frontdesk_invoice      │        │ Control Tower            │
 │ (QC → Finance →    │  (own tx,    │   → sales invoice → PostingService       │        │ Financial statements     │
 │  Dispatch)         │  never blocks│                                          │        │ Report Center            │
 └────────────────────┘  Frontdesk)  │ Forms: invoices, receipts, bills,        │        │ Ageing / statements      │
 ┌────────────────────┐              │   payments, vouchers, journals,          │──────► │ Stock status / valuation │
 │ CRM customers      │◄─── shared ──│   adjustments, counts, loans, assets     │ reads  │ Lineage sheets           │
 │ Suppliers          │◄─── shared ──│                                          │        │ Integrity monitor        │
 └────────────────────┘   masters    │ Subledgers: AR · AP · stock (FIFO+batch) │        └──────────────────────────┘
 ┌────────────────────┐              │   · bank · assets · budgets              │
 │ Operational stock  │◄── mirror ───│ PostingService → fin_journals/lines      │
 │ (placeware_        │   (movements │ Controls: subledger = control account    │
 │  inventory_events) │   not from   └──────────────────────────────────────────┘
 └────────────────────┘   Frontdesk)                     ▲
                                                          │ one-time transfer (stage → check → load)
                                           Sage 50: balances at 30 Jun 2026 + line history 2018→Jun 2026
```

| ACE module | Relationship to ACE Books | Direction / rule |
|---|---|---|
| **Frontdesk** (walk-ins, invoices, QC, dispatch) | An invoice becomes a sales invoice in the books **at Finance approval**. `routers/frontdesk.py` `finance_approval` calls `integrations.post_frontdesk_invoice(…, automatic=True)`. | Runs in its own transaction and never blocks Frontdesk. Failures land in Close & Controls with Retry. Honours the `auto_post_frontdesk` setting. Test invoices can be **excluded** permanently. |
| **CRM** (`customers`) | ACE Books has no customer table of its own. It reads CRM customers: credit limit, payment terms, Sage code. Walk-ins link to customers through `frontdesk_walk_ins.customer_id`. | One master per party. The Sage migration only *adds* missing customers, keyed by Sage code. |
| **Procurement** (`suppliers`) | Same pattern: bills and payments reference the shared supplier master. | One master. |
| **CRM** (`src/services/crm_hub.py`, router `/crm/*`: overview, directory, customer, pipeline, deals, reminders, prospects, weekly-report, targets, leaderboard) | Customers, sales, margin, reorder cycle and balances come from the ACE Books views (`v_sales_lines`, `v_customer_invoices`, `v_ar_open`). **Pipeline** new → qualified → proposal (incl. payment plan) → won/lost; won/lost columns show 90 days. **Won creates or links the customer in `customers`** (the master ACE Books invoices); a deal whose customer gets a posted ACE Books invoice is **won automatically** at the invoice value. Prospecting returns real places near the rep (GPS or typed area, OpenStreetMap; Google Places when `GOOGLE_PLACES_API_KEY` is set) and stores nothing until the rep acts. Team targets are measured on ACE Books sales, rep targets on deals won. Customer credit limits can only be changed by finance/management (ACE Books enforces them at invoicing). | Migration 123 archived 155 Sage customers copied in as "won" deals and 1,792 imported/mock prospects; `require_role("crm")` (an unassignable role) replaced so sales reps can use the CRM. |
| **Inventory & Quality: QC, Compliance/QMS, calendar** (`src/services/quality_hub.py`, router `/quality`, sidebar group "Inventory & Quality") | **Recall** = QMS case (`recall_cases`) + ACE Books recall (`fin_recalls`), opened in one transaction from QC, Compliance or the calendar: batch set RECALLED, buyers traced into `fin_recall_items`, closing the case closes the books recall. **Batch release**: a registered batch (`nafdac_batch_registry.fin_batch_id`) is QUARANTINED in ACE Books until QC releases it (AVAILABLE); rejection keeps it quarantined and raises a deviation. **Expiry** per product from ACE Books lots, with quarantine / write-off (adjustment for a second approver) / recall per lot. **Deviations** carry a close date and CAPA due dates; a maintenance or audit deviation moves the linked job. **Audits** have a real date; completing a recurring one books the next. **Calendar** (`/quality/calendar`) is a view over these records plus stock orders, lots expiring and manual events; moving an item moves the record. **Sales rule:** stock sold or loaned without a named batch never comes from a recalled, quarantined, damaged or expired lot; a named expired batch is refused (`fin/inventory.issue`, `require_sellable`). | One record per fact; QC and Compliance endpoints delegate recalls and batch release to `quality_hub` (migration 122). QA roles have `inventory.view / recall.create / batch.edit / adjustment.create` in ACE Books. |
| **Operations: stock orders, suppliers, logistics** (`src/services/stock_orders.py`, router `/procurement/*`, `/ops/overview`) | **Reorder plan** per *product* (every Sage lot code of a product, e.g. MENACTRA (A)…(R), is one product): ACE Books stock + dated sales demand (180 days) + last supplier and cost + stock on order → status and suggested quantity; FIFO lot-by-lot expiry risk. **Stock orders** are `replenishment_requests`: requested → approved → with supplier → **received automatically when a supplier bill for any lot code of that product is posted in ACE Books** (`sync_received`, linked by `bill_id`). **Supplier invoices** = ACE Books bills + the Sage purchase journal (an invoice still open at go-live appears once, as its opening bill). **Supplier directory**: balances from ACE Books payables, buying history, gap between invoices, price trend. **Logistics**: Frontdesk order → dispatch, delivery board, stock turnover and days of stock from ACE Books cost of sales. | Operations never records money. Stock enters only on a supplier bill or an approved adjustment. The old "purchase orders" (Sage vendor-invoice history) and the reorder automation's Sage-based requests are retired (migration 121). |
| **Operational inventory** (`placeware_inventory_events`, Inventory page) | ACE Books keeps the valued stock (FIFO layers, batches). Its movements are mirrored into the operational event feed; Frontdesk-sourced movements are skipped, because Frontdesk already moves operational stock. The Inventory page's stock actions now create ACE Books documents: **Receive stock** posts a supplier bill (delivery) or an EXCESS adjustment (stock found); **Log adjustment** and **Write off** create adjustments for a second person to approve. | Books → operations, one way. Books and live stock move together (verified: delivery +10/+10, write-off after approval −3/−3). |
| **Sage 50** | A one-time transfer: balances at 30 Jun 2026, then line history, then the July-to-date export. Nothing reads Sage after the transfer. | Retired after the July-to-date load (§11). |
| **Finance department pages** (legacy) | Customer Receipts, Vendor Payments and Budget recorded into separate tables; Analytics and Reports duplicated ACE Books from Sage snapshots. All five routes now **redirect** to the ACE Books screens. AR & Alerts became **Credit Control & Alerts** (in the ACE Books group), keeping its own features (alert rules, credit-risk scoring, cash-flow forecast, payroll) but reading ACE Books. | One place to record each thing, one source for each number (§4). |
| **Non-finance features** (CRM 360, CRM stats and risk, reorder prediction, top sellers, inventory analytics, ops KPIs, margin drivers, dashboards, agents, report generator, health checks) | Read the migration-120 views through **`src/services/books_analytics.py`**; each falls back to its Sage snapshot only before ACE Books is live. Ask ACE's schema allowlist exposes the ACE Books views, not the frozen Sage AR/AP/GL/item snapshots. | One current source for every number in the app. |
| **Shared finance read functions** (KPI watchdog, intelligence services, Ask ACE tools, dashboards) | `sage_adapter.kpis / ar_aging_buckets / ar_aging_customers` and the finance router's P&L, credit-risk and cash-flow calculations delegate to **`src/fin/readmodel.py`** once ACE Books is live, with the same output shapes. | Every consumer gets ACE Books numbers without code changes. |
| **Auth / roles** | JWT roles map to ACE Books permissions (`context.py` `ROLE_PERMISSIONS`). The sidebar group and route guard allow admin, finance and management. | See §11 for the role list. |

---

## 3. Engine rules (the part that must never change)

1. **One posting path.** Every journal goes through `posting.post_system` (system documents) or the manual journal workflow. Nothing else inserts into `fin_journal_lines`.
2. **Database enforcement.** Triggers raise `FIN_<CODE>:` errors on any of:
   - an unbalanced journal (deferred to commit)
   - posting into a closed period
   - an inactive, header or cross-entity account
   - editing a posted journal
   - editing the audit log
   - editing a stock movement

   The API maps each to a typed error.
3. **Immutability.** Posted journals are never edited; corrections are reversals. Documents are voided (reversed), never deleted. The only permitted change to a stock movement is attaching its journal, or attaching a Sage lot to *migrated opening* stock (migration 119).
4. **Idempotency.** System postings carry an idempotency key. Forms send an `Idempotency-Key` header. A Frontdesk invoice can become at most one sales invoice (a unique index on its source).
5. **Subledgers reconcile to control accounts.** AR, AP, stock, stock-on-loan and fixed assets each have a control in the integrity monitor. The Control Tower shows them.
6. **Maker-checker.** Manual journals (when approval is on), stock adjustments and stock counts need a second person. `allow_self_approval` exists for very small teams.
7. **Money is `Decimal` at 2 dp and travels as strings.** The frontend formats values and never recalculates them. The backend is the financial authority.

---

## 4. The consistency contract: one fact, one place, one answer

These rules came out of the UI review of 29 Sep 2026. Apply them to any feature that appears in more than one place.

1. **One system of record per fact.**
   - Invoices, receipts, bills, payments, stock values and balances live in ACE Books.
   - People and organisations live in CRM and suppliers.
   - The physical workflow (QC, dispatch) lives in Frontdesk.

   A second screen may *show* a fact, but it reads it from the system of record. It never keeps its own copy.
2. **One recording path per event.** If two screens can record the same event, one must write through the other, or be retired (redirect). Recording the same sale in Frontdesk and again in ACE Books is prevented in three ways:
   - the Frontdesk invoice posts itself on approval
   - the ACE Books invoice form warns when the customer has Frontdesk invoices in progress
   - posting is idempotent on the Frontdesk source
3. **Same engine, same result.** A Frontdesk invoice and an ACE Books invoice run through the same `sales.create_invoice` / `post_invoice` code. Pricing, credit checks, FIFO/batch costing and the journal are therefore identical.
4. **Same inputs, same prefills.** Forms that capture the same thing offer the same assistance. The invoice form uses `GET /fin/products?customer_id=`, which returns:
   - stock on hand
   - the next batch to sell (earliest expiry first) and its expiry
   - the price this customer last paid (ACE Books first, then Sage history)
   - a list or recent price as fallback

   Choosing a customer shows `CustomerPanel`: balance, overdue, credit limit and % used, terms, and Frontdesk invoices in progress. The receipt form shows the same panel.
5. **Same record, same view.** A record looks and links the same wherever it opens. See §5.
6. **Same number, same source.** Two screens showing "receivables" must compute it the same way. Example: Control Tower "overdue" is netted from the same open-item subledger as the ageing report. It was once summed from gross invoices and showed more overdue than owed.

**Overlap register.** Keep this table current; it is the checklist for the next review.

| Purpose | Screens | Status |
|---|---|---|
| Raise a sales invoice | Frontdesk / Customer Workspace request; ACE Books › Sales › New invoice | Same engine. The ACE form has Frontdesk-level prefills plus a duplicate warning ✅ |
| Record a customer receipt | Finance › Customer Receipts (old `ar_receipts`); ACE Books receipts | Old route redirects to ACE Books ✅ |
| Pay a supplier | Finance › Vendor Payments (old `fin_vendor_payment_requests`); ACE Books payments | Old route redirects ✅ (the old approval queue is not carried over) |
| Budgets | Finance › Budget (old `fin_budget_targets`); ACE Books › Setup › Budgets | Old route redirects ✅ |
| Receivables ageing / AR alerts | Credit Control & Alerts; ACE Books aged receivables | Credit Control reads ACE Books through `readmodel` ✅. Totals are identical (₦559,912,558.31), customers are named and clickable. Invoice Match (ACE vs Sage) removed |
| Profitability / P&L | Finance › Analytics and Reports; Credit Control P&L tab; ACE Books statements | Analytics → Control Tower and Reports → Report Center (redirects) ✅. The P&L tab reads ACE Books: the pre-go-live months are one "migrated" row, then ACE months. Net ₦94,038,821.73 = Sage ✅. The old `v_pl_monthly` view was dropped from use because it double-counted revenue (₦1.68bn against Sage's ₦840M for Jan–Jun) |
| Credit risk, cash-flow forecast | Credit Control & Alerts | Scored and forecast from ACE Books open items, bank balance and supplier bills ✅. Credit-risk total = ACE receivables |
| Receive stock / adjust stock | Inventory page; ACE Books bills and adjustments | Inventory page actions create ACE Books documents ✅. Adjustment types no longer include "sale" or "restock" (those are invoices and deliveries) |
| Stock on hand (every screen) | Inventory, Frontdesk stock check, analytics, agents (`v_inventory`); ACE Books Stock | `v_inventory` reads ACE Books FIFO stock for every item the books hold ✅. The old view summed a Sage batch that lists each item twice, **doubling all stock** (MENACTRA (R) 1,496 against 748). Direct stock writes for books items are refused with a pointer to Receive stock / Log adjustment. Replenishment "received" no longer adds stock by itself; the supplier bill does. Frontdesk's dispatch SALE event stays as an operational record, because the books take the stock at Finance approval |
| Customer view | CRM 360; ACE Books customer panel | Same outstanding balance (Vaccines Place ₦243,756,199.85 in both) ✅. Overdue is netted with credits. Lifetime profitability and top items come from dated sales lines |
| Sales history | CRM top items, top sellers, inventory analytics, ops turnover, agents | `v_sales_lines` (Sage history 2018→Jun 2026 + ACE Books invoices and credit notes) replaces the undated `sage_invoice_lines_snapshot` ✅. Reorder prediction now uses every dated invoice (e.g. 134 orders for Vaccines Place) |
| Margin drivers | Analytics margin drivers, agents, report generator | From the ACE Books ledger by account type ✅. The old 4-digit GL ranges never matched the 5-digit chart and reported ₦0 revenue |
| Stock on hand | Inventory page (operational feed); ACE Books Stock (valued FIFO) | Kept in step by the one-way mirror; the valued figure is the books' |

---

## 5. Financial lineage and the shared record view

**Lineage** means every figure opens the record behind it, and every record links onward:

```
Report / statement → account → ledger line → journal → source document → customer / supplier → product → batch → stock movement
Revenue → month → customer → invoice → what was sold → product → who else bought it
Balance sheet line → subledger (ageing by customer · valuation by product & batch · asset register · bank register)
```

**How it is built**
- `drill-context.ts` defines the record types, including `sageinvoice`, and maps posting sources to them (`SOURCE_TYPES`, `sourceTarget`).
- `lineage.tsx` provides `<DrillProvider>` (wrapped around every Books page by `BooksShell`) and **`<RecordView>`**, the one detail view per record type:
  - journal, account
  - invoice, receipt, credit note, bill, payment, debit note, voucher
  - customer, supplier, product, batch
  - adjustment, loan, asset, historic Sage invoice
- `DrillLink` in `kit.tsx` makes any reference clickable. Records stack in one sheet with a breadcrumb and Back.
- **Pages reuse the same views.** Each list page's own detail sheet renders `<RecordView>` plus that page's actions (post draft, void, approve, reverse). An invoice opened from the invoice list, from a customer, from a journal or from a report is the same view.
- `kit.JournalSheet` hands off to the lineage viewer whenever one is present, so every journal opened anywhere gets search and drill-through.

**Side-panel standard.** New record views must follow this.

| Rule | Implementation |
|---|---|
| Use the full width | `Facts` grid (2–4 columns) for key fields; `Totals` box (2 columns) for money summaries. Never fixed narrow columns |
| Show everything we hold for the record | Header facts, lines, totals, what settled it (allocations), the journal, the source, void or override reasons, audit where relevant |
| Every reference is a link | Party, product, batch, journal, source document, settling documents |
| Long lists get a search box | `useListFilter` appears automatically above 6 rows: journal lines, ledger lines, customer and supplier lists, product sales and movements, batch movements |
| Busy records get tabs | Product: *Who bought it · Sales · Stock movements · Batches · Purchases*. Customer: *Invoices · What they buy · Sage history · Receipts · On loan*. Supplier: *Bills · What we buy · Payments* |
| Say where data came from | Migrated documents show a badge ("opening balance from Sage"). Their lines are labelled "from the Sage sales & COGS journal". Sage-history rows are labelled "Sage" |
| Actions live in the footer | Page sheets add Post / Void / Approve / Reverse under the shared view |

---

## 6. What data we hold and where it is exposed

| Data | Source | Stored in | Exposed in |
|---|---|---|---|
| Chart of accounts, opening TB (30 Jun 2026) | Sage COA + TB | `fin_accounts`, opening journal JV-000001 | Setup, Trial balance, statements, Report Center › Chart of Accounts |
| Open receivables / payables at cut-over | Sage aged AR/AP (detail) | Opening `fin_sales_invoices` / `fin_supplier_bills` / credit and debit notes (no journal; inside JV-000001) | Sales / Purchases lists, ageing, customer and supplier panels |
| **Line detail behind those invoices and bills** | Sage Sales Journal + COGS Journal + Purchase Journal | `fin_sage_sales_lines`, `fin_sage_purchase_lines` | Invoice and bill panels ("What was sold / bought"), customer "What they buy" and "Sage history", product "Sales" and "Who bought it" |
| **Every stock movement per Sage item** | Sage Item Costing report | `fin_sage_item_costing` | Product › Stock movements; used to pin history lines to the exact lot |
| Stock on hand (valued) | Sage Inventory Valuation | FIFO cost layers + opening movements | Stock status, valuation, unit activity, product panel |
| **Batches and expiry of opening stock** | Sage item = one lettered lot (`ROTARIX(L)` → lot `L`); expiry from `sage_items_snapshot` | `fin_batches` (attached by `sage_history.assign_opening_batches`) | Stock › Batches & Expiry, product › Batches, FEFO batch suggestion on invoices |
| Everything posted in ACE Books from go-live | Forms + Frontdesk | Documents + journals | Everywhere |

Two points about the history:
- **Sage history is display and lineage only.** It never posts and never changes a balance.
- **Loading is repeatable.** Each file replaces its own date range, so loading the July-to-date export later doesn't duplicate anything.

**How history lines are matched** (`sage_history.resolve`):
- **Customers**
  - Sales-journal AR line → customer by name or Sage code.
  - Opening invoices → exact customer, via the invoice's source.
- **Items**
  - A name that belongs to only one item gets that item.
  - Otherwise, a sale is matched to the Item Costing entry with the same item name, date, quantity and cost. This pins the exact lot.
  - Purchases are matched on bill date and received cost, which also gives the quantity.

**Loaded 29 Sep 2026** (2018 → 26 Jun 2026):

| History | Lines | Matched |
|---|---|---|
| Sales lines | 77,135 | 99.98% to a customer, 97.5% to an exact item/lot, 98% with quantity and cost. Unmatched lines are mostly delivery charges, which correctly aren't items |
| Purchase lines | 2,278 | 96.8% to item and quantity |
| Item-costing movements | 78,871 | 733 items |
| Opening stock | 40 items | All batched; 37 with an expiry date |

**Reconciliation:** item sales total ₦7.97bn against ₦8.26bn in Sage's Items Sold report (the difference is non-item lines). Cost of sales is ₦6.71bn against ₦6.76bn.

---

## 7. Where things live

### Database
- `116_fin_core.sql`: the kernel.
  - Entities, periods, chart of accounts.
  - Journals and lines, settings, posting rules, audit.
  - The GL view `fin_v_general_ledger` and the guard triggers.
- `117_fin_modules.sql`: the subledgers.
  - Stock: products, batches, FIFO layers, movements, adjustments, counts, loans, recalls.
  - Banking; AR and AP documents with allocations; assets; budgets.
  - Controls, source postings, migration batches.
  - Seeds entity **PNL**.
- `118_fin_bill_invoice_normalisation.sql`: the duplicate supplier-invoice rule compares letters and digits only.
- `120_books_read_views.sql`: the read views for the whole app:
  - `v_sales_lines`, `v_customer_invoices`, `v_ar_open`, `v_customer_sales_summary`, `v_gl_monthly`
  - a corrected `v_inventory` (ACE Books stock; the Sage baseline de-duplicated for items outside the books)
- `123_crm_pipeline.sql`: `leads.customer_id / prospect_id / stage_changed_at / won_at / lost_at / lost_reason`, `crm_stage` enum gains `archived`, negotiation/payment_plan folded into proposal; prospect statuses saved/contacted/not_interested; interaction log accepts stage changes and customer-only entries.
- `122_quality_hub.sql`: `audit_schedule.scheduled_date`; `recall_cases.fin_recall_id / sku / expected_return_date`; `deviation_reports.target_close_date`; `nafdac_batch_registry.sku / fin_batch_id / expected_arrival_date / quantity / expiry_date / stock_order_id`.
- `121_stock_orders.sql`: stock-order columns on `replenishment_requests` (supplier, cost, expected date, approved/ordered timestamps, `bill_id`, received qty); cancels the 753 requests the reorder automation raised from the retired Sage stock view.
- `119_fin_sage_history.sql`:
  - The Sage history tables.
  - The history kinds in the migration pipeline.
  - The one permitted change to opening stock movements (attaching a lot).

### Backend (`backend/src/fin/`, router `/fin`)

| Module | Responsibility |
|---|---|
| `db.py`, `errors.py`, `context.py`, `audit.py`, `numbering.py` | Transactions, typed errors, user/permission/entity context, audit, numbering |
| `periods.py`, `accounts.py`, `setup.py`, `rules.py` | Calendar and close, COA, settings, posting-rule mappings |
| `posting.py`, `ledger.py` | Posting service, manual journals, reversal, TB, account activity, GL |
| `sales.py`, `purchases.py` | AR and AP documents, allocations, credit and duplicate controls, Frontdesk → invoice. Detail of migrated documents includes `history_lines` |
| `inventory.py` | FIFO/batch costing, adjustments, counts, loans, trace, recalls, the operations mirror |
| `banking.py`, `assets.py`, `closing.py` | Banking and reconciliation; fixed assets; year-end and budgets |
| `reports.py`, `report_center.py`, `dashboard.py`, `controls.py` | Statements, ageing, journals, Report Center tables with lineage links, Control Tower, integrity monitor |
| `integrations.py` | Frontdesk → books: automatic-post pause, **exclude** (tests / duplicates), unposted list, retry, backfill |
| `migration.py`, `sage_history.py` | Sage transfer (stage → check → load): balances, open items, stock, line history, batch attachment |
| `../services/books_analytics.py` | The non-finance read layer: customer receivables, profitability and top items, order history, CRM totals, top sellers and customers, product profitability, stock totals, sold units, AR by month, ledger rows / detail / account summary / cash register, margin drivers, data counts |
| `readmodel.py` | ACE Books as the finance read model for the rest of ACE: open-item AR/AP rows, ageing buckets and customers, KPIs, P&L series, cash position. It keeps the legacy function shapes, and `live()` gates the switch-over |
| `api.py` | All endpoints. Error envelope `detail: {code, message, details}` |

**Endpoints added for lineage and consistency:**
- `GET /customers/{id}/overview` and `GET /suppliers/{id}/overview`: party hubs. They include exposure, Frontdesk invoices in progress, and Sage history.
- `GET /products?customer_id=`: search with prefills.
- `GET /products/{sku:path}/movements`: includes `sage` history. SKUs may contain `/`.
- `GET /sage-history/invoices/{no}`
- `GET /integrations/frontdesk/unposted`
- `POST /integrations/frontdesk/{id}/exclude`
- `POST /migration/opening-batches`
- `GET /report-center/{key}`

### Frontend (`SynbotUI/client/`)
- `lib/books-api.ts`: the fetch wrapper (auth refresh, `X-Legal-Entity`, `Idempotency-Key`, typed `BooksError`) and formatters.
- `components/books/kit.tsx`: money and status components, server-side pickers, `DrillLink`, `JournalSheet`, `AccountSheet` (with search).
  - `ProductPick` takes `customerId` and shows the prefills.
- `components/books/lineage.tsx`, `drill-context.ts`: `DrillProvider`, `RecordView`, `Facts`, `Totals`, `useListFilter` (§5).
- `components/books/BooksShell.tsx`: frame, section nav, lineage provider.
- `pages/books/*.tsx`: routed under `#/finance/books/*`, lazy-loaded.
  - Sidebar: the top-level **ACE Books** group holds every finance screen, including **Credit Control & Alerts** (`#/finance/ar`, wrapped in `DrillProvider`) and **Sage Import / Export** (legacy reference uploads plus the export bridge).
  - The separate **Finance** group was removed; it only duplicated ACE Books.
  - `/finance/analytics`, `/finance/reports`, `/finance/ar/receipts`, `/finance/vendor-payments` and `/finance/budget` redirect to their ACE Books screens.

| Page | Covers |
|---|---|
| Control Tower | Cash, AR/AP (overdue netted), stock, revenue and profit. Each KPI tile opens its detail. Health checks, pending work, trend, ageing |
| Sales & Receivables | Invoices (prefills, customer panel, credit override), receipts (customer panel, auto-apply, WHT, duplicate-reference confirm), credit notes, ageing, statements |
| Purchases & Payables | Bills (stock with batch/expiry, expense, asset lines), payments with allocation and WHT, returns, ageing, statements |
| Stock | Status, FIFO valuation, unit activity (each row opens the product panel), batches and expiry, adjustments, counts, loans, trace, recalls |
| Banking | Accounts, vouchers, transfers, statement import, matching, reconciliation |
| Journals & Ledger | Journals (searchable panel), manual journal workflow, TB with drill-down, GL |
| Financial Statements | P&L (vs prior year, trace revenue), balance sheet (subledger links), cash flow, retained earnings, budget vs actual, the 8 Sage-style journals |
| Report Center | The essential reports from the study and meetings. Tables download as CSV and print; every cell links onward |
| Fixed Assets | Register, categories, depreciation, disposal |
| Close & Controls | Periods and checklist, year-end, integrity monitor, Frontdesk postings (unposted list with Post / Exclude, failures with Retry, auto-post status), exceptions, audit trail |
| Setup | COA, posting rules, settings, budgets, Sage transfer (a one-time tool, §11) |

### Infrastructure
`SynbotUI/nginx.conf`:
- proxies `^/fin/`
- sets `client_max_body_size 25m`
- gives `/fin/migration/` a 900 s read timeout (large Sage journals)
- serves `index.html` with `Cache-Control: no-cache`

Deploy with `docker compose build backend frontend && docker compose up -d backend frontend` from `backend/`. The images bake in the source.

---

## 8. Report Center

The essentials from the study and meetings are grouped by area:
- **Financial statements:** balance sheet, P&L, cash flow, retained earnings, budget vs actual.
- **General ledger:** COA, TB, GL, general journal, account register.
- **Sales:** sales analysis (revenue → month → customer → invoice), ageing, customer ledgers and statements, invoice and receipts registers, items sold to customers, sales and cash-receipts journals.
- **Purchases:** ageing, vendor ledgers, purchase register, cash requirements, purchase and disbursements journals.
- **Inventory:** valuation, stock status, unit activity, item costing, profitability, batches and expiry, stock on loan, COGS and adjustment journals.
- **Banking & control:** reconciliation, outstanding items, asset register, audit trail.

Every table report returns columns plus a lineage link per column (`report_center.py`), downloads as CSV and prints. Further Sage reports (working TB, customer and vendor lists, reorder worksheet, count sheet, item master) already exist in `report_center.py` and only need a catalogue entry.

---

## 9. Deviations from the study specifications

| Study said | Built | Why |
|---|---|---|
| SQLAlchemy + Alembic | Raw psycopg2 + numbered `.sql` migrations | Matches the rest of the ACE backend |
| Error envelope `{error:{code,…}}` | FastAPI `detail: {code, message, details}` | Matches every other ACE router |
| Separate customer/supplier masters | Shared `customers` / `suppliers` | One master per party (§4) |
| Weighted-average costing option | FIFO, batch-specific when a batch is named | Batch and expiry traceability |
| Payroll, tax engine, PO/GRN, AI tools | Not built | §12 |

---

## 10. Sage transfer results (entity PNL, balances at 30 Jun 2026)

| Item | Result |
|---|---|
| Chart of accounts | 464 accounts, 17 posting rules, 22 bank/cash accounts, 7 asset categories, 791 products |
| Opening TB | JV-000001, ₦2,643,616,118.81 each side |
| Profit Jan–Jun | ₦94,038,821.73, **equal to Sage** |
| Open receivables | 2,755 documents, ₦559,912,558.31, equal to Sage's aged report, ageing to the kobo |
| Open payables | 118 documents, ₦589,853,418.49, exact |
| Stock | 40 items, ₦153,438,241.76, batched with expiry (20 negative-stock items excluded) |
| Line history | §6 |

**Known differences carried over from Sage (for the accountant)**
- **AR:** control 11000 is ₦55,190 above the customer ledger (already so in Sage).
- **Inventory:** GL ₦100.87M against valued stock ₦153.44M. Run a full stock count.
- **Fixed assets:** ₦527.7M in the GL with an empty register. Register each asset as an opening balance.
- **Suspense account 10120** carries a balance.

---

## 11. Go-live runbook

1. **Load July → export date from Sage** (the last Sage data ever), from files covering 1 Jul → the end date. The list agreed with M:
   - General Ledger, Trial Balance
   - Customer Ledgers, Sales Journal, COGS Journal
   - Vendor Ledgers, Purchase Journal
   - Aged Receivables and Aged Payables (detail, as of the end date)
   - Inventory Valuation (as of the end date)

   The GL becomes monthly journals, the subledgers are re-baselined to the end-date reports, and the history tables are extended. *(The importer for this step is the next build item.)*
2. **Move the cut-over** to the day after the export end date, and switch **auto-post Frontdesk** back on (Setup › Settings). From then on nothing is keyed into Sage.
3. **Retire the transfer tool.** Hide Setup › Sage migration. ACE's own database is now the complete record.
4. **Deploy to the client's server from a database dump** of this environment plus the new code: pull, apply migrations 113–119, rebuild. Don't re-run the transfer there.
5. **Clear the known differences** (§10).
6. **Prove the live path.** Take one real Frontdesk invoice through approval, then check it on the Control Tower, in the customer's statement and in stock.
7. **Assign roles** (`context.py` `ROLE_PERMISSIONS`):
   - `finance`: bookkeeping, close, transfer.
   - `management`: reports, approvals, credit override, close and reopen, settings, budget approval.
   - `admin`: everything, including control-account journals.
   - `sales`: invoices only.
   - `ops`: stock only.
8. **Close each month in turn** from the checklist (Close & Controls › Periods).

Current state (29 Sep 2026):
- Auto-post is **paused**.
- The 10 test Frontdesk invoices (Aug–Sep) are **excluded**.
- The books hold only the 30 Jun transfer.

---

## 12. Not built yet / open items

- **Payroll.** Needs the Nigerian statutory rules (PAYE, pension 8%/10%, NHF, NSITF, ITF) and the HR data source.
- **VAT.** `OUTPUT_TAX` / `INPUT_TAX` are unmapped (the client posts no VAT through Sage sales). Invoices with tax are refused until the treatment is confirmed.
- **Goods received / three-way match.** Stock orders (Operations › Stock Orders & Purchases) cover request → approval → placed with supplier, and close when the supplier bill is posted. There is no separate GRN step between delivery and the bill, and lead time is a stated assumption (30 days) because no order dates were ever recorded.
- **Sage "purchase orders" retired** (29 Sep 2026): `sage_purchase_orders_snapshot` was Sage's Vendor Transaction History (every supplier invoice since 2018, 1,180 rows; the 72 "open" were simply invoices from the last 180 days). The PO page, Project Controls, ops fulfilment KPI and Workstation card now read stock orders and supplier bills; only the import tooling still references the table.
- **Automation** (`workflow/automation.py`): the low-stock, expiry and credit-risk loops stand down once ACE Books is live (reorder plan, batch expiry/recalls and Credit Control alert rules replace them); they read Sage views and had raised 753 reorder requests for dead items.
- **Sage snapshots still read on purpose** (29 Sep 2026 sweep):
  - **Staff and payroll** (`sage_staff_snapshot`, `sage_payroll_snapshot`): HR data (Sage's employee file is empty), outside ACE Books.
  - **Legacy endpoints behind retired pages** (`/finance/invoices`, budget variance, AR match, `ar_receipts`): no screen calls them any more; remove when convenient.
  - **Import tooling and data-intelligence lineage** (`data_ingest`, `pipeline/orchestrator`, `explorer`/`lineage` services): write side and diagnostics.
  - **`sage_sync_engine`** (the live Sage API bridge): obsolete once Sage is switched off.
- **Finance questions in Ask ACE**: read-only tools over `/fin/reports`.
- **Multi-currency revaluation**: everything is NGN today.

---

## 13. Replicating ACE Books in another project (e.g. Royan Hospital / Synbot)

Carry over unchanged:
- **The kernel:** `116`, most of `117`, and `posting.py`, `ledger.py`, `periods.py`, `controls.py`, the triggers, and §3's rules.
- **The consistency contract (§4).** Start the overlap register on day one. List every screen that records or shows money, and name its system of record.
- **The lineage layer (§5):** `drill-context.ts`, `lineage.tsx`, `DrillLink`, `RecordView`, `Facts` / `Totals` / `useListFilter`, and the side-panel standard. Build the record views first; the list pages then only add actions.
- **Operations → books integration** in the Frontdesk pattern:
  - post at the approval point
  - in its own transaction
  - never blocking operations
  - idempotent on the source
  - with retry, backfill, exclude and a pause switch
  - watched by a control that also catches never-attempted items
- **Legacy transfer** as balances plus line history: stage → check against the legacy system's own reports → load, then retire the tool and deploy by database dump.

Adapt:
- **Parties:** for a hospital, patients / payers (HMOs, insurers) replace customers, and the HMO is usually the debtor. Keep one master per party, shared with the clinical system.
- **Posting rules** (`rules.MAPPING_KEYS`): service revenue by department, HMO receivables, pharmacy stock and COGS, deposits / advances.
- **Stock:** pharmacy and consumables keep batch, expiry, FEFO and recall exactly as here.
- **Roles:** map clinical and billing roles onto `ROLE_PERMISSIONS`.

Before calling a copy done, check it against §14.

---

## 14. How it was verified

- **Golden tests:** 27 in `backend/tests/fin/`.
  ```
  FIN_TEST_DATABASE_URL=postgresql://postgres:<pw>@localhost:5432/synbot_demo python -m pytest tests/fin -q -p no:cacheprovider
  ```
- **Live data:** statements, ageing and balances reconciled to Sage's own reports. History reconciled to Sage's Items Sold and COGS totals (§6). Spot checks:
  - invoice OB-52365 = MENACTRA (R) × 2, ₦55,200, cost ₦49,000
  - bill WLGRIN26009416 = ACTRAPID (U) × 200 and NOVORAPID × 5
- **Endpoint smoke:** every GET the pages call returns 200 through nginx.
- **Form flows:** every form's payload was replayed through the real `/fin` router on one connection, then rolled back. The TB and balance sheet still balanced and the cash flow reconciled.
- **UI:** headless-Chromium runs over all pages and the lineage panels, with no page errors or failing calls:
  - invoice, bill and credit-note panels
  - searchable journal
  - product tabs, customer history
  - invoice form prefills
