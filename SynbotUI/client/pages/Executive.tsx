/**
 * Executive overview - the CEO / CFO control centre. One page, read live from the modules that own
 * each figure: ACE Books (P&L, cash, receivables, payables, controls), sales, customers and pipeline,
 * stock and orders, quality and compliance, people. Every block opens the page where it is dealt with.
 */
import { ReactNode, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  AlertOctagon, AlertTriangle, ArrowDownRight, ArrowUpRight, Banknote, BookOpen, Boxes, Briefcase, Building2, ChevronRight,
  ClipboardCheck, Info, Landmark, Loader2, PackageX, RefreshCw, ShieldCheck, TrendingUp, Users, Wallet,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api-client";
import { fmtDate } from "@/lib/books-api";

type Dict = Record<string, any>;

const M = (v: any, dp = 1) => {
  const n = Number(v ?? 0);
  if (!Number.isFinite(n)) return "—";
  const a = Math.abs(n);
  if (a >= 1e9) return `₦${(n / 1e9).toFixed(2)}bn`;
  if (a >= 1e6) return `₦${(n / 1e6).toFixed(dp)}M`;
  if (a >= 1e3) return `₦${(n / 1e3).toFixed(0)}k`;
  return `₦${n.toFixed(0)}`;
};
const pct = (v: any) => (v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`);
const monthName = (p: string) => new Date(p + "-15").toLocaleDateString("en-GB", { month: "short", year: "2-digit" });

function Delta({ v, suffix = "" }: { v: number | null | undefined; suffix?: string }) {
  if (v === null || v === undefined) return null;
  const up = v >= 0;
  return (
    <span className={`inline-flex items-center text-xs font-medium ${up ? "text-emerald-600" : "text-red-600"}`}>
      {up ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}{Math.abs(v).toFixed(1)}%{suffix}
    </span>
  );
}

function Tile({ label, value, sub, to, tone, icon: Icon }: { label: string; value: ReactNode; sub?: ReactNode; to?: string; tone?: "danger" | "warning" | "good"; icon?: any }) {
  const nav = useNavigate();
  return (
    <button onClick={() => to && nav(to)} disabled={!to}
      className={`group flex flex-col rounded-xl border bg-card p-4 text-left transition-colors ${to ? "hover:border-primary/50" : "cursor-default"}`}>
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>{label}</span>{Icon && <Icon className="h-4 w-4" />}
      </div>
      <div className={`mt-1 text-2xl font-bold tabular-nums ${tone === "danger" ? "text-red-600" : tone === "warning" ? "text-amber-600" : tone === "good" ? "text-emerald-600" : ""}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-muted-foreground">{sub}</div>}
    </button>
  );
}

function Panel({ title, to, linkLabel, icon: Icon, children, className = "" }: { title: string; to?: string; linkLabel?: string; icon?: any; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border bg-card p-4 ${className}`}>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="flex items-center gap-2 text-sm font-semibold">{Icon && <Icon className="h-4 w-4 text-primary" />}{title}</h3>
        {to && <Link to={to} className="flex items-center text-xs text-primary hover:underline">{linkLabel ?? "Open"}<ChevronRight className="h-3 w-3" /></Link>}
      </div>
      {children}
    </section>
  );
}

function Row({ label, value, tone, to }: { label: ReactNode; value: ReactNode; tone?: string; to?: string }) {
  const inner = (
    <div className={`flex items-center justify-between gap-3 py-1.5 text-sm ${to ? "hover:text-primary" : ""}`}>
      <span className="text-muted-foreground">{label}</span><span className={`font-medium tabular-nums ${tone ?? ""}`}>{value}</span>
    </div>
  );
  return to ? <Link to={to}>{inner}</Link> : inner;
}

function Bar100({ parts }: { parts: { label: string; value: number; cls: string }[] }) {
  const total = parts.reduce((s, p) => s + Math.max(0, p.value), 0) || 1;
  return (
    <div>
      <div className="flex h-2.5 overflow-hidden rounded-full bg-muted">
        {parts.map((p) => <div key={p.label} className={p.cls} style={{ width: `${(Math.max(0, p.value) / total) * 100}%` }} title={`${p.label}: ${M(p.value)}`} />)}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
        {parts.map((p) => <span key={p.label} className="inline-flex items-center gap-1"><span className={`h-2 w-2 rounded-full ${p.cls}`} />{p.label} {M(p.value)}</span>)}
      </div>
    </div>
  );
}

const LEVEL: Record<string, { icon: any; cls: string }> = {
  critical: { icon: AlertOctagon, cls: "text-red-600" },
  action: { icon: AlertTriangle, cls: "text-amber-600" },
  info: { icon: Info, cls: "text-sky-600" },
};

export default function Executive() {
  const [refreshing, setRefreshing] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const q = useQuery({ queryKey: ["executive-overview"], queryFn: () => api.dashboard.executive(), refetchInterval: 300_000 });
  const d = q.data;
  const refresh = async () => { setRefreshing(true); try { await api.dashboard.executive(true); await q.refetch(); } finally { setRefreshing(false); } };

  if (q.isLoading) return <div className="flex justify-center py-20"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>;
  if (!d) return <p className="p-6 text-sm text-destructive">The executive overview could not be loaded{(q.error as any)?.message ? `: ${(q.error as any).message}` : ""}.</p>;

  const f = d.finance ?? {}, s = d.sales ?? {}, c = d.customers ?? {}, st = d.stock ?? {}, ql = d.quality ?? {}, p = d.people ?? {};
  const ar = f.receivables ?? {}, ap = f.payables ?? {}, bk = f.books ?? {}, ctl = f.controls ?? {};
  const agedOn = f.aged_on ? fmtDate(f.aged_on) : "";
  const trend = (s.trend ?? []).map((t: Dict) => ({ ...t, label: monthName(t.period) }));
  const critical = (d.attention ?? []).filter((a: Dict) => a.level === "critical").length;

  return (
    <div className="flex flex-col gap-5">
      {/* header */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Executive overview</h1>
          <p className="text-sm text-muted-foreground">
            Placeware Nigeria Limited · the whole business on one page, live from ACE Books and every department ·
            updated {new Date(d.generated_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}
          </p>
        </div>
        <Link to="/reports/new?type=executive&kind=current&id=now"><Button size="sm" variant="outline">Executive report</Button></Link>
        <Button size="sm" variant="outline" onClick={refresh} disabled={refreshing}><RefreshCw className={`mr-1.5 h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />Refresh</Button>
      </div>

      {bk.stale && (
        <div className="flex gap-3 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm dark:border-amber-500/40 dark:bg-amber-500/10">
          <BookOpen className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
          <div>
            <div className="font-semibold">The books are complete to {agedOn}; {bk.missing_months} month{bk.missing_months === 1 ? "" : "s"} still to load</div>
            <div className="text-muted-foreground">
              Last sale in the books: {fmtDate(s.as_of)}. Trading since the cut-over on {fmtDate(bk.cutover)} arrives with the Sage import - until then sales,
              cash, receivables and payables below are as at {agedOn}, and comparisons are to the same point last year.{" "}
              <Link to="/finance/sage-import" className="text-primary hover:underline">Sage import</Link>
            </div>
          </div>
        </div>
      )}

      {/* 1. headline */}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Tile label={`Revenue this year (to ${fmtDate(s.as_of)})`} icon={TrendingUp} to="/finance/books/statements"
          value={M(f.revenue_ytd)} sub={<><Delta v={s.ytd_growth_pct} /> vs same point last year ({M(s.ly_ytd)})</>} />
        <Tile label="Gross profit this year" icon={Briefcase} to="/finance/books/statements"
          value={M(f.gross_profit_ytd)} sub={`${pct(f.gross_margin_pct)} gross margin · 12-month sales margin ${pct(s.margin_365_pct)}`} />
        <Tile label="Net profit this year" icon={Landmark} to="/finance/books/statements" tone={f.net_profit_ytd < 0 ? "danger" : "good"}
          value={M(f.net_profit_ytd)} sub={`${pct(f.net_margin_pct)} of revenue · operating ${M(f.operating_profit_ytd)}`} />
        <Tile label="Cash & bank" icon={Wallet} to="/finance/books/banking"
          value={M(f.cash)} sub={`${(f.banks ?? []).length} accounts · covers ${ap.total ? `${Math.round((f.cash / ap.total) * 100)}% of what we owe suppliers` : "—"}`} />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Tile label={`Customers owe us (at ${agedOn})`} icon={Banknote} to="/finance/ar" tone={ar.over_90_pct >= 30 ? "warning" : undefined}
          value={M(ar.total)} sub={`${pct(ar.over_90_pct)} over 90 days (${M(ar.over_90)})`} />
        <Tile label={`We owe suppliers (at ${agedOn})`} icon={Building2} to="/finance/books/purchases" tone={ap.overdue > 0 ? "warning" : undefined}
          value={M(ap.total)} sub={ap.overdue ? `${M(ap.overdue)} past due` : "nothing past due"} />
        <Tile label="Stock (cost)" icon={Boxes} to="/inventory"
          value={M(st.value)} sub={`${st.cover_days ?? "—"} days of cover · ${st.skus_in_stock ?? 0} lines in stock`} />
        <Tile label="Working capital" icon={Briefcase} to="/finance/books/statements"
          value={M(d.working_capital)} sub="cash + receivables + stock − payables" />
      </div>

      {/* 2. attention + sales */}
      <div className="grid gap-4 xl:grid-cols-5">
        <Panel title={`Needs your attention${critical ? ` · ${critical} critical` : ""}`} icon={AlertTriangle} className="xl:col-span-2">
          {(d.attention ?? []).length === 0 ? <p className="text-sm text-muted-foreground">Nothing needs escalating.</p> : (
            <ul className="space-y-1">
              {(showAll ? d.attention : d.attention.slice(0, 6)).map((a: Dict, i: number) => {
                const L = LEVEL[a.level] ?? LEVEL.info;
                return (
                  <li key={i}>
                    <Link to={a.link} className="flex gap-2.5 rounded-lg px-2 py-2 hover:bg-muted/50">
                      <L.icon className={`mt-0.5 h-4 w-4 shrink-0 ${L.cls}`} />
                      <span className="min-w-0">
                        <span className="block text-sm font-medium">{a.title}</span>
                        {a.detail && <span className="block text-xs text-muted-foreground">{a.detail}</span>}
                      </span>
                    </Link>
                  </li>
                );
              })}
              {d.attention.length > 6 && (
                <li><button onClick={() => setShowAll((v) => !v)} className="px-2 py-1 text-xs text-primary hover:underline">
                  {showAll ? "Show fewer" : `Show all ${d.attention.length}`}
                </button></li>
              )}
            </ul>
          )}
        </Panel>
        <Panel title="Sales by month - with margin and last year" icon={TrendingUp} to="/finance/books/sales" linkLabel="Sales & receivables" className="xl:col-span-3">
          <div className="mb-2 grid grid-cols-3 gap-2 text-center">
            <div className="rounded-lg bg-muted/40 p-2"><div className="text-[11px] text-muted-foreground">{monthName(s.month?.period ?? "2026-01")} (to {fmtDate(s.as_of)})</div>
              <div className="font-semibold">{M(s.month?.sales)}</div>
              <div className="text-[11px]">{s.month?.last_year ? <Delta v={((s.month.sales - s.month.last_year) / s.month.last_year) * 100} suffix=" vs LY" /> : null}</div></div>
            <div className="rounded-lg bg-muted/40 p-2"><div className="text-[11px] text-muted-foreground">Last 90 days</div>
              <div className="font-semibold">{M(s.last90)}</div><div className="text-[11px]"><Delta v={s.q_growth_pct} suffix=" vs prior 90" /></div></div>
            <div className="rounded-lg bg-muted/40 p-2"><div className="text-[11px] text-muted-foreground">Last 12 months</div>
              <div className="font-semibold">{M(s.last365)}</div><div className="text-[11px] text-muted-foreground">{s.buyers_365} buyers · avg invoice {M(s.avg_invoice)}</div></div>
          </div>
          <div className="h-60">
            <ResponsiveContainer>
              <ComposedChart data={trend} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} className="stroke-muted" />
                <XAxis dataKey="label" fontSize={10} tickLine={false} axisLine={false} />
                <YAxis yAxisId="l" fontSize={10} tickLine={false} axisLine={false} width={44} tickFormatter={(v) => `${Math.round(v / 1e6)}M`} />
                <YAxis yAxisId="r" orientation="right" fontSize={10} tickLine={false} axisLine={false} width={34} unit="%" domain={[0, "auto"]} />
                <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }}
                  formatter={(v: any, n: string) => (n === "Margin" ? [`${v}%`, n] : [M(v), n])} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar yAxisId="l" dataKey="last_year" name="Same month last year" fill="hsl(var(--muted-foreground) / 0.25)" radius={[3, 3, 0, 0]} />
                <Bar yAxisId="l" dataKey="sales" name="Sales" fill="hsl(var(--primary))" radius={[3, 3, 0, 0]} />
                <Line yAxisId="r" dataKey="margin_pct" name="Margin" stroke="#f59e0b" strokeWidth={2} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      </div>

      {/* 3. money detail */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Receivables ageing" icon={Banknote} to="/finance/ar" linkLabel="Credit control">
          <p className="mb-2 text-[11px] text-muted-foreground">As at {agedOn}, by due date</p>
          <Bar100 parts={[
            { label: "0–30", value: ar.buckets?.["0_30"] ?? 0, cls: "bg-emerald-500" },
            { label: "31–60", value: ar.buckets?.["31_60"] ?? 0, cls: "bg-lime-500" },
            { label: "61–90", value: ar.buckets?.["61_90"] ?? 0, cls: "bg-amber-500" },
            { label: "90+", value: ar.buckets?.["91_plus"] ?? 0, cls: "bg-red-500" },
          ]} />
          <div className="mt-3 border-t pt-2">
            <Row label="Customers over credit limit" value={`${f.credit_breaches?.customers ?? 0} · ${M(f.credit_breaches?.excess)} over`} tone="text-amber-600" to="/crm/customers" />
            <Row label="Supplier bills past due" value={M(ap.overdue)} tone={ap.overdue ? "text-amber-600" : ""} to="/finance/books/purchases" />
            <Row label="Supplier bills due next 30 days" value={M(ap.due_30)} to="/finance/books/purchases" />
          </div>
        </Panel>
        <Panel title="Cash by account" icon={Wallet} to="/finance/books/banking" linkLabel="Banking">
          <div className="divide-y">
            {(f.banks ?? []).map((b: Dict) => <Row key={b.code} label={`${b.name}`} value={M(b.balance, 2)} />)}
          </div>
          <div className="mt-2 flex justify-between border-t pt-2 text-sm font-semibold"><span>Total</span><span>{M(f.cash, 2)}</span></div>
        </Panel>
        <Panel title="Books & controls" icon={ClipboardCheck} to="/finance/books/close" linkLabel="Close & controls">
          <Row label="Last trading posted in ACE Books" value={bk.last_posting ? fmtDate(bk.last_posting) : "none since cut-over"} tone={bk.stale ? "text-amber-600" : ""} />
          <Row label="Months still to load" value={bk.missing_months || "none"} tone={bk.missing_months ? "text-amber-600" : ""} to="/finance/sage-import" />
          <Row label="Past months still open" value={ctl.past_periods_open ?? 0} />
          <Row label="Bank accounts reconciled" value={`${ctl.reconciled ?? 0} of ${(f.banks ?? []).length}`} tone={(ctl.reconciled ?? 0) < (f.banks ?? []).length ? "text-amber-600" : ""} to="/finance/books/banking" />
          <Row label="Last reconciliation" value={ctl.last_reconciled ? fmtDate(ctl.last_reconciled) : "never"} />
          <Row label="Drafts not yet posted" value={(ctl.draft_invoices ?? 0) + (ctl.draft_bills ?? 0) + (ctl.draft_journals ?? 0)} />
        </Panel>
      </div>

      {/* 4. where sales come from */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title={`Top customers, last 12 months · top 10 = ${pct(s.top10_share_pct)} of sales`} icon={Users} to="/crm/customers" linkLabel="Customers">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-[11px] text-muted-foreground"><th className="pb-1 font-medium">Customer</th><th className="pb-1 text-right font-medium">Sales</th><th className="pb-1 text-right font-medium">Share</th><th className="pb-1 text-right font-medium">Margin</th></tr></thead>
            <tbody className="divide-y">
              {(s.top_customers ?? []).map((x: Dict) => (
                <tr key={x.id}><td className="max-w-[220px] truncate py-1.5"><Link to={`/crm/customers?customer=${x.id}`} className="hover:text-primary">{x.name}</Link></td>
                  <td className="py-1.5 text-right tabular-nums">{M(x.sales)}</td><td className="py-1.5 text-right tabular-nums">{pct(x.share_pct)}</td>
                  <td className={`py-1.5 text-right tabular-nums ${x.margin_pct < 10 ? "text-amber-600" : ""}`}>{pct(x.margin_pct)}</td></tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <Panel title="Top products, last 12 months" icon={Boxes} to="/inventory" linkLabel="Stock">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-[11px] text-muted-foreground"><th className="pb-1 font-medium">Product</th><th className="pb-1 text-right font-medium">Sales</th><th className="pb-1 text-right font-medium">Units</th><th className="pb-1 text-right font-medium">Margin</th></tr></thead>
            <tbody className="divide-y">
              {(s.top_products ?? []).map((x: Dict) => (
                <tr key={x.product}><td className="max-w-[220px] truncate py-1.5">{x.product}</td><td className="py-1.5 text-right tabular-nums">{M(x.sales)}</td>
                  <td className="py-1.5 text-right tabular-nums">{Number(x.units).toLocaleString()}</td>
                  <td className={`py-1.5 text-right tabular-nums ${x.margin_pct < 10 ? "text-amber-600" : ""}`}>{pct(x.margin_pct)}</td></tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>

      {/* 5. departments */}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Panel title="Customers & pipeline" icon={Users} to="/crm" linkLabel="CRM">
          <Row label="Active (bought in 90 days)" value={c.counts?.active ?? "—"} to="/crm/customers" />
          <Row label="New (first order in 90 days)" value={c.counts?.new ?? "—"} />
          <Row label="Lapsing (3–12 months)" value={c.counts?.lapsing ?? "—"} tone="text-amber-600" />
          <Row label="Slipping regulars" value={`${c.at_risk ?? 0} · ${M(c.at_risk_sales)}`} tone={c.at_risk ? "text-amber-600" : ""} to="/crm/customers" />
          <Row label="Open pipeline" value={`${c.open_deals ?? 0} deals · ${M(c.pipeline_value)}`} to="/crm/sales" />
          <Row label="Win rate (90 days)" value={pct(c.win_rate_90d)} />
          {(c.at_risk_top ?? []).length > 0 && (
            <div className="mt-2 border-t pt-2 text-xs">
              <div className="mb-1 font-medium text-muted-foreground">Biggest slipping accounts</div>
              {c.at_risk_top.slice(0, 4).map((x: Dict) => (
                <div key={x.id} className="flex justify-between gap-2 py-0.5"><span className="truncate">{x.name}</span><span className="shrink-0 text-muted-foreground" title={x.why}>{M(x.sales_12m)}</span></div>
              ))}
            </div>
          )}
        </Panel>
        <Panel title="Stock & purchasing" icon={Boxes} to="/operations/purchase-orders" linkLabel="Stock orders">
          <Row label="Stock value (cost)" value={M(st.value)} to="/inventory" />
          <Row label="Days of cover (90-day sales)" value={st.cover_days ?? "—"} />
          <Row label="Out of stock" value={st.out_of_stock ?? 0} tone={st.out_of_stock ? "text-red-600" : ""} />
          <Row label="To reorder now" value={`${st.reorder_now ?? 0} · ${M(st.to_order_value)}`} tone={st.reorder_now ? "text-amber-600" : ""} />
          <Row label="Orders open with suppliers" value={`${st.open_orders ?? 0}${st.ordered_value ? ` · ${M(st.ordered_value)}` : ""}`} />
          <Row label="Deliveries overdue" value={st.overdue_orders ?? 0} tone={st.overdue_orders ? "text-red-600" : ""} />
          <Row label="Purchases, 12 months" value={M(st.purchases_12m)} />
        </Panel>
        <Panel title="Quality & compliance" icon={ShieldCheck} to="/quality" linkLabel="Inventory & Quality">
          <div className="mb-2 flex items-center gap-3">
            <div className={`text-3xl font-bold ${ql.compliance_score >= 85 ? "text-emerald-600" : ql.compliance_score >= 70 ? "text-amber-600" : "text-red-600"}`}>{ql.compliance_score ?? "—"}</div>
            <div className="text-xs text-muted-foreground">compliance score<br />from what is overdue today</div>
          </div>
          <Row label="Expired stock (unsellable)" value={`${M(ql.expired_value)} · ${ql.expired_products ?? 0} products`} tone={ql.expired_value ? "text-red-600" : ""} to="/quality-control?tab=expiry" />
          <Row label="Expiring within 90 days" value={M(ql.expiring_90_value)} tone={ql.expiring_90_value ? "text-amber-600" : ""} to="/quality-control?tab=expiry" />
          <Row label="Open recalls" value={ql.recalls?.open ?? 0} tone={ql.recalls?.open ? "text-red-600" : ""} to="/quality-control?tab=recalls" />
          <Row label="Open deviations" value={`${ql.deviations?.open ?? 0}${ql.deviations?.overdue ? ` (${ql.deviations.overdue} late)` : ""}`} to="/compliance?tab=deviations" />
          <Row label="Audits overdue / next 30 days" value={`${ql.audits?.overdue ?? 0} / ${ql.audits?.due_30 ?? 0}`} to="/compliance?tab=audits" />
          <Row label="Batches awaiting release" value={ql.batches?.pending ?? 0} to="/quality-control?tab=release" />
        </Panel>
        <Panel title="People & work" icon={Users} to="/hr" linkLabel="HR">
          <Row label="Team members" value={p.headcount ?? "—"} to="/hr?tab=directory" />
          <Row label="Online / on the clock now" value={`${p.online ?? 0} / ${p.on_clock ?? 0}`} />
          <Row label="Hours this week" value={`${Number(p.hours_week ?? 0).toFixed(1)}h · ${p.people_with_hours ?? 0} people`} to="/hr" />
          <Row label="Timesheets to approve" value={p.pending_timesheets ?? 0} to="/hr?tab=timesheets" />
          <Row label="Open tasks (overdue)" value={`${p.open_tasks ?? 0} (${p.overdue_tasks ?? 0})`} tone={p.overdue_tasks ? "text-amber-600" : ""} to="/workspace?tab=team" />
          <Row label="Tasks done, last 7 days" value={p.done_7d ?? 0} />
          <Row label="Requests open (late)" value={`${p.open_requests ?? 0} (${p.overdue_requests ?? 0})`} />
        </Panel>
      </div>

      <p className="text-[11px] text-muted-foreground">
        Every figure is read from the module that owns it - nothing on this page is typed in or estimated. Revenue and profit: ACE Books income statement for the financial year to date.
        Sales trend, customers and products: invoiced sales lines. Stock: ACE Books cost layers. Built in {d.build_seconds}s; refreshed every 5 minutes.
        {critical > 0 && <Badge variant="destructive" className="ml-2 h-4 px-1 text-[10px]">{critical} critical</Badge>}
      </p>
    </div>
  );
}
