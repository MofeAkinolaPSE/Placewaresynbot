import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AlertCircle, Package, Search } from "lucide-react";
import { InventoryDashboardData } from "@shared/dashboard-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "@/lib/api-client";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { useIsMobile } from "@/hooks/use-mobile";

export function InventoryDashboard({ data: initialData }: { data?: InventoryDashboardData }) {
  const isMobile = useIsMobile();
  const queryClient = useQueryClient();
  const [stockSearch, setStockSearch] = useState("");
  const [companyFilter, setCompanyFilter] = useState<string>("all");

  const { data: fetchedData, isLoading, error } = useQuery({
    queryKey: ["inventory-dashboard"],
    queryFn: () => api.dashboard.inventory(),
    // Only fetch if initialData is not provided (or we want to prioritize fresh data)
    enabled: !initialData,
    refetchInterval: 60000
  });

  const { data: allStockRows, isLoading: stockLoading } = useQuery({
    queryKey: ["inventory-all-stock"],
    queryFn: () => api.inventory.stock(),
    refetchInterval: 60000,
  });

  // Invalidate cached data whenever the backend emits an inventory event over
  // the realtime WebSocket (e.g. after a movement is recorded).
  useRealtimeChannel(
    "inventory_updates",
    (msg) => {
      if (msg?.event && msg.event !== "subscriber_joined" && msg.event !== "pong") {
        queryClient.invalidateQueries({ queryKey: ["inventory-dashboard"] });
      }
    },
    !initialData,
  );

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

  const allStock: any[] = Array.isArray(allStockRows) ? allStockRows : [];
  const filteredStock = useMemo(() => {
    const q = stockSearch.trim().toLowerCase();
    return allStock.filter((r: any) => {
      const matchSearch =
        !q ||
        String(r.sku ?? "").toLowerCase().includes(q) ||
        String(r.name ?? r.item_name ?? "").toLowerCase().includes(q);
      const matchCompany =
        companyFilter === "all" || (r.company_id ?? "") === companyFilter;
      return matchSearch && matchCompany;
    });
  }, [allStock, stockSearch, companyFilter]);

  return (
    <div className="flex flex-col gap-4">
      {error && (
        <div className="text-sm text-destructive">
          Data error: inventory dashboard payload is unavailable or malformed.
        </div>
      )}
      {/* KPI Row */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="border-l-4 border-l-primary">
          <CardHeader className="pb-1 pt-4">
            <div className="flex items-center justify-between">
              <CardTitle className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Total Active SKUs</CardTitle>
              <Package className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent className="pb-4">
            <div className="text-2xl font-bold tabular-nums">
              {dataValid ? summary.total_active_skus : (isLoading ? "Loading..." : "—")}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">From Sage 2013 Snapshot</p>
          </CardContent>
        </Card>

        <Card className={dataValid && summary.low_stock_count > 0 ? "border-l-4 border-l-warning" : "border-l-4 border-l-success"}>
          <CardHeader className="pb-1 pt-4">
            <div className="flex items-center justify-between">
              <CardTitle className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Low Stock Alerts</CardTitle>
              <AlertCircle className="h-4 w-4 text-warning" />
            </div>
          </CardHeader>
          <CardContent className="pb-4">
            <div className="text-2xl font-bold tabular-nums">{dataValid ? summary.low_stock_count : (isLoading ? "..." : "—")}</div>
            <p className="mt-1 text-xs text-muted-foreground">Below threshold</p>
          </CardContent>
        </Card>

        <Card className={dataValid && summary.out_of_stock_count > 0 ? "border-l-4 border-l-destructive" : "border-l-4 border-l-success"}>
          <CardHeader className="pb-1 pt-4">
            <div className="flex items-center justify-between">
              <CardTitle className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Out of Stock</CardTitle>
              <AlertCircle className="h-4 w-4 text-destructive" />
            </div>
          </CardHeader>
          <CardContent className="pb-4">
            <div className={`text-2xl font-bold tabular-nums ${dataValid && summary.out_of_stock_count > 0 ? 'text-destructive' : ''}`}>{dataValid ? summary.out_of_stock_count : (isLoading ? "..." : "—")}</div>
            <p className="mt-1 text-xs text-muted-foreground">Requires immediate attention</p>
          </CardContent>
        </Card>
      </div>

      {/* Critical Items Table */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base font-semibold">Critical Inventory Items</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {isMobile ? (
            <div className="space-y-3 p-3">
              {criticalItems.map((item) => (
                <div key={item.sku} className="rounded-lg border bg-card p-3 text-sm">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="font-medium leading-tight">{item.sku}</p>
                      <p className="text-xs text-muted-foreground">{item.name}</p>
                    </div>
                    <Badge variant={item.current_stock > 0 ? "outline" : "destructive"}>{item.status}</Badge>
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                    <span className="text-muted-foreground">Baseline</span>
                    <span>{item.baseline.quantity}</span>
                    <span className="text-muted-foreground">Net Change</span>
                    <span className={item.events.net_change < 0 ? "text-destructive" : "text-success"}>{item.events.net_change}</span>
                    <span className="text-muted-foreground">Current Stock</span>
                    <span className="font-semibold">{item.current_stock}</span>
                  </div>
                </div>
              ))}
              {!criticalItems.length && (
                <p className="py-4 text-center text-sm text-muted-foreground">
                  {isLoading ? "Loading critical inventory items..." : "No critical inventory items."}
                </p>
              )}
            </div>
          ) : (
            <div className="max-h-[320px] overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="sticky left-0 z-10 min-w-[130px] bg-muted/90">SKU</TableHead>
                    <TableHead className="min-w-[220px]">Name</TableHead>
                    <TableHead className="min-w-[130px]">Baseline (Sage)</TableHead>
                    <TableHead className="min-w-[120px]">Net Change</TableHead>
                    <TableHead className="min-w-[120px]">Current Stock</TableHead>
                    <TableHead className="min-w-[100px]">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {criticalItems.map((item) => (
                    <TableRow key={item.sku}>
                      <TableCell className="sticky left-0 z-10 bg-background font-medium">{item.sku}</TableCell>
                      <TableCell>{item.name}</TableCell>
                      <TableCell>{item.baseline.quantity}</TableCell>
                      <TableCell className={item.events.net_change < 0 ? "text-destructive" : "text-success"}>
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
                      <TableCell colSpan={6} className="py-6 text-center text-muted-foreground">
                        {isLoading ? "Loading critical inventory items..." : "No critical inventory items."}
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Recent Movements */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base font-semibold">Recent Inventory Movements</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {recentMovements.length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">{isLoading ? "Loading recent movements..." : "No recent inventory movements recorded."}</p>
          ) : isMobile ? (
            <div className="space-y-3 p-3">
              {recentMovements.map((mv: any, idx: number) => (
                <div key={idx} className="rounded-lg border bg-card p-3 text-sm">
                  <div className="flex items-center justify-between gap-3">
                    <p className="font-medium">{mv.sku}</p>
                    <span className={mv.change < 0 ? "font-semibold text-destructive" : "font-semibold text-success"}>{mv.change}</span>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{mv.event_type} • {mv.reference || "-"}</p>
                  <p className="mt-1 text-xs">{mv.created_at ? new Date(mv.created_at).toLocaleString() : "-"}</p>
                </div>
              ))}
            </div>
          ) : (
            <div className="max-h-[320px] overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="sticky left-0 z-10 min-w-[180px] bg-muted/90">Timestamp</TableHead>
                    <TableHead className="min-w-[110px]">SKU</TableHead>
                    <TableHead className="min-w-[90px]">Change</TableHead>
                    <TableHead className="min-w-[120px]">Type</TableHead>
                    <TableHead className="min-w-[130px]">Reference</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {recentMovements.map((mv: any, idx: number) => (
                    <TableRow key={idx}>
                      <TableCell className="sticky left-0 z-10 bg-background">{mv.created_at ? new Date(mv.created_at).toLocaleString() : "-"}</TableCell>
                      <TableCell>{mv.sku}</TableCell>
                      <TableCell className={mv.change < 0 ? "text-destructive" : "text-success"}>
                        {mv.change}
                      </TableCell>
                      <TableCell>{mv.event_type}</TableCell>
                      <TableCell>{mv.reference || "-"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
      {/* Full Inventory Table */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex flex-col gap-2">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <CardTitle className="text-base font-semibold">
                Full Inventory ({filteredStock.length}{filteredStock.length !== allStock.length ? ` / ${allStock.length}` : ""} SKUs)
              </CardTitle>
              <div className="relative w-full sm:w-64">
                <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  placeholder="Search SKU or name…"
                  value={stockSearch}
                  onChange={(e) => setStockSearch(e.target.value)}
                  className="h-8 pl-8 text-xs"
                />
              </div>
            </div>
            <div className="flex gap-1.5">
              {(["all", "PlacewareNig", "PlacewarePha"] as const).map((c) => (
                <Button
                  key={c}
                  size="sm"
                  variant={companyFilter === c ? "default" : "outline"}
                  className="h-7 text-xs px-3"
                  onClick={() => setCompanyFilter(c)}
                >
                  {c === "all" ? "All Companies" : c}
                </Button>
              ))}
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {stockLoading ? (
            <p className="p-4 text-sm text-muted-foreground">Loading inventory…</p>
          ) : allStock.length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No inventory data available.</p>
          ) : isMobile ? (
            <div className="space-y-3 p-3">
              {filteredStock.map((r: any, idx: number) => {
                const qty = Number(r.current_stock ?? r.quantity ?? 0);
                return (
                  <div key={r.sku ?? idx} className="rounded-lg border bg-card p-3 text-sm">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="font-medium leading-tight">{r.sku}</p>
                        <p className="text-xs text-muted-foreground">{r.name ?? r.item_name ?? "—"}</p>
                      </div>
                      <Badge variant={qty > 0 ? "default" : r.has_sage_qty ? "destructive" : "secondary"}>
                        {qty > 0 ? "In Stock" : r.has_sage_qty ? "Out of Stock" : "No Qty Recorded"}
                      </Badge>
                    </div>
                    <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                      <span className="text-muted-foreground">Qty on Hand</span>
                      <span className="font-semibold">{qty}</span>
                      {(r.unit_cost != null || r.cost_price != null) && (
                        <>
                          <span className="text-muted-foreground">Cost Price</span>
                          <span>₦{Number(r.unit_cost ?? r.cost_price).toLocaleString()}</span>
                        </>
                      )}
                      {r.category && (
                        <>
                          <span className="text-muted-foreground">Category</span>
                          <span>{r.category}</span>
                        </>
                      )}
                      {r.expiry_date && (
                        <>
                          <span className="text-muted-foreground">Expiry</span>
                          <span className={new Date(r.expiry_date) < new Date() ? "text-destructive font-semibold" : ""}>
                            {new Date(r.expiry_date).toLocaleDateString()}
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
              {filteredStock.length === 0 && (
                <p className="py-4 text-center text-sm text-muted-foreground">
                  {stockSearch
                    ? `No matching items for "${stockSearch}"`
                    : companyFilter !== "all"
                    ? `No items for ${companyFilter}`
                    : "No inventory data available."}
                </p>
              )}
            </div>
          ) : (
            <div className="max-h-[480px] overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="sticky left-0 z-10 min-w-[130px] bg-muted/90">SKU</TableHead>
                    <TableHead className="min-w-[240px]">Name</TableHead>
                    <TableHead className="min-w-[110px]">Category</TableHead>
                    <TableHead className="min-w-[110px]">Qty on Hand</TableHead>
                    <TableHead className="min-w-[120px]">Cost Price</TableHead>
                    <TableHead className="min-w-[120px]">Sell Price</TableHead>
                    <TableHead className="min-w-[120px]">Total Value</TableHead>
                    <TableHead className="min-w-[110px]">Expiry</TableHead>
                    <TableHead className="min-w-[110px]">Batch</TableHead>
                    <TableHead className="min-w-[110px]">Reorder Lvl</TableHead>
                    <TableHead className="min-w-[110px]">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredStock.map((r: any, idx: number) => {
                    const qty = Number(r.current_stock ?? r.quantity ?? 0);
                    const unitCost = Number(r.unit_cost ?? r.cost_price ?? 0);
                    const sellPrice = Number(r.selling_price ?? r.sell_price ?? 0);
                    const totalValue = qty * unitCost;
                    const expiryRaw = r.expiry_date as string | null | undefined;
                    const expiryDate = expiryRaw ? new Date(expiryRaw) : null;
                    const isExpired = expiryDate ? expiryDate < new Date() : false;
                    const reorderLevel = r.reorder_level != null ? Number(r.reorder_level) : null;
                    const belowReorder = reorderLevel !== null && qty <= reorderLevel;
                    return (
                      <TableRow key={r.sku ?? idx}>
                        <TableCell className="sticky left-0 z-10 bg-background font-mono text-xs">{r.sku}</TableCell>
                        <TableCell>{r.name ?? r.item_name ?? "—"}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">{r.category || "—"}</TableCell>
                        <TableCell className="font-semibold tabular-nums">{qty.toLocaleString()}</TableCell>
                        <TableCell className="tabular-nums">
                          {unitCost > 0 ? `₦${unitCost.toLocaleString()}` : "—"}
                        </TableCell>
                        <TableCell className="tabular-nums">
                          {sellPrice > 0 ? `₦${sellPrice.toLocaleString()}` : "—"}
                        </TableCell>
                        <TableCell className="tabular-nums">
                          {totalValue > 0 ? `₦${totalValue.toLocaleString()}` : "—"}
                        </TableCell>
                        <TableCell className={`text-xs ${isExpired ? "text-destructive font-semibold" : "text-muted-foreground"}`}>
                          {expiryDate ? expiryDate.toLocaleDateString() : "—"}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">{r.batch_number || "—"}</TableCell>
                        <TableCell className="text-xs tabular-nums">
                          {reorderLevel !== null ? (
                            <span className={belowReorder ? "text-destructive font-semibold" : "text-muted-foreground"}>
                              {reorderLevel.toLocaleString()}
                              {belowReorder && " ⚠"}
                            </span>
                          ) : "—"}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={qty > 0 ? "default" : r.has_sage_qty ? "destructive" : "secondary"}
                            className={qty > 0 && qty < 10 ? "border-warning/70 text-warning" : ""}
                          >
                            {qty > 0 ? "In Stock" : r.has_sage_qty ? "Out of Stock" : "No Qty Recorded"}
                          </Badge>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                  {filteredStock.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={11} className="py-6 text-center text-muted-foreground">
                        {stockSearch
                          ? `No matching items for "${stockSearch}"`
                          : companyFilter !== "all"
                          ? `No items for ${companyFilter}`
                          : "No inventory data available."}
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

