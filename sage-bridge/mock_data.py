"""
mock_data.py — Realistic fake Sage 50 data for local testing.

When SAGE_MOCK=true in sage-bridge/.env, all ODBC and SDK calls
return data from this module instead of hitting Pervasive PSQL or
the Sage SDK.  This lets you run a full SynBot ↔ Bridge round-trip
without the Sage application or a company file.

The sample data is modelled on a small Nigerian pharma distributor
(Placeware's domain) — realistic enough to exercise all code paths.
"""
from __future__ import annotations
from typing import Any, Dict, List

# ── Customers ─────────────────────────────────────────────────────────────────

MOCK_CUSTOMERS: List[Dict[str, Any]] = [
    {
        "id": "CUST001", "name": "Lagos General Hospital", "address1": "12 Broad Street",
        "city": "Lagos", "state": "LA", "zip": "101233", "country": "Nigeria",
        "phone": "+234-1-2345678", "email": "pharmacy@lgh.ng", "contact": "Dr. Adewale Okafor",
        "balance": 1250000.00, "credit_limit": 5000000.00, "is_active": True,
    },
    {
        "id": "CUST002", "name": "Abuja National Medical Centre", "address1": "PMB 55 Central District",
        "city": "Abuja", "state": "FC", "zip": "900001", "country": "Nigeria",
        "phone": "+234-9-5232100", "email": "procurement@anmc.gov.ng", "contact": "Mrs. Fatima Bello",
        "balance": 3780000.00, "credit_limit": 10000000.00, "is_active": True,
    },
    {
        "id": "CUST003", "name": "Kano State University Teaching Hospital", "address1": "Katsina Road",
        "city": "Kano", "state": "KN", "zip": "700001", "country": "Nigeria",
        "phone": "+234-64-660777", "email": "stores@ksuth.edu.ng", "contact": "Alhaji Musa Dantata",
        "balance": 620000.00, "credit_limit": 2000000.00, "is_active": True,
    },
    {
        "id": "CUST004", "name": "PharmaPlus Retail Chain", "address1": "45 Adeola Odeku Street",
        "city": "Lagos", "state": "LA", "zip": "101241", "country": "Nigeria",
        "phone": "+234-1-4611234", "email": "orders@pharmaplus.ng", "contact": "Chinwe Eze",
        "balance": 890000.00, "credit_limit": 3000000.00, "is_active": True,
    },
    {
        "id": "CUST005", "name": "HealthMart Dispensary", "address1": "7 Isaac John Street",
        "city": "Ikeja", "state": "LA", "zip": "100271", "country": "Nigeria",
        "phone": "+234-1-4964321", "email": "admin@healthmart.ng", "contact": "Tunde Adeleke",
        "balance": 0.00, "credit_limit": 500000.00, "is_active": True,
    },
]

# ── Vendors ───────────────────────────────────────────────────────────────────

MOCK_VENDORS: List[Dict[str, Any]] = [
    {
        "id": "VEND001", "name": "GlaxoSmithKline Nigeria Ltd", "address1": "1 Industrial Avenue",
        "city": "Lagos", "state": "LA", "zip": "100001", "country": "Nigeria",
        "phone": "+234-1-2633400", "email": "orders@ng.gsk.com", "contact": "Emeka Nwachukwu",
        "balance": 4500000.00, "is_active": True,
    },
    {
        "id": "VEND002", "name": "Emzor Pharmaceutical Industries", "address1": "8 Abimbola Street",
        "city": "Isolo", "state": "LA", "zip": "100263", "country": "Nigeria",
        "phone": "+234-1-7741222", "email": "supply@emzor.com.ng", "contact": "Dr. Stella Emeziem",
        "balance": 2100000.00, "is_active": True,
    },
    {
        "id": "VEND003", "name": "May & Baker Nigeria Plc", "address1": "3-5 Sapara Street",
        "city": "Ikeja", "state": "LA", "zip": "100271", "country": "Nigeria",
        "phone": "+234-1-4930100", "email": "orders@may-baker.com", "contact": "Ibrahim Suleiman",
        "balance": 1875000.00, "is_active": True,
    },
]

# ── Inventory ─────────────────────────────────────────────────────────────────

MOCK_INVENTORY: List[Dict[str, Any]] = [
    {
        "id": "AMO500", "description": "Amoxicillin 500mg Capsules (Pack of 1000)",
        "item_type": "Stock", "sales_price": 28500.00, "cost": 18200.00,
        "quantity_on_hand": 450.0, "quantity_on_order": 200.0, "reorder_quantity": 100.0,
        "sales_gl_account": "4000-00", "cogs_gl_account": "5000-00",
        "inventory_gl_account": "1300-00", "unit_of_measure": "Pack", "is_active": True,
    },
    {
        "id": "MET850", "description": "Metformin 850mg Tablets (Pack of 500)",
        "item_type": "Stock", "sales_price": 15200.00, "cost": 9400.00,
        "quantity_on_hand": 78.0, "quantity_on_order": 300.0, "reorder_quantity": 100.0,
        "sales_gl_account": "4000-00", "cogs_gl_account": "5000-00",
        "inventory_gl_account": "1300-00", "unit_of_measure": "Pack", "is_active": True,
    },
    {
        "id": "ART20", "description": "Artemether/Lumefantrine 20/120mg Tabs (Blister x24)",
        "item_type": "Stock", "sales_price": 4800.00, "cost": 3100.00,
        "quantity_on_hand": 12.0, "quantity_on_order": 0.0, "reorder_quantity": 50.0,
        "sales_gl_account": "4000-00", "cogs_gl_account": "5000-00",
        "inventory_gl_account": "1300-00", "unit_of_measure": "Blister", "is_active": True,
    },
    {
        "id": "ORS001", "description": "Oral Rehydration Salts Sachet (Box of 50)",
        "item_type": "Stock", "sales_price": 3200.00, "cost": 1800.00,
        "quantity_on_hand": 920.0, "quantity_on_order": 0.0, "reorder_quantity": 200.0,
        "sales_gl_account": "4000-00", "cogs_gl_account": "5000-00",
        "inventory_gl_account": "1300-00", "unit_of_measure": "Box", "is_active": True,
    },
    {
        "id": "PAR500", "description": "Paracetamol 500mg Tablets (Pack of 1000)",
        "item_type": "Stock", "sales_price": 8900.00, "cost": 5200.00,
        "quantity_on_hand": 1200.0, "quantity_on_order": 0.0, "reorder_quantity": 300.0,
        "sales_gl_account": "4000-00", "cogs_gl_account": "5000-00",
        "inventory_gl_account": "1300-00", "unit_of_measure": "Pack", "is_active": True,
    },
    {
        "id": "CIP500", "description": "Ciprofloxacin 500mg Tablets (Pack of 100)",
        "item_type": "Stock", "sales_price": 24000.00, "cost": 15500.00,
        "quantity_on_hand": 35.0, "quantity_on_order": 150.0, "reorder_quantity": 50.0,
        "sales_gl_account": "4000-00", "cogs_gl_account": "5000-00",
        "inventory_gl_account": "1300-00", "unit_of_measure": "Pack", "is_active": True,
    },
]

# ── Invoices (AR) ─────────────────────────────────────────────────────────────

MOCK_INVOICES: List[Dict[str, Any]] = [
    {
        "sage_id": "INV-2026-001", "customer_id": "CUST001",
        "date": "2026-01-15", "due_date": "2026-02-15",
        "invoice_number": "PWR/INV/2026/001", "po_number": "LGH/PO/2026/014",
        "total_amount": 712500.00, "amount_paid": 712500.00, "amount_due": 0.00,
        "is_paid": True, "note": "January supply — antibiotics + ACT",
        "lines": [
            {"item_id": "AMO500", "description": "Amoxicillin 500mg x25 packs", "quantity": 25.0, "unit_price": 28500.00},
            {"item_id": "ART20",  "description": "Artemether/Lumefantrine x100 blister", "quantity": 25.0, "unit_price": 4800.00},
        ],
    },
    {
        "sage_id": "INV-2026-002", "customer_id": "CUST002",
        "date": "2026-02-01", "due_date": "2026-03-01",
        "invoice_number": "PWR/INV/2026/002", "po_number": "ANMC/PROC/0041",
        "total_amount": 3780000.00, "amount_paid": 2000000.00, "amount_due": 1780000.00,
        "is_paid": False, "note": "Q1 bulk supply",
        "lines": [
            {"item_id": "MET850", "description": "Metformin 850mg x200 packs", "quantity": 200.0, "unit_price": 15200.00},
            {"item_id": "PAR500", "description": "Paracetamol 500mg x100 packs", "quantity": 100.0, "unit_price": 8900.00},
        ],
    },
    {
        "sage_id": "INV-2026-003", "customer_id": "CUST004",
        "date": "2026-03-10", "due_date": "2026-04-10",
        "invoice_number": "PWR/INV/2026/003", "po_number": "PP/2026/103",
        "total_amount": 890000.00, "amount_paid": 0.00, "amount_due": 890000.00,
        "is_paid": False, "note": "",
        "lines": [
            {"item_id": "CIP500", "description": "Ciprofloxacin 500mg x30 packs", "quantity": 30.0, "unit_price": 24000.00},
            {"item_id": "ORS001", "description": "ORS x50 boxes", "quantity": 50.0, "unit_price": 3200.00},
        ],
    },
]

# ── Accounts (Chart of Accounts) ──────────────────────────────────────────────

MOCK_ACCOUNTS: List[Dict[str, Any]] = [
    {"id": "1000-00", "description": "Cash - Zenith Bank Current",        "account_type": "Cash",                "balance": 12500000.00, "is_active": True},
    {"id": "1100-00", "description": "Cash - GTBank Savings",             "account_type": "Cash",                "balance": 3200000.00,  "is_active": True},
    {"id": "1200-00", "description": "Accounts Receivable",               "account_type": "Accounts Receivable", "balance": 6040000.00,  "is_active": True},
    {"id": "1300-00", "description": "Pharmaceutical Inventory",          "account_type": "Inventory",           "balance": 9870000.00,  "is_active": True},
    {"id": "2000-00", "description": "Accounts Payable",                  "account_type": "Accounts Payable",    "balance": 8475000.00,  "is_active": True},
    {"id": "4000-00", "description": "Product Sales Revenue",             "account_type": "Income",              "balance": 45200000.00, "is_active": True},
    {"id": "5000-00", "description": "Cost of Goods Sold",                "account_type": "Cost of Sales",       "balance": 28100000.00, "is_active": True},
    {"id": "6000-00", "description": "Salaries & Wages",                  "account_type": "Expenses",            "balance": 4800000.00,  "is_active": True},
    {"id": "6100-00", "description": "Rent & Facilities",                 "account_type": "Expenses",            "balance": 900000.00,   "is_active": True},
    {"id": "6200-00", "description": "Transport & Logistics",             "account_type": "Expenses",            "balance": 620000.00,   "is_active": True},
    {"id": "3000-00", "description": "Share Capital",                     "account_type": "Equity",              "balance": 20000000.00, "is_active": True},
    {"id": "3100-00", "description": "Retained Earnings",                 "account_type": "Equity",              "balance": 11800000.00, "is_active": True},
]

# ── Employees ─────────────────────────────────────────────────────────────────

MOCK_EMPLOYEES: List[Dict[str, Any]] = [
    {
        "id": "EMP001", "first_name": "Oluwaseun", "last_name": "Adesanya",
        "phone": "+234-803-1234567", "email": "o.adesanya@placeware.ng",
        "hire_date": "2019-03-01", "pay_type": "Salary", "pay_frequency": "Monthly",
        "department": "Sales", "is_active": True,
    },
    {
        "id": "EMP002", "first_name": "Ngozi", "last_name": "Okwu",
        "phone": "+234-807-9876543", "email": "n.okwu@placeware.ng",
        "hire_date": "2020-07-15", "pay_type": "Salary", "pay_frequency": "Monthly",
        "department": "Warehouse", "is_active": True,
    },
    {
        "id": "EMP003", "first_name": "Yusuf", "last_name": "Lawal",
        "phone": "+234-805-4561234", "email": "y.lawal@placeware.ng",
        "hire_date": "2021-01-10", "pay_type": "Salary", "pay_frequency": "Monthly",
        "department": "Finance", "is_active": True,
    },
]

# ── Sales Orders ──────────────────────────────────────────────────────────────

MOCK_SALES_ORDERS: List[Dict[str, Any]] = [
    {
        "sage_id": "SO-2026-001", "customer_id": "CUST003",
        "date": "2026-04-05", "ship_date": "2026-04-12",
        "po_number": "KSUTH/2026/009", "total_amount": 620000.00,
        "lines": [
            {"item_id": "AMO500", "quantity": 20.0, "unit_price": 28500.00},
            {"item_id": "PAR500", "quantity": 10.0, "unit_price": 8900.00},
        ],
    },
]

# ── Purchase Orders ───────────────────────────────────────────────────────────

MOCK_PURCHASE_ORDERS: List[Dict[str, Any]] = [
    {
        "sage_id": "PO-2026-001", "vendor_id": "VEND001",
        "date": "2026-04-01", "expected_date": "2026-04-20",
        "reference": "GSK/Q2/RESTOCK", "total_amount": 4500000.00,
        "lines": [
            {"item_id": "AMO500", "quantity": 100.0, "unit_price": 18200.00},
            {"item_id": "CIP500", "quantity": 80.0, "unit_price": 15500.00},
        ],
    },
    {
        "sage_id": "PO-2026-002", "vendor_id": "VEND003",
        "date": "2026-04-10", "expected_date": "2026-04-25",
        "reference": "MAYBAKER/Q2", "total_amount": 1875000.00,
        "lines": [
            {"item_id": "MET850", "quantity": 200.0, "unit_price": 9400.00},
        ],
    },
]

# ── Payments (Customer Receipts) ──────────────────────────────────────────────

MOCK_PAYMENTS: List[Dict[str, Any]] = [
    {
        "sage_id": "RCPT-2026-001", "customer_id": "CUST001",
        "date": "2026-02-20", "amount": 712500.00,
        "reference": "ZENITH/TXN/4451223", "invoice_ids": ["INV-2026-001"],
    },
    {
        "sage_id": "RCPT-2026-002", "customer_id": "CUST002",
        "date": "2026-03-15", "amount": 2000000.00,
        "reference": "GTB/TXN/8870012", "invoice_ids": ["INV-2026-002"],
    },
]

# ── Journal Entries ───────────────────────────────────────────────────────────

MOCK_JOURNAL: List[Dict[str, Any]] = [
    {
        "sage_id": "JNL-2026-001", "date": "2026-03-31", "reference": "Q1-ADJ-001",
        "memo": "Q1 inventory adjustment — expired stock write-off",
        "lines": [
            {"gl_account": "5000-00", "description": "Expired stock COGS adjustment", "debit": 125000.00, "credit": 0.00},
            {"gl_account": "1300-00", "description": "Inventory reduction",            "debit": 0.00, "credit": 125000.00},
        ],
    },
]

# ── Company Info ──────────────────────────────────────────────────────────────

MOCK_COMPANY: Dict[str, Any] = {
    "name": "Placeware Pharmaceuticals Limited",
    "address": "14 Commercial Avenue, Sabo, Yaba, Lagos",
    "phone": "+234-1-2930100",
    "email": "info@placeware.ng",
    "fiscal_year_end": "December 31",
    "company_id": "PWPH2019001",
}

# ── Payroll ───────────────────────────────────────────────────────────────────

MOCK_PAYROLL: List[Dict[str, Any]] = [
    {"sage_id": "PAY-2026-001", "employee_id": "EMP001", "date": "2026-03-31", "gross": 450000.00, "net": 382500.00, "tax": 67500.00},
    {"sage_id": "PAY-2026-002", "employee_id": "EMP002", "date": "2026-03-31", "gross": 280000.00, "net": 238000.00, "tax": 42000.00},
    {"sage_id": "PAY-2026-003", "employee_id": "EMP003", "date": "2026-03-31", "gross": 380000.00, "net": 323000.00, "tax": 57000.00},
]

# ── Vendor Bills (AP) ─────────────────────────────────────────────────────────

MOCK_VENDOR_BILLS: List[Dict[str, Any]] = [
    {
        "sage_id": "BILL-2026-001", "vendor_id": "VEND001",
        "date": "2026-04-20", "due_date": "2026-05-20",
        "reference": "GSK/INV/2026/0441", "total_amount": 4500000.00,
        "is_paid": False, "lines": [],
    },
    {
        "sage_id": "BILL-2026-002", "vendor_id": "VEND003",
        "date": "2026-04-25", "due_date": "2026-05-25",
        "reference": "MB/INV/2026/1102", "total_amount": 1875000.00,
        "is_paid": False, "lines": [],
    },
]

# ── Quotes ────────────────────────────────────────────────────────────────────

MOCK_QUOTES: List[Dict[str, Any]] = [
    {
        "sage_id": "QT-2026-001", "customer_id": "CUST005",
        "date": "2026-04-28", "expiry_date": "2026-05-28",
        "total_amount": 148500.00,
        "lines": [
            {"item_id": "ORS001", "quantity": 20.0, "unit_price": 3200.00},
            {"item_id": "PAR500", "quantity": 10.0, "unit_price": 8900.00},
        ],
    },
]

# ── Jobs ──────────────────────────────────────────────────────────────────────

MOCK_JOBS: List[Dict[str, Any]] = [
    {
        "sage_id": "JOB-2026-001", "description": "NAFDAC Compliance Audit — Q1",
        "customer_id": "", "status": "Open",
        "start_date": "2026-01-01", "end_date": "2026-03-31",
        "estimated_revenue": 0.00, "actual_revenue": 0.00,
    },
]


# ── Helper — filter + paginate ────────────────────────────────────────────────

def paginate(data: List[Dict], limit: int, offset: int) -> List[Dict]:
    return data[offset: offset + limit]


def search_field(data: List[Dict], field: str, term: str) -> List[Dict]:
    term = term.lower()
    return [row for row in data if term in str(row.get(field, "")).lower()]
