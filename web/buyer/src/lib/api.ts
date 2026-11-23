// Booking API calls. In dev the API is reached through `kubectl port-forward` (localhost:18080);
// with CloudFront (later) it becomes same-origin.
import type { SeatMap } from "./seatmap";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:18080";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

async function request<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(BASE + path, {
    ...init,
    headers: { ...(init.headers ?? {}), Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    const detail = typeof body.detail === "object" ? body.detail.reason : body.detail;
    throw new ApiError(r.status, String(detail ?? `HTTP ${r.status}`), body);
  }
  return body as T;
}

export interface Hold {
  hold_id: string;
  expires_at: string;
  seats: { id: string; label: string; price_paise: number }[];
  amount_paise: number;
}

// Every /book/{event}/... call carries the waiting room's booking pass.
const passHeader = (bookingPass: string) => ({ "X-Booking-Pass": bookingPass });

/** True when the API refused because the booking pass is missing, expired or invalid. */
export function needsQueue(err: unknown): boolean {
  return err instanceof ApiError && err.status === 403 && typeof err.body.detail === "object";
}

export function getSeatMap(eventId: string, token: string, bookingPass: string): Promise<SeatMap> {
  return request<SeatMap>(`/book/${eventId}/seats`, token, { headers: passHeader(bookingPass) });
}

export function holdSeats(
  eventId: string,
  seatIds: string[],
  token: string,
  bookingPass: string,
): Promise<Hold> {
  return request<Hold>(`/book/${eventId}/holds`, token, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...passHeader(bookingPass) },
    body: JSON.stringify({ seat_ids: seatIds }),
  });
}

// --- orders (Day 7 Task 3) ------------------------------------------------------------------

export type Checkout =
  | { type: "redirect"; url: string } // mock provider (ADR 004)
  | { type: "razorpay_js"; key_id: string; order_id: string }; // Razorpay checkout.js, later

export interface Order {
  order_id: string;
  status: "pending" | "paid" | "failed" | "refunded";
  event_id: string;
  hold_id: string;
  hold_expires_at: string;
  seats: string[];
  amount_paise: number;
  currency: string;
  provider: string;
  provider_order_id: string | null;
  checkout: Checkout | null;
  created_at: string;
  paid_at: string | null;
}

/** Same Idempotency-Key = same order (201 the first time, 200 after). */
export function createOrder(
  eventId: string,
  holdId: string,
  idempotencyKey: string,
  returnUrl: string,
  token: string,
  bookingPass: string,
): Promise<Order> {
  return request<Order>(`/book/${eventId}/orders`, token, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
      ...passHeader(bookingPass),
    },
    body: JSON.stringify({ hold_id: holdId, return_url: returnUrl }),
  });
}

/** Outside /book/*: works after the booking pass expires; owner only. */
export function getOrder(orderId: string, token: string): Promise<Order> {
  return request<Order>(`/orders/${orderId}`, token);
}
