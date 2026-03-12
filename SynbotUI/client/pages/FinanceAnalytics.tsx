import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { FinancialDashboard } from "@/components/dashboards/FinancialDashboard";
import { GeneralLedgerTable } from "@/components/dashboards/GeneralLedgerTable";
import { ProfitabilityDashboard } from "@/components/dashboards/ProfitabilityDashboard";
import { Button } from "@/components/ui/button";
import { FileDown, PieChart, Loader2 } from "lucide-react";
import { api } from "@/lib/api-client";
import { useToast } from "@/hooks/use-toast";
import { useQueryClient } from "@tanstack/react-query";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";

/**
 * Finance Page - Combines Analytics (Dashboard) and Reports
 */
const FinanceAnalytics = () => {
  const queryClient = useQueryClient();
  const [exporting, setExporting] = useState(false);
  const { toast } = useToast();

  useRealtimeChannel("workflow_updates", () => {
    void queryClient.invalidateQueries({ queryKey: ["finance-kpis"] });
    void queryClient.invalidateQueries({ queryKey: ["finance-trend"] });
    void queryClient.invalidateQueries({ queryKey: ["finance-transactions"] });
    void queryClient.invalidateQueries({ queryKey: ["finance-profitability"] });
    void queryClient.invalidateQueries({ queryKey: ["finance-gl"] });
    void queryClient.invalidateQueries({ queryKey: ["ar-trends"] });
  });

  useRealtimeChannel("alerts_updates", () => {
    void queryClient.invalidateQueries({ queryKey: ["finance-kpis"] });
    void queryClient.invalidateQueries({ queryKey: ["finance-trend"] });
  });

  useRealtimeChannel("finance_updates", () => {
    void queryClient.invalidateQueries({ queryKey: ["finance-kpis"] });
    void queryClient.invalidateQueries({ queryKey: ["finance-trend"] });
    void queryClient.invalidateQueries({ queryKey: ["finance-transactions"] });
    void queryClient.invalidateQueries({ queryKey: ["finance-profitability"] });
    void queryClient.invalidateQueries({ queryKey: ["finance-gl"] });
  });

  const handleExportPL = async () => {
    try {
      setExporting(true);
      // Fetch profitability data
      const data = await api.finance.profitability();
      
      // Convert to CSV
      const rows = [
        ["Metric", "Value"],
        ["Total Revenue", data.total_revenue ?? 0],
        ["Total Cost", data.total_cost ?? 0],
        ["Gross Profit", data.gross_profit ?? 0],
        ["Net Margin %", data.net_margin ?? 0],
        ["Period", data.period ?? "Current"],
      ];
      const csv = rows.map(r => r.join(",")).join("\n");
      
      // Download
      const blob = new Blob([csv], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `pl_report_${new Date().toISOString().slice(0,10)}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      
      toast({ title: "Export Complete", description: "P&L report has been downloaded." });
    } catch (err: any) {
      toast({ title: "Export Failed", description: err.message, variant: "destructive" });
    } finally {
      setExporting(false);
    }
  };

  const handleNewReport = () => {
    toast({
      title: "Custom Reports",
      description: "Navigate to the Reports tab or use the AR Aging report in the sidebar for detailed analysis.",
    });
  };

  return (
    <div className="p-8 space-y-8">
      <div className="flex items-center justify-between">
        <div>
           <h2 className="text-3xl font-bold tracking-tight">Financial Intelligence</h2>
           <p className="text-muted-foreground">Monitor cashflow, AR/AP, and profitability.</p>
        </div>
        <div className="flex gap-2">
           <Button variant="outline" onClick={handleExportPL} disabled={exporting}>
              {exporting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <FileDown className="mr-2 h-4 w-4" />}
              Export P&L
           </Button>
           <Button onClick={handleNewReport}>
              <PieChart className="mr-2 h-4 w-4" />
              New Report
           </Button>
        </div>
      </div>

      <Tabs defaultValue="dashboard" className="space-y-4">
        <TabsList>
          <TabsTrigger value="dashboard">Dashboard</TabsTrigger>
          <TabsTrigger value="profitability">Profitability</TabsTrigger>
          <TabsTrigger value="ledgers">Ledgers</TabsTrigger>
        </TabsList>
        <TabsContent value="dashboard" className="space-y-4">
           <FinancialDashboard />
        </TabsContent>
        <TabsContent value="profitability">
           <ProfitabilityDashboard />
        </TabsContent>
        <TabsContent value="ledgers">
           <GeneralLedgerTable />
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default FinanceAnalytics;
