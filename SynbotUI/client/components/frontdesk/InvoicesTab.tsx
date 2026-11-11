import { useState, useMemo, useEffect } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/components/AuthProvider";
import { ClearVoidedButton } from "@/components/books/kit";
import { useClearVoided } from "@/lib/voided";
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
import { invoiceTotal } from "@/lib/invoice-total";

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
  // Resolved from the inventory catalogue when the product is picked from
  // autocomplete. Dispatch uses it to deduct the right stock; without it the
  // backend can only fall back to an exact name match.
  sku?: string;
  batch_number?: string;
  pack_batch_number?: string;
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
  delivery_charge?: number;
  discount_amount?: number;
  created_by_email?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  arrived:           { label: "Arrived",          color: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300" },
  invoiced:          { label: "Invoiced",          color: "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300" },
  // no QC stage since 6 Nov: an older request still in these states is waiting for Finance
  qc_pending:        { label: "Pending Finance",   color: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300" },
  qc_passed:         { label: "Pending Finance",   color: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300" },
  qc_failed:         { label: "Pending Finance",   color: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300" },
  finance_pending:   { label: "Pending Finance",   color: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300" },
  finance_approved:  { label: "Finance Approved",  color: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300" },
  finance_rejected:  { label: "Finance Rejected",  color: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300" },
  completed:         { label: "Completed",         color: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300" },
  cancelled:         { label: "Voided",            color: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400" },
  // the Invoice register's own statuses, for invoices not raised on Frontdesk
  VOID:              { label: "Voided",            color: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400" },
  OPEN:              { label: "Open",              color: "bg-sky-100 text-sky-800 dark:bg-sky-500/15 dark:text-sky-300" },
  POSTED:            { label: "Open",              color: "bg-sky-100 text-sky-800 dark:bg-sky-500/15 dark:text-sky-300" },
  PARTIALLY_PAID:    { label: "Part paid",         color: "bg-sky-100 text-sky-800 dark:bg-sky-500/15 dark:text-sky-300" },
  PAID:              { label: "Paid",              color: "bg-green-100 text-green-800 dark:bg-green-500/15 dark:text-green-300" },
  CREDIT:            { label: "Credit memo",       color: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400" },
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
  address: "64, Aina Street, Ojodu, Lagos",
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

/** Text from the database, safe to put inside the print window's HTML (a customer name or address
 *  containing markup must print as text, never run as script in the app's origin). */
const esc = (v: unknown): string =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string);

/** The batch number printed on an invoice line: the number on the pack. Sage's lot letters (E, P, Z ii)
 *  only tell lots apart and are never a batch number, so they print as blank. */
export function printableBatch(it: { pack_batch_number?: string | null; batch_number?: string | null }): string {
  if (it.pack_batch_number) return it.pack_batch_number;
  const b = (it.batch_number ?? "").trim();
  return !b || b.toUpperCase() === "SAGE" || /^[A-Z]{1,3}( ?[ivxlc]+)?$/i.test(b) ? "" : b;
}

export function printInvoice(invoice: Invoice, walkIn?: WalkIn | null, target?: Window | null) {
  // Every invoice prints from the one ACE Books invoice layout (client, 28 Oct) - Frontdesk invoices included.
  const url = `${window.location.origin}${window.location.pathname}#/finance/books/invoice-print/frontdesk/${encodeURIComponent(invoice.id)}?print=1`;
  if (target) { target.location.href = url; return; }
  window.open(url, "_blank");
  return;
}

/** The previous Frontdesk paper layout (kept for reference; not used). */
export function printInvoiceLegacy(invoice: Invoice, walkIn?: WalkIn | null, target?: Window | null) {
  const win = target ?? window.open("", "_blank", "width=1000,height=800");
  if (!win) return;

  const itemRows = invoice.items.map((it) => `
    <tr>
      <td style="padding:5px 7px;border-bottom:1px solid #eee;text-align:center">${esc(it.quantity)}</td>
      <td style="padding:5px 7px;border-bottom:1px solid #eee">${esc(it.product)}</td>
      <td style="padding:5px 7px;border-bottom:1px solid #eee;font-family:monospace;font-size:11px">${printableBatch(it) ? esc(printableBatch(it)) : '<span class="muted">—</span>'}</td>
      <td style="padding:5px 7px;border-bottom:1px solid #eee;font-size:11px">${it.manufacture_date ? esc(fmtMonthYear(it.manufacture_date)) : '<span class="muted">—</span>'}</td>
      <td style="padding:5px 7px;border-bottom:1px solid #eee;font-size:11px">${it.expiry_date ? esc(fmtDateOnly(it.expiry_date)) : '<span class="muted">—</span>'}</td>
      <td style="padding:5px 7px;border-bottom:1px solid #eee;text-align:right">₦${Number(it.unit_price).toLocaleString("en-NG", { minimumFractionDigits: 2 })}</td>
      <td style="padding:5px 7px;border-bottom:1px solid #eee;text-align:right;font-weight:600">₦${Number(it.line_total ?? it.quantity * it.unit_price).toLocaleString("en-NG", { minimumFractionDigits: 2 })}</td>
    </tr>`
  ).join("");

  const taxAmount = Number(invoice.tax_amount ?? 0);
  const deliveryCharge = Number(invoice.delivery_charge ?? 0);
  const discountAmount = Number(invoice.discount_amount ?? 0);
  const grandTotal = invoiceTotal(invoice);
  const customerId = walkIn?.customer_code || "WALK-IN";
  // the person who raised (prepared) the invoice: their HR name, else their login
  const salesRep = (invoice as any).created_by_name || (invoice.created_by_email ? invoice.created_by_email.split("@")[0] : "—");
  const authorisedBy = invoice.finance_approved ? (invoice.finance_approver || "—") : null;
  const deliveredBy = invoice.delivered_by || null;
  const shipDate = invoice.dispatched_at ? fmtDateOnly(invoice.dispatched_at) : "Pending dispatch";
  const dueDate = invoice.due_date ? fmtDateOnly(invoice.due_date) : "—";
  const billingAddress = esc(invoice.billing_address).replace(/\n/g, "<br>");
  const shippingAddress = esc(invoice.shipping_address).replace(/\n/g, "<br>");

  win.document.write(`<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>Invoice ${esc(invoice.invoice_number)}</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Segoe UI',Arial,sans-serif;padding:28px;color:#12203A;background:#fff;font-size:12px}
  .header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;gap:24px}
  .company-block img{height:44px;display:block;margin-bottom:8px}
  .company-block .name{font-size:16px;font-weight:800;color:#003A91}
  .company-block .line{font-size:11px;color:#666;line-height:1.5}
  .inv-title{font-size:28px;font-weight:800;text-align:right;background:linear-gradient(90deg,#003A91,#62C76A);-webkit-background-clip:text;background-clip:text;color:transparent}
  .inv-meta{text-align:right;font-size:12px;color:#555;margin-top:4px}
  .inv-meta strong{color:#12203A}
  .divider{height:2px;background:linear-gradient(90deg,#003A91,#62C76A);margin:8px 0;border-radius:2px}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:16px 0}
  .grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px;margin:16px 0}
  .section-label{font-size:10px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:5px}
  .field{font-size:13px;color:#12203A;margin-bottom:2px;line-height:1.5}
  .muted{color:#aaa}
  .boxes{display:grid;grid-template-columns:1fr 1fr;gap:28px;margin:10px 0}
  .box{border:1px solid #8A96A8;min-height:92px}
  .box-h{background:#E3E8F0;border-bottom:1px solid #8A96A8;padding:4px 8px;font-weight:700;font-size:12px}
  .box-b{padding:6px 8px;line-height:1.5;font-size:12.5px}
  table.meta{width:100%;border-collapse:collapse;margin:10px 0 18px;text-align:center}
  table.meta td{border:1px solid #8A96A8!important;padding:5px 8px;font-size:12px}
  table.meta tr.mh td{background:#E3E8F0;font-weight:700;color:#12203A}
  table{width:100%;border-collapse:collapse;margin:0 0 12px;border:1px solid #8A96A8}
  th{background:#003A91;color:#fff;padding:8px;text-align:left;font-size:11px;font-weight:600;text-transform:uppercase;border:1px solid #8A96A8}
  td{border:1px solid #8A96A8!important}
  .totals{border:1px solid #8A96A8}
  .totals-row{border-bottom:1px solid #D5DBE5}
  th:nth-child(1){text-align:center}
  th:nth-child(6),th:nth-child(7){text-align:right}
  tbody tr:nth-child(even){background:#F2F6FC}
  .totals{margin-left:auto;width:280px;margin-top:8px}
  .totals-row{display:flex;justify-content:space-between;padding:5px 8px;font-size:13px}
  .totals-row.grand{background:#62C76A;color:#fff;font-weight:700;font-size:15px;border-radius:6px;margin-top:4px;padding:10px 8px}
  .compliance-note{margin:12px 0;padding:8px 14px;background:#F2F6FC;border-radius:8px;border-left:4px solid #62C76A;font-size:12px;font-weight:600;color:#12203A}
  .sig-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:14px 0 10px}
  .sig-cell{font-size:11px}
  .sig-name{font-weight:600;color:#12203A;margin-bottom:22px;min-height:14px}
  .sig-line{border-top:1px solid #999;padding-top:4px;color:#888}
  .footer{margin-top:10px;padding-top:8px;border-top:1px solid #eee;font-size:10.5px;color:#999;display:flex;justify-content:space-between;gap:24px}
  .status-badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;background:#d1fae5;color:#065f46}
  @page{size:A4;margin:0}
  @media print{body{padding:10mm;font-size:11px;-webkit-box-decoration-break:clone;box-decoration-break:clone}button{display:none!important}.no-print{display:none!important}.totals,.sig-grid,.footer{break-inside:avoid}}
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
      Invoice Number: <strong>${esc(invoice.invoice_number)}</strong><br>
      Invoice Date: <strong>${fmtDateOnly(invoice.created_at)}</strong><br>
      Page: <strong>1 of 1</strong>
      <div style="margin-top:6px"><span class="status-badge">${esc(STATUS_LABELS[invoice.status]?.label ?? invoice.status)}</span></div>
    </div>
  </div>
</div>
<div class="divider"></div>

<div class="boxes">
  <div class="box"><div class="box-h">Bill To:</div><div class="box-b">
    <div style="font-weight:700">${esc(invoice.company_name || invoice.customer_name)}</div>
    <div>${billingAddress || ""}</div>
    ${walkIn?.contact_phone ? `<div>${esc(walkIn.contact_phone)}</div>` : ""}
    ${walkIn?.email ? `<div>${esc(walkIn.email)}</div>` : ""}
  </div></div>
  <div class="box"><div class="box-h">Ship to:</div><div class="box-b">
    <div style="font-weight:700">${esc(invoice.company_name || invoice.customer_name)}</div>
    <div>${shippingAddress || billingAddress || ""}</div>
  </div></div>
</div>

<table class="meta">
  <tr class="mh"><td>Customer ID</td><td>Customer PO</td><td colspan="2">Payment Terms</td></tr>
  <tr><td>${esc(customerId)}</td><td>${invoice.customer_po ? esc(invoice.customer_po) : ""}</td><td colspan="2">${esc(invoice.payment_terms || "Due on Receipt")}</td></tr>
  <tr class="mh"><td>Prepared by</td><td>Shipping Method</td><td>Ship Date</td><td>Due Date</td></tr>
  <tr><td>${esc(salesRep)}</td><td>${invoice.shipping_method ? esc(invoice.shipping_method) : ""}</td><td>${shipDate}</td><td>${dueDate}</td></tr>
</table>

<table>
  <thead>
    <tr>
      <th>Qty</th><th>Description</th><th>Batch Number</th><th>Mfg. Date</th><th>Exp. Date</th>
      <th style="text-align:right">Unit Price</th><th style="text-align:right">Amount</th>
    </tr>
  </thead>
  <tbody>${itemRows}${Array.from({ length: Math.max(0, 6 - invoice.items.length) }).map(() => `<tr>${'<td style="height:18px;padding:0"></td>'.repeat(7)}</tr>`).join("")}</tbody>
</table>

<div class="totals">
  <div class="totals-row"><span>Subtotal</span><span>${fmt(invoice.total_amount)}</span></div>
  ${discountAmount > 0 ? `<div class="totals-row"><span>Discount Allowed</span><span>-${fmt(discountAmount)}</span></div>` : ""}
  ${deliveryCharge > 0 ? `<div class="totals-row"><span>Delivery Charge</span><span>${fmt(deliveryCharge)}</span></div>` : ""}
  <div class="totals-row"><span>Sales Tax</span><span>${fmt(taxAmount)}</span></div>
  <div class="totals-row"><span>Total Invoice Amount</span><span>${fmt(grandTotal)}</span></div>
  <div class="totals-row"><span>Payment/Credit Applied</span><span>₦0.00</span></div>
  <div class="totals-row grand"><span>TOTAL</span><span>${fmt(grandTotal)}</span></div>
</div>

<div class="compliance-note">Goods received in good condition with cold chain maintained. Not returnable.</div>

<div class="sig-grid">
  <div class="sig-cell"><div class="sig-name">${salesRep !== "—" ? esc(salesRep) : ""}</div><div class="sig-line">Prepared by (Name/Sign)</div></div>
  <div class="sig-cell"><div class="sig-name">${esc(authorisedBy)}</div><div class="sig-line">Authorised by</div></div>
  <div class="sig-cell"><div class="sig-name">${esc(deliveredBy)}</div><div class="sig-line">Delivered</div></div>
  <div class="sig-cell"><div class="sig-name">&nbsp;</div><div class="sig-line">Received by (Name)</div></div>
  <div class="sig-cell"><div class="sig-name">&nbsp;</div><div class="sig-line">Received by (Sign)</div></div>
</div>

<div class="footer">
  <div>This is a computer-generated invoice from ACE · Placeware Limited<br>NAFDAC Compliance · All transactions are subject to audit review</div>
  <div style="text-align:right">All payments should be made by cheque or transfer to:<br><strong>${COMPANY_INFO.bankPayee}</strong><br>${COMPANY_INFO.bankDetails}<br>Cash payment is not allowed.</div>
</div>

<div class="no-print" style="margin-top:24px;text-align:center">
  <button id="print-btn" style="background:linear-gradient(90deg,#003A91,#62C76A);color:#fff;padding:12px 32px;border:none;border-radius:8px;font-size:15px;cursor:pointer;font-weight:600">🖨️ Print / Save as PDF</button>
</div>
</body></html>`);
  win.document.close();
  // wired from here, not inline in the popup: the Content-Security-Policy blocks inline scripts
  win.document.getElementById("print-btn")?.addEventListener("click", () => win.print());
  setTimeout(() => win.print(), 400);
}

// ---------------------------------------------------------------------------
// Tab: All Invoices
// ---------------------------------------------------------------------------

const fmtDay = (d?: string | null) => (d ? new Date(`${String(d).slice(0, 10)}T12:00:00`).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "");

/** An invoice raised in Sage or in ACE Books itself: what was sold and what is owed, read-only. Changing it
 *  (Add items, Return / remove items, Void, Record receipt) is done in ACE Books, by Finance. */
function BookedInvoice({ row }: { row: any }) {
  const { roles } = useAuth();
  const canOpen = roles.some((r: string) => ["admin", "finance", "management", "sales"].includes(r));
  const { data, isLoading, error } = useQuery({
    queryKey: ["fd-invoices", "booked", row.invoice_id, row.number],
    queryFn: () => api.frontdesk.bookedInvoice({ invoice_id: row.invoice_id, number: row.number }),
  });
  if (isLoading) return <div className="flex items-center justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>;
  if (error || !data) return <p className="text-sm text-red-600">{(error as any)?.message ?? "Invoice not found"}</p>;
  const lines: any[] = data.lines ?? [];
  return (
    <div className="space-y-4 text-sm">
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-0.5"><div className="text-xs text-muted-foreground">Invoice #</div><div className="font-mono font-bold">{row.number}</div></div>
        <div className="space-y-0.5"><div className="text-xs text-muted-foreground">Status</div><StatusPill status={row.status} /></div>
        <div className="space-y-0.5"><div className="text-xs text-muted-foreground">Customer</div><div className="font-medium">{row.customer}</div></div>
        <div className="space-y-0.5"><div className="text-xs text-muted-foreground">Date · raised in</div><div>{fmtDay(row.date)} · {data.raised_in}</div></div>
      </div>
      <div className="space-y-1 rounded-lg border p-3">
        {lines.length === 0 && <p className="text-xs text-muted-foreground">Sage's item lines for this invoice are not loaded.</p>}
        {lines.map((l, i) => (
          <div key={i} className="flex items-start justify-between gap-3 border-b py-1 last:border-0">
            <div className="min-w-0"><div className="truncate font-medium">{l.description}</div>
              <div className="text-xs text-muted-foreground">{l.quantity != null ? `${Number(l.quantity)} × ${fmt(Number(l.unit_price ?? 0))}` : ""}{l.batch ? ` · batch ${l.batch}` : ""}{l.expiry ? ` · exp ${fmtDay(l.expiry)}` : ""}</div></div>
            <span className="flex-shrink-0 font-mono">{fmt(Number(l.amount ?? 0))}</span>
          </div>
        ))}
      </div>
      <div className="flex justify-between font-semibold"><span>Total</span><span className="font-mono">{fmt(Number(row.amount ?? 0))}</span></div>
      <div className="flex justify-between"><span>Still owing</span><span className="font-mono">{fmt(Number(row.balance ?? 0))}</span></div>
      <p className="rounded-md border bg-muted/30 p-2 text-xs">Raised in {data.raised_in}. Finance changes it in ACE Books → Invoice register (Add items, Return / remove items, Void, Record receipt).</p>
      {canOpen && <Button variant="outline" className="w-full" asChild><Link to={`/finance/books/sales?tab=register`}>Open the Invoice register</Link></Button>}
    </div>
  );
}

/** `openInvoiceId`: open this invoice's detail as soon as it is set (e.g. one
 *  just raised from Frontdesk's New Invoice sheet); `onOpened` clears it. */
export function InvoicesTab({ openInvoiceId, onOpened }: { openInvoiceId?: string | null; onOpened?: () => void } = {}) {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const [statusFilter, setStatusFilter] = useState("");
  const [searchQ,      setSearchQ]      = useState("");
  const [period,       setPeriod]       = useState("");
  const [shown,        setShown]        = useState(20);
  const [booked,       setBooked]       = useState<any | null>(null);
  const [selected,     setSelected]     = useState<Invoice | null>(null);
  const [detailData,   setDetailData]   = useState<{ invoice: Invoice; walk_in?: WalkIn } | null>(null);

  const days = Number(period) || 30;
  // A working list: voided invoices stay out until someone asks to see them (remembered on this computer). Nothing is deleted.
  const vd = useClearVoided("frontdesk.all-invoices", [], true);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["fd-invoices", statusFilter, searchQ, days, shown, vd.cleared],
    // The Invoice register's own list (Sage's, ACE Books' and Frontdesk's): what is waiting for QC or
    // Finance first, whatever day it was raised, then the most recent. A search looks back two years.
    queryFn: () => api.frontdesk.recentInvoices({
      days, limit: shown, status: statusFilter || undefined, q: searchQ || undefined, include_void: !vd.cleared,
    }),
    staleTime: 15_000,
  });

  const rows: any[] = (data as any)?.rows ?? [];
  const sum = (data as any)?.summary ?? {};
  const periodLabel = days === 365 ? "last 12 months" : `last ${days} days`;

  function openRow(r: any) {
    if (r.frontdesk_id) { setBooked(null); openDetail({ id: r.frontdesk_id } as Invoice); }
    else { setSelected(null); setDetailData(null); setBooked(r); }
  }

  async function openDetail(inv: Invoice) {
    setSelected(inv);
    try {
      const detail = await api.frontdesk.getInvoice(inv.id) as any;
      setDetailData(detail);
    } catch {
      setDetailData({ invoice: inv });
    }
  }

  useEffect(() => {
    if (!openInvoiceId) return;
    queryClient.invalidateQueries({ queryKey: ["fd-invoices"] });
    openDetail({ id: openInvoiceId } as Invoice);
    onOpened?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openInvoiceId]);

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
    { value: "awaiting_finance", label: "Pending Finance" },
    { value: "open",             label: "Open (owing)"    },
    { value: "paid",             label: "Paid"            },
    { value: "credit",           label: "Credit memos"    },
    { value: "not_posted",       label: "Approved, not posted" },
    { value: "void",             label: "Voided"          },
  ];

  return (
    <div className="space-y-4">
      <KpiStrip
        items={[
          { label: `Invoices, ${periodLabel}`, value: sum.invoices ?? 0 },
          { label: `Value, ${periodLabel}`, value: fmt(Number(sum.total ?? 0)), tone: "success" },
          { label: "Pending Finance", value: sum.pending_finance ?? 0, tone: "warning" },
        ]}
      />

      <FilterBar
        search={{ value: searchQ, onChange: (v: string) => { setSearchQ(v); setShown(20); }, placeholder: "Invoice no. or client…" }}
        selects={[
          {
            label: "status",
            value: statusFilter,
            onChange: (v: string) => { setStatusFilter(v); setShown(20); },
            placeholder: "All Statuses",
            options: STATUS_FILTERS,
          },
          {
            label: "period",
            value: period,
            onChange: (v: string) => { setPeriod(v); setShown(20); },
            placeholder: "Last 30 days",
            options: [{ value: "7", label: "Last 7 days" }, { value: "90", label: "Last 90 days" }, { value: "365", label: "Last 12 months" }],
          },
        ]}
      />

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr_240px] gap-4">
        {/* List / Queue Panel */}
        <Card className="lg:max-h-[600px] flex flex-col">
          <CardHeader className="space-y-1 pb-2">
            <div className="flex items-center justify-between gap-2">
              <CardTitle className="text-sm">Invoices</CardTitle>
              {statusFilter !== "void" && <ClearVoidedButton cleared={vd.cleared} count={sum.voided ?? 0} onToggle={vd.toggle} />}
            </div>
            <p className="text-[11px] text-muted-foreground">Waiting first, then the most recent{(data as any)?.count != null ? ` · ${rows.length} of ${(data as any).count}` : ""}</p>
          </CardHeader>
          <CardContent className="overflow-y-auto space-y-2 flex-1">
            {isLoading ? (
              <div className="flex items-center justify-center py-12 text-muted-foreground gap-2">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading invoices…
              </div>
            ) : rows.length === 0 ? (
              <div className="text-center py-12 text-muted-foreground text-sm border rounded-lg">No invoices found.</div>
            ) : (
              rows.map((inv) => (
                <button
                  key={`${inv.source}:${inv.number}:${inv.invoice_id ?? inv.frontdesk_id ?? ""}`}
                  data-tour-row
                  onClick={() => openRow(inv)}
                  className={`w-full text-left rounded-lg border bg-card px-4 py-3 hover:bg-muted/40 transition-colors space-y-1 ${
                    (inv.frontdesk_id && selected?.id === inv.frontdesk_id) || (booked && booked === inv) ? "border-primary bg-muted/40" : ""
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
                    <span className="font-mono text-xs text-muted-foreground truncate min-w-0">{inv.number}</span>
                    <div className="flex items-center gap-1.5 flex-shrink-0">
                      <StatusPill status={inv.frontdesk_status ?? inv.status} />
                      <Eye className="h-3.5 w-3.5 text-muted-foreground" />
                    </div>
                  </div>
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="font-semibold text-sm truncate">{inv.customer}</span>
                  </div>
                  <div className="flex items-center justify-between gap-2 min-w-0">
                    <span className="text-xs text-muted-foreground truncate">{fmtDay(inv.date)} · {inv.source === "sage" ? "Sage" : inv.source === "frontdesk" ? "Frontdesk" : "ACE Books"}</span>
                    <span className="font-bold font-mono text-sm flex-shrink-0">{fmt(Number(inv.amount ?? 0))}</span>
                  </div>
                </button>
              ))
            )}
            {rows.length < ((data as any)?.count ?? 0) && (
              <Button variant="outline" size="sm" className="w-full" onClick={() => setShown(shown + 20)}>Show 20 more</Button>
            )}
          </CardContent>
        </Card>

        {/* Detail Workspace — inline (replaces the old hand-rolled slide-in
            drawer). Per ACE-Workspace-Standard.md Ch.5/Ch.3: a persistent,
            selected record has no reason to be dismissible — there is
            intentionally no close button here, matching ARReceipts.tsx. */}
        <Card>
          <CardContent className="pt-6">
            {!selected && !booked && (
              <p className="text-sm text-muted-foreground text-center py-12">Select an invoice to view details.</p>
            )}
            {booked && <BookedInvoice row={booked} />}
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
                      {Number(inv.discount_amount ?? 0) > 0 && (
                        <div className="flex justify-between rounded px-3 py-1.5 text-muted-foreground">
                          <span>Discount allowed</span><span className="font-semibold">−{fmt(Number(inv.discount_amount))}</span>
                        </div>)}
                      {Number(inv.delivery_charge ?? 0) > 0 && (
                        <div className="flex justify-between rounded px-3 py-1.5 text-muted-foreground">
                          <span>Delivery charge</span><span className="font-semibold">{fmt(Number(inv.delivery_charge))}</span>
                        </div>)}
                      {Number(inv.tax_amount ?? 0) > 0 && (
                        <div className="flex justify-between rounded px-3 py-1.5 text-muted-foreground">
                          <span>Sales tax</span><span className="font-semibold">{fmt(Number(inv.tax_amount))}</span>
                        </div>)}
                      <div className="flex justify-between font-bold px-3 py-2 border-t mt-1">
                        <span>Total</span>
                        <span className="text-green-600 dark:text-green-300">{fmt(invoiceTotal(inv))}</span>
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
                    showPrint={false}
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
