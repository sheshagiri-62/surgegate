// k6: 1,000 virtual buyers join the waiting room, wait, and get admitted (plan: Day 6 Task 4).
//
//   k6 run -e QUEUE_API=https://<api> -e EVENT_ID=<event> -e TOKENS=.load_tokens.json queue.js
//
// Flow per virtual user (like the buyer page):
//   1. POST /queue/{event}/join                       (once)
//   2. GET  /queue/{event}/serving every 10 s         until the sale opens (no /position before)
//   3. GET  /queue/{event}/position every 5 s         until a number arrives (after the shuffle)
//   4. GET  /queue/{event}/serving every 10 s         the shared counter (blueprint: 1 poll / 10 s)
//   5. POST /queue/{event}/admit                      when serving_up_to >= position -> booking pass
//
// Arrivals spread over ARRIVAL_SECONDS, so the account's Lambda concurrency limit (10) is not
// the thing being measured. /book is not called: without CloudFront the ALB is not reachable
// from here (pending CloudFront verification), and the booking path has its own tests.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';
import { SharedArray } from 'k6/data';

const API = __ENV.QUEUE_API;
const EVENT = __ENV.EVENT_ID;
const VUS = Number(__ENV.VUS || 1000);
const ARRIVAL_SECONDS = Number(__ENV.ARRIVAL_SECONDS || 60);
const MAX_WAIT_SECONDS = Number(__ENV.MAX_WAIT_SECONDS || 480);

const tokens = new SharedArray('tokens', () => JSON.parse(open(__ENV.TOKENS || '.load_tokens.json')));

const joined = new Rate('queue_join_ok');
const admitted = new Counter('queue_admitted');
const notAdmitted = new Counter('queue_not_admitted');
const waitTime = new Trend('queue_wait_seconds', false);
const throttled = new Counter('http_429');

export const options = {
  scenarios: {
    fans: {
      executor: 'per-vu-iterations',
      vus: VUS,
      iterations: 1,
      maxDuration: `${ARRIVAL_SECONDS + MAX_WAIT_SECONDS + 60}s`,
    },
  },
  thresholds: {
    queue_join_ok: ['rate>0.999'], // blueprint SLO: 99.9% of joins succeed
    queue_admitted: [`count==${VUS}`], // everyone gets in
    http_req_failed: ['rate<0.01'],
  },
};

function auth(token) {
  return { headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } };
}

function withRetry(fn) {
  // 429/503 = throttled: back off and retry, like a real browser would.
  for (let attempt = 0; attempt < 6; attempt++) {
    const r = fn();
    if (r.status !== 429 && r.status !== 503) return r;
    throttled.add(1);
    sleep(Math.min(8, 0.5 * 2 ** attempt) + Math.random());
  }
  return fn();
}

export default function () {
  const token = tokens[(__VU - 1) % tokens.length];
  sleep(Math.random() * ARRIVAL_SECONDS); // fans arrive over a minute
  const start = Date.now();

  const j = withRetry(() => http.post(`${API}/queue/${EVENT}/join`, null, auth(token)));
  const ok = check(j, { 'join 202': (r) => r.status === 202 });
  joined.add(ok);
  if (!ok) return;
  const req = j.json('request_id');

  // Before the sale nobody has a number: watch only the shared (cacheable) counter until the
  // queue opens, then ask for our position. (Day 6 run: polling /position before the start was
  // most of the load.)
  while ((Date.now() - start) / 1000 < MAX_WAIT_SECONDS) {
    const s = withRetry(() => http.get(`${API}/queue/${EVENT}/serving`));
    if (s.status === 200 && !['pre-queue', 'shuffling'].includes(s.json('status'))) break;
    sleep(10);
  }

  let pos = null;
  while (!pos && (Date.now() - start) / 1000 < MAX_WAIT_SECONDS) {
    const p = withRetry(() => http.get(`${API}/queue/${EVENT}/position?req=${req}`, auth(token)));
    if (p.status === 200 && p.json('position')) pos = p.json();
    else sleep(5);
  }
  if (!pos) {
    notAdmitted.add(1);
    return;
  }

  let serving = pos.serving_up_to;
  while (serving < pos.position && (Date.now() - start) / 1000 < MAX_WAIT_SECONDS) {
    sleep(10);
    const s = withRetry(() => http.get(`${API}/queue/${EVENT}/serving`));
    if (s.status === 200) serving = s.json('serving_up_to');
  }
  if (serving < pos.position) {
    notAdmitted.add(1);
    return;
  }

  const a = withRetry(() =>
    http.post(`${API}/queue/${EVENT}/admit`, JSON.stringify({ queue_token: pos.queue_token }), auth(token)),
  );
  if (check(a, { 'admit 200 + pass': (r) => r.status === 200 && !!r.json('booking_pass') })) {
    admitted.add(1);
    waitTime.add((Date.now() - start) / 1000);
  } else {
    notAdmitted.add(1);
  }
}
