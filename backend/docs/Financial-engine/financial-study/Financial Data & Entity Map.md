

# Synbot Financial Data & Entity Map

## 1. Purpose

The Financial Data & Entity Map translates the workflow design into a structured business-data model.

The goal is **not yet to write the final database schema**. Instead, this establishes:

* the core entities Synbot needs;
* the relationships between entities;
* which module owns each entity;
* which workflows create or update them;
* which entities generate accounting entries;
* which entities require auditability;
* how the model supports multi-company operations;
* how Payroll connects into HR/Staff;
* how everything ultimately feeds the General Ledger.

The central principle remains:

> **Every operational financial event must have a traceable path from business transaction → accounting event → journal → ledger → financial report.**

---

# 2. The Synbot Financial Data Architecture

At the highest level, the financial system can be viewed as seven layers:

```text
┌──────────────────────────────────────────────┐
│              USER / DASHBOARDS               │
│ Finance │ HR │ Inventory │ Sales │ Admin    │
└──────────────────────┬───────────────────────┘
                       │
┌──────────────────────▼───────────────────────┐
│             BUSINESS TRANSACTIONS            │
│ Sales │ Purchases │ Payments │ Payroll       │
│ Inventory │ Expenses │ Assets │ Banking       │
└──────────────────────┬───────────────────────┘
                       │
┌──────────────────────▼───────────────────────┐
│             CONTROL / VALIDATION             │
│ Approval │ Credit │ Duplicate │ Balance      │
│ Stock │ Period │ Tax │ Permissions           │
└──────────────────────┬───────────────────────┘
                       │
┌──────────────────────▼───────────────────────┐
│             ACCOUNTING ENGINE                │
│ Accounting Rules │ Journal Engine            │
└──────────────────────┬───────────────────────┘
                       │
┌──────────────────────▼───────────────────────┐
│               GENERAL LEDGER                 │
│ Accounts │ Journal Entries │ Ledger Lines    │
└──────────────────────┬───────────────────────┘
                       │
┌──────────────────────▼───────────────────────┐
│              REPORTING ENGINE                │
│ P&L │ Balance Sheet │ Cash Flow │ TB │ AR/AP │
│ Inventory │ Payroll │ Management Reports     │
└──────────────────────┬───────────────────────┘
                       │
┌──────────────────────▼───────────────────────┐
│              FINANCE INTELLIGENCE            │
│ AI Finance Agent │ Analytics │ Alerts        │
│ Forecasting │ Anomaly Detection              │
└──────────────────────────────────────────────┘
```

This is important because **the dashboard is not the financial system**.

The dashboard is simply a presentation layer over the underlying transaction and accounting system.

---

# 3. Entity Domains

I would organize the data model into **12 domains**.

| Domain                   | Primary responsibility                   |
| ------------------------ | ---------------------------------------- |
| Organization             | Companies, branches and structure        |
| Master Data              | Customers, suppliers, products, accounts |
| Sales & AR               | Revenue and customer receivables         |
| Procurement & AP         | Purchases and supplier liabilities       |
| Inventory                | Stock, batches and movements             |
| Banking & Cash           | Cash, bank and reconciliation            |
| Accounting               | Journals and General Ledger              |
| Fixed Assets             | Asset lifecycle and depreciation         |
| Payroll & HR             | Employees, payroll and staff liabilities |
| Budgeting                | Budgets and variance                     |
| Controls & Audit         | Validation, approvals and audit trail    |
| Reporting & Intelligence | Statements, analytics and AI             |

---

# 4. Organization & Multi-Company Entities

Synbot needs multi-company support from the beginning even if the first deployment has only one company.

### Core entities

```text
Organization
   │
   ├── Legal Entity
   │      │
   │      ├── Branch
   │      ├── Department
   │      └── Cost Centre
   │
   └── Users / Roles
```

### Organization

Represents the overall Synbot customer.

Example:

```text
Organization
    Atiat Group
```

### Legal Entity

Represents an actual company/legal business.

```text
Atiat Limited
Company A
Company B
Company C
```

Each legal entity should have its own:

* accounting configuration;
* COA;
* financial periods;
* tax configuration;
* bank accounts;
* customers;
* suppliers;
* inventory;
* payroll;
* financial statements.

Where required, entities can later participate in consolidated reporting.

---

# 5. Core Organizational Entities

### `organization`

Owns the overall Synbot environment.

Key concepts:

* organization ID
* name
* status
* configuration
* subscription/license information

### `legal_entity`

The accounting boundary.

Important fields conceptually:

* legal entity ID
* organization ID
* registered name
* tax identifiers
* base currency
* accounting method/configuration
* fiscal year
* status

### `branch`

Physical/business operating location.

### `department`

Functional business unit.

Examples:

* Finance
* Sales
* Operations
* Procurement
* HR
* Warehouse

### `cost_centre`

Used for management accounting.

Example:

```text
Sales
   ├── Lagos
   ├── Abuja
   └── Port Harcourt
```

### `financial_period`

Controls whether accounting activity can be posted.

Example:

```text
2026-09
OPEN
```

Later:

```text
2026-09
CLOSED
```

This becomes a critical control entity.

---

# 6. Financial Master Data

The financial engine depends heavily on master data.

## Chart of Accounts

```text
Chart of Accounts
       │
       ├── Account
       │      ├── Asset
       │      ├── Liability
       │      ├── Equity
       │      ├── Revenue
       │      └── Expense
       │
       └── Account Groups
```

### `account`

Represents an individual GL account.

Examples:

```text
1000 Cash
1010 Main Bank
1200 Accounts Receivable
1300 Inventory
2000 Accounts Payable
4000 Sales Revenue
5000 Cost of Sales
6000 Operating Expenses
```

Each account should contain:

* account code
* account name
* account type
* parent account
* normal balance
* active/inactive status
* control-account designation
* tax configuration where applicable
* reporting classification

### Important rule

Once an account has participated in posted transactions:

> **Do not physically delete it.**

Deactivate it instead.

That protects historical accounting integrity.

---

# 7. Customer Entity

### `customer`

The primary AR master.

Relationships:

```text
Customer
   │
   ├── Contacts
   ├── Sales Orders
   ├── Invoices
   ├── Credit Notes
   ├── Payments
   ├── Returns
   ├── Statements
   └── Receivable Ledger
```

Important concepts:

* customer code
* legal name
* contacts
* addresses
* payment terms
* credit limit
* tax information
* assigned salesperson
* status
* default currency
* receivable account

---

# 8. Supplier Entity

### `supplier`

The AP equivalent.

```text
Supplier
   │
   ├── Purchase Orders
   ├── Goods Receipts
   ├── Supplier Invoices
   ├── Returns
   ├── Payments
   └── Payable Ledger
```

Important concepts:

* supplier code
* supplier name
* contacts
* payment terms
* tax information
* bank details
* payable account
* status

---

# 9. Product & Inventory Entities

Inventory requires more than a simple product table.

The model should distinguish:

```text
Product
   │
   ├── Product Category
   ├── Unit of Measure
   ├── Batch
   ├── Price
   ├── Cost
   └── Inventory Balance
```

### `product`

Defines what the company sells or stores.

### `product_category`

Groups products.

### `unit_of_measure`

Examples:

* piece
* box
* carton
* pack
* litre
* kilogram

### `batch`

Critical for the client's pharmaceutical/medical distribution-type workflows.

```text
Product
   │
   ├── Batch A
   │     ├── Expiry
   │     └── Quantity
   │
   └── Batch B
         ├── Expiry
         └── Quantity
```

A batch should carry:

* batch number
* product
* manufacturing date where applicable
* expiry date
* quantity
* cost
* warehouse/location
* status

Potential statuses:

```text
AVAILABLE
QUARANTINED
DAMAGED
EXPIRED
RECALLED
LOANED
```

---

# 10. Inventory Movement Entity

The most important inventory entity is not the stock balance.

It is the **inventory movement**.

### `inventory_transaction`

Every movement creates an immutable movement record.

Types:

```text
PURCHASE
SALE
RETURN_IN
RETURN_OUT
TRANSFER
ADJUSTMENT
DAMAGE
EXPIRY
RECALL
LOAN_OUT
LOAN_RETURN
STOCK_COUNT
BATCH_REPLACEMENT
OPENING_BALANCE
```

Conceptually:

```text
Product + Batch
      │
      ▼
Inventory Transaction
      │
      ├── Quantity
      ├── Unit Cost
      ├── Source Document
      ├── Warehouse
      ├── Reason
      └── User
```

Then:

```text
Inventory Transaction
        │
        ├── Inventory Ledger
        │
        └── Accounting Event
                 │
                 ▼
              Journal
```

This is what makes the inventory report trustworthy.

---

# 11. Sales & Accounts Receivable

The central sales entity is the transaction/document chain.

```text
Customer
   │
   ▼
Sales Order
   │
   ▼
Delivery
   │
   ▼
Invoice
   │
   ▼
Accounts Receivable
   │
   ▼
Payment
   │
   ▼
Payment Allocation
```

Not every sale needs every document, but the architecture should support the full chain.

### `sales_order`

Represents the customer commitment.

### `delivery`

Represents physical fulfillment.

### `sales_invoice`

Creates the receivable and revenue.

Relationships:

```text
Invoice
 ├── Customer
 ├── Invoice Lines
 ├── Tax
 ├── Discount
 ├── Charges
 ├── Inventory Transactions
 └── Accounting Event
```

### Invoice accounting

Typical structure:

```text
DR Accounts Receivable
    CR Sales Revenue

DR Cost of Sales
    CR Inventory
```

The exact accounts come from the accounting rules rather than being hard-coded into the invoice itself.

---

# 12. Payment Entity

### `customer_payment`

Represents money received from a customer.

```text
Customer Payment
      │
      ├── Customer
      ├── Bank/Cash Account
      ├── Payment Allocation
      └── Accounting Event
```

Example:

```text
Customer owes ₦1,000,000

Payment = ₦600,000

Invoice balance = ₦400,000
```

The payment and its allocation should be separate concepts.

That allows:

* partial payments;
* multiple invoices;
* overpayments;
* unapplied receipts;
* payment reallocation.

---

# 13. Credit Notes & Returns

A return should not simply edit the original invoice.

Instead:

```text
Original Sale
      │
      ▼
Return Request
      │
      ▼
Return Approval
      │
      ▼
Inventory Return
      │
      ▼
Credit Note
      │
      ▼
Accounting Reversal/Adjustment
```

This preserves the original transaction.

---

# 14. Procurement & Accounts Payable

The purchasing model mirrors sales.

```text
Supplier
   │
   ▼
Purchase Request
   │
   ▼
Purchase Order
   │
   ▼
Goods Receipt
   │
   ▼
Supplier Invoice
   │
   ▼
Accounts Payable
   │
   ▼
Supplier Payment
```

### `purchase_order`

Commercial commitment.

### `goods_receipt`

Physical receipt of inventory.

### `supplier_invoice`

Financial obligation.

### `supplier_payment`

Settlement.

This separation allows Synbot to support proper matching:

```text
PO
 +
Goods Receipt
 +
Supplier Invoice
 =
Three-way validation
```

---

# 15. Expense Entity

Not every expense originates from inventory procurement.

Therefore Synbot needs a direct expense workflow.

### `expense`

```text
Expense
 ├── Employee/Vendor
 ├── Expense Account
 ├── Department
 ├── Cost Centre
 ├── Supporting Document
 ├── Approval
 └── Payment
```

Example:

```text
Office Electricity
    ↓
Utilities Expense
    ↓
Finance Department
    ↓
Payment
    ↓
GL
```

---

# 16. Banking & Cash Entities

Banking should have its own domain.

```text
Cash Account
Bank Account
     │
     ▼
Bank Transaction
     │
     ▼
Reconciliation
```

### `bank_account`

Contains:

* bank
* account number/reference
* currency
* GL account
* status

### `bank_transaction`

Represents actual bank-side movement.

Examples:

```text
Deposit
Withdrawal
Transfer
Bank Charge
Interest
Direct Debit
```

### `cash_transaction`

For physical cash.

Examples:

```text
Cash Receipt
Cash Payment
Petty Cash
Cash Transfer
Bank Lodgement
```

---

# 17. Bank Reconciliation Entities

```text
Bank Statement
      │
      ▼
Statement Transaction
      │
      ├── Matched
      ├── Likely Match
      ├── Unmatched
      ├── Duplicate
      └── Exception
```

### `bank_reconciliation`

Represents a reconciliation session.

### `reconciliation_item`

Connects:

```text
Bank Statement Transaction
        ↕
Synbot Transaction
```

The system should preserve the reconciliation history rather than simply marking a transaction "reconciled."

---

# 18. General Journal & Accounting Entities

This is the **core accounting layer**.

```text
Business Transaction
       │
       ▼
Accounting Event
       │
       ▼
Journal Entry
       │
       ├── Journal Lines
       │
       ▼
General Ledger
```

### `accounting_event`

Represents the accounting consequence of a business event.

Examples:

```text
Invoice Posted
Payment Received
Stock Adjustment
Asset Purchased
Payroll Posted
Depreciation Posted
Bank Charge
Expense Posted
```

### `journal_entry`

Header.

Contains:

* journal number
* date
* legal entity
* financial period
* source
* status
* description

### `journal_line`

The individual debit/credit lines.

```text
Journal Entry
 ├── Line 1: DR
 ├── Line 2: CR
 ├── Line 3: DR
 └── Line 4: CR
```

Control:

```text
SUM(DEBITS) = SUM(CREDITS)
```

must always hold before posting.

---

# 19. General Ledger

### `general_ledger`

Conceptually, the GL is the consolidated accounting view.

It should not be a second independent source of truth.

Instead:

```text
Journal Lines
      │
      ▼
General Ledger
```

Therefore:

```text
Invoice
   ↓
Accounting Event
   ↓
Journal
   ↓
Journal Lines
   ↓
GL
   ↓
Financial Statements
```

This creates the traceability the client wants.

---

# 20. Fixed Assets

Fixed assets require their own lifecycle.

```text
Asset Acquisition
       │
       ▼
Fixed Asset
       │
       ├── Capitalisation
       ├── Depreciation
       ├── Transfer
       ├── Revaluation
       └── Disposal
```

### `fixed_asset`

Fields/concepts:

* asset code
* asset name
* asset category
* acquisition date
* acquisition cost
* useful life
* depreciation method
* accumulated depreciation
* net book value
* location
* department
* status

### Depreciation

The workflow produces an accounting event:

```text
DR Depreciation Expense
CR Accumulated Depreciation
```

---

# 21. Payroll & HR Data Model

Payroll stays inside the financial architecture but is connected directly to the HR/Staff system.

```text
Employee
   │
   ├── Employment
   ├── Salary Structure
   ├── Attendance
   ├── Leave
   ├── Allowances
   ├── Deductions
   ├── Loans/Advances
   └── Payroll
```

### `employee`

HR owns the employee master.

### `employee_compensation`

Defines:

* basic salary
* allowances
* deductions
* effective dates

### `payroll_period`

Example:

```text
September 2026
OPEN
```

### `payroll_run`

Represents a payroll calculation.

```text
Payroll Run
    │
    ├── Employees
    ├── Gross Pay
    ├── Allowances
    ├── Deductions
    ├── Statutory deductions
    ├── Net Pay
    └── Payroll Journal
```

### `payroll_item`

Employee-level result for a payroll run.

### `payroll_payment`

Actual salary payment.

### Payroll → GL

The payroll engine ultimately generates accounting entries.

Conceptually:

```text
Payroll Calculation
       ↓
Payroll Approval
       ↓
Payroll Journal
       ↓
GL
       ↓
Financial Statements
```

This is why Payroll cannot be treated as an isolated HR feature.

---

# 22. Employee Loans & Advances

Because staff financial activity may need to flow between HR and Finance:

```text
Employee
   │
   ▼
Loan / Advance Request
   │
   ▼
Approval
   │
   ▼
Disbursement
   │
   ▼
Staff Receivable
   │
   ▼
Payroll Deduction
```

The outstanding balance should therefore be visible from both:

* HR/Staff Dashboard
* Finance

without creating two competing records.

---

# 23. Budgeting Entities

Budgeting should operate against the same accounting dimensions.

```text
Budget
 │
 ├── Account
 ├── Department
 ├── Cost Centre
 ├── Period
 └── Amount
```

### `budget`

Header.

### `budget_line`

Contains:

* account
* period
* department
* cost centre
* budget amount

Then:

```text
Budget
   +
Actual GL
   ↓
Variance
```

This supports:

* budget vs actual;
* department performance;
* cost-centre analysis;
* management reporting.

---

# 24. Tax Entities

Tax should not be embedded directly into invoices.

Instead, create a reusable tax model.

```text
Tax Configuration
      │
      ├── Tax Type
      ├── Rate
      ├── Effective Date
      ├── Account
      └── Rules
```

Transactions reference applicable tax configurations.

This gives us flexibility for the later Nigerian tax research without hard-coding assumptions into the database.

---

# 25. Approval Entities

Approval is cross-functional.

Instead of building approval logic independently into every module:

```text
Approval Request
      │
      ├── Entity Type
      ├── Entity ID
      ├── Requested By
      ├── Approver
      ├── Level
      ├── Decision
      └── Timestamp
```

This allows the same engine to approve:

* invoices;
* purchase orders;
* expenses;
* stock adjustments;
* payroll;
* journal entries;
* payments;
* asset purchases.

---

# 26. Audit Entities

The system needs an immutable audit trail.

### `audit_event`

Should capture concepts such as:

```text
WHO
WHAT
WHEN
WHERE
BEFORE
AFTER
SOURCE
REASON
```

Example:

```text
User: Finance Manager
Action: APPROVED
Entity: Sales Invoice
ID: INV-000492
Time: 2026-09-27 10:32
```

For financial records:

> **Never solve corrections by silently overwriting history.**

Use:

```text
Original Transaction
       ↓
Reversal / Correction
       ↓
Replacement Transaction
```

---

# 27. Document & Attachment Entities

Financial transactions will often have supporting documents.

Examples:

* supplier invoice;
* receipt;
* payment evidence;
* bank statement;
* purchase order;
* delivery note;
* expense receipt;
* asset documentation.

Therefore:

```text
Document
   │
   ├── Entity Type
   ├── Entity ID
   ├── File
   ├── Uploaded By
   └── Timestamp
```

Documents should attach to transactions without becoming the financial record themselves.

---

# 28. The Central Relationship Model

The most important relationships look like this:

```text
                         ORGANIZATION
                              │
                        LEGAL ENTITY
                              │
       ┌──────────────────────┼───────────────────────┐
       │                      │                       │
     MASTER                 USERS                   PERIODS
       │
 ┌─────┼─────────┬───────────┬───────────┐
 │     │         │           │           │
COA Customer  Supplier    Product     Employee
 │     │         │           │           │
 │     │         │         Batch       Payroll
 │     │         │           │           │
 └─────┴─────────┴───────────┴───────────┘
                         │
                  BUSINESS EVENTS
                         │
        ┌────────────────┼─────────────────┐
        │                │                 │
       SALES          PURCHASE         PAYROLL
        │                │                 │
       AR               AP                HR
        │                │                 │
        └────────────────┼─────────────────┘
                         │
                 ACCOUNTING EVENT
                         │
                    JOURNAL ENTRY
                         │
                   JOURNAL LINES
                         │
                  GENERAL LEDGER
                         │
          ┌──────────────┼──────────────┐
          │              │              │
         P&L       BALANCE SHEET   CASH FLOW
          │
          └──────────────┬──────────────┘
                         │
                  FINANCE INTELLIGENCE
```

---

# 29. Source-of-Truth Rules

This is one of the most important sections for the development team.

| Data                    | Source of truth                   |
| ----------------------- | --------------------------------- |
| Customer identity       | Customer master                   |
| Supplier identity       | Supplier master                   |
| Employee identity       | HR employee master                |
| Product                 | Product master                    |
| Batch                   | Batch master + inventory ledger   |
| Account                 | Chart of Accounts                 |
| Stock quantity          | Inventory ledger                  |
| Customer balance        | AR ledger / accounting engine     |
| Supplier balance        | AP ledger / accounting engine     |
| Bank balance            | Bank/cash ledger + reconciliation |
| Asset NBV               | Fixed asset register              |
| Employee payroll result | Payroll run                       |
| Accounting balance      | General Ledger                    |
| Financial statements    | Reporting engine derived from GL  |
| Audit history           | Audit engine                      |

The key design rule:

> **Do not allow dashboards to maintain their own financial copies of the truth.**

---

# 30. Transaction Lineage

Every financial figure should eventually be traceable.

For example, if the user sees:

**₦43,196,458.72 Net Income**

the system should allow:

```text
Net Income
   ↓
Income Statement
   ↓
Revenue / Expenses
   ↓
GL Accounts
   ↓
Journal Entries
   ↓
Source Transactions
   ↓
Invoice / Payment / Expense / Payroll etc.
```

This becomes the foundation for Synbot's **Finance AI**.

The AI should be able to explain:

> “Why did profit change this month?”

by querying the same authoritative data rather than generating an unsupported answer.

---

# 31. Entity Lifecycle

Almost every transactional entity should follow a common lifecycle.

```text
DRAFT
  ↓
VALIDATING
  ↓
PENDING APPROVAL
  ↓
APPROVED
  ↓
POSTED
  ↓
RECONCILED
  ↓
CLOSED
```

Not every entity requires every state.

For example:

```text
Customer
ACTIVE / INACTIVE

Invoice
DRAFT → APPROVED → POSTED → PARTIALLY PAID → PAID

Purchase Order
DRAFT → APPROVED → SENT → PARTIALLY RECEIVED → CLOSED

Payroll
DRAFT → CALCULATED → REVIEW → APPROVED → POSTED → PAID
```

---

# 32. Entity Ownership

A useful rule for development is:

> **One entity, one owner. Multiple modules may consume it.**

Example:

```text
Employee
Owner → HR

Payroll
Owner → Payroll/Finance

Employee salary
Owner → HR/Payroll

Payroll journal
Owner → Accounting

GL
Owner → Accounting

Financial statement
Owner → Reporting
```

This prevents modules from modifying one another's core records directly.

---

# 33. Core Entity Inventory — V1

The first development model should therefore contain approximately these conceptual entities:

### Organization

```text
organization
legal_entity
branch
department
cost_centre
financial_period
currency
```

### Master Data

```text
account
account_group
customer
customer_contact
supplier
supplier_contact
product
product_category
unit_of_measure
batch
price_list
tax_configuration
```

### Sales / AR

```text
sales_order
delivery
sales_invoice
sales_invoice_line
credit_note
credit_note_line
customer_payment
payment_allocation
customer_return
customer_ledger
```

### Procurement / AP

```text
purchase_request
purchase_order
purchase_order_line
goods_receipt
goods_receipt_line
supplier_invoice
supplier_invoice_line
supplier_payment
supplier_return
supplier_ledger
```

### Inventory

```text
warehouse
warehouse_location
inventory_transaction
inventory_balance
inventory_adjustment
stock_count
stock_transfer
stock_loan
stock_loan_return
stock_recall
```

### Banking / Cash

```text
bank_account
bank_transaction
cash_account
cash_transaction
bank_statement
bank_statement_transaction
bank_reconciliation
reconciliation_item
```

### Accounting

```text
accounting_event
journal_entry
journal_line
general_ledger
```

### Fixed Assets

```text
asset_category
fixed_asset
asset_transaction
depreciation_run
asset_disposal
```

### HR / Payroll

```text
employee
employment
employee_compensation
attendance
leave
allowance
deduction
employee_loan
payroll_period
payroll_run
payroll_item
payroll_payment
```

### Budgeting

```text
budget
budget_line
budget_variance
```

### Controls

```text
approval_request
approval_action
audit_event
validation_event
duplicate_check
```

### Documents

```text
document
document_attachment
```

---

# 34. What We Should NOT Build Yet

This map deliberately does **not** lock us into final database tables yet.

Before writing the actual backend schema, we still need to resolve several business rules.

Most importantly:

1. **Nigerian payroll and statutory calculations**
2. **Nigerian tax/VAT/WHT treatment**
3. **Inventory costing method**
4. **Exact multi-company/intercompany behaviour**
5. **Bank integration/reconciliation approach**
6. **Approval hierarchy**
7. **Customer sales workflow actually used by the client**
8. **Supplier procurement workflow actually used**
9. **Fixed-asset accounting policy**
10. **Period close/year-end rules**
11. **Credit notes/write-offs**
12. **Budgeting requirements**
13. **Whether healthcare/HMO billing will eventually feed this financial core**

Those should be researched before we freeze the schema.

---

# 35. The Architecture Principle

The entire model can ultimately be reduced to this:

```text
              BUSINESS WORLD
                    │
                    ▼
             TRANSACTION
                    │
                    ▼
              VALIDATION
                    │
                    ▼
               APPROVAL
                    │
                    ▼
             ACCOUNTING EVENT
                    │
                    ▼
             JOURNAL ENTRY
                    │
                    ▼
              GENERAL LEDGER
                    │
          ┌─────────┼─────────┐
          ▼         ▼         ▼
        REPORTS   CONTROLS   ANALYTICS
                              │
                              ▼
                         SYNBOT AI
```

And the reverse direction is equally important:

```text
AI / Dashboard
      ↓
Question
      ↓
Reporting / Query Layer
      ↓
Authoritative Financial Data
      ↓
GL / Transactions
      ↓
Source Document
```

**The AI never becomes the accounting system.**

It sits on top of it.

---

## Where this leaves us

We now have three layers established:

**1. Capability Matrix** → *what Synbot Finance must do*
**2. Workflow Map** → *how those capabilities operate*
**3. Data & Entity Map** → *what information those workflows create and how it connects*

The next logical step is the **Synbot Financial Data Model & Backend Architecture** — where we turn this entity map into actual modules, database boundaries, table structures, keys/relationships, transaction architecture, accounting-engine design, APIs, and service boundaries.

That is the point where we can start producing the **backend development specification that your development engine/agents can actually build from**.
