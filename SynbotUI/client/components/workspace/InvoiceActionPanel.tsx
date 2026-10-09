import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, CheckCircle2, Truck, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api-client";
import { useAuth } from "@/components/AuthProvider";
import { myUserId } from "@/lib/auth-client";

/**
 * Role-aware QC/Finance/Dispatch action panel for a single Frontdesk
 * invoice. Extracted from Frontdesk.tsx's InvoicesTab so the QC/Finance/
 * Delivery mutation logic is shared, not duplicated, between InvoicesTab
 * and the Centralized Customer Workspace — a correctness concern for
 * financial/QC actions, not just DRY. See ACE-Workspace-Standard.md Ch.10.
 */
export interface ActionableInvoice {
  id: string;
  status: string;
  qc_passed?: boolean | null;
  finance_approved?: boolean | null;
  dispatched_at?: string;
}

// event_type -> human label. Every transition already writes to
// placeware_audit_logs (subject_type="invoice") server-side; this just
// renders it back. outcome disambiguates the two-outcome events (QC
// pass/fail, finance approve/reject) since event_type alone is the same
// string either way.
const EVENT_LABELS: Record<string, (e: { outcome?: string }) => string> = {
  frontdesk_walk_in_registered: () => "Walk-in registered",
  frontdesk_invoice_created: () => "Invoice created",
  frontdesk_quick_request_created: () => "Invoice created",
  frontdesk_qc_checked: (e) => (e.outcome === "pass" ? "QC passed" : "QC failed"),
  frontdesk_finance_decision: (e) => (e.outcome === "approved" ? "Finance approved" : "Finance rejected"),
  frontdesk_invoice_dispatched: () => "Sent for delivery",
  frontdesk_invoice_completed: () => "Delivery confirmed — completed",
  frontdesk_executive_notified: () => "Executive notified",
};

function eventLabel(e: { event_type: string; outcome?: string }): string {
  return EVENT_LABELS[e.event_type]?.(e) ?? e.event_type.replace(/^frontdesk_/, "").replace(/_/g, " ");
}

const fmtHistoryDate = (iso?: string) =>
  iso ? new Date(iso).toLocaleString("en-NG", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";

export function InvoiceActionPanel({
  invoice,
  onActioned,
}: {
  invoice: ActionableInvoice;
  onActioned: () => void;
}) {
  const { roles } = useAuth();
  const { toast } = useToast();
  const qc = useQueryClient();

  const historyQuery = useQuery({
    queryKey: ["invoice-history", invoice.id],
    queryFn: () => api.frontdesk.invoiceHistory(invoice.id),
  });
  const events: { event_type: string; outcome?: string; created_at: string }[] = historyQuery.data?.events ?? [];

  const [qcInspector, setQcInspector] = useState("");
  const [qcBatches, setQcBatches] = useState("");
  const [qcNotes, setQcNotes] = useState("");
  const [financeApprover, setFinanceApprover] = useState("");
  const [financeReason, setFinanceReason] = useState("");

  // QC can't be done by the person who raised the invoice (the server refuses it too)
  const raisedByMe = !!myUserId() && String((invoice as any).created_by ?? "") === myUserId();
  const canQc = roles.includes("admin") || roles.includes("quality_assurance") || roles.includes("qa");
  const canFinance = roles.includes("admin") || roles.includes("finance");
  const canDispatch = roles.includes("admin") || roles.includes("finance") || roles.includes("ops");

  const qcMutation = useMutation({
    mutationFn: (passed: boolean) => api.frontdesk.submitQc(invoice.id, {
      passed,
      inspector_name: qcInspector.trim() || undefined,
      notes: qcNotes.trim() || undefined,
      batch_numbers: qcBatches.trim() ? qcBatches.split(",").map((b) => b.trim()).filter(Boolean) : undefined,
    }),
    onSuccess: (_data, passed) => {
      toast({ title: passed ? "QC passed" : "QC failed", description: `Invoice moved to ${passed ? "Finance" : "QC Failed"}.` });
      setQcInspector(""); setQcBatches(""); setQcNotes("");
      qc.invalidateQueries({ queryKey: ["invoice-history", invoice.id] });
      onActioned();
    },
    onError: (e: any) => toast({ title: "QC submission failed", description: e?.message, variant: "destructive" }),
  });

  const financeMutation = useMutation({
    mutationFn: (approved: boolean) => api.frontdesk.financeApproval(invoice.id, {
      approved,
      approver_name: financeApprover.trim() || undefined,
      reason: financeReason.trim() || undefined,
    }),
    onSuccess: (_data, approved) => {
      toast({ title: approved ? "Invoice approved" : "Invoice rejected" });
      setFinanceApprover(""); setFinanceReason("");
      qc.invalidateQueries({ queryKey: ["invoice-history", invoice.id] });
      onActioned();
    },
    onError: (e: any) => toast({ title: "Finance decision failed", description: e?.message, variant: "destructive" }),
  });

  const dispatchMutation = useMutation({
    mutationFn: () => api.frontdesk.sendForDelivery(invoice.id),
    onSuccess: () => {
      toast({ title: "Sent for delivery", description: "A delivery record was created in Logistics." });
      qc.invalidateQueries({ queryKey: ["invoice-history", invoice.id] });
      onActioned();
    },
    onError: (e: any) => toast({ title: "Dispatch failed", description: e?.message, variant: "destructive" }),
  });

  return (
    <>
      {/* Always rendered regardless of status -- this is the only place in
          the panel that shows anything at all for qc_failed/finance_rejected/
          completed/cancelled invoices, which otherwise render an empty
          fragment (no action block applies to a terminal/rejected state). */}
      <div className="space-y-1.5">
        <div className="text-xs font-semibold text-muted-foreground flex items-center gap-1">
          <Clock className="h-3 w-3" /> INVOICE HISTORY
        </div>
        {historyQuery.isLoading && (
          <div className="flex justify-center py-2">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
          </div>
        )}
        {!historyQuery.isLoading && events.length === 0 && (
          <p className="text-xs text-muted-foreground">No history recorded yet.</p>
        )}
        {events.length > 0 && (
          <div className="space-y-1 max-h-36 overflow-y-auto">
            {events.map((e, i) => (
              <div key={i} className="text-xs flex items-center justify-between bg-muted/30 rounded px-2 py-1">
                <span className="font-medium">{eventLabel(e)}</span>
                <span className="text-muted-foreground flex-shrink-0">{fmtHistoryDate(e.created_at)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {invoice.status === "qc_pending" && canQc && raisedByMe && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 dark:bg-amber-500/10 dark:text-amber-200">
          You raised this invoice, so a QC colleague checks it. It is in their Quality Control queue and they have been notified.
        </div>
      )}

      {invoice.status === "qc_pending" && canQc && !raisedByMe && (
        <div className="space-y-2 border rounded-lg p-3 bg-muted/30">
          <div className="text-xs font-semibold text-muted-foreground">QC CHECK <span className="font-normal">· signed with your login</span></div>
          <Input placeholder="Batch numbers (comma-separated)" value={qcBatches} onChange={(e) => setQcBatches(e.target.value)} />
          <Textarea placeholder="Notes" rows={2} value={qcNotes} onChange={(e) => setQcNotes(e.target.value)} />
          <div className="flex gap-2">
            <Button
              size="sm" variant="destructive" className="flex-1"
              disabled={qcMutation.isPending}
              onClick={() => qcMutation.mutate(false)}
            >
              Fail QC
            </Button>
            <Button
              size="sm" className="flex-1"
              disabled={qcMutation.isPending}
              onClick={() => qcMutation.mutate(true)}
            >
              {qcMutation.isPending && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
              Pass QC
            </Button>
          </div>
        </div>
      )}

      {invoice.status === "finance_pending" && canFinance && (
        <div className="space-y-2 border rounded-lg p-3 bg-muted/30">
          <div className="text-xs font-semibold text-muted-foreground">FINANCE APPROVAL <span className="font-normal">· signed with your login</span></div>
          <Textarea placeholder="Reason (required for rejection)" rows={2} value={financeReason} onChange={(e) => setFinanceReason(e.target.value)} />
          <div className="flex gap-2">
            <Button
              size="sm" variant="destructive" className="flex-1"
              disabled={financeMutation.isPending}
              onClick={() => financeMutation.mutate(false)}
            >
              Reject
            </Button>
            <Button
              size="sm" className="flex-1"
              disabled={financeMutation.isPending}
              onClick={() => financeMutation.mutate(true)}
            >
              {financeMutation.isPending && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
              Approve
            </Button>
          </div>
        </div>
      )}

      {invoice.status === "finance_approved" && canDispatch && (
        <Button
          variant="outline" className="w-full gap-2"
          disabled={dispatchMutation.isPending}
          onClick={() => dispatchMutation.mutate()}
        >
          {dispatchMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Truck className="h-4 w-4" />}
          Send for Delivery
        </Button>
      )}

      {invoice.status === "dispatched" && (
        <div className="rounded-lg border bg-green-50 dark:bg-green-950/30 p-3 text-sm text-green-700 dark:text-green-400 flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          Sent for delivery{invoice.dispatched_at ? ` on ${invoice.dispatched_at}` : ""}.
        </div>
      )}
    </>
  );
}
