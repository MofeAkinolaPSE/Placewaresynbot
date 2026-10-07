// Temperature monitoring, kept as it was until the client's temperature-monitoring system is connected.
import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ShieldCheck, Thermometer, AlertTriangle, Package, FlaskConical,
  Loader2, Plus, RefreshCw, CheckCircle2, XCircle, ChevronDown,
  ChevronRight, ChevronUp, Lock, ClipboardList, ClipboardCheck, Activity, BarChart3, Bell,
  Siren, Clock, FileWarning, X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { FilterBar } from "@/components/workspace/FilterBar";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { InvoiceActionPanel } from "@/components/workspace/InvoiceActionPanel";
import { InvoiceDetailBody } from "@/components/workspace/InvoiceDetailBody";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";

// Matches the currency-formatting convention used across Frontdesk/ARReceipts/CustomerWorkspace.
const fmtCurrency = (n: number | null | undefined) =>
  typeof n === "number"
    ? `₦${n.toLocaleString("en-NG", { minimumFractionDigits: 2 })}`
    : "—";

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
  minor:    "bg-yellow-100 text-yellow-700 dark:bg-yellow-500/15 dark:text-yellow-300",
  major:    "bg-orange-100 text-orange-700 dark:bg-orange-500/15 dark:text-orange-300",
  critical: "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300",
};

const STATUS_COLORS: Record<string, string> = {
  open:               "bg-blue-100 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300",
  under_investigation:"bg-purple-100 text-purple-700 dark:bg-purple-500/15 dark:text-purple-300",
  escalated:          "bg-orange-100 text-orange-700 dark:bg-orange-500/15 dark:text-orange-300",
  closed:             "bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300",
  pending:            "bg-yellow-100 text-yellow-700 dark:bg-yellow-500/15 dark:text-yellow-300",
  approved:           "bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300",
  rejected:           "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300",
  suspended:          "bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-white/70",
  initiated:          "bg-blue-100 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300",
  in_progress:        "bg-purple-100 text-purple-700 dark:bg-purple-500/15 dark:text-purple-300",
  completed:          "bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300",
};

function Pill({ label, colorCls }: { label: string; colorCls?: string }) {
  const cls = colorCls ?? "bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-white/70";
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

export function TemperatureTab() {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const [sheetOpen, setSheetOpen] = useState(false);
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

  // Derived from the already-fetched logs array (no new call) — matches
  // CapaTab's KpiStrip precedent. See ACE-Workspace-Standard.md Ch.9's
  // partial-retrofit note: this tab keeps its flat table (every row already
  // is its own detail view) but adopts KpiStrip/FilterBar/DetailSheet.
  const kpis = useMemo(() => ({
    total:      logs.length,
    deviations: logs.filter((l) => l.is_deviation).length,
    escalated:  logs.filter((l) => l.is_deviation && l.deviation_escalated).length,
    normal:     logs.filter((l) => !l.is_deviation).length,
  }), [logs]);

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
      setSheetOpen(false);
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
    <div className="space-y-4">
      <KpiStrip
        items={[
          { label: "Total Logs", value: kpis.total },
          { label: "Deviations", value: kpis.deviations, tone: "warning" },
          { label: "Escalated", value: kpis.escalated, tone: "danger" },
          { label: "Normal", value: kpis.normal, tone: "success" },
        ]}
      />

      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-semibold">Cold-Chain Temperature Logs</h2>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={`h-4 w-4 mr-1 ${isFetching ? "animate-spin" : ""}`} />
          </Button>
          <Button size="sm" onClick={() => setSheetOpen(true)}>
            <Plus className="h-4 w-4 mr-1" /> Log Reading
          </Button>
        </div>
      </div>

      <FilterBar
        search={{ value: filterLocation, onChange: setFilterLocation, placeholder: "Filter by location…" }}
        selects={[
          {
            label: "readings",
            value: filterDevOnly ? "deviations" : "",
            onChange: (v) => setFilterDevOnly(v === "deviations"),
            placeholder: "All Readings",
            options: [{ value: "deviations", label: "Deviations Only" }],
          },
        ]}
      />

      {/* Logs table — stays a flat table, not List/Detail: every row already
          shows its full detail, and Escalate is a single Dialog click away.
          See ACE-Workspace-Standard.md Ch.9's partial-retrofit note. */}
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
                      className={`border-b last:border-0 ${log.is_deviation ? "bg-red-50 dark:bg-red-500/15" : ""}`}
                    >
                      <td className="p-3 font-medium">{log.location}</td>
                      <td className="p-3 text-right font-mono font-semibold">
                        <span className={log.is_deviation ? "text-red-600 dark:text-red-300" : ""}>{log.reading_celsius}°C</span>
                      </td>
                      <td className="p-3">{SESSION_LABELS[log.log_session] ?? log.log_session}</td>
                      <td className="p-3 text-muted-foreground">{log.logged_by}</td>
                      <td className="p-3 text-muted-foreground whitespace-nowrap">{fmtDt(log.logged_at)}</td>
                      <td className="p-3">
                        {log.is_deviation ? (
                          log.deviation_escalated ? (
                            <Pill label="Escalated" colorCls="bg-orange-100 text-orange-700 dark:bg-orange-500/15 dark:text-orange-300" />
                          ) : (
                            <Pill label="Deviation" colorCls="bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300" />
                          )
                        ) : (
                          <Pill label="Normal" colorCls="bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300" />
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

      {/* New Temperature Reading — ephemeral create task, matches CapaTab's
          "New Deviation" DetailSheet precedent (Ch.5.2). */}
      <DetailSheet
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        title="New Temperature Reading"
        icon={Thermometer}
        footer={
          <Button
            className="w-full"
            disabled={logMut.isPending || !logLocation.trim() || !logReading || !logBy.trim()}
            onClick={() => logMut.mutate()}
          >
            {logMut.isPending && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
            Submit
          </Button>
        }
      >
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
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
              <label className="text-xs text-muted-foreground mb-1 block">Logged By *</label>
              <Input placeholder="Staff name" value={logBy} onChange={(e) => setLogBy(e.target.value)} />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Min Threshold (°C)</label>
              <Input type="number" step="0.1" placeholder="2.0" value={logMin} onChange={(e) => setLogMin(e.target.value)} />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Max Threshold (°C)</label>
              <Input type="number" step="0.1" placeholder="8.0" value={logMax} onChange={(e) => setLogMax(e.target.value)} />
            </div>
          </div>
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Notes</label>
            <Textarea placeholder="Optional notes…" rows={2} value={logNotes} onChange={(e) => setLogNotes(e.target.value)} />
          </div>
        </div>
      </DetailSheet>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab 4: CAPA / Deviations
