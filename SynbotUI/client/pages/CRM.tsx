/**
 * CRM › Overview. Customers, sales and what they owe come from ACE Books (dated sales history,
 * open receivables); deals, leads and reminders from the sales pipeline (backend
 * services/crm_hub.overview). No figure here is estimated: the old page drew "prior" and
 * "forecast" chart points as fixed percentages of the pipeline when data was missing.
 */
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlarmClock, ArrowRight, Kanban, Loader2, Target, TrendingUp, Users, Wallet } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { PageHeader } from "@/components/workspace/PageHeader";
import { DrillLink } from "@/components/books/kit";
import { DrillProvider } from "@/components/books/lineage";
import { api } from "@/lib/api-client";
import { Dict, fmtDate, naira, num } from "@/lib/books-api";
import { STAGE_LABEL, STAGE_TONE } from "@/components/crm/crm-kit";

const compact = (v: number) => (Math.abs(v) >= 1e9 ? `₦${(v / 1e9).toFixed(1)}bn` : Math.abs(v) >= 1e6 ? `₦${(v / 1e6).toFixed(0)}M` : naira(v));
const pct = (a: number, b: number) => (b ? Math.round(((a - b) / b) * 100) : null);

export default function CRM() {
  return <DrillProvider><Overview /></DrillProvider>;
}

function Overview() {
  const navigate = useNavigate();
  const { data: d, isLoading, error } = useQuery({ queryKey: ["crm-hub", "overview"], queryFn: () => api.crmHub.overview(), refetchInterval: 120000 });
  if (isLoading) return <div className="flex justify-center py-16"><Loader2 className="h-6 w-6 animate-spin" /></div>;
  if (error || !d) return <p className="p-6 text-sm text-destructive">Could not load the CRM overview: {(error as Error)?.message}</p>;
  const c = d.customers, s = d.sales, change = pct(s.last30, s.prev30);

  return (
    <div className="space-y-5">
      <PageHeader icon={Users} title="CRM" subtitle={`Customers and sales from ACE Books (to ${fmtDate(d.as_of)}) · deals from the sales pipeline`}
        actions={<div className="flex gap-2">
          <Button variant="outline" onClick={() => navigate("/crm/lead-finder")}><Target className="mr-1.5 h-4 w-4" />Find leads</Button>
          <Button onClick={() => navigate("/crm/sales")}><Kanban className="mr-1.5 h-4 w-4" />Pipeline</Button></div>} />
      <KpiStrip items={[
        { label: "Active customers", value: num(c.active_90), icon: Users, sub: `bought in the last 90 days · ${num(c.active_365)} in 12 months · ${num(c.on_file)} on file`, onClick: () => navigate("/customers/workspace") },
        { label: "Sales, last 30 days", value: compact(s.last30), icon: TrendingUp, tone: change != null && change < 0 ? "warning" : "success",
          sub: change == null ? "ACE Books" : `${change >= 0 ? "+" : ""}${change}% on the 30 days before` },
        { label: "Owed by customers", value: compact(d.receivables.owed), icon: Wallet, tone: d.receivables.overdue > 0 ? "warning" : "default",
          sub: `${compact(d.receivables.overdue)} past due · ${num(d.receivables.overdue_customers)} customers`, onClick: () => navigate("/finance/ar") },
        { label: "Gross margin, 12 months", value: s.margin_pct != null ? `${s.margin_pct}%` : "—", sub: `on ${compact(s.last365)} sales` },
      ]} />
      <KpiStrip items={[
        { label: "Open deals", value: d.open_deals, icon: Kanban, sub: `${compact(d.open_pipeline_value)} expected`, onClick: () => navigate("/crm/sales") },
        { label: "Won, last 90 days", value: d.pipeline.won.count, tone: "success", sub: `${compact(d.pipeline.won.value)}${d.win_rate_90d != null ? ` · win rate ${d.win_rate_90d}%` : ""}` },
        { label: "New leads this week", value: d.new_leads_7d, icon: Target, onClick: () => navigate("/crm/lead-finder") },
        { label: "Follow-ups due", value: d.reminders.overdue + d.reminders.today, icon: AlarmClock, tone: d.reminders.overdue ? "danger" : "default",
          sub: `${d.reminders.overdue} overdue · ${d.reminders.today} today`, onClick: () => navigate("/crm/sales?tab=reminders") },
      ]} />
      <p className="text-xs text-muted-foreground">New customers in the last 90 days: {c.new_90} · Lapsed (bought in the last year, not in 90 days): {c.lapsed}</p>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="pb-2"><CardTitle className="text-base">Sales and buying customers by month</CardTitle>
            <CardDescription>ACE Books sales (Sage history to go-live, ACE Books after).</CardDescription></CardHeader>
          <CardContent className="pl-1">
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={d.monthly}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="period" fontSize={11} tickLine={false} axisLine={false} />
                <YAxis yAxisId="v" fontSize={11} tickLine={false} axisLine={false} tickFormatter={compact} width={60} />
                <YAxis yAxisId="c" orientation="right" fontSize={11} tickLine={false} axisLine={false} width={40} />
                <Tooltip formatter={(v: number, n: string) => (n === "Customers" ? num(v) : naira(v))} />
                <Legend />
                <Bar yAxisId="v" dataKey="sales" name="Sales" fill="hsl(var(--primary))" radius={[3, 3, 0, 0]} />
                <Line yAxisId="c" dataKey="customers" name="Customers" stroke="hsl(var(--success))" strokeWidth={2} dot={{ r: 2 }} />
              </ComposedChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2"><CardTitle className="text-base">Pipeline</CardTitle>
            <Button size="sm" variant="ghost" onClick={() => navigate("/crm/sales")}>Open <ArrowRight className="ml-1 h-4 w-4" /></Button></CardHeader>
          <CardContent className="space-y-2">
            {(["new", "qualified", "proposal", "won", "lost"] as const).map((k) => (
              <div key={k} className="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
                <span className={`rounded px-1.5 py-0.5 text-[11px] ${STAGE_TONE[k]}`}>{STAGE_LABEL[k]}{["won", "lost"].includes(k) ? " (90d)" : ""}</span>
                <span className="text-right"><span className="font-semibold">{d.pipeline[k].count}</span><span className="ml-2 text-xs text-muted-foreground">{compact(d.pipeline[k].value)}</span></span>
              </div>))}
            {d.open_deals === 0 && <p className="text-xs text-muted-foreground">No open deals yet - add leads from the lead finder or the pipeline.</p>}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <List title="Due to reorder" desc="Past their usual reorder date, from their invoice history" empty="No customers are due - order history resumes after the July–September import."
          rows={d.reorder_due.map((r: Dict) => ({ id: r.customer_pk, name: r.customer_name,
            sub: `every ~${Math.round(r.avg_gap_days ?? 0)} days · last ${fmtDate(r.last_order_date)}`,
            right: r.days_until_or_since > 0 ? `${r.days_until_or_since} days late${r.queue_status === "lapsing" ? " · lapsing" : ""}` : r.days_until_or_since === 0 ? "due today" : `due in ${-r.days_until_or_since} days`, bad: r.days_until_or_since > 0 }))} />
        <List title="Owing most (past due)" desc="ACE Books receivables" empty="No customer owes past-due money."
          rows={d.overdue_customers.map((r: Dict) => ({ id: r.id, name: r.name, sub: `owes ${naira(r.balance)} in total`, right: naira(r.overdue), bad: true }))} />
        <List title="Top customers, last 90 days" desc="By sales in ACE Books" empty="No sales in the last 90 days."
          rows={d.top_customers.map((r: Dict) => ({ id: r.id, name: r.name, sub: `${r.invoices} invoices · last ${fmtDate(r.last_date)}`, right: naira(r.sales) }))} />
        <List title="Recently won deals" desc="From the pipeline" empty="No deals won in the last 90 days."
          rows={d.recently_won.map((r: Dict) => ({ id: r.customer_id, name: r.company_name, sub: `won ${fmtDate(r.won_at)}`, right: naira(r.expected_value) }))} />
      </div>
    </div>
  );
}

function List({ title, desc, rows, empty }: { title: string; desc: string; empty: string; rows: { id?: number; name: string; sub: string; right: string; bad?: boolean }[] }) {
  return (
    <Card>
      <CardHeader className="pb-2"><CardTitle className="text-base">{title}</CardTitle><CardDescription>{desc}</CardDescription></CardHeader>
      <CardContent className="space-y-1.5">
        {rows.length === 0 && <p className="text-sm text-muted-foreground">{empty}</p>}
        {rows.map((r, i) => (
          <div key={i} className="flex items-center justify-between gap-3 border-b pb-1.5 text-sm last:border-0">
            <div className="min-w-0">
              <DrillLink to={r.id ? { type: "customer", id: String(r.id), label: r.name } : null}><span className="truncate font-medium">{r.name}</span></DrillLink>
              <div className="truncate text-[11px] text-muted-foreground">{r.sub}</div>
            </div>
            <span className={`shrink-0 text-sm ${r.bad ? "text-red-600 dark:text-red-400" : ""}`}>{r.right}</span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
