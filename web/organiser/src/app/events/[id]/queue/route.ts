// Pause / resume / admission rate: a plain form POST, then back to the event page.
import { api } from "@/lib/api";
import { seeOther } from "@/lib/redirect";
import { token } from "@/lib/session";

export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const t = await token();
  if (!t) return seeOther("/organiser/login");
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
    return seeOther(`/organiser/events/${id}`, { error: String(err instanceof Error ? err.message : err) });
  }
  return seeOther(`/organiser/events/${id}`);
}
