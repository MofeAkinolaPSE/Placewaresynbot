import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Truck,
  User,
  Plus,
  RefreshCw,
  Loader2,
  MapPin,
  CheckCircle2,
  Clock,
  AlertCircle,
  Route,
  Map as MapIcon,
  Navigation,
  Copy,
  Signal,
  Play,
} from "lucide-react";
import { MapContainer, TileLayer, Marker, Popup } from "react-leaflet";
import L from "leaflet";
import { authClient } from "@/lib/auth-client";
import { apiUrl } from "@/lib/api-base";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api-client";
import { motion } from "framer-motion";
import { motionVariants } from "@/lib/motion";
import { PageHeader } from "@/components/workspace/PageHeader";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { DetailSheet } from "@/components/workspace/DetailSheet";

// ---------------------------------------------------------------------------
// Leaflet default icon fix (webpack/vite asset bundling quirk)
// ---------------------------------------------------------------------------
// eslint-disable-next-line @typescript-eslint/no-explicit-any
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl:       'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl:     'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Rider {
  id: string;
  name: string;
  phone?: string;
  vehicle?: string;
  active?: boolean;
  last_lat?: number;
  last_lng?: number;
  last_seen_at?: string;
  created_at?: string;
}

interface LiveRider {
  id: string;
  name: string;
  vehicle?: string;
  last_lat: number;
  last_lng: number;
  last_seen_at?: string;
}

interface DeliveryAddress {
  destination?: string;
  recipient_name?: string;
  recipient_phone?: string;
  customer_name?: string;
  company_name?: string;
  contact_phone?: string;
  items_summary?: string;
  [key: string]: any;
}

// Matches the real DB row (backend/src/schemas/logistics.py's Delivery model
// + migration 084/099 columns) — the previous flat destination/recipient_name/
// recipient_phone fields here didn't exist on the actual schema at all.
interface Delivery {
  id: string;
  reference?: string;
  customer_id?: string;
  address?: DeliveryAddress;
  quantity?: number;
  status: "unassigned" | "assigned" | "in_transit" | "delivered" | "failed";
  assigned_rider?: string;
  rider?: { id: string; name: string; phone?: string; vehicle?: string } | null;
  source?: string;
  source_ref_id?: string;
  tracking_token?: string;
  dest_lat?: number;
  dest_lng?: number;
  eta_text?: string;
  last_ping_at?: string;
  picked_up_at?: string;
  delivered_at?: string;
  created_at?: string;
}

interface Ping {
  id: string;
  lat: number;
  lng: number;
  speed_kmh?: number;
  accuracy_m?: number;
  battery_pct?: number;
  ts: string;
}

// address shape varies by source: LogisticsMonitor's own create form uses
// destination/recipient_name/recipient_phone; Frontdesk's delivery handoff
// (backend/src/routers/frontdesk.py send_for_delivery) uses customer_name/
// company_name/contact_phone/items_summary — both read here so either source
// displays correctly.
function deliveryLabel(d: Delivery): string {
  const a = d.address || {};
  return a.destination || a.company_name || a.customer_name || d.reference || `Delivery ${d.id.slice(0, 8)}`;
}
function deliveryRecipient(d: Delivery): string | undefined {
  const a = d.address || {};
  return a.recipient_name || a.customer_name || a.company_name;
}
function deliveryPhone(d: Delivery): string | undefined {
  const a = d.address || {};
  return a.recipient_phone || a.contact_phone;
}
function trackingUrlFor(d: Delivery, sessionLinks: Record<string, string>): string | undefined {
  if (sessionLinks[d.id]) return sessionLinks[d.id];
  if (d.tracking_token && typeof window !== "undefined") {
    return `${window.location.origin}/rider-track/${d.tracking_token}`;
  }
  return undefined;
}

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

const STATUS_COLORS: Record<string, string> = {
  unassigned: "bg-slate-100 text-slate-700 border-slate-300",
  assigned:   "bg-blue-100 text-blue-700 border-blue-300",
  in_transit: "bg-yellow-100 text-yellow-700 border-yellow-300",
  delivered:  "bg-green-100 text-green-700 border-green-300",
  failed:     "bg-red-100 text-red-700 border-red-300",
};

const STATUS_ICONS: Record<string, React.ReactNode> = {
  unassigned: <AlertCircle className="h-3.5 w-3.5" />,
  assigned:   <User className="h-3.5 w-3.5" />,
  in_transit: <Truck className="h-3.5 w-3.5" />,
  delivered:  <CheckCircle2 className="h-3.5 w-3.5" />,
  failed:     <AlertCircle className="h-3.5 w-3.5" />,
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-xs font-medium ${STATUS_COLORS[status] ?? "bg-muted text-muted-foreground"}`}>
      {STATUS_ICONS[status]}
      {status.replace(/_/g, " ")}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Local state — riders + deliveries managed client-side after API calls
// ---------------------------------------------------------------------------

export default function LogisticsMonitor() {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  // Real list queries — previously these were plain useState([]) arrays,
  // populated only by this browser session's own create-mutation responses,
  // so both tabs started empty on every page load regardless of real data
  // (including everything Frontdesk's send-for-delivery handoff writes
  // directly into `deliveries`). Backed by the new GET /logistics/deliveries
  // and GET /logistics/riders endpoints.
  const { data: deliveriesData, isLoading: deliveriesLoading, refetch: refetchDeliveries } = useQuery({
    queryKey: ["logistics-deliveries"],
    queryFn: () => api.logistics.listDeliveries({ limit: 200 }),
  });
  const deliveries: Delivery[] = deliveriesData?.deliveries ?? [];

  const { data: ridersData, isLoading: ridersLoading, refetch: refetchRiders } = useQuery({
    queryKey: ["logistics-riders"],
    queryFn: () => api.logistics.listRiders(),
  });
  const riders: Rider[] = ridersData?.riders ?? [];

  // Selected delivery — Detail Workspace (Ch.5.1, no dismiss button).
  const [selectedDeliveryId, setSelectedDeliveryId] = useState<string | null>(null);
  const selectedDelivery = useMemo(
    () => deliveries.find((d) => d.id === selectedDeliveryId) ?? null,
    [deliveries, selectedDeliveryId],
  );

  const { data: pingsData, isLoading: pingsLoading } = useQuery({
    queryKey: ["logistics-delivery-pings", selectedDeliveryId],
    queryFn: () => api.logistics.deliveryPings(selectedDeliveryId!),
    enabled: !!selectedDeliveryId,
  });
  const pings: Ping[] = pingsData?.pings ?? [];

  // Create Rider dialog
  const [riderOpen, setRiderOpen] = useState(false);
  const [riderName, setRiderName] = useState("");
  const [riderPhone, setRiderPhone] = useState("");
  const [riderVehicle, setRiderVehicle] = useState("motorcycle");
  // Shown once, right after creation -- access_code is the rider's
  // persistent sign-in credential (ACE Riders, /rider), staff need to
  // actually relay it to them, so the sheet stays open on a success view
  // instead of closing immediately like every other create-flow in this app.
  const [newRiderCode, setNewRiderCode] = useState<string | null>(null);
  const [codeCopied, setCodeCopied] = useState(false);

  // Create Delivery dialog
  const [deliveryOpen, setDeliveryOpen] = useState(false);
  const [deliveryDest, setDeliveryDest] = useState("");
  const [newDeliveryRecipient, setNewDeliveryRecipient] = useState("");
  const [newDeliveryPhone, setNewDeliveryPhone] = useState("");

  // Update status
  const [statusTarget, setStatusTarget] = useState<Delivery | null>(null);
  const [newStatus, setNewStatus] = useState<string>("in_transit");

  // Manual rider assignment (unassigned deliveries) — resets on selection change.
  const [assignRiderId, setAssignRiderId] = useState<string>("");
  // Destination pin, captured at assign time. Frontdesk-originated deliveries
  // arrive with no coordinates, so without this the geofence auto-delivery
  // detection can never trigger for them.
  const [assignDestLat, setAssignDestLat] = useState<string>("");
  const [assignDestLng, setAssignDestLng] = useState<string>("");
  useEffect(() => { setAssignRiderId(""); }, [selectedDeliveryId]);

  // Route viewer
  const [routeRiderId, setRouteRiderId] = useState<string | null>(null);

  // Live map
  const [liveRiders, setLiveRiders] = useState<LiveRider[]>([]);
  const [trackingLinks, setTrackingLinks] = useState<Record<string, string>>({});
  const [sseStatus, setSseStatus] = useState<"connecting" | "live" | "polling" | "off">("off");
  const sseAbortRef = useRef<AbortController | null>(null);

  // ---------------------------------------------------------------------------
  // Mutations
  // ---------------------------------------------------------------------------

  const createRider = useMutation({
    mutationFn: () =>
      api.logistics.createRider({
        name: riderName.trim(),
        phone: riderPhone.trim() || undefined,
        vehicle: riderVehicle,
      }),
    onSuccess: (data: any) => {
      toast({ title: "Rider registered", description: data?.rider?.name });
      setNewRiderCode(data?.rider?.access_code || null);
      setRiderName("");
      setRiderPhone("");
      void queryClient.invalidateQueries({ queryKey: ["logistics-riders"] });
    },
    onError: (e: any) => {
      toast({ title: "Failed to create rider", description: e?.message, variant: "destructive" });
    },
  });

  // Payload now matches the real Delivery schema (reference?, customer_id?,
  // address?, quantity?, status?) — the previous {destination, recipient_name,
  // recipient_phone} shape didn't match any field on the backend model
  // (extra="forbid"), so every submission 422'd, unconditionally.
  const createDelivery = useMutation({
    mutationFn: () =>
      api.logistics.createDelivery({
        address: {
          destination: deliveryDest.trim(),
          recipient_name: newDeliveryRecipient.trim() || undefined,
          recipient_phone: newDeliveryPhone.trim() || undefined,
        },
      }),
    onSuccess: (data: any) => {
      toast({ title: "Delivery created", description: deliveryDest.trim() });
      setDeliveryOpen(false);
      setDeliveryDest("");
      setNewDeliveryRecipient("");
      setNewDeliveryPhone("");
      void queryClient.invalidateQueries({ queryKey: ["logistics-deliveries"] });
      if (data?.delivery?.id) setSelectedDeliveryId(data.delivery.id);
    },
    onError: (e: any) => {
      toast({ title: "Failed to create delivery", description: e?.message, variant: "destructive" });
    },
  });

  const assignRoutes = useMutation({
    mutationFn: () => api.logistics.assignRoutes(),
    onSuccess: (data: any) => {
      toast({ title: "Routes assigned", description: `${data.assigned_count ?? 0} deliveries assigned` });
      void queryClient.invalidateQueries({ queryKey: ["logistics-deliveries"] });
    },
    onError: (e: any) => {
      toast({ title: "Assignment failed", description: e?.message, variant: "destructive" });
    },
  });

  const updateStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      api.logistics.updateDeliveryStatus(id, status),
    onSuccess: () => {
      toast({ title: "Status updated" });
      setStatusTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["logistics-deliveries"] });
    },
    onError: (e: any) => {
      toast({ title: "Update failed", description: e?.message, variant: "destructive" });
    },
  });

  const assignDelivery = useMutation({
    mutationFn: ({ id, riderId, destLat, destLng }: { id: string; riderId: string; destLat?: string; destLng?: string }) =>
      api.logistics.assignDelivery(
        id,
        riderId,
        destLat && destLng ? { dest_lat: Number(destLat), dest_lng: Number(destLng) } : undefined,
      ),
    onSuccess: () => {
      toast({ title: "Rider assigned" });
      setAssignRiderId("");
      void queryClient.invalidateQueries({ queryKey: ["logistics-deliveries"] });
    },
    onError: (e: any) => {
      toast({ title: "Failed to assign rider", description: e?.message, variant: "destructive" });
    },
  });

  const { data: routeData, isLoading: routeLoading } = useQuery({
    queryKey: ["logistics-route", routeRiderId],
    queryFn: () => api.logistics.getRiderRoute(routeRiderId!),
    enabled: routeRiderId !== null,
  });

  // Fallback poll — used when SSE is not live
  const { data: livePositionsData } = useQuery({
    queryKey: ["logistics-live-positions"],
    queryFn: () => api.logistics.livePositions(),
    refetchInterval: sseStatus === "live" ? false : 5_000,
    enabled: sseStatus !== "live",
  });

  useEffect(() => {
    if (sseStatus === "polling" && livePositionsData?.riders) {
      setLiveRiders(livePositionsData.riders as LiveRider[]);
    }
  }, [livePositionsData, sseStatus]);

  // The deliveries/riders lists previously refreshed only when THIS operator
  // performed a mutation, so a delivery dispatched from Frontdesk by Finance --
  // or a delivery a rider just confirmed -- never appeared on an already-open
  // Logistics Monitor without a manual page refresh. The live-feed SSE above
  // only carries rider GPS positions, not delivery state, so it did not cover
  // this. Subscribe to both lifecycle channels instead.
  const invalidateDeliveries = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["logistics-deliveries"] });
  }, [queryClient]);

  useRealtimeChannel("frontdesk_updates", invalidateDeliveries);
  useRealtimeChannel("logistics_updates", invalidateDeliveries);

  // SSE connection — started when "Live Map" tab is first activated
  function connectSSE() {
    if (sseStatus === "live" || sseStatus === "connecting") return;
    setSseStatus("connecting");
    const ac = new AbortController();
    sseAbortRef.current = ac;

    void (async () => {
      try {
        const token = authClient.getAccessToken();
        const res = await fetch(apiUrl("/logistics/live-feed"), {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          signal: ac.signal,
        });
        if (!res.ok || !res.body) throw new Error("SSE unavailable");
        setSseStatus("live");
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split("\n");
          buf = lines.pop() ?? "";
          for (const line of lines) {
            if (line.startsWith("data: ")) {
              try {
                const parsed = JSON.parse(line.slice(6)) as { riders?: LiveRider[] };
                if (parsed.riders) setLiveRiders(parsed.riders);
              } catch { /* malformed frame */ }
            }
          }
        }
        setSseStatus("polling");
      } catch (e) {
        if ((e as Error).name !== "AbortError") setSseStatus("polling");
      }
    })();
  }

  function disconnectSSE() {
    sseAbortRef.current?.abort();
    sseAbortRef.current = null;
    setSseStatus("off");
  }

  // Start delivery mutation
  const startDelivery = useMutation({
    mutationFn: (deliveryId: string) => api.logistics.startDelivery(deliveryId),
    onSuccess: (data: any, deliveryId: string) => {
      const url: string = data.tracking_url ?? "";
      setTrackingLinks((prev) => ({ ...prev, [deliveryId]: url }));
      toast({ title: "Tracking started", description: url ? "Tracking link generated" : undefined });
      void queryClient.invalidateQueries({ queryKey: ["logistics-deliveries"] });
    },
    onError: (e: any) => {
      toast({ title: "Failed to start tracking", description: e?.message, variant: "destructive" });
    },
  });

  // ---------------------------------------------------------------------------
  // Stats
  // ---------------------------------------------------------------------------

  const stats = {
    total:      deliveries.length,
    unassigned: deliveries.filter((d) => d.status === "unassigned").length,
    assigned:   deliveries.filter((d) => d.status === "assigned").length,
    in_transit: deliveries.filter((d) => d.status === "in_transit").length,
    delivered:  deliveries.filter((d) => d.status === "delivered").length,
  };

  return (
    <div className="space-y-6">
      <PageHeader
        icon={Truck}
        title="Logistics Monitor"
        subtitle="Riders · Deliveries · Route Assignment"
        actions={
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            disabled={assignRoutes.isPending || riders.length === 0 || stats.unassigned === 0}
            onClick={() => assignRoutes.mutate()}
          >
            {assignRoutes.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Route className="h-4 w-4" />}
            Assign Routes
          </Button>
        }
      />

      <KpiStrip
        items={[
          { label: "Total", value: stats.total },
          { label: "Unassigned", value: stats.unassigned },
          { label: "Assigned", value: stats.assigned, tone: "warning" },
          { label: "In Transit", value: stats.in_transit, tone: "warning" },
          { label: "Delivered", value: stats.delivered, tone: "success" },
        ]}
      />

      <Tabs defaultValue="deliveries" onValueChange={(v) => { if (v === "livemap") connectSSE(); else disconnectSSE(); }}>
        <TabsList>
          <TabsTrigger value="deliveries" className="gap-1.5">
            <Truck className="h-4 w-4" /> Deliveries
          </TabsTrigger>
          <TabsTrigger value="riders" className="gap-1.5">
            <User className="h-4 w-4" /> Riders
          </TabsTrigger>
          <TabsTrigger value="livemap" className="gap-1.5">
            <MapIcon className="h-4 w-4" /> Live Map
          </TabsTrigger>
        </TabsList>

        {/* Deliveries Tab — full retrofit: List/Detail/QuickActions. Real
            data has meaningfully more content than a flat row shows
            (structured address, quantity, source provenance, full GPS ping
            history) — closest precedent InvoicesTab. See
            ACE-Workspace-Standard.md §9.10. */}
        <TabsContent value="deliveries" className="mt-4">
          <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr_240px] gap-4">
            {/* List Panel */}
            <Card className="lg:max-h-[600px] flex flex-col">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Deliveries ({deliveries.length})</CardTitle>
              </CardHeader>
              <CardContent className="overflow-y-auto space-y-2 flex-1">
                {deliveriesLoading ? (
                  <div className="flex items-center justify-center py-12">
                    <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                  </div>
                ) : deliveries.length === 0 ? (
                  <div className="text-center py-12 text-muted-foreground text-sm">
                    No deliveries yet. Use "New Delivery" to add one.
                  </div>
                ) : (
                  deliveries.map((delivery) => (
                    <button
                      key={delivery.id}
                      onClick={() => setSelectedDeliveryId(delivery.id)}
                      className={`w-full text-left rounded-lg border px-3 py-2.5 hover:bg-muted/40 transition-colors ${
                        selectedDeliveryId === delivery.id ? "border-primary bg-muted/40" : ""
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <MapPin className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
                        <span className="font-medium text-sm truncate">{deliveryLabel(delivery)}</span>
                      </div>
                      <div className="mt-1"><StatusBadge status={delivery.status} /></div>
                    </button>
                  ))
                )}
              </CardContent>
            </Card>

            {/* Detail Workspace — inline, no dismiss button (Ch.5.1). */}
            <Card>
              <CardContent className="pt-6">
                {!selectedDelivery && (
                  <p className="text-sm text-muted-foreground text-center py-12">Select a delivery to view details.</p>
                )}
                {selectedDelivery && (
                  <div className="space-y-4 text-sm">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="font-bold text-lg">{deliveryLabel(selectedDelivery)}</div>
                        {selectedDelivery.reference && (
                          <div className="text-xs text-muted-foreground font-mono">{selectedDelivery.reference}</div>
                        )}
                      </div>
                      <StatusBadge status={selectedDelivery.status} />
                    </div>

                    <div className="grid grid-cols-2 gap-2">
                      {[
                        ["Recipient", deliveryRecipient(selectedDelivery)],
                        ["Phone", deliveryPhone(selectedDelivery)],
                        ["Quantity", selectedDelivery.quantity],
                        ["Source", selectedDelivery.source ?? "manual"],
                        ["Rider", selectedDelivery.rider?.name],
                        ["Rider Phone", selectedDelivery.rider?.phone],
                      ].map(([label, value]) => (
                        <div key={String(label)} className="space-y-0.5">
                          <div className="text-xs text-muted-foreground">{label}</div>
                          <div className="text-xs font-medium truncate">{value ?? "—"}</div>
                        </div>
                      ))}
                    </div>

                    {selectedDelivery.address?.items_summary && (
                      <div>
                        <div className="text-xs text-muted-foreground mb-1">Items</div>
                        <div className="text-xs bg-muted/40 rounded p-2">{selectedDelivery.address.items_summary}</div>
                      </div>
                    )}

                    <Separator />

                    <div>
                      <div className="text-xs font-semibold text-muted-foreground mb-2">TRACKING HISTORY</div>
                      {pingsLoading ? (
                        <div className="flex justify-center py-4">
                          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                        </div>
                      ) : pings.length === 0 ? (
                        <p className="text-xs text-muted-foreground">No GPS pings recorded yet.</p>
                      ) : (
                        <div className="space-y-1 max-h-32 overflow-y-auto">
                          {pings.map((p) => (
                            <div key={p.id} className="text-xs flex justify-between bg-muted/30 rounded px-2 py-1">
                              <span>{p.lat.toFixed(4)}, {p.lng.toFixed(4)}</span>
                              <span className="text-muted-foreground">{new Date(p.ts).toLocaleTimeString()}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    <Separator />

                    {selectedDelivery.status === "unassigned" && (
                      <div className="space-y-2">
                        <div className="flex items-center gap-2">
                          <Select value={assignRiderId} onValueChange={setAssignRiderId}>
                            <SelectTrigger className="h-8 text-xs flex-1">
                              <SelectValue placeholder={riders.filter((r) => r.active).length === 0 ? "No active riders" : "Select rider…"} />
                            </SelectTrigger>
                            <SelectContent>
                              {riders.filter((r) => r.active).map((r) => (
                                <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <Button
                            size="sm" className="gap-1 flex-shrink-0"
                            disabled={!assignRiderId || assignDelivery.isPending || (!!assignDestLat !== !!assignDestLng)}
                            onClick={() => assignDelivery.mutate({
                              id: selectedDelivery.id,
                              riderId: assignRiderId,
                              destLat: assignDestLat.trim(),
                              destLng: assignDestLng.trim(),
                            })}
                          >
                            {assignDelivery.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <User className="h-3.5 w-3.5" />}
                            Assign
                          </Button>
                        </div>
                        {/* Optional destination pin. Walk-in invoices carry no address,
                            so this is the only place a destination can be set — and
                            without it the arrival geofence never fires. */}
                        <div className="flex items-center gap-2">
                          <Input
                            value={assignDestLat}
                            onChange={(e) => setAssignDestLat(e.target.value)}
                            placeholder="Dest. latitude (optional)"
                            inputMode="decimal"
                            className="h-8 text-xs"
                          />
                          <Input
                            value={assignDestLng}
                            onChange={(e) => setAssignDestLng(e.target.value)}
                            placeholder="Dest. longitude (optional)"
                            inputMode="decimal"
                            className="h-8 text-xs"
                          />
                        </div>
                        <p className="text-[10px] text-muted-foreground">
                          Set a destination to enable automatic delivery confirmation when the rider arrives within 150 m.
                        </p>
                      </div>
                    )}

                    <div className="flex gap-2 flex-wrap">
                      {selectedDelivery.status === "assigned" && (
                        <Button
                          size="sm" variant="outline" className="gap-1 text-green-600"
                          disabled={startDelivery.isPending}
                          onClick={() => startDelivery.mutate(selectedDelivery.id)}
                        >
                          {startDelivery.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                          Start
                        </Button>
                      )}
                      {trackingUrlFor(selectedDelivery, trackingLinks) && (
                        <Button
                          size="sm" variant="ghost" className="gap-1"
                          onClick={() => {
                            const url = trackingUrlFor(selectedDelivery, trackingLinks)!;
                            void navigator.clipboard.writeText(url);
                            toast({ title: "Tracking link copied!" });
                          }}
                        >
                          <Copy className="h-3.5 w-3.5" /> Copy Tracking Link
                        </Button>
                      )}
                      {selectedDelivery.status !== "delivered" && selectedDelivery.status !== "failed" && (
                        <Button
                          size="sm" variant="outline" className="gap-1"
                          onClick={() => { setStatusTarget(selectedDelivery); setNewStatus("in_transit"); }}
                        >
                          Update Status
                        </Button>
                      )}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Quick Actions */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Quick Actions</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <Button className="w-full" size="sm" onClick={() => setDeliveryOpen(true)}>
                  <Truck className="h-4 w-4 mr-1" /> New Delivery
                </Button>
                <Button
                  variant="outline" className="w-full" size="sm"
                  onClick={() => refetchDeliveries()} disabled={deliveriesLoading}
                >
                  <RefreshCw className="h-4 w-4 mr-1" /> Refresh
                </Button>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* Riders Tab — partial retrofit: KpiStrip + DetailSheet for the
            create form, flat card list kept as-is (every card already shows
            what's relevant, "Route" is already a single Dialog click away).
            See ACE-Workspace-Standard.md §9.5/§9.10. */}
        <TabsContent value="riders" className="mt-4">
          <motion.div {...motionVariants.cardEnter} className="space-y-3">
            <KpiStrip
              items={[
                { label: "Total Riders", value: riders.length },
                { label: "Active", value: riders.filter((r) => r.active).length, tone: "success" },
                { label: "Inactive", value: riders.filter((r) => !r.active).length },
              ]}
            />
            <div className="flex justify-end">
              <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setRiderOpen(true)}>
                <Plus className="h-3.5 w-3.5" /> Register Rider
              </Button>
            </div>
            {ridersLoading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : riders.length === 0 ? (
              <Card>
                <CardContent className="py-12 text-center text-muted-foreground text-sm">
                  <User className="h-8 w-8 mx-auto mb-2 opacity-40" />
                  No riders registered. Click <strong>"Register Rider"</strong> to add one.
                </CardContent>
              </Card>
            ) : (
              riders.map((rider) => (
                <Card key={rider.id} className="border-border/60">
                  <CardContent className="p-4 flex items-center justify-between gap-3">
                    <div className="space-y-0.5">
                      <p className="text-sm font-medium">{rider.name}</p>
                      <div className="flex items-center gap-3 text-xs text-muted-foreground">
                        {rider.phone && <span>{rider.phone}</span>}
                        {rider.vehicle && (
                          <Badge variant="outline" className="text-[10px]">{rider.vehicle}</Badge>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant={rider.active ? "default" : "secondary"} className="text-xs">
                        {rider.active ? "Active" : "Inactive"}
                      </Badge>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 text-xs gap-1"
                        onClick={() => setRouteRiderId(rider.id)}
                      >
                        <Route className="h-3 w-3" />
                        Route
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))
            )}
          </motion.div>
        </TabsContent>

        {/* Live Map Tab */}
        <TabsContent value="livemap" className="mt-4">
          <motion.div {...motionVariants.cardEnter} className="space-y-3">
            {/* Status bar */}
            <div className="flex items-center justify-between px-1">
              <div className="flex items-center gap-2 text-xs">
                <Signal
                  className={`h-4 w-4 ${
                    sseStatus === "live"
                      ? "text-green-500"
                      : sseStatus === "connecting"
                      ? "text-yellow-400 animate-pulse"
                      : sseStatus === "polling"
                      ? "text-blue-400"
                      : "text-muted-foreground"
                  }`}
                />
                <span className="text-muted-foreground">
                  {sseStatus === "live"
                    ? "Live feed active"
                    : sseStatus === "connecting"
                    ? "Connecting…"
                    : sseStatus === "polling"
                    ? "Polling every 5 s"
                    : "Not connected"}
                </span>
              </div>
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <Navigation className="h-3.5 w-3.5" />
                {liveRiders.length} active rider{liveRiders.length !== 1 ? "s" : ""}
              </div>
            </div>

            {/* Leaflet Map */}
            <div className="rounded-lg overflow-hidden border border-border/60 h-[420px] relative">
              <MapContainer
                center={[6.5244, 3.3792]}   // Lagos, Nigeria
                zoom={12}
                style={{ height: "100%", width: "100%" }}
                scrollWheelZoom={true}
              >
                <TileLayer
                  url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                  attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                />
                {liveRiders.map((rider) => (
                  <Marker key={rider.id} position={[rider.last_lat, rider.last_lng]}>
                    <Popup>
                      <div className="text-sm space-y-1">
                        <p className="font-semibold">{rider.name}</p>
                        {rider.vehicle && (
                          <p className="text-muted-foreground capitalize">{rider.vehicle}</p>
                        )}
                        {rider.last_seen_at && (
                          <p className="text-xs text-muted-foreground">
                            Last seen: {new Date(rider.last_seen_at).toLocaleTimeString()}
                          </p>
                        )}
                      </div>
                    </Popup>
                  </Marker>
                ))}
              </MapContainer>
            </div>

            {/* Active riders list below map */}
            {liveRiders.length === 0 ? (
              <Card>
                <CardContent className="py-8 text-center text-muted-foreground text-sm">
                  <Navigation className="h-7 w-7 mx-auto mb-2 opacity-40" />
                  No active riders with GPS data. Start a delivery to see riders on the map.
                </CardContent>
              </Card>
            ) : (
              liveRiders.map((rider) => (
                <Card key={rider.id} className="border-border/60">
                  <CardContent className="p-3 flex items-center gap-3">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium">{rider.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {rider.last_lat.toFixed(5)}, {rider.last_lng.toFixed(5)}
                        {rider.last_seen_at && (
                          <> · {new Date(rider.last_seen_at).toLocaleTimeString()}</>
                        )}
                      </p>
                    </div>
                    {rider.vehicle && (
                      <Badge variant="outline" className="text-xs capitalize">{rider.vehicle}</Badge>
                    )}
                    <div className="flex h-2.5 w-2.5 rounded-full bg-green-500 relative">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                    </div>
                  </CardContent>
                </Card>
              ))
            )}
          </motion.div>
        </TabsContent>
      </Tabs>

      {/* Register Rider — ephemeral create task, DetailSheet per Ch.5.2.
          After creation the sheet switches to a success view showing the
          rider's persistent ACE Riders sign-in code (shown once, like an
          API key) instead of closing immediately -- staff need to actually
          relay this to the rider by phone/WhatsApp/etc. */}
      <DetailSheet
        open={riderOpen}
        onOpenChange={(open) => {
          setRiderOpen(open);
          if (!open) { setNewRiderCode(null); setCodeCopied(false); }
        }}
        title={newRiderCode ? "Rider Registered" : "Register Rider"}
        description={newRiderCode ? "Share this sign-in code with the rider." : "Add a new dispatch rider to the system."}
        icon={User}
        footer={
          newRiderCode ? (
            <Button className="w-full gap-2" onClick={() => setRiderOpen(false)}>
              Done
            </Button>
          ) : (
            <Button className="w-full gap-2" disabled={riderName.trim().length < 2 || createRider.isPending} onClick={() => createRider.mutate()}>
              {createRider.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <User className="h-4 w-4" />}
              Register
            </Button>
          )
        }
      >
        {newRiderCode ? (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              This code signs the rider in at <strong>/rider</strong> and stays valid across every future delivery — no need to send a new link each time.
            </p>
            <div className="flex items-center justify-between gap-3 rounded-xl border border-border/60 bg-muted/30 px-5 py-4">
              <span className="text-2xl font-bold tracking-[0.3em]">{newRiderCode}</span>
              <Button
                type="button"
                size="icon"
                variant="ghost"
                onClick={() => {
                  navigator.clipboard.writeText(newRiderCode);
                  setCodeCopied(true);
                  setTimeout(() => setCodeCopied(false), 2000);
                }}
              >
                {codeCopied ? <CheckCircle2 className="h-4 w-4 text-green-500" /> : <Copy className="h-4 w-4" />}
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="space-y-1">
              <label className="text-sm font-medium">Name *</label>
              <Input placeholder="e.g. Ahmed Musa" value={riderName} onChange={(e) => setRiderName(e.target.value)} />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Phone <span className="text-muted-foreground text-xs">(optional)</span></label>
              <Input type="tel" placeholder="+234 801 234 5678" value={riderPhone} onChange={(e) => setRiderPhone(e.target.value)} />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Vehicle</label>
              <Select value={riderVehicle} onValueChange={setRiderVehicle}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="motorcycle">Motorcycle</SelectItem>
                  <SelectItem value="bicycle">Bicycle</SelectItem>
                  <SelectItem value="van">Van</SelectItem>
                  <SelectItem value="car">Car</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        )}
      </DetailSheet>

      {/* New Delivery — ephemeral create task, DetailSheet per Ch.5.2. */}
      <DetailSheet
        open={deliveryOpen}
        onOpenChange={setDeliveryOpen}
        title="New Delivery"
        description="Create a new delivery job to be assigned."
        icon={Truck}
        footer={
          <Button className="w-full gap-2" disabled={deliveryDest.trim().length < 3 || createDelivery.isPending} onClick={() => createDelivery.mutate()}>
            {createDelivery.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Truck className="h-4 w-4" />}
            Create Delivery
          </Button>
        }
      >
        <div className="space-y-3">
          <div className="space-y-1">
            <label className="text-sm font-medium">Destination *</label>
            <Input placeholder="e.g. 14 Broad Street, Lagos" value={deliveryDest} onChange={(e) => setDeliveryDest(e.target.value)} />
          </div>
          <div className="space-y-1">
            <label className="text-sm font-medium">Recipient Name <span className="text-muted-foreground text-xs">(optional)</span></label>
            <Input placeholder="e.g. Medway Pharmacy" value={newDeliveryRecipient} onChange={(e) => setNewDeliveryRecipient(e.target.value)} />
          </div>
          <div className="space-y-1">
            <label className="text-sm font-medium">Recipient Phone <span className="text-muted-foreground text-xs">(optional)</span></label>
            <Input type="tel" placeholder="+234 ..." value={newDeliveryPhone} onChange={(e) => setNewDeliveryPhone(e.target.value)} />
          </div>
        </div>
      </DetailSheet>

      {/* Update Status Dialog */}
      <Dialog open={statusTarget !== null} onOpenChange={(open) => { if (!open) setStatusTarget(null); }}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Update Delivery Status</DialogTitle>
            <DialogDescription>{statusTarget ? deliveryLabel(statusTarget) : ""}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="space-y-1">
              <label className="text-sm font-medium">New Status</label>
              <Select value={newStatus} onValueChange={setNewStatus}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="assigned">Assigned</SelectItem>
                  <SelectItem value="in_transit">In Transit</SelectItem>
                  <SelectItem value="delivered">Delivered</SelectItem>
                  <SelectItem value="failed">Failed</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setStatusTarget(null)}>Cancel</Button>
            <Button
              disabled={updateStatus.isPending}
              onClick={() => {
                if (statusTarget) updateStatus.mutate({ id: statusTarget.id, status: newStatus });
              }}
              className="gap-2"
            >
              {updateStatus.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              Update
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Route Viewer Dialog */}
      <Dialog open={routeRiderId !== null} onOpenChange={(open) => { if (!open) setRouteRiderId(null); }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Route className="h-5 w-5" /> Rider Route
            </DialogTitle>
            <DialogDescription>Active deliveries for this rider.</DialogDescription>
          </DialogHeader>
          <div className="py-2 space-y-2 max-h-64 overflow-y-auto">
            {routeLoading ? (
              <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
            ) : ((routeData as any)?.deliveries?.length ?? 0) === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">No deliveries on this route.</p>
            ) : (
              ((routeData as any).deliveries as Delivery[]).map((d) => (
                <div key={d.id} className="flex items-center justify-between gap-2 py-1 border-b last:border-0">
                  <div className="min-w-0">
                    <p className="text-sm truncate">{deliveryLabel(d)}</p>
                    {deliveryRecipient(d) && <p className="text-xs text-muted-foreground">{deliveryRecipient(d)}</p>}
                  </div>
                  <StatusBadge status={d.status} />
                </div>
              ))
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRouteRiderId(null)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
