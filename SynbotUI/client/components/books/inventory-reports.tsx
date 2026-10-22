/**
 * Stock reports as the client ran them in Sage (finance meeting 4, 19 Oct 2026), across Sage history
 * and ACE Books (backend fin/inventory_reports.py):
 *  - Inventory Unit Activity: beginning qty, units sold, units purchased, adjust qty, qty on hand.
 *  - Item Costing: each item's movements in date order - received (with item cost), adjusted, sold,
 *    remaining - and the customer / supplier and document behind each, so "who did we sell these ten
 *    to?" is one click (the invoice opens in a panel).
 * Used on ACE Books -> Stock and on Inventory & Quality -> Stock. Columns can be shown or hidden
 * (as Sage's Options -> Columns), and every report prints and exports to CSV.
 */
import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Columns3, Printer } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Dict, fmtDate, naira, num, today } from "@/lib/books-api";
import { CsvButton, DateRange, DrillLink, Empty, ErrorNote, Loading, SageTag, useBooks } from "./kit";
import type { DrillTarget } from "./drill-context";

// ---------------------------------------------------------------------------
// shared bits: period with quarters, item filter, column chooser, print
// ---------------------------------------------------------------------------

const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
function quarters(): { label: string; from: string; to: string }[] {
  const now = new Date(); const out = [];
  let y = now.getFullYear(), qn = Math.floor(now.getMonth() / 3);
  for (let i = 0; i < 6; i++) {
    out.push({ label: `Q${qn + 1} ${y} (${["Jan–Mar", "Apr–Jun", "Jul–Sep", "Oct–Dec"][qn]})`,
               from: ymd(new Date(y, qn * 3, 1)), to: ymd(new Date(y, qn * 3 + 3, 0)) });
    qn -= 1; if (qn < 0) { qn = 3; y -= 1; }
  }
  return out;
}

type Period = { from: string; to: string };
function PeriodPicker({ value, onChange }: { value: Period; onChange: (p: Period) => void }) {
  const qs = useMemo(quarters, []);
  return (
    <div className="flex flex-wrap items-end gap-2">
      <DateRange from={value.from} to={value.to} onChange={(f, t) => onChange({ from: f ?? value.from, to: t })} />
      <select className="h-9 rounded-md px-2 text-xs" value="" aria-label="Quarter"
              onChange={(e) => { const q = qs[Number(e.target.value)]; if (q) onChange({ from: q.from, to: q.to }); }}>
        <option value="">Quarter…</option>
        {qs.map((q, i) => <option key={q.label} value={i}>{q.label}</option>)}
      </select>
    </div>
  );
}

type ItemFilter = { search: string; sku_from: string; sku_to: string };
function ItemFilterBar({ value, onChange }: { value: ItemFilter; onChange: (v: ItemFilter) => void }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  const apply = () => onChange(v);
  return (
    <div className="flex flex-wrap items-end gap-2">
      <div className="space-y-1"><Label className="text-xs">Item (ID or name contains)</Label>
        <Input className="h-9 w-56" placeholder="e.g. CERVARIX" value={v.search} onChange={(e) => setV({ ...v, search: e.target.value })}
               onKeyDown={(e) => e.key === "Enter" && apply()} /></div>
      <div className="space-y-1"><Label className="text-xs">Item IDs from</Label>
        <Input className="h-9 w-44" placeholder="CERVARIX 0.5ml(E)" value={v.sku_from} onChange={(e) => setV({ ...v, sku_from: e.target.value })}
               onKeyDown={(e) => e.key === "Enter" && apply()} /></div>
      <div className="space-y-1"><Label className="text-xs">to</Label>
        <Input className="h-9 w-44" placeholder="CERVARIX 0.5ml(H)" value={v.sku_to} onChange={(e) => setV({ ...v, sku_to: e.target.value })}
               onKeyDown={(e) => e.key === "Enter" && apply()} /></div>
      <Button size="sm" className="h-9" onClick={apply}>Show</Button>
      {(value.search || value.sku_from || value.sku_to) && <Button size="sm" variant="ghost" className="h-9" onClick={() => onChange({ search: "", sku_from: "", sku_to: "" })}>Clear</Button>}
    </div>
  );
}

type Col = { key: string; label: string; on: boolean };
/** Sage's Options -> Columns: tick what to show; remembered on this computer. */
function useColumns(storeKey: string, defaults: Col[]) {
  const [cols, setCols] = useState<Col[]>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(storeKey) || "null") as Record<string, boolean> | null;
      if (saved) return defaults.map((c) => ({ ...c, on: saved[c.key] ?? c.on }));
    } catch { /* storage unavailable */ }
    return defaults;
  });
  const toggle = (key: string) => setCols((cs) => {
    const next = cs.map((c) => (c.key === key ? { ...c, on: !c.on } : c));
    try { localStorage.setItem(storeKey, JSON.stringify(Object.fromEntries(next.map((c) => [c.key, c.on])))); } catch { /* ignore */ }
    return next;
  });
  const show = (key: string) => cols.find((c) => c.key === key)?.on ?? true;
  const menu = (
    <DropdownMenu>
      <DropdownMenuTrigger asChild><Button size="sm" variant="outline"><Columns3 className="mr-1 h-4 w-4" />Columns</Button></DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>Show columns</DropdownMenuLabel><DropdownMenuSeparator />
        {cols.map((c) => <DropdownMenuCheckboxItem key={c.key} checked={c.on} onSelect={(e) => e.preventDefault()} onCheckedChange={() => toggle(c.key)}>{c.label}</DropdownMenuCheckboxItem>)}
      </DropdownMenuContent>
    </DropdownMenu>
  );
  return { show, menu };
}

/** Print the report as shown (title, period, the table) in a clean window. */
function printReport(title: string, subtitle: string, node: HTMLElement | null) {
  if (!node) return;
  const win = window.open("", "_blank", "width=1100,height=800");
  if (!win) return;
  const clone = node.cloneNode(true) as HTMLElement;
  clone.querySelectorAll("[data-noprint]").forEach((n) => n.remove());
  win.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${title}</title><style>
    body{font-family:Arial,Helvetica,sans-serif;color:#111;margin:24px;font-size:11px}
    h1{font-size:16px;margin:0;text-align:center} h2{font-size:12px;margin:2px 0 12px;text-align:center;font-weight:normal}
    table{width:100%;border-collapse:collapse} th,td{padding:4px 6px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}
    th{border-bottom:2px solid #333;font-size:10px;text-transform:uppercase} .text-right{text-align:right}
    a{color:#111;text-decoration:none} button{display:none}
  </style></head><body><div style="text-align:center;font-weight:bold">PLACEWARE NIGERIA LIMITED</div><h1></h1><h2></h2></body></html>`);
  win.document.querySelector("h1")!.textContent = title;
  win.document.querySelector("h2")!.textContent = subtitle;
  win.document.body.appendChild(win.document.importNode(clone, true));
  win.document.close();
  win.focus();
  setTimeout(() => win.print(), 300);
}

const q = (v: any, dp = 2) => (v === null || v === undefined || v === "" ? "" : num(v, dp));
const periodText = (p: Period) => `For the period from ${fmtDate(p.from)} to ${fmtDate(p.to)}`;
const yearStartStr = () => `${new Date().getFullYear()}-01-01`;

// ---------------------------------------------------------------------------
// Inventory Unit Activity
// ---------------------------------------------------------------------------

export function UnitActivityReport({ period, setPeriod, filter, setFilter, onItem }: {
  period: Period; setPeriod: (p: Period) => void; filter: ItemFilter; setFilter: (f: ItemFilter) => void; onItem?: (sku: string) => void;
}) {
  const [all, setAll] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { show, menu } = useColumns("ace.unitActivity.cols", [
    { key: "beg", label: "Beg Qty", on: true }, { key: "sold", label: "Units Sold", on: true }, { key: "purchased", label: "Units Purchased", on: true },
    { key: "adjusted", label: "Adjust Qty", on: true }, { key: "loans", label: "Lent / returned", on: false }, { key: "on_hand", label: "Qty on Hand", on: true },
    { key: "cos", label: "Cost of sales", on: false }, { key: "pc", label: "Purchase cost", on: false },
  ]);
  const { data, isLoading, error } = useBooks<Dict>(["inv-unit-activity", period, filter, all], "/inventory/unit-activity",
    { from: period.from, to: period.to, search: filter.search || undefined, sku_from: filter.sku_from || undefined, sku_to: filter.sku_to || undefined, include_inactive: all || undefined });
  const rows: Dict[] = data?.rows ?? [];
  const t = data?.totals ?? {};
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-wrap items-end gap-3"><PeriodPicker value={period} onChange={setPeriod} /><ItemFilterBar value={filter} onChange={setFilter} /></div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />Include items with no activity</label>
          {menu}
          <Button size="sm" variant="outline" onClick={() => printReport("Inventory Unit Activity Report", periodText(period), ref.current)}><Printer className="mr-1 h-4 w-4" />Print</Button>
          <CsvButton filename={`unit-activity-${period.from}-${period.to}.csv`} rows={rows} />
        </div>
      </div>
      <p className="text-xs text-muted-foreground">Units sold include customer returns (as negatives), as in Sage. Click an item to see every movement behind its figures (Item costing).</p>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (rows.length === 0 ? <Empty>No stock activity for these items in this period.</Empty> : (
        <div ref={ref}>
          <Table>
            <TableHeader><TableRow>
              <TableHead>Item ID / description</TableHead>
              {show("beg") && <TableHead className="text-right">Beg Qty</TableHead>}
              {show("sold") && <TableHead className="text-right">Units Sold</TableHead>}
              {show("purchased") && <TableHead className="text-right">Units Purchased</TableHead>}
              {show("adjusted") && <TableHead className="text-right">Adjust Qty</TableHead>}
              {show("loans") && <TableHead className="text-right">Lent / returned</TableHead>}
              {show("on_hand") && <TableHead className="text-right">Qty on Hand</TableHead>}
              {show("cos") && <TableHead className="text-right">Cost of sales</TableHead>}
              {show("pc") && <TableHead className="text-right">Purchase cost</TableHead>}
            </TableRow></TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.sku} className={onItem ? "cursor-pointer hover:bg-muted/50" : ""} onClick={() => onItem?.(r.sku)}>
                  <TableCell><div className="font-mono text-xs font-medium">{r.sku}</div><div className="text-xs text-muted-foreground">{r.name}</div></TableCell>
                  {show("beg") && <TableCell className="text-right tabular-nums">{q(r.beg_qty)}</TableCell>}
                  {show("sold") && <TableCell className="text-right tabular-nums">{q(r.sold)}</TableCell>}
                  {show("purchased") && <TableCell className="text-right tabular-nums">{q(r.purchased)}</TableCell>}
                  {show("adjusted") && <TableCell className="text-right tabular-nums">{Number(r.adjusted) ? q(r.adjusted) : ""}</TableCell>}
                  {show("loans") && <TableCell className="text-right tabular-nums">{Number(r.loans) ? q(r.loans) : ""}</TableCell>}
                  {show("on_hand") && <TableCell className="text-right font-medium tabular-nums">{q(r.on_hand)}</TableCell>}
                  {show("cos") && <TableCell className="text-right tabular-nums">{naira(r.cost_of_sales, { blankZero: true })}</TableCell>}
                  {show("pc") && <TableCell className="text-right tabular-nums">{naira(r.purchase_cost, { blankZero: true })}</TableCell>}
                </TableRow>
              ))}
              <TableRow className="border-t-2 font-semibold">
                <TableCell>{rows.length} items</TableCell>
                {show("beg") && <TableCell className="text-right">{q(t.beg_qty)}</TableCell>}
                {show("sold") && <TableCell className="text-right">{q(t.sold)}</TableCell>}
                {show("purchased") && <TableCell className="text-right">{q(t.purchased)}</TableCell>}
                {show("adjusted") && <TableCell className="text-right">{q(t.adjusted)}</TableCell>}
                {show("loans") && <TableCell className="text-right">{q(t.loans)}</TableCell>}
                {show("on_hand") && <TableCell className="text-right">{q(t.on_hand)}</TableCell>}
                {show("cos") && <TableCell className="text-right">{naira(t.cost_of_sales)}</TableCell>}
                {show("pc") && <TableCell className="text-right">{naira(t.purchase_cost)}</TableCell>}
              </TableRow>
            </TableBody>
          </Table>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Item Costing
// ---------------------------------------------------------------------------

function Doc({ d }: { d?: DrillTarget | null }) {
  if (!d) return null;
  return <DrillLink to={d}>{d.label || d.id}</DrillLink>;
}

export function ItemCostingReport({ period, setPeriod, filter, setFilter }: {
  period: Period; setPeriod: (p: Period) => void; filter: ItemFilter; setFilter: (f: ItemFilter) => void;
}) {
  const [page, setPage] = useState(0);
  const limit = 20;
  useEffect(() => setPage(0), [period.from, period.to, filter.search, filter.sku_from, filter.sku_to]);
  const ref = useRef<HTMLDivElement>(null);
  const { show, menu } = useColumns("ace.itemCosting.cols", [
    { key: "type", label: "Type", on: true }, { key: "received", label: "Qty Received", on: true }, { key: "cost", label: "Item Cost", on: true },
    { key: "adjusted", label: "Adjust Qty", on: true }, { key: "sold", label: "Quantity Sold", on: true }, { key: "cos", label: "Cost of Sales", on: false },
    { key: "remaining", label: "Remaining Qty", on: true }, { key: "value", label: "Remain Value", on: false },
    { key: "party", label: "Customer / supplier", on: true }, { key: "doc", label: "Invoice / document", on: true }, { key: "batch", label: "Batch (ACE)", on: false },
  ]);
  const { data, isLoading, error } = useBooks<Dict>(["inv-item-costing", period, filter, page], "/inventory/item-costing",
    { from: period.from, to: period.to, search: filter.search || undefined, sku_from: filter.sku_from || undefined, sku_to: filter.sku_to || undefined,
      offset: page * limit, limit });
  const items: Dict[] = data?.items ?? [];
  const total = Number(data?.items_total ?? 0);
  const flat = useMemo(() => items.flatMap((i) => i.rows.map((r: Dict) => ({
    item_id: i.sku, description: i.name, date: r.date, type: r.kind, qty_received: r.qty_received, item_cost: r.item_cost, adjust_qty: r.qty_adjusted,
    quantity_sold: r.qty_sold, cost_of_sales: r.cost_of_sales, remaining_qty: r.remaining_qty, remaining_value: r.remaining_value,
    customer_or_supplier: r.party, document: r.doc?.label ?? "", source: r.source }))), [items]);
  const pages = Math.max(1, Math.ceil(total / limit));
  const cells = (r: Dict) => (
    <>
      {show("type") && <TableCell className="whitespace-nowrap text-xs">{r.kind}{r.source === "SAGE" && <SageTag />}</TableCell>}
      {show("received") && <TableCell className="text-right tabular-nums">{q(r.qty_received)}</TableCell>}
      {show("cost") && <TableCell className="text-right tabular-nums">{r.item_cost != null ? naira(r.item_cost) : ""}</TableCell>}
      {show("adjusted") && <TableCell className="text-right tabular-nums">{q(r.qty_adjusted)}</TableCell>}
      {show("sold") && <TableCell className="text-right tabular-nums">{q(r.qty_sold)}</TableCell>}
      {show("cos") && <TableCell className="text-right tabular-nums">{r.cost_of_sales != null ? naira(r.cost_of_sales) : ""}</TableCell>}
      {show("remaining") && <TableCell className="text-right font-medium tabular-nums">{q(r.remaining_qty)}</TableCell>}
      {show("value") && <TableCell className="text-right tabular-nums">{naira(r.remaining_value)}</TableCell>}
      {show("party") && <TableCell className="text-xs">{r.customer_id && r.party
        ? <DrillLink to={{ type: "customer", id: String(r.customer_id), label: r.party }}>{r.party}</DrillLink>
        : r.supplier_id && r.party ? <DrillLink to={{ type: "supplier", id: String(r.supplier_id), label: r.party }}>{r.party}</DrillLink> : r.party}</TableCell>}
      {show("doc") && <TableCell className="text-xs">
        {r.doc ? <Doc d={r.doc} /> : r.possible?.length ? (
          <span className="text-muted-foreground">same day: {r.possible.slice(0, 4).map((p: Dict, k: number) => (
            <span key={k}>{k > 0 && ", "}<DrillLink to={p as DrillTarget}>{p.label}</DrillLink> {p.party}</span>))}</span>
        ) : r.kind === "Sold" || r.kind === "Customer return" ? <span className="text-muted-foreground">not in Sage's sales journal</span> : ""}
      </TableCell>}
      {show("batch") && <TableCell className="text-xs">{r.batch ? <DrillLink to={{ type: "batch", id: r.batch.id, label: r.batch.label }}>{r.batch.label}</DrillLink> : ""}</TableCell>}
    </>
  );
  const colCount = 2 + ["type", "received", "cost", "adjusted", "sold", "cos", "remaining", "value", "party", "doc", "batch"].filter(show).length;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-wrap items-end gap-3"><PeriodPicker value={period} onChange={setPeriod} /><ItemFilterBar value={filter} onChange={setFilter} /></div>
        <div className="flex items-center gap-2">
          {menu}
          <Button size="sm" variant="outline" onClick={() => printReport("Item Costing Report", periodText(period), ref.current)}><Printer className="mr-1 h-4 w-4" />Print</Button>
          <CsvButton filename={`item-costing-${period.from}-${period.to}.csv`} rows={flat}
                     columns={Object.keys(flat[0] ?? { item_id: 1 }).map((k) => ({ key: k, label: k.replace(/_/g, " ") }))} />
        </div>
      </div>
      <p className="text-xs text-muted-foreground">Each item's receipts, adjustments and sales in date order with the quantity remaining after each. Click an invoice to open it (what was on it, who bought it); click a customer to open their account.</p>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (items.length === 0 ? <Empty>No stock or movements for these items in this period.</Empty> : (
        <div ref={ref}>
          <Table>
            <TableHeader><TableRow>
              <TableHead>Item ID / description</TableHead><TableHead>Date</TableHead>
              {show("type") && <TableHead>Type</TableHead>}
              {show("received") && <TableHead className="text-right">Qty Received</TableHead>}
              {show("cost") && <TableHead className="text-right">Item Cost</TableHead>}
              {show("adjusted") && <TableHead className="text-right">Adjust Qty</TableHead>}
              {show("sold") && <TableHead className="text-right">Quantity Sold</TableHead>}
              {show("cos") && <TableHead className="text-right">Cost of Sales</TableHead>}
              {show("remaining") && <TableHead className="text-right">Remaining Qty</TableHead>}
              {show("value") && <TableHead className="text-right">Remain Value</TableHead>}
              {show("party") && <TableHead>Customer / supplier</TableHead>}
              {show("doc") && <TableHead>Invoice / document</TableHead>}
              {show("batch") && <TableHead>Batch</TableHead>}
            </TableRow></TableHeader>
            <TableBody>
              {items.map((i) => (
                <ItemBlock key={i.sku} i={i} colCount={colCount} cells={cells} show={show} />
              ))}
            </TableBody>
          </Table>
        </div>
      ))}
      {total > limit && (
        <div className="flex items-center justify-end gap-2 text-sm" data-noprint>
          <span className="text-muted-foreground">Items {page * limit + 1}–{Math.min(total, (page + 1) * limit)} of {total}</span>
          <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Previous</Button>
          <Button size="sm" variant="outline" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>Next</Button>
        </div>
      )}
    </div>
  );
}

function ItemBlock({ i, colCount, cells, show }: { i: Dict; colCount: number; cells: (r: Dict) => ReactNode; show: (k: string) => boolean }) {
  const [open, setOpen] = useState(true);
  return (
    <>
      <TableRow className="bg-muted/40 hover:bg-muted/60">
        <TableCell colSpan={colCount} className="py-2">
          <button className="flex w-full flex-wrap items-baseline justify-between gap-2 text-left" onClick={() => setOpen((o) => !o)}>
            <span><span className="font-mono text-sm font-semibold">{i.sku}</span> <span className="text-xs text-muted-foreground">{i.name}</span></span>
            <span className="text-xs">opening <strong>{q(i.opening_qty)}</strong> · received {q(i.totals.received)} · sold {q(i.totals.sold)}
              {Number(i.totals.adjusted) ? <> · adjusted {q(i.totals.adjusted)}</> : null} · closing <strong>{q(i.closing_qty)}</strong> {open ? "▾" : "▸"}</span>
          </button>
        </TableCell>
      </TableRow>
      {open && i.rows.map((r: Dict) => (
        <TableRow key={r.key}>
          <TableCell />
          <TableCell className="whitespace-nowrap text-xs">{fmtDate(r.date)}</TableCell>
          {cells(r)}
        </TableRow>
      ))}
      {open && i.rows.length === 0 && (
        <TableRow><TableCell /><TableCell colSpan={colCount - 1} className="text-xs text-muted-foreground">No movements in the period{show("remaining") ? ` - ${q(i.opening_qty)} on hand throughout` : ""}.</TableCell></TableRow>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Both, with a shared period and item filter (clicking an item in Unit activity opens its costing)
// ---------------------------------------------------------------------------

export function StockReports({ defaultTab = "unit" }: { defaultTab?: "unit" | "costing" }) {
  const [tab, setTab] = useState<string>(defaultTab);
  const [period, setPeriod] = useState<Period>({ from: yearStartStr(), to: today() });
  const [filter, setFilter] = useState<ItemFilter>({ search: "", sku_from: "", sku_to: "" });
  return (
    <Tabs value={tab} onValueChange={setTab}>
      <TabsList>
        <TabsTrigger value="unit">Inventory unit activity</TabsTrigger>
        <TabsTrigger value="costing">Item costing</TabsTrigger>
      </TabsList>
      <TabsContent value="unit" className="pt-3">
        <UnitActivityReport period={period} setPeriod={setPeriod} filter={filter} setFilter={setFilter}
                            onItem={(sku) => { setFilter({ search: "", sku_from: sku, sku_to: sku }); setTab("costing"); }} />
      </TabsContent>
      <TabsContent value="costing" className="pt-3">
        <ItemCostingReport period={period} setPeriod={setPeriod} filter={filter} setFilter={setFilter} />
      </TabsContent>
    </Tabs>
  );
}
