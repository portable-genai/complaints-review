# Embedding and identity: client integration guide (B6 Complaints and Conduct File Review)

This guide shows how an enterprise client runs the B6 service and, when desired, embeds its UI
inside an existing web application with secure single sign-on (SSO) so users never see a second
login. It is grounded in what the codebase implements today: a server verified `IdentityPort`, a
same origin reverse proxy embed mode, CSP `frame-ancestors` plus a per tenant CORS allowlist, and
a UI persona picker for offline demos.

The core invariant, enforced in code: the server never trusts a client asserted `actor` or ACL.
Identity is resolved server side from the inbound transport, and the verified `Principal` supplies
both the audit actor and the entitlement principals that scope governed retrieval.

## The two pieces

The service ships as two cooperating pieces:

- **Backend**: a FastAPI service (default port `8095`) exposing the review endpoints
  (`/v1/review`, `/v1/summary`, `/v1/draft-response`), health (`/healthz`), the persona list
  (`/v1/personas`), and the A2A agent card (`/.well-known/agent-card.json`).
- **UI**: a Next.js console (default port `3000`) that calls the backend and renders the cited
  review. `NEXT_PUBLIC_EMBED=1` drops the UI's own header/chrome (`ui/app/layout.tsx`); the UI
  base path and API base are build time env vars (`ui/next.config.mjs`, `ui/lib/api.ts`).

## Three deployment shapes

Pick the cheapest shape the host can actually satisfy.

| # | Shape | Use when the host... | Host work | Identity |
|---|-------|----------------------|-----------|----------|
| 1 | **Embedded, same origin reverse proxy** | controls its own edge (nginx / Next.js rewrites) and can federate its IdP into Cloud IAP. | Two proxy routes (`/agent/*`, `/agent/api/*`) plus one `<iframe src="/agent/">`. | IAP verified `x-goog-iap-jwt-assertion`; the proxy forwards the header. |
| 2 | **Standalone behind Cloud IAP** | has no host app, or wants a separate console at its own URL. | DNS plus HTTPS load balancer plus IAP. | IAP verified assertion; IAP plus Workforce Identity Federation gives SSO. |
| 3 | **Local dev, no auth** | is evaluating offline, no IdP. | None. | Seeded personas via `X-Dev-Persona` (`adapters/local/identity.py`). |

Because the same origin iframe (shape 1) is first party, there is no third party cookie problem and
no CORS to configure. The standalone shape (2) is a top level app, not framed.

## Shape 3: run locally, no auth

Local mode (`COMPLAINTS_PROFILE=local`) runs the whole pipeline offline: SQLite FTS5 retrieval, a
deterministic LLM, regex redaction, a heuristic guardrail, and NO IdP, AD, or LDAP. Identity is
resolved from a small set of seeded dev personas (`adapters/local/identity.py`) selected by an
`X-Dev-Persona` request header, with the first persona as the default.

```bash
# Backend (repo root)
export COMPLAINTS_PROFILE=local
make run-api                       # uvicorn on http://localhost:8095

# UI (in ./ui)
cp .env.local.example .env.local   # NEXT_PUBLIC_API_BASE defaults to http://localhost:8095
npm install && npm run dev         # http://localhost:3000
```

The UI fetches `GET /v1/personas` and sends the chosen id as `X-Dev-Persona`. The seeded personas
deliberately span different entitlements and tenants (including a cross tenant persona) so per user
and per tenant authorization is demoable fully offline:

| Persona id | Subject | Tenant | Entitlement principals |
|-----------|---------|--------|------------------------|
| `analyst` | `demo.analyst@bank.example` | `demo-bank` | `group:complaints-analyst`, `group:conduct` |
| `approver` | `demo.approver@bank.example` | `demo-bank` | `group:complaints-analyst`, `group:conduct`, `group:complaints-approver` |
| `auditor` | `demo.auditor@bank.example` | `demo-bank` | `group:audit` |
| `other-tenant` | `user@other-tenant.example` | `other-bank` | `group:complaints-analyst` |

```bash
curl -s http://localhost:8095/v1/personas | python -m json.tool
curl -s -X POST http://localhost:8095/v1/review \
  -H 'Content-Type: application/json' -H 'X-Dev-Persona: auditor' \
  -d @your-file.json | python -m json.tool
```

In secure profiles `X-Dev-Persona` is ignored entirely, so leaving persona selection code in the UI
is harmless in production. `/v1/personas` returns an empty list outside `local`, so the picker never
renders there.

## Shape 2: standalone behind Cloud IAP

When there is no host application, deploy the service on its own URL:

1. Deploy backend and UI behind the same HTTPS load balancer and Cloud IAP.
2. Set `COMPLAINTS_PROFILE=gcp` and `COMPLAINTS_IAP_AUDIENCE` so the backend verifies the IAP
   assertion. Authentication is configured on the load balancer / service (not hand rolled), and
   the backend still independently re verifies the signed assertion (the defense that survives an
   edge bypass or a forged unsigned header).
3. Point the UI at the backend with `NEXT_PUBLIC_API_BASE`. If UI and backend are on different
   origins, also set `COMPLAINTS_CORS_ORIGINS` to the UI origin (explicit allowlist, never `"*"`):

   ```bash
   export COMPLAINTS_CORS_ORIGINS="https://complaints.client.example"
   export NEXT_PUBLIC_API_BASE="https://api.complaints.client.example"
   ```

4. Share the URL with authorized users. IAP plus Workforce Identity Federation gives SSO from the
   corporate IdP.

Leave `COMPLAINTS_FRAME_ANCESTORS` at its `'self'` default: nothing should iframe a standalone
deployment.

## Shape 1: embed via same origin reverse proxy

Serve the service under your own origin at a sub path (for example `/agent/`) via a reverse proxy,
then drop an iframe pointing at that same origin path. The client owns exactly two things: a proxy
route and an iframe tag.

### nginx

```nginx
# On https://portal.client.example
location /agent/ {
    proxy_pass         http://complaints-ui.internal:3000/;    # the Next.js UI
    proxy_set_header   Host              $host;
    proxy_set_header   X-Forwarded-Proto $scheme;
}

# The UI's API calls (NEXT_PUBLIC_API_BASE=/agent/api) also resolve same origin:
location /agent/api/ {
    proxy_pass         http://complaints-backend.internal:8095/;
    proxy_set_header   Host              $host;
    proxy_set_header   X-Forwarded-Proto $scheme;
    # IAP runs in front of this origin, so the x-goog-iap-jwt-assertion header is
    # present on the inbound request and forwarded through to the backend.
}
```

### Next.js host app

If the parent is itself Next.js, use `rewrites()` in its own config:

```js
// next.config.mjs of the PARENT app
const nextConfig = {
  async rewrites() {
    return [
      { source: "/agent/api/:path*", destination: "http://complaints-backend.internal:8095/:path*" },
      { source: "/agent/:path*",     destination: "http://complaints-ui.internal:3000/:path*" },
    ];
  },
};
export default nextConfig;
```

### Mount the agent UI under the sub path and hide its chrome

```bash
# Environment for the agent UI (build time)
NEXT_PUBLIC_BASE_PATH=/agent       # mount the UI (and assets) under the sub path
NEXT_PUBLIC_API_BASE=/agent/api    # same origin API calls (no CORS needed)
NEXT_PUBLIC_EMBED=1                # hide the UI's own header/nav chrome when embedded
```

### The iframe tag (host page)

```html
<!-- On https://portal.client.example, inside your existing page -->
<iframe
  src="/agent/"
  title="Complaints and Conduct File Review"
  style="width:100%; height:100%; border:0;"
  loading="lazy">
</iframe>
```

Height caveat: `height:100%` renders correctly only inside a host container that already has a fixed
pixel height. There is no child to parent resize message today, so give the iframe a sized container.

### Allow the parent origin to frame the UI

The backend emits `Content-Security-Policy: frame-ancestors <COMPLAINTS_FRAME_ANCESTORS>` via
middleware (`api/app.py`), and adds `X-Frame-Options: SAMEORIGIN` only when the value is `'self'`
(the legacy header cannot express a multi origin allowlist, so CSP wins for multiple parents):

```bash
export COMPLAINTS_FRAME_ANCESTORS="https://portal.client.example"
# multiple parents are space separated, per the CSP grammar:
# export COMPLAINTS_FRAME_ANCESTORS="https://portal.client.example https://admin.client.example"
```

Scope limit: `frame-ancestors` is honored on the HTTP response of the document the browser actually
frames. In shape 1 that document is served same origin through the proxy, so the backend header
reaches it. It must be delivered as a real response header, not via a `<meta>` element.

In shape 2 the framed document is served by Next, not by the backend, so the console emits its own
`frame-ancestors` from `NEXT_PUBLIC_FRAME_ANCESTORS`. The two variables are read with the SAME three
states on purpose (see below): an operator who configures one and its twin gets one answer, not two.

### The console's own Content-Security-Policy

The document a browser parses and executes is served by Next, so the document layer policy is the
console's to emit. It is built in exactly one place, `ui/lib/csp.mjs`, and read by two:

| Layer | File | What it does |
|---|---|---|
| Per request headers | `ui/proxy.ts` | Mints a fresh script nonce, builds the policy, and sets it on BOTH the request headers (where Next reads the nonce it stamps onto every script tag) and the response headers (what the browser enforces). |
| Build time refusal | `ui/next.config.mjs` | Emits only the static headers (`X-Content-Type-Options`, `Referrer-Policy`) and calls `assertHydratableCsp`, which refuses to build a console whose rendering mode cannot carry the nonce. |

`next.config.mjs` deliberately emits NO `Content-Security-Policy`. Two layers both setting one hands
the browser two policies to intersect, and the stricter wins per directive, which is how a nonce
less `script-src` comes back without anybody editing the policy.

Three things about this are load bearing, and each of them is a defect somebody has already shipped:

1. `script-src` carries the per request nonce plus `'strict-dynamic'`. Next serves its hydration
   bootstrap as an INLINE script carrying the Flight payload, so a bare `script-src 'self'` blocks
   it: `__next_f` never fills, React never attaches, and every control on the page is dead markup
   while the headers, the type check, the build and every test stay green.
2. `app/layout.tsx` sets `export const dynamic = "force-dynamic"`. Next can only stamp a per
   request nonce onto a DYNAMICALLY rendered route. Minting a nonce for a statically prerendered
   page is worse than no fix at all: nothing carries it, and `'strict-dynamic'` switches off the
   `'self'` fallback that had at least been loading the chunk scripts.
3. `ui/scripts/assert-hydratable.mjs` proves it by execution. It starts the BUILT server, fetches
   the served document and asserts every script tag carries the served nonce. A header assertion
   cannot see this failure, because the header is byte identical in the working case and the
   broken one. It runs last in `make ui-check` and in CI.

`object-src 'none'` and `base-uri 'self'` are present for the two escapes `default-src` alone does
not close in every agent: a plugin document, and injected markup re-pointing every relative URL on
the page at an attacker origin.

## The identity contract

The single invariant, preserved across every shape: the server never trusts a client asserted actor
or ACL.

- `get_principal` (`api/security.py`) builds a `RequestContext` from inbound headers only, asks the
  active `IdentityPort` adapter to resolve a verified `Principal`, and treats any failure as a hard
  401.
- Every artifact route takes `principal: CurrentPrincipal` and passes `actor=principal.actor` and
  `principals=principal.principals` into the review service. The request schema (`ReviewRequest`)
  has NO `actor` field, so a client supplied identity is simply ignored.
- The review service scopes governed A2 retrieval with `acl_principals=(actor, *principals)`, so the
  data path returns only what the verified user may see.

The `Principal` (`domain/identity.py`) models everything enforcement needs: `subject` (the audit
actor), `principals` (entitlement groups/ACL), `tenant` (multi tenant partition), `assurance` (auth
strength hint), and `source` (which adapter resolved it).

Identity options by profile:

| Profile | Adapter | What it does |
|---------|---------|--------------|
| `local` | `LocalPersonaIdentityAdapter` | Offline dev/test identity via `X-Dev-Persona`, no IdP. |
| `gcp` / `platform` | `IapIdentityAdapter` | Verifies the signed `x-goog-iap-jwt-assertion` (signature, audience, issuer, expiry) against Google's IAP public keys; `tenant` from the `hd` claim; never logs the assertion. |
| `onprem` | `OnPremIdentityAdapter` | Fail fast placeholder: raises `NotImplementedError` rather than returning an unverified identity (the correct fail closed default). Implement it against your enterprise IdP (OIDC/SAML). |

Defense in depth PEP: the edge (Cloud IAP / Apigee) authenticates at ingress, the `agent-guardrail-gateway`
applies central policy, and this backend independently re verifies and derives identity itself, then
enforces per user ACLs in retrieval. Each layer assumes the others may be bypassed.

## Configuration knobs

| Variable | Side | Purpose |
|----------|------|---------|
| `COMPLAINTS_PROFILE` | backend | `local` \| `gcp` \| `platform` \| `onprem`. Selects the identity adapter (and the whole adapter set). |
| `COMPLAINTS_IAP_AUDIENCE` | backend | The IAP audience string (the exact structured resource path) the backend verifies against. Required in `gcp`/`platform`. |
| `COMPLAINTS_CORS_ORIGINS` | backend | Explicit origin allowlist for the cross origin / standalone case (comma separated). Never `"*"`; unset falls back to the localhost dev origins. |
| `COMPLAINTS_FRAME_ANCESTORS` | backend | CSP `frame-ancestors` allowlist: parent origins permitted to iframe the UI. Defaults to `'self'`. |
| `NEXT_PUBLIC_API_BASE` | UI | Backend base URL the UI calls. Build time. An absolute URL widens the console's `connect-src` to that ORIGIN only; the root relative `/agent/api` embed form widens it by nothing, because console and API are then one origin. |
| `NEXT_PUBLIC_FRAME_ANCESTORS` | UI | CSP `frame-ancestors` for the document Next serves, read in the same three states as its backend twin: unset keeps `'self'`; a value naming origins is used verbatim; a value naming NOTHING becomes `'none'`, never an empty directive (browsers discard an empty directive as a parse error, which silently removes the restriction the operator asked for). Build time. |
| `NEXT_PUBLIC_BASE_PATH` | UI | Sub path the UI is mounted under. Build time; blank keeps the standalone build. |
| `NEXT_PUBLIC_EMBED` | UI | Set to `1` to hide the UI's own chrome. Build time. |
| `X-Dev-Persona` | request header | Local profile only. Selects a seeded dev persona; ignored in secure profiles. |

## Checklists

### Client integration checklist

**Shape 1 (same origin reverse proxy):**

- [ ] Reverse proxy route mapping `/agent/*` to the agent UI service.
- [ ] Reverse proxy route mapping `/agent/api/*` to the agent backend service.
- [ ] `<iframe src="/agent/">` on the host page in a sized container.
- [ ] Build the UI with `NEXT_PUBLIC_BASE_PATH=/agent`, `NEXT_PUBLIC_API_BASE=/agent/api`,
      `NEXT_PUBLIC_EMBED=1`.
- [ ] `COMPLAINTS_FRAME_ANCESTORS` set to the exact parent origin(s).
- [ ] IdP federated into IAP (Workforce Identity Federation) so users carry one session through.

**Shape 2 (standalone):**

- [ ] DNS plus HTTPS load balancer plus IAP fronting the deployment.
- [ ] `COMPLAINTS_PROFILE=gcp` and `COMPLAINTS_IAP_AUDIENCE` set (backend refuses to verify without
      the audience).
- [ ] `COMPLAINTS_CORS_ORIGINS` set to the UI origin if UI and API are on different origins.
- [ ] URL shared with authorized users/groups.

### Security checklist

- [ ] HTTPS everywhere (the load balancer terminates TLS; IAP requires it).
- [ ] IAP audience configured: `COMPLAINTS_IAP_AUDIENCE` set to the exact structured resource path in
      any IAP profile.
- [ ] Framing locked down: `COMPLAINTS_FRAME_ANCESTORS` set to the exact parent origin(s); `'self'`
      for standalone; never a wildcard.
- [ ] Origins locked down: same origin proxy (no CORS) for shape 1; otherwise
      `COMPLAINTS_CORS_ORIGINS` is an explicit allowlist, never `"*"`.
- [ ] No client asserted identity trusted: production uses `gcp`/`platform` (or an implemented
      `onprem`), not `local`.

## Further layers (not built here, documented for completeness)

The reference build `cdd-sow-research` carries additional embedding and identity layers that are
out of scope for this repo but ready to receive on the same seams:

- A Mode 6 "launch in new tab" OIDC Authorization Code plus PKCE login with a self issued session
  cookie (a standalone, top level navigation path for hosts with an OIDC IdP but no proxy or IAP).
- Cross origin token handoff shapes: a versioned loader plus web component, a hardened postMessage
  contract, and a host minted short TTL bearer verified against the host IdP's JWKS by a new adapter
  on the `IdentityPort` seam.
- Per hop OAuth2 token exchange (on behalf of), Workload Identity, and mTLS to the Hrz platform
  services; per tenant request time framing/CORS/issuer policy; a tenant predicate, fail closed ACL
  in the knowledge base; and Trusted Types on the UI bundles.

See `cdd-sow-research/docs/embedding-and-identity.md` for the full treatment of those layers.
