import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useDrill } from "@/components/books/drill-context";
import { DrillLink } from "@/components/books/kit";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { BooksShell } from "@/components/books/BooksShell";
import {
  act, Amount, BatchPick, CsvButton, CustomerPick, DateRange, Empty, ErrorNote, JournalSheet, Loading, ProductPick, Section,
  StatusBadge, useBooks, useLines,
} from "@/components/books/kit";
import { books, Dict, fmtDate, monthStart, naira, num, today } from "@/lib/books-api";

const REASONS = ["DAMAGE", "EXPIRY", "SHORTAGE", "EXCESS", "COUNT_CORRECTION", "DATA_CORRECTION", "OTHER"];

export default function BooksStock() {
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState(params.get("tab") ?? "status");
  const open = (k: string, v: string | null) => { const p = new URLSearchParams(params); v ? p.set(k, v) : p.delete(k); setParams(p, { replace: true }); };
  return (
    <BooksShell title="Stock"
                actions={<>
                  <Button size="sm" onClick={() => open("new", "adjustment")}><Plus className="mr-1 h-4 w-4" />Adjustment</Button>
                  <Button size="sm" variant="outline" onClick={() => open("new", "loan")}>Lend stock</Button>
                  <Button size="sm" variant="outline" onClick={() => open("new", "count")}>Start stock count</Button>
                </>}>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="flex-wrap">
          <TabsTrigger value="status">Stock status</TabsTrigger>
          <TabsTrigger value="valuation">Valuation</TabsTrigger>
          <TabsTrigger value="activity">Unit activity</TabsTrigger>
          <TabsTrigger value="batches">Batches & expiry</TabsTrigger>
          <TabsTrigger value="adjustments">Adjustments</TabsTrigger>
          <TabsTrigger value="counts">Stock counts</TabsTrigger>
          <TabsTrigger value="loans">Stock on loan</TabsTrigger>
          <TabsTrigger value="recalls">Recalls</TabsTrigger>
        </TabsList>
        <TabsContent value="status"><StockStatus onItem={(sku) => open("item", sku)} /></TabsContent>
        <TabsContent value="valuation"><Valuation /></TabsContent>
        <TabsContent value="activity"><UnitActivity onItem={(sku) => open("item", sku)} /></TabsContent>
        <TabsContent value="batches"><Batches onTrace={(id) => open("batch", id)} /></TabsContent>
        <TabsContent value="adjustments"><AdjustmentList onOpen={(id) => open("adjustment", id)} /></TabsContent>
        <TabsContent value="counts"><CountList onOpen={(id) => open("count", id)} /></TabsContent>
        <TabsContent value="loans"><LoanList onOpen={(id) => open("loan", id)} /></TabsContent>
        <TabsContent value="recalls"><RecallList onOpen={(id) => open("recall", id)} onNew={() => open("new", "recall")} /></TabsContent>
      </Tabs>
      <AdjustmentForm open={params.get("new") === "adjustment"} onClose={(id) => { open("new", null); if (id) open("adjustment", id); }} />
      <LoanForm open={params.get("new") === "loan"} onClose={() => open("new", null)} />
      <CountStart open={params.get("new") === "count"} onClose={(id) => { open("new", null); if (id) open("count", id); }} />
      <RecallForm open={params.get("new") === "recall"} onClose={(id) => { open("new", null); if (id) open("recall", id); }} />
      <AdjustmentDetail id={params.get("adjustment")} onClose={() => open("adjustment", null)} />
      <CountSheet id={params.get("count")} onClose={() => open("count", null)} />
      <LoanDetail id={params.get("loan")} onClose={() => open("loan", null)} />
      <BatchTrace id={params.get("batch")} onClose={() => open("batch", null)} onRecall={() => open("new", "recall")} />
      <RecallDetail id={params.get("recall")} onClose={() => open("recall", null)} />
      <ItemMovements sku={params.get("item")} onClose={() => open("item", null)} />
    </BooksShell>
  );
}

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

function StockStatus({ onItem }: { onItem: (sku: string) => void }) {
  const drill = useDrill();
  const [search, setSearch] = useState("");
  const [show, setShow] = useState("stocked");
  const { data, isLoading, error } = useBooks<Dict[]>(["stock-status"], "/reports/stock-status");
  const rows = useMemo(() => (data ?? []).filter((r) =>
    (!search || `${r.sku} ${r.name}`.toLowerCase().includes(search.toLowerCase())) &&
    (show === "all" || (show === "stocked" ? Number(r.on_hand) !== 0 : show === "low" ? r.reorder_level != null && Number(r.on_hand) <= Number(r.reorder_level) : Number(r.on_hand) < 0))),
  [data, search, show]);
  const soon = new Date(Date.now() + 90 * 864e5).toISOString().slice(0, 10);
  return (
    <Section title={`Stock status (${rows.length})`} actions={<CsvButton filename="stock-status.csv" rows={rows} />}>
      <div className="mb-3 flex flex-wrap gap-2">
        <Input className="h-9 max-w-xs" placeholder="Search SKU or product" value={search} onChange={(e) => setSearch(e.target.value)} />
        <select className="h-9 rounded-md border bg-background px-2 text-sm" value={show} onChange={(e) => setShow(e.target.value)}>
          <option value="stocked">In stock</option><option value="low">At / below reorder level</option><option value="negative">Negative</option><option value="all">All products</option>
        </select>
      </div>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (
        <Table>
          <TableHeader><TableRow><TableHead>SKU</TableHead><TableHead>Product</TableHead><TableHead className="text-right">On hand</TableHead><TableHead className="text-right">Reorder at</TableHead><TableHead>Nearest expiry</TableHead><TableHead className="text-right">Batches</TableHead><TableHead className="text-right">Value</TableHead></TableRow></TableHeader>
          <TableBody>{rows.map((r) => (
            <TableRow key={r.sku} className="cursor-pointer hover:bg-muted/50" onClick={() => (drill ? drill.open({ type: "product", id: r.sku, label: r.sku }) : onItem(r.sku))}>
              <TableCell className="font-mono text-xs">{r.sku}</TableCell><TableCell className="max-w-[260px] truncate">{r.name}</TableCell>
              <TableCell className={`text-right ${Number(r.on_hand) < 0 ? "text-red-600" : r.reorder_level != null && Number(r.on_hand) <= Number(r.reorder_level) ? "text-amber-600" : ""}`}>{num(r.on_hand)}</TableCell>
              <TableCell className="text-right text-muted-foreground">{r.reorder_level != null ? num(r.reorder_level) : "—"}</TableCell>
              <TableCell className={r.nearest_expiry && r.nearest_expiry <= soon ? "text-amber-600" : ""}>{fmtDate(r.nearest_expiry)}</TableCell>
              <TableCell className="text-right">{r.batches}</TableCell><TableCell className="text-right"><Amount value={r.value} /></TableCell>
            </TableRow>
          ))}</TableBody>
        </Table>
      )}
    </Section>
  );
}

function Valuation() {
  const drill = useDrill();
  const [asOf, setAsOf] = useState(today());
  const { data, isLoading, error } = useBooks<any>(["valuation", asOf], "/reports/inventory-valuation", { as_of: asOf });
  return (
    <Section title="Inventory valuation (FIFO)" actions={<CsvButton filename={`inventory-valuation-${asOf}.csv`} rows={data?.rows} />}>
      <DateRange single to={asOf} onChange={(_, t) => setAsOf(t)} />
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (
        <div className="mt-3 space-y-4">
          <div className="flex flex-wrap gap-6 text-sm">
            <div>In the warehouse <div className="text-lg font-bold"><Amount value={data.total_value} /></div></div>
            <div>Out on loan <div className="text-lg font-bold"><Amount value={data.on_loan_value} /></div></div>
          </div>
          <Table>
            <TableHeader><TableRow><TableHead>SKU</TableHead><TableHead>Product</TableHead><TableHead>GL</TableHead><TableHead className="text-right">Qty</TableHead><TableHead className="text-right">Avg cost</TableHead><TableHead className="text-right">Value</TableHead></TableRow></TableHeader>
            <TableBody>
              {data.rows.map((r: Dict) => (
                <TableRow key={r.sku} className="cursor-pointer hover:bg-muted/50" onClick={() => drill?.open({ type: "product", id: r.sku, label: r.sku })}>
                  <TableCell className="font-mono text-xs">{r.sku}</TableCell><TableCell className="max-w-[260px] truncate">{r.name}</TableCell>
                  <TableCell className="text-xs">{r.inventory_account}</TableCell><TableCell className="text-right">{num(r.quantity)}</TableCell>
                  <TableCell className="text-right"><Amount value={r.avg_cost} /></TableCell><TableCell className="text-right"><Amount value={r.value} /></TableCell></TableRow>
              ))}
              <TableRow className="font-semibold"><TableCell colSpan={5}>Total</TableCell><TableCell className="text-right"><Amount value={data.total_value} /></TableCell></TableRow>
            </TableBody>
          </Table>
        </div>
      )}
    </Section>
  );
}

function UnitActivity({ onItem }: { onItem: (sku: string) => void }) {
  const drill = useDrill();
  const [range, setRange] = useState({ from: monthStart(), to: today() });
  const { data, isLoading, error } = useBooks<any>(["unit-activity", range], "/reports/unit-activity", range);
  return (
    <Section title="Inventory unit activity" actions={<CsvButton filename="unit-activity.csv" rows={data?.rows} />}>
      <DateRange from={range.from} to={range.to} onChange={(f, t) => setRange({ from: f ?? range.from, to: t })} />
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (data.rows.length === 0 ? <Empty>No stock movement in this period.</Empty> : (
        <Table className="mt-3">
          <TableHeader><TableRow><TableHead>SKU</TableHead><TableHead className="text-right">Opening</TableHead><TableHead className="text-right">Purchased</TableHead><TableHead className="text-right">Sold</TableHead><TableHead className="text-right">Returns</TableHead><TableHead className="text-right">Loans</TableHead><TableHead className="text-right">Adjusted</TableHead><TableHead className="text-right">Closing</TableHead><TableHead className="text-right">Cost of sales</TableHead></TableRow></TableHeader>
          <TableBody>{data.rows.map((r: Dict) => (
            <TableRow key={r.sku} className="cursor-pointer hover:bg-muted/50" onClick={() => (drill ? drill.open({ type: "product", id: r.sku, label: r.sku }) : onItem(r.sku))}>
              <TableCell><div className="font-mono text-xs">{r.sku}</div><div className="max-w-[200px] truncate text-xs text-muted-foreground">{r.name}</div></TableCell>
              {["opening", "purchased", "sold", "returns", "loans", "adjusted", "closing"].map((k) => <TableCell key={k} className="text-right">{Number(r[k]) ? num(r[k]) : ""}</TableCell>)}
              <TableCell className="text-right"><Amount value={r.cost_of_sales} blankZero /></TableCell>
            </TableRow>
          ))}</TableBody>
        </Table>
      ))}
    </Section>
  );
}

function Batches({ onTrace }: { onTrace: (id: string) => void }) {
  const drill = useDrill();
  const [days, setDays] = useState("");
  const { data, isLoading, error } = useBooks<Dict[]>(["batches", days], "/reports/batches", { expiring_within_days: days || undefined });
  const rows = (data ?? []).filter((b) => Number(b.on_hand) !== 0 || b.status !== "AVAILABLE");
  return (
    <Section title="Batches & expiry" actions={<CsvButton filename="batches.csv" rows={rows} />}>
      <div className="mb-3 flex items-center gap-2 text-sm">
        Expiring within
        <select className="h-9 rounded-md border bg-background px-2" value={days} onChange={(e) => setDays(e.target.value)}>
          <option value="">any time</option><option value="30">30 days</option><option value="90">90 days</option><option value="180">180 days</option><option value="0">already expired</option>
        </select>
      </div>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (rows.length === 0 ? <Empty>No batches.</Empty> : (
        <Table>
          <TableHeader><TableRow><TableHead>SKU</TableHead><TableHead>Batch</TableHead><TableHead>Expiry</TableHead><TableHead>Status</TableHead><TableHead className="text-right">On hand</TableHead><TableHead className="text-right">Value</TableHead></TableRow></TableHeader>
          <TableBody>{rows.map((b) => (
            <TableRow key={b.id} className="cursor-pointer hover:bg-muted/50" onClick={() => (drill ? drill.open({ type: "batch", id: b.id, label: b.batch_number }) : onTrace(b.id))}>
              <TableCell><div className="font-mono text-xs">{b.sku}</div><div className="max-w-[220px] truncate text-xs text-muted-foreground">{b.product_name}</div></TableCell>
              <TableCell className="font-mono text-xs">{b.batch_number}</TableCell>
              <TableCell className={b.expiry_date && b.expiry_date < today() ? "text-red-600" : ""}>{fmtDate(b.expiry_date)}</TableCell>
              <TableCell><StatusBadge status={b.status} /></TableCell><TableCell className="text-right">{num(b.on_hand)}</TableCell>
              <TableCell className="text-right"><Amount value={b.value} /></TableCell>
            </TableRow>
          ))}</TableBody>
        </Table>
      ))}
    </Section>
  );
}

function ItemMovements({ sku, onClose }: { sku: string | null; onClose: () => void }) {
  const [range, setRange] = useState({ from: monthStart(), to: today() });
  const [journal, setJournal] = useState<string | null>(null);
  const { data: res, isLoading, error } = useBooks<Dict>(["movements", sku, range], `/products/${encodeURIComponent(sku ?? "")}/movements`, range, !!sku);
  const data = res?.movements as Dict[] | undefined;
  return (
    <>
      <DetailSheet open={!!sku} onOpenChange={(o) => !o && onClose()} title={`Movements · ${sku ?? ""}`} description={res ? `${res.product?.name ?? ""} · on hand ${num(res.on_hand?.quantity)} (${naira(res.on_hand?.value)})` : "Every stock movement with its batch, party and journal."}>
        <div className="space-y-3 text-sm">
          <DateRange from={range.from} to={range.to} onChange={(f, t) => setRange({ from: f ?? range.from, to: t })} />
          {isLoading && <Loading />}<ErrorNote error={error} />
          {data && (data.length === 0 ? <Empty>No movements in this range.</Empty> : (
            <Table>
              <TableHeader><TableRow><TableHead>Date</TableHead><TableHead>Type</TableHead><TableHead>Batch</TableHead><TableHead className="text-right">Qty</TableHead><TableHead className="text-right">Cost</TableHead></TableRow></TableHeader>
              <TableBody>{data.map((t) => (
                <TableRow key={t.id} className={t.journal_id ? "cursor-pointer hover:bg-muted/50" : ""} onClick={() => t.journal_id && setJournal(t.journal_id)}>
                  <TableCell className="whitespace-nowrap">{fmtDate(t.txn_date)}</TableCell>
                  <TableCell><div className="text-xs">{t.txn_type.replace(/_/g, " ").toLowerCase()} {t.reference}</div><div className="text-xs text-muted-foreground">{t.customer_name ?? t.supplier_name ?? t.reason ?? ""}</div></TableCell>
                  <TableCell className="font-mono text-xs">{t.batch_number}</TableCell>
                  <TableCell className={`text-right ${Number(t.quantity) < 0 ? "text-red-600" : ""}`}>{num(t.quantity)}</TableCell>
                  <TableCell className="text-right"><Amount value={t.total_cost} /></TableCell>
                </TableRow>
              ))}</TableBody>
            </Table>
          ))}
        </div>
      </DetailSheet>
      <JournalSheet id={journal} onClose={() => setJournal(null)} />
    </>
  );
}

// ---------------------------------------------------------------------------
// Adjustments (maker-checker)
// ---------------------------------------------------------------------------

function AdjustmentList({ onOpen }: { onOpen: (id: string) => void }) {
  const { data, isLoading, error } = useBooks<Dict[]>(["adjustments"], "/inventory/adjustments", { limit: 200 });
  return (
    <Section title="Stock adjustments">
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (data.length === 0 ? <Empty>No adjustments yet.</Empty> : (
        <Table>
          <TableHeader><TableRow><TableHead>Number</TableHead><TableHead>Date</TableHead><TableHead>Reason</TableHead><TableHead className="text-right">Lines</TableHead><TableHead className="text-right">Value</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
          <TableBody>{data.map((a) => (
            <TableRow key={a.id} className="cursor-pointer hover:bg-muted/50" onClick={() => onOpen(a.id)}>
              <TableCell className="font-mono text-xs">{a.adjustment_number}</TableCell><TableCell className="whitespace-nowrap">{fmtDate(a.adjustment_date)}</TableCell>
              <TableCell className="text-xs">{a.reason_code.replace(/_/g, " ").toLowerCase()}</TableCell><TableCell className="text-right">{a.lines}</TableCell>
              <TableCell className="text-right"><Amount value={a.total_value} blankZero /></TableCell><TableCell><StatusBadge status={a.status} /></TableCell>
            </TableRow>
          ))}</TableBody>
        </Table>
      ))}
    </Section>
  );
}

type ALine = { product: Dict | null; batch: Dict | null; batch_number: string; quantity: string; unit_cost: string; reason: string };
const blankALine = (): ALine => ({ product: null, batch: null, batch_number: "", quantity: "", unit_cost: "", reason: "" });

function AdjustmentForm({ open, onClose }: { open: boolean; onClose: (id?: string) => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ adjustment_date: today(), reason_code: "DAMAGE", notes: "" });
  const [busy, setBusy] = useState(false);
  const L = useLines<ALine>(blankALine);
  useEffect(() => { if (!open) { L.reset(); setF({ adjustment_date: today(), reason_code: "DAMAGE", notes: "" }); } }, [open]);
  const reduces = ["DAMAGE", "EXPIRY", "SHORTAGE"].includes(f.reason_code);
  const submit = async () => {
    setBusy(true);
    const a = await act(() => books.post("/inventory/adjustments", { ...f,
      lines: L.lines.filter((l) => l.product).map((l) => ({ sku: l.product?.sku, batch_id: l.batch?.id, batch_number: l.batch ? undefined : l.batch_number || undefined,
        quantity: reduces ? -Math.abs(Number(l.quantity)) : Number(l.quantity), unit_cost: l.unit_cost || undefined, reason: l.reason || undefined })) }),
      "Adjustment saved — another person must approve it");
    setBusy(false);
    if (a) { qc.invalidateQueries({ queryKey: ["books"] }); onClose(a.id); }
  };
  return (
    <DetailSheet open={open} onOpenChange={(o) => !o && onClose()} title="Stock adjustment"
                 description="Saved as a draft. A second person approves it, which moves stock and posts the journal."
                 footer={<Button disabled={busy || !L.lines.some((l) => l.product && Number(l.quantity))} onClick={submit}>{busy ? "Saving…" : "Save for approval"}</Button>}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1"><Label className="text-xs">Date</Label><Input type="date" value={f.adjustment_date} onChange={(e) => setF({ ...f, adjustment_date: e.target.value })} /></div>
          <div className="space-y-1"><Label className="text-xs">Reason</Label><select className="h-9 w-full rounded-md border bg-background px-2 text-sm" value={f.reason_code} onChange={(e) => setF({ ...f, reason_code: e.target.value })}>
            {REASONS.map((r) => <option key={r} value={r}>{r.replace(/_/g, " ").toLowerCase()}</option>)}</select></div>
        </div>
        <p className="text-xs text-muted-foreground">{reduces ? "Quantities reduce stock." : "Positive quantities add stock, negative reduce it. Unit cost blank = last cost."}</p>
        {L.lines.map((l, i) => (
          <div key={i} className="space-y-2 rounded-lg border p-2">
            <div className="flex gap-2"><div className="flex-1"><ProductPick value={l.product} onChange={(p) => L.update(i, { product: p })} /></div>
              <Button size="icon" variant="ghost" onClick={() => L.remove(i)}><Trash2 className="h-4 w-4" /></Button></div>
            <div className="grid grid-cols-3 gap-2">
              {reduces ? <BatchPick value={l.batch} onChange={(b) => L.update(i, { batch: b })} label="" />
                : <Input className="h-9" placeholder="Batch no." value={l.batch_number} onChange={(e) => L.update(i, { batch_number: e.target.value })} />}
              <Input className="h-9" type="number" placeholder="Quantity" value={l.quantity} onChange={(e) => L.update(i, { quantity: e.target.value })} />
              {!reduces && <Input className="h-9" type="number" placeholder="Unit cost" value={l.unit_cost} onChange={(e) => L.update(i, { unit_cost: e.target.value })} />}
            </div>
            <Input className="h-8" placeholder="Line note (optional)" value={l.reason} onChange={(e) => L.update(i, { reason: e.target.value })} />
          </div>
        ))}
        <Button size="sm" variant="outline" onClick={L.add}><Plus className="mr-1 h-4 w-4" />Add line</Button>
        <div className="space-y-1"><Label className="text-xs">Notes</Label><Textarea rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></div>
      </div>
    </DetailSheet>
  );
}

function AdjustmentDetail({ id, onClose }: { id: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const { data: a, isLoading, error, refetch } = useBooks<Dict>(["adjustment", id], `/inventory/adjustments/${id}`, undefined, !!id);
  const [journal, setJournal] = useState<string | null>(null);
  const post = async () => { if (await act(() => books.post(`/inventory/adjustments/${id}/post`, {}), "Adjustment approved and posted")) { refetch(); qc.invalidateQueries({ queryKey: ["books"] }); } };
  return (
    <>
      <DetailSheet open={!!id} onOpenChange={(o) => !o && onClose()} title={a ? `Adjustment ${a.adjustment_number}` : ""} description={a?.notes}>
        {isLoading && <Loading />}<ErrorNote error={error} />
        {a && (
          <div className="space-y-3 text-sm">
            <div className="flex items-center gap-2"><StatusBadge status={a.status} /><span className="text-muted-foreground">{fmtDate(a.adjustment_date)} · {a.reason_code.replace(/_/g, " ").toLowerCase()} · raised by {a.created_by}</span></div>
            <Table>
              <TableHeader><TableRow><TableHead>Item</TableHead><TableHead className="text-right">Qty</TableHead><TableHead className="text-right">Value</TableHead></TableRow></TableHeader>
              <TableBody>{a.lines.map((l: Dict) => (
                <TableRow key={l.id}><TableCell><div className="font-mono text-xs">{l.sku} {l.batch_number && `· ${l.batch_number}`}</div><div className="text-xs text-muted-foreground">{l.product_name}{l.reason ? ` — ${l.reason}` : ""}</div></TableCell>
                  <TableCell className={`text-right ${Number(l.quantity) < 0 ? "text-red-600" : ""}`}>{num(l.quantity)}</TableCell><TableCell className="text-right"><Amount value={l.value} blankZero /></TableCell></TableRow>
              ))}</TableBody>
            </Table>
            <div className="flex gap-2">
              {a.status === "DRAFT" && <Button size="sm" onClick={post}>Approve & post</Button>}
              {a.journal_id && <Button size="sm" variant="outline" onClick={() => setJournal(a.journal_id)}>View journal</Button>}
            </div>
          </div>
        )}
      </DetailSheet>
      <JournalSheet id={journal} onClose={() => setJournal(null)} />
    </>
  );
}

// ---------------------------------------------------------------------------
// Stock counts
// ---------------------------------------------------------------------------

function CountList({ onOpen }: { onOpen: (id: string) => void }) {
  const { data, isLoading, error } = useBooks<Dict[]>(["counts"], "/inventory/counts");
  return (
    <Section title="Stock counts">
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (data.length === 0 ? <Empty>No stock counts yet. A count corrects negative or drifting stock and posts the difference.</Empty> : (
        <Table>
          <TableHeader><TableRow><TableHead>Number</TableHead><TableHead>Date</TableHead><TableHead className="text-right">Lines</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
          <TableBody>{data.map((c) => (
            <TableRow key={c.id} className="cursor-pointer hover:bg-muted/50" onClick={() => onOpen(c.id)}>
              <TableCell className="font-mono text-xs">{c.count_number}</TableCell><TableCell className="whitespace-nowrap">{fmtDate(c.count_date)}</TableCell>
              <TableCell className="text-right">{c.lines}</TableCell><TableCell><StatusBadge status={c.status} /></TableCell>
            </TableRow>
          ))}</TableBody>
        </Table>
      ))}
    </Section>
  );
}

function CountStart({ open, onClose }: { open: boolean; onClose: (id?: string) => void }) {
  const [date, setDate] = useState(today());
  const [skus, setSkus] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    const c = await act(() => books.post("/inventory/counts", { count_date: date, skus: skus.trim() ? skus.split(/[\s,]+/).filter(Boolean) : undefined }), "Count sheet created");
    setBusy(false);
    if (c) onClose(c.id);
  };
  return (
    <DetailSheet open={open} onOpenChange={(o) => !o && onClose()} title="Start a stock count"
                 description="Takes a snapshot of system quantity per item & batch. Enter what is physically counted, then a second person posts the variances."
                 footer={<Button disabled={busy} onClick={submit}>{busy ? "Creating…" : "Create count sheet"}</Button>}>
      <div className="space-y-3">
        <div className="space-y-1"><Label className="text-xs">Count date</Label><Input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></div>
        <div className="space-y-1"><Label className="text-xs">Only these SKUs (optional, comma or space separated)</Label><Textarea rows={3} value={skus} onChange={(e) => setSkus(e.target.value)} placeholder="Leave blank to count everything with a balance" /></div>
      </div>
    </DetailSheet>
  );
}

function CountSheet({ id, onClose }: { id: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const { data: c, isLoading, error, refetch } = useBooks<Dict>(["count", id], `/inventory/counts/${id}`, undefined, !!id);
  const [edits, setEdits] = useState<Record<string, { counted_qty: string; reason: string }>>({});
  const [filter, setFilter] = useState("");
  useEffect(() => setEdits({}), [id]);
  const draft = c?.status === "DRAFT";
  const save = async () => {
    const lines = Object.entries(edits).map(([lid, v]) => ({ id: lid, ...v }));
    if (lines.length && (await act(() => books.put(`/inventory/counts/${id}/lines`, { lines }), "Counts saved"))) { setEdits({}); refetch(); }
  };
  const post = async () => {
    if (Object.keys(edits).length) await save();
    if (await act(() => books.post(`/inventory/counts/${id}/post`, {}), "Count posted")) { refetch(); qc.invalidateQueries({ queryKey: ["books"] }); }
  };
  const lines = (c?.lines ?? []).filter((l: Dict) => !filter || `${l.sku} ${l.product_name} ${l.batch_number}`.toLowerCase().includes(filter.toLowerCase()));
  const val = (l: Dict, k: "counted_qty" | "reason") => edits[l.id]?.[k] ?? (l[k] ?? "");
  const set = (l: Dict, k: "counted_qty" | "reason", v: string) =>
    setEdits({ ...edits, [l.id]: { counted_qty: String(val(l, "counted_qty")), reason: String(val(l, "reason")), [k]: v } });
  return (
    <DetailSheet open={!!id} onOpenChange={(o) => !o && onClose()} title={c ? `Stock count ${c.count_number}` : ""} description={c ? `${fmtDate(c.count_date)} · ${c.lines?.length ?? 0} lines` : ""}
                 footer={draft ? <div className="flex gap-2"><Button variant="outline" disabled={!Object.keys(edits).length} onClick={save}>Save counts</Button><Button onClick={post}>Post variances</Button></div> : undefined}>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {c && (
        <div className="space-y-3 text-sm">
          <div className="flex items-center gap-2"><StatusBadge status={c.status} />{draft && <Button size="sm" variant="ghost" onClick={() => {
            const e = { ...edits }; (c.lines as Dict[]).forEach((l) => { if (l.counted_qty == null && !e[l.id]) e[l.id] = { counted_qty: String(l.system_qty), reason: "" }; }); setEdits(e);
          }}>Fill blanks with system qty</Button>}</div>
          <Input className="h-9" placeholder="Filter" value={filter} onChange={(e) => setFilter(e.target.value)} />
          <Table>
            <TableHeader><TableRow><TableHead>Item / batch</TableHead><TableHead className="text-right">System</TableHead><TableHead className="w-24">Counted</TableHead><TableHead className="text-right">Variance</TableHead></TableRow></TableHeader>
            <TableBody>{lines.map((l: Dict) => {
              const counted = val(l, "counted_qty");
              const variance = counted === "" ? null : Number(counted) - Number(l.system_qty);
              return (
                <TableRow key={l.id}>
                  <TableCell><div className="font-mono text-xs">{l.sku} {l.batch_number && `· ${l.batch_number}`}</div><div className="max-w-[200px] truncate text-xs text-muted-foreground">{l.product_name}</div></TableCell>
                  <TableCell className="text-right">{num(l.system_qty)}</TableCell>
                  <TableCell>{draft ? <Input className="h-8" type="number" value={counted} onChange={(e) => set(l, "counted_qty", e.target.value)} /> : num(l.counted_qty)}</TableCell>
                  <TableCell className={`text-right ${variance ? (variance < 0 ? "text-red-600" : "text-emerald-600") : ""}`}>{variance == null ? "—" : num(variance)}</TableCell>
                </TableRow>
              );
            })}</TableBody>
          </Table>
          {c.adjustment_id && <p className="text-xs text-muted-foreground">Variances posted as a count-correction adjustment.</p>}
        </div>
      )}
    </DetailSheet>
  );
}

// ---------------------------------------------------------------------------
// Loans
// ---------------------------------------------------------------------------

function LoanList({ onOpen }: { onOpen: (id: string) => void }) {
  const [status, setStatus] = useState("OPEN,PARTIALLY_RETURNED");
  const { data, isLoading, error } = useBooks<Dict[]>(["loans", status], "/inventory/loans", { status: status || undefined });
  return (
    <Section title="Stock on loan" actions={<select className="h-8 rounded-md border bg-background px-2 text-xs" value={status} onChange={(e) => setStatus(e.target.value)}>
      <option value="OPEN,PARTIALLY_RETURNED">Outstanding</option><option value="">All</option></select>}>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (data.length === 0 ? <Empty>No stock out on loan.</Empty> : (
        <Table>
          <TableHeader><TableRow><TableHead>Loan</TableHead><TableHead>Date</TableHead><TableHead>Customer</TableHead><TableHead>Item / batch</TableHead><TableHead className="text-right">Out</TableHead><TableHead>Due back</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
          <TableBody>{data.map((l) => (
            <TableRow key={l.id} className="cursor-pointer hover:bg-muted/50" onClick={() => onOpen(l.id)}>
              <TableCell className="font-mono text-xs">{l.loan_number}</TableCell><TableCell className="whitespace-nowrap">{fmtDate(l.loan_date)}</TableCell><TableCell><DrillLink to={{ type: "customer", id: String(l.customer_id ?? ""), label: l.customer_name }}>{l.customer_name}</DrillLink></TableCell>
              <TableCell className="font-mono text-xs">{l.sku} {l.batch_number && `· ${l.batch_number}`}</TableCell>
              <TableCell className="text-right">{num(l.outstanding)} / {num(l.quantity)}</TableCell>
              <TableCell className={l.expected_return_date && l.expected_return_date < today() && Number(l.outstanding) > 0 ? "text-red-600" : ""}>{fmtDate(l.expected_return_date)}</TableCell>
              <TableCell><StatusBadge status={l.status} /></TableCell>
            </TableRow>
          ))}</TableBody>
        </Table>
      ))}
    </Section>
  );
}

function LoanForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [customer, setCustomer] = useState<Dict | null>(null);
  const [product, setProduct] = useState<Dict | null>(null);
  const [batch, setBatch] = useState<Dict | null>(null);
  const [f, setF] = useState({ quantity: "", loan_date: today(), expected_return_date: "", notes: "" });
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (!open) { setCustomer(null); setProduct(null); setBatch(null); setF({ quantity: "", loan_date: today(), expected_return_date: "", notes: "" }); } }, [open]);
  const submit = async () => {
    setBusy(true);
    const ok = await act(() => books.post("/inventory/loans", { ...f, customer_id: customer?.id, sku: product?.sku ?? batch?.sku, batch_id: batch?.id,
      expected_return_date: f.expected_return_date || undefined }), "Stock loaned");
    setBusy(false);
    if (ok) { qc.invalidateQueries({ queryKey: ["books"] }); onClose(); }
  };
  return (
    <DetailSheet open={open} onOpenChange={(o) => !o && onClose()} title="Lend stock to a customer"
                 description="Not a sale: stock moves to 'stock on loan' at cost until it is returned (any batch) or written off."
                 footer={<Button disabled={busy || !customer || !(product || batch) || Number(f.quantity) <= 0} onClick={submit}>{busy ? "Posting…" : "Post loan"}</Button>}>
      <div className="space-y-3">
        <CustomerPick value={customer} onChange={setCustomer} />
        <ProductPick label="Product" value={product} onChange={setProduct} />
        <BatchPick label="Batch (optional — FIFO if blank)" value={batch} onChange={setBatch} />
        <div className="grid grid-cols-3 gap-3">
          <div className="space-y-1"><Label className="text-xs">Quantity</Label><Input type="number" value={f.quantity} onChange={(e) => setF({ ...f, quantity: e.target.value })} /></div>
          <div className="space-y-1"><Label className="text-xs">Date</Label><Input type="date" value={f.loan_date} onChange={(e) => setF({ ...f, loan_date: e.target.value })} /></div>
          <div className="space-y-1"><Label className="text-xs">Expected back</Label><Input type="date" value={f.expected_return_date} onChange={(e) => setF({ ...f, expected_return_date: e.target.value })} /></div>
        </div>
        <div className="space-y-1"><Label className="text-xs">Notes</Label><Textarea rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></div>
      </div>
    </DetailSheet>
  );
}

function LoanDetail({ id, onClose }: { id: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const { data: l, isLoading, error, refetch } = useBooks<Dict>(["loan", id], `/inventory/loans/${id}`, undefined, !!id);
  const [r, setR] = useState({ quantity: "", return_date: today(), batch_number: "", expiry_date: "", notes: "" });
  const [journal, setJournal] = useState<string | null>(null);
  const done = () => { refetch(); qc.invalidateQueries({ queryKey: ["books"] }); };
  const ret = async () => {
    if (await act(() => books.post(`/inventory/loans/${id}/return`, { ...r, batch_number: r.batch_number || undefined, expiry_date: r.expiry_date || undefined }), "Return recorded")) {
      setR({ quantity: "", return_date: today(), batch_number: "", expiry_date: "", notes: "" }); done();
    }
  };
  const writeOff = async () => {
    const reason = window.prompt("Why is the outstanding stock being written off?");
    if (reason && (await act(() => books.post(`/inventory/loans/${id}/write-off`, { reason, on: today() }), "Written off"))) done();
  };
  const outstanding = l && ["OPEN", "PARTIALLY_RETURNED"].includes(l.status);
  return (
    <>
      <DetailSheet open={!!id} onOpenChange={(o) => !o && onClose()} title={l ? `Loan ${l.loan_number}` : ""} description={l ? `${l.customer_name} · ${l.sku} ${l.product_name ?? ""}` : ""}>
        {isLoading && <Loading />}<ErrorNote error={error} />
        {l && (
          <div className="space-y-4 text-sm">
            <div className="flex flex-wrap items-center gap-2"><StatusBadge status={l.status} /><span className="text-muted-foreground">{fmtDate(l.loan_date)} · batch {l.batch_number ?? "FIFO"} · at {naira(l.unit_cost)} each</span></div>
            <div className="grid grid-cols-3 gap-2"><div>Lent<div className="font-semibold">{num(l.quantity)}</div></div><div>Returned<div className="font-semibold">{num(l.quantity_returned)}</div></div><div>Still out<div className="font-semibold">{num(l.outstanding)}</div></div></div>
            {l.returns.length > 0 && (
              <Table><TableBody>{l.returns.map((x: Dict) => <TableRow key={x.id}><TableCell className="whitespace-nowrap">{fmtDate(x.return_date)}</TableCell><TableCell className="font-mono text-xs">{x.batch_number}</TableCell><TableCell className="text-right">{num(x.quantity)}</TableCell></TableRow>)}</TableBody></Table>
            )}
            {outstanding && (
              <div className="space-y-2 rounded-lg border p-3">
                <div className="text-xs font-semibold uppercase text-muted-foreground">Record a return</div>
                <div className="grid grid-cols-2 gap-2">
                  <Input type="number" placeholder="Quantity" value={r.quantity} onChange={(e) => setR({ ...r, quantity: e.target.value })} />
                  <Input type="date" value={r.return_date} onChange={(e) => setR({ ...r, return_date: e.target.value })} />
                  <Input placeholder="Batch returned (blank = same)" value={r.batch_number} onChange={(e) => setR({ ...r, batch_number: e.target.value })} />
                  <Input type="date" title="Expiry of returned batch" value={r.expiry_date} onChange={(e) => setR({ ...r, expiry_date: e.target.value })} />
                </div>
                <div className="flex gap-2"><Button size="sm" disabled={Number(r.quantity) <= 0} onClick={ret}>Record return</Button><Button size="sm" variant="destructive" onClick={writeOff}>Write off remainder</Button></div>
              </div>
            )}
            {l.notes && <p className="whitespace-pre-line text-xs text-muted-foreground">{l.notes}</p>}
          </div>
        )}
      </DetailSheet>
      <JournalSheet id={journal} onClose={() => setJournal(null)} />
    </>
  );
}

// ---------------------------------------------------------------------------
// Batch trace & recalls
// ---------------------------------------------------------------------------

function BatchTrace({ id, onClose, onRecall }: { id: string | null; onClose: () => void; onRecall: () => void }) {
  const qc = useQueryClient();
  const { data, isLoading, error, refetch } = useBooks<Dict>(["trace", id], `/inventory/batches/${id}/trace`, undefined, !!id);
  const b = data?.batch;
  const setStatus = async (status: string) => {
    const reason = window.prompt(`Reason for marking this batch ${status.toLowerCase()}?`);
    if (reason && (await act(() => books.post(`/inventory/batches/${id}/status`, { status, reason }), "Batch updated"))) { refetch(); qc.invalidateQueries({ queryKey: ["books"] }); }
  };
  return (
    <DetailSheet open={!!id} onOpenChange={(o) => !o && onClose()} title={b ? `Batch ${b.batch_number}` : "Batch"} description={b ? `${b.sku} · ${b.product_name ?? ""}` : ""}>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && b && (
        <div className="space-y-4 text-sm">
          <div className="flex flex-wrap items-center gap-2"><StatusBadge status={b.status} /><span className="text-muted-foreground">expires {fmtDate(b.expiry_date)} · on hand {num(data.on_hand?.quantity)}</span></div>
          <div className="flex flex-wrap gap-2">
            {b.status !== "RECALLED" && <Button size="sm" variant="destructive" onClick={onRecall}>Open recall</Button>}
            {b.status === "AVAILABLE" ? <Button size="sm" variant="outline" onClick={() => setStatus("QUARANTINED")}>Quarantine</Button>
              : <Button size="sm" variant="outline" onClick={() => setStatus("AVAILABLE")}>Release (available)</Button>}
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">Who has this batch</div>
            {data.customers.length === 0 ? <Empty>No customer has received this batch.</Empty> : (
              <Table><TableHeader><TableRow><TableHead>Customer</TableHead><TableHead className="text-right">Sold</TableHead><TableHead className="text-right">On loan</TableHead><TableHead>Documents</TableHead></TableRow></TableHeader>
                <TableBody>{data.customers.map((c: Dict) => (
                  <TableRow key={c.customer_id}><TableCell><DrillLink to={{ type: "customer", id: String(c.customer_id), label: c.customer_name }}>{c.customer_name}</DrillLink></TableCell><TableCell className="text-right">{num(c.quantity_sold)}</TableCell><TableCell className="text-right">{num(c.quantity_on_loan)}</TableCell>
                    <TableCell className="max-w-[160px] truncate font-mono text-[11px]">{(c.documents ?? []).join(", ")}</TableCell></TableRow>
                ))}</TableBody></Table>
            )}
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">Movements</div>
            <Table><TableBody>{data.movements.map((m: Dict) => (
              <TableRow key={m.id}><TableCell className="whitespace-nowrap">{fmtDate(m.txn_date)}</TableCell><TableCell className="text-xs">{m.txn_type.replace(/_/g, " ").toLowerCase()} {m.reference}<div className="text-muted-foreground">{m.customer_name ?? m.supplier_name}</div></TableCell>
                <TableCell className={`text-right ${Number(m.quantity) < 0 ? "text-red-600" : ""}`}>{num(m.quantity)}</TableCell></TableRow>
            ))}</TableBody></Table>
          </div>
        </div>
      )}
    </DetailSheet>
  );
}

function RecallList({ onOpen, onNew }: { onOpen: (id: string) => void; onNew: () => void }) {
  const { data, isLoading, error } = useBooks<Dict[]>(["recalls"], "/inventory/recalls");
  return (
    <Section title="Recalls" actions={<Button size="sm" variant="outline" onClick={onNew}>Open recall</Button>}>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (data.length === 0 ? <Empty>No recalls.</Empty> : (
        <Table>
          <TableHeader><TableRow><TableHead>Recall</TableHead><TableHead>Opened</TableHead><TableHead>Item / batch</TableHead><TableHead>Reason</TableHead><TableHead className="text-right">Customers</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
          <TableBody>{data.map((r) => (
            <TableRow key={r.id} className="cursor-pointer hover:bg-muted/50" onClick={() => onOpen(r.id)}>
              <TableCell className="font-mono text-xs">{r.recall_number}</TableCell><TableCell className="whitespace-nowrap">{fmtDate(r.opened_at)}</TableCell>
              <TableCell className="font-mono text-xs">{r.sku} · {r.batch_number}</TableCell><TableCell className="max-w-[220px] truncate text-xs">{r.reason}</TableCell>
              <TableCell className="text-right">{r.customers}</TableCell><TableCell><StatusBadge status={r.status} /></TableCell>
            </TableRow>
          ))}</TableBody>
        </Table>
      ))}
    </Section>
  );
}

function RecallForm({ open, onClose }: { open: boolean; onClose: (id?: string) => void }) {
  const qc = useQueryClient();
  const [batch, setBatch] = useState<Dict | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (!open) { setBatch(null); setReason(""); } }, [open]);
  const submit = async () => {
    setBusy(true);
    const r = await act(() => books.post("/inventory/recalls", { batch_id: batch?.id, reason }), "Recall opened — batch frozen");
    setBusy(false);
    if (r) { qc.invalidateQueries({ queryKey: ["books"] }); onClose(r.id); }
  };
  return (
    <DetailSheet open={open} onOpenChange={(o) => !o && onClose()} title="Open a recall"
                 description="Freezes the batch (it can no longer be sold) and lists every customer who received it."
                 footer={<Button variant="destructive" disabled={busy || !batch || !reason.trim()} onClick={submit}>{busy ? "Opening…" : "Open recall"}</Button>}>
      <div className="space-y-3">
        <BatchPick value={batch} onChange={setBatch} />
        <div className="space-y-1"><Label className="text-xs">Reason</Label><Textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Manufacturer recall notice ref …" /></div>
      </div>
    </DetailSheet>
  );
}

function RecallDetail({ id, onClose }: { id: string | null; onClose: () => void }) {
  const { data: r, isLoading, error, refetch } = useBooks<Dict>(["recall", id], `/inventory/recalls/${id}`, undefined, !!id);
  const update = async (item: Dict, patch: Dict) => { if (await act(() => books.patch(`/inventory/recalls/${id}/items/${item.id}`, patch))) refetch(); };
  const close = async () => {
    const notes = window.prompt("Closing notes (optional)") ?? undefined;
    if (await act(() => books.post(`/inventory/recalls/${id}/close`, { notes }), "Recall closed")) refetch();
  };
  const isOpen = r?.status === "OPEN";
  return (
    <DetailSheet open={!!id} onOpenChange={(o) => !o && onClose()} title={r ? `Recall ${r.recall_number}` : ""} description={r ? `${r.sku} ${r.product_name ?? ""} · batch ${r.batch_number}` : ""}
                 footer={isOpen ? <Button variant="outline" onClick={close}>Close recall</Button> : undefined}>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {r && (
        <div className="space-y-3 text-sm">
          <div className="flex items-center gap-2"><StatusBadge status={r.status} /><span className="text-muted-foreground">{r.reason} · still in stock {num(r.on_hand?.quantity)}</span></div>
          <CsvButton filename={`recall-${r.recall_number}.csv`} rows={r.items} />
          {r.items.length === 0 ? <Empty>No customer received this batch.</Empty> : (
            <Table>
              <TableHeader><TableRow><TableHead>Customer</TableHead><TableHead className="text-right">Supplied</TableHead><TableHead className="w-20">Returned</TableHead><TableHead>Contact</TableHead></TableRow></TableHeader>
              <TableBody>{r.items.map((i: Dict) => (
                <TableRow key={i.id}>
                  <TableCell><div><DrillLink to={{ type: "customer", id: String(i.customer_id ?? ""), label: i.customer_name }}>{i.customer_name}</DrillLink></div><div className="max-w-[180px] truncate font-mono text-[11px] text-muted-foreground">{i.invoice_number}</div></TableCell>
                  <TableCell className="text-right">{num(i.quantity_sold)}</TableCell>
                  <TableCell>{isOpen ? <Input className="h-8" type="number" defaultValue={i.quantity_returned} onBlur={(e) => e.target.value !== String(i.quantity_returned) && update(i, { quantity_returned: e.target.value })} /> : num(i.quantity_returned)}</TableCell>
                  <TableCell>{isOpen ? (
                    <select className="h-8 rounded-md border bg-background px-1 text-xs" value={i.contact_status} onChange={(e) => update(i, { contact_status: e.target.value })}>
                      {["PENDING", "CONTACTED", "RETURNED", "NOT_RETURNED"].map((s) => <option key={s} value={s}>{s.replace(/_/g, " ").toLowerCase()}</option>)}
                    </select>) : <StatusBadge status={i.contact_status} />}</TableCell>
                </TableRow>
              ))}</TableBody>
            </Table>
          )}
        </div>
      )}
    </DetailSheet>
  );
}
