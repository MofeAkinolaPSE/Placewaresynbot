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
import { Badge } from "@/components/ui/badge";

export function StaffDirectory() {
  const { data: staffList, isLoading, isError: staffError, error: staffErrorObj } = useQuery({
    queryKey: ["staff-list"],
    queryFn: () => api.staff.list(),
  });
  const { data: snapshotList, isError: snapshotError, error: snapshotErrorObj } = useQuery({
    queryKey: ["staff-snapshot"],
    queryFn: () => api.staff.snapshot(),
  });

  // Backend response shape is { data: [...] } from staff router
  // But wait, staff router in staff_ops.py:
  // "return {"data": get_staff_by_department(department)}"
  // And api-client.ts says: "return res.json().then(d => d.data)"
  // So staffList here should be the array itself.

  const liveRows = Array.isArray(staffList) ? (staffList as any[]) : [];
  const snapRows = Array.isArray(snapshotList) ? (snapshotList as any[]) : [];
  const rows: any[] = liveRows.length > 0 ? liveRows : snapRows;
  const usingSnapshot = liveRows.length === 0 && snapRows.length > 0;

  if (!Array.isArray(staffList) && !Array.isArray(snapshotList)) {
    return (
      <div className="rounded-md border p-4 text-sm text-destructive">
        Data error: staff payload is unavailable or malformed.
        {staffError ? ` ${(staffErrorObj as Error)?.message || ""}` : ""}
        {snapshotError ? ` ${(snapshotErrorObj as Error)?.message || ""}` : ""}
      </div>
    );
  }

  return (
    <div className="rounded-md border">
      {isLoading && (
        <div className="p-3 text-xs text-muted-foreground border-b">
          Loading staff directory...
        </div>
      )}
      {usingSnapshot && (
        <div className="p-3 text-xs text-muted-foreground border-b">
          Showing latest import snapshot (not yet synced to live registry).
        </div>
      )}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Full Name</TableHead>
            <TableHead>Email</TableHead>
            <TableHead>Department</TableHead>
            <TableHead>Role</TableHead>
            <TableHead>Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.filter((staff: any) => typeof staff?.full_name === "string" && typeof staff?.email === "string").map((staff) => (
            <TableRow key={staff.staff_id ?? staff.email}>
              <TableCell className="font-medium">{staff.full_name}</TableCell>
              <TableCell>{staff.email}</TableCell>
              <TableCell>{staff.department}</TableCell>
              <TableCell>{typeof staff.role === "string" ? staff.role : ""}</TableCell>
              <TableCell>
                <Badge variant={staff.status === "active" ? "default" : "secondary"}>
                  {staff.status}
                </Badge>
              </TableCell>
            </TableRow>
          ))}
          {rows.length === 0 && (
             <TableRow>
                <TableCell colSpan={5} className="text-center h-24">
                   No staff records found. Import them via the Sage Import page.
                </TableCell>
             </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}
