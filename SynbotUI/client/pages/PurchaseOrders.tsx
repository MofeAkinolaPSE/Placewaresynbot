import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";
import { ShoppingCart } from "lucide-react";
import { PageHeader } from "@/components/workspace/PageHeader";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { FilterBar } from "@/components/workspace/FilterBar";
import { useAuth } from "@/components/AuthProvider";
import { useToast } from "@/hooks/use-toast";

const STATUS_COLOR: Record<string, string> = {
  open: "bg-blue-100 text-blue-700",
  pending: "bg-yellow-100 text-yellow-700",
  approved: "bg-green-100 text-green-700",
  received: "bg-emerald-100 text-emerald-700",
  closed: "bg-muted text-muted-foreground",
  cancelled: "bg-destructive/15 text-destructive",
};

const STALE_OPEN_DAYS = 180; // must match purchase_orders.py's _STALE_OPEN_DAYS

// Matches the backend's own open/overdue definitions (purchase_orders.py
// `_is_open`/`_is_overdue`) — pending/approved always count, "open" is
// disambiguated by a stale-date cutoff since historical bulk imports
// defaulted every blank status to "open" — so the row-level badges can
// never disagree with the KPI cards sourced from that same logic.
function isPoOpen(o: any): boolean {
  if (o.status === "pending" || o.status === "approved") return true;
  if (o.status !== "open") return false;
  const eff = o.expected_delivery_date || o.order_date;
  if (!eff) return false; // no dates at all — backend treats as stale too
  const effDate = new Date(String(eff).slice(0, 10));
  const daysSince = (Date.now() - effDate.getTime()) / 86400000;
  return daysSince <= STALE_OPEN_DAYS;
}

function isPoOverdue(o: any): boolean {
  if (!isPoOpen(o)) return false;
  const due = o.expected_delivery_date;
  if (!due) return false;
  const dueDate = new Date(String(due).slice(0, 10));
  const today = new Date(new Date().toDateString());
  return dueDate < today;
}

const PurchaseOrders = () => {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [closeTarget, setCloseTarget] = useState<{ po: any; action: "closed" | "cancelled" } | null>(null);
  const [closeReason, setCloseReason] = useState("");

  const { roles } = useAuth();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const canManagePos = roles.includes("admin") || roles.includes("ops") || roles.includes("finance") || roles.includes("procurement");

  const { data: ordersRaw, isLoading } = useQuery({
    queryKey: ["purchase-orders"],
    queryFn: () => api.procurement.purchaseOrders({ limit: 200 }),
  });

  const { data: summary } = useQuery({
    queryKey: ["purchase-orders-summary"],
    queryFn: () => api.procurement.purchaseOrdersSummary(),
  });

  const statusMutation = useMutation({
    mutationFn: (vars: { poId: string; status: "closed" | "cancelled"; reason?: string }) =>
      api.procurement.updatePoStatus(vars.poId, { status: vars.status, reason: vars.reason }),
    onSuccess: (_data, vars) => {
      toast({ title: vars.status === "closed" ? "Purchase order closed" : "Purchase order cancelled" });
      queryClient.invalidateQueries({ queryKey: ["purchase-orders"] });
      queryClient.invalidateQueries({ queryKey: ["purchase-orders-summary"] });
      setCloseTarget(null);
      setCloseReason("");
    },
    onError: (err: any) => {
      toast({ title: "Action failed", description: err.message, variant: "destructive" });
    },
  });

  const orders: any[] = Array.isArray(ordersRaw) ? ordersRaw : [];

  const filtered = orders.filter((o) => {
    if (statusFilter !== "all" && o.status !== statusFilter) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        String(o.po_number ?? "").toLowerCase().includes(q) ||
        String(o.vendor_name ?? o.vendor_id ?? "").toLowerCase().includes(q)
      );
    }
    return true;
  });

  const statuses = ["all", ...Array.from(new Set(orders.map((o) => o.status).filter(Boolean)))];

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionTransitions.standard}
      className="flex flex-col gap-5"
    >
      <PageHeader
        icon={ShoppingCart}
        title="Purchase Orders"
        subtitle="Sage 50 procurement pipeline"
      />

      {/* Summary KPIs */}
      {summary && (
        <KpiStrip
          items={[
            { label: "Total POs", value: summary.total_pos ?? "—" },
            { label: "Open POs", value: summary.open_pos ?? "—" },
            { label: "Overdue POs", value: summary.overdue_pos ?? "—", tone: (summary.overdue_pos ?? 0) > 0 ? "danger" : "default" },
            { label: "Total Value", value: summary.total_value != null ? `₦${Number(summary.total_value).toLocaleString()}` : "—" },
            { label: "Open Value", value: summary.open_value != null ? `₦${Number(summary.open_value).toLocaleString()}` : "—" },
            { label: "Overdue Value", value: summary.overdue_value != null ? `₦${Number(summary.overdue_value).toLocaleString()}` : "—", tone: (summary.overdue_value ?? 0) > 0 ? "danger" : "default" },
          ]}
        />
      )}

      {/* Filters — status stays a pill-button row (never had a sentinel-Select
          to begin with, so converting it to FilterBar's Select would be new
          UX rather than a mechanical swap). Search moved into FilterBar. */}
      <div className="space-y-2">
        <FilterBar search={{ value: search, onChange: setSearch, placeholder: "Search PO number or vendor…" }} />
        <div className="flex gap-1 flex-wrap">
          {statuses.map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`px-3 py-1 rounded text-xs font-medium border transition-colors ${
                statusFilter === s
                  ? "bg-primary text-primary-foreground border-primary"
                  : "bg-muted text-muted-foreground border-transparent hover:border-muted-foreground/30"
              }`}
            >
              {s === "all" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <Card>
        <CardHeader className="mb-2">
          <CardTitle className="text-lg font-semibold flex items-center gap-2">
            <ShoppingCart className="h-5 w-5" />
            Purchase Orders
          </CardTitle>
          <CardDescription>{filtered.length} records</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="min-w-[120px]">PO Number</TableHead>
                  <TableHead className="min-w-[180px]">Vendor</TableHead>
                  <TableHead className="min-w-[110px]">Order Date</TableHead>
                  <TableHead className="min-w-[130px]">Due / Expected</TableHead>
                  <TableHead className="min-w-[120px] text-right">Net Amount</TableHead>
                  <TableHead className="min-w-[100px]">Status</TableHead>
                  {canManagePos && <TableHead className="min-w-[140px]">Actions</TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading ? (
                  <TableRow>
                    <TableCell colSpan={canManagePos ? 7 : 6} className="text-center text-muted-foreground py-8">
                      Loading…
                    </TableCell>
                  </TableRow>
                ) : filtered.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={canManagePos ? 7 : 6} className="text-center text-muted-foreground py-8">
                      {orders.length === 0 ? "No purchase orders found. Import Sage data to populate." : "No orders match your filter."}
                    </TableCell>
                  </TableRow>
                ) : (
                  filtered.map((o, i) => {
                    const dueRaw = o.expected_delivery_date;
                    const isOverdue = isPoOverdue(o);
                    return (
                    <TableRow key={o.po_id ?? i}>
                      <TableCell className="font-mono text-xs">{o.po_number || "—"}</TableCell>
                      <TableCell className="text-sm">{o.vendor_name || o.vendor_id || "—"}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {o.order_date ? new Date(o.order_date).toLocaleDateString() : "—"}
                      </TableCell>
                      <TableCell className={`text-xs ${isOverdue ? "text-destructive font-semibold" : "text-muted-foreground"}`}>
                        {dueRaw ? new Date(dueRaw).toLocaleDateString() : "—"}
                      </TableCell>
                      <TableCell className="text-right font-mono text-sm">
                        {o.net_amount != null ? `₦${Number(o.net_amount).toLocaleString()}` : "—"}
                      </TableCell>
                      <TableCell>
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          isOverdue
                            ? "bg-destructive/15 text-destructive"
                            : STATUS_COLOR[o.status] ?? "bg-muted text-muted-foreground"
                        }`}>
                          {isOverdue ? "overdue" : (o.status || "—")}
                        </span>
                      </TableCell>
                      {canManagePos && (
                        <TableCell>
                          {isPoOpen(o) ? (
                            <div className="flex gap-1.5">
                              <Button
                                variant="outline"
                                size="sm"
                                className="h-7 px-2 text-xs"
                                onClick={() => setCloseTarget({ po: o, action: "closed" })}
                              >
                                Close
                              </Button>
                              <Button
                                variant="outline"
                                size="sm"
                                className="h-7 px-2 text-xs text-destructive hover:text-destructive"
                                onClick={() => setCloseTarget({ po: o, action: "cancelled" })}
                              >
                                Cancel
                              </Button>
                            </div>
                          ) : (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </TableCell>
                      )}
                    </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Close/Cancel confirmation — same short single-target Dialog
          convention as FinanceBudget.tsx's budget-target delete. */}
      <Dialog open={!!closeTarget} onOpenChange={(open) => { if (!open) { setCloseTarget(null); setCloseReason(""); } }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{closeTarget?.action === "cancelled" ? "Cancel" : "Close"} Purchase Order</DialogTitle>
            <DialogDescription>
              {closeTarget && (
                <>
                  {closeTarget.action === "cancelled" ? "Cancel" : "Close"} PO{" "}
                  <strong>{closeTarget.po.po_number || closeTarget.po.po_id}</strong>
                  {closeTarget.po.vendor_name ? <> from <strong>{closeTarget.po.vendor_name}</strong></> : null}?
                  It will no longer count toward open/overdue totals.
                </>
              )}
            </DialogDescription>
          </DialogHeader>
          <textarea
            value={closeReason}
            onChange={(e) => setCloseReason(e.target.value)}
            placeholder="Reason (optional)"
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm min-h-[70px]"
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setCloseTarget(null)}>
              Back
            </Button>
            <Button
              variant={closeTarget?.action === "cancelled" ? "destructive" : "default"}
              disabled={statusMutation.isPending}
              onClick={() =>
                closeTarget &&
                statusMutation.mutate({
                  poId: closeTarget.po.po_id,
                  status: closeTarget.action,
                  reason: closeReason || undefined,
                })
              }
            >
              {closeTarget?.action === "cancelled" ? "Cancel PO" : "Close PO"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </motion.div>
  );
};

export default PurchaseOrders;
