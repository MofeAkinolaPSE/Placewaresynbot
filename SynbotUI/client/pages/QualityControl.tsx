/**
 * Inventory & Quality › Quality Control: product-facing QC.
 *   Release   - Frontdesk invoices waiting for QC, and incoming batches (held in quarantine in
 *               ACE Books until released; rejected batches raise a deviation)
 *   Expiry    - ACE Books lots grouped by product, with quarantine / write-off / recall per lot
 *   Recalls   - QMS case + ACE Books recall together (batch frozen, buyers traced, returns)
 *   Temperature - unchanged until the client's temperature-monitoring system is connected
 * Deviations & CAPA live on Compliance & QMS (one list for the whole company).
 */
import { useSearchParams } from "react-router-dom";
import { ClipboardCheck } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/components/workspace/PageHeader";
import { DrillProvider } from "@/components/books/lineage";
import { QualityActionsProvider } from "@/components/quality/actions";
import { ExpiryByProduct, RecallsPanel, ReleaseQueue } from "@/components/quality/panels";
import { TemperatureTab } from "@/components/quality/TemperatureTab";

export default function QualityControl() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "release";
  return (
    <DrillProvider>
      <QualityActionsProvider>
        <div className="space-y-5">
          <PageHeader icon={ClipboardCheck} title="Quality Control" subtitle="Release · expiry · recalls - stock status is kept in ACE Books" />
          <Tabs value={tab} onValueChange={(t) => setParams({ tab: t }, { replace: true })}>
            <TabsList>
              <TabsTrigger value="release">Release queue</TabsTrigger>
              <TabsTrigger value="expiry">Expiry</TabsTrigger>
              <TabsTrigger value="recalls">Recalls</TabsTrigger>
              <TabsTrigger value="temperature">Temperature</TabsTrigger>
            </TabsList>
            <TabsContent value="release" className="mt-4"><ReleaseQueue /></TabsContent>
            <TabsContent value="expiry" className="mt-4"><ExpiryByProduct /></TabsContent>
            <TabsContent value="recalls" className="mt-4"><RecallsPanel /></TabsContent>
            <TabsContent value="temperature" className="mt-4">
              <p className="mb-3 text-xs text-muted-foreground">Manual readings for now; live readings will come from the temperature-monitoring system once it is connected.</p>
              <TemperatureTab />
            </TabsContent>
          </Tabs>
        </div>
      </QualityActionsProvider>
    </DrillProvider>
  );
}
