import { ReactNode, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Printer } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { BooksShell } from "@/components/books/BooksShell";
import { sageLineTarget, sourceTarget } from "@/components/books/drill-context";
import { Input } from "@/components/ui/input";
import { AccountSheet, Amount, CsvButton, DateRange, DrillLink, Empty, ErrorNote, JournalSheet, Loading, Section, useBooks } from "@/components/books/kit";
import { Dict, fmtDate, monthStart, today, yearStart } from "@/lib/books-api";

/** Financial statements and Sage-style journals. Every figure drills to its ledger lines. */
export default function BooksStatements() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "pl";
  const [account, setAccount] = useState<Dict | null>(null);
  const [drillRange, setDrillRange] = useState({ from: yearStart(), to: today() });
  const drill = (a: Dict, from: string, to: string) => { if (a.account_id) { setDrillRange({ from, to }); setAccount({ id: a.account_id, code: a.code, name: a.name }); } };
  return (
    <BooksShell title="Reports" actions={<Button size="sm" variant="outline" onClick={() => window.print()}><Printer className="mr-1 h-4 w-4" />Print</Button>}>
      <Tabs value={tab} onValueChange={(v) => { const p = new URLSearchParams(params); p.set("tab", v); setParams(p, { replace: true }); }}>
        <TabsList className="flex-wrap">
          <TabsTrigger value="pl">Income statement</TabsTrigger>
          <TabsTrigger value="bs">Balance sheet</TabsTrigger>
          <TabsTrigger value="cf">Cash flow</TabsTrigger>
          <TabsTrigger value="re">Retained earnings</TabsTrigger>
          <TabsTrigger value="budget">Budget vs actual</TabsTrigger>
          <TabsTrigger value="journals">Journals</TabsTrigger>
        </TabsList>
        <TabsContent value="pl"><IncomeStatement onDrill={drill} /></TabsContent>
        <TabsContent value="bs"><BalanceSheet onDrill={drill} /></TabsContent>
        <TabsContent value="cf"><CashFlow onDrill={drill} /></TabsContent>
        <TabsContent value="re"><RetainedEarnings /></TabsContent>
        <TabsContent value="budget"><BudgetVsActual onDrill={drill} /></TabsContent>
        <TabsContent value="journals"><JournalReports /></TabsContent>
      </Tabs>
      <AccountSheet account={account} from={drillRange.from} to={drillRange.to} onClose={() => setAccount(null)} />
    </BooksShell>
  );
}

type Drill = (a: Dict, from: string, to: string) => void;

function Line({ label, value, compare, bold, indent, onClick, border }: { label: ReactNode; value: any; compare?: any; bold?: boolean; indent?: boolean; onClick?: () => void; border?: boolean }) {
  return (
    <TableRow className={`${onClick ? "cursor-pointer hover:bg-muted/50" : ""} ${border ? "border-t-2" : ""}`} onClick={onClick}>
      <TableCell className={`${indent ? "pl-8" : ""} ${bold ? "font-semibold" : ""}`}>{label}</TableCell>
      <TableCell className="text-right"><Amount value={value} bold={bold} /></TableCell>
      {compare !== undefined && <TableCell className="text-right text-muted-foreground"><Amount value={compare} bold={bold} /></TableCell>}
    </TableRow>
  );
}

function IncomeStatement({ onDrill }: { onDrill: Drill }) {
  const [range, setRange] = useState({ from: yearStart(), to: today() });
  const [sp] = useSearchParams();
  const [compare, setCompare] = useState(sp.get("compare") === "1");
  const prior = { from: shiftYear(range.from), to: shiftYear(range.to) };
  const { data, isLoading, error } = useBooks<any>(["pl", range, compare], "/reports/income-statement",
    { ...range, ...(compare ? { compare_from: prior.from, compare_to: prior.to } : {}) });
  const cmp = data?.comparison;
  const cmpLine = (section: number, id: string) => cmp?.sections[section].lines.find((l: Dict) => l.account_id === id)?.amount ?? 0;
  const csv = data?.sections.flatMap((s: Dict) => s.lines.map((l: Dict) => ({ section: s.title, code: l.code, account: l.name, amount: l.amount })));
  return (
    <Section title="Income statement (profit & loss)" actions={<CsvButton filename={`income-statement-${range.from}-${range.to}.csv`} rows={csv} />}>
      <div className="mb-3 flex flex-wrap items-end gap-4">
        <DateRange from={range.from} to={range.to} onChange={(f, t) => setRange({ from: f ?? range.from, to: t })} />
        <div className="flex gap-1">
          <Button size="sm" variant="ghost" onClick={() => setRange({ from: monthStart(), to: today() })}>This month</Button>
          <Button size="sm" variant="ghost" onClick={() => setRange({ from: yearStart(), to: today() })}>Year to date</Button>
        </div>
        <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} />compare with same period last year</label>
      </div>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (
        <Table className="max-w-3xl">
          {cmp && <TableHeader><TableRow><TableHead /><TableHead className="text-right">{fmtDate(range.from)} – {fmtDate(range.to)}</TableHead><TableHead className="text-right">{fmtDate(prior.from)} – {fmtDate(prior.to)}</TableHead></TableRow></TableHeader>}
          <TableBody>
            {/* Sage layout: Revenues (sales, then other income) -> Total revenues; Cost of sales -> Gross profit; Expenses -> Net income */}
            {data.sections.map((s: Dict, si: number) => (s.lines.length > 0 || si === 0 || si === 2) && (
              <PLSection key={s.title} s={s} cmpTotal={cmp ? cmp.sections[si].total : undefined}
                         cmpOf={cmp ? (id: string) => cmpLine(si, id) : undefined} onDrill={(l) => onDrill(l, range.from, range.to)}
                         after={si === 2 ? <Line label="Gross profit" value={data.gross_profit} compare={cmp?.gross_profit} bold border /> :
                                si === 3 ? <Line label="Operating profit" value={data.operating_profit} compare={cmp?.operating_profit} bold border /> : null} />
            )).flatMap((el: any, si: number) => si === 1
              ? [el, <Line key="total-rev" label="Total revenues" value={data.total_revenue} compare={cmp?.total_revenue} bold border />] : [el])}
            <Line label="Net income" value={data.net_profit} compare={cmp?.net_profit} bold border />
          </TableBody>
        </Table>
      )}
      {data && (
        <div className="mt-3 flex flex-wrap gap-6 text-sm text-muted-foreground">
          <Link className="text-primary hover:underline" to={`/finance/books/reports?r=sales-analysis&from=${range.from}&to=${range.to}`}>Trace revenue → month → customer → invoice</Link>
          {data.gross_margin_pct != null && <span>Gross margin {data.gross_margin_pct}%</span>}
          {data.year_to_date && <span>Year to date (from {fmtDate(data.year_to_date.date_from)}): revenue <Amount value={data.year_to_date.revenue} /> · net profit <Amount value={data.year_to_date.net_profit} /></span>}
        </div>
      )}
    </Section>
  );
}

function PLSection({ s, cmpTotal, cmpOf, onDrill, after }: { s: Dict; cmpTotal?: any; cmpOf?: (id: string) => any; onDrill: (l: Dict) => void; after?: ReactNode }) {
  return (
    <>
      <TableRow><TableCell colSpan={cmpOf ? 3 : 2} className="pt-4 text-xs font-semibold uppercase text-muted-foreground">{s.title}</TableCell></TableRow>
      {s.lines.map((l: Dict) => <Line key={l.account_id} indent label={<span><span className="font-mono text-xs text-muted-foreground">{l.code}</span> {l.name}</span>} value={l.amount} compare={cmpOf?.(l.account_id)} onClick={() => onDrill(l)} />)}
      <Line label={`Total ${s.title.toLowerCase()}`} value={s.total} compare={cmpTotal} bold />
      {after}
    </>
  );
}

function BalanceSheet({ onDrill }: { onDrill: Drill }) {
  const [asOf, setAsOf] = useState(today());
  const { data, isLoading, error } = useBooks<any>(["bs", asOf], "/reports/balance-sheet", { as_of: asOf });
  const sec = (s: Dict) => (
    <>
      <TableRow><TableCell colSpan={2} className="pt-3 text-xs font-semibold uppercase text-muted-foreground">{s.title}</TableCell></TableRow>
      {s.lines.map((l: Dict, i: number) => <Line key={l.account_id ?? i} indent label={<span><span className="font-mono text-xs text-muted-foreground">{l.code}</span> {l.name}
        {SUBLEDGER[l.subtype] && <Link onClick={(e) => e.stopPropagation()} className="ml-2 text-[11px] text-primary hover:underline" to={SUBLEDGER[l.subtype][1]}>{SUBLEDGER[l.subtype][0]} →</Link>}</span>} value={l.amount}
        onClick={l.account_id ? () => onDrill(l, `${asOf.slice(0, 4)}-01-01`, asOf) : undefined} />)}
      <Line label={`Total ${s.title.toLowerCase()}`} value={s.total} bold />
    </>
  );
  const csv = data ? [...data.assets, ...data.liabilities, data.equity].flatMap((s: Dict) => s.lines.map((l: Dict) => ({ section: s.title, code: l.code, account: l.name, amount: l.amount }))) : undefined;
  return (
    <Section title="Balance sheet" actions={<CsvButton filename={`balance-sheet-${asOf}.csv`} rows={csv} />}>
      <DateRange single to={asOf} onChange={(_, t) => setAsOf(t)} />
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (
        <>
          <div className={`mt-2 text-sm font-medium ${data.balanced ? "text-emerald-600" : "text-red-600"}`}>{data.balanced ? "✓ Assets equal liabilities plus equity" : <>✗ Out of balance by <Amount value={data.difference} /></>}</div>
          <div className="mt-3 grid gap-6 lg:grid-cols-2">
            <Table><TableBody>{data.assets.map((s: Dict) => <SectionFrag key={s.title}>{sec(s)}</SectionFrag>)}<Line label="TOTAL ASSETS" value={data.total_assets} bold border /></TableBody></Table>
            <Table><TableBody>
              {data.liabilities.map((s: Dict) => <SectionFrag key={s.title}>{sec(s)}</SectionFrag>)}
              <Line label="Total liabilities" value={data.total_liabilities} bold border />
              {sec(data.equity)}
              <Line label="TOTAL LIABILITIES & EQUITY" value={data.total_liabilities_and_equity} bold border />
            </TableBody></Table>
          </div>
        </>
      )}
    </Section>
  );
}
const SUBLEDGER: Record<string, [string, string]> = {
  RECEIVABLE: ["by customer", "/finance/books/sales?tab=aging"],
  PAYABLE: ["by supplier", "/finance/books/purchases?tab=aging"],
  INVENTORY: ["by product & batch", "/finance/books/stock?tab=valuation"],
  FIXED_ASSET: ["asset register", "/finance/books/assets"],
  CASH: ["bank register", "/finance/books/banking"],
};
const SectionFrag = ({ children }: { children: ReactNode }) => <>{children}</>;

function CashFlow({ onDrill }: { onDrill: Drill }) {
  const [range, setRange] = useState({ from: monthStart(), to: today() });
  const { data, isLoading, error } = useBooks<any>(["cf", range], "/reports/cash-flow", range);
  const lines = (ls: Dict[]) => ls.map((l) => <Line key={l.account_id} indent label={l.name} value={l.amount} onClick={() => onDrill(l, range.from, range.to)} />);
  return (
    <Section title="Cash flow statement (indirect)">
      <DateRange from={range.from} to={range.to} onChange={(f, t) => setRange({ from: f ?? range.from, to: t })} />
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (
        <Table className="mt-3 max-w-3xl">
          <TableBody>
            <TableRow><TableCell colSpan={2} className="text-xs font-semibold uppercase text-muted-foreground">Operating activities</TableCell></TableRow>
            <Line indent label="Net profit" value={data.operating.net_profit} />
            {lines(data.operating.adjustments)}{lines(data.operating.working_capital)}
            <Line label="Net cash from operating activities" value={data.operating.total} bold />
            <TableRow><TableCell colSpan={2} className="pt-4 text-xs font-semibold uppercase text-muted-foreground">Investing activities</TableCell></TableRow>
            {lines(data.investing.lines)}<Line label="Net cash from investing activities" value={data.investing.total} bold />
            <TableRow><TableCell colSpan={2} className="pt-4 text-xs font-semibold uppercase text-muted-foreground">Financing activities</TableCell></TableRow>
            {lines(data.financing.lines)}<Line label="Net cash from financing activities" value={data.financing.total} bold />
            <Line label="Net change in cash" value={data.net_change} bold border />
            <Line label="Cash at start" value={data.opening_cash} /><Line label="Cash at end" value={data.closing_cash} bold />
          </TableBody>
        </Table>
      )}
      {data && <p className={`mt-2 text-xs ${data.reconciles ? "text-emerald-600" : "text-red-600"}`}>{data.reconciles ? "✓ Reconciles to the cash & bank accounts" : "✗ Does not reconcile to cash — check journals posting directly between cash and equity"}</p>}
    </Section>
  );
}

function RetainedEarnings() {
  const [range, setRange] = useState({ from: yearStart(), to: today() });
  const { data, isLoading, error } = useBooks<any>(["re", range], "/reports/retained-earnings", range);
  return (
    <Section title="Statement of retained earnings">
      <DateRange from={range.from} to={range.to} onChange={(f, t) => setRange({ from: f ?? range.from, to: t })} />
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (
        <Table className="mt-3 max-w-2xl"><TableBody>
          <Line label={`Retained earnings at ${fmtDate(data.date_from)}`} value={data.opening} />
          <Line label="Adjustments posted to retained earnings" value={data.adjustments} />
          <Line label="Net profit for the period" value={data.net_profit} />
          {Number(data.closed_to_retained_earnings) !== 0 && <Line label="(of which closed at year end)" value={data.closed_to_retained_earnings} indent />}
          <Line label={`Retained earnings at ${fmtDate(data.date_to)}`} value={data.closing} bold border />
        </TableBody></Table>
      )}
    </Section>
  );
}

function BudgetVsActual({ onDrill }: { onDrill: Drill }) {
  const [range, setRange] = useState({ from: yearStart(), to: today() });
  const { data: budgets } = useBooks<Dict[]>(["budgets"], "/budgets");
  const [budget, setBudget] = useState("");
  const chosen = budget || budgets?.find((b) => b.status === "APPROVED")?.id || budgets?.[0]?.id || "";
  const { data, isLoading, error } = useBooks<any>(["bva", chosen, range], "/reports/budget-vs-actual", { budget_id: chosen, ...range }, !!chosen);
  return (
    <Section title="Budget vs actual" actions={<CsvButton filename="budget-vs-actual.csv" rows={data?.rows} />}>
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <select className="h-9 rounded-md border bg-background px-2 text-sm" value={chosen} onChange={(e) => setBudget(e.target.value)}>
          {(budgets ?? []).map((b) => <option key={b.id} value={b.id}>{b.name} ({b.status.toLowerCase()})</option>)}
        </select>
        <DateRange from={range.from} to={range.to} onChange={(f, t) => setRange({ from: f ?? range.from, to: t })} />
      </div>
      {budgets && budgets.length === 0 && <Empty>No budgets yet — create one under Setup → Budgets.</Empty>}
      {isLoading && chosen && <Loading />}<ErrorNote error={error} />
      {data && (
        <Table>
          <TableHeader><TableRow><TableHead>Account</TableHead><TableHead className="text-right">Budget</TableHead><TableHead className="text-right">Actual</TableHead><TableHead className="text-right">Variance</TableHead><TableHead className="text-right">%</TableHead></TableRow></TableHeader>
          <TableBody>{data.rows.map((r: Dict) => (
            <TableRow key={r.account_id} className="cursor-pointer hover:bg-muted/50" onClick={() => onDrill(r, range.from, range.to)}>
              <TableCell><span className="font-mono text-xs text-muted-foreground">{r.code}</span> {r.name}</TableCell>
              <TableCell className="text-right"><Amount value={r.budget} /></TableCell><TableCell className="text-right"><Amount value={r.actual} /></TableCell>
              <TableCell className={`text-right ${r.favourable ? "text-emerald-600" : "text-red-600"}`}>{Number(r.variance).toLocaleString("en-NG", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</TableCell>
              <TableCell className="text-right text-xs">{r.variance_pct != null ? `${r.variance_pct}%` : "—"}</TableCell>
            </TableRow>
          ))}</TableBody>
        </Table>
      )}
    </Section>
  );
}

const JOURNAL_KINDS = [
  ["sales", "Sales journal"], ["cash-receipts", "Cash receipts journal"], ["purchases", "Purchases journal"],
  ["cash-disbursements", "Cash disbursements journal"], ["cogs", "Cost of goods sold journal"],
  ["inventory-adjustments", "Inventory adjustments journal"], ["general", "General journal"], ["assets", "Fixed assets journal"],
];

/** The Sage journals in Sage's own column layout (each journal has its own columns), any period. */
function JournalReports() {
  const [sp] = useSearchParams();
  const [kind, setKind] = useState(sp.get("kind") ?? "sales");
  const [range, setRange] = useState({ from: monthStart(), to: today() });
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [journal, setJournal] = useState<string | null>(null);
  const { data, isLoading, error } = useBooks<any>(["jr2", kind, range, q], `/ledger/journal/${kind}`, { ...range, search: q || undefined });
  const cols: Dict[] = data?.columns ?? [];
  const shown: Dict[] = (data?.rows ?? []).slice(0, 3000);
  const target = (r: Dict) => (r.source === "sage" ? sageLineTarget({ date: r.date, jrnl: r.jrnl, reference: r.reference }) : sourceTarget(r.source_type, r.source_id));
  const cell = (c: Dict, r: Dict) => {
    const v = r[c.key];
    if (c.key === "reference") { const t = target(r); return t ? <DrillLink to={t}>{v ?? r.journal_number}</DrillLink> : v; }
    if (c.type === "money") return <Amount value={v} blankZero />;
    if (c.type === "date") return fmtDate(v);
    if (c.type === "qty") return v != null ? Number(v).toLocaleString() : "";
    return v ?? "";
  };
  return (
    <Section title={data?.title ?? JOURNAL_KINDS.find((k) => k[0] === kind)?.[1]}
             actions={<CsvButton filename={`${kind}-journal-${range.from}-${range.to}.csv`} rows={data?.rows.map((r: Dict) => Object.fromEntries(cols.map((c) => [c.label, r[c.key] ?? ""])))} />}>
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <select className="h-9 rounded-md border bg-background px-2 text-sm" value={kind} onChange={(e) => setKind(e.target.value)}>
          {JOURNAL_KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <DateRange from={range.from} to={range.to} onChange={(f, t) => setRange({ from: f ?? range.from, to: t })} />
        <Input className="h-9 w-64" placeholder="Search reference / description (Enter)" value={search}
               onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === "Enter" && setQ(search.trim())} />
      </div>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (data.rows.length === 0 ? <Empty>No entries in this period.</Empty> : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader><TableRow>{cols.map((c) => <TableHead key={c.key} className={c.type === "money" || c.type === "qty" ? "text-right" : ""}>{c.label}</TableHead>)}</TableRow></TableHeader>
            <TableBody>
              {shown.map((r: Dict, i: number) => (
                <TableRow key={i} className={r.journal_id ? "cursor-pointer hover:bg-muted/50" : ""} onClick={() => r.journal_id && setJournal(r.journal_id)}>
                  {cols.map((c) => <TableCell key={c.key} className={`${c.type === "money" || c.type === "qty" ? "text-right" : ""} ${c.type === "date" ? "whitespace-nowrap" : ""} text-xs`}>{cell(c, r)}</TableCell>)}
                </TableRow>
              ))}
              <TableRow className="font-semibold">{cols.map((c, i) => <TableCell key={c.key} className="text-right">
                {i === 0 ? <span className="float-left">Total</span> : c.key === "debit" ? <Amount value={data.total_debit} /> : c.key === "credit" ? <Amount value={data.total_credit} /> : ""}</TableCell>)}</TableRow>
            </TableBody>
          </Table>
          {data.rows.length > shown.length && <p className="mt-2 text-xs text-muted-foreground">Showing the first {shown.length.toLocaleString()} of {data.rows.length.toLocaleString()} lines - the CSV has all of them; narrow the dates or search to see the rest here.</p>}
        </div>
      ))}
      <JournalSheet id={journal} onClose={() => setJournal(null)} />
    </Section>
  );
}

function shiftYear(d: string) {
  const [y, m, day] = d.split("-").map(Number);
  const last = new Date(y - 1, m, 0).getDate();
  return `${y - 1}-${String(m).padStart(2, "0")}-${String(Math.min(day, last)).padStart(2, "0")}`;
}
