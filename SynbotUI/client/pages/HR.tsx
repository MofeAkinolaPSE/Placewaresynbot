import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { WorkforceDashboard } from "@/components/dashboards/WorkforceDashboard";
import { StaffDirectory } from "@/components/dashboards/StaffDirectory";
import { Button } from "@/components/ui/button";
import { UserPlus, Loader2 } from "lucide-react";
import { TimesheetsTable } from "@/components/dashboards/TimesheetsTable";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
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
      <div className="flex flex-col gap-1 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Human Resources</h1>
          <p className="text-sm text-muted-foreground">Workforce analytics and staff directory.</p>
        </div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button size="sm">
              <UserPlus className="mr-2 h-4 w-4" />
              Add Staff
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add New Staff Member</DialogTitle>
              <DialogDescription>Enter the details for the new staff member.</DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-4">
              <div className="grid grid-cols-4 items-center gap-4">
                <Label htmlFor="full_name" className="text-right">Full Name</Label>
                <Input
                  id="full_name"
                  className="col-span-3"
                  value={formData.full_name}
                  onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
                  placeholder="John Doe"
                />
              </div>
              <div className="grid grid-cols-4 items-center gap-4">
                <Label htmlFor="email" className="text-right">Email</Label>
                <Input
                  id="email"
                  type="email"
                  className="col-span-3"
                  value={formData.email}
                  onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                  placeholder="john.doe@company.com"
                />
              </div>
              <div className="grid grid-cols-4 items-center gap-4">
                <Label htmlFor="department" className="text-right">Department</Label>
                <Select
                  value={formData.department}
                  onValueChange={(val) => setFormData({ ...formData, department: val })}
                >
                  <SelectTrigger className="col-span-3">
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
              <div className="grid grid-cols-4 items-center gap-4">
                <Label htmlFor="role" className="text-right">Role</Label>
                <Input
                  id="role"
                  className="col-span-3"
                  value={formData.role}
                  onChange={(e) => setFormData({ ...formData, role: e.target.value })}
                  placeholder="Optional job title"
                />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
              <Button onClick={handleCreate} disabled={creating}>
                {creating && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Add Staff
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

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
