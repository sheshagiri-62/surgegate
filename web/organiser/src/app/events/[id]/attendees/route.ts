// Attendee export: stream the booking API's CSV through (the browser never sees the token).
import { apiRaw } from "@/lib/api";
import { token } from "@/lib/session";

export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const t = await token();
  if (!t) return Response.redirect(new URL("/organiser/login", req.url), 303);
  const { id } = await params;
  const r = await apiRaw(`/org/events/${id}/attendees.csv`, t);
  return new Response(r.body, {
    status: r.status,
    headers: {
      "Content-Type": r.headers.get("content-type") ?? "text/csv",
      "Content-Disposition": r.headers.get("content-disposition") ?? "attachment",
      "Cache-Control": "no-store",
    },
  });
}
