import { Loader2 } from "lucide-react";

/**
 * Read-only invoice detail — customer/shipping context + itemized line
 * items (product, batch, expiry, price). Extracted because the QC and
 * Finance approval queues (QualityControl.tsx, ARReceipts.tsx) were
 * rendering InvoiceActionPanel directly off the summary-list row (id,
 * customer_name, total_amount only — no items), so QC staff had no way to
 * see what they were actually approving without leaving the page. Frontdesk
 * InvoicesTab and CustomerWorkspace already fetch full invoice detail and
 * render items inline themselves; this generalizes that same rendering so
 * it isn't written a third and fourth time.
 */

const fmt = (n: number | null | undefined) =>
  typeof n === "number"
    ? `₦${n.toLocaleString("en-NG", { minimumFractionDigits: 2 })}`
    : "—";

const fmtMonthYear = (ym?: string | null) => {
  if (!ym) return "—";
  const [y, m] = ym.split("-");
  if (!y || !m) return ym;
  return new Date(Number(y), Number(m) - 1, 1).toLocaleDateString("en-NG", { month: "short", year: "numeric" });
};

const fmtDateOnly = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleDateString("en-NG", { day: "2-digit", month: "short", year: "numeric" }) : "—";

export interface DetailInvoiceItem {
  product: string;
  quantity: number;
  unit_price: number;
  line_total?: number;
  batch_number?: string;
  manufacture_date?: string;
  expiry_date?: string;
}

export interface DetailInvoice {
  invoice_number?: string;
  customer_name: string;
  company_name?: string;
  items: DetailInvoiceItem[];
  total_amount: number;
  payment_method?: string;
  billing_address?: string;
  shipping_address?: string;
  customer_po?: string;
  payment_terms?: string;
  shipping_method?: string;
  notes?: string;
}

export function InvoiceDetailBody({ invoice, loading }: { invoice: DetailInvoice | null | undefined; loading?: boolean }) {
  if (loading) {
    return (
      <div className="flex justify-center py-4">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (!invoice) return null;

  return (
    <div className="space-y-3 text-sm">
      <div>
        <div className="font-semibold">{invoice.customer_name}</div>
        {invoice.company_name && <div className="text-xs text-muted-foreground">{invoice.company_name}</div>}
      </div>

      {(invoice.billing_address || invoice.shipping_address || invoice.customer_po || invoice.payment_terms || invoice.shipping_method) && (
        <div className="grid grid-cols-2 gap-2 text-xs">
          {invoice.billing_address && (
            <div>
              <div className="text-muted-foreground">Bill To</div>
              <div className="whitespace-pre-line">{invoice.billing_address}</div>
            </div>
          )}
          {invoice.shipping_address && (
            <div>
              <div className="text-muted-foreground">Ship To</div>
              <div className="whitespace-pre-line">{invoice.shipping_address}</div>
            </div>
          )}
          {invoice.customer_po && (
            <div>
              <div className="text-muted-foreground">Customer PO</div>
              <div>{invoice.customer_po}</div>
            </div>
          )}
          {invoice.payment_terms && (
            <div>
              <div className="text-muted-foreground">Payment Terms</div>
              <div>{invoice.payment_terms}</div>
            </div>
          )}
          {invoice.shipping_method && (
            <div>
              <div className="text-muted-foreground">Shipping Method</div>
              <div>{invoice.shipping_method}</div>
            </div>
          )}
        </div>
      )}

      <div>
        <div className="text-xs font-semibold text-muted-foreground mb-1">ITEMS</div>
        <div className="space-y-1.5">
          {(invoice.items || []).map((it, i) => (
            <div key={i} className="rounded border bg-muted/20 px-3 py-2 text-xs space-y-1">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{it.product} × {it.quantity}</span>
                <span className="font-semibold flex-shrink-0">{fmt(it.line_total ?? it.quantity * it.unit_price)}</span>
              </div>
              {(it.batch_number || it.manufacture_date || it.expiry_date) && (
                <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-muted-foreground">
                  <span>Batch: <span className="font-mono">{it.batch_number || "—"}</span></span>
                  <span>Mfg: {fmtMonthYear(it.manufacture_date)}</span>
                  <span className={it.expiry_date && new Date(it.expiry_date) < new Date() ? "text-red-600 font-medium dark:text-red-300" : undefined}>
                    Exp: {fmtDateOnly(it.expiry_date)}
                  </span>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {invoice.notes && (
        <div>
          <div className="text-xs text-muted-foreground">Notes</div>
          <div className="text-xs">{invoice.notes}</div>
        </div>
      )}

      <div className="flex items-center justify-between border-t pt-2">
        <span className="text-xs text-muted-foreground">{invoice.payment_method ? `Payment: ${invoice.payment_method}` : ""}</span>
        <span className="font-bold">{fmt(invoice.total_amount)}</span>
      </div>
    </div>
  );
}
