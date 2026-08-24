import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Receipt, Plus, RefreshCw, XCircle, Loader2, Banknote, ClipboardCheck, ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api-client";
import { PageHeader } from "@/components/workspace/PageHeader";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { FilterBar } from "@/components/workspace/FilterBar";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { EntityAutocomplete } from "@/components/workspace/EntityAutocomplete";
import { InvoiceActionPanel } from "@/components/workspace/InvoiceActionPanel";
import { InvoiceDetailBody } from "@/components/workspace/InvoiceDetailBody";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";

// Matches FinanceVendorPayments.tsx's existing currency-formatting convention.
const fmt = (n: number | null | undefined) =>
  typeof n === "number"
    ? `₦${n.toLocaleString("en-NG", { minimumFractionDigits: 2 })}`
    : "—";

const PAYMENT_METHODS = [
  { value: "cash", label: "Cash" },
  { value: "card", label: "Card" },
  { value: "bank_transfer", label: "Bank Transfer" },
  { value: "mobile_payment", label: "Mobile Payment" },
  { value: "corporate_account", label: "Corporate Account" },
  { value: "split_payment", label: "Split Payment" },
  { value: "cheque", label: "Cheque" },
  { value: "pos", label: "POS" },
];

function StatusBadge({ status }: { status: string }) {
  return (
    <Badge className={status === "posted" ? "bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300" : "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300"}>
      {status === "posted" ? "Posted" : "Voided"}
    </Badge>
  );
}

type Customer = { customer_id: string; name: string; phone?: string; email?: string };
type OpenInvoice = {
  invoice_id: string;
  due_date?: string;
  invoice_date?: string;
  true_outstanding_balance: number;
};

export default function ARReceipts() {
  const { toast } = useToast();
  const qc = useQueryClient();

  // Filters
  const [statusFilter, setStatusFilter] = useState("");
  const [methodFilter, setMethodFilter] = useState("");
  const [search, setSearch] = useState("");

  // List selection
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Record-receipt sheet
  const [sheetOpen, setSheetOpen] = useState(false);
  const [selectedCustomer, setSelectedCustomer] = useState<Customer | null>(null);
  const [amount, setAmount] = useState("");
  const [paymentMethod, setPaymentMethod] = useState("cash");
  const [reference, setReference] = useState("");
  const [collector, setCollector] = useState("");
  const [receiptDate, setReceiptDate] = useState("");
  const [notes, setNotes] = useState("");
  const [allocations, setAllocations] = useState<Record<string, string>>({});

  // Void dialog
  const [voidId, setVoidId] = useState<string | null>(null);
  const [voidReason, setVoidReason] = useState("");

  // Invoices — invoice requests raised via the ACE Workstation/Customer
  // Workspace pipeline (Frontdesk QC -> Finance -> Dispatch), distinct from
  // the Sage-imported AR invoices the rest of this page reconciles receipts
  // against. Started as a "Pending Finance Approval"-only queue (Finance had
  // no UI anywhere to act on these); broadened to a full status/customer
  // browser so Finance can pull up a client and see their whole invoice
  // history side by side with the receipts search below -- there's no
  // shared key between frontdesk_invoices and the Sage AR system to do a
  // real join, so this is a manual-correlation-by-customer-name workflow,
  // not an automated match. Defaults to finance_pending so the actionable
  // queue is still what loads first.
  const [expandedInvoiceId, setExpandedInvoiceId] = useState<string | null>(null);
  const [invoiceStatusFilter, setInvoiceStatusFilter] = useState("finance_pending");
  const [invoiceSearch, setInvoiceSearch] = useState("");
  const pendingFinanceQuery = useQuery({
    queryKey: ["frontdesk-invoices", invoiceStatusFilter, invoiceSearch],
    queryFn: () => api.frontdesk.listInvoices({
      status: invoiceStatusFilter || undefined,
      q: invoiceSearch || undefined,
      limit: 100,
    }),
    refetchInterval: 30_000,
  });
  const pendingFinanceInvoices: any[] = pendingFinanceQuery.data?.invoices ?? [];
  useRealtimeChannel("frontdesk_updates", () => pendingFinanceQuery.refetch());

  const INVOICE_STATUS_FILTERS = [
    { value: "qc_pending",       label: "Pending QC"      },
    { value: "finance_pending",  label: "Pending Finance" },
    { value: "finance_approved", label: "Approved"        },
    { value: "dispatched",       label: "Dispatched"      },
    { value: "completed",        label: "Completed"       },
    { value: "cancelled",        label: "Cancelled"       },
  ];

  // Full detail (items, batch/expiry, addresses, PO/terms) -- the list
  // query above only has summary columns, same gap as QualityControl.tsx's
  // Pending QC queue: Finance had no way to see what they were actually
  // approving without leaving the page.
  const expandedFinanceDetailQuery = useQuery({
    queryKey: ["fd-invoice-detail", expandedInvoiceId],
    queryFn: () => api.frontdesk.getInvoice(expandedInvoiceId!),
    enabled: !!expandedInvoiceId,
  });

  const listQuery = useQuery({
    queryKey: ["ar-receipts", statusFilter, methodFilter, search],
    queryFn: () =>
      api.finance.listArReceipts({
        status: statusFilter || undefined,
        payment_method: methodFilter || undefined,
        q: search || undefined,
        limit: 100,
      }),
  });

  const detailQuery = useQuery({
    queryKey: ["ar-receipt", selectedId],
    queryFn: () => api.finance.getArReceipt(selectedId as string),
    enabled: !!selectedId,
  });

  const openInvoicesQuery = useQuery({
    queryKey: ["ar-open-invoices", selectedCustomer?.customer_id],
    queryFn: () => api.finance.getCustomerOpenInvoices(selectedCustomer!.customer_id),
    enabled: !!selectedCustomer,
  });

  const resetForm = () => {
    setSelectedCustomer(null);
    setAmount("");
    setPaymentMethod("cash");
    setReference("");
    setCollector("");
    setReceiptDate("");
    setNotes("");
    setAllocations({});
  };

  const createMutation = useMutation({
    mutationFn: (payload: any) => api.finance.createArReceipt(payload),
    onSuccess: () => {
      toast({ title: "Receipt posted" });
      qc.invalidateQueries({ queryKey: ["ar-receipts"] });
      qc.invalidateQueries({ queryKey: ["ar-open-invoices"] });
      setSheetOpen(false);
      resetForm();
    },
    onError: (err: any) =>
      toast({ title: "Failed to post receipt", description: err.message, variant: "destructive" }),
  });

  const voidMutation = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => api.finance.voidArReceipt(id, reason),
    onSuccess: (_data, variables) => {
      toast({ title: "Receipt voided" });
      qc.invalidateQueries({ queryKey: ["ar-receipts"] });
      qc.invalidateQueries({ queryKey: ["ar-receipt", variables.id] });
      qc.invalidateQueries({ queryKey: ["ar-open-invoices"] });
      setVoidId(null);
      setVoidReason("");
    },
    onError: (err: any) =>
      toast({ title: "Failed to void receipt", description: err.message, variant: "destructive" }),
  });

  const summary = listQuery.data?.summary ?? {};
  const receipts = listQuery.data?.data ?? [];
  const openInvoices: OpenInvoice[] = openInvoicesQuery.data?.data ?? [];

  const allocatedTotal = Object.values(allocations).reduce((sum, v) => sum + (parseFloat(v) || 0), 0);
  const amountNum = parseFloat(amount) || 0;
  const remaining = amountNum - allocatedTotal;

  const handleSave = () => {
    if (!selectedCustomer || amountNum <= 0) return;
    const applications = Object.entries(allocations)
      .filter(([, v]) => parseFloat(v) > 0)
      .map(([invoice_id, v]) => ({ invoice_id, amount_applied: parseFloat(v) }));
    createMutation.mutate({
      customer_id: selectedCustomer.customer_id,
      customer_name: selectedCustomer.name,
      amount: amountNum,
      payment_method: paymentMethod,
      reference: reference || undefined,
      collector: collector || undefined,
      receipt_date: receiptDate || undefined,
      notes: notes || undefined,
      applications,
    });
  };

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <PageHeader
        icon={Receipt}
        title="Customer Receipts & Accounts"
        subtitle="Record and reconcile customer payments against invoices"
        actions={
          <Button
            onClick={() => {
              resetForm();
              setSheetOpen(true);
            }}
          >
            <Plus className="h-4 w-4 mr-1" /> Record Receipt
          </Button>
        }
      />

      <KpiStrip
        items={[
          { label: "Today's Receipts", value: fmt(summary.today_total), tone: "success" },
          { label: "Today's Count", value: summary.today_count ?? 0 },
          { label: "Unapplied / On Account", value: fmt(summary.unapplied_total), tone: "warning" },
          { label: "Voided (30d)", value: summary.voided_30d_count ?? 0, tone: "danger" },
        ]}
      />

      {/* Invoices — the ACE Workstation/Frontdesk pipeline's invoices,
          separate from the Sage AR reconciliation below. Lets Finance pull
          up a customer here and cross-check against the receipts search
          further down for the same customer name -- there's no shared key
          between the two systems to join automatically. */}
      <Card className="border-amber-300/60 dark:border-amber-800/60">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <ClipboardCheck className="h-4 w-4 text-amber-600 dark:text-amber-300" />
            Invoices
            <Badge variant="outline" className="ml-1">{pendingFinanceInvoices.length}</Badge>
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            Requests raised via the ACE Workstation / Customer Workspace pipeline. Search by customer to correlate with their receipts below.
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          <FilterBar
            search={{ value: invoiceSearch, onChange: setInvoiceSearch, placeholder: "Search customer name…" }}
            selects={[{
              label: "status",
              value: invoiceStatusFilter,
              onChange: setInvoiceStatusFilter,
              placeholder: "All Statuses",
              options: INVOICE_STATUS_FILTERS,
            }]}
          />
          {pendingFinanceQuery.isLoading && (
            <div className="flex justify-center py-6">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            </div>
          )}
          {!pendingFinanceQuery.isLoading && pendingFinanceInvoices.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-6">No invoices found.</p>
          )}
          <div className="space-y-2">
            {pendingFinanceInvoices.map((inv: any) => (
              <div key={inv.id} className="border rounded-lg overflow-hidden">
                <button
                  onClick={() => setExpandedInvoiceId(expandedInvoiceId === inv.id ? null : inv.id)}
                  className="w-full flex items-center justify-between px-3 py-2 hover:bg-muted/40 transition-colors text-left"
                >
                  <div className="min-w-0">
                    <div className="font-mono text-xs text-muted-foreground">{inv.invoice_number}</div>
                    <div className="text-sm font-medium truncate">{inv.company_name || inv.customer_name}</div>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <span className="font-semibold text-sm">{fmt(inv.total_amount)}</span>
                    {expandedInvoiceId === inv.id ? (
                      <ChevronUp className="h-4 w-4 text-muted-foreground" />
                    ) : (
                      <ChevronDown className="h-4 w-4 text-muted-foreground" />
                    )}
                  </div>
                </button>
                {expandedInvoiceId === inv.id && (
                  <div className="border-t bg-muted/20 p-3 space-y-3">
                    <InvoiceDetailBody
                      invoice={expandedFinanceDetailQuery.data?.invoice}
                      loading={expandedFinanceDetailQuery.isLoading}
                    />
                    <div className="border-t pt-3">
                      <InvoiceActionPanel
                        invoice={inv}
                        onActioned={() => pendingFinanceQuery.refetch()}
                      />
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <FilterBar
        search={{ value: search, onChange: setSearch, placeholder: "Search receipt #, customer, reference..." }}
        selects={[
          {
            label: "statuses",
            value: statusFilter,
            onChange: setStatusFilter,
            placeholder: "All statuses",
            options: [
              { value: "posted", label: "Posted" },
              { value: "voided", label: "Voided" },
            ],
          },
          {
            label: "methods",
            value: methodFilter,
            onChange: setMethodFilter,
            placeholder: "All methods",
            options: PAYMENT_METHODS,
          },
        ]}
      />

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr_240px] gap-4">
        {/* List / Queue Panel */}
        <Card className="lg:max-h-[600px] flex flex-col">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Recent Receipts</CardTitle>
          </CardHeader>
          <CardContent className="overflow-y-auto space-y-1 flex-1">
            {listQuery.isLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
            {receipts.map((r: any) => (
              <button
                key={r.id}
                onClick={() => setSelectedId(r.id)}
                className={`w-full text-left px-2 py-2 rounded-md border text-sm hover:bg-muted/60 transition-colors ${
                  selectedId === r.id ? "border-primary bg-muted/40" : ""
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs">{r.receipt_number}</span>
                  <StatusBadge status={r.status} />
                </div>
                <div className="text-xs text-muted-foreground truncate">{r.customer_name || r.customer_id}</div>
                <div className="text-sm font-semibold">{fmt(r.amount)}</div>
              </button>
            ))}
            {!listQuery.isLoading && receipts.length === 0 && (
              <p className="text-sm text-muted-foreground py-4 text-center">No receipts found.</p>
            )}
          </CardContent>
        </Card>

        {/* Detail Workspace (inline — primary content, per the Modal/Panel Priority rule) */}
        <Card>
          <CardContent className="pt-6">
            {!selectedId && (
              <p className="text-sm text-muted-foreground text-center py-12">Select a receipt to view details.</p>
            )}
            {selectedId && detailQuery.isLoading && (
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            )}
            {selectedId && detailQuery.data && (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-lg font-semibold">{fmt(detailQuery.data.amount)}</div>
                    <div className="text-sm text-muted-foreground">
                      {detailQuery.data.customer_name || detailQuery.data.customer_id}
                    </div>
                  </div>
                  <StatusBadge status={detailQuery.data.status} />
                </div>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <span className="text-muted-foreground">Method:</span> {detailQuery.data.payment_method}
                  </div>
                  <div>
                    <span className="text-muted-foreground">Date:</span> {detailQuery.data.receipt_date}
                  </div>
                  <div>
                    <span className="text-muted-foreground">Reference:</span> {detailQuery.data.reference || "—"}
                  </div>
                  <div>
                    <span className="text-muted-foreground">Collector:</span> {detailQuery.data.collector || "—"}
                  </div>
                </div>
                {detailQuery.data.notes && (
                  <p className="text-sm text-muted-foreground">{detailQuery.data.notes}</p>
                )}
                <div>
                  <h4 className="text-xs font-semibold uppercase text-muted-foreground mb-1">
                    Applied to {detailQuery.data.applications?.length || 0} invoice(s)
                  </h4>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Invoice</TableHead>
                        <TableHead className="text-right">Applied</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(detailQuery.data.applications || []).map((a: any) => (
                        <TableRow key={a.id}>
                          <TableCell className="font-mono text-xs">{a.invoice_id}</TableCell>
                          <TableCell className="text-right">{fmt(a.amount_applied)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
                {detailQuery.data.status === "posted" && (
                  <Button variant="destructive" size="sm" onClick={() => setVoidId(detailQuery.data.id)}>
                    <XCircle className="h-4 w-4 mr-1" /> Void Receipt
                  </Button>
                )}
                {detailQuery.data.status === "voided" && (
                  <p className="text-xs text-red-700 dark:text-red-300">Voided: {detailQuery.data.void_reason}</p>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Quick Actions */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Quick Actions</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <Button
              className="w-full"
              onClick={() => {
                resetForm();
                setSheetOpen(true);
              }}
            >
              <Plus className="h-4 w-4 mr-1" /> Record Receipt
            </Button>
            <Button variant="outline" className="w-full" onClick={() => listQuery.refetch()}>
              <RefreshCw className="h-4 w-4 mr-1" /> Refresh
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* Record Receipt Sheet — the one Sheet usage: an ephemeral task, not persistent page content */}
      <DetailSheet
        open={sheetOpen}
        onOpenChange={(open) => {
          setSheetOpen(open);
          if (!open) resetForm();
        }}
        title="Record Receipt"
        description="Record a customer payment and allocate it to open invoices."
        icon={Banknote}
        footer={
          <Button
            className="w-full"
            onClick={handleSave}
            disabled={!selectedCustomer || amountNum <= 0 || remaining < -0.01 || createMutation.isPending}
          >
            {createMutation.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            Save Receipt
          </Button>
        }
      >
        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground">Customer *</label>
            {selectedCustomer ? (
              <div className="flex items-center justify-between border rounded-md px-3 py-2 mt-1">
                <span className="text-sm">{selectedCustomer.name}</span>
                <Button variant="ghost" size="sm" onClick={() => setSelectedCustomer(null)}>
                  Change
                </Button>
              </div>
            ) : (
              <EntityAutocomplete<Customer>
                fetchFn={(q) => api.finance.searchArReceiptCustomers(q).then((r: any) => r.data ?? [])}
                getKey={(c) => c.customer_id}
                getLabel={(c) => c.name}
                getSubtitle={(c) => c.phone || c.email}
                onSelect={setSelectedCustomer}
                placeholder="Search customer by name..."
              />
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground">Amount (₦) *</label>
              <Input type="number" min="0" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Payment Method *</label>
              <Select value={paymentMethod} onValueChange={setPaymentMethod}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PAYMENT_METHODS.map((m) => (
                    <SelectItem key={m.value} value={m.value}>
                      {m.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground">Reference</label>
              <Input value={reference} onChange={(e) => setReference(e.target.value)} />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Collector</label>
              <Input value={collector} onChange={(e) => setCollector(e.target.value)} />
            </div>
          </div>

          <div>
            <label className="text-xs text-muted-foreground">Receipt Date</label>
            <Input type="date" value={receiptDate} onChange={(e) => setReceiptDate(e.target.value)} />
          </div>

          {selectedCustomer && (
            <div>
              <div className="flex items-center justify-between mb-1">
                <h4 className="text-xs font-semibold uppercase text-muted-foreground">Allocate to open invoices</h4>
                <span className={`text-xs ${remaining < -0.01 ? "text-red-700 dark:text-red-300" : "text-muted-foreground"}`}>
                  Remaining to allocate: {fmt(remaining)}
                </span>
              </div>
              {openInvoicesQuery.isLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
              {!openInvoicesQuery.isLoading && openInvoices.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  No open invoices for this customer — receipt will be recorded on account.
                </p>
              )}
              <div className="space-y-1.5">
                {openInvoices.map((inv) => (
                  <div key={inv.invoice_id} className="flex items-center gap-2 text-sm">
                    <div className="flex-1">
                      <div className="font-mono text-xs">{inv.invoice_id}</div>
                      <div className="text-xs text-muted-foreground">
                        Due {inv.due_date || "—"} · Outstanding {fmt(inv.true_outstanding_balance)}
                      </div>
                    </div>
                    <Input
                      type="number"
                      min="0"
                      step="0.01"
                      className="w-28"
                      placeholder="0.00"
                      value={allocations[inv.invoice_id] ?? ""}
                      onChange={(e) =>
                        setAllocations((prev) => ({ ...prev, [inv.invoice_id]: e.target.value }))
                      }
                    />
                  </div>
                ))}
              </div>
            </div>
          )}

          <div>
            <label className="text-xs text-muted-foreground">Notes</label>
            <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} />
          </div>
        </div>
      </DetailSheet>

      {/* Void Dialog — short confirmation, per the Modal/Panel Priority rule */}
      <Dialog
        open={!!voidId}
        onOpenChange={(open) => {
          if (!open) {
            setVoidId(null);
            setVoidReason("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Void Receipt</DialogTitle>
            <DialogDescription>
              Provide a reason for voiding (required for audit trail). The receipt is never deleted — only
              marked voided.
            </DialogDescription>
          </DialogHeader>
          <Textarea placeholder="Void reason *" value={voidReason} onChange={(e) => setVoidReason(e.target.value)} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setVoidId(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => voidId && voidMutation.mutate({ id: voidId, reason: voidReason })}
              disabled={voidMutation.isPending || !voidReason.trim()}
            >
              {voidMutation.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Confirm Void
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
