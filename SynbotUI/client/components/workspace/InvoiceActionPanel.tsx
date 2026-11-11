import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, CheckCircle2, Truck, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api-client";
import { useAuth } from "@/components/AuthProvider";
import { myUserId } from "@/lib/auth-client";
import { PrintFrontdeskInvoiceButton } from "@/components/frontdesk/PrintFrontdeskInvoice";
import { askText } from "@/lib/ask";
import { Link } from "react-router-dom";
import { ModifyInvoiceSheet } from "@/components/frontdesk/ModifyInvoice";

/**
 * Role-aware Finance/Dispatch action panel for a single Frontdesk invoice, shared by every screen that shows
 * one. Frontdesk raises the invoice and Finance (or the CFO/CEO) approves it - the client dropped the QC
 * stage on 6 Nov - and approval posts it to ACE Books.
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
  showPrint = true,
}: {
  invoice: ActionableInvoice;
  onActioned: () => void;
  /** Print invoice at the top of the panel (off where the page already has its own print button). */
  showPrint?: boolean;
}) {
  const { roles } = useAuth();
  const { toast } = useToast();
  const qc = useQueryClient();

  const historyQuery = useQuery({
    queryKey: ["invoice-history", invoice.id],
    queryFn: () => api.frontdesk.invoiceHistory(invoice.id),
  });
  const events: { event_type: string; outcome?: string; created_at: string }[] = historyQuery.data?.events ?? [];

  const [financeApprover, setFinanceApprover] = useState("");
  const [financeReason, setFinanceReason] = useState("");

  const raisedByMe = !!myUserId() && String((invoice as any).created_by ?? "") === myUserId();
  // Finance approves; the CFO/CEO (management) can sign off when Finance is away
  const canFinance = roles.includes("admin") || roles.includes("finance") || roles.includes("management");
  // waiting for Finance - including a request raised before the QC stage was dropped
  const awaitingFinance = ["finance_pending", "finance_rejected", "draft", "qc_pending", "qc_passed", "qc_failed"].includes(invoice.status);
  const canDispatch = roles.includes("admin") || roles.includes("finance") || roles.includes("ops");
  const approved = ["finance_approved", "dispatched", "completed"].includes(String((invoice as any).status));
  const canVoid = String((invoice as any).status) !== "cancelled"
    && (roles.includes("admin") || roles.includes("finance") || roles.includes("management")
        || ((raisedByMe || roles.includes("frontdesk") || roles.includes("sales")) && !approved));
  const voidMutation = useMutation({
    mutationFn: (reason: string) => api.frontdesk.voidInvoice(invoice.id, reason),
    onSuccess: (r: any) => {
      toast({ title: "Invoice voided", description: r?.ace_invoice_voided
        ? "Voided in ACE Books too - stock and postings reversed. It has left Finance's queue, Frontdesk and the customer's orders."
        : "It has left Finance's queue, Frontdesk and the customer's orders." });
      qc.invalidateQueries({ queryKey: ["fd-invoices"] });
      qc.invalidateQueries({ queryKey: ["quality"] });
      qc.invalidateQueries({ queryKey: ["books"] });
      onActioned();
    },
    onError: (e: any) => toast({ title: "Could not void", description: e?.message, variant: "destructive" }),
  });
  // before Finance approval the invoice itself is changed; after, it is an ACE Books invoice (Add items / Return / remove items)
  const canModify = !approved && String((invoice as any).status) !== "cancelled"
    && (roles.includes("admin") || roles.includes("finance") || roles.includes("management") || roles.includes("frontdesk") || roles.includes("sales"));
  const aceModify = approved && !!(invoice as any).ace_invoice_id && (roles.includes("admin") || roles.includes("finance") || roles.includes("management"));
  const [modifying, setModifying] = useState(false);
  const voidIt = async () => {
    const reason = await askText(approved
      ? "Why is this invoice being voided? It is already approved: its ACE Books invoice is voided too (stock and postings reversed)."
      : "Why is this invoice being voided? It leaves Finance's queue, Frontdesk and the customer's orders.");
    if (reason && reason.trim()) voidMutation.mutate(reason.trim());
  };


  const financeMutation = useMutation({
    mutationFn: (approved: boolean) => api.frontdesk.financeApproval(invoice.id, {
      approved,
      approver_name: financeApprover.trim() || undefined,
      reason: financeReason.trim() || undefined,
    }),
    onSuccess: (data: any, approved) => {
      const books = data?.books;
      if (approved && books && books.status !== "POSTED") {
        // approved, but the books did not take it - say so instead of a silent "approved"
        toast({ title: "Approved - not yet in ACE Books", description: `${books.message ?? books.status}. It is listed in the Invoice register as Not posted, with Retry.`, variant: "destructive" });
      } else {
        toast({ title: approved ? "Invoice approved" : "Invoice rejected",
                description: approved && books?.invoice_number ? `Posted to ACE Books as invoice ${books.invoice_number}.` : undefined });
      }
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
      <ModifyInvoiceSheet invoice={invoice} open={modifying} onClose={(changed) => { setModifying(false); if (changed) { qc.invalidateQueries({ queryKey: ["fd-invoices"] }); qc.invalidateQueries({ queryKey: ["quality"] }); onActioned(); } }} />
      {(showPrint || canVoid || canModify || approved) && (
        <div className="flex flex-wrap justify-end gap-2">
          {canModify && <Button size="sm" variant="outline" onClick={() => setModifying(true)}>Modify invoice</Button>}
          {aceModify && <Button asChild size="sm" variant="outline"><Link to={`/finance/books/sales?tab=register&invoice=${(invoice as any).ace_invoice_id}`}>Modify invoice (ACE Books)</Link></Button>}
          {approved && !aceModify && String((invoice as any).status) !== "cancelled" &&
            <Button size="sm" variant="outline" onClick={() => toast({ title: "Approved - finance modifies it",
              description: "It is posted in ACE Books: Invoice register -> this invoice -> Add items / Return / remove items." })}>Modify invoice</Button>}
          {canVoid && <Button size="sm" variant="destructive" disabled={voidMutation.isPending} onClick={voidIt}>Void invoice</Button>}
          {showPrint && <PrintFrontdeskInvoiceButton invoiceId={invoice.id} />}
        </div>
      )}
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


      {awaitingFinance && canFinance && (
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
