/**
 * Operations › Procurement: stock orders and supplier buying from ACE Books,
 * plus the import-shipment clearance tracker when there are shipments to track.
 * The old tab showed an always-empty "reliability scorecard" (no delivery data
 * is recorded) and a debug "Realtime event" line.
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, Clock, Package, TrendingDown } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { api } from "@/lib/api-client";
import { apiUrl } from "@/lib/api-base";
import { authClient } from "@/lib/auth-client";
import { naira, num } from "@/lib/books-api";
import { ProcurementShipment } from "@shared/dashboard-types";
import { Chip, PLAN_STATUS, StockOrderKpis } from "@/components/operations/stock-orders";

function wsUrl(path: string, token: string): string {
  const withToken = `${apiUrl(path)}?token=${encodeURIComponent(token)}`;
  if (withToken.startsWith("http://")) return withToken.replace("http://", "ws://");
  if (withToken.startsWith("https://")) return withToken.replace("https://", "wss://");
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${withToken}`;
}

function statusVariant(status: string): "default" | "secondary" | "outline" | "destructive" {
  if (status === "under_clearance") return "destructive";
  if (status === "released") return "secondary";
  if (status === "delivered_to_warehouse") return "default";
  return "outline";
}

const statusLabel = (status: string) => status.replace(/_/g, " ");

const NEXT_STEP: Record<string, [string, string]> = {
  in_transit: ["at_port", "Mark at port"],
  at_port: ["under_clearance", "Mark under clearance"],
  under_clearance: ["released", "Mark released"],
  released: ["delivered_to_warehouse", "Mark delivered"],
};

export function ProcurementImportDashboard() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [busyShipmentId, setBusyShipmentId] = useState<string | null>(null);
  const [escalateTarget, setEscalateTarget] = useState<ProcurementShipment | null>(null);

  const stockSummary = useQuery({ queryKey: ["stock-orders-summary"], queryFn: () => api.procurement.stockOrdersSummary() });
  const plan = useQuery({ queryKey: ["reorder-plan"], queryFn: () => api.procurement.reorderPlan() });
  const directory = useQuery({ queryKey: ["supplier-directory"], queryFn: () => api.procurement.supplierDirectory() });
  const needs = (plan.data?.items ?? []).filter((i: any) => i.status === "out_of_stock" || i.status === "reorder_now").slice(0, 8);
  const topSuppliers = (directory.data?.suppliers ?? []).filter((x: any) => x.last12 > 0).slice(0, 8);

  const shipmentsQuery = useQuery({
    queryKey: ["procurement-shipments"],
    queryFn: () => api.procurement.shipments({ limit: 100 }),
    refetchInterval: 60000,
  });
  const analysisQuery = useQuery({
    queryKey: ["procurement-analysis"],
    queryFn: () => api.procurement.analyze({}),
    refetchInterval: 90000,
  });
  const shipments = shipmentsQuery.data?.data ?? [];
  const analysis = analysisQuery.data?.data;
  const inClearanceCount = useMemo(() => shipments.filter((item) => item.status === "under_clearance").length, [shipments]);
  const delayedCount = analysis?.delayed_count ?? 0;
  const estimatedImpact = analysis?.estimated_total_impact ?? 0;
  const delayedTop = (analysis?.delayed_shipments ?? []).slice(0, 6);

  // Live shipment updates (best effort; the queries also poll).
  useEffect(() => {
    let socket: WebSocket | null = null;
    let isDisposed = false;
    async function connectSocket() {
      let token = authClient.getAccessToken();
      if (!token) {
        if (!(await authClient.refresh())) return;
        token = authClient.getAccessToken();
      }
      if (!token || isDisposed) return;
      socket = new WebSocket(wsUrl("/procurement/import-agent/ws", token));
      socket.onmessage = () => {
        queryClient.invalidateQueries({ queryKey: ["procurement-shipments"] });
        queryClient.invalidateQueries({ queryKey: ["procurement-analysis"] });
      };
    }
    void connectSocket();
    return () => {
      isDisposed = true;
      socket?.close();
    };
  }, [queryClient]);

  async function transitionShipment(shipment: ProcurementShipment, nextStatus: string) {
    setBusyShipmentId(shipment.id);
    try {
      await api.procurement.transition(shipment.id, { next_status: nextStatus, reason: "dashboard_action" });
      toast.success(`Shipment ${shipment.shipment_ref} moved to ${statusLabel(nextStatus)}.`);
      await queryClient.invalidateQueries({ queryKey: ["procurement-shipments"] });
      await queryClient.invalidateQueries({ queryKey: ["procurement-analysis"] });
    } catch (error) {
      toast.error((error as Error).message || "Failed to transition shipment.");
    } finally {
      setBusyShipmentId(null);
    }
  }

  async function escalateShipment(shipment: ProcurementShipment) {
    setBusyShipmentId(shipment.id);
    try {
      await api.procurement.escalate(shipment.id, {
        reason: "clearance_delay_threshold_exceeded",
        notify_regulatory: true,
        notify_executive_dashboard: true,
      });
      toast.success(`Shipment ${shipment.shipment_ref} escalated.`);
      await queryClient.invalidateQueries({ queryKey: ["procurement-analysis"] });
    } catch (error) {
      toast.error((error as Error).message || "Failed to escalate shipment.");
    } finally {
      setBusyShipmentId(null);
      setEscalateTarget(null);
    }
  }

  return (
    <div className="space-y-6">
      <StockOrderKpis s={stockSummary.data} onPick={(tab, f) => navigate(`/operations/purchase-orders?tab=${tab}${f ? `&filter=${f}` : ""}`)} />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
            <div>
              <CardTitle className="text-base">Needs ordering now</CardTitle>
              <CardDescription>Out of stock or below the reorder point (ACE Books stock and sales).</CardDescription>
            </div>
            <Button size="sm" variant="outline" onClick={() => navigate("/operations/purchase-orders?tab=plan&filter=needs")}>Reorder plan</Button>
          </CardHeader>
          <CardContent className="space-y-1.5">
            {plan.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
            {!plan.isLoading && needs.length === 0 && <p className="text-sm text-muted-foreground">Nothing needs ordering.</p>}
            {needs.map((i: any) => (
              <div key={i.family} className="flex items-center justify-between gap-3 border-b pb-1.5 text-sm last:border-0">
                <div className="min-w-0">
                  <div className="truncate font-medium">{i.name}</div>
                  <div className="truncate text-[11px] text-muted-foreground">
                    {num(i.on_hand)} on hand · sells {num(i.monthly_demand, 1)}/month{i.supplier_name ? ` · ${i.supplier_name}` : ""}
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  <Chip map={PLAN_STATUS} value={i.status} />
                  <div className="text-[11px] text-muted-foreground">order {num(i.suggested_qty)} · {naira(i.est_cost)}</div>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
            <div>
              <CardTitle className="text-base">Top suppliers, last 12 months</CardTitle>
              <CardDescription>Spend, what we owe and price trend (ACE Books).</CardDescription>
            </div>
            <Button size="sm" variant="outline" onClick={() => navigate("/operations/suppliers")}>All suppliers</Button>
          </CardHeader>
          <CardContent className="space-y-1.5">
            {directory.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
            {topSuppliers.map((sp: any) => (
              <div key={sp.id} className="flex items-center justify-between gap-3 border-b pb-1.5 text-sm last:border-0">
                <div className="min-w-0">
                  <div className="truncate font-medium">{sp.name}</div>
                  <div className="truncate text-[11px] text-muted-foreground">
                    {num(sp.items)} items · buys every {sp.avg_gap_days != null ? `${num(sp.avg_gap_days)} days` : "—"}
                    {sp.price_change_pct != null && ` · prices ${sp.price_change_pct > 0 ? "+" : ""}${Number(sp.price_change_pct).toFixed(1)}%`}
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  <div className="font-medium">{naira(sp.last12)}</div>
                  <div className="text-[11px] text-muted-foreground">owe {naira(sp.balance)}</div>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      {shipments.length > 0 && (
        <>
          <KpiStrip
            items={[
              { label: "Import shipments", value: shipments.length, icon: Package },
              { label: "Under clearance", value: inClearanceCount, icon: Clock, tone: inClearanceCount > 0 ? "warning" : "default" },
              { label: "Delayed", value: delayedCount, icon: AlertTriangle, tone: delayedCount > 0 ? "danger" : "default" },
              { label: "Est. delay impact", value: naira(estimatedImpact), icon: TrendingDown },
            ]}
          />
          {delayedTop.length > 0 && (
            <Card>
              <CardHeader><CardTitle className="text-base">Delayed at clearance</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                {delayedTop.map((item) => (
                  <div key={item.shipment_id} className="rounded-md border p-3">
                    <div className="flex items-center justify-between">
                      <p className="font-medium">{item.shipment_ref}</p>
                      <Badge variant="destructive">{item.delay_days} days delayed</Badge>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      {item.supplier_name} · {item.status.replace(/_/g, " ")} · Impact: {item.estimated_impact.toLocaleString()} {item.currency}
                    </p>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
          <Card>
            <CardHeader><CardTitle className="text-base">Import shipments</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {shipments.map((shipment) => {
                const next = NEXT_STEP[shipment.status];
                const busy = busyShipmentId === shipment.id;
                return (
                  <div key={shipment.id} className="rounded-md border p-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="font-medium">{shipment.shipment_ref}</p>
                        <p className="text-xs text-muted-foreground">{shipment.supplier_name} · {shipment.expected_arrival_date || "No ETA"}</p>
                      </div>
                      <Badge variant={statusVariant(shipment.status)}>{statusLabel(shipment.status)}</Badge>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {next && <Button size="sm" onClick={() => transitionShipment(shipment, next[0])} disabled={busy}>{next[1]}</Button>}
                      {shipment.status === "under_clearance" && (
                        <Button size="sm" variant="destructive" onClick={() => setEscalateTarget(shipment)} disabled={busy}>Escalate</Button>
                      )}
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>
        </>
      )}

      <Dialog open={!!escalateTarget} onOpenChange={(open) => { if (!open) setEscalateTarget(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Escalate Shipment?</DialogTitle>
            <DialogDescription>
              This notifies regulatory and the executive dashboard for <span className="font-medium">{escalateTarget?.shipment_ref}</span>. This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEscalateTarget(null)}>Cancel</Button>
            <Button variant="destructive" onClick={() => escalateTarget && escalateShipment(escalateTarget)} disabled={!!busyShipmentId}>Escalate</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
