import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Plus, Trash2, Upload, Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { FilterBar } from "@/components/workspace/FilterBar";
import { BooksShell } from "@/components/books/BooksShell";
import { RecordView } from "@/components/books/lineage";
import {
  AccountPick, AccountSheet, act, Amount, BankSelect, CsvButton, DateRange, Empty, ErrorNote, JournalSheet, Loading, Section,
  StatusBadge, useBooks, useLines,
} from "@/components/books/kit";
import { books, BooksError, Dict, fmtDate, monthStart, naira, newIdemKey, today, yearStart } from "@/lib/books-api";

export default function BooksBanking() {
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState(params.get("tab") ?? "accounts");
  const open = (k: string, v: string | null) => { const p = new URLSearchParams(params); v ? p.set(k, v) : p.delete(k); setParams(p, { replace: true }); };
  return (
    <BooksShell title="Banking"
                actions={<>
                  <Button size="sm" onClick={() => open("new", "voucher")}><Plus className="mr-1 h-4 w-4" />Spend / receive money</Button>
                  <Button size="sm" variant="outline" onClick={() => open("new", "transfer")}>Transfer</Button>
                  <Button size="sm" variant="outline" onClick={() => open("new", "statement")}><Upload className="mr-1 h-4 w-4" />Import statement</Button>
                </>}>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="accounts">Accounts</TabsTrigger>
          <TabsTrigger value="vouchers">Vouchers</TabsTrigger>
          <TabsTrigger value="reconcile">Reconciliation</TabsTrigger>
        </TabsList>
        <TabsContent value="accounts"><Accounts onNew={() => open("new", "account")} /></TabsContent>
        <TabsContent value="vouchers"><VoucherList onOpen={(id) => open("voucher", id)} /></TabsContent>
        <TabsContent value="reconcile"><StatementList onOpen={(id) => open("statement", id)} /></TabsContent>
      </Tabs>
      <VoucherForm open={params.get("new") === "voucher"} onClose={(id) => { open("new", null); if (id) open("voucher", id); }} />
      <TransferForm open={params.get("new") === "transfer"} onClose={() => open("new", null)} />
      <StatementImport open={params.get("new") === "statement"} onClose={(id) => { open("new", null); if (id) { setTab("reconcile"); open("statement", id); } }} />
      <AccountForm open={params.get("new") === "account"} onClose={() => open("new", null)} />
      <VoucherDetail id={params.get("voucher")} onClose={() => open("voucher", null)} />
      <Reconcile id={params.get("statement")} onClose={() => open("statement", null)} />
    </BooksShell>
  );
}

function Accounts({ onNew }: { onNew: () => void }) {
  const { data, isLoading, error } = useBooks<Dict[]>(["banks"], "/banking/accounts");
  const [account, setAccount] = useState<Dict | null>(null);
  const [showZero, setShowZero] = useState(false);
  const rows = (data ?? []).filter((b) => showZero || Number(b.book_balance) !== 0);
  const total = rows.reduce((s, b) => s + Number(b.book_balance), 0);
  return (
    <Section title="Bank & cash accounts" actions={<>
      <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={showZero} onChange={(e) => setShowZero(e.target.checked)} />show zero balances</label>
      <Button size="sm" variant="outline" onClick={onNew}>Add account</Button></>}>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (
        <Table>
          <TableHeader><TableRow><TableHead>Account</TableHead><TableHead>GL</TableHead><TableHead>Kind</TableHead><TableHead className="text-right">Book balance</TableHead><TableHead className="text-right">Uncleared entries</TableHead><TableHead>Last reconciled</TableHead></TableRow></TableHeader>
          <TableBody>
            {rows.map((b) => (
              <TableRow key={b.id} className="cursor-pointer hover:bg-muted/50" onClick={() => setAccount({ id: b.gl_account_id, code: b.gl_code, name: b.name })}>
                <TableCell><div className="font-medium">{b.name}</div><div className="text-xs text-muted-foreground">{[b.bank_name, b.account_number].filter(Boolean).join(" · ")}</div></TableCell>
                <TableCell className="text-xs">{b.gl_code}</TableCell><TableCell className="text-xs">{b.kind.toLowerCase().replace("_", " ")}</TableCell>
                <TableCell className="text-right"><Amount value={b.book_balance} /></TableCell><TableCell className="text-right">{b.uncleared_count}</TableCell>
                <TableCell>{b.last_reconciled ? fmtDate(b.last_reconciled) : <span className="text-muted-foreground">never</span>}</TableCell>
              </TableRow>
            ))}
            <TableRow className="font-semibold"><TableCell colSpan={3}>Total</TableCell><TableCell className="text-right"><Amount value={total} /></TableCell><TableCell colSpan={2} /></TableRow>
          </TableBody>
        </Table>
      )}
      <AccountSheet account={account} from={yearStart()} to={today()} onClose={() => setAccount(null)} />
    </Section>
  );
}

function AccountForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [gl, setGl] = useState<Dict | null>(null);
  const [f, setF] = useState({ name: "", kind: "BANK", bank_name: "", account_number: "" });
  const submit = async () => {
    if (await act(() => books.post("/banking/accounts", { ...f, gl_account_id: gl?.id, name: f.name || undefined }), "Account added")) {
      qc.invalidateQueries({ queryKey: ["books"] }); onClose();
    }
  };
  return (
    <DetailSheet open={open} onOpenChange={(o) => !o && onClose()} title="Add bank / cash account"
                 description="Links a cash-type GL account so it can be used for payments, receipts and reconciliation."
                 footer={<Button disabled={!gl} onClick={submit}>Add account</Button>}>
      <div className="space-y-3">
        <AccountPick label="GL account (cash type)" value={gl} onChange={setGl} accountType="ASSET" />
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1"><Label className="text-xs">Display name</Label><Input value={f.name} placeholder={gl?.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></div>
          <div className="space-y-1"><Label className="text-xs">Kind</Label><select className="h-9 w-full rounded-md border bg-background px-2 text-sm" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
            <option value="BANK">Bank</option><option value="CASH">Cash</option><option value="PETTY_CASH">Petty cash</option></select></div>
          <div className="space-y-1"><Label className="text-xs">Bank</Label><Input value={f.bank_name} onChange={(e) => setF({ ...f, bank_name: e.target.value })} /></div>
          <div className="space-y-1"><Label className="text-xs">Account number</Label><Input value={f.account_number} onChange={(e) => setF({ ...f, account_number: e.target.value })} /></div>
        </div>
      </div>
    </DetailSheet>
  );
}

function VoucherList({ onOpen }: { onOpen: (id: string) => void }) {
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  const [bank, setBank] = useState("");
  const [range, setRange] = useState({ from: monthStart(), to: today() });
  const { data, isLoading, error } = useBooks<any>(["vouchers", search, kind, bank, range], "/banking/vouchers",
    { search, kind: kind || undefined, bank_account_id: bank || undefined, from: range.from, to: range.to, limit: 300 });
  return (
    <Section title={`Vouchers${data ? ` (${data.total})` : ""}`} actions={<CsvButton filename="vouchers.csv" rows={data?.items} />}>
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <div className="flex-1"><FilterBar search={{ value: search, onChange: setSearch, placeholder: "Number, payee, reference, description" }}
          selects={[{ label: "Kind", value: kind, onChange: setKind, options: [{ value: "SPEND", label: "Spend" }, { value: "RECEIVE", label: "Receive" }, { value: "TRANSFER", label: "Transfer" }] }]} /></div>
        <div className="w-60"><BankSelect label="Account" value={bank} onChange={setBank} /></div>
        <DateRange from={range.from} to={range.to} onChange={(f, t) => setRange({ from: f ?? range.from, to: t })} />
      </div>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (data.items.length === 0 ? <Empty>No vouchers in this period.</Empty> : (
        <Table>
          <TableHeader><TableRow><TableHead>Voucher</TableHead><TableHead>Date</TableHead><TableHead>Kind</TableHead><TableHead>Account</TableHead><TableHead>Payee / description</TableHead><TableHead className="text-right">Amount</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
          <TableBody>{data.items.map((v: Dict) => (
            <TableRow key={v.id} className="cursor-pointer hover:bg-muted/50" onClick={() => onOpen(v.id)}>
              <TableCell className="font-mono text-xs">{v.voucher_number}</TableCell><TableCell className="whitespace-nowrap">{fmtDate(v.voucher_date)}</TableCell>
              <TableCell className="text-xs">{v.kind.toLowerCase()}</TableCell>
              <TableCell className="text-xs">{v.bank_account_name}{v.to_bank_account_name ? ` → ${v.to_bank_account_name}` : ""}</TableCell>
              <TableCell className="max-w-[240px] truncate text-xs">{v.payee ?? v.description}{v.reference ? ` · ${v.reference}` : ""}</TableCell>
              <TableCell className="text-right"><Amount value={v.kind === "SPEND" ? -Number(v.amount) : v.amount} /></TableCell>
              <TableCell><StatusBadge status={v.status} /></TableCell>
            </TableRow>
          ))}</TableBody>
        </Table>
      ))}
    </Section>
  );
}

type VLine = { account: Dict | null; description: string; amount: string };
const blankV = (): VLine => ({ account: null, description: "", amount: "" });

function VoucherForm({ open, onClose, preset }: { open: boolean; onClose: (id?: string) => void; preset?: Dict }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ kind: "SPEND", voucher_date: today(), bank_account_id: "", payee: "", reference: "", description: "" });
  const [busy, setBusy] = useState(false);
  const [idem] = useState(newIdemKey);
  const L = useLines<VLine>(blankV);
  useEffect(() => {
    if (open && preset) { setF((x) => ({ ...x, ...preset })); if (preset.amount) L.setLines([{ account: null, description: preset.description ?? "", amount: String(preset.amount) }]); }
    if (!open) { L.reset(); setF({ kind: "SPEND", voucher_date: today(), bank_account_id: "", payee: "", reference: "", description: "" }); }
  }, [open]);
  const total = L.lines.reduce((s, l) => s + Number(l.amount || 0), 0);
  const submit = async () => {
    setBusy(true);
    const v = await act(() => books.post("/banking/vouchers", { ...f, lines: L.lines.filter((l) => l.account).map((l) => ({ account_id: l.account?.id, description: l.description || undefined, amount: l.amount })) }, idem), "Voucher posted");
    setBusy(false);
    if (v) { qc.invalidateQueries({ queryKey: ["books"] }); onClose(v.id); }
  };
  return (
    <DetailSheet open={open} onOpenChange={(o) => !o && onClose()} title={f.kind === "SPEND" ? "Spend money (payment voucher)" : "Receive money"}
                 description="For money that is not a customer receipt or supplier payment: bank charges, salaries, rent, petty cash, loans, interest…"
                 footer={<div className="flex w-full items-center justify-between"><span className="text-sm">Total <strong>{naira(total)}</strong></span>
                   <Button disabled={busy || !f.bank_account_id || total <= 0} onClick={submit}>{busy ? "Posting…" : "Post voucher"}</Button></div>}>
      <div className="space-y-3">
        <div className="flex gap-2">{["SPEND", "RECEIVE"].map((k) => <Button key={k} size="sm" variant={f.kind === k ? "default" : "outline"} onClick={() => setF({ ...f, kind: k })}>{k === "SPEND" ? "Money out" : "Money in"}</Button>)}</div>
        <div className="grid grid-cols-2 gap-3">
          <BankSelect value={f.bank_account_id} onChange={(v) => setF({ ...f, bank_account_id: v })} label={f.kind === "SPEND" ? "Paid from" : "Paid into"} />
          <div className="space-y-1"><Label className="text-xs">Date</Label><Input type="date" value={f.voucher_date} onChange={(e) => setF({ ...f, voucher_date: e.target.value })} /></div>
          <div className="space-y-1"><Label className="text-xs">{f.kind === "SPEND" ? "Payee" : "Received from"}</Label><Input value={f.payee} onChange={(e) => setF({ ...f, payee: e.target.value })} /></div>
          <div className="space-y-1"><Label className="text-xs">Cheque / reference</Label><Input value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} /></div>
        </div>
        <div className="space-y-1"><Label className="text-xs">Description</Label><Input value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></div>
        <div className="text-xs font-semibold uppercase text-muted-foreground">{f.kind === "SPEND" ? "What was it for?" : "What was it for?"}</div>
        {L.lines.map((l, i) => (
          <div key={i} className="grid grid-cols-[1fr_1fr_120px_32px] items-end gap-2">
            <AccountPick value={l.account} onChange={(a) => L.update(i, { account: a })} />
            <Input className="h-9" placeholder="Line description" value={l.description} onChange={(e) => L.update(i, { description: e.target.value })} />
            <Input className="h-9" type="number" placeholder="Amount" value={l.amount} onChange={(e) => L.update(i, { amount: e.target.value })} />
            <Button size="icon" variant="ghost" onClick={() => L.remove(i)}><Trash2 className="h-4 w-4" /></Button>
          </div>
        ))}
        <Button size="sm" variant="outline" onClick={L.add}><Plus className="mr-1 h-4 w-4" />Add line</Button>
      </div>
    </DetailSheet>
  );
}

function TransferForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ voucher_date: today(), bank_account_id: "", to_bank_account_id: "", amount: "", reference: "", description: "" });
  const [idem] = useState(newIdemKey);
  const submit = async () => {
    if (await act(() => books.post("/banking/vouchers", { ...f, kind: "TRANSFER" }, idem), "Transfer posted")) { qc.invalidateQueries({ queryKey: ["books"] }); onClose(); }
  };
  return (
    <DetailSheet open={open} onOpenChange={(o) => !o && onClose()} title="Transfer between accounts"
                 footer={<Button disabled={!f.bank_account_id || !f.to_bank_account_id || Number(f.amount) <= 0} onClick={submit}>Post transfer</Button>}>
      <div className="space-y-3">
        <BankSelect label="From" value={f.bank_account_id} onChange={(v) => setF({ ...f, bank_account_id: v })} />
        <BankSelect label="To" value={f.to_bank_account_id} onChange={(v) => setF({ ...f, to_bank_account_id: v })} />
        <div className="grid grid-cols-3 gap-3">
          <div className="space-y-1"><Label className="text-xs">Amount</Label><Input type="number" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></div>
          <div className="space-y-1"><Label className="text-xs">Date</Label><Input type="date" value={f.voucher_date} onChange={(e) => setF({ ...f, voucher_date: e.target.value })} /></div>
          <div className="space-y-1"><Label className="text-xs">Reference</Label><Input value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} /></div>
        </div>
        <div className="space-y-1"><Label className="text-xs">Description</Label><Input value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></div>
      </div>
    </DetailSheet>
  );
}

function VoucherDetail({ id, onClose }: { id: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const { data: v, refetch } = useBooks<Dict>(["voucher", id], `/banking/vouchers/${id}`, undefined, !!id);
  const [ver, setVer] = useState(0);
  const voidIt = async () => {
    const reason = window.prompt("Why is this voucher being voided?");
    if (reason && (await act(() => books.post(`/banking/vouchers/${id}/void`, { reason }), "Voided"))) { refetch(); setVer((x) => x + 1); qc.invalidateQueries({ queryKey: ["books"] }); }
  };
  return (
    <DetailSheet open={!!id} onOpenChange={(o) => !o && onClose()} title={v ? `Voucher ${v.voucher_number}` : ""} description={v?.payee ?? v?.description}
                 footer={v?.status === "POSTED" ? <Button size="sm" variant="destructive" onClick={voidIt}>Void</Button> : undefined}>
      {id && <RecordView key={`${id}:${ver}`} t={{ type: "voucher", id }} />}
    </DetailSheet>
  );
}

// ---------------------------------------------------------------------------
// Reconciliation
// ---------------------------------------------------------------------------

function StatementList({ onOpen }: { onOpen: (id: string) => void }) {
  const { data, isLoading, error } = useBooks<Dict[]>(["statements"], "/banking/statements");
  return (
    <Section title="Bank statements">
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (data.length === 0 ? <Empty>Import a bank statement CSV (Date, Description, Reference, and Amount or Debit/Credit) to reconcile.</Empty> : (
        <Table>
          <TableHeader><TableRow><TableHead>Account</TableHead><TableHead>Statement date</TableHead><TableHead className="text-right">Closing balance</TableHead><TableHead className="text-right">Matched</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
          <TableBody>{data.map((s) => (
            <TableRow key={s.id} className="cursor-pointer hover:bg-muted/50" onClick={() => onOpen(s.id)}>
              <TableCell>{s.bank_account_name}</TableCell><TableCell className="whitespace-nowrap">{fmtDate(s.statement_date)}</TableCell>
              <TableCell className="text-right"><Amount value={s.closing_balance} /></TableCell><TableCell className="text-right">{s.matched} / {s.lines}</TableCell>
              <TableCell><StatusBadge status={s.status} /></TableCell>
            </TableRow>
          ))}</TableBody>
        </Table>
      ))}
    </Section>
  );
}

function StatementImport({ open, onClose }: { open: boolean; onClose: (id?: string) => void }) {
  const [f, setF] = useState({ bank_account_id: "", statement_date: today(), closing_balance: "", opening_balance: "" });
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const submit = async () => {
    if (!file) return;
    const fd = new FormData();
    Object.entries(f).forEach(([k, v]) => v && fd.append(k, v));
    fd.append("file", file);
    setBusy(true);
    const st = await act(() => books.upload("/banking/statements", fd), "Statement imported");
    setBusy(false);
    if (st) { qc.invalidateQueries({ queryKey: ["books"] }); onClose(st.id); }
  };
  return (
    <DetailSheet open={open} onOpenChange={(o) => !o && onClose()} title="Import bank statement"
                 description="CSV exported from the bank. Needs a Date column and either Amount (signed) or Debit/Credit columns."
                 footer={<Button disabled={busy || !file || !f.bank_account_id || f.closing_balance === ""} onClick={submit}>{busy ? "Importing…" : "Import"}</Button>}>
      <div className="space-y-3">
        <BankSelect value={f.bank_account_id} onChange={(v) => setF({ ...f, bank_account_id: v })} kinds={["BANK"]} />
        <div className="grid grid-cols-3 gap-3">
          <div className="space-y-1"><Label className="text-xs">Statement date</Label><Input type="date" value={f.statement_date} onChange={(e) => setF({ ...f, statement_date: e.target.value })} /></div>
          <div className="space-y-1"><Label className="text-xs">Opening balance</Label><Input type="number" value={f.opening_balance} onChange={(e) => setF({ ...f, opening_balance: e.target.value })} /></div>
          <div className="space-y-1"><Label className="text-xs">Closing balance</Label><Input type="number" value={f.closing_balance} onChange={(e) => setF({ ...f, closing_balance: e.target.value })} /></div>
        </div>
        <Input type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </div>
    </DetailSheet>
  );
}

function Reconcile({ id, onClose }: { id: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const { data: st, isLoading, error, refetch } = useBooks<Dict>(["statement", id], `/banking/statements/${id}`, undefined, !!id);
  const [pick, setPick] = useState<Record<string, string>>({});
  const [record, setRecord] = useState<Dict | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const done = () => { refetch(); qc.invalidateQueries({ queryKey: ["books"] }); };
  const book: Dict[] = st?.unmatched_book ?? [];
  const candidates = (amount: any) => book.filter((b) => Number(b.amount) === Number(amount));
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    (st?.lines ?? []).forEach((l: Dict) => { c[l.match_status] = (c[l.match_status] ?? 0) + 1; });
    return c;
  }, [st]);
  const match = async (line: Dict, status: string, journal_line_id?: string) => {
    const note = status === "MATCHED" ? undefined : window.prompt(status === "IGNORED" ? "Why ignore this line?" : "Describe the exception") ?? undefined;
    if (await act(() => books.post(`/banking/statement-lines/${line.id}/match`, { journal_line_id, status, note }))) done();
  };
  const complete = async () => {
    setProblem(null);
    try { await books.post(`/banking/statements/${id}/complete`, {}); done(); }
    catch (e) { setProblem((e as BooksError).message); }
  };
  const reconciled = st?.status === "RECONCILED";
  return (
    <>
      <DetailSheet open={!!id} onOpenChange={(o) => !o && onClose()} title={st ? `Reconcile ${st.bank_account_name}` : ""}
                   description={st ? `Statement to ${fmtDate(st.statement_date)} · closing ${naira(st.closing_balance)}` : ""}
                   footer={st && !reconciled ? <div className="flex gap-2">
                     <Button variant="outline" onClick={async () => { const r = await act(() => books.post(`/banking/statements/${id}/auto-match`, {}), "Auto-match done"); if (r) done(); }}><Wand2 className="mr-1 h-4 w-4" />Auto-match</Button>
                     <Button onClick={complete}><CheckCircle2 className="mr-1 h-4 w-4" />Complete reconciliation</Button></div> : undefined}>
        {isLoading && <Loading />}<ErrorNote error={error} />
        {st && (
          <div className="space-y-4 text-sm">
            <div className="flex flex-wrap items-center gap-3"><StatusBadge status={st.status} />
              <span className="text-xs text-muted-foreground">{counts.MATCHED ?? 0} matched · {counts.UNMATCHED ?? 0} unmatched · {counts.IGNORED ?? 0} ignored · {counts.EXCEPTION ?? 0} exceptions</span></div>
            {problem && <div className="rounded-lg border border-amber-400 bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-500/10 dark:text-amber-200">{problem}</div>}
            <Table>
              <TableHeader><TableRow><TableHead>Date</TableHead><TableHead>Statement line</TableHead><TableHead className="text-right">Amount</TableHead><TableHead>Book entry</TableHead></TableRow></TableHeader>
              <TableBody>{st.lines.map((l: Dict) => {
                const c = candidates(l.amount);
                return (
                  <TableRow key={l.id}>
                    <TableCell className="whitespace-nowrap">{fmtDate(l.line_date)}</TableCell>
                    <TableCell className="max-w-[200px]"><div className="truncate text-xs">{l.description}</div><div className="font-mono text-[11px] text-muted-foreground">{l.reference}</div></TableCell>
                    <TableCell className="text-right"><Amount value={l.amount} /></TableCell>
                    <TableCell className="min-w-[220px]">
                      {l.match_status === "MATCHED" ? (
                        <div className="text-xs"><StatusBadge status="MATCHED" /> {l.journal_number} · {fmtDate(l.book_date)}
                          {!reconciled && <button className="ml-1 text-muted-foreground underline" onClick={() => match(l, "UNMATCHED")}>undo</button>}</div>
                      ) : l.match_status !== "UNMATCHED" ? (
                        <div className="text-xs"><StatusBadge status={l.match_status === "IGNORED" ? "CLOSED" : "FAILED"} /> {l.match_status.toLowerCase()} {l.note && `— ${l.note}`}
                          {!reconciled && <button className="ml-1 text-muted-foreground underline" onClick={() => match(l, "UNMATCHED")}>undo</button>}</div>
                      ) : !reconciled && (
                        <div className="flex flex-wrap items-center gap-1">
                          <select className="h-8 max-w-[180px] rounded-md border bg-background px-1 text-xs" value={pick[l.id] ?? ""} onChange={(e) => setPick({ ...pick, [l.id]: e.target.value })}>
                            <option value="">{c.length ? `${c.length} same-amount entr${c.length > 1 ? "ies" : "y"}…` : "choose book entry…"}</option>
                            {(c.length ? c : book).slice(0, 80).map((b) => <option key={b.line_id} value={b.line_id}>{fmtDate(b.journal_date)} {b.source_ref ?? b.journal_number} {naira(b.amount)}</option>)}
                          </select>
                          <Button size="sm" className="h-8" disabled={!pick[l.id]} onClick={() => match(l, "MATCHED", pick[l.id])}>Match</Button>
                          <Button size="sm" variant="ghost" className="h-8 text-xs" onClick={() => setRecord({ statement_line: l, bank_account_id: st.bank_account_id })}>Record</Button>
                          <Button size="sm" variant="ghost" className="h-8 text-xs" onClick={() => match(l, "IGNORED")}>Ignore</Button>
                        </div>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}</TableBody>
            </Table>
            {!reconciled && book.length > 0 && (
              <div>
                <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">In the books, not on this statement ({book.length})</div>
                <Table><TableBody>{book.slice(0, 200).map((b) => (
                  <TableRow key={b.line_id}><TableCell className="whitespace-nowrap">{fmtDate(b.journal_date)}</TableCell><TableCell className="max-w-[260px] truncate text-xs">{b.source_ref ?? b.journal_number} · {b.description}</TableCell><TableCell className="text-right"><Amount value={b.amount} /></TableCell></TableRow>
                ))}</TableBody></Table>
              </div>
            )}
          </div>
        )}
      </DetailSheet>
      <VoucherForm open={!!record} preset={record ? { kind: Number(record.statement_line.amount) < 0 ? "SPEND" : "RECEIVE", bank_account_id: record.bank_account_id,
        voucher_date: record.statement_line.line_date, reference: record.statement_line.reference ?? "", description: record.statement_line.description ?? "",
        amount: Math.abs(Number(record.statement_line.amount)) } : undefined}
        onClose={(vid) => { setRecord(null); if (vid) act(() => books.post(`/banking/statements/${id}/auto-match`, {})).then(done); }} />
    </>
  );
}
