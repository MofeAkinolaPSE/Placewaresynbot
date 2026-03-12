import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { 
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar 
} from "recharts";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api-client";

function toNumber(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function describeDashboardError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.kind === "permission") return "You do not have permission to view this financial dataset.";
    if (err.kind === "session") return "Your session has expired. Please sign in again.";
    if (err.kind === "transport") return "Network issue while loading finance data. Check connection and retry.";
    if (err.kind === "validation") return "Finance request was rejected due to invalid input.";
    if (err.kind === "server") return "Finance service is temporarily unavailable.";
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
    queryFn: ()=> api.finance.trend(),
  });

  const { data: txData, error: txError } = useQuery({
    queryKey: ["finance-transactions"],
    queryFn: () => api.finance.transactions(),
  });

  // Handle nested "data" wrapper from API response if present
  const payload = (financeData as any)?.data || financeData;

  const financeValid =
    !!payload &&
    payload.ar &&
    payload.ap &&
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

  // Process Trend Data
    const cashflowData = trendValid ? ((trendData as any).periods as any[]).map((p: any) => ({
      month: p.period,
      inflow: Number(p.inflow ?? p.amount ?? 0) / 1000000,
      outflow: Number(p.outflow ?? 0) / 1000000,
      net: Number(p.net ?? (Number(p.inflow ?? p.amount ?? 0) - Number(p.outflow ?? 0))) / 1000000,
    })).sort((a: any, b: any) => a.month.localeCompare(b.month)) : [];

  const recentTx = txValid ? txData : [];

  return (
    <div className="space-y-6">
      {error && (
        <div className="text-sm text-destructive">
          Data error: {describeDashboardError(error, "Failed to load financial KPIs.")}
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total AR (Revenue)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {financeValid ? `₦${ar.total_amount?.toLocaleString()}` : (kpiLoading ? "Loading..." : "Data unavailable")}
            </div>
            <p className="text-xs text-muted-foreground">
              {financeValid ? `Outstanding: ₦${ar.total_balance?.toLocaleString()}` : "Waiting for KPI data"}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Overdue Invoices</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{financeValid ? ar.overdue_count : (kpiLoading ? "..." : "-")}</div>
            <p className="text-xs text-muted-foreground">{financeValid ? "Needs attention" : "Waiting for KPI data"}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total AP (Expenses)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {financeValid ? `₦${ap.total_amount?.toLocaleString()}` : (kpiLoading ? "Loading..." : "Data unavailable")}
            </div>
            <p className="text-xs text-muted-foreground">
              {financeValid ? `Outstanding: ₦${ap.total_balance?.toLocaleString()}` : "Waiting for KPI data"}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Overdue Bills</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{financeValid ? ap.overdue_count : (kpiLoading ? "..." : "-")}</div>
            <p className="text-xs text-muted-foreground">{financeValid ? "Needs attention" : "Waiting for KPI data"}</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-7">
        <Card className="col-span-4">
          <CardHeader>
            <CardTitle>Cash Flow Overview</CardTitle>
            <CardDescription>Monthly inflow vs outflow from latest GL snapshot</CardDescription>
          </CardHeader>
          <CardContent className="pl-2">
            {trendValid && cashflowData.length > 0 ? (
              <ResponsiveContainer width="100%" height={350}>
                <BarChart data={cashflowData}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="month" stroke="#888888" fontSize={12} tickLine={false} axisLine={false} />
                  <YAxis stroke="#888888" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(value) => `₦${value}M`} />
                  <Tooltip />
                  <Bar dataKey="inflow" name="Inflow" fill="#0ea5e9" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="outflow" name="Outflow" fill="#ef4444" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-destructive p-4">Data error: {describeDashboardError(trendError, "cashflow trend payload unavailable.")}</p>
            )}
            {trendError && <p className="text-xs text-destructive px-4">{describeDashboardError(trendError, "Failed to load trend data.")}</p>}
          </CardContent>
        </Card>
        
        <Card className="col-span-3">
          <CardHeader>
            <CardTitle>Recent Transactions</CardTitle>
            <CardDescription>Latest financial movements</CardDescription>
          </CardHeader>
          <CardContent>
             <div className="space-y-4">
                {!txValid ? <p className="text-sm text-destructive">Data error: transactions payload unavailable.</p> : recentTx.length === 0 ? <p className="text-sm text-muted">No recent transactions</p> : recentTx.map((tx: any, i: number) => (
                   <div key={i} className="flex items-center justify-between border-b pb-2 last:border-0 last:pb-0">
                      <div>
                         <p className="text-sm font-medium">{tx.description}</p>
                         <p className="text-xs text-muted-foreground">{new Date(tx.date).toLocaleDateString()}</p>
                      </div>
                       <div className={`font-bold text-sm ${tx.type === 'credit' ? 'text-success' : 'text-destructive'}`}>
                         {tx.type === 'credit' ? "+" : "-"} ₦{(tx.amount).toLocaleString()}
                      </div>
                   </div>
                ))}
                 {txError && <p className="text-xs text-destructive">{describeDashboardError(txError, "Failed to load transactions.")}</p>}
             </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
