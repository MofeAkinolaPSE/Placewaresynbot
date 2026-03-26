import { ExecutiveDashboard as ExecutiveDashboardComponent } from "@/components/dashboards/ExecutiveDashboard";
import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { api } from "@/lib/api-client";
import { useQueryClient } from "@tanstack/react-query";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Cell, ReferenceLine,
} from "recharts";

type HeatmapCell = {
  domain: string;
  severity: number;
  likelihood: number;
  score: number;
};

const Executive = () => {
  const [heatmap, setHeatmap] = useState<HeatmapCell[]>([]);
  const queryClient = useQueryClient();

  const loadHeatmap = useCallback(async () => {
    const cached = await api.agents.cached("enterprise_risk").catch(() => null);
    const cachedHeatmap = cached?.value?.metrics?.heatmap;
    if (Array.isArray(cachedHeatmap)) {
      setHeatmap(cachedHeatmap);
      return;
    }
    const res = await api.agents.run("enterprise_risk").catch(() => null);
    const hm = res?.insight?.metrics?.heatmap;
    if (Array.isArray(hm)) {
      setHeatmap(hm);
    }
  }, []);

  useEffect(() => {
    void loadHeatmap();
  }, [loadHeatmap]);

  useRealtimeChannel("alerts_updates", () => {
    void loadHeatmap();
    void queryClient.invalidateQueries({ queryKey: ["executive-briefing"] });
    void queryClient.invalidateQueries({ queryKey: ["executive-summary"] });
    void queryClient.invalidateQueries({ queryKey: ["risk-signals"] });
    void queryClient.invalidateQueries({ queryKey: ["recommendations"] });
    void queryClient.invalidateQueries({ queryKey: ["anomalies"] });
  });

  useRealtimeChannel("workflow_updates", () => {
    void queryClient.invalidateQueries({ queryKey: ["executive-briefing"] });
    void queryClient.invalidateQueries({ queryKey: ["ar-trends"] });
    void queryClient.invalidateQueries({ queryKey: ["ops-kpis"] });
    void queryClient.invalidateQueries({ queryKey: ["hr-summary"] });
  });

  useRealtimeChannel("inventory_updates", () => {
    void queryClient.invalidateQueries({ queryKey: ["executive-briefing"] });
    void queryClient.invalidateQueries({ queryKey: ["ops-kpis"] });
  });

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionTransitions.standard}
      className="pw-page-surface space-y-6 p-6"
    >
      <ExecutiveDashboardComponent />

      <Card className="pw-surface-interactive">
        <CardHeader>
          <CardTitle>Enterprise Risk Heatmap</CardTitle>
          <CardDescription>Risk score by domain — sorted by severity. Above 60 = High Risk.</CardDescription>
        </CardHeader>
        <CardContent>
          {heatmap.length === 0 ? (
            <p className="text-sm text-muted-foreground">No risk heatmap data available yet.</p>
          ) : (
            <ResponsiveContainer width="100%" height={Math.max(200, heatmap.length * 48)}>
              <BarChart
                data={[...heatmap]
                  .sort((a, b) => b.score - a.score)
                  .map((c) => ({ ...c, domain: c.domain.charAt(0).toUpperCase() + c.domain.slice(1) }))}
                layout="vertical"
                margin={{ top: 4, right: 32, left: 12, bottom: 4 }}
              >
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--border)" opacity={0.4} />
                <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 11 }} />
                <YAxis type="category" dataKey="domain" tick={{ fontSize: 11 }} width={96} />
                <Tooltip
                  formatter={(_v: any, _n: any, props: any) => [
                    `Score: ${props.payload.score} · Severity ${props.payload.severity}/5 · Likelihood ${props.payload.likelihood}/5`,
                    props.payload.domain,
                  ]}
                  contentStyle={{ fontSize: "11px" }}
                />
                <ReferenceLine
                  x={60}
                  stroke="#ef4444"
                  strokeDasharray="4 4"
                  label={{ value: "High Risk", position: "top", fontSize: 10, fill: "#ef4444" }}
                />
                <Bar dataKey="score" radius={[0, 4, 4, 0]}>
                  {[...heatmap]
                    .sort((a, b) => b.score - a.score)
                    .map((cell, i) => (
                      <Cell
                        key={i}
                        fill={cell.score >= 60 ? "#ef4444" : cell.score >= 40 ? "#f59e0b" : "#22c55e"}
                      />
                    ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
};

export default Executive;
