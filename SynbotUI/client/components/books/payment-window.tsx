/**
 * Payments - laid out like the client's Sage "Payments" window (meeting 7 Oct 2026):
 *
 *   Pay to: a supplier (their unpaid bills listed - tick "Pay" on what is being paid) or anyone
 *   else ("Pay to the order of", a one-off payment with no supplier record).
 *   Check / transfer no. · Date · Cash account (with its balance) · Memo.
 *   Apply to invoices  - the supplier's open bills: invoice, date due, amount due, amount paid, Pay.
 *   Apply to expenses  - the account each amount goes to (an expense, or a fixed-asset account such
 *                        as Furniture & Fixtures, which raises that asset's value on the balance
 *                        sheet and can start its depreciation schedule in the register).
 *
 * Bills paid post a supplier payment (allocated to the bills); expense lines post a payment voucher.
 * Both appear in the General Ledger, the bank account and every report, with their lineage.
 */
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Building2, Plus, Trash2, UserRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { books, BooksError, Dict, fmtDate, naira, newIdemKey, today } from "@/lib/books-api";
import { AccountPick, act, Amount, BankSelect, SupplierPick, useBooks } from "./kit";

type ExpLine = { account: Dict | null; description: string; amount: string; register: boolean; life: string };
const blankExp = (): ExpLine => ({ account: null, description: "", amount: "", register: true, life: "" });
const n = (v: any) => Number(v || 0);

function addressLines(a: any): string[] {
  if (!a) return [];
  if (typeof a === "string") return a.split(/\n|,(?=\s*\S)/).map((x) => x.trim()).filter(Boolean);
  if (typeof a === "object") return Object.values(a).map(String).filter(Boolean);
  return [];
}

export function PaymentWindow({ open, onClose, oneOff = false }: { open: boolean; onClose: (done?: boolean) => void; oneOff?: boolean }) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<"supplier" | "other">(oneOff ? "other" : "supplier");
  const [supplier, setSupplier] = useState<Dict | null>(null);
  const [payee, setPayee] = useState("");
  const [payeeAddress, setPayeeAddress] = useState("");
  const [h, setH] = useState({ reference: "", payment_date: today(), method: "TRANSFER", bank_account_id: "", memo: "", wht_amount: "" });
  const [tab, setTab] = useState<"invoices" | "expenses">(oneOff ? "expenses" : "invoices");
  const [pay, setPay] = useState<Record<string, string>>({});
  const [exp, setExp] = useState<ExpLine[]>([blankExp()]);
  const [busy, setBusy] = useState(false);
  const [dupe, setDupe] = useState<string | null>(null);
  const [idem] = useState(newIdemKey);
  useEffect(() => {
    if (!open) {
      setSupplier(null); setPayee(""); setPayeeAddress(""); setPay({}); setExp([blankExp()]); setDupe(null);
      setH({ reference: "", payment_date: today(), method: "TRANSFER", bank_account_id: "", memo: "", wht_amount: "" });
    } else { setMode(oneOff ? "other" : "supplier"); setTab(oneOff ? "expenses" : "invoices"); }
  }, [open, oneOff]);

  // opened from a bill ("Pay this bill"): ?supplier=<id>&pay=<bill id> - supplier chosen, that bill ticked
  const [sp] = useSearchParams();
  const fromSupplier = open && !oneOff ? sp.get("supplier") : null;
  const fromBill = open && !oneOff ? sp.get("pay") : null;
  const { data: preSup } = useBooks<Dict>(["pw-supplier", fromSupplier], `/suppliers/${fromSupplier}/overview`, undefined, !!fromSupplier && !supplier);
  useEffect(() => { if (preSup?.supplier && !supplier) setSupplier(preSup.supplier); }, [preSup]);
  const { data: items } = useBooks<Dict[]>(["ap-open", supplier?.id], "/payables/open-items", { supplier_id: supplier?.id }, !!supplier && mode === "supplier");
  const bills = useMemo(() => (items ?? []).filter((i) => i.doc_type === "BILL" && n(i.open_amount) > 0)
    .sort((a, b) => (a.due_date < b.due_date ? -1 : 1)), [items]);
  const credits = useMemo(() => (items ?? []).filter((i) => i.doc_type !== "BILL"), [items]);
  useEffect(() => {
    const b = fromBill ? bills.find((x) => String(x.doc_id) === fromBill) : null;
    if (b && !Object.keys(pay).length) setPay({ [b.doc_id]: n(b.open_amount).toFixed(2) });
  }, [bills, fromBill]);
  const { data: banks } = useBooks<Dict[]>(["bank-accounts"], "/banking/accounts");
  const { data: cats } = useBooks<Dict[]>(["asset-cats"], "/assets/categories");
  const bank = (banks ?? []).find((b) => b.id === h.bank_account_id);
  // current value of each fixed-asset account (whole ledger), to show what a payment does to it
  const { data: assetAccts } = useBooks<Dict[]>(["pw-asset-balances"], "/accounts", { account_type: "ASSET", history: true }, open);
  const assetBal: Record<string, number> = Object.fromEntries((assetAccts ?? []).filter((a) => a.subtype === "FIXED_ASSET").map((a) => [a.code, Number(a.balance_as_of || 0)]));

  const toInvoices = Object.values(pay).reduce((s, v) => s + n(v), 0);
  const toExpenses = exp.reduce((s, l) => s + n(l.amount), 0);
  const wht = mode === "supplier" ? n(h.wht_amount) : 0;
  const cashOut = toInvoices - wht + toExpenses;
  const name = mode === "supplier" ? supplier?.name : payee.trim();
  const catFor = (acct: Dict | null) => (cats ?? []).find((c) => c.asset_account_id === acct?.id);
  const setLine = (i: number, patch: Partial<ExpLine>) => setExp((xs) => xs.map((x, k) => (k === i ? { ...x, ...patch } : x)));

  const ready = !!name && !!h.bank_account_id && cashOut > 0 && wht <= toInvoices
    && exp.every((l) => !n(l.amount) || l.account) && !busy;

  const submit = async (confirmDuplicate = false) => {
    setBusy(true);
    const done: string[] = [];
    try {
      if (mode === "supplier" && toInvoices > 0) {
        const r = await books.post<Dict>("/payables/payments", {
          supplier_id: supplier!.id, payment_date: h.payment_date, method: h.method, bank_account_id: h.bank_account_id,
          amount: (toInvoices - wht).toFixed(2), wht_amount: wht ? wht.toFixed(2) : undefined, reference: h.reference || undefined,
          notes: h.memo || undefined, confirm_duplicate: confirmDuplicate,
          allocations: Object.entries(pay).filter(([, v]) => n(v) > 0).map(([bill_id, amount]) => ({ bill_id, amount })),
        }, idem + (confirmDuplicate ? "c" : ""));
        done.push(`payment ${r.payment_number ?? ""}`.trim());
      }
      const lines = exp.filter((l) => n(l.amount) > 0 && l.account);
      if (lines.length) {
        const v = await books.post<Dict>("/banking/vouchers", {
          kind: "SPEND", voucher_date: h.payment_date, bank_account_id: h.bank_account_id, payee: name,
          reference: h.reference || undefined,
          description: [h.memo, mode === "other" && payeeAddress ? `(${payeeAddress.replace(/\n/g, ", ")})` : ""].filter(Boolean).join(" ") || `Payment to ${name}`,
          lines: lines.map((l) => ({ account_id: l.account!.id, amount: n(l.amount).toFixed(2), description: l.description || undefined })),
        });
        done.push(`voucher ${v.voucher_number ?? ""}`.trim());
        // a purchase coded to a fixed-asset account goes into the depreciation register (already posted - no second journal)
        for (const [i, l] of lines.entries()) {
          const cat = catFor(l.account);
          if (!cat || !l.register) continue;
          await act(() => books.post("/assets", {
            name: l.description || `${l.account!.name} from ${name}`, category_id: cat.id, cost: n(l.amount).toFixed(2), residual_value: 0,
            acquisition_date: h.payment_date, funding: "POSTED", useful_life_months: l.life || cat.default_life_months || undefined,
            notes: `Paid to ${name} by ${v.voucher_number}`, source_line: `voucher:${v.id}:${i}`,
          }), `Added to the asset register (${cat.name})`);
        }
      }
      act(async () => done, `Posted: ${done.join(" and ")}`);
      qc.invalidateQueries({ queryKey: ["books"] });
      onClose(true);
    } catch (e) {
      const err = e as BooksError;
      if (err.code === "DUPLICATE_REFERENCE") setDupe(err.message); else act(async () => { throw e; });
    } finally { setBusy(false); }
  };

  const addr = mode === "supplier" ? addressLines(supplier?.address) : payeeAddress.split("\n").filter(Boolean);
  return (
    <DetailSheet open={open} onOpenChange={(o) => !o && onClose()} title="Payment"
                 description="Pay a supplier's bills, or pay anyone and choose the account it goes to. Posted to the bank, the General Ledger and every report."
                 footer={<div className="flex w-full flex-wrap items-center justify-between gap-2">
                   <div className="text-sm">Paying <strong>{naira(cashOut)}</strong> from {bank?.name ?? "—"}
                     {toInvoices > 0 && toExpenses > 0 && <span className="text-xs text-muted-foreground"> · {naira(toInvoices - wht)} to bills + {naira(toExpenses)} to accounts</span>}</div>
                   <Button disabled={!ready} onClick={() => submit(false)}>{busy ? "Posting…" : "Save payment"}</Button></div>}>
      <div className="space-y-4">
        {/* header - who, how, from where (as Sage) */}
        <div className="grid gap-4 rounded-lg border bg-muted/20 p-3 lg:grid-cols-[1.3fr_1fr]">
          <div className="space-y-2">
            <div className="flex gap-2">
              <Button size="sm" variant={mode === "supplier" ? "default" : "outline"} onClick={() => { setMode("supplier"); setTab("invoices"); }}><Building2 className="mr-1 h-4 w-4" />Supplier</Button>
              <Button size="sm" variant={mode === "other" ? "default" : "outline"} onClick={() => { setMode("other"); setTab("expenses"); setPay({}); }}><UserRound className="mr-1 h-4 w-4" />Someone else (one-off)</Button>
            </div>
            {mode === "supplier"
              ? <SupplierPick label="Vendor" value={supplier} onChange={(s) => { setSupplier(s); setPay({}); }} />
              : <div className="space-y-1"><Label className="text-xs">Pay to the order of</Label><Input placeholder="e.g. Mr Mufe" value={payee} onChange={(e) => setPayee(e.target.value)} /></div>}
            <div className="rounded-md border bg-background p-2 text-xs">
              <div className="text-[11px] uppercase text-muted-foreground">Pay to the order of</div>
              <div className="font-medium">{name || "—"}</div>
              {mode === "supplier" ? addr.map((x, i) => <div key={i}>{x}</div>)
                : <Textarea rows={2} className="mt-1 text-xs" placeholder="Address (optional)" value={payeeAddress} onChange={(e) => setPayeeAddress(e.target.value)} />}
              {mode === "supplier" && supplier?.payment_terms && <div className="text-muted-foreground">Terms: {supplier.payment_terms}</div>}
            </div>
          </div>
          <div className="space-y-2">
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1"><Label className="text-xs">Check / transfer no.</Label><Input placeholder="TRANSFER" value={h.reference} onChange={(e) => setH({ ...h, reference: e.target.value })} /></div>
              <div className="space-y-1"><Label className="text-xs">Date</Label><Input type="date" value={h.payment_date} onChange={(e) => setH({ ...h, payment_date: e.target.value })} /></div>
            </div>
            <div className="space-y-1"><Label className="text-xs">Method</Label>
              <select className="h-9 w-full rounded-md border bg-background px-2 text-sm" value={h.method} onChange={(e) => setH({ ...h, method: e.target.value })}>
                {["TRANSFER", "CHEQUE", "CASH", "OTHER"].map((m) => <option key={m} value={m}>{m.toLowerCase()}</option>)}</select></div>
            <BankSelect value={h.bank_account_id} onChange={(v) => setH({ ...h, bank_account_id: v })} label="Cash account" />
            <div className="flex justify-between rounded-md border bg-background px-2 py-1 text-xs"><span>Cash account balance</span><strong>{bank ? naira(bank.book_balance) : "—"}</strong></div>
            <div className="flex items-baseline justify-between rounded-md bg-primary/5 px-2 py-1"><span className="text-xs">Amount</span><span className="text-lg font-semibold tabular-nums">{naira(cashOut)}</span></div>
          </div>
        </div>
        <div className="space-y-1"><Label className="text-xs">Memo</Label><Input placeholder="What the payment is for" value={h.memo} onChange={(e) => setH({ ...h, memo: e.target.value })} /></div>

        {dupe && (
          <div className="space-y-2 rounded-lg border border-amber-400 bg-amber-50 p-3 text-sm dark:bg-amber-500/10">
            <div className="flex items-center gap-2 font-medium text-amber-800 dark:text-amber-300"><AlertTriangle className="h-4 w-4" />{dupe}</div>
            <div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => setDupe(null)}>Fix the reference</Button><Button size="sm" onClick={() => submit(true)}>It is genuine — post anyway</Button></div>
          </div>
        )}

        {/* apply to invoices / expenses (as Sage) */}
        <div className="flex gap-1 border-b">
          {mode === "supplier" && <button className={`-mb-px border-b-2 px-3 py-1.5 text-sm ${tab === "invoices" ? "border-primary font-medium" : "border-transparent text-muted-foreground"}`} onClick={() => setTab("invoices")}>Apply to invoices: {naira(toInvoices)}</button>}
          <button className={`-mb-px border-b-2 px-3 py-1.5 text-sm ${tab === "expenses" ? "border-primary font-medium" : "border-transparent text-muted-foreground"}`} onClick={() => setTab("expenses")}>Apply to expenses / assets: {naira(toExpenses)}</button>
        </div>

        {tab === "invoices" && mode === "supplier" && (
          !supplier ? <p className="text-sm text-muted-foreground">Choose the vendor: their unpaid bills appear here.</p>
            : bills.length === 0 ? <p className="text-sm text-muted-foreground">No unpaid bills for {supplier.name}.</p> : (
              <>
                <Table>
                  <TableHeader><TableRow><TableHead>Invoice</TableHead><TableHead>Date due</TableHead><TableHead className="text-right">Amount due</TableHead>
                    <TableHead>Description</TableHead><TableHead className="w-36 text-right">Amount paid</TableHead><TableHead className="w-12 text-center">Pay</TableHead></TableRow></TableHeader>
                  <TableBody>{bills.map((b) => {
                    const on = n(pay[b.doc_id]) > 0;
                    return (
                      <TableRow key={b.doc_id} className={on ? "bg-primary/5" : ""}>
                        <TableCell className="font-mono text-xs">{b.supplier_ref || b.doc_number}</TableCell>
                        <TableCell className={`whitespace-nowrap text-xs ${b.due_date < today() ? "text-red-600" : ""}`}>{fmtDate(b.due_date)}</TableCell>
                        <TableCell className="text-right"><Amount value={b.open_amount} /></TableCell>
                        <TableCell className="text-xs text-muted-foreground">{b.doc_number !== (b.supplier_ref || b.doc_number) ? `bill ${b.doc_number}` : ""}</TableCell>
                        <TableCell><Input className="h-8 text-right" type="number" value={pay[b.doc_id] ?? ""} onChange={(e) => setPay({ ...pay, [b.doc_id]: e.target.value })} /></TableCell>
                        <TableCell className="text-center"><input type="checkbox" className="h-4 w-4" checked={on}
                          onChange={(e) => setPay({ ...pay, [b.doc_id]: e.target.checked ? Number(b.open_amount).toFixed(2) : "" })} /></TableCell>
                      </TableRow>);
                  })}
                    <TableRow className="font-semibold"><TableCell colSpan={2}>Total owed</TableCell><TableCell className="text-right"><Amount value={bills.reduce((s, b) => s + n(b.open_amount), 0)} /></TableCell>
                      <TableCell /><TableCell className="text-right"><Amount value={toInvoices} /></TableCell><TableCell /></TableRow>
                  </TableBody>
                </Table>
                {credits.length > 0 && <p className="text-xs text-muted-foreground">{supplier.name} also has {credits.length} credit(s) / payment(s) on account not yet applied.</p>}
                <div className="flex items-center gap-2"><Label className="text-xs">WHT withheld (owed to FIRS)</Label>
                  <Input className="h-8 w-40" type="number" value={h.wht_amount} onChange={(e) => setH({ ...h, wht_amount: e.target.value })} /></div>
              </>
            )
        )}

        {tab === "expenses" && (
          <div className="space-y-3">
            {exp.map((l, i) => {
              const cat = catFor(l.account);
              const now = cat ? Number(assetBal[cat.asset_code_gl] ?? 0) : 0;
              return (
                <div key={i} className="space-y-2 rounded-lg border p-3">
                  <div className="grid gap-2 md:grid-cols-[minmax(180px,220px)_1fr_minmax(120px,160px)_auto] md:items-end">
                    <div className="space-y-1"><Label className="text-xs">What is it?</Label>
                      <select className="h-9 w-full rounded-md border bg-background px-2 text-sm" value={cat ? cat.id : "expense"}
                              onChange={(e) => {
                                const c = (cats ?? []).find((x) => x.id === e.target.value);
                                setLine(i, { account: c ? { id: c.asset_account_id, code: c.asset_code_gl, name: c.asset_account_name, subtype: "FIXED_ASSET" } : null });
                              }}>
                        <option value="expense">An expense / other account</option>
                        <optgroup label="A fixed asset">{(cats ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</optgroup>
                      </select></div>
                    <div className="space-y-1"><Label className="text-xs">{cat ? "Asset account" : "Account"}</Label>
                      <AccountPick value={l.account} onChange={(a) => setLine(i, { account: a })} /></div>
                    <div className="space-y-1"><Label className="text-xs">Amount</Label>
                      <Input className="border text-right" type="number" placeholder="0.00" value={l.amount} onChange={(e) => setLine(i, { amount: e.target.value })} /></div>
                    <Button size="icon" variant="ghost" title="Remove line" onClick={() => setExp((xs) => xs.length > 1 ? xs.filter((_, k) => k !== i) : [blankExp()])}><Trash2 className="h-4 w-4" /></Button>
                  </div>
                  <div className="space-y-1"><Label className="text-xs">Description</Label>
                    <Input placeholder={cat ? "e.g. 2 visitors chairs for MD's office" : "What it is for"} value={l.description} onChange={(e) => setLine(i, { description: e.target.value })} /></div>
                  {cat && (
                    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-md border border-sky-300 bg-sky-50 px-3 py-2 text-xs dark:bg-sky-500/10">
                      <span><strong>{cat.name}</strong> ({cat.asset_code_gl}) on the balance sheet: {naira(now)} → <strong>{naira(now + n(l.amount))}</strong></span>
                      <label className="flex items-center gap-1"><input type="checkbox" checked={l.register} onChange={(e) => setLine(i, { register: e.target.checked })} />Add to the asset register</label>
                      {l.register && cat.depreciable && <label className="flex items-center gap-1">Useful life (months)
                        <Input className="h-7 w-24 text-xs" type="number" placeholder={cat.default_life_months ? String(cat.default_life_months) : "e.g. 48"} value={l.life} onChange={(e) => setLine(i, { life: e.target.value })} /></label>}
                      {!cat.depreciable && <span className="text-muted-foreground">not depreciated</span>}
                    </div>
                  )}
                </div>
              );
            })}
            <Button size="sm" variant="outline" onClick={() => setExp((xs) => [...xs, blankExp()])}><Plus className="mr-1 h-4 w-4" />Add line</Button>
            {exp.some((l) => catFor(l.account) && l.register && catFor(l.account)?.depreciable && !l.life && !catFor(l.account)?.default_life_months) &&
              <p className="text-xs text-amber-700">Enter the useful life for the asset line(s), or untick "Add to the asset register" and register it later from Fixed Assets.</p>}
          </div>
        )}
      </div>
    </DetailSheet>
  );
}
