# Sage 50 DAT File Processing Status

Last updated: 2026-06-07

## Processed & Live in DB

| DAT File | Records | DB Table(s) | Fields Available | Notes |
|----------|---------|-------------|-----------------|-------|
| CUSTOMER.DAT | 155 | `customers`, `sage_customers_snapshot` | name, customer_code, status, contact_details (phone, address), risk_score | Fully mapped; drives CRM dashboard |
| VENDOR.DAT | 24 | `sage_vendors_snapshot` | vendor_code, name, contact, address | Available in Suppliers page |
| ACCOUNT.DAT | 204 | `sage_coa_snapshot` | account_code, description, account_type, balance | Chart of Accounts; Finance/COA page |
| LINEITEM.DAT | 174 | `sage_items_snapshot`, `sage_inventory_snapshot` | item_id, item_name, category, unit, cost_price, selling_price, vat_category, reorder_level, expiry_date, batch_number | Rich metadata including expiry/lot; 92 items have expiry dates, 78 already expired |
| CONTACTS.DAT | 1780 | `crm_prospects` | name, phone, email, company, industry, region | Prospective leads; Lead Finder page |
| ADDRESS.DAT | — | enriched into `customers.contact_details` | street, city, postal_code | Merged during customer assimilation |

## Deferred — Amounts Encrypted / Binary Format

| DAT File | Size | Reason Deferred | Decision |
|----------|------|-----------------|---------|
| JRNLROW.DAT | 225 MB | Debit/credit amounts stored in a proprietary binary encoding (not standard IEEE float or BCD). Description strings and dates extracted (21,750 records) but financial values unreadable. | Await client IT to provide ODBC access or Pervasive SDK. Do not upload partial GL data. |
| JRNLHDR.DAT | 133 MB | Journal header records — different binary format, 0 readable records via current Btrieve scanner | Same as JRNLROW — requires SDK access |
| INVCOST.DAT | 62 MB | Invoice cost records — binary format unresolved | Revisit once ODBC/PSQL DLL 1114 error is fixed |

## Empty / No Data Entered in Sage

| DAT File | Reason |
|----------|--------|
| STXHDR.DAT | Sales transaction headers — client has not entered any invoices in Sage 50 |
| STXROW.DAT | Sales transaction rows — same as above |
| EMPLOYEE.DAT | No employee/payroll records entered |

## Out of Scope (Non-LSTRING Binary, No Extraction Path)

| DAT File | Notes |
|----------|-------|
| BUDGET.DAT | Fixed-width binary format; no LSTRING fields; would require reverse-engineering Pervasive record layout |
| BANKREC.DAT | Same as BUDGET.DAT |
| TAXCODE.DAT | Same as BUDGET.DAT |
| UNITMEAS.DAT | Same as BUDGET.DAT |

---

## Page-to-Data Mapping (Frontend)

| Sidebar Page | DB Source | Status |
|-------------|-----------|--------|
| Dashboard — Inventory widget | `sage_inventory_snapshot` + `sage_items_snapshot` | Live (enriched) |
| Dashboard — Finance widget | `sage_ar_snapshot`, `sage_ap_snapshot` | Empty — no invoice data in Sage |
| CRM Overview | `customers` (155), `crm_pipeline_snapshot` (empty) | Customer count live; pipeline value = 0 (no deal data) |
| Sales Pipeline (Kanban) | `customers` / `crm_pipeline_snapshot` | No pipeline deals; shows customer list instead |
| Lead Finder | `crm_prospects` | 1780 leads — fully working |
| Operations — Inventory | `sage_items_snapshot` via `/inventory/items` | Live with full fields (category, pricing, expiry, batch) |
| Operations — Stock Summary | `sage_inventory_snapshot` + enriched from `sage_items_snapshot` | Live |
| Quality Control — Expiry Alerts | `sage_items_snapshot` (fallback) | 92 items with expiry, 78 expired |
| Finance — COA | `sage_coa_snapshot` | 204 accounts — live if endpoint exists |
| Finance — AR/AP | `sage_ar_snapshot`, `sage_ap_snapshot` | Empty — no invoice data in Sage |
| Finance — GL | `sage_gl_snapshot` | Empty — JRNLROW amounts not extracted |
| Project Controls | stub endpoints | Returns empty lists; no crash |
| Suppliers | `sage_vendors_snapshot` | 24 vendors — live |
| HR / Staff | None | EMPLOYEE.DAT empty; no data available |
| ACE Synbot | `customers` via `customer_list` query type | 155 customers available to ACE |

---

## Next Steps to Unlock More Data

1. **ODBC access**: Fix Pervasive PSQL DLL 1114 error on client machine → enables direct SQL queries against all Sage 50 tables including invoices, GL amounts, journal entries.
2. **Invoice export**: Client exports STXHDR/STXROW as CSV from Sage 50 → import via `sage_csv_import` endpoint → unlocks AR, AP, Finance pages.
3. **GL amounts**: Client IT provides Btrieve SDK or ODBC → unlocks JRNLROW amount fields → populates `sage_gl_snapshot`.
