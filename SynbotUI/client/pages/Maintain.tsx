/**
 * Maintain - the records behind the books, as Sage's Maintain menu (Frontdesk design meeting, 26 Oct 2026):
 *  - Inventory Items (Sage's "Maintain Inventory Items"): description, class, prices, GL accounts, costing,
 *    stock on hand / held for invoices / available, reorder level and quantity, preferred vendor, UPC,
 *    part number, location, weight - its batches (number on the pack, manufacture and expiry dates) and
 *    every lot of the product in delivery order (A ... Z, Z i, Z ii ...), with the next lot one click away.
 *  - Batch numbers & dates for every batch at once.
 *  - Vendors (Sage's "Maintain Vendors"): Vendor ID, name, contact, account number, address, phones, e-mail ...
 *  - Shipping methods offered as "Ship via" on invoices.
 *  - Customers, Chart of Accounts, Company information and Users open their own pages.
 * An item, lot, batch or vendor made by mistake can be deleted while nothing has been recorded against it
 * (components/books/delete-record.tsx); one with history is made inactive instead.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Plus, Save, Wrench } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/workspace/PageHeader";
import { act, Empty, ErrorNote, Loading, Section, SupplierPick, useBooks } from "@/components/books/kit";
import { DrillProvider } from "@/components/books/lineage";
import { BatchDetails } from "@/pages/books/BooksStock";
import { NewItemSheet } from "@/components/books/new-item";
import { GlSelect } from "@/components/books/gl-select";
import { DeleteRecord } from "@/components/books/delete-record";
import { books, Dict, fmtDate, naira, num, today } from "@/lib/books-api";
import { askText } from "@/lib/ask";
import { useAuth } from "@/components/AuthProvider";

const F = ({ label, children, className = "" }: { label: string; children: React.ReactNode; className?: string }) => (
  <div className={`space-y-1 ${className}`}><Label className="text-xs">{label}</Label>{children}</div>
);
const RO = ({ value }: { value: React.ReactNode }) => <div className="flex h-10 items-center rounded-md border bg-muted px-3 text-sm">{value ?? "—"}</div>;

export default function Maintain() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "items";
  const { roles } = useAuth();
  const admin = roles.includes("admin");
  return (
    <DrillProvider>
      <div className="flex flex-col gap-5">
        <PageHeader icon={Wrench} title="Maintain" subtitle="The records behind the books - items, batches, vendors and lists - as Sage's Maintain menu" />
        <Tabs value={tab} onValueChange={(t) => { const p = new URLSearchParams(params); p.set("tab", t); setParams(p, { replace: true }); }}>
          <TabsList className="flex-wrap">
            <TabsTrigger value="items">Inventory Items</TabsTrigger>
            <TabsTrigger value="batches">Batch numbers & dates</TabsTrigger>
            <TabsTrigger value="vendors">Vendors</TabsTrigger>
            <TabsTrigger value="ship">Shipping methods</TabsTrigger>
            <TabsTrigger value="more">Customers, accounts & more</TabsTrigger>
          </TabsList>
          <TabsContent value="items"><ItemsMaintain initial={params.get("sku")} /></TabsContent>
          <TabsContent value="batches"><BatchDetails /></TabsContent>
          <TabsContent value="vendors"><VendorsMaintain /></TabsContent>
          <TabsContent value="ship"><ShipMethodsMaintain /></TabsContent>
          <TabsContent value="more">
            <Section title="Other records">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {[["Customers / Prospects", "/crm/customers", "Add or edit a customer: contact, terms, credit limit"],
                  ["Chart of Accounts", "/finance/books/setup?tab=accounts", "Add an account, rename it, make it inactive"],
                  ["Budgets", "/finance/books/setup?tab=budgets", "Budgets by account and month"],
                  ["Company information & invoice layout", "/finance/books/setup?tab=settings", "Name, address, phones, bank details on invoices"],
                  ["Fixed Assets", "/finance/books/assets", "The asset register and depreciation"],
                  ...(admin ? [["Users", "/admin/users", "Logins and access"]] : [])].map(([t, href, d]) => (
                  <Link key={t} to={href} className="rounded-lg border p-3 hover:bg-muted/50"><div className="font-medium">{t}</div><div className="text-xs text-muted-foreground">{d}</div></Link>
                ))}
              </div>
            </Section>
          </TabsContent>
        </Tabs>
      </div>
    </DrillProvider>
  );
}

// ---------------------------------------------------------------------------
// Maintain Inventory Items
// ---------------------------------------------------------------------------

type ItemForm = Record<string, string>;
const toForm = (p: Dict): ItemForm => ({
  name: p.name ?? "", sales_description: p.sales_description ?? "", legacy_class: p.legacy_class ?? "Stock item",
  standard_price: p.standard_price != null ? String(Number(p.standard_price)) : "",
  price_2: p.price_levels?.["2"] != null ? String(p.price_levels["2"]) : "", price_3: p.price_levels?.["3"] != null ? String(p.price_levels["3"]) : "",
  reorder_level: p.reorder_level != null ? String(Number(p.reorder_level)) : "", reorder_qty: p.reorder_qty != null ? String(Number(p.reorder_qty)) : "",
  uom: p.uom ?? "Each", upc: p.upc ?? "", part_number: p.part_number ?? "", location: p.location ?? "",
  weight: p.weight != null ? String(Number(p.weight)) : "", sales_gl: p.sales_gl ?? "", inventory_gl: p.inventory_gl ?? "", cogs_gl: p.cogs_gl ?? "",
  status: p.status ?? "ACTIVE",
});
const CLASSES = ["Stock item", "Non-stock item", "Service", "Description only"];

function ItemsMaintain({ initial }: { initial: string | null }) {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const { data: list, isLoading: listLoading } = useBooks<Dict[]>(["maintain-items", search, showInactive], "/maintain/items",
    { search: search || undefined, include_inactive: showInactive || undefined });
  const [sku, setSku] = useState<string | null>(initial);
  // a link to another item (…/maintain?sku=X) while Maintain is already open
  useEffect(() => { if (initial) setSku(initial); }, [initial]);
  useEffect(() => { if (!sku && list?.length) setSku(list[0].sku); }, [list]); // eslint-disable-line react-hooks/exhaustive-deps
  const { data: item, isLoading, error, refetch } = useBooks<Dict>(["maintain-item", sku], `/maintain/items/${encodeURIComponent(sku ?? "")}`, {}, !!sku);
  const [f, setF] = useState<ItemForm | null>(null);
  const [vendor, setVendor] = useState<Dict | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (item) { setF(toForm(item)); setVendor(item.preferred_supplier_id ? { id: item.preferred_supplier_id, name: item.preferred_vendor, supplier_code: item.preferred_vendor_id } : null); }
  }, [item]);
  const idx = (list ?? []).findIndex((r) => r.sku === sku);
  const go = (d: number) => { const r = (list ?? [])[idx + d]; if (r) setSku(r.sku); };
  const set = (k: string, v: string) => setF((x) => (x ? { ...x, [k]: v } : x));
  const payload = () => f && ({
    name: f.name, sales_description: f.sales_description, legacy_class: f.legacy_class, uom: f.uom, upc: f.upc, part_number: f.part_number,
    location: f.location, status: f.status, standard_price: f.standard_price === "" ? null : Number(f.standard_price),
    reorder_level: f.reorder_level === "" ? null : Number(f.reorder_level), reorder_qty: f.reorder_qty === "" ? null : Number(f.reorder_qty),
    weight: f.weight === "" ? null : Number(f.weight), sales_gl: f.sales_gl, inventory_gl: f.inventory_gl, cogs_gl: f.cogs_gl,
    preferred_supplier_id: vendor?.id ?? null,
    price_levels: { ...(f.price_2 !== "" ? { "2": Number(f.price_2) } : {}), ...(f.price_3 !== "" ? { "3": Number(f.price_3) } : {}) },
  });
  const save = async () => {
    if (!sku || !f) return;
    setBusy(true);
    const r = await act(() => books.put(`/maintain/items/${encodeURIComponent(sku)}`, payload()), `${sku} saved`);
    setBusy(false);
    if (r) { qc.invalidateQueries({ queryKey: ["books"] }); refetch(); }
  };
  const newLot = async () => {
    if (!item) return;
    const id = await askText(`Item ID for the next lot of ${item.name} (copies its description, class, prices and accounts):`, item.next_lot);
    if (!id) return;
    const r = await act(() => books.post<Dict>("/maintain/items", { copy_from: item.sku, sku: id.trim() }), `${id.trim()} created - receive its stock on the supplier's bill`);
    if (r) { qc.invalidateQueries({ queryKey: ["books"] }); setSku(r.sku); }
  };
  const [adding, setAdding] = useState(false);
  const newItem = () => setAdding(true);
  const afterDelete = (gone: string) => {
    const lot = (item?.family ?? []).find((l: Dict) => l.sku !== gone);
    const near = (list ?? [])[idx + 1] ?? (list ?? [])[idx - 1];
    qc.invalidateQueries({ queryKey: ["books"] });
    setSku(gone !== sku ? sku : lot?.sku ?? (near && near.sku !== gone ? near.sku : null));
  };
  const makeInactive = async () => {
    if (!sku) return;
    const r = await act(() => books.put(`/maintain/items/${encodeURIComponent(sku)}`, { status: "INACTIVE" }), `${sku} is now inactive`);
    if (r) { qc.invalidateQueries({ queryKey: ["books"] }); refetch(); }
  };
  return (
    <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
      <NewItemSheet open={adding} defaultFrom={item ? { sku: item.sku, name: item.name } : null}
                    onClose={(r) => { setAdding(false); if (r) { qc.invalidateQueries({ queryKey: ["books"] }); setSku(r.sku); } }} />
      <Section title="Item ID" actions={<Button size="sm" onClick={newItem}><Plus className="mr-1 h-4 w-4" />New item</Button>}>
        <Input placeholder="Search item ID or description" value={search} onChange={(e) => setSearch(e.target.value)} />
        <label className="mt-2 flex items-center gap-2 text-xs"><input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />Show inactive items</label>
        <div className="mt-2 max-h-[560px] overflow-y-auto rounded border">
          {listLoading && <Loading />}
          {(list ?? []).map((r) => (
            <button key={r.sku} type="button" onClick={() => setSku(r.sku)}
                    className={`flex w-full items-center justify-between gap-2 border-b px-2 py-1.5 text-left text-xs hover:bg-muted/50 ${r.sku === sku ? "bg-primary/10 font-semibold" : ""}`}>
              <span className="truncate font-mono">{r.sku}</span>
              <span className={`shrink-0 tabular-nums ${Number(r.on_hand) > 0 ? "" : "text-muted-foreground"}`}>{num(r.on_hand)}{r.status === "INACTIVE" ? " · inactive" : ""}</span>
            </button>
          ))}
        </div>
        <Button size="sm" variant="outline" className="mt-2 w-full" onClick={newItem}><Plus className="mr-1 h-4 w-4" />New item</Button>
      </Section>
      <div className="space-y-4">
        {isLoading && <Loading />}<ErrorNote error={error} />
        {item && f && (
          <>
            <Section title={<span className="flex items-center gap-2">Maintain Inventory Items · <span className="font-mono">{item.sku}</span></span>}
                     actions={<div className="flex items-center gap-2">
                       <Button size="icon" variant="outline" disabled={idx <= 0} onClick={() => go(-1)} aria-label="Previous item"><ChevronLeft className="h-4 w-4" /></Button>
                       <Button size="icon" variant="outline" disabled={idx < 0 || idx >= (list ?? []).length - 1} onClick={() => go(1)} aria-label="Next item"><ChevronRight className="h-4 w-4" /></Button>
                       <Button size="sm" variant="outline" onClick={newLot}><Plus className="mr-1 h-4 w-4" />New lot ({item.next_lot})</Button>
                       <Button size="sm" disabled={busy} onClick={save}><Save className="mr-1 h-4 w-4" />{busy ? "Saving…" : "Save"}</Button>
                       <DeleteRecord kind="item" recordKey={item.sku} name={item.sku} onDeleted={() => afterDelete(item.sku)}
                                     onMakeInactive={item.status === "INACTIVE" ? undefined : makeInactive} />
                     </div>}>
              <div className="grid gap-3 md:grid-cols-3">
                <F label="Item ID"><RO value={<span className="font-mono">{item.sku}</span>} /></F>
                <F label="Description"><Input value={f.name} onChange={(e) => set("name", e.target.value)} /></F>
                <F label="Item class"><select className="h-10 w-full rounded-md px-3 text-sm" value={f.legacy_class} onChange={(e) => set("legacy_class", e.target.value)}>
                  {(CLASSES.includes(f.legacy_class) ? CLASSES : [f.legacy_class, ...CLASSES]).map((c) => <option key={c}>{c}</option>)}</select></F>
                <F label="Description for sales (on invoices)" className="md:col-span-2"><Textarea rows={2} value={f.sales_description} onChange={(e) => set("sales_description", e.target.value)} /></F>
                <F label="Status"><label className="flex h-10 items-center gap-2 text-sm"><input type="checkbox" checked={f.status === "INACTIVE"}
                  onChange={(e) => set("status", e.target.checked ? "INACTIVE" : "ACTIVE")} />Inactive (not offered on invoices)</label></F>
              </div>
            </Section>
            <Tabs defaultValue="general">
              <TabsList><TabsTrigger value="general">General</TabsTrigger><TabsTrigger value="batches">Batches ({item.batches?.length ?? 0})</TabsTrigger>
                <TabsTrigger value="lots">Lots of this product ({item.family?.length ?? 0})</TabsTrigger></TabsList>
              <TabsContent value="general">
                <Section>
                  <div className="grid gap-3 md:grid-cols-4">
                    <F label="Price level 1 (₦)"><Input type="number" value={f.standard_price} onChange={(e) => set("standard_price", e.target.value)} /></F>
                    <F label="Price level 2 (₦)"><Input type="number" value={f.price_2} onChange={(e) => set("price_2", e.target.value)} /></F>
                    <F label="Price level 3 (₦)"><Input type="number" value={f.price_3} onChange={(e) => set("price_3", e.target.value)} /></F>
                    <F label="Last unit cost"><RO value={item.last_unit_cost != null ? `${naira(item.last_unit_cost)}${item.last_received ? ` · ${fmtDate(item.last_received)}` : ""}` : "—"} /></F>
                    <F label="Cost method"><RO value={item.cost_method} /></F>
                    <F label="GL sales account"><GlSelect kind="sales" label="GL sales account" value={f.sales_gl} onChange={(v) => set("sales_gl", v)} /></F>
                    <F label="GL inventory account"><GlSelect kind="inventory" label="GL inventory account" value={f.inventory_gl} onChange={(v) => set("inventory_gl", v)} /></F>
                    <F label="GL cost of sales account"><GlSelect kind="cogs" label="GL cost of sales account" value={f.cogs_gl} onChange={(v) => set("cogs_gl", v)} /></F>
                    <F label="Qty on hand"><RO value={num(item.on_hand)} /></F>
                    <F label="Held for invoices awaiting QC / Finance"><RO value={num(item.held_for_invoices)} /></F>
                    <F label="Qty available"><RO value={<strong>{num(item.available)}</strong>} /></F>
                    <F label="On loan to customers"><RO value={num(item.on_loan)} /></F>
                    <F label="Minimum stock (reorder level)"><Input type="number" value={f.reorder_level} onChange={(e) => set("reorder_level", e.target.value)} /></F>
                    <F label="Reorder quantity"><Input type="number" value={f.reorder_qty} onChange={(e) => set("reorder_qty", e.target.value)} /></F>
                    <F label="Stock value"><RO value={naira(item.value)} /></F>
                    <F label="Stocking U/M"><Input value={f.uom} onChange={(e) => set("uom", e.target.value)} /></F>
                    <F label="UPC / SKU"><Input value={f.upc} onChange={(e) => set("upc", e.target.value)} /></F>
                    <F label="Part number"><Input value={f.part_number} onChange={(e) => set("part_number", e.target.value)} /></F>
                    <F label="Location"><Input placeholder="e.g. Cold room 2" value={f.location} onChange={(e) => set("location", e.target.value)} /></F>
                    <F label="Weight"><Input type="number" value={f.weight} onChange={(e) => set("weight", e.target.value)} /></F>
                    <div className="md:col-span-2"><SupplierPick label="Preferred vendor" value={vendor} onChange={setVendor} /></div>
                  </div>
                </Section>
              </TabsContent>
              <TabsContent value="batches"><ItemBatches item={item} onSaved={refetch} /></TabsContent>
              <TabsContent value="lots">
                <Section title={`Lots of ${item.name}, in delivery order`} actions={<Button size="sm" onClick={newLot}><Plus className="mr-1 h-4 w-4" />Create the next lot · {item.next_lot}</Button>}>
                  <p className="mb-2 text-xs text-muted-foreground">Each delivery that comes at a new price gets the next letter (A to Z, then Z i, Z ii ...). The list shows which lot came before which, its price and what is left. A lot created by mistake can be deleted (the bin) while nothing has been received or sold on it.</p>
                  <Table>
                    <TableHeader><TableRow><TableHead>#</TableHead><TableHead>Item ID</TableHead><TableHead className="text-right">Price</TableHead><TableHead>First received</TableHead><TableHead>Expiry</TableHead><TableHead className="text-right">On hand</TableHead><TableHead className="w-10" /></TableRow></TableHeader>
                    <TableBody>{(item.family ?? []).map((l: Dict) => (
                      <TableRow key={l.sku} className={`cursor-pointer ${l.current ? "bg-primary/10 font-semibold" : "hover:bg-muted/50"}`} onClick={() => setSku(l.sku)}>
                        <TableCell>{l.order}</TableCell><TableCell className="font-mono text-xs">{l.sku}{l.status === "INACTIVE" ? " · inactive" : ""}</TableCell>
                        <TableCell className="text-right">{l.standard_price != null ? naira(l.standard_price) : ""}</TableCell>
                        <TableCell>{fmtDate(l.first_received)}</TableCell><TableCell>{fmtDate(l.expiry)}</TableCell><TableCell className="text-right">{num(l.on_hand)}</TableCell>
                        <TableCell onClick={(e) => e.stopPropagation()}>
                          <DeleteRecord kind="item" recordKey={l.sku} name={l.sku} label="Delete lot" iconOnly onDeleted={() => afterDelete(l.sku)} />
                        </TableCell>
                      </TableRow>))}</TableBody>
                  </Table>
                </Section>
              </TabsContent>
            </Tabs>
          </>
        )}
      </div>
    </div>
  );
}

function ItemBatches({ item, onSaved }: { item: Dict; onSaved: () => void }) {
  const qc = useQueryClient();
  const [edits, setEdits] = useState<Record<string, Dict>>({});
  const rows: Dict[] = item.batches ?? [];
  const val = (b: Dict, k: string) => edits[b.id]?.[k] ?? b[k] ?? "";
  const set = (b: Dict, k: string, v: string) => setEdits((e) => ({ ...e, [b.id]: { ...e[b.id], [k]: v } }));
  const save = async () => {
    for (const [id, e] of Object.entries(edits)) {
      const ok = await act(() => books.put(`/inventory/batches/${id}`, e), "");
      if (!ok) return;
    }
    setEdits({}); qc.invalidateQueries({ queryKey: ["books"] }); onSaved();
  };
  return (
    <Section title={`Batches of ${item.sku}`} actions={<Button size="sm" disabled={!Object.keys(edits).length} onClick={save}><Save className="mr-1 h-4 w-4" />Save batches</Button>}>
      {rows.length === 0 ? <Empty>No batch received for this item yet - it is created when the supplier's bill (or QC's incoming batch) is recorded.</Empty> : (
        <Table>
          <TableHeader><TableRow><TableHead>Sage lot</TableHead><TableHead>Batch number on the pack</TableHead><TableHead>Manufacture date</TableHead><TableHead>Expiry date</TableHead>
            <TableHead>Supplier</TableHead><TableHead className="text-right">Unit cost</TableHead><TableHead className="text-right">On hand</TableHead><TableHead>Status</TableHead><TableHead className="w-10" /></TableRow></TableHeader>
          <TableBody>{rows.map((b) => (
            <TableRow key={b.id} className={edits[b.id] ? "bg-amber-50 dark:bg-amber-500/10" : ""}>
              <TableCell className="font-mono text-xs">{b.lot_code ?? b.batch_number}</TableCell>
              <TableCell><Input className="h-8 w-40" aria-label={`Batch number on the pack, ${b.batch_number}`} value={val(b, "pack_batch_number")} onChange={(e) => set(b, "pack_batch_number", e.target.value)} /></TableCell>
              <TableCell><Input className="h-8 w-40" type="date" max={today()} aria-label="Manufacture date" value={val(b, "manufacture_date")} onChange={(e) => set(b, "manufacture_date", e.target.value)} /></TableCell>
              <TableCell><Input className="h-8 w-40" type="date" aria-label="Expiry date" value={val(b, "expiry_date")} onChange={(e) => set(b, "expiry_date", e.target.value)} /></TableCell>
              <TableCell className="text-xs">{b.supplier ?? ""}</TableCell><TableCell className="text-right">{b.unit_cost != null ? naira(b.unit_cost) : ""}</TableCell>
              <TableCell className="text-right">{num(b.on_hand)}</TableCell><TableCell className="text-xs">{String(b.status).toLowerCase()}</TableCell>
              <TableCell><DeleteRecord kind="batch" recordKey={b.id} name={`Batch ${b.pack_batch_number || b.lot_code || b.batch_number}`} iconOnly
                                       label="Delete batch" onDeleted={() => { setEdits(({ [b.id]: _, ...rest }) => rest); onSaved(); }} /></TableCell>
            </TableRow>))}</TableBody>
        </Table>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Maintain Vendors
// ---------------------------------------------------------------------------

const VENDOR_BLANK: Dict = { vendor_id: "", name: "", contact_name: "", account_number: "", address: "", phone: "", telephone_2: "", fax: "",
  contact_email: "", website: "", category: "", payment_terms: "", tax_id: "", bank_details: "", expense_account_code: "", status: "active" };

function VendorsMaintain() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const { data: list, isLoading } = useBooks<Dict[]>(["maintain-vendors", search], "/maintain/vendors", { search: search || undefined, include_inactive: true });
  const [id, setId] = useState<string | null>(null);
  const { data: v } = useBooks<Dict>(["maintain-vendor", id], `/maintain/vendors/${id}`, {}, !!id && id !== "new");
  const [f, setF] = useState<Dict>(VENDOR_BLANK);
  useEffect(() => { if (id === "new") setF(VENDOR_BLANK); else if (v) setF(Object.fromEntries(Object.keys(VENDOR_BLANK).map((k) => [k, v[k] ?? VENDOR_BLANK[k]]))); }, [v, id]);
  const set = (k: string, x: string) => setF((o) => ({ ...o, [k]: x }));
  const save = async () => {
    const r = id === "new" ? await act(() => books.post<Dict>("/maintain/vendors", f), `Vendor ${f.name} created`)
                           : await act(() => books.put<Dict>(`/maintain/vendors/${id}`, f), `${f.name} saved`);
    if (r) { qc.invalidateQueries({ queryKey: ["books"] }); setId(r.id); }
  };
  const makeInactive = async () => {
    const r = await act(() => books.put<Dict>(`/maintain/vendors/${id}`, { status: "inactive" }), `${f.name} is now inactive`);
    if (r) { qc.invalidateQueries({ queryKey: ["books"] }); setF((o) => ({ ...o, status: "inactive" })); }
  };
  const fields: [string, string, string?][] = [["contact_name", "Contact"], ["account_number", "Account number (ours with them)"], ["address", "Mailing address"],
    ["category", "Vendor type"], ["expense_account_code", "Expense account (GL code)", "e.g. 50000"], ["payment_terms", "Terms", "e.g. Net 30 Days"],
    ["phone", "Telephone 1"], ["telephone_2", "Telephone 2"], ["fax", "Fax"], ["contact_email", "E-mail"], ["website", "Web site"], ["tax_id", "TIN"], ["bank_details", "Bank details"]];
  return (
    <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
      <Section title="Vendors">
        <Input placeholder="Search Vendor ID or name" value={search} onChange={(e) => setSearch(e.target.value)} />
        <div className="mt-2 max-h-[560px] overflow-y-auto rounded border">
          {isLoading && <Loading />}
          {(list ?? []).map((r) => (
            <button key={r.id} type="button" onClick={() => setId(r.id)}
                    className={`block w-full border-b px-2 py-1.5 text-left text-xs hover:bg-muted/50 ${r.id === id ? "bg-primary/10 font-semibold" : ""}`}>
              <div className="truncate">{r.name}{r.status === "inactive" ? " · inactive" : ""}</div><div className="font-mono text-[11px] text-muted-foreground">{r.vendor_id ?? "no Vendor ID"}</div>
            </button>
          ))}
        </div>
        <Button size="sm" variant="outline" className="mt-2 w-full" onClick={() => setId("new")}><Plus className="mr-1 h-4 w-4" />New vendor</Button>
      </Section>
      {!id ? <Empty>Choose a vendor, or New vendor.</Empty> : (
        <Section title={id === "new" ? "New vendor" : `Maintain Vendors · ${f.name}`} actions={<div className="flex items-center gap-2">
                   <Button size="sm" onClick={save} disabled={!String(f.name).trim()}><Save className="mr-1 h-4 w-4" />Save</Button>
                   {id !== "new" && <DeleteRecord kind="vendor" recordKey={id} name={f.name || "this vendor"}
                                                  onDeleted={() => setId(null)} onMakeInactive={f.status === "inactive" ? undefined : makeInactive} />}
                 </div>}>
          <div className="grid gap-3 md:grid-cols-3">
            <F label="Vendor ID (up to 20 characters)"><Input value={f.vendor_id ?? ""} onChange={(e) => set("vendor_id", e.target.value)} placeholder="made from the name if blank" /></F>
            <F label="Name"><Input value={f.name} onChange={(e) => set("name", e.target.value)} /></F>
            <F label="Status"><label className="flex h-10 items-center gap-2 text-sm"><input type="checkbox" checked={f.status === "inactive"} onChange={(e) => set("status", e.target.checked ? "inactive" : "active")} />Inactive</label></F>
            {fields.map(([k, label, ph]) => (
              <F key={k} label={label} className={k === "address" || k === "bank_details" ? "md:col-span-2" : ""}>
                {k === "address" || k === "bank_details" ? <Textarea rows={2} value={f[k] ?? ""} onChange={(e) => set(k, e.target.value)} />
                  : k === "expense_account_code" ? <GlSelect kind="any" label={label} value={f[k] ?? ""} onChange={(v) => set(k, v)} />
                  : <Input placeholder={ph} value={f[k] ?? ""} onChange={(e) => set(k, e.target.value)} />}
              </F>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shipping methods ("Ship via")
// ---------------------------------------------------------------------------

function ShipMethodsMaintain() {
  const qc = useQueryClient();
  const [methods, setMethods] = useState<string[] | null>(null);
  const [adding, setAdding] = useState("");
  useEffect(() => { import("@/lib/api-client").then(({ api }) => api.frontdesk.shipMethods().then((r) => setMethods(r.methods))); }, []);
  const save = async (next: string[]) => {
    const r = await act(() => books.put<Dict>("/maintain/ship-methods", { methods: next }), "Shipping methods saved");
    if (r) { setMethods(r.methods); qc.invalidateQueries({ queryKey: ["ship-methods"] }); }
  };
  const move = (i: number, d: number) => { if (!methods) return; const n = [...methods]; const [x] = n.splice(i, 1); n.splice(i + d, 0, x); save(n); };
  return (
    <Section title="Shipping methods (Ship via on invoices)">
      {!methods ? <Loading /> : (
        <div className="max-w-md space-y-2">
          {methods.map((m, i) => (
            <div key={m} className="flex items-center justify-between rounded border px-3 py-1.5 text-sm">
              <span>{m}</span>
              <span className="flex gap-1">
                <Button size="sm" variant="ghost" disabled={i === 0} onClick={() => move(i, -1)}>↑</Button>
                <Button size="sm" variant="ghost" disabled={i === methods.length - 1} onClick={() => move(i, 1)}>↓</Button>
                <Button size="sm" variant="ghost" className="text-red-600" disabled={methods.length === 1} onClick={() => save(methods.filter((x) => x !== m))}>Remove</Button>
              </span>
            </div>
          ))}
          <div className="flex gap-2"><Input placeholder="e.g. DHL" value={adding} onChange={(e) => setAdding(e.target.value)} />
            <Button disabled={!adding.trim()} onClick={() => { save([...methods, adding.trim()]); setAdding(""); }}><Plus className="mr-1 h-4 w-4" />Add</Button></div>
        </div>
      )}
    </Section>
  );
}
