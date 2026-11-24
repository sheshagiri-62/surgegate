// Gate check-in: send the scanned token to the booking API; show the result on the page.
import { NextResponse } from "next/server";

import { token } from "@/lib/session";

const BASE = process.env.BOOKING_API_URL ?? "http://booking-api.booking.svc.cluster.local";

export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const back = new URL(`/organiser/events/${id}`, req.url);
  const t = await token();
  if (!t) return NextResponse.redirect(new URL("/organiser/login", req.url), 303);
  const form = await req.formData();
  const r = await fetch(`${BASE}/org/events/${id}/check-in`, {
    method: "POST",
    headers: { Authorization: `Bearer ${t}`, "Content-Type": "application/json" },
    body: JSON.stringify({ token: String(form.get("token") ?? "").trim() }),
    cache: "no-store",
  });
  const body = await r.json().catch(() => ({}));
  back.searchParams.set("checkin", body.result ?? `error ${r.status}`);
  if (body.seat) back.searchParams.set("seat", body.seat);
  const detail = body.reason ?? (body.used_at ? `first used ${new Date(body.used_at).toLocaleTimeString("en-IN")}` : "");
  if (detail) back.searchParams.set("detail", detail);
  return NextResponse.redirect(back, 303);
}
