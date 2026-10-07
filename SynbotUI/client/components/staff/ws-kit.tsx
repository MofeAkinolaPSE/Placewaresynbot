/**
 * Staff Workspace shared pieces: the work clock (top-bar pill + card), the task panel,
 * new task / reminder / note, requests, chat and the people picker. Every action is
 * completed where it appears - nothing sends you to another page to finish it.
 */
import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlarmClock, ArrowUpRight, CheckCircle2, CircleDot, Clock, Coffee, HandHelping, Hourglass, ListChecks, Loader2,
  MessageSquare, Pause, Play, Plus, Send, Square, StickyNote, Undo2, UserRound, XCircle, Repeat, Flame, Sparkles, CornerDownLeft,
  SlidersHorizontal, ShieldAlert, Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { api } from "@/lib/api-client";
import { authClient } from "@/lib/auth-client";

export type Dict = Record<string, any>;
export const DEPARTMENTS = ["Finance", "Sales", "Frontdesk", "Operations", "Procurement", "Logistics", "Quality", "HR", "Management", "Admin"];

// ── helpers ─────────────────────────────────────────────────────────────────

export function myId(): string | null {
  try {
    const t = authClient.getAccessToken();
    if (!t) return null;
    return JSON.parse(atob(t.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))).sub ?? null;
  } catch { return null; }
}

export const fmtDur = (sec: number) => {
  const m = Math.max(0, Math.round(sec / 60));
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
};
export const fmtClock = (sec: number) => {
  const s = Math.max(0, Math.floor(sec));
  return [Math.floor(s / 3600), Math.floor((s % 3600) / 60), s % 60].map((n) => String(n).padStart(2, "0")).join(":");
};
export const hhmm = (v?: string | null) => (v ? new Date(v).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : "");
export const when = (v?: string | null) => {
  if (!v) return "";
  const d = new Date(v);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const day = new Date(d); day.setHours(0, 0, 0, 0);
  const diff = Math.round((day.getTime() - today.getTime()) / 86400000);
  const t = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  if (diff === 0) return `Today ${t}`;
  if (diff === 1) return `Tomorrow ${t}`;
  if (diff === -1) return `Yesterday ${t}`;
  if (diff > 1 && diff < 7) return `${d.toLocaleDateString("en-GB", { weekday: "short" })} ${t}`;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }) + ` ${t}`;
};
export const ago = (v?: string | null) => {
  if (!v) return "";
  const s = (Date.now() - new Date(v).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(v).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
};
/** value for <input type="datetime-local"> n days from now at hour h */
export const at = (days: number, h: number, m = 0) => {
  const d = new Date(); d.setDate(d.getDate() + days); d.setHours(h, m, 0, 0);
  return toLocalInput(d);
};
export const toLocalInput = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
const fromLocalInput = (v: string) => (v ? new Date(v).toISOString() : null);

export const PRIORITY_DOT: Record<string, string> = {
  critical: "bg-red-500", high: "bg-orange-500", medium: "bg-amber-400", low: "bg-slate-400",
};
export const STATUS_LABEL: Record<string, string> = {
  pending: "To do", in_progress: "In progress", waiting: "Waiting", completed: "Done", cancelled: "Cancelled", blocked: "Blocked",
};
const STATUS_TONE: Record<string, string> = {
  pending: "bg-muted text-foreground", in_progress: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300",
  waiting: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300",
  completed: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300", cancelled: "bg-muted text-muted-foreground",
};
export const KIND_ICON: Record<string, any> = { task: ListChecks, reminder: AlarmClock, note: StickyNote };
export const PRESENCE: Record<string, { dot: string; label: string }> = {
  working: { dot: "bg-emerald-500", label: "Working" }, on_break: { dot: "bg-amber-400", label: "On break" },
  online: { dot: "bg-sky-400", label: "Online" }, offline: { dot: "bg-slate-300 dark:bg-slate-600", label: "Offline" },
  inactive: { dot: "bg-slate-200", label: "Deactivated" },
};
export const SOURCE_LABEL: Record<string, string> = {
  operational: "Operational", request: "Request", assigned: "Given to you", manual: "", chat: "From chat", workflow: "Workflow",
};

export function StatusChip({ status }: { status: string }) {
  return <span className={`inline-flex rounded-md px-1.5 py-0.5 text-[11px] font-medium ${STATUS_TONE[status] ?? "bg-muted"}`}>{STATUS_LABEL[status] ?? status}</span>;
}

export function Dot({ status }: { status: string }) {
  return <span className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${PRESENCE[status]?.dot ?? "bg-slate-300"}`} title={PRESENCE[status]?.label} />;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-lg border border-dashed px-3 py-6 text-center text-sm text-muted-foreground">{children}</p>;
}

export function Section({ title, action, children, className = "" }: { title: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border bg-card p-4 ${className}`}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  );
}

// ── live refresh ────────────────────────────────────────────────────────────

/** Refresh the workspace when anything concerning this person (or the team) changes. */
export function useWorkspaceLive() {
  const qc = useQueryClient();
  const me = myId();
  useRealtimeChannel("workspace_updates", (msg: any) => {
    const users: string[] = msg?.users ?? [];
    if (!users.length || (me && users.includes(me)) || msg?.event === "clock") {
      qc.invalidateQueries({ queryKey: ["ws"] });
    }
    if (msg?.event === "clock") qc.invalidateQueries({ queryKey: ["hr"] });
  });
}

export function useWsRefresh() {
  const qc = useQueryClient();
  return () => { qc.invalidateQueries({ queryKey: ["ws"] }); qc.invalidateQueries({ queryKey: ["hr"] }); };
}

export function useTeam() {
  return useQuery({ queryKey: ["ws", "team"], queryFn: () => api.workspace.team(), staleTime: 30_000 });
}

export function PersonPick({ value, onChange, includeMe = true, placeholder = "Choose person" }:
  { value: string; onChange: (v: string) => void; includeMe?: boolean; placeholder?: string }) {
  const { data } = useTeam();
  const people: Dict[] = (data?.people ?? []).filter((p: Dict) => includeMe || !p.me);
  return (
    <Select value={value || undefined} onValueChange={onChange}>
      <SelectTrigger><SelectValue placeholder={placeholder} /></SelectTrigger>
      <SelectContent>
        {people.map((p) => (
          <SelectItem key={p.user_id} value={p.user_id}>
            {p.me ? "Me" : p.name}{p.department ? ` · ${p.department}` : ""}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

// ── work clock ──────────────────────────────────────────────────────────────

/** Server-side clock state, ticking locally between polls. */
export function useClock() {
  const q = useQuery({ queryKey: ["ws", "time"], queryFn: () => api.workspace.time(), refetchInterval: 60_000 });
  const [, setTick] = useState(0);
  const loadedAt = useRef(Date.now());
  useEffect(() => { loadedAt.current = Date.now(); }, [q.dataUpdatedAt]);
  useEffect(() => {
    if (q.data?.status !== "working") return;
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [q.data?.status]);
  const d = q.data;
  const drift = d?.status === "working" ? (Date.now() - loadedAt.current) / 1000 : 0;
  return {
    ...q,
    status: (d?.status ?? "off") as "off" | "working" | "break",
    worked: (d?.session?.worked_seconds ?? 0) + drift,
    today: (d?.today_seconds ?? 0) + drift,
    week: (d?.week_seconds ?? 0) + drift,
  };
}

function useClockActions() {
  const refresh = useWsRefresh();
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<any>, ok: string) => {
    setBusy(true);
    try { await fn(); toast.success(ok); refresh(); }
    catch (e: any) { toast.error(e?.message || "That did not work"); }
    finally { setBusy(false); }
  };
  return {
    busy,
    start: () => run(() => api.workspace.clockIn({}), "Clocked in - have a good day"),
    pause: () => run(() => api.workspace.takeBreak(), "On a break"),
    resume: () => run(() => api.workspace.resume(), "Welcome back"),
  };
}

export function ClockOutSheet({ open, onOpenChange, startedAt }: { open: boolean; onOpenChange: (v: boolean) => void; startedAt?: string }) {
  const refresh = useWsRefresh();
  const [note, setNote] = useState("");
  const [end, setEnd] = useState("");
  const [needEnd, setNeedEnd] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) { setNote(""); setEnd(""); setNeedEnd(false); } }, [open]);
  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.workspace.clockOut({ note: note.trim() || undefined, ended_at: fromLocalInput(end) || undefined });
      toast.success(r.recorded_hours > 0 ? `Clocked out · ${r.recorded_hours}h saved to your timesheet` : "Clocked out (under a minute, nothing saved)");
      refresh(); onOpenChange(false);
    } catch (e: any) {
      if (e?.code === "needs_end_time") { setNeedEnd(true); toast.message(e.message); }
      else toast.error(e?.message || "Clock-out failed");
    } finally { setBusy(false); }
  };
  return (
    <DetailSheet open={open} onOpenChange={onOpenChange} title="Finish work" icon={Square}
      description={startedAt ? `Started ${when(startedAt)}. Your hours go to your timesheet for HR.` : undefined}
      footer={<Button className="w-full" onClick={submit} disabled={busy || (needEnd && !end)}>{busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Clock out &amp; save</Button>}>
      <div className="space-y-2">
        <Label>What did you work on? (optional)</Label>
        <Textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Received 2 deliveries, counted cold room 2" />
      </div>
      <div className="space-y-2">
        <Label>{needEnd ? "When did you actually finish?" : "Finished earlier? (optional)"}</Label>
        <Input type="datetime-local" value={end} max={toLocalInput(new Date())} onChange={(e) => setEnd(e.target.value)} />
        {needEnd && <p className="text-xs text-amber-600">The clock was left running. Enter your real finish time so the timesheet is right.</p>}
      </div>
    </DetailSheet>
  );
}

/** Compact clock for the top bar - on every page. */
export function ClockPill() {
  const c = useClock();
  const a = useClockActions();
  const [open, setOpen] = useState(false);
  const [out, setOut] = useState(false);
  const s = c.data?.session;
  return (
    <div className="relative">
      <button type="button" onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-lg border border-border/40 bg-muted/30 px-2.5 py-1 hover:bg-muted/60 transition-colors">
        <span className={`h-2 w-2 rounded-full ${c.status === "working" ? "bg-emerald-500 animate-pulse" : c.status === "break" ? "bg-amber-400" : "bg-slate-400"}`} />
        {c.status === "off" ? "Not clocked in" : c.status === "break" ? "On break" : <span className="font-mono tabular-nums text-foreground">{fmtClock(c.worked)}</span>}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-40 mt-1 w-64 rounded-lg border bg-card p-3 shadow-lg">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Work session</div>
            {s ? (
              <dl className="mt-2 grid grid-cols-2 gap-y-1 text-xs">
                <dt className="text-muted-foreground">Started</dt><dd className="text-right">{hhmm(s.started_at)}</dd>
                <dt className="text-muted-foreground">Worked</dt><dd className="text-right font-mono">{fmtClock(c.worked)}</dd>
                <dt className="text-muted-foreground">Breaks</dt><dd className="text-right">{fmtDur(s.break_seconds)}</dd>
                <dt className="text-muted-foreground">This week</dt><dd className="text-right">{fmtDur(c.week)}</dd>
              </dl>
            ) : <p className="mt-2 text-xs text-muted-foreground">This week: {fmtDur(c.week)}</p>}
            <div className="mt-3 grid gap-1.5">
              {c.status === "off" && <Button size="sm" disabled={a.busy} onClick={() => { a.start(); setOpen(false); }}><Play className="mr-1.5 h-3.5 w-3.5" />Start work</Button>}
              {c.status === "working" && <Button size="sm" variant="outline" disabled={a.busy} onClick={() => { a.pause(); setOpen(false); }}><Coffee className="mr-1.5 h-3.5 w-3.5" />Take a break</Button>}
              {c.status === "break" && <Button size="sm" disabled={a.busy} onClick={() => { a.resume(); setOpen(false); }}><Play className="mr-1.5 h-3.5 w-3.5" />Back to work</Button>}
              {c.status !== "off" && <Button size="sm" variant="destructive" onClick={() => { setOut(true); setOpen(false); }}><Square className="mr-1.5 h-3.5 w-3.5" />End work</Button>}
              <Link to="/workspace" onClick={() => setOpen(false)} className="text-center text-[11px] text-primary hover:underline">Open my workspace</Link>
            </div>
          </div>
        </>
      )}
      <ClockOutSheet open={out} onOpenChange={setOut} startedAt={s?.started_at} />
    </div>
  );
}

/** Clock card on My Day. */
export function ClockCard({ name, department }: { name?: string; department?: string }) {
  const c = useClock();
  const a = useClockActions();
  const [out, setOut] = useState(false);
  const s = c.data?.session;
  // Who and which department come from the person's HR profile (User Access ->
  // HR), never a picker: the session and its timesheet are filed under them.
  const who = [name, s?.department || department].filter(Boolean).join(" · ");
  return (
    <div className="flex flex-wrap items-center gap-4 rounded-xl border bg-card p-4">
      <div className="flex items-center gap-3">
        <div className={`flex h-11 w-11 items-center justify-center rounded-full ${c.status === "working" ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15" : c.status === "break" ? "bg-amber-100 text-amber-700 dark:bg-amber-500/15" : "bg-muted text-muted-foreground"}`}>
          {c.status === "break" ? <Coffee className="h-5 w-5" /> : <Clock className="h-5 w-5" />}
        </div>
        <div>
          <div className="text-xs text-muted-foreground">{c.status === "off" ? "Not clocked in" : c.status === "break" ? `On break · started ${hhmm(s?.started_at)}` : `Working since ${hhmm(s?.started_at)}`}</div>
          <div className="font-mono text-2xl font-bold tabular-nums">{fmtClock(c.status === "off" ? c.today : c.worked)}</div>
        </div>
      </div>
      <div className="flex gap-6 text-xs">
        <div><div className="text-muted-foreground">Today</div><div className="font-semibold">{fmtDur(c.today)}</div></div>
        <div><div className="text-muted-foreground">This week</div><div className="font-semibold">{fmtDur(c.week)}</div></div>
        {s && <div><div className="text-muted-foreground">Breaks</div><div className="font-semibold">{fmtDur(s.break_seconds)}</div></div>}
      </div>
      <div className="ml-auto flex flex-wrap items-center gap-2">
        {who && <span className="text-xs text-muted-foreground">{who}</span>}
        {c.status === "off" && <Button disabled={a.busy || c.isLoading} onClick={() => a.start()}><Play className="mr-1.5 h-4 w-4" />Start work</Button>}
        {c.status === "working" && <Button variant="outline" disabled={a.busy} onClick={a.pause}><Pause className="mr-1.5 h-4 w-4" />Break</Button>}
        {c.status === "break" && <Button disabled={a.busy} onClick={a.resume}><Play className="mr-1.5 h-4 w-4" />Resume</Button>}
        {c.status !== "off" && <Button variant="destructive" onClick={() => setOut(true)}><Square className="mr-1.5 h-4 w-4" />End work</Button>}
      </div>
      <ClockOutSheet open={out} onOpenChange={setOut} startedAt={s?.started_at} />
    </div>
  );
}

// ── new task / reminder / note ──────────────────────────────────────────────

export type NewTaskDefaults = {
  kind?: "task" | "reminder" | "note"; assigned_to?: string; title?: string; due?: string; priority?: string;
  recurrence?: string | null; recurrence_until?: string | null; department?: string | null;
};

export const REPEAT_OPTIONS: [string, string][] = [
  ["", "Does not repeat"], ["daily", "Every day"], ["weekdays", "Every weekday (Mon–Fri)"], ["weekly", "Every week"],
  ["every:2:weeks", "Every 2 weeks"], ["monthly", "Every month (same date)"], ["monthly:last", "End of every month"],
];

/** Same wording as the backend (workspace_automation.describe). */
export function repeatLabel(rule?: string | null): string {
  if (!rule) return "";
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], codes = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"];
  const fixed: Record<string, string> = { daily: "every day", weekdays: "every weekday", weekly: "every week", monthly: "every month" };
  if (fixed[rule]) return fixed[rule];
  if (rule.startsWith("weekly:")) return "every " + rule.slice(7).split(",").map((c) => days[codes.indexOf(c)]).join(", ");
  if (rule.startsWith("monthly:")) return rule.slice(8) === "last" ? "end of every month" : `monthly on day ${rule.slice(8)}`;
  const [, n, unit] = rule.split(":");
  return n === "1" ? `every ${unit.slice(0, -1)}` : `every ${n} ${unit}`;
}

export function NewTaskSheet({ open, onOpenChange, defaults }: { open: boolean; onOpenChange: (v: boolean) => void; defaults?: NewTaskDefaults }) {
  const refresh = useWsRefresh();
  const me = myId() ?? "";
  const blank = () => ({ kind: defaults?.kind ?? "task", title: defaults?.title ?? "", description: "", due: defaults?.due ?? "",
    priority: defaults?.priority ?? "medium", assigned_to: defaults?.assigned_to ?? me, department: defaults?.department ?? "", checklist: "",
    recurrence: defaults?.recurrence ?? "", until: defaults?.recurrence_until ?? "" });
  const [f, setF] = useState(blank);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) setF(blank()); }, [open]);  // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k: string, v: string) => setF((p) => ({ ...p, [k]: v }));
  const submit = async () => {
    setBusy(true);
    try {
      await api.workspace.createTask({
        kind: f.kind, title: f.title, description: f.description || undefined, priority: f.priority,
        due_at: fromLocalInput(f.due), assigned_to: f.assigned_to || me, department: f.department || undefined,
        checklist: f.checklist.split("\n").map((s) => s.trim()).filter(Boolean),
        recurrence: f.kind !== "note" && f.recurrence ? f.recurrence : undefined,
        recurrence_until: f.kind !== "note" && f.recurrence && f.until ? f.until : undefined,
      });
      toast.success(f.assigned_to && f.assigned_to !== me ? "Task sent" : f.kind === "reminder" ? "Reminder set" : f.kind === "note" ? "Noted" : "Task added");
      refresh(); onOpenChange(false);
    } catch (e: any) { toast.error(e?.message || "Could not save"); } finally { setBusy(false); }
  };
  const Icon = KIND_ICON[f.kind] ?? ListChecks;
  return (
    <DetailSheet open={open} onOpenChange={onOpenChange} icon={Icon}
      title={f.kind === "reminder" ? "New reminder" : f.kind === "note" ? "New note" : "New task"}
      footer={<Button className="w-full" onClick={submit} disabled={busy || !f.title.trim() || (f.kind === "reminder" && !f.due) || (!!f.recurrence && f.kind !== "note" && !f.due)}>{busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Save</Button>}>
      <div className="flex gap-1 rounded-lg bg-muted p-1">
        {(["task", "reminder", "note"] as const).map((k) => (
          <button key={k} onClick={() => set("kind", k)}
            className={`flex-1 rounded-md px-2 py-1.5 text-xs font-medium capitalize ${f.kind === k ? "bg-background shadow-sm" : "text-muted-foreground"}`}>{k}</button>
        ))}
      </div>
      <div className="space-y-2">
        <Label>{f.kind === "note" ? "Note" : f.kind === "reminder" ? "Remind me to…" : "What needs to be done?"}</Label>
        <Input autoFocus value={f.title} onChange={(e) => set("title", e.target.value)}
          placeholder={f.kind === "note" ? "e.g. Vaccines Place reorder coming in Thursday" : f.kind === "reminder" ? "e.g. Call Skylark about payment" : "e.g. Verify supplier shipment"} />
      </div>
      <div className="space-y-2">
        <Label>Details (optional)</Label>
        <Textarea rows={2} value={f.description} onChange={(e) => set("description", e.target.value)} />
      </div>
      <div className="space-y-2">
        <Label>{f.kind === "reminder" ? "When" : "Due (optional)"}</Label>
        <Input type="datetime-local" value={f.due} onChange={(e) => set("due", e.target.value)} />
        <div className="flex flex-wrap gap-1">
          {[["In 1 hour", () => toLocalInput(new Date(Date.now() + 3600000))], ["Today 5pm", () => at(0, 17)], ["Tomorrow 9am", () => at(1, 9)],
            ["Next week", () => at(7, 9)]].map(([l, fn]: any) => (
            <button key={l} onClick={() => set("due", fn())} className="rounded-md border px-2 py-0.5 text-[11px] hover:bg-muted">{l}</button>
          ))}
          {f.due && <button onClick={() => set("due", "")} className="rounded-md px-2 py-0.5 text-[11px] text-muted-foreground hover:underline">clear</button>}
        </div>
      </div>
      {f.kind !== "note" && (
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label>Repeat</Label>
            <Select value={f.recurrence || "none"} onValueChange={(v) => set("recurrence", v === "none" ? "" : v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {REPEAT_OPTIONS.map(([k, l]) => <SelectItem key={k || "none"} value={k || "none"}>{l}</SelectItem>)}
                {f.recurrence && !REPEAT_OPTIONS.some(([k]) => k === f.recurrence) && <SelectItem value={f.recurrence}>{repeatLabel(f.recurrence)}</SelectItem>}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Until (optional)</Label>
            <Input type="date" disabled={!f.recurrence} value={f.until} onChange={(e) => set("until", e.target.value)} />
          </div>
        </div>
      )}
      {f.kind !== "note" && (
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label>For</Label>
            <PersonPick value={f.assigned_to} onChange={(v) => set("assigned_to", v)} />
          </div>
          <div className="space-y-2">
            <Label>Priority</Label>
            <Select value={f.priority} onValueChange={(v) => set("priority", v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{["low", "medium", "high", "critical"].map((p) => <SelectItem key={p} value={p} className="capitalize">{p}</SelectItem>)}</SelectContent>
            </Select>
          </div>
        </div>
      )}
      {f.kind === "task" && (
        <div className="space-y-2">
          <Label>Checklist (one step per line, optional)</Label>
          <Textarea rows={3} value={f.checklist} onChange={(e) => set("checklist", e.target.value)} placeholder={"Confirm PO\nCheck quantity\nCheck batch and expiry"} />
        </div>
      )}
    </DetailSheet>
  );
}

// ── task row + task panel ───────────────────────────────────────────────────

export function TaskRow({ t, onOpen, onDone, showOwner }: { t: Dict; onOpen: () => void; onDone?: () => void; showOwner?: boolean }) {
  const Icon = KIND_ICON[t.kind] ?? ListChecks;
  const done = t.status === "completed";
  return (
    <div className="group flex items-start gap-3 rounded-lg border bg-background/60 px-3 py-2.5 transition-colors hover:border-primary/40">
      {onDone && !done ? (
        <button onClick={onDone} title="Mark done" className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 border-muted-foreground/40 hover:border-emerald-500 hover:bg-emerald-50 dark:hover:bg-emerald-500/10">
          <CheckCircle2 className="h-3 w-3 text-emerald-600 opacity-0 group-hover:opacity-100" />
        </button>
      ) : done ? <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" /> : <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />}
      <button onClick={onOpen} className="min-w-0 flex-1 text-left">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 shrink-0 rounded-full ${PRIORITY_DOT[t.priority] ?? "bg-slate-300"}`} title={`${t.priority} priority`} />
          <span className={`truncate text-sm font-medium ${done ? "text-muted-foreground line-through" : ""}`}>{t.title}</span>
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
          {t.kind !== "task" && <span className="capitalize">{t.kind}</span>}
          {t.when && !done && <span className={t.overdue ? "font-medium text-red-600" : t.due_today ? "font-medium text-amber-600" : ""}>{t.overdue ? "Overdue · " : ""}{when(t.when)}</span>}
          {done && t.completed_at && <span>Done {when(t.completed_at)}</span>}
          {t.status === "waiting" && <span className="text-amber-700 dark:text-amber-400">Waiting on {t.waiting_on}</span>}
          {t.status === "in_progress" && <span className="text-sky-600">In progress</span>}
          {t.recurrence && <span className="inline-flex items-center gap-0.5" title={`Repeats ${repeatLabel(t.recurrence)}`}><Repeat className="h-3 w-3" />{repeatLabel(t.recurrence)}</span>}
          {t.escalated && <span className="inline-flex items-center gap-0.5 rounded bg-red-100 px-1 font-medium text-red-700 dark:bg-red-500/15 dark:text-red-300"><Flame className="h-3 w-3" />escalated{t.escalated_to === "management" ? " to management" : ""}</span>}
          {t.entity_label && <span className="rounded bg-muted px-1">{t.entity_label}</span>}
          {SOURCE_LABEL[t.source] && t.source !== "operational" && <span>{SOURCE_LABEL[t.source]}{t.created_by_name && t.source !== "manual" ? ` by ${t.created_by_name}` : ""}</span>}
          {showOwner && t.assigned_to_name && <span className="inline-flex items-center gap-0.5"><UserRound className="h-3 w-3" />{t.assigned_to_name}</span>}
          {t.checklist?.length > 0 && <span>{t.checklist_done}/{t.checklist.length} steps</span>}
          {Number(t.comments) > 0 && <span className="inline-flex items-center gap-0.5"><MessageSquare className="h-3 w-3" />{t.comments}</span>}
        </div>
      </button>
    </div>
  );
}

export function TaskSheet({ taskId, onClose, onAsk }: { taskId: string | null; onClose: () => void; onAsk?: (task: Dict) => void }) {
  const refresh = useWsRefresh();
  const nav = useNavigate();
  const me = myId();
  const q = useQuery({ queryKey: ["ws", "task", taskId], queryFn: () => api.workspace.task(taskId as string), enabled: !!taskId });
  const t = q.data;
  const [commentText, setComment] = useState("");
  const [mode, setMode] = useState<"" | "waiting" | "complete" | "handover">("");
  const [extra, setExtra] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { setMode(""); setExtra(""); setComment(""); }, [taskId]);

  const act = async (fn: () => Promise<any>, ok?: string) => {
    setBusy(true);
    try { await fn(); if (ok) toast.success(ok); setMode(""); setExtra(""); refresh(); await q.refetch(); }
    catch (e: any) { toast.error(e?.message || "That did not work"); } finally { setBusy(false); }
  };
  const can = (s: string) => t?.transitions?.includes(s);
  const toggleStep = (i: number) => {
    const list = t.checklist.map((c: Dict, j: number) => (j === i ? { ...c, done: !c.done } : c));
    act(() => api.workspace.updateTask(t.id, { checklist: list }));
  };

  return (
    <DetailSheet open={!!taskId} onOpenChange={(v) => !v && onClose()} title={t?.title ?? "Task"} icon={KIND_ICON[t?.kind] ?? ListChecks}
      description={t ? [t.entity_label, t.department, t.created_by && t.created_by !== t.assigned_to ? `from ${t.created_by_name}` : null].filter(Boolean).join(" · ") : undefined}>
      {!t ? <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div> : (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <StatusChip status={t.status} />
            <span className="inline-flex items-center gap-1 capitalize"><span className={`h-2 w-2 rounded-full ${PRIORITY_DOT[t.priority]}`} />{t.priority}</span>
            {t.when && <span className={t.overdue ? "font-medium text-red-600" : ""}><Clock className="mr-0.5 inline h-3 w-3" />{when(t.when)}</span>}
            {t.assigned_to !== me && <span className="text-muted-foreground">For {t.assigned_to_name}</span>}
            {t.status === "waiting" && <span className="text-amber-700">Waiting on {t.waiting_on}</span>}
          </div>
          {t.escalated && (
            <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
              <Flame className="h-4 w-4" />Overdue and escalated to {t.escalated_to === "management" ? "management" : "the person who gave it"}{t.escalated_at ? ` · ${ago(t.escalated_at)}` : ""}. Moving the due date restarts the chain.
            </div>
          )}
          {t.kind !== "note" && t.status !== "completed" && t.status !== "cancelled" && (
            <div className="flex items-center gap-2 text-xs">
              <Repeat className="h-3.5 w-3.5 text-muted-foreground" />
              <select value={t.recurrence ?? ""} disabled={busy || (!t.when && !t.recurrence)}
                title={!t.when ? "Give the task a date to make it repeat" : undefined}
                onChange={(e) => act(() => api.workspace.updateTask(t.id, { recurrence: e.target.value || null }), e.target.value ? "Now repeats" : "Stopped repeating")}
                className="h-7 rounded-md border bg-background px-1.5">
                {REPEAT_OPTIONS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                {t.recurrence && !REPEAT_OPTIONS.some(([k]) => k === t.recurrence) && <option value={t.recurrence}>{repeatLabel(t.recurrence)}</option>}
              </select>
              {t.recurrence && <span className="text-muted-foreground">finishing or cancelling this one schedules the next{t.recurrence_until ? ` · until ${new Date(t.recurrence_until).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}` : ""}</span>}
            </div>
          )}
          {t.description && <p className="whitespace-pre-wrap rounded-lg bg-muted/40 p-3 text-sm">{t.description}</p>}
          {t.link && (
            <Button variant="outline" size="sm" className="w-full justify-between" onClick={() => { onClose(); nav(t.link); }}>
              Open the record ({t.entity_label || "linked page"}) <ArrowUpRight className="h-4 w-4" />
            </Button>
          )}

          {t.checklist?.length > 0 && (
            <div className="space-y-1">
              <div className="text-xs font-semibold text-muted-foreground">Checklist · {t.checklist_done}/{t.checklist.length}</div>
              {t.checklist.map((c: Dict, i: number) => (
                <label key={i} className="flex cursor-pointer items-center gap-2 rounded-md px-1 py-1 text-sm hover:bg-muted/50">
                  <input type="checkbox" checked={!!c.done} disabled={busy || t.status === "completed"} onChange={() => toggleStep(i)} className="h-4 w-4 accent-emerald-600" />
                  <span className={c.done ? "text-muted-foreground line-through" : ""}>{c.text}</span>
                </label>
              ))}
            </div>
          )}

          {/* actions, done in place */}
          <div className="flex flex-wrap gap-2">
            {can("in_progress") && t.status !== "waiting" && <Button size="sm" disabled={busy} onClick={() => act(() => api.workspace.setStatus(t.id, "in_progress"), "Started")}><Play className="mr-1 h-3.5 w-3.5" />Start</Button>}
            {t.status === "waiting" && <Button size="sm" disabled={busy} onClick={() => act(() => api.workspace.setStatus(t.id, "in_progress"), "Back on it")}><Play className="mr-1 h-3.5 w-3.5" />Resume</Button>}
            {can("completed") && <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700" disabled={busy} onClick={() => setMode("complete")}><CheckCircle2 className="mr-1 h-3.5 w-3.5" />Complete</Button>}
            {can("waiting") && <Button size="sm" variant="outline" disabled={busy} onClick={() => setMode("waiting")}><Hourglass className="mr-1 h-3.5 w-3.5" />Waiting on…</Button>}
            {onAsk && t.status !== "completed" && <Button size="sm" variant="outline" onClick={() => onAsk(t)}><HandHelping className="mr-1 h-3.5 w-3.5" />Ask someone</Button>}
            {t.status !== "completed" && t.status !== "cancelled" && <Button size="sm" variant="outline" onClick={() => setMode("handover")}><UserRound className="mr-1 h-3.5 w-3.5" />Hand over</Button>}
            {can("pending") && (t.status === "completed" || t.status === "cancelled") && <Button size="sm" variant="outline" disabled={busy} onClick={() => act(() => api.workspace.setStatus(t.id, "pending"), "Reopened")}><Undo2 className="mr-1 h-3.5 w-3.5" />Reopen</Button>}
            {can("cancelled") && <Button size="sm" variant="ghost" className="text-muted-foreground" disabled={busy} onClick={() => act(() => api.workspace.setStatus(t.id, "cancelled"), "Cancelled")}><XCircle className="mr-1 h-3.5 w-3.5" />Cancel</Button>}
          </div>
          {mode === "complete" && (
            <div className="space-y-2 rounded-lg border p-3">
              <Label className="text-xs">What was done? (optional)</Label>
              <Input value={extra} onChange={(e) => setExtra(e.target.value)} placeholder="e.g. 98 of 100 units received, batch B2026-09" />
              <Button size="sm" className="w-full" disabled={busy} onClick={() => act(() => api.workspace.setStatus(t.id, "completed", { note: extra || undefined }), "Done - nice work")}>Mark complete</Button>
            </div>
          )}
          {mode === "waiting" && (
            <div className="space-y-2 rounded-lg border p-3">
              <Label className="text-xs">Waiting on whom or what?</Label>
              <Input value={extra} onChange={(e) => setExtra(e.target.value)} placeholder="e.g. Supplier delivery note" />
              <Button size="sm" className="w-full" disabled={busy || !extra.trim()} onClick={() => act(() => api.workspace.setStatus(t.id, "waiting", { waiting_on: extra }), "Marked as waiting")}>Save</Button>
            </div>
          )}
          {mode === "handover" && (
            <div className="space-y-2 rounded-lg border p-3">
              <Label className="text-xs">Hand this to</Label>
              <PersonPick value={extra} onChange={setExtra} />
              <Button size="sm" className="w-full" disabled={busy || !extra} onClick={() => act(() => api.workspace.updateTask(t.id, { assigned_to: extra }), "Handed over")}>Hand over</Button>
            </div>
          )}

          {t.requests?.length > 0 && (
            <div className="space-y-1">
              <div className="text-xs font-semibold text-muted-foreground">Requests</div>
              {t.requests.map((r: Dict) => (
                <div key={r.id} className="rounded-md border px-2 py-1.5 text-xs">
                  <div className="flex justify-between gap-2"><span className="font-medium">{r.subject}</span><span className="text-muted-foreground">{r.to} · {r.status}</span></div>
                  {r.response && <div className="mt-1 text-muted-foreground">↳ {r.response}</div>}
                </div>
              ))}
            </div>
          )}

          <div className="space-y-2">
            <div className="text-xs font-semibold text-muted-foreground">Activity</div>
            <ol className="space-y-2 border-l pl-3">
              {t.activity.map((a: Dict) => (
                <li key={a.id} className="text-xs">
                  <span className="text-muted-foreground">{when(a.created_at)} · </span>
                  <span className="font-medium">{a.actor_name}</span>{" "}
                  {a.kind === "comment" ? <span className="block whitespace-pre-wrap rounded-md bg-muted/50 px-2 py-1 mt-0.5">{a.body}</span> : <span>{a.body}</span>}
                </li>
              ))}
            </ol>
            <div className="flex gap-2">
              <Input value={commentText} onChange={(e) => setComment(e.target.value)} placeholder="Comment (use @name to mention)"
                onKeyDown={(e) => { if (e.key === "Enter" && commentText.trim()) act(() => api.workspace.comment(t.id, commentText)).then(() => setComment("")); }} />
              <Button size="icon" variant="outline" disabled={busy || !commentText.trim()} onClick={() => act(() => api.workspace.comment(t.id, commentText)).then(() => setComment(""))}><Send className="h-4 w-4" /></Button>
            </div>
          </div>
        </>
      )}
    </DetailSheet>
  );
}

// ── type a sentence ─────────────────────────────────────────────────────────

/** "Remind me to call Skylark every Monday at 10am" -> shows what was understood, Enter saves exactly that. */
export function QuickAdd({ onMore }: { onMore?: (d: NewTaskDefaults) => void }) {
  const refresh = useWsRefresh();
  const [text, setText] = useState("");
  const [draft, setDraft] = useState<Dict | null>(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);
  useEffect(() => {
    if (text.trim().length < 3) { setDraft(null); return; }
    const n = ++seq.current;
    const id = setTimeout(() => {
      api.workspace.parse(text).then((d) => { if (n === seq.current) setDraft(d); }).catch(() => { if (n === seq.current) setDraft(null); });
    }, 350);
    return () => clearTimeout(id);
  }, [text]);
  const save = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try {
      const d = draft && draft.text === text ? draft : await api.workspace.parse(text);
      await api.workspace.createTask({ title: d.title, kind: d.kind, priority: d.priority, due_at: d.due_at, assigned_to: d.assigned_to ?? undefined,
        department: d.department ?? undefined, recurrence: d.recurrence ?? undefined, recurrence_until: d.recurrence_until ?? undefined });
      toast.success(`${d.kind === "reminder" ? "Reminder set" : d.kind === "note" ? "Noted" : d.assignee_name ? `Sent to ${d.assignee_name}` : "Added"}: ${d.title}`);
      setText(""); setDraft(null); refresh();
    } catch (e: any) { toast.error(e?.message || "Could not add"); } finally { setBusy(false); }
  };
  const toLocal = (iso?: string | null) => (iso ? toLocalInput(new Date(iso)) : "");
  return (
    <div className="rounded-xl border bg-card p-3">
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 shrink-0 text-primary" />
        <Input value={text} onChange={(e) => setText(e.target.value)} disabled={busy}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); save(); } }}
          className="border-0 shadow-none focus-visible:ring-0"
          placeholder="Type it as you'd say it - “Remind me to call Skylark every Monday at 10am”, “Ask Tayo to send timesheets by Friday, urgent”" />
        {text && <Button size="sm" disabled={busy} onClick={save}>{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <><CornerDownLeft className="mr-1 h-3.5 w-3.5" />Add</>}</Button>}
      </div>
      {draft && text && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t pt-2 text-[11px]">
          <span className="font-medium">“{draft.title}”</span>
          {draft.understood.map((u: string) => <span key={u} className="rounded-full bg-primary/10 px-2 py-0.5 text-primary">{u}</span>)}
          {onMore && (
            <button className="ml-auto inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
              onClick={() => { onMore({ kind: draft.kind, title: draft.title, due: toLocal(draft.due_at), priority: draft.priority,
                assigned_to: draft.assigned_to ?? undefined, recurrence: draft.recurrence, recurrence_until: draft.recurrence_until,
                department: draft.department }); setText(""); setDraft(null); }}>
              <SlidersHorizontal className="h-3 w-3" />adjust before saving
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── escalation rules ────────────────────────────────────────────────────────

const ESC_ROWS: [string, string, string][] = [
  ["task", "critical", "Critical tasks"], ["task", "high", "High priority tasks"], ["task", "medium", "Medium priority tasks"],
  ["task", "low", "Low priority tasks"], ["request", "all", "Requests to colleagues"],
];
const ESC_TO: Record<string, [string, string][]> = {
  task: [["assignee", "the person doing it"], ["giver", "whoever gave it"], ["management", "management"]],
  request: [["recipient", "the person asked"], ["requester", "the person who asked"], ["management", "management"]],
};

export function EscalationSheet({ open, onOpenChange, canRun }: { open: boolean; onOpenChange: (v: boolean) => void; canRun?: boolean }) {
  const q = useQuery({ queryKey: ["ws", "escalation-policy"], queryFn: () => api.workspace.escalationPolicy(), enabled: open });
  const [edit, setEdit] = useState<Record<string, { after_hours: number; to: string }[]>>({});
  const [busy, setBusy] = useState("");
  useEffect(() => { if (q.data) setEdit(JSON.parse(JSON.stringify(q.data))); }, [q.data]);
  const save = async (subject: string, priority: string) => {
    setBusy(`${subject}:${priority}`);
    try { await api.workspace.saveEscalationPolicy(subject, priority, edit[`${subject}:${priority}`] ?? []); toast.success("Rule saved"); q.refetch(); }
    catch (e: any) { toast.error(e?.message || "Could not save"); } finally { setBusy(""); }
  };
  const upd = (key: string, fn: (s: { after_hours: number; to: string }[]) => { after_hours: number; to: string }[]) =>
    setEdit((e) => ({ ...e, [key]: fn([...(e[key] ?? [])]) }));
  return (
    <DetailSheet open={open} onOpenChange={onOpenChange} icon={ShieldAlert} title="Escalation rules"
      description="When something passes its due time, each step fires once, in order - hours counted from the due time. Notes never escalate; reminders only remind their owner."
      footer={canRun ? <Button variant="outline" className="w-full" onClick={() => api.workspace.runEscalations().then((r) => toast.success(`Checked now: ${r.tasks} tasks, ${r.requests} requests escalated`)).catch((e) => toast.error(e.message))}>Run the check now</Button> : undefined}>
      {!q.data ? <Loader2 className="mx-auto h-5 w-5 animate-spin" /> : ESC_ROWS.map(([subject, priority, label]) => {
        const key = `${subject}:${priority}`;
        const steps = edit[key] ?? [];
        return (
          <div key={key} className="rounded-lg border p-3">
            <div className="mb-2 flex items-center justify-between text-sm font-medium">{label}
              <Button size="sm" variant="outline" className="h-7" disabled={busy === key || JSON.stringify(steps) === JSON.stringify(q.data[key] ?? [])} onClick={() => save(subject, priority)}>
                {busy === key ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Save"}</Button>
            </div>
            {steps.length === 0 && <p className="text-xs text-muted-foreground">No escalation.</p>}
            {steps.map((s, i) => (
              <div key={i} className="mb-1.5 flex items-center gap-2 text-xs">
                <span className="w-10 text-muted-foreground">Step {i + 1}</span>
                <Input type="number" min={0} className="h-7 w-20" value={s.after_hours}
                  onChange={(e) => upd(key, (l) => { l[i] = { ...l[i], after_hours: Number(e.target.value) }; return l; })} />
                <span>hours late → tell</span>
                <select value={s.to} onChange={(e) => upd(key, (l) => { l[i] = { ...l[i], to: e.target.value }; return l; })} className="h-7 rounded-md border bg-background px-1">
                  {ESC_TO[subject].map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
                <button className="ml-auto text-muted-foreground hover:text-red-600" onClick={() => upd(key, (l) => l.filter((_, j) => j !== i))}><Trash2 className="h-3.5 w-3.5" /></button>
              </div>
            ))}
            <button className="text-xs text-primary hover:underline" onClick={() => upd(key, (l) => [...l, { after_hours: (l[l.length - 1]?.after_hours ?? 0) + 24, to: "management" }])}>+ add step</button>
          </div>
        );
      })}
    </DetailSheet>
  );
}

// ── requests ────────────────────────────────────────────────────────────────

export type RequestDefaults = { to_user?: string; to_department?: string; task_id?: string; subject?: string; kind?: "info" | "work" };

export function NewRequestSheet({ open, onOpenChange, defaults }: { open: boolean; onOpenChange: (v: boolean) => void; defaults?: RequestDefaults }) {
  const refresh = useWsRefresh();
  const blank = () => ({ target: defaults?.to_department ? "team" : "person", to_user: defaults?.to_user ?? "", to_department: defaults?.to_department ?? "Finance",
    kind: defaults?.kind ?? "info", subject: defaults?.subject ?? "", body: "", due: "" });
  const [f, setF] = useState(blank);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) setF(blank()); }, [open]);  // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k: string, v: string) => setF((p) => ({ ...p, [k]: v }));
  const submit = async () => {
    setBusy(true);
    try {
      await api.workspace.createRequest({
        to_user: f.target === "person" ? f.to_user : undefined, to_department: f.target === "team" ? f.to_department : undefined,
        kind: f.kind, subject: f.subject, body: f.body || undefined, due_at: fromLocalInput(f.due), task_id: defaults?.task_id,
      });
      toast.success("Request sent - it will show under Waiting until they answer");
      refresh(); onOpenChange(false);
    } catch (e: any) { toast.error(e?.message || "Could not send"); } finally { setBusy(false); }
  };
  return (
    <DetailSheet open={open} onOpenChange={onOpenChange} icon={HandHelping} title="Ask a colleague"
      description="An information request expects an answer; a work request puts a task in their list."
      footer={<Button className="w-full" onClick={submit} disabled={busy || !f.subject.trim() || (f.target === "person" && !f.to_user)}>{busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Send request</Button>}>
      <div className="grid grid-cols-2 gap-1 rounded-lg bg-muted p-1">
        {[["info", "Information"], ["work", "Work"]].map(([k, l]) => (
          <button key={k} onClick={() => set("kind", k)} className={`rounded-md px-2 py-1.5 text-xs font-medium ${f.kind === k ? "bg-background shadow-sm" : "text-muted-foreground"}`}>{l} request</button>
        ))}
      </div>
      <div className="space-y-2">
        <Label>To</Label>
        <div className="flex gap-2">
          <Select value={f.target} onValueChange={(v) => set("target", v)}>
            <SelectTrigger className="w-28"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="person">Person</SelectItem>{f.kind === "info" && <SelectItem value="team">Team</SelectItem>}</SelectContent>
          </Select>
          <div className="flex-1">
            {f.target === "person" ? <PersonPick value={f.to_user} onChange={(v) => set("to_user", v)} includeMe={false} /> : (
              <Select value={f.to_department} onValueChange={(v) => set("to_department", v)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>{DEPARTMENTS.map((d) => <SelectItem key={d} value={d}>{d} team</SelectItem>)}</SelectContent>
              </Select>
            )}
          </div>
        </div>
      </div>
      <div className="space-y-2">
        <Label>{f.kind === "info" ? "What do you need to know?" : "What needs doing?"}</Label>
        <Input value={f.subject} onChange={(e) => set("subject", e.target.value)} placeholder={f.kind === "info" ? "e.g. Has PO-1024 been paid?" : "e.g. Pack 20 MENACTRA for Skylark"} />
      </div>
      <div className="space-y-2"><Label>Details (optional)</Label><Textarea rows={3} value={f.body} onChange={(e) => set("body", e.target.value)} /></div>
      <div className="space-y-2">
        <Label>Needed by (optional)</Label>
        <Input type="datetime-local" value={f.due} onChange={(e) => set("due", e.target.value)} />
      </div>
    </DetailSheet>
  );
}

export function RequestSheet({ requestId, onClose }: { requestId: string | null; onClose: () => void }) {
  const refresh = useWsRefresh();
  const q = useQuery({ queryKey: ["ws", "request", requestId], queryFn: () => api.workspace.request(requestId as string), enabled: !!requestId });
  const r = q.data;
  const me = myId();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => setText(""), [requestId]);
  const act = async (action: string, body?: string) => {
    setBusy(true);
    try { await api.workspace.requestAction(r.id, action, body ? { body } : {}); setText(""); refresh(); await q.refetch(); }
    catch (e: any) { toast.error(e?.message || "That did not work"); } finally { setBusy(false); }
  };
  const asker = r?.from_user === me;
  const open = r && ["sent", "acknowledged", "in_progress"].includes(r.status);
  return (
    <DetailSheet open={!!requestId} onOpenChange={(v) => !v && onClose()} icon={HandHelping} title={r?.subject ?? "Request"}
      description={r ? `${r.from_name} → ${r.to_name} · ${r.kind === "work" ? "work" : "information"} request · ${ago(r.created_at)}` : undefined}>
      {!r ? <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin" /></div> : (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Badge variant="outline" className="capitalize">{r.status.replace("_", " ")}</Badge>
            {r.due_at && <span className={r.overdue ? "text-red-600" : "text-muted-foreground"}>Needed {when(r.due_at)}</span>}
          </div>
          {r.body && <p className="whitespace-pre-wrap rounded-lg bg-muted/40 p-3 text-sm">{r.body}</p>}
          {r.response && <div className="rounded-lg border-l-4 border-emerald-500 bg-emerald-50 p-3 text-sm dark:bg-emerald-500/10"><div className="text-xs text-muted-foreground">{r.responded_by_name} answered</div>{r.response}</div>}
          <div className="space-y-2">
            {r.thread.map((m: Dict) => (
              <div key={m.id} className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${m.author === me ? "ml-auto bg-primary/10" : "bg-muted"}`}>
                <div className="text-[10px] text-muted-foreground">{m.author_name} · {ago(m.created_at)}</div>{m.body}
              </div>
            ))}
          </div>
          {r.status !== "closed" && (
            <Textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder={!asker && open ? "Your answer…" : "Message…"} />
          )}
          <div className="flex flex-wrap gap-2">
            {!asker && open && <Button size="sm" disabled={busy || !text.trim()} onClick={() => act("respond", text)}><Send className="mr-1 h-3.5 w-3.5" />Send answer</Button>}
            {r.status !== "closed" && <Button size="sm" variant="outline" disabled={busy || !text.trim()} onClick={() => act("reply", text)}><MessageSquare className="mr-1 h-3.5 w-3.5" />Reply</Button>}
            {!asker && r.status === "sent" && <Button size="sm" variant="outline" disabled={busy} onClick={() => act("acknowledge")}>Seen - on it</Button>}
            {!asker && open && <Button size="sm" variant="ghost" disabled={busy} onClick={() => act("decline", text || undefined)}>Can't help</Button>}
            {asker && r.status !== "closed" && <Button size="sm" variant="outline" disabled={busy} onClick={() => act("close")}><CheckCircle2 className="mr-1 h-3.5 w-3.5" />Close</Button>}
          </div>
        </>
      )}
    </DetailSheet>
  );
}

export function RequestRow({ r, onOpen, incoming }: { r: Dict; onOpen: () => void; incoming?: boolean }) {
  return (
    <button onClick={onOpen} className="flex w-full items-start gap-3 rounded-lg border bg-background/60 px-3 py-2 text-left hover:border-primary/40">
      <HandHelping className={`mt-0.5 h-4 w-4 shrink-0 ${r.mine_to_answer ? "text-orange-500" : "text-muted-foreground"}`} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{r.subject}</div>
        <div className="text-[11px] text-muted-foreground">
          {incoming ? `From ${r.from_name}${r.to_user ? "" : ` to ${r.to_name}`}` : `To ${r.to_name}`} · {r.status === "responded" ? `answered ${ago(r.responded_at)}` : r.status.replace("_", " ")}
          {r.due_at && r.status !== "responded" && <span className={r.overdue ? " text-red-600" : ""}> · needed {when(r.due_at)}</span>}
        </div>
      </div>
      {Number(r.messages) > 0 && <span className="text-[11px] text-muted-foreground"><MessageSquare className="inline h-3 w-3" /> {r.messages}</span>}
    </button>
  );
}

// ── chat ────────────────────────────────────────────────────────────────────

export function ChatPane({ withId, title }: { withId: string; title?: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["ws", "chat", withId], queryFn: () => api.workspace.messages(withId), refetchInterval: 15_000 });
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const msgs: Dict[] = q.data?.messages ?? [];
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [msgs.length]);
  useEffect(() => { qc.invalidateQueries({ queryKey: ["ws", "conversations"] }); }, [q.dataUpdatedAt, qc]);
  const send = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try { await api.workspace.send(withId, text.trim()); setText(""); await q.refetch(); qc.invalidateQueries({ queryKey: ["ws", "conversations"] }); }
    catch (e: any) { toast.error(e?.message || "Not sent"); } finally { setBusy(false); }
  };
  const grouped = useMemo(() => msgs, [msgs]);
  return (
    <div className="flex h-full min-h-[420px] flex-col">
      {title && <div className="border-b px-3 py-2 text-sm font-semibold">{title}</div>}
      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {q.isLoading ? <Loader2 className="mx-auto h-5 w-5 animate-spin text-muted-foreground" /> :
          grouped.length === 0 ? <p className="py-10 text-center text-sm text-muted-foreground">No messages yet - say hello.</p> :
            grouped.map((m) => (
              <div key={m.id} className={`max-w-[80%] rounded-2xl px-3 py-2 text-sm ${m.mine ? "ml-auto rounded-br-sm bg-primary text-primary-foreground" : "rounded-bl-sm bg-muted"}`}>
                {!m.mine && withId === "team" && <div className="text-[10px] font-semibold opacity-70">{m.sender_name}</div>}
                <div className="whitespace-pre-wrap break-words">{m.content}</div>
                <div className={`mt-0.5 text-[10px] ${m.mine ? "text-primary-foreground/70" : "text-muted-foreground"}`}>{when(m.created_at)}</div>
              </div>
            ))}
        <div ref={end} />
      </div>
      <div className="flex gap-2 border-t p-2">
        <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Message (@name to mention)"
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
        <Button size="icon" disabled={busy || !text.trim()} onClick={send}><Send className="h-4 w-4" /></Button>
      </div>
    </div>
  );
}

export function ChatSheet({ withId, name, onClose }: { withId: string | null; name?: string; onClose: () => void }) {
  return (
    <DetailSheet open={!!withId} onOpenChange={(v) => !v && onClose()} icon={MessageSquare} title={name ?? "Messages"}>
      {withId && <div className="-mx-2 h-[70vh] rounded-lg border"><ChatPane withId={withId} /></div>}
    </DetailSheet>
  );
}

export { CircleDot, Plus };
