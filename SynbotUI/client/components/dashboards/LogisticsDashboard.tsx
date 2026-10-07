/**
 * Operations › Logistics: order-to-dispatch and delivery timings from Frontdesk
 * and the delivery board, and stock economics (turnover, days of stock, expiry)
 * from ACE Books. Replaces cards that read empty ops snapshot tables
 * ("Data error") and derived "fulfilment time" from Sage invoice dates.
 */
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlarmClock, Loader2, PackageCheck, RefreshCcw, Truck } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { api } from "@/lib/api-client";
import { fmtDate, naira, num } from "@/lib/books-api";

function duration(hours: number | null | undefined): string {
  if (hours == null) return "—";
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min`;
  if (hours < 48) return `${hours.toFixed(1)} h`;
  return `${(hours / 24).toFixed(1)} days`;
}

const compact = (v: number) => (Math.abs(v) >= 1e9 ? `₦${(v / 1e9).toFixed(1)}bn` : Math.abs(v) >= 1e6 ? `₦${(v / 1e6).toFixed(0)}M` : naira(v));

export function LogisticsDashboard() {
  const navigate = useNavigate();
  const { data: d, isLoading, error } = useQuery({ queryKey: ["ops-overview"], queryFn: () => api.ops.overview(12), refetchInterval: 120000 });
  if (isLoading) return <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>;
  if (error || !d) return <p className="p-6 text-sm text-destructive">Could not load the operations overview: {(error as Error)?.message}</p>;
  const o = d.orders, dl = d.deliveries, st = d.stock;

  return (
    <div className="space-y-5">
      <KpiStrip
        items={[
          { label: "Order to dispatch", value: duration(o.avg_hours_to_dispatch), icon: AlarmClock,
            sub: `${num(o.dispatched)} dispatched · ${num(o.awaiting_dispatch)} waiting · approval ${duration(o.avg_hours_to_approval)}`, onClick: () => navigate("/frontdesk") },
          { label: "Deliveries completed", value: `${num(dl.delivered)} / ${num(dl.total)}`, icon: Truck, tone: dl.unassigned > 0 ? "warning" : "default",
            sub: `${num(dl.in_transit)} in transit · ${num(dl.assigned)} assigned · ${num(dl.unassigned)} unassigned`, onClick: () => navigate("/operations/logistics") },
          { label: "Stock turnover", value: st.turnover != null ? `${st.turnover}× a year` : "—", icon: RefreshCcw,
            sub: st.days_of_stock != null ? `≈ ${num(st.days_of_stock)} days of stock · ${compact(st.value)} at cost` : undefined },
          { label: "Expiring within 90 days", value: compact(st.expiring_90d_value), icon: PackageCheck, tone: st.expiring_90d_value > 0 ? "warning" : "success",
            sub: `${num(st.expiring_90d_items)} items at cost`, onClick: () => navigate("/inventory") },
        ]}
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Sales and cost of sales by month</CardTitle>
            <CardDescription>Dated sales (Sage history to go-live, ACE Books after), to {fmtDate(d.as_of)}.</CardDescription>
          </CardHeader>
          <CardContent className="pl-1">
            <ResponsiveContainer width="100%" height={300}>
              <ComposedChart data={d.monthly}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="period" fontSize={11} tickLine={false} axisLine={false} />
                <YAxis yAxisId="v" fontSize={11} tickLine={false} axisLine={false} tickFormatter={compact} width={60} />
                <YAxis yAxisId="u" orientation="right" fontSize={11} tickLine={false} axisLine={false} width={50} />
                <Tooltip formatter={(v: number, name: string) => (name === "Units sold" ? num(v) : naira(v))} />
                <Legend />
                <Bar yAxisId="v" dataKey="sales" name="Sales" fill="hsl(var(--primary))" radius={[3, 3, 0, 0]} />
                <Bar yAxisId="v" dataKey="cost" name="Cost of sales" fill="hsl(var(--muted-foreground))" radius={[3, 3, 0, 0]} />
                <Line yAxisId="u" type="monotone" dataKey="units" name="Units sold" stroke="hsl(var(--success))" strokeWidth={2} dot={{ r: 2 }} />
              </ComposedChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Stock position</CardTitle>
            <CardDescription>ACE Books, FIFO at cost</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {[
              ["Stock value", naira(st.value)],
              ["Units on hand", num(st.units)],
              ["Items in stock", num(st.items_in_stock)],
              ["Cost of sales, 12 months", naira(st.cogs_12m)],
              ["Days of stock", st.days_of_stock != null ? num(st.days_of_stock) : "—"],
              ["Expiring ≤ 90 days", `${naira(st.expiring_90d_value)} (${num(st.expiring_90d_items)} items)`],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between gap-3 border-b pb-1.5 last:border-0">
                <span className="text-muted-foreground">{k}</span><span className="text-right font-medium">{v}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
