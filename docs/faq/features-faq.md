# Features FAQ

For product, compliance, and delivery teams: what this agent does, what is deterministic vs
LLM, and, importantly, where its responsibilities **stop** and a sibling catalog system takes
over. Cross-references: [`README.md`](../../README.md), [`SPEC.md`](../../SPEC.md),
[`DEMO.md`](../../DEMO.md).

### What does Doc6 actually produce?

From a customer complaint / conduct file it produces four cited artifacts:

- a **`ComplaintSummary`** (a grounded summary of what happened),
- a **`Categorization`** (category, root cause, severity, and regulatory relevance),
- a **`ConductFlag[]`** list (the conduct issues the file raises), and
- a **`DraftResponse`** (a proposed regulator / customer reply).

Every claim carries a source-and-page `Citation`, empty retrieval is a hard error (the agent
never answers ungrounded), and every interaction is written to a WORM audit trail.

### What is deterministic vs done by the LLM?

The consequential decisions are **deterministic and replayable** (pure stdlib, unit-tested):
the mandatory conduct flags (vulnerable customer, systemic issue, regulatory breach) and the
complaint-handling deadline-breach check live in `domain/categorization_service.py`
(`_deterministic_flags` / `_deadline_breached`, and the deterministic flags win the merge),
and the escalation policy lives in `domain/review_policy.py`. The LLM only **classifies**
(the category and severity) and **narrates / drafts** (the summary wording and the draft
response). An auditor can recompute every flag and the deadline breach without the model.
Unit-tested in `tests/unit/test_categorization.py` and `tests/unit/test_policy_and_serialization.py`.

### Is anything auto-approved or auto-sent?

No. `ComplaintReviewPolicy` sets `requires_human_review=True` on every review, and
`draft_is_sendable()` is **always false**: the draft response is a DRAFT and is never sent by
the system (maker-checker, P-06 / R1). Escalation signals raise the review bar; they never
lower it and never auto-execute. Proven by `test_review_always_required` and
`test_draft_response_is_always_a_draft_never_sent` (in `test_policy_and_serialization.py`).

### How does human review actually happen (rule R8)?

Because every complaint review requires a human, the escalation is **routed**, not left as a
per-repo boolean. The shared `review-kit` client (redact-before-wire) submits the review
over S2S to the sibling **Hrz7** Human-Review and Maker-Checker Console under `gcp`/`platform`
(`HUMAN_REVIEW_URL`); the `local` profile enqueues to an in-memory outbox so the routing
path runs offline; and `onprem` is the sovereign placeholder
(`ports/review_router.py`, `adapters/{local,platform,onprem}/review_router.py`). Proven by
`tests/unit/test_review_routing.py`.

### Which capabilities does this repo own vs integrate from the catalog?

This is one system in a catalog of composable GRC systems. It **owns** the complaints /
conduct review domain logic and its four outputs. It **integrates** (via the `platform`
profile's HTTP adapters) several cross-cutting concerns owned by sibling platform systems; do
not rebuild these in a fork:

| Concern | Owned by (catalog id / repo) | Doc6's role |
|---|---|---|
| Runtime guardrail: PII redaction, prompt-injection / jailbreak defense | **Hrz1** `agent-guardrail-gateway` | consumes it on every review (input + output screen) |
| Governed RAG / ACL-aware knowledge base with citations | **Hrz2** `enterprise-knowledge-base` | retrieves grounded policy / precedent passages from it |
| Agent registry, versioning, identity, entitlements | **Hrz3** `agent-registry` | publishes its A2A AgentCard for discovery |
| AI-quality / eval / model-risk promotion gate | **Hrz4** `model-quality-gate` | its eval metrics gate promotion; the offline gate mirrors it |
| Observability + immutable WORM prompt/response audit | **Hrz5** `agent-observability` | writes audit events to it; traces spans through it |
| Human-review / maker-checker console (the R8 target) | **Hrz7** `human-review-console` | routes every review to it for a human to dispose |
| Regulatory Q&A / conduct-rule checklists | **Rsk1** `compliance-advisory` | consumes it for regulatory compliance checks |
| On-prem, CPU-only DLP scrub before egress | **Rsk6** `onprem-dlp` | the sovereign-DLP option behind the redaction port |

So the guardrail, knowledge base, audit sink, eval platform and review console are
*dependencies*, not features of this repo. Doc6's own summary / categorization / conduct-flag
logic is the file-level review, distinct from the platform's runtime controls.

### How does this relate to other systems in the catalog?

Doc6 is a **file-level** complaints and conduct review: it reasons over one complaint file and
proposes an assessment plus a draft. Enterprise-scale complaint *case management* and workflow
orchestration (routing, SLAs, queues across many cases) and the human disposition step are the
sibling **Hrz7** `human-review-console`; do not duplicate those
here. Check [the organization's repository index](https://github.com/portable-genai) before
building a capability that may already have a home.

### Can I use this for a non-complaints document-diligence product?

Yes, that is the point of the ports-and-adapters design. The reusable machinery (citations,
grounding, the deterministic decision service, audit, eval, maker-checker routing) transfers
to other document-diligence verticals; you replace the artifact models and prompts and retune
the policy and taxonomy. Note that a formal `domain/kernel.py` kernel/vertical split (which
would make that reuse cleaner) is a known open item (A7); see
[portability-faq.md](portability-faq.md) and [`docs/ADOPTING.md`](../ADOPTING.md).

### How do I see it working?

`make demo` runs the offline, presenter-paced walkthrough (`scripts/complaints_demo.py` +
`scripts/render_complaints_ui.py`) over a synthetic complaint queue and renders static
audit-first HTML; `make demo-server` runs the click-through server. Everything runs on
synthetic, fictional data with no cloud and no API key.
