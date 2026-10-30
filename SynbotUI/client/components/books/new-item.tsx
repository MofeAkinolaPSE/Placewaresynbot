/**
 * Add an inventory item (Maintain -> Inventory Items -> New item, and from "Register incoming batch" when a
 * delivery is for something not in the list yet). Either a brand-new product, or the next lot of an existing
 * one: pick the item it follows and the next lot code (A ... Z, Z i ...) is filled in, with its description,
 * class, prices and GL accounts copied.
 */
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { books, Dict } from "@/lib/books-api";
import { act, ProductPick, SupplierPick } from "./kit";
import { GlSelect } from "./gl-select";

const CLASSES = ["Stock item", "Non-stock item", "Service", "Description only"];

const EMPTY: Dict = { sku: "", name: "", legacy_class: "Stock item", standard_price: "", reorder_level: "", sales_gl: "", inventory_gl: "", cogs_gl: "" };

export function NewItemSheet({ open, onClose, defaultFrom }: { open: boolean; onClose: (created?: Dict) => void; defaultFrom?: Dict | null }) {
  // every New item starts as a clean slate (client, 28 Oct): nothing carried over from the item last looked at
  const [mode, setMode] = useState<"lot" | "new">("new");
  const [from, setFrom] = useState<Dict | null>(null);
  const [vendor, setVendor] = useState<Dict | null>(null);
  const [f, setF] = useState<Dict>(EMPTY);
  const clear = () => { setFrom(null); setVendor(null); setF(EMPTY); };
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: string) => setF((x) => ({ ...x, [k]: v }));
  useEffect(() => {
    clear(); setMode("new");
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (mode !== "lot" || !from?.sku) { if (mode === "lot") setF(EMPTY); return; }
    books.get<Dict>(`/maintain/items/${encodeURIComponent(from.sku)}`).then((it) => setF({
      sku: it.next_lot, name: it.name, legacy_class: it.legacy_class ?? "Stock item", standard_price: it.standard_price ?? "",
      reorder_level: it.reorder_level ?? "", sales_gl: it.sales_gl ?? "", inventory_gl: it.inventory_gl ?? "", cogs_gl: it.cogs_gl ?? "" })).catch(() => {});
  }, [from?.sku, mode]);
  const submit = async () => {
    setBusy(true);
    const r = await act(() => books.post<Dict>("/maintain/items", {
      ...(mode === "lot" && from ? { copy_from: from.sku } : {}), sku: String(f.sku).trim(), name: String(f.name).trim(), legacy_class: f.legacy_class,
      standard_price: f.standard_price === "" ? undefined : Number(f.standard_price), reorder_level: f.reorder_level === "" ? undefined : Number(f.reorder_level),
      sales_gl: f.sales_gl || undefined, inventory_gl: f.inventory_gl || undefined, cogs_gl: f.cogs_gl || undefined,
      preferred_supplier_id: vendor?.id ?? undefined }), `${String(f.sku).trim()} added`);
    setBusy(false);
    if (r) onClose(r);
  };
  return (
    <DetailSheet open={open} onOpenChange={(o) => !o && onClose()} title="New inventory item"
                 description="A new lot of a product you already stock (new delivery at a new price), or a product you have never stocked."
                 footer={<Button className="w-full" disabled={busy || !String(f.sku).trim() || !String(f.name).trim() || (mode === "lot" && !from)} onClick={submit}>{busy ? "Adding…" : "Add item"}</Button>}>
      <div className="space-y-3">
        <div className="flex gap-4 text-sm">
          <label className="flex items-center gap-2"><input type="radio" checked={mode === "lot"} onChange={() => { clear(); setMode("lot"); if (defaultFrom) setFrom(defaultFrom); }} />Next lot of an existing product</label>
          <label className="flex items-center gap-2"><input type="radio" checked={mode === "new"} onChange={() => { clear(); setMode("new"); }} />A new product</label>
        </div>
        {mode === "lot" && <ProductPick label="Follows this item (its latest lot)" value={from} onChange={setFrom} />}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1"><Label className="text-xs">Item ID{mode === "lot" ? " (next lot code)" : ""}</Label>
            <Input placeholder="e.g. TYPHIM (A)" value={f.sku} onChange={(e) => set("sku", e.target.value)} /></div>
          <div className="space-y-1"><Label className="text-xs">Description (product name)</Label><Input value={f.name} onChange={(e) => set("name", e.target.value)} /></div>
          <div className="space-y-1"><Label className="text-xs">Item class</Label>
            <select className="h-10 w-full rounded-md px-3 text-sm" value={f.legacy_class} onChange={(e) => set("legacy_class", e.target.value)}>{CLASSES.map((c) => <option key={c}>{c}</option>)}</select></div>
          <div className="space-y-1"><Label className="text-xs">Price level 1 (₦)</Label><Input type="number" value={f.standard_price} onChange={(e) => set("standard_price", e.target.value)} /></div>
          <div className="space-y-1"><Label className="text-xs">Minimum stock (reorder level)</Label><Input type="number" value={f.reorder_level} onChange={(e) => set("reorder_level", e.target.value)} /></div>
          <div className="space-y-1"><Label className="text-xs">GL sales account</Label><GlSelect kind="sales" allowDefault label="GL sales account" value={f.sales_gl} onChange={(v) => set("sales_gl", v)} /></div>
          <div className="space-y-1"><Label className="text-xs">GL inventory account</Label><GlSelect kind="inventory" allowDefault label="GL inventory account" value={f.inventory_gl} onChange={(v) => set("inventory_gl", v)} /></div>
          <div className="space-y-1"><Label className="text-xs">GL cost of sales account</Label><GlSelect kind="cogs" allowDefault label="GL cost of sales account" value={f.cogs_gl} onChange={(v) => set("cogs_gl", v)} /></div>
        </div>
        <SupplierPick label="Preferred vendor (optional)" value={vendor} onChange={setVendor} />
        <p className="text-xs text-muted-foreground">Its stock arrives with the delivery (Confirm arrived) or the supplier's bill; batch number and dates are entered there or in Maintain.</p>
      </div>
    </DetailSheet>
  );
}
