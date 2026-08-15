# ACE Workspace Standard

**Version:** 1.0

**Platform:** ACE / Placeware Nigeria Limited

**Prepared By:** Placeware Engineering

**Delivered by:** `ACE-Customer-Receipts-Workspace.md` (the first workspace built to this standard)

---

# Chapter 1 — Purpose & Origin

## 1.1 Origin

`backend/docs/Latestmods-TB/NL-Master-guide/` contains UX/workflow standards written for RoyanHealth, a hospital client: a platform-wide "Universal Department Workspace Standard" (UDWS) — one consistent screen layout every hospital department reuses — plus 10 department-specific specs (SHAS-101→110) and an engineering translation (SHES-001→008).

This document takes the reusable **pattern**, not the hospital content: the layout shape, the dropdown-vs-autocomplete rule, and the modal-priority hierarchy are directly portable to a commercial-distribution business; encounters, patients, wards, and clinical workflows are not, and none of that vocabulary appears anywhere below.

## 1.2 In scope

- The 6-region workspace layout (translated).
- The dropdown-vs-autocomplete rule for smart forms.
- The modal/panel priority hierarchy.
- A small shared component set implementing the above.

## 1.3 Explicitly out of scope

- Retrofitting any existing page — deferred to future phases, done one at a time. **Retrofitted so far**: `Frontdesk.tsx`'s `InvoicesTab` (see Chapter 9) and `QualityControl.tsx`'s CAPA tab. `CRM.tsx`, `FinanceAR.tsx`, `SalesCRM.tsx`, `FinanceVendorPayments.tsx`, the rest of `Frontdesk.tsx` (`QueueTab`, `NewWalkInTab`, `ReportsTab`), and the rest of `QualityControl.tsx` (`DashboardTab`, `ExpiryTab`, `TemperatureTab`, `NafdacTab`) remain untouched. Nothing existing is modified by adopting this standard beyond the specific tab/page a given retrofit targets.
- Zustand or any global state library — this app has no global state library today; TanStack Query's cache plus local component state is sufficient at this scope.
- Realtime/WebSocket wiring stays opt-in per feature, not mandatory — but `InvoicesTab` now uses it (see Chapter 7), justified by the genuine "shared queue multiple staff act on concurrently" case that chapter calls out. Most retrofits still won't need it (e.g. CAPA's retrofit doesn't).
- A mandatory Timeline strip or Notifications strip — see 2.4.

---

# Chapter 2 — The ACE Workspace Layout

## 2.1 The shape

UDWS's core layout (repeated verbatim across the source docs) is a fixed region set:

```
Header
[ List/Queue Panel | Detail Workspace | Quick Actions ]   (3-column body)
```

Only the content of each region varies per workspace; the shape stays fixed. Translated to ACE:

| UDWS region | ACE region | Content example (Customer Receipts) |
|---|---|---|
| Header (dept name, KPI counts, alerts) | `PageHeader` + `KpiStrip` | "Customer Receipts & Accounts" · today's total/count/unapplied/voided |
| Queue Panel | List/Queue Panel | Recent receipts, filterable, searchable |
| Current Patient Workspace | Detail Workspace | Selected receipt's full detail, inline |
| Quick Action Panel | Quick Actions | "Record Receipt", "Refresh" |

## 2.2 Body layout

A 3-column grid, roughly `280px | 1fr | 240px`, stacking to a single column on mobile.

## 2.3 KPI strip placement

KPI counts get their own strip directly below the Header, not crammed into the header row — this already matches this app's existing convention (`DataIntelligence.tsx`, `FinanceVendorPayments.tsx` both separate the header row from a KPI-card row).

## 2.4 Timeline and Notifications strips — deferred

UDWS also specifies a Workflow Timeline strip and a Notifications/Activity strip below the 3-column body. **Both are deferred for v1**, space reserved but not built:

- No existing page in this app uses either pattern.
- The underlying need — every action audited (actor/timestamp/before/after) — is already met by `audit_event()` without a dedicated Timeline widget.
- A page-local Notifications strip would duplicate this app's existing `threads.py`/unread-summary infrastructure — building a second, page-local notification pattern is exactly the kind of divergence this standard exists to prevent.

Revisit once a second workspace page exists and a real, demonstrated need justifies the additional surface.

## 2.5 Header region inside Tabs-hosted retrofits

Validated by the standard's second real consumer: `Frontdesk.tsx`'s `InvoicesTab`, retrofitted without touching its sibling tabs (`QueueTab`, `NewWalkInTab`, `ReportsTab`).

When a workspace is retrofitted as one tab inside an existing multi-tab page — rather than shipped as its own route, like `ARReceipts.tsx` — **`PageHeader` is skipped entirely**. The page's own top-level header plus the active `TabsTrigger` label already satisfy the Header region's identity function; a second title inside the tab would be redundant. `KpiStrip` still applies, dropped directly into the tab's content in place of the `PageHeader`+`KpiStrip` pairing.

Only introduce a `PageHeader` inside a tab if that tab has header-level actions with nowhere else to live. (`InvoicesTab` doesn't: its closest analog to `ARReceipts.tsx`'s "Record Receipt" action — creating an invoice — belongs to a different tab, `NewWalkInTab`'s wizard.)

---

# Chapter 3 — Universal Workspace Rules

Carried over from UDWS, translated:

- Minimize navigation — prefer inline editing or a side panel over a new page.
- Preserve context — the selected record stays loaded until the user changes it.
- Every action is audited (`audit_event()`), not just financially-sensitive ones.
- **Explicit carve-out**: financial "post" actions (e.g. recording a receipt) are a deliberate, confirmed action — not auto-saved. They are irreversible ledger events (immutable after confirmation; corrections happen via a reversal with a reason, never a silent edit), unlike draft/editable UI state elsewhere, which may auto-save freely.

---

# Chapter 4 — Smart Forms: Dropdown vs. Autocomplete

The rule, translated directly from UDWS's Smart Forms standard:

- **Large, governed catalogues** (customers, items/products, GL accounts, vendors) → a searchable typeahead/autocomplete against the master data, not a giant dropdown and not free-text. Component: `EntityAutocomplete`.
- **Small, fixed enumerations** (payment method, status, priority) → a plain `Select` dropdown. Component: the existing `Select` primitive, via `FilterBar` for filters or used directly in a form.
- Manual free-text typing is the last resort, never the first choice, for anything that exists in a governed catalogue.

### Engineering Decisions

- `EntityAutocomplete` generalizes the existing hand-rolled `InventoryAutoComplete.tsx` pattern (300ms debounce, min-2-chars) via generic `fetchFn`/`getKey`/`getLabel` props, rather than introducing a `cmdk`/Radix-Popover Combobox dependency that doesn't exist in this app today.
- Every existing filter dropdown in this app already solves Radix `Select`'s `value=""` restriction with a sentinel value mapped back to `""` in state. `FilterBar` owns that translation internally so callers never see the sentinel.

### Implementation Requirements

- `SynbotUI/client/components/workspace/EntityAutocomplete.tsx`
- `SynbotUI/client/components/workspace/FilterBar.tsx`

### Acceptance Criteria

- No new frontend dependencies added for search/autocomplete.
- Filter state feeds directly into the consuming page's `useQuery` key, matching the existing app-wide convention.

### Developer Checklist

- [ ] `EntityAutocomplete` accepts a generic `fetchFn` — not hardcoded to one entity type
- [ ] `FilterBar`'s sentinel translation is internal — callers pass/receive plain `""`

---

# Chapter 5 — Modal/Panel Priority Hierarchy

Translated directly: **inline editing > side panel > modal dialog > new page.** Only use a new page when the workflow genuinely can't fit in the current workspace.

- **Side panel** = shadcn `Sheet`, wrapped as `DetailSheet`. Chosen because it's the only side-panel primitive already used correctly once in this app (`SalesCRM.tsx`'s "Pre-call Intelligence Brief") — not the hand-rolled `motion.div` drawer pattern that `Frontdesk.tsx`'s Invoices tab used to use (retrofitted onto the inline Detail Workspace instead — see 5.1), and not an inline toggle-form for *creating* a new record (see 5.2 — `QualityControl.tsx`'s CAPA tab retrofit).
- **Modal dialog** = shadcn `Dialog`, reserved for short confirmations requiring a single input (e.g. void-with-reason), matching `FinanceVendorPayments.tsx`'s existing reject-with-note pattern exactly.
- **Inline** = the Detail Workspace region itself, for a workspace's primary content (e.g. viewing a selected receipt) — not everything needs a panel or dialog.

## 5.1 Inline Detail Workspace has no dismiss affordance, by design

Validated twice now: `ARReceipts.tsx` (native) and `Frontdesk.tsx`'s `InvoicesTab` retrofit, which replaced the exact hand-rolled drawer named above — the drawer had a backdrop-click and an `X` button to dismiss back to a list-only view; the inline Detail Workspace has neither.

This is a direct, intentional consequence of Chapter 3's "preserve context" rule, not an oversight: a persistent region showing the currently-selected record has no reason to be dismissible — the user changes what's shown by selecting a different list item, not by closing the panel. Call this out explicitly in any retrofit's PR/review notes so it isn't mistaken for a regression.

## 5.2 Create forms belong in `DetailSheet`, even if the pre-retrofit page used an inline toggle

Validated by the third real usage: `QualityControl.tsx`'s CAPA tab pre-retrofit had an inline toggle-form for "New Deviation" — technically the top preference per the "inline > side panel" ordering above. Converted to `DetailSheet` anyway, matching `ARReceipts.tsx`'s "Record Receipt" precedent exactly.

The resolution: "inline > side panel" governs *viewing/editing a selected existing record* (the Detail Workspace's job). A multi-field *create* form is a different task — it has no natural inline home once the List/Detail/Actions 3-column shape is in place, since the Detail Workspace column is reserved for the selected item, not a blank creation form. `DetailSheet` is correct for both "record a new receipt" and "report a new deviation" — any ephemeral create/act flow — even on a page whose pre-retrofit version happened to use an inline toggle for it.

Also from this usage: selecting an item by ID and deriving the displayed record via `deviations.find(d => d.id === selectedId)` (rather than storing a separate snapshot object, as `InvoicesTab` does for invoices) keeps the Detail Workspace automatically in sync with the list query after a mutation invalidates it — no manual re-fetch-and-reselect needed. Prefer this when the list query already returns full detail (no separate richer fetch needed, unlike `InvoicesTab`'s invoices, which need a dedicated `GET` for full line items).

### Engineering Decisions

- `Sheet` is reserved for genuinely ephemeral tasks (e.g. "record a new receipt"), not persistent page content — persistent content belongs inline in the Detail Workspace region.

### Implementation Requirements

- `SynbotUI/client/components/workspace/DetailSheet.tsx`

### Acceptance Criteria

- No new `Dialog`/`Sheet`/hand-rolled-drawer variant is introduced beyond these two.

### Developer Checklist

- [ ] `DetailSheet` standardizes `className="w-full sm:max-w-xl overflow-y-auto"` (from `SalesCRM.tsx`)

---

# Chapter 6 — State Management

TanStack Query for all server state (list/detail queries, mutations with cache invalidation) plus local `useState`/`useReducer` for UI/form state. **No Zustand, no Redux, no new global store.** This app has no global state library today, and TanStack Query's cache already functions as the de facto shared cache app-wide. Page-scoped React Context is acceptable only if a single page's prop-drilling genuinely requires it — not expected at this scope.

---

# Chapter 7 — Realtime Policy

Opt-in per feature, justified case by case — not a platform-wide requirement. Vendor Payments uses plain TanStack Query invalidation after mutation with zero WebSocket wiring, and that's sufficient for a single-operator create/approve flow. `useRealtimeChannel` (`SynbotUI/client/hooks/use-realtime-channel.ts`) is for features that genuinely need live cross-user updates.

**First real use**: `Frontdesk.tsx`'s `InvoicesTab`, once extended into a QC/Finance/Ops work-queue (see `ACE-Customer-Receipts-Workspace.md`-style role-aware detail pattern) — a different logged-in QC or Finance user needs their queue view to reflect changes made by someone else, on a different invoice, without polling. The broadcast channel (`frontdesk_updates`, published via `realtime_hub.broadcast()` from `frontdesk.py` at each status transition) just invalidates the list query and, if the currently-open detail matches, refreshes it — no new client-side state machine, no manual reconnect logic beyond what the hook already handles.

---

# Chapter 8 — Shared Component Set

`SynbotUI/client/components/workspace/`:

| Component | Purpose |
|---|---|
| `PageHeader.tsx` | Header region — icon, title, subtitle, actions |
| `KpiStrip.tsx` | KPI strip below the header |
| `FilterBar.tsx` | Search + dropdown filters, owns the `Select` sentinel translation |
| `DetailSheet.tsx` | The one side-panel primitive |
| `EntityAutocomplete.tsx` | Searchable typeahead for governed catalogues |

Not yet built: a `WorkspaceLayout`/`QueuePanel` grid wrapper for the 3-column body. Even now that a second consumer exists (`Frontdesk.tsx`'s `InvoicesTab`, retrofitted onto the same `grid-cols-1 lg:grid-cols-[280px_1fr_240px] gap-4` shape as `ARReceipts.tsx`), extraction is deliberately deferred again — extracting it would mean also editing `ARReceipts.tsx`, which conflicts with keeping each retrofit's blast radius to one file. Logged as a candidate for the third usage.

A retrofit using only a subset of the 5 components is expected, not a smell. `InvoicesTab` uses `KpiStrip` and `FilterBar` plus the inline Detail Workspace pattern, but not `DetailSheet` or `EntityAutocomplete` — it has no ephemeral create/act flow (invoice creation lives in the separate `NewWalkInTab` wizard, untouched) and no governed-catalogue search. A page only needs the subset its actual flows call for; "uses all 5" is not a completion criterion.

### Engineering Decisions

- Every component here is additive — none replace or modify an existing component.

### Implementation Requirements

- See Chapters 4–5 for per-component detail.

### Acceptance Criteria

- No existing page's rendering or behavior changes as a result of these components existing.

### Developer Checklist

- [x] All 5 components exist under `components/workspace/`
- [x] Adopted by a second page (`Frontdesk.tsx`'s `InvoicesTab`) without modifying any of the 5 components themselves

---

# Chapter 9 — Rollout

## 9.1 Engineering Decisions

Build the standard and its components against one real, currently-missing feature (Customer Receipts & Accounts — see `ACE-Customer-Receipts-Workspace.md`) rather than a synthetic example, so the components are validated by production use from day one. Retrofit existing pages one at a time, narrowly scoped, only after the components have proven out on new work.

**Retrofit #1 (`Frontdesk.tsx`'s `InvoicesTab`)**: picked via a comparative research pass ranking candidates by lowest risk of behavior change, closest existing fit, and clearest visible value. `FinanceAR.tsx` was explicitly passed over — it's a 7-tab report center where only 1 tab has partial fit, and a real retrofit would first need an unresolved product-scoping decision (split into its own route? demote the rest to a separate "Reports" page?) before any engineering starts. `QualityControl.tsx` was retrofit #3, in two passes: `CapaTab` first (full retrofit — it genuinely fit the List/Detail/QuickActions shape), then `TemperatureTab`/`NafdacTab` (partial retrofit — see §9.5). `DashboardTab`/`ExpiryTab` remain untouched — see §9.5 for why.

## 9.2 Implementation Requirements

- Components (Chapter 8) ship alongside the first consuming feature, not in advance of it.
- Each retrofit is scoped to the smallest self-contained unit that has the workspace shape (a single tab, not necessarily a whole multi-tab page) — sibling tabs/flows that don't fit (wizards, dashboards, Kanban boards) are left untouched, not forced into the shape.

## 9.3 Acceptance Criteria

- A second (and third) workspace page can be built by composing these 5 components without needing to modify any of them. **Met**: none of the `InvoicesTab`, `CapaTab`, `TemperatureTab`, or `NafdacTab` retrofits changed any of the 5 shared components.
- No existing page, route, or API method changes behavior. **Met**: `QueueTab`/`NewWalkInTab`/`ReportsTab` (Frontdesk) and `DashboardTab`/`ExpiryTab` (QualityControl) all untouched across every retrofit pass; every API call the retrofitted tabs make is reused with the exact same request/response shape. Intentional UX changes (loss of the InvoicesTab drawer's dismiss button; CAPA/Temperature/NAFDAC create-forms moving from inline toggles to a Sheet) are documented consequences of 5.1/5.2, not unintended behavior changes.

## 9.4 Developer Checklist

- [x] Standard document reviewed against the shipped feature for drift (this document, Chapters 2.5/5.1/5.2/8/9.5, updated after each retrofit)
- [x] Retrofit #1 shipped narrowly (`Frontdesk.tsx`'s `InvoicesTab` only)
- [x] Retrofit #2 shipped narrowly (`QualityControl.tsx`'s CAPA tab only)
- [x] Retrofit #3 shipped: `QualityControl.tsx` fully assessed — `CapaTab` (full retrofit), `TemperatureTab`/`NafdacTab` (partial retrofit, §9.5), `DashboardTab`/`ExpiryTab` (intentionally untouched — no selectable/actionable records, or Kanban shape that doesn't fit)
- [x] Retrofit #4 shipped: Finance department fully assessed across `FinanceAR.tsx`, `FinanceVendorPayments.tsx`, `FinanceBudget.tsx` — see §9.6/9.7. `FinanceAR.tsx`'s long-deferred product-scoping question is resolved (§9.7), not just answered by scope-narrowing.
- [x] Retrofit #5 shipped: CRM department fully assessed across `CRM.tsx`, `SalesCRM.tsx`, `CRMLeadFinder.tsx`, `Leads.tsx` — see §9.9. Two full retrofits (first since `InvoicesTab`/`CapaTab`), the standard's own `DetailSheet` origin precedent finally converted, a dead-UI bug and a real data-shape bug both fixed, one identity-duplication question deliberately resolved and one bigger three-way pipeline duplication deliberately logged, not resolved.
- [x] Retrofit #6 shipped: Operations department fully assessed across `Operations.tsx` (+4 sub-dashboards), `LogisticsMonitor.tsx`, `ProjectControls.tsx`, `Suppliers.tsx`, `PurchaseOrders.tsx` — see §9.10. Two full retrofits, two consolidations (§9.7 pattern applied twice more), a wrong-endpoint bug fix, a missing-list-endpoint architectural gap closed, and `InventoryAutoComplete.tsx` fully retired (its last consumer converted).
- [x] Retrofit #7 shipped: HR department fully assessed across `HR.tsx`, `WorkforceDashboard.tsx`, `StaffDirectory.tsx`, `TimesheetsTable.tsx`, plus a correctness-only pass on `StaffDashboard.tsx` (not retrofitted — personal dashboard, wrong shape) — see §9.11. Smaller than Operations, but the first round driven by "remove fabricated data" rather than "adopt the shared components": genuinely fake trend/sparkline metrics identified and removed, and a real UUID-instead-of-name backend bug found and fixed.
- [x] Retrofit #8 shipped: Compliance & QMS department fully assessed across all 7 `Compliance.tsx` tabs plus a ported action into `QualityControl.tsx`'s `CapaTab` — see §9.12. The buggiest module found this session: 4 independent systemic bugs (a role-check bug, a response-shape bug, a wrong-arity `audit_event()` call across all 15 mutation sites, and an unsupported embedded-relation `select()` syntax across 5 maintenance endpoints) compounded with per-tab field-mismatch bugs and one full duplicate-tab consolidation with a ported capability. **This closes out the department rollout — all departments assessed.**
- [ ] Future work: none currently scoped — department rollout complete. Logged-not-built gaps remain across several rounds (`/controls/*` governance module, Compliance `Activities`/`Equipment` tabs, three-way leads pipeline duplication, `FinanceVendorPayments.tsx` vendor autocomplete) — see their respective sections above if picked up later.

## 9.5 Partial retrofits — when the shape doesn't call for List/Detail

Not every retrofit candidate needs the full 3-column List/Detail/QuickActions shape. `KpiStrip`, `FilterBar`, and `DetailSheet` compose independently of it and are each individually reusable.

`TemperatureTab` and `NafdacTab` (`QualityControl.tsx`) are the first case of a **partial** retrofit, as distinct from `InvoicesTab`/`CapaTab`'s **full** retrofit:

- **Full retrofit** (`InvoicesTab`, `CapaTab`): records are worth *selecting* — there's more to show about one than fits in a list row, so a persistent inline Detail Workspace earns its place.
- **Partial retrofit** (`TemperatureTab`, `NafdacTab`): flat audit-log/registry tables where every row already shows its full detail, and each action (Escalate, Approve, Reject, Update Status) is already a single `Dialog` click from the row. There's nothing a Detail Workspace would add — forcing the List/Detail split here would cost a click for no new information. These tabs instead adopt only `KpiStrip` (derived stats, `useMemo` off the already-fetched list — no new calls), `FilterBar` (replacing hand-rolled search/`Select` filters — `NafdacTab`'s manual `"__all__"` sentinel plumbing is deleted, `FilterBar` owns that internally), and `DetailSheet` for the multi-field *create* forms (same Ch.5.2 reasoning as CAPA's "New Deviation": an ephemeral create task doesn't have a natural inline home). The tables themselves, and every existing per-row `Dialog` action, are left exactly as they were.

When scoping a future retrofit, decide full vs. partial by asking: does the record have enough content that a reader benefits from a dedicated, persistent detail view — or does the list row already say everything relevant? The latter gets `KpiStrip`/`FilterBar`/`DetailSheet` only.

## 9.6 Finance department — mostly pure reports, no full retrofits

Researched three files (`FinanceAR.tsx`, `FinanceVendorPayments.tsx`, `FinanceBudget.tsx`) in full before touching any of them. Finding, stated plainly because it cuts against the pattern so far: **zero full-retrofit candidates**. Every tab is either a pure report/one-shot generator with no selectable or mutable records (AR Aging, Invoice Match, P&L, Cash Flow, Payroll, Credit Risk, Variance Report — all untouched, same reasoning as `DashboardTab`/`ExpiryTab`), or a flat registry table where every row already shows full detail and actions are already a single click/`Dialog` away (partial retrofit, §9.5):

- **`FinanceAR.tsx`**: unlike every prior retrofit target, this file is one monolithic function with all 7 tabs' state/queries/mutations inline, not split into per-tab components. Only its **Alert Rules** tab has real mutations (create/delete/ack) — extracted into its own `AlertRulesTab()` function first (mirroring `NafdacTab`/`TemperatureTab`), then given `KpiStrip` + `DetailSheet`. No `FilterBar` — the tab has no existing filter UI to replace, and adding one would be new UX rather than a like-for-like swap (Ch.8: only the subset a page's flows actually call for).
- **`FinanceVendorPayments.tsx`**: `KpiStrip` (existing 4 cards) + `DetailSheet` (create-request form). Its Approve-with-note/Reject-with-note `Dialog`s are the standard's own cited canonical example of the correct pattern (Ch.5) — left untouched. Status filter stays a `Tabs` strip, not converted to `FilterBar` — doing so would lose the pending-count `Badge` on the tab trigger and isn't a mechanical sentinel-cleanup win the way `NafdacTab`'s was.
- **`FinanceBudget.tsx`**: page-level `KpiStrip` (spans both tabs). Budget Targets tab gets `DetailSheet` for its create form; Variance Report tab is a pure computed report, untouched. Also fixed a real gap found during research: budget-target delete fired immediately with **zero confirmation** — added a short confirmation `Dialog`, matching the app's existing reject-with-note convention, rather than leaving a one-click destructive action live.

**Real backend bugs found and fixed via live write-through verification (not just noted)** — none introduced this session, all pre-existing and previously unexercised by any live test:
1. `POST /finance/ar/alerts` 500'd on every call — `audit_event(..., metadata={...})` passed a kwarg the function doesn't accept (real signature takes a positional `details` dict). Fixed at both call sites in `finance.py`.
2. Vendor payment approve/reject were broken for **every** user, always — both checked `user.get("role")`/`user.get("user_role")` (singular), fields that don't exist anywhere in this app's JWT payload (every router, including `_require_finance` two lines above the bug, uses `roles` — plural, a list). Since `_FINANCE_ROLES` and the redundant secondary `_APPROVE_ROLES` check were identical sets, fixed by deleting the dead secondary check rather than duplicating the roles-set comparison a second time.
3. Budget-target delete had the same singular-`role` bug, but with a genuinely narrower intended set (`admin`/`finance`, excluding `management`) — fixed by reading `roles` correctly rather than removing the check.
4. `TableQuery` (`backend/src/local_db.py`, the shared Supabase-style DB wrapper) had **no `.delete()` method at all** — `insert`/`update`/`upsert`/`select` only. `delete_budget_target` (and, found via grep, `threads.py` and `calendar_tasks.py`) called `.delete().eq(...).execute()` expecting Supabase semantics that were never implemented — silently broken since inception everywhere it was used. Added `.delete()` to `TableQuery`, mirroring `.update()`'s WHERE-clause builder, with one deliberate addition beyond that precedent: it refuses to execute with an empty WHERE clause (raises rather than risking a full-table wipe) — a DELETE with no filter is a categorically worse failure mode than an unfiltered UPDATE, so the extra guard is justified even though `.update()` itself doesn't have one.

## 9.7 AR Aging consolidation

Research surfaced a real duplication, not just a retrofit-shape question: `FinanceAR.tsx`'s AR Aging tab and `FinanceReports.tsx` (+ its `/finance/reports/ar/:bucket` drilldown, `ARAgingBucketDetails.tsx`) both read `GET /finance/ar/aging` — `FinanceAR`'s version (full per-customer table, search, triggered-alerts banner, inline expand) was strictly richer than the 4-row bucket-total table it duplicated. This is the resolution to the product-scoping question `FinanceAR.tsx` was originally deferred over ("split into its own route? demote the rest to a Reports page?").

**Resolved, not just logged**: `FinanceAR.tsx`'s AR Aging tab (its default tab — `/finance/ar` already lands there) is now the single canonical view. `FinanceReports.tsx`'s AR section was replaced with a `KpiStrip` of the same 4 bucket totals it already fetched (same `arAging()` call, zero new backend work) plus a "View Full AR Aging →" link to `/finance/ar`. `ARAgingBucketDetails.tsx` and its route were deleted — confirmed dead (its only entry point was `FinanceReports.tsx`'s now-removed bucket-row links) — along with the now-unused `api.finance.arAgingCustomers` client method. `FinanceReports.tsx`'s unrelated Inventory tab is untouched.

## 9.8 CRM department — the first full retrofits since InvoicesTab/CapaTab

Researched four files in full before touching any: `CRM.tsx`, `SalesCRM.tsx`, `CRMLeadFinder.tsx`, `Leads.tsx`. Unlike QC and Finance, CRM produced genuine **full** retrofit candidates again:

- **`CRM.tsx`'s Customer Accounts table** — full retrofit. Its Customer 360 dialog and Edit dialog moved into an inline Detail Workspace, replacing both modals; Edit fields became directly-editable inline inputs (Ch.3's inline-editing preference, matching `CapaTab`'s "always-editable fields + Save" precedent rather than a toggled Edit dialog). This reuses the same `GET /crm/customers/{id}/360` data `CustomerWorkspace.tsx` (Ch.10) already consumes — a real overlap, deliberately kept as coexistence, not consolidated: `CRM.tsx` is a bulk browse-all-customers admin view, `CustomerWorkspace.tsx` is a search-first single-customer order-raising workflow. Same shared-endpoint-different-job precedent as Ch.10.6 already established. Charts and the Active Opportunities table stayed untouched — confirmed pure computed reports, no real record ids, nothing selectable.
- **`CRMLeadFinder.tsx`'s Discover + Pipeline tabs merged into one full retrofit.** Previously, selecting a prospect card in Discover handed off to a *different tab* via a raw text ID field with no name or context shown — the textbook "record has more content than the row shows, but no persistent detail view exists" gap. The Detail Workspace now shows full prospect fields (including `contact_name`/`contact_email`/`industry`/`region`, fetched all along but never displayed) plus the Score+Ingest or Assign-to-rep form inline, switching on `converted_lead_id`. The List/Map toggle that used to live inside the results view became a full-width map panel toggled from Quick Actions instead, to avoid squeezing a map into a 280px List Panel column. Follow-ups stayed its own thin flat tab (zero actions, zero filters — thinner than even `NafdacTab`'s partial-retrofit bar).
- **`SalesCRM.tsx`**: Pipeline stayed a Kanban board, untouched (`ExpiryTab` precedent) — but its "Pre-call Intelligence Brief" side panel converted from a hand-rolled `Sheet` to the real `DetailSheet` component. Worth stating plainly: this is the exact panel `ACE-Workspace-Standard.md` Ch.5 cites as the real-world precedent that justified building `DetailSheet` in the first place — converting it closes that loop rather than opening a new one. Reminders and Targets tabs got `KpiStrip`+`DetailSheet` (`FinanceBudget.tsx`'s Budget Targets tab is the closest precedent for Targets). Bulk Message, Log Interaction, and New Lead all converted to `DetailSheet` too, per the now-established rule that a form's *shape* (multi-field ephemeral create), not its pre-existing container, decides the verdict.
- **`Leads.tsx`**: minimal partial retrofit, deliberately scoped down — see §9.9.

**Real bugs found and fixed during research/retrofit (not introduced this session)**:
1. `SalesCRM.tsx`'s "New Lead" dialog was fully wired (form, mutation, validation) but no button anywhere opened it — `setNewLeadOpen(true)` never appeared in the file. Added as a `PageHeader` action.
2. `Leads.tsx` → `LeadsQueue.tsx` — `GET /admin/leads` returns `{data, count}`, not a bare array. The old `Array.isArray(data)` check ran against the whole response object and was always `false`, so the leads queue silently showed "No leads found" regardless of what the backend actually returned. Fixed the check and `api.leads.list`'s return type (was mistyped as `any[]`).
3. `POST /crm/lead-finder/prospects/{id}/score-ingest` — found live, testing the Detail Workspace's primary action: the `leads_kg_node` trigger's `kg_create_node()` function compares `kg_nodes.ref_id` (bigint) against `NEW.event_ledger_id` (uuid) whenever that field is populated — `operator does not exist: bigint = uuid`, which as an AFTER-INSERT trigger rolled back the entire lead insert. Every score-ingest call that populated `event_ledger_id` had been failing outright. Fixed via `backend/migrations/101_fix_kg_create_node_event_ledger_link.sql` — the function's own comment already frames this lookup as best-effort ("Optionally create edge..."), so the fix wraps it so a failure there can never block the primary row insert, rather than attempting a real redesign of `kg_nodes`' bigint-only `ref_id` (shared cross-cutting infrastructure with triggers on `leads`/`customers`/`opportunities` — out of scope here).

## 9.9 Leads.tsx — bug fixed, three-way pipeline duplication logged not resolved

`Leads.tsx` sits on top of a bigger finding than a retrofit-shape question: this app has **three separate, disconnected "record a walk-in/lead" pipelines** — `Frontdesk.tsx`'s walk-in intake (bridged to `customers`, feeds the QC/Finance/Dispatch pipeline, Ch.10.3), `Leads.tsx`'s own `WalkInForm` (writes to legacy `placeware_leads`/`placeware_orders`), and `CRMLeadFinder.tsx`'s own separate `leads` table (CRM module). Unlike AR Aging (§9.7, one endpoint, one strictly-richer consumer), these three aren't obviously "one is correct and the others should redirect to it" — they may genuinely serve different funnel stages (early-funnel prospecting vs. an actual distribution-business walk-in vs. a legacy chat-widget capture path). Asked explicitly: **user chose to fix the real bug and ship a minimal retrofit, and log the three-way duplication as a future decision** — not resolve it this round.

Shipped: the `Array.isArray` bug fix (§9.8), `LeadsQueue.tsx` converted from plain `useState`/`useEffect`/`fetch` to `useQuery` (Ch.6 — it was the one file in this area that didn't follow that convention), a `KpiStrip` (total leads), and `WalkInForm`'s permanent inline form moved into a `DetailSheet` (Ch.5.2). `WalkInForm`'s `InventoryAutoComplete` swapped for the real `EntityAutocomplete` — Ch.4's Engineering Decisions section literally names that file as the hand-rolled pattern `EntityAutocomplete` was built to generalize; left `InventoryAutoComplete.tsx` itself in place since `Operations.tsx` still depends on it. **Explicitly not resolved**: whether `Leads.tsx` should be deprecated/merged into `Frontdesk.tsx`'s walk-in intake or `CRMLeadFinder.tsx`'s pipeline — a product decision, not an engineering one, same treatment `FinanceAR.tsx` originally got before its own round came up (§9.1).

## 9.10 Operations department — the biggest, messiest round yet

Researched five files in full before touching any: `Operations.tsx` (→ `InventoryDashboard.tsx`/`LogisticsDashboard.tsx`/`ProcurementImportDashboard.tsx`/`OperationsSettings.tsx`), `ProjectControls.tsx`, `Suppliers.tsx`, `PurchaseOrders.tsx`, `LogisticsMonitor.tsx`. Unlike Finance (§9.6, zero full-retrofit candidates) or CRM (§9.8, two), this round mixed real architectural bugs with retrofit-shape questions — several pages here weren't just under-styled, they didn't work.

**`LogisticsMonitor.tsx` — the deepest bug, user chose the full fix.** Both `deliveries` and `riders` were plain `useState([])`, populated only by the current browser session's own creates — there was **no list endpoint at all**, so both tabs started empty on every page load regardless of real data, including everything Frontdesk's delivery handoff (migration 099) writes directly into `deliveries`. Its "New Delivery" form also sent `{destination, recipient_name, recipient_phone}`, none of which exist on the real `Delivery` schema (`extra="forbid"`) — every submission 422'd, unconditionally. Given the explicit choice to fix this properly: added `GET /logistics/deliveries` and `GET /logistics/riders` (pure additive reads, rider-join pattern mirrored from the existing `active-deliveries` endpoint, no migration needed), corrected `api-client.ts`'s `createDelivery` payload shape to nest into `address` JSONB (matching what Frontdesk's `send_for_delivery` already writes), and rewired both tabs onto real `useQuery`s. Deliveries tab → full retrofit (closest precedent `InvoicesTab`): structured `address` fields, full GPS ping history via the already-built-but-unused `GET /logistics/deliveries/{id}/pings`, inline Start/Update-Status actions. Riders tab → partial retrofit (`NafdacTab` precedent): `KpiStrip` + `DetailSheet` for "Register Rider", flat card list and "Route" dialog kept as-is. Live Map stayed untouched (`SalesCRM.tsx` Kanban precedent). The "Assign Routes" button is now gated on a real unassigned count instead of stale, permanently-near-zero local state — a functional fix, since it was previously unusable against real backend data.

**`Operations.tsx` — a wrong-endpoint bug, not a broken feature.** The "Log Adjustment" dialog POSTed `movement_type` values (`SALE`/`DAMAGE`/`EXPIRY`/`ADJUSTMENT`/`TRANSFER`, uppercase) to `POST /inventory/movements`, whose real enum is lowercase (`purchase`/`sale`/`adjustment`/`transfer`/`write_off`) — guaranteed 422 on every use. Those uppercase values are in fact the real allowed set, but for a *different* endpoint: `POST /inventory/event` (`InventoryEventRequest{sku, quantity_change, event_type, reference?}`), the same one "Add Stock" already used correctly. Fixed by pointing "Log Adjustment" at the correct endpoint, restructuring the form to match (`sku` via `EntityAutocomplete`, signed `quantity_change`, `event_type` incl. RESTOCK, a single `reference` field), dropping the unsupported TRANSFER option and the Source/Destination fields that don't map to this model — and converting the dialog to `DetailSheet`. This is the last consumer of `InventoryAutoComplete.tsx` (§9.9 already swapped `WalkInForm.tsx`'s usage) — the file is now deleted, fully retired. `InventoryDashboard.tsx` (Inventory tab) → partial retrofit: `KpiStrip` for the 3 summary cards, `FilterBar` for the search input + company toggle (the existing 3-button company filter became a `FilterBar` select, using its `""`-is-all sentinel convention), `DetailSheet` for "Add Stock". `ProcurementImportDashboard.tsx` (Procurement/Import tab) → partial retrofit: `KpiStrip` for the 4 summary cards; also fixed a real gap found during research — "Escalate" fired immediately with **zero confirmation** on a single click, same class of gap as Finance's found-and-fixed budget-target-delete (§9.6) — added a short confirmation `Dialog`. `LogisticsDashboard.tsx` (pure computed report with descriptive KPI-card subtitles `KpiStrip` can't represent) and `OperationsSettings.tsx` (100% static prose) both confirmed untouched — same reasoning as `DashboardTab`/`ExpiryTab`.

**`ProjectControls.tsx` — one full retrofit, two consolidations, one real gap closed.** Converted from plain `useState`/`useEffect`/`fetch` to `useQuery` throughout (Ch.6, same class of fix as `LeadsQueue.tsx` in §9.9). Active Projects tab → full retrofit (`CapaTab` precedent): several real fields were fetched but never rendered anywhere — `quality_notes`, `nafdac_sampling_status`, `po_reference`, `temperature_profile`, `quality_checked_by`/`_at` — the textbook List/Detail/QuickActions gap. The Detail Workspace surfaces the full record plus the stage-transition controls (target stage / QC status / NAFDAC status / a `quality_notes` textarea) inline — that textarea is a genuine gap fix: the field was wired through every `transitionStage` call from day one but no UI anywhere ever set it, on either the old flat table or the Stage Board Kanban. Stage Board stayed untouched (Kanban, `ExpiryTab` precedent) — deliberate coexistence with the new inline controls, same reasoning as CRM's bulk-browse-vs-`CustomerWorkspace` coexistence (§9.8). Deliveries and Stock Orders tabs were **100% hardcoded mock data** (`DLV-1023`, `SO-8821`, etc., zero API calls) duplicating two pages that already work for real — resolved the same way as the AR Aging consolidation (§9.7): each replaced with a `KpiStrip` (sourced from `GET /logistics/deliveries` and `purchaseOrdersSummary()` respectively) + a "View Full X →" link. "New Project" → `DetailSheet`, with its `supplier_name`/`assigned_staff_id` sentinel-based Selects converted to real `EntityAutocomplete`s — backed by client-side filtering over the already-fetched supplier/staff lists rather than a server search call, since neither `api.suppliers.list()` nor `api.staff.list()` take a query param (a deliberate, narrower use of `EntityAutocomplete`'s generic `fetchFn` than its `api.inventory.search`-backed uses elsewhere). The dead "Filter projects..." input is now a real `FilterBar` search box; the unused `STAGE_BOARD_PREFS_KEY` constant (no `localStorage` calls anywhere) was removed.

**`Suppliers.tsx`** → partial retrofit: `KpiStrip` for the 6 existing KPI cards, `DetailSheet` for "Add Supplier" (a real multi-field create form). No `FilterBar` — no existing filter UI to replace, and the 14-column table already shows effectively everything per row. The "View Metrics" `Dialog` stays as-is (already the correct short-lookup pattern).

**`PurchaseOrders.tsx`** → partial retrofit: `KpiStrip` for the 6 summary cards, `FilterBar` for the search input. The status filter stayed its existing pill-button row rather than becoming a `FilterBar` `Select` — it never had a sentinel-hack to begin with, so converting it would be a real UX change, not the mechanical swap `NafdacTab`'s was. No `DetailSheet` — confirmed zero create/mutate flow exists on this page. Also fixed a real bug found during research: the row-level "Overdue" badge and the backend-sourced "Overdue POs"/"Overdue Value" KPI cards used **different overdue definitions** — the row check compared full datetimes and only flagged `status === "open"`, while the backend's `_is_overdue` (`purchase_orders.py`) compares dates only and treats `open`/`pending`/`approved` as open. A PO due today, or one sitting in `pending`/`approved`, could show as on-time in the table while counting as overdue in the KPI cards. Added `isPoOverdue()` mirroring the backend's exact logic so the two can no longer disagree.

**New precedent**: this is the first round to add genuinely new list/read endpoints (`GET /logistics/deliveries`, `GET /logistics/riders`) as part of a retrofit rather than just consuming what already existed — justified because the frontend gap wasn't a styling problem, it was a missing data path. Both are pure additive reads against existing tables, no migration required.

**Also logged, not resolved** (same "log a bigger finding, don't scope-creep into resolving it" precedent as §9.9's three-way leads pipeline): `backend/app.py` implements a full `/controls/scope`, `/controls/cost`, `/controls/risk`, `/controls/change`, `/controls/rollup`, `/controls/audit/export` project-governance module (~400 lines) with **zero frontend consumers** anywhere in `ProjectControls.tsx` or elsewhere — only reachable via an AI chat tool. Independent of this retrofit; a future product decision on whether it needs a UI at all.

**Real bugs found and fixed (pre-existing, confirmed via research/live verification, not introduced this session)**:
1. `LogisticsMonitor.tsx` had no way to list existing deliveries or riders — both tabs silently discarded all real data on every page load (detailed above).
2. `LogisticsMonitor.tsx`'s "New Delivery" form 422'd on every submission — wrong payload shape entirely (detailed above).
3. `Operations.tsx`'s "Log Adjustment" 422'd on every submission — right values, wrong endpoint (detailed above).
4. `ProjectControls.tsx` offered a "Planning" project status that always 500'd server-side. Two layers turned out to disagree, discovered in two passes: `PROJECT_STATUS_ALLOWED` (`backend/src/constants.py`) excluded `"planning"` (fixed first) — but the *actual* gate on `POST /controls/projects` was a database CHECK constraint, `placeware_projects_status_check` (`015_project_controls_core.sql`), never updated to match and still rejecting the row after the Python-level fix. Live write-through verification caught the live 500 the static fix alone didn't resolve; fixed via `migrations/102_project_status_allow_planning.sql`, altering the constraint to `('planning', 'active', 'on_hold', 'completed', 'cancelled')`.
5. `ProjectControls.tsx`'s `quality_notes` field was passed through every stage-transition API call from day one but had no UI anywhere that could set it — not a broken call, but a feature that was silently never actually usable.
6. `PurchaseOrders.tsx`'s row-level overdue badge and its own KPI cards could disagree (detailed above).
7. **Found only during live verification of the new `GET /logistics/deliveries` endpoint** (§ above): it 500'd — silently, as an empty list, not a visible error — because `TableQuery.execute()` (`local_db.py`) swallows exceptions on plain `SELECT` actions and returns `Result([])` rather than re-raising (mutations *do* re-raise; this asymmetry is deliberate for reads generally, but it meant the endpoint's own bug produced no visible signal, only silently-wrong data). The actual cause: the new endpoint's `.select(...)` column list included `last_update`, a column the real `deliveries` table has never had. Removed it from the select.
8. **Same `last_update`-doesn't-exist bug, found by continuing to pull the thread**: `update_delivery_status` (used by the newly-wired "Update Status" action) and `start_delivery` (used by the newly-wired "Start" action) both tried to `UPDATE ... SET last_update = ...` on every call — these are mutations, so unlike #7 they *did* re-raise, meaning both actions 500'd on every use, unconditionally, since inception. A third call site in the GPS-ping geofence auto-delivery handler (`POST /logistics/deliveries/{id}/ping`) had the identical bug but wrapped in a swallowed `try/except`, so it silently failed to ever mark a delivery `delivered` by proximity detection — a real feature that has never worked. All three fixed by dropping the nonexistent column from their `UPDATE` payloads (`deliveries` has no `last_update`/`updated_at` column at all).

## 9.11 HR department — fabricated metrics removed, not just under-styled

User asked for HR next, specifically flagging "filler text and metrics" on HR cards that should stay blank until real data flows in. Research (full read of every HR-related file) found no literal placeholder content anywhere in the shipped app — no page renders fake names, IDs, or role labels. What research *did* find, confirmed with the user via `AskUserQuestion` before implementation, was three real issues: one page with genuinely fabricated metrics dressed up as real trend data, one page whose cards already show real data but omit fields the user wanted (ID, activity history), and one real backend bug (a UUID shown instead of a name). This round is a smaller, more surgical retrofit than Operations — one full retrofit, one partial, one page-level `PageHeader`/`DetailSheet` conversion, and a correctness pass on a fourth page that doesn't fit the List/Detail shape at all.

**`StaffDashboard.tsx` (`/staff/dashboard`) — fabricated metrics removed, not retrofitted.** This is a single user's personal dashboard (keyed by auth `subject`), not a governed collection-of-records workspace, so it was deliberately *not* pulled into the List/Detail/QuickActions shape — same reasoning that kept `LogisticsDashboard.tsx`/`OperationsSettings.tsx` untouched in the Operations round (§9.10). What it needed instead was honesty: its "Statistics" sidebar `change` badges (e.g. `+34%`) were arithmetic formulas run on today's task counts (`Math.min(activeCount * 7 + 12, 48)`), not derived from any stored prior period — there is no historical snapshot table for personal performance anywhere in this schema. The accompanying `Sparkline` components plotted mostly-hardcoded leading points (`[2, 3, 2, 4, 3, ...]`) with only the last value real. Removed both entirely; each stat row now shows one real current-value string ("X completed", "Y events", or "No tasks yet") with no invented trend or chart. The `ScoreGauge`/progress stat's hardcoded `72%`/`40%` fallback (shown whenever a user had zero tasks) was replaced with a real `0%` — confirmed live against a real zero-task account. A profile-blurb line that always rendered the literal string `"Open Tasks"` under the person's name (`{kpis[0]?.label || "Staff Member"}` — `kpis[0]` is unconditionally pushed with that label server-side, so the `"Staff Member"` fallback could never actually trigger) was removed rather than replaced with a guess, since no reliable job-title field exists at this call site.

**`StaffDirectory.tsx` (HR → Staff Directory tab) → full retrofit** (closest precedent: `ProjectControls.tsx`'s Active Projects tab). Its cards already showed real data (Name/Email/Department/Role/Status, sourced from `placeware_staff`) — not filler — but had no `staff_id` field and no way to see a staff member's activity history, exactly the "record has more content than the row shows" gap the standard's own decision rule (§9.5) calls out. Detail Workspace now surfaces the Staff ID plus a "Recent Activity" section (real timesheet entries via the newly-exposed `GET /timesheets/staff/{staff_id}`, which already existed on the backend but had no frontend consumer). Added `KpiStrip` (Total/Active/Inactive) and `FilterBar` (name/email search + department filter) — this tab had zero filter UI before. For rows sourced from the `sage_staff_snapshot` fallback (no live registry yet), the activity fetch correctly returns empty rather than erroring — an honest "no real activity recorded for this identity yet," per the user's own framing.

**`TimesheetsTable.tsx` (HR → Timesheets tab) → partial retrofit** (closest precedent: `PurchaseOrders.tsx`) — a flat log where every row already shows what's relevant, no per-row detail to surface. `KpiStrip` (Entries / Total Hours / Unique Staff Logged, client-derived) + `FilterBar` (department + staff-name search, previously absent).

**`HR.tsx`** — page-level retrofit matching every other top-level department page: plain `<h1>`/`<p>` header → `PageHeader` (icon `Users`, matching the Sidebar's own icon); "Add Staff" `Dialog` → `DetailSheet` (§5.2 precedent). `WorkforceDashboard.tsx` (Overview tab) got the mechanical `KpiStrip` swap for its 3 hand-rolled KPI cards; its bar chart stayed untouched (pure computed report).

**Real bug found and fixed (pre-existing, confirmed via live verification)**: `TimesheetsTable.tsx`'s "Staff" column always showed a raw `staff_id` UUID instead of a name, for every row, unconditionally. The frontend type (`TimesheetEntry.staff?.full_name`) had expected a joined field since the type was written, but `get_timesheets()` (`backend/src/services/staff_ops.py`) did a bare `select("*")` on `placeware_timesheets` with no join to `placeware_staff`. Fixed by batch-looking-up distinct `staff_id`s and attaching a `staff: {full_name}` object per row — mirroring the exact rider-enrichment pattern already used in `list_deliveries` (Operations round, §9.10) — which fixes it for both consumers of the function (`GET /timesheets` and `GET /timesheets/staff/{staff_id}`). Confirmed live: created a real staff member and two timesheet entries, both returned with `staff.full_name` populated correctly.

## 9.12 Compliance & QMS department — the final department, and the buggiest module found yet

Last department in the rollout. `Compliance.tsx` (7 tabs: Overview/Audits/Deviations/Maintenance/Recalls/SOPs/Documents) had zero adoption of any shared component and, on inspection, turned out to have the deepest bug surface of any department this session — worse than Operations (§9.10). Three **systemic** bugs — each independently capable of breaking the entire module on its own — compounded on top of each other, plus several field-mismatch bugs per tab, plus one confirmed dead duplicate of an already-working page.

**Systemic bug #1 — every QA-gated mutation 403'd, for every user, always.** `_require_qa()` (`compliance.py`) checked `user.get("role")` (singular) against `COMPLIANCE_QA_ROLES`, but the JWT only ever populates `roles` (plural, list) — the exact bug class already fixed in Finance (§9.6) and HR (§9.11), except here it gated all 15 mutation endpoints across Audits/Deviations/Maintenance/Recalls/SOP. Fixed with the same set-intersection pattern as `_require_finance`.

**Systemic bug #2 — 4 of 5 list tabs always showed zero records, regardless of real data.** Every list tab did `data?.data ?? (Array.isArray(data) ? data : [])`, but `list_audits`/`list_deviations`/`list_maintenance`/`list_recalls` return domain-keyed objects (`{"audits": [...]}` etc.), not `{data:[...]}` — the same bug class as `Leads.tsx`'s `Array.isArray` bug (§9.8). Only `SopTab` happened to match. Fixed by reading the correct key per endpoint and correcting the four wrong TS return types in `api-client.ts`.

**Systemic bug #3 — found only during live verification, not by reading the code: every single mutation in the file 500'd immediately after doing its real DB work, and every scheduled background PDF/certificate generation task silently never ran.** `audit_event()`'s real signature is `(event_type: str, details: dict, *, actor_id=..., ...)` — but all 15 call sites in this file called it as `audit_event(user, "event.type", {...})`: the decoded JWT dict as the first arg (should be the event-type string), the event-type string as the second (should be the details dict), and a third positional argument the function doesn't accept at all. `TypeError: audit_event() takes from 1 to 2 positional arguments but 3 were given`, raised *after* the real database write already succeeded and *after* `background_tasks.add_task(...)` was called in several handlers — meaning the underlying data was correct but every response was a 500, and because FastAPI's exception handler builds its own response rather than the one the background tasks were attached to, the scheduled PDF/certificate generation for recalls, audit reports, and maintenance certificates likely never fired either. This was caught live, registering test equipment: the request 500'd with the exact `TypeError` message. Fixed all 15 call sites to the correct argument order/count, matching the pattern already used correctly in `logistics.py`. Confirmed live end-to-end after the fix: equipment registration, audit start/complete (report generated, `report_document_id` populated), maintenance complete (certificate generated), and recall document generation all now return success and their background documents materialize.

**Systemic bug #4 — an unsupported Supabase-style embedded-relation `select()` syntax, unique to the Maintenance endpoints.** Five call sites used `.select("*, equipment_registry(...)")` (a PostgREST embedded-relation join), but this app's local `TableQuery` wrapper (`local_db.py`) is a flat SELECT-column-list builder with zero join/embed parsing — the string was passed through literally into the SQL, producing `SELECT *, equipment_registry(...) FROM ...`, which Postgres rejects (a table isn't a callable function). Because `TableQuery.execute()` swallows SELECT-action exceptions and returns an empty result rather than re-raising (the exact same silent-failure mechanism documented in the Operations round, §9.10 finding #7), the three list endpoints (`list_maintenance`, `overdue_maintenance`, `upcoming_maintenance`) always silently returned zero rows, while the two mutation endpoints that used `.single()` on the same broken query (`complete_maintenance`, `generate_maintenance_certificate`) always 404'd ("Schedule not found") since an empty result plus `.single()` behavior collapses to `{}`. Fixed by adding `_enrich_maintenance_with_equipment()`/`_fetch_maintenance_with_equipment()` helpers that do the join in Python via a batched follow-up query — the same enrichment pattern used for delivery/rider (Operations), staff/timesheet (HR), and this round's own audit/report-URL enrichment — attaching the result under an `equipment_registry` key so the one downstream consumer that already expected that shape (`_generate_maintenance_cert_bg`, which builds the certificate PDF) needed no changes.

**Per-tab field-mismatch bugs** (each independent of the systemic bugs above):
- **Maintenance "Complete" dialog** sent `completed_by`; backend requires `performed_by`. **Filter pills** ("All/Overdue/Upcoming") posted a `?filter=` query param the endpoint has never accepted at all (its real filter param is `status`) — selecting either pill silently did nothing, always returning the unfiltered list.
- **Audits "Complete" dialog** sent `findings`/`recommendations` as plain strings against a `List[str]`-typed field (Pydantic 2 rejects a bare string for `List[str]`, no v1 auto-split) — fixed by newline-splitting into arrays. A "Compliance Score" input was silently dropped — not a rename, a removal, since `AuditComplete` has no field to hold it (the sibling "Generate Report" dialog's `score` field is real and unaffected). **Audits table rows** read `audit_title`/`scheduled_date`/`report_url` — none exist; real columns are `audit_type` and `month_due`+`year` ints, and `report_url` needed the new backend enrichment (bug #4's sibling fix) since only `report_document_id` (an FK) existed.
- **Recalls create form** collected `severity` and a "NAFDAC notified" checkbox that neither `RecallCreate` nor `recall_cases` had fields for — both silently discarded on every submission. For a pharma recall, whether the regulator was notified is a genuine compliance record; fixed via `migrations/103_recall_severity_nafdac_notified.sql` (two additive, defaulted columns) rather than removing the UI fields. Confirmed live: a recall created with `severity=critical, nafdac_notified=true` now persists and returns both values correctly, and a recall row created *before* the migration correctly inherited the column defaults.
- **SOP table rows** read `sop_code`/`next_review_date` — neither exists on `sop_registry`; the real id column is `sop_id`, and "next review" has to be derived client-side from `last_reviewed_at` (or `effective_from`, if never reviewed) `+ review_interval_days`.
- **Overview tab** read `audits_overdue`/`maintenance_overdue` — real keys are `overdue_audits`/`overdue_maintenance`. A "Score Deductions" card expected a labeled breakdown array the backend never returns (only the single reduced score); fixed by computing the breakdown client-side from the response's own real counts using the exact same weights `compliance_status()` uses internally — no fabrication, no backend change. A "Recent Compliance Activity" card expected data no endpoint has ever provided and was removed outright (unlike the deductions card, no real data source exists to derive it from). `missed_activities` — real, already computed, previously shown nowhere — now has a `KpiStrip` slot.

**A real duplication, resolved not just logged** (matching the AR Aging / Deliveries-Stock-Orders precedent, §9.7/§9.10): `DeviationsTab` and `QualityControl.tsx`'s already-working `CapaTab` were two independent UIs over the same `deviation_reports` table via two different routers (`/compliance/deviations*` vs `/qc/deviations*`), presented as two sibling top-level sidebar entries with identical role gates. `CapaTab`'s field names correctly matched the schema and its role check wasn't broken; `DeviationsTab` was 100% non-functional in every direction (couldn't list — bug #2; couldn't create — its form's fields don't exist anywhere on the real model, moot once consolidated). Resolved by replacing `DeviationsTab` with a `KpiStrip` (sourced from `GET /qc/deviations`, the same data `CapaTab` already fetches) + a "View Full CAPA & Deviations →" link — but unlike a pure coarser-duplicate consolidation, this one had a genuine unique capability worth preserving: PDF "Generate Report" export via `DocumentEngine`. That action was ported into `CapaTab`'s Detail Workspace as a new button (`api.compliance.generateDeviationReport`, now functional post bug #3's fix) rather than dropped — a new variant on the consolidation pattern: *merge the duplicate's one real feature into the canonical page, don't just redirect away from it*. Confirmed live: created a real deviation via `CapaTab`'s own create path, then successfully generated its PDF report via the ported button's underlying endpoint.

**Also logged, not built** (matching the Operations round's `/controls/*` precedent, §9.10): `compliance_activity_log` has full CRUD in the router (`/compliance/activities*`) with zero frontend consumer — no client method even exists. `equipment_registry` similarly has real endpoints, an unused `api.compliance.equipment()` client method, and no dedicated UI tab (though this round's live verification used `POST /compliance/equipment` directly to seed test data, confirming it works). Both are real backend capability with no frontend surface — out of scope to build this round.

**Minor logged-not-fixed observation**: `initiate_recall` sets `created_by: user.get("username")`, but this app's JWT payload doesn't carry a `username` field (only `sub`/`roles`) — every recall's `created_by` is silently `null`. Same class of attribution gap as the Frontdesk round's logged (not fixed) `create_invoice` actor-id issue — functional but loses audit attribution; out of scope for this pass.

**Fully deployed and live-verified**: `python -m py_compile`, `npm run build:client` + `npx tsc --noEmit` (zero new errors across every touched file), one new migration (103) applied. Backend redeployed twice — once for the planned fixes, once more after live testing surfaced bug #3 (`audit_event` arity) that neither research nor static checks had caught, since it only manifests at runtime on the success path of a mutation. Full write-through chain confirmed on real data: registered equipment → seeded a maintenance schedule row → listed it with real joined equipment details (previously always empty) → completed it (certificate generated, next date correctly advanced, equipment's own `last_maintenance_date` updated) → seeded an audit → started → completed with array-shaped findings (report generated, `report_url` resolved) → created a recall with severity+NAFDAC-notified (both persisted) → generated its document pack → created a real deviation via `CapaTab` → generated its PDF report via the newly-ported button. Every one of these previously failed at a different layer (role check, response-shape, field-name, or the `audit_event` arity bug) — all now work end-to-end.

**This closes out the ACE Workspace Standard department rollout** (§9.4's checklist) — Frontdesk, QualityControl, Finance, CRM, Operations, HR, and now Compliance & QMS are all assessed and retrofitted where the shape called for it.

---

# Chapter 10 — Universal Customer Workspace

## 10.1 Origin (second pattern import)

Second import from the same RoyanHealth source docs as Chapter 1, this time from the "Patient Context Engine" (`backend/docs/Latestmods-TB/Nl-Data-mod/Data Engine/data-engine2.md` §3, and `data-engine.md`'s exact `GET /patient/{id}/context` shape) and `NL-Master-guide/Synbot Architectural Standard.md`'s SHAS-003 "Universal Clinical Workspace," specifically its closing "Architect's Recommendation: Evolve from CPRS to the Patient Context Engine" section. The reusable idea: one aggregated backend context object (not many separate calls) consumed by a single workspace UI whose Quick Actions panel reuses the same role-gated action components the rest of the app already has, rather than rebuilding them per-surface.

## 10.2 Translation: Customer Context Engine over existing data

This is a context-engine-*over-existing-data* approach, not a new aggregation service: `GET /crm/customers/{id}/360` (`backend/src/routers/crm_360.py`, already built for `CRM.tsx`'s read-only 360 dialog) is extended additively with an `orders` key, joined through the `frontdesk_walk_ins.customer_id` bridge (migration 100). No new aggregation infrastructure.

## 10.3 The identity bridge

Three previously-disconnected "customer" identity systems existed — the CRM `customers` table, Frontdesk's free-text `frontdesk_walk_ins` registry, and the Sage silver-layer `v_customers` view — with no shared key between them. Bridged forward-only via `frontdesk_walk_ins.customer_id → customers.id`, populated by `POST /frontdesk/customers/{id}/quick-request`. Historical walk-ins are not backfilled (no reliable match key exists — free-text name/phone on both sides, unnormalized) — "Recent Orders" reflects orders raised via the Workspace going forward, not full historical Frontdesk history, until a future "link existing walk-in" action is built.

## 10.4 Caching — deferred, documented not built

The source doc's Patient Context Engine specifies a ~10-minute Redis cache. This app has no caching infrastructure anywhere today (the only mention of Redis in `backend/src` is `middleware.py`'s `rate_limit()` docstring — "For MVP only. Replace with Redis... later"). Introducing new infra for one endpoint is out of proportion to this slice. Revisit only if `/crm/customers/{id}/360` shows up as a real, measured latency problem.

## 10.5 Reuse over rebuild: `InvoiceActionPanel`

The QC/Finance/Dispatch action panel `InvoicesTab` already had was extracted to `SynbotUI/client/components/workspace/InvoiceActionPanel.tsx` so the Centralized Customer Workspace and `InvoicesTab` share identical mutation logic — a correctness concern for financial/QC actions, not just DRY. Small presentation-only helpers (`fmt`/`fmtDate`/`StatusPill`) were deliberately *not* extracted in this pass (low drift risk, unlike mutation logic) — logged as a future candidate once a third consumer exists, same reasoning already applied to deferring the 3-column grid wrapper (Chapter 8).

## 10.6 Rollout

Narrow slice: one new page (`SynbotUI/client/pages/CustomerWorkspace.tsx`, route `/customers/workspace`), two new endpoints (`GET /crm/customers/search`, `POST /frontdesk/customers/{id}/quick-request`), one additive extension (`crm_360.py`'s `orders` key). Zero changes to `CRM.tsx`'s existing 360 dialog behavior. `InvoicesTab`'s only change is the `InvoiceActionPanel` extraction, a confirmed pure refactor (same mutations, same payloads, same toasts).
