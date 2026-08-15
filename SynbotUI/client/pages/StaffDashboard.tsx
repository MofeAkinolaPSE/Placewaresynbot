import { useState, useEffect } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";
import { api } from "@/lib/api-client";
import { authClient } from "@/lib/auth-client";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { useToast } from "@/hooks/use-toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Sun, Moon, Clock, CheckCircle2, AlertCircle,
  ChevronRight, TrendingUp, Loader2, PlusCircle,
  Activity, Target, Briefcase, ArrowRight,
} from "lucide-react";

// ── Helpers ──────────────────────────────────────────────────────────────

function getGreeting(name: string) {
  const h = new Date().getHours();
  if (h < 12) return { text: `Good morning, ${name}`, Icon: Sun,  color: "text-yellow-400" };
  if (h < 17) return { text: `Good afternoon, ${name}`, Icon: Sun,  color: "text-orange-400" };
  return       { text: `Good evening, ${name}`,   Icon: Moon, color: "text-blue-400"   };
}

function taskPct(status: string): number {
  switch ((status || "").toLowerCase()) {
    case "done": case "completed": return 100;
    case "in_progress":            return 60;
    case "blocked":                return 25;
    case "cancelled":              return 0;
    default:                       return 15;
  }
}

function pctColor(v: number): string {
  if (v >= 80) return "#22c55e";
  if (v >= 50) return "#eab308";
  if (v >= 20) return "#f97316";
  return "#ef4444";
}

function scoreLabel(s: number): string {
  if (s >= 85) return "🔥 Fantastic job";
  if (s >= 70) return "⚡ Keep it up";
  if (s >= 50) return "💪 Good progress";
  return "📋 Let's get moving";
}

// ── SVG micro-components ────────────────────────────────────────────────

function RingProgress({ value, size = 48 }: { value: number; size?: number }) {
  const r = (size - 8) / 2;
  const circ = 2 * Math.PI * r;
  const fill = (value / 100) * circ;
  const c = pctColor(value);
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ flexShrink: 0 }}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="hsl(var(--muted))" strokeWidth="4" />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={c} strokeWidth="4"
        strokeLinecap="round" strokeDasharray={`${fill} ${circ - fill}`}
        transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      <text x={size / 2} y={size / 2 + 4} textAnchor="middle"
        fontSize={size < 40 ? 9 : 10} fontWeight="600" fill={c}>{value}%</text>
    </svg>
  );
}

function ScoreGauge({ value }: { value: number }) {
  const r = 54;
  const circ = Math.PI * r;
  const fill = (value / 100) * circ;
  const c = pctColor(value);
  return (
    <svg width="140" height="82" viewBox="0 0 140 82">
      <path d="M10,72 A60,60 0 0,1 130,72" fill="none" stroke="hsl(var(--muted))" strokeWidth="12" strokeLinecap="round" />
      <path d="M10,72 A60,60 0 0,1 130,72" fill="none" stroke={c} strokeWidth="12"
        strokeLinecap="round" strokeDasharray={`${fill} ${circ}`} />
      <text x="70" y="65" textAnchor="middle" fontSize="22" fontWeight="700" fill={c}>{value}%</text>
      <text x="70" y="80" textAnchor="middle" fontSize="10" fill="hsl(var(--muted-foreground))">Score</text>
    </svg>
  );
}

// ── Main component ──────────────────────────────────────────────────────

export default function StaffDashboard() {
  const queryClient = useQueryClient();
  const subject = authClient.getSubject();
  const { toast } = useToast();

  const [logHoursOpen, setLogHoursOpen] = useState(false);
  const [timesheetForm, setTimesheetForm] = useState({
    staff_id: "",
    date: new Date().toISOString().slice(0, 10),
    hours_worked: "8",
    department: "Operations",
    activity_note: "",
  });

  useRealtimeChannel("staff_updates", () => {
    if (!subject) return;
    void queryClient.invalidateQueries({ queryKey: ["staff-dashboard", subject] });
  }, !!subject);

  const { data, isLoading } = useQuery({
    queryKey: ["staff-dashboard", subject],
    queryFn: () => api.staff.dashboard(subject as string),
    enabled: !!subject,
  });

  const identity = data?.identity;
  const name = identity?.display_name || "there";
  const { text: greetText, Icon: GreetIcon, color: greetColor } = getGreeting(name);
  const hoursThisWeek = identity?.hours_this_week ?? 0;

  // Pre-fill the Log Hours form's Staff ID once the real staff_id resolves
  // (linked via email to placeware_staff) -- never overwrite a value the
  // user already typed themselves.
  useEffect(() => {
    if (identity?.staff_id) {
      setTimesheetForm((p) => (p.staff_id ? p : { ...p, staff_id: identity.staff_id as string }));
    }
  }, [identity?.staff_id]);

  const tasks         = Array.isArray(data?.tasks)              ? data.tasks              : [];
  const projects      = Array.isArray(data?.assigned_projects)  ? data.assigned_projects  : [];
  const activities    = Array.isArray(data?.activities)         ? data.activities         : [];
  const pending       = Array.isArray(data?.pending_approvals)  ? data.pending_approvals  : [];

  // ── Derived metrics ─────────────────────────────────────────────────
  const completedCount = tasks.filter((t: any) =>
    t.status === "completed" || t.status === "done").length;
  const activeCount = tasks.filter((t: any) =>
    ["open", "in_progress", "pending"].includes((t.status || "").toLowerCase())).length;
  const today = new Date();
  const dueTodayCount = tasks.filter((t: any) =>
    t.due_date && new Date(t.due_date).toDateString() === today.toDateString()).length;
  const score    = tasks.length > 0 ? Math.round((completedCount / tasks.length) * 100) : 0;
  const progress = tasks.length > 0 ? Math.round((completedCount / tasks.length) * 100) : 0;

  // ── Timesheet mutation ───────────────────────────────────────────────
  const tsSubmit = useMutation({
    mutationFn: () =>
      api.staff.submitTimesheet({
        staff_id: timesheetForm.staff_id.trim(),
        date: timesheetForm.date,
        hours_worked: Number(timesheetForm.hours_worked),
        department: timesheetForm.department.trim(),
        activity_note: timesheetForm.activity_note.trim() || undefined,
      }),
    onSuccess: () => {
      toast({ title: "Hours logged", description: "Timesheet entry recorded." });
      setLogHoursOpen(false);
      setTimesheetForm((p) => ({ ...p, activity_note: "", hours_worked: "8", date: new Date().toISOString().slice(0, 10) }));
      if (subject) void queryClient.invalidateQueries({ queryKey: ["staff-dashboard", subject] });
      void queryClient.invalidateQueries({ queryKey: ["workforce-dashboard"] });
    },
    onError: (e: any) => {
      toast({ title: "Failed to log hours", description: e?.message, variant: "destructive" });
    },
  });

  const resumeTask = tasks.find((t: any) => t.status === "in_progress") ?? tasks[0];

  const statCards = [
    { label: "Active Goals",  value: activeCount,       icon: Target,       color: "text-blue-400"    },
    { label: "Progress",      value: `${progress}%`,    icon: TrendingUp,   color: "text-green-400"   },
    { label: "Completed",     value: completedCount,    icon: CheckCircle2, color: "text-emerald-400" },
    { label: "Due Today",     value: dueTodayCount,     icon: AlertCircle,  color: "text-orange-400"  },
  ];

  // Each row shows a real, currently-available number — no fabricated
  // trend badges or sparklines. There's no stored historical snapshot for
  // personal performance anywhere in this schema, so a genuine period-over-
  // period change can't be computed honestly yet.
  const statsPanel = [
    { label: "Performance", sub: "Based on tasks",    value: tasks.length > 0 ? `${progress}%` : "No tasks yet",         color: "#f59e0b" },
    { label: "Projects",    sub: "Completion rate",    value: `${completedCount} completed`,                             color: "#22c55e" },
    { label: "Activity",    sub: "Recent events",      value: `${activities.length} event${activities.length === 1 ? "" : "s"}`, color: "#38bdf8" },
  ];

  // ── Render ───────────────────────────────────────────────────────────
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionTransitions.standard}
      className="pw-page-surface space-y-5 p-6"
    >
      {/* Greeting + Log Hours button */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-2.5">
          <GreetIcon className={`h-6 w-6 shrink-0 ${greetColor}`} />
          <div>
            <h1 className="text-2xl font-bold leading-tight">{greetText}</h1>
            <p className="text-sm text-muted-foreground">Let's see how you're doing today</p>
          </div>
        </div>

        <Dialog open={logHoursOpen} onOpenChange={setLogHoursOpen}>
          <DialogTrigger asChild>
            <Button size="sm" className="gap-1.5">
              <PlusCircle className="h-4 w-4" /> Log Hours
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Log Work Hours</DialogTitle>
              <DialogDescription>Submit your hours worked for any date.</DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-2">
              <div className="grid gap-2">
                <Label>Staff ID</Label>
                <Input value={timesheetForm.staff_id}
                  onChange={(e) => setTimesheetForm((p) => ({ ...p, staff_id: e.target.value }))}
                  placeholder="Your staff/user ID" />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="grid gap-2">
                  <Label>Date</Label>
                  <Input type="date" value={timesheetForm.date}
                    onChange={(e) => setTimesheetForm((p) => ({ ...p, date: e.target.value }))} />
                </div>
                <div className="grid gap-2">
                  <Label>Hours Worked</Label>
                  <Input type="number" min="0.5" max="24" step="0.5"
                    value={timesheetForm.hours_worked}
                    onChange={(e) => setTimesheetForm((p) => ({ ...p, hours_worked: e.target.value }))} />
                </div>
              </div>
              <div className="grid gap-2">
                <Label>Department</Label>
                <Input value={timesheetForm.department}
                  onChange={(e) => setTimesheetForm((p) => ({ ...p, department: e.target.value }))}
                  placeholder="Operations, Finance, HR..." />
              </div>
              <div className="grid gap-2">
                <Label>Activity Note</Label>
                <Textarea value={timesheetForm.activity_note}
                  onChange={(e) => setTimesheetForm((p) => ({ ...p, activity_note: e.target.value }))}
                  placeholder="Summarise what you worked on" />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setLogHoursOpen(false)}>Cancel</Button>
              <Button onClick={() => tsSubmit.mutate()}
                disabled={
                  tsSubmit.isPending ||
                  !timesheetForm.staff_id.trim() || !timesheetForm.date || !timesheetForm.department.trim() ||
                  !Number.isFinite(Number(timesheetForm.hours_worked)) ||
                  Number(timesheetForm.hours_worked) <= 0 || Number(timesheetForm.hours_worked) > 24
                }>
                {tsSubmit.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Submit Entry
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {/* Profile + Resume card | Score gauge */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="pw-surface-interactive lg:col-span-2">
          <CardContent className="flex items-center gap-5 p-5">
            {/* Avatar */}
            <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-primary/60 to-primary/20 text-2xl font-bold text-primary select-none">
              {name.charAt(0).toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-lg font-bold truncate">{name}</p>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <span className="flex items-center gap-1"><Briefcase className="h-3 w-3" /> {identity?.department || identity?.email || "—"}</span>
                <span className="flex items-center gap-1"><Clock className="h-3 w-3" /> {hoursThisWeek.toFixed(1)}h this week</span>
              </div>
            </div>
            {resumeTask && (
              <div className="hidden md:flex flex-col items-start gap-1.5 rounded-xl border border-border/50 bg-muted/30 p-3 min-w-[180px] max-w-[220px]">
                <p className="text-xs font-medium text-muted-foreground">Continue where you left off ↩</p>
                <p className="text-sm font-semibold line-clamp-2 leading-snug">{resumeTask.title}</p>
                <Button variant="outline" size="sm" className="mt-0.5 h-7 gap-1 text-xs">
                  Jump to task <ArrowRight className="h-3 w-3" />
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="pw-surface-interactive">
          <CardContent className="flex flex-col items-center justify-center gap-1 p-5">
            <ScoreGauge value={score} />
            <p className="text-sm text-muted-foreground text-center mt-1">{scoreLabel(score)}</p>
          </CardContent>
        </Card>
      </div>

      {/* Stats strip */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {statCards.map((s) => {
          const Icon = s.icon;
          return (
            <Card key={s.label} className="pw-surface-interactive cursor-pointer hover:border-border/80 transition-colors">
              <CardContent className="flex items-center justify-between p-4">
                <div>
                  <p className="text-xs text-muted-foreground">{s.label}</p>
                  <p className={`text-2xl font-bold mt-0.5 ${s.color}`}>{isLoading ? "–" : s.value}</p>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <Icon className={`h-5 w-5 ${s.color} opacity-70`} />
                  <ChevronRight className="h-4 w-4 text-muted-foreground" />
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Main: Tasks (2/3) + Statistics sidebar (1/3) */}
      <div className="grid gap-5 lg:grid-cols-3">

        {/* Left column */}
        <div className="lg:col-span-2 space-y-4">

          {/* My Tasks */}
          <Card className="pw-surface-interactive">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">My Tasks</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2.5">
              {isLoading ? (
                <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" /> Loading tasks…
                </div>
              ) : tasks.length === 0 ? (
                <p className="py-4 text-sm text-muted-foreground text-center">No assigned tasks. You're all caught up!</p>
              ) : tasks.slice(0, 6).map((task: any, idx: number) => {
                const pct = taskPct(task.status);
                return (
                  <motion.div key={task.task_id || idx}
                    initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: idx * 0.05 }}
                    className="flex items-center gap-3 rounded-xl border border-border/50 bg-muted/20 px-4 py-3">
                    <span className="w-5 shrink-0 text-sm font-medium text-muted-foreground">{idx + 1}.</span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{task.title}</p>
                      <div className="mt-0.5 flex flex-wrap items-center gap-2">
                        {task.due_date && (
                          <span className="text-xs text-muted-foreground">
                            Due {new Date(task.due_date).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}
                          </span>
                        )}
                        {task.priority && task.priority !== "medium" && (
                          <Badge variant="outline" className="h-4 px-1 text-[10px]">{task.priority}</Badge>
                        )}
                      </div>
                    </div>
                    <RingProgress value={pct} size={44} />
                  </motion.div>
                );
              })}
            </CardContent>
          </Card>

          {/* Assigned Projects */}
          {projects.length > 0 && (
            <Card className="pw-surface-interactive">
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Assigned Projects</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2.5">
                {projects.slice(0, 4).map((p: any) => (
                  <div key={p.project_id} className="flex items-center justify-between rounded-xl border border-border/50 bg-muted/20 px-4 py-3 gap-3">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{p.name}</p>
                      <p className="text-xs text-muted-foreground">{p.activity_type || "Operational workflow"}</p>
                    </div>
                    <Badge variant={p.status === "completed" ? "default" : "secondary"} className="shrink-0">
                      {p.status}
                    </Badge>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          {/* Pending Approvals */}
          {pending.length > 0 && (
            <Card className="pw-surface-interactive">
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  Pending Approvals
                  <Badge variant="destructive" className="text-xs">{pending.length}</Badge>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {pending.slice(0, 3).map((item: any) => (
                  <div key={item.event_id} className="rounded-xl border border-orange-500/20 bg-orange-500/5 px-4 py-3">
                    <p className="text-sm font-medium">{item.event_type}</p>
                    <p className="text-xs text-muted-foreground">{item.timestamp || "-"}</p>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </div>

        {/* Right sidebar */}
        <div className="space-y-4">

          {/* Statistics */}
          <Card className="pw-surface-interactive">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">Statistics</CardTitle>
                <span className="text-xs text-muted-foreground">
                  {new Date().toLocaleString("default", { month: "short", year: "numeric" })}
                </span>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {statsPanel.map((stat) => (
                <div key={stat.label}
                  className="flex items-center justify-between gap-3 rounded-xl border border-border/40 bg-muted/20 p-3">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold">{stat.label}</p>
                    <p className="text-xs text-muted-foreground">{stat.sub}</p>
                  </div>
                  <p className="text-sm font-bold shrink-0" style={{ color: stat.color }}>{stat.value}</p>
                </div>
              ))}
            </CardContent>
          </Card>

          {/* Recent Activity */}
          <Card className="pw-surface-interactive">
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Activity className="h-4 w-4" /> Recent Activity
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {activities.length === 0 ? (
                <p className="py-2 text-xs text-muted-foreground">No recent activity recorded.</p>
              ) : activities.slice(0, 5).map((a: any) => (
                <div key={a.event_id} className="flex items-start gap-2.5 rounded-lg py-1.5">
                  <div className="mt-1 h-2 w-2 shrink-0 rounded-full bg-primary/60" />
                  <div className="min-w-0">
                    <p className="text-xs font-medium truncate">{a.event_type}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {a.timestamp ? new Date(a.timestamp).toLocaleString() : "-"}
                    </p>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </motion.div>
  );
}
