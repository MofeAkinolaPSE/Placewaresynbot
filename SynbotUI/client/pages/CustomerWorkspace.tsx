import { useState, useMemo, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Users, Plus, RefreshCw, Loader2, TrendingUp, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api-client";
import { PageHeader } from "@/components/workspace/PageHeader";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { EntityAutocomplete } from "@/components/workspace/EntityAutocomplete";
import { InvoiceActionPanel } from "@/components/workspace/InvoiceActionPanel";
import { NewRequestSheet, type CustomerSearchResult } from "@/components/workspace/NewRequestSheet";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { DrillLink } from "@/components/books/kit";
import { DrillProvider } from "@/components/books/lineage";
import { ActivitySheet, NewCustomerSheet, NewDealSheet, ReminderSheet, StageChip } from "@/components/crm/crm-kit";

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
  const s = STATUS_LABELS[status] ?? { label: status, color: "bg-gray-100 text-gray-600 dark:bg-gray-500/15 dark:text-gray-300" };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${s.color}`}>
      {s.label}
    </span>
  );
}

type OrderRow = { id: string; invoice_number?: string; walk_in_id: string; status: string; total_amount: number; created_at: string };

export default function CustomerWorkspace() {
  return <DrillProvider><CustomerWorkspaceInner /></DrillProvider>;
}

function CustomerWorkspaceInner() {
  const { toast } = useToast();
  const qc = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();

  const [selectedCustomer, setSelectedCustomer] = useState<CustomerSearchResult | null>(null);
  // Session-only, no persistence — matches ACE-Workspace-Standard.md Ch.6
  // (TanStack Query cache + local state only, no global state library).
  const [recent, setRecent] = useState<CustomerSearchResult[]>([]);
  const [expandedOrderId, setExpandedOrderId] = useState<string | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  // CRM actions on the selected customer (deal, call log, reminder) and creating a customer.
  const [crmAction, setCrmAction] = useState<null | "deal" | "activity" | "reminder" | "customer">(null);

  // Cross-link from the ACE Workstation's "Create Invoice" Quick Action
  // (/customers/workspace?action=new-request) — auto-opens this page's
  // existing request form instead of duplicating it. Consumed once, then
  // stripped from the URL so a refresh doesn't keep re-triggering it.
  useEffect(() => {
    const preselect = Number(searchParams.get("customer"));
    if (preselect) {
      setSelectedCustomer({ id: preselect, name: "" });
      setSheetOpen(true);
      searchParams.delete("customer");
      setSearchParams(searchParams, { replace: true });
    }
    if (searchParams.get("action") === "new-request") {
      setSheetOpen(true);
      searchParams.delete("action");
      setSearchParams(searchParams, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  // A ?customer= preselect arrives with only an id -- fill in the name once
  // customer_360 has it.
  useEffect(() => {
    const cust = (context as any)?.customer;
    if (cust && selectedCustomer && !selectedCustomer.name && cust.name) {
      setSelectedCustomer({ ...selectedCustomer, name: cust.name, customer_code: cust.customer_code });
    }
  }, [context, selectedCustomer]);

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
                        <div className="font-bold text-red-600 dark:text-red-300">{fmt(recv?.overdue_amount)}</div>
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
                            <span className={`font-semibold text-sm ${overdue ? "text-red-600 dark:text-red-300" : ""}`}>
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
                            <div className="text-xs font-medium text-red-600 pt-1 dark:text-red-300">
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

                  {(() => {
                    const prof = (context as any).profitability;
                    const invs: any[] = (context as any).invoices ?? [];
                    return (
                      <div>
                        <div className="mb-2 flex items-center justify-between">
                          <span className="text-xs font-semibold text-muted-foreground">SALES & INVOICES (ACE BOOKS)</span>
                          <DrillLink to={{ type: "customer", id: String(cust.id), label: cust.name }}><span className="text-xs">Full account</span></DrillLink>
                        </div>
                        {prof && (
                          <div className="mb-2 grid grid-cols-2 gap-2">
                            <div className="rounded-lg bg-muted/40 px-3 py-2"><div className="text-xs text-muted-foreground">Lifetime sales</div><div className="font-bold">{fmt(prof.sales)}</div></div>
                            <div className="rounded-lg bg-muted/40 px-3 py-2"><div className="text-xs text-muted-foreground">Gross margin</div><div className="font-bold">{prof.gross_margin_pct != null ? `${Number(prof.gross_margin_pct).toFixed(1)}%` : "—"}</div></div>
                          </div>
                        )}
                        {invs.length === 0 ? <p className="rounded-lg border py-3 text-center text-xs text-muted-foreground">No invoices yet.</p> : (
                          <div className="space-y-1">
                            {invs.slice(0, 8).map((iv: any) => (
                              <div key={`${iv.source}-${iv.invoice_id}`} className="flex items-center justify-between rounded border px-2 py-1 text-xs">
                                <span className="truncate">
                                  {iv.ace_invoice_id ? <DrillLink to={{ type: "invoice", id: iv.ace_invoice_id, label: iv.invoice_id }}>{iv.invoice_id}</DrillLink>
                                    : <DrillLink to={{ type: "sageinvoice", id: String(iv.invoice_id), label: iv.invoice_id }}>{iv.invoice_id}</DrillLink>}
                                  <span className="ml-1 text-muted-foreground">{iv.date ? new Date(iv.date).toLocaleDateString("en-GB") : ""}</span>
                                </span>
                                <span className="shrink-0">{fmt(Number(iv.amount))}{Number(iv.balance) > 0 && <span className="ml-1 text-red-600 dark:text-red-300">· owes {fmt(Number(iv.balance))}</span>}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })()}

                  {(((context as any).deals ?? []).length > 0 || ((context as any).activity ?? []).length > 0) && (
                    <div>
                      <div className="mb-2 text-xs font-semibold text-muted-foreground">DEALS & CONTACT</div>
                      {((context as any).deals ?? []).map((dl: any) => (
                        <div key={dl.id} className="flex items-center justify-between border-b py-1 text-xs"><span>{dl.company_name}</span>
                          <span className="flex items-center gap-2">{Number(dl.expected_value) > 0 && fmt(Number(dl.expected_value))}<StageChip stage={dl.stage} /></span></div>
                      ))}
                      {((context as any).activity ?? []).map((a: any, i: number) => (
                        <div key={i} className="border-b py-1 text-xs"><span className="font-medium capitalize">{String(a.interaction_type).replace("_", " ")}</span> · {a.summary}
                          <span className="ml-1 text-muted-foreground">{fmtDate(a.occurred_at)}</span></div>
                      ))}
                    </div>
                  )}

                  <div>
                    <div className="text-xs font-semibold text-muted-foreground mb-2">RECENT ORDERS</div>
                    {orders.length === 0 && (
                      <p className="text-xs text-muted-foreground py-4 text-center border rounded-lg">
                        No Frontdesk requests raised for this customer yet.
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
            <Button variant="outline" className="w-full" disabled={!selectedCustomer} onClick={() => setCrmAction("activity")}>Log a call or visit</Button>
            <Button variant="outline" className="w-full" disabled={!selectedCustomer} onClick={() => setCrmAction("reminder")}>Set a reminder</Button>
            <Button variant="outline" className="w-full" disabled={!selectedCustomer} onClick={() => setCrmAction("deal")}>New deal for this customer</Button>
            <Button variant="outline" className="w-full" onClick={() => setCrmAction("customer")}>New customer</Button>
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
                    <div className={`text-xs flex items-center gap-1 ${overdue ? "text-red-600 font-medium dark:text-red-300" : "text-muted-foreground"}`}>
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

      <ActivitySheet target={crmAction === "activity" && selectedCustomer ? { customer_id: selectedCustomer.id, name: selectedCustomer.name } : null}
        onClose={() => { setCrmAction(null); if (selectedCustomer) qc.invalidateQueries({ queryKey: ["customer-360", selectedCustomer.id] }); }} />
      <ReminderSheet target={crmAction === "reminder" && selectedCustomer ? { customer_id: selectedCustomer.id, name: selectedCustomer.name } : null} onClose={() => setCrmAction(null)} />
      <NewDealSheet key={`deal-${selectedCustomer?.id}`} open={crmAction === "deal" && !!selectedCustomer}
        defaults={selectedCustomer ? { company_name: selectedCustomer.name, customer_id: selectedCustomer.id, source: "existing_customer" } : {}}
        onClose={() => { setCrmAction(null); if (selectedCustomer) qc.invalidateQueries({ queryKey: ["customer-360", selectedCustomer.id] }); }} />
      <NewCustomerSheet open={crmAction === "customer"} onClose={() => setCrmAction(null)}
        onCreated={(c) => selectCustomer({ id: c.id, name: c.name })} />

      {/* "Make New Request" — an ephemeral create task, belongs in a sheet per
          Ch.5.2. Shared with Frontdesk (components/workspace/NewRequestSheet). */}
      <NewRequestSheet
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        customer={selectedCustomer}
        onCustomerChange={selectCustomer}
        onCreated={(data) => {
          if (selectedCustomer) qc.invalidateQueries({ queryKey: ["customer-360", selectedCustomer.id] });
          refetchToday();
          // Auto-expand the new invoice so its QC action panel is immediately visible.
          if (data?.invoice?.id) setExpandedOrderId(data.invoice.id);
        }}
      />
    </div>
  );
}
