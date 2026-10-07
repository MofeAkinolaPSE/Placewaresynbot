/**
 * CRM › Sales Pipeline. Deals move New lead → Qualified → Proposal & terms → Won | Lost.
 * Won and Lost show deals closed in the last 90 days (not every customer). A won deal becomes
 * (or links) the customer in ACE Books; a deal whose customer is invoiced in ACE Books is won
 * automatically. Reminders, weekly report, targets and leaderboard are built from the same
 * records (backend services/crm_hub.py).
 */
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlarmClock, BarChart3, Bell, ChevronLeft, ChevronRight, Download, Kanban, Loader2, MessageSquare, Plus, Send, Trophy, TrendingUp } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { PageHeader } from "@/components/workspace/PageHeader";
import { RecipientPicker, type Recipient } from "@/components/workspace/RecipientPicker";
import { useAuth } from "@/components/AuthProvider";
import { api } from "@/lib/api-client";
import { Dict, fmtDate, naira, num } from "@/lib/books-api";
import { DealSheet, downloadAuthed, dt, myId, NewDealSheet, RepPick, ReminderSheet, STAGE_LABEL, useCrmRefresh } from "@/components/crm/crm-kit";

const COLS = ["new", "qualified", "proposal", "won", "lost"];
const COL_TOP: Record<string, string> = { new: "border-t-sky-500", qualified: "border-t-violet-500", proposal: "border-t-amber-500", won: "border-t-emerald-500", lost: "border-t-slate-400" };
const monday = (d = new Date()) => { const x = new Date(d); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); return x.toISOString().slice(0, 10); };

export default function SalesCRM() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "pipeline";
  const [newDeal, setNewDeal] = useState(false);
  const [bulk, setBulk] = useState(false);
  const { data: rem } = useQuery({ queryKey: ["crm-hub", "reminders", "mine"], queryFn: () => api.crmHub.reminders("mine") });
  const dueCount = (rem?.overdue?.length ?? 0) + (rem?.today?.length ?? 0);
  return (
    <div className="space-y-5">
      <PageHeader icon={Kanban} title="Sales Pipeline" subtitle="Deals · reminders · weekly report · targets - customers and sales from ACE Books"
        actions={<>
          <Button variant="outline" onClick={() => setBulk(true)}><Send className="mr-1.5 h-4 w-4" />Message customers</Button>
          <Button onClick={() => setNewDeal(true)}><Plus className="mr-1.5 h-4 w-4" />Add lead</Button>
        </>} />
      <Tabs value={tab} onValueChange={(t) => setParams({ tab: t }, { replace: true })}>
        <TabsList className="h-auto flex-wrap">
          <TabsTrigger value="pipeline"><Kanban className="mr-1.5 h-4 w-4" />Pipeline</TabsTrigger>
          <TabsTrigger value="reminders"><Bell className="mr-1.5 h-4 w-4" />Reminders{dueCount > 0 && <Badge variant="destructive" className="ml-1.5 px-1.5 text-[10px]">{dueCount}</Badge>}</TabsTrigger>
          <TabsTrigger value="report"><BarChart3 className="mr-1.5 h-4 w-4" />Weekly report</TabsTrigger>
          <TabsTrigger value="targets"><TrendingUp className="mr-1.5 h-4 w-4" />Targets</TabsTrigger>
          <TabsTrigger value="leaderboard"><Trophy className="mr-1.5 h-4 w-4" />Leaderboard</TabsTrigger>
          <TabsTrigger value="ask"><MessageSquare className="mr-1.5 h-4 w-4" />Ask ACE</TabsTrigger>
        </TabsList>
        <TabsContent value="pipeline" className="mt-4"><Pipeline /></TabsContent>
        <TabsContent value="reminders" className="mt-4"><Reminders /></TabsContent>
        <TabsContent value="report" className="mt-4"><WeeklyReport /></TabsContent>
        <TabsContent value="targets" className="mt-4"><Targets /></TabsContent>
        <TabsContent value="leaderboard" className="mt-4"><Leaderboard /></TabsContent>
        <TabsContent value="ask" className="mt-4"><AskAce /></TabsContent>
      </Tabs>
      <NewDealSheet open={newDeal} onClose={() => setNewDeal(false)} />
      <BulkMessage open={bulk} onClose={() => setBulk(false)} />
    </div>
  );
}

// ---------------------------------------------------------------------------

function Pipeline() {
  const me = myId();
  const [rep, setRep] = useState("");
  const [picked, setPicked] = useState<number | null>(null);
  const { data, isLoading } = useQuery({ queryKey: ["crm-hub", "pipeline", rep], queryFn: () => api.crmHub.pipeline(rep || undefined) });
  const open = ["new", "qualified", "proposal"];
  const openCount = open.reduce((s, c) => s + (data?.counts?.[c] ?? 0), 0);
  const openValue = open.reduce((s, c) => s + (data?.values?.[c] ?? 0), 0);
  const closed = (data?.counts?.won ?? 0) + (data?.counts?.lost ?? 0);
  const stale = open.reduce((s, c) => s + (data?.board?.[c] ?? []).filter((x: Dict) => x.stale || x.reminder_overdue).length, 0);
  return (
    <div className="space-y-4">
      <KpiStrip items={[
        { label: "Open deals", value: openCount, sub: `${naira(openValue)} expected` },
        { label: "Won, last 90 days", value: data?.counts?.won ?? 0, tone: "success", sub: naira(data?.values?.won ?? 0) },
        { label: "Win rate, last 90 days", value: closed ? `${Math.round((data.counts.won / closed) * 100)}%` : "—", sub: `${data?.counts?.lost ?? 0} lost` },
        { label: "Need attention", value: stale, tone: stale ? "warning" : "success", sub: "overdue follow-up or no action for 14+ days" },
      ]} />
      <div className="flex items-center gap-2">
        <div className="w-60"><RepPick value={rep} onChange={setRep} allowTeam placeholder="Whole team" /></div>
        {me && <Button size="sm" variant="outline" onClick={() => setRep(me)}>My deals</Button>}
      </div>
      {isLoading ? <div className="flex justify-center py-16"><Loader2 className="h-6 w-6 animate-spin" /></div> : (
        <div className="grid gap-3 overflow-x-auto lg:grid-cols-5" style={{ minWidth: 0 }}>
          {COLS.map((c) => {
            const cards: Dict[] = data?.board?.[c] ?? [];
            return (
              <div key={c} className={`flex min-w-[220px] flex-col rounded-lg border border-t-4 bg-muted/20 ${COL_TOP[c]}`}>
                <div className="flex items-center justify-between px-3 py-2">
                  <div><div className="text-sm font-semibold">{STAGE_LABEL[c]}</div>
                    <div className="text-[11px] text-muted-foreground">{cards.length} · {naira(data?.values?.[c] ?? 0)}{["won", "lost"].includes(c) ? " · last 90 days" : ""}</div></div>
                </div>
                <div className="flex-1 space-y-2 overflow-y-auto p-2" style={{ maxHeight: 560 }}>
                  {cards.length === 0 && <p className="py-6 text-center text-[11px] text-muted-foreground">{c === "new" ? "Add a lead or send one from the lead finder." : "Nothing here."}</p>}
                  {cards.map((x) => (
                    <button key={x.id} onClick={() => setPicked(x.id)} className="w-full rounded-md border bg-card p-2.5 text-left shadow-sm hover:border-primary/50">
                      <div className="truncate text-sm font-medium">{x.company_name || "Unnamed lead"}</div>
                      <div className="truncate text-[11px] text-muted-foreground">{[x.contact_person, x.contact_phone].filter(Boolean).join(" · ") || "no contact yet"}</div>
                      <div className="mt-1 flex flex-wrap items-center gap-1 text-[11px]">
                        {Number(x.expected_value) > 0 && <span className="font-medium">{naira(x.expected_value)}</span>}
                        {x.customer_id && <Badge variant="outline" className="h-4 px-1 text-[10px]">customer</Badge>}
                        {x.reminder_overdue && <Badge variant="destructive" className="h-4 px-1 text-[10px]">follow-up overdue</Badge>}
                        {x.stale && !x.reminder_overdue && <Badge variant="outline" className="h-4 border-amber-400 px-1 text-[10px] text-amber-700">idle {x.days_in_stage}d</Badge>}
                      </div>
                      <div className="mt-1 flex justify-between text-[10px] text-muted-foreground">
                        <span>{x.rep_name ?? "unassigned"}</span>
                        <span>{c === "won" ? `won ${fmtDate(x.won_at)}` : c === "lost" ? "lost" : x.next_reminder ? `next ${dt(x.next_reminder)}` : `${x.days_in_stage ?? 0}d in stage`}</span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
      <DealSheet id={picked} onClose={() => setPicked(null)} />
    </div>
  );
}

// ---------------------------------------------------------------------------

function Reminders() {
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const refresh = useCrmRefresh();
  const [picked, setPicked] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const { data, isLoading } = useQuery({ queryKey: ["crm-hub", "reminders", scope], queryFn: () => api.crmHub.reminders(scope) });
  const actOn = async (id: string, a: "done" | "snooze" | "dismiss", days = 1) => {
    try { await api.crmHub.reminderAction(id, a, days); toast.success(a === "done" ? "Done" : a === "snooze" ? `Moved ${days} day${days > 1 ? "s" : ""}` : "Dismissed"); refresh(); }
    catch (e: any) { toast.error(e?.message); }
  };
  const Group = ({ title, rows, tone }: { title: string; rows: Dict[]; tone?: string }) => rows.length === 0 ? null : (
    <Card>
      <CardHeader className="pb-2"><CardTitle className={`text-sm ${tone ?? ""}`}>{title} ({rows.length})</CardTitle></CardHeader>
      <CardContent className="space-y-1.5">
        {rows.map((r) => (
          <div key={r.id} className="flex items-center justify-between gap-3 border-b pb-1.5 text-sm last:border-0">
            <div className="min-w-0">
              <div className="truncate font-medium">{r.title || r.reminder_type?.replace("_", " ")}{(r.lead_name || r.customer_name) && <span className="font-normal text-muted-foreground"> · {r.lead_name || r.customer_name}</span>}</div>
              <div className="truncate text-[11px] text-muted-foreground">{dt(r.due_at)}{r.rep_name ? ` · ${r.rep_name}` : ""}{r.contact_phone ? ` · ${r.contact_phone}` : ""}{r.note ? ` · ${r.note}` : ""}</div>
            </div>
            {!["done", "dismissed"].includes(r.status) ? (
              <div className="flex shrink-0 gap-1">
                {r.lead_id && <Button size="sm" variant="ghost" onClick={() => setPicked(r.lead_id)}>Open</Button>}
                <Button size="sm" variant="outline" onClick={() => actOn(r.id, "snooze", 1)}>+1 day</Button>
                <Button size="sm" onClick={() => actOn(r.id, "done")}>Done</Button>
              </div>
            ) : <span className="text-[11px] text-muted-foreground">{r.status} {dt(r.completed_at)}</span>}
          </div>
        ))}
      </CardContent>
    </Card>
  );
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        {(["mine", "all"] as const).map((s) => <Button key={s} size="sm" className="h-8" variant={scope === s ? "default" : "outline"} onClick={() => setScope(s)}>{s === "mine" ? "My reminders" : "Whole team"}</Button>)}
        <Button size="sm" className="ml-auto" onClick={() => setAdding(true)}><AlarmClock className="mr-1.5 h-4 w-4" />New reminder</Button>
      </div>
      {isLoading ? <Loader2 className="mx-auto h-6 w-6 animate-spin" /> : (
        <>
          {["overdue", "today", "upcoming"].every((k) => (data?.[k] ?? []).length === 0) &&
            <p className="rounded-md border p-6 text-center text-sm text-muted-foreground">No reminders due. Set one from a deal, or when you log a call with a follow-up date.</p>}
          <Group title="Overdue" rows={data?.overdue ?? []} tone="text-red-600" />
          <Group title="Today" rows={data?.today ?? []} tone="text-amber-700 dark:text-amber-300" />
          <Group title="Coming up" rows={data?.upcoming ?? []} />
          <Group title="Done in the last 14 days" rows={data?.done ?? []} />
        </>
      )}
      <DealSheet id={picked} onClose={() => setPicked(null)} />
      <ReminderSheet target={adding ? {} : null} onClose={() => setAdding(false)} />
    </div>
  );
}

// ---------------------------------------------------------------------------

function WeeklyReport() {
  const [week, setWeek] = useState(monday());
  const { data: r, isLoading } = useQuery({ queryKey: ["crm-hub", "weekly", week], queryFn: () => api.crmHub.weeklyReport(week) });
  const shift = (n: number) => { const d = new Date(week); d.setDate(d.getDate() + 7 * n); setWeek(d.toISOString().slice(0, 10)); };
  const s = r?.summary ?? {};
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="icon" variant="outline" onClick={() => shift(-1)}><ChevronLeft className="h-4 w-4" /></Button>
        <div className="min-w-[210px] text-center font-semibold">{r ? `${fmtDate(r.week_start)} – ${fmtDate(r.week_end)}` : "…"}</div>
        <Button size="icon" variant="outline" onClick={() => shift(1)} disabled={week >= monday()}><ChevronRight className="h-4 w-4" /></Button>
        <div className="ml-auto flex gap-2">
          <Button variant="outline" onClick={() => downloadAuthed(api.crmHub.weeklyReportCsvUrl(week), `weekly_sales_${week}.csv`).catch((e) => toast.error(e.message))}>
            <Download className="mr-1.5 h-4 w-4" />Export CSV</Button>
          <Button variant="outline" onClick={() => window.print()}>Print / PDF</Button>
        </div>
      </div>
      {isLoading || !r ? <Loader2 className="mx-auto h-6 w-6 animate-spin" /> : (
        <>
          <KpiStrip items={[
            { label: "New leads", value: s.new_leads, sub: `${s.prospects_saved} prospects saved · ${s.prospects_contacted} contacted` },
            { label: "Calls, visits & messages", value: s.activities, sub: `${s.reminders_done} reminders done · ${s.reminders_overdue} overdue` },
            { label: "Deals won", value: s.won, tone: s.won ? "success" : "default", sub: `${naira(s.won_value)} · ${s.lost} lost` },
            { label: "Sales invoiced (ACE Books)", value: naira(s.sales), sub: `${num(s.invoices)} invoices · ${num(s.customers_invoiced)} customers` },
          ]} />
          <p className="text-xs text-muted-foreground">Open pipeline now: {s.open_pipeline} deals, {naira(s.open_pipeline_value)}.
            {s.sales === 0 && " ACE Books has no invoices this week yet (sales after 30 Jun are loaded with the July–September import)."}</p>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card><CardHeader className="pb-2"><CardTitle className="text-sm">By rep</CardTitle></CardHeader><CardContent className="p-0">
              {r.per_rep.length === 0 ? <p className="p-4 text-sm text-muted-foreground">No activity recorded this week.</p> : (
                <Table><TableHeader><TableRow><TableHead>Rep</TableHead><TableHead className="text-right">New leads</TableHead><TableHead className="text-right">Activity</TableHead>
                  <TableHead className="text-right">Won</TableHead><TableHead className="text-right">Lost</TableHead></TableRow></TableHeader>
                  <TableBody>{r.per_rep.map((p: Dict) => (
                    <TableRow key={p.rep}><TableCell>{p.rep}</TableCell><TableCell className="text-right">{p.new_leads}</TableCell><TableCell className="text-right">{p.activities}</TableCell>
                      <TableCell className="text-right">{p.won}{p.won_value ? ` · ${naira(p.won_value)}` : ""}</TableCell><TableCell className="text-right">{p.lost}</TableCell></TableRow>))}</TableBody></Table>)}
            </CardContent></Card>
            <Card><CardHeader className="pb-2"><CardTitle className="text-sm">New leads, wins & losses</CardTitle></CardHeader><CardContent className="space-y-1 text-sm">
              {[...r.new_leads.map((l: Dict) => ["New", l.company_name, `${String(l.source ?? "").replace("_", " ")}${l.rep_name ? ` · ${l.rep_name}` : ""}`]),
                ...r.won.map((l: Dict) => ["Won", l.company_name, naira(l.expected_value)]), ...r.lost.map((l: Dict) => ["Lost", l.company_name, l.lost_reason])].map(([k, n, x], i) => (
                <div key={i} className="flex justify-between gap-2 border-b pb-1 last:border-0"><span><Badge variant="outline" className="mr-2 text-[10px]">{k}</Badge>{n}</span><span className="truncate text-xs text-muted-foreground">{x}</span></div>))}
              {r.new_leads.length + r.won.length + r.lost.length === 0 && <p className="text-muted-foreground">None this week.</p>}
            </CardContent></Card>
          </div>
          <Card><CardHeader className="pb-2"><CardTitle className="text-sm">Activity log</CardTitle></CardHeader><CardContent className="space-y-1 text-sm">
            {r.activity.length === 0 && <p className="text-muted-foreground">Nothing logged this week.</p>}
            {r.activity.map((a: Dict, i: number) => (
              <div key={i} className="flex justify-between gap-2 border-b pb-1 text-xs last:border-0"><span><span className="font-medium capitalize">{a.interaction_type.replace("_", " ")}</span>
                {a.company_name ? ` · ${a.company_name}` : ""} · {a.summary}</span><span className="shrink-0 text-muted-foreground">{dt(a.occurred_at)} · {a.by}</span></div>))}
          </CardContent></Card>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

function Targets() {
  const { roles } = useAuth();
  const canSet = roles.some((r) => ["admin", "management"].includes(r));
  const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7));
  const [setting, setSetting] = useState(false);
  const [f, setF] = useState({ rep_id: "", target_value: "", target_deals: "" });
  const refresh = useCrmRefresh();
  const { data: t, isLoading } = useQuery({ queryKey: ["crm-hub", "targets", period], queryFn: () => api.crmHub.targets(period) });
  const save = async () => {
    try { await api.crmHub.setTarget({ period, rep_id: f.rep_id || undefined, target_value: Number(f.target_value), target_deals: f.target_deals ? Number(f.target_deals) : undefined });
      toast.success("Target saved"); setSetting(false); refresh(); } catch (e: any) { toast.error(e?.message); }
  };
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1"><Label className="text-xs">Month</Label><Input type="month" value={period} onChange={(e) => setPeriod(e.target.value)} className="w-44" /></div>
        {canSet && <Button className="ml-auto" onClick={() => setSetting(true)}><Plus className="mr-1.5 h-4 w-4" />Set target</Button>}
      </div>
      {isLoading || !t ? <Loader2 className="mx-auto h-6 w-6 animate-spin" /> : (
        <>
          <KpiStrip items={[
            { label: "Team sales (ACE Books)", value: naira(t.sales.value), sub: `${num(t.sales.invoices)} invoices · ${num(t.sales.customers)} customers` },
            { label: "Month elapsed", value: `${t.elapsed_pct}%`, sub: `${fmtDate(t.start)} – ${fmtDate(t.end)}` },
            { label: "Deals won", value: t.won_by_rep.reduce((s: number, w: Dict) => s + w.deals, 0), sub: naira(t.won_by_rep.reduce((s: number, w: Dict) => s + w.value, 0)) },
            { label: "Targets set", value: t.targets.length },
          ]} />
          {t.sales.value === 0 && <p className="text-xs text-muted-foreground">No ACE Books invoices in this month yet - sales after 30 Jun arrive with the July–September import.</p>}
          <Card><CardContent className="p-0">
            {t.targets.length === 0 ? <p className="p-6 text-center text-sm text-muted-foreground">No targets for this month.{canSet ? " Set a team or rep target." : ""}</p> : (
              <Table><TableHeader><TableRow><TableHead>Who</TableHead><TableHead>Measured on</TableHead><TableHead className="text-right">Target</TableHead>
                <TableHead className="text-right">Actual</TableHead><TableHead className="w-[30%]">Progress</TableHead></TableRow></TableHeader>
                <TableBody>{t.targets.map((x: Dict) => (
                  <TableRow key={x.id}><TableCell className="font-medium">{x.who}</TableCell><TableCell className="text-xs text-muted-foreground">{x.basis}</TableCell>
                    <TableCell className="text-right">{naira(x.target_value)}</TableCell><TableCell className="text-right">{naira(x.actual)}</TableCell>
                    <TableCell><div className="h-2 rounded bg-muted"><div className={`h-2 rounded ${(x.attainment_pct ?? 0) >= t.elapsed_pct ? "bg-emerald-500" : "bg-amber-500"}`}
                      style={{ width: `${Math.min(100, x.attainment_pct ?? 0)}%` }} /></div><div className="text-[11px] text-muted-foreground">{x.attainment_pct ?? 0}% (time used {t.elapsed_pct}%)</div></TableCell>
                  </TableRow>))}</TableBody></Table>)}
          </CardContent></Card>
        </>
      )}
      <DetailSheet open={setting} onOpenChange={setSetting} title={`Target for ${period}`} description="A team target is measured on ACE Books sales; a rep target on the value of deals the rep wins."
                   footer={<Button className="w-full" disabled={!(Number(f.target_value) > 0)} onClick={save}>Save target</Button>}>
        <div className="space-y-1"><Label className="text-xs">Who</Label><RepPick value={f.rep_id} onChange={(v) => setF({ ...f, rep_id: v })} allowTeam /></div>
        <div className="space-y-1"><Label className="text-xs">Target (₦)</Label><Input type="number" value={f.target_value} onChange={(e) => setF({ ...f, target_value: e.target.value })} /></div>
        <div className="space-y-1"><Label className="text-xs">Deals (optional)</Label><Input type="number" value={f.target_deals} onChange={(e) => setF({ ...f, target_deals: e.target.value })} /></div>
      </DetailSheet>
    </div>
  );
}

// ---------------------------------------------------------------------------

function Leaderboard() {
  const [days, setDays] = useState(30);
  const { data, isLoading } = useQuery({ queryKey: ["crm-hub", "leaderboard", days], queryFn: () => api.crmHub.leaderboard(days) });
  return (
    <div className="space-y-3">
      <div className="flex gap-2">{[7, 30, 90].map((d) => <Button key={d} size="sm" className="h-8" variant={days === d ? "default" : "outline"} onClick={() => setDays(d)}>Last {d} days</Button>)}</div>
      <Card><CardContent className="p-0">
        {isLoading ? <Loader2 className="m-6 mx-auto h-6 w-6 animate-spin" /> : (data?.reps ?? []).length === 0 ? <p className="p-6 text-center text-sm text-muted-foreground">No sales activity yet.</p> : (
          <Table><TableHeader><TableRow><TableHead>#</TableHead><TableHead>Rep</TableHead><TableHead className="text-right">Won</TableHead><TableHead className="text-right">Won value</TableHead>
            <TableHead className="text-right">Leads added</TableHead><TableHead className="text-right">Calls & visits</TableHead><TableHead className="text-right">Lost</TableHead><TableHead className="text-right">Open pipeline</TableHead></TableRow></TableHeader>
            <TableBody>{data.reps.map((r: Dict, i: number) => (
              <TableRow key={r.rep}><TableCell>{i + 1}</TableCell><TableCell className="font-medium">{r.name}</TableCell><TableCell className="text-right">{r.won}</TableCell>
                <TableCell className="text-right">{naira(r.won_value)}</TableCell><TableCell className="text-right">{r.leads_added}</TableCell><TableCell className="text-right">{r.activities}</TableCell>
                <TableCell className="text-right">{r.lost}</TableCell><TableCell className="text-right">{naira(r.open_value)}</TableCell></TableRow>))}</TableBody></Table>)}
      </CardContent></Card>
    </div>
  );
}

// ---------------------------------------------------------------------------

function AskAce() {
  const [qText, setQ] = useState("");
  const [answers, setAnswers] = useState<{ q: string; a: string }[]>([]);
  const ask = useMutation({
    mutationFn: (text: string) => api.salesCrm.query(text),
    onSuccess: (r: any, text) => { setAnswers([{ q: text, a: r?.answer ?? "" }, ...answers]); setQ(""); },
    onError: (e: any) => toast.error(e?.message),
  });
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Input placeholder="e.g. Which customers haven't ordered in 60 days?" value={qText} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && qText.trim() && ask.mutate(qText.trim())} />
        <Button disabled={!qText.trim() || ask.isPending} onClick={() => ask.mutate(qText.trim())}>{ask.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : "Ask"}</Button>
      </div>
      <div className="flex flex-wrap gap-1">{["Which customers haven't ordered in 60 days?", "Which deals have had no contact this week?", "Who are our top customers this quarter?"].map((s) =>
        <Button key={s} size="sm" variant="outline" className="h-7 text-xs" onClick={() => ask.mutate(s)}>{s}</Button>)}</div>
      {answers.map((x, i) => <Card key={i}><CardContent className="space-y-1 p-3 text-sm"><div className="font-medium">{x.q}</div><div className="whitespace-pre-wrap text-muted-foreground">{x.a}</div></CardContent></Card>)}
    </div>
  );
}

// ---------------------------------------------------------------------------

function BulkMessage({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [channel, setChannel] = useState<"sms" | "email">("sms");
  const [recipients, setRecipients] = useState<Recipient[]>([]);
  const [subject, setSubject] = useState("");
  const [text, setText] = useState("");
  const send = useMutation({
    mutationFn: async () => {
      const job = await api.salesCrm.queueBulkMessage({ channel, message_text: text, subject: subject || undefined,
        recipient_filter: { customer_ids: recipients.filter((r) => r.kind === "customer").map((r) => r.id), supplier_ids: recipients.filter((r) => r.kind === "supplier").map((r) => r.id) } });
      const id = job?.id ?? job?.data?.id;
      if (!id) throw new Error("The message was queued but not sent");
      return api.salesCrm.dispatchBulkMessage(id);
    },
    onSuccess: (r: any) => { toast.success(`Sent to ${r?.sent ?? 0}${r?.failed ? `, ${r.failed} failed` : ""}`); setText(""); setRecipients([]); onClose(); },
    onError: (e: any) => toast.error(e?.message),
  });
  return (
    <DetailSheet open={open} onOpenChange={(o) => !o && onClose()} title="Message customers" description="SMS or email to the customers you pick."
                 footer={<Button className="w-full" disabled={!text.trim() || recipients.length === 0 || send.isPending} onClick={() => send.mutate()}>
                   {send.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Send to {recipients.length}</Button>}>
      <Select value={channel} onValueChange={(v) => setChannel(v as any)}><SelectTrigger><SelectValue /></SelectTrigger>
        <SelectContent><SelectItem value="sms">SMS</SelectItem><SelectItem value="email">Email</SelectItem></SelectContent></Select>
      <RecipientPicker value={recipients} onChange={setRecipients} channel={channel} />
      {channel === "email" && <Input placeholder="Subject" value={subject} onChange={(e) => setSubject(e.target.value)} />}
      <Textarea rows={5} placeholder="Message" value={text} onChange={(e) => setText(e.target.value)} />
    </DetailSheet>
  );
}
