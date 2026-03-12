import { ExecutiveDashboard as ExecutiveDashboardComponent } from "@/components/dashboards/ExecutiveDashboard";
import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api-client";
import { useQueryClient } from "@tanstack/react-query";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";

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
        </CardHeader>
        <CardContent>
          {heatmap.length === 0 ? (
            <p className="text-sm text-muted-foreground">No risk heatmap data available yet.</p>
          ) : (
            <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
              {heatmap.map((cell) => (
                <div key={cell.domain} className="pw-surface-base space-y-2 rounded-xl p-3">
                  <div className="flex items-center justify-between">
                    <p className="font-medium capitalize">{cell.domain}</p>
                    <Badge variant={cell.score >= 60 ? "destructive" : "secondary"}>{cell.score}</Badge>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Severity {cell.severity}/5 • Likelihood {cell.likelihood}/5
                  </p>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
};

export default Executive;
