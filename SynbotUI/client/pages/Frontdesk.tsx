import { useState, useCallback, useRef, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  UserPlus, ClipboardList, CheckCircle2, DollarSign, Bell,
  Loader2, Plus, Trash2, Search, Download, RefreshCw,
  Building2, Phone, Mail, Calendar, PackageSearch,
  TrendingUp, Clock, ChevronRight, X, Eye, History,
  AlertTriangle, CheckCheck, BarChart3, Users, FileText,
  Boxes, Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
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
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api-client";
import { motion } from "framer-motion";
import { motionVariants, motionTransitions } from "@/lib/motion";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { FilterBar } from "@/components/workspace/FilterBar";
import { InvoiceActionPanel } from "@/components/workspace/InvoiceActionPanel";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface WalkIn {
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

interface InvoiceItem {
  product: string;
  quantity: number;
  unit_price: number;
  line_total?: number;
  batch_number?: string;
  manufacture_date?: string;
  expiry_date?: string;
}

interface Invoice {
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

interface StockResult {
  product: string;
  sku?: string;
  name?: string;
  quantity?: number;
  status: "in_stock" | "low_stock" | "out_of_stock" | "unknown";
  unit_cost?: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
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

function StatusPill({ status }: { status: string }) {
  const s = STATUS_LABELS[status] ?? { label: status, color: "bg-gray-100 text-gray-600 dark:bg-gray-500/15 dark:text-gray-300" };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${s.color}`}>
      {s.label}
    </span>
  );
}

function fmt(n: number) {
  return "₦" + n.toLocaleString("en-NG", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtDate(iso: string) {
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

function printInvoice(invoice: Invoice, walkIn?: WalkIn | null) {
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
// Step Indicator
// ---------------------------------------------------------------------------

const WIZARD_STEPS = [
  { label: "Walk-in", icon: UserPlus },
  { label: "Invoice", icon: ClipboardList },
  { label: "QC",      icon: CheckCircle2 },
  { label: "Finance", icon: DollarSign },
];

function StepIndicator({ current }: { current: number }) {
  return (
    <div className="flex items-center gap-0 mb-6">
      {WIZARD_STEPS.map((step, i) => {
        const Icon = step.icon;
        const done = i < current;
        const active = i === current;
        return (
          <div key={step.label} className="flex items-center flex-1 last:flex-none">
            <div className="flex flex-col items-center">
              <div className={`w-9 h-9 rounded-full flex items-center justify-center border-2 transition-colors ${
                done   ? "border-green-500 bg-green-500 text-white"
                : active ? "border-primary bg-primary text-primary-foreground"
                : "border-muted bg-muted text-muted-foreground"
              }`}>
                <Icon className="h-4 w-4" />
              </div>
              <span className={`text-xs mt-1 font-medium ${active ? "text-primary" : done ? "text-green-600 dark:text-green-400" : "text-muted-foreground"}`}>
                {step.label}
              </span>
            </div>
            {i < WIZARD_STEPS.length - 1 && (
              <div className={`h-0.5 flex-1 mx-1 mb-4 rounded ${done ? "bg-green-500" : "bg-muted"}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Client Search (returning client lookup)
// ---------------------------------------------------------------------------

function ClientSearch({ onSelect }: { onSelect: (client: WalkIn) => void }) {
  const [q, setQ] = useState("");
  const { data, isFetching } = useQuery({
    queryKey: ["frontdesk-client-search", q],
    queryFn: () => api.frontdesk.searchClients(q),
    enabled: q.trim().length >= 2,
    staleTime: 10_000,
  });

  const clients: WalkIn[] = (data as any)?.clients ?? [];

  return (
    <div className="space-y-2">
      <div className="relative">
        <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input
          className="pl-9"
          placeholder="Search by name, company, or phone…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        {isFetching && <Loader2 className="absolute right-3 top-2.5 h-4 w-4 animate-spin text-muted-foreground" />}
      </div>
      {clients.length > 0 && (
        <div className="border rounded-lg overflow-hidden divide-y bg-card shadow-sm">
          {clients.map((c) => (
            <button
              key={c.id}
              className="w-full flex items-center justify-between px-3 py-2.5 text-left hover:bg-muted/60 transition-colors text-sm"
              onClick={() => { onSelect(c); setQ(""); }}
            >
              <div>
                <div className="font-medium">{c.customer_name}</div>
                {c.company_name && <div className="text-xs text-muted-foreground">{c.company_name}</div>}
              </div>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                {c.contact_phone && <span>{c.contact_phone}</span>}
                <StatusPill status={c.status} />
                <ChevronRight className="h-3.5 w-3.5" />
              </div>
            </button>
          ))}
        </div>
      )}
      {q.trim().length >= 2 && !isFetching && clients.length === 0 && (
        <p className="text-xs text-muted-foreground pl-1">No returning clients found. Register as new below.</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Returning Client History Panel
// ---------------------------------------------------------------------------

function ClientHistoryPanel({ walkInId, onClose }: { walkInId: string; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ["fd-client-history", walkInId],
    queryFn: () => api.frontdesk.clientHistory(walkInId),
  });

  if (isLoading) return (
    <Card className="border-primary/20 bg-primary/5">
      <CardContent className="py-6 flex items-center justify-center gap-2">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading client history…
      </CardContent>
    </Card>
  );

  const client = (data as any)?.client;
  const visits: WalkIn[]   = (data as any)?.visits   ?? [];
  const invoices: Invoice[] = (data as any)?.invoices ?? [];

  return (
    <Card className="border-primary/20 bg-primary/5">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <History className="h-4 w-4 text-primary" /> Returning Client
          </CardTitle>
          <Button size="icon" variant="ghost" className="h-6 w-6" onClick={onClose}>
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="grid grid-cols-2 gap-x-4 gap-y-1">
          <div><span className="text-muted-foreground">Name:</span> <strong>{client?.name}</strong></div>
          {client?.company && <div><span className="text-muted-foreground">Company:</span> {client.company}</div>}
          {client?.phone   && <div><span className="text-muted-foreground">Phone:</span> {client.phone}</div>}
          {client?.email   && <div><span className="text-muted-foreground">Email:</span> {client.email}</div>}
          <div><span className="text-muted-foreground">Visits:</span> <strong>{(data as any)?.visit_count}</strong></div>
          <div><span className="text-muted-foreground">Total Spend:</span> <strong className="text-green-600 dark:text-green-300">{fmt((data as any)?.total_spend ?? 0)}</strong></div>
        </div>
        {invoices.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-muted-foreground mb-1">Last Invoices</p>
            <div className="space-y-1">
              {invoices.slice(0, 3).map((inv) => (
                <div key={inv.id} className="flex items-center justify-between text-xs bg-background rounded px-2 py-1.5 border">
                  <span className="font-mono text-muted-foreground">{inv.invoice_number}</span>
                  <span className="font-semibold">{fmt(inv.total_amount)}</span>
                  <StatusPill status={inv.status} />
                </div>
              ))}
            </div>
          </div>
        )}
        {visits[0]?.products_requested?.length ? (
          <div>
            <p className="text-xs font-semibold text-muted-foreground mb-1">Usually Buys</p>
            <div className="flex flex-wrap gap-1">
              {visits.flatMap((v) => v.products_requested ?? [])
                .slice(0, 6)
                .map((p, i) => (
                  <span key={i} className="bg-muted rounded-full px-2 py-0.5 text-xs">{p}</span>
                ))}
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Stock Check Indicator
// ---------------------------------------------------------------------------

function StockBadge({ status }: { status: StockResult["status"] }) {
  if (status === "in_stock")     return <span className="text-xs text-green-600 font-medium dark:text-green-300">✓ In Stock</span>;
  if (status === "low_stock")    return <span className="text-xs text-yellow-600 font-medium dark:text-yellow-300">⚠ Low Stock</span>;
  if (status === "out_of_stock") return <span className="text-xs text-red-600 font-medium dark:text-red-300">✗ Out of Stock</span>;
  return null;
}

// ---------------------------------------------------------------------------
// Step 1: Walk-in Registration
// ---------------------------------------------------------------------------

function StepWalkIn({
  prefill,
  onSuccess,
}: {
  prefill?: Partial<WalkIn>;
  onSuccess: (result: { walk_in: WalkIn }) => void;
}) {
  const { toast } = useToast();
  const [name,        setName]        = useState(prefill?.customer_name ?? "");
  const [company,     setCompany]     = useState(prefill?.company_name ?? "");
  const [phone,       setPhone]       = useState(prefill?.contact_phone ?? "");
  const [email,       setEmail]       = useState(prefill?.email ?? "");
  const [appointment, setAppointment] = useState(prefill?.has_appointment ?? false);
  const [purpose,     setPurpose]     = useState("");
  const [products,    setProducts]    = useState(prefill?.products_requested?.join(", ") ?? "");
  const [notes,       setNotes]       = useState("");

  const register = useMutation({
    mutationFn: () =>
      api.frontdesk.registerWalkIn({
        customer_name:      name.trim(),
        company_name:       company.trim()  || undefined,
        contact_phone:      phone.trim()    || undefined,
        email:              email.trim()    || undefined,
        has_appointment:    appointment,
        purpose:            purpose.trim(),
        products_requested: products.trim()
          ? products.split(",").map((p) => p.trim()).filter(Boolean)
          : undefined,
        notes: notes.trim() || undefined,
      }),
    onSuccess: (data: any) => {
      toast({ title: "Walk-in registered", description: `Welcome, ${data.walk_in?.customer_name}!` });
      onSuccess(data as { walk_in: WalkIn });
    },
    onError: (e: any) => {
      toast({ title: "Registration failed", description: e?.message ?? "Unknown error", variant: "destructive" });
    },
  });

  const valid = name.trim().length >= 2 && purpose.trim().length >= 3;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <UserPlus className="h-5 w-5" /> Register Walk-in Client
        </CardTitle>
        <CardDescription>Capture client details at reception.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1 col-span-2 sm:col-span-1">
            <label className="text-sm font-medium">Client Name *</label>
            <Input placeholder="e.g. Medway Pharmacy Ltd" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-1 col-span-2 sm:col-span-1">
            <label className="text-sm font-medium flex items-center gap-1"><Building2 className="h-3.5 w-3.5" /> Company</label>
            <Input placeholder="Company / Organisation" value={company} onChange={(e) => setCompany(e.target.value)} />
          </div>
          <div className="space-y-1 col-span-2 sm:col-span-1">
            <label className="text-sm font-medium flex items-center gap-1"><Phone className="h-3.5 w-3.5" /> Phone</label>
            <Input type="tel" placeholder="+234 801 234 5678" value={phone} onChange={(e) => setPhone(e.target.value)} />
          </div>
          <div className="space-y-1 col-span-2 sm:col-span-1">
            <label className="text-sm font-medium flex items-center gap-1"><Mail className="h-3.5 w-3.5" /> Email</label>
            <Input type="email" placeholder="client@example.com" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
        </div>

        <div className="flex items-center gap-2 py-1">
          <input
            type="checkbox"
            id="appointment"
            className="h-4 w-4 rounded border-gray-300 dark:border-gray-500/30"
            checked={appointment}
            onChange={(e) => setAppointment(e.target.checked)}
          />
          <label htmlFor="appointment" className="text-sm flex items-center gap-1.5">
            <Calendar className="h-3.5 w-3.5 text-muted-foreground" /> Client has a prior appointment
          </label>
        </div>

        <div className="space-y-1">
          <label className="text-sm font-medium">Purpose of Visit *</label>
          <Textarea
            placeholder="e.g. Purchase Amoxicillin 500mg x 200 packs, settle outstanding invoice"
            value={purpose}
            onChange={(e) => setPurpose(e.target.value)}
            rows={2}
            className="resize-none"
          />
        </div>
        <div className="space-y-1">
          <label className="text-sm font-medium flex items-center gap-1">
            <PackageSearch className="h-3.5 w-3.5" /> Products Requested
            <span className="text-muted-foreground text-xs font-normal">(comma-separated)</span>
          </label>
          <Input placeholder="Amoxicillin 500mg, Paracetamol 500mg" value={products} onChange={(e) => setProducts(e.target.value)} />
        </div>
        <div className="space-y-1">
          <label className="text-sm font-medium">Notes <span className="text-muted-foreground text-xs">(optional)</span></label>
          <Textarea placeholder="Any additional notes…" value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className="resize-none" />
        </div>
        <Button className="w-full gap-2" disabled={!valid || register.isPending} onClick={() => register.mutate()}>
          {register.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
          Register & Proceed to Invoice
        </Button>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Step 2: Invoice Creation (with inline stock check)
// ---------------------------------------------------------------------------

// Matches frontdesk.py's _due_date_from_terms regex ("Net (\d+)") — client-
// side preview only, the server is what actually persists due_date.
const PAYMENT_TERMS_OPTIONS = ["Due on Receipt", "Net 7 Days", "Net 15 Days", "Net 30 Days", "Net 60 Days"];
function previewDueDate(terms: string): string | null {
  const m = /Net\s+(\d+)/i.exec(terms);
  if (!m) return null;
  const d = new Date();
  d.setDate(d.getDate() + parseInt(m[1], 10));
  return d.toLocaleDateString("en-NG", { day: "2-digit", month: "short", year: "numeric" });
}

function StepInvoice({
  walkInId,
  onSuccess,
}: {
  walkInId: string;
  onSuccess: (result: { invoice: Invoice }) => void;
}) {
  const { toast } = useToast();
  const [items, setItems] = useState<InvoiceItem[]>([{ product: "", quantity: 1, unit_price: 0 }]);
  const [paymentMethod, setPaymentMethod] = useState("cash");
  const [notes, setNotes] = useState("");
  const [stockData, setStockData] = useState<Record<string, StockResult>>({});
  const stockTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Invoice Details — matches the real paper invoice's Bill To/Ship To,
  // Customer PO, Payment Terms, Shipping Method fields (previously captured
  // nowhere in this app at all).
  const [billingAddress, setBillingAddress] = useState("");
  const [shippingAddress, setShippingAddress] = useState("");
  const [sameAsBilling, setSameAsBilling] = useState(true);
  const [customerPo, setCustomerPo] = useState("");
  const [paymentTerms, setPaymentTerms] = useState("Due on Receipt");
  const [shippingMethod, setShippingMethod] = useState("");

  const checkStock = useCallback((products: string[]) => {
    const toCheck = products.filter((p) => p.trim().length >= 2);
    if (!toCheck.length) return;
    api.frontdesk.stockCheck(toCheck).then((data: any) => {
      const map: Record<string, StockResult> = {};
      for (const r of data?.products ?? []) map[r.product] = r;
      setStockData((prev) => ({ ...prev, ...map }));
    }).catch(() => {});
  }, []);

  const addItem = () => setItems((prev) => [...prev, { product: "", quantity: 1, unit_price: 0 }]);
  const removeItem = (i: number) => setItems((prev) => prev.filter((_, idx) => idx !== i));
  const TEXT_FIELDS: (keyof InvoiceItem)[] = ["product", "batch_number", "manufacture_date", "expiry_date"];
  const updateItem = (i: number, field: keyof InvoiceItem, value: string) => {
    setItems((prev) => {
      const next = prev.map((item, idx) =>
        idx === i ? { ...item, [field]: TEXT_FIELDS.includes(field) ? value : parseFloat(value) || 0 } : item
      );
      if (field === "product") {
        if (stockTimer.current) clearTimeout(stockTimer.current);
        stockTimer.current = setTimeout(() => {
          checkStock(next.map((it) => it.product).filter(Boolean));
        }, 600);
      }
      return next;
    });
  };

  const total = items.reduce((sum, item) => sum + item.quantity * item.unit_price, 0);
  const valid = items.every((item) => item.product.trim() && item.quantity > 0 && item.unit_price >= 0);

  const createInvoice = useMutation({
    mutationFn: () =>
      api.frontdesk.createInvoice(walkInId, {
        items: items.map((it) => ({ ...it, product: it.product.trim() })),
        payment_method: paymentMethod,
        notes: notes.trim() || undefined,
        billing_address: billingAddress.trim() || undefined,
        shipping_address: (sameAsBilling ? billingAddress : shippingAddress).trim() || undefined,
        customer_po: customerPo.trim() || undefined,
        payment_terms: paymentTerms,
        shipping_method: shippingMethod.trim() || undefined,
      }),
    onSuccess: (data: any) => {
      toast({ title: "Invoice created", description: `Total: ${fmt(data.invoice?.total_amount ?? 0)}` });
      onSuccess(data as { invoice: Invoice });
    },
    onError: (e: any) => {
      toast({ title: "Invoice creation failed", description: e?.message ?? "Unknown error", variant: "destructive" });
    },
  });

  const hasStockAlerts = items.some((it) => {
    const s = stockData[it.product];
    return s && (s.status === "low_stock" || s.status === "out_of_stock");
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <ClipboardList className="h-5 w-5" /> Create Invoice
        </CardTitle>
        <CardDescription>Add line items. Stock availability is checked automatically.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {hasStockAlerts && (
          <div className="flex items-center gap-2 rounded-lg bg-yellow-50 dark:bg-yellow-950/30 border border-yellow-200 dark:border-yellow-800 px-3 py-2 text-sm text-yellow-800 dark:text-yellow-300">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            Some items show low / out-of-stock. Confirm with inventory before issuing.
          </div>
        )}

        {/* Invoice Details — Bill To/Ship To, PO, Payment Terms, Shipping
            Method. Matches the real Placeware paper invoice's fields; none
            of this was captured anywhere in this app before. */}
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
                  <input type="checkbox" className="h-3.5 w-3.5 rounded border-gray-300 dark:border-gray-500/30"
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
                  {PAYMENT_TERMS_OPTIONS.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Shipping Method</label>
              <Input placeholder="e.g. Hand Delivery" value={shippingMethod} onChange={(e) => setShippingMethod(e.target.value)} />
            </div>
          </div>
          {previewDueDate(paymentTerms) && (
            <div className="text-xs text-muted-foreground">Due date: <span className="font-medium text-foreground">{previewDueDate(paymentTerms)}</span></div>
          )}
        </div>

        <div className="space-y-2">
          <div className="hidden grid-cols-12 gap-2 px-1 text-xs font-semibold text-muted-foreground sm:grid">
            <span className="col-span-5">Product</span>
            <span className="col-span-2 text-center">Qty</span>
            <span className="col-span-2 text-right">Unit ₦</span>
            <span className="col-span-2 text-right">Amount</span>
          </div>
          {items.map((item, i) => (
            <div key={i} className="space-y-0.5">
              <div className="grid grid-cols-2 items-center gap-2 sm:grid-cols-12">
                <div className="col-span-2 sm:col-span-5">
                  <Input
                    placeholder="Product name"
                    value={item.product}
                    onChange={(e) => updateItem(i, "product", e.target.value)}
                  />
                </div>
                <div className="col-span-1 sm:col-span-2">
                  <Input type="number" placeholder="Qty" min={1} value={item.quantity}
                    onChange={(e) => updateItem(i, "quantity", e.target.value)} />
                </div>
                <div className="col-span-1 sm:col-span-2">
                  <Input type="number" placeholder="0.00" min={0} step="0.01" value={item.unit_price}
                    onChange={(e) => updateItem(i, "unit_price", e.target.value)} />
                </div>
                <div className="col-span-1 text-right text-sm font-semibold tabular-nums sm:col-span-2">
                  ₦{(item.quantity * item.unit_price).toLocaleString()}
                </div>
                <div className="col-span-1 flex justify-end sm:col-span-1">
                  {items.length > 1 && (
                    <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => removeItem(i)}>
                      <Trash2 className="h-3.5 w-3.5 text-destructive" />
                    </Button>
                  )}
                </div>
              </div>
              {item.product.trim().length >= 2 && stockData[item.product] && (
                <div className="pl-1">
                  <StockBadge status={stockData[item.product].status} />
                  {stockData[item.product].quantity != null && (
                    <span className="text-xs text-muted-foreground ml-2">
                      ({stockData[item.product].quantity} units on hand)
                    </span>
                  )}
                </div>
              )}
              {/* Batch/Mfg/Exp -- always manual here, no inventory
                  autocomplete exists in this wizard (unlike CustomerWorkspace's
                  "Make New Request", which autofills batch_number/expiry_date
                  from the inventory search). */}
              <div className="grid grid-cols-3 gap-2 pl-1">
                <Input placeholder="Batch number" className="h-8 text-xs" value={item.batch_number ?? ""}
                  onChange={(e) => updateItem(i, "batch_number", e.target.value)} />
                <Input type="month" className="h-8 text-xs" value={item.manufacture_date ?? ""}
                  onChange={(e) => updateItem(i, "manufacture_date", e.target.value)} />
                <Input type="date" className="h-8 text-xs" value={item.expiry_date ?? ""}
                  onChange={(e) => updateItem(i, "expiry_date", e.target.value)} />
              </div>
            </div>
          ))}
          <Button size="sm" variant="outline" className="gap-1.5 mt-1" onClick={addItem}>
            <Plus className="h-3.5 w-3.5" /> Add Line Item
          </Button>
        </div>

        <div className="flex items-center justify-between py-2 border-t">
          <span className="text-sm font-semibold">Total</span>
          <span className="text-xl font-bold font-mono">{fmt(total)}</span>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <label className="text-sm font-medium">Payment Method</label>
            <Select value={paymentMethod} onValueChange={setPaymentMethod}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="cash">Cash</SelectItem>
                <SelectItem value="transfer">Bank Transfer</SelectItem>
                <SelectItem value="credit">Credit (Invoice)</SelectItem>
                <SelectItem value="pos">POS</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <label className="text-sm font-medium">Notes</label>
            <Input placeholder="Optional notes…" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
        </div>

        <Button className="w-full gap-2" disabled={!valid || createInvoice.isPending} onClick={() => createInvoice.mutate()}>
          {createInvoice.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ClipboardList className="h-4 w-4" />}
          Create Invoice & Send for QC
        </Button>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Step 3: QC Check
// ---------------------------------------------------------------------------

function StepQC({ invoiceId, onSuccess }: { invoiceId: string; onSuccess: (passed: boolean) => void }) {
  const { toast } = useToast();
  const [inspectorName, setInspectorName] = useState("");
  const [batchNumbers,  setBatchNumbers]  = useState("");
  const [notes,         setNotes]         = useState("");

  const submitQc = useMutation({
    mutationFn: (pass: boolean) =>
      api.frontdesk.submitQc(invoiceId, {
        passed: pass,
        inspector_name: inspectorName.trim(),
        notes: notes.trim() || undefined,
        batch_numbers: batchNumbers.trim()
          ? batchNumbers.split(",").map((b) => b.trim()).filter(Boolean)
          : undefined,
      }),
    onSuccess: (_: any, pass) => {
      toast({ title: pass ? "QC Passed ✓" : "QC Failed", variant: pass ? "default" : "destructive" });
      onSuccess(pass);
    },
    onError: (e: any) => {
      toast({ title: "QC submission failed", description: e?.message, variant: "destructive" });
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <CheckCircle2 className="h-5 w-5" /> QC Inspection
        </CardTitle>
        <CardDescription>Quality assurance check before finance approval.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1">
          <label className="text-sm font-medium">Inspector Name *</label>
          <Input placeholder="QA Officer name" value={inspectorName} onChange={(e) => setInspectorName(e.target.value)} />
        </div>
        <div className="space-y-1">
          <label className="text-sm font-medium">Batch Numbers <span className="text-muted-foreground text-xs">(comma-separated)</span></label>
          <Input placeholder="BN2024-001, BN2024-002" value={batchNumbers} onChange={(e) => setBatchNumbers(e.target.value)} />
        </div>
        <div className="space-y-1">
          <label className="text-sm font-medium">QC Notes</label>
          <Textarea placeholder="Inspection findings…" value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} className="resize-none" />
        </div>
        <div className="flex gap-3 pt-2">
          <Button variant="destructive" className="flex-1 gap-2" disabled={!inspectorName.trim() || submitQc.isPending}
            onClick={() => submitQc.mutate(false)}>
            {submitQc.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Fail QC
          </Button>
          <Button className="flex-1 gap-2 bg-green-600 hover:bg-green-700" disabled={!inspectorName.trim() || submitQc.isPending}
            onClick={() => submitQc.mutate(true)}>
            {submitQc.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
            Pass QC
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Step 4: Finance Approval
// ---------------------------------------------------------------------------

function StepFinance({ invoiceId, onSuccess }: { invoiceId: string; onSuccess: (approved: boolean) => void }) {
  const { toast } = useToast();
  const [approverName, setApproverName] = useState("");
  const [reason, setReason] = useState("");

  const approve = useMutation({
    mutationFn: (approved: boolean) =>
      api.frontdesk.financeApproval(invoiceId, {
        approved,
        approver_name: approverName.trim(),
        reason: reason.trim() || undefined,
      }),
    onSuccess: (_: any, approved) => {
      toast({ title: approved ? "Finance Approved ✓" : "Invoice Rejected", variant: approved ? "default" : "destructive" });
      onSuccess(approved);
    },
    onError: (e: any) => {
      toast({ title: "Finance decision failed", description: e?.message, variant: "destructive" });
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <DollarSign className="h-5 w-5" /> Finance Approval
        </CardTitle>
        <CardDescription>Final finance review and approval.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1">
          <label className="text-sm font-medium">Finance Officer Name *</label>
          <Input placeholder="Name and title" value={approverName} onChange={(e) => setApproverName(e.target.value)} />
        </div>
        <div className="space-y-1">
          <label className="text-sm font-medium">Reason / Notes <span className="text-muted-foreground text-xs">(optional)</span></label>
          <Textarea placeholder="Approval notes or rejection reason…" value={reason} onChange={(e) => setReason(e.target.value)} rows={3} className="resize-none" />
        </div>
        <div className="flex gap-3 pt-2">
          <Button variant="outline" className="flex-1 border-destructive text-destructive hover:bg-destructive hover:text-destructive-foreground"
            disabled={!approverName.trim() || approve.isPending} onClick={() => approve.mutate(false)}>
            {approve.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Reject
          </Button>
          <Button className="flex-1 bg-green-600 hover:bg-green-700" disabled={!approverName.trim() || approve.isPending}
            onClick={() => approve.mutate(true)}>
            {approve.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCheck className="h-4 w-4" />}
            Approve
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Step 5: Complete — print invoice + notify CEO
// ---------------------------------------------------------------------------

function StepComplete({ invoiceId, walkInName }: { invoiceId: string; walkInName: string }) {
  const { toast } = useToast();

  const { data } = useQuery({
    queryKey: ["fd-invoice-detail", invoiceId],
    queryFn: () => api.frontdesk.getInvoice(invoiceId),
  });

  const notify = useMutation({
    mutationFn: () => api.frontdesk.notifyExecutive(invoiceId),
    onSuccess: (d: any) => {
      toast({ title: "Executives notified", description: `Sent to: ${(d.notified ?? []).join(", ") || "No recipients configured"}` });
    },
    onError: (e: any) => {
      toast({ title: "Notification failed", description: e?.message, variant: "destructive" });
    },
  });

  const invoice: Invoice | undefined = (data as any)?.invoice;
  const walkIn: WalkIn | undefined   = (data as any)?.walk_in;

  return (
    <Card className="border-green-500/40 bg-green-50/20 dark:bg-green-950/20">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base text-green-700 dark:text-green-400">
          <CheckCircle2 className="h-5 w-5" /> Transaction Complete
        </CardTitle>
        <CardDescription>
          All steps completed for <strong>{walkInName}</strong>. Invoice registered, QC-checked, and finance-approved.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {invoice && (
          <div className="bg-background rounded-lg border p-3 text-sm space-y-1">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Invoice</span>
              <span className="font-mono font-semibold">{invoice.invoice_number}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Total</span>
              <span className="font-bold text-green-600 dark:text-green-300">{fmt(invoice.total_amount)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Payment</span>
              <span className="capitalize">{invoice.payment_method}</span>
            </div>
          </div>
        )}
        <div className="flex gap-2">
          <Button
            className="flex-1 gap-2"
            variant="outline"
            disabled={!invoice}
            onClick={() => invoice && printInvoice(invoice, walkIn)}
          >
            <Download className="h-4 w-4" /> Print / Save Invoice
          </Button>
          <Button
            className="flex-1 gap-2"
            variant="outline"
            disabled={notify.isPending}
            onClick={() => notify.mutate()}
          >
            {notify.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Bell className="h-4 w-4" />}
            Notify CEO / CFO
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Tab: New Walk-in Wizard
// ---------------------------------------------------------------------------

function NewWalkInTab() {
  const [step,      setStep]      = useState(0);
  const [walkIn,    setWalkIn]    = useState<WalkIn | null>(null);
  const [invoiceId, setInvoiceId] = useState<string | null>(null);
  const [prefill,   setPrefill]   = useState<Partial<WalkIn> | undefined>();
  const [historyId, setHistoryId] = useState<string | null>(null);

  function reset() {
    setStep(0); setWalkIn(null); setInvoiceId(null); setPrefill(undefined); setHistoryId(null);
  }

  return (
    <div className="space-y-4 max-w-2xl mx-auto">
      {step === 0 && (
        <Card className="border-dashed">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Search className="h-4 w-4 text-muted-foreground" /> Returning Client?
            </CardTitle>
            <CardDescription className="text-xs">Search before registering to auto-fill details and view history.</CardDescription>
          </CardHeader>
          <CardContent>
            <ClientSearch onSelect={(c) => {
              setPrefill(c);
              setHistoryId(c.id);
            }} />
          </CardContent>
        </Card>
      )}

      {historyId && step === 0 && (
        <ClientHistoryPanel walkInId={historyId} onClose={() => setHistoryId(null)} />
      )}

      <StepIndicator current={step < 4 ? step : 3} />

      {step > 0 && (
        <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={reset}>
          ← Start New Walk-in
        </Button>
      )}

      <motion.div key={step} {...motionVariants.cardEnter} transition={motionTransitions.standard}>
        {step === 0 && (
          <StepWalkIn
            prefill={prefill}
            onSuccess={(result) => { setWalkIn(result.walk_in); setStep(1); }}
          />
        )}
        {step === 1 && walkIn && (
          <StepInvoice
            walkInId={walkIn.id}
            onSuccess={(result) => { setInvoiceId(result.invoice.id); setStep(2); }}
          />
        )}
        {step === 2 && invoiceId && (
          <StepQC invoiceId={invoiceId} onSuccess={(passed) => { if (passed) setStep(3); }} />
        )}
        {step === 3 && invoiceId && (
          <StepFinance invoiceId={invoiceId} onSuccess={(approved) => { if (approved) setStep(4); }} />
        )}
        {step === 4 && invoiceId && (
          <StepComplete invoiceId={invoiceId} walkInName={walkIn?.customer_name ?? ""} />
        )}
      </motion.div>

      {walkIn && step > 0 && (
        <div className="flex flex-wrap gap-2 text-xs text-muted-foreground pt-2 border-t">
          <span>Walk-in: <code className="font-mono">{walkIn.id.slice(-10)}</code></span>
          {invoiceId && <span>Invoice: <code className="font-mono">{invoiceId.slice(-10)}</code></span>}
          <Badge variant={step === 4 ? "default" : "secondary"} className="text-[10px]">
            {["registering","invoicing","qc pending","finance pending","completed"][step] ?? ""}
          </Badge>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Today's Queue (live dashboard)
// ---------------------------------------------------------------------------

function QueueTab() {
  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["fd-daily-report"],
    queryFn: () => api.frontdesk.dailyReport(),
    refetchInterval: 30_000,
  });
  const { toast } = useToast();

  const [reportDialog, setReportDialog] = useState<{ open: boolean; report: string | null }>({ open: false, report: null });

  const intelligenceMutation = useMutation({
    mutationFn: () => api.reports.generate({ report_type: "frontdesk", intent_text: "generate daily frontdesk operations report" }),
    onSuccess: (data: any) => {
      setReportDialog({ open: true, report: data?.full_report ?? data?.findings?.join("\n") ?? "No content generated." });
    },
    onError: (e: any) => toast({ title: "Report generation failed", description: e.message, variant: "destructive" }),
  });

  const cancelMut = useMutation({
    mutationFn: (id: string) => api.frontdesk.cancelWalkIn(id),
    onSuccess: () => refetch(),
  });

  const report = data as any;
  const walkIns: WalkIn[] = report?.walk_ins ?? [];

  const stats = [
    { label: "Walk-ins Today",  value: report?.walk_in_count  ?? 0,              icon: Users,      color: "text-blue-600 dark:text-blue-300"   },
    { label: "Invoices Raised", value: report?.invoice_count  ?? 0,              icon: FileText,   color: "text-purple-600 dark:text-purple-300" },
    { label: "Revenue Today",   value: fmt(report?.total_revenue ?? 0),          icon: TrendingUp, color: "text-green-600 dark:text-green-300"  },
    { label: "Pending QC",      value: report?.pending_qc     ?? 0,              icon: Clock,      color: "text-yellow-600 dark:text-yellow-300" },
    { label: "Pending Finance", value: report?.pending_finance ?? 0,             icon: DollarSign, color: "text-orange-600 dark:text-orange-300" },
    { label: "Completed",       value: report?.completed_today ?? 0,             icon: CheckCheck, color: "text-green-600 dark:text-green-300"  },
  ];

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-muted-foreground">
          {new Date().toLocaleDateString("en-NG", { weekday: "long", day: "numeric", month: "long" })}
        </h2>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            className="gap-1.5"
            onClick={() => intelligenceMutation.mutate()}
            disabled={intelligenceMutation.isPending}
          >
            {intelligenceMutation.isPending
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
              : <Sparkles className="h-3.5 w-3.5" />
            }
            Intelligence Report
          </Button>
          <Button size="sm" variant="outline" className="gap-1.5" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? "animate-spin" : ""}`} /> Refresh
          </Button>
        </div>
      </div>

      {/* Intelligence Report Dialog */}
      <Dialog open={reportDialog.open} onOpenChange={(open) => setReportDialog((s) => ({ ...s, open }))}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-purple-500" />
              Frontdesk Intelligence Report
            </DialogTitle>
          </DialogHeader>
          <ScrollArea className="max-h-[60vh] pr-2">
            <pre className="text-xs whitespace-pre-wrap font-mono leading-relaxed">
              {reportDialog.report ?? ""}
            </pre>
          </ScrollArea>
          {reportDialog.report && (
            <div className="flex justify-end pt-2 border-t">
              <Button
                size="sm"
                variant="outline"
                className="gap-1.5"
                onClick={async () => {
                  try {
                    const { authClient } = await import("@/lib/auth-client");
                    let token = authClient.getAccessToken();
                    if (!token) {
                      const refreshed = await authClient.refresh();
                      if (refreshed) token = authClient.getAccessToken();
                    }
                    const { apiUrl } = await import("@/lib/api-base");
                    const res = await fetch(apiUrl("/reports/generate/docx"), {
                      method: "POST",
                      headers: {
                        "Content-Type": "application/json",
                        ...(token ? { Authorization: `Bearer ${token}` } : {}),
                      },
                      body: JSON.stringify({ report_type: "frontdesk", intent_text: "generate daily frontdesk operations report" }),
                    });
                    if (!res.ok) throw new Error(await res.text());
                    const blob = await res.blob();
                    const a = document.createElement("a");
                    a.href = URL.createObjectURL(blob);
                    a.download = `frontdesk_report_${new Date().toISOString().slice(0, 10)}.docx`;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                  } catch (err: any) {
                    toast({ title: "Download failed", description: err.message, variant: "destructive" });
                  }
                }}
              >
                <Download className="h-3.5 w-3.5" />
                Download Word (.docx)
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <div className="grid grid-cols-3 gap-3 sm:grid-cols-6">
        {stats.map((s) => {
          const Icon = s.icon;
          return (
            <Card key={s.label} className="p-3 text-center">
              <Icon className={`h-5 w-5 mx-auto mb-1 ${s.color}`} />
              <div className="text-lg font-bold">{isLoading ? "—" : s.value}</div>
              <div className="text-xs text-muted-foreground leading-tight">{s.label}</div>
            </Card>
          );
        })}
      </div>

      <div>
        <h3 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
          <Users className="h-4 w-4" /> Today's Walk-ins
        </h3>
        {isLoading ? (
          <div className="flex items-center justify-center py-10 text-muted-foreground gap-2">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading…
          </div>
        ) : walkIns.length === 0 ? (
          <div className="text-center py-10 text-muted-foreground text-sm border rounded-lg">
            No walk-ins registered today. Click "New Walk-in" to get started.
          </div>
        ) : (
          <div className="space-y-2">
            {walkIns.map((wi) => (
              <motion.div key={wi.id} {...motionVariants.cardEnter}>
                <div className="flex items-center justify-between rounded-lg border bg-card px-4 py-3 hover:bg-muted/40 transition-colors">
                  <div className="flex items-center gap-3">
                    <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center text-primary text-sm font-bold">
                      {wi.customer_name[0].toUpperCase()}
                    </div>
                    <div>
                      <div className="font-medium text-sm">{wi.customer_name}</div>
                      {wi.company_name && <div className="text-xs text-muted-foreground">{wi.company_name}</div>}
                    </div>
                  </div>
                  <div className="flex items-center gap-3 text-right">
                    <div className="text-xs text-muted-foreground hidden sm:block">{fmtDate(wi.created_at)}</div>
                    <StatusPill status={wi.status} />
                    {!["completed", "cancelled"].includes(wi.status) && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-6 px-2 text-xs text-destructive hover:bg-destructive/10"
                        disabled={cancelMut.isPending}
                        onClick={() => {
                          if (confirm(`Cancel walk-in for ${wi.customer_name}?`))
                            cancelMut.mutate(wi.id);
                        }}
                      >
                        Cancel
                      </Button>
                    )}
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </div>

      {(report?.top_products?.length ?? 0) > 0 && (
        <div>
          <h3 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
            <Boxes className="h-4 w-4" /> Top Requested Products Today
          </h3>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {report.top_products.slice(0, 6).map((p: any, i: number) => (
              <div key={p.product} className="flex items-center gap-2 rounded-lg border bg-card px-3 py-2">
                <span className="text-xs font-bold text-muted-foreground w-4">{i + 1}.</span>
                <div className="flex-1 truncate text-sm">{p.product}</div>
                <Badge variant="secondary" className="text-xs shrink-0">{p.count}×</Badge>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: All Invoices
// ---------------------------------------------------------------------------

function InvoicesTab() {
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
                      duplicated (ACE-Workspace-Standard.md Ch.10). */}
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

// ---------------------------------------------------------------------------
// Tab: Reports
// ---------------------------------------------------------------------------

function ReportsTab() {
  const [reportDate, setReportDate] = useState("");
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["fd-report", reportDate],
    queryFn: () => api.frontdesk.dailyReport(reportDate || undefined),
  });

  const report = data as any;

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <label className="text-sm font-medium">Report Date</label>
          <Input type="date" className="w-40" value={reportDate} onChange={(e) => setReportDate(e.target.value)} />
        </div>
        <Button size="sm" variant="outline" className="gap-1.5" onClick={() => refetch()}>
          <BarChart3 className="h-3.5 w-3.5" /> Generate
        </Button>
        {reportDate && (
          <Button size="sm" variant="ghost" onClick={() => setReportDate("")} className="text-muted-foreground">
            Today
          </Button>
        )}
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-12 text-muted-foreground gap-2">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading report…
        </div>
      ) : report ? (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: "Walk-ins",         value: report.walk_in_count,                         icon: Users,      color: "text-blue-600 dark:text-blue-300"   },
              { label: "Invoices",         value: report.invoice_count,                         icon: FileText,   color: "text-purple-600 dark:text-purple-300" },
              { label: "Revenue",          value: fmt(report.total_revenue),                    icon: TrendingUp, color: "text-green-600 dark:text-green-300"  },
              { label: "Pending Approval", value: (report.pending_qc ?? 0) + (report.pending_finance ?? 0), icon: Clock, color: "text-orange-600 dark:text-orange-300" },
            ].map((s) => {
              const Icon = s.icon;
              return (
                <Card key={s.label} className="p-4">
                  <div className="flex items-center gap-2 mb-1">
                    <Icon className={`h-4 w-4 ${s.color}`} />
                    <span className="text-xs text-muted-foreground">{s.label}</span>
                  </div>
                  <div className="text-2xl font-bold">{s.value}</div>
                </Card>
              );
            })}
          </div>

          {report.top_products?.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Boxes className="h-4 w-4" /> Top Requested Products
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {report.top_products.map((p: any, i: number) => (
                    <div key={p.product} className="flex items-center gap-3">
                      <span className="text-xs text-muted-foreground w-5 text-right">{i + 1}.</span>
                      <div className="flex-1 text-sm">{p.product}</div>
                      <div className="flex items-center gap-2">
                        <div
                          className="h-2 rounded-full bg-primary/60"
                          style={{ width: `${Math.max(8, (p.count / report.top_products[0].count) * 100)}px` }}
                        />
                        <span className="text-xs font-semibold w-6 text-right">{p.count}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {(report.pending_qc > 0 || report.pending_finance > 0) && (
            <Card className="border-yellow-200 dark:border-yellow-800">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2 text-yellow-700 dark:text-yellow-400">
                  <AlertTriangle className="h-4 w-4" /> Pending Approvals
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm space-y-1">
                {report.pending_qc > 0 && (
                  <p>• <strong>{report.pending_qc}</strong> walk-in(s) waiting for QC inspection</p>
                )}
                {report.pending_finance > 0 && (
                  <p>• <strong>{report.pending_finance}</strong> invoice(s) awaiting Finance approval</p>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Frontdesk Page
// ---------------------------------------------------------------------------

export default function Frontdesk() {
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Users className="h-6 w-6 text-primary" /> Frontdesk & Client Reception
        </h1>
        <p className="text-sm text-muted-foreground">
          Walk-in intake · Invoicing · QC → Finance pipeline · Client history · Reports
        </p>
      </div>

      <Tabs defaultValue="queue">
        <TabsList className="w-full sm:grid sm:grid-cols-4">
          <TabsTrigger value="queue"    className="gap-1.5"><Clock     className="h-3.5 w-3.5" /> Today's Queue</TabsTrigger>
          <TabsTrigger value="new"      className="gap-1.5"><UserPlus  className="h-3.5 w-3.5" /> New Walk-in</TabsTrigger>
          <TabsTrigger value="invoices" className="gap-1.5"><FileText  className="h-3.5 w-3.5" /> All Invoices</TabsTrigger>
          <TabsTrigger value="reports"  className="gap-1.5"><BarChart3 className="h-3.5 w-3.5" /> Reports</TabsTrigger>
        </TabsList>

        <TabsContent value="queue" className="mt-4">
          <QueueTab />
        </TabsContent>

        <TabsContent value="new" className="mt-4">
          <NewWalkInTab />
        </TabsContent>

        <TabsContent value="invoices" className="mt-4">
          <InvoicesTab />
        </TabsContent>

        <TabsContent value="reports" className="mt-4">
          <ReportsTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

