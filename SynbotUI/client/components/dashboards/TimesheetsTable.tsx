import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export function TimesheetsTable() {
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
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Date</TableHead>
              <TableHead>Staff</TableHead>
              <TableHead>Department</TableHead>
              <TableHead className="text-right">Hours Worked</TableHead>
              <TableHead>Activity</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length > 0 ? (
              rows.map((row: any) => (
                <TableRow key={row.id}>
                  <TableCell className="text-sm text-muted-foreground">
                    {row.date}
                  </TableCell>
                  <TableCell className="font-medium">
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
    </div>
  );
}
