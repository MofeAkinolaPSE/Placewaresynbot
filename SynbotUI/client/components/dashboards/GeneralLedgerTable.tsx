import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { useIsMobile } from "@/hooks/use-mobile";

export function GeneralLedgerTable() {
  const isMobile = useIsMobile();
  const { data: rows, isLoading, error } = useQuery({
    queryKey: ["finance-gl"],
    queryFn: () => api.finance.gl(),
  });

  const data = rows || [];

  return (
    <div className="pw-surface-interactive rounded-xl">
      {isMobile ? (
        <div className="space-y-3 p-4">
          {isLoading && <p className="text-sm text-muted-foreground">Loading General Ledger...</p>}
          {!isLoading && error && <p className="text-sm text-destructive">Failed to load GL entries.</p>}
          {!isLoading && !error && data.length === 0 && <p className="text-sm text-muted-foreground">No GL entries found.</p>}
          {!isLoading && !error && data.map((row: any, i: number) => (
            <div key={row.id || i} className="rounded-lg border border-border/60 bg-muted/20 p-3 space-y-2">
              <div className="flex items-start justify-between gap-2">
                <p className="font-semibold text-foreground">{row.account_name}</p>
                <p className="text-xs text-muted-foreground">{row.period}</p>
              </div>
              <p className="text-xs font-mono text-muted-foreground">{row.account_code}</p>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <p className="text-muted-foreground">Debit: <span className="font-mono text-foreground">{parseFloat(row.debit) > 0 ? `₦${parseFloat(row.debit).toLocaleString()}` : "-"}</span></p>
                <p className="text-muted-foreground">Credit: <span className="font-mono text-foreground">{parseFloat(row.credit) > 0 ? `₦${parseFloat(row.credit).toLocaleString()}` : "-"}</span></p>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="sticky left-0 z-10 min-w-[120px] bg-muted/90">Period</TableHead>
                <TableHead className="min-w-[120px]">Account Code</TableHead>
                <TableHead className="min-w-[220px]">Account Name</TableHead>
                <TableHead className="text-right min-w-[120px]">Debit</TableHead>
                <TableHead className="text-right min-w-[120px]">Credit</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center h-24">Loading General Ledger...</TableCell>
                </TableRow>
              )}
              {!isLoading && error && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center h-24 text-destructive">Failed to load GL entries.</TableCell>
                </TableRow>
              )}
               {!isLoading && !error && data.length === 0 && (
                 <TableRow>
                    <TableCell colSpan={5} className="text-center h-24">No GL entries found.</TableCell>
                 </TableRow>
              )}
              {data.map((row: any, i: number) => (
                <TableRow key={row.id || i}>
                  <TableCell className="sticky left-0 z-10 bg-background">{row.period}</TableCell>
                  <TableCell className="font-mono text-xs">{row.account_code}</TableCell>
                  <TableCell className="font-medium">{row.account_name}</TableCell>
                  <TableCell className="text-right text-muted-foreground font-mono">
                     {parseFloat(row.debit) > 0 ? `₦${parseFloat(row.debit).toLocaleString()}` : "-"}
                  </TableCell>
                  <TableCell className="text-right text-muted-foreground font-mono">
                     {parseFloat(row.credit) > 0 ? `₦${parseFloat(row.credit).toLocaleString()}` : "-"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      <div className="border-t bg-muted/40 p-4 text-xs text-muted-foreground">
         Showing latest snapshot entries.
      </div>
    </div>
  );
}
