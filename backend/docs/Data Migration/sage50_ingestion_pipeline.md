# Sage 50 2013 → Synbot Data Ingestion Pipeline

## Overview

This document describes the end-to-end process for ingesting a client's Sage 50 2013
(Peachtree) data into the Synbot backend so that deployment can begin.

The approach avoids the real-time bridge entirely. Instead:

1. Export Sage 50 data from the Windows machine as a ZIP bundle.
2. Upload the ZIP to the Synbot backend via one HTTP call.
3. Synbot ingests all entities and deployment proceeds.

---

## Architecture

```
Client's Windows 7 Machine
  Sage 50 2013 installed
  Pervasive PSQL v10 running
        │
        │  sage50_extractor.py  (reads via ODBC)
        ▼
  sage_export_20260605_143000.zip
  ├── customers.csv
  ├── vendors.csv
  ├── chart_of_accounts.csv
  ├── items.csv
  ├── stock_on_hand.csv
  ├── sales_invoices.csv
  ├── sales_invoice_lines.csv
  ├── purchase_orders.csv
  ├── inventory_transactions.csv
  ├── gl_journal_entries.csv
  ├── staff.csv
  └── manifest.json
        │
        │  Transfer (USB / network share / email)
        ▼
  POST /sage/import/batch   (multipart ZIP upload)
        │
        ▼
  Synbot PostgreSQL (synbot_demo)
  ├── sage_customers_snapshot
  ├── sage_vendors_snapshot
  ├── sage_coa_snapshot
  ├── sage_items_snapshot
  ├── sage_inventory_snapshot
  ├── sage_ar_snapshot
  ├── sage_invoice_lines_snapshot
  ├── sage_purchase_orders_snapshot
  ├── sage_ap_snapshot (auto-mirrored from POs)
  ├── sage_inv_transactions_snapshot
  ├── sage_gl_snapshot
  └── sage_staff_snapshot
```

---

## Step 1 — Prepare the Windows Machine

### 1a. Verify Pervasive PSQL ODBC DSN

The Pervasive PSQL v10 Workgroup Engine is already installed (confirmed by
`PSQL_v10_Install.log`). Before running the extractor, verify an ODBC DSN exists:

1. Press **Win+R** → type `odbcad32` → **System DSN** tab.
2. Look for an entry with "Pervasive", "Actian", or the company name.
   - If one exists: note the exact DSN name (e.g. `PEACHTREE_COMPANY`).
   - If none exists: click **Add** → select **Pervasive PSQL v10 Client** →
     set the database path to the company data folder
     (typically `C:\Users\PlacewareServer\AppData\Roaming\Sage\Peachtree\Company\<CompanyName>\`)
     → name it `SAGE_DATA`.

### 1b. If Working from a Backup File (.ptb)

A `.ptb` backup is a ZIP archive containing the company's Pervasive `.DAT` files.

1. Open Sage 50 2013 → **File → Restore Company**.
2. Select the `.ptb` file → restore to a local folder.
3. Sage restores the company data. The ODBC DSN will point at the restored files.

### 1c. Install pyodbc (one-time)

Python 3.8.6 embeddable is already in `D:\py38\` (from Phase 5 of the simulation plan).

```cmd
D:\py38\python.exe -m pip install pyodbc requests
```

---

## Step 2 — Copy the Extractor to the Windows Machine

Copy `backend/scripts/sage50_extractor.py` to `D:\PlacewareBridge\` on the Windows machine.
Use the VirtualBox shared folder if working in the VM simulation:

```cmd
xcopy \\VBOXSVR\PlacewareSetup\sage50_extractor.py D:\PlacewareBridge\
```

---

## Step 3 — Discover Available Tables (Optional)

Run this first to see what tables Sage exposes via the DSN:

```cmd
D:\py38\python.exe D:\PlacewareBridge\sage50_extractor.py ^
    --dsn "SAGE_DATA" ^
    --discover
```

Expected output (will vary by company configuration):

```
47 tables found:

  Customer          (CustomerID, Name, EmailAddress, Telephone1, Active ...)
  Vendor            (VendorID, Name, Contact, EmailAddress, PaymentTerms ...)
  InventoryItem     (ItemID, Description, ItemClassID, UnitPrice, Cost, QuantityOnHand ...)
  Account           (AccountID, Description, AccountType, Active ...)
  SalesInvoice      (InvoiceNo, CustomerID, Date, DueDate, AmountDue, Status ...)
  SalesInvoiceItem  (LineNo, InvoiceNo, ItemID, Quantity, UnitPrice, Amount ...)
  PurchaseOrder     (PurchaseOrderNo, VendorID, Date, ShipByDate, Amount ...)
  GenericJournal    (AccountID, PostingDate, Description, Debit, Credit ...)
  Employee          (EmployeeID, FirstName, LastName, EmailAddress, Department ...)
```

---

## Step 4 — Run the Extractor

### Option A — Export all entities

```cmd
D:\py38\python.exe D:\PlacewareBridge\sage50_extractor.py ^
    --dsn "SAGE_DATA"
```

Output: `sage_export_20260605_143022.zip` in the current directory.

### Option B — Export specific entities only

```cmd
D:\py38\python.exe D:\PlacewareBridge\sage50_extractor.py ^
    --dsn "SAGE_DATA" ^
    --entities customers vendors sales_invoices stock_on_hand chart_of_accounts
```

### Option C — Export and auto-upload to backend (if network accessible)

```cmd
D:\py38\python.exe D:\PlacewareBridge\sage50_extractor.py ^
    --dsn "SAGE_DATA" ^
    --upload http://192.168.1.10 ^
    --token eyJhbGciOiJIUzI1NiIs...
```

The `--upload` flag automatically calls `POST /sage/import/batch` and prints the result.

### Option D — Use a full connection string (no DSN required)

```cmd
D:\py38\python.exe D:\PlacewareBridge\sage50_extractor.py ^
    --conn "DRIVER={Pervasive PSQL v10 Client};ServerName=localhost;DbName=COMPANY_NAME"
```

---

## Step 5 — Transfer the ZIP to the Backend Machine

Copy `sage_export_*.zip` from the Windows machine to any machine that can reach the backend:

- USB drive → copy to laptop → upload via browser or curl
- Network share (if Windows VM and laptop are on same LAN)
- Email the ZIP (if small enough)

---

## Step 6 — Upload ZIP to Synbot Backend

### Via curl

```bash
# Get a token first
TOKEN=$(curl -s -X POST http://localhost/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@placeware.com","password":"YOUR_PASSWORD"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Upload the ZIP
curl -X POST http://localhost/sage/import/batch \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@sage_export_20260605_143022.zip"
```

### Via PowerShell (from laptop)

```powershell
$token = "eyJhbGci..."  # paste your JWT here

$response = Invoke-RestMethod `
    -Uri "http://localhost/sage/import/batch" `
    -Method POST `
    -Headers @{ Authorization = "Bearer $token" } `
    -Form @{ file = Get-Item "sage_export_20260605_143022.zip" }

$response | ConvertTo-Json -Depth 5
```

### Expected response

```json
{
  "batch_id": "3f7a2c14-...",
  "status": "succeeded",
  "total_rows_inserted": 4821,
  "datasets": [
    { "file": "customers.csv",           "file_type": "customers",           "rows_inserted": 312,  "status": "succeeded" },
    { "file": "vendors.csv",             "file_type": "vendors",             "rows_inserted": 48,   "status": "succeeded" },
    { "file": "chart_of_accounts.csv",   "file_type": "chart_of_accounts",   "rows_inserted": 185,  "status": "succeeded" },
    { "file": "items.csv",               "file_type": "items",               "rows_inserted": 620,  "status": "succeeded" },
    { "file": "stock_on_hand.csv",       "file_type": "stock_on_hand",       "rows_inserted": 620,  "status": "succeeded" },
    { "file": "sales_invoices.csv",      "file_type": "sales_invoices",      "rows_inserted": 2104, "status": "succeeded" },
    { "file": "sales_invoice_lines.csv", "file_type": "sales_invoice_lines", "rows_inserted": 1180, "status": "succeeded" },
    { "file": "gl_journal_entries.csv",  "file_type": "gl_journal_entries",  "rows_inserted": 890,  "status": "succeeded" }
  ],
  "imported_at": "2026-06-05T14:30:22Z"
}
```

---

## Step 7 — Verify Ingestion

### Check import job status

```bash
curl http://localhost/sage/import/jobs \
  -H "Authorization: Bearer $TOKEN"
```

### Verify data is in Synbot

Open the Synbot UI or hit the finance/inventory dashboards. The AI will now be
able to answer questions about Placeware's customers, invoices, stock levels,
and GL accounts using the ingested Sage data.

---

## Troubleshooting

### "No matching table found for 'sales_invoices' — skipped"

The extractor tries multiple table name variants. If Sage is using a non-standard
table name, run `--discover` to see what tables are available and add the name to
`ENTITY_DEFS[...]["tables"]` in `sage50_extractor.py`.

### "No ODBC DSN found"

Verify in `odbcad32` → System DSN tab. The DSN must be a **System DSN** (not
a User DSN), so it's accessible by all Windows accounts.

### Upload returns 403

The user must have role `admin`, `finance`, or `management`.

### Upload returns 422

One or more CSV rows failed validation. The response includes `validation_errors`
with the specific line number and reason. Common causes:
- Missing required column (e.g. `invoice_id` missing from sales_invoices.csv)
- Encoding issue — the extractor writes UTF-8 with BOM, which the backend handles.

---

## What Gets Loaded (Entity → Synbot Table Mapping)

| Sage 50 Entity        | CSV Filename              | Synbot Table                    |
|-----------------------|---------------------------|---------------------------------|
| Customers             | customers.csv             | sage_customers_snapshot         |
| Vendors / Suppliers   | vendors.csv               | sage_vendors_snapshot + suppliers |
| Chart of Accounts     | chart_of_accounts.csv     | sage_coa_snapshot               |
| Inventory Items       | items.csv                 | sage_items_snapshot             |
| Stock on Hand         | stock_on_hand.csv         | sage_inventory_snapshot         |
| Sales Invoices (AR)   | sales_invoices.csv        | sage_ar_snapshot                |
| Invoice Lines         | sales_invoice_lines.csv   | sage_invoice_lines_snapshot     |
| Purchase Orders       | purchase_orders.csv       | sage_purchase_orders_snapshot + sage_ap_snapshot |
| Inventory Transactions| inventory_transactions.csv| sage_inv_transactions_snapshot  |
| GL Journal Entries    | gl_journal_entries.csv    | sage_gl_snapshot                |
| Staff / Employees     | staff.csv                 | sage_staff_snapshot             |
| HR Payroll            | hr_payroll.csv            | sage_payroll_snapshot           |

---

## Files Created by This Pipeline

| File | Purpose |
|------|---------|
| `backend/scripts/sage50_extractor.py` | Runs on Windows 7; ODBC extraction → ZIP |
| `backend/src/routers/sage_csv_import.py` | Backend import router (updated with /batch endpoint) |
| `backend/docs/Data Migration/sage50_ingestion_pipeline.md` | This document |
