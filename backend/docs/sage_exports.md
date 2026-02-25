# Sage Export Templates (MVP)

These CSV templates define the minimum required columns for the file-based Sage adapter. Use exact headers (case-insensitive). Additional columns are allowed but ignored.

## Customers
Required columns:
- customer_id
- name
Optional: email, phone, status

## Accounts Receivable (AR)
Required columns:
- invoice_id
- customer_id
- date (YYYY-MM-DD)
- amount
- balance
Optional: due_date, status

## Accounts Payable (AP)
Required columns:
- bill_id
- vendor_id
- date (YYYY-MM-DD)
- amount
- balance
Optional: due_date, status

## General Ledger (GL) Summary
Required columns:
- period (e.g., 2025-11)
- account_code
- account_name
- debit
- credit

## Inventory
Required columns:
- sku
- name
- quantity
Optional: unit_cost, valuation, updated_at (ISO8601)

## Upload API
Endpoint: POST /sage/import

Multipart form fields (CSV files): customers, ar, ap, gl, inventory
Headers:
- Authorization: Bearer <JWT-with-admin-role>

Response: JSON with batch_id, imported_at, per-entity counts, status

Notes:
- Snapshots are append-only, immutable.
- Invalid headers/data will be rejected with 400.
- For large files, split by entity (do not mix rows across types).
