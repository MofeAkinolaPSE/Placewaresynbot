/**
 * HR on live data: who's online and on the clock, hours this week per person (saved +
 * running), the directory built from User Access, and timesheet review.
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, Circle, Clock, Download, Loader2, MessageSquare, Pencil, Plus, Search,
  Timer, UserCheck, UserPlus, Users, XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { api } from "@/lib/api-client";
import { downloadAuthed } from "@/components/crm/crm-kit";
import { DEPARTMENTS, Dict, Dot, Empty, fmtDur, hhmm, PRESENCE, Section, when } from "@/components/staff/ws-kit";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const iso = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
const addDays = (s: string, n: number) => { const d = new Date(s + "T12:00:00"); d.setDate(d.getDate() + n); return iso(d); };
const weekLabel = (s: string) => {
  const a = new Date(s + "T12:00:00"), b = new Date(addDays(s, 6) + "T12:00:00");
  return `${a.toLocaleDateString("en-GB", { day: "numeric", month: "short" })} – ${b.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}`;
};
const hx = (n: number) => (Math.round((n || 0) * 10) / 10).toFixed(1);
const thisMonday = () =>{ const d = new Date(); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return iso(d); };
const h1 = (n: number) =>(n ? (Math.round(n * 10) / 10).toFixed(1) : "–");

export function WeekPicker({ week, onChange, current }: { week: string; onChange: (w: string) => void; current: string }) {
  return (
    <div className="flex items-center gap-1 text-sm">
      <Button size="icon" variant="ghost" className="h-8 w-8" onClick={() => onChange(addDays(week, -7))}><ChevronLeft className="h-4 w-4" /></Button>
      <span className="min-w-[170px] text-center font-medium">{week === current ? "This week" : weekLabel(week)}</span>
      <Button size="icon" variant="ghost" className="h-8 w-8" disabled={week >= current} onClick={() => onChange(addDays(week, 7))}><ChevronRight className="h-4 w-4" /></Button>
    </div>
  );
}

function useTick(on: boolean) {
  const [, set] = useState(0);
  useEffect(() => { if (!on) return; const id = setInterval(() => set((n) => n + 1), 30_000); return () => clearInterval(id); }, [on]);
}

// ── Overview ────────────────────────────────────────────────────────────────

export function OverviewPanel({ onPerson, gotoTimesheets }: { onPerson: (key: string) => void; gotoTimesheets: (view?: string) => void }) {
  const [week, setWeek] = useState<string>("");
  const q = useQuery({ queryKey: ["hr", "overview", week], queryFn: () => api.hrHub.overview(week || undefined), refetchInterval: 60_000 });
  const d = q.data;
  useTick(!!d?.on_clock?.length);
  if (!d) return q.isLoading ? <Loader2 className="mx-auto mt-10 h-6 w-6 animate-spin" /> : <p className="text-sm text-destructive">Could not load HR overview.</p>;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <WeekPicker week={week || d.week} current={thisMonday()} onChange={(w) => setWeek(w)} />
        <span className="text-xs text-muted-foreground">Live · updated {hhmm(d.as_of)}{d.is_current && d.hours_live > 0 ? " · includes clocks still running" : ""}</span>
      </div>
      <KpiStrip items={[
        { label: "Online now", value: d.online.length, icon: Circle, tone: d.online.length ? "success" : "default",
          sub: d.online.map((o: Dict) => o.name.split(" ")[0]).join(", ") || "nobody" },
        { label: "On the clock now", value: d.on_clock.length, icon: Timer, tone: d.on_clock.length ? "success" : "default",
          sub: d.on_clock.map((o: Dict) => o.name.split(" ")[0]).join(", ") || "nobody clocked in" },
        { label: d.is_current ? "Hours this week (all staff)" : "Hours that week (all staff)", value: `${hx(d.hours_total)}h`, icon: Clock,
          sub: (d.hours_live > 0 ? `${hx(d.hours_saved)}h saved + ${hx(d.hours_live)}h running · ` : "") +
            `${d.people_with_hours} of ${d.headcount} people${d.people_with_hours ? `, avg ${hx(d.avg_per_person)}h` : ""}` },
        { label: "Awaiting approval", value: d.pending_approval.entries, icon: UserCheck, tone: d.pending_approval.entries ? "warning" : "default",
          // Counts every week, so it opens the all-weeks queue, not this week.
          sub: `${hx(d.pending_approval.hours)}h submitted`, onClick: () => gotoTimesheets("pending") },
      ]} />
      {d.long_clocks.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm dark:bg-amber-500/10">
          <AlertTriangle className="h-4 w-4 text-amber-600" />
          Clocks running over 12 hours: {d.long_clocks.map((l: Dict) => `${l.name} (since ${when(l.clocked_in_at)})`).join(", ")} - they will be asked for their real finish time.
        </div>
      )}
      <div className="grid gap-4 xl:grid-cols-4">
        <Section title="Hours by person" className="overflow-x-auto xl:col-span-3">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th className="pb-2 text-left font-medium">Team member</th>
                {DAYS.map((x) => <th key={x} className="pb-2 text-right font-medium">{x}</th>)}
                <th className="pb-2 text-right font-medium">Total</th>
                <th className="pb-2 pl-3 text-left font-medium">of target</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {d.grid.map((r: Dict) => (
                <tr key={r.key} className="cursor-pointer hover:bg-muted/40" onClick={() => onPerson(r.key)}>
                  <td className="py-2">
                    <div className="flex items-center gap-2">
                      <Dot status={r.status} />
                      <div className="min-w-0">
                        <div className="truncate font-medium">{r.name}</div>
                        <div className="truncate text-[11px] text-muted-foreground">{r.job_title ? `${r.job_title} · ` : ""}{r.department}{!r.has_login ? " · no login" : ""}</div>
                      </div>
                    </div>
                  </td>
                  {DAYS.map((x) => <td key={x} className={`py-2 text-right tabular-nums ${r.days[x] ? "" : "text-muted-foreground/40"}`}>{h1(r.days[x])}</td>)}
                  <td className="py-2 text-right font-semibold tabular-nums">
                    {h1(r.total)}
                    {r.live > 0 && <div className="text-[10px] font-normal text-emerald-600">{h1(r.live)} running</div>}
                  </td>
                  <td className="py-2 pl-3">
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary" style={{ width: `${Math.min(100, r.pct ?? 0)}%` }} /></div>
                      <span className="text-[11px] text-muted-foreground">{r.pct ?? 0}%</span>
                      {r.pending > 0 && <Badge variant="outline" className="h-5 px-1.5 text-[10px]">{r.pending} to approve</Badge>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t text-xs font-semibold">
                <td className="pt-2">Everyone</td>
                {d.by_day.map((x: Dict) => <td key={x.day} className="pt-2 text-right tabular-nums">{h1(x.hours)}</td>)}
                <td className="pt-2 text-right tabular-nums">{h1(d.hours_total)}</td><td />
              </tr>
            </tfoot>
          </table>
        </Section>
        <div className="space-y-4">
          <Section title="On the clock now">
            {d.on_clock.length === 0 ? <Empty>Nobody is clocked in.</Empty> : (
              <ul className="space-y-2 text-sm">
                {d.on_clock.map((o: Dict) => (
                  <li key={o.key} className="flex cursor-pointer items-center gap-2" onClick={() => onPerson(o.key)}>
                    <Dot status={o.status} /><span className="flex-1 truncate">{o.name}</span>
                    <span className="text-xs text-muted-foreground">{o.status === "on_break" ? "break · " : ""}{fmtDur((Date.now() - new Date(o.clocked_in_at).getTime()) / 1000)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Section>
          <Section title="Hours by department">
            {d.by_department.length === 0 ? <Empty>No hours this week yet.</Empty> : (
              <div className="space-y-2">
                {d.by_department.map((x: Dict) => (
                  <div key={x.department} className="text-xs">
                    <div className="flex justify-between"><span>{x.department}</span><span className="tabular-nums">{h1(x.hours)}h</span></div>
                    <div className="mt-0.5 h-1.5 rounded-full bg-muted"><div className="h-full rounded-full bg-primary" style={{ width: `${(100 * x.hours) / d.hours_total}%` }} /></div>
                  </div>
                ))}
              </div>
            )}
          </Section>
          <Section title="Last 8 weeks">
            <div className="h-32">
              <ResponsiveContainer>
                <BarChart data={d.weeks.map((w: Dict) => ({ ...w, label: new Date(w.week + "T12:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" }) }))}>
                  <XAxis dataKey="label" fontSize={10} tickLine={false} axisLine={false} />
                  <YAxis hide />
                  <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} formatter={(v: any) => [`${v}h`, "Hours"]} />
                  <Bar dataKey="hours" fill="hsl(var(--primary))" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}

// ── Directory ───────────────────────────────────────────────────────────────

const DIR_FILTERS: [string, string][] = [["active", "Active"], ["working", "At work now"], ["online", "Online"], ["nologin", "No login"], ["inactive", "Deactivated"]];

export function DirectoryPanel({ onPerson }: { onPerson: (key: string) => void }) {
  const q = useQuery({ queryKey: ["hr", "people"], queryFn: () => api.hrHub.people(), refetchInterval: 60_000 });
  const [flt, setFlt] = useState("active");
  const [dept, setDept] = useState("");
  const [search, setSearch] = useState("");
  const d = q.data;
  const rows: Dict[] = useMemo(() => (d?.people ?? []).filter((p: Dict) => {
    const ok = { active: p.active, working: ["working", "on_break"].includes(p.status), online: p.status !== "offline" && p.status !== "inactive",
      nologin: !p.has_login, inactive: !p.active }[flt as "active"];
    return ok && (!dept || p.department === dept) &&
      (!search || `${p.name} ${p.email ?? ""} ${p.job_title ?? ""} ${p.phone ?? ""}`.toLowerCase().includes(search.toLowerCase()));
  }), [d, flt, dept, search]);
  if (!d) return <Loader2 className="mx-auto mt-10 h-6 w-6 animate-spin" />;
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">Everyone set up on User Access appears here automatically, with their HR profile. Records without a login are staff HR added directly.</p>
      <div className="flex flex-wrap items-center gap-2">
        {DIR_FILTERS.map(([k, l]) => {
          const n = { active: d.counts.active, working: d.counts.working, online: d.counts.online, nologin: d.counts.no_login, inactive: d.counts.inactive }[k as "active"];
          return <button key={k} onClick={() => setFlt(k)} className={`rounded-full border px-3 py-1 text-xs ${flt === k ? "border-primary bg-primary/10 font-medium text-primary" : "hover:bg-muted"}`}>{l} · {n}</button>;
        })}
        <div className="ml-auto flex gap-2">
          <select value={dept} onChange={(e) => setDept(e.target.value)} className="h-8 rounded-md border bg-background px-2 text-xs">
            <option value="">All departments</option>{d.by_department.map((x: Dict) => <option key={x.department} value={x.department}>{x.department} ({x.count})</option>)}
          </select>
          <div className="relative"><Search className="absolute left-2 top-2 h-4 w-4 text-muted-foreground" /><Input className="h-8 w-52 pl-7" placeholder="Name, email, phone" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
        </div>
      </div>
      {rows.length === 0 ? <Empty>No one matches.</Empty> : (
        <div className="overflow-x-auto rounded-xl border bg-card">
          <table className="w-full min-w-[760px] text-sm">
            <thead><tr className="border-b text-xs text-muted-foreground">
              <th className="px-3 py-2 text-left font-medium">Name</th><th className="px-3 py-2 text-left font-medium">Department</th>
              <th className="px-3 py-2 text-left font-medium">Contact</th><th className="px-3 py-2 text-left font-medium">Now</th>
              <th className="px-3 py-2 text-right font-medium">Hours (week)</th><th className="px-3 py-2 text-right font-medium">Open tasks</th>
              <th className="px-3 py-2 text-left font-medium">Access</th>
            </tr></thead>
            <tbody className="divide-y">
              {rows.map((p) => (
                <tr key={p.key} className="cursor-pointer hover:bg-muted/40" onClick={() => onPerson(p.key)}>
                  <td className="px-3 py-2">
                    <div className="font-medium">{p.name}</div>
                    <div className="text-[11px] text-muted-foreground">{p.job_title || <span className="italic">no job title yet</span>}</div>
                  </td>
                  <td className="px-3 py-2">{p.department}</td>
                  <td className="px-3 py-2 text-xs"><div>{p.email ?? "—"}</div><div className="text-muted-foreground">{p.phone ?? ""}</div></td>
                  <td className="px-3 py-2 text-xs"><span className="inline-flex items-center gap-1.5"><Dot status={p.status} />{PRESENCE[p.status]?.label}</span></td>
                  <td className="px-3 py-2 text-right tabular-nums">{p.hours_week ? `${p.hours_week}h` : "–"}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{p.open_tasks || "–"}{p.overdue_tasks ? <span className="text-red-600"> ({p.overdue_tasks} late)</span> : ""}</td>
                  <td className="px-3 py-2 text-xs">{p.has_login ? (p.roles ?? []).join(", ") : <Badge variant="outline" className="text-[10px]">no login</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function PersonSheet({ personKey, onClose, canEdit }: { personKey: string | null; onClose: () => void; canEdit: boolean }) {
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["hr", "person", personKey], queryFn: () => api.hrHub.person(personKey as string), enabled: !!personKey });
  const p = q.data;
  const [edit, setEdit] = useState(false);
  const [f, setF] = useState<Dict>({});
  const [busy, setBusy] = useState(false);
  useEffect(() => { setEdit(false); }, [personKey]);
  useEffect(() => { if (p) setF({ name: p.name, department: p.department, job_title: p.job_title ?? "", phone: p.phone ?? "", branch: p.branch ?? "",
    start_date: p.start_date ?? "", weekly_hours: String(p.weekly_hours ?? 40) }); }, [p]);
  const save = async () => {
    setBusy(true);
    try { await api.hrHub.updatePerson(p.key, { ...f, weekly_hours: Number(f.weekly_hours), start_date: f.start_date || null }); toast.success("Profile saved"); setEdit(false); q.refetch(); }
    catch (e: any) { toast.error(e?.message || "Could not save"); } finally { setBusy(false); }
  };
  const maxW = Math.max(1, ...(p?.weeks ?? []).map((w: Dict) => w.hours));
  return (
    <DetailSheet open={!!personKey} onOpenChange={(v) => !v && onClose()} icon={Users} title={p?.name ?? "Staff member"}
      description={p ? `${p.job_title ? p.job_title + " · " : ""}${p.department}${p.email ? " · " + p.email : ""}` : undefined}>
      {!p ? <Loader2 className="mx-auto h-5 w-5 animate-spin" /> : (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="inline-flex items-center gap-1.5"><Dot status={p.status} />{PRESENCE[p.status]?.label}</span>
            {p.clock && <span className="text-muted-foreground">clocked in {when(p.clock.started_at)} · {fmtDur(p.clock.worked_seconds)} so far{p.clock.on_break ? " · on break" : ""}</span>}
            {!p.has_login && <Badge variant="outline">No login - create one on User Access</Badge>}
            <div className="ml-auto flex gap-1.5">
              {p.user_id && <Button size="sm" variant="outline" className="h-7" onClick={() => nav(`/workspace?tab=messages&with=${p.user_id}`)}><MessageSquare className="mr-1 h-3.5 w-3.5" />Message</Button>}
              {canEdit && !edit && <Button size="sm" variant="outline" className="h-7" onClick={() => setEdit(true)}><Pencil className="mr-1 h-3.5 w-3.5" />Edit</Button>}
            </div>
          </div>
          {edit ? (
            <div className="grid grid-cols-2 gap-3 rounded-lg border p-3">
              <div className="col-span-2 space-y-1"><Label className="text-xs">Full name</Label><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></div>
              <div className="space-y-1"><Label className="text-xs">Department</Label>
                <Select value={f.department} onValueChange={(v) => setF({ ...f, department: v })}><SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>{DEPARTMENTS.map((x) => <SelectItem key={x} value={x}>{x}</SelectItem>)}</SelectContent></Select></div>
              <div className="space-y-1"><Label className="text-xs">Job title</Label><Input value={f.job_title} onChange={(e) => setF({ ...f, job_title: e.target.value })} /></div>
              <div className="space-y-1"><Label className="text-xs">Phone</Label><Input value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></div>
              <div className="space-y-1"><Label className="text-xs">Branch</Label>
                <Select value={f.branch || undefined} onValueChange={(v) => setF({ ...f, branch: v })}><SelectTrigger><SelectValue placeholder="Branch" /></SelectTrigger>
                  <SelectContent>{["Lagos", "Abuja"].map((x) => <SelectItem key={x} value={x}>{x}</SelectItem>)}</SelectContent></Select></div>
              <div className="space-y-1"><Label className="text-xs">Start date</Label><Input type="date" value={f.start_date ?? ""} onChange={(e) => setF({ ...f, start_date: e.target.value })} /></div>
              <div className="space-y-1"><Label className="text-xs">Contracted hours / week</Label><Input type="number" min={1} max={80} value={f.weekly_hours} onChange={(e) => setF({ ...f, weekly_hours: e.target.value })} /></div>
              <div className="col-span-2 flex gap-2"><Button size="sm" disabled={busy} onClick={save}>{busy && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}Save</Button><Button size="sm" variant="ghost" onClick={() => setEdit(false)}>Cancel</Button></div>
            </div>
          ) : (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 rounded-lg bg-muted/40 p-3 text-xs">
              <dt className="text-muted-foreground">Phone</dt><dd>{p.phone ?? "—"}</dd>
              <dt className="text-muted-foreground">Branch</dt><dd>{p.branch ?? "—"}</dd>
              <dt className="text-muted-foreground">Started</dt><dd>{p.start_date ? new Date(p.start_date).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "—"}</dd>
              <dt className="text-muted-foreground">Contracted</dt><dd>{p.weekly_hours}h / week</dd>
              <dt className="text-muted-foreground">Access</dt><dd>{p.has_login ? (p.roles ?? []).join(", ") : "no login"}</dd>
            </dl>
          )}
          <div className="grid grid-cols-4 gap-2 text-center">
            {[["Open tasks", p.work.open_tasks], ["Done this week", p.work.done_week], ["Done 30 days", p.work.done_30d], ["Requests answered", p.work.requests_answered_30d]].map(([l, v]) => (
              <div key={l as string} className="rounded-lg border p-2"><div className="text-lg font-bold">{v}</div><div className="text-[10px] text-muted-foreground">{l}</div></div>
            ))}
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-muted-foreground">This week</div>
            <div className="grid grid-cols-7 gap-1 text-center text-[11px]">
              {p.week_days.map((x: Dict) => <div key={x.day} className="rounded-md bg-muted/50 py-1"><div className="text-muted-foreground">{x.day}</div><div className="font-medium">{h1(x.hours)}</div></div>)}
            </div>
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-muted-foreground">Last 8 weeks</div>
            <div className="flex h-16 items-end gap-1">
              {p.weeks.map((w: Dict) => (
                <div key={w.week} className="flex flex-1 flex-col items-center gap-0.5" title={`${w.week}: ${w.hours}h`}>
                  <div className="w-full rounded-t bg-primary/70" style={{ height: `${Math.max(2, (w.hours / maxW) * 52)}px` }} />
                  <span className="text-[9px] text-muted-foreground">{h1(w.hours)}</span>
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-muted-foreground">Recent clock sessions</div>
            {p.sessions.length === 0 ? <p className="text-xs text-muted-foreground">No clock sessions yet.</p> : (
              <ul className="space-y-1 text-xs">
                {p.sessions.map((s: Dict) => (
                  <li key={s.id} className="flex justify-between gap-2">
                    <span>{when(s.started_at)} → {s.ended_at ? hhmm(s.ended_at) : <span className="text-emerald-600">running</span>}</span>
                    <span className="text-muted-foreground">{fmtDur(s.worked_seconds)}{s.breaks ? ` · ${s.breaks} break${s.breaks > 1 ? "s" : ""}` : ""}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </DetailSheet>
  );
}

export function AddPersonSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const [f, setF] = useState<Dict>({ name: "", email: "", department: "Operations", job_title: "", phone: "" });
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();
  const submit = async () => {
    setBusy(true);
    try { await api.hrHub.addPerson(f); toast.success("Staff record added"); onOpenChange(false); setF({ name: "", email: "", department: "Operations", job_title: "", phone: "" }); }
    catch (e: any) { toast.error(e?.message || "Could not add"); } finally { setBusy(false); }
  };
  return (
    <DetailSheet open={open} onOpenChange={onOpenChange} icon={UserPlus} title="Add a staff record"
      description="For someone who does not need to sign in (yet). To give someone access, create their login on User Access - they appear here automatically."
      footer={<div className="flex w-full gap-2"><Button variant="outline" className="flex-1" onClick={() => nav("/admin/users")}>Go to User Access</Button>
        <Button className="flex-1" disabled={busy || !f.name.trim() || !f.email.includes("@")} onClick={submit}>{busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Add record</Button></div>}>
      <div className="space-y-2"><Label>Full name</Label><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></div>
      <div className="space-y-2"><Label>Email</Label><Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2"><Label>Department</Label>
          <Select value={f.department} onValueChange={(v) => setF({ ...f, department: v })}><SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>{DEPARTMENTS.map((x) => <SelectItem key={x} value={x}>{x}</SelectItem>)}</SelectContent></Select></div>
        <div className="space-y-2"><Label>Job title</Label><Input value={f.job_title} onChange={(e) => setF({ ...f, job_title: e.target.value })} /></div>
      </div>
      <div className="space-y-2"><Label>Phone</Label><Input value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></div>
    </DetailSheet>
  );
}

// ── Timesheets ──────────────────────────────────────────────────────────────

export function TimesheetsPanel({ canEdit, onPerson, pending = false, onPendingChange }: {
  canEdit: boolean; onPerson: (key: string) => void; pending?: boolean; onPendingChange?: (pending: boolean) => void;
}) {
  const [week, setWeek] = useState<string>("");
  const [person, setPerson] = useState<string>("");
  const q = useQuery({ queryKey: ["hr", "timesheets", week, person, pending], queryFn: () => api.hrHub.timesheets(week || undefined, person || undefined, pending), refetchInterval: 60_000 });
  const people = useQuery({ queryKey: ["hr", "people"], queryFn: () => api.hrHub.people() });
  const [adding, setAdding] = useState(false);
  const [edit, setEdit] = useState<{ id: number; mode: "reject" | "adjust"; hours: string; note: string } | null>(null);
  const d = q.data;
  const act = async (fn: () => Promise<any>, ok: string) => {
    try { await fn(); toast.success(ok); setEdit(null); q.refetch(); } catch (e: any) { toast.error(e?.message || "That did not work"); }
  };
  const today = iso(new Date());
  const cur = d?.week;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {d && !pending && <WeekPicker week={week || d.week} current={thisMonday()} onChange={setWeek} />}
        {pending && <span className="text-sm font-medium">Awaiting approval · all weeks</span>}
        <Button size="sm" variant={pending ? "default" : "outline"} className="h-8" onClick={() => onPendingChange?.(!pending)}>
          <UserCheck className="mr-1.5 h-4 w-4" />{pending ? "Back to week view" : "Awaiting approval"}
        </Button>
        <select value={person} onChange={(e) => setPerson(e.target.value)} className="h-8 rounded-md border bg-background px-2 text-xs">
          <option value="">Everyone</option>{(people.data?.people ?? []).map((p: Dict) => <option key={p.key} value={p.key}>{p.name}</option>)}
        </select>
        <div className="ml-auto flex gap-2">
          <Button size="sm" variant="outline" onClick={() => downloadAuthed(api.hrHub.timesheetsCsvUrl(week || undefined), `timesheets-${cur ?? "week"}.csv`).catch((e) => toast.error(e.message))}><Download className="mr-1.5 h-4 w-4" />Export CSV</Button>
          {canEdit && <Button size="sm" variant="outline" onClick={() => setAdding(true)}><Plus className="mr-1.5 h-4 w-4" />Add hours</Button>}
          {canEdit && d?.totals.submitted > 0 && <Button size="sm" onClick={() => act(() => api.hrHub.approveWeek({ week: d.week, person: person || undefined, all_weeks: pending || undefined }), pending ? "All submitted hours approved" : "Week approved")}><CheckCircle2 className="mr-1.5 h-4 w-4" />Approve all submitted</Button>}
        </div>
      </div>
      {!d ? <Loader2 className="mx-auto h-5 w-5 animate-spin" /> : (
        <>
          <KpiStrip items={[
            { label: "Hours recorded", value: `${hx(d.totals.hours)}h`, icon: Clock, sub: `${d.entries.length} entries` },
            { label: "Running now (not yet saved)", value: `${hx(d.totals.live)}h`, icon: Timer, tone: d.live.length ? "success" : "default", sub: `${d.live.length} on the clock` },
            { label: "Waiting for approval", value: `${hx(d.totals.submitted)}h`, icon: UserCheck, tone: d.totals.submitted ? "warning" : "default" },
            { label: "Approved", value: `${hx(d.totals.approved)}h`, icon: CheckCircle2, tone: "success" },
          ]} />
          {d.people.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {d.people.map((g: Dict) => (
                <button key={g.person} onClick={() => onPerson(g.person)} className="rounded-lg border bg-card px-3 py-1.5 text-left text-xs hover:border-primary/40">
                  <div className="font-medium">{g.name}</div>
                  <div className="text-muted-foreground">{h1(g.hours)}h{g.live ? ` + ${h1(g.live)}h running` : ""}{g.submitted ? ` · ${h1(g.submitted)}h to approve` : ""}</div>
                </button>
              ))}
            </div>
          )}
          {d.entries.length === 0 && d.live.length === 0 ? pending ? <Empty>Nothing is waiting for approval.</Empty> : <Empty>No hours recorded for this week. Hours appear here as soon as people clock out from their workspace.</Empty> : (
            <div className="overflow-x-auto rounded-xl border bg-card">
              <table className="w-full min-w-[820px] text-sm">
                <thead><tr className="border-b text-xs text-muted-foreground">
                  <th className="px-3 py-2 text-left font-medium">Date</th><th className="px-3 py-2 text-left font-medium">Team member</th>
                  <th className="px-3 py-2 text-right font-medium">Hours</th><th className="px-3 py-2 text-left font-medium">How</th>
                  <th className="px-3 py-2 text-left font-medium">Note</th><th className="px-3 py-2 text-left font-medium">Status</th>
                  {canEdit && <th className="px-3 py-2 text-right font-medium" />}
                </tr></thead>
                <tbody className="divide-y">
                  {d.live.map((l: Dict) => (
                    <tr key={`live-${l.person}`} className="bg-emerald-50/50 dark:bg-emerald-500/5">
                      <td className="px-3 py-2">{new Date().toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}</td>
                      <td className="px-3 py-2 font-medium">{l.name}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{l.hours_so_far.toFixed(2)}</td>
                      <td className="px-3 py-2 text-xs">clock · since {hhmm(l.started_at)}</td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">{l.on_break ? "on a break" : "working"}</td>
                      <td className="px-3 py-2"><Badge variant="outline" className="border-emerald-500 text-emerald-600">running</Badge></td>
                      {canEdit && <td />}
                    </tr>
                  ))}
                  {[...d.entries].reverse().map((e: Dict) => (
                    <tr key={e.id} className={e.status === "rejected" ? "opacity-60" : ""}>
                      <td className="px-3 py-2">{new Date(e.date + "T12:00:00").toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}</td>
                      <td className="px-3 py-2"><button className="font-medium hover:underline" onClick={() => onPerson(e.person)}>{e.name}</button><div className="text-[11px] text-muted-foreground">{e.department}</div></td>
                      <td className="px-3 py-2 text-right font-semibold tabular-nums">{Number(e.hours_worked).toFixed(2)}</td>
                      <td className="px-3 py-2 text-xs">{e.source === "clock" ? "clock in/out" : e.source === "hr" ? `added by ${e.recorded_by_name ?? "HR"}` : "manual"}</td>
                      <td className="max-w-[240px] px-3 py-2 text-xs text-muted-foreground"><div className="truncate" title={e.activity_note ?? ""}>{e.activity_note ?? "—"}</div>
                        {e.review_note && <div className="truncate text-amber-700" title={e.review_note}>HR: {e.review_note}</div>}</td>
                      <td className="px-3 py-2">
                        <Badge variant="outline" className={e.status === "approved" ? "border-emerald-500 text-emerald-600" : e.status === "rejected" ? "border-red-500 text-red-600" : "border-amber-500 text-amber-600"}>
                          {e.status === "submitted" ? "to approve" : e.status}
                        </Badge>
                        {e.approved_by_name && <div className="text-[10px] text-muted-foreground">{e.approved_by_name}</div>}
                      </td>
                      {canEdit && (
                        <td className="whitespace-nowrap px-3 py-2 text-right">
                          {e.status === "submitted" && <Button size="sm" variant="ghost" className="h-7 px-2 text-emerald-600" onClick={() => act(() => api.hrHub.review(e.id, "approve"), "Approved")}><CheckCircle2 className="h-4 w-4" /></Button>}
                          <Button size="sm" variant="ghost" className="h-7 px-2" title="Adjust hours" onClick={() => setEdit({ id: e.id, mode: "adjust", hours: String(e.hours_worked), note: "" })}><Pencil className="h-3.5 w-3.5" /></Button>
                          {e.status !== "rejected" && <Button size="sm" variant="ghost" className="h-7 px-2 text-red-600" title="Reject" onClick={() => setEdit({ id: e.id, mode: "reject", hours: "", note: "" })}><XCircle className="h-4 w-4" /></Button>}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
      <DetailSheet open={!!edit} onOpenChange={(v) => !v && setEdit(null)} title={edit?.mode === "reject" ? "Reject entry" : "Adjust hours"} icon={Pencil}
        description="The team member is told, with your reason."
        footer={<Button className="w-full" disabled={!edit?.note.trim() || (edit?.mode === "adjust" && !(Number(edit.hours) > 0))}
          onClick={() => edit && act(() => api.hrHub.review(edit.id, edit.mode, { hours: Number(edit.hours), note: edit.note }), edit.mode === "reject" ? "Rejected" : "Adjusted")}>Save</Button>}>
        {edit?.mode === "adjust" && <div className="space-y-2"><Label>Correct hours</Label><Input type="number" step="0.25" min="0.25" max="24" value={edit.hours} onChange={(e) => setEdit({ ...edit, hours: e.target.value })} /></div>}
        <div className="space-y-2"><Label>Reason</Label><Textarea rows={3} value={edit?.note ?? ""} onChange={(e) => edit && setEdit({ ...edit, note: e.target.value })} /></div>
      </DetailSheet>
      <AddHoursSheet open={adding} onOpenChange={setAdding} people={people.data?.people ?? []} onDone={() => q.refetch()} maxDate={today} />
    </div>
  );
}

function AddHoursSheet({ open, onOpenChange, people, onDone, maxDate }: { open: boolean; onOpenChange: (v: boolean) => void; people: Dict[]; onDone: () => void; maxDate: string }) {
  const [f, setF] = useState<Dict>({ person: "", date: maxDate, hours: "8", note: "" });
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try { await api.hrHub.addEntry({ ...f, hours: Number(f.hours) }); toast.success("Hours recorded"); onOpenChange(false); onDone(); setF({ person: "", date: maxDate, hours: "8", note: "" }); }
    catch (e: any) { toast.error(e?.message || "Could not record"); } finally { setBusy(false); }
  };
  return (
    <DetailSheet open={open} onOpenChange={onOpenChange} icon={Plus} title="Add hours for someone" description="For a missed clock-in. Recorded as approved by you."
      footer={<Button className="w-full" disabled={busy || !f.person || !(Number(f.hours) > 0)} onClick={submit}>{busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Record</Button>}>
      <div className="space-y-2"><Label>Team member</Label>
        <Select value={f.person || undefined} onValueChange={(v) => setF({ ...f, person: v })}><SelectTrigger><SelectValue placeholder="Choose" /></SelectTrigger>
          <SelectContent>{people.filter((p) => p.active).map((p) => <SelectItem key={p.key} value={p.key}>{p.name} · {p.department}</SelectItem>)}</SelectContent></Select></div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2"><Label>Date</Label><Input type="date" max={maxDate} value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></div>
        <div className="space-y-2"><Label>Hours</Label><Input type="number" step="0.25" min="0.25" max="24" value={f.hours} onChange={(e) => setF({ ...f, hours: e.target.value })} /></div>
      </div>
      <div className="space-y-2"><Label>Note</Label><Textarea rows={2} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} placeholder="e.g. Forgot to clock in - confirmed with supervisor" /></div>
    </DetailSheet>
  );
}
