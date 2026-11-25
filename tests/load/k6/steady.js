// Steady background load for a canary rollout (Day 10 Task 2): a constant RATE requests/s to a
// real booking-API route through CloudFront, so the Rollout's CloudWatch analysis always has
// data (no traffic = analysis failure by design). Counts every status, so the run's summary
// gives the share of failed requests during the rollout.
//
//   k6 run -e BASE=https://<cloudfront> -e TOKEN_FILE=token.txt -e RATE=20 -e DURATION=45m steady.js
//
// The load generator's IP must be in the WAF load-test ALLOW rule for the window
// (-var=waf_load_test_enabled=true -var='waf_load_test_cidrs=["<ip>/32"]'), otherwise WAF's
// rate rule (2,000 per 5 min per IP) blocks it after a few minutes.
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';

const BASE = __ENV.BASE;
const TOKEN = open(__ENV.TOKEN_FILE || 'token.txt').trim();
const status5xx = new Counter('status_5xx');
const statusOther = new Counter('status_other_non_2xx');

export const options = {
  scenarios: {
    steady: {
      executor: 'constant-arrival-rate',
      rate: Number(__ENV.RATE || 20),
      timeUnit: '1s',
      duration: __ENV.DURATION || '45m',
      preAllocatedVUs: 20,
      maxVUs: 60,
    },
  },
  summaryTrendStats: ['avg', 'p(95)', 'p(99)', 'max'],
  // CloudFront also serves IPv6, but the WAF load-test IP set is IPv4: stay on IPv4, or WAF's
  // rate rule blocks the load after ~2,000 requests (seen on 25 Nov: 429 from 100 s in).
  dns: { ttl: '5m', select: 'first', policy: 'onlyIPv4' },
};

export default function () {
  const r = http.get(`${BASE}/me`, { headers: { Authorization: `Bearer ${TOKEN}` }, tags: { route: '/me' } });
  if (r.status >= 500) status5xx.add(1);
  else if (r.status >= 300) statusOther.add(1);
  check(r, { '200': (res) => res.status === 200 });
}
