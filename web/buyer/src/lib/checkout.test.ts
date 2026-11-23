import { canPay, orderKey, orderView } from "./checkout";

function memoryStore() {
  const m = new Map<string, string>();
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) };
}

describe("orderKey", () => {
  it("reuses one key per hold (double click / reload = same order)", () => {
    const store = memoryStore();
    let n = 0;
    const gen = () => `key-${++n}`;
    expect(orderKey("hold-1", store, gen)).toBe("key-1");
    expect(orderKey("hold-1", store, gen)).toBe("key-1");
    expect(orderKey("hold-2", store, gen)).toBe("key-2");
  });
});

describe("canPay", () => {
  const now = Date.parse("2026-11-24T12:00:00Z");
  it("needs at least 60 seconds left on the hold", () => {
    expect(canPay("2026-11-24T12:01:00Z", now)).toBe(true);
    expect(canPay("2026-11-24T12:00:59Z", now)).toBe(false);
  });
});

describe("orderView", () => {
  const none = new URLSearchParams();
  it("shows pending until the webhook confirms", () => {
    expect(orderView({ status: "pending" }, none)).toEqual({ kind: "pending", failedAttempt: false });
  });
  it("tells the buyer a failed attempt can be retried", () => {
    expect(orderView({ status: "pending" }, new URLSearchParams("id=o&payment=failed"))).toEqual({
      kind: "pending",
      failedAttempt: true,
    });
  });
  it("trusts the order status, not the redirect", () => {
    // A redirect claiming success does not make the order paid; only the API status does.
    const fakeSuccess = new URLSearchParams("id=o&razorpay_payment_id=pay_x");
    expect(orderView({ status: "pending" }, fakeSuccess).kind).toBe("pending");
    expect(orderView({ status: "paid" }, none)).toEqual({ kind: "paid" });
  });
});
