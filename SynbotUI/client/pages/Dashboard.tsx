import { Link } from "react-router-dom";
import {
  ArrowRight,
  TrendingUp,
  TrendingDown,
  AlertCircle,
  Users,
  Package,
  Activity,
  CreditCard,
  Truck,
  CheckCircle2,
  AlertTriangle,
  X,
  Thermometer,
  Target,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  LineChart, Line, AreaChart, Area,
} from "recharts";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useQuery } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";
import { useState } from "react";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { useIsMobile } from "@/hooks/use-mobile";

const Dashboard = () => {
  const queryClient = useQueryClient();
  const isMobile = useIsMobile();
  const [alertDismissed, setAlertDismissed] = useState(false);

  useRealtimeChannel("alerts_updates", () => {
    queryClient.invalidateQueries({ queryKey: ["dashboard-alerts"] });
  });
  useRealtimeChannel("inventory_updates", () => {
    queryClient.invalidateQueries({ queryKey: ["dashboard-stock"] });
  });
  useRealtimeChannel("workflow_updates", (message) => {
    const evt = message?.event;
    if (["batch_locked", "batch_approved"].includes(evt)) {
      queryClient.invalidateQueries({ queryKey: ["dashboard-alerts"] });
    }
  });
  useRealtimeChannel("finance_updates", () => {
    queryClient.invalidateQueries({ queryKey: ["dashboard-revenue"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard-trend"] });
  });
  useRealtimeChannel("logistics_updates", () => {
    queryClient.invalidateQueries({ queryKey: ["dashboard-stock"] });
  });

  const { data: financeData, isLoading: financeLoading, isError: financeIsError } = useQuery({
    queryKey: ["dashboard-revenue"],
    queryFn: api.dashboard.finance,
  });
  const { data: trendData, isLoading: trendLoading, isError: trendIsError } = useQuery({
    queryKey: ["dashboard-trend"],
    queryFn: () => api.finance.trend(),
  });
  const { data: stockData, isLoading: stockLoading, isError: stockIsError } = useQuery({
    queryKey: ["dashboard-stock"],
    queryFn: () => api.inventory.stock(),
  });
  const { data: workforceData, isLoading: workforceLoading, isError: workforceIsError } = useQuery({
    queryKey: ["dashboard-workforce"],
    queryFn: () => api.dashboard.workforce(),
  });
  const { data: alertsData, isLoading: alertsLoading, isError: alertsIsError } = useQuery({
    queryKey: ["dashboard-alerts"],
    queryFn: () => api.dashboard.alerts(),
  });

  const financeValid = !!financeData && typeof (financeData as any).ar?.total_amount === "number";
  const trendValid = !!trendData && Array.isArray((trendData as any).periods);
  const stockValid = Array.isArray(stockData);
  const workforceValid =
    !!workforceData &&
    typeof (workforceData as any).active_staff_count === "number" &&
    typeof (workforceData as any).department_breakdown === "object";
  const alertsValid = Array.isArray(alertsData);

  const revenue = financeValid ? (financeData as any).ar.total_amount : null;

  const cashflowData = trendValid
    ? ((trendData as any).periods as any[])
        .map((p: any) => ({
          month: p.period,
          inflow: Number(p.inflow ?? p.amount ?? 0) / 1_000_000,
          outflow: Number(p.outflow ?? 0) / 1_000_000,
        }))
        .sort((a: any, b: any) => a.month.localeCompare(b.month))
    : [];

  const criticalItems = (stockValid ? stockData : [])
    .filter((item: any) => (item.current_stock !== undefined ? item.current_stock : item.quantity || 0) < 10)
    .map((item: any) => ({
      sku: item.sku,
      name: item.name,
      stock: item.current_stock !== undefined ? item.current_stock : item.quantity,
      status: (item.current_stock !== undefined ? item.current_stock : item.quantity) <= 0 ? "Out of Stock" : "Low Stock",
    }));

  const lowStockCount = criticalItems.length;
  const totalSkus = stockValid ? (stockData as any[]).length : null;
  const activeWorkforce = workforceValid ? (workforceData as any).active_staff_count : null;
  const deptBreakdown = workforceValid ? (workforceData as any).department_breakdown : {};
  const deptChartData = Object.keys(deptBreakdown).map((k) => ({ name: k, count: deptBreakdown[k] }));
  const alerts = alertsValid ? (alertsData as any[]) : [];
  const criticalAlerts = alerts.filter((a: any) => a.severity === "critical");
  const hasCritical = criticalAlerts.length > 0 && !alertDismissed;

  const { data: crmDashData } = useQuery({
    queryKey: ["dashboard-crm-count"],
    queryFn: () => api.dashboard.crm(),
  });
  const customerCount = (crmDashData as any)?.customer_count ?? 0;

  const { data: expiryAlertsData } = useQuery({
    queryKey: ["dashboard-expiry-alerts"],
    queryFn: () => api.qc.expiryAlerts(),
  });
  const expiryBuckets = (expiryAlertsData as any)?.buckets;
  const nearExpiryCount = expiryBuckets
    ? (expiryBuckets.expired?.length ?? 0) + (expiryBuckets.critical?.length ?? 0) + (expiryBuckets.high?.length ?? 0)
    : null;

  const { data: deviationsData } = useQuery({
    queryKey: ["dashboard-cold-deviations"],
    queryFn: () => api.qc.activeDeviations(),
  });
  const coldDeviationCount = Array.isArray(deviationsData)
    ? (deviationsData as any[]).length
    : (deviationsData as any)?.total ?? (deviationsData as any)?.count ?? null;

  const { data: pipelineData } = useQuery({
    queryKey: ["dashboard-prospect-pipeline"],
    queryFn: () => api.dashboard.crm(),
  });
  const prospectPipeline = (pipelineData as any)?.pipeline_value ?? null;

  const { data: poSummaryData } = useQuery({
    queryKey: ["dashboard-po-summary"],
    queryFn: () => api.procurement.purchaseOrdersSummary(),
  });
  const openPoCount = (poSummaryData as any)?.open_pos ?? null;

  // Detect if all data loaded but every value is genuinely zero/empty (no Sage import yet)
  const allLoaded = !financeLoading && !trendLoading && !stockLoading && !workforceLoading && !alertsLoading;
  const noSageData =
    allLoaded &&
    !financeIsError &&
    !stockIsError &&
    !workforceIsError &&
    (revenue === 0 || revenue === null) &&
    (totalSkus === 0 || totalSkus === null) &&
    (activeWorkforce === 0 || activeWorkforce === null) &&
    customerCount === 0;

  // KPI health helpers
  const stockHealthy = lowStockCount === 0;
  const stockBorderClass = stockHealthy
    ? "border-l-4 border-l-success"
    : lowStockCount > 5
    ? "border-l-4 border-l-destructive"
    : "border-l-4 border-l-warning";

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionTransitions.standard}
      className="flex flex-col gap-5"
    >
      {/* ── No Sage Data Banner ─────────────────────────────────── */}
      {noSageData && (
        <div className="flex items-center gap-3 rounded-xl border border-muted-foreground/20 bg-muted/40 px-4 py-2.5 text-sm text-muted-foreground">
          <Activity className="h-4 w-4 shrink-0" />
          <span className="flex-1">
            No Sage data has been imported yet. Use the{" "}
            <Link to="/knowledge" className="font-medium underline underline-offset-2 hover:text-foreground">Knowledge Base</Link>{" "}
            page to import CSV exports from Sage.
          </span>
        </div>
      )}

      {/* ── Global Critical Alert Banner ─────────────────────────── */}
      {hasCritical && (
        <div className="flex items-center gap-3 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-2.5 text-sm text-destructive">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span className="flex-1 font-medium">
            {criticalAlerts[0].title}: {criticalAlerts[0].message}
          </span>
          <button
            onClick={() => setAlertDismissed(true)}
            className="rounded p-0.5 hover:bg-destructive/20 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* ── Page Header ─────────────────────────────────────────── */}
      <div className="flex flex-col gap-1 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Business Overview</h1>
          <p className="text-sm text-muted-foreground">Real-time operational command center</p>
        </div>
        <div className="flex gap-2">
          <Link to="/executive">
            <Button variant="default" size="sm">
              <Activity className="mr-2 h-4 w-4" />
              Executive Briefing
            </Button>
          </Link>
          <Button variant="outline" size="sm" onClick={() => {
              void queryClient.invalidateQueries();
            }}>
            Refresh
          </Button>
        </div>
      </div>

      {/* ── KPI Cards ───────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {/* Revenue */}
        <Card className="border-l-4 border-l-primary bg-gradient-to-br from-primary/5 to-card">
          <CardHeader className="pb-2 pt-4">
            <div className="flex items-center justify-between">
              <CardDescription className="text-xs font-medium uppercase tracking-wide">Total Revenue (AR)</CardDescription>
              <CreditCard className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent className="pb-4">
            <div className="text-3xl font-bold tabular-nums">
              {financeLoading ? (
                <Skeleton className="h-8 w-32" />
              ) : financeValid ? (
                `₦${(revenue as number).toLocaleString()}`
              ) : (
                <span className="text-base text-muted-foreground">—</span>
              )}
            </div>
            <div className="mt-2 flex items-center gap-1 text-xs text-success font-medium">
              <TrendingUp className="h-3 w-3" />
              Real-time from Sage
            </div>
          </CardContent>
        </Card>

        {/* Stock Health */}
        <Card className={cn("bg-gradient-to-br from-card", stockBorderClass)}>
          <CardHeader className="pb-2 pt-4">
            <div className="flex items-center justify-between">
              <CardDescription className="text-xs font-medium uppercase tracking-wide">Stock Health</CardDescription>
              <Truck className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent className="pb-4">
            <div className="text-3xl font-bold tabular-nums">
              {stockLoading ? (
                <Skeleton className="h-8 w-16" />
              ) : stockValid ? (
                lowStockCount
              ) : (
                <span className="text-base text-muted-foreground">—</span>
              )}
            </div>
            <div className={cn("mt-2 flex items-center gap-1 text-xs font-medium",
              stockHealthy ? "text-success" : lowStockCount > 5 ? "text-destructive" : "text-warning"
            )}>
              {stockLoading ? (
                <Skeleton className="h-3 w-24" />
              ) : stockHealthy ? (
                <><CheckCircle2 className="h-3 w-3" /> All items healthy</>
              ) : (
                <><AlertCircle className="h-3 w-3" /> {lowStockCount} low stock items</>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Inventory Overview */}
        <Card className="border-l-4 border-l-secondary bg-gradient-to-br from-secondary/5 to-card">
          <CardHeader className="pb-2 pt-4">
            <div className="flex items-center justify-between">
              <CardDescription className="text-xs font-medium uppercase tracking-wide">Inventory</CardDescription>
              <Package className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent className="pb-4">
            <div className="text-3xl font-bold tabular-nums">
              {stockLoading ? (
                <Skeleton className="h-8 w-16" />
              ) : stockValid ? (
                totalSkus
              ) : (
                <span className="text-base text-muted-foreground">—</span>
              )}
            </div>
            <div className="mt-2 text-xs text-muted-foreground">
              {stockLoading ? <Skeleton className="h-3 w-20" /> : stockValid ? `${lowStockCount} alerts` : "No data"}
            </div>
          </CardContent>
        </Card>

        {/* Workforce */}
        <Card className="border-l-4 border-l-info bg-gradient-to-br from-info/5 to-card">
          <CardHeader className="pb-2 pt-4">
            <div className="flex items-center justify-between">
              <CardDescription className="text-xs font-medium uppercase tracking-wide">Active Workforce</CardDescription>
              <Users className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent className="pb-4">
            <div className="text-3xl font-bold tabular-nums">
              {workforceLoading ? (
                <Skeleton className="h-8 w-16" />
              ) : workforceValid ? (
                activeWorkforce
              ) : (
                <span className="text-base text-muted-foreground">—</span>
              )}
            </div>
            <div className="mt-2 text-xs text-muted-foreground">Staff members online</div>
          </CardContent>
        </Card>
      </div>

      {/* ── Operational Alert Cards ─────────────────────────────── */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {/* Near-Expiry */}
        <Card className={cn("border-l-4", nearExpiryCount !== null && nearExpiryCount > 0 ? "border-l-warning" : "border-l-success")}>
          <CardHeader className="pb-2 pt-4">
            <div className="flex items-center justify-between">
              <CardDescription className="text-xs font-medium uppercase tracking-wide">Near-Expiry Items</CardDescription>
              <Package className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent className="pb-4">
            <div className="text-3xl font-bold tabular-nums">
              {nearExpiryCount !== null ? nearExpiryCount : <span className="text-base text-muted-foreground">—</span>}
            </div>
            <div className={cn("mt-2 flex items-center gap-1 text-xs font-medium",
              nearExpiryCount !== null && nearExpiryCount > 0 ? "text-warning" : "text-success"
            )}>
              <AlertCircle className="h-3 w-3" />
              {nearExpiryCount !== null && nearExpiryCount > 0 ? `${nearExpiryCount} items need attention` : "All items OK"}
            </div>
          </CardContent>
        </Card>

        {/* Cold-Chain Deviations */}
        <Card className={cn("border-l-4", coldDeviationCount !== null && coldDeviationCount > 0 ? "border-l-destructive" : "border-l-success")}>
          <CardHeader className="pb-2 pt-4">
            <div className="flex items-center justify-between">
              <CardDescription className="text-xs font-medium uppercase tracking-wide">Temp Deviations</CardDescription>
              <Thermometer className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent className="pb-4">
            <div className="text-3xl font-bold tabular-nums">
              {coldDeviationCount !== null ? coldDeviationCount : <span className="text-base text-muted-foreground">—</span>}
            </div>
            <div className={cn("mt-2 flex items-center gap-1 text-xs font-medium",
              coldDeviationCount !== null && coldDeviationCount > 0 ? "text-destructive" : "text-success"
            )}>
              <Thermometer className="h-3 w-3" />
              {coldDeviationCount !== null && coldDeviationCount > 0 ? "Active temperature breaches" : "All readings normal"}
            </div>
          </CardContent>
        </Card>

        {/* Prospect Pipeline */}
        <Card className="border-l-4 border-l-primary">
          <CardHeader className="pb-2 pt-4">
            <div className="flex items-center justify-between">
              <CardDescription className="text-xs font-medium uppercase tracking-wide">Prospect Pipeline</CardDescription>
              <Target className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent className="pb-4">
            <div className="text-3xl font-bold tabular-nums">
              {prospectPipeline !== null
                ? `₦${(Number(prospectPipeline) / 1_000_000).toFixed(1)}M`
                : <span className="text-base text-muted-foreground">—</span>}
            </div>
            <div className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
              <TrendingUp className="h-3 w-3" />
              Total open opportunity value
            </div>
          </CardContent>
        </Card>

        {/* Open POs */}
        <Card className="border-l-4 border-l-secondary">
          <CardHeader className="pb-2 pt-4">
            <div className="flex items-center justify-between">
              <CardDescription className="text-xs font-medium uppercase tracking-wide">Open Purchase Orders</CardDescription>
              <Truck className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent className="pb-4">
            <div className="text-3xl font-bold tabular-nums">
              {openPoCount !== null ? openPoCount : <span className="text-base text-muted-foreground">—</span>}
            </div>
            <div className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
              <Activity className="h-3 w-3" />
              Pending procurement orders
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ── Main Charts Row ─────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        {/* Financial Performance — col-span-8 */}
        <Card className="lg:col-span-8">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-base font-semibold">Financial Performance</CardTitle>
                <CardDescription className="text-xs">Accounts Receivable Trend (Last 6 Months)</CardDescription>
              </div>
              <Link to="/finance/analytics">
                <Button variant="ghost" size="sm" className="text-xs">
                  View Report <ArrowRight className="ml-1 h-3 w-3" />
                </Button>
              </Link>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <div className="h-[340px]">
              {trendValid && cashflowData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={cashflowData} margin={{ top: 8, right: 20, left: 8, bottom: 8 }}>
                    <defs>
                      <linearGradient id="colorInflow" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="hsl(var(--primary))" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="hsl(var(--primary))" stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" opacity={0.5} />
                    <XAxis dataKey="month" stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} />
                    <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(v) => `₦${v}M`} width={56} />
                    <Tooltip
                      formatter={(value: number) => [`₦${value.toFixed(2)}M`, "AR Inflow"]}
                      contentStyle={{ fontSize: "12px", borderRadius: "8px" }}
                    />
                    <Area
                      type="monotone"
                      dataKey="inflow"
                      name="Invoiced (AR)"
                      stroke="hsl(var(--primary))"
                      strokeWidth={2}
                      fill="url(#colorInflow)"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              ) : trendLoading ? (
                <div className="flex h-full flex-col gap-3 p-4">
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-5/6" />
                  <Skeleton className="h-4 w-4/6" />
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-3/4" />
                </div>
              ) : (
                <div className="flex h-full flex-col items-center justify-center gap-1 text-sm text-muted-foreground">
                  <Activity className="h-6 w-6 opacity-40" />
                  <span>No AR trend data available.</span>
                  <span className="text-xs opacity-70">Import Sage invoices to populate this chart.</span>
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Critical Inventory — col-span-4 */}
        <Card className="lg:col-span-4">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-base font-semibold">Critical Inventory</CardTitle>
                <CardDescription className="text-xs">Items needing attention</CardDescription>
              </div>
              <Link to="/operations">
                <Button variant="ghost" size="sm" className="text-xs">
                  Manage <ArrowRight className="ml-1 h-3 w-3" />
                </Button>
              </Link>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {isMobile ? (
              <div className="space-y-3 p-3">
                {stockLoading ? (
                  <div className="flex flex-col gap-2 px-1 py-2">
                    <Skeleton className="h-4 w-full" />
                    <Skeleton className="h-4 w-5/6" />
                    <Skeleton className="h-4 w-4/6" />
                  </div>
                ) : !stockValid ? (
                  <p className="py-6 text-center text-sm text-muted-foreground">Stock data unavailable.</p>
                ) : criticalItems.length > 0 ? (
                  criticalItems.map((item: any) => (
                    <div key={item.sku} className="rounded-lg border bg-card p-3 text-sm">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="font-medium leading-tight">{item.name}</p>
                          <p className="text-[11px] text-muted-foreground">{item.sku}</p>
                        </div>
                        <Badge
                          variant={item.stock === 0 ? "destructive" : "outline"}
                          className={cn("text-[10px]", item.stock > 0 && "border-warning/70 text-warning")}
                        >
                          {item.status}
                        </Badge>
                      </div>
                      <p className="mt-2 text-xs">Stock: <span className="font-semibold tabular-nums">{item.stock}</span></p>
                    </div>
                  ))
                ) : (
                  <div className="flex flex-col items-center gap-1.5 py-8 text-success">
                    <CheckCircle2 className="h-7 w-7" />
                    <p className="text-sm">All items healthy</p>
                  </div>
                )}
              </div>
            ) : (
              <div className="max-h-[300px] overflow-auto">
                <Table>
                  <TableHeader className="sticky top-0 bg-muted/80 backdrop-blur-sm">
                    <TableRow>
                      <TableHead className="sticky left-0 z-10 min-w-[220px] bg-muted/90 text-xs">Item</TableHead>
                      <TableHead className="min-w-[90px] text-right text-xs">Stock</TableHead>
                      <TableHead className="min-w-[100px] text-right text-xs">Status</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {stockLoading ? (
                      <TableRow>
                        <TableCell colSpan={3} className="py-6 text-center">
                          <div className="flex flex-col gap-2 px-4">
                            <Skeleton className="h-4 w-full" />
                            <Skeleton className="h-4 w-5/6" />
                            <Skeleton className="h-4 w-4/6" />
                          </div>
                        </TableCell>
                      </TableRow>
                    ) : !stockValid ? (
                      <TableRow>
                        <TableCell colSpan={3} className="py-8 text-center text-sm text-muted-foreground">
                          Stock data unavailable.
                        </TableCell>
                      </TableRow>
                    ) : criticalItems.length > 0 ? (
                      criticalItems.map((item: any) => (
                        <TableRow key={item.sku} className="text-sm">
                          <TableCell className="sticky left-0 z-10 bg-background">
                            <div className="font-medium leading-tight">{item.name}</div>
                            <div className="text-[11px] text-muted-foreground">{item.sku}</div>
                          </TableCell>
                          <TableCell className="text-right tabular-nums">{item.stock}</TableCell>
                          <TableCell className="text-right">
                            <Badge
                              variant={item.stock === 0 ? "destructive" : "outline"}
                              className={cn("text-[10px]", item.stock > 0 && "border-warning/70 text-warning")}
                            >
                              {item.status}
                            </Badge>
                          </TableCell>
                        </TableRow>
                      ))
                    ) : (
                      <TableRow>
                        <TableCell colSpan={3} className="py-8 text-center">
                          <div className="flex flex-col items-center gap-1.5 text-success">
                            <CheckCircle2 className="h-7 w-7" />
                            <p className="text-sm">All items healthy</p>
                          </div>
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ── Second Row: Workforce + Notifications ────────────────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        {/* Workforce Distribution — col-span-4 */}
        <Card className="lg:col-span-4">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-base font-semibold">Workforce Distribution</CardTitle>
                <CardDescription className="text-xs">Headcount by Department</CardDescription>
              </div>
              <Link to="/hr">
                <Button variant="ghost" size="sm" className="text-xs">
                  HR <ArrowRight className="ml-1 h-3 w-3" />
                </Button>
              </Link>
            </div>
          </CardHeader>
          <CardContent className="px-2 pb-4">
            <div className="h-[240px]">
              {workforceLoading ? (
                <div className="flex h-full flex-col gap-3 p-4">
                  <Skeleton className="h-5 w-full" />
                  <Skeleton className="h-5 w-4/5" />
                  <Skeleton className="h-5 w-3/5" />
                  <Skeleton className="h-5 w-full" />
                </div>
              ) : workforceValid && deptChartData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={deptChartData} layout="vertical">
                    <XAxis type="number" hide />
                    <YAxis
                      dataKey="name"
                      type="category"
                      width={90}
                      tickLine={false}
                      axisLine={false}
                      style={{ fontSize: "11px" }}
                    />
                    <Tooltip contentStyle={{ fontSize: "12px", borderRadius: "8px" }} />
                    <Bar
                      dataKey="count"
                      name="Staff Count"
                      fill="hsl(var(--secondary))"
                      radius={[0, 6, 6, 0]}
                      barSize={18}
                    />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="flex h-full flex-col items-center justify-center gap-1 text-sm text-muted-foreground">
                  <Users className="h-6 w-6 opacity-40" />
                  <span>No workforce data yet.</span>
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* System Notifications — col-span-8 */}
        <Card className="lg:col-span-8 border-border/50 bg-muted/20">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-base font-semibold">
              <Activity className="h-4 w-4 text-primary" />
              System Notifications
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="max-h-[240px] space-y-2 overflow-y-auto pr-1">
              {alertsLoading ? (
                <div className="space-y-2">
                  <Skeleton className="h-14 w-full rounded-xl" />
                  <Skeleton className="h-14 w-full rounded-xl" />
                </div>
              ) : !alertsValid ? (
                <div className="py-4 text-sm text-muted-foreground">Alerts temporarily unavailable.</div>
              ) : alerts.length > 0 ? (
                alerts.map((alert: any, idx: number) => (
                  <div
                    key={idx}
                    className={cn(
                      "flex items-start gap-3 rounded-xl border p-3",
                      alert.severity === "critical"
                        ? "border-l-4 border-l-destructive bg-destructive/5 border-destructive/30"
                        : "border-l-4 border-l-warning bg-warning/5 border-border/50",
                    )}
                  >
                    {alert.severity === "critical" ? (
                      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                    ) : (
                      <TrendingUp className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium leading-tight">{alert.title}</p>
                      <p className="text-xs text-muted-foreground">{alert.message}</p>
                      <p className="mt-0.5 text-[10px] text-muted-foreground/60">
                        {new Date(alert.created_at).toLocaleTimeString()}
                      </p>
                    </div>
                  </div>
                ))
              ) : (
                <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                  <CheckCircle2 className="mb-2 h-8 w-8 text-success/70" />
                  <p className="text-sm">No new system alerts</p>
                </div>
              )}
            </div>
            {(financeIsError || trendIsError || stockIsError || workforceIsError || alertsIsError) && (
              <p className="mt-2 text-xs text-muted-foreground/70">
                Some cards show fallback values while data refreshes.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ── Compact Reminders / Quick Links ─────────────────────── */}
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border/40 bg-muted/20 px-4 py-2.5 text-sm">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Quick Links:</span>
        <Link to="/executive">
          <Badge variant="outline" className="cursor-pointer hover:bg-accent transition-colors">📊 Executive Briefing</Badge>
        </Link>
        <Link to="/finance/analytics">
          <Badge variant="outline" className="cursor-pointer hover:bg-accent transition-colors">💰 Finance Analytics</Badge>
        </Link>
        <Link to="/calendar">
          <Badge variant="outline" className="cursor-pointer hover:bg-accent transition-colors">📅 Calendar & Tasks</Badge>
        </Link>
        <Link to="/compliance">
          <Badge variant="outline" className="cursor-pointer hover:bg-accent transition-colors">🛡 Compliance</Badge>
        </Link>
        <Link to="/synbot">
          <Badge variant="outline" className="cursor-pointer hover:bg-accent transition-colors">🤖 Ask ACE</Badge>
        </Link>
      </div>
    </motion.div>
  );
};

export default Dashboard;
