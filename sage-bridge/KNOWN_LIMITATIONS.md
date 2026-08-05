# Sage Bridge — Known Limitations

What this system cannot do, or cannot guarantee, given the Windows 7 / Sage 50
2013 constraints. Read before going live.

---

## 1. Unverified schema assumptions — **highest risk**

`sage_schema.py` holds table and column names taken from canonical Peachtree
naming. **They have not been verified against the client's company file.** Real
names come from the `.DDF` files and vary between Sage versions.

- **Impact:** if they differ, invoice detection fails entirely at startup.
- **Detection:** `verify_onsite.py` reports the mismatch precisely; it does not
  fail silently.
- **Mitigation:** every assumption is isolated in one file. Correcting it is a
  single edit with no logic changes.
- **Resolve by:** running `verify_onsite.py --report` on the client machine and
  reconciling. Budget time for this on the first visit.

---

## 2. Detection latency is bounded, not instant

Invoices are detected by polling, not by a Sage event hook — Sage 50 2013
exposes no push notification.

- Typical: **≤30 s** (`WATCHER_POLL_SECONDS`).
- Worst case: **≤5 min** (`WATCHER_FULL_SCAN_SECONDS`), if Pervasive does not
  update the `.DAT` mtime promptly.

Not fixable within the constraints. Lower the intervals to trade CPU for
latency. Sub-second sync is not achievable.

**Why the second layer exists:** Pervasive holds `.DAT` files open and flushes
lazily, so mtime is an unreliable trigger. The periodic full scan runs
regardless of mtime, so a missed mtime change *delays* an invoice — it never
loses it.

---

## 3. Deleted and voided invoices — detected, with a deliberate delay

The forward scan walks from a watermark and cannot see deletions. A
**reconciliation sweep** now covers that gap: it enumerates every invoice ID in
Sage, diffs against what the bridge has synced, and emits `record_deleted` for
the difference. SynBot soft-deletes (`is_voided`) across the invoice cache,
stock movements, sales lines and GL entries, then recomputes the customer's AR
balance.

Residual limitations:

- **Latency is up to `RECONCILE_INTERVAL_SECONDS` (default 24 h).** The sweep is
  a full-table enumeration, so it cannot run at poll frequency on this hardware.
  A void is invisible to SynBot until the next sweep. Force one with
  `POST /sync/reconcile`.
- **The sweep refuses to act when it cannot trust its input.** Three guards —
  abort on any read error, abort on an empty enumeration, abort above
  `RECONCILE_MAX_DELETE_RATIO` (default 10%) — mean a genuine bulk void needs an
  operator to raise the ceiling deliberately. That is the intended trade: a
  false delete is unrecoverable downstream, a delayed one is not.
- **Voids that keep the row** and flip a status column were already handled as
  edits (the content fingerprint changes). Unchanged.
- **Only invoices.** Deletion of customers, vendors or inventory items is still
  undetected.

---

## 4. What the Sage 50 2013 SDK genuinely cannot do

`sdk_client.py` is now written against the real API, verified member-by-member
against `Sage.Peachtree.API` 2013.0.0.826 by `verify_sdk_api.py` (189 names).
These are hard gaps in the SDK itself, not omissions in the bridge:

| Capability | Status | Why |
|---|---|---|
| **Create vendor bills** | Not possible | `PurchaseInvoice` has no `Save()`. Returns **501**. Enter in Sage, or post via `/journal`. |
| **Payroll** | Not available | No payroll factory exists on `Company.Factories`. `sdk_get_payroll_checks` returns `[]`. Read `PAYROLL.DAT` over ODBC if needed. |
| **Company address / phone / tax ID / fiscal year** | Not available | There is no `CompanyInformation` object. `CompanyIdentifier` gives name, path, database, schema version only. Fields are returned empty and listed in `_unavailable`. |
| **Employee detail** | Minimal | Sage's `Employee` is ID, Name, Email, PhoneNumbers, IsInactive, IsSalesRepresentative. No address, hire date, pay type, or department. |
| **Inventory cost** | Not exposed | A costing-method computation in Sage, not a property. Reported as `0.0` rather than guessed. Sales price comes from `PriceLevels[0]`. |
| **Per-line tax amounts** | Not available | `SalesInvoiceSalesLine.SalesTaxType` is an integer *code*. Tax is computed at invoice level (`SalesTaxAmount`). Per-line tax is always `0.0`. |
| **Invoice ship date** | Not available | `SalesInvoice` has no ship date; only `SalesOrder` does. Always `None`. |

### Invoice identity differs between the two paths

The SDK's primary key for a transaction is a **Guid** (`invoice.Key.Guid`). The
ODBC scan keys on `ARTRANS.TRANSNO`. `sdk_get_invoice()` therefore matches on
*either* the Guid or `ReferenceNumber`, so the two paths stay interchangeable.
If the client's `REFERENCE` column does not correspond to the SDK's
`ReferenceNumber`, SDK lookups from the ODBC-driven scan will miss and every
invoice will fall back to the partial ODBC record. **Confirm this on site** —
it is the one remaining assumption linking the two halves.

### Full-table loads

`factory.List()` + `.Load()` materialises the whole entity set; the SDK's
`LoadModifiers` filtering was not used because filter expressions could not be
tested without a company file. On a company with years of history this is the
most likely performance problem. Measure it on site before raising
`WATCHER_SCAN_PAGE_SIZE`.

---

## 5. SDK authorization cannot be automated

The Sage 50 SDK requires a one-time interactive consent dialog. A Windows
service cannot answer it.

- **Impact:** first install needs a human at the desktop (INSTALL.md §3.4). The
  prompt can reappear after a Sage upgrade.
- **Degraded mode:** without it the bridge runs ODBC-only. Invoices still sync,
  marked `completeness=partial`, **without tax**. SynBot logs a warning per
  partial invoice.

---

## 6. Duplicate protection requires the SynBot migrations

Migration `071_sage_bridge_idempotency.sql` creates `placeware_sage_event_log`.
**Without it, the dedupe check fails open and duplicates become possible.**

`097_sage_bridge_voids_and_downstream.sql` is equally required: it adds the
`is_voided` columns, `sage_gl_entries`, `sage_sales_lines` and the customer AR
rollup columns. Without it, void handling and the finance/sales/customer
downstream writes all fail — and because those writes now raise rather than
log-and-continue, the events stay pending in the outbox rather than being
silently half-applied. Apply both.

The failure is deliberate: the check fails *open* (processes the event) rather
than *closed* (drops it), because reprocessing is recoverable and dropping is
not. But it means a missing migration silently weakens the no-duplicate
guarantee to "usually". Apply it.

---

## 7. Single-writer assumption

One bridge instance per Sage company. Two pointed at the same company file
would both scan and both enqueue.

Deduplication would still prevent double-*application* in SynBot (same
deterministic `event_id`), but they would fight over the watermark and waste
resources. Do not run two.

---

## 8. What the tests do and do not prove

58 bridge tests plus 6 SynBot webhook tests, all against fakes. Honestly scoped:

**Proven by tests here (real, verifiable):**

- Event ID determinism and content sensitivity
- Watermark/event atomicity, including rollback on failure
- Crash recovery across process restart, with real SQLite files
- Retry backoff, the ~10 h retry window, permanent-vs-transient error handling
- 409 handled as success
- Failed events retained and replayable, never deleted
- Field-level extraction accuracy, inventory sign convention, payment status
- Delivery against a real HTTP server that 503s, 403s and disappears
- Void detection, tombstoning, and delete-event ID stability
- All three reconciliation guards (partial read, empty read, bulk ceiling)
- Watcher liveness reporting — a watcher that never started reports unhealthy
- **The receiver honours the no-loss contract**: a failed apply returns 5xx and
  does *not* record the `event_id`, so the bridge retries instead of dropping.
  Verified by reverting the fix and confirming the tests fail.

**Proven against the REAL Sage assembly (2013.0.0.826):**

- The SDK loads, and all 400 types resolve — so the assembly resolver finds
  every dependency in the Peachtree install (`Sage.Peachtree.Domain` and the
  rest live in the program root, not beside the DLL in `API\`)
- **Every one of the 189 type / property / method names `sdk_client.py` calls
  exists in the assembly** — `verify_sdk_api.py`, runnable on any machine with
  Sage installed, no company file needed
- 32-bit Python 3.9 loads the X86 assembly; the bitness guard fires correctly
  on a 64-bit interpreter

**NOT proven — needs the client machine:**

- Real Pervasive ODBC connectivity and driver bitness
- **Whether the table/column names are correct** (see §1)
- SDK **authorization** — `RequestAccess` needs a real company and a human
- Whether the *values* are what we expect. The API surface is verified; that a
  property exists does not prove it is populated the way we assume
- **Whether the ODBC `TRANSNO` matches the SDK `ReferenceNumber`** (see §4) —
  the assumption linking the two halves
- Extraction accuracy against *real* invoices — mock data is representative,
  not real
- Behaviour under a real Sage upgrade or company-file lock
- Performance of full-table `List()` + `Load()` against years of history (§4)

`verify_onsite.py` covers each of these as a checklist on site.

---

## 9. Security constraints

| Item | Status |
|---|---|
| `.env` in plaintext | Windows DPAPI would need a decrypt step in the service account; ACLs (INSTALL.md §3.5) are the practical mitigation. |
| HTTP on the LAN | Sage 50 2013 on Win7 has no TLS story. Bridge listens on plain HTTP; keep it on a trusted LAN and firewall port 7070 to the SynBot host only. |
| Windows 7 is EOL | No security updates since Jan 2020. Isolate this machine; do not use it for browsing or email. Outside this project's scope but the largest real risk. |
| No rate limiting | Bridge assumes a trusted LAN. API-key auth only. |

---

## 10. The GL mirror is a mirror, not a ledger

`sage_gl_entries` reproduces the standard sales-invoice shape — revenue per GL
account, tax, and the receivable as the balancing side — so finance reporting
has account-level figures instead of only invoice totals.

It is **not** a double-entry engine. Sage remains the book of record. Anything
beyond the plain sales-invoice shape (multi-currency, deferred revenue, job
costing splits, manual adjusting entries) is not modelled here and must be read
from Sage directly. Do not reconcile statutory accounts from this table.

---

## 11. Deliberately unchanged

- **`/invoices` list endpoint still returns ODBC header rows.** SynBot's
  pull-based paths use it; the new push path carries full records instead.
  Changing it would break existing consumers for no gain.
- **Non-invoice entities still use change-pings.** Customers, vendors,
  inventory etc. keep the original ping-then-pull flow. Only invoices were in
  scope for full extraction. They now carry `event_id`s, so they are
  deduplicated too.
- **ODBC-for-reads / SDK-for-writes split.** Sound design; kept.
- **`data_changed` pings still run as background tasks.** They carry no data, so
  a lost ping costs a sync cycle rather than a record. Only the data-carrying
  events (`record_upserted`, `record_deleted`) were made synchronous.

---

## 12. Recommended follow-ups

1. **Extend full extraction** to sales orders and payments, once the invoice
   path is proven on site.
2. **Alerting** — `/health` now reports `degraded` when the watcher is not
   running, stalled, or the outbox has failures. Nothing watches it. Point a
   monitor at it so a stalled sync pages someone. This is the largest remaining
   operational gap.
3. **Extend reconciliation** to customers, vendors and inventory (§3).
4. **Replace Windows 7** — the real long-term fix for §9.
