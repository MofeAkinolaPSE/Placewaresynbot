/**
 * Data backups (Settings › Data Backup, administrators only).
 *
 * The server prepares a full backup on the schedule chosen here (daily / weekly / monthly) and
 * keeps the last few. An administrator downloads each one to this computer - in Chrome / Edge
 * they can pick the folder, e.g. an external drive - and is reminded until someone does.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { DatabaseBackup, Download, HardDriveDownload, Loader2, Play, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api-client";
import { useAuth } from "@/components/AuthProvider";

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const size = (b?: number | null) => (b == null ? "" : b > 1 << 30 ? `${(b / (1 << 30)).toFixed(2)} GB` : `${(b / (1 << 20)).toFixed(1)} MB`);
const when = (v?: string | null) => (v ? new Date(v).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : "");

function useBackups(enabled = true) {
  return useQuery({ queryKey: ["admin-backups"], queryFn: () => api.adminBackup.schedule(), enabled, refetchInterval: 60_000, retry: false });
}

/** Save a backup: a folder picker where the browser has one (choose the external drive), else Downloads. */
export async function saveBackup(id: string) {
  const { blob, filename, sha256 } = await api.adminBackup.downloadFile(id);
  const picker = (window as any).showSaveFilePicker;
  if (typeof picker === "function") {
    try {
      const handle = await picker({ suggestedName: filename, types: [{ description: "Placeware backup", accept: { "application/octet-stream": [filename.endsWith(".zip") ? ".zip" : ".gz"] } }] });
      const w = await handle.createWritable();
      await w.write(blob);
      await w.close();
      toast.success("Backup saved", { description: `${filename}${sha256 ? ` · checksum ${sha256.slice(0, 12)}…` : ""}` });
      return;
    } catch (e: any) {
      if (e?.name === "AbortError") return;  // the user closed the picker
    }
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
  toast.success("Backup downloaded to your Downloads folder", { description: `${filename} - copy it to the external drive.` });
}

export function BackupPanel() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useBackups();
  const [form, setForm] = useState<any>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const s = form ?? data?.settings;
  const set = (k: string, v: any) => setForm({ ...(form ?? data?.settings), [k]: v });
  const refresh = () => qc.invalidateQueries({ queryKey: ["admin-backups"] });

  const save = async () => {
    setBusy("save");
    try {
      await api.adminBackup.saveSchedule({ frequency: s.frequency, run_hour: Number(s.run_hour), weekday: Number(s.weekday),
                                           month_day: Number(s.month_day), keep_last: Number(s.keep_last) });
      setForm(null); refresh();
      toast.success("Backup schedule saved");
    } catch (e: any) { toast.error("Could not save the schedule", { description: e?.message }); }
    setBusy(null);
  };
  const runNow = async () => {
    setBusy("run");
    try {
      const b = await api.adminBackup.runNow();
      refresh();
      if (b?.status === "READY") toast.success("Backup prepared - download it below"); else toast.error("Backup failed", { description: b?.error });
    } catch (e: any) { toast.error("Backup failed", { description: e?.status === 409 ? "A backup is already being prepared." : e?.message }); }
    setBusy(null);
  };
  const download = async (id: string) => {
    setBusy(id);
    try { await saveBackup(id); refresh(); } catch (e: any) { toast.error("Download failed", { description: e?.message }); }
    setBusy(null);
  };

  if (isLoading) return <p className="text-sm text-muted-foreground">Checking…</p>;
  if (error) return <p className="text-sm text-muted-foreground">{(error as any)?.status === 403 ? "Only administrators can manage backups." : "Backups are unavailable right now."}</p>;
  if (!data || !s) return null;
  const items: any[] = data.items ?? [];
  return (
    <div className="space-y-4">
      <div className="pw-surface-base space-y-3 rounded-xl p-4">
        <div className="flex items-center gap-2 font-medium text-foreground"><DatabaseBackup className="h-4 w-4" />Schedule</div>
        <div className="grid gap-3 sm:grid-cols-4">
          <div className="space-y-1"><Label className="text-xs">How often</Label>
            <select className="h-9 w-full rounded-md border bg-background px-2 text-sm" value={s.frequency} onChange={(e) => set("frequency", e.target.value)}>
              <option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option><option value="off">Off (only when I ask)</option>
            </select></div>
          {s.frequency === "weekly" && <div className="space-y-1"><Label className="text-xs">On</Label>
            <select className="h-9 w-full rounded-md border bg-background px-2 text-sm" value={s.weekday} onChange={(e) => set("weekday", e.target.value)}>
              {WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}</select></div>}
          {s.frequency === "monthly" && <div className="space-y-1"><Label className="text-xs">Day of the month</Label>
            <select className="h-9 w-full rounded-md border bg-background px-2 text-sm" value={s.month_day} onChange={(e) => set("month_day", e.target.value)}>
              {Array.from({ length: 28 }, (_, i) => <option key={i} value={i + 1}>{i + 1}</option>)}</select></div>}
          {s.frequency !== "off" && <div className="space-y-1"><Label className="text-xs">At</Label>
            <select className="h-9 w-full rounded-md border bg-background px-2 text-sm" value={s.run_hour} onChange={(e) => set("run_hour", e.target.value)}>
              {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}</select></div>}
          <div className="space-y-1"><Label className="text-xs">Keep on the server</Label>
            <select className="h-9 w-full rounded-md border bg-background px-2 text-sm" value={s.keep_last} onChange={(e) => set("keep_last", e.target.value)}>
              {[2, 4, 8, 12, 30].map((n) => <option key={n} value={n}>last {n}</option>)}</select></div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>{data.next_due && s.frequency !== "off" ? `Next backup ${when(data.next_due)} (${data.timezone}).` : "No scheduled backups."}
            {" "}{data.restorable ? "Full restorable database dump." : "Data-only export (CSV) - restorable dumps need the updated server image."}</span>
          <div className="flex gap-2">
            {form && <Button size="sm" onClick={save} disabled={busy === "save"}>{busy === "save" ? "Saving…" : "Save schedule"}</Button>}
            <Button size="sm" variant="outline" onClick={runNow} disabled={!!busy}>
              {busy === "run" ? <><Loader2 className="mr-1 h-4 w-4 animate-spin" />Preparing…</> : <><Play className="mr-1 h-4 w-4" />Back up now</>}</Button>
          </div>
        </div>
      </div>

      <div className="pw-surface-base rounded-xl p-4">
        <div className="mb-2 font-medium text-foreground">Backups on the server</div>
        {items.length === 0 ? <p className="text-sm text-muted-foreground">None yet.</p> : (
          <ul className="divide-y text-sm">
            {items.map((b) => (
              <li key={b.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <div className="min-w-0">
                  <div className="truncate font-mono text-xs">{b.file_name ?? "preparing…"}</div>
                  <div className="text-xs text-muted-foreground">
                    {when(b.started_at)} · {b.kind === "SCHEDULED" ? "scheduled" : `by ${b.requested_by ?? "admin"}`} · {size(b.size_bytes)}
                    {b.status === "FAILED" && <span className="text-red-600"> · failed: {b.error}</span>}
                    {b.status === "RUNNING" && <span> · preparing…</span>}
                    {b.status === "READY" && (b.download_count ? <span> · downloaded {b.download_count}× (last {when(b.last_downloaded_at)} by {b.last_downloaded_by})</span>
                                                               : <span className="font-medium text-amber-600"> · not downloaded yet</span>)}
                  </div>
                </div>
                {b.status === "READY" && (
                  <Button size="sm" variant={b.download_count ? "outline" : "default"} onClick={() => download(b.id)} disabled={busy === b.id} className="gap-1">
                    {busy === b.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <HardDriveDownload className="h-4 w-4" />}Save to this computer</Button>
                )}
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-xs text-muted-foreground">
          Chrome and Edge ask where to save - pick the external drive. Other browsers save to Downloads; copy the file across.
          The file holds every client and financial record: keep the drive safe. To restore: <span className="font-mono">gunzip -c FILE | psql</span> on a fresh database.
        </p>
      </div>
    </div>
  );
}

/** Top-of-page reminder for administrators while a prepared backup has not been downloaded. */
export function BackupReminder() {
  const { roles } = useAuth();
  const admin = roles.includes("admin");
  const { data } = useBackups(admin);
  const [hidden, setHidden] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const b = data?.awaiting_download;
  if (!admin || !b || hidden === b.id) return null;
  const save = async () => {
    setBusy(true);
    try { await saveBackup(b.id); qc.invalidateQueries({ queryKey: ["admin-backups"] }); } catch (e: any) { toast.error("Download failed", { description: e?.message }); }
    setBusy(false);
  };
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-sky-300 bg-sky-50 px-3 py-2 text-xs text-sky-900 dark:bg-sky-500/10 dark:text-sky-200">
      <DatabaseBackup className="h-4 w-4 shrink-0" />
      <span className="flex-1">The {b.kind === "SCHEDULED" ? "scheduled" : "requested"} backup of {when(b.started_at)} ({size(b.size_bytes)}) is ready. Save it to the external drive.</span>
      <Button size="sm" className="h-7 gap-1" onClick={save} disabled={busy}>{busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}Save backup</Button>
      <Link to="/settings" className="underline">Schedule</Link>
      <button type="button" aria-label="Hide" onClick={() => setHidden(b.id)}><X className="h-4 w-4" /></button>
    </div>
  );
}
