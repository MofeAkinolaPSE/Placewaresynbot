import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Plus, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { BooksShell } from "@/components/books/BooksShell";
import { AccountPick, AccountSheet, act, Amount, CsvButton, Empty, ErrorNote, Loading, Section, StatusBadge, useBooks } from "@/components/books/kit";
import { books, Dict, fmtDate, today, yearStart } from "@/lib/books-api";
import { askConfirm, askText } from "@/lib/ask";

const SUBTYPES: [string, string][] = [
  ["CASH", "ASSET"], ["RECEIVABLE", "ASSET"], ["INVENTORY", "ASSET"], ["OTHER_CURRENT_ASSET", "ASSET"], ["FIXED_ASSET", "ASSET"],
  ["ACCUMULATED_DEPRECIATION", "ASSET"], ["OTHER_ASSET", "ASSET"], ["PAYABLE", "LIABILITY"], ["OTHER_CURRENT_LIABILITY", "LIABILITY"],
  ["LONG_TERM_LIABILITY", "LIABILITY"], ["EQUITY", "EQUITY"], ["RETAINED_EARNINGS", "EQUITY"], ["EQUITY_CLOSING", "EQUITY"],
  ["SALES", "REVENUE"], ["OTHER_INCOME", "REVENUE"], ["COST_OF_SALES", "EXPENSE"], ["OPERATING_EXPENSE", "EXPENSE"], ["OTHER_EXPENSE", "EXPENSE"],
];
const label = (s?: string) => (s ?? "").replace(/_/g, " ").toLowerCase();

export default function BooksSetup() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "accounts";
  return (
    <BooksShell title="Setup">
      <Tabs value={tab} onValueChange={(v) => { const p = new URLSearchParams(params); p.set("tab", v); setParams(p, { replace: true }); }}>
        <TabsList className="flex-wrap">
          <TabsTrigger value="accounts">Chart of accounts</TabsTrigger>
          <TabsTrigger value="rules">Posting rules</TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
          <TabsTrigger value="budgets">Budgets</TabsTrigger>
          <TabsTrigger value="migration">Sage migration</TabsTrigger>
        </TabsList>
        <TabsContent value="accounts"><ChartOfAccounts /></TabsContent>
        <TabsContent value="rules"><PostingRules /></TabsContent>
        <TabsContent value="settings"><Settings /></TabsContent>
        <TabsContent value="budgets"><Budgets /></TabsContent>
        <TabsContent value="migration"><Migration /></TabsContent>
      </Tabs>
    </BooksShell>
  );
}

// ---------------------------------------------------------------------------
// Chart of accounts
// ---------------------------------------------------------------------------

function ChartOfAccounts() {
  const [search, setSearch] = useState("");
  const [type, setType] = useState("");
  const [inactive, setInactive] = useState(false);
  const [edit, setEdit] = useState<Dict | null>(null);
  const [ledger, setLedger] = useState<Dict | null>(null);
  const [asOf, setAsOf] = useState(today());
  const [used, setUsed] = useState("");
  // balances and activity over the whole ledger - Sage's years and ACE Books
  const { data, isLoading, error } = useBooks<Dict[]>(["coa", type, inactive, asOf], "/accounts",
    { account_type: type || undefined, include_inactive: inactive, as_of: asOf, history: true });
  const rows = (data ?? []).filter((a) => (!search || `${a.code} ${a.name}`.toLowerCase().includes(search.toLowerCase()))
    && (used === "" || (used === "used" ? a.entries > 0 : a.entries === 0)));
  return (
    <Section title={`Chart of accounts (${rows.length})`} actions={<>
      <CsvButton filename="chart-of-accounts.csv" rows={rows.map((a) => ({ code: a.code, name: a.name, type: a.account_type, subtype: a.subtype, status: a.status, sage_code: a.legacy_code, balance: a.balance }))} />
      <Button size="sm" onClick={() => setEdit({})}><Plus className="mr-1 h-4 w-4" />New account</Button></>}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Input className="h-9 max-w-xs" placeholder="Code or name" value={search} onChange={(e) => setSearch(e.target.value)} />
        <select className="h-9 rounded-md border bg-background px-2 text-sm" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">All types</option>{["ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"].map((t) => <option key={t} value={t}>{t.toLowerCase()}</option>)}
        </select>
        <select className="h-9 rounded-md border bg-background px-2 text-sm" value={used} onChange={(e) => setUsed(e.target.value)}>
          <option value="">Used and unused</option><option value="used">With entries</option><option value="unused">Never used</option></select>
        <label className="flex items-center gap-1 text-xs">As at <Input type="date" className="h-9 w-40" value={asOf} onChange={(e) => setAsOf(e.target.value || today())} /></label>
        <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={inactive} onChange={(e) => setInactive(e.target.checked)} />show inactive</label>
      </div>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (
        <Table>
          <TableHeader><TableRow><TableHead>Code</TableHead><TableHead>Name</TableHead><TableHead>Type</TableHead><TableHead>Subtype</TableHead>
            <TableHead className="text-right">Balance at {fmtDate(asOf)}</TableHead><TableHead className="text-right">Entries</TableHead><TableHead>First · last entry</TableHead><TableHead /></TableRow></TableHeader>
          <TableBody>{rows.map((a) => (
            <TableRow key={a.id} className={a.status !== "ACTIVE" ? "opacity-60" : ""}>
              <TableCell className="font-mono text-xs">{a.code}</TableCell>
              <TableCell><div>{a.name}</div><div className="text-[11px] text-muted-foreground">{[a.is_control && "control", !a.is_postable && "header", a.status !== "ACTIVE" && "inactive"].filter(Boolean).join(" · ")}</div></TableCell>
              <TableCell className="text-xs">{label(a.account_type)}</TableCell><TableCell className="text-xs">{label(a.subtype)}</TableCell>
              <TableCell className="text-right"><button className="hover:underline" title="Open every ledger line behind this figure" onClick={() => setLedger({ id: a.id, code: a.code, name: a.name })}>
                {Number(a.balance_as_of) ? <Amount value={a.balance_as_of} /> : <span className="text-muted-foreground">0.00</span>}</button>
                {a.balance_basis === "year to date" && <div className="text-[10px] text-muted-foreground">year to date</div>}</TableCell>
              <TableCell className="text-right text-xs">{a.entries ? a.entries.toLocaleString() : <span className="text-muted-foreground">none</span>}</TableCell>
              <TableCell className="whitespace-nowrap text-xs">{a.first_entry ? `${fmtDate(a.first_entry)} · ${fmtDate(a.last_entry)}` : ""}</TableCell>
              <TableCell><Button size="sm" variant="ghost" onClick={() => setEdit(a)}>Edit</Button></TableCell>
            </TableRow>
          ))}</TableBody>
        </Table>
      )}
      <AccountEditor account={edit} onClose={() => setEdit(null)} />
      <AccountSheet account={ledger} from={`${asOf.slice(0, 4)}-01-01`} to={asOf} onClose={() => setLedger(null)} />
    </Section>
  );
}

function AccountEditor({ account, onClose }: { account: Dict | null; onClose: () => void }) {
  const qc = useQueryClient();
  const isNew = account && !account.id;
  const [f, setF] = useState<Dict>({});
  useEffect(() => { if (account) setF({ code: account.code ?? "", name: account.name ?? "", subtype: account.subtype ?? "OPERATING_EXPENSE", description: account.description ?? "", is_control: !!account.is_control, is_postable: account.is_postable ?? true }); }, [account]);
  const done = () => { qc.invalidateQueries({ queryKey: ["books"] }); onClose(); };
  const save = async () => {
    const r = isNew ? await act(() => books.post("/accounts", f), "Account created")
      : await act(() => books.patch(`/accounts/${account!.id}`, { name: f.name, subtype: f.subtype, description: f.description, is_control: f.is_control, is_postable: f.is_postable }), "Account updated");
    if (r) done();
  };
  const toggle = async () => {
    if (account!.status === "ACTIVE") {
      const reason = await askText("Why deactivate this account? (it will no longer accept postings)");
      if (reason !== null && (await act(() => books.post(`/accounts/${account!.id}/deactivate`, { reason }), "Account deactivated"))) done();
    } else if (await act(() => books.post(`/accounts/${account!.id}/activate`, {}), "Account activated")) done();
  };
  return (
    <DetailSheet open={!!account} onOpenChange={(o) => !o && onClose()} title={isNew ? "New account" : `Edit ${account?.code}`}
                 description="The subtype decides where the account appears on the statements and in the cash flow."
                 footer={<div className="flex gap-2">{!isNew && <Button variant="outline" onClick={toggle}>{account?.status === "ACTIVE" ? "Deactivate" : "Activate"}</Button>}
                   <Button disabled={!f.code || !f.name} onClick={save}>Save</Button></div>}>
      <div className="space-y-3">
        <div className="grid grid-cols-[140px_1fr] gap-3">
          <div className="space-y-1"><Label className="text-xs">Code</Label><Input value={f.code ?? ""} disabled={!isNew} onChange={(e) => setF({ ...f, code: e.target.value })} /></div>
          <div className="space-y-1"><Label className="text-xs">Name</Label><Input value={f.name ?? ""} onChange={(e) => setF({ ...f, name: e.target.value })} /></div>
        </div>
        <div className="space-y-1"><Label className="text-xs">Subtype</Label>
          <select className="h-9 w-full rounded-md border bg-background px-2 text-sm" value={f.subtype} onChange={(e) => setF({ ...f, subtype: e.target.value })}>
            {SUBTYPES.map(([s, t]) => <option key={s} value={s}>{label(t)} — {label(s)}</option>)}
          </select></div>
        <div className="space-y-1"><Label className="text-xs">Description</Label><Input value={f.description ?? ""} onChange={(e) => setF({ ...f, description: e.target.value })} /></div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!f.is_control} onChange={(e) => setF({ ...f, is_control: e.target.checked })} />Control account (fed only by its subledger; manual journals need special permission)</label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!f.is_postable} onChange={(e) => setF({ ...f, is_postable: e.target.checked })} />Accepts postings (untick for a header/grouping account)</label>
        {account?.legacy_code && <p className="text-xs text-muted-foreground">Sage account {account.legacy_code} ({account.legacy_type})</p>}
      </div>
    </DetailSheet>
  );
}

// ---------------------------------------------------------------------------
// Posting rules & settings
// ---------------------------------------------------------------------------

function PostingRules() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useBooks<Dict[]>(["mappings"], "/mappings");
  const [editing, setEditing] = useState<string | null>(null);
  const set = async (key: string, acc: Dict | null) => {
    if (!acc) return;
    if (await act(() => books.put(`/mappings/${key}`, { account_id: acc.id }), `${label(key)} → ${acc.code}`)) { setEditing(null); qc.invalidateQueries({ queryKey: ["books"] }); }
  };
  return (
    <Section title="Posting rules">
      <p className="mb-3 text-sm text-muted-foreground">Where each kind of transaction lands in the ledger. Per-product sales, stock and cost-of-sales accounts come from the product (synced from Sage); these are the defaults and control accounts.</p>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (
        <Table>
          <TableHeader><TableRow><TableHead>Rule</TableHead><TableHead>Account</TableHead><TableHead /></TableRow></TableHeader>
          <TableBody>{data.map((m) => (
            <TableRow key={m.mapping_key}>
              <TableCell><div className="font-mono text-xs">{m.mapping_key}</div><div className="text-xs text-muted-foreground">{m.description}</div></TableCell>
              <TableCell className="min-w-[280px]">{editing === m.mapping_key ? <AccountPick value={null} onChange={(a) => set(m.mapping_key, a)} />
                : m.account_id ? <span>{m.code} · {m.name}</span> : <span className="flex items-center gap-1 text-amber-600"><AlertTriangle className="h-4 w-4" />not mapped</span>}</TableCell>
              <TableCell><Button size="sm" variant="ghost" onClick={() => setEditing(editing === m.mapping_key ? null : m.mapping_key)}>{editing === m.mapping_key ? "Cancel" : "Change"}</Button></TableCell>
            </TableRow>
          ))}</TableBody>
        </Table>
      )}
    </Section>
  );
}

function Settings() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useBooks<Dict>(["settings"], "/settings");
  const [f, setF] = useState<Dict | null>(null);
  useEffect(() => { if (data) setF({ ...data, aging_buckets: (data.aging_buckets ?? []).join(", ") }); }, [data]);
  const save = async () => {
    if (!f) return;
    const body = { journal_approval_required: f.journal_approval_required, allow_self_approval: f.allow_self_approval, credit_limit_mode: f.credit_limit_mode,
      negative_stock_policy: f.negative_stock_policy, cutover_date: f.cutover_date || null, auto_post_frontdesk: f.auto_post_frontdesk,
      default_customer_code: f.default_customer_code || null, aging_buckets: String(f.aging_buckets).split(/[\s,]+/).filter(Boolean).map(Number) };
    if (await act(() => books.put("/settings", body), "Settings saved")) qc.invalidateQueries({ queryKey: ["books"] });
  };
  const Toggle = ({ k, children }: { k: string; children: React.ReactNode }) =>
    <label className="flex items-start gap-2 text-sm"><input className="mt-1" type="checkbox" checked={!!f?.[k]} onChange={(e) => setF({ ...f, [k]: e.target.checked })} /><span>{children}</span></label>;
  return (
    <Section title="Company settings" actions={<Button size="sm" onClick={save} disabled={!f}>Save settings</Button>}>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {f && (
        <div className="grid max-w-3xl gap-5 md:grid-cols-2">
          <div className="space-y-1"><Label className="text-xs">Go-live (cut-over) date</Label><Input type="date" value={f.cutover_date ?? ""} onChange={(e) => setF({ ...f, cutover_date: e.target.value })} />
            <p className="text-xs text-muted-foreground">Frontdesk invoices from this date post to ACE Books; earlier ones are in the Sage opening balances.</p></div>
          <div className="space-y-1"><Label className="text-xs">Walk-in / default customer code</Label><Input value={f.default_customer_code ?? ""} onChange={(e) => setF({ ...f, default_customer_code: e.target.value })} /></div>
          <div className="space-y-1"><Label className="text-xs">Credit limit control</Label>
            <select className="h-9 w-full rounded-md border bg-background px-2 text-sm" value={f.credit_limit_mode} onChange={(e) => setF({ ...f, credit_limit_mode: e.target.value })}>
              <option value="OFF">Off</option><option value="WARN">Warn — allow with reason</option><option value="BLOCK">Block — needs override permission</option></select></div>
          <div className="space-y-1"><Label className="text-xs">Negative stock</Label>
            <select className="h-9 w-full rounded-md border bg-background px-2 text-sm" value={f.negative_stock_policy} onChange={(e) => setF({ ...f, negative_stock_policy: e.target.value })}>
              <option value="BLOCK">Block — cannot sell what is not in stock</option><option value="ALLOW">Allow</option></select></div>
          <div className="space-y-1"><Label className="text-xs">Ageing buckets (days)</Label><Input value={f.aging_buckets} onChange={(e) => setF({ ...f, aging_buckets: e.target.value })} /></div>
          <div className="space-y-1"><Label className="text-xs">Costing</Label><Input value="FIFO (batch-specific when a batch is chosen)" disabled /></div>
          <div className="space-y-3 md:col-span-2">
            <Toggle k="journal_approval_required">Manual journals need approval by a second person before posting</Toggle>
            <Toggle k="allow_self_approval">Allow a user to approve their own journals / stock adjustments (small teams only)</Toggle>
            <Toggle k="auto_post_frontdesk">Post finance-approved Frontdesk invoices to the books automatically</Toggle>
          </div>
        </div>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Budgets
// ---------------------------------------------------------------------------

function Budgets() {
  const qc = useQueryClient();
  const { data, isLoading, error, refetch } = useBooks<Dict[]>(["budgets"], "/budgets");
  const { data: years } = useBooks<Dict[]>(["periods"], "/periods");
  const [open, setOpen] = useState<string | null>(null);
  const create = async () => {
    const fy = years?.find((y) => y.status === "OPEN") ?? years?.[0];
    if (!fy) return;
    const name = await askText(`Budget name for ${fy.name}`, `${fy.name} budget`);
    const b = name && (await act(() => books.post("/budgets", { fiscal_year_id: fy.id, name }), "Budget created"));
    if (b) { refetch(); setOpen(b.id); }
  };
  const rename = async (b: Dict) => {
    const name = await askText("New name for the budget", b.name);
    if (name && name !== b.name && (await act(() => books.patch(`/budgets/${b.id}`, { name }), "Budget renamed"))) refetch();
  };
  const copy = async (b: Dict) => {
    const name = await askText("Name of the copy", `${b.name} (revised)`);
    const n = name && (await act(() => books.post(`/budgets/${b.id}/copy`, { name }), "Budget copied"));
    if (n) { refetch(); setOpen(n.id); }
  };
  const remove = async (b: Dict) => {
    if (!(await askConfirm(`Delete the budget "${b.name}" and its ${b.accounts} account line(s)? It stays in the audit trail.`))) return;
    if (await act(() => books.del(`/budgets/${b.id}`), "Budget deleted")) refetch();
  };
  return (
    <Section title="Budgets" actions={<Button size="sm" onClick={create}><Plus className="mr-1 h-4 w-4" />New budget</Button>}>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (data.length === 0 ? <Empty>No budgets yet.</Empty> : (
        <Table>
          <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Year</TableHead><TableHead className="text-right">Accounts</TableHead><TableHead className="text-right">Total</TableHead><TableHead>Status</TableHead><TableHead /></TableRow></TableHeader>
          <TableBody>{data.map((b) => (
            <TableRow key={b.id} className="cursor-pointer hover:bg-muted/50" onClick={() => setOpen(b.id)}>
              <TableCell>{b.name}</TableCell><TableCell>{b.fiscal_year}</TableCell><TableCell className="text-right">{b.accounts}</TableCell>
              <TableCell className="text-right"><Amount value={b.total} /></TableCell><TableCell><StatusBadge status={b.status} /></TableCell>
              <TableCell className="whitespace-nowrap text-right" onClick={(e) => e.stopPropagation()}>
                <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => rename(b)}>Rename</Button>
                <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => copy(b)}>Copy</Button>
                <Button size="sm" variant="ghost" className="h-7 text-xs text-red-600" onClick={() => remove(b)}>Delete</Button>
              </TableCell>
            </TableRow>
          ))}</TableBody>
        </Table>
      ))}
      <BudgetEditor id={open} onClose={() => { setOpen(null); qc.invalidateQueries({ queryKey: ["books"] }); }} />
    </Section>
  );
}

function BudgetEditor({ id, onClose }: { id: string | null; onClose: () => void }) {
  const { data: b, isLoading, error, refetch } = useBooks<Dict>(["budget", id], `/budgets/${id}`, undefined, !!id);
  const [adding, setAdding] = useState<Dict | null>(null);
  const [annual, setAnnual] = useState("");
  const [cells, setCells] = useState<Record<string, Record<string, string>>>({});
  useEffect(() => setCells({}), [id, b?.lines?.length]);
  const locked = b?.status === "APPROVED";
  const addLine = async () => {
    if (adding && (await act(() => books.put(`/budgets/${id}/lines`, { lines: [{ account_id: adding.id, annual }] }), "Line added"))) { setAdding(null); setAnnual(""); refetch(); }
  };
  const saveCells = async () => {
    const lines = Object.entries(cells).map(([account_id, amounts]) => {
      const line = b!.lines.find((l: Dict) => l.account_id === account_id);
      return { account_id, amounts: { ...(line?.amounts ?? {}), ...amounts } };
    });
    if (lines.length && (await act(() => books.put(`/budgets/${id}/lines`, { lines }), "Budget saved"))) { setCells({}); refetch(); }
  };
  const approve = async () => { if (await act(() => books.post(`/budgets/${id}/approve`, {}), "Budget approved")) refetch(); };
  const reopen = async () => { if (await act(() => books.patch(`/budgets/${id}`, { status: "DRAFT" }), "Budget reopened for editing")) refetch(); };
  const removeLine = async (l: Dict) => {
    if (await askConfirm(`Remove ${l.code} ${l.name} from the budget?`) && (await act(() => books.put(`/budgets/${id}/lines`, { lines: [{ account_id: l.account_id, remove: true }] }), "Line removed"))) refetch();
  };
  return (
    <DetailSheet open={!!id} onOpenChange={(o) => !o && onClose()} title={b ? b.name : "Budget"} description={b ? `${b.fiscal_year} · ${b.status.toLowerCase()}` : ""}
                 footer={b && !locked ? <div className="flex gap-2"><Button variant="outline" disabled={!Object.keys(cells).length} onClick={saveCells}>Save changes</Button><Button onClick={approve}>Approve</Button></div>
                   : b ? <Button variant="outline" onClick={reopen}>Reopen for editing</Button> : undefined}>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {b && (
        <div className="space-y-3 text-sm">
          {!locked && (
            <div className="grid grid-cols-[1fr_140px_auto] items-end gap-2">
              <AccountPick label="Add income / expense account" value={adding} onChange={setAdding} />
              <Input type="number" placeholder="Annual amount" value={annual} onChange={(e) => setAnnual(e.target.value)} />
              <Button size="sm" disabled={!adding || !annual} onClick={addLine}>Spread evenly</Button>
            </div>
          )}
          {b.lines.length === 0 ? <Empty>No budget lines yet.</Empty> : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader><TableRow><TableHead className="sticky left-0 bg-background">Account</TableHead>{b.periods.map((p: Dict) => <TableHead key={p.id} className="text-right text-xs">{p.name}</TableHead>)}<TableHead className="text-right">Total</TableHead></TableRow></TableHeader>
                <TableBody>{b.lines.map((l: Dict) => (
                  <TableRow key={l.account_id}>
                    <TableCell className="sticky left-0 whitespace-nowrap bg-background text-xs"><span className="font-mono">{l.code}</span> {l.name}</TableCell>
                    {b.periods.map((p: Dict) => (
                      <TableCell key={p.id} className="p-1 text-right">{locked ? <Amount value={l.amounts[p.id] ?? 0} blankZero /> :
                        <Input className="h-7 w-24 text-right text-xs" type="number" value={cells[l.account_id]?.[p.id] ?? l.amounts[p.id] ?? ""}
                               onChange={(e) => setCells({ ...cells, [l.account_id]: { ...(cells[l.account_id] ?? {}), [p.id]: e.target.value } })} />}</TableCell>
                    ))}
                    <TableCell className="text-right font-semibold"><Amount value={l.total} /></TableCell>
                    <TableCell>{!locked && <Button size="sm" variant="ghost" className="h-7 text-xs text-red-600" onClick={() => removeLine(l)}>Remove</Button>}</TableCell>
                  </TableRow>
                ))}</TableBody>
              </Table>
            </div>
          )}
        </div>
      )}
    </DetailSheet>
  );
}

// ---------------------------------------------------------------------------
// Sage migration
// ---------------------------------------------------------------------------

const KINDS = [
  { kind: "COA", title: "1. Chart of accounts", hint: "Sage: Reports › General Ledger › Chart of Accounts → Excel/CSV", asOf: false },
  { kind: "TRIAL_BALANCE", title: "2. Trial balance (opening balances)", hint: "Sage: General Ledger Trial Balance as at the day before go-live", asOf: true },
  { kind: "OPEN_AR", title: "3. Open receivables", hint: "Sage: Aged Receivables (detail, by invoice) as at the same date", asOf: true },
  { kind: "OPEN_AP", title: "4. Open payables", hint: "Sage: Aged Payables (detail, by invoice) as at the same date", asOf: true },
  { kind: "INVENTORY", title: "5. Stock on hand", hint: "Sage: Inventory Valuation Report as at the same date", asOf: true },
  { kind: "SALES_JOURNAL", title: "7. Sales history", hint: "Sage: Accounts Receivable › Sales Journal (any period). Shows what each invoice sold.", asOf: false },
  { kind: "COGS_JOURNAL", title: "8. Quantities & cost of sales", hint: "Sage: Inventory › Cost of Goods Sold Journal, same period. Load after the Sales Journal.", asOf: false },
  { kind: "ITEM_COSTING", title: "9. Item movements", hint: "Sage: Inventory › Item Costing Report. Pins each line to its exact item/lot.", asOf: false },
  { kind: "PURCHASE_JOURNAL", title: "10. Purchase history", hint: "Sage: Accounts Payable › Purchase Journal. Shows what each bill bought.", asOf: false },
];

function Migration() {
  const qc = useQueryClient();
  const { data: batches, isLoading, error, refetch } = useBooks<Dict[]>(["migration"], "/migration/batches");
  const { data: ctx } = useBooks<any>(["context"], "/context");
  const [open, setOpen] = useState<string | null>(null);
  const done = () => { refetch(); qc.invalidateQueries({ queryKey: ["books"] }); };
  const latest = useMemo(() => {
    const m: Record<string, Dict> = {};
    (batches ?? []).forEach((b) => { if (b.status !== "DISCARDED" && !m[b.kind]) m[b.kind] = b; });
    return m;
  }, [batches]);
  return (
    <div className="space-y-4">
      <Section title="Move from Sage 50 to ACE Books">
        <p className="mb-3 text-sm text-muted-foreground">Upload each Sage report in order. Every file is staged first so you can check totals against Sage before anything is posted. Loading the trial balance sets the go-live date to the day after its “as of” date.</p>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {KINDS.map((k) => <StageCard key={k.kind} spec={k} latest={latest[k.kind]} onStaged={(id) => { done(); setOpen(id); }} onOpen={setOpen} />)}
          <div className="space-y-2 rounded-lg border p-3 text-sm">
            <div className="font-medium">6. Products & dates</div>
            <p className="text-xs text-muted-foreground">Sync products (with their Sage sales / stock / cost-of-sales accounts) and refresh the invoice dates of opening receivables so ageing matches Sage.</p>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={async () => { const r = await act(() => books.post("/migration/products/sync", {})); if (r) { act(async () => r, `Products synced (${r.created ?? 0} new, ${r.updated ?? 0} updated)`); done(); } }}>Sync products</Button>
              <Button size="sm" variant="outline" onClick={async () => { const r = await act(() => books.post("/migration/opening-dates/refresh", {})); if (r) { act(async () => r, "Opening dates refreshed"); done(); } }}>Refresh opening dates</Button>
              <Button size="sm" variant="outline" onClick={async () => { const r = await act(() => books.post("/migration/opening-batches", {})); if (r) { act(async () => r, `Batches & expiry attached (${r.opening_movements_batched})`); done(); } }}>Attach batches & expiry</Button>
            </div>
            {ctx?.setup && <p className="text-xs text-muted-foreground">{ctx.setup.accounts} accounts · {ctx.setup.products} products · opening balances {ctx.setup.opening_posted ? "posted" : "not posted"}</p>}
          </div>
        </div>
      </Section>
      <Section title="All migration batches">
        {isLoading && <Loading />}<ErrorNote error={error} />
        {batches && (batches.length === 0 ? <Empty>Nothing staged yet.</Empty> : (
          <Table>
            <TableHeader><TableRow><TableHead>Kind</TableHead><TableHead>File</TableHead><TableHead>As of</TableHead><TableHead className="text-right">Rows</TableHead><TableHead className="text-right">Issues</TableHead><TableHead>Status</TableHead><TableHead>When</TableHead></TableRow></TableHeader>
            <TableBody>{batches.map((b) => (
              <TableRow key={b.id} className="cursor-pointer hover:bg-muted/50" onClick={() => setOpen(b.id)}>
                <TableCell className="text-xs">{label(b.kind)}</TableCell><TableCell className="max-w-[200px] truncate text-xs">{b.file_name}</TableCell><TableCell className="whitespace-nowrap">{fmtDate(b.as_of_date)}</TableCell>
                <TableCell className="text-right">{b.row_count}</TableCell><TableCell className={`text-right ${b.issue_count ? "text-amber-600" : ""}`}>{b.issue_count}</TableCell>
                <TableCell><StatusBadge status={b.status} /></TableCell><TableCell className="text-xs">{new Date(b.loaded_at ?? b.created_at).toLocaleString("en-GB")}</TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        ))}
      </Section>
      <BatchSheet id={open} onClose={() => setOpen(null)} onDone={done} />
    </div>
  );
}

function StageCard({ spec, latest, onStaged, onOpen }: { spec: typeof KINDS[number]; latest?: Dict; onStaged: (id: string) => void; onOpen: (id: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [asOf, setAsOf] = useState("");
  const [busy, setBusy] = useState(false);
  const stage = async () => {
    if (!file) return;
    const fd = new FormData();
    fd.append("kind", spec.kind);
    if (asOf) fd.append("as_of", asOf);
    fd.append("file", file);
    setBusy(true);
    const b = await act(() => books.upload("/migration/stage", fd), "Staged — review before loading");
    setBusy(false);
    if (b) { setFile(null); onStaged(b.id); }
  };
  return (
    <div className="space-y-2 rounded-lg border p-3 text-sm">
      <div className="flex items-center justify-between font-medium">{spec.title}
        {latest && <button onClick={() => onOpen(latest.id)}>{latest.status === "LOADED" ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <StatusBadge status={latest.status} />}</button>}</div>
      <p className="text-xs text-muted-foreground">{spec.hint}</p>
      <Input type="file" accept=".csv,.xlsx,.xls" className="h-9 text-xs" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      {spec.asOf && <Input type="date" className="h-9" value={asOf} onChange={(e) => setAsOf(e.target.value)} title="Report as of date" />}
      <Button size="sm" disabled={busy || !file || (spec.asOf && !asOf)} onClick={stage}><Upload className="mr-1 h-4 w-4" />{busy ? "Reading…" : "Stage"}</Button>
    </div>
  );
}

function BatchSheet({ id, onClose, onDone }: { id: string | null; onClose: () => void; onDone: () => void }) {
  const { data: b, isLoading, error, refetch } = useBooks<Dict>(["migration-batch", id], `/migration/batches/${id}`, undefined, !!id);
  const [result, setResult] = useState<Dict | null>(null);
  useEffect(() => setResult(null), [id]);
  const load = async () => {
    if (!await askConfirm("Load this batch into ACE Books? This posts opening balances / creates records.")) return;
    const r = await act(() => books.post(`/migration/batches/${id}/load`, {}), "Loaded");
    if (r) { setResult(r.result); refetch(); onDone(); }
  };
  const discard = async () => { if (await act(() => books.post(`/migration/batches/${id}/discard`, {}), "Discarded")) { refetch(); onDone(); } };
  const summary = b?.summary ?? {};
  const issues: Dict[] = b?.issues ?? [];
  return (
    <DetailSheet open={!!id} onOpenChange={(o) => !o && onClose()} title={b ? `${label(b.kind)} · ${b.file_name}` : ""} description={b ? `${b.row_count} rows${b.as_of_date ? ` · as of ${fmtDate(b.as_of_date)}` : ""}` : ""}
                 footer={b?.status === "STAGED" ? <div className="flex gap-2"><Button variant="outline" onClick={discard}>Discard</Button><Button onClick={load}>Load into ACE Books</Button></div> : undefined}>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {b && (
        <div className="space-y-4 text-sm">
          <StatusBadge status={b.status} />
          <div>
            <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">Check against Sage</div>
            <Table><TableBody>{Object.entries(summary).filter(([k]) => k !== "load_result").map(([k, v]) => (
              <TableRow key={k}><TableCell className="text-xs">{label(k)}</TableCell>
                <TableCell className={`text-right ${k.startsWith("difference") && Number(v) !== 0 ? "font-semibold text-amber-600" : ""}`}>{typeof v === "object" ? <span className="text-xs">{JSON.stringify(v)}</span> : isFinite(Number(v)) && String(v).includes(".") ? <Amount value={v} /> : String(v)}</TableCell></TableRow>
            ))}</TableBody></Table>
          </div>
          {issues.length > 0 && (
            <div>
              <div className="mb-1 flex items-center justify-between text-xs font-semibold uppercase text-amber-600">{issues.length} issue(s)<CsvButton filename={`migration-issues-${b.kind}.csv`} rows={issues} /></div>
              <ul className="max-h-60 space-y-1 overflow-auto text-xs">{issues.slice(0, 200).map((i, n) => <li key={n}>• {i.message ?? JSON.stringify(i)}</li>)}</ul>
            </div>
          )}
          {(result ?? summary.load_result) && (
            <div><div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">Load result</div>
              <pre className="whitespace-pre-wrap rounded bg-muted p-2 text-xs">{JSON.stringify(result ?? summary.load_result, null, 2)}</pre></div>
          )}
          {b.sample?.length > 0 && (
            <div><div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">First rows</div>
              <div className="overflow-x-auto"><Table>
                <TableHeader><TableRow>{Object.keys(b.sample[0]).slice(0, 7).map((k) => <TableHead key={k} className="text-xs">{label(k)}</TableHead>)}</TableRow></TableHeader>
                <TableBody>{b.sample.map((r: Dict, i: number) => <TableRow key={i}>{Object.keys(b.sample[0]).slice(0, 7).map((k) => <TableCell key={k} className="text-xs">{typeof r[k] === "object" ? JSON.stringify(r[k]) : String(r[k] ?? "")}</TableCell>)}</TableRow>)}</TableBody>
              </Table></div></div>
          )}
        </div>
      )}
    </DetailSheet>
  );
}
