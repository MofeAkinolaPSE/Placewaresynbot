import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/components/AuthProvider";

const Login = () => {
  const { login, isLoading } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const navigate = useNavigate();

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    try {
      await login(email, password);
      navigate("/", { replace: true });
    } catch (e) {
      setError("Invalid email or password");
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center p-6">
      <div className="max-w-lg w-full rounded-2xl border border-slate-800 bg-slate-900/60 p-8 shadow-xl">
        <h1 className="text-2xl font-semibold">Staff Sign-In</h1>
        <p className="mt-2 text-sm text-slate-300">
          Securely access Placeware intelligence and analytics dashboards.
        </p>
        <form className="mt-6 space-y-4" onSubmit={onSubmit}>
          <input
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-4 py-3 text-sm"
            type="email"
            placeholder="admin@placeware.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <input
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-4 py-3 text-sm"
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          {error ? <p className="text-sm text-red-400">{error}</p> : null}
          <button
            className="w-full rounded-lg bg-emerald-500 px-4 py-3 text-sm font-semibold text-slate-900 hover:bg-emerald-400 disabled:opacity-60"
            type="submit"
            disabled={isLoading}
          >
            {isLoading ? "Signing in…" : "Sign In"}
          </button>
        </form>
      </div>
    </div>
  );
};

export default Login;
