/**
 * RiderTrack.tsx
 *
 * Rider-facing PWA page — no authentication UI, accessible via public URL.
 * The tracking_token in the URL path IS the credential for all API calls.
 *
 * Route: /rider-track/:token
 *
 * Features:
 *  - Fetch delivery info on mount via GET /logistics/track/:token
 *  - "Start Tracking" → requests wakeLock + starts watchPosition loop
 *  - POSTs GPS pings to /logistics/location-ping every PING_INTERVAL_MS
 *  - localStorage offline queue → drained on reconnect (handles Nigeria network drops)
 *  - Auto-delivered banner when backend returns auto_delivered: true
 *  - Manual "Confirm Delivery" button
 *  - Battery / signal / accuracy status indicators
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  MapPin,
  Navigation,
  Wifi,
  WifiOff,
  Battery,
  CheckCircle,
  Loader2,
  AlertTriangle,
  Package,
  User,
  Phone,
} from "lucide-react";

// ─── Constants ────────────────────────────────────────────────────────────────

const API_BASE = import.meta.env.VITE_API_URL ?? "";
const PING_INTERVAL_MS = 5_000;
const OFFLINE_QUEUE_KEY = "ridertrack_offline_pings";

// ─── Types ────────────────────────────────────────────────────────────────────

interface DeliveryInfo {
  id: string;
  reference?: string;
  status: string;
  address?: Record<string, unknown>;
  dest_lat?: number;
  dest_lng?: number;
  eta_text?: string;
}

interface OfflinePing {
  token: string;
  lat: number;
  lng: number;
  speed_kmh?: number;
  accuracy_m?: number;
  battery_pct?: number;
  ts: string;
}

type TrackingState = "idle" | "loading" | "ready" | "tracking" | "delivered" | "error";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function loadOfflineQueue(): OfflinePing[] {
  try {
    const raw = localStorage.getItem(OFFLINE_QUEUE_KEY);
    return raw ? (JSON.parse(raw) as OfflinePing[]) : [];
  } catch {
    return [];
  }
}

function saveOfflineQueue(queue: OfflinePing[]): void {
  try {
    localStorage.setItem(OFFLINE_QUEUE_KEY, JSON.stringify(queue));
  } catch {
    // Storage quota exceeded — discard oldest
    localStorage.setItem(OFFLINE_QUEUE_KEY, JSON.stringify(queue.slice(-20)));
  }
}

function getBatteryPct(): number | undefined {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const nav = navigator as any;
  if (nav.getBattery) {
    // getBattery() is async — cached synchronously via event listener elsewhere
  }
  return undefined; // populated separately
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function RiderTrack() {
  const { token } = useParams<{ token: string }>();

  const [state, setState] = useState<TrackingState>("loading");
  const [delivery, setDelivery] = useState<DeliveryInfo | null>(null);
  const [error, setError] = useState<string>("");
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [batteryPct, setBatteryPct] = useState<number | undefined>();
  const [lastAccuracy, setLastAccuracy] = useState<number | undefined>();
  const [lastSpeed, setLastSpeed] = useState<number | undefined>();
  const [pingCount, setPingCount] = useState(0);
  const [autoDelivered, setAutoDelivered] = useState(false);

  const watchIdRef = useRef<number | null>(null);
  const wakeLockRef = useRef<WakeLockSentinel | null>(null);
  const pingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastPositionRef = useRef<GeolocationPosition | null>(null);
  const offlineQueueRef = useRef<OfflinePing[]>(loadOfflineQueue());
  const isMountedRef = useRef(true);

  // ── Online / offline monitoring ──────────────────────────────────────────
  useEffect(() => {
    const onOnline = () => {
      setIsOnline(true);
      void drainOfflineQueue();
    };
    const onOffline = () => setIsOnline(false);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, []);

  // ── Battery monitoring ────────────────────────────────────────────────────
  useEffect(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const nav = navigator as any;
    if (typeof nav.getBattery === "function") {
      nav.getBattery().then((battery: { level: number; addEventListener: Function }) => {
        const update = () => setBatteryPct(Math.round(battery.level * 100));
        update();
        battery.addEventListener("levelchange", update);
      });
    }
  }, []);

  // ── Fetch delivery info on mount ──────────────────────────────────────────
  useEffect(() => {
    if (!token) {
      setError("No tracking token in URL.");
      setState("error");
      return;
    }
    void fetchDelivery();
    return () => {
      isMountedRef.current = false;
      stopTracking();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function fetchDelivery() {
    try {
      const res = await fetch(`${API_BASE}/logistics/track/${encodeURIComponent(token!)}`, {
        headers: { "Content-Type": "application/json" },
      });
      if (!res.ok) {
        const data = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(data.detail ?? `HTTP ${res.status}`);
      }
      const data = (await res.json()) as { delivery: DeliveryInfo };
      if (!isMountedRef.current) return;
      setDelivery(data.delivery);
      if (data.delivery.status === "delivered") {
        setState("delivered");
      } else {
        setState("ready");
      }
    } catch (err) {
      if (!isMountedRef.current) return;
      setError(err instanceof Error ? err.message : "Failed to load delivery.");
      setState("error");
    }
  }

  // ── GPS ping ──────────────────────────────────────────────────────────────
  const sendPing = useCallback(
    async (pos: GeolocationPosition) => {
      if (!token) return;
      const ping: OfflinePing = {
        token,
        lat: pos.coords.latitude,
        lng: pos.coords.longitude,
        speed_kmh:
          pos.coords.speed != null ? Math.round(pos.coords.speed * 3.6) : undefined,
        accuracy_m: pos.coords.accuracy != null ? Math.round(pos.coords.accuracy) : undefined,
        battery_pct: batteryPct,
        ts: new Date().toISOString(),
      };

      setLastAccuracy(ping.accuracy_m);
      setLastSpeed(ping.speed_kmh);

      if (!navigator.onLine) {
        offlineQueueRef.current.push(ping);
        saveOfflineQueue(offlineQueueRef.current);
        return;
      }

      try {
        const res = await fetch(`${API_BASE}/logistics/location-ping`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(ping),
        });
        if (res.ok) {
          const data = (await res.json()) as { auto_delivered?: boolean };
          setPingCount((c) => c + 1);
          if (data.auto_delivered) {
            setAutoDelivered(true);
            setDelivery((d) => d ? { ...d, status: "delivered" } : d);
            setState("delivered");
            stopTracking();
          }
        } else {
          // Server error — queue offline
          offlineQueueRef.current.push(ping);
          saveOfflineQueue(offlineQueueRef.current);
        }
      } catch {
        // Network error — queue offline
        offlineQueueRef.current.push(ping);
        saveOfflineQueue(offlineQueueRef.current);
      }
    },
    [token, batteryPct]
  );

  const drainOfflineQueue = useCallback(async () => {
    if (offlineQueueRef.current.length === 0) return;
    const queue = [...offlineQueueRef.current];
    offlineQueueRef.current = [];
    saveOfflineQueue([]);
    for (const ping of queue) {
      try {
        await fetch(`${API_BASE}/logistics/location-ping`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(ping),
        });
      } catch {
        // re-queue on failure
        offlineQueueRef.current.push(ping);
      }
    }
    if (offlineQueueRef.current.length > 0) {
      saveOfflineQueue(offlineQueueRef.current);
    }
  }, []);

  // ── Start / stop tracking ──────────────────────────────────────────────────
  async function startTracking() {
    if (!("geolocation" in navigator)) {
      setError("Geolocation is not supported by this browser.");
      setState("error");
      return;
    }

    // Request wake lock to prevent GPS suspension
    try {
      if ("wakeLock" in navigator) {
        wakeLockRef.current = await (navigator as Navigator & { wakeLock: WakeLock }).wakeLock.request("screen");
      }
    } catch {
      // Wake lock not critical — continue without it
    }

    setState("tracking");

    watchIdRef.current = navigator.geolocation.watchPosition(
      (pos) => {
        lastPositionRef.current = pos;
      },
      (err) => {
        console.warn("GPS error:", err.message);
      },
      {
        enableHighAccuracy: true,
        timeout: 10_000,
        maximumAge: 0,
      }
    );

    // Ping loop — reads cached position every PING_INTERVAL_MS
    pingIntervalRef.current = setInterval(() => {
      if (lastPositionRef.current) {
        void sendPing(lastPositionRef.current);
      }
    }, PING_INTERVAL_MS);
  }

  function stopTracking() {
    if (watchIdRef.current !== null) {
      navigator.geolocation.clearWatch(watchIdRef.current);
      watchIdRef.current = null;
    }
    if (pingIntervalRef.current !== null) {
      clearInterval(pingIntervalRef.current);
      pingIntervalRef.current = null;
    }
    if (wakeLockRef.current) {
      void wakeLockRef.current.release();
      wakeLockRef.current = null;
    }
  }

  async function handleManualDelivery() {
    if (!delivery) return;
    try {
      const res = await fetch(
        `${API_BASE}/logistics/deliveries/${encodeURIComponent(delivery.id)}/status`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          // This page has no staff JWT (it's public, token-authenticated) --
          // the tracking token itself now authenticates this call, same
          // credential model as the location-ping calls above.
          body: JSON.stringify({ status: "delivered", token }),
        }
      );
      if (res.ok) {
        stopTracking();
        setDelivery((d) => d ? { ...d, status: "delivered" } : d);
        setState("delivered");
      }
    } catch {
      // Non-critical — rider will try again
    }
  }

  // ── Accuracy signal strength ───────────────────────────────────────────────
  function getSignalLabel() {
    if (lastAccuracy == null) return "—";
    if (lastAccuracy <= 10) return "Excellent";
    if (lastAccuracy <= 25) return "Good";
    if (lastAccuracy <= 50) return "Fair";
    return "Weak";
  }

  function getSignalColor() {
    if (lastAccuracy == null) return "text-muted-foreground";
    if (lastAccuracy <= 10) return "text-green-500";
    if (lastAccuracy <= 25) return "text-green-400";
    if (lastAccuracy <= 50) return "text-yellow-400";
    return "text-red-400";
  }

  // ── Format address ─────────────────────────────────────────────────────────
  function formatAddress(addr: Record<string, unknown> | undefined): string {
    if (!addr) return "No address provided";
    return [addr.line1, addr.city, addr.state].filter(Boolean).join(", ");
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────────

  if (state === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-3 text-muted-foreground">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <p>Loading delivery…</p>
        </div>
      </div>
    );
  }

  if (state === "error") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background p-4">
        <Alert variant="destructive" className="max-w-sm">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{error || "An unexpected error occurred."}</AlertDescription>
        </Alert>
      </div>
    );
  }

  if (state === "delivered") {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-background p-6 gap-6">
        <CheckCircle className="h-20 w-20 text-green-500" />
        <h1 className="text-2xl font-bold text-foreground">Delivery Complete!</h1>
        {autoDelivered && (
          <p className="text-muted-foreground text-center text-sm">
            Auto-confirmed — you arrived within 150 m of the destination.
          </p>
        )}
        <Card className="w-full max-w-sm">
          <CardContent className="pt-4 space-y-1 text-sm text-muted-foreground">
            <p>
              <span className="font-medium text-foreground">Reference: </span>
              {delivery?.reference ?? delivery?.id}
            </p>
            <p>
              <span className="font-medium text-foreground">Address: </span>
              {formatAddress(delivery?.address)}
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background p-4 flex flex-col gap-4 max-w-md mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between pt-2">
        <div className="flex items-center gap-2">
          <Package className="h-6 w-6 text-primary" />
          <h1 className="text-xl font-bold text-foreground">Placeware Delivery</h1>
        </div>
        <div className="flex items-center gap-1">
          {isOnline ? (
            <Wifi className="h-4 w-4 text-green-500" />
          ) : (
            <WifiOff className="h-4 w-4 text-red-400" />
          )}
          <span className={`text-xs ${isOnline ? "text-green-500" : "text-red-400"}`}>
            {isOnline ? "Online" : "Offline"}
          </span>
        </div>
      </div>

      {/* Delivery card */}
      {delivery && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <MapPin className="h-4 w-4 text-primary" />
              Delivery #{delivery.reference ?? delivery.id.slice(0, 8)}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex items-start gap-2">
              <MapPin className="h-4 w-4 mt-0.5 shrink-0 text-muted-foreground" />
              <span className="text-foreground">{formatAddress(delivery.address)}</span>
            </div>
            {delivery.eta_text && (
              <div className="flex items-center gap-2 text-muted-foreground">
                <Navigation className="h-4 w-4" />
                <span>ETA: {delivery.eta_text}</span>
              </div>
            )}
            <Badge
              variant={delivery.status === "in_transit" ? "default" : "secondary"}
              className="mt-1"
            >
              {delivery.status.replace("_", " ")}
            </Badge>
          </CardContent>
        </Card>
      )}

      {/* Status indicators (visible while tracking) */}
      {state === "tracking" && (
        <Card className="bg-muted/40">
          <CardContent className="pt-4 grid grid-cols-3 gap-3 text-center">
            {/* GPS signal */}
            <div className="flex flex-col items-center gap-1">
              <Navigation className={`h-5 w-5 ${getSignalColor()}`} />
              <span className="text-xs text-muted-foreground">Signal</span>
              <span className={`text-xs font-semibold ${getSignalColor()}`}>
                {getSignalLabel()}
              </span>
              {lastAccuracy != null && (
                <span className="text-xs text-muted-foreground">±{lastAccuracy}m</span>
              )}
            </div>

            {/* Speed */}
            <div className="flex flex-col items-center gap-1">
              <Navigation className="h-5 w-5 text-blue-400 rotate-45" />
              <span className="text-xs text-muted-foreground">Speed</span>
              <span className="text-xs font-semibold text-foreground">
                {lastSpeed != null ? `${lastSpeed} km/h` : "—"}
              </span>
            </div>

            {/* Battery */}
            <div className="flex flex-col items-center gap-1">
              <Battery
                className={`h-5 w-5 ${
                  batteryPct == null
                    ? "text-muted-foreground"
                    : batteryPct <= 20
                    ? "text-red-400"
                    : "text-green-400"
                }`}
              />
              <span className="text-xs text-muted-foreground">Battery</span>
              <span className="text-xs font-semibold text-foreground">
                {batteryPct != null ? `${batteryPct}%` : "—"}
              </span>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Ping counter + offline queue notice */}
      {state === "tracking" && (
        <div className="flex items-center justify-between px-1 text-xs text-muted-foreground">
          <span>Pings sent: {pingCount}</span>
          {offlineQueueRef.current.length > 0 && (
            <span className="text-yellow-400">
              {offlineQueueRef.current.length} queued offline
            </span>
          )}
        </div>
      )}

      {/* Primary action */}
      {state === "ready" && (
        <Button size="lg" className="w-full h-14 text-base" onClick={() => void startTracking()}>
          <Navigation className="h-5 w-5 mr-2" />
          Start Tracking
        </Button>
      )}

      {state === "tracking" && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-center gap-2 text-green-500 text-sm font-medium">
            <span className="relative flex h-3 w-3">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-3 w-3 bg-green-500" />
            </span>
            Tracking active
          </div>

          <Button
            variant="outline"
            className="w-full"
            onClick={() => void handleManualDelivery()}
          >
            <CheckCircle className="h-4 w-4 mr-2 text-green-500" />
            Confirm Delivery Manually
          </Button>

          <Button
            variant="ghost"
            size="sm"
            className="w-full text-muted-foreground"
            onClick={() => {
              stopTracking();
              setState("ready");
            }}
          >
            Pause Tracking
          </Button>
        </div>
      )}

      {/* Offline disclaimer */}
      {!isOnline && state === "tracking" && (
        <Alert className="border-yellow-400/50 bg-yellow-400/10">
          <WifiOff className="h-4 w-4 text-yellow-400" />
          <AlertDescription className="text-yellow-300 text-xs">
            You're offline. Location pings are queued locally and will be sent when you
            reconnect.
          </AlertDescription>
        </Alert>
      )}

      {/* Footer branding */}
      <p className="text-center text-xs text-muted-foreground mt-auto pb-4">
        Placeware Logistics · Rider App
      </p>
    </div>
  );
}
