import { useState, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Upload, File, CheckCircle, AlertCircle, Clock, Users } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toast } from "sonner";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { authClient } from "@/lib/auth-client";
import { format } from "date-fns";

const SageImport = () => {
  const [uploadedFiles, setUploadedFiles] = useState<
    {
      name: string;
      status: "pending" | "uploaded";
      rows: number;
    }[]
  >([]);
  const [fileMap, setFileMap] = useState<Record<string, File>>({});
  const [importInProgress, setImportInProgress] = useState(false);
  const [importResult, setImportResult] = useState<{
    batchId: string;
    timestamp: string;
    files: { name: string; rows: number }[];
  } | null>(null);

  const { data: historyData, refetch: refetchHistory } = useQuery({
    queryKey: ["sage-history"],
    queryFn: () => api.sage.history(),
  });
  
  const auditLogs = historyData || [];

  const datasets = [
    { id: "customers", label: "Customers", icon: File },
    { id: "ar", label: "Accounts Receivable (AR)", icon: File },
    { id: "ap", label: "Accounts Payable (AP)", icon: File },
    { id: "gl", label: "General Ledger (GL)", icon: File },
    { id: "inventory", label: "Inventory", icon: File },
    { id: "staff", label: "Staff Registry", icon: Users },
  ];

  const handleFileChange = (datasetId: string, e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const f = e.target.files[0];
      setFileMap((prev) => ({ ...prev, [datasetId]: f }));
      
      // Update UI state
      setUploadedFiles((prev) => {
        const filtered = prev.filter((p) => !p.name.startsWith(datasetId));
        return [
          ...filtered,
          {
            name: `${datasetId}_${f.name}`,
            status: "uploaded",
            rows: 0, // Will be updated after import
          },
        ];
      });
      toast.success(`${datasetId.toUpperCase()} file selected`);
    }
  };

  const handleImport = async () => {
    if (Object.keys(fileMap).length === 0) {
      toast.error("Please upload at least one file");
      return;
    }

    setImportInProgress(true);

    try {
      const formData = new FormData();
      Object.entries(fileMap).forEach(([key, file]) => {
         formData.append(key, file);
      });

      const refreshed = await authClient.refresh();
      if (!refreshed && !authClient.getAccessToken()) {
        throw new Error("Session expired. Please sign in again.");
      }

      const data = await api.imports.sage(formData, false);

      const responseBatchId =
        (typeof data?.batch_id === "string" && data.batch_id) ||
        (typeof data?.batchId === "string" && data.batchId) ||
        "";
      const responseImportedAt =
        (typeof data?.imported_at === "string" && data.imported_at) ||
        (typeof data?.timestamp === "string" && data.timestamp) ||
        "";
      const responseCounts = typeof data?.counts === "object" && data?.counts ? data.counts : {};

      if (!responseBatchId || !responseImportedAt) {
        throw new Error("Import response is missing required fields (batch_id/imported_at)");
      }

      setImportResult({
        batchId: responseBatchId,
        timestamp: responseImportedAt,
        files: Object.entries(responseCounts).map(([k, v]) => ({
            name: k.toUpperCase(),
            rows: v as number
        })),
      });
      
      toast.success("Import completed successfully");
      setFileMap({});
      setUploadedFiles([]);
      refetchHistory();

    } catch (e: any) {
        const message =
          typeof e?.message === "string" && e.message.trim()
            ? e.message
            : "Unknown import error";
        console.error("Sage import failed", {
          message,
          error: e,
        });
        toast.error(`Import failed: ${message}`);
    } finally {
        setImportInProgress(false);
    }
  };

  const getStatusIcon = (status: string) => {
    if (status === "success") {
      return <CheckCircle className="w-4 h-4 text-success" />;
    } else if (status === "error") {
      return <AlertCircle className="w-4 h-4 text-destructive" />;
    }
    return <Clock className="w-4 h-4 text-muted-foreground" />;
  };

  return (
    <div className="p-8 space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-foreground">Sage Import</h1>
        <p className="text-muted-foreground mt-2">
          Import ERP data from Sage into Synbot-BVE
        </p>
      </div>

      {/* Upload Cards */}
      <div className="space-y-4">
        <h2 className="text-lg font-semibold text-foreground">Step 1: Select Files to Import</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {datasets.map((dataset) => {
            const isUploaded = uploadedFiles.some((f) =>
              f.name.includes(dataset.id)
            );
            const Icon = dataset.icon;
            return (
              <div
                key={dataset.id}
                className="bg-card border border-border rounded-lg p-6 hover:shadow-lg transition-shadow"
              >
                <input
                    type="file"
                    id={`file-${dataset.id}`}
                    className="hidden"
                  accept=".csv,.json,.xlsx"
                    onChange={(e) => handleFileChange(dataset.id, e)}
                />
                <Icon className="w-8 h-8 text-muted-foreground mb-3" />
                <h3 className="font-semibold text-foreground mb-2">
                  {dataset.label}
                </h3>
                <p className="text-sm text-muted-foreground mb-4">
                  {isUploaded ? "File ready for import" : "Click to select file"}
                </p>
                <Button
                  onClick={() => document.getElementById(`file-${dataset.id}`)?.click()}
                  variant={isUploaded ? "secondary" : "default"}
                  className="w-full"
                >
                  {isUploaded ? (
                    <>
                      <CheckCircle className="w-4 h-4 mr-2" />
                      Ready
                    </>
                  ) : (
                    <>
                      <Upload className="w-4 h-4 mr-2" />
                      Select
                    </>
                  )}
                </Button>
              </div>
            );
          })}
        </div>
      </div>

      {/* Uploaded Files Summary */}
      {uploadedFiles.length > 0 && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
          <div className="flex items-start gap-3">
            <CheckCircle className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-medium text-blue-900">
                {uploadedFiles.length} file(s) ready for import
              </p>
              <div className="mt-2 space-y-1">
                {uploadedFiles.map((file, idx) => (
                  <p key={idx} className="text-sm text-blue-700">
                    • {file.name.split("_")[0].toUpperCase()} -{" "}
                    {file.rows.toLocaleString()} rows
                  </p>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Import Button */}
      <div className="flex gap-3">
        <Button
          onClick={handleImport}
          disabled={importInProgress || uploadedFiles.length === 0}
          size="lg"
          className="min-w-48"
        >
          {importInProgress ? (
            <>
              <div className="animate-spin mr-2 h-4 w-4 border-2 border-current border-t-transparent rounded-full" />
              Importing...
            </>
          ) : (
            <>
              <Upload className="w-4 h-4 mr-2" />
              Start Import
            </>
          )}
        </Button>
      </div>

      {/* Import Result */}
      {importResult && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-6">
          <div className="flex gap-4">
            <CheckCircle className="w-6 h-6 text-success flex-shrink-0" />
            <div>
              <h3 className="font-semibold text-green-900 mb-3">
                Import Completed Successfully
              </h3>
              <div className="space-y-2 text-sm text-green-800">
                <p>
                  <span className="font-medium">Batch ID:</span>{" "}
                  <code className="bg-white px-2 py-1 rounded font-mono">
                    {importResult.batchId}
                  </code>
                </p>
                <p>
                  <span className="font-medium">Timestamp:</span>{" "}
                  {importResult.timestamp}
                </p>
                <div className="mt-3 pt-3 border-t border-green-200">
                  <p className="font-medium mb-2">Imported Datasets:</p>
                  <ul className="space-y-1">
                    {importResult.files.map((file, idx) => (
                      <li key={idx}>
                        • {file.name}: {file.rows.toLocaleString()} rows
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Audit Log */}
      <div className="bg-card border border-border rounded-lg p-6">
        <h2 className="text-lg font-semibold text-foreground mb-4">
          Import History
        </h2>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Date & Time</TableHead>
                <TableHead>User</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Details</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {auditLogs.length === 0 && (
                <TableRow>
                   <TableCell colSpan={5} className="text-center text-muted-foreground h-24">
                     No import history found.
                   </TableCell>
                </TableRow>
              )}
              {auditLogs.map((log: any) => (
                <TableRow key={log.id}>
                  <TableCell className="font-mono text-sm">
                    {log.date ? format(new Date(log.date), "yyyy-MM-dd HH:mm") : "-"}
                  </TableCell>
                  <TableCell className="text-sm">{log.user}</TableCell>
                  <TableCell className="text-sm font-medium">
                    {log.action}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      {getStatusIcon(log.status)}
                      <span
                        className={`text-sm font-medium ${
                          log.status === "success"
                            ? "text-success"
                            : "text-destructive"
                        }`}
                      >
                        {log.status.charAt(0).toUpperCase() + log.status.slice(1)}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {log.details}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  );
};

export default SageImport;
