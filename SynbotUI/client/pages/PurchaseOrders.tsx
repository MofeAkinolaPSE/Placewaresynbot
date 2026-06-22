import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";
import { ShoppingCart, Search } from "lucide-react";

const STATUS_COLOR: Record<string, string> = {
  open: "bg-blue-100 text-blue-700",
  pending: "bg-yellow-100 text-yellow-700",
  approved: "bg-green-100 text-green-700",
  received: "bg-emerald-100 text-emerald-700",
  closed: "bg-muted text-muted-foreground",
  cancelled: "bg-destructive/15 text-destructive",
};

const PurchaseOrders = () => {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");

  const { data: ordersRaw, isLoading } = useQuery({
    queryKey: ["purchase-orders"],
    queryFn: () => api.procurement.purchaseOrders({ limit: 200 }),
  });

  const { data: summary } = useQuery({
    queryKey: ["purchase-orders-summary"],
    queryFn: () => api.procurement.purchaseOrdersSummary(),
  });

  const orders: any[] = Array.isArray(ordersRaw) ? ordersRaw : [];

  const filtered = orders.filter((o) => {
    if (statusFilter !== "all" && o.status !== statusFilter) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        String(o.po_number ?? "").toLowerCase().includes(q) ||
        String(o.vendor_name ?? o.vendor_id ?? "").toLowerCase().includes(q)
      );
    }
    return true;
  });

  const statuses = ["all", ...Array.from(new Set(orders.map((o) => o.status).filter(Boolean)))];

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionTransitions.standard}
      className="flex flex-col gap-5"
    >
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Purchase Orders</h1>
          <p className="text-sm text-muted-foreground">Sage 50 procurement pipeline</p>
        </div>
      </div>

      {/* Summary KPIs */}
      {summary && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {[
            { label: "Total POs", value: summary.total_pos ?? "—" },
            { label: "Open POs", value: summary.open_pos ?? "—" },
            { label: "Total Value", value: summary.total_value != null ? `₦${Number(summary.total_value).toLocaleString()}` : "—" },
            { label: "Open Value", value: summary.open_value != null ? `₦${Number(summary.open_value).toLocaleString()}` : "—" },
          ].map(({ label, value }) => (
            <Card key={label}>
              <CardHeader className="pb-1 pt-4">
                <CardDescription className="text-xs font-medium uppercase tracking-wide">{label}</CardDescription>
              </CardHeader>
              <CardContent className="pb-4">
                <div className="text-2xl font-bold tabular-nums">{value}</div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search PO number or vendor…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <div className="flex gap-1 flex-wrap">
          {statuses.map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`px-3 py-1 rounded text-xs font-medium border transition-colors ${
                statusFilter === s
                  ? "bg-primary text-primary-foreground border-primary"
                  : "bg-muted text-muted-foreground border-transparent hover:border-muted-foreground/30"
              }`}
            >
              {s === "all" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <Card>
        <CardHeader className="mb-2">
          <CardTitle className="text-lg font-semibold flex items-center gap-2">
            <ShoppingCart className="h-5 w-5" />
            Purchase Orders
          </CardTitle>
          <CardDescription>{filtered.length} records</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="min-w-[120px]">PO Number</TableHead>
                  <TableHead className="min-w-[180px]">Vendor</TableHead>
                  <TableHead className="min-w-[110px]">Order Date</TableHead>
                  <TableHead className="min-w-[130px]">Expected Delivery</TableHead>
                  <TableHead className="min-w-[120px] text-right">Net Amount</TableHead>
                  <TableHead className="min-w-[100px]">Status</TableHead>
                  <TableHead className="min-w-[120px]">Created By</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading ? (
                  <TableRow>
                    <TableCell colSpan={7} className="text-center text-muted-foreground py-8">
                      Loading…
                    </TableCell>
                  </TableRow>
                ) : filtered.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7} className="text-center text-muted-foreground py-8">
                      {orders.length === 0 ? "No purchase orders found. Import Sage data to populate." : "No orders match your filter."}
                    </TableCell>
                  </TableRow>
                ) : (
                  filtered.map((o, i) => (
                    <TableRow key={o.po_id ?? i}>
                      <TableCell className="font-mono text-xs">{o.po_number || "—"}</TableCell>
                      <TableCell className="text-sm">{o.vendor_name || o.vendor_id || "—"}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {o.order_date ? new Date(o.order_date).toLocaleDateString() : "—"}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {o.expected_delivery_date ? new Date(o.expected_delivery_date).toLocaleDateString() : "—"}
                      </TableCell>
                      <TableCell className="text-right font-mono text-sm">
                        {o.net_amount != null ? `₦${Number(o.net_amount).toLocaleString()}` : "—"}
                      </TableCell>
                      <TableCell>
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLOR[o.status] ?? "bg-muted text-muted-foreground"}`}>
                          {o.status || "—"}
                        </span>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">{o.created_by || "—"}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
};

export default PurchaseOrders;
