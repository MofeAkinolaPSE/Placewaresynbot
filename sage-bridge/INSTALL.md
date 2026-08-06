# Sage Bridge — Installation & Operations Guide

Middleware connecting **Sage 50 Accounting 2013** (Windows 7) to the **SynBot
ERP** platform. Detects new invoices, extracts them in full, and delivers them
to SynBot exactly once.

---

## 1. Architecture in one page

```
   Windows 7 machine (Sage 50 2013)          Ubuntu VM / server
  ┌────────────────────────────────┐        ┌────────────────────┐
  │  Sage 50 company (.DAT files)  │        │      SynBot        │
  │            ▲         ▲         │        │                    │
  │   ODBC ────┘         └─ SDK    │        │  POST /sage/webhook│
  │  (reads)             (detail)  │        │        │           │
  │      │                  │      │        │        ▼           │
  │  ┌───┴──────────────────┴───┐  │        │  event_id dedupe   │
  │  │      Sage Bridge         │  │        │        │           │
  │  │                          │  │        │        ▼           │
  │  │  watcher ──► outbox.db ──┼──┼── HTTP ─┼──►  inventory     │
  │  │              (SQLite)    │  │  retry  │     finance       │
  │  │                  ▲       │  │  until  │     sales         │
  │  │              sender      │  │   2xx   │     audit log     │
  │  └──────────────────────────┘  │        │                    │
  └────────────────────────────────┘        └────────────────────┘
```

**The two guarantees and where they live:**

| Guarantee | Mechanism |
|---|---|
| Never drop a sync | `outbox.db` — events are committed to disk *with* the scan watermark in one transaction, before any delivery attempt. Retried until SynBot returns 2xx. **SynBot applies the record synchronously**, so a 2xx means it landed; a failure returns 5xx and the event stays pending. |
| Never duplicate a sync | Deterministic `event_id` per record. SynBot records applied IDs — only *after* a successful apply — and returns **409** for repeats; the bridge treats 409 as done. |

**Detection has two layers plus a sweep:**

| Layer | Catches | Interval |
|---|---|---|
| `.DAT` mtime poll | "something changed in AR" | `WATCHER_POLL_SECONDS` (30 s) |
| Forward table scan | new and edited invoices | `WATCHER_FULL_SCAN_SECONDS` (5 min), mtime-independent |
| Reconciliation sweep | **deleted / voided** invoices | `RECONCILE_INTERVAL_SECONDS` (24 h) |

The sweep exists because the forward scan walks a watermark upward and cannot
see a row that is gone.

**Do not delete `data/outbox.db`.** It holds undelivered invoices and the scan
position. Back it up alongside the Sage company file.

---

## 2. Prerequisites

| Requirement | Notes |
|---|---|
| Windows 7 SP1 | Target platform. |
| Sage 50 Accounting 2013 | Installed with its Pervasive Workgroup Engine. |
| **Python 3.9.13, 32-bit** | See the warning below — this is the #1 install failure. |
| .NET Framework 4.x | Preinstalled on Win7 SP1. Required by the Sage SDK. |
| NSSM | Service wrapper — <https://nssm.cc/download> |

> ### ⚠ Python MUST be 32-bit
>
> The Pervasive ODBC driver shipped with Sage 50 2013 is 32-bit. A 64-bit
> Python **cannot** load it — `pyodbc.connect()` fails with an architecture
> mismatch that reads like a missing DSN and wastes hours.
>
> Download `python-3.9.13.exe` (**not** `python-3.9.13-amd64.exe`).
> Verify: `python -c "import struct; print(struct.calcsize('P')*8)"` → `32`
>
> 3.9 is also the **last** Python with Windows 7 support. Do not upgrade.

---

## 3. Installation

### 3.1 Files and virtualenv

```bat
mkdir C:\PlacewareBridge
xcopy /E /I <source>\sage-bridge C:\PlacewareBridge
cd C:\PlacewareBridge

python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\pip install -r requirements.txt
```

### 3.2 Create the ODBC DSN

Run **`C:\Windows\SysWOW64\odbcad32.exe`** — the 32-bit administrator.

> Not the ODBC entry in Control Panel: that one is 64-bit and the DSN you
> create there will be invisible to 32-bit Python.

*System DSN* → *Add* → *Pervasive ODBC Client Interface* → name it
`PervasiveSage50`, point it at the Sage company folder, *Test Connection*.

### 3.3 Find the Sage company path

In Sage 50: **Help → About Sage 50 Accounting** → note the data path.
It looks like `C:\Sage\Peachtree\Company\YourCompany\`.

### 3.4 Authorize the SDK — one time, interactive

> The Sage 50 SDK requires a **one-time interactive consent prompt** inside
> Sage. A Windows service cannot answer a dialog, so this must be done by hand
> **before** installing the service, from a logged-in desktop session.

1. Open Sage 50 and log in as an admin user. Leave it open.
2. From an interactive command prompt (not a service):
   ```bat
   cd C:\PlacewareBridge
   .venv\Scripts\python verify_onsite.py
   ```
3. When Sage shows the third-party application request, **approve it**.
4. Re-run until the SDK check passes.

If this is skipped, the bridge starts in ODBC-only mode: invoices still sync
but are marked `completeness=partial` and tax is missing.

### 3.5 Configure

```bat
copy .env.example .env
notepad .env
```

Generate a strong key — the service **refuses to start** with a placeholder:

```bat
.venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Must-set values:

| Variable | Value |
|---|---|
| `BRIDGE_API_KEY` | Generated above. Must equal `SAGE_BRIDGE_KEY` in SynBot's `backend/.env`. |
| `SAGE_COMPANY_PATH` | From step 3.3. |
| `SAGE_ODBC_DSN` | `PervasiveSage50` |
| `SYNBOT_WEBHOOK_URL` | `http://<VM_LAN_IP>/sage/webhook` |
| `SYNBOT_WEBHOOK_KEY` | Must equal `SAGE_BRIDGE_WEBHOOK_SECRET` in SynBot's `backend/.env`. |
| `SAGE_MOCK` | `false` |

Optional, sensible defaults — change only with a reason:

| Variable | Default | Notes |
|---|---|---|
| `SAGE_INSTALL_DIR` | derived | Peachtree program folder (holds `Peachw.exe`). Blank derives it from `SAGE_API_DLL_PATH`. |
| `RECONCILE_ENABLED` | `true` | Void/delete detection. Turning this off means voided invoices stay live in SynBot forever. |
| `RECONCILE_INTERVAL_SECONDS` | `86400` | Full-table enumeration — daily is the right order of magnitude, not hourly. |
| `RECONCILE_MAX_DELETE_RATIO` | `0.10` | Abort the sweep if more than 10% of known invoices vanish at once. Raise deliberately, never casually. |

Then restrict the file — it holds a shared secret in plaintext:

```bat
icacls .env /inheritance:r /grant:r "SYSTEM:(R)" /grant:r "Administrators:(F)"
```

### 3.6 Apply the SynBot migrations

On the SynBot side, once. **Both are required:**

```bash
psql "$DATABASE_URL" -f backend/migrations/071_sage_bridge_idempotency.sql
psql "$DATABASE_URL" -f backend/migrations/097_sage_bridge_voids_and_downstream.sql
```

`071` creates `placeware_sage_event_log` (the dedupe ledger — **without it
duplicate protection does not work**) and `sage_inventory_movements`.

`097` adds void/soft-delete support (`is_voided` across the invoice cache, stock
movements, sales lines and GL entries), the `sage_gl_entries` and
`sage_sales_lines` tables, and the customer AR rollup columns. Without it every
invoice sync fails at the downstream write — loudly, with events staying pending
in the outbox rather than half-applying.

### 3.7a Verify the SDK API surface — do this FIRST

```bat
.venv\Scripts\python verify_sdk_api.py
```

Reflects over the installed `Sage.Peachtree.API.dll` and asserts that all 189
types, properties and methods the bridge calls actually exist. Takes seconds,
needs **no company file**, touches no data.

Expected: `OK — every type, property and method the bridge calls exists here.`

If it fails, the SDK on this machine is not the 2013.0.0.826 build the bridge
targets, and the failures name the exact missing members. **Stop and reconcile
`sdk_client.py` before going further** — nothing else in the SDK path can work.

> This check exists because the original `sdk_client.py` was written against an
> API that does not exist (`ProductType`, `Company.SalesInvoices`,
> `invoice.TotalAmount`, ~20 more). None of that fails at import — it fails at
> the first real call, gets caught by the degraded-start handler, and leaves
> the bridge quietly running ODBC-only with no tax on any invoice.

### 3.7 Verify before installing the service

```bat
.venv\Scripts\python verify_onsite.py --report
```

Fix every `[FAIL]` before continuing. `--report` prints the real table and
column names — if the schema check fails, correct `sage_schema.py` to match and
re-run. That file is the **only** place schema names live.

End-to-end check (delivers one real test event):

```bat
.venv\Scripts\python verify_onsite.py --send-test
```

### 3.8 Install the service

```powershell
powershell -ExecutionPolicy Bypass -File install-service.ps1
```

> **Service account:** the default LocalSystem often cannot reach the Pervasive
> engine or the company file. If the service starts but ODBC fails while
> `verify_onsite.py` succeeds interactively, set the service to run as the
> Windows user that normally runs Sage:
>
> ```
> nssm set PlacewareSageBridge ObjectName .\SageUser <password>
> ```

---

## 4. Operating it

### Health and status

```bash
curl http://<win7-ip>:7070/health                     # no auth
curl -H "X-Bridge-API-Key: <key>" http://<win7-ip>:7070/sync/status
```

`/sync/status` is the one to watch:

```json
{
  "healthy": true,
  "odbc_connected": true,
  "sdk": {"healthy": true},
  "watcher": {"healthy": true, "thread_alive": true, "stalled": false,
              "start_error": "", "last_scan_age_seconds": 12.4,
              "last_reconcile_age_seconds": 3600.0},
  "outbox": {"pending": 0, "sent": 1432, "failed": 0,
             "oldest_pending_age_seconds": null},
  "invoice_watermark": "1099"
}
```

| Symptom | Meaning | Action |
|---|---|---|
| `pending` climbing, `sent` flat | SynBot unreachable | Check VM/network. Events are safe; they drain automatically. |
| `failed` > 0 | Events exhausted retries | Fix the cause, then `POST /sync/outbox/replay`. |
| `oldest_pending_age_seconds` large | Delivery stalled | Check the bridge log. |
| `sdk.healthy: false` | SDK down | Invoices sync as `partial`. Re-check authorization (3.4). |
| `watcher.start_error` non-empty | Watcher never started — usually a bad `SAGE_COMPANY_PATH` | Fix the path and restart. **Nothing is being detected until you do.** |
| `watcher.stalled: true` | Loop wedged, probably a hung ODBC call | Check the log, restart the service. |
| `watcher.healthy: false` with an empty outbox | Detection is dead | Do **not** read an empty outbox as "no new invoices" — check this field first. |

> **Why the `watcher` block matters.** A watcher that never started leaves the
> outbox permanently empty, which looks exactly like a quiet day. Before this
> block existed the service reported `ok` indefinitely while syncing nothing.
> `healthy` is now false whenever the watcher is not actually running.

### Useful operations

```bash
# Force an immediate scan
curl -X POST -H "X-Bridge-API-Key: <key>" http://<ip>:7070/sync/scan

# Replay everything that failed (safe — SynBot dedupes)
curl -X POST -H "X-Bridge-API-Key: <key>" http://<ip>:7070/sync/outbox/replay

# Re-read all invoices from scratch (safe — dedupes)
curl -X POST -H "X-Bridge-API-Key: <key>" \
     "http://<ip>:7070/sync/watermark/reset?value="

# Check for voided/deleted invoices now, instead of waiting for the daily sweep
curl -X POST -H "X-Bridge-API-Key: <key>" http://<ip>:7070/sync/reconcile
```

**Reading a reconcile result.** `status: "ok"` means the sweep completed;
`deleted` is how many invoices vanished from Sage. `status: "aborted"` means a
safety guard tripped and **nothing was emitted** — check `reason`:

| `reason` | Meaning | Action |
|---|---|---|
| `enumeration failed` | ODBC error mid-scan | Fix connectivity; a partial read is indistinguishable from mass deletion, so nothing was emitted |
| `empty enumeration` | Sage returned zero invoices | Connectivity or permissions fault — not an empty company |
| `bulk delete ceiling exceeded` | More than `RECONCILE_MAX_DELETE_RATIO` missing | Usually a swapped or restored company file. Investigate before raising the ceiling |

An aborted sweep is safe to ignore once the cause is fixed — the next sweep
retries, and nothing was tombstoned.

### Logs

`C:\PlacewareBridge\logs\sage_bridge.log`, rotating at 5 MB × 5 files
(25 MB ceiling — it cannot fill the disk).

### Backup

Back up **`data\outbox.db`**. It contains undelivered invoices and the scan
position. Losing it while events are pending loses those events.

---

## 5. Resource footprint

Measured in mock mode; expect similar on the target:

| Resource | Idle | During a scan |
|---|---|---|
| RAM | ~45 MB | ~60 MB |
| CPU | <1% | brief spike |
| Disk | ~1 MB/1000 invoices | 25 MB log ceiling |

Tunable in `.env` if the machine is very constrained: raise
`WATCHER_POLL_SECONDS`, lower `WATCHER_SCAN_PAGE_SIZE`.

---

## 6. Testing

Runs anywhere — no Sage, no Windows:

```bash
pip install pytest pydantic pydantic-settings python-dotenv httpx fastapi
python -m pytest tests/ -v
```

58 tests covering event identity, no-loss, no-duplicate, crash recovery, retry
behaviour, extraction accuracy, void detection with all three sweep guards, and
watcher liveness.

The receiving end has its own regression tests — run these from `backend/`:

```bash
python -m pytest tests/test_sage_webhook_durability.py -v
```

Six tests pinning the contract that makes the outbox meaningful: a 2xx from
SynBot must mean the record was actually applied. They are the guard against
reintroducing the background-task bug, where a failed apply still returned 200
and the bridge dropped the invoice.

See section 7 of `KNOWN_LIMITATIONS.md` for what these do **not** cover.

Run the service against fake Sage data:

```bash
set SAGE_MOCK=true
.venv\Scripts\python main.py
```

---

## 7. Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `BRIDGE_API_KEY is unset or still a placeholder` | Real key not set | Section 3.5 |
| `architecture mismatch` / `IM002` | 64-bit Python vs 32-bit driver | Reinstall 32-bit Python |
| DSN not found | Created in the 64-bit ODBC admin | Use `SysWOW64\odbcad32.exe` |
| `expected table 'ARTRANS' NOT FOUND` | DDF names differ | `verify_onsite.py --report`, fix `sage_schema.py` |
| SDK session fails | Authorization not granted | Section 3.4, interactively |
| Webhook 403 | Key mismatch | `SYNBOT_WEBHOOK_KEY` == `SAGE_BRIDGE_WEBHOOK_SECRET` |
| Service starts, ODBC fails | LocalSystem can't reach Pervasive | Run as the Sage user (3.8) |
