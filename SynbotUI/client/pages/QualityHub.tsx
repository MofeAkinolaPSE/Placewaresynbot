/**
 * Inventory & Quality › Overview. One screen over stock (ACE Books), expiry, recalls, batch release,
 * deviations, audits and maintenance - every number from the live records (/quality/overview),
 * plus what is overdue and what is coming up (the same items as the Logistics Calendar).
 */
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CalendarClock, CalendarPlus, ClipboardCheck, Loader2, PackageX, ShieldAlert, ShieldCheck, Warehouse, Wrench } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/workspace/PageHeader";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { DrillProvider } from "@/components/books/lineage";
import { api } from "@/lib/api-client";
import { Dict, fmtDate, naira, num } from "@/lib/books-api";
import { QualityActionsProvider, useIsQa, useQualityActions } from "@/components/quality/actions";
import { Tone } from "@/components/quality/panels";

export const KIND_TONE: Record<string, ["red" | "amber" | "sky" | "green" | "slate" | "violet", string]> = {
  recall: ["red", "Recall"], stock_order: ["sky", "Delivery"], batch: ["violet", "Incoming batch"], audit: ["amber", "Audit"],
  maintenance: ["slate", "Maintenance"], deviation: ["red", "Deviation"], capa: ["amber", "CAPA"], activity: ["slate", "Activity"],
  expiry: ["amber", "Expiry"], event: ["sky", "Event"],
};

export default function QualityHub() {
  return (
    <DrillProvider>
      <QualityActionsProvider>
        <Hub />
      </QualityActionsProvider>
    </DrillProvider>
  );
}

function Hub() {
  const navigate = useNavigate();
  const qa = useQualityActions();
  const isQa = useIsQa();
  const { data: d, isLoading } = useQuery({ queryKey: ["quality", "overview"], queryFn: () => api.quality.overview(), refetchInterval: 120000 });
  if (isLoading || !d) return <div className="flex justify-center py-16"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>;
  const e = d.expiry ?? {};
  const expiredOrCritical = (e.expired?.products ?? 0) + (e.critical?.products ?? 0);

  return (
    <div className="space-y-5">
      <PageHeader icon={Warehouse} title="Inventory & Quality" subtitle="Stock, quality control and compliance - one view, from ACE Books and the QMS records"
        actions={
          <div className="flex flex-wrap gap-2">
            {isQa && <Button size="sm" variant="outline" onClick={() => qa.open("recall")}><PackageX className="mr-1.5 h-4 w-4" />Recall</Button>}
            <Button size="sm" variant="outline" onClick={() => qa.open("deviation")}><ShieldAlert className="mr-1.5 h-4 w-4" />Deviation</Button>
            <Button size="sm" variant="outline" onClick={() => qa.open("audit")}><CalendarPlus className="mr-1.5 h-4 w-4" />Audit</Button>
            <Button size="sm" variant="outline" onClick={() => qa.open("maintenance")}><Wrench className="mr-1.5 h-4 w-4" />Maintenance</Button>
            <Button size="sm" onClick={() => qa.open("batch")}><ClipboardCheck className="mr-1.5 h-4 w-4" />Incoming batch</Button>
          </div>
        } />

      <KpiStrip items={[
        { label: "Stock at cost", value: naira(d.stock.value), sub: `${num(d.stock.items_in_stock)} items · ${num(d.stock.units)} units`, onClick: () => navigate("/inventory") },
        { label: "Held from sale", value: naira(d.stock.held_value), tone: d.stock.held_lots ? "warning" : "success",
          sub: `${num(d.stock.held_lots)} lots quarantined or recalled`, onClick: () => navigate("/quality-control?tab=expiry") },
        { label: "Expired or expiring ≤30 days", value: `${expiredOrCritical} product${expiredOrCritical === 1 ? "" : "s"}`, tone: e.expired ? "danger" : expiredOrCritical ? "warning" : "success",
          sub: `${naira((e.expired?.value ?? 0) + (e.critical?.value ?? 0))} at cost · expired lots cannot be sold`, onClick: () => navigate("/quality-control?tab=expiry") },
        { label: "Won't sell before expiry", value: naira(d.expiry_unsellable_value), tone: d.expiry_unsellable_value > 0 ? "warning" : "success",
          sub: "at current sales rates", onClick: () => navigate("/quality-control?tab=expiry") },
      ]} />
      <KpiStrip items={[
        { label: "Open recalls", value: d.recalls.open, tone: d.recalls.open ? "danger" : "success",
          sub: `${num(d.recalls.customers_to_contact)} customers to contact · ${num(d.recalls.units_frozen)} units frozen`, onClick: () => navigate("/quality-control?tab=recalls") },
        { label: "Open deviations", value: d.deviations.open, tone: d.deviations.overdue || d.deviations.capa_overdue ? "danger" : d.deviations.open ? "warning" : "success",
          sub: `${d.deviations.overdue} past close date · ${d.deviations.capa_overdue} CAPA overdue`, onClick: () => navigate("/compliance?tab=deviations") },
        { label: "Audits", value: `${d.audits.due_30} due`, tone: d.audits.overdue ? "danger" : "default",
          sub: `next 30 days · ${d.audits.overdue} overdue · ${d.audits.done_this_year} done this year`, onClick: () => navigate("/compliance?tab=audits") },
        { label: "Maintenance", value: `${d.maintenance.due_30} due`, tone: d.maintenance.overdue ? "danger" : "default",
          sub: `next 30 days · ${d.maintenance.overdue} overdue · ${d.maintenance.equipment} machines`, onClick: () => navigate("/compliance?tab=maintenance") },
      ]} />
      <div className="grid gap-3 md:grid-cols-2">
        <Card className="cursor-pointer" onClick={() => navigate("/quality-control?tab=release")}>
          <CardContent className="flex items-center justify-between p-4">
            <div><div className="text-xs text-muted-foreground">Batches awaiting QC release</div>
              <div className="text-xl font-bold">{d.batches.pending + d.batches.received_unreleased}</div>
              <div className="text-[11px] text-muted-foreground">{d.batches.pending} registered · {d.batches.received_unreleased} received on a bill, not yet checked · {d.batches.late} late</div></div>
            <ClipboardCheck className="h-6 w-6 text-muted-foreground" />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center justify-between p-4">
            <div><div className="text-xs text-muted-foreground">Compliance score</div>
              <div className={`text-xl font-bold ${d.compliance_score >= 90 ? "text-emerald-600" : d.compliance_score >= 70 ? "text-amber-600" : "text-red-600"}`}>{d.compliance_score}/100</div>
              <div className="text-[11px] text-muted-foreground">100 less points for overdue audits, open & overdue deviations, overdue maintenance and open recalls</div></div>
            <ShieldCheck className="h-6 w-6 text-muted-foreground" />
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <ItemList title="Needs attention now" icon={AlertTriangle} items={d.attention} empty="Nothing is overdue." />
        <ItemList title="Next 14 days" icon={CalendarClock} items={d.upcoming} empty="Nothing scheduled in the next two weeks."
          action={<Button size="sm" variant="outline" onClick={() => navigate("/calendar")}>Calendar</Button>} />
      </div>
    </div>
  );
}

function ItemList({ title, icon: Icon, items, empty, action }: { title: string; icon: any; items: Dict[]; empty: string; action?: React.ReactNode }) {
  const navigate = useNavigate();
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="flex items-center gap-2 text-base"><Icon className="h-4 w-4" />{title}</CardTitle>{action}
      </CardHeader>
      <CardContent className="space-y-1.5">
        {items.length === 0 && <p className="text-sm text-muted-foreground">{empty}</p>}
        {items.map((i) => (
          <button key={`${i.kind}-${i.id}`} className="flex w-full items-center justify-between gap-3 rounded-md border-b px-1 pb-1.5 text-left text-sm last:border-0 hover:bg-muted/40"
                  onClick={() => i.link && navigate(i.link)}>
            <div className="min-w-0">
              <div className="flex items-center gap-2"><Tone tone={KIND_TONE[i.kind]?.[0] ?? "slate"}>{KIND_TONE[i.kind]?.[1] ?? i.kind}</Tone><span className="truncate font-medium">{i.title}</span></div>
              <div className="truncate text-[11px] text-muted-foreground">{i.subtitle}</div>
            </div>
            <div className={`shrink-0 text-right text-xs ${i.overdue ? "text-red-600" : "text-muted-foreground"}`}>{i.overdue ? `was due ${fmtDate(i.date)}` : fmtDate(i.date)}</div>
          </button>
        ))}
      </CardContent>
    </Card>
  );
}
