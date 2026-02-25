import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { OpsKpis, OpsForecast } from "@shared/dashboard-types";
import { Truck, Clock, Activity } from "lucide-react";
import { ResponsiveContainer, LineChart, Line, CartesianGrid, XAxis, YAxis, Tooltip, Legend } from "recharts";

interface LogisticsKpis extends OpsKpis {}
interface LogisticsForecast extends OpsForecast {}

export function LogisticsDashboard() {
  const { data: kpis, isLoading: kpisLoading, error: kpisError } = useQuery<LogisticsKpis>({
    queryKey: ["ops-kpis"],
    queryFn: () => api.ops.kpis(),
    refetchInterval: 60000,
  });

  const { data: forecast, isLoading: forecastLoading, error: forecastError } = useQuery<LogisticsForecast>({
    queryKey: ["ops-forecast-stock-turnover"],
    queryFn: () => api.ops.forecastStockTurnover(),
    refetchInterval: 300000,
  });

  const isLoading = kpisLoading && !kpis && forecastLoading && !forecast;

  if (isLoading) {
    return <div className="p-10 text-center">Loading logistics metrics...</div>;
  }

  if (kpisError) {
    // We still try to render forecast chart even if KPIs fail
    console.error("Failed to load ops KPIs", kpisError);
  }

  if (forecastError) {
    console.error("Failed to load stock turnover forecast", forecastError);
  }

  const kpisValid =
    !!kpis &&
    typeof kpis.fulfillment_days_avg === "number" &&
    typeof kpis.downtime_minutes_total === "number" &&
    typeof kpis.stock_turnover === "number";
  const forecastValid = !!forecast && Array.isArray(forecast.series) && Array.isArray(forecast.rolling);

  if (!kpisValid && !forecastValid) {
    return <div className="p-10 text-center text-red-500">Data error: logistics payloads are unavailable or malformed.</div>;
  }

  const series = forecastValid ? forecast.series : [];
  const rolling = forecastValid ? forecast.rolling : [];

  const chartData = (series.length > 0
    ? series.map((point, idx) => ({
        period: point.period,
        turnover: point.turnover,
        rolling: typeof rolling[idx] === "number" ? rolling[idx] : undefined,
      }))
    : []) as Array<{
    period: string;
    turnover: number;
    rolling?: number;
  }>;

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Avg Fulfillment Time</CardTitle>
            <Clock className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {kpisValid ? `${kpis.fulfillment_days_avg.toFixed(1)} days` : "Data error"}
            </div>
            <p className="text-xs text-muted-foreground">Average days from order to fulfillment.</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Downtime</CardTitle>
            <Activity className="h-4 w-4 text-red-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{kpisValid ? `${kpis.downtime_minutes_total.toFixed(0)} min` : "Data error"}</div>
            <p className="text-xs text-muted-foreground">Summed across all recorded downtime events.</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Stock Turnover</CardTitle>
            <Truck className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{kpisValid ? `${kpis.stock_turnover.toFixed(2)}x` : "Data error"}</div>
            <p className="text-xs text-muted-foreground">sum(quantity_sold) / avg inventory quantity.</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle>Stock Turnover Trend</CardTitle>
            <CardDescription>Historical turnover with rolling average from ops orders and inventory snapshots.</CardDescription>
          </CardHeader>
          <CardContent className="pl-2">
            {chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={320}>
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="period" stroke="#888888" fontSize={12} tickLine={false} axisLine={false} />
                  <YAxis stroke="#888888" fontSize={12} tickLine={false} axisLine={false} />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="turnover" name="Turnover" stroke="#2563eb" strokeWidth={2} dot={{ r: 3 }} />
                  <Line type="monotone" dataKey="rolling" name="Rolling Avg" stroke="#16a34a" strokeWidth={2} dot={{ r: 2 }} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-destructive p-4">Data error: stock turnover series unavailable.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Data Sources</CardTitle>
            <CardDescription>How these logistics metrics are computed.</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="text-xs text-muted-foreground space-y-2">
              <li>
                <span className="font-semibold">Fulfillment time:</span> {kpis?.explain?.fulfillment_days_avg || "unavailable"}
              </li>
              <li>
                <span className="font-semibold">Downtime:</span> {kpis?.explain?.downtime_minutes_total || "unavailable"}
              </li>
              <li>
                <span className="font-semibold">Stock turnover:</span> {kpis?.explain?.stock_turnover || "unavailable"}
              </li>
              <li>
                <span className="font-semibold">Tables:</span> {Array.isArray(kpis?.explain?.sources) ? kpis.explain.sources.join(", ") : "unavailable"}
              </li>
            </ul>
          </CardContent>
        </Card>
      </div>
      {kpisError && <p className="text-xs text-destructive">{(kpisError as Error).message}</p>}
      {forecastError && <p className="text-xs text-destructive">{(forecastError as Error).message}</p>}
    </div>
  );
}
