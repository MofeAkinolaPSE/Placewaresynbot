/**
 * Stock orders on ACE Books: the reorder plan, the order pipeline
 * (requested -> approved -> with supplier -> received on the supplier bill) and
 * every supplier invoice. Used by Operations › Stock Orders & Purchases and the
 * Project Controls "Stock Orders" tab. Figures come from /procurement/*, which
 * reads ACE Books (stock, dated sales, supplier bills) - never the retired Sage
 * "purchase order" snapshot, which was really the supplier-invoice history.
 */
import { ReactNode, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowUpRight, Loader2, PackagePlus, ShoppingCart, Truck, Wallet } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { api } from "@/lib/api-client";
import { Dict, fmtDate, naira, num } from "@/lib/books-api";
import { DrillLink, SupplierPick } from "@/components/books/kit";
import { Facts, RecordView } from "@/components/books/lineage";
import { useAuth } from "@/components/AuthProvider";

export const PLAN_STATUS: Record<string, { label: string; cls: string }> = {
  out_of_stock: { label: "Out of stock", cls: "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300" },
  reorder_now: { label: "Reorder now", cls: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300" },
  reorder_soon: { label: "Order soon", cls: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300" },
  healthy: { label: "Healthy", cls: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300" },
  no_recent_sales: { label: "No recent sales", cls: "bg-muted text-muted-foreground" },
};

export const ORDER_STATUS: Record<string, { label: string; cls: string }> = {
  recommended: { label: "Requested", cls: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300" },
  approved: { label: "Approved", cls: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300" },
  ordered: { label: "With supplier", cls: "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300" },
  received: { label: "Received", cls: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300" },
  cancelled: { label: "Cancelled", cls: "bg-muted text-muted-foreground" },
};

export function Chip({ map, value }: { map: Record<string, { label: string; cls: string }>; value: string }) {
  const m = map[value] ?? { label: value, cls: "bg-muted text-muted-foreground" };
  return <span className={`inline-flex whitespace-nowrap rounded-md px-1.5 py-0.5 text-[11px] font-medium ${m.cls}`}>{m.label}</span>;
}

const PROCUREMENT_ROLES = ["admin", "ops", "operations", "finance", "procurement", "management"];
export function useCanOrder() {
  const { roles } = useAuth();
  return roles.some((r) => PROCUREMENT_ROLES.includes(r));
}

export function useStockOrderData() {
  const qc = useQueryClient();
  const summary = useQuery({ queryKey: ["stock-orders-summary"], queryFn: () => api.procurement.stockOrdersSummary() });
  const refresh = () => {
    ["stock-orders-summary", "reorder-plan", "stock-orders", "purchase-orders-summary"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  };
  return { summary, refresh };
}

// ---------------------------------------------------------------------------
// Summary strip
// ---------------------------------------------------------------------------

export function StockOrderKpis({ s, onPick }: { s: Dict | undefined; onPick?: (tab: string, filter?: string) => void }) {
  const inProgress = (s?.requested ?? 0) + (s?.approved ?? 0) + (s?.ordered ?? 0);
  return (
    <KpiStrip
      items={[
        {
          label: "Items to order now", value: s ? s.to_order_count : "—", icon: AlertTriangle,
          tone: (s?.to_order_count ?? 0) > 0 ? "danger" : "success",
          sub: s ? `${s.out_of_stock} out of stock · ≈ ${naira(s.to_order_value)} at last cost` : undefined,
          onClick: onPick && (() => onPick("plan", "needs")),
        },
        {
          label: "Stock orders in progress", value: s ? inProgress : "—", icon: Truck,
          tone: (s?.overdue_orders ?? 0) > 0 ? "warning" : "default",
          sub: s ? `${s.requested} requested · ${s.approved} approved · ${s.ordered} with suppliers${s.overdue_orders ? ` (${s.overdue_orders} late)` : ""}` : undefined,
          onClick: onPick && (() => onPick("orders")),
        },
        {
          label: "We owe suppliers", value: s ? naira(s.open_payables) : "—", icon: Wallet,
          tone: (s?.overdue_payables ?? 0) > 0 ? "warning" : "default",
          sub: s ? `${naira(s.overdue_payables)} past due · ACE Books` : undefined,
          onClick: onPick && (() => onPick("invoices")),
        },
        {
          label: "Bought in the last 12 months", value: s ? naira(s.purchases_12m) : "—", icon: ShoppingCart,
          sub: s?.purchases_as_of ? `to ${fmtDate(s.purchases_as_of)}` : undefined,
          onClick: onPick && (() => onPick("invoices")),
        },
      ]}
    />
  );
}

export function PlanBasis({ s }: { s: Dict | undefined }) {
  if (!s) return null;
  const p = s.policy ?? {};
  return (
    <p className="text-xs text-muted-foreground">
      Plan uses ACE Books stock on hand and dated sales up to {fmtDate(s.as_of)}: average demand over the last {p.demand_days} days,
      {" "}{p.lead_days}-day supplier lead time plus {p.safety_days} days' safety stock; a suggested order covers {p.cover_days} days after it arrives.
    </p>
  );
}

// ---------------------------------------------------------------------------
// Reorder plan
// ---------------------------------------------------------------------------

const PLAN_FILTERS: [string, string][] = [
  ["needs", "Needs ordering"], ["reorder_soon", "Order soon"], ["expiry", "Expiry risk"],
  ["healthy", "Healthy"], ["no_recent_sales", "No recent sales"], ["all", "All"],
];

export function ReorderPlan({ initialFilter = "needs" }: { initialFilter?: string }) {
  const { data, isLoading } = useQuery({ queryKey: ["reorder-plan"], queryFn: () => api.procurement.reorderPlan() });
  const [filter, setFilter] = useState(initialFilter);
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<Dict | null>(null);
  const items: Dict[] = data?.items ?? [];
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: items.length, expiry: 0, needs: 0 };
    items.forEach((i) => {
      c[i.status] = (c[i.status] ?? 0) + 1;
      if (i.expiry_risk) c.expiry += 1;
      if (i.status === "out_of_stock" || i.status === "reorder_now") c.needs += 1;
    });
    return c;
  }, [items]);
  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return items.filter((i) => {
      if (filter === "needs" && !(i.status === "out_of_stock" || i.status === "reorder_now")) return false;
      if (filter === "expiry" && !i.expiry_risk) return false;
      if (!["needs", "expiry", "all"].includes(filter) && i.status !== filter) return false;
      return !q || `${i.family} ${i.sku} ${i.supplier_name ?? ""}`.toLowerCase().includes(q);
    });
  }, [items, filter, search]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {PLAN_FILTERS.map(([k, label]) => (
          <Button key={k} size="sm" variant={filter === k ? "default" : "outline"} className="h-8" onClick={() => setFilter(k)}>
            {label} <span className="ml-1.5 opacity-70">{counts[k] ?? 0}</span>
          </Button>
        ))}
        <Input className="ml-auto h-8 w-56" placeholder="Search item or supplier" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>
      <Card>
        <CardContent className="p-0">
          {isLoading ? <Spinner /> : rows.length === 0 ? (
            <p className="p-8 text-center text-sm text-muted-foreground">Nothing in this view.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Item</TableHead><TableHead>Status</TableHead>
                  <TableHead className="text-right">On hand</TableHead><TableHead className="text-right">Sells / month</TableHead>
                  <TableHead className="text-right">Cover</TableHead><TableHead className="text-right">Suggested</TableHead>
                  <TableHead className="text-right">Est. cost</TableHead><TableHead>Last bought from</TableHead><TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((i) => (
                  <TableRow key={i.family} className="cursor-pointer" onClick={() => setPicked(i)}>
                    <TableCell className="max-w-[260px]">
                      <div className="truncate font-medium">{i.name}</div>
                      <div className="truncate text-[11px] text-muted-foreground">
                        {i.lots_in_stock ? `${i.lots_in_stock} lot${i.lots_in_stock === 1 ? "" : "s"} in stock` : "no stock"}
                        {i.next_expiry ? ` · next expiry ${fmtDate(i.next_expiry)}` : ""}
                        {i.expiry_risk && <span className="ml-1 text-red-600 dark:text-red-400">· {num(i.expiry_risk_units)} won't sell before expiry</span>}
                      </div>
                    </TableCell>
                    <TableCell><Chip map={PLAN_STATUS} value={i.status} /></TableCell>
                    <TableCell className="text-right">{num(i.on_hand)}{i.on_order > 0 && <div className="text-[11px] text-muted-foreground">+{num(i.on_order)} on order</div>}</TableCell>
                    <TableCell className="text-right">{num(i.monthly_demand, 1)}</TableCell>
                    <TableCell className="text-right whitespace-nowrap">{i.days_cover == null ? "—" : `${num(i.days_cover)} d`}</TableCell>
                    <TableCell className="text-right font-medium">{i.suggested_qty ? num(i.suggested_qty) : "—"}</TableCell>
                    <TableCell className="text-right whitespace-nowrap">{i.est_cost ? naira(i.est_cost) : "—"}</TableCell>
                    <TableCell className="max-w-[180px] text-xs">
                      <div className="truncate">{i.supplier_name ?? "—"}</div>
                      {i.last_purchase && <div className="text-[11px] text-muted-foreground">{fmtDate(i.last_purchase)} · {naira(i.unit_cost)}/unit</div>}
                    </TableCell>
                    <TableCell className="text-right">
                      {i.order_status ? <Chip map={ORDER_STATUS} value={i.order_status} /> : null}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <PlanItemSheet item={picked} onClose={() => setPicked(null)} />
    </div>
  );
}

function PlanItemSheet({ item, onClose }: { item: Dict | null; onClose: () => void }) {
  const { refresh } = useStockOrderData();
  const canOrder = useCanOrder();
  const [qty, setQty] = useState("");
  const [cost, setCost] = useState("");
  const [supplier, setSupplier] = useState<Dict | null>(null);
  const [busy, setBusy] = useState(false);
  const [key, setKey] = useState<string | null>(null);
  if (item && key !== item.family) {
    setKey(item.family);
    setQty(String(item.suggested_qty || item.last_qty || ""));
    setCost(item.unit_cost ? String(item.unit_cost) : "");
    setSupplier(item.supplier_id ? { id: item.supplier_id, name: item.supplier_name } : null);
  }
  const raise = async () => {
    setBusy(true);
    try {
      await api.procurement.raiseStockOrder({ sku: item!.sku, qty: Number(qty), supplier_id: supplier?.id ?? null, unit_cost: cost ? Number(cost) : null });
      toast.success(`Stock order raised for ${num(Number(qty))} × ${item!.name}`, { description: "It needs approval before it is placed with the supplier." });
      refresh();
      onClose();
    } catch (e: any) {
      toast.error(e.message ?? "Could not raise the order");
    } finally {
      setBusy(false);
    }
  };
  return (
    <DetailSheet open={!!item} onOpenChange={(o) => { if (!o) { setKey(null); onClose(); } }} title={item?.name ?? ""} icon={PackagePlus}
                 description={item ? `${PLAN_STATUS[item.status]?.label ?? item.status} · ${item.codes} Sage item code${item.codes === 1 ? "" : "s"} (one per lot)` : undefined}>
      {item && (
        <div className="space-y-4 text-sm">
          <Facts items={[
            ["On hand", num(item.on_hand)], ["On order", num(item.on_order)], ["Stock value", naira(item.stock_value)],
            ["Sells per month", num(item.monthly_demand, 1)], ["Days of cover", item.days_cover == null ? "—" : num(item.days_cover)],
            ["Reorder point", num(item.reorder_point)],
            ["Customers (180 d)", num(item.customers)], ["Orders (180 d)", num(item.orders)], ["Last sold", fmtDate(item.last_sold)],
            ["Next lot", item.next_sku ?? "—"], ["Next expiry", item.next_expiry ? fmtDate(item.next_expiry) : "—"],
            ["Last bought", item.last_purchase ? `${fmtDate(item.last_purchase)} · ${num(item.last_qty)} @ ${naira(item.unit_cost)}` : "—"],
          ]} />
          {item.expiry_risk && (
            <p className="rounded-md border border-red-300 bg-red-50 p-2 text-xs text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
              At the current rate of sale about {num(item.expiry_risk_units)} units ({naira(item.expiry_risk_value)} at cost) will not sell before their lot expires.
              Consider a promotion, a return to the supplier or a stock loan.
            </p>
          )}
          {item.lots?.length > 0 && (
            <div>
              <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">Lots in stock (sold first-expiry-first)</div>
              <Table>
                <TableHeader><TableRow><TableHead>Lot / item code</TableHead><TableHead>Batch</TableHead><TableHead>Expiry</TableHead><TableHead className="text-right">Qty</TableHead><TableHead className="text-right">Value</TableHead></TableRow></TableHeader>
                <TableBody>
                  {item.lots.map((l: Dict) => (
                    <TableRow key={l.sku}>
                      <TableCell><DrillLink to={{ type: "product", id: l.sku, label: l.sku }}>{l.sku}</DrillLink></TableCell>
                      <TableCell className="text-xs">{l.batch ?? "—"}</TableCell>
                      <TableCell className="text-xs whitespace-nowrap">{l.expiry ? fmtDate(l.expiry) : "—"}</TableCell>
                      <TableCell className="text-right">{num(l.qty)}</TableCell>
                      <TableCell className="text-right whitespace-nowrap">{naira(l.value)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
          {item.order_id ? (
            <p className="rounded-md border p-2 text-xs">This item already has a stock order: <Chip map={ORDER_STATUS} value={item.order_status} />. Manage it on the Stock orders tab.</p>
          ) : canOrder ? (
            <div className="space-y-3 rounded-md border p-3">
              <div className="text-xs font-semibold uppercase text-muted-foreground">Raise a stock order for {item.sku}</div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1"><Label className="text-xs">Quantity</Label><Input type="number" value={qty} onChange={(e) => setQty(e.target.value)} /></div>
                <div className="space-y-1"><Label className="text-xs">Unit cost (last paid)</Label><Input type="number" value={cost} onChange={(e) => setCost(e.target.value)} /></div>
              </div>
              <SupplierPick label="Supplier" value={supplier} onChange={setSupplier} />
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>Estimated cost {naira(Number(qty || 0) * Number(cost || 0))}</span>
                <Button size="sm" disabled={busy || !(Number(qty) > 0)} onClick={raise}>
                  {busy && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}Raise order
                </Button>
              </div>
            </div>
          ) : null}
          <div className="border-t pt-3">
            <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">Stock record · {item.next_sku ?? item.last_sku ?? item.sku} (ACE Books)</div>
            <RecordView t={{ type: "product", id: item.next_sku ?? item.last_sku ?? item.sku }} />
          </div>
        </div>
      )}
    </DetailSheet>
  );
}

// ---------------------------------------------------------------------------
// Stock orders
// ---------------------------------------------------------------------------

const ORDER_FILTERS: [string, string][] = [["open", "In progress"], ["recommended", "Requested"], ["approved", "Approved"], ["ordered", "With supplier"], ["received", "Received"], ["cancelled", "Cancelled"]];

export function StockOrdersList({ compact = false }: { compact?: boolean }) {
  const [filter, setFilter] = useState("open");
  const { data = [], isLoading } = useQuery({
    queryKey: ["stock-orders", filter],
    queryFn: () => api.procurement.stockOrders(filter === "open" ? undefined : filter),
  });
  const rows = filter === "open" ? data.filter((o: Dict) => ["recommended", "approved", "ordered"].includes(o.status)) : data;
  const [picked, setPicked] = useState<Dict | null>(null);
  return (
    <div className="space-y-3">
      {!compact && (
        <div className="flex flex-wrap gap-2">
          {ORDER_FILTERS.map(([k, label]) => (
            <Button key={k} size="sm" variant={filter === k ? "default" : "outline"} className="h-8" onClick={() => setFilter(k)}>{label}</Button>
          ))}
        </div>
      )}
      <Card>
        <CardContent className="p-0">
          {isLoading ? <Spinner /> : rows.length === 0 ? (
            <p className="p-8 text-center text-sm text-muted-foreground">
              {filter === "open" ? "No stock orders in progress. Raise one from the reorder plan." : "No stock orders here."}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Item</TableHead><TableHead className="text-right">Qty</TableHead><TableHead>Status</TableHead>
                  <TableHead>Supplier</TableHead><TableHead className="text-right">Est. value</TableHead>
                  <TableHead>Raised</TableHead>{!compact && <TableHead>Approved</TableHead>}<TableHead>Expected / received</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((o: Dict) => (
                  <TableRow key={o.id} className="cursor-pointer" onClick={() => setPicked(o)}>
                    <TableCell className="max-w-[220px]"><div className="truncate font-medium">{o.name}</div><div className="truncate text-[11px] text-muted-foreground">{o.sku}</div></TableCell>
                    <TableCell className="text-right">{num(o.requested_qty)}</TableCell>
                    <TableCell><Chip map={ORDER_STATUS} value={o.status} />{o.overdue && <div className="text-[11px] text-red-600">late</div>}</TableCell>
                    <TableCell className="max-w-[160px] truncate text-xs">{o.supplier_name ?? "—"}{o.po_reference && <div className="text-[11px] text-muted-foreground">ref {o.po_reference}</div>}</TableCell>
                    <TableCell className="text-right whitespace-nowrap">{o.est_value ? naira(o.est_value) : "—"}</TableCell>
                    <TableCell className="text-xs whitespace-nowrap">{o.created_by_name ?? "—"}<div className="text-[11px] text-muted-foreground">{fmtDate(o.created_at)}</div></TableCell>
                    {!compact && <TableCell className="text-xs whitespace-nowrap">{o.approved_by_name ?? "—"}{o.approved_at && <div className="text-[11px] text-muted-foreground">{fmtDate(o.approved_at)}</div>}</TableCell>}
                    <TableCell className="text-xs whitespace-nowrap">
                      {o.status === "received" ? <>{fmtDate(o.received_at)}{o.bill_number && <div className="text-[11px] text-muted-foreground">bill {o.bill_number}</div>}</> : o.expected_date ? fmtDate(o.expected_date) : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <OrderSheet order={picked} onClose={() => setPicked(null)} />
    </div>
  );
}

function OrderSheet({ order, onClose }: { order: Dict | null; onClose: () => void }) {
  const { refresh } = useStockOrderData();
  const canOrder = useCanOrder();
  const { roles } = useAuth();
  const canPostBills = roles.some((r) => ["admin", "finance"].includes(r));
  const [busy, setBusy] = useState<string | null>(null);
  const [f, setF] = useState<Dict>({});
  const [key, setKey] = useState<string | null>(null);
  if (order && key !== order.id) {
    setKey(order.id);
    setF({ qty: String(order.requested_qty ?? ""), unit_cost: order.unit_cost ? String(order.unit_cost) : "", po_reference: order.po_reference ?? "",
           expected_date: order.expected_date ?? "", supplier: order.supplier_id ? { id: order.supplier_id, name: order.supplier_name } : null, reason: "" });
  }
  const run = async (action: "approve" | "order" | "cancel") => {
    setBusy(action);
    try {
      await api.procurement.stockOrderAction(order!.id, action, {
        qty: f.qty ? Number(f.qty) : undefined,
        unit_cost: f.unit_cost ? Number(f.unit_cost) : undefined,
        supplier_id: f.supplier?.id, po_reference: f.po_reference || undefined, expected_date: f.expected_date || undefined,
        reason: f.reason || undefined,
      });
      toast.success(action === "approve" ? "Stock order approved" : action === "order" ? "Marked as placed with the supplier" : "Stock order cancelled");
      refresh();
      onClose();
    } catch (e: any) {
      toast.error(e.message ?? "Action failed");
    } finally {
      setBusy(null);
    }
  };
  const st = order?.status;
  const open = st === "recommended" || st === "approved" || st === "ordered";
  return (
    <DetailSheet open={!!order} onOpenChange={(o) => { if (!o) { setKey(null); onClose(); } }} title={order ? `Stock order · ${order.name}` : ""} icon={Truck}
                 description={order ? `${order.sku} · ${ORDER_STATUS[order.status]?.label ?? order.status}` : undefined}>
      {order && (
        <div className="space-y-4 text-sm">
          <Facts items={[
            ["Item", <DrillLink to={{ type: "product", id: order.sku, label: order.sku }}>{order.sku}</DrillLink>],
            ["Quantity", num(order.requested_qty)], ["Unit cost", order.unit_cost ? naira(order.unit_cost) : "—"],
            ["Supplier", order.supplier_id ? <DrillLink to={{ type: "supplier", id: order.supplier_id, label: order.supplier_name }}>{order.supplier_name}</DrillLink> : "—"],
            ["Supplier ref", order.po_reference ?? "—"], ["Expected", order.expected_date ? fmtDate(order.expected_date) : "—"],
            ["Raised by", `${order.created_by_name ?? "—"} · ${fmtDate(order.created_at)}`],
            ["Approved by", order.approved_by_name ? `${order.approved_by_name} · ${fmtDate(order.approved_at)}` : "—"],
            ["Placed", order.ordered_at ? fmtDate(order.ordered_at) : "—"],
            ["Received", order.received_at ? `${fmtDate(order.received_at)}${order.received_qty ? ` · ${num(order.received_qty)} units` : ""}` : "—"],
            ["Supplier bill", order.bill_id ? <DrillLink to={{ type: "bill", id: order.bill_id, label: order.bill_number }}>{order.bill_number}</DrillLink> : "—"],
          ]} />
          {order.notes && <p className="rounded bg-muted/40 p-2 text-xs">{order.notes}</p>}
          {st === "ordered" && (
            <div className="rounded-md border border-indigo-200 bg-indigo-50/60 p-3 text-xs dark:border-indigo-500/30 dark:bg-indigo-500/10">
              Waiting for delivery. When the goods arrive, Finance records the supplier's invoice in ACE Books (or Inventory › Receive stock); that adds the
              stock with its batch and expiry and closes this order automatically.
              {canPostBills && <Link to="/finance/books/purchases" className="ml-1 inline-flex items-center text-primary hover:underline">Record the supplier bill <ArrowUpRight className="h-3 w-3" /></Link>}
            </div>
          )}
          {open && canOrder && (
            <div className="space-y-3 rounded-md border p-3">
              {(st === "recommended" || st === "approved") && (
                <>
                  <div className="text-xs font-semibold uppercase text-muted-foreground">{st === "recommended" ? "Approve or place the order" : "Place the order with the supplier"}</div>
                  <div className="grid grid-cols-2 gap-3">
                    <Field label="Quantity"><Input type="number" value={f.qty} onChange={(e) => setF({ ...f, qty: e.target.value })} /></Field>
                    <Field label="Unit cost"><Input type="number" value={f.unit_cost} onChange={(e) => setF({ ...f, unit_cost: e.target.value })} /></Field>
                    <Field label="Supplier's order / proforma ref"><Input value={f.po_reference} onChange={(e) => setF({ ...f, po_reference: e.target.value })} /></Field>
                    <Field label="Expected delivery"><Input type="date" value={f.expected_date} onChange={(e) => setF({ ...f, expected_date: e.target.value })} /></Field>
                  </div>
                  <SupplierPick label="Supplier" value={f.supplier} onChange={(v) => setF({ ...f, supplier: v })} />
                  <div className="flex flex-wrap justify-end gap-2">
                    {st === "recommended" && <Button size="sm" variant="outline" disabled={!!busy} onClick={() => run("approve")}>{busy === "approve" && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}Approve</Button>}
                    <Button size="sm" disabled={!!busy || !f.supplier} onClick={() => run("order")}>{busy === "order" && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}Mark as ordered</Button>
                  </div>
                </>
              )}
              <div className="flex items-end gap-2 border-t pt-3">
                <Field label="Cancel reason" className="flex-1"><Input value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} placeholder="Optional" /></Field>
                <Button size="sm" variant="destructive" disabled={!!busy} onClick={() => run("cancel")}>Cancel order</Button>
              </div>
            </div>
          )}
        </div>
      )}
    </DetailSheet>
  );
}

// ---------------------------------------------------------------------------
// Supplier invoices
// ---------------------------------------------------------------------------

export function SupplierInvoices({ supplierId }: { supplierId?: string }) {
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(100);
  const { data, isLoading } = useQuery({
    queryKey: ["supplier-purchases", search, supplierId, limit],
    queryFn: () => api.procurement.purchases({ search, supplier_id: supplierId, limit }),
  });
  const rows = data?.rows ?? [];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Input className="h-8 w-72" placeholder="Search invoice number or supplier" value={search} onChange={(e) => { setSearch(e.target.value); setLimit(100); }} />
        {data && <span className="text-xs text-muted-foreground">{num(data.total)} invoices · {naira(data.amount)}</span>}
      </div>
      <Card>
        <CardContent className="p-0">
          {isLoading ? <Spinner /> : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead><TableHead>Supplier invoice</TableHead><TableHead>Supplier</TableHead>
                  <TableHead className="text-right">Lines</TableHead><TableHead className="text-right">Amount</TableHead>
                  <TableHead className="text-right">Still owed</TableHead><TableHead>Record</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r: Dict) => {
                  const to = r.doc_id ? { type: "bill" as const, id: r.doc_id, label: r.number } : { type: "sagebill" as const, id: `${r.number}|${r.supplier_id ?? ""}`, label: r.number };
                  return (
                    <TableRow key={`${r.source}-${r.number}-${r.supplier_id}`}>
                      <TableCell className="whitespace-nowrap text-xs">{fmtDate(r.bill_date)}</TableCell>
                      <TableCell><DrillLink to={to}>{r.supplier_ref ?? r.number}</DrillLink>{r.doc_id && r.number !== r.supplier_ref && <div className="text-[11px] text-muted-foreground">{r.number}</div>}</TableCell>
                      <TableCell className="max-w-[220px] truncate text-xs">{r.supplier_id ? <DrillLink to={{ type: "supplier", id: r.supplier_id, label: r.supplier_name }}>{r.supplier_name}</DrillLink> : r.supplier_name ?? "—"}</TableCell>
                      <TableCell className="text-right text-xs">{r.lines ? num(r.lines) : "—"}{r.qty ? <div className="text-[11px] text-muted-foreground">{num(r.qty)} units</div> : null}</TableCell>
                      <TableCell className="text-right whitespace-nowrap">{naira(r.amount)}</TableCell>
                      <TableCell className="text-right whitespace-nowrap">{Number(r.balance) ? naira(r.balance) : "—"}</TableCell>
                      <TableCell>
                        {r.source === "Sage" ? <Badge variant="outline" className="text-[10px]">Paid in Sage</Badge>
                          : <Badge variant={Number(r.balance) > 0 ? "default" : "secondary"} className="text-[10px]">{r.is_opening ? "Opening bill" : "ACE Books"}{Number(r.balance) > 0 ? " · open" : " · paid"}</Badge>}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      {data && rows.length < data.total && (
        <div className="flex justify-center"><Button size="sm" variant="outline" onClick={() => setLimit(limit + 100)}>Show more ({num(data.total - rows.length)} left)</Button></div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

function Field({ label, children, className = "" }: { label: string; children: ReactNode; className?: string }) {
  return <div className={`space-y-1 ${className}`}><Label className="text-xs">{label}</Label>{children}</div>;
}

function Spinner() {
  return <div className="flex justify-center py-10"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>;
}
