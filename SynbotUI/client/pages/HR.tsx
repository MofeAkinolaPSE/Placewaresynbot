/**
 * Human Resources, on live data: who is online and on the clock, hours this week per person
 * (saved timesheets + clocks still running, summed for the headline), the directory built from
 * User Access, and timesheet review. The hours come from each person's work clock in their
 * workspace - nothing here is typed in twice.
 */
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { UserPlus, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/workspace/PageHeader";
import { useAuth } from "@/components/AuthProvider";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { AddPersonSheet, DirectoryPanel, OverviewPanel, PersonSheet, TimesheetsPanel } from "@/components/hr/hr-panels";

const TABS: [string, string][] = [["overview", "Overview"], ["directory", "Staff directory"], ["timesheets", "Timesheets"]];

const HR = () => {
  const qc = useQueryClient();
  const { roles } = useAuth();
  const canEdit = roles.some((r) => r === "admin" || r === "hr");
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "overview";
  const [person, setPerson] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: ["hr"] });
  useRealtimeChannel("staff_updates", refresh);
  useRealtimeChannel("workspace_updates", (m: any) => { if (m?.event === "clock") refresh(); });
  const go = (t: string, view?: string) => {
    params.set("tab", t);
    if (view) params.set("view", view); else params.delete("view");
    setParams(params, { replace: true });
  };

  return (
    <div className="flex flex-col gap-5">
      <PageHeader icon={Users} title="Human Resources" subtitle="Live attendance, hours and the team - from what people actually record in their workspace."
        actions={canEdit ? <Button size="sm" variant="outline" onClick={() => setAdding(true)}><UserPlus className="mr-2 h-4 w-4" />Add staff record</Button> : undefined} />
      <div className="flex gap-1 border-b">
        {TABS.map(([k, l]) => (
          <button key={k} onClick={() => go(k)} className={`border-b-2 px-3 py-2 text-sm ${tab === k ? "border-primary font-medium text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}>{l}</button>
        ))}
      </div>
      {tab === "overview" && <OverviewPanel onPerson={setPerson} gotoTimesheets={(view) => go("timesheets", view)} />}
      {tab === "directory" && <DirectoryPanel onPerson={setPerson} />}
      {tab === "timesheets" && <TimesheetsPanel canEdit={canEdit} onPerson={setPerson} pending={params.get("view") === "pending"} onPendingChange={(p) => go("timesheets", p ? "pending" : undefined)} />}
      <PersonSheet personKey={person} onClose={() => setPerson(null)} canEdit={canEdit} />
      <AddPersonSheet open={adding} onOpenChange={(v) => { setAdding(v); if (!v) refresh(); }} />
    </div>
  );
};

export default HR;
