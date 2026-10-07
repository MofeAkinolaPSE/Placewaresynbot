# SYNBOT FINANCIAL WORKFLOW MAP

## From Business Event → Transaction → Accounting → Control → Reporting → Intelligence

### Document Status

**Version:** 1.0
**Purpose:** Define how financial activities should move through Synbot before backend and frontend architecture are frozen.

---

# 1. Core Workflow Philosophy

Synbot Finance is built around one principle:

> **A business event should be recorded once, then automatically propagate through every financial system that depends on it.**

The user should not enter the same information separately into:

* Sales
* Inventory
* Accounts Receivable
* General Ledger
* Cash Flow
* Financial Statements
* Reporting

Instead:

```text
BUSINESS EVENT
      ↓
TRANSACTION
      ↓
VALIDATION
      ↓
ACCOUNTING RULE
      ↓
JOURNAL
      ↓
LEDGERS
      ↓
FINANCIAL STATEMENTS
      ↓
REPORTING
      ↓
INTELLIGENCE
```

This reflects the client's expectation that transactions entered through invoices, receipts or other activities should automatically update the General Ledger and financial statements. The client's existing Sage workflow also treats the General Ledger as the consolidated view of financial activity.

---

# 2. Universal Transaction Lifecycle

Every financial transaction should follow a controlled lifecycle.

```text
DRAFT
  ↓
VALIDATE
  ↓
APPROVE
  ↓
POST
  ↓
RECONCILE
  ↓
CLOSE
```

Not every transaction requires manual approval or reconciliation, but the architecture must support the lifecycle.

## 2.1 Draft

The transaction is being prepared.

Examples:

* draft invoice
* draft purchase
* draft payment
* draft journal
* draft stock adjustment
* draft payroll.

No accounting impact yet.

---

## 2.2 Validate

Synbot checks:

* required fields
* valid customer/vendor
* valid account
* valid product
* valid batch
* valid period
* duplicate reference
* available stock
* credit limit
* approval requirements
* accounting classification
* debit/credit structure
* supporting information.

If validation fails:

```text
TRANSACTION
     ↓
VALIDATION FAILED
     ↓
EXCEPTION
     ↓
USER CORRECTS
     ↓
VALIDATE AGAIN
```

---

## 2.3 Approve

If the transaction requires approval:

```text
VALIDATED
    ↓
APPROVAL RULE
    ↓
APPROVER
    ↓
APPROVED / REJECTED
```

Rejected transactions return to correction rather than being posted.

---

## 2.4 Post

Once posted:

* accounting entries are created
* inventory is updated where applicable
* AR/AP is updated
* cash/bank balances update where applicable
* General Ledger updates
* financial reports update
* audit event is created.

---

## 2.5 Reconcile

Applicable transactions are subsequently reconciled against:

* bank
* cash
* supplier statements
* customer balances
* inventory counts
* payroll
* other control accounts.

---

## 2.6 Close

Once the accounting period is closed:

```text
POSTING → BLOCKED
```

unless an authorised adjustment/reopening workflow is used.

---

# 3. MASTER DATA WORKFLOW

Before transactions can operate, Synbot needs controlled master data.

```text
ORGANIZATION
    ↓
LEGAL ENTITY
    ↓
BRANCH
    ↓
DEPARTMENT
    ↓
COST CENTRE
```

Alongside this:

```text
CHART OF ACCOUNTS
CUSTOMERS
SUPPLIERS
PRODUCTS
BATCHES
BANK ACCOUNTS
FIXED ASSETS
EMPLOYEES
TAX CONFIGURATION
PAYROLL CONFIGURATION
```

Master data changes should themselves be auditable.

---

# 4. Chart of Accounts Workflow

```text
Create Account
      ↓
Select Account Type
      ↓
Select Parent
      ↓
Configure Posting Rules
      ↓
Configure Control Behaviour
      ↓
Activate
```

Example:

```text
EXPENSES
 └── Marketing
      └── Advertising
```

The client explicitly wants the ability to add new expense/income/stock heads when business requirements change.

### Control

An account cannot be deleted if financial transactions already reference it.

Instead:

```text
ACTIVE → INACTIVE
```

---

# 5. Sales-to-Cash Workflow

This is one of the most important Synbot workflows.

```text
CUSTOMER
   ↓
SALES TRANSACTION
   ↓
VALIDATE CUSTOMER
   ↓
CHECK CREDIT
   ↓
CHECK PRICE/DISCOUNT
   ↓
CHECK STOCK
   ↓
CREATE INVOICE
   ↓
POST
   ↓
AR + REVENUE + INVENTORY + COGS
   ↓
CUSTOMER PAYMENT
   ↓
CASH/BANK + AR
   ↓
RECONCILIATION
```

---

# 6. Sales Invoice Workflow

## User action

User creates an invoice.

### Synbot performs:

```text
1. Identify customer
2. Check account status
3. Check credit limit
4. Add products/services
5. Determine prices
6. Apply authorised discounts
7. Identify batches
8. Check stock
9. Calculate totals
10. Determine charges
11. Validate accounting
12. Approve if required
13. Post
```

### Accounting consequence

For a credit sale:

```text
DR Accounts Receivable
CR Sales Revenue
```

For inventory:

```text
DR Cost of Goods Sold
CR Inventory
```

### Result

Automatically update:

* invoice register
* sales journal
* customer ledger
* AR ageing
* inventory ledger
* COGS
* General Ledger
* P&L
* Balance Sheet
* relevant management reports.

The client's Sage dataset already contains separate sales journals, invoice registers, customer ledgers, transaction histories and inventory/COGS reports, giving us concrete report outputs against which these flows can eventually be tested.

---

# 7. Credit Limit Workflow

```text
CREATE INVOICE
      ↓
CALCULATE CURRENT EXPOSURE
      ↓
ADD NEW TRANSACTION
      ↓
COMPARE TO CREDIT LIMIT
```

### Within limit

```text
CONTINUE
```

### Exceeds limit

```text
WARNING
   ↓
USER DECISION
   ├── Cancel
   ├── Request Approval
   └── Authorised Override
```

The client specifically requested this behaviour.

The credit-limit rule must exist in the backend, not merely as a frontend warning.

---

# 8. Discount Workflow

Discounts should be explicitly classified.

```text
INVOICE
  ↓
DISCOUNT
  ↓
DISCOUNT RULE
  ↓
ACCOUNTING CLASSIFICATION
```

The client specifically raised the need to distinguish discounts and other charges rather than allowing them to disappear into the main sales account.

The exact account treatment should remain configurable.

---

# 9. Delivery Charge / Additional Charge Workflow

Example:

```text
Invoice
 ├── Product = ₦100,000
 └── Delivery = ₦10,000
```

Synbot should not blindly classify the entire ₦110,000 as product sales.

Instead:

```text
Product → Sales Revenue
Delivery → Configured Delivery/Other Income Account
```

The client explicitly highlighted this classification requirement.

This becomes a general:

# Charge Classification Engine

Supporting configurable categories such as:

* delivery
* service charge
* discount
* surcharge
* other income
* other expense.

---

# 10. Customer Payment Workflow

```text
CUSTOMER PAYMENT
      ↓
IDENTIFY CUSTOMER
      ↓
SELECT PAYMENT ACCOUNT
      ↓
MATCH OUTSTANDING INVOICE(S)
      ↓
ALLOCATE PAYMENT
      ↓
POST
```

Accounting:

```text
DR Bank/Cash
CR Accounts Receivable
```

Then:

```text
Customer Balance ↓
Outstanding Invoice ↓
Cash/Bank ↑
GL Updated
```

### Partial payment

If:

Invoice = ₦1,000,000

Payment = ₦600,000

Then:

```text
Outstanding = ₦400,000
```

The invoice remains open.

---

# 11. Customer Credit Note Workflow

```text
Customer Issue
      ↓
Credit Note
      ↓
Reference Original Invoice
      ↓
Validate
      ↓
Approve
      ↓
Post
```

Potential effects:

* AR decreases
* revenue decreases
* inventory may increase if goods are returned
* COGS may reverse/adjust.

The exact accounting depends on the reason for the credit note.

---

# 12. Customer Return — Return Inward

```text
CUSTOMER
    ↓
RETURN REQUEST
    ↓
REFERENCE ORIGINAL SALE
    ↓
VALIDATE PRODUCT/BATCH
    ↓
INSPECT
    ↓
APPROVE
    ↓
RETURN INWARD
    ↓
INVENTORY UPDATE
    ↓
AR/REFUND/CREDIT NOTE
    ↓
ACCOUNTING UPDATE
```

The client specifically identified Return Inward as a required inventory workflow.

The returned stock should not automatically become available stock if it is:

* damaged
* expired
* quarantined
* recalled.

That status must be determined by the return workflow.

---

# 13. Customer Recall Workflow

This is a dedicated operational workflow.

```text
SELECT PRODUCT/BATCH
        ↓
SEARCH ALL OUTBOUND MOVEMENTS
        ↓
IDENTIFY CUSTOMERS
        ↓
IDENTIFY INVOICES
        ↓
IDENTIFY QUANTITIES
        ↓
CREATE RECALL
        ↓
CUSTOMER NOTIFICATION
        ↓
RETURN TRACKING
        ↓
STOCK QUARANTINE/DISPOSITION
        ↓
FINANCIAL ADJUSTMENT
        ↓
CLOSE RECALL
```

The client specifically wants batch-level traceability to determine who purchased a particular batch and the quantity purchased.

---

# 14. Stock Loan Workflow

A loan must be treated differently from a sale.

```text
REQUEST LOAN
    ↓
CUSTOMER
    ↓
PRODUCT
    ↓
BATCH
    ↓
QUANTITY
    ↓
APPROVAL
    ↓
LOAN OUT
```

### Accounting/stock behaviour

```text
Inventory ↓
Loan Stock ↑
Sales Revenue = 0
AR = 0
```

unless the business later converts the loan into a sale.

The client explicitly described loan stock as separate from sales and requiring batch tracking.

---

# 15. Loan Return Workflow

```text
LOAN
 ↓
CUSTOMER RETURNS STOCK
 ↓
VERIFY QUANTITY
 ↓
CAPTURE RETURNED BATCH
 ↓
MATCH ORIGINAL LOAN
 ↓
UPDATE LOAN BALANCE
 ↓
UPDATE INVENTORY
```

Example:

```text
Original:
Batch A → 5 units loaned

Returned:
Batch B → 5 units
```

Synbot preserves both batch histories.

The returned batch can then join the existing inventory for that batch where appropriate, following the client's described workflow.

---

# 16. Purchase-to-Pay Workflow

```text
SUPPLIER
   ↓
PURCHASE REQUEST
   ↓
PURCHASE ORDER
   ↓
GOODS RECEIVED
   ↓
INVENTORY UPDATE
   ↓
SUPPLIER INVOICE
   ↓
AP
   ↓
APPROVAL
   ↓
PAYMENT
   ↓
SUPPLIER LEDGER
   ↓
BANK/CASH
```

The actual client PO workflow remains a **research/confirmation item** because the Sage exports do not prove that purchase orders are actively used.

---

# 17. Goods Receipt Workflow

```text
GOODS RECEIVED
      ↓
VERIFY SUPPLIER
      ↓
VERIFY PO (if applicable)
      ↓
COUNT QUANTITY
      ↓
CAPTURE BATCH
      ↓
CAPTURE EXPIRY
      ↓
RECORD COST
      ↓
ACCEPT / QUARANTINE / REJECT
      ↓
INVENTORY LEDGER
```

Where accounting recognition is appropriate:

```text
DR Inventory
CR Accounts Payable / Goods Received Control
```

The exact GRN/accounting treatment will be finalized during the accounting architecture stage.

---

# 18. Supplier Invoice Workflow

```text
SUPPLIER INVOICE
       ↓
DUPLICATE CHECK
       ↓
SUPPLIER VALIDATION
       ↓
MATCH PO
       ↓
MATCH GOODS RECEIVED
       ↓
MATCH AMOUNT
       ↓
APPROVAL
       ↓
POST AP
```

Where three-way matching is enabled:

```text
PO
+
GRN
+
Invoice
=
MATCH
```

If not:

```text
EXCEPTION
```

---

# 19. Supplier Payment Workflow

```text
SELECT SUPPLIER
      ↓
VIEW OUTSTANDING AP
      ↓
SELECT INVOICE(S)
      ↓
CREATE PAYMENT
      ↓
APPROVAL
      ↓
POST
      ↓
BANK/CASH
      ↓
AP REDUCED
      ↓
SUPPLIER LEDGER UPDATED
```

Accounting:

```text
DR Accounts Payable
CR Bank/Cash
```

---

# 20. Supplier Return — Return Outward

```text
SUPPLIER
    ↑
RETURN REQUEST
    ↑
STOCK IDENTIFICATION
    ↑
BATCH IDENTIFICATION
    ↑
APPROVAL
    ↑
RETURN OUTWARD
```

Effects:

```text
Inventory ↓
AP/Supplier Balance ↓ or adjusted
Return transaction recorded
GL updated
```

The client explicitly requested Return Outward.

---

# 21. Inventory Adjustment Workflow

```text
ADJUSTMENT REQUEST
       ↓
SELECT PRODUCT
       ↓
SELECT BATCH
       ↓
CURRENT QUANTITY
       ↓
COUNT/REASON
       ↓
PROPOSE ADJUSTMENT
       ↓
APPROVAL
       ↓
POST
```

Reasons:

* shortage
* excess
* damage
* expiry
* count correction
* data correction
* other approved reason.

The client's existing Sage report inventory identifies the Inventory Adjustment Journal as an important missing report, specifically because it would capture write-offs, expiry and count corrections.

---

# 22. Inventory Reconciliation Workflow

```text
SYSTEM STOCK
     ↓
PHYSICAL COUNT
     ↓
COMPARE
     ↓
DIFFERENCE?
 ┌───┴───┐
NO      YES
│        │
CLOSE   REVIEW
         ↓
      ADJUSTMENT
         ↓
       APPROVE
         ↓
        POST
```

This should produce an audit record showing:

```text
System Quantity
Physical Quantity
Variance
Reason
Approver
Adjustment
```

---

# 23. Inventory-to-GL Workflow

This is one of the most important cross-module flows.

```text
INVENTORY EVENT
      ↓
INVENTORY LEDGER
      ↓
ACCOUNTING RULE
      ↓
JOURNAL
      ↓
GENERAL LEDGER
```

Examples:

### Purchase

```text
Inventory ↑
AP ↑
```

### Sale

```text
Inventory ↓
COGS ↑
```

### Return Inward

```text
Inventory ↑
COGS ↓ / appropriate reversal
AR adjusted
```

### Write-off

```text
Inventory ↓
Inventory Loss/Expense ↑
```

The client explicitly stated that inventory movements must reflect in the accounts.

---

# 24. Cash Receipt Workflow

```text
CASH RECEIVED
      ↓
IDENTIFY SOURCE
      ↓
CUSTOMER / OTHER INCOME / OTHER
      ↓
VALIDATE
      ↓
POST
```

Example:

```text
DR Cash
CR Accounts Receivable
```

or, depending on source:

```text
DR Cash
CR Other Income
```

The account classification should come from the configured accounting rule rather than user improvisation.

---

# 25. Cash-to-Bank Lodgement Workflow

The client specifically described transferring physical cash to the bank through a General Journal-style transaction.

```text
CASH ON HAND
      ↓
BANK LODGEMENT
      ↓
VERIFY AMOUNT
      ↓
POST
```

Accounting:

```text
DR Bank
CR Cash on Hand
```

Result:

```text
Cash on Hand ↓
Bank ↑
Total Cash = unchanged
```

---

# 26. Bank Reconciliation Workflow

```text
BANK STATEMENT
      ↓
IMPORT/RECEIVE TRANSACTIONS
      ↓
MATCH AGAINST LEDGER
      ↓
AUTO MATCH
      ↓
MANUAL REVIEW
      ↓
EXCEPTIONS
      ↓
RECONCILE
```

Each transaction becomes:

```text
MATCHED
UNMATCHED
DUPLICATE
EXCEPTION
```

The client's Sage reconciliation exports cover account reconciliation, deposits, deposits in transit, outstanding checks and other outstanding items.

---

# 27. Bank Exception Workflow

```text
UNMATCHED TRANSACTION
        ↓
IDENTIFY POSSIBLE SOURCE
        ↓
SUGGEST MATCH
        ↓
USER CONFIRMS
        ↓
POST/ALLOCATE
```

If no match:

```text
EXCEPTION QUEUE
```

Nothing should silently disappear.

---

# 28. General Journal Workflow

The General Journal should support controlled accounting events that do not originate from normal operational workflows.

Examples:

* asset acquisition
* depreciation
* correction
* transfer
* accrual
* adjustment
* opening balance
* reclassification.

The client's finance discussion specifically describes using journals for transfers, asset purchases and depreciation.

Workflow:

```text
CREATE JOURNAL
      ↓
ENTER LINES
      ↓
DEBIT = CREDIT?
      ↓
ACCOUNT VALID?
      ↓
PERIOD OPEN?
      ↓
APPROVAL
      ↓
POST
```

---

# 29. Fixed Asset Acquisition Workflow

```text
ASSET PURCHASE
      ↓
IDENTIFY ASSET
      ↓
CAPITALISE
      ↓
CREATE ASSET RECORD
      ↓
POST JOURNAL
      ↓
ASSET REGISTER
      ↓
GL
```

Example:

```text
DR Fixed Asset
CR Bank/AP
```

---

# 30. Depreciation Workflow

```text
ASSET REGISTER
      ↓
DEPRECIATION SCHEDULE
      ↓
PERIOD CALCULATION
      ↓
REVIEW
      ↓
POST
```

Example:

```text
DR Depreciation Expense
CR Accumulated Depreciation
```

The client specifically described annual depreciation and journal posting of depreciation.

---

# 31. Asset Disposal Workflow

```text
SELECT ASSET
      ↓
CHECK NET BOOK VALUE
      ↓
DISPOSAL VALUE
      ↓
APPROVAL
      ↓
REMOVE ASSET
      ↓
CALCULATE GAIN/LOSS
      ↓
POST
```

---

# 32. Expense Workflow

```text
EXPENSE REQUEST
      ↓
CLASSIFY EXPENSE
      ↓
SELECT DEPARTMENT/COST CENTRE
      ↓
ATTACH SUPPORT
      ↓
APPROVAL
      ↓
PAYMENT
      ↓
POST
```

Example:

```text
DR Expense
CR Bank/AP
```

New expense heads can be introduced through controlled Chart of Accounts administration, as requested by the client.

---

# 33. Payroll Workflow

Payroll becomes a major cross-functional workflow.

```text
EMPLOYEE MASTER
      ↓
ATTENDANCE
      ↓
LEAVE
      ↓
OVERTIME
      ↓
ALLOWANCES
      ↓
DEDUCTIONS
      ↓
GROSS PAY
      ↓
STATUTORY CALCULATIONS
      ↓
NET PAY
      ↓
PAYROLL REVIEW
      ↓
APPROVAL
      ↓
PAYSLIPS
      ↓
PAYMENT
      ↓
PAYROLL JOURNAL
      ↓
GENERAL LEDGER
```

The client's current Sage employee file is empty, so the historical Sage data does not provide a payroll workflow to replicate. Payroll therefore remains a **Synbot target capability**, requiring separate client/payroll research.

---

# 34. Payroll-to-GL Workflow

Payroll should automatically produce accounting entries.

Conceptually:

```text
Payroll Run
     ↓
Salary Expense
     ↓
Payroll Liabilities
     ↓
Net Salary Payable
```

Then:

```text
Salary Payment
     ↓
Bank
     ↓
Payroll Liability ↓
```

This ensures payroll participates in the same accounting ecosystem as every other business process.

---

# 35. HR-to-Payroll Workflow

```text
EMPLOYEE
      ↓
HR PROFILE
      ↓
EMPLOYMENT STATUS
      ↓
SALARY STRUCTURE
      ↓
ALLOWANCES/DEDUCTIONS
      ↓
PAYROLL
```

Changes to salary or employment status should be:

```text
REQUEST
 ↓
APPROVAL
 ↓
EFFECTIVE DATE
 ↓
PAYROLL
```

The employee record should therefore be the common link between HR and Finance.

---

# 36. Staff Loan / Advance Workflow

```text
EMPLOYEE REQUEST
      ↓
APPROVAL
      ↓
DISBURSEMENT
      ↓
STAFF RECEIVABLE
      ↓
PAYROLL DEDUCTIONS
      ↓
BALANCE REDUCTION
```

This is a natural extension of the HR/Payroll/Finance integration and should be confirmed against the client's actual HR policies before final implementation.

---

# 37. Budget Workflow

```text
CREATE BUDGET
      ↓
ASSIGN PERIOD
      ↓
ASSIGN ACCOUNT
      ↓
ASSIGN DEPARTMENT/COST CENTRE
      ↓
APPROVE
      ↓
ACTUAL TRANSACTIONS
      ↓
VARIANCE ENGINE
```

Output:

```text
BUDGET
ACTUAL
VARIANCE
VARIANCE %
FORECAST
```

---

# 38. Financial Reporting Workflow

Reports should not have independent accounting logic.

```text
POSTED TRANSACTIONS
       ↓
GENERAL LEDGER
       ↓
REPORTING ENGINE
       ↓
REPORT DEFINITION
       ↓
FILTERS
       ↓
CALCULATION
       ↓
REPORT
```

Core outputs:

* Balance Sheet
* Income Statement
* Cash Flow
* Trial Balance
* General Ledger
* AR
* AP
* Inventory
* Fixed Assets
* Payroll
* Budget/Variance.

The client's actual Sage corpus contains the corresponding financial statement, GL, AR, AP, inventory and reconciliation report families, giving us a concrete report catalogue.

---

# 39. Report Drill-Down Workflow

Every major financial figure should be traceable.

```text
BALANCE SHEET
      ↓
ACCOUNT
      ↓
LEDGER
      ↓
JOURNAL
      ↓
TRANSACTION
      ↓
SOURCE EVENT
```

Example:

```text
Inventory
 ₦450,000,000
      ↓
Inventory Valuation
      ↓
Product
      ↓
Batch
      ↓
Stock Movement
      ↓
Purchase/Sale/Adjustment
```

This becomes the foundation of Synbot's **financial lineage**.

---

# 40. Internal Accounting Review Workflow

This should run continuously or on demand.

```text
FINANCIAL DATA
      ↓
CONTROL ENGINE
      ↓
RUN CHECKS
      ↓
EXCEPTIONS
      ↓
REVIEW QUEUE
```

Checks include:

### AR

```text
AR Control Account
vs
Customer Balances
```

### AP

```text
AP Control Account
vs
Supplier Balances
```

### Inventory

```text
Inventory GL
vs
Inventory Valuation
```

### Bank

```text
Bank Ledger
vs
Reconciliation
```

### Payroll

```text
Payroll Liability
vs
Unpaid Payroll
```

### Accounting

```text
Total Debits
=
Total Credits
```

The client's existing Sage workflow specifically identifies AR differences between the ageing report and Balance Sheet as an internal accounting review issue.

---

# 41. Duplicate Transaction Workflow

The client specifically mentioned duplicate check numbers.

```text
NEW TRANSACTION
      ↓
REFERENCE CHECK
      ↓
DUPLICATE?
 ┌────┴────┐
NO        YES
│          │
CONTINUE   FLAG
             ↓
           REVIEW
```

Possible duplicate signals:

* same check number
* same supplier
* same amount
* same date
* same invoice
* same payment reference.

---

# 42. Audit Workflow

Every posted financial event creates an audit event.

```text
TRANSACTION
     ↓
POST
     ↓
AUDIT EVENT
```

Audit captures:

```text
WHO
WHAT
WHEN
SOURCE
REFERENCE
BEFORE
AFTER
APPROVAL
```

For corrections:

```text
ORIGINAL
   ↓
REVERSAL
   ↓
CORRECTED TRANSACTION
```

Never silently overwrite posted accounting history.

The existing Sage report inventory identifies Audit Trail as a missing company-level report and specifically notes its importance to auditors.

---

# 43. Financial Period Closing Workflow

```text
PERIOD
 ↓
RUN CONTROL CHECKS
 ↓
RESOLVE EXCEPTIONS
 ↓
RECONCILE
 ↓
RUN TRIAL BALANCE
 ↓
REVIEW FINANCIAL STATEMENTS
 ↓
APPROVE CLOSURE
 ↓
LOCK PERIOD
```

After closure:

```text
Normal posting = BLOCKED
```

Any subsequent adjustment requires an authorised adjustment workflow.

---

# 44. Year-End Workflow

```text
YEAR-END REVIEW
      ↓
RECONCILIATIONS
      ↓
ADJUSTMENTS
      ↓
DEPRECIATION
      ↓
ACCRUALS
      ↓
FINAL TRIAL BALANCE
      ↓
FINANCIAL STATEMENTS
      ↓
APPROVAL
      ↓
CLOSE YEAR
      ↓
CARRY FORWARD BALANCES
```

Retained earnings and other appropriate balances carry forward according to the configured accounting rules.

---

# 45. Finance AI Workflow

AI sits **above** the financial engine.

It should never bypass the accounting system.

```text
USER
 ↓
FINANCE AI
 ↓
INTENT
 ↓
FINANCIAL QUERY
 ↓
AUTHORITATIVE DATA
 ↓
CALCULATION
 ↓
EXPLANATION
```

Example:

> "Why did profit fall this month?"

Synbot:

```text
Revenue
   ↓
COGS
   ↓
Expenses
   ↓
Variance
   ↓
Major Drivers
   ↓
Explanation
```

The AI should provide evidence and drill-down paths rather than inventing financial explanations.

---

# 46. Anomaly Detection Workflow

```text
TRANSACTION
      ↓
RULE CHECK
      +
HISTORICAL PATTERN
      +
CONTEXT
      ↓
ANOMALY DETECTED?
```

Examples:

* duplicate payment
* unusual journal
* unusual discount
* unusual stock adjustment
* abnormal supplier invoice
* unexpected payroll change.

Result:

```text
NORMAL
LOW RISK
REVIEW
HIGH PRIORITY
```

The exact risk methodology should be designed later.

---

# 47. Executive Finance Dashboard Workflow

The dashboard is not a separate data source.

```text
ACCOUNTING ENGINE
       ↓
REPORTING ENGINE
       ↓
ANALYTICS
       ↓
DASHBOARD
```

Core indicators:

```text
Revenue
Gross Profit
Net Profit
Cash
AR
AP
Inventory
Overdue AR
Outstanding AP
Bank Reconciliation
Budget Variance
Payroll
Exceptions
```

Then:

```text
Dashboard Metric
      ↓
Click
      ↓
Underlying Report
      ↓
Transactions
      ↓
Source Event
```

---

# 48. Cross-Module Master Workflow

This is the workflow that ultimately ties everything together.

## Example: Product Sale

```text
CUSTOMER
   ↓
INVOICE
   ↓
CREDIT CONTROL
   ↓
INVENTORY CHECK
   ↓
BATCH ALLOCATION
   ↓
SALE POSTED
   │
   ├──→ AR
   ├──→ REVENUE
   ├──→ INVENTORY
   ├──→ COGS
   ├──→ CUSTOMER LEDGER
   ├──→ INVENTORY LEDGER
   ├──→ GENERAL LEDGER
   ├──→ P&L
   ├──→ BALANCE SHEET
   └──→ ANALYTICS
```

Later:

```text
CUSTOMER PAYMENT
   ↓
BANK/CASH
   ↓
AR REDUCTION
   ↓
CASH FLOW
   ↓
BANK RECONCILIATION
```

One business event therefore propagates across the entire financial ecosystem.

---

# 49. The Synbot Financial Event Model

The workflows reveal a deeper architectural concept:

## Everything begins with an event.

Examples:

```text
SALE
PURCHASE
PAYMENT
RECEIPT
RETURN_IN
RETURN_OUT
LOAN_OUT
LOAN_RETURN
ADJUSTMENT
TRANSFER
RECALL
ASSET_PURCHASE
DEPRECIATION
PAYROLL
EXPENSE
BANK_TRANSACTION
JOURNAL
```

Each event has:

```text
EVENT
 ↓
BUSINESS DATA
 ↓
VALIDATION
 ↓
ACCOUNTING RULE
 ↓
POSTING
 ↓
AUDIT
 ↓
REPORTING
```

This should become the foundation of the eventual backend architecture.

---

# 50. Workflow Dependency Map

The major dependencies now look like this:

```text
                    MASTER DATA
                         │
        ┌────────────────┼─────────────────┐
        │                │                 │
     CUSTOMERS        SUPPLIERS        PRODUCTS
        │                │                 │
        ↓                ↓                 ↓
       SALES         PURCHASES        INVENTORY
        │                │                 │
        ↓                ↓                 ↓
       AR               AP          INVENTORY GL
        │                │                 │
        └────────────────┼─────────────────┘
                         ↓
                 ACCOUNTING ENGINE
                         ↓
              GENERAL LEDGER
                         ↓
       ┌─────────────────┼─────────────────┐
       │                 │                 │
      P&L          BALANCE SHEET      CASH FLOW
       │                 │                 │
       └─────────────────┼─────────────────┘
                         ↓
                 REPORTING ENGINE
                         ↓
                 FINANCE INTELLIGENCE
```

And:

```text
                    HR / STAFF
                        │
                        ↓
                     PAYROLL
                        │
                        ↓
                 ACCOUNTING ENGINE
```

---

# 51. The Control Layer Surrounds Everything

The final architectural insight from the workflow map is that controls cannot be a single page called "Audit."

They surround the entire system.

```text
┌───────────────────────────────────────────────┐
│               CONTROL ENGINE                  │
│                                               │
│ Validation                                    │
│ Approval                                      │
│ Permissions                                   │
│ Duplicate Detection                           │
│ Credit Control                                │
│ Accounting Integrity                          │
│ Reconciliation                                │
│ Audit Trail                                   │
│ Period Control                                │
│ Exception Management                          │
│                                               │
│     ┌─────────────────────────────────┐       │
│     │       FINANCIAL ENGINE           │       │
│     └─────────────────────────────────┘       │
│                                               │
└───────────────────────────────────────────────┘
```

This is critical because the client doesn't simply want Synbot to **record mistakes**.

They want Synbot to **prevent, detect and explain mistakes**.

---

# 52. Workflow Classification

The workflow map now gives us five classes.

### A. Operational workflows

* Sales
* Purchases
* Inventory
* Returns
* Loan stock
* Recall
* Payments
* Receipts.

### B. Accounting workflows

* Journal
* GL
* AR
* AP
* Assets
* Payroll
* Period close.

### C. Control workflows

* Validation
* Approval
* Credit control
* Duplicate detection
* Reconciliation
* Audit
* Exception management.

### D. Reporting workflows

* Financial statements
* Operational reports
* Management reports
* Drill-down
* Financial lineage.

### E. Intelligence workflows

* Financial analysis
* Forecasting
* anomaly detection
* AI finance assistant
* management insights.

---

# 53. What This Map Gives Us

We can now see the system as:

```text
              BUSINESS
                 │
                 ↓
            TRANSACTIONS
                 │
                 ↓
             CONTROLS
                 │
                 ↓
             ACCOUNTING
                 │
                 ↓
              LEDGER
                 │
                 ↓
             REPORTING
                 │
                 ↓
           INTELLIGENCE
```

And importantly:

> **The General Ledger is not the starting point. It is the accounting consequence of business activity.**

That distinction should drive the backend design.

---

# 54. Remaining Workflow Research Items

Before freezing the architecture, these workflows still require dedicated research:

1. Nigerian payroll/statutory workflow
2. Nigerian tax/VAT/withholding workflow
3. Multi-company/intercompany workflow
4. Exact customer sales workflow
5. Exact supplier procurement workflow
6. Inventory costing method
7. Fixed-asset policy
8. Budget approval hierarchy
9. Payroll approval hierarchy
10. Bank integration/reconciliation method
11. HMO/healthcare billing integration where Synbot Health is involved
12. Staff loans/advances policy
13. Credit-note/write-off policy
14. Period-close/year-end policy
15. User roles and financial approval matrix.

These should be resolved **before** the final backend specification.

---

# 55. Final Workflow Principle

The eventual Synbot Financial System should behave like this:

```text
USER ENTERS BUSINESS EVENT
             ↓
        SYNBOT VALIDATES
             ↓
       SYNBOT CONTROLS
             ↓
      ACCOUNTING RULE FIRES
             ↓
        JOURNAL CREATED
             ↓
       LEDGERS UPDATED
             ↓
       INVENTORY UPDATED
             ↓
       AR/AP UPDATED
             ↓
        CASH UPDATED
             ↓
       GENERAL LEDGER
             ↓
      FINANCIAL STATEMENTS
             ↓
         DASHBOARDS
             ↓
       FINANCE INTELLIGENCE
```

**One entry. One transaction. One accounting truth.**

That is the workflow philosophy I recommend carrying forward into the development architecture.
