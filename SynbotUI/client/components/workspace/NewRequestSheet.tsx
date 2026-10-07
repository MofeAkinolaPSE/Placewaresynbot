import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api-client";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { EntityAutocomplete } from "@/components/workspace/EntityAutocomplete";

/**
 * "Make New Request" -- raise an invoice for a customer and queue it for QC.
 * One form, shared by the Customer Workspace (opened from a customer's record)
 * and Frontdesk (opened from the page header, customer picked in the sheet),
 * so both entry points create exactly the same invoice via
 * POST /frontdesk/customers/{id}/quick-request.
 */

export type CustomerSearchResult = { id: number; name: string; customer_code?: string; phone?: string };
type ItemRow = {
  product: string; quantity: number; unit_price: number;
  // Carried through to the invoice so dispatch can deduct the right stock.
  // Without it the backend can only name-match, which silently fails to
  // decrement anything when the typed product isn't an exact catalogue name.
  sku?: string;
  batch_number?: string; manufacture_date?: string; expiry_date?: string;
};
// GET /inventory/search's real return shape (v_inventory).
type InventorySuggestion = {
  sku?: string; name: string; category?: string; current_stock?: number; selling_price?: number;
  batch_number?: string; expiry_date?: string;
  // ranked by the server: sellable first, then a lot whose receipt Finance still has to record
  sellable?: boolean; receipt_pending?: boolean; stock_note?: string | null;
};

const fmt = (n: number | null | undefined) =>
  typeof n === "number" ? `₦${n.toLocaleString("en-NG", { minimumFractionDigits: 2 })}` : "—";

const BLANK_ITEM: ItemRow = { product: "", quantity: 1, unit_price: 0 };

// customer_360 splits the address and city, but most records keep the city
// inline in the address string already ("...OJODU BERGER, LAGOS"), so only
// append it when it isn't there to avoid "LAGOS, LAGOS".
function buildBillingAddress(cust: any): string {
  const address = String(cust?.address || "").trim();
  const city = String(cust?.city || "").trim();
  if (!address) return city;
  if (!city || address.toLowerCase().includes(city.toLowerCase())) return address;
  return `${address}, ${city}`;
}

function resolveCustomerTerms(cust: any): string | null {
  const terms = String(cust?.terms || "").trim();
  if (terms) return terms;
  const days = cust?.payment_terms_days;
  return days != null ? `Net ${days} Days` : null;
}

export function NewRequestSheet({
  open,
  onOpenChange,
  customer,
  onCustomerChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  customer: CustomerSearchResult | null;
  onCustomerChange: (c: CustomerSearchResult) => void;
  /** Receives the quick-request response ({ invoice, ... }). */
  onCreated?: (data: any) => void;
}) {
  const { toast } = useToast();
  // Lets the sheet pick/change the customer inline instead of forcing staff
  // to close it and search elsewhere first.
  const [changingCustomer, setChangingCustomer] = useState(false);
  const [items, setItems] = useState<ItemRow[]>([BLANK_ITEM]);
  const [paymentMethod, setPaymentMethod] = useState("cash");
  const [notes, setNotes] = useState("");

  // Invoice Details — Bill To/Ship To, PO, Payment Terms, Shipping Method.
  // Matches the real Placeware paper invoice's fields (see printInvoice()
  // in InvoicesTab.tsx, which this same data feeds).
  const [billingAddress, setBillingAddress] = useState("");
  const [shippingAddress, setShippingAddress] = useState("");
  const [sameAsBilling, setSameAsBilling] = useState(true);
  const [customerPo, setCustomerPo] = useState("");
  const [paymentTerms, setPaymentTerms] = useState("Due on Receipt");
  const [shippingMethod, setShippingMethod] = useState("");

  // Item-row inventory autocomplete, debounced per row against GET
  // /inventory/search. Only one row can be typed in at a time, so a single
  // slot keyed by row index is enough.
  const [itemSuggestions, setItemSuggestions] = useState<{ idx: number; results: InventorySuggestion[] } | null>(null);
  const itemSearchTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isMounted = useRef(true);
  useEffect(() => () => {
    isMounted.current = false;
    if (itemSearchTimeout.current) clearTimeout(itemSearchTimeout.current);
  }, []);

  function handleProductInputChange(idx: number, value: string) {
    // Drop any previously-picked sku: it belonged to the old product, and a
    // stale sku would make dispatch deduct stock from the wrong item.
    setItems((prev) => prev.map((r, i) => (i === idx ? { ...r, product: value, sku: undefined } : r)));
    if (itemSearchTimeout.current) clearTimeout(itemSearchTimeout.current);
    const q = value.trim();
    if (q.length < 2) {
      setItemSuggestions(null);
      return;
    }
    itemSearchTimeout.current = setTimeout(async () => {
      try {
        const results = await api.inventory.search(q);
        if (isMounted.current) setItemSuggestions({ idx, results: (Array.isArray(results) ? results : []).slice(0, 8) });
      } catch {
        if (isMounted.current) setItemSuggestions(null);
      }
    }, 300);
  }

  function applyItemSuggestion(idx: number, sug: InventorySuggestion) {
    setItems((prev) => prev.map((r, i) =>
      i === idx ? {
        ...r, product: sug.name, sku: sug.sku ?? r.sku,
        unit_price: sug.selling_price ?? r.unit_price,
        batch_number: sug.batch_number ?? r.batch_number,
        expiry_date: sug.expiry_date ?? r.expiry_date,
      } : r
    ));
    setItemSuggestions(null);
  }

  // Same query key as the Customer Workspace's detail panel, so there this is
  // a cache hit rather than a second request.
  const { data: context } = useQuery({
    queryKey: ["customer-360", customer?.id],
    queryFn: () => api.crm.customer360(customer!.id),
    enabled: open && !!customer,
  });

  // Prefill Invoice Details from the customer's own record (customer_360
  // returns address/city/terms). Keyed by customer id so switching customers
  // re-fills, while a re-render mid-edit leaves what's being typed alone.
  const prefilledForRef = useRef<number | null>(null);
  useEffect(() => {
    const cust = (context as any)?.customer;
    if (!cust || !customer || prefilledForRef.current === customer.id) return;
    prefilledForRef.current = customer.id;
    // Set rather than fill-if-empty: the ref above already means this runs
    // once per customer, so a merge would only preserve the PREVIOUS
    // customer's address after switching -- which is exactly wrong.
    setBillingAddress(buildBillingAddress(cust));
    const terms = resolveCustomerTerms(cust);
    if (terms) setPaymentTerms(terms);
  }, [context, customer]);

  // A customer's stored terms won't always be one of the preset options (they
  // come from the Sage master data), and silently dropping an unknown value
  // would persist the wrong due_date -- the server derives it from this string.
  const termsOptions = useMemo(() => {
    const base = ["Due on Receipt", "Net 7 Days", "Net 15 Days", "Net 30 Days", "Net 60 Days"];
    return base.includes(paymentTerms) ? base : [...base, paymentTerms];
  }, [paymentTerms]);

  const quickRequestMutation = useMutation({
    mutationFn: () => api.frontdesk.quickRequest(customer!.id, {
      items: items
        .filter((it) => it.product.trim())
        .map((it) => ({
          product: it.product.trim(), quantity: it.quantity, unit_price: it.unit_price,
          sku: it.sku || undefined,
          batch_number: it.batch_number || undefined,
          manufacture_date: it.manufacture_date || undefined,
          expiry_date: it.expiry_date || undefined,
        })),
      payment_method: paymentMethod,
      notes: notes.trim() || undefined,
      billing_address: billingAddress.trim() || undefined,
      shipping_address: (sameAsBilling ? billingAddress : shippingAddress).trim() || undefined,
      customer_po: customerPo.trim() || undefined,
      payment_terms: paymentTerms,
      shipping_method: shippingMethod.trim() || undefined,
    }),
    onSuccess: (data: any) => {
      toast({ title: "Request created", description: "Invoice raised and queued for QC." });
      onOpenChange(false);
      setChangingCustomer(false);
      setItems([BLANK_ITEM]);
      setItemSuggestions(null);
      setNotes("");
      setCustomerPo("");
      setShippingMethod("");
      onCreated?.(data);
    },
    onError: (e: any) => toast({ title: "Request failed", description: e?.message, variant: "destructive" }),
  });

  const canSubmitRequest = !!customer && items.some((it) => it.product.trim() && it.quantity > 0);

  return (
    <DetailSheet
      open={open}
      onOpenChange={(o) => {
        onOpenChange(o);
        if (!o) setChangingCustomer(false);
      }}
      title="Make New Request"
      description={customer?.name ? `Raise a new invoice request for ${customer.name}.` : "Pick a customer below, then raise a new invoice request."}
      icon={Plus}
      footer={
        <Button className="w-full" disabled={!canSubmitRequest || quickRequestMutation.isPending} onClick={() => quickRequestMutation.mutate()}>
          {quickRequestMutation.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
          Raise Request
        </Button>
      }
    >
      <div className="space-y-3">
        <div className="space-y-1.5">
          <div className="text-xs font-semibold text-muted-foreground">CUSTOMER</div>
          {customer && !changingCustomer ? (
            <div className="flex items-center justify-between gap-2 rounded-lg border bg-muted/30 px-3 py-2">
              <div className="min-w-0">
                <div className="text-sm font-medium truncate">{customer.name || (context as any)?.customer?.name || "Loading…"}</div>
                {(customer.customer_code || customer.phone) && (
                  <div className="text-xs text-muted-foreground">{customer.customer_code || customer.phone}</div>
                )}
              </div>
              <Button variant="ghost" size="sm" className="flex-shrink-0" onClick={() => setChangingCustomer(true)}>
                Change
              </Button>
            </div>
          ) : (
            <>
              <EntityAutocomplete<CustomerSearchResult>
                placeholder="Search customer name or code…"
                fetchFn={(q) => api.crm.searchCustomers(q).then((r: any) => r?.data ?? [])}
                getKey={(c) => c.id}
                getLabel={(c) => c.name}
                getSubtitle={(c) => c.customer_code || c.phone}
                onSelect={(c) => {
                  onCustomerChange(c);
                  setChangingCustomer(false);
                }}
              />
              {customer && changingCustomer && (
                <Button variant="ghost" size="sm" onClick={() => setChangingCustomer(false)}>
                  Cancel
                </Button>
              )}
            </>
          )}
        </div>

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
                  {termsOptions.map((t) => (
                    <SelectItem key={t} value={t}>{t}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Shipping Method</label>
              <Input placeholder="e.g. Hand Delivery" value={shippingMethod} onChange={(e) => setShippingMethod(e.target.value)} />
            </div>
          </div>
        </div>

        <div className="text-xs font-semibold text-muted-foreground">ITEMS</div>
        {items.map((it, idx) => (
          <div key={idx} className="space-y-1">
            <div className="flex gap-2 items-start">
              <div className="relative flex-1">
                <Input
                  placeholder="Product"
                  value={it.product}
                  onChange={(e) => handleProductInputChange(idx, e.target.value)}
                  onBlur={() => setItemSuggestions((s) => (s?.idx === idx ? null : s))}
                />
                {itemSuggestions?.idx === idx && itemSuggestions.results.length > 0 && (
                  <ul className="absolute z-40 mt-1 w-72 bg-card border rounded shadow max-h-56 overflow-auto">
                    {itemSuggestions.results.map((sug) => (
                      <li
                        key={sug.sku ?? sug.name}
                        className="p-2 hover:bg-accent/10 cursor-pointer"
                        onMouseDown={(e) => { e.preventDefault(); applyItemSuggestion(idx, sug); }}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-medium truncate">{sug.name}</span>
                          {sug.selling_price != null && (
                            <span className="text-xs font-semibold text-green-600 flex-shrink-0 dark:text-green-300">{fmt(sug.selling_price)}</span>
                          )}
                        </div>
                        <div className="text-xs text-muted-foreground flex items-center gap-1.5">
                          {sug.sku && <span className="font-mono">{sug.sku}</span>}
                          <span className={sug.current_stock != null && sug.current_stock <= 0 ? "text-red-600 font-medium dark:text-red-300" : undefined}>
                            Stock: {sug.current_stock ?? "—"}
                          </span>
                          {sug.batch_number && <span>· batch {sug.batch_number}{sug.expiry_date ? ` exp ${String(sug.expiry_date).slice(0, 10)}` : ""}</span>}
                        </div>
                        {sug.stock_note && (
                          <div className={`text-[11px] ${sug.receipt_pending ? "text-amber-700 dark:text-amber-300" : "text-red-600 dark:text-red-300"}`}>{sug.stock_note}</div>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <Input
                type="number" min={1} placeholder="Qty" className="w-20"
                value={it.quantity}
                onChange={(e) => setItems((prev) => prev.map((r, i) => (i === idx ? { ...r, quantity: Number(e.target.value) || 1 } : r)))}
              />
              <Input
                type="number" min={0} placeholder="Unit price" className="w-28"
                value={it.unit_price}
                onChange={(e) => setItems((prev) => prev.map((r, i) => (i === idx ? { ...r, unit_price: Number(e.target.value) || 0 } : r)))}
              />
              <Button
                variant="ghost" size="icon"
                disabled={items.length === 1}
                onClick={() => {
                  setItems((prev) => prev.filter((_, i) => i !== idx));
                  setItemSuggestions(null);
                }}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
            {/* Batch Number/Expiry Date autofill from the inventory suggestion
                above; Manufacture Date always manual (no data source for it). */}
            <div className="grid grid-cols-3 gap-2 pl-1">
              <Input placeholder="Batch number" className="h-8 text-xs" value={it.batch_number ?? ""}
                onChange={(e) => setItems((prev) => prev.map((r, i) => (i === idx ? { ...r, batch_number: e.target.value } : r)))} />
              <Input type="month" className="h-8 text-xs" value={it.manufacture_date ?? ""}
                onChange={(e) => setItems((prev) => prev.map((r, i) => (i === idx ? { ...r, manufacture_date: e.target.value } : r)))} />
              <Input type="date" className="h-8 text-xs" value={it.expiry_date ?? ""}
                onChange={(e) => setItems((prev) => prev.map((r, i) => (i === idx ? { ...r, expiry_date: e.target.value } : r)))} />
            </div>
          </div>
        ))}
        <Button variant="outline" size="sm" onClick={() => setItems((prev) => [...prev, { ...BLANK_ITEM }])}>
          <Plus className="h-4 w-4 mr-1" /> Add item
        </Button>

        <div className="pt-2">
          <div className="text-xs font-semibold text-muted-foreground mb-1">PAYMENT METHOD</div>
          <Select value={paymentMethod} onValueChange={setPaymentMethod}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="cash">Cash</SelectItem>
              <SelectItem value="transfer">Transfer</SelectItem>
              <SelectItem value="credit">Credit</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <Textarea placeholder="Notes (optional)" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />

        <div className="flex justify-between font-bold pt-2 border-t">
          <span>Total</span>
          <span className="text-green-600 dark:text-green-300">
            {fmt(items.reduce((sum, it) => sum + it.quantity * it.unit_price, 0))}
          </span>
        </div>
      </div>
    </DetailSheet>
  );
}
