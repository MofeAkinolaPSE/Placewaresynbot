import { useMemo, useState } from "react";
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
import { InventoryAnalytics } from "@/components/workspace/InventoryAnalytics";
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
  CalendarClock,
} from "lucide-react";

type WorkspaceCard = {
  family: string;
  company_id: string | null;
  category: string | null;
  sku_count: number;
  total_stock: number;
  sellable_stock: number;
  expired_stock: number;
  expired_valuation: number;
  sellable_sku_count: number;
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

// Attention-first ordering within the in-stock group.
const STATUS_ORDER = ["critical", "warning", "adequate", "out_of_stock"];

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

  const { data: analytics } = useQuery({
    queryKey: ["inventory-analytics", companyFilter],
    queryFn: () => api.inventory.analytics(companyFilter || undefined),
    staleTime: 60_000,
  });

  // The reorder queue. Until this existed, a raised request had nowhere to
  // appear and no way to be advanced.
  const { data: reorderRequests } = useQuery({
    queryKey: ["replenishment-requests"],
    queryFn: () => api.replenishment.list({ limit: 200 }),
    staleTime: 30_000,
  });

  const [busyRequestId, setBusyRequestId] = useState<string | null>(null);
  const advanceRequest = useMutation({
    mutationFn: async (vars: { row: any; action: "approve" | "receive" }) =>
      vars.action === "approve"
        ? api.replenishment.approve(vars.row.id)
        : api.replenishment.received(vars.row.id, Number(vars.row.requested_qty) || undefined),
    onMutate: (vars) => setBusyRequestId(vars.row.id),
    onSettled: () => setBusyRequestId(null),
    onSuccess: (res: any, vars) => {
      if (vars.action === "approve") {
        toast({ title: "Reorder approved", description: `${vars.row.sku} — awaiting delivery` });
      } else if (res?.already_received) {
        toast({ title: "Already received", description: "Stock was not added again." });
      } else {
        toast({
          title: "Received into stock",
          description: `${Number(res?.stock_added ?? 0).toLocaleString()} units of ${vars.row.sku} added.`,
        });
      }
      queryClient.invalidateQueries({ queryKey: ["replenishment-requests"] });
      invalidateAll();
      queryClient.invalidateQueries({ queryKey: ["inventory-analytics"] });
    },
    onError: (err: any) =>
      toast({
        title: "Could not update reorder",
        description:
          err?.status === 403
            ? "Requires ops, finance, management or admin role."
            : err?.message,
        variant: "destructive",
      }),
  });

  const cancelRequest = useMutation({
    mutationFn: (row: any) => api.replenishment.cancel(row.id),
    onMutate: (row: any) => setBusyRequestId(row.id),
    onSettled: () => setBusyRequestId(null),
    onSuccess: (_res: any, row: any) => {
      toast({ title: "Reorder cancelled", description: `${row.sku} — kept in history as cancelled` });
      queryClient.invalidateQueries({ queryKey: ["replenishment-requests"] });
    },
    onError: (err: any) =>
      toast({
        title: "Could not cancel reorder",
        description:
          err?.status === 409
            ? "This request was already received, so it can't be cancelled."
            : err?.status === 403
              ? "Requires ops, finance, management or admin role."
              : err?.message,
        variant: "destructive",
      }),
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

  // Families that actually have stock come first. The backend returns them in
  // catalogue order, which pushed empty/expired families above vaccines that
  // are physically on the shelf.
  const cardList: WorkspaceCard[] = useMemo(() => {
    const list: WorkspaceCard[] = Array.isArray(cards) ? cards : [];
    return [...list].sort((a, b) => {
      const aHas = (a.total_stock ?? 0) > 0 ? 0 : 1;
      const bHas = (b.total_stock ?? 0) > 0 ? 0 : 1;
      if (aHas !== bHas) return aHas - bHas;
      // Within in-stock, surface what needs attention soonest.
      const rank = (s: string) => STATUS_ORDER.indexOf(s);
      const r = rank(a.status) - rank(b.status);
      if (r !== 0) return r;
      return (b.total_stock ?? 0) - (a.total_stock ?? 0);
    });
  }, [cards]);
  const summary = kpiData?.summary;

  // Batches split: what we can actually sell vs. what's expired or empty.
  // Previously every batch rendered in backend order, so a family like
  // ROTARIX led with four zero-quantity batches that expired in 2020-2022
  // and buried the stock that's actually on hand.
  const [showDormantBatches, setShowDormantBatches] = useState(false);
  const { activeBatches, dormantBatches } = useMemo(() => {
    const members: any[] = (familyDetail as any)?.members ?? [];
    const today = new Date().setHours(0, 0, 0, 0);
    const isDormant = (m: any) =>
      Number(m.current_stock ?? 0) <= 0 ||
      (m.expiry_date && new Date(m.expiry_date).getTime() < today);
    // FEFO: soonest expiry first, so the batch to sell next is at the top.
    const byExpiry = (a: any, b: any) => {
      const ax = a.expiry_date ? new Date(a.expiry_date).getTime() : Infinity;
      const bx = b.expiry_date ? new Date(b.expiry_date).getTime() : Infinity;
      return ax - bx;
    };
    return {
      activeBatches: members.filter((m) => !isDormant(m)).sort(byExpiry),
      dormantBatches: members.filter(isDormant).sort(byExpiry),
    };
  }, [familyDetail]);

  const reorderMutation = useMutation({
    mutationFn: (vars: { sku: string; qty: number }) =>
      api.replenishment.create({ sku: vars.sku, requested_qty: vars.qty }),
    onSuccess: (_data, vars) => {
      toast({
        title: "Reorder requested",
        description: `${vars.qty} units of ${vars.sku} — see "Reorders in flight"`,
      });
      queryClient.invalidateQueries({ queryKey: ["inventory-family-detail"] });
      queryClient.invalidateQueries({ queryKey: ["replenishment-requests"] });
    },
    onError: (err: any) => toast({ title: "Reorder request failed", description: err.message, variant: "destructive" }),
  });

  // Write-off from the Position & Risk panel. Recorded as an append-only
  // EXPIRY event rather than a deletion: current_stock drops to zero so the
  // batch leaves the live list, while the units and the reason stay on the
  // record permanently.
  const [busySku, setBusySku] = useState<string | null>(null);
  const writeOffMutation = useMutation({
    mutationFn: (row: any) =>
      api.inventory.addStock({
        sku: row.sku,
        quantity_change: -Math.abs(Number(row.units ?? row.current_stock ?? 0)),
        event_type: (row.days_to_expiry ?? 0) < 0 ? "EXPIRY" : "DAMAGE",
        reference: `Written off from inventory dashboard${
          (row.days_to_expiry ?? 0) < 0 ? ` (expired ${Math.abs(row.days_to_expiry)}d)` : ""
        }`,
      }),
    onMutate: (row: any) => setBusySku(row.sku),
    onSettled: () => setBusySku(null),
    onSuccess: (_d, row: any) => {
      toast({
        title: "Stock written off",
        description: `${Number(row.units ?? 0).toLocaleString()} units of ${row.sku} removed from live stock and recorded.`,
      });
      invalidateAll();
      queryClient.invalidateQueries({ queryKey: ["inventory-analytics"] });
    },
    onError: (err: any) =>
      toast({ title: "Write-off failed", description: err?.message, variant: "destructive" }),
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

  const renderBatchCard = (m: any) => {
    const pendingReq = ((familyDetail as any)?.open_replenishment_requests || []).find((r: any) => r.sku === m.sku);
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
          {
            // The number that actually costs money: stock already expired or
            // expiring within 90 days, valued at cost.
            label: "Value at Expiry Risk",
            value: analytics
              ? `₦${Math.round(
                  (analytics.expiry?.buckets?.expired?.value ?? 0) +
                    (analytics.expiry?.buckets?.within_30_days?.value ?? 0) +
                    (analytics.expiry?.buckets?.within_90_days?.value ?? 0),
                ).toLocaleString()}`
              : "—",
            icon: CalendarClock,
            tone:
              (analytics?.expiry?.buckets?.expired?.value ?? 0) > 0 ? "danger" : "warning",
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

      <InventoryAnalytics
        data={analytics}
        busySku={busySku}
        onSelect={(family, companyId) => {
          setSelectedFamily({ family, company_id: companyId });
          setShowDormantBatches(false);
        }}
        onReorder={(row) =>
          reorderMutation.mutate({
            sku: row.sku,
            // Prefer the demand-derived quantity; fall back to the canonical
            // top-up heuristic when there's no rate to project from.
            qty: Math.max(1, Math.round(Number(row.recommended_reorder_qty ?? 0) || 20)),
          })
        }
        onWriteOff={(row) => writeOffMutation.mutate(row)}
        requests={Array.isArray(reorderRequests) ? reorderRequests : []}
        busyRequestId={busyRequestId}
        onAdvanceRequest={(row, action) => advanceRequest.mutate({ row, action })}
        onCancelRequest={(row) => cancelRequest.mutate(row)}
      />

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
                          {/* Reconciles with the detail panel's "In Stock (N)",
                              which also excludes expired batches. */}
                          {c.expired_stock > 0
                            ? `${c.sellable_sku_count} of ${c.sku_count} batches sellable`
                            : `${c.sku_count} batch${c.sku_count === 1 ? "" : "es"}`}{" "}
                          · {c.category || "—"}
                        </p>
                      </div>
                      <Badge variant={STATUS_BADGE[c.status] ?? "outline"}>{c.status}</Badge>
                    </div>
                    <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                      {/* Sellable leads, because expired units sit on the shelf
                          but cannot be sold -- showing only the raw total made
                          the grid overstate sellable stock by ~18%. */}
                      <span className="text-muted-foreground">Sellable Stock</span>
                      <span className="font-semibold tabular-nums">
                        {(c.sellable_stock ?? c.total_stock).toLocaleString()}
                      </span>
                      {c.expired_stock > 0 && (
                        <>
                          <span className="text-destructive">Expired</span>
                          <span className="tabular-nums text-destructive font-medium">
                            {c.expired_stock.toLocaleString()} units · ₦{c.expired_valuation.toLocaleString()}
                          </span>
                        </>
                      )}
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
                      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                        In Stock{activeBatches.length > 0 && ` (${activeBatches.length})`}
                      </p>
                      {activeBatches.length === 0 && (
                        <p className="text-xs text-muted-foreground rounded-md border border-dashed p-2.5">
                          No batches of this vaccine are currently in stock.
                        </p>
                      )}
                      {activeBatches.map(renderBatchCard)}

                      {dormantBatches.length > 0 && (
                        <>
                          <button
                            type="button"
                            onClick={() => setShowDormantBatches((v) => !v)}
                            className="w-full text-left text-xs text-muted-foreground hover:text-foreground rounded-md border border-dashed px-2.5 py-2 transition-colors"
                          >
                            {showDormantBatches ? "Hide" : "Show"} {dormantBatches.length} expired / empty batch
                            {dormantBatches.length === 1 ? "" : "es"}
                          </button>
                          {showDormantBatches && (
                            <div className="space-y-2 opacity-70">
                              {dormantBatches.map(renderBatchCard)}
                            </div>
                          )}
                        </>
                      )}
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
