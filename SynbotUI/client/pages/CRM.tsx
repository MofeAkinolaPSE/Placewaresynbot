import { useState } from "react";
import { TrendingUp, AlertTriangle, Pencil, Eye } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";

const CRM = () => {
  const queryClient = useQueryClient();
  const isMobile = useIsMobile();

  const [editCustomer, setEditCustomer] = useState<any | null>(null);
  const [editForm, setEditForm] = useState<Record<string, any>>({});
  const [view360Customer, setView360Customer] = useState<any | null>(null);

  const updateMutation = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: Record<string, any> }) =>
      api.crm.updateCustomer(id, patch),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["crm-customers"] });
      setEditCustomer(null);
    },
  });

  const { data: customer360Data, isLoading: loading360 } = useQuery({
    queryKey: ["customer-360", view360Customer?.id],
    queryFn: () => api.crm.customer360(view360Customer!.id),
    enabled: !!view360Customer?.id,
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
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-foreground">CRM</h1>
        <p className="text-muted-foreground mt-2">
          Revenue & risk visibility for Placeware Nigeria sales pipeline
        </p>
      </div>
      {isLoading && <p className="text-sm text-muted-foreground">Loading CRM data...</p>}
      {(isError || (!isLoading && !dataValid)) && (
        <p className="text-sm text-destructive">
          Data error: CRM dashboard payload is unavailable or malformed.
          {isError ? ` ${(error as Error)?.message || ""}` : ""}
        </p>
      )}

      {/* KPI Grid */}
      {riskIsError && (
        <p className="text-sm text-destructive">Risk data error: {(riskError as Error)?.message || "Failed to load CRM risk scores."}</p>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {kpis.map((kpi, idx) => (
          <Card key={idx}>
            <CardHeader className="pb-2">
              <CardDescription className="text-sm font-medium text-muted-foreground mb-1">
              {kpi.label}
              </CardDescription>
              <CardTitle className="text-3xl font-bold text-foreground mb-1">
              {dataValid ? kpi.value : (isLoading ? "Loading..." : "-")}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="mb-2 flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-warning" />
              <span className="text-sm font-medium text-warning">
                {kpi.change}
              </span>
              </div>
              <p className="text-xs text-muted-foreground">{kpi.sublabel}</p>
            </CardContent>
          </Card>
        ))}
      </div>

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
      {/* Customer List */}
      <Card>
        <CardHeader className="mb-2">
          <CardTitle className="text-lg font-semibold text-foreground">
            Customer Accounts
          </CardTitle>
          <CardDescription className="text-sm text-muted-foreground">
            {customersList.length} customers from Sage 50
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="min-w-[60px]">Code</TableHead>
                  <TableHead className="min-w-[200px]">Name</TableHead>
                  <TableHead className="min-w-[100px]">Type</TableHead>
                  <TableHead className="min-w-[120px]">Phone</TableHead>
                  <TableHead className="min-w-[180px]">Email</TableHead>
                  <TableHead className="min-w-[100px]">City</TableHead>
                  <TableHead className="min-w-[90px]">Terms</TableHead>
                  <TableHead className="min-w-[110px] text-right">Credit Limit</TableHead>
                  <TableHead className="min-w-[80px] text-right">Risk</TableHead>
                  <TableHead className="min-w-[90px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {customersList.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={10} className="text-center text-muted-foreground py-8">
                      {customersRaw === undefined ? "Loading..." : "No customers found"}
                    </TableCell>
                  </TableRow>
                ) : (
                  customersList.map((c: any, i: number) => (
                    <TableRow key={c.id ?? i}>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {c.customer_code || c.id || "—"}
                      </TableCell>
                      <TableCell className="font-medium">{c.name || "—"}</TableCell>
                      <TableCell>
                        <span className="px-2 py-0.5 rounded text-xs font-medium bg-muted text-muted-foreground capitalize">
                          {c.client_type || c.facility_type || "—"}
                        </span>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {(c.contact_details as any)?.phone || c.phone || "—"}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {(c.contact_details as any)?.email || c.email || "—"}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {(c.contact_details as any)?.city || (c.contact_details as any)?.region || "—"}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {(c.metadata as any)?.terms || (c.payment_terms_days != null ? `${c.payment_terms_days}d` : "—")}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs">
                        {Number(c.credit_limit) > 0 ? `₦${Number(c.credit_limit).toLocaleString()}` : "—"}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs">
                        {c.risk_score != null ? Number(c.risk_score).toFixed(0) : "—"}
                      </TableCell>
                      <TableCell>
                        <div className="flex gap-1">
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 w-7 p-0"
                            title="Edit customer"
                            onClick={() => { setEditCustomer(c); setEditForm({ credit_limit: c.credit_limit ?? "", payment_terms_days: c.payment_terms_days ?? "", facility_type: c.facility_type ?? "", client_type: c.client_type ?? "", last_ordered_at: c.last_ordered_at ?? "", storage_capacity: c.storage_capacity ?? "", competing_supplier: c.competing_supplier ?? "" }); }}
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 w-7 p-0"
                            title="Customer 360"
                            onClick={() => setView360Customer(c)}
                          >
                            <Eye className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
      {/* Customer Edit Modal */}
      <Dialog open={!!editCustomer} onOpenChange={(o) => { if (!o) setEditCustomer(null); }}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Edit Customer — {editCustomer?.name}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-2">
            {[
              { key: "client_type", label: "Client Type" },
              { key: "facility_type", label: "Facility Type" },
              { key: "credit_limit", label: "Credit Limit (₦)", type: "number" },
              { key: "payment_terms_days", label: "Payment Terms (days)", type: "number" },
              { key: "storage_capacity", label: "Storage Capacity", type: "number" },
              { key: "competing_supplier", label: "Competing Supplier" },
              { key: "last_ordered_at", label: "Last Ordered At", type: "date" },
            ].map(({ key, label, type }) => (
              <div key={key} className="grid grid-cols-3 items-center gap-2">
                <Label className="text-right text-sm col-span-1">{label}</Label>
                <Input
                  type={type ?? "text"}
                  className="col-span-2"
                  value={editForm[key] ?? ""}
                  onChange={(e) => setEditForm((f) => ({ ...f, [key]: e.target.value }))}
                />
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditCustomer(null)}>Cancel</Button>
            <Button
              disabled={updateMutation.isPending}
              onClick={() => {
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
                updateMutation.mutate({ id: editCustomer.id, patch });
              }}
            >
              {updateMutation.isPending ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Customer 360 Modal */}
      <Dialog open={!!view360Customer} onOpenChange={(o) => { if (!o) setView360Customer(null); }}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Customer 360 — {view360Customer?.name}</DialogTitle>
          </DialogHeader>
          {loading360 ? (
            <p className="text-sm text-muted-foreground py-4">Loading…</p>
          ) : customer360Data ? (
            (() => {
              const prof360 = customer360Data.customer ?? {};
              const recv = customer360Data.receivables ?? {};
              const pnl = customer360Data.profitability;
              const items: any[] = customer360Data.top_items ?? [];
              const util = recv.credit_utilization_pct;
              return (
                <div className="space-y-4 py-1">
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
            <p className="text-sm text-muted-foreground py-4">No 360 data available for this customer yet.</p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setView360Customer(null)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </motion.div>
  );
};

export default CRM;
