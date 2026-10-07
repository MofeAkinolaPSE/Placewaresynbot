# Synbot Financial Frontend Architecture & Screen Map — V1

## 1. Frontend Objective

The Synbot Financial frontend is the user-facing operating environment for the Financial Operating System.

It must allow different users to:

* operate daily business processes;
* manage financial transactions;
* manage customers and suppliers;
* manage inventory;
* process payments;
* manage employees and payroll;
* review accounting;
* reconcile banking;
* manage budgets;
* investigate financial exceptions;
* produce reports;
* understand business performance.

The frontend must expose the underlying architecture without forcing users to understand accounting-system internals.

The user should be able to perform a business action naturally:

> Create invoice → approve → post → receive payment

while Synbot handles the accounting consequences underneath.

---

# 2. Frontend Architecture

Recommended stack:

```text
React
   │
   ├── Application Shell
   │
   ├── Routing
   │
   ├── Authentication / Authorization
   │
   ├── Domain Modules
   │
   ├── Shared Components
   │
   ├── State Management
   │
   ├── API Client
   │
   └── Notification / Error Layer
             │
             ▼
          FastAPI
```

The frontend should remain a client of the backend.

It must not contain authoritative accounting logic.

---

# 3. Application Shell

Every authenticated user enters through a common shell.

```text
┌──────────────────────────────────────────────────────────────┐
│ Synbot │ Company ▾ │ Global Search │ Alerts │ User ▾         │
├───────────────┬──────────────────────────────────────────────┤
│               │                                              │
│ Dashboard     │                                              │
│ Finance       │              MAIN CONTENT                    │
│ Sales         │                                              │
│ Procurement   │                                              │
│ Inventory     │                                              │
│ Banking       │                                              │
│ HR & Payroll  │                                              │
│ Assets        │                                              │
│ Budget        │                                              │
│ Reports       │                                              │
│ Intelligence  │                                              │
│ Documents     │                                              │
│ Administration│                                              │
│               │                                              │
└───────────────┴──────────────────────────────────────────────┘
```

The navigation should adapt according to the user's permissions.

A payroll user should not necessarily see accounting administration.

A warehouse user should not see payroll.

A management user may see dashboards and reports without being allowed to post transactions.

---

# 4. Global Navigation

Primary navigation:

```text
Dashboard
Finance
Sales
Procurement
Inventory
Banking
HR & Payroll
Fixed Assets
Budgeting
Reports
Intelligence
Documents
Administration
```

The exact labels can be refined during UI implementation, but the domain boundaries should remain consistent with the backend architecture.

---

# 5. Global Company Switcher

Because Synbot is being designed for multi-company operation, the company context should be visible globally.

Example:

```text
┌─────────────────────────────────────┐
│ Atiat Limited ▾                     │
│                                     │
│ ✓ Atiat Limited                     │
│   Atiat Subsidiary A                │
│   Atiat Subsidiary B                │
│   Atiat Subsidiary C                │
│                                     │
│ View: Current Company               │
│       Group View                    │
└─────────────────────────────────────┘
```

Changing company context should affect:

* dashboards;
* transactions;
* customers;
* suppliers;
* inventory;
* accounting;
* reports;
* payroll;
* budgets.

The user should never accidentally post a transaction against the wrong legal entity.

---

# 6. Global Search

Search should be one of the most useful features in Synbot.

The user should be able to search:

```text
Customers
Suppliers
Invoices
Payments
Products
Batches
Purchase Orders
Employees
Journal Entries
Assets
Reports
Documents
```

Example:

```text
Search: INV-2026-00492

Results
────────────────────────
Sales Invoice
INV-2026-00492
Customer: ABC Pharmaceuticals
₦1,240,000
Status: Partially Paid

[Open Invoice]
```

Search should understand business identifiers rather than requiring users to navigate through menus.

---

# 7. Notification Centre

The global notification centre should surface actionable events.

Examples:

```text
⚠ Customer credit limit exceeded
⚠ Supplier invoice may be duplicate
⚠ Stock below reorder level
⚠ Bank reconciliation exception
✓ Payroll approved
⚠ Invoice awaiting approval
⚠ Financial period approaching close
```

Notifications should link directly to the relevant entity.

---

# 8. Dashboard Architecture

There should not be one universal dashboard.

Instead:

```text
Executive Dashboard
Finance Dashboard
Sales Dashboard
Procurement Dashboard
Inventory Dashboard
HR/Payroll Dashboard
```

The user sees the dashboard appropriate to their role.

---

# 9. Executive Dashboard

The executive dashboard should answer:

> How is the business doing?

Primary cards:

```text
Revenue
Gross Profit
Net Profit
Cash Position
Receivables
Payables
Inventory Value
Budget Variance
```

Then:

```text
Revenue Trend
Cash Position
Receivables Ageing
Payables Ageing
Top Customers
Top Products
Major Expenses
```

The dashboard should allow:

```text
Current Company
↓
Group View
```

for authorized users.

---

# 10. Finance Control Tower

This is the operational dashboard for Finance.

It should answer:

> What requires financial attention right now?

Sections:

### Cash

```text
Cash on Hand
Bank Balance
Unreconciled Transactions
```

### AR

```text
Total Receivables
Overdue
0–30
31–60
61–90
90+
```

### AP

```text
Total Payables
Due Soon
Overdue
```

### Accounting

```text
Unposted Journals
Pending Approvals
Exceptions
```

### Inventory

```text
Stock Value
Stock Adjustments
Expired Stock
Recalled Stock
```

### Period

```text
Current Period
Period Status
Close Readiness
```

---

# 11. Finance Module

Finance navigation:

```text
Finance
├── Overview
├── General Ledger
├── Chart of Accounts
├── Journals
├── Accounts Receivable
├── Accounts Payable
├── Cash & Banking
├── Fixed Assets
├── Budgeting
├── Tax
└── Period Close
```

---

# 12. Chart of Accounts Screen

Screen:

```text
Chart of Accounts
─────────────────────────────────────────────

Search accounts       [+ New Account]

Code    Account              Type       Status
1000    Cash                 Asset      Active
1010    Main Bank            Asset      Active
1200    Receivables          Asset      Active
1300    Inventory            Asset      Active
2000    Payables             Liability  Active
4000    Sales Revenue        Revenue    Active
5000    Cost of Sales        Expense    Active
```

Support:

* hierarchy;
* search;
* filters;
* account details;
* activate/deactivate;
* reporting classification.

---

# 13. Account Detail Screen

Selecting an account opens:

```text
Account: 4000 — Sales Revenue

Balance
Current Period
YTD

Tabs:
Overview
Transactions
Journal Entries
Monthly Trend
Budget
Audit
```

A transaction can be opened directly from the ledger.

---

# 14. General Ledger Screen

The GL screen should be a powerful financial investigation tool.

```text
General Ledger

Account ▾
Period ▾
Date From ▾
Date To ▾
Branch ▾
Department ▾
Cost Centre ▾

Date       Ref       Description       Debit      Credit     Balance
---------------------------------------------------------------------
01 Sep     INV-001   Customer Sale                500,000    ...
02 Sep     PAY-009   Customer Payment  200,000              ...
```

Each row should be clickable.

---

# 15. Journal Screen

```text
Journals

[+ New Journal]

Journal No.
Date
Source
Description
Debit
Credit
Status
```

Filters:

* period;
* source;
* status;
* account;
* user.

---

# 16. Journal Detail

```text
Journal JE-2026-001923

Status: POSTED

Date: 27 Sep 2026
Source: Sales Invoice

Account                 Debit        Credit
------------------------------------------------
Accounts Receivable     1,000,000
Sales Revenue                        1,000,000

Balanced ✓
```

Actions:

```text
View Source
View Audit
Reverse
```

For posted entries, ordinary editing is disabled.

---

# 17. Sales Workspace

Navigation:

```text
Sales
├── Overview
├── Customers
├── Quotes
├── Sales Orders
├── Deliveries
├── Invoices
├── Credit Notes
├── Returns
└── Sales Reports
```

---

# 18. Sales Dashboard

KPIs:

```text
Today's Sales
Month-to-Date Sales
Outstanding AR
Overdue Customers
Open Orders
Pending Deliveries
```

Then:

```text
Recent Sales
Top Customers
Top Products
Sales Trend
```

---

# 19. Customer List

```text
Customers

[+ New Customer]

Search
Filter
Export/View

Code      Customer           Balance       Credit Limit    Status
------------------------------------------------------------------
C-001     ABC Ltd            ₦4.2m        ₦5m              Active
C-002     XYZ Ltd            ₦800k        ₦1m              Active
```

---

# 20. Customer 360 Screen

This should be one of Synbot's strongest screens.

```text
ABC Pharmaceuticals

Balance: ₦4.2m
Credit Limit: ₦5m
Status: Active

Tabs
────────────────────────────────────
Overview
Transactions
Invoices
Payments
Orders
Returns
Statements
Contacts
Documents
Activity
```

The overview should show:

```text
Total Sales
Outstanding Balance
Overdue Amount
Last Payment
Credit Utilisation
```

---

# 21. Customer Transaction Drill-Down

From customer:

```text
Customer
 ↓
Invoice
 ↓
Invoice Lines
 ↓
Product
 ↓
Batch
 ↓
Inventory Movement
 ↓
Journal
 ↓
GL
```

The user should be able to follow this chain without leaving the application.

---

# 22. Invoice Creation Screen

Invoice creation should be wizard-like where appropriate.

```text
New Invoice

Customer
Payment Terms
Invoice Date
Due Date

Items
─────────────────────────────
Product
Batch
Quantity
Price
Discount
Tax

Summary
Subtotal
Discount
Tax
Charges
Total
```

Then:

```text
Save Draft
Submit for Approval
Post
```

The `Post` action should only appear where the user's permissions allow it.

---

# 23. Invoice Detail

```text
Invoice INV-2026-00492

Customer
Invoice Date
Due Date
Status

Items
Payments
Credit Notes
Accounting
Documents
Audit
```

Accounting tab:

```text
Journal JE-...
AR
Revenue
COGS
Inventory
Tax
```

This makes the accounting consequence visible without forcing normal users into the GL.

---

# 24. Accounts Receivable Workspace

```text
Accounts Receivable

Overview
Invoices
Payments
Credit Notes
Ageing
Customer Statements
Collections
```

Ageing screen:

```text
Customer      Current    1–30    31–60    61–90    90+
----------------------------------------------------------
ABC Ltd        1.2m       400k    300k     100k     0
XYZ Ltd        300k       100k    0        0        500k
```

Clicking an amount opens the underlying transactions.

---

# 25. Procurement Workspace

```text
Procurement
├── Overview
├── Purchase Requests
├── Purchase Orders
├── Goods Receipts
├── Supplier Invoices
├── Returns
└── Procurement Reports
```

---

# 26. Supplier 360

Equivalent to Customer 360.

```text
Supplier

Balance
Outstanding
Overdue
Last Payment

Tabs:
Overview
Purchase Orders
Receipts
Invoices
Payments
Returns
Statements
Documents
Activity
```

---

# 27. Purchase Order Screen

```text
Purchase Order

Supplier
Order Date
Expected Date

Items
Product
Quantity
Unit Cost
Tax

Approval
Delivery Status
Invoice Status
```

Status progression:

```text
Draft
 ↓
Submitted
 ↓
Approved
 ↓
Sent
 ↓
Partially Received
 ↓
Received
 ↓
Closed
```

---

# 28. Three-Way Matching Screen

Finance/procurement users need a dedicated exception view.

```text
Purchase Order
      ↕
Goods Receipt
      ↕
Supplier Invoice
```

Show:

```text
Quantity variance
Price variance
Tax variance
Supplier mismatch
Duplicate warning
```

The user should be able to resolve the exception before AP posting.

---

# 29. Inventory Workspace

```text
Inventory
├── Overview
├── Products
├── Stock
├── Batches
├── Transfers
├── Adjustments
├── Returns
├── Stock Loans
├── Recalls
├── Stock Counts
└── Inventory Reports
```

---

# 30. Inventory Dashboard

KPIs:

```text
Total Stock Value
Units in Stock
Low Stock
Expired
Near Expiry
Recalled
On Loan
Stock Adjustments
```

---

# 31. Product 360

```text
Product

Current Quantity
Stock Value
Average Cost

Tabs:
Overview
Stock
Batches
Sales
Purchases
Adjustments
Movement
Pricing
Documents
```

---

# 32. Batch Detail

This is particularly important for traceability.

```text
Batch: ABC-123

Product
Manufacturing Date
Expiry Date
Current Quantity
Status

Tabs:
Stock Movement
Customers
Sales
Purchases
Returns
Recall
Audit
```

The Customers tab should answer:

> Who received this batch?

---

# 33. Stock Movement Screen

```text
Product: Rotarix
Batch: ABC-123

Opening Balance       84
Purchases            +100
Sales                -103
Adjustments            0
-------------------------
Closing Balance       81
```

Each movement opens its source document.

---

# 34. Stock Adjustment Screen

```text
Stock Adjustment

Warehouse
Product
Batch
Current Quantity
Counted Quantity

Variance
Reason
Supporting Document

[Submit for Approval]
```

The system should clearly display the accounting consequence before posting where appropriate.

---

# 35. Recall Workspace

```text
Recall

Batch
Reason
Recall Date
Severity
Status

Affected Customers
Affected Invoices
Quantity Sold
Quantity Returned
Outstanding Quantity
```

Workflow:

```text
Identify Batch
 ↓
Trace Customers
 ↓
Create Recall
 ↓
Notify/Action
 ↓
Receive Returns
 ↓
Quarantine
 ↓
Financial Adjustment
 ↓
Close
```

---

# 36. Stock Loan Workspace

```text
Stock Loans

Customer
Product
Original Batch
Quantity
Expected Return
Returned Quantity
Outstanding
Status
```

Loan detail should preserve both:

```text
Original Batch
Returned Batch
```

when they differ.

---

# 37. Banking Workspace

```text
Banking
├── Overview
├── Bank Accounts
├── Transactions
├── Statements
├── Reconciliation
├── Cash
└── Bank Reports
```

---

# 38. Bank Reconciliation Screen

The interface should visually separate:

```text
Bank Statement
          ↔
Synbot Transactions
```

Example:

```text
Bank Transaction              Synbot Transaction
---------------------------------------------------
₦500,000 ABC PAYMENT     ↔    INV-00231 ₦500,000
₦120,000 BANK CHARGE     ↔    Bank Charge ₦120,000
₦75,000 UNKNOWN          ↔    No Match
```

Actions:

```text
Match
Create Transaction
Ignore
Mark Exception
```

---

# 39. Cash Management

Show:

```text
Cash on Hand
Bank Balances
Total Available Cash
Unreconciled Amount
```

Cash transfer:

```text
From
To
Amount
Date
Reference
```

The accounting consequence should be generated automatically.

---

# 40. Fixed Assets Workspace

```text
Fixed Assets
├── Overview
├── Asset Register
├── Acquisitions
├── Depreciation
├── Transfers
├── Disposal
└── Reports
```

Asset detail:

```text
Asset
Acquisition Cost
Accumulated Depreciation
Net Book Value
Useful Life
Department
Location

Timeline
```

---

# 41. HR & Payroll Workspace

```text
HR & Payroll
├── Staff Dashboard
├── Employees
├── Organization
├── Attendance
├── Leave
├── Compensation
├── Payroll
├── Staff Loans
└── HR Reports
```

---

# 42. Staff Dashboard

The staff dashboard should combine HR and financial information appropriately.

For an employee:

```text
Employee Profile
Employment
Department
Manager
Leave
Attendance
Compensation
Payroll
Loans/Advances
Documents
```

Employees should only see their own permitted information.

Managers should receive broader visibility according to permissions.

---

# 43. Employee 360

```text
Employee

Profile
Employment
Compensation
Attendance
Leave
Payroll
Loans
Documents
Activity
```

This becomes the central HR record.

---

# 44. Payroll Dashboard

KPIs:

```text
Current Payroll
Employees
Gross Pay
Deductions
Net Pay
Pending Approval
Paid
Outstanding
```

Payroll run:

```text
Select Period
      ↓
Calculate
      ↓
Review Exceptions
      ↓
Approve
      ↓
Post
      ↓
Pay
```

---

# 45. Payroll Review Screen

This should not simply show a total.

It should show:

```text
Employee
Basic
Allowances
Deductions
Statutory
Loan
Net Pay
Status
```

Exceptions should be prominent:

```text
⚠ Missing bank information
⚠ Salary changed this period
⚠ Unusual deduction
⚠ Employee inactive
```

---

# 46. Budgeting Workspace

```text
Budgeting
├── Overview
├── Budgets
├── Budget Builder
├── Actual vs Budget
├── Variance
└── Forecast
```

Budget builder:

```text
Account
Department
Cost Centre
Period
Budget Amount
```

---

# 47. Budget vs Actual Screen

```text
Department: Operations

Account              Budget      Actual      Variance
-------------------------------------------------------
Utilities             2.0m        2.4m       +400k
Transport             5.0m        4.2m       -800k
Supplies              3.0m        3.1m       +100k
```

Clicking the variance opens the underlying GL transactions.

---

# 48. Period Close Workspace

This should be a dedicated finance workflow rather than a hidden accounting function.

```text
Period Close — September 2026

✓ Bank reconciliation
✓ AR reconciliation
✓ AP reconciliation
✓ Inventory reconciliation
⚠ Unposted journals
✓ Payroll posted
⚠ Outstanding approval
✓ Trial balance balanced

[Review Exceptions]
[Close Period]
```

The system should not allow closure while critical exceptions remain unresolved.

---

# 49. Reports Workspace

Reports should be categorized.

```text
Reports
│
├── Financial Statements
│   ├── Income Statement
│   ├── Balance Sheet
│   ├── Cash Flow
│   ├── Retained Earnings
│   └── Trial Balance
│
├── General Ledger
│   ├── GL
│   ├── Journal
│   └── Account Activity
│
├── Receivables
│   ├── Ageing
│   ├── Customer Ledger
│   └── Statements
│
├── Payables
│   ├── Ageing
│   ├── Supplier Ledger
│   └── Statements
│
├── Inventory
│   ├── Valuation
│   ├── Stock Status
│   ├── Movement
│   └── Batch
│
├── Banking
│   ├── Reconciliation
│   └── Cash
│
├── Payroll
│
└── Management
```

---

# 50. Report Viewer

All major reports should use a consistent viewer.

```text
Report Name

Filters
─────────────────────────────
Entity
Period
Date
Branch
Department
Cost Centre

[Run Report]

─────────────────────────────
REPORT CONTENT
─────────────────────────────

[Export] [Print] [Save View]
```

Rows should be drillable where appropriate.

---

# 51. Financial Statement Viewer

For example:

```text
Income Statement
September 2026

Revenue                         ₦XXX
Cost of Sales                  (₦XXX)
────────────────────────────────────
Gross Profit                    ₦XXX

Operating Expenses             (₦XXX)
────────────────────────────────────
Net Profit                      ₦XXX
```

Click:

```text
Revenue
 ↓
Revenue Accounts
 ↓
Transactions
```

---

# 52. Intelligence Workspace

The AI layer gets its own workspace.

```text
Intelligence
├── Finance AI
├── Business Insights
├── Anomalies
├── Forecasts
└── Saved Analysis
```

---

# 53. Finance AI

Interface:

```text
┌──────────────────────────────────────────┐
│ Ask Synbot Finance                       │
│                                          │
│ "Why did expenses increase this month?" │
│                                          │
│ [Ask]                                    │
└──────────────────────────────────────────┘
```

Response should provide:

```text
Answer
Key Drivers
Supporting Figures
Source Transactions
Suggested Investigation
```

The source links should be clickable.

---

# 54. AI Financial Explanation

Example:

```text
Why did profit fall this month?

Net profit decreased by ₦X.

Primary movements:
• Operating expenses increased by ₦X
• Revenue decreased by ₦X
• Cost of sales increased by ₦X

[View Expense Transactions]
[View Revenue Transactions]
[View P&L]
```

The AI response must remain grounded in system data.

---

# 55. Anomaly Centre

```text
Anomalies

Severity
Type
Entity
Amount
Detected
Status
```

Examples:

```text
Duplicate supplier invoice
Unusual expense
Unbalanced reconciliation
Large stock adjustment
Unexpected payroll variance
Customer credit exposure
```

Each anomaly links to the relevant record.

---

# 56. Administration

```text
Administration
├── Organization
├── Legal Entities
├── Branches
├── Departments
├── Users
├── Roles
├── Permissions
├── Financial Periods
├── Numbering
├── Accounting Rules
├── Tax Configuration
├── Approval Rules
├── Audit Logs
└── System Settings
```

---

# 57. Accounting Rules UI

This should eventually allow authorized finance administrators to configure rules without changing application code.

Example:

```text
Sales Invoice

Receivable Account
Revenue Account
Tax Account
COGS Account
Inventory Account
```

However, configuration must be permission-controlled and audited.

---

# 58. Approval Centre

Rather than hiding approvals inside individual modules, provide a unified queue.

```text
Approval Centre

Pending
────────────────────────────────────────────

Sales Invoice      INV-00492      ₦1.2m
Purchase Order     PO-00182       ₦4.3m
Stock Adjustment   ADJ-00012      500 units
Payroll Run        SEP-2026       ₦18m
Payment            PAY-00321      ₦2.4m
```

Clicking an item opens its contextual approval screen.

---

# 59. Audit Centre

```text
Audit

Search
User
Entity
Action
Date
Reference

User        Action       Entity       Reference
------------------------------------------------
M. Admin    Approved     Invoice      INV-492
A. User     Created      PO           PO-182
Finance     Posted       Journal      JE-923
```

Audit entries should be read-only.

---

# 60. Document Centre

```text
Documents

Recent
Invoices
Supplier Documents
Bank Statements
Payroll
Assets
Contracts
Other
```

Documents can be searched globally.

Each document should show its linked business entity.

---

# 61. Role-Based Screen Visibility

Example permission model:

### Executive

```text
Dashboard
Reports
Intelligence
Limited transaction visibility
```

### Finance Manager

```text
Finance
AR
AP
Banking
Reports
Budget
Approvals
Audit
```

### Accountant

```text
Finance
AR
AP
Banking
Reports
Limited administration
```

### Sales User

```text
Customers
Sales
Invoices
Collections
```

### Procurement User

```text
Suppliers
Purchase Requests
Purchase Orders
Goods Receipts
```

### Warehouse User

```text
Inventory
Stock
Transfers
Receipts
Returns
Counts
```

### HR

```text
Staff
Attendance
Leave
Payroll preparation
```

### Payroll/Finance

```text
Payroll
Finance
Payroll Journal
Payments
Reports
```

---

# 62. Screen Permission vs Action Permission

Visibility and action must be separated.

A user may:

```text
VIEW invoice
```

without being able to:

```text
EDIT invoice
APPROVE invoice
POST invoice
VOID invoice
```

Therefore permissions should be granular:

```text
module.resource.action
```

Examples:

```text
sales.invoice.view
sales.invoice.create
sales.invoice.edit
sales.invoice.approve
sales.invoice.post
sales.invoice.void
```

---

# 63. Responsive Design

The application should be desktop-first because Finance and Operations involve dense tables.

However:

* dashboards;
* approvals;
* notifications;
* employee views;
* simple transaction actions

should work effectively on tablets/mobile.

The system should not attempt to make every accounting table identical on a phone.

---

# 64. Reusable Frontend Components

The development engine should create a common component library.

Core components:

```text
DataTable
SearchBar
FilterBar
DateRangePicker
CurrencyInput
AmountDisplay
StatusBadge
ApprovalBadge
TransactionTimeline
EntityHeader
EntityTabs
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

---

# 65. Universal Entity Header

Customer, supplier, product, employee, asset and account screens should use a consistent structure.

Example:

```text
ABC Pharmaceuticals
Customer ID: C-001
Status: Active

Balance       ₦4.2m
Credit Limit  ₦5m
```

Then:

```text
Overview | Transactions | Documents | Audit
```

This gives the entire application a consistent mental model.

---

# 66. Universal Transaction Timeline

Every major transaction should expose a timeline.

Example:

```text
27 Sep 09:10
Created by Mofe

27 Sep 09:15
Submitted for approval

27 Sep 10:02
Approved by Finance Manager

27 Sep 10:04
Posted

27 Sep 11:22
Payment received
```

This is especially valuable for audit and operational troubleshooting.

---

# 67. Exception-First UX

Synbot should not merely display information.

It should surface what requires attention.

Examples:

```text
⚠ 12 overdue customers
⚠ 3 duplicate invoice warnings
⚠ 5 unmatched bank transactions
⚠ 2 stock expiry issues
⚠ 1 payroll exception
```

Clicking the alert should take the user directly to the resolution workflow.

---

# 68. Dashboard Drill-Down Rule

Every KPI that represents a financial number should be traceable.

For example:

```text
Receivables: ₦25.4m
       ↓
Aged Receivables
       ↓
Customer
       ↓
Invoice
       ↓
Transaction
       ↓
Journal
```

The user should never be shown an unexplained number.

---

# 69. Frontend State Management

Separate:

### Server state

Data from backend:

* customers;
* invoices;
* GL;
* inventory;
* payroll;
* reports.

### UI state

Local interface state:

* modal open;
* selected tab;
* filters;
* sort order;
* sidebar state.

Do not treat frontend state as the authoritative financial state.

---

# 70. Form Architecture

Financial forms should use:

```text
Draft
Validation
Review
Submission
Approval
Posting
```

rather than immediately saving everything as a posted transaction.

For example:

```text
Invoice Form
    ↓
Save Draft
    ↓
Validate
    ↓
Submit
    ↓
Approve
    ↓
Post
```

---

# 71. Error Handling

Errors should be business-readable.

Bad:

```text
HTTP 400
ForeignKeyViolation
```

Better:

```text
Unable to post invoice.

The selected financial period is closed.
Period: September 2026

[View Period]
```

For multiple errors:

```text
Cannot post transaction.

3 issues require attention:
• Customer credit limit exceeded
• Batch quantity insufficient
• Approval required
```

---

# 72. Confirmation UX

Financially significant actions should require explicit confirmation.

Examples:

```text
Post Invoice
Approve Payroll
Submit Payment
Close Period
Reverse Journal
Dispose Asset
Adjust Stock
```

The confirmation should explain the consequence.

Example:

```text
Post Invoice?

Posting will:
• Create the customer receivable
• Recognize revenue
• Update inventory
• Record cost of sales
• Create a journal entry

This action cannot be edited after posting.

[Cancel] [Post Invoice]
```

---

# 73. Frontend Data Flow

The standard frontend flow should be:

```text
User Action
    ↓
UI Component
    ↓
API Client
    ↓
Backend Service
    ↓
Validation
    ↓
Business Transaction
    ↓
Accounting Engine
    ↓
Database
    ↓
Response
    ↓
UI Refresh
```

The frontend never calculates authoritative financial balances itself.

---

# 74. Screen Map — Complete V1

The overall application map becomes:

```text
SYNBOT
│
├── Dashboard
│   ├── Executive
│   └── Finance Control Tower
│
├── Finance
│   ├── Overview
│   ├── Chart of Accounts
│   ├── General Ledger
│   ├── Journals
│   ├── Accounts Receivable
│   ├── Accounts Payable
│   ├── Cash & Banking
│   ├── Fixed Assets
│   ├── Budgeting
│   ├── Tax
│   └── Period Close
│
├── Sales
│   ├── Overview
│   ├── Customers
│   ├── Orders
│   ├── Deliveries
│   ├── Invoices
│   ├── Credit Notes
│   ├── Returns
│   └── Reports
│
├── Procurement
│   ├── Overview
│   ├── Purchase Requests
│   ├── Purchase Orders
│   ├── Goods Receipts
│   ├── Supplier Invoices
│   ├── Returns
│   └── Reports
│
├── Inventory
│   ├── Overview
│   ├── Products
│   ├── Stock
│   ├── Batches
│   ├── Transfers
│   ├── Adjustments
│   ├── Returns
│   ├── Loans
│   ├── Recalls
│   ├── Stock Counts
│   └── Reports
│
├── Banking
│   ├── Overview
│   ├── Bank Accounts
│   ├── Transactions
│   ├── Statements
│   ├── Reconciliation
│   └── Cash
│
├── HR & Payroll
│   ├── Staff Dashboard
│   ├── Employees
│   ├── Organization
│   ├── Attendance
│   ├── Leave
│   ├── Compensation
│   ├── Payroll
│   ├── Staff Loans
│   └── Reports
│
├── Fixed Assets
│   ├── Overview
│   ├── Asset Register
│   ├── Acquisitions
│   ├── Depreciation
│   ├── Transfers
│   ├── Disposal
│   └── Reports
│
├── Budgeting
│   ├── Overview
│   ├── Budgets
│   ├── Budget Builder
│   ├── Actual vs Budget
│   └── Variance
│
├── Reports
│   ├── Financial Statements
│   ├── General Ledger
│   ├── AR
│   ├── AP
│   ├── Inventory
│   ├── Banking
│   ├── Payroll
│   ├── Assets
│   └── Management
│
├── Intelligence
│   ├── Finance AI
│   ├── Insights
│   ├── Anomalies
│   └── Forecasts
│
├── Approvals
│
├── Documents
│
└── Administration
    ├── Organization
    ├── Users
    ├── Roles
    ├── Permissions
    ├── Accounting Rules
    ├── Tax
    ├── Approval Rules
    ├── Periods
    └── Audit
```

---

# 75. Frontend Development Priority

The development engine should build the frontend in the same dependency order as the backend.

### Stage 1 — Shell

```text
Authentication
Application Shell
Navigation
Company Switcher
Global Search
Notifications
Permissions
```

### Stage 2 — Finance Foundation

```text
COA
Financial Periods
GL
Journals
Account Detail
```

### Stage 3 — Sales + AR

```text
Customers
Customer 360
Invoices
Payments
AR
Ageing
```

### Stage 4 — Procurement + AP

```text
Suppliers
Supplier 360
PO
Goods Receipt
Supplier Invoice
AP
```

### Stage 5 — Inventory

```text
Products
Stock
Batches
Movement
Adjustments
Recall
Loan
```

### Stage 6 — Banking

```text
Bank Accounts
Transactions
Statements
Reconciliation
Cash
```

### Stage 7 — HR + Payroll

```text
Employees
Employee 360
Compensation
Payroll
Staff Loans
```

### Stage 8 — Assets + Budget

```text
Assets
Depreciation
Budgets
Variance
```

### Stage 9 — Reporting

```text
Financial Statements
Management Reports
Drill-down
Export
```

### Stage 10 — Intelligence

```text
Finance AI
Anomaly Centre
Forecasts
Executive Insights
```

---

# 76. The Most Important UX Principle

Synbot should make accounting **visible without making accounting complicated**.

A sales user should see:

> Invoice posted successfully.

A finance user can see:

> AR + Revenue + COGS + Inventory journal.

An auditor can see:

> Source → approval → posting → journal → GL → report.

An executive can see:

> Revenue → profit → cash → receivables → risks.

All four users are looking at the **same underlying transaction**.

That is the frontend expression of the architecture we have designed.

---

# 77. Final Frontend Architecture

```text
                         SYNBOT UI
                            │
             ┌──────────────┼───────────────┐
             │              │               │
          OPERATIONS      FINANCE        MANAGEMENT
             │              │               │
      ┌──────┼──────┐       │         ┌─────┴─────┐
      │      │      │       │         │           │
    Sales  Stock  HR/Pay   Accounting Reports   Intelligence
      │      │      │       │         │           │
      └──────┴──────┴───────┴─────────┴───────────┘
                            │
                       FastAPI APIs
                            │
                    Financial Core
                            │
                       PostgreSQL
```

The frontend therefore becomes a **single operating environment**, not a collection of disconnected applications.

# End of V1
