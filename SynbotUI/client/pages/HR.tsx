import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { WorkforceDashboard } from "@/components/dashboards/WorkforceDashboard";
import { StaffDirectory } from "@/components/dashboards/StaffDirectory";
import { Button } from "@/components/ui/button";
import { UserPlus, Loader2, Users } from "lucide-react";
import { TimesheetsTable } from "@/components/dashboards/TimesheetsTable";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api-client";
import { useToast } from "@/hooks/use-toast";
import { useQueryClient } from "@tanstack/react-query";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";
import { PageHeader } from "@/components/workspace/PageHeader";
import { DetailSheet } from "@/components/workspace/DetailSheet";

const HR = () => {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [formData, setFormData] = useState({ full_name: "", email: "", department: "Operations", role: "" });
  const { toast } = useToast();

  const invalidateHrQueries = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["dashboard-workforce"] }),
      queryClient.invalidateQueries({ queryKey: ["staff-list"] }),
      queryClient.invalidateQueries({ queryKey: ["staff-snapshot"] }),
      queryClient.invalidateQueries({ queryKey: ["timesheets"] }),
      queryClient.invalidateQueries({ queryKey: ["hr-summary"] }),
    ]);
  };

  useRealtimeChannel("workflow_updates", () => {
    void invalidateHrQueries();
  });

  useRealtimeChannel("alerts_updates", () => {
    void queryClient.invalidateQueries({ queryKey: ["hr-summary"] });
  });

  useRealtimeChannel("staff_updates", () => {
    void invalidateHrQueries();
  });

  const handleCreate = async () => {
    if (!formData.full_name.trim() || !formData.email.trim()) {
      toast({ title: "Validation Error", description: "Name and Email are required", variant: "destructive" });
      return;
    }
    try {
      setCreating(true);
      await api.staff.create({
        full_name: formData.full_name,
        email: formData.email,
        department: formData.department,
        role: formData.role || undefined,
      });
      toast({ title: "Staff Added", description: `${formData.full_name} has been registered.` });
      setDialogOpen(false);
      setFormData({ full_name: "", email: "", department: "Operations", role: "" });
      await invalidateHrQueries();
    } catch (err: any) {
      toast({ title: "Failed to Add Staff", description: err.message, variant: "destructive" });
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        icon={Users}
        title="Human Resources"
        subtitle="Workforce analytics and staff directory."
        actions={
          <Button size="sm" onClick={() => setDialogOpen(true)}>
            <UserPlus className="mr-2 h-4 w-4" />
            Add Staff
          </Button>
        }
      />

      <DetailSheet
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        title="Add New Staff Member"
        description="Enter the details for the new staff member."
        icon={UserPlus}
        footer={
          <Button onClick={handleCreate} disabled={creating} className="w-full">
            {creating && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Add Staff
          </Button>
        }
      >
        <div className="space-y-2">
          <Label htmlFor="full_name">Full Name</Label>
          <Input
            id="full_name"
            value={formData.full_name}
            onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
            placeholder="John Doe"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            value={formData.email}
            onChange={(e) => setFormData({ ...formData, email: e.target.value })}
            placeholder="john.doe@company.com"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="department">Department</Label>
          <Select
            value={formData.department}
            onValueChange={(val) => setFormData({ ...formData, department: val })}
          >
            <SelectTrigger id="department">
              <SelectValue placeholder="Select department" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="Finance">Finance</SelectItem>
              <SelectItem value="Sales">Sales</SelectItem>
              <SelectItem value="Operations">Operations</SelectItem>
              <SelectItem value="HR">HR</SelectItem>
              <SelectItem value="Management">Management</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="role">Role</Label>
          <Input
            id="role"
            value={formData.role}
            onChange={(e) => setFormData({ ...formData, role: e.target.value })}
            placeholder="Optional job title"
          />
        </div>
      </DetailSheet>

      <Tabs defaultValue="overview">
        <TabsList className="mb-4">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="staff">Staff Directory</TabsTrigger>
          <TabsTrigger value="timesheets">Timesheets</TabsTrigger>
        </TabsList>
        <TabsContent value="overview">
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
