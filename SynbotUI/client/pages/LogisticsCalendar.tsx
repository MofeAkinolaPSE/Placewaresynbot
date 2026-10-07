/**
 * Logistics Calendar: one calendar over the real records, not a separate diary.
 *   stock deliveries (stock orders placed with suppliers) · incoming batches for QC · recall returns ·
 *   audits · maintenance · deviation close dates and CAPA actions · lots expiring · other events
 * Items come from /quality/calendar (services/quality_hub.calendar_feed). Moving an item (drag it to
 * another day, or pick a date in its panel) moves the record itself; "Schedule" creates the record
 * (recall, audit, maintenance, batch...), which then appears here and on its own page.
 */
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, CalendarDays, ChevronLeft, ChevronRight, Loader2, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { PageHeader } from "@/components/workspace/PageHeader";
import { DrillProvider } from "@/components/books/lineage";
import { api } from "@/lib/api-client";
import { Dict, fmtDate } from "@/lib/books-api";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { ACTION_LABELS, QualityAction, QualityActionsProvider, useIsQa, useQualityActions, useQualityRefresh } from "@/components/quality/actions";
import { Tone } from "@/components/quality/panels";
import { KIND_TONE } from "./QualityHub";

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const PILL: Record<string, string> = {
  red: "bg-red-500 text-white", amber: "bg-amber-500 text-white", sky: "bg-sky-600 text-white", green: "bg-emerald-600 text-white",
  slate: "bg-slate-500 text-white", violet: "bg-violet-600 text-white",
};

export default function LogisticsCalendar() {
  return (
    <DrillProvider>
      <QualityActionsProvider>
        <CalendarPage />
      </QualityActionsProvider>
    </DrillProvider>
  );
}

function CalendarPage() {
  const qa = useQualityActions();
  const isQa = useIsQa();
  const refresh = useQualityRefresh();
  const [month, setMonth] = useState(() => { const n = new Date(); return new Date(n.getFullYear(), n.getMonth(), 1); });
  const [hidden, setHidden] = useState<Record<string, boolean>>({ expiry: false });
  const [picked, setPicked] = useState<Dict | null>(null);
  const [dayMenu, setDayMenu] = useState<string | null>(null);
  const [dragging, setDragging] = useState<Dict | null>(null);
  const todayStr = iso(new Date());

  const grid = useMemo(() => {
    const start = new Date(month); start.setDate(1 - month.getDay());
    const last = new Date(month.getFullYear(), month.getMonth() + 1, 0);
    const end = new Date(last); end.setDate(last.getDate() + (6 - last.getDay()));
    const days: Date[] = [];
    for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) days.push(new Date(d));
    return { from: iso(start), to: iso(end), days };
  }, [month]);

  const { data, isLoading } = useQuery({ queryKey: ["quality-calendar", grid.from, grid.to], queryFn: () => api.quality.calendar(grid.from, grid.to) });
  useRealtimeChannel("calendar_tasks", () => refresh());
  const items: Dict[] = (data?.items ?? []).filter((i: Dict) => !hidden[i.kind]);
  const byDay = useMemo(() => {
    const m: Record<string, Dict[]> = {};
    items.forEach((i) => { (m[i.display_date] ??= []).push(i); });
    return m;
  }, [items]);

  const move = async (item: Dict, date: string) => {
    if (!item.movable || date === item.date) return;
    try {
      await api.quality.move(item.kind, item.id, date);
      toast.success(`${KIND_TONE[item.kind]?.[1] ?? "Item"} moved to ${fmtDate(date)} - updated on its own record too`);
      refresh();
      setPicked(null);
    } catch (e: any) { toast.error(e?.message ?? "Could not move it"); }
  };

  const actions: QualityAction[] = ["delivery", "batch", "audit", "maintenance", "deviation", ...(isQa ? ["recall" as QualityAction] : []), "event"];

  return (
    <div className="space-y-4">
      <PageHeader icon={CalendarDays} title="Logistics Calendar" subtitle="Deliveries, incoming batches, recalls, audits, maintenance, CAPA and expiry - straight from their records"
        actions={<Button size="sm" onClick={() => setDayMenu(todayStr)}><Plus className="mr-1.5 h-4 w-4" />Schedule</Button>} />

      <div className="flex flex-wrap items-center gap-2">
        <Button size="icon" variant="outline" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}><ChevronLeft className="h-4 w-4" /></Button>
        <div className="w-40 text-center font-semibold">{month.toLocaleDateString("en-GB", { month: "long", year: "numeric" })}</div>
        <Button size="icon" variant="outline" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}><ChevronRight className="h-4 w-4" /></Button>
        <Button size="sm" variant="ghost" onClick={() => { const n = new Date(); setMonth(new Date(n.getFullYear(), n.getMonth(), 1)); }}>Today</Button>
        {data?.overdue > 0 && <Tone tone="red">{data.overdue} overdue (shown on today)</Tone>}
        <div className="ml-auto flex flex-wrap gap-1.5">
          {Object.entries(KIND_TONE).map(([k, [tone, label]]) => (
            <button key={k} onClick={() => setHidden({ ...hidden, [k]: !hidden[k] })}
                    className={`rounded-md px-2 py-0.5 text-[11px] font-medium ${hidden[k] ? "bg-muted text-muted-foreground line-through" : PILL[tone]}`}>
              {label} {data?.counts?.[k] ? `(${data.counts[k]})` : ""}
            </button>
          ))}
        </div>
      </div>

      <Card>
        <CardContent className="p-2">
          {isLoading ? <div className="flex justify-center py-20"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div> : (
            <div className="grid grid-cols-7 gap-px overflow-hidden rounded-md bg-border">
              {DAYS.map((d) => <div key={d} className="bg-muted/60 px-2 py-1 text-center text-xs font-semibold text-muted-foreground">{d}</div>)}
              {grid.days.map((d) => {
                const key = iso(d);
                const dayItems = byDay[key] ?? [];
                const inMonth = d.getMonth() === month.getMonth();
                return (
                  <div key={key} onClick={() => setDayMenu(key)}
                       onDragOver={(e) => { if (dragging?.movable) e.preventDefault(); }}
                       onDrop={(e) => { e.preventDefault(); if (dragging) move(dragging, key); setDragging(null); }}
                       className={`min-h-[108px] cursor-pointer bg-background p-1 hover:bg-muted/30 ${inMonth ? "" : "opacity-50"} ${key === todayStr ? "ring-2 ring-inset ring-primary" : ""}`}>
                    <div className={`mb-1 text-right text-xs ${key === todayStr ? "font-bold text-primary" : "text-muted-foreground"}`}>{d.getDate()}</div>
                    {dayItems.slice(0, 4).map((i) => (
                      <button key={`${i.kind}-${i.id}`} draggable={i.movable} onDragStart={() => setDragging(i)} onDragEnd={() => setDragging(null)}
                              onClick={(e) => { e.stopPropagation(); setPicked(i); }}
                              title={`${i.title} - ${i.subtitle}`}
                              className={`mb-0.5 block w-full truncate rounded px-1.5 py-0.5 text-left text-[11px] font-medium ${PILL[i.overdue ? "red" : KIND_TONE[i.kind]?.[0] ?? "slate"]} ${i.overdue ? "ring-1 ring-red-300" : ""}`}>
                        {i.overdue ? "⚠ " : ""}{i.title}
                      </button>
                    ))}
                    {dayItems.length > 4 && <div className="px-1 text-[11px] text-muted-foreground">+{dayItems.length - 4} more</div>}
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
      <p className="text-xs text-muted-foreground">Drag an item to another day to reschedule it. Expiry dates and past events cannot be moved.</p>

      <DetailSheet open={!!dayMenu} onOpenChange={(o) => !o && setDayMenu(null)} title={dayMenu ? `Schedule on ${fmtDate(dayMenu)}` : ""}
                   description="Each option creates the real record; it then shows here and on its own page.">
        {dayMenu && (
          <div className="space-y-3">
            {(byDay[dayMenu] ?? []).length > 0 && (
              <div className="space-y-1">
                <div className="text-xs font-semibold uppercase text-muted-foreground">On this day</div>
                {(byDay[dayMenu] ?? []).map((i) => (
                  <button key={`${i.kind}-${i.id}`} className="flex w-full items-center gap-2 rounded border p-2 text-left text-sm hover:bg-muted/40" onClick={() => { setDayMenu(null); setPicked(i); }}>
                    <Tone tone={KIND_TONE[i.kind]?.[0] ?? "slate"}>{KIND_TONE[i.kind]?.[1] ?? i.kind}</Tone><span className="truncate">{i.title}</span>
                  </button>))}
              </div>
            )}
            <div className="grid gap-2">
              {actions.map((a) => (
                <Button key={a} variant="outline" className="justify-start" onClick={() => { const d = dayMenu; setDayMenu(null); qa.open(a, { date: d }); }}>
                  <Plus className="mr-2 h-4 w-4" />{ACTION_LABELS[a]}</Button>))}
            </div>
          </div>
        )}
      </DetailSheet>

      <ItemSheet item={picked} onClose={() => setPicked(null)} onMove={move} onDeleted={() => { refresh(); setPicked(null); }} />
    </div>
  );
}

function ItemSheet({ item, onClose, onMove, onDeleted }: { item: Dict | null; onClose: () => void; onMove: (i: Dict, d: string) => void; onDeleted: () => void }) {
  const navigate = useNavigate();
  const [date, setDate] = useState("");
  const i = item;
  return (
    <DetailSheet open={!!i} onOpenChange={(o) => { if (!o) { setDate(""); onClose(); } }} title={i?.title ?? ""} description={i ? `${KIND_TONE[i.kind]?.[1] ?? i.kind} · ${fmtDate(i.date)}${i.overdue ? " · overdue" : ""}` : undefined}>
      {i && (
        <div className="space-y-4 text-sm">
          <p className="text-muted-foreground">{i.subtitle || "—"}</p>
          {i.status && <div><Tone tone={i.overdue ? "red" : KIND_TONE[i.kind]?.[0] ?? "slate"}>{i.status}</Tone></div>}
          {i.meta?.value ? <p>Value at cost: ₦{Number(i.meta.value).toLocaleString()}</p> : null}
          {i.movable && (
            <div className="flex items-end gap-2 rounded-md border p-3">
              <div className="flex-1 space-y-1"><Label className="text-xs">Move to</Label><Input type="date" value={date || i.date} onChange={(e) => setDate(e.target.value)} /></div>
              <Button disabled={!date || date === i.date} onClick={() => { onMove(i, date); setDate(""); }}>Move</Button>
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            {i.link && i.link !== "/calendar" && <Button variant="outline" onClick={() => navigate(i.link)}>Open record <ArrowUpRight className="ml-1 h-4 w-4" /></Button>}
            {i.kind === "event" && (
              <Button variant="ghost" className="text-red-600" onClick={async () => {
                try { await api.calendar.delete(i.id); toast.success("Removed from the calendar"); onDeleted(); } catch (e: any) { toast.error(e?.message ?? "Failed"); }
              }}><Trash2 className="mr-1.5 h-4 w-4" />Remove event</Button>
            )}
          </div>
        </div>
      )}
    </DetailSheet>
  );
}
