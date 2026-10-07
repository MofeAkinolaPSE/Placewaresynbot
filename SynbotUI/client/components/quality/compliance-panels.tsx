/**
 * Compliance & QMS: audits and equipment maintenance as schedulable work, not just records.
 * Scheduling goes through /quality (so it lands on the Logistics Calendar); starting / completing
 * uses the existing compliance endpoints, which generate the audit report / maintenance certificate
 * PDFs, and a completed recurring audit books its next occurrence automatically.
 * "Overdue" is computed from the dates - the stored 'overdue' statuses were never set by anything.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CalendarPlus, Download, Loader2, Plus, Wrench } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { ReportButton } from "@/components/reports/ReportButton";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { Facts } from "@/components/books/lineage";
import { api } from "@/lib/api-client";
import { Dict, fmtDate } from "@/lib/books-api";
import { useIsQa, useQualityActions, useQualityRefresh } from "./actions";
import { Tone } from "./panels";

const todayStr = () => new Date().toISOString().slice(0, 10);
const daysUntil = (d?: string | null) => (d ? Math.round((new Date(d).getTime() - new Date(todayStr()).getTime()) / 86400000) : null);
const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

function Spinner() {
  return <div className="flex justify-center py-10"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>;
}

function Due({ date, done }: { date?: string | null; done?: boolean }) {
  const n = daysUntil(date);
  if (!date) return <span className="text-muted-foreground">—</span>;
  return (
    <div className="whitespace-nowrap text-xs">{fmtDate(date)}
      {!done && n !== null && <div className={`text-[11px] ${n < 0 ? "text-red-600" : n <= 14 ? "text-amber-700 dark:text-amber-300" : "text-muted-foreground"}`}>
        {n < 0 ? `${-n} days overdue` : n === 0 ? "today" : `in ${n} days`}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Audits
// ---------------------------------------------------------------------------

const FREQ: Record<string, string> = { ad_hoc: "Once", monthly: "Monthly", quarterly: "Quarterly", biannual: "6-monthly", annual: "Yearly" };

export function AuditsPanel() {
  const qa = useQualityActions();
  const isQa = useIsQa();
  const refresh = useQualityRefresh();
  const { data, isLoading, refetch } = useQuery({ queryKey: ["quality", "audits"], queryFn: () => api.compliance.audits() });
  const [picked, setPicked] = useState<Dict | null>(null);
  const [filter, setFilter] = useState("open");
  const audits: Dict[] = (data as any)?.audits ?? [];
  const withDate: Dict[] = audits.map((a) => ({ ...a, date: a.scheduled_date ?? `${a.year}-${String(a.month_due ?? 1).padStart(2, "0")}-01` }));
  const open = withDate.filter((a) => ["scheduled", "in_progress", "overdue"].includes(a.status));
  const overdue = open.filter((a) => (daysUntil(a.date) ?? 0) < 0);
  const rows = useMemo(() => (filter === "open" ? open : filter === "done" ? withDate.filter((a) => a.status === "completed") : withDate)
    .sort((a, b) => a.date.localeCompare(b.date)), [filter, audits]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-4">
      <KpiStrip items={[
        { label: "Audits planned", value: open.length, sub: `${open.filter((a) => (daysUntil(a.date) ?? 99) >= 0 && (daysUntil(a.date) ?? 99) <= 30).length} in the next 30 days` },
        { label: "Overdue", value: overdue.length, tone: overdue.length ? "danger" : "success", sub: "past their date, not completed" },
        { label: "In progress", value: open.filter((a) => a.status === "in_progress").length },
        { label: `Completed in ${new Date().getFullYear()}`, value: withDate.filter((a) => a.status === "completed").length,
          sub: `${withDate.filter((a) => a.report_url).length} with a report` },
      ]} />
      <div className="flex flex-wrap items-center gap-2">
        {[["open", "Planned"], ["done", "Completed"], ["all", "All"]].map(([k, l]) => (
          <Button key={k} size="sm" className="h-8" variant={filter === k ? "default" : "outline"} onClick={() => setFilter(k)}>{l}</Button>))}
        <Button size="sm" className="ml-auto" onClick={() => qa.open("audit")}><CalendarPlus className="mr-1.5 h-4 w-4" />Schedule audit</Button>
      </div>
      <Card>
        <CardContent className="p-0">
          {isLoading ? <Spinner /> : rows.length === 0 ? <p className="p-6 text-center text-sm text-muted-foreground">No audits here. Schedule one: it appears on the calendar on its date.</p> : (
            <Table>
              <TableHeader><TableRow><TableHead>Audit</TableHead><TableHead>Date</TableHead><TableHead>Repeats</TableHead><TableHead>Auditor</TableHead><TableHead>Status</TableHead><TableHead /></TableRow></TableHeader>
              <TableBody>{rows.map((a) => (
                <TableRow key={a.id} className="cursor-pointer" onClick={() => setPicked(a)}>
                  <TableCell><div className="font-medium">{a.audit_type}</div><div className="text-[11px] text-muted-foreground">{a.department} · {a.risk_level} risk</div></TableCell>
                  <TableCell><Due date={a.date} done={a.status === "completed"} /></TableCell>
                  <TableCell className="text-xs">{FREQ[a.frequency] ?? a.frequency}</TableCell>
                  <TableCell className="text-xs">{a.assigned_to ?? "—"}</TableCell>
                  <TableCell><Tone tone={a.status === "completed" ? "green" : a.status === "in_progress" ? "sky" : (daysUntil(a.date) ?? 0) < 0 ? "red" : "slate"}>
                    {a.status === "completed" ? "Completed" : a.status === "in_progress" ? "In progress" : (daysUntil(a.date) ?? 0) < 0 ? "Overdue" : "Scheduled"}</Tone></TableCell>
                  <TableCell className="text-right">{a.report_url && <a href={a.report_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}
                    className="inline-flex items-center text-xs text-primary hover:underline"><Download className="mr-1 h-3 w-3" />Report</a>}</TableCell>
                </TableRow>))}</TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <AuditSheet audit={picked} canAct={isQa} onClose={() => setPicked(null)} onDone={() => { refresh(); refetch(); setPicked(null); }} />
    </div>
  );
}

function AuditSheet({ audit, canAct, onClose, onDone }: { audit: Dict | null; canAct: boolean; onClose: () => void; onDone: () => void }) {
  const qa = useQualityActions();
  const [f, setF] = useState({ auditor_name: "", summary: "", findings: "", recommendations: "" });
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<any>, ok: (r: any) => string) => {
    setBusy(true);
    try { const r = await fn(); toast.success(ok(r)); onDone(); } catch (e: any) { toast.error(e?.message ?? "Failed"); } finally { setBusy(false); }
  };
  const a = audit;
  return (
    <DetailSheet open={!!a} onOpenChange={(o) => !o && onClose()} title={a ? a.audit_type : ""} description={a ? `${a.department} · ${FREQ[a.frequency] ?? a.frequency}` : undefined}>
      {a && (
        <div className="space-y-4 text-sm">
          <div className="flex justify-end"><ReportButton type="audit" kind="audit" id={a.id} label="Write audit report" /></div>
          <Facts items={[["Date", fmtDate(a.date)], ["Status", a.status.replace("_", " ")], ["Risk", a.risk_level], ["Auditor", a.assigned_to ?? "—"],
            ["Completed", a.completed_at ? fmtDate(a.completed_at) : "—"], ["Notes", a.notes ?? "—"]]} />
          {a.report_url && <a href={a.report_url} target="_blank" rel="noreferrer" className="inline-flex items-center text-primary hover:underline"><Download className="mr-1 h-4 w-4" />Audit report (PDF)</a>}
          {canAct && a.status === "scheduled" && (
            <Button disabled={busy} onClick={() => run(() => api.compliance.startAudit(a.id), () => "Audit started")}>Start audit</Button>
          )}
          {canAct && ["scheduled", "in_progress"].includes(a.status) && (
            <div className="space-y-2 rounded-md border p-3">
              <div className="text-xs font-semibold uppercase text-muted-foreground">Complete audit</div>
              <Input placeholder="Auditor" value={f.auditor_name} onChange={(e) => setF({ ...f, auditor_name: e.target.value })} />
              <Textarea rows={2} placeholder="Summary" value={f.summary} onChange={(e) => setF({ ...f, summary: e.target.value })} />
              <Textarea rows={3} placeholder="Findings (one per line)" value={f.findings} onChange={(e) => setF({ ...f, findings: e.target.value })} />
              <Textarea rows={2} placeholder="Recommendations (one per line)" value={f.recommendations} onChange={(e) => setF({ ...f, recommendations: e.target.value })} />
              <Button className="w-full" disabled={busy} onClick={() => run(() => api.compliance.completeAudit(a.id, {
                auditor_name: f.auditor_name || undefined, summary: f.summary || undefined, findings: lines(f.findings), recommendations: lines(f.recommendations) } as any),
                (r) => `Audit completed · report being generated${r?.next_audit_id ? " · next one scheduled" : ""}`)}>
                {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Complete and generate report</Button>
              {lines(f.findings).length > 0 && <Button variant="outline" className="w-full" onClick={() => qa.open("deviation", {
                trigger_type: "audit_failure", trigger_ref: a.id, department: a.department, observation: `Audit finding (${a.audit_type}): ${lines(f.findings)[0]}` })}>
                Raise a deviation from a finding</Button>}
            </div>
          )}
        </div>
      )}
    </DetailSheet>
  );
}

// ---------------------------------------------------------------------------
// Equipment maintenance
// ---------------------------------------------------------------------------

export function MaintenancePanel() {
  const qa = useQualityActions();
  const isQa = useIsQa();
  const refresh = useQualityRefresh();
  const { data, isLoading, refetch } = useQuery({ queryKey: ["quality", "maintenance"], queryFn: () => api.compliance.maintenance() });
  const { data: eq, refetch: refetchEq } = useQuery({ queryKey: ["quality", "equipment"], queryFn: () => api.compliance.equipment() });
  const jobs: Dict[] = ((data as any)?.maintenance ?? []).filter((m: Dict) => m.status !== "cancelled");
  const equipment: Dict[] = (eq as any)?.equipment ?? (eq as any)?.data ?? [];
  const [picked, setPicked] = useState<Dict | null>(null);
  const [adding, setAdding] = useState(false);
  const overdue = jobs.filter((m) => (daysUntil(m.next_maintenance_date) ?? 0) < 0);
  const soon = jobs.filter((m) => { const n = daysUntil(m.next_maintenance_date); return n !== null && n >= 0 && n <= 30; });
  const covered = new Set(jobs.map((m) => m.equipment_id));

  return (
    <div className="space-y-4">
      <KpiStrip items={[
        { label: "Equipment", value: equipment.length, sub: `${equipment.filter((e) => !covered.has(e.id)).length} without a maintenance schedule` },
        { label: "Overdue", value: overdue.length, tone: overdue.length ? "danger" : "success", sub: "past the next service date" },
        { label: "Due in 30 days", value: soon.length, tone: soon.length ? "warning" : "default" },
        { label: "Serviced this year", value: jobs.filter((m) => m.last_maintenance_date?.startsWith(String(new Date().getFullYear()))).length },
      ]} />
      <div className="flex flex-wrap justify-end gap-2">
        {isQa && <Button size="sm" variant="outline" onClick={() => setAdding(true)}><Plus className="mr-1.5 h-4 w-4" />Register equipment</Button>}
        <Button size="sm" onClick={() => qa.open("maintenance")}><CalendarPlus className="mr-1.5 h-4 w-4" />Schedule maintenance</Button>
      </div>
      <Card>
        <CardContent className="p-0">
          {isLoading ? <Spinner /> : jobs.length === 0 ? <p className="p-6 text-center text-sm text-muted-foreground">No maintenance scheduled.</p> : (
            <Table>
              <TableHeader><TableRow><TableHead>Equipment</TableHead><TableHead>Type</TableHead><TableHead>Next due</TableHead><TableHead>Last done</TableHead><TableHead>Every</TableHead></TableRow></TableHeader>
              <TableBody>{[...jobs].sort((a, b) => String(a.next_maintenance_date).localeCompare(String(b.next_maintenance_date))).map((m) => (
                <TableRow key={m.id} className="cursor-pointer" onClick={() => setPicked(m)}>
                  <TableCell><div className="font-medium">{m.equipment_registry?.equipment_name ?? "Equipment"}</div><div className="text-[11px] text-muted-foreground">{m.equipment_registry?.location}</div></TableCell>
                  <TableCell className="text-xs capitalize">{m.maintenance_type}</TableCell>
                  <TableCell><Due date={m.next_maintenance_date} /></TableCell>
                  <TableCell className="text-xs">{m.last_maintenance_date ? `${fmtDate(m.last_maintenance_date)}${m.performed_by ? ` · ${m.performed_by}` : ""}` : "—"}</TableCell>
                  <TableCell className="text-xs">{m.interval_days} days</TableCell>
                </TableRow>))}</TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <MaintenanceSheet job={picked} canAct={isQa} onClose={() => setPicked(null)} onDone={() => { refresh(); refetch(); setPicked(null); }} />
      <EquipmentSheet open={adding} onClose={() => setAdding(false)} onDone={() => { refetchEq(); setAdding(false); }} />
    </div>
  );
}

function MaintenanceSheet({ job, canAct, onClose, onDone }: { job: Dict | null; canAct: boolean; onClose: () => void; onDone: () => void }) {
  const qa = useQualityActions();
  const [f, setF] = useState({ performed_by: "", completion_notes: "", next_maintenance_date: "" });
  const [busy, setBusy] = useState(false);
  const m = job;
  return (
    <DetailSheet open={!!m} onOpenChange={(o) => !o && onClose()} title={m ? m.equipment_registry?.equipment_name ?? "Maintenance" : ""} icon={Wrench}
                 description={m ? `${m.maintenance_type} · every ${m.interval_days} days · ${m.equipment_registry?.location ?? ""}` : undefined}>
      {m && (
        <div className="space-y-4 text-sm">
          <div className="flex justify-end"><ReportButton type="maintenance" kind="maintenance" id={m.id} label="Write maintenance report" /></div>
          <Facts items={[["Next due", fmtDate(m.next_maintenance_date)], ["Last done", m.last_maintenance_date ? fmtDate(m.last_maintenance_date) : "—"],
            ["By", m.performed_by ?? "—"], ["Serial", m.equipment_registry?.serial_number ?? "—"], ["Model", m.equipment_registry?.model ?? "—"],
            ["Notes", m.completion_notes ?? "—"]]} />
          {canAct && (
            <div className="space-y-2 rounded-md border p-3">
              <div className="text-xs font-semibold uppercase text-muted-foreground">Record the service</div>
              <Input placeholder="Performed by" value={f.performed_by} onChange={(e) => setF({ ...f, performed_by: e.target.value })} />
              <Textarea rows={2} placeholder="What was done" value={f.completion_notes} onChange={(e) => setF({ ...f, completion_notes: e.target.value })} />
              <div className="space-y-1"><Label className="text-xs">Next due (blank = in {m.interval_days} days)</Label>
                <Input type="date" value={f.next_maintenance_date} onChange={(e) => setF({ ...f, next_maintenance_date: e.target.value })} /></div>
              <Button className="w-full" disabled={busy || !f.performed_by.trim()} onClick={async () => {
                setBusy(true);
                try {
                  await api.compliance.completeMaintenance(m.id, { performed_by: f.performed_by, completion_notes: f.completion_notes || undefined,
                                                                  next_maintenance_date: f.next_maintenance_date || undefined });
                  toast.success("Service recorded · certificate filed in Documents · next date on the calendar");
                  onDone();
                } catch (e: any) { toast.error(e?.message ?? "Failed"); } finally { setBusy(false); }
              }}>{busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Record service</Button>
            </div>
          )}
          <Button variant="outline" className="w-full" onClick={() => qa.open("deviation", {
            trigger_type: "missed_maintenance", trigger_ref: m.id, department: "Operations",
            observation: `${m.equipment_registry?.equipment_name ?? "Equipment"} ${m.maintenance_type} due ${fmtDate(m.next_maintenance_date)} was missed or failed`,
          })}>Raise a deviation (and reschedule)</Button>
        </div>
      )}
    </DetailSheet>
  );
}

function EquipmentSheet({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState({ equipment_name: "", equipment_type: "refrigerator", location: "", serial_number: "", model: "", maintenance_interval_days: "90" });
  const [busy, setBusy] = useState(false);
  return (
    <DetailSheet open={open} onOpenChange={(o) => !o && onClose()} title="Register equipment" description="Then schedule its maintenance; each service shows on the calendar."
                 footer={<Button className="w-full" disabled={busy || !f.equipment_name.trim() || !f.location.trim()} onClick={async () => {
                   setBusy(true);
                   try { await api.compliance.registerEquipment({ ...f, maintenance_interval_days: Number(f.maintenance_interval_days) || 90 }); toast.success("Equipment registered"); onDone(); }
                   catch (e: any) { toast.error(e?.message ?? "Failed"); } finally { setBusy(false); }
                 }}>Register</Button>}>
      {([["equipment_name", "Name"], ["equipment_type", "Type (refrigerator, cold_room, generator…)"], ["location", "Location"], ["serial_number", "Serial number"],
         ["model", "Model"], ["maintenance_interval_days", "Service every (days)"]] as [keyof typeof f, string][]).map(([k, l]) => (
        <div key={k} className="space-y-1"><Label className="text-xs">{l}</Label><Input value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></div>
      ))}
    </DetailSheet>
  );
}
