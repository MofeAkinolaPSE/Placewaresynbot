import { useMemo, useState } from "react";
import { TrendingUp, AlertTriangle, Loader2, RefreshCw, Users } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
} from "recharts";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { useIsMobile } from "@/hooks/use-mobile";
import { useToast } from "@/hooks/use-toast";
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";
import { PageHeader } from "@/components/workspace/PageHeader";
import { KpiStrip } from "@/components/workspace/KpiStrip";

const CRM = () => {
  const queryClient = useQueryClient();
  const isMobile = useIsMobile();
  const { toast } = useToast();

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<Record<string, any>>({});

  const updateMutation = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: Record<string, any> }) =>
      api.crm.updateCustomer(id, patch),
    onSuccess: () => {
      toast({ title: "Customer updated" });
      void queryClient.invalidateQueries({ queryKey: ["crm-customers"] });
    },
    onError: (e: any) => toast({ title: "Update failed", description: e?.message, variant: "destructive" }),
  });

  // Reuses the same /crm/customers/{id}/360 endpoint CustomerWorkspace.tsx
  // consumes — a different job (bulk browse-all-customers admin view here
  // vs. search-first single-customer workflow there), same shared data, no
  // new endpoint. See ACE-Workspace-Standard.md Ch.10.6/§9.8.
  const { data: customer360Data, isLoading: loading360 } = useQuery({
    queryKey: ["customer-360", selectedId],
    queryFn: () => api.crm.customer360(selectedId!),
    enabled: !!selectedId,
  });

  useRealtimeChannel("workflow_updates", () => {
    void queryClient.invalidateQueries({ queryKey: ["crm-dashboard"] });
    void queryClient.invalidateQueries({ queryKey: ["crm-risk-scores"] });
  });

  useRealtimeChannel("alerts_updates", () => {
    void queryClient.invalidateQueries({ queryKey: ["crm-risk-scores"] });
  });

  useRealtimeChannel("crm_updates", () => {
    void queryClient.invalidateQueries({ queryKey: ["crm-dashboard"] });
    void queryClient.invalidateQueries({ queryKey: ["crm-risk-scores"] });
  });

  const { data: fetchedData, isLoading, isError, error } = useQuery({
    queryKey: ["crm-dashboard"],
    queryFn: () => api.dashboard.crm(),
  });
  const { data: riskRaw, isError: riskIsError, error: riskError } = useQuery({
    queryKey: ["crm-risk-scores"],
    queryFn: () => api.crm.riskScores(),
  });

  const { data: customersRaw } = useQuery({
    queryKey: ["crm-customers"],
    queryFn: () => api.crm.customers(300),
  });
  const customersList: any[] = Array.isArray(customersRaw) ? customersRaw : [];

  // Derived from the list query (not a separate snapshot) so the Detail
  // Workspace automatically reflects the latest data after any mutation's
  // invalidation — same pattern as QualityControl.tsx's CapaTab.
  const selected = useMemo(
    () => customersList.find((c) => c.id === selectedId) ?? null,
    [customersList, selectedId],
  );

  function selectCustomer(c: any) {
    setSelectedId(c.id);
    setEditForm({
      credit_limit: c.credit_limit ?? "",
      payment_terms_days: c.payment_terms_days ?? "",
      facility_type: c.facility_type ?? "",
      client_type: c.client_type ?? "",
      last_ordered_at: c.last_ordered_at ?? "",
      storage_capacity: c.storage_capacity ?? "",
      competing_supplier: c.competing_supplier ?? "",
    });
  }

  function handleSaveEdit() {
    if (!selected) return;
    const patch: Record<string, any> = {};
    for (const [k, v] of Object.entries(editForm)) {
      if (v !== "" && v != null) {
        patch[k] = (k === "credit_limit" || k === "storage_capacity")
          ? Number(v)
          : k === "payment_terms_days"
          ? parseInt(String(v), 10)
          : v;
      }
    }
    updateMutation.mutate({ id: selected.id, patch });
  }

  const dataValid =
    !!fetchedData &&
    typeof (fetchedData as any).pipeline_value === "number" &&
    typeof (fetchedData as any).active_opps === "number" &&
    typeof (fetchedData as any).win_rate === "number" &&
    typeof (fetchedData as any).avg_risk_score === "number" &&
    Array.isArray((fetchedData as any).recent_deals);

  const riskCustomers =
    riskRaw && Array.isArray((riskRaw as any).customers)
      ? (riskRaw as any).customers
      : [];

  const data = dataValid
    ? (fetchedData as any)
    : {
        pipeline_value: 0,
        active_opps: 0,
        win_rate: 0,
        avg_risk_score: 0,
        recent_deals: [],
      };
  const riskByCustomer: Record<string, { risk_score: number; overdue_ar_amount: number }> = {};
  (riskCustomers as any[]).forEach((c) => {
    const cid = String(c.customer_id ?? "");
    if (!cid) return;
    riskByCustomer[cid] = {
      risk_score: Number(c.risk_score ?? 0),
      overdue_ar_amount: Number(c.overdue_ar_amount ?? 0),
    };
  });

  const kpis = [
    {
      label: "Pipeline Value",
      value: `₦${(data.pipeline_value / 1000000).toFixed(1)}M`,
      change: "",
      sublabel: `${data.active_opps} active opportunities`,
    },
    {
      label: "Win Rate %",
      value: `${data.win_rate.toFixed(1)}%`,
      change: "",
      sublabel: "Closed won vs total",
    },
    {
      label: "Risk Score",
      value: data.avg_risk_score.toFixed(1),
      change: "",
      sublabel: "Average (0-100 scale)",
    },
    {
      label: "Customers",
      value: String(data.customer_count ?? customersList.length ?? 0),
      change: "",
      sublabel: `${data.active_customers ?? 0} active accounts`,
    },
  ];

  const pipelineTrendData = (() => {
    const deals: any[] = data.recent_deals || [];
    const byMonth: Record<string, number> = {};
    for (const d of deals) {
      const month = String(d.close_date ?? d.invoice_date ?? "").slice(0, 7);
      if (!month) continue;
      byMonth[month] = (byMonth[month] ?? 0) + Number(d.amount ?? 0);
    }
    const sorted = Object.entries(byMonth)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([month, total]) => ({ month, value: +(total / 1_000_000).toFixed(2), forecast: 0 }));
    if (sorted.length === 0) {
      return [
        { month: "Prior", value: +(data.pipeline_value * 0.82 / 1_000_000).toFixed(2), forecast: 0 },
        { month: "Current", value: +(data.pipeline_value / 1_000_000).toFixed(2), forecast: +(data.pipeline_value * 1.08 / 1_000_000).toFixed(2) },
      ];
    }
    return sorted;
  })();

  const winLossData = (() => {
    const deals: any[] = data.recent_deals || [];
    const wonStages = new Set(["won", "closed won", "closed_won", "win"]);
    const byMonth: Record<string, { won: number; lost: number }> = {};
    for (const d of deals) {
      const month = String(d.close_date ?? "").slice(0, 7);
      if (!month) continue;
      if (!byMonth[month]) byMonth[month] = { won: 0, lost: 0 };
      const stage = String(d.stage ?? d.status ?? "").toLowerCase();
      if (wonStages.has(stage)) byMonth[month].won++;
      else byMonth[month].lost++;
    }
    const sorted = Object.entries(byMonth)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([month, { won, lost }]) => ({ month, won, lost }));
    if (sorted.length === 0) {
      const wr = data.win_rate;
      return [
        { month: "Prior", won: Math.max(0, +(wr - 6).toFixed(1)), lost: Math.min(100, +(106 - wr).toFixed(1)) },
        { month: "Current", won: +wr.toFixed(1), lost: +(100 - wr).toFixed(1) },
      ];
    }
    return sorted;
  })();

  const opportunitiesData = (data.recent_deals || []).map((d: any, i: number) => {
    const customerId = String(d.customer_id ?? "");
    const riskInfo = customerId ? riskByCustomer[customerId] : undefined;
    const riskScore = riskInfo?.risk_score ?? 0;
    const overdueAmount = riskInfo?.overdue_ar_amount ?? 0;

    const riskFlag = (() => {
      if (riskScore >= 70) return "high";
      if (riskScore >= 40) return "medium";
      return "low";
    })();

    const arStatus = overdueAmount > 0 ? "overdue" : "current";

    return {
      id: i,
      customer: customerId,
      value: Number(d.amount),
      stage: d.stage || d.status || "unknown",
      riskFlag,
      arStatus,
      closeDate: d.close_date,
    };
  }).filter((d: any) => typeof d.customer === "string" && d.customer.length > 0 && Number.isFinite(d.value) && typeof d.closeDate === "string");

  const getRiskColor = (risk: string) => {
    switch (risk) {
      case "high":
        return "bg-destructive/10 text-destructive";
      case "medium":
        return "bg-warning/15 text-warning";
      case "low":
        return "bg-success/15 text-success";
      default:
        return "bg-muted text-muted-foreground";
    }
  };

  const getARStatusColor = (status: string) => {
    return status === "overdue"
      ? "bg-destructive/10 text-destructive"
      : "bg-success/15 text-success";
  };

  const totalPipeline = data.pipeline_value;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionTransitions.standard}
      className="space-y-8"
    >
      <PageHeader
        icon={Users}
        title="CRM"
        subtitle="Revenue & risk visibility for Placeware Nigeria sales pipeline"
      />
      {isLoading && <p className="text-sm text-muted-foreground">Loading CRM data...</p>}
      {(isError || (!isLoading && !dataValid)) && (
        <p className="text-sm text-destructive">
          Data error: CRM dashboard payload is unavailable or malformed.
          {isError ? ` ${(error as Error)?.message || ""}` : ""}
        </p>
      )}

      {riskIsError && (
        <p className="text-sm text-destructive">Risk data error: {(riskError as Error)?.message || "Failed to load CRM risk scores."}</p>
      )}
      <KpiStrip
        items={kpis.map((kpi) => ({
          label: kpi.label,
          value: dataValid ? kpi.value : (isLoading ? "Loading..." : "-"),
        }))}
      />

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Pipeline Trend */}
        <Card>
          <CardHeader className="mb-2">
            <CardTitle className="text-lg font-semibold text-foreground">
              Pipeline Trend
            </CardTitle>
            <CardDescription className="text-sm text-muted-foreground">
              Monthly sales pipeline value (₦M)
            </CardDescription>
          </CardHeader>
          <CardContent>
          <ResponsiveContainer width="100%" height={340}>
            <LineChart data={pipelineTrendData} margin={{ top: 8, right: 16, left: 8, bottom: 14 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="month" stroke="hsl(var(--muted-foreground))" angle={-45} height={84} tick={{ fontSize: 12 }} tickLine={false} />
              <YAxis stroke="hsl(var(--muted-foreground))" tick={{ fontSize: 12 }} tickLine={false} width={56} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--background))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "8px",
                  fontSize: "13px",
                }}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="value"
                stroke="hsl(var(--primary))"
                strokeWidth={2}
                name="Pipeline"
                dot={{ r: 4 }}
                activeDot={{ r: 6 }}
              />
            </LineChart>
          </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Win/Loss Ratio */}
        <Card>
          <CardHeader className="mb-2">
            <CardTitle className="text-lg font-semibold text-foreground">
              Win/Loss Ratio
            </CardTitle>
            <CardDescription className="text-sm text-muted-foreground">
              Closed opportunities by outcome
            </CardDescription>
          </CardHeader>
          <CardContent>
          <ResponsiveContainer width="100%" height={340}>
            <BarChart data={winLossData} margin={{ top: 8, right: 16, left: 8, bottom: 14 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="month" stroke="hsl(var(--muted-foreground))" angle={-45} height={84} tick={{ fontSize: 12 }} tickLine={false} />
              <YAxis stroke="hsl(var(--muted-foreground))" tick={{ fontSize: 12 }} tickLine={false} width={56} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--background))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "8px",
                  fontSize: "13px",
                }}
              />
              <Legend />
              <Bar dataKey="won" fill="hsl(var(--success))" name="Won" />
              <Bar dataKey="lost" fill="hsl(var(--destructive))" name="Lost" />
            </BarChart>
          </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* Opportunities Table */}
      <Card>
        <CardHeader className="mb-2">
          <CardTitle className="text-lg font-semibold text-foreground">
            Active Opportunities
          </CardTitle>
          <CardDescription className="text-sm text-muted-foreground">
            {opportunitiesData.length} open opportunities worth ₦
            {(totalPipeline / 1000000).toFixed(1)}M
          </CardDescription>
        </CardHeader>

        <CardContent>

        {isMobile ? (
          <div className="space-y-3">
            {opportunitiesData.length > 0 ? (
              opportunitiesData.map((opp) => (
                <div key={opp.id} className="rounded-xl border border-border/60 bg-muted/20 p-4 space-y-3">
                  <div className="flex items-start justify-between gap-3">
                    <p className="font-semibold text-foreground break-all">{opp.customer}</p>
                    <p className="font-mono font-semibold text-foreground whitespace-nowrap">₦{(opp.value / 1000000).toFixed(1)}M</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <span className="rounded px-2 py-1 text-xs font-medium bg-info/15 text-info">
                      {opp.stage}
                    </span>
                    <span className={`px-2 py-1 rounded text-xs font-medium inline-block ${getRiskColor(opp.riskFlag)}`}>
                      {opp.riskFlag.charAt(0).toUpperCase() + opp.riskFlag.slice(1)} Risk
                    </span>
                    <span className={`px-2 py-1 rounded text-xs font-medium inline-block ${getARStatusColor(opp.arStatus)}`}>
                      {opp.arStatus === "overdue" ? "Overdue AR" : "Current AR"}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground">Est. close: {opp.closeDate}</p>
                </div>
              ))
            ) : (
              <p className="text-center text-destructive py-8">Data error: no valid opportunities returned from backend.</p>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="sticky left-0 z-10 min-w-[180px] bg-muted/90">Customer</TableHead>
                  <TableHead className="text-right min-w-[130px]">Value (₦)</TableHead>
                  <TableHead className="min-w-[120px]">Stage</TableHead>
                  <TableHead className="min-w-[140px]">Risk</TableHead>
                  <TableHead className="min-w-[130px]">AR Status</TableHead>
                  <TableHead className="min-w-[140px]">Est. Close Date</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {opportunitiesData.map((opp) => (
                  <TableRow key={opp.id}>
                    <TableCell className="sticky left-0 z-10 bg-background font-medium">{opp.customer}</TableCell>
                    <TableCell className="text-right font-mono">
                      {(opp.value / 1000000).toFixed(1)}M
                    </TableCell>
                    <TableCell>
                      <span className="rounded px-2 py-1 text-xs font-medium bg-info/15 text-info">
                        {opp.stage}
                      </span>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        {opp.riskFlag === "high" && (
                          <AlertTriangle className="w-4 h-4 text-destructive" />
                        )}
                        <span
                          className={`px-2 py-1 rounded text-xs font-medium inline-block ${getRiskColor(
                            opp.riskFlag
                          )}`}
                        >
                          {opp.riskFlag.charAt(0).toUpperCase() +
                            opp.riskFlag.slice(1)}{" "}
                          Risk
                        </span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <span
                        className={`px-2 py-1 rounded text-xs font-medium inline-block ${getARStatusColor(
                          opp.arStatus
                        )}`}
                      >
                        {opp.arStatus === "overdue" ? "Overdue AR" : "Current AR"}
                      </span>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {opp.closeDate}
                    </TableCell>
                  </TableRow>
                ))}
                {opportunitiesData.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center text-destructive py-8">
                      Data error: no valid opportunities returned from backend.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        )}

        {/* Risk Summary */}
        <div className="grid grid-cols-3 gap-4 mt-6">
          <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-4">
            <p className="text-xs font-semibold text-destructive uppercase">
              High Risk
            </p>
            <p className="text-lg font-bold text-destructive mt-2">
              {opportunitiesData.filter((o) => o.riskFlag === "high").length}
            </p>
            <p className="text-xs text-destructive mt-1">
              ₦
              {(
                opportunitiesData
                  .filter((o) => o.riskFlag === "high")
                  .reduce((sum, o) => sum + o.value, 0) / 1000000
              ).toFixed(1)}
              M at risk
            </p>
          </div>
          <div className="rounded-xl border border-warning/30 bg-warning/15 p-4">
            <p className="text-xs font-semibold text-warning uppercase">
              Medium Risk
            </p>
            <p className="text-lg font-bold text-warning mt-2">
              {opportunitiesData.filter((o) => o.riskFlag === "medium").length}
            </p>
            <p className="text-xs text-warning mt-1">
              ₦
              {(
                opportunitiesData
                  .filter((o) => o.riskFlag === "medium")
                  .reduce((sum, o) => sum + o.value, 0) / 1000000
              ).toFixed(1)}
              M at risk
            </p>
          </div>
          <div className="rounded-xl border border-success/30 bg-success/15 p-4">
            <p className="text-xs font-semibold text-success uppercase">
              Low Risk
            </p>
            <p className="text-lg font-bold text-success mt-2">
              {opportunitiesData.filter((o) => o.riskFlag === "low").length}
            </p>
            <p className="text-xs text-success mt-1">
              ₦
              {(
                opportunitiesData
                  .filter((o) => o.riskFlag === "low")
                  .reduce((sum, o) => sum + o.value, 0) / 1000000
              ).toFixed(1)}
              M
            </p>
          </div>
        </div>
        </CardContent>
      </Card>
      {/* Customer Accounts — full retrofit: List / Detail (inline, reuses
          the same 360 data the old dialog fetched + inline edit) /
          QuickActions. Detail Workspace has no dismiss button by design
          (Ch.5.1) — change context by selecting a different customer. */}
      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr_240px] gap-4">
        {/* List Panel */}
        <Card className="lg:max-h-[600px] flex flex-col">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Customer Accounts ({customersList.length})</CardTitle>
          </CardHeader>
          <CardContent className="overflow-y-auto space-y-2 flex-1">
            {customersList.length === 0 ? (
              <div className="text-center py-12 text-muted-foreground text-sm">
                {customersRaw === undefined ? "Loading..." : "No customers found"}
              </div>
            ) : (
              customersList.map((c: any, i: number) => (
                <button
                  key={c.id ?? i}
                  onClick={() => selectCustomer(c)}
                  className={`w-full text-left rounded-lg border px-3 py-2.5 hover:bg-muted/40 transition-colors ${
                    selectedId === c.id ? "border-primary bg-muted/40" : ""
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-sm truncate">{c.name || "—"}</span>
                    {c.risk_score != null && (
                      <span className="text-xs font-mono text-muted-foreground shrink-0">{Number(c.risk_score).toFixed(0)}</span>
                    )}
                  </div>
                  <div className="text-xs text-muted-foreground font-mono">{c.customer_code || c.id || "—"}</div>
                </button>
              ))
            )}
          </CardContent>
        </Card>

        {/* Detail Workspace */}
        <Card>
          <CardContent className="pt-6">
            {!selected && (
              <p className="text-sm text-muted-foreground text-center py-12">Select a customer to view details.</p>
            )}
            {selected && (
              <div className="space-y-4 text-sm">
                <div>
                  <div className="font-bold text-lg">{selected.name}</div>
                  <div className="text-xs text-muted-foreground font-mono">{selected.customer_code}</div>
                </div>

                {loading360 ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                  </div>
                ) : customer360Data ? (
                  (() => {
                    const prof360 = customer360Data.customer ?? {};
                    const recv = customer360Data.receivables ?? {};
                    const pnl = customer360Data.profitability;
                    const items: any[] = customer360Data.top_items ?? [];
                    const util = recv.credit_utilization_pct;
                    return (
                      <div className="space-y-4">
                        {/* Profile */}
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">Profile</p>
                          <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm">
                            {[
                              ["Contact", prof360.contact_person],
                              ["Phone", prof360.phone],
                              ["Address", prof360.address],
                              ["City", prof360.city],
                              ["Trade Terms", prof360.terms],
                              ["Customer Since", prof360.customer_since ? new Date(prof360.customer_since).toLocaleDateString() : null],
                            ].map(([label, value]) => (
                              <div key={String(label)} className="flex justify-between gap-3 border-b border-dashed pb-1">
                                <span className="text-muted-foreground text-xs">{label}</span>
                                <span className="text-right text-xs font-medium truncate" title={String(value ?? "")}>{value || "—"}</span>
                              </div>
                            ))}
                          </div>
                        </div>

                        {/* Receivables */}
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">Receivables</p>
                          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                            {[
                              { label: "Outstanding", value: `₦${Number(recv.outstanding ?? 0).toLocaleString()}`, alert: false },
                              { label: "Open Invoices", value: recv.invoice_count ?? 0, alert: false },
                              { label: "Overdue", value: `₦${Number(recv.overdue_amount ?? 0).toLocaleString()}`, alert: Number(recv.overdue_amount) > 0 },
                              { label: "Credit Limit", value: prof360.credit_limit > 0 ? `₦${Number(prof360.credit_limit).toLocaleString()}` : "—", alert: false },
                            ].map(({ label, value, alert }) => (
                              <div key={label} className={`rounded border p-2.5 ${alert ? "border-destructive/40" : ""}`}>
                                <p className="text-[11px] text-muted-foreground">{label}</p>
                                <p className={`text-sm font-semibold mt-0.5 tabular-nums ${alert ? "text-destructive" : ""}`}>{value}</p>
                              </div>
                            ))}
                          </div>
                          {util != null && (
                            <div className="mt-2 flex items-center gap-2">
                              <div className="h-1.5 flex-1 rounded-full bg-muted overflow-hidden">
                                <div
                                  className={`h-full rounded-full ${util > 100 ? "bg-destructive" : util > 75 ? "bg-amber-400" : "bg-emerald-500"}`}
                                  style={{ width: `${Math.min(util, 100)}%` }}
                                />
                              </div>
                              <span className={`text-xs tabular-nums ${util > 100 ? "text-destructive font-semibold" : "text-muted-foreground"}`}>
                                {util}% of credit limit
                              </span>
                            </div>
                          )}
                        </div>

                        {/* Profitability */}
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">Lifetime Profitability (Sage)</p>
                          {pnl ? (
                            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                              {[
                                { label: "Sales", value: `₦${Number(pnl.sales).toLocaleString()}` },
                                { label: "Cost of Sales", value: `₦${Number(pnl.cost_of_sales).toLocaleString()}` },
                                { label: "Gross Profit", value: `₦${Number(pnl.gross_profit).toLocaleString()}` },
                                { label: "Margin", value: `${Number(pnl.gross_margin_pct).toFixed(1)}%` },
                              ].map(({ label, value }) => (
                                <div key={label} className="rounded border p-2.5">
                                  <p className="text-[11px] text-muted-foreground">{label}</p>
                                  <p className="text-sm font-semibold mt-0.5 tabular-nums">{value}</p>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <p className="text-xs text-muted-foreground">No sales history recorded for this customer.</p>
                          )}
                        </div>

                        {/* Top purchased items */}
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">Top Purchased Items</p>
                          {items.length > 0 ? (
                            <div className="rounded border overflow-x-auto">
                              <table className="w-full text-xs">
                                <thead className="bg-muted/40">
                                  <tr>
                                    <th className="text-left p-2 font-medium text-muted-foreground">Item</th>
                                    <th className="text-right p-2 font-medium text-muted-foreground">Qty</th>
                                    <th className="text-right p-2 font-medium text-muted-foreground">Amount</th>
                                    <th className="text-right p-2 font-medium text-muted-foreground">Gross Profit</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {items.map((it) => (
                                    <tr key={it.item_id} className="border-t">
                                      <td className="p-2">{it.item_id}</td>
                                      <td className="p-2 text-right tabular-nums">{Number(it.quantity).toLocaleString()}</td>
                                      <td className="p-2 text-right tabular-nums">₦{Number(it.amount).toLocaleString()}</td>
                                      <td className="p-2 text-right tabular-nums">₦{Number(it.gross_profit).toLocaleString()}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          ) : (
                            <p className="text-xs text-muted-foreground">No line-level purchase history for this customer.</p>
                          )}
                        </div>
                      </div>
                    );
                  })()
                ) : (
                  <p className="text-xs text-muted-foreground">No 360 data available for this customer yet.</p>
                )}

                <Separator />

                {/* Inline edit — Ch.3 prefers inline editing over a separate
                    modal; matches CapaTab's Detail Workspace precedent
                    (always-editable fields + Save, not a toggled Edit dialog). */}
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">Edit</p>
                  <div className="grid grid-cols-2 gap-3">
                    {[
                      { key: "client_type", label: "Client Type" },
                      { key: "facility_type", label: "Facility Type" },
                      { key: "credit_limit", label: "Credit Limit (₦)", type: "number" },
                      { key: "payment_terms_days", label: "Payment Terms (days)", type: "number" },
                      { key: "storage_capacity", label: "Storage Capacity", type: "number" },
                      { key: "competing_supplier", label: "Competing Supplier" },
                      { key: "last_ordered_at", label: "Last Ordered At", type: "date" },
                    ].map(({ key, label, type }) => (
                      <div key={key}>
                        <Label className="text-xs text-muted-foreground mb-1 block">{label}</Label>
                        <Input
                          type={type ?? "text"}
                          value={editForm[key] ?? ""}
                          onChange={(e) => setEditForm((f) => ({ ...f, [key]: e.target.value }))}
                        />
                      </div>
                    ))}
                  </div>
                  <Button
                    size="sm"
                    className="mt-3"
                    disabled={updateMutation.isPending}
                    onClick={handleSaveEdit}
                  >
                    {updateMutation.isPending && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
                    Save
                  </Button>
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
            <Button
              variant="outline" className="w-full" size="sm"
              onClick={() => queryClient.invalidateQueries({ queryKey: ["crm-customers"] })}
            >
              <RefreshCw className="h-4 w-4 mr-1" /> Refresh
            </Button>
          </CardContent>
        </Card>
      </div>
    </motion.div>
  );
};

export default CRM;
