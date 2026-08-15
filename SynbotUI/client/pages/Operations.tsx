import { useState } from "react";
import { Link } from "react-router-dom";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent } from "@/components/ui/card";
import { LogisticsDashboard } from "@/components/dashboards/LogisticsDashboard";
import { OperationsSettings } from "@/components/dashboards/OperationsSettings";
import { ProcurementImportDashboard } from "@/components/dashboards/ProcurementImportDashboard";
import { Button } from "@/components/ui/button";
import { Boxes, PlusCircle, Loader2, Package, ArrowRight, AlertCircle } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api-client";
import { useToast } from "@/hooks/use-toast";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";
import { PageHeader } from "@/components/workspace/PageHeader";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { EntityAutocomplete } from "@/components/workspace/EntityAutocomplete";

function InventoryTabSummary() {
  const { data } = useQuery({ queryKey: ["dashboard-inventory"], queryFn: () => api.dashboard.inventory() });
  const summary = data?.summary;
  return (
    <div className="flex flex-col gap-4">
      <KpiStrip
        items={[
          { label: "Total Active SKUs", value: summary?.total_active_skus ?? "—", icon: Package },
          { label: "Low Stock Alerts", value: summary?.low_stock_count ?? "—", icon: AlertCircle, tone: (summary?.low_stock_count ?? 0) > 0 ? "warning" : "default" },
          { label: "Out of Stock", value: summary?.out_of_stock_count ?? "—", icon: AlertCircle, tone: (summary?.out_of_stock_count ?? 0) > 0 ? "danger" : "default" },
        ]}
      />
      <Card>
        <CardContent className="flex items-center justify-between p-4">
          <p className="text-sm text-muted-foreground">
            Grouped stock cards, batch-level detail, reorder requests, and top-selling vaccines now live in the full Inventory Workspace.
          </p>
          <Button asChild size="sm">
            <Link to="/inventory">
              View Full Inventory Workspace <ArrowRight className="ml-2 h-4 w-4" />
            </Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

type InventorySearchResult = { id?: number; sku?: string; name: string };

export default function Operations() {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [formData, setFormData] = useState({
    sku: "",
    item_name: "",
    quantity_change: 0,
    event_type: "ADJUSTMENT",
    reference: "",
  });
  const { toast } = useToast();

  useRealtimeChannel("inventory_updates", () => {
    void queryClient.invalidateQueries({ queryKey: ["inventory-dashboard"] });
    void queryClient.invalidateQueries({ queryKey: ["ops-kpis"] });
    void queryClient.invalidateQueries({ queryKey: ["ops-forecast-stock-turnover"] });
    void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  });
  useRealtimeChannel("workflow_updates", () => {
    void queryClient.invalidateQueries({ queryKey: ["ops-kpis"] });
    void queryClient.invalidateQueries({ queryKey: ["ops-forecast-stock-turnover"] });
  });
  useRealtimeChannel("logistics_updates", () => {
    void queryClient.invalidateQueries({ queryKey: ["inventory-dashboard"] });
    void queryClient.invalidateQueries({ queryKey: ["ops-kpis"] });
    void queryClient.invalidateQueries({ queryKey: ["ops-forecast-stock-turnover"] });
  });

  const resetForm = () =>
    setFormData({ sku: "", item_name: "", quantity_change: 0, event_type: "ADJUSTMENT", reference: "" });

  const handleSubmit = async () => {
    if (!formData.sku.trim() || formData.quantity_change === 0) {
      toast({ title: "Validation Error", description: "Item and Quantity Change are required", variant: "destructive" });
      return;
    }
    try {
      setSubmitting(true);
      await api.inventory.addStock({
        sku: formData.sku,
        quantity_change: formData.quantity_change,
        event_type: formData.event_type,
        reference: formData.reference || undefined,
      });
      toast({ title: "Adjustment Recorded", description: `${formData.event_type} for ${formData.sku} recorded.` });
      setDialogOpen(false);
      resetForm();
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["inventory-dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["inventory-all-stock"] }),
        queryClient.invalidateQueries({ queryKey: ["ops-kpis"] }),
        queryClient.invalidateQueries({ queryKey: ["ops-forecast-stock-turnover"] }),
      ]);
    } catch (err: any) {
      toast({ title: "Failed to Record Adjustment", description: err.message, variant: "destructive" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionTransitions.standard}
      className="flex flex-col gap-5"
    >
      <PageHeader
        icon={Boxes}
        title="Operations"
        subtitle="Inventory · Logistics · Procurement & Import"
        actions={
          <Button size="sm" variant="outline" onClick={() => setDialogOpen(true)}>
            <PlusCircle className="mr-2 h-4 w-4" />
            Log Adjustment
          </Button>
        }
      />

      <DetailSheet
        open={dialogOpen}
        onOpenChange={(open) => {
          setDialogOpen(open);
          if (!open) resetForm();
        }}
        title="Log Stock Adjustment"
        description="Record a sale, damage write-off, expiry, or manual adjustment. To add incoming stock, use the Add Stock button in the inventory table."
        icon={Boxes}
        footer={
          <>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
            <Button onClick={handleSubmit} disabled={submitting}>
              {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Record
            </Button>
          </>
        }
      >
        <div className="space-y-2">
          <Label htmlFor="sku">Item/SKU</Label>
          <EntityAutocomplete<InventorySearchResult>
            fetchFn={(q) => api.inventory.search(q)}
            getKey={(p) => p.sku ?? p.id ?? p.name}
            getLabel={(p) => p.name}
            getSubtitle={(p) => p.sku}
            placeholder="Search inventory..."
            onSelect={(p) => setFormData({ ...formData, sku: p.sku || p.name, item_name: p.name })}
          />
          {formData.sku && (
            <p className="text-xs text-muted-foreground">Selected: {formData.item_name || formData.sku} ({formData.sku})</p>
          )}
        </div>
        <div className="space-y-2">
          <Label htmlFor="event_type">Type</Label>
          <Select value={formData.event_type} onValueChange={(val) => setFormData({ ...formData, event_type: val })}>
            <SelectTrigger id="event_type">
              <SelectValue placeholder="Select type" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="SALE">Sale</SelectItem>
              <SelectItem value="RESTOCK">Restock</SelectItem>
              <SelectItem value="DAMAGE">Damage / Write-off</SelectItem>
              <SelectItem value="EXPIRY">Expiry</SelectItem>
              <SelectItem value="ADJUSTMENT">Adjustment</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="quantity_change">Qty Change</Label>
          <Input
            id="quantity_change"
            type="number"
            value={formData.quantity_change}
            onChange={(e) => setFormData({ ...formData, quantity_change: parseFloat(e.target.value) || 0 })}
            placeholder="+100 or -50"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="reference">Reference</Label>
          <Input
            id="reference"
            value={formData.reference}
            onChange={(e) => setFormData({ ...formData, reference: e.target.value })}
            placeholder="Optional — e.g. reason or PO#"
          />
        </div>
      </DetailSheet>

      {/* Tabs */}
      <Tabs defaultValue="inventory">
        <TabsList className="mb-4">
          <TabsTrigger value="inventory">Inventory</TabsTrigger>
          <TabsTrigger value="logistics">Logistics</TabsTrigger>
          <TabsTrigger value="procurement-import">Procurement/Import</TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
        </TabsList>
        <TabsContent value="inventory">
          <InventoryTabSummary />
        </TabsContent>
        <TabsContent value="logistics">
          <LogisticsDashboard />
        </TabsContent>
        <TabsContent value="procurement-import">
          <ProcurementImportDashboard />
        </TabsContent>
        <TabsContent value="settings">
          <OperationsSettings />
        </TabsContent>
      </Tabs>
    </motion.div>
  );
}
