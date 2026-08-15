import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AlertCircle, Package, PlusCircle, Loader2 } from "lucide-react";
import { InventoryDashboardData } from "@shared/dashboard-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "@/lib/api-client";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { useIsMobile } from "@/hooks/use-mobile";
import { useToast } from "@/hooks/use-toast";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { FilterBar } from "@/components/workspace/FilterBar";
import { DetailSheet } from "@/components/workspace/DetailSheet";

// ─── helpers ──────────────────────────────────────────────────────────────────

function buildRef(batch: string, expiry: string, storage: string, po: string): string {
  const parts: string[] = [];
  if (po.trim())      parts.push(po.trim());
  if (batch.trim())   parts.push(`Batch: ${batch.trim()}`);
  if (expiry.trim())  parts.push(`Exp: ${expiry.trim()}`);
  if (storage && storage !== "none") parts.push(storage);
  return parts.join(" | ");
}

type StockStatus = "Critical" | "Low" | "OK" | "In Stock" | "Out of Stock" | "No Qty";

function stockStatus(qty: number, reorderLevel: number): StockStatus {
  if (qty <= 0) return "Out of Stock";
  if (reorderLevel <= 0) return "In Stock";
  if (qty <= reorderLevel) return "Critical";
  if (qty <= reorderLevel * 1.2) return "Low";
  return "OK";
}

function statusVariant(s: StockStatus): "destructive" | "secondary" | "outline" | "default" {
  if (s === "Critical" || s === "Out of Stock") return "destructive";
  if (s === "Low") return "secondary";
  if (s === "OK" || s === "In Stock") return "outline";
  return "secondary";
}

// ─── component ────────────────────────────────────────────────────────────────

export function InventoryDashboard({ data: initialData }: { data?: InventoryDashboardData }) {
  const isMobile = useIsMobile();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  // view state
  const [viewMode, setViewMode] = useState<"in-stock" | "all">("in-stock");
  const [stockSearch, setStockSearch] = useState("");
  const [companyFilter, setCompanyFilter] = useState<string>("");

  // stock-entry modal state
  const [selectedItem, setSelectedItem] = useState<{ sku: string; name: string } | null>(null);
  const [entryQty, setEntryQty] = useState("");
  const [entryBatch, setEntryBatch] = useState("");
  const [entryExpiry, setEntryExpiry] = useState("");
  const [entryStorage, setEntryStorage] = useState("none");
  const [entryRef, setEntryRef] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // ─── queries ──────────────────────────────────────────────────────────────

  const { data: fetchedData, isLoading, error } = useQuery({
    queryKey: ["inventory-dashboard"],
    queryFn: () => api.dashboard.inventory(),
    enabled: !initialData,
    refetchInterval: 60000,
  });

  const { data: allStockRows, isLoading: stockLoading } = useQuery({
    queryKey: ["inventory-all-stock"],
    queryFn: () => api.inventory.stock(),
    refetchInterval: 60000,
  });

  useRealtimeChannel(
    "inventory_updates",
    (msg) => {
      if (msg?.event && msg.event !== "subscriber_joined" && msg.event !== "pong") {
        queryClient.invalidateQueries({ queryKey: ["inventory-dashboard"] });
        queryClient.invalidateQueries({ queryKey: ["inventory-all-stock"] });
      }
    },
    !initialData,
  );

  const data = initialData || fetchedData;
  const dataValid =
    !!data &&
    typeof data.summary?.total_active_skus === "number" &&
    typeof data.summary?.low_stock_count === "number" &&
    typeof data.summary?.out_of_stock_count === "number";

  const summary = dataValid
    ? data.summary
    : { total_active_skus: 0, low_stock_count: 0, out_of_stock_count: 0 };

  const allStock: any[] = Array.isArray(allStockRows) ? allStockRows : [];

  // ─── derived rows ─────────────────────────────────────────────────────────

  const filteredRows = useMemo(() => {
    const q = stockSearch.trim().toLowerCase();
    const base = allStock.filter((r: any) => {
      const matchSearch =
        !q ||
        String(r.sku ?? "").toLowerCase().includes(q) ||
        String(r.name ?? r.item_name ?? "").toLowerCase().includes(q);
      const matchCompany =
        !companyFilter || (r.company_id ?? "") === companyFilter;
      return matchSearch && matchCompany;
    });

    if (viewMode === "in-stock") {
      const withStock = base.filter((r: any) => Number(r.current_stock ?? r.quantity ?? 0) > 0);
      // sort: items below reorder level first, then by qty desc
      withStock.sort((a: any, b: any) => {
        const aqty = Number(a.current_stock ?? 0);
        const bqty = Number(b.current_stock ?? 0);
        const arl  = Number(a.reorder_level ?? 0);
        const brl  = Number(b.reorder_level ?? 0);
        const aUrgent = arl > 0 && aqty <= arl ? 1 : 0;
        const bUrgent = brl > 0 && bqty <= brl ? 1 : 0;
        if (aUrgent !== bUrgent) return bUrgent - aUrgent;
        return bqty - aqty;
      });
      return withStock;
    }
    return base;
  }, [allStock, stockSearch, companyFilter, viewMode]);

  // ─── stock entry submit ───────────────────────────────────────────────────

  const handleAddStock = async () => {
    if (!selectedItem) return;
    const qty = parseFloat(entryQty);
    if (!qty || qty <= 0) {
      toast({ title: "Validation Error", description: "Quantity must be greater than 0", variant: "destructive" });
      return;
    }
    try {
      setSubmitting(true);
      await api.inventory.addStock({
        sku: selectedItem.sku,
        quantity_change: qty,
        event_type: "RESTOCK",
        reference: buildRef(entryBatch, entryExpiry, entryStorage, entryRef) || undefined,
      });
      toast({ title: "Stock Added", description: `${qty} units of ${selectedItem.name} added successfully.` });
      setSelectedItem(null);
      setEntryQty(""); setEntryBatch(""); setEntryExpiry(""); setEntryStorage("none"); setEntryRef("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["inventory-all-stock"] }),
        queryClient.invalidateQueries({ queryKey: ["inventory-dashboard"] }),
      ]);
      setViewMode("in-stock");
    } catch (err: any) {
      toast({ title: "Failed to Add Stock", description: err?.message ?? "Unknown error", variant: "destructive" });
    } finally {
      setSubmitting(false);
    }
  };

  // ─── render ───────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col gap-4">
      {error && (
        <div className="text-sm text-destructive">
          Data error: inventory dashboard payload is unavailable or malformed.
        </div>
      )}

      {/* KPI Row */}
      <KpiStrip
        items={[
          {
            label: "Total Active SKUs",
            value: dataValid ? summary.total_active_skus : (isLoading ? "…" : "—"),
            icon: Package,
          },
          {
            label: "Low Stock Alerts",
            value: dataValid ? summary.low_stock_count : (isLoading ? "…" : "—"),
            icon: AlertCircle,
            tone: dataValid && summary.low_stock_count > 0 ? "warning" : "default",
          },
          {
            label: "Out of Stock",
            value: dataValid ? summary.out_of_stock_count : (isLoading ? "…" : "—"),
            icon: AlertCircle,
            tone: dataValid && summary.out_of_stock_count > 0 ? "danger" : "default",
          },
        ]}
      />

      {/* Smart Inventory Table */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            {/* Mode selector */}
            <div className="flex items-center gap-2">
              <div className="flex rounded-md border overflow-hidden">
                <button
                  className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                    viewMode === "in-stock"
                      ? "bg-primary text-primary-foreground"
                      : "bg-background text-muted-foreground hover:bg-muted"
                  }`}
                  onClick={() => setViewMode("in-stock")}
                >
                  Items with Stock
                </button>
                <button
                  className={`px-3 py-1.5 text-xs font-medium transition-colors border-l ${
                    viewMode === "all"
                      ? "bg-primary text-primary-foreground"
                      : "bg-background text-muted-foreground hover:bg-muted"
                  }`}
                  onClick={() => setViewMode("all")}
                >
                  All Items
                </button>
              </div>
              <span className="text-xs text-muted-foreground tabular-nums">
                {stockLoading
                  ? "Loading…"
                  : viewMode === "in-stock"
                  ? `${filteredRows.length} on hand`
                  : `${filteredRows.length} items`}
              </span>
            </div>

            {/* Search + company filter */}
            <FilterBar
              search={{ value: stockSearch, onChange: setStockSearch, placeholder: "Search SKU or name…" }}
              selects={[
                {
                  label: "Company",
                  value: companyFilter,
                  onChange: setCompanyFilter,
                  options: [
                    { value: "PlacewareNig", label: "PlacewareNig" },
                    { value: "PlacewarePha", label: "PlacewarePha" },
                  ],
                  placeholder: "All Companies",
                  className: "h-8 w-[170px] text-xs",
                },
              ]}
            />
          </div>
        </CardHeader>

        <CardContent className="p-0">
          {stockLoading ? (
            <p className="p-4 text-sm text-muted-foreground">Loading inventory…</p>
          ) : filteredRows.length === 0 ? (
            <div className="p-6 text-center text-sm text-muted-foreground">
              {viewMode === "in-stock"
                ? "No items currently on hand — switch to All Items to add stock."
                : stockSearch
                ? `No matching items for "${stockSearch}"`
                : "No inventory data available."}
            </div>
          ) : isMobile ? (
            // ── Mobile card list ──────────────────────────────────────────
            <div className="space-y-3 p-3">
              {filteredRows.map((r: any, idx: number) => {
                const qty        = Number(r.current_stock ?? r.quantity ?? 0);
                const rl         = Number(r.reorder_level ?? 0);
                const name       = r.name ?? r.item_name ?? "—";
                const status     = stockStatus(qty, rl);
                const expiryRaw  = r.expiry_date as string | null | undefined;
                const expiryDate = expiryRaw ? new Date(expiryRaw) : null;
                const isExpired  = expiryDate ? expiryDate < new Date() : false;
                const nearExpiry = expiryDate ? expiryDate < new Date(Date.now() + 30 * 86400_000) : false;

                return (
                  <div key={r.sku ?? idx} className="rounded-lg border bg-card p-3 text-sm">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="font-mono text-xs font-medium leading-tight">{r.sku}</p>
                        <p className="text-xs text-muted-foreground">{name}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge variant={statusVariant(status)}>{status}</Badge>
                        {viewMode === "all" && (
                          <Button size="sm" variant="outline" className="h-6 text-xs px-2"
                            onClick={() => setSelectedItem({ sku: r.sku, name })}>
                            <PlusCircle className="h-3 w-3 mr-1" />Add
                          </Button>
                        )}
                      </div>
                    </div>
                    <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                      <span className="text-muted-foreground">Qty on Hand</span>
                      <span className="font-semibold">{qty.toLocaleString()}</span>
                      {rl > 0 && (
                        <>
                          <span className="text-muted-foreground">Reorder Level</span>
                          <span>{rl.toLocaleString()}</span>
                        </>
                      )}
                      {expiryDate && (
                        <>
                          <span className="text-muted-foreground">Expiry</span>
                          <span className={(isExpired || nearExpiry) ? "text-destructive font-semibold" : ""}>
                            {expiryDate.toLocaleDateString()}
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : viewMode === "in-stock" ? (
            // ── Items with Stock table ─────────────────────────────────────
            <div className="max-h-[480px] overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="sticky left-0 z-10 min-w-[130px] bg-muted/90">SKU</TableHead>
                    <TableHead className="min-w-[220px]">Name</TableHead>
                    <TableHead className="min-w-[110px]">Qty on Hand</TableHead>
                    <TableHead className="min-w-[160px]">Stock Health</TableHead>
                    <TableHead className="min-w-[110px]">Reorder Lvl</TableHead>
                    <TableHead className="min-w-[110px]">Expiry</TableHead>
                    <TableHead className="min-w-[110px]">Batch #</TableHead>
                    <TableHead className="min-w-[100px]">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredRows.map((r: any, idx: number) => {
                    const qty        = Number(r.current_stock ?? r.quantity ?? 0);
                    const rl         = Number(r.reorder_level ?? 0);
                    const name       = r.name ?? r.item_name ?? "—";
                    const status     = stockStatus(qty, rl);
                    const expiryRaw  = r.expiry_date as string | null | undefined;
                    const expiryDate = expiryRaw ? new Date(expiryRaw) : null;
                    const isExpired  = expiryDate ? expiryDate < new Date() : false;
                    const nearExpiry = expiryDate
                      ? expiryDate < new Date(Date.now() + 30 * 86400_000)
                      : false;

                    // health bar: fill = qty / (rl * 2), capped 0–100%
                    const hasThreshold = rl > 0;
                    const barPct = hasThreshold
                      ? Math.min(100, Math.round((qty / (rl * 2)) * 100))
                      : 50;
                    const barColor = !hasThreshold
                      ? "bg-muted-foreground/30"
                      : barPct <= 50
                      ? "bg-destructive"
                      : barPct <= 100
                      ? "bg-amber-400"
                      : "bg-emerald-500";

                    return (
                      <TableRow key={r.sku ?? idx}>
                        <TableCell className="sticky left-0 z-10 bg-background font-mono text-xs">
                          {r.sku}
                        </TableCell>
                        <TableCell className="text-sm">{name}</TableCell>
                        <TableCell className="font-bold tabular-nums">{qty.toLocaleString()}</TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <div className="h-1.5 w-24 rounded-full bg-muted overflow-hidden" title={hasThreshold ? `${barPct}% of safe level` : "No threshold set"}>
                              <div className={`h-full rounded-full ${barColor}`} style={{ width: `${barPct}%` }} />
                            </div>
                            {!hasThreshold && (
                              <span className="text-xs text-muted-foreground">—</span>
                            )}
                          </div>
                        </TableCell>
                        <TableCell className="text-xs tabular-nums">
                          {rl > 0 ? rl.toLocaleString() : <span className="text-muted-foreground">—</span>}
                        </TableCell>
                        <TableCell className={`text-xs ${(isExpired || nearExpiry) ? "text-destructive font-semibold" : "text-muted-foreground"}`}>
                          {expiryDate ? expiryDate.toLocaleDateString() : <span className="text-muted-foreground">—</span>}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {r.batch_number || <span>—</span>}
                        </TableCell>
                        <TableCell>
                          <Badge variant={statusVariant(status)}>{status}</Badge>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          ) : (
            // ── All Items table ─────────────────────────────────────────────
            <div className="max-h-[480px] overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="sticky left-0 z-10 min-w-[130px] bg-muted/90">SKU</TableHead>
                    <TableHead className="min-w-[240px]">Name</TableHead>
                    <TableHead className="min-w-[110px]">Category</TableHead>
                    <TableHead className="min-w-[110px]">Current Stock</TableHead>
                    <TableHead className="min-w-[110px]">Reorder Lvl</TableHead>
                    <TableHead className="min-w-[110px]">Status</TableHead>
                    <TableHead className="min-w-[90px] text-right">Action</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredRows.map((r: any, idx: number) => {
                    const qty    = Number(r.current_stock ?? r.quantity ?? 0);
                    const rl     = Number(r.reorder_level ?? 0);
                    const name   = r.name ?? r.item_name ?? "—";
                    const status = stockStatus(qty, rl);
                    return (
                      <TableRow key={r.sku ?? idx}>
                        <TableCell className="sticky left-0 z-10 bg-background font-mono text-xs">{r.sku}</TableCell>
                        <TableCell className="text-sm">{name}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">{r.category || "—"}</TableCell>
                        <TableCell className={`tabular-nums ${qty === 0 ? "text-muted-foreground" : "font-semibold"}`}>
                          {qty.toLocaleString()}
                        </TableCell>
                        <TableCell className="text-xs tabular-nums text-muted-foreground">
                          {rl > 0 ? rl.toLocaleString() : "—"}
                        </TableCell>
                        <TableCell>
                          <Badge variant={statusVariant(status)}>{status}</Badge>
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 px-2 text-xs"
                            onClick={() => setSelectedItem({ sku: r.sku, name })}
                          >
                            <PlusCircle className="h-3 w-3 mr-1" />
                            Add Stock
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Stock Entry Panel */}
      <DetailSheet
        open={!!selectedItem}
        onOpenChange={(open) => { if (!open) setSelectedItem(null); }}
        title="Add Stock"
        description={selectedItem ? `Record incoming stock for ${selectedItem.name}` : undefined}
        icon={PlusCircle}
        footer={
          <>
            <Button variant="outline" onClick={() => setSelectedItem(null)}>Cancel</Button>
            <Button onClick={handleAddStock} disabled={submitting || !entryQty || Number(entryQty) <= 0}>
              {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Add Stock
            </Button>
          </>
        }
      >
        {/* Item read-only */}
        <div className="space-y-2">
          <Label className="text-xs text-muted-foreground">Item</Label>
          <div className="rounded-md border bg-muted/40 px-3 py-1.5 text-xs">
            <span className="font-mono">{selectedItem?.sku}</span>
            <span className="ml-2 text-muted-foreground">{selectedItem?.name}</span>
          </div>
        </div>
        {/* Quantity */}
        <div className="space-y-2">
          <Label htmlFor="entry-qty" className="text-xs">Quantity <span className="text-destructive">*</span></Label>
          <Input
            id="entry-qty"
            type="number"
            min="1"
            step="1"
            className="h-8 text-xs"
            placeholder="e.g. 100"
            value={entryQty}
            onChange={(e) => setEntryQty(e.target.value)}
          />
        </div>
        {/* Batch */}
        <div className="space-y-2">
          <Label htmlFor="entry-batch" className="text-xs">Batch #</Label>
          <Input
            id="entry-batch"
            className="h-8 text-xs"
            placeholder="Optional — e.g. BN-2024-01"
            value={entryBatch}
            onChange={(e) => setEntryBatch(e.target.value)}
          />
        </div>
        {/* Expiry */}
        <div className="space-y-2">
          <Label htmlFor="entry-expiry" className="text-xs">Expiry Date</Label>
          <Input
            id="entry-expiry"
            type="date"
            className="h-8 text-xs"
            value={entryExpiry}
            onChange={(e) => setEntryExpiry(e.target.value)}
          />
        </div>
        {/* Storage */}
        <div className="space-y-2">
          <Label className="text-xs">Storage</Label>
          <Select value={entryStorage} onValueChange={setEntryStorage}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="Select storage condition" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">Not specified</SelectItem>
              <SelectItem value="Ambient">Ambient</SelectItem>
              <SelectItem value="Cold Chain (2–8°C)">Cold Chain (2–8°C)</SelectItem>
              <SelectItem value="Frozen (-20°C)">Frozen (-20°C)</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {/* Reference / PO */}
        <div className="space-y-2">
          <Label htmlFor="entry-ref" className="text-xs">Reference / PO#</Label>
          <Input
            id="entry-ref"
            className="h-8 text-xs"
            placeholder="Optional — e.g. PO-2024-001"
            value={entryRef}
            onChange={(e) => setEntryRef(e.target.value)}
          />
        </div>
      </DetailSheet>
    </div>
  );
}
