// Server-side calls to the booking API inside the cluster (never from the browser).

const BASE = process.env.BOOKING_API_URL ?? "http://booking-api.booking.svc.cluster.local";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(BASE + path, {
    ...init,
    headers: { ...(init.headers ?? {}), Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  const text = await r.text();
  const body = text && r.headers.get("content-type")?.includes("json") ? JSON.parse(text) : text;
  if (!r.ok) {
    const detail = typeof body === "object" ? (body.detail ?? body.reason ?? JSON.stringify(body)) : body;
    throw new ApiError(r.status, String(detail));
  }
  return body as T;
}

export async function apiRaw(path: string, token: string): Promise<Response> {
  return fetch(BASE + path, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
}

export interface EventOut {
  id: string;
  name: string;
  venue: string;
  starts_at: string;
  sale_starts_at: string;
  per_buyer_limit: number;
  status: string;
  seat_count: number;
}

export interface QueueState {
  status: string;
  admission_rate: number;
  sale_starts_at: string;
  in_line: number;
  admitted: number;
  waiting: number;
}
