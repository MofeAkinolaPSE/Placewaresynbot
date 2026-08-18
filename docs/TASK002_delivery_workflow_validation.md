# Task 002 — Logistics & Delivery Workflow Validation

Status of the invoice-to-delivery chain ahead of the client demo: findings, fixes applied,
environment requirements, and the browser test script still to be executed.

**Scope note:** the Claude-in-Chrome extension was not connected during this pass, so the
formal in-browser walkthrough (the task's Validation Deliverable) has **not** been performed.
Everything below was validated by driving the real HTTP API with the real role accounts —
which is what exposed the blockers — plus code audit. The browser script in §5 is the
remaining work.

---

## 1. Environment blocker (the big one)

**15 migrations had never been applied to `synbot_demo`**, including the two the entire
delivery workflow depends on:

| Migration | Adds | Without it |
|---|---|---|
| `099_frontdesk_delivery_handoff.sql` | `deliveries.source`, `deliveries.source_ref_id`, `frontdesk_invoices.delivery_id`, `dispatched_at`, `'dispatched'`/`'completed'` in the status CHECK | Dispatch fails outright; invoice can never reach `completed` |
| `109_rider_access_codes.sql` | `riders.access_code` (unique) | Rider registration and the **entire access-code sign-in flow** are dead |

**Root cause of the drift:** `backend/scripts/apply_migrations.py` never calls
`load_dotenv()`. With no `DATABASE_URL` exported in the shell it silently falls back to
`postgresql://postgres:postgres@localhost:5432/**postgres**` — the wrong database — and
either fails on auth or applies migrations to an unrelated DB while appearing to succeed.

**Applied during this task:**

```bash
cd backend
export DATABASE_URL='postgresql://postgres:<pw>@localhost:5432/synbot_demo'   # REQUIRED
./venv/Scripts/python.exe scripts/apply_migrations.py
```

> **Deployment requirement:** always export `DATABASE_URL` explicitly before running
> `apply_migrations.py`. Do not rely on its default. Worth fixing the script to load
> `backend/.env`, and worth adding a startup assertion that the newest migration is present.

---

## 2. Bugs found and fixed

### 2.1 `/rider-track/:token` called the wrong origin and silently faked success — CRITICAL

`RiderTrack.tsx` read `import.meta.env.VITE_API_URL`, a variable **defined nowhere in the
project**. Every other module uses `VITE_API_BASE_URL` via the `apiUrl()` helper. It
therefore resolved to `""`, making all four calls relative to the SPA origin — which has no
`/logistics` proxy entry in `vite.config.ts`.

The failure mode was the dangerous kind, not a visible error:

```
GET http://localhost:8000/logistics/riders/by-code/ABC123  → 404 {"detail":"Invalid rider code"}
GET http://localhost:5173/logistics/riders/by-code/ABC123  → 200 text/html  (the SPA shell)
```

Because the SPA returns **HTTP 200** for unknown paths, `res.ok` was `true`. So:

- GPS pings "succeeded", the ping counter incremented, and the rider page showed *Tracking
  active* — while **no position ever reached the server** and staff saw an empty map.
- "Confirm Delivery" "succeeded" and flipped the UI to *Delivered* — while the delivery row
  and the originating invoice were never touched.

This would have presented as a working demo right up until someone looked at the staff map.

**Fix:** `RiderTrack.tsx` now uses the shared `apiUrl()` helper, consistent with the rest of
the codebase.

### 2.2 Geofence auto-delivery could never fire for any real delivery — HIGH

`frontdesk_walk_ins` has **no address column at all**, so
`POST /frontdesk/invoices/{id}/send-for-delivery` creates deliveries with `dest_lat`/
`dest_lng` `NULL`. The geofence in `/logistics/location-ping` is gated on both being
non-NULL, so auto-delivery-on-arrival was unreachable for every invoice-originated
delivery — only the manual button worked. This is a stated Testing Requirement.

**Fix:** `POST /logistics/deliveries/{id}/assign` now accepts optional `dest_lat`/`dest_lng`
(validated: both-or-neither, numeric, in range), and the Logistics Monitor assign panel has
two optional destination fields. Dispatch drops a pin when assigning the rider.

### 2.3 Duplicate delivery confirmation double-completed the invoice — MEDIUM

The geofence auto-detect and the rider's manual Confirm button race by design — a rider
arriving inside 150 m is auto-delivered mid-ping while their thumb is already on the button.
The second writer overwrote `delivered_at` and ran `_complete_linked_invoice()` again,
emitting a **duplicate `frontdesk_invoice_completed` row** into the invoice audit timeline.

**Fix:** idempotency guard in `update_delivery_status` — re-confirming an already-delivered
delivery is now a no-op returning `{"status": "already_delivered"}`. Verified: 1 audit row,
not 2.

### 2.4 Logistics Monitor never updated when another department acted — MEDIUM

The `logistics-deliveries` query had no `refetchInterval` and no realtime subscription; it
invalidated only on the *current* operator's own mutations. The SSE `live-feed` carries
rider GPS positions only, not delivery state. Net effect: an invoice dispatched by Finance,
or a delivery a rider just confirmed, **never appeared on an already-open Logistics Monitor
without a manual page refresh** — exactly the failure a multi-screen demo exposes.

Compounding it, `logistics.py` broadcast nothing at all, so the dashboard Operations Queue
(which already listens on `logistics_updates`) had no producer.

**Fix:** `logistics.py` now broadcasts `logistics_updates` on assign, start, status change,
and geofence auto-delivery; `LogisticsMonitor.tsx` subscribes to both `frontdesk_updates`
and `logistics_updates`.

### 2.5 Rider-facing error handling — MEDIUM

Two gaps on the only two pages a rider ever touches:

- **Manual confirm failed completely silently.** `handleManualDelivery` had no `!res.ok`
  branch and an empty `catch`. The rider taps *Confirm Delivery*, and nothing happens — no
  error, no spinner, no state change. **Fixed:** surfaces the server `detail`, a distinct
  offline message, plus a pending state and a disabled button to prevent double-taps.
- **Reopening the browser mid-delivery dropped tracking.** An `in_transit` delivery loaded
  into the `"ready"` state, so a rider who was backgrounded, killed by battery saver, or
  simply closed the tab came back to a page that **sent nothing** until they noticed and
  re-tapped *Start Tracking*. **Fixed:** an `in_transit` delivery now resumes tracking
  automatically on load.
- **Offline queue was never drained on mount.** Pings buffered during a signal drop persist
  in `localStorage`, but the drain was wired only to the `online` event — which does not
  fire if the tab reopens already online, stranding those pings permanently. **Fixed:**
  explicit drain on mount.

---

## 3. Verified working (via real API, real role accounts)

| Check | Result |
|---|---|
| Request → invoice lands in QC queue | PASS (`qc_pending`) |
| QC pass → `finance_pending` / QC fail → `qc_failed` | PASS both |
| Finance approve → `finance_approved` / reject → `finance_rejected` | PASS both |
| Finance blocked on a `qc_failed` invoice | PASS (409) |
| Dispatch of a non-approved invoice blocked | PASS (409) |
| Duplicate dispatch blocked | PASS (409) |
| Dispatch creates real delivery, appears in Logistics | PASS |
| Manual rider assignment, status → `assigned` | PASS |
| Access code resolves delivery, auto-starts, mints token | PASS (`in_transit`) |
| Invalid code / idle rider messaging | PASS (404 / friendly "no delivery assigned") |
| GPS pings stored, staff live positions populated | PASS (4 pings, rider on map) |
| **Geofence auto-delivery at 150 m** | PASS (fires only on arrival, not en route) |
| Manual confirm via rider token | PASS |
| Duplicate confirm is idempotent | PASS (1 audit row) |
| Pings rejected after delivery | PASS (410) |
| Invoice ends `completed` | PASS |
| Full audit trail | PASS — `create_invoice → qc_check → finance_approval → send_for_delivery → delivery_confirmed` |

**Role separation genuinely enforced** — not one admin doing everything:

- Finance account attempting QC → **403**
- QC account attempting Finance approval → **403**

---

## 4. Test accounts created

| Role | Email | Password |
|---|---|---|
| QC | `qc.tester@placeware.com` | `Pware!2345` |
| Finance | `finance.tester@placeware.com` | `Pware!2345` |
| Ops | `ops.tester@placeware.com` | `Pware!2345` |
| Admin (pre-existing) | `admin@placeware.com` | `pware1234` |

Created through the app's own `POST /users` admin endpoint — no direct DB writes.

> Demo passwords for a local `synbot_demo` instance. Rotate or remove before any
> internet-reachable deployment.

---

## 5. Browser test script (still to run)

Local: backend `127.0.0.1:8000`, frontend `127.0.0.1:5173`.
Use **separate browser profiles or windows** per role — not one session — or you will not
observe the realtime handoffs.

### 5.1 Setup
1. Window A → `/login` as **ops**, go to `/operations/logistics` → Riders tab.
2. Register a rider. **Record the 6-character access code** — it is shown once at creation.
3. Leave the Logistics Monitor open for the rest of the run.

### 5.2 Request → QC
4. Window B → `/login` as **admin**, go to `/frontdesk`. Register a walk-in, then raise an
   invoice from it.
5. Window C → `/login` as **qc**, go to `/quality-control`.
   ✅ The new invoice appears in the QC queue **without a manual refresh**.
6. **QC fail path first:** on a throwaway invoice, fail QC → status `qc_failed`, and confirm
   Finance cannot action it.
7. On the real invoice, pass QC → advances to `finance_pending`.

### 5.3 Finance → Dispatch
8. Window D → `/login` as **finance**, open the invoice action panel.
   ✅ It appears in the Finance queue live.
9. Reject once on a throwaway invoice → `finance_rejected`, and confirm dispatch is blocked.
10. Approve the real invoice → `finance_approved`, then **Send for Delivery**.
    ✅ **In Window A, the new delivery appears in the Logistics Monitor with no refresh** —
    this is regression 2.4, verify it explicitly.

### 5.4 Assign with destination
11. In Window A, select the unassigned delivery, pick the rider, and **enter destination
    lat/lng** (this enables the geofence — see 2.2). Use coordinates near where you will
    simulate arrival. Assign.
    ✅ Status → `assigned`.

### 5.5 Rider on a real phone
12. On an **actual phone** (same network; use the machine's LAN IP, not `localhost`), open
    `/rider`. Note this requires the site be reachable over the LAN and that mobile browsers
    generally **require HTTPS for the Geolocation API** — plain `http://<lan-ip>` will
    silently deny GPS on Chrome/Safari. Use a tunnel or a TLS-terminating proxy for the demo.
13. Enter the access code.
    ✅ Resolves the rider's delivery and redirects to `/rider-track/:token`, tracking
    auto-started.
14. Also test the error paths: a wrong code → *Invalid rider code*; a rider with nothing
    assigned → the friendly "no delivery assigned" message.

### 5.6 Live tracking + resilience
15. Move (or simulate movement via device GPS spoofing).
    ✅ In Window A the rider marker updates within ~5 s.
16. **Kill the browser mid-delivery and reopen `/rider-track/:token`.**
    ✅ Tracking resumes automatically (regression 2.5).
17. **Enable airplane mode for ~30 s, then restore.**
    ✅ Queued pings flush on reconnect and the gap backfills.
18. Background the app / enable battery saver and confirm ping cadence.
    ⚠️ Expect degradation — mobile browsers throttle timers in background tabs and the
    Wake Lock is screen-only. See §6.

### 5.7 Confirmation
19. Ride into the 150 m geofence.
    ✅ Auto-delivered banner appears; delivery → `delivered` without anyone tapping anything.
20. On a second delivery, use the **manual** Confirm button instead. Also tap it twice.
    ✅ Second tap is a harmless no-op (regression 2.3).
21. ✅ Invoice shows **completed**; history shows all five stages.

### 5.8 Concurrency
22. With two staff windows open on the same invoice, action it from both near-simultaneously.
    ✅ One wins, the other gets a clear 409 — no duplicate delivery, no lost update.

---

## 6. Open risks for the demo

1. **HTTPS is mandatory for the rider pages.** Chrome and Safari refuse `navigator.geolocation`
   on non-secure origins other than `localhost`. A rider's phone hitting `http://<lan-ip>`
   gets a permission denial that surfaces only as a `console.warn` in `startTracking`'s error
   callback — the page still says *Tracking active*. **This will look exactly like the bug
   fixed in 2.1 and is the single most likely thing to break the live demo.** Serve the demo
   over TLS.
2. **Background GPS is best-effort.** `PING_INTERVAL_MS` is a `setInterval`, which mobile
   browsers throttle hard (often to ≥60 s) once the tab is backgrounded; Wake Lock only keeps
   the *screen* awake and is released when the page is hidden. Phase one should keep the
   rider's screen on and the tab foregrounded. A service worker + Background Sync would be
   the real fix, out of scope here.
3. **GPS error feedback is console-only.** A denied or failing GPS fix leaves the UI showing
   *Tracking active* with a silently frozen position. Recommend surfacing `watchPosition`
   errors and a "no fix in Ns" warning — not fixed here as it is a UX addition rather than a
   regression.
4. **`submit_qc` does not check the invoice's current status.** A dispatched or completed
   invoice can be re-QC'd, dragging it back to `finance_pending` while a delivery is already
   in flight. Not triggerable through the normal UI path, but it is an unguarded transition;
   recommend a status precondition matching the one `send_for_delivery` already has.
5. **Access code entropy.** 6 characters from a 32-symbol alphabet with no rate limiting on
   `/logistics/riders/by-code/{code}`. Acceptable for phase one; add throttling before this
   is internet-facing, since a hit starts tracking and exposes customer name, phone, and
   address.

---

## 7. Files changed

| File | Change |
|---|---|
| `SynbotUI/client/pages/RiderTrack.tsx` | Use `apiUrl()`; resume tracking on reopen; drain offline queue on mount; surface confirm errors + pending state |
| `SynbotUI/client/pages/LogisticsMonitor.tsx` | Destination lat/lng on assign; subscribe to `frontdesk_updates` + `logistics_updates` |
| `SynbotUI/client/lib/api-client.ts` | `assignDelivery` accepts optional destination |
| `backend/src/routers/logistics.py` | Destination on assign (validated); confirm idempotency guard; `logistics_updates` broadcasts |
| Database | Applied 15 pending migrations (097–110) |

No schema changes beyond the already-committed, idempotent migrations. No workarounds — the
whole chain runs through the real endpoints.
