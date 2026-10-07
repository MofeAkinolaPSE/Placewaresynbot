/**
 * Financial lineage viewer. One sheet, a stack of records: every reference in a
 * record opens the next one on top (with a breadcrumb back), so a user can walk
 *   Revenue -> customer -> invoice -> product -> batch -> stock movement -> journal -> GL account
 * without leaving the page they started on.
 *
 * The same record views (<RecordView>) are used by the list pages' own detail
 * sheets, so an invoice / bill / receipt looks and links the same everywhere.
 * Migrated (opening) documents show their line detail from the Sage journals.
 */
import { ReactNode, useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight, ChevronLeft, Pencil, Printer, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { useQueryClient } from "@tanstack/react-query";
import { books, Dict, fmtDate, naira, num, today, yearStart } from "@/lib/books-api";
import { DrillContext, DrillTarget, sourceTarget } from "./drill-context";
import { act, Amount, CsvButton, DateRange, DrillLink, ErrorNote, Loading, sourceLink, StatusBadge, useBooks } from "./kit";
import { GlAccountDetail } from "./gl";
import { DataIssueBody } from "./data-issues";

const TITLES: Record<string, string> = {
  journal: "Journal", account: "Account", invoice: "Sales invoice", receipt: "Customer receipt", creditnote: "Credit note",
  bill: "Supplier bill", payment: "Supplier payment", debitnote: "Debit note", voucher: "Voucher", customer: "Customer",
  supplier: "Supplier", product: "Product", batch: "Batch", adjustment: "Stock adjustment", loan: "Stock loan", asset: "Fixed asset",
  sageinvoice: "Invoice", sagebill: "Supplier invoice", sagereceipt: "Receipt", sagetxn: "Transaction", dataissue: "Data issue",
};

export function DrillProvider({ children }: { children: ReactNode }) {
  const [stack, setStack] = useState<DrillTarget[]>([]);
  const open = useCallback((t: DrillTarget) => setStack((s) => (s.length && s[s.length - 1].type === t.type && s[s.length - 1].id === t.id ? s : [...s, t])), []);
  const ctx = useMemo(() => ({ open }), [open]);
  const top = stack[stack.length - 1];
  return (
    <DrillContext.Provider value={ctx}>
      {children}
      <DetailSheet open={!!top} onOpenChange={(o) => !o && setStack([])} title={top ? `${TITLES[top.type]}${top.label ? ` · ${top.label}` : ""}` : ""}
                   description={stack.length > 1 ? undefined : "Financial lineage: click any underlined reference to follow it."}>
        {stack.length > 1 && (
          <div className="mb-3 flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
            <Button size="sm" variant="ghost" className="h-7 px-2" onClick={() => setStack((s) => s.slice(0, -1))}><ChevronLeft className="h-4 w-4" />Back</Button>
            {stack.map((t, i) => (
              <button key={i} className={`hover:underline ${i === stack.length - 1 ? "font-semibold text-foreground" : ""}`} onClick={() => setStack((s) => s.slice(0, i + 1))}>
                {i > 0 && "› "}{TITLES[t.type]}{t.label ? ` ${t.label}` : ""}
              </button>
            ))}
          </div>
        )}
        {top && <RecordView key={`${top.type}:${top.id}`} t={top} />}
      </DetailSheet>
    </DrillContext.Provider>
  );
}

/** The detail view of any record; also used inside the list pages' own sheets. */
export function RecordView({ t }: { t: DrillTarget }) {
  switch (t.type as string) {
    case "journal": return <JournalBody id={t.id} />;
    case "account": return <AccountBody id={t.id} />;
    case "invoice": return <InvoiceBody id={t.id} />;
    case "receipt": return <ReceiptBody id={t.id} />;
    case "creditnote": return <CreditNoteBody id={t.id} />;
    case "bill": return <BillBody id={t.id} />;
    case "payment": return <PaymentBody id={t.id} />;
    case "debitnote": return <DebitNoteBody id={t.id} />;
    case "voucher": return <VoucherBody id={t.id} />;
    case "customer": return <CustomerBody id={t.id} />;
    case "supplier": return <SupplierBody id={t.id} />;
    case "product": return <ProductBody sku={t.id} />;
    case "batch": return <BatchBody id={t.id} />;
    case "adjustment": return <AdjustmentBody id={t.id} />;
    case "loan": return <LoanBody id={t.id} />;
    case "asset": return <AssetBody id={t.id} />;
    case "sageinvoice": return <SageInvoiceBody number={t.id} />;
    case "sagebill": return <SageBillBody id={t.id} />;
    case "sagereceipt": return <SageReceiptBody id={t.id} />;
    case "sagetxn": return <SageTxnBody id={t.id} />;
    case "dataissue": return <DataIssueBody id={t.id} />;
    default: return null;
  }
}

// ---------------------------------------------------------------------------
// Building blocks
// ---------------------------------------------------------------------------

function Load<T = Dict>({ path, params, children }: { path: string; params?: Dict; children: (d: T) => ReactNode }) {
  const { data, isLoading, error } = useBooks<T>(["lineage", path, params], path, params);
  if (isLoading) return <Loading />;
  if (error) return <ErrorNote error={error} />;
  return <>{data ? children(data) : null}</>;
}

/** Key facts in a grid that uses the sheet's full width. */
export function Facts({ items, cols = 3 }: { items: [string, ReactNode][]; cols?: 2 | 3 | 4 }) {
  const shown = items.filter(([, v]) => v !== null && v !== undefined && v !== "" && v !== false);
  return (
    <div className={`grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg bg-muted/40 p-3 text-sm ${cols === 3 ? "md:grid-cols-3" : cols === 4 ? "md:grid-cols-4" : ""}`}>
      {shown.map(([k, v]) => (
        <div key={k} className="min-w-0"><div className="text-[11px] uppercase tracking-wide text-muted-foreground">{k}</div><div className="truncate font-medium">{v}</div></div>
      ))}
    </div>
  );
}

function H({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return <div className="mb-1 mt-4 flex items-center justify-between gap-2"><span className="text-xs font-semibold uppercase text-muted-foreground">{children}</span>{right}</div>;
}

/** Search box for long lists inside a sheet. */
export function useListFilter<T extends Dict>(rows: T[] | undefined, placeholder = "Search") {
  const [s, setS] = useState("");
  const list = useMemo(() => {
    const r = rows ?? [];
    if (!s.trim()) return r;
    const needle = s.toLowerCase();
    return r.filter((x) => Object.values(x).some((v) => v != null && typeof v !== "object" && String(v).toLowerCase().includes(needle)));
  }, [rows, s]);
  const box = (rows?.length ?? 0) > 6 ? (
    <div className="relative w-56"><Search className="absolute left-2 top-2 h-3.5 w-3.5 text-muted-foreground" />
      <Input className="h-7 pl-7 text-xs" placeholder={placeholder} value={s} onChange={(e) => setS(e.target.value)} /></div>
  ) : null;
  return [list, box] as const;
}

const J = ({ id, n }: { id?: string; n?: string }) => (id ? <DrillLink to={{ type: "journal", id, label: n }}>{n ?? "journal"}</DrillLink> : <span className="text-muted-foreground">—</span>);
const Cust = ({ id, name }: { id?: any; name?: string }) => (id ? <DrillLink to={{ type: "customer", id: String(id), label: name }}>{name ?? `#${id}`}</DrillLink> : <>{name ?? "—"}</>);
const Sup = ({ id, name }: { id?: any; name?: string }) => (id ? <DrillLink to={{ type: "supplier", id: String(id), label: name }}>{name ?? "supplier"}</DrillLink> : <>{name ?? "—"}</>);
const Prod = ({ sku, children }: { sku?: string; children?: ReactNode }) => (sku ? <DrillLink to={{ type: "product", id: sku, label: sku }}>{children ?? sku}</DrillLink> : <>{children}</>);
const Bat = ({ id, n }: { id?: string; n?: string }) => (id ? <DrillLink to={{ type: "batch", id, label: n }}>{n ?? "batch"}</DrillLink> : <>{n ?? ""}</>);
const SageInv = ({ number, openingId }: { number: string; openingId?: string | null }) =>
  openingId ? <DrillLink to={{ type: "invoice", id: openingId, label: number }}>{number}</DrillLink>
            : <DrillLink to={{ type: "sageinvoice" as any, id: number, label: number }}>{number}</DrillLink>;

/** Open the printable invoice (the client's invoice layout) in a new tab. */
export function PrintInvoiceButton({ kind, id }: { kind: "ace" | "sage"; id: string }) {
  return (
    <Button size="sm" variant="outline" onClick={() => window.open(`#/finance/books/invoice-print/${kind}/${encodeURIComponent(id)}`, "_blank")}>
      <Printer className="mr-1 h-4 w-4" />Print invoice
    </Button>
  );
}

/** Payments Sage applied to an invoice (from the Cash Receipts Journal). */
function SagePayments({ rows, customer }: { rows?: Dict[]; customer?: string }) {
  if (!rows?.length) return null;
  return (
    <>
      <H>Payments received</H>
      <Table>
        <TableHeader><TableRow><TableHead>Date</TableHead><TableHead>Reference</TableHead><TableHead>Into</TableHead><TableHead className="text-right">Applied</TableHead></TableRow></TableHeader>
        <TableBody>{rows.map((p, i) => (
          <TableRow key={i}>
            <TableCell className="whitespace-nowrap text-xs">{fmtDate(p.date)}</TableCell>
            <TableCell className="text-xs">{p.kind === "credit memo" ? <>credit {p.reference}</> :
              <DrillLink to={{ type: "sagereceipt", id: `${p.date}|${p.reference ?? ""}|${p.received_from ?? customer ?? ""}`, label: p.reference }}>{p.reference}</DrillLink>}
              {p.with_invoices?.length > 0 && <div className="text-[11px] text-muted-foreground">same payment also paid {p.with_invoices.slice(0, 6).join(", ")}{p.with_invoices.length > 6 ? "…" : ""}</div>}</TableCell>
            <TableCell className="text-xs">{p.deposited_to_name ?? p.deposited_to ?? ""}{p.receipt_total ? <div className="text-[11px] text-muted-foreground">receipt total {naira(p.receipt_total)}</div> : null}</TableCell>
            <TableCell className="text-right"><Amount value={p.amount} /></TableCell>
          </TableRow>))}</TableBody>
      </Table>
    </>
  );
}

function PageLink({ to }: { to: string | null }) {
  return to ? <Link className="inline-flex items-center text-xs text-muted-foreground hover:underline" to={to}>open in its page <ArrowUpRight className="h-3 w-3" /></Link> : null;
}

function Totals({ rows }: { rows: [string, any, boolean?][] }) {
  return (
    <div className="grid grid-cols-1 gap-x-8 gap-y-1 rounded-lg border p-3 text-sm sm:grid-cols-2">
      {rows.filter(([, v]) => v !== undefined && v !== null).map(([k, v, bold]) => (
        <div key={k} className={`flex justify-between gap-2 ${bold ? "font-semibold" : ""}`}><span className="text-muted-foreground">{k}</span><Amount value={v} /></div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Ledger
// ---------------------------------------------------------------------------

export function JournalBody({ id }: { id: string }) {
  return <Load path={`/journals/${id}`}>{(j) => <JournalContent j={j} />}</Load>;
}

function JournalContent({ j }: { j: Dict }) {
  const [lines, box] = useListFilter<Dict>(j.lines.map((l: Dict) => ({ ...l, _acc: `${l.account_code} ${l.account_name}` })), "Search account, description, item");
  const manual = !j.source_type || j.source_type === "MANUAL_JOURNAL";
  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap items-center gap-2"><StatusBadge status={j.status} /><Badge variant="outline">{j.journal_type.toLowerCase()}</Badge>
        <span className="text-muted-foreground">{fmtDate(j.journal_date)} · {j.period_name}</span></div>
      <Facts items={[["Journal", j.journal_number], ["Narration", j.description],
        ["Source", !manual && j.source_ref ? <DrillLink to={sourceTarget(j.source_type, j.source_id)}>{j.source_type?.replace(/_/g, " ").toLowerCase()} {j.source_ref}</DrillLink> : manual ? "manual journal" : null],
        ["Created by", j.created_by], ["Posted by", j.posted_by], ["Lines", j.lines.length]]} />
      <H right={box}>Lines</H>
      <Table>
        <TableHeader><TableRow><TableHead>Account</TableHead><TableHead className="text-right">Debit</TableHead><TableHead className="text-right">Credit</TableHead></TableRow></TableHeader>
        <TableBody>
          {lines.map((l: Dict) => (
            <TableRow key={l.id}>
              <TableCell><DrillLink to={{ type: "account", id: l.account_id, label: l.account_code }}>{l.account_code} · {l.account_name}</DrillLink>
                <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                  {l.description && <span>{l.description}</span>}
                  {l.customer_id && <Cust id={l.customer_id} name={`customer #${l.customer_id}`} />}
                  {l.supplier_id && <Sup id={l.supplier_id} />}
                  <Prod sku={l.product_sku} />
                </div></TableCell>
              <TableCell className="text-right"><Amount value={l.debit} blankZero /></TableCell><TableCell className="text-right"><Amount value={l.credit} blankZero /></TableCell>
            </TableRow>
          ))}
          <TableRow className="font-semibold"><TableCell>Total{lines.length !== j.lines.length ? ` (all ${j.lines.length} lines)` : ""}</TableCell><TableCell className="text-right"><Amount value={j.total_debit} /></TableCell><TableCell className="text-right"><Amount value={j.total_credit} /></TableCell></TableRow>
        </TableBody>
      </Table>
      {j.reversal_of_id && <DrillLink to={{ type: "journal", id: j.reversal_of_id }}>This reverses another journal — open it</DrillLink>}
      {j.reversed_by_id && <DrillLink to={{ type: "journal", id: j.reversed_by_id }}>Reversed — open the reversal</DrillLink>}
      {j.audit?.length > 0 && (<><H>Audit trail</H>
        <ul className="space-y-1 text-xs">{j.audit.map((a: Dict, i: number) => (
          <li key={i}><span className="text-muted-foreground">{new Date(a.created_at).toLocaleString("en-GB")}</span> · {a.action.replace(/_/g, " ").toLowerCase()} by {a.actor_name}{a.reason ? ` — ${a.reason}` : ""}</li>))}</ul></>)}
    </div>
  );
}

function AccountBody({ id }: { id: string }) {
  const [range, setRange] = useState({ from: yearStart(), to: today() });
  return (
    <div className="space-y-3 text-sm">
      <DateRange from={range.from} to={range.to} onChange={(f, t) => setRange({ from: f ?? range.from, to: t })} />
      <Load path={`/accounts/${id}`}>{(a) => (
        <>
          <Facts cols={3} items={[["Account", `${a.code} · ${a.name}`], ["Type", `${String(a.subtype ?? "").replace(/_/g, " ").toLowerCase()}`], ["Normal balance", a.normal_balance?.toLowerCase()]]} />
          <GlAccountDetail code={a.code} from={range.from} to={range.to} compact />
        </>
      )}</Load>
    </div>
  );
}

function AccountContent({ d }: { d: Dict }) {
  const [rows, box] = useListFilter<Dict>(d.rows, "Search reference, description");
  return (
    <>
      <Facts cols={4} items={[["Account", `${d.account.code} · ${d.account.name}`], ["Type", `${d.account.subtype.replace(/_/g, " ").toLowerCase()}`],
        ["Opening", <Amount value={d.opening} />], ["Closing", <Amount value={d.closing} bold />]]} />
      <H right={<div className="flex gap-2">{box}<CsvButton filename={`ledger-${d.account.code}.csv`} rows={d.rows} /></div>}>Ledger lines ({d.count})</H>
      <Table>
        <TableHeader><TableRow><TableHead>Date</TableHead><TableHead>Reference</TableHead><TableHead className="text-right">Dr</TableHead><TableHead className="text-right">Cr</TableHead><TableHead className="text-right">Balance</TableHead></TableRow></TableHeader>
        <TableBody>{rows.map((r: Dict) => (
          <TableRow key={r.line_id}>
            <TableCell className="whitespace-nowrap">{fmtDate(r.journal_date)}</TableCell>
            <TableCell><DrillLink to={sourceTarget(r.source_type, r.source_id) ?? { type: "journal", id: r.journal_id }}><span className="font-mono text-xs">{r.source_ref || r.journal_number}</span></DrillLink>
              <div className="max-w-[260px] truncate text-xs text-muted-foreground">{r.description}</div>
              <div className="text-[11px]"><J id={r.journal_id} n={r.journal_number} /></div></TableCell>
            <TableCell className="text-right"><Amount value={r.debit} blankZero /></TableCell><TableCell className="text-right"><Amount value={r.credit} blankZero /></TableCell>
            <TableCell className="text-right"><Amount value={r.running_balance} /></TableCell>
          </TableRow>
        ))}</TableBody>
      </Table>
      {d.count > d.rows.length && <p className="text-xs text-muted-foreground">Showing {d.rows.length} of {d.count} lines.</p>}
    </>
  );
}

// ---------------------------------------------------------------------------
// Sales documents
// ---------------------------------------------------------------------------

function HistoryLines({ lines, kind }: { lines: Dict[]; kind: "sale" | "purchase" }) {
  if (!lines?.length) return null;
  const total = lines.reduce((s, l) => s + Number(l.amount || 0), 0);
  return (
    <>
      <H>{kind === "sale" ? "What was sold" : "What was bought"}</H>
      <Table>
        <TableHeader><TableRow><TableHead className="text-right">Qty</TableHead><TableHead>Description</TableHead><TableHead>Batch</TableHead><TableHead>Exp. date</TableHead><TableHead className="text-right">{kind === "sale" ? "Unit price" : "Unit cost"}</TableHead><TableHead className="text-right">Amount</TableHead>{kind === "sale" && <TableHead className="text-right">Unit cost</TableHead>}</TableRow></TableHeader>
        <TableBody>
          {lines.map((l, i) => (
            <TableRow key={i}>
              <TableCell className="text-right">{l.quantity != null ? num(l.quantity) : "—"}</TableCell>
              <TableCell><div>{l.sku ? <Prod sku={l.sku}>{l.product_name || l.description}</Prod> : l.description}</div><div className="text-xs text-muted-foreground">{l.sku} · GL {l.account_code}</div></TableCell>
              <TableCell className="text-xs">{l.batch_number || (l.sku ? (l.sku.match(/\(([^)]*)\)\s*\w*$/)?.[1] ?? "") : "")}</TableCell>
              <TableCell className="whitespace-nowrap text-xs">{l.expiry_date ? fmtDate(l.expiry_date) : ""}</TableCell>
              <TableCell className="text-right">{l.quantity ? <Amount value={l.unit_price ?? l.unit_cost ?? Number(l.amount) / Number(l.quantity)} /> : ""}</TableCell>
              <TableCell className="text-right"><Amount value={l.amount} /></TableCell>
              {kind === "sale" && <TableCell className="text-right">{l.cost != null && l.quantity ? <Amount value={Number(l.cost) / Number(l.quantity)} /> : ""}</TableCell>}
            </TableRow>
          ))}
          <TableRow className="font-semibold"><TableCell colSpan={5}>Total</TableCell><TableCell className="text-right"><Amount value={total} /></TableCell>{kind === "sale" && <TableCell />}</TableRow>
        </TableBody>
      </Table>
    </>
  );
}

export function InvoiceBody({ id }: { id: string }) {
  return (
    <Load path={`/sales/invoices/${id}`}>{(i) => (
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2"><StatusBadge status={i.status} /><span className="font-mono text-base font-semibold">{i.invoice_number}</span>
            {i.source_type === "FRONTDESK" && <Badge variant="outline">from Frontdesk</Badge>}</div>
          <PrintInvoiceButton kind="ace" id={id} />
        </div>
        <Facts items={[["Customer", <Cust id={i.customer_id} name={i.customer_name} />], ["Customer ID", i.customer_code], ["Invoice date", fmtDate(i.invoice_date)], ["Due date", fmtDate(i.due_date)],
          ["Payment terms", i.terms_days === 0 ? "C.O.D." : i.terms_days ? `Net ${i.terms_days} days` : null], ["Customer PO", i.customer_po || i.reference], ["Shipping method", i.shipping_method],
          ["Journal", i.journal_id ? <J id={i.journal_id} n={i.journal_number} /> : null], ["Credit override", i.credit_override_reason]]} />
        {i.lines?.length > 0 && (<><H>What was sold</H>
          <Table>
            <TableHeader><TableRow><TableHead className="text-right">Qty</TableHead><TableHead>Description</TableHead><TableHead>Batch</TableHead><TableHead>Man. date</TableHead><TableHead>Exp. date</TableHead><TableHead className="text-right">Unit price</TableHead><TableHead className="text-right">Amount</TableHead><TableHead className="text-right">Unit cost</TableHead></TableRow></TableHeader>
            <TableBody>{i.lines.map((l: Dict) => (
              <TableRow key={l.id}>
                <TableCell className="text-right">{num(l.quantity)}</TableCell>
                <TableCell><div>{l.sku ? <Prod sku={l.sku}>{l.description || l.sku}</Prod> : l.description}</div><div className="text-[11px] text-muted-foreground">{l.sku} · {l.line_type.toLowerCase()} → {l.account_code}</div></TableCell>
                <TableCell className="text-xs">{l.batch_id ? <Bat id={l.batch_id} n={l.batch_number} /> : l.shipped_batch ?? ""}</TableCell>
                <TableCell className="whitespace-nowrap text-xs">{fmtDate(l.manufacture_date ?? l.shipped_mfg)}</TableCell>
                <TableCell className="whitespace-nowrap text-xs">{fmtDate(l.expiry_date ?? l.shipped_expiry)}</TableCell>
                <TableCell className="text-right"><Amount value={l.unit_price} />{Number(l.discount_amount) > 0 && <div className="text-xs text-muted-foreground">−{naira(l.discount_amount)}</div>}</TableCell>
                <TableCell className="text-right"><Amount value={l.line_total} /></TableCell><TableCell className="text-right"><Amount value={l.unit_cost} blankZero /></TableCell>
              </TableRow>
            ))}</TableBody>
          </Table></>)}
        <HistoryLines lines={i.history_lines} kind="sale" />
        <Totals rows={[["Invoice amount", i.original_total ?? i.total, true],
          ["Paid before this period", i.original_total && Number(i.original_total) !== Number(i.total) ? -(Number(i.original_total) - Number(i.total)) : undefined],
          ["Discounts", Number(i.discount_total) ? -Number(i.discount_total) : undefined], ["Charges", Number(i.charge_total) ? i.charge_total : undefined],
          ["Tax", Number(i.tax_total) ? i.tax_total : undefined], ["Paid / credited", Number(i.amount_settled) ? -Number(i.amount_settled) : undefined], ["Balance due", i.balance_due, true]]} />
        <SagePayments rows={i.sage_payments} customer={i.customer_name} />
        {i.allocations?.length > 0 && (<><H>Paid / credited by</H>
          {i.allocations.map((a: Dict) => (
            <div key={a.id} className="flex justify-between text-xs"><DrillLink to={{ type: a.source_type === "CREDIT_NOTE" ? "creditnote" : "receipt", id: a.source_id, label: a.source_number }}>{a.source_number}</DrillLink>
              <span>{fmtDate(a.allocation_date)} · <Amount value={a.amount} />{a.reversed ? " (reversed)" : ""}</span></div>
          ))}</>)}
        {i.void_reason && <p className="text-xs text-red-600">Voided: {i.void_reason}</p>}
        <PageLink to={sourceLink("SALES_INVOICE", id)} />
      </div>
    )}</Load>
  );
}

function SageInvoiceBody({ number }: { number: string }) {
  return (
    <Load path={`/sage-history/invoices/${encodeURIComponent(number)}`}>{(d) => (
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="font-mono text-base font-semibold">{d.invoice_number}</span>
          <div className="flex gap-2">{d.ace_invoice_id && <DrillLink to={{ type: "invoice", id: d.ace_invoice_id, label: d.invoice_number }}>open item in ACE Books</DrillLink>}
            <PrintInvoiceButton kind="sage" id={number} /></div>
        </div>
        <Facts items={[["Customer", <Cust id={d.customer_id} name={d.customer_name} />], ["Customer ID", d.customer_code], ["Invoice date", fmtDate(d.invoice_date)],
          ["Invoice amount", <Amount value={d.total} bold />], ["Paid / credited", <Amount value={d.paid} />], ["Balance", <Amount value={d.balance} bold />],
          ["Cost of sales", <Amount value={d.cost} />]]} />
        <HistoryLines lines={d.lines} kind="sale" />
        <SagePayments rows={d.payments} customer={d.customer_name} />
        {(!d.payments || d.payments.length === 0) && Number(d.balance) > 0 && <p className="text-xs text-amber-700">No payment has been applied to this invoice.</p>}
      </div>
    )}</Load>
  );
}

/** A supplier invoice from the Sage purchase journal. id is "<invoice number>|<supplier id>". */
function SageBillBody({ id }: { id: string }) {
  const [number, supplierId] = id.split("|");
  return (
    <Load path={`/sage-history/bills/${encodeURIComponent(number)}`} params={{ supplier_id: supplierId || undefined }}>{(d) => (
      <div className="space-y-3 text-sm">
        <Facts items={[["Supplier invoice", d.bill_number], ["Supplier", <Sup id={d.supplier_id} name={d.supplier_name} />], ["Date", fmtDate(d.bill_date)],
          ["Amount", <Amount value={d.total} bold />], ["Paid", <Amount value={d.paid} />], ["Lines", d.lines?.length ?? 0]]} />
        <HistoryLines lines={d.lines} kind="purchase" />
        {d.payments?.length > 0 && (<><H>Payments made</H>{d.payments.map((p: Dict, i: number) => (
          <div key={i} className="flex justify-between text-xs"><DrillLink to={{ type: "sagetxn", id: `${p.date}|CDJ|${p.reference ?? ""}`, label: p.reference }}>{fmtDate(p.date)} · {p.reference}</DrillLink><Amount value={p.amount} /></div>))}</>)}
      </div>
    )}</Load>
  );
}

/** A receipt from Sage's Cash Receipts Journal: who paid, into which bank, which invoices it settled. */
function SageReceiptBody({ id }: { id: string }) {
  const [date, ref, customer] = id.split("|");
  return (
    <Load path="/sage-history/receipt" params={{ date, ref: ref || undefined, customer: customer || undefined }}>{(d) => (
      <div className="space-y-4 text-sm">
        {d.receipts.length === 0 && <p className="text-xs text-muted-foreground">No receipt with this reference on {fmtDate(date)}.</p>}
        {d.receipts.map((r: Dict, i: number) => (
          <div key={i} className="space-y-2">
            <Facts items={[["Received from", r.received_from], ["Date", fmtDate(d.date)], ["Reference", d.reference], ["Into", r.deposited_to_name ?? r.deposited_to],
              ["Amount", <Amount value={r.amount} bold />]]} />
            <H>Applied to</H>
            <Table><TableBody>{r.applied.map((a: Dict, k: number) => (
              <TableRow key={k}><TableCell className="text-xs">{a.invoice_number ? <DrillLink to={{ type: "sageinvoice", id: a.invoice_number, label: a.invoice_number }}>Invoice {a.invoice_number}</DrillLink> : <>{a.description} · {a.account}</>}</TableCell>
                <TableCell className="text-right"><Amount value={a.amount} /></TableCell></TableRow>))}</TableBody></Table>
          </div>
        ))}
      </div>
    )}</Load>
  );
}

/** Every line of one Sage transaction (date + journal + reference), e.g. a petty cash payment and the expense it went to. */
function SageTxnBody({ id }: { id: string }) {
  const [date, jrnl, ref] = id.split("|");
  return (
    <Load path="/sage-history/transaction" params={{ date, jrnl: jrnl || undefined, ref: ref || undefined }}>{(d) => (
      <div className="space-y-3 text-sm">
        <Facts items={[["Date", fmtDate(d.date)], ["Journal", d.jrnl], ["Reference", d.reference], ["Debits", <Amount value={d.total_debit} />], ["Credits", <Amount value={d.total_credit} />]]} />
        {d.invoice_number && <DrillLink to={{ type: "sageinvoice", id: d.invoice_number, label: d.invoice_number }}>Open invoice {d.invoice_number}</DrillLink>}
        {d.correction && (
          <div className="rounded-lg border border-sky-300 bg-sky-50 p-2 text-xs dark:bg-sky-500/10">
            Correction decided in Data issues by {d.correction.created_by} on {fmtDate(d.correction.created_at)}: {d.correction.title}
            {d.correction.note ? <> - “{d.correction.note}”</> : null}.{" "}
            <DrillLink to={{ type: "dataissue", id: d.correction.exception_id, label: d.reference }}>Open the issue</DrillLink>
            {d.correction.journal_id && <> · <DrillLink to={{ type: "journal", id: d.correction.journal_id, label: d.correction.journal_number }}>journal {d.correction.journal_number}</DrillLink></>}
          </div>
        )}
        <H>{d.lines.length} line(s) posted with this reference on this day</H>
        <Table>
          <TableHeader><TableRow><TableHead>Account</TableHead><TableHead>Description</TableHead><TableHead className="text-right">Debit</TableHead><TableHead className="text-right">Credit</TableHead></TableRow></TableHeader>
          <TableBody>{d.lines.map((l: Dict) => (
            <TableRow key={l.id}>
              <TableCell className="text-xs">{l.account_id ? <DrillLink to={{ type: "account", id: l.account_id, label: l.account_code }}>{l.account_code} · {l.account_name}</DrillLink> : l.account_code}</TableCell>
              <TableCell className="text-xs">{l.description}</TableCell>
              <TableCell className="text-right"><Amount value={l.debit} blankZero /></TableCell><TableCell className="text-right"><Amount value={l.credit} blankZero /></TableCell>
            </TableRow>))}</TableBody>
        </Table>
        {d.journal_lines?.length > 0 && (<><H>As entered in the journal</H>
          <Table><TableBody>{d.journal_lines.map((l: Dict, i: number) => (
            <TableRow key={i}><TableCell className="text-xs">{l.account_code} {l.account_description ?? ""}</TableCell><TableCell className="text-xs">{l.description}{l.qty != null ? ` · qty ${num(l.qty)}` : ""}</TableCell>
              <TableCell className="text-right"><Amount value={l.debit} blankZero /></TableCell><TableCell className="text-right"><Amount value={l.credit} blankZero /></TableCell></TableRow>))}</TableBody></Table></>)}
      </div>
    )}</Load>
  );
}

export function ReceiptBody({ id }: { id: string }) {
  return (
    <Load path={`/receivables/receipts/${id}`}>{(r) => (
      <div className="space-y-3 text-sm">
        <div className="flex items-center gap-2"><StatusBadge status={r.status} /><span className="font-mono">{r.receipt_number}</span></div>
        <Facts items={[["From", <Cust id={r.customer_id} name={r.customer_name} />], ["Date", fmtDate(r.receipt_date)], ["Method", `${r.method?.toLowerCase()}`],
          ["Cheque / ref", r.reference], ["Into", r.bank_account_name], ["Journal", <J id={r.journal_id} n={r.journal_number} />]]} />
        <Totals rows={[["Received", r.amount, true], ["WHT deducted", Number(r.wht_amount) ? r.wht_amount : undefined], ["Applied", r.amount_allocated], ["On account", r.unapplied, true]]} />
        {r.allocations?.length > 0 && (<><H>Applied to invoices</H>{r.allocations.map((a: Dict) => (
          <div key={a.id} className="flex justify-between text-xs"><DrillLink to={{ type: "invoice", id: a.invoice_id, label: a.invoice_number }}>{a.invoice_number}</DrillLink>
            <span>{fmtDate(a.allocation_date)} · <Amount value={a.amount} />{a.reversed ? " (reversed)" : ""}</span></div>))}</>)}
        {r.void_reason && <p className="text-xs text-red-600">Voided: {r.void_reason}</p>}
        <PageLink to={sourceLink("CUSTOMER_RECEIPT", id)} />
      </div>
    )}</Load>
  );
}

export function CreditNoteBody({ id }: { id: string }) {
  return (
    <Load path={`/sales/credit-notes/${id}`}>{(n) => {
      const opening = !n.journal_id;
      return (
        <div className="space-y-3 text-sm">
          <div className="flex flex-wrap items-center gap-2"><StatusBadge status={n.status} /><span className="font-mono">{n.credit_note_number}</span></div>
          <Facts items={[["Customer", <Cust id={n.customer_id} name={n.customer_name} />], ["Date", fmtDate(n.note_date)],
            ["Against invoice", n.invoice_id ? <DrillLink to={{ type: "invoice", id: n.invoice_id, label: n.invoice_number }}>{n.invoice_number}</DrillLink>
              : n.sage_invoice_number && /^\d{3,}$/.test(n.sage_invoice_number) ? <DrillLink to={{ type: "sageinvoice", id: n.sage_invoice_number, label: n.sage_invoice_number }}>{n.sage_invoice_number}</DrillLink> : "none (on account)"],
            ["Reason", n.reason], ["Returned to stock", n.lines?.some((l: Dict) => l.inventory_txn_id) ? "yes" : null],
            ["Journal", n.journal_id ? <J id={n.journal_id} n={n.journal_number} /> : null]]} />
          <Totals rows={[["Credit total", n.total, true], ["Applied to invoices", n.amount_settled], ["Unapplied (on account)", n.unapplied ?? Number(n.total) - Number(n.amount_settled || 0), true]]} />
          {n.lines?.length > 0 && (<><H>Lines</H><Table><TableBody>{n.lines.map((l: Dict) => (
            <TableRow key={l.id}><TableCell>{l.sku ? <Prod sku={l.sku} /> : l.description}</TableCell>
              <TableCell className="text-right">{num(l.quantity)}</TableCell><TableCell className="text-right"><Amount value={l.line_total} /></TableCell></TableRow>))}</TableBody></Table></>)}
          {n.allocations?.length > 0 && (<><H>Applied to</H>{n.allocations.map((a: Dict) => (
            <div key={a.id} className="flex justify-between text-xs"><DrillLink to={{ type: "invoice", id: a.invoice_id, label: a.invoice_number }}>{a.invoice_number}</DrillLink><Amount value={a.amount} /></div>))}</>)}
          {opening && Number(n.unapplied ?? 0) > 0 && <p className="text-xs text-muted-foreground">On the customer's account until it is applied to an invoice (Sales › Credit notes).</p>}
          <PageLink to={sourceLink("CREDIT_NOTE", id)} />
        </div>
      );
    }}</Load>
  );
}

// ---------------------------------------------------------------------------
// Purchasing & banking documents
// ---------------------------------------------------------------------------

export function BillBody({ id }: { id: string }) {
  return (
    <Load path={`/payables/bills/${id}`}>{(b) => (
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap items-center gap-2"><StatusBadge status={b.status} /><span className="font-mono">{b.bill_number}</span></div>
        <Facts items={[["Supplier", <Sup id={b.supplier_id} name={b.supplier_name} />], ["Supplier invoice", b.supplier_invoice_number], ["Bill date", fmtDate(b.bill_date)],
          ["Due", fmtDate(b.due_date)], ["Journal", b.journal_id ? <J id={b.journal_id} n={b.journal_number} /> : null], ["Notes", b.notes]]} />
        {b.lines?.length > 0 && (<><H>What was bought</H><Table>
          <TableHeader><TableRow><TableHead>Item / account</TableHead><TableHead className="text-right">Qty</TableHead><TableHead className="text-right">Unit cost</TableHead><TableHead className="text-right">Amount</TableHead></TableRow></TableHeader>
          <TableBody>{b.lines.map((l: Dict) => (
            <TableRow key={l.id}><TableCell><div>{l.sku ? <Prod sku={l.sku} /> : l.description}</div><div className="text-xs text-muted-foreground">{l.batch_id && <>batch <Bat id={l.batch_id} n={l.batch_number} /> </>}{l.expiry_date && `exp ${fmtDate(l.expiry_date)} · `}{l.account_code} {l.account_name}</div></TableCell>
              <TableCell className="text-right">{num(l.quantity)}</TableCell><TableCell className="text-right"><Amount value={l.unit_cost} /></TableCell><TableCell className="text-right"><Amount value={l.line_total} /></TableCell></TableRow>))}</TableBody></Table></>)}
        <HistoryLines lines={b.history_lines} kind="purchase" />
        <Totals rows={[["Total", b.total, true], ["Paid / returned", b.amount_settled], ["Still owed", b.balance_due, true]]} />
        {b.allocations?.length > 0 && (<><H>Paid / returned by</H>{b.allocations.map((a: Dict) => (
          <div key={a.id} className="flex justify-between text-xs"><DrillLink to={{ type: a.source_type === "DEBIT_NOTE" ? "debitnote" : "payment", id: a.source_id, label: a.source_number }}>{a.source_number}</DrillLink><Amount value={a.amount} /></div>))}</>)}
        {b.void_reason && <p className="text-xs text-red-600">Voided: {b.void_reason}</p>}
        <PageLink to={sourceLink("SUPPLIER_BILL", id)} />
      </div>
    )}</Load>
  );
}

export function PaymentBody({ id }: { id: string }) {
  return (
    <Load path={`/payables/payments/${id}`}>{(p) => (
      <div className="space-y-3 text-sm">
        <div className="flex items-center gap-2"><StatusBadge status={p.status} /><span className="font-mono">{p.payment_number}</span></div>
        <Facts items={[["Paid to", <Sup id={p.supplier_id} name={p.supplier_name} />], ["Date", fmtDate(p.payment_date)], ["Method", p.method?.toLowerCase()],
          ["Cheque / ref", p.reference], ["From", p.bank_account_name], ["Journal", <J id={p.journal_id} n={p.journal_number} />]]} />
        <Totals rows={[["Paid", p.amount, true], ["WHT withheld", Number(p.wht_amount) ? p.wht_amount : undefined], ["Applied", p.amount_allocated], ["Unapplied", p.unapplied, true]]} />
        {p.allocations?.length > 0 && (<><H>Settled bills</H>{p.allocations.map((a: Dict) => (
          <div key={a.id} className="flex justify-between text-xs"><DrillLink to={{ type: "bill", id: a.bill_id, label: a.bill_number }}>{a.bill_number} {a.supplier_invoice_number && `(${a.supplier_invoice_number})`}</DrillLink><Amount value={a.amount} /></div>))}</>)}
        {p.void_reason && <p className="text-xs text-red-600">Voided: {p.void_reason}</p>}
      </div>
    )}</Load>
  );
}

export function DebitNoteBody({ id }: { id: string }) {
  return (
    <Load path={`/payables/debit-notes/${id}`}>{(d) => (
      <div className="space-y-3 text-sm">
        <Facts items={[["Number", d.debit_note_number], ["Supplier", <Sup id={d.supplier_id} name={d.supplier_name} />], ["Date", fmtDate(d.note_date)],
          ["Against bill", d.bill_id ? <DrillLink to={{ type: "bill", id: d.bill_id, label: d.bill_number }}>{d.bill_number}</DrillLink> : "none"], ["Reason", d.reason],
          ["Journal", <J id={d.journal_id} n={d.journal_number} />]]} />
        <Totals rows={[["Total", d.total, true], ["Applied", d.amount_settled]]} />
        {(d.lines ?? []).length > 0 && <Table><TableBody>{d.lines.map((l: Dict) => (
          <TableRow key={l.id}><TableCell><Prod sku={l.sku} /> {l.batch_id && <Bat id={l.batch_id} />}</TableCell><TableCell className="text-right">{num(l.quantity)}</TableCell><TableCell className="text-right"><Amount value={l.line_total} /></TableCell></TableRow>))}</TableBody></Table>}
      </div>
    )}</Load>
  );
}

export function VoucherBody({ id }: { id: string }) {
  return (
    <Load path={`/banking/vouchers/${id}`}>{(v) => (
      <div className="space-y-3 text-sm">
        <div className="flex items-center gap-2"><StatusBadge status={v.status} /><span className="font-mono">{v.voucher_number}</span><Badge variant="outline">{v.kind.toLowerCase()}</Badge></div>
        <Facts items={[["Date", fmtDate(v.voucher_date)], ["Account", `${v.bank_account_name}${v.to_bank_account_name ? ` → ${v.to_bank_account_name}` : ""}`], ["Payee", v.payee],
          ["Reference", v.reference], ["Amount", <Amount value={v.amount} bold />], ["Journal", <J id={v.journal_id} n={v.journal_number} />]]} />
        {(v.lines ?? []).length > 0 && (<><H>What it was for</H><Table><TableBody>{v.lines.map((l: Dict) => (
          <TableRow key={l.id}><TableCell><DrillLink to={{ type: "account", id: l.account_id, label: l.account_code }}>{l.account_code} · {l.account_name}</DrillLink><div className="text-xs text-muted-foreground">{l.description}</div></TableCell>
            <TableCell className="text-right"><Amount value={l.amount} /></TableCell></TableRow>))}</TableBody></Table></>)}
        {v.void_reason && <p className="text-xs text-red-600">Voided: {v.void_reason}</p>}
      </div>
    )}</Load>
  );
}

// ---------------------------------------------------------------------------
// Parties
// ---------------------------------------------------------------------------

function CustomerBody({ id }: { id: string }) {
  return <Load path={`/customers/${id}/overview`}>{(d) => <CustomerContent d={d} />}</Load>;
}

function CustomerContent({ d }: { d: Dict }) {
  const [invoices, invBox] = useListFilter<Dict>(d.invoices, "Search invoices");
  const [history, histBox] = useListFilter<Dict>(d.sage?.invoices, "Search Sage invoices");
  const [products, prodBox] = useListFilter<Dict>([...(d.products ?? []), ...(d.sage?.products ?? []).map((p: Dict) => ({ ...p, _sage: true }))], "Search products");
  const c = d.customer;
  return (
    <div className="space-y-3 text-sm">
      <Facts items={[["Customer", c.name], ["Sage ID", c.customer_code], ["Owes now", <Amount value={d.balance} bold />], ["Overdue", <Amount value={d.overdue} />],
        ["Credit limit", c.credit_limit ? naira(c.credit_limit) : "none"], ["Terms", c.payment_terms_days ? `${c.payment_terms_days} days` : null]]} />
      {d.frontdesk_in_progress?.length > 0 && (
        <div className="rounded-lg border border-sky-300 bg-sky-50 p-2 text-xs dark:bg-sky-500/10">
          <strong>{d.frontdesk_in_progress.length} Frontdesk invoice(s) in progress</strong> — they post to the books automatically when Finance approves them:{" "}
          {d.frontdesk_in_progress.map((f: Dict) => `${f.invoice_number} (${f.status.replace(/_/g, " ")})`).join(", ")}
        </div>
      )}
      <Tabs defaultValue="open">
        <TabsList className="flex-wrap">
          <TabsTrigger value="open">Invoices ({d.invoices.length})</TabsTrigger>
          <TabsTrigger value="products">What they buy</TabsTrigger>
          <TabsTrigger value="history">All invoices ({d.sage?.invoices?.length ?? 0}{(d.sage?.invoices?.length ?? 0) >= 100 ? "+" : ""})</TabsTrigger>
          <TabsTrigger value="receipts">Receipts ({d.receipts.length})</TabsTrigger>
          {d.loans.length > 0 && <TabsTrigger value="loans">On loan ({d.loans.length})</TabsTrigger>}
        </TabsList>
        <TabsContent value="open">
          <H right={invBox}>Invoices with a balance, and new invoices</H>
          <Table><TableBody>{invoices.map((i: Dict) => (
            <TableRow key={i.id}><TableCell><DrillLink to={{ type: "invoice", id: i.id, label: i.invoice_number }}>{i.invoice_number}</DrillLink></TableCell>
              <TableCell className="whitespace-nowrap text-xs">{fmtDate(i.invoice_date)}</TableCell><TableCell className="text-right"><Amount value={i.total} /></TableCell>
              <TableCell className="text-right"><Amount value={i.balance} blankZero /></TableCell><TableCell><StatusBadge status={i.status} /></TableCell></TableRow>))}</TableBody></Table>
        </TabsContent>
        <TabsContent value="products">
          <H right={prodBox}>Products bought</H>
          <Table><TableHeader><TableRow><TableHead>Item</TableHead><TableHead className="text-right">Qty</TableHead><TableHead className="text-right">Amount</TableHead><TableHead>Last</TableHead></TableRow></TableHeader>
            <TableBody>{products.map((p: Dict, i: number) => (
              <TableRow key={i}><TableCell><Prod sku={p.sku}>{p.sku ?? p.name}</Prod><div className="text-xs text-muted-foreground">{p.name}{p._sage ? " · Sage history" : ""}</div></TableCell>
                <TableCell className="text-right">{num(p.quantity)}</TableCell><TableCell className="text-right"><Amount value={p.amount} /></TableCell><TableCell className="whitespace-nowrap text-xs">{fmtDate(p.last_date)}</TableCell></TableRow>))}</TableBody></Table>
        </TabsContent>
        <TabsContent value="history">
          <H right={histBox}>Every invoice (newest first) - open one for what was sold and how it was paid</H>
          <Table><TableBody>{history.map((h: Dict) => (
            <TableRow key={h.invoice_number}><TableCell><SageInv number={h.invoice_number} openingId={h.opening_invoice_id} /></TableCell>
              <TableCell className="whitespace-nowrap text-xs">{fmtDate(h.invoice_date)}</TableCell><TableCell className="text-xs">{h.lines} line(s)</TableCell>
              <TableCell className="text-right"><Amount value={h.amount} /></TableCell></TableRow>))}</TableBody></Table>
        </TabsContent>
        <TabsContent value="receipts">
          <Table><TableBody>{d.receipts.map((r: Dict) => (
            <TableRow key={r.id}><TableCell><DrillLink to={{ type: "receipt", id: r.id, label: r.receipt_number }}>{r.receipt_number}</DrillLink></TableCell>
              <TableCell className="text-xs">{fmtDate(r.receipt_date)} · {r.method?.toLowerCase()} {r.reference}</TableCell><TableCell className="text-right"><Amount value={r.amount} /></TableCell></TableRow>))}</TableBody></Table>
        </TabsContent>
        <TabsContent value="loans">
          {d.loans.map((l: Dict) => (
            <div key={l.id} className="flex justify-between text-xs"><DrillLink to={{ type: "loan", id: l.id, label: l.loan_number }}>{l.loan_number} · {l.sku}</DrillLink><span>{num(l.outstanding)} still out</span></div>))}
        </TabsContent>
      </Tabs>
    </div>
  );
}

function SupplierBody({ id }: { id: string }) {
  return <Load path={`/suppliers/${id}/overview`}>{(d) => <SupplierContent d={d} />}</Load>;
}

function SupplierContent({ d }: { d: Dict }) {
  const [bills, box] = useListFilter<Dict>(d.bills, "Search bills");
  const [sageBills, sageBox] = useListFilter<Dict>(d.sage_bills ?? [], "Search invoices");
  const products = [...(d.products ?? []), ...(d.sage_products ?? []).map((p: Dict) => ({ ...p, _sage: true }))];
  return (
    <div className="space-y-3 text-sm">
      <Facts items={[["Supplier", d.supplier.name], ["Sage ID", d.supplier.supplier_code], ["We owe", <Amount value={d.balance} bold />], ["Overdue", <Amount value={d.overdue} />],
        ["Terms", d.supplier.payment_terms], ["Phone", d.supplier.phone]]} />
      <Tabs defaultValue="bills">
        <TabsList><TabsTrigger value="bills">Bills ({d.bills.length})</TabsTrigger><TabsTrigger value="history">Paid in Sage ({(d.sage_bills ?? []).length})</TabsTrigger><TabsTrigger value="products">What we buy</TabsTrigger><TabsTrigger value="payments">Payments ({d.payments.length})</TabsTrigger></TabsList>
        <TabsContent value="bills">
          <H right={box}>Bills</H>
          <Table><TableBody>{bills.map((b: Dict) => (
            <TableRow key={b.id}><TableCell><DrillLink to={{ type: "bill", id: b.id, label: b.bill_number }}>{b.bill_number}</DrillLink><div className="text-[11px] text-muted-foreground">{b.supplier_invoice_number}</div></TableCell>
              <TableCell className="whitespace-nowrap text-xs">{fmtDate(b.bill_date)}</TableCell><TableCell className="text-right"><Amount value={b.total} /></TableCell>
              <TableCell className="text-right"><Amount value={b.balance} blankZero /></TableCell></TableRow>))}</TableBody></Table>
        </TabsContent>
        <TabsContent value="history">
          <H right={sageBox}>Supplier invoices settled in Sage before go-live</H>
          <Table><TableBody>{sageBills.map((b: Dict) => (
            <TableRow key={b.bill_number}><TableCell><DrillLink to={{ type: "sagebill", id: `${b.bill_number}|${d.supplier.id}`, label: b.bill_number }}>{b.bill_number}</DrillLink>
              <div className="text-[11px] text-muted-foreground">{b.lines} line{b.lines === 1 ? "" : "s"}{b.quantity ? ` · ${num(b.quantity)} units` : ""}</div></TableCell>
              <TableCell className="whitespace-nowrap text-xs">{fmtDate(b.bill_date)}</TableCell><TableCell className="text-right"><Amount value={b.amount} /></TableCell></TableRow>))}</TableBody></Table>
        </TabsContent>
        <TabsContent value="products">
          <Table><TableBody>{products.map((p: Dict, i: number) => (
            <TableRow key={i}><TableCell><Prod sku={p.sku}>{p.sku ?? p.name}</Prod><div className="text-xs text-muted-foreground">{p.name}{p._sage ? " · Sage history" : ""}</div></TableCell>
              <TableCell className="text-right">{num(p.quantity)}</TableCell><TableCell className="text-right"><Amount value={p.amount} /></TableCell><TableCell className="whitespace-nowrap text-xs">{fmtDate(p.last_date)}</TableCell></TableRow>))}</TableBody></Table>
        </TabsContent>
        <TabsContent value="payments">
          <Table><TableBody>{d.payments.map((p: Dict) => (
            <TableRow key={p.id}><TableCell><DrillLink to={{ type: "payment", id: p.id, label: p.payment_number }}>{p.payment_number}</DrillLink></TableCell><TableCell className="text-xs">{fmtDate(p.payment_date)} · {p.reference}</TableCell>
              <TableCell className="text-right"><Amount value={p.amount} /></TableCell></TableRow>))}</TableBody></Table>
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stock: product -> batch -> movement -> document -> journal
// ---------------------------------------------------------------------------

function Movements({ rows, showSku }: { rows: Dict[]; showSku?: boolean }) {
  const [list, box] = useListFilter<Dict>(rows, "Search movements");
  return (
    <>
      {box && <div className="mb-2 flex justify-end">{box}</div>}
      <Table>
        <TableHeader><TableRow><TableHead>Date</TableHead><TableHead>Movement</TableHead><TableHead>Customer / supplier</TableHead><TableHead className="text-right">Qty</TableHead><TableHead className="text-right">Cost</TableHead></TableRow></TableHeader>
        <TableBody>{list.map((m) => (
          <TableRow key={m.id}>
            <TableCell className="whitespace-nowrap text-xs">{fmtDate(m.txn_date)}</TableCell>
            <TableCell className="text-xs"><div>{m.txn_type.replace(/_/g, " ").toLowerCase()} <DrillLink to={sourceTarget(m.source_type, m.source_id)}>{m.reference}</DrillLink></div>
              <div className="text-muted-foreground">{showSku && <><Prod sku={m.sku} /> </>}{m.batch_number && <>batch <Bat id={m.batch_id} n={m.batch_number} /></>}{m.journal_id && <> · <J id={m.journal_id} n={m.journal_number ?? "journal"} /></>}</div></TableCell>
            <TableCell className="text-xs">{m.customer_id ? <Cust id={m.customer_id} name={m.customer_name} /> : m.supplier_id ? <Sup id={m.supplier_id} name={m.supplier_name} /> : m.reason}</TableCell>
            <TableCell className={`text-right ${Number(m.quantity) < 0 ? "text-red-600" : ""}`}>{num(m.quantity)}</TableCell>
            <TableCell className="text-right"><Amount value={m.total_cost} /></TableCell>
          </TableRow>
        ))}</TableBody>
      </Table>
    </>
  );
}

function ProductBody({ sku }: { sku: string }) {
  const [range, setRange] = useState({ from: `${new Date().getFullYear() - 1}-01-01`, to: today() });
  return (
    <Load path={`/products/${encodeURIComponent(sku)}/movements`} params={range}>{(d) => <ProductContent d={d} range={range} setRange={setRange} />}</Load>
  );
}

function ProductContent({ d, range, setRange }: { d: Dict; range: { from: string; to: string }; setRange: (r: { from: string; to: string }) => void }) {
  const sage = d.sage ?? { sales: [], buyers: [], costing: [], purchases: [] };
  const aceBuyers: Record<string, Dict> = {};
  d.movements.filter((m: Dict) => m.txn_type === "SALE" && m.customer_id).forEach((m: Dict) => {
    const b = (aceBuyers[m.customer_id] ??= { customer_id: m.customer_id, customer_name: m.customer_name, quantity: 0, amount: null, source: "ACE" });
    b.quantity += -Number(m.quantity);
  });
  const buyersAll = [...Object.values(aceBuyers), ...sage.buyers.map((b: Dict) => ({ ...b, source: "Sage" }))];
  const [buyers, buyerBox] = useListFilter<Dict>(buyersAll, "Search customers");
  const [sales, salesBox] = useListFilter<Dict>(sage.sales, "Search invoices, customers");
  const [costing, costBox] = useListFilter<Dict>(sage.costing, "Search dates");
  const p = d.product;
  return (
    <div className="space-y-3 text-sm">
      <Facts cols={4} items={[["Item", p.sku], ["Description", p.name], ["On hand", num(d.on_hand.quantity)], ["Stock value", <Amount value={d.on_hand.value} />],
        ["Sales price", p.standard_price ? naira(p.standard_price) : null], ["Unit", p.uom], ["Reorder at", p.reorder_level != null ? num(p.reorder_level) : null], ["Status", p.status?.toLowerCase()]]} />
      <Tabs defaultValue="buyers">
        <TabsList className="flex-wrap">
          <TabsTrigger value="buyers">Who bought it ({buyersAll.length})</TabsTrigger>
          <TabsTrigger value="sales">Sales ({sage.sales.length}{sage.sales.length >= 300 ? "+" : ""})</TabsTrigger>
          <TabsTrigger value="movements">Stock movements</TabsTrigger>
          <TabsTrigger value="batches">Batches ({d.batches.length})</TabsTrigger>
          <TabsTrigger value="purchases">Purchases ({sage.purchases.length})</TabsTrigger>
        </TabsList>
        <TabsContent value="buyers">
          <H right={buyerBox}>Customers who bought this item</H>
          {buyers.length === 0 ? <p className="text-xs text-muted-foreground">No sales recorded.</p> : (
            <Table><TableHeader><TableRow><TableHead>Customer</TableHead><TableHead className="text-right">Qty</TableHead><TableHead className="text-right">Sales</TableHead><TableHead>Last</TableHead><TableHead>Source</TableHead></TableRow></TableHeader>
              <TableBody>{buyers.map((b, i) => (
                <TableRow key={i}><TableCell><Cust id={b.customer_id} name={b.customer_name} /></TableCell><TableCell className="text-right">{num(b.quantity)}</TableCell>
                  <TableCell className="text-right">{b.amount != null ? <Amount value={b.amount} /> : ""}</TableCell><TableCell className="whitespace-nowrap text-xs">{fmtDate(b.last_date)}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{b.source}</TableCell></TableRow>))}</TableBody></Table>)}
        </TabsContent>
        <TabsContent value="sales">
          <H right={salesBox}>Invoice lines (Sage history, newest first)</H>
          <Table><TableHeader><TableRow><TableHead>Date</TableHead><TableHead>Invoice</TableHead><TableHead>Customer</TableHead><TableHead className="text-right">Qty</TableHead><TableHead className="text-right">Amount</TableHead><TableHead className="text-right">Cost</TableHead></TableRow></TableHeader>
            <TableBody>{sales.map((s, i) => (
              <TableRow key={i}><TableCell className="whitespace-nowrap text-xs">{fmtDate(s.invoice_date)}</TableCell><TableCell><SageInv number={s.invoice_number} openingId={s.opening_invoice_id} /></TableCell>
                <TableCell className="text-xs"><Cust id={s.customer_id} name={s.customer_name} /></TableCell><TableCell className="text-right">{num(s.quantity)}</TableCell>
                <TableCell className="text-right"><Amount value={s.amount} /></TableCell><TableCell className="text-right"><Amount value={s.cost} blankZero /></TableCell></TableRow>))}</TableBody></Table>
        </TabsContent>
        <TabsContent value="movements">
          <H>ACE Books movements</H>
          <DateRange from={range.from} to={range.to} onChange={(f, t) => setRange({ from: f ?? range.from, to: t })} />
          {d.movements.length === 0 ? <p className="text-xs text-muted-foreground">None in this range.</p> : <Movements rows={d.movements} />}
          <H right={costBox}>Sage item costing (receipts, sales, adjustments)</H>
          {sage.costing.length === 0 ? <p className="text-xs text-muted-foreground">No Sage history for this item.</p> : (
            <Table><TableHeader><TableRow><TableHead>Date</TableHead><TableHead className="text-right">In</TableHead><TableHead className="text-right">Sold</TableHead><TableHead className="text-right">Adjusted</TableHead><TableHead className="text-right">Remaining</TableHead><TableHead className="text-right">Value</TableHead></TableRow></TableHeader>
              <TableBody>{costing.map((c, i) => (
                <TableRow key={i}><TableCell className="whitespace-nowrap text-xs">{fmtDate(c.txn_date)}</TableCell>
                  <TableCell className="text-right">{c.qty_received ? num(c.qty_received) : ""}</TableCell><TableCell className="text-right">{c.qty_sold ? num(c.qty_sold) : ""}</TableCell>
                  <TableCell className="text-right">{c.qty_adjusted ? num(c.qty_adjusted) : ""}</TableCell><TableCell className="text-right">{num(c.remaining_qty)}</TableCell>
                  <TableCell className="text-right"><Amount value={c.remaining_value} /></TableCell></TableRow>))}</TableBody></Table>)}
        </TabsContent>
        <TabsContent value="batches">
          {d.batches.length === 0 ? <p className="text-xs text-muted-foreground">No batches.</p> : (
            <Table><TableHeader><TableRow><TableHead>Batch</TableHead><TableHead>Expiry</TableHead><TableHead>Status</TableHead><TableHead className="text-right">On hand</TableHead><TableHead className="text-right">Value</TableHead></TableRow></TableHeader>
              <TableBody>{d.batches.map((b: Dict) => (
                <TableRow key={b.id}><TableCell><Bat id={b.id} n={b.batch_number} /></TableCell><TableCell className={`text-xs ${b.expiry_date && b.expiry_date < today() ? "text-red-600" : ""}`}>{fmtDate(b.expiry_date)}</TableCell>
                  <TableCell><StatusBadge status={b.status} /></TableCell><TableCell className="text-right">{num(b.on_hand)}</TableCell><TableCell className="text-right"><Amount value={b.value} /></TableCell></TableRow>))}</TableBody></Table>)}
        </TabsContent>
        <TabsContent value="purchases">
          {sage.purchases.length === 0 ? <p className="text-xs text-muted-foreground">No purchases recorded.</p> : (
            <Table><TableHeader><TableRow><TableHead>Date</TableHead><TableHead>Supplier invoice</TableHead><TableHead>Supplier</TableHead><TableHead className="text-right">Qty</TableHead><TableHead className="text-right">Amount</TableHead></TableRow></TableHeader>
              <TableBody>{sage.purchases.map((p: Dict, i: number) => (
                <TableRow key={i}><TableCell className="whitespace-nowrap text-xs">{fmtDate(p.bill_date)}</TableCell>
                  <TableCell className="text-xs"><DrillLink to={p.opening_bill_id ? { type: "bill", id: p.opening_bill_id, label: p.bill_number } : { type: "sagebill", id: `${p.bill_number}|${p.supplier_id ?? ""}`, label: p.bill_number }}>{p.bill_number}</DrillLink></TableCell>
                  <TableCell className="text-xs"><Sup id={p.supplier_id} name={p.supplier_name} /></TableCell><TableCell className="text-right">{p.quantity != null ? num(p.quantity) : "—"}</TableCell>
                  <TableCell className="text-right"><Amount value={p.amount} /></TableCell></TableRow>))}</TableBody></Table>)}
        </TabsContent>
      </Tabs>
    </div>
  );
}

function BatchEdit({ b, onDone }: { b: Dict; onDone: () => void }) {
  const [f, setF] = useState({ batch_number: b.batch_number ?? "", manufacture_date: b.manufacture_date ?? "", expiry_date: b.expiry_date ?? "" });
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    const ok = await act(() => books.put(`/inventory/batches/${b.id}`, f), "Batch updated");
    setBusy(false);
    if (ok) onDone();
  };
  return (
    <div className="grid grid-cols-1 gap-2 rounded-lg border p-3 sm:grid-cols-4">
      <div><div className="text-[11px] text-muted-foreground">Batch number (as printed)</div><Input className="h-8" value={f.batch_number} onChange={(e) => setF({ ...f, batch_number: e.target.value })} /></div>
      <div><div className="text-[11px] text-muted-foreground">Man. date</div><Input className="h-8" type="date" value={f.manufacture_date ?? ""} onChange={(e) => setF({ ...f, manufacture_date: e.target.value })} /></div>
      <div><div className="text-[11px] text-muted-foreground">Exp. date</div><Input className="h-8" type="date" value={f.expiry_date ?? ""} onChange={(e) => setF({ ...f, expiry_date: e.target.value })} /></div>
      <div className="flex items-end"><Button size="sm" disabled={busy || !f.batch_number.trim()} onClick={save}>Save</Button></div>
    </div>
  );
}

function BatchBody({ id }: { id: string }) {
  const [editing, setEditing] = useState(false);
  const qc = useQueryClient();
  return (
    <Load path={`/inventory/batches/${id}/trace`}>{(d) => (
      <div className="space-y-3 text-sm">
        <Facts cols={4} items={[["Product", <Prod sku={d.batch.sku} />], ["Batch number", d.batch.batch_number], ["Lot (Sage)", d.batch.lot_code !== d.batch.batch_number ? d.batch.lot_code : null],
          ["Man. date", fmtDate(d.batch.manufacture_date)], ["Exp. date", fmtDate(d.batch.expiry_date)], ["Status", <StatusBadge status={d.batch.status} />],
          ["On hand", num(d.on_hand?.quantity)], ["Value", <Amount value={d.on_hand?.value} />]]} />
        {editing ? <BatchEdit b={d.batch} onDone={() => { setEditing(false); qc.invalidateQueries({ queryKey: ["books"] }); }} />
          : <Button size="sm" variant="outline" onClick={() => setEditing(true)}><Pencil className="mr-1 h-3.5 w-3.5" />Edit batch number / dates</Button>}
        <H>Who received this batch</H>
        {d.customers.length === 0 ? <p className="text-xs text-muted-foreground">No customer has received it in ACE Books yet (Sage sales history is per item — see the product).</p> : d.customers.map((c: Dict) => (
          <div key={c.customer_id} className="flex justify-between text-xs"><Cust id={c.customer_id} name={c.customer_name} /><span>{num(c.quantity_sold)} sold{Number(c.quantity_on_loan) ? `, ${num(c.quantity_on_loan)} on loan` : ""}</span></div>))}
        <H>Movements</H>
        <Movements rows={d.movements.map((m: Dict) => ({ ...m, batch_number: undefined }))} />
      </div>
    )}</Load>
  );
}

function AdjustmentBody({ id }: { id: string }) {
  return (
    <Load path={`/inventory/adjustments/${id}`}>{(a) => (
      <div className="space-y-3 text-sm">
        <Facts items={[["Number", a.adjustment_number], ["Date", fmtDate(a.adjustment_date)], ["Reason", a.reason_code.replace(/_/g, " ").toLowerCase()], ["Status", <StatusBadge status={a.status} />],
          ["Raised by", a.created_by], ["Approved by", a.posted_by], ["Value", <Amount value={a.total_value} />], ["Journal", <J id={a.journal_id} />]]} />
        <Table><TableBody>{a.lines.map((l: Dict) => (
          <TableRow key={l.id}><TableCell><Prod sku={l.sku} /> {l.batch_id && <Bat id={l.batch_id} n={l.batch_number} />}<div className="text-xs text-muted-foreground">{l.reason}</div></TableCell>
            <TableCell className="text-right">{num(l.quantity)}</TableCell><TableCell className="text-right"><Amount value={l.value} blankZero /></TableCell></TableRow>))}</TableBody></Table>
      </div>
    )}</Load>
  );
}

function LoanBody({ id }: { id: string }) {
  return (
    <Load path={`/inventory/loans/${encodeURIComponent(id)}`}>{(l) => (
      <div className="space-y-3 text-sm">
        <Facts items={[["Loan", l.loan_number], ["Customer", <Cust id={l.customer_id} name={l.customer_name} />], ["Product", <Prod sku={l.sku} />],
          ["Batch", <Bat id={l.batch_id} n={l.batch_number} />], ["Lent", num(l.quantity)], ["Still out", num(l.outstanding)], ["Date", fmtDate(l.loan_date)],
          ["Due back", fmtDate(l.expected_return_date)], ["Status", <StatusBadge status={l.status} />]]} />
        {l.returns?.length > 0 && (<><H>Returns</H>{l.returns.map((r: Dict) => (
          <div key={r.id} className="flex justify-between text-xs"><span>{fmtDate(r.return_date)} · batch <Bat id={r.batch_id} n={r.batch_number} /></span><span>{num(r.quantity)}</span></div>))}</>)}
      </div>
    )}</Load>
  );
}

function AssetBody({ id }: { id: string }) {
  return (
    <Load path={`/assets/${id}`}>{(a) => (
      <div className="space-y-3 text-sm">
        <Facts items={[["Asset", `${a.asset_code} · ${a.name}`], ["Category", a.category_name], ["Acquired", fmtDate(a.acquisition_date)], ["Status", <StatusBadge status={a.status} />],
          ["Cost", <Amount value={a.cost} />], ["Net book value", <Amount value={a.net_book_value} bold />],
          ["Acquisition journal", <J id={a.acquisition_journal_id} />], ["Disposal journal", a.disposal_journal_id ? <J id={a.disposal_journal_id} /> : null]]} />
      </div>
    )}</Load>
  );
}
