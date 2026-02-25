import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { WorkforceDashboard } from "@/components/dashboards/WorkforceDashboard";
import { StaffDirectory } from "@/components/dashboards/StaffDirectory";
import { Button } from "@/components/ui/button";
import { UserPlus } from "lucide-react";
import { TimesheetsTable } from "@/components/dashboards/TimesheetsTable";

const HR = () => {
  return (
    <div className="p-8 space-y-8">
      <div className="flex items-center justify-between">
        <div>
           <h2 className="text-3xl font-bold tracking-tight">Human Resources</h2>
           <p className="text-muted-foreground">Workforce analytics and staff directory.</p>
        </div>
        <Button>
           <UserPlus className="mr-2 h-4 w-4" />
           Add Staff
        </Button>
      </div>

      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="staff">Staff Directory</TabsTrigger>
          <TabsTrigger value="timesheets">Timesheets</TabsTrigger>
        </TabsList>
        <TabsContent value="overview" className="space-y-4">
           <WorkforceDashboard />
        </TabsContent>
        <TabsContent value="staff">
           <StaffDirectory />
        </TabsContent>
        <TabsContent value="timesheets">
            <TimesheetsTable />
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default HR;
