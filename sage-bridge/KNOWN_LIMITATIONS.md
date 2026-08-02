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

## 3. Deleted and voided invoices are not detected

The scan walks *forward* from a watermark, so it sees new and updated rows but
not deletions.

- **Impact:** an invoice voided in Sage stays in SynBot's cache as active.
- **Workaround:** if Sage marks voids with a status column rather than deleting
  the row, the change is picked up as an edit. Confirm the client's void
  behaviour on site.
- **Proper fix:** a periodic full reconciliation sweep comparing ID sets. Not
  implemented — it needs the verified schema first.

---

## 4. SDK authorization cannot be automated

The Sage 50 SDK requires a one-time interactive consent dialog. A Windows
service cannot answer it.

- **Impact:** first install needs a human at the desktop (INSTALL.md §3.4). The
  prompt can reappear after a Sage upgrade.
- **Degraded mode:** without it the bridge runs ODBC-only. Invoices still sync,
  marked `completeness=partial`, **without tax**. SynBot logs a warning per
  partial invoice.

---

## 5. Duplicate protection requires the SynBot migration

Migration `071_sage_bridge_idempotency.sql` creates `placeware_sage_event_log`.
**Without it, the dedupe check fails open and duplicates become possible.**

The failure is deliberate: the check fails *open* (processes the event) rather
than *closed* (drops it), because reprocessing is recoverable and dropping is
not. But it means a missing migration silently weakens the no-duplicate
guarantee to "usually". Apply it.

---

## 6. Single-writer assumption

One bridge instance per Sage company. Two pointed at the same company file
would both scan and both enqueue.

Deduplication would still prevent double-*application* in SynBot (same
deterministic `event_id`), but they would fight over the watermark and waste
resources. Do not run two.

---

## 7. What the tests do and do not prove

The 47 automated tests run against fakes. Honestly scoped:

**Proven by tests here (real, verifiable):**

- Event ID determinism and content sensitivity
- Watermark/event atomicity, including rollback on failure
- Crash recovery across process restart, with real SQLite files
- Retry backoff, the ~10 h retry window, permanent-vs-transient error handling
- 409 handled as success
- Failed events retained and replayable, never deleted
- Field-level extraction accuracy, inventory sign convention, payment status
- Delivery against a real HTTP server that 503s, 403s and disappears

**NOT proven — needs the client machine:**

- Real Pervasive ODBC connectivity and driver bitness
- **Whether the table/column names are correct** (see §1)
- Real Sage SDK loading, authorization and session behaviour
- Extraction accuracy against *real* invoices — mock data is representative,
  not real
- Behaviour under a real Sage upgrade or company-file lock
- Performance against a company file with years of history

`verify_onsite.py` covers each of these as a checklist on site.

---

## 8. Security constraints

| Item | Status |
|---|---|
| `.env` in plaintext | Windows DPAPI would need a decrypt step in the service account; ACLs (INSTALL.md §3.5) are the practical mitigation. |
| HTTP on the LAN | Sage 50 2013 on Win7 has no TLS story. Bridge listens on plain HTTP; keep it on a trusted LAN and firewall port 7070 to the SynBot host only. |
| Windows 7 is EOL | No security updates since Jan 2020. Isolate this machine; do not use it for browsing or email. Outside this project's scope but the largest real risk. |
| No rate limiting | Bridge assumes a trusted LAN. API-key auth only. |

---

## 9. Deliberately unchanged

- **`/invoices` list endpoint still returns ODBC header rows.** SynBot's
  pull-based paths use it; the new push path carries full records instead.
  Changing it would break existing consumers for no gain.
- **Non-invoice entities still use change-pings.** Customers, vendors,
  inventory etc. keep the original ping-then-pull flow. Only invoices were in
  scope for full extraction. They now carry `event_id`s, so they are
  deduplicated too.
- **ODBC-for-reads / SDK-for-writes split.** Sound design; kept.

---

## 10. Recommended follow-ups

1. **Reconciliation sweep** — daily full comparison to catch voids/deletes (§3).
2. **Extend full extraction** to sales orders and payments, once the invoice
   path is proven on site.
3. **Alerting** — `/health` reports `degraded`; nothing watches it. Point a
   monitor at it so a stalled outbox pages someone.
4. **Replace Windows 7** — the real long-term fix for §8.
