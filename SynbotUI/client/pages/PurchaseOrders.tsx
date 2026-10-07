/**
 * Operations › Stock Orders & Purchases.
 *
 * Replaces the old "Purchase Orders" page, which listed Sage's vendor-invoice
 * history as if it were 1,180 purchase orders (72 "open" = invoices from the
 * last 180 days). Everything here reads ACE Books: what needs ordering, the
 * stock orders in progress (received automatically when the supplier bill is
 * posted), and every supplier invoice with click-through to its lines.
 */
import { useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { ShoppingCart } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/components/workspace/PageHeader";
import { motionTransitions } from "@/lib/motion";
import { DrillProvider } from "@/components/books/lineage";
import { PlanBasis, ReorderPlan, StockOrderKpis, StockOrdersList, SupplierInvoices, useStockOrderData } from "@/components/operations/stock-orders";

export default function PurchaseOrders() {
  return (
    <DrillProvider>
      <StockOrdersPage />
    </DrillProvider>
  );
}

function StockOrdersPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "plan";
  const filter = params.get("filter") ?? "needs";
  const { summary } = useStockOrderData();
  const s = summary.data;
  const pick = (t: string, f?: string) => setParams(f ? { tab: t, filter: f } : { tab: t }, { replace: true });

  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={motionTransitions.standard} className="space-y-5">
      <PageHeader icon={ShoppingCart} title="Stock Orders & Purchases" subtitle="What to reorder · orders with suppliers · supplier invoices (ACE Books)" />
      <StockOrderKpis s={s} onPick={pick} />
      <PlanBasis s={s} />
      <Tabs value={tab} onValueChange={(t) => pick(t)}>
        <TabsList>
          <TabsTrigger value="plan">Reorder plan{s ? ` (${s.to_order_count})` : ""}</TabsTrigger>
          <TabsTrigger value="orders">Stock orders{s ? ` (${(s.requested ?? 0) + (s.approved ?? 0) + (s.ordered ?? 0)})` : ""}</TabsTrigger>
          <TabsTrigger value="invoices">Supplier invoices</TabsTrigger>
        </TabsList>
        <TabsContent value="plan" className="mt-4"><ReorderPlan key={filter} initialFilter={filter} /></TabsContent>
        <TabsContent value="orders" className="mt-4"><StockOrdersList /></TabsContent>
        <TabsContent value="invoices" className="mt-4"><SupplierInvoices /></TabsContent>
      </Tabs>
    </motion.div>
  );
}
