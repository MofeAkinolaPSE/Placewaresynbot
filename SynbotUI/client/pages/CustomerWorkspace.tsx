import { useState, useMemo, useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Users, Plus, RefreshCw, Loader2, Trash2, TrendingUp, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api-client";
import { PageHeader } from "@/components/workspace/PageHeader";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { EntityAutocomplete } from "@/components/workspace/EntityAutocomplete";
import { InvoiceActionPanel } from "@/components/workspace/InvoiceActionPanel";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";

// Matches Frontdesk.tsx / ARReceipts.tsx's existing currency-formatting convention.
const fmt = (n: number | null | undefined) =>
  typeof n === "number"
    ? `₦${n.toLocaleString("en-NG", { minimumFractionDigits: 2 })}`
    : "—";

const fmtDate = (iso?: string | null) =>
  iso
    ? new Date(iso).toLocaleString("en-NG", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })
    : "—";

// Local copy of Frontdesk.tsx's STATUS_LABELS palette, scoped to the
// statuses an order can actually be in from this workspace (qc_pending
// onward — "arrived"/"invoiced" don't apply, quick-request skips straight
// to qc_pending). See ACE-Workspace-Standard.md Ch.10.5 on why small
// presentation helpers like this aren't extracted into a shared module yet.
const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  qc_pending:        { label: "Pending QC",        color: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300" },
  qc_failed:         { label: "QC Failed",         color: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300" },
  finance_pending:   { label: "Pending Finance",   color: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300" },
  finance_approved:  { label: "Finance Approved",  color: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300" },
  finance_rejected:  { label: "Finance Rejected",  color: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300" },
  completed:         { label: "Completed",         color: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300" },
  cancelled:         { label: "Cancelled",         color: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400" },
  dispatched:        { label: "Dispatched",        color: "bg-teal-100 text-teal-800 dark:bg-teal-900/40 dark:text-teal-300" },
};

function StatusPill({ status }: { status: string }) {
  const s = STATUS_LABELS[status] ?? { label: status, color: "bg-gray-100 text-gray-600" };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${s.color}`}>
      {s.label}
    </span>
  );
}

type CustomerSearchResult = { id: number; name: string; customer_code?: string; phone?: string };
type OrderRow = { id: string; invoice_number?: string; walk_in_id: string; status: string; total_amount: number; created_at: string };
type ItemRow = {
  product: string; quantity: number; unit_price: number;
  batch_number?: string; manufacture_date?: string; expiry_date?: string;
};
// GET /inventory/search's real return shape (v_inventory) -- product is
// still a free-text field on the request (quick-request has no SKU FK), so
// this only powers autocomplete/autofill, not a hard catalog constraint.
type InventorySuggestion = {
  sku?: string; name: string; category?: string; current_stock?: number; selling_price?: number;
  batch_number?: string; expiry_date?: string;
};

export default function CustomerWorkspace() {
  const { toast } = useToast();
  const qc = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();

  const [selectedCustomer, setSelectedCustomer] = useState<CustomerSearchResult | null>(null);
  // Session-only, no persistence — matches ACE-Workspace-Standard.md Ch.6
  // (TanStack Query cache + local state only, no global state library).
  const [recent, setRecent] = useState<CustomerSearchResult[]>([]);
  const [expandedOrderId, setExpandedOrderId] = useState<string | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  // Lets "Make New Request" pick/change the customer inline instead of
  // forcing staff to close the sheet and use the left-panel search first --
  // that was the only path in before, and it's the only path the ACE
  // Workstation's "Create Invoice" quick action can land on (no customer
  // selected yet at all, since it opens this sheet directly via the URL).
  const [changingCustomer, setChangingCustomer] = useState(false);

  // Cross-link from the ACE Workstation's "Create Invoice" Quick Action
  // (/customers/workspace?action=new-request) — auto-opens this page's
  // existing request form instead of duplicating it. Consumed once, then
  // stripped from the URL so a refresh doesn't keep re-triggering it.
  useEffect(() => {
    if (searchParams.get("action") === "new-request") {
      setSheetOpen(true);
      searchParams.delete("action");
      setSearchParams(searchParams, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const [items, setItems] = useState<ItemRow[]>([{ product: "", quantity: 1, unit_price: 0 }]);
  const [paymentMethod, setPaymentMethod] = useState("cash");
  const [notes, setNotes] = useState("");

  // Invoice Details — Bill To/Ship To, PO, Payment Terms, Shipping Method.
  // Matches the real Placeware paper invoice's fields (see printInvoice()
  // in Frontdesk.tsx, which this same data now feeds).
  const [billingAddress, setBillingAddress] = useState("");
  const [shippingAddress, setShippingAddress] = useState("");
  const [sameAsBilling, setSameAsBilling] = useState(true);
  const [customerPo, setCustomerPo] = useState("");
  const [paymentTerms, setPaymentTerms] = useState("Due on Receipt");
  const [shippingMethod, setShippingMethod] = useState("");

  // Item-row inventory autocomplete -- previously the Product field was a
  // plain free-text Input with zero connection to inventory, so staff had
  // to know exact product names/prices from memory. Debounced per-row
  // search against the same GET /inventory/search WalkInForm already uses,
  // shown as a dropdown under whichever row is focused (only one row can
  // be actively typed in at a time, so a single slot keyed by row index is
  // enough -- no need for per-row state).
  const [itemSuggestions, setItemSuggestions] = useState<{ idx: number; results: InventorySuggestion[] } | null>(null);
  const itemSearchTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isMounted = useRef(true);
  useEffect(() => () => {
    isMounted.current = false;
    if (itemSearchTimeout.current) clearTimeout(itemSearchTimeout.current);
  }, []);

  function handleProductInputChange(idx: number, value: string) {
    setItems((prev) => prev.map((r, i) => (i === idx ? { ...r, product: value } : r)));
    if (itemSearchTimeout.current) clearTimeout(itemSearchTimeout.current);
    const q = value.trim();
    if (q.length < 2) {
      setItemSuggestions(null);
      return;
    }
    itemSearchTimeout.current = setTimeout(async () => {
      try {
        const results = await api.inventory.search(q);
        if (isMounted.current) setItemSuggestions({ idx, results: (Array.isArray(results) ? results : []).slice(0, 8) });
      } catch {
        if (isMounted.current) setItemSuggestions(null);
      }
    }, 300);
  }

  function applyItemSuggestion(idx: number, sug: InventorySuggestion) {
    setItems((prev) => prev.map((r, i) =>
      i === idx ? {
        ...r, product: sug.name, unit_price: sug.selling_price ?? r.unit_price,
        batch_number: sug.batch_number ?? r.batch_number,
        expiry_date: sug.expiry_date ?? r.expiry_date,
      } : r
    ));
    setItemSuggestions(null);
  }

  const { data: today, refetch: refetchToday } = useQuery({
    queryKey: ["fd-daily-report-today"],
    queryFn: () => api.frontdesk.dailyReport(),
    staleTime: 15_000,
  });

  // Computed client-side from the invoices array daily_report already
  // returns, filtered by invoice.status — NOT the endpoint's pre-computed
  // pending_qc/pending_finance fields, which are derived from walk-in
  // status and can undercount (a walk-in can lag its invoice's status on
  // the older wizard path). Matches InvoicesTab's own KPI derivation.
  const todayInvoices: any[] = (today as any)?.invoices ?? [];
  const kpis = useMemo(() => ({
    pendingQc:      todayInvoices.filter((i) => i.status === "qc_pending").length,
    pendingFinance: todayInvoices.filter((i) => i.status === "finance_pending").length,
    dispatched:     todayInvoices.filter((i) => i.status === "dispatched").length,
    total:          todayInvoices.length,
  }), [todayInvoices]);

  const { data: context, isLoading: contextLoading, refetch: refetchContext } = useQuery({
    queryKey: ["customer-360", selectedCustomer?.id],
    queryFn: () => api.crm.customer360(selectedCustomer!.id),
    enabled: !!selectedCustomer,
  });

  const orders: OrderRow[] = (context as any)?.orders ?? [];

  // Ranked by reorder urgency, from real dated AR ledger history (not
  // per-SKU -- see customer_reorder.py's docstring on why per-SKU timing
  // isn't buildable from this app's current data).
  const { data: reorderQueue } = useQuery({
    queryKey: ["reorder-queue"],
    queryFn: () => api.crm.reorderQueue(20),
    staleTime: 60_000,
  });

  const { data: orderDetail, isLoading: orderDetailLoading } = useQuery({
    queryKey: ["fd-invoice-detail", expandedOrderId],
    queryFn: () => api.frontdesk.getInvoice(expandedOrderId!),
    enabled: !!expandedOrderId,
  });

  // Realtime — same "shared queue multiple staff act on concurrently"
  // justification as InvoicesTab's existing Ch.7 usage: a QC/Finance/Ops
  // user acting from InvoicesTab (or another Workspace session) shows up
  // here live, without navigating away from the customer.
  useRealtimeChannel("frontdesk_updates", (msg: any) => {
    refetchToday();
    if (selectedCustomer) qc.invalidateQueries({ queryKey: ["customer-360", selectedCustomer.id] });
    if (expandedOrderId && msg?.invoice_id === expandedOrderId) {
      qc.invalidateQueries({ queryKey: ["fd-invoice-detail", expandedOrderId] });
    }
  });

  function selectCustomer(c: CustomerSearchResult) {
    setSelectedCustomer(c);
    setExpandedOrderId(null);
    setRecent((prev) => [c, ...prev.filter((r) => r.id !== c.id)].slice(0, 5));
  }

  const quickRequestMutation = useMutation({
    mutationFn: () => api.frontdesk.quickRequest(selectedCustomer!.id, {
      items: items
        .filter((it) => it.product.trim())
        .map((it) => ({
          product: it.product.trim(), quantity: it.quantity, unit_price: it.unit_price,
          batch_number: it.batch_number || undefined,
          manufacture_date: it.manufacture_date || undefined,
          expiry_date: it.expiry_date || undefined,
        })),
      payment_method: paymentMethod,
      notes: notes.trim() || undefined,
      billing_address: billingAddress.trim() || undefined,
      shipping_address: (sameAsBilling ? billingAddress : shippingAddress).trim() || undefined,
      customer_po: customerPo.trim() || undefined,
      payment_terms: paymentTerms,
      shipping_method: shippingMethod.trim() || undefined,
    }),
    onSuccess: (data: any) => {
      toast({ title: "Request created", description: "Invoice raised and queued for QC." });
      setSheetOpen(false);
      setItems([{ product: "", quantity: 1, unit_price: 0 }]);
      setItemSuggestions(null);
      setNotes("");
      if (selectedCustomer) qc.invalidateQueries({ queryKey: ["customer-360", selectedCustomer.id] });
      refetchToday();
      // Auto-expand the new invoice so its QC action panel is immediately
      // visible — closes the exact "search -> request -> QC/Finance/deliver"
      // loop the business owner described.
      if (data?.invoice?.id) setExpandedOrderId(data.invoice.id);
    },
    onError: (e: any) => toast({ title: "Request failed", description: e?.message, variant: "destructive" }),
  });

  // Requires a selected customer -- previously only checked item validity,
  // which was safe only because the sheet could never open without one
  // already selected (the trigger button was itself disabled otherwise).
  // The new ?action=new-request auto-open (above) is the first path that
  // can open this sheet before a customer is chosen, so this now guards
  // the actual submission too.
  const canSubmitRequest = !!selectedCustomer && items.some((it) => it.product.trim() && it.quantity > 0);

  return (
    <div className="space-y-4">
      <PageHeader
        icon={Users}
        title="Customer Workspace"
        subtitle="Search a customer, view their full context, and raise a new request — without leaving their record."
        actions={
          <Button
            variant="outline" size="sm" className="gap-2"
            onClick={() => { refetchToday(); if (selectedCustomer) refetchContext(); }}
          >
            <RefreshCw className="h-4 w-4" /> Refresh
          </Button>
        }
      />

      <KpiStrip
        items={[
          { label: "Pending QC Today", value: kpis.pendingQc, tone: "warning" },
          { label: "Pending Finance Today", value: kpis.pendingFinance, tone: "warning" },
          { label: "Dispatched Today", value: kpis.dispatched, tone: "success" },
          { label: "Total Requests Today", value: kpis.total },
        ]}
      />

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr_240px] gap-4">
        {/* List Panel */}
        <Card className="lg:max-h-[700px] flex flex-col">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Find Customer</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 overflow-y-auto flex-1">
            <EntityAutocomplete<CustomerSearchResult>
              placeholder="Search customer name or code…"
              fetchFn={(q) => api.crm.searchCustomers(q).then((r: any) => r?.data ?? [])}
              getKey={(c) => c.id}
              getLabel={(c) => c.name}
              getSubtitle={(c) => c.customer_code || c.phone}
              onSelect={selectCustomer}
            />
            {recent.length > 0 && (
              <div className="space-y-1">
                <div className="text-xs font-semibold text-muted-foreground">RECENTLY VIEWED</div>
                {recent.map((c) => (
                  <button
                    key={c.id}
                    onClick={() => selectCustomer(c)}
                    className={`w-full text-left rounded-lg border bg-card px-3 py-2 hover:bg-muted/40 transition-colors ${
                      selectedCustomer?.id === c.id ? "border-primary bg-muted/40" : ""
                    }`}
                  >
                    <div className="font-medium text-sm">{c.name}</div>
                    {(c.customer_code || c.phone) && (
                      <div className="text-xs text-muted-foreground">{c.customer_code || c.phone}</div>
                    )}
                  </button>
                ))}
              </div>
            )}
            {recent.length === 0 && !selectedCustomer && (
              <p className="text-xs text-muted-foreground text-center py-8">Search above to find a customer.</p>
            )}
          </CardContent>
        </Card>

        {/* Detail Workspace — inline, no dismiss button (Ch.5.1). The
            customer should never be "lost" from view; selecting a different
            customer (or order within them) is the only way context changes. */}
        <Card>
          <CardContent className="pt-6">
            {!selectedCustomer && (
              <p className="text-sm text-muted-foreground text-center py-12">Select a customer to view their workspace.</p>
            )}
            {selectedCustomer && contextLoading && (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            )}
            {selectedCustomer && context && (() => {
              const cust = (context as any).customer;
              const recv = (context as any).receivables;
              return (
                <div className="space-y-4 text-sm">
                  <div>
                    <div className="font-bold text-lg">{cust.name}</div>
                    {cust.customer_code && <div className="text-xs text-muted-foreground font-mono">{cust.customer_code}</div>}
                  </div>

                  <div className="grid grid-cols-2 gap-2">
                    <div className="space-y-0.5">
                      <div className="text-xs text-muted-foreground">Phone</div>
                      <div>{cust.phone || "—"}</div>
                    </div>
                    <div className="space-y-0.5">
                      <div className="text-xs text-muted-foreground">Email</div>
                      <div>{cust.email || "—"}</div>
                    </div>
                    <div className="space-y-0.5">
                      <div className="text-xs text-muted-foreground">City</div>
                      <div>{cust.city || "—"}</div>
                    </div>
                    <div className="space-y-0.5">
                      <div className="text-xs text-muted-foreground">Terms</div>
                      <div>{cust.terms || "—"}</div>
                    </div>
                  </div>

                  <Separator />

                  <div>
                    <div className="text-xs font-semibold text-muted-foreground mb-2">RECEIVABLES</div>
                    <div className="grid grid-cols-2 gap-2">
                      <div className="rounded-lg bg-muted/40 px-3 py-2">
                        <div className="text-xs text-muted-foreground">Outstanding</div>
                        <div className="font-bold">{fmt(recv?.outstanding)}</div>
                      </div>
                      <div className="rounded-lg bg-muted/40 px-3 py-2">
                        <div className="text-xs text-muted-foreground">Overdue</div>
                        <div className="font-bold text-red-600">{fmt(recv?.overdue_amount)}</div>
                      </div>
                    </div>
                    {recv?.credit_utilization_pct != null && (
                      <div className="mt-2">
                        <div className="flex justify-between text-xs text-muted-foreground mb-1">
                          <span>Credit Utilization</span>
                          <span>{recv.credit_utilization_pct}%</span>
                        </div>
                        <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
                          <div
                            className={`h-full ${
                              recv.credit_utilization_pct > 90 ? "bg-red-500" :
                              recv.credit_utilization_pct > 70 ? "bg-amber-500" : "bg-green-500"
                            }`}
                            style={{ width: `${Math.min(100, recv.credit_utilization_pct)}%` }}
                          />
                        </div>
                      </div>
                    )}
                  </div>

                  <Separator />

                  {(() => {
                    const rp = (context as any).reorder_profile;
                    if (!rp || rp.confidence === "insufficient_history") return null;
                    const overdue = (rp.days_until_or_since ?? 0) > 0;
                    return (
                      <div>
                        <div className="text-xs font-semibold text-muted-foreground mb-2">REORDER PROFILE</div>
                        <div className="rounded-lg bg-muted/40 px-3 py-2 space-y-1">
                          <div className="flex justify-between items-center">
                            <span className="text-xs text-muted-foreground">Predicted next order</span>
                            <span className={`font-semibold text-sm ${overdue ? "text-red-600" : ""}`}>
                              {rp.predicted_next_order_date ? new Date(rp.predicted_next_order_date).toLocaleDateString() : "—"}
                              {overdue && ` (${rp.days_until_or_since}d overdue)`}
                            </span>
                          </div>
                          <div className="flex justify-between text-xs text-muted-foreground">
                            <span>Avg. reorder cycle</span>
                            <span>{rp.avg_gap_days} days</span>
                          </div>
                          <div className="flex justify-between text-xs text-muted-foreground">
                            <span>Avg. order value</span>
                            <span>{fmt(rp.avg_order_value)}</span>
                          </div>
                          {rp.churn_risk && (
                            <div className="text-xs font-medium text-red-600 pt-1">
                              ⚠ Overdue beyond typical cycle — possible churn risk
                            </div>
                          )}
                          {rp.confidence === "low" && (
                            <div className="text-xs text-muted-foreground pt-1">Irregular order history — prediction has low confidence.</div>
                          )}
                        </div>
                      </div>
                    );
                  })()}

                  <Separator />

                  <div>
                    <div className="text-xs font-semibold text-muted-foreground mb-2">RECENT ORDERS</div>
                    {orders.length === 0 && (
                      <p className="text-xs text-muted-foreground py-4 text-center border rounded-lg">
                        No requests raised yet from this workspace.
                      </p>
                    )}
                    <div className="space-y-2">
                      {orders.map((o) => (
                        <div key={o.id} className="border rounded-lg overflow-hidden">
                          <button
                            onClick={() => setExpandedOrderId(expandedOrderId === o.id ? null : o.id)}
                            className="w-full flex items-center justify-between px-3 py-2 hover:bg-muted/40 transition-colors text-left"
                          >
                            <div>
                              <div className="font-mono text-xs text-muted-foreground">{o.invoice_number}</div>
                              <div className="text-xs text-muted-foreground">{fmtDate(o.created_at)}</div>
                            </div>
                            <div className="flex items-center gap-2">
                              <span className="font-semibold text-sm">{fmt(o.total_amount)}</span>
                              <StatusPill status={o.status} />
                            </div>
                          </button>
                          {expandedOrderId === o.id && (
                            <div className="border-t bg-muted/20 p-3 space-y-3">
                              {orderDetailLoading && (
                                <div className="flex justify-center py-4">
                                  <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                                </div>
                              )}
                              {orderDetail && (orderDetail as any).invoice && (
                                <>
                                  <div className="space-y-1">
                                    {(orderDetail as any).invoice.items?.map((it: any, i: number) => (
                                      <div key={i} className="flex justify-between bg-card rounded px-3 py-1.5 text-xs">
                                        <span>{it.product} × {it.quantity}</span>
                                        <span className="font-semibold">{fmt(it.line_total ?? it.quantity * it.unit_price)}</span>
                                      </div>
                                    ))}
                                  </div>
                                  {/* Reused, not duplicated — same component InvoicesTab
                                      uses, so a different QC/Finance/Ops user acting from
                                      here follows identical role/status rules. */}
                                  <InvoiceActionPanel
                                    invoice={(orderDetail as any).invoice}
                                    onActioned={() => {
                                      qc.invalidateQueries({ queryKey: ["fd-invoice-detail", o.id] });
                                      qc.invalidateQueries({ queryKey: ["customer-360", selectedCustomer.id] });
                                      refetchToday();
                                    }}
                                  />
                                </>
                              )}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              );
            })()}
          </CardContent>
        </Card>

        {/* Quick Actions */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Quick Actions</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <Button
              className="w-full gap-2"
              disabled={!selectedCustomer}
              onClick={() => setSheetOpen(true)}
            >
              <Plus className="h-4 w-4" /> Make New Request
            </Button>
            <Button
              variant="outline" className="w-full gap-2"
              onClick={() => { refetchToday(); if (selectedCustomer) refetchContext(); }}
            >
              <RefreshCw className="h-4 w-4" /> Refresh
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* Reorder Priority Queue — ranked by urgency from real dated AR
          history. Clicking a row selects that customer into the Detail
          Workspace above, same pattern as clicking a "Recently Viewed" row. */}
      {Array.isArray(reorderQueue) && reorderQueue.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <TrendingUp className="h-4 w-4" /> Reorder Priority Queue
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
              {reorderQueue.map((p: any) => {
                const overdue = (p.days_until_or_since ?? 0) > 0;
                return (
                  <button
                    key={p.customer_code}
                    disabled={!p.customer_pk}
                    onClick={() => p.customer_pk && selectCustomer({ id: p.customer_pk, name: p.customer_name, customer_code: p.customer_code })}
                    className="text-left rounded-lg border p-2.5 hover:bg-muted/40 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
                  >
                    <div className="font-medium text-sm truncate">{p.customer_name}</div>
                    <div className={`text-xs flex items-center gap-1 ${overdue ? "text-red-600 font-medium" : "text-muted-foreground"}`}>
                      <Clock className="h-3 w-3" />
                      {overdue ? `${p.days_until_or_since}d overdue` : `due in ${Math.abs(p.days_until_or_since)}d`}
                    </div>
                    <div className="text-xs text-muted-foreground">{fmt(p.avg_order_value)}/order</div>
                  </button>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* "Make New Request" — an ephemeral create task, belongs in DetailSheet
          per Ch.5.2, not inline (the Detail Workspace above is for viewing an
          existing customer/order, not for a multi-field create form). */}
      <DetailSheet
        open={sheetOpen}
        onOpenChange={(open) => {
          setSheetOpen(open);
          if (!open) setChangingCustomer(false);
        }}
        title="Make New Request"
        description={
          selectedCustomer
            ? `Raise a new invoice request for ${selectedCustomer.name}.`
            : "Pick a customer below, then raise a new invoice request."
        }
        icon={Plus}
        footer={
          <Button
            className="w-full"
            disabled={!canSubmitRequest || quickRequestMutation.isPending}
            onClick={() => quickRequestMutation.mutate()}
          >
            {quickRequestMutation.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            Raise Request
          </Button>
        }
      >
        <div className="space-y-3">
          <div className="space-y-1.5">
            <div className="text-xs font-semibold text-muted-foreground">CUSTOMER</div>
            {selectedCustomer && !changingCustomer ? (
              <div className="flex items-center justify-between gap-2 rounded-lg border bg-muted/30 px-3 py-2">
                <div className="min-w-0">
                  <div className="text-sm font-medium truncate">{selectedCustomer.name}</div>
                  {(selectedCustomer.customer_code || selectedCustomer.phone) && (
                    <div className="text-xs text-muted-foreground">{selectedCustomer.customer_code || selectedCustomer.phone}</div>
                  )}
                </div>
                <Button variant="ghost" size="sm" className="flex-shrink-0" onClick={() => setChangingCustomer(true)}>
                  Change
                </Button>
              </div>
            ) : (
              <>
                <EntityAutocomplete<CustomerSearchResult>
                  placeholder="Search customer name or code…"
                  fetchFn={(q) => api.crm.searchCustomers(q).then((r: any) => r?.data ?? [])}
                  getKey={(c) => c.id}
                  getLabel={(c) => c.name}
                  getSubtitle={(c) => c.customer_code || c.phone}
                  onSelect={(c) => {
                    selectCustomer(c);
                    setChangingCustomer(false);
                  }}
                />
                {selectedCustomer && changingCustomer && (
                  <Button variant="ghost" size="sm" onClick={() => setChangingCustomer(false)}>
                    Cancel
                  </Button>
                )}
              </>
            )}
          </div>

          {/* Invoice Details — Bill To/Ship To, PO, Payment Terms, Shipping
              Method. Matches the real Placeware paper invoice's fields;
              feeds printInvoice() (Frontdesk.tsx). */}
          <div className="space-y-3 rounded-lg border p-3 bg-muted/20">
            <div className="text-xs font-semibold text-muted-foreground">INVOICE DETAILS</div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-sm font-medium">Bill To</label>
                <Textarea rows={2} placeholder="Billing address" value={billingAddress}
                  onChange={(e) => setBillingAddress(e.target.value)} />
              </div>
              <div className="space-y-1">
                <div className="flex items-center justify-between">
                  <label className="text-sm font-medium">Ship To</label>
                  <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <input type="checkbox" className="h-3.5 w-3.5 rounded border-gray-300"
                      checked={sameAsBilling} onChange={(e) => setSameAsBilling(e.target.checked)} />
                    Same as Bill To
                  </label>
                </div>
                <Textarea rows={2} placeholder="Shipping address" value={sameAsBilling ? billingAddress : shippingAddress}
                  disabled={sameAsBilling} onChange={(e) => setShippingAddress(e.target.value)} />
              </div>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1">
                <label className="text-sm font-medium">Customer PO</label>
                <Input placeholder="Optional" value={customerPo} onChange={(e) => setCustomerPo(e.target.value)} />
              </div>
              <div className="space-y-1">
                <label className="text-sm font-medium">Payment Terms</label>
                <Select value={paymentTerms} onValueChange={setPaymentTerms}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {["Due on Receipt", "Net 7 Days", "Net 15 Days", "Net 30 Days", "Net 60 Days"].map((t) => (
                      <SelectItem key={t} value={t}>{t}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <label className="text-sm font-medium">Shipping Method</label>
                <Input placeholder="e.g. Hand Delivery" value={shippingMethod} onChange={(e) => setShippingMethod(e.target.value)} />
              </div>
            </div>
          </div>

          <div className="text-xs font-semibold text-muted-foreground">ITEMS</div>
          {items.map((it, idx) => (
            <div key={idx} className="space-y-1">
            <div className="flex gap-2 items-start">
              <div className="relative flex-1">
                <Input
                  placeholder="Product"
                  value={it.product}
                  onChange={(e) => handleProductInputChange(idx, e.target.value)}
                  onBlur={() => setItemSuggestions((s) => (s?.idx === idx ? null : s))}
                />
                {itemSuggestions?.idx === idx && itemSuggestions.results.length > 0 && (
                  <ul className="absolute z-40 mt-1 w-72 bg-card border rounded shadow max-h-56 overflow-auto">
                    {itemSuggestions.results.map((sug) => (
                      <li
                        key={sug.sku ?? sug.name}
                        className="p-2 hover:bg-accent/10 cursor-pointer"
                        onMouseDown={(e) => { e.preventDefault(); applyItemSuggestion(idx, sug); }}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-medium truncate">{sug.name}</span>
                          {sug.selling_price != null && (
                            <span className="text-xs font-semibold text-green-600 flex-shrink-0">{fmt(sug.selling_price)}</span>
                          )}
                        </div>
                        <div className="text-xs text-muted-foreground flex items-center gap-1.5">
                          {sug.sku && <span className="font-mono">{sug.sku}</span>}
                          <span className={sug.current_stock != null && sug.current_stock <= 0 ? "text-red-600 font-medium" : undefined}>
                            Stock: {sug.current_stock ?? "—"}
                          </span>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <Input
                type="number" min={1} placeholder="Qty" className="w-20"
                value={it.quantity}
                onChange={(e) => setItems((prev) => prev.map((r, i) => (i === idx ? { ...r, quantity: Number(e.target.value) || 1 } : r)))}
              />
              <Input
                type="number" min={0} placeholder="Unit price" className="w-28"
                value={it.unit_price}
                onChange={(e) => setItems((prev) => prev.map((r, i) => (i === idx ? { ...r, unit_price: Number(e.target.value) || 0 } : r)))}
              />
              <Button
                variant="ghost" size="icon"
                disabled={items.length === 1}
                onClick={() => {
                  setItems((prev) => prev.filter((_, i) => i !== idx));
                  setItemSuggestions(null);
                }}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
            {/* Batch Number/Expiry Date autofill from the inventory
                suggestion above; Manufacture Date always manual (no data
                source exists anywhere for it). */}
            <div className="grid grid-cols-3 gap-2 pl-1">
              <Input placeholder="Batch number" className="h-8 text-xs" value={it.batch_number ?? ""}
                onChange={(e) => setItems((prev) => prev.map((r, i) => (i === idx ? { ...r, batch_number: e.target.value } : r)))} />
              <Input type="month" className="h-8 text-xs" value={it.manufacture_date ?? ""}
                onChange={(e) => setItems((prev) => prev.map((r, i) => (i === idx ? { ...r, manufacture_date: e.target.value } : r)))} />
              <Input type="date" className="h-8 text-xs" value={it.expiry_date ?? ""}
                onChange={(e) => setItems((prev) => prev.map((r, i) => (i === idx ? { ...r, expiry_date: e.target.value } : r)))} />
            </div>
            </div>
          ))}
          <Button
            variant="outline" size="sm"
            onClick={() => setItems((prev) => [...prev, { product: "", quantity: 1, unit_price: 0 }])}
          >
            <Plus className="h-4 w-4 mr-1" /> Add item
          </Button>

          <div className="pt-2">
            <div className="text-xs font-semibold text-muted-foreground mb-1">PAYMENT METHOD</div>
            <Select value={paymentMethod} onValueChange={setPaymentMethod}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="cash">Cash</SelectItem>
                <SelectItem value="transfer">Transfer</SelectItem>
                <SelectItem value="credit">Credit</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <Textarea placeholder="Notes (optional)" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />

          <div className="flex justify-between font-bold pt-2 border-t">
            <span>Total</span>
            <span className="text-green-600">
              {fmt(items.reduce((sum, it) => sum + it.quantity * it.unit_price, 0))}
            </span>
          </div>
        </div>
      </DetailSheet>
    </div>
  );
}
