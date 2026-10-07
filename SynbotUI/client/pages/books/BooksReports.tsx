import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowUpRight, ChevronRight, FileSpreadsheet, Printer, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { BooksShell } from "@/components/books/BooksShell";
import { sourceTarget, useDrill } from "@/components/books/drill-context";
import { AccountPick, Amount, BankSelect, CustomerPick, DateRange, Empty, ErrorNote, Loading, ProductPick, Section, SupplierPick, useBooks } from "@/components/books/kit";
import { Dict, downloadCsv, fmtDate, num, today, yearStart } from "@/lib/books-api";

type Param = "range" | "asOf" | "account" | "bank" | "customer" | "supplier" | "sku" | "withBalance";
type Entry = { name: string; desc?: string } & ({ key: string; params?: Param[] } | { to: string } | { na: string });

/** The essential report set from the finance study and client meetings. More Sage reports
 *  (working TB, reorder worksheet, vendor/customer lists, ...) exist in /fin/report-center and can be added here later. */
const CATALOG: { area: string; items: Entry[] }[] = [
  { area: "Financial Statements", items: [
    { name: "Balance Sheet", to: "/finance/books/statements?tab=bs" },
    { name: "Income Statement (Profit & Loss)", to: "/finance/books/statements?tab=pl" },
    { name: "Cash Flow", to: "/finance/books/statements?tab=cf" },
    { name: "Retained Earnings", to: "/finance/books/statements?tab=re" },
    { name: "Budget vs Actual", to: "/finance/books/statements?tab=budget" },
  ] },
  { area: "General Ledger", items: [
    { name: "Chart of Accounts", key: "chart-of-accounts", params: ["asOf"] },
    { name: "Trial Balance", to: "/finance/books/ledger?tab=tb" },
    { name: "General Ledger", to: "/finance/books/ledger?tab=gl" },
    { name: "General Journal", to: "/finance/books/statements?tab=journals&kind=general" },
    { name: "Account Register (e.g. cash / bank)", key: "account-register", params: ["range", "account"] },
  ] },
  { area: "Sales & Receivables", items: [
    { name: "Sales Analysis (revenue → month → customer → invoice)", key: "sales-analysis", params: ["range"], desc: "Click a month, then a customer, then an invoice to see what was sold and its journal." },
    { name: "Aged Receivables", to: "/finance/books/sales?tab=aging" },
    { name: "Customer Ledgers", key: "customer-ledgers", params: ["range", "customer"] },
    { name: "Customer Statement", to: "/finance/books/sales?tab=statement" },
    { name: "Invoice Register", key: "invoice-register", params: ["range"] },
    { name: "Receipts Register", key: "receipts-register", params: ["range"] },
    { name: "Items Sold to Customers (who bought what)", key: "items-sold-to-customers", params: ["range"] },
    { name: "Sales Journal", to: "/finance/books/statements?tab=journals&kind=sales" },
    { name: "Cash Receipts Journal", to: "/finance/books/statements?tab=journals&kind=cash-receipts" },
  ] },
  { area: "Purchases & Payables", items: [
    { name: "Aged Payables", to: "/finance/books/purchases?tab=aging" },
    { name: "Vendor Ledgers", key: "vendor-ledgers", params: ["range", "supplier"] },
    { name: "Purchase Register", key: "purchase-register", params: ["range"] },
    { name: "Cash Requirements (bills due)", key: "cash-requirements", params: ["asOf"] },
    { name: "Purchase Journal", to: "/finance/books/statements?tab=journals&kind=purchases" },
    { name: "Cash Disbursements Journal", to: "/finance/books/statements?tab=journals&kind=cash-disbursements" },
  ] },
  { area: "Inventory", items: [
    { name: "Inventory Valuation", to: "/finance/books/stock?tab=valuation" },
    { name: "Stock Status", to: "/finance/books/stock?tab=status" },
    { name: "Inventory Unit Activity", to: "/finance/books/stock?tab=activity" },
    { name: "Item Costing (every movement at cost)", key: "item-costing", params: ["range", "sku"] },
    { name: "Inventory Profitability (margin per item)", key: "inventory-profitability", params: ["range"] },
    { name: "Batches & Expiry", to: "/finance/books/stock?tab=batches" },
    { name: "Stock on Loan", to: "/finance/books/stock?tab=loans" },
    { name: "Cost of Goods Sold Journal", to: "/finance/books/statements?tab=journals&kind=cogs" },
    { name: "Inventory Adjustment Journal", to: "/finance/books/statements?tab=journals&kind=inventory-adjustments" },
  ] },
  { area: "Banking & Control", items: [
    { name: "Bank Reconciliation", to: "/finance/books/banking?tab=reconcile" },
    { name: "Outstanding Items (deposits in transit / unpresented cheques)", key: "outstanding-items", params: ["asOf", "bank"] },
    { name: "Fixed Asset Register", to: "/finance/books/assets" },
    { name: "Audit Trail", key: "audit-trail", params: ["range"] },
  ] },
];

const ALL = CATALOG.flatMap((a) => a.items.map((i) => ({ ...i, area: a.area })));

export default function BooksReports() {
  const [params, setParams] = useSearchParams();
  const [filter, setFilter] = useState("");
  const key = params.get("r");
  const current = ALL.find((e) => "key" in e && e.key === key) as (Entry & { key: string; params?: Param[]; area: string }) | undefined;
  const set = (patch: Record<string, string | null>) => {
    const p = new URLSearchParams(params);
    Object.entries(patch).forEach(([k, v]) => (v ? p.set(k, v) : p.delete(k)));
    setParams(p, { replace: true });
  };
  const counts = { table: ALL.filter((e) => "key" in e).length, page: ALL.filter((e) => "to" in e).length };
  return (
    <BooksShell title="Report Center" subtitle={`Essential finance reports · ${counts.table + counts.page} available`}>
      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <Section className="self-start lg:sticky lg:top-4">
          <div className="relative mb-3"><Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input className="h-9 pl-8" placeholder="Find a report" value={filter} onChange={(e) => setFilter(e.target.value)} /></div>
          <div className="max-h-[70vh] space-y-4 overflow-y-auto pr-1">
            {CATALOG.map((a) => {
              const items = a.items.filter((i) => !filter || `${a.area} ${i.name}`.toLowerCase().includes(filter.toLowerCase()));
              if (!items.length) return null;
              return (
                <div key={a.area}>
                  <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{a.area}</div>
                  <ul className="space-y-0.5">
                    {items.map((i) => (
                      <li key={i.name}>
                        {"key" in i ? (
                          <button onClick={() => set({ r: i.key, month: null, customer_id: null })}
                                  className={`flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted ${key === i.key ? "bg-muted font-semibold" : ""}`}>
                            {i.name}<ChevronRight className="h-3.5 w-3.5 shrink-0 opacity-50" />
                          </button>
                        ) : "to" in i ? (
                          <Link to={i.to} className="flex items-center justify-between rounded-md px-2 py-1.5 text-sm hover:bg-muted">{i.name}<ArrowUpRight className="h-3.5 w-3.5 shrink-0 opacity-50" /></Link>
                        ) : (
                          <div className="rounded-md px-2 py-1.5 text-sm text-muted-foreground/70" title={i.na}>{i.name}<div className="text-[11px]">{i.na}</div></div>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>
        </Section>
        <div className="min-w-0">
          {current ? <ReportView entry={current} params={params} set={set} /> : (
            <Section title="Choose a report">
              <p className="text-sm text-muted-foreground">
                Reports on the left marked <ChevronRight className="inline h-3.5 w-3.5" /> open here as tables you can filter, download (CSV opens in Excel) and print.
                Those marked <ArrowUpRight className="inline h-3.5 w-3.5" /> are the full financial statements and working screens.
                Every underlined figure or reference opens the record behind it — invoice, customer, product, batch, journal, account — so you can follow a number back to where it came from.
              </p>
            </Section>
          )}
        </div>
      </div>
    </BooksShell>
  );
}

function ReportView({ entry, params, set }: { entry: { key: string; name: string; params?: Param[]; desc?: string }; params: URLSearchParams; set: (p: Record<string, string | null>) => void }) {
  const drill = useDrill();
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<Record<string, Dict | null>>({});
  const ps = entry.params ?? [];
  const from = params.get("from") ?? yearStart();
  const to = params.get("to") ?? today();
  const q: Dict = { from, to, as_of: params.get("as_of") ?? today(), month: params.get("month") ?? undefined,
    customer_id: params.get("customer_id") ?? undefined, supplier_id: params.get("supplier_id") ?? undefined,
    account_id: params.get("account_id") ?? undefined, bank_account_id: params.get("bank_account_id") ?? undefined,
    sku: params.get("sku") ?? undefined, with_balance: params.get("with_balance") ?? undefined };
  const needsAccount = ps.includes("account") && entry.key === "account-register" && !q.account_id;
  const { data, isLoading, error } = useBooks<Dict>(["report-center", entry.key, q], `/report-center/${entry.key}`, q, !needsAccount);
  const rows: Dict[] = useMemo(() => {
    const r = data?.rows ?? [];
    if (!search) return r;
    const s = search.toLowerCase();
    return r.filter((x) => Object.values(x).some((v) => v != null && String(v).toLowerCase().includes(s)));
  }, [data, search]);
  const cols: Dict[] = data?.columns ?? [];
  const click = (c: Dict, row: Dict) => {
    const id = row[c.id];
    if (id == null || id === "") return;
    if (c.link === "drill:month") return set({ month: String(id), customer_id: null });
    if (c.link === "drill:customer") return set({ customer_id: String(id) });
    if (!drill) return;
    if (c.link === "source") { const t = sourceTarget(row.source_type, String(id)); if (t) drill.open(t); return; }
    if (c.link === "doc") return drill.open({ type: row.link, id: String(id), label: row.number });
    drill.open({ type: c.link, id: String(id), label: row[c.key] != null ? String(row[c.key]) : undefined });
  };
  const cell = (c: Dict, row: Dict) => {
    const v = row[c.key];
    const content = c.type === "money" ? (v == null ? "" : <Amount value={v} />) : c.type === "qty" ? (v == null ? "" : num(v, Number(v) % 1 ? 2 : 0))
      : c.type === "date" ? fmtDate(v) : c.type === "datetime" ? (v ? new Date(v).toLocaleString("en-GB") : "") : v == null ? "" : String(v);
    if (c.link && row[c.id] != null && row[c.id] !== "" && content !== "") {
      return <button className="text-left text-primary underline-offset-2 hover:underline" onClick={() => click(c, row)}>{content}</button>;
    }
    return content;
  };
  const sa = entry.key === "sales-analysis";
  return (
    <Section title={data?.title ?? entry.name}
             actions={<>
               <Button size="sm" variant="outline" disabled={!rows.length}
                       onClick={() => downloadCsv(`${entry.key}-${q.as_of ?? to}.csv`, rows, cols.map((c) => ({ key: c.key, label: c.label })))}>
                 <FileSpreadsheet className="mr-1.5 h-4 w-4" />Download (Excel CSV)</Button>
               <Button size="sm" variant="outline" onClick={() => window.print()}><Printer className="mr-1.5 h-4 w-4" />Print / PDF</Button>
             </>}>
      <div className="mb-3 space-y-3">
        {data?.subtitle && <p className="text-sm text-muted-foreground">{data.subtitle}</p>}
        {entry.desc && <p className="text-xs text-muted-foreground">{entry.desc}</p>}
        <div className="flex flex-wrap items-end gap-3">
          {ps.includes("range") && <DateRange from={from} to={to} onChange={(f, t) => set({ from: f ?? from, to: t })} />}
          {ps.includes("asOf") && <DateRange single to={q.as_of} onChange={(_, t) => set({ as_of: t })} />}
          {ps.includes("account") && <div className="w-72"><AccountPick label="Account" value={picked.account ?? null}
            onChange={(a) => { setPicked({ ...picked, account: a }); set({ account_id: a?.id ?? null }); }} /></div>}
          {ps.includes("bank") && <div className="w-64"><BankSelect label="Bank account (all if blank)" value={q.bank_account_id ?? ""} onChange={(v) => set({ bank_account_id: v || null })} /></div>}
          {ps.includes("customer") && <div className="w-64"><CustomerPick label="Customer (all if blank)" value={picked.customer ?? null}
            onChange={(c) => { setPicked({ ...picked, customer: c }); set({ customer_id: c ? String(c.id) : null }); }} /></div>}
          {ps.includes("supplier") && <div className="w-64"><SupplierPick label="Vendor (all if blank)" value={picked.supplier ?? null}
            onChange={(s) => { setPicked({ ...picked, supplier: s }); set({ supplier_id: s ? String(s.id) : null }); }} /></div>}
          {ps.includes("sku") && <div className="w-64"><ProductPick label="Item (all if blank)" value={picked.sku ?? null}
            onChange={(p) => { setPicked({ ...picked, sku: p }); set({ sku: p?.sku ?? null }); }} /></div>}
          {ps.includes("withBalance") && <label className="flex items-center gap-1 pb-2 text-xs"><input type="checkbox" checked={!!q.with_balance}
            onChange={(e) => set({ with_balance: e.target.checked ? "true" : null })} />only with a balance</label>}
          <div className="relative ml-auto w-56"><Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input className="h-9 pl-8" placeholder="Filter rows" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
        </div>
        {sa && (
          <div className="flex flex-wrap items-center gap-1 text-sm">
            <button className="text-primary hover:underline" onClick={() => set({ month: null, customer_id: null })}>All months</button>
            {q.month && <><ChevronRight className="h-3.5 w-3.5" /><button className="text-primary hover:underline" onClick={() => set({ customer_id: null })}>{q.month}</button></>}
            {q.customer_id && <><ChevronRight className="h-3.5 w-3.5" /><span>customer #{q.customer_id}</span></>}
          </div>
        )}
      </div>
      {needsAccount && <Empty>Choose an account to see its register.</Empty>}
      {isLoading && !needsAccount && <Loading />}<ErrorNote error={error} />
      {data && (rows.length === 0 ? (
        <Empty>No rows for this selection.{sa || /sold|sales|profitab|receipts|purchased|check/.test(entry.key)
          ? " ACE Books transactions start at go-live (1 Jul 2026); earlier history is in the Sage opening balances." : ""}</Empty>
      ) : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader><TableRow>{cols.map((c) => <TableHead key={c.key} className={`whitespace-nowrap ${["money", "qty"].includes(c.type) ? "text-right" : ""}`}>{c.label}</TableHead>)}</TableRow></TableHeader>
            <TableBody>
              {rows.slice(0, 2000).map((r, i) => (
                <TableRow key={i} className={r.name === "NET INCOME" || r.line?.startsWith?.("TOTAL") ? "font-semibold" : ""}>
                  {cols.map((c) => <TableCell key={c.key} className={`${["money", "qty"].includes(c.type) ? "text-right" : ""} ${c.type === "date" ? "whitespace-nowrap" : ""} text-sm`}>{cell(c, r)}</TableCell>)}
                </TableRow>
              ))}
              {Object.keys(data.totals ?? {}).length > 0 && !search && (
                <TableRow className="font-semibold">
                  {cols.map((c, i) => <TableCell key={c.key} className="text-right">{i === 0 ? <span className="float-left">Total</span> : data.totals[c.key] != null ? <Amount value={data.totals[c.key]} /> : ""}</TableCell>)}
                </TableRow>
              )}
            </TableBody>
          </Table>
          <p className="mt-2 text-xs text-muted-foreground">{rows.length.toLocaleString()} rows{rows.length > 2000 ? " — showing the first 2,000; the download contains all of them" : ""}.</p>
        </div>
      ))}
    </Section>
  );
}
