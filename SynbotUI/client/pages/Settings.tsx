import { useEffect, useMemo, useState } from "react";
import { useTheme } from "next-themes";
import ThemeToggle from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { CheckCircle, AlertCircle, Copy, Sun, Moon, Download, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api-client";
import { getSynbotConfig } from "@/lib/wp-config";
import { authClient } from "@/lib/auth-client";
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";

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
  const { theme, setTheme } = useTheme();
  const isDark = theme === "dark" || (theme === "system" && typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches);

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

  // Data backup — admin-only on the server; this just surfaces it.
  const [backupInfo, setBackupInfo] = useState<any>(null);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    let alive = true;
    api.adminBackup
      .info()
      .then((info) => alive && setBackupInfo(info))
      .catch(() => alive && setBackupInfo(null));
    return () => {
      alive = false;
    };
  }, []);

  const downloadBackup = async () => {
    setDownloading(true);
    try {
      const { url, filename } = await api.adminBackup.download();
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      // Give the browser a moment to start the save before revoking.
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
      toast.success("Backup downloaded", { description: filename });
    } catch (e: any) {
      toast.error("Backup failed", {
        description:
          e?.status === 403
            ? "Only administrators can download a backup."
            : e?.message ?? "Could not generate the backup.",
      });
    } finally {
      setDownloading(false);
    }
  };

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
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionTransitions.standard}
      className="pw-page-surface max-w-4xl space-y-8 p-8"
    >
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-foreground">Settings</h1>
        <p className="text-muted-foreground mt-2">
          Local UI preferences and runtime session/config visibility for Placeware
        </p>
      </div>

      {(!hasConfigApi || !hasSessionToken) && (
        <div className="flex gap-3 rounded-xl border border-warning/30 bg-warning/15 p-4">
          <AlertCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-warning" />
          <div>
            <p className="font-medium text-warning">Runtime configuration warning</p>
            <p className="mt-1 text-sm text-warning">
              {!hasConfigApi && "API base URL is not provided by runtime config. "}
              {!hasSessionToken && "No active authenticated session token is available."}
            </p>
          </div>
        </div>
      )}

      {/* API Configuration */}
      <div className="pw-surface-interactive space-y-6 rounded-xl p-6">
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

      {/* Appearance */}
      <div className="pw-surface-interactive space-y-4 rounded-xl p-6">
        <div>
          <h2 className="text-xl font-semibold text-foreground mb-1">Appearance</h2>
          <p className="text-sm text-muted-foreground mb-5">Choose your preferred colour scheme. Takes effect immediately.</p>
          <div className="pw-surface-base flex flex-wrap items-center justify-between gap-4 rounded-xl p-4">
            <div className="flex items-center gap-3">
              {isDark ? <Moon className="h-5 w-5 text-primary" /> : <Sun className="h-5 w-5 text-warning" />}
              <div>
                <p className="font-medium text-foreground">Theme</p>
                <p className="text-sm text-muted-foreground">
                  {theme === "system"
                    ? `Following your device (currently ${isDark ? "dark" : "light"})`
                    : isDark
                      ? "Currently using dark theme"
                      : "Currently using light theme"}
                </p>
              </div>
            </div>
            {/* Three-way control here (not the header's two-way flip) so
                "follow my device" is reachable from Settings. */}
            <ThemeToggle variant="segmented" />
          </div>
        </div>
      </div>

      {/* Feature Toggles */}
      <div className="pw-surface-interactive space-y-6 rounded-xl p-6">
        <div>
          <h2 className="text-xl font-semibold text-foreground mb-2">
            Data Backup
          </h2>
          <p className="text-sm text-muted-foreground mb-4">
            Download a complete copy of this deployment's data. Keep the file
            somewhere secure — it contains client and commercial records.
          </p>

          <div className="pw-surface-base flex flex-wrap items-center justify-between gap-3 rounded-xl p-4">
            <div className="min-w-0">
              <p className="font-medium text-foreground">Full data export</p>
              <p className="text-sm text-muted-foreground">
                {backupInfo
                  ? `${backupInfo.table_count} tables · ${backupInfo.database_size}` +
                    (backupInfo.restorable
                      ? " · restorable SQL dump"
                      : " · CSV bundle (data only, no schema)")
                  : "Checking…"}
              </p>
            </div>
            <Button onClick={downloadBackup} disabled={downloading} className="gap-2">
              {downloading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> Preparing…
                </>
              ) : (
                <>
                  <Download className="h-4 w-4" /> Download backup
                </>
              )}
            </Button>
          </div>

          {backupInfo && !backupInfo.restorable && (
            <p className="text-xs text-muted-foreground mt-2">
              This export carries data only — no schema, indexes or constraints —
              so it is not a one-click restore. For a directly restorable dump,
              use the scheduled server-side backup (deploy/backup.sh).
            </p>
          )}
        </div>

        <div>
          <h2 className="text-xl font-semibold text-foreground mb-6">
            Feature Toggles
          </h2>

          <div className="space-y-4">
            {/* Enable Forecasting */}
            <div className="pw-surface-base flex items-center justify-between rounded-xl p-4">
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
            <div className="pw-surface-base flex items-center justify-between rounded-xl p-4">
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
            <div className="pw-surface-base flex items-center justify-between rounded-xl p-4">
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
      <div className="flex gap-3 rounded-xl border border-info/30 bg-info/15 p-4">
        <AlertCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-info" />
        <div>
          <p className="font-medium text-info">Security Notice</p>
          <p className="mt-1 text-sm text-info">
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
    </motion.div>
  );
};

export default Settings;
