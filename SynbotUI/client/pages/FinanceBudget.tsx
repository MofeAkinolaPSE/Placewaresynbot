import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Loader2,
  PlusCircle,
  Target,
  Trash2,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { motion } from "framer-motion";
import { motionVariants } from "@/lib/motion";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api-client";
import { PageHeader } from "@/components/workspace/PageHeader";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { DetailSheet } from "@/components/workspace/DetailSheet";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const fmt = (n: number) =>
  typeof n === "number"
    ? `₦${n.toLocaleString("en-NG", { minimumFractionDigits: 2 })}`
    : "—";

function currentPeriod() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function VariancePill({ variance, variancePct }: { variance: number; variancePct: number | null }) {
  if (variance === 0) return <span className="text-xs text-muted-foreground">On target</span>;
  const over = variance > 0;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-semibold ${
        over ? "bg-red-500/15 text-red-600 dark:text-red-400" : "bg-green-500/15 text-green-600 dark:text-green-400"
      }`}
    >
      {over ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
      {over ? "+" : ""}
      {fmt(variance)}
      {variancePct !== null && ` (${variancePct > 0 ? "+" : ""}${variancePct}%)`}
    </span>
  );
}

// ---------------------------------------------------------------------------
// FinanceBudget page
// ---------------------------------------------------------------------------
export default function FinanceBudget() {
  const { toast } = useToast();
  const qc = useQueryClient();

  const [period, setPeriod] = useState(currentPeriod());
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState({
    department: "",
    category: "general",
    budgeted_amount: "",
    note: "",
  });
  // Delete previously fired immediately with zero confirmation — a
  // one-click data-loss risk found during the Finance retrofit research.
  // Fixed with a short confirmation Dialog, matching this app's existing
  // reject-with-note / void-with-reason Dialog convention (Ch.5).
  const [deleteTarget, setDeleteTarget] = useState<any | null>(null);

  // --- queries ---
  const varianceQ = useQuery({
    queryKey: ["finance-budget-variance", period],
    queryFn: () => api.finance.budgetVariance(period || undefined),
    refetchInterval: 300_000,
  });

  const targetsQ = useQuery({
    queryKey: ["finance-budget-targets", period],
    queryFn: () => api.finance.listBudgetTargets(period || undefined),
  });

  const variance = (varianceQ.data as any) ?? {};
  const rows: any[] = variance.rows ?? [];
  const summary = variance.summary ?? {};
  const targets: any[] = (targetsQ.data as any)?.data ?? [];

  // --- mutations ---
  const upsertMut = useMutation({
    mutationFn: (p: any) => api.finance.upsertBudgetTarget(p),
    onSuccess: () => {
      toast({ title: "Budget target saved" });
      void qc.invalidateQueries({ queryKey: ["finance-budget-variance"] });
      void qc.invalidateQueries({ queryKey: ["finance-budget-targets"] });
      setCreateOpen(false);
      setForm({ department: "", category: "general", budgeted_amount: "", note: "" });
    },
    onError: (err: any) =>
      toast({ title: "Failed to save target", description: err.message, variant: "destructive" }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.finance.deleteBudgetTarget(id),
    onSuccess: () => {
      toast({ title: "Budget target deleted" });
      setDeleteTarget(null);
      void qc.invalidateQueries({ queryKey: ["finance-budget-variance"] });
      void qc.invalidateQueries({ queryKey: ["finance-budget-targets"] });
    },
    onError: (err: any) =>
      toast({ title: "Delete failed", description: err.message, variant: "destructive" }),
  });

  function handleUpsert() {
    if (!form.department || !form.budgeted_amount) {
      toast({ title: "Department and amount are required", variant: "destructive" });
      return;
    }
    if (!/^\d{4}-\d{2}$/.test(period)) {
      toast({ title: "Period must be YYYY-MM format", variant: "destructive" });
      return;
    }
    upsertMut.mutate({
      department: form.department.trim(),
      category: form.category.trim() || "general",
      period,
      budgeted_amount: parseFloat(form.budgeted_amount),
      note: form.note.trim() || undefined,
    });
  }

  const overBudgetCount = rows.filter((r) => r.status === "over_budget").length;

  return (
    <motion.div {...motionVariants.cardEnter} className="space-y-6">
      <PageHeader
        icon={Target}
        title="Budget vs. Actual"
        subtitle="Compare departmental spending against approved budgets. Detect overspend early."
        actions={
          <>
            <Input
              className="w-36"
              placeholder="YYYY-MM"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
            />
            <Button size="sm" onClick={() => void varianceQ.refetch()} disabled={varianceQ.isFetching}>
              {varianceQ.isFetching ? <Loader2 className="w-4 h-4 animate-spin" /> : "Refresh"}
            </Button>
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <PlusCircle className="w-4 h-4 mr-2" />
              Set Budget
            </Button>
          </>
        }
      />

      {/* Alert if over budget — prose content, kept as its own banner rather
          than forced into a KpiStrip tile. */}
      {overBudgetCount > 0 && (
        <Card className="border-red-500/40 bg-red-500/5">
          <CardContent className="py-3 flex items-center gap-2 text-sm text-red-700 dark:text-red-400">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span>
              <strong>{overBudgetCount}</strong> department
              {overBudgetCount > 1 ? "s are" : " is"} over budget for <strong>{period}</strong>.
            </span>
          </CardContent>
        </Card>
      )}

      {/* Page-level KpiStrip — spans both tabs below, mirrors NafdacTab's
          per-sub-section KpiStrip pattern but scoped to the whole page here
          since this data isn't specific to either tab. */}
      <KpiStrip
        items={[
          { label: "Total Budget", value: fmt(summary.total_budgeted ?? 0) },
          { label: "Total Actual Spend", value: fmt(summary.total_actual ?? 0) },
          {
            label: "Overall Variance",
            value: `${(summary.total_variance ?? 0) > 0 ? "+" : ""}${fmt(summary.total_variance ?? 0)}`,
            tone: (summary.total_variance ?? 0) > 0 ? "danger" : (summary.total_variance ?? 0) < 0 ? "success" : "default",
          },
          { label: "Over Budget Depts", value: summary.over_budget_departments ?? 0, tone: overBudgetCount > 0 ? "danger" : "default" },
        ]}
      />

      <Tabs defaultValue="variance">
        <TabsList className="mb-4">
          <TabsTrigger value="variance">Variance Report</TabsTrigger>
          <TabsTrigger value="targets">
            Budget Targets
            <Badge variant="secondary" className="ml-1 h-4 text-xs px-1">
              {targets.length}
            </Badge>
          </TabsTrigger>
        </TabsList>

        {/* ================================================================ */}
        {/* TAB: VARIANCE REPORT                                              */}
        {/* ================================================================ */}
        <TabsContent value="variance">
          {varianceQ.isLoading ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
          ) : rows.length === 0 ? (
            <p className="text-center text-muted-foreground py-16">
              No GL data or budget targets for <strong>{variance.period ?? period}</strong>.
              <br />
              Upload a GL CSV via Sage Import and set department budgets above.
            </p>
          ) : (
            <>
            {variance.period && variance.requested_period && variance.period !== variance.requested_period && (
              <p className="text-xs text-muted-foreground mb-2">
                No GL activity for {variance.requested_period} yet — showing the latest month with data: <strong>{variance.period}</strong>.
              </p>
            )}
            <div className="rounded-md border overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Department</TableHead>
                    <TableHead className="text-right">Budgeted</TableHead>
                    <TableHead className="text-right">Actual Spend</TableHead>
                    <TableHead>Variance</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Utilisation</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row: any) => {
                    const util =
                      row.budgeted > 0
                        ? Math.min(Math.round((row.actual / row.budgeted) * 100), 999)
                        : null;
                    return (
                      <TableRow key={row.department}>
                        <TableCell className="font-medium">{row.department}</TableCell>
                        <TableCell className="text-right font-mono">
                          {row.budgeted > 0 ? fmt(row.budgeted) : <span className="text-muted-foreground italic">No budget</span>}
                        </TableCell>
                        <TableCell className="text-right font-mono">{fmt(row.actual)}</TableCell>
                        <TableCell>
                          <VariancePill variance={row.variance} variancePct={row.variance_pct} />
                        </TableCell>
                        <TableCell>
                          <span
                            className={`rounded px-2 py-0.5 text-xs font-semibold ${
                              row.status === "over_budget"
                                ? "bg-red-500/15 text-red-600 dark:text-red-400"
                                : row.status === "no_budget"
                                ? "bg-muted text-muted-foreground"
                                : row.status === "under_budget"
                                ? "bg-green-500/15 text-green-600 dark:text-green-400"
                                : "bg-blue-500/15 text-blue-600 dark:text-blue-400"
                            }`}
                          >
                            {row.status.replace("_", " ")}
                          </span>
                        </TableCell>
                        <TableCell className="text-right">
                          {util !== null ? (
                            <div className="flex items-center justify-end gap-2">
                              <div className="w-20 h-2 rounded-full bg-muted overflow-hidden">
                                <div
                                  className={`h-full rounded-full ${
                                    util > 100 ? "bg-red-500" : util > 80 ? "bg-yellow-500" : "bg-green-500"
                                  }`}
                                  style={{ width: `${Math.min(util, 100)}%` }}
                                />
                              </div>
                              <span className="text-xs font-mono">{util}%</span>
                            </div>
                          ) : (
                            <span className="text-muted-foreground text-xs">—</span>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
            </>
          )}
          {variance.gl_rows_processed !== undefined && (
            <p className="text-xs text-muted-foreground mt-2">
              Based on {variance.gl_rows_processed} expense account lines for {variance.period ?? period}.
            </p>
          )}
        </TabsContent>

        {/* ================================================================ */}
        {/* TAB: BUDGET TARGETS                                               */}
        {/* ================================================================ */}
        <TabsContent value="targets">
          {targetsQ.isLoading ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
          ) : targets.length === 0 ? (
            <p className="text-center text-muted-foreground py-16">
              No budget targets set for <strong>{period}</strong>.
              <br />
              Click <strong>Set Budget</strong> to add department targets.
            </p>
          ) : (
            <div className="rounded-md border overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Department</TableHead>
                    <TableHead>Category</TableHead>
                    <TableHead>Period</TableHead>
                    <TableHead className="text-right">Budgeted Amount</TableHead>
                    <TableHead>Note</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {targets.map((t: any) => (
                    <TableRow key={t.id}>
                      <TableCell className="font-medium">{t.department}</TableCell>
                      <TableCell className="text-xs">{t.category}</TableCell>
                      <TableCell className="text-xs font-mono">{t.period}</TableCell>
                      <TableCell className="text-right font-mono">{fmt(parseFloat(t.budgeted_amount))}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">{t.note || "—"}</TableCell>
                      <TableCell>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 text-xs text-red-600 dark:text-red-300"
                          onClick={() => setDeleteTarget(t)}
                        >
                          <Trash2 className="w-3 h-3" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* Set Department Budget — ephemeral create task, DetailSheet per
          Ch.5.2 (same move as CAPA/Temperature/NAFDAC/FinanceAR's Alert
          Rules/Vendor Payments' create form). */}
      <DetailSheet
        open={createOpen}
        onOpenChange={setCreateOpen}
        title="Set Department Budget"
        description={`Set a budget target for a department for period ${period}. Existing entries will be updated.`}
        icon={Target}
        footer={
          <Button className="w-full" onClick={handleUpsert} disabled={upsertMut.isPending}>
            {upsertMut.isPending && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
            Save Target
          </Button>
        }
      >
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">
              Department *
            </label>
            <Input
              placeholder="e.g. Finance, Operations, Sales"
              value={form.department}
              onChange={(e) => setForm((f) => ({ ...f, department: e.target.value }))}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">
              Category
            </label>
            <Input
              placeholder="e.g. general, payroll, opex, marketing"
              value={form.category}
              onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">
              Budgeted Amount (₦) *
            </label>
            <Input
              type="number"
              placeholder="e.g. 5000000"
              value={form.budgeted_amount}
              onChange={(e) => setForm((f) => ({ ...f, budgeted_amount: e.target.value }))}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">
              Note (optional)
            </label>
            <Input
              placeholder="e.g. Approved by CEO Apr 2026"
              value={form.note}
              onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))}
            />
          </div>
        </div>
      </DetailSheet>

      {/* Delete confirmation — new, replaces the previous zero-confirmation
          immediate-fire delete button (a real data-loss risk found during
          the Finance retrofit research). Short single-target confirmation,
          same Dialog convention as reject-with-note/void-with-reason (Ch.5). */}
      <Dialog open={!!deleteTarget} onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Budget Target</DialogTitle>
            <DialogDescription>
              {deleteTarget && (
                <>
                  Delete the <strong>{deleteTarget.department}</strong> budget target for{" "}
                  <strong>{deleteTarget.period}</strong> ({fmt(parseFloat(deleteTarget.budgeted_amount))})? This
                  cannot be undone.
                </>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteTarget && deleteMut.mutate(deleteTarget.id)}
              disabled={deleteMut.isPending}
            >
              {deleteMut.isPending && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </motion.div>
  );
}
