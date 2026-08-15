import React, { useState } from "react";
import { EntityAutocomplete } from "@/components/workspace/EntityAutocomplete";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api-client";
import { toast } from "sonner";

type Item = { sku?: string; name: string; qty: number };
type Product = { id?: number; sku?: string; name: string };

export default function WalkInForm({ onSuccess }: { onSuccess?: () => void }) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [agent, setAgent] = useState("");
  const [location, setLocation] = useState("");
  const [notes, setNotes] = useState("");
  const [items, setItems] = useState<Item[]>([]);
  const [submitting, setSubmitting] = useState(false);

  function addProduct(p: Product) {
    setItems((s) => [...s, { sku: p.sku, name: p.name, qty: 1 }]);
  }

  function updateQty(idx: number, q: number) {
    setItems((s) => s.map((it, i) => (i === idx ? { ...it, qty: q } : it)));
  }

  function removeItem(idx: number) {
    setItems((s) => s.filter((_, i) => i !== idx));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      // create lead first
      const leadPayload = { name, phone, email, message: notes, source: "walk_in" };
      const leadResp = await api.leads.create(leadPayload);
      const leadId = leadResp?.lead_id ?? leadResp?.id ?? null;

      const orderPayload = {
        customer_name: name,
        customer_phone: phone,
        customer_email: email,
        items: items.map((it) => ({ sku: it.sku, name: it.name, quantity: it.qty })),
        source: "walk_in",
        lead_id: leadId,
        walk_in_agent: agent || undefined,
        walk_in_location: location || undefined,
        notes,
      };

      await api.orders.submit(orderPayload);

      toast.success("Walk-in recorded and order created");
      setName("");
      setPhone("");
      setEmail("");
      setAgent("");
      setLocation("");
      setNotes("");
      setItems([]);
      onSuccess?.();
    } catch (err: any) {
      console.error(err);
      toast.error(err?.message || "Failed to submit walk-in");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <Input placeholder="Customer name" value={name} onChange={(e) => setName(e.target.value)} />
        <Input placeholder="Phone" value={phone} onChange={(e) => setPhone(e.target.value)} />
        <Input placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <Input placeholder="Staff agent" value={agent} onChange={(e) => setAgent(e.target.value)} />
        <Input placeholder="Location" value={location} onChange={(e) => setLocation(e.target.value)} />
      </div>

      <div>
        <label className="block mb-2 text-sm font-medium">Add product</label>
        {/* Swapped from the hand-rolled InventoryAutoComplete — this is
            literally the pattern EntityAutocomplete was built to generalize
            (ACE-Workspace-Standard.md Ch.4). */}
        <EntityAutocomplete<Product>
          placeholder="Search inventory..."
          fetchFn={(q) => api.inventory.search(q).then((r) => (Array.isArray(r) ? r : []))}
          getKey={(p) => p.id ?? p.sku ?? p.name}
          getLabel={(p) => p.name}
          getSubtitle={(p) => p.sku}
          onSelect={addProduct}
        />
      </div>

      {items.length > 0 && (
        <div className="space-y-2">
          {items.map((it, idx) => (
            <div key={idx} className="flex items-center gap-2">
              <div className="flex-1">
                <div className="font-medium">{it.name}</div>
                {it.sku && <div className="text-xs text-muted-foreground">{it.sku}</div>}
              </div>
              <input type="number" min={1} value={it.qty} onChange={(e) => updateQty(idx, Number(e.target.value))} className="w-20 p-2 border rounded" />
              <Button type="button" variant="destructive" onClick={() => removeItem(idx)}>Remove</Button>
            </div>
          ))}
        </div>
      )}

      <div>
        <label className="block mb-2 text-sm font-medium">Notes</label>
        <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} />
      </div>

      <div className="flex justify-end">
        <Button type="submit" disabled={submitting}>{submitting ? "Saving..." : "Record Walk-in"}</Button>
      </div>
    </form>
  );
}
