import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/components/AuthProvider";
import { AuthError } from "@/lib/auth-client";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { motion } from "framer-motion";
import { Loader2, Eye, EyeOff } from "lucide-react";

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
    } catch (err) {
      setError(
        err instanceof AuthError
          ? err.message
          : "Invalid email or password. Please try again.",
      );
    }
  };

  return (
    <div
      className="relative flex min-h-dvh overflow-hidden pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)] pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]"
      style={{
        background: "#06101e",
        backgroundImage: [
          "radial-gradient(ellipse 80% 55% at 15% 40%, rgba(0,180,180,0.09) 0%, transparent 65%)",
          "radial-gradient(ellipse 65% 75% at 85% 65%, rgba(0,90,200,0.07) 0%, transparent 65%)",
          "radial-gradient(ellipse 40% 40% at 50% 10%, rgba(98,199,106,0.05) 0%, transparent 60%)",
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
        {/* Blue-green tint wash over the image, matching the brand gradient */}
        <div
          className="absolute inset-0"
          style={{
            background: "linear-gradient(135deg, transparent 30%, rgba(98,199,106,0.05) 60%, rgba(0,58,145,0.05) 100%)",
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
        {/* Logo — transparent mark on a soft halo. No plate or border: the
            wordmark should read as part of the hero, not as a pasted-in
            image sitting in its own box. */}
        <div className="relative inline-flex px-1 py-1">
          <div
            className="pointer-events-none absolute -inset-6"
            aria-hidden
            style={{
              background:
                "radial-gradient(ellipse 70% 80% at 35% 50%, rgba(98,199,106,0.16) 0%, transparent 70%)," +
                "radial-gradient(ellipse 60% 70% at 80% 40%, rgba(0,58,145,0.22) 0%, transparent 72%)",
            }}
          />
          <img
            src="/placeware-logo-onDark.png"
            alt="Placeware Nigeria Limited"
            className="relative h-14 w-auto object-contain"
            style={{ filter: "drop-shadow(0 2px 12px rgba(0,0,0,0.55))" }}
          />
        </div>

        {/* Hero copy — kept short and warm on purpose: this is a staff
            sign-in, not a marketing page. One welcome line, one tagline,
            one sentence of context, done. */}
        <div className="max-w-[480px] space-y-4">
          <motion.p
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.25 }}
            className="text-[11px] font-bold uppercase tracking-[0.22em] text-green-400/75"
          >
            ACE · Placeware Intelligence System
          </motion.p>

          <motion.h1
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.3 }}
            className="text-[2.6rem] font-extrabold leading-[1.12] tracking-tight text-white lg:text-[3.4rem]"
          >
            Welcome to{" "}
            <span className="bg-gradient-to-r from-blue-400 to-green-400 bg-clip-text text-transparent">
              Placeware
            </span>
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.38 }}
            className="text-lg font-medium text-white/70"
          >
            Designed for Placeware — built to grow, and built to last.
          </motion.p>

          <motion.p
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.46 }}
            className="max-w-sm text-sm leading-relaxed text-white/40"
          >
            Everything your team needs to run the business — inventory, finance, compliance, and more — in one place.
          </motion.p>
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
            <div className="relative inline-flex">
              <div
                className="pointer-events-none absolute -inset-5"
                aria-hidden
                style={{
                  background:
                    "radial-gradient(ellipse 70% 80% at 50% 50%, rgba(98,199,106,0.14) 0%, transparent 70%)",
                }}
              />
              <img
                src="/placeware-logo-onDark.png"
                alt="Placeware Nigeria Limited"
                className="relative mx-auto h-11 w-auto object-contain"
                style={{ filter: "drop-shadow(0 2px 10px rgba(0,0,0,0.5))" }}
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
            {/* Nav accent strip — green brand accent for visual variety against the blue logo chrome above */}
            <div
              className="mb-7 flex items-center gap-2 rounded-xl px-4 py-2.5"
              style={{ background: "linear-gradient(90deg, rgba(98,199,106,0.18) 0%, rgba(0,58,145,0.10) 100%)", border: "1px solid rgba(98,199,106,0.20)" }}
            >
              <div className="h-2 w-2 rounded-full bg-green-400 shadow-[0_0_6px_rgba(98,199,106,0.8)]" />
              <span className="text-[11px] font-semibold uppercase tracking-widest text-green-300/80">
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
                  background: "linear-gradient(90deg, #003A91 0%, #62C76A 100%)",
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
