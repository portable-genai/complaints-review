# On-prem migration · Doc6 Complaints & Conduct File Review

Doc6 is designed so the managed Google Cloud stack can be replaced by an on-premise stack
(Google Distributed Cloud, or another sovereign target) **without touching the domain
core** (P-02, P-12). This document is the migration runbook.

## What stays the same

- The whole of `src/complaints_review/domain/` (models, services, prompts, policy).
- The ports (`src/complaints_review/ports/`).
- The API, CLI and agent wiring (they depend on ports, not adapters).
- The service contracts and the eval gate.

## What changes

Only the **adapter bindings**. Switching `COMPLAINTS_PROFILE=onprem` (or `profile: onprem`
in `config/settings.yaml`) rebinds every port to the `onprem` adapter family in
`src/complaints_review/adapters/onprem/`. Today those adapters are placeholders: each
constructs cleanly with a single `Settings` argument, structurally satisfies its Protocol
(the contract test proves this), and raises `NotImplementedError` from every method, except
the tracer, which is a safe no-op.

To migrate, fill in the body of each placeholder against your on-premise platform:

| Port | On-prem implementation target |
|------|-------------------------------|
| `DocumentExtractionPort` | Your on-premise document parser. |
| `KnowledgeBaseClientPort` | Your on-premise governed search over the policy / regulatory corpus. Must enforce ACLs and return page-level citations. |
| `LLMPort` | Your on-premise model serving (summary, categorisation, drafting). |
| `GuardrailPort` | Your on-premise prompt / response screening. Must fail closed, never fail open. |
| `PIIRedactionPort` | Your on-premise de-identifier. Must never leak customer PII. |
| `AuditSinkPort` | Your on-premise immutable (WORM) audit store. Must never silently drop a record. |
| `ObservabilityTracerPort` | Your on-premise tracer (optional; the placeholder is already a safe no-op). |
| `EvaluationGatePort` | Your on-premise eval backend. Must never wave a model through unevaluated. |
| `AgentRegistryPort` | Your on-premise agent catalog. |
| `ToolCatalogPort` | Your on-premise governed MCP tool catalog. |

## Why the stubs raise

A half-migrated deployment must fail loudly, not silently. A guardrail that fail-opens, a
redactor that passes PII through, or an audit sink that drops records would each be a
serious conduct / compliance failure. So those placeholders raise `NotImplementedError`
rather than return a permissive default. The CLI maps that to a clean exit code 2 naming
the migration target; the API surfaces it as a handled error.

## Validating a migration

1. Implement the `onprem` adapters.
2. Keep `COMPLAINTS_PROFILE=onprem` and run the full gate: `make test`, `python
   eval/run_eval.py`. The contract test already passes; the unit tests use fakes, so add
   integration tests against your on-premise services under the `integration` marker.
3. Run the API and exercise `POST /v1/review` end to end against a synthetic complaint file.
4. Confirm residency, WORM immutability and redaction with your own controls.
