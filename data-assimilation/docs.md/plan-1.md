Ready for review
Select text to add comments on the plan
Full Data Visibility Mission Plan
Context
Assimilation ran and data IS in the DB. The problems are:

Frontend calls endpoints that don't exist (/stock → 404 HTML)
Backend services read from empty tables (invoice/AR data we don't have)
Rich data in sage_items_snapshot is never joined by inventory handlers
Project Controls router doesn't exist → HTML error
CRM/ACE queries empty crm_pipeline_snapshot instead of customers table
This plan fixes every visible symptom systematically, page by page.

Part 1 — DAT File Status (to become data-assimilation/sage50/DAT_FILE_STATUS.md)
DAT File	Size	Records	Extracted	DB Table	Status
CUSTOMER.DAT	~2 MB	155	✅ All fields	customers, sage_customers_snapshot	Live
VENDOR.DAT	~0.5 MB	24	✅ All fields	sage_vendors_snapshot	Live
ACCOUNT.DAT	~1 MB	204	✅ All fields	sage_coa_snapshot	Live
LINEITEM.DAT	~8 MB	174 items	✅ All fields + expiry/lot	sage_items_snapshot, sage_inventory_snapshot	Live
CONTACTS.DAT	~1 MB	1780	✅ Name + phone	crm_prospects	Live
ADDRESS.DAT	~1 MB	—	✅ Street + city	enriched into customers.contact_details	Live
JRNLROW.DAT	225 MB	21,750 GL rows	⚠️ Description + date only	NOT uploaded — amounts binary/encrypted	Deferred
JRNLHDR.DAT	133 MB	0	❌ Different format	—	Out of scope
STXHDR.DAT	—	0	❌ No data entered in Sage	—	N/A
STXROW.DAT	—	0	❌ No data entered in Sage	—	N/A
INVCOST.DAT	62 MB	—	❌ Binary format unresolved	—	Out of scope
EMPLOYEE.DAT	~0.5 MB	0	❌ Empty file	—	N/A
BUDGET.DAT	small	—	❌ Non-LSTRING binary	—	Out of scope
BANKREC.DAT	small	—	❌ Non-LSTRING binary	—	Out of scope
TAXCODE.DAT	small	—	❌ Non-LSTRING binary	—	Out of scope
UNITMEAS.DAT	small	—	❌ Non-LSTRING binary	—	Out of scope
Part 2 — Page-by-Page Data Audit & Fix Plan
Dashboard (/)
Current state: Mostly blank. Calls /stock (doesn't exist → 404). Data available: sage_inventory_snapshot (58 rows), sage_items_snapshot (174 rows), customers (155) Fix:

api.inventory.stock() calls /stock — backend has no such route. Should call /inventory/summary. Fix in SynbotUI/client/lib/api-client.ts:
stock: (skus?: string[]) => fetchJson<any>("/inventory/summary"),
The Dashboard finance card reads api.dashboard.finance() → /dashboard/finance — this reads from AR/AP snapshots (empty). Nothing to fix here; it will show zeros until invoice data exists.
CRM Overview (/crm)
Current state: All KPIs zero. Risk table empty. Data available: customers (155 rows), crm_prospects (1780 leads) Fix:

backend/src/services/crm.py → get_crm_stats(): add customer count from customers table. Add customer_count and active_customers keys to return dict.
backend/src/routers/agents_exec.py: add customer_list query type reading from customers.
SynbotUI/client/lib/api-client.ts → crm object: add customers() function → GET /crm/customers.
SynbotUI/client/pages/CRM.tsx: add customer count KPI + customer list table using new query.
Sales Pipeline (/crm/sales)
Current state: Blank Kanban board. Reads leads table (0 rows). Data available: customers (155), crm_prospects (1780) Fix: Seed the leads table from confirmed customers so the Kanban isn't empty.

backend/src/routers/crm_sales.py or a migration: INSERT into leads from customers with default stage "existing_customer". This makes the pipeline show existing client accounts.
Alternatively: add a "Customers" tab to SalesCRM page that reads from GET /crm/customers.
Lead Finder (/crm/lead-finder)
Current state: ✅ Working. Shows 1780 prospects from crm_prospects. Fix needed: None. This is correct — hospital/pharma contacts as prospective leads.

Operations Overview (/operations)
Current state: Partially working. /dashboard/inventory reads sage_inventory_snapshot (58 rows). Data available: 58 inventory rows with qty=0, sage_items_snapshot (174 rows with rich metadata) Fix:

backend/src/services/inventory.py → get_inventory_summary(): join sage_inventory_snapshot with sage_items_snapshot on sku/item_id to add category, expiry_date, batch_number, cost_price, reorder_level to each returned item.
Inventory Items (within Operations, and /inventory)
Current state: Shows item names only. /stock route doesn't exist. Data available: sage_items_snapshot (174 rows): item_id, item_name, category, unit, cost_price, selling_price, vat_category, reorder_level, expiry_date, batch_number Fix 1 — Backend: add /stock endpoint (or /inventory/items):

@router.get("/items")
async def list_items(...):
    res = db.table("sage_items_snapshot")
           .select("item_id, item_name, category, unit, cost_price, selling_price,
                    vat_category, reorder_level, expiry_date, batch_number, is_active")
           .order("imported_at", desc=True)
           .execute()
    # deduplicate by item_id, keep latest
    ...
Fix 2 — Frontend: api.inventory.stock() → update to call /inventory/items:

stock: () => fetchJson<any>("/inventory/items"),
Quality Control (/quality-control)
Current state: QC dashboard likely empty. Expiry alerts may work if qc/expiry-alerts reads from sage_items_snapshot. Data available: 92 items with expiry_date, 78 already expired. Fix: Verify /qc/expiry-alerts endpoint reads from sage_items_snapshot. If not, update it to join or fallback to sage_items_snapshot. The expiry data is the MOST valuable clinical data we have — it must surface here.

Finance (all sub-pages)
Current state: All blank — no AR/AP/GL data. Data available: sage_coa_snapshot (204 accounts) ONLY. No invoices, no AR ledger, no GL amounts (encrypted). Fix: Finance pages will remain mostly blank. Add COA to GET /finance/coa if not present. Nothing else can be done without invoice export data.

Project Controls (/operations/project-controls)
Current state: ❌ HTML error — /controls/projects endpoint does not exist in backend. Fix: Add a stub router that returns empty lists gracefully (no 404/HTML crash):

# backend/src/routers/controls.py (new file)
@router.get("/projects")
async def list_projects(): return {"data": [], "total": 0}

@router.get("/readiness")
async def readiness(): return {"score": 0, "checks": []}
Register in app.py: app.include_router(controls_router, prefix="/controls") This stops the HTML error and shows an empty state instead.

Suppliers (/operations/suppliers)
Current state: Unknown — api.suppliers.list() → /suppliers. Check if populated. Data available: sage_vendors_snapshot (24 vendors) — close enough to suppliers. Fix: Check if /suppliers reads from sage_vendors_snapshot. If not, seed from vendors.

HR / Staff (/hr, /staff/*)
Current state: Empty — EMPLOYEE.DAT was empty, no payroll/HR records. Data available: None. Fix: Nothing to do. These pages are blank by design — client hasn't entered HR data in Sage.

ACE (/synbot)
Current state: Reports 0 customers — reads placeware_ar_ledger (empty AR). Fix: Same as Fix 2 in agents_exec.py — add customer_list query type. ACE will then answer customer questions from the real 155 rows in customers table.

Part 3 — Implementation Order (by impact)
Phase A — Backend only (docker cp, no rebuild needed)
#	File	Change	Impact
1	backend/src/services/crm.py	get_crm_stats() adds customer_count from customers	CRM KPIs show 155
2	backend/src/routers/agents_exec.py	Add customer_list query type	ACE knows about customers
3	backend/src/routers/inventory.py	Add GET /inventory/items reading from sage_items_snapshot	Inventory shows full fields
4	backend/src/services/inventory.py	get_inventory_summary() joins sage_items_snapshot for rich metadata	Ops inventory shows category/expiry
5	backend/src/routers/controls.py	New stub file: empty list endpoints	Project Controls stops crashing
6	backend/app.py	Register controls router at /controls prefix	Activates stub
Phase B — Frontend (requires rebuild)
#	File	Change	Impact
7	api-client.ts	api.inventory.stock() → /inventory/items; api.crm.customers() added	Stock + customer API calls work
8	CRM.tsx	Add customer count KPI + customer list table	CRM page shows real customers
9	data-assimilation/sage50/DAT_FILE_STATUS.md	Create tracking file	Audit record
Part 4 — Deployment Commands
# Phase A — backend files
docker cp "backend\src\services\crm.py" chat-backend.v1:/backend/src/services/crm.py
docker cp "backend\src\routers\agents_exec.py" chat-backend.v1:/backend/src/routers/agents_exec.py
docker cp "backend\src\routers\inventory.py" chat-backend.v1:/backend/src/routers/inventory.py
docker cp "backend\src\services\inventory.py" chat-backend.v1:/backend/src/services/inventory.py
docker cp "backend\src\routers\controls.py" chat-backend.v1:/backend/src/routers/controls.py
docker cp "backend\app.py" chat-backend.v1:/backend/app.py
docker restart chat-backend.v1

# Phase B — frontend rebuild
docker exec placeware-frontend.v1 sh -c "cd /app && npm run build"
docker restart placeware-frontend.v1
Part 5 — Verification Checklist
After deploy, check each page:

 CRM Overview: "Customers" KPI shows 155, customer list table visible
 Ask ACE "how many customers?" → answers with 155
 Operations inventory: items show category, cost_price, expiry_date, batch_number
 Dashboard: inventory section loads (no 404 error)
 Project Controls: shows empty state (no HTML crash)
 Lead Finder: still shows 1780 prospects ✓ (unchanged)
 QC Expiry Alerts: shows 78 expired items and 14 expiring soon
 Finance: COA shows 204 accounts; AR/AP remain blank (expected)
 curl http://localhost:8000/inventory/items | python -m json.tool | head -30
 curl http://localhost:8000/controls/projects → {"data": [], "total": 0}
 curl http://localhost:8000/dashboard/crm | python -m json.tool | grep customer_count