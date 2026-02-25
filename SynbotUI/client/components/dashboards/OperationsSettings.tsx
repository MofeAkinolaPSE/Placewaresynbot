import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AlertCircle, UploadCloud, Shield, PackageSearch } from "lucide-react";

export function OperationsSettings() {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Ops Data Source</CardTitle>
            <CardDescription>Orders & downtime snapshots from Sage exports.</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Operations metrics (fulfillment time, downtime, stock turnover) are computed from
              <span className="font-semibold"> ops_orders_snapshot</span>,
              <span className="font-semibold"> ops_downtime_snapshot</span>, and the latest
              <span className="font-semibold"> sage_inventory_snapshot</span>.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Inventory Behaviour</CardTitle>
            <CardDescription>Baseline from Sage + operational events.</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Live stock is calculated as <span className="font-mono">Sage snapshot</span> +
              <span className="font-mono"> inventory_events</span> (RESTOCK, SALE, DAMAGE, EXPIRY, ADJUSTMENT)
              recorded via the Operations console.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Access Control</CardTitle>
            <CardDescription>Who can change what.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            <p>
              <span className="font-semibold">Inventory write</span>: roles
              <span className="font-mono"> admin</span>,
              <span className="font-mono"> ops</span>,
              <span className="font-mono"> finance</span>.
            </p>
            <p>
              <span className="font-semibold">Inventory read</span>: roles
              <span className="font-mono"> admin</span>,
              <span className="font-mono"> ops</span>,
              <span className="font-mono"> finance</span>,
              <span className="font-mono"> sales</span>.
            </p>
            <p>
              <span className="font-semibold">Ops analytics</span> (/ops/*): roles
              <span className="font-mono"> admin</span>,
              <span className="font-mono"> ops</span>.
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader className="flex items-center justify-between">
            <div>
              <CardTitle>Ops Import (Orders & Downtime)</CardTitle>
              <CardDescription>Configure how logistics data is fed into Placeware.</CardDescription>
            </div>
            <UploadCloud className="h-5 w-5 text-muted-foreground" />
          </CardHeader>
          <CardContent className="space-y-4 text-sm text-muted-foreground">
            <div>
              <p className="font-semibold mb-1">Endpoint</p>
              <p className="font-mono text-xs bg-muted px-2 py-1 rounded">
                POST /ops/import (multipart/form-data)
              </p>
            </div>
            <div>
              <p className="font-semibold mb-1">Orders CSV (required columns)</p>
              <p className="font-mono text-xs bg-muted px-2 py-1 rounded break-all">
                order_id, created_at, fulfilled_at, sku, quantity
              </p>
            </div>
            <div>
              <p className="font-semibold mb-1">Downtime CSV (required columns)</p>
              <p className="font-mono text-xs bg-muted px-2 py-1 rounded break-all">
                machine_id, started_at, ended_at, minutes
              </p>
            </div>
            <p>
              Successful imports create new snapshot batches and immediately refresh Logistics KPIs
              and the stock turnover charts.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex items-center justify-between">
            <div>
              <CardTitle>Inventory Alerts & Thresholds</CardTitle>
              <CardDescription>How "critical" and "low" stock are derived.</CardDescription>
            </div>
            <PackageSearch className="h-5 w-5 text-muted-foreground" />
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <p>
              The Inventory dashboard flags <span className="font-semibold">critical items</span> where
              <span className="font-mono"> current_stock &lt; 10</span> units. Out-of-stock is when
              <span className="font-mono"> current_stock &lt;= 0</span>.
            </p>
            <p>
              These thresholds are currently fixed in the backend for Phase 1 and applied consistently
              across all inventory and Logistics views.
            </p>
            <div className="flex items-center gap-2">
              <Badge variant="outline">Planned</Badge>
              <span className="text-xs">
                Future releases will allow admin-configurable thresholds per SKU or category.
              </span>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="border-amber-200 bg-amber-50/60">
        <CardHeader className="flex items-center gap-2">
          <AlertCircle className="h-5 w-5 text-amber-600" />
          <div>
            <CardTitle className="text-sm">Operational Safety Note</CardTitle>
            <CardDescription>
              Ops settings control how Placeware interprets Sage exports and live movements.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="text-sm text-amber-800 space-y-1">
          <p>
            - Always validate CSV headers before importing into /ops/import to avoid corrupting
            historical trend lines.
          </p>
          <p>
            - Use inventory events (Record Movement) only for real-world adjustments; Sage remains the
            system of record for baseline quantities.
          </p>
          <p>
            - Restrict ops/admin roles in your JWTs to trusted users only.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
