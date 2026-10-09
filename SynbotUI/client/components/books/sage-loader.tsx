/**
 * Sage reports into ACE Books' history, from the Sage Import page. Every file is checked first
 * (recognised from its header, loaded and checked, then undone - nothing kept), so the user sees
 * what loading would do; "Load" repeats the same checks and keeps the result. Refused:
 * rows dated after the hand-over (ACE Books keeps the books from the next day), a General Ledger
 * that does not tie to Sage's ending balances, and files that are not Sage reports.
 * Loading a file replaces that report's rows for the file's own dates - never duplicates.
 */
import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, FileSpreadsheet, Loader2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { books, BooksError, Dict, fmtDate, naira, num, today } from "@/lib/books-api";
import { askConfirm } from "@/lib/ask";
import { useBooks } from "./kit";

type Item = { file: File; state: "checking" | "checked" | "loading" | "loaded" | "error"; result?: Dict; error?: string };

const ORDER = ["ITEM_MASTER", "CUSTOMER_LIST", "VENDOR_LIST", "GENERAL_LEDGER", "CUSTOMER_LEDGER", "VENDOR_LEDGER", "SALES_JOURNAL",
  "COGS_JOURNAL", "PURCHASE_JOURNAL", "CASH_RECEIPTS_JOURNAL", "CASH_DISBURSEMENTS_JOURNAL", "GENERAL_JOURNAL", "ITEM_COSTING"];

async function send(file: File, confirm: boolean): Promise<Dict> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("confirm", confirm ? "true" : "false");
  return books.upload<Dict>("/sage-history/upload", fd);
}

const REQUIRED = [["GENERAL_LEDGER", "General Ledger"], ["CUSTOMER_LEDGER", "Customer Ledger"], ["VENDOR_LEDGER", "Vendor Ledger"],
  ["SALES_JOURNAL", "Sales Journal"], ["TRIAL_BALANCE", "General Ledger Trial Balance"], ["OPEN_AR", "Aged Receivables"],
  ["OPEN_AP", "Aged Payables"], ["INVENTORY", "Inventory Valuation"]];
const OPTIONAL = "Cash Receipts, Cash Disbursements, Purchase, Cost of Goods Sold and General journals, Item Costing, Item Master List, Customer List, Vendor Master File";

/** Sage is the record while staff get used to ACE: the full export set as of one date brings ACE
 *  up to that date (history, every account's balance, open invoices / bills, stock, invoice numbers)
 *  and moves the hand-over there. Check first (nothing kept), then confirm. */
export function SageRollForward({ onDone }: { onDone?: () => void }) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [asOf, setAsOf] = useState(today());
  const [plan, setPlan] = useState<Dict | null>(null);
  const [done, setDone] = useState<Dict | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<"check" | "run" | null>(null);
  const [voidInv, setVoidInv] = useState(false);
  const send = async (confirm: boolean) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    fd.append("as_of", asOf);
    fd.append("confirm", confirm ? "true" : "false");
    fd.append("void_ace_invoices", voidInv ? "true" : "false");
    return books.upload<Dict>("/sage-history/rollforward", fd);
  };
  const check = async () => {
    setBusy("check"); setErr(null); setPlan(null); setDone(null);
    try { setPlan(await send(false)); } catch (e) { setErr((e as BooksError).message); }
    setBusy(null);
  };
  const run = async () => {
    if (!plan || !(await askConfirm(`Bring ACE Books up to Sage as of ${fmtDate(asOf)}? Every account, open invoice, bill and stock line will match Sage at that date, and ACE takes over from the next day.`))) return;
    setBusy("run"); setErr(null);
    try { setDone(await send(true)); setPlan(null); qc.invalidateQueries({ queryKey: ["books"] }); onDone?.(); }
    catch (e) { setErr((e as BooksError).message); }
    setBusy(null);
  };
  const blocking: Dict[] = plan?.blocking_documents ?? [];
  const toVoid: Dict[] = plan?.invoices_to_void ?? [];
  return (
    <div className="space-y-3 rounded-xl border border-primary/30 p-6">
      <h2 className="text-lg font-semibold">Bring ACE up to date from Sage</h2>
      <p className="text-sm text-muted-foreground">
        While staff still record in Sage: export these reports from Sage, all <strong>as of the same date</strong>, and upload them together.
        ACE then matches Sage at that date (history, every account, open invoices and bills, stock, the next invoice number) and keeps
        the books from the next day. Repeat whenever you like (e.g. every Friday) until the client works in ACE only.
      </p>
      <div className="grid gap-1 text-xs sm:grid-cols-2">
        <div><strong>Required:</strong> {REQUIRED.map(([, l]) => l).join(", ")}.</div>
        <div><strong>Also load when available:</strong> {OPTIONAL}.</div>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <input ref={input} type="file" multiple accept=".xlsx,.xls,.csv" className="hidden" onChange={(e) => { setFiles(Array.from(e.target.files ?? [])); setPlan(null); setDone(null); setErr(null); }} />
        <Button variant="outline" onClick={() => input.current?.click()}><Upload className="mr-2 h-4 w-4" />Choose the export set{files.length ? ` (${files.length} files)` : ""}</Button>
        <div><div className="text-xs text-muted-foreground">Sage reports as of</div><Input type="date" className="h-9 w-44" value={asOf} onChange={(e) => { setAsOf(e.target.value); setPlan(null); }} /></div>
        <Button disabled={!files.length || !!busy} onClick={check}>{busy === "check" ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Checking…</> : "Check"}</Button>
      </div>
      {err && <p className="flex items-start gap-1 text-sm text-red-600"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{err}</p>}
      {plan && (
        <div className="space-y-2 rounded-md border bg-muted/30 p-3 text-sm">
          <div className="font-semibold">What will happen (nothing has changed yet)</div>
          <ul className="list-disc space-y-1 pl-5 text-xs">
            <li>Hand-over moves from <strong>{fmtDate(plan.previous_hand_over)}</strong> to <strong>{fmtDate(plan.as_of)}</strong>; ACE keeps the books from the next day.</li>
            <li>{(plan.loaded ?? []).filter((l: Dict) => !l.note).length} Sage report(s) loaded as history.</li>
            <li>Every account brought to Sage's balance: one journal per month ({(plan.journals ?? []).map((d: string) => fmtDate(d)).join(", ")}).</li>
            <li>Open receivables replaced by Sage's aged report: {num(plan.receivables?.documents)} invoices, {naira(plan.receivables?.aged_report_total ?? 0)}
              {Number(plan.receivables?.aged_report_total) !== Number(plan.receivables?.control_account) && ` (control account ${naira(plan.receivables?.control_account ?? 0)} - the difference goes to Data issues)`}.</li>
            <li>Open payables replaced: {num(plan.payables?.documents)} bills, {naira(plan.payables?.aged_report_total ?? 0)}.</li>
            <li>Stock replaced by Sage's valuation: {num(plan.stock?.items_loaded)} items, {naira(plan.stock?.value_loaded ?? 0)}.</li>
            <li>Next invoice number: <strong>{plan.next_invoice_number ?? "unchanged"}</strong>.</li>
            {(plan.trial_balance_vs_general_ledger ?? []).length > 0 && <li>{plan.trial_balance_vs_general_ledger.length} account(s) differ between Sage's trial balance and its General Ledger (Sage's own difference) - listed in Data issues.</li>}
          </ul>
          {blocking.length > 0 && (
            <div className="rounded-md border border-red-300 bg-red-50 p-2 text-xs dark:bg-red-500/10">
              <div className="font-semibold text-red-700">Entered in ACE for days Sage covers - void these in ACE first (Sage already has them):</div>
              {blocking.map((d) => <div key={d.id}>{d.kind} {d.number} · {fmtDate(d.date)} · {naira(d.total)}</div>)}
            </div>
          )}
          {toVoid.length > 0 && (
            <label className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-2 text-xs dark:bg-amber-500/10">
              <input type="checkbox" className="mt-0.5" checked={voidInv} onChange={(e) => setVoidInv(e.target.checked)} />
              <span>{toVoid.length} invoice(s) were raised in ACE for days Sage covers ({toVoid.map((d) => d.number).join(", ")}). Void them as part of this update - Sage has these sales.</span>
            </label>
          )}
          <div className="flex justify-end">
            <Button disabled={!!busy || blocking.length > 0 || (toVoid.length > 0 && !voidInv)} onClick={run}>
              {busy === "run" ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Updating ACE…</> : `Bring ACE up to ${fmtDate(plan.as_of)}`}</Button>
          </div>
        </div>
      )}
      {done && (
        <p className="flex items-start gap-1 text-sm text-emerald-700"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
          ACE is up to date with Sage as of {fmtDate(done.as_of)}: {done.journals?.length ?? 0} balancing journal(s), next invoice {done.next_invoice_number ?? "unchanged"}
          {done.voided?.length ? `, voided ${done.voided.join(", ")}` : ""}. Every account equals Sage at that date.</p>
      )}
    </div>
  );
}

export function SageBooksLoader() {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [items, setItems] = useState<Item[]>([]);
  const { data: range, refetch } = useBooks<Dict>(["ledger-range"], "/ledger/range");
  const set = (name: string, patch: Partial<Item>) => setItems((xs) => xs.map((x) => (x.file.name === name ? { ...x, ...patch } : x)));

  const pick = async (files: FileList | null) => {
    const list = Array.from(files ?? []);
    if (!list.length) return;
    setItems((xs) => [...xs.filter((x) => !list.some((f) => f.name === x.file.name)), ...list.map((f) => ({ file: f, state: "checking" as const }))]);
    for (const f of list) {
      try { set(f.name, { state: "checked", result: await send(f, false) }); }
      catch (e) { set(f.name, { state: "error", error: (e as BooksError).message }); }
    }
    if (input.current) input.current.value = "";
  };
  const load = async (it: Item) => {
    set(it.file.name, { state: "loading" });
    try {
      const r = await send(it.file, true);
      set(it.file.name, { state: "loaded", result: r });
      refetch(); qc.invalidateQueries({ queryKey: ["books"] });
    } catch (e) { set(it.file.name, { state: "error", error: (e as BooksError).message }); }
  };
  const loadable = (it: Item) => it.state === "checked" && it.result?.status === "PREVIEW";
  const loadAll = async () => {
    // masters first (so ledgers match customers, suppliers and items), the GL, then journals - as Sage reports depend on each other
    const queue = items.filter(loadable).sort((a, b) => ORDER.indexOf(a.result?.kind) - ORDER.indexOf(b.result?.kind));
    for (const it of queue) await load(it);
  };
  const h = range?.history_until;

  return (
    <div className="space-y-6">
      <SageRollForward onDone={() => refetch()} />
      <div className="space-y-2 rounded-xl border border-info/30 p-6">
        <h2 className="text-lg font-semibold">Correct or complete Sage history (single reports)</h2>
        <p className="text-sm text-muted-foreground">
          Upload Sage 50 report exports (Excel or CSV). Each file is recognised from its header and <strong>checked first: nothing changes until you press Load</strong>.
          Loading replaces that report's Sage history for the file's own dates, so loading the same file twice never duplicates anything.
          ACE Books keeps the books from {h ? fmtDate(new Date(new Date(h).getTime() + 86400000).toISOString().slice(0, 10)) : "the hand-over"}: rows dated after
          {h ? ` ${fmtDate(h)}` : " the hand-over"} are refused, because those days are already recorded in ACE Books.
        </p>
        <p className="text-xs text-muted-foreground">
          Accepted: General Ledger (detail, with beginning balances), Customer Ledger, Vendor Ledger, Sales / Cash Receipts / Cash Disbursements /
          Purchase / Cost of Goods Sold / General journals, Item Costing, Item Master List, Customer List, Vendor Master File.
          Trial balance, aged receivables / payables and inventory valuation are recognised but only used when ACE Books takes over from Sage.
        </p>
        <div className="flex flex-wrap gap-2 pt-1">
          <input ref={input} type="file" multiple accept=".xlsx,.xls,.csv" className="hidden" onChange={(e) => pick(e.target.files)} />
          <Button onClick={() => input.current?.click()}><Upload className="mr-2 h-4 w-4" />Choose Sage files</Button>
          {items.some(loadable) && <Button variant="outline" onClick={loadAll}>Load all checked files ({items.filter(loadable).length})</Button>}
        </div>
      </div>

      {items.length > 0 && (
        <Table>
          <TableHeader><TableRow><TableHead>File</TableHead><TableHead>Sage report</TableHead><TableHead>Dates</TableHead><TableHead className="text-right">Rows</TableHead>
            <TableHead>Check</TableHead><TableHead /></TableRow></TableHeader>
          <TableBody>{items.map((it) => {
            const r = it.result ?? {};
            const rows = r.lines ?? r.rows ?? r.updated ?? r.added;
            return (
              <TableRow key={it.file.name}>
                <TableCell className="max-w-[220px]"><div className="flex items-center gap-2"><FileSpreadsheet className="h-4 w-4 shrink-0 text-muted-foreground" /><span className="truncate" title={it.file.name}>{it.file.name}</span></div></TableCell>
                <TableCell className="text-sm">{r.label ?? (it.state === "error" ? "—" : "…")}</TableCell>
                <TableCell className="whitespace-nowrap text-xs">{r.from ? `${fmtDate(r.from)} – ${fmtDate(r.to)}` : "—"}</TableCell>
                <TableCell className="text-right">{rows != null ? num(rows) : ""}</TableCell>
                <TableCell className="max-w-[360px] text-xs">
                  {it.state === "checking" && <span className="flex items-center gap-1 text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" />Checking…</span>}
                  {it.state === "loading" && <span className="flex items-center gap-1 text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" />Loading…</span>}
                  {it.state === "error" && <span className="flex items-start gap-1 text-red-600"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{it.error}</span>}
                  {it.state === "checked" && r.status === "PREVIEW" && <span className="flex items-start gap-1 text-emerald-700"><CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    Ready.{r.replaces ? " Replaces the Sage history already loaded for these dates." : " New dates."}</span>}
                  {it.state === "checked" && r.status === "REFUSED" && <span className="flex items-start gap-1 text-red-600"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{(r.problems ?? []).join(" ")}</span>}
                  {r.status === "NOT_LOADED" && <span className="text-muted-foreground">{r.message}</span>}
                  {it.state === "loaded" && <span className="flex items-start gap-1 text-emerald-700"><CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    Loaded into ACE Books{r.data_issues ? ` · data issues re-checked (${r.data_issues.open ?? 0} open)` : ""}.</span>}
                </TableCell>
                <TableCell>{loadable(it) && <Button size="sm" onClick={() => load(it)}>Load</Button>}</TableCell>
              </TableRow>
            );
          })}</TableBody>
        </Table>
      )}

      <div className="space-y-2">
        <h3 className="text-sm font-semibold">Sage history in ACE Books</h3>
        {!range ? <Loader2 className="h-4 w-4 animate-spin" /> : (
          <Table>
            <TableHeader><TableRow><TableHead>Sage report</TableHead><TableHead>From</TableHead><TableHead>To</TableHead><TableHead className="text-right">Rows</TableHead><TableHead>Last loaded</TableHead></TableRow></TableHeader>
            <TableBody>{(range.loaded ?? []).map((c: Dict) => (
              <TableRow key={c.kind}><TableCell>{c.kind.replace(/_/g, " ").toLowerCase().replace(/^./, (x: string) => x.toUpperCase())}</TableCell>
                <TableCell className="text-xs">{fmtDate(c.date_from)}</TableCell><TableCell className="text-xs">{fmtDate(c.date_to)}</TableCell>
                <TableCell className="text-right">{num(c.rows)}</TableCell><TableCell className="text-xs">{fmtDate(c.last_loaded)}</TableCell></TableRow>))}</TableBody>
          </Table>
        )}
      </div>
    </div>
  );
}
