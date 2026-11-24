// The browser asks for a 60-second live token; this server adds the organiser's cookie token.
import { api } from "@/lib/api";
import { token } from "@/lib/session";

export async function POST(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const t = await token();
  if (!t) return Response.json({ error: "signed out" }, { status: 401 });
  const { id } = await params;
  try {
    return Response.json(await api(`/org/events/${id}/live-token`, t, { method: "POST" }));
  } catch (err) {
    return Response.json({ error: String(err) }, { status: 502 });
  }
}
