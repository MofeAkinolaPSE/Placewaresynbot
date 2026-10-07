/**
 * Inventory & Quality › Compliance & QMS: the quality system as scheduled work.
 *   Audits       - schedule, start, complete (report PDF), recurring audits book the next one
 *   Deviations   - the single deviation & CAPA register (QC's batch rejections land here too)
 *   Maintenance  - equipment and its service schedule; a missed service raises a deviation that moves the date
 *   SOPs, Documents - unchanged
 * Everything with a date appears on the Logistics Calendar. Recalls are on Quality Control.
 */
import { useSearchParams } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/components/workspace/PageHeader";
import { DrillProvider } from "@/components/books/lineage";
import { QualityActionsProvider } from "@/components/quality/actions";
import { DeviationsPanel } from "@/components/quality/panels";
import { AuditsPanel, MaintenancePanel } from "@/components/quality/compliance-panels";
import { DocumentsTab, SopTab } from "@/components/quality/ComplianceLibrary";

export default function Compliance() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "audits";
  return (
    <DrillProvider>
      <QualityActionsProvider>
        <div className="space-y-5">
          <PageHeader icon={ShieldCheck} title="Compliance & QMS" subtitle="Audits · deviations & CAPA · maintenance · SOPs - all dated work shows on the calendar" />
          <Tabs value={tab} onValueChange={(t) => setParams({ tab: t }, { replace: true })}>
            <TabsList>
              <TabsTrigger value="audits">Audits</TabsTrigger>
              <TabsTrigger value="deviations">Deviations & CAPA</TabsTrigger>
              <TabsTrigger value="maintenance">Maintenance</TabsTrigger>
              <TabsTrigger value="sop">SOPs</TabsTrigger>
              <TabsTrigger value="documents">Documents</TabsTrigger>
            </TabsList>
            <TabsContent value="audits" className="mt-4"><AuditsPanel /></TabsContent>
            <TabsContent value="deviations" className="mt-4"><DeviationsPanel /></TabsContent>
            <TabsContent value="maintenance" className="mt-4"><MaintenancePanel /></TabsContent>
            <TabsContent value="sop" className="mt-4"><SopTab /></TabsContent>
            <TabsContent value="documents" className="mt-4"><DocumentsTab /></TabsContent>
          </Tabs>
        </div>
      </QualityActionsProvider>
    </DrillProvider>
  );
}
