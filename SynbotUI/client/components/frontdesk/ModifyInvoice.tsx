/**
 * Modify an invoice before Finance approves it: add, remove or change items, the delivery charge or the
 * discount; the total is worked out again (the customer's invoice goes up or down) and, if QC had already
 * checked it, it goes back to QC. Approved invoices are ACE Books invoices - modified there with
 * Add items / Return / remove items, which posts the change to the customer's account.
 */
import { useEffect, useRef, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { api } from "@/lib/api-client";

type Row = { product: string; sku?: string; quantity: number; unit_price: number; batch_number?: string; manufacture_date?: string; expiry_date?: string };
const fmt = (n: number) => `₦${Number(n || 0).toLocaleString("en-NG", { minimumFractionDigits: 2 })}`;

export function ModifyInvoiceSheet({ invoice, open, onClose }: { invoice: any; open: boolean; onClose: (changed?: boolean) => void }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [delivery, setDelivery] = useState(0);
  const [discount, setDiscount] = useState(0);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [sug, setSug] = useState<{ idx: number; results: any[] } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!open || !invoice) return;
    setRows((invoice.items ?? []).map((it: any) => ({ product: it.product, sku: it.sku, quantity: Number(it.quantity), unit_price: Number(it.unit_price),
      batch_number: it.batch_number ?? undefined, manufacture_date: it.manufacture_date ?? undefined, expiry_date: it.expiry_date ?? undefined })));
    setDelivery(Number(invoice.delivery_charge ?? 0)); setDiscount(Number(invoice.discount_amount ?? 0)); setReason("");
  }, [open, invoice?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (i: number, p: Partial<Row>) => setRows((rs) => rs.map((r, k) => (k === i ? { ...r, ...p } : r)));
  const search = (i: number, v: string) => {
    set(i, { product: v, sku: undefined });
    if (timer.current) clearTimeout(timer.current);
    if (v.trim().length < 2) { setSug(null); return; }
    timer.current = setTimeout(() => api.inventory.search(v.trim()).then((r: any) => setSug({ idx: i, results: (r ?? []).slice(0, 8) })).catch(() => setSug(null)), 300);
  };
  const goods = rows.reduce((s, r) => s + r.quantity * r.unit_price, 0);
  const before = Number(invoice?.total_amount ?? 0) - Number(invoice?.discount_amount ?? 0) + Number(invoice?.delivery_charge ?? 0);
  const after = goods - Math.min(discount, goods) + delivery;
  const ready = reason.trim().length >= 3 && rows.length > 0 && rows.every((r) => r.product.trim() && r.quantity > 0 && r.unit_price >= 0);
  const save = async () => {
    setBusy(true);
    try {
      const r = await api.frontdesk.modifyInvoice(invoice.id, { items: rows, delivery_charge: delivery, discount_amount: discount, reason });
      toast.success(`Invoice ${invoice.invoice_number} modified: ${fmt(before)} → ${fmt(after)}${r?.back_to_qc ? " - back with QC to check the change" : ""}`);
      onClose(true);
    } catch (e) { toast.error((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <DetailSheet open={open} onOpenChange={(o) => !o && onClose()} title={`Modify invoice ${invoice?.invoice_number ?? ""}`}
                 description="Add, remove or change items, the delivery charge or the discount. The invoice total is worked out again; if QC already checked it, it goes back to QC."
                 footer={<div className="flex w-full items-center justify-between gap-2">
                   <span className="text-sm">{fmt(before)} → <strong>{fmt(after)}</strong></span>
                   <Button disabled={busy || !ready} onClick={save}>{busy ? "Saving…" : "Save changes"}</Button></div>}>
      <div className="space-y-3">
        <div className="text-xs font-semibold text-muted-foreground">ITEMS</div>
        {rows.map((r, i) => (
          <div key={i} className="space-y-1 rounded-lg border p-2">
            <div className="grid grid-cols-[1fr_80px_120px_36px] gap-2 text-[11px] font-medium text-muted-foreground"><span>Product (item)</span><span>Qty</span><span>Unit price (₦)</span><span /></div>
            <div className="grid grid-cols-[1fr_80px_120px_36px] items-start gap-2">
              <div className="relative">
                <Input value={r.product} onChange={(e) => search(i, e.target.value)} onBlur={() => setTimeout(() => setSug((s) => (s?.idx === i ? null : s)), 150)} />
                {sug?.idx === i && sug.results.length > 0 && (
                  <ul className="absolute z-50 mt-1 max-h-56 w-80 overflow-auto rounded border bg-popover text-sm shadow">
                    {sug.results.map((x: any) => (
                      <li key={x.sku ?? x.name} className="cursor-pointer px-2 py-1 hover:bg-accent" onMouseDown={(e) => { e.preventDefault();
                        set(i, { product: x.name, sku: x.sku, unit_price: x.selling_price ?? r.unit_price, batch_number: x.batch_number ?? undefined,
                                 manufacture_date: x.manufacture_date ?? undefined, expiry_date: x.expiry_date ?? undefined }); setSug(null); }}>
                        <div className="font-medium">{x.name}</div><div className="font-mono text-[11px] text-muted-foreground">{x.sku} · stock {x.current_stock ?? "—"}</div>
                      </li>))}
                  </ul>)}
              </div>
              <Input type="number" min={1} value={r.quantity} onChange={(e) => set(i, { quantity: Number(e.target.value) || 0 })} />
              <Input type="number" min={0} value={r.unit_price} onChange={(e) => set(i, { unit_price: Number(e.target.value) || 0 })} />
              <Button size="icon" variant="ghost" aria-label="Remove item" onClick={() => setRows((rs) => rs.filter((_, k) => k !== i))}><Trash2 className="h-4 w-4" /></Button>
            </div>
            <div className="text-right text-xs text-muted-foreground">{fmt(r.quantity * r.unit_price)}</div>
          </div>
        ))}
        <Button size="sm" variant="outline" onClick={() => setRows((rs) => [...rs, { product: "", quantity: 1, unit_price: 0 }])}><Plus className="mr-1 h-4 w-4" />Add item</Button>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1"><Label className="text-xs">Delivery charge (₦)</Label><Input type="number" min={0} value={delivery || ""} onChange={(e) => setDelivery(Number(e.target.value) || 0)} /></div>
          <div className="space-y-1"><Label className="text-xs">Discount allowed (₦)</Label><Input type="number" min={0} value={discount || ""} onChange={(e) => setDiscount(Number(e.target.value) || 0)} /></div>
        </div>
        <div className="space-y-1"><Label className="text-xs">Why (kept in the history)</Label><Input placeholder="e.g. customer no longer wants the Hep B; added 2 Typhim" value={reason} onChange={(e) => setReason(e.target.value)} /></div>
      </div>
    </DetailSheet>
  );
}

/** "Modify invoice" anywhere an invoice is raised or worked on (walk-in QC / Finance steps, the "Invoice raised" view). */
export function ModifyInvoiceButton({ invoiceId, onChanged, className = "" }: { invoiceId: string; onChanged?: () => void; className?: string }) {
  const [inv, setInv] = useState<any>(null);
  const [open, setOpen] = useState(false);
  const load = async () => {
    try { const d = await api.frontdesk.getInvoice(invoiceId); setInv(d?.invoice ?? null); setOpen(true); }
    catch (e) { toast.error((e as Error).message); }
  };
  const approved = inv && ["finance_approved", "dispatched", "completed"].includes(inv.status);
  return (
    <>
      <Button size="sm" variant="outline" className={className} onClick={load}>Modify invoice</Button>
      {inv && !approved && <ModifyInvoiceSheet invoice={inv} open={open} onClose={(c) => { setOpen(false); if (c) onChanged?.(); }} />}
      {inv && approved && open && (
        <DetailSheet open onOpenChange={(o) => !o && setOpen(false)} title={`Modify invoice ${inv.invoice_number}`}
                     description="This invoice is approved and posted in ACE Books.">
          <p className="text-sm">Finance modifies it in ACE Books: <strong>Sales & Receivables → Invoice register → {inv.invoice_number} → Modify this invoice: Add items / Return / remove items</strong>. The customer's balance and the books follow.</p>
          {inv.ace_invoice_id && <Button asChild className="mt-3"><a href={`#/finance/books/sales?tab=register&invoice=${inv.ace_invoice_id}`}>Open it in ACE Books</a></Button>}
        </DetailSheet>
      )}
    </>
  );
}

