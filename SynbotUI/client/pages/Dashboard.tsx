import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Package,
  DollarSign,
  Users,
  ShieldCheck,
  ShoppingCart,
  Factory,
  AlertCircle,
  RotateCcw,
  ReceiptText,
  ClipboardList,
  BarChart3,
  MessageSquare,
  CalendarDays,
  Loader2,
  Truck,
  MapPin,
  CheckCircle2,
  FileText,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { useAuth } from "@/components/AuthProvider";
import { useToast } from "@/hooks/use-toast";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/workspace/PageHeader";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { EntityAutocomplete } from "@/components/workspace/EntityAutocomplete";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import type { DepartmentCard, WorkstationSummary } from "@shared/dashboard-types";

// ── Department card definitions ─────────────────────────────────────────────
// Each department's shallow metrics + a can_drill_in-aware "View Full X" link.
// Sensitive fields (ar_total_balance, pipeline_value, total_value, etc.) are
// simply absent from the payload for a role without access -- see
// backend/src/services/intelligence.py's get_workstation_summary() -- so
// this component never has to decide what to hide, only what to render if present.
const DEPARTMENTS: {
  key: keyof WorkstationSummary["departments"];
  label: string;
  icon: typeof Package;
  metrics: (d: DepartmentCard) => { label: string; value: string | number }[];
}[] = [
  {
    key: "inventory",
    label: "Inventory",
    icon: Package,
    metrics: (d) => [
      { label: "Active SKUs", value: d.total_active_skus ?? "—" },
      { label: "Low Stock", value: d.low_stock_count ?? "—" },
      { label: "Out of Stock", value: d.out_of_stock_count ?? "—" },
    ],
  },
  {
    key: "finance",
    label: "Finance",
    icon: DollarSign,
    metrics: (d) => {
      const rows = [{ label: "Overdue AR Invoices", value: d.overdue_ar_count ?? "—" }];
      if (d.ar_total_balance != null) rows.push({ label: "AR Balance", value: `₦${Number(d.ar_total_balance).toLocaleString()}` });
      if (d.ap_total_balance != null) rows.push({ label: "AP Balance", value: `₦${Number(d.ap_total_balance).toLocaleString()}` });
      return rows;
    },
  },
  {
    key: "hr",
    label: "HR / Workforce",
    icon: Users,
    metrics: (d) => [
      { label: "Staff Active This Week", value: d.active_staff_count ?? "—" },
      { label: "Hours Logged", value: d.total_hours_this_week ?? "—" },
    ],
  },
  {
    key: "quality_control",
    label: "Quality Control",
    icon: ShieldCheck,
    metrics: (d) => [
      { label: "Expiring (30d)", value: d.expiring_critical_30d ?? "—" },
      { label: "Open Deviations", value: d.open_deviations ?? "—" },
      { label: "Temp Alerts Today", value: d.temp_alerts_today ?? "—" },
    ],
  },
  {
    key: "crm",
    label: "CRM / Sales",
    icon: ShoppingCart,
    metrics: (d) => {
      const rows = [
        { label: "Open Prospects", value: d.open_prospects_count ?? "—" },
        { label: "Win Rate", value: d.win_rate_pct != null ? `${d.win_rate_pct}%` : "—" },
      ];
      if (d.pipeline_value != null) rows.push({ label: "Pipeline Value", value: `₦${Number(d.pipeline_value).toLocaleString()}` });
      return rows;
    },
  },
  {
    key: "operations",
    label: "Operations",
    icon: Factory,
    metrics: (d) => {
      const rows = [
        { label: "Open POs", value: d.open_po_count ?? "—" },
        { label: "Overdue POs", value: d.overdue_po_count ?? "—" },
      ];
      if (d.total_value != null) rows.push({ label: "Total PO Value", value: `₦${Number(d.total_value).toLocaleString()}` });
      return rows;
    },
  },
];

const STATUS_BORDER: Record<string, string> = {
  healthy: "border-l-4 border-l-success",
  attention: "border-l-4 border-l-warning",
  critical: "border-l-4 border-l-destructive",
  at_risk: "border-l-4 border-l-warning",
  unknown: "border-l-4 border-l-muted",
};

// ── Quick Actions ────────────────────────────────────────────────────────────
// Day-to-day cross-department shortcuts, role-filtered, capped at 5 -- a
// "quick access" row that tries to cover everything stops being quick.
// Each reuses an already-built flow (no duplicated forms) except "Reorder
// Stock", simple enough (SKU + qty, one endpoint) to embed directly here.
type QuickAction =
  | { id: string; label: string; icon: typeof Package; roles: string[]; kind: "embedded" }
  | { id: string; label: string; icon: typeof Package; roles: string[]; kind: "navigate"; target: string };

const QUICK_ACTIONS: QuickAction[] = [
  { id: "reorder", label: "Reorder Stock", icon: RotateCcw, roles: ["admin", "ops", "operations", "finance", "procurement"], kind: "embedded" },
  { id: "invoice", label: "Create Invoice", icon: ReceiptText, roles: ["admin", "crm", "sales"], kind: "navigate", target: "/customers/workspace?action=new-request" },
  { id: "receipt", label: "Approve Receipt", icon: ClipboardList, roles: ["admin", "finance"], kind: "navigate", target: "/finance/ar/receipts" },
  { id: "inventory", label: "View Inventory", icon: Package, roles: ["admin", "ops", "operations", "finance", "sales"], kind: "navigate", target: "/inventory" },
  { id: "timesheet", label: "Log Timesheet", icon: CalendarDays, roles: ["admin", "hr", "ops", "management"], kind: "navigate", target: "/staff/time-tracker" },
];

type InventorySearchResult = { sku?: string; name: string };

const QUICK_LINKS: { label: string; href: string; icon: typeof BarChart3; roles?: string[] }[] = [
  { label: "Executive Briefing", href: "/executive", icon: BarChart3, roles: ["admin", "management", "finance"] },
  { label: "Finance Analytics", href: "/finance/analytics", icon: DollarSign, roles: ["admin", "finance"] },
  { label: "Calendar", href: "/calendar", icon: CalendarDays },
  { label: "Compliance & QMS", href: "/compliance", icon: ShieldCheck, roles: ["admin", "quality_assurance", "qa", "operations", "ops", "management"] },
  { label: "Ask ACE", href: "/synbot", icon: MessageSquare },
  // No `roles` — every team member can view invoices; QC/Finance/Dispatch
  // actions inside stay gated by role regardless of how this page is reached.
  { label: "All Invoices", href: "/frontdesk/invoices", icon: FileText },
];

const Dashboard = () => {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { roles } = useAuth();
  const { toast } = useToast();

  const [reorderOpen, setReorderOpen] = useState(false);
  const [reorderItem, setReorderItem] = useState<{ sku: string; name: string } | null>(null);
  const [reorderQty, setReorderQty] = useState("20");

  const [selectedDelivery, setSelectedDelivery] = useState<any | null>(null);

  const invalidateWorkstation = () => queryClient.invalidateQueries({ queryKey: ["workstation-summary"] });
  const invalidateOpsQueue = () => queryClient.invalidateQueries({ queryKey: ["ops-active-deliveries"] });
  const invalidateLogistics = () => { invalidateWorkstation(); invalidateOpsQueue(); };

  useRealtimeChannel("alerts_updates", invalidateWorkstation);
  useRealtimeChannel("inventory_updates", invalidateWorkstation);
  useRealtimeChannel("finance_updates", invalidateWorkstation);
  useRealtimeChannel("workflow_updates", invalidateWorkstation);
  useRealtimeChannel("logistics_updates", invalidateLogistics);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["workstation-summary"],
    queryFn: () => api.dashboard.workstation(),
    refetchInterval: 60000,
  });

  // Same query key Layout.tsx's top-bar pill uses -- TanStack Query dedupes
  // this automatically. Spliced into the HR department card's metrics below
  // rather than threaded through the backend's DepartmentCard shape, to
  // keep presence a fully separate, always-live subsystem.
  const { data: presenceData } = useQuery({
    queryKey: ["presence-online"],
    queryFn: () => api.presence.online(),
    refetchInterval: 30000,
  });
  const onlineCount = presenceData?.count ?? 0;

  // Operations Queue — in-flight deliveries, straight from the pipeline the
  // invoice/QC/finance/dispatch flow feeds into. No new backend endpoint:
  // this is the same data GET /logistics/active-deliveries already returns
  // for LogisticsMonitor.tsx's own live map.
  const { data: opsQueueData, isLoading: opsQueueLoading } = useQuery({
    queryKey: ["ops-active-deliveries"],
    queryFn: () => api.logistics.activeDeliveries(),
    refetchInterval: 30000,
  });
  const activeDeliveries: any[] = opsQueueData?.deliveries ?? [];
  const assignedCount = activeDeliveries.filter((d) => d.status === "assigned").length;
  const inTransitCount = activeDeliveries.filter((d) => d.status === "in_transit").length;

  const markDeliveredMutation = useMutation({
    mutationFn: (deliveryId: string) => api.logistics.updateDeliveryStatus(deliveryId, "delivered"),
    onSuccess: () => {
      toast({ title: "Delivery confirmed" });
      setSelectedDelivery(null);
      invalidateOpsQueue();
    },
    onError: (err: any) => toast({ title: "Failed to confirm delivery", description: err.message, variant: "destructive" }),
  });

  const departments = data?.departments;
  const canView = (allowed?: string[]) => !allowed || roles.some((r) => allowed.includes(r));
  // Keep a card while its data is still loading (undefined) so cards don't
  // flicker in/out as the summary arrives; once loaded, drop any the
  // viewer's role can't drill into.
  const visibleDepartments = DEPARTMENTS.filter(({ key }) => {
    const d = departments?.[key];
    return !d || d.can_drill_in;
  });

  const reorderMutation = useMutation({
    mutationFn: () => api.replenishment.create({ sku: reorderItem!.sku, requested_qty: parseFloat(reorderQty) || 1 }),
    onSuccess: () => {
      toast({ title: "Reorder requested", description: `${reorderQty} units of ${reorderItem?.name}` });
      setReorderOpen(false);
      setReorderItem(null);
      setReorderQty("20");
    },
    onError: (err: any) => toast({ title: "Reorder request failed", description: err.message, variant: "destructive" }),
  });

  const handleQuickAction = (action: QuickAction) => {
    if (action.kind === "navigate") {
      navigate(action.target);
    } else if (action.id === "reorder") {
      setReorderOpen(true);
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
        icon={Factory}
        title="ACE Workstation"
        subtitle="Every department, at a glance — drill in to what you have access to."
      />

      {isError && (
        <div className="text-sm text-destructive rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-2.5">
          Failed to load the workstation summary. Try refreshing.
        </div>
      )}

      {/* ── Quick Actions ────────────────────────────────────────── */}
      {(() => {
        const visible = QUICK_ACTIONS.filter((a) => canView(a.roles));
        if (visible.length === 0) return null;
        return (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">Quick Actions</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
                {visible.map((action) => (
                  <Button
                    key={action.id}
                    variant="outline"
                    className="h-auto flex-col gap-1.5 py-3"
                    onClick={() => handleQuickAction(action)}
                  >
                    <action.icon className="h-4 w-4" />
                    <span className="text-xs font-medium">{action.label}</span>
                  </Button>
                ))}
              </div>
            </CardContent>
          </Card>
        );
      })()}

      {/* ── Department cards ────────────────────────────────────────── */}
      {/* Only show departments this role can actually drill into --
          previously every card rendered regardless, with its "View Full"
          button replaced by a static "Restricted" span for departments the
          viewer couldn't open. can_drill_in is already computed server-side
          per the caller's roles (get_workstation_summary, includes admin in
          every department's allowed set, so admin's view is unaffected).
          Cards stay visible while loading (d undefined) so they don't
          flicker in/out once the summary arrives. */}
      {!isLoading && visibleDepartments.length === 0 && (
        <div className="rounded-lg border bg-muted/20 p-8 text-center text-sm text-muted-foreground">
          No department views available for your role.
        </div>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {visibleDepartments.map(({ key, label, icon: Icon, metrics }) => {
          const d = departments?.[key];
          return (
            <Card key={key} className={cn(d ? STATUS_BORDER[d.status] ?? STATUS_BORDER.unknown : STATUS_BORDER.unknown)}>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm font-semibold flex items-center gap-2">
                    <Icon className="h-4 w-4 text-muted-foreground" />
                    {label}
                  </CardTitle>
                  {d && d.alert_count > 0 && (
                    <Badge variant="destructive" className="text-[10px]">{d.alert_count} alert{d.alert_count === 1 ? "" : "s"}</Badge>
                  )}
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {isLoading || !d ? (
                  <p className="text-xs text-muted-foreground">Loading…</p>
                ) : (
                  <div className="space-y-1.5">
                    {(key === "hr" ? [...metrics(d), { label: "Currently Online", value: onlineCount }] : metrics(d)).map((m) => (
                      <div key={m.label} className="flex justify-between text-sm">
                        <span className="text-muted-foreground">{m.label}</span>
                        <span className="font-semibold tabular-nums">{m.value}</span>
                      </div>
                    ))}
                  </div>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  className="w-full mt-1"
                  disabled={!d}
                  asChild={!!d}
                >
                  {d ? (
                    <Link to={d.drill_in_path}>
                      View Full {label} <ArrowRight className="ml-2 h-3.5 w-3.5" />
                    </Link>
                  ) : (
                    <span>Loading…</span>
                  )}
                </Button>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* ── Operations Queue ────────────────────────────────────────
          In-flight deliveries — reuses the same live data LogisticsMonitor.tsx's
          map already shows, summarized here so operations has a queue view on
          the org-wide dashboard the same way every other department already does. */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-semibold flex items-center gap-2">
              <Truck className="h-4 w-4 text-muted-foreground" />
              Operations Queue
            </CardTitle>
            <Button size="sm" variant="outline" asChild>
              <Link to="/operations/logistics">
                View Full Logistics <ArrowRight className="ml-2 h-3.5 w-3.5" />
              </Link>
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <KpiStrip
            items={[
              { label: "In-Flight Deliveries", value: activeDeliveries.length, icon: Truck },
              { label: "Assigned", value: assignedCount },
              { label: "In Transit", value: inTransitCount, tone: inTransitCount > 0 ? "warning" : "default" },
            ]}
          />
          {opsQueueLoading ? (
            <p className="text-xs text-muted-foreground py-2">Loading…</p>
          ) : activeDeliveries.length === 0 ? (
            <p className="text-xs text-muted-foreground py-2">No deliveries in flight right now.</p>
          ) : (
            <div className="space-y-1.5">
              {activeDeliveries.slice(0, 5).map((d) => (
                <button
                  key={d.id}
                  onClick={() => setSelectedDelivery(d)}
                  className="w-full flex items-center justify-between gap-3 rounded-lg border border-border/50 px-3 py-2 text-left text-sm transition-colors hover:border-primary/40 hover:bg-muted/40"
                >
                  <div className="min-w-0">
                    <p className="font-medium truncate">{d.reference || `Delivery ${String(d.id).slice(0, 8)}`}</p>
                    <p className="text-xs text-muted-foreground truncate">
                      {d.rider?.name ? `Rider: ${d.rider.name}` : "Unassigned rider"}
                      {d.eta_text ? ` · ETA ${d.eta_text}` : ""}
                    </p>
                  </div>
                  <Badge variant={d.status === "in_transit" ? "default" : "secondary"} className="shrink-0 text-[10px]">
                    {d.status === "in_transit" ? "In Transit" : "Assigned"}
                  </Badge>
                </button>
              ))}
              {activeDeliveries.length > 5 && (
                <p className="text-xs text-muted-foreground pt-1">
                  +{activeDeliveries.length - 5} more — see Full Logistics for all of them.
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Quick Links ──────────────────────────────────────────── */}
      <div className="flex flex-wrap gap-2">
        {QUICK_LINKS.filter((l) => canView(l.roles)).map((link) => (
          <Button key={link.href} variant="secondary" size="sm" asChild>
            <Link to={link.href}>
              <link.icon className="mr-2 h-4 w-4" />
              {link.label}
            </Link>
          </Button>
        ))}
      </div>

      {/* Reorder Stock — the one Quick Action simple enough to embed here
          directly (SKU search + qty, one endpoint) rather than navigating
          away; reuses api.inventory.search / api.replenishment.create, both
          already built for the Inventory Workspace. */}
      <DetailSheet
        open={reorderOpen}
        onOpenChange={(open) => { setReorderOpen(open); if (!open) setReorderItem(null); }}
        title="Reorder Stock"
        description="Search for a SKU and submit a replenishment request."
        icon={RotateCcw}
        footer={
          <Button
            className="w-full"
            disabled={!reorderItem || reorderMutation.isPending || !parseFloat(reorderQty)}
            onClick={() => reorderMutation.mutate()}
          >
            {reorderMutation.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            Submit Reorder Request
          </Button>
        }
      >
        <div className="space-y-2">
          <label className="text-xs text-muted-foreground">Item / SKU</label>
          <EntityAutocomplete<InventorySearchResult>
            fetchFn={(q) => api.inventory.search(q)}
            getKey={(p) => p.sku ?? p.name}
            getLabel={(p) => p.name}
            getSubtitle={(p) => p.sku}
            placeholder="Search inventory…"
            onSelect={(p) => setReorderItem({ sku: p.sku || p.name, name: p.name })}
          />
          {reorderItem && (
            <p className="text-xs text-muted-foreground">Selected: {reorderItem.name} ({reorderItem.sku})</p>
          )}
        </div>
        <div className="space-y-2">
          <label className="text-xs text-muted-foreground">Quantity</label>
          <Input type="number" min="1" value={reorderQty} onChange={(e) => setReorderQty(e.target.value)} />
        </div>
      </DetailSheet>

      {/* Operations Queue delivery detail — quick look + confirm, without
          leaving the dashboard for the full logistics workspace. */}
      <DetailSheet
        open={!!selectedDelivery}
        onOpenChange={(open) => { if (!open) setSelectedDelivery(null); }}
        title={selectedDelivery?.reference || "Delivery Detail"}
        description="In-flight delivery from the Operations Queue."
        icon={Truck}
        footer={
          selectedDelivery && selectedDelivery.status !== "delivered" ? (
            <Button
              className="w-full gap-2"
              disabled={markDeliveredMutation.isPending}
              onClick={() => markDeliveredMutation.mutate(selectedDelivery.id)}
            >
              {markDeliveredMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
              Mark Delivered
            </Button>
          ) : undefined
        }
      >
        {selectedDelivery && (
          <div className="space-y-3 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Status</span>
              <Badge variant={selectedDelivery.status === "in_transit" ? "default" : "secondary"}>
                {selectedDelivery.status === "in_transit" ? "In Transit" : "Assigned"}
              </Badge>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Rider</span>
              <span className="font-medium">{selectedDelivery.rider?.name || "Unassigned"}</span>
            </div>
            {selectedDelivery.eta_text && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">ETA</span>
                <span className="font-medium">{selectedDelivery.eta_text}</span>
              </div>
            )}
            {selectedDelivery.address?.destination && (
              <div className="flex items-start justify-between gap-2">
                <span className="text-muted-foreground shrink-0">Destination</span>
                <span className="font-medium text-right flex items-center gap-1">
                  <MapPin className="h-3.5 w-3.5 shrink-0" /> {selectedDelivery.address.destination}
                </span>
              </div>
            )}
            {selectedDelivery.rider?.last_seen_at && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Last Position Update</span>
                <span className="font-medium">{new Date(selectedDelivery.rider.last_seen_at).toLocaleTimeString()}</span>
              </div>
            )}
          </div>
        )}
      </DetailSheet>
    </motion.div>
  );
};

export default Dashboard;
