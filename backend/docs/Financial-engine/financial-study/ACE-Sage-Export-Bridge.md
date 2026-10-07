# ACE → Sage 50 Export Bridge

**Where:** Finance → Sage Import / Export → **Export to Sage** tab (`/finance/sage-import`).

## Why journals and not a GL or balance sheet
Sage 50 2013 cannot import a general ledger, balance sheet or P&L; it derives them. As the accountant said in the meeting (`linksage.md`), once a transaction goes in through a sales invoice or receipt, "it will go to ledger by itself, it will go to P&L by itself."

So ACE exports **transaction journals** in the exact layout of the client's own Sage Import/Export templates (`export-templates/`). Sage then posts everything else itself.

## What is exported (v1)
| File | Sage template | ACE source | What it updates in Sage |
|---|---|---|---|
| `CUSTOMER.CSV` | AR → Customer List | CRM customers on exported invoices that are not yet in Sage | Customer master |
| `SALES.CSV` | AR → Sales Journal | `frontdesk_invoices` with status `finance_approved`, `dispatched` or `completed` | AR, revenue, **COGS and stock qty** (each line carries the Item ID; Sage uses the item's own Sales/Inventory/COGS accounts) |
| `RECEIPTS.CSV` | AR → Cash Receipts Journal | `ar_receipts` (posted) + `ar_receipt_applications` | Bank/cash, AR, invoice paid status |
| `ADJUST.CSV` | Inventory → Adjustments Journal | `placeware_inventory_events` of type `DAMAGE`, `EXPIRY` or `ADJUSTMENT` | Stock qty, write-off account |

**Not exported:**
- **Purchases and supplier payments.** These stay in Sage for now, because ACE has no goods-received data (vendor, cost, received quantity).
- **SALE inventory events.** Sage already reduces stock when it posts the Sales Journal, so exporting these too would take the stock out twice.

## How the Export tab works
- **Document cards.** There is one card per Sage template, numbered in Sage import order (Customer List, then Sales, then Receipts, then Adjustments). Purchases and Payments appear as locked "In Sage" cards.
- **Per card.** Each card shows:
  - the number of records ready, and their naira total
  - the number held back, with reasons
  - the column count
  - when the document was last exported
  - an **Export** button, with a line of text explaining why it is disabled when it is
- **Export.** Each document is exported on its own, under Sage's own default file name (`SALES.CSV` etc.).
  - **Chrome/Edge:** a save dialog opens in **Documents** with the file name already filled in, and remembers the folder chosen. A browser cannot save to a folder without asking the user.
  - **Other browsers:** the file downloads normally.
- **Customer List first.** Sales cannot be exported until the Customer List has been exported for any new customers on those invoices. Otherwise Sage would reject the invoices.
- **View.** This opens three tabs:
  - **Data preview:** the real rows, showing only the columns ACE fills.
  - **Columns:** a copy of Sage's *Fields* tab. Columns Sage requires are locked. The chosen layout is saved on the server (`sage_export_settings.column_selection`, migration 114). Sage reads columns by position, so any field unticked here must also be unticked in Sage's import template.
  - **Held back:** the records left out, with how to fix them.
- **Periods.** "Not yet exported" (from the cut-over date to today) is the default, with This week, Last week, This month and Custom as alternatives. Nothing is ever exported twice, whichever period is chosen.
- **Exported files.** A list of past exports. Each can be saved again, or undone (only if Sage did not import it).

## Safety rules
- **Whole record or nothing.** An invoice or receipt with any unmappable part is *held back* and listed with a fix. Nothing is exported half-done. Records are held back for:
  - no Sage customer
  - an unknown Item ID
  - VAT (the client posts no VAT through Sage sales; see `SALES.CSV`)
  - line totals that don't match the invoice total
  - a receipt that isn't fully applied to invoices
  - no write-off account set
- **Exported once.** `sage_export_items` has `UNIQUE(doc_type, source_id)`. Deleting a batch releases its records; do that **only** if Sage did not import the batch.
- **Cut-over date.** Nothing dated before it is exported, and generating a batch requires it to be set.
- **Needs reversal.** Anything exported and then cancelled or voided in ACE is listed for the accountant to void in Sage by hand.

## Setup (one-off)
1. Import `export-templates/ITEM.CSV` on the Import tab as **Item GL Accounts**. This fills `sage_item_accounts` with each item's Sales, Inventory and COGS accounts. Re-import it whenever the accountant adds items in Sage.
2. In **Export settings**:
   - Set the **cut-over date**.
   - Set the **stock write-off account**; ask the accountant which one.
   - Check the payment-method → cash-account mapping. Defaults: cash → 10100, everything else → 10290 Fidelity.

## Code
- **Migration:** `backend/migrations/113_sage_export.sql`
- **Template layouts:** `backend/src/services/sage_export/_generated_layouts.py`. This is generated from `export-templates/`; don't hand-edit it.
- **Builders (pure, unit-tested):** `backend/src/services/sage_export/builders.py`. Tests are in `backend/tests/test_sage_export_builders.py`.
- **Service:** `backend/src/services/sage_export/service.py`. `plan()` does the preview; `generate()` runs the export under an advisory lock.
- **Router:** `backend/src/routers/sage_export.py` (`/sage/export/*`, finance roles).
- **UI:** `SynbotUI/client/components/sage/SageExportPanel.tsx`

## Still to confirm on a test import (on a copy of the Sage company)
- **Adjustments sign convention.** `ADJUST.CSV` had no sample rows. We export a negative Quantity and Amount for stock going out.
- **Cost of Sales Amount.** Sage may recompute it from average cost instead of using ACE's Qty × Last Unit Cost figure.
- **Transaction Period.** It is derived from the June 2026 = 34 anchor. It can be changed in `sage_export_settings` if the fiscal year rolls.
