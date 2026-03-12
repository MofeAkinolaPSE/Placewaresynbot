import { useMemo, useState } from "react";
import { Search, Download, Filter } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";

const FinanceReports = () => {
  const navigate = useNavigate();
  const [searchAR, setSearchAR] = useState("");
  const [searchInventory, setSearchInventory] = useState("");
  const { data: arAgingRaw, isLoading: arLoading, error: arError } = useQuery({
    queryKey: ["reports-ar-aging"],
    queryFn: () => api.finance.arAging(),
    refetchInterval: 60000,
  });

  const { data: stockRows, isLoading: invLoading, error: invError } = useQuery({
    queryKey: ["reports-inventory"],
    queryFn: () => api.inventory.stock(),
    refetchInterval: 60000,
  });

  // Normalize AR aging buckets into table-friendly rows (no per-customer granularity available yet)
  const arAgingData = useMemo(
    () => {
      const source = (arAgingRaw as any)?.aging ?? arAgingRaw;
      if (
        !source ||
        typeof source !== "object" ||
        typeof (source as any)["0_30"] !== "number" ||
        typeof (source as any)["31_60"] !== "number" ||
        typeof (source as any)["61_90"] !== "number" ||
        typeof (source as any)["91_plus"] !== "number"
      ) {
        return [];
      }
      const buckets = source as Record<string, number>;
      return [
        { id: 1, customer: "All Customers", amount: buckets["0_30"], bucket: "0-30 days", days: "0-30", dueDate: "-" },
        { id: 2, customer: "All Customers", amount: buckets["31_60"], bucket: "31-60 days", days: "31-60", dueDate: "-" },
        { id: 3, customer: "All Customers", amount: buckets["61_90"], bucket: "61-90 days", days: "61-90", dueDate: "-" },
        { id: 4, customer: "All Customers", amount: buckets["91_plus"], bucket: "90+ days", days: "90+", dueDate: "-" },
      ];
    },
    [arAgingRaw]
  );

  const inventoryData = useMemo(
    () => {
      if (!Array.isArray(stockRows)) return [];
      const rows = stockRows;
      return rows.map((r: any) => ({
        sku: r.sku,
        name: r.name,
        quantity: Number(r.current_stock ?? r.quantity),
        unitCost: Number(r.unit_cost),
        valuation: r.valuation != null
          ? Number(r.valuation)
          : Number(r.unit_cost) * Number(r.current_stock ?? r.quantity),
        status: ((): "optimal" | "low" | "out" => {
          const qty = Number(r.current_stock ?? r.quantity);
          if (r.status === "optimal" || r.status === "low" || r.status === "out") {
            return r.status;
          }
          if (qty <= 0) return "out";
          if (qty < 10) return "low";
          return "optimal";
        })(),
      })).filter((r: any) =>
        typeof r.sku === "string" &&
        typeof r.name === "string" &&
        Number.isFinite(r.quantity) &&
        Number.isFinite(r.unitCost) &&
        Number.isFinite(r.valuation)
      );
    },
    [stockRows]
  );

  const arPayloadInvalid = !arLoading && !arError && arAgingData.length === 0;
  const inventoryPayloadInvalid = !invLoading && !invError && !Array.isArray(stockRows);

  const filteredAR = arAgingData.filter(
    (item) =>
      item.customer.toLowerCase().includes(searchAR.toLowerCase()) ||
      item.bucket.toLowerCase().includes(searchAR.toLowerCase())
  );

  const filteredInventory = inventoryData.filter(
    (item) =>
      item.name.toLowerCase().includes(searchInventory.toLowerCase()) ||
      item.sku.toLowerCase().includes(searchInventory.toLowerCase())
  );

  const handleExportCSV = (dataType: "ar" | "inventory") => {
    const data = dataType === "ar" ? filteredAR : filteredInventory;
    const headers =
      dataType === "ar"
        ? ["Customer", "Amount (₦)", "Bucket", "Days Overdue", "Due Date"]
        : ["SKU", "Name", "Quantity", "Unit Cost (₦)", "Valuation (₦)"];

    let csv = headers.join(",") + "\n";
    data.forEach((item) => {
      if (dataType === "ar") {
        const row = [
          item.customer,
          item.amount,
          item.bucket,
          item.days,
          item.dueDate,
        ];
        csv += row.join(",") + "\n";
      } else {
        const row = [
          item.sku,
          item.name,
          item.quantity,
          item.unitCost,
          item.valuation,
        ];
        csv += row.join(",") + "\n";
      }
    });

    const element = document.createElement("a");
    element.setAttribute("href", "data:text/csv;charset=utf-8," + encodeURI(csv));
    element.setAttribute("download", `${dataType}-report-${Date.now()}.csv`);
    element.click();
  };

  const arBuckets = {
    "0-30 days": arAgingData.find((a) => a.bucket === "0-30 days")?.amount,
    "31-60 days": arAgingData.find((a) => a.bucket === "31-60 days")?.amount,
    "61-90 days": arAgingData.find((a) => a.bucket === "61-90 days")?.amount,
    "90+ days": arAgingData.find((a) => a.bucket === "90+ days")?.amount,
  };

  const getArBucketClass = (bucket: string) => {
    if (bucket === "0-30 days") return "bg-success/15 text-success";
    if (bucket === "90+ days") return "bg-destructive/10 text-destructive";
    return "bg-warning/15 text-warning";
  };

  const getInventoryStatusClass = (status: string) => {
    if (status === "optimal") return "bg-success/15 text-success";
    if (status === "low") return "bg-warning/15 text-warning";
    return "bg-destructive/10 text-destructive";
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
        <h1 className="text-3xl font-bold text-foreground">Finance Reports</h1>
        <p className="text-muted-foreground mt-2">
          Detailed financial tables with search, filters, and export capabilities
        </p>
      </div>

      <Tabs defaultValue="ar" className="w-full">
        <TabsList className="grid w-full max-w-md grid-cols-2">
          <TabsTrigger value="ar">AR Aging</TabsTrigger>
          <TabsTrigger value="inventory">Inventory</TabsTrigger>
        </TabsList>

        {/* AR Aging Tab */}
        <TabsContent value="ar" className="space-y-4">
          <div className="pw-surface-interactive p-6 space-y-4">
            {arError && <p className="text-sm text-destructive">Data error: {(arError as Error).message || "Failed to load AR aging."}</p>}
            {arPayloadInvalid && <p className="text-sm text-destructive">Data error: malformed AR aging payload.</p>}
            {/* Summary Buckets */}
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
              {Object.entries(arBuckets).map(([bucket, amount]) => (
                <div
                  key={bucket}
                  className="rounded-xl border border-border/50 bg-muted/30 p-3 text-center"
                >
                  <p className="text-xs font-semibold text-muted-foreground uppercase">
                    {bucket}
                  </p>
                  <p className="text-lg font-bold text-foreground mt-1">
                    {typeof amount === "number" ? `₦${Number(amount).toLocaleString()}` : "Data error"}
                  </p>
                </div>
              ))}
            </div>

            {/* Search and Export */}
            <div className="flex gap-2 flex-col sm:flex-row sm:items-center">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  placeholder="Search by customer or bucket..."
                  value={searchAR}
                  onChange={(e) => setSearchAR(e.target.value)}
                  className="pl-10"
                />
              </div>
              <Button
                variant="outline"
                onClick={() => handleExportCSV("ar")}
              >
                <Download className="w-4 h-4 mr-2" />
                Export CSV
              </Button>
            </div>

            {/* Table */}
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Customer</TableHead>
                    <TableHead className="text-right">Amount (₦)</TableHead>
                        <TableHead>Bucket</TableHead>
                        <TableHead className="text-center">Days Range</TableHead>
                        <TableHead>Due Date</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredAR.length > 0 ? (
                    filteredAR.map((item) => (
                      <TableRow
                        key={item.id}
                        className="cursor-pointer hover:bg-muted/40"
                        onClick={() => {
                          const bucketParam = encodeURIComponent(item.bucket);
                          navigate(`/finance/reports/ar/${bucketParam}`);
                        }}
                      >
                        <TableCell className="font-medium">
                          {item.customer}
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          {item.amount.toLocaleString()}
                        </TableCell>
                        <TableCell>
                          <span
                            className={`rounded px-2 py-1 text-xs font-medium ${getArBucketClass(item.bucket)}`}
                          >
                            {item.bucket}
                          </span>
                        </TableCell>
                        <TableCell className="text-center">{item.days}</TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {item.dueDate}
                        </TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell colSpan={5} className="text-center py-8">
                        <p className="text-muted-foreground">
                          No results found
                        </p>
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>

            <p className="text-xs text-muted-foreground">
              Showing {filteredAR.length} of {arAgingData.length} records
            </p>
          </div>
        </TabsContent>

        {/* Inventory Tab */}
        <TabsContent value="inventory" className="space-y-4">
          <div className="pw-surface-interactive p-6 space-y-4">
            {invError && <p className="text-sm text-destructive">Data error: {(invError as Error).message || "Failed to load inventory."}</p>}
            {inventoryPayloadInvalid && <p className="text-sm text-destructive">Data error: malformed inventory payload.</p>}
            {/* Status Summary */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
              <div className="rounded-xl border border-success/30 bg-success/15 p-3">
                <p className="text-xs font-semibold text-success uppercase">
                  Optimal Stock
                </p>
                <p className="text-lg font-bold text-success mt-1">
                  {inventoryData.filter((i) => i.status === "optimal").length}
                </p>
              </div>
              <div className="rounded-xl border border-warning/30 bg-warning/15 p-3">
                <p className="text-xs font-semibold text-warning uppercase">
                  Low Stock
                </p>
                <p className="text-lg font-bold text-warning mt-1">
                  {inventoryData.filter((i) => i.status === "low").length}
                </p>
              </div>
              <div className="rounded-xl border border-info/30 bg-info/15 p-3">
                <p className="text-xs font-semibold text-info uppercase">
                  Total SKUs
                </p>
                <p className="text-lg font-bold text-info mt-1">
                  {inventoryData.length}
                </p>
              </div>
              <div className="rounded-xl border border-secondary/30 bg-secondary/15 p-3">
                <p className="text-xs font-semibold text-secondary uppercase">
                  Total Value
                </p>
                <p className="text-lg font-bold text-secondary mt-1">
                  ₦
                  {(
                    inventoryData.reduce((sum, i) => sum + i.valuation, 0) /
                    1000000
                  ).toFixed(1)}
                  M
                </p>
              </div>
            </div>

            {/* Search and Export */}
            <div className="flex gap-2 flex-col sm:flex-row sm:items-center">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  placeholder="Search by SKU or product name..."
                  value={searchInventory}
                  onChange={(e) => setSearchInventory(e.target.value)}
                  className="pl-10"
                />
              </div>
              <Button
                variant="outline"
                onClick={() => handleExportCSV("inventory")}
              >
                <Download className="w-4 h-4 mr-2" />
                Export CSV
              </Button>
            </div>

            {/* Table */}
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>SKU</TableHead>
                    <TableHead>Product Name</TableHead>
                    <TableHead className="text-right">Quantity</TableHead>
                    <TableHead className="text-right">Unit Cost (₦)</TableHead>
                    <TableHead className="text-right">Valuation (₦)</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredInventory.length > 0 ? (
                    filteredInventory.map((item) => (
                      <TableRow key={item.sku}>
                        <TableCell className="font-mono text-sm">
                          {item.sku}
                        </TableCell>
                        <TableCell className="font-medium">{item.name}</TableCell>
                        <TableCell className="text-right">
                          {item.quantity.toLocaleString()}
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          {item.unitCost.toLocaleString()}
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          {item.valuation.toLocaleString()}
                        </TableCell>
                        <TableCell>
                          <span
                            className={`rounded px-2 py-1 text-xs font-medium ${getInventoryStatusClass(item.status)}`}
                          >
                            {item.status === "optimal"
                              ? "Optimal"
                              : item.status === "low"
                                ? "Low Stock"
                                : "Out of Stock"}
                          </span>
                        </TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell colSpan={6} className="text-center py-8">
                        <p className="text-muted-foreground">
                          No results found
                        </p>
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>

            <p className="text-xs text-muted-foreground">
              Showing {filteredInventory.length} of {inventoryData.length}{" "}
              products
            </p>
          </div>
        </TabsContent>
      </Tabs>
    </motion.div>
  );
};

export default FinanceReports;
