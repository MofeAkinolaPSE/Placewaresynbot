import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api-client";
import {
  Play,
  RefreshCw,
  Bot,
  Loader2,
  CheckCircle,
  AlertTriangle,
  Info,
  Sparkles,
  TrendingUp,
  Package,
  Thermometer,
  Truck,
  FileCheck,
  DollarSign,
  AlertCircle,
  Settings,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

interface Agent {
  name: string;
  required_role: string | null;
}

interface Insight {
  _agent_name?: string;
  metrics: Record<string, any>;
  findings: string[];
  risks: string[];
  recommendations: string[];
  confidence_score: number;
  supporting_refs: any[];
  execution_metadata: {
    query_count: number;
    latency_ms: number;
    timestamp?: string;
    cache_hit?: boolean;
    cache_ttl_seconds?: number | null;
  };
}

interface ExecuteResult {
  agents_executed: string[];
  merged: Insight;
  insights: Insight[];
  errors?: { agent: string; error: string }[];
}

const AGENT_ICONS: Record<string, React.ReactNode> = {
  inventory_intelligence: <Package className="h-5 w-5" />,
  import_clearance: <Truck className="h-5 w-5" />,
  compliance_monitoring: <FileCheck className="h-5 w-5" />,
  cold_chain_integrity: <Thermometer className="h-5 w-5" />,
  cold_room_capacity: <Thermometer className="h-5 w-5" />,
  logistics_optimization: <Truck className="h-5 w-5" />,
  financial_analyst: <DollarSign className="h-5 w-5" />,
  revenue_strategy: <TrendingUp className="h-5 w-5" />,
  enterprise_risk: <AlertCircle className="h-5 w-5" />,
  process_optimization: <Settings className="h-5 w-5" />,
  expiry_monitoring: <AlertTriangle className="h-5 w-5" />,
};

const AGENT_DESCRIPTIONS: Record<string, string> = {
  inventory_intelligence: "Monitors stock levels, detects low stock, and triggers replenishment workflows",
  import_clearance: "Tracks shipments, monitors clearance delays, and evaluates supplier reliability",
  compliance_monitoring: "Ensures NAFDAC compliance, blocks non-approved batches from sale",
  cold_chain_integrity: "Monitors temperature deviations and flags affected batches",
  cold_room_capacity: "Tracks cold room utilization and forecasts overflow risk",
  logistics_optimization: "Monitors delivery SLAs, route efficiency, and dispatch performance",
  financial_analyst: "Analyzes AR aging, customer risk scoring, and margin metrics",
  revenue_strategy: "Decomposes revenue goals and suggests growth strategies",
  enterprise_risk: "Cross-domain risk analysis combining regulatory, inventory, and finance",
  process_optimization: "Identifies bottlenecks and suggests process improvements",
  expiry_monitoring: "Tracks near-expiry items and triggers promotion workflows",
};

export default function AgentsDashboard() {
  const navigate = useNavigate();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [executing, setExecuting] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<ExecuteResult | null>(null);
  const [singleInsight, setSingleInsight] = useState<Insight | null>(null);
  const { toast } = useToast();

  useEffect(() => {
    loadAgents();
  }, []);

  const loadAgents = async () => {
    try {
      setLoading(true);
      const res = await api.agents.list();
      setAgents(res.agents || []);
    } catch (err: any) {
      toast({
        title: "Failed to load agents",
        description: err.message,
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };

  const executeAgents = async () => {
    if (!question.trim()) {
      toast({
        title: "Question required",
        description: "Enter a question to route to relevant agents",
        variant: "destructive",
      });
      return;
    }
    try {
      setExecuting("all");
      setResult(null);
      const res = await api.agents.execute(question, "executive");
      setResult(res);
      toast({
        title: "Agents executed",
        description: `${res.agents_executed?.length || 0} agent(s) ran successfully`,
      });
    } catch (err: any) {
      toast({
        title: "Execution failed",
        description: err.message,
        variant: "destructive",
      });
    } finally {
      setExecuting(null);
    }
  };

  const runSingleAgent = async (agentName: string) => {
    try {
      setExecuting(agentName);
      setSingleInsight(null);

      // Cache-first read for fast UX
      const cached = await api.agents.cached(agentName).catch(() => null);
      const ttl = await api.agents.cacheTtl(agentName).catch(() => null);
      if (cached?.value) {
        setSingleInsight({
          ...cached.value,
          _agent_name: agentName,
          execution_metadata: {
            ...(cached.value.execution_metadata || {}),
            cache_hit: true,
            cache_ttl_seconds: ttl?.ttl_seconds,
          },
        });
        toast({
          title: "Loaded from cache",
          description: `${agentName} result reused (${ttl?.ttl_seconds ?? "?"}s TTL)` ,
        });
        return;
      }

      const res = await api.agents.run(agentName);
      setSingleInsight({ ...res.insight, _agent_name: agentName });
      toast({
        title: "Agent executed",
        description: `${agentName} completed successfully`,
      });
    } catch (err: any) {
      toast({
        title: "Execution failed",
        description: err.message,
        variant: "destructive",
      });
    } finally {
      setExecuting(null);
    }
  };

  const formatAgentName = (name: string) => {
    return name
      .split("_")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");
  };

  return (
    <div className="p-8 space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <Bot className="h-8 w-8 text-primary" />
            Intelligence Agents
          </h2>
          <p className="text-muted-foreground">
            Department-scoped analyst agents with closed-loop automation
          </p>
        </div>
        <Button variant="outline" onClick={loadAgents} disabled={loading}>
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      <Tabs defaultValue="agents" className="space-y-4">
        <TabsList>
          <TabsTrigger value="agents">Agent Stack</TabsTrigger>
          <TabsTrigger value="execute">Query Execution</TabsTrigger>
          <TabsTrigger value="results">Results</TabsTrigger>
        </TabsList>

        <TabsContent value="agents" className="space-y-4">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              <AnimatePresence>
                {agents.map((agent, idx) => (
                  <motion.div
                    key={agent.name}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: idx * 0.05 }}
                  >
                    <Card className="hover:shadow-md transition-shadow">
                      <CardHeader className="pb-2">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <div className="p-2 rounded-lg bg-primary/10 text-primary">
                              {AGENT_ICONS[agent.name] || <Sparkles className="h-5 w-5" />}
                            </div>
                            <CardTitle className="text-lg">
                              {formatAgentName(agent.name)}
                            </CardTitle>
                          </div>
                          {agent.required_role && (
                            <Badge variant="outline" className="text-xs">
                              {agent.required_role}
                            </Badge>
                          )}
                        </div>
                      </CardHeader>
                      <CardContent>
                        <p className="text-sm text-muted-foreground mb-4">
                          {AGENT_DESCRIPTIONS[agent.name] || "Department intelligence agent"}
                        </p>
                        <Button
                          size="sm"
                          onClick={() => runSingleAgent(agent.name)}
                          disabled={executing === agent.name}
                        >
                          {executing === agent.name ? (
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          ) : (
                            <Play className="mr-2 h-4 w-4" />
                          )}
                          Run Agent
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="ml-2"
                          onClick={() => navigate(`/agents/${agent.name}`)}
                        >
                          Details
                        </Button>
                      </CardContent>
                    </Card>
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          )}

          {/* Single Agent Result */}
          {singleInsight && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
            >
              <Card className="mt-6 border-primary/50">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <CheckCircle className="h-5 w-5 text-success" />
                    {formatAgentName(singleInsight._agent_name || "Agent")} Result
                  </CardTitle>
                  <CardDescription>
                    Confidence: {Math.round((singleInsight.confidence_score || 0) * 100)}% •
                    Latency: {singleInsight.execution_metadata?.latency_ms || 0}ms
                    {singleInsight.execution_metadata?.cache_hit ? " • Cache Hit" : ""}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  {/* Metrics */}
                  {Object.keys(singleInsight.metrics || {}).length > 0 && (
                    <div>
                      <h4 className="font-medium mb-2 flex items-center gap-1">
                        <TrendingUp className="h-4 w-4" /> Metrics
                      </h4>
                      <div className="grid gap-2 md:grid-cols-3">
                        {Object.entries(singleInsight.metrics).map(([key, value]) => (
                          <div key={key} className="bg-muted rounded-lg p-3">
                            <p className="text-xs text-muted-foreground">{key}</p>
                            <p className="text-lg font-semibold">{String(value)}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Findings */}
                  {singleInsight.findings?.length > 0 && (
                    <div>
                      <h4 className="font-medium mb-2 flex items-center gap-1">
                        <Info className="h-4 w-4" /> Findings
                      </h4>
                      <ul className="space-y-1">
                        {singleInsight.findings.map((f, i) => (
                          <li key={i} className="text-sm text-muted-foreground">• {f}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Recommendations */}
                  {singleInsight.recommendations?.length > 0 && (
                    <div>
                      <h4 className="font-medium mb-2 flex items-center gap-1">
                        <Sparkles className="h-4 w-4" /> Recommendations
                      </h4>
                      <ul className="space-y-1">
                        {singleInsight.recommendations.map((r, i) => (
                          <li key={i} className="text-sm text-muted-foreground">• {r}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Risks */}
                  {singleInsight.risks?.length > 0 && (
                    <div>
                      <h4 className="font-medium mb-2 text-warning flex items-center gap-1">
                        <AlertTriangle className="h-4 w-4" /> Risks
                      </h4>
                      <ul className="space-y-1">
                        {singleInsight.risks.map((r, i) => (
                          <li key={i} className="text-sm text-warning">• {r}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </CardContent>
              </Card>
            </motion.div>
          )}
        </TabsContent>

        <TabsContent value="execute" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Query-Based Execution</CardTitle>
              <CardDescription>
                Ask a question and the system will route it to relevant agents automatically
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex gap-2">
                <Input
                  placeholder="e.g., What's the current inventory risk? Show me cold chain status."
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && executeAgents()}
                />
                <Button onClick={executeAgents} disabled={executing === "all"}>
                  {executing === "all" ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Play className="mr-2 h-4 w-4" />
                  )}
                  Execute
                </Button>
              </div>

              <div className="text-sm text-muted-foreground">
                <p className="font-medium mb-1">Example queries:</p>
                <ul className="space-y-1">
                  <li>• "Show me low stock items and expiry risks"</li>
                  <li>• "What's the cold chain status?"</li>
                  <li>• "Analyze AR aging and credit risks"</li>
                  <li>• "Review import clearance and supplier performance"</li>
                  <li>• "Give me an executive summary of all operations"</li>
                </ul>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="results" className="space-y-4">
          {result ? (
            <div className="space-y-6">
              {/* Summary */}
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <CheckCircle className="h-5 w-5 text-success" />
                    Merged Results
                  </CardTitle>
                  <CardDescription>
                    {result.agents_executed?.length || 0} agents executed
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-2 mb-4">
                    {result.agents_executed?.map((name) => (
                      <Badge key={name} variant="secondary">
                        {formatAgentName(name)}
                      </Badge>
                    ))}
                  </div>

                  {/* Merged Metrics */}
                  {result.merged && Object.keys(result.merged.metrics || {}).length > 0 && (
                    <div className="mb-4">
                      <h4 className="font-medium mb-2">Combined Metrics</h4>
                      <div className="grid gap-2 md:grid-cols-4">
                        {Object.entries(result.merged.metrics).map(([key, value]) => (
                          <div key={key} className="bg-muted rounded-lg p-3">
                            <p className="text-xs text-muted-foreground">{key}</p>
                            <p className="text-lg font-semibold">{String(value)}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Merged Findings */}
                  {result.merged?.findings?.length > 0 && (
                    <div className="mb-4">
                      <h4 className="font-medium mb-2">Key Findings</h4>
                      <ul className="space-y-1">
                        {result.merged.findings.map((f, i) => (
                          <li key={i} className="text-sm text-muted-foreground">• {f}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Merged Recommendations */}
                  {result.merged?.recommendations?.length > 0 && (
                    <div>
                      <h4 className="font-medium mb-2">Recommendations</h4>
                      <ScrollArea className="h-40">
                        <ul className="space-y-1">
                          {result.merged.recommendations.map((r, i) => (
                            <li key={i} className="text-sm text-muted-foreground">• {r}</li>
                          ))}
                        </ul>
                      </ScrollArea>
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Individual Agent Results */}
              {result.insights?.map((insight, idx) => (
                <Card key={idx}>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-lg flex items-center gap-2">
                      {AGENT_ICONS[insight._agent_name || ""] || <Bot className="h-5 w-5" />}
                      {formatAgentName(insight._agent_name || `Agent ${idx + 1}`)}
                    </CardTitle>
                    <CardDescription>
                      Confidence: {Math.round((insight.confidence_score || 0) * 100)}%
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="grid gap-2 md:grid-cols-3">
                      {Object.entries(insight.metrics || {}).map(([key, value]) => (
                        <div key={key} className="bg-muted rounded-lg p-2">
                          <p className="text-xs text-muted-foreground">{key}</p>
                          <p className="font-medium">{String(value)}</p>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              ))}

              {/* Errors */}
              {result.errors && result.errors.length > 0 && (
                <Card className="border-destructive/50">
                  <CardHeader>
                    <CardTitle className="text-destructive flex items-center gap-2">
                      <AlertCircle className="h-5 w-5" />
                      Errors
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    {result.errors.map((err, i) => (
                      <div key={i} className="text-sm text-destructive">
                        {err.agent}: {err.error}
                      </div>
                    ))}
                  </CardContent>
                </Card>
              )}
            </div>
          ) : (
            <Card>
              <CardContent className="p-12 text-center text-muted-foreground">
                <Bot className="h-12 w-12 mx-auto mb-4 opacity-50" />
                <p>No results yet. Run agents from the "Query Execution" tab.</p>
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
