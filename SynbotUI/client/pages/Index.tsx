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
    <div className="pw-page-surface min-h-screen flex items-center justify-center">
      <div className="text-center">
        <h1 className="text-2xl font-semibold text-foreground">
          Placeware Frontend Runtime Status
        </h1>
        {fetchError ? (
          <div className="mt-4 mx-auto max-w-md rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-left">
            <p className="flex items-center gap-2 font-medium text-destructive">
              <AlertCircle className="h-4 w-4" />
              Backend status check failed
            </p>
            <p className="mt-1 text-sm text-destructive">{fetchError}</p>
          </div>
        ) : exampleFromServer ? (
          <div className="mt-4 mx-auto max-w-md rounded-xl border border-success/30 bg-success/10 p-4 text-left">
            <p className="flex items-center gap-2 font-medium text-success">
              <CheckCircle className="h-4 w-4" />
              Backend status reachable
            </p>
            <p className="mt-1 text-sm text-success">{exampleFromServer}</p>
          </div>
        ) : (
          <p className="mt-4 max-w-md text-muted-foreground">
            Checking backend runtime status...
          </p>
        )}
      </div>
    </div>
  );
}
