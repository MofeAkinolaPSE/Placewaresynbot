import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { KpiStrip } from "@/components/workspace/KpiStrip";

export default function LeadsQueue() {
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["admin-leads"],
    queryFn: () => api.leads.list(50),
  });

  // Real bug fix: GET /admin/leads returns {data, count}, not a bare array —
  // the previous Array.isArray(data) check ran against the whole response
  // object and was always false, so this queue silently showed "No leads
  // found" regardless of what the backend actually returned.
  const leads: any[] = Array.isArray(data?.data) ? data.data : [];

  if (isLoading) return <div>Loading leads...</div>;
  if (isError) return (
    <div>
      <div className="text-sm text-destructive mb-2">Leads list endpoint not available on backend. Please enable `/admin/leads` or use admin dashboard.</div>
      <Button onClick={() => refetch()}>Retry</Button>
      <div className="text-xs text-muted-foreground mt-3">Backend metric endpoint `/admin/leads-to-orders` is available for conversion metrics.</div>
    </div>
  );

  return (
    <div className="space-y-3">
      <KpiStrip items={[{ label: "Total Leads", value: leads.length }]} />
      <div className="flex justify-between items-center">
        <h3 className="text-lg font-medium">Active Leads</h3>
        <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
          {isFetching ? "Refreshing..." : "Refresh"}
        </Button>
      </div>
      {leads.length === 0 && <div className="text-sm text-muted-foreground">No leads found.</div>}
      {leads.length > 0 && (
        <ul className="space-y-2">
          {leads.map((l) => (
            <li key={l.id} className="p-3 border rounded bg-card">
              <div className="flex justify-between">
                <div>
                  <div className="font-medium">{l.name || l.customer_name || l.email}</div>
                  <div className="text-xs text-muted-foreground">{l.email || l.customer_email} • {l.phone || l.customer_phone}</div>
                </div>
                <div className="text-right text-xs text-muted-foreground">{l.created_at}</div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
