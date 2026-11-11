/**
 * What a Frontdesk invoice bills the customer: goods - discount + delivery charge + tax.
 *
 * `total_amount` on a Frontdesk invoice is the GOODS only. Screens that showed it as "the total" showed an
 * invoice with a delivery charge short by that charge (the client's 6 Nov meeting: raised for N95,000,
 * shown lower at QC). The server now sends `grand_total`, worked out by the database (migration 148).
 * Use this everywhere a Frontdesk invoice's total is shown - never `total_amount` on its own.
 */
export function invoiceTotal(inv: any): number {
  if (!inv) return 0;
  if (inv.grand_total != null && inv.grand_total !== "") return Number(inv.grand_total);
  return Number(inv.total_amount ?? 0) - Number(inv.discount_amount ?? 0)
    + Number(inv.delivery_charge ?? 0) + Number(inv.tax_amount ?? 0);
}
