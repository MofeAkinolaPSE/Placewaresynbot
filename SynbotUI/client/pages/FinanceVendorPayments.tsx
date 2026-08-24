import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  Loader2,
  PlusCircle,
  Wallet,
  X,
  XCircle,
} from "lucide-react";
import { motion } from "framer-motion";
import { motionVariants } from "@/lib/motion";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api-client";
import { PageHeader } from "@/components/workspace/PageHeader";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { DetailSheet } from "@/components/workspace/DetailSheet";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const fmt = (n: number) =>
  typeof n === "number"
    ? `₦${n.toLocaleString("en-NG", { minimumFractionDigits: 2 })}`
    : "—";

const STATUS_TABS = [
  { value: "all", label: "All" },
  { value: "pending", label: "Pending" },
  { value: "approved", label: "Approved" },
  { value: "paid", label: "Paid" },
  { value: "rejected", label: "Rejected" },
  { value: "cancelled", label: "Cancelled" },
];

function StatusBadge({ status }: { status: string }) {
  const config: Record<string, string> = {
    pending:   "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400",
    approved:  "bg-blue-500/15 text-blue-700 dark:text-blue-400",
    paid:      "bg-green-500/15 text-green-700 dark:text-green-400",
    rejected:  "bg-red-500/15 text-red-700 dark:text-red-400",
    cancelled: "bg-muted text-muted-foreground",
  };
  const cls = config[status] ?? "bg-muted text-muted-foreground";
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-semibold ${cls}`}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

// ---------------------------------------------------------------------------
// FinanceVendorPayments page
// ---------------------------------------------------------------------------
export default function FinanceVendorPayments() {
  const { toast } = useToast();
  const qc = useQueryClient();

  const [statusFilter, setStatusFilter] = useState("all");
  const [createOpen, setCreateOpen] = useState(false);
  const [rejectDialogId, setRejectDialogId] = useState<string | null>(null);
  const [rejectNote, setRejectNote] = useState("");
  const [approveNoteId, setApproveNoteId] = useState<string | null>(null);
  const [approveNote, setApproveNote] = useState("");

  const [form, setForm] = useState({
    vendor_id: "",
    vendor_name: "",
    amount: "",
    currency: "NGN",
    payment_date: "",
    reference: "",
    description: "",
  });

  // --- query ---
  const paymentsQ = useQuery({
    queryKey: ["finance-vendor-payments", statusFilter],
    queryFn: () =>
      api.finance.listVendorPayments(statusFilter === "all" ? undefined : statusFilter),
    refetchInterval: 60_000,
  });

  const payments: any[] = (paymentsQ.data as any)?.data ?? [];

  // --- mutations ---
  const createMut = useMutation({
    mutationFn: (p: any) => api.finance.createVendorPayment(p),
    onSuccess: () => {
      toast({ title: "Payment request created" });
      void qc.invalidateQueries({ queryKey: ["finance-vendor-payments"] });
      setCreateOpen(false);
      setForm({ vendor_id: "", vendor_name: "", amount: "", currency: "NGN", payment_date: "", reference: "", description: "" });
    },
    onError: (err: any) =>
      toast({ title: "Failed to create request", description: err.message, variant: "destructive" }),
  });

  const approveMut = useMutation({
    mutationFn: ({ id, note }: { id: string; note?: string }) =>
      api.finance.approveVendorPayment(id, note),
    onSuccess: () => {
      toast({ title: "Payment approved" });
      void qc.invalidateQueries({ queryKey: ["finance-vendor-payments"] });
      setApproveNoteId(null);
      setApproveNote("");
    },
    onError: (err: any) =>
      toast({ title: "Approval failed", description: err.message, variant: "destructive" }),
  });

  const rejectMut = useMutation({
    mutationFn: ({ id, note }: { id: string; note?: string }) =>
      api.finance.rejectVendorPayment(id, note),
    onSuccess: () => {
      toast({ title: "Payment rejected" });
      void qc.invalidateQueries({ queryKey: ["finance-vendor-payments"] });
      setRejectDialogId(null);
      setRejectNote("");
    },
    onError: (err: any) =>
      toast({ title: "Rejection failed", description: err.message, variant: "destructive" }),
  });

  const paidMut = useMutation({
    mutationFn: (id: string) => api.finance.markVendorPaymentPaid(id),
    onSuccess: () => {
      toast({ title: "Marked as paid" });
      void qc.invalidateQueries({ queryKey: ["finance-vendor-payments"] });
    },
    onError: (err: any) =>
      toast({ title: "Failed to mark paid", description: err.message, variant: "destructive" }),
  });

  const cancelMut = useMutation({
    mutationFn: (id: string) => api.finance.cancelVendorPayment(id),
    onSuccess: () => {
      toast({ title: "Payment request cancelled" });
      void qc.invalidateQueries({ queryKey: ["finance-vendor-payments"] });
    },
    onError: (err: any) =>
      toast({ title: "Cancel failed", description: err.message, variant: "destructive" }),
  });

  // --- summary counts ---
  const allQ = useQuery({
    queryKey: ["finance-vendor-payments", "all"],
    queryFn: () => api.finance.listVendorPayments(undefined, 500),
    refetchInterval: 120_000,
  });
  const allPayments: any[] = (allQ.data as any)?.data ?? [];
  const pendingCount = allPayments.filter((p) => p.status === "pending").length;
  const totalApproved = allPayments
    .filter((p) => p.status === "approved")
    .reduce((s, p) => s + parseFloat(p.amount || 0), 0);
  const totalPaid = allPayments
    .filter((p) => p.status === "paid")
    .reduce((s, p) => s + parseFloat(p.amount || 0), 0);

  function handleCreate() {
    if (!form.vendor_id || !form.amount) {
      toast({ title: "Vendor ID and Amount are required", variant: "destructive" });
      return;
    }
    createMut.mutate({
      vendor_id: form.vendor_id.trim(),
      vendor_name: form.vendor_name.trim() || undefined,
      amount: parseFloat(form.amount),
      currency: form.currency || "NGN",
      payment_date: form.payment_date || undefined,
      reference: form.reference.trim() || undefined,
      description: form.description.trim() || undefined,
    });
  }

  return (
    <motion.div {...motionVariants.cardEnter} className="space-y-6">
      <PageHeader
        icon={Wallet}
        title="Vendor Payments"
        subtitle="Raise, approve, and track vendor payment requests — MD approval workflow"
        actions={
          <Button onClick={() => setCreateOpen(true)} size="sm">
            <PlusCircle className="w-4 h-4 mr-2" />
            New Request
          </Button>
        }
      />

      <KpiStrip
        items={[
          { label: "Pending Approval", value: pendingCount, tone: "warning" },
          { label: "Approved (Outstanding)", value: fmt(totalApproved) },
          { label: "Total Paid", value: fmt(totalPaid), tone: "success" },
          { label: "Total Requests", value: allPayments.length },
        ]}
      />

      {/* Status filter tabs + table */}
      <Tabs value={statusFilter} onValueChange={setStatusFilter}>
        <TabsList className="mb-4 flex-wrap h-auto gap-1">
          {STATUS_TABS.map((t) => (
            <TabsTrigger key={t.value} value={t.value}>
              {t.label}
              {t.value === "pending" && pendingCount > 0 && (
                <Badge variant="destructive" className="ml-1 h-4 text-xs px-1">
                  {pendingCount}
                </Badge>
              )}
            </TabsTrigger>
          ))}
        </TabsList>

        {STATUS_TABS.map((t) => (
          <TabsContent key={t.value} value={t.value}>
            {paymentsQ.isLoading ? (
              <div className="flex items-center justify-center py-20">
                <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
              </div>
            ) : payments.length === 0 ? (
              <p className="text-center text-muted-foreground py-16">
                No {t.value === "all" ? "" : t.value + " "}payment requests.
              </p>
            ) : (
              <div className="rounded-md border overflow-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Vendor</TableHead>
                      <TableHead className="text-right">Amount</TableHead>
                      <TableHead>Currency</TableHead>
                      <TableHead>Payment Date</TableHead>
                      <TableHead>Reference</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Description</TableHead>
                      <TableHead>Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {payments.map((p: any) => (
                      <TableRow key={p.id}>
                        <TableCell>
                          <div className="font-medium">{p.vendor_name || p.vendor_id}</div>
                          <div className="text-xs text-muted-foreground font-mono">{p.vendor_id}</div>
                        </TableCell>
                        <TableCell className="text-right font-mono font-semibold">
                          {fmt(parseFloat(p.amount))}
                        </TableCell>
                        <TableCell className="text-xs">{p.currency}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {p.payment_date || "—"}
                        </TableCell>
                        <TableCell className="text-xs font-mono">{p.reference || "—"}</TableCell>
                        <TableCell>
                          <StatusBadge status={p.status} />
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground max-w-[200px] truncate">
                          {p.description || "—"}
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-1 flex-wrap">
                            {p.status === "pending" && (
                              <>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="h-7 text-xs text-blue-600 border-blue-300 dark:text-blue-300 dark:border-blue-500/30"
                                  onClick={() => { setApproveNoteId(p.id); setApproveNote(""); }}
                                >
                                  <CheckCircle2 className="w-3 h-3 mr-1" /> Approve
                                </Button>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="h-7 text-xs text-red-600 border-red-300 dark:text-red-300 dark:border-red-500/30"
                                  onClick={() => { setRejectDialogId(p.id); setRejectNote(""); }}
                                >
                                  <XCircle className="w-3 h-3 mr-1" /> Reject
                                </Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  className="h-7 text-xs text-muted-foreground"
                                  onClick={() => cancelMut.mutate(p.id)}
                                  disabled={cancelMut.isPending}
                                >
                                  <X className="w-3 h-3 mr-1" /> Cancel
                                </Button>
                              </>
                            )}
                            {p.status === "approved" && (
                              <>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="h-7 text-xs text-green-600 border-green-300 dark:text-green-300 dark:border-green-500/30"
                                  onClick={() => paidMut.mutate(p.id)}
                                  disabled={paidMut.isPending}
                                >
                                  <Wallet className="w-3 h-3 mr-1" /> Mark Paid
                                </Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  className="h-7 text-xs text-muted-foreground"
                                  onClick={() => cancelMut.mutate(p.id)}
                                  disabled={cancelMut.isPending}
                                >
                                  <X className="w-3 h-3 mr-1" /> Cancel
                                </Button>
                              </>
                            )}
                            {["paid", "rejected", "cancelled"].includes(p.status) && (
                              <span className="text-xs text-muted-foreground italic">
                                {p.approval_note || "—"}
                              </span>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </TabsContent>
        ))}
      </Tabs>

      {/* New Vendor Payment Request — ephemeral create task, DetailSheet per
          Ch.5.2. Was already a Dialog, not an inline-toggle Card, but the
          standard's reasoning is about task shape (multi-field ephemeral
          create with no natural inline home), not what container it
          happened to already use — same move as CAPA/Temperature/NAFDAC/
          FinanceAR's Alert Rules. */}
      <DetailSheet
        open={createOpen}
        onOpenChange={setCreateOpen}
        title="New Vendor Payment Request"
        description="Submit a request for MD/Finance approval before payment is processed."
        icon={PlusCircle}
        footer={
          <Button className="w-full" onClick={handleCreate} disabled={createMut.isPending}>
            {createMut.isPending && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
            Submit Request
          </Button>
        }
      >
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">
                Vendor ID *
              </label>
              <Input
                placeholder="e.g. VND-001"
                value={form.vendor_id}
                onChange={(e) => setForm((f) => ({ ...f, vendor_id: e.target.value }))}
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">
                Vendor Name
              </label>
              <Input
                placeholder="e.g. Acme Pharma Ltd"
                value={form.vendor_name}
                onChange={(e) => setForm((f) => ({ ...f, vendor_name: e.target.value }))}
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">
                Amount (₦) *
              </label>
              <Input
                type="number"
                placeholder="e.g. 500000"
                value={form.amount}
                onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))}
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">
                Payment Date
              </label>
              <Input
                type="date"
                value={form.payment_date}
                onChange={(e) => setForm((f) => ({ ...f, payment_date: e.target.value }))}
              />
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">
              Reference / Invoice Number
            </label>
            <Input
              placeholder="e.g. INV-2026-0042"
              value={form.reference}
              onChange={(e) => setForm((f) => ({ ...f, reference: e.target.value }))}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">
              Description
            </label>
            <Input
              placeholder="e.g. April drug supply payment"
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            />
          </div>
        </div>
      </DetailSheet>

      {/* ====================================================================
          DIALOG: Approve with note
          ==================================================================== */}
      <Dialog open={!!approveNoteId} onOpenChange={(open) => { if (!open) { setApproveNoteId(null); setApproveNote(""); } }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Approve Payment Request</DialogTitle>
            <DialogDescription>Optionally add an approval note before confirming.</DialogDescription>
          </DialogHeader>
          <Input
            placeholder="Approval note (optional)"
            value={approveNote}
            onChange={(e) => setApproveNote(e.target.value)}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setApproveNoteId(null)}>
              Cancel
            </Button>
            <Button
              className="bg-blue-600 hover:bg-blue-700 text-white"
              onClick={() => approveNoteId && approveMut.mutate({ id: approveNoteId, note: approveNote || undefined })}
              disabled={approveMut.isPending}
            >
              {approveMut.isPending && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              Confirm Approval
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ====================================================================
          DIALOG: Reject with note
          ==================================================================== */}
      <Dialog open={!!rejectDialogId} onOpenChange={(open) => { if (!open) { setRejectDialogId(null); setRejectNote(""); } }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject Payment Request</DialogTitle>
            <DialogDescription>Provide a reason for rejection (required for audit trail).</DialogDescription>
          </DialogHeader>
          <Input
            placeholder="Rejection reason *"
            value={rejectNote}
            onChange={(e) => setRejectNote(e.target.value)}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRejectDialogId(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => rejectDialogId && rejectMut.mutate({ id: rejectDialogId, note: rejectNote || undefined })}
              disabled={rejectMut.isPending || !rejectNote.trim()}
            >
              {rejectMut.isPending && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              Confirm Rejection
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </motion.div>
  );
}
