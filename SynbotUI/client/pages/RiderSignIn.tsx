import { useState, FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { apiUrl } from "@/lib/api-base";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Loader2 } from "lucide-react";

/**
 * ACE Riders sign-in — public, code-authenticated entry point.
 *
 * A rider's access_code is persistent (issued once when staff register
 * them), unlike the old flow where staff had to hand out a fresh tracking
 * link for every single delivery. Resolving the code just finds whichever
 * delivery is currently assigned and hands off to the existing, already-
 * working /rider-track/:token page for the actual GPS tracking UI — no
 * duplication of that page's ping/geofence/offline-queue logic.
 */
export default function RiderSignIn() {
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [waitingMessage, setWaitingMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = code.trim().toUpperCase();
    if (!trimmed || loading) return;
    setLoading(true);
    setError("");
    setWaitingMessage(null);
    try {
      const res = await fetch(apiUrl(`/logistics/riders/by-code/${encodeURIComponent(trimmed)}`));
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data?.detail || "Invalid code. Check with dispatch and try again.");
      }
      if (!data.delivery) {
        setWaitingMessage(
          `Hi ${data.rider?.name || "there"} — no delivery assigned to you right now. Check back once dispatch assigns one.`,
        );
        return;
      }
      const token = data.delivery.tracking_token;
      if (!token) {
        setError("Delivery found but tracking couldn't start. Contact dispatch.");
        return;
      }
      navigate(`/rider-track/${token}`, { replace: true });
    } catch (err: any) {
      setError(err?.message || "Sign-in failed. Check your code and try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#06101e] p-6">
      <div
        className="w-full max-w-sm rounded-2xl border border-white/10 p-8 shadow-2xl"
        style={{ background: "rgba(255,255,255,0.05)", backdropFilter: "blur(24px)" }}
      >
        <div className="mb-7 text-center">
          <div
            className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl"
            style={{ background: "linear-gradient(135deg, rgba(21,104,196,0.25) 0%, rgba(47,162,74,0.20) 100%)" }}
          >
            <span className="text-lg font-extrabold text-white">A</span>
          </div>
          <h1 className="text-2xl font-bold text-white">ACE Riders</h1>
          <p className="mt-1 text-sm text-white/50">Enter your rider code to start tracking</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <Input
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            placeholder="e.g. 7K2QXP"
            maxLength={6}
            autoComplete="off"
            autoCapitalize="characters"
            className="h-14 border-white/10 bg-white/5 text-center text-xl font-bold tracking-[0.3em] text-white placeholder:text-white/20 placeholder:tracking-normal"
          />
          {error && <p className="text-sm text-red-400">{error}</p>}
          {waitingMessage && <p className="text-sm text-amber-300">{waitingMessage}</p>}
          <Button
            type="submit"
            disabled={loading || !code.trim()}
            className="h-12 w-full border-0 text-base font-semibold text-white"
            style={{ background: "linear-gradient(90deg, #1568C4 0%, #2FA24A 100%)" }}
          >
            {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : "Sign In"}
          </Button>
        </form>

        <p className="mt-6 text-center text-[11px] text-white/25">
          Don't have a code? Ask your dispatcher.
        </p>
      </div>
    </div>
  );
}
