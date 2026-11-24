import { redirect } from "next/navigation";

import { ApiError, api, type EventOut } from "@/lib/api";
import { token } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function Events() {
  const t = await token();
  if (!t) redirect("/login");
  let events: EventOut[];
  try {
    events = await api<EventOut[]>("/org/events", t);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) redirect("/login?error=Session%20expired");
    throw err;
  }
  return (
    <div className="space-y-3">
      <h1 className="text-2xl font-semibold">Your events</h1>
      {events.length === 0 && <p>No events yet.</p>}
      <ul className="divide-y divide-slate-200 dark:divide-slate-800">
        {events.map((e) => (
          <li key={e.id} className="py-3">
            <a href={`/organiser/events/${e.id}`} className="font-medium underline">
              {e.name}
            </a>
            <span className="ml-2 text-sm text-slate-500">
              {e.venue} · {new Date(e.starts_at).toLocaleString("en-IN")} · {e.seat_count} seats
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
