"use client";

// "My tickets": every paid order with its seats and a short-lived PDF link (5 minutes; the
// page fetches a fresh one each time you open it or press the button).
import { useCallback, useEffect, useState } from "react";

import SignIn from "@/components/SignIn";
import { ApiError, getMyTickets, type MyTicketsOrder } from "@/lib/api";
import { loadTokens, signOut, type Tokens } from "@/lib/cognito";

export default function TicketsPage() {
  const [tokens, setTokens] = useState<Tokens | null>(() =>
    typeof window === "undefined" ? null : loadTokens(),
  );
  const [orders, setOrders] = useState<MyTicketsOrder[] | null>(null);
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    if (!tokens) return;
    try {
      setOrders((await getMyTickets(tokens.accessToken)).orders);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        signOut();
        setTokens(null);
      } else {
        setMessage(err instanceof Error ? err.message : String(err));
      }
    }
  }, [tokens]);

  useEffect(() => {
    const t = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(t);
  }, [refresh]);

  if (!tokens) return <SignIn onSignedIn={setTokens} />;
  if (!orders) return <p>{message || "Loading your tickets…"}</p>;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">My tickets</h1>
        <button className="text-sm underline" onClick={() => void refresh()}>
          Refresh links
        </button>
      </div>
      {orders.length === 0 && <p>No tickets yet.</p>}
      {orders.map((o) => (
        <div key={o.order_id} className="rounded-lg border border-slate-300 p-4 dark:border-slate-700">
          <p className="font-medium">{o.event.name}</p>
          <p className="text-sm text-slate-500">
            {o.event.venue} · {new Date(o.event.starts_at).toLocaleString("en-IN")}
          </p>
          <p className="mt-2">
            {o.tickets.map((t) => (
              <span key={t.ticket_id} className="mr-2">
                {t.seat}
                {t.used_at ? " (used)" : ""}
              </span>
            ))}
          </p>
          {o.pdf_url ? (
            <a className="mt-2 inline-block underline" href={o.pdf_url}>
              Download tickets (PDF, link valid 5 minutes)
            </a>
          ) : (
            <p className="mt-2 text-sm text-slate-500">Your tickets are being prepared…</p>
          )}
        </div>
      ))}
      {message && <p role="alert" className="text-red-700">{message}</p>}
    </div>
  );
}
