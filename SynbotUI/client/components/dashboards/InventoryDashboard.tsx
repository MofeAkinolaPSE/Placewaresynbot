import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { AlertCircle, Package, CheckCircle2 } from "lucide-react";
import { InventoryDashboardData } from "@shared/dashboard-types";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";

export function InventoryDashboard({ data: initialData }: { data?: InventoryDashboardData }) {
  const { data: fetchedData, isLoading, error } = useQuery({
    queryKey: ["inventory-dashboard"],
    queryFn: () => api.dashboard.inventory(),
    // Only fetch if initialData is not provided (or we want to prioritize fresh data)
    enabled: !initialData,
    refetchInterval: 60000
  });

  const data = initialData || fetchedData;

  const dataValid =
    !!data &&
    typeof data.summary?.total_active_skus === "number" &&
    typeof data.summary?.low_stock_count === "number" &&
    typeof data.summary?.out_of_stock_count === "number" &&
    Array.isArray(data.critical_items) &&
    Array.isArray(data.recent_movements);

  const summary = dataValid
    ? data.summary
    : { total_active_skus: 0, low_stock_count: 0, out_of_stock_count: 0 };
  const criticalItems = dataValid ? data.critical_items : [];
  const recentMovements = dataValid ? data.recent_movements : [];

  return (
    <div className="space-y-6">
      {error && (
        <div className="text-sm text-destructive">
          Data error: inventory dashboard payload is unavailable or malformed.
        </div>
      )}
      {/* KPI Row */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Active SKUs</CardTitle>
            <Package className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {dataValid ? summary.total_active_skus : (isLoading ? "Loading..." : "-")}
            </div>
            <p className="text-xs text-muted-foreground">From Sage 2013 Snapshot</p>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Low Stock Alerts</CardTitle>
            <AlertCircle className="h-4 w-4 text-yellow-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{dataValid ? summary.low_stock_count : (isLoading ? "..." : "-")}</div>
            <p className="text-xs text-muted-foreground">Below threshold</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Out of Stock</CardTitle>
            <AlertCircle className="h-4 w-4 text-red-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-red-500">{dataValid ? summary.out_of_stock_count : (isLoading ? "..." : "-")}</div>
            <p className="text-xs text-muted-foreground">Requires immediate attention</p>
          </CardContent>
        </Card>
      </div>

      {/* Critical Items Table */}
      <Card>
        <CardHeader>
          <CardTitle>Critical Inventory Items</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>SKU</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Baseline (Sage)</TableHead>
                <TableHead>Net Change</TableHead>
                <TableHead>Current Stock</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {criticalItems.map((item) => (
                <TableRow key={item.sku}>
                  <TableCell className="font-medium">{item.sku}</TableCell>
                  <TableCell>{item.name}</TableCell>
                  <TableCell>{item.baseline.quantity}</TableCell>
                  <TableCell className={item.events.net_change < 0 ? "text-red-500" : "text-green-500"}>
                    {item.events.net_change}
                  </TableCell>
                  <TableCell className="font-bold">{item.current_stock}</TableCell>
                  <TableCell>
                    <Badge variant={item.current_stock > 0 ? "outline" : "destructive"}>
                      {item.status}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
              {!criticalItems.length && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground py-6">
                    {isLoading ? "Loading critical inventory items..." : "No critical inventory items."}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Recent Movements */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Inventory Movements</CardTitle>
        </CardHeader>
        <CardContent>
          {recentMovements.length === 0 ? (
            <p className="text-sm text-muted-foreground">{isLoading ? "Loading recent inventory movements..." : "No recent inventory movements recorded."}</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Timestamp</TableHead>
                  <TableHead>SKU</TableHead>
                  <TableHead>Change</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Reference</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recentMovements.map((mv: any, idx: number) => (
                  <TableRow key={idx}>
                    <TableCell>{mv.created_at ? new Date(mv.created_at).toLocaleString() : "-"}</TableCell>
                    <TableCell>{mv.sku}</TableCell>
                    <TableCell className={mv.change < 0 ? "text-red-500" : "text-green-600"}>
                      {mv.change}
                    </TableCell>
                    <TableCell>{mv.event_type}</TableCell>
                    <TableCell>{mv.reference || "-"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
