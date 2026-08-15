import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import LeadsQueue from "@/components/leads/LeadsQueue";
import WalkInForm from "@/components/leads/WalkInForm";
import { PageHeader } from "@/components/workspace/PageHeader";
import { DetailSheet } from "@/components/workspace/DetailSheet";

export default function LeadsPage() {
  const [sheetOpen, setSheetOpen] = useState(false);
  const queryClient = useQueryClient();

  return (
    <div className="p-8 space-y-6">
      <PageHeader
        icon={UserPlus}
        title="Leads"
        subtitle="Manage incoming leads and record manual walk-ins."
        actions={
          <Button onClick={() => setSheetOpen(true)} className="gap-2">
            <UserPlus className="h-4 w-4" /> Record Walk-in
          </Button>
        }
      />

      <LeadsQueue />

      {/* Record Walk-in / Manual Lead — was a permanent inline form, the
          clearest possible Ch.5.2 candidate (ephemeral create task with no
          natural inline home). */}
      <DetailSheet
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        title="Record Walk-in / Manual Lead"
        icon={UserPlus}
      >
        <WalkInForm
          onSuccess={() => {
            setSheetOpen(false);
            void queryClient.invalidateQueries({ queryKey: ["admin-leads"] });
          }}
        />
      </DetailSheet>
    </div>
  );
}
