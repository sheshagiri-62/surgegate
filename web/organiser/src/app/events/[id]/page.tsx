import { redirect } from "next/navigation";

import LivePanel from "@/components/LivePanel";
import { ApiError, api, type EventOut, type QueueState } from "@/lib/api";
import { token } from "@/lib/session";

export const dynamic = "force-dynamic";

type Search = { checkin?: string; seat?: string; detail?: string; error?: string };

export default async function EventPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Search>;
}) {
  const t = await token();
  if (!t) redirect("/login");
  const { id } = await params;
  const q = await searchParams;
  let ev: EventOut;
  try {
    ev = await api<EventOut>(`/org/events/${id}`, t);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) redirect("/login?error=Session%20expired");
    throw err;
  }
  let queue: QueueState | null = null;
  try {
    queue = await api<QueueState>(`/org/events/${id}/queue`, t);
  } catch {
    queue = null; // no waiting room opened yet
  }
  const action = `/organiser/events/${id}`;
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{ev.name}</h1>
        <p className="text-slate-500">
          {ev.venue} · {new Date(ev.starts_at).toLocaleString("en-IN")} · {ev.seat_count} seats
        </p>
      </div>

      <LivePanel eventId={id} />

      <section className="space-y-2 rounded-lg border border-slate-300 p-4 dark:border-slate-700">
        <h2 className="font-semibold">Waiting room</h2>
        {queue ? (
          <>
            <p>
              Status <strong>{queue.status}</strong> · admitting <strong>{queue.admission_rate}</strong>{" "}
              per minute
            </p>
            <div className="flex flex-wrap gap-2">
              <form action={`${action}/queue`} method="post">
                <input type="hidden" name="action" value={queue.status === "paused" ? "resume" : "pause"} />
                <button className="rounded bg-amber-600 px-4 py-2 text-white">
                  {queue.status === "paused" ? "Resume" : "Pause"}
                </button>
              </form>
              <form action={`${action}/queue`} method="post" className="flex gap-2">
                <input
                  name="admission_rate"
                  type="number"
                  min={0}
                  max={10000}
                  defaultValue={queue.admission_rate}
                  className="w-28 rounded border px-2 py-2 text-slate-900"
                />
                <button className="rounded bg-indigo-600 px-4 py-2 text-white">Set rate</button>
              </form>
            </div>
          </>
        ) : (
          <p className="text-slate-500">No waiting room is open for this event.</p>
        )}
      </section>

      <section className="space-y-2 rounded-lg border border-slate-300 p-4 dark:border-slate-700">
        <h2 className="font-semibold">Gate check-in</h2>
        {q.checkin && (
          <p
            role="status"
            className={
              q.checkin === "admitted"
                ? "rounded bg-emerald-100 px-3 py-2 text-emerald-900"
                : "rounded bg-red-100 px-3 py-2 text-red-800"
            }
          >
            {q.checkin === "admitted" ? `Admitted: seat ${q.seat}` : `${q.checkin}${q.seat ? `: seat ${q.seat}` : ""}`}
            {q.detail ? ` (${q.detail})` : ""}
          </p>
        )}
        <form action={`${action}/check-in`} method="post" className="flex gap-2">
          <input
            name="token"
            required
            placeholder="Scan or paste the ticket's QR code"
            className="flex-1 rounded border px-3 py-2 font-mono text-sm text-slate-900"
          />
          <button className="rounded bg-emerald-700 px-4 py-2 text-white">Check in</button>
        </form>
      </section>

      <a href={`${action}/attendees`} className="inline-block underline">
        Download attendees (CSV)
      </a>
      {q.error && <p className="rounded bg-red-100 px-3 py-2 text-red-800">{q.error}</p>}
    </div>
  );
}
