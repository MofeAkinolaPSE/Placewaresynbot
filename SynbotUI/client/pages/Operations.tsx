import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { AlertCircle, ArrowRight, Boxes, CalendarClock, Loader2, Package, PlusCircle, Wallet } from "lucide-react";
import { toast } from "sonner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { LogisticsDashboard } from "@/components/dashboards/LogisticsDashboard";
import { OperationsSettings } from "@/components/dashboards/OperationsSettings";
import { ProcurementImportDashboard } from "@/components/dashboards/ProcurementImportDashboard";
import { PageHeader } from "@/components/workspace/PageHeader";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { ProductPick } from "@/components/books/kit";
import { api } from "@/lib/api-client";
import { books, Dict, fmtDate, naira, num } from "@/lib/books-api";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { motionTransitions } from "@/lib/motion";

// ACE Books adjustment reasons; the first three reduce stock.
const REASONS: [string, string][] = [
  ["DAMAGE", "Damage / write-off"], ["EXPIRY", "Expired"], ["SHORTAGE", "Shortage (count lower)"],
  ["EXCESS", "Excess (stock found)"], ["COUNT_CORRECTION", "Count correction (+/-)"],
];
const REDUCES = ["DAMAGE", "EXPIRY", "SHORTAGE"];

function InventoryTabSummary() {
  const navigate = useNavigate();
  const { data: ov } = useQuery({ queryKey: ["ops-overview"], queryFn: () => api.ops.overview(12) });
  const { data: so } = useQuery({ queryKey: ["stock-orders-summary"], queryFn: () => api.procurement.stockOrdersSummary() });
  const st = ov?.stock;
  return (
    <div className="flex flex-col gap-4">
      <KpiStrip
        items={[
          { label: "Items in stock", value: st ? num(st.items_in_stock) : "—", icon: Package, sub: st ? `${num(st.units)} units on hand` : undefined, onClick: () => navigate("/inventory") },
          { label: "Stock value at cost", value: st ? naira(st.value) : "—", icon: Wallet, sub: st?.days_of_stock ? `≈ ${num(st.days_of_stock)} days of stock` : undefined },
          { label: "Items to order now", value: so ? so.to_order_count : "—", icon: AlertCircle, tone: (so?.to_order_count ?? 0) > 0 ? "danger" : "success",
            sub: so ? `${so.out_of_stock} out of stock · ${so.reorder_now} below reorder point` : undefined,
            onClick: () => navigate("/operations/purchase-orders?tab=plan&filter=needs") },
          { label: "Expiring within 90 days", value: st ? naira(st.expiring_90d_value) : "—", icon: CalendarClock, tone: (st?.expiring_90d_value ?? 0) > 0 ? "warning" : "success",
            sub: st ? `${num(st.expiring_90d_items)} items · ${so?.expiry_risk_count ?? 0} won't sell in time` : undefined, onClick: () => navigate("/inventory") },
        ]}
      />
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>Stock from ACE Books{ov?.as_of ? ` · sales to ${fmtDate(ov.as_of)}` : ""}.</span>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => navigate("/operations/purchase-orders")}>Stock orders</Button>
          <Button size="sm" onClick={() => navigate("/inventory")}>Inventory workspace <ArrowRight className="ml-1.5 h-4 w-4" /></Button>
        </div>
      </div>
    </div>
  );
}

export default function Operations() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [product, setProduct] = useState<Dict | null>(null);
  const [reason, setReason] = useState("DAMAGE");
  const [qty, setQty] = useState("");
  const [note, setNote] = useState("");

  const refresh = () => {
    ["ops-overview", "stock-orders-summary", "reorder-plan", "ops-kpis", "dashboard-inventory", "inventory-all-stock"].forEach((k) =>
      queryClient.invalidateQueries({ queryKey: [k] }),
    );
  };
  useRealtimeChannel("inventory_updates", refresh);
  useRealtimeChannel("logistics_updates", refresh);

  const reset = () => { setProduct(null); setReason("DAMAGE"); setQty(""); setNote(""); };

  // Stock is held in ACE Books: an adjustment is recorded there and needs a second person to approve it
  // before stock (and its value) changes. Direct stock writes are refused for items the books hold.
  const submit = async () => {
    const n = Number(qty);
    if (!product || !n) return toast.error("Choose an item and a quantity");
    setBusy(true);
    try {
      const adj = await books.post("/inventory/adjustments", {
        adjustment_date: new Date().toISOString().slice(0, 10), reason_code: reason, notes: note || undefined,
        lines: [{ sku: product.sku, quantity: REDUCES.includes(reason) ? -Math.abs(n) : reason === "EXCESS" ? Math.abs(n) : n }],
      });
      toast.success(`${adj.adjustment_number} sent for approval`, { description: `${product.sku}: stock changes once a second person approves it in ACE Books › Stock.` });
      setOpen(false);
      reset();
      refresh();
    } catch (e: any) {
      toast.error(e.message ?? "Could not record the adjustment");
    } finally {
      setBusy(false);
    }
  };

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={motionTransitions.standard} className="flex flex-col gap-5">
      <PageHeader
        icon={Boxes}
        title="Operations"
        subtitle="Inventory · Logistics · Procurement"
        actions={<Button size="sm" variant="outline" onClick={() => setOpen(true)}><PlusCircle className="mr-2 h-4 w-4" />Log adjustment</Button>}
      />

      <DetailSheet
        open={open}
        onOpenChange={(o) => { setOpen(o); if (!o) reset(); }}
        title="Log stock adjustment"
        description="Damage, expiry, shortages and count corrections. Recorded in ACE Books and applied once a second person approves it. To receive a delivery, use Receive stock on the Inventory page."
        icon={Boxes}
        footer={
          <>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={submit} disabled={busy}>{busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Send for approval</Button>
          </>
        }
      >
        <ProductPick label="Item" value={product} onChange={setProduct} />
        <div className="space-y-1">
          <Label className="text-xs">Reason</Label>
          <Select value={reason} onValueChange={setReason}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>{REASONS.map(([k, l]) => <SelectItem key={k} value={k}>{l}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label className="text-xs">{reason === "COUNT_CORRECTION" ? "Quantity (+ to add, - to remove)" : REDUCES.includes(reason) ? "Quantity to remove" : "Quantity to add"}</Label>
          <Input type="number" value={qty} onChange={(e) => setQty(e.target.value)} />
          {product && <p className="text-xs text-muted-foreground">{num(product.on_hand)} on hand{product.next_batch ? ` · next batch ${product.next_batch}` : ""}</p>}
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Note</Label>
          <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="What happened" />
        </div>
      </DetailSheet>

      <Tabs defaultValue="inventory">
        <TabsList className="mb-4">
          <TabsTrigger value="inventory">Inventory</TabsTrigger>
          <TabsTrigger value="logistics">Logistics</TabsTrigger>
          <TabsTrigger value="procurement">Procurement</TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
        </TabsList>
        <TabsContent value="inventory"><InventoryTabSummary /></TabsContent>
        <TabsContent value="logistics"><LogisticsDashboard /></TabsContent>
        <TabsContent value="procurement"><ProcurementImportDashboard /></TabsContent>
        <TabsContent value="settings"><OperationsSettings /></TabsContent>
      </Tabs>
    </motion.div>
  );
}
