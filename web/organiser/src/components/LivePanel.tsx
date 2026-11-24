"use client";

// Live numbers over the WebSocket: get a 60-second token from our server, connect, show every
// push. Reconnects (with a fresh token) if the connection drops.
import { useEffect, useState } from "react";

interface Stats {
  waiting: number;
  admitted: number;
  held_seats: number;
  sold_seats: number;
  orders_paid: number;
  revenue_paise: number;
  tickets: number;
  queue_status: string | null;
  admission_rate: number;
}

const inr = (paise: number) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(paise / 100);

export default function LivePanel({ eventId }: { eventId: string }) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [state, setState] = useState("connecting…");
  const [updated, setUpdated] = useState<string>("");

  useEffect(() => {
    let ws: WebSocket | null = null;
    let stopped = false;
    let retry: ReturnType<typeof setTimeout>;

    async function connect() {
      try {
        const r = await fetch(`/organiser/api/live-token/${eventId}`, { method: "POST" });
        if (!r.ok) throw new Error(`token ${r.status}`);
        const { ws_url } = await r.json();
        ws = new WebSocket(ws_url);
        ws.onopen = () => {
          setState("live");
          ws?.send(JSON.stringify({ action: "snapshot" }));
        };
        ws.onmessage = (m) => {
          const data = JSON.parse(m.data);
          if (data.type === "stats") {
            setStats(data);
            setUpdated(new Date().toLocaleTimeString("en-IN"));
          }
        };
        ws.onclose = () => {
          setState("reconnecting…");
          if (!stopped) retry = setTimeout(connect, 3000);
        };
      } catch (err) {
        setState(`offline (${String(err)})`);
        if (!stopped) retry = setTimeout(connect, 5000);
      }
    }
    void connect();
    return () => {
      stopped = true;
      clearTimeout(retry);
      ws?.close();
    };
  }, [eventId]);

  const tiles: [string, string | number][] = stats
    ? [
        ["Waiting", stats.waiting],
        ["Admitted", stats.admitted],
        ["Held seats", stats.held_seats],
        ["Sold seats", stats.sold_seats],
        ["Revenue", inr(stats.revenue_paise)],
        ["Admission rate", `${stats.admission_rate}/min`],
      ]
    : [];
  return (
    <section className="rounded-lg border border-slate-300 p-4 dark:border-slate-700">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-semibold">Live</h2>
        <span className="text-xs text-slate-500" data-testid="live-state">
          {state}
          {updated ? ` · updated ${updated}` : ""}
        </span>
      </div>
      {stats ? (
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {tiles.map(([label, value]) => (
            <div key={label} className="rounded bg-slate-100 p-3 dark:bg-slate-900">
              <dt className="text-xs text-slate-500">{label}</dt>
              <dd className="text-xl font-semibold tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="text-slate-500">Waiting for the first numbers…</p>
      )}
    </section>
  );
}
