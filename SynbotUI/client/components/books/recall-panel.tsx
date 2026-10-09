/**
 * One recall, one panel - used by ACE Books Stock, Quality Control and the lineage sheet (an
 * invoice that is part of a recall opens it). It shows the recall end to end:
 *   - every invoice (ACE Books or Sage) and loan that took the batch out, at the price it was sold;
 *   - a customer return on a line: credit note against that invoice (their balance goes down),
 *     the units come back into the frozen batch;
 *   - an invoice the trace missed can be added by hand;
 *   - where the batch came from and stock sent back to the supplier: debit note against that bill.
 */
import { Fragment, ReactNode, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ArrowUpRight, PackageX, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { books, Dict, fmtDate, naira, num, today } from "@/lib/books-api";
import { askText } from "@/lib/ask";
import { DrillTarget } from "./drill-context";
import { act, Amount, CsvButton, DrillLink, Empty, ErrorNote, Loading, StatusBadge, useBooks } from "./kit";

const CONTACT: [string, string][] = [["PENDING", "Not contacted"], ["CONTACTED", "Contacted"], ["RETURNED", "Returned"], ["NOT_RETURNED", "Will not return"]];

function docTarget(i: Dict): DrillTarget | null {
  if (i.source === "ACE" && i.invoice_id) return { type: "invoice", id: String(i.invoice_id), label: i.invoice_number };
  if (i.source === "SAGE" && i.invoice_number) return { type: "sageinvoice", id: i.invoice_number, label: i.invoice_number };
  if (i.source === "LOAN" && i.invoice_number) return { type: "loan", id: i.invoice_number, label: i.invoice_number };
  return null;
}

function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return <div className="rounded-lg border px-3 py-2"><div className="text-[11px] uppercase text-muted-foreground">{label}</div><div className={`text-base font-semibold ${tone ?? ""}`}>{value}</div></div>;
}

export function RecallBody({ id, onChanged }: { id: string; onChanged?: () => void }) {
  const qc = useQueryClient();
  const { data: r, isLoading, error, refetch } = useBooks<Dict>(["recall", id], `/inventory/recalls/${id}`, undefined, !!id);
  const [returning, setReturning] = useState<string | null>(null);
  const [adding, setAdding] = useState({ number: "", sage: false });
  const [supplierForm, setSupplierForm] = useState(false);
  const done = () => { refetch(); qc.invalidateQueries({ queryKey: ["books"] }); qc.invalidateQueries({ queryKey: ["quality"] }); onChanged?.(); };
  if (isLoading) return <Loading />;
  if (error || !r) return <ErrorNote error={error} />;
  const isOpen = r.status === "OPEN";
  const t = r.totals ?? {};
  const setContact = async (i: Dict, contact_status: string) => { if (await act(() => books.patch(`/inventory/recalls/${id}/items/${i.id}`, { contact_status }))) done(); };
  const addInvoice = async () => {
    if (await act(() => books.post(`/inventory/recalls/${id}/invoices`, { invoice_number: adding.number.trim(), sage: adding.sage }), "Invoice added to the recall")) {
      setAdding({ number: "", sage: false }); done();
    }
  };
  const voidIt = async () => {
    const reason = await askText(`Void recall ${r.recall_number}? The batch becomes sellable again and the Quality Control case is voided too. Why?`);
    if (reason && (await act(() => books.post(`/inventory/recalls/${id}/void`, { reason }), "Recall voided - batch released"))) done();
  };
  const close = async () => {
    const notes = await askText("Closing notes (optional)");
    if (notes !== null && (await act(() => books.post(`/inventory/recalls/${id}/close`, { notes: notes || undefined }), "Recall closed"))) done();
  };
  return (
    <div className="space-y-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={r.status} />
        <span className="font-mono font-semibold">{r.recall_number}</span>
        <DrillLink to={{ type: "batch", id: String(r.batch_id), label: r.batch_number }}>{r.product_name ?? r.sku} · batch {r.batch_number}</DrillLink>
        {r.qc_case && <Link to="/quality-control?tab=recalls" className="ml-auto inline-flex items-center text-xs text-primary hover:underline">QC case {r.qc_case.recall_id}<ArrowUpRight className="h-3 w-3" /></Link>}
      </div>
      <p className="text-xs text-muted-foreground">{r.reason} · opened {fmtDate(r.opened_at)}{r.expiry_date ? ` · batch expires ${fmtDate(r.expiry_date)}` : ""}</p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        <Stat label="Invoices affected" value={num(t.invoices)} />
        <Stat label="Units with customers" value={num(t.units_out)} />
        <Stat label="Returned" value={`${num(t.units_returned)}`} tone={Number(t.units_returned) >= Number(t.units_out) && Number(t.units_out) > 0 ? "text-emerald-600" : ""} />
        <Stat label="Credited to customers" value={naira(t.credited ?? 0)} />
        <Stat label="Frozen in stock" value={num(r.on_hand?.quantity)} tone="text-red-600" />
      </div>

      <div>
        <div className="mb-1 flex items-center justify-between">
          <span className="text-xs font-semibold uppercase text-muted-foreground">Invoices affected</span>
          <CsvButton filename={`recall-${r.recall_number}.csv`} rows={r.items} />
        </div>
        {r.items.length === 0 ? <Empty>No sale of this batch was found - all of it is still in stock (frozen). Add an invoice below if a customer has it.</Empty> : (
          <Table>
            <TableHeader><TableRow><TableHead>Invoice</TableHead><TableHead>Customer</TableHead><TableHead className="text-right">Qty</TableHead>
              <TableHead className="text-right">Price</TableHead><TableHead className="text-right">Returned</TableHead><TableHead>Credit note</TableHead><TableHead>Contact</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>{r.items.map((i: Dict) => (
              <Fragment key={i.id}>
                <TableRow>
                  <TableCell className="whitespace-nowrap"><DrillLink to={docTarget(i)}>{i.invoice_number ?? "—"}</DrillLink>
                    <div className="text-[11px] text-muted-foreground">{fmtDate(i.invoice_date)} · {i.source === "SAGE" ? "Sage" : i.source === "LOAN" ? "loan" : "ACE Books"}{i.added_by_hand ? " · added" : ""}</div></TableCell>
                  <TableCell className="max-w-[200px]"><DrillLink to={i.customer_id ? { type: "customer", id: String(i.customer_id), label: i.customer_name } : null}>{i.customer_name ?? "—"}</DrillLink></TableCell>
                  <TableCell className="text-right">{num(i.quantity_sold)}</TableCell>
                  <TableCell className="text-right">{i.unit_price != null ? <Amount value={i.unit_price} /> : "—"}</TableCell>
                  <TableCell className="text-right">{num(i.quantity_returned)}</TableCell>
                  <TableCell className="text-xs">{i.credit_note_id ? <DrillLink to={{ type: "creditnote", id: String(i.credit_note_id), label: i.credit_note_number }}>{i.credit_note_number}</DrillLink> : "—"}
                    {i.credit_total != null && <div className="text-[11px] text-emerald-700">{naira(i.credit_total)}</div>}</TableCell>
                  <TableCell>{isOpen ? (
                    <select className="h-8 rounded-md border bg-background px-1 text-xs" value={i.contact_status} onChange={(e) => setContact(i, e.target.value)}>
                      {CONTACT.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </select>) : <StatusBadge status={i.contact_status} />}</TableCell>
                  <TableCell>{isOpen && i.customer_id && Number(i.quantity_returned) < Number(i.quantity_sold) &&
                    <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => setReturning(returning === i.id ? null : i.id)}>Record return</Button>}</TableCell>
                </TableRow>
                {returning === i.id && (
                  <TableRow className="hover:bg-transparent"><TableCell colSpan={8}>
                    <CustomerReturn recallId={id} item={i} onDone={() => { setReturning(null); done(); }} />
                  </TableCell></TableRow>
                )}
              </Fragment>
            ))}</TableBody>
          </Table>
        )}
        {isOpen && (
          <div className="mt-2 flex flex-wrap items-end gap-2 rounded-md border p-2">
            <div className="space-y-1"><Label className="text-xs">Add an affected invoice</Label>
              <Input className="h-8 w-48" placeholder="Invoice number, e.g. 53540" value={adding.number} onChange={(e) => setAdding({ ...adding, number: e.target.value })} /></div>
            <label className="flex items-center gap-1 pb-1.5 text-xs"><input type="checkbox" checked={adding.sage} onChange={(e) => setAdding({ ...adding, sage: e.target.checked })} />Sage invoice</label>
            <Button size="sm" variant="outline" disabled={!adding.number.trim()} onClick={addInvoice}><Plus className="mr-1 h-3.5 w-3.5" />Add to recall</Button>
            <span className="text-[11px] text-muted-foreground">For a sale the trace did not find. The invoice must carry {r.product_name ?? r.sku}.</span>
          </div>
        )}
      </div>

      <div>
        <div className="mb-1 flex items-center justify-between"><span className="text-xs font-semibold uppercase text-muted-foreground">Supplier</span>
          {isOpen && Number(r.on_hand?.quantity) > 0 && <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => setSupplierForm(!supplierForm)}><PackageX className="mr-1 h-3.5 w-3.5" />Return to supplier</Button>}</div>
        {r.supply.length === 0 ? <p className="text-xs text-muted-foreground">No supplier bill in ACE Books or Sage shows who supplied this batch.</p> : (
          <Table>
            <TableHeader><TableRow><TableHead>Bill</TableHead><TableHead>Supplier</TableHead><TableHead className="text-right">Received</TableHead><TableHead className="text-right">Unit cost</TableHead></TableRow></TableHeader>
            <TableBody>{r.supply.map((s: Dict) => (
              <TableRow key={`${s.source}:${s.bill_number}`}>
                <TableCell className="whitespace-nowrap"><DrillLink to={s.bill_id ? { type: "bill", id: String(s.bill_id), label: s.bill_number } : { type: "sagebill", id: `${s.bill_number}|${s.supplier_id ?? ""}`, label: s.bill_number }}>{s.supplier_invoice_number || s.bill_number}</DrillLink>
                  <div className="text-[11px] text-muted-foreground">{fmtDate(s.bill_date)} · {s.source === "SAGE" ? "Sage" : "ACE Books"}</div></TableCell>
                <TableCell><DrillLink to={s.supplier_id ? { type: "supplier", id: String(s.supplier_id), label: s.supplier_name } : null}>{s.supplier_name ?? "—"}</DrillLink></TableCell>
                <TableCell className="text-right">{num(s.quantity)}</TableCell><TableCell className="text-right"><Amount value={s.unit_cost} /></TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        )}
        {supplierForm && <SupplierReturn recall={r} onDone={() => { setSupplierForm(false); done(); }} />}
        {r.supplier_returns.length > 0 && (
          <div className="mt-2 space-y-1">{r.supplier_returns.map((x: Dict) => (
            <div key={x.id} className="flex flex-wrap justify-between gap-2 text-xs">
              <span>{num(x.quantity)} returned to {x.supplier_name ?? "the supplier"}{x.bill_number || x.sage_bill_number ? ` against ${x.bill_number ?? x.sage_bill_number}` : ""}</span>
              <span><DrillLink to={x.debit_note_id ? { type: "debitnote", id: String(x.debit_note_id), label: x.debit_note_number } : null}>{x.debit_note_number}</DrillLink> · {naira(x.debit_total ?? 0)}</span>
            </div>))}</div>
        )}
      </div>

      <p className="text-xs text-muted-foreground">A customer return raises a credit note on that invoice (their balance goes down) and brings the units back into this batch, which stays frozen. A return to the supplier raises a debit note on their bill (what we owe goes down) and takes the units out of stock.</p>
      {r.status === "VOID" && <p className="text-xs text-red-600">Voided{r.voided_at ? ` ${fmtDate(r.voided_at)}` : ""}: {r.void_reason}</p>}
      {r.status !== "VOID" && (
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="ghost" className="text-red-600" onClick={voidIt}>Void recall</Button>
          {isOpen && <Button size="sm" variant="outline" onClick={close}>Close recall</Button>}
        </div>
      )}
    </div>
  );
}

function CustomerReturn({ recallId, item, onDone }: { recallId: string; item: Dict; onDone: () => void }) {
  const outstanding = Math.max(0, Number(item.quantity_sold) - Number(item.quantity_returned));
  const [quantity, setQuantity] = useState(String(outstanding || ""));
  const [price, setPrice] = useState(item.unit_price != null ? String(Number(item.unit_price)) : "");
  const [credit, setCredit] = useState(item.source !== "LOAN");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    const ok = await act(() => books.post(`/inventory/recalls/${recallId}/returns`, {
      item_id: item.id, customer_id: item.customer_id, quantity: Number(quantity), unit_price: credit ? Number(price || 0) : 0, credit, note_date: today(),
    }), credit ? `Return recorded - credit note on ${item.invoice_number}` : "Return recorded - stock back in the recalled batch");
    setBusy(false);
    if (ok) onDone();
  };
  return (
    <div className="flex flex-wrap items-end gap-2 rounded-md border bg-muted/30 p-2 text-xs">
      <div><Label className="text-xs">Units back</Label><Input className="h-8 w-24" type="number" value={quantity} onChange={(e) => setQuantity(e.target.value)} /></div>
      <div><Label className="text-xs">Credit per unit (₦)</Label><Input className="h-8 w-32" type="number" value={price} disabled={!credit} onChange={(e) => setPrice(e.target.value)} /></div>
      <label className="flex items-center gap-1 pb-2"><input type="checkbox" checked={credit} onChange={(e) => setCredit(e.target.checked)} />Credit the customer</label>
      {credit && Number(quantity) > 0 && Number(price) > 0 && <span className="pb-2 text-muted-foreground">Credit note {naira(Number(quantity) * Number(price))} against {item.invoice_number}</span>}
      <Button size="sm" className="ml-auto" disabled={busy || !(Number(quantity) > 0) || (credit && !(Number(price) > 0))} onClick={save}>Record return</Button>
    </div>
  );
}

function SupplierReturn({ recall, onDone }: { recall: Dict; onDone: () => void }) {
  const first = recall.supply[0];
  const [pick, setPick] = useState(first ? `${first.source}:${first.bill_number}` : "");
  const src = recall.supply.find((s: Dict) => `${s.source}:${s.bill_number}` === pick);
  const [quantity, setQuantity] = useState(String(Number(recall.on_hand?.quantity) || ""));
  const [cost, setCost] = useState(src?.unit_cost != null ? String(Number(src.unit_cost)) : "");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    const ok = await act(() => books.post(`/inventory/recalls/${recall.id}/supplier-return`, {
      quantity: Number(quantity), unit_cost: Number(cost || 0) || undefined, note_date: today(),
      bill_id: src?.bill_id ?? undefined, bill_number: src && !src.bill_id ? src.bill_number : undefined,
    }), "Debit note raised - stock returned to the supplier");
    setBusy(false);
    if (ok) onDone();
  };
  return (
    <div className="mt-2 flex flex-wrap items-end gap-2 rounded-md border bg-muted/30 p-2 text-xs">
      <div><Label className="text-xs">Against bill</Label>
        <select className="h-8 rounded-md border bg-background px-2" value={pick} onChange={(e) => { setPick(e.target.value); const s = recall.supply.find((x: Dict) => `${x.source}:${x.bill_number}` === e.target.value); if (s?.unit_cost != null) setCost(String(Number(s.unit_cost))); }}>
          {recall.supply.map((s: Dict) => <option key={`${s.source}:${s.bill_number}`} value={`${s.source}:${s.bill_number}`}>{s.supplier_invoice_number || s.bill_number} · {s.supplier_name}</option>)}
        </select></div>
      <div><Label className="text-xs">Units back</Label><Input className="h-8 w-24" type="number" value={quantity} onChange={(e) => setQuantity(e.target.value)} /></div>
      <div><Label className="text-xs">Credit per unit (₦)</Label><Input className="h-8 w-32" type="number" value={cost} onChange={(e) => setCost(e.target.value)} /></div>
      {Number(quantity) > 0 && Number(cost) > 0 && <span className="pb-2 text-muted-foreground">Debit note {naira(Number(quantity) * Number(cost))}</span>}
      <Button size="sm" className="ml-auto" disabled={busy || !(Number(quantity) > 0) || !src} onClick={save}>Raise debit note</Button>
    </div>
  );
}

/** On an invoice (ACE Books or Sage): the recalls it is part of, each opening the recall. */
export function RecallNotice({ recalls }: { recalls?: Dict[] }) {
  if (!recalls?.length) return null;
  return (
    <div className="space-y-1 rounded-md border border-red-300 bg-red-50 p-2 text-xs dark:bg-red-500/10">
      {recalls.map((x) => (
        <div key={x.recall_id} className="flex flex-wrap items-center gap-x-2">
          <PackageX className="h-3.5 w-3.5 text-red-600" />
          <span className="font-semibold text-red-700 dark:text-red-300">Recalled</span>
          <span>{x.sku} batch {x.batch_number}: {num(x.quantity_sold)} on this invoice, {num(x.quantity_returned)} returned</span>
          <DrillLink to={{ type: "recall", id: String(x.recall_id), label: x.recall_number }}>{x.recall_number} ({String(x.status).toLowerCase()})</DrillLink>
          {x.credit_note_id && <DrillLink to={{ type: "creditnote", id: String(x.credit_note_id), label: x.credit_note_number }}>credit {x.credit_note_number}</DrillLink>}
        </div>
      ))}
    </div>
  );
}
