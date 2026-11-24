// Gate check-in: send the scanned token to the booking API; show the result on the page.
import { seeOther } from "@/lib/redirect";
import { token } from "@/lib/session";

const BASE = process.env.BOOKING_API_URL ?? "http://booking-api.booking.svc.cluster.local";

export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const t = await token();
  if (!t) return seeOther("/organiser/login");
  const form = await req.formData();
  const r = await fetch(`${BASE}/org/events/${id}/check-in`, {
    method: "POST",
    headers: { Authorization: `Bearer ${t}`, "Content-Type": "application/json" },
    body: JSON.stringify({ token: String(form.get("token") ?? "").trim() }),
    cache: "no-store",
  });
  const body = await r.json().catch(() => ({}));
  const q: Record<string, string> = { checkin: body.result ?? `error ${r.status}` };
  if (body.seat) q.seat = body.seat;
  // used_at is UTC; say so (the server has no local time zone).
  const detail = body.reason ?? (body.used_at ? `first used ${String(body.used_at).slice(11, 19)} UTC` : "");
  if (detail) q.detail = detail;
  return seeOther(`/organiser/events/${id}`, q);
}
