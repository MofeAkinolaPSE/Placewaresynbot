import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Kanban,
  Bell,
  Send,
  BarChart3,
  MessageSquare,
  Plus,
  ChevronRight,
  Check,
  Clock,
  AlertCircle,
  Loader2,
  Trophy,
  Target,
  Brain,
  Package,
  FileDown,
  History,
  Phone,
  TrendingUp,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api-client";
import { motion } from "framer-motion";
import { motionVariants } from "@/lib/motion";

// --- Types ---

interface Lead {
  id: number;
  company_name?: string;
  contact_person?: string;
  stage: string;
  score?: number;
  expected_value?: number;
  last_contacted_at?: string;
  next_action?: string;
  product_interest?: string[];
}

interface PipelineBoard {
  stages: string[];
  board: Record<string, Lead[]>;
  counts: Record<string, number>;
  total: number;
}

interface Reminder {
  id: string;
  lead_id?: number;
  reminder_type: string;
  due_at: string;
  note?: string;
  status: string;
}

interface WeeklyReport {
  week_start: string;
  week_end: string;
  new_leads_count: number;
  active_leads: number;
  won_count: number;
  lost_count: number;
  pipeline_value: number;
  won_value: number;
  stage_breakdown: Record<string, number>;
  top_products: [string, number][];
  rep_activity: Record<string, number>;
  generated_at: string;
}

interface RepEntry {
  rank: number;
  rep_id: string;
  won_count: number;
  won_value: number;
  lost_count: number;
  active_count: number;
  pipeline_value: number;
  total_touched: number;
  score: number;
}

// --- Stage styling ---

const STAGE_COLORS: Record<string, string> = {
  new:          "bg-slate-100 dark:bg-slate-800 border-slate-300",
  qualified:    "bg-blue-50 dark:bg-blue-950 border-blue-300",
  proposal:     "bg-yellow-50 dark:bg-yellow-950 border-yellow-300",
  negotiation:  "bg-orange-50 dark:bg-orange-950 border-orange-300",
  payment_plan: "bg-purple-50 dark:bg-purple-950 border-purple-300",
  won:          "bg-green-50 dark:bg-green-950 border-green-300",
  lost:         "bg-red-50 dark:bg-red-950 border-red-300",
};

const STAGE_LABELS: Record<string, string> = {
  new:          "New Lead",
  qualified:    "Qualified",
  proposal:     "Proposal Sent",
  negotiation:  "Negotiation",
  payment_plan: "Payment Plan",
  won:          "Won",
  lost:         "Lost",
};

const STAGE_BADGE_VARIANT: Record<string, string> = {
  new:          "secondary",
  qualified:    "outline",
  proposal:     "outline",
  negotiation:  "outline",
  payment_plan: "outline",
  won:          "default",
  lost:         "destructive",
};

// --- Deal probability by stage ---

const STAGE_PROBABILITY: Record<string, number> = {
  new:          10,
  qualified:    25,
  proposal:     40,
  negotiation:  65,
  payment_plan: 80,
  won:          100,
  lost:         0,
};

function getProbabilityColor(p: number): string {
  if (p >= 80) return "text-green-600 dark:text-green-400";
  if (p >= 50) return "text-yellow-600 dark:text-yellow-400";
  if (p >= 20) return "text-orange-600 dark:text-orange-400";
  return "text-muted-foreground";
}

// --- Helpers ---

function formatCurrency(value?: number) {
  if (!value) return "---";
  return `${String.fromCharCode(8358)}${(value / 1000).toFixed(0)}k`;
}

function formatCurrencyM(value?: number) {
  if (!value && value !== 0) return "---";
  return `${String.fromCharCode(8358)}${(value / 1_000_000).toFixed(2)}M`;
}

function formatDate(iso?: string) {
  if (!iso) return "---";
  return new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}

function isOverdue(iso?: string) {
  if (!iso) return false;
  return new Date(iso) < new Date();
}

function repLabel(repId: string) {
  if (!repId || repId === "unassigned") return "Unassigned";
  return repId.length > 8 ? `...${repId.slice(-8)}` : repId;
}

// --- Pipeline Kanban Column ---

function KanbanColumn({
  stage,
  leads,
  onMoveStage,
  nextStage,
  onBrief,
  onStock,
  onLogInteraction,
}: {
  stage: string;
  leads: Lead[];
  onMoveStage: (leadId: number, newStage: string) => void;
  nextStage?: string;
  onBrief: (leadId: number) => void;
  onStock: (leadId: number) => void;
  onLogInteraction: (leadId: number) => void;
}) {
  const probability = STAGE_PROBABILITY[stage] ?? 0;
  return (
    <div className={`flex flex-col rounded-lg border-2 ${STAGE_COLORS[stage]} min-w-[220px] w-[220px] flex-shrink-0`}>
      <div className="px-3 py-2 border-b border-inherit flex items-center justify-between">
        <span className="text-sm font-semibold">{STAGE_LABELS[stage] ?? stage}</span>
        <div className="flex items-center gap-1.5">
          {stage !== "won" && stage !== "lost" && (
            <span className={`text-[10px] font-mono ${getProbabilityColor(probability)}`}>
              {probability}%
            </span>
          )}
          <Badge variant="secondary" className="text-xs">{leads.length}</Badge>
        </div>
      </div>
      <div className="flex flex-col gap-2 p-2 overflow-y-auto max-h-[520px]">
        {leads.length === 0 && (
          <p className="text-xs text-muted-foreground text-center py-4">No leads</p>
        )}
        {leads.map((lead) => (
          <Card key={lead.id} className="shadow-none border border-border/60 cursor-default hover:border-border transition-colors">
            <CardContent className="p-2.5 space-y-1">
              <p className="text-sm font-medium leading-tight truncate">
                {lead.company_name || `Lead #${lead.id}`}
              </p>
              {lead.contact_person && (
                <p className="text-xs text-muted-foreground truncate">{lead.contact_person}</p>
              )}
              <div className="flex items-center justify-between gap-1 pt-0.5">
                <span className="text-xs font-mono text-muted-foreground">
                  {formatCurrency(lead.expected_value)}
                </span>
                <div className="flex items-center gap-1">
                  {lead.score !== undefined && lead.score !== null && (
                    <span className={`text-[10px] font-bold ${getProbabilityColor(lead.score)}`}>
                      <Target className="inline h-2.5 w-2.5 mr-0.5" />
                      {lead.score}%
                    </span>
                  )}
                  {lead.last_contacted_at && (
                    <span className={`text-xs ${isOverdue(lead.last_contacted_at) ? "text-destructive" : "text-muted-foreground"}`}>
                      {formatDate(lead.last_contacted_at)}
                    </span>
                  )}
                </div>
              </div>
              {lead.product_interest && lead.product_interest.length > 0 && (
                <div className="flex flex-wrap gap-1 pt-0.5">
                  {lead.product_interest.slice(0, 2).map((p) => (
                    <Badge key={p} variant="outline" className="text-[10px] px-1 py-0">{p}</Badge>
                  ))}
                </div>
              )}
              {/* Brief + Stock + Log quick-action buttons */}
              <div className="flex gap-1 pt-1">
                <Button
                  size="sm"
                  variant="outline"
                  className="flex-1 h-6 text-[10px] gap-1 px-1"
                  onClick={() => onBrief(lead.id)}
                  title="Pre-call intelligence brief"
                >
                  <Brain className="h-3 w-3" />
                  Brief
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="flex-1 h-6 text-[10px] gap-1 px-1"
                  onClick={() => onStock(lead.id)}
                  title="Check product availability"
                >
                  <Package className="h-3 w-3" />
                  Stock
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="flex-1 h-6 text-[10px] gap-1 px-1"
                  onClick={() => onLogInteraction(lead.id)}
                  title="Log a call, visit, or demo"
                >
                  <Phone className="h-3 w-3" />
                  Log
                </Button>
              </div>
              {nextStage && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="w-full h-6 text-xs mt-1 gap-1"
                  onClick={() => onMoveStage(lead.id, nextStage)}
                >
                  Move to {STAGE_LABELS[nextStage] ?? nextStage}
                  <ChevronRight className="h-3 w-3" />
                </Button>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

// --- Main Page ---

export default function SalesCRM() {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  // Pipeline
  const { data: pipelineData, isLoading: pipelineLoading } = useQuery({
    queryKey: ["crm-sales-pipeline"],
    queryFn: () => api.salesCrm.pipeline(),
  });

  const moveStage = useMutation({
    mutationFn: ({ leadId, stage }: { leadId: number; stage: string }) =>
      api.salesCrm.moveStage(leadId, stage),
    onSuccess: () => {
      toast({ title: "Lead moved", description: "Pipeline updated." });
      void queryClient.invalidateQueries({ queryKey: ["crm-sales-pipeline"] });
    },
    onError: (e: any) => {
      toast({ title: "Failed to move lead", description: e?.message ?? "Unknown error", variant: "destructive" });
    },
  });

  // Reminders
  const { data: remindersData } = useQuery({
    queryKey: ["crm-sales-reminders"],
    queryFn: () => api.salesCrm.dueReminders(48),
  });
  const reminders: Reminder[] = (remindersData as any)?.reminders ?? [];

  const doneReminder = useMutation({
    mutationFn: (id: string) => api.salesCrm.updateReminder(id, "done"),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["crm-sales-reminders"] });
      toast({ title: "Reminder marked done" });
    },
  });

  // Add Reminder dialog
  const [addReminderOpen, setAddReminderOpen] = useState(false);
  const [reminderLeadId, setReminderLeadId] = useState("");
  const [reminderDueAt, setReminderDueAt] = useState("");
  const [reminderType, setReminderType] = useState("follow_up");
  const [reminderNote, setReminderNote] = useState("");

  const createReminder = useMutation({
    mutationFn: () =>
      api.salesCrm.createFollowUp({
        lead_id:       reminderLeadId ? parseInt(reminderLeadId, 10) : undefined,
        reminder_type: reminderType,
        due_at:        new Date(reminderDueAt).toISOString(),
        note:          reminderNote || undefined,
      }),
    onSuccess: () => {
      toast({ title: "Reminder created", description: "It will appear when due." });
      setAddReminderOpen(false);
      setReminderLeadId("");
      setReminderDueAt("");
      setReminderNote("");
      void queryClient.invalidateQueries({ queryKey: ["crm-sales-reminders"] });
    },
    onError: (e: any) => {
      toast({ title: "Failed to create reminder", description: e?.message, variant: "destructive" });
    },
  });

  // Weekly report
  const { data: reportData, isLoading: reportLoading, refetch: refetchReport } = useQuery({
    queryKey: ["crm-sales-weekly-report"],
    queryFn: () => api.salesCrm.weeklyReport(),
  });
  const report: WeeklyReport | undefined = (reportData as any)?.report;

  // Leaderboard
  const [lbDays, setLbDays] = useState(30);
  const { data: lbData, isLoading: lbLoading } = useQuery({
    queryKey: ["crm-sales-leaderboard", lbDays],
    queryFn: () => api.salesCrm.leaderboard(lbDays),
  });
  const leaderboard: RepEntry[] = (lbData as any)?.leaderboard ?? [];

  // NLQ
  const [nlqInput, setNlqInput] = useState("");
  const [nlqAnswer, setNlqAnswer] = useState("");
  const nlqMutation = useMutation({
    mutationFn: (query: string) => api.salesCrm.query(query),
    onSuccess: (data: any) => {
      setNlqAnswer(data?.answer ?? "No answer returned.");
    },
    onError: (e: any) => {
      setNlqAnswer(`Error: ${e?.message ?? "Failed to query ACE."}`);
    },
  });

  // Bulk message
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkChannel, setBulkChannel] = useState("whatsapp");
  const [bulkSubject, setBulkSubject] = useState("");
  const [bulkText, setBulkText] = useState("");

  // Brief sheet
  const [briefLeadId, setBriefLeadId] = useState<number | null>(null);
  const { data: briefData, isLoading: briefLoading } = useQuery({
    queryKey: ["crm-brief", briefLeadId],
    queryFn: () => api.salesCrm.getLeadBrief(briefLeadId!),
    enabled: briefLeadId !== null,
  });

  // Stock dialog
  const [stockLeadId, setStockLeadId] = useState<number | null>(null);
  const { data: stockData, isLoading: stockLoading } = useQuery({
    queryKey: ["crm-stock", stockLeadId],
    queryFn: () => api.salesCrm.getProductAvailability(stockLeadId!),
    enabled: stockLeadId !== null,
  });

  // New Lead dialog
  const [newLeadOpen, setNewLeadOpen] = useState(false);
  const [newLeadCompany, setNewLeadCompany] = useState("");
  const [newLeadContact, setNewLeadContact] = useState("");
  const [newLeadPhone, setNewLeadPhone] = useState("");
  const [newLeadProducts, setNewLeadProducts] = useState("");
  const [newLeadStage, setNewLeadStage] = useState("new");
  const [newLeadValue, setNewLeadValue] = useState("");
  const [newLeadTerms, setNewLeadTerms] = useState("");
  const [newLeadNotes, setNewLeadNotes] = useState("");

  const createLead = useMutation({
    mutationFn: () =>
      api.salesCrm.createLead({
        company_name:    newLeadCompany.trim(),
        contact_person:  newLeadContact.trim() || undefined,
        contact_phone:   newLeadPhone.trim() || undefined,
        product_interest: newLeadProducts ? newLeadProducts.split(",").map(p => p.trim()).filter(Boolean) : undefined,
        stage:           newLeadStage,
        expected_value:  newLeadValue ? parseFloat(newLeadValue) : undefined,
        payment_terms:   newLeadTerms.trim() || undefined,
        notes:           newLeadNotes.trim() || undefined,
      }),
    onSuccess: () => {
      toast({ title: "Lead created", description: `${newLeadCompany} added to pipeline.` });
      setNewLeadOpen(false);
      setNewLeadCompany(""); setNewLeadContact(""); setNewLeadPhone("");
      setNewLeadProducts(""); setNewLeadValue(""); setNewLeadTerms(""); setNewLeadNotes("");
      setNewLeadStage("new");
      void queryClient.invalidateQueries({ queryKey: ["crm-sales-pipeline"] });
    },
    onError: (e: any) => {
      toast({ title: "Failed to create lead", description: e?.message, variant: "destructive" });
    },
  });

  // Log Interaction dialog
  const [logLeadId, setLogLeadId] = useState<number | null>(null);
  const [logType, setLogType] = useState("call");
  const [logSummary, setLogSummary] = useState("");
  const [logOutcome, setLogOutcome] = useState("");
  const [logNextStep, setLogNextStep] = useState("");

  const logInteractionMutation = useMutation({
    mutationFn: () =>
      api.salesCrm.logInteraction(logLeadId!, {
        interaction_type: logType,
        summary:          logSummary.trim(),
        outcome:          logOutcome.trim() || undefined,
        next_step:        logNextStep.trim() || undefined,
      }),
    onSuccess: () => {
      toast({ title: "Interaction logged", description: "Activity recorded and last-contacted updated." });
      setLogLeadId(null);
      setLogSummary(""); setLogOutcome(""); setLogNextStep("");
      void queryClient.invalidateQueries({ queryKey: ["crm-sales-pipeline"] });
    },
    onError: (e: any) => {
      toast({ title: "Failed to log interaction", description: e?.message, variant: "destructive" });
    },
  });

  // Targets vs Actuals
  const currentPeriod = new Date().toISOString().slice(0, 7); // YYYY-MM
  const [targetPeriod, setTargetPeriod] = useState(currentPeriod);
  const { data: tvaData, isLoading: tvaLoading, refetch: refetchTva } = useQuery({
    queryKey: ["crm-targets-vs-actuals", targetPeriod],
    queryFn: () => api.salesCrm.targetsVsActuals(targetPeriod),
  });
  const [newTargetOpen, setNewTargetOpen] = useState(false);
  const [ntRepId, setNtRepId] = useState("");
  const [ntPeriodType, setNtPeriodType] = useState("monthly");
  const [ntValue, setNtValue] = useState("");
  const [ntDeals, setNtDeals] = useState("");
  const createTarget = useMutation({
    mutationFn: () =>
      api.salesCrm.createTarget({
        rep_id:       ntRepId.trim() || undefined,
        period:       targetPeriod,
        period_type:  ntPeriodType,
        target_value: parseFloat(ntValue),
        target_deals: ntDeals ? parseInt(ntDeals, 10) : undefined,
      }),
    onSuccess: () => {
      toast({ title: "Target set" });
      setNewTargetOpen(false);
      setNtRepId(""); setNtValue(""); setNtDeals("");
      void queryClient.invalidateQueries({ queryKey: ["crm-targets-vs-actuals", targetPeriod] });
    },
    onError: (e: any) => {
      toast({ title: "Failed to set target", description: e?.message, variant: "destructive" });
    },
  });

  const sendBulk = useMutation({
    mutationFn: () =>
      api.salesCrm.queueBulkMessage({
        channel:      bulkChannel,
        message_text: bulkText,
        subject:      bulkSubject || undefined,
      }),
    onSuccess: () => {
      toast({ title: "Bulk message queued", description: "It will be processed shortly." });
      setBulkOpen(false);
      setBulkText("");
      setBulkSubject("");
    },
    onError: (e: any) => {
      toast({ title: "Failed to queue message", description: e?.message, variant: "destructive" });
    },
  });

  const pipeline = pipelineData as PipelineBoard | undefined;
  const NEXT_STAGE: Record<string, string> = {
    new:          "qualified",
    qualified:    "proposal",
    proposal:     "negotiation",
    negotiation:  "payment_plan",
    payment_plan: "won",
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold">Sales CRM</h1>
          <p className="text-sm text-muted-foreground">Pipeline � Reminders � Reports � Leaderboard � ACE</p>
        </div>
        <Button onClick={() => setBulkOpen(true)} className="gap-2">
          <Send className="h-4 w-4" />
          Bulk Message
        </Button>
      </div>

      <Tabs defaultValue="pipeline">
        <TabsList className="flex-wrap h-auto gap-1">
          <TabsTrigger value="pipeline" className="gap-1.5">
            <Kanban className="h-4 w-4" /> Pipeline
          </TabsTrigger>
          <TabsTrigger value="reminders" className="gap-1.5">
            <Bell className="h-4 w-4" />
            Reminders
            {reminders.length > 0 && (
              <Badge variant="destructive" className="ml-1 text-[10px] px-1.5 py-0">
                {reminders.length}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="report" className="gap-1.5">
            <BarChart3 className="h-4 w-4" /> Weekly Report
          </TabsTrigger>
          <TabsTrigger value="leaderboard" className="gap-1.5">
            <Trophy className="h-4 w-4" /> Leaderboard
          </TabsTrigger>
          <TabsTrigger value="query" className="gap-1.5">
            <MessageSquare className="h-4 w-4" /> Ask ACE
          </TabsTrigger>
          <TabsTrigger value="targets" className="gap-1.5">
            <TrendingUp className="h-4 w-4" /> Targets
          </TabsTrigger>
        </TabsList>

        {/* Pipeline tab */}
        <TabsContent value="pipeline" className="mt-4">
          {pipelineLoading ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <motion.div {...motionVariants.cardEnter}>
              {pipeline && (
                <div className="flex flex-wrap gap-2 mb-4">
                  {pipeline.stages.map((s) => (
                    <div key={s} className="flex items-center gap-1.5 text-sm">
                      <Badge variant={STAGE_BADGE_VARIANT[s] as any}>{STAGE_LABELS[s]}</Badge>
                      <span className="text-muted-foreground font-mono">{pipeline.counts[s] ?? 0}</span>
                    </div>
                  ))}
                  <span className="text-xs text-muted-foreground self-center ml-2">Total: {pipeline.total}</span>
                </div>
              )}
              <div className="flex items-center gap-3 mb-3 text-xs text-muted-foreground">
                <Target className="h-3.5 w-3.5" />
                <span>Deal probability by stage:</span>
                {["new","qualified","negotiation","won"].map((s) => (
                  <span key={s} className={getProbabilityColor(STAGE_PROBABILITY[s])}>
                    {STAGE_LABELS[s]} {STAGE_PROBABILITY[s]}%
                  </span>
                ))}
              </div>
              <div className="flex gap-3 overflow-x-auto pb-4">
                {(pipeline?.stages ?? []).map((stage) => (
                  <KanbanColumn
                    key={stage}
                    stage={stage}
                    leads={pipeline?.board[stage] ?? []}
                    nextStage={NEXT_STAGE[stage]}
                    onMoveStage={(leadId, newStage) => moveStage.mutate({ leadId, stage: newStage })}
                    onBrief={(leadId) => setBriefLeadId(leadId)}
                    onStock={(leadId) => setStockLeadId(leadId)}
                    onLogInteraction={(leadId) => setLogLeadId(leadId)}
                  />
                ))}
              </div>
            </motion.div>
          )}
        </TabsContent>

        {/* Reminders tab */}
        <TabsContent value="reminders" className="mt-4">
          <motion.div {...motionVariants.cardEnter} className="space-y-3 max-w-2xl">
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted-foreground">Follow-ups due in the next 48 hours</p>
              <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setAddReminderOpen(true)}>
                <Plus className="h-3.5 w-3.5" />
                Add Reminder
              </Button>
            </div>

            {reminders.length === 0 && (
              <Card>
                <CardContent className="py-10 text-center text-muted-foreground text-sm">
                  No reminders due. You are all caught up.
                </CardContent>
              </Card>
            )}

            {reminders.map((rem) => (
              <Card key={rem.id} className={`border ${isOverdue(rem.due_at) ? "border-destructive/60" : ""}`}>
                <CardContent className="p-4 flex items-start justify-between gap-3">
                  <div className="space-y-0.5 flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      {isOverdue(rem.due_at) ? (
                        <AlertCircle className="h-4 w-4 text-destructive flex-shrink-0" />
                      ) : (
                        <Clock className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                      )}
                      <span className="text-sm font-medium">
                        {rem.reminder_type.replace(/_/g, " ")}
                        {rem.lead_id ? ` -- Lead #${rem.lead_id}` : ""}
                      </span>
                    </div>
                    {rem.note && <p className="text-xs text-muted-foreground pl-6">{rem.note}</p>}
                    <p className={`text-xs pl-6 ${isOverdue(rem.due_at) ? "text-destructive font-medium" : "text-muted-foreground"}`}>
                      Due: {new Date(rem.due_at).toLocaleString("en-GB")}
                    </p>
                  </div>
                  <Button size="sm" variant="outline" className="flex-shrink-0 gap-1" disabled={doneReminder.isPending} onClick={() => doneReminder.mutate(rem.id)}>
                    <Check className="h-3.5 w-3.5" />
                    Done
                  </Button>
                </CardContent>
              </Card>
            ))}
          </motion.div>
        </TabsContent>

        {/* Weekly report tab */}
        <TabsContent value="report" className="mt-4">
          <motion.div {...motionVariants.cardEnter} className="space-y-4 max-w-3xl">
            <div className="flex items-center justify-between">
              <div>
                {report && (
                  <p className="text-xs text-muted-foreground">
                    Week {report.week_start} to {report.week_end} - generated {new Date(report.generated_at).toLocaleString("en-GB")}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2">
                {report && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="gap-1.5"
                    onClick={() => {
                      window.open(api.salesCrm.weeklyReportPdfUrl(report.week_start), "_blank");
                      // Background: enrich sales intelligence via ReportGenerationAgent
                      void api.reports.generate({ report_type: "sales", intent_text: "generate weekly sales report" }).catch(() => {});
                    }}
                  >
                    <FileDown className="h-4 w-4" />
                    PDF
                  </Button>
                )}
                <Button size="sm" variant="outline" disabled={reportLoading} onClick={() => void refetchReport()}>
                  {reportLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Refresh"}
                </Button>
              </div>
            </div>

            {report ? (
              <>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  {[
                    { label: "New Leads",    value: report.new_leads_count },
                    { label: "Active Leads", value: report.active_leads },
                    { label: "Won",          value: report.won_count },
                    { label: "Lost",         value: report.lost_count },
                  ].map((kpi) => (
                    <Card key={kpi.label}>
                      <CardContent className="p-4 text-center">
                        <p className="text-2xl font-bold">{kpi.value}</p>
                        <p className="text-xs text-muted-foreground">{kpi.label}</p>
                      </CardContent>
                    </Card>
                  ))}
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <Card>
                    <CardHeader className="pb-1"><CardTitle className="text-sm">Pipeline Value</CardTitle></CardHeader>
                    <CardContent><p className="text-xl font-bold font-mono">{formatCurrencyM(report.pipeline_value)}</p></CardContent>
                  </Card>
                  <Card>
                    <CardHeader className="pb-1"><CardTitle className="text-sm">Won Value (this week)</CardTitle></CardHeader>
                    <CardContent><p className="text-xl font-bold font-mono text-green-600 dark:text-green-400">{formatCurrencyM(report.won_value)}</p></CardContent>
                  </Card>
                </div>

                <Card>
                  <CardHeader className="pb-2"><CardTitle className="text-sm">Stage Breakdown (active)</CardTitle></CardHeader>
                  <CardContent>
                    <div className="space-y-1.5">
                      {Object.entries(report.stage_breakdown ?? {}).map(([stage, count]) => (
                        <div key={stage} className="flex items-center justify-between text-sm">
                          <span>{STAGE_LABELS[stage] ?? stage}</span>
                          <div className="flex items-center gap-2">
                            <div className="h-2 rounded-full bg-primary" style={{ width: `${Math.max(4, (count / Math.max(1, report.active_leads)) * 120)}px` }} />
                            <span className="font-mono text-xs w-4 text-right">{count}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>

                {(report.top_products ?? []).length > 0 && (
                  <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm">Top Products of Interest</CardTitle></CardHeader>
                    <CardContent>
                      <div className="flex flex-wrap gap-2">
                        {(report.top_products ?? []).map(([product, count]) => (
                          <Badge key={product} variant="outline" className="gap-1">
                            {product}<span className="text-muted-foreground">x{count}</span>
                          </Badge>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                )}
              </>
            ) : reportLoading ? (
              <div className="flex justify-center py-16"><Loader2 className="h-8 w-8 animate-spin text-muted-foreground" /></div>
            ) : (
              <Card><CardContent className="py-10 text-center text-muted-foreground text-sm">No report data available. Click Refresh to generate.</CardContent></Card>
            )}
          </motion.div>
        </TabsContent>

        {/* Leaderboard tab */}
        <TabsContent value="leaderboard" className="mt-4">
          <motion.div {...motionVariants.cardEnter} className="space-y-4 max-w-2xl">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <p className="text-sm text-muted-foreground">Ranked by deals won + active pipeline activity</p>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Period:</span>
                <Select value={String(lbDays)} onValueChange={(v) => setLbDays(Number(v))}>
                  <SelectTrigger className="w-28 h-8 text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="7">Last 7 days</SelectItem>
                    <SelectItem value="30">Last 30 days</SelectItem>
                    <SelectItem value="90">Last 90 days</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {lbLoading ? (
              <div className="flex justify-center py-12"><Loader2 className="h-8 w-8 animate-spin text-muted-foreground" /></div>
            ) : leaderboard.length === 0 ? (
              <Card><CardContent className="py-10 text-center text-muted-foreground text-sm">No rep activity data for this period.</CardContent></Card>
            ) : (
              <div className="space-y-2">
                {leaderboard.map((rep) => (
                  <Card key={rep.rep_id} className={`border ${rep.rank === 1 ? "border-yellow-400/60 bg-yellow-50/30 dark:bg-yellow-950/20" : rep.rank === 2 ? "border-slate-400/60" : ""}`}>
                    <CardContent className="p-4">
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-3 min-w-0">
                          <div className={`text-xl font-black w-7 text-center flex-shrink-0 ${rep.rank === 1 ? "text-yellow-500" : rep.rank === 2 ? "text-slate-400" : rep.rank === 3 ? "text-amber-600" : "text-muted-foreground"}`}>
                            #{rep.rank}
                          </div>
                          <div className="min-w-0">
                            <p className="text-sm font-semibold truncate font-mono">{repLabel(rep.rep_id)}</p>
                            <p className="text-xs text-muted-foreground">Score: {rep.score}</p>
                          </div>
                        </div>
                        <div className="flex gap-4 text-center flex-shrink-0">
                          <div>
                            <p className="text-lg font-bold text-green-600 dark:text-green-400">{rep.won_count}</p>
                            <p className="text-[10px] text-muted-foreground">Won</p>
                          </div>
                          <div>
                            <p className="text-lg font-bold">{rep.active_count}</p>
                            <p className="text-[10px] text-muted-foreground">Active</p>
                          </div>
                          <div>
                            <p className="text-sm font-mono">{formatCurrency(rep.won_value)}</p>
                            <p className="text-[10px] text-muted-foreground">Won value</p>
                          </div>
                        </div>
                      </div>
                      {rep.total_touched > 0 && (
                        <div className="mt-2 flex h-1.5 rounded-full overflow-hidden gap-px">
                          <div className="bg-green-500" style={{ width: `${(rep.won_count / rep.total_touched) * 100}%` }} />
                          <div className="bg-blue-400" style={{ width: `${(rep.active_count / rep.total_touched) * 100}%` }} />
                          <div className="bg-red-400" style={{ width: `${(rep.lost_count / rep.total_touched) * 100}%` }} />
                        </div>
                      )}
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </motion.div>
        </TabsContent>

        {/* Ask ACE tab */}
        <TabsContent value="query" className="mt-4">
          <motion.div {...motionVariants.cardEnter} className="max-w-2xl space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Ask a sales question</CardTitle>
                <CardDescription>
                  E.g. "Which clients have not ordered in 60 days?" or "How many leads are in negotiation?"
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <Textarea
                  placeholder="Type your question..."
                  value={nlqInput}
                  onChange={(e) => setNlqInput(e.target.value)}
                  rows={3}
                  className="resize-none"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && nlqInput.trim().length >= 3) {
                      nlqMutation.mutate(nlqInput.trim());
                    }
                  }}
                />
                <Button disabled={nlqInput.trim().length < 3 || nlqMutation.isPending} onClick={() => nlqMutation.mutate(nlqInput.trim())} className="gap-2 w-full">
                  {nlqMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <MessageSquare className="h-4 w-4" />}
                  {nlqMutation.isPending ? "Thinking..." : "Ask ACE"}
                </Button>
              </CardContent>
            </Card>

            {nlqAnswer && (
              <Card className="border-primary/40">
                <CardHeader className="pb-2"><CardTitle className="text-sm text-primary">ACE</CardTitle></CardHeader>
                <CardContent><p className="text-sm whitespace-pre-wrap">{nlqAnswer}</p></CardContent>
              </Card>
            )}
          </motion.div>
        </TabsContent>

        {/* Targets tab */}
        <TabsContent value="targets" className="mt-4">
          <motion.div {...motionVariants.cardEnter} className="max-w-3xl space-y-4">
            <div className="flex items-center justify-between flex-wrap gap-3">
              <div>
                <h2 className="text-base font-semibold">Sales Targets vs. Actuals</h2>
                <p className="text-sm text-muted-foreground">Compare rep targets against won deals for any period</p>
              </div>
              <div className="flex gap-2">
                <Input
                  type="month"
                  value={targetPeriod}
                  onChange={e => setTargetPeriod(e.target.value)}
                  className="w-40"
                />
                <Button variant="outline" onClick={() => refetchTva()} disabled={tvaLoading} className="gap-1">
                  {tvaLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <BarChart3 className="h-4 w-4" />}
                  Refresh
                </Button>
                <Button onClick={() => setNewTargetOpen(true)} className="gap-1">
                  <Plus className="h-4 w-4" />
                  Set Target
                </Button>
              </div>
            </div>

            {tvaLoading ? (
              <div className="flex items-center justify-center py-16">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <>
                {/* Summary row */}
                {(tvaData as any)?.total_target !== undefined && (
                  <div className="grid grid-cols-3 gap-3">
                    {[
                      { label: "Team Target", value: formatCurrency((tvaData as any).total_target) },
                      { label: "Team Actual (Won)", value: formatCurrency((tvaData as any).total_actual) },
                      {
                        label: "Attainment",
                        value: (tvaData as any).total_target > 0
                          ? `${((tvaData as any).total_actual / (tvaData as any).total_target * 100).toFixed(1)}%`
                          : "N/A",
                      },
                    ].map(({ label, value }) => (
                      <Card key={label}>
                        <CardContent className="pt-4 pb-3">
                          <p className="text-xs text-muted-foreground">{label}</p>
                          <p className="text-xl font-bold font-mono mt-0.5">{value}</p>
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                )}

                {/* Per-rep table */}
                <Card>
                  <CardContent className="pt-4">
                    {!(tvaData as any)?.rows?.length ? (
                      <p className="text-sm text-muted-foreground py-6 text-center">
                        No targets set for {targetPeriod}. Click "Set Target" to add one.
                      </p>
                    ) : (
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-left text-xs text-muted-foreground border-b">
                            <th className="pb-2 pr-4">Rep</th>
                            <th className="pb-2 pr-4">Target</th>
                            <th className="pb-2 pr-4">Actual (Won)</th>
                            <th className="pb-2">Attainment %</th>
                          </tr>
                        </thead>
                        <tbody>
                          {((tvaData as any).rows as any[]).map((row: any, i: number) => {
                            const att = row.attainment_pct ?? null;
                            const color = att === null ? "text-muted-foreground" : att >= 100 ? "text-green-600" : att >= 70 ? "text-yellow-600" : "text-red-500";
                            return (
                              <tr key={i} className="border-b border-border/40 last:border-0">
                                <td className="py-2 pr-4 font-mono text-xs">{repLabel(row.rep_id)}</td>
                                <td className="py-2 pr-4 font-mono">{row.target_value != null ? formatCurrency(row.target_value) : <span className="text-muted-foreground">—</span>}</td>
                                <td className="py-2 pr-4 font-mono">{formatCurrency(row.actual_value)}</td>
                                <td className={`py-2 font-bold ${color}`}>{att !== null ? `${att}%` : "—"}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    )}
                  </CardContent>
                </Card>
              </>
            )}
          </motion.div>
        </TabsContent>
      </Tabs>

      {/* Add Reminder dialog */}
      <Dialog open={addReminderOpen} onOpenChange={setAddReminderOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Add Follow-up Reminder</DialogTitle>
            <DialogDescription>Schedule a reminder for a lead or client.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="space-y-1">
              <label className="text-sm font-medium">Lead ID <span className="text-muted-foreground text-xs">(optional)</span></label>
              <Input type="number" placeholder="e.g. 42" value={reminderLeadId} onChange={(e) => setReminderLeadId(e.target.value)} />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Reminder type</label>
              <Select value={reminderType} onValueChange={setReminderType}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="follow_up">Follow-up call</SelectItem>
                  <SelectItem value="product_demo">Product demo</SelectItem>
                  <SelectItem value="proposal_review">Proposal review</SelectItem>
                  <SelectItem value="payment_check">Payment check</SelectItem>
                  <SelectItem value="order_follow_up">Order follow-up</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Due date and time</label>
              <Input type="datetime-local" value={reminderDueAt} onChange={(e) => setReminderDueAt(e.target.value)} />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Note <span className="text-muted-foreground text-xs">(optional)</span></label>
              <Textarea placeholder="e.g. Follow up on Amoxicillin quotation..." value={reminderNote} onChange={(e) => setReminderNote(e.target.value)} rows={2} className="resize-none" />
            </div>
          </div>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setAddReminderOpen(false)}>Cancel</Button>
            <Button disabled={!reminderDueAt || createReminder.isPending} onClick={() => createReminder.mutate()} className="gap-2">
              {createReminder.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Bell className="h-4 w-4" />}
              Save Reminder
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Bulk message dialog */}
      <Dialog open={bulkOpen} onOpenChange={setBulkOpen}>        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Send Bulk Message</DialogTitle>
            <DialogDescription>Broadcast a message to your client list via WhatsApp or Email.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="space-y-1">
              <label className="text-sm font-medium">Channel</label>
              <Select value={bulkChannel} onValueChange={setBulkChannel}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="whatsapp">WhatsApp (via Termii)</SelectItem>
                  <SelectItem value="email">Email (via Gmail SMTP)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {bulkChannel === "email" && (
              <div className="space-y-1">
                <label className="text-sm font-medium">Subject</label>
                <Input placeholder="Email subject..." value={bulkSubject} onChange={(e) => setBulkSubject(e.target.value)} />
              </div>
            )}
            <div className="space-y-1">
              <label className="text-sm font-medium">Message</label>
              <Textarea placeholder="Type your message to clients..." value={bulkText} onChange={(e) => setBulkText(e.target.value)} rows={5} className="resize-none" />
              <p className="text-xs text-muted-foreground text-right">{bulkText.length} / 4096</p>
            </div>
          </div>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setBulkOpen(false)}>Cancel</Button>
            <Button disabled={bulkText.trim().length === 0 || sendBulk.isPending} onClick={() => sendBulk.mutate()} className="gap-2">
              {sendBulk.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              Queue Message
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Pre-call Brief Sheet */}
      <Sheet open={briefLeadId !== null} onOpenChange={(open) => { if (!open) setBriefLeadId(null); }}>
        <SheetContent className="w-full sm:max-w-xl overflow-y-auto">
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2">
              <Brain className="h-5 w-5 text-primary" />
              Pre-call Intelligence Brief
            </SheetTitle>
            <SheetDescription>AI-generated summary for Lead #{briefLeadId}</SheetDescription>
          </SheetHeader>
          <div className="mt-4 space-y-4">
            {briefLoading ? (
              <div className="flex justify-center py-12"><Loader2 className="h-8 w-8 animate-spin text-muted-foreground" /></div>
            ) : briefData ? (
              <>
                {(briefData as any).ai_brief && (
                  <Card className="border-primary/40">
                    <CardHeader className="pb-2"><CardTitle className="text-sm text-primary">AI Brief</CardTitle></CardHeader>
                    <CardContent>
                      <p className="text-sm whitespace-pre-wrap leading-relaxed">{(briefData as any).ai_brief}</p>
                    </CardContent>
                  </Card>
                )}
                {(briefData as any).recent_reminders?.length > 0 && (
                  <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-1.5"><Bell className="h-4 w-4" />Recent Reminders</CardTitle></CardHeader>
                    <CardContent className="space-y-1">
                      {(briefData as any).recent_reminders.map((r: any) => (
                        <div key={r.id} className="text-xs text-muted-foreground flex justify-between">
                          <span>{r.reminder_type?.replace(/_/g, " ")}</span>
                          <span>{formatDate(r.due_at)}</span>
                        </div>
                      ))}
                    </CardContent>
                  </Card>
                )}
                {(briefData as any).recent_invoices?.length > 0 && (
                  <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-1.5"><History className="h-4 w-4" />Recent Invoices</CardTitle></CardHeader>
                    <CardContent className="space-y-1">
                      {(briefData as any).recent_invoices.map((inv: any) => (
                        <div key={inv.id} className="text-xs flex justify-between">
                          <span className="text-muted-foreground">#{String(inv.id).slice(-8)}</span>
                          <span>{formatCurrency(inv.total_amount ?? inv.amount)}</span>
                          <Badge variant={inv.status === "paid" ? "default" : "secondary"} className="text-[10px]">{inv.status}</Badge>
                        </div>
                      ))}
                    </CardContent>
                  </Card>
                )}
              </>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-8">No brief data available.</p>
            )}
          </div>
        </SheetContent>
      </Sheet>

      {/* Product Availability Dialog */}
      <Dialog open={stockLeadId !== null} onOpenChange={(open) => { if (!open) setStockLeadId(null); }}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Package className="h-5 w-5 text-primary" />
              Product Availability
            </DialogTitle>
            <DialogDescription>Stock check for products of interest � Lead #{stockLeadId}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2 max-h-[60vh] overflow-y-auto py-2">
            {stockLoading ? (
              <div className="flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
            ) : ((stockData as any)?.availability ?? []).length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-6">No product interest linked to this lead, or no inventory data found.</p>
            ) : (
              ((stockData as any).availability as any[]).map((item: any, i: number) => (
                <Card key={i} className="border-border/60">
                  <CardContent className="p-3 flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate">{item.name ?? item.product_query}</p>
                      {item.sku && <p className="text-xs text-muted-foreground">SKU: {item.sku}</p>}
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      {item.quantity !== undefined && (
                        <span className="text-sm font-mono">{item.quantity} {item.unit ?? ""}</span>
                      )}
                      <Badge
                        variant={item.status === "in_stock" ? "default" : item.status === "low_stock" ? "outline" : "destructive"}
                        className="text-[10px]"
                      >
                        {item.status?.replace(/_/g, " ") ?? "unknown"}
                      </Badge>
                    </div>
                  </CardContent>
                </Card>
              ))
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setStockLeadId(null)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* New Lead Dialog */}
      <Dialog open={newLeadOpen} onOpenChange={setNewLeadOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Add New Lead</DialogTitle>
            <DialogDescription>Enter the details to add a new opportunity to the pipeline.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="text-sm font-medium">Company Name *</label>
              <Input placeholder="e.g. Lagos Island General Hospital" value={newLeadCompany} onChange={e => setNewLeadCompany(e.target.value)} />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-sm font-medium">Contact Person</label>
                <Input placeholder="Dr. Abiodun" value={newLeadContact} onChange={e => setNewLeadContact(e.target.value)} />
              </div>
              <div>
                <label className="text-sm font-medium">Phone</label>
                <Input placeholder="080..." value={newLeadPhone} onChange={e => setNewLeadPhone(e.target.value)} />
              </div>
            </div>
            <div>
              <label className="text-sm font-medium">Products Interested In</label>
              <Input placeholder="Lantus, MMR, Flu (comma-separated)" value={newLeadProducts} onChange={e => setNewLeadProducts(e.target.value)} />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-sm font-medium">Stage</label>
                <Select value={newLeadStage} onValueChange={setNewLeadStage}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {["new","qualified","proposal","negotiation","payment_plan"].map(s => (
                      <SelectItem key={s} value={s}>{STAGE_LABELS[s]}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-sm font-medium">Expected Value (₦)</label>
                <Input type="number" placeholder="5000000" value={newLeadValue} onChange={e => setNewLeadValue(e.target.value)} />
              </div>
            </div>
            <div>
              <label className="text-sm font-medium">Payment Terms</label>
              <Input placeholder="e.g. 30 days net" value={newLeadTerms} onChange={e => setNewLeadTerms(e.target.value)} />
            </div>
            <div>
              <label className="text-sm font-medium">Notes</label>
              <Textarea placeholder="Any context about this lead..." value={newLeadNotes} onChange={e => setNewLeadNotes(e.target.value)} rows={2} className="resize-none" />
            </div>
          </div>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setNewLeadOpen(false)}>Cancel</Button>
            <Button
              disabled={!newLeadCompany.trim() || createLead.isPending}
              onClick={() => createLead.mutate()}
              className="gap-2"
            >
              {createLead.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Add Lead
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Log Interaction Dialog */}
      <Dialog open={logLeadId !== null} onOpenChange={(o) => !o && setLogLeadId(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Log Interaction — Lead #{logLeadId}</DialogTitle>
            <DialogDescription>Record a call, visit, site visit, demo, or meeting.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="text-sm font-medium">Type</label>
              <Select value={logType} onValueChange={setLogType}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {["call","visit","site_visit","demo","email","whatsapp","meeting"].map(t => (
                    <SelectItem key={t} value={t}>{t.replace("_", " ").replace(/\b\w/g, c => c.toUpperCase())}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-sm font-medium">Summary *</label>
              <Textarea
                placeholder="e.g. Called Dr. Abiodun, confirmed interest in Lantus 100U. Requested quotation."
                value={logSummary}
                onChange={e => setLogSummary(e.target.value)}
                rows={3}
                className="resize-none"
              />
            </div>
            <div>
              <label className="text-sm font-medium">Outcome</label>
              <Input placeholder="e.g. Interested, requested sample" value={logOutcome} onChange={e => setLogOutcome(e.target.value)} />
            </div>
            <div>
              <label className="text-sm font-medium">Next Step</label>
              <Input placeholder="e.g. Send quotation by Friday" value={logNextStep} onChange={e => setLogNextStep(e.target.value)} />
            </div>
          </div>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setLogLeadId(null)}>Cancel</Button>
            <Button
              disabled={!logSummary.trim() || logInteractionMutation.isPending}
              onClick={() => logInteractionMutation.mutate()}
              className="gap-2"
            >
              {logInteractionMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Phone className="h-4 w-4" />}
              Log Interaction
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Set Target Dialog */}
      <Dialog open={newTargetOpen} onOpenChange={setNewTargetOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Set Sales Target</DialogTitle>
            <DialogDescription>Period: {targetPeriod}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="text-sm font-medium">Rep ID (leave blank for team)</label>
              <Input placeholder="UUID or leave blank for team target" value={ntRepId} onChange={e => setNtRepId(e.target.value)} />
            </div>
            <div>
              <label className="text-sm font-medium">Period Type</label>
              <Select value={ntPeriodType} onValueChange={setNtPeriodType}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="monthly">Monthly</SelectItem>
                  <SelectItem value="weekly">Weekly</SelectItem>
                  <SelectItem value="quarterly">Quarterly</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-sm font-medium">Target Value (₦) *</label>
              <Input type="number" placeholder="e.g. 50000000" value={ntValue} onChange={e => setNtValue(e.target.value)} />
            </div>
            <div>
              <label className="text-sm font-medium">Target Deals (optional)</label>
              <Input type="number" placeholder="e.g. 10" value={ntDeals} onChange={e => setNtDeals(e.target.value)} />
            </div>
          </div>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setNewTargetOpen(false)}>Cancel</Button>
            <Button
              disabled={!ntValue || createTarget.isPending}
              onClick={() => createTarget.mutate()}
              className="gap-2"
            >
              {createTarget.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <TrendingUp className="h-4 w-4" />}
              Save Target
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
