import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { ResponsiveContainer, BarChart, Bar, CartesianGrid, XAxis, YAxis, Tooltip, Legend, LineChart, Line } from "recharts";

export function ProfitabilityDashboard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["finance-profitability"],
    queryFn: () => api.finance.profitability(),
    refetchInterval: 30000,
  });

  const series = Array.isArray(data?.series) ? data.series : [];
  const latest = series.length > 0 ? series[series.length - 1] : null;

  const formatNaira = (value: number) => `₦${value.toLocaleString()}`;
  const marginPercent = (latest?.profit && latest?.revenue)
    ? (latest.profit / latest.revenue) * 100
    : 0;

  return (
    <div className="space-y-6">
      {isLoading && <div className="text-sm text-muted-foreground">Loading profitability metrics...</div>}
      {error && <div className="text-sm text-destructive">Data error: {(error as Error).message || "Failed to load profitability metrics."}</div>}
      {!isLoading && !error && !latest && (
        <div className="text-sm text-destructive">Data error: profitability series payload unavailable.</div>
      )}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Net Profit (Latest Period)</CardTitle>
            <CardDescription>{latest ? latest.period : "No period"}</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{latest ? formatNaira(latest.profit) : (isLoading ? "Loading..." : "-")}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Revenue (Latest Period)</CardTitle>
            <CardDescription>{latest ? latest.period : "No period"}</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{latest ? formatNaira(latest.revenue) : (isLoading ? "Loading..." : "-")}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Expenses (Latest Period)</CardTitle>
            <CardDescription>{latest ? latest.period : "No period"}</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{latest ? formatNaira(latest.expenses) : (isLoading ? "Loading..." : "-")}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Profit Margin (Latest Period)</CardTitle>
            <CardDescription>Profit / Revenue</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{latest ? `${marginPercent.toFixed(1)}%` : (isLoading ? "Loading..." : "-")}</div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Revenue vs Expenses</CardTitle>
            <CardDescription>Per financial period from latest GL snapshot</CardDescription>
          </CardHeader>
          <CardContent className="pl-2">
            {series.length > 0 ? (
              <ResponsiveContainer width="100%" height={320}>
                <BarChart data={series}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="period" stroke="#888888" fontSize={12} tickLine={false} axisLine={false} />
                  <YAxis stroke="#888888" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(v) => `₦${(v / 1_000_000).toFixed(1)}M`} />
                  <Tooltip formatter={(value: any) => formatNaira(Number(value))} />
                  <Legend />
                  <Bar dataKey="revenue" name="Revenue" fill="#2FA24A" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="expenses" name="Expenses" fill="#dc2626" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-muted-foreground py-8 text-center">
                {isLoading ? "Loading chart data..." : "No profitability chart data yet."}
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Profit Trend</CardTitle>
            <CardDescription>Net profit per period</CardDescription>
          </CardHeader>
          <CardContent className="pl-2">
            {series.length > 0 ? (
              <ResponsiveContainer width="100%" height={320}>
                <LineChart data={series}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="period" stroke="#888888" fontSize={12} tickLine={false} axisLine={false} />
                  <YAxis stroke="#888888" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(v) => `₦${(v / 1_000_000).toFixed(1)}M`} />
                  <Tooltip formatter={(value: any) => formatNaira(Number(value))} />
                  <Line type="monotone" dataKey="profit" name="Profit" stroke="#1568C4" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-muted-foreground py-8 text-center">
                {isLoading ? "Loading trend data..." : "No profit trend data yet."}
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
