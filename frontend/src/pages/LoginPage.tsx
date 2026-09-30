import { useState } from "react";
import { MessageCircle } from "lucide-react";
import { useAuth } from "../stores/auth";
import { useToast } from "../stores/toast";
import { ApiError } from "../lib/api";

export function LoginPage() {
  const { login } = useAuth();
  const { push } = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
      push("success", "خوش آمدید!");
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "ورود ناموفق بود");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center bg-canvas p-4">
      <div className="card w-full max-w-sm p-7 shadow-xl">
        <div className="mb-6 flex flex-col items-center gap-2 text-center">
          <div className="flex size-12 items-center justify-center rounded-2xl bg-brand-600 text-white">
            <MessageCircle className="size-6" />
          </div>
          <h1 className="text-base font-extrabold">میزبــان پشتیبانی ایتـا</h1>
          <p className="text-xs text-ink-faint">برای ورود به پنل پشتیبانی، اطلاعات خود را وارد کنید</p>
        </div>

        <form onSubmit={submit} className="space-y-3.5">
          <div>
            <label htmlFor="email" className="mb-1.5 block text-xs font-semibold">
              ایمیل
            </label>
            <input
              id="email"
              type="email"
              dir="ltr"
              className="input text-left"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
              autoFocus
            />
          </div>
          <div>
            <label htmlFor="password" className="mb-1.5 block text-xs font-semibold">
              گذرواژه
            </label>
            <input
              id="password"
              type="password"
              dir="ltr"
              className="input text-left"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>

          {error && (
            <p role="alert" className="rounded-lg bg-red-500/10 p-2.5 text-xs text-red-600">
              {error}
            </p>
          )}

          <button type="submit" className="btn btn-primary w-full !py-2.5" disabled={busy}>
            {busy ? "در حال ورود…" : "ورود به پنل"}
          </button>
        </form>
      </div>
    </div>
  );
}
