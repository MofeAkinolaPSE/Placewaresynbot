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
| Never drop a sync | `outbox.db` — events are committed to disk *with* the scan watermark in one transaction, before any delivery attempt. Retried until SynBot returns 2xx. |
| Never duplicate a sync | Deterministic `event_id` per record. SynBot records applied IDs and returns **409** for repeats; the bridge treats 409 as done. |

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

Then restrict the file — it holds a shared secret in plaintext:

```bat
icacls .env /inheritance:r /grant:r "SYSTEM:(R)" /grant:r "Administrators:(F)"
```

### 3.6 Apply the SynBot migration

On the SynBot side, once:

```bash
psql "$DATABASE_URL" -f backend/migrations/071_sage_bridge_idempotency.sql
```

This creates `placeware_sage_event_log` (the dedupe ledger — **without it
duplicate protection does not work**) and `sage_inventory_movements`.

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

### Useful operations

```bash
# Force an immediate scan
curl -X POST -H "X-Bridge-API-Key: <key>" http://<ip>:7070/sync/scan

# Replay everything that failed (safe — SynBot dedupes)
curl -X POST -H "X-Bridge-API-Key: <key>" http://<ip>:7070/sync/outbox/replay

# Re-read all invoices from scratch (safe — dedupes)
curl -X POST -H "X-Bridge-API-Key: <key>" \
     "http://<ip>:7070/sync/watermark/reset?value="
```

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

47 tests covering event identity, no-loss, no-duplicate, crash recovery, retry
behaviour and extraction accuracy. See section 7 of `KNOWN_LIMITATIONS.md` for
what these do **not** cover.

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
