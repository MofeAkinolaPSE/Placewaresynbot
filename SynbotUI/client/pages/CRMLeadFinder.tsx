/**
 * CRM › Leads & Prospecting (the old Lead Finder and Leads pages, combined).
 *   Find prospects  real businesses near the rep (GPS or a typed area), nearest first, exactly as
 *                   many as asked - nothing is stored until the rep acts on one.
 *   Worked          prospects the team has saved, called or turned down.
 *   Website         enquiries from the website form.
 * "Add to pipeline" makes a New lead on the Sales Pipeline. Existing customers are flagged, not
 * offered as prospects. The old page listed 1,780 of our own Sage customers plus 12 mock places.
 */
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Crosshair, ExternalLink, Loader2, MapPin, Phone, Plus, Search, Target, ThumbsDown } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { PageHeader } from "@/components/workspace/PageHeader";
import { api } from "@/lib/api-client";
import { Dict, fmtDate, naira } from "@/lib/books-api";
import { NewDealSheet, StageChip, useCrmRefresh } from "@/components/crm/crm-kit";

const TYPES: [string, string][] = [["pharmacy", "Pharmacies"], ["hospital", "Hospitals"], ["clinic", "Clinics"], ["lab", "Laboratories"], ["distributor", "Medical suppliers"]];
const AREAS: Record<string, string[]> = {
  Lagos: ["Ikeja, Lagos", "Victoria Island, Lagos", "Lekki, Lagos", "Surulere, Lagos", "Yaba, Lagos", "Ikorodu, Lagos", "Festac, Lagos"],
  Abuja: ["Wuse, Abuja", "Garki, Abuja", "Maitama, Abuja", "Gwarinpa, Abuja", "Kubwa, Abuja"],
};
const km = (m?: number) => (m == null ? "" : m < 1000 ? `${m} m` : `${(m / 1000).toFixed(1)} km`);
const STATUS: Record<string, [string, string]> = {
  saved: ["Saved", "bg-sky-100 text-sky-700"], contacted: ["Contacted", "bg-violet-100 text-violet-700"],
  not_interested: ["Not interested", "bg-muted text-muted-foreground"], converted: ["In pipeline", "bg-emerald-100 text-emerald-700"],
};

export default function CRMLeadFinder() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "find";
  const [adding, setAdding] = useState<Dict | null>(null);
  return (
    <div className="space-y-5">
      <PageHeader icon={Target} title="Leads & Prospecting" subtitle="Find businesses near you, work them, and send the interested ones to the pipeline"
        actions={<Button onClick={() => setAdding({})}><Plus className="mr-1.5 h-4 w-4" />Add lead</Button>} />
      <Tabs value={tab} onValueChange={(t) => setParams({ tab: t }, { replace: true })}>
        <TabsList>
          <TabsTrigger value="find"><Search className="mr-1.5 h-4 w-4" />Find prospects</TabsTrigger>
          <TabsTrigger value="worked">Worked prospects</TabsTrigger>
          <TabsTrigger value="inbound">Website enquiries</TabsTrigger>
        </TabsList>
        <TabsContent value="find" className="mt-4"><Finder /></TabsContent>
        <TabsContent value="worked" className="mt-4"><Worked /></TabsContent>
        <TabsContent value="inbound" className="mt-4"><Inbound onAdd={setAdding} /></TabsContent>
      </Tabs>
      <NewDealSheet key={JSON.stringify(adding ?? {})} open={!!adding} defaults={adding ?? {}} onClose={() => setAdding(null)} />
    </div>
  );
}

// ---------------------------------------------------------------------------

function Finder() {
  const refresh = useCrmRefresh();
  const [mode, setMode] = useState<"gps" | "area">("area");
  const [coords, setCoords] = useState<{ lat: number; lng: number; acc?: number } | null>(null);
  const [locating, setLocating] = useState(false);
  const [area, setArea] = useState("Ikeja, Lagos");
  const [type, setType] = useState("pharmacy");
  const [radius, setRadius] = useState("5");
  const [limit, setLimit] = useState("10");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<Dict | null>(null);
  const [acting, setActing] = useState<{ place: Dict; kind: "call" | "pipeline" } | null>(null);

  const locate = () => {
    if (!navigator.geolocation) return toast.error("This browser cannot share its location");
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (p) => { setCoords({ lat: p.coords.latitude, lng: p.coords.longitude, acc: Math.round(p.coords.accuracy) }); setMode("gps"); setLocating(false); },
      (e) => { toast.error(e.code === 1 ? "Location permission was refused - type an area instead" : "Could not get your location"); setLocating(false); },
      { enableHighAccuracy: true, timeout: 15000 });
  };
  const search = async () => {
    setBusy(true);
    try {
      const r = await api.crmHub.search({ ...(mode === "gps" && coords ? { lat: coords.lat, lng: coords.lng } : { location: area }),
                                          business_type: type, radius_km: Number(radius), limit: Number(limit) });
      setRes(r);
    } catch (e: any) { toast.error(e?.message ?? "Search failed"); }
    setBusy(false);
  };
  const setPlace = (pid: string, patch: Dict) => setRes((r) => r && { ...r, places: r.places.map((p: Dict) => (p.place_id === pid ? { ...p, ...patch } : p)) });
  const quick = async (place: Dict, status: string) => {
    try { const r = await api.crmHub.saveProspect(place, status); setPlace(place.place_id, { status, prospect_id: r.prospect_id }); toast.success(STATUS[status][0]); refresh(); }
    catch (e: any) { toast.error(e?.message); }
  };

  return (
    <div className="space-y-4">
      <Card><CardContent className="grid gap-3 p-4 md:grid-cols-[1.4fr_1fr_0.7fr_0.7fr_auto] md:items-end">
        <div className="space-y-1">
          <Label className="text-xs">Where</Label>
          <div className="flex gap-2">
            <Button type="button" variant={mode === "gps" ? "default" : "outline"} onClick={locate} disabled={locating} title="Use your current position">
              {locating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Crosshair className="h-4 w-4" />}</Button>
            {mode === "gps" && coords ? (
              <div className="flex h-9 flex-1 items-center justify-between rounded-md border bg-muted/40 px-3 text-sm">
                <span>My location <span className="text-xs text-muted-foreground">(±{coords.acc} m)</span></span>
                <button className="text-xs text-primary" onClick={() => setMode("area")}>type an area</button>
              </div>
            ) : (
              <>
                <Input list="areas" value={area} onChange={(e) => { setArea(e.target.value); setMode("area"); }} placeholder="Area, e.g. Ikeja, Lagos" />
                <datalist id="areas">{Object.values(AREAS).flat().map((a) => <option key={a} value={a} />)}</datalist>
              </>
            )}
          </div>
        </div>
        <div className="space-y-1"><Label className="text-xs">Looking for</Label>
          <Select value={type} onValueChange={setType}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{TYPES.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select></div>
        <div className="space-y-1"><Label className="text-xs">Within</Label>
          <Select value={radius} onValueChange={setRadius}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{["1", "2", "5", "10", "20"].map((r) => <SelectItem key={r} value={r}>{r} km</SelectItem>)}</SelectContent></Select></div>
        <div className="space-y-1"><Label className="text-xs">How many</Label>
          <Select value={limit} onValueChange={setLimit}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{["5", "10", "20", "30"].map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent></Select></div>
        <Button onClick={search} disabled={busy || (mode === "area" && !area.trim())}>{busy ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Search className="mr-1.5 h-4 w-4" />}Find</Button>
      </CardContent></Card>

      {!res && !busy && <p className="rounded-md border p-8 text-center text-sm text-muted-foreground">Choose where and what to look for. Results come from the live map, nearest first; nothing is added to the CRM until you act on a prospect.</p>}
      {busy && <p className="text-center text-sm text-muted-foreground">Searching the map… this can take up to half a minute.</p>}
      {res && !busy && (
        <>
          <p className="text-sm text-muted-foreground">
            {res.found} of {res.requested} requested · {TYPES.find(([v]) => v === res.business_type)?.[1].toLowerCase()} within {res.radius_m / 1000} km of {res.origin_label}
            {res.found < res.requested && " - that is all the map has in this radius; widen it or try another area."}
            {res.source === "openstreetmap" && " · Source: OpenStreetMap (phone numbers are often missing there)."}
          </p>
          <div className="space-y-2">
            {res.places.map((p: Dict) => (
              <Card key={p.place_id} className={p.customer ? "border-emerald-300 dark:border-emerald-500/30" : undefined}>
                <CardContent className="flex flex-wrap items-center justify-between gap-3 p-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{p.company_name}</span>
                      <span className="text-xs text-muted-foreground">{km(p.distance_m)}</span>
                      {p.customer && <Badge variant="outline" className="border-emerald-400 text-[10px] text-emerald-700">Already our customer</Badge>}
                      {p.lead && <StageChip stage={p.lead.stage} />}
                      {STATUS[p.status] && <span className={`rounded px-1.5 py-0.5 text-[10px] ${STATUS[p.status][1]}`}>{STATUS[p.status][0]}</span>}
                    </div>
                    <div className="text-xs text-muted-foreground">{p.formatted_address || "Address not listed"}{p.opening_hours ? ` · ${p.opening_hours}` : ""}</div>
                    <div className="mt-0.5 flex flex-wrap gap-3 text-xs">
                      {p.phone_number ? <a href={`tel:${p.phone_number}`} className="inline-flex items-center text-primary"><Phone className="mr-1 h-3 w-3" />{p.phone_number}</a>
                        : <span className="text-muted-foreground">No phone listed</span>}
                      {p.website && <a href={p.website} target="_blank" rel="noreferrer" className="inline-flex items-center text-primary"><ExternalLink className="mr-1 h-3 w-3" />Website</a>}
                      <a href={`https://www.openstreetmap.org/?mlat=${p.lat}&mlon=${p.lng}#map=18/${p.lat}/${p.lng}`} target="_blank" rel="noreferrer" className="inline-flex items-center text-primary">
                        <MapPin className="mr-1 h-3 w-3" />Map</a>
                    </div>
                  </div>
                  {!p.customer && p.status !== "converted" && !p.lead && (
                    <div className="flex shrink-0 flex-wrap gap-1">
                      {p.status === "new" && <Button size="sm" variant="ghost" onClick={() => quick(p, "saved")}>Save</Button>}
                      <Button size="sm" variant="outline" onClick={() => setActing({ place: p, kind: "call" })}><Phone className="mr-1 h-3.5 w-3.5" />Log call</Button>
                      <Button size="sm" onClick={() => setActing({ place: p, kind: "pipeline" })}><Plus className="mr-1 h-3.5 w-3.5" />Add to pipeline</Button>
                    </div>
                  )}
                  {p.customer && <Link to="/customers/workspace" className="text-xs text-primary hover:underline">Customer workspace</Link>}
                </CardContent>
              </Card>
            ))}
          </div>
        </>
      )}
      <ActSheet acting={acting} onClose={() => setActing(null)} onDone={(pid, patch) => setPlace(pid, patch)} />
    </div>
  );
}

function ActSheet({ acting, onClose, onDone }: { acting: { place: Dict; kind: "call" | "pipeline" } | null; onClose: () => void; onDone: (pid: string, patch: Dict) => void }) {
  const refresh = useCrmRefresh();
  const [f, setF] = useState({ note: "", contact_person: "", contact_phone: "", expected_value: "", next_action: "" });
  const [busy, setBusy] = useState(false);
  const p = acting?.place;
  const toPipeline = async () => {
    setBusy(true);
    try {
      const r = await api.crmHub.prospectToPipeline(p!, { contact_person: f.contact_person || undefined, contact_phone: f.contact_phone || p!.phone_number || undefined,
        expected_value: f.expected_value ? Number(f.expected_value) : undefined, notes: f.note || undefined, next_action: f.next_action || undefined });
      toast.success(`${p!.company_name} added to the pipeline as a New lead`);
      onDone(p!.place_id, { status: "converted", lead: { id: r.id, stage: "new" } }); refresh(); onClose();
    } catch (e: any) { toast.error(e?.message); }
    setBusy(false);
  };
  const logCall = async (status: "contacted" | "not_interested") => {
    setBusy(true);
    try { const r = await api.crmHub.saveProspect(p!, status, f.note || undefined); onDone(p!.place_id, { status, prospect_id: r.prospect_id });
      toast.success(status === "contacted" ? "Call logged" : "Marked not interested"); refresh(); onClose(); } catch (e: any) { toast.error(e?.message); }
    setBusy(false);
  };
  return (
    <DetailSheet open={!!acting} onOpenChange={(o) => !o && onClose()} title={p?.company_name ?? ""} description={p ? `${km(p.distance_m)} · ${p.formatted_address ?? ""}` : undefined}>
      {p && (
        <div className="space-y-3 text-sm">
          {p.phone_number && <a href={`tel:${p.phone_number}`} className="inline-flex items-center text-primary"><Phone className="mr-1 h-4 w-4" />Call {p.phone_number}</a>}
          {acting!.kind === "call" ? (
            <>
              <div className="space-y-1"><Label className="text-xs">What did they say?</Label><Textarea rows={3} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></div>
              <div className="grid grid-cols-2 gap-2">
                <Button variant="outline" disabled={busy} onClick={() => logCall("contacted")}>Called - follow up later</Button>
                <Button variant="ghost" className="text-red-600" disabled={busy} onClick={() => logCall("not_interested")}><ThumbsDown className="mr-1 h-4 w-4" />Not interested</Button>
              </div>
              <Button className="w-full" disabled={busy} onClick={toPipeline}>Interested - add to pipeline</Button>
            </>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1"><Label className="text-xs">Contact person</Label><Input value={f.contact_person} onChange={(e) => setF({ ...f, contact_person: e.target.value })} /></div>
                <div className="space-y-1"><Label className="text-xs">Phone</Label><Input value={f.contact_phone} placeholder={p.phone_number ?? ""} onChange={(e) => setF({ ...f, contact_phone: e.target.value })} /></div>
                <div className="space-y-1"><Label className="text-xs">Expected value (₦)</Label><Input type="number" value={f.expected_value} onChange={(e) => setF({ ...f, expected_value: e.target.value })} /></div>
                <div className="space-y-1"><Label className="text-xs">Next step</Label><Input value={f.next_action} onChange={(e) => setF({ ...f, next_action: e.target.value })} /></div>
              </div>
              <div className="space-y-1"><Label className="text-xs">Notes</Label><Textarea rows={2} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></div>
              <Button className="w-full" disabled={busy} onClick={toPipeline}>{busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Add to pipeline</Button>
            </>
          )}
        </div>
      )}
    </DetailSheet>
  );
}

// ---------------------------------------------------------------------------

function Worked() {
  const refresh = useCrmRefresh();
  const [status, setStatus] = useState<string>("");
  const [acting, setActing] = useState<{ place: Dict; kind: "call" | "pipeline" } | null>(null);
  const { data = [], isLoading, refetch } = useQuery({ queryKey: ["crm-hub", "prospects", status], queryFn: () => api.crmHub.prospects(status || undefined) });
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {[["", "All"], ["saved", "Saved"], ["contacted", "Contacted"], ["converted", "In pipeline"], ["not_interested", "Not interested"]].map(([k, l]) =>
          <Button key={k} size="sm" className="h-8" variant={status === k ? "default" : "outline"} onClick={() => setStatus(k)}>{l}</Button>)}
      </div>
      <Card><CardContent className="p-0">
        {isLoading ? <Loader2 className="m-6 mx-auto h-6 w-6 animate-spin" /> : data.length === 0 ? (
          <p className="p-6 text-center text-sm text-muted-foreground">No prospects worked yet. Find prospects near you and save, call or add them.</p>
        ) : (
          <Table><TableHeader><TableRow><TableHead>Prospect</TableHead><TableHead>Status</TableHead><TableHead>Phone</TableHead><TableHead>Last note</TableHead><TableHead>Rep</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>{data.map((p: Dict) => (
              <TableRow key={p.id}>
                <TableCell><div className="font-medium">{p.company_name}</div><div className="text-[11px] text-muted-foreground">{p.formatted_address || p.search_query}</div></TableCell>
                <TableCell>{STATUS[p.status] && <span className={`rounded px-1.5 py-0.5 text-[11px] ${STATUS[p.status][1]}`}>{STATUS[p.status][0]}</span>}
                  {p.lead_stage && <div className="mt-0.5"><StageChip stage={p.lead_stage} /></div>}</TableCell>
                <TableCell className="text-xs">{p.phone_number || p.contact_phone ? <a className="text-primary" href={`tel:${p.phone_number || p.contact_phone}`}>{p.phone_number || p.contact_phone}</a> : "—"}</TableCell>
                <TableCell className="max-w-[240px] truncate text-xs">{p.last_note ?? "—"}{p.contacted_at && <div className="text-[11px] text-muted-foreground">{fmtDate(p.contacted_at)}</div>}</TableCell>
                <TableCell className="text-xs">{p.rep_name ?? "—"}</TableCell>
                <TableCell className="whitespace-nowrap text-right">{p.status !== "converted" && (
                  <Button size="sm" variant="outline" onClick={() => setActing({ place: { ...p, prospect_id: p.id }, kind: "pipeline" })}>Add to pipeline</Button>)}</TableCell>
              </TableRow>))}</TableBody></Table>)}
      </CardContent></Card>
      <ActSheet acting={acting} onClose={() => setActing(null)} onDone={() => { refetch(); refresh(); }} />
    </div>
  );
}

function Inbound({ onAdd }: { onAdd: (d: Dict) => void }) {
  const { data = [], isLoading } = useQuery({ queryKey: ["crm-hub", "inbound"], queryFn: () => api.crmHub.inbound() });
  return (
    <Card><CardContent className="p-0">
      {isLoading ? <Loader2 className="m-6 mx-auto h-6 w-6 animate-spin" /> : data.length === 0 ? <p className="p-6 text-center text-sm text-muted-foreground">No website enquiries.</p> : (
        <Table><TableHeader><TableRow><TableHead>From</TableHead><TableHead>Contact</TableHead><TableHead>Message</TableHead><TableHead>Received</TableHead><TableHead /></TableRow></TableHeader>
          <TableBody>{data.map((x: Dict) => (
            <TableRow key={x.id}>
              <TableCell className="font-medium">{x.name}</TableCell>
              <TableCell className="text-xs">{x.phone && <a className="block text-primary" href={`tel:${x.phone}`}>{x.phone}</a>}{x.email}</TableCell>
              <TableCell className="max-w-[300px] truncate text-xs">{x.message || x.service || "—"}</TableCell>
              <TableCell className="text-xs">{fmtDate(x.created_at)}</TableCell>
              <TableCell className="text-right">{x.lead_id ? <Badge variant="outline">In pipeline</Badge> : (
                <Button size="sm" onClick={() => onAdd({ company_name: x.name, contact_person: x.name, contact_phone: x.phone ?? "", source: "website",
                                                         notes: x.message ?? "", contact_email: x.email, inbound_id: String(x.id) })}>Add to pipeline</Button>)}</TableCell>
            </TableRow>))}</TableBody></Table>)}
    </CardContent></Card>
  );
}

export { naira };
