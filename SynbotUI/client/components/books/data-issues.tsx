/**
 * Data issues: what the Sage hand-over left unexplained (lots Sage sold below zero, Trial Balance
 * vs General Ledger differences, control accounts that disagree with their subledger), each with
 * its lineage and the resolutions the finance team can choose. Every decision is recorded and the
 * correction it posts (FIX-…) is traceable from the ledger back to here.
 */
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, PackageSearch, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { books, Dict, fmtDate, naira, num } from "@/lib/books-api";
import { useDrill } from "./drill-context";
import { act, Amount, DrillLink, Empty, ErrorNote, Loading, Section, Stat, StatusBadge, SupplierPick, useBooks } from "./kit";

const SEVERITY: Record<string, string> = {
  HIGH: "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300",
  MEDIUM: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300",
  LOW: "bg-slate-100 text-slate-700 dark:bg-slate-500/15 dark:text-slate-300",
};
const ACTION_LABEL: Record<string, string> = {
  record_receipt: "Recorded the missing receipt", move_from_lot: "Moved stock from another lot", physical_count: "Used a physical count",
  post_missing_entry: "Posted the missing entry", reduce_document: "Corrected the document", accept: "Accepted as it is", reopen: "Reopened",
};

function Severity({ s }: { s: string }) {
  return <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${SEVERITY[s] ?? ""}`}>{s.toLowerCase()}</span>;
}

/** The list (Close & Controls › Data issues). */
export function DataIssuesPanel() {
  const qc = useQueryClient();
  const drill = useDrill();
  const [status, setStatus] = useState("OPEN");
  const { data, isLoading, error, refetch } = useBooks<Dict>(["data-issues", status], "/data-exceptions", { status: status || undefined });
  const [busy, setBusy] = useState(false);
  const recheck = async () => {
    setBusy(true);
    await act(() => books.post("/data-exceptions/refresh", {}), "Checked again against the latest data");
    setBusy(false);
    qc.invalidateQueries({ queryKey: ["books"] });
    refetch();
  };
  const open = (data?.by_kind ?? []).filter((k: Dict) => k.status === "OPEN");
  const total = (kind: string) => open.find((k: Dict) => k.kind === kind);
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        What the Sage data leaves unexplained, found every time an export is brought in. Open one to see where it comes from
        (the invoices, bills and ledger lines behind it) and choose how to resolve it. Each decision is recorded with your
        reason; a correction is posted as a <span className="font-mono">FIX-</span> journal you can follow back to here.
      </p>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Open issues" value={num(data?.open ?? 0)} tone={data?.open ? "warn" : "good"} />
        <Stat label="Lots sold below zero" value={num(total("STOCK_SHORT_LOT")?.n ?? 0)} sub={total("STOCK_SHORT_LOT") ? naira(total("STOCK_SHORT_LOT").amount) : undefined}
              tone={total("STOCK_SHORT_LOT") ? "bad" : "good"} />
        <Stat label="Trial Balance vs ledger" value={total("TB_GL_DIFFERENCE") ? naira(total("TB_GL_DIFFERENCE").amount) : "agrees"} tone={total("TB_GL_DIFFERENCE") ? "warn" : "good"} />
        <Stat label="Control accounts" value={num((total("AR_CONTROL")?.n ?? 0) + (total("AP_CONTROL")?.n ?? 0) + (total("INVENTORY_CONTROL")?.n ?? 0))}
              sub="receivables · payables · inventory" tone={total("AR_CONTROL") || total("AP_CONTROL") || total("INVENTORY_CONTROL") ? "warn" : "good"} />
      </div>
      <Section title="Issues" actions={<>
        <select className="h-8 rounded-md border bg-background px-2 text-xs" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="OPEN">Open</option><option value="RESOLVED">Resolved</option><option value="ACCEPTED">Accepted</option><option value="">All</option>
        </select>
        <Button size="sm" variant="outline" onClick={recheck} disabled={busy}><RefreshCw className={`mr-1 h-4 w-4 ${busy ? "animate-spin" : ""}`} />Check again</Button>
      </>}>
        {isLoading && <Loading />}<ErrorNote error={error} />
        {data && (data.items.length === 0 ? <Empty>{status === "OPEN" ? "Nothing open - the data agrees." : "Nothing here."}</Empty> : (
          <Table>
            <TableHeader><TableRow><TableHead>Issue</TableHead><TableHead>Kind</TableHead><TableHead>Severity</TableHead>
              <TableHead className="text-right">Amount</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
            <TableBody>{data.items.map((x: Dict) => (
              <TableRow key={x.id} className="cursor-pointer" onClick={() => drill?.open({ type: "dataissue", id: x.id, label: x.key })}>
                <TableCell><div className="font-medium">{x.title}</div><div className="max-w-xl text-xs text-muted-foreground">{x.summary}</div></TableCell>
                <TableCell className="text-xs">{x.kind_label}</TableCell>
                <TableCell><Severity s={x.severity} /></TableCell>
                <TableCell className="text-right"><Amount value={x.amount} /></TableCell>
                <TableCell><StatusBadge status={x.status} />{x.resolution && x.status !== "OPEN" && <div className="text-[11px] text-muted-foreground">{(ACTION_LABEL[x.resolution.toLowerCase()] ?? x.resolution.replace(/_/g, " ").toLowerCase())}{x.resolved_by ? ` · ${x.resolved_by}` : ""}</div>}</TableCell>
              </TableRow>))}</TableBody>
          </Table>
        ))}
      </Section>
    </div>
  );
}

/** One issue: what was found, where it comes from, what was decided, and the ways to resolve it. */
export function DataIssueBody({ id }: { id: string }) {
  const excId = id.split(":")[0];
  const { data: x, isLoading, error, refetch } = useBooks<Dict>(["data-issue", excId], `/data-exceptions/${excId}`);
  if (isLoading) return <Loading />;
  if (error || !x) return <ErrorNote error={error ?? "Not found"} />;
  const d = x.detail ?? {};
  return (
    <div className="space-y-4 text-sm">
      <div className="flex flex-wrap items-center gap-2"><StatusBadge status={x.status} /><Severity s={x.severity} /><span className="text-xs text-muted-foreground">{x.kind_label} · found {fmtDate(x.first_seen)} · as at {fmtDate(x.as_of)}</span></div>
      <p>{x.summary}</p>
      {x.kind === "STOCK_SHORT_LOT" && <ShortLot x={x} d={d} />}
      {x.kind === "TB_GL_DIFFERENCE" && <TbGl x={x} d={d} />}
      {(x.kind === "AR_CONTROL" || x.kind === "AP_CONTROL") && <PartyControl x={x} d={d} />}
      {x.kind === "INVENTORY_CONTROL" && <InventoryControl d={d} />}
      {x.actions?.length > 0 && (
        <div><H>Decisions</H>
          <ul className="space-y-1 text-xs">{x.actions.map((a: Dict) => (
            <li key={a.id} className="rounded border p-2">
              <span className="font-medium">{ACTION_LABEL[a.action] ?? a.action}</span> · {a.created_by} · {new Date(a.created_at).toLocaleString("en-GB")}
              {a.journal_id && <> · <DrillLink to={{ type: "journal", id: a.journal_id, label: a.journal_number }}>{a.reference} ({a.journal_number})</DrillLink></>}
              {a.note && <div className="text-muted-foreground">“{a.note}”</div>}
              {a.stock_delta?.length > 0 && <div className="text-muted-foreground">Stock: {a.stock_delta.map((s: Dict) => `${s.sku} ${Number(s.quantity) > 0 ? "+" : ""}${num(s.quantity)}`).join(", ")}</div>}
            </li>))}</ul>
        </div>
      )}
      <Resolve x={x} onDone={refetch} />
    </div>
  );
}

const H = ({ children }: { children: React.ReactNode }) => <div className="mb-1 mt-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{children}</div>;

function ShortLot({ x, d }: { x: Dict; d: Dict }) {
  const L = x.lineage ?? {};
  const c = d.costing ?? {};
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 rounded-lg bg-muted/40 p-3 text-xs sm:grid-cols-4">
        <div>Product<div className="font-medium"><DrillLink to={{ type: "product", id: x.key, label: x.key }}>{d.name}</DrillLink></div></div>
        <div>Sage holds<div className="font-medium">{num(d.sage_quantity)} · {naira(d.sage_value)}</div></div>
        <div>Still short<div className="font-medium text-red-600">{num(d.deficit)}</div></div>
        <div>Sage's unit cost<div className="font-medium">{naira(d.sage_unit_cost)}</div></div>
        <div>Received in Sage<div className="font-medium">{num(c.received)}{c.last_receipt ? ` · last ${fmtDate(c.last_receipt)}` : ""}</div></div>
        <div>Sold in Sage<div className="font-medium">{num(c.sold)}</div></div>
        <div>Below zero since<div className="font-medium">{c.first_negative ? fmtDate(c.first_negative) : "—"}</div></div>
        <div>Corrected so far<div className="font-medium">{num(d.corrected_quantity)}</div></div>
      </div>
      {d.never_received && <div className="rounded-lg border border-amber-400 bg-amber-50 p-2 text-xs text-amber-900 dark:bg-amber-500/10 dark:text-amber-200">
        Sage has no receipt at all for this lot: every unit was sold without the goods being received in the system. Usually the supplier's
        invoice has not been entered yet; check the supplier bills below and the delivery notes.</div>}
      {L.other_lots?.length > 0 && (<><H>Other lots of {d.family} with stock (was it sold under the wrong lot?)</H>
        <Table><TableBody>{L.other_lots.map((l: Dict) => (
          <TableRow key={`${l.sku}${l.batch_id}`}><TableCell className="text-xs">{l.sku}</TableCell><TableCell className="text-xs">{l.batch_number} · exp {fmtDate(l.expiry_date)}</TableCell>
            <TableCell className="text-right text-xs">{num(l.available)} at {naira(l.unit_cost)}</TableCell></TableRow>))}</TableBody></Table></>)}
      <H>Supplier bills for {d.family} in Sage</H>
      {L.supplier_bills?.length ? (
        <Table><TableBody>{L.supplier_bills.map((b: Dict, i: number) => (
          <TableRow key={i}><TableCell className="text-xs">{fmtDate(b.bill_date)}</TableCell>
            <TableCell className="text-xs"><DrillLink to={{ type: "sagebill", id: `${b.bill_number}|${b.supplier_id ?? ""}`, label: b.bill_number }}>{b.bill_number}</DrillLink> · {b.supplier_name}</TableCell>
            <TableCell className="text-xs">{b.sku}</TableCell><TableCell className="text-right text-xs">{num(b.quantity)} · <Amount value={b.amount} /></TableCell></TableRow>))}</TableBody></Table>
      ) : <div className="text-xs text-muted-foreground">None.</div>}
      <H>Sales that took it below zero ({L.sales_below_zero?.length ?? 0})</H>
      <div className="max-h-72 overflow-auto">
        <Table><TableHeader><TableRow><TableHead>Date</TableHead><TableHead>Invoice</TableHead><TableHead>Customer</TableHead><TableHead className="text-right">Qty</TableHead><TableHead className="text-right">Amount</TableHead></TableRow></TableHeader>
          <TableBody>{(L.sales_below_zero ?? []).map((s: Dict, i: number) => (
            <TableRow key={i}><TableCell className="text-xs">{fmtDate(s.invoice_date)}</TableCell>
              <TableCell className="text-xs"><DrillLink to={{ type: "sageinvoice", id: s.invoice_number, label: s.invoice_number }}>{s.invoice_number}</DrillLink></TableCell>
              <TableCell className="text-xs">{s.customer_id ? <DrillLink to={{ type: "customer", id: String(s.customer_id), label: s.customer_name }}>{s.customer_name}</DrillLink> : s.customer_name}</TableCell>
              <TableCell className="text-right text-xs">{num(s.quantity)}</TableCell><TableCell className="text-right text-xs"><Amount value={s.amount} /></TableCell></TableRow>))}</TableBody></Table>
      </div>
    </div>
  );
}

function TbGl({ x, d }: { x: Dict; d: Dict }) {
  return (
    <div className="space-y-3">
      <H>Accounts that differ</H>
      <Table><TableHeader><TableRow><TableHead>Account</TableHead><TableHead className="text-right">Trial Balance</TableHead><TableHead className="text-right">General Ledger</TableHead><TableHead className="text-right">Difference</TableHead></TableRow></TableHeader>
        <TableBody>{(d.accounts ?? []).map((a: Dict) => (
          <TableRow key={a.code}><TableCell className="text-xs">{a.code} · {a.name}</TableCell><TableCell className="text-right"><Amount value={a.trial_balance} /></TableCell>
            <TableCell className="text-right"><Amount value={a.general_ledger} /></TableCell><TableCell className="text-right"><Amount value={a.difference} bold /></TableCell></TableRow>))}</TableBody></Table>
      {(x.lineage?.documents ?? []).map((doc: Dict) => (
        <div key={doc.reference} className="rounded-lg border p-3">
          <div className="mb-1 font-medium">
            {doc.kind === "SJ" ? <DrillLink to={{ type: "sageinvoice", id: doc.reference, label: doc.reference }}>Invoice {doc.reference}</DrillLink> : `${doc.kind} ${doc.reference}`}
            {doc.party ? ` · ${doc.party}` : ""} · {fmtDate(doc.date)} {doc.corrected && <StatusBadge status="POSTED" />}
          </div>
          <div className="text-xs text-muted-foreground">The journal Sage exported has these lines; the General Ledger export has a different amount on them - the document was most likely changed after the ledger was exported.</div>
          <Table><TableHeader><TableRow><TableHead>Account</TableHead><TableHead className="text-right">In the journal</TableHead><TableHead className="text-right">In the ledger</TableHead><TableHead className="text-right">Missing</TableHead></TableRow></TableHeader>
            <TableBody>{doc.lines.map((l: Dict) => (
              <TableRow key={l.account_code}><TableCell className="text-xs">{l.account_code}</TableCell><TableCell className="text-right"><Amount value={l.journal} /></TableCell>
                <TableCell className="text-right"><Amount value={l.ledger} /></TableCell><TableCell className="text-right"><Amount value={l.difference} bold /></TableCell></TableRow>))}</TableBody></Table>
          <details className="mt-1 text-xs"><summary className="cursor-pointer text-muted-foreground">Every line of {doc.reference} in the journal and in the ledger</summary>
            <div className="grid gap-2 lg:grid-cols-2">
              <Table><TableBody>{doc.journal_lines.map((l: Dict, i: number) => (<TableRow key={i}><TableCell className="text-[11px]">{l.account_code} {l.description}</TableCell><TableCell className="text-right text-[11px]"><Amount value={l.debit} blankZero /></TableCell><TableCell className="text-right text-[11px]"><Amount value={l.credit} blankZero /></TableCell></TableRow>))}</TableBody></Table>
              <Table><TableBody>{doc.ledger_lines.map((l: Dict, i: number) => (<TableRow key={i}><TableCell className="text-[11px]">{l.account_code} {l.jrnl} {l.description}</TableCell><TableCell className="text-right text-[11px]"><Amount value={l.debit} blankZero /></TableCell><TableCell className="text-right text-[11px]"><Amount value={l.credit} blankZero /></TableCell></TableRow>))}</TableBody></Table>
            </div></details>
        </div>
      ))}
    </div>
  );
}

function PartyControl({ x, d }: { x: Dict; d: Dict }) {
  const who = x.kind === "AR_CONTROL" ? "customer" : "supplier";
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 rounded-lg bg-muted/40 p-3 text-xs sm:grid-cols-4">
        <div>Control account {d.account}<div className="font-medium"><Amount value={d.control} /></div></div>
        <div>Open {who} items<div className="font-medium"><Amount value={d.open_items} /></div></div>
        <div>Difference<div className="font-medium"><Amount value={d.difference} bold /></div></div>
        {d.sage_ledgers_total && Number(d.sage_ledgers_total) !== 0 && <div>Sage's {who} ledgers<div className="font-medium"><Amount value={d.sage_ledgers_total} /></div></div>}
      </div>
      <H>{who === "customer" ? "Customers" : "Suppliers"} whose Sage ledger disagrees with the open items</H>
      {(d.parties ?? []).length === 0 ? <div className="text-xs text-muted-foreground">None found party by party: the difference sits in the control account itself (an entry posted to it without a {who}).</div> : (
        <Table><TableHeader><TableRow><TableHead>{who === "customer" ? "Customer" : "Supplier"}</TableHead><TableHead className="text-right">Sage ledger</TableHead><TableHead className="text-right">Open items</TableHead><TableHead className="text-right">Difference</TableHead></TableRow></TableHeader>
          <TableBody>{d.parties.map((p: Dict, i: number) => (
            <TableRow key={i}><TableCell className="text-xs">{p.party_id ? <DrillLink to={{ type: who, id: p.party_id, label: p.party }}>{p.party}</DrillLink> : p.party}
              {p.last_ledger_date && <div className="text-[11px] text-muted-foreground">last ledger entry {fmtDate(p.last_ledger_date)}</div>}</TableCell>
              <TableCell className="text-right"><Amount value={p.sage_ledger_balance} /></TableCell><TableCell className="text-right"><Amount value={p.open_items} /></TableCell>
              <TableCell className="text-right"><Amount value={p.difference} bold /></TableCell></TableRow>))}</TableBody></Table>)}
    </div>
  );
}

function InventoryControl({ d }: { d: Dict }) {
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 rounded-lg bg-muted/40 p-3 text-xs sm:grid-cols-4">
        <div>Inventory accounts<div className="font-medium"><Amount value={d.general_ledger} /></div></div>
        <div>Valued stock<div className="font-medium"><Amount value={d.stock} /></div></div>
        <div>Difference<div className="font-medium"><Amount value={d.difference} bold /></div></div>
        <div>From open short lots<div className="font-medium"><Amount value={d.explained_by_short_lots} /></div></div>
      </div>
      <Table><TableHeader><TableRow><TableHead>Account</TableHead><TableHead className="text-right">Ledger</TableHead><TableHead className="text-right">Stock</TableHead><TableHead className="text-right">Difference</TableHead><TableHead>Short lots</TableHead></TableRow></TableHeader>
        <TableBody>{(d.accounts ?? []).map((a: Dict) => (
          <TableRow key={a.code}><TableCell className="text-xs">{a.code} · {a.name}</TableCell><TableCell className="text-right"><Amount value={a.general_ledger} /></TableCell>
            <TableCell className="text-right"><Amount value={a.stock} /></TableCell><TableCell className="text-right"><Amount value={a.difference} bold /></TableCell>
            <TableCell className="text-xs">{a.short_lots.map((s: Dict) => <div key={s.id}><DrillLink to={{ type: "dataissue", id: s.id, label: s.sku }}>{s.sku}</DrillLink></div>)}</TableCell></TableRow>))}</TableBody></Table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Resolutions
// ---------------------------------------------------------------------------

function Resolve({ x, onDone }: { x: Dict; onDone: () => void }) {
  const qc = useQueryClient();
  const [action, setAction] = useState<string>("");
  const [f, setF] = useState<Dict>({});
  const [supplier, setSupplier] = useState<Dict | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setF((v) => ({ ...v, [k]: e.target.value }));
  const opt = (x.options ?? []).find((o: Dict) => o.action === action);
  const d = x.detail ?? {};
  const submit = async () => {
    setBusy(true);
    const payload = { ...f, supplier_id: supplier?.id };
    const ok = await act(() => books.post(`/data-exceptions/${x.id}/${action}`, payload), "Decision recorded");
    setBusy(false);
    if (ok) { setAction(""); setF({}); setSupplier(null); qc.invalidateQueries({ queryKey: ["books"] }); onDone(); }
  };
  if (!x.options?.length) return null;
  const docs = d.documents ?? [];
  return (
    <div className="space-y-3 rounded-lg border-2 border-primary/30 p-3">
      <div className="font-medium">{x.status === "OPEN" ? "How should this be resolved?" : "Change the decision"}</div>
      <div className="grid gap-2 sm:grid-cols-2">
        {x.options.map((o: Dict) => (
          <button key={o.action} type="button" onClick={() => { setAction(o.action); setF({}); }}
                  className={`rounded-lg border p-2 text-left text-xs hover:bg-muted/50 ${action === o.action ? "border-primary ring-1 ring-primary" : ""}`}>
            <div className="font-medium">{o.label}</div><div className="mt-0.5 text-muted-foreground">{o.effect}</div>
          </button>
        ))}
      </div>
      {opt && (
        <div className="space-y-2">
          {action === "record_receipt" && (
            <div className="grid gap-2 sm:grid-cols-3">
              <Field label={`Quantity received (at least ${num(d.deficit)} were sold)`}><Input type="number" value={f.quantity ?? ""} onChange={set("quantity")} /></Field>
              <Field label={`Unit cost (blank = Sage's ${naira(d.sage_unit_cost)})`}><Input type="number" value={f.unit_cost ?? ""} onChange={set("unit_cost")} /></Field>
              <Field label="Date received"><Input type="date" value={f.receipt_date ?? ""} onChange={set("receipt_date")} /></Field>
              <div className="sm:col-span-2"><SupplierPick label="Supplier" value={supplier} onChange={setSupplier} /></div>
              <Field label="Supplier invoice / delivery note no."><Input value={f.supplier_ref ?? ""} onChange={set("supplier_ref")} /></Field>
              <Field label="Batch number (blank = the Sage lot letter)"><Input value={f.batch_number ?? ""} onChange={set("batch_number")} /></Field>
              <Field label="Manufacture date"><Input type="date" value={f.manufacture_date ?? ""} onChange={set("manufacture_date")} /></Field>
              <Field label="Expiry date"><Input type="date" value={f.expiry_date ?? ""} onChange={set("expiry_date")} /></Field>
              {f.quantity && Number(f.quantity) >= Number(d.deficit) && <div className="text-xs text-emerald-700 sm:col-span-3">{num(Number(f.quantity) - Number(d.deficit))} will be available to sell after the {num(d.deficit)} already sold.</div>}
            </div>
          )}
          {action === "move_from_lot" && (
            <div className="grid gap-2 sm:grid-cols-2">
              <Field label="The lot the stock really came from">
                <select className="h-9 w-full rounded-md border bg-background px-2 text-sm" value={f.source_sku ?? ""} onChange={set("source_sku")}>
                  <option value="">Choose…</option>
                  {(x.lineage?.other_lots ?? []).map((l: Dict) => <option key={`${l.sku}${l.batch_id}`} value={l.sku}>{l.sku} · {num(l.available)} available · exp {fmtDate(l.expiry_date)}</option>)}
                </select>
              </Field>
              <Field label={`Quantity to move (short by ${num(d.deficit)})`}><Input type="number" value={f.quantity ?? ""} onChange={set("quantity")} /></Field>
              {(x.lineage?.other_lots ?? []).length === 0 && <div className="text-xs text-muted-foreground sm:col-span-2">No other lot of {d.family} holds stock, so this option cannot be used.</div>}
            </div>
          )}
          {action === "physical_count" && (
            <div className="grid gap-2 sm:grid-cols-2">
              <Field label="Counted on the shelf now"><Input type="number" value={f.on_hand ?? ""} onChange={set("on_hand")} /></Field>
              <Field label={`Unit cost (blank = Sage's ${naira(d.sage_unit_cost)})`}><Input type="number" value={f.unit_cost ?? ""} onChange={set("unit_cost")} /></Field>
              <Field label="Batch number (blank = the Sage lot letter)"><Input value={f.batch_number ?? ""} onChange={set("batch_number")} /></Field>
              <Field label="Expiry date"><Input type="date" value={f.expiry_date ?? ""} onChange={set("expiry_date")} /></Field>
            </div>
          )}
          {(action === "post_missing_entry" || action === "reduce_document") && docs.length > 1 && (
            <Field label="Document"><select className="h-9 w-full rounded-md border bg-background px-2 text-sm" value={f.document ?? ""} onChange={set("document")}>
              <option value="">Choose…</option>{docs.filter((dd: Dict) => !dd.corrected).map((dd: Dict) => <option key={dd.reference} value={dd.reference}>{dd.kind} {dd.reference}{dd.party ? ` · ${dd.party}` : ""}</option>)}
            </select></Field>
          )}
          <Field label={action === "accept" ? "Reason (required - kept with the decision)" : "Note (why - kept with the decision)"}>
            <Textarea rows={2} value={f.note ?? ""} onChange={set("note")} />
          </Field>
          <div className="flex items-center gap-2">
            <Button onClick={submit} disabled={busy || (action === "accept" && !f.note)}>{busy ? "Recording…" : opt.label}</Button>
            <Button variant="ghost" onClick={() => setAction("")}>Cancel</Button>
          </div>
          {["record_receipt", "physical_count", "move_from_lot", "post_missing_entry"].includes(action) && (
            <p className="text-[11px] text-muted-foreground">Posted as a FIX- journal on the hand-over date and kept when later Sage exports are loaded.
              While Sage is still in use, do not also key the same correction in Sage - it would count twice.</p>
          )}
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="space-y-1"><Label className="text-xs">{label}</Label>{children}</div>;
}

// ---------------------------------------------------------------------------
// On the invoice form
// ---------------------------------------------------------------------------

/** Shown under an invoice line whose product has a lot Sage sold below zero: the newest stock is
 *  there physically but not in the books until its receipt is recorded. */
export function PendingReceiptNote({ product, onReload }: { product: Dict | null; onReload: (p: Dict | null) => void }) {
  const drill = useDrill();
  const pending: Dict[] = product?.family_receipts_pending ?? [];
  if (!product || pending.length === 0) return null;
  const reload = async () => {
    const rows = await act(() => books.get<Dict[]>("/products", { search: product.sku, for_sale: true, limit: 5 }));
    const p = (rows ?? []).find((r) => r.sku === product.sku);
    if (p) onReload(p);
  };
  const sellable = Number(product.sellable_qty || 0);
  return (
    <div className={`flex flex-wrap items-start gap-2 rounded-md border p-2 text-[11px] ${sellable > 0 ? "border-amber-300 bg-amber-50 text-amber-900 dark:bg-amber-500/10 dark:text-amber-200" : "border-red-300 bg-red-50 text-red-900 dark:bg-red-500/10 dark:text-red-200"}`}>
      {sellable > 0 ? <PackageSearch className="mt-0.5 h-3.5 w-3.5 shrink-0" /> : <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
      <div className="flex-1">
        {pending.map((p) => (
          <div key={p.sku}>Lot <strong>{p.sku}</strong> was sold in Sage without its receipt (short {num(p.short_by)}).{" "}
            <button type="button" className="font-medium underline" onClick={() => drill?.open({ type: "dataissue", id: p.exception_id, label: p.sku })}>Record the receipt</button>
            {" "}to sell from it.</div>
        ))}
        {sellable <= 0 && <div>Nothing of this lot can be sold until then.</div>}
      </div>
      <Button type="button" size="sm" variant="outline" className="h-6 px-2 text-[11px]" onClick={reload}><CheckCircle2 className="mr-1 h-3 w-3" />Recorded - reload stock</Button>
    </div>
  );
}
