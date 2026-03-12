import { Link } from "react-router-dom";
import { 
  ArrowRight, 
  TrendingUp, 
  AlertCircle, 
  Users, 
  Package, 
  Activity,
  CreditCard,
  Truck,
  CheckCircle2
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { 
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, LineChart, Line 
} from 'recharts';
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

const Dashboard = () => {
  const queryClient = useQueryClient();

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

  const { data: financeData, isError: financeIsError } = useQuery({
        queryKey: ["dashboard-revenue"],
        queryFn: api.dashboard.finance,
    });

    // New: Fetch financial trends (Cashflow)
    const { data: trendData, isError: trendIsError } = useQuery({
        queryKey: ["dashboard-trend"],
        queryFn: () => api.finance.trend(),
    });

    const { data: stockData, isError: stockIsError } = useQuery({
        queryKey: ["dashboard-stock"],
        queryFn: () => api.inventory.stock(), // This calls /stock which returns {"stock": [...]}
    });

    const { data: workforceData, isError: workforceIsError } = useQuery({
        queryKey: ["dashboard-workforce"],
        queryFn: () => api.dashboard.workforce(),
    });

    const { data: alertsData, isError: alertsIsError } = useQuery({
         queryKey: ["dashboard-alerts"],
         queryFn: () => api.dashboard.alerts(),
    });

    const financeValid =
      !!financeData &&
      typeof (financeData as any).ar?.total_amount === "number";
    const trendValid =
      !!trendData &&
      Array.isArray((trendData as any).periods);
    const stockValid = Array.isArray(stockData);
    const workforceValid =
      !!workforceData &&
      typeof (workforceData as any).active_staff_count === "number" &&
      typeof (workforceData as any).department_breakdown === "object";
    const alertsValid = Array.isArray(alertsData);

    const revenue = financeValid ? (financeData as any).ar.total_amount : null;
    
    // Process Trend Data
    const cashflowData = trendValid ? ((trendData as any).periods as any[]).map((p: any) => ({
        month: p.period,
      inflow: Number(p.inflow ?? p.amount ?? 0) / 1000000,
      outflow: Number(p.outflow ?? 0) / 1000000,
    })).sort((a: any, b: any) => a.month.localeCompare(b.month)) : []; // Ensure chronological order

    // Process inventory for Critical Items (Low Stock)
    const criticalItems = (stockValid ? stockData : []).filter((item: any) => {
        // Low stock if < 10 and > 0, Out of Stock if 0
        return (item.current_stock !== undefined ? item.current_stock : item.quantity || 0) < 10;
    }).map((item: any) => ({
        sku: item.sku,
        name: item.name,
        stock: item.current_stock !== undefined ? item.current_stock : item.quantity,
        status: (item.current_stock !== undefined ? item.current_stock : item.quantity) <= 0 ? "Out of Stock" : "Low Stock"
    }));

    const lowStockCount = criticalItems.length;
    const totalSkus = stockValid ? stockData.length : null;
    // Workforce Data
    const activeWorkforce = workforceValid ? (workforceData as any).active_staff_count : null;
    const deptBreakdown = workforceValid ? (workforceData as any).department_breakdown : {};
    const deptChartData = Object.keys(deptBreakdown).map(k => ({ name: k, hours: deptBreakdown[k] }));

    // Alerts Data
    const alerts = alertsValid ? alertsData : [];

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionTransitions.standard}
      className="space-y-8"
    >
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Business Overview</h1>
          <p className="text-muted-foreground">Real-time operational command center.</p>
        </div>
        <div className="flex gap-2">
           <Link to="/executive">
             <Button variant="default">
               <Activity className="mr-2 h-4 w-4" />
               Executive Briefing
             </Button>
           </Link>
           <Button variant="outline" onClick={() => window.location.reload()}>Refresh Data</Button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Revenue (AR)</CardTitle>
            <CreditCard className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {financeValid ? (
              <div className="text-2xl font-bold">₦{(revenue as number).toLocaleString()}</div>
            ) : (
              <div className="text-sm text-muted-foreground">Temporarily unavailable</div>
            )}
            <p className="text-xs text-success font-medium">Real-time from Sage</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Stock Health</CardTitle>
            <Truck className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {stockValid ? (
              <div className="text-2xl font-bold">{lowStockCount}</div>
            ) : (
              <div className="text-sm text-muted-foreground">Temporarily unavailable</div>
            )}
            <p className="text-xs text-muted-foreground">Low stock items</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Inventory Overview</CardTitle>
            <Package className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {stockValid ? (
              <>
                <div className="text-2xl font-bold">{totalSkus} SKUs</div>
                <p className="text-xs text-muted-foreground">{lowStockCount} Alerts</p>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">Temporarily unavailable</p>
            )}
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active Workforce</CardTitle>
            <Users className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {workforceValid ? (
              <div className="text-2xl font-bold">{activeWorkforce}</div>
            ) : (
              <div className="text-sm text-muted-foreground">Temporarily unavailable</div>
            )}
            <p className="text-xs text-muted-foreground">Staff members online</p>
          </CardContent>
        </Card>
      </div>

      {/* Main Charts Row */}
      <div className="grid gap-4 md:grid-cols-1 lg:grid-cols-7">
        
        {/* Financial Chart */}
        <Card className="col-span-4">
          <CardHeader>
            <CardTitle>Financial Performance</CardTitle>
            <CardDescription>Accounts Receivable Trend (Last 6 Months)</CardDescription>
          </CardHeader>
          <CardContent className="pl-2">
            {trendValid && cashflowData.length > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={cashflowData}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="month" stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} />
                  <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(value) => `₦${value}M`} />
                  <Tooltip formatter={(value: number) => `₦${value.toFixed(2)}M`} />
                  <Bar dataKey="inflow" name="Invoiced (AR)" fill="hsl(var(--primary))" radius={[8, 8, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-muted-foreground px-4 py-8">Trend data is temporarily unavailable.</p>
            )}
             <div className="flex justify-end p-4">
                <Link to="/finance/analytics">
                   <Button variant="ghost" size="sm">View Detailed Report <ArrowRight className="ml-2 h-4 w-4" /></Button>
                </Link>
             </div>
          </CardContent>
        </Card>

        {/* Inventory Critical Table */}
        <Card className="col-span-3">
          <CardHeader>
            <CardTitle>Critical Inventory</CardTitle>
            <CardDescription>Items needing immediate attention</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
               <TableHeader>
                  <TableRow>
                     <TableHead>SKU</TableHead>
                     <TableHead>Stock</TableHead>
                     <TableHead className="text-right">Status</TableHead>
                  </TableRow>
               </TableHeader>
               <TableBody>
                  {!stockValid ? (
                    <TableRow>
                      <TableCell colSpan={3} className="text-center text-muted-foreground p-4">
                        Stock data is temporarily unavailable.
                      </TableCell>
                    </TableRow>
                  ) : criticalItems.length > 0 ? (
                      criticalItems.map((item: any) => (
                         <TableRow key={item.sku}>
                            <TableCell>
                               <div className="font-medium">{item.name}</div>
                               <div className="text-xs text-muted-foreground">{item.sku}</div>
                            </TableCell>
                            <TableCell>{item.stock}</TableCell>
                            <TableCell className="text-right">
                               <Badge variant={item.stock === 0 ? "destructive" : "outline"} className={item.stock > 0 ? "text-warning border-warning/70" : ""}>
                                  {item.status}
                               </Badge>
                            </TableCell>
                         </TableRow>
                      ))
                  ) : (
                      <TableRow>
                          <TableCell colSpan={3} className="text-center text-muted-foreground p-4">
                              <div className="flex flex-col items-center gap-2">
                                <CheckCircle2 className="h-8 w-8 text-success" />
                                <p>All items within healthy stock levels</p>
                              </div>
                          </TableCell>
                      </TableRow>
                  )}
               </TableBody>
            </Table>
            <div className="flex justify-end pt-4">
               <Link to="/operations">
                  <Button variant="ghost" size="sm">Manage Inventory <ArrowRight className="ml-2 h-4 w-4" /></Button>
               </Link>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Workforce Quick View */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
         <Card className="col-span-1">
            <CardHeader>
               <CardTitle>Workforce Distribution</CardTitle>
               <CardDescription>Headcount by Department</CardDescription>
            </CardHeader>
            <CardContent>
               <div className="h-[200px]">
                  {workforceValid && deptChartData.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={deptChartData} layout="vertical">
                        <XAxis type="number" hide />
                        <YAxis dataKey="name" type="category" width={80} tickLine={false} axisLine={false} style={{fontSize: '11px'}} />
                        <Tooltip />
                        <Bar dataKey="hours" name="Staff Count" fill="hsl(var(--secondary))" radius={[0, 8, 8, 0]} barSize={20} />
                      </BarChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="text-sm text-muted-foreground py-4">Department breakdown is temporarily unavailable.</div>
                  )}
               </div>
               <div className="flex justify-end">
                 <Link to="/hr">
                    <Button variant="ghost" size="sm">HR Dashboard <ArrowRight className="ml-2 h-4 w-4" /></Button>
                 </Link>
               </div>
            </CardContent>
         </Card>
         
        <Card className="col-span-2 border-border/50 bg-muted/30">
            <CardHeader>
               <CardTitle className="flex items-center gap-2">
              <Activity className="h-5 w-5 text-primary" />
                  System Notifications
               </CardTitle>
            </CardHeader>
            <CardContent>
               <div className="space-y-4">
                {!alertsValid ? (
                  <div className="text-sm text-muted-foreground">Alerts are temporarily unavailable.</div>
                ) : alerts.length > 0 ? (
                     alerts.map((alert: any, idx: number) => (
                      <div key={idx} className="pw-surface-base flex items-start gap-4 rounded-xl p-3">
                           {alert.severity === 'critical' ? (
                           <AlertCircle className="h-5 w-5 text-destructive mt-0.5" />
                           ) : (
                           <TrendingUp className="h-5 w-5 text-primary mt-0.5" />
                           )}
                           <div>
                              <p className="text-sm font-medium">{alert.title}</p>
                              <p className="text-sm text-muted-foreground">{alert.message}</p>
                          <p className="mt-1 text-xs text-muted-foreground">{new Date(alert.created_at).toLocaleTimeString()}</p>
                           </div>
                        </div>
                     ))
                  ) : (
                     <div className="flex flex-col items-center justify-center p-8 text-muted-foreground">
                      <CheckCircle2 className="mb-2 h-8 w-8 text-success/70" />
                        <p>No new system alerts</p>
                     </div>
                  )}
               </div>
                {financeIsError || trendIsError || stockIsError || workforceIsError || alertsIsError ? (
                  <p className="text-xs text-muted-foreground">Some cards are showing fallback values while data refresh completes.</p>
                ) : null}
            </CardContent>
         </Card>
      </div>

    </motion.div>
  );
};

export default Dashboard;
