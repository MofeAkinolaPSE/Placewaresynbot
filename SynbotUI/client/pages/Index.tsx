import { DemoResponse } from "@shared/api";
import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle } from "lucide-react";

export default function Index() {
  const [exampleFromServer, setExampleFromServer] = useState("");
  const [fetchError, setFetchError] = useState<string | null>(null);
  // Fetch users on component mount
  useEffect(() => {
    fetchDemo();
  }, []);

  // Example of how to fetch data from the server (if needed)
  const fetchDemo = async () => {
    try {
      const response = await fetch("/api/demo");
      if (!response.ok) {
        throw new Error(`Backend responded with ${response.status}`);
      }
      const data = (await response.json()) as DemoResponse;
      if (!data || typeof data.message !== "string" || !data.message.trim()) {
        throw new Error("Invalid demo payload received");
      }
      setExampleFromServer(data.message.trim());
      setFetchError(null);
    } catch (error) {
      setFetchError(error instanceof Error ? error.message : "Failed to fetch backend status");
      console.error("Error fetching hello:", error);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-100 to-slate-200">
      <div className="text-center">
        <h1 className="text-2xl font-semibold text-slate-800">
          Placeware Frontend Runtime Status
        </h1>
        {fetchError ? (
          <div className="mt-4 mx-auto max-w-md rounded-lg border border-red-200 bg-red-50 p-4 text-left">
            <p className="font-medium text-red-700 flex items-center gap-2">
              <AlertCircle className="h-4 w-4" />
              Backend status check failed
            </p>
            <p className="mt-1 text-sm text-red-700">{fetchError}</p>
          </div>
        ) : exampleFromServer ? (
          <div className="mt-4 mx-auto max-w-md rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-left">
            <p className="font-medium text-emerald-700 flex items-center gap-2">
              <CheckCircle className="h-4 w-4" />
              Backend status reachable
            </p>
            <p className="mt-1 text-sm text-emerald-700">{exampleFromServer}</p>
          </div>
        ) : (
          <p className="mt-4 text-slate-600 max-w-md">
            Checking backend runtime status...
          </p>
        )}
      </div>
    </div>
  );
}
