# Week 1 · Day 3 · Task 03 — Cognito user pool with buyer and organiser groups; JWT checks in FastAPI

- **Date:** 2026-11-21
- **Phase / milestone:** Phase 2 (Booking core) → M2
- **Status:** Done
- **Commit / PR:** [#19](https://github.com/sheshagiri-62/surgegate/pull/19)

## 1. What the task was

Plan text: *"Cognito user pool with buyer and organiser groups; JWT checks in FastAPI."* The
blueprint wants email + OTP login and "JWTs with role and tenant", and the API must reject any
organiser request for another tenant's event. This task builds the identity part those rules
depend on.

## 2. What I did, step by step

1. **New module `infra/modules/identity`.** The plan's repo layout has no place for Cognito, so
   this is the one addition.
   - **User pool `surgegate-dev`:**
     - Essentials tier, needed for email-OTP sign-in and for adding claims to access tokens.
     - Sign-in by verified email; usernames case-insensitive.
     - Allowed first factors `EMAIL_OTP` and `PASSWORD`.
     - Cognito's built-in email sender (free, 50/day; SES on Day 8).
   - **Groups `buyer` and `organiser`.** Membership is set only by an admin.
   - **Custom attribute `custom:tenant_id`** (UUID). No app client may write it.
   - **Three app clients:**
     - `buyer-web` and `organiser-web`: public, no secret, USER_AUTH (email OTP) / SRP / refresh,
       token revocation on, user-existence errors hidden.
     - `test` (dev only): USER_PASSWORD_AUTH, for scripts and tests.
   - **Pre-token-generation V2 Lambda** (python3.12, arm64, 128 MB, logs kept 7 days): copies
     `custom:tenant_id` into a `tenant_id` claim on the **access token**.
2. **Test users as code** (`infra/envs/dev/test_users.tf`, dev only):
   - organiser A (tenant A), organiser B (tenant B) and buyer 1;
   - random passwords stored in Secrets Manager `surgegate/dev/test-users`;
   - `.test` email addresses, so Cognito never sends anything.
3. **`app/auth.py`:**
   - Verifies the access token: RS256 signature against the pool's JWKS (cached for an hour; an
     unknown `kid` triggers one refetch), `iss`, `exp` (60 s leeway), `token_use == "access"` and
     `client_id` ∈ our clients.
   - Builds a `Principal` (sub, groups, tenant_id) from verified claims only.
   - FastAPI dependencies `Buyer`, `Organiser` (an organiser must have a tenant) and `AnyUser`.
   - Fails closed (503) if auth isn't configured.
   - New `GET /me`.
4. **Chart:** `COGNITO_USER_POOL_ID` and `COGNITO_CLIENT_IDS`. Not secret: the browser needs them
   to sign in.
5. **Bootstrap:** the CI plan role may also read `surgegate/dev/test-users-*`, for Terraform's
   refresh (error 3 below).
6. **Applied** with saved plans (you approved): identity (11), test users (13, then 5 after error 1),
   bootstrap (1 change), Lambda zip fix (1 change). Then PR #19 merged, the pipeline ran and Argo CD
   deployed `fe94bc0cb8aa`.

### Commands I ran

```bash
terraform -chdir=infra/envs/dev providers schema -json      # check Cognito attributes in provider 6.73
terraform -chdir=infra/envs/dev init && terraform providers lock -platform=windows_amd64 -platform=linux_amd64 hashicorp/archive
terraform -chdir=infra/envs/dev validate && tflint
terraform -chdir=infra/envs/dev plan … -out=identity.tfplan     # 11 to add
aws pricing get-products --service-code AmazonCognito …          # Essentials $0.015/MAU (beyond free tier)
terraform -chdir=infra/envs/dev apply identity.tfplan
python -m pytest -q                                              # 25 passed (17 new auth tests)
terraform -chdir=infra/envs/dev plan … -out=users.tfplan && terraform apply users.tfplan   # error 1
terraform -chdir=infra/envs/dev plan … -out=users.tfplan && terraform apply users.tfplan   # 5 added
uvicorn app.main:app --port 8077   # + script: initiate-auth (test client) → /me with real tokens
aws cognito-idp update-user-attributes --access-token … custom:tenant_id=…   # must be refused
aws cognito-idp sign-up … custom:tenant_id=…                                # must be refused
cd infra/bootstrap && terraform plan -out=test-users.tfplan && terraform apply test-users.tfplan
terraform -chdir=infra/envs/dev plan … -out=lambda.tfplan && terraform apply lambda.tfplan   # zip fix
gh pr merge 19 --squash && gh run watch <build-deploy>
kubectl -n booking port-forward svc/booking-api 18080:80   # + /me with real tokens
```

### Files created or changed

| File | What it does |
| --- | --- |
| `infra/modules/identity/main.tf`, `variables.tf`, `outputs.tf`, `versions.tf` | User pool, groups, clients, pre-token Lambda + role + logs |
| `infra/modules/identity/lambda/pre_token.py` | Adds `tenant_id` to access and ID tokens |
| `infra/envs/dev/main.tf`, `outputs.tf`, `versions.tf`, `.terraform.lock.hcl` | `module "identity"`, outputs, `hashicorp/archive` provider |
| `infra/envs/dev/test_users.tf` | dev test users and their secret |
| `infra/bootstrap/iam.tf` | Plan role may read the dev test-users secret |
| `services/booking-api/app/auth.py` | JWT verification and role/tenant dependencies |
| `services/booking-api/app/main.py` | `GET /me` |
| `services/booking-api/tests/test_auth.py` | 17 tests with a local RSA key and fake JWKS |
| `deploy/helm/booking-api/…` | Cognito env vars |
| `.gitignore` | Ignore Lambda zips built by Terraform |

## 3. How it works

**A JWT is a signed note.** When you sign in, Cognito gives you an *access token*: a small JSON
document saying "this is user X, in group Y, tenant Z, valid until 12:30", signed with Cognito's
private key. Anyone can read it, but nobody can change it without breaking the signature. The API
holds no passwords. It downloads Cognito's **public** keys (the JWKS) once an hour and checks every
token's signature, issuer, expiry, type and client. If someone edits the tenant in a token, the
signature no longer matches and the API answers 401. That was tested with a real token.

**Role and tenant.** The role is the Cognito group (`cognito:groups`), and the tenant is the
`tenant_id` claim. Users can't change either: groups are set by an admin, and Cognito refuses any
client write to `custom:tenant_id` (`NotAuthorizedException … unauthorized attribute`). By default
Cognito puts custom attributes only in the *ID* token. A small Lambda that runs at token time copies
the tenant into the *access* token, because APIs should authorize with access tokens: ID tokens are
for the app to know who the user is.

**How it fits SurgeGate.**
- Organiser endpoints (Task 4) take the tenant **only from the token**, so organiser A can never
  name tenant B in a URL or body.
- Buyers sign in with email + OTP.
- The waiting room (Days 5–6) will require a verified Cognito account for a queue place.

## 4. Errors I hit and how I fixed them

| # | Error (exact message) | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `Error: Provider produced inconsistent final plan` (x2, on `aws_cognito_user.test`) | The users' `attributes` map used `random_uuid` values that are unknown at plan time. The provider then saw a different map at apply time | Once the first apply had created the random values and the secret, a new plan (5 to add) applied cleanly |
| 2 | Test `garbage` expected `unknown signing key` but got `invalid token` | A non-JWT fails when the header is decoded, before any key lookup | Fixed the test's expectation. `invalid token` is the right answer |
| 3 | CI: `AccessDeniedException: User: …assumed-role/surgegate-gha-plan/infra-plan-pr19 is not authorized to perform: secretsmanager:GetSecretValue on resource: …secret:surgegate/dev/test-users-dp4VnD` | Terraform refreshes the secret version during plan; the read-only CI role had no read on that secret | Bootstrap change (you approved): plan role may read `surgegate/dev/test-users-*`, the same pattern as redis-auth. The role can already read these values in the state file |
| 4 | CI plan: `~ aws_lambda_function.pre_token … source_code_hash = "CfMx…" -> "i2uz…"` (perpetual diff) | `archive_file` stores file permission bits in the zip, which differ between Windows and Linux, so CI built a different zip | `output_file_mode = "0644"` makes the zip identical everywhere. CI plan now `No changes` |
| 5 | ruff `S106 Possible hardcoded password assigned to argument: "token_use"` | False positive: `token_use="id"` is a claim name | `# noqa: S106` on that test line |

## 5. How I verified it works

| Check | Result |
| --- | --- |
| Unit tests (`tests/test_auth.py`, local RSA key) | 17 passed: valid token; missing (401 + `WWW-Authenticate: Bearer`); expired; wrong issuer; wrong client; ID token; bad signature; unknown kid; missing `token_use`; garbage; **HS256 algorithm-confusion** forgery; buyer → organiser route (403); organiser without tenant (403); organiser → buyer route (403); malformed tenant; unconfigured auth (503) |
| Real Cognito tokens (local API) | Access tokens: `token_use=access`, `groups=['organiser']`, `tenant_id=dcae9cad…` (A) and `61a4d81f…` (B); buyer `groups=['buyer']`, no tenant. ID token → `401 access token required`; token with tenant edited to B → `401 invalid token` |
| Users can't set their tenant | Self-update and sign-up with `custom:tenant_id` → `NotAuthorizedException … unauthorized attribute` |
| Deployed pods (`fe94bc0cb8aa`, port-forward) | organiser A `/me` → 200 with tenant A; buyer → 200, tenant `None`; no token → 401; garbage → 401 |
| CI (#19) | ruff + pytest (25 with Postgres) green; dev plan `No changes` |

## 6. Cost impact

No hourly resources.
- Cognito Essentials costs $0.015 per monthly active user beyond the 10,000-MAU free tier, so
  about $0 with 3 dev users.
- **Watch out on Day 11:** load tests must not sign in thousands of synthetic users through
  Cognito unless that stays inside the free tier.
- Lambda and logs are within the free tier. The test-users secret is $0.40/month.
- All of it is persistent; `make down` doesn't touch it.

## 7. Interview notes

- **Q:** Why validate the access token and not the ID token?
  **A:** The ID token tells the *client app* who the user is. The access token is meant for
  *APIs*: it names the client it was issued to, and it can be revoked. I check `token_use=access`
  and `client_id`, so an ID token, or a token issued to some other app, is refused. The tenant is
  added to the access token by a pre-token-generation Lambda.
- **Q:** How do you stop a user claiming to be in another tenant?
  **A:** The tenant comes only from a signed claim. Users can't write `custom:tenant_id` (Cognito
  refuses it), and editing the token breaks the RS256 signature. The API never takes a tenant from
  the URL or body.
- **Q:** What is algorithm confusion, and how did you prevent it?
  **A:** An attacker signs a token with HS256 using the server's *public* key as the HMAC secret,
  hoping the server verifies it with that same key. The API pins `algorithms=["RS256"]`, and a test
  proves the forged HS256 token is rejected.

## 8. Next task

Day 3 Task 4 — Organiser endpoints: create event, upload seat map (CSV), list events, tenant-scoped.
