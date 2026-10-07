# Synbot Financial Backend & Frontend Implementation Specification

**Version:** 1.0
**Status:** Engineering Baseline
**Architecture:** Modular Monolith
**Backend:** FastAPI + PostgreSQL
**Frontend:** React + TypeScript + Vite
**Primary Objective:** Replace the client's Sage-based financial system with Synbot Financial OS.

---

# 1. Engineering Philosophy

The implementation must follow five principles.

### 1.1 Accounting is the centre

Sales, procurement, inventory, banking, assets and payroll are operational domains.

Accounting is the financial truth.

### 1.2 Modules own their data

A module may own its tables and business rules.

It must not directly modify another module's data.

Cross-domain activity happens through services.

### 1.3 Financial posting is centralized

No module creates its own journal logic.

Everything goes through:

```text
PostingService
```

### 1.4 Frontend is never the financial authority

React displays and submits intent.

The backend validates and determines financial consequences.

### 1.5 AI is an observer and analyst

AI can understand financial information.

AI does not bypass normal financial controls.

---

# 2. Repository Structure

The initial repository should be organized approximately as follows:

```text
synbot-financial/
│
├── backend/
│   │
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── dependencies.py
│   │   │
│   │   ├── core/
│   │   │   ├── database.py
│   │   │   ├── security.py
│   │   │   ├── exceptions.py
│   │   │   ├── middleware.py
│   │   │   ├── logging.py
│   │   │   └── pagination.py
│   │   │
│   │   ├── organization/
│   │   ├── identity/
│   │   ├── master_data/
│   │   │
│   │   ├── accounting/
│   │   ├── sales/
│   │   ├── receivables/
│   │   ├── procurement/
│   │   ├── payables/
│   │   ├── inventory/
│   │   ├── banking/
│   │   ├── fixed_assets/
│   │   ├── hr/
│   │   ├── payroll/
│   │   ├── budgeting/
│   │   ├── tax/
│   │   ├── approvals/
│   │   ├── audit/
│   │   ├── documents/
│   │   ├── reporting/
│   │   └── intelligence/
│   │
│   ├── migrations/
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   ├── accounting/
│   │   ├── api/
│   │   └── e2e/
│   │
│   ├── scripts/
│   ├── Dockerfile
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   ├── auth/
│   │   ├── components/
│   │   ├── layouts/
│   │   ├── modules/
│   │   │   ├── dashboard/
│   │   │   ├── finance/
│   │   │   ├── sales/
│   │   │   ├── procurement/
│   │   │   ├── inventory/
│   │   │   ├── banking/
│   │   │   ├── hr/
│   │   │   ├── payroll/
│   │   │   ├── assets/
│   │   │   ├── budgeting/
│   │   │   ├── reports/
│   │   │   └── intelligence/
│   │   │
│   │   ├── services/
│   │   ├── hooks/
│   │   ├── types/
│   │   ├── utils/
│   │   └── routes/
│   │
│   ├── public/
│   ├── package.json
│   └── vite.config.ts
│
├── docs/
│   ├── architecture/
│   ├── api/
│   ├── accounting/
│   ├── workflows/
│   ├── migration/
│   └── decisions/
│
├── docker/
├── .env.example
├── docker-compose.yml
└── README.md
```

---

# 3. Backend Domain Contract

Every domain should follow a predictable internal structure.

Example:

```text
sales/
├── models.py
├── schemas.py
├── repository.py
├── service.py
├── router.py
├── validators.py
├── accounting.py
└── tests/
```

### Responsibilities

**models.py**

Database models only.

**schemas.py**

Request/response validation.

**repository.py**

Database access.

**service.py**

Business logic.

**validators.py**

Domain validation.

**accounting.py**

Defines the accounting event produced by the domain.

**router.py**

HTTP/API layer.

---

# 4. Dependency Direction

The dependency direction must remain controlled.

```text
Router
   ↓
Service
   ↓
Repository
   ↓
Database
```

Accounting interaction:

```text
Domain Service
      ↓
Accounting Event
      ↓
PostingService
      ↓
Journal Engine
```

Never:

```text
Router → Database
```

and never:

```text
Frontend → Accounting Tables
```

---

# 5. Database Strategy

Use PostgreSQL as the primary transactional database.

All financial tables must contain the required organizational scope.

Where applicable:

```text
organization_id
legal_entity_id
branch_id
department_id
cost_centre_id
```

Not every table needs every field.

The engineering agent must determine the minimum appropriate scope for each entity rather than blindly adding every column.

---

# 6. Database Naming

Use:

```text
snake_case
```

Primary keys:

```text
id
```

Foreign keys:

```text
customer_id
supplier_id
product_id
account_id
```

Dates:

```text
created_at
updated_at
posted_at
approved_at
```

Financial amounts:

```text
numeric
```

Do not use floating-point types for financial amounts.

---

# 7. Financial Amount Model

Money should be represented with explicit precision.

Conceptually:

```text
amount
currency_id
exchange_rate
base_amount
```

This allows future multi-currency support without redesigning the accounting engine.

---

# 8. Accounting Core Models

The minimum accounting core consists of:

```text
financial_periods
account_groups
accounts

accounting_events

journal_entries
journal_lines
```

A journal entry:

```text
journal_entry
    ├── journal_line
    ├── journal_line
    ├── journal_line
    └── ...
```

Each line contains either a debit or credit.

Never both.

---

# 9. Posting Service Contract

The central service should conceptually expose:

```python
PostingService.post(
    accounting_event,
    context
)
```

Internally:

```text
validate_event()
        ↓
validate_period()
        ↓
resolve_accounts()
        ↓
build_journal()
        ↓
validate_balance()
        ↓
validate_permissions()
        ↓
persist_journal()
        ↓
mark_event_posted()
        ↓
create_audit_event()
        ↓
commit()
```

Everything occurs within the appropriate database transaction.

---

# 10. Accounting Event

An accounting event should identify:

```text
event_id
event_type
source_type
source_id
organization_id
legal_entity_id
financial_period_id
event_date
currency
metadata
status
```

Examples:

```text
SALE_INVOICE_POSTED
CUSTOMER_PAYMENT_POSTED
PURCHASE_INVOICE_POSTED
SUPPLIER_PAYMENT_POSTED
INVENTORY_ADJUSTMENT_POSTED
ASSET_ACQUISITION_POSTED
DEPRECIATION_POSTED
PAYROLL_POSTED
MANUAL_JOURNAL_POSTED
```

This gives Synbot a universal financial event stream.

---

# 11. Example: Sales Invoice Posting

The sales service creates the invoice.

It does **not** directly manipulate the GL.

It creates:

```text
SALE_INVOICE_POSTED
```

The accounting service determines:

```text
AR
Revenue
COGS
Inventory
Tax
Other Charges
```

The final journal is generated and posted.

---

# 12. Example: Inventory Adjustment

Inventory service:

```text
Create Adjustment
       ↓
Validate
       ↓
Approve
       ↓
Inventory Transaction
       ↓
Accounting Event
```

Accounting determines the appropriate adjustment account.

This prevents inventory from developing an isolated accounting system.

---

# 13. Transaction Boundary

For financial posting:

```text
BEGIN TRANSACTION

create accounting event
create journal
create journal lines
validate balance
post
create audit event

COMMIT
```

If any step fails:

```text
ROLLBACK
```

This is a critical requirement.

---

# 14. Idempotency

Financial POST endpoints must accept:

```text
Idempotency-Key
```

Example:

```http
POST /api/v1/sales/invoices/INV-1001/post
Idempotency-Key: 2a8b...
```

If the request is accidentally submitted twice, Synbot must not create two accounting events.

---

# 15. Sales Service

Core services:

```text
SalesOrderService
DeliveryService
SalesInvoiceService
CreditNoteService
SalesReturnService
```

Sales Invoice Service:

```text
create()
validate()
submit()
approve()
post()
void()
```

Posting calls:

```text
PostingService
```

---

# 16. AR Service

Core services:

```text
CustomerPaymentService
PaymentAllocationService
ARBalanceService
ARAgingService
CustomerStatementService
```

Customer balance should be derived from financial transactions.

Do not maintain arbitrary manually updated balances.

---

# 17. Procurement Service

Core services:

```text
PurchaseRequestService
PurchaseOrderService
GoodsReceiptService
SupplierInvoiceService
SupplierReturnService
```

Supplier invoice service should support duplicate detection.

Recommended duplicate key:

```text
supplier_id
+
supplier_invoice_number
```

with appropriate normalization.

---

# 18. AP Service

Core services:

```text
SupplierPaymentService
APBalanceService
APAgingService
SupplierStatementService
```

Supplier balances must reconcile back to accounting.

---

# 19. Inventory Service

Core services:

```text
InventoryMovementService
InventoryBalanceService
BatchService
StockTransferService
StockAdjustmentService
StockCountService
StockLoanService
RecallService
InventoryValuationService
```

Inventory transactions are immutable history.

Balances are derived.

---

# 20. Batch Service

A batch record should contain at minimum:

```text
product_id
batch_number
manufacturing_date
expiry_date
unit_cost
status
```

Batch movement must be traceable.

---

# 21. Banking Service

Core services:

```text
BankAccountService
BankTransactionService
BankStatementService
BankMatchingService
BankReconciliationService
CashService
```

Matching should be designed so automated matching can be introduced progressively.

---

# 22. Fixed Asset Service

Core services:

```text
AssetService
AssetAcquisitionService
DepreciationService
AssetDisposalService
AssetTransferService
```

Depreciation should produce accounting events rather than directly writing journal rows.

---

# 23. HR Service

Core services:

```text
EmployeeService
EmploymentService
CompensationService
AttendanceService
LeaveService
EmployeeLoanService
```

HR owns employee information.

Payroll consumes approved HR information.

---

# 24. Payroll Service

Core services:

```text
PayrollPeriodService
PayrollCalculationService
PayrollApprovalService
PayrollPostingService
PayslipService
PayrollPaymentService
```

Payroll flow:

```text
Payroll Period
      ↓
Gather Employees
      ↓
Load Compensation
      ↓
Load Attendance
      ↓
Load Leave
      ↓
Calculate Earnings
      ↓
Calculate Deductions
      ↓
Calculate Net Pay
      ↓
Review
      ↓
Approve
      ↓
Post
      ↓
Pay
```

The statutory calculation engine remains a research-gated component until Nigerian requirements are formally verified.

---

# 25. Reporting Architecture

Do not build every report as an independent SQL query.

Create a reporting layer.

```text
ReportingService
      ↓
ReportDefinition
      ↓
Query Builder / SQL
      ↓
Financial Read Model
      ↓
Report
```

Reports should share common accounting queries.

---

# 26. Read Models

For dashboards and heavy reporting, create derived read models.

Examples:

```text
gl_account_summary
customer_balance_summary
supplier_balance_summary
inventory_summary
cash_position_summary
payroll_summary
```

These are **not authoritative financial records**.

They can be rebuilt from source transactions.

---

# 27. Report Drill-Down

Every financial report should expose lineage.

Example:

```text
Income Statement
       ↓
Revenue Account
       ↓
GL Entries
       ↓
Journal Entry
       ↓
Accounting Event
       ↓
Sales Invoice
       ↓
Customer
```

This is one of the major differentiators of the system.

---

# 28. API Response Standard

Successful responses should have consistent structures.

Example:

```json
{
  "data": {},
  "meta": {
    "request_id": "...",
    "timestamp": "..."
  }
}
```

Paginated:

```json
{
  "data": [],
  "meta": {
    "page": 1,
    "page_size": 50,
    "total": 1250,
    "request_id": "..."
  }
}
```

---

# 29. Error Contract

Example:

```json
{
  "error": {
    "code": "CREDIT_LIMIT_EXCEEDED",
    "message": "Customer credit limit would be exceeded.",
    "details": {
      "credit_limit": 10000000,
      "current_exposure": 8500000,
      "requested_amount": 2500000
    },
    "request_id": "..."
  }
}
```

The frontend should be able to display useful business-level errors rather than generic server failures.

---

# 30. Authentication & Authorization

Every request should resolve:

```text
user
organization
legal_entity_scope
branch_scope
roles
permissions
```

Permissions use:

```text
domain.resource.action
```

Examples:

```text
sales.invoice.create
sales.invoice.approve
sales.invoice.post

inventory.adjustment.approve
inventory.recall.create

payroll.run.approve
payroll.run.post

accounting.journal.post
finance.period.close
```

---

# 31. Visibility vs Action Permissions

These must be separate.

A user may be allowed to:

```text
VIEW invoice
```

without being allowed to:

```text
POST invoice
```

Similarly:

```text
VIEW payroll
```

does not imply:

```text
APPROVE payroll
```

---

# 32. Frontend Application Structure

The React application should use a domain-oriented structure.

```text
src/
├── app/
├── layouts/
├── routes/
├── components/
│
├── modules/
│   ├── dashboard/
│   ├── finance/
│   ├── sales/
│   ├── procurement/
│   ├── inventory/
│   ├── banking/
│   ├── hr/
│   ├── payroll/
│   ├── assets/
│   ├── budgeting/
│   ├── reports/
│   └── intelligence/
│
├── services/
├── hooks/
├── types/
└── utils/
```

---

# 33. Global Application Shell

The shell should contain:

```text
┌──────────────────────────────────────────┐
│ Logo │ Company │ Search │ Alerts │ User │
├────────────┬─────────────────────────────┤
│            │                             │
│ Navigation │       Application           │
│            │       Workspace              │
│            │                             │
└────────────┴─────────────────────────────┘
```

The company switcher is globally available.

---

# 34. Company Context

When the user changes company:

```text
Company A
```

all relevant:

* dashboards;
* customers;
* suppliers;
* products;
* transactions;
* reports;
* payroll;
* budgets

must automatically operate within that company context.

The backend must independently enforce the scope.

The frontend must never be trusted to provide isolation.

---

# 35. Reusable Financial Components

Build these early.

```text
DataTable
FilterBar
DateRangePicker
CurrencyInput
AmountDisplay
StatusBadge
ApprovalBadge
EntityHeader
EntityTimeline
KPI Card
ChartCard
DrillDownLink
AuditTimeline
DocumentUploader
DocumentViewer
ConfirmationDialog
ExceptionPanel
EmptyState
```

This will dramatically reduce UI duplication.

---

# 36. Universal Entity Page

Every major business entity should use the same pattern.

Example:

```text
┌─────────────────────────────────────────┐
│ Customer: ABC Limited                   │
│ Status | Credit Limit | Balance         │
├─────────────────────────────────────────┤
│ Overview | Transactions | Documents     │
│ Payments | Statements | Timeline        │
├─────────────────────────────────────────┤
│                                         │
│              Content                    │
│                                         │
└─────────────────────────────────────────┘
```

The same concept should apply to:

* customers;
* suppliers;
* products;
* employees;
* assets.

---

# 37. Exception-First UX

The application should not merely show numbers.

It should surface what needs attention.

Examples:

```text
⚠ 4 overdue customer accounts
⚠ 2 bank reconciliation exceptions
⚠ 7 supplier invoices awaiting approval
⚠ 1 batch approaching expiry
⚠ 3 stock adjustments awaiting approval
⚠ Payroll awaiting approval
```

The user should be able to move directly from the exception to the underlying transaction.

---

# 38. Posting Confirmation UX

Before an irreversible financial action:

```text
Post Invoice?
```

Show:

```text
Customer
Invoice
Amount
Tax
AR Impact
Revenue Impact
Inventory Impact
COGS Impact
Financial Period
```

Then:

```text
Cancel
Confirm & Post
```

This makes the consequences of a transaction explicit.

---

# 39. Approval Centre

Build one unified approval interface.

```text
Approval Centre

Invoices       12
Purchases       4
Stock Adjust.   3
Payroll         1
Journals        2
Expenses        6
```

Each approval should show:

* requester;
* amount;
* entity;
* reason;
* financial impact;
* supporting documents;
* history.

---

# 40. Period Close Workspace

This should be a dedicated screen rather than a single button.

Example:

```text
JUNE 2026 CLOSE

✓ All invoices posted
✓ Trial balance balanced
✓ AR reconciled
✓ AP reconciled
✓ Inventory reconciled
⚠ 2 bank exceptions
✓ Payroll posted

[View Exceptions]

Close Period
```

Closing must remain blocked while critical exceptions exist.

---

# 41. Finance Control Tower

Initial dashboard:

```text
Revenue
Expenses
Net Profit
Cash
AR
AP
Inventory
Overdue AR
Overdue AP
```

Then:

```text
Revenue Trend
Cash Position
AR Ageing
AP Ageing
Top Customers
Top Products
Expense Breakdown
Budget Variance
Exceptions
```

---

# 42. Finance AI Interface

The AI screen should not simply be a chatbot.

It should behave like a financial analysis workspace.

Example:

```text
USER:
Why did profit fall this month?

AI:
Net profit decreased by ₦X compared with the prior period.

Primary drivers:
1. Expense category A +X%
2. Revenue category B -X%
3. COGS +X%

Supporting records:
[View Expense Account]
[View Revenue Account]
[View GL Entries]
```

Every numerical claim must be traceable to backend data.

---

# 43. AI Guardrails

The Finance AI must:

* query approved financial data;
* respect user permissions;
* respect company scope;
* identify the reporting period;
* distinguish actuals from forecasts;
* provide source references;
* state uncertainty;
* never invent financial values;
* never post transactions directly.

If a user asks:

> "Post this invoice."

The AI should initiate the controlled workflow, not directly manipulate the database.

---

# 44. Background Jobs

Use background processing for:

* large reports;
* exports;
* payroll calculations;
* document processing;
* bank statement processing;
* anomaly detection;
* AI analysis;
* heavy reconciliation;
* scheduled reporting.

Do **not** move ordinary financial posting into an uncontrolled asynchronous process merely for convenience.

Financial posting should remain transactional and predictable.

---

# 45. Document Architecture

Documents should be linked to business entities.

Example:

```text
Supplier Invoice
      ↓
Document
```

or:

```text
Employee
      ↓
Employment Contract
```

Document metadata:

```text
document_id
document_type
filename
storage_location
uploaded_by
uploaded_at
checksum
entity_type
entity_id
```

---

# 46. Audit Architecture

Audit events should be append-only.

Example:

```json
{
  "actor_id": "...",
  "action": "INVOICE_POSTED",
  "entity_type": "sales_invoice",
  "entity_id": "...",
  "timestamp": "...",
  "metadata": {}
}
```

For sensitive modifications, capture before/after state where appropriate.

---

# 47. Migration Engine

The migration engine should be separate from the production accounting modules.

```text
migration/
├── extract/
├── transform/
├── validate/
├── reconcile/
├── load/
└── reports/
```

Its job is:

```text
Legacy Data
   ↓
Mapping
   ↓
Transformation
   ↓
Validation
   ↓
Synbot Import
```

It must not become a permanent Sage compatibility layer.

---

# 48. Migration Validation

For each migrated financial area:

```text
Source Total
      ↓
Transformation
      ↓
Target Total
      ↓
Difference
```

Generate reconciliation reports.

Examples:

```text
AR source total
AR Synbot total
Difference

AP source total
AP Synbot total
Difference

Inventory source valuation
Synbot inventory valuation
Difference
```

---

# 49. Testing Pyramid

```text
                E2E
               /   \
          API Tests
             /   \
      Integration Tests
           /       \
       Unit Tests
```

But financial testing gets an additional layer:

```text
Financial Invariant Tests
```

These must run continuously.

---

# 50. Golden Financial Scenarios

The development engine must maintain a set of fixed scenarios.

Example:

### Scenario

Customer purchases:

```text
10 units
₦100,000
```

Expected:

```text
AR +₦100,000
Revenue +₦100,000
```

If inventory cost is:

```text
₦60,000
```

Expected:

```text
COGS +₦60,000
Inventory -₦60,000
```

The exact scenario data can vary, but the expected accounting result must be explicit.

This becomes the regression standard.

---

# 51. CI/CD

Every pull request should run:

```text
Lint
↓
Type Check
↓
Unit Tests
↓
Integration Tests
↓
Accounting Tests
↓
API Contract Tests
↓
Migration Test
↓
Build
```

Production deployment should only occur after successful completion.

---

# 52. Database Migration Policy

Every schema change requires an Alembic migration.

Never modify production schema manually.

Migration must be:

* versioned;
* reversible where practical;
* tested against representative data.

---

# 53. Logging

Every request should have:

```text
request_id
user_id
organization_id
route
timestamp
duration
status
```

Financial operations should additionally expose:

```text
transaction_id
accounting_event_id
journal_id
```

This makes debugging significantly easier.

---

# 54. Observability

Initial production monitoring should track:

* API errors;
* database errors;
* failed financial postings;
* failed background jobs;
* reconciliation failures;
* payroll failures;
* report failures;
* authentication failures;
* unusual transaction volume.

---

# 55. Security Baseline

Minimum requirements:

* secure authentication;
* password hashing;
* token/session management;
* RBAC;
* company isolation;
* HTTPS;
* encrypted secrets;
* audit logs;
* database backups;
* controlled document access.

Financial data should never be exposed through an unrestricted API endpoint.

---

# 56. Development Agent Protocol

This is important because the system will eventually be developed using your internal development engine/agents.

Every agent must receive:

```text
PROJECT CONTEXT
DOMAIN
TASK
DEPENDENCIES
DATABASE IMPACT
ACCOUNTING IMPACT
API IMPACT
FRONTEND IMPACT
PERMISSIONS
AUDIT
TESTS
ACCEPTANCE CRITERIA
```

---

# 57. Agent Task Format

Every generated development task should look conceptually like:

```text
TASK
Implement customer payment allocation.

CONTEXT
Customer payments settle outstanding AR invoices.

DEPENDENCIES
Customer
Invoice
AR
Bank/Cash
Accounting

DATABASE
customer_payments
payment_allocations

SERVICES
CustomerPaymentService
PaymentAllocationService
PostingService

ACCOUNTING
DR Bank/Cash
CR Accounts Receivable

API
POST /customer-payments
POST /customer-payments/{id}/allocate
POST /customer-payments/{id}/post

FRONTEND
Payment creation
Invoice allocation
Payment confirmation

PERMISSIONS
ar.payment.create
ar.payment.post

AUDIT
Payment created
Payment allocated
Payment posted

TESTS
Full payment
Partial payment
Overpayment
Invalid invoice
Closed period
Duplicate request

ACCEPTANCE
Payment posts once and customer balance reconciles.
```

This is the format I would use for your development engine.

---

# 58. Agent Stop Conditions

An agent must stop and request clarification when:

* a financial rule is undefined;
* tax treatment is unknown;
* accounting treatment is ambiguous;
* conflicting requirements exist;
* the required source data does not exist;
* a permission model is unclear;
* the change could affect posted financial history.

The agent must **not invent accounting policy**.

---

# 59. Agent Completion Conditions

An agent cannot declare a feature complete merely because:

```text
API works
```

or:

```text
UI works
```

Completion requires:

```text
Database
+
Service
+
API
+
Accounting
+
Permissions
+
Audit
+
Tests
+
Frontend
```

where applicable.

---

# 60. Recommended Build Sequence for the Actual Coding Agent

The first coding sprint should be deliberately boring.

### Sprint 1

```text
Repository
Docker
PostgreSQL
FastAPI
React
Environment Configuration
Alembic
Authentication Foundation
Health Checks
Logging
```

### Sprint 2

```text
Organization
Legal Entity
Branch
Department
Cost Centre
Users
Roles
Permissions
```

### Sprint 3

```text
Currencies
Financial Periods
COA
Account Groups
Accounts
```

### Sprint 4

```text
Accounting Events
Journal Entries
Journal Lines
PostingService
Trial Balance
GL
```

### Sprint 5

Build the first complete vertical slice:

```text
Customer
↓
Invoice
↓
Post
↓
AR
↓
Revenue
↓
GL
↓
Income Statement
```

Do not proceed to dozens of screens before this vertical slice is working.

---

# 61. First Vertical Slice

This is the most important recommendation in the entire implementation plan.

Build **one complete financial transaction** from UI to financial statement.

```text
Create Customer
      ↓
Create Invoice
      ↓
Validate
      ↓
Approve
      ↓
Post
      ↓
Accounting Event
      ↓
Journal
      ↓
GL
      ↓
AR Balance
      ↓
Revenue
      ↓
Income Statement
      ↓
Audit Trail
```

Then test it thoroughly.

Once this works, use the same architecture to add:

```text
Payment
Purchase
Inventory
Banking
Payroll
```

This proves the core architecture before the project becomes large.

---

# 62. Second Vertical Slice

After sales:

```text
Supplier
↓
Purchase Order
↓
Goods Receipt
↓
Supplier Invoice
↓
AP
↓
Inventory / Expense
↓
Journal
↓
GL
↓
Supplier Balance
```

---

# 63. Third Vertical Slice

Then:

```text
Product
↓
Purchase
↓
Stock
↓
Sale
↓
COGS
↓
Inventory Balance
↓
Profit
```

This proves the most important cross-domain relationship:

```text
Inventory ↔ Accounting
```

---

# 64. Fourth Vertical Slice

Then:

```text
Employee
↓
Compensation
↓
Payroll
↓
Approval
↓
Payroll Journal
↓
GL
↓
Payslip
```

This proves:

```text
HR ↔ Payroll ↔ Accounting
```

---

# 65. The Strategic Result

Once these four vertical slices work:

```text
Sales ↔ AR ↔ Accounting
Procurement ↔ AP ↔ Accounting
Inventory ↔ Accounting
HR ↔ Payroll ↔ Accounting
```

the remaining modules become controlled extensions of an already-proven architecture.

That is much safer than trying to build the entire ERP simultaneously.

---

# 66. Final Engineering Rule

If there is ever a conflict between:

```text
Fast implementation
```

and:

```text
Financial correctness
```

choose financial correctness.

If there is a conflict between:

```text
Convenient UI
```

and:

```text
Accounting integrity
```

choose accounting integrity.

If there is a conflict between:

```text
AI autonomy
```

and:

```text
Financial control
```

choose financial control.

The AI can become extremely capable later.

The accounting core must be deterministic.

---

# 67. Immediate Next Build Target

The first implementation package should therefore be:

```text
SYNBOT FINANCIAL FOUNDATION
```

containing:

1. PostgreSQL schema foundation
2. Organization model
3. Legal entity
4. Branch
5. Department
6. Cost centre
7. User/RBAC foundation
8. Currency
9. Financial period
10. Chart of Accounts
11. Account groups
12. Accounts
13. Accounting event
14. Journal entry
15. Journal lines
16. PostingService
17. Trial Balance
18. General Ledger
19. Audit event
20. Initial financial APIs
21. Initial React shell
22. Finance dashboard foundation
23. Golden accounting tests

Only after this passes should the Sales/AR vertical slice begin.

---

# 68. Definition of the Synbot Financial Core

At the end of Foundation, the following statement should be true:

> **Synbot can accept a valid financial event, determine its accounting treatment, create a balanced journal, post it into the General Ledger, preserve an immutable audit trail, and expose the resulting financial position through an API and frontend.**

If we can prove that statement, we have built the heart of the replacement system.

Everything else is expansion.
