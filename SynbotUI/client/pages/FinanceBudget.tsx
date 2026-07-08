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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
      {/* Header */}
      <div className="flex flex-col gap-1 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Budget vs. Actual</h1>
          <p className="text-sm text-muted-foreground">
            Compare departmental spending against approved budgets. Detect overspend early.
          </p>
        </div>
        <div className="flex gap-2">
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
        </div>
      </div>

      {/* Alert if over budget */}
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

      {/* Summary KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-xs text-muted-foreground flex items-center gap-1">
              <Target className="w-3 h-3" /> Total Budget
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-lg font-bold">{fmt(summary.total_budgeted ?? 0)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-xs text-muted-foreground">Total Actual Spend</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-lg font-bold">{fmt(summary.total_actual ?? 0)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-xs text-muted-foreground">Overall Variance</CardTitle>
          </CardHeader>
          <CardContent>
            <p
              className={`text-lg font-bold ${
                (summary.total_variance ?? 0) > 0
                  ? "text-red-500"
                  : (summary.total_variance ?? 0) < 0
                  ? "text-green-500"
                  : ""
              }`}
            >
              {(summary.total_variance ?? 0) > 0 ? "+" : ""}
              {fmt(summary.total_variance ?? 0)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-xs text-muted-foreground flex items-center gap-1">
              <TrendingUp className="w-3 h-3 text-red-500" /> Over Budget Depts
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className={`text-2xl font-bold ${overBudgetCount > 0 ? "text-red-500" : ""}`}>
              {summary.over_budget_departments ?? 0}
            </p>
          </CardContent>
        </Card>
      </div>

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
                          className="h-7 text-xs text-red-600"
                          onClick={() => deleteMut.mutate(t.id)}
                          disabled={deleteMut.isPending}
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

      {/* ================================================================== */}
      {/* DIALOG: Set Budget Target                                           */}
      {/* ================================================================== */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Set Department Budget</DialogTitle>
            <DialogDescription>
              Set a budget target for a department for period <strong>{period}</strong>.
              Existing entries will be updated.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
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
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleUpsert} disabled={upsertMut.isPending}>
              {upsertMut.isPending && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              Save Target
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </motion.div>
  );
}
