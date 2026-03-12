import { TrendingUp, AlertTriangle } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";

const CRM = () => {
  const queryClient = useQueryClient();

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
      label: "Sales Cycle",
      value: "Data unavailable",
      change: "",
      sublabel: "Insufficient Data",
    },
  ];

  const pipelineTrendData = [{ month: "Current", value: data.pipeline_value / 1000000, forecast: 0 }];
  const winLossData = [{ month: "Current", won: data.win_rate, lost: 100 - data.win_rate, rate: data.win_rate }];

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
              <CardTitle className="text-2xl font-bold text-foreground mb-1">
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
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={pipelineTrendData}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="month" stroke="hsl(var(--muted-foreground))" angle={-45} height={80} />
              <YAxis stroke="hsl(var(--muted-foreground))" />
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--background))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "8px",
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
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={winLossData}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="month" stroke="hsl(var(--muted-foreground))" angle={-45} height={80} />
              <YAxis stroke="hsl(var(--muted-foreground))" />
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--background))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "8px",
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

        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Customer</TableHead>
                <TableHead className="text-right">Value (₦)</TableHead>
                <TableHead>Stage</TableHead>
                <TableHead>Risk</TableHead>
                <TableHead>AR Status</TableHead>
                <TableHead>Est. Close Date</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {opportunitiesData.map((opp) => (
                <TableRow key={opp.id}>
                  <TableCell className="font-medium">{opp.customer}</TableCell>
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
    </motion.div>
  );
};

export default CRM;
