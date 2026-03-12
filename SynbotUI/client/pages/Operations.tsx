import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { InventoryDashboard } from "@/components/dashboards/InventoryDashboard";
import { LogisticsDashboard } from "@/components/dashboards/LogisticsDashboard";
import { OperationsSettings } from "@/components/dashboards/OperationsSettings";
import { ProcurementImportDashboard } from "@/components/dashboards/ProcurementImportDashboard";
import { Button } from "@/components/ui/button";
import { PlusCircle, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
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
import { useQueryClient } from "@tanstack/react-query";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";

export default function Operations() {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [formData, setFormData] = useState({
    item_id: "",
    change: 0,
    movement_type: "RESTOCK",
    source: "",
    destination: "",
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

  const handleSubmit = async () => {
    if (!formData.item_id.trim() || formData.change === 0) {
      toast({ title: "Validation Error", description: "Item ID and Change are required", variant: "destructive" });
      return;
    }
    try {
      setSubmitting(true);
      await api.inventory.recordMovement({
        item_id: formData.item_id,
        change: formData.change,
        movement_type: formData.movement_type,
        source: formData.source || undefined,
        destination: formData.destination || undefined,
      });
      toast({ title: "Movement Recorded", description: `${formData.movement_type} for ${formData.item_id} recorded.` });
      setDialogOpen(false);
      setFormData({ item_id: "", change: 0, movement_type: "RESTOCK", source: "", destination: "" });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["inventory-dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["ops-kpis"] }),
        queryClient.invalidateQueries({ queryKey: ["ops-forecast-stock-turnover"] }),
      ]);
    } catch (err: any) {
      toast({ title: "Failed to Record Movement", description: err.message, variant: "destructive" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionTransitions.standard}
      className="pw-page-surface space-y-8 p-8"
    >
      <div className="flex items-center justify-between">
         <div>
          <h2 className="text-3xl font-bold tracking-tight">Operations</h2>
          <p className="text-muted-foreground">Manage inventory and stock movements.</p>
        </div>
        <div className="flex gap-2">
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button>
                <PlusCircle className="mr-2 h-4 w-4" />
                Record Movement
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Record Inventory Movement</DialogTitle>
                <DialogDescription>Log a stock movement event (restock, sale, damage, etc.)</DialogDescription>
              </DialogHeader>
              <div className="grid gap-4 py-4">
                <div className="grid grid-cols-4 items-center gap-4">
                  <Label htmlFor="item_id" className="text-right">Item/SKU</Label>
                  <Input
                    id="item_id"
                    className="col-span-3"
                    value={formData.item_id}
                    onChange={(e) => setFormData({ ...formData, item_id: e.target.value })}
                    placeholder="e.g. VAC-001"
                  />
                </div>
                <div className="grid grid-cols-4 items-center gap-4">
                  <Label htmlFor="movement_type" className="text-right">Type</Label>
                  <Select
                    value={formData.movement_type}
                    onValueChange={(val) => setFormData({ ...formData, movement_type: val })}
                  >
                    <SelectTrigger className="col-span-3">
                      <SelectValue placeholder="Select type" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="RESTOCK">Restock</SelectItem>
                      <SelectItem value="SALE">Sale</SelectItem>
                      <SelectItem value="DAMAGE">Damage</SelectItem>
                      <SelectItem value="EXPIRY">Expiry</SelectItem>
                      <SelectItem value="ADJUSTMENT">Adjustment</SelectItem>
                      <SelectItem value="TRANSFER">Transfer</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid grid-cols-4 items-center gap-4">
                  <Label htmlFor="change" className="text-right">Qty Change</Label>
                  <Input
                    id="change"
                    type="number"
                    className="col-span-3"
                    value={formData.change}
                    onChange={(e) => setFormData({ ...formData, change: parseFloat(e.target.value) || 0 })}
                    placeholder="+100 or -50"
                  />
                </div>
                <div className="grid grid-cols-4 items-center gap-4">
                  <Label htmlFor="source" className="text-right">Source</Label>
                  <Input
                    id="source"
                    className="col-span-3"
                    value={formData.source}
                    onChange={(e) => setFormData({ ...formData, source: e.target.value })}
                    placeholder="Optional (e.g., Warehouse A)"
                  />
                </div>
                <div className="grid grid-cols-4 items-center gap-4">
                  <Label htmlFor="destination" className="text-right">Destination</Label>
                  <Input
                    id="destination"
                    className="col-span-3"
                    value={formData.destination}
                    onChange={(e) => setFormData({ ...formData, destination: e.target.value })}
                    placeholder="Optional (e.g., Clinic B)"
                  />
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
                <Button onClick={handleSubmit} disabled={submitting}>
                  {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Record
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
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
    </motion.div>
  );
}
