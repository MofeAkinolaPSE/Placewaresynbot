import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { api } from "@/lib/api-client";
import { apiUrl } from "@/lib/api-base";
import { authClient } from "@/lib/auth-client";
import { ProcurementShipment } from "@shared/dashboard-types";

const chartConfig = {
  reliability_score: {
    label: "Reliability Score",
    color: "hsl(var(--primary))",
  },
} satisfies ChartConfig;

function wsUrl(path: string, token: string): string {
  const endpoint = apiUrl(path);
  const withToken = `${endpoint}?token=${encodeURIComponent(token)}`;

  if (withToken.startsWith("http://")) {
    return withToken.replace("http://", "ws://");
  }
  if (withToken.startsWith("https://")) {
    return withToken.replace("https://", "wss://");
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${withToken}`;
}

function statusVariant(status: string): "default" | "secondary" | "outline" | "destructive" {
  if (status === "under_clearance") return "destructive";
  if (status === "released") return "secondary";
  if (status === "delivered_to_warehouse") return "default";
  return "outline";
}

function statusLabel(status: string): string {
  return status.replace(/_/g, " ");
}

export function ProcurementImportDashboard() {
  const queryClient = useQueryClient();
  const [lastRealtimeEvent, setLastRealtimeEvent] = useState<string>("none");
  const [busyShipmentId, setBusyShipmentId] = useState<string | null>(null);

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

  const inClearanceCount = useMemo(
    () => shipments.filter((item) => item.status === "under_clearance").length,
    [shipments],
  );

  const delayedCount = analysis?.delayed_count ?? 0;
  const estimatedImpact = analysis?.estimated_total_impact ?? 0;

  const scorecardTop = (analysis?.supplier_scorecard ?? []).slice(0, 6);
  const delayedTop = (analysis?.delayed_shipments ?? []).slice(0, 6);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let isDisposed = false;

    async function connectSocket() {
      let token = authClient.getAccessToken();
      if (!token) {
        const refreshed = await authClient.refresh();
        if (!refreshed) {
          return;
        }
        token = authClient.getAccessToken();
      }

      if (!token || isDisposed) {
        return;
      }

      socket = new WebSocket(wsUrl("/procurement/import-agent/ws", token));

      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          const eventName = String(payload?.event || "unknown");
          setLastRealtimeEvent(eventName);
          queryClient.invalidateQueries({ queryKey: ["procurement-shipments"] });
          queryClient.invalidateQueries({ queryKey: ["procurement-analysis"] });
        } catch {
          setLastRealtimeEvent("unknown");
        }
      };

      socket.onerror = () => {
        setLastRealtimeEvent("socket_error");
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
      await api.procurement.transition(shipment.id, {
        next_status: nextStatus,
        reason: "dashboard_action",
      });
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
    }
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Tracked Shipments</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{shipments.length}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Under Clearance</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{inClearanceCount}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Delayed Shipments</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{delayedCount}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Estimated Delay Impact</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{estimatedImpact.toLocaleString()}</div>
            <p className="text-xs text-muted-foreground">Realtime event: {lastRealtimeEvent}</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Supplier Reliability Scorecard</CardTitle>
            <CardDescription>Top suppliers by reliability score for procurement/import workflow.</CardDescription>
          </CardHeader>
          <CardContent>
            {scorecardTop.length > 0 ? (
              <ChartContainer config={chartConfig} className="h-[260px] w-full">
                <BarChart data={scorecardTop}>
                  <CartesianGrid vertical={false} />
                  <XAxis dataKey="supplier" tickLine={false} axisLine={false} />
                  <YAxis />
                  <ChartTooltip content={<ChartTooltipContent />} />
                  <Bar dataKey="reliability_score" fill="var(--color-reliability_score)" radius={6} />
                </BarChart>
              </ChartContainer>
            ) : (
              <p className="text-sm text-muted-foreground">No scorecard data yet.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Delay Risk Watchlist</CardTitle>
            <CardDescription>Shipments above clearance threshold with estimated financial impact.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {delayedTop.length === 0 && <p className="text-sm text-muted-foreground">No delayed shipments above threshold.</p>}
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
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Shipment Lifecycle Control</CardTitle>
          <CardDescription>Controlled workflow transitions and explicit escalation actions.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {(shipmentsQuery.isLoading || analysisQuery.isLoading) && (
            <p className="text-sm text-muted-foreground">Loading procurement/import intelligence...</p>
          )}
          {shipments.map((shipment) => (
            <div key={shipment.id} className="rounded-md border p-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="font-medium">{shipment.shipment_ref}</p>
                  <p className="text-xs text-muted-foreground">
                    {shipment.supplier_name} · {shipment.expected_arrival_date || "No ETA"}
                  </p>
                </div>
                <Badge variant={statusVariant(shipment.status)}>{statusLabel(shipment.status)}</Badge>
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                {shipment.status === "in_transit" && (
                  <Button
                    size="sm"
                    onClick={() => transitionShipment(shipment, "at_port")}
                    disabled={busyShipmentId === shipment.id}
                  >
                    Mark At Port
                  </Button>
                )}
                {shipment.status === "at_port" && (
                  <Button
                    size="sm"
                    onClick={() => transitionShipment(shipment, "under_clearance")}
                    disabled={busyShipmentId === shipment.id}
                  >
                    Mark Under Clearance
                  </Button>
                )}
                {shipment.status === "under_clearance" && (
                  <>
                    <Button
                      size="sm"
                      onClick={() => transitionShipment(shipment, "released")}
                      disabled={busyShipmentId === shipment.id}
                    >
                      Mark Released
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => escalateShipment(shipment)}
                      disabled={busyShipmentId === shipment.id}
                    >
                      Escalate
                    </Button>
                  </>
                )}
                {shipment.status === "released" && (
                  <Button
                    size="sm"
                    onClick={() => transitionShipment(shipment, "delivered_to_warehouse")}
                    disabled={busyShipmentId === shipment.id}
                  >
                    Mark Delivered
                  </Button>
                )}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
