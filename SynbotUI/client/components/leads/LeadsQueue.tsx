import React, { useEffect, useState } from "react";
import { api } from "@/lib/api-client";
import { Button } from "@/components/ui/button";

export default function LeadsQueue() {
  const [leads, setLeads] = useState<any[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await api.leads.list(50);
      setLeads(Array.isArray(data) ? data : []);
    } catch (err: any) {
      setError("Leads list endpoint not available on backend. Please enable `/admin/leads` or use admin dashboard.");
      setLeads(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  if (loading) return <div>Loading leads...</div>;
  if (error) return (
    <div>
      <div className="text-sm text-destructive mb-2">{error}</div>
      <Button onClick={load}>Retry</Button>
      <div className="text-xs text-muted-foreground mt-3">Backend metric endpoint `/admin/leads-to-orders` is available for conversion metrics.</div>
    </div>
  );

  return (
    <div>
      <div className="flex justify-between items-center mb-2">
        <h3 className="text-lg font-medium">Active Leads</h3>
        <Button onClick={load}>Refresh</Button>
      </div>
      {leads && leads.length === 0 && <div className="text-sm text-muted-foreground">No leads found.</div>}
      {leads && leads.length > 0 && (
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
