import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ArrowRight, AlertTriangle, TrendingUp, Archive, Activity, Users, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import {
   ExecutiveBriefing,
   ExecutiveSummaryResponse,
   ArTrendsResponse,
   HrSummaryResponse,
   TrendFlag,
   OpsKpis,
   RiskSignalsResponse,
   RecommendationsResponse,
   AnomaliesResponse,
} from "@shared/dashboard-types";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";

function buildSuggestedActions(brief: ExecutiveBriefing): string[] {
   const actions: string[] = [];

   if (brief.finance_brief.cash_outstanding > 0) {
      actions.push(
         "Prioritise collections on larger outstanding invoices to improve cash position over the next 30 days."
      );
   }

   if (brief.inventory_brief.low_stock_alerts > 0) {
      actions.push(
         "Review low-stock SKUs and confirm reorder plans for products tied to key customers and therapies."
      );
   }

   if (brief.workforce_brief.weekly_hours > 0 && brief.workforce_brief.top_dept !== "None") {
      actions.push(
         `Review utilisation, overtime, and handoffs in ${brief.workforce_brief.top_dept} to protect service levels as volume grows.`
      );
   }

   if (actions.length === 0) {
      actions.push("No immediate actions detected from today's data. Continue monitoring trends this week.");
   }

   return actions.slice(0, 3);
}

function summaryStatusClass(status?: string) {
   if (status === "Healthy") return "bg-success/15 text-success border border-success/30";
   if (status === "At Risk") return "bg-destructive/15 text-destructive border border-destructive/30";
   return "bg-warning/15 text-warning border border-warning/30";
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
   const suggestedActions = briefing ? buildSuggestedActions(briefing) : ["Executive briefing is still loading. Insights will appear here shortly."];

   const getRiskLink = (domain: string) => {
      switch (domain?.toLowerCase()) {
         case "finance":
            return "/finance/analytics";
         case "operations":
         case "inventory":
            return "/operations";
         case "hr":
         case "workforce":
         case "staff":
            return "/hr";
         case "crm":
         case "customer":
            return "/crm";
         default:
            return "/executive/summary";
      }
   };

  return (
    <div className="space-y-6">
      {/* Header Section */}
         <div className="flex flex-col space-y-2">
            <h1 className="text-3xl font-bold tracking-tight">Executive Briefing</h1>
            <p className="text-muted-foreground">
               {briefing ? `Daily snapshot generated at ${new Date(briefing.generated_at).toLocaleTimeString()}` : (isLoading ? "Generating daily snapshot..." : "Snapshot unavailable. Other sections may still load.")}
            </p>
         </div>

         {!briefing && (
            <Card className="pw-surface-base">
               <CardHeader>
                  <CardTitle>Executive Briefing</CardTitle>
                  <CardDescription>
                     {isLoading
                        ? "Compiling executive summary..."
                        : "We couldn't generate today's briefing yet. Ensure Sage, inventory, and timesheet data are imported and try again."}
                  </CardDescription>
               </CardHeader>
            </Card>
         )}

         {/* Executive Summary Card */}
         <Link to="/executive/summary" className="block">
            <Card className="pw-surface-interactive cursor-pointer border-l-4 border-l-success transition-colors hover:border-l-success/70">
               <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                     <ShieldCheck className="h-5 w-5 text-success" />
                     Executive Business Health Summary
                  </CardTitle>
                  <CardDescription>
                     Calm, explainable overview based on finance, ops, HR, and inventory signals.
                  </CardDescription>
               </CardHeader>
               <CardContent>
                  <div className="space-y-3">
                     <div className="flex items-center gap-2">
                        <span className="font-semibold">Status:</span>
                        {typeof summaryStatus === "string" ? (
                           <span className={`rounded-full px-2 py-1 text-xs font-bold ${summaryStatusClass(summaryStatus)}`}>
                              {summaryStatus}
                           </span>
                        ) : (
                           <span className="text-xs text-destructive">Data error: summary status unavailable.</span>
                        )}
                     </div>
                     <div className="text-sm text-muted-foreground">
                        {summaryFindings.length > 0 ? (
                           <ul className="list-disc pl-5 space-y-1">
                              {summaryFindings.map((finding, i) => (
                                 <li key={i}>{finding}</li>
                              ))}
                           </ul>
                        ) : (
                           <p className="text-destructive">Data error: summary findings unavailable.</p>
                        )}
                     </div>
                     {summaryFocus.length > 0 && (
                        <div className="text-sm">
                           <span className="font-semibold">Recommended Focus:</span>
                           <span className="ml-2 text-muted-foreground">{summaryFocus.join(", ")}</span>
                        </div>
                     )}
                  </div>
               </CardContent>
            </Card>
         </Link>

         {/* Trend Flags */}
         <div className="grid gap-4 md:grid-cols-3">
            <Link to="/finance/analytics" className="block">
               <Card className="pw-surface-interactive h-full cursor-pointer transition-all hover:-translate-y-0.5 hover:shadow-elevation-xl">
                  <CardHeader>
                     <CardTitle className="text-base">AR Balance Trend</CardTitle>
                  </CardHeader>
                  <CardContent>
                              {typeof arTrend?.trend === "string" ? (
                                 <>
                                    <div className="text-2xl font-bold">{arTrend.trend}</div>
                                    <p className="text-xs text-muted-foreground">
                                       Change: {typeof arTrend.change_pct === "number" ? `${(arTrend.change_pct * 100).toFixed(1)}%` : "Insufficient data"}
                                    </p>
                                 </>
                              ) : (
                                 <p className="text-sm text-muted-foreground">Insufficient data for AR trend.</p>
                              )}
                  </CardContent>
               </Card>
            </Link>
            <Link to="/operations" className="block">
               <Card className="pw-surface-interactive h-full cursor-pointer transition-all hover:-translate-y-0.5 hover:shadow-elevation-xl">
                  <CardHeader>
                     <CardTitle className="text-base">Stock Turnover Trend</CardTitle>
                  </CardHeader>
                  <CardContent>
                              {typeof opsTrend?.trend === "string" ? (
                                 <>
                                    <div className="text-2xl font-bold">{opsTrend.trend}</div>
                                    <p className="text-xs text-muted-foreground">
                                       Change: {typeof opsTrend.change_pct === "number" ? `${(opsTrend.change_pct * 100).toFixed(1)}%` : "Insufficient data"}
                                    </p>
                                 </>
                              ) : (
                                 <p className="text-sm text-muted-foreground">Insufficient data for stock turnover trend.</p>
                              )}
                  </CardContent>
               </Card>
            </Link>
            <Link to="/hr" className="block">
               <Card className="pw-surface-interactive h-full cursor-pointer transition-all hover:-translate-y-0.5 hover:shadow-elevation-xl">
                  <CardHeader>
                     <CardTitle className="text-base">Absence Trend</CardTitle>
                  </CardHeader>
                  <CardContent>
                              {typeof hrTrend?.trend === "string" ? (
                                 <>
                                    <div className="text-2xl font-bold">{hrTrend.trend}</div>
                                    <p className="text-xs text-muted-foreground">
                                       Change: {typeof hrTrend.change_pct === "number" ? `${(hrTrend.change_pct * 100).toFixed(1)}%` : "Insufficient data"}
                                    </p>
                                 </>
                              ) : (
                                 <p className="text-sm text-muted-foreground">Insufficient data for absence trend.</p>
                              )}
                  </CardContent>
               </Card>
            </Link>
         </div>

         {/* AI Summary Card */}
      <Link to="/finance/reports" className="block">
             <Card className="pw-surface-interactive cursor-pointer border-l-4 border-l-info transition-colors hover:border-l-info/70">
           <CardHeader>
             <CardTitle className="flex items-center gap-2">
                      <Activity className="h-5 w-5 text-info" />
               AI Business Summary
             </CardTitle>
             <CardDescription>
               Automated insights from your Sage ledger, inventory movements, and workforce timesheets to support
               growth decisions.
             </CardDescription>
           </CardHeader>
           <CardContent>
              <div className="space-y-4">
                 <div className="flex items-center gap-2">
                    <span className="font-semibold">Health Score:</span>
                    <span className={`rounded-full px-2 py-1 text-xs font-bold ${briefingHealth === 'Stable' ? 'bg-success/15 text-success border border-success/30' : 'bg-warning/15 text-warning border border-warning/30'}`}>
                       {briefingHealth}
                    </span>
                 </div>
                 <p className="text-sm text-muted-foreground">
                    The business currently requires focus on <strong>{briefingFocus}</strong>. {" "}
                    {riskCount > 0 ? (
                      <>
                        There are <strong>{riskCount} critical risks</strong> identified, including
                        {" "}
                        {criticalRisks.join(", ")}
                        .
                      </>
                    ) : (
                      <>
                        No critical risks have been flagged across finance and inventory today.
                      </>
                    )}
                 </p>
                 <div className="text-sm">
                    <span className="font-semibold">Key Metrics:</span>
                    <ul className="mt-1 list-disc space-y-1 pl-5 text-muted-foreground">
                       <li>Cash Outstanding: ₦{cashOutstanding.toLocaleString()}</li>
                       <li>Cash Payable: ₦{cashPayable.toLocaleString()}</li>
                       <li>Inventory Alerts: {lowStockAlerts} items need reordering</li>
                       <li>Workforce: {weeklyHours} hours logged (Top: {topDept})</li>
                    </ul>
                 </div>
              </div>
           </CardContent>
         </Card>
      </Link>

         {/* Risk Signals */}
         <Card className="pw-surface-interactive">
            <CardHeader>
               <CardTitle className="text-base">Risk Signals</CardTitle>
               <CardDescription>Early warnings by domain, severity, and source.</CardDescription>
            </CardHeader>
            <CardContent>
               {!riskSignals?.risks?.length ? (
                  <p className="text-sm text-muted-foreground">No active risk signals detected.</p>
               ) : (
                  <div className="space-y-3">
                     {riskSignals.risks.map((r, i) => (
                        <Link to={getRiskLink(r.domain)} key={`${r.domain}-${i}`} className="block rounded-md transition-colors hover:bg-card/40">
                           <div className="flex items-start justify-between gap-3 rounded-xl border border-border/70 bg-card/40 p-3 hover:border-primary/40">
                              <div>
                                 <div className="text-sm font-semibold">{r.domain}: {r.risk_type}</div>
                                 <div className="text-xs text-muted-foreground">{r.signal}</div>
                                 <div className="text-xs text-muted-foreground">Source: {r.data_source}</div>
                              </div>
                              <span className={`rounded-full px-2 py-1 text-xs font-semibold ${severityClass(r.severity)}`}>
                                 {r.severity}
                              </span>
                           </div>
                        </Link>
                     ))}
                  </div>
               )}
            </CardContent>
         </Card>

         {/* Opportunities */}
         <Card className="pw-surface-interactive">
            <CardHeader>
               <CardTitle className="text-base">Risk → Opportunity Insights</CardTitle>
               <CardDescription>Strategic options paired to the current risks.</CardDescription>
            </CardHeader>
            <CardContent>
               {!riskSignals?.opportunities?.length ? (
                  <p className="text-sm text-muted-foreground">No opportunity insights available yet.</p>
               ) : (
                  <div className="space-y-3">
                     {riskSignals.opportunities.map((o, i) => (
                        <Link to="/executive/summary" key={`${o.risk}-${i}`} className="block rounded-md transition-all hover:bg-card/40">
                           <div className="rounded-xl border border-border/70 bg-card/40 p-3 hover:shadow-elevation-lg">
                              <div className="text-sm font-semibold">Risk: {o.risk}</div>
                              <div className="text-xs text-muted-foreground">Opportunity: {o.opportunity}</div>
                              <div className="text-xs text-muted-foreground">Confidence: {o.confidence}</div>
                           </div>
                        </Link>
                     ))}
                  </div>
               )}
            </CardContent>
         </Card>

         {/* Recommendations */}
         <Card className="pw-surface-interactive">
            <CardHeader>
               <CardTitle className="text-base">Recommended Actions</CardTitle>
               <CardDescription>Explainable, data-backed actions.</CardDescription>
            </CardHeader>
            <CardContent>
               {!recommendations?.recommendations?.length ? (
                  <p className="text-sm text-muted-foreground">No recommendations available yet.</p>
               ) : (
                  <div className="space-y-3">
                     {recommendations.recommendations.map((rec, i) => (
                        <Link to="/executive/summary" key={`${rec.action}-${i}`} className="block rounded-md transition-all hover:bg-card/40">
                           <div className="rounded-xl border border-border/70 bg-card/40 p-3 hover:shadow-elevation-lg">
                              <div className="text-sm font-semibold">{rec.action}</div>
                              <div className="text-xs text-muted-foreground">{rec.reason}</div>
                              <div className="text-xs text-muted-foreground">Source: {rec.data_source} · Confidence: {rec.confidence}</div>
                           </div>
                        </Link>
                     ))}
                  </div>
               )}
            </CardContent>
         </Card>

         {/* Anomalies */}
         <Card className="pw-surface-interactive">
            <CardHeader>
               <CardTitle className="text-base">Anomaly Signals</CardTitle>
               <CardDescription>Lightweight anomaly detection (z-score).</CardDescription>
            </CardHeader>
            <CardContent>
               {!anomalies?.anomalies?.length ? (
                  <p className="text-sm text-muted-foreground">No anomalies detected.</p>
               ) : (
                  <div className="space-y-3">
                     {anomalies.anomalies.map((a, i) => (
                        <Link to={getRiskLink(a.domain)} key={`${a.domain}-${i}`} className="block rounded-md transition-all hover:bg-card/40">
                           <div className="rounded-xl border border-border/70 bg-card/40 p-3 hover:shadow-elevation-lg">
                              <div className="text-sm font-semibold">{a.domain}: {a.signal}</div>
                              <div className="text-xs text-muted-foreground">{a.detail}</div>
                              <div className="text-xs text-muted-foreground">Z-score: {a.zscore.toFixed(2)} · Source: {a.data_source}</div>
                           </div>
                        </Link>
                     ))}
                  </div>
               )}
            </CardContent>
         </Card>

      {/* Domain Shortcuts */}
      <div className="grid gap-4 md:grid-cols-3">
            <Card className="pw-surface-interactive">
           <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                 <TrendingUp className="h-4 w-4" /> Finance
              </CardTitle>
           </CardHeader>
           <CardContent>
              <div className="text-2xl font-bold">₦{cashOutstanding.toLocaleString()}</div>
              <p className="text-xs text-muted-foreground mb-4">Total AR Outstanding</p>
              <Link to="/finance/analytics">
                 <Button variant="outline" size="sm" className="w-full">View Financials <ArrowRight className="ml-2 h-3 w-3"/></Button>
              </Link>
           </CardContent>
        </Card>

      <Card className="pw-surface-interactive">
           <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                 <Archive className="h-4 w-4" /> Inventory
              </CardTitle>
           </CardHeader>
           <CardContent>
              <div className="text-2xl font-bold text-warning">{lowStockAlerts}</div>
              <p className="text-xs text-muted-foreground mb-4">Low Stock Alerts</p>
              <Link to="/operations">
                 <Button variant="outline" size="sm" className="w-full">Manage Stock <ArrowRight className="ml-2 h-3 w-3"/></Button>
              </Link>
           </CardContent>
        </Card>

      <Card className="pw-surface-interactive">
           <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                 <Users className="h-4 w-4" /> Workforce
              </CardTitle>
           </CardHeader>
           <CardContent>
              <div className="text-2xl font-bold">{weeklyHours}h</div>
              <p className="text-xs text-muted-foreground mb-4">Effort this week</p>
              <Link to="/hr">
                 <Button variant="outline" size="sm" className="w-full">View Timesheets <ArrowRight className="ml-2 h-3 w-3"/></Button>
              </Link>
           </CardContent>
        </Card>
      </div>

         {/* Suggested Actions */}
         <Card className="pw-surface-interactive">
            <CardHeader>
               <CardTitle className="text-base">Suggested Executive Actions</CardTitle>
               <CardDescription>
                  Concrete next steps derived from today&apos;s finance, inventory, and workforce signals.
               </CardDescription>
            </CardHeader>
            <CardContent>
               <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                  {suggestedActions.map((action, index) => (
                     <li key={index}>{action}</li>
                  ))}
               </ul>
            </CardContent>
         </Card>

      {/* Live Alerts Feed */}
      <div className="space-y-4">
         <h3 className="text-lg font-semibold">Live Intelligence Feed</h3>
         {latestAlerts.length === 0 ? <p className="text-sm text-muted-foreground">No active intelligence alerts from finance, inventory, or workforce at this time.</p> : latestAlerts.map((alert, i) => (
            <Alert key={i} variant={alert.includes("Low stock") ? "default" : "destructive"}>
               <AlertTriangle className="h-4 w-4" />
               <AlertTitle>{alert.includes("Low stock") ? "Inventory Warning" : "Critical Risk"}</AlertTitle>
               <AlertDescription>
                  {alert}
               </AlertDescription>
            </Alert>
         ))}
      </div>
    </div>
  );
}

// Icon import helper
