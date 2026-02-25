import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { FinancialDashboard } from "@/components/dashboards/FinancialDashboard";
import { GeneralLedgerTable } from "@/components/dashboards/GeneralLedgerTable";
import { ProfitabilityDashboard } from "@/components/dashboards/ProfitabilityDashboard";
import { Button } from "@/components/ui/button";
import { FileDown, PieChart } from "lucide-react";

/**
 * Finance Page - Combines Analytics (Dashboard) and Reports
 */
const FinanceAnalytics = () => {
  return (
    <div className="p-8 space-y-8">
      <div className="flex items-center justify-between">
        <div>
           <h2 className="text-3xl font-bold tracking-tight">Financial Intelligence</h2>
           <p className="text-muted-foreground">Monitor cashflow, AR/AP, and profitability.</p>
        </div>
        <div className="flex gap-2">
           <Button variant="outline">
              <FileDown className="mr-2 h-4 w-4" />
              Export P&L
           </Button>
           <Button>
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
