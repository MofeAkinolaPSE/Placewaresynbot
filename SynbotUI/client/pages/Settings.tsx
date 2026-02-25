import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { CheckCircle, AlertCircle, Copy } from "lucide-react";
import { toast } from "sonner";
import { getSynbotConfig } from "@/lib/wp-config";
import { authClient } from "@/lib/auth-client";

type SettingsPayload = {
  apiUrl: string;
  features: {
    forecasting: boolean;
    workflow: boolean;
    riskScoring: boolean;
  };
};

const STORAGE_KEY = "placeware_ui_settings";

function loadStoredSettings(): Partial<SettingsPayload> {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Partial<SettingsPayload>;
    return typeof parsed === "object" && parsed ? parsed : {};
  } catch {
    return {};
  }
}

const Settings = () => {
  const config = getSynbotConfig();
  const stored = loadStoredSettings();
  const token = authClient.getAccessToken();

  const [apiUrl, setApiUrl] = useState(
    (typeof stored.apiUrl === "string" && stored.apiUrl) || config.apiBaseUrl || ""
  );
  const [showJwt, setShowJwt] = useState(false);
  const [saveStatus, setSaveStatus] = useState<
    "idle" | "saving" | "success" | "error"
  >("idle");

  const [features, setFeatures] = useState({
    forecasting: stored.features?.forecasting ?? false,
    workflow: stored.features?.workflow ?? false,
    riskScoring: stored.features?.riskScoring ?? false,
  });

  const hasConfigApi = Boolean(config.apiBaseUrl && config.apiBaseUrl.trim());
  const hasSessionToken = Boolean(token && token.trim());
  const isValidApiUrl = useMemo(() => {
    if (!apiUrl.trim()) return false;
    try {
      const parsed = new URL(apiUrl.trim());
      return parsed.protocol === "http:" || parsed.protocol === "https:";
    } catch {
      return false;
    }
  }, [apiUrl]);

  const handleSave = async () => {
    if (!isValidApiUrl) {
      setSaveStatus("error");
      toast.error("Enter a valid HTTP(S) API URL before saving");
      return;
    }

    setSaveStatus("saving");
    try {
      const payload: SettingsPayload = {
        apiUrl: apiUrl.trim(),
        features,
      };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
      setSaveStatus("success");
      toast.success("Local settings saved successfully");
      setTimeout(() => setSaveStatus("idle"), 3000);
    } catch {
      setSaveStatus("error");
      toast.error("Unable to save local settings");
    }
  };

  const toggleFeature = (
    feature: "forecasting" | "workflow" | "riskScoring"
  ) => {
    setFeatures((prev) => ({ ...prev, [feature]: !prev[feature] }));
  };

  const copyToClipboard = () => {
    if (!apiUrl.trim()) {
      toast.error("No API URL to copy");
      return;
    }
    navigator.clipboard.writeText(apiUrl);
    toast.success("API URL copied to clipboard");
  };

  const revealJwt = () => {
    if (!hasSessionToken) {
      toast.error("No active session token found");
      return;
    }
    setShowJwt(!showJwt);
  };

  return (
    <div className="p-8 space-y-8 max-w-4xl">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-foreground">Settings</h1>
        <p className="text-muted-foreground mt-2">
          Local UI preferences and runtime session/config visibility for Placeware
        </p>
      </div>

      {(!hasConfigApi || !hasSessionToken) && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 flex gap-3">
          <AlertCircle className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
          <div>
            <p className="font-medium text-amber-900">Runtime configuration warning</p>
            <p className="text-sm text-amber-700 mt-1">
              {!hasConfigApi && "API base URL is not provided by runtime config. "}
              {!hasSessionToken && "No active authenticated session token is available."}
            </p>
          </div>
        </div>
      )}

      {/* API Configuration */}
      <div className="bg-card border border-border rounded-lg p-6 space-y-6">
        <div>
          <h2 className="text-xl font-semibold text-foreground mb-6">
            API Configuration
          </h2>

          {/* API Base URL */}
          <div className="space-y-2 mb-6">
            <Label htmlFor="api-url" className="text-base font-medium">
              Backend API Base URL
            </Label>
            <div className="flex gap-2">
              <Input
                id="api-url"
                value={apiUrl}
                onChange={(e) => setApiUrl(e.target.value)}
                className="flex-1"
                placeholder="https://api.example.com"
              />
              <Button
                variant="outline"
                size="icon"
                onClick={copyToClipboard}
                title="Copy URL"
                disabled={!apiUrl.trim()}
              >
                <Copy className="w-4 h-4" />
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Persisted in browser storage only; backend config still controls actual server routing
            </p>
            {!isValidApiUrl && apiUrl.trim() && (
              <p className="text-xs text-destructive">Provide a valid HTTP(S) URL.</p>
            )}
          </div>

          {/* JWT Token */}
          <div className="space-y-2">
            <Label htmlFor="jwt-token" className="text-base font-medium">
              Admin JWT Token
            </Label>
            <div className="flex gap-2">
              <Input
                id="jwt-token"
                type={showJwt ? "text" : "password"}
                value={token ?? ""}
                readOnly
                className="flex-1 font-mono text-sm"
                placeholder="No active token"
              />
              <Button variant="outline" onClick={revealJwt} disabled={!hasSessionToken}>
                {showJwt ? "Hide" : "Show"}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Displayed from in-memory authenticated session only
            </p>
          </div>
        </div>
      </div>

      {/* Feature Toggles */}
      <div className="bg-card border border-border rounded-lg p-6 space-y-6">
        <div>
          <h2 className="text-xl font-semibold text-foreground mb-6">
            Feature Toggles
          </h2>

          <div className="space-y-4">
            {/* Enable Forecasting */}
            <div className="flex items-center justify-between p-4 rounded-lg bg-muted/30">
              <div>
                <p className="font-medium text-foreground">
                  Enable Forecasting
                </p>
                <p className="text-sm text-muted-foreground">
                  Enable AR/AP trend forecasting in Finance Analytics
                </p>
              </div>
              <Switch
                checked={features.forecasting}
                onCheckedChange={() => toggleFeature("forecasting")}
              />
            </div>

            {/* Enable Workflow Engine */}
            <div className="flex items-center justify-between p-4 rounded-lg bg-muted/30">
              <div>
                <p className="font-medium text-foreground">
                  Enable Workflow Engine
                </p>
                <p className="text-sm text-muted-foreground">
                  Enable approval workflows and pending intents
                </p>
              </div>
              <Switch
                checked={features.workflow}
                onCheckedChange={() => toggleFeature("workflow")}
              />
            </div>

            {/* Enable CRM Risk Scoring */}
            <div className="flex items-center justify-between p-4 rounded-lg bg-muted/30">
              <div>
                <p className="font-medium text-foreground">
                  Enable CRM Risk Scoring
                </p>
                <p className="text-sm text-muted-foreground">
                  Enable AI-powered risk scoring for opportunities
                </p>
              </div>
              <Switch
                checked={features.riskScoring}
                onCheckedChange={() => toggleFeature("riskScoring")}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Security Notice */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 flex gap-3">
        <AlertCircle className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
        <div>
          <p className="font-medium text-blue-900">Security Notice</p>
          <p className="text-sm text-blue-700 mt-1">
            This page stores only client-side preferences. Critical platform configuration,
            access controls, and auditable policy changes remain server-managed.
          </p>
        </div>
      </div>

      {/* Save Button */}
      <div className="flex gap-3 items-center">
        <Button
          onClick={handleSave}
          disabled={saveStatus === "saving" || !isValidApiUrl}
          size="lg"
          className="min-w-32"
        >
          {saveStatus === "saving" ? (
            <>
              <div className="animate-spin mr-2 h-4 w-4 border-2 border-current border-t-transparent rounded-full" />
              Saving...
            </>
          ) : saveStatus === "success" ? (
            <>
              <CheckCircle className="w-4 h-4 mr-2" />
              Saved
            </>
          ) : (
            "Save Settings"
          )}
        </Button>

        {saveStatus === "success" && (
          <div className="flex items-center gap-2 text-success">
            <CheckCircle className="w-5 h-5" />
            <span className="text-sm font-medium">All changes saved</span>
          </div>
        )}
      </div>
    </div>
  );
};

export default Settings;
