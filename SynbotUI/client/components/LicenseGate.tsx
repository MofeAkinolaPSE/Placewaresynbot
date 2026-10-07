import { ReactNode, useEffect, useSyncExternalStore } from "react";
import { Lock, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getLicenseStatus, refreshLicense, subscribeLicense, watchFetchForLicenseLock } from "@/lib/license";

const fmt = (d: string | null) =>
  d ? new Date(`${d}T00:00:00`).toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" }) : "-";

const TITLES: Record<string, string> = {
  expired: "Subscription expired",
  missing: "No licence installed",
  invalid: "Licence could not be verified",
  clock_rollback: "Server clock problem",
};

export default function LicenseGate({ children }: { children: ReactNode }) {
  const status = useSyncExternalStore(subscribeLicense, getLicenseStatus);

  useEffect(() => {
    watchFetchForLicenseLock();
    void refreshLicense();
    const t = window.setInterval(() => void refreshLicense(), 5 * 60_000);
    return () => window.clearInterval(t);
  }, []);

  if (status?.locked && status.lock_mode === "full") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background px-4">
        <div className="w-full max-w-md rounded-xl border bg-card p-8 text-center shadow-sm">
          <Lock className="mx-auto mb-4 h-10 w-10 text-destructive" />
          <h1 className="text-xl font-semibold text-foreground">{TITLES[status.state] ?? "System locked"}</h1>
          <p className="mt-2 text-sm text-muted-foreground">{status.message}</p>
          {status.licensee && (
            <p className="mt-4 text-sm text-foreground">
              {status.licensee} - expired {fmt(status.expires_on)}
            </p>
          )}
          <p className="mt-4 text-sm text-muted-foreground">
            Your data is safe and unchanged. Contact <span className="font-medium text-foreground">{status.support_contact}</span> to
            restore access.
          </p>
          <Button className="mt-6" variant="outline" onClick={() => void refreshLicense()}>
            Check again
          </Button>
        </div>
      </div>
    );
  }

  const banner =
    status?.locked && status.lock_mode === "read_only"
      ? `${status.message} The system is read-only - contact ${status.support_contact}.`
      : status?.state === "grace"
        ? `${status.message} Contact ${status.support_contact}.`
        : null;

  return (
    <>
      {banner && (
        <div className="sticky top-0 z-[100] flex items-center justify-center gap-2 bg-amber-500 px-4 py-2 text-sm font-medium text-black">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>{banner}</span>
        </div>
      )}
      {children}
    </>
  );
}
