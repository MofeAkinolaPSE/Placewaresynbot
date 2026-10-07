import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AlertTriangle, CheckCircle2, RefreshCw } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table";
import { BooksShell } from "@/components/books/BooksShell";
import { Amount, DateRange, ErrorNote, Loading, Section, Stat, useBooks } from "@/components/books/kit";
import { naira, today } from "@/lib/books-api";

/** Finance Control Tower: position, performance, and what needs attention. */
export default function BooksOverview() {
  const [asOf, setAsOf] = useState(today());
  const navigate = useNavigate();
  const { data: d, isLoading, error, refetch, isFetching } = useBooks<any>(["dashboard", asOf], "/dashboard", { as_of: asOf });
  const k = d?.kpis;
  const quick = [
    ["New invoice", "/finance/books/sales?new=invoice"], ["Record receipt", "/finance/books/sales?new=receipt"],
    ["Supplier bill", "/finance/books/purchases?new=bill"], ["Pay supplier", "/finance/books/purchases?new=payment"],
    ["Spend / receive money", "/finance/books/banking?new=voucher"], ["Journal entry", "/finance/books/ledger?new=journal"],
    ["Stock adjustment", "/finance/books/stock?new=adjustment"], ["Financial statements", "/finance/books/statements"],
  ];
  return (
    <BooksShell title="Finance Control Tower"
                actions={<Button size="sm" variant="outline" onClick={() => refetch()}><RefreshCw className={`mr-1.5 h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />Refresh</Button>}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <DateRange single to={asOf} onChange={(_, t) => setAsOf(t)} />
        <div className="flex flex-wrap gap-2">
          {quick.map(([label, to]) => <Button key={to} asChild size="sm" variant="secondary"><Link to={to}>{label}</Link></Button>)}
        </div>
      </div>
      {isLoading && <Loading />}
      <ErrorNote error={error} />
      {d && k && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
            {([
              ["/finance/books/banking", <Stat label="Cash & bank" value={naira(k.cash)} />],
              ["/finance/books/sales?tab=aging", <Stat label="Receivables" value={naira(k.receivables)} sub={`${naira(k.overdue_receivables)} overdue`} tone={Number(k.overdue_receivables) > 0 ? "warn" : undefined} />],
              ["/finance/books/purchases?tab=aging", <Stat label="Payables" value={naira(k.payables)} sub={`${naira(k.overdue_payables)} overdue`} />],
              ["/finance/books/stock?tab=valuation", <Stat label="Stock value" value={naira(k.inventory_value)} />],
              [`/finance/books/reports?r=sales-analysis&from=${asOf.slice(0, 4)}-01-01&to=${asOf}`, <Stat label="Revenue (year to date)" value={naira(k.revenue_ytd)} sub={`this month ${naira(k.revenue_mtd)}`} />],
              ["/finance/books/statements?tab=pl", <Stat label="Net profit (year to date)" value={naira(k.net_profit_ytd)} sub={k.gross_margin_ytd_pct ? `gross margin ${k.gross_margin_ytd_pct}%` : undefined}
                    tone={Number(k.net_profit_ytd) >= 0 ? "good" : "bad"} />],
            ] as [string, JSX.Element][]).map(([to, el]) => (
              <div key={to} role="link" tabIndex={0} onClick={() => navigate(to)} onKeyDown={(e) => e.key === "Enter" && navigate(to)}
                   className="cursor-pointer rounded-xl transition hover:ring-2 hover:ring-primary/40" title="Open the detail behind this figure">{el}</div>
            ))}
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Section className="lg:col-span-2" title="Financial health — internal accounting review"
                     actions={<Button asChild size="sm" variant="outline"><Link to="/finance/books/close">Open controls</Link></Button>}>
              <ul className="space-y-2">
                {d.health.map((h: any) => (
                  <li key={h.code} className="flex items-start gap-2 text-sm">
                    {h.status === "PASS"
                      ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                      : <AlertTriangle className={`mt-0.5 h-4 w-4 shrink-0 ${h.blocking ? "text-red-600" : "text-amber-500"}`} />}
                    <div><span className="font-medium">{h.title}.</span> <span className="text-muted-foreground">{h.message}</span></div>
                  </li>
                ))}
              </ul>
            </Section>
            <Section title="Needs attention">
              <Table>
                <TableBody>
                  {[
                    ["Journals awaiting approval", d.pending.journals_awaiting_approval, "/finance/books/ledger"],
                    ["Draft journals", d.pending.draft_journals, "/finance/books/ledger"],
                    ["Stock adjustments to approve", d.pending.draft_adjustments, "/finance/books/stock"],
                    ["Draft invoices", d.pending.draft_invoices, "/finance/books/sales"],
                    ["Frontdesk sales not posted", d.pending.failed_frontdesk_postings, "/finance/books/close"],
                    ["Open recalls", d.pending.open_recalls, "/finance/books/stock"],
                    ["Stock out on loan", d.pending.open_stock_loans, "/finance/books/stock"],
                  ].map(([label, n, to]) => (
                    <TableRow key={label as string}>
                      <TableCell className="py-1.5"><Link className="hover:underline" to={to as string}>{label}</Link></TableCell>
                      <TableCell className={`py-1.5 text-right font-semibold ${Number(n) > 0 ? "text-amber-600" : "text-muted-foreground"}`}>{n}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Section>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Section className="lg:col-span-2" title="Revenue & profit by month">
              {d.trend.length === 0 ? <p className="text-sm text-muted-foreground">Monthly figures appear as transactions are posted in ACE Books (the migrated Sage half-year is one opening balance).</p> : (
                <div className="h-64">
                  <ResponsiveContainer>
                    <BarChart data={d.trend.map((t: any) => ({ ...t, revenue: Number(t.revenue), net_profit: Number(t.net_profit) }))}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="month" fontSize={12} />
                      <YAxis fontSize={12} tickFormatter={(v) => `₦${(v / 1e6).toFixed(0)}m`} />
                      <Tooltip formatter={(v: any) => naira(v)} />
                      <Bar dataKey="revenue" name="Revenue" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
                      <Bar dataKey="net_profit" name="Net profit" fill="hsl(var(--chart-2, 160 60% 45%))" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Section>
            <Section title="Cash & bank">
              <Table>
                <TableBody>
                  {d.cash_accounts.filter((c: any) => Number(c.balance) !== 0).map((c: any) => (
                    <TableRow key={c.id}><TableCell className="py-1.5">{c.name}</TableCell><TableCell className="py-1.5 text-right"><Amount value={c.balance} /></TableCell></TableRow>
                  ))}
                </TableBody>
              </Table>
            </Section>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <Section title="Receivables ageing (by due date)" actions={<Button asChild size="sm" variant="outline"><Link to="/finance/books/sales?tab=aging">Details</Link></Button>}>
              <AgeBars buckets={d.ar_aging.buckets} totals={d.ar_aging.totals} />
            </Section>
            <Section title="Payables ageing (by due date)" actions={<Button asChild size="sm" variant="outline"><Link to="/finance/books/purchases?tab=aging">Details</Link></Button>}>
              <AgeBars buckets={d.ap_aging.buckets} totals={d.ap_aging.totals} />
            </Section>
          </div>
        </>
      )}
    </BooksShell>
  );
}

function AgeBars({ buckets, totals }: { buckets: string[]; totals: string[] }) {
  const max = Math.max(...totals.map((t) => Math.abs(Number(t))), 1);
  return (
    <div className="space-y-2">
      {buckets.map((b, i) => (
        <div key={b} className="grid grid-cols-[90px_1fr_140px] items-center gap-2 text-sm">
          <span className="text-muted-foreground">{b} days</span>
          <div className="h-2.5 rounded-full bg-muted"><div className={`h-2.5 rounded-full ${i >= 3 ? "bg-red-500" : i >= 1 ? "bg-amber-500" : "bg-emerald-500"}`} style={{ width: `${(Math.abs(Number(totals[i])) / max) * 100}%` }} /></div>
          <span className="text-right"><Amount value={totals[i]} /></span>
        </div>
      ))}
    </div>
  );
}
