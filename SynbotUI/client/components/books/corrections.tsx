/**
 * Correcting posted documents without editing posted history (client, 9 Oct):
 *  - AddItems: a posted invoice takes more items (same number; the addition is its own journal).
 *  - CorrectReceipt / CorrectVoucher: the wrong one is voided and the right one posted in one step,
 *    each pointing at the other. The form starts from what was posted, so only the mistake is changed.
 */
import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { books, Dict, fmtDate, naira, today } from "@/lib/books-api";
import { AccountPick, act, Amount, BankSelect, BatchPick, CustomerPick, DrillLink, ProductPick, r2, useBooks, WhtPicker } from "./kit";

const box = "space-y-2 rounded-md border border-sky-300 bg-sky-50 p-3 text-xs dark:bg-sky-500/10";

type ItemLine = { kind: "ITEM" | "CHARGE" | "DISCOUNT"; product: Dict | null; batch: Dict | null; quantity: string; unit_price: string; description: string };
const blank = (kind: ItemLine["kind"] = "ITEM"): ItemLine => ({
  kind, product: null, batch: null, quantity: kind === "ITEM" ? "" : "1", unit_price: "",
  description: kind === "CHARGE" ? "Delivery charge" : kind === "DISCOUNT" ? "Discount allowed" : "" });
const lineValue = (l: ItemLine) => (l.kind === "ITEM" ? (l.product ? Number(l.quantity || 0) * Number(l.unit_price || 0) : 0)
  : l.kind === "CHARGE" ? Number(l.unit_price || 0) : -Number(l.unit_price || 0));

export function AddItems({ inv }: { inv: Dict }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [lines, setLines] = useState<ItemLine[]>([blank()]);
  const [reason, setReason] = useState("Customer added to the order");
  const [date, setDate] = useState(today());
  const [busy, setBusy] = useState(false);
  const set = (i: number, p: Partial<ItemLine>) => setLines((xs) => xs.map((x, k) => (k === i ? { ...x, ...p } : x)));
  const total = lines.reduce((s, l) => s + lineValue(l), 0);
  const ready = reason.trim() && total > 0
    && lines.every((l) => (l.kind === "ITEM" ? !l.product || (Number(l.quantity) > 0 && Number(l.unit_price) >= 0) : Number(l.unit_price || 0) >= 0))
    && lines.some((l) => (l.kind === "ITEM" ? l.product && Number(l.quantity) > 0 : l.kind === "CHARGE" && Number(l.unit_price) > 0));
  const save = async () => {
    setBusy(true);
    const r = await act(() => books.post(`/sales/invoices/${inv.id}/amend`, {
      reason, amend_date: date,
      lines: lines.filter((l) => (l.kind === "ITEM" ? l.product && Number(l.quantity) > 0 : Number(l.unit_price) > 0)).map((l) => (l.kind === "ITEM"
        ? { line_type: "ITEM", sku: l.product!.sku, batch_id: l.batch?.id || undefined, quantity: Number(l.quantity), unit_price: Number(l.unit_price || 0) }
        : { line_type: l.kind, description: l.description.trim() || (l.kind === "CHARGE" ? "Delivery charge" : "Discount allowed"), quantity: 1,
            unit_price: Number(l.unit_price), charge_kind: l.kind === "CHARGE" && /deliver/i.test(l.description) ? "DELIVERY" : undefined })),
    }), `Items added to ${inv.invoice_number} - the invoice, the customer's balance and the books are updated`);
    setBusy(false);
    if (r) { setOpen(false); setLines([blank()]); qc.invalidateQueries({ queryKey: ["books"] }); }
  };
  if (!open) return <Button size="sm" variant="outline" onClick={() => setOpen(true)}><Plus className="mr-1 h-3.5 w-3.5" />Add items</Button>;
  return (
    <div className={box}>
      <div className="font-semibold">Add items to {inv.invoice_number}</div>
      <p className="text-muted-foreground">The invoice keeps its number. The added items are posted as their own entry on it: the customer owes more, the stock leaves its batch, revenue and cost of sales are booked. A delivery charge goes to Other Income; a discount on the added items goes to Sales Discount.</p>
      {lines.map((l, i) => l.kind !== "ITEM" ? (
        <div key={i} className="grid items-end gap-2 md:grid-cols-[1.4fr_1fr_210px_32px]">
          <div>{i === 0 && <Label className="text-xs">Line</Label>}<div className="flex h-9 items-center rounded-md border px-2 text-xs font-medium">{l.kind === "CHARGE" ? "Delivery charge (other income)" : "Discount allowed"}</div></div>
          <div><Label className="text-xs">Description</Label><Input className="h-9" value={l.description} onChange={(e) => set(i, { description: e.target.value })} /></div>
          <div><Label className="text-xs">{l.kind === "CHARGE" ? "Amount (₦)" : "Discount (₦)"}</Label><Input className="h-9" type="number" min={0} value={l.unit_price} onChange={(e) => set(i, { unit_price: e.target.value })} /></div>
          <Button size="icon" variant="ghost" aria-label="Remove line" onClick={() => setLines((xs) => (xs.length > 1 ? xs.filter((_, k) => k !== i) : [blank()]))}><Trash2 className="h-4 w-4" /></Button>
        </div>
      ) : (
        <div key={i} className="grid items-end gap-2 md:grid-cols-[1.4fr_1fr_90px_120px_32px]">
          <ProductPick label={i === 0 ? "Product" : undefined} value={l.product} onChange={(p) => set(i, { product: p, batch: null, unit_price: l.unit_price || String(p?.unit_price ?? p?.selling_price ?? "") })} />
          <BatchPick label={i === 0 ? "Batch (FIFO if blank)" : undefined} value={l.batch} onChange={(b) => set(i, { batch: b })} />
          <div>{i === 0 && <Label className="text-xs">Qty</Label>}<Input className="h-9" type="number" value={l.quantity} onChange={(e) => set(i, { quantity: e.target.value })} /></div>
          <div>{i === 0 && <Label className="text-xs">Unit price</Label>}<Input className="h-9" type="number" value={l.unit_price} onChange={(e) => set(i, { unit_price: e.target.value })} /></div>
          <Button size="icon" variant="ghost" onClick={() => setLines((xs) => (xs.length > 1 ? xs.filter((_, k) => k !== i) : [blank()]))}><Trash2 className="h-4 w-4" /></Button>
        </div>
      ))}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={() => setLines((xs) => [...xs, blank()])}><Plus className="mr-1 h-3.5 w-3.5" />Another item</Button>
        <Button size="sm" variant="outline" onClick={() => setLines((xs) => [...xs, blank("CHARGE")])}><Plus className="mr-1 h-3.5 w-3.5" />Delivery charge</Button>
        <Button size="sm" variant="outline" onClick={() => setLines((xs) => [...xs, blank("DISCOUNT")])}><Plus className="mr-1 h-3.5 w-3.5" />Discount allowed</Button>
      </div>
      <div className="grid gap-2 md:grid-cols-[1fr_160px]">
        <div><Label className="text-xs">Why</Label><Input className="h-8" value={reason} onChange={(e) => setReason(e.target.value)} /></div>
        <div><Label className="text-xs">Date of the addition</Label><Input className="h-8" type="date" value={date} onChange={(e) => setDate(e.target.value)} /></div>
      </div>
      <div className="flex items-center justify-end gap-2">
        <span>Invoice {naira(inv.total)} → <strong>{naira(Number(inv.total) + total)}</strong></span>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
        <Button size="sm" disabled={busy || !ready} onClick={save}>{busy ? "Posting…" : `Add ${naira(total)}`}</Button>
      </div>
    </div>
  );
}

type RetLine = { qty: string };

/** Return or remove items from an invoice, or give a discount on it after posting: a credit note
 *  against this invoice. The invoice keeps its posted lines; the credit note reduces what the
 *  customer owes (or leaves them in credit if already paid) and, when ticked, puts the goods back
 *  into the batch they were sold from. */
export function ReturnItems({ inv }: { inv: Dict }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const items: Dict[] = (inv.lines ?? []).filter((l: Dict) => l.line_type === "ITEM");
  const returned: Record<string, number> = Object.fromEntries(Object.entries(inv.returned ?? {}).map(([k, v]) => [k, Number(v)]));
  // what is left to return per line: the item's returns are taken from its lines in order
  const left = useMemo(() => {
    const used: Record<string, number> = { ...returned };
    return items.map((l) => { const take = Math.min(Number(l.quantity), used[l.sku] ?? 0); used[l.sku] = (used[l.sku] ?? 0) - take; return Number(l.quantity) - take; });
  }, [inv.id, inv.returned]); // eslint-disable-line react-hooks/exhaustive-deps
  const [ret, setRet] = useState<Record<number, RetLine>>({});
  const [discount, setDiscount] = useState("");
  const [toStock, setToStock] = useState(true);
  const [reason, setReason] = useState("");
  const [date, setDate] = useState(today());
  const [busy, setBusy] = useState(false);
  const unit = (l: Dict) => (Number(l.quantity) ? Number(l.line_total) / Number(l.quantity) : Number(l.unit_price));
  const back = items.reduce((s, l, k) => s + r2(Number(ret[k]?.qty || 0) * unit(l)), 0);
  const credit = r2(back + Number(discount || 0));
  const bad = items.some((_, k) => Number(ret[k]?.qty || 0) < 0 || Number(ret[k]?.qty || 0) > left[k]);
  const ready = reason.trim() && credit > 0 && !bad && Number(discount || 0) >= 0;
  const balance = Number(inv.balance_due);
  const save = async () => {
    setBusy(true);
    const lines: Dict[] = items.flatMap((l, k) => (Number(ret[k]?.qty || 0) > 0 ? [{
      line_type: "ITEM", sku: l.sku, batch_id: l.batch_id || undefined, description: l.description,
      quantity: Number(ret[k].qty), unit_price: r2(unit(l)), unit_cost: l.unit_cost ?? undefined }] : []));
    if (Number(discount) > 0) lines.push({ line_type: "DISCOUNT", description: "Discount allowed", quantity: 1, unit_price: Number(discount) });
    const r = await act(() => books.post(`/sales/credit-notes`, {
      customer_id: inv.customer_id, invoice_id: inv.id, note_date: date, reason, return_to_stock: toStock && back > 0, lines,
    }), `Credit note posted against ${inv.invoice_number} - the customer's balance and the books are updated`);
    setBusy(false);
    if (r) { setOpen(false); setRet({}); setDiscount(""); setReason(""); qc.invalidateQueries({ queryKey: ["books"] }); }
  };
  if (!open) return <Button size="sm" variant="outline" onClick={() => setOpen(true)}>Return / remove items</Button>;
  return (
    <div className="space-y-2 rounded-md border border-rose-300 bg-rose-50 p-3 text-xs dark:bg-rose-500/10">
      <div className="font-semibold">Return / remove items on {inv.invoice_number}</div>
      <p className="text-muted-foreground">Enter how many of each item come back (or are taken off the order), and any discount given after invoicing. A credit note is posted against this invoice: what the customer owes goes down{balance <= 0 ? " - this invoice is already paid, so the credit stays on the customer's account to refund or use on their next invoice" : ""}.</p>
      {items.length > 0 && (
        <Table>
          <TableHeader><TableRow><TableHead>Item</TableHead><TableHead className="text-right">Sold</TableHead><TableHead className="text-right">Already returned</TableHead>
            <TableHead className="text-right">Unit price</TableHead><TableHead className="w-28">Return</TableHead><TableHead className="text-right">Credit</TableHead></TableRow></TableHeader>
          <TableBody>{items.map((l, k) => {
            const q = Number(ret[k]?.qty || 0);
            return (
              <TableRow key={l.id}>
                <TableCell><div>{l.description || l.sku}</div><div className="text-[11px] text-muted-foreground">{l.sku}</div></TableCell>
                <TableCell className="text-right">{Number(l.quantity)}</TableCell>
                <TableCell className="text-right">{Number(l.quantity) - left[k] || "—"}</TableCell>
                <TableCell className="text-right">{naira(unit(l))}</TableCell>
                <TableCell><Input className={`h-8 ${q > left[k] ? "border-red-500" : ""}`} type="number" min={0} max={left[k]} disabled={left[k] <= 0}
                                  aria-label={`Quantity of ${l.sku} to return`} placeholder={left[k] > 0 ? `max ${left[k]}` : "none left"}
                                  value={ret[k]?.qty ?? ""} onChange={(e) => setRet((x) => ({ ...x, [k]: { qty: e.target.value } }))} /></TableCell>
                <TableCell className="text-right">{q > 0 ? naira(r2(q * unit(l))) : ""}</TableCell>
              </TableRow>);
          })}</TableBody>
        </Table>)}
      <div className="grid gap-2 md:grid-cols-[180px_1fr_160px]">
        <div><Label className="text-xs">Discount allowed (₦)</Label><Input className="h-8" type="number" min={0} placeholder="0.00" value={discount} onChange={(e) => setDiscount(e.target.value)} /></div>
        <div><Label className="text-xs">Why</Label><Input className="h-8" placeholder="e.g. customer returned 2 vials - damaged in transit" value={reason} onChange={(e) => setReason(e.target.value)} /></div>
        <div><Label className="text-xs">Date</Label><Input className="h-8" type="date" value={date} onChange={(e) => setDate(e.target.value)} /></div>
      </div>
      {back > 0 && (
        <label className="flex items-center gap-2"><input type="checkbox" className="h-4 w-4" checked={toStock} onChange={(e) => setToStock(e.target.checked)} />
          The goods come back into stock (back into the batch they were sold from). Untick if they are being written off.</label>)}
      <div className="flex flex-wrap items-center justify-end gap-2">
        <span>Invoice {naira(inv.total)} · credit <strong>{naira(credit)}</strong> · customer then owes <strong>{naira(Math.max(0, balance - credit))}</strong> on it</span>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
        <Button size="sm" disabled={busy || !ready} onClick={save}>{busy ? "Posting…" : `Post credit ${naira(credit)}`}</Button>
      </div>
    </div>
  );
}

export function CreditNotesOn({ rows }: { rows?: Dict[] }) {
  if (!rows?.length) return null;
  return (
    <div className="space-y-1 text-xs">
      {rows.map((n) => (
        <div key={n.id} className="flex flex-wrap justify-between gap-2 rounded border px-2 py-1">
          <span><DrillLink to={{ type: "creditnote", id: n.id, label: n.credit_note_number }}>{n.credit_note_number}</DrillLink> {fmtDate(n.note_date)} · {n.reason}{n.return_to_stock ? " · back into stock" : ""}{n.status === "VOID" ? " · void" : ""}</span>
          <Amount value={n.total} />
        </div>
      ))}
    </div>
  );
}

export function Amendments({ rows }: { rows?: Dict[] }) {
  if (!rows?.length) return null;
  return (
    <div className="space-y-1 text-xs">
      {rows.map((a) => (
        <div key={a.id} className="flex flex-wrap justify-between gap-2 rounded border px-2 py-1">
          <span>Items added {fmtDate(a.amend_date)} (lines {a.line_from}{a.line_to !== a.line_from ? `–${a.line_to}` : ""}) · {a.reason}{a.reversed ? " · reversed by the void" : ""}</span>
          <span><Amount value={a.added_total} /> · {a.journal_number}</span>
        </div>
      ))}
    </div>
  );
}

export function CorrectReceipt({ r }: { r: Dict }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [customer, setCustomer] = useState<Dict | null>({ id: r.customer_id, name: r.customer_name });
  const [f, setF] = useState({ receipt_date: String(r.receipt_date).slice(0, 10), method: r.method ?? "TRANSFER", bank_account_id: r.bank_account_id ?? "",
    amount: String(Number(r.amount)), wht_amount: Number(r.wht_amount) ? String(Number(r.wht_amount)) : "", reference: r.reference ?? "" });
  const [reason, setReason] = useState("");
  const sameCustomer = String(customer?.id ?? "") === String(r.customer_id);
  const { data: items } = useBooks<Dict[]>(["openitems", customer?.id], "/receivables/open-items", { customer_id: customer?.id }, open && !!customer);
  // the invoices this receipt paid reopen when it is voided: offer them at what it applied
  const rows = useMemo(() => {
    const m: Record<string, Dict> = {};
    (items ?? []).filter((i) => i.doc_type === "INVOICE" && Number(i.open_amount) > 0).forEach((i) => { m[i.doc_id] = { ...i, open_amount: Number(i.open_amount) }; });
    if (sameCustomer) (r.allocations ?? []).filter((a: Dict) => !a.reversed).forEach((a: Dict) => {
      m[a.invoice_id] = { ...(m[a.invoice_id] ?? { doc_id: a.invoice_id, doc_number: a.invoice_number, open_amount: 0 }) };
      m[a.invoice_id].open_amount += Number(a.amount);
    });
    return Object.values(m).sort((a, b) => (String(a.doc_date ?? "") > String(b.doc_date ?? "") ? -1 : 1));
  }, [items, sameCustomer, r.allocations]);
  const [alloc, setAlloc] = useState<Record<string, string>>(() =>
    Object.fromEntries((r.allocations ?? []).filter((a: Dict) => !a.reversed).map((a: Dict) => [a.invoice_id, String(Number(a.amount))])));
  const applied = Object.values(alloc).reduce((s, v) => s + Number(v || 0), 0);
  const avail = Number(f.amount || 0) + Number(f.wht_amount || 0);
  const [whtRate, setWhtRate] = useState(Number(r.wht_amount) ? "custom" : "");
  const pickRate = (rate: string) => {
    setWhtRate(rate);
    if (rate && rate !== "custom") { const w = r2(applied * Number(rate)); setF((v) => ({ ...v, wht_amount: w.toFixed(2), amount: (applied - w).toFixed(2) })); }
    if (!rate) setF((v) => ({ ...v, wht_amount: "", amount: applied ? applied.toFixed(2) : v.amount }));
  };
  const save = async () => {
    const n = await act(() => books.post<Dict>(`/receivables/receipts/${r.id}/correct`, {
      ...f, wht_amount: f.wht_amount || undefined, reference: f.reference || undefined, customer_id: customer?.id, reason,
      allocations: Object.entries(alloc).filter(([, v]) => Number(v) > 0).map(([invoice_id, amount]) => ({ invoice_id, amount })),
    }), "Receipt corrected - the wrong one is voided and the right one posted");
    if (n) { setOpen(false); qc.invalidateQueries({ queryKey: ["books"] }); }
  };
  if (!open) return <Button size="sm" variant="outline" onClick={() => setOpen(true)}>Correct this receipt</Button>;
  return (
    <div className={box}>
      <div className="font-semibold">Correct receipt {r.receipt_number}</div>
      <p className="text-muted-foreground">Change what was wrong. {r.receipt_number} is voided (its entry reversed, the invoices it paid reopened) and the corrected receipt is posted in the same step.</p>
      <CustomerPick value={customer} onChange={(c) => { setCustomer(c); setAlloc({}); }} />
      <div className="grid gap-2 md:grid-cols-3">
        <div><Label className="text-xs">Date</Label><Input className="h-8" type="date" value={f.receipt_date} onChange={(e) => setF({ ...f, receipt_date: e.target.value })} /></div>
        <div><Label className="text-xs">Amount</Label><Input className="h-8" type="number" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></div>
        <WhtPicker base={applied} rate={whtRate} onRate={pickRate} amount={f.wht_amount} onAmount={(a) => setF({ ...f, wht_amount: a })} />
        <div><Label className="text-xs">Method</Label>
          <select className="h-8 w-full rounded-md border bg-background px-2" value={f.method} onChange={(e) => setF({ ...f, method: e.target.value })}>
            {["TRANSFER", "CHEQUE", "CASH", "POS", "OTHER"].map((m) => <option key={m} value={m}>{m.toLowerCase()}</option>)}</select></div>
        <div className="md:col-span-2"><Label className="text-xs">Cheque / transfer ref</Label><Input className="h-8" value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} /></div>
      </div>
      <BankSelect value={f.bank_account_id} onChange={(v) => setF({ ...f, bank_account_id: v })} label="Received into" />
      <Label className="text-xs">Apply to</Label>
      {rows.length === 0 ? <p className="text-muted-foreground">No open invoices: the receipt will sit on the customer's account.</p> : (
        <Table><TableHeader><TableRow><TableHead className="w-8" /><TableHead>Invoice</TableHead><TableHead className="text-right">Open</TableHead><TableHead className="w-32">Apply</TableHead></TableRow></TableHeader>
          <TableBody>{rows.map((i) => (
            <TableRow key={i.doc_id}><TableCell><input type="checkbox" checked={Number(alloc[i.doc_id]) > 0}
              onChange={(e) => setAlloc((a) => { const n = { ...a }; if (e.target.checked) n[i.doc_id] = i.open_amount.toFixed(2); else delete n[i.doc_id]; return n; })} /></TableCell>
              <TableCell className="font-mono">{i.doc_number}</TableCell><TableCell className="text-right"><Amount value={i.open_amount} /></TableCell>
              <TableCell><Input className="h-7" type="number" value={alloc[i.doc_id] ?? ""} onChange={(e) => setAlloc({ ...alloc, [i.doc_id]: e.target.value })} /></TableCell></TableRow>))}</TableBody></Table>)}
      <div><Label className="text-xs">What was wrong</Label><Input className="h-8" placeholder="e.g. posted to the wrong customer" value={reason} onChange={(e) => setReason(e.target.value)} /></div>
      <div className="flex items-center justify-end gap-2">
        <span className={applied > avail + 0.001 ? "text-red-600" : "text-muted-foreground"}>Applied {naira(applied)} of {naira(avail)}</span>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
        <Button size="sm" disabled={!reason.trim() || !customer || !f.bank_account_id || !(Number(f.amount) > 0) || applied > avail + 0.001} onClick={save}>Void and post the correct receipt</Button>
      </div>
    </div>
  );
}

type VLine = { account: Dict | null; amount: string; description: string };

export function CorrectVoucher({ v }: { v: Dict }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const transfer = v.kind === "TRANSFER";
  const [f, setF] = useState({ voucher_date: String(v.voucher_date).slice(0, 10), bank_account_id: v.bank_account_id ?? "", to_bank_account_id: v.to_bank_account_id ?? "",
    payee: v.payee ?? "", reference: v.reference ?? "", description: v.description ?? "", amount: String(Number(v.amount)) });
  const [lines, setLines] = useState<VLine[]>(() => (v.lines ?? []).filter((l: Dict) => !l.is_bank).map((l: Dict) => ({
    account: { id: l.account_id, code: l.account_code, name: l.account_name }, amount: String(Number(l.amount ?? (Number(l.debit) || Number(l.credit) || 0))), description: l.description ?? "" })));
  const [reason, setReason] = useState("");
  const total = transfer ? Number(f.amount || 0) : lines.reduce((s, l) => s + Number(l.amount || 0), 0);
  const save = async () => {
    const n = await act(() => books.post<Dict>(`/banking/vouchers/${v.id}/correct`, {
      reason, kind: v.kind, ...f, reference: f.reference || undefined, to_bank_account_id: transfer ? f.to_bank_account_id : undefined,
      amount: transfer ? f.amount : undefined,
      lines: transfer ? undefined : lines.filter((l) => l.account && Number(l.amount) > 0).map((l) => ({ account_id: l.account!.id, amount: l.amount, description: l.description || undefined })),
    }), "Voucher corrected - the wrong one is voided and the right one posted");
    if (n) { setOpen(false); qc.invalidateQueries({ queryKey: ["books"] }); }
  };
  if (!open) return <Button size="sm" variant="outline" onClick={() => setOpen(true)}>Correct this voucher</Button>;
  return (
    <div className={box}>
      <div className="font-semibold">Correct voucher {v.voucher_number}</div>
      <p className="text-muted-foreground">Change what was wrong. {v.voucher_number} is voided (its entry reversed) and the corrected voucher is posted in the same step.</p>
      <div className="grid gap-2 md:grid-cols-3">
        <div><Label className="text-xs">Date</Label><Input className="h-8" type="date" value={f.voucher_date} onChange={(e) => setF({ ...f, voucher_date: e.target.value })} /></div>
        {!transfer && <div><Label className="text-xs">Payee</Label><Input className="h-8" value={f.payee} onChange={(e) => setF({ ...f, payee: e.target.value })} /></div>}
        <div><Label className="text-xs">Reference</Label><Input className="h-8" value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} /></div>
      </div>
      <BankSelect value={f.bank_account_id} onChange={(x) => setF({ ...f, bank_account_id: x })} label={v.kind === "RECEIVE" ? "Received into" : "Paid from"} />
      {transfer ? (
        <div className="grid gap-2 md:grid-cols-2">
          <BankSelect value={f.to_bank_account_id} onChange={(x) => setF({ ...f, to_bank_account_id: x })} label="Transferred to" />
          <div><Label className="text-xs">Amount</Label><Input className="h-8" type="number" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></div>
        </div>
      ) : (
        <>
          {lines.map((l, i) => (
            <div key={i} className="grid items-end gap-2 md:grid-cols-[1.4fr_120px_1fr_32px]">
              <AccountPick label={i === 0 ? "Account" : undefined} value={l.account} onChange={(a) => setLines((xs) => xs.map((x, k) => (k === i ? { ...x, account: a } : x)))} />
              <div>{i === 0 && <Label className="text-xs">Amount</Label>}<Input className="h-9" type="number" value={l.amount} onChange={(e) => setLines((xs) => xs.map((x, k) => (k === i ? { ...x, amount: e.target.value } : x)))} /></div>
              <div>{i === 0 && <Label className="text-xs">Description</Label>}<Input className="h-9" value={l.description} onChange={(e) => setLines((xs) => xs.map((x, k) => (k === i ? { ...x, description: e.target.value } : x)))} /></div>
              <Button size="icon" variant="ghost" onClick={() => setLines((xs) => xs.filter((_, k) => k !== i))}><Trash2 className="h-4 w-4" /></Button>
            </div>
          ))}
          <Button size="sm" variant="ghost" onClick={() => setLines((xs) => [...xs, { account: null, amount: "", description: "" }])}><Plus className="mr-1 h-3.5 w-3.5" />Add line</Button>
        </>
      )}
      <div><Label className="text-xs">What was wrong</Label><Input className="h-8" placeholder="e.g. amount was 45,000" value={reason} onChange={(e) => setReason(e.target.value)} /></div>
      <div className="flex items-center justify-end gap-2">
        <span>{naira(Number(v.amount))} → <strong>{naira(total)}</strong></span>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
        <Button size="sm" disabled={!reason.trim() || !f.bank_account_id || !(total > 0)} onClick={save}>Void and post the correct voucher</Button>
      </div>
    </div>
  );
}
