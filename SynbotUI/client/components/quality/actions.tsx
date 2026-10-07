/**
 * Inventory & Quality actions, shared by the Quality overview, Quality Control, Compliance & QMS and
 * the Logistics Calendar. Each form creates the real record (recall, audit, maintenance job,
 * deviation, incoming batch...) through /quality, which also updates ACE Books where the action
 * touches stock - so the calendar and every page show it without anything being keyed twice.
 *
 *   const qa = useQualityActions();  qa.open("recall", { batch: {...} });
 */
import { createContext, ReactNode, useCallback, useContext, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { BatchPick, CustomerPick, ProductPick } from "@/components/books/kit";
import { api } from "@/lib/api-client";
import { Dict, fmtDate, num } from "@/lib/books-api";
import { useAuth } from "@/components/AuthProvider";

export type QualityAction = "recall" | "audit" | "maintenance" | "deviation" | "batch" | "delivery" | "event";

export const ACTION_LABELS: Record<QualityAction, string> = {
  recall: "Initiate a recall", audit: "Schedule an audit", maintenance: "Schedule maintenance", deviation: "Raise a deviation",
  batch: "Register an incoming batch", delivery: "Expected stock delivery", event: "Other calendar event",
};

const Ctx = createContext<{ open: (a: QualityAction, defaults?: Dict) => void } | null>(null);

export function useQualityActions() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useQualityActions needs <QualityActionsProvider>");
  return c;
}

export const QA_ROLES = ["admin", "quality_assurance", "qa"];

export function useIsQa() {
  const { roles } = useAuth();
  return roles.some((r) => QA_ROLES.includes(r));
}

/** Everything that shows Inventory & Quality data refreshes after an action. */
export function useQualityRefresh() {
  const qc = useQueryClient();
  return useCallback(() => {
    ["quality", "quality-calendar", "stock-orders", "stock-orders-summary", "reorder-plan", "books"].forEach((k) =>
      qc.invalidateQueries({ queryKey: [k] }));
  }, [qc]);
}

const today = () => new Date().toISOString().slice(0, 10);
const plusDays = (n: number, from?: string) => {
  const d = from ? new Date(from) : new Date();
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
};

export function QualityActionsProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState<{ a: QualityAction; d: Dict } | null>(null);
  const open = useCallback((a: QualityAction, d: Dict = {}) => setActive({ a, d }), []);
  const ctx = useMemo(() => ({ open }), [open]);
  const close = () => setActive(null);
  return (
    <Ctx.Provider value={ctx}>
      {children}
      <DetailSheet open={!!active} onOpenChange={(o) => !o && close()} title={active ? ACTION_LABELS[active.a] : ""}
                   description={active ? DESCRIPTIONS[active.a] : undefined}>
        {active && <ActionForm key={`${active.a}-${JSON.stringify(active.d)}`} action={active.a} defaults={active.d} onDone={close} />}
      </DetailSheet>
    </Ctx.Provider>
  );
}

const DESCRIPTIONS: Record<QualityAction, string> = {
  recall: "Opens the recall in ACE Books too: the batch is frozen so it cannot be sold and every customer who bought it is listed for contact.",
  audit: "Appears on the Logistics Calendar on its date. A recurring audit schedules its next occurrence when completed.",
  maintenance: "Appears on the Logistics Calendar on its date.",
  deviation: "If it concerns a maintenance job or an audit, give the new date: the job is moved and the calendar updated.",
  batch: "Held in quarantine in ACE Books (cannot be sold) until QC releases it. Its expected arrival shows on the calendar.",
  delivery: "Sets when a stock order placed with a supplier is expected. Shown on the calendar and on the stock order.",
  event: "A calendar entry that is not tied to a record (meetings, reminders, dispatch runs).",
};

function Field({ label, children, className = "" }: { label: string; children: ReactNode; className?: string }) {
  return <div className={`space-y-1 ${className}`}><Label className="text-xs">{label}</Label>{children}</div>;
}

function Pick({ value, onChange, options, placeholder }: { value: string; onChange: (v: string) => void; options: [string, string][]; placeholder?: string }) {
  return (
    <Select value={value || undefined} onValueChange={onChange}>
      <SelectTrigger><SelectValue placeholder={placeholder ?? "Choose"} /></SelectTrigger>
      <SelectContent>{options.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
    </Select>
  );
}

function ActionForm({ action, defaults, onDone }: { action: QualityAction; defaults: Dict; onDone: () => void }) {
  const refresh = useQualityRefresh();
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<any>, ok: string | ((r: any) => string)) => {
    setBusy(true);
    try {
      const r = await fn();
      toast.success(typeof ok === "function" ? ok(r) : ok);
      refresh();
      onDone();
    } catch (e: any) {
      toast.error(e?.message ?? "Could not save");
    } finally {
      setBusy(false);
    }
  };
  const props = { defaults, busy, run };
  switch (action) {
    case "recall": return <RecallForm {...props} />;
    case "audit": return <AuditForm {...props} />;
    case "maintenance": return <MaintenanceForm {...props} />;
    case "deviation": return <DeviationForm {...props} />;
    case "batch": return <BatchForm {...props} />;
    case "delivery": return <DeliveryForm {...props} />;
    default: return <EventForm {...props} />;
  }
}

type FormProps = { defaults: Dict; busy: boolean; run: (fn: () => Promise<any>, ok: string | ((r: any) => string)) => Promise<void> };

function Submit({ busy, label, disabled }: { busy: boolean; label: string; disabled?: boolean }) {
  return (
    <Button type="submit" className="w-full" disabled={busy || disabled}>
      {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}{label}
    </Button>
  );
}

// ---------------------------------------------------------------------------

function RecallForm({ defaults, busy, run }: FormProps) {
  const [batch, setBatch] = useState<Dict | null>(defaults.batch ?? null);
  const [f, setF] = useState({ reason: "", scope: "voluntary", severity: "major", authority: "NAFDAC",
                               expected: defaults.date ?? plusDays(14), notified: false });
  // a customer bringing this batch back now (e.g. "we ordered three, they delivered five")
  const [cust, setCust] = useState<Dict | null>(null);
  const [inv, setInv] = useState("");
  const [rq, setRq] = useState({ qty: "", price: "" });
  const { data: invoices } = useQuery({ queryKey: ["quality", "cust-invoices", cust?.id, batch?.sku], enabled: !!cust && !!batch,
                                       queryFn: () => api.quality.customerInvoices(cust!.id, { sku: batch?.sku, batch_id: batch?.id ?? batch?.batch_id }) });
  const chosen = (invoices ?? []).find((i: Dict) => `${i.sage ? "s" : "a"}:${i.invoice_number}` === inv);
  const line = chosen?.lines?.find((l: Dict) => l.sku === batch?.sku) ?? chosen?.lines?.[0];
  return (
    <form className="space-y-3" onSubmit={(e) => {
      e.preventDefault();
      run(() => api.quality.openRecall({ batch_id: batch?.id ?? batch?.batch_id, recall_reason: f.reason, scope: f.scope, severity: f.severity,
                                         regulatory_authority: f.authority, expected_return_date: f.expected, nafdac_notified: f.notified,
                                         ...(cust && Number(rq.qty) > 0 ? {
                                           customer_id: cust.id, return_quantity: Number(rq.qty), unit_price: Number(rq.price || line?.unit_price || 0),
                                           unit_cost: line?.unit_cost ?? undefined, invoice_id: chosen?.invoice_id || undefined,
                                           sage_invoice_number: chosen?.sage ? chosen.invoice_number : undefined } : {}) }),
          (r) => `${r.recall_id} opened · ${r.fin_recall_number ?? ""} in ACE Books, ${r.customers ?? 0} customers to contact${cust && Number(rq.qty) > 0 ? ` · ${cust.name}'s return credited` : ""}`);
    }}>
      <BatchPick label="Batch (from ACE Books stock)" value={batch} onChange={setBatch} />
      <Field label="Reason"><Textarea rows={3} value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} placeholder="e.g. NAFDAC alert, suspected contamination" /></Field>
      <div className="space-y-2 rounded-md border p-2">
        <div className="text-xs font-medium">Customer returning it (optional)</div>
        <CustomerPick label="Customer" value={cust} onChange={(c) => { setCust(c); setInv(""); }} />
        {cust && batch && (
          <>
            <select className="h-8 w-full rounded-md border bg-background px-2 text-xs" value={inv} onChange={(e) => setInv(e.target.value)}>
              <option value="">Invoice it was bought on…</option>
              {(invoices ?? []).map((i: Dict) => <option key={`${i.sage ? "s" : "a"}:${i.invoice_number}`} value={`${i.sage ? "s" : "a"}:${i.invoice_number}`}>{i.invoice_number} · {fmtDate(i.invoice_date)}</option>)}
            </select>
            <div className="grid grid-cols-2 gap-2">
              <Input className="h-8" type="number" placeholder="Quantity returned" value={rq.qty} onChange={(e) => setRq({ ...rq, qty: e.target.value })} />
              <Input className="h-8" type="number" placeholder={line?.unit_price ? `Credit per unit (₦${Number(line.unit_price).toLocaleString()})` : "Credit per unit ₦"}
                     value={rq.price} onChange={(e) => setRq({ ...rq, price: e.target.value })} />
            </div>
            <p className="text-[11px] text-muted-foreground">A credit note is raised on that invoice (the customer's balance goes down) and the units come back into the frozen batch.</p>
          </>
        )}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Scope"><Pick value={f.scope} onChange={(v) => setF({ ...f, scope: v })} options={[["voluntary", "Voluntary"], ["mandatory", "Mandatory"]]} /></Field>
        <Field label="Severity"><Pick value={f.severity} onChange={(v) => setF({ ...f, severity: v })} options={[["critical", "Critical"], ["major", "Major"], ["minor", "Minor"]]} /></Field>
        <Field label="Authority"><Input value={f.authority} onChange={(e) => setF({ ...f, authority: e.target.value })} /></Field>
        <Field label="Stock due back by"><Input type="date" value={f.expected} onChange={(e) => setF({ ...f, expected: e.target.value })} /></Field>
      </div>
      <label className="flex items-center gap-2 text-sm"><Checkbox checked={f.notified} onCheckedChange={(v) => setF({ ...f, notified: !!v })} /> NAFDAC already notified</label>
      <Submit busy={busy} label="Initiate recall" disabled={!batch || f.reason.trim().length < 5} />
    </form>
  );
}

function AuditForm({ defaults, busy, run }: FormProps) {
  const [f, setF] = useState({ audit_type: defaults.audit_type ?? "Self Audit", department: defaults.department ?? "Warehouse",
                               scheduled_date: defaults.date ?? plusDays(7), frequency: "ad_hoc", risk_level: "medium", assigned_to: "", notes: "" });
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); run(() => api.quality.scheduleAudit(f), `${f.audit_type} scheduled for ${fmtDate(f.scheduled_date)}`); }}>
      <Field label="Audit"><Input list="audit-types" value={f.audit_type} onChange={(e) => setF({ ...f, audit_type: e.target.value })} />
        <datalist id="audit-types">{["Self Audit", "Cold Chain Audit", "Warehouse / GDP Audit", "Stock Count Audit", "Supplier Audit", "Document Control Audit"].map((t) => <option key={t} value={t} />)}</datalist></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Department"><Input value={f.department} onChange={(e) => setF({ ...f, department: e.target.value })} /></Field>
        <Field label="Date"><Input type="date" value={f.scheduled_date} onChange={(e) => setF({ ...f, scheduled_date: e.target.value })} /></Field>
        <Field label="Repeats"><Pick value={f.frequency} onChange={(v) => setF({ ...f, frequency: v })}
          options={[["ad_hoc", "Once"], ["monthly", "Monthly"], ["quarterly", "Quarterly"], ["biannual", "Every 6 months"], ["annual", "Yearly"]]} /></Field>
        <Field label="Risk"><Pick value={f.risk_level} onChange={(v) => setF({ ...f, risk_level: v })} options={[["low", "Low"], ["medium", "Medium"], ["high", "High"], ["critical", "Critical"]]} /></Field>
      </div>
      <Field label="Auditor"><Input value={f.assigned_to} onChange={(e) => setF({ ...f, assigned_to: e.target.value })} placeholder="Who will carry it out" /></Field>
      <Field label="Scope / notes"><Textarea rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
      <Submit busy={busy} label="Schedule audit" />
    </form>
  );
}

function MaintenanceForm({ defaults, busy, run }: FormProps) {
  const { data } = useQuery({ queryKey: ["quality", "equipment"], queryFn: () => api.compliance.equipment() });
  const equipment: Dict[] = (data as any)?.equipment ?? (data as any)?.data ?? [];
  const [f, setF] = useState({ equipment_id: defaults.equipment_id ?? "", maintenance_type: "preventive",
                               next_maintenance_date: defaults.date ?? plusDays(7), interval_days: "90" });
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); run(() => api.quality.scheduleMaintenance({ ...f, interval_days: Number(f.interval_days) }), "Maintenance scheduled"); }}>
      <Field label="Equipment"><Pick value={f.equipment_id} onChange={(v) => setF({ ...f, equipment_id: v })}
        options={equipment.map((e) => [e.id, `${e.equipment_name} · ${e.location}`] as [string, string])} placeholder={equipment.length ? "Choose equipment" : "No equipment registered"} /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Type"><Pick value={f.maintenance_type} onChange={(v) => setF({ ...f, maintenance_type: v })}
          options={[["preventive", "Preventive"], ["calibration", "Calibration"], ["inspection", "Inspection"], ["repair", "Repair"]]} /></Field>
        <Field label="Date"><Input type="date" value={f.next_maintenance_date} onChange={(e) => setF({ ...f, next_maintenance_date: e.target.value })} /></Field>
        <Field label="Repeat every (days)"><Input type="number" value={f.interval_days} onChange={(e) => setF({ ...f, interval_days: e.target.value })} /></Field>
      </div>
      <Submit busy={busy} label="Schedule maintenance" disabled={!f.equipment_id} />
    </form>
  );
}

const TRIGGERS: [string, string][] = [
  ["manual", "Observed / reported"], ["missed_maintenance", "Missed or failed maintenance"], ["audit_failure", "Audit finding"],
  ["inspection_failed", "Failed inspection"], ["temperature_breach", "Temperature excursion"], ["missed_activity", "Missed compliance activity"],
  ["nafdac_violation", "NAFDAC / regulatory"],
];

function DeviationForm({ defaults, busy, run }: FormProps) {
  const [f, setF] = useState({ classification: defaults.classification ?? "minor", trigger_type: defaults.trigger_type ?? "manual",
                               trigger_ref: defaults.trigger_ref ?? "", observation: defaults.observation ?? "", responsible_department: defaults.department ?? "Quality Assurance",
                               responsible_person: "", target_close_date: plusDays(30), reschedule_date: defaults.reschedule_date ?? "" });
  const [capa, setCapa] = useState<Dict[]>([]);
  const needsJob = f.trigger_type === "missed_maintenance" || f.trigger_type === "audit_failure";
  const { data: maint } = useQuery({ queryKey: ["quality", "maintenance-list"], queryFn: () => api.compliance.maintenance(), enabled: f.trigger_type === "missed_maintenance" });
  const { data: audits } = useQuery({ queryKey: ["quality", "audit-list"], queryFn: () => api.compliance.audits(), enabled: f.trigger_type === "audit_failure" });
  const jobs: [string, string][] = f.trigger_type === "missed_maintenance"
    ? ((maint as any)?.maintenance ?? []).map((m: Dict) => [m.id, `${m.equipment_registry?.equipment_name ?? "Equipment"} · ${m.maintenance_type} · due ${fmtDate(m.next_maintenance_date)}`])
    : ((audits as any)?.audits ?? []).map((a: Dict) => [a.id, `${a.audit_type} · ${a.department} · ${a.scheduled_date ? fmtDate(a.scheduled_date) : `${a.month_due}/${a.year}`}`]);
  return (
    <form className="space-y-3" onSubmit={(e) => {
      e.preventDefault();
      run(() => api.quality.raiseDeviation({ ...f, trigger_ref: f.trigger_ref || undefined, reschedule_date: f.reschedule_date || undefined,
                                             capa_actions: capa.filter((c) => c.action?.trim()).map((c) => ({ ...c, status: "open" })) }),
          (r) => `${r.deviation_id} raised${r.rescheduled ? ` · ${r.rescheduled.kind} moved to ${fmtDate(r.rescheduled.date)}` : ""}`);
    }}>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Type"><Pick value={f.trigger_type} onChange={(v) => setF({ ...f, trigger_type: v, trigger_ref: "" })} options={TRIGGERS} /></Field>
        <Field label="Classification"><Pick value={f.classification} onChange={(v) => setF({ ...f, classification: v })} options={[["minor", "Minor"], ["major", "Major"], ["critical", "Critical"]]} /></Field>
      </div>
      {needsJob && (
        <div className="grid grid-cols-2 gap-3 rounded-md border p-2">
          <Field label={f.trigger_type === "missed_maintenance" ? "Maintenance job" : "Audit"} className="col-span-2">
            <Pick value={f.trigger_ref} onChange={(v) => setF({ ...f, trigger_ref: v })} options={jobs} placeholder="Link the job it concerns" /></Field>
          <Field label={f.trigger_type === "missed_maintenance" ? "New maintenance date" : "Follow-up audit date"} className="col-span-2">
            <Input type="date" value={f.reschedule_date} onChange={(e) => setF({ ...f, reschedule_date: e.target.value })} /></Field>
        </div>
      )}
      <Field label="What happened"><Textarea rows={3} value={f.observation} onChange={(e) => setF({ ...f, observation: e.target.value })} /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Department"><Input value={f.responsible_department} onChange={(e) => setF({ ...f, responsible_department: e.target.value })} /></Field>
        <Field label="Owner"><Input value={f.responsible_person} onChange={(e) => setF({ ...f, responsible_person: e.target.value })} /></Field>
        <Field label="Close by"><Input type="date" value={f.target_close_date} onChange={(e) => setF({ ...f, target_close_date: e.target.value })} /></Field>
      </div>
      <CapaEditor rows={capa} onChange={setCapa} />
      <Submit busy={busy} label="Raise deviation" disabled={f.observation.trim().length < 10} />
    </form>
  );
}

export function CapaEditor({ rows, onChange }: { rows: Dict[]; onChange: (r: Dict[]) => void }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label className="text-xs">Corrective / preventive actions (each shows on the calendar on its due date)</Label>
        <Button type="button" size="sm" variant="ghost" onClick={() => onChange([...rows, { action: "", owner: "", due_date: plusDays(14), status: "open" }])}>
          <Plus className="mr-1 h-3.5 w-3.5" />Add</Button>
      </div>
      {rows.map((r, i) => (
        <div key={i} className="grid grid-cols-[1fr_110px_130px_32px] gap-2">
          <Input placeholder="Action" value={r.action} onChange={(e) => onChange(rows.map((x, j) => (j === i ? { ...x, action: e.target.value } : x)))} />
          <Input placeholder="Owner" value={r.owner} onChange={(e) => onChange(rows.map((x, j) => (j === i ? { ...x, owner: e.target.value } : x)))} />
          <Input type="date" value={r.due_date} onChange={(e) => onChange(rows.map((x, j) => (j === i ? { ...x, due_date: e.target.value } : x)))} />
          <Button type="button" size="icon" variant="ghost" onClick={() => onChange(rows.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></Button>
        </div>
      ))}
    </div>
  );
}

function BatchForm({ defaults, busy, run }: FormProps) {
  const isQa = useIsQa();
  const [product, setProduct] = useState<Dict | null>(defaults.product ?? null);
  const { data: orders } = useQuery({ queryKey: ["stock-orders", "ordered"], queryFn: () => api.procurement.stockOrders("ordered").catch(() => []) });
  const [f, setF] = useState({ batch_number: defaults.batch_number ?? "", expected_arrival_date: defaults.date ?? plusDays(7), quantity: "", expiry_date: "",
                               supplier: "", nafdac_reg_number: "", certificate_ref: "", stock_order_id: "", notes: "", release_now: false });
  const pickOrder = (id: string) => {
    const o = (orders ?? []).find((x: Dict) => x.id === id);
    setF({ ...f, stock_order_id: id, quantity: o ? String(o.requested_qty) : f.quantity, supplier: o?.supplier_name ?? f.supplier,
           expected_arrival_date: o?.expected_date ?? f.expected_arrival_date });
    if (o) setProduct({ sku: o.sku, name: o.name });
  };
  return (
    <form className="space-y-3" onSubmit={(e) => {
      e.preventDefault();
      run(() => api.quality.registerBatch({ ...f, sku: product?.sku, quantity: f.quantity ? Number(f.quantity) : undefined,
                                           expiry_date: f.expiry_date || undefined, stock_order_id: f.stock_order_id || undefined }),
          f.release_now ? "Batch registered and released" : "Batch registered · on the calendar, held until QC releases it");
    }}>
      {(orders ?? []).length > 0 && (
        <Field label="From a stock order (optional)"><Pick value={f.stock_order_id} onChange={pickOrder}
          options={(orders ?? []).map((o: Dict) => [o.id, `${o.name} · ${num(o.requested_qty)} units · ${o.supplier_name ?? ""}`] as [string, string])} /></Field>
      )}
      <ProductPick label="Product (ACE Books)" value={product} onChange={setProduct} />
      <div className="grid grid-cols-2 gap-3">
        <Field label="Batch / lot number"><Input value={f.batch_number} onChange={(e) => setF({ ...f, batch_number: e.target.value })} /></Field>
        <Field label="Expected arrival"><Input type="date" value={f.expected_arrival_date} onChange={(e) => setF({ ...f, expected_arrival_date: e.target.value })} /></Field>
        <Field label="Quantity"><Input type="number" value={f.quantity} onChange={(e) => setF({ ...f, quantity: e.target.value })} /></Field>
        <Field label="Expiry date"><Input type="date" value={f.expiry_date} onChange={(e) => setF({ ...f, expiry_date: e.target.value })} /></Field>
        <Field label="Supplier"><Input value={f.supplier} onChange={(e) => setF({ ...f, supplier: e.target.value })} /></Field>
        <Field label="NAFDAC reg. no."><Input value={f.nafdac_reg_number} onChange={(e) => setF({ ...f, nafdac_reg_number: e.target.value })} /></Field>
        <Field label="Certificate / CoA ref" className="col-span-2"><Input value={f.certificate_ref} onChange={(e) => setF({ ...f, certificate_ref: e.target.value })} /></Field>
      </div>
      {isQa && <label className="flex items-center gap-2 text-sm"><Checkbox checked={f.release_now} onCheckedChange={(v) => setF({ ...f, release_now: !!v })} />
        Already checked - release it now</label>}
      <Submit busy={busy} label={f.release_now ? "Register and release" : "Register batch"} disabled={!product || !f.batch_number.trim()} />
    </form>
  );
}

function DeliveryForm({ defaults, busy, run }: FormProps) {
  const { data: orders, isLoading } = useQuery({ queryKey: ["stock-orders", "ordered"], queryFn: () => api.procurement.stockOrders("ordered").catch(() => []) });
  const [id, setId] = useState("");
  const [date, setDate] = useState(defaults.date ?? plusDays(7));
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); run(() => api.quality.move("stock_order", id, date), `Delivery expected ${fmtDate(date)}`); }}>
      <Field label="Stock order placed with a supplier">
        <Pick value={id} onChange={setId} placeholder={isLoading ? "Loading…" : (orders ?? []).length ? "Choose the order" : "No orders with suppliers"}
          options={(orders ?? []).map((o: Dict) => [o.id, `${o.name} · ${num(o.requested_qty)} units · ${o.supplier_name ?? ""}${o.expected_date ? ` · now ${fmtDate(o.expected_date)}` : ""}`] as [string, string])} />
      </Field>
      <Field label="Expected on"><Input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
      <p className="text-xs text-muted-foreground">Orders are raised and placed on Operations › Stock Orders & Purchases; they are received automatically when the supplier bill is posted in ACE Books.</p>
      <Submit busy={busy} label="Set delivery date" disabled={!id} />
    </form>
  );
}

function EventForm({ defaults, busy, run }: FormProps) {
  const [f, setF] = useState({ title: "", event_type: "regional_dispatch", date: defaults.date ?? today(), time: "09:00", location: "", description: "" });
  return (
    <form className="space-y-3" onSubmit={(e) => {
      e.preventDefault();
      run(() => api.calendar.create({ title: f.title, event_type: f.event_type, start_time: `${f.date}T${f.time}:00`, location: f.location || undefined,
                                      description: f.description || undefined }), "Added to the calendar");
    }}>
      <Field label="Title"><Input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Kind"><Pick value={f.event_type} onChange={(v) => setF({ ...f, event_type: v })}
          options={[["regional_dispatch", "Dispatch run"], ["meeting", "Meeting"], ["reminder", "Reminder"], ["deadline", "Deadline"], ["holiday", "Holiday / closure"], ["other", "Other"]]} /></Field>
        <Field label="Location"><Input value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} /></Field>
        <Field label="Date"><Input type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>
        <Field label="Time"><Input type="time" value={f.time} onChange={(e) => setF({ ...f, time: e.target.value })} /></Field>
      </div>
      <Field label="Notes"><Textarea rows={2} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
      <Submit busy={busy} label="Add to calendar" disabled={!f.title.trim()} />
    </form>
  );
}
