import { useState, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Loader2, Eye, Download, RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api-client";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { FilterBar } from "@/components/workspace/FilterBar";
import { InvoiceActionPanel } from "@/components/workspace/InvoiceActionPanel";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";

// ---------------------------------------------------------------------------
// Types — shared with Frontdesk.tsx (walk-in / invoice creation flows also
// use these), moved here alongside InvoicesTab and printInvoice so this
// module can be mounted standalone (e.g. the broadly-accessible
// /frontdesk/invoices route) without pulling in the rest of Frontdesk.tsx.
// ---------------------------------------------------------------------------

export interface WalkIn {
  id: string;
  customer_name: string;
  company_name?: string;
  contact_phone?: string;
  email?: string;
  has_appointment?: boolean;
  purpose: string;
  products_requested?: string[];
  status: string;
  created_at: string;
  customer_code?: string;
}

export interface InvoiceItem {
  product: string;
  quantity: number;
  unit_price: number;
  line_total?: number;
  batch_number?: string;
  manufacture_date?: string;
  expiry_date?: string;
}

export interface Invoice {
  id: string;
  invoice_number: string;
  walk_in_id?: string;
  customer_name: string;
  company_name?: string;
  items: InvoiceItem[];
  total_amount: number;
  payment_method: string;
  status: string;
  qc_passed?: boolean;
  qc_inspector?: string;
  finance_approved?: boolean;
  finance_approver?: string;
  notes?: string;
  created_at: string;
  delivery_id?: string;
  dispatched_at?: string;
  delivered_by?: string;
  billing_address?: string;
  shipping_address?: string;
  customer_po?: string;
  payment_terms?: string;
  due_date?: string;
  shipping_method?: string;
  tax_amount?: number;
  created_by_email?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  arrived:           { label: "Arrived",          color: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300" },
  invoiced:          { label: "Invoiced",          color: "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300" },
  qc_pending:        { label: "Pending QC",        color: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300" },
  qc_passed:         { label: "QC Passed",         color: "bg-teal-100 text-teal-800 dark:bg-teal-900/40 dark:text-teal-300" },
  qc_failed:         { label: "QC Failed",         color: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300" },
  finance_pending:   { label: "Pending Finance",   color: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300" },
  finance_approved:  { label: "Finance Approved",  color: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300" },
  finance_rejected:  { label: "Finance Rejected",  color: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300" },
  completed:         { label: "Completed",         color: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300" },
  cancelled:         { label: "Cancelled",         color: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400" },
  draft:             { label: "Draft",             color: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400" },
};

export function StatusPill({ status }: { status: string }) {
  const s = STATUS_LABELS[status] ?? { label: status, color: "bg-gray-100 text-gray-600 dark:bg-gray-500/15 dark:text-gray-300" };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${s.color}`}>
      {s.label}
    </span>
  );
}

export function fmt(n: number) {
  return "₦" + n.toLocaleString("en-NG", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function fmtDate(iso: string) {
  return new Date(iso).toLocaleString("en-NG", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// Print invoice (browser print-to-PDF)
// ---------------------------------------------------------------------------

// Static company info for the printed invoice header/footer — this app has
// no company_settings table, and a small constant here is the right-sized
// solution for one fixed business's letterhead. Bank details are a
// deliberate placeholder: printing a wrong account number on a real,
// customer-facing invoice is a real business risk, so this waits for the
// exact confirmed value rather than guessing from a photographed paper form.
const COMPANY_INFO = {
  name: "PLACEWARE NIGERIA LIMITED",
  address: "72, Aina Street, Ojodu, Lagos",
  phones: ["08023246113", "08127541803"],
  email: "placewareng@hotmail.com",
  website: "www.placewarenigeria.com",
  bankPayee: "PLACEWARE NIG. LTD.",
  bankDetails: "Bank name &amp; account number — pending confirmation",
};

function fmtDateOnly(iso?: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-NG", { day: "2-digit", month: "short", year: "numeric" });
}

function fmtMonthYear(ym?: string | null): string {
  if (!ym) return "—";
  const [y, m] = ym.split("-");
  if (!y || !m) return ym;
  return new Date(Number(y), Number(m) - 1, 1).toLocaleDateString("en-NG", { month: "short", year: "numeric" });
}

export function printInvoice(invoice: Invoice, walkIn?: WalkIn | null) {
  const win = window.open("", "_blank", "width=1000,height=800");
  if (!win) return;

  const itemRows = invoice.items.map((it) => `
    <tr>
      <td style="padding:8px;border-bottom:1px solid #eee;text-align:center">${it.quantity}</td>
      <td style="padding:8px;border-bottom:1px solid #eee">${it.product}</td>
      <td style="padding:8px;border-bottom:1px solid #eee;font-family:monospace;font-size:11px">${it.batch_number || '<span class="muted">—</span>'}</td>
      <td style="padding:8px;border-bottom:1px solid #eee;font-size:11px">${it.manufacture_date ? fmtMonthYear(it.manufacture_date) : '<span class="muted">—</span>'}</td>
      <td style="padding:8px;border-bottom:1px solid #eee;font-size:11px">${it.expiry_date ? fmtDateOnly(it.expiry_date) : '<span class="muted">—</span>'}</td>
      <td style="padding:8px;border-bottom:1px solid #eee;text-align:right">₦${Number(it.unit_price).toLocaleString("en-NG", { minimumFractionDigits: 2 })}</td>
      <td style="padding:8px;border-bottom:1px solid #eee;text-align:right;font-weight:600">₦${Number(it.line_total ?? it.quantity * it.unit_price).toLocaleString("en-NG", { minimumFractionDigits: 2 })}</td>
    </tr>`
  ).join("");

  const taxAmount = invoice.tax_amount ?? 0;
  const grandTotal = invoice.total_amount + taxAmount;
  const customerId = walkIn?.customer_code || "WALK-IN";
  const salesRep = invoice.created_by_email ? invoice.created_by_email.split("@")[0] : "—";
  const authorisedBy = invoice.finance_approved ? (invoice.finance_approver || "—") : null;
  const deliveredBy = invoice.delivered_by || null;
  const shipDate = invoice.dispatched_at ? fmtDateOnly(invoice.dispatched_at) : "Pending dispatch";
  const dueDate = invoice.due_date ? fmtDateOnly(invoice.due_date) : "—";
  const billingAddress = (invoice.billing_address || "").replace(/\n/g, "<br>");
  const shippingAddress = (invoice.shipping_address || "").replace(/\n/g, "<br>");

  win.document.write(`<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>Invoice ${invoice.invoice_number}</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Segoe UI',Arial,sans-serif;padding:40px;color:#12203A;background:#fff;font-size:13px}
  .header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:20px;gap:24px}
  .company-block img{height:44px;display:block;margin-bottom:8px}
  .company-block .name{font-size:16px;font-weight:800;color:#003A91}
  .company-block .line{font-size:11px;color:#666;line-height:1.5}
  .inv-title{font-size:28px;font-weight:800;text-align:right;background:linear-gradient(90deg,#003A91,#62C76A);-webkit-background-clip:text;background-clip:text;color:transparent}
  .inv-meta{text-align:right;font-size:12px;color:#555;margin-top:4px}
  .inv-meta strong{color:#12203A}
  .divider{height:2px;background:linear-gradient(90deg,#003A91,#62C76A);margin:16px 0;border-radius:2px}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:16px 0}
  .grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px;margin:16px 0}
  .section-label{font-size:10px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:5px}
  .field{font-size:13px;color:#12203A;margin-bottom:2px;line-height:1.5}
  .muted{color:#aaa}
  table{width:100%;border-collapse:collapse;margin:20px 0}
  th{background:#003A91;color:#fff;padding:8px;text-align:left;font-size:11px;font-weight:600;text-transform:uppercase}
  th:nth-child(1){text-align:center}
  th:nth-child(6),th:nth-child(7){text-align:right}
  tbody tr:nth-child(even){background:#F2F6FC}
  .totals{margin-left:auto;width:280px;margin-top:8px}
  .totals-row{display:flex;justify-content:space-between;padding:5px 8px;font-size:13px}
  .totals-row.grand{background:#62C76A;color:#fff;font-weight:700;font-size:15px;border-radius:6px;margin-top:4px;padding:10px 8px}
  .compliance-note{margin:20px 0;padding:12px 16px;background:#F2F6FC;border-radius:8px;border-left:4px solid #62C76A;font-size:12px;font-weight:600;color:#12203A}
  .sig-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:24px 0 16px}
  .sig-cell{font-size:11px}
  .sig-name{font-weight:600;color:#12203A;margin-bottom:22px;min-height:14px}
  .sig-line{border-top:1px solid #999;padding-top:4px;color:#888}
  .footer{margin-top:20px;padding-top:14px;border-top:1px solid #eee;font-size:10.5px;color:#999;display:flex;justify-content:space-between;gap:24px}
  .status-badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;background:#d1fae5;color:#065f46}
  @media print{body{padding:20px}button{display:none!important}.no-print{display:none!important}}
</style>
</head><body>
<div class="header">
  <div class="company-block">
    <img src="${window.location.origin}/placeware-logo.png" alt="Placeware">
    <div class="line">${COMPANY_INFO.address}<br>${COMPANY_INFO.phones.join(" · ")}<br>${COMPANY_INFO.email} · ${COMPANY_INFO.website}</div>
  </div>
  <div>
    <div class="inv-title">INVOICE</div>
    <div class="inv-meta">
      Invoice Number: <strong>${invoice.invoice_number}</strong><br>
      Invoice Date: <strong>${fmtDateOnly(invoice.created_at)}</strong><br>
      Page: <strong>1 of 1</strong>
      <div style="margin-top:6px"><span class="status-badge">${STATUS_LABELS[invoice.status]?.label ?? invoice.status}</span></div>
    </div>
  </div>
</div>
<div class="divider"></div>

<div class="grid2">
  <div>
    <div class="section-label">Bill To</div>
    <div class="field" style="font-weight:700;font-size:15px">${invoice.customer_name}</div>
    ${invoice.company_name ? `<div class="field">${invoice.company_name}</div>` : ""}
    <div class="field">${billingAddress || '<span class="muted">—</span>'}</div>
    ${walkIn?.contact_phone ? `<div class="field">📞 ${walkIn.contact_phone}</div>` : ""}
    ${walkIn?.email ? `<div class="field">✉ ${walkIn.email}</div>` : ""}
  </div>
  <div>
    <div class="section-label">Ship To</div>
    <div class="field">${shippingAddress ? shippingAddress : "Same as Bill To"}</div>
  </div>
</div>

<div class="grid3">
  <div>
    <div class="section-label">Customer ID</div>
    <div class="field">${customerId}</div>
  </div>
  <div>
    <div class="section-label">Customer PO</div>
    <div class="field">${invoice.customer_po || '<span class="muted">—</span>'}</div>
  </div>
  <div>
    <div class="section-label">Payment Terms</div>
    <div class="field">${invoice.payment_terms || "Due on Receipt"}</div>
  </div>
</div>
<div class="grid3">
  <div>
    <div class="section-label">Sales Rep</div>
    <div class="field">${salesRep}</div>
  </div>
  <div>
    <div class="section-label">Shipping Method</div>
    <div class="field">${invoice.shipping_method || '<span class="muted">—</span>'}</div>
  </div>
  <div>
    <div class="section-label">Ship Date / Due Date</div>
    <div class="field">${shipDate} / ${dueDate}</div>
  </div>
</div>

<table>
  <thead>
    <tr>
      <th>Qty</th><th>Description</th><th>Batch Number</th><th>Mfg. Date</th><th>Exp. Date</th>
      <th style="text-align:right">Unit Price</th><th style="text-align:right">Amount</th>
    </tr>
  </thead>
  <tbody>${itemRows}</tbody>
</table>

<div class="totals">
  <div class="totals-row"><span>Subtotal</span><span>${fmt(invoice.total_amount)}</span></div>
  <div class="totals-row"><span>Sales Tax</span><span>${fmt(taxAmount)}</span></div>
  <div class="totals-row"><span>Total Invoice Amount</span><span>${fmt(grandTotal)}</span></div>
  <div class="totals-row"><span>Payment/Credit Applied</span><span>₦0.00</span></div>
  <div class="totals-row grand"><span>TOTAL</span><span>${fmt(grandTotal)}</span></div>
</div>

<div class="compliance-note">Goods received in good condition with cold chain maintained. Not returnable.</div>

<div class="sig-grid">
  <div class="sig-cell"><div class="sig-name">${salesRep !== "—" ? salesRep : ""}</div><div class="sig-line">Prepared by (Name/Sign)</div></div>
  <div class="sig-cell"><div class="sig-name">${authorisedBy ?? ""}</div><div class="sig-line">Authorised by</div></div>
  <div class="sig-cell"><div class="sig-name">${deliveredBy ?? ""}</div><div class="sig-line">Delivered</div></div>
  <div class="sig-cell"><div class="sig-name">${invoice.customer_name}</div><div class="sig-line">Customer Name</div></div>
  <div class="sig-cell"><div class="sig-name">&nbsp;</div><div class="sig-line">Customer Sign</div></div>
</div>

<div class="footer">
  <div>This is a computer-generated invoice from ACE · Placeware Limited<br>NAFDAC Compliance · All transactions are subject to audit review</div>
  <div style="text-align:right">All payments should be made by cheque or transfer to:<br><strong>${COMPANY_INFO.bankPayee}</strong><br>${COMPANY_INFO.bankDetails}<br>Cash payment is not allowed.</div>
</div>

<div class="no-print" style="margin-top:24px;text-align:center">
  <button onclick="window.print()" style="background:linear-gradient(90deg,#003A91,#62C76A);color:#fff;padding:12px 32px;border:none;border-radius:8px;font-size:15px;cursor:pointer;font-weight:600">🖨️ Print / Save as PDF</button>
</div>
<script>setTimeout(()=>window.print(),400);</script>
</body></html>`);
  win.document.close();
}

// ---------------------------------------------------------------------------
// Tab: All Invoices
// ---------------------------------------------------------------------------

export function InvoicesTab() {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const [statusFilter, setStatusFilter] = useState("");
  const [searchQ,      setSearchQ]      = useState("");
  const [selected,     setSelected]     = useState<Invoice | null>(null);
  const [detailData,   setDetailData]   = useState<{ invoice: Invoice; walk_in?: WalkIn } | null>(null);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["fd-invoices", statusFilter, searchQ],
    queryFn: () => api.frontdesk.listInvoices({
      status: statusFilter || undefined,
      q:      searchQ      || undefined,
      // Bumped to the backend's hard max (default was unset -> server default
      // 100). The KPI strip below is derived from this same array, so it
      // needs to see as close to "all matching rows" as the API allows —
      // same reasoning as ar_receipts.py's list endpoint's summary block.
      limit: 500,
    }),
    staleTime: 15_000,
  });

  const invoices: Invoice[] = (data as any)?.invoices ?? [];

  const kpis = useMemo(() => ({
    total: invoices.length,
    totalValue: invoices.reduce((sum, inv) => sum + (inv.total_amount || 0), 0),
    pendingQc: invoices.filter((inv) => inv.status === "qc_pending").length,
    pendingFinance: invoices.filter((inv) => inv.status === "finance_pending").length,
  }), [invoices]);

  async function openDetail(inv: Invoice) {
    setSelected(inv);
    try {
      const detail = await api.frontdesk.getInvoice(inv.id) as any;
      setDetailData(detail);
    } catch {
      setDetailData({ invoice: inv });
    }
  }

  // Realtime — this is what makes the queue "light up" for a QC/Finance/Ops
  // user without them having to poll: any transition anywhere refreshes the
  // list (and KPI strip, since it's derived from the same array) and, if the
  // currently-open detail happens to be the invoice that changed, refreshes
  // that too. See ACE-Workspace-Standard.md Ch.7 — realtime is opt-in per
  // feature; this is exactly the "shared queue multiple staff act on
  // concurrently" case that chapter calls out as justified.
  useRealtimeChannel("frontdesk_updates", (msg: any) => {
    queryClient.invalidateQueries({ queryKey: ["fd-invoices"] });
    if (selected && msg?.invoice_id === selected.id) {
      openDetail(selected);
    }
  });

  // Radix Select throws on <SelectItem value="">, so the "no filter" state
  // is represented as "" here — FilterBar owns the "__all__" sentinel
  // translation internally now, so this list no longer needs its own "all" row.
  const STATUS_FILTERS = [
    { value: "qc_pending",       label: "Pending QC"      },
    { value: "finance_pending",  label: "Pending Finance" },
    { value: "finance_approved", label: "Approved"        },
    { value: "dispatched",       label: "Dispatched"      },
    { value: "completed",        label: "Completed"       },
    { value: "cancelled",        label: "Cancelled"       },
  ];

  return (
    <div className="space-y-4">
      <KpiStrip
        items={[
          { label: "Total Invoices", value: kpis.total },
          { label: "Total Value", value: fmt(kpis.totalValue), tone: "success" },
          { label: "Pending QC", value: kpis.pendingQc, tone: "warning" },
          { label: "Pending Finance", value: kpis.pendingFinance, tone: "warning" },
        ]}
      />

      <FilterBar
        search={{ value: searchQ, onChange: setSearchQ, placeholder: "Search client name…" }}
        selects={[
          {
            label: "status",
            value: statusFilter,
            onChange: setStatusFilter,
            placeholder: "All Statuses",
            options: STATUS_FILTERS,
          },
        ]}
      />

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr_240px] gap-4">
        {/* List / Queue Panel */}
        <Card className="lg:max-h-[600px] flex flex-col">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Invoices</CardTitle>
          </CardHeader>
          <CardContent className="overflow-y-auto space-y-2 flex-1">
            {isLoading ? (
              <div className="flex items-center justify-center py-12 text-muted-foreground gap-2">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading invoices…
              </div>
            ) : invoices.length === 0 ? (
              <div className="text-center py-12 text-muted-foreground text-sm border rounded-lg">No invoices found.</div>
            ) : (
              invoices.map((inv) => (
                <button
                  key={inv.id}
                  onClick={() => openDetail(inv)}
                  className={`w-full text-left rounded-lg border bg-card px-4 py-3 hover:bg-muted/40 transition-colors space-y-1 ${
                    selected?.id === inv.id ? "border-primary bg-muted/40" : ""
                  }`}
                >
                  {/* Every line gets its own full-width row and `truncate` --
                      the old single-row layout shared width with a shrink-0
                      amount/badge/icon cluster, which left almost nothing
                      for the invoice number/name and made this row's own
                      global overflow-wrap:anywhere base style (global.css)
                      break long text one character per line instead of
                      overflowing cleanly. */}
                  <div className="flex items-center justify-between gap-2 min-w-0">
                    <span className="font-mono text-xs text-muted-foreground truncate min-w-0">{inv.invoice_number}</span>
                    <div className="flex items-center gap-1.5 flex-shrink-0">
                      <StatusPill status={inv.status} />
                      <Eye className="h-3.5 w-3.5 text-muted-foreground" />
                    </div>
                  </div>
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="font-semibold text-sm truncate">{inv.customer_name}</span>
                    {inv.company_name && <span className="text-xs text-muted-foreground hidden sm:inline truncate">· {inv.company_name}</span>}
                  </div>
                  <div className="flex items-center justify-between gap-2 min-w-0">
                    <span className="text-xs text-muted-foreground truncate">{fmtDate(inv.created_at)}</span>
                    <span className="font-bold font-mono text-sm flex-shrink-0">{fmt(inv.total_amount)}</span>
                  </div>
                </button>
              ))
            )}
          </CardContent>
        </Card>

        {/* Detail Workspace — inline (replaces the old hand-rolled slide-in
            drawer). Per ACE-Workspace-Standard.md Ch.5/Ch.3: a persistent,
            selected record has no reason to be dismissible — there is
            intentionally no close button here, matching ARReceipts.tsx. */}
        <Card>
          <CardContent className="pt-6">
            {!selected && (
              <p className="text-sm text-muted-foreground text-center py-12">Select an invoice to view details.</p>
            )}
            {selected && !detailData && (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            )}
            {selected && detailData && (() => {
              const inv = detailData.invoice;
              const wi  = detailData.walk_in;
              return (
                <div className="space-y-4 text-sm">
                  <div className="grid grid-cols-2 gap-2">
                    <div className="space-y-0.5">
                      <div className="text-xs text-muted-foreground">Invoice #</div>
                      <div className="font-mono font-bold">{inv.invoice_number}</div>
                    </div>
                    <div className="space-y-0.5">
                      <div className="text-xs text-muted-foreground">Status</div>
                      <StatusPill status={inv.status} />
                    </div>
                    <div className="space-y-0.5">
                      <div className="text-xs text-muted-foreground">Client</div>
                      <div className="font-semibold">{inv.customer_name}</div>
                    </div>
                    {inv.company_name && (
                      <div className="space-y-0.5">
                        <div className="text-xs text-muted-foreground">Company</div>
                        <div>{inv.company_name}</div>
                      </div>
                    )}
                    <div className="space-y-0.5">
                      <div className="text-xs text-muted-foreground">Payment</div>
                      <div className="capitalize">{inv.payment_method}</div>
                    </div>
                    <div className="space-y-0.5">
                      <div className="text-xs text-muted-foreground">Date</div>
                      <div>{fmtDate(inv.created_at)}</div>
                    </div>
                  </div>

                  <Separator />

                  <div>
                    <div className="text-xs font-semibold text-muted-foreground mb-2">LINE ITEMS</div>
                    <div className="space-y-1">
                      {inv.items.map((it, i) => (
                        <div key={i} className="flex justify-between bg-muted/40 rounded px-3 py-1.5">
                          <span>{it.product} × {it.quantity}</span>
                          <span className="font-semibold">{fmt(it.line_total ?? it.quantity * it.unit_price)}</span>
                        </div>
                      ))}
                      <div className="flex justify-between font-bold px-3 py-2 border-t mt-1">
                        <span>Total</span>
                        <span className="text-green-600 dark:text-green-300">{fmt(inv.total_amount)}</span>
                      </div>
                    </div>
                  </div>

                  {inv.qc_passed != null && (
                    <div className="flex gap-2 flex-wrap">
                      <Badge variant={inv.qc_passed ? "default" : "destructive"}>
                        QC: {inv.qc_passed ? "Passed" : "Failed"}
                      </Badge>
                      {inv.finance_approved != null && (
                        <Badge variant={inv.finance_approved ? "default" : "destructive"}>
                          Finance: {inv.finance_approved ? "Approved" : "Rejected"}
                        </Badge>
                      )}
                    </div>
                  )}

                  {/* Role-aware action panel — a different logged-in QC/Finance/Ops
                      user can act on this invoice from here, without needing the
                      original wizard session. Shared with the Centralized Customer
                      Workspace so the QC/Finance/Delivery mutation logic isn't
                      duplicated (ACE-Workspace-Standard.md Ch.10). Role gates live
                      server-side and are mirrored client-side in this panel, so a
                      viewer without QC/Finance/Dispatch permissions sees the
                      invoice here but not the action buttons. */}
                  <InvoiceActionPanel
                    invoice={inv}
                    onActioned={() => {
                      queryClient.invalidateQueries({ queryKey: ["fd-invoices"] });
                      if (selected) openDetail(selected);
                    }}
                  />

                  <Button className="w-full gap-2" onClick={() => printInvoice(inv, wi)}>
                    <Download className="h-4 w-4" /> Print / Save as PDF
                  </Button>
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
            <Button variant="outline" className="w-full" onClick={() => refetch()}>
              <RefreshCw className="h-4 w-4 mr-1" /> Refresh
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
