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
import { format } from "date-fns";

export function GeneralLedgerTable() {
  const { data: rows, isLoading, error } = useQuery({
    queryKey: ["finance-gl"],
    queryFn: () => api.finance.gl(),
  });

  const data = rows || [];

  return (
    <div className="pw-surface-interactive rounded-xl">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Period</TableHead>
            <TableHead>Account Code</TableHead>
            <TableHead>Account Name</TableHead>
            <TableHead className="text-right">Debit</TableHead>
            <TableHead className="text-right">Credit</TableHead>
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
              <TableCell>{row.period}</TableCell>
              <TableCell className="font-mono text-xs">{row.account_code}</TableCell>
              <TableCell className="font-medium">{row.account_name}</TableCell>
              <TableCell className="text-right text-muted-foreground">
                 {parseFloat(row.debit) > 0 ? `₦${parseFloat(row.debit).toLocaleString()}` : "-"}
              </TableCell>
              <TableCell className="text-right text-muted-foreground">
                 {parseFloat(row.credit) > 0 ? `₦${parseFloat(row.credit).toLocaleString()}` : "-"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <div className="border-t bg-muted/40 p-4 text-xs text-muted-foreground">
         Showing latest snapshot entries.
      </div>
    </div>
  );
}
