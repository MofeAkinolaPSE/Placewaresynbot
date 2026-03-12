import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ArrowLeft, Bot, Loader2, Play } from "lucide-react";
import { api } from "@/lib/api-client";
import { useToast } from "@/hooks/use-toast";

type Insight = {
  metrics?: Record<string, any>;
  findings?: string[];
  risks?: string[];
  recommendations?: string[];
  confidence_score?: number;
  execution_metadata?: Record<string, any>;
};

export default function AgentDetail() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [loading, setLoading] = useState(true);
  const [executing, setExecuting] = useState(false);
  const [insight, setInsight] = useState<Insight | null>(null);
  const [ttl, setTtl] = useState<number | null>(null);

  const agentName = name || "";

  const loadCache = async () => {
    if (!agentName) return;
    try {
      const [cacheRes, ttlRes] = await Promise.all([
        api.agents.cached(agentName),
        api.agents.cacheTtl(agentName),
      ]);
      if (cacheRes?.value) {
        setInsight({
          ...cacheRes.value,
          execution_metadata: {
            ...(cacheRes.value.execution_metadata || {}),
            cache_hit: true,
          },
        });
      }
      setTtl(ttlRes?.ttl_seconds ?? null);
    } catch {
      // No-op: cache may be empty
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCache();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentName]);

  const runAgent = async () => {
    if (!agentName) return;
    try {
      setExecuting(true);
      const res = await api.agents.run(agentName);
      setInsight(res.insight);
      const ttlRes = await api.agents.cacheTtl(agentName);
      setTtl(ttlRes?.ttl_seconds ?? null);
      toast({ title: "Agent executed", description: `${agentName} completed` });
    } catch (err: any) {
      toast({
        title: "Agent execution failed",
        description: err?.message || "Request failed",
        variant: "destructive",
      });
    } finally {
      setExecuting(false);
    }
  };

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <Button variant="outline" onClick={() => navigate("/agents")}> 
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to Agent Stack
        </Button>
        <Button onClick={runAgent} disabled={executing}>
          {executing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
          Run Agent
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Bot className="h-5 w-5" />
            {agentName.split("_").join(" ")}
          </CardTitle>
          <CardDescription>
            {ttl !== null && ttl >= 0 ? `Cache TTL: ${ttl}s` : "No active cached result"}
          </CardDescription>
        </CardHeader>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Latest Insight</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {!loading && !insight && (
            <p className="text-sm text-muted-foreground">No cached insight found. Run this agent to generate one.</p>
          )}

          {loading && <Loader2 className="h-5 w-5 animate-spin" />}

          {insight && (
            <>
              {insight.execution_metadata?.cache_hit && <Badge variant="secondary">From Cache</Badge>}

              {insight.metrics && Object.keys(insight.metrics).length > 0 && (
                <div className="grid gap-2 md:grid-cols-3">
                  {Object.entries(insight.metrics).map(([k, v]) => (
                    <div key={k} className="bg-muted rounded-lg p-3">
                      <p className="text-xs text-muted-foreground">{k}</p>
                      <p className="font-semibold text-sm">{String(v)}</p>
                    </div>
                  ))}
                </div>
              )}

              {insight.findings && insight.findings.length > 0 && (
                <div>
                  <p className="font-medium mb-2">Findings</p>
                  <ul className="space-y-1 text-sm text-muted-foreground">
                    {insight.findings.map((f, i) => (
                      <li key={i}>• {f}</li>
                    ))}
                  </ul>
                </div>
              )}

              {insight.recommendations && insight.recommendations.length > 0 && (
                <div>
                  <p className="font-medium mb-2">Recommendations</p>
                  <ul className="space-y-1 text-sm text-muted-foreground">
                    {insight.recommendations.map((r, i) => (
                      <li key={i}>• {r}</li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
