import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api-client";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";

export default function CRMLeadFinder() {
  const queryClient = useQueryClient();

  const [industry, setIndustry] = useState("pharma");
  const [region, setRegion] = useState("lagos");
  const [limit, setLimit] = useState(10);
  const [selectedProspectId, setSelectedProspectId] = useState<string | null>(null);
  const [expectedValue, setExpectedValue] = useState(500000);
  const [urgency, setUrgency] = useState<"low" | "medium" | "high">("medium");
  const [assignLeadId, setAssignLeadId] = useState(0);
  const [repUserId, setRepUserId] = useState("");
  const [followUpHours, setFollowUpHours] = useState(24);

  useRealtimeChannel("crm_updates", () => {
    void queryClient.invalidateQueries({ queryKey: ["lead-finder-pipeline"] });
  });

  const pipelineQuery = useQuery({
    queryKey: ["lead-finder-pipeline"],
    queryFn: () => api.leadFinder.pipeline(100),
  });

  const sourceMutation = useMutation({
    mutationFn: () =>
      api.leadFinder.sourceProspects({
        industry,
        region,
        limit,
        source: "revenue_officer",
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["lead-finder-pipeline"] });
    },
  });

  const scoreMutation = useMutation({
    mutationFn: () =>
      api.leadFinder.scoreIngestProspect(selectedProspectId as string, {
        expected_value: expectedValue,
        urgency,
        fit_signals: {
          decision_maker_identified: true,
          product_fit: true,
          urgent_need: urgency === "high",
        },
      }),
    onSuccess: (res) => {
      setAssignLeadId(Number(res?.lead?.id || 0));
      void queryClient.invalidateQueries({ queryKey: ["lead-finder-pipeline"] });
    },
  });

  const assignMutation = useMutation({
    mutationFn: () =>
      api.leadFinder.assignLead({
        lead_id: assignLeadId,
        rep_user_id: repUserId,
        follow_up_type: "call",
        follow_up_hours: followUpHours,
        notes: "Auto-assigned by revenue officer lead finder",
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["lead-finder-pipeline"] });
    },
  });

  const prospects = Array.isArray(pipelineQuery.data?.prospects) ? pipelineQuery.data.prospects : [];
  const followups = Array.isArray(pipelineQuery.data?.followups) ? pipelineQuery.data.followups : [];

  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Lead Finder</h1>
        <p className="text-muted-foreground">Prospect sourcing, enrichment, scoring, CRM ingest, and automated assignment flow.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>1) Prospect Sourcing + Enrichment</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-4">
          <div>
            <Label>Industry</Label>
            <Select value={industry} onValueChange={setIndustry}>
              <SelectTrigger><SelectValue placeholder="Industry" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="pharma">Pharma / Healthcare</SelectItem>
                <SelectItem value="fmcg">FMCG</SelectItem>
                <SelectItem value="manufacturing">Manufacturing</SelectItem>
                <SelectItem value="retail">Retail</SelectItem>
                <SelectItem value="finance">Financial Services</SelectItem>
                <SelectItem value="logistics">Logistics</SelectItem>
                <SelectItem value="education">Education</SelectItem>
                <SelectItem value="other">Other</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>Region</Label>
            <Select value={region} onValueChange={setRegion}>
              <SelectTrigger><SelectValue placeholder="Region" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="lagos">Lagos</SelectItem>
                <SelectItem value="abuja">Abuja (FCT)</SelectItem>
                <SelectItem value="kano">Kano</SelectItem>
                <SelectItem value="phc">Port Harcourt</SelectItem>
                <SelectItem value="ibadan">Ibadan</SelectItem>
                <SelectItem value="enugu">Enugu</SelectItem>
                <SelectItem value="nationwide">Nationwide</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>Limit</Label>
            <Input type="number" value={limit} onChange={(e) => setLimit(Number(e.target.value || 1))} />
          </div>
          <div className="flex items-end">
            <Button className="w-full" onClick={() => sourceMutation.mutate()} disabled={sourceMutation.isPending}>
              {sourceMutation.isPending ? "Sourcing..." : "Source Prospects"}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>2) Lead Scoring + CRM Insert</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-2 md:grid-cols-4">
            <div>
              <Label>Prospect ID</Label>
              <Input value={selectedProspectId || ""} onChange={(e) => setSelectedProspectId(e.target.value)} placeholder="Select from list below" />
            </div>
            <div>
              <Label>Expected Value</Label>
              <Input type="number" value={expectedValue} onChange={(e) => setExpectedValue(Number(e.target.value || 0))} />
            </div>
            <div>
              <Label>Urgency</Label>
              <Select value={urgency} onValueChange={(v) => setUrgency(v as "low" | "medium" | "high")}>
                <SelectTrigger><SelectValue placeholder="Urgency" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="low">Low</SelectItem>
                  <SelectItem value="medium">Medium</SelectItem>
                  <SelectItem value="high">High</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-end">
              <Button className="w-full" onClick={() => scoreMutation.mutate()} disabled={!selectedProspectId || scoreMutation.isPending}>
                {scoreMutation.isPending ? "Scoring..." : "Score + Ingest"}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>3) Assignment + Follow-up Automation</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-4">
          <div>
            <Label>Lead ID</Label>
            <Input type="number" value={assignLeadId || ""} onChange={(e) => setAssignLeadId(Number(e.target.value || 0))} />
          </div>
          <div>
            <Label>Revenue Officer User ID</Label>
            <Input value={repUserId} onChange={(e) => setRepUserId(e.target.value)} placeholder="user-123" />
          </div>
          <div>
            <Label>Follow-up Hours</Label>
            <Input type="number" value={followUpHours} onChange={(e) => setFollowUpHours(Number(e.target.value || 24))} />
          </div>
          <div className="flex items-end">
            <Button className="w-full" onClick={() => assignMutation.mutate()} disabled={!assignLeadId || !repUserId || assignMutation.isPending}>
              {assignMutation.isPending ? "Assigning..." : "Assign Lead"}
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Prospects</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 max-h-[420px] overflow-y-auto">
            {prospects.length === 0 ? (
              <p className="text-sm text-muted-foreground">{pipelineQuery.isLoading ? "Loading prospects..." : "No prospects yet."}</p>
            ) : prospects.map((p: any) => (
              <button
                key={p.id}
                onClick={() => setSelectedProspectId(String(p.id))}
                className={`w-full rounded border p-3 text-left ${selectedProspectId === String(p.id) ? "border-primary" : ""}`}
              >
                <p className="font-medium">{p.company_name}</p>
                <p className="text-xs text-muted-foreground">{p.industry || "-"} · {p.region || "-"}</p>
                <p className="text-xs text-muted-foreground">score: {p.score ?? 0} · status: {p.status}</p>
              </button>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Follow-ups</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 max-h-[420px] overflow-y-auto">
            {followups.length === 0 ? (
              <p className="text-sm text-muted-foreground">No follow-ups yet.</p>
            ) : followups.map((f: any) => (
              <div key={f.id} className="rounded border p-3">
                <p className="font-medium">Lead #{f.lead_id}</p>
                <p className="text-xs text-muted-foreground">Assigned: {f.assigned_to}</p>
                <p className="text-xs text-muted-foreground">Due: {f.due_at || "-"}</p>
                <p className="text-xs text-muted-foreground">Status: {f.status}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
