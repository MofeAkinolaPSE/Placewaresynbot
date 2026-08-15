import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { PlusCircle, Loader2, TruckIcon, RefreshCcw, ShieldCheck, AlertTriangle, Star, PackageCheck } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api-client";
import { useIsMobile } from "@/hooks/use-mobile";
import { PageHeader } from "@/components/workspace/PageHeader";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { DetailSheet } from "@/components/workspace/DetailSheet";

interface Supplier {
  id?: string;
  name: string;
  contact_name?: string;
  contact_email?: string;
  phone?: string;
  address?: string;
  payment_terms?: string;
  tax_id?: string;
  bank_details?: string;
  current_balance?: number;
  status?: string;
  created_at?: string;
  // Agent-computed metric columns
  reliability_score?: number;
  avg_delay_days?: number;
  rejection_count?: number;
  total_shipments?: number;
  compliance_issues?: number;
}

interface SupplierMetrics {
  total_deliveries: number;
  avg_lead_time_days: number;
  on_time_rate: number;
  quality_score: number;
}

export default function Suppliers() {
  const isMobile = useIsMobile();
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [formData, setFormData] = useState({
    name: "",
    contact_name: "",
    contact_email: "",
    phone: "",
    address: "",
    payment_terms: "",
    tax_id: "",
    bank_details: "",
    current_balance: "",
  });
  const [selectedMetrics, setSelectedMetrics] = useState<{ name: string; metrics: SupplierMetrics } | null>(null);
  const { toast } = useToast();

  const fetchSuppliers = async () => {
    try {
      setLoading(true);
      const data = await api.suppliers.list();
      setSuppliers(Array.isArray(data) ? data : (Array.isArray((data as any)?.data) ? (data as any).data : []));
    } catch (err: any) {
      toast({ title: "Error", description: err.message, variant: "destructive" });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSuppliers();
  }, []);

  const handleCreate = async () => {
    if (!formData.name.trim()) {
      toast({ title: "Error", description: "Name is required", variant: "destructive" });
      return;
    }
    try {
      setCreating(true);
      await api.suppliers.create({
        ...formData,
        current_balance: formData.current_balance ? parseFloat(formData.current_balance) : undefined,
      });
      toast({ title: "Supplier Created" });
      setDialogOpen(false);
      setFormData({
        name: "",
        contact_name: "",
        contact_email: "",
        phone: "",
        address: "",
        payment_terms: "",
        tax_id: "",
        bank_details: "",
        current_balance: "",
      });
      fetchSuppliers();
    } catch (err: any) {
      toast({ title: "Failed", description: err.message, variant: "destructive" });
    } finally {
      setCreating(false);
    }
  };

  const viewMetrics = async (supplierName: string) => {
    try {
      const data = await api.suppliers.metrics(supplierName);
      const metrics: SupplierMetrics = {
        total_deliveries: Number(data?.deliveries_count || 0),
        avg_lead_time_days: Number(data?.avg_delivery_time_hours || 0) / 24,
        on_time_rate: Number(data?.on_time_rate || 0),
        quality_score: Number(data?.reliability_score || 0) / 100,
      };
      setSelectedMetrics({ name: supplierName, metrics });
    } catch (err: any) {
      toast({ title: "No metrics available", description: err.message, variant: "destructive" });
    }
  };

  // ── KPI aggregates derived from suppliers data ─────────────────────────
  const totalSuppliers = suppliers.length;
  const activeSuppliers = suppliers.filter((s) => (s.status || "active") === "active").length;
  const avgReliability =
    suppliers.filter((s) => s.reliability_score != null).length > 0
      ? suppliers.reduce((sum, s) => sum + (s.reliability_score ?? 0), 0) /
        suppliers.filter((s) => s.reliability_score != null).length
      : null;
  const totalBalance = suppliers.reduce((sum, s) => sum + (s.current_balance ?? 0), 0);
  const complianceIssues = suppliers.reduce((sum, s) => sum + (s.compliance_issues ?? 0), 0);
  const avgDelayDays =
    suppliers.filter((s) => s.avg_delay_days != null).length > 0
      ? suppliers.reduce((sum, s) => sum + (s.avg_delay_days ?? 0), 0) /
        suppliers.filter((s) => s.avg_delay_days != null).length
      : null;

  return (
    <div className="p-8 space-y-8">
      <PageHeader
        icon={TruckIcon}
        title="Supplier Management"
        subtitle="Track suppliers, deliveries, and performance metrics."
        actions={
          <>
            <Button variant="outline" onClick={fetchSuppliers} disabled={loading}>
              <RefreshCcw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </Button>
            <Button onClick={() => setDialogOpen(true)}>
              <PlusCircle className="mr-2 h-4 w-4" />
              Add Supplier
            </Button>
          </>
        }
      />

      <DetailSheet
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        title="Add New Supplier"
        description="Enter supplier details."
        icon={TruckIcon}
        footer={
          <Button onClick={handleCreate} disabled={creating} className="w-full">
            {creating && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Create
          </Button>
        }
      >
        <div className="space-y-2">
          <Label>Name</Label>
          <Input
            value={formData.name}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            placeholder="Supplier name"
          />
        </div>
        <div className="space-y-2">
          <Label>Contact</Label>
          <Input
            value={formData.contact_name}
            onChange={(e) => setFormData({ ...formData, contact_name: e.target.value })}
            placeholder="Contact person name"
          />
        </div>
        <div className="space-y-2">
          <Label>Email</Label>
          <Input
            type="email"
            value={formData.contact_email}
            onChange={(e) => setFormData({ ...formData, contact_email: e.target.value })}
          />
        </div>
        <div className="space-y-2">
          <Label>Phone</Label>
          <Input
            value={formData.phone}
            onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
          />
        </div>
        <div className="space-y-2">
          <Label>Address</Label>
          <Input
            value={formData.address}
            onChange={(e) => setFormData({ ...formData, address: e.target.value })}
          />
        </div>
        <div className="space-y-2">
          <Label>Payment Terms</Label>
          <Input
            value={formData.payment_terms}
            onChange={(e) => setFormData({ ...formData, payment_terms: e.target.value })}
            placeholder="e.g. Net 30"
          />
        </div>
        <div className="space-y-2">
          <Label>Tax ID</Label>
          <Input
            value={formData.tax_id}
            onChange={(e) => setFormData({ ...formData, tax_id: e.target.value })}
          />
        </div>
        <div className="space-y-2">
          <Label>Bank Details</Label>
          <Input
            value={formData.bank_details}
            onChange={(e) => setFormData({ ...formData, bank_details: e.target.value })}
            placeholder="Bank — Account number"
          />
        </div>
        <div className="space-y-2">
          <Label>Balance (₦)</Label>
          <Input
            type="number"
            value={formData.current_balance}
            onChange={(e) => setFormData({ ...formData, current_balance: e.target.value })}
            placeholder="0.00"
          />
        </div>
      </DetailSheet>

      {/* ── KPI Summary ──────────────────────────────────────────── */}
      <KpiStrip
        items={[
          { label: "Total Suppliers", value: totalSuppliers, icon: TruckIcon },
          { label: "Avg Reliability", value: avgReliability != null ? `${avgReliability.toFixed(1)}%` : "—", icon: Star },
          { label: "Avg Delay", value: avgDelayDays != null ? `${avgDelayDays.toFixed(1)} d` : "—", icon: RefreshCcw },
          { label: "Total Shipments", value: suppliers.reduce((s, r) => s + (r.total_shipments ?? 0), 0).toLocaleString(), icon: PackageCheck },
          { label: "Outstanding (₦)", value: totalBalance.toLocaleString("en-NG", { maximumFractionDigits: 0 }), icon: ShieldCheck },
          { label: "Compliance Issues", value: complianceIssues, icon: AlertTriangle, tone: complianceIssues > 0 ? "danger" : "default" },
        ]}
      />

      <Card>
        <CardHeader>
          <CardTitle>Suppliers</CardTitle>
          <CardDescription>All registered suppliers and their performance.</CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : suppliers.length === 0 ? (
            <p className="text-center text-muted-foreground py-8">No suppliers registered yet. Upload a vendors.csv via Sage Import to populate this list.</p>
          ) : isMobile ? (
            <div className="space-y-3">
              {suppliers.map((s, i) => (
                <Card key={s.id || i} className="border-border/60">
                  <CardHeader className="pb-2">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <CardTitle className="text-base leading-tight">{s.name}</CardTitle>
                        <CardDescription>{s.contact_name || "No contact"}</CardDescription>
                      </div>
                      <Badge variant={s.status === "active" ? "default" : "secondary"}>
                        {s.status || "active"}
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-2 text-sm">
                    <div className="flex justify-between gap-3">
                      <span className="text-muted-foreground">Phone</span>
                      <span className="truncate text-right">{s.phone || "-"}</span>
                    </div>
                    <div className="flex justify-between gap-3">
                      <span className="text-muted-foreground">Balance</span>
                      <span className="tabular-nums text-right">
                        {s.current_balance != null
                          ? `₦${s.current_balance.toLocaleString("en-NG", { maximumFractionDigits: 2 })}`
                          : "-"}
                      </span>
                    </div>
                    <div className="flex justify-between gap-3">
                      <span className="text-muted-foreground">Reliability</span>
                      <span className="text-right">{s.reliability_score != null ? `${s.reliability_score.toFixed(1)}%` : "—"}</span>
                    </div>
                    <div className="flex justify-between gap-3">
                      <span className="text-muted-foreground">Compliance issues</span>
                      <span className={s.compliance_issues && s.compliance_issues > 0 ? "font-semibold text-destructive" : ""}>
                        {s.compliance_issues ?? "—"}
                      </span>
                    </div>
                    <div className="pt-2">
                      <Button size="sm" variant="outline" className="w-full" onClick={() => viewMetrics(s.name)}>
                        <TruckIcon className="mr-1 h-3 w-3" />
                        View Metrics
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="sticky left-0 z-10 min-w-[180px] bg-muted/90">Name</TableHead>
                    <TableHead className="min-w-[140px]">Contact</TableHead>
                    <TableHead className="min-w-[200px] hidden md:table-cell">Email</TableHead>
                    <TableHead className="min-w-[150px] hidden md:table-cell">Phone</TableHead>
                    <TableHead className="min-w-[220px] hidden lg:table-cell">Address</TableHead>
                    <TableHead className="min-w-[110px] hidden xl:table-cell">Payment Terms</TableHead>
                    <TableHead className="min-w-[140px] hidden xl:table-cell">Tax ID</TableHead>
                    <TableHead className="min-w-[200px] hidden xl:table-cell">Bank Details</TableHead>
                    <TableHead className="min-w-[130px] text-right">Balance (₦)</TableHead>
                    <TableHead className="min-w-[90px]">Status</TableHead>
                    <TableHead className="min-w-[110px] text-right">Reliability</TableHead>
                    <TableHead className="min-w-[100px] text-right hidden lg:table-cell">Avg Delay</TableHead>
                    <TableHead className="min-w-[110px] text-right hidden lg:table-cell">Shipments</TableHead>
                    <TableHead className="min-w-[100px] text-right">Compliance</TableHead>
                    <TableHead className="min-w-[90px] text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {suppliers.map((s, i) => (
                    <TableRow key={s.id || i}>
                      <TableCell className="sticky left-0 z-10 bg-background font-medium whitespace-nowrap">{s.name}</TableCell>
                      <TableCell className="whitespace-nowrap">{s.contact_name || "-"}</TableCell>
                      <TableCell className="hidden md:table-cell">{s.contact_email || "-"}</TableCell>
                      <TableCell className="whitespace-nowrap hidden md:table-cell">{s.phone || "-"}</TableCell>
                      <TableCell className="hidden lg:table-cell">{s.address || "-"}</TableCell>
                      <TableCell className="whitespace-nowrap hidden xl:table-cell">{s.payment_terms || "-"}</TableCell>
                      <TableCell className="whitespace-nowrap hidden xl:table-cell">{s.tax_id || "-"}</TableCell>
                      <TableCell className="whitespace-nowrap hidden xl:table-cell">{s.bank_details || "-"}</TableCell>
                      <TableCell className="text-right whitespace-nowrap">
                        {s.current_balance != null
                          ? s.current_balance.toLocaleString("en-NG", { minimumFractionDigits: 2 })
                          : "-"}
                      </TableCell>
                      <TableCell>
                        <Badge variant={s.status === "active" ? "default" : "secondary"}>
                          {s.status || "active"}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right whitespace-nowrap">
                        {s.reliability_score != null ? `${s.reliability_score.toFixed(1)}%` : "—"}
                      </TableCell>
                      <TableCell className="text-right whitespace-nowrap hidden lg:table-cell">
                        {s.avg_delay_days != null ? `${s.avg_delay_days.toFixed(1)} d` : "—"}
                      </TableCell>
                      <TableCell className="text-right whitespace-nowrap hidden lg:table-cell">
                        {s.total_shipments ?? "—"}
                      </TableCell>
                      <TableCell className="text-right whitespace-nowrap">
                        {s.compliance_issues != null ? (
                          <span className={s.compliance_issues > 0 ? "text-destructive font-semibold" : ""}>
                            {s.compliance_issues}
                          </span>
                        ) : "—"}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button size="sm" variant="outline" onClick={() => viewMetrics(s.name)}>
                          <TruckIcon className="mr-1 h-3 w-3" />
                          Metrics
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Metrics Modal */}
      {selectedMetrics && (
        <Dialog open={!!selectedMetrics} onOpenChange={() => setSelectedMetrics(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Metrics: {selectedMetrics.name}</DialogTitle>
            </DialogHeader>
            <div className="grid grid-cols-2 gap-4 py-4">
              <div className="text-center p-4 bg-muted rounded">
                <p className="text-2xl font-bold">{selectedMetrics.metrics.total_deliveries}</p>
                <p className="text-sm text-muted-foreground">Total Deliveries</p>
              </div>
              <div className="text-center p-4 bg-muted rounded">
                <p className="text-2xl font-bold">{selectedMetrics.metrics.avg_lead_time_days.toFixed(1)}</p>
                <p className="text-sm text-muted-foreground">Avg Lead Time (days)</p>
              </div>
              <div className="text-center p-4 bg-muted rounded">
                <p className="text-2xl font-bold">{(selectedMetrics.metrics.on_time_rate * 100).toFixed(0)}%</p>
                <p className="text-sm text-muted-foreground">On-Time Rate</p>
              </div>
              <div className="text-center p-4 bg-muted rounded">
                <p className="text-2xl font-bold">{(selectedMetrics.metrics.quality_score * 100).toFixed(0)}%</p>
                <p className="text-sm text-muted-foreground">Quality Score</p>
              </div>
            </div>
            <DialogFooter>
              <Button onClick={() => setSelectedMetrics(null)}>Close</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
