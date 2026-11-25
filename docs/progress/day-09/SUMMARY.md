# Day 9 summary — planned for Fri 27 Nov, done Wed 25 Nov 2026

Same long session as Day 8 (dev up since 23 Nov, at your request). Day 9 was started early after
the M4 milestone, the buyer site on S3 and the Day 8 write-ups.

## Finished

| Task | PRs | Report |
| --- | --- | --- |
| 1. Demo environment: two NAT gateways, Multi-AZ RDS, Redis replica, Karpenter, 2+ nodes. **Code + plan only** (apply on Day 10, your call) | [#61](https://github.com/sheshagiri-62/surgegate/pull/61) | [task-01-demo-env](task-01-demo-env.md) |
| 2. WAF on CloudFront (rate rules, IP reputation, challenge on the page + join, Bot Control on `/queue/*`, common rules, load-test ALLOW rule off) + queue origin header | [#62](https://github.com/sheshagiri-62/surgegate/pull/62) [#63](https://github.com/sheshagiri-62/surgegate/pull/63) [#65](https://github.com/sheshagiri-62/surgegate/pull/65) | [task-02-waf](task-02-waf.md) |
| 3. Observability: JSON logs, OpenTelemetry → X-Ray (Transaction Search), Container Insights (demo only), sale-room dashboard | [#64](https://github.com/sheshagiri-62/surgegate/pull/64) [#66](https://github.com/sheshagiri-62/surgegate/pull/66) | [task-03-observability](task-03-observability.md) |
| 4. 14 SLO alarms → SNS email, 3 runbooks; budget fixed (usage before credits) | [#64](https://github.com/sheshagiri-62/surgegate/pull/64) [#65](https://github.com/sheshagiri-62/surgegate/pull/65) | [task-04-slo-alarms](task-04-slo-alarms.md) |

**Day 9 of the plan is complete**, except Task 1's apply, which moves to Day 10 by decision.

## Not finished / open items

- **Your Chrome check:** join on `/waiting/?id=…` with the test buyer in
  `chrome_test_login.txt` (scratchpad), and keep the tab open 7 minutes. Admissions on that event
  are paused so you stay in the queue.
- **M4 recording:** after the Day 11 UI polish (your call).
- **Join → dashboard at idle (~18 s)**, from the sequencer's first poll: re-measure under load.
- **No SQL spans** (the OTel SQLAlchemy instrumentation doesn't support 2.1 yet).
- **Gmail Spam / DMARC** for ticket emails: waits for a domain.
- **Audit consumer:** skipped (revisit after Day 10).

## All errors of the day

Full details are in each report.

| # | Task | Error (shortened) | Fix |
| --- | --- | --- | --- |
| 1 | 1 | `releases.hashicorp.com: read` / `could not query provider` | Copied dev's lock file; re-ran init |
| 2 | 1 | `Invalid count argument` (edge, `queue_api_domain != ""`) | `queue_api_enabled` boolean |
| 3 | 1 | `Module not installed` (dev) | `terraform init` |
| 4 | 1 | Pre-commit `check yaml … Failed` (Helm template) | Exclude `infra/modules/*/charts/*/templates` |
| 5 | 1, 2 | `GraphQL: No commits between main and …` | Follow-ons of failed hooks; committed after the fix |
| 6 | — | README merge conflict (#59 vs #61) | Merged main into the branch (no force push), kept both sides |
| 7 | 2 | tflint: WAF descriptions `does not match valid pattern` | Plain-text descriptions; version constraints |
| 8 | 2 | `waf_challenge_sdk_url` = `challenge.js` (no host) | No SDK URL for Bot Control COMMON → `ChallengePage` rule (approved, +$1/month) |
| 9 | 2 | Browser joins challenged for ~20 min | Closed by the fix in row 8 |
| 10 | 2 | `Permission … denied` (unapproved cost change / merge) | Asked you first |
| 11 | 2 | ruff `I001` ×3 | `ruff --fix` |
| 12 | 3 | `SQLAlchemyInstrumentor only instruments "sqlalchemy >= 1.0.0, < 2.1.0"` | Tried `skip_dep_check` |
| 13 | 3 | `ImportError: … requires that the Python 'greenlet' library is installed` | Dropped SQL instrumentation (would have crashed the pod) |
| 14 | 3 | `failed to connect to the docker API` | Unit tests locally; full suite in CI |
| 15 | 3 | `Inconsistent conditional result types` | Filtered `for` expressions |
| 16 | 3 | Plan: `ORIGIN_VERIFY_REQUIRED "true" -> "false"` | Not applied; built on #63 |
| 17 | 3 | X-Ray 0 traces (`Destination: XRay`) | Transaction Search (approved) |
| 18 | 3 | `Log groups starting with AWS/ are reserved for AWS.` | Import after X-Ray creates it |
| 19 | 3 | Plan: WAF immunity back to 1,800 s + destroy 4 log groups | Built on #65; log groups kept |
| 20 | 3 | `BatchGetTraces` empty (unindexed trace) | 1% indexing: 1,500 requests → 2 indexed traces |
| 21 | 4 | Runbook schedule name guessed | Grepped; fixed |
| 22 | 4 | Budget `ActualSpend 0.0` (credits included) | Imported; usage before credits |
| 23 | 4 | Import plan printed the alert email locally | Deleted the output; local apply first; `ignore_changes`; CI plan shows no changes |

## Cost

- Cost Explorer (usage before credits): **24 Nov $6.55**; 25 Nov isn't complete there yet.
- The budget now shows **$15.73 actual for November, forecast $23.92**, under the $45 alert and
  the $50 limit. **The $15 budget alert will email you; that's correct.**
- **Added today:**
  - WAF about $0.76/day;
  - Container Insights only during today's ~2 h in dev (now off in dev);
  - alarms about $0.07/day;
  - Transaction Search: cents.
- Credits cover all of it (net $0).

## Still running (bills by the hour)

Dev is **up** (no `make down` until you say so): EKS control plane + nodes, NAT gateway, internal
ALB, RDS, ElastiCache, the Kinesis shard, about **$0.35/h**. Plus WAF (~$0.76/day, prorated) and
the CloudWatch agent pods (no extra charge in dev now).

## Day 10 starts with

1. Pre-scaling 15 minutes before a sale + the backpressure Lambda (admission rate down when
   booking p95 > 500 ms).
2. Argo Rollouts canary for the booking API, with a deliberately broken release that must roll
   back by itself.
3. GuardDuty / Security Hub / CloudTrail; base-image upgrade; Trivy/ECR gate failing on HIGH.
4. **Last:** demo apply + k6 10k/50k. I'll show you the cost and the load-generator plan (with the
   WAF ALLOW rule) before applying.

**Reminder:** run `make down` when you're done (only when you say so).
