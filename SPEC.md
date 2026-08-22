# SPEC · Doc6 Complaints & Conduct File Review

## 1. Purpose and scope

Doc6 is a **decision-support** assistant for Complaints and Conduct Ops at APAC banks. Given a
complaint / conduct file it produces a cited summary, a categorisation with root cause and
conduct flags, and a draft regulator/customer response. It does not decide outcomes and it
does not send anything: a human reviews the categorisation and sends the draft (P-06). The
deployment is single-tenant and Singapore-resident (region `asia-southeast1`).

- Catalog identity: **Doc6**, group `doc`, priority **P2**, buyer **Conduct / Compliance Ops**.
- Service port default: **8095**. Profile env var: **`COMPLAINTS_PROFILE`** (gcp | local |
  platform | onprem). Production sets gcp and dev/tests/CI set local, both explicitly: an
  unset variable binds the local adapter family so an offline process starts, but it is not
  read as choosing local, so every relaxation that posture grants is withheld.

### Deployment profiles

| Profile | Backends | Use |
|---------|----------|-----|
| `gcp` | Document AI, Agent Search, Gemini, Model Armor, DLP, Cloud Logging WORM, Cloud Trace, Gen AI Evals (lazy SDK imports). | Production managed stack. |
| `local` | SQLite FTS5 retrieval (BM25), deterministic schema-driven LLM, regex DLP, heuristic guardrail, append-only SQLite audit, no-op tracer, local document parser, in-process registry / tool catalog. No Google Cloud, no API key, no emulators by default. | A WORKING offline laptop stack: the default for dev, tests and CI; drives the suite and the CLI end to end. |
| `platform` | Guardrail, redaction, knowledge-base, audit, registry and eval ports over HTTP to the shared Hrz1 to Hrz5 services. | Inside the full platform. |
| `onprem` | Fail-fast `NotImplementedError` placeholders. | Google Distributed Cloud migration target (P-02 / P-12). |

Optional emulator opt-in: when `FIRESTORE_EMULATOR_HOST` is set and the `[gcp]` extra is
installed, the `local` registry routes to the official Firestore emulator (the google
client is imported lazily, only on that branch). There is no emulator for Agent Search,
Gemini, Model Armor, DLP or Document AI, so those stay on the SDK-free workaround. The
default `local` path imports no google-cloud package.

## 2. Platform and residency

- Built on the **Gemini Enterprise Agent Platform** (host `aiplatform.googleapis.com`),
  region pinned `asia-southeast1`.
- Models: reasoning `gemini-3.5-flash` (thinking=high) for summary, categorisation and
  drafting; triage `gemini-3.1-flash-lite`. Never a floating default or `gemini-2.0-flash`.
- Unified SDK `google-genai`. ADK `google-adk==2.3.0`. A2A v1.0 + MCP 2025-11-25.
- Audit: Cloud Logging locked WORM bucket, retention 2557 days. Tracing: Cloud Trace via
  OpenTelemetry, message-content capture OFF. Eval: Gen AI evaluation service.

## 3. Dependencies (catalog matrix)

Hrz1 Guardrail, Hrz2 Enterprise KB, Hrz3 Registry, Hrz4 AI Quality, Hrz5 Observability/Audit (all
already built). `platform` clients plus on-prem stubs. Policy / regulatory-guidance
retrieval is via Hrz2 `/v1/search`. Register in Hrz3 (R4), audit to Hrz5 (R2), Hrz4 gate at
promotion (R5), Rsk3 at intake (R6). No Rsk1 dependency.

## 4. Artifacts

| Artifact | Fields | Review |
|----------|--------|--------|
| `ComplaintReview` | file_id, summary, categorization, conduct_flags, draft_response, generated_at | `requires_human_review=True` |
| `ComplaintSummary` | issue, products, channel, timeline[], parties, citations | bundled |
| `Categorization` | category, root_cause, severity, regulatory_relevance, citations | bundled |
| `ConductFlag[]` | kind, severity, detail, citations | bundled |
| `DraftResponse` | body, tone, citations, requires_human_review, is_draft | never sent by the system |

Every artifact is cited (page-level where the source has pages), audited, and produced
through the maker-checker pipeline. The draft response is never auto-sent.

## 5. Services and the pipeline

`ComplaintReviewService(extraction, knowledge_base, llm, guardrail, redaction, tracer,
audit, review_policy=None)` with `.review(file, actor) -> ComplaintReview`,
`.summarize(file, actor)` and `.draft_response(file, actor)`. Supported by
`CategorizationService` (category + root cause + conduct flags, with a deterministic policy
for mandatory flags), `ResponseDraftingService` (the grounded draft) and a
`ComplaintReviewPolicy` (the maker-checker gate).

Pipeline (full R1 safety because the file carries customer PII; wrapped in a tracer span;
audited):

```
redact(narrative)
  -> guardrail(INPUT)                       [blocked -> audit BLOCKED + raise]
  -> extract attached documents (+ redact each extract)
  -> Hrz2 retrieve policy / regulatory guidance  [empty -> audit + raise]
  -> llm summarise
  -> categorise (category + root cause + conduct flags; deterministic + LLM)
  -> llm draft response (grounded; always a draft)
  -> assemble ComplaintReview (requires_human_review=True)
  -> guardrail(OUTPUT)                       [blocked -> audit BLOCKED + raise]
  -> review policy (always) + escalation
  -> audit (already-redacted prompt + response)
```

The draft response is never sent by the system (R1 / P-06): a human sends it.

## 6. HTTP API (endpoints Doc6 defines)

All JSON field names mirror the domain dataclasses (enums as strings). Requests carry no
`actor`: identity is resolved server side from the verified `Principal` (an IAP assertion in
gcp/platform, or a seeded dev persona selected via the `X-Dev-Persona` header in local), and the
verified subject becomes the audit actor while the verified principals scope governed retrieval. See
[docs/embedding-and-identity.md](docs/embedding-and-identity.md).

- `POST /v1/review {file}` -> `ComplaintReview`.
- `POST /v1/summary {file}` -> `ComplaintSummary`.
- `POST /v1/draft-response {file}` -> `DraftResponse`.
- `GET /healthz` -> `{status, profile, region}`.
- `GET /v1/personas` -> `[{id, subject, tenant, principals}]` (seeded dev personas; empty outside
  the local profile).
- `GET /.well-known/agent-card.json` -> A2A AgentCard `{name, description, url, version,
  provider, skills:[{id, name, description}]}`. Skills: `review_complaint`, `categorise`,
  `draft_response`.

A guardrail block or an empty corpus is returned as a 200 blocked envelope
(`{file_id, blocked, requires_human_review, detail, reason}`), never a 5xx.

### Services Doc6 consumes

- Hrz1 guardrail (`HRZ_GUARDRAIL_URL`): `POST /v1/guardrail/screen`, `POST /v1/redact`.
- Hrz2 enterprise KB (`HRZ_KB_URL`): `POST /v1/search`.
- Hrz3 registry (`HRZ_REGISTRY_URL`): `POST /v1/agents`, `GET /v1/agents/{name}`,
  `GET /v1/agents`.
- Hrz4 AI quality (`HRZ_QUALITY_URL`): `POST /v1/evaluations` and `POST /v1/gate`, each with a
  structured body `{target: {model, prompt_version, dataset_id, system}, dataset_id, bundle:
  "doc6-complaints-review"}`. `/v1/evaluations` returns `{results[]}` (parsed from `results`, not
  `metrics`); `/v1/gate` returns `{passed}`. Metric selection is by the registered bundle name
  `doc6-complaints-review` (no bare metric names); the top-level `dataset_id` must equal
  `target.dataset_id`, and Hrz4 returns 422 on divergence or on unregistered metric names.
- Hrz5 observability (`HRZ_OBSERVABILITY_URL`): `POST /v1/audit`.

## 7. Eval gate (Hrz4 / P-08)

`eval/run_eval.py` drives the real `ComplaintReviewService` over a synthetic golden set with
deterministic fakes (no GCP). Metrics and thresholds:

| Metric | Threshold |
|--------|-----------|
| `categorisation_accuracy` | >= 0.85 |
| `groundedness` | >= 0.80 (draft cites policy) |
| `citation_accuracy` | >= 0.90 |
| `pii_safety` | >= 0.99 (no unredacted PII; response always a draft, never auto-sent) |

Exit non-zero on any failure. The production evaluator (`--use-gcp`) routes through the Gen
AI evaluation service; the `platform` profile routes to Hrz4, which selects this metric suite
from the registered `doc6-complaints-review` bundle rather than from bare metric names (see the
Hrz4 contract in §6).

## 8. Non-goals

- Doc6 does not decide complaint outcomes or remediation amounts.
- Doc6 does not send any response to a customer or a regulator.
- Doc6 does not build its own retrieval backend; policy / regulatory guidance is Hrz2's (R3).
