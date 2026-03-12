import { useState } from "react";
import {
  CheckCircle,
  XCircle,
  Clock,
  AlertCircle,
  ChevronRight,
  MessageSquare,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { toast } from "sonner";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";

const Workflow = () => {
  const [selectedIntent, setSelectedIntent] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [approvalReason, setApprovalReason] = useState("");
  const [attestationText, setAttestationText] = useState(
    "I attest this workflow approval decision is authorized and reviewed.",
  );

  const queryClient = useQueryClient();

  useRealtimeChannel("workflow_updates", (message) => {
    const evt = message?.event;
    if (!evt) return;
    if (["batch_locked", "batch_unlocked", "batch_approved", "task_created", "subscriber_joined"].includes(evt)) {
      queryClient.invalidateQueries({ queryKey: ["workflow-pending"] });
      queryClient.invalidateQueries({ queryKey: ["audit-logs"] });
    }
  });

  const {
    data: fetchedIntents,
    error: intentsError,
    isError: intentsIsError,
  } = useQuery({
    queryKey: ["workflow-pending"],
    queryFn: () => api.workflow.pending(),
  });

  const {
    data: auditLogs,
    error: auditError,
    isError: auditIsError,
  } = useQuery({
    queryKey: ["audit-logs"],
    queryFn: () => api.audit.logs(),
  });

  const approvalMutation = useMutation({
    mutationFn: async (params: {
      intentId: string;
      approved: boolean;
      note: string;
      reason: string;
      attestation: string;
    }) => {
      return api.workflow.approve(
        params.intentId,
        params.approved,
        params.note || undefined,
        params.reason,
        params.attestation,
      );
    },
    onSuccess: (_data, variables) => {
      toast.success(variables.approved ? "Intent approved" : "Intent rejected");
      setNotes("");
      setApprovalReason("");
      setAttestationText("I attest this workflow approval decision is authorized and reviewed.");
      setSelectedIntent(null);
      queryClient.invalidateQueries({ queryKey: ["workflow-pending"] });
      queryClient.invalidateQueries({ queryKey: ["audit-logs"] });
    },
    onError: (error: any) => {
      console.error("Workflow approval failed", error);
      toast.error("Failed to submit decision. Please try again.");
    },
  });

  const rawIntents = Array.isArray(fetchedIntents) ? fetchedIntents : [];
  const invalidIntentCount = rawIntents.filter((intent: any) => {
    const hasId = Boolean(intent?.intent_id || intent?.id);
    const hasType = Boolean(intent?.intent_type);
    const hasCustomer = Boolean(intent?.payload?.customer_id);
    return !(hasId && hasType && hasCustomer);
  }).length;

  const pendingIntents = rawIntents.filter((intent: any) => {
    const hasId = Boolean(intent?.intent_id || intent?.id);
    const hasType = Boolean(intent?.intent_type);
    const hasCustomer = Boolean(intent?.payload?.customer_id);
    return hasId && hasType && hasCustomer;
  }).map((intent: any) => {
    const amountRaw = intent.payload?.amount;
    const amountNumber = typeof amountRaw === "number" ? amountRaw : parseFloat(amountRaw || "0");
    let priority: "high" | "medium" | "low" = "low";
    if (amountNumber >= 2000000) {
      priority = "high";
    } else if (amountNumber >= 500000) {
      priority = "medium";
    }

    return {
      id: intent.intent_id || intent.id,
      type: intent.intent_type,
      customer: intent.payload.customer_id,
      amount: amountRaw ? `₦${amountRaw}` : "",
      reason: intent.payload?.reason || "",
      context: intent.payload?.context || "",
      priority,
      submittedBy: "System",
      submittedDate: intent.created_at,
      recommendation: intent.recommendation ? JSON.stringify(intent.recommendation) : "",
      status: intent.status || "pending",
    };
  });

  const rawAuditLogs = Array.isArray(auditLogs) ? auditLogs : [];
  const auditTrail = rawAuditLogs.map((log: any) => ({
    id: log.id,
    date: log.created_at,
    user: log.actor_id || "unknown",
    action: log.event_type,
    details: JSON.stringify(log.details || {}),
    signatureHashRef: log.signature_hash_ref || "",
    status: log.event_type && log.event_type.endsWith("approved") ? "approved" : "submitted",
  }));

  const activeIntent =
    pendingIntents.find((i: any) => i.id === selectedIntent) || pendingIntents[0];

  const handleApprove = () => {
    const current = activeIntent;
    if (!current) return;
    if (!approvalReason.trim() || !attestationText.trim()) {
      toast.error("Approval reason and attestation are required");
      return;
    }
    approvalMutation.mutate({
      intentId: current.id,
      approved: true,
      note: notes,
      reason: approvalReason,
      attestation: attestationText,
    });
  };

  const handleReject = () => {
    const current = activeIntent;
    if (!current) return;
    if (!approvalReason.trim() || !attestationText.trim()) {
      toast.error("Approval reason and attestation are required");
      return;
    }
    approvalMutation.mutate({
      intentId: current.id,
      approved: false,
      note: notes,
      reason: approvalReason,
      attestation: attestationText,
    });
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "approved":
        return <CheckCircle className="w-4 h-4 text-success" />;
      case "rejected":
        return <XCircle className="w-4 h-4 text-destructive" />;
      default:
        return <Clock className="w-4 h-4 text-muted-foreground" />;
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case "approved":
        return "bg-success/15 text-success";
      case "rejected":
        return "bg-destructive/10 text-destructive";
      case "pending":
        return "bg-warning/15 text-warning";
      default:
        return "bg-muted text-muted-foreground";
    }
  };

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case "high":
        return "bg-destructive/10 border-destructive/30 text-destructive";
      case "medium":
        return "bg-warning/15 border-warning/30 text-warning";
      case "low":
        return "bg-info/15 border-info/30 text-info";
      default:
        return "";
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionTransitions.standard}
      className="space-y-8"
    >
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-foreground">Workflow</h1>
        <p className="text-muted-foreground mt-2">
          Approval workflows and governance for business decisions
        </p>
      </div>

      <Tabs defaultValue="pending" className="w-full">
        <TabsList className="grid w-full max-w-md grid-cols-2">
          <TabsTrigger value="pending">Pending ({pendingIntents.length})</TabsTrigger>
          <TabsTrigger value="audit">Audit Trail</TabsTrigger>
        </TabsList>

        {/* Pending Intents Tab */}
        <TabsContent value="pending" className="space-y-6">
          {intentsIsError && (
            <p className="text-sm text-destructive">
              Data error: {(intentsError as Error)?.message || "Failed to load pending intents."}
            </p>
          )}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Intent List */}
            <div className="lg:col-span-1 space-y-2">
              <h2 className="font-semibold text-foreground mb-4">
                Pending Intents
              </h2>
              {invalidIntentCount > 0 && (
                <p className="text-sm text-destructive mb-2">
                  Data error: {invalidIntentCount} pending intent record(s) are missing required fields.
                </p>
              )}
              {pendingIntents.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  No pending workflow intents. New requests will appear here.
                </p>
              )}
              {pendingIntents.map((intent) => (
                <button
                  key={intent.id}
                  onClick={() => setSelectedIntent(intent.id)}
                  className={`w-full text-left p-4 rounded-lg border-2 transition-colors ${
                    selectedIntent === intent.id
                      ? "border-primary bg-primary/10"
                      : "border-border/60 hover:border-primary/50 bg-background/70"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <p className="font-medium text-foreground text-sm">
                      {intent.type}
                    </p>
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-medium flex-shrink-0 ${
                        intent.priority === "high"
                          ? "bg-destructive/10 text-destructive"
                          : intent.priority === "medium"
                            ? "bg-warning/15 text-warning"
                            : "bg-info/15 text-info"
                      }`}
                    >
                      {intent.priority.charAt(0).toUpperCase() +
                        intent.priority.slice(1)}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {intent.customer}
                  </p>
                  <p className="text-sm font-semibold text-primary mt-1">
                    {intent.amount}
                  </p>
                </button>
              ))}
            </div>

            {/* Detail Panel */}
            {activeIntent && (
              <div className="lg:col-span-2 pw-surface-interactive p-6 space-y-6">
                {/* Header */}
                <div className="border-b border-border pb-4">
                  <div className="flex items-start justify-between mb-3">
                    <div>
                      <h3 className="text-lg font-bold text-foreground">
                        {activeIntent.type}
                      </h3>
                      <p className="text-muted-foreground mt-1">
                        {activeIntent.customer}
                      </p>
                    </div>
                    <span
                      className={`px-3 py-1 rounded text-xs font-medium ${getPriorityColor(
                        activeIntent.priority
                      )} border`}
                    >
                      {activeIntent.priority.toUpperCase()} PRIORITY
                    </span>
                  </div>
                  <p className="text-2xl font-bold text-primary">
                    {activeIntent.amount}
                  </p>
                </div>

                {/* Reason */}
                <div>
                  <h4 className="font-semibold text-foreground mb-2">Reason</h4>
                  <p className="text-sm text-muted-foreground">
                    {activeIntent.reason}
                  </p>
                </div>

                {/* Context */}
                <div>
                  <h4 className="font-semibold text-foreground mb-2">Context</h4>
                  <p className="text-sm text-muted-foreground bg-muted/30 p-3 rounded">
                    {activeIntent.context}
                  </p>
                </div>

                {/* Recommendation */}
                <div className="rounded-xl border border-info/30 bg-info/15 p-4">
                  <div className="flex gap-3">
                    <AlertCircle className="w-5 h-5 text-info flex-shrink-0 mt-0.5" />
                    <div>
                      <p className="font-semibold text-info text-sm">
                        Recommendation
                      </p>
                      <p className="text-sm text-info mt-1">
                        {activeIntent.recommendation}
                      </p>
                    </div>
                  </div>
                </div>

                {/* Submitted Info */}
                <div className="text-xs text-muted-foreground space-y-1">
                  <p>
                    <span className="font-medium">Submitted by:</span>{" "}
                    {activeIntent.submittedBy}
                  </p>
                  <p>
                    <span className="font-medium">Date:</span>{" "}
                    {activeIntent.submittedDate}
                  </p>
                </div>

                {/* Notes */}
                <div>
                  <h4 className="font-semibold text-foreground mb-2 flex items-center gap-2">
                    <MessageSquare className="w-4 h-4" />
                    Approval Notes
                  </h4>
                  <Textarea
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="Add your notes before approval/rejection..."
                    className="min-h-24"
                  />
                </div>

                <div>
                  <h4 className="font-semibold text-foreground mb-2">Approval Reason</h4>
                  <Textarea
                    value={approvalReason}
                    onChange={(e) => setApprovalReason(e.target.value)}
                    placeholder="Why this decision is approved or rejected"
                    className="min-h-16"
                  />
                </div>

                <div>
                  <h4 className="font-semibold text-foreground mb-2">Attestation</h4>
                  <Textarea
                    value={attestationText}
                    onChange={(e) => setAttestationText(e.target.value)}
                    className="min-h-20"
                  />
                </div>

                {/* Action Buttons */}
                <div className="flex gap-3 pt-4 border-t border-border">
                  <Button
                    onClick={handleApprove}
                    className="flex-1 bg-success hover:bg-success/90"
                    disabled={approvalMutation.isPending}
                  >
                    <CheckCircle className="w-4 h-4 mr-2" />
                    Approve
                  </Button>
                  <Button
                    onClick={handleReject}
                    variant="destructive"
                    className="flex-1"
                    disabled={approvalMutation.isPending}
                  >
                    <XCircle className="w-4 h-4 mr-2" />
                    Reject
                  </Button>
                </div>
              </div>
            )}
          </div>
        </TabsContent>

        {/* Audit Trail Tab */}
        <TabsContent value="audit" className="space-y-4">
          <div className="bg-card border border-border rounded-lg p-6">
            <h2 className="font-semibold text-foreground mb-4">Audit Trail</h2>

            {auditIsError && (
              <p className="text-sm text-destructive mb-4">
                Data error: {(auditError as Error)?.message || "Failed to load audit logs."}
              </p>
            )}

            <div className="space-y-4">
              {auditTrail.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  No audit entries yet. Approvals and rejections will appear here.
                </p>
              )}
              {auditTrail.map((entry) => (
                <div key={entry.id} className="pw-surface-base rounded-xl p-4">
                  <div className="flex items-start gap-4">
                    <div className="mt-1">{getStatusIcon(entry.status)}</div>
                    <div className="flex-1">
                      <div className="flex items-center justify-between">
                        <p className="font-medium text-foreground">
                          {entry.action}
                        </p>
                        <span
                          className={`px-2 py-0.5 rounded text-xs font-medium ${getStatusColor(
                            entry.status
                          )}`}
                        >
                          {entry.status.charAt(0).toUpperCase() +
                            entry.status.slice(1)}
                        </span>
                      </div>
                      <p className="text-sm text-muted-foreground mt-1">
                        {entry.details}
                      </p>
                      {entry.signatureHashRef && (
                        <p className="text-xs text-muted-foreground mt-1">
                          Signature Hash: {entry.signatureHashRef}
                        </p>
                      )}
                      <div className="flex items-center gap-4 text-xs text-muted-foreground mt-2">
                        <span>{entry.user}</span>
                        <span>•</span>
                        <span>{entry.date}</span>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <p className="text-xs text-muted-foreground mt-4">
              All workflow approvals and rejections are logged in this audit
              trail for compliance and transparency.
            </p>
          </div>
        </TabsContent>
      </Tabs>
    </motion.div>
  );
};

export default Workflow;
