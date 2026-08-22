import { useState, useMemo, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Plus,
  Bell,
  Eye,
  Snowflake,
  ShieldCheck,
  Package,
  Truck,
  ClipboardList,
  FlaskConical,
  AlertTriangle,
  CalendarDays,
  FileText,
  X,
  RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api-client";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type LogisticsEventType =
  | "inbound_inventory"
  | "regional_dispatch"
  | "warehouse_audit"
  | "qc_inspection"
  | "meeting"
  | "deadline"
  | "reminder"
  | "holiday"
  | "other";

interface EventMeta {
  batch_id?: string;
  product_name?: string;
  quantity?: number;
  is_cold_chain?: boolean;
  is_nafdac_regulated?: boolean;
  dispatch_zone?: string;
  supplier?: string;
  status?: string;
  batch_expiry?: string;
  notes?: string;
}

interface LogisticsEvent {
  id: string;
  title: string;
  description?: string;
  event_type: LogisticsEventType;
  start_time: string;
  end_time?: string;
  all_day: boolean;
  location?: string;
  metadata?: EventMeta | string;
}

interface CalendarDay {
  date: number;
  dateStr: string;
  isCurrentMonth: boolean;
  isToday: boolean;
  events: LogisticsEvent[];
  hasColdChain: boolean;
  hasNafdac: boolean;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

interface EventConfig {
  label: string;
  textColor: string;
  bgClass: string;
  icon: React.ReactNode;
}

const EVENT_CONFIG: Record<string, EventConfig> = {
  inbound_inventory: {
    label: "Inbound Inventory",
    textColor: "text-white",
    bgClass: "bg-blue-500",
    icon: <Package className="w-3 h-3" />,
  },
  regional_dispatch: {
    label: "Regional Dispatch",
    textColor: "text-white",
    bgClass: "bg-teal-500",
    icon: <Truck className="w-3 h-3" />,
  },
  warehouse_audit: {
    label: "Warehouse Audit",
    textColor: "text-white",
    bgClass: "bg-orange-500",
    icon: <ClipboardList className="w-3 h-3" />,
  },
  qc_inspection: {
    label: "QC Inspection",
    textColor: "text-white",
    bgClass: "bg-purple-500",
    icon: <FlaskConical className="w-3 h-3" />,
  },
  meeting: {
    label: "Meeting",
    textColor: "text-white",
    bgClass: "bg-cyan-500",
    icon: <CalendarDays className="w-3 h-3" />,
  },
  deadline: {
    label: "Deadline",
    textColor: "text-white",
    bgClass: "bg-red-500",
    icon: <AlertTriangle className="w-3 h-3" />,
  },
  other: {
    label: "Other",
    textColor: "text-white",
    bgClass: "bg-slate-500",
    icon: <CalendarDays className="w-3 h-3" />,
  },
};

type StatusVariant = "default" | "secondary" | "destructive" | "outline";

const STATUS_MAP: Record<string, { label: string; variant: StatusVariant }> = {
  scheduled: { label: "Scheduled", variant: "secondary" },
  in_transit: { label: "In Transit", variant: "default" },
  awaiting_qc: { label: "Awaiting QC", variant: "outline" },
  delivered: { label: "Delivered", variant: "default" },
  storage_limit_reached: { label: "Storage Limit Reached", variant: "destructive" },
};

const LOGISTICS_TYPES: LogisticsEventType[] = [
  "inbound_inventory",
  "regional_dispatch",
  "warehouse_audit",
  "qc_inspection",
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function parseMeta(raw?: EventMeta | string | null): EventMeta {
  if (!raw) return {};
  if (typeof raw === "string") {
    try {
      return JSON.parse(raw) as EventMeta;
    } catch {
      return {};
    }
  }
  return raw;
}

function toMonthKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function buildCalendarDays(
  monthDate: Date,
  events: LogisticsEvent[],
  todayStr: string,
): CalendarDay[] {
  const year = monthDate.getFullYear();
  const month = monthDate.getMonth();
  const firstDay = new Date(year, month, 1);
  const lastDay = new Date(year, month + 1, 0);

  // Pad to the Sunday before the first day
  const start = new Date(firstDay);
  start.setDate(firstDay.getDate() - firstDay.getDay());

  // Pad to the Saturday after the last day
  const end = new Date(lastDay);
  end.setDate(lastDay.getDate() + (6 - lastDay.getDay()));

  const days: CalendarDay[] = [];
  const cursor = new Date(start);

  while (cursor <= end) {
    const dateStr = cursor.toISOString().slice(0, 10);
    const dayEvents = events.filter((e) => e.start_time.startsWith(dateStr));
    const hasColdChain = dayEvents.some((e) => parseMeta(e.metadata).is_cold_chain);
    const hasNafdac = dayEvents.some((e) => parseMeta(e.metadata).is_nafdac_regulated);

    days.push({
      date: cursor.getDate(),
      dateStr,
      isCurrentMonth: cursor.getMonth() === month,
      isToday: dateStr === todayStr,
      events: dayEvents,
      hasColdChain,
      hasNafdac,
    });

    cursor.setDate(cursor.getDate() + 1);
  }

  return days;
}

// ---------------------------------------------------------------------------
// Sub-component: event pill inside a calendar cell
// ---------------------------------------------------------------------------

function EventPill({
  event,
  onClick,
}: {
  event: LogisticsEvent;
  onClick: () => void;
}) {
  const cfg = EVENT_CONFIG[event.event_type] ?? EVENT_CONFIG.other;
  const meta = parseMeta(event.metadata);

  return (
    <button
      className={cn(
        "w-full text-left text-[11px] leading-tight px-1.5 py-[3px] rounded flex items-center gap-1 mb-[2px] hover:opacity-90 transition-opacity",
        cfg.bgClass,
        cfg.textColor,
      )}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
    >
      <span className="truncate flex-1 font-medium">{event.title}</span>
      {meta.is_cold_chain && (
        <Snowflake className="w-2.5 h-2.5 flex-shrink-0 opacity-90" />
      )}
      {meta.is_nafdac_regulated && (
        <ShieldCheck className="w-2.5 h-2.5 flex-shrink-0 opacity-90" />
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Default form state factory (avoids stale todayStr on reset)
// ---------------------------------------------------------------------------

function defaultForm(todayStr: string) {
  return {
    title: "",
    event_type: "inbound_inventory" as LogisticsEventType,
    start_date: todayStr,
    end_date: "",
    batch_id: "",
    product_name: "",
    quantity: "",
    dispatch_zone: "",
    supplier: "",
    status: "scheduled",
    batch_expiry: "",
    is_cold_chain: false,
    is_nafdac_regulated: false,
    notes: "",
  };
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function LogisticsCalendar() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const todayStr = new Date().toISOString().slice(0, 10);

  const [currentMonth, setCurrentMonth] = useState<Date>(() => {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), 1);
  });
  const [previewOpen, setPreviewOpen] = useState(false);
  const [selectedDay, setSelectedDay] = useState<CalendarDay | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<LogisticsEvent | null>(null);
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [alertDismissed, setAlertDismissed] = useState(false);
  const [form, setForm] = useState(() => defaultForm(todayStr));

  // -------------------------------------------------------------------------
  // Realtime subscription
  // -------------------------------------------------------------------------
  useRealtimeChannel("calendar_tasks", () => {
    queryClient.invalidateQueries({ queryKey: ["logistics-events"] });
    queryClient.invalidateQueries({ queryKey: ["logistics-alerts"] });
  });

  // -------------------------------------------------------------------------
  // Queries
  // -------------------------------------------------------------------------
  const monthKey = toMonthKey(currentMonth);

  const { data: eventsRaw, isLoading } = useQuery({
    queryKey: ["logistics-events", monthKey],
    queryFn: () => api.calendar.list(monthKey),
    staleTime: 30_000,
  });

  const { data: alertsRaw } = useQuery({
    queryKey: ["logistics-alerts"],
    queryFn: () => api.calendar.logisticsAlerts(),
    staleTime: 60_000,
    refetchInterval: 120_000,
  });

  const events: LogisticsEvent[] = (eventsRaw as any)?.events ?? [];
  const alertCount: number = (alertsRaw as any)?.total ?? 0;
  const alerts: any[] = (alertsRaw as any)?.alerts ?? [];

  // -------------------------------------------------------------------------
  // Derived data
  // -------------------------------------------------------------------------
  const calendarDays = useMemo(
    () => buildCalendarDays(currentMonth, events, todayStr),
    [currentMonth, events, todayStr],
  );

  const todayEvents = useMemo(
    () => events.filter((e) => e.start_time.startsWith(todayStr)),
    [events, todayStr],
  );

  const criticalToday = useMemo(
    () =>
      todayEvents.filter(
        (e) =>
          LOGISTICS_TYPES.includes(e.event_type) ||
          parseMeta(e.metadata).is_cold_chain,
      ),
    [todayEvents],
  );

  // -------------------------------------------------------------------------
  // Mutations
  // -------------------------------------------------------------------------
  const createMutation = useMutation({
    mutationFn: (payload: Parameters<typeof api.calendar.create>[0]) => api.calendar.create(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["logistics-events"] });
      queryClient.invalidateQueries({ queryKey: ["logistics-alerts"] });
      toast({
        title: "Event scheduled",
        description: `"${form.title}" added to the logistics calendar.`,
      });
      setShowAddDialog(false);
      setForm(defaultForm(todayStr));
    },
    onError: (e: any) => {
      toast({
        title: "Failed to schedule event",
        description: e?.message ?? "Please try again.",
        variant: "destructive",
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.calendar.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["logistics-events"] });
      setSelectedEvent(null);
      toast({ title: "Event removed from calendar" });
    },
    onError: (e: any) => {
      toast({
        title: "Delete failed",
        description: e?.message ?? "Please try again.",
        variant: "destructive",
      });
    },
  });

  // -------------------------------------------------------------------------
  // Handlers
  // -------------------------------------------------------------------------
  const handleSubmit = useCallback(() => {
    if (!form.title.trim()) {
      toast({ title: "Title is required", variant: "destructive" });
      return;
    }
    if (!form.start_date) {
      toast({ title: "Date is required", variant: "destructive" });
      return;
    }

    createMutation.mutate({
      title: form.title.trim(),
      event_type: form.event_type,
      start_time: `${form.start_date}T08:00:00`,
      end_time: form.end_date ? `${form.end_date}T17:00:00` : undefined,
      all_day: true,
      metadata: {
        batch_id: form.batch_id || undefined,
        product_name: form.product_name || undefined,
        quantity: form.quantity ? Number(form.quantity) : undefined,
        dispatch_zone: form.dispatch_zone || undefined,
        supplier: form.supplier || undefined,
        status: form.status,
        batch_expiry: form.batch_expiry || undefined,
        is_cold_chain: form.is_cold_chain,
        is_nafdac_regulated: form.is_nafdac_regulated,
        notes: form.notes || undefined,
      },
    });
  }, [form, createMutation, toast]);

  const prevMonth = () =>
    setCurrentMonth((d) => new Date(d.getFullYear(), d.getMonth() - 1, 1));
  const nextMonth = () =>
    setCurrentMonth((d) => new Date(d.getFullYear(), d.getMonth() + 1, 1));

  const handleDayClick = (day: CalendarDay) => {
    setSelectedDay(day);
    setPreviewOpen(true);
  };

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  return (
    <div className="flex flex-col h-full min-h-0 bg-background">
      {/* ------------------------------------------------------------------ */}
      {/* Expiring-batch alert banner                                         */}
      {/* ------------------------------------------------------------------ */}
      <AnimatePresence>
        {!alertDismissed && alertCount > 0 && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.18 }}
            className="flex items-center gap-3 px-5 py-2.5 bg-red-50 border-b border-red-200 dark:bg-red-950/30 dark:border-red-900/40 flex-shrink-0"
          >
            {/* Bell with badge */}
            <span className="relative flex h-7 w-7 items-center justify-center rounded-full bg-red-100 dark:bg-red-900/50 flex-shrink-0">
              <Bell className="h-4 w-4 text-red-600 dark:text-red-400" />
              <span className="absolute -top-0.5 -right-0.5 h-3.5 w-3.5 rounded-full bg-red-500 text-[9px] font-bold text-white flex items-center justify-center leading-none">
                {alertCount > 9 ? "9+" : alertCount}
              </span>
            </span>

            <div className="flex-1 min-w-0 text-sm">
              <span className="font-semibold text-red-700 dark:text-red-400">
                Expiring batch alert
              </span>
              <span className="text-red-600/80 dark:text-red-400/70 ml-2">
                {alertCount} batch{alertCount !== 1 ? "es" : ""} expiring within 30 days
              </span>
            </div>

            <div className="flex items-center gap-1.5 flex-shrink-0">
              <Button
                size="sm"
                variant="ghost"
                className="h-7 text-red-600 hover:text-red-700 hover:bg-red-100 text-xs px-2 dark:text-red-300"
                onClick={() => setPreviewOpen(true)}
              >
                View
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="h-7 w-7 p-0 text-red-400 hover:text-red-600 hover:bg-red-100"
                onClick={() => setAlertDismissed(true)}
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ------------------------------------------------------------------ */}
      {/* Page header                                                         */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 px-4 py-3 sm:px-5 sm:py-4 flex-shrink-0">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Logistics Calendar</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Pharma supply chain — inbound shipments, dispatch runs &amp; NAFDAC compliance
          </p>
        </div>

        <div className="flex items-center gap-2">
          {/* Legend (large screens only) */}
          <div className="hidden xl:flex items-center gap-1.5 mr-3 flex-wrap">
            {LOGISTICS_TYPES.map((key) => {
              const cfg = EVENT_CONFIG[key];
              return (
                <span
                  key={key}
                  className={cn(
                    "inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full font-medium",
                    cfg.bgClass,
                    cfg.textColor,
                  )}
                >
                  {cfg.icon}
                  {cfg.label}
                </span>
              );
            })}
          </div>

          <Button
            variant={previewOpen ? "default" : "outline"}
            size="sm"
            className="gap-1.5"
            onClick={() => setPreviewOpen((v) => !v)}
          >
            <Eye className="h-4 w-4" />
            Preview
          </Button>

          <Button size="sm" className="gap-1.5" onClick={() => setShowAddDialog(true)}>
            <Plus className="h-4 w-4" />
            Add Event
          </Button>
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Body: calendar grid + optional side panel                           */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex flex-1 min-h-0 flex-col overflow-hidden md:flex-row">
        {/* Calendar column */}
        <div className="flex min-h-0 flex-1 flex-col overflow-auto p-3 sm:p-4">
          {/* Month navigation */}
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <Button
              variant="outline"
              size="icon"
              className="h-8 w-8 flex-shrink-0"
              onClick={prevMonth}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>

            <h2 className="text-base font-semibold min-w-[180px] text-center">
              {MONTH_NAMES[currentMonth.getMonth()]} {currentMonth.getFullYear()}
            </h2>

            <Button
              variant="outline"
              size="icon"
              className="h-8 w-8 flex-shrink-0"
              onClick={nextMonth}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>

            {isLoading && (
              <RefreshCw className="h-4 w-4 text-muted-foreground animate-spin ml-1 flex-shrink-0" />
            )}
          </div>

          {/* Day-of-week header row */}
          <div className="grid grid-cols-7 border-b border-border/40 mb-0">
            {DAY_LABELS.map((d) => (
              <div
                key={d}
                className="truncate py-2 text-center text-[10px] font-semibold uppercase tracking-wide text-muted-foreground sm:text-xs"
              >
                {d}
              </div>
            ))}
          </div>

          {/* Calendar day cells */}
          <div className="grid grid-cols-7 flex-1 border-l border-t border-border/30 rounded-b-sm overflow-hidden">
            {calendarDays.map((day, idx) => (
              <div
                key={idx}
                className={cn(
                  "min-h-[64px] sm:min-h-[110px] border-r border-b border-border/30 p-1 sm:p-1.5 cursor-pointer transition-colors relative group",
                  !day.isCurrentMonth && "bg-muted/20",
                  day.isToday && "bg-primary/5",
                  selectedDay?.dateStr === day.dateStr &&
                    "ring-2 ring-inset ring-primary/40 bg-primary/5",
                  "hover:bg-accent/25",
                )}
                onClick={() => handleDayClick(day)}
              >
                {/* Date number */}
                <div
                  className={cn(
                    "text-[11px] sm:text-xs font-semibold w-5 h-5 sm:w-6 sm:h-6 flex items-center justify-center rounded-full mb-0.5 sm:mb-1 select-none",
                    day.isToday
                      ? "bg-primary text-primary-foreground"
                      : day.isCurrentMonth
                        ? "text-foreground"
                        : "text-muted-foreground/40",
                  )}
                >
                  {day.date}
                </div>

                {/* Event pills — max 3 visible + overflow count */}
                <div className="hidden sm:block">
                  {day.events.slice(0, 3).map((ev) => (
                    <EventPill
                      key={ev.id}
                      event={ev}
                      onClick={() => setSelectedEvent(ev)}
                    />
                  ))}
                  {day.events.length > 3 && (
                    <p className="text-[10px] text-muted-foreground px-1 mt-0.5">
                      +{day.events.length - 3} more
                    </p>
                  )}
                </div>

                {/* Phones get a count instead of pills -- a 50px-wide cell
                    cannot show a readable label. */}
                {day.events.length > 0 && (
                  <span className="mt-0.5 block text-[10px] font-medium leading-none text-primary sm:hidden">
                    {day.events.length}
                  </span>
                )}

                {/* Cold-chain / NAFDAC cell indicators (bottom-right corner) */}
                {(day.hasColdChain || day.hasNafdac) && (
                  <div className="absolute bottom-1.5 right-1.5 flex gap-0.5 opacity-70">
                    {day.hasColdChain && (
                      <Snowflake className="w-3 h-3 text-blue-400" />
                    )}
                    {day.hasNafdac && (
                      <ShieldCheck className="w-3 h-3 text-green-500" />
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* ---------------------------------------------------------------- */}
        {/* Side preview panel                                               */}
        {/* ---------------------------------------------------------------- */}
        <AnimatePresence>
          {previewOpen && (
            <motion.aside
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 20 }}
              transition={{ duration: 0.18 }}
              className="flex max-h-[45vh] w-full flex-shrink-0 flex-col overflow-y-auto border-t border-border/50 bg-card/60 md:max-h-none md:w-72 md:border-l md:border-t-0"
            >
              {/* Panel header */}
              <div className="flex items-center justify-between px-4 py-3 border-b border-border/40 flex-shrink-0">
                <h3 className="text-sm font-semibold">
                  {selectedDay
                    ? `${MONTH_NAMES[new Date(`${selectedDay.dateStr}T12:00:00`).getMonth()]} ${selectedDay.date}`
                    : "Today's Logistics"}
                </h3>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7"
                  onClick={() => {
                    setPreviewOpen(false);
                    setSelectedDay(null);
                  }}
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              </div>

              {/* Quick actions */}
              <div className="px-4 py-3 border-b border-border/40">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                  Quick Actions
                </p>
                <div className="grid grid-cols-2 gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    className="gap-1.5 text-xs"
                    onClick={() =>
                      toast({
                        title: "Waybill generated",
                        description: "Waybill export queued for download.",
                      })
                    }
                  >
                    <Truck className="h-3 w-3" />
                    Waybill
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="gap-1.5 text-xs"
                    onClick={() =>
                      toast({
                        title: "CoA generated",
                        description: "Certificate of Analysis exported.",
                      })
                    }
                  >
                    <FileText className="h-3 w-3" />
                    CoA
                  </Button>
                </div>
              </div>

              {/* Events for selected day (or today's critical) */}
              <div className="flex-1 px-4 py-3 overflow-y-auto">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-3">
                  {selectedDay ? "Events This Day" : "Critical Today"}
                </p>

                {(() => {
                  const displayEvents = selectedDay
                    ? selectedDay.events
                    : criticalToday;

                  if (displayEvents.length === 0) {
                    return (
                      <p className="text-sm text-muted-foreground">
                        No events scheduled.
                      </p>
                    );
                  }

                  return (
                    <div className="space-y-2">
                      {displayEvents.map((ev) => {
                        const meta = parseMeta(ev.metadata);
                        const cfg = EVENT_CONFIG[ev.event_type] ?? EVENT_CONFIG.other;
                        const statusCfg = meta.status
                          ? STATUS_MAP[meta.status]
                          : null;

                        return (
                          <button
                            key={ev.id}
                            className="w-full text-left rounded-lg border border-border/40 p-2.5 hover:bg-accent/20 transition-colors"
                            onClick={() => setSelectedEvent(ev)}
                          >
                            <div className="flex items-start gap-2">
                              <span
                                className={cn(
                                  "mt-0.5 p-1 rounded flex-shrink-0",
                                  cfg.bgClass,
                                )}
                              >
                                {cfg.icon}
                              </span>
                              <div className="flex-1 min-w-0">
                                <p className="text-xs font-semibold truncate">
                                  {ev.title}
                                </p>
                                <p className="text-[10px] text-muted-foreground">
                                  {cfg.label}
                                </p>
                              </div>
                              <div className="flex flex-col gap-0.5 items-end flex-shrink-0">
                                {meta.is_cold_chain && (
                                  <Snowflake className="w-3 h-3 text-blue-400" />
                                )}
                                {meta.is_nafdac_regulated && (
                                  <ShieldCheck className="w-3 h-3 text-green-500" />
                                )}
                              </div>
                            </div>

                            {(meta.product_name || meta.batch_id) && (
                              <div className="mt-1.5 text-[10px] text-muted-foreground space-y-0.5 text-left">
                                {meta.product_name && (
                                  <p>Product: {meta.product_name}</p>
                                )}
                                {meta.batch_id && <p>Batch: {meta.batch_id}</p>}
                              </div>
                            )}

                            {statusCfg && (
                              <Badge
                                variant={statusCfg.variant}
                                className="mt-1.5 text-[10px] py-0"
                              >
                                {statusCfg.label}
                              </Badge>
                            )}
                          </button>
                        );
                      })}
                    </div>
                  );
                })()}

                {/* Expiry alert list */}
                {alerts.length > 0 && (
                  <div className="mt-4">
                    <Separator className="mb-3" />
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                      Batch Expiry Alerts
                    </p>
                    <div className="space-y-1.5">
                      {alerts.slice(0, 6).map((a: any, i: number) => (
                        <div
                          key={i}
                          className="flex items-center gap-2 text-[11px]"
                        >
                          <AlertTriangle className="h-3 w-3 text-amber-500 flex-shrink-0" />
                          <div className="flex-1 min-w-0">
                            <span className="font-medium truncate block">
                              {a.title}
                            </span>
                            {a.batch_id && (
                              <span className="text-muted-foreground font-mono">
                                {a.batch_id}
                              </span>
                            )}
                          </div>
                          <Badge
                            variant="outline"
                            className="text-[10px] py-0 text-amber-600 border-amber-300 flex-shrink-0 dark:text-amber-300 dark:border-amber-500/30"
                          >
                            {a.days_until_expiry}d
                          </Badge>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </motion.aside>
          )}
        </AnimatePresence>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Event detail dialog                                                 */}
      {/* ------------------------------------------------------------------ */}
      <Dialog
        open={!!selectedEvent}
        onOpenChange={(open) => {
          if (!open) setSelectedEvent(null);
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {selectedEvent && (
                <>
                  <span
                    className={cn(
                      "p-1.5 rounded flex-shrink-0",
                      (EVENT_CONFIG[selectedEvent.event_type] ?? EVENT_CONFIG.other).bgClass,
                    )}
                  >
                    {(EVENT_CONFIG[selectedEvent.event_type] ?? EVENT_CONFIG.other).icon}
                  </span>
                  <span className="truncate">{selectedEvent.title}</span>
                </>
              )}
            </DialogTitle>
            <DialogDescription>
              {selectedEvent?.start_time
                ? new Date(selectedEvent.start_time).toLocaleDateString("en-GB", {
                    weekday: "long",
                    year: "numeric",
                    month: "long",
                    day: "numeric",
                  })
                : ""}
            </DialogDescription>
          </DialogHeader>

          {selectedEvent && (
            <EventDetailBody
              event={selectedEvent}
              onDelete={() => deleteMutation.mutate(selectedEvent.id)}
              deleteLoading={deleteMutation.isPending}
              onClose={() => setSelectedEvent(null)}
            />
          )}
        </DialogContent>
      </Dialog>

      {/* ------------------------------------------------------------------ */}
      {/* Add logistics event dialog                                          */}
      {/* ------------------------------------------------------------------ */}
      <Dialog
        open={showAddDialog}
        onOpenChange={(open) => {
          if (!open) {
            setShowAddDialog(false);
            setForm(defaultForm(todayStr));
          }
        }}
      >
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Schedule Logistics Event</DialogTitle>
            <DialogDescription>
              Add a shipment, dispatch run, warehouse audit, or QC inspection.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            {/* Title */}
            <div className="space-y-1.5">
              <Label htmlFor="ev-title">Event Title *</Label>
              <Input
                id="ev-title"
                placeholder="e.g. Inbound — Paracetamol 500mg from Lagos depot"
                value={form.title}
                onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
              />
            </div>

            {/* Type + Status */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Event Type *</Label>
                <Select
                  value={form.event_type}
                  onValueChange={(v) =>
                    setForm((f) => ({ ...f, event_type: v as LogisticsEventType }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="inbound_inventory">Inbound Inventory</SelectItem>
                    <SelectItem value="regional_dispatch">Regional Dispatch</SelectItem>
                    <SelectItem value="warehouse_audit">Warehouse Audit</SelectItem>
                    <SelectItem value="qc_inspection">QC Inspection</SelectItem>
                    <SelectItem value="meeting">Meeting</SelectItem>
                    <SelectItem value="deadline">Deadline</SelectItem>
                    <SelectItem value="other">Other</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label>Status</Label>
                <Select
                  value={form.status}
                  onValueChange={(v) => setForm((f) => ({ ...f, status: v }))}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="scheduled">Scheduled</SelectItem>
                    <SelectItem value="in_transit">In Transit</SelectItem>
                    <SelectItem value="awaiting_qc">Awaiting QC</SelectItem>
                    <SelectItem value="delivered">Delivered</SelectItem>
                    <SelectItem value="storage_limit_reached">
                      Storage Limit Reached
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Dates */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="ev-start">Date *</Label>
                <Input
                  id="ev-start"
                  type="date"
                  value={form.start_date}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, start_date: e.target.value }))
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="ev-end">End Date (optional)</Label>
                <Input
                  id="ev-end"
                  type="date"
                  value={form.end_date}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, end_date: e.target.value }))
                  }
                />
              </div>
            </div>

            <Separator />

            {/* Pharma batch details */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Batch ID</Label>
                <Input
                  placeholder="PLW-BATCH-0001"
                  value={form.batch_id}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, batch_id: e.target.value }))
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label>Product Name</Label>
                <Input
                  placeholder="Paracetamol 500mg"
                  value={form.product_name}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, product_name: e.target.value }))
                  }
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Quantity (units)</Label>
                <Input
                  type="number"
                  placeholder="5000"
                  value={form.quantity}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, quantity: e.target.value }))
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label>Batch Expiry Date</Label>
                <Input
                  type="date"
                  value={form.batch_expiry}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, batch_expiry: e.target.value }))
                  }
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Supplier</Label>
                <Input
                  placeholder="Fidson Healthcare"
                  value={form.supplier}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, supplier: e.target.value }))
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label>Dispatch Zone</Label>
                <Input
                  placeholder="South-West Nigeria"
                  value={form.dispatch_zone}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, dispatch_zone: e.target.value }))
                  }
                />
              </div>
            </div>

            {/* Compliance toggles */}
            <div className="flex items-center gap-6 pt-1">
              <div className="flex items-center gap-2">
                <Checkbox
                  id="cold-chain"
                  checked={form.is_cold_chain}
                  onCheckedChange={(v) =>
                    setForm((f) => ({ ...f, is_cold_chain: !!v }))
                  }
                />
                <Label
                  htmlFor="cold-chain"
                  className="flex items-center gap-1.5 cursor-pointer font-normal"
                >
                  <Snowflake className="h-3.5 w-3.5 text-blue-500" />
                  Cold Chain Required
                </Label>
              </div>

              <div className="flex items-center gap-2">
                <Checkbox
                  id="nafdac"
                  checked={form.is_nafdac_regulated}
                  onCheckedChange={(v) =>
                    setForm((f) => ({ ...f, is_nafdac_regulated: !!v }))
                  }
                />
                <Label
                  htmlFor="nafdac"
                  className="flex items-center gap-1.5 cursor-pointer font-normal"
                >
                  <ShieldCheck className="h-3.5 w-3.5 text-green-500" />
                  NAFDAC Regulated
                </Label>
              </div>
            </div>

            <div className="space-y-1.5">
              <Label>Notes</Label>
              <Textarea
                placeholder="Additional logistics notes or handling instructions..."
                rows={2}
                value={form.notes}
                onChange={(e) =>
                  setForm((f) => ({ ...f, notes: e.target.value }))
                }
              />
            </div>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setShowAddDialog(false);
                setForm(defaultForm(todayStr));
              }}
            >
              Cancel
            </Button>
            <Button onClick={handleSubmit} disabled={createMutation.isPending}>
              {createMutation.isPending ? "Scheduling…" : "Schedule Event"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Event detail body (extracted to keep main render readable)
// ---------------------------------------------------------------------------

function EventDetailBody({
  event,
  onDelete,
  deleteLoading,
  onClose,
}: {
  event: LogisticsEvent;
  onDelete: () => void;
  deleteLoading: boolean;
  onClose: () => void;
}) {
  const meta = parseMeta(event.metadata);
  const cfg = EVENT_CONFIG[event.event_type] ?? EVENT_CONFIG.other;
  const statusCfg = meta.status ? STATUS_MAP[meta.status] : null;

  return (
    <>
      <div className="space-y-3 py-2">
        {/* Badges row */}
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary" className="gap-1">
            {cfg.icon}
            {cfg.label}
          </Badge>
          {statusCfg && <Badge variant={statusCfg.variant}>{statusCfg.label}</Badge>}
          {meta.is_cold_chain && (
            <Badge variant="outline" className="gap-1 text-blue-600 border-blue-300 dark:text-blue-300 dark:border-blue-500/30">
              <Snowflake className="h-3 w-3" /> Cold Chain
            </Badge>
          )}
          {meta.is_nafdac_regulated && (
            <Badge variant="outline" className="gap-1 text-green-600 border-green-300 dark:text-green-300 dark:border-green-500/30">
              <ShieldCheck className="h-3 w-3" /> NAFDAC
            </Badge>
          )}
        </div>

        {event.description && (
          <p className="text-sm text-muted-foreground">{event.description}</p>
        )}

        {/* Batch details table */}
        {(meta.product_name ||
          meta.batch_id ||
          meta.quantity != null ||
          meta.supplier ||
          meta.dispatch_zone ||
          meta.batch_expiry) && (
          <div className="rounded-md bg-muted/40 p-3 space-y-1.5 text-sm">
            {meta.product_name && (
              <div className="flex justify-between gap-4">
                <span className="text-muted-foreground">Product</span>
                <span className="font-medium text-right">{meta.product_name}</span>
              </div>
            )}
            {meta.batch_id && (
              <div className="flex justify-between gap-4">
                <span className="text-muted-foreground">Batch ID</span>
                <span className="font-mono text-xs font-medium text-right">
                  {meta.batch_id}
                </span>
              </div>
            )}
            {meta.quantity != null && (
              <div className="flex justify-between gap-4">
                <span className="text-muted-foreground">Quantity</span>
                <span className="font-medium text-right">
                  {meta.quantity.toLocaleString()} units
                </span>
              </div>
            )}
            {meta.supplier && (
              <div className="flex justify-between gap-4">
                <span className="text-muted-foreground">Supplier</span>
                <span className="font-medium text-right">{meta.supplier}</span>
              </div>
            )}
            {meta.dispatch_zone && (
              <div className="flex justify-between gap-4">
                <span className="text-muted-foreground">Zone</span>
                <span className="font-medium text-right">{meta.dispatch_zone}</span>
              </div>
            )}
            {meta.batch_expiry && (
              <div className="flex justify-between gap-4">
                <span className="text-muted-foreground">Expires</span>
                <span className="font-medium text-right text-amber-600 dark:text-amber-300">
                  {meta.batch_expiry}
                </span>
              </div>
            )}
          </div>
        )}

        {meta.notes && (
          <div>
            <p className="text-xs font-medium text-muted-foreground mb-1">Notes</p>
            <p className="text-sm">{meta.notes}</p>
          </div>
        )}
      </div>

      <DialogFooter className="gap-2">
        <Button
          variant="destructive"
          size="sm"
          disabled={deleteLoading}
          onClick={onDelete}
        >
          {deleteLoading ? "Removing…" : "Remove Event"}
        </Button>
        <Button variant="outline" size="sm" onClick={onClose}>
          Close
        </Button>
      </DialogFooter>
    </>
  );
}
