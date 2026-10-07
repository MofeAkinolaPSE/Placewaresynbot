# Sage 50 Report Inventory: what Sage provides vs. what we hold

**Purpose.** The goal is to replicate Sage's full financial reporting in ACE. This is the checklist of every report type Sage 50 (2013) offers, by area, with a note of which ones we already hold as a real export from the client's Sage.

**Snapshot we hold:** every export runs to **30 June 2026**. The last transactions are dated 26 June; the General Ledger runs to 30 June. This is the same point the client's Sage company is open to. The financial statements tie to it: Petty Cash is ₦97,015 on the Balance Sheet, the Trial Balance and the GL Account Summary.

**Where the files are:**
- `data-assimilation/sage-exports/<Area>/`: 42 reports
- `data-assimilation/backupsageexports/`: 11 financial statements
- `backend/docs/Latestmods-TB/sage-link/export-templates/`: 7 Import/Export templates (these are what ACE sends back to Sage, not reports)

All 53 report files were opened and checked. Each has headers and real data.

> **About the "Sage provides" list.** It is the standard *Reports & Forms* list for Sage 50 (Peachtree) 2013. It was compiled from the product, not from screenshots of the client's own menu. The client's install may name a few reports differently, or have custom reports saved alongside these. To confirm it, take one screenshot per area of the Reports & Forms menu.

**Key**
- ✅ held (real export)
- ❌ not held
- ⚪ area not used by this client (their Sage has no data for it)

---

## Summary

| Sage report area | Held | Not held | Notes |
|---|---|---|---|
| Financial Statements | 12 | 2 | Balance Sheet, Income Statement, Cash Flow and Retained Earnings are all held |
| General Ledger | 7 | 2 | GL, Trial Balance, Journal and COA are all held |
| Accounts Receivable | 12 | 11 | Every AR report with data is held; the missing ones are sales orders, quotes and tax |
| Accounts Payable | 7 | 6 | **Cash Disbursements Journal is missing**, and it matters (see Gaps) |
| Inventory | 8 | 10 | **Inventory Adjustment Journal is missing**, and it matters (see Gaps) |
| Account Reconciliation | 6 | 0 | Complete |
| Payroll | 0 | 10 | ⚪ The client's Sage employee file is empty, so payroll is not run in Sage |
| Jobs | 0 | 6 | ⚪ The job/project file is empty |
| Time/Expense | 0 | 4 | ⚪ Not used |
| Company | 0 | 4 | **Audit Trail is missing**, and auditors ask for it |

---

## 1. Financial Statements (`data-assimilation/backupsageexports/` + `sage-exports/Financial Statements/`)

| Sage report | Held | File | Rows |
|---|---|---|---|
| Balance Sheet | ✅ | `Balance sheet.xlsx` | 83 |
| Balance Sheet with Budget | ✅ | `Balance sheet- budget.xlsx` | 209 |
| Income Statement (current month + YTD) | ✅ | `Income statement.xlsx` | 283 |
| Income – 2 Years (this year vs last) | ✅ | `Income 2 yrs.xlsx` | 283 |
| Income – 12 Period (month by month) | ✅ | `Income 12 period.xlsx` | 283 |
| Income vs Budget, period | ✅ | `Income budget per.xlsx` | 283 |
| Income vs Budget, year to date | ✅ | `Income budget ytd.xlsx` | 283 |
| Statement of Revenue & Expenses vs Budget | ✅ | `stmt rev exp budget.xlsx` | 189 |
| Cash Flow | ✅ | `Cash flow.xlsx` | 194 |
| Retained Earnings | ✅ | `Retained earnings.xlsx` | 7 |
| Statement of Financial Position (condensed: Cash / AR / Inventory …) | ✅ | `Stmt financial pos.xlsx` | 16 |
| GL Account Summary (opening, debits, credits, closing per account) | ✅ | `sage-exports/Financial Statements/Gl account summaru.xlsx` | 339 |
| Income/Earnings (income statement with earnings per share) | ❌ | none | |
| Statement of Changes in Financial Position | ❌ | none | Possibly the same as "Stmt financial pos"; confirm with the accountant |

Figures at 30 June 2026:
- Year-to-date net income: ₦94,038,821.73. Of this, ₦43,196,458.72 was earned in the month.
- Retained earnings: ₦983,477,366.12 at the start of the period, ₦1,077,516,187.85 after the year's income is added.

## 2. General Ledger (`sage-exports/General Ledger/`)

| Sage report | Held | File | Rows | Covers |
|---|---|---|---|---|
| General Ledger | ✅ | `GEneral Ledger.xlsx` | 447,427 | Jan 2017 – Jun 2026 |
| General Ledger Trial Balance | ✅ | `General Ledger Trial balance.xlsx` | 167 | as of Jun 2026 |
| General Journal | ✅ | `General Journal.xlsx` | 22,298 | Dec 2018 – Jun 2026 |
| Chart of Accounts | ✅ | `Chart of accounts.xlsx` | 465 | |
| Cash Account Register | ✅ | `Cash ACcount Register.xlsx` | 10,557 | Dec 2018 – Jun 2026 |
| Account Variance | ✅ | `Account Variance.xlsx` | 60,321 | |
| Account Variance – Dual Budgets | ✅ | `Account Variance-Dual Budgets.xlsx` | 60,321 | |
| Working Trial Balance | ❌ | none | | Trial balance with blank columns for the accountant's manual adjustments |
| Budget Report | ❌ | none | | |

## 3. Accounts Receivable (`sage-exports/Account-Receiveable/`)

| Sage report | Held | File | Rows | Covers |
|---|---|---|---|---|
| Aged Receivables | ✅ | `Aged Receiveable.xlsx` | 3,476 | |
| Sales Journal | ✅ | `Sales Journal.xlsx` | 263,332 | Dec 2018 – Jun 2026 |
| Cash Receipts Journal | ✅ | `Cash receipts journal.xlsx` | 75,039 | Jan 2019 – Jun 2026 |
| Customer Ledgers | ✅ | `Customer Ledger.xlsx` | 63,642 | Dec 2018 – Jun 2026 |
| Customer Transaction History | ✅ | `Customers Transaction History.xlsx` | 112,074 | Dec 2018 – Jun 2026 |
| Customer Management Detail | ✅ | `Customer Management Details.xlsx` | 34,203 | |
| Customer Sales History | ✅ | `Customer sales History.xlsx` | 1,095 | |
| Items Sold to Customers | ✅ | `Items sold to customers.xlsx` | 23,880 | |
| Invoice Register | ✅ | `Invoice Register.xlsx` | 33,320 | Dec 2018 – Jun 2026 |
| Customer List | ✅ | `Customer List.xlsx` | 1,521 | |
| Customer Master File List | ✅ | `Customer Master File list.xlsx` | 1,523 | |
| Customer Contact List | ✅ | `Contacts list.xlsx` | 1,523 | |
| Sales Order Journal | ❌ | none | | |
| Sales Order Register | ❌ | none | | |
| Sales Order Report | ❌ | none | | |
| Sales Backorder Report | ❌ | none | | |
| Picking List Report | ❌ | none | | |
| Quote Register | ❌ | none | | |
| Sales Rep Report | ❌ | none | | |
| Taxable/Exempt Sales | ❌ | none | | Client posts no VAT through Sage sales |
| Sales Tax Codes | ❌ | none | | |
| Prospect List | ❌ | none | | |
| Ticket Listing by Customer | ❌ | none | | Time/Expense feature, not used |

## 4. Accounts Payable (`sage-exports/Account-Payable/`)

| Sage report | Held | File | Rows | Covers |
|---|---|---|---|---|
| Aged Payables | ✅ | `Aged Payables.xlsx` | 141 | |
| Purchase Journal | ✅ | `Purchased journal.xlsx` | 3,446 | Jan 2019 – Jun 2026 |
| Vendor Ledgers | ✅ | `Vendor ledgers.xlsx` | 2,405 | Dec 2018 – Jun 2026 |
| Vendor Transaction History | ✅ | `Vendor transaction history.xlsx` | 3,988 | Dec 2018 – Jun 2026 |
| Vendor Management Detail (open invoices, due dates, net to pay) | ✅ | `Open AP invoices.xlsx` | 1,219 | |
| Items Purchased from Vendors | ✅ | `Items purchased from vendors.xlsx` | 850 | |
| Vendor Master File List | ✅ | `Vendor Master List.xlsx` | 52 | |
| **Cash Disbursements Journal** | ❌ | none | | See Gaps |
| Purchase Order Journal | ❌ | `Purchase order journal.xlsx` is misnamed; it contains the vendor list | | |
| Purchase Order Register | ❌ | none | | |
| Purchase Order Report | ❌ | none | | |
| Check Register | ❌ | none | | |
| Cash Requirements | ❌ | none | | Upcoming supplier payments due |
| 1099 reports | n/a | | | US tax forms, not relevant in Nigeria |

## 5. Inventory (`sage-exports/Inventory/`)

| Sage report | Held | File | Rows | Covers |
|---|---|---|---|---|
| Inventory Valuation Report | ✅ | `Inventory Valuation report.xlsx` | 793 | |
| Inventory Stock Status Report | ✅ | `Inventiry Stock Status report.xlsx` | 792 | |
| Inventory Unit Activity Report (opening, sold, purchased, adjusted, closing) | ✅ | `Inventory unit Activity Report.xlsx` | 793 | This is the report the accountant used in the meeting (Rotarix: 84 opening, +100, −103, 81 closing) |
| Item Costing Report | ✅ | `Item costing report.xlsx` | 79,663 | Dec 2018 – Jun 2026 |
| Cost of Goods Sold Journal | ✅ | `Cost of goods sold journal.xlsx` | 152,206 | Jan 2019 – Jun 2026 |
| Item Master List | ✅ | `Item Master list.xlsx` | 792 | |
| Item Price List | ✅ | `Item Price list.xlsx` | 792 | |
| Buyer Report | ✅ | `Buyers report.xlsx` | 791 | |
| **Inventory Adjustment Journal** | ❌ | none | | See Gaps |
| Inventory Profitability Report | ❌ | none | | Margin per item |
| Inventory Reorder Worksheet | ❌ | none | | |
| Physical Inventory List | ❌ | none | | Stock-count sheet |
| Item List | ❌ | none | | Covered by Item Master List |
| Serial Number History / Status | ❌ | none | | Only one serialized item ("ABC") |
| Assemblies Adjustment Journal | ❌ | none | | Assemblies not used |
| Assemblies List | ❌ | none | | Assemblies not used |
| Component Lists | ❌ | none | | Assemblies not used |
| Bill of Materials / Work Ticket reports | ❌ | none | | Not used |

## 6. Account Reconciliation (`sage-exports/Account reconciliation/`): complete

| Sage report | Held | File | Rows | Covers |
|---|---|---|---|---|
| Account Reconciliation | ✅ | `Account reconciliation.xlsx` | 29,925 | to Jun 2026 |
| Account Register | ✅ | `Accounts register.xlsx` | 6,131 | Jan 2025 – Jun 2026 |
| Bank Deposit Report | ✅ | `Bank Deposit Report.xlsx` | 18,896 | Jan 2019 – Jun 2026 |
| Deposits in Transit | ✅ | `Deposits in Transit.xlsx` | 18,895 | Jan 2019 – Jun 2026 |
| Outstanding Checks | ✅ | `Outstanding Checks.xlsx` | 2,897 | Jan 2019 – Jun 2026 |
| Other Outstanding Items | ✅ | `Other Outstanding Items.xlsx` | 8,086 | Dec 2018 – Apr 2026 |

## 7. Payroll ⚪ (not run in Sage)
Current Earnings, Employee List, Exception Report, Payroll Check Register, Payroll Journal, Payroll Register, Payroll Tax Report, Quarterly Earnings, Yearly Earnings and Tax Liability are all ❌. The client's Sage employee file (`EMPLOYEE.DAT`) is empty, so there is nothing to export. HR/payroll data enters ACE separately, through the Import tab's HR import.

## 8. Jobs ⚪ (not used)
Job Ledger, Job List, Job Master File List, Job Profitability, Job Register and Job Estimates are all ❌. The client's project file is empty.

## 9. Time/Expense ⚪ (not used)
Time Ticket Register, Expense Ticket Register, Ticket Listing and Payroll Time Sheet are all ❌.

## 10. Company
| Sage report | Held | Notes |
|---|---|---|
| **Audit Trail Report** | ❌ | Who changed what, and when. Auditors ask for it (see Gaps) |
| Action Items / Event Log | ❌ | Reminders; not needed |
| Transaction History (company-wide) | ❌ | Partly covered by the GL and the journals |

---

## Gaps worth closing (ask the accountant to export these)

These are the missing reports that matter for replicating the books. Same method as before: *Reports & Forms → area → report → Excel*, for the same period.

1. **Accounts Payable → Cash Disbursements Journal.** Every supplier payment by GL line. We hold AP bills (Purchase Journal) but not the payments against them. Without it, ACE can't rebuild the AP side of the cash book or reconcile the Aged Payables.
2. **Inventory → Inventory Adjustment Journal.** Past write-offs, expiries and count corrections. It also serves as the real sample row we're missing for `ADJUST.CSV`.
3. **Company → Audit Trail Report.** The accountant noted that FRS audits need the ledger; auditors also expect an audit trail. ACE needs Sage's to replicate it.
4. **General Ledger → Working Trial Balance**, and **Financial Statements → Statement of Changes in Financial Position / Income-Earnings**. Useful for the full financial-statement set; lower priority.
5. **Purchase Order Journal / Register.** Only if the client raises POs in Sage. The file currently named `Purchase order journal.xlsx` is actually the vendor list.

Everything else Sage offers is either held already or belongs to a module the client doesn't use (payroll, jobs, time/expense, sales orders/quotes, assemblies).
