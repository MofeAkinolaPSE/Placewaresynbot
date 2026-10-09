import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api-client";
import { ChevronLeft, ChevronRight } from "lucide-react";

const PAGE_SIZE = 200;

const fmt = new Intl.NumberFormat("en-NG", {
  style: "currency",
  currency: "NGN",
  maximumFractionDigits: 0,
});

const JOURNAL_COLORS: Record<string, string> = {
  GJ:   "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  SJ:   "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  CR:   "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300",
  COGS: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
};

export function GlTransactionsTable() {
  const [page, setPage]         = useState(0);
  const [acctFilter, setAcct]   = useState("");
  const [jtFilter, setJt]       = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["gl-detail", page, acctFilter, jtFilter],
    queryFn: () => api.finance.glDetail({
      limit:        PAGE_SIZE,
      offset:       page * PAGE_SIZE,
      account_code: acctFilter || undefined,
      journal_type: jtFilter   || undefined,
    }),
    placeholderData: keepPreviousData,  // keep the current page on screen while the next loads
  });

  const page_ = data as { data?: any[]; count?: number } | undefined;
  const rows: any[]  = page_?.data || [];
  const count: number = page_?.count ?? 0;
  const hasPrev = page > 0;
  const hasNext = count === PAGE_SIZE;

  return (
    <div className="space-y-3">
      {/* Filters */}
      <div className="flex flex-wrap gap-2">
        <Input
          placeholder="Filter by account code…"
          className="h-8 w-48 text-sm"
          value={acctFilter}
          onChange={e => { setAcct(e.target.value); setPage(0); }}
        />
        <Input
          placeholder="Journal type (GJ, SJ, CR…)"
          className="h-8 w-44 text-sm"
          value={jtFilter}
          onChange={e => { setJt(e.target.value); setPage(0); }}
        />
      </div>

      {/* Table */}
      <div className="rounded-xl border border-border/60 overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40">
              <TableHead className="min-w-[90px]">Date</TableHead>
              <TableHead className="min-w-[100px]">Account</TableHead>
              <TableHead className="min-w-[180px]">Description</TableHead>
              <TableHead className="min-w-[70px]">Journal</TableHead>
              <TableHead className="min-w-[80px]">Reference</TableHead>
              <TableHead className="text-right min-w-[110px]">Debit</TableHead>
              <TableHead className="text-right min-w-[110px]">Credit</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-10 text-sm text-muted-foreground">
                  Loading GL transactions…
                </TableCell>
              </TableRow>
            )}
            {!isLoading && error && (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-10 text-sm text-destructive">
                  Failed to load GL transactions.
                </TableCell>
              </TableRow>
            )}
            {!isLoading && !error && rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-10 text-sm text-muted-foreground">
                  No transactions found. Import Sage 50 GL exports to populate this table.
                </TableCell>
              </TableRow>
            )}
            {rows.map((row, i) => {
              const debit  = parseFloat(row.debit  || "0");
              const credit = parseFloat(row.credit || "0");
              const jt     = (row.journal_type || "").toUpperCase();
              return (
                <TableRow key={row.id || i} className="text-sm">
                  <TableCell className="text-muted-foreground tabular-nums whitespace-nowrap">
                    {row.txn_date || "—"}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    <div>{row.account_code}</div>
                    {row.account_name && (
                      <div className="text-muted-foreground truncate max-w-[120px]">{row.account_name}</div>
                    )}
                  </TableCell>
                  <TableCell className="truncate max-w-[200px]">{row.description || "—"}</TableCell>
                  <TableCell>
                    {jt ? (
                      <Badge variant="outline" className={`text-xs ${JOURNAL_COLORS[jt] || ""}`}>
                        {jt}
                      </Badge>
                    ) : "—"}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{row.reference || "—"}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {debit > 0 ? fmt.format(debit) : "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {credit > 0 ? fmt.format(credit) : "—"}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      {/* Pagination */}
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Button variant="outline" size="sm" disabled={!hasPrev} onClick={() => setPage(p => p - 1)}>
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span>Page {page + 1}</span>
        <Button variant="outline" size="sm" disabled={!hasNext} onClick={() => setPage(p => p + 1)}>
          <ChevronRight className="h-4 w-4" />
        </Button>
        <span className="ml-2">{count} rows shown</span>
      </div>
    </div>
  );
}
