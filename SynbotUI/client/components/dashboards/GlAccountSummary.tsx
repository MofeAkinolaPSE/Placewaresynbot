import { useQuery } from "@tanstack/react-query";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { api } from "@/lib/api-client";

const fmt = new Intl.NumberFormat("en-NG", {
  style: "currency",
  currency: "NGN",
  maximumFractionDigits: 0,
});

function AmountCell({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-muted-foreground">—</span>;
  const n = parseFloat(String(value));
  const cls = n < 0 ? "text-destructive" : n > 0 ? "" : "text-muted-foreground";
  return <span className={`tabular-nums ${cls}`}>{fmt.format(n)}</span>;
}

export function GlAccountSummary() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["gl-account-summary"],
    queryFn: () => api.finance.glSummary(),
  });

  const rows: any[]   = data?.data || [];
  const totalEnding   = data?.total_ending_balance ?? null;

  return (
    <div className="space-y-3">
      {/* Totals banner */}
      {totalEnding !== null && (
        <div className="rounded-xl border border-border/60 px-4 py-3 flex items-center gap-4 bg-muted/20">
          <div>
            <p className="text-xs text-muted-foreground">Total Ending Balance</p>
            <p className="text-lg font-semibold tabular-nums">{fmt.format(totalEnding)}</p>
          </div>
          <div className="ml-auto text-xs text-muted-foreground">{rows.length} accounts</div>
        </div>
      )}

      {/* Table */}
      <div className="rounded-xl border border-border/60 overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40">
              <TableHead className="min-w-[100px]">Account</TableHead>
              <TableHead className="min-w-[200px]">Name</TableHead>
              <TableHead className="text-right min-w-[120px]">Beginning</TableHead>
              <TableHead className="text-right min-w-[110px]">Debit Δ</TableHead>
              <TableHead className="text-right min-w-[110px]">Credit Δ</TableHead>
              <TableHead className="text-right min-w-[110px]">Net Δ</TableHead>
              <TableHead className="text-right min-w-[120px]">Ending</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-10 text-sm text-muted-foreground">
                  Loading GL account summary…
                </TableCell>
              </TableRow>
            )}
            {!isLoading && error && (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-10 text-sm text-destructive">
                  Failed to load GL account summary.
                </TableCell>
              </TableRow>
            )}
            {!isLoading && !error && rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-10 text-sm text-muted-foreground">
                  No account summary data. Import the Sage 50 "Gl account summary" export to populate.
                </TableCell>
              </TableRow>
            )}
            {rows.map((row, i) => (
              <TableRow key={row.account_code || i} className="text-sm">
                <TableCell className="font-mono text-xs">{row.account_code}</TableCell>
                <TableCell className="truncate max-w-[220px]">{row.account_name || "—"}</TableCell>
                <TableCell className="text-right"><AmountCell value={row.beginning_balance} /></TableCell>
                <TableCell className="text-right"><AmountCell value={row.debit_change} /></TableCell>
                <TableCell className="text-right"><AmountCell value={row.credit_change} /></TableCell>
                <TableCell className="text-right"><AmountCell value={row.net_change} /></TableCell>
                <TableCell className="text-right font-medium"><AmountCell value={row.ending_balance} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
