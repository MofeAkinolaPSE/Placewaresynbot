import { Fragment, useEffect, useState } from "react";
import { historyTarget, useDrill } from "@/components/books/drill-context";
import { SageTag } from "@/components/books/kit";
import { Link, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, CheckCircle2, ChevronDown, ChevronRight, Plus, Search, Trash2, XCircle } from "lucide-react";
import { GlAccountDetail } from "@/components/books/gl";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { FilterBar } from "@/components/workspace/FilterBar";
import { BooksShell } from "@/components/books/BooksShell";
import { JournalBody } from "@/components/books/lineage";
import { JournalReports } from "@/pages/books/BooksStatements";
import {
  AccountPick, AccountSheet, act, Amount, CsvButton, DateRange, Empty, ErrorNote, Loading, Section, sourceLink, StatusBadge,
  useBooks, useLines,
} from "@/components/books/kit";
import { books, Dict, fmtDate, monthStart, naira, newIdemKey, today, yearStart } from "@/lib/books-api";
import { askConfirm, askText } from "@/lib/ask";

export default function BooksLedger() {
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState(params.get("tab") ?? "gl");
  const open = (k: string, v: string | null) => { const p = new URLSearchParams(params); v ? p.set(k, v) : p.delete(k); setParams(p, { replace: true }); };
  return (
    <BooksShell title="Journals & Ledger"
                actions={<Button size="sm" onClick={() => open("new", "journal")}><Plus className="mr-1 h-4 w-4" />Journal entry</Button>}>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="journals">Journal entries</TabsTrigger>
          <TabsTrigger value="books">Journals by type</TabsTrigger>
          <TabsTrigger value="tb">Trial balance</TabsTrigger>
          <TabsTrigger value="gl">General ledger</TabsTrigger>
        </TabsList>
        <TabsContent value="journals"><JournalList onOpen={(id) => open("journal", id)} /></TabsContent>
        <TabsContent value="books">
          <p className="mb-3 text-sm text-muted-foreground">Sales, cash receipts, purchases, cash disbursements, cost of goods sold, inventory
            adjustments, general and fixed-asset journals, in Sage's own layout, for any period (Sage's years and ACE Books).</p>
          <JournalReports />
        </TabsContent>
        <TabsContent value="tb"><TrialBalance /></TabsContent>
        <TabsContent value="gl"><GeneralLedger onJournal={(id) => open("journal", id)} /></TabsContent>
      </Tabs>
      <JournalEditor open={params.get("new") === "journal" || !!params.get("edit")} editId={params.get("edit")}
                     onClose={(id) => { const p = new URLSearchParams(params); p.delete("new"); p.delete("edit"); if (id) p.set("journal", id); setParams(p, { replace: true }); }} />
      <JournalDetail id={params.get("journal")} onClose={() => open("journal", null)}
                     onEdit={(id) => { const p = new URLSearchParams(params); p.delete("journal"); p.set("edit", id); setParams(p, { replace: true }); }}
                     onOpen={(id) => open("journal", id)} />
    </BooksShell>
  );
}

const STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "POSTED", "REVERSED", "REJECTED"];

function JournalList({ onOpen }: { onOpen: (id: string) => void }) {
  const drill = useDrill();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [type, setType] = useState("");
  const [range, setRange] = useState({ from: monthStart(), to: today() });
  const { data, isLoading, error } = useBooks<any>(["journals", search, status, type, range], "/journals",
    { search, status: status || undefined, journal_type: type || undefined, from: range.from, to: range.to, limit: 300 });
  return (
    <Section title={`Journals${data ? ` (${data.total})` : ""}`} actions={<CsvButton filename="journals.csv" rows={data?.items} />}>
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <div className="flex-1"><FilterBar search={{ value: search, onChange: setSearch, placeholder: "Journal no., description, source ref" }}
          selects={[
            { label: "Status", value: status, onChange: setStatus, options: STATUSES.map((s) => ({ value: s, label: s.toLowerCase() })) },
            { label: "Type", value: type, onChange: setType, options: ["MANUAL", "SYSTEM", "OPENING", "CLOSING", "REVERSAL", "ADJUSTMENT"].map((s) => ({ value: s, label: s.toLowerCase() })) },
          ]} /></div>
        <DateRange from={range.from} to={range.to} onChange={(f, t) => setRange({ from: f ?? range.from, to: t })} />
      </div>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (data.items.length === 0 ? <Empty>No journals match.</Empty> : (
        <Table>
          <TableHeader><TableRow><TableHead>Journal</TableHead><TableHead>Date</TableHead><TableHead>Type</TableHead><TableHead>Description</TableHead><TableHead>Source</TableHead><TableHead className="text-right">Amount</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
          <TableBody>{data.items.map((j: Dict) => (
            <TableRow key={j.id ?? `s:${j.journal_date}:${j.source_ref}`} className="cursor-pointer hover:bg-muted/50"
                      onClick={() => (j.id ? onOpen(j.id) : drill?.open(historyTarget("journal", j)))}>
              <TableCell className="font-mono text-xs">{j.journal_number}{j.source === "SAGE" && <SageTag />}</TableCell><TableCell className="whitespace-nowrap">{fmtDate(j.journal_date)}</TableCell>
              <TableCell className="text-xs">{j.source === "SAGE" ? "general (Sage)" : j.journal_type.toLowerCase()}</TableCell>
              <TableCell className="max-w-[280px] truncate text-xs">{j.description}</TableCell>
              <TableCell className="font-mono text-xs">{j.source_ref}</TableCell>
              <TableCell className="text-right"><Amount value={j.total_debit} /></TableCell><TableCell><StatusBadge status={j.status} /></TableCell>
            </TableRow>
          ))}</TableBody>
        </Table>
      ))}
    </Section>
  );
}

type JLine = { account: Dict | null; debit: string; credit: string; description: string };
const blankJ = (): JLine => ({ account: null, debit: "", credit: "", description: "" });

function JournalEditor({ open, editId, onClose }: { open: boolean; editId: string | null; onClose: (id?: string) => void }) {
  const qc = useQueryClient();
  const [date, setDate] = useState(today());
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [idem, setIdem] = useState(newIdemKey);
  const L = useLines<JLine>(blankJ, [blankJ(), blankJ()]);
  const { data: existing } = useBooks<Dict>(["journal", editId], `/journals/${editId}`, undefined, !!editId);
  useEffect(() => {
    if (existing && editId) {
      setDate(existing.journal_date); setDescription(existing.description ?? "");
      L.setLines(existing.lines.map((l: Dict) => ({ account: { id: l.account_id, code: l.account_code, name: l.account_name },
        debit: Number(l.debit) ? String(l.debit) : "", credit: Number(l.credit) ? String(l.credit) : "", description: l.description ?? "" })));
    }
  }, [existing, editId]);
  useEffect(() => { if (!open) { L.setLines([blankJ(), blankJ()]); setDescription(""); setDate(today()); setIdem(newIdemKey()); } }, [open]);
  const dr = L.lines.reduce((s, l) => s + Number(l.debit || 0), 0);
  const cr = L.lines.reduce((s, l) => s + Number(l.credit || 0), 0);
  const diff = Math.round((dr - cr) * 100) / 100;
  const save = async () => {
    setBusy(true);
    const body = { journal_date: date, description, lines: L.lines.filter((l) => l.account).map((l) => ({ account_id: l.account?.id, debit: l.debit || 0, credit: l.credit || 0, description: l.description || undefined })) };
    const j = await act(() => (editId ? books.put(`/journals/${editId}`, body) : books.post("/journals", body, idem)), "Journal saved as draft");
    setBusy(false);
    if (j) { qc.invalidateQueries({ queryKey: ["books"] }); onClose(j.id); }
  };
  return (
    <DetailSheet open={open} onOpenChange={(o) => !o && onClose()} title={editId ? "Edit draft journal" : "New journal entry"}
                 description="Saved as a draft. Submit it for approval; once approved it is posted. Control accounts (debtors, creditors, stock) are fed by their own modules."
                 footer={<div className="flex w-full items-center justify-between text-sm">
                   <span>Dr {naira(dr)} · Cr {naira(cr)} {diff !== 0 ? <span className="text-red-600">· out by {naira(diff)}</span> : dr > 0 && <span className="text-emerald-600">· balanced</span>}</span>
                   <Button disabled={busy || dr === 0 || diff !== 0 || !description.trim()} onClick={save}>{busy ? "Saving…" : "Save draft"}</Button></div>}>
      <div className="space-y-3">
        <div className="grid grid-cols-[160px_1fr] gap-3">
          <div className="space-y-1"><Label className="text-xs">Date</Label><Input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></div>
          <div className="space-y-1"><Label className="text-xs">Narration</Label><Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Why this entry is being made" /></div>
        </div>
        {L.lines.map((l, i) => (
          <div key={i} className="grid grid-cols-[1fr_110px_110px_32px] items-end gap-2">
            <div className="space-y-1">
              <AccountPick label={i === 0 ? "Account" : undefined} value={l.account} onChange={(a) => L.update(i, { account: a })} />
              <Input className="h-7 text-xs" placeholder="Line description (optional)" value={l.description} onChange={(e) => L.update(i, { description: e.target.value })} />
            </div>
            <Input className="h-9" type="number" placeholder="Debit" value={l.debit} onChange={(e) => L.update(i, { debit: e.target.value, credit: e.target.value ? "" : l.credit })} />
            <Input className="h-9" type="number" placeholder="Credit" value={l.credit} onChange={(e) => L.update(i, { credit: e.target.value, debit: e.target.value ? "" : l.debit })} />
            <Button size="icon" variant="ghost" onClick={() => L.remove(i)}><Trash2 className="h-4 w-4" /></Button>
          </div>
        ))}
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={L.add}><Plus className="mr-1 h-4 w-4" />Add line</Button>
          {diff !== 0 && <Button size="sm" variant="ghost" onClick={() => L.setLines([...L.lines, { ...blankJ(), debit: diff < 0 ? String(-diff) : "", credit: diff > 0 ? String(diff) : "" }])}>Add balancing line</Button>}
        </div>
      </div>
    </DetailSheet>
  );
}

function JournalDetail({ id, onClose, onEdit, onOpen }: { id: string | null; onClose: () => void; onEdit: (id: string) => void; onOpen: (id: string) => void }) {
  const qc = useQueryClient();
  const { data: j, isLoading, error, refetch } = useBooks<Dict>(["journal", id], `/journals/${id}`, undefined, !!id);
  const [check, setCheck] = useState<Dict | null>(null);
  useEffect(() => setCheck(null), [id]);
  const done = () => { refetch(); qc.invalidateQueries({ queryKey: ["books"] }); };
  const run = async (action: string, body: Dict = {}, ok?: string) => { if (await act(() => books.post(`/journals/${id}/${action}`, body), ok)) done(); };
  // "Delete entry": posts the exact reversal on the entry's own date, so every balance and report is as
  // if it had never been posted; the entry and its reversal stay in Journals and the audit trail.
  const reverse = async () => {
    const reason = await askText(`Delete ${j?.journal_number}? Every report will go back to how it was before it was posted.

Why is it being deleted? (kept in the audit trail)`);
    if (!reason) return;
    const r = await act(() => books.post(`/journals/${id}/reverse`, { reason }), "Entry deleted - its reversal is posted on the same date");
    if (r) { done(); onClose(); }
  };
  const del = async () => { if (await askConfirm("Delete this draft?") && (await act(() => books.del(`/journals/${id}`), "Draft deleted"))) { qc.invalidateQueries({ queryKey: ["books"] }); onClose(); } };
  const link = j ? sourceLink(j.source_type, j.source_id) : null;
  const manual = j && (!j.source_type || j.source_type === "MANUAL_JOURNAL");
  return (
    <DetailSheet open={!!id} onOpenChange={(o) => !o && onClose()} title={j ? `Journal ${j.journal_number}` : "Journal"} description={j?.description}
                 footer={j && manual ? (
                   <div className="flex flex-wrap gap-2">
                     {j.status === "DRAFT" && <>
                       <Button size="sm" variant="outline" onClick={() => onEdit(j.id)}>Edit</Button>
                       <Button size="sm" variant="outline" onClick={async () => setCheck(await act(() => books.post(`/journals/${id}/validate`, {})) ?? null)}>Check</Button>
                       <Button size="sm" variant="ghost" onClick={del}>Delete</Button>
                       <Button size="sm" onClick={() => run("submit", {}, "Submitted for approval")}>Submit for approval</Button>
                       <Button size="sm" variant="secondary" onClick={() => run("post", {}, "Posted")}>Post now</Button></>}
                     {j.status === "SUBMITTED" && <>
                       <Button size="sm" variant="outline" onClick={async () => { const reason = await askText("Reason for rejecting?"); if (reason) run("reject", { reason }, "Rejected"); }}>Reject</Button>
                       <Button size="sm" onClick={async () => run("approve", { comment: (await askText("Approval comment (optional)")) || undefined }, "Approved")}>Approve</Button></>}
                     {j.status === "APPROVED" && <Button size="sm" onClick={() => run("post", {}, "Posted")}>Post</Button>}
                     {j.status === "POSTED" && !j.reversed_by_id && <Button size="sm" variant="destructive" onClick={reverse}>Delete entry</Button>}
                   </div>) : j?.status === "POSTED" && !j.reversed_by_id && j.journal_type !== "OPENING" ? (
                   <Button size="sm" variant="destructive" onClick={reverse}>Delete entry</Button>) : undefined}>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {check && (
        <div className={`mb-3 rounded-md border p-2 text-xs ${check.valid ? "border-emerald-400 text-emerald-700" : "border-red-400 text-red-700"}`}>
          {check.valid ? <span className="flex items-center gap-1"><CheckCircle2 className="h-4 w-4" />Ready to post.</span>
            : <ul className="space-y-1">{check.issues.map((x: Dict, i: number) => <li key={i} className="flex gap-1"><XCircle className="h-4 w-4 shrink-0" />{x.message}</li>)}</ul>}
        </div>
      )}
      {j && link && <Link className="mb-2 inline-flex items-center text-xs text-primary hover:underline" to={link}>open the source document's page <ArrowUpRight className="h-3 w-3" /></Link>}
      {id && <JournalBody key={`${id}:${j?.status}`} id={id} />}
    </DetailSheet>
  );
}

function TrialBalance() {
  const [mode, setMode] = useState<"asof" | "period">("asof");
  return (
    <div className="space-y-3">
      <div className="flex gap-1">
        <Button size="sm" variant={mode === "asof" ? "default" : "outline"} onClick={() => setMode("asof")}>General Ledger Trial Balance (as of a date)</Button>
        <Button size="sm" variant={mode === "period" ? "default" : "outline"} onClick={() => setMode("period")}>Working trial balance (period movements)</Button>
      </div>
      {mode === "asof" ? <TrialBalanceAsOf /> : <TrialBalancePeriod />}
    </div>
  );
}

/** Sage's "General Ledger Trial Balance": Account ID, Account Description, Debit Amt, Credit Amt. */
function TrialBalanceAsOf() {
  const [asOf, setAsOf] = useState(today());
  const [zero, setZero] = useState(false);
  const [account, setAccount] = useState<Dict | null>(null);
  const { data, isLoading, error } = useBooks<any>(["tb-asof", asOf, zero], "/ledger/trial-balance", { as_of: asOf, include_zero: zero });
  const csv = data?.rows.map((r: Dict) => ({ "Account ID": r.code, "Account Description": r.name, "Debit Amt": Number(r.debit) || "", "Credit Amt": Number(r.credit) || "" }));
  return (
    <Section title="General Ledger Trial Balance" actions={<CsvButton filename={`gl-trial-balance-${asOf}.csv`} rows={csv} />}>
      <div className="mb-3 flex flex-wrap items-end gap-4">
        <DateRange single to={asOf} onChange={(_, t) => setAsOf(t)} />
        <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={zero} onChange={(e) => setZero(e.target.checked)} />include zero accounts</label>
        {data && <span className={`text-sm font-medium ${data.balanced ? "text-emerald-600" : "text-red-600"}`}>{data.balanced ? "✓ Balanced" : "✗ Out of balance"}</span>}
      </div>
      <p className="mb-2 text-xs text-muted-foreground">As of {fmtDate(asOf)}. Income and expense accounts show the year to date. Click an account for every line behind it.</p>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (
        <Table>
          <TableHeader><TableRow><TableHead>Account ID</TableHead><TableHead>Account Description</TableHead><TableHead className="text-right">Debit Amt</TableHead><TableHead className="text-right">Credit Amt</TableHead></TableRow></TableHeader>
          <TableBody>
            {data.rows.map((r: Dict) => (
              <TableRow key={r.code} className="cursor-pointer hover:bg-muted/50" onClick={() => setAccount({ id: r.account_id, code: r.code, name: r.name })}>
                <TableCell className="font-mono text-xs">{r.code}</TableCell><TableCell>{r.name}</TableCell>
                <TableCell className="text-right"><Amount value={r.debit} blankZero /></TableCell><TableCell className="text-right"><Amount value={r.credit} blankZero /></TableCell>
              </TableRow>
            ))}
            <TableRow className="font-semibold"><TableCell /><TableCell>Total:</TableCell>
              <TableCell className="text-right"><Amount value={data.total_debit} /></TableCell><TableCell className="text-right"><Amount value={data.total_credit} /></TableCell></TableRow>
          </TableBody>
        </Table>
      )}
      <AccountSheet account={account} from={`${asOf.slice(0, 4)}-01-01`} to={asOf} onClose={() => setAccount(null)} />
    </Section>
  );
}

function TrialBalancePeriod() {
  const [range, setRange] = useState({ from: yearStart(), to: today() });
  const [zero, setZero] = useState(false);
  const [account, setAccount] = useState<Dict | null>(null);
  const { data, isLoading, error } = useBooks<any>(["tb", range, zero], "/trial-balance", { ...range, include_zero: zero });
  return (
    <Section title="Working trial balance" actions={<CsvButton filename={`trial-balance-${range.to}.csv`} rows={data?.rows.map((r: Dict) => ({ code: r.code, name: r.name, type: r.account_type, opening: r.opening, debit: r.period_debit, credit: r.period_credit, closing_debit: r.closing_debit, closing_credit: r.closing_credit }))} />}>
      <div className="mb-3 flex flex-wrap items-end gap-4">
        <DateRange from={range.from} to={range.to} onChange={(f, t) => setRange({ from: f ?? range.from, to: t })} />
        <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={zero} onChange={(e) => setZero(e.target.checked)} />include zero accounts</label>
        {data && <span className={`text-sm font-medium ${data.balanced ? "text-emerald-600" : "text-red-600"}`}>{data.balanced ? "✓ Balanced" : "✗ Out of balance"}</span>}
      </div>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (
        <Table>
          <TableHeader><TableRow><TableHead>Code</TableHead><TableHead>Account</TableHead><TableHead className="text-right">Opening</TableHead><TableHead className="text-right">Debit</TableHead><TableHead className="text-right">Credit</TableHead><TableHead className="text-right">Closing Dr</TableHead><TableHead className="text-right">Closing Cr</TableHead></TableRow></TableHeader>
          <TableBody>
            {data.rows.map((r: Dict) => (
              <TableRow key={r.code} className="cursor-pointer hover:bg-muted/50" onClick={() => setAccount({ id: r.account_id, code: r.code, name: r.name })}>
                <TableCell className="font-mono text-xs">{r.code}</TableCell><TableCell className="max-w-[260px] truncate">{r.name}</TableCell>
                <TableCell className="text-right"><Amount value={r.opening} blankZero /></TableCell>
                <TableCell className="text-right"><Amount value={r.period_debit} blankZero /></TableCell><TableCell className="text-right"><Amount value={r.period_credit} blankZero /></TableCell>
                <TableCell className="text-right"><Amount value={r.closing_debit} blankZero /></TableCell><TableCell className="text-right"><Amount value={r.closing_credit} blankZero /></TableCell>
              </TableRow>
            ))}
            <TableRow className="font-semibold"><TableCell colSpan={2}>Totals</TableCell><TableCell />
              <TableCell className="text-right"><Amount value={data.totals.period_debit} /></TableCell><TableCell className="text-right"><Amount value={data.totals.period_credit} /></TableCell>
              <TableCell className="text-right"><Amount value={data.totals.closing_debit} /></TableCell><TableCell className="text-right"><Amount value={data.totals.closing_credit} /></TableCell></TableRow>
          </TableBody>
        </Table>
      )}
      <AccountSheet account={account} from={range.from} to={range.to} onClose={() => setAccount(null)} />
    </Section>
  );
}

/** Sage's General Ledger: every account for the period with its beginning balance, debits,
 *  credits and ending balance; open an account (▸) for every transaction, month by month. */
function GeneralLedger({ onJournal }: { onJournal: (id: string) => void }) {
  void onJournal;
  const [sp, setSp] = useSearchParams();
  const [range, setRange] = useState({ from: sp.get("gl_from") ?? monthStart(), to: sp.get("gl_to") ?? today() });
  const [filter, setFilter] = useState("");
  const [zero, setZero] = useState(false);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const { data, isLoading, error } = useBooks<Dict>(["gl-summary", range, zero], "/ledger/gl-summary", { ...range, include_zero: zero });
  const { data: span } = useBooks<Dict>(["ledger-range"], "/ledger/range");
  const setR = (f: string | undefined, t: string) => {
    const r = { from: f ?? range.from, to: t };
    setRange(r);
    const p = new URLSearchParams(sp); p.set("gl_from", r.from); p.set("gl_to", r.to); setSp(p, { replace: true });
  };
  const rows: Dict[] = (data?.rows ?? []).filter((r: Dict) => !filter || `${r.code} ${r.name}`.toLowerCase().includes(filter.toLowerCase()));
  const summaryCsv = rows.map((r) => ({ "Account ID": r.code, "Account Description": r.name, "Beginning Balance": r.opening, "Debit Amt": r.debit, "Credit Amt": r.credit, "Ending Balance": r.closing }));
  return (
    <Section title="General Ledger" actions={<CsvButton filename={`general-ledger-summary-${range.from}-${range.to}.csv`} rows={summaryCsv} />}>
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <DateRange from={range.from} to={range.to} onChange={setR} />
        <div className="relative w-64"><Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input className="h-9 pl-8" placeholder="Find account (e.g. 10000, petty cash)" value={filter} onChange={(e) => setFilter(e.target.value)} /></div>
        <label className="flex items-center gap-1 pb-2 text-xs"><input type="checkbox" checked={zero} onChange={(e) => setZero(e.target.checked)} />include accounts with no activity</label>
        <Button size="sm" variant="ghost" onClick={() => setOpen({})}>Collapse all</Button>
      </div>
      {span?.history_start && <p className="mb-2 text-xs text-muted-foreground">
        The ledger goes back to {fmtDate(span.history_start)}. Click an account to list every entry in the period; click a reference to open the invoice, receipt or transaction behind it.</p>}
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (rows.length === 0 ? <Empty>No ledger activity in this period.</Empty> : (
        <Table>
          <TableHeader><TableRow><TableHead className="w-6" /><TableHead>Account ID</TableHead><TableHead>Account Description</TableHead>
            <TableHead className="text-right">Beginning Balance</TableHead><TableHead className="text-right">Debit Amt</TableHead><TableHead className="text-right">Credit Amt</TableHead>
            <TableHead className="text-right">Ending Balance</TableHead><TableHead className="text-right">Lines</TableHead></TableRow></TableHeader>
          <TableBody>
            {rows.map((r) => (
              <Fragment key={r.code}>
                <TableRow className="cursor-pointer hover:bg-muted/50" onClick={() => setOpen({ ...open, [r.code]: !open[r.code] })}>
                  <TableCell>{open[r.code] ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</TableCell>
                  <TableCell className="font-mono text-xs">{r.code}</TableCell><TableCell>{r.name}</TableCell>
                  <TableCell className="text-right"><Amount value={r.opening} /></TableCell>
                  <TableCell className="text-right"><Amount value={r.debit} blankZero /></TableCell><TableCell className="text-right"><Amount value={r.credit} blankZero /></TableCell>
                  <TableCell className="text-right"><Amount value={r.closing} bold /></TableCell>
                  <TableCell className="text-right text-xs text-muted-foreground">{Number(r.lines).toLocaleString()}</TableCell>
                </TableRow>
                {open[r.code] && (
                  <TableRow className="hover:bg-transparent"><TableCell colSpan={8} className="bg-muted/10 p-3">
                    <GlAccountDetail code={r.code} from={range.from} to={range.to} />
                  </TableCell></TableRow>
                )}
              </Fragment>
            ))}
            <TableRow className="font-semibold"><TableCell /><TableCell colSpan={3}>Totals</TableCell>
              <TableCell className="text-right"><Amount value={data.totals.debit} /></TableCell><TableCell className="text-right"><Amount value={data.totals.credit} /></TableCell><TableCell colSpan={2} /></TableRow>
          </TableBody>
        </Table>
      ))}
    </Section>
  );
}
