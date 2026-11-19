# SurgeGate — Project Blueprint & System Design

Nov 19, 2026 · @sheshagiri

## In one paragraph

SurgeGate is a ticketing platform built to survive flash sales: when tens of thousands of people arrive at once for a concert, a college fest or an admission round, it puts them in a fair virtual queue, admits only as many as the booking system can serve, holds seats for 10 minutes while they pay, and never sells the same seat twice. It runs on AWS (CloudFront, WAF, API Gateway, Lambda, DynamoDB, EKS, RDS, ElastiCache, SQS, Step Functions, EventBridge, Kinesis), built with Terraform, GitHub Actions and Argo CD. The panel demo: 50,000 simulated fans hit a sale, the site stays up, bots are blocked, and one Availability Zone is switched off mid-sale without losing an order.

**Pitch:** "The sale that BookMyShow couldn't handle, built so it can't crash."

## The problem

When demand arrives in one minute instead of one day, ordinary web apps fall over, and the fans who waited longest often lose.

**Evidence.**

- BookMyShow crashed just before Coldplay's Mumbai tickets went on sale after more than 13 million fans joined its online queue ([Free Press Journal](https://www.freepressjournal.in/mumbai/coldplay-india-tour-2025-bookmyshow-crashes-as-13-million-fans-rush-for-tickets-to-mumbai-concerts)).
- The same site had broken down before the 2023 Cricket World Cup ticket sale ([Free Press Journal](https://www.freepressjournal.in/business/bookmyshow-does-a-ticketmaster-repeats-2023-world-cup-fiasco-as-website-crashes-before-sale-of-coldplays-mumbai-2025-concert-tickets)).
- Its CEO later said the company was underprepared for the bots ([Business Today](https://www.businesstoday.in/amp/india/story/we-were-underprepared-for-the-bots-bookmyshow-ceo-on-coldplay-ticketing-row-462362-2025-01-29)); fans also complained of tickets appearing on resale sites at high prices ([NBC News](https://www.nbcnews.com/news/world/ticketing-platform-fire-scalping-coldplay-tickets-rcna173221)).

**Why it keeps happening.** Four things go wrong at the same moment:

1. **Thundering herd.** Every visitor hits the database at the same second; connection pools run out and the whole site returns errors, even for people who were already paying.
2. **Overselling and lost seats.** Two people grab the same seat, or a seat stays locked by someone who left.
3. **Unfairness.** Whoever refreshes fastest, or runs a bot, wins; people who joined early lose their place after a crash.
4. **No visibility.** Organisers cannot see how many are waiting, how fast the queue is moving, or whether the system is healthy.

**Problem statement.** *Event organisers, colleges and small ticketing businesses need a way to sell scarce seats to a sudden crowd that stays online, sells each seat exactly once, and treats every real fan fairly — without paying for a huge always-on server fleet.*

## Users and scope

Three kinds of people use SurgeGate; the MVP serves all three for one kind of sale (reserved seats, fixed price) and leaves everything else for later.

| User | Who they are | What they need |
| --- | --- | --- |
| Buyer (fan, student) | Opens the sale link on a phone at 12:00 sharp | A fair place in line, a clear wait time, a seat that is really theirs once chosen, a ticket by email |
| Organiser | College fest committee, small event company, admissions office | Create an event and seat map, set the sale time and per-person limit, watch the sale live, export attendees |
| Platform operator (you) | Runs SurgeGate | Know the system is healthy, scale it, roll back a bad release, see cost per event |

**In the MVP**

- Multi-tenant: many organisers, each sees only their own events.
- Reserved-seat events with up to 3 price zones and a per-buyer ticket limit.
- Virtual waiting room that opens 15 minutes before the sale; fair ordering; controlled admission rate that slows down automatically when the booking API struggles.
- Seat selection with a 10-minute hold, payment through Razorpay test mode, QR ticket by email.
- Bot defences: rate limits, challenge on joining the queue, one queue place per verified account.
- Organiser live dashboard: waiting, admitted, sold, revenue, admission rate.
- Full AWS infrastructure in Terraform, CI/CD, monitoring, load test results, AZ-failure and rollback demos.

**Out of scope (and why)**

- Real money and real payouts: test-mode payments only; no legal or tax handling.
- General admission (standing) tickets, transfers, resale and refunds: different data model; not needed to prove the system design.
- Native mobile apps: a responsive web app is enough for the demo.
- Multi-region active-active: one region, two Availability Zones; cross-region is a documented v2.

**v2 ideas** — resale with price caps, a waiting-room-only product other ticket sites can put in front of their own site, multi-region failover, Azure status page during an AWS outage.

## Features and user journeys

Twenty MVP features, grouped by who uses them; each one maps to a system-design problem explained later.

| # | Feature | User | What it does |
| --- | --- | --- | --- |
| 1 | Sign-up and login | All | Email + OTP login (Cognito); organiser and buyer roles |
| 2 | Organiser workspace | Organiser | Each organiser is a tenant; sees only their events |
| 3 | Create event | Organiser | Name, venue, date, sale start time, per-buyer limit |
| 4 | Seat map builder | Organiser | Sections, rows, seats, up to 3 price zones (uploaded as CSV) |
| 5 | Event page | Buyer | Public page with countdown to the sale, cached at the edge |
| 6 | Pre-queue | Buyer | Waiting room opens 15 min early; everyone who arrives before the start gets a random order (no advantage for refreshing first) |
| 7 | Live queue | Buyer | After the start, arrivals join at the back; page shows position and estimated wait |
| 8 | Controlled admission | System | Lets in a set number of buyers per minute so the booking app is never overloaded |
| 9 | Bot defence | System | WAF rate limits, a challenge before joining, one queue place per verified account |
| 10 | Seat selection | Buyer | Live seat map; taken seats greyed out within seconds |
| 11 | 10-minute seat hold | Buyer | Chosen seats are reserved while paying; released automatically if time runs out |
| 12 | Checkout | Buyer | Razorpay test-mode payment; one order per idempotency key |
| 13 | Ticket delivery | Buyer | PDF ticket with QR code emailed; also in "My tickets" |
| 14 | Gate check-in | Organiser | Scan the QR code once; a second scan shows "already used" |
| 15 | Live sale dashboard | Organiser | Waiting, admitted, sold, revenue, admission rate, updated live over WebSocket |
| 16 | Admission control | Organiser | Pause the queue, change the admission rate, end the sale |
| 17 | Attendee export | Organiser | CSV of buyers and seats |
| 18 | Ops dashboards and alarms | Operator | SLOs, queue depth, error rate, latency, cost per event |
| 19 | Safe releases | Operator | Every change through CI/CD with automatic rollback |
| 20 | Backups and restore | Operator | Point-in-time recovery of orders and a tested restore |

**Buyer journey (sale day)**

1. Opens the event link at 11:50; sees a countdown and joins the waiting room after a quick challenge.
2. At 12:00 everyone already waiting is shuffled into a random order; the page shows "You are number 8,412 — about 14 minutes".
3. The page refreshes the position every few seconds without loading the booking servers.
4. When admitted, the buyer gets a 10-minute pass to the booking pages and picks two seats.
5. The seats turn grey for everyone else; a 10-minute timer starts.
6. Pays in Razorpay test mode; within seconds the order is confirmed and the ticket email arrives.
7. If payment fails or the timer runs out, the seats go back on sale and the buyer can retry while the pass is valid.

**Organiser journey**

1. Signs up, creates the event, uploads the seat map, sets sale time and limit (about 10 minutes).
2. Shares the event link.
3. On sale day watches the live dashboard; pauses the queue if the payment provider is slow.
4. After the sale exports attendees and scans tickets at the gate.

## Tools and tech stack

The stack reuses the languages you already know (Python, TypeScript) so the 12 weeks go into AWS, Terraform and system design, not into learning a new framework.

| Layer | Choice | Why this one |
| --- | --- | --- |
| Buyer frontend | Next.js + TypeScript + Tailwind, built as static files on S3 + CloudFront | The pages are dynamic in the browser (they call the APIs for queue position, seats and payment) but load from the CloudFront cache, so 50,000 page loads at 12:00 never touch a server |
| Organiser dashboard | Next.js server-side rendering (SSR) on EKS | Low traffic, needs login and fresh data on every load |
| Live updates | API Gateway WebSocket API | Pushes sale numbers to the dashboard and seat changes to the seat map |
| Waiting-room API | Python on AWS Lambda behind API Gateway | Spiky traffic, pay per request, scales to thousands of requests per second without servers |
| Booking API | Python FastAPI in Docker on Amazon EKS (managed node group + Karpenter), packaged with Helm | Steady traffic and database connections; EKS is what AWS DevOps job descriptions ask for; the cluster is built by Terraform only for work sessions and the demo |
| Background jobs | SQS + Lambda; Step Functions for the 10-minute hold | Job queues: each message handled once by one worker, with retries and dead-letter queues |
| Sale events stream | EventBridge custom bus + Kinesis Data Streams stream sale-events (partition key = event ID), published by the booking API and queue Lambdas | One event per join, admission, hold and sale; several consumer groups (live dashboard, analytics to S3, audit) read and replay the same ordered stream |
| Main database | Amazon RDS PostgreSQL, Multi-AZ | Seats and orders need transactions and row locks so a seat is sold once |
| Queue state | Amazon DynamoDB | Millions of small writes with predictable latency; conditional writes and TTL |
| Cache | Amazon ElastiCache (Redis) | Seat-map cache and per-user rate limits |
| Files and email | S3 (tickets, seat maps), SES (ticket emails) | Durable storage with lifecycle rules; transactional email |
| Payments | Razorpay test mode (webhooks) | Indian payment flow without real money |
| Identity | Amazon Cognito | Sign-up, OTP, JWTs with a tenant claim |
| Edge and security | Route 53, ACM, CloudFront, AWS WAF (rate rules, bot control), KMS, Secrets Manager, GuardDuty, Security Hub | Protection at the edge before traffic reaches the app |
| Infrastructure as code | Terraform (modules, S3 remote state, dev and prod environments) | Everything rebuilt or destroyed with one command |
| CI/CD and GitOps | GitHub Actions with OIDC to AWS, ECR image scanning, Trivy, Helm, Argo CD, Argo Rollouts | No stored cloud keys; images blocked on critical vulnerabilities; canary releases with automatic rollback |
| Observability | CloudWatch logs, metrics, alarms, dashboards, Container Insights for EKS; AWS X-Ray via OpenTelemetry | Traces a buyer's request across Lambda, EKS and RDS |
| Testing | pytest, Playwright, k6 load tests, AWS Fault Injection Service | Proof with numbers: 50,000 virtual users, an AZ failure test |
| Cost | AWS Budgets, Cost Explorer, cost allocation tags | Cost per event and alerts before overspend |
| Azure (secondary) | Azure Static Web Apps status page; Blob Storage copy of nightly backups; GitHub Actions federated login to Azure | Status page stays up even if AWS is down; second-cloud backup copy |

## Architecture

SurgeGate is split into a cheap, massively scalable *front of house* (the edge and the waiting room) and a small, carefully protected *back of house* (booking, payments, database); the waiting room is the valve between them.

&#91;embedded content: SurgeGate architecture · front of house, two-AZ back of house, async workers\]

Only buyers holding a valid booking pass reach the VPC; everyone else is served by CloudFront and the serverless queue, so the crowd's size never reaches the database.

| Component | Runs on | Responsibility |
| --- | --- | --- |
| Edge | Route 53, ACM, CloudFront, WAF | Serves the static buyer site, caches the queue counter, blocks abusive traffic, checks the booking pass on `/book/*` |
| Waiting room | API Gateway, Lambda, SQS, DynamoDB, EventBridge Scheduler | Takes joins, assigns fair positions, moves the "now serving" counter, issues booking passes |
| Booking API | Amazon EKS (managed node group in 2 AZs, Karpenter) behind an ALB via the AWS Load Balancer Controller | Seat map, holds, checkout, orders |
| Organiser dashboard | Next.js SSR on the same EKS cluster | Event setup, live sale view, queue controls, exports |
| Live updates | API Gateway WebSocket API + Lambda | Pushes dashboard numbers and seat changes to browsers |
| Sale events stream | EventBridge bus + Kinesis Data Streams + Lambda consumers | Carries joined, admitted, held and sold events to the dashboard, analytics and audit |
| Seat hold timer | Step Functions | Releases unpaid seats after 10 minutes |
| Payment intake | ALB route + SQS + order worker | Verifies Razorpay webhooks, confirms orders exactly once |
| Ticket worker | SQS + Lambda + S3 + SES | Generates PDF/QR tickets and emails them |
| Data | RDS PostgreSQL Multi-AZ, ElastiCache Redis, DynamoDB, S3 | Orders and seats (source of truth), cache and rate limits, queue state, files |
| Identity | Cognito | Buyer and organiser accounts, JWTs with role and tenant |
| Operations | CloudWatch with Container Insights, X-Ray, Budgets, AWS Backup, GuardDuty, Security Hub | Watching, alerting, restoring, auditing |
| Delivery | Terraform, GitHub Actions (OIDC), ECR, Helm, Argo CD | Builds, scans and deploys everything |
| Azure | Static Web Apps, Blob Storage | Status page and second-cloud backup copy |

## System design deep dive

The hard part of SurgeGate is not the database — at a safe admission rate it handles a few writes a second — it is absorbing the crowd at the edge and letting it through at a pace the database can take.

### Requirements

| Type | Requirement | Target (to verify in load tests) |
| --- | --- | --- |
| Correctness | No seat is ever sold twice | 0, enforced by the database |
| Correctness | A paid order is never lost or confirmed twice | 0 duplicates, 0 lost |
| Fairness | Arrivals before the sale start are randomly ordered; after it, first come first served | Shuffle verified in logs |
| Availability | Joining the queue works during a sale | 99.9% of join requests succeed |
| Latency | Booking pages for admitted buyers | p95 under 500 ms |
| Freshness | A buyer's position on screen | Updated within 10 s |
| Holds | Unpaid seats return to sale | Within 10 min + 30 s |
| Resilience | One Availability Zone fails mid-sale | Sale continues, no lost orders |
| Cost | No sale running | Close to zero compute cost |

### Capacity estimate (demo scenario)

Assumptions, not measurements: 5,000 seats, 50,000 fans arriving within 5 minutes of 12:00, 2 tickets per buyer, a 4-minute booking session, the booking app sized for 500 shoppers at once.

| Quantity | Working | Result |
| --- | --- | --- |
| Join rate | 50,000 ÷ 300 s, with a 5× peak | ≈ 170/s average, ≈ 850/s peak |
| Position polls | 50,000 waiting × 1 poll per 10 s | ≈ 5,000 requests/s |
| Admission rate | 500 shoppers ÷ 4 min | ≈ 125 buyers per minute |
| Buyers needed to sell out | 5,000 seats ÷ 2 | ≈ 2,500 buyers |
| Time to sell out | 2,500 ÷ 125 per min | ≈ 20 minutes |
| Database writes | 125 buyers/min × about 5 writes each | ≈ 10 writes/s |

Two design consequences: the 5,000 polls per second must never reach a server (cache them at CloudFront), and the other 47,500 fans must be told "sold out" quickly, so the queue stops when stock reaches zero.

### The waiting room

&#91;embedded content: Waiting room flow · join once, poll a cached counter, enter with a pass\]

The only thing that grows with the crowd is cached polling; the booking pages see just the buyers the scheduler has let in.

1. **Join.** The buyer passes a WAF challenge and signs in; `POST /queue/{event}/join` puts a join request on an SQS queue and answers 202 at once, so a burst of joins never waits on a database.
2. **Sequence.** A sequencer Lambda reads joins in batches and gives out positions with one DynamoDB update per batch (not per person), which avoids a single hot counter. A conditional write allows one place per account.
3. **Shuffle at start.** Everyone who joined before 12:00 is assigned a random order when the sale opens, so refreshing early gives no advantage. Later arrivals go to the back in order.
4. **Signed position.** The buyer receives a signed queue token holding their position; refreshing the page keeps the same place.
5. **Cached counter.** Every waiting browser polls `GET /queue/{event}/serving`, which returns one number, "now serving up to N", identical for all. CloudFront caches it for 5 seconds, so 5,000 polls a second become a handful of origin calls.
6. **Admission valve.** Every minute a scheduled Lambda raises N by the admission rate set by the organiser (125 per minute in the scenario). Pausing the queue sets the rate to zero.
7. **Booking pass.** When the buyer's position is ≤ N, the browser swaps its queue token for a 15-minute booking pass bound to that user and event. A CloudFront Function checks the pass on every `/book/*` request before it reaches the app; no pass, back to the queue.

### Seat inventory: never sell a seat twice

PostgreSQL is the single source of truth for seats. A hold is one atomic statement that only succeeds for seats still available:

```sql
UPDATE seats
SET status = 'held', hold_id = :hold, held_until = now() + interval '10 minutes'
WHERE event_id = :event AND id = ANY(:seat_ids) AND status = 'available'
RETURNING id;
```

If fewer rows come back than were asked for, the transaction rolls back and the buyer sees "someone just took that seat". The per-buyer limit is checked in the same transaction. A unique constraint on `order_items(seat_id)` is the second safety net. The seat map shown to buyers is read from Redis and may lag up to 2 seconds; that is acceptable because only the write above decides who gets a seat.

### Holds and expiry

Each hold starts a Step Functions execution: wait 10 minutes, then release the seats *only if* they are still held by that same hold. A paid order changes them to `sold` first, so the release does nothing. Edge case to handle and demo: a payment succeeds at 10:01 after the release — if the seats are still free they are re-held and confirmed; otherwise the payment is refunded (test mode) and the buyer is told.

### Payments and idempotency

1. The browser creates an order with an idempotency key (a UUID); a unique constraint means a double click creates one order.
2. A Razorpay order is created and the buyer pays in test mode.
3. Razorpay's webhook arrives at `/webhooks/razorpay`; the signature is verified and the event goes onto SQS.
4. The order worker confirms the order in one transaction, keyed on Razorpay's payment ID, so a repeated webhook changes nothing.
5. Confirmation puts a message on the ticket queue; a Lambda builds the PDF and QR code, stores it in S3 and emails it with SES.

### Bot and abuse defence

- WAF rate-based rules per IP on joins and booking calls; AWS managed bot-control rules on `/queue/*`; a challenge before joining.
- A queue place needs a verified Cognito account; one place per account per event.
- Queue tokens and booking passes are signed and bound to the user, so they cannot be forged or shared.
- Per-buyer ticket limit enforced in the database, not only in the browser.

### Data model

| Store | Table / item | Key | Main fields |
| --- | --- | --- | --- |
| DynamoDB | Queue state | `EVENT#id` | serving\_up\_to, next\_position, admission\_rate, status (pre-queue/open/paused/sold out) |
| DynamoDB | Queue entry | `EVENT#id` + `USER#id` | position, request\_id, joined\_at, admitted\_at, expiry (TTL) |
| PostgreSQL | tenants, organiser\_users | id | name, plan; email, role, tenant\_id |
| PostgreSQL | events | id, tenant\_id | venue, starts\_at, sale\_starts\_at, per\_buyer\_limit, status |
| PostgreSQL | seats | id, event\_id | label, zone, price, status (available/held/sold), hold\_id, held\_until |
| PostgreSQL | orders, order\_items | id; unique idempotency\_key; unique seat\_id | buyer\_id, status, amount; seat\_id, price |
| PostgreSQL | payments, tickets | provider\_payment\_id unique; order\_item\_id | status, raw event; qr\_code, used\_at |
| Redis | seat map cache, rate limits | `seatmap:{event}`, `rl:{user}` | seat statuses, counters with expiry |

### Main APIs

| Method and path | Purpose | Served by |
| --- | --- | --- |
| `POST /queue/{event}/join` | Join the waiting room | API Gateway + Lambda |
| `GET /queue/{event}/position?req=` | Get your signed position | API Gateway + Lambda |
| `GET /queue/{event}/serving` | Current "now serving" number (cached 5 s) | CloudFront → API Gateway |
| `POST /queue/{event}/admit` | Swap queue token for a booking pass | API Gateway + Lambda |
| `GET /book/{event}/seats` | Seat map | Booking API (Redis) |
| `POST /book/{event}/holds` | Hold seats | Booking API (PostgreSQL) |
| `POST /book/orders` | Create order (idempotency key) | Booking API |
| `POST /webhooks/razorpay` | Payment result | Booking API → SQS |
| `GET /me/tickets` | My tickets | Booking API |
| `POST /org/events`, `PUT /org/events/{id}/seats` | Create event, upload seat map | Booking API (organiser role) |
| `PATCH /org/events/{id}/queue` | Pause, resume, change admission rate | Booking API → DynamoDB |
| `GET /org/events/{id}/live` | Live sale numbers | Booking API |
| `POST /org/checkin` | Scan a ticket at the gate | Booking API |

### What fails, and what happens

| Failure | What the buyer sees | Design response |
| --- | --- | --- |
| 10× more fans than expected | Longer wait, site stays up | Joins buffered in SQS; polls served from cache; admission rate unchanged |
| Booking API slow or erroring | Queue pauses briefly | Alarm on p95 latency; organiser or automation lowers the admission rate |
| One AZ goes down | Nothing, or one retry | ALB and EKS nodes in two AZs; RDS Multi-AZ fails over; Lambda, SQS and DynamoDB are regional |
| Redis lost | Seat map loads a bit slower | Cache only; reads fall back to PostgreSQL |
| Duplicate or late payment webhook | Nothing | Idempotent on payment ID; late-payment rule above |
| Bad release | Nothing | Argo Rollouts canary aborts and rolls back; Lambda alias moves back |
| Ticket email fails | Ticket arrives a little later | SQS retries, then a dead-letter queue and an alarm; ticket always in "My tickets" |
| Bot flood | Real fans unaffected | WAF rate rules, bot control, challenge, account-bound tokens |

### How it scales

- **Reads at the edge:** static pages and the serving counter come from CloudFront, so most traffic never reaches AWS compute.
- **Writes through queues:** joins, payments and ticket jobs go through SQS, which smooths bursts into a steady flow.
- **A valve in front of the database:** the admission rate, not the crowd size, sets the load on RDS.
- **Elastic compute:** Lambda scales with joins; EKS pods scale with the Horizontal Pod Autoscaler and nodes with Karpenter; both scale back to a minimum after the sale.

### Sudden spikes: pre-scaling and backpressure

Autoscaling reacts after load arrives, which is too late for a crowd that lands at exactly 12:00, so SurgeGate scales *before* the sale and slows the queue *during* it.

1. **Pre-scale 15 minutes before the sale.** A scheduled job raises the booking API to its sale size (more pods, extra nodes through Karpenter), sets Lambda provisioned concurrency on the queue functions, and checks RDS and Redis are at their sale size.
2. **Absorb at the edge.** CloudFront serves the buyer pages and the cached counter; WAF drops floods; API Gateway → SQS accepts every join instantly.
3. **Admit at a fixed pace.** The admission rate, not the crowd size, sets the load on EKS and RDS.
4. **Backpressure.** If booking p95 latency passes 500 ms or errors rise, a Lambda lowers the admission rate; when it recovers, the rate climbs back. The queue gets longer instead of the site falling over.
5. **Scale down after.** When the event sells out or the sale ends, provisioned concurrency is removed and nodes drain back to the minimum.

### Key design decisions

| Decision | Choice | Why | Alternative and why not |
| --- | --- | --- | --- |
| Container platform for booking | Amazon EKS | Industry-standard for AWS DevOps roles; Helm and Argo CD carry over | ECS Fargate is simpler and has no control-plane charge, but adds less to your resume |
| Job queues | SQS | Each job processed once, retries and dead-letter queues, free at idle | Kafka (MSK) is a stream, not a job queue, and bills hourly; already on your resume via LabForge |
| Event fan-out | EventBridge + Kinesis Data Streams | Several consumers read and replay the same events, ordered per event (partition key = event ID); EventBridge also routes events to AWS targets such as alerts and the archive | Amazon MSK (Kafka) is blocked on this Free-plan account and bills by the hour; Kafka is already shown in LabForge (ADR 002) |
| Buyer frontend | Static files + API calls | Survives 50,000 page loads from cache | Server rendering would put every page load on EKS at the worst moment |
| Organiser frontend | Server-rendered (SSR) | Low traffic, needs fresh logged-in data | Static would work but loads data after the page appears |
| Seat locking | PostgreSQL conditional update | Strong consistency where it matters | Redis locks are fast but add a second source of truth |

### Sale events with EventBridge and Kinesis

Every state change in a sale becomes one record on the `sale-events` Kinesis stream, keyed by event ID so all records for one event stay in order on one shard. The same events also go on an EventBridge bus for AWS-side routing (alarms, archive).

| Producer | Messages |
| --- | --- |
| Queue Lambdas | `joined`, `admitted`, `pass_expired` |
| Booking API (EKS) | `seat_held`, `hold_released`, `order_paid`, `ticket_issued` |

| Consumer group | Runs on | Does |
| --- | --- | --- |
| `live-dashboard` | Lambda (Kinesis event source) | Updates live counters and pushes them over the WebSocket API to organisers |
| `analytics` | Lambda | Writes events to S3 for Athena queries (sales per minute, drop-off from queue to purchase) |
| `audit` | Lambda | Keeps a tamper-evident record of who was admitted and when, for fairness checks |

Rules: every record carries a unique message ID; Lambda consumers process in order per shard, checkpoint by sequence number and ignore duplicates by message ID; failed batches go to an SQS on-failure destination. Jobs that must run exactly once per item (joins, payments, tickets) stay on SQS.

## Design Q&A

**Why does the booking API run on EKS and not ECS Fargate?** Both run the same Docker container. EKS is the orchestrator AWS DevOps and platform job descriptions ask for, and your Helm and Argo CD skills from LabForge carry straight over, so the new learning is the AWS side: IAM roles for pods, the AWS Load Balancer Controller, Karpenter. The cost is the EKS control-plane charge, so Terraform creates the cluster only for work sessions and the demo.

**What happens when a huge load arrives suddenly?** No single service takes the hit. CloudFront serves the pages and the cached queue counter, WAF drops bots, API Gateway and SQS accept every join instantly, and the admission valve lets only a fixed number of buyers per minute reach EKS and the database. Because autoscaling reacts too late for a 12:00 spike, the system pre-scales 15 minutes before the sale and lowers the admission rate automatically if the booking API slows down.

**Why use both SQS and Kinesis?** They solve different problems. SQS is a job queue: one worker handles each join, payment or ticket, with retries and a dead-letter queue. Kinesis is an event stream: many consumers read and replay the same ordered events, which suits the live dashboard, analytics and audit.

**Why not use the stream for everything?** A stream has no per-message retry or dead-letter queue built in, and Kinesis bills by the hour even when idle. Using it for jobs would add work and cost without benefit.

**The buyer site is "static" — how is it dynamic?** Static describes how the files are delivered, not what the page does. The HTML and JavaScript come from the CloudFront cache, then the page calls the APIs for queue position, seats and payment and updates every few seconds. Server-rendering every buyer page would put 50,000 page loads on EKS at the worst moment. The organiser dashboard, which has little traffic, is server-rendered.

**Why not just make the database bigger?** A crowd of any size can outgrow any database at the moment the sale opens. Shaping the crowd with the queue means the database load depends on the admission rate you choose, which you can test and guarantee.

## Security, operations, reliability and cost

### Security

- **Identity:** Cognito for buyers and organisers; JWTs carry role and tenant; the API rejects any organiser request for another tenant's event, with automated cross-tenant tests in CI.
- **Network:** ALB in public subnets; EKS nodes, RDS and Redis in private subnets; security groups allow only the next hop; S3 and DynamoDB via gateway endpoints.
- **Secrets and keys:** Razorpay keys and the token-signing key in Secrets Manager; data encrypted with KMS; no secrets in code or images.
- **Pipeline:** GitHub Actions assumes an AWS role through OIDC (no stored keys); ECR scan and Trivy block critical vulnerabilities.
- **Detection:** CloudTrail, GuardDuty and Security Hub on; WAF logs kept for the sale period.

### Observability and SLOs

| SLI | SLO during a sale |
| --- | --- |
| Successful queue joins | 99.9% |
| Booking API latency (admitted buyers) | p95 < 500 ms |
| Oversold seats | 0 |
| Paid orders confirmed within 60 s | 99% |
| Ticket email delivered within 5 min | 99% |

Alarms on SLO burn rate, queue depth and oldest-message age, dead-letter queues above zero, ECS task count, RDS CPU and connections, and budget thresholds. A CloudWatch "sale room" dashboard shows waiting, admitted, sold, error rate and latency side by side; X-Ray traces follow one buyer from CloudFront to RDS.

### Reliability and recovery

- **Two AZs** for the ALB, EKS nodes and RDS Multi-AZ; Lambda, SQS and DynamoDB are regional services.
- **Backups:** RDS automated backups with point-in-time recovery; DynamoDB point-in-time recovery; AWS Backup daily plan; a nightly copy to Azure Blob Storage.
- **Proof:** an AWS Fault Injection Service experiment cuts one AZ during a k6 load test; a restore drill rebuilds the orders database from a point in time and records the time taken (your measured RTO).
- **Releases:** Argo CD deploys with Argo Rollouts canaries that roll back automatically when error-rate checks fail; Lambda versions behind aliases.

### Cost

The idea is to pay for capacity only during work sessions and the demo; everything is Terraform, so the expensive parts are switched off when idle. Always-on hourly items are the risk: NAT gateway (about $0.056/hour in Mumbai, [CloudKeeper](https://www.cloudkeeper.com/insights/blog/aws-cloud-cost-optimization-nat-gateway)), ALB (about $0.0225/hour plus usage, [Spendark](https://spendark.com/blog/alb-vs-nlb-pricing/)), the EKS control plane (about $0.10/hour per cluster; verify on the EKS pricing page) and its nodes, RDS, ElastiCache and the WAF web ACL ($5/month plus $1 per rule, [AWS](https://aws.amazon.com/waf/pricing)).

- Target: under $50 of AWS spend over the project, plus Azure for Students credit ($100, no card, [Microsoft](https://azure.microsoft.com/en-in/free/students/)) for the Azure parts.
- Budgets alerts at $15, $30 and $45; tags `Project`, `Env`, `Component` on every resource for cost per component and per event.
- A `make down` that destroys the EKS cluster, compute and database layers between sessions (data kept as snapshots); full stack only for load tests and the demo.
- Open question: exact RDS and ElastiCache prices for ap-south-1 — check in the AWS Pricing Calculator before Week 1.

Kinesis Data Streams bills by the hour for each stream's capacity (check the Kinesis pricing page for ap-south-1), so Terraform creates the stream only during work sessions, load tests and the demo, like the EKS cluster. MSK was dropped because it is blocked on the Free plan (ADR 002).

## What it proves, and what comes next

SurgeGate fills the AWS gap on your resume: LabForge already proves Kubernetes, GitOps and Prometheus; this project proves AWS networking, managed services, Terraform at a real level, event-driven design and high-scale system design.

**Resume bullets to earn (numbers come from your own tests)**

- Built SurgeGate, a multi-tenant ticketing platform on AWS (CloudFront, WAF, API Gateway, Lambda, DynamoDB, EKS, RDS, ElastiCache, SQS, Step Functions, EventBridge, Kinesis) that served `<measured>` concurrent virtual users with zero oversold seats.
- Designed a fair virtual waiting room with edge-cached queue state and controlled admission, keeping booking p95 latency at `<measured>` ms under a `<measured>`× traffic spike.
- Provisioned all infrastructure with Terraform modules and deployed to EKS through GitHub Actions (OIDC), Helm and Argo CD, with automatic canary rollback, CloudWatch SLO alarms, and an AZ-failure test that lost no orders.

**Interview questions it prepares you for**

1. Design BookMyShow (or Ticketmaster) for a flash sale.
2. How do you guarantee a seat is never sold twice?
3. How do you serve 5,000 requests per second of polling cheaply?
4. How do you make payment webhooks idempotent?
5. What happens to your system if one Availability Zone fails?
6. Why Lambda for the queue but EKS for booking, and SQS for jobs but Kinesis for events?
7. How do you stop bots without hurting real fans?
8. How did you keep this under $50?

**Next step:** once you are happy with this blueprint, we turn it into the 12-week build plan: Terraform repo layout, week-by-week milestones, and the first week's tasks.

## Sources

- [Free Press Journal — BookMyShow crashes as 13 million fans join the Coldplay queue](https://www.freepressjournal.in/mumbai/coldplay-india-tour-2025-bookmyshow-crashes-as-13-million-fans-rush-for-tickets-to-mumbai-concerts)
- [Free Press Journal — repeat of the 2023 World Cup ticketing crash](https://www.freepressjournal.in/business/bookmyshow-does-a-ticketmaster-repeats-2023-world-cup-fiasco-as-website-crashes-before-sale-of-coldplays-mumbai-2025-concert-tickets)
- [Business Today — BookMyShow CEO on bots](https://www.businesstoday.in/amp/india/story/we-were-underprepared-for-the-bots-bookmyshow-ceo-on-coldplay-ticketing-row-462362-2025-01-29)
- [NBC News — scalping complaints](https://www.nbcnews.com/news/world/ticketing-platform-fire-scalping-coldplay-tickets-rcna173221)
- [AWS WAF pricing](https://aws.amazon.com/waf/pricing)
- [CloudKeeper — NAT gateway cost in Mumbai](https://www.cloudkeeper.com/insights/blog/aws-cloud-cost-optimization-nat-gateway)
- [Spendark — ALB pricing 2026](https://spendark.com/blog/alb-vs-nlb-pricing/)
- [Azure for Students](https://azure.microsoft.com/en-in/free/students/)
