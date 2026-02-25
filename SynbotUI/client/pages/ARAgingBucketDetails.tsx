import { useMemo } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const bucketLabelMap: Record<string, string> = {
  "0-30": "0-30 days",
  "31-60": "31-60 days",
  "61-90": "61-90 days",
  "90+": "90+ days",
  "0_30": "0-30 days",
  "31_60": "31-60 days",
  "61_90": "61-90 days",
  "91_plus": "90+ days",
};

const ARAgingBucketDetails = () => {
  const params = useParams<{ bucket: string }>();
  const rawBucket = typeof params.bucket === "string" ? params.bucket : "";

  const normalizedBucket = useMemo(() => {
    const b = decodeURIComponent(rawBucket).toLowerCase();
    if (b.startsWith("0-30")) return "0-30";
    if (b.startsWith("31-60")) return "31-60";
    if (b.startsWith("61-90")) return "61-90";
    if (b.startsWith("90+")) return "90+";
    if (b.startsWith("0_30")) return "0-30";
    if (b.startsWith("31_60")) return "31-60";
    if (b.startsWith("61_90")) return "61-90";
    if (b.startsWith("91_plus")) return "90+";
    return b;
  }, [rawBucket]);

  const { data, isLoading, error } = useQuery({
    queryKey: ["reports-ar-aging-customers", normalizedBucket],
    queryFn: () => api.finance.arAgingCustomers(normalizedBucket),
    enabled: Boolean(normalizedBucket),
    refetchInterval: 60000,
  });

  const rawCustomers = Array.isArray((data as any)?.customers)
    ? (data as any).customers
    : Array.isArray(data)
      ? data
      : [];
  const customers = rawCustomers.filter((row: any) =>
    typeof row?.customer_id === "string" &&
    typeof row?.customer_name === "string" &&
    Number.isFinite(Number(row?.total_balance)) &&
    Number.isFinite(Number(row?.total_amount))
  );
  const malformedCount = rawCustomers.length - customers.length;
  const displayLabel = bucketLabelMap[normalizedBucket] || normalizedBucket;

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-foreground">AR Aging Details</h1>
          <p className="text-muted-foreground mt-2">
            Customers in the <span className="font-semibold">{displayLabel}</span> bucket.
          </p>
        </div>
        <Button asChild variant="outline">
          <Link to="/finance/reports">Back to Finance Reports</Link>
        </Button>
      </div>

      {isLoading && <div className="p-8 text-center">Loading customer aging details...</div>}
      {error && (
        <div className="p-8 text-center text-red-500">
          Data error: {((error as Error)?.message) || "Failed to load customer aging details."}
        </div>
      )}

      {!isLoading && !error && !displayLabel && (
        <div className="p-8 text-center text-red-500">Data error: invalid bucket parameter.</div>
      )}

      {!isLoading && !error && !!displayLabel && (
        <div className="bg-card border border-border rounded-lg p-6 space-y-4">
          {malformedCount > 0 && (
            <p className="text-sm text-destructive">
              Data error: {malformedCount} customer record(s) were malformed and excluded.
            </p>
          )}
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Customer ID</TableHead>
                  <TableHead>Customer Name</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Phone</TableHead>
                  <TableHead className="text-right">Total Balance (₦)</TableHead>
                  <TableHead className="text-right">Total Amount (₦)</TableHead>
                  <TableHead className="text-center">Invoices</TableHead>
                  <TableHead className="text-center">Max Days Overdue</TableHead>
                  <TableHead>Earliest Due Date</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {customers.length > 0 ? (
                  customers.map((c: any) => (
                    <TableRow key={c.customer_id}>
                      <TableCell className="font-mono text-xs">{c.customer_id}</TableCell>
                      <TableCell className="font-medium">{c.customer_name}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">{typeof c.email === "string" ? c.email : ""}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">{typeof c.phone === "string" ? c.phone : ""}</TableCell>
                      <TableCell className="text-right font-mono">
                        {Number(c.total_balance).toLocaleString()}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {Number(c.total_amount).toLocaleString()}
                      </TableCell>
                      <TableCell className="text-center">{c.invoices_count}</TableCell>
                      <TableCell className="text-center">{c.max_days_overdue}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {typeof c.earliest_due_date === "string" ? c.earliest_due_date : ""}
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell colSpan={9} className="text-center py-8">
                      <p className="text-muted-foreground">No customers found in this bucket.</p>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
          <p className="text-xs text-muted-foreground">
            Showing {customers.length} customers in the {displayLabel} bucket.
          </p>
        </div>
      )}
    </div>
  );
};

export default ARAgingBucketDetails;
