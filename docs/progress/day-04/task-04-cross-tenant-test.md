# Week 1 · Day 4 · Task 04 — Cross-tenant test: organiser A can never read or change organiser B's events

- **Date:** 2026-11-21 (evening of Day 3, ahead of schedule)
- **Phase / milestone:** Phase 2 (Booking core) → M2
- **Status:** Done
- **Commit / PR:** [#24](https://github.com/sheshagiri-62/surgegate/pull/24)

## 1. What the task was

Plan text: *"Cross-tenant test: organiser A can never read or change organiser B's events."*
Blueprint: "the API rejects any organiser request for another tenant's event, with automated
cross-tenant tests in CI".

## 2. What I did, step by step

1. **Route discovery from the app itself** (`tests/test_cross_tenant.py`). Every
   `/org/…/{event_id}` route and method is read from the OpenAPI schema, so routes added later are
   tested automatically.
2. **A recipe per route:** a *valid* request (correct body and content type), so that only the
   tenant check can stop it. `test_every_organiser_route_has_an_attack_recipe` **fails** when a new
   organiser route has no recipe.
3. **For every route**, organiser B calls it on organiser A's event:
   - the answer must be `404 {"detail": "event not found"}`;
   - it must be **identical to the answer for a random event ID**, so B can't probe whether an ID
     exists;
   - A's event row and all its seats must be **byte-identical** in the database before and after
     (`to_jsonb` snapshots);
   - finally the owner makes the same call successfully, which proves the recipe is valid.
4. **Lists:** three tenants with two events each; every tenant sees exactly its own two.
5. **Tenant smuggling:** `?tenant_id=<B>` in the query is ignored, and `tenant_id` in the body is
   refused (422).
6. **Database invariant:** every event belongs to an existing tenant.
7. **Mutation check:** I removed the tenant filter from `_own_event` and ran the tests. **3 failed**
   (`GET/PUT … as another tenant -> 200`). Then I restored the filter.

### Commands I ran

```bash
git checkout -b test/cross-tenant test/concurrency
python -m pytest -v tests/test_cross_tenant.py    # 1st: "4 passed, 1 skipped" (error 1)
python -m pytest -v tests/test_cross_tenant.py    # 6 passed
sed -i 's/…Event.tenant_id == org.tenant_id)/…)  # MUTATION/' app/routes/organiser.py
python -m pytest -q tests/test_cross_tenant.py tests/test_organiser.py   # 3 failed (expected)
git checkout -- app/routes/organiser.py
gh pr create … ; gh pr merge 24 --squash           # approved; CI 80 passed
```

### Files created or changed

| File | What it does |
| --- | --- |
| `services/booking-api/tests/test_cross_tenant.py` | Route-discovering cross-tenant tests |

## 3. How it works

A hand-written test only checks the routes someone remembered. This test asks the app for its own
list of organiser routes and attacks every one, so tenant isolation stays tested as the API grows.
It checks three things:
- **the answer:** 404, the same as for a missing event;
- **the effect:** the database is unchanged;
- **the test itself:** the owner can make the same call, so a broken recipe can't make the test
  pass for the wrong reason.

The mutation check shows the test really protects the rule: break the rule and the test goes red.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `4 passed, 1 skipped` (the per-route test was skipped, and the recipe test **passed vacuously**) | In FastAPI 0.165, `app.routes` holds `_IncludedRouter` wrappers rather than flat `APIRoute`s, so my filter found no routes | Discover routes from `app.openapi()["paths"]` instead, and **assert the list isn't empty**, so broken discovery fails loudly |

## 5. How I verified it works

| Check | Result |
| --- | --- |
| Local | 6 passed: recipe coverage, `GET /org/events/{event_id}`, `PUT /org/events/{event_id}/seats`, lists across 3 tenants, query/body smuggling, orphan check |
| Mutation (tenant filter removed) | 3 failed, as expected; filter restored |
| CI (#24) | 80 passed |
| Real RDS (pod run, see Task 3) | cross-tenant tests passed |
| Deployed API, real Cognito tokens (Day 3 Task 4) | organiser B → A's event: `404` on GET and PUT; list `[]` |

## 6. Cost impact

None.

## 7. Interview notes

- **Q:** How do you make sure a new endpoint doesn't break tenant isolation?
  **A:** The cross-tenant test discovers routes from the OpenAPI schema and fails if a new
  organiser route has no attack recipe. Every route is attacked by another tenant, and the database
  is compared before and after.
- **Q:** How do you know the test itself works?
  **A:** A mutation check: I deleted the tenant filter and the test went red (3 failures). Each
  recipe is also replayed by the owner, so a test can't pass because the request was malformed.

## 8. Next task

Day 4 Task 5 — Buyer Next.js app: event page and seat picker calling the API (no queue yet).
