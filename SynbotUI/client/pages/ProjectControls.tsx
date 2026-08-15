import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PlusCircle, Loader2, ArrowRight, ClipboardList } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api-client";
import { useToast } from "@/hooks/use-toast";
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";
import { ChevronDown } from "lucide-react";
import { PageHeader } from "@/components/workspace/PageHeader";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { FilterBar } from "@/components/workspace/FilterBar";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { EntityAutocomplete } from "@/components/workspace/EntityAutocomplete";

const STAGE_LABELS: Record<string, { label: string; department: string }> = {
  port_clearing: { label: "Port Clearing", department: "Logistics" },
  anti_room_received: { label: "Anti-room Receipt", department: "Inventory + QC" },
  cold_room_stacked: { label: "Cold Room Stacked", department: "Quality Control" },
  nafdac_sampling: { label: "NAFDAC Sampling", department: "Quality Control + Regulatory" },
  released_for_issuing: { label: "Released for Issuing", department: "Finance + Operations" },
  packaging_for_delivery: { label: "Packaging for Delivery", department: "Operations" },
  delivered_to_end_users: { label: "Delivered to End Users", department: "Logistics" },
};

const STAGE_TRANSITIONS: Record<string, string[]> = {
  port_clearing: ["anti_room_received"],
  anti_room_received: ["cold_room_stacked", "port_clearing"],
  cold_room_stacked: ["nafdac_sampling", "anti_room_received"],
  nafdac_sampling: ["released_for_issuing", "cold_room_stacked"],
  released_for_issuing: ["packaging_for_delivery", "nafdac_sampling"],
  packaging_for_delivery: ["delivered_to_end_users", "released_for_issuing"],
  delivered_to_end_users: [],
};

const QC_STATUSES = ["pending", "in_review", "passed", "failed", "waived"] as const;
const NAFDAC_STATUSES = ["pending", "in_progress", "released"] as const;

interface Project {
  id: string;
  name: string;
  description?: string;
  status: string;
  created_at?: string;
  owner_id?: string;
  activity_type?: string;
  supplier_name?: string;
  assigned_staff_id?: string;
  workflow_stage?: string;
  po_reference?: string;
  temperature_profile?: string;
  nafdac_sampling_status?: string;
  quality_check_status?: string;
  quality_notes?: string;
  quality_checked_by?: string;
  quality_checked_at?: string;
}

interface SupplierOption {
  id?: string;
  name: string;
}

export default function ProjectControls() {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [newProject, setNewProject] = useState({
    name: "",
    description: "",
    status: "active",
    activity_type: "restock",
    supplier_name: "",
    assigned_staff_id: "",
    workflow_stage: "anti_room_received",
    po_reference: "",
    temperature_profile: "2-8C",
    nafdac_sampling_status: "pending",
    quality_check_status: "pending",
    quality_notes: "",
  });
  const [movingProjectId, setMovingProjectId] = useState<string | null>(null);
  const [stageDrafts, setStageDrafts] = useState<Record<string, {
    workflow_stage: string;
    quality_check_status: string;
    nafdac_sampling_status: string;
    quality_notes: string;
  }>>({});
  const { toast } = useToast();

  const { data: projects = [], isLoading: loading } = useQuery({
    queryKey: ["controls-projects"],
    queryFn: () => api.projects.list(50),
  });

  const { data: readiness, isLoading: controlsReadyLoading } = useQuery({
    queryKey: ["controls-readiness"],
    queryFn: () => api.projects.readiness(),
  });
  const controlsReady = controlsReadyLoading ? true : Boolean(readiness?.ready);
  const controlsReadyReason = readiness?.ready ? null : (readiness?.reason || "Project workflow schema is not ready yet.");

  const { data: staffRows } = useQuery({
    queryKey: ["staff-options"],
    queryFn: () => api.staff.list(),
  });
  const staffOptions = useMemo(
    () => (staffRows || [])
      .filter((row: any) => typeof row?.staff_id === "string" && typeof row?.full_name === "string")
      .map((row: any) => ({ staff_id: row.staff_id as string, full_name: row.full_name as string })),
    [staffRows],
  );

  const { data: supplierRows } = useQuery({
    queryKey: ["supplier-options"],
    queryFn: () => api.suppliers.list(),
  });
  const supplierOptions: SupplierOption[] = useMemo(
    () => (supplierRows || [])
      .filter((row: any) => typeof row?.name === "string")
      .map((row: any) => ({ id: row.id as string | undefined, name: row.name as string })),
    [supplierRows],
  );

  const createProject = useMutation({
    mutationFn: () => api.projects.create(newProject),
    onSuccess: () => {
      toast({ title: "Project Created", description: `"${newProject.name}" has been created.` });
      setDialogOpen(false);
      setNewProject({
        name: "",
        description: "",
        status: "active",
        activity_type: "restock",
        supplier_name: "",
        assigned_staff_id: "",
        workflow_stage: "anti_room_received",
        po_reference: "",
        temperature_profile: "2-8C",
        nafdac_sampling_status: "pending",
        quality_check_status: "pending",
        quality_notes: "",
      });
      void queryClient.invalidateQueries({ queryKey: ["controls-projects"] });
    },
    onError: (err: any) => toast({ title: "Create Failed", description: err.message, variant: "destructive" }),
  });

  const handleCreate = () => {
    if (!controlsReady) {
      toast({ title: "Workflow not ready", description: controlsReadyReason || "Backend schema is not ready for project actions.", variant: "destructive" });
      return;
    }
    if (!newProject.name.trim()) {
      toast({ title: "Validation Error", description: "Project name is required", variant: "destructive" });
      return;
    }
    createProject.mutate();
  };

  const updateStageDraft = (project: Project, patch: Partial<{ workflow_stage: string; quality_check_status: string; nafdac_sampling_status: string; quality_notes: string }>) => {
    const currentStage = project.workflow_stage || "port_clearing";
    const fallbackTarget = STAGE_TRANSITIONS[currentStage]?.[0] || currentStage;
    const prev = stageDrafts[project.id] || {
      workflow_stage: fallbackTarget,
      quality_check_status: project.quality_check_status || "pending",
      nafdac_sampling_status: project.nafdac_sampling_status || "pending",
      quality_notes: project.quality_notes || "",
    };
    setStageDrafts((existing) => ({
      ...existing,
      [project.id]: {
        ...prev,
        ...patch,
      },
    }));
  };

  const moveProjectStage = async (project: Project) => {
    if (!controlsReady) {
      toast({ title: "Workflow not ready", description: controlsReadyReason || "Backend schema is not ready for stage transitions.", variant: "destructive" });
      return;
    }
    const currentStage = project.workflow_stage || "port_clearing";
    const draft = stageDrafts[project.id] || {
      workflow_stage: STAGE_TRANSITIONS[currentStage]?.[0] || currentStage,
      quality_check_status: project.quality_check_status || "pending",
      nafdac_sampling_status: project.nafdac_sampling_status || "pending",
      quality_notes: project.quality_notes || "",
    };
    if (!draft.workflow_stage || draft.workflow_stage === currentStage) {
      toast({ title: "No transition selected", description: "Choose a different stage before moving.", variant: "destructive" });
      return;
    }
    try {
      setMovingProjectId(project.id);
      await api.projects.transitionStage(project.id, {
        workflow_stage: draft.workflow_stage,
        quality_check_status: draft.quality_check_status,
        nafdac_sampling_status: draft.nafdac_sampling_status,
        quality_notes: draft.quality_notes,
        reason_code: "manual_board_transition",
      });
      toast({ title: "Stage updated", description: `${project.name} moved to ${STAGE_LABELS[draft.workflow_stage]?.label || draft.workflow_stage}.` });
      await queryClient.invalidateQueries({ queryKey: ["controls-projects"] });
    } catch (err: any) {
      toast({ title: "Transition blocked", description: err.message, variant: "destructive" });
    } finally {
      setMovingProjectId(null);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionTransitions.standard}
      className="pw-page-surface flex-1 space-y-4 p-8 pt-6"
    >
      <PageHeader
        icon={ClipboardList}
        title="Project Controls"
        subtitle="Projects · Stage Board · Deliveries · Stock Orders"
        actions={
          <Button disabled={!controlsReady || controlsReadyLoading} onClick={() => setDialogOpen(true)}>
            <PlusCircle className="mr-2 h-4 w-4" />
            New Project
          </Button>
        }
      />

      <DetailSheet
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        title="Create New Project"
        description="Enter the details for your new project."
        icon={ClipboardList}
        footer={
          <Button onClick={handleCreate} disabled={createProject.isPending} className="w-full">
            {createProject.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Create
          </Button>
        }
      >
        <div className="space-y-2">
          <Label htmlFor="name">Name</Label>
          <Input
            id="name"
            value={newProject.name}
            onChange={(e) => setNewProject({ ...newProject, name: e.target.value })}
            placeholder="Project name"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="description">Description</Label>
          <Textarea
            id="description"
            value={newProject.description}
            onChange={(e) => setNewProject({ ...newProject, description: e.target.value })}
            placeholder="Optional description"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="status">Status</Label>
          <Select
            value={newProject.status}
            onValueChange={(val) => setNewProject({ ...newProject, status: val })}
          >
            <SelectTrigger id="status">
              <SelectValue placeholder="Select status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="active">Active</SelectItem>
              <SelectItem value="planning">Planning</SelectItem>
              <SelectItem value="on_hold">On Hold</SelectItem>
              <SelectItem value="completed">Completed</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="activity_type">Activity</Label>
          <Select
            value={newProject.activity_type}
            onValueChange={(val) => setNewProject({ ...newProject, activity_type: val })}
          >
            <SelectTrigger id="activity_type">
              <SelectValue placeholder="Select activity type" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="restock">Restock</SelectItem>
              <SelectItem value="qc">QC</SelectItem>
              <SelectItem value="delivery">Delivery</SelectItem>
              <SelectItem value="client_request">Client Request</SelectItem>
              <SelectItem value="cold_chain">Cold Chain</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label>Supplier</Label>
          <EntityAutocomplete<SupplierOption>
            placeholder="Search suppliers..."
            fetchFn={(q) => Promise.resolve(supplierOptions.filter((s) => s.name.toLowerCase().includes(q.toLowerCase())))}
            getKey={(s) => s.id ?? s.name}
            getLabel={(s) => s.name}
            onSelect={(s) => setNewProject({ ...newProject, supplier_name: s.name })}
          />
          {newProject.supplier_name && (
            <p className="text-xs text-muted-foreground">
              Selected: {newProject.supplier_name}{" "}
              <button type="button" className="underline" onClick={() => setNewProject({ ...newProject, supplier_name: "" })}>clear</button>
            </p>
          )}
        </div>
        <div className="space-y-2">
          <Label>In Charge</Label>
          <EntityAutocomplete<{ staff_id: string; full_name: string }>
            placeholder="Search staff..."
            fetchFn={(q) => Promise.resolve(staffOptions.filter((s) => s.full_name.toLowerCase().includes(q.toLowerCase())))}
            getKey={(s) => s.staff_id}
            getLabel={(s) => s.full_name}
            onSelect={(s) => setNewProject({ ...newProject, assigned_staff_id: s.staff_id })}
          />
          {newProject.assigned_staff_id && (
            <p className="text-xs text-muted-foreground">
              Selected: {staffOptions.find((s) => s.staff_id === newProject.assigned_staff_id)?.full_name ?? newProject.assigned_staff_id}{" "}
              <button type="button" className="underline" onClick={() => setNewProject({ ...newProject, assigned_staff_id: "" })}>clear</button>
            </p>
          )}
        </div>
        <div className="space-y-2">
          <Label htmlFor="workflow_stage">Workflow Stage</Label>
          <Select
            value={newProject.workflow_stage}
            onValueChange={(val) => setNewProject({ ...newProject, workflow_stage: val })}
          >
            <SelectTrigger id="workflow_stage">
              <SelectValue placeholder="Select workflow stage" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="port_clearing">Port Clearing</SelectItem>
              <SelectItem value="anti_room_received">Anti-room Receipt (Inventory/QC)</SelectItem>
              <SelectItem value="cold_room_stacked">Stacked in Cold Room</SelectItem>
              <SelectItem value="nafdac_sampling">NAFDAC Sampling</SelectItem>
              <SelectItem value="released_for_issuing">Released for Invoicing/Issuing</SelectItem>
              <SelectItem value="packaging_for_delivery">Packaging for Delivery</SelectItem>
              <SelectItem value="delivered_to_end_users">Delivered to End Users</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="po_reference">PO Reference</Label>
          <Input
            id="po_reference"
            value={newProject.po_reference}
            onChange={(e) => setNewProject({ ...newProject, po_reference: e.target.value })}
            placeholder="Purchase order reference"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="temperature_profile">Temp Profile</Label>
          <Input
            id="temperature_profile"
            value={newProject.temperature_profile}
            onChange={(e) => setNewProject({ ...newProject, temperature_profile: e.target.value })}
            placeholder="e.g. 2-8C"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="nafdac_sampling_status">NAFDAC</Label>
          <Select
            value={newProject.nafdac_sampling_status}
            onValueChange={(val) => setNewProject({ ...newProject, nafdac_sampling_status: val })}
          >
            <SelectTrigger id="nafdac_sampling_status">
              <SelectValue placeholder="Select NAFDAC status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="pending">Pending Sampling</SelectItem>
              <SelectItem value="in_progress">Sampling In Progress</SelectItem>
              <SelectItem value="released">Released</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="quality_check_status">QC Status</Label>
          <Select
            value={newProject.quality_check_status}
            onValueChange={(val) => setNewProject({ ...newProject, quality_check_status: val })}
          >
            <SelectTrigger id="quality_check_status">
              <SelectValue placeholder="Select QC status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="pending">Pending</SelectItem>
              <SelectItem value="in_review">In Review</SelectItem>
              <SelectItem value="passed">Passed</SelectItem>
              <SelectItem value="failed">Failed</SelectItem>
              <SelectItem value="waived">Waived</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </DetailSheet>

      {controlsReadyLoading ? (
        <Card className="pw-surface-interactive">
          <CardContent className="py-3 text-sm text-muted-foreground">Checking project workflow readiness...</CardContent>
        </Card>
      ) : !controlsReady ? (
        <Card className="pw-surface-interactive border-warning/40">
          <CardContent className="py-3 text-sm text-warning">
            Project actions are temporarily disabled: {controlsReadyReason || "workflow schema not ready"}.
          </CardContent>
        </Card>
      ) : null}
      <Tabs defaultValue="projects" className="space-y-4">
        <TabsList>
          <TabsTrigger value="projects">Active Projects</TabsTrigger>
          <TabsTrigger value="stage_board">Stage Board</TabsTrigger>
          <TabsTrigger value="deliveries">Deliveries</TabsTrigger>
          <TabsTrigger value="stock_orders">Stock Orders</TabsTrigger>
        </TabsList>
        <TabsContent value="projects" className="space-y-4">
          <ProjectList
            projects={projects}
            loading={loading}
            controlsReady={controlsReady}
            movingProjectId={movingProjectId}
            stageDrafts={stageDrafts}
            onDraftChange={updateStageDraft}
            onMoveStage={moveProjectStage}
          />
        </TabsContent>
        <TabsContent value="stage_board" className="space-y-4">
          <Card className="pw-surface-interactive">
            <CardContent className="pt-5 pb-4 px-5">
              <StageTransitionBoard
                projects={projects}
                loading={loading}
                controlsReady={controlsReady}
                movingProjectId={movingProjectId}
                stageDrafts={stageDrafts}
                onDraftChange={updateStageDraft}
                onMoveStage={moveProjectStage}
              />
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="deliveries" className="space-y-4">
          <DeliveryList />
        </TabsContent>
        <TabsContent value="stock_orders" className="space-y-4">
          <StockOrderList />
        </TabsContent>
      </Tabs>
    </motion.div>
  );
}

function statusBadge(status: string) {
  switch (status) {
    case "active": return <Badge>Active</Badge>;
    case "planning": return <Badge variant="outline">Planning</Badge>;
    case "on_hold": return <Badge variant="secondary">On Hold</Badge>;
    case "completed": return <Badge className="border-success/30 bg-success/15 text-success">Completed</Badge>;
    default: return <Badge variant="outline">{status}</Badge>;
  }
}

// Active Projects — full retrofit (closest precedent: CapaTab). Several real
// fields were fetched but never rendered anywhere (quality_notes,
// nafdac_sampling_status, po_reference, temperature_profile,
// quality_checked_by/_at) — the textbook List/Detail/QuickActions gap. The
// stage-transition controls (previously only reachable from the Stage Board
// Kanban) are surfaced here too, including a quality_notes textarea that was
// wired through every transition call but never had a UI anywhere.
// See ACE-Workspace-Standard.md §9.10.
function ProjectList({
  projects,
  loading,
  controlsReady,
  movingProjectId,
  stageDrafts,
  onDraftChange,
  onMoveStage,
}: {
  projects: Project[];
  loading: boolean;
  controlsReady: boolean;
  movingProjectId: string | null;
  stageDrafts: Record<string, { workflow_stage: string; quality_check_status: string; nafdac_sampling_status: string; quality_notes: string }>;
  onDraftChange: (project: Project, patch: Partial<{ workflow_stage: string; quality_check_status: string; nafdac_sampling_status: string; quality_notes: string }>) => void;
  onMoveStage: (project: Project) => Promise<void>;
}) {
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return projects;
    return projects.filter((p) =>
      p.name.toLowerCase().includes(q) ||
      (p.supplier_name ?? "").toLowerCase().includes(q) ||
      (p.activity_type ?? "").toLowerCase().includes(q),
    );
  }, [projects, search]);

  const selected = useMemo(
    () => filtered.find((p) => p.id === selectedId) ?? null,
    [filtered, selectedId],
  );

  const kpis = useMemo(() => ({
    total: projects.length,
    active: projects.filter((p) => p.status === "active").length,
    planning: projects.filter((p) => p.status === "planning").length,
    completed: projects.filter((p) => p.status === "completed").length,
  }), [projects]);

  const currentStage = selected?.workflow_stage || "port_clearing";
  const nextOptions = STAGE_TRANSITIONS[currentStage] || [];
  const draft = selected ? (stageDrafts[selected.id] || {
    workflow_stage: nextOptions[0] || currentStage,
    quality_check_status: selected.quality_check_status || "pending",
    nafdac_sampling_status: selected.nafdac_sampling_status || "pending",
    quality_notes: selected.quality_notes || "",
  }) : null;
  const moving = selected ? movingProjectId === selected.id : false;

  return (
    <div className="space-y-4">
      <KpiStrip
        items={[
          { label: "Total Projects", value: kpis.total },
          { label: "Active", value: kpis.active },
          { label: "Planning", value: kpis.planning, tone: "warning" },
          { label: "Completed", value: kpis.completed, tone: "success" },
        ]}
      />

      <FilterBar search={{ value: search, onChange: setSearch, placeholder: "Filter projects..." }} />

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr_240px] gap-4">
        {/* List Panel */}
        <Card className="lg:max-h-[600px] flex flex-col">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Projects ({filtered.length})</CardTitle>
          </CardHeader>
          <CardContent className="overflow-y-auto space-y-2 flex-1">
            {loading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : filtered.length === 0 ? (
              <div className="text-center py-12 text-muted-foreground text-sm">No projects found.</div>
            ) : (
              filtered.map((p) => (
                <button
                  key={p.id}
                  onClick={() => setSelectedId(p.id)}
                  className={`w-full text-left rounded-lg border px-3 py-2.5 hover:bg-muted/40 transition-colors ${
                    selectedId === p.id ? "border-primary bg-muted/40" : ""
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-sm truncate">{p.name}</span>
                    {statusBadge(p.status)}
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground truncate">
                    {p.activity_type || "-"} · {p.supplier_name || "no supplier"}
                  </div>
                </button>
              ))
            )}
          </CardContent>
        </Card>

        {/* Detail Workspace — inline, no dismiss (Ch.5.1) */}
        <Card>
          <CardContent className="pt-6">
            {!selected && (
              <p className="text-sm text-muted-foreground text-center py-12">Select a project to view details.</p>
            )}
            {selected && draft && (
              <div className="space-y-4 text-sm">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="font-bold text-lg">{selected.name}</div>
                    {selected.description && (
                      <div className="text-xs text-muted-foreground mt-0.5">{selected.description}</div>
                    )}
                  </div>
                  {statusBadge(selected.status)}
                </div>

                <div className="grid grid-cols-2 gap-2">
                  {[
                    ["Activity", selected.activity_type],
                    ["Supplier", selected.supplier_name],
                    ["Owner", selected.assigned_staff_id || selected.owner_id],
                    ["Stage", STAGE_LABELS[currentStage]?.label || currentStage],
                    ["PO Reference", selected.po_reference],
                    ["Temp Profile", selected.temperature_profile],
                    ["NAFDAC", selected.nafdac_sampling_status],
                    ["QC Status", selected.quality_check_status],
                    ["Reviewed By", selected.quality_checked_by],
                    ["Reviewed At", selected.quality_checked_at ? new Date(selected.quality_checked_at).toLocaleString() : undefined],
                    ["Created", selected.created_at ? new Date(selected.created_at).toLocaleDateString() : undefined],
                  ].map(([label, value]) => (
                    <div key={String(label)} className="space-y-0.5">
                      <div className="text-xs text-muted-foreground">{label}</div>
                      <div className="text-xs font-medium truncate">{value ?? "—"}</div>
                    </div>
                  ))}
                </div>

                {selected.quality_notes && (
                  <div>
                    <div className="text-xs text-muted-foreground mb-1">Quality Notes</div>
                    <div className="text-xs bg-muted/40 rounded p-2">{selected.quality_notes}</div>
                  </div>
                )}

                <Separator />

                {nextOptions.length === 0 ? (
                  <p className="text-xs text-muted-foreground">This project has reached its final stage.</p>
                ) : (
                  <div className="space-y-3">
                    <div className="text-xs font-semibold text-muted-foreground">MOVE STAGE</div>
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">Next Stage</label>
                      <Select
                        value={draft.workflow_stage}
                        onValueChange={(value) => onDraftChange(selected, { workflow_stage: value })}
                      >
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {nextOptions.map((opt) => (
                            <SelectItem key={opt} value={opt}>{STAGE_LABELS[opt]?.label || opt}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="text-xs text-muted-foreground mb-1 block">QC Status</label>
                        <Select
                          value={draft.quality_check_status}
                          onValueChange={(value) => onDraftChange(selected, { quality_check_status: value })}
                        >
                          <SelectTrigger><SelectValue /></SelectTrigger>
                          <SelectContent>
                            {QC_STATUSES.map((s) => (
                              <SelectItem key={s} value={s}>{s.replace("_", " ")}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <label className="text-xs text-muted-foreground mb-1 block">NAFDAC Status</label>
                        <Select
                          value={draft.nafdac_sampling_status}
                          onValueChange={(value) => onDraftChange(selected, { nafdac_sampling_status: value })}
                        >
                          <SelectTrigger><SelectValue /></SelectTrigger>
                          <SelectContent>
                            {NAFDAC_STATUSES.map((s) => (
                              <SelectItem key={s} value={s}>{s.replace("_", " ")}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">Quality Notes</label>
                      <Textarea
                        rows={3}
                        placeholder="Notes for this transition…"
                        value={draft.quality_notes}
                        onChange={(e) => onDraftChange(selected, { quality_notes: e.target.value })}
                      />
                    </div>
                    <Button
                      size="sm"
                      disabled={moving || !controlsReady}
                      onClick={() => onMoveStage(selected)}
                    >
                      {moving && <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />}
                      Confirm Move
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
            <p className="text-xs text-muted-foreground">Use "New Project" in the header to create a project.</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// ── Kanban column accent colours (Placeware brand) ─────────────────────────
const STAGE_COLUMN: Record<string, { bg: string; count: string }> = {
  port_clearing:          { bg: "#2740AE", count: "rgba(255,255,255,0.22)" },
  anti_room_received:     { bg: "#256CAE", count: "rgba(255,255,255,0.22)" },
  cold_room_stacked:      { bg: "#02646F", count: "rgba(255,255,255,0.22)" },
  nafdac_sampling:        { bg: "#d97706", count: "rgba(255,255,255,0.22)" },
  released_for_issuing:   { bg: "#16a34a", count: "rgba(255,255,255,0.22)" },
  packaging_for_delivery: { bg: "#ea580c", count: "rgba(255,255,255,0.22)" },
  delivered_to_end_users: { bg: "#059669", count: "rgba(255,255,255,0.22)" },
};

const QC_CHIP: Record<string, string> = {
  passed:    "bg-emerald-50 text-emerald-700 border-emerald-200",
  failed:    "bg-red-50 text-red-700 border-red-200",
  in_review: "bg-sky-50 text-sky-700 border-sky-200",
  waived:    "bg-amber-50 text-amber-700 border-amber-200",
  pending:   "bg-slate-100 text-slate-500 border-slate-200",
};

const NAFDAC_CHIP: Record<string, string> = {
  released:    "bg-emerald-50 text-emerald-700 border-emerald-200",
  in_progress: "bg-sky-50 text-sky-700 border-sky-200",
  pending:     "bg-slate-100 text-slate-500 border-slate-200",
};

const ACTIVITY_CHIP: Record<string, string> = {
  restock:        "bg-blue-50 text-blue-700 border-blue-200",
  qc:             "bg-teal-50 text-teal-700 border-teal-200",
  delivery:       "bg-cyan-50 text-cyan-700 border-cyan-200",
  client_request: "bg-amber-50 text-amber-700 border-amber-200",
  cold_chain:     "bg-indigo-50 text-indigo-700 border-indigo-200",
};

// ── Per-card expanded state ──────────────────────────────────────────────────
function KanbanCard({
  project,
  stageKey,
  controlsReady,
  movingProjectId,
  stageDrafts,
  onDraftChange,
  onMoveStage,
}: {
  project: Project;
  stageKey: string;
  controlsReady: boolean;
  movingProjectId: string | null;
  stageDrafts: Record<string, { workflow_stage: string; quality_check_status: string; nafdac_sampling_status: string; quality_notes: string }>;
  onDraftChange: (project: Project, patch: Partial<{ workflow_stage: string; quality_check_status: string; nafdac_sampling_status: string; quality_notes: string }>) => void;
  onMoveStage: (project: Project) => Promise<void>;
}) {
  const [expanded, setExpanded] = useState(false);
  const nextOptions = STAGE_TRANSITIONS[stageKey] || [];
  const draft = stageDrafts[project.id] || {
    workflow_stage: nextOptions[0] || stageKey,
    quality_check_status: project.quality_check_status || "pending",
    nafdac_sampling_status: project.nafdac_sampling_status || "pending",
    quality_notes: project.quality_notes || "",
  };
  const moving = movingProjectId === project.id;
  const qcChip  = QC_CHIP[project.quality_check_status || "pending"]  || QC_CHIP.pending;
  const nafChip = NAFDAC_CHIP[project.nafdac_sampling_status || "pending"] || NAFDAC_CHIP.pending;
  const actChip = ACTIVITY_CHIP[project.activity_type || ""] || "bg-slate-100 text-slate-600 border-slate-200";
  const isComplete = stageKey === "delivered_to_end_users";

  // Left border accent based on QC
  const leftAccent =
    project.quality_check_status === "passed"    ? "border-l-emerald-500" :
    project.quality_check_status === "failed"    ? "border-l-red-500"     :
    project.quality_check_status === "in_review" ? "border-l-sky-500"     :
    stageKey === "delivered_to_end_users"         ? "border-l-emerald-500" :
    "border-l-primary";

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className={`rounded-xl border border-border/60 border-l-4 ${leftAccent} bg-card shadow-elevation-1 transition-shadow hover:shadow-elevation-2`}
    >
      {/* Card body */}
      <div className="p-3 space-y-2">
        <p className="text-sm font-semibold leading-snug line-clamp-2">{project.name}</p>

        {/* Activity + supplier row */}
        <div className="flex flex-wrap items-center gap-1.5">
          {project.activity_type && (
            <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${actChip}`}>
              {project.activity_type.replace("_", " ")}
            </span>
          )}
          {project.supplier_name && (
            <span className="text-[11px] text-muted-foreground truncate max-w-[120px]">{project.supplier_name}</span>
          )}
        </div>

        {/* QC + NAFDAC badges */}
        <div className="flex flex-wrap gap-1.5">
          <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${qcChip}`}>
            QC: {(project.quality_check_status || "pending").replace("_", " ")}
          </span>
          <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${nafChip}`}>
            NAFDAC: {(project.nafdac_sampling_status || "pending").replace("_", " ")}
          </span>
        </div>

        {/* PO reference */}
        {project.po_reference && (
          <p className="text-[11px] text-muted-foreground font-mono">PO: {project.po_reference}</p>
        )}

        {/* Footer row: staff avatar + expand button */}
        <div className="flex items-center justify-between pt-1">
          <div className="flex items-center gap-1.5">
            {(project.assigned_staff_id || project.owner_id) && (
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/20 text-[10px] font-bold text-primary select-none ring-1 ring-primary/30">
                {((project.assigned_staff_id || project.owner_id) as string).charAt(0).toUpperCase()}
              </div>
            )}
            {project.temperature_profile && (
              <span className="text-[10px] text-muted-foreground">{project.temperature_profile}</span>
            )}
          </div>
          {!isComplete && (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="flex items-center gap-0.5 rounded-md px-2 py-0.5 text-[11px] font-medium text-primary hover:bg-primary/10 transition-colors"
            >
              {expanded ? "Close" : "Move"}
              <ChevronDown className={`h-3 w-3 transition-transform ${expanded ? "rotate-180" : ""}`} />
            </button>
          )}
          {isComplete && (
            <span className="text-[11px] font-medium text-emerald-600">✓ Delivered</span>
          )}
        </div>
      </div>

      {/* Expanded move controls */}
      {expanded && nextOptions.length > 0 && (
        <div className="border-t border-border/50 bg-muted/30 rounded-b-xl p-3 space-y-2">
          <Select
            value={draft.workflow_stage}
            onValueChange={(value) => onDraftChange(project, { workflow_stage: value })}
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="Next stage" />
            </SelectTrigger>
            <SelectContent>
              {nextOptions.map((opt) => (
                <SelectItem key={opt} value={opt} className="text-xs">
                  {STAGE_LABELS[opt]?.label || opt}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="grid grid-cols-2 gap-2">
            <Select
              value={draft.quality_check_status}
              onValueChange={(value) => onDraftChange(project, { quality_check_status: value })}
            >
              <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="QC" /></SelectTrigger>
              <SelectContent>
                {QC_STATUSES.map((s) => (
                  <SelectItem key={s} value={s} className="text-xs">{s.replace("_", " ")}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={draft.nafdac_sampling_status}
              onValueChange={(value) => onDraftChange(project, { nafdac_sampling_status: value })}
            >
              <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="NAFDAC" /></SelectTrigger>
              <SelectContent>
                {NAFDAC_STATUSES.map((s) => (
                  <SelectItem key={s} value={s} className="text-xs">{s.replace("_", " ")}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button
            size="sm"
            className="w-full h-8 text-xs gap-1.5"
            disabled={moving || !controlsReady}
            onClick={() => { void onMoveStage(project); setExpanded(false); }}
          >
            {moving
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
              : <span>→</span>
            }
            Confirm Move
          </Button>
        </div>
      )}
    </motion.div>
  );
}

// ── Main board ───────────────────────────────────────────────────────────────
function StageTransitionBoard({
  projects,
  loading,
  controlsReady,
  movingProjectId,
  stageDrafts,
  onDraftChange,
  onMoveStage,
}: {
  projects: Project[];
  loading: boolean;
  controlsReady: boolean;
  movingProjectId: string | null;
  stageDrafts: Record<string, { workflow_stage: string; quality_check_status: string; nafdac_sampling_status: string; quality_notes: string }>;
  onDraftChange: (project: Project, patch: Partial<{ workflow_stage: string; quality_check_status: string; nafdac_sampling_status: string; quality_notes: string }>) => void;
  onMoveStage: (project: Project) => Promise<void>;
}) {
  const grouped = Object.keys(STAGE_LABELS).map((stageKey) => ({
    stageKey,
    stage: STAGE_LABELS[stageKey],
    col: STAGE_COLUMN[stageKey] || { bg: "#2740AE", count: "rgba(255,255,255,0.22)" },
    items: projects.filter((p) => (p.workflow_stage || "port_clearing") === stageKey),
  }));

  const total = projects.length;

  return (
    <div className="space-y-4">
      {/* Board header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h3 className="text-base font-bold">Workflow Stage Board</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            {total} active project{total !== 1 ? "s" : ""} · Port Clearing → Delivered
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {grouped.map((col) => (
            <div key={col.stageKey} className="flex items-center gap-1 text-[11px] font-medium">
              <span className="h-2 w-2 rounded-full" style={{ background: col.col.bg }} />
              <span className="text-muted-foreground">{col.stage.label.split(" ")[0]}</span>
              <span className="font-bold">{col.items.length}</span>
            </div>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-16">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : (
        /* Horizontal Kanban scroll container */
        <div className="overflow-x-auto pb-4 -mx-1 px-1">
          <div className="flex gap-3" style={{ minWidth: "max-content" }}>
            {grouped.map((col) => (
              <div
                key={col.stageKey}
                className="flex flex-col rounded-2xl border border-border/50 bg-background/60 backdrop-blur-sm"
                style={{ width: "252px", minWidth: "252px" }}
              >
                {/* Column header */}
                <div
                  className="flex items-center justify-between rounded-t-2xl px-3.5 py-2.5"
                  style={{ background: col.col.bg }}
                >
                  <div className="min-w-0">
                    <p className="text-sm font-bold text-white leading-tight truncate">{col.stage.label}</p>
                    <p className="text-[10px] text-white/70 truncate">{col.stage.department}</p>
                  </div>
                  <span
                    className="ml-2 shrink-0 rounded-full px-2 py-0.5 text-xs font-bold text-white"
                    style={{ background: col.col.count }}
                  >
                    {col.items.length}
                  </span>
                </div>

                {/* Cards */}
                <div className="flex-1 space-y-2 overflow-y-auto p-2" style={{ maxHeight: "520px" }}>
                  {col.items.length === 0 ? (
                    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border/60 py-8 text-center">
                      <p className="text-[11px] text-muted-foreground">No projects here</p>
                    </div>
                  ) : (
                    col.items.map((project) => (
                      <KanbanCard
                        key={project.id}
                        project={project}
                        stageKey={col.stageKey}
                        controlsReady={controlsReady}
                        movingProjectId={movingProjectId}
                        stageDrafts={stageDrafts}
                        onDraftChange={onDraftChange}
                        onMoveStage={onMoveStage}
                      />
                    ))
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// Deliveries tab — consolidated onto LogisticsMonitor.tsx (its List/Detail/
// QuickActions full retrofit, ping history, real rider assignment), which
// this tab's hardcoded mock rows (DLV-1023 etc.) duplicated with zero real
// data behind them. Same treatment as the AR Aging consolidation
// (ACE-Workspace-Standard.md §9.7).
function DeliveryList() {
  const navigate = useNavigate();
  const { data } = useQuery({
    queryKey: ["logistics-deliveries-summary"],
    queryFn: () => api.logistics.listDeliveries({ limit: 200 }),
  });
  const deliveries: any[] = data?.deliveries ?? [];
  const stats = useMemo(() => ({
    total: deliveries.length,
    unassigned: deliveries.filter((d) => d.status === "unassigned").length,
    inTransit: deliveries.filter((d) => d.status === "in_transit").length,
    delivered: deliveries.filter((d) => d.status === "delivered").length,
  }), [deliveries]);

  return (
    <Card className="pw-surface-interactive">
      <CardHeader>
        <CardTitle>Deliveries</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <KpiStrip
          items={[
            { label: "Total Deliveries", value: stats.total },
            { label: "Unassigned", value: stats.unassigned, tone: stats.unassigned > 0 ? "warning" : "default" },
            { label: "In Transit", value: stats.inTransit, tone: "warning" },
            { label: "Delivered", value: stats.delivered, tone: "success" },
          ]}
        />
        <Button onClick={() => navigate("/operations/logistics")} className="gap-2">
          View Full Logistics Monitor <ArrowRight className="w-4 h-4" />
        </Button>
      </CardContent>
    </Card>
  );
}

// Stock Orders tab — consolidated onto PurchaseOrders.tsx (real Sage-sourced
// PO data, search, status filters), which this tab's hardcoded mock rows
// (SO-8821 etc.) duplicated. Same treatment as §9.7.
function StockOrderList() {
  const navigate = useNavigate();
  const { data: summary } = useQuery({
    queryKey: ["purchase-orders-summary"],
    queryFn: () => api.procurement.purchaseOrdersSummary(),
  });

  return (
    <Card className="pw-surface-interactive">
      <CardHeader>
        <CardTitle>Stock Orders</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <KpiStrip
          items={[
            { label: "Total POs", value: summary?.total_pos ?? "—" },
            { label: "Open POs", value: summary?.open_pos ?? "—" },
            { label: "Overdue POs", value: summary?.overdue_pos ?? "—", tone: (summary?.overdue_pos ?? 0) > 0 ? "danger" : "default" },
            { label: "Overdue Value", value: summary?.overdue_value != null ? `₦${Number(summary.overdue_value).toLocaleString()}` : "—", tone: (summary?.overdue_value ?? 0) > 0 ? "danger" : "default" },
          ]}
        />
        <Button onClick={() => navigate("/operations/purchase-orders")} className="gap-2">
          View Full Purchase Orders <ArrowRight className="w-4 h-4" />
        </Button>
      </CardContent>
    </Card>
  );
}
