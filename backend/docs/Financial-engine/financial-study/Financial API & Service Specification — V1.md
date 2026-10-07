# Synbot Financial API & Service Specification — V1

## 1. Purpose

This document defines the application-service and API layer for the Synbot Financial Operating System.

It establishes:

* service ownership;
* API boundaries;
* endpoint structure;
* commands and queries;
* request/response conventions;
* validation;
* approval;
* posting;
* accounting integration;
* permissions;
* error handling;
* idempotency;
* transaction boundaries;
* cross-module workflows;
* reporting access;
* AI access.

The API must preserve the core Synbot principle:

> **The frontend requests business operations. Domain services validate and execute them. The accounting engine creates the financial consequences.**

---

# 2. API Architecture

The API sits between the frontend and domain services.

```text
┌─────────────────────────────┐
│        Synbot Frontend      │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│       API / Router Layer    │
│ Authentication              │
│ Authorization               │
│ Request Validation           │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│      Application Services   │
│ Sales │ AR │ AP │ Inventory │
│ Banking │ Payroll │ Assets  │
└──────────────┬──────────────┘
               │
       ┌───────┴────────┐
       ▼                ▼
┌──────────────┐  ┌───────────────┐
│ Domain Logic │  │ Accounting    │
│              │  │ Engine        │
└──────┬───────┘  └──────┬────────┘
       │                  │
       └────────┬─────────┘
                ▼
         PostgreSQL
```

---

# 3. API Versioning

Base path:

```text
/api/v1/
```

All public application endpoints should be versioned.

Example:

```text
/api/v1/customers
/api/v1/sales/invoices
/api/v1/accounting/journals
/api/v1/payroll/runs
```

Future breaking changes use:

```text
/api/v2/
```

Do not silently change the contract of `/v1`.

---

# 4. API Design Style

The API should combine:

### REST resources

For standard CRUD/query operations.

### Commands

For business actions that cause state transitions.

Example:

```text
POST /sales/invoices/{id}/approve
POST /sales/invoices/{id}/post
POST /sales/invoices/{id}/void
```

rather than allowing:

```text
PUT /sales/invoices/{id}
```

to arbitrarily change the status.

This makes business actions explicit and auditable.

---

# 5. Authentication

Every protected request must carry an authenticated identity.

Conceptually:

```text
Authorization: Bearer <token>
```

The authentication system should provide:

```text
user_id
organization_id
roles
permissions
legal_entity_scope
branch_scope
```

The exact authentication mechanism can follow the existing Synbot platform/security implementation.

---

# 6. Authorization

Authorization should be evaluated at multiple levels.

```text
User
 ↓
Role
 ↓
Permission
 ↓
Organization
 ↓
Legal Entity
 ↓
Branch
 ↓
Resource
 ↓
Action
```

Example permission:

```text
sales.invoice.post
```

Another:

```text
payroll.run.approve
```

---

# 7. Permission Convention

Use:

```text
<domain>.<resource>.<action>
```

Examples:

```text
customer.view
customer.create
customer.edit

sales.invoice.view
sales.invoice.create
sales.invoice.approve
sales.invoice.post
sales.invoice.void

inventory.adjustment.create
inventory.adjustment.approve
inventory.adjustment.post

accounting.journal.create
accounting.journal.approve
accounting.journal.post
accounting.journal.reverse

payroll.run.view
payroll.run.calculate
payroll.run.approve
payroll.run.post
```

---

# 8. Organization APIs

```text
GET    /organizations
POST   /organizations
GET    /organizations/{id}
PATCH  /organizations/{id}
```

Legal entities:

```text
GET    /legal-entities
POST   /legal-entities
GET    /legal-entities/{id}
PATCH  /legal-entities/{id}
```

Branches:

```text
GET    /branches
POST   /branches
GET    /branches/{id}
PATCH  /branches/{id}
```

Departments:

```text
GET    /departments
POST   /departments
GET    /departments/{id}
PATCH  /departments/{id}
```

Cost centres:

```text
GET    /cost-centres
POST   /cost-centres
GET    /cost-centres/{id}
PATCH  /cost-centres/{id}
```

---

# 9. Financial Period APIs

```text
GET    /financial-periods
POST   /financial-periods
GET    /financial-periods/{id}
POST   /financial-periods/{id}/open
POST   /financial-periods/{id}/close
```

Closing a period must invoke the period-close validation service.

The API should not simply change:

```text
status = CLOSED
```

without running financial controls.

---

# 10. Chart of Accounts APIs

```text
GET    /accounts
POST   /accounts
GET    /accounts/{id}
PATCH  /accounts/{id}
POST   /accounts/{id}/activate
POST   /accounts/{id}/deactivate
```

Account deletion should not be exposed once an account has financial history.

---

# 11. Customer Service

The Customer Service owns customer master data.

```text
GET    /customers
POST   /customers
GET    /customers/{id}
PATCH  /customers/{id}
POST   /customers/{id}/activate
POST   /customers/{id}/deactivate
```

Customer summary:

```text
GET /customers/{id}/summary
```

Transactions:

```text
GET /customers/{id}/transactions
GET /customers/{id}/invoices
GET /customers/{id}/payments
GET /customers/{id}/returns
GET /customers/{id}/statement
```

Balance:

```text
GET /customers/{id}/balance
```

The balance should come from authoritative AR data.

---

# 12. Supplier Service

```text
GET    /suppliers
POST   /suppliers
GET    /suppliers/{id}
PATCH  /suppliers/{id}
POST   /suppliers/{id}/activate
POST   /suppliers/{id}/deactivate
```

Supporting queries:

```text
GET /suppliers/{id}/summary
GET /suppliers/{id}/transactions
GET /suppliers/{id}/purchase-orders
GET /suppliers/{id}/invoices
GET /suppliers/{id}/payments
GET /suppliers/{id}/statement
GET /suppliers/{id}/balance
```

---

# 13. Product Service

```text
GET    /products
POST   /products
GET    /products/{id}
PATCH  /products/{id}
POST   /products/{id}/activate
POST   /products/{id}/deactivate
```

Product queries:

```text
GET /products/{id}/stock
GET /products/{id}/batches
GET /products/{id}/movements
GET /products/{id}/sales
GET /products/{id}/purchases
```

---

# 14. Batch Service

```text
GET    /batches
POST   /batches
GET    /batches/{id}
PATCH  /batches/{id}
```

Batch traceability:

```text
GET /batches/{id}/movements
GET /batches/{id}/customers
GET /batches/{id}/invoices
GET /batches/{id}/recalls
```

This enables the recall workflow.

---

# 15. Sales Service

Sales owns the commercial sales lifecycle.

```text
GET    /sales/orders
POST   /sales/orders
GET    /sales/orders/{id}
PATCH  /sales/orders/{id}
```

Order actions:

```text
POST /sales/orders/{id}/submit
POST /sales/orders/{id}/approve
POST /sales/orders/{id}/cancel
```

---

# 16. Delivery Service

```text
GET    /sales/deliveries
POST   /sales/deliveries
GET    /sales/deliveries/{id}
PATCH  /sales/deliveries/{id}
```

Actions:

```text
POST /sales/deliveries/{id}/confirm
POST /sales/deliveries/{id}/cancel
```

Confirmation should generate the relevant inventory movement where the business workflow requires it.

---

# 17. Sales Invoice Service

```text
GET    /sales/invoices
POST   /sales/invoices
GET    /sales/invoices/{id}
PATCH  /sales/invoices/{id}
```

Actions:

```text
POST /sales/invoices/{id}/submit
POST /sales/invoices/{id}/approve
POST /sales/invoices/{id}/post
POST /sales/invoices/{id}/void
```

Posting invokes:

```text
InvoiceService
      ↓
ValidationService
      ↓
CreditService
      ↓
AccountingEngine
      ↓
InventoryService
      ↓
AuditService
```

The exact ordering will be controlled transactionally.

---

# 18. Invoice Posting Contract

When:

```text
POST /sales/invoices/{id}/post
```

is called, the service should:

### 1. Authenticate

Verify the user.

### 2. Authorize

Verify:

```text
sales.invoice.post
```

### 3. Lock source

Prevent simultaneous posting.

### 4. Validate

Check:

* invoice status;
* customer;
* legal entity;
* financial period;
* accounts;
* lines;
* tax;
* discounts;
* charges;
* stock;
* batch;
* credit exposure;
* approval.

### 5. Generate accounting event

```text
SALES_INVOICE_POSTED
```

### 6. Generate journal

Example:

```text
DR AR
CR Revenue

DR COGS
CR Inventory
```

### 7. Generate inventory movements

Where applicable.

### 8. Write audit event.

### 9. Commit transaction.

---

# 19. Customer Payment API

```text
GET  /receivables/payments
POST /receivables/payments
GET  /receivables/payments/{id}
```

Actions:

```text
POST /receivables/payments/{id}/approve
POST /receivables/payments/{id}/post
POST /receivables/payments/{id}/allocate
```

Allocation:

```text
POST /receivables/payments/{id}/allocations
```

Request:

```text
invoice_id
amount
```

The system must prevent allocation above the available payment amount.

---

# 20. AR Service

Queries:

```text
GET /receivables/ageing
GET /receivables/ledger
GET /receivables/outstanding
GET /receivables/statements
GET /receivables/overdue
```

Customer-specific:

```text
GET /customers/{id}/receivables
```

---

# 21. Credit Note API

```text
GET  /receivables/credit-notes
POST /receivables/credit-notes
GET  /receivables/credit-notes/{id}
```

Actions:

```text
POST /receivables/credit-notes/{id}/approve
POST /receivables/credit-notes/{id}/post
POST /receivables/credit-notes/{id}/void
```

A posted credit note creates its own accounting event.

---

# 22. Procurement Service

Purchase requests:

```text
GET  /procurement/requests
POST /procurement/requests
GET  /procurement/requests/{id}
```

Actions:

```text
POST /procurement/requests/{id}/submit
POST /procurement/requests/{id}/approve
POST /procurement/requests/{id}/reject
```

---

# 23. Purchase Order API

```text
GET  /procurement/orders
POST /procurement/orders
GET  /procurement/orders/{id}
PATCH /procurement/orders/{id}
```

Actions:

```text
POST /procurement/orders/{id}/submit
POST /procurement/orders/{id}/approve
POST /procurement/orders/{id}/send
POST /procurement/orders/{id}/cancel
```

---

# 24. Goods Receipt API

```text
GET  /procurement/receipts
POST /procurement/receipts
GET  /procurement/receipts/{id}
```

Actions:

```text
POST /procurement/receipts/{id}/confirm
POST /procurement/receipts/{id}/reject
```

Confirmation can generate:

```text
Inventory Movement
```

and, depending on the configured accounting policy:

```text
Accounting Event
```

---

# 25. Supplier Invoice API

```text
GET  /payables/invoices
POST /payables/invoices
GET  /payables/invoices/{id}
```

Actions:

```text
POST /payables/invoices/{id}/match
POST /payables/invoices/{id}/approve
POST /payables/invoices/{id}/post
POST /payables/invoices/{id}/void
```

`match` invokes the three-way matching service.

---

# 26. Three-Way Matching Service

Input:

```text
Purchase Order
Goods Receipt
Supplier Invoice
```

Output:

```text
MATCHED
PARTIAL_MATCH
VARIANCE
EXCEPTION
```

Endpoint:

```text
POST /payables/invoices/{id}/match
```

Response should identify:

```text
quantity_variance
price_variance
tax_variance
missing_receipt
duplicate_warning
```

---

# 27. Supplier Payment API

```text
GET  /payables/payments
POST /payables/payments
GET  /payables/payments/{id}
```

Actions:

```text
POST /payables/payments/{id}/approve
POST /payables/payments/{id}/post
POST /payables/payments/{id}/allocate
```

---

# 28. AP Service

```text
GET /payables/ageing
GET /payables/ledger
GET /payables/outstanding
GET /payables/statements
GET /payables/overdue
```

---

# 29. Inventory Service

Inventory movement query:

```text
GET /inventory/movements
GET /inventory/balances
GET /inventory/valuation
```

Stock adjustment:

```text
POST /inventory/adjustments
GET  /inventory/adjustments/{id}
```

Actions:

```text
POST /inventory/adjustments/{id}/submit
POST /inventory/adjustments/{id}/approve
POST /inventory/adjustments/{id}/post
```

---

# 30. Stock Transfer API

```text
POST /inventory/transfers
GET  /inventory/transfers/{id}
```

Actions:

```text
POST /inventory/transfers/{id}/approve
POST /inventory/transfers/{id}/execute
```

A transfer should generate the corresponding:

```text
TRANSFER_OUT
TRANSFER_IN
```

inventory movements.

---

# 31. Stock Count API

```text
POST /inventory/counts
GET  /inventory/counts/{id}
```

Workflow:

```text
CREATE
 ↓
COUNT
 ↓
REVIEW
 ↓
APPROVE
 ↓
POST VARIANCE
```

---

# 32. Stock Loan API

```text
GET  /inventory/loans
POST /inventory/loans
GET  /inventory/loans/{id}
```

Actions:

```text
POST /inventory/loans/{id}/approve
POST /inventory/loans/{id}/issue
POST /inventory/loans/{id}/return
```

The return request must support a different returned batch.

---

# 33. Recall API

```text
GET  /inventory/recalls
POST /inventory/recalls
GET  /inventory/recalls/{id}
```

Actions:

```text
POST /inventory/recalls/{id}/identify
POST /inventory/recalls/{id}/activate
POST /inventory/recalls/{id}/receive-return
POST /inventory/recalls/{id}/close
```

The identification service should determine affected:

* batches;
* invoices;
* customers;
* quantities.

---

# 34. Banking Service

Bank accounts:

```text
GET  /banking/accounts
POST /banking/accounts
GET  /banking/accounts/{id}
PATCH /banking/accounts/{id}
```

Transactions:

```text
GET  /banking/transactions
POST /banking/transactions
GET  /banking/transactions/{id}
```

---

# 35. Bank Reconciliation API

```text
GET  /banking/statements
POST /banking/statements
GET  /banking/statements/{id}
```

Reconciliation:

```text
POST /banking/reconciliations
GET  /banking/reconciliations/{id}
POST /banking/reconciliations/{id}/match
POST /banking/reconciliations/{id}/complete
```

Matching:

```text
POST /banking/reconciliations/{id}/items/{item_id}/match
```

---

# 36. Cash API

```text
GET  /banking/cash/accounts
GET  /banking/cash/transactions
POST /banking/cash/transactions
```

Transfers:

```text
POST /banking/cash/transfers
```

Bank lodgement:

```text
POST /banking/cash/lodgements
```

The accounting engine determines the corresponding journal.

---

# 37. Accounting Service

Accounting queries:

```text
GET /accounting/journals
GET /accounting/journals/{id}
GET /accounting/ledger
GET /accounting/accounts/{id}/activity
GET /accounting/trial-balance
```

Journal creation:

```text
POST /accounting/journals
```

Actions:

```text
POST /accounting/journals/{id}/validate
POST /accounting/journals/{id}/approve
POST /accounting/journals/{id}/post
POST /accounting/journals/{id}/reverse
```

---

# 38. Posting Service

The central posting endpoint is intentionally not exposed as a generic public operation.

Internally:

```text
PostingService.post(
    accounting_event
)
```

The service performs:

```text
Validate Event
 ↓
Resolve Accounts
 ↓
Generate Journal
 ↓
Validate Journal
 ↓
Validate Period
 ↓
Validate Permissions
 ↓
Post
 ↓
Audit
```

This becomes the central financial control point.

---

# 39. Accounting Rule Service

Internal service:

```text
AccountingRuleService
```

Responsibilities:

* resolve account mappings;
* determine debit/credit;
* apply configured tax accounts;
* determine inventory accounts;
* determine revenue accounts;
* determine COGS;
* determine AR/AP accounts;
* generate accounting lines.

Example:

```text
Sales Invoice
       ↓
Rule:
AR → Debit
Revenue → Credit
COGS → Debit
Inventory → Credit
```

---

# 40. General Ledger Service

The GL service should expose queries rather than allow arbitrary mutations.

```text
GET /accounting/gl
GET /accounting/gl/{account_id}
```

Filters:

```text
date_from
date_to
period
branch
department
cost_centre
source
customer
supplier
```

---

# 41. Fixed Asset Service

Assets:

```text
GET  /assets
POST /assets
GET  /assets/{id}
PATCH /assets/{id}
```

Acquisition:

```text
POST /assets/{id}/acquire
POST /assets/{id}/capitalize
```

Depreciation:

```text
POST /assets/depreciation-runs
GET  /assets/depreciation-runs/{id}
POST /assets/depreciation-runs/{id}/calculate
POST /assets/depreciation-runs/{id}/approve
POST /assets/depreciation-runs/{id}/post
```

Disposal:

```text
POST /assets/{id}/dispose
```

---

# 42. HR Service

Employees:

```text
GET  /hr/employees
POST /hr/employees
GET  /hr/employees/{id}
PATCH /hr/employees/{id}
```

Employment:

```text
GET  /hr/employees/{id}/employment
GET  /hr/employees/{id}/compensation
```

Attendance:

```text
GET  /hr/attendance
POST /hr/attendance
```

Leave:

```text
GET  /hr/leave
POST /hr/leave
POST /hr/leave/{id}/approve
POST /hr/leave/{id}/reject
```

---

# 43. Payroll Service

Payroll periods:

```text
GET  /payroll/periods
POST /payroll/periods
GET  /payroll/periods/{id}
```

Payroll runs:

```text
GET  /payroll/runs
POST /payroll/runs
GET  /payroll/runs/{id}
```

Actions:

```text
POST /payroll/runs/{id}/calculate
POST /payroll/runs/{id}/review
POST /payroll/runs/{id}/approve
POST /payroll/runs/{id}/post
POST /payroll/runs/{id}/pay
```

---

# 44. Payroll Calculation Service

Internal service:

```text
PayrollCalculationService
```

Responsibilities:

```text
Load Employees
 ↓
Load Compensation
 ↓
Load Attendance/Leave
 ↓
Load Allowances
 ↓
Load Deductions
 ↓
Load Staff Loans
 ↓
Calculate Gross
 ↓
Calculate Statutory
 ↓
Calculate Net
 ↓
Create Payroll Items
```

Exact statutory calculations remain a research/configuration dependency.

The service should therefore support configurable payroll components.

---

# 45. Payroll Accounting Service

Once payroll is approved:

```text
Payroll
 ↓
Accounting Event
 ↓
Payroll Journal
 ↓
GL
```

The payroll service should not manually manipulate GL balances.

---

# 46. Employee Loan Service

```text
GET  /hr/loans
POST /hr/loans
GET  /hr/loans/{id}
POST /hr/loans/{id}/approve
POST /hr/loans/{id}/disburse
POST /hr/loans/{id}/close
```

Payroll deductions should reference the outstanding loan rather than maintaining a second loan balance.

---

# 47. Budget Service

```text
GET  /budgets
POST /budgets
GET  /budgets/{id}
PATCH /budgets/{id}
```

Actions:

```text
POST /budgets/{id}/submit
POST /budgets/{id}/approve
POST /budgets/{id}/activate
```

Budget analysis:

```text
GET /budgets/{id}/actual-vs-budget
GET /budgets/{id}/variance
```

---

# 48. Tax Service

```text
GET  /tax/types
GET  /tax/rates
POST /tax/rates
PATCH /tax/rates/{id}
```

Tax calculation should be invoked by relevant transaction services.

Example:

```text
InvoiceService
 ↓
TaxService
 ↓
Tax Result
 ↓
AccountingEngine
```

The exact Nigerian tax rules will be configured after the tax research stage.

---

# 49. Approval Service

Central approval APIs:

```text
GET /approvals
GET /approvals/{id}
POST /approvals/{id}/approve
POST /approvals/{id}/reject
POST /approvals/{id}/return
```

The approval engine determines:

```text
Who must approve?
How many levels?
What threshold?
Which entity?
```

Example:

```text
Invoice < ₦500k
 → Level 1

₦500k–₦5m
 → Level 1 + Finance

> ₦5m
 → Additional approval
```

Actual thresholds must be client configuration, not hard-coded assumptions.

---

# 50. Audit Service

```text
GET /audit/events
GET /audit/entities/{entity_type}/{entity_id}
GET /audit/users/{user_id}
```

Audit records should be read-only through the API.

No:

```text
PUT /audit/events
DELETE /audit/events
```

---

# 51. Document Service

Upload:

```text
POST /documents
```

Retrieve:

```text
GET /documents/{id}
```

Link:

```text
POST /documents/{id}/links
```

List:

```text
GET /documents?entity_type=invoice&entity_id=...
```

Document deletion should be restricted and audited.

---

# 52. Reporting Service

The reporting service is read-only.

Core endpoints:

```text
GET /reports/income-statement
GET /reports/balance-sheet
GET /reports/cash-flow
GET /reports/trial-balance
GET /reports/general-ledger
GET /reports/aged-receivables
GET /reports/aged-payables
GET /reports/inventory
GET /reports/bank-reconciliation
GET /reports/payroll
GET /reports/fixed-assets
GET /reports/budget-vs-actual
```

---

# 53. Report Query Contract

Common parameters:

```text
legal_entity_id
branch_id
department_id
cost_centre_id
date_from
date_to
financial_period_id
currency_id
```

Domain-specific filters can be added.

Example:

```text
GET /reports/general-ledger?
account_id=...
&date_from=...
&date_to=...
```

---

# 54. Report Drill-Down API

Each report should return identifiers that allow navigation.

Example:

```text
GET /reports/income-statement
```

returns:

```text
account_id
account_name
amount
```

The frontend can then request:

```text
GET /accounting/accounts/{account_id}/activity
```

and ultimately:

```text
GET /accounting/journals/{journal_id}
```

---

# 55. Dashboard Service

Dashboards should use specialized query endpoints.

Examples:

```text
GET /dashboard/executive
GET /dashboard/finance
GET /dashboard/sales
GET /dashboard/procurement
GET /dashboard/inventory
GET /dashboard/hr
GET /dashboard/payroll
```

These should be optimized read operations.

They should not independently calculate accounting balances.

---

# 56. Intelligence Service

Finance AI endpoint:

```text
POST /intelligence/finance/query
```

Request:

```text
{
  "question": "Why did expenses increase this month?"
}
```

Internal flow:

```text
User Question
 ↓
Intent Detection
 ↓
Permission Check
 ↓
Financial Query Planner
 ↓
Reporting/Query Service
 ↓
Calculation
 ↓
Explanation
 ↓
Source References
```

---

# 57. AI Response Contract

A useful response structure:

```text
{
  "answer": "...",
  "summary": [],
  "metrics": [],
  "sources": [],
  "actions": []
}
```

For example:

```text
answer:
"Operating expenses increased by ₦X..."

sources:
[
  {
    "type": "account",
    "id": "...",
    "label": "Utilities Expense"
  }
]
```

The frontend can turn these sources into clickable links.

---

# 58. AI Permission Boundary

Before returning financial information:

```text
AI Query
 ↓
User Identity
 ↓
Permission Check
 ↓
Entity Scope
 ↓
Query
```

A user must not use Finance AI to bypass normal access controls.

For example, an employee without payroll access should not be able to ask:

> "Show me everyone's salary."

and receive payroll information.

---

# 59. Anomaly Service

```text
GET /intelligence/anomalies
GET /intelligence/anomalies/{id}
POST /intelligence/anomalies/{id}/review
POST /intelligence/anomalies/{id}/resolve
```

Potential anomaly types:

```text
DUPLICATE_INVOICE
UNUSUAL_EXPENSE
STOCK_VARIANCE
CREDIT_EXPOSURE
BANK_EXCEPTION
PAYROLL_VARIANCE
UNUSUAL_JOURNAL
```

The detection logic can evolve independently from the transaction engine.

---

# 60. Error Contract

All API errors should use a consistent format.

Example:

```text
{
  "error": {
    "code": "PERIOD_CLOSED",
    "message": "The transaction cannot be posted because the financial period is closed.",
    "details": {
      "period_id": "...",
      "period": "September 2026"
    },
    "request_id": "..."
  }
}
```

---

# 61. Standard Error Codes

Examples:

```text
AUTHENTICATION_REQUIRED
PERMISSION_DENIED
RESOURCE_NOT_FOUND
VALIDATION_FAILED
DUPLICATE_RESOURCE
PERIOD_CLOSED
ACCOUNT_INACTIVE
ACCOUNT_NOT_POSTABLE
UNBALANCED_JOURNAL
APPROVAL_REQUIRED
CREDIT_LIMIT_EXCEEDED
INSUFFICIENT_STOCK
INVALID_BATCH
DUPLICATE_INVOICE
RECONCILIATION_EXCEPTION
TRANSACTION_ALREADY_POSTED
INVALID_STATE_TRANSITION
IDEMPOTENCY_CONFLICT
```

---

# 62. HTTP Status Convention

Use standard HTTP semantics.

```text
200  Successful query/action
201  Resource created
202  Accepted asynchronous operation
204  Successful operation without body
400  Invalid request
401  Authentication required
403  Permission denied
404  Resource not found
409  State/conflict/duplicate
422  Validation failure
500  Unexpected server error
```

---

# 63. Idempotency

All financial mutation endpoints that could be retried must support idempotency.

Header:

```text
Idempotency-Key: <unique-key>
```

Especially:

```text
POST invoice
POST payment
POST supplier payment
POST journal
POST payroll
POST bank transaction
POST inventory adjustment
POST stock transfer
```

---

# 64. API Pagination

Large financial datasets must never return unlimited rows.

Use:

```text
?page=1&page_size=50
```

or cursor-based pagination where appropriate.

Response:

```text
{
  "items": [],
  "pagination": {
    "page": 1,
    "page_size": 50,
    "total": 447427
  }
}
```

For very large GL/report datasets, cursor-based pagination should be preferred.

---

# 65. Filtering

List endpoints should support predictable filtering.

Example:

```text
GET /sales/invoices?
status=POSTED
&customer_id=...
&date_from=...
&date_to=...
```

Do not create arbitrary SQL-like query parameters exposed to clients.

---

# 66. Sorting

Use controlled sortable fields.

Example:

```text
?sort=-invoice_date
```

The backend must validate allowed fields.

---

# 67. Response Envelope

For normal resource endpoints:

```text
{
  "data": {...}
}
```

For lists:

```text
{
  "data": [],
  "pagination": {...}
}
```

For actions:

```text
{
  "data": {
    "id": "...",
    "status": "POSTED"
  }
}
```

---

# 68. Transaction Correlation

Every request should carry or receive a request ID.

Example:

```text
X-Request-ID
```

That identifier should appear in:

* logs;
* audit events;
* errors;
* transaction traces.

This makes production debugging possible.

---

# 69. Cross-Module Transaction Example

Consider:

> Customer buys inventory.

The frontend calls:

```text
POST /sales/invoices
```

Then:

```text
SalesService
 ↓
CreditService
 ↓
InventoryService
 ↓
TaxService
 ↓
AccountingEngine
 ↓
PostingService
 ↓
AuditService
```

The result becomes:

```text
Invoice
+
AR
+
Revenue
+
Inventory movement
+
COGS
+
Tax
+
Journal
+
GL
+
Audit
```

One business action creates a connected financial record.

---

# 70. Purchase Transaction Example

Supplier invoice:

```text
POST /payables/invoices/{id}/post
```

Flow:

```text
PayablesService
 ↓
DuplicateCheck
 ↓
ThreeWayMatch
 ↓
TaxService
 ↓
AccountingEngine
 ↓
PostingService
 ↓
AuditService
```

Result:

```text
AP
+
Expense/Inventory
+
Tax
+
Journal
+
GL
+
Audit
```

---

# 71. Payroll Transaction Example

```text
POST /payroll/runs/{id}/calculate
```

then:

```text
Review
 ↓
Approve
 ↓
POST /payroll/runs/{id}/post
```

Flow:

```text
PayrollService
 ↓
PayrollCalculationService
 ↓
Validation
 ↓
Approval
 ↓
AccountingEngine
 ↓
Payroll Journal
 ↓
GL
```

Then:

```text
POST /payroll/runs/{id}/pay
```

creates the actual payment process.

---

# 72. Inventory Adjustment Example

```text
POST /inventory/adjustments/{id}/post
```

Flow:

```text
InventoryService
 ↓
Validate Count
 ↓
Validate Reason
 ↓
Validate Approval
 ↓
Create Inventory Transaction
 ↓
Accounting Event
 ↓
Accounting Engine
 ↓
Journal
 ↓
GL
 ↓
Audit
```

---

# 73. Period Close Example

```text
POST /financial-periods/{id}/close
```

The service must run:

```text
Check Unposted Transactions
Check Unbalanced Journals
Check AR Reconciliation
Check AP Reconciliation
Check Bank Reconciliation
Check Inventory Reconciliation
Check Payroll
Check Trial Balance
Check Critical Exceptions
```

Then:

```text
All Critical Checks Pass
        ↓
Close Period
        ↓
Audit Event
```

---

# 74. Service Layer Rules

Each service owns its domain.

### Sales Service

Owns:

```text
Orders
Deliveries
Invoices
Credit Notes
```

### AR Service

Owns:

```text
Receivables
Payments
Allocations
Ageing
```

### Inventory Service

Owns:

```text
Stock
Batches
Movements
Transfers
Adjustments
Loans
Recalls
```

### Accounting Service

Owns:

```text
Accounting Events
Journals
GL
Posting
Reversal
```

A service may call another service, but it should not directly modify another domain's database records.

---

# 75. Repository Boundary

For example:

```text
SalesService
 ↓
SalesRepository
```

not:

```text
SalesService
 ↓
Raw SQL
 ↓
Payroll tables
```

Cross-domain changes should go through application/domain services or controlled transactional orchestration.

---

# 76. Transaction Orchestrator

For complex operations, introduce an application-level orchestrator.

Example:

```text
SalesPostingOrchestrator
```

Responsibilities:

```text
Validate sales transaction
Validate inventory
Validate credit
Resolve tax
Generate accounting event
Post journal
Commit
```

This is preferable to having the invoice endpoint directly manipulate five unrelated repositories.

---

# 77. Background Jobs

Some tasks should be asynchronous.

Potential background jobs:

```text
Report generation
Large exports
Payroll calculation for large workforce
Bank statement processing
Document processing
Anomaly detection
AI analysis
Dashboard aggregation
```

But financial posting itself should remain synchronous/transactional where practical.

The user should know immediately whether a transaction was successfully posted.

---

# 78. Notifications

Business events can trigger notifications.

Examples:

```text
Invoice approved
Payment received
Purchase order approved
Payroll approved
Stock recall activated
Credit limit exceeded
Bank reconciliation exception
Period ready for close
```

Notification service:

```text
NotificationService
```

Channels can later include:

* in-app;
* email;
* SMS;
* WhatsApp;
* other configured channels.

---

# 79. API Security

Production API should implement:

* authentication;
* authorization;
* rate limiting;
* input validation;
* secure headers;
* request logging;
* audit logging;
* secrets management;
* encrypted transport;
* appropriate database credentials;
* restricted administrative endpoints.

Financial endpoints require stronger monitoring than ordinary informational endpoints.

---

# 80. API Documentation

The backend should expose OpenAPI documentation.

Recommended:

```text
/api/docs
/api/redoc
```

The generated API documentation becomes a direct reference for the frontend development engine.

The OpenAPI contract should be generated from the actual FastAPI models rather than maintained manually where possible.

---

# 81. Testing the API

Every service should have:

### Unit tests

Business rules.

### Integration tests

Database/service interaction.

### API tests

HTTP contract.

### Accounting tests

Journal generation.

### Permission tests

Unauthorized access.

### Workflow tests

State transitions.

### Regression tests

Existing functionality.

---

# 82. Golden Financial Tests

Create a permanent suite of financial scenarios.

Examples:

```text
Simple cash sale
Credit sale
Partial payment
Overpayment
Customer return
Supplier purchase
Supplier return
Inventory adjustment
Stock transfer
Stock loan
Loan return
Bank reconciliation
Fixed asset acquisition
Depreciation
Payroll
Expense
Manual journal
Period close
Journal reversal
```

Each scenario should verify:

```text
Source Transaction
↓
Sub-ledger
↓
Journal
↓
GL
↓
Report
```

---

# 83. API Contract Testing

The frontend and backend should be tested against the same OpenAPI contract.

The development process should prevent:

```text
Frontend expects field A
Backend returns field B
```

Contract tests should run in CI.

---

# 84. CI/CD Requirements

The development engine should eventually implement:

```text
Lint
 ↓
Type Check
 ↓
Unit Tests
 ↓
Integration Tests
 ↓
API Contract Tests
 ↓
Database Migration Test
 ↓
Build
 ↓
Deploy
```

Production deployment should require successful financial regression tests.

---

# 85. Final Service Architecture

```text
                         API GATEWAY
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
     OPERATIONS            FINANCE              PEOPLE
        │                     │                     │
 ┌──────┼──────┐       ┌──────┼──────┐        ┌────┴────┐
Sales Procurement     AR/AP Accounting       HR      Payroll
Inventory Banking     Assets Budget          │
        │                     │              │
        └──────────┬──────────┘              │
                   │                         │
             APPLICATION SERVICES            │
                   │                         │
             ACCOUNTING ENGINE               │
                   │                         │
              POSTING SERVICE               │
                   │                         │
                POSTGRESQL                  │
                   │                         │
          ┌────────┴────────┐               │
          │                 │               │
      REPORTING         AUDIT              │
          │                 │               │
          └────────┬────────┴───────────────┘
                   │
              INTELLIGENCE
                   │
                  AI
```

---

# 86. Final API Principle

The API layer should enforce one fundamental rule:

> **A financial transaction enters Synbot through a business operation, passes through validation and authorization, produces an accounting event, and is posted through the central accounting engine.**

There should be no shortcut around this architecture.

The intended chain is:

```text
FRONTEND
   ↓
API
   ↓
APPLICATION SERVICE
   ↓
DOMAIN VALIDATION
   ↓
APPROVAL
   ↓
ACCOUNTING EVENT
   ↓
ACCOUNTING ENGINE
   ↓
JOURNAL
   ↓
GENERAL LEDGER
   ↓
REPORTING
   ↓
AI / DASHBOARD
```

This gives Synbot a single financial truth while allowing every operational department to work through a natural business interface.

# End of V1
