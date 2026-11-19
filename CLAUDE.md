# SurgeGate — instructions for Claude Code

You are helping Sheshagiri build **SurgeGate**, a flash-sale ticketing platform with a fair virtual
waiting room, on AWS (EKS, Lambda, API Gateway, SQS, DynamoDB, RDS PostgreSQL, ElastiCache, Step
Functions, MSK, CloudFront, WAF), built with Terraform, GitHub Actions (OIDC), Helm and Argo CD.

Read these two files before any task; they are the source of truth:

- `docs/blueprint.md` — project blueprint and system design (what we build and why: features,
  architecture, data model, APIs, failure modes, scaling, security, cost).
- `docs/implementation-plan.md` — the day-by-day task list, milestones (M1–M6), repo layout,
  environments, testing strategy, risks.

Repo: https://github.com/sheshagiri-62/surgegate

Follow the implementation plan **phase by phase, day by day, one task at a time**, in the order
listed. Do not build anything the plan does not call for, and do not drop anything it does.

## Schedule: full scope in 12 days

The whole plan runs from **Thu 19 Nov to Mon 30 Nov 2026**, one plan-day per calendar day
(Day 1 = 19 Nov … Day 12 = 30 Nov), 10–12 hours a day. 1–3 Dec is overflow buffer only.
Work fast: generate complete files in one go, batch related changes, run tests as you go, and
avoid asking questions you can answer from the blueprint or plan. Still follow every safety rule.
If a day's tasks will not finish, say so early and list what moves to the next morning.

## Account facts (check these before creating resources)

- Region: `ap-south-1` (Mumbai). CloudFront certificates go in `us-east-1`.
- The AWS account is on the **Free plan**: about $140 credit, ends **22 Jan 2027** or when the
  credit runs out. Free-plan accounts are blocked from some expensive services. On Day 1, before
  building, check with me whether EKS, MSK Serverless and WAF are usable on this account.
- If an AWS call fails because the service is not available on the Free plan, **stop** and tell
  me. Do not look for workarounds; I will decide whether to upgrade to the Paid plan.
- Budget for the whole project: under $50. Budget alerts at $15 / $30 / $45.

## Safety rules (always)

1. **Ask before anything that costs money.** Before any `terraform apply`, `eksctl`, `aws ... create`
   or deploy that creates billable resources, show me: what will be created, the hourly items
   (EKS control plane, NAT gateway, ALB, RDS, ElastiCache, MSK, WAF), and how to tear it down.
   Wait for my "yes".
2. **Never commit secrets.** No AWS keys, Razorpay keys or tokens in code, `.tfvars` or Git history.
   Locally use the AWS CLI profile `surgegate` (IAM user `sheshagiri-admin`, short-term credentials
   from `aws login --profile surgegate`; never the root user, never long-term access keys). If AWS
   calls fail with expired credentials, ask me to run `aws login --profile surgegate` again.
   In CI use GitHub OIDC. Secrets live in Secrets Manager.
3. **Infrastructure only through Terraform.** No console changes except the one-time manual steps
   listed in the plan. Run `terraform fmt`, `validate` and `plan` before every apply; save the plan
   with `-out` and apply that file.
4. **Tags on everything:** `Project=surgegate`, `Env=<dev|demo|shared>`, `Component=<module>` via provider
   `default_tags`. `shared` is only for resources used by both environments (`infra/bootstrap`).
5. **End of every session:** remind me to run `make down`, and list anything still running that bills
   by the hour.
6. Never run destructive commands (`terraform destroy` on `demo`, deleting state, `git push --force`)
   without asking.

## How to work on each task

1. Say which task you are starting (week number + task text from the plan) and the plan for it in
   3–6 bullets.
2. Do the task: write code and Terraform, run commands, run tests.
3. When a command fails, **record the exact error message**, find the cause, fix it, and re-run until
   it works. Keep every error you hit, even small ones — they go in the report.
4. Verify it works (a command, a test, a URL, a screenshot description).
5. Commit on a branch with a conventional message (`infra:`, `feat:`, `fix:`, `docs:`, `ci:`), push,
   and open a pull request if CI exists for it.
6. **Write the task report** (next section), tick the task in `docs/progress/CHECKLIST.md`, then
   stop and give me a short summary in chat. Wait for me before starting the next task.

## Task report (required after every task)

Create `docs/progress/day-XX/task-YY-<short-slug>.md` by copying
`docs/progress/TEMPLATE.md` and filling every section. Write in plain, simple English so I can
explain it in an interview. Rules:

- **Commands:** the real commands you ran, in order, in code blocks.
- **Errors:** every error, with the exact message, the cause in one or two sentences, and the
  exact fix. If there were none, write "None".
- **How it works:** explain the concept as if to a beginner, then how it fits SurgeGate.
- **Interview notes:** 2–3 questions an interviewer could ask about this task, with short answers.
- Link the commit / pull request.

Also add one line per task to `docs/progress/README.md` (date, day, task, link to the report).

## End of each day

Write `docs/progress/day-XX/SUMMARY.md`: what was finished, what was not and why, all errors of
the day in one table, cost spent today (from Cost Explorer or an estimate), what is still running,
and what the next day starts with. Then remind me to run `make down`.

## End of each phase (milestones M1–M6)

Check the milestone's "done when" test from the plan, show me how to demo it, and write
`docs/progress/phase-N-milestone.md` with the result and screenshots I should take.

## Conventions

- Python 3.12, FastAPI, SQLAlchemy, Alembic, pytest, ruff.
- Next.js + TypeScript + Tailwind for `web/buyer` (static export) and `web/organiser` (SSR).
- Terraform modules in `infra/modules/`, environments in `infra/envs/dev` and `infra/envs/demo`,
  remote state in S3 with the native lock file.
- Repo layout exactly as in the implementation plan.
