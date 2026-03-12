import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api-client";
import { motionTransitions } from "@/lib/motion";

const statusClass = (status?: string) => {
  if (status === "Healthy" || status === "Stable") return "border-success/30 bg-success/15 text-success";
  if (status === "At Risk") return "border-destructive/30 bg-destructive/15 text-destructive";
  return "border-warning/30 bg-warning/15 text-warning";
};

export default function ExecutiveSummaryDetails() {
  const { data: briefing } = useQuery({
    queryKey: ["executive-briefing"],
    queryFn: () => api.dashboard.briefing(),
  });

  const { data: summary } = useQuery({
    queryKey: ["executive-summary"],
    queryFn: () => api.intelligence.executiveSummary(),
  });

  const findings = Array.isArray(summary?.key_findings) ? summary.key_findings : [];
  const focus = Array.isArray(summary?.recommended_focus) ? summary.recommended_focus : [];

  const generatedAt = useMemo(() => {
    if (!briefing?.generated_at) return "-";
    return new Date(briefing.generated_at).toLocaleString();
  }, [briefing?.generated_at]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionTransitions.standard}
      className="pw-page-surface space-y-6 p-8"
    >
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Executive Summary Details</h1>
        <p className="mt-2 text-base text-muted-foreground">
          Strategic narrative generated from finance, operations, workforce, and inventory intelligence.
        </p>
      </div>

      <Card className="pw-surface-interactive">
        <CardHeader>
          <CardTitle className="flex items-center justify-between gap-3">
            <span>Business Health</span>
            <Badge className={statusClass(summary?.status)}>{summary?.status || "Pending"}</Badge>
          </CardTitle>
          <CardDescription>Generated at {generatedAt}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <h3 className="mb-2 text-base font-semibold">Key Findings</h3>
            {findings.length > 0 ? (
              <ul className="list-disc space-y-2 pl-5 text-sm text-muted-foreground">
                {findings.map((item: string, idx: number) => (
                  <li key={idx}>{item}</li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">No findings are available yet for the current snapshot.</p>
            )}
          </div>

          <div>
            <h3 className="mb-2 text-base font-semibold">Recommended Focus</h3>
            {focus.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {focus.map((item: string, idx: number) => (
                  <Badge key={idx} variant="secondary">{item}</Badge>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No focus recommendations available yet.</p>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card className="pw-surface-interactive">
          <CardHeader><CardTitle className="text-sm">Cash Outstanding</CardTitle></CardHeader>
          <CardContent><p className="text-2xl font-semibold">₦{Number(briefing?.finance_brief?.cash_outstanding || 0).toLocaleString()}</p></CardContent>
        </Card>
        <Card className="pw-surface-interactive">
          <CardHeader><CardTitle className="text-sm">Cash Payable</CardTitle></CardHeader>
          <CardContent><p className="text-2xl font-semibold">₦{Number(briefing?.finance_brief?.cash_payable || 0).toLocaleString()}</p></CardContent>
        </Card>
        <Card className="pw-surface-interactive">
          <CardHeader><CardTitle className="text-sm">Low Stock Alerts</CardTitle></CardHeader>
          <CardContent><p className="text-2xl font-semibold">{Number(briefing?.inventory_brief?.low_stock_alerts || 0)}</p></CardContent>
        </Card>
        <Card className="pw-surface-interactive">
          <CardHeader><CardTitle className="text-sm">Weekly Workforce Hours</CardTitle></CardHeader>
          <CardContent><p className="text-2xl font-semibold">{Number(briefing?.workforce_brief?.weekly_hours || 0)}h</p></CardContent>
        </Card>
      </div>
    </motion.div>
  );
}
