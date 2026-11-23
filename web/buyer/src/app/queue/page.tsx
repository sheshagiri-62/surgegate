"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import SignIn from "@/components/SignIn";
import { loadTokens, signOut, type Tokens } from "@/lib/cognito";
import {
  admit,
  getPosition,
  getServing,
  joinQueue,
  loadJoin,
  loadPass,
  mayAskPosition,
  QueueError,
  saveJoin,
  savePass,
  view,
  waitText,
  type Position,
  type Serving,
} from "@/lib/queue";
import { countdown } from "@/lib/seatmap";

const SERVING_POLL_MS = 5000; // the counter is cached for 5 s at the edge (CloudFront, pending)
const POSITION_POLL_MS = 3000; // only until we have a number

function WaitingRoom() {
  const eventId = useSearchParams().get("id") ?? "";
  const router = useRouter();
  // Browser-only page (useSearchParams in a static export): sessionStorage is safe here.
  const [tokens, setTokens] = useState<Tokens | null>(() => loadTokens());
  const [serving, setServing] = useState<Serving | null>(null);
  const [position, setPosition] = useState<Position | null>(null);
  const [error, setError] = useState("");
  const [now, setNow] = useState(() => Date.now());
  const admitting = useRef(false);

  const goToSeats = useCallback(() => router.push(`/event/?id=${eventId}`), [router, eventId]);

  // Already holding a valid pass (e.g. came back from the seat page): straight to the seats.
  useEffect(() => {
    if (eventId && loadPass(eventId)) goToSeats();
  }, [eventId, goToSeats]);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  // The shared "now serving" counter: public, the same for everyone.
  useEffect(() => {
    if (!eventId) return;
    const poll = () =>
      getServing(eventId)
        .then(setServing)
        .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    const first = setTimeout(poll, 0);
    const t = setInterval(poll, SERVING_POLL_MS);
    return () => {
      clearTimeout(first);
      clearInterval(t);
    };
  }, [eventId]);

  // Join once (kept per event in this tab). Ask for our number only once the sale has started:
  // before the start nobody has one (places are shuffled at the start), and the shared /serving
  // status (polled above, cacheable) tells us when that happens. The k6 run on Day 6 showed that
  // asking every 5 s before the start was most of the load.
  const askPosition = mayAskPosition(serving);
  useEffect(() => {
    if (!eventId || !tokens || position?.position) return;
    let stop = false;
    const step = async () => {
      try {
        let requestId = loadJoin(eventId);
        if (!requestId) {
          requestId = (await joinQueue(eventId, tokens.accessToken)).request_id;
          saveJoin(eventId, requestId);
        }
        if (!askPosition) return; // pre-queue: wait for the shared counter to say "open"
        const p = await getPosition(eventId, tokens.accessToken, requestId);
        if (!stop) setPosition(p);
      } catch (e) {
        if (e instanceof QueueError && e.status === 401) {
          signOut();
          setTokens(null);
        } else if (!stop) setError(e instanceof Error ? e.message : String(e));
      }
    };
    const first = setTimeout(step, 0);
    const t = setInterval(step, POSITION_POLL_MS);
    return () => {
      stop = true;
      clearTimeout(first);
      clearInterval(t);
    };
  }, [eventId, tokens, position?.position, askPosition]);

  const v = view(position, serving, now);

  // Our turn: swap the queue token for a booking pass, then go to the seats.
  useEffect(() => {
    if (v.phase !== "your-turn" || !tokens || !position?.queue_token || admitting.current) return;
    admitting.current = true;
    admit(eventId, position.queue_token, tokens.accessToken)
      .then((pass) => {
        savePass(eventId, pass);
        goToSeats();
      })
      .catch((e) => {
        admitting.current = false;
        setError(e instanceof Error ? e.message : String(e));
      });
  }, [v.phase, tokens, position?.queue_token, eventId, goToSeats]);

  if (!eventId) return <p>No event selected.</p>;
  if (!tokens) return <SignIn onSignedIn={setTokens} />;

  return (
    <section className="mx-auto max-w-lg space-y-6 text-center">
      <h1 className="text-2xl font-semibold">Waiting room</h1>
      {v.phase === "before-sale" && (
        <>
          <p className="text-slate-600 dark:text-slate-400">The sale opens in</p>
          <p className="font-mono text-5xl" aria-live="polite">
            {countdown(serving?.sale_starts_at ?? "", now) || "now"}
          </p>
          <p className="text-sm text-slate-500">
            You&apos;re in. Everyone who arrives before the start gets a random place, so there&apos;s no need
            to refresh.
          </p>
        </>
      )}
      {v.phase === "placing" && <p aria-live="polite">Finding your place in line…</p>}
      {v.phase === "in-line" && (
        <>
          <p className="text-slate-600 dark:text-slate-400">You are number</p>
          <p className="font-mono text-6xl" aria-live="polite">
            {v.position.toLocaleString("en-IN")}
          </p>
          <p>
            {v.ahead.toLocaleString("en-IN")} {v.ahead === 1 ? "person" : "people"} ahead of you
            {v.paused ? " · the queue is paused for a moment" : waitText(v.etaSeconds) && ` · ${waitText(v.etaSeconds)}`}
          </p>
          <div className="h-2 overflow-hidden rounded bg-slate-200 dark:bg-slate-800" aria-hidden>
            <div
              className="h-full bg-indigo-600 transition-all"
              style={{ width: `${Math.min(100, (100 * (serving?.serving_up_to ?? 0)) / v.position)}%` }}
            />
          </div>
          <p className="text-sm text-slate-500">Keep this tab open. You&apos;ll be taken to the seats automatically.</p>
        </>
      )}
      {v.phase === "your-turn" && <p aria-live="assertive">It&apos;s your turn! Taking you to the seats…</p>}
      {error && (
        <p role="alert" className="rounded bg-red-100 px-3 py-2 text-red-800">
          {error}
        </p>
      )}
    </section>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<p>Loading…</p>}>
      <WaitingRoom />
    </Suspense>
  );
}
