import { useState, useEffect, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";
import { api } from "@/lib/api-client";
import { authClient } from "@/lib/auth-client";
import { useToast } from "@/hooks/use-toast";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Clock, LogIn, LogOut, PlusCircle, Loader2, CalendarDays, BarChart3 } from "lucide-react";

// ── Constants ────────────────────────────────────────────────────────────────

const LS_KEY    = "pw_clock_in_at";
const LS_DEPT   = "pw_clock_in_dept";
const DAYS      = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const DEPTS     = ["Operations", "Finance", "HR", "Sales", "Management", "Compliance", "Procurement"];
const HOURS_GOAL = 40;

// ── Helpers ──────────────────────────────────────────────────────────────────

function getWeekBounds() {
  const now = new Date();
  const mon = new Date(now);
  mon.setDate(now.getDate() - ((now.getDay() + 6) % 7));
  mon.setHours(0, 0, 0, 0);
  return mon;
}

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function formatElapsed(ms: number): string {
  const total = Math.floor(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

// ── Sub-components ────────────────────────────────────────────────────────────

/** Horizontal week-by-day bar chart */
function WeeklyBars({ data }: { data: { day: string; hours: number; isToday: boolean }[] }) {
  const max = Math.max(...data.map((d) => d.hours), 8);
  return (
    <div className="flex items-end justify-between gap-1.5 h-16">
      {data.map((d) => {
        const h = max > 0 ? (d.hours / max) * 52 : 0;
        return (
          <div key={d.day} className="flex flex-col items-center gap-1 flex-1">
            <span className="text-[10px] text-muted-foreground leading-none min-h-[12px]">
              {d.hours > 0 ? `${d.hours.toFixed(1)}` : ""}
            </span>
            <div className="w-full flex flex-col justify-end" style={{ height: "52px" }}>
              <div
                className={`w-full rounded-t transition-all duration-500 ${d.isToday ? "bg-primary" : "bg-primary/40"}`}
                style={{ height: `${Math.max(h, d.hours > 0 ? 4 : 0)}px` }}
              />
            </div>
            <span className={`text-[10px] leading-none ${d.isToday ? "font-bold text-primary" : "text-muted-foreground"}`}>
              {d.day}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function StaffTimeTracker() {
  const queryClient = useQueryClient();
  const subject     = authClient.getSubject();
  const { toast }   = useToast();

  // ── Clock-in state (persisted in localStorage) ───────────────────────────
  const [clockedInAt, setClockedInAt] = useState<number | null>(() => {
    const v = localStorage.getItem(LS_KEY);
    return v ? Number(v) : null;
  });
  const [elapsed,  setElapsed]  = useState(0);
  const [clockDept, setClockDept] = useState(() => localStorage.getItem(LS_DEPT) || "Operations");
  const [clockNote, setClockNote] = useState("");

  // Live timer ticker
  useEffect(() => {
    if (!clockedInAt) { setElapsed(0); return; }
    const tick = () => setElapsed(Date.now() - clockedInAt);
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [clockedInAt]);

  const handleClockIn = () => {
    const now = Date.now();
    localStorage.setItem(LS_KEY,  String(now));
    localStorage.setItem(LS_DEPT, clockDept);
    setClockedInAt(now);
    toast({
      title: "Clocked in",
      description: `Shift started at ${new Date(now).toLocaleTimeString()} · ${clockDept}`,
    });
  };

  const clockOutMutation = useMutation({
    mutationFn: (hrs: number) =>
      api.staff.submitTimesheet({
        staff_id:      (subject || "").trim(),
        date:          isoDate(new Date()),
        hours_worked:  hrs,
        department:    clockDept,
        activity_note: clockNote.trim() || `Shift: clocked out at ${new Date().toLocaleTimeString()}`,
      }),
    onSuccess: (_data, hrs) => {
      localStorage.removeItem(LS_KEY);
      localStorage.removeItem(LS_DEPT);
      setClockedInAt(null);
      setElapsed(0);
      setClockNote("");
      toast({ title: "Clocked out", description: `${hrs}h recorded to your timesheet.` });
      void queryClient.invalidateQueries({ queryKey: ["timesheets"] });
      void queryClient.invalidateQueries({ queryKey: ["workforce-dashboard"] });
    },
    onError: (e: any) => {
      toast({ title: "Clock-out failed", description: e?.message, variant: "destructive" });
    },
  });

  const handleClockOut = () => {
    if (!clockedInAt) return;
    const raw = (Date.now() - clockedInAt) / 3_600_000;
    const hrs  = Math.max(0.5, parseFloat(raw.toFixed(2)));
    clockOutMutation.mutate(hrs);
  };

  // ── Manual log form ───────────────────────────────────────────────────────
  const [logOpen, setLogOpen] = useState(false);
  const [form, setForm] = useState({
    staff_id:     subject || "",
    date:         isoDate(new Date()),
    hours_worked: "8",
    department:   "Operations",
    activity_note: "",
  });

  const logMutation = useMutation({
    mutationFn: () =>
      api.staff.submitTimesheet({
        staff_id:      form.staff_id.trim(),
        date:          form.date,
        hours_worked:  Number(form.hours_worked),
        department:    form.department.trim(),
        activity_note: form.activity_note.trim() || undefined,
      }),
    onSuccess: () => {
      toast({ title: "Entry recorded", description: "Timesheet entry saved." });
      setLogOpen(false);
      setForm((p) => ({ ...p, activity_note: "", hours_worked: "8", date: isoDate(new Date()) }));
      void queryClient.invalidateQueries({ queryKey: ["timesheets"] });
      void queryClient.invalidateQueries({ queryKey: ["workforce-dashboard"] });
    },
    onError: (e: any) => {
      toast({ title: "Failed to log hours", description: e?.message, variant: "destructive" });
    },
  });

  // ── Timesheet data ────────────────────────────────────────────────────────
  const { data: tsRaw, isLoading } = useQuery({
    queryKey: ["timesheets"],
    queryFn: () => api.staff.timesheets(undefined, 60),
  });

  const sheets = useMemo(() => {
    if (Array.isArray(tsRaw)) return tsRaw as any[];
    if (Array.isArray((tsRaw as any)?.data)) return (tsRaw as any).data as any[];
    return [];
  }, [tsRaw]);

  // ── Weekly breakdown ──────────────────────────────────────────────────────
  const mon = useMemo(() => getWeekBounds(), []);

  const weeklyData = useMemo(() => {
    const todayDow = (new Date().getDay() + 6) % 7; // 0=Mon…6=Sun
    const map: Record<string, number> = {};
    DAYS.forEach((_, i) => {
      const d = new Date(mon);
      d.setDate(mon.getDate() + i);
      map[isoDate(d)] = 0;
    });
    sheets.forEach((s) => {
      const dt = (s.date as string)?.slice(0, 10);
      if (dt && dt in map) map[dt] += Number(s.hours_worked) || 0;
    });
    return DAYS.map((day, i) => {
      const d = new Date(mon);
      d.setDate(mon.getDate() + i);
      return { day, hours: map[isoDate(d)], isToday: i === todayDow };
    });
  }, [sheets, mon]);

  const totalHours = weeklyData.reduce((s, d) => s + d.hours, 0);
  const weekPct    = Math.min(100, Math.round((totalHours / HOURS_GOAL) * 100));

  const weekLabel = `Week of ${mon.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}`;

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionTransitions.standard}
      className="pw-page-surface space-y-5 p-6"
    >
      {/* ── Header ── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Clock className="h-6 w-6 text-primary" /> Time Tracker
          </h1>
          <p className="text-sm text-muted-foreground">{weekLabel}</p>
        </div>

        <Dialog open={logOpen} onOpenChange={setLogOpen}>
          <DialogTrigger asChild>
            <Button variant="outline" size="sm" className="gap-1.5">
              <PlusCircle className="h-4 w-4" /> Add Entry
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Manual Timesheet Entry</DialogTitle>
              <DialogDescription>Log hours for any date.</DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-2">
              <div className="grid gap-2">
                <Label>Staff ID</Label>
                <Input value={form.staff_id} onChange={(e) => setForm((p) => ({ ...p, staff_id: e.target.value }))} />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="grid gap-2">
                  <Label>Date</Label>
                  <Input type="date" value={form.date} onChange={(e) => setForm((p) => ({ ...p, date: e.target.value }))} />
                </div>
                <div className="grid gap-2">
                  <Label>Hours</Label>
                  <Input type="number" min="0.5" max="24" step="0.5" value={form.hours_worked}
                    onChange={(e) => setForm((p) => ({ ...p, hours_worked: e.target.value }))} />
                </div>
              </div>
              <div className="grid gap-2">
                <Label>Department</Label>
                <Select value={form.department} onValueChange={(v) => setForm((p) => ({ ...p, department: v }))}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {DEPTS.map((d) => <SelectItem key={d} value={d}>{d}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <Label>Activity Note</Label>
                <Textarea value={form.activity_note}
                  onChange={(e) => setForm((p) => ({ ...p, activity_note: e.target.value }))}
                  placeholder="What did you work on?" />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setLogOpen(false)}>Cancel</Button>
              <Button
                onClick={() => logMutation.mutate()}
                disabled={
                  logMutation.isPending ||
                  !form.staff_id.trim() || !form.date || !form.department.trim() ||
                  !Number.isFinite(Number(form.hours_worked)) ||
                  Number(form.hours_worked) <= 0 || Number(form.hours_worked) > 24
                }
              >
                {logMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Submit
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {/* ── Clock card + Weekly chart ── */}
      <div className="grid gap-5 lg:grid-cols-2">

        {/* Clock In / Out */}
        <Card className="pw-surface-interactive">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              {clockedInAt ? (
                <>
                  <span className="h-2.5 w-2.5 rounded-full bg-green-500 animate-pulse" />
                  Shift in progress
                </>
              ) : (
                <>
                  <span className="h-2.5 w-2.5 rounded-full bg-muted-foreground/40" />
                  Not clocked in
                </>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col items-center gap-4 pb-6">
            {/* Big timer display */}
            <div className="font-mono text-5xl font-bold tabular-nums tracking-tight text-primary">
              {clockedInAt ? formatElapsed(elapsed) : "00:00:00"}
            </div>

            {clockedInAt && (
              <p className="text-sm text-muted-foreground text-center">
                Started at {new Date(clockedInAt).toLocaleTimeString()}
                &nbsp;·&nbsp;
                <span className="font-semibold text-foreground">{(elapsed / 3_600_000).toFixed(2)}h elapsed</span>
              </p>
            )}

            {/* Department selector (always visible for clock-in choice) */}
            <div className="w-full max-w-xs space-y-1.5">
              <Label className="text-xs">Department</Label>
              <Select value={clockDept} onValueChange={(v) => {
                setClockDept(v);
                if (clockedInAt) localStorage.setItem(LS_DEPT, v);
              }}>
                <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {DEPTS.map((d) => <SelectItem key={d} value={d}>{d}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>

            {/* Optional note when clocked in */}
            {clockedInAt && (
              <div className="w-full max-w-xs space-y-1.5">
                <Label className="text-xs">Activity note (optional)</Label>
                <Input
                  value={clockNote}
                  onChange={(e) => setClockNote(e.target.value)}
                  placeholder="What are you working on?"
                  className="h-9 text-sm"
                />
              </div>
            )}

            {/* Clock In / Out button */}
            {!clockedInAt ? (
              <Button size="lg" className="gap-2 px-10 mt-1" onClick={handleClockIn}>
                <LogIn className="h-5 w-5" /> Clock In
              </Button>
            ) : (
              <Button
                size="lg" variant="destructive" className="gap-2 px-10 mt-1"
                onClick={handleClockOut} disabled={clockOutMutation.isPending}
              >
                {clockOutMutation.isPending
                  ? <Loader2 className="h-5 w-5 animate-spin" />
                  : <LogOut className="h-5 w-5" />
                }
                Clock Out &amp; Save
              </Button>
            )}
          </CardContent>
        </Card>

        {/* Weekly hours chart */}
        <Card className="pw-surface-interactive">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base flex items-center gap-2">
                <BarChart3 className="h-4 w-4" /> Hours This Week
              </CardTitle>
              <span className="text-sm">
                <span className="font-semibold text-primary">{totalHours.toFixed(1)}</span>
                <span className="text-muted-foreground"> / {HOURS_GOAL}h</span>
              </span>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Progress bar */}
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>Weekly goal</span>
                <span className={weekPct >= 100 ? "text-green-400 font-semibold" : ""}>{weekPct}%</span>
              </div>
              <div className="h-2 rounded-full bg-muted overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${weekPct >= 100 ? "bg-green-500" : "bg-primary"}`}
                  style={{ width: `${weekPct}%` }}
                />
              </div>
            </div>

            <WeeklyBars data={weeklyData} />

            {/* Summary stats */}
            <div className="grid grid-cols-3 gap-2 pt-1">
              {[
                { label: "Today",   value: weeklyData.find((d) => d.isToday)?.hours.toFixed(1) ?? "0.0", unit: "h" },
                { label: "Average", value: (totalHours / 5).toFixed(1), unit: "h/day" },
                { label: "Goal",    value: `${weekPct}`, unit: "%" },
              ].map((s) => (
                <div key={s.label} className="rounded-lg border border-border/40 bg-muted/20 p-2.5 text-center">
                  <p className="text-lg font-bold text-primary">{s.value}<span className="text-xs font-normal text-muted-foreground ml-0.5">{s.unit}</span></p>
                  <p className="text-[10px] text-muted-foreground">{s.label}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ── Timesheet History ── */}
      <Card className="pw-surface-interactive">
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <CalendarDays className="h-4 w-4" /> Timesheet History
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground justify-center">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading timesheets…
            </div>
          ) : sheets.length === 0 ? (
            <p className="py-8 text-sm text-muted-foreground text-center">
              No timesheet entries yet. Clock in or add a manual entry to get started.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50 text-xs text-muted-foreground">
                    <th className="pb-2.5 text-left font-medium">Date</th>
                    <th className="pb-2.5 text-right font-medium">Hours</th>
                    <th className="pb-2.5 pl-4 text-left font-medium">Department</th>
                    <th className="pb-2.5 pl-4 text-left font-medium hidden md:table-cell">Note</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/30">
                  {sheets.slice(0, 25).map((s: any, i: number) => {
                    const isThisWeek = s.date && new Date(s.date) >= mon;
                    return (
                      <motion.tr key={s.id ?? i}
                        initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                        transition={{ delay: i * 0.02 }}
                        className="hover:bg-muted/20 transition-colors">
                        <td className="py-2.5">
                          <div className="flex items-center gap-2">
                            {isThisWeek && (
                              <span className="h-1.5 w-1.5 rounded-full bg-primary shrink-0" />
                            )}
                            <span>
                              {s.date
                                ? new Date(s.date).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })
                                : "–"}
                            </span>
                          </div>
                        </td>
                        <td className="py-2.5 text-right">
                          <span className="font-semibold text-primary">{s.hours_worked}h</span>
                        </td>
                        <td className="py-2.5 pl-4">
                          <Badge variant="outline" className="text-xs">{s.department || "–"}</Badge>
                        </td>
                        <td className="py-2.5 pl-4 hidden md:table-cell text-muted-foreground max-w-[220px] truncate">
                          {s.activity_note || "–"}
                        </td>
                      </motion.tr>
                    );
                  })}
                </tbody>
              </table>
              {sheets.length > 25 && (
                <p className="mt-3 text-center text-xs text-muted-foreground">
                  Showing 25 of {sheets.length} entries
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}
