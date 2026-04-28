import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import { AlertCircle, TrendingUp } from "lucide-react";

function toNumber(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function describeDashboardError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.kind === "permission") return "You do not have permission to view this financial dataset.";
    if (err.kind === "session") return "Your session has expired. Please sign in again.";
    if (err.kind === "transport") return "Network issue while loading finance data.";
    if (err.kind === "validation") return "Finance request rejected due to invalid input.";
    if (err.kind === "server") return "Finance service temporarily unavailable.";
    return err.message || fallback;
  }
  if (err instanceof Error) return err.message || fallback;
  return fallback;
}

export function FinancialDashboard() {
  const { data: financeData, isLoading: kpiLoading, error } = useQuery({
    queryKey: ["finance-kpis"],
    queryFn: api.dashboard.finance,
    refetchInterval: 30000,
  });
  const { data: trendData, error: trendError } = useQuery({
    queryKey: ["finance-trend"],
    queryFn: () => api.finance.trend(),
  });
  const { data: txData, error: txError } = useQuery({
    queryKey: ["finance-transactions"],
    queryFn: () => api.finance.transactions(),
  });

  const payload = (financeData as any)?.data || financeData;
  const financeValid =
    !!payload && payload.ar && payload.ap &&
    payload.ar.total_amount !== undefined &&
    payload.ar.total_balance !== undefined &&
    payload.ar.overdue_count !== undefined &&
    payload.ap.total_amount !== undefined &&
    payload.ap.total_balance !== undefined &&
    payload.ap.overdue_count !== undefined;

  const trendValid = !!trendData && Array.isArray((trendData as any).periods);
  const txValid = Array.isArray(txData);

  const ar = financeValid
    ? {
        total_amount: toNumber(payload.ar.total_amount),
        total_balance: toNumber(payload.ar.total_balance),
        overdue_count: toNumber(payload.ar.overdue_count),
      }
    : { total_amount: 0, total_balance: 0, overdue_count: 0 };

  const ap = financeValid
    ? {
        total_amount: toNumber(payload.ap.total_amount),
        total_balance: toNumber(payload.ap.total_balance),
        overdue_count: toNumber(payload.ap.overdue_count),
      }
    : { total_amount: 0, total_balance: 0, overdue_count: 0 };

  const cashflowData = trendValid
    ? ((trendData as any).periods as any[])
        .map((p: any) => ({
          month: p.period,
          inflow: Number(p.inflow ?? p.amount ?? 0) / 1_000_000,
          outflow: Number(p.outflow ?? 0) / 1_000_000,
          net: Number(p.net ?? (Number(p.inflow ?? p.amount ?? 0) - Number(p.outflow ?? 0))) / 1_000_000,
        }))
        .sort((a: any, b: any) => a.month.localeCompare(b.month))
    : [];

  const recentTx = txValid ? (txData as any[]) : [];

  // Determine health borders based on data
  const arHealthy = ar.overdue_count === 0;
  const apHealthy = ap.overdue_count === 0;

  return (
    <div className="flex flex-col gap-5">
      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-2.5 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {describeDashboardError(error, "Failed to load financial KPIs.")}
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card className={cn("border-l-4", arHealthy ? "border-l-success" : "border-l-primary")}>
          <CardHeader className="pb-1 pt-4">
            <CardDescription className="text-xs font-medium uppercase tracking-wide">Total AR (Revenue)</CardDescription>
          </CardHeader>
          <CardContent className="pb-4">
            <div className="text-3xl font-bold tabular-nums">
              {financeValid ? `₦${ar.total_amount.toLocaleString()}` : (kpiLoading ? "Loading..." : "—")}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {financeValid ? `Outstanding: ₦${ar.total_balance.toLocaleString()}` : "Waiting for KPI data"}
            </p>
          </CardContent>
        </Card>

        <Card className={cn("border-l-4", arHealthy ? "border-l-success" : "border-l-destructive")}>
          <CardHeader className="pb-1 pt-4">
            <CardDescription className="text-xs font-medium uppercase tracking-wide">Overdue Invoices</CardDescription>
          </CardHeader>
          <CardContent className="pb-4">
            <div className={cn("text-3xl font-bold tabular-nums", !arHealthy && "text-destructive")}>
              {financeValid ? ar.overdue_count : (kpiLoading ? "..." : "—")}
            </div>
            <div className={cn("mt-1 flex items-center gap-1 text-xs font-medium", arHealthy ? "text-success" : "text-destructive")}>
              {arHealthy ? "All invoices current" : "Needs immediate attention"}
            </div>
          </CardContent>
        </Card>

        <Card className="border-l-4 border-l-warning">
          <CardHeader className="pb-1 pt-4">
            <CardDescription className="text-xs font-medium uppercase tracking-wide">Total AP (Expenses)</CardDescription>
          </CardHeader>
          <CardContent className="pb-4">
            <div className="text-3xl font-bold tabular-nums">
              {financeValid ? `₦${ap.total_amount.toLocaleString()}` : (kpiLoading ? "Loading..." : "—")}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {financeValid ? `Outstanding: ₦${ap.total_balance.toLocaleString()}` : "Waiting for KPI data"}
            </p>
          </CardContent>
        </Card>

        <Card className={cn("border-l-4", apHealthy ? "border-l-success" : "border-l-destructive")}>
          <CardHeader className="pb-1 pt-4">
            <CardDescription className="text-xs font-medium uppercase tracking-wide">Overdue Bills</CardDescription>
          </CardHeader>
          <CardContent className="pb-4">
            <div className={cn("text-3xl font-bold tabular-nums", !apHealthy && "text-destructive")}>
              {financeValid ? ap.overdue_count : (kpiLoading ? "..." : "—")}
            </div>
            <div className={cn("mt-1 flex items-center gap-1 text-xs font-medium", apHealthy ? "text-success" : "text-destructive")}>
              {apHealthy ? "All bills current" : "Needs attention"}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Charts Row */}
      <div className="grid gap-4 lg:grid-cols-12">
        {/* Cash Flow Area Chart — col-span-8 */}
        <Card className="lg:col-span-8">
          <CardHeader className="pb-2">
            <CardTitle className="text-base font-semibold">Cash Flow Overview</CardTitle>
            <CardDescription className="text-xs">Monthly inflow vs outflow from latest GL snapshot</CardDescription>
          </CardHeader>
          <CardContent className="px-2 pb-4">
            <div className="h-[340px]">
              {trendValid && cashflowData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={cashflowData} margin={{ top: 8, right: 16, left: 8, bottom: 10 }}>
                    <defs>
                      <linearGradient id="inflowGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#14AAF5" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#14AAF5" stopOpacity={0.02} />
                      </linearGradient>
                      <linearGradient id="outflowGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#ef4444" stopOpacity={0.2} />
                        <stop offset="95%" stopColor="#ef4444" stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" opacity={0.5} />
                    <XAxis dataKey="month" fontSize={12} tickLine={false} axisLine={false} stroke="hsl(var(--muted-foreground))" />
                    <YAxis fontSize={12} tickLine={false} axisLine={false} tickFormatter={(v) => `₦${v}M`} width={56} stroke="hsl(var(--muted-foreground))" />
                    <Tooltip formatter={(v: number, name: string) => [`₦${v.toFixed(2)}M`, name]} contentStyle={{ fontSize: "13px", borderRadius: "8px" }} />
                    <Area type="monotone" dataKey="inflow" name="Inflow" stroke="#14AAF5" strokeWidth={2} fill="url(#inflowGrad)" />
                    <Area type="monotone" dataKey="outflow" name="Outflow" stroke="#ef4444" strokeWidth={2} fill="url(#outflowGrad)" />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-destructive">
                  {describeDashboardError(trendError, "Cashflow trend payload unavailable.")}
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Recent Transactions — col-span-4 */}
        <Card className="lg:col-span-4">
          <CardHeader className="pb-2">
            <CardTitle className="text-base font-semibold">Recent Transactions</CardTitle>
            <CardDescription className="text-xs">Latest financial movements</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <div className="max-h-[300px] overflow-y-auto">
              {!txValid ? (
                <p className="p-4 text-sm text-destructive">{describeDashboardError(txError, "Transactions unavailable.")}</p>
              ) : recentTx.length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">No recent transactions.</p>
              ) : (
                recentTx.map((tx: any, i: number) => (
                  <div key={i} className="flex items-center justify-between border-b border-border/40 px-4 py-3 last:border-0">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{tx.description}</p>
                      <p className="text-xs text-muted-foreground">{new Date(tx.date).toLocaleDateString()}</p>
                    </div>
                    <div className={cn("ml-3 shrink-0 text-sm font-bold tabular-nums", tx.type === "credit" ? "text-success" : "text-destructive")}>
                      {tx.type === "credit" ? "+" : "-"}₦{tx.amount.toLocaleString()}
                    </div>
                  </div>
                ))
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
