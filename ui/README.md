# `complaints-review` Complaints & Conduct File Review : demo console (UI)

A small React / Next.js console that calls the `complaints-review` FastAPI backend and renders a complaint
review: the structured summary, the categorisation with root cause, the conduct flags, and
the draft regulator/customer response (clearly marked as a draft that the system never
sends).

The console has its own gate (`make ui-check`, see below); the Python gate (`make check`)
stays Python-only. To run the console locally:

```bash
cd ui
cp .env.local.example .env.local   # point NEXT_PUBLIC_API_BASE at the backend (default :8095)
npm install
npm run dev                         # http://localhost:3000
```

The backend must be running (e.g. `make run-api` or `complaints-review serve`) and CORS
allows `http://localhost:3000` by default.

## Layout

| Path | Purpose |
|------|---------|
| `app/page.tsx` | The review form and result view (client component). |
| `components/ComplaintReviewView.tsx` | Renders summary, categorisation, flags, draft. |
| `components/CitationCard.tsx` | Source-and-page citation chips. |
| `components/SeverityBadge.tsx` | Severity pills and conduct-flag badges. |
| `lib/api.ts` | Thin fetch client for the FastAPI backend. |
| `lib/types.ts` | TypeScript mirrors of the API response shapes. |
| `lib/csp.mjs` | The ONE place the Content-Security-Policy is built, plus the nonce mint and the build-time refusal. |
| `proxy.ts` | Mints a per-request nonce and sets the policy on both the request and the response. |
| `next.config.mjs` | The static headers only, and the `assertHydratableCsp` refusal. It emits NO CSP. |
| `scripts/assert-hydratable.mjs` | Starts the BUILT server and proves the served page can hydrate. |
| `tests/csp.test.mjs` | `node:test` cover for the parts of the policy a string can decide. |

## Gate

```bash
make ui-install    # npm ci from the committed lockfile
make ui-check      # tsc --noEmit -> node:test -> next build -> assert-hydratable
```

`assert-hydratable` runs LAST, against the artefact the build just produced, and it is the only
step that can see the failure this console is configured to avoid. The CSP puts a per-request
nonce in `script-src`, because Next serves its hydration bootstrap as an INLINE script and a bare
`script-src 'self'` blocks it: `__next_f` never fills, React never attaches, and every control is
dead markup while the headers, the type-check, the build and every test stay green.

Next can only stamp that nonce onto a DYNAMICALLY rendered route, which is why `app/layout.tsx`
sets `export const dynamic = "force-dynamic"` and why `next.config.mjs` refuses to build without
it. Minting a nonce for a statically prerendered page is worse than no fix: nothing carries the
nonce, and `'strict-dynamic'` switches off the `'self'` fallback that had at least been loading
the chunk scripts. A header assertion cannot tell the two apart, because the header is byte
identical in both; only the markup knows, so the check reads the markup.

## Environment

| Variable | Effect |
|---|---|
| `NEXT_PUBLIC_API_BASE` | Backend base URL. An absolute URL widens `connect-src` to that ORIGIN only; the root-relative `/agent/api` embed form widens it by nothing. A value that is neither is refused rather than silently dropped. |
| `NEXT_PUBLIC_FRAME_ANCESTORS` | Who may frame the console. Unset keeps `'self'`; a value naming origins is used verbatim; a value naming NOTHING becomes `'none'`, never an empty directive. Mirrors `COMPLAINTS_FRAME_ANCESTORS` on the backend. |
| `NEXT_PUBLIC_BASE_PATH` | Sub-path the console is mounted under; blank keeps the standalone build. |
| `NEXT_PUBLIC_EMBED` | `1` hides the console's own chrome so a host page owns it. |

All four are build-time. See `docs/embedding-and-identity.md` for the deployment shapes.

Synthetic complaint data shown in the console is fictional.
