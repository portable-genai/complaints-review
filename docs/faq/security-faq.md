# Security FAQ

For an application-security team reviewing this repo before adopting it as a base. Answers
reflect the current code. Cross-references: [`ARCHITECTURE.md`](../../ARCHITECTURE.md),
[`COMPLIANCE.md`](../../COMPLIANCE.md),
[`docs/embedding-and-identity.md`](../embedding-and-identity.md).

### How is a request authenticated? Can a client spoof its identity?

No. Identity is resolved **server-side** from the transport context by an `IdentityPort`
adapter (`api/security.py::get_principal` -> `domain/identity.py`), never from the request
body. The request schemas carry no `actor` field (`api/schemas.py` documents "intentionally
no actor field"), and any client-asserted actor or ACL is discarded. The audit actor and the
entitlement principals both come from the verified `Principal`. Per profile: `local` = seeded
dev personas (no IdP, offline only), `gcp`/`platform` = the IAP-injected signed assertion
(auth configured ON the GCP service), `onprem` = a client-IdP placeholder. **This repo owns
no login flow of its own** (there is no `api/auth.py` or `adapters/oidc/`): end-user
authentication is delegated to the deployment's IAP or IdP, so the OIDC hardening surface
does not exist here to get wrong.

### How is object-level authorization (multi-tenant isolation) enforced?

The case retrieval ACL is derived server-side in `domain/entitlements.py`: a client-asserted
principal set is narrowed to the subset the verified `Principal` actually holds, and evidence
is tagged at ingest. The knowledge-base ACL match is **subset-based and fail-closed** (a
reader must hold every tag on a passage): the FTS5 adapter (`adapters/local/knowledge_base.py`)
has an `acl_tags` column, over-fetches, then applies an all-of filter, and the server-verified
`tenant` is stamped as a `tenant:<t>` ACL principal in the review service (never derived from
the request body). An authenticated user in another tenant gets zero passages for a case id
they merely guessed. Proven in `tests/unit/test_kb_acl.py` and `tests/unit/test_entitlements.py`
(cross-tenant denial was RED before the fix).

### What about the service-to-service calls in the `platform` profile?

The platform adapters source their client from the shared `hex_service_kit.s2s` commons
(`adapters/platform/_s2s.py`): every delegate validates its base URL at construction
(`https://` required outside loopback), attaches a bearer credential (a Cloud Run ID token /
OIDC service-account JWT / gateway key), and propagates the verified end-user actor as a
signed header (`X-Cr-Actor` / `-Sig`) rather than a trust-me JSON field. The receiving
platform services own verification (check C7 in [`docs/practices-audit.md`](../practices-audit.md)).

### Is the demo/dev server safe? Does anything bind 0.0.0.0 by default?

No. There are two bounds, and the load-bearing one rides the **app object** rather than an
entry point.

`main()` binds **loopback (127.0.0.1)** via `hex_service_kit.resolve_bind_host`, and the
Makefile defaults `API_HOST` to `127.0.0.1`. On its own that is a property of one entry
point, not of the application: the Dockerfile `CMD` is
`uvicorn complaints_review.api.app:app --host 0.0.0.0`, and a `uvicorn ... --host 0.0.0.0`
typed by hand behaves the same way, so neither ever reaches that call. The real bound is
`add_loopback_exposure_guard`, registered on the app object as the outermost middleware, so
it holds however the service is started: a non-loopback peer is refused with a 503 before
CORS, before the header baseline and before any route or dependency runs.

**What switches it off is the identity BINDING, and nothing else.** The guard asks the
adapter bound to the identity port whether it verifies the end user (see
`src/complaints_review/ports/identity.py`). The seeded persona adapter reads `X-Dev-Persona`,
a header the caller writes, so it declares `client-asserted` and the guard stays on; the
on-premises placeholder resolves nobody, so it declares `unimplemented` and the guard stays
on; only the IAP adapter, which verifies a signed assertion, declares `verified` and stands
the guard down. A run that named NO profile is bounded too, and additionally refuses the
seeded personas outright, so a lost environment variable cannot publish an unauthenticated
API.

`COMPLAINTS_S2S_TOKEN` is deliberately **not** part of that decision. It authenticates a
calling service and no end user, so setting one closes the service-to-service dependency and
changes nothing about the end-user routes. A guard derived from it would switch off for
exactly the routes it was protecting.

`COMPLAINTS_ALLOW_INSECURE_DEMO=1` remains the single documented opt-out. Secure profiles
keep the container-friendly `0.0.0.0` (ingress is fronted by the platform / IAP and the
identity adapter verifies the caller). The stdlib demo server
(`scripts/complaints_demo_server.py`) is offline and clearly dev-only. Proven in
`tests/unit/test_serving_path_exposure.py` and `tests/unit/test_netdefaults.py`.

### What HTTP security headers are set?

The API sets a CSP `frame-ancestors` directive and `X-Frame-Options: SAMEORIGIN`; the Next.js
UI sets `frame-ancestors`. A fuller baseline (`X-Content-Type-Options: nosniff`,
`Referrer-Policy`, HSTS on secure profiles, and a full UI CSP with `default-src 'self'` and a
scoped `connect-src`) is a **known open hardening item** tracked as check C6 in
[`docs/practices-audit.md`](../practices-audit.md); do not assume the full Doc1 header set is
present here yet.

### Is there an OIDC login flow to review?

No, by design. Doc6 does not implement an Authorization Code / PKCE flow, session cookies, or
JWKS verification; end-user identity is the IAP-injected assertion or a seeded dev persona
(see the identity question above). Check C8 in the practices audit is marked **N-A** for this
repo for exactly this reason. If your deployment needs an interactive login, that belongs at
the IAP / IdP layer in front of the service, not in this codebase.

### How tamper-evident is the audit trail? What are its limits?

The `local` audit store wraps the shared `hex_service_kit.audit.HashChainedAuditLog`: a
SHA-256 hash chain (`entry_hash` over canonical JSON of `prev_hash` plus the record) with
SQLite `UPDATE`/`DELETE` triggers enforcing append-only, plus JSONL export/restore and a
`verify_chain()` that re-checks the chain line by line. The commons module docstring states
which tamper classes the chain alone catches and which it does not (a chain with no external
secret cannot by itself detect a full rewrite). In production the `gcp` profile writes to a
locked WORM log bucket, which provides non-rewritability itself. This repo does not *replace*
the platform audit system (Hrz5); see [features-faq.md](features-faq.md). Proven in
`tests/unit/test_audit_chain.py`.

### Supply chain: are dependencies pinned and scanned?

Yes. Committed lockfiles (`requirements-dev.lock`, `requirements-gcp.lock`, produced by
`uv pip compile`) are installed in CI and the Docker build; `ruff==0.15.18` is pinned exactly;
the base image is pinned by digest (`FROM python:3.12-slim@sha256:...`, both build and runtime
stages); GitHub Actions are SHA-pinned; `.github/dependabot.yml` proposes bumps; and a CI
`supply-chain` job runs `pip-audit` on both lockfiles plus `npm audit --audit-level=high` on
the UI. The three shared commons (`hex-service-kit`, `agent-eval-kit`, `review-kit`) and
the shared `pii-kit` are pinned by git tag and resolved to exact SHAs in the lockfiles, so
there is no build-time coupling.

### Where are secrets? Are any committed?

No secret values are in the repo. `config/settings.yaml` stores only the **names** of env
vars holding secrets (e.g. `${COMPLAINTS_KMS_KEY:-}`, `S2S_TOKEN`, DLP template ids);
values are read at construction time and never logged. Every fixture, customer reference and
NRIC / FIN id is synthetic and obviously fictional.

### What is explicitly out of scope / a residual risk?

- The fuller security-header baseline (C6) and an offline Terraform `fmt`/`validate` CI check
  (D5) are open hardening items in [`docs/practices-audit.md`](../practices-audit.md).
- The in-app posture is defense-in-depth; production is expected to enforce the primary rate
  limit and WAF at the edge (IAP / Apigee / LB).
- The hash chain needs the WORM bucket (or an external anchor) to resist full-rewrite.
- This is a reference build: run your own pen-test, threat model, and model-risk review
  before any live-data deployment (stated throughout the docs).
