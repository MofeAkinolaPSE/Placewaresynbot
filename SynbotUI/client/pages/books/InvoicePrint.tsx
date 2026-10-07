/**
 * The printed invoice, in the client's own layout (their Sage invoice form):
 * company header · INVOICE · Invoice Number / Date / Page · Bill To / Ship To ·
 * Customer ID | Customer PO | Payment Terms · Sales Rep ID | Shipping Method | Ship Date | Due Date ·
 * Qty | Description | Batch Number | Man. Date | Exp. Date | Unit Price | Amount ·
 * Subtotal / Sales Tax / Total Invoice Amount / Payment/Credit Applied / TOTAL ·
 * Prepared by / Authorised by / Delivered / Customer Name / Customer Sign · notes and bank details.
 * Works for ACE Books invoices and for any invoice in the Sage history.
 */
import { useParams } from "react-router-dom";
import { Printer } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useBooks } from "@/components/books/kit";
import { Dict } from "@/lib/books-api";

const money = (v: any) => (v == null || v === "" ? "" : Number(v).toLocaleString("en-NG", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const qty = (v: any) => (v == null ? "" : Number(v).toLocaleString("en-NG", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const mdy = (v?: string | null) => (v ? `${Number(v.slice(5, 7))}/${Number(v.slice(8, 10))}/${v.slice(2, 4)}` : "");
const mmyy = (v?: string | null) => (v ? `${v.slice(5, 7)}/${v.slice(2, 4)}` : "");
const longDate = (v?: string | null) => (v ? new Date(`${v}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "");

function address(c: Dict | null | undefined): string[] {
  const d = c?.contact_details ?? {};
  const a = d.address ?? d.billing_address;
  const lines = typeof a === "string" ? a.split(/\n|,(?=\s*\S)/).map((s: string) => s.trim()).filter(Boolean) : a && typeof a === "object" ? Object.values(a).map(String).filter(Boolean) : [];
  return lines;
}

export default function InvoicePrint() {
  const { kind = "ace", id = "" } = useParams();
  const path = kind === "sage" ? `/sage-history/invoices/${encodeURIComponent(id)}` : `/sales/invoices/${id}`;
  const { data: inv, error } = useBooks<Dict>(["print", kind, id], path);
  const { data: lay } = useBooks<Dict>(["invoice-layout"], "/settings/invoice-layout");
  const custId = inv?.customer_id;
  const { data: cust } = useBooks<Dict>(["print-cust", custId], `/customers/${custId}/overview`, undefined, !!custId && kind === "sage");
  if (error) return <div className="p-8 text-sm text-red-600">Could not load the invoice.</div>;
  if (!inv || !lay) return <div className="p-8 text-sm text-muted-foreground">Preparing the invoice…</div>;
  const L = lay.layout;
  const customer = kind === "sage" ? cust?.customer : inv.customer;
  const lines: Dict[] = kind === "sage" ? inv.lines.map((l: Dict) => ({
    quantity: l.quantity, description: l.product_name || l.description, batch: l.batch_number ?? (l.sku?.match(/\(([^)]*)\)\s*\w*$/)?.[1] ?? ""),
    mfg: l.manufacture_date, exp: l.expiry_date, price: l.unit_price ?? (l.quantity ? Number(l.amount) / Number(l.quantity) : null), amount: l.amount,
  })) : [...(inv.lines ?? []).map((l: Dict) => ({
    quantity: l.line_type === "ITEM" || l.line_type === "SERVICE" ? l.quantity : null, description: l.description || l.sku,
    batch: l.batch_number ?? l.shipped_batch ?? "", mfg: l.manufacture_date ?? l.shipped_mfg, exp: l.expiry_date ?? l.shipped_expiry,
    price: l.line_type === "ITEM" || l.line_type === "SERVICE" ? l.unit_price : null, amount: l.line_total,
  })), ...(inv.history_lines ?? []).map((l: Dict) => ({
    quantity: l.quantity, description: l.product_name || l.description, batch: l.batch_number ?? "", mfg: l.manufacture_date, exp: l.expiry_date,
    price: l.unit_price, amount: l.amount,
  }))];
  const number = kind === "sage" ? inv.invoice_number : inv.invoice_number;
  const date = inv.invoice_date;
  const subtotal = lines.reduce((s, l) => s + Number(l.amount || 0), 0);
  const total = kind === "sage" ? Number(inv.total) : Number(inv.original_total ?? inv.total);
  const tax = kind === "sage" ? 0 : Number(inv.tax_total || 0);
  const applied = kind === "sage" ? Number(inv.paid || 0) : total - Number(inv.balance_due ?? 0);
  const terms = kind === "sage" ? "" : inv.terms_days === 0 ? "C.O.D." : inv.terms_days ? `Net ${inv.terms_days} Days` : "";
  const bill = [customer?.name ?? inv.customer_name, ...address(customer)];
  const ship = inv.ship_to ? [customer?.name ?? inv.customer_name, ...String(inv.ship_to).split(/\n|,(?=\s*\S)/).map((s) => s.trim())] : bill.slice(1);
  const blank = Math.max(0, 14 - lines.length);
  const cell = "border border-neutral-500 px-1.5 py-0.5";
  return (
    <div className="min-h-screen bg-neutral-200 py-6 print:bg-white print:py-0">
      <div className="mx-auto mb-3 flex max-w-[210mm] justify-end gap-2 print:hidden">
        <Button size="sm" onClick={() => window.print()}><Printer className="mr-1 h-4 w-4" />Print</Button>
      </div>
      <div className="mx-auto max-w-[210mm] bg-white p-[10mm] text-[11px] leading-tight text-black shadow print:shadow-none" style={{ fontFamily: "Arial, Helvetica, sans-serif" }}>
        {/* header */}
        <div className="flex justify-between">
          <div>
            <div className="text-[22px] font-black italic tracking-wide text-neutral-600">{(L.company_name || "").split(" ")[0]}</div>
            <div className="text-[12px] font-semibold tracking-widest text-neutral-600">{(L.company_name || "").split(" ").slice(1).join(" ")}</div>
            {(L.address_lines ?? []).map((a: string) => <div key={a}>{a.toUpperCase()}</div>)}
            {(L.phones ?? []).map((p: string) => <div key={p}>{p}</div>)}
            <div className="mt-1">{L.email}</div><div>{L.website}</div>
          </div>
          <div className="w-60">
            <table className="w-full"><tbody>
              <tr><td className="pr-2 text-right">Invoice Number:</td><td className="font-semibold">{number}</td></tr>
              <tr><td className="pr-2 text-right">Invoice Date:</td><td>{longDate(date)}</td></tr>
              <tr><td className="pr-2 text-right">Page:</td><td>1</td></tr>
            </tbody></table>
          </div>
        </div>
        <div className="my-3 text-center font-serif text-[26px] font-bold tracking-wider text-neutral-700">INVOICE</div>
        {/* bill / ship */}
        <div className="grid grid-cols-2 gap-6">
          <div className="border border-neutral-500"><div className="border-b border-neutral-500 bg-neutral-200 px-1.5 font-semibold">Bill To:</div>
            <div className="min-h-[64px] px-1.5 py-1">{bill.filter(Boolean).map((b, i) => <div key={i}>{b}</div>)}</div></div>
          <div className="border border-neutral-500"><div className="border-b border-neutral-500 bg-neutral-200 px-1.5 font-semibold">Ship to:</div>
            <div className="min-h-[64px] px-1.5 py-1">{ship.filter(Boolean).map((b, i) => <div key={i}>{b}</div>)}</div></div>
        </div>
        {/* terms grid */}
        <table className="mt-3 w-full border-collapse text-center">
          <tbody>
            <tr className="bg-neutral-200 font-semibold"><td className={cell}>Customer ID</td><td className={cell}>Customer PO</td><td className={cell} colSpan={2}>Payment Terms</td></tr>
            <tr><td className={cell}>{customer?.customer_code ?? inv.customer_code ?? ""}</td><td className={cell}>{inv.customer_po ?? inv.reference ?? ""}</td><td className={cell} colSpan={2}>{terms}</td></tr>
            <tr className="bg-neutral-200 font-semibold"><td className={cell}>Sales Rep ID</td><td className={cell}>Shipping Method</td><td className={cell}>Ship Date</td><td className={cell}>Due Date</td></tr>
            <tr><td className={cell}>{inv.sales_rep ?? ""}</td><td className={cell}>{inv.shipping_method ?? L.default_shipping_method ?? ""}</td><td className={cell} /><td className={cell}>{mdy(inv.due_date)}</td></tr>
          </tbody>
        </table>
        {/* lines */}
        <table className="mt-3 w-full border-collapse">
          <thead><tr className="bg-neutral-200 text-center font-semibold">
            <td className={cell}>Qty</td><td className={cell}>Description</td><td className={cell}>Batch Number</td><td className={cell}>Man. Date</td>
            <td className={cell}>Exp. Date</td><td className={cell}>Unit Price</td><td className={cell}>Amount</td></tr></thead>
          <tbody>
            {lines.map((l, i) => (
              <tr key={i} className="align-top">
                <td className="border-x border-neutral-500 px-1.5 text-right">{qty(l.quantity)}</td>
                <td className="border-x border-neutral-500 px-1.5">{l.description}</td>
                <td className="border-x border-neutral-500 px-1.5">{l.batch}</td>
                <td className="border-x border-neutral-500 px-1.5">{mmyy(l.mfg)}</td>
                <td className="border-x border-neutral-500 px-1.5">{mmyy(l.exp)}</td>
                <td className="border-x border-neutral-500 px-1.5 text-right">{money(l.price)}</td>
                <td className="border-x border-neutral-500 px-1.5 text-right">{money(l.amount)}</td>
              </tr>
            ))}
            {Array.from({ length: blank }).map((_, i) => (
              <tr key={`b${i}`}>{Array.from({ length: 7 }).map((__, k) => <td key={k} className="h-5 border-x border-neutral-500" />)}</tr>
            ))}
            <tr>{Array.from({ length: 7 }).map((_, k) => <td key={k} className="border-b border-neutral-500" />)}</tr>
          </tbody>
        </table>
        {/* signatures + totals */}
        <div className="mt-2 grid grid-cols-[1fr_260px] gap-4">
          <div className="space-y-2 pt-2">
            <div>Prepared by(Name/Sign) ..................................................</div>
            <div>Authorised by ..................................................</div>
            <div>Delivered ..................................................</div>
            <div>Customer Name ..................................................</div>
            <div>Customer Sign ..................................................</div>
            <div className="pt-4 text-[13px] font-bold">{L.footer_left}</div>
          </div>
          <div>
            <table className="w-full border-collapse"><tbody>
              <tr><td className={`${cell} text-right`}>Subtotal</td><td className={`${cell} text-right`}>{money(subtotal)}</td></tr>
              <tr><td className={`${cell} text-right`}>Sales Tax</td><td className={`${cell} text-right`}>{tax ? money(tax) : ""}</td></tr>
              <tr><td className={`${cell} text-right`}>Total Invoice Amount</td><td className={`${cell} text-right`}>{money(total)}</td></tr>
              <tr><td className={`${cell} text-right`}>Payment/Credit Applied</td><td className={`${cell} text-right`}>{applied ? money(applied) : ""}</td></tr>
              <tr className="bg-neutral-200 font-bold"><td className={`${cell} text-right`}>TOTAL</td><td className={`${cell} text-right`}>{money(total - applied)}</td></tr>
            </tbody></table>
            <div className="mt-3 font-bold">{L.payment_note}</div>
            {(L.bank_lines ?? []).map((b: string) => <div key={b} className="font-bold">{b}</div>)}
          </div>
        </div>
      </div>
    </div>
  );
}
