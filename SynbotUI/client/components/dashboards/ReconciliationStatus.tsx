import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api-client";
import { AlertTriangle, CheckCircle, Clock, Plus, RefreshCw } from "lucide-react";

const SNAPSHOT_LABELS: Record<string, string> = {
  account_reconciliation: "Account Reconciliation",
  account_register:       "Account Register",
  bank_deposit_report:    "Bank Deposit Report",
  deposits_in_transit:    "Deposits in Transit",
  other_outstanding_items:"Other Outstanding Items",
  outstanding_checks:     "Outstanding Checks",
};

const POINT_IN_TIME_TYPES = new Set([
  "account_reconciliation",
  "deposits_in_transit",
  "other_outstanding_items",
  "outstanding_checks",
]);

function StaleBadge({ row }: { row: any }) {
  if (!POINT_IN_TIME_TYPES.has(row.snapshot_type)) {
    return <Badge variant="outline" className="text-xs">Historical</Badge>;
  }
  if (row.days_since_update === null || row.days_since_update === undefined) {
    return <Badge variant="destructive" className="text-xs gap-1"><AlertTriangle className="h-3 w-3" />Never updated</Badge>;
  }
  if (row.days_since_update >= 30) {
    return <Badge variant="destructive" className="text-xs gap-1"><AlertTriangle className="h-3 w-3" />{row.days_since_update}d ago</Badge>;
  }
  if (row.days_since_update >= 14) {
    return <Badge className="text-xs gap-1 bg-amber-500 hover:bg-amber-500"><Clock className="h-3 w-3" />{row.days_since_update}d ago</Badge>;
  }
  return <Badge className="text-xs gap-1 bg-emerald-600 hover:bg-emerald-600"><CheckCircle className="h-3 w-3" />{row.days_since_update}d ago</Badge>;
}

function DifferenceBadge({ diff }: { diff: number | null }) {
  if (diff === null || diff === undefined) return <span className="text-muted-foreground text-xs">—</span>;
  const fmt = new Intl.NumberFormat("en-NG", { style: "currency", currency: "NGN", maximumFractionDigits: 0 });
  if (Math.abs(diff) < 0.01) {
    return <span className="text-emerald-600 font-medium text-sm">Balanced</span>;
  }
  return <span className="text-destructive font-medium text-sm">{fmt.format(diff)}</span>;
}

const EMPTY_FORM = {
  account_code: "",
  account_name: "",
  snapshot_type: "",
  reconciled_period: "",
  gl_balance: "",
  bank_balance: "",
  outstanding_count: "",
  outstanding_total: "",
  notes: "",
};

export function ReconciliationStatus() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["reconciliation-status"],
    queryFn: () => api.finance.reconciliationStatus(),
    refetchInterval: 60_000,
  });

  const log = useMutation({
    mutationFn: (payload: any) => api.finance.logReconciliation(payload),
    onSuccess: () => {
      toast({ title: "Reconciliation logged", description: "Record saved successfully." });
      queryClient.invalidateQueries({ queryKey: ["reconciliation-status"] });
      setOpen(false);
      setForm(EMPTY_FORM);
    },
    onError: (err: any) => {
      toast({ title: "Save failed", description: err.message, variant: "destructive" });
    },
  });

  const rows: any[] = data?.data || [];
  const staleCount: number = data?.stale_count ?? 0;

  const handleSubmit = () => {
    if (!form.account_code || !form.snapshot_type) {
      toast({ title: "Validation error", description: "Account code and type are required.", variant: "destructive" });
      return;
    }
    log.mutate({
      account_code: form.account_code.trim(),
      account_name: form.account_name || undefined,
      snapshot_type: form.snapshot_type,
      reconciled_period: form.reconciled_period || undefined,
      gl_balance: form.gl_balance ? parseFloat(form.gl_balance) : undefined,
      bank_balance: form.bank_balance ? parseFloat(form.bank_balance) : undefined,
      outstanding_count: form.outstanding_count ? parseInt(form.outstanding_count) : undefined,
      outstanding_total: form.outstanding_total ? parseFloat(form.outstanding_total) : undefined,
      notes: form.notes || undefined,
    });
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold">Bank Reconciliation Status</h3>
          <p className="text-sm text-muted-foreground">
            Point-in-time snapshots must be re-exported from Sage monthly.
            {staleCount > 0 && (
              <span className="ml-2 text-destructive font-medium">
                {staleCount} account{staleCount > 1 ? "s" : ""} overdue for update.
              </span>
            )}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()} className="gap-1">
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </Button>
          <Button size="sm" onClick={() => setOpen(true)} className="gap-1">
            <Plus className="h-3.5 w-3.5" /> Log Reconciliation
          </Button>
        </div>
      </div>

      {/* Table */}
      <div className="rounded-xl border border-border/60 overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40">
              <TableHead>Account</TableHead>
              <TableHead>Report Type</TableHead>
              <TableHead>Period</TableHead>
              <TableHead>GL Balance</TableHead>
              <TableHead>Bank Balance</TableHead>
              <TableHead>Difference</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-sm text-muted-foreground py-8">
                  Loading reconciliation data…
                </TableCell>
              </TableRow>
            )}
            {!isLoading && error && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-sm text-destructive py-8">
                  Failed to load reconciliation status.
                </TableCell>
              </TableRow>
            )}
            {!isLoading && !error && rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-sm text-muted-foreground py-8">
                  No reconciliation records yet. Log your first reconciliation using the button above,
                  or import Sage 50 reconciliation exports via the Data Import page.
                </TableCell>
              </TableRow>
            )}
            {rows.map((row, i) => {
              const fmt = new Intl.NumberFormat("en-NG", { style: "currency", currency: "NGN", maximumFractionDigits: 0 });
              return (
                <TableRow key={row.id || i} className={row.is_stale ? "bg-destructive/5" : ""}>
                  <TableCell className="font-medium text-sm">
                    {row.account_name || row.account_code}
                    {row.account_name && (
                      <span className="ml-1 text-xs text-muted-foreground">({row.account_code})</span>
                    )}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {SNAPSHOT_LABELS[row.snapshot_type] || row.snapshot_type}
                  </TableCell>
                  <TableCell className="text-sm">{row.reconciled_period || "—"}</TableCell>
                  <TableCell className="text-sm tabular-nums">
                    {row.gl_balance != null ? fmt.format(row.gl_balance) : "—"}
                  </TableCell>
                  <TableCell className="text-sm tabular-nums">
                    {row.bank_balance != null ? fmt.format(row.bank_balance) : "—"}
                  </TableCell>
                  <TableCell><DifferenceBadge diff={row.difference} /></TableCell>
                  <TableCell><StaleBadge row={row} /></TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-full bg-emerald-600" /> Up to date (&lt;14 days)</span>
        <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-full bg-amber-500" /> Aging (14–29 days)</span>
        <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-full bg-destructive" /> Overdue (30+ days — Ace will flag this in chat)</span>
        <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-full bg-muted border" /> Historical (no staleness check)</span>
      </div>

      {/* Log dialog */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Log Reconciliation</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-2">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>Account Code *</Label>
                <Input
                  placeholder="e.g. 1100"
                  value={form.account_code}
                  onChange={e => setForm(f => ({ ...f, account_code: e.target.value }))}
                />
              </div>
              <div className="space-y-1">
                <Label>Account Name</Label>
                <Input
                  placeholder="e.g. Current Bank Account"
                  value={form.account_name}
                  onChange={e => setForm(f => ({ ...f, account_name: e.target.value }))}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>Report Type *</Label>
                <Select value={form.snapshot_type} onValueChange={v => setForm(f => ({ ...f, snapshot_type: v }))}>
                  <SelectTrigger><SelectValue placeholder="Select type" /></SelectTrigger>
                  <SelectContent>
                    {Object.entries(SNAPSHOT_LABELS).map(([v, l]) => (
                      <SelectItem key={v} value={v}>{l}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label>Reconciled Period</Label>
                <Input
                  placeholder="YYYY-MM e.g. 2026-06"
                  value={form.reconciled_period}
                  onChange={e => setForm(f => ({ ...f, reconciled_period: e.target.value }))}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>GL Balance (₦)</Label>
                <Input
                  type="number"
                  placeholder="0.00"
                  value={form.gl_balance}
                  onChange={e => setForm(f => ({ ...f, gl_balance: e.target.value }))}
                />
              </div>
              <div className="space-y-1">
                <Label>Bank Statement Balance (₦)</Label>
                <Input
                  type="number"
                  placeholder="0.00"
                  value={form.bank_balance}
                  onChange={e => setForm(f => ({ ...f, bank_balance: e.target.value }))}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>Outstanding Item Count</Label>
                <Input
                  type="number"
                  placeholder="0"
                  value={form.outstanding_count}
                  onChange={e => setForm(f => ({ ...f, outstanding_count: e.target.value }))}
                />
              </div>
              <div className="space-y-1">
                <Label>Outstanding Total (₦)</Label>
                <Input
                  type="number"
                  placeholder="0.00"
                  value={form.outstanding_total}
                  onChange={e => setForm(f => ({ ...f, outstanding_total: e.target.value }))}
                />
              </div>
            </div>
            <div className="space-y-1">
              <Label>Notes</Label>
              <Textarea
                placeholder="Any discrepancies or notes about this reconciliation…"
                value={form.notes}
                onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
                rows={2}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={handleSubmit} disabled={log.isPending}>
              {log.isPending ? "Saving…" : "Save Record"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
