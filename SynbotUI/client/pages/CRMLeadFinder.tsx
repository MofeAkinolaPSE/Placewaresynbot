import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api-client";
import { authClient } from "@/lib/auth-client";
import { apiUrl } from "@/lib/api-base";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { MapContainer, TileLayer, Marker, Popup } from "react-leaflet";
import L from "leaflet";
import { motion } from "framer-motion";
import { motionVariants } from "@/lib/motion";
import {
  Search,
  MapPin,
  Download,
  Star,
  Phone,
  Globe,
  Map as MapIcon,
  Users,
  ClipboardList,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Zap,
  RefreshCw,
  Plus,
} from "lucide-react";
import { PageHeader } from "@/components/workspace/PageHeader";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { EntityAutocomplete } from "@/components/workspace/EntityAutocomplete";

// â”€â”€ Leaflet icon fix â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// eslint-disable-next-line @typescript-eslint/no-explicit-any
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  iconUrl:       "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  shadowUrl:     "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
});

// â”€â”€ Types â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

interface Prospect {
  id: string;
  company_name: string;
  industry?: string;
  region?: string;
  formatted_address?: string;
  contact_name?: string;
  contact_email?: string;
  contact_phone?: string;
  phone_number?: string;
  website?: string;
  rating?: number;
  user_ratings_total?: number;
  places_score?: number;
  score?: number;
  status: string;
  source?: string;
  search_query?: string;
  lat?: number;
  lng?: number;
  converted_lead_id?: number;
}

interface FollowUp {
  id: string;
  lead_id?: number;
  assigned_to: string;
  follow_up_type?: string;
  due_at?: string;
  status: string;
  notes?: string;
}

// â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function scoreColor(score: number): string {
  if (score >= 70) return "bg-green-500/20 text-green-400 border-green-500/30";
  if (score >= 45) return "bg-yellow-500/20 text-yellow-400 border-yellow-500/30";
  return "bg-red-500/20 text-red-400 border-red-500/30";
}

function renderStars(rating?: number) {
  if (!rating) return null;
  return (
    <span className="flex items-center gap-0.5 text-yellow-400 text-xs">
      <Star className="h-3 w-3 fill-yellow-400" />
      {rating.toFixed(1)}
    </span>
  );
}

// â”€â”€ Component â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export default function CRMLeadFinder() {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  // â”€â”€ Discover tab state â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  const [location, setLocation] = useState("Lagos, Nigeria");
  const [businessType, setBusinessType] = useState("pharmacy");
  const [radiusKm, setRadiusKm] = useState(5);
  const [searchLimit, setSearchLimit] = useState(20);
  const [showMap, setShowMap] = useState(false);
  const [findOpen, setFindOpen] = useState(false);
  // Holds the latest search mutation result for immediate display
  const [searchResults, setSearchResults] = useState<Prospect[] | null>(null);

  // â”€â”€ Pipeline tab state â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  const [selectedProspectId, setSelectedProspectId] = useState<string | null>(null);
  const [expectedValue, setExpectedValue] = useState(500000);
  const [urgency, setUrgency] = useState<"low" | "medium" | "high">("medium");
  const [assignLeadId, setAssignLeadId] = useState(0);
  const [repUserId, setRepUserId] = useState("");
  const [followUpHours, setFollowUpHours] = useState(24);

  // Realtime invalidation
  useRealtimeChannel("crm_updates", () => {
    void queryClient.invalidateQueries({ queryKey: ["lead-finder-pipeline"] });
  });

  // â”€â”€ Pipeline query â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  const pipelineQuery = useQuery({
    queryKey: ["lead-finder-pipeline"],
    queryFn: () => api.leadFinder.pipeline(200),
  });
  // Clear searchResults once the pipeline has refetched so the persistent view takes over
  useEffect(() => {
    if (pipelineQuery.isSuccess && searchResults !== null) {
      setSearchResults(null);
    }
  }, [pipelineQuery.dataUpdatedAt]); // eslint-disable-line react-hooks/exhaustive-deps
  const pipelineProspects: Prospect[] = Array.isArray(pipelineQuery.data?.prospects)
    ? pipelineQuery.data.prospects
    : [];
  // Show immediate search results while pipeline refetches; fall back to pipeline data
  const prospects: Prospect[] = searchResults !== null ? searchResults : pipelineProspects;
  const followups: FollowUp[] = Array.isArray(pipelineQuery.data?.followups)
    ? pipelineQuery.data.followups
    : [];

  // Derived from the same array (not a separate snapshot) so the Detail
  // Workspace automatically reflects the latest data after any mutation's
  // invalidation — same pattern as QualityControl.tsx's CapaTab.
  const selected = useMemo(
    () => prospects.find((p) => String(p.id) === selectedProspectId) ?? null,
    [prospects, selectedProspectId],
  );

  function selectProspect(p: Prospect) {
    setSelectedProspectId(String(p.id));
    if (p.converted_lead_id) setAssignLeadId(p.converted_lead_id);
  }

  // â”€â”€ Mutations â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  const searchMutation = useMutation({
    mutationFn: () =>
      api.leadFinder.searchByLocation({
        location: location.trim(),
        business_type: businessType.trim(),
        radius_m: radiusKm * 1000,
        limit: searchLimit,
        industry: "pharma",
        region: location.trim(),
      }),
    onSuccess: (data: any) => {
      // Show results immediately from mutation response — don't wait for pipeline refetch
      setSearchResults(Array.isArray(data.prospects) ? data.prospects : []);
      setFindOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["lead-finder-pipeline"] });
      const newCount = data.count ?? 0;
      const total = (data.prospects ?? []).length;
      const skipped = data.skipped ?? 0;
      const errors = data.errors ?? 0;
      const title =
        newCount > 0
          ? `Found ${newCount} new lead${newCount === 1 ? "" : "s"}`
          : skipped > 0
          ? `${skipped} lead${skipped === 1 ? "" : "s"} already in CRM`
          : errors > 0
          ? "Search failed — check migration 085"
          : "No leads found";
      const description =
        errors > 0
          ? `${errors} insert error${errors === 1 ? "" : "s"} — migration 085 may not be applied.`
          : newCount > 0 && skipped > 0
          ? `${skipped} duplicate(s) already in CRM — showing all ${total}.`
          : newCount > 0
          ? `${total} lead${total === 1 ? "" : "s"} displayed.`
          : skipped > 0
          ? `Showing ${total} existing prospect${total === 1 ? "" : "s"} from a previous search.`
          : undefined;
      toast({ title, description, variant: errors > 0 ? "destructive" : "default" });
    },
    onError: (e: any) => {
      toast({ title: "Search failed", description: e?.message, variant: "destructive" });
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
    onSuccess: (res: any) => {
      setAssignLeadId(Number(res?.lead?.id || 0));
      void queryClient.invalidateQueries({ queryKey: ["lead-finder-pipeline"] });
      toast({ title: "Lead ingested", description: `Score: ${res?.score}` });
    },
    onError: (e: any) => {
      toast({ title: "Score/ingest failed", description: e?.message, variant: "destructive" });
    },
  });

  const assignMutation = useMutation({
    mutationFn: () =>
      api.leadFinder.assignLead({
        lead_id: assignLeadId,
        rep_user_id: repUserId,
        follow_up_type: "call",
        follow_up_hours: followUpHours,
        notes: "Assigned via Lead Finder",
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["lead-finder-pipeline"] });
      toast({ title: "Lead assigned", description: `Follow-up due in ${followUpHours}h` });
    },
    onError: (e: any) => {
      toast({ title: "Assignment failed", description: e?.message, variant: "destructive" });
    },
  });

  // â”€â”€ CSV export â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  const handleExport = useCallback(async () => {
    try {
      const token = authClient.getAccessToken();
      const res = await fetch(apiUrl("/crm/lead-finder/export?limit=1000"), {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error(`Export failed (${res.status})`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `prospects_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      toast({ title: "Export failed", description: e?.message, variant: "destructive" });
    }
  }, [toast]);

  // â”€â”€ Map-ready prospects â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  const mappable = prospects.filter((p) => p.lat && p.lng);

  // â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  // Render
  // â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  return (
    <div className="space-y-5">
      <PageHeader
        icon={Search}
        title="Lead Finder"
        subtitle="Location intelligence · Prospect discovery · CRM ingest"
        actions={
          <Button variant="outline" size="sm" className="gap-1.5" onClick={() => void handleExport()}>
            <Download className="h-4 w-4" /> Export CSV
          </Button>
        }
      />

      <KpiStrip
        items={[
          { label: "Prospects", value: prospects.length },
          { label: "Converted", value: prospects.filter((p) => p.status === "converted").length, tone: "success" },
          { label: "Follow-ups", value: followups.length },
        ]}
      />

      {showMap && (
        <Card>
          <CardContent className="p-0">
            <div className="rounded-lg overflow-hidden h-[400px]">
              {mappable.length === 0 ? (
                <div className="h-full flex items-center justify-center text-sm text-muted-foreground bg-muted/30">
                  <AlertCircle className="h-5 w-5 mr-2" />
                  No prospects with GPS coordinates yet. Run a search first.
                </div>
              ) : (
                <MapContainer
                  center={[mappable[0].lat!, mappable[0].lng!]}
                  zoom={12}
                  style={{ height: "100%", width: "100%" }}
                  scrollWheelZoom
                >
                  <TileLayer
                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                    attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                  />
                  {mappable.map((p) => (
                    <Marker key={p.id} position={[p.lat!, p.lng!]}>
                      <Popup>
                        <div className="text-sm space-y-1 min-w-[160px]">
                          <p className="font-semibold">{p.company_name}</p>
                          {p.formatted_address && (
                            <p className="text-xs text-muted-foreground">{p.formatted_address}</p>
                          )}
                          {p.rating && <p className="text-xs">★ {p.rating}</p>}
                          {(p.phone_number || p.contact_phone) && (
                            <p className="text-xs">{p.phone_number || p.contact_phone}</p>
                          )}
                          <p className="text-xs font-medium">Score: {p.places_score ?? p.score ?? 0}</p>
                        </div>
                      </Popup>
                    </Marker>
                  ))}
                </MapContainer>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      <Tabs defaultValue="prospects">
        <TabsList>
          <TabsTrigger value="prospects" className="gap-1.5">
            <Zap className="h-4 w-4" /> Prospects
          </TabsTrigger>
          <TabsTrigger value="followups" className="gap-1.5">
            <ClipboardList className="h-4 w-4" /> Follow-ups
          </TabsTrigger>
        </TabsList>

        {/* ── PROSPECTS TAB — full retrofit: merges the old Discover +
            Pipeline tabs into one List/Detail/QuickActions layout. Selecting
            a prospect used to hand off to a different tab via a raw text ID
            field with no name/context shown — the Detail Workspace now shows
            full prospect detail (including contact_name/contact_email/
            industry/region, previously fetched but never displayed) plus the
            Score+Ingest or Assign form inline, in place. See
            ACE-Workspace-Standard.md §9.8. */}
        <TabsContent value="prospects" className="mt-4">
          <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr_240px] gap-4">
            {/* List Panel */}
            <Card className="lg:max-h-[600px] flex flex-col">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Prospects ({prospects.length})</CardTitle>
              </CardHeader>
              <CardContent className="overflow-y-auto space-y-2 flex-1">
                {pipelineQuery.isLoading ? (
                  <div className="flex items-center justify-center py-12">
                    <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                  </div>
                ) : prospects.length === 0 ? (
                  <div className="text-center py-12 text-muted-foreground text-sm">
                    No prospects yet. Use "Find New Leads" to search.
                  </div>
                ) : (
                  prospects.map((p) => {
                    const displayScore = p.places_score ?? p.score ?? 0;
                    return (
                      <button
                        key={p.id}
                        onClick={() => selectProspect(p)}
                        className={`w-full text-left rounded-lg border px-3 py-2.5 hover:bg-muted/40 transition-colors ${
                          selectedProspectId === String(p.id) ? "border-primary bg-muted/40" : ""
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium text-sm truncate">{p.company_name}</span>
                          <Badge variant="outline" className={`text-xs shrink-0 ${scoreColor(displayScore)}`}>
                            {displayScore}
                          </Badge>
                        </div>
                        <div className="flex items-center gap-2 mt-1">
                          <Badge variant="secondary" className="text-xs capitalize">{p.status}</Badge>
                          {p.converted_lead_id && (
                            <Badge className="text-xs bg-green-500/20 text-green-400 border-green-500/30">
                              <CheckCircle2 className="h-3 w-3 mr-1" /> In CRM
                            </Badge>
                          )}
                        </div>
                      </button>
                    );
                  })
                )}
              </CardContent>
            </Card>

            {/* Detail Workspace — inline, no dismiss button (Ch.5.1). */}
            <Card>
              <CardContent className="pt-6">
                {!selected && (
                  <p className="text-sm text-muted-foreground text-center py-12">Select a prospect to view details.</p>
                )}
                {selected && (
                  <div className="space-y-4 text-sm">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="font-bold text-lg">{selected.company_name}</div>
                        {selected.formatted_address && (
                          <div className="text-xs text-muted-foreground flex items-center gap-1 mt-0.5">
                            <MapPin className="h-3 w-3" /> {selected.formatted_address}
                          </div>
                        )}
                      </div>
                      <Badge variant="outline" className={scoreColor(selected.places_score ?? selected.score ?? 0)}>
                        {selected.places_score ?? selected.score ?? 0}
                      </Badge>
                    </div>

                    <div className="grid grid-cols-2 gap-2">
                      {[
                        ["Industry", selected.industry],
                        ["Region", selected.region],
                        ["Contact", selected.contact_name],
                        ["Contact Email", selected.contact_email],
                        ["Phone", selected.phone_number || selected.contact_phone],
                        ["Website", selected.website],
                      ].map(([label, value]) => (
                        <div key={String(label)} className="space-y-0.5">
                          <div className="text-xs text-muted-foreground">{label}</div>
                          <div className="text-xs font-medium truncate">{value || "—"}</div>
                        </div>
                      ))}
                    </div>

                    <div className="flex items-center gap-3 flex-wrap">
                      {renderStars(selected.rating)}
                      {selected.user_ratings_total && (
                        <span className="text-xs text-muted-foreground">({selected.user_ratings_total} ratings)</span>
                      )}
                      {selected.source === "mock" && (
                        <Badge variant="outline" className="text-xs text-yellow-400 border-yellow-400/30">mock data</Badge>
                      )}
                      {selected.source === "openstreetmap" && (
                        <Badge variant="outline" className="text-xs text-blue-400 border-blue-400/30">OSM</Badge>
                      )}
                    </div>

                    <Separator />

                    {!selected.converted_lead_id ? (
                      <div className="space-y-2 border rounded-lg p-3 bg-muted/30">
                        <div className="text-xs font-semibold text-muted-foreground">SCORE + INGEST TO CRM</div>
                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <Label className="text-xs text-muted-foreground mb-1 block">Expected Value (₦)</Label>
                            <Input type="number" value={expectedValue} onChange={(e) => setExpectedValue(Number(e.target.value) || 0)} />
                          </div>
                          <div>
                            <Label className="text-xs text-muted-foreground mb-1 block">Urgency</Label>
                            <Select value={urgency} onValueChange={(v) => setUrgency(v as "low" | "medium" | "high")}>
                              <SelectTrigger><SelectValue /></SelectTrigger>
                              <SelectContent>
                                <SelectItem value="low">Low</SelectItem>
                                <SelectItem value="medium">Medium</SelectItem>
                                <SelectItem value="high">High</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>
                        </div>
                        <Button size="sm" className="w-full gap-2" disabled={scoreMutation.isPending} onClick={() => scoreMutation.mutate()}>
                          {scoreMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
                          Score + Ingest
                        </Button>
                      </div>
                    ) : (
                      <div className="space-y-2 border rounded-lg p-3 bg-muted/30">
                        <div className="text-xs font-semibold text-muted-foreground">ASSIGN TO REVENUE OFFICER</div>
                        <div>
                          <Label className="text-xs text-muted-foreground mb-1 block">Revenue Officer</Label>
                          <EntityAutocomplete<{ id: string; email: string; roles: string[] }>
                            placeholder="Search by email…"
                            fetchFn={(q) =>
                              api.users.list(200).then((users: any[]) =>
                                users.filter((u) => (u.email || "").toLowerCase().includes(q.toLowerCase())),
                              )
                            }
                            getKey={(u) => u.id}
                            getLabel={(u) => u.email}
                            getSubtitle={(u) => u.roles?.join(", ")}
                            onSelect={(u) => setRepUserId(u.id)}
                          />
                          {repUserId && <p className="text-xs text-muted-foreground mt-1">Selected: {repUserId}</p>}
                        </div>
                        <div>
                          <Label className="text-xs text-muted-foreground mb-1 block">Follow-up (hours)</Label>
                          <Input type="number" value={followUpHours} onChange={(e) => setFollowUpHours(Number(e.target.value) || 24)} />
                        </div>
                        <Button
                          size="sm" className="w-full gap-2"
                          disabled={!assignLeadId || !repUserId.trim() || assignMutation.isPending}
                          onClick={() => assignMutation.mutate()}
                        >
                          {assignMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Users className="h-4 w-4" />}
                          Assign Lead
                        </Button>
                      </div>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Quick Actions */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Quick Actions</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <Button className="w-full" size="sm" onClick={() => setFindOpen(true)}>
                  <Plus className="h-4 w-4 mr-1" /> Find New Leads
                </Button>
                <Button variant="outline" className="w-full" size="sm" onClick={() => setShowMap((v) => !v)}>
                  <MapIcon className="h-4 w-4 mr-1" /> {showMap ? "Hide Map" : "Show Map"}
                </Button>
                <Button variant="outline" className="w-full" size="sm" onClick={() => void handleExport()}>
                  <Download className="h-4 w-4 mr-1" /> Export CSV
                </Button>
                <Button
                  variant="outline" className="w-full" size="sm"
                  onClick={() => pipelineQuery.refetch()} disabled={pipelineQuery.isFetching}
                >
                  <RefreshCw className={`h-4 w-4 mr-1 ${pipelineQuery.isFetching ? "animate-spin" : ""}`} /> Refresh
                </Button>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* â”€â”€ FOLLOW-UPS TAB â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
        <TabsContent value="followups" className="mt-4">
          <motion.div {...motionVariants.cardEnter}>
            {followups.length === 0 ? (
              <Card>
                <CardContent className="py-12 text-center text-muted-foreground text-sm">
                  <ClipboardList className="h-8 w-8 mx-auto mb-3 opacity-40" />
                  No follow-ups yet. Assign a lead to create one automatically.
                </CardContent>
              </Card>
            ) : (
              <div className="space-y-3">
                {followups.map((f) => (
                  <Card key={f.id} className="border-border/60">
                    <CardContent className="p-4 flex items-center justify-between gap-3 flex-wrap">
                      <div className="space-y-0.5">
                        <p className="text-sm font-medium">Lead #{f.lead_id}</p>
                        <div className="flex items-center gap-3 text-xs text-muted-foreground">
                          <span>Assigned to: {f.assigned_to}</span>
                          {f.follow_up_type && (
                            <Badge variant="outline" className="text-xs capitalize">
                              {f.follow_up_type}
                            </Badge>
                          )}
                        </div>
                        {f.due_at && (
                          <p className="text-xs text-muted-foreground">
                            Due: {new Date(f.due_at).toLocaleString()}
                          </p>
                        )}
                        {f.notes && (
                          <p className="text-xs text-muted-foreground italic">{f.notes}</p>
                        )}
                      </div>
                      <Badge
                        className={`text-xs ${
                          f.status === "done"
                            ? "bg-green-500/20 text-green-400"
                            : f.status === "overdue"
                            ? "bg-red-500/20 text-red-400"
                            : "bg-blue-500/20 text-blue-400"
                        }`}
                      >
                        {f.status}
                      </Badge>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </motion.div>
        </TabsContent>
      </Tabs>

      {/* Find New Leads — ephemeral act flow that produces new list rows,
          DetailSheet per Ch.5.2 (same reasoning as CAPA's "New Deviation"). */}
      <DetailSheet
        open={findOpen}
        onOpenChange={setFindOpen}
        title="Find New Leads"
        description="Powered by OpenStreetMap (free) · Google Places when API key is set · mock data offline"
        icon={Search}
        footer={
          <Button
            className="w-full gap-2"
            disabled={!location.trim() || searchMutation.isPending}
            onClick={() => searchMutation.mutate()}
          >
            {searchMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            {searchMutation.isPending ? "Searching…" : "Find Leads"}
          </Button>
        }
      >
        <div className="space-y-3">
          <div className="space-y-1">
            <Label>Location</Label>
            <Input placeholder="e.g. Lekki, Lagos" value={location} onChange={(e) => setLocation(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label>Business Type</Label>
            <Input placeholder="e.g. pharmacy" value={businessType} onChange={(e) => setBusinessType(e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Radius (km)</Label>
              <Input type="number" min={1} max={50} value={radiusKm} onChange={(e) => setRadiusKm(Number(e.target.value) || 5)} />
            </div>
            <div className="space-y-1">
              <Label>Limit</Label>
              <Input type="number" min={1} max={60} value={searchLimit} onChange={(e) => setSearchLimit(Number(e.target.value) || 20)} />
            </div>
          </div>
        </div>
      </DetailSheet>
    </div>
  );
}


