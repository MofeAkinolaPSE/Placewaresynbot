import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { api, ApiError } from "@/lib/api-client";
import { authClient } from "@/lib/auth-client";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";
import { Loader2, PlusCircle } from "lucide-react";
import { useState } from "react";

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.kind === "permission") return "You do not have access to this staff dashboard.";
    if (error.kind === "session") return "Session expired. Please sign in again.";
    return error.message || "Failed to load staff dashboard.";
  }
  return error instanceof Error ? error.message : "Failed to load staff dashboard.";
}

export default function StaffDashboard() {
  const queryClient = useQueryClient();
  const subject = authClient.getSubject();
  const { toast } = useToast();
  const [logHoursOpen, setLogHoursOpen] = useState(false);
  const [timesheetForm, setTimesheetForm] = useState({
    staff_id: subject || "",
    date: new Date().toISOString().slice(0, 10),
    hours_worked: "8",
    department: "Operations",
    activity_note: "",
  });

  useRealtimeChannel("staff_updates", () => {
    if (!subject) return;
    void queryClient.invalidateQueries({ queryKey: ["staff-dashboard", subject] });
  }, !!subject);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["staff-dashboard", subject],
    queryFn: () => api.staff.dashboard(subject as string),
    enabled: !!subject,
  });

  const tasks = Array.isArray(data?.tasks) ? data.tasks : [];
  const assignedProjects = Array.isArray(data?.assigned_projects) ? data.assigned_projects : [];
  const activities = Array.isArray(data?.activities) ? data.activities : [];
  const pending = Array.isArray(data?.pending_approvals) ? data.pending_approvals : [];
  const kpis = Array.isArray(data?.kpis) ? data.kpis : [];

  const submitTimesheetMutation = useMutation({
    mutationFn: () =>
      api.staff.submitTimesheet({
        staff_id: timesheetForm.staff_id.trim(),
        date: timesheetForm.date,
        hours_worked: Number(timesheetForm.hours_worked),
        department: timesheetForm.department.trim(),
        activity_note: timesheetForm.activity_note.trim() || undefined,
      }),
    onSuccess: () => {
      toast({ title: "Hours logged", description: "Your timesheet entry was recorded successfully." });
      setLogHoursOpen(false);
      setTimesheetForm((prev) => ({ ...prev, activity_note: "", hours_worked: "8", date: new Date().toISOString().slice(0, 10) }));
      void queryClient.invalidateQueries({ queryKey: ["timesheets"] });
      if (subject) {
        void queryClient.invalidateQueries({ queryKey: ["staff-dashboard", subject] });
      }
      void queryClient.invalidateQueries({ queryKey: ["workforce-dashboard"] });
    },
    onError: (err: any) => {
      toast({
        title: "Failed to log hours",
        description: err?.message || "Unable to record timesheet entry right now.",
        variant: "destructive",
      });
    },
  });

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionTransitions.standard}
      className="pw-page-surface space-y-6 p-8"
    >
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Staff Dashboard</h1>
        <p className="text-muted-foreground">Personal work feed, approvals, and assigned tasks.</p>
      </div>

      <Card className="pw-surface-interactive">
        <CardHeader>
          <CardTitle className="text-base">Log Work Hours</CardTitle>
        </CardHeader>
        <CardContent className="flex items-center justify-between gap-4">
          <p className="text-sm text-muted-foreground">
            Record your daily hours so HR and management can track operational effort accurately.
          </p>
          <Dialog open={logHoursOpen} onOpenChange={setLogHoursOpen}>
            <DialogTrigger asChild>
              <Button>
                <PlusCircle className="mr-2 h-4 w-4" />
                Log Hours
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Timesheet Entry</DialogTitle>
                <DialogDescription>Submit your hours worked for today or any selected date.</DialogDescription>
              </DialogHeader>
              <div className="grid gap-4 py-2">
                <div className="grid gap-2">
                  <Label htmlFor="staff-id">Staff ID</Label>
                  <Input
                    id="staff-id"
                    value={timesheetForm.staff_id}
                    onChange={(e) => setTimesheetForm((prev) => ({ ...prev, staff_id: e.target.value }))}
                    placeholder="Your staff/user ID"
                  />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="grid gap-2">
                    <Label htmlFor="work-date">Date</Label>
                    <Input
                      id="work-date"
                      type="date"
                      value={timesheetForm.date}
                      onChange={(e) => setTimesheetForm((prev) => ({ ...prev, date: e.target.value }))}
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="work-hours">Hours Worked</Label>
                    <Input
                      id="work-hours"
                      type="number"
                      min="0.5"
                      max="24"
                      step="0.5"
                      value={timesheetForm.hours_worked}
                      onChange={(e) => setTimesheetForm((prev) => ({ ...prev, hours_worked: e.target.value }))}
                    />
                  </div>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="work-dept">Department</Label>
                  <Input
                    id="work-dept"
                    value={timesheetForm.department}
                    onChange={(e) => setTimesheetForm((prev) => ({ ...prev, department: e.target.value }))}
                    placeholder="Operations, Finance, HR..."
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="work-note">Activity Note</Label>
                  <Textarea
                    id="work-note"
                    value={timesheetForm.activity_note}
                    onChange={(e) => setTimesheetForm((prev) => ({ ...prev, activity_note: e.target.value }))}
                    placeholder="Summarize what you worked on"
                  />
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setLogHoursOpen(false)}>Cancel</Button>
                <Button
                  onClick={() => submitTimesheetMutation.mutate()}
                  disabled={
                    submitTimesheetMutation.isPending ||
                    !timesheetForm.staff_id.trim() ||
                    !timesheetForm.date ||
                    !timesheetForm.department.trim() ||
                    !Number.isFinite(Number(timesheetForm.hours_worked)) ||
                    Number(timesheetForm.hours_worked) <= 0 ||
                    Number(timesheetForm.hours_worked) > 24
                  }
                >
                  {submitTimesheetMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Submit Entry
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </CardContent>
      </Card>

      {isError && <p className="text-sm text-destructive">{errorText(error)}</p>}

      <div className="grid gap-4 md:grid-cols-3">
        {kpis.length > 0 ? kpis.map((kpi: any) => (
          <Card key={kpi.key} className="pw-surface-interactive">
            <CardHeader>
              <CardTitle className="text-sm font-medium">{kpi.label}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{kpi.value}</div>
            </CardContent>
          </Card>
        )) : (
          <Card className="pw-surface-interactive md:col-span-3">
            <CardContent className="py-8 text-sm text-muted-foreground">
              {isLoading ? "Loading KPI widgets..." : "No KPI widgets available."}
            </CardContent>
          </Card>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="pw-surface-interactive">
          <CardHeader>
            <CardTitle>Assigned Projects</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {assignedProjects.length === 0 ? (
              <p className="text-sm text-muted-foreground">{isLoading ? "Loading projects..." : "No project assignments yet."}</p>
            ) : assignedProjects.map((project: any) => (
              <div key={project.project_id} className="pw-surface-base rounded-xl p-3 space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="font-medium">{project.name}</p>
                    <p className="text-xs text-muted-foreground">{project.activity_type || "Operational workflow"}</p>
                  </div>
                  <Badge variant={project.status === "completed" ? "default" : "secondary"}>{project.status}</Badge>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Badge variant="outline">Stage: {project.workflow_stage || "unassigned"}</Badge>
                  <Badge variant="outline">QC: {project.quality_check_status || "pending"}</Badge>
                  <Badge variant="outline">NAFDAC: {project.nafdac_sampling_status || "pending"}</Badge>
                </div>
                <p className="text-xs text-muted-foreground">Supplier: {project.supplier_name || "Not set"}</p>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card className="pw-surface-interactive">
          <CardHeader>
            <CardTitle>Pending Approvals</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {pending.length === 0 ? (
              <p className="text-sm text-muted-foreground">{isLoading ? "Loading approvals..." : "No pending approvals."}</p>
            ) : pending.map((item: any) => (
              <div key={item.event_id} className="pw-surface-base rounded-xl p-3">
                <p className="font-medium">{item.event_type}</p>
                <p className="text-xs text-muted-foreground">{item.timestamp || "-"}</p>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card className="pw-surface-interactive">
          <CardHeader>
            <CardTitle>My Tasks</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {tasks.length === 0 ? (
              <p className="text-sm text-muted-foreground">{isLoading ? "Loading tasks..." : "No assigned tasks."}</p>
            ) : tasks.map((task: any) => (
              <div key={task.task_id} className="pw-surface-base rounded-xl p-3 flex items-start justify-between gap-2">
                <div>
                  <p className="font-medium">{task.title}</p>
                  <p className="text-xs text-muted-foreground">{task.description || "No description"}</p>
                </div>
                <Badge variant={task.status === "done" ? "default" : "secondary"}>{task.status}</Badge>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card className="pw-surface-interactive">
        <CardHeader>
          <CardTitle>Recent Activity</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {activities.length === 0 ? (
            <p className="text-sm text-muted-foreground">{isLoading ? "Loading activity..." : "No recent activity for this user."}</p>
          ) : activities.map((activity: any) => (
            <div key={activity.event_id} className="pw-surface-base rounded-xl p-3">
              <p className="font-medium">{activity.event_type}</p>
              <p className="text-xs text-muted-foreground">{activity.timestamp || "-"}</p>
              <p className="text-sm text-muted-foreground">{activity.summary || "No summary"}</p>
            </div>
          ))}
        </CardContent>
      </Card>
    </motion.div>
  );
}
