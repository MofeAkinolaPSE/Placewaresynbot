import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { useIsMobile } from "@/hooks/use-mobile";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export function TimesheetsTable() {
  const isMobile = useIsMobile();
  const { data, isLoading, error } = useQuery({
    queryKey: ["timesheets"],
    queryFn: () => api.staff.timesheets(),
    refetchInterval: 60000,
  });

  const payloadValid = Array.isArray(data);
  const dataError = !isLoading && (error || !payloadValid);

  const rows = (payloadValid ? data : []).filter((row: any) =>
    row &&
    (typeof row.id === "number" || typeof row.id === "string") &&
    typeof row.date === "string" &&
    typeof row.department === "string" &&
    Number.isFinite(Number(row.hours_worked))
  );
  const malformedCount = (payloadValid ? data.length : 0) - rows.length;

  return (
    <div className="rounded-md border bg-card">
      <div className="border-b p-4 text-sm text-muted-foreground">
        Recent timesheet entries from staff operations.
      </div>
      {isLoading && (
        <div className="px-4 py-2 text-sm text-muted-foreground border-b">
          Loading timesheets...
        </div>
      )}
      {dataError && (
        <div className="px-4 py-2 text-sm text-destructive border-b">
          Data error: {(error as Error)?.message || "Malformed timesheets payload."}
        </div>
      )}
      {malformedCount > 0 && (
        <div className="px-4 py-2 text-sm text-destructive border-b">
          Data error: {malformedCount} timesheet row(s) were malformed and excluded.
        </div>
      )}
      {isMobile ? (
        <div className="space-y-3 p-4">
          {rows.length > 0 ? (
            rows.map((row: any) => (
              <div key={row.id} className="rounded-lg border border-border/60 bg-muted/20 p-3 space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <p className="font-semibold text-foreground">
                    {typeof row.staff?.full_name === "string" ? row.staff.full_name : String(row.staff_id || "")}
                  </p>
                  <p className="font-mono text-sm text-foreground">{Number(row.hours_worked).toFixed(2)}h</p>
                </div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span>{row.date}</span>
                  <span>•</span>
                  <span>{row.department}</span>
                </div>
                <p className="text-xs text-muted-foreground break-words">
                  {typeof row.activity_note === "string" ? row.activity_note : ""}
                </p>
              </div>
            ))
          ) : (
            <p className="text-center text-muted-foreground py-6">
              No timesheet data uploaded yet. Once teams start recording hours in Placeware,
              entries will appear here automatically.
            </p>
          )}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-[120px]">Date</TableHead>
                <TableHead className="sticky left-0 z-10 min-w-[180px] bg-muted/90">Staff</TableHead>
                <TableHead className="min-w-[140px]">Department</TableHead>
                <TableHead className="text-right min-w-[120px]">Hours Worked</TableHead>
                <TableHead className="min-w-[280px]">Activity</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length > 0 ? (
                rows.map((row: any) => (
                  <TableRow key={row.id}>
                    <TableCell className="text-sm text-muted-foreground">
                      {row.date}
                    </TableCell>
                    <TableCell className="sticky left-0 z-10 bg-background font-medium">
                      {typeof row.staff?.full_name === "string" ? row.staff.full_name : String(row.staff_id || "")}
                    </TableCell>
                    <TableCell>{row.department}</TableCell>
                    <TableCell className="text-right font-mono">
                      {Number(row.hours_worked).toFixed(2)}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground max-w-xs truncate">
                      {typeof row.activity_note === "string" ? row.activity_note : ""}
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={5} className="text-center py-10">
                    <p className="text-muted-foreground">
                      No timesheet data uploaded yet. Once teams start recording hours in Placeware,
                      entries will appear here automatically.
                    </p>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
