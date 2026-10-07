import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { DrillLink } from "@/components/books/kit";
import { DrillTarget } from "@/components/books/drill-context";
import { AlertTriangle, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { FilterBar } from "@/components/workspace/FilterBar";
import { BooksShell } from "@/components/books/BooksShell";
import { RecordView } from "@/components/books/lineage";
import {
  act, Amount, BankSelect, CsvButton, CustomerPick, DateRange, Empty, ErrorNote, JournalSheet, Loading, ProductPick,
  Section, StatusBadge, useBooks, useLines,
} from "@/components/books/kit";
import { books, BooksError, Dict, fmtDate, naira, newIdemKey, num, today, yearStart } from "@/lib/books-api";
import { PendingReceiptNote } from "@/components/books/data-issues";

export default function BooksSales() {
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState(params.get("tab") ?? "invoices");
  const open = (k: string, v: string | null) => { const p = new URLSearchParams(params); v ? p.set(k, v) : p.delete(k); setParams(p, { replace: true }); };
  return (
    <BooksShell title="Sales & Receivables"
                actions={<>
                  <Button size="sm" onClick={() => open("new", "invoice")}><Plus className="mr-1 h-4 w-4" />Invoice</Button>
                  <Button size="sm" variant="outline" onClick={() => open("new", "receipt")}>Record receipt</Button>
                  <Button size="sm" variant="outline" onClick={() => open("new", "creditnote")}>Credit note</Button>
                </>}>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="flex-wrap">
          <TabsTrigger value="invoices">Invoices</TabsTrigger>
          <TabsTrigger value="receipts">Receipts</TabsTrigger>
          <TabsTrigger value="credit">Credit notes</TabsTrigger>
          <TabsTrigger value="aging">Aged receivables</TabsTrigger>
          <TabsTrigger value="statement">Customer statement</TabsTrigger>
        </TabsList>
        <TabsContent value="invoices"><InvoiceList onOpen={(id) => open("invoice", id)} /></TabsContent>
        <TabsContent value="receipts"><ReceiptList onOpen={(id) => open("receipt", id)} /></TabsContent>
        <TabsContent value="credit"><CreditNoteList onOpen={(id) => open("creditnote", id)} /></TabsContent>
        <TabsContent value="aging"><AgedReceivables /></TabsContent>
        <TabsContent value="statement"><CustomerStatement /></TabsContent>
      </Tabs>
      <InvoiceForm open={params.get("new") === "invoice"} onClose={(id) => { open("new", null); if (id) open("invoice", id); }} />
      <ReceiptForm open={params.get("new") === "receipt"} onClose={() => open("new", null)} />
      <CreditNoteForm open={params.get("new") === "creditnote"} onClose={() => open("new", null)} />
      <InvoiceDetail id={params.get("invoice")} onClose={() => open("invoice", null)} />
      <ReceiptDetail id={params.get("receipt")} onClose={() => open("receipt", null)} />
      <CreditNoteDetail id={params.get("creditnote")} onClose={() => open("creditnote", null)} />
    </BooksShell>
  );
}

// ---------------------------------------------------------------------------
// Lists
// ---------------------------------------------------------------------------

function InvoiceList({ onOpen }: { onOpen: (id: string) => void }) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [range, setRange] = useState({ from: yearStart(), to: today() });
  const { data, isLoading, error } = useBooks<any>(["invoices", search, status, range], "/sales/invoices",
    { search, status, from: range.from, to: range.to, limit: 300 });
  return (
    <Section title={`Invoices${data ? ` (${data.total})` : ""}`} actions={<CsvButton filename="invoices.csv" rows={data?.items} />}>
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <div className="flex-1"><FilterBar search={{ value: search, onChange: setSearch, placeholder: "Invoice no., customer, PO" }}
          selects={[{ label: "Status", value: status, onChange: setStatus, options: ["DRAFT", "POSTED", "PARTIALLY_PAID", "PAID", "VOID"].map((s) => ({ value: s, label: s.replace("_", " ").toLowerCase() })) }]} /></div>
        <DateRange from={range.from} to={range.to} onChange={(f, t) => setRange({ from: f ?? range.from, to: t })} />
      </div>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (data.items.length === 0 ? <Empty>No invoices in this period.</Empty> : (
        <Table>
          <TableHeader><TableRow><TableHead>Invoice</TableHead><TableHead>Date</TableHead><TableHead>Customer</TableHead><TableHead>Due</TableHead><TableHead className="text-right">Total</TableHead><TableHead className="text-right">Balance</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
          <TableBody>
            {data.items.map((i: Dict) => (
              <TableRow key={i.id} className="cursor-pointer hover:bg-muted/50" onClick={() => onOpen(i.id)}>
                <TableCell className="font-mono text-xs">{i.invoice_number}{i.source_type === "FRONTDESK" && <span className="ml-1 text-[10px] text-muted-foreground">frontdesk</span>}</TableCell>
                <TableCell className="whitespace-nowrap">{fmtDate(i.invoice_date)}</TableCell>
                <TableCell className="max-w-[240px] truncate"><DrillLink to={{ type: "customer", id: String(i.customer_id ?? ""), label: i.customer_name }}>{i.customer_name}</DrillLink></TableCell>
                <TableCell className={i.due_date < today() && Number(i.balance_due) > 0 ? "text-red-600" : ""}>{fmtDate(i.due_date)}</TableCell>
                <TableCell className="text-right"><Amount value={i.total} /></TableCell>
                <TableCell className="text-right"><Amount value={i.balance_due} /></TableCell>
                <TableCell><StatusBadge status={i.status} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ))}
    </Section>
  );
}

function ReceiptList({ onOpen }: { onOpen: (id: string) => void }) {
  const [search, setSearch] = useState("");
  const [range, setRange] = useState({ from: yearStart(), to: today() });
  const { data, isLoading, error } = useBooks<any>(["receipts", search, range], "/receivables/receipts", { search, from: range.from, to: range.to, limit: 300 });
  return (
    <Section title={`Receipts${data ? ` (${data.total})` : ""}`} actions={<CsvButton filename="receipts.csv" rows={data?.items} />}>
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <div className="flex-1"><FilterBar search={{ value: search, onChange: setSearch, placeholder: "Receipt no., customer, cheque/transfer ref" }} /></div>
        <DateRange from={range.from} to={range.to} onChange={(f, t) => setRange({ from: f ?? range.from, to: t })} />
      </div>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (data.items.length === 0 ? <Empty>No receipts in this period.</Empty> : (
        <Table>
          <TableHeader><TableRow><TableHead>Receipt</TableHead><TableHead>Date</TableHead><TableHead>Customer</TableHead><TableHead>Method</TableHead><TableHead>Into</TableHead><TableHead className="text-right">Amount</TableHead><TableHead className="text-right">Unapplied</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
          <TableBody>
            {data.items.map((r: Dict) => (
              <TableRow key={r.id} className="cursor-pointer hover:bg-muted/50" onClick={() => onOpen(r.id)}>
                <TableCell className="font-mono text-xs">{r.receipt_number}</TableCell>
                <TableCell className="whitespace-nowrap">{fmtDate(r.receipt_date)}</TableCell>
                <TableCell className="max-w-[220px] truncate"><DrillLink to={{ type: "customer", id: String(r.customer_id ?? ""), label: r.customer_name }}>{r.customer_name}</DrillLink></TableCell>
                <TableCell className="text-xs">{r.method.toLowerCase()} {r.reference}</TableCell>
                <TableCell className="text-xs">{r.bank_account_name}</TableCell>
                <TableCell className="text-right"><Amount value={Number(r.amount) + Number(r.wht_amount)} /></TableCell>
                <TableCell className="text-right"><Amount value={r.unapplied} blankZero /></TableCell>
                <TableCell><StatusBadge status={r.status} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ))}
    </Section>
  );
}

function CreditNoteList({ onOpen }: { onOpen: (id: string) => void }) {
  const { data, isLoading, error } = useBooks<any>(["creditnotes"], "/sales/credit-notes", { limit: 300 });
  return (
    <Section title="Credit notes & returns inward" actions={<CsvButton filename="credit-notes.csv" rows={data?.items} />}>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (data.items.length === 0 ? <Empty>No credit notes yet.</Empty> : (
        <Table>
          <TableHeader><TableRow><TableHead>Number</TableHead><TableHead>Date</TableHead><TableHead>Customer</TableHead><TableHead>Against</TableHead><TableHead>Reason</TableHead><TableHead className="text-right">Total</TableHead><TableHead>Stock back</TableHead></TableRow></TableHeader>
          <TableBody>
            {data.items.map((n: Dict) => (
              <TableRow key={n.id} className="cursor-pointer hover:bg-muted/50" onClick={() => onOpen(n.id)}>
                <TableCell className="font-mono text-xs">{n.credit_note_number}</TableCell>
                <TableCell className="whitespace-nowrap">{fmtDate(n.note_date)}</TableCell>
                <TableCell className="max-w-[200px] truncate"><DrillLink to={{ type: "customer", id: String(n.customer_id ?? ""), label: n.customer_name }}>{n.customer_name}</DrillLink></TableCell>
                <TableCell className="font-mono text-xs">{n.invoice_number ?? "—"}</TableCell>
                <TableCell className="max-w-[220px] truncate text-xs">{n.reason}</TableCell>
                <TableCell className="text-right"><Amount value={n.total} /></TableCell>
                <TableCell>{n.return_to_stock ? "yes" : ""}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ))}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Invoice form & detail
// ---------------------------------------------------------------------------

type Line = { line_type: string; product: Dict | null; description: string; quantity: string; unit_price: string; discount_amount: string; batch_number: string;
  expiry?: string; batch_id?: string; unit_cost?: string };
const blankLine = (): Line => ({ line_type: "ITEM", product: null, description: "", quantity: "1", unit_price: "", discount_amount: "", batch_number: "" });

/** Sellable batches of the chosen product: batch number, man. date, expiry, quantity, unit cost. */
function BatchSelect({ product, value, onChange }: { product: Dict | null; value?: string; onChange: (b: Dict | null) => void }) {
  const batches: Dict[] = (product?.batches ?? []).filter((b: Dict) => b.sellable);
  const held: Dict[] = (product?.batches ?? []).filter((b: Dict) => !b.sellable);
  if (!product) return null;
  return (
    <div className="space-y-1">
      <select className="h-8 w-full rounded-md border bg-background px-2 text-xs" value={value ?? ""}
              onChange={(e) => onChange(batches.find((b) => b.id === e.target.value) ?? null)}>
        <option value="">Batch: first to expire (automatic)</option>
        {batches.map((b) => (
          <option key={b.id} value={b.id}>
            {b.batch_number} · exp {fmtDate(b.expiry_date)}{b.manufacture_date ? ` · mfd ${fmtDate(b.manufacture_date)}` : ""} · {num(b.available)} available
          </option>
        ))}
      </select>
      {held.length > 0 && <div className="text-[11px] text-muted-foreground">{held.length} batch(es) not offered: {held.map((b) => `${b.batch_number} (${b.expiry_date && b.expiry_date < today() ? "expired" : b.status.toLowerCase()})`).join(", ")}</div>}
    </div>
  );
}

/** Customer position shown while raising an invoice or receipt: exposure vs limit, terms, and any
 *  Frontdesk invoices in progress (those post themselves on approval - don't key them again). */
function CustomerPanel({ customer }: { customer: Dict | null }) {
  const { data: d } = useBooks<Dict>(["cust-overview", customer?.id], `/customers/${customer?.id}/overview`, undefined, !!customer);
  if (!customer || !d) return null;
  const c = d.customer;
  const limit = Number(c.credit_limit || 0);
  const used = limit ? Math.round((Number(d.exposure) / limit) * 100) : null;
  return (
    <div className="space-y-2 rounded-lg bg-muted/40 p-3 text-xs">
      <div className="flex flex-wrap gap-x-6 gap-y-1">
        <span>Owes <strong><Amount value={d.balance} /></strong></span>
        <span>Overdue <strong><Amount value={d.overdue} /></strong></span>
        <span>Credit limit <strong>{limit ? naira(limit) : "none"}</strong>{used != null && <span className={used > 90 ? " text-red-600" : used > 70 ? " text-amber-600" : ""}> · {used}% used</span>}</span>
        <span>Terms <strong>{c.payment_terms_days ? `${c.payment_terms_days} days` : "on receipt"}</strong></span>
      </div>
      {d.frontdesk_in_progress?.length > 0 && (
        <div className="flex items-start gap-1 text-amber-700 dark:text-amber-300"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{d.frontdesk_in_progress.length} Frontdesk invoice(s) for this customer are in progress ({d.frontdesk_in_progress.map((f: Dict) => f.invoice_number).join(", ")}).
            They post to the books automatically on Finance approval — don't raise them again here.</span></div>
      )}
    </div>
  );
}

function lineTotal(l: Line) {
  const gross = Number(l.quantity || 0) * Number(l.unit_price || 0);
  if (l.line_type === "DISCOUNT") return -Number(l.unit_price || 0);
  if (l.line_type === "CHARGE") return Number(l.unit_price || 0);
  return gross - Number(l.discount_amount || 0);
}

function InvoiceForm({ open, onClose }: { open: boolean; onClose: (createdId?: string) => void }) {
  const qc = useQueryClient();
  const [customer, setCustomer] = useState<Dict | null>(null);
  const [date, setDate] = useState(today());
  const [reference, setReference] = useState("");
  const [shipping, setShipping] = useState("Hand Delivery");
  const [shipTo, setShipTo] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [credit, setCredit] = useState<Dict | null>(null);
  const [override, setOverride] = useState("");
  const [idem] = useState(newIdemKey);
  const L = useLines<Line>(blankLine);
  const total = L.lines.reduce((s, l) => s + lineTotal(l), 0);
  const { data: layout } = useBooks<Dict>(["invoice-layout"], "/settings/invoice-layout", undefined, open);
  useEffect(() => { if (!open) { setCustomer(null); L.reset(); setCredit(null); setOverride(""); setReference(""); setNotes(""); setShipTo(""); } }, [open]);

  const payload = (post: boolean) => ({
    customer_id: customer?.id, invoice_date: date, reference, customer_po: reference || undefined, shipping_method: shipping || undefined,
    ship_to: shipTo || undefined, notes, post,
    override_credit: !!override, override_reason: override || undefined,
    lines: L.lines.filter((l) => l.line_type !== "ITEM" || l.product).map((l) => ({
      line_type: l.line_type, sku: l.product?.sku, description: l.description || undefined,
      quantity: l.line_type === "CHARGE" || l.line_type === "DISCOUNT" ? 1 : l.quantity,
      unit_price: l.unit_price || 0, discount_amount: l.discount_amount || 0,
      batch_id: l.batch_id || undefined, batch_number: l.batch_id ? undefined : l.batch_number || undefined,
    })),
  });
  const submit = async (post: boolean) => {
    if (!customer) return;
    setBusy(true);
    try {
      const inv = await books.post("/sales/invoices", payload(post), idem + (post ? "p" : "d"));
      qc.invalidateQueries({ queryKey: ["books"] });
      onClose(inv.id);
    } catch (e) {
      const err = e as BooksError;
      if (err.code === "CREDIT_LIMIT_EXCEEDED") setCredit(err.details ?? {});
      else act(async () => { throw e; });
    } finally {
      setBusy(false);
    }
  };
  return (
    <DetailSheet open={open} onOpenChange={(o) => !o && onClose()} title={`New sales invoice${layout?.next_invoice_number ? ` · No. ${layout.next_invoice_number}` : ""}`}
                 description="Posting records AR, revenue, discounts, delivery income, cost of sales and stock in one step. Numbers continue the invoice sequence."
                 footer={<div className="flex w-full items-center justify-between gap-2">
                   <span className="text-sm">Total <strong>{naira(total)}</strong></span>
                   <div className="flex gap-2">
                     <Button variant="outline" disabled={busy || !customer} onClick={() => submit(false)}>Save draft</Button>
                     <Button disabled={busy || !customer || total <= 0} onClick={() => submit(true)}>{busy ? "Posting…" : "Post invoice"}</Button>
                   </div>
                 </div>}>
      <div className="space-y-3">
        <CustomerPick value={customer} onChange={setCustomer} />
        <CustomerPanel customer={customer} />
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <div className="space-y-1"><Label className="text-xs">Invoice date</Label><Input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></div>
          <div className="space-y-1"><Label className="text-xs">Customer PO</Label><Input value={reference} onChange={(e) => setReference(e.target.value)} /></div>
          <div className="space-y-1"><Label className="text-xs">Shipping method</Label><Input value={shipping} onChange={(e) => setShipping(e.target.value)} /></div>
          <div className="space-y-1"><Label className="text-xs">Ship to (if not the billing address)</Label><Input value={shipTo} onChange={(e) => setShipTo(e.target.value)} /></div>
        </div>
        <div className="space-y-2">
          {L.lines.map((l, i) => {
            const b: Dict | undefined = (l.product?.batches ?? []).find((x: Dict) => x.id === l.batch_id) ?? (l.product?.batches ?? []).find((x: Dict) => x.sellable);
            return (
            <div key={i} className="space-y-2 rounded-lg border p-2">
              <div className="flex items-center gap-2">
                <select className="h-8 rounded-md border bg-background px-2 text-xs" value={l.line_type} onChange={(e) => L.update(i, { line_type: e.target.value })}>
                  <option value="ITEM">Stock item</option><option value="SERVICE">Service</option><option value="CHARGE">Delivery / charge</option><option value="DISCOUNT">Invoice discount</option>
                </select>
                <div className="flex-1">{l.line_type === "ITEM"
                  ? <ProductPick value={l.product} customerId={customer?.id} forSale
                                 onChange={(p) => L.update(i, { product: p, unit_price: p?.suggested_price ? String(p.suggested_price) : l.unit_price,
                                                                batch_id: undefined, batch_number: p?.next_batch ?? "", expiry: p?.next_expiry ?? undefined })} />
                  : <Input className="h-8" placeholder={l.line_type === "CHARGE" ? "e.g. Delivery charge" : "Description"} value={l.description} onChange={(e) => L.update(i, { description: e.target.value })} />}</div>
                <Button size="icon" variant="ghost" onClick={() => L.remove(i)}><Trash2 className="h-4 w-4" /></Button>
              </div>
              {l.line_type === "ITEM" && l.product && (
                <PendingReceiptNote product={l.product} onReload={(p) => L.update(i, { product: p, batch_id: undefined, batch_number: p?.next_batch ?? "", expiry: p?.next_expiry ?? undefined })} />
              )}
              {l.line_type === "ITEM" && l.product && (
                <BatchSelect product={l.product} value={l.batch_id}
                             onChange={(bb) => L.update(i, { batch_id: bb?.id, batch_number: bb?.batch_number ?? l.product?.next_batch ?? "", expiry: bb?.expiry_date ?? l.product?.next_expiry })} />
              )}
              <div className="grid grid-cols-3 gap-2">
                {(l.line_type === "ITEM" || l.line_type === "SERVICE") && <div><Label className="text-[11px]">Qty</Label><Input className="h-8" type="number" value={l.quantity} onChange={(e) => L.update(i, { quantity: e.target.value })} /></div>}
                <div><Label className="text-[11px]">{l.line_type === "DISCOUNT" || l.line_type === "CHARGE" ? "Amount" : "Unit price"}</Label>
                  <Input className="h-8" type="number" value={l.unit_price} onChange={(e) => L.update(i, { unit_price: e.target.value })} /></div>
                {(l.line_type === "ITEM" || l.line_type === "SERVICE") && <div><Label className="text-[11px]">Discount ₦</Label><Input className="h-8" type="number" value={l.discount_amount} onChange={(e) => L.update(i, { discount_amount: e.target.value })} /></div>}
              </div>
              {l.line_type === "ITEM" && l.product && (
                <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 rounded bg-muted/40 px-2 py-1 text-[11px] sm:grid-cols-5">
                  <span>Batch <strong>{b?.batch_number ?? l.batch_number ?? "—"}</strong></span>
                  <span>Man. date <strong>{b?.manufacture_date ? fmtDate(b.manufacture_date) : "—"}</strong></span>
                  <span>Exp. date <strong>{fmtDate(b?.expiry_date ?? l.expiry) || "—"}</strong></span>
                  <span>Unit cost <strong>{b?.unit_cost ? naira(b.unit_cost) : "—"}</strong></span>
                  <span className={Number(l.quantity) > Number(l.product.sellable_qty ?? l.product.on_hand) ? "text-red-600" : ""}>Can sell <strong>{num(l.product.sellable_qty ?? l.product.on_hand)}</strong></span>
                </div>
              )}
              <div className="flex justify-end text-xs text-muted-foreground"><span>Line {naira(lineTotal(l))}</span></div>
            </div>
            );
          })}
          <Button size="sm" variant="outline" onClick={L.add}><Plus className="mr-1 h-4 w-4" />Add line</Button>
        </div>
        <div className="space-y-1"><Label className="text-xs">Notes</Label><Textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} /></div>
        {credit && (
          <div className="space-y-2 rounded-lg border border-amber-400 bg-amber-50 p-3 text-sm dark:bg-amber-500/10">
            <div className="flex items-center gap-2 font-medium text-amber-800 dark:text-amber-300"><AlertTriangle className="h-4 w-4" />Credit limit would be exceeded by {naira(credit.excess)}</div>
            <div className="text-xs">Limit {naira(credit.credit_limit)} · owing now {naira(credit.current_exposure)} · after this invoice {naira(credit.projected_exposure)}</div>
            <Input placeholder="Reason to continue (recorded for audit)" value={override} onChange={(e) => setOverride(e.target.value)} />
            <p className="text-xs text-muted-foreground">Enter a reason and post again to continue, or cancel.</p>
          </div>
        )}
      </div>
    </DetailSheet>
  );
}

function InvoiceDetail({ id, onClose }: { id: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const { data: inv, refetch } = useBooks<Dict>(["invoice", id], `/sales/invoices/${id}`, undefined, !!id);
  const [override, setOverride] = useState("");
  const [v, setV] = useState(0);
  const refresh = () => { refetch(); setV((x) => x + 1); qc.invalidateQueries({ queryKey: ["books"] }); };
  const post = async () => {
    try {
      await books.post(`/sales/invoices/${id}/post`, override ? { override_credit: true, override_reason: override } : {});
      refresh();
    } catch (e) {
      const err = e as BooksError;
      if (err.code === "CREDIT_LIMIT_EXCEEDED") act(async () => { throw new Error(`${err.message}. Enter a reason below and post again.`); });
      else act(async () => { throw e; });
    }
  };
  const voidIt = async () => {
    const reason = window.prompt("Why is this invoice being voided? (stock and all postings will be reversed)");
    if (reason && (await act(() => books.post(`/sales/invoices/${id}/void`, { reason }), "Invoice voided"))) refresh();
  };
  const canVoid = inv && ["DRAFT", "POSTED"].includes(inv.status) && !inv.is_opening && Number(inv.amount_settled) === 0;
  return (
    <DetailSheet open={!!id} onOpenChange={(o) => !o && onClose()} title={inv ? `Invoice ${inv.invoice_number}` : "Invoice"} description={inv?.customer_name}
                 footer={inv && (inv.status === "DRAFT" || canVoid) ? (
                   <div className="flex w-full flex-wrap items-center justify-end gap-2">
                     {inv.status === "DRAFT" && (<><Input className="h-9 w-64" placeholder="Credit override reason (if needed)" value={override} onChange={(e) => setOverride(e.target.value)} />
                       <Button size="sm" onClick={post}>Post invoice</Button></>)}
                     {canVoid && <Button size="sm" variant="destructive" onClick={voidIt}>Void</Button>}
                   </div>) : undefined}>
      {id && <RecordView key={`${id}:${v}`} t={{ type: "invoice", id }} />}
    </DetailSheet>
  );
}

function Row({ k, v, bold }: { k: string; v: any; bold?: boolean }) {
  return <div className={`flex justify-between ${bold ? "font-semibold" : ""}`}><span className="text-muted-foreground">{k}</span><Amount value={v} /></div>;
}

// ---------------------------------------------------------------------------
// Receipts
// ---------------------------------------------------------------------------

function ReceiptForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [customer, setCustomer] = useState<Dict | null>(null);
  const [f, setF] = useState({ receipt_date: today(), method: "TRANSFER", bank_account_id: "", amount: "", wht_amount: "", reference: "", notes: "" });
  const [alloc, setAlloc] = useState<Record<string, string>>({});
  const [dupe, setDupe] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [idem] = useState(newIdemKey);
  useEffect(() => { if (!open) { setCustomer(null); setAlloc({}); setDupe(null); setF({ ...f, amount: "", wht_amount: "", reference: "", notes: "" }); } }, [open]);
  const { data: items } = useBooks<Dict[]>(["openitems", customer?.id], "/receivables/open-items", { customer_id: customer?.id }, !!customer);
  const invoices = useMemo(() => (items ?? []).filter((i) => i.doc_type === "INVOICE" && Number(i.open_amount) > 0).sort((a, b) => (a.due_date < b.due_date ? -1 : 1)), [items]);
  const available = Number(f.amount || 0) + Number(f.wht_amount || 0);
  const allocated = Object.values(alloc).reduce((s, v) => s + Number(v || 0), 0);
  const autoAllocate = () => {
    let left = available;
    const next: Record<string, string> = {};
    for (const i of invoices) { if (left <= 0) break; const take = Math.min(left, Number(i.open_amount)); next[i.doc_id] = take.toFixed(2); left -= take; }
    setAlloc(next);
  };
  const submit = async (confirmDuplicate = false) => {
    setBusy(true);
    try {
      await books.post("/receivables/receipts", {
        ...f, customer_id: customer?.id, confirm_duplicate: confirmDuplicate,
        allocations: Object.entries(alloc).filter(([, v]) => Number(v) > 0).map(([invoice_id, amount]) => ({ invoice_id, amount })),
      }, idem + (confirmDuplicate ? "c" : ""));
      qc.invalidateQueries({ queryKey: ["books"] });
      onClose();
    } catch (e) {
      const err = e as BooksError;
      if (err.code === "DUPLICATE_REFERENCE") setDupe(err.message);
      else act(async () => { throw e; });
    } finally { setBusy(false); }
  };
  return (
    <DetailSheet open={open} onOpenChange={(o) => !o && onClose()} title="Record customer receipt"
                 description="Money in against the customer's invoices. Anything not applied stays on account."
                 footer={<div className="flex w-full items-center justify-between"><span className="text-xs">Applied {naira(allocated)} of {naira(available)}{available - allocated > 0 ? ` · ${naira(available - allocated)} on account` : ""}</span>
                   <Button disabled={busy || !customer || !f.bank_account_id || Number(f.amount) <= 0 || allocated > available + 0.001} onClick={() => submit(false)}>{busy ? "Posting…" : "Post receipt"}</Button></div>}>
      <div className="space-y-3">
        <CustomerPick value={customer} onChange={(c) => { setCustomer(c); setAlloc({}); }} />
        <CustomerPanel customer={customer} />
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1"><Label className="text-xs">Date</Label><Input type="date" value={f.receipt_date} onChange={(e) => setF({ ...f, receipt_date: e.target.value })} /></div>
          <div className="space-y-1"><Label className="text-xs">Method</Label>
            <select className="h-9 w-full rounded-md border bg-background px-2 text-sm" value={f.method} onChange={(e) => setF({ ...f, method: e.target.value })}>
              {["TRANSFER", "CHEQUE", "CASH", "POS", "OTHER"].map((m) => <option key={m} value={m}>{m.toLowerCase()}</option>)}
            </select></div>
        </div>
        <BankSelect value={f.bank_account_id} onChange={(v) => setF({ ...f, bank_account_id: v })} label="Received into" />
        <div className="grid grid-cols-3 gap-3">
          <div className="space-y-1"><Label className="text-xs">Amount received</Label><Input type="number" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></div>
          <div className="space-y-1"><Label className="text-xs">WHT deducted</Label><Input type="number" value={f.wht_amount} onChange={(e) => setF({ ...f, wht_amount: e.target.value })} /></div>
          <div className="space-y-1"><Label className="text-xs">Cheque / transfer ref</Label><Input value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} /></div>
        </div>
        {dupe && (
          <div className="space-y-2 rounded-lg border border-amber-400 bg-amber-50 p-3 text-sm dark:bg-amber-500/10">
            <div className="flex items-center gap-2 font-medium text-amber-800 dark:text-amber-300"><AlertTriangle className="h-4 w-4" />Possible duplicate: {dupe}</div>
            <div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => setDupe(null)}>Fix the reference</Button><Button size="sm" onClick={() => submit(true)}>It is genuine — post anyway</Button></div>
          </div>
        )}
        {customer && (
          <div className="space-y-2">
            <div className="flex items-center justify-between"><Label className="text-xs">Apply to invoices (oldest due first)</Label><Button size="sm" variant="outline" onClick={autoAllocate} disabled={!available}>Auto-apply</Button></div>
            {invoices.length === 0 ? <Empty>No open invoices — the receipt will sit on the customer's account.</Empty> : (
              <Table>
                <TableHeader><TableRow><TableHead>Invoice</TableHead><TableHead>Due</TableHead><TableHead className="text-right">Open</TableHead><TableHead className="w-32">Apply</TableHead></TableRow></TableHeader>
                <TableBody>
                  {invoices.map((i) => (
                    <TableRow key={i.doc_id}>
                      <TableCell className="font-mono text-xs">{i.doc_number}</TableCell>
                      <TableCell className="text-xs">{fmtDate(i.due_date)}</TableCell>
                      <TableCell className="text-right"><Amount value={i.open_amount} /></TableCell>
                      <TableCell><Input className="h-8" type="number" value={alloc[i.doc_id] ?? ""} onChange={(e) => setAlloc({ ...alloc, [i.doc_id]: e.target.value })} /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </div>
        )}
        <div className="space-y-1"><Label className="text-xs">Notes</Label><Textarea rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></div>
      </div>
    </DetailSheet>
  );
}

function ReceiptDetail({ id, onClose }: { id: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const { data: r, refetch } = useBooks<Dict>(["receipt", id], `/receivables/receipts/${id}`, undefined, !!id);
  const [v, setV] = useState(0);
  const voidIt = async () => {
    const reason = window.prompt("Why is this receipt being voided? (e.g. cheque bounced)");
    if (reason && (await act(() => books.post(`/receivables/receipts/${id}/void`, { reason }), "Receipt voided"))) { refetch(); setV((x) => x + 1); qc.invalidateQueries({ queryKey: ["books"] }); }
  };
  return (
    <DetailSheet open={!!id} onOpenChange={(o) => !o && onClose()} title={r ? `Receipt ${r.receipt_number}` : "Receipt"} description={r?.customer_name}
                 footer={r?.status === "POSTED" ? <Button size="sm" variant="destructive" onClick={voidIt}>Void receipt</Button> : undefined}>
      {id && <RecordView key={`${id}:${v}`} t={{ type: "receipt", id }} />}
    </DetailSheet>
  );
}

// ---------------------------------------------------------------------------
// Credit notes
// ---------------------------------------------------------------------------

/** Return inward: pick the customer, then the invoice the goods were sold on (ACE Books or Sage
 *  history); its lines come up with the batch, price and cost - enter what came back. The credit
 *  reduces that invoice (and the customer's balance) and the stock returns to the batch at its cost. */
function CreditNoteForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [customer, setCustomer] = useState<Dict | null>(null);
  const [inv, setInv] = useState<Dict | null>(null);
  const [reason, setReason] = useState("");
  const [date, setDate] = useState(today());
  const [toStock, setToStock] = useState(true);
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  const [back, setBack] = useState<Record<number, string>>({});
  const L = useLines<Line>(blankLine);
  const { data: invs, isLoading } = useBooks<Dict[]>(["cn-returnable", customer?.id, search], "/sales/returnable-invoices",
    { customer_id: customer?.id, search: search || undefined }, !!customer);
  useEffect(() => { if (!open) { setCustomer(null); setInv(null); setReason(""); setBack({}); L.reset(); } }, [open]);
  const invLines: Dict[] = inv?.lines ?? [];
  const fromInvoice = invLines.map((l, i): Dict => ({ ...l, qty: Number(back[i] || 0) })).filter((l) => l.qty > 0);
  const total = inv ? fromInvoice.reduce((s, l) => s + l.qty * Number(l.unit_price || 0), 0) : L.lines.reduce((s, l) => s + lineTotal(l), 0);
  const submit = async () => {
    setBusy(true);
    const lines = inv
      ? fromInvoice.map((l) => ({ line_type: "ITEM", sku: l.sku, description: l.description, quantity: l.qty, unit_price: l.unit_price || 0,
                                  batch_id: l.return_batch_id || undefined, unit_cost: l.unit_cost ?? undefined }))
      : L.lines.filter((l) => l.line_type !== "ITEM" || l.product).map((l) => ({ line_type: l.line_type, sku: l.product?.sku, description: l.description || undefined,
          quantity: l.line_type === "ITEM" || l.line_type === "SERVICE" ? l.quantity : 1, unit_price: l.unit_price || 0, batch_number: l.batch_number || undefined }));
    const ok = await act(() => books.post("/sales/credit-notes", {
      customer_id: customer?.id, invoice_id: inv && !inv.sage ? inv.invoice_id : (inv?.invoice_id || undefined),
      sage_invoice_number: inv?.sage ? inv.invoice_number : undefined, note_date: date, reason, return_to_stock: toStock, lines,
    }), "Return recorded - the customer's account and stock are updated");
    setBusy(false);
    if (ok) { qc.invalidateQueries({ queryKey: ["books"] }); onClose(); }
  };
  return (
    <DetailSheet open={open} onOpenChange={(o) => !o && onClose()} title="Return inward / credit note"
                 description="Choose the invoice the goods were sold on. The credit reduces that invoice and the customer's balance; returned goods go back into their batch."
                 footer={<div className="flex w-full items-center justify-between"><span className="text-sm">Credit <strong>{naira(total)}</strong></span>
                   <Button disabled={busy || !customer || !reason || total <= 0} onClick={submit}>{busy ? "Posting…" : "Post return"}</Button></div>}>
      <div className="space-y-3">
        <CustomerPick value={customer} onChange={(c) => { setCustomer(c); setInv(null); setBack({}); }} />
        {customer && !inv && (
          <div className="space-y-2">
            <div className="flex items-end justify-between gap-2"><Label className="text-xs">Which invoice were the goods sold on?</Label>
              <Input className="h-8 w-48 text-xs" placeholder="Invoice number" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
            {isLoading && <Loading />}
            <div className="max-h-64 overflow-y-auto rounded border">
              {(invs ?? []).map((i) => (
                <button key={`${i.sage}-${i.invoice_number}`} type="button" className="flex w-full items-center justify-between border-b px-3 py-1.5 text-left text-xs hover:bg-accent"
                        onClick={() => { setInv(i); setBack({}); }}>
                  <span><span className="font-mono font-medium">{i.invoice_number}</span> · {fmtDate(i.invoice_date)} · {i.lines.length} item(s)</span>
                  <span>{naira(i.total)}{i.balance != null && Number(i.balance) > 0 ? <span className="ml-2 text-amber-700">{naira(i.balance)} open</span> : ""}</span>
                </button>
              ))}
              {invs && invs.length === 0 && <div className="p-2 text-xs text-muted-foreground">No invoices found.</div>}
            </div>
            <button type="button" className="text-xs text-muted-foreground underline" onClick={() => setInv({ manual: true, lines: [] })}>No invoice - enter the items by hand</button>
          </div>
        )}
        {inv && !inv.manual && (
          <div className="space-y-2 rounded-lg border p-2">
            <div className="flex items-center justify-between text-xs"><span>Invoice <strong className="font-mono">{inv.invoice_number}</strong> · {fmtDate(inv.invoice_date)}</span>
              <button type="button" className="text-muted-foreground underline" onClick={() => setInv(null)}>choose another</button></div>
            <Table>
              <TableHeader><TableRow><TableHead>Item</TableHead><TableHead>Batch</TableHead><TableHead className="text-right">Sold</TableHead><TableHead className="text-right">Price</TableHead><TableHead className="w-24">Returned</TableHead></TableRow></TableHeader>
              <TableBody>{invLines.map((l, k) => (
                <TableRow key={k}><TableCell className="text-xs">{l.description}<div className="text-[11px] text-muted-foreground">{l.sku}</div></TableCell>
                  <TableCell className="text-xs">{l.batch_number ?? "—"}</TableCell><TableCell className="text-right text-xs">{num(l.quantity)}</TableCell>
                  <TableCell className="text-right text-xs">{naira(l.unit_price)}</TableCell>
                  <TableCell><Input className="h-7" type="number" min={0} max={Number(l.quantity)} value={back[k] ?? ""} onChange={(e) => setBack({ ...back, [k]: e.target.value })} /></TableCell></TableRow>
              ))}</TableBody>
            </Table>
          </div>
        )}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1"><Label className="text-xs">Date</Label><Input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></div>
          <div className="space-y-1"><Label className="text-xs">Reason</Label><Input placeholder="e.g. Ordered 3, delivered 5 - 2 returned" value={reason} onChange={(e) => setReason(e.target.value)} /></div>
        </div>
        <div className="flex items-center gap-2"><Switch checked={toStock} onCheckedChange={setToStock} /><span className="text-sm">Goods returned to stock</span></div>
        {inv?.manual && (<>
          {L.lines.map((l, i) => (
            <div key={i} className="grid grid-cols-[1fr_80px_110px_110px_32px] items-end gap-2">
              <ProductPick label={i === 0 ? "Product" : undefined} value={l.product} onChange={(p) => L.update(i, { product: p })} />
              <Input className="h-9" type="number" placeholder="Qty" value={l.quantity} onChange={(e) => L.update(i, { quantity: e.target.value })} />
              <Input className="h-9" type="number" placeholder="Unit price" value={l.unit_price} onChange={(e) => L.update(i, { unit_price: e.target.value })} />
              <Input className="h-9" placeholder="Batch" value={l.batch_number} onChange={(e) => L.update(i, { batch_number: e.target.value })} />
              <Button size="icon" variant="ghost" onClick={() => L.remove(i)}><Trash2 className="h-4 w-4" /></Button>
            </div>
          ))}
          <Button size="sm" variant="outline" onClick={L.add}><Plus className="mr-1 h-4 w-4" />Add line</Button>
        </>)}
      </div>
    </DetailSheet>
  );
}

function CreditNoteDetail({ id, onClose }: { id: string | null; onClose: () => void }) {
  const { data: n } = useBooks<Dict>(["creditnote", id], `/sales/credit-notes/${id}`, undefined, !!id);
  return (
    <DetailSheet open={!!id} onOpenChange={(o) => !o && onClose()} title={n ? `Credit note ${n.credit_note_number}` : "Credit note"} description={n?.customer_name}>
      {id && <RecordView t={{ type: "creditnote", id }} />}
    </DetailSheet>
  );
}

// ---------------------------------------------------------------------------
// Aged receivables & statement
// ---------------------------------------------------------------------------

function AgedReceivables() {
  const [asOf, setAsOf] = useState(today());
  const [basis, setBasis] = useState("due_date");
  const [open, setOpen] = useState<Dict | null>(null);
  const [find, setFind] = useState("");
  const { data: raw, isLoading, error } = useBooks<any>(["aged-ar", asOf, basis], "/reports/aged-receivables", { as_of: asOf, basis });
  const data = raw && find ? { ...raw, rows: raw.rows.filter((r: Dict) => `${r.customer_name} ${r.customer_code} ${r.items.map((i: Dict) => i.doc_number).join(" ")}`.toLowerCase().includes(find.toLowerCase())) } : raw;
  return (
    <Section title="Aged receivables" actions={<CsvButton filename={`aged-receivables-${asOf}.csv`} rows={data?.rows.flatMap((r: Dict) => [
      ...r.items.map((it: Dict) => ({ "Customer ID": r.customer_code, Customer: r.customer_name, "Invoice/CM #": it.doc_number,
        ...Object.fromEntries(data.buckets.map((b: string) => [b, b === it.bucket ? it.open_amount : ""])), "Amount Due": it.open_amount })),
      { "Customer ID": r.customer_code, Customer: r.customer_name, "Invoice/CM #": "", ...Object.fromEntries(data.buckets.map((b: string, i: number) => [b, r.buckets[i]])), "Amount Due": r.total },
    ])} />}>
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <DateRange single to={asOf} onChange={(_, t) => setAsOf(t)} />
        <div className="space-y-1"><Label className="text-xs">Age by</Label><select className="h-9 rounded-md border bg-background px-2 text-sm" value={basis} onChange={(e) => setBasis(e.target.value)}><option value="due_date">Due date (as Sage)</option><option value="invoice_date">Invoice date</option></select></div>
        <div className="space-y-1"><Label className="text-xs">Find</Label><Input className="h-9 w-64" placeholder="Customer or invoice number" value={find} onChange={(e) => setFind(e.target.value)} /></div>
      </div>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (
        <Table>
          <TableHeader><TableRow><TableHead>Customer</TableHead>{data.buckets.map((b: string) => <TableHead key={b} className="text-right">{b}</TableHead>)}<TableHead className="text-right">Total</TableHead><TableHead className="text-right">Limit</TableHead></TableRow></TableHeader>
          <TableBody>
            {data.rows.map((r: Dict) => (
              <TableRow key={r.customer_id} className="cursor-pointer hover:bg-muted/50" onClick={() => setOpen(r)}>
                <TableCell className="max-w-[240px] truncate"><DrillLink to={{ type: "customer", id: String(r.customer_id ?? ""), label: r.customer_name }}>{r.customer_name}</DrillLink></TableCell>
                {r.buckets.map((v: string, i: number) => <TableCell key={i} className="text-right"><Amount value={v} blankZero /></TableCell>)}
                <TableCell className="text-right font-semibold"><Amount value={r.total} /></TableCell>
                <TableCell className={`text-right text-xs ${r.credit_limit && Number(r.total) > Number(r.credit_limit) ? "text-red-600" : "text-muted-foreground"}`}>{r.credit_limit ? naira(r.credit_limit) : ""}</TableCell>
              </TableRow>
            ))}
            <TableRow className="font-semibold"><TableCell>Total</TableCell>{data.bucket_totals.map((v: string, i: number) => <TableCell key={i} className="text-right"><Amount value={v} /></TableCell>)}<TableCell className="text-right"><Amount value={data.total} /></TableCell><TableCell /></TableRow>
          </TableBody>
        </Table>
      )}
      <DetailSheet open={!!open} onOpenChange={(o) => !o && setOpen(null)} title={open?.customer_name ?? ""} description="Open items making up this balance">
        {open && (
          <Table>
            <TableHeader><TableRow><TableHead>Document</TableHead><TableHead>Due</TableHead><TableHead>Bucket</TableHead><TableHead className="text-right">Open</TableHead></TableRow></TableHeader>
            <TableBody>{open.items.map((it: Dict, i: number) => (
              <TableRow key={i}><TableCell className="font-mono text-xs"><DrillLink to={{ type: it.doc_type === "INVOICE" ? "invoice" : it.doc_type === "RECEIPT" ? "receipt" : "creditnote", id: it.doc_id, label: it.doc_number }}>{it.doc_number}</DrillLink><div className="text-[10px] text-muted-foreground">{it.doc_type.replace("_", " ").toLowerCase()}</div></TableCell><TableCell className="text-xs">{fmtDate(it.due_date)}</TableCell><TableCell className="text-xs">{it.bucket}</TableCell><TableCell className="text-right"><Amount value={it.open_amount} /></TableCell></TableRow>
            ))}</TableBody>
          </Table>
        )}
      </DetailSheet>
    </Section>
  );
}

/** The record behind a ledger row: a sale opens the invoice (what was bought, how it was paid), a
 *  receipt opens the payment (which invoices it settled). */
export function partyRowTarget(r: Dict, partyName?: string): DrillTarget | null {
  if (r.source === "ace" && r.link && r.doc_id) return { type: r.link, id: r.doc_id, label: r.trans_no };
  if (r.type === "SJ" && r.trans_no) return { type: "sageinvoice", id: r.trans_no, label: r.trans_no };
  if (r.type === "CRJ") return { type: "sagereceipt", id: `${r.date}|${r.trans_no ?? ""}|${partyName ?? r.party ?? ""}`, label: r.trans_no };
  if (r.type === "PJ" && r.trans_no) return { type: "sagebill", id: `${r.trans_no}|${r.party_id ?? ""}`, label: r.trans_no };
  if (r.type) return { type: "sagetxn", id: `${r.date}|${r.type}|${r.trans_no ?? ""}`, label: r.trans_no };
  return null;
}

function CustomerStatement() {
  const [sp] = useSearchParams();
  const [customer, setCustomer] = useState<Dict | null>(null);
  const [range, setRange] = useState({ from: yearStart(), to: today() });
  const { data: preset } = useBooks<Dict>(["cust-preset", sp.get("customer")], `/customers/${sp.get("customer")}/overview`, undefined, !!sp.get("customer") && !customer);
  useEffect(() => { if (preset?.customer && !customer) setCustomer(preset.customer); }, [preset]);
  const { data, isLoading, error } = useBooks<any>(["statement", customer?.id, range], `/reports/customer-statement/${customer?.id}`, range, !!customer);
  const csv = data?.rows.map((r: Dict) => ({ "Customer ID": data.customer?.customer_code, Customer: data.customer?.name, Date: r.date, "Trans No": r.trans_no,
    Type: r.type, "Debit Amt": Number(r.debit) || "", "Credit Amt": Number(r.credit) || "", Balance: r.balance }));
  return (
    <Section title="Customer ledger / statement" actions={<>
      <CsvButton filename={`statement-${customer?.name ?? ""}-${range.from}-${range.to}.csv`} rows={csv} />
      <Button size="sm" variant="outline" disabled={!data} onClick={() => window.print()}>Print</Button></>}>
      <div className="mb-3 grid gap-3 md:grid-cols-[1fr_auto]">
        <CustomerPick value={customer} onChange={setCustomer} />
        <DateRange from={range.from} to={range.to} onChange={(f, t) => setRange({ from: f ?? range.from, to: t })} />
      </div>
      {!customer && <Empty>Choose a customer to see every invoice and payment, as far back as the records go.</Empty>}
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (
        <div className="space-y-3 text-sm">
          <div className="flex flex-wrap justify-between gap-2 text-xs text-muted-foreground"><span>{data.customer?.name} · {data.customer?.customer_code}</span>
            <span>Credit limit {data.customer?.credit_limit ? naira(data.customer.credit_limit) : "none"}</span></div>
          <Table>
            <TableHeader><TableRow><TableHead>Date</TableHead><TableHead>Trans No</TableHead><TableHead>Type</TableHead><TableHead className="text-right">Debit Amt</TableHead><TableHead className="text-right">Credit Amt</TableHead><TableHead className="text-right">Balance</TableHead></TableRow></TableHeader>
            <TableBody>
              <TableRow className="bg-muted/40"><TableCell className="whitespace-nowrap">{fmtDate(range.from)}</TableCell><TableCell className="text-xs font-medium">Balance Fwd</TableCell><TableCell /><TableCell /><TableCell />
                <TableCell className="text-right font-medium"><Amount value={data.opening_balance} /></TableCell></TableRow>
              {data.rows.map((r: Dict, i: number) => {
                const t = partyRowTarget(r, data.customer?.name);
                return (
                  <TableRow key={i}><TableCell className="whitespace-nowrap">{fmtDate(r.date)}</TableCell>
                    <TableCell className="font-mono text-xs">{t ? <DrillLink to={t}>{r.trans_no ?? "—"}</DrillLink> : r.trans_no}</TableCell>
                    <TableCell className="text-xs">{r.type}</TableCell>
                    <TableCell className="text-right"><Amount value={r.debit} blankZero /></TableCell><TableCell className="text-right"><Amount value={r.credit} blankZero /></TableCell>
                    <TableCell className="text-right"><Amount value={r.balance} /></TableCell></TableRow>
                );
              })}
              <TableRow className="font-semibold"><TableCell colSpan={3}>Totals · balance at {fmtDate(range.to)}</TableCell>
                <TableCell className="text-right"><Amount value={data.total_debit} /></TableCell><TableCell className="text-right"><Amount value={data.total_credit} /></TableCell>
                <TableCell className="text-right"><Amount value={data.closing_balance} /></TableCell></TableRow>
            </TableBody>
          </Table>
          <p className="text-xs text-muted-foreground">SJ = sales invoice / credit, CRJ = payment received. Click a Trans No to see what was bought or which invoices a payment settled.</p>
          <div className="grid grid-cols-5 gap-2 text-xs">{data.aging.buckets.map((b: string, i: number) => <div key={b} className="rounded border p-2"><div className="text-muted-foreground">{b} days</div><Amount value={data.aging.amounts[i]} /></div>)}</div>
        </div>
      )}
    </Section>
  );
}
