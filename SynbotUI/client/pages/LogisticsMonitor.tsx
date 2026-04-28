import { useState, useEffect, useRef } from "react";
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
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api-client";
import { motion } from "framer-motion";
import { motionVariants } from "@/lib/motion";

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
}

interface LiveRider {
  id: string;
  name: string;
  vehicle?: string;
  last_lat: number;
  last_lng: number;
  last_seen_at?: string;
}

interface Delivery {
  id: string;
  destination: string;
  recipient_name?: string;
  recipient_phone?: string;
  status: "unassigned" | "assigned" | "in_transit" | "delivered" | "failed";
  assigned_rider?: string;
  created_at?: string;
  last_update?: string;
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

  // Local lists (populated from mutations)
  const [riders, setRiders] = useState<Rider[]>([]);
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);

  // Create Rider dialog
  const [riderOpen, setRiderOpen] = useState(false);
  const [riderName, setRiderName] = useState("");
  const [riderPhone, setRiderPhone] = useState("");
  const [riderVehicle, setRiderVehicle] = useState("motorcycle");

  // Create Delivery dialog
  const [deliveryOpen, setDeliveryOpen] = useState(false);
  const [deliveryDest, setDeliveryDest] = useState("");
  const [deliveryRecipient, setDeliveryRecipient] = useState("");
  const [deliveryPhone, setDeliveryPhone] = useState("");

  // Update status
  const [statusTarget, setStatusTarget] = useState<Delivery | null>(null);
  const [newStatus, setNewStatus] = useState<string>("in_transit");

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
      const created: Rider = data.rider;
      setRiders((prev) => [...prev, created]);
      toast({ title: "Rider registered", description: created.name });
      setRiderOpen(false);
      setRiderName("");
      setRiderPhone("");
    },
    onError: (e: any) => {
      toast({ title: "Failed to create rider", description: e?.message, variant: "destructive" });
    },
  });

  const createDelivery = useMutation({
    mutationFn: () =>
      api.logistics.createDelivery({
        destination: deliveryDest.trim(),
        recipient_name: deliveryRecipient.trim() || undefined,
        recipient_phone: deliveryPhone.trim() || undefined,
      }),
    onSuccess: (data: any) => {
      const created: Delivery = data.delivery;
      setDeliveries((prev) => [...prev, created]);
      toast({ title: "Delivery created", description: created.destination });
      setDeliveryOpen(false);
      setDeliveryDest("");
      setDeliveryRecipient("");
      setDeliveryPhone("");
    },
    onError: (e: any) => {
      toast({ title: "Failed to create delivery", description: e?.message, variant: "destructive" });
    },
  });

  const assignRoutes = useMutation({
    mutationFn: () => api.logistics.assignRoutes(),
    onSuccess: (data: any) => {
      toast({ title: "Routes assigned", description: `${data.assigned_count ?? 0} deliveries assigned` });
      // Update local deliveries to 'assigned' for unassigned ones
      setDeliveries((prev) =>
        prev.map((d) => (d.status === "unassigned" ? { ...d, status: "assigned" as const } : d))
      );
    },
    onError: (e: any) => {
      toast({ title: "Assignment failed", description: e?.message, variant: "destructive" });
    },
  });

  const updateStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      api.logistics.updateDeliveryStatus(id, status),
    onSuccess: (_data, { id, status }) => {
      setDeliveries((prev) => prev.map((d) => (d.id === id ? { ...d, status: status as any } : d)));
      toast({ title: "Status updated" });
      setStatusTarget(null);
    },
    onError: (e: any) => {
      toast({ title: "Update failed", description: e?.message, variant: "destructive" });
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
      setDeliveries((prev) =>
        prev.map((d) => (d.id === deliveryId ? { ...d, status: "in_transit" as const } : d))
      );
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
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold">Logistics Monitor</h1>
          <p className="text-sm text-muted-foreground">Riders · Deliveries · Route Assignment</p>
        </div>
        <div className="flex items-center gap-2">
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
          <Button size="sm" className="gap-1.5" onClick={() => setDeliveryOpen(true)}>
            <Truck className="h-4 w-4" /> New Delivery
          </Button>
        </div>
      </div>

      {/* Stats bar */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        {[
          { label: "Total",       value: stats.total,      color: "text-foreground" },
          { label: "Unassigned",  value: stats.unassigned, color: "text-muted-foreground" },
          { label: "Assigned",    value: stats.assigned,   color: "text-blue-600 dark:text-blue-400" },
          { label: "In Transit",  value: stats.in_transit, color: "text-yellow-600 dark:text-yellow-400" },
          { label: "Delivered",   value: stats.delivered,  color: "text-green-600 dark:text-green-400" },
        ].map((stat) => (
          <Card key={stat.label} className="text-center">
            <CardContent className="p-3">
              <p className={`text-2xl font-bold ${stat.color}`}>{stat.value}</p>
              <p className="text-xs text-muted-foreground">{stat.label}</p>
            </CardContent>
          </Card>
        ))}
      </div>

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

        {/* Deliveries Tab */}
        <TabsContent value="deliveries" className="mt-4">
          <motion.div {...motionVariants.cardEnter} className="space-y-3">
            {deliveries.length === 0 ? (
              <Card>
                <CardContent className="py-12 text-center text-muted-foreground text-sm">
                  <Truck className="h-8 w-8 mx-auto mb-2 opacity-40" />
                  No deliveries yet. Click <strong>"New Delivery"</strong> to add one.
                </CardContent>
              </Card>
            ) : (
              deliveries.map((delivery) => (
                <Card key={delivery.id} className="border-border/60">
                  <CardContent className="p-4 flex items-center justify-between gap-3 flex-wrap">
                    <div className="min-w-0 space-y-0.5">
                      <div className="flex items-center gap-2">
                        <MapPin className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
                        <p className="text-sm font-medium truncate">{delivery.destination}</p>
                      </div>
                      {delivery.recipient_name && (
                        <p className="text-xs text-muted-foreground pl-5">{delivery.recipient_name}</p>
                      )}
                      {delivery.assigned_rider && (
                        <p className="text-xs text-muted-foreground pl-5 font-mono">
                          Rider: {delivery.assigned_rider.slice(-8)}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <StatusBadge status={delivery.status} />
                      {delivery.status === "assigned" && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 text-xs gap-1 text-green-600"
                          disabled={startDelivery.isPending}
                          onClick={() => startDelivery.mutate(delivery.id)}
                        >
                          {startDelivery.isPending && startDelivery.variables === delivery.id ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <Play className="h-3 w-3" />
                          )}
                          Start
                        </Button>
                      )}
                      {trackingLinks[delivery.id] && (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 text-xs gap-1"
                          onClick={() => {
                            void navigator.clipboard.writeText(trackingLinks[delivery.id]);
                            toast({ title: "Tracking link copied!" });
                          }}
                        >
                          <Copy className="h-3 w-3" />
                        </Button>
                      )}
                      {delivery.status !== "delivered" && delivery.status !== "failed" && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 text-xs gap-1"
                          onClick={() => { setStatusTarget(delivery); setNewStatus("in_transit"); }}
                        >
                          Update
                        </Button>
                      )}
                    </div>
                  </CardContent>
                </Card>
              ))
            )}
          </motion.div>
        </TabsContent>

        {/* Riders Tab */}
        <TabsContent value="riders" className="mt-4">
          <motion.div {...motionVariants.cardEnter} className="space-y-3">
            <div className="flex justify-end">
              <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setRiderOpen(true)}>
                <Plus className="h-3.5 w-3.5" /> Register Rider
              </Button>
            </div>
            {riders.length === 0 ? (
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

      {/* Register Rider Dialog */}
      <Dialog open={riderOpen} onOpenChange={setRiderOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Register Rider</DialogTitle>
            <DialogDescription>Add a new dispatch rider to the system.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
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
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setRiderOpen(false)}>Cancel</Button>
            <Button disabled={riderName.trim().length < 2 || createRider.isPending} onClick={() => createRider.mutate()} className="gap-2">
              {createRider.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <User className="h-4 w-4" />}
              Register
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* New Delivery Dialog */}
      <Dialog open={deliveryOpen} onOpenChange={setDeliveryOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>New Delivery</DialogTitle>
            <DialogDescription>Create a new delivery job to be assigned.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="space-y-1">
              <label className="text-sm font-medium">Destination *</label>
              <Input placeholder="e.g. 14 Broad Street, Lagos" value={deliveryDest} onChange={(e) => setDeliveryDest(e.target.value)} />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Recipient Name <span className="text-muted-foreground text-xs">(optional)</span></label>
              <Input placeholder="e.g. Medway Pharmacy" value={deliveryRecipient} onChange={(e) => setDeliveryRecipient(e.target.value)} />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Recipient Phone <span className="text-muted-foreground text-xs">(optional)</span></label>
              <Input type="tel" placeholder="+234 ..." value={deliveryPhone} onChange={(e) => setDeliveryPhone(e.target.value)} />
            </div>
          </div>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setDeliveryOpen(false)}>Cancel</Button>
            <Button disabled={deliveryDest.trim().length < 3 || createDelivery.isPending} onClick={() => createDelivery.mutate()} className="gap-2">
              {createDelivery.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Truck className="h-4 w-4" />}
              Create Delivery
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Update Status Dialog */}
      <Dialog open={statusTarget !== null} onOpenChange={(open) => { if (!open) setStatusTarget(null); }}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Update Delivery Status</DialogTitle>
            <DialogDescription>{statusTarget?.destination}</DialogDescription>
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
                    <p className="text-sm truncate">{d.destination}</p>
                    {d.recipient_name && <p className="text-xs text-muted-foreground">{d.recipient_name}</p>}
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
