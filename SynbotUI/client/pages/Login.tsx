import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/components/AuthProvider";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { motion } from "framer-motion";
import { FlaskConical, ShieldCheck, BarChart3, Loader2, Eye, EyeOff } from "lucide-react";

// ── Feature highlight panels (mirror the 3-image strip in the template) ──────
const FEATURES = [
  {
    icon: BarChart3,
    title: "Real-Time Business Intelligence",
    desc: "Live dashboards for inventory, finance, HR and sales — unified in one secure platform.",
    gradient: "from-cyan-500/20 to-blue-600/10",
    border: "border-cyan-500/25",
    iconColor: "text-cyan-300",
  },
  {
    icon: FlaskConical,
    title: "NAFDAC & Quality Control",
    desc: "Cold-chain monitoring, CAPA, expiry alerts and batch registry built for pharma compliance.",
    gradient: "from-teal-500/20 to-cyan-600/10",
    border: "border-teal-400/25",
    iconColor: "text-teal-300",
  },
  {
    icon: ShieldCheck,
    title: "GMP Compliance & Audit-Ready",
    desc: "SOP tracking, deviation management and regulatory workflows for Nigerian pharma standards.",
    gradient: "from-blue-600/20 to-teal-500/10",
    border: "border-blue-400/25",
    iconColor: "text-blue-300",
  },
] as const;

const Login = () => {
  const { login, isLoading } = useAuth();
  const [email, setEmail]     = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw]   = useState(false);
  const [error, setError]     = useState("");
  const navigate = useNavigate();

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    try {
      await login(email, password);
      navigate("/", { replace: true });
    } catch {
      setError("Invalid email or password. Please try again.");
    }
  };

  return (
    <div
      className="relative flex min-h-screen overflow-hidden"
      style={{
        background: "#06101e",
        backgroundImage: [
          "radial-gradient(ellipse 80% 55% at 15% 40%, rgba(0,180,180,0.09) 0%, transparent 65%)",
          "radial-gradient(ellipse 65% 75% at 85% 65%, rgba(0,90,200,0.07) 0%, transparent 65%)",
          "radial-gradient(ellipse 40% 40% at 50% 10%, rgba(0,200,220,0.05) 0%, transparent 60%)",
          "radial-gradient(circle at 50% 50%, rgba(255,255,255,0.018) 1px, transparent 1px)",
        ].join(", "),
        backgroundSize: "auto, auto, auto, 28px 28px",
      }}
    >
      {/* ── Pharma background image layer ──────────────────────────────────── */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
        {/* Base image — full bleed, object-right so vials are always on the right side */}
        <img
          src="/pharma-bg.jpg"
          alt=""
          className="absolute inset-0 h-full w-full object-cover object-right"
          style={{ opacity: 0.18 }}
        />
        {/* Left vignette — fades the image away behind hero text */}
        <div
          className="absolute inset-0"
          style={{
            background: "linear-gradient(to right, #06101e 0%, #06101e 22%, rgba(6,16,30,0.88) 40%, rgba(6,16,30,0.45) 62%, rgba(6,16,30,0.15) 100%)",
          }}
        />
        {/* Top vignette — keeps top area dark/clean */}
        <div
          className="absolute inset-0"
          style={{
            background: "linear-gradient(to bottom, #06101e 0%, rgba(6,16,30,0.6) 18%, transparent 40%, rgba(6,16,30,0.55) 80%, #06101e 100%)",
          }}
        />
        {/* Cyan tint wash over the image to harmonise with the teal palette */}
        <div
          className="absolute inset-0"
          style={{
            background: "linear-gradient(135deg, transparent 30%, rgba(0,160,180,0.06) 60%, rgba(0,80,200,0.05) 100%)",
          }}
        />
      </div>

      {/* Ambient glow orbs — keep on top of the image layer */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
        <div className="absolute -left-48 top-1/4 h-[500px] w-[500px] rounded-full bg-cyan-500/8 blur-[140px]" />
        <div className="absolute -right-48 bottom-1/4 h-[500px] w-[500px] rounded-full bg-blue-600/8 blur-[140px]" />
        <div className="absolute left-1/3 -top-20 h-72 w-72 rounded-full bg-teal-400/5 blur-[90px]" />
      </div>

      {/* ── LEFT HERO PANEL ──────────────────────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0, x: -28 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.75, ease: [0.22, 1, 0.36, 1] }}
        className="relative hidden flex-col justify-between p-12 lg:flex lg:w-[58%]"
      >
        {/* Logo */}
        <div
          className="relative inline-flex overflow-hidden rounded-2xl px-5 py-3"
          style={{
            background: "linear-gradient(135deg, rgba(0,200,220,0.08) 0%, rgba(0,80,200,0.06) 100%)",
            border: "1px solid rgba(0,200,220,0.18)",
            boxShadow: "0 0 32px rgba(0,200,220,0.12), 0 0 60px rgba(0,90,200,0.08), inset 0 1px 0 rgba(255,255,255,0.08)",
          }}
        >
          {/* Top specular highlight */}
          <div
            className="pointer-events-none absolute inset-0"
            aria-hidden
            style={{
              background: "radial-gradient(ellipse 80% 50% at 50% 0%, rgba(255,255,255,0.09) 0%, transparent 70%)",
            }}
          />
          <img
            src="/placeware-logo.jpg"
            alt="Placeware Nigeria Limited"
            className="relative h-14 w-auto object-contain"
            style={{
              filter: "drop-shadow(0 2px 12px rgba(0,200,220,0.4)) drop-shadow(0 0 4px rgba(255,255,255,0.12))",
            }}
          />
        </div>

        {/* Hero copy */}
        <div className="max-w-[520px] space-y-5">
          <motion.p
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.25 }}
            className="text-[11px] font-bold uppercase tracking-[0.22em] text-cyan-400/75"
          >
            Welcome to ACE
          </motion.p>

          <motion.h1
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.3 }}
            className="text-[2.6rem] font-extrabold leading-[1.12] tracking-tight text-white lg:text-[3.1rem]"
          >
            ENTERPRISE<br />
            <span className="bg-gradient-to-r from-cyan-300 to-blue-400 bg-clip-text text-transparent">
              PHARMACEUTICAL
            </span><br />
            INTELLIGENCE
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.4 }}
            className="max-w-md text-sm leading-relaxed text-white/45"
          >
            A unified platform for Placeware Nigeria — combining AI-powered analytics, pharma
            compliance, cold-chain monitoring, and real-time business intelligence in a single
            secure dashboard.
          </motion.p>

          {/* Feature cards — echoing the 3-image strip in the reference */}
          <div className="mt-2 space-y-3">
            {FEATURES.map((f, i) => {
              const Icon = f.icon;
              return (
                <motion.div
                  key={f.title}
                  initial={{ opacity: 0, x: -18 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.5, delay: 0.45 + i * 0.13, ease: [0.22, 1, 0.36, 1] }}
                  className={`flex items-start gap-4 rounded-xl border bg-gradient-to-r p-4 ${f.gradient} ${f.border}`}
                  style={{ backdropFilter: "blur(8px)" }}
                >
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-white/8">
                    <Icon className={`h-5 w-5 ${f.iconColor}`} />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-white">{f.title}</p>
                    <p className="mt-0.5 text-xs leading-relaxed text-white/45">{f.desc}</p>
                  </div>
                </motion.div>
              );
            })}
          </div>
        </div>

        {/* Bottom credit */}
        <p className="text-[11px] text-white/25">
          © 2026 Placeware Nigeria Limited · All rights reserved
        </p>
      </motion.div>

      {/* ── RIGHT LOGIN PANEL ────────────────────────────────────────────────── */}
      <div className="relative flex flex-1 items-center justify-center p-6 lg:p-14">
        {/* Vertical divider (desktop) */}
        <div
          className="absolute left-0 top-[8%] hidden h-[84%] w-px lg:block"
          style={{ background: "linear-gradient(to bottom, transparent, rgba(255,255,255,0.08) 30%, rgba(255,255,255,0.08) 70%, transparent)" }}
          aria-hidden
        />

        <motion.div
          initial={{ opacity: 0, y: 22 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.65, delay: 0.18, ease: [0.22, 1, 0.36, 1] }}
          className="w-full max-w-[360px]"
        >
          {/* Mobile-only logo */}
          <div className="mb-8 flex justify-center lg:hidden">
            <div
              className="relative inline-flex overflow-hidden rounded-xl px-4 py-2.5"
              style={{
                background: "linear-gradient(135deg, rgba(0,200,220,0.08) 0%, rgba(0,80,200,0.06) 100%)",
                border: "1px solid rgba(0,200,220,0.18)",
                boxShadow: "0 0 24px rgba(0,200,220,0.12), inset 0 1px 0 rgba(255,255,255,0.07)",
              }}
            >
              <div
                className="pointer-events-none absolute inset-0"
                aria-hidden
                style={{
                  background: "radial-gradient(ellipse 80% 50% at 50% 0%, rgba(255,255,255,0.08) 0%, transparent 70%)",
                }}
              />
              <img
                src="/placeware-logo.jpg"
                alt="Placeware Nigeria Limited"
                className="relative mx-auto h-11 w-auto object-contain"
                style={{
                  filter: "drop-shadow(0 2px 10px rgba(0,200,220,0.35)) drop-shadow(0 0 3px rgba(255,255,255,0.1))",
                }}
              />
            </div>
          </div>

          {/* Glassmorphism card */}
          <div
            className="rounded-2xl border border-white/10 p-8 shadow-2xl"
            style={{
              background: "rgba(255,255,255,0.042)",
              backdropFilter: "blur(28px)",
              WebkitBackdropFilter: "blur(28px)",
            }}
          >
            {/* Nav accent strip — mirrors the teal nav bar in the template */}
            <div
              className="mb-7 flex items-center gap-2 rounded-xl px-4 py-2.5"
              style={{ background: "linear-gradient(90deg, rgba(0,195,195,0.18) 0%, rgba(0,110,200,0.12) 100%)", border: "1px solid rgba(0,200,220,0.18)" }}
            >
              <div className="h-2 w-2 rounded-full bg-cyan-400 shadow-[0_0_6px_rgba(0,200,220,0.8)]" />
              <span className="text-[11px] font-semibold uppercase tracking-widest text-cyan-300/80">
                Secure Access Portal
              </span>
            </div>

            <div className="mb-6 space-y-1">
              <h2 className="text-[1.35rem] font-bold text-white">Staff Sign-In</h2>
              <p className="text-xs text-white/40">Securely access your Placeware dashboard</p>
            </div>

            <form className="space-y-4" onSubmit={onSubmit}>
              <div className="space-y-1.5">
                <label className="text-[11px] font-semibold uppercase tracking-wide text-white/50">
                  Email
                </label>
                <Input
                  type="email"
                  placeholder="you@placeware.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  className="border-white/10 bg-white/5 text-white placeholder:text-white/20 focus-visible:border-cyan-400/50 focus-visible:ring-1 focus-visible:ring-cyan-400/30"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-[11px] font-semibold uppercase tracking-wide text-white/50">
                  Password
                </label>
                <div className="relative">
                  <Input
                    type={showPw ? "text" : "password"}
                    placeholder="Password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    className="border-white/10 bg-white/5 pr-10 text-white placeholder:text-white/20 focus-visible:border-cyan-400/50 focus-visible:ring-1 focus-visible:ring-cyan-400/30"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPw((p) => !p)}
                    tabIndex={-1}
                    aria-label={showPw ? "Hide password" : "Show password"}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-white/25 transition-colors hover:text-white/60"
                  >
                    {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>

              {error && (
                <motion.p
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="text-xs text-red-400"
                >
                  {error}
                </motion.p>
              )}

              <Button
                type="submit"
                disabled={isLoading}
                className="mt-1 w-full border-0 font-semibold text-white"
                style={{
                  background: "linear-gradient(90deg, #06b6d4 0%, #3b82f6 100%)",
                }}
              >
                {isLoading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Signing in…
                  </>
                ) : (
                  "Sign In"
                )}
              </Button>
            </form>

            <p className="mt-6 text-center text-[10px] leading-relaxed text-white/20">
              Authorized personnel only · This system is monitored and all access is logged
            </p>
          </div>

          <p className="mt-5 text-center text-[11px] text-white/20">
            Placeware Nigeria Limited © 2026
          </p>
        </motion.div>
      </div>
    </div>
  );
};

export default Login;
