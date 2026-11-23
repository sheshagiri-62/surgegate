"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import SeatPicker from "@/components/SeatPicker";
import SignIn from "@/components/SignIn";
import { ApiError, createOrder, getSeatMap, holdSeats, needsQueue, type Hold } from "@/lib/api";
import { canPay, MIN_SECONDS_TO_PAY, orderKey } from "@/lib/checkout";
import { loadTokens, signOut, type Tokens } from "@/lib/cognito";
import { clearPass, loadPass } from "@/lib/queue";
import {
  countdown,
  formatInr,
  pruneSelection,
  toggleSeat,
  total,
  type SeatMap,
} from "@/lib/seatmap";

const REFRESH_MS = 2000; // the API's cache TTL; taken seats grey out within ~2 s

function EventPage() {
  const eventId = useSearchParams().get("id") ?? "";
  const router = useRouter();
  // No valid booking pass for this event: back to the waiting room.
  const toQueue = useCallback(() => {
    clearPass(eventId);
    router.push(`/queue/?id=${eventId}`);
  }, [router, eventId]);
  // This page renders only in the browser (useSearchParams in a static export), so reading
  // sessionStorage in the initializer is safe.
  const [tokens, setTokens] = useState<Tokens | null>(() => loadTokens());
  const [map, setMap] = useState<SeatMap | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [hold, setHold] = useState<Hold | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const refresh = useCallback(async () => {
    if (!tokens || !eventId) return;
    const bookingPass = loadPass(eventId);
    if (!bookingPass) return toQueue();
    try {
      const m = await getSeatMap(eventId, tokens.accessToken, bookingPass.booking_pass);
      setMap(m);
      setSelected((sel) => pruneSelection(sel, m.seats));
    } catch (err) {
      if (needsQueue(err)) {
        toQueue();
      } else if (err instanceof ApiError && err.status === 401) {
        signOut();
        setTokens(null);
      } else {
        setMessage(err instanceof Error ? err.message : String(err));
      }
    }
  }, [tokens, eventId, toQueue]);

  useEffect(() => {
    const first = setTimeout(() => void refresh(), 0);
    const t = setInterval(() => void refresh(), REFRESH_MS);
    return () => {
      clearTimeout(first);
      clearInterval(t);
    };
  }, [refresh]);

  async function onHold() {
    if (!tokens || !map) return;
    const bookingPass = loadPass(eventId);
    if (!bookingPass) return toQueue();
    setBusy(true);
    setMessage("");
    try {
      setHold(await holdSeats(eventId, selected, tokens.accessToken, bookingPass.booking_pass));
      setSelected([]);
    } catch (err) {
      if (needsQueue(err)) {
        toQueue();
      } else if (err instanceof ApiError && err.status === 409 && Array.isArray(err.body.unavailable)) {
        const gone = new Set(err.body.unavailable as string[]);
        const labels = map.seats.filter((s) => gone.has(s.id)).map((s) => s.label);
        setMessage(`Someone just took ${labels.join(", ") || "that seat"}. Pick another.`);
        setSelected((sel) => sel.filter((id) => !gone.has(id)));
      } else {
        setMessage(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setBusy(false);
      void refresh();
    }
  }

  async function onPay() {
    if (!tokens || !hold) return;
    const bookingPass = loadPass(eventId);
    if (!bookingPass) return toQueue();
    setBusy(true);
    setMessage("");
    try {
      const order = await createOrder(
        eventId,
        hold.hold_id,
        orderKey(hold.hold_id), // same key on retry/reload -> same order
        `${window.location.origin}/order/`,
        tokens.accessToken,
        bookingPass.booking_pass,
      );
      if (order.checkout?.type === "redirect") {
        window.location.assign(order.checkout.url); // the provider's checkout page
        return;
      }
      setMessage("This payment method is not available yet.");
    } catch (err) {
      if (needsQueue(err)) {
        toQueue();
      } else {
        setMessage(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setBusy(false);
    }
  }

  if (!eventId) return <p>No event selected.</p>;
  if (!tokens) return <SignIn onSignedIn={setTokens} />;
  if (!map) return <p>{message || "Loading seats…"}</p>;

  const ev = map.event;
  const saleIn = countdown(ev.sale_starts_at, now);
  const holdLeft = hold ? countdown(hold.expires_at, now) : "";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">{ev.name}</h1>
          <p className="text-slate-600 dark:text-slate-400">
            {ev.venue} · {new Date(ev.starts_at).toLocaleString("en-IN")}
          </p>
        </div>
        <button
          className="text-sm text-slate-500 underline"
          onClick={() => {
            signOut();
            setTokens(null);
          }}
        >
          Sign out
        </button>
      </div>

      {saleIn ? (
        <p className="rounded bg-amber-100 px-3 py-2 text-amber-900">Sale opens in {saleIn}</p>
      ) : (
        <p className="text-sm text-slate-500">
          Up to {ev.per_buyer_limit} seats per buyer. Seats are held for 10 minutes while you pay.
        </p>
      )}

      {hold && (
        <div role="status" className="rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-100">
          {holdLeft ? (
            <>
              <strong>Held: {hold.seats.map((s) => s.label).join(", ")}</strong> ·{" "}
              {formatInr(hold.amount_paise)} · time left <span className="font-mono">{holdLeft}</span>
              {canPay(hold.expires_at, now) ? (
                <button
                  className="mt-3 block rounded bg-emerald-700 px-5 py-2 font-medium text-white disabled:opacity-40"
                  disabled={busy}
                  onClick={onPay}
                >
                  {busy ? "Starting payment…" : `Pay ${formatInr(hold.amount_paise)}`}
                </button>
              ) : (
                <p className="text-sm">
                  Less than {MIN_SECONDS_TO_PAY} seconds left: not enough time to pay. Hold the seats
                  again when the hold ends.
                </p>
              )}
            </>
          ) : (
            <strong>Your hold expired. The seats go back on sale.</strong>
          )}
        </div>
      )}

      {message && <p role="alert" className="rounded bg-red-100 px-3 py-2 text-red-800">{message}</p>}

      <SeatPicker
        seats={map.seats}
        selected={selected}
        onToggle={(seat) => setSelected((sel) => toggleSeat(sel, seat, ev.per_buyer_limit))}
      />

      <div className="sticky bottom-0 flex items-center justify-between gap-4 border-t border-slate-200 bg-slate-50/95 py-3 dark:border-slate-800 dark:bg-slate-950/95">
        <span>
          {selected.length} selected · {formatInr(total(selected, map.seats))}
        </span>
        <button
          className="rounded bg-indigo-600 px-5 py-2 font-medium text-white disabled:opacity-40"
          disabled={busy || selected.length === 0 || !!saleIn}
          onClick={onHold}
        >
          {busy ? "Holding…" : "Hold seats"}
        </button>
      </div>
    </div>
  );
}

export default function Page() {
  // useSearchParams needs a Suspense boundary in a static export.
  return (
    <Suspense fallback={<p>Loading…</p>}>
      <EventPage />
    </Suspense>
  );
}
