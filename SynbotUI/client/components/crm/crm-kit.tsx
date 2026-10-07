/**
 * CRM shared pieces: the deal side panel (timeline, log a call, reminders, move stage, win / lose),
 * new-deal and reminder forms, rep picker and helpers. Used by the pipeline, overview and
 * lead finder so a deal behaves the same wherever it is opened.
 */
import { ReactNode, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, BellPlus, Brain, CheckCircle2, Loader2, Phone, Trophy, XCircle } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { api } from "@/lib/api-client";
import { authClient } from "@/lib/auth-client";
import { Dict, fmtDate, naira } from "@/lib/books-api";

export const STAGE_LABEL: Record<string, string> = { new: "New lead", qualified: "Qualified", proposal: "Proposal & terms", won: "Won", lost: "Lost" };
export const STAGE_TONE: Record<string, string> = {
  new: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300", qualified: "bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300",
  proposal: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300", won: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
  lost: "bg-muted text-muted-foreground",
};
const NEXT: Record<string, string[]> = { new: ["qualified", "proposal"], qualified: ["proposal", "won"], proposal: ["won"], won: [], lost: ["new"] };
export const ACTIVITY_TYPES: [string, string][] = [["call", "Call"], ["visit", "Visit"], ["whatsapp", "WhatsApp"], ["email", "Email"], ["meeting", "Meeting"], ["demo", "Demo"], ["note", "Note"]];

export function StageChip({ stage }: { stage: string }) {
  return <span className={`inline-flex rounded-md px-1.5 py-0.5 text-[11px] font-medium ${STAGE_TONE[stage] ?? "bg-muted"}`}>{STAGE_LABEL[stage] ?? stage}</span>;
}

export function useCrmRefresh() {
  const qc = useQueryClient();
  return () => ["crm-hub", "crm-dashboard"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
}

export const dt = (v?: string | null) => (v ? new Date(v).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—");
export const inDays = (n: number, h = 9) => { const d = new Date(); d.setDate(d.getDate() + n); d.setHours(h, 0, 0, 0); return d.toISOString().slice(0, 16); };

/** The signed-in user's id (JWT "sub"). */
export function myId(): string | null {
  try {
    const t = authClient.getAccessToken();
    if (!t) return null;
    return JSON.parse(atob(t.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))).sub ?? null;
  } catch { return null; }
}

export async function downloadAuthed(url: string, filename: string) {
  const token = authClient.getAccessToken();
  const r = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!r.ok) throw new Error(`Download failed (${r.status})`);
  const blob = await r.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

export function useReps() {
  return useQuery({ queryKey: ["crm-hub", "reps"], queryFn: () => api.crmHub.reps(), staleTime: 300000 });
}

export function RepPick({ value, onChange, allowTeam, placeholder }: { value: string; onChange: (v: string) => void; allowTeam?: boolean; placeholder?: string }) {
  const { data: reps = [] } = useReps();
  return (
    <Select value={value || (allowTeam ? "__team" : undefined)} onValueChange={(v) => onChange(v === "__team" ? "" : v)}>
      <SelectTrigger><SelectValue placeholder={placeholder ?? "Choose rep"} /></SelectTrigger>
      <SelectContent>
        {allowTeam && <SelectItem value="__team">Whole team</SelectItem>}
        {reps.map((r: Dict) => <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>)}
      </SelectContent>
    </Select>
  );
}

function Field({ label, children, className = "" }: { label: string; children: ReactNode; className?: string }) {
  return <div className={`space-y-1 ${className}`}><Label className="text-xs">{label}</Label>{children}</div>;
}

async function run<T>(fn: () => Promise<T>, ok: string): Promise<T | undefined> {
  try { const r = await fn(); toast.success(ok); return r; } catch (e: any) { toast.error(e?.message ?? "Failed"); return undefined; }
}

// ---------------------------------------------------------------------------
// New deal
// ---------------------------------------------------------------------------

export function NewDealSheet({ open, onClose, defaults = {} }: { open: boolean; onClose: () => void; defaults?: Dict }) {
  const refresh = useCrmRefresh();
  const [f, setF] = useState<Dict>({ company_name: "", contact_person: "", contact_phone: "", expected_value: "", product_interest: "", source: "walk_in",
                                     notes: "", next_action: "", assigned_rep: "", ...defaults });
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    const r = await run(() => api.crmHub.createDeal({ ...f, expected_value: f.expected_value ? Number(f.expected_value) : undefined,
      product_interest: String(f.product_interest || "").split(",").map((x: string) => x.trim()).filter(Boolean), assigned_rep: f.assigned_rep || undefined }),
      "Added to the pipeline as a new lead");
    setBusy(false);
    if (r) { refresh(); onClose(); }
  };
  return (
    <DetailSheet open={open} onOpenChange={(o) => !o && onClose()} title="Add a lead" description="It goes into the pipeline as a New lead. If the company is already a customer it is linked to its ACE Books account."
                 footer={<Button className="w-full" disabled={busy || !String(f.company_name).trim()} onClick={save}>{busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Add to pipeline</Button>}>
      <Field label="Company / facility"><Input value={f.company_name} onChange={(e) => setF({ ...f, company_name: e.target.value })} /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Contact person"><Input value={f.contact_person} onChange={(e) => setF({ ...f, contact_person: e.target.value })} /></Field>
        <Field label="Phone"><Input value={f.contact_phone} onChange={(e) => setF({ ...f, contact_phone: e.target.value })} /></Field>
        <Field label="Where from">
          <Select value={f.source} onValueChange={(v) => setF({ ...f, source: v })}><SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>{[["walk_in", "Walk-in"], ["referral", "Referral"], ["phone", "Phone enquiry"], ["website", "Website"], ["event", "Event / visit"], ["lead_finder", "Lead finder"]].map(([v, l]) =>
              <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select></Field>
        <Field label="Expected value (₦)"><Input type="number" value={f.expected_value} onChange={(e) => setF({ ...f, expected_value: e.target.value })} /></Field>
      </div>
      <Field label="Products of interest (comma-separated)"><Input value={f.product_interest} onChange={(e) => setF({ ...f, product_interest: e.target.value })} /></Field>
      <Field label="Owner"><RepPick value={f.assigned_rep} onChange={(v) => setF({ ...f, assigned_rep: v })} placeholder="Me" /></Field>
      <Field label="Next step"><Input value={f.next_action} onChange={(e) => setF({ ...f, next_action: e.target.value })} placeholder="e.g. Send price list" /></Field>
      <Field label="Notes"><Textarea rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
    </DetailSheet>
  );
}

// ---------------------------------------------------------------------------
// Reminder
// ---------------------------------------------------------------------------

export function ReminderSheet({ target, onClose }: { target: { lead_id?: number; customer_id?: number; name?: string } | null; onClose: () => void }) {
  const refresh = useCrmRefresh();
  const [f, setF] = useState({ title: "", due_at: inDays(1), note: "", assigned_rep: "" });
  const save = async () => {
    const r = await run(() => api.crmHub.createReminder({ ...target, title: f.title || "Follow up", due_at: new Date(f.due_at).toISOString(),
                                                           note: f.note || undefined, assigned_rep: f.assigned_rep || undefined }), "Reminder set");
    if (r) { refresh(); onClose(); }
  };
  return (
    <DetailSheet open={!!target} onOpenChange={(o) => !o && onClose()} title={`Reminder${target?.name ? ` · ${target.name}` : ""}`}
                 footer={<Button className="w-full" onClick={save}>Set reminder</Button>}>
      <Field label="What"><Input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="e.g. Call back with prices" /></Field>
      <Field label="When"><Input type="datetime-local" value={f.due_at} onChange={(e) => setF({ ...f, due_at: e.target.value })} /></Field>
      <div className="flex flex-wrap gap-1">{[["Tomorrow", 1], ["In 3 days", 3], ["Next week", 7]].map(([l, n]) =>
        <Button key={l as string} size="sm" variant="outline" className="h-7" onClick={() => setF({ ...f, due_at: inDays(n as number) })}>{l}</Button>)}</div>
      <Field label="For"><RepPick value={f.assigned_rep} onChange={(v) => setF({ ...f, assigned_rep: v })} placeholder="Me" /></Field>
      <Field label="Note"><Textarea rows={2} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></Field>
    </DetailSheet>
  );
}

// ---------------------------------------------------------------------------
// Deal side panel
// ---------------------------------------------------------------------------

export function DealSheet({ id, onClose }: { id: number | null; onClose: () => void }) {
  const refresh = useCrmRefresh();
  const { data, refetch, isLoading } = useQuery({ queryKey: ["crm-hub", "deal", id], queryFn: () => api.crmHub.deal(id!), enabled: !!id });
  const [act, setAct] = useState({ interaction_type: "call", summary: "", outcome: "", next_step: "", follow_up_at: "" });
  const [closing, setClosing] = useState<"won" | "lost" | null>(null);
  const [close, setClose] = useState({ expected_value: "", payment_terms: "", lost_reason: "" });
  const [remind, setRemind] = useState(false);
  const [brief, setBrief] = useState<string | null>(null);
  const [briefBusy, setBriefBusy] = useState(false);
  const d: Dict | undefined = data?.lead;
  const done = () => { refresh(); refetch(); };

  const move = async (stage: string, extra: Dict = {}) => {
    const r = await run(() => api.crmHub.moveDeal(d!.id, stage, extra), stage === "won" ? "Won · customer ready to invoice in ACE Books" : `Moved to ${STAGE_LABEL[stage]}`);
    if (r) { setClosing(null); done(); }
  };
  const log = async () => {
    const r = await run(() => api.crmHub.logActivity({ lead_id: d!.id, ...act, follow_up_at: act.follow_up_at ? new Date(act.follow_up_at).toISOString() : undefined }),
      act.follow_up_at ? "Logged · follow-up reminder set" : "Logged");
    if (r) { setAct({ interaction_type: "call", summary: "", outcome: "", next_step: "", follow_up_at: "" }); done(); }
  };
  const getBrief = async () => {
    setBriefBusy(true);
    try { const b = await api.salesCrm.getLeadBrief(d!.id); setBrief((b as any)?.ai_brief ?? "No brief available."); } catch (e: any) { toast.error(e?.message); }
    setBriefBusy(false);
  };

  return (
    <DetailSheet open={!!id} onOpenChange={(o) => { if (!o) { setBrief(null); setClosing(null); onClose(); } }} title={d?.company_name ?? "Deal"}
                 description={d ? `${STAGE_LABEL[d.stage] ?? d.stage}${d.rep_name ? ` · ${d.rep_name}` : ""}${d.source ? ` · from ${String(d.source).replace("_", " ")}` : ""}` : undefined}>
      {isLoading || !d ? <div className="flex justify-center py-10"><Loader2 className="h-6 w-6 animate-spin" /></div> : (
        <div className="space-y-4 text-sm">
          <div className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-md bg-muted/40 p-3">
            {[["Contact", d.contact_person], ["Phone", d.contact_phone ? <a className="text-primary" href={`tel:${d.contact_phone}`}>{d.contact_phone}</a> : null],
              ["Expected value", Number(d.expected_value) ? naira(d.expected_value) : null], ["Terms", d.payment_terms], ["Next step", d.next_action],
              ["Last contact", d.last_contacted_at ? fmtDate(d.last_contacted_at) : "never"],
              ["Products", (d.product_interest ?? []).join(", ")], ["In pipeline since", fmtDate(d.created_at)]].map(([k, v]) => (
              <div key={k as string}><div className="text-[11px] uppercase text-muted-foreground">{k}</div><div>{v || "—"}</div></div>))}
          </div>
          {d.customer_id && (
            <div className="rounded-md border border-emerald-200 bg-emerald-50/60 p-3 text-xs dark:border-emerald-500/30 dark:bg-emerald-500/10">
              <div className="font-medium">Customer in ACE Books: {d.customer_name}</div>
              {data?.books && <div className="text-muted-foreground">Sales, last 12 months {naira(data.books.sales_12m)} · owes {naira(data.books.balance)} · last invoice {fmtDate(data.books.last_invoice)}</div>}
              <Link to="/customers/workspace" className="mt-1 inline-flex items-center text-primary hover:underline">Customer workspace <ArrowUpRight className="h-3 w-3" /></Link>
            </div>
          )}
          {d.lost_reason && <p className="rounded bg-muted/40 p-2 text-xs">Lost: {d.lost_reason}</p>}

          {["new", "qualified", "proposal", "lost"].includes(d.stage) && (
            <div className="flex flex-wrap gap-2">
              {NEXT[d.stage].filter((s) => s !== "won").map((s) => <Button key={s} size="sm" variant="outline" onClick={() => move(s)}>Move to {STAGE_LABEL[s]}</Button>)}
              {NEXT[d.stage].includes("won") && <Button size="sm" onClick={() => { setClosing("won"); setClose({ ...close, expected_value: String(d.expected_value ?? "") }); }}><Trophy className="mr-1 h-4 w-4" />Won</Button>}
              {d.stage !== "lost" && <Button size="sm" variant="ghost" className="text-red-600" onClick={() => setClosing("lost")}><XCircle className="mr-1 h-4 w-4" />Lost</Button>}
              <Button size="sm" variant="ghost" onClick={() => setRemind(true)}><BellPlus className="mr-1 h-4 w-4" />Reminder</Button>
              <Button size="sm" variant="ghost" onClick={getBrief} disabled={briefBusy}>{briefBusy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Brain className="mr-1 h-4 w-4" />}Pre-call brief</Button>
            </div>
          )}
          {closing === "won" && (
            <div className="space-y-2 rounded-md border p-3">
              <div className="text-xs text-muted-foreground">Marking it won creates the customer in ACE Books (or links the existing one) so Frontdesk / Finance can invoice it. Once its first invoice posts, the deal value follows the invoice.</div>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Deal value (₦)"><Input type="number" value={close.expected_value} onChange={(e) => setClose({ ...close, expected_value: e.target.value })} /></Field>
                <Field label="Agreed terms / payment plan"><Input value={close.payment_terms} onChange={(e) => setClose({ ...close, payment_terms: e.target.value })} /></Field>
              </div>
              <Button className="w-full" onClick={() => move("won", { expected_value: close.expected_value ? Number(close.expected_value) : undefined, payment_terms: close.payment_terms || undefined })}>
                <CheckCircle2 className="mr-1 h-4 w-4" />Confirm won</Button>
            </div>
          )}
          {closing === "lost" && (
            <div className="space-y-2 rounded-md border p-3">
              <Field label="Why was it lost?"><Input value={close.lost_reason} onChange={(e) => setClose({ ...close, lost_reason: e.target.value })} placeholder="e.g. Price, went with another supplier, no budget" /></Field>
              <Button variant="destructive" className="w-full" disabled={close.lost_reason.trim().length < 3} onClick={() => move("lost", { lost_reason: close.lost_reason })}>Confirm lost</Button>
            </div>
          )}
          {brief && <div className="whitespace-pre-wrap rounded-md border border-primary/40 p-3 text-xs">{brief}</div>}

          {["new", "qualified", "proposal"].includes(d.stage) && (
            <div className="space-y-2 rounded-md border p-3">
              <div className="text-xs font-semibold uppercase text-muted-foreground">Log a call or visit</div>
              <div className="grid grid-cols-[130px_1fr] gap-2">
                <Select value={act.interaction_type} onValueChange={(v) => setAct({ ...act, interaction_type: v })}><SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>{ACTIVITY_TYPES.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select>
                <Input placeholder="What happened" value={act.summary} onChange={(e) => setAct({ ...act, summary: e.target.value })} />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Input placeholder="Outcome (e.g. interested)" value={act.outcome} onChange={(e) => setAct({ ...act, outcome: e.target.value })} />
                <Input placeholder="Next step" value={act.next_step} onChange={(e) => setAct({ ...act, next_step: e.target.value })} />
              </div>
              <div className="flex items-end gap-2">
                <Field label="Follow up on (creates a reminder)" className="flex-1"><Input type="datetime-local" value={act.follow_up_at} onChange={(e) => setAct({ ...act, follow_up_at: e.target.value })} /></Field>
                <Button disabled={act.summary.trim().length < 3} onClick={log}><Phone className="mr-1 h-4 w-4" />Log</Button>
              </div>
            </div>
          )}

          {(data?.reminders ?? []).filter((r: Dict) => ["pending", "snoozed"].includes(r.status)).length > 0 && (
            <div><div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">Open reminders</div>
              {(data.reminders as Dict[]).filter((r) => ["pending", "snoozed"].includes(r.status)).map((r) => (
                <div key={r.id} className="flex justify-between border-b py-1 text-xs"><span>{r.title ?? r.reminder_type}</span><span className="text-muted-foreground">{dt(r.due_at)}</span></div>))}</div>
          )}
          <div>
            <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">Timeline</div>
            {(data?.activity ?? []).length === 0 && <p className="text-xs text-muted-foreground">No activity yet.</p>}
            <ol className="space-y-2">{(data?.activity ?? []).map((a: Dict) => (
              <li key={a.id} className="border-l-2 pl-2 text-xs">
                <div className="flex justify-between"><span className="font-medium capitalize">{a.interaction_type.replace("_", " ")}</span><span className="text-muted-foreground">{dt(a.occurred_at)} · {a.by}</span></div>
                <div>{a.summary}</div>
                {(a.outcome || a.next_step) && <div className="text-muted-foreground">{[a.outcome, a.next_step && `next: ${a.next_step}`].filter(Boolean).join(" · ")}</div>}
              </li>))}</ol>
          </div>
        </div>
      )}
      <ReminderSheet target={remind && d ? { lead_id: d.id, name: d.company_name } : null} onClose={() => { setRemind(false); done(); }} />
    </DetailSheet>
  );
}

export { Badge };

// ---------------------------------------------------------------------------
// Log a call / visit with a customer (no deal needed)
// ---------------------------------------------------------------------------

export function ActivitySheet({ target, onClose }: { target: { lead_id?: number; customer_id?: number; name?: string } | null; onClose: () => void }) {
  const refresh = useCrmRefresh();
  const [f, setF] = useState({ interaction_type: "call", summary: "", outcome: "", next_step: "", follow_up_at: "" });
  const save = async () => {
    const r = await run(() => api.crmHub.logActivity({ ...target, ...f, follow_up_at: f.follow_up_at ? new Date(f.follow_up_at).toISOString() : undefined }),
      f.follow_up_at ? "Logged · follow-up reminder set" : "Logged");
    if (r) { refresh(); onClose(); setF({ interaction_type: "call", summary: "", outcome: "", next_step: "", follow_up_at: "" }); }
  };
  return (
    <DetailSheet open={!!target} onOpenChange={(o) => !o && onClose()} title={`Log a call or visit${target?.name ? ` · ${target.name}` : ""}`}
                 footer={<Button className="w-full" disabled={f.summary.trim().length < 3} onClick={save}>Log</Button>}>
      <Field label="Type"><Select value={f.interaction_type} onValueChange={(v) => setF({ ...f, interaction_type: v })}><SelectTrigger><SelectValue /></SelectTrigger>
        <SelectContent>{ACTIVITY_TYPES.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select></Field>
      <Field label="What happened"><Textarea rows={3} value={f.summary} onChange={(e) => setF({ ...f, summary: e.target.value })} /></Field>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Outcome"><Input value={f.outcome} onChange={(e) => setF({ ...f, outcome: e.target.value })} /></Field>
        <Field label="Next step"><Input value={f.next_step} onChange={(e) => setF({ ...f, next_step: e.target.value })} /></Field>
      </div>
      <Field label="Follow up on (creates a reminder)"><Input type="datetime-local" value={f.follow_up_at} onChange={(e) => setF({ ...f, follow_up_at: e.target.value })} /></Field>
    </DetailSheet>
  );
}

// ---------------------------------------------------------------------------
// New customer (shared master - ACE Books invoices the same record)
// ---------------------------------------------------------------------------

export function NewCustomerSheet({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated?: (c: Dict) => void }) {
  const [f, setF] = useState<Dict>({ name: "", contact_person: "", phone: "", email: "", address: "", city: "", facility_type: "pharmacy", payment_terms_days: "30", credit_limit: "" });
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    const r = await run(() => api.crmHub.newCustomer({ ...f, payment_terms_days: Number(f.payment_terms_days) || 30, credit_limit: f.credit_limit ? Number(f.credit_limit) : undefined }),
      "Customer created - ready to invoice in ACE Books");
    setBusy(false);
    if (r) { onCreated?.(r); onClose(); }
  };
  return (
    <DetailSheet open={open} onOpenChange={(o) => !o && onClose()} title="New customer" description="Created in the customer master that ACE Books, Frontdesk and the CRM share. Duplicates are refused."
                 footer={<Button className="w-full" disabled={busy || String(f.name).trim().length < 2} onClick={save}>{busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Create customer</Button>}>
      <Field label="Name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Contact person"><Input value={f.contact_person} onChange={(e) => setF({ ...f, contact_person: e.target.value })} /></Field>
        <Field label="Phone"><Input value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></Field>
        <Field label="Email"><Input value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
        <Field label="Type"><Select value={f.facility_type} onValueChange={(v) => setF({ ...f, facility_type: v })}><SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>{["pharmacy", "hospital", "clinic", "distributor", "ngo", "other"].map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent></Select></Field>
      </div>
      <Field label="Address"><Input value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} /></Field>
      <div className="grid grid-cols-3 gap-2">
        <Field label="City"><Input value={f.city} onChange={(e) => setF({ ...f, city: e.target.value })} /></Field>
        <Field label="Terms (days)"><Input type="number" value={f.payment_terms_days} onChange={(e) => setF({ ...f, payment_terms_days: e.target.value })} /></Field>
        <Field label="Credit limit (₦)"><Input type="number" value={f.credit_limit} onChange={(e) => setF({ ...f, credit_limit: e.target.value })} /></Field>
      </div>
    </DetailSheet>
  );
}
