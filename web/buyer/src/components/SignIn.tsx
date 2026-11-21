"use client";

import { useState } from "react";

import {
  finishEmailOtp,
  saveTokens,
  signInWithPassword,
  startEmailOtp,
  type Tokens,
} from "@/lib/cognito";

// Email + one-time code (real buyers) or password (dev test users on the .test domain, which
// cannot receive email).
export default function SignIn({ onSignedIn }: { onSignedIn: (t: Tokens) => void }) {
  const [email, setEmail] = useState("");
  const [mode, setMode] = useState<"otp" | "password">("otp");
  const [session, setSession] = useState<string | null>(null);
  const [secret, setSecret] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (mode === "password") {
        done(await signInWithPassword(email, secret));
      } else if (!session) {
        setSession(await startEmailOtp(email));
      } else {
        done(await finishEmailOtp(email, session, secret));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function done(t: Tokens) {
    saveTokens(t);
    onSignedIn(t);
  }

  const input =
    "w-full rounded border border-slate-300 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-900";
  return (
    <form onSubmit={submit} className="max-w-sm space-y-3 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <h2 className="font-semibold">Sign in to choose seats</h2>
      <input
        className={input}
        type="email"
        autoComplete="email"
        placeholder="you@example.com"
        aria-label="Email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        required
        disabled={!!session}
      />
      {(mode === "password" || session) && (
        <input
          className={input}
          type={mode === "password" ? "password" : "text"}
          inputMode={mode === "otp" ? "numeric" : undefined}
          autoComplete={mode === "password" ? "current-password" : "one-time-code"}
          placeholder={mode === "password" ? "Password" : "Code from your email"}
          aria-label={mode === "password" ? "Password" : "Email code"}
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          required
        />
      )}
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      <button className="w-full rounded bg-indigo-600 px-4 py-2 font-medium text-white disabled:opacity-40" disabled={busy}>
        {busy ? "…" : mode === "password" ? "Sign in" : session ? "Verify code" : "Email me a code"}
      </button>
      <button
        type="button"
        className="text-sm text-indigo-600 underline"
        onClick={() => {
          setMode(mode === "otp" ? "password" : "otp");
          setSession(null);
          setSecret("");
          setError("");
        }}
      >
        {mode === "otp" ? "Use a password instead" : "Use an email code instead"}
      </button>
    </form>
  );
}
