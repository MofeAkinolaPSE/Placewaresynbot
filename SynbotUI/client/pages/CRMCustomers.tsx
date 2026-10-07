/**
 * CRM › Customers. Every customer with real numbers from ACE Books (sales, orders, margin, reorder
 * cycle, balance, overdue) and the CRM (owner, open deal, last contact, next follow-up), grouped
 * into Active / New / Lapsing / Lapsed / Never bought, with the reason a customer is at risk.
 * The side panel is the customer's full picture and where the rep acts on them: log a call, set a
 * reminder, open a deal, raise a request, edit details. Backend: services/crm_hub.customer_directory / customer_profile.
 */
import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlarmClock, AlertTriangle, ArrowDownRight, ArrowUpRight, Download, Kanban, Loader2, Pencil, Phone, Plus, ShoppingCart, Users, Wallet } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { ReportButton } from "@/components/reports/ReportButton";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { PageHeader } from "@/components/workspace/PageHeader";
import { DrillLink } from "@/components/books/kit";
import { DrillProvider, RecordView } from "@/components/books/lineage";
import { useAuth } from "@/components/AuthProvider";
import { api } from "@/lib/api-client";
import { Dict, downloadCsv, fmtDate, naira, num } from "@/lib/books-api";
import { ActivitySheet, dt, NewCustomerSheet, NewDealSheet, ReminderSheet, RepPick, StageChip } from "@/components/crm/crm-kit";

const SEG: Record<string, [string, string]> = {
  active: ["Active", "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300"],
  new: ["New", "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300"],
  lapsing: ["Lapsing", "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300"],
  lapsed: ["Lapsed", "bg-muted text-muted-foreground"],
  never: ["Never bought", "bg-muted text-muted-foreground"],
};
const compact = (v: number) => (Math.abs(v) >= 1e9 ? `₦${(v / 1e9).toFixed(1)}bn` : Math.abs(v) >= 1e6 ? `₦${(v / 1e6).toFixed(1)}M` : naira(v));
const FILTERS: [string, string][] = [["buying", "Buying (active & new)"], ["at_risk", "At risk"], ["due", "Due to reorder"], ["owes", "Owes past due"],
  ["lapsing", "Lapsing"], ["lapsed", "Lapsed"], ["never", "Never bought"], ["all", "All"]];
const SORTS: [string, string][] = [["sales_12m", "Sales, 12 months"], ["trend_pct", "Growth"], ["overdue", "Past due"], ["last_order", "Last order"],
  ["reorder_due_in", "Reorder due"], ["name", "Name"]];

export default function CRMCustomers() {
  return <DrillProvider><CustomersPage /></DrillProvider>;
}

function Seg({ s }: { s: string }) {
  return <span className={`inline-flex whitespace-nowrap rounded-md px-1.5 py-0.5 text-[11px] font-medium ${SEG[s]?.[1] ?? "bg-muted"}`}>{SEG[s]?.[0] ?? s}</span>;
}

function CustomersPage() {
  const { data, isLoading } = useQuery({ queryKey: ["crm-hub", "directory"], queryFn: () => api.crmHub.directory() });
  const [filter, setFilter] = useState("buying");
  const [search, setSearch] = useState("");
  const [rep, setRep] = useState("");
  const [sort, setSort] = useState("sales_12m");
  const [shown, setShown] = useState(50);
  // ?customer=<id> opens that customer's panel (links from the executive overview)
  const [params] = useSearchParams();
  const [picked, setPicked] = useState<number | null>(() => Number(params.get("customer")) || null);
  const [adding, setAdding] = useState(false);
  const all: Dict[] = data?.customers ?? [];
  const c = data?.counts ?? {};
  const due = (x: Dict) => x.reorder_due_in != null && x.reorder_due_in <= 7 && x.reorder_due_in >= -(Number(x.avg_gap_days) || 30);
  const rows = useMemo(() => {
    const qq = search.trim().toLowerCase();
    const f = all.filter((x) => {
      if (filter === "buying" && !["active", "new"].includes(x.segment)) return false;
      if (filter === "at_risk" && !x.at_risk) return false;
      if (filter === "due" && !due(x)) return false;
      if (filter === "owes" && !(Number(x.overdue) > 0)) return false;
      if (["lapsing", "lapsed", "never"].includes(filter) && x.segment !== filter) return false;
      if (rep && x.owner !== rep) return false;
      return !qq || `${x.name} ${x.customer_code ?? ""} ${x.phone ?? ""} ${x.city ?? ""} ${x.contact_person ?? ""}`.toLowerCase().includes(qq);
    });
    const key = sort;
    return f.sort((a, b) => {
      if (key === "name") return String(a.name).localeCompare(String(b.name));
      if (key === "reorder_due_in") return (a.reorder_due_in ?? 9999) - (b.reorder_due_in ?? 9999);
      if (key === "last_order") return String(b.last_order ?? "").localeCompare(String(a.last_order ?? ""));
      return (Number(b[key]) || -1e15) - (Number(a[key]) || -1e15);
    });
  }, [all, filter, search, rep, sort]);
  const counts: Record<string, number> = { buying: (c.active ?? 0) + (c.new ?? 0), at_risk: c.at_risk ?? 0, due: all.filter(due).length,
    owes: all.filter((x) => Number(x.overdue) > 0).length, lapsing: c.lapsing ?? 0, lapsed: c.lapsed ?? 0, never: c.never ?? 0, all: data?.total ?? 0 };

  return (
    <div className="space-y-5">
      <PageHeader icon={Users} title="Customers" subtitle={`Every customer with their ACE Books numbers${data ? ` (sales to ${fmtDate(data.as_of)})` : ""} - open one to act on it`}
        actions={<div className="flex gap-2">
          <Button variant="outline" onClick={() => downloadCsv("customers.csv", rows.map((x) => ({ name: x.name, code: x.customer_code, segment: x.segment,
            sales_12m: x.sales_12m, trend_pct: x.trend_pct, margin_pct: x.margin_pct, orders_12m: x.orders_12m, last_order: x.last_order, owes: x.balance,
            past_due: x.overdue, owner: x.owner_name, phone: x.phone, city: x.city })))}><Download className="mr-1.5 h-4 w-4" />Export</Button>
          <Button onClick={() => setAdding(true)}><Plus className="mr-1.5 h-4 w-4" />New customer</Button></div>} />
      <KpiStrip items={[
        { label: "Buying customers", value: counts.buying, icon: Users, sub: `${c.new ?? 0} new in 90 days · ${data?.total ?? 0} on file`, onClick: () => setFilter("buying") },
        { label: "Sales, 12 months", value: data ? compact(data.totals.sales_12m) : "—", icon: ShoppingCart, sub: "ACE Books" },
        { label: "At risk", value: counts.at_risk, icon: AlertTriangle, tone: counts.at_risk ? "warning" : "success", sub: "falling sales, past reorder or long overdue", onClick: () => setFilter("at_risk") },
        { label: "Owed by customers", value: data ? compact(data.totals.balance) : "—", icon: Wallet, tone: "warning",
          sub: data ? `${compact(data.totals.overdue)} past due · ${counts.owes} customers` : undefined, onClick: () => setFilter("owes") },
      ]} />
      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map(([k, l]) => <Button key={k} size="sm" className="h-8" variant={filter === k ? "default" : "outline"} onClick={() => { setFilter(k); setShown(50); }}>
          {l} <span className="ml-1.5 opacity-70">{counts[k]}</span></Button>)}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Input className="h-9 w-72" placeholder="Search name, code, phone, city, contact" value={search} onChange={(e) => { setSearch(e.target.value); setShown(50); }} />
        <div className="w-52"><RepPick value={rep} onChange={setRep} allowTeam placeholder="Any owner" /></div>
        <Select value={sort} onValueChange={setSort}><SelectTrigger className="h-9 w-48"><SelectValue /></SelectTrigger>
          <SelectContent>{SORTS.map(([v, l]) => <SelectItem key={v} value={v}>Sort: {l}</SelectItem>)}</SelectContent></Select>
        <span className="ml-auto text-xs text-muted-foreground">{rows.length} customers</span>
      </div>
      <Card><CardContent className="p-0">
        {isLoading ? <div className="flex justify-center py-16"><Loader2 className="h-6 w-6 animate-spin" /></div> : rows.length === 0 ? (
          <p className="p-8 text-center text-sm text-muted-foreground">No customers in this view.</p>
        ) : (
          <Table>
            <TableHeader><TableRow>
              <TableHead>Customer</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Sales, 12m</TableHead>
              <TableHead className="text-right">Orders</TableHead><TableHead>Last order</TableHead><TableHead>Next order</TableHead>
              <TableHead className="text-right">Owes</TableHead><TableHead>Owner · next step</TableHead>
            </TableRow></TableHeader>
            <TableBody>{rows.slice(0, shown).map((x) => (
              <TableRow key={x.id} className="cursor-pointer" onClick={() => setPicked(x.id)}>
                <TableCell className="max-w-[260px]">
                  <div className="truncate font-medium">{x.name}</div>
                  <div className="truncate text-[11px] text-muted-foreground">{[x.facility_type, x.city, x.phone].filter(Boolean).join(" · ") || x.customer_code}</div>
                </TableCell>
                <TableCell><Seg s={x.segment} />{x.at_risk && <div className="mt-0.5 max-w-[170px] truncate text-[10px] text-amber-700 dark:text-amber-300" title={x.risk_reasons.join("; ")}>⚠ {x.risk_reasons[0]}</div>}</TableCell>
                <TableCell className="whitespace-nowrap text-right">{Number(x.sales_12m) ? compact(Number(x.sales_12m)) : "—"}
                  {x.trend_pct != null && <div className={`text-[11px] ${x.trend_pct >= 0 ? "text-emerald-600" : "text-red-600"}`}>
                    {x.trend_pct >= 0 ? <ArrowUpRight className="inline h-3 w-3" /> : <ArrowDownRight className="inline h-3 w-3" />}{Math.abs(x.trend_pct)}%</div>}</TableCell>
                <TableCell className="text-right text-xs">{x.orders_12m || "—"}{x.avg_gap_days && <div className="text-[11px] text-muted-foreground">every {x.avg_gap_days}d</div>}</TableCell>
                <TableCell className="whitespace-nowrap text-xs">{x.last_order ? fmtDate(x.last_order) : "never"}{x.days_since_order != null && <div className="text-[11px] text-muted-foreground">{x.days_since_order}d ago</div>}</TableCell>
                <TableCell className="whitespace-nowrap text-xs">{x.reorder_due_in == null ? "—" : x.reorder_due_in < 0
                  ? <span className="text-red-600">{-x.reorder_due_in}d late</span> : x.reorder_due_in === 0 ? "today" : `in ${x.reorder_due_in}d`}</TableCell>
                <TableCell className="whitespace-nowrap text-right">{Number(x.balance) > 0 ? compact(Number(x.balance)) : "—"}
                  {Number(x.overdue) > 0 && <div className="text-[11px] text-red-600">{compact(Number(x.overdue))} past due</div>}
                  {x.credit_used_pct != null && x.credit_used_pct > 90 && <div className="text-[10px] text-amber-700">{x.credit_used_pct}% of limit</div>}</TableCell>
                <TableCell className="max-w-[180px] text-xs"><div className="truncate">{x.owner_name ?? "unassigned"}</div>
                  <div className="truncate text-[11px] text-muted-foreground">{x.deal_stage ? <>deal: {x.deal_stage}</> : x.next_reminder ? `follow up ${dt(x.next_reminder)}` : x.last_contact ? `contacted ${fmtDate(x.last_contact)}` : "no contact logged"}</div></TableCell>
              </TableRow>))}</TableBody>
          </Table>
        )}
      </CardContent></Card>
      {rows.length > shown && <div className="flex justify-center"><Button variant="outline" onClick={() => setShown(shown + 100)}>Show more ({rows.length - shown} left)</Button></div>}
      <CustomerPanel id={picked} onClose={() => setPicked(null)} />
      <NewCustomerSheet open={adding} onClose={() => setAdding(false)} onCreated={(x) => setPicked(x.id)} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// The customer panel
// ---------------------------------------------------------------------------

function CustomerPanel({ id, onClose }: { id: number | null; onClose: () => void }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data: p, isLoading } = useQuery({ queryKey: ["crm-hub", "customer", id], queryFn: () => api.crmHub.customer(id!), enabled: !!id });
  const [action, setAction] = useState<null | "call" | "reminder" | "deal" | "edit">(null);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["crm-hub"] }); };
  const c = p?.customer, m = p?.metrics ?? {};
  return (
    <Sheet open={!!id} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-3xl">
        {isLoading || !p ? <div className="flex justify-center py-16"><Loader2 className="h-6 w-6 animate-spin" /></div> : (
          <div className="space-y-4">
            <SheetHeader>
              <SheetTitle className="flex flex-wrap items-center gap-2">{c.name} <Seg s={m.segment} /></SheetTitle>
              <SheetDescription>{[c.customer_code, c.facility_type, c.city, c.owner_name ? `owner ${c.owner_name}` : "no owner"].filter(Boolean).join(" · ")}</SheetDescription>
            </SheetHeader>
            <div className="flex flex-wrap gap-2">
              {c.phone && <Button size="sm" variant="outline" asChild><a href={`tel:${c.phone}`}><Phone className="mr-1.5 h-4 w-4" />{c.phone}</a></Button>}
              <Button size="sm" onClick={() => setAction("call")}>Log call / visit</Button>
              <Button size="sm" variant="outline" onClick={() => setAction("reminder")}><AlarmClock className="mr-1.5 h-4 w-4" />Reminder</Button>
              <Button size="sm" variant="outline" onClick={() => setAction("deal")}><Kanban className="mr-1.5 h-4 w-4" />New deal</Button>
              <Button size="sm" variant="outline" onClick={() => navigate(`/customers/workspace?customer=${c.id}`)}><ShoppingCart className="mr-1.5 h-4 w-4" />New request</Button>
              <Button size="sm" variant="ghost" onClick={() => setAction("edit")}><Pencil className="mr-1.5 h-4 w-4" />Edit</Button>
              <ReportButton type="customer" kind="customer" id={c.id} variant="ghost" label="Report" />
            </div>
            {m.at_risk && <div className="rounded-md border border-amber-300 bg-amber-50 p-2 text-xs text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
              At risk: {m.risk_reasons.join("; ")}.</div>}
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              {[["Sales, 12 months", compact(Number(m.sales_12m) || 0), m.trend_pct != null ? `${m.trend_pct >= 0 ? "+" : ""}${m.trend_pct}% on last year` : "no prior year"],
                ["Margin, 12 months", m.margin_pct != null ? `${m.margin_pct}%` : "—", `lifetime ${compact(Number(m.lifetime) || 0)}`],
                ["Orders, 12 months", num(m.orders_12m), m.avg_gap_days ? `every ~${m.avg_gap_days} days` : "no regular cycle"],
                ["Next order", m.reorder_due_in == null ? "—" : m.reorder_due_in < 0 ? `${-m.reorder_due_in} days late` : m.reorder_due_in === 0 ? "today" : `in ${m.reorder_due_in} days`,
                  m.last_order ? `last ${fmtDate(m.last_order)}` : "never ordered"],
                ["Owes", naira(m.balance), Number(m.overdue) > 0 ? `${naira(m.overdue)} past due` : "nothing past due"],
                ["Credit limit", Number(c.credit_limit) ? naira(c.credit_limit) : "none set", m.credit_used_pct != null ? `${m.credit_used_pct}% used` : `terms ${c.payment_terms_days ?? 30} days`],
                ["Last contact", m.last_contact ? fmtDate(m.last_contact) : "never", m.next_reminder ? `next ${dt(m.next_reminder)}` : "no follow-up set"],
                ["Customer since", m.first_order ? fmtDate(m.first_order) : "—", `${num(m.orders)} orders in total`],
              ].map(([k, v, s]) => (
                <div key={k} className="rounded-md bg-muted/40 p-2"><div className="text-[11px] text-muted-foreground">{k}</div><div className="font-semibold">{v}</div><div className="text-[11px] text-muted-foreground">{s}</div></div>))}
            </div>
            <Tabs defaultValue="sales">
              <TabsList className="h-auto flex-wrap">
                <TabsTrigger value="sales">Sales</TabsTrigger><TabsTrigger value="products">What they buy ({p.products.length})</TabsTrigger>
                <TabsTrigger value="invoices">Invoices ({p.invoices.length})</TabsTrigger><TabsTrigger value="account">Account (ACE Books)</TabsTrigger>
                <TabsTrigger value="activity">Contact & deals</TabsTrigger>
              </TabsList>
              <TabsContent value="sales">
                {p.monthly.length === 0 ? <p className="py-6 text-center text-sm text-muted-foreground">No sales in the last two years.</p> : (
                  <ResponsiveContainer width="100%" height={240}>
                    <ComposedChart data={p.monthly.map((x: Dict) => ({ ...x, sales: Number(x.sales), orders: Number(x.orders) }))}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="period" fontSize={10} tickLine={false} axisLine={false} />
                      <YAxis yAxisId="v" fontSize={10} tickFormatter={compact} width={55} tickLine={false} axisLine={false} />
                      <YAxis yAxisId="o" orientation="right" fontSize={10} width={30} tickLine={false} axisLine={false} />
                      <Tooltip formatter={(v: number, n: string) => (n === "Orders" ? num(v) : naira(v))} />
                      <Bar yAxisId="v" dataKey="sales" name="Sales" fill="hsl(var(--primary))" radius={[3, 3, 0, 0]} />
                      <Line yAxisId="o" dataKey="orders" name="Orders" stroke="hsl(var(--success))" dot={{ r: 2 }} />
                    </ComposedChart>
                  </ResponsiveContainer>
                )}
              </TabsContent>
              <TabsContent value="products">
                <Table><TableHeader><TableRow><TableHead>Product</TableHead><TableHead className="text-right">Qty</TableHead><TableHead className="text-right">Avg price</TableHead>
                  <TableHead className="text-right">Sales</TableHead><TableHead>Last bought</TableHead></TableRow></TableHeader>
                  <TableBody>{p.products.map((x: Dict) => (
                    <TableRow key={x.sku}><TableCell><DrillLink to={{ type: "product", id: x.sku, label: x.sku }}>{x.name || x.sku}</DrillLink><div className="text-[11px] text-muted-foreground">{x.sku} · {x.orders} orders</div></TableCell>
                      <TableCell className="text-right">{num(x.qty)}</TableCell><TableCell className="text-right">{naira(x.avg_price)}</TableCell>
                      <TableCell className="text-right">{naira(x.sales)}</TableCell><TableCell className="text-xs">{fmtDate(x.last_bought)}</TableCell></TableRow>))}</TableBody></Table>
              </TabsContent>
              <TabsContent value="invoices">
                <Table><TableHeader><TableRow><TableHead>Invoice</TableHead><TableHead>Date</TableHead><TableHead className="text-right">Amount</TableHead><TableHead className="text-right">Still owed</TableHead></TableRow></TableHeader>
                  <TableBody>{p.invoices.map((iv: Dict) => (
                    <TableRow key={`${iv.source}-${iv.invoice_id}`}>
                      <TableCell>{iv.ace_invoice_id ? <DrillLink to={{ type: "invoice", id: iv.ace_invoice_id, label: iv.invoice_id }}>{iv.invoice_id}</DrillLink>
                        : <DrillLink to={{ type: "sageinvoice", id: String(iv.invoice_id), label: iv.invoice_id }}>{iv.invoice_id}</DrillLink>}
                        <div className="text-[10px] text-muted-foreground">{iv.source}</div></TableCell>
                      <TableCell className="text-xs">{fmtDate(iv.date)}{iv.due_date && <div className="text-[10px] text-muted-foreground">due {fmtDate(iv.due_date)}</div>}</TableCell>
                      <TableCell className="text-right">{naira(iv.amount)}</TableCell>
                      <TableCell className={`text-right ${Number(iv.balance) > 0 ? "text-red-600" : "text-muted-foreground"}`}>{Number(iv.balance) > 0 ? naira(iv.balance) : "paid"}</TableCell>
                    </TableRow>))}</TableBody></Table>
              </TabsContent>
              <TabsContent value="account"><RecordView t={{ type: "customer", id: String(c.id), label: c.name }} /></TabsContent>
              <TabsContent value="activity" className="space-y-3">
                {p.reminders.length > 0 && <div><div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">Follow-ups</div>
                  {p.reminders.map((r: Dict) => <div key={r.id} className="flex justify-between border-b py-1 text-xs"><span>{r.title ?? r.reminder_type}</span><span>{dt(r.due_at)}</span></div>)}</div>}
                <div><div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">Deals</div>
                  {p.deals.length === 0 ? <p className="text-xs text-muted-foreground">No deals.</p> : p.deals.map((x: Dict) => (
                    <div key={x.id} className="flex items-center justify-between border-b py-1 text-xs"><span>{x.company_name}{x.rep_name ? ` · ${x.rep_name}` : ""}</span>
                      <span className="flex items-center gap-2">{Number(x.expected_value) > 0 && naira(x.expected_value)}<StageChip stage={x.stage} /></span></div>))}</div>
                <div><div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">Contact history</div>
                  {p.activity.length === 0 ? <p className="text-xs text-muted-foreground">No calls or visits logged yet.</p> : (
                    <ol className="space-y-2">{p.activity.map((a: Dict) => (
                      <li key={a.id} className="border-l-2 pl-2 text-xs"><div className="flex justify-between"><span className="font-medium capitalize">{String(a.interaction_type).replace("_", " ")}</span>
                        <span className="text-muted-foreground">{dt(a.occurred_at)} · {a.by}</span></div><div>{a.summary}</div>
                        {(a.outcome || a.next_step) && <div className="text-muted-foreground">{[a.outcome, a.next_step && `next: ${a.next_step}`].filter(Boolean).join(" · ")}</div>}</li>))}</ol>)}</div>
              </TabsContent>
            </Tabs>
          </div>
        )}
        {c && <>
          <ActivitySheet target={action === "call" ? { customer_id: c.id, name: c.name } : null} onClose={() => { setAction(null); refresh(); }} />
          <ReminderSheet target={action === "reminder" ? { customer_id: c.id, name: c.name } : null} onClose={() => { setAction(null); refresh(); }} />
          <NewDealSheet key={`deal-${c.id}`} open={action === "deal"} defaults={{ company_name: c.name, customer_id: c.id, source: "existing_customer", contact_phone: c.phone ?? "", contact_person: c.contact_person ?? "" }}
            onClose={() => { setAction(null); refresh(); }} />
          <EditCustomer customer={action === "edit" ? c : null} onClose={() => { setAction(null); refresh(); }} />
        </>}
      </SheetContent>
    </Sheet>
  );
}

function EditCustomer({ customer, onClose }: { customer: Dict | null; onClose: () => void }) {
  const { roles } = useAuth();
  const canCredit = roles.some((r) => ["admin", "finance", "management"].includes(r));
  const [f, setF] = useState<Dict>({});
  const [key, setKey] = useState<number | null>(null);
  if (customer && key !== customer.id) {
    setKey(customer.id);
    setF({ phone: customer.phone ?? "", email: customer.email ?? "", contact_person: customer.contact_person ?? "", address: customer.address ?? "", city: customer.city ?? "",
           facility_type: customer.facility_type ?? "", payment_terms_days: String(customer.payment_terms_days ?? 30), credit_limit: String(customer.credit_limit ?? 0),
           owner: customer.owner ?? "", competing_supplier: customer.competing_supplier ?? "" });
  }
  const save = async () => {
    const payload: Dict = { ...f, payment_terms_days: Number(f.payment_terms_days) || 30 };
    if (canCredit) payload.credit_limit = Number(f.credit_limit) || 0; else delete payload.credit_limit;
    try { await api.crmHub.updateCustomer(customer!.id, payload); toast.success("Customer updated"); setKey(null); onClose(); } catch (e: any) { toast.error(e?.message); }
  };
  const field = (k: string, l: string, type = "text") => (
    <div className="space-y-1"><Label className="text-xs">{l}</Label><Input type={type} value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></div>);
  return (
    <DetailSheet open={!!customer} onOpenChange={(o) => { if (!o) { setKey(null); onClose(); } }} title={`Edit ${customer?.name ?? ""}`}
                 description="Contacts, owner and terms. The credit limit is checked by ACE Books when invoicing and can only be changed by Finance or management."
                 footer={<Button className="w-full" onClick={save}>Save</Button>}>
      <div className="grid grid-cols-2 gap-2">{field("contact_person", "Contact person")}{field("phone", "Phone")}{field("email", "Email")}{field("city", "City")}</div>
      {field("address", "Address")}
      <div className="grid grid-cols-2 gap-2">{field("facility_type", "Type")}{field("payment_terms_days", "Terms (days)", "number")}
        <div className="space-y-1"><Label className="text-xs">Credit limit (₦)</Label><Input type="number" disabled={!canCredit} value={f.credit_limit ?? ""} onChange={(e) => setF({ ...f, credit_limit: e.target.value })} /></div>
        {field("competing_supplier", "Also buys from")}</div>
      <div className="space-y-1"><Label className="text-xs">Owner (account manager)</Label><RepPick value={f.owner ?? ""} onChange={(v) => setF({ ...f, owner: v })} placeholder="Unassigned" /></div>
    </DetailSheet>
  );
}

export { Badge };
