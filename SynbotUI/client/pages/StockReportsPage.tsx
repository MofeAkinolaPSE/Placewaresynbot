/** Stock reports on a page of their own (from Inventory & Quality -> Stock or ACE Books -> Stock). */
import { BarChart3 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/workspace/PageHeader";
import { StockReports } from "@/components/books/inventory-reports";
import { DrillProvider } from "@/components/books/lineage";

export default function StockReportsPage() {
  return (
    <DrillProvider>
      <div className="flex flex-col gap-5">
        <PageHeader icon={BarChart3} title="Stock reports" subtitle="Inventory unit activity and item costing - Sage history and ACE Books together; click a sale to open its invoice" />
        <Card><CardContent className="pt-6"><StockReports /></CardContent></Card>
      </div>
    </DrillProvider>
  );
}
