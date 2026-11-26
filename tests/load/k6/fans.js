// k6: a flash sale end to end, through the real edge (CloudFront -> WAF -> API Gateway / ALB).
// Day 10 Task 4, demo only. One virtual user (VU) = one fan with their own 1-hour test token.
//
//   k6 run -e BASE=https://<demo cloudfront> -e EVENT_ID=<id> -e TOKENS=/work/tokens.json \
//          -e VUS=5000 -e START_AT=<epoch s> fans.js           (run by the k6 Job, one per shard)
//
// Per fan, like the buyer site:
//   1. arrive at a random moment in [START_AT, START_AT + ARRIVAL_SECONDS)   (60 s by default)
//   2. POST /queue/{e}/join                       202
//   3. GET  /queue/{e}/serving every 10 s         until the sale opens (CloudFront-cached 5 s)
//   4. GET  /queue/{e}/position every ~15 s       until a number arrives (after the shuffle)
//   5. GET  /queue/{e}/serving every 10 s         until serving_up_to >= my position
//   6. POST /queue/{e}/admit                      -> booking pass
//   7. GET  /book/{e}/seats -> POST holds (2 random free seats; retry on 409) -> POST orders
//      -> POST mock-pay checkout (success)        the webhook marks the order paid
// A paused queue (the runner pauses it once every seat is sold) ends the wait: "sale over".
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';
import { SharedArray } from 'k6/data';

const BASE = __ENV.BASE;
const EVENT = __ENV.EVENT_ID;
const VUS = Number(__ENV.VUS || 1000);
const START_AT = Number(__ENV.START_AT || 0); // epoch seconds; 0 = now
const ARRIVAL_SECONDS = Number(__ENV.ARRIVAL_SECONDS || 60);
const MAX_WAIT_SECONDS = Number(__ENV.MAX_WAIT_SECONDS || 1500);
const SEATS_PER_BUYER = Number(__ENV.SEATS_PER_BUYER || 2);
const POSITION_POLL = Number(__ENV.POSITION_POLL_SECONDS || 15);

const tokens = new SharedArray('tokens', () => JSON.parse(open(__ENV.TOKENS || '/work/tokens.json')));

const joinOk = new Rate('fan_join_ok');
const admitted = new Counter('fan_admitted');
const saleOverWaiting = new Counter('fan_sale_over_while_waiting');
const timedOut = new Counter('fan_timed_out');
const soldOutSeen = new Counter('fan_sold_out_at_seat_map');
const holdConflicts = new Counter('hold_conflict_409');
const holdGaveUp = new Counter('fan_hold_gave_up');
const ordersPaid = new Counter('fan_paid');
const seatsPaid = new Counter('seats_paid');
const throttled = new Counter('http_429_or_503');
const http5xx = new Counter('http_5xx');
const waitTime = new Trend('fan_wait_seconds', false);

export const options = {
  scenarios: {
    fans: {
      executor: 'per-vu-iterations',
      vus: VUS,
      iterations: 1,
      maxDuration: `${Math.max(0, START_AT - Math.floor(Date.now() / 1000)) + ARRIVAL_SECONDS + MAX_WAIT_SECONDS + 120}s`,
      gracefulStop: '30s',
    },
  },
  // IPv4 (the WAF allow rule holds the NAT EIPs) and spread over CloudFront's addresses, so no
  // single destination gets near the NAT gateway's 55,000 connections per destination.
  dns: { ttl: '5m', select: 'random', policy: 'onlyIPv4' },
  discardResponseBodies: true, // bodies only where read (responseType: 'text' per request)
  summaryTrendStats: ['avg', 'p(50)', 'p(95)', 'p(99)', 'max'],
  thresholds: {
    fan_join_ok: ['rate>0.999'], // blueprint SLO: 99.9% of joins succeed
    'http_req_duration{stage:join}': ['p(95)<1000'],
    'http_req_duration{stage:hold}': ['p(95)<1000'],
  },
};

const text = { responseType: 'text' };

function auth(token, extra = {}) {
  return { headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...extra } };
}

function req(fn) {
  // 429/503 = throttled: back off and retry like a browser would.
  for (let attempt = 0; attempt < 6; attempt++) {
    const r = fn();
    if (r.status >= 500 && r.status !== 503) http5xx.add(1);
    if (r.status !== 429 && r.status !== 503) return r;
    throttled.add(1);
    sleep(Math.min(8, 0.5 * 2 ** attempt) + Math.random());
  }
  return fn();
}

function uuid4() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

const elapsed = (start) => (Date.now() - start) / 1000;

function serving() {
  const r = req(() => http.get(`${BASE}/queue/${EVENT}/serving`, { ...text, tags: { stage: 'serving' } }));
  return r.status === 200 ? r.json() : null;
}

function buy(token, pass) {
  const book = auth(token, { 'X-Booking-Pass': pass });
  for (let attempt = 0; attempt < 6; attempt++) {
    const m = req(() => http.get(`${BASE}/book/${EVENT}/seats`, { ...book, ...text, tags: { stage: 'seats' } }));
    if (m.status !== 200) return 'seat map failed';
    const free = m.json('seats').filter((s) => s.status === 'available');
    if (free.length === 0) {
      soldOutSeen.add(1);
      return 'sold out';
    }
    const pick = [];
    for (let i = 0; i < Math.min(SEATS_PER_BUYER, free.length); i++) {
      pick.push(free.splice(Math.floor(Math.random() * free.length), 1)[0].id);
    }
    const h = req(() =>
      http.post(`${BASE}/book/${EVENT}/holds`, JSON.stringify({ seat_ids: pick }), {
        ...book, ...text, tags: { stage: 'hold' },
      }),
    );
    if (h.status === 409) {
      holdConflicts.add(1); // someone else got there first (the seat map lags ~1 s)
      sleep(0.5 + Math.random());
      continue;
    }
    if (h.status !== 201) return `hold ${h.status}`;
    const o = req(() =>
      http.post(
        `${BASE}/book/${EVENT}/orders`,
        JSON.stringify({ hold_id: h.json('hold_id'), return_url: `${BASE}/orders/` }),
        { ...auth(token, { 'X-Booking-Pass': pass, 'Idempotency-Key': uuid4() }), ...text, tags: { stage: 'order' } },
      ),
    );
    if (o.status !== 201 || !o.json('checkout.url')) return `order ${o.status}`;
    const p = req(() =>
      http.post(`${o.json('checkout.url')}/pay`, { outcome: 'success' }, { redirects: 0, tags: { stage: 'pay' } }),
    );
    if (check(p, { 'mock pay accepted': (r) => r.status === 303 || r.status === 200 })) {
      ordersPaid.add(1);
      seatsPaid.add(pick.length);
      return 'paid';
    }
    return `pay ${p.status}`;
  }
  holdGaveUp.add(1);
  return 'gave up';
}

export default function () {
  const token = tokens[(__VU - 1) % tokens.length];
  const now = Date.now() / 1000;
  sleep(Math.max(0, START_AT - now) + Math.random() * ARRIVAL_SECONDS); // fans arrive over a minute
  const start = Date.now();

  const j = req(() => http.post(`${BASE}/queue/${EVENT}/join`, null, { ...auth(token), ...text, tags: { stage: 'join' } }));
  const ok = check(j, { 'join 202': (r) => r.status === 202 });
  joinOk.add(ok);
  if (!ok) return;
  const requestId = j.json('request_id');

  // Before the sale: only the shared, cached counter.
  let s = serving();
  while (elapsed(start) < MAX_WAIT_SECONDS && (!s || ['pre-queue', 'shuffling'].includes(s.status))) {
    sleep(10);
    s = serving();
  }

  let pos = null;
  sleep(Math.random() * POSITION_POLL); // spread 50k first position calls over the poll interval
  while (!pos && elapsed(start) < MAX_WAIT_SECONDS) {
    const p = req(() =>
      http.get(`${BASE}/queue/${EVENT}/position?req=${requestId}`, { ...auth(token), ...text, tags: { stage: 'position' } }),
    );
    if (p.status === 200 && p.json('position')) pos = p.json();
    else sleep(POSITION_POLL);
  }
  if (!pos) {
    timedOut.add(1);
    return;
  }

  let servingUpTo = pos.serving_up_to || 0;
  while (servingUpTo < pos.position && elapsed(start) < MAX_WAIT_SECONDS) {
    sleep(10);
    s = serving();
    if (s && s.status === 'paused') {
      saleOverWaiting.add(1); // every seat sold: the runner paused the queue
      return;
    }
    if (s) servingUpTo = s.serving_up_to;
  }
  if (servingUpTo < pos.position) {
    timedOut.add(1);
    return;
  }

  const a = req(() =>
    http.post(`${BASE}/queue/${EVENT}/admit`, JSON.stringify({ queue_token: pos.queue_token }), {
      ...auth(token), ...text, tags: { stage: 'admit' },
    }),
  );
  if (!check(a, { 'admit 200 + pass': (r) => r.status === 200 && !!r.json('booking_pass') })) return;
  admitted.add(1);
  waitTime.add(elapsed(start));
  buy(token, a.json('booking_pass'));
}

// One JSON line per shard; the runner adds the shards up (real VU count = sum of vus_max).
export function handleSummary(data) {
  const pick = {};
  for (const [name, m] of Object.entries(data.metrics)) {
    if (m.values) pick[name] = m.values;
  }
  return { stdout: `K6_SUMMARY ${JSON.stringify({ shard: __ENV.SHARD || '0', metrics: pick })}\n` };
}
