import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { BooksShell } from "@/components/books/BooksShell";
import { AccountPick, act, Amount, BankSelect, CsvButton, Empty, ErrorNote, JournalSheet, Loading, Section, Stat, StatusBadge, useBooks } from "@/components/books/kit";
import { books, Dict, fmtDate, naira, today } from "@/lib/books-api";

export default function BooksAssets() {
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState(params.get("tab") ?? "register");
  const open = (k: string, v: string | null) => { const p = new URLSearchParams(params); v ? p.set(k, v) : p.delete(k); setParams(p, { replace: true }); };
  return (
    <BooksShell title="Fixed Assets" actions={<Button size="sm" onClick={() => open("new", "asset")}><Plus className="mr-1 h-4 w-4" />Register asset</Button>}>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="register">Asset register</TabsTrigger>
          <TabsTrigger value="depreciation">Depreciation</TabsTrigger>
          <TabsTrigger value="categories">Categories</TabsTrigger>
        </TabsList>
        <TabsContent value="register"><Register onOpen={(id) => open("asset", id)} /></TabsContent>
        <TabsContent value="depreciation"><Depreciation /></TabsContent>
        <TabsContent value="categories"><Categories /></TabsContent>
      </Tabs>
      <AssetForm open={params.get("new") === "asset"} onClose={(id) => { open("new", null); if (id) open("asset", id); }} />
      <AssetDetail id={params.get("asset")} onClose={() => open("asset", null)} />
    </BooksShell>
  );
}

function Register({ onOpen }: { onOpen: (id: string) => void }) {
  const { data, isLoading, error } = useBooks<Dict[]>(["assets"], "/assets");
  const [status, setStatus] = useState("live");
  const rows = (data ?? []).filter((a) => status === "all" || (status === "live" ? a.status !== "DISPOSED" : a.status === "DISPOSED"));
  const tot = (k: string) => rows.reduce((s, a) => s + Number(a[k]), 0);
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <Stat label="Cost" value={naira(tot("cost"))} /><Stat label="Accumulated depreciation" value={naira(tot("accumulated_depreciation"))} /><Stat label="Net book value" value={naira(tot("net_book_value"))} />
      </div>
      <Section title={`Asset register (${rows.length})`} actions={<>
        <select className="h-8 rounded-md border bg-background px-2 text-xs" value={status} onChange={(e) => setStatus(e.target.value)}><option value="live">In use</option><option value="disposed">Disposed</option><option value="all">All</option></select>
        <CsvButton filename="asset-register.csv" rows={rows} /></>}>
        {isLoading && <Loading />}<ErrorNote error={error} />
        {data && (rows.length === 0 ? <Empty>No assets registered. The balance sheet carries fixed assets from Sage; register each asset (funding "opening balance") so depreciation can run and the register reconciles to the GL.</Empty> : (
          <Table>
            <TableHeader><TableRow><TableHead>Code</TableHead><TableHead>Asset</TableHead><TableHead>Category</TableHead><TableHead>Acquired</TableHead><TableHead className="text-right">Cost</TableHead><TableHead className="text-right">Acc. dep.</TableHead><TableHead className="text-right">NBV</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
            <TableBody>{rows.map((a) => (
              <TableRow key={a.id} className="cursor-pointer hover:bg-muted/50" onClick={() => onOpen(a.id)}>
                <TableCell className="font-mono text-xs">{a.asset_code}</TableCell><TableCell><div>{a.name}</div><div className="text-xs text-muted-foreground">{[a.serial_number, a.location].filter(Boolean).join(" · ")}</div></TableCell>
                <TableCell className="text-xs">{a.category_name}</TableCell><TableCell className="whitespace-nowrap">{fmtDate(a.acquisition_date)}</TableCell>
                <TableCell className="text-right"><Amount value={a.cost} /></TableCell><TableCell className="text-right"><Amount value={a.accumulated_depreciation} /></TableCell>
                <TableCell className="text-right"><Amount value={a.net_book_value} bold /></TableCell><TableCell><StatusBadge status={a.status} /></TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        ))}
      </Section>
    </div>
  );
}

function AssetForm({ open, onClose }: { open: boolean; onClose: (id?: string) => void }) {
  const qc = useQueryClient();
  const { data: cats } = useBooks<Dict[]>(["asset-cats"], "/assets/categories");
  const blank = { name: "", category_id: "", serial_number: "", location: "", acquisition_date: today(), depreciation_start: "", cost: "", residual_value: "",
    useful_life_months: "", funding: "BANK", bank_account_id: "", opening_accumulated_depreciation: "", notes: "" };
  const [f, setF] = useState(blank);
  const [credit, setCredit] = useState<Dict | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (!open) { setF(blank); setCredit(null); } }, [open]);
  const cat = cats?.find((c) => c.id === f.category_id);
  const submit = async () => {
    setBusy(true);
    const a = await act(() => books.post("/assets", { ...f, depreciation_start: f.depreciation_start || undefined, useful_life_months: f.useful_life_months || undefined,
      residual_value: f.residual_value || 0, credit_account_id: credit?.id, bank_account_id: f.bank_account_id || undefined }), "Asset registered");
    setBusy(false);
    if (a) { qc.invalidateQueries({ queryKey: ["books"] }); onClose(a.id); }
  };
  const set = (k: keyof typeof blank) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <DetailSheet open={open} onOpenChange={(o) => !o && onClose()} title="Register fixed asset"
                 description="Straight-line depreciation, monthly. Use 'Opening balance' for assets already on the books from Sage — no new journal is posted."
                 footer={<Button disabled={busy || !f.name || !f.category_id || Number(f.cost) <= 0 || (f.funding === "BANK" && !f.bank_account_id) || (f.funding === "CLEARING" && !credit)} onClick={submit}>{busy ? "Saving…" : "Register asset"}</Button>}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2 space-y-1"><Label className="text-xs">Name</Label><Input value={f.name} onChange={set("name")} /></div>
          <div className="space-y-1"><Label className="text-xs">Category</Label><select className="h-9 w-full rounded-md border bg-background px-2 text-sm" value={f.category_id} onChange={set("category_id")}>
            <option value="">Choose…</option>{(cats ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></div>
          <div className="space-y-1"><Label className="text-xs">Useful life (months)</Label><Input type="number" placeholder={cat?.default_life_months ? String(cat.default_life_months) : ""} value={f.useful_life_months} onChange={set("useful_life_months")} /></div>
          <div className="space-y-1"><Label className="text-xs">Serial number</Label><Input value={f.serial_number} onChange={set("serial_number")} /></div>
          <div className="space-y-1"><Label className="text-xs">Location</Label><Input value={f.location} onChange={set("location")} /></div>
          <div className="space-y-1"><Label className="text-xs">Acquired</Label><Input type="date" value={f.acquisition_date} onChange={set("acquisition_date")} /></div>
          <div className="space-y-1"><Label className="text-xs">Depreciate from (default: month acquired)</Label><Input type="date" value={f.depreciation_start} onChange={set("depreciation_start")} /></div>
          <div className="space-y-1"><Label className="text-xs">Cost</Label><Input type="number" value={f.cost} onChange={set("cost")} /></div>
          <div className="space-y-1"><Label className="text-xs">Residual value</Label><Input type="number" value={f.residual_value} onChange={set("residual_value")} /></div>
        </div>
        <div className="space-y-1"><Label className="text-xs">How was it paid for?</Label>
          <div className="flex gap-2">{[["BANK", "Paid from bank"], ["CLEARING", "Other account (e.g. creditor)"], ["OPENING", "Opening balance (from Sage)"]].map(([k, l]) =>
            <Button key={k} size="sm" variant={f.funding === k ? "default" : "outline"} onClick={() => setF({ ...f, funding: k })}>{l}</Button>)}</div></div>
        {f.funding === "BANK" && <BankSelect value={f.bank_account_id} onChange={(v) => setF({ ...f, bank_account_id: v })} label="Paid from" />}
        {f.funding === "CLEARING" && <AccountPick label="Credit account" value={credit} onChange={setCredit} />}
        {f.funding === "OPENING" && <div className="space-y-1"><Label className="text-xs">Accumulated depreciation already charged in Sage</Label><Input type="number" value={f.opening_accumulated_depreciation} onChange={set("opening_accumulated_depreciation")} /></div>}
      </div>
    </DetailSheet>
  );
}

function AssetDetail({ id, onClose }: { id: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const { data: a, isLoading, error, refetch } = useBooks<Dict>(["asset", id], `/assets/${id}`, undefined, !!id);
  const [journal, setJournal] = useState<string | null>(null);
  const [d, setD] = useState({ disposal_date: today(), proceeds: "", bank_account_id: "" });
  const [disposing, setDisposing] = useState(false);
  useEffect(() => setDisposing(false), [id]);
  const dispose = async () => {
    if (await act(() => books.post(`/assets/${id}/dispose`, { ...d, proceeds: d.proceeds || 0, bank_account_id: d.bank_account_id || undefined }), "Asset disposed")) { refetch(); qc.invalidateQueries({ queryKey: ["books"] }); }
  };
  const gain = a ? Number(d.proceeds || 0) - Number(a.net_book_value) : 0;
  return (
    <>
      <DetailSheet open={!!id} onOpenChange={(o) => !o && onClose()} title={a ? `${a.asset_code} · ${a.name}` : ""} description={a?.category_name}>
        {isLoading && <Loading />}<ErrorNote error={error} />
        {a && (
          <div className="space-y-4 text-sm">
            <div className="flex flex-wrap items-center gap-2"><StatusBadge status={a.status} /><span className="text-muted-foreground">acquired {fmtDate(a.acquisition_date)} · life {a.useful_life_months} months · depreciating from {fmtDate(a.depreciation_start)}</span></div>
            <div className="grid grid-cols-2 gap-2">
              <div>Cost<div className="font-semibold"><Amount value={a.cost} /></div></div>
              <div>Accumulated depreciation<div className="font-semibold"><Amount value={a.accumulated_depreciation} /></div></div>
              <div>Net book value<div className="font-semibold"><Amount value={a.net_book_value} /></div></div>
              <div>Monthly charge<div className="font-semibold"><Amount value={a.monthly_charge} /></div></div>
            </div>
            {a.depreciation.length > 0 && (
              <Table><TableHeader><TableRow><TableHead>Period</TableHead><TableHead>Run</TableHead><TableHead className="text-right">Charge</TableHead></TableRow></TableHeader>
                <TableBody>{a.depreciation.map((r: Dict) => <TableRow key={r.run_number}><TableCell>{r.period}</TableCell><TableCell className="font-mono text-xs">{r.run_number}</TableCell><TableCell className="text-right"><Amount value={r.amount} /></TableCell></TableRow>)}</TableBody></Table>
            )}
            <div className="flex flex-wrap gap-2">
              {a.acquisition_journal_id && <Button size="sm" variant="outline" onClick={() => setJournal(a.acquisition_journal_id)}>Acquisition journal</Button>}
              {a.disposal_journal_id && <Button size="sm" variant="outline" onClick={() => setJournal(a.disposal_journal_id)}>Disposal journal</Button>}
              {a.status !== "DISPOSED" && !disposing && <Button size="sm" variant="destructive" onClick={() => setDisposing(true)}>Dispose / sell</Button>}
            </div>
            {disposing && (
              <div className="space-y-2 rounded-lg border p-3">
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1"><Label className="text-xs">Date</Label><Input type="date" value={d.disposal_date} onChange={(e) => setD({ ...d, disposal_date: e.target.value })} /></div>
                  <div className="space-y-1"><Label className="text-xs">Sale proceeds (0 if scrapped)</Label><Input type="number" value={d.proceeds} onChange={(e) => setD({ ...d, proceeds: e.target.value })} /></div>
                </div>
                {Number(d.proceeds) > 0 && <BankSelect value={d.bank_account_id} onChange={(v) => setD({ ...d, bank_account_id: v })} label="Proceeds received into" />}
                <p className="text-xs">{gain >= 0 ? "Gain" : "Loss"} on disposal: <Amount value={gain} bold /></p>
                <Button size="sm" variant="destructive" disabled={Number(d.proceeds) > 0 && !d.bank_account_id} onClick={dispose}>Post disposal</Button>
              </div>
            )}
          </div>
        )}
      </DetailSheet>
      <JournalSheet id={journal} onClose={() => setJournal(null)} />
    </>
  );
}

function Depreciation() {
  const qc = useQueryClient();
  const { data: years } = useBooks<Dict[]>(["periods"], "/periods");
  const periods = useMemo(() => (years ?? []).flatMap((y) => y.periods).filter((p: Dict) => p.status === "OPEN"), [years]);
  const [period, setPeriod] = useState("");
  const chosen = period || periods[0]?.id || "";
  const { data, isLoading, error, refetch } = useBooks<Dict>(["dep-preview", chosen], "/assets/depreciation/preview", { period_id: chosen }, !!chosen);
  const [journal, setJournal] = useState<string | null>(null);
  const run = async () => {
    const r = await act(() => books.post("/assets/depreciation/run", { period_id: chosen }), "Depreciation posted");
    if (r) { refetch(); qc.invalidateQueries({ queryKey: ["books"] }); if (r.journal_id) setJournal(r.journal_id); }
  };
  return (
    <Section title="Monthly depreciation run" actions={data && !data.already_run && data.lines.length > 0 ? <Button size="sm" onClick={run}>Post {naira(data.total)}</Button> : undefined}>
      <select className="mb-3 h-9 rounded-md border bg-background px-2 text-sm" value={chosen} onChange={(e) => setPeriod(e.target.value)}>
        {periods.map((p: Dict) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (data.already_run ? <Empty>Depreciation for {data.period.name} has already been posted.</Empty> : data.lines.length === 0 ? <Empty>Nothing to depreciate in {data.period.name}.</Empty> : (
        <Table>
          <TableHeader><TableRow><TableHead>Asset</TableHead><TableHead className="text-right">Charge</TableHead></TableRow></TableHeader>
          <TableBody>
            {data.lines.map((l: Dict) => <TableRow key={l.asset_id}><TableCell><span className="font-mono text-xs">{l.asset_code}</span> {l.name}</TableCell><TableCell className="text-right"><Amount value={l.amount} /></TableCell></TableRow>)}
            <TableRow className="font-semibold"><TableCell>Total</TableCell><TableCell className="text-right"><Amount value={data.total} /></TableCell></TableRow>
          </TableBody>
        </Table>
      ))}
      <JournalSheet id={journal} onClose={() => setJournal(null)} />
    </Section>
  );
}

function Categories() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useBooks<Dict[]>(["asset-cats"], "/assets/categories");
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState({ code: "", name: "", default_life_months: "", depreciable: true });
  const [acc, setAcc] = useState<{ asset: Dict | null; accum: Dict | null; exp: Dict | null; disp: Dict | null }>({ asset: null, accum: null, exp: null, disp: null });
  const save = async () => {
    if (await act(() => books.post("/assets/categories", { ...f, default_life_months: f.default_life_months || undefined, asset_account_id: acc.asset?.id,
      accum_dep_account_id: acc.accum?.id, dep_expense_account_id: acc.exp?.id, disposal_account_id: acc.disp?.id }), "Category added")) {
      setAdding(false); qc.invalidateQueries({ queryKey: ["books"] });
    }
  };
  return (
    <Section title="Asset categories" actions={<Button size="sm" variant="outline" onClick={() => setAdding(!adding)}>Add category</Button>}>
      {adding && (
        <div className="mb-4 space-y-2 rounded-lg border p-3">
          <div className="grid grid-cols-3 gap-2">
            <Input placeholder="Code" value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} />
            <Input placeholder="Name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
            <Input type="number" placeholder="Default life (months)" value={f.default_life_months} onChange={(e) => setF({ ...f, default_life_months: e.target.value })} />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <AccountPick label="Asset (cost) account" value={acc.asset} onChange={(v) => setAcc({ ...acc, asset: v })} />
            <AccountPick label="Accumulated depreciation" value={acc.accum} onChange={(v) => setAcc({ ...acc, accum: v })} />
            <AccountPick label="Depreciation expense" value={acc.exp} onChange={(v) => setAcc({ ...acc, exp: v })} />
            <AccountPick label="Gain/loss on disposal (optional)" value={acc.disp} onChange={(v) => setAcc({ ...acc, disp: v })} />
          </div>
          <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={f.depreciable} onChange={(e) => setF({ ...f, depreciable: e.target.checked })} />depreciable (untick for land)</label>
          <Button size="sm" disabled={!f.code || !f.name || !acc.asset} onClick={save}>Save category</Button>
        </div>
      )}
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && (
        <Table>
          <TableHeader><TableRow><TableHead>Code</TableHead><TableHead>Name</TableHead><TableHead>Cost GL</TableHead><TableHead>Acc. dep. GL</TableHead><TableHead>Expense GL</TableHead><TableHead className="text-right">Life</TableHead></TableRow></TableHeader>
          <TableBody>{data.map((c) => (
            <TableRow key={c.id}><TableCell className="font-mono text-xs">{c.code}</TableCell><TableCell>{c.name}</TableCell><TableCell className="text-xs">{c.asset_code_gl}</TableCell>
              <TableCell className="text-xs">{c.accum_code ?? "—"}</TableCell><TableCell className="text-xs">{c.expense_code ?? "—"}</TableCell>
              <TableCell className="text-right">{c.depreciable ? (c.default_life_months ? `${c.default_life_months} mo` : "—") : "not depreciated"}</TableCell></TableRow>
          ))}</TableBody>
        </Table>
      )}
    </Section>
  );
}
