import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PlusCircle, Search, Filter, Loader2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
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
import { ChevronDown, LayoutGrid } from "lucide-react";
import { useIsMobile } from "@/hooks/use-mobile";

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
const STAGE_BOARD_PREFS_KEY = "project_controls_stage_board_prefs";

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
  const [projects, setProjects] = useState<Project[]>([]);
  const [staffOptions, setStaffOptions] = useState<Array<{ staff_id: string; full_name: string }>>([]);
  const [supplierOptions, setSupplierOptions] = useState<SupplierOption[]>([]);
  const [loading, setLoading] = useState(true);
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
  const [creating, setCreating] = useState(false);
  const [controlsReady, setControlsReady] = useState(true);
  const [controlsReadyReason, setControlsReadyReason] = useState<string | null>(null);
  const [controlsReadyLoading, setControlsReadyLoading] = useState(true);
  const [movingProjectId, setMovingProjectId] = useState<string | null>(null);
  const [stageDrafts, setStageDrafts] = useState<Record<string, {
    workflow_stage: string;
    quality_check_status: string;
    nafdac_sampling_status: string;
    quality_notes: string;
  }>>({});
  const { toast } = useToast();

  const fetchProjects = useCallback(async () => {
    try {
      setLoading(true);
      const data = await api.projects.list(50);
      setProjects(data || []);
    } catch (err: any) {
      toast({ title: "Error loading projects", description: err.message, variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  useEffect(() => {
    const loadReadiness = async () => {
      try {
        setControlsReadyLoading(true);
        const result = await api.projects.readiness();
        const ready = Boolean(result?.ready);
        setControlsReady(ready);
        setControlsReadyReason(ready ? null : result?.reason || "Project workflow schema is not ready yet.");
      } catch (err: any) {
        setControlsReady(false);
        setControlsReadyReason(err?.message || "Failed to verify workflow readiness.");
      } finally {
        setControlsReadyLoading(false);
      }
    };
    void loadReadiness();
  }, []);

  useEffect(() => {
    const loadStaff = async () => {
      try {
        const rows = await api.staff.list();
        const parsed = (rows || [])
          .filter((row: any) => typeof row?.staff_id === "string" && typeof row?.full_name === "string")
          .map((row: any) => ({ staff_id: row.staff_id as string, full_name: row.full_name as string }));
        setStaffOptions(parsed);
      } catch {
        setStaffOptions([]);
      }
    };
    const loadSuppliers = async () => {
      try {
        const rows = await api.suppliers.list();
        const parsed = (rows || []).filter((row: any) => typeof row?.name === "string").map((row: any) => ({ id: row.id as string | undefined, name: row.name as string }));
        setSupplierOptions(parsed);
      } catch {
        setSupplierOptions([]);
      }
    };
    void loadStaff();
    void loadSuppliers();
  }, []);

  const handleCreate = async () => {
    if (!controlsReady) {
      toast({ title: "Workflow not ready", description: controlsReadyReason || "Backend schema is not ready for project actions.", variant: "destructive" });
      return;
    }
    if (!newProject.name.trim()) {
      toast({ title: "Validation Error", description: "Project name is required", variant: "destructive" });
      return;
    }
    try {
      setCreating(true);
      await api.projects.create(newProject);
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
      fetchProjects();
    } catch (err: any) {
      toast({ title: "Create Failed", description: err.message, variant: "destructive" });
    } finally {
      setCreating(false);
    }
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
      await fetchProjects();
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
      <div className="flex items-center justify-between space-y-2">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Project Controls</h2>
          <p className="text-muted-foreground">
            Manage projects, deliveries, and stock orders.
          </p>
        </div>
        <div className="flex items-center space-x-2">
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button disabled={!controlsReady || controlsReadyLoading}>
                <PlusCircle className="mr-2 h-4 w-4" />
                New Project
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Create New Project</DialogTitle>
                <DialogDescription>Enter the details for your new project.</DialogDescription>
              </DialogHeader>
              <div className="grid gap-4 py-4">
                <div className="grid grid-cols-4 items-center gap-4">
                  <Label htmlFor="name" className="text-right">Name</Label>
                  <Input
                    id="name"
                    className="col-span-3"
                    value={newProject.name}
                    onChange={(e) => setNewProject({ ...newProject, name: e.target.value })}
                    placeholder="Project name"
                  />
                </div>
                <div className="grid grid-cols-4 items-center gap-4">
                  <Label htmlFor="description" className="text-right">Description</Label>
                  <Textarea
                    id="description"
                    className="col-span-3"
                    value={newProject.description}
                    onChange={(e) => setNewProject({ ...newProject, description: e.target.value })}
                    placeholder="Optional description"
                  />
                </div>
                <div className="grid grid-cols-4 items-center gap-4">
                  <Label htmlFor="status" className="text-right">Status</Label>
                  <Select
                    value={newProject.status}
                    onValueChange={(val) => setNewProject({ ...newProject, status: val })}
                  >
                    <SelectTrigger className="col-span-3">
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
                <div className="grid grid-cols-4 items-center gap-4">
                  <Label htmlFor="activity_type" className="text-right">Activity</Label>
                  <Select
                    value={newProject.activity_type}
                    onValueChange={(val) => setNewProject({ ...newProject, activity_type: val })}
                  >
                    <SelectTrigger className="col-span-3">
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
                <div className="grid grid-cols-4 items-center gap-4">
                  <Label htmlFor="supplier_name" className="text-right">Supplier</Label>
                  <Select
                    value={newProject.supplier_name || "unspecified_supplier"}
                    onValueChange={(val) => setNewProject({ ...newProject, supplier_name: val === "unspecified_supplier" ? "" : val })}
                  >
                    <SelectTrigger className="col-span-3">
                      <SelectValue placeholder="Select supplier" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="unspecified_supplier">Unspecified</SelectItem>
                      {supplierOptions.map((supplier) => (
                        <SelectItem key={supplier.id || supplier.name} value={supplier.name}>
                          {supplier.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid grid-cols-4 items-center gap-4">
                  <Label htmlFor="assigned_staff_id" className="text-right">In Charge</Label>
                  <Select
                    value={newProject.assigned_staff_id || "unassigned"}
                    onValueChange={(val) => setNewProject({ ...newProject, assigned_staff_id: val === "unassigned" ? "" : val })}
                  >
                    <SelectTrigger className="col-span-3">
                      <SelectValue placeholder="Select staff in charge" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="unassigned">Unassigned</SelectItem>
                      {staffOptions.map((staff) => (
                        <SelectItem key={staff.staff_id} value={staff.staff_id}>
                          {staff.full_name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid grid-cols-4 items-center gap-4">
                  <Label htmlFor="workflow_stage" className="text-right">Workflow Stage</Label>
                  <Select
                    value={newProject.workflow_stage}
                    onValueChange={(val) => setNewProject({ ...newProject, workflow_stage: val })}
                  >
                    <SelectTrigger className="col-span-3">
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
                <div className="grid grid-cols-4 items-center gap-4">
                  <Label htmlFor="po_reference" className="text-right">PO Reference</Label>
                  <Input
                    id="po_reference"
                    className="col-span-3"
                    value={newProject.po_reference}
                    onChange={(e) => setNewProject({ ...newProject, po_reference: e.target.value })}
                    placeholder="Purchase order reference"
                  />
                </div>
                <div className="grid grid-cols-4 items-center gap-4">
                  <Label htmlFor="temperature_profile" className="text-right">Temp Profile</Label>
                  <Input
                    id="temperature_profile"
                    className="col-span-3"
                    value={newProject.temperature_profile}
                    onChange={(e) => setNewProject({ ...newProject, temperature_profile: e.target.value })}
                    placeholder="e.g. 2-8C"
                  />
                </div>
                <div className="grid grid-cols-4 items-center gap-4">
                  <Label htmlFor="nafdac_sampling_status" className="text-right">NAFDAC</Label>
                  <Select
                    value={newProject.nafdac_sampling_status}
                    onValueChange={(val) => setNewProject({ ...newProject, nafdac_sampling_status: val })}
                  >
                    <SelectTrigger className="col-span-3">
                      <SelectValue placeholder="Select NAFDAC status" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="pending">Pending Sampling</SelectItem>
                      <SelectItem value="in_progress">Sampling In Progress</SelectItem>
                      <SelectItem value="released">Released</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid grid-cols-4 items-center gap-4">
                  <Label htmlFor="quality_check_status" className="text-right">QC Status</Label>
                  <Select
                    value={newProject.quality_check_status}
                    onValueChange={(val) => setNewProject({ ...newProject, quality_check_status: val })}
                  >
                    <SelectTrigger className="col-span-3">
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
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
                <Button onClick={handleCreate} disabled={creating}>
                  {creating && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Create
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>
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
          <ProjectList projects={projects} loading={loading} />
        </TabsContent>
        <TabsContent value="stage_board" className="space-y-4">
          <StageTransitionBoard
            projects={projects}
            loading={loading}
            controlsReady={controlsReady}
            movingProjectId={movingProjectId}
            stageDrafts={stageDrafts}
            onDraftChange={updateStageDraft}
            onMoveStage={moveProjectStage}
          />
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

function ProjectList({ projects, loading }: { projects: Project[]; loading: boolean }) {
  const isMobile = useIsMobile();

  const statusBadge = (status: string) => {
    switch (status) {
      case "active": return <Badge>Active</Badge>;
      case "planning": return <Badge variant="outline">Planning</Badge>;
      case "on_hold": return <Badge variant="secondary">On Hold</Badge>;
      case "completed": return <Badge className="border-success/30 bg-success/15 text-success">Completed</Badge>;
      default: return <Badge variant="outline">{status}</Badge>;
    }
  };

  return (
    <Card className="pw-surface-interactive">
      <CardHeader>
        <CardTitle>Active Projects</CardTitle>
        <CardDescription>
          Overview of ongoing operational projects.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex items-center py-4">
            <Input placeholder="Filter projects..." className="max-w-sm mr-4" />
            <Button variant="outline" size="icon"><Filter className="h-4 w-4" /></Button>
        </div>
        {loading ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : projects.length === 0 ? (
          <p className="text-center text-muted-foreground py-8">No projects found. Create one to get started.</p>
        ) : isMobile ? (
          <div className="space-y-3">
            {projects.map((p) => (
              <div key={p.id} className="rounded-lg border bg-card p-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-medium leading-tight">{p.name}</p>
                    <p className="mt-1 text-xs text-muted-foreground">{p.activity_type || "-"} • {p.supplier_name || "-"}</p>
                  </div>
                  {statusBadge(p.status)}
                </div>
                <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                  <span className="text-muted-foreground">Owner</span>
                  <span className="truncate">{p.assigned_staff_id || p.owner_id || "-"}</span>
                  <span className="text-muted-foreground">Stage</span>
                  <span>{p.workflow_stage || "-"}</span>
                  <span className="text-muted-foreground">QC</span>
                  <span>{p.quality_check_status || "-"}</span>
                  <span className="text-muted-foreground">Created</span>
                  <span>{p.created_at ? new Date(p.created_at).toLocaleDateString() : "-"}</span>
                </div>
                {p.description ? (
                  <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">{p.description}</p>
                ) : null}
              </div>
            ))}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="sticky left-0 z-10 min-w-[200px] bg-muted/90">Project Name</TableHead>
                  <TableHead className="min-w-[120px]">Activity</TableHead>
                  <TableHead className="min-w-[160px]">Supplier</TableHead>
                  <TableHead className="min-w-[140px]">Owner</TableHead>
                  <TableHead className="min-w-[150px]">Stage</TableHead>
                  <TableHead className="min-w-[110px]">QC</TableHead>
                  <TableHead className="min-w-[100px]">Status</TableHead>
                  <TableHead className="min-w-[260px]">Description</TableHead>
                  <TableHead className="min-w-[110px]">Created</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {projects.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="sticky left-0 z-10 bg-background font-medium">{p.name}</TableCell>
                    <TableCell>{p.activity_type || "-"}</TableCell>
                    <TableCell>{p.supplier_name || "-"}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{p.assigned_staff_id || p.owner_id || "-"}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{p.workflow_stage || "-"}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{p.quality_check_status || "-"}</TableCell>
                    <TableCell>{statusBadge(p.status)}</TableCell>
                    <TableCell className="max-w-xs truncate">{p.description || "-"}</TableCell>
                    <TableCell>{p.created_at ? new Date(p.created_at).toLocaleDateString() : "-"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

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
  const [compactMode, setCompactMode] = useState(false);
  const [collapsedStages, setCollapsedStages] = useState<Record<string, boolean>>({});
  const [collapsedProjects, setCollapsedProjects] = useState<Record<string, boolean>>({});

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STAGE_BOARD_PREFS_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as {
        compactMode?: boolean;
        collapsedStages?: Record<string, boolean>;
        collapsedProjects?: Record<string, boolean>;
      };
      setCompactMode(Boolean(parsed.compactMode));
      setCollapsedStages(parsed.collapsedStages || {});
      setCollapsedProjects(parsed.collapsedProjects || {});
    } catch {
      // Ignore malformed stored preferences.
    }
  }, []);

  useEffect(() => {
    localStorage.setItem(
      STAGE_BOARD_PREFS_KEY,
      JSON.stringify({ compactMode, collapsedStages, collapsedProjects }),
    );
  }, [compactMode, collapsedStages, collapsedProjects]);

  const grouped = Object.keys(STAGE_LABELS).map((stageKey) => ({
    stageKey,
    stage: STAGE_LABELS[stageKey],
    projects: projects.filter((project) => (project.workflow_stage || "port_clearing") === stageKey),
  }));

  return (
    <Card className="pw-surface-interactive">
      <CardHeader>
        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div>
            <CardTitle>Workflow Stage Board</CardTitle>
            <CardDescription>Track transitions from Port Clearing to End Users with explicit Quality Control gating.</CardDescription>
          </div>
          <Button variant="outline" size="sm" className="w-fit" onClick={() => setCompactMode((prev) => !prev)}>
            <LayoutGrid className="mr-2 h-4 w-4" />
            {compactMode ? "Expanded Mode" : "Compact Mode"}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {grouped.map((column) => {
              const stageCollapsed = Boolean(collapsedStages[column.stageKey]);
              return (
                <div key={column.stageKey} className={compactMode ? "rounded-xl border border-border/60 bg-background/30 p-2" : "rounded-xl border border-border/60 bg-background/30 p-3"}>
                  <button
                    type="button"
                    onClick={() => setCollapsedStages((prev) => ({ ...prev, [column.stageKey]: !stageCollapsed }))}
                    className="mb-3 flex w-full items-start justify-between text-left"
                  >
                    <div>
                      <h3 className={compactMode ? "text-xs font-semibold" : "text-sm font-semibold"}>{column.stage.label}</h3>
                      <p className="text-xs text-muted-foreground">{column.stage.department}</p>
                    </div>
                    <ChevronDown className={stageCollapsed ? "h-4 w-4 transition-transform rotate-180" : "h-4 w-4 transition-transform"} />
                  </button>

                  {stageCollapsed ? (
                    <p className="rounded-lg border border-dashed border-border/60 p-2 text-xs text-muted-foreground">
                      {column.projects.length} hidden in this stage.
                    </p>
                  ) : (
                    <div className={compactMode ? "space-y-2" : "space-y-3"}>
                      {column.projects.length === 0 ? (
                        <p className="rounded-lg border border-dashed border-border/60 p-3 text-xs text-muted-foreground">No projects in this stage.</p>
                      ) : (
                        column.projects.map((project) => {
                          const nextOptions = STAGE_TRANSITIONS[column.stageKey] || [];
                          const draft = stageDrafts[project.id] || {
                            workflow_stage: nextOptions[0] || column.stageKey,
                            quality_check_status: project.quality_check_status || "pending",
                            nafdac_sampling_status: project.nafdac_sampling_status || "pending",
                            quality_notes: project.quality_notes || "",
                          };
                          const moving = movingProjectId === project.id;
                          const projectCollapsed = Boolean(collapsedProjects[project.id]);

                          return (
                            <Collapsible
                              key={project.id}
                              open={!projectCollapsed}
                              onOpenChange={(open) => setCollapsedProjects((prev) => ({ ...prev, [project.id]: !open }))}
                            >
                              <div className={compactMode ? "rounded-lg border border-border/60 bg-background/50 p-2" : "rounded-lg border border-border/60 bg-background/50 p-3"}>
                                <CollapsibleTrigger asChild>
                                  <button type="button" className="flex w-full items-start justify-between text-left">
                                    <div className="space-y-1">
                                      <p className={compactMode ? "text-xs font-medium leading-tight" : "text-sm font-medium leading-tight"}>{project.name}</p>
                                      <p className="text-xs text-muted-foreground">{project.supplier_name || "No supplier"}</p>
                                      <div className="flex flex-wrap gap-2">
                                        <Badge variant="outline" className="text-[10px]">QC: {project.quality_check_status || "pending"}</Badge>
                                        <Badge variant="outline" className="text-[10px]">NAFDAC: {project.nafdac_sampling_status || "pending"}</Badge>
                                      </div>
                                    </div>
                                    <ChevronDown className={projectCollapsed ? "h-4 w-4 transition-transform rotate-180" : "h-4 w-4 transition-transform"} />
                                  </button>
                                </CollapsibleTrigger>
                                <CollapsibleContent className="space-y-3 pt-3">
                                  {nextOptions.length > 0 ? (
                                    <>
                                      <Select
                                        value={draft.workflow_stage}
                                        onValueChange={(value) => onDraftChange(project, { workflow_stage: value })}
                                      >
                                        <SelectTrigger>
                                          <SelectValue placeholder="Select next stage" />
                                        </SelectTrigger>
                                        <SelectContent>
                                          {nextOptions.map((option) => (
                                            <SelectItem key={option} value={option}>{STAGE_LABELS[option]?.label || option}</SelectItem>
                                          ))}
                                        </SelectContent>
                                      </Select>
                                      <div className="grid grid-cols-2 gap-2">
                                        <Select
                                          value={draft.quality_check_status}
                                          onValueChange={(value) => onDraftChange(project, { quality_check_status: value })}
                                        >
                                          <SelectTrigger>
                                            <SelectValue placeholder="QC status" />
                                          </SelectTrigger>
                                          <SelectContent>
                                            {QC_STATUSES.map((status) => (
                                              <SelectItem key={status} value={status}>{status.replace("_", " ")}</SelectItem>
                                            ))}
                                          </SelectContent>
                                        </Select>
                                        <Select
                                          value={draft.nafdac_sampling_status}
                                          onValueChange={(value) => onDraftChange(project, { nafdac_sampling_status: value })}
                                        >
                                          <SelectTrigger>
                                            <SelectValue placeholder="NAFDAC status" />
                                          </SelectTrigger>
                                          <SelectContent>
                                            {NAFDAC_STATUSES.map((status) => (
                                              <SelectItem key={status} value={status}>{status.replace("_", " ")}</SelectItem>
                                            ))}
                                          </SelectContent>
                                        </Select>
                                      </div>
                                      <Button disabled={moving || !controlsReady} onClick={() => void onMoveStage(project)} className="w-full">
                                        {moving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                                        Move Stage
                                      </Button>
                                    </>
                                  ) : (
                                    <p className="text-xs text-success">Workflow completed.</p>
                                  )}
                                </CollapsibleContent>
                              </div>
                            </Collapsible>
                          );
                        })
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DeliveryList() {
  const isMobile = useIsMobile();

    return (
        <Card className="pw-surface-interactive">
        <CardHeader>
            <CardTitle>Scheduled Deliveries</CardTitle>
            <CardDescription>
            Upcoming inbound and outbound shipments.
            </CardDescription>
        </CardHeader>
        <CardContent>
            {isMobile ? (
              <div className="space-y-3">
                <div className="rounded-lg border bg-card p-3 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">DLV-1023</span>
                    <Badge className="border-info/30 bg-info/15 text-info">In Transit</Badge>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">Outbound • Lagos General Hospital</p>
                  <p className="mt-1 text-xs">ETA: Today, 14:00</p>
                </div>
                <div className="rounded-lg border bg-card p-3 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">DLV-1024</span>
                    <Badge variant="outline">Scheduled</Badge>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">Inbound • Main Warehouse</p>
                  <p className="mt-1 text-xs">ETA: Tomorrow, 09:00</p>
                </div>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="sticky left-0 z-10 min-w-[120px] bg-muted/90">Ref ID</TableHead>
                      <TableHead className="min-w-[110px]">Type</TableHead>
                      <TableHead className="min-w-[200px]">Destination</TableHead>
                      <TableHead className="min-w-[130px]">ETA</TableHead>
                      <TableHead className="min-w-[110px]">Status</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    <TableRow>
                      <TableCell className="sticky left-0 z-10 bg-background">DLV-1023</TableCell>
                      <TableCell>Outbound</TableCell>
                      <TableCell>Lagos General Hospital</TableCell>
                      <TableCell>Today, 14:00</TableCell>
                      <TableCell><Badge className="border-info/30 bg-info/15 text-info">In Transit</Badge></TableCell>
                    </TableRow>
                    <TableRow>
                      <TableCell className="sticky left-0 z-10 bg-background">DLV-1024</TableCell>
                      <TableCell>Inbound</TableCell>
                      <TableCell>Main Warehouse</TableCell>
                      <TableCell>Tomorrow, 09:00</TableCell>
                      <TableCell><Badge variant="outline">Scheduled</Badge></TableCell>
                    </TableRow>
                  </TableBody>
                </Table>
              </div>
            )}
        </CardContent>
        </Card>
    )
}

function StockOrderList() {
    const isMobile = useIsMobile();

    return (
        <Card className="pw-surface-interactive">
        <CardHeader>
            <CardTitle>Stock Requisitions</CardTitle>
            <CardDescription>
            Pending stock orders and approvals.
            </CardDescription>
        </CardHeader>
        <CardContent>
            {isMobile ? (
              <div className="space-y-3">
                <div className="rounded-lg border bg-card p-3 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">SO-8821</span>
                    <Badge variant="destructive">Approval Required</Badge>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">Pfizer COVID-19 (x500)</p>
                  <p className="mt-1 text-xs">Requester: Dr. Smith (Clinical Ops)</p>
                  <p className="mt-1 text-xs">Date: 2026-02-18</p>
                </div>
                <div className="rounded-lg border bg-card p-3 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">SO-8820</span>
                    <Badge className="border-success/30 bg-success/15 text-success">Approved</Badge>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">Syringes 5ml (x2000)</p>
                  <p className="mt-1 text-xs">Requester: Inventory Mgr</p>
                  <p className="mt-1 text-xs">Date: 2026-02-17</p>
                </div>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="sticky left-0 z-10 min-w-[120px] bg-muted/90">Order ID</TableHead>
                      <TableHead className="min-w-[220px]">Items</TableHead>
                      <TableHead className="min-w-[180px]">Requester</TableHead>
                      <TableHead className="min-w-[120px]">Date</TableHead>
                      <TableHead className="min-w-[120px]">Status</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    <TableRow>
                      <TableCell className="sticky left-0 z-10 bg-background">SO-8821</TableCell>
                      <TableCell>Pfizer COVID-19 (x500)</TableCell>
                      <TableCell>Dr. Smith (Clinical Ops)</TableCell>
                      <TableCell>2026-02-18</TableCell>
                      <TableCell><Badge variant="destructive">Approval Required</Badge></TableCell>
                    </TableRow>
                    <TableRow>
                      <TableCell className="sticky left-0 z-10 bg-background">SO-8820</TableCell>
                      <TableCell>Syringes 5ml (x2000)</TableCell>
                      <TableCell>Inventory Mgr</TableCell>
                      <TableCell>2026-02-17</TableCell>
                      <TableCell><Badge className="border-success/30 bg-success/15 text-success">Approved</Badge></TableCell>
                    </TableRow>
                  </TableBody>
                </Table>
              </div>
            )}
        </CardContent>
        </Card>
    )
}
