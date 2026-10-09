import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { DrillLink } from "@/components/books/kit";
import { DrillTarget, historyTarget, useDrill } from "@/components/books/drill-context";
import { PartyBalances, SageTag } from "@/components/books/kit";
import { AlertTriangle, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { FilterBar } from "@/components/workspace/FilterBar";
import { BooksShell } from "@/components/books/BooksShell";
import { RecordView } from "@/components/books/lineage";
import {
  AccountPick, act, Amount, BankSelect, CsvButton, DateRange, Empty, ErrorNote, JournalSheet, Loading, ProductPick,
  Section, StatusBadge, SupplierPick, useBooks, useLines,
} from "@/components/books/kit";
import { books, BooksError, Dict, fmtDate, naira, newIdemKey, num, today, yearStart } from "@/lib/books-api";
import { askConfirm, askText } from "@/lib/ask";
import { PaymentWindow } from "@/components/books/payment-window";

export default function BooksPurchases() {
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState(params.get("tab") ?? "bills");
  const open = (k: string, v: string | null) => { const p = new URLSearchParams(params); v ? p.set(k, v) : p.delete(k); setParams(p, { replace: true }); };
  return (
    <BooksShell title="Purchases & Payables"
                actions={<>
                  <Button size="sm" onClick={() => open("new", "bill")}><Plus className="mr-1 h-4 w-4" />Supplier bill</Button>
                  <Button size="sm" variant="outline" onClick={() => open("new", "payment")}>Pay supplier</Button>
                  <Button size="sm" variant="outline" onClick={() => open("new", "debitnote")}>Return to supplier</Button>
                  <Button size="sm" variant="outline" title="Pay someone who is not a supplier (e.g. Mr X for furniture) and choose the account it goes to"
                          onClick={() => open("new", "oneoff")}>One-off payment</Button>
                </>}>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="flex-wrap">
          <TabsTrigger value="bills">Bills</TabsTrigger>
          <TabsTrigger value="payments">Payments</TabsTrigger>
          <TabsTrigger value="debit">Returns / debit notes</TabsTrigger>
          <TabsTrigger value="aging">Aged payables</TabsTrigger>
          <TabsTrigger value="statement">Supplier statement</TabsTrigger>
        </TabsList>
        <TabsContent value="bills"><BillList onOpen={(id) => open("bill", id)} /></TabsContent>
        <TabsContent value="payments"><PaymentList onOpen={(id) => open("payment", id)} /></TabsContent>
        <TabsContent value="debit"><DebitNoteList onOpen={(id) => open("debitnote", id)} onNew={() => open("new", "debitnote")} /></TabsContent>
        <TabsContent value="aging"><AgedPayables /></TabsContent>
        <TabsContent value="statement"><SupplierStatement /></TabsContent>
      </Tabs>
      <BillForm open={params.get("new") === "bill"} onClose={(id) => { open("new", null); if (id) open("bill", id); }} />
      <PaymentWindow open={params.get("new") === "payment" || params.get("new") === "oneoff"} oneOff={params.get("new") === "oneoff"} onClose={() => open("new", null)} />
      <DebitNoteForm open={params.get("new") === "debitnote"} onClose={() => open("new", null)} />
      <DocDetail kind="bill" id={params.get("bill")} onClose={() => open("bill", null)} />
      <DocDetail kind="payment" id={params.get("payment")} onClose={() => open("payment", null)} />
      <DocDetail kind="debitnote" id={params.get("debitnote")} onClose={() => open("debitnote", null)} />
    </BooksShell>
  );
}

function BillList({ onOpen }: { onOpen: (id: string) => void }) {
  const drill = useDrill();
  const [search, setSearch] = useState("");
  const [openOnly, setOpenOnly] = useState("");
  const [range, setRange] = useState({ from: yearStart(), to: today() });
  const { data, isLoading, error } = useBooks<any>(["bills", search, openOnly, range], "/payables/bills",
    { search, open_only: openOnly === "open", from: range.from, to: range.to, limit: 300 });
  return (
    <Section title={`Supplier bills${data ? ` (${data.total})` : ""}`} actions={<CsvButton filename="bills.csv" rows={data?.items} />}>
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <div className="flex-1"><FilterBar search={{ value: search, onChange: setSearch, placeholder: "Bill no., supplier, supplier invoice no." }}
          selects={[{ label: "Show", value: openOnly, onChange: setOpenOnly, options: [{ value: "open", label: "Unpaid only" }] }]} /></div>
        <DateRange from={range.from} to={range.to} onChange={(f, t) => setRange({ from: f ?? range.from, to: t })} />
      </div>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (data.items.length === 0 ? <Empty>No bills in this period.</Empty> : (
        <Table>
          <TableHeader><TableRow><TableHead>Bill</TableHead><TableHead>Supplier inv.</TableHead><TableHead>Date</TableHead><TableHead>Supplier</TableHead><TableHead>Due</TableHead><TableHead className="text-right">Total</TableHead><TableHead className="text-right">Balance</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
          <TableBody>{data.items.map((b: Dict) => (
            <TableRow key={b.id ?? `s:${b.bill_date}:${b.bill_number}:${b.supplier_id}`} className="cursor-pointer hover:bg-muted/50"
                      onClick={() => (b.id ? onOpen(b.id) : drill?.open(historyTarget("bill", b)))}>
              <TableCell className="font-mono text-xs">{b.bill_number}{b.is_opening && <span className="ml-1 text-[10px] text-muted-foreground">opening</span>}{b.source === "SAGE" && <SageTag />}</TableCell>
              <TableCell className="text-xs">{b.supplier_invoice_number}</TableCell>
              <TableCell className="whitespace-nowrap">{fmtDate(b.bill_date)}</TableCell>
              <TableCell className="max-w-[220px] truncate"><DrillLink to={{ type: "supplier", id: String(b.supplier_id ?? ""), label: b.supplier_name }}>{b.supplier_name}</DrillLink></TableCell>
              <TableCell className={b.due_date < today() && Number(b.balance_due) > 0 ? "text-red-600" : ""}>{fmtDate(b.due_date)}</TableCell>
              <TableCell className="text-right"><Amount value={b.total} /></TableCell>
              <TableCell className="text-right"><Amount value={b.balance_due} /></TableCell>
              <TableCell><StatusBadge status={b.status} /></TableCell>
            </TableRow>
          ))}</TableBody>
        </Table>
      ))}
    </Section>
  );
}

function PaymentList({ onOpen }: { onOpen: (id: string) => void }) {
  const drill = useDrill();
  const [search, setSearch] = useState("");
  const [range, setRange] = useState({ from: yearStart(), to: today() });
  const { data, isLoading, error } = useBooks<any>(["spayments", search, range], "/payables/payments", { search, from: range.from, to: range.to, limit: 300 });
  return (
    <Section title={`Supplier payments${data ? ` (${data.total})` : ""}`} actions={<CsvButton filename="supplier-payments.csv" rows={data?.items} />}>
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <div className="flex-1"><FilterBar search={{ value: search, onChange: setSearch, placeholder: "Payment no., supplier, cheque ref" }} /></div>
        <DateRange from={range.from} to={range.to} onChange={(f, t) => setRange({ from: f ?? range.from, to: t })} />
      </div>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (data.items.length === 0 ? <Empty>No payments in this period.</Empty> : (
        <Table>
          <TableHeader><TableRow><TableHead>Payment</TableHead><TableHead>Date</TableHead><TableHead>Supplier</TableHead><TableHead>Method</TableHead><TableHead>From</TableHead><TableHead className="text-right">Paid</TableHead><TableHead className="text-right">WHT</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
          <TableBody>{data.items.map((p: Dict) => (
            <TableRow key={p.id ?? `s:${p.payment_date}:${p.payment_number}:${p.supplier_id}`} className="cursor-pointer hover:bg-muted/50"
                      onClick={() => (p.id ? onOpen(p.id) : drill?.open(historyTarget("payment", p)))}>
              <TableCell className="font-mono text-xs">{p.payment_number}{p.source === "SAGE" && <SageTag />}</TableCell><TableCell className="whitespace-nowrap">{fmtDate(p.payment_date)}</TableCell>
              <TableCell className="max-w-[200px] truncate"><DrillLink to={{ type: "supplier", id: String(p.supplier_id ?? ""), label: p.supplier_name }}>{p.supplier_name}</DrillLink></TableCell><TableCell className="text-xs">{p.method ? `${p.method.toLowerCase()} ${p.reference ?? ""}` : p.reference}</TableCell>
              <TableCell className="text-xs">{p.bank_account_name}</TableCell><TableCell className="text-right"><Amount value={p.amount} /></TableCell>
              <TableCell className="text-right"><Amount value={p.wht_amount} blankZero /></TableCell><TableCell><StatusBadge status={p.status} /></TableCell>
            </TableRow>
          ))}</TableBody>
        </Table>
      ))}
    </Section>
  );
}

const DN_KIND: Record<string, string> = { RETURN: "Return", BROUGHT_FORWARD: "Credit from Sage", SAGE_CREDIT: "Sage credit memo" };

/** Returns outward (goods back to the supplier: stock out of its batch, what we owe goes down,
 *  against the supplier invoice they came on) and every supplier credit - with how much of each
 *  credit is still unused, so it can be applied to their next bill. */
function DebitNoteList({ onOpen, onNew }: { onOpen: (id: string) => void; onNew: () => void }) {
  const drill = useDrill();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [supplier, setSupplier] = useState<Dict | null>(null);
  const [range, setRange] = useState({ from: "2019-01-01", to: today() });
  const { data, isLoading, error } = useBooks<any>(["debitnotes", search, status, supplier?.id, range], "/payables/debit-notes",
    { limit: 300, search: search || undefined, status: status || undefined, supplier_id: supplier?.id, from: range.from, to: range.to });
  const sm = data?.summary ?? {};
  return (
    <Section title={`Returns outward & supplier credits${data ? ` (${data.total})` : ""}`}
             actions={<><Button size="sm" onClick={onNew}><Plus className="mr-1 h-4 w-4" />Return to supplier</Button><CsvButton filename="supplier-returns.csv" rows={data?.items} /></>}>
      <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-5">
        {[["Returns posted", `${num(sm.returns)} · ${naira(sm.returned_value ?? 0)}`], ["Units returned", num(sm.units_returned)],
          ["Unused supplier credit", naira(sm.unused_credit ?? 0)], ["Credits not yet used", num(sm.with_unused)], ["Credit brought from Sage", naira(sm.brought_forward ?? 0)]].map(([k, v]) => (
          <div key={k as string} className="rounded-lg border px-3 py-2"><div className="text-[11px] uppercase text-muted-foreground">{k}</div><div className="text-sm font-semibold">{v}</div></div>))}
      </div>
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <div className="flex-1"><FilterBar search={{ value: search, onChange: setSearch, placeholder: "Number, supplier, invoice, reason" }}
          selects={[{ label: "Show", value: status, onChange: setStatus, options: [{ value: "returns", label: "Returns of goods" }, { value: "unused", label: "Credit not yet used" },
            { value: "used", label: "Fully used" }, { value: "brought_forward", label: "Credits from Sage (brought forward)" }, { value: "sage", label: "Sage credit memos" }] }]} /></div>
        <div className="w-64"><SupplierPick value={supplier} onChange={setSupplier} /></div>
        <DateRange from={range.from} to={range.to} onChange={(f, t) => setRange({ from: f ?? range.from, to: t })} />
      </div>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (data.items.length === 0 ? <Empty>No supplier returns or credits for this filter. Use "Return to supplier" to send goods back against the invoice they came on.</Empty> : (
        <Table>
          <TableHeader><TableRow><TableHead>Number</TableHead><TableHead>Date</TableHead><TableHead>Supplier</TableHead><TableHead>Kind</TableHead><TableHead>Goods</TableHead>
            <TableHead>Against invoice</TableHead><TableHead>Reason</TableHead><TableHead className="text-right">Credit</TableHead><TableHead className="text-right">Unused</TableHead></TableRow></TableHeader>
          <TableBody>{data.items.map((d: Dict) => (
            <TableRow key={d.id ?? `s:${d.note_date}:${d.debit_note_number}:${d.supplier_id}`} className="cursor-pointer hover:bg-muted/50"
                      onClick={() => (d.id ? onOpen(d.id) : drill?.open({ type: "sagetxn", id: `${d.note_date}|PJ|${d.debit_note_number}`, label: d.debit_note_number }))}>
              <TableCell className="max-w-[180px] truncate font-mono text-xs" title={d.debit_note_number}>{d.debit_note_number}{d.source === "SAGE" && <SageTag />}</TableCell>
              <TableCell className="whitespace-nowrap text-xs">{fmtDate(d.note_date)}</TableCell>
              <TableCell className="max-w-[180px] truncate"><DrillLink to={d.supplier_id ? { type: "supplier", id: String(d.supplier_id), label: d.supplier_name } : null}>{d.supplier_name}</DrillLink></TableCell>
              <TableCell className="text-xs">{DN_KIND[d.kind] ?? d.kind}{d.recall_number && <div><DrillLink to={{ type: "recall", id: String(d.recall_id), label: d.recall_number }}>recall {d.recall_number}</DrillLink></div>}</TableCell>
              <TableCell className="max-w-[160px] truncate text-xs" title={d.skus ?? ""}>{Number(d.units) > 0 ? `${num(d.units)} unit(s) · ${d.skus}` : "—"}</TableCell>
              <TableCell className="font-mono text-xs">{d.against ? <DrillLink to={d.bill_id ? { type: "bill", id: String(d.bill_id), label: d.against } : { type: "sagebill", id: `${d.against}|${d.supplier_id ?? ""}`, label: d.against }}>{d.against}</DrillLink> : "—"}</TableCell>
              <TableCell className="max-w-[200px] truncate text-xs" title={d.reason}>{d.reason}</TableCell>
              <TableCell className="text-right"><Amount value={d.total} /></TableCell>
              <TableCell className={`text-right ${Number(d.unused) > 0 ? "font-semibold text-emerald-700" : ""}`}><Amount value={d.unused} blankZero /></TableCell>
            </TableRow>
          ))}</TableBody>
        </Table>
      ))}
    </Section>
  );
}

type BLine = { line_type: string; product: Dict | null; account: Dict | null; description: string; quantity: string; unit_cost: string; line_total: string; batch_number: string; expiry_date: string };
const blankBLine = (): BLine => ({ line_type: "ITEM", product: null, account: null, description: "", quantity: "", unit_cost: "", line_total: "", batch_number: "", expiry_date: "" });
const bLineTotal = (l: BLine) => (l.line_total ? Number(l.line_total) : Number(l.quantity || 0) * Number(l.unit_cost || 0));

function BillForm({ open, onClose }: { open: boolean; onClose: (id?: string) => void }) {
  const qc = useQueryClient();
  const [supplier, setSupplier] = useState<Dict | null>(null);
  const [f, setF] = useState({ supplier_invoice_number: "", bill_date: today(), due_date: "", notes: "" });
  const [busy, setBusy] = useState(false);
  const [idem] = useState(newIdemKey);
  const L = useLines<BLine>(blankBLine);
  useEffect(() => { if (!open) { setSupplier(null); L.reset(); setF({ supplier_invoice_number: "", bill_date: today(), due_date: "", notes: "" }); } }, [open]);
  const total = L.lines.reduce((s, l) => s + bLineTotal(l), 0);
  const submit = async () => {
    setBusy(true);
    const b = await act(() => books.post("/payables/bills", {
      supplier_id: supplier?.id, ...f, due_date: f.due_date || undefined,
      lines: L.lines.map((l) => ({ line_type: l.line_type, sku: l.product?.sku, account_id: l.account?.id, description: l.description || undefined,
        quantity: l.quantity || 1, unit_cost: l.unit_cost || 0, line_total: l.line_total || undefined, batch_number: l.batch_number || undefined,
        expiry_date: l.expiry_date || undefined })),
    }, idem), "Bill posted");
    setBusy(false);
    if (b) { qc.invalidateQueries({ queryKey: ["books"] }); onClose(b.id); }
  };
  return (
    <DetailSheet open={open} onOpenChange={(o) => !o && onClose()} title="Record supplier bill"
                 description="Stock lines are received into inventory (with batch & expiry) and owed to the supplier in one step."
                 footer={<div className="flex w-full items-center justify-between"><span className="text-sm">Total <strong>{naira(total)}</strong></span>
                   <Button disabled={busy || !supplier || !f.supplier_invoice_number || total <= 0} onClick={submit}>{busy ? "Posting…" : "Post bill"}</Button></div>}>
      <div className="space-y-3">
        <SupplierPick value={supplier} onChange={setSupplier} />
        <div className="grid grid-cols-3 gap-3">
          <div className="space-y-1"><Label className="text-xs">Supplier invoice no.</Label><Input value={f.supplier_invoice_number} onChange={(e) => setF({ ...f, supplier_invoice_number: e.target.value })} /></div>
          <div className="space-y-1"><Label className="text-xs">Invoice date</Label><Input type="date" value={f.bill_date} onChange={(e) => setF({ ...f, bill_date: e.target.value })} /></div>
          <div className="space-y-1"><Label className="text-xs">Due (default: supplier terms)</Label><Input type="date" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} /></div>
        </div>
        {L.lines.map((l, i) => (
          <div key={i} className="space-y-2 rounded-lg border p-2">
            <div className="flex items-center gap-2">
              <select className="h-8 rounded-md border bg-background px-2 text-xs" value={l.line_type} onChange={(e) => L.update(i, { line_type: e.target.value })}>
                <option value="ITEM">Stock received</option><option value="EXPENSE">Expense / service</option><option value="ASSET">Fixed asset</option>
              </select>
              <div className="flex-1">{l.line_type === "ITEM" ? <ProductPick value={l.product} onChange={(p) => L.update(i, { product: p })} />
                : <AccountPick value={l.account} onChange={(a) => L.update(i, { account: a })} accountType={l.line_type === "ASSET" ? "ASSET" : undefined} />}</div>
              <Button size="icon" variant="ghost" onClick={() => L.remove(i)}><Trash2 className="h-4 w-4" /></Button>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <Input className="h-8" type="number" placeholder="Qty" value={l.quantity} onChange={(e) => L.update(i, { quantity: e.target.value })} />
              <Input className="h-8" type="number" placeholder="Unit cost" value={l.unit_cost} onChange={(e) => L.update(i, { unit_cost: e.target.value })} />
              <Input className="h-8" type="number" placeholder="Line total (as on invoice)" value={l.line_total} onChange={(e) => L.update(i, { line_total: e.target.value })} />
            </div>
            {l.line_type === "ITEM" ? (
              <div className="grid grid-cols-2 gap-2">
                <Input className="h-8" placeholder="Batch / lot number" value={l.batch_number} onChange={(e) => L.update(i, { batch_number: e.target.value })} />
                <Input className="h-8" type="date" title="Expiry date" value={l.expiry_date} onChange={(e) => L.update(i, { expiry_date: e.target.value })} />
              </div>
            ) : <Input className="h-8" placeholder="Description" value={l.description} onChange={(e) => L.update(i, { description: e.target.value })} />}
            <div className="text-right text-xs text-muted-foreground">Line {naira(bLineTotal(l))}</div>
          </div>
        ))}
        <Button size="sm" variant="outline" onClick={L.add}><Plus className="mr-1 h-4 w-4" />Add line</Button>
        <div className="space-y-1"><Label className="text-xs">Notes</Label><Textarea rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></div>
      </div>
    </DetailSheet>
  );
}

const RETURN_REASONS = ["Expired / short expiry", "Damaged in transit", "Recalled by the manufacturer", "Wrong item delivered", "Excess quantity delivered",
  "Failed quality check", "Cold chain broken"];

function DebitNoteForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [supplier, setSupplier] = useState<Dict | null>(null);
  const [billId, setBillId] = useState("");
  const [reason, setReason] = useState("");
  const [date, setDate] = useState(today());
  const [busy, setBusy] = useState(false);
  const [bill, setBill] = useState<Dict | null>(null);
  const [back, setBack] = useState<Record<number, string>>({});
  const L = useLines<BLine>(blankBLine);
  const { data: bills } = useBooks<Dict[]>(["dn-returnable", supplier?.id], "/payables/returnable-bills", { supplier_id: supplier?.id }, !!supplier);
  useEffect(() => { if (!open) { setSupplier(null); setBillId(""); setReason(""); setBill(null); setBack({}); L.reset(); } }, [open]);
  void billId; void setBillId;
  const fromBill = (bill?.lines ?? []).map((l: Dict, k: number) => ({ ...l, qty: Number(back[k] || 0) })).filter((l: Dict) => l.qty > 0);
  const submit = async () => {
    setBusy(true);
    const lines = bill
      ? fromBill.map((l: Dict) => ({ line_type: "ITEM", sku: l.sku, quantity: l.qty, batch_id: l.return_batch_id || undefined,
                                     line_total: l.unit_cost ? (Number(l.unit_cost) * l.qty).toFixed(2) : undefined, description: l.description }))
      : L.lines.filter((l) => l.product).map((l) => ({ line_type: "ITEM", sku: l.product?.sku, quantity: l.quantity, batch_number: l.batch_number || undefined,
          line_total: l.line_total || undefined }));
    const ok = await act(() => books.post("/payables/debit-notes", { supplier_id: supplier?.id, bill_id: bill && !bill.sage ? bill.bill_id : (bill?.bill_id || undefined),
      sage_bill_number: bill?.sage ? bill.supplier_invoice_number : undefined, note_date: date, reason, lines }), "Return to supplier posted - stock and the supplier's account are updated");
    setBusy(false);
    if (ok) { qc.invalidateQueries({ queryKey: ["books"] }); onClose(); }
  };
  return (
    <DetailSheet open={open} onOpenChange={(o) => !o && onClose()} title="Return to supplier (return outward)"
                 description="Choose the supplier invoice the goods came on. The stock leaves its batch, and what you owe the supplier goes down by their credit."
                 footer={<Button disabled={busy || !supplier || !reason.trim() || (bill ? fromBill.length === 0 : false)} onClick={submit}>{busy ? "Posting…" : "Post return"}</Button>}>
      <div className="space-y-3">
        <SupplierPick value={supplier} onChange={(s) => { setSupplier(s); setBill(null); setBack({}); }} />
        {supplier && !bill && (
          <div className="space-y-1">
            <Label className="text-xs">Which supplier invoice did the goods come on?</Label>
            <div className="max-h-56 overflow-y-auto rounded border">
              {(bills ?? []).map((b) => (
                <button key={`${b.sage}-${b.supplier_invoice_number}-${b.bill_id ?? ""}`} type="button" className="flex w-full justify-between border-b px-3 py-1.5 text-left text-xs hover:bg-accent"
                        onClick={() => { setBill(b); setBack({}); }}>
                  <span><span className="font-mono font-medium">{b.supplier_invoice_number}</span> · {fmtDate(b.bill_date)} · {b.lines.length} item(s)</span><span>{naira(b.total)}</span>
                </button>
              ))}
              {bills && bills.length === 0 && <div className="p-2 text-xs text-muted-foreground">No invoices from this supplier.</div>}
            </div>
            <button type="button" className="text-xs text-muted-foreground underline" onClick={() => setBill(null)}>or enter the items by hand below</button>
          </div>
        )}
        {bill && (
          <div className="space-y-2 rounded-lg border p-2">
            <div className="flex justify-between text-xs"><span>Supplier invoice <strong className="font-mono">{bill.supplier_invoice_number}</strong> · {fmtDate(bill.bill_date)}</span>
              <button type="button" className="text-muted-foreground underline" onClick={() => setBill(null)}>choose another</button></div>
            <Table>
              <TableHeader><TableRow><TableHead>Item</TableHead><TableHead>Batch</TableHead><TableHead className="text-right">Bought</TableHead><TableHead className="text-right">Unit cost</TableHead><TableHead className="w-24">Returning</TableHead></TableRow></TableHeader>
              <TableBody>{(bill.lines ?? []).map((l: Dict, k: number) => (
                <TableRow key={k}><TableCell className="text-xs">{l.description}<div className="text-[11px] text-muted-foreground">{l.sku}</div></TableCell>
                  <TableCell className="text-xs">{l.batch_number ?? "—"}</TableCell><TableCell className="text-right text-xs">{num(l.quantity)}</TableCell>
                  <TableCell className="text-right text-xs">{naira(l.unit_cost)}</TableCell>
                  <TableCell><Input className="h-7" type="number" min={0} value={back[k] ?? ""} onChange={(e) => setBack({ ...back, [k]: e.target.value })} /></TableCell></TableRow>))}</TableBody>
            </Table>
          </div>
        )}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1"><Label className="text-xs">Date</Label><Input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></div>
          <div className="space-y-1"><Label className="text-xs">Reason</Label>
            <select className="h-9 w-full rounded-md border bg-background px-2 text-sm" value={RETURN_REASONS.includes(reason) ? reason : reason ? "Other" : ""}
                    onChange={(e) => setReason(e.target.value === "Other" ? " " : e.target.value)}>
              <option value="">Choose…</option>{RETURN_REASONS.map((r) => <option key={r} value={r}>{r}</option>)}<option value="Other">Other (type it)</option>
            </select>
            {reason && !RETURN_REASONS.includes(reason) && <Input className="mt-1" placeholder="Reason" value={reason.trim()} onChange={(e) => setReason(e.target.value || " ")} />}</div>
        </div>
        {!bill && L.lines.map((l, i) => (
          <div key={i} className="grid grid-cols-[1fr_70px_100px_120px_32px] items-end gap-2">
            <ProductPick label={i === 0 ? "Product" : undefined} value={l.product} onChange={(p) => L.update(i, { product: p })} />
            <Input className="h-9" type="number" placeholder="Qty" value={l.quantity} onChange={(e) => L.update(i, { quantity: e.target.value })} />
            <Input className="h-9" placeholder="Batch" value={l.batch_number} onChange={(e) => L.update(i, { batch_number: e.target.value })} />
            <Input className="h-9" type="number" placeholder="Credit ₦ (blank = cost)" value={l.line_total} onChange={(e) => L.update(i, { line_total: e.target.value })} />
            <Button size="icon" variant="ghost" onClick={() => L.remove(i)}><Trash2 className="h-4 w-4" /></Button>
          </div>
        ))}
        {!bill && <Button size="sm" variant="outline" onClick={L.add}><Plus className="mr-1 h-4 w-4" />Add line</Button>}
      </div>
    </DetailSheet>
  );
}

function DocDetail({ kind, id, onClose }: { kind: "bill" | "payment" | "debitnote"; id: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const path = { bill: "/payables/bills/", payment: "/payables/payments/", debitnote: "/payables/debit-notes/" }[kind] + id;
  const { data: d, refetch } = useBooks<Dict>([kind, id], path, undefined, !!id);
  const [v, setV] = useState(0);
  const voidIt = async () => {
    const reason = await askText(`Why is this ${kind === "bill" ? "bill" : "payment"} being voided?`);
    if (reason && (await act(() => books.post(`${path}/void`, { reason }), "Voided"))) { refetch(); setV((x) => x + 1); qc.invalidateQueries({ queryKey: ["books"] }); }
  };
  const title = d ? (kind === "bill" ? `Bill ${d.bill_number}` : kind === "payment" ? `Payment ${d.payment_number}` : `Debit note ${d.debit_note_number}`) : "";
  const canVoid = d && kind !== "debitnote" && d.status !== "VOID" && !d.is_opening;
  return (
    <DetailSheet open={!!id} onOpenChange={(o) => !o && onClose()} title={title} description={d?.supplier_name}
                 footer={canVoid ? <Button size="sm" variant="destructive" onClick={voidIt}>Void</Button> : undefined}>
      {id && <RecordView key={`${id}:${v}`} t={{ type: kind, id }} />}
    </DetailSheet>
  );
}

function Row({ k, v, bold }: { k: string; v: any; bold?: boolean }) {
  return <div className={`flex justify-between ${bold ? "font-semibold" : ""}`}><span className="text-muted-foreground">{k}</span><Amount value={v} /></div>;
}

function AgedPayables() {
  const [asOf, setAsOf] = useState(today());
  const { data, isLoading, error } = useBooks<any>(["aged-ap", asOf], "/reports/aged-payables", { as_of: asOf });
  return (
    <Section title="Aged payables (by due date)" actions={<CsvButton filename={`aged-payables-${asOf}.csv`} rows={data?.rows.map((r: Dict) => ({ supplier: r.supplier_name, ...Object.fromEntries(data.buckets.map((b: string, i: number) => [b, r.buckets[i]])), total: r.total }))} />}>
      <DateRange single to={asOf} onChange={(_, t) => setAsOf(t)} />
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (
        <Table className="mt-3">
          <TableHeader><TableRow><TableHead>Supplier</TableHead>{data.buckets.map((b: string) => <TableHead key={b} className="text-right">{b}</TableHead>)}<TableHead className="text-right">Total</TableHead></TableRow></TableHeader>
          <TableBody>
            {data.rows.map((r: Dict) => (
              <TableRow key={r.supplier_id}><TableCell><DrillLink to={{ type: "supplier", id: String(r.supplier_id), label: r.supplier_name }}>{r.supplier_name}</DrillLink></TableCell>{r.buckets.map((v: string, i: number) => <TableCell key={i} className="text-right"><Amount value={v} blankZero /></TableCell>)}<TableCell className="text-right font-semibold"><Amount value={r.total} /></TableCell></TableRow>
            ))}
            <TableRow className="font-semibold"><TableCell>Total</TableCell>{data.bucket_totals.map((v: string, i: number) => <TableCell key={i} className="text-right"><Amount value={v} /></TableCell>)}<TableCell className="text-right"><Amount value={data.total} /></TableCell></TableRow>
          </TableBody>
        </Table>
      )}
    </Section>
  );
}

function SupplierStatement() {
  const [supplier, setSupplier] = useState<Dict | null>(null);
  const [range, setRange] = useState({ from: yearStart(), to: today() });
  const { data, isLoading, error } = useBooks<any>(["sstatement", supplier?.id, range], `/reports/supplier-statement/${supplier?.id}`, range, !!supplier);
  return (
    <Section title="Vendor ledger / statement" actions={<CsvButton filename="supplier-statement.csv" rows={data?.rows.map((r: Dict) => ({ Date: r.date, "Trans No": r.trans_no, Type: r.type, Paid: r.paid ?? "", "Debit Amt": Number(r.debit) || "", "Credit Amt": Number(r.credit) || "", Balance: r.balance }))} />}>
      <div className="mb-3 grid gap-3 md:grid-cols-[1fr_auto]"><SupplierPick value={supplier} onChange={setSupplier} />
        <DateRange from={range.from} to={range.to} onChange={(f, t) => setRange({ from: f ?? range.from, to: t })} /></div>
      {!supplier && <PartyBalances kind="supplier" onPick={setSupplier} />}
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (
        <div className="space-y-2 text-sm">
          <div className="flex justify-between"><span>Brought forward</span><Amount value={data.opening_balance} bold /></div>
          <Table>
            <TableHeader><TableRow><TableHead>Date</TableHead><TableHead>Trans No</TableHead><TableHead>Type</TableHead><TableHead>Paid</TableHead><TableHead className="text-right">Debit Amt</TableHead><TableHead className="text-right">Credit Amt</TableHead><TableHead className="text-right">Balance</TableHead></TableRow></TableHeader>
            <TableBody>{data.rows.map((r: Dict, i: number) => {
              const t = r.source === "ace" && r.link ? { type: r.link, id: r.doc_id, label: r.trans_no } as DrillTarget
                : r.type === "PJ" ? { type: "sagebill", id: `${r.trans_no}|${supplier?.id ?? ""}`, label: r.trans_no } as DrillTarget
                : { type: "sagetxn", id: `${r.date}|${r.type ?? ""}|${r.trans_no ?? ""}`, label: r.trans_no } as DrillTarget;
              return (
              <TableRow key={i}><TableCell className="whitespace-nowrap">{fmtDate(r.date)}</TableCell><TableCell className="font-mono text-xs"><DrillLink to={t}>{r.trans_no ?? "—"}</DrillLink></TableCell>
                <TableCell className="text-xs">{r.type}</TableCell><TableCell className="text-xs">{r.paid ?? ""}</TableCell>
                <TableCell className="text-right"><Amount value={r.debit} blankZero /></TableCell><TableCell className="text-right"><Amount value={r.credit} blankZero /></TableCell><TableCell className="text-right"><Amount value={r.balance} /></TableCell></TableRow>
              );
            })}</TableBody>
          </Table>
          <div className="flex justify-between font-semibold"><span>Balance owed</span><Amount value={data.closing_balance} /></div>
        </div>
      )}
    </Section>
  );
}
