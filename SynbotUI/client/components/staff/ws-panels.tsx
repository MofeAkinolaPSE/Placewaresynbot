/**
 * The Staff Workspace tabs. Metrics here are about the person, from what they did:
 * add a task and complete it, and Progress moves; clock out, and the hours land in HR.
 */
import { createContext, ReactNode, useContext, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  AlarmClock, AlertTriangle, ArrowUpRight, Bell, CalendarDays, CheckCheck, CheckCircle2, ClipboardList, Clock, HandHelping,
  Hourglass, Inbox, ListChecks, Loader2, MessageSquare, Search, Sparkles, StickyNote, Users,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { api } from "@/lib/api-client";
import {
  ago, ChatPane, ClockCard, Dict, Dot, Empty, fmtDur, hhmm, NewTaskDefaults, PRESENCE, QuickAdd, RequestDefaults, RequestRow, Section, TaskRow,
  when, useWsRefresh,
} from "./ws-kit";

export type WsActions = {
  openTask: (id: string) => void;
  newTask: (d?: NewTaskDefaults) => void;
  ask: (d?: RequestDefaults) => void;
  openRequest: (id: string) => void;
  chat: (withId: string, name?: string) => void;
  goto: (tab: string) => void;
};
export const WsCtx = createContext<WsActions>(null as any);
const useWs = () => useContext(WsCtx);

function useComplete() {
  const refresh = useWsRefresh();
  return async (id: string) => {
    try { await api.workspace.setStatus(id, "completed"); toast.success("Done"); refresh(); }
    catch (e: any) { toast.error(e?.message || "Could not complete"); }
  };
}

const LEVEL_TONE: Record<string, string> = {
  critical: "text-red-600", action: "text-orange-500", info: "text-sky-500", social: "text-violet-500",
};

// ── My Day ──────────────────────────────────────────────────────────────────

export function DayPanel({ day, prefs }: { day: Dict; prefs: Dict }) {
  const ws = useWs();
  const complete = useComplete();
  const refresh = useWsRefresh();
  const c = day.counts;
  const openNotification = (n: Dict) => {
    api.workspace.markRead([n.id]).then(refresh);
    if (n.link_type === "task") ws.openTask(n.link_id);
    else if (n.link_type === "request") ws.openRequest(n.link_id);
    else if (n.link_type === "message") ws.chat(n.link_id);
  };
  return (
    <div className="space-y-4">
      <ClockCard name={day.me?.name} department={day.me?.department} />
      <QuickAdd onMore={(d) => ws.newTask(d)} />
      <KpiStrip items={[
        { label: "My open tasks", value: c.open, icon: ListChecks, tone: c.done_today ? "success" : "default",
          sub: [c.in_progress ? `${c.in_progress} in progress` : "", c.done_today ? `${c.done_today} done today` : ""].filter(Boolean).join(" · ") || undefined,
          onClick: () => ws.goto("work") },
        { label: "Due today", value: c.due_today, icon: CalendarDays, tone: c.overdue ? "danger" : c.due_today ? "warning" : "default",
          sub: c.overdue ? `${c.overdue} overdue` : undefined, onClick: () => ws.goto("work") },
        { label: "Waiting on others", value: c.waiting, icon: Hourglass, onClick: () => ws.goto("work") },
        { label: "To answer", value: c.to_answer, icon: HandHelping, tone: c.to_answer ? "warning" : "default",
          sub: c.unread ? `${c.unread} unread in inbox` : undefined, onClick: () => ws.goto("inbox") },
      ]} />

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Section title="Today" action={<Button size="sm" variant="outline" onClick={() => ws.newTask()}>+ Add</Button>}>
            {day.timeline.length === 0 ? (
              <Empty>Nothing dated for today. Add a task, a reminder or a quick note - e.g. “reorder coming in from Vaccines Place”.</Empty>
            ) : (
              <ol className="space-y-2">
                {day.timeline.map((i: Dict) => (
                  <li key={(i.task?.id ?? i.event?.id)} className="flex gap-3">
                    <span className={`w-12 shrink-0 pt-2.5 text-right text-xs tabular-nums ${i.task?.overdue ? "text-red-600" : "text-muted-foreground"}`}>
                      {i.task?.overdue ? "late" : hhmm(i.at)}
                    </span>
                    <div className="flex-1">
                      {i.type === "task" ? <TaskRow t={i.task} onOpen={() => ws.openTask(i.task.id)} onDone={() => complete(i.task.id)} /> : (
                        <div className="rounded-lg border border-dashed px-3 py-2 text-sm">
                          <CalendarDays className="mr-1.5 inline h-3.5 w-3.5 text-muted-foreground" />{i.event.title}
                          <span className="ml-2 text-xs text-muted-foreground">{i.event.location}</span>
                        </div>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </Section>

          {day.no_date.length > 0 && (
            <Section title="On my list (no date)">
              <div className="space-y-1.5">{day.no_date.map((t: Dict) => <TaskRow key={t.id} t={t} onOpen={() => ws.openTask(t.id)} onDone={() => complete(t.id)} />)}</div>
            </Section>
          )}

          {prefs.show_operational !== false && <OperationalSection sig={day.operational} />}

          {day.upcoming.length > 0 && (
            <Section title="Coming up">
              <div className="space-y-1.5">{day.upcoming.map((t: Dict) => <TaskRow key={t.id} t={t} onOpen={() => ws.openTask(t.id)} />)}</div>
            </Section>
          )}
        </div>

        <div className="space-y-4">
          <Section title={<span className="flex items-center gap-1.5"><Bell className="h-4 w-4" />Needs attention</span>}
            action={day.attention.length > 0 ? <button className="text-xs text-primary hover:underline" onClick={() => ws.goto("inbox")}>Inbox</button> : undefined}>
            {day.to_answer.length === 0 && day.attention.length === 0 ? <Empty>You're all caught up.</Empty> : (
              <div className="space-y-2">
                {day.to_answer.map((r: Dict) => <RequestRow key={r.id} r={r} incoming onOpen={() => ws.openRequest(r.id)} />)}
                {day.attention.map((n: Dict) => (
                  <button key={n.id} onClick={() => openNotification(n)} className="flex w-full gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-muted/60">
                    <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full bg-current ${LEVEL_TONE[n.level]}`} />
                    <span className="min-w-0"><span className="block truncate text-sm">{n.title}</span><span className="text-[11px] text-muted-foreground">{ago(n.created_at)}</span></span>
                  </button>
                ))}
              </div>
            )}
          </Section>

          <Section title={<span className="flex items-center gap-1.5"><Hourglass className="h-4 w-4" />Waiting on others</span>}>
            {day.waiting_on_others.length === 0 && day.answered.length === 0 ? <Empty>Nothing pending with colleagues.</Empty> : (
              <div className="space-y-1.5">
                {day.answered.map((r: Dict) => <RequestRow key={r.id} r={r} onOpen={() => ws.openRequest(r.id)} />)}
                {day.waiting_on_others.map((r: Dict) => <RequestRow key={r.id} r={r} onOpen={() => ws.openRequest(r.id)} />)}
              </div>
            )}
          </Section>

          {prefs.show_journal !== false && (
            <Section title="My day so far">
              {day.journal.length === 0 ? <Empty>Your activity today will show here.</Empty> : (
                <ol className="space-y-1.5 text-xs">
                  {day.journal.map((j: Dict, i: number) => (
                    <li key={i} className="flex gap-2"><span className="w-10 shrink-0 tabular-nums text-muted-foreground">{hhmm(j.occurred_at)}</span><span>{j.summary}</span></li>
                  ))}
                </ol>
              )}
            </Section>
          )}
        </div>
      </div>
    </div>
  );
}

function OperationalSection({ sig }: { sig: Dict }) {
  const ws = useWs();
  const refresh = useWsRefresh();
  const [busy, setBusy] = useState("");
  const [open, setOpen] = useState<Record<string, boolean>>({});
  if (!sig?.groups?.length) return null;
  const take = async (rule: string, id: string) => {
    setBusy(`${rule}|${id}`);
    try { const t = await api.workspace.take(rule, id); toast.success("Added to your tasks"); refresh(); ws.openTask(t.id); }
    catch (e: any) { toast.error(e?.message || "Could not take it"); } finally { setBusy(""); }
  };
  return (
    <Section title={<span className="flex items-center gap-1.5"><Sparkles className="h-4 w-4 text-primary" />For your role, from the system</span>}>
      <p className="-mt-1 mb-3 text-xs text-muted-foreground">Live items that need a person. Take one to put it on your list - it closes itself once it's dealt with in its module.</p>
      <div className="space-y-2">
        {sig.groups.map((g: Dict) => {
          const expanded = open[g.key] ?? g.count <= 3;
          return (
            <div key={g.key} className="rounded-lg border">
              <button onClick={() => setOpen((o) => ({ ...o, [g.key]: !expanded }))} className="flex w-full items-center justify-between px-3 py-2 text-left">
                <span className="flex items-center gap-2 text-sm font-medium">
                  {g.level === "critical" ? <AlertTriangle className="h-4 w-4 text-red-600" /> : <ClipboardList className="h-4 w-4 text-muted-foreground" />}
                  {g.label}
                </span>
                <span className="flex items-center gap-2 text-xs">
                  {g.overdue > 0 && <Badge variant="destructive" className="h-5 px-1.5">{g.overdue} late</Badge>}
                  <Badge variant="secondary" className="h-5 px-1.5">{g.count}</Badge>
                </span>
              </button>
              {expanded && (
                <div className="space-y-1 border-t px-2 py-2">
                  {g.items.slice(0, 8).map((i: Dict) => (
                    <div key={i.id} className="flex items-center gap-2 rounded-md px-1.5 py-1 text-sm hover:bg-muted/40">
                      <div className="min-w-0 flex-1">
                        <div className="truncate">{i.title}</div>
                        <div className="truncate text-[11px] text-muted-foreground">
                          {i.overdue && i.due ? <span className="text-red-600">due {i.due} · </span> : i.due ? `due ${i.due} · ` : ""}{i.detail}
                        </div>
                      </div>
                      {i.link && <Link to={i.link} className="shrink-0 text-muted-foreground hover:text-primary" title="Open"><ArrowUpRight className="h-4 w-4" /></Link>}
                      {i.task_id ? (
                        <button className="shrink-0 text-[11px] text-muted-foreground hover:underline" onClick={() => ws.openTask(i.task_id)}>
                          {i.taken_by_name === "you" ? "On your list" : `Taken by ${i.taken_by_name}`}
                        </button>
                      ) : (
                        <Button size="sm" variant="outline" className="h-7 shrink-0 px-2 text-xs" disabled={busy === `${g.key}|${i.id}`} onClick={() => take(g.key, i.id)}>
                          {busy === `${g.key}|${i.id}` ? <Loader2 className="h-3 w-3 animate-spin" /> : "Take it"}
                        </Button>
                      )}
                    </div>
                  ))}
                  {g.items.length > 8 && <div className="px-1.5 text-[11px] text-muted-foreground">+ {g.items.length - 8} more in {g.items[0]?.link ? <Link className="text-primary hover:underline" to={g.items[0].link}>the module</Link> : "the module"}</div>}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Section>
  );
}

// ── My Work ─────────────────────────────────────────────────────────────────

const WORK_FILTERS: [string, string][] = [["all", "All open"], ["today", "Today"], ["upcoming", "Upcoming"], ["nodate", "No date"],
  ["waiting", "Waiting"], ["notes", "Notes & reminders"], ["done", "Done"], ["given", "Given to others"]];

export function WorkPanel({ prefs }: { prefs: Dict }) {
  const ws = useWs();
  const complete = useComplete();
  const q = useQuery({ queryKey: ["ws", "tasks"], queryFn: () => api.workspace.tasks() });
  const [flt, setFlt] = useState("all");
  const [order, setOrder] = useState<string>(prefs.task_order ?? "due");
  const [search, setSearch] = useState("");
  const data = q.data ?? { open: [], completed: [], delegated: [] };
  const rows = useMemo(() => {
    const open: Dict[] = data.open;
    const tomorrow = new Date(); tomorrow.setHours(24, 0, 0, 0);
    let r: Dict[] = {
      all: open, today: open.filter((t) => t.overdue || t.due_today || t.status === "in_progress"),
      upcoming: open.filter((t) => t.when && new Date(t.when) >= tomorrow), nodate: open.filter((t) => !t.when),
      waiting: open.filter((t) => t.status === "waiting"), notes: open.filter((t) => t.kind !== "task"),
      done: data.completed, given: data.delegated,
    }[flt] ?? open;
    if (search.trim()) r = r.filter((t) => `${t.title} ${t.description ?? ""}`.toLowerCase().includes(search.toLowerCase()));
    const pr: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
    if (flt !== "done") r = [...r].sort((a, b) => order === "priority"
      ? (pr[a.priority] - pr[b.priority]) || String(a.when ?? "9").localeCompare(String(b.when ?? "9"))
      : String(a.when ?? "9").localeCompare(String(b.when ?? "9")) || (pr[a.priority] - pr[b.priority]));
    return r;
  }, [data, flt, order, search]);
  const count = (k: string) => ({ all: data.open.length, done: data.completed.length, given: data.delegated.length } as Dict)[k];
  return (
    <div className="space-y-3">
      <QuickAdd onMore={(d) => ws.newTask(d)} />
      <div className="flex flex-wrap items-center gap-2">
        {WORK_FILTERS.map(([k, l]) => (
          <button key={k} onClick={() => setFlt(k)} className={`rounded-full border px-3 py-1 text-xs ${flt === k ? "border-primary bg-primary/10 font-medium text-primary" : "hover:bg-muted"}`}>
            {l}{count(k) !== undefined ? ` · ${count(k)}` : ""}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2">
          <div className="relative"><Search className="absolute left-2 top-2 h-4 w-4 text-muted-foreground" /><Input className="h-8 w-44 pl-7" placeholder="Search" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
          <select value={order} onChange={(e) => setOrder(e.target.value)} className="h-8 rounded-md border bg-background px-2 text-xs">
            <option value="due">By due date</option><option value="priority">By priority</option>
          </select>
          <Button size="sm" onClick={() => ws.newTask()}>+ New</Button>
        </div>
      </div>
      {q.isLoading ? <Loader2 className="mx-auto h-5 w-5 animate-spin" /> : rows.length === 0 ? (
        <Empty>{flt === "done" ? "Nothing completed in the last 30 days yet." : flt === "given" ? "You haven't given anyone a task." : "Nothing here. Add what's on your mind - it becomes your partner for the day."}</Empty>
      ) : (
        <div className="space-y-1.5">
          {rows.map((t) => <TaskRow key={t.id} t={t} showOwner={flt === "given"} onOpen={() => ws.openTask(t.id)}
            onDone={flt !== "given" && flt !== "done" ? () => complete(t.id) : undefined} />)}
        </div>
      )}
    </div>
  );
}

// ── Inbox ───────────────────────────────────────────────────────────────────

const INBOX_FILTERS: [string, string][] = [["all", "All"], ["action", "Action required"], ["requests", "Requests"], ["mentions", "Mentions & comments"], ["updates", "Updates"]];

export function InboxPanel() {
  const ws = useWs();
  const refresh = useWsRefresh();
  const [flt, setFlt] = useState("all");
  const n = useQuery({ queryKey: ["ws", "inbox", flt], queryFn: () => api.workspace.inbox(flt) });
  const r = useQuery({ queryKey: ["ws", "requests"], queryFn: () => api.workspace.requests() });
  const counts = n.data?.counts ?? {};
  const open = (x: Dict) => {
    if (!x.read_at) api.workspace.markRead([x.id]).then(refresh);
    if (x.link_type === "task") ws.openTask(x.link_id);
    else if (x.link_type === "request") ws.openRequest(x.link_id);
    else if (x.link_type === "message") ws.chat(x.link_id);
  };
  const incoming: Dict[] = r.data?.incoming ?? [];
  const outgoing: Dict[] = r.data?.outgoing ?? [];
  return (
    <div className="grid gap-4 lg:grid-cols-5">
      <div className="space-y-3 lg:col-span-3">
        <div className="flex flex-wrap items-center gap-2">
          {INBOX_FILTERS.map(([k, l]) => (
            <button key={k} onClick={() => setFlt(k)} className={`rounded-full border px-3 py-1 text-xs ${flt === k ? "border-primary bg-primary/10 font-medium text-primary" : "hover:bg-muted"}`}>
              {l}{(k === "all" ? counts.unread : counts[k]) ? ` · ${k === "all" ? counts.unread : counts[k]}` : ""}
            </button>
          ))}
          {counts.unread > 0 && <Button size="sm" variant="ghost" className="ml-auto h-7 text-xs" onClick={() => api.workspace.markRead().then(refresh)}><CheckCheck className="mr-1 h-3.5 w-3.5" />Mark all read</Button>}
        </div>
        {n.isLoading ? <Loader2 className="mx-auto h-5 w-5 animate-spin" /> : (n.data?.items ?? []).length === 0 ? <Empty>Nothing here.</Empty> : (
          <div className="divide-y rounded-xl border bg-card">
            {n.data.items.map((x: Dict) => (
              <button key={x.id} onClick={() => open(x)} className={`flex w-full gap-3 px-3 py-2.5 text-left hover:bg-muted/40 ${x.read_at ? "opacity-70" : ""}`}>
                <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${x.read_at ? "bg-transparent" : "bg-current"} ${LEVEL_TONE[x.level]}`} />
                <span className="min-w-0 flex-1">
                  <span className={`block text-sm ${x.read_at ? "" : "font-medium"}`}>{x.title}</span>
                  {x.body && <span className="block truncate text-xs text-muted-foreground">“{x.body}”</span>}
                  <span className="text-[11px] text-muted-foreground">{x.actor_name} · {ago(x.created_at)}</span>
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="space-y-4 lg:col-span-2">
        <Section title={`Asked of me${incoming.filter((x) => x.mine_to_answer).length ? ` · ${incoming.filter((x) => x.mine_to_answer).length} open` : ""}`}>
          {incoming.length === 0 ? <Empty>No requests to you or your team.</Empty> :
            <div className="space-y-1.5">{incoming.map((x) => <RequestRow key={x.id} r={x} incoming onOpen={() => ws.openRequest(x.id)} />)}</div>}
        </Section>
        <Section title="My requests" action={<Button size="sm" variant="outline" onClick={() => ws.ask()}>+ Ask</Button>}>
          {outgoing.length === 0 ? <Empty>Ask a colleague or a team for information or work - it's tracked until they answer.</Empty> :
            <div className="space-y-1.5">{outgoing.map((x) => <RequestRow key={x.id} r={x} onOpen={() => ws.openRequest(x.id)} />)}</div>}
        </Section>
      </div>
    </div>
  );
}

// ── Messages ────────────────────────────────────────────────────────────────

export function MessagesPanel({ initial }: { initial?: string | null }) {
  const c = useQuery({ queryKey: ["ws", "conversations"], queryFn: () => api.workspace.conversations(), refetchInterval: 30_000 });
  const team = useQuery({ queryKey: ["ws", "team"], queryFn: () => api.workspace.team(), staleTime: 30_000 });
  const [sel, setSel] = useState<string>(initial || "team");
  const convs: Dict[] = c.data?.conversations ?? [];
  const known = new Set(convs.map((x) => x.with));
  const others: Dict[] = (team.data?.people ?? []).filter((p: Dict) => !p.me && !known.has(p.user_id));
  const selName = convs.find((x) => x.with === sel)?.name ?? (team.data?.people ?? []).find((p: Dict) => p.user_id === sel)?.name ?? "Whole team";
  return (
    <div className="grid overflow-hidden rounded-xl border bg-card md:grid-cols-3" style={{ minHeight: 520 }}>
      <div className="border-b md:border-b-0 md:border-r">
        <div className="max-h-[520px] overflow-y-auto">
          {convs.map((x) => (
            <button key={x.id} onClick={() => setSel(x.with)} className={`flex w-full items-center gap-2 border-b px-3 py-2.5 text-left ${sel === x.with ? "bg-primary/5" : "hover:bg-muted/40"}`}>
              {x.with === "team" ? <Users className="h-4 w-4 text-muted-foreground" /> : <Dot status={x.online ? "online" : "offline"} />}
              <span className="min-w-0 flex-1">
                <span className="flex justify-between gap-2 text-sm font-medium"><span className="truncate">{x.name}</span>{x.unread > 0 && <Badge className="h-5 px-1.5">{x.unread}</Badge>}</span>
                <span className="block truncate text-[11px] text-muted-foreground">{x.last_message ? `${x.last_sender ? x.last_sender.split(" ")[0] + ": " : ""}${x.last_message}` : "No messages yet"}</span>
              </span>
            </button>
          ))}
          {others.length > 0 && <div className="px-3 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Start a conversation</div>}
          {others.map((p) => (
            <button key={p.user_id} onClick={() => setSel(p.user_id)} className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm ${sel === p.user_id ? "bg-primary/5" : "hover:bg-muted/40"}`}>
              <Dot status={p.status} /><span className="truncate">{p.name}</span><span className="ml-auto text-[11px] text-muted-foreground">{p.department}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="md:col-span-2"><ChatPane key={sel} withId={sel} title={selName} /></div>
    </div>
  );
}

// ── Team ────────────────────────────────────────────────────────────────────

export function TeamPanel() {
  const ws = useWs();
  const q = useQuery({ queryKey: ["ws", "team"], queryFn: () => api.workspace.team(), refetchInterval: 60_000 });
  const [dept, setDept] = useState("");
  const [search, setSearch] = useState("");
  const people: Dict[] = (q.data?.people ?? []).filter((p: Dict) => (!dept || p.department === dept) &&
    (!search || `${p.name} ${p.job_title ?? ""} ${p.department}`.toLowerCase().includes(search.toLowerCase())));
  const maxLoad = Math.max(5, ...people.map((p) => p.open_tasks));
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground">{q.data?.working ?? 0} at work now · {q.data?.online ?? 0} online</span>
        <div className="ml-auto flex gap-2">
          <select value={dept} onChange={(e) => setDept(e.target.value)} className="h-8 rounded-md border bg-background px-2 text-xs">
            <option value="">All teams</option>{(q.data?.departments ?? []).map((d: string) => <option key={d}>{d}</option>)}
          </select>
          <Input className="h-8 w-44" placeholder="Find someone" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
      </div>
      {q.isLoading ? <Loader2 className="mx-auto h-5 w-5 animate-spin" /> : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {people.map((p) => (
            <div key={p.user_id} className="rounded-xl border bg-card p-4">
              <div className="flex items-start gap-3">
                <div className="relative">
                  <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/10 text-sm font-semibold text-primary">
                    {p.name.split(" ").map((s: string) => s[0]).slice(0, 2).join("").toUpperCase()}
                  </div>
                  <span className="absolute -bottom-0.5 -right-0.5 rounded-full border-2 border-card"><Dot status={p.status} /></span>
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium">{p.name}{p.me && <span className="ml-1 text-xs text-muted-foreground">(you)</span>}</div>
                  <div className="truncate text-xs text-muted-foreground">{p.job_title ? `${p.job_title} · ` : ""}{p.department}</div>
                  <div className="mt-0.5 text-[11px]">{PRESENCE[p.status]?.label}{p.clocked_in_at ? ` since ${hhmm(p.clocked_in_at)}` : ""}</div>
                </div>
              </div>
              <div className="mt-3 space-y-1">
                <div className="flex justify-between text-[11px] text-muted-foreground"><span>{p.open_tasks} active{p.waiting ? ` · ${p.waiting} waiting` : ""}</span><span>{p.done_this_week} done this week · {p.hours_week}h</span></div>
                <div className="h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary/60" style={{ width: `${Math.min(100, (p.open_tasks / maxLoad) * 100)}%` }} /></div>
              </div>
              {!p.me && (
                <div className="mt-3 grid grid-cols-3 gap-1.5">
                  <Button size="sm" variant="outline" className="h-8 text-xs" onClick={() => ws.chat(p.user_id, p.name)}><MessageSquare className="mr-1 h-3.5 w-3.5" />Message</Button>
                  <Button size="sm" variant="outline" className="h-8 text-xs" onClick={() => ws.ask({ to_user: p.user_id })}><HandHelping className="mr-1 h-3.5 w-3.5" />Ask</Button>
                  <Button size="sm" variant="outline" className="h-8 text-xs" onClick={() => ws.newTask({ assigned_to: p.user_id })}><ListChecks className="mr-1 h-3.5 w-3.5" />Give task</Button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      <p className="text-[11px] text-muted-foreground">Workload shows who has capacity to help - it is not a score.</p>
    </div>
  );
}

// ── Progress ────────────────────────────────────────────────────────────────

export function ProgressPanel() {
  const [range, setRange] = useState("week");
  const [jr, setJr] = useState("week");
  const p = useQuery({ queryKey: ["ws", "progress", range], queryFn: () => api.workspace.progress(range) });
  const j = useQuery({ queryKey: ["ws", "journal", jr], queryFn: () => api.workspace.journal(jr) });
  const t = useQuery({ queryKey: ["ws", "time"], queryFn: () => api.workspace.time() });
  const d = p.data;
  const delta = d ? d.completed - d.completed_prev : 0;
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">Your work, over time - from what you completed, answered and clocked.</p>
        <div className="flex gap-1 rounded-lg bg-muted p-1">
          {[["week", "This week"], ["month", "This month"]].map(([k, l]) => (
            <button key={k} onClick={() => setRange(k)} className={`rounded-md px-3 py-1 text-xs ${range === k ? "bg-background font-medium shadow-sm" : "text-muted-foreground"}`}>{l}</button>
          ))}
        </div>
      </div>
      {!d ? <Loader2 className="mx-auto h-5 w-5 animate-spin" /> : (
        <>
          <KpiStrip items={[
            { label: "Tasks completed", value: d.completed, icon: CheckCircle2, tone: d.completed ? "success" : "default",
              sub: `${delta >= 0 ? "+" : ""}${delta} vs last ${range} · ${d.open} open${d.waiting ? `, ${d.waiting} waiting` : ""}` },
            { label: "On time", value: d.on_time_pct === null ? "—" : `${d.on_time_pct}%`, icon: Clock, sub: d.with_due ? `of ${d.with_due} with a due date` : "no dated tasks yet" },
            { label: "Requests answered", value: d.requests_answered, icon: HandHelping, sub: d.avg_answer_hours !== null ? `avg ${d.avg_answer_hours}h to answer` : undefined },
            { label: "Hours worked", value: `${d.hours}h`, icon: AlarmClock, sub: "saved + running clock" },
          ]} />
          <div className="grid gap-4 lg:grid-cols-3">
            <Section title="Completed and hours, by day" className="lg:col-span-2">
              <div className="h-56">
                <ResponsiveContainer>
                  <BarChart data={d.days.map((x: Dict) => ({ ...x, label: new Date(x.date).toLocaleDateString("en-GB", range === "week" ? { weekday: "short" } : { day: "numeric" }) }))}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} className="stroke-muted" />
                    <XAxis dataKey="label" fontSize={11} tickLine={false} axisLine={false} />
                    <YAxis yAxisId="l" fontSize={11} tickLine={false} axisLine={false} allowDecimals={false} width={28} />
                    <YAxis yAxisId="r" orientation="right" fontSize={11} tickLine={false} axisLine={false} width={32} unit="h" />
                    <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                    <Bar yAxisId="l" dataKey="completed" name="Completed" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
                    <Bar yAxisId="r" dataKey="hours" name="Hours" fill="hsl(var(--primary) / 0.3)" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Section>
            <Section title="What I worked on">
              {d.by_department.length === 0 ? <Empty>Complete a task to see the split.</Empty> : (
                <div className="space-y-2">
                  {d.by_department.map((x: Dict) => (
                    <div key={x.name} className="text-xs">
                      <div className="flex justify-between"><span>{x.name}</span><span className="text-muted-foreground">{Math.round((100 * x.count) / d.completed)}%</span></div>
                      <div className="mt-0.5 h-1.5 rounded-full bg-muted"><div className="h-full rounded-full bg-primary" style={{ width: `${(100 * x.count) / d.completed}%` }} /></div>
                    </div>
                  ))}
                  <div className="pt-2 text-[11px] text-muted-foreground">{d.by_source.map((x: Dict) => `${x.name}: ${x.count}`).join(" · ")}</div>
                </div>
              )}
            </Section>
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <Section title="Accomplishments">
              {d.accomplishments.length === 0 ? <Empty>Nothing completed in this period yet.</Empty> : (
                <ul className="space-y-1.5 text-sm">{d.accomplishments.map((a: Dict) => <li key={a.id} className="flex gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" /><span>{a.title}</span></li>)}</ul>
              )}
            </Section>
            <Section title="Work journal" action={
              <select value={jr} onChange={(e) => setJr(e.target.value)} className="h-7 rounded-md border bg-background px-1.5 text-xs">
                <option value="today">Today</option><option value="week">This week</option><option value="month">This month</option>
              </select>}>
              {(j.data ?? []).length === 0 ? <Empty>No activity recorded.</Empty> : (
                <ol className="max-h-72 space-y-1.5 overflow-y-auto text-xs">
                  {(j.data ?? []).map((x: Dict) => <li key={x.id} className="flex gap-2"><span className="w-20 shrink-0 text-muted-foreground">{when(x.occurred_at)}</span><span>{x.summary}</span></li>)}
                </ol>
              )}
            </Section>
            <Section title="My timesheet">
              {!t.data ? <Loader2 className="mx-auto h-4 w-4 animate-spin" /> : (
                <div className="space-y-3">
                  <div className="grid grid-cols-7 gap-1 text-center text-[10px]">
                    {t.data.days.map((x: Dict) => (
                      <div key={x.date} className={`rounded-md py-1 ${x.today ? "bg-primary/10 font-semibold text-primary" : "bg-muted/50"}`}>
                        <div>{new Date(x.date).toLocaleDateString("en-GB", { weekday: "narrow" })}</div><div>{x.hours ? x.hours.toFixed(1) : "–"}</div>
                      </div>
                    ))}
                  </div>
                  <div className="max-h-48 space-y-1 overflow-y-auto">
                    {t.data.entries.length === 0 ? <p className="text-xs text-muted-foreground">Clock in and out to build your timesheet.</p> :
                      t.data.entries.slice(0, 12).map((e: Dict) => (
                        <div key={e.id} className="flex items-center justify-between gap-2 text-xs">
                          <span>{new Date(e.date).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}</span>
                          <span className="font-medium">{Number(e.hours_worked).toFixed(2)}h</span>
                          <Badge variant="outline" className={`h-5 px-1.5 text-[10px] ${e.status === "approved" ? "border-emerald-500 text-emerald-600" : e.status === "rejected" ? "border-red-500 text-red-600" : ""}`}
                            title={e.review_note ?? undefined}>{e.status === "submitted" ? "with HR" : e.status}</Badge>
                        </div>
                      ))}
                  </div>
                  <div className="text-[11px] text-muted-foreground">Last 5 weeks: {t.data.weeks.map((w: Dict) => `${w.hours}h`).join(" · ")}</div>
                </div>
              )}
            </Section>
          </div>
        </>
      )}
    </div>
  );
}

export function Hint({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-dashed bg-muted/30 px-3 py-2 text-xs text-muted-foreground">{children}</div>;
}

export { Inbox, StickyNote, fmtDur };
