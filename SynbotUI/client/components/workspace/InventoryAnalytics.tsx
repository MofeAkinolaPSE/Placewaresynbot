import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  AlertTriangle, CalendarClock, PackageX, TrendingDown, Info,
  RotateCcw, Archive, ChevronRight, Loader2, X,
} from "lucide-react";

const naira = (n: number) =>
  `₦${Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

const num = (n: number) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 0 });

type Bucket = { value: number; units: number; skus: number };

// Expiry buckets, worst first — the order a distributor actually triages in.
const BUCKETS: { key: string; label: string; tone: string }[] = [
  { key: "expired", label: "Already expired", tone: "text-destructive" },
  { key: "within_30_days", label: "Expires ≤ 30 days", tone: "text-destructive" },
  { key: "within_90_days", label: "Expires ≤ 90 days", tone: "text-amber-600 dark:text-amber-400" },
  { key: "beyond_90_days", label: "Beyond 90 days", tone: "text-foreground" },
  { key: "no_expiry_date", label: "No expiry recorded", tone: "text-muted-foreground" },
];

type Tab = "expiry" | "dead" | "reorder" | "requests";

// Where a reorder actually is, once raised. Previously a filed request had no
// visible home at all -- 774 of them sat at "recommended" with nothing in the
// app able to show or advance them.
type RequestStage = {
  label: string;
  next?: "approve" | "receive";
  variant: "destructive" | "secondary" | "outline";
};

const REQUEST_FLOW: Record<string, RequestStage> = {
  recommended: { label: "awaiting approval", next: "approve", variant: "secondary" },
  approved: { label: "approved — awaiting delivery", next: "receive", variant: "outline" },
  ordered: { label: "ordered — awaiting delivery", next: "receive", variant: "outline" },
  received: { label: "received", variant: "outline" },
  cancelled: { label: "cancelled", variant: "outline" },
};

export function InventoryAnalytics({
  data,
  onSelect,
  onReorder,
  onWriteOff,
  busySku,
  requests,
  onAdvanceRequest,
  onCancelRequest,
  busyRequestId,
}: {
  data: any;
  onSelect?: (family: string, companyId: string | null) => void;
  onReorder?: (row: any) => void;
  onWriteOff?: (row: any) => void;
  busySku?: string | null;
  requests?: any[];
  onAdvanceRequest?: (row: any, action: "approve" | "receive") => void;
  onCancelRequest?: (row: any) => void;
  busyRequestId?: string | null;
}) {
  const [tab, setTab] = useState<Tab>("expiry");
  const [cancelConfirmId, setCancelConfirmId] = useState<string | null>(null);
  if (!data) return null;

  const buckets: Record<string, Bucket> = data.expiry?.buckets ?? {};
  const atRisk: any[] = data.expiry?.at_risk ?? [];
  const dead: any[] = data.dead_stock ?? [];
  const reorder: any[] = data.reorder_candidates ?? [];
  const totals = data.totals ?? {};
  const demand = data.demand ?? {};

  const atRiskValue =
    (buckets.expired?.value ?? 0) +
    (buckets.within_30_days?.value ?? 0) +
    (buckets.within_90_days?.value ?? 0);

  const openRequests = (requests ?? []).filter(
    (r) => !["received", "cancelled"].includes(String(r.status || "").toLowerCase()),
  );

  const TABS: { key: Tab; label: string; count: number }[] = [
    { key: "expiry", label: "Expiry exposure", count: atRisk.length },
    { key: "dead", label: "Dead stock", count: dead.length },
    { key: "reorder", label: "Needs reorder", count: reorder.length },
    { key: "requests", label: "Reorders in flight", count: openRequests.length },
  ];

  return (
    <Card>
      <CardContent className="p-4 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-sm font-semibold">Position &amp; Risk</p>
            <p className="text-xs text-muted-foreground">
              {num(totals.sku_count)} SKUs in stock · {naira(totals.total_value)} at cost ·{" "}
              {totals.top5_value_share_pct}% of value in the top 5
            </p>
          </div>
          {atRiskValue > 0 && (
            <Badge variant="destructive" className="gap-1">
              <AlertTriangle className="h-3 w-3" />
              {naira(atRiskValue)} at expiry risk
            </Badge>
          )}
        </div>

        {/* Expiry exposure bar — where the money actually sits */}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
          {BUCKETS.map((b) => {
            const v = buckets[b.key] ?? { value: 0, units: 0, skus: 0 };
            return (
              <div key={b.key} className="rounded-md border p-2">
                <p className="text-[11px] text-muted-foreground leading-tight">{b.label}</p>
                <p className={`text-sm font-semibold tabular-nums mt-0.5 ${b.tone}`}>
                  {naira(v.value)}
                </p>
                <p className="text-[11px] text-muted-foreground">
                  {v.skus} SKU{v.skus === 1 ? "" : "s"} · {num(v.units)} units
                </p>
              </div>
            );
          })}
        </div>

        <div className="flex gap-1 border-b">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={`px-3 py-1.5 text-xs font-medium border-b-2 -mb-px transition-colors ${
                tab === t.key
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {t.label} ({t.count})
            </button>
          ))}
        </div>

        {tab === "expiry" && (
          <List
            rows={atRisk}
            empty="Nothing expiring within 90 days."
            icon={CalendarClock}
            onSelect={onSelect}
            onReorder={onReorder}
            onWriteOff={onWriteOff}
            busySku={busySku}
            render={(r) => ({
              title: r.sku,
              subtitle: `${num(r.units)} units · exp ${r.expiry_date}`,
              right: naira(r.value),
              badge:
                r.days_to_expiry < 0
                  ? { text: `expired ${Math.abs(r.days_to_expiry)}d ago`, variant: "destructive" as const }
                  : { text: `${r.days_to_expiry}d left`, variant: r.days_to_expiry <= 30 ? ("destructive" as const) : ("secondary" as const) },
            })}
          />
        )}

        {tab === "dead" && (
          <>
            <p className="text-[11px] text-muted-foreground flex items-start gap-1.5">
              <Info className="h-3 w-3 mt-0.5 shrink-0" />
              In stock but never sold in the full Sage history — capital sitting still.
            </p>
            <List
              rows={dead}
              empty="No dead stock — every item in stock has sold before."
              icon={PackageX}
              onSelect={onSelect}
              onWriteOff={onWriteOff}
              busySku={busySku}
              render={(r) => ({
                title: r.sku,
                subtitle: `${num(r.units)} units${r.expiry_date ? ` · exp ${r.expiry_date}` : ""}`,
                right: naira(r.value),
              })}
            />
          </>
        )}

        {tab === "reorder" && (
          <List
            rows={reorder}
            empty="Nothing flagged for reorder."
            icon={TrendingDown}
            onSelect={onSelect}
            onReorder={onReorder}
            busySku={busySku}
            render={(r) => ({
              title: r.sku,
              subtitle:
                r.coverage_days != null
                  ? `${num(r.current_stock)} units · ~${r.coverage_days}d cover · out ${r.predicted_stockout_date}`
                  : `${num(r.current_stock)} units · no recent sales to project from`,
              right: `order ${num(r.recommended_reorder_qty)}`,
              badge: { text: r.risk_tier, variant: r.risk_tier === "critical" ? ("destructive" as const) : ("secondary" as const) },
            })}
          />
        )}

        {tab === "requests" && (
          <>
            <p className="text-[11px] text-muted-foreground flex items-start gap-1.5">
              <Info className="h-3 w-3 mt-0.5 shrink-0" />
              Reorders you've raised. Marking one received adds the units back
              into stock.
            </p>
            {openRequests.length === 0 ? (
              <p className="text-xs text-muted-foreground rounded-md border border-dashed p-3 text-center">
                No reorders in flight.
              </p>
            ) : (
              <div className="space-y-1.5 max-h-72 overflow-auto">
                {openRequests.map((r) => {
                  const flow: RequestStage =
                    REQUEST_FLOW[String(r.status || "").toLowerCase()] ?? {
                      label: String(r.status ?? "unknown"),
                      variant: "outline",
                    };
                  const busy = busyRequestId === r.id;
                  const confirmingCancel = cancelConfirmId === r.id;

                  if (confirmingCancel) {
                    return (
                      <div
                        key={r.id}
                        className="rounded-md border border-destructive/50 bg-destructive/5 p-2 text-xs space-y-2"
                      >
                        <p>
                          Cancel the reorder for <span className="font-mono">{r.sku}</span> (
                          {num(r.requested_qty)} units)? It stays in history as cancelled — nothing
                          is deleted.
                        </p>
                        <div className="flex gap-2">
                          <Button
                            size="sm"
                            variant="destructive"
                            className="h-6 px-2 text-[11px]"
                            disabled={busy}
                            onClick={() => {
                              setCancelConfirmId(null);
                              onCancelRequest?.(r);
                            }}
                          >
                            {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : "Confirm cancel"}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-6 px-2 text-[11px]"
                            onClick={() => setCancelConfirmId(null)}
                          >
                            Keep it
                          </Button>
                        </div>
                      </div>
                    );
                  }

                  return (
                    <div key={r.id} className="flex items-center gap-2 rounded-md border p-2 text-xs">
                      <RotateCcw className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                      <div className="min-w-0 flex-1">
                        <p className="font-medium truncate">{r.sku}</p>
                        <p className="text-muted-foreground truncate">
                          {num(r.requested_qty)} units requested
                          {r.created_at ? ` · ${String(r.created_at).slice(0, 10)}` : ""}
                        </p>
                      </div>
                      <Badge variant={flow.variant} className="text-[10px] shrink-0">
                        {flow.label}
                      </Badge>
                      {flow.next && onAdvanceRequest && (
                        <Button
                          size="sm"
                          variant={flow.next === "receive" ? "default" : "outline"}
                          className="h-6 px-2 text-[11px] shrink-0"
                          disabled={busy}
                          onClick={() =>
                            onAdvanceRequest(r, flow.next!)
                          }
                        >
                          {busy ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : flow.next === "approve" ? (
                            "Approve"
                          ) : (
                            "Mark received"
                          )}
                        </Button>
                      )}
                      {onCancelRequest && (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-6 w-6 p-0 text-muted-foreground hover:text-destructive shrink-0"
                          title="Cancel this reorder"
                          disabled={busy}
                          onClick={() => setCancelConfirmId(r.id)}
                        >
                          <X className="h-3 w-3" />
                        </Button>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}

        {/* Stated plainly so nobody reads a forecast into data that can't support one. */}
        {demand.skus_with_dated_demand === 0 && (
          <p className="text-[11px] text-muted-foreground border-t pt-2 flex items-start gap-1.5">
            <Info className="h-3 w-3 mt-0.5 shrink-0" />
            No dated sales yet, so demand rates and stockout dates are not being
            projected. These build up automatically as invoices are dispatched;
            historic Sage sales carry no transaction date, so they inform dead
            stock only.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function List({
  rows,
  empty,
  icon: Icon,
  render,
  onSelect,
  onReorder,
  onWriteOff,
  busySku,
}: {
  rows: any[];
  empty: string;
  icon: any;
  render: (r: any) => {
    title: string;
    subtitle: string;
    right: string;
    badge?: { text: string; variant: "destructive" | "secondary" | "outline" };
  };
  onSelect?: (family: string, companyId: string | null) => void;
  onReorder?: (row: any) => void;
  onWriteOff?: (row: any) => void;
  busySku?: string | null;
}) {
  // Two-step confirm: writing stock off is destructive, so it never fires on
  // a single click.
  const [confirming, setConfirming] = useState<string | null>(null);

  if (!rows.length) {
    return (
      <p className="text-xs text-muted-foreground rounded-md border border-dashed p-3 text-center">
        {empty}
      </p>
    );
  }

  return (
    <div className="space-y-1.5 max-h-72 overflow-auto">
      {rows.map((r, i) => {
        const v = render(r);
        const key = `${r.sku ?? v.title}-${i}`;
        const busy = busySku === r.sku;
        const isExpired = typeof r.days_to_expiry === "number" && r.days_to_expiry < 0;
        const canOpen = Boolean(onSelect && r.family);

        if (confirming === key) {
          return (
            <div
              key={key}
              className="rounded-md border border-destructive/50 bg-destructive/5 p-2 text-xs space-y-2"
            >
              <p>
                Write off <span className="font-semibold">{num(r.units ?? r.current_stock)}</span> units
                of <span className="font-mono">{r.sku}</span>
                {isExpired ? " (expired)" : ""}? This removes them from live stock and
                records the write-off permanently.
              </p>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="destructive"
                  className="h-6 px-2 text-[11px]"
                  disabled={busy}
                  onClick={() => {
                    setConfirming(null);
                    onWriteOff?.(r);
                  }}
                >
                  {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : "Confirm write-off"}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 px-2 text-[11px]"
                  onClick={() => setConfirming(null)}
                >
                  Cancel
                </Button>
              </div>
            </div>
          );
        }

        return (
          <div
            key={key}
            role={canOpen ? "button" : undefined}
            tabIndex={canOpen ? 0 : undefined}
            onClick={canOpen ? () => onSelect!(r.family, r.company_id ?? null) : undefined}
            onKeyDown={
              canOpen
                ? (e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelect!(r.family, r.company_id ?? null);
                    }
                  }
                : undefined
            }
            className={`flex items-center gap-2 rounded-md border p-2 text-xs ${
              canOpen ? "cursor-pointer hover:border-primary hover:bg-accent/10 transition-colors" : ""
            }`}
          >
            <Icon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            <div className="min-w-0 flex-1">
              <p className="font-medium truncate">{v.title}</p>
              <p className="text-muted-foreground truncate">{v.subtitle}</p>
            </div>
            {v.badge && (
              <Badge variant={v.badge.variant} className="text-[10px] shrink-0">
                {v.badge.text}
              </Badge>
            )}
            <span className="font-semibold tabular-nums shrink-0">{v.right}</span>

            <div className="flex items-center gap-0.5 shrink-0" onClick={(e) => e.stopPropagation()}>
              {onReorder && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 w-6 p-0"
                  title="Request reorder"
                  disabled={busy}
                  onClick={() => onReorder(r)}
                >
                  {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <RotateCcw className="h-3 w-3" />}
                </Button>
              )}
              {onWriteOff && (r.units ?? 0) > 0 && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 w-6 p-0 text-destructive hover:text-destructive"
                  title={isExpired ? "Write off expired stock" : "Write off stock"}
                  disabled={busy}
                  onClick={() => setConfirming(key)}
                >
                  <Archive className="h-3 w-3" />
                </Button>
              )}
              {canOpen && <ChevronRight className="h-3 w-3 text-muted-foreground" />}
            </div>
          </div>
        );
      })}
    </div>
  );
}
