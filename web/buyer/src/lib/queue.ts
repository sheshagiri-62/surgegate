// Waiting-room client: API calls (API Gateway) and the pure logic of what the page shows.
//
// Blueprint flow: join once -> get a signed queue token with your position -> poll ONLY the
// public, cacheable "now serving" counter -> when your number is reached, swap the token for a
// 15-minute booking pass -> go to the seats.

const QUEUE_API = process.env.NEXT_PUBLIC_QUEUE_API ?? "";

export interface Serving {
  event_id: string;
  status: "pre-queue" | "shuffling" | "open" | "paused" | string;
  serving_up_to: number;
  admission_rate: number;
  sale_starts_at: string;
}

export interface Position {
  status: "joining" | "pre-queue" | "queued" | "admitted";
  position?: number;
  serving_up_to?: number;
  queue_token?: string;
  sale_starts_at?: string;
}

export interface BookingPass {
  booking_pass: string;
  expires_at: string;
}

export class QueueError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const headers: Record<string, string> = { ...((init.headers as Record<string, string>) ?? {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const r = await fetch(QUEUE_API + path, { ...init, headers, cache: "no-store" });
  const body = await r.json().catch(() => ({}));
  if (!r.ok && r.status !== 202) throw new QueueError(r.status, String(body.detail ?? body.message ?? r.status));
  return body as T;
}

export const getServing = (eventId: string) => call<Serving>(`/queue/${eventId}/serving`);

export const joinQueue = (eventId: string, token: string) =>
  call<{ request_id: string }>(`/queue/${eventId}/join`, { method: "POST" }, token);

export const getPosition = (eventId: string, token: string, requestId?: string) =>
  call<Position>(`/queue/${eventId}/position${requestId ? `?req=${requestId}` : ""}`, {}, token);

export const admit = (eventId: string, queueToken: string, token: string) =>
  call<BookingPass>(
    `/queue/${eventId}/admit`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ queue_token: queueToken }) },
    token,
  );

// --- per-event browser storage (this tab only) ----------------------------------------------

const key = (eventId: string, what: string) => `surgegate.${what}.${eventId}`;

export function saveJoin(eventId: string, requestId: string): void {
  sessionStorage.setItem(key(eventId, "join"), requestId);
}
export function loadJoin(eventId: string): string | null {
  return sessionStorage.getItem(key(eventId, "join"));
}
export function savePass(eventId: string, pass: BookingPass): void {
  sessionStorage.setItem(key(eventId, "pass"), JSON.stringify(pass));
}
/** A booking pass that is still valid for at least `marginMs`, else null. */
export function loadPass(eventId: string, now = Date.now(), marginMs = 5000): BookingPass | null {
  try {
    const p = JSON.parse(sessionStorage.getItem(key(eventId, "pass")) ?? "null") as BookingPass | null;
    return p && Date.parse(p.expires_at) - marginMs > now ? p : null;
  } catch {
    return null;
  }
}
export function clearPass(eventId: string): void {
  sessionStorage.removeItem(key(eventId, "pass"));
}

// --- what to show (pure) ----------------------------------------------------------------------

export type View =
  | { phase: "before-sale"; startsInMs: number }
  | { phase: "placing" } // joined, waiting for a number (sequencer / shuffle at the start)
  | { phase: "in-line"; position: number; ahead: number; etaSeconds: number | null; paused: boolean }
  | { phase: "your-turn"; position: number };

export function view(position: Position | null, serving: Serving | null, now: number): View {
  const saleAt = Date.parse(serving?.sale_starts_at ?? position?.sale_starts_at ?? "");
  if (!position?.position) {
    if (!Number.isNaN(saleAt) && now < saleAt) return { phase: "before-sale", startsInMs: saleAt - now };
    return { phase: "placing" };
  }
  const served = Math.max(serving?.serving_up_to ?? 0, position.serving_up_to ?? 0);
  if (position.position <= served) return { phase: "your-turn", position: position.position };
  const ahead = position.position - served - 1;
  const paused = serving?.status === "paused";
  const rate = serving?.admission_rate ?? 0;
  const etaSeconds = paused || rate <= 0 ? null : Math.ceil((ahead + 1) / rate) * 60;
  return { phase: "in-line", position: position.position, ahead, etaSeconds, paused };
}

/** "about 4 minutes" / "less than a minute" / "" */
export function waitText(etaSeconds: number | null): string {
  if (etaSeconds === null) return "";
  if (etaSeconds <= 60) return "less than a minute";
  const minutes = Math.round(etaSeconds / 60);
  return minutes < 60 ? `about ${minutes} minutes` : `about ${Math.round(minutes / 60)} h ${minutes % 60} min`;
}

/**
 * Ask for our own position only after the sale has started. Before that, places have no number
 * (they are shuffled at the start), so polling /position would only add load. Unknown status
 * (first /serving answer not in yet) also waits.
 */
export function mayAskPosition(serving: Serving | null): boolean {
  return !!serving && serving.status !== "pre-queue" && serving.status !== "shuffling";
}
