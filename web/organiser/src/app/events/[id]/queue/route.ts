// Pause / resume / admission rate: a plain form POST, then back to the event page.
import { NextResponse } from "next/server";

import { api } from "@/lib/api";
import { token } from "@/lib/session";

export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const back = new URL(`/organiser/events/${id}`, req.url);
  const t = await token();
  if (!t) return NextResponse.redirect(new URL("/organiser/login", req.url), 303);
  const form = await req.formData();
  const body = form.get("action")
    ? { action: String(form.get("action")) }
    : { admission_rate: Number(form.get("admission_rate")) };
  try {
    await api(`/org/events/${id}/queue`, t, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (err) {
    back.searchParams.set("error", String(err instanceof Error ? err.message : err));
  }
  return NextResponse.redirect(back, 303);
}
