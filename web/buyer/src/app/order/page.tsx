"use client";

// Where the payment provider sends the buyer back: /order/?id=<order>[&payment=failed|...].
// The page trusts only the API's order status (a redirect can be faked); it polls until the
// webhook has confirmed the order (Day 7 Task 4).
import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import SignIn from "@/components/SignIn";
import { ApiError, getOrder, type Order } from "@/lib/api";
import { orderView } from "@/lib/checkout";
import { loadTokens, signOut, type Tokens } from "@/lib/cognito";
import { formatInr } from "@/lib/seatmap";

const POLL_MS = 3000;

function OrderPage() {
  const params = useSearchParams();
  const orderId = params.get("id") ?? "";
  const [tokens, setTokens] = useState<Tokens | null>(() => loadTokens());
  const [order, setOrder] = useState<Order | null>(null);
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    if (!tokens || !orderId) return;
    try {
      setOrder(await getOrder(orderId, tokens.accessToken));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        signOut();
        setTokens(null);
      } else {
        setMessage(err instanceof Error ? err.message : String(err));
      }
    }
  }, [tokens, orderId]);

  const pending = !order || order.status === "pending";
  useEffect(() => {
    if (!pending) return;
    const first = setTimeout(() => void refresh(), 0);
    const t = setInterval(() => void refresh(), POLL_MS);
    return () => {
      clearTimeout(first);
      clearInterval(t);
    };
  }, [refresh, pending]);

  if (!orderId) return <p>No order selected.</p>;
  if (!tokens) return <SignIn onSignedIn={setTokens} />;
  if (!order) return <p>{message || "Loading your order…"}</p>;

  const v = orderView(order, params);
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Your order</h1>
      <p>
        {order.seats.join(", ")} · {formatInr(order.amount_paise)}
      </p>
      {v.kind === "paid" && (
        <p role="status" className="rounded bg-emerald-100 px-3 py-2 text-emerald-900">
          Payment confirmed. Your ticket is on its way by email.
        </p>
      )}
      {v.kind === "pending" && (
        <div role="status" className="rounded bg-amber-100 px-3 py-2 text-amber-900">
          {v.failedAttempt ? (
            <p>
              The payment failed. Your seats stay held until{" "}
              {new Date(order.hold_expires_at).toLocaleTimeString("en-IN")}; you can{" "}
              <a className="underline" href={`/event/?id=${order.event_id}`}>
                try again
              </a>
              .
            </p>
          ) : (
            <p>Payment pending: waiting for the payment provider&apos;s confirmation…</p>
          )}
        </div>
      )}
      {v.kind === "failed" && (
        <p role="alert" className="rounded bg-red-100 px-3 py-2 text-red-800">
          This order was not paid.
        </p>
      )}
      {v.kind === "refunded" && (
        <p role="status" className="rounded bg-slate-100 px-3 py-2 text-slate-800">
          This payment was refunded (test mode): the seats were no longer available.
        </p>
      )}
      {message && <p role="alert" className="text-red-700">{message}</p>}
      <p className="text-xs text-slate-500">Order {order.order_id}</p>
    </div>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<p>Loading…</p>}>
      <OrderPage />
    </Suspense>
  );
}
