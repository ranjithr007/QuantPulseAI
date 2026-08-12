import { useEffect, useState } from "react";
import { LockKeyhole, Sparkles } from "lucide-react";
import { loadSession, login, logout } from "../authApi";

export default function AuthGate({ children }) {
  const [state, setState] = useState({ checking: true, username: null });

  useEffect(() => {
    loadSession()
      .then((session) => setState({ checking: false, username: session.authenticated ? session.username : null }))
      .catch(() => setState({ checking: false, username: null }));
  }, []);

  useEffect(() => {
    const expireSession = () => setState({ checking: false, username: null });
    window.addEventListener("quantpulse:unauthorized", expireSession);
    return () => window.removeEventListener("quantpulse:unauthorized", expireSession);
  }, []);

  if (state.checking) return <AuthenticationLoading />;
  if (!state.username) {
    return <LoginScreen onAuthenticated={(username) => setState({ checking: false, username })} />;
  }

  return children({
    username: state.username,
    onLogout: async () => {
      await logout().catch(() => null);
      setState({ checking: false, username: null });
    },
  });
}

function AuthenticationLoading() {
  return (
    <div className="grid min-h-screen place-items-center bg-slate-950 text-slate-200">
      <div className="flex items-center gap-3 text-sm text-slate-400">
        <span className="h-2 w-2 animate-pulse rounded-full bg-cyan-300" />
        Checking secure session
      </div>
    </div>
  );
}

function LoginScreen({ onAuthenticated }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const session = await login(username, password);
      onAuthenticated(session.username);
    } catch (loginError) {
      setError(loginError.message || "Unable to sign in");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="relative grid min-h-screen place-items-center overflow-hidden bg-slate-950 px-4 py-10 text-slate-100">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(6,182,212,0.16),transparent_42%)]" />
      <form onSubmit={submit} className="relative w-full max-w-md rounded-2xl border border-white/10 bg-slate-900/85 p-6 shadow-2xl shadow-cyan-950/30 backdrop-blur sm:p-8">
        <div className="mb-7 flex items-center gap-3">
          <div className="grid h-11 w-11 place-items-center rounded-xl border border-cyan-400/25 bg-cyan-500/10 text-cyan-300">
            <Sparkles className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-white">QuantPulseAI</h1>
            <p className="text-sm text-slate-400">Secure trading intelligence</p>
          </div>
        </div>

        <div className="mb-6 flex items-center gap-2 rounded-lg border border-cyan-400/15 bg-cyan-500/5 px-3 py-2 text-xs text-cyan-100">
          <LockKeyhole className="h-4 w-4 shrink-0" />
          Sign in to access market data and trading controls.
        </div>

        <label className="block text-sm text-slate-300">
          Username
          <input autoComplete="username" required value={username} onChange={(event) => setUsername(event.target.value)} className="mt-2 h-11 w-full rounded-lg border border-white/10 bg-slate-950/80 px-3 text-white outline-none transition focus:border-cyan-400/50 focus:ring-2 focus:ring-cyan-400/10" />
        </label>
        <label className="mt-4 block text-sm text-slate-300">
          Password
          <input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} className="mt-2 h-11 w-full rounded-lg border border-white/10 bg-slate-950/80 px-3 text-white outline-none transition focus:border-cyan-400/50 focus:ring-2 focus:ring-cyan-400/10" />
        </label>

        {error ? <div role="alert" className="mt-4 rounded-lg border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">{error}</div> : null}

        <button type="submit" disabled={submitting} className="mt-6 h-11 w-full rounded-lg bg-cyan-400 font-semibold text-slate-950 transition hover:bg-cyan-300 disabled:cursor-wait disabled:opacity-60">
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
