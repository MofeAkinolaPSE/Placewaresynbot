/**
 * A Frontdesk invoice opened from anywhere - ACE Books' Invoice register, the customer's account, a report:
 * what was ordered, where it is in QC -> Finance -> dispatch, and the actions the viewer's role allows
 * (Void, Print, QC, Finance approval). It posts to ACE Books when Finance approves it.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api-client";
import { InvoiceActionPanel } from "@/components/workspace/InvoiceActionPanel";

const fmt = (n: number) => `₦${Number(n || 0).toLocaleString("en-NG", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const STAGE: Record<string, string> = {
  draft: "Awaiting QC", qc_pending: "Awaiting QC", qc_failed: "Failed QC", qc_passed: "Awaiting Finance", finance_pending: "Awaiting Finance",
  finance_rejected: "Rejected by Finance", finance_approved: "Approved", dispatched: "Dispatched", completed: "Completed", cancelled: "Voided",
};

export function FrontdeskInvoiceBody({ id }: { id: string }) {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ["fd-invoice-detail", id], queryFn: () => api.frontdesk.getInvoice(id) });
  if (isLoading) return <div className="flex items-center gap-2 p-4 text-sm"><Loader2 className="h-4 w-4 animate-spin" />Loading…</div>;
  if (error || !data?.invoice) return <p className="p-4 text-sm text-red-600">{(error as any)?.message ?? "Invoice not found"}</p>;
  const inv = data.invoice;
  const items: any[] = inv.items ?? [];
  const discount = Number(inv.discount_amount ?? 0), delivery = Number(inv.delivery_charge ?? 0), tax = Number(inv.tax_amount ?? 0);
  const total = Number(inv.total_amount) - discount + delivery + tax;
  const posted = ["finance_approved", "dispatched", "completed"].includes(inv.status);
  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-sky-100 px-2 py-0.5 text-[11px] font-medium text-sky-800 dark:bg-sky-500/15 dark:text-sky-300">{STAGE[inv.status] ?? inv.status}</span>
        <span className="font-mono text-base font-semibold">{inv.invoice_number}</span>
        <span className="text-xs text-muted-foreground">raised on Frontdesk · {new Date(inv.created_at).toLocaleDateString("en-GB")}</span>
      </div>
      <p className="rounded-md border bg-muted/30 p-2 text-xs">
        {inv.status === "cancelled" ? "This invoice was voided; it is not in the books."
          : posted ? <>Approved by Finance. If it is not in ACE Books yet, see <Link className="underline" to="/finance/books/close?tab=frontdesk">Close & Controls → Frontdesk postings</Link> for the reason and Retry.</>
          : "Raised on Frontdesk and waiting for QC and Finance. It posts to ACE Books (customer owes, stock leaves) when Finance approves it; until then its stock is held for it."}
      </p>
      <div className="grid grid-cols-2 gap-2 rounded-lg border p-3">
        <div><div className="text-[11px] uppercase text-muted-foreground">Customer</div>{inv.company_name || inv.customer_name}</div>
        <div><div className="text-[11px] uppercase text-muted-foreground">Payment</div><span className="capitalize">{inv.payment_method}</span> · {inv.payment_terms}</div>
      </div>
      <table className="w-full border-collapse text-xs">
        <thead><tr className="border-b text-left text-muted-foreground"><th className="py-1">Item</th><th className="text-right">Qty</th><th className="text-right">Price</th><th className="text-right">Amount</th></tr></thead>
        <tbody>{items.map((it, i) => (
          <tr key={i} className="border-b"><td className="py-1">{it.product}{(it.pack_batch_number || it.batch_number) && <div className="text-muted-foreground">batch {it.pack_batch_number || it.batch_number}</div>}</td>
            <td className="text-right">{it.quantity}</td><td className="text-right">{fmt(it.unit_price)}</td><td className="text-right">{fmt(it.line_total ?? it.quantity * it.unit_price)}</td></tr>))}
        </tbody>
      </table>
      <div className="ml-auto w-64 space-y-0.5 text-xs">
        <div className="flex justify-between"><span>Goods</span><span>{fmt(inv.total_amount)}</span></div>
        {discount > 0 && <div className="flex justify-between"><span>Discount allowed</span><span>−{fmt(discount)}</span></div>}
        {delivery > 0 && <div className="flex justify-between"><span>Delivery charge</span><span>{fmt(delivery)}</span></div>}
        {tax > 0 && <div className="flex justify-between"><span>Sales tax</span><span>{fmt(tax)}</span></div>}
        <div className="flex justify-between border-t pt-1 font-semibold"><span>Total</span><span>{fmt(total)}</span></div>
      </div>
      <InvoiceActionPanel invoice={inv} onActioned={() => { qc.invalidateQueries({ queryKey: ["fd-invoice-detail", id] }); qc.invalidateQueries({ queryKey: ["books"] }); }} />
    </div>
  );
}
