import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  ArrowRight, AlertTriangle, TrendingUp, TrendingDown, Archive,
  Activity, Users, ShieldCheck, Zap, AlertCircle,
} from "lucide-react";
import { Link } from "react-router-dom";
import {
  ExecutiveBriefing, ExecutiveSummaryResponse, ArTrendsResponse,
  HrSummaryResponse, TrendFlag, OpsKpis, OpsForecast,
  RiskSignalsResponse, RecommendationsResponse, AnomaliesResponse,
} from "@shared/dashboard-types";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import {
  ResponsiveContainer, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, Tooltip, CartesianGrid, PieChart, Pie, Cell, AreaChart, Area,
} from "recharts";
import { cn } from "@/lib/utils";

function buildSuggestedActions(brief: ExecutiveBriefing): string[] {
  const actions: string[] = [];
  if (brief.finance_brief.cash_outstanding > 0)
    actions.push("Prioritise collections on larger outstanding invoices to improve cash position over the next 30 days.");
  if (brief.inventory_brief.low_stock_alerts > 0)
    actions.push("Review low-stock SKUs and confirm reorder plans for products tied to key customers and therapies.");
  if (brief.workforce_brief.weekly_hours > 0 && brief.workforce_brief.top_dept !== "None")
    actions.push(`Review utilisation, overtime, and handoffs in ${brief.workforce_brief.top_dept} to protect service levels.`);
  if (actions.length === 0)
    actions.push("No immediate actions detected from today's data. Continue monitoring trends this week.");
  return actions.slice(0, 3);
}

function summaryStatusClass(status?: string) {
  if (status === "Healthy") return "bg-success/15 text-success border border-success/30";
  if (status === "At Risk") return "bg-destructive/15 text-destructive border border-destructive/30";
  return "bg-warning/15 text-warning border border-warning/30";
}

function summaryCardBorder(status?: string) {
  if (status === "Healthy") return "border-l-4 border-l-success";
  if (status === "At Risk") return "border-l-4 border-l-destructive";
  return "border-l-4 border-l-warning";
}

function trendBadgeClass(trend?: string) {
  if (trend === "Improving") return "bg-success/15 text-success border border-success/30";
  if (trend === "Declining") return "bg-destructive/15 text-destructive border border-destructive/30";
  return "bg-warning/15 text-warning border border-warning/30";
}

function trendCardBorder(trend?: string) {
  if (trend === "Declining") return "border border-destructive/30 bg-destructive/5";
  if (trend === "Improving") return "border border-success/30";
  return "";
}

function severityClass(severity?: string) {
  if (severity === "High") return "bg-destructive/15 text-destructive border border-destructive/30";
  if (severity === "Medium") return "bg-warning/15 text-warning border border-warning/30";
  return "bg-success/15 text-success border border-success/30";
}

export function ExecutiveDashboard() {
  const { data, isLoading, isError } = useQuery<ExecutiveBriefing>({
    queryKey: ["executive-briefing"],
    queryFn: () => api.dashboard.briefing(),
  });
  const { data: summaryData } = useQuery<ExecutiveSummaryResponse>({
    queryKey: ["executive-summary"],
    queryFn: () => api.intelligence.executiveSummary(),
  });
  const { data: arTrends } = useQuery<ArTrendsResponse>({
    queryKey: ["ar-trends"],
    queryFn: () => api.analytics.arTrends(6),
  });
  const { data: opsKpis } = useQuery<OpsKpis>({
    queryKey: ["ops-kpis"],
    queryFn: () => api.ops.kpis(),
  });
  const { data: hrSummary } = useQuery<HrSummaryResponse>({
    queryKey: ["hr-summary"],
    queryFn: () => api.hr.summary(3),
  });
  const { data: riskSignals } = useQuery<RiskSignalsResponse>({
    queryKey: ["risk-signals"],
    queryFn: () => api.intelligence.riskSignals(),
  });
  const { data: recommendations } = useQuery<RecommendationsResponse>({
    queryKey: ["recommendations"],
    queryFn: () => api.intelligence.recommendations(),
  });
  const { data: anomalies } = useQuery<AnomaliesResponse>({
    queryKey: ["anomalies"],
    queryFn: () => api.intelligence.anomalies(),
  });
  const { data: opsForecast } = useQuery<OpsForecast>({
    queryKey: ["ops-forecast-turnover"],
    queryFn: () => api.ops.forecastStockTurnover(3, 3),
  });
  const { data: arAgingBuckets } = useQuery<Record<string, number>>({
    queryKey: ["ar-aging-buckets"],
    queryFn: () => api.finance.arAging(),
  });

  const briefing = !isError && data ? data : null;
  const briefingHealth = briefing?.summary.health_score ?? "Loading...";
  const briefingFocus = briefing?.summary.focus_area ?? "core operations";
  const criticalRisks = briefing?.summary.critical_risks ?? [];
  const riskCount = criticalRisks.length;
  const cashOutstanding = briefing?.finance_brief.cash_outstanding ?? 0;
  const cashPayable = briefing?.finance_brief.cash_payable ?? 0;
  const lowStockAlerts = briefing?.inventory_brief.low_stock_alerts ?? 0;
  const weeklyHours = briefing?.workforce_brief.weekly_hours ?? 0;
  const topDept = briefing?.workforce_brief.top_dept ?? "-";
  const latestAlerts = briefing?.latest_alerts ?? [];
  const summaryStatus = summaryData?.status;
  const summaryFindings = Array.isArray(summaryData?.key_findings) ? summaryData.key_findings : [];
  const summaryFocus = Array.isArray(summaryData?.recommended_focus) ? summaryData.recommended_focus : [];
  const arTrend = arTrends?.trend;
  const opsTrend = (opsKpis as any)?.stock_turnover_trend as TrendFlag | undefined;
  const hrTrend = hrSummary?.absenteeism_trend_flag;
  const suggestedActions = briefing
    ? buildSuggestedActions(briefing)
    : ["Executive briefing is still loading. Insights will appear here shortly."];

  // Chart data
  const arSparklineData = (arTrends?.summary?.periods ?? []).map((p) => ({ period: p.period, value: p.balance }));
  const turnoverActuals = (opsForecast?.series ?? []).map((p) => ({ period: p.period, actual: p.turnover, forecast: null as number | null }));
  const forecastPoints = (opsForecast?.forecast ?? []).map((v, i) => ({ period: `F+${i + 1}`, actual: null as number | null, forecast: v }));
  const turnoverChartData = [...turnoverActuals, ...forecastPoints];
  const turnoverLineColor = opsTrend?.trend === "Declining" ? "#ef4444" : "#3b82f6";
  const absenceData = (hrSummary?.absenteeism_trend ?? []).map((p) => ({ period: p.period, hours: p.hours }));
  const arAgingData = arAgingBuckets
    ? [
        { name: "0–30d", value: arAgingBuckets["0_30"] ?? 0, fill: "#22c55e" },
        { name: "31–60d", value: arAgingBuckets["31_60"] ?? 0, fill: "#f59e0b" },
        { name: "61–90d", value: arAgingBuckets["61_90"] ?? 0, fill: "#f97316" },
        { name: "91+d", value: arAgingBuckets["91_plus"] ?? 0, fill: "#ef4444" },
      ]
    : [];
  const arAgingTotal = arAgingData.reduce((s, d) => s + d.value, 0);
  const ar91Plus = arAgingBuckets?.["91_plus"] ?? 0;
  const ar91PlusPct = arAgingTotal > 0 ? ((ar91Plus / arAgingTotal) * 100).toFixed(1) : "0.0";
  const cashExposureData = [
    { label: "AR Outstanding", value: cashOutstanding, fill: "#3b82f6" },
    { label: "AP Payable", value: cashPayable, fill: "#f97316" },
  ];
  const riskSeverityCounts = { High: 0, Medium: 0, Low: 0 };
  for (const r of riskSignals?.risks ?? []) {
    if (r.severity === "High") riskSeverityCounts.High++;
    else if (r.severity === "Medium") riskSeverityCounts.Medium++;
    else riskSeverityCounts.Low++;
  }
  const riskSeverityData = [
    { name: "High", value: riskSeverityCounts.High, fill: "#ef4444" },
    { name: "Medium", value: riskSeverityCounts.Medium, fill: "#f59e0b" },
    { name: "Low", value: riskSeverityCounts.Low, fill: "#22c55e" },
  ].filter((d) => d.value > 0);

  const hasHighRisk = riskSeverityCounts.High > 0;

  const getRiskLink = (domain: string) => {
    switch (domain?.toLowerCase()) {
      case "finance": return "/finance/analytics";
      case "operations": case "inventory": return "/operations";
      case "hr": case "workforce": case "staff": return "/hr";
      case "crm": case "customer": return "/crm";
      default: return "/executive/summary";
    }
  };

  return (
    <div className="flex flex-col gap-5">
      {/* Header */}
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold tracking-tight">Executive Briefing</h1>
        <p className="text-sm text-muted-foreground">
          {briefing
            ? `Daily snapshot generated at ${new Date(briefing.generated_at).toLocaleTimeString()}`
            : isLoading
            ? "Generating daily snapshot..."
            : "Snapshot unavailable. Other sections may still load."}
        </p>
      </div>

      {/* Briefing unavailable state */}
      {!briefing && (
        <Card className="pw-surface-base">
          <CardHeader>
            <CardTitle className="text-base">Executive Briefing</CardTitle>
            <CardDescription>
              {isLoading
                ? "Compiling executive summary..."
                : "We couldn't generate today's briefing yet. Ensure Sage, inventory, and timesheet data are imported."}
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {/* ── Row 1: Executive Health Summary (full width) ──────────── */}
      <Link to="/executive/summary" className="block">
        <Card className={cn("cursor-pointer transition-colors hover:shadow-elevation-lg", summaryCardBorder(summaryStatus))}>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2 text-base font-semibold">
                <ShieldCheck className="h-4 w-4 text-success" />
                Executive Business Health Summary
              </CardTitle>
              {typeof summaryStatus === "string" && (
                <span className={cn("rounded-full px-2.5 py-0.5 text-xs font-bold", summaryStatusClass(summaryStatus))}>
                  {summaryStatus}
                </span>
              )}
            </div>
            <CardDescription className="text-xs">Calm, explainable overview based on finance, ops, HR, and inventory signals.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="text-sm text-muted-foreground">
                {summaryFindings.length > 0 ? (
                  <ul className="list-disc space-y-1 pl-4">
                    {summaryFindings.map((finding, i) => <li key={i}>{finding}</li>)}
                  </ul>
                ) : (
                  <p className="text-destructive text-xs">Summary findings unavailable.</p>
                )}
              </div>
              {summaryFocus.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {summaryFocus.map((f, i) => (
                    <Badge key={i} variant="outline" className="text-xs">{f}</Badge>
                  ))}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </Link>

      {/* ── Row 2: Trend Sparklines (3 columns) ─────────────────── */}
      <div className="grid gap-4 md:grid-cols-3">
        {/* AR Balance Trend */}
        <Link to="/finance/analytics" className="block">
          <Card className={cn("h-full cursor-pointer transition-all hover:-translate-y-0.5 hover:shadow-elevation-lg", trendCardBorder(arTrend?.trend))}>
            <CardHeader className="pb-1">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-semibold">AR Balance Trend</CardTitle>
                {typeof arTrend?.trend === "string" && (
                  <span className={cn("rounded-full px-2 py-0.5 text-xs font-bold", trendBadgeClass(arTrend.trend))}>
                    {arTrend.trend}
                  </span>
                )}
              </div>
              {typeof arTrend?.change_pct === "number" && (
                <p className="text-xs text-muted-foreground">{(arTrend.change_pct * 100).toFixed(1)}% change</p>
              )}
            </CardHeader>
            <CardContent className="px-3 pb-4">
              <div className="h-[220px]">
                {arSparklineData.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={arSparklineData} margin={{ top: 8, right: 12, left: 8, bottom: 6 }}>
                      <defs>
                        <linearGradient id="arGrad" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.25} />
                          <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.3} />
                      <XAxis dataKey="period" tick={{ fontSize: 12, fontWeight: 500 }} tickLine={false} axisLine={false} />
                      <YAxis tick={{ fontSize: 12, fontWeight: 500 }} tickLine={false} axisLine={false} tickFormatter={(v) => `₦${(v / 1_000_000).toFixed(0)}M`} width={56} />
                      <Tooltip formatter={(v: any) => [`₦${Number(v).toLocaleString()}`, "Balance"]} contentStyle={{ fontSize: "13px" }} />
                      <Area type="monotone" dataKey="value" stroke="#3b82f6" strokeWidth={2} fill="url(#arGrad)" dot={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex h-full items-center justify-center text-xs text-muted-foreground">No series data</div>
                )}
              </div>
            </CardContent>
          </Card>
        </Link>

        {/* Stock Turnover Trend */}
        <Link to="/operations" className="block">
          <Card className={cn("h-full cursor-pointer transition-all hover:-translate-y-0.5 hover:shadow-elevation-lg", trendCardBorder(opsTrend?.trend))}>
            <CardHeader className="pb-1">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-semibold">Stock Turnover</CardTitle>
                {typeof opsTrend?.trend === "string" && (
                  <span className={cn("rounded-full px-2 py-0.5 text-xs font-bold", trendBadgeClass(opsTrend.trend))}>
                    {opsTrend.trend}
                  </span>
                )}
              </div>
              {typeof opsTrend?.change_pct === "number" && (
                <p className="text-xs text-muted-foreground">{(opsTrend.change_pct * 100).toFixed(1)}% change</p>
              )}
            </CardHeader>
            <CardContent className="px-3 pb-4">
              <div className="h-[220px]">
                {turnoverChartData.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={turnoverChartData} margin={{ top: 8, right: 12, left: 8, bottom: 6 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.3} />
                      <XAxis dataKey="period" tick={{ fontSize: 12, fontWeight: 500 }} tickLine={false} axisLine={false} />
                      <YAxis tick={{ fontSize: 12, fontWeight: 500 }} tickLine={false} axisLine={false} width={48} />
                      <Tooltip contentStyle={{ fontSize: "13px" }} />
                      <Line type="monotone" dataKey="actual" stroke={turnoverLineColor} strokeWidth={2} dot={false} name="Actual" connectNulls={false} />
                      <Line type="monotone" dataKey="forecast" stroke="#94a3b8" strokeWidth={2} strokeDasharray="5 5" dot={false} name="Forecast" connectNulls={false} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex h-full items-center justify-center text-xs text-muted-foreground">No series data</div>
                )}
              </div>
            </CardContent>
          </Card>
        </Link>

        {/* Absence Trend */}
        <Link to="/hr" className="block">
          <Card className={cn("h-full cursor-pointer transition-all hover:-translate-y-0.5 hover:shadow-elevation-lg", trendCardBorder(hrTrend?.trend))}>
            <CardHeader className="pb-1">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-semibold">Absence Trend</CardTitle>
                {typeof hrTrend?.trend === "string" && (
                  <span className={cn("rounded-full px-2 py-0.5 text-xs font-bold", trendBadgeClass(hrTrend.trend))}>
                    {hrTrend.trend}
                  </span>
                )}
              </div>
              {typeof hrTrend?.change_pct === "number" && (
                <p className="text-xs text-muted-foreground">{(hrTrend.change_pct * 100).toFixed(1)}% change</p>
              )}
            </CardHeader>
            <CardContent className="px-3 pb-4">
              <div className="h-[220px]">
                {absenceData.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={absenceData} margin={{ top: 8, right: 12, left: 8, bottom: 6 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.3} />
                      <XAxis dataKey="period" tick={{ fontSize: 12, fontWeight: 500 }} tickLine={false} axisLine={false} />
                      <YAxis tick={{ fontSize: 12, fontWeight: 500 }} tickLine={false} axisLine={false} width={48} />
                      <Tooltip formatter={(v: any) => [`${v}h`, "Absence"]} contentStyle={{ fontSize: "13px" }} />
                      <Bar dataKey="hours" fill="#f59e0b" radius={[3, 3, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex h-full items-center justify-center text-xs text-muted-foreground">No series data</div>
                )}
              </div>
            </CardContent>
          </Card>
        </Link>
      </div>

      {/* ── Row 3: AR Aging + AI Business Summary ────────────────── */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* AR Aging Breakdown */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm font-semibold">
              <span className="inline-block h-2.5 w-2.5 rounded-full bg-destructive" />
              AR Aging Breakdown
            </CardTitle>
            <CardDescription className="text-xs">Outstanding receivables by overdue age bucket.</CardDescription>
          </CardHeader>
          <CardContent>
            {arAgingData.length === 0 || arAgingTotal === 0 ? (
              <p className="text-sm text-muted-foreground">No AR aging data. Import AR snapshot to populate.</p>
            ) : (
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
                <div className="h-[260px] w-full sm:w-[280px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={arAgingData} cx="50%" cy="50%" innerRadius={62} outerRadius={102} dataKey="value" strokeWidth={2} stroke="var(--background)">
                        {arAgingData.map((entry, i) => <Cell key={i} fill={entry.fill} />)}
                      </Pie>
                      <Tooltip formatter={(v: any, name: string) => [`₦${Number(v).toLocaleString()}`, name]} contentStyle={{ fontSize: "13px" }} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="flex-1 space-y-2">
                  <div>
                    <div className="text-xl font-bold tabular-nums">₦{arAgingTotal.toLocaleString()}</div>
                    <p className="text-xs text-muted-foreground">Total AR Outstanding</p>
                  </div>
                  <div className="space-y-1.5">
                    {arAgingData.map((d) => (
                      <div key={d.name} className="flex items-center justify-between text-sm">
                        <span className="flex items-center gap-1.5">
                          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: d.fill }} />
                          {d.name}
                        </span>
                        <span className="tabular-nums font-medium">₦{d.value.toLocaleString()}</span>
                      </div>
                    ))}
                  </div>
                  {parseFloat(ar91PlusPct) > 0 && (
                    <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                      ⚠ {ar91PlusPct}% of AR is 91+ days overdue — immediate collection action required.
                    </div>
                  )}
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* AI Business Summary */}
        <Link to="/finance/reports" className="block">
          <Card className="h-full cursor-pointer border-l-4 border-l-primary transition-colors hover:shadow-elevation-lg">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm font-semibold">
                <Activity className="h-4 w-4 text-primary" />
                AI Business Summary
              </CardTitle>
              <CardDescription className="text-xs">Automated insights from Sage, inventory, and timesheets.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold">Health Score:</span>
                <span className={cn("rounded-full px-2 py-0.5 text-xs font-bold",
                  briefingHealth === "Stable" ? "bg-success/15 text-success border border-success/30" : "bg-warning/15 text-warning border border-warning/30"
                )}>
                  {briefingHealth}
                </span>
              </div>
              <p className="text-sm text-muted-foreground">
                Focus on <strong>{briefingFocus}</strong>.{" "}
                {riskCount > 0
                  ? <>There are <strong>{riskCount} critical risks</strong>: {criticalRisks.join(", ")}.</>
                  : "No critical risks flagged today."}
              </p>
              <div className="flex flex-wrap gap-1.5">
                <span className="rounded-full border border-blue-500/30 bg-blue-500/15 px-2 py-0.5 text-xs text-blue-500">₦{cashOutstanding.toLocaleString()} Outstanding</span>
                <span className="rounded-full border border-orange-500/30 bg-orange-500/15 px-2 py-0.5 text-xs text-orange-500">₦{cashPayable.toLocaleString()} Payable</span>
                <span className="rounded-full border border-warning/30 bg-warning/15 px-2 py-0.5 text-xs text-warning">{lowStockAlerts} Low-Stock Alerts</span>
                <span className="rounded-full border border-border/50 bg-muted/50 px-2 py-0.5 text-xs text-muted-foreground">{weeklyHours}h · {topDept}</span>
              </div>
              {(cashOutstanding > 0 || cashPayable > 0) && (
                <div className="h-[100px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={cashExposureData} layout="vertical" margin={{ top: 0, right: 12, left: 8, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.3} horizontal={false} />
                      <XAxis type="number" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} tickFormatter={(v) => `₦${(v / 1_000_000).toFixed(0)}M`} />
                      <YAxis type="category" dataKey="label" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} width={88} />
                      <Tooltip formatter={(v: any) => [`₦${Number(v).toLocaleString()}`, ""]} contentStyle={{ fontSize: "11px" }} />
                      <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                        {cashExposureData.map((entry, idx) => <Cell key={idx} fill={entry.fill} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </CardContent>
          </Card>
        </Link>
      </div>

      {/* ── Row 4: Risk Signals (full width) ─────────────────────── */}
      <Card className={cn(hasHighRisk && "border border-destructive/30 bg-destructive/5")}>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2 text-sm font-semibold">
                <AlertTriangle className={cn("h-4 w-4", hasHighRisk ? "text-destructive" : "text-muted-foreground")} />
                Risk Signals
              </CardTitle>
              <CardDescription className="text-xs">Early warnings by domain, severity, and source.</CardDescription>
            </div>
            {riskSeverityData.length > 0 && (
              <div className="flex items-center gap-3">
                <PieChart width={140} height={140}>
                  <Pie data={riskSeverityData} cx={66} cy={66} innerRadius={34} outerRadius={58} dataKey="value" strokeWidth={0}>
                    {riskSeverityData.map((entry, i) => <Cell key={i} fill={entry.fill} />)}
                  </Pie>
                </PieChart>
                <div className="flex flex-col gap-0.5 text-xs">
                  {riskSeverityData.map((d) => (
                    <span key={d.name} className="flex items-center gap-1">
                      <span className="inline-block h-2 w-2 rounded-full" style={{ background: d.fill }} />
                      {d.name}: {d.value}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {!riskSignals?.risks?.length ? (
            <p className="text-sm text-muted-foreground">No active risk signals detected.</p>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {riskSignals.risks.map((r, i) => (
                <Link to={getRiskLink(r.domain)} key={`${r.domain}-${i}`} className="block">
                  <div className="flex items-start justify-between gap-2 rounded-xl border border-border/60 bg-card/40 p-3 transition-colors hover:border-primary/40 hover:bg-card/60">
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-semibold">{r.domain}: {r.risk_type}</div>
                      <div className="text-[11px] text-muted-foreground leading-tight">{r.signal}</div>
                    </div>
                    <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold", severityClass(r.severity))}>
                      {r.severity}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Row 5: Recommendations + Anomalies ───────────────────── */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Recommendations */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold">Recommended Actions</CardTitle>
            <CardDescription className="text-xs">Explainable, data-backed next steps.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="max-h-[220px] space-y-2 overflow-y-auto pr-1">
              {!recommendations?.recommendations?.length ? (
                <p className="text-sm text-muted-foreground">No recommendations available yet.</p>
              ) : (
                recommendations.recommendations.map((rec, i) => (
                  <Link to="/executive/summary" key={`${rec.action}-${i}`} className="block">
                    <div className="rounded-xl border border-border/60 bg-card/40 p-3 transition-all hover:shadow-elevation-lg">
                      <div className="text-xs font-semibold">{rec.action}</div>
                      <div className="text-[11px] text-muted-foreground">{rec.reason}</div>
                      <div className="mt-0.5 text-[10px] text-muted-foreground/60">Source: {rec.data_source} · Confidence: {rec.confidence}</div>
                    </div>
                  </Link>
                ))
              )}
            </div>
          </CardContent>
        </Card>

        {/* Anomalies */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold">Anomaly Signals</CardTitle>
            <CardDescription className="text-xs">Lightweight anomaly detection (z-score).</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="max-h-[220px] space-y-2 overflow-y-auto pr-1">
              {!anomalies?.anomalies?.length ? (
                <p className="text-sm text-muted-foreground">No anomalies detected.</p>
              ) : (
                anomalies.anomalies.map((a, i) => (
                  <Link to={getRiskLink(a.domain)} key={`${a.domain}-${i}`} className="block">
                    <div className="rounded-xl border border-border/60 bg-card/40 p-3 transition-all hover:shadow-elevation-lg">
                      <div className="text-xs font-semibold">{a.domain}: {a.signal}</div>
                      <div className="text-[11px] text-muted-foreground">{a.detail}</div>
                      <div className="mt-0.5 text-[10px] text-muted-foreground/60">Z-score: {a.zscore.toFixed(2)} · Source: {a.data_source}</div>
                    </div>
                  </Link>
                ))
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ── Row 6: Domain Shortcuts + Suggested Actions ───────────── */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="cursor-pointer transition-all hover:shadow-elevation-lg">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm font-semibold">
              <TrendingUp className="h-4 w-4 text-primary" /> Finance
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold tabular-nums">₦{cashOutstanding.toLocaleString()}</div>
            <p className="mb-3 text-xs text-muted-foreground">Total AR Outstanding</p>
            <Link to="/finance/analytics">
              <Button variant="outline" size="sm" className="w-full text-xs">View Financials <ArrowRight className="ml-1.5 h-3 w-3" /></Button>
            </Link>
          </CardContent>
        </Card>

        <Card className="cursor-pointer transition-all hover:shadow-elevation-lg">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm font-semibold">
              <Archive className="h-4 w-4 text-warning" /> Inventory
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold tabular-nums text-warning">{lowStockAlerts}</div>
            <p className="mb-3 text-xs text-muted-foreground">Low Stock Alerts</p>
            <Link to="/operations">
              <Button variant="outline" size="sm" className="w-full text-xs">Manage Stock <ArrowRight className="ml-1.5 h-3 w-3" /></Button>
            </Link>
          </CardContent>
        </Card>

        <Card className="cursor-pointer transition-all hover:shadow-elevation-lg">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm font-semibold">
              <Users className="h-4 w-4 text-info" /> Workforce
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold tabular-nums">{weeklyHours}h</div>
            <p className="mb-3 text-xs text-muted-foreground">Effort this week</p>
            <Link to="/hr">
              <Button variant="outline" size="sm" className="w-full text-xs">View Timesheets <ArrowRight className="ml-1.5 h-3 w-3" /></Button>
            </Link>
          </CardContent>
        </Card>
      </div>

      {/* ── Suggested Actions (compact strip) ──────────────────────── */}
      <div className="rounded-xl border border-border/50 bg-muted/20 p-4">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Suggested Executive Actions</h3>
        <div className="grid gap-2 md:grid-cols-3">
          {suggestedActions.map((action, i) => (
            <div key={i} className="flex items-start gap-2 text-xs text-muted-foreground">
              <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-primary/15 text-[10px] font-bold text-primary">{i + 1}</span>
              {action}
            </div>
          ))}
        </div>
      </div>

      {/* ── Live Intelligence Feed (scrollable) ─────────────────────── */}
      {latestAlerts.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold">Live Intelligence Feed</h3>
          <div className="max-h-[200px] space-y-2 overflow-y-auto pr-1">
            {latestAlerts.map((alert, i) => (
              <Alert key={i} variant={alert.includes("Low stock") ? "default" : "destructive"} className="py-2">
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle className="text-xs font-semibold">{alert.includes("Low stock") ? "Inventory Warning" : "Critical Risk"}</AlertTitle>
                <AlertDescription className="text-xs">{alert}</AlertDescription>
              </Alert>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
