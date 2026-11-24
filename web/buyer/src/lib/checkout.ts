// Checkout helpers (Day 7 Task 3). Pure where possible so they are easy to test.
import type { Order } from "./api";

/** The API refuses to start a payment with less than this left on the hold (409). */
export const MIN_SECONDS_TO_PAY = 60;

type KeyStore = Pick<Storage, "getItem" | "setItem" | "removeItem">;

/**
 * One Idempotency-Key per hold, kept for the browser tab: a double click, a retry after a
 * network error or a page reload all reuse it, so the API returns the same order.
 */
export function orderKey(
  holdId: string,
  store: KeyStore = sessionStorage,
  newKey: () => string = () => crypto.randomUUID(),
): string {
  const k = `surgegate:checkout:${holdId}`;
  const existing = store.getItem(k);
  if (existing) return existing;
  const key = newKey();
  store.setItem(k, key);
  return key;
}

/** After a FAILED payment the old key would return the failed order: start a new one. */
export function forgetOrderKey(holdId: string, store: KeyStore = sessionStorage): void {
  store.removeItem(`surgegate:checkout:${holdId}`);
}

export function canPay(holdExpiresAt: string, now = Date.now()): boolean {
  return Date.parse(holdExpiresAt) - now >= MIN_SECONDS_TO_PAY * 1000;
}

export type OrderView =
  | { kind: "pending"; failedAttempt: boolean }
  | { kind: "paid" }
  | { kind: "failed" }
  | { kind: "refunded" };

/** What the order page shows. `returnedWith` = query params the checkout sent back. */
export function orderView(order: Pick<Order, "status">, returnedWith: URLSearchParams): OrderView {
  switch (order.status) {
    case "paid":
      return { kind: "paid" };
    case "failed":
      return { kind: "failed" };
    case "refunded":
      return { kind: "refunded" };
    default:
      return { kind: "pending", failedAttempt: returnedWith.get("payment") === "failed" };
  }
}
