/**
 * Inventory & Quality panels (Quality Control and Compliance pages): batch release, expiry by
 * product, recalls, deviations & CAPA. Everything reads /quality (ACE Books-backed) and acts
 * through it, so stock status, recalls and the calendar stay in step.
 */
import { Fragment, ReactNode, useEffect, useMemo, useState } from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { CustomerPick } from "@/components/books/kit";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, CalendarPlus, ChevronDown, ChevronRight, Loader2, PackageX, Plus, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { ReportButton } from "@/components/reports/ReportButton";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { InvoiceActionPanel } from "@/components/workspace/InvoiceActionPanel";
import { InvoiceDetailBody } from "@/components/workspace/InvoiceDetailBody";
import { DrillLink } from "@/components/books/kit";
import { Facts } from "@/components/books/lineage";
import { api } from "@/lib/api-client";
import { books, Dict, fmtDate, naira, num } from "@/lib/books-api";
import { CapaEditor, useIsQa, useQualityActions, useQualityRefresh } from "./actions";

export function Tone({ tone, children }: { tone: "red" | "amber" | "sky" | "green" | "slate" | "violet"; children: ReactNode }) {
  const cls = {
    red: "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300", amber: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300",
    sky: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300", green: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
    slate: "bg-muted text-muted-foreground", violet: "bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300",
  }[tone];
  return <span className={`inline-flex whitespace-nowrap rounded-md px-1.5 py-0.5 text-[11px] font-medium ${cls}`}>{children}</span>;
}

function Spinner() {
  return <div className="flex justify-center py-10"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>;
}

async function act(fn: () => Promise<any>, ok: string, refresh: () => void) {
  try {
    await fn();
    toast.success(ok);
    refresh();
    return true;
  } catch (e: any) {
    toast.error(e?.message ?? "Action failed");
    return false;
  }
}

// ---------------------------------------------------------------------------
// Release queue: invoices waiting for QC + incoming batches waiting for release
// ---------------------------------------------------------------------------

const STAGE: Record<string, [string, "sky" | "amber" | "green" | "red"]> = {
  expected: ["Expected", "sky"], awaiting_release: ["Received · awaiting release", "amber"], released: ["Released", "green"], rejected: ["Rejected", "red"],
};

export function ReleaseQueue() {
  const isQa = useIsQa();
  const qa = useQualityActions();
  const refresh = useQualityRefresh();
  const [openInv, setOpenInv] = useState<string | null>(null);
  const invoices = useQuery({ queryKey: ["quality", "qc-invoices"], queryFn: () => api.frontdesk.listInvoices({ status: "qc_pending", limit: 50 }), refetchInterval: 30000 });
  const detail = useQuery({ queryKey: ["quality", "qc-invoice", openInv], queryFn: () => api.frontdesk.getInvoice(openInv!), enabled: !!openInv });
  const { data, isLoading } = useQuery({ queryKey: ["quality", "batches"], queryFn: () => api.quality.batches() });
  const [rejecting, setRejecting] = useState<Dict | null>(null);
  const [reason, setReason] = useState("");
  const pending: Dict[] = invoices.data?.invoices ?? [];
  const batches: Dict[] = data?.batches ?? [];
  const received: Dict[] = data?.received_unreleased ?? [];
  const open = batches.filter((b) => b.stage !== "released" && b.stage !== "rejected");
  const done = batches.filter((b) => b.stage === "released" || b.stage === "rejected").slice(0, 15);

  return (
    <div className="space-y-5">
      <KpiStrip items={[
        { label: "Invoices waiting for QC", value: pending.length, tone: pending.length ? "warning" : "success", sub: "Frontdesk requests to check against stock" },
        { label: "Batches expected", value: open.filter((b) => b.stage === "expected").length, sub: `${open.filter((b) => b.late).length} late` },
        { label: "Received, awaiting release", value: open.filter((b) => b.stage === "awaiting_release").length + received.length,
          tone: open.some((b) => b.stage === "awaiting_release") || received.length ? "warning" : "default", sub: "quarantined in ACE Books until released" },
        { label: "Released this list", value: done.filter((b) => b.stage === "released").length, sub: `${done.filter((b) => b.stage === "rejected").length} rejected` },
      ]} />

      {pending.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">Invoice requests waiting for QC ({pending.length})</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {pending.map((inv) => (
              <div key={inv.id} className="overflow-hidden rounded-lg border">
                <button className="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-muted/40" onClick={() => setOpenInv(openInv === inv.id ? null : inv.id)}>
                  <div className="min-w-0"><div className="truncate font-mono text-xs text-muted-foreground">{inv.invoice_number}</div>
                    <div className="truncate text-sm font-medium">{inv.company_name || inv.customer_name}</div></div>
                  <div className="flex items-center gap-2"><span className="text-sm font-semibold">{naira(inv.total_amount)}</span>
                    {openInv === inv.id ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</div>
                </button>
                {openInv === inv.id && (
                  <div className="space-y-3 border-t bg-muted/20 p-3">
                    <InvoiceDetailBody invoice={detail.data?.invoice} loading={detail.isLoading} />
                    <div className="border-t pt-3"><InvoiceActionPanel invoice={inv as any} onActioned={() => invoices.refetch()} /></div>
                  </div>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm">Incoming batches</CardTitle>
          <Button size="sm" onClick={() => qa.open("batch")}><CalendarPlus className="mr-1.5 h-4 w-4" />Register incoming batch</Button>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? <Spinner /> : open.length === 0 && received.length === 0 ? (
            <p className="p-6 text-center text-sm text-muted-foreground">Nothing waiting. Register a batch when a delivery is expected; it shows on the calendar and is held until you release it.</p>
          ) : (
            <Table>
              <TableHeader><TableRow><TableHead>Product · batch</TableHead><TableHead>Stage</TableHead><TableHead>Expected</TableHead>
                <TableHead className="text-right">Qty</TableHead><TableHead>Registered by</TableHead><TableHead /></TableRow></TableHeader>
              <TableBody>
                {received.map((b) => (
                  <TableRow key={b.batch_id}>
                    <TableCell><div className="font-medium">{b.product}</div><div className="text-[11px] text-muted-foreground">{b.sku} · lot {b.batch_number} · exp {fmtDate(b.expiry_date)}</div></TableCell>
                    <TableCell><Tone tone="amber">Received on a bill · not checked</Tone></TableCell>
                    <TableCell className="text-xs">{fmtDate(b.created_at)}</TableCell>
                    <TableCell className="text-right">{num(b.on_hand)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">—</TableCell>
                    <TableCell className="text-right">{isQa && (
                      <Button size="sm" variant="outline" onClick={() => act(() => api.quality.registerBatch({ sku: b.sku, batch_number: b.batch_number, release_now: true }),
                        `Lot ${b.batch_number} released`, refresh)}>Release</Button>)}</TableCell>
                  </TableRow>
                ))}
                {open.map((b) => (
                  <TableRow key={b.id}>
                    <TableCell><div className="font-medium">{b.product_name}</div><div className="text-[11px] text-muted-foreground">{b.sku ?? "not in ACE Books"} · lot {b.batch_number}{b.expiry_date ? ` · exp ${fmtDate(b.expiry_date)}` : ""}</div></TableCell>
                    <TableCell><Tone tone={STAGE[b.stage][1]}>{STAGE[b.stage][0]}</Tone>{b.late && <div className="text-[11px] text-red-600">late</div>}</TableCell>
                    <TableCell className="whitespace-nowrap text-xs">{b.expected_arrival_date ? fmtDate(b.expected_arrival_date) : "—"}</TableCell>
                    <TableCell className="text-right">{b.fin_batch_id ? num(b.on_hand) : b.quantity ? `${num(b.quantity)} due` : "—"}</TableCell>
                    <TableCell className="text-xs">{b.registered_by_name ?? "—"}<div className="text-[11px] text-muted-foreground">{fmtDate(b.created_at)}</div></TableCell>
                    <TableCell className="space-x-1 whitespace-nowrap text-right">{isQa && (<>
                      <Button size="sm" variant="outline" onClick={() => act(() => api.quality.releaseBatch(b.id), `${b.product_name} lot ${b.batch_number} released`, refresh)}>Release</Button>
                      <Button size="sm" variant="ghost" className="text-red-600" onClick={() => { setRejecting(b); setReason(""); }}>Reject</Button></>)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {done.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">Recent decisions</CardTitle></CardHeader>
          <CardContent className="p-0">
            <Table><TableBody>{done.map((b) => (
              <TableRow key={b.id}>
                <TableCell><div className="font-medium">{b.product_name}</div><div className="text-[11px] text-muted-foreground">lot {b.batch_number}{b.sku ? "" : " · not in ACE Books"}</div></TableCell>
                <TableCell><Tone tone={STAGE[b.stage][1]}>{STAGE[b.stage][0]}</Tone></TableCell>
                <TableCell className="text-xs">{b.stage === "released" ? `${b.approved_by_name ?? "—"} · ${fmtDate(b.approved_at)}` : b.rejection_reason}</TableCell>
                <TableCell className="text-right"><ReportButton type="batch" kind="batch" id={b.id} variant="ghost" label="Report" /></TableCell>
              </TableRow>))}</TableBody></Table>
          </CardContent>
        </Card>
      )}

      <DetailSheet open={!!rejecting} onOpenChange={(o) => !o && setRejecting(null)} title={`Reject lot ${rejecting?.batch_number ?? ""}`}
                   description="The lot stays quarantined in ACE Books (it cannot be sold) and a deviation is raised for the investigation."
                   footer={<Button variant="destructive" className="w-full" disabled={reason.trim().length < 5}
                     onClick={async () => { if (await act(() => api.quality.rejectBatch(rejecting!.id, reason), "Batch rejected · deviation raised", refresh)) setRejecting(null); }}>Reject batch</Button>}>
        <Label className="text-xs">Reason</Label>
        <Textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. certificate of analysis does not match, damaged packaging, cold chain broken" />
      </DetailSheet>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Expiry, grouped by product
// ---------------------------------------------------------------------------

const BUCKETS: [string, string, "red" | "amber" | "sky" | "slate" | "green"][] = [
  ["expired", "Expired", "red"], ["critical", "Within 30 days", "amber"], ["soon", "31-90 days", "sky"], ["watch", "91-180 days", "slate"], ["ok", "Later", "green"],
];
const BUCKET = Object.fromEntries(BUCKETS.map(([k, l, t]) => [k, { label: l, tone: t }]));

export function ExpiryByProduct() {
  const isQa = useIsQa();
  const qa = useQualityActions();
  const refresh = useQualityRefresh();
  const { data, isLoading } = useQuery({ queryKey: ["quality", "expiry"], queryFn: () => api.quality.expiry(180) });
  const [filter, setFilter] = useState("all");
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const products: Dict[] = data?.products ?? [];
  const shown = products.filter((p) => filter === "all" || p.bucket === filter);
  const s = data?.summary ?? {};

  return (
    <div className="space-y-4">
      <KpiStrip items={BUCKETS.slice(0, 4).map(([k, l]) => ({
        label: l, value: s[k] ? `${s[k].products} product${s[k].products === 1 ? "" : "s"}` : "None",
        tone: (k === "expired" && s[k] ? "danger" : k === "critical" && s[k] ? "warning" : "default") as any,
        sub: s[k] ? `${num(s[k].units)} units · ${naira(s[k].value)} at cost` : undefined, onClick: () => setFilter(k),
      }))} />
      {data?.unsellable_value > 0 && (
        <p className="text-xs text-muted-foreground">At current sales rates about {naira(data.unsellable_value)} of this stock will not sell before it expires.
          Expired lots cannot be sold (ACE Books refuses them); quarantine, write them off or return them to the supplier.</p>
      )}
      <div className="flex flex-wrap gap-2">
        {[["all", "All"] as [string, string], ...BUCKETS.slice(0, 4).map(([k, l]) => [k, l] as [string, string])].map(([k, l]) => (
          <Button key={k} size="sm" className="h-8" variant={filter === k ? "default" : "outline"} onClick={() => setFilter(k)}>{l}</Button>
        ))}
      </div>
      {isLoading ? <Spinner /> : shown.length === 0 ? <p className="p-6 text-center text-sm text-muted-foreground">No products in this range.</p> : (
        <div className="space-y-2">
          {shown.map((p) => (
            <Card key={p.product} className={p.bucket === "expired" ? "border-red-300 dark:border-red-500/30" : undefined}>
              <button className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left" onClick={() => setOpen({ ...open, [p.product]: !open[p.product] })}>
                <div className="flex min-w-0 items-center gap-2">
                  {open[p.product] ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
                  <div className="min-w-0">
                    <div className="truncate font-medium">{p.product}</div>
                    <div className="truncate text-[11px] text-muted-foreground">
                      {p.lots.length} lot{p.lots.length === 1 ? "" : "s"} in stock · {num(p.units)} units · {naira(p.value)}
                      {p.monthly_demand ? ` · sells ${num(p.monthly_demand, 1)}/month` : " · no recent sales"}
                    </div>
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  <Tone tone={BUCKET[p.bucket]?.tone ?? "slate"}>{p.days_left < 0 ? `Expired ${-p.days_left} days ago` : `Next expiry in ${p.days_left} days`}</Tone>
                  {p.unsellable_units > 0 && <div className="text-[11px] text-red-600 dark:text-red-400">{num(p.unsellable_units)} units won't sell in time</div>}
                </div>
              </button>
              {open[p.product] && (
                <CardContent className="border-t p-0">
                  <Table>
                    <TableHeader><TableRow><TableHead>Lot / item code</TableHead><TableHead>Expiry</TableHead><TableHead className="text-right">Qty</TableHead>
                      <TableHead className="text-right">Value</TableHead><TableHead>Status</TableHead><TableHead /></TableRow></TableHeader>
                    <TableBody>{p.lots.map((l: Dict) => (
                      <TableRow key={l.batch_id ?? l.sku}>
                        <TableCell><DrillLink to={{ type: "product", id: l.sku, label: l.sku }}>{l.sku}</DrillLink><div className="text-[11px] text-muted-foreground">batch {l.batch_number ?? "—"}</div></TableCell>
                        <TableCell className="whitespace-nowrap text-xs">{fmtDate(l.expiry_date)}<div><Tone tone={BUCKET[l.bucket]?.tone ?? "slate"}>{BUCKET[l.bucket]?.label ?? "—"}</Tone></div></TableCell>
                        <TableCell className="text-right">{num(l.qty)}</TableCell>
                        <TableCell className="text-right whitespace-nowrap">{naira(l.value)}</TableCell>
                        <TableCell className="text-xs">{l.recall ? <Tone tone="red">Recall {l.recall.recall_number}</Tone> : <Tone tone={l.batch_status === "AVAILABLE" ? (l.bucket === "expired" ? "red" : "green") : "amber"}>
                          {l.batch_status === "AVAILABLE" ? (l.bucket === "expired" ? "Blocked (expired)" : "Sellable") : l.batch_status?.toLowerCase()}</Tone>}</TableCell>
                        <TableCell className="space-x-1 whitespace-nowrap text-right">
                          {isQa && l.batch_id && l.batch_status === "AVAILABLE" && <Button size="sm" variant="outline" onClick={() => act(() => api.quality.quarantineLot(l.batch_id, "Expiry review"), `Lot ${l.batch_number} quarantined`, refresh)}>Quarantine</Button>}
                          {isQa && l.batch_id && l.batch_status === "QUARANTINED" && l.bucket !== "expired" && <Button size="sm" variant="outline" onClick={() => act(() => api.quality.releaseLot(l.batch_id), `Lot ${l.batch_number} released`, refresh)}>Release</Button>}
                          {l.batch_id && <Button size="sm" variant="outline" onClick={() => act(() => api.quality.writeOffLot(l.batch_id, "EXPIRY"), "Write-off sent for approval in ACE Books › Stock", refresh)}>Write off</Button>}
                          {isQa && l.batch_id && !l.recall && <Button size="sm" variant="ghost" className="text-red-600" onClick={() => qa.open("recall", { batch: { id: l.batch_id, sku: l.sku, batch_number: l.batch_number } })}>Recall</Button>}
                        </TableCell>
                      </TableRow>))}</TableBody>
                  </Table>
                </CardContent>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Recalls (QMS case + ACE Books recall)
// ---------------------------------------------------------------------------

const RSTATUS: Record<string, [string, "red" | "amber" | "green" | "slate"]> = {
  initiated: ["Initiated", "red"], in_progress: ["In progress", "amber"], completed: ["Completed", "green"], closed: ["Closed", "slate"],
};

export function RecallsPanel() {
  const isQa = useIsQa();
  const qa = useQualityActions();
  const { data = [], isLoading } = useQuery({ queryKey: ["quality", "recalls"], queryFn: () => api.quality.recalls() });
  const [picked, setPicked] = useState<string | null>(null);
  const open = data.filter((r: Dict) => ["initiated", "in_progress"].includes(r.status));
  return (
    <div className="space-y-4">
      <KpiStrip items={[
        { label: "Open recalls", value: open.length, tone: open.length ? "danger" : "success", sub: `${open.filter((r: Dict) => r.overdue).length} past their return date` },
        { label: "Customers to contact", value: open.reduce((s: number, r: Dict) => s + Number(r.customers || 0) - Number(r.contacted || 0), 0), sub: "from ACE Books sales of the batch" },
        { label: "Units frozen", value: num(open.reduce((s: number, r: Dict) => s + Number(r.units_frozen || 0), 0)), sub: "in stock, blocked from sale" },
        { label: "Units returned", value: num(open.reduce((s: number, r: Dict) => s + Number(r.units_returned || 0), 0)),
          sub: `of ${num(open.reduce((s: number, r: Dict) => s + Number(r.units_out || 0), 0))} sold` },
      ]} />
      <div className="flex justify-end">{isQa && <Button size="sm" onClick={() => qa.open("recall")}><PackageX className="mr-1.5 h-4 w-4" />Initiate recall</Button>}</div>
      <Card>
        <CardContent className="p-0">
          {isLoading ? <Spinner /> : data.length === 0 ? <p className="p-6 text-center text-sm text-muted-foreground">No recalls.</p> : (
            <Table>
              <TableHeader><TableRow><TableHead>Recall</TableHead><TableHead>Product · batch</TableHead><TableHead>Status</TableHead>
                <TableHead className="text-right">Customers</TableHead><TableHead className="text-right">Returned</TableHead><TableHead>Due back</TableHead><TableHead>ACE Books</TableHead></TableRow></TableHeader>
              <TableBody>{data.map((r: Dict) => (
                <TableRow key={r.id} className="cursor-pointer" onClick={() => setPicked(r.id)}>
                  <TableCell><div className="font-medium">{r.recall_id}</div><div className="text-[11px] text-muted-foreground">{fmtDate(r.initiation_date)} · {r.severity} · {r.scope}</div></TableCell>
                  <TableCell className="max-w-[240px]"><div className="truncate">{r.product_name}</div><div className="text-[11px] text-muted-foreground">batch {r.batch_number}</div></TableCell>
                  <TableCell><Tone tone={RSTATUS[r.status]?.[1] ?? "slate"}>{RSTATUS[r.status]?.[0] ?? r.status}</Tone>{r.overdue && <div className="text-[11px] text-red-600">past return date</div>}</TableCell>
                  <TableCell className="text-right">{r.fin_recall_id ? `${num(r.contacted)} / ${num(r.customers)}` : "—"}</TableCell>
                  <TableCell className="text-right">{r.fin_recall_id ? `${num(r.units_returned)} / ${num(r.units_out)}` : "—"}</TableCell>
                  <TableCell className="whitespace-nowrap text-xs">{r.expected_return_date ? fmtDate(r.expected_return_date) : "—"}</TableCell>
                  <TableCell>{r.fin_recall_id ? <Tone tone="violet">{r.fin_recall_number} · {r.fin_status?.toLowerCase()}</Tone> : <Tone tone="slate">not linked (test record)</Tone>}</TableCell>
                </TableRow>))}</TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <RecallSheet id={picked} onClose={() => setPicked(null)} />
    </div>
  );
}

/** A customer brings recalled stock back: choose the invoice they bought it on (ACE Books or
 *  Sage history), how many came back and at what price - the credit note reduces that invoice and
 *  the customer's balance, and the stock comes back into the recalled (frozen) batch. */
export function RecallReturnForm({ recallId, sku, batchId, customer, itemId, onDone }: {
  recallId: string; sku?: string; batchId?: string; customer: { id: string | number; name?: string }; itemId?: string; onDone: () => void;
}) {
  const { data: invoices, isLoading } = useQuery({ queryKey: ["quality", "cust-invoices", customer.id, sku, batchId],
    queryFn: () => api.quality.customerInvoices(customer.id, { sku, batch_id: batchId }) });
  const [pick, setPick] = useState("");
  const [qty, setQty] = useState("");
  const [price, setPrice] = useState("");
  const [credit, setCredit] = useState(true);
  const [busy, setBusy] = useState(false);
  const inv = (invoices ?? []).find((i: Dict) => `${i.sage ? "s" : "a"}:${i.invoice_number}` === pick);
  const line = inv?.lines?.find((l: Dict) => !sku || l.sku === sku) ?? inv?.lines?.[0];
  useEffect(() => { if (line?.unit_price != null) setPrice(String(line.unit_price)); }, [pick]);
  const save = async () => {
    setBusy(true);
    const ok = await act(() => api.quality.recordRecallReturn(recallId, {
      item_id: itemId, customer_id: customer.id, quantity: Number(qty), unit_price: credit ? Number(price || 0) : 0, credit,
      invoice_id: inv && !inv.sage ? inv.invoice_id : inv?.invoice_id || undefined, sage_invoice_number: inv?.sage ? inv.invoice_number : undefined,
      unit_cost: line?.unit_cost ?? undefined,
    }), credit ? "Return recorded - credit note raised on the invoice, stock back in the recalled batch" : "Return recorded - stock back in the recalled batch", () => {});
    setBusy(false);
    if (ok) onDone();
  };
  return (
    <div className="space-y-2 rounded-md border bg-muted/30 p-3 text-xs">
      <div className="font-medium">{customer.name} is returning stock</div>
      <div className="space-y-1">
        <Label className="text-xs">Invoice it was bought on</Label>
        <select className="h-8 w-full rounded-md border bg-background px-2" value={pick} onChange={(e) => setPick(e.target.value)}>
          <option value="">{isLoading ? "Loading invoices…" : (invoices ?? []).length ? "Choose the invoice…" : "No invoice found for this product"}</option>
          {(invoices ?? []).map((i: Dict) => {
            const l = i.lines.find((x: Dict) => !sku || x.sku === sku);
            return <option key={`${i.sage ? "s" : "a"}:${i.invoice_number}`} value={`${i.sage ? "s" : "a"}:${i.invoice_number}`}>
              {i.invoice_number} · {fmtDate(i.invoice_date)}{l ? ` · ${num(l.quantity)} @ ₦${Number(l.unit_price ?? 0).toLocaleString()}` : ""}
            </option>;
          })}
        </select>
      </div>
      <div className="grid grid-cols-3 gap-2">
        <div><Label className="text-xs">Quantity back</Label><Input className="h-8" type="number" value={qty} onChange={(e) => setQty(e.target.value)} /></div>
        <div><Label className="text-xs">Credit per unit (₦)</Label><Input className="h-8" type="number" value={price} disabled={!credit} onChange={(e) => setPrice(e.target.value)} /></div>
        <label className="flex items-end gap-2 pb-1.5"><Checkbox checked={credit} onCheckedChange={(v) => setCredit(!!v)} />Credit the customer</label>
      </div>
      {credit && Number(qty) > 0 && Number(price) > 0 && <div className="text-muted-foreground">Credit note of ₦{(Number(qty) * Number(price)).toLocaleString()} against {inv ? `invoice ${inv.invoice_number}` : "the customer's account"}.</div>}
      <div className="flex justify-end gap-2"><Button size="sm" variant="ghost" onClick={onDone}>Cancel</Button>
        <Button size="sm" disabled={busy || !(Number(qty) > 0) || (credit && !(Number(price) > 0))} onClick={save}>Record return</Button></div>
    </div>
  );
}

function RecallSheet({ id, onClose }: { id: string | null; onClose: () => void }) {
  const isQa = useIsQa();
  const refresh = useQualityRefresh();
  const { data: r, refetch } = useQuery({ queryKey: ["quality", "recall", id], queryFn: () => api.quality.recall(id!), enabled: !!id });
  const [due, setDue] = useState("");
  const [returning, setReturning] = useState<Dict | null>(null);
  const [otherCustomer, setOtherCustomer] = useState<Dict | null>(null);
  const b = r?.books;
  const update = async (payload: Dict, ok: string) => { if (await act(() => api.quality.updateRecall(id!, payload), ok, refresh)) refetch(); };
  const item = async (itemId: string, payload: Dict) => {
    if (await act(() => books.patch(`/inventory/recalls/${r.fin_recall_id}/items/${itemId}`, payload), "Updated", refresh)) refetch();
  };
  return (
    <DetailSheet open={!!id} onOpenChange={(o) => !o && onClose()} title={r ? `${r.recall_id} · ${r.product_name}` : "Recall"} icon={PackageX}
                 description={r ? `Batch ${r.batch_number} · ${r.recall_reason}` : undefined}>
      {!r ? <Spinner /> : (
        <div className="space-y-4 text-sm">
          <div className="flex justify-end"><ReportButton type="recall" kind="recall" id={r.id ?? id} label="Write recall report" /></div>
          <Facts items={[["Status", RSTATUS[r.status]?.[0] ?? r.status], ["Severity", r.severity], ["Scope", r.scope], ["Authority", `${r.regulatory_authority ?? "—"}${r.nafdac_notified ? " · notified" : ""}`],
            ["Opened", `${fmtDate(r.initiation_date)} · ${r.created_by_name ?? "—"}`], ["Due back", r.expected_return_date ? fmtDate(r.expected_return_date) : "—"],
            ["ACE Books", r.fin_recall_id ? `${r.fin_recall_number} (${r.fin_status?.toLowerCase()})` : "not linked"],
            ["Units frozen", num(r.units_frozen)], ["Returned", `${num(r.units_returned)} of ${num(r.units_out)}`]]} />
          {isQa && ["initiated", "in_progress"].includes(r.status) && (
            <div className="flex flex-wrap items-end gap-2 rounded-md border p-3">
              {r.status === "initiated" && <Button size="sm" variant="outline" onClick={() => update({ status: "in_progress" }, "Recall in progress")}>Start contacting customers</Button>}
              <Button size="sm" variant="outline" onClick={() => update({ status: "completed" }, "Recall completed · ACE Books recall closed")}>Complete recall</Button>
              <div className="ml-auto flex items-end gap-2">
                <div className="space-y-1"><Label className="text-xs">Stock due back by</Label><Input type="date" className="h-8" value={due || r.expected_return_date || ""} onChange={(e) => setDue(e.target.value)} /></div>
                <Button size="sm" disabled={!due} onClick={() => update({ expected_return_date: due }, "Return date moved (calendar updated)")}>Save</Button>
              </div>
            </div>
          )}
          {b && (
            <div>
              <div className="mb-1 flex items-center justify-between"><span className="text-xs font-semibold uppercase text-muted-foreground">Customers who bought the batch (ACE Books)</span>
                <Link to="/finance/books/stock?tab=recalls" className="inline-flex items-center text-xs text-primary hover:underline">ACE Books <ArrowUpRight className="h-3 w-3" /></Link></div>
              {b.items.length === 0 ? <p className="text-xs text-muted-foreground">No sales of this batch were found: all of it is still in stock (frozen).</p> : (
                <Table>
                  <TableHeader><TableRow><TableHead>Customer</TableHead><TableHead className="text-right">Sold</TableHead><TableHead>Contact</TableHead><TableHead className="text-right">Returned</TableHead><TableHead /></TableRow></TableHeader>
                  <TableBody>{b.items.map((i: Dict) => (
                    <Fragment key={i.id}>
                    <TableRow>
                      <TableCell className="max-w-[180px]"><DrillLink to={i.customer_id ? { type: "customer", id: String(i.customer_id), label: i.customer_name } : null}>{i.customer_name ?? "—"}</DrillLink>
                        <div className="truncate text-[11px] text-muted-foreground" title={i.invoice_number}>{i.invoice_number}</div>
                        {i.credit_note_number && <div className="text-[11px] text-emerald-700">credit {i.credit_note_number} · ₦{Number(i.credit_total ?? 0).toLocaleString()}</div>}</TableCell>
                      <TableCell className="text-right">{num(i.quantity_sold)}</TableCell>
                      <TableCell>{isQa && b.status === "OPEN" ? (
                        <Select value={i.contact_status} onValueChange={(v) => item(i.id, { contact_status: v })}>
                          <SelectTrigger className="h-8 w-[130px]"><SelectValue /></SelectTrigger>
                          <SelectContent>{[["PENDING", "Not contacted"], ["CONTACTED", "Contacted"], ["RETURNED", "Returned"], ["NOT_RETURNED", "Will not return"]].map(([v, l]) =>
                            <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
                        </Select>) : i.contact_status?.toLowerCase().replace("_", " ")}</TableCell>
                      <TableCell className="text-right">{num(i.quantity_returned)}</TableCell>
                      <TableCell>{b.status === "OPEN" && i.customer_id && <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => setReturning(i)}>Record return</Button>}</TableCell>
                    </TableRow>
                    {returning?.id === i.id && (
                      <TableRow className="hover:bg-transparent"><TableCell colSpan={5}>
                        <RecallReturnForm recallId={r.id ?? id!} sku={b.sku} batchId={b.batch_id} itemId={i.id} customer={{ id: i.customer_id, name: i.customer_name }}
                                          onDone={() => { setReturning(null); refetch(); refresh(); }} />
                      </TableCell></TableRow>
                    )}
                    </Fragment>))}</TableBody>
                </Table>
              )}
              {b.status === "OPEN" && (
                <div className="mt-2 space-y-2">
                  {!otherCustomer ? (
                    <div className="flex items-end gap-2"><div className="w-72"><CustomerPick label="Another customer returning it" value={null} onChange={setOtherCustomer} /></div></div>
                  ) : (
                    <RecallReturnForm recallId={r.id ?? id!} sku={b.sku} batchId={b.batch_id} customer={{ id: otherCustomer.id, name: otherCustomer.name }}
                                      onDone={() => { setOtherCustomer(null); refetch(); refresh(); }} />
                  )}
                </div>
              )}
              <p className="mt-2 text-xs text-muted-foreground">Recording a return raises a credit note on the customer's invoice (their balance goes down) and brings the units back into the recalled batch, which stays frozen.</p>
            </div>
          )}
        </div>
      )}
    </DetailSheet>
  );
}

// ---------------------------------------------------------------------------
// Deviations & CAPA (one place; QC and Compliance both use this)
// ---------------------------------------------------------------------------

const CLS: Record<string, "red" | "amber" | "sky"> = { critical: "red", major: "amber", minor: "sky" };
const DSTATUS: Record<string, string> = { open: "Open", under_investigation: "Investigating", escalated: "Escalated", closed: "Closed" };
const TRIGGER: Record<string, string> = {
  manual: "Reported", missed_maintenance: "Maintenance", audit_failure: "Audit finding", inspection_failed: "Inspection", temperature_breach: "Temperature",
  missed_activity: "Missed activity", nafdac_violation: "Regulatory / batch",
};

export function DeviationsPanel() {
  const qa = useQualityActions();
  const { data = [], isLoading } = useQuery({ queryKey: ["quality", "deviations"], queryFn: () => api.quality.deviations() });
  const [filter, setFilter] = useState("open");
  const [picked, setPicked] = useState<Dict | null>(null);
  const rows = useMemo(() => data.filter((d: Dict) => filter === "all" || (filter === "open" ? d.status !== "closed" : filter === "overdue" ? d.overdue || d.capa_overdue > 0 : d.status === filter)), [data, filter]);
  const open = data.filter((d: Dict) => d.status !== "closed");
  return (
    <div className="space-y-4">
      <KpiStrip items={[
        { label: "Open deviations", value: open.length, tone: open.length ? "warning" : "success", sub: `${open.filter((d: Dict) => d.classification === "critical").length} critical · ${open.filter((d: Dict) => d.classification === "major").length} major` },
        { label: "Past their close date", value: open.filter((d: Dict) => d.overdue).length, tone: open.some((d: Dict) => d.overdue) ? "danger" : "success", onClick: () => setFilter("overdue") },
        { label: "CAPA actions overdue", value: open.reduce((s: number, d: Dict) => s + d.capa_overdue, 0), tone: open.some((d: Dict) => d.capa_overdue) ? "danger" : "success" },
        { label: "Closed", value: data.length - open.length, sub: "all time", onClick: () => setFilter("closed") },
      ]} />
      <div className="flex flex-wrap items-center gap-2">
        {[["open", "Open"], ["overdue", "Overdue"], ["closed", "Closed"], ["all", "All"]].map(([k, l]) => (
          <Button key={k} size="sm" className="h-8" variant={filter === k ? "default" : "outline"} onClick={() => setFilter(k)}>{l}</Button>))}
        <Button size="sm" className="ml-auto" onClick={() => qa.open("deviation")}><Plus className="mr-1.5 h-4 w-4" />Raise deviation</Button>
      </div>
      <Card>
        <CardContent className="p-0">
          {isLoading ? <Spinner /> : rows.length === 0 ? <p className="p-6 text-center text-sm text-muted-foreground">No deviations in this view.</p> : (
            <Table>
              <TableHeader><TableRow><TableHead>Deviation</TableHead><TableHead>What happened</TableHead><TableHead>Status</TableHead><TableHead>CAPA</TableHead><TableHead>Close by</TableHead></TableRow></TableHeader>
              <TableBody>{rows.map((d: Dict) => (
                <TableRow key={d.id} className="cursor-pointer" onClick={() => setPicked(d)}>
                  <TableCell><div className="font-medium">{d.deviation_id}</div><div className="flex gap-1"><Tone tone={CLS[d.classification] ?? "sky"}>{d.classification}</Tone>
                    <span className="text-[11px] text-muted-foreground">{TRIGGER[d.trigger_type] ?? d.trigger_type}</span></div></TableCell>
                  <TableCell className="max-w-[320px]"><div className="line-clamp-2 text-xs">{d.observation}</div><div className="text-[11px] text-muted-foreground">{d.responsible_department}{d.responsible_person ? ` · ${d.responsible_person}` : ""}</div></TableCell>
                  <TableCell><Tone tone={d.status === "closed" ? "green" : d.status === "escalated" ? "red" : "amber"}>{DSTATUS[d.status] ?? d.status}</Tone></TableCell>
                  <TableCell className="text-xs">{d.capa_total ? `${d.capa_done}/${d.capa_total} done` : "—"}{d.capa_overdue > 0 && <div className="text-[11px] text-red-600">{d.capa_overdue} overdue</div>}</TableCell>
                  <TableCell className="whitespace-nowrap text-xs">{d.target_close_date ? fmtDate(d.target_close_date) : "—"}{d.overdue && <div className="text-[11px] text-red-600">overdue</div>}</TableCell>
                </TableRow>))}</TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <DeviationSheet dev={picked} onClose={() => setPicked(null)} />
    </div>
  );
}

function DeviationSheet({ dev, onClose }: { dev: Dict | null; onClose: () => void }) {
  const refresh = useQualityRefresh();
  const [f, setF] = useState<Dict>({});
  const [capa, setCapa] = useState<Dict[]>([]);
  const [key, setKey] = useState<string | null>(null);
  if (dev && key !== dev.id) {
    setKey(dev.id);
    setF({ status: dev.status, impact_assessment: dev.impact_assessment ?? "", responsible_person: dev.responsible_person ?? "",
           target_close_date: dev.target_close_date ?? "", resolution: "" });
    setCapa(Array.isArray(dev.capa_actions) ? dev.capa_actions : []);
  }
  const closed = dev?.status === "closed";
  const save = async (extra: Dict = {}, ok = "Deviation updated") => {
    if (await act(() => api.quality.updateDeviation(dev!.id, { status: f.status, impact_assessment: f.impact_assessment, responsible_person: f.responsible_person,
                                                                 target_close_date: f.target_close_date || undefined, capa_actions: capa, ...extra }), ok, refresh)) { setKey(null); onClose(); }
  };
  return (
    <DetailSheet open={!!dev} onOpenChange={(o) => { if (!o) { setKey(null); onClose(); } }} title={dev ? `${dev.deviation_id} · ${dev.classification}` : ""} icon={ShieldCheck}
                 description={dev ? `${TRIGGER[dev.trigger_type] ?? dev.trigger_type} · raised ${fmtDate(dev.investigation_start_date)}` : undefined}>
      {dev && (
        <div className="space-y-3 text-sm">
          <div className="flex justify-end gap-2">
            <ReportButton type="deviation" kind="deviation" id={dev.id} label="Deviation report" />
            {(dev.capa_actions ?? []).length > 0 && <ReportButton type="capa" kind="capa" id={dev.id} label="CAPA report" />}
          </div>
          <p className="rounded bg-muted/40 p-2 text-sm">{dev.observation}</p>
          {closed ? (
            <Facts items={[["Status", "Closed"], ["Closed", fmtDate(dev.closed_at)], ["Resolution", dev.recommendations ?? "—"], ["Owner", dev.responsible_person ?? "—"]]} />
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1"><Label className="text-xs">Status</Label>
                  <Select value={f.status} onValueChange={(v) => setF({ ...f, status: v })}><SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>{["open", "under_investigation", "escalated"].map((s) => <SelectItem key={s} value={s}>{DSTATUS[s]}</SelectItem>)}</SelectContent></Select></div>
                <div className="space-y-1"><Label className="text-xs">Close by</Label><Input type="date" value={f.target_close_date} onChange={(e) => setF({ ...f, target_close_date: e.target.value })} /></div>
                <div className="col-span-2 space-y-1"><Label className="text-xs">Owner</Label><Input value={f.responsible_person} onChange={(e) => setF({ ...f, responsible_person: e.target.value })} /></div>
              </div>
              <div className="space-y-1"><Label className="text-xs">Impact assessment / root cause</Label><Textarea rows={3} value={f.impact_assessment} onChange={(e) => setF({ ...f, impact_assessment: e.target.value })} /></div>
              <CapaEditor rows={capa} onChange={setCapa} />
              {capa.length > 0 && (
                <div className="flex flex-wrap gap-2">{capa.map((c, i) => (
                  <Button key={i} size="sm" variant={["done", "completed"].includes(String(c.status).toLowerCase()) ? "default" : "outline"} className="h-7 text-xs"
                          onClick={() => setCapa(capa.map((x, j) => (j === i ? { ...x, status: ["done", "completed"].includes(String(x.status).toLowerCase()) ? "open" : "done" } : x)))}>
                    {["done", "completed"].includes(String(c.status).toLowerCase()) ? "✓ " : ""}{c.action || `Action ${i + 1}`}</Button>))}</div>
              )}
              <Button className="w-full" variant="outline" onClick={() => save()}>Save</Button>
              <div className="space-y-2 rounded-md border p-3">
                <Label className="text-xs">Resolution (to close)</Label>
                <Textarea rows={2} value={f.resolution} onChange={(e) => setF({ ...f, resolution: e.target.value })} placeholder="What was done and how recurrence is prevented" />
                <Button className="w-full" disabled={(f.resolution ?? "").trim().length < 10} onClick={() => save({ status: "closed", recommendations: f.resolution }, "Deviation closed")}>Close deviation</Button>
              </div>
            </>
          )}
        </div>
      )}
    </DetailSheet>
  );
}
