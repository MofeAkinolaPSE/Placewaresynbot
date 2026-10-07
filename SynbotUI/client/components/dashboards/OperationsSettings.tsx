/**
 * Operations › Settings: the rules the Operations screens run on, stated once
 * and briefly. Replaces cards describing the retired Sage snapshot pipeline
 * (ops_orders_snapshot, "Sage snapshot + inventory_events", the /ops/import CSV).
 */
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, PackageSearch, Shield, Truck } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api-client";

function Rows({ rows }: { rows: [string, string][] }) {
  return (
    <dl className="space-y-2 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="flex justify-between gap-4 border-b pb-1.5 last:border-0">
          <dt className="text-muted-foreground">{k}</dt>
          <dd className="text-right font-medium">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function OperationsSettings() {
  const { data: s } = useQuery({ queryKey: ["stock-orders-summary"], queryFn: () => api.procurement.stockOrdersSummary() });
  const p = s?.policy ?? {};
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card>
        <CardHeader className="pb-2"><CardTitle className="flex items-center gap-2 text-sm"><PackageSearch className="h-4 w-4" />Stock</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <Rows rows={[
            ["Source of stock", "ACE Books (FIFO, by batch)"],
            ["Stock in", "Supplier bill or approved adjustment"],
            ["Stock out", "Invoice approved by Finance"],
            ["Write-off / count change", "Adjustment, second approver"],
          ]} />
          <Link to="/inventory" className="inline-flex items-center text-xs text-primary hover:underline">Inventory workspace <ArrowUpRight className="ml-0.5 h-3 w-3" /></Link>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="pb-2"><CardTitle className="flex items-center gap-2 text-sm"><Truck className="h-4 w-4" />Reorder planning</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <Rows rows={[
            ["Demand", p.demand_days ? `average of the last ${p.demand_days} days` : "—"],
            ["Supplier lead time", p.lead_days ? `${p.lead_days} days` : "—"],
            ["Safety stock", p.safety_days ? `${p.safety_days} days of demand` : "—"],
            ["Order covers", p.cover_days ? `${p.cover_days} days after arrival` : "—"],
            ["Order received when", "its supplier bill is posted"],
          ]} />
          <Link to="/operations/purchase-orders" className="inline-flex items-center text-xs text-primary hover:underline">Stock Orders & Purchases <ArrowUpRight className="ml-0.5 h-3 w-3" /></Link>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="pb-2"><CardTitle className="flex items-center gap-2 text-sm"><Shield className="h-4 w-4" />Who can do what</CardTitle></CardHeader>
        <CardContent>
          <Rows rows={[
            ["Raise / approve / place stock orders", "admin, ops, procurement, finance, management"],
            ["Log stock adjustments", "admin, ops, finance"],
            ["Approve adjustments", "a second person: admin, ops, finance, management"],
            ["Record supplier bills", "admin, finance"],
            ["See supplier balances", "admin, ops, procurement, finance, management"],
          ]} />
        </CardContent>
      </Card>
    </div>
  );
}
