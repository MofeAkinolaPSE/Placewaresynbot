import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bell,
  BellOff,
  Check,
  ChevronDown,
  ChevronRight,
  Download,
  FileDown,
  Loader2,
  Plus,
  Search,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
  Trash2,
  Users,
  X,
} from "lucide-react";
import { motion } from "framer-motion";
import { DrillLink } from "@/components/books/kit";
import { motionVariants } from "@/lib/motion";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api-client";
import { apiUrl } from "@/lib/api-base";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { DetailSheet } from "@/components/workspace/DetailSheet";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const fmt = (n: number) =>
  typeof n === "number" ? `₦${n.toLocaleString("en-NG", { minimumFractionDigits: 2 })}` : "—";

function BucketBadge({ bucket }: { bucket: string }) {
  const lc = (bucket || "").toLowerCase();
  let cls = "bg-muted text-muted-foreground";
  if (lc.includes("0-30") || lc.includes("0_30")) cls = "bg-green-500/15 text-green-700 dark:text-green-400";
  else if (lc.includes("31-60") || lc.includes("31_60")) cls = "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400";
  else if (lc.includes("61-90") || lc.includes("61_90")) cls = "bg-orange-500/15 text-orange-700 dark:text-orange-400";
  else if (lc.includes("90+") || lc.includes("91")) cls = "bg-red-500/15 text-red-700 dark:text-red-400";
  return <span className={`rounded px-2 py-0.5 text-xs font-semibold ${cls}`}>{bucket}</span>;
}

// ---------------------------------------------------------------------------
// Alert Rules tab — extracted into its own component (mirroring
// QualityControl.tsx's NafdacTab/TemperatureTab pattern) since FinanceAR is
// otherwise one monolithic function with all 7 tabs' state/queries/
// mutations inline. This is the only FinanceAR tab with real create/delete/
// ack mutations on discrete, already-fully-shown records — a partial
// retrofit (KpiStrip + DetailSheet, flat table + per-row actions kept
// as-is), same reasoning as NafdacTab/TemperatureTab. See
// ACE-Workspace-Standard.md Ch.9.5/9.7.
// ---------------------------------------------------------------------------

function AlertRulesTab() {
  const { toast } = useToast();
  const qc = useQueryClient();

  const [sheetOpen, setSheetOpen] = useState(false);
  const [alertForm, setAlertForm] = useState({
    threshold_amount: "",
    days_overdue_min: "30",
    customer_id: "",
    description: "",
    notify_emails: "",
  });

  const alertsQ = useQuery({
    queryKey: ["finance-ar-alerts"],
    queryFn: () => api.finance.listArAlerts(),
    refetchInterval: 60_000,
  });

  const alerts = (alertsQ.data as any) ?? {};
  const rules: any[] = alerts.rules ?? [];
  const events: any[] = alerts.unacknowledged_events ?? [];

  const kpis = useMemo(() => ({
    total: rules.length,
    active: rules.filter((r) => r.is_active).length,
    inactive: rules.filter((r) => !r.is_active).length,
    unacked: events.length,
  }), [rules, events]);

  const createAlertMut = useMutation({
    mutationFn: (payload: any) => api.finance.createArAlert(payload),
    onSuccess: () => {
      toast({ title: "Alert rule created" });
      void qc.invalidateQueries({ queryKey: ["finance-ar-alerts"] });
      setSheetOpen(false);
      setAlertForm({ threshold_amount: "", days_overdue_min: "30", customer_id: "", description: "", notify_emails: "" });
    },
    onError: (err: any) =>
      toast({ title: "Failed to create alert", description: err.message, variant: "destructive" }),
  });

  const deleteAlertMut = useMutation({
    mutationFn: (ruleId: string) => api.finance.deleteArAlert(ruleId),
    onSuccess: () => {
      toast({ title: "Alert rule deactivated" });
      void qc.invalidateQueries({ queryKey: ["finance-ar-alerts"] });
    },
    onError: (err: any) =>
      toast({ title: "Failed to deactivate", description: err.message, variant: "destructive" }),
  });

  const ackEventMut = useMutation({
    mutationFn: (eventId: string) => api.finance.ackAlertEvent(eventId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["finance-ar-alerts"] });
    },
  });

  function handleCreateAlert() {
    const payload: any = {
      threshold_amount: parseFloat(alertForm.threshold_amount),
      days_overdue_min: parseInt(alertForm.days_overdue_min, 10),
    };
    if (alertForm.customer_id) payload.customer_id = alertForm.customer_id;
    if (alertForm.description) payload.description = alertForm.description;
    if (alertForm.notify_emails)
      payload.notify_emails = alertForm.notify_emails.split(",").map((s) => s.trim()).filter(Boolean);
    createAlertMut.mutate(payload);
  }

  return (
    <div className="space-y-4">
      <KpiStrip
        items={[
          { label: "Total Rules", value: kpis.total },
          { label: "Active", value: kpis.active, tone: "success" },
          { label: "Inactive", value: kpis.inactive },
          { label: "Unacknowledged Events", value: kpis.unacked, tone: kpis.unacked > 0 ? "danger" : "default" },
        ]}
      />

      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">Threshold Alert Rules</h2>
        <Button size="sm" onClick={() => setSheetOpen(true)}>
          <Plus className="w-4 h-4 mr-1" /> New Rule
        </Button>
      </div>

      {/* Unacknowledged events */}
      {events.length > 0 && (
        <Card className="border-orange-500/30 bg-orange-500/5">
          <CardHeader className="py-3">
            <CardTitle className="text-sm text-orange-600 dark:text-orange-400">
              Unacknowledged Events ({events.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="space-y-2">
              {events.map((ev: any) => (
                <div
                  key={ev.id}
                  className="flex items-center justify-between text-sm border border-border/50 rounded-lg px-3 py-2"
                >
                  <div>
                    <strong>{ev.customer_id ?? ev.customer_name}</strong>:{" "}
                    {fmt(ev.outstanding_balance)} outstanding — {ev.days_overdue}d overdue
                    <span className="ml-2 text-xs text-muted-foreground">
                      {ev.triggered_at?.slice(0, 16)}
                    </span>
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => ackEventMut.mutate(ev.id)}
                    disabled={ackEventMut.isPending}
                  >
                    <Check className="w-4 h-4" />
                  </Button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Rules table — stays flat, not List/Detail: every row already shows
          its full detail, and delete is already a single click away. See
          ACE-Workspace-Standard.md Ch.9.5. */}
      <div className="rounded-xl border border-border overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Threshold (₦)</TableHead>
              <TableHead>Min Days Overdue</TableHead>
              <TableHead>Customer</TableHead>
              <TableHead>Description</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="w-12" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {alertsQ.isLoading ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center py-8">
                  <Loader2 className="w-5 h-5 animate-spin mx-auto text-muted-foreground" />
                </TableCell>
              </TableRow>
            ) : rules.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground py-10">
                  No alert rules configured
                </TableCell>
              </TableRow>
            ) : (
              rules.map((r: any) => (
                <TableRow key={r.id}>
                  <TableCell className="font-mono font-semibold">
                    {fmt(r.threshold_amount)}
                  </TableCell>
                  <TableCell>{r.days_overdue_min}d</TableCell>
                  <TableCell>{r.customer_id ?? <span className="text-muted-foreground">All</span>}</TableCell>
                  <TableCell className="text-sm">{r.description ?? "—"}</TableCell>
                  <TableCell>
                    <Badge variant={r.is_active ? "default" : "secondary"}>
                      {r.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-7 w-7 text-muted-foreground hover:text-destructive"
                      onClick={() => deleteAlertMut.mutate(r.id)}
                      disabled={deleteAlertMut.isPending}
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* New Rule — ephemeral create task, DetailSheet per Ch.5.2 (same
          precedent as CAPA's "New Deviation" / Temperature's "Log Reading"
          / NAFDAC's "Register Batch"/"Initiate Recall"). */}
      <DetailSheet
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        title="New AR Threshold Alert"
        description="Trigger an alert when a client's outstanding balance exceeds the threshold for the specified number of days."
        icon={Bell}
        footer={
          <Button
            className="w-full"
            onClick={handleCreateAlert}
            disabled={!alertForm.threshold_amount || createAlertMut.isPending}
          >
            {createAlertMut.isPending && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
            Create Rule
          </Button>
        }
      >
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">
              Threshold Amount (₦) *
            </label>
            <Input
              type="number"
              placeholder="e.g. 2000000"
              value={alertForm.threshold_amount}
              onChange={(e) => setAlertForm((f) => ({ ...f, threshold_amount: e.target.value }))}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">
              Minimum Days Overdue *
            </label>
            <Input
              type="number"
              value={alertForm.days_overdue_min}
              onChange={(e) => setAlertForm((f) => ({ ...f, days_overdue_min: e.target.value }))}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">
              Customer ID (blank = all customers)
            </label>
            <Input
              placeholder="e.g. CST-001"
              value={alertForm.customer_id}
              onChange={(e) => setAlertForm((f) => ({ ...f, customer_id: e.target.value }))}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">
              Description
            </label>
            <Input
              placeholder="e.g. High-value overdue accounts"
              value={alertForm.description}
              onChange={(e) => setAlertForm((f) => ({ ...f, description: e.target.value }))}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">
              Notify Emails (comma-separated)
            </label>
            <Input
              placeholder="finance@company.com, director@company.com"
              value={alertForm.notify_emails}
              onChange={(e) => setAlertForm((f) => ({ ...f, notify_emails: e.target.value }))}
            />
          </div>
        </div>
      </DetailSheet>
    </div>
  );
}

// ---------------------------------------------------------------------------
// FinanceAR page
// ---------------------------------------------------------------------------
export default function FinanceAR() {
  const { toast } = useToast();
  const qc = useQueryClient();

  // --- state ---
  const [search, setSearch] = useState("");
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [matchPeriod, setMatchPeriod] = useState("");
  const [matchResult, setMatchResult] = useState<any>(null);
  const [matchLoading, setMatchLoading] = useState(false);
  const [plPeriod, setPlPeriod] = useState("");
  const [plPdfLoading, setPlPdfLoading] = useState(false);
  const [agingPdfLoading, setAgingPdfLoading] = useState(false);

  // Tier-2: cash flow
  const [cfWeeks, setCfWeeks] = useState(12);

  // Tier-2: payroll
  const [payrollPeriod, setPayrollPeriod] = useState("");
  const [payrollPdfLoading, setPayrollPdfLoading] = useState(false);

  // --- queries ---
  const agingQ = useQuery({
    queryKey: ["finance-ar-aging-detail"],
    queryFn: () => api.finance.arAgingDetail(),
    refetchInterval: 120_000,
  });

  // Kept here (in addition to AlertRulesTab's own copy) purely to read
  // unacknowledged_events.length for the TabsList badge below — that badge
  // sits outside the tab's own render tree. TanStack Query dedupes by
  // queryKey, so this shares AlertRulesTab's cache/network request rather
  // than doubling it.
  const alertsQ = useQuery({
    queryKey: ["finance-ar-alerts"],
    queryFn: () => api.finance.listArAlerts(),
    refetchInterval: 60_000,
  });

  const plQ = useQuery({
    queryKey: ["finance-pl", plPeriod],
    queryFn: () => api.finance.pl(plPeriod || undefined),
    refetchInterval: 300_000,
  });

  const cashflowQ = useQuery({
    queryKey: ["finance-cashflow", cfWeeks],
    queryFn: () => api.finance.cashflowForecast(cfWeeks),
    refetchInterval: 300_000,
  });

  const payrollQ = useQuery({
    queryKey: ["finance-payroll", payrollPeriod],
    queryFn: () => api.finance.payrollSummary(payrollPeriod || undefined),
    refetchInterval: 300_000,
  });

  const creditRiskQ = useQuery({
    queryKey: ["finance-credit-risk"],
    queryFn: () => api.finance.creditRiskScores(),
    refetchInterval: 300_000,
  });

  // --- handlers ---
  async function handleMatch() {
    setMatchLoading(true);
    try {
      const result = await api.finance.matchInvoices({ period: matchPeriod || undefined });
      setMatchResult(result);
    } catch (err: any) {
      toast({ title: "Matching failed", description: err.message, variant: "destructive" });
    } finally {
      setMatchLoading(false);
    }
  }

  async function handlePlPdf() {
    setPlPdfLoading(true);
    try {
      const { authClient } = await import("@/lib/auth-client");
      let token = authClient.getAccessToken();
      if (!token) {
        const refreshed = await authClient.refresh();
        if (refreshed) token = authClient.getAccessToken();
      }
      const url = apiUrl(api.finance.plPdfUrl(plPeriod || undefined));
      const res = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      if (!res.ok) throw new Error(await res.text());
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `pl_report_${plPeriod || "all"}_${new Date().toISOString().slice(0, 10)}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch (err: any) {
      toast({ title: "PDF export failed", description: err.message, variant: "destructive" });
    } finally {
      setPlPdfLoading(false);
    }
  }

  async function handleAgingPdf() {
    setAgingPdfLoading(true);
    try {
      const { authClient } = await import("@/lib/auth-client");
      let token = authClient.getAccessToken();
      if (!token) {
        const refreshed = await authClient.refresh();
        if (refreshed) token = authClient.getAccessToken();
      }
      const url = apiUrl(api.finance.agingPdfUrl());
      const res = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      if (!res.ok) throw new Error(await res.text());
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `ar_aging_all_${new Date().toISOString().slice(0, 10)}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch (err: any) {
      toast({ title: "PDF export failed", description: err.message, variant: "destructive" });
    } finally {
      setAgingPdfLoading(false);
    }
  }

  async function handlePayrollPdf() {
    setPayrollPdfLoading(true);
    try {
      const { authClient } = await import("@/lib/auth-client");
      let token = authClient.getAccessToken();
      if (!token) {
        const refreshed = await authClient.refresh();
        if (refreshed) token = authClient.getAccessToken();
      }
      const url = apiUrl(api.finance.payrollPdfUrl(payrollPeriod || undefined));
      const res = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      if (!res.ok) throw new Error(await res.text());
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `payroll_${payrollPeriod || "latest"}_${new Date().toISOString().slice(0, 10)}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch (err: any) {
      toast({ title: "Payroll PDF export failed", description: err.message, variant: "destructive" });
    } finally {
      setPayrollPdfLoading(false);
    }
  }

  // --- derived data ---
  const aging = (agingQ.data as any) ?? {};
  const summary = aging.summary ?? {};
  const customers: any[] = aging.customers ?? [];
  const triggeredAlerts: any[] = aging.triggered_alerts ?? [];
  const [showAllAlerts, setShowAllAlerts] = useState(false);
  const [arTab, setArTab] = useState("aging");

  // Only events.length is read here (TabsList badge); rules/create/delete/
  // ack all live in AlertRulesTab now.
  const alerts = (alertsQ.data as any) ?? {};
  const events: any[] = alerts.unacknowledged_events ?? [];

  const pl = (plQ.data as any) ?? {};
  const plTotals = pl.totals ?? {};
  const plSeries: any[] = pl.series ?? [];

  const cf = (cashflowQ.data as any) ?? {};
  const cfForecast: any[] = cf.forecast ?? [];
  const cfTotals = cf.totals ?? {};

  const payroll = (payrollQ.data as any) ?? {};
  const payrollTotals = payroll.totals ?? {};
  const payrollEmployees: any[] = payroll.employees ?? [];
  const payrollDepts: any[] = payroll.department_summary ?? [];
  const payrollVariance = payroll.variance ?? null;

  const creditRisk = (creditRiskQ.data as any) ?? {};
  const creditCustomers: any[] = creditRisk.customers ?? [];
  const creditTierDist = creditRisk.tier_distribution ?? {};
  const criticalCount = (creditTierDist.Critical ?? 0) + (creditTierDist.High ?? 0);

  const filteredCustomers = customers.filter(
    (c) =>
      !search ||
      (c.customer_id ?? "").toLowerCase().includes(search.toLowerCase())
  );

  const summaryBuckets = [
    { label: "0–30 days", key: "0_30", color: "text-green-500" },
    { label: "31–60 days", key: "31_60", color: "text-yellow-500" },
    { label: "61–90 days", key: "61_90", color: "text-orange-500" },
    { label: "90+ days", key: "91_plus", color: "text-red-500" },
  ];

  return (
    <motion.div
      {...motionVariants.cardEnter}
      className="space-y-6"
    >
      {/* Header */}
      <div className="flex flex-col gap-1 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Credit Control &amp; Alerts</h1>
          <p className="text-sm text-muted-foreground">
            Receivables ageing, threshold alerts, credit risk, cash-flow forecast, P&amp;L and payroll, from ACE Books
          </p>
        </div>
        {triggeredAlerts.length > 0 && (
          <button type="button" onClick={() => { setShowAllAlerts(true); document.getElementById("ar-alerts")?.scrollIntoView({ behavior: "smooth" }); }}
                  className="self-start md:self-auto" title="Show every customer that triggered an alert">
            <Badge variant="destructive" className="cursor-pointer hover:opacity-90">
              <AlertTriangle className="w-3 h-3 mr-1" />
              {triggeredAlerts.length} active alert{triggeredAlerts.length > 1 ? "s" : ""} - open
            </Badge>
          </button>
        )}
      </div>

      {/* Active alert banner — capped to the top offenders (server already
          sorts by outstanding_balance desc); a threshold rule can
          legitimately match hundreds of customers, and rendering all of
          them inline turns this summary banner into an unbounded wall of
          near-identical rows. */}
      {triggeredAlerts.length > 0 && (
        <Card id="ar-alerts" className="border-destructive/40 bg-destructive/5">
          <CardHeader className="flex flex-row items-center justify-between gap-2 py-3">
            <CardTitle className="text-sm text-destructive flex items-center gap-2">
              <Bell className="w-4 h-4" /> Triggered Alert Rules ({triggeredAlerts.length})
            </CardTitle>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => setArTab("alerts")}>Alert rules</Button>
              {triggeredAlerts.length > 8 && <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => setShowAllAlerts((v) => !v)}>
                {showAllAlerts ? "Show top 8" : `Show all ${triggeredAlerts.length}`}</Button>}
            </div>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="divide-y divide-destructive/10">
            {(showAllAlerts ? triggeredAlerts : triggeredAlerts.slice(0, 8)).map((a, i) => {
              const cid = a.ace_customer_id ? String(a.ace_customer_id) : null;
              return (
              <div key={i} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5 text-sm">
                <AlertTriangle className="w-4 h-4 text-destructive shrink-0" />
                <span className="min-w-0 flex-1">
                  <strong><DrillLink to={cid ? { type: "customer", id: cid, label: a.name ?? a.customer_id } : null}>{a.name ?? a.customer_id}</DrillLink></strong>: outstanding{" "}
                  <strong>{fmt(a.outstanding_balance)}</strong> — {a.days_overdue} days overdue
                  {a.rule_description && <span className="text-muted-foreground"> ({a.rule_description})</span>}
                </span>
                {cid && (
                  <span className="flex flex-wrap gap-1">
                    <Button asChild size="sm" variant="outline" className="h-7 px-2 text-xs"><Link to={`/finance/books/sales?tab=statement&customer=${cid}`}>Statement</Link></Button>
                    <Button asChild size="sm" variant="outline" className="h-7 px-2 text-xs"><Link to={`/finance/books/sales?tab=receipts&new=receipt&customer=${cid}`}>Record receipt</Link></Button>
                    <Button asChild size="sm" variant="outline" className="h-7 px-2 text-xs"><Link to={`/crm/customers?customer=${cid}`}>Customer account</Link></Button>
                  </span>
                )}
              </div>
              );
            })}
            </div>
            {!showAllAlerts && triggeredAlerts.length > 8 && (
              <button type="button" className="pt-2 text-xs text-primary underline" onClick={() => setShowAllAlerts(true)}>
                +{triggeredAlerts.length - 8} more customer{triggeredAlerts.length - 8 > 1 ? "s" : ""} over this threshold - show them
              </button>
            )}
          </CardContent>
        </Card>
      )}

      <p className="text-xs text-muted-foreground">
        Figures come from ACE Books (open items aged by due date, credits netted) — the same numbers as ACE Books ›
        Sales › Aged receivables. Click a customer to open their account.
      </p>

      <Tabs value={arTab} onValueChange={setArTab}>
        <TabsList className="mb-4">
          <TabsTrigger value="aging">AR Aging</TabsTrigger>
          <TabsTrigger value="alerts">
            Alert Rules
            {events.length > 0 && (
              <Badge variant="destructive" className="ml-1 h-4 text-xs px-1">
                {events.length}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="pl">P&L Report</TabsTrigger>
          <TabsTrigger value="cashflow">Cash Flow</TabsTrigger>
          <TabsTrigger value="payroll">Payroll</TabsTrigger>
          <TabsTrigger value="credit">Credit Risk</TabsTrigger>
        </TabsList>

        {/* ================================================================ */}
        {/* TAB: AR AGING                                                     */}
        {/* ================================================================ */}
        <TabsContent value="aging" className="space-y-4">
          {/* Bucket summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {summaryBuckets.map(({ label, key, color }) => (
              <Card key={key} className="text-center py-4 px-3">
                <p className="text-xs text-muted-foreground uppercase font-semibold mb-1">{label}</p>
                <p className={`text-xl font-bold ${color}`}>
                  {agingQ.isLoading ? "…" : fmt(summary[key] ?? 0)}
                </p>
              </Card>
            ))}
          </div>

          {/* Per-customer table */}
          <div className="flex items-center gap-2">
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input
                placeholder="Search by customer ID…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9"
              />
            </div>
            {agingQ.isLoading && <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />}
            <Button variant="outline" size="sm" onClick={handleAgingPdf} disabled={agingPdfLoading} className="ml-auto">
              {agingPdfLoading ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <FileDown className="w-4 h-4 mr-2" />}
              Export PDF
            </Button>
          </div>

          {agingQ.isError && (
            <p className="text-sm text-destructive">Failed to load AR aging data.</p>
          )}

          <div className="rounded-xl border border-border overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-6" />
                  <TableHead>Customer ID</TableHead>
                  <TableHead className="text-right">Outstanding (₦)</TableHead>
                  <TableHead className="text-right">Invoice Amt (₦)</TableHead>
                  <TableHead className="text-center">Invoices</TableHead>
                  <TableHead className="text-center">Max Days Overdue</TableHead>
                  <TableHead>Bucket</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredCustomers.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7} className="text-center text-muted-foreground py-10">
                      {agingQ.isLoading ? "Loading…" : "No data"}
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredCustomers.map((c, idx) => {
                    const id = c.customer_id ?? idx;
                    const expanded = expandedRow === String(id);
                    return (
                      <>
                        <TableRow
                          key={`row-${id}`}
                          className="cursor-pointer hover:bg-muted/40"
                          onClick={() => setExpandedRow(expanded ? null : String(id))}
                        >
                          <TableCell className="p-2">
                            {expanded ? (
                              <ChevronDown className="w-4 h-4 text-muted-foreground" />
                            ) : (
                              <ChevronRight className="w-4 h-4 text-muted-foreground" />
                            )}
                          </TableCell>
                          <TableCell className="font-medium" onClick={(e) => e.stopPropagation()}>
                            <DrillLink to={c.ace_customer_id ? { type: "customer", id: String(c.ace_customer_id), label: c.name ?? c.customer_id } : null}>{c.name ?? c.customer_id}</DrillLink>
                            {c.name && <div className="text-[11px] font-normal text-muted-foreground">{c.customer_id}</div>}
                          </TableCell>
                          <TableCell className="text-right font-mono">
                            {fmt(c.total_balance)}
                          </TableCell>
                          <TableCell className="text-right font-mono">
                            {fmt(c.total_amount)}
                          </TableCell>
                          <TableCell className="text-center">{c.invoices_count ?? "—"}</TableCell>
                          <TableCell className="text-center">
                            {c.max_days_overdue ?? "—"}
                          </TableCell>
                          <TableCell>
                            <BucketBadge bucket={c.bucket_label ?? c.bucket ?? ""} />
                          </TableCell>
                        </TableRow>
                        {expanded && (
                          <TableRow key={`exp-${id}`} className="bg-muted/10">
                            <TableCell colSpan={7} className="px-6 py-3">
                              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                                <div>
                                  <p className="text-xs text-muted-foreground">Earliest Due</p>
                                  <p>{c.earliest_due_date || "—"}</p>
                                </div>
                                <div>
                                  <p className="text-xs text-muted-foreground">Max Days Overdue</p>
                                  <p>{c.max_days_overdue ?? "—"}</p>
                                </div>
                                <div>
                                  <p className="text-xs text-muted-foreground">Total Balance</p>
                                  <p className="font-semibold">{fmt(c.total_balance)}</p>
                                </div>
                                <div>
                                  <p className="text-xs text-muted-foreground">Customer ID</p>
                                  <p>{c.customer_id}</p>
                                </div>
                              </div>
                            </TableCell>
                          </TableRow>
                        )}
                      </>
                    );
                  })
                )}
              </TableBody>
            </Table>
          </div>

          <p className="text-xs text-muted-foreground">
            As of {aging.as_of ?? "—"}. Data sourced from Sage AR snapshot.
          </p>
        </TabsContent>

        {/* ================================================================ */}
        {/* TAB: ALERT RULES — extracted, see AlertRulesTab() above           */}
        {/* ================================================================ */}
        <TabsContent value="alerts" className="space-y-4">
          <AlertRulesTab />
        </TabsContent>

        {/* ================================================================ */}
        {/* TAB: INVOICE MATCH                                                */}
        {/* ================================================================ */}
        {/* ================================================================ */}
        <TabsContent value="pl" className="space-y-4">
          <div className="flex items-end gap-3 flex-wrap">
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">
                Period (YYYY-MM, optional)
              </label>
              <Input
                placeholder="e.g. 2025-03"
                value={plPeriod}
                onChange={(e) => setPlPeriod(e.target.value)}
                className="w-40"
              />
            </div>
            <Button
              variant="outline"
              onClick={() => void qc.invalidateQueries({ queryKey: ["finance-pl", plPeriod] })}
            >
              Refresh
            </Button>
            <Button onClick={handlePlPdf} disabled={plPdfLoading}>
              {plPdfLoading ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <FileDown className="w-4 h-4 mr-2" />
              )}
              Download PDF
            </Button>
          </div>

          {/* Totals cards */}
          {plQ.isLoading ? (
            <div className="flex justify-center py-12">
              <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {[
                  { label: "Total Revenue", value: plTotals.revenue, color: "text-green-500" },
                  { label: "Total Expenses", value: plTotals.expenses, color: "text-red-500" },
                  { label: "Net Profit", value: plTotals.net_profit, color: plTotals.net_profit >= 0 ? "text-green-500" : "text-red-500" },
                  { label: "Net Margin", value: `${(plTotals.net_margin_pct ?? 0).toFixed(1)}%`, color: "text-blue-500", raw: true },
                ].map(({ label, value, color, raw }) => (
                  <Card key={label} className="text-center py-4 px-3">
                    <p className="text-xs text-muted-foreground uppercase font-semibold mb-1">{label}</p>
                    <p className={`text-xl font-bold ${color}`}>
                      {raw ? value : fmt(value as number)}
                    </p>
                  </Card>
                ))}
              </div>

              {/* Monthly series table */}
              {plSeries.length > 0 && (
                <div className="rounded-xl border border-border overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Period</TableHead>
                        <TableHead className="text-right">Revenue (₦)</TableHead>
                        <TableHead className="text-right">Expenses (₦)</TableHead>
                        <TableHead className="text-right">Gross Profit (₦)</TableHead>
                        <TableHead className="text-right">Margin %</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {plSeries.map((row: any) => (
                        <TableRow key={row.period}>
                          <TableCell className="font-medium">{row.period}</TableCell>
                          <TableCell className="text-right font-mono">{fmt(row.revenue)}</TableCell>
                          <TableCell className="text-right font-mono">{fmt(row.expenses)}</TableCell>
                          <TableCell className={`text-right font-mono font-semibold ${row.gross_profit >= 0 ? "text-green-500" : "text-red-500"}`}>
                            {fmt(row.gross_profit)}
                          </TableCell>
                          <TableCell className="text-right">{row.margin_pct?.toFixed(1)}%</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}

              {plSeries.length === 0 && !plQ.isLoading && (
                <p className="text-center text-muted-foreground py-10">
                  No GL data for this period. Upload Sage GL CSV via Sage Import.
                </p>
              )}
            </>
          )}
        </TabsContent>

        {/* ================================================================ */}
        {/* TAB: CASH FLOW FORECAST (Tier 2)                                 */}
        {/* ================================================================ */}
        <TabsContent value="cashflow" className="space-y-4">
          {/* Controls */}
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">Forecast Horizon (weeks)</label>
              <select
                className="border rounded px-3 py-1.5 text-sm bg-background"
                value={cfWeeks}
                onChange={(e) => setCfWeeks(Number(e.target.value))}
              >
                {[4, 8, 12, 16, 26, 52].map((w) => (
                  <option key={w} value={w}>{w} weeks</option>
                ))}
              </select>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => void cashflowQ.refetch()}
              disabled={cashflowQ.isFetching}
            >
              {cashflowQ.isFetching ? <Loader2 className="w-4 h-4 animate-spin" /> : "Refresh"}
            </Button>
          </div>

          {cashflowQ.isLoading ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <>
              {/* Summary KPIs */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Card>
                  <CardHeader className="pb-1">
                    <CardTitle className="text-xs text-muted-foreground">Opening Balance</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-lg font-bold">{fmt(cf.opening_balance ?? 0)}</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-1">
                    <CardTitle className="text-xs text-muted-foreground flex items-center gap-1">
                      <TrendingUp className="w-3 h-3 text-green-500" /> Total Inflows
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-lg font-bold text-green-600 dark:text-green-300">{fmt(cfTotals.total_inflow ?? 0)}</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-1">
                    <CardTitle className="text-xs text-muted-foreground flex items-center gap-1">
                      <TrendingDown className="w-3 h-3 text-red-500" /> Total Outflows
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-lg font-bold text-red-600 dark:text-red-300">{fmt(cfTotals.total_outflow ?? 0)}</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-1">
                    <CardTitle className="text-xs text-muted-foreground">Closing Balance</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className={`text-lg font-bold ${(cfTotals.closing_balance ?? 0) >= 0 ? "text-green-600 dark:text-green-300" : "text-red-600 dark:text-red-300"}`}>
                      {fmt(cfTotals.closing_balance ?? 0)}
                    </p>
                  </CardContent>
                </Card>
              </div>

              {/* Weekly forecast table */}
              {cfForecast.length > 0 ? (
                <div className="rounded-md border overflow-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Week</TableHead>
                        <TableHead>Start Date</TableHead>
                        <TableHead>End Date</TableHead>
                        <TableHead className="text-right text-green-600 dark:text-green-300">Inflows</TableHead>
                        <TableHead className="text-right text-red-600 dark:text-red-300">Outflows</TableHead>
                        <TableHead className="text-right">Net</TableHead>
                        <TableHead className="text-right">Running Balance</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {cfForecast.map((row: any) => (
                        <TableRow key={row.week}>
                          <TableCell className="font-medium">W{row.week}</TableCell>
                          <TableCell className="text-muted-foreground text-xs">{row.start}</TableCell>
                          <TableCell className="text-muted-foreground text-xs">{row.end}</TableCell>
                          <TableCell className="text-right font-mono text-green-600 dark:text-green-300">{fmt(row.inflow)}</TableCell>
                          <TableCell className="text-right font-mono text-red-600 dark:text-red-300">{fmt(row.outflow)}</TableCell>
                          <TableCell className={`text-right font-mono font-semibold ${row.net >= 0 ? "text-green-500" : "text-red-500"}`}>
                            {row.net >= 0 ? "+" : ""}{fmt(row.net)}
                          </TableCell>
                          <TableCell className={`text-right font-mono ${row.running_balance >= 0 ? "" : "text-red-500"}`}>
                            {fmt(row.running_balance)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <p className="text-center text-muted-foreground py-10">
                  No forecast data. Upload AR (sales_invoices) and PO CSV via Sage Import.
                </p>
              )}

              {cf.note && (
                <p className="text-xs text-muted-foreground border rounded px-3 py-2 bg-muted/40">
                  ℹ {cf.note}
                </p>
              )}
            </>
          )}
        </TabsContent>

        {/* ================================================================ */}
        {/* TAB: PAYROLL SUMMARY (Tier 2)                                    */}
        {/* ================================================================ */}
        <TabsContent value="payroll" className="space-y-4">
          {/* Controls */}
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">Pay Period (optional)</label>
              <Input
                placeholder="e.g. 2025-04"
                value={payrollPeriod}
                onChange={(e) => setPayrollPeriod(e.target.value)}
                className="w-40"
              />
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => void payrollQ.refetch()}
              disabled={payrollQ.isFetching}
            >
              {payrollQ.isFetching ? <Loader2 className="w-4 h-4 animate-spin" /> : "Refresh"}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={handlePayrollPdf}
              disabled={payrollPdfLoading}
            >
              {payrollPdfLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileDown className="w-4 h-4" />}
              <span className="ml-1">Export PDF</span>
            </Button>
          </div>

          {payrollQ.isLoading ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <>
              {/* Summary KPIs */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Card>
                  <CardHeader className="pb-1">
                    <CardTitle className="text-xs text-muted-foreground flex items-center gap-1">
                      <Users className="w-3 h-3" /> Total Employees
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-2xl font-bold">{payroll.headcount ?? 0}</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-1">
                    <CardTitle className="text-xs text-muted-foreground">Total Gross Pay</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-lg font-bold">{fmt(payrollTotals.total_gross ?? 0)}</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-1">
                    <CardTitle className="text-xs text-muted-foreground">Total Net Pay</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-lg font-bold text-green-600 dark:text-green-300">{fmt(payrollTotals.total_net ?? 0)}</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-1">
                    <CardTitle className="text-xs text-muted-foreground">Total Overtime Cost</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-lg font-bold text-orange-500">{fmt(payrollTotals.total_overtime_cost ?? 0)}</p>
                  </CardContent>
                </Card>
              </div>

              {/* Period variance banner */}
              {payrollVariance && (
                <Card className="border-blue-500/30 bg-blue-500/5">
                  <CardContent className="py-3 flex flex-wrap items-center gap-4 text-sm">
                    <span className="font-medium">vs Prior Period:</span>
                    <span>Prior Gross: <strong>{fmt(payrollVariance.prior_total_gross)}</strong></span>
                    <span className={`font-semibold ${payrollVariance.change >= 0 ? "text-green-500" : "text-red-500"}`}>
                      {payrollVariance.change >= 0 ? "+" : ""}{fmt(payrollVariance.change)}
                      {payrollVariance.change_pct != null && ` (${payrollVariance.change_pct > 0 ? "+" : ""}${payrollVariance.change_pct}%)`}
                    </span>
                  </CardContent>
                </Card>
              )}

              {/* Department summary */}
              {payrollDepts.length > 0 && (
                <>
                  <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">By Department</h3>
                  <div className="rounded-md border overflow-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Department</TableHead>
                          <TableHead className="text-right">Headcount</TableHead>
                          <TableHead className="text-right">Gross Pay</TableHead>
                          <TableHead className="text-right">Net Pay</TableHead>
                          <TableHead className="text-right">OT Cost</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {payrollDepts.map((d: any) => (
                          <TableRow key={d.department}>
                            <TableCell className="font-medium">{d.department}</TableCell>
                            <TableCell className="text-right">{d.headcount}</TableCell>
                            <TableCell className="text-right font-mono">{fmt(d.total_gross)}</TableCell>
                            <TableCell className="text-right font-mono text-green-600 dark:text-green-300">{fmt(d.total_net)}</TableCell>
                            <TableCell className="text-right font-mono text-orange-500">{fmt(d.total_overtime_cost)}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </>
              )}

              {/* Employee detail */}
              {payrollEmployees.length > 0 ? (
                <>
                  <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">Employee Detail</h3>
                  <div className="rounded-md border overflow-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Employee ID</TableHead>
                          <TableHead>Department</TableHead>
                          <TableHead>Period</TableHead>
                          <TableHead className="text-right">Gross (₦)</TableHead>
                          <TableHead className="text-right">Deductions (₦)</TableHead>
                          <TableHead className="text-right">Net Pay (₦)</TableHead>
                          <TableHead className="text-right">OT Hours</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {payrollEmployees.map((emp: any, i: number) => (
                          <TableRow key={i}>
                            <TableCell className="font-mono text-xs">{emp.employee_id || "—"}</TableCell>
                            <TableCell>{emp.department || "—"}</TableCell>
                            <TableCell className="text-muted-foreground text-xs">{emp.period || "—"}</TableCell>
                            <TableCell className="text-right font-mono">{fmt(emp.gross_pay)}</TableCell>
                            <TableCell className="text-right font-mono text-red-500">{fmt(emp.deductions)}</TableCell>
                            <TableCell className="text-right font-mono text-green-600 dark:text-green-300">{fmt(emp.net_pay)}</TableCell>
                            <TableCell className="text-right">{emp.overtime_hours}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </>
              ) : (
                <p className="text-center text-muted-foreground py-10">
                  No payroll data. Upload HR Payroll CSV via Sage Import.
                </p>
              )}
            </>
          )}
        </TabsContent>

        {/* ================================================================ */}
        {/* TAB: CREDIT RISK SCORING (Tier 3)                                */}
        {/* ================================================================ */}
        <TabsContent value="credit" className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-muted-foreground">
              Risk scores computed from AR aging, outstanding balance, and alert event frequency.
            </p>
            <Button
              size="sm"
              variant="outline"
              onClick={() => void creditRiskQ.refetch()}
              disabled={creditRiskQ.isFetching}
            >
              {creditRiskQ.isFetching ? <Loader2 className="w-4 h-4 animate-spin" /> : "Refresh"}
            </Button>
          </div>

          {/* High-risk alert banner */}
          {criticalCount > 0 && (
            <Card className="border-red-500/40 bg-red-500/5">
              <CardContent className="py-3 flex items-center gap-2 text-sm text-red-700 dark:text-red-400">
                <ShieldAlert className="w-4 h-4 shrink-0" />
                <span>
                  <strong>{criticalCount}</strong> customer{criticalCount > 1 ? "s" : ""} with{" "}
                  <strong>High or Critical</strong> credit risk require immediate attention.
                </span>
              </CardContent>
            </Card>
          )}

          {creditRiskQ.isLoading ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <>
              {/* Tier distribution KPI cards */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {(["Critical", "High", "Medium", "Low"] as const).map((tier) => {
                  const colors: Record<string, string> = {
                    Critical: "text-red-600 dark:text-red-300",
                    High: "text-orange-500",
                    Medium: "text-yellow-600 dark:text-yellow-300",
                    Low: "text-green-600 dark:text-green-300",
                  };
                  return (
                    <Card key={tier}>
                      <CardHeader className="pb-1">
                        <CardTitle className={`text-xs font-semibold ${colors[tier]}`}>
                          {tier} Risk
                        </CardTitle>
                      </CardHeader>
                      <CardContent>
                        <p className={`text-2xl font-bold ${colors[tier]}`}>
                          {creditTierDist[tier] ?? 0}
                        </p>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>

              {/* Customer risk table */}
              {creditCustomers.length > 0 ? (
                <div className="rounded-md border overflow-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Customer ID</TableHead>
                        <TableHead className="text-right">Outstanding</TableHead>
                        <TableHead className="text-right">Max Days Overdue</TableHead>
                        <TableHead className="text-right">Alert Events</TableHead>
                        <TableHead className="text-right">Risk Score</TableHead>
                        <TableHead>Risk Tier</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {creditCustomers.map((c: any) => {
                        const tierColors: Record<string, string> = {
                          Critical: "bg-red-500/15 text-red-600 dark:text-red-400",
                          High: "bg-orange-500/15 text-orange-600 dark:text-orange-400",
                          Medium: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400",
                          Low: "bg-green-500/15 text-green-600 dark:text-green-400",
                        };
                        return (
                          <TableRow key={c.customer_id}>
                            <TableCell className="text-xs">
                              <DrillLink to={c.ace_customer_id ? { type: "customer", id: String(c.ace_customer_id), label: c.name ?? c.customer_id } : null}>{c.name ?? c.customer_id}</DrillLink>
                              {c.name && <div className="font-mono text-[11px] text-muted-foreground">{c.customer_id}</div>}
                            </TableCell>
                            <TableCell className="text-right font-mono">
                              {fmt(c.outstanding_balance)}
                            </TableCell>
                            <TableCell className="text-right">
                              <span
                                className={
                                  c.max_days_overdue > 90
                                    ? "text-red-500 font-semibold"
                                    : c.max_days_overdue > 60
                                    ? "text-orange-500"
                                    : c.max_days_overdue > 30
                                    ? "text-yellow-600 dark:text-yellow-300"
                                    : ""
                                }
                              >
                                {c.max_days_overdue}d
                              </span>
                            </TableCell>
                            <TableCell className="text-right">
                              {c.alert_events > 0 ? (
                                <span className="text-red-500 font-semibold">{c.alert_events}</span>
                              ) : (
                                0
                              )}
                            </TableCell>
                            <TableCell className="text-right">
                              <div className="flex items-center justify-end gap-2">
                                <div className="w-16 h-1.5 rounded-full bg-muted overflow-hidden">
                                  <div
                                    className={`h-full rounded-full ${
                                      c.risk_score >= 76
                                        ? "bg-red-500"
                                        : c.risk_score >= 51
                                        ? "bg-orange-500"
                                        : c.risk_score >= 21
                                        ? "bg-yellow-500"
                                        : "bg-green-500"
                                    }`}
                                    style={{ width: `${c.risk_score}%` }}
                                  />
                                </div>
                                <span className="text-xs font-mono font-semibold">
                                  {c.risk_score}
                                </span>
                              </div>
                            </TableCell>
                            <TableCell>
                              <span
                                className={`rounded px-2 py-0.5 text-xs font-semibold ${
                                  tierColors[c.risk_tier] ?? "bg-muted text-muted-foreground"
                                }`}
                              >
                                {c.risk_tier}
                              </span>
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <p className="text-center text-muted-foreground py-10">
                  No outstanding AR data to score. Upload Sales Invoices CSV via Sage Import.
                </p>
              )}

              {creditRisk.scoring_date && (
                <p className="text-xs text-muted-foreground">
                  Scores computed as of {creditRisk.scoring_date}. Total outstanding AR:{" "}
                  <strong>{fmt(creditRisk.total_ar_outstanding ?? 0)}</strong>.
                </p>
              )}
            </>
          )}
        </TabsContent>
      </Tabs>
    </motion.div>
  );
}
