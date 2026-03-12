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
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { PlusCircle, Loader2, TruckIcon, RefreshCcw } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { apiUrl } from "@/lib/api-base";
import { authClient } from "@/lib/auth-client";

interface Supplier {
  id?: string;
  name: string;
  contact_email?: string;
  phone?: string;
  address?: string;
  status?: string;
  created_at?: string;
}

interface SupplierMetrics {
  total_deliveries: number;
  avg_lead_time_days: number;
  on_time_rate: number;
  quality_score: number;
}

async function fetchWithAuth<T>(endpoint: string): Promise<T> {
  const token = authClient.getAccessToken();
  const res = await fetch(apiUrl(endpoint), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function postWithAuth<T>(endpoint: string, body: Record<string, any>): Promise<T> {
  const token = authClient.getAccessToken();
  const res = await fetch(apiUrl(endpoint), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export default function Suppliers() {
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [formData, setFormData] = useState({ name: "", contact_email: "", phone: "", address: "" });
  const [selectedMetrics, setSelectedMetrics] = useState<{ name: string; metrics: SupplierMetrics } | null>(null);
  const { toast } = useToast();

  const fetchSuppliers = async () => {
    try {
      setLoading(true);
      const data = await fetchWithAuth<any>("/suppliers");
      setSuppliers(Array.isArray(data) ? data : (Array.isArray(data?.data) ? data.data : []));
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
      await postWithAuth("/suppliers", formData);
      toast({ title: "Supplier Created" });
      setDialogOpen(false);
      setFormData({ name: "", contact_email: "", phone: "", address: "" });
      fetchSuppliers();
    } catch (err: any) {
      toast({ title: "Failed", description: err.message, variant: "destructive" });
    } finally {
      setCreating(false);
    }
  };

  const viewMetrics = async (supplierName: string) => {
    try {
      const data = await fetchWithAuth<any>(`/suppliers/${encodeURIComponent(supplierName)}/metrics`);
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

  return (
    <div className="p-8 space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Supplier Management</h2>
          <p className="text-muted-foreground">Track suppliers, deliveries, and performance metrics.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={fetchSuppliers} disabled={loading}>
            <RefreshCcw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button>
                <PlusCircle className="mr-2 h-4 w-4" />
                Add Supplier
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Add New Supplier</DialogTitle>
                <DialogDescription>Enter supplier details.</DialogDescription>
              </DialogHeader>
              <div className="grid gap-4 py-4">
                <div className="grid grid-cols-4 items-center gap-4">
                  <Label className="text-right">Name</Label>
                  <Input
                    className="col-span-3"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    placeholder="Supplier name"
                  />
                </div>
                <div className="grid grid-cols-4 items-center gap-4">
                  <Label className="text-right">Email</Label>
                  <Input
                    type="email"
                    className="col-span-3"
                    value={formData.contact_email}
                    onChange={(e) => setFormData({ ...formData, contact_email: e.target.value })}
                  />
                </div>
                <div className="grid grid-cols-4 items-center gap-4">
                  <Label className="text-right">Phone</Label>
                  <Input
                    className="col-span-3"
                    value={formData.phone}
                    onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                  />
                </div>
                <div className="grid grid-cols-4 items-center gap-4">
                  <Label className="text-right">Address</Label>
                  <Input
                    className="col-span-3"
                    value={formData.address}
                    onChange={(e) => setFormData({ ...formData, address: e.target.value })}
                  />
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
            <p className="text-center text-muted-foreground py-8">No suppliers registered yet.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Phone</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {suppliers.map((s, i) => (
                  <TableRow key={s.id || i}>
                    <TableCell className="font-medium">{s.name}</TableCell>
                    <TableCell>{s.contact_email || "-"}</TableCell>
                    <TableCell>{s.phone || "-"}</TableCell>
                    <TableCell>
                      <Badge variant={s.status === "active" ? "default" : "secondary"}>
                        {s.status || "active"}
                      </Badge>
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
