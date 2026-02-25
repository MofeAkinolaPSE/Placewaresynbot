import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { InventoryDashboard } from "@/components/dashboards/InventoryDashboard";
import { LogisticsDashboard } from "@/components/dashboards/LogisticsDashboard";
import { OperationsSettings } from "@/components/dashboards/OperationsSettings";
import { ProcurementImportDashboard } from "@/components/dashboards/ProcurementImportDashboard";
import { Button } from "@/components/ui/button";
import { PlusCircle } from "lucide-react";

export default function Operations() {
  return (
    <div className="p-8 space-y-8">
      <div className="flex items-center justify-between">
         <div>
          <h2 className="text-3xl font-bold tracking-tight">Operations</h2>
          <p className="text-muted-foreground">Manage inventory and stock movements.</p>
        </div>
        <div className="flex gap-2">
           <Button>
             <PlusCircle className="mr-2 h-4 w-4" />
             Record Movement
           </Button>
        </div>
      </div>

      <Tabs defaultValue="inventory" className="space-y-4">
        <TabsList>
          <TabsTrigger value="inventory">Inventory</TabsTrigger>
          <TabsTrigger value="logistics">Logistics</TabsTrigger>
          <TabsTrigger value="procurement-import">Procurement/Import</TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
        </TabsList>
        <TabsContent value="inventory" className="space-y-4">
          <InventoryDashboard />
        </TabsContent>
        <TabsContent value="logistics">
          <LogisticsDashboard />
        </TabsContent>
        <TabsContent value="procurement-import" className="space-y-4">
          <ProcurementImportDashboard />
        </TabsContent>
        <TabsContent value="settings" className="space-y-4">
          <OperationsSettings />
        </TabsContent>
      </Tabs>
    </div>
  );
}
