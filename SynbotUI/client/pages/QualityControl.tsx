import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ShieldCheck, Thermometer, AlertTriangle, Package, FlaskConical,
  Loader2, Plus, RefreshCw, CheckCircle2, XCircle, ChevronDown,
  ChevronRight, Lock, ClipboardList, Activity, BarChart3, Bell,
  Siren, Clock, FileWarning, X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api-client";
import { motion } from "framer-motion";
import { motionVariants, motionTransitions } from "@/lib/motion";

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------

interface QcKpi {
  expiring_critical_30d: number;
  open_deviations: number;
  temp_alerts_today: number;
  nafdac_pending: number;
  open_recalls: number;
}

interface RecentDeviation {
  id: string;
  deviation_id?: string;
  classification: string;
  observation: string;
  status: string;
  created_at: string;
}

interface ExpiryItem {
  id: string;
  product_name: string;
  sku?: string;
  quantity: number;
  expiry_date: string;
  days_remaining: number;
  location?: string;
}

interface ExpiryBuckets {
  expired: ExpiryItem[];
  critical: ExpiryItem[];
  high: ExpiryItem[];
  medium: ExpiryItem[];
}

interface TempLog {
  id: string;
  location: string;
  reading_celsius: number;
  min_threshold?: number;
  max_threshold?: number;
  log_session: string;
  is_deviation: boolean;
  deviation_escalated: boolean;
  logged_by: string;
  logged_at: string;
  notes?: string;
}

interface Deviation {
  id: string;
  deviation_id: string;
  classification: "minor" | "major" | "critical";
  trigger_type: string;
  observation: string;
  status: string;
  responsible_department: string;
  responsible_person?: string;
  capa_actions?: object[];
  resolution?: string;
  created_at: string;
}

interface NafdacBatch {
  id: string;
  batch_number: string;
  product_name: string;
  nafdac_reg_number?: string;
  supplier?: string;
  status: "pending" | "approved" | "rejected" | "suspended";
  dispatch_blocked: boolean;
  valid_from?: string;
  valid_to?: string;
  certificate_ref?: string;
  created_at: string;
}

interface Recall {
  id: string;
  recall_id: string;
  batch_number: string;
  product_name: string;
  recall_reason: string;
  scope: "voluntary" | "mandatory";
  status: string;
  regulatory_authority?: string;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

const CLASS_COLORS: Record<string, string> = {
  minor:    "bg-yellow-100 text-yellow-700",
  major:    "bg-orange-100 text-orange-700",
  critical: "bg-red-100 text-red-700",
};

const STATUS_COLORS: Record<string, string> = {
  open:               "bg-blue-100 text-blue-700",
  under_investigation:"bg-purple-100 text-purple-700",
  escalated:          "bg-orange-100 text-orange-700",
  closed:             "bg-green-100 text-green-700",
  pending:            "bg-yellow-100 text-yellow-700",
  approved:           "bg-green-100 text-green-700",
  rejected:           "bg-red-100 text-red-700",
  suspended:          "bg-gray-100 text-gray-600",
  initiated:          "bg-blue-100 text-blue-700",
  in_progress:        "bg-purple-100 text-purple-700",
  completed:          "bg-green-100 text-green-700",
};

function Pill({ label, colorCls }: { label: string; colorCls?: string }) {
  const cls = colorCls ?? "bg-gray-100 text-gray-600";
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {label}
    </span>
  );
}

function fmtDt(iso: string) {
  return new Date(iso).toLocaleString("en-NG", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// Tab 1: Dashboard
// ---------------------------------------------------------------------------

function DashboardTab() {
  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["qc-dashboard"],
    queryFn: () => api.qc.dashboard(),
    refetchInterval: 60_000,
  });

  const kpi: QcKpi = data?.kpi ?? {
    expiring_critical_30d: 0,
    open_deviations: 0,
    temp_alerts_today: 0,
    nafdac_pending: 0,
    open_recalls: 0,
  };
  const recent: RecentDeviation[] = data?.recent_deviations ?? [];

  const kpiCards = [
    {
      label: "Expiring ≤30d",
      value: kpi.expiring_critical_30d,
      icon: <Package className="h-5 w-5 text-orange-500" />,
      alert: kpi.expiring_critical_30d > 0,
    },
    {
      label: "Open Deviations",
      value: kpi.open_deviations,
      icon: <FileWarning className="h-5 w-5 text-yellow-500" />,
      alert: kpi.open_deviations > 0,
    },
    {
      label: "Temp Alerts Today",
      value: kpi.temp_alerts_today,
      icon: <Thermometer className="h-5 w-5 text-red-500" />,
      alert: kpi.temp_alerts_today > 0,
    },
    {
      label: "NAFDAC Pending",
      value: kpi.nafdac_pending,
      icon: <ClipboardList className="h-5 w-5 text-purple-500" />,
      alert: kpi.nafdac_pending > 0,
    },
    {
      label: "Open Recalls",
      value: kpi.open_recalls,
      icon: <Siren className="h-5 w-5 text-rose-600" />,
      alert: kpi.open_recalls > 0,
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">QC Overview</h2>
        <Button variant="ghost" size="sm" onClick={() => refetch()} disabled={isFetching}>
          <RefreshCw className={`h-4 w-4 mr-1 ${isFetching ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-32">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
            {kpiCards.map((k) => (
              <motion.div key={k.label} {...motionVariants.cardEnter} transition={motionTransitions.standard}>
                <Card className={k.alert ? "border-orange-300" : ""}>
                  <CardContent className="pt-5 pb-4 flex flex-col items-center gap-2 text-center">
                    {k.icon}
                    <div className={`text-3xl font-bold ${k.alert ? "text-orange-600" : "text-foreground"}`}>
                      {k.value}
                    </div>
                    <p className="text-xs text-muted-foreground leading-tight">{k.label}</p>
                  </CardContent>
                </Card>
              </motion.div>
            ))}
          </div>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <Activity className="h-4 w-4" /> Recent Deviations
              </CardTitle>
            </CardHeader>
            <CardContent>
              {recent.length === 0 ? (
                <p className="text-sm text-muted-foreground py-4 text-center">No recent deviations.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-muted-foreground border-b">
                      <th className="text-left pb-2 font-medium">ID</th>
                      <th className="text-left pb-2 font-medium">Classification</th>
                      <th className="text-left pb-2 font-medium">Observation</th>
                      <th className="text-left pb-2 font-medium">Status</th>
                      <th className="text-left pb-2 font-medium">Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recent.map((r) => (
                      <tr key={r.id} className="border-b last:border-0">
                        <td className="py-2 font-mono text-xs">{r.deviation_id ?? r.id.slice(0, 8)}</td>
                        <td className="py-2">
                          <Pill label={r.classification} colorCls={CLASS_COLORS[r.classification]} />
                        </td>
                        <td className="py-2 max-w-xs truncate text-muted-foreground">{r.observation}</td>
                        <td className="py-2">
                          <Pill label={r.status} colorCls={STATUS_COLORS[r.status]} />
                        </td>
                        <td className="py-2 text-muted-foreground whitespace-nowrap">{fmtDt(r.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab 2: Expiry Alerts
// ---------------------------------------------------------------------------

function ExpiryTab() {
  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["qc-expiry"],
    queryFn: () => api.qc.expiryAlerts(),
    refetchInterval: 120_000,
  });

  const buckets: ExpiryBuckets = data?.buckets ?? {
    expired: [], critical: [], high: [], medium: [],
  };

  const bucketConfig = [
    { key: "expired" as const, label: "Expired",         color: "border-red-500    bg-red-50",     badge: "bg-red-100 text-red-700",    action: "Quarantine" },
    { key: "critical" as const, label: "Critical (≤30d)", color: "border-orange-500 bg-orange-50",  badge: "bg-orange-100 text-orange-700", action: "Quarantine" },
    { key: "high" as const,    label: "High (≤60d)",      color: "border-amber-500  bg-amber-50",   badge: "bg-amber-100 text-amber-700",  action: "Promote" },
    { key: "medium" as const,  label: "Monitor (≤90d)",   color: "border-yellow-400 bg-yellow-50",  badge: "bg-yellow-100 text-yellow-700", action: "Monitor" },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Expiry Alerts</h2>
        <Button variant="ghost" size="sm" onClick={() => refetch()} disabled={isFetching}>
          <RefreshCw className={`h-4 w-4 mr-1 ${isFetching ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-32">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {bucketConfig.map(({ key, label, color, badge, action }) => {
            const items = buckets[key];
            return (
              <motion.div key={key} {...motionVariants.cardEnter} transition={motionTransitions.standard}>
                <Card className={`border-l-4 ${color.split(" ")[0]}`}>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm flex items-center justify-between">
                      <span>{label}</span>
                      <Badge variant="outline">{items.length}</Badge>
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    {items.length === 0 ? (
                      <p className="text-sm text-muted-foreground py-2">None</p>
                    ) : (
                      items.map((item) => (
                        <div key={item.id} className={`rounded-md p-3 text-sm space-y-1 ${color.split(" ")[1]} border`}>
                          <div className="flex items-center justify-between">
                            <span className="font-medium truncate max-w-[180px]">{item.product_name}</span>
                            <Pill label={action} colorCls={badge} />
                          </div>
                          <div className="flex gap-4 text-xs text-muted-foreground flex-wrap">
                            {item.sku && <span>SKU: {item.sku}</span>}
                            <span>Qty: <strong>{item.quantity}</strong></span>
                            <span>
                              {item.days_remaining <= 0
                                ? <span className="text-red-600 font-semibold">Expired</span>
                                : <span>{item.days_remaining}d left</span>
                              }
                            </span>
                            {item.location && <span>📍 {item.location}</span>}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            Expires: {new Date(item.expiry_date).toLocaleDateString("en-NG", { day: "2-digit", month: "short", year: "numeric" })}
                          </div>
                        </div>
                      ))
                    )}
                  </CardContent>
                </Card>
              </motion.div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab 3: Temperature Monitoring
// ---------------------------------------------------------------------------

function TemperatureTab() {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const [showLogForm, setShowLogForm] = useState(false);
  const [escalateTarget, setEscalateTarget] = useState<TempLog | null>(null);
  const [filterDevOnly, setFilterDevOnly] = useState(false);
  const [filterLocation, setFilterLocation] = useState("");

  // Log form state
  const [logLocation, setLogLocation]   = useState("");
  const [logReading,  setLogReading]    = useState("");
  const [logSession,  setLogSession]    = useState<"morning" | "midday" | "evening" | "ad_hoc">("morning");
  const [logBy,       setLogBy]         = useState("");
  const [logNotes,    setLogNotes]      = useState("");
  const [logMin,      setLogMin]        = useState("");
  const [logMax,      setLogMax]        = useState("");

  // Escalation state
  const [escalatedTo,    setEscalatedTo]    = useState("");
  const [escalationNote, setEscalationNote] = useState("");

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["qc-temp-logs", filterLocation, filterDevOnly],
    queryFn: () => api.qc.listTemperatureLogs({
      location:       filterLocation || undefined,
      deviations_only: filterDevOnly || undefined,
    }),
    refetchInterval: 30_000,
  });

  const logs: TempLog[] = data?.logs ?? data ?? [];

  const logMut = useMutation({
    mutationFn: () => api.qc.logTemperature({
      location:       logLocation.trim(),
      reading_celsius: parseFloat(logReading),
      min_threshold:  logMin ? parseFloat(logMin) : undefined,
      max_threshold:  logMax ? parseFloat(logMax) : undefined,
      log_session:    logSession,
      logged_by:      logBy.trim(),
      notes:          logNotes.trim() || undefined,
    }),
    onSuccess: () => {
      toast({ title: "Temperature logged" });
      setShowLogForm(false);
      setLogLocation(""); setLogReading(""); setLogBy(""); setLogNotes("");
      setLogMin(""); setLogMax("");
      void queryClient.invalidateQueries({ queryKey: ["qc-temp-logs"] });
      void queryClient.invalidateQueries({ queryKey: ["qc-dashboard"] });
    },
    onError: (e: any) => toast({ title: "Error", description: e?.message ?? "Failed to log", variant: "destructive" }),
  });

  const escalateMut = useMutation({
    mutationFn: (log: TempLog) => api.qc.escalateDeviation(log.id, {
      escalated_to:      escalatedTo.trim(),
      escalation_notes:  escalationNote.trim() || undefined,
    }),
    onSuccess: () => {
      toast({ title: "Deviation escalated" });
      setEscalateTarget(null);
      setEscalatedTo(""); setEscalationNote("");
      void queryClient.invalidateQueries({ queryKey: ["qc-temp-logs"] });
    },
    onError: (e: any) => toast({ title: "Error", description: e?.message ?? "Escalation failed", variant: "destructive" }),
  });

  const SESSION_LABELS: Record<string, string> = {
    morning: "AM", midday: "Midday", evening: "PM", ad_hoc: "Ad-hoc",
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-semibold">Cold-Chain Temperature Logs</h2>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={`h-4 w-4 mr-1 ${isFetching ? "animate-spin" : ""}`} />
          </Button>
          <Button size="sm" onClick={() => setShowLogForm((p) => !p)}>
            <Plus className="h-4 w-4 mr-1" /> Log Reading
          </Button>
        </div>
      </div>

      {/* Inline log form */}
      {showLogForm && (
        <motion.div {...motionVariants.cardEnter} transition={motionTransitions.standard}>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">New Temperature Reading</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Location *</label>
                  <Input placeholder="e.g. Cold Room A" value={logLocation} onChange={(e) => setLogLocation(e.target.value)} />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Reading (°C) *</label>
                  <Input type="number" step="0.1" placeholder="2.4" value={logReading} onChange={(e) => setLogReading(e.target.value)} />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Session</label>
                  <Select value={logSession} onValueChange={(v) => setLogSession(v as typeof logSession)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="morning">Morning</SelectItem>
                      <SelectItem value="midday">Midday</SelectItem>
                      <SelectItem value="evening">Evening</SelectItem>
                      <SelectItem value="ad_hoc">Ad-hoc</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Min Threshold (°C)</label>
                  <Input type="number" step="0.1" placeholder="2.0" value={logMin} onChange={(e) => setLogMin(e.target.value)} />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Max Threshold (°C)</label>
                  <Input type="number" step="0.1" placeholder="8.0" value={logMax} onChange={(e) => setLogMax(e.target.value)} />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Logged By *</label>
                  <Input placeholder="Staff name" value={logBy} onChange={(e) => setLogBy(e.target.value)} />
                </div>
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Notes</label>
                <Textarea placeholder="Optional notes…" rows={2} value={logNotes} onChange={(e) => setLogNotes(e.target.value)} />
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  disabled={logMut.isPending || !logLocation.trim() || !logReading || !logBy.trim()}
                  onClick={() => logMut.mutate()}
                >
                  {logMut.isPending && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
                  Submit
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setShowLogForm(false)}>Cancel</Button>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <Input
          className="max-w-[200px] h-8 text-sm"
          placeholder="Filter by location…"
          value={filterLocation}
          onChange={(e) => setFilterLocation(e.target.value)}
        />
        <label className="flex items-center gap-1.5 text-sm cursor-pointer select-none">
          <input
            type="checkbox"
            checked={filterDevOnly}
            onChange={(e) => setFilterDevOnly(e.target.checked)}
            className="rounded"
          />
          Deviations only
        </label>
      </div>

      {/* Logs table */}
      {isLoading ? (
        <div className="flex items-center justify-center h-32">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <Card>
          <CardContent className="p-0 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-muted-foreground text-xs">
                  <th className="text-left p-3 font-medium">Location</th>
                  <th className="text-right p-3 font-medium">°C</th>
                  <th className="text-left p-3 font-medium">Session</th>
                  <th className="text-left p-3 font-medium">Logged By</th>
                  <th className="text-left p-3 font-medium">Time</th>
                  <th className="text-left p-3 font-medium">Status</th>
                  <th className="p-3" />
                </tr>
              </thead>
              <tbody>
                {logs.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="text-center py-8 text-muted-foreground">No temperature logs found.</td>
                  </tr>
                ) : (
                  logs.map((log) => (
                    <tr
                      key={log.id}
                      className={`border-b last:border-0 ${log.is_deviation ? "bg-red-50" : ""}`}
                    >
                      <td className="p-3 font-medium">{log.location}</td>
                      <td className="p-3 text-right font-mono font-semibold">
                        <span className={log.is_deviation ? "text-red-600" : ""}>{log.reading_celsius}°C</span>
                      </td>
                      <td className="p-3">{SESSION_LABELS[log.log_session] ?? log.log_session}</td>
                      <td className="p-3 text-muted-foreground">{log.logged_by}</td>
                      <td className="p-3 text-muted-foreground whitespace-nowrap">{fmtDt(log.logged_at)}</td>
                      <td className="p-3">
                        {log.is_deviation ? (
                          log.deviation_escalated ? (
                            <Pill label="Escalated" colorCls="bg-orange-100 text-orange-700" />
                          ) : (
                            <Pill label="Deviation" colorCls="bg-red-100 text-red-700" />
                          )
                        ) : (
                          <Pill label="Normal" colorCls="bg-green-100 text-green-700" />
                        )}
                      </td>
                      <td className="p-3 text-right">
                        {log.is_deviation && !log.deviation_escalated && (
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-7 text-xs"
                            onClick={() => setEscalateTarget(log)}
                          >
                            Escalate
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {/* Escalation dialog */}
      <Dialog open={!!escalateTarget} onOpenChange={(o) => { if (!o) setEscalateTarget(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Escalate Temperature Deviation</DialogTitle>
          </DialogHeader>
          {escalateTarget && (
            <div className="space-y-3 text-sm">
              <div className="rounded-md bg-muted p-3 space-y-1">
                <div><span className="font-medium">Location:</span> {escalateTarget.location}</div>
                <div><span className="font-medium">Reading:</span> {escalateTarget.reading_celsius}°C</div>
                <div><span className="font-medium">Session:</span> {escalateTarget.log_session}</div>
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Escalate To *</label>
                <Input placeholder="Manager / QA Lead name" value={escalatedTo} onChange={(e) => setEscalatedTo(e.target.value)} />
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Notes</label>
                <Textarea placeholder="Escalation notes…" rows={3} value={escalationNote} onChange={(e) => setEscalationNote(e.target.value)} />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setEscalateTarget(null)}>Cancel</Button>
            <Button
              disabled={!escalatedTo.trim() || escalateMut.isPending}
              onClick={() => escalateTarget && escalateMut.mutate(escalateTarget)}
            >
              {escalateMut.isPending && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
              Confirm Escalation
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab 4: CAPA / Deviations
// ---------------------------------------------------------------------------

const TRIGGER_TYPES = [
  "temperature_excursion", "expiry_risk", "batch_rejection",
  "supplier_complaint", "internal_audit", "customer_complaint",
  "equipment_failure", "process_deviation", "other",
];

function CapaTab() {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const [showForm, setShowForm]               = useState(false);
  const [selected, setSelected]               = useState<Deviation | null>(null);
  const [showCloseDialog, setShowCloseDialog] = useState(false);
  const [filterStatus, setFilterStatus]       = useState("");
  const [filterClass,  setFilterClass]        = useState("");

  // Create form
  const [cls,        setCls]        = useState<"minor" | "major" | "critical">("minor");
  const [trigger,    setTrigger]    = useState("");
  const [obs,        setObs]        = useState("");
  const [dept,       setDept]       = useState("");
  const [person,     setPerson]     = useState("");
  const [impact,     setImpact]     = useState("");
  const [recoms,     setRecoms]     = useState("");
  const [capaText,   setCapaText]   = useState("");   // free-text CAPA summary

  // Update form
  const [updStatus,  setUpdStatus]  = useState("");
  const [updPerson,  setUpdPerson]  = useState("");
  const [updCapaText,setUpdCapaText] = useState("");

  // Close form
  const [resolution, setResolution] = useState("");

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["qc-deviations", filterStatus, filterClass],
    queryFn: () => api.qc.listDeviations({
      status:         filterStatus || undefined,
      classification: filterClass  || undefined,
    }),
  });

  const deviations: Deviation[] = data?.deviations ?? data ?? [];

  const createMut = useMutation({
    mutationFn: () => api.qc.createDeviation({
      classification:      cls,
      trigger_type:        trigger,
      observation:         obs.trim(),
      responsible_department: dept.trim(),
      responsible_person:  person.trim() || undefined,
      impact_assessment:   impact.trim() || undefined,
      recommendations:     recoms.trim() || undefined,
      capa_actions:        capaText.trim() ? [{ description: capaText.trim() }] : undefined,
    }),
    onSuccess: () => {
      toast({ title: "Deviation report created" });
      setShowForm(false);
      setCls("minor"); setTrigger(""); setObs(""); setDept(""); setPerson(""); setImpact(""); setRecoms(""); setCapaText("");
      void queryClient.invalidateQueries({ queryKey: ["qc-deviations"] });
      void queryClient.invalidateQueries({ queryKey: ["qc-dashboard"] });
    },
    onError: (e: any) => toast({ title: "Error", description: e?.message, variant: "destructive" }),
  });

  const updateMut = useMutation({
    mutationFn: (dev: Deviation) => api.qc.updateDeviation(dev.id, {
      status:             updStatus || undefined,
      responsible_person: updPerson.trim() || undefined,
      capa_actions:       updCapaText.trim() ? [{ description: updCapaText.trim() }] : undefined,
    }),
    onSuccess: () => {
      toast({ title: "Deviation updated" });
      setSelected(null);
      void queryClient.invalidateQueries({ queryKey: ["qc-deviations"] });
    },
    onError: (e: any) => toast({ title: "Error", description: e?.message, variant: "destructive" }),
  });

  const closeMut = useMutation({
    mutationFn: (dev: Deviation) => api.qc.closeDeviation(dev.id, { resolution: resolution.trim() }),
    onSuccess: () => {
      toast({ title: "Deviation closed" });
      setShowCloseDialog(false);
      setSelected(null);
      setResolution("");
      void queryClient.invalidateQueries({ queryKey: ["qc-deviations"] });
      void queryClient.invalidateQueries({ queryKey: ["qc-dashboard"] });
    },
    onError: (e: any) => toast({ title: "Error", description: e?.message, variant: "destructive" }),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-semibold">CAPA & Deviation Reports</h2>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
          </Button>
          <Button size="sm" onClick={() => setShowForm((p) => !p)}>
            <Plus className="h-4 w-4 mr-1" /> New Deviation
          </Button>
        </div>
      </div>

      {/* Create form */}
      {showForm && (
        <motion.div {...motionVariants.cardEnter} transition={motionTransitions.standard}>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">New Deviation Report</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Classification *</label>
                  <Select value={cls} onValueChange={(v) => setCls(v as typeof cls)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="minor">Minor</SelectItem>
                      <SelectItem value="major">Major</SelectItem>
                      <SelectItem value="critical">Critical</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Trigger Type *</label>
                  <Select value={trigger} onValueChange={setTrigger}>
                    <SelectTrigger><SelectValue placeholder="Select…" /></SelectTrigger>
                    <SelectContent>
                      {TRIGGER_TYPES.map((t) => (
                        <SelectItem key={t} value={t}>{t.replace(/_/g, " ")}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Responsible Dept *</label>
                  <Input placeholder="e.g. Quality Assurance" value={dept} onChange={(e) => setDept(e.target.value)} />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Responsible Person</label>
                  <Input placeholder="Optional" value={person} onChange={(e) => setPerson(e.target.value)} />
                </div>
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Observation *</label>
                <Textarea placeholder="Describe what was observed…" rows={3} value={obs} onChange={(e) => setObs(e.target.value)} />
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Impact Assessment</label>
                  <Textarea placeholder="Potential impact…" rows={2} value={impact} onChange={(e) => setImpact(e.target.value)} />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Recommendations</label>
                  <Textarea placeholder="Recommended actions…" rows={2} value={recoms} onChange={(e) => setRecoms(e.target.value)} />
                </div>
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Initial CAPA Action</label>
                <Input placeholder="Initial corrective/preventive action…" value={capaText} onChange={(e) => setCapaText(e.target.value)} />
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  disabled={createMut.isPending || !trigger || !obs.trim() || !dept.trim()}
                  onClick={() => createMut.mutate()}
                >
                  {createMut.isPending && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
                  Submit
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setShowForm(false)}>Cancel</Button>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <Select value={filterStatus || "__all__"} onValueChange={(v) => setFilterStatus(v === "__all__" ? "" : v)}>
          <SelectTrigger className="w-[150px] h-8 text-sm"><SelectValue placeholder="All statuses" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">All statuses</SelectItem>
            <SelectItem value="open">Open</SelectItem>
            <SelectItem value="under_investigation">Under Investigation</SelectItem>
            <SelectItem value="escalated">Escalated</SelectItem>
            <SelectItem value="closed">Closed</SelectItem>
          </SelectContent>
        </Select>
        <Select value={filterClass || "__all__"} onValueChange={(v) => setFilterClass(v === "__all__" ? "" : v)}>
          <SelectTrigger className="w-[150px] h-8 text-sm"><SelectValue placeholder="All classes" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">All classes</SelectItem>
            <SelectItem value="minor">Minor</SelectItem>
            <SelectItem value="major">Major</SelectItem>
            <SelectItem value="critical">Critical</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* List */}
      {isLoading ? (
        <div className="flex items-center justify-center h-32">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <div className="space-y-3">
          {deviations.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">No deviations found.</div>
          ) : (
            deviations.map((dev) => (
              <motion.div key={dev.id} {...motionVariants.cardEnter} transition={motionTransitions.standard}>
                <Card
                  className="cursor-pointer hover:shadow-md transition-shadow"
                  onClick={() => {
                    setSelected(dev);
                    setUpdStatus(dev.status);
                    setUpdPerson(dev.responsible_person ?? "");
                    setUpdCapaText("");
                  }}
                >
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-1 flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-mono text-xs text-muted-foreground">{dev.deviation_id}</span>
                          <Pill label={dev.classification} colorCls={CLASS_COLORS[dev.classification]} />
                          <Pill label={dev.status} colorCls={STATUS_COLORS[dev.status]} />
                        </div>
                        <p className="text-sm font-medium truncate">{dev.observation}</p>
                        <div className="flex gap-3 text-xs text-muted-foreground flex-wrap">
                          <span>Dept: {dev.responsible_department}</span>
                          {dev.responsible_person && <span>By: {dev.responsible_person}</span>}
                          <span>{fmtDt(dev.created_at)}</span>
                        </div>
                      </div>
                      <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            ))
          )}
        </div>
      )}

      {/* Detail / Update dialog */}
      <Dialog open={!!selected && !showCloseDialog} onOpenChange={(o) => { if (!o) setSelected(null); }}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <span>{selected?.deviation_id}</span>
              {selected && <Pill label={selected.classification} colorCls={CLASS_COLORS[selected.classification]} />}
            </DialogTitle>
          </DialogHeader>
          {selected && (
            <div className="space-y-4 text-sm">
              <div className="rounded-md bg-muted p-3 space-y-1">
                <div><span className="font-medium">Trigger:</span> {selected.trigger_type.replace(/_/g, " ")}</div>
                <div><span className="font-medium">Department:</span> {selected.responsible_department}</div>
                <div className="leading-relaxed"><span className="font-medium">Observation:</span> {selected.observation}</div>
              </div>
              <Separator />
              <div className="space-y-3">
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Update Status</label>
                  <Select value={updStatus} onValueChange={setUpdStatus}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="open">Open</SelectItem>
                      <SelectItem value="under_investigation">Under Investigation</SelectItem>
                      <SelectItem value="escalated">Escalated</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Responsible Person</label>
                  <Input value={updPerson} onChange={(e) => setUpdPerson(e.target.value)} placeholder="Name…" />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Add CAPA Action</label>
                  <Input value={updCapaText} onChange={(e) => setUpdCapaText(e.target.value)} placeholder="Describe CAPA step…" />
                </div>
              </div>
            </div>
          )}
          <DialogFooter className="gap-2">
            <Button
              variant="destructive"
              size="sm"
              disabled={selected?.status === "closed"}
              onClick={() => setShowCloseDialog(true)}
            >
              Close Deviation
            </Button>
            <Button
              size="sm"
              disabled={updateMut.isPending}
              onClick={() => selected && updateMut.mutate(selected)}
            >
              {updateMut.isPending && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Close dialog */}
      <Dialog open={showCloseDialog} onOpenChange={(o) => { if (!o) setShowCloseDialog(false); }}>
        <DialogContent>
          <DialogHeader><DialogTitle>Close Deviation {selected?.deviation_id}</DialogTitle></DialogHeader>
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Resolution *</label>
            <Textarea
              rows={4}
              placeholder="Describe how this deviation was resolved…"
              value={resolution}
              onChange={(e) => setResolution(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setShowCloseDialog(false)}>Cancel</Button>
            <Button
              disabled={!resolution.trim() || closeMut.isPending}
              onClick={() => selected && closeMut.mutate(selected)}
            >
              {closeMut.isPending && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
              Confirm Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab 5: NAFDAC & Recalls
// ---------------------------------------------------------------------------

function NafdacTab() {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  // Sub-section: "batches" | "recalls"
  const [sub, setSub] = useState<"batches" | "recalls">("batches");

  // Batch form
  const [showBatchForm,  setShowBatchForm]  = useState(false);
  const [batchNum,       setBatchNum]       = useState("");
  const [productName,    setProductName]    = useState("");
  const [nafdacReg,      setNafdacReg]      = useState("");
  const [supplier,       setSupplier]       = useState("");
  const [validFrom,      setValidFrom]      = useState("");
  const [validTo,        setValidTo]        = useState("");
  const [certRef,        setCertRef]        = useState("");
  const [batchNotes,     setBatchNotes]     = useState("");

  // Batch approval/rejection dialog
  const [approveTarget, setApproveTarget] = useState<NafdacBatch | null>(null);
  const [rejectTarget,  setRejectTarget]  = useState<NafdacBatch | null>(null);
  const [approveNotes,  setApproveNotes]  = useState("");
  const [rejectReason,  setRejectReason]  = useState("");

  // Recall form
  const [showRecallForm, setShowRecallForm] = useState(false);
  const [rBatch,         setRBatch]         = useState("");
  const [rProduct,       setRProduct]       = useState("");
  const [rReason,        setRReason]        = useState("");
  const [rScope,         setRScope]         = useState<"voluntary" | "mandatory">("voluntary");
  const [rAuthority,     setRAuthority]     = useState("");

  // Recall status update dialog
  const [recallUpdateTarget, setRecallUpdateTarget] = useState<Recall | null>(null);
  const [newRecallStatus,    setNewRecallStatus]     = useState<Recall["status"]>("in_progress");
  const [recallNotes,        setRecallNotes]         = useState("");

  // Filter
  const [batchStatusFilter, setBatchStatusFilter] = useState("");
  const [recallStatusFilter, setRecallStatusFilter] = useState("");

  const batchQuery = useQuery({
    queryKey: ["qc-batches", batchStatusFilter],
    queryFn: () => api.qc.listBatches({ status: batchStatusFilter || undefined }),
    enabled: sub === "batches",
  });

  const recallQuery = useQuery({
    queryKey: ["qc-recalls", recallStatusFilter],
    queryFn: () => api.qc.listRecalls({ status: recallStatusFilter || undefined }),
    enabled: sub === "recalls",
  });

  const batches: NafdacBatch[] = batchQuery.data?.batches ?? batchQuery.data ?? [];
  const recalls: Recall[]      = recallQuery.data?.recalls ?? recallQuery.data ?? [];

  // Mutations
  const registerBatchMut = useMutation({
    mutationFn: () => api.qc.registerBatch({
      batch_number: batchNum.trim(),
      product_name: productName.trim(),
      nafdac_reg_number: nafdacReg.trim() || undefined,
      supplier:     supplier.trim() || undefined,
      valid_from:   validFrom || undefined,
      valid_to:     validTo   || undefined,
      certificate_ref: certRef.trim() || undefined,
      notes:        batchNotes.trim() || undefined,
    }),
    onSuccess: () => {
      toast({ title: "Batch registered — pending NAFDAC approval" });
      setShowBatchForm(false);
      setBatchNum(""); setProductName(""); setNafdacReg(""); setSupplier("");
      setValidFrom(""); setValidTo(""); setCertRef(""); setBatchNotes("");
      void queryClient.invalidateQueries({ queryKey: ["qc-batches"] });
      void queryClient.invalidateQueries({ queryKey: ["qc-dashboard"] });
    },
    onError: (e: any) => toast({ title: "Error", description: e?.message, variant: "destructive" }),
  });

  const approveMut = useMutation({
    mutationFn: (b: NafdacBatch) => api.qc.approveBatch(b.id, {
      valid_from: validFrom || undefined,
      valid_to:   validTo   || undefined,
      notes:      approveNotes.trim() || undefined,
    }),
    onSuccess: () => {
      toast({ title: "Batch approved — dispatch unblocked" });
      setApproveTarget(null); setApproveNotes("");
      void queryClient.invalidateQueries({ queryKey: ["qc-batches"] });
      void queryClient.invalidateQueries({ queryKey: ["qc-dashboard"] });
    },
    onError: (e: any) => toast({ title: "Error", description: e?.message, variant: "destructive" }),
  });

  const rejectMut = useMutation({
    mutationFn: (b: NafdacBatch) => api.qc.rejectBatch(b.id, {
      rejection_reason: rejectReason.trim(),
      notes:            batchNotes.trim() || undefined,
    }),
    onSuccess: () => {
      toast({ title: "Batch rejected" });
      setRejectTarget(null); setRejectReason("");
      void queryClient.invalidateQueries({ queryKey: ["qc-batches"] });
    },
    onError: (e: any) => toast({ title: "Error", description: e?.message, variant: "destructive" }),
  });

  const initiateRecallMut = useMutation({
    mutationFn: () => api.qc.initiateRecall({
      batch_number: rBatch.trim(),
      product_name: rProduct.trim(),
      recall_reason: rReason.trim(),
      scope:        rScope,
      regulatory_authority: rAuthority.trim() || undefined,
    }),
    onSuccess: () => {
      toast({ title: "Recall initiated" });
      setShowRecallForm(false);
      setRBatch(""); setRProduct(""); setRReason(""); setRAuthority("");
      void queryClient.invalidateQueries({ queryKey: ["qc-recalls"] });
      void queryClient.invalidateQueries({ queryKey: ["qc-dashboard"] });
    },
    onError: (e: any) => toast({ title: "Error", description: e?.message, variant: "destructive" }),
  });

  const updateRecallMut = useMutation({
    mutationFn: (r: Recall) => api.qc.updateRecallStatus(r.id, {
      status: newRecallStatus,
      notes:  recallNotes.trim() || undefined,
    }),
    onSuccess: () => {
      toast({ title: "Recall status updated" });
      setRecallUpdateTarget(null); setRecallNotes("");
      void queryClient.invalidateQueries({ queryKey: ["qc-recalls"] });
    },
    onError: (e: any) => toast({ title: "Error", description: e?.message, variant: "destructive" }),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-semibold">NAFDAC & Recalls</h2>
        {/* Sub-section toggle */}
        <div className="flex rounded-md border overflow-hidden text-sm">
          {(["batches", "recalls"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setSub(s)}
              className={`px-4 py-1.5 capitalize transition-colors ${
                sub === s ? "bg-primary text-primary-foreground" : "bg-background hover:bg-muted"
              }`}
            >
              {s === "batches" ? "Batch Registry" : "Recalls"}
            </button>
          ))}
        </div>
      </div>

      {/* ---- BATCH REGISTRY ---- */}
      {sub === "batches" && (
        <div className="space-y-4">
          <div className="flex items-center gap-2 flex-wrap">
            <Select value={batchStatusFilter || "__all__"} onValueChange={(v) => setBatchStatusFilter(v === "__all__" ? "" : v)}>
              <SelectTrigger className="w-[150px] h-8 text-sm"><SelectValue placeholder="All statuses" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">All statuses</SelectItem>
                <SelectItem value="pending">Pending</SelectItem>
                <SelectItem value="approved">Approved</SelectItem>
                <SelectItem value="rejected">Rejected</SelectItem>
                <SelectItem value="suspended">Suspended</SelectItem>
              </SelectContent>
            </Select>
            <Button variant="ghost" size="sm" onClick={() => batchQuery.refetch()} disabled={batchQuery.isFetching}>
              <RefreshCw className={`h-4 w-4 ${batchQuery.isFetching ? "animate-spin" : ""}`} />
            </Button>
            <Button size="sm" onClick={() => setShowBatchForm((p) => !p)}>
              <Plus className="h-4 w-4 mr-1" /> Register Batch
            </Button>
          </div>

          {/* Register form */}
          {showBatchForm && (
            <motion.div {...motionVariants.cardEnter} transition={motionTransitions.standard}>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">Register NAFDAC Batch</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">Batch Number *</label>
                      <Input placeholder="e.g. BTH-2026-001" value={batchNum} onChange={(e) => setBatchNum(e.target.value)} />
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">Product Name *</label>
                      <Input placeholder="Product name" value={productName} onChange={(e) => setProductName(e.target.value)} />
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">NAFDAC Reg. No.</label>
                      <Input placeholder="A4-0000" value={nafdacReg} onChange={(e) => setNafdacReg(e.target.value)} />
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">Supplier</label>
                      <Input placeholder="Supplier name" value={supplier} onChange={(e) => setSupplier(e.target.value)} />
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">Valid From</label>
                      <Input type="date" value={validFrom} onChange={(e) => setValidFrom(e.target.value)} />
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">Valid To</label>
                      <Input type="date" value={validTo} onChange={(e) => setValidTo(e.target.value)} />
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">Certificate Ref.</label>
                      <Input placeholder="CERT-XXX" value={certRef} onChange={(e) => setCertRef(e.target.value)} />
                    </div>
                  </div>
                  <div>
                    <label className="text-xs text-muted-foreground mb-1 block">Notes</label>
                    <Textarea rows={2} value={batchNotes} onChange={(e) => setBatchNotes(e.target.value)} placeholder="Optional…" />
                  </div>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      disabled={registerBatchMut.isPending || !batchNum.trim() || !productName.trim()}
                      onClick={() => registerBatchMut.mutate()}
                    >
                      {registerBatchMut.isPending && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
                      Register
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => setShowBatchForm(false)}>Cancel</Button>
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          )}

          {/* Batch table */}
          {batchQuery.isLoading ? (
            <div className="flex items-center justify-center h-32">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <Card>
              <CardContent className="p-0 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-muted-foreground text-xs">
                      <th className="text-left p-3 font-medium">Batch No.</th>
                      <th className="text-left p-3 font-medium">Product</th>
                      <th className="text-left p-3 font-medium">Supplier</th>
                      <th className="text-left p-3 font-medium">Status</th>
                      <th className="text-left p-3 font-medium">Dispatch</th>
                      <th className="text-left p-3 font-medium">Valid To</th>
                      <th className="p-3" />
                    </tr>
                  </thead>
                  <tbody>
                    {batches.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="text-center py-8 text-muted-foreground">No batches registered.</td>
                      </tr>
                    ) : (
                      batches.map((b) => (
                        <tr key={b.id} className="border-b last:border-0">
                          <td className="p-3 font-mono text-xs">{b.batch_number}</td>
                          <td className="p-3 font-medium">{b.product_name}</td>
                          <td className="p-3 text-muted-foreground">{b.supplier ?? "—"}</td>
                          <td className="p-3">
                            <Pill label={b.status} colorCls={STATUS_COLORS[b.status]} />
                          </td>
                          <td className="p-3">
                            {b.dispatch_blocked ? (
                              <span className="flex items-center gap-1 text-red-600 text-xs font-medium">
                                <Lock className="h-3 w-3" /> Blocked
                              </span>
                            ) : (
                              <span className="text-green-600 text-xs font-medium flex items-center gap-1">
                                <CheckCircle2 className="h-3 w-3" /> Clear
                              </span>
                            )}
                          </td>
                          <td className="p-3 text-muted-foreground">
                            {b.valid_to ? new Date(b.valid_to).toLocaleDateString("en-NG") : "—"}
                          </td>
                          <td className="p-3">
                            {b.status === "pending" && (
                              <div className="flex gap-1">
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="h-7 text-xs text-green-700 border-green-300 hover:bg-green-50"
                                  onClick={() => { setApproveTarget(b); setValidFrom(b.valid_from ?? ""); setValidTo(b.valid_to ?? ""); }}
                                >
                                  Approve
                                </Button>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="h-7 text-xs text-red-700 border-red-300 hover:bg-red-50"
                                  onClick={() => setRejectTarget(b)}
                                >
                                  Reject
                                </Button>
                              </div>
                            )}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* ---- RECALLS ---- */}
      {sub === "recalls" && (
        <div className="space-y-4">
          <div className="flex items-center gap-2 flex-wrap">
            <Select value={recallStatusFilter || "__all__"} onValueChange={(v) => setRecallStatusFilter(v === "__all__" ? "" : v)}>
              <SelectTrigger className="w-[150px] h-8 text-sm"><SelectValue placeholder="All statuses" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">All statuses</SelectItem>
                <SelectItem value="initiated">Initiated</SelectItem>
                <SelectItem value="in_progress">In Progress</SelectItem>
                <SelectItem value="completed">Completed</SelectItem>
                <SelectItem value="closed">Closed</SelectItem>
              </SelectContent>
            </Select>
            <Button variant="ghost" size="sm" onClick={() => recallQuery.refetch()} disabled={recallQuery.isFetching}>
              <RefreshCw className={`h-4 w-4 ${recallQuery.isFetching ? "animate-spin" : ""}`} />
            </Button>
            <Button size="sm" variant="destructive" onClick={() => setShowRecallForm((p) => !p)}>
              <Siren className="h-4 w-4 mr-1" /> Initiate Recall
            </Button>
          </div>

          {/* Recall form */}
          {showRecallForm && (
            <motion.div {...motionVariants.cardEnter} transition={motionTransitions.standard}>
              <Card className="border-red-300">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm text-red-700 flex items-center gap-2">
                    <Siren className="h-4 w-4" /> Initiate Product Recall
                  </CardTitle>
                  <CardDescription>This action will be recorded and notified to relevant departments.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">Batch Number *</label>
                      <Input value={rBatch} onChange={(e) => setRBatch(e.target.value)} placeholder="BTH-2026-001" />
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">Product Name *</label>
                      <Input value={rProduct} onChange={(e) => setRProduct(e.target.value)} placeholder="Product name" />
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">Scope</label>
                      <Select value={rScope} onValueChange={(v) => setRScope(v as typeof rScope)}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="voluntary">Voluntary</SelectItem>
                          <SelectItem value="mandatory">Mandatory</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="md:col-span-2">
                      <label className="text-xs text-muted-foreground mb-1 block">Regulatory Authority</label>
                      <Input value={rAuthority} onChange={(e) => setRAuthority(e.target.value)} placeholder="NAFDAC / SON / etc." />
                    </div>
                  </div>
                  <div>
                    <label className="text-xs text-muted-foreground mb-1 block">Recall Reason *</label>
                    <Textarea rows={3} value={rReason} onChange={(e) => setRReason(e.target.value)} placeholder="Detailed reason for recall…" />
                  </div>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="destructive"
                      disabled={initiateRecallMut.isPending || !rBatch.trim() || !rProduct.trim() || !rReason.trim()}
                      onClick={() => initiateRecallMut.mutate()}
                    >
                      {initiateRecallMut.isPending && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
                      Initiate Recall
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => setShowRecallForm(false)}>Cancel</Button>
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          )}

          {/* Recalls list */}
          {recallQuery.isLoading ? (
            <div className="flex items-center justify-center h-32">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <div className="space-y-3">
              {recalls.length === 0 ? (
                <div className="text-center py-12 text-muted-foreground">No recalls on record.</div>
              ) : (
                recalls.map((r) => (
                  <motion.div key={r.id} {...motionVariants.cardEnter} transition={motionTransitions.standard}>
                    <Card>
                      <CardContent className="p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div className="space-y-1 flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="font-mono text-xs text-muted-foreground">{r.recall_id}</span>
                              <Pill
                                label={r.scope}
                                colorCls={r.scope === "mandatory" ? "bg-red-100 text-red-700" : "bg-yellow-100 text-yellow-700"}
                              />
                              <Pill label={r.status} colorCls={STATUS_COLORS[r.status]} />
                            </div>
                            <p className="text-sm font-medium">{r.product_name} — Batch {r.batch_number}</p>
                            <p className="text-xs text-muted-foreground leading-relaxed line-clamp-2">{r.recall_reason}</p>
                            <p className="text-xs text-muted-foreground">{fmtDt(r.created_at)}</p>
                          </div>
                          {r.status !== "closed" && (
                            <Button
                              size="sm"
                              variant="outline"
                              className="shrink-0 h-8 text-xs"
                              onClick={() => {
                                setRecallUpdateTarget(r);
                                setNewRecallStatus("in_progress");
                                setRecallNotes("");
                              }}
                            >
                              Update Status
                            </Button>
                          )}
                        </div>
                      </CardContent>
                    </Card>
                  </motion.div>
                ))
              )}
            </div>
          )}
        </div>
      )}

      {/* Approve dialog */}
      <Dialog open={!!approveTarget} onOpenChange={(o) => { if (!o) setApproveTarget(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Approve Batch {approveTarget?.batch_number}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            <div className="rounded-md bg-muted p-3">
              <div><span className="font-medium">Product:</span> {approveTarget?.product_name}</div>
              <div><span className="font-medium">Supplier:</span> {approveTarget?.supplier ?? "—"}</div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Valid From</label>
                <Input type="date" value={validFrom} onChange={(e) => setValidFrom(e.target.value)} />
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Valid To</label>
                <Input type="date" value={validTo} onChange={(e) => setValidTo(e.target.value)} />
              </div>
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Notes</label>
              <Textarea rows={2} value={approveNotes} onChange={(e) => setApproveNotes(e.target.value)} placeholder="Approval notes…" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setApproveTarget(null)}>Cancel</Button>
            <Button
              className="bg-green-700 hover:bg-green-800 text-white"
              disabled={approveMut.isPending}
              onClick={() => approveTarget && approveMut.mutate(approveTarget)}
            >
              {approveMut.isPending && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
              Confirm Approval
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Reject dialog */}
      <Dialog open={!!rejectTarget} onOpenChange={(o) => { if (!o) setRejectTarget(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject Batch {rejectTarget?.batch_number}</DialogTitle>
          </DialogHeader>
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Rejection Reason *</label>
            <Textarea rows={3} value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} placeholder="State reason for rejection…" />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRejectTarget(null)}>Cancel</Button>
            <Button
              variant="destructive"
              disabled={!rejectReason.trim() || rejectMut.isPending}
              onClick={() => rejectTarget && rejectMut.mutate(rejectTarget)}
            >
              {rejectMut.isPending && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
              Confirm Rejection
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Recall status update dialog */}
      <Dialog open={!!recallUpdateTarget} onOpenChange={(o) => { if (!o) setRecallUpdateTarget(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Update Recall Status — {recallUpdateTarget?.recall_id}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">New Status</label>
              <Select value={newRecallStatus} onValueChange={(v) => setNewRecallStatus(v as typeof newRecallStatus)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="initiated">Initiated</SelectItem>
                  <SelectItem value="in_progress">In Progress</SelectItem>
                  <SelectItem value="completed">Completed</SelectItem>
                  <SelectItem value="closed">Closed</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Notes</label>
              <Textarea rows={3} value={recallNotes} onChange={(e) => setRecallNotes(e.target.value)} placeholder="Progress notes…" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRecallUpdateTarget(null)}>Cancel</Button>
            <Button
              disabled={updateRecallMut.isPending}
              onClick={() => recallUpdateTarget && updateRecallMut.mutate(recallUpdateTarget)}
            >
              {updateRecallMut.isPending && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
              Update
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Root page component
// ---------------------------------------------------------------------------

export default function QualityControl() {
  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Page header */}
      <div className="flex items-center gap-3">
        <div className="h-10 w-10 rounded-full bg-green-100 flex items-center justify-center">
          <ShieldCheck className="h-5 w-5 text-green-700" />
        </div>
        <div>
          <h1 className="text-2xl font-bold">Quality Control</h1>
          <p className="text-sm text-muted-foreground">
            Compliance, cold-chain monitoring, NAFDAC registry &amp; product recall management
          </p>
        </div>
      </div>

      <Tabs defaultValue="dashboard" className="space-y-6">
        <TabsList className="flex-wrap h-auto gap-1">
          <TabsTrigger value="dashboard" className="flex items-center gap-1.5">
            <BarChart3 className="h-4 w-4" /> Dashboard
          </TabsTrigger>
          <TabsTrigger value="expiry" className="flex items-center gap-1.5">
            <Package className="h-4 w-4" /> Expiry Alerts
          </TabsTrigger>
          <TabsTrigger value="temperature" className="flex items-center gap-1.5">
            <Thermometer className="h-4 w-4" /> Temperature
          </TabsTrigger>
          <TabsTrigger value="capa" className="flex items-center gap-1.5">
            <FlaskConical className="h-4 w-4" /> CAPA
          </TabsTrigger>
          <TabsTrigger value="nafdac" className="flex items-center gap-1.5">
            <ShieldCheck className="h-4 w-4" /> NAFDAC &amp; Recalls
          </TabsTrigger>
        </TabsList>

        <TabsContent value="dashboard">
          <DashboardTab />
        </TabsContent>
        <TabsContent value="expiry">
          <ExpiryTab />
        </TabsContent>
        <TabsContent value="temperature">
          <TemperatureTab />
        </TabsContent>
        <TabsContent value="capa">
          <CapaTab />
        </TabsContent>
        <TabsContent value="nafdac">
          <NafdacTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
