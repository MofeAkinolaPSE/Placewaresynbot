# ACE Customer Receipts & Accounts Workspace

**Version:** 1.0

**Platform:** ACE / Placeware Nigeria Limited

**Prepared By:** Placeware Engineering

**Delivers:** `ACE-Workspace-Standard.md`, applied to the Customer Receipts & Accounts workspace — the first workspace built to that standard.

---

# Chapter 1 — Purpose & Origin

A short meeting-minutes transcript (`backend/docs/Latestmods-TB/NL-Master-guide/Meetiing mintues.txt`) describes an accounts staff member's current Sage 50 workflow: invoices are raised from a US entity, customers make payments, the staff member checks the payment against a bank statement and records ("pledges"/posts) it against the customer's account — "the receipts part of it." The explicit ask from the interviewer: *"we want to move all the features you have on Sage to that new platform... but easier, more fine-tuned, and more direct."*

This is the missing write-side counterpart to `finance.py`'s existing read-only AR endpoints (`GET /finance/ar/aging`, `POST /finance/ar/match`) — nothing in ACE today lets a user record a customer payment against an invoice.

## 1.1 Non-breaking guarantee

Nothing existing is modified. `sage_ar_snapshot` and `v_ar_invoices` are read-only inputs, never written to. `CRM.tsx`, `Frontdesk.tsx`, `FinanceAR.tsx`, `SalesCRM.tsx`, `QualityControl.tsx`, `FinanceVendorPayments.tsx`, and every existing backend router are untouched. The only edits to existing files are pure additions: one router registration in `app.py`, one nav child in `Sidebar.tsx`, one route in `App.tsx`, and new methods appended to `api-client.ts`'s existing `finance` object.

## 1.2 Operational note: coexistence with Sage 50 during transition

`sage_invoices_cache` (migration `080`, populated by `sage_sync_engine.py`'s live Sage Bridge sync) already carries its own `amount_paid`/`is_paid` fields, reflecting payments entered directly in Sage 50 — but this table is write-only today (no router reads it), so it is not part of any workflow users currently see, and this feature does not build on it. `sage_ar_snapshot.balance` (the CSV/DAT batch-import path `finance.py`'s existing AR endpoints already use) already reflects Sage-side payment entry on each re-import. During the transition period, if accounts staff record a payment directly in Sage 50 **and** also record it here, the payment isn't double-counted in `true_outstanding_balance` — Sage's own recalculated balance is the `sage_outstanding_balance` input either way — but staff should be trained to record each payment in **one** place, not both, to avoid confusion about which system is authoritative for a given receipt.

---

# Chapter 2 — Canonical Model

## 2.1 Domain translation (extends `ACE-Workspace-Standard.md`)

| SHAS-107 (hospital) | ACE Customer Receipts |
|---|---|
| Charge → Invoice → Payment → Receipt → Reconciliation | Invoice (Sage import) → Receipt (recorded) → Allocation → true outstanding balance |
| Payment methods (Cash/Card/Bank Transfer/Mobile/HMO/Split) | `cash/card/bank_transfer/mobile_payment/corporate_account/split_payment/cheque/pos` (cheque/POS added for Nigerian B2B — confirm with accounts team) |
| "Payments become immutable after confirmation" | `ar_receipts.status`: `posted → voided` only, no edit endpoint exists |
| Discounts/adjustments require Reason + Approver, never overwrite | Void requires a reason (`void_reason`), audited via `audit_event()`; the original receipt is never edited |
| Revenue Reconciliation (daily collections, receivables, outstanding balances) | KPI strip (today's total/count, unapplied total, voided-30d count) + `v_ar_receivables_open` |

## 2.2 Tables (migration `098_ar_receipts.sql`)

`ar_receipts` — one row per payment. `ar_receipt_applications` — allocation lines (a receipt may span multiple invoices). `v_ar_receivables_open` — `true_outstanding_balance = sage_outstanding_balance - SUM(unvoided applications)`, built on `v_ar_invoices` (086/087).

### Engineering Decisions

- `receipt_number` is a generated/stored column (`'RCT-' || upper(right(id::text,8))`), matching this app's existing convention of no sequential-document-number infrastructure (`fin_vendor_payment_requests` has none either).
- No per-row void flag on `ar_receipt_applications` — void state lives only on the parent `ar_receipts.status`, a single source of truth.
- `invoice_id` is a soft (text) relationship, matching the rest of this schema — no FK to `sage_ar_snapshot`, an append-only batch-import table.

### Implementation Requirements

- `backend/migrations/098_ar_receipts.sql`

### Acceptance Criteria

- A Sage re-import (new `sales_invoices` batch) leaves `ar_receipts`/`ar_receipt_applications` row counts unchanged.
- `v_ar_receivables_open.true_outstanding_balance` recomputes correctly against the new batch while still subtracting existing receipts.

### Developer Checklist

- [ ] Migration applies cleanly (idempotent, `IF NOT EXISTS` throughout)
- [ ] `sage_ar_snapshot` has zero write references anywhere in this feature

---

# Chapter 3 — API

Router `backend/src/routers/ar_receipts.py`, prefix `/finance/ar/receipts`, all endpoints behind `_require_finance` (imported from `finance.py` — the same cross-module pattern `finance.py` itself already uses for `_latest_batch_for_table`).

| Method | Path | Purpose |
|---|---|---|
| GET | `/finance/ar/receipts` | Paginated list + filters + server-computed `summary` |
| GET | `/finance/ar/receipts/{id}` | One receipt + allocations |
| POST | `/finance/ar/receipts` | Create + post (immutable after confirmation) |
| PATCH | `/finance/ar/receipts/{id}/void` | Terminal reversal, reason required |
| GET | `/finance/ar/receipts/customers/search` | Autocomplete source |
| GET | `/finance/ar/receipts/customers/{id}/open-invoices` | Allocation targets, oldest-due-first |

### Engineering Decisions

- Post validates `sum(applications) <= amount` and each allocation `<= true_outstanding_balance` at write time (409 on violation) — over-application is rejected, not silently clamped.
- Void uses the same role gate as posting (`_require_finance`) — not a stricter role — matching the existing Vendor Payments precedent where cancel uses the same gate as everything else. The required reason plus audit trail is the mitigating control.
- No realtime/WebSocket wiring (see `ACE-Workspace-Standard.md` Chapter 7).

### Implementation Requirements

- `backend/src/routers/ar_receipts.py`, registered in `backend/app.py`.

### Acceptance Criteria

- All 6 endpoints reject non-finance roles with 403.
- Attempting to edit a posted receipt's core fields has no endpoint to call (404/405).

### Developer Checklist

- [ ] `POST` rejects over-allocation with 409
- [ ] `PATCH .../void` rejects a second void attempt (already-terminal state)
- [ ] `audit_event()` called for both post and void

---

# Chapter 4 — Frontend

`SynbotUI/client/pages/ARReceipts.tsx`, route `/finance/ar/receipts`, built from the Chapter 8 shared components in `ACE-Workspace-Standard.md`: `PageHeader` + `KpiStrip` + `FilterBar` + a 3-column body (List Panel / inline Detail Workspace / Quick Actions) + one `DetailSheet` (Record Receipt) + one `Dialog` (Void, mirroring `FinanceVendorPayments.tsx`'s reject-with-note pattern).

### Engineering Decisions

- The Record-Receipt flow is the only `Sheet` usage — an ephemeral task. Viewing a selected receipt is inline in the Detail Workspace — persistent page content, per the Modal/Panel Priority hierarchy.
- Client-side mirrors the backend's allocation-sum validation (a "remaining to allocate" indicator) before submit, so users see the constraint before the round trip, not just after a 409.

### Implementation Requirements

- `SynbotUI/client/pages/ARReceipts.tsx`
- `App.tsx`: `/finance/ar/receipts` route
- `Sidebar.tsx`: "Customer Receipts" nav child under Finance, after "AR & Alerts"
- `ProtectedRoute.tsx`: no change — the existing `/finance` rule already covers this route
- `api-client.ts`: `listArReceipts`/`getArReceipt`/`createArReceipt`/`voidArReceipt`/`searchArReceiptCustomers`/`getCustomerOpenInvoices` under the existing `finance` object

### Acceptance Criteria

- `/finance/ar/receipts` loads for `admin`/`finance`, redirects other roles.
- Recording a receipt: customer autocomplete → open invoices load progressively → allocation validates client-side → list/detail refresh via query invalidation.
- Voiding requires a non-empty reason; the Void button disappears once voided.

### Developer Checklist

- [ ] KPI strip numbers match a manual sum against the full dataset
- [ ] No existing page's behavior changed (regression pass — see Chapter 5)

---

# Chapter 5 — Verification & Rollout

## 5.1 Phase A — backend only (curl-checkable)

| # | Check | Expected |
|---|---|---|
| 1 | `GET /finance/ar/receipts` | `summary` block present, independent of pagination |
| 2 | `POST /finance/ar/receipts` against a real imported invoice | 201; both tables written |
| 3 | Balance reduced, snapshot untouched | `true_outstanding_balance` drops by the applied amount; `sage_ar_snapshot.balance` unchanged |
| 4 | Re-import a `sales_invoices` batch, re-check | Receipts/applications unchanged; balance recomputes against the new batch |
| 5 | `PATCH .../void` then re-check | Balance restored; `status=voided`, `void_reason` populated |
| 6 | Over-application | 409 |
| 7 | Edit a posted receipt | No such endpoint exists |
| 8 | Autocomplete | Known-good customer found; garbage/blank rows absent |
| 9 | Role gate, non-finance role | 403 on all 6 endpoints |

## 5.2 Phase B — frontend

- Route loads for `admin`/`finance`, redirects otherwise.
- Full record-receipt flow works end to end; void flow requires a reason.
- **Regression check**: every existing `/finance/*` page and endpoint behaves identically to before this feature.

## 5.3 Manual checklist

- [ ] Confirm the payment-method enum with the finance/accounts team (cheque/POS added as an assumption).
- [ ] Spot-check `true_outstanding_balance` by hand in `psql` against one known invoice + receipt.
- [ ] Confirm "Customer Receipts" is the terminology accounts staff would actually use.
- [ ] Brief accounts staff on the single-entry-point rule during the Sage 50 transition period (Chapter 1.2).

---

# Appendix A — Endpoint Reference

See Chapter 3.

# Appendix B — curl Quick Reference

```bash
TOKEN="<bearer token>"
BASE="http://localhost:8000"

curl -H "Authorization: Bearer $TOKEN" "$BASE/finance/ar/receipts"
curl -H "Authorization: Bearer $TOKEN" "$BASE/finance/ar/receipts/customers/search?q=acme"
curl -H "Authorization: Bearer $TOKEN" "$BASE/finance/ar/receipts/customers/<customer_id>/open-invoices"
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"customer_id":"<id>","amount":5000,"payment_method":"bank_transfer","applications":[{"invoice_id":"<inv>","amount_applied":5000}]}' \
  "$BASE/finance/ar/receipts"
curl -X PATCH -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"reason":"duplicate entry"}' \
  "$BASE/finance/ar/receipts/<id>/void"
```
