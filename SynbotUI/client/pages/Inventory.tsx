import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";
import { api } from "@/lib/api-client";
import { useToast } from "@/hooks/use-toast";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { PageHeader } from "@/components/workspace/PageHeader";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { FilterBar } from "@/components/workspace/FilterBar";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { EntityAutocomplete } from "@/components/workspace/EntityAutocomplete";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import {
  Package,
  AlertCircle,
  AlertTriangle,
  RotateCcw,
  PlusCircle,
  TrendingUp,
  Loader2,
  X,
  Users,
  ArrowRight,
} from "lucide-react";

type WorkspaceCard = {
  family: string;
  company_id: string | null;
  category: string | null;
  sku_count: number;
  total_stock: number;
  valuation: number;
  nearest_expiry_date: string | null;
  status: "critical" | "warning" | "adequate";
  suggested_reorder_qty: number;
  members: string[];
};

const STATUS_BADGE: Record<string, "destructive" | "secondary" | "outline"> = {
  critical: "destructive",
  warning: "secondary",
  out_of_stock: "destructive",
  adequate: "outline",
};

type InventorySearchResult = { sku?: string; name: string };

const Inventory = () => {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const [search, setSearch] = useState("");
  const [companyFilter, setCompanyFilter] = useState("");
  const [selectedFamily, setSelectedFamily] = useState<{ family: string; company_id: string | null } | null>(null);
  const [reorderQty, setReorderQty] = useState<Record<string, string>>({});

  // Add Stock / Log Adjustment — ported from Operations.tsx / InventoryDashboard.tsx
  const [addStockItem, setAddStockItem] = useState<{ sku: string; name: string } | null>(null);
  const [entryQty, setEntryQty] = useState("");
  const [entryRef, setEntryRef] = useState("");
  const [addStockSubmitting, setAddStockSubmitting] = useState(false);

  const [adjustmentOpen, setAdjustmentOpen] = useState(false);
  const [adjustment, setAdjustment] = useState({ sku: "", item_name: "", quantity_change: 0, event_type: "ADJUSTMENT", reference: "" });
  const [adjustmentSubmitting, setAdjustmentSubmitting] = useState(false);

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ["inventory-workspace-cards"] });
    queryClient.invalidateQueries({ queryKey: ["inventory-family-detail"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard-inventory"] });
    queryClient.invalidateQueries({ queryKey: ["inventory-pending-reorders"] });
    queryClient.invalidateQueries({ queryKey: ["inventory-top-sellers"] });
  };

  useRealtimeChannel("inventory_updates", () => invalidateAll());

  const { data: kpiData } = useQuery({
    queryKey: ["dashboard-inventory"],
    queryFn: () => api.dashboard.inventory(),
  });

  const { data: pendingReorders } = useQuery({
    queryKey: ["inventory-pending-reorders"],
    queryFn: () => api.inventory.pendingReordersCount(),
  });

  const { data: cards, isLoading: cardsLoading } = useQuery({
    queryKey: ["inventory-workspace-cards", companyFilter, search],
    queryFn: () => api.inventory.workspaceCards({ company_id: companyFilter || undefined, search: search || undefined }),
  });

  const { data: familyDetail, isLoading: detailLoading } = useQuery({
    queryKey: ["inventory-family-detail", selectedFamily?.family, selectedFamily?.company_id],
    queryFn: () => api.inventory.familyDetail(selectedFamily!.family, selectedFamily?.company_id || undefined),
    enabled: !!selectedFamily,
  });

  const { data: topSellers } = useQuery({
    queryKey: ["inventory-top-sellers"],
    queryFn: () => api.inventory.topSellers(8),
  });

  // Cross-link only — the full ranked queue with per-customer detail lives
  // in the Customer Workspace (customer-behavior data keyed by customer,
  // not stock data keyed by SKU; kept as two separate primary UIs on
  // purpose, same "shared data, different job" precedent as CRM.tsx vs
  // CustomerWorkspace.tsx).
  const { data: reorderQueue } = useQuery({
    queryKey: ["reorder-queue-count"],
    queryFn: () => api.crm.reorderQueue(100),
    staleTime: 60_000,
  });
  const overdueCustomerCount = Array.isArray(reorderQueue)
    ? reorderQueue.filter((p: any) => (p.days_until_or_since ?? 0) > 0).length
    : 0;

  const cardList: WorkspaceCard[] = Array.isArray(cards) ? cards : [];
  const summary = kpiData?.summary;

  const reorderMutation = useMutation({
    mutationFn: (vars: { sku: string; qty: number }) =>
      api.replenishment.create({ sku: vars.sku, requested_qty: vars.qty }),
    onSuccess: (_data, vars) => {
      toast({ title: "Reorder requested", description: `${vars.qty} units of ${vars.sku}` });
      queryClient.invalidateQueries({ queryKey: ["inventory-family-detail"] });
    },
    onError: (err: any) => toast({ title: "Reorder request failed", description: err.message, variant: "destructive" }),
  });

  const handleAddStock = async () => {
    if (!addStockItem) return;
    const qty = parseFloat(entryQty);
    if (!qty || qty <= 0) {
      toast({ title: "Validation Error", description: "Quantity must be greater than 0", variant: "destructive" });
      return;
    }
    try {
      setAddStockSubmitting(true);
      await api.inventory.addStock({
        sku: addStockItem.sku,
        quantity_change: qty,
        event_type: "RESTOCK",
        reference: entryRef || undefined,
      });
      toast({ title: "Stock Added", description: `${qty} units of ${addStockItem.name} added.` });
      setAddStockItem(null);
      setEntryQty("");
      setEntryRef("");
      invalidateAll();
    } catch (err: any) {
      toast({ title: "Failed to Add Stock", description: err?.message ?? "Unknown error", variant: "destructive" });
    } finally {
      setAddStockSubmitting(false);
    }
  };

  const handleLogAdjustment = async () => {
    if (!adjustment.sku.trim() || adjustment.quantity_change === 0) {
      toast({ title: "Validation Error", description: "Item and Quantity Change are required", variant: "destructive" });
      return;
    }
    try {
      setAdjustmentSubmitting(true);
      await api.inventory.addStock({
        sku: adjustment.sku,
        quantity_change: adjustment.quantity_change,
        event_type: adjustment.event_type,
        reference: adjustment.reference || undefined,
      });
      toast({ title: "Adjustment Recorded", description: `${adjustment.event_type} for ${adjustment.sku} recorded.` });
      setAdjustmentOpen(false);
      setAdjustment({ sku: "", item_name: "", quantity_change: 0, event_type: "ADJUSTMENT", reference: "" });
      invalidateAll();
    } catch (err: any) {
      toast({ title: "Failed to Record Adjustment", description: err.message, variant: "destructive" });
    } finally {
      setAdjustmentSubmitting(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionTransitions.standard}
      className="flex flex-col gap-5"
    >
      <PageHeader
        icon={Package}
        title="Inventory"
        subtitle="Live Stock Workspace"
        actions={
          <Button size="sm" variant="outline" onClick={() => setAdjustmentOpen(true)}>
            <RotateCcw className="mr-2 h-4 w-4" />
            Log Adjustment
          </Button>
        }
      />

      <KpiStrip
        items={[
          { label: "Live Families in Stock", value: cardList.length, icon: Package },
          {
            label: "Low / Critical Families",
            value: cardList.filter((c) => c.status === "critical" || c.status === "warning").length,
            icon: AlertTriangle,
            tone: cardList.some((c) => c.status === "critical") ? "danger" : "warning",
          },
          {
            label: "Out of Stock Alerts",
            value: summary?.out_of_stock_count ?? "—",
            icon: AlertCircle,
            tone: (summary?.out_of_stock_count ?? 0) > 0 ? "danger" : "default",
          },
          {
            label: "Pending Reorders",
            value: pendingReorders ?? "—",
            icon: RotateCcw,
            tone: (pendingReorders ?? 0) > 0 ? "warning" : "default",
          },
        ]}
      />

      {overdueCustomerCount > 0 && (
        <Card>
          <CardContent className="flex items-center justify-between p-3">
            <p className="text-sm text-muted-foreground">
              <span className="font-semibold text-foreground">{overdueCustomerCount}</span> customer{overdueCustomerCount === 1 ? "" : "s"} overdue for reorder
            </p>
            <Button asChild size="sm" variant="outline">
              <Link to="/customers/workspace">
                View Customer Workspace <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* List Panel: card grid */}
        <div className="lg:col-span-2 flex flex-col gap-3">
          <FilterBar
            search={{ value: search, onChange: setSearch, placeholder: "Search vaccine or SKU…" }}
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
              },
            ]}
          />

          {cardsLoading ? (
            <p className="text-sm text-muted-foreground p-4">Loading inventory…</p>
          ) : cardList.length === 0 ? (
            <Card>
              <CardContent className="p-6 text-center text-sm text-muted-foreground">
                No vaccines currently have live stock.
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {cardList.map((c) => (
                <Card
                  key={`${c.company_id ?? ""}::${c.family}`}
                  className={`cursor-pointer transition-colors hover:border-primary ${
                    selectedFamily?.family === c.family ? "border-primary ring-1 ring-primary" : ""
                  }`}
                  onClick={() => setSelectedFamily({ family: c.family, company_id: c.company_id })}
                >
                  <CardContent className="pt-4 pb-3">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="font-semibold text-sm">{c.family}</p>
                        <p className="text-xs text-muted-foreground">
                          {c.sku_count} batch{c.sku_count === 1 ? "" : "es"} · {c.category || "—"}
                        </p>
                      </div>
                      <Badge variant={STATUS_BADGE[c.status] ?? "outline"}>{c.status}</Badge>
                    </div>
                    <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                      <span className="text-muted-foreground">Total Stock</span>
                      <span className="font-semibold tabular-nums">{c.total_stock.toLocaleString()}</span>
                      <span className="text-muted-foreground">Valuation</span>
                      <span className="tabular-nums">₦{c.valuation.toLocaleString()}</span>
                      {c.nearest_expiry_date && (
                        <>
                          <span className="text-muted-foreground">Nearest Expiry</span>
                          <span>{new Date(c.nearest_expiry_date).toLocaleDateString()}</span>
                        </>
                      )}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>

        {/* Detail Workspace */}
        <div className="lg:col-span-1">
          {!selectedFamily ? (
            <Card className="h-full">
              <CardContent className="p-6 text-center text-sm text-muted-foreground">
                Select a vaccine card to view batch details, reorder, and top customers.
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base font-semibold">{selectedFamily.family}</CardTitle>
                  <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => setSelectedFamily(null)}>
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {detailLoading ? (
                  <p className="text-sm text-muted-foreground">Loading…</p>
                ) : familyDetail ? (
                  <>
                    <div className="space-y-2">
                      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Batches</p>
                      {familyDetail.members.map((m: any) => {
                        const pendingReq = (familyDetail.open_replenishment_requests || []).find((r: any) => r.sku === m.sku);
                        return (
                          <div key={m.sku} className="rounded-md border p-2.5 text-xs space-y-1.5">
                            <div className="flex items-center justify-between">
                              <span className="font-mono">{m.sku}</span>
                              <Badge variant={STATUS_BADGE[m.stock_status] ?? "outline"} className="text-[10px]">
                                {m.stock_status}
                              </Badge>
                            </div>
                            <div className="flex justify-between text-muted-foreground">
                              <span>Qty: {Number(m.current_stock).toLocaleString()}</span>
                              {m.expiry_date && <span>Exp: {new Date(m.expiry_date).toLocaleDateString()}</span>}
                            </div>
                            {(m.stock_status === "critical" || m.stock_status === "warning" || m.stock_status === "out_of_stock") && (
                              pendingReq ? (
                                <div className="flex items-center justify-between text-amber-700 bg-amber-50 rounded px-2 py-1 dark:text-amber-300 dark:bg-amber-500/15">
                                  <span>Reorder pending ({pendingReq.requested_qty})</span>
                                </div>
                              ) : (
                                <div className="flex items-center gap-1.5">
                                  <Input
                                    type="number"
                                    className="h-6 text-xs w-16"
                                    value={reorderQty[m.sku] ?? String(m.suggested_reorder_qty || 20)}
                                    onChange={(e) => setReorderQty({ ...reorderQty, [m.sku]: e.target.value })}
                                  />
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    className="h-6 px-2 text-[11px]"
                                    disabled={reorderMutation.isPending}
                                    onClick={() =>
                                      reorderMutation.mutate({
                                        sku: m.sku,
                                        qty: parseFloat(reorderQty[m.sku] ?? String(m.suggested_reorder_qty || 20)) || 1,
                                      })
                                    }
                                  >
                                    Reorder
                                  </Button>
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    className="h-6 px-2 text-[11px]"
                                    onClick={() => setAddStockItem({ sku: m.sku, name: m.name })}
                                  >
                                    <PlusCircle className="h-3 w-3 mr-1" />
                                    Add
                                  </Button>
                                </div>
                              )
                            )}
                          </div>
                        );
                      })}
                    </div>

                    {familyDetail.top_customers?.length > 0 && (
                      <div className="space-y-1.5">
                        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1">
                          <Users className="h-3 w-3" /> Top Customers for this Vaccine
                        </p>
                        {familyDetail.top_customers.map((c: any) => (
                          <div key={c.customer_code} className="flex justify-between text-xs">
                            <span className="truncate">{c.customer_name}</span>
                            <span className="tabular-nums text-muted-foreground">₦{c.amount.toLocaleString()}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                ) : null}
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {/* Quick Actions: Top Sellers */}
      {Array.isArray(topSellers) && topSellers.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base font-semibold flex items-center gap-2">
              <TrendingUp className="h-4 w-4" /> Top Sellers — All-Time
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
              {topSellers.map((t: any) => (
                <div key={t.sku} className="rounded-md border p-2.5 text-xs space-y-1">
                  <p className="font-semibold truncate">{t.name}</p>
                  <p className="text-muted-foreground">{t.total_qty.toLocaleString()} units lifetime</p>
                  <p className="text-muted-foreground">₦{t.total_revenue.toLocaleString()} revenue</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Add Stock */}
      <DetailSheet
        open={!!addStockItem}
        onOpenChange={(open) => { if (!open) setAddStockItem(null); }}
        title="Add Stock"
        description={addStockItem ? `Record incoming stock for ${addStockItem.name}` : undefined}
        icon={PlusCircle}
        footer={
          <>
            <Button variant="outline" onClick={() => setAddStockItem(null)}>Cancel</Button>
            <Button onClick={handleAddStock} disabled={addStockSubmitting || !entryQty || Number(entryQty) <= 0}>
              {addStockSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Add Stock
            </Button>
          </>
        }
      >
        <div className="space-y-2">
          <Label className="text-xs text-muted-foreground">Item</Label>
          <div className="rounded-md border bg-muted/40 px-3 py-1.5 text-xs">
            <span className="font-mono">{addStockItem?.sku}</span>
            <span className="ml-2 text-muted-foreground">{addStockItem?.name}</span>
          </div>
        </div>
        <div className="space-y-2">
          <Label htmlFor="add-stock-qty" className="text-xs">Quantity <span className="text-destructive">*</span></Label>
          <Input id="add-stock-qty" type="number" min="1" step="1" className="h-8 text-xs"
            placeholder="e.g. 100" value={entryQty} onChange={(e) => setEntryQty(e.target.value)} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="add-stock-ref" className="text-xs">Reference / PO#</Label>
          <Input id="add-stock-ref" className="h-8 text-xs"
            placeholder="Optional — e.g. PO-2024-001" value={entryRef} onChange={(e) => setEntryRef(e.target.value)} />
        </div>
      </DetailSheet>

      {/* Log Adjustment */}
      <DetailSheet
        open={adjustmentOpen}
        onOpenChange={(open) => { setAdjustmentOpen(open); if (!open) setAdjustment({ sku: "", item_name: "", quantity_change: 0, event_type: "ADJUSTMENT", reference: "" }); }}
        title="Log Stock Adjustment"
        description="Record a sale, damage write-off, expiry, or manual adjustment."
        icon={RotateCcw}
        footer={
          <>
            <Button variant="outline" onClick={() => setAdjustmentOpen(false)}>Cancel</Button>
            <Button onClick={handleLogAdjustment} disabled={adjustmentSubmitting}>
              {adjustmentSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Record
            </Button>
          </>
        }
      >
        <div className="space-y-2">
          <Label htmlFor="adj-sku">Item/SKU</Label>
          <EntityAutocomplete<InventorySearchResult>
            fetchFn={(q) => api.inventory.search(q)}
            getKey={(p) => p.sku ?? p.name}
            getLabel={(p) => p.name}
            getSubtitle={(p) => p.sku}
            placeholder="Search inventory..."
            onSelect={(p) => setAdjustment({ ...adjustment, sku: p.sku || p.name, item_name: p.name })}
          />
          {adjustment.sku && (
            <p className="text-xs text-muted-foreground">Selected: {adjustment.item_name || adjustment.sku} ({adjustment.sku})</p>
          )}
        </div>
        <div className="space-y-2">
          <Label htmlFor="adj-type">Type</Label>
          <Select value={adjustment.event_type} onValueChange={(val) => setAdjustment({ ...adjustment, event_type: val })}>
            <SelectTrigger id="adj-type"><SelectValue placeholder="Select type" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="SALE">Sale</SelectItem>
              <SelectItem value="RESTOCK">Restock</SelectItem>
              <SelectItem value="DAMAGE">Damage / Write-off</SelectItem>
              <SelectItem value="EXPIRY">Expiry</SelectItem>
              <SelectItem value="ADJUSTMENT">Adjustment</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="adj-qty">Qty Change</Label>
          <Input id="adj-qty" type="number" value={adjustment.quantity_change}
            onChange={(e) => setAdjustment({ ...adjustment, quantity_change: parseFloat(e.target.value) || 0 })}
            placeholder="+100 or -50" />
        </div>
        <div className="space-y-2">
          <Label htmlFor="adj-ref">Reference</Label>
          <Input id="adj-ref" value={adjustment.reference}
            onChange={(e) => setAdjustment({ ...adjustment, reference: e.target.value })}
            placeholder="Optional — e.g. reason or PO#" />
        </div>
      </DetailSheet>
    </motion.div>
  );
};

export default Inventory;
